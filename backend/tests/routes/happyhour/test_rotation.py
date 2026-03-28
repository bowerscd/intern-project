"""Tests for the GET /api/v2/happyhour/rotation endpoint.

Covers response structure, multi-user visibility, projected weeks
accuracy, and rotation state transitions — gaps that allowed display
bugs to reach production.
"""

from datetime import datetime, UTC, timedelta

from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from app import app, secret
from db.functions import (
    create_account,
    create_tyrant_assignment,
)
from models import (
    AccountClaims,
    AccountStatus,
    ExternalAuthProvider,
    TyrantAssignmentStatus,
)
from tests.conftest import _mk_auth_cookie
from ratelimit import limiter


def _make_user(
    s: Session,
    name: str,
    claims: AccountClaims = AccountClaims.HAPPY_HOUR | AccountClaims.HAPPY_HOUR_TYRANT,
):
    act = create_account(
        name,
        f"{name}@test.com",
        ExternalAuthProvider.test,
        name,
        claims=claims,
    )
    act.status = AccountStatus.ACTIVE
    s.add(act)
    s.commit()
    return act


class TestRotationEndpoint:
    """Verify GET /api/v2/happyhour/rotation response structure and accuracy."""

    def test_rotation_response_structure(
        self, authenticated_client: TestClient
    ) -> None:
        """Response contains cycle number and members list."""
        r = authenticated_client.get("/api/v2/happyhour/rotation")
        assert r.status_code == 200
        data = r.json()
        assert "cycle" in data
        assert "members" in data
        assert isinstance(data["members"], list)

    def test_rotation_member_fields(self, db_session: Session) -> None:
        """Each member contains position, username, status, and deadline."""
        alice = _make_user(db_session, "rot_alice")
        bob = _make_user(db_session, "rot_bob")

        now = datetime.now(UTC)
        deadline = now + timedelta(days=5)

        create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=deadline,
            status=TyrantAssignmentStatus.CURRENT,
        )
        create_tyrant_assignment(
            db_session,
            bob.id,
            cycle=1,
            position=1,
            assigned_at=now,
        )
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, alice.id))
            r = c.get("/api/v2/happyhour/rotation")

        assert r.status_code == 200
        members = r.json()["members"]
        assert len(members) == 2

        # Verify field presence on every member
        for m in members:
            assert "position" in m
            assert "username" in m
            assert "status" in m
            assert "deadline" in m

        # Current member has deadline, scheduled does not
        current_m = [m for m in members if m["status"] == "current"][0]
        assert current_m["deadline"] is not None
        assert current_m["username"] == "rot_alice"

        scheduled_m = [m for m in members if m["status"] == "scheduled"][0]
        assert scheduled_m["deadline"] is None
        assert scheduled_m["username"] == "rot_bob"

    def test_multiple_users_see_same_rotation(self, db_session: Session) -> None:
        """All users see the identical rotation schedule."""
        alice = _make_user(db_session, "view_alice")
        bob = _make_user(db_session, "view_bob")

        now = datetime.now(UTC)
        create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        create_tyrant_assignment(
            db_session,
            bob.id,
            cycle=1,
            position=1,
            assigned_at=now,
        )
        db_session.commit()

        limiter.reset()

        # alice's view
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, alice.id))
            r_alice = c.get("/api/v2/happyhour/rotation")

        limiter.reset()

        # bob's view
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, bob.id))
            r_bob = c.get("/api/v2/happyhour/rotation")

        assert r_alice.status_code == 200
        assert r_bob.status_code == 200
        assert r_alice.json() == r_bob.json()

    def test_upcoming_current_tyrant_consistency(self, db_session: Session) -> None:
        """Both users see the same current_tyrant_username on /events/upcoming."""
        alice = _make_user(db_session, "ct_alice")
        bob = _make_user(db_session, "ct_bob")

        now = datetime.now(UTC)
        create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        db_session.commit()

        limiter.reset()

        # alice checks upcoming
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, alice.id))
            r_alice = c.get("/api/v2/happyhour/events/upcoming")

        limiter.reset()

        # bob checks upcoming
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, bob.id))
            r_bob = c.get("/api/v2/happyhour/events/upcoming")

        assert r_alice.status_code == 200
        assert r_bob.status_code == 200

        # Both should see alice as the current tyrant
        assert r_alice.json()["current_tyrant_username"] == "ct_alice"
        assert r_bob.json()["current_tyrant_username"] == "ct_alice"

    def test_rotation_reflects_status_transitions(self, db_session: Session) -> None:
        """After an assignment is marked CHOSEN, the rotation reflects the change."""
        alice = _make_user(db_session, "trans_alice")

        now = datetime.now(UTC)
        assignment = create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, alice.id))

            r = c.get("/api/v2/happyhour/rotation")
            assert r.json()["members"][0]["status"] == "current"

        # Mark as chosen
        from db.functions import mark_assignment_chosen

        mark_assignment_chosen(db_session, assignment.id)
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, alice.id))

            r = c.get("/api/v2/happyhour/rotation")
            assert r.json()["members"][0]["status"] == "chosen"


class TestRegenerateRotation:
    """Verify POST /api/v2/happyhour/rotation/regenerate."""

    def test_requires_admin(self, db_session: Session) -> None:
        """Non-admin users are rejected with 403."""
        alice = _make_user(db_session, "regen_alice")
        now = datetime.now(UTC)
        create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, alice.id))
            r = c.post("/api/v2/happyhour/rotation/regenerate")
        assert r.status_code == 403

    def test_regenerate_creates_new_cycle(self, db_session: Session) -> None:
        """Regeneration creates a new cycle with all tyrants re-shuffled."""
        alice = _make_user(db_session, "regen2_alice")
        bob = _make_user(
            db_session,
            "regen2_bob",
            claims=AccountClaims.HAPPY_HOUR
            | AccountClaims.HAPPY_HOUR_TYRANT
            | AccountClaims.ADMIN,
        )

        now = datetime.now(UTC)
        create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        create_tyrant_assignment(
            db_session,
            bob.id,
            cycle=1,
            position=1,
            assigned_at=now,
        )
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, bob.id))
            r = c.post("/api/v2/happyhour/rotation/regenerate")

        assert r.status_code == 200
        data = r.json()
        assert data["cycle"] == 2
        assert len(data["members"]) == 2

        # New cycle should have one CURRENT member
        statuses = [m["status"] for m in data["members"]]
        assert "current" in statuses

        # Current member should have a deadline
        current_m = [m for m in data["members"] if m["status"] == "current"][0]
        assert current_m["deadline"] is not None

    def test_regenerate_marks_old_assignments_skipped(
        self, db_session: Session
    ) -> None:
        """Non-terminal assignments in the old cycle are marked SKIPPED."""
        from db.functions import get_rotation_schedule

        alice = _make_user(
            db_session,
            "regen3_alice",
            claims=AccountClaims.HAPPY_HOUR
            | AccountClaims.HAPPY_HOUR_TYRANT
            | AccountClaims.ADMIN,
        )
        bob = _make_user(db_session, "regen3_bob")

        now = datetime.now(UTC)
        create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        create_tyrant_assignment(
            db_session,
            bob.id,
            cycle=1,
            position=1,
            assigned_at=now,
        )
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, alice.id))
            r = c.post("/api/v2/happyhour/rotation/regenerate")
        assert r.status_code == 200

        # Check old cycle — both should be SKIPPED
        old_schedule = get_rotation_schedule(db_session, 1)
        for r in old_schedule:
            assert r.status == TyrantAssignmentStatus.SKIPPED

    def test_regenerate_no_tyrants_returns_400(self, db_session: Session) -> None:
        """If no HAPPY_HOUR_TYRANT users exist, returns 400."""
        from db.functions import create_account

        admin = create_account(
            "regen4_admin",
            "regen4@test.com",
            ExternalAuthProvider.test,
            "regen4_admin",
            claims=AccountClaims.ADMIN | AccountClaims.HAPPY_HOUR,
        )
        admin.status = AccountStatus.ACTIVE
        db_session.add(admin)
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, admin.id))
            r = c.post("/api/v2/happyhour/rotation/regenerate")
        assert r.status_code == 400
        assert "No HAPPY_HOUR_TYRANT" in r.json()["detail"]
