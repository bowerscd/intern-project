"""End-to-end scenario tests for the happy hour flow."""

from datetime import datetime, UTC, timedelta
from starlette.testclient import TestClient


LOCATION = {
    "name": "The Portland Pub",
    "url": "https://portlandpub.com",
    "address_raw": "456 Oak Ave, Portland, OR 97201",
    "number": 456,
    "street_name": "Oak Ave",
    "city": "Portland",
    "state": "OR",
    "zip_code": "97201",
    "latitude": 45.52,
    "longitude": -122.67,
}


class TestHappyHourFlow:
    """Full scenario: locations + events lifecycle."""

    def test_full_happy_hour_lifecycle(self, authenticated_client: TestClient) -> None:
        """Verify the full lifecycle: create location, schedule event, and close.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        c = authenticated_client

        # 1. Create a location
        r = c.post("/api/v2/happyhour/locations", json=LOCATION)
        assert r.status_code == 201
        loc = r.json()
        loc_id = loc["id"]

        # 2. List locations
        r = c.get("/api/v2/happyhour/locations")
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 1

        # 3. Schedule an event
        event_when = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        r = c.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc_id,
                "description": "Weekly happy hour!",
                "when": event_when,
            },
        )
        assert r.status_code == 201
        event = r.json()
        assert event["location_name"] == "The Portland Pub"
        assert event["auto_selected"] is False

        # 4. Check upcoming
        r = c.get("/api/v2/happyhour/events/upcoming")
        assert r.status_code == 200

        # 5. Get event by ID
        r = c.get(f"/api/v2/happyhour/events/{event['id']}")
        assert r.status_code == 200
        assert r.json()["description"] == "Weekly happy hour!"

        # 6. Close location
        r = c.patch(f"/api/v2/happyhour/locations/{loc_id}", json={"closed": True})
        assert r.status_code == 200
        assert r.json()["closed"] is True

        # 7. Can't create event at closed location (or same week as existing event)
        r = c.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc_id,
                "when": event_when,
            },
        )
        assert r.status_code in (400, 409)

    def test_multiple_locations_and_events(
        self, authenticated_client: TestClient
    ) -> None:
        """Verify events can span multiple locations.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        c = authenticated_client

        loc1 = LOCATION.copy()
        loc1["name"] = "Bar One"
        loc2 = LOCATION.copy()
        loc2["name"] = "Bar Two"

        r1 = c.post("/api/v2/happyhour/locations", json=loc1)
        r2 = c.post("/api/v2/happyhour/locations", json=loc2)

        loc1_id = r1.json()["id"]
        loc2_id = r2.json()["id"]

        # Create events at both
        t1 = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        t2 = (datetime.now(UTC) + timedelta(days=10)).isoformat()

        c.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc1_id,
                "when": t1,
            },
        )
        c.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc2_id,
                "when": t2,
            },
        )

        # Verify event list
        r = c.get("/api/v2/happyhour/events")
        assert r.status_code == 200
        events = r.json()["items"]
        assert len(events) >= 2
