"""One-off script to import legacy database.json and locations.json into the current database.

Reads ``existing_db_samples/database.json`` and creates:
- Legacy accounts (claimable, PENDING_APPROVAL) from the ``Users`` array
- Mealbot receipts from the ``Reciepts`` array

Reads ``existing_db_samples/locations.json`` and creates:
- Happy hour locations from the location entries
- Happy hour events from the ``Occasions`` arrays

Usage::

    cd backend
    DATABASE_URI=sqlite:///data/app.db python -m scripts.import_legacy_db

Or with the venv explicitly::

    cd backend
    DATABASE_URI=sqlite:///data/app.db .venv/bin/python -m scripts.import_legacy_db
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the backend package root is on sys.path so ORM imports work
# when invoked as ``python -m scripts.import_legacy_db`` from backend/.
_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from db import Database  # noqa: E402
from models.account import Account  # noqa: E402
from models.enums import (  # noqa: E402
    AccountClaims,
    AccountStatus,
    ExternalAuthProvider,
    PhoneProvider,
)
from models.happyhour.event import Event  # noqa: E402
from models.happyhour.location import Location  # noqa: E402
from models.mealbot import Receipt  # noqa: E402

DATA_FILE = _backend_root / "existing_db_samples" / "database.json"
LOCATIONS_FILE = _backend_root / "existing_db_samples" / "locations.json"
LEGACY_PREFIX = "legacy-"


def _parse_datetime(raw: str) -> datetime:
    """Parse ISO-8601 datetime strings with varying timezone formats.

    The legacy data contains timestamps with nanosecond precision and
    mixed timezone representations (``Z``, ``+00:00``, ``-07:00``,
    ``-08:00``).  Python's ``fromisoformat`` handles most of these
    after truncating sub-microsecond digits.
    """
    # Replace trailing Z with +00:00 for fromisoformat compatibility
    s = raw.replace("Z", "+00:00")

    # Truncate nanoseconds to microseconds (6 digits after the dot)
    # e.g. ".1228698Z" → ".122869" (keep 6 digits before the tz offset)
    dot_idx = s.find(".")
    if dot_idx != -1:
        # Find where the fractional seconds end (start of +/- offset)
        tz_idx = -1
        for i in range(dot_idx + 1, len(s)):
            if s[i] in ("+", "-"):
                tz_idx = i
                break
        if tz_idx == -1:
            # No timezone offset found after dot — shouldn't happen
            frac = s[dot_idx + 1 :]
            s = s[: dot_idx + 1] + frac[:6]
        else:
            frac = s[dot_idx + 1 : tz_idx]
            s = s[: dot_idx + 1] + frac[:6] + s[tz_idx:]

    dt = datetime.fromisoformat(s)
    # Normalise to UTC
    return dt.astimezone(timezone.utc)


# ── Address pattern: "123 Street Name, City, ST 98052" ───────────────
# Some addresses have a building prefix like "Pike Motorworks Building, "
# or a suite suffix like "#100".  We extract number, street, city, state,
# zip from the *last 3* comma-separated segments.
_ADDR_RE = re.compile(
    r"(\d+)\s+"  # street number
    r"(.+?),\s*"  # street name (up to comma)
    r"(.+?),\s*"  # city
    r"([A-Z]{2})\s+"  # state abbreviation
    r"(\d{5})"  # zip code
)


def _parse_address(raw: str) -> dict[str, str | int]:
    """Best-effort parse of a US address string into components.

    Returns a dict with keys: number, street_name, city, state, zip_code.
    Falls back to storing the entire string as street_name if parsing fails.
    """
    m = _ADDR_RE.search(raw)
    if m:
        return {
            "number": int(m.group(1)),
            "street_name": m.group(2).strip(),
            "city": m.group(3).strip(),
            "state": m.group(4),
            "zip_code": m.group(5),
        }
    # Fallback: unparseable address
    return {
        "number": 0,
        "street_name": raw,
        "city": "",
        "state": "",
        "zip_code": "",
    }


def _compute_week_of(when: datetime) -> str:
    """Compute ISO year-week string for an event date."""
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _import_locations(session, upn_to_account: dict[str, Account]) -> tuple[int, int]:
    """Import happy hour locations and their occasion history.

    Returns (locations_imported, events_imported).
    """
    if not LOCATIONS_FILE.exists():
        print(f"WARNING: Locations file not found: {LOCATIONS_FILE}", file=sys.stderr)
        return 0, 0

    with open(LOCATIONS_FILE, "r", encoding="utf-8") as f:
        locations_raw = json.load(f)

    print(f"Found {len(locations_raw)} locations in {LOCATIONS_FILE.name}")

    locations_imported = 0
    events_imported = 0
    events_skipped = 0
    seen_weeks: set[str] = set()

    for loc_data in locations_raw:
        addr = _parse_address(loc_data["Location"]["Address"])
        loc = Location(
            Name=loc_data["Name"],
            Closed=loc_data.get("Defunct", False),
            Illegal=False,
            URL=None,
            AddressRaw=loc_data["Location"]["Address"],
            Number=addr["number"],
            StreetName=addr["street_name"],
            City=addr["city"],
            State=addr["state"],
            ZipCode=addr["zip_code"],
            Latitude=loc_data["Location"]["Coordinates"]["Lat"],
            Longitude=loc_data["Location"]["Coordinates"]["Long"],
        )
        session.add(loc)
        session.flush()  # assign loc.id
        locations_imported += 1

        for occasion in loc_data.get("Occasions", []):
            date_str = occasion["Date"]
            when = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            week_of = _compute_week_of(when)

            if week_of in seen_weeks:
                print(
                    f"WARNING: Skipping duplicate week {week_of} "
                    f"for {loc_data['Name']} on {date_str}"
                )
                events_skipped += 1
                continue
            seen_weeks.add(week_of)

            # Resolve organizer to account ID if possible
            organizer = occasion.get("Organizer", "").strip()
            tyrant_id = None
            if organizer and organizer in upn_to_account:
                tyrant_id = upn_to_account[organizer].id

            event = Event(
                LocationID=loc.id,
                When=when,
                week_of=week_of,
                TyrantID=tyrant_id,
                AutoSelected=tyrant_id is None,
            )
            session.add(event)
            events_imported += 1

    session.flush()

    if events_skipped:
        print(f"  Events skipped (duplicate weeks): {events_skipped}")

    return locations_imported, events_imported


def main() -> None:
    """Load legacy data and import accounts + receipts."""
    if not DATA_FILE.exists():
        print(f"ERROR: Data file not found: {DATA_FILE}", file=sys.stderr)
        sys.exit(1)

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    users = data["Users"]
    receipts_raw = data["Reciepts"]

    print(
        f"Found {len(users)} users and {len(receipts_raw)} receipts in {DATA_FILE.name}"
    )

    # Build ID → UPN mapping
    id_to_upn: dict[int, str] = {}
    for user in users:
        id_to_upn[user["ID"]] = user["UPN"]

    db = Database()
    db.start()

    try:
        with db.session() as session:
            # ── Step 1: Check for existing accounts ──
            existing = set()
            for upn in id_to_upn.values():
                act = session.query(Account).filter(Account.username == upn).first()
                if act is not None:
                    existing.add(upn)

            if existing:
                print(
                    f"ERROR: {len(existing)} account(s) already exist: "
                    f"{', '.join(sorted(existing))}",
                    file=sys.stderr,
                )
                sys.exit(1)

            # ── Step 2: Create legacy accounts ──
            upn_to_account: dict[str, Account] = {}
            for user in users:
                upn = user["UPN"]
                act = Account(
                    username=upn,
                    email=None,
                    phone=None,
                    phone_provider=PhoneProvider.NONE,
                    account_provider=ExternalAuthProvider.test,
                    external_unique_id=f"{LEGACY_PREFIX}{upn}",
                    claims=AccountClaims.BASIC | AccountClaims.MEALBOT,
                    status=AccountStatus.PENDING_APPROVAL,
                )
                session.add(act)
                upn_to_account[upn] = act

            # Flush to assign IDs
            session.flush()

            # Build legacy-ID → DB-ID mapping
            id_to_db_id: dict[int, int] = {}
            for user in users:
                id_to_db_id[user["ID"]] = upn_to_account[user["UPN"]].id

            # ── Step 3: Import receipts ──
            imported = 0
            skipped = 0
            for r in receipts_raw:
                # Legacy semantics: "Payer" = person who owes (meal recipient),
                # "Payee" = person who paid the bill.  Our model is the
                # opposite: PayerId = person who paid, RecipientId = meal
                # recipient.  So we swap them.
                payer_legacy_id = r["Payee"]
                payee_legacy_id = r["Payer"]

                if payer_legacy_id == payee_legacy_id:
                    payer_upn = id_to_upn.get(payer_legacy_id, f"ID={payer_legacy_id}")
                    print(f"WARNING: Skipping self-payment by {payer_upn}")
                    skipped += 1
                    continue

                payer_db_id = id_to_db_id.get(payer_legacy_id)
                payee_db_id = id_to_db_id.get(payee_legacy_id)

                if payer_db_id is None or payee_db_id is None:
                    payer_upn = id_to_upn.get(payer_legacy_id, f"ID={payer_legacy_id}")
                    payee_upn = id_to_upn.get(payee_legacy_id, f"ID={payee_legacy_id}")
                    print(
                        f"WARNING: Skipping receipt with unknown user: "
                        f"Payer={payer_upn} Payee={payee_upn}"
                    )
                    skipped += 1
                    continue

                receipt = Receipt(
                    Credits=r["NumMeals"],
                    Time=_parse_datetime(r["DateTime"]),
                    PayerId=payer_db_id,
                    RecipientId=payee_db_id,
                    RecorderId=None,
                )
                session.add(receipt)
                imported += 1

            # ── Step 4: Import locations and events ──
            locs_imported, events_imported = _import_locations(session, upn_to_account)

            session.commit()

        print("\nImport complete:")
        print(f"  Accounts created: {len(users)}")
        print(f"  Receipts imported: {imported}")
        if skipped:
            print(f"  Receipts skipped: {skipped}")
        print(f"  Locations imported: {locs_imported}")
        print(f"  Events imported: {events_imported}")

    finally:
        db.stop()


if __name__ == "__main__":
    main()
