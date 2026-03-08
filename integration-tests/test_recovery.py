"""Integration tests for disaster recovery workflows.

Tests the full recovery lifecycle through the API:
- Happy hour event cancellation and rescheduling
- Happy hour event update (change venue)
- Mealbot record voiding
- Rotation turn skipping

These tests require the full stack to be running (backend + OIDC).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta

import httpx
import pytest

from helpers import (
    oidc_register_session,
    complete_registration,
    activate_account,
    oidc_login,
    create_backend_client,
)


def _get_csrf(client: httpx.Client) -> str:
    """Fetch a CSRF token from the backend."""
    resp = client.get("/api/v2/auth/csrf-token")
    assert resp.status_code == 200
    return resp.json()["csrf_token"]


def _grant_claims(db_path: str, username: str, claims_int: int) -> None:
    """Set account claims directly in the database."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE accounts SET claims = ? WHERE username = ?",
            (claims_int, username),
        )
        conn.commit()
    finally:
        conn.close()


# AccountClaims bitmask values (from models/enums.py)
BASIC = 1
ADMIN = 2
MEALBOT = 4
HAPPY_HOUR = 16
HAPPY_HOUR_TYRANT = 32
ALL_CLAIMS = BASIC | ADMIN | MEALBOT | HAPPY_HOUR | HAPPY_HOUR_TYRANT


class TestHappyHourRecovery:
    """Test happy hour disaster recovery: cancel, update, reschedule."""

    def _setup_user(self, backend_url, oidc_issuer, db_path, username="recovery_user"):
        """Register, activate, and login a user with all claims."""
        reg_client = oidc_register_session(
            backend_url, oidc_issuer, sub=username, name=username, email=f"{username}@test.com"
        )
        complete_registration(reg_client, username)
        reg_client.close()
        activate_account(db_path, username)
        _grant_claims(db_path, username, ALL_CLAIMS)
        client = oidc_login(
            backend_url, oidc_issuer, sub=username, name=username, email=f"{username}@test.com"
        )
        return client

    def test_cancel_and_reschedule_event(self, backend_server, oidc_server, backend_db_path):
        """A tyrant creates an event, cancels it (wrong venue), then reschedules."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        client = self._setup_user(backend_url, oidc_issuer, backend_db_path, "cancel_test")
        csrf = _get_csrf(client)

        # Create a location
        resp = client.post(
            "/api/v2/happyhour/locations",
            json={
                "name": "Bad Venue",
                "address_raw": "1 Bad St, Portland, OR 97201",
                "number": 1, "street_name": "Bad St", "city": "Portland",
                "state": "OR", "zip_code": "97201", "latitude": 45.5, "longitude": -122.7,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201
        bad_loc_id = resp.json()["id"]

        # Create the event (at the wrong venue)
        next_week = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        resp = client.post(
            "/api/v2/happyhour/events",
            json={"location_id": bad_loc_id, "description": "Wrong place!", "when": next_week},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201
        event_id = resp.json()["id"]

        # Cancel the event
        csrf = _get_csrf(client)
        resp = client.delete(
            f"/api/v2/happyhour/events/{event_id}",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # Verify the event is gone
        resp = client.get(f"/api/v2/happyhour/events/{event_id}")
        assert resp.status_code == 404

        # Create a better location and reschedule
        csrf = _get_csrf(client)
        resp = client.post(
            "/api/v2/happyhour/locations",
            json={
                "name": "Good Venue",
                "address_raw": "2 Good St, Portland, OR 97201",
                "number": 2, "street_name": "Good St", "city": "Portland",
                "state": "OR", "zip_code": "97201", "latitude": 45.5, "longitude": -122.7,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201
        good_loc_id = resp.json()["id"]

        csrf = _get_csrf(client)
        resp = client.post(
            "/api/v2/happyhour/events",
            json={"location_id": good_loc_id, "description": "Better spot!", "when": next_week},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201
        assert resp.json()["location_name"] == "Good Venue"

        client.close()

    def test_update_event_venue(self, backend_server, oidc_server, backend_db_path):
        """A tyrant updates an event to change the venue (e.g., it closed at 4PM)."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        client = self._setup_user(backend_url, oidc_issuer, backend_db_path, "upd_test")
        csrf = _get_csrf(client)

        # Create two locations
        resp = client.post(
            "/api/v2/happyhour/locations",
            json={
                "name": "Closed At 4pm",
                "address_raw": "10 Early St, Portland, OR 97201",
                "number": 10, "street_name": "Early St", "city": "Portland",
                "state": "OR", "zip_code": "97201", "latitude": 45.5, "longitude": -122.7,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201
        bad_loc_id = resp.json()["id"]

        csrf = _get_csrf(client)
        resp = client.post(
            "/api/v2/happyhour/locations",
            json={
                "name": "Open Late",
                "address_raw": "20 Late St, Portland, OR 97201",
                "number": 20, "street_name": "Late St", "city": "Portland",
                "state": "OR", "zip_code": "97201", "latitude": 45.5, "longitude": -122.7,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201
        good_loc_id = resp.json()["id"]

        # Create event at the bad location
        csrf = _get_csrf(client)
        next_week = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        resp = client.post(
            "/api/v2/happyhour/events",
            json={"location_id": bad_loc_id, "when": next_week},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201
        event_id = resp.json()["id"]
        assert resp.json()["location_name"] == "Closed At 4pm"

        # Update the event to the better location
        csrf = _get_csrf(client)
        resp = client.patch(
            f"/api/v2/happyhour/events/{event_id}",
            json={"location_id": good_loc_id, "description": "Moved to Open Late!"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        assert resp.json()["location_name"] == "Open Late"
        assert resp.json()["description"] == "Moved to Open Late!"

        client.close()


class TestMealbotRecovery:
    """Test mealbot disaster recovery: void mistaken records."""

    def _setup_users(self, backend_url, oidc_issuer, db_path, suffix=""):
        """Create two users with MEALBOT claims."""
        users = {}
        for name in [f"meal_a{suffix}", f"meal_b{suffix}"]:
            reg_client = oidc_register_session(
                backend_url, oidc_issuer, sub=name, name=name, email=f"{name}@test.com"
            )
            complete_registration(reg_client, name)
            reg_client.close()
            activate_account(db_path, name)
            _grant_claims(db_path, name, BASIC | MEALBOT)
            client = oidc_login(
                backend_url, oidc_issuer, sub=name, name=name, email=f"{name}@test.com"
            )
            users[name] = client
        return users

    def test_void_mistaken_record(self, backend_server, oidc_server, backend_db_path):
        """User records a meal by mistake and voids it."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        users = self._setup_users(backend_url, oidc_issuer, backend_db_path, "_v1")
        client_a = users["meal_a_v1"]

        csrf = _get_csrf(client_a)
        resp = client_a.post(
            "/api/v2/mealbot/record",
            json={"payer": "meal_a_v1", "recipient": "meal_b_v1", "credits": 1},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200

        # Get the record ID from the ledger
        resp = client_a.get("/api/v2/mealbot/ledger")
        assert resp.status_code == 200
        records = resp.json()["items"]
        my_records = [r for r in records if r["payer"] == "meal_a_v1" and r["recipient"] == "meal_b_v1"]
        assert len(my_records) >= 1
        record_id = my_records[0]["id"]

        # Verify the record has an id field
        assert isinstance(record_id, int)

        # Void the record
        csrf = _get_csrf(client_a)
        resp = client_a.delete(
            f"/api/v2/mealbot/record/{record_id}",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "voided"

        # Verify it's gone from the ledger
        resp = client_a.get("/api/v2/mealbot/ledger/me")
        assert resp.status_code == 200
        remaining = [r for r in resp.json()["items"] if r["id"] == record_id]
        assert len(remaining) == 0

        for c in users.values():
            c.close()

    def test_void_by_other_party(self, backend_server, oidc_server, backend_db_path):
        """The recipient can also void a record."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        users = self._setup_users(backend_url, oidc_issuer, backend_db_path, "_v2")
        client_a = users["meal_a_v2"]
        client_b = users["meal_b_v2"]

        # A creates a record
        csrf = _get_csrf(client_a)
        resp = client_a.post(
            "/api/v2/mealbot/record",
            json={"payer": "meal_a_v2", "recipient": "meal_b_v2", "credits": 1},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200

        # B gets the record ID from their ledger
        resp = client_b.get("/api/v2/mealbot/ledger/me")
        assert resp.status_code == 200
        records = resp.json()["items"]
        my_records = [r for r in records if r["payer"] == "meal_a_v2" and r["recipient"] == "meal_b_v2"]
        assert len(my_records) >= 1
        record_id = my_records[0]["id"]

        # B voids the record (as the recipient)
        csrf = _get_csrf(client_b)
        resp = client_b.delete(
            f"/api/v2/mealbot/record/{record_id}",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "voided"

        for c in users.values():
            c.close()
