"""One-off script to fix production database after deploying updated code.

Fixes data while preserving real user accounts and user-created locations:

- **receipts** — origin import had Payer/Payee swapped (lesson 071).
  Drop table, re-create, re-import from database.json with correct mapping.
- **HappyHourTyrantRotation** — drop and re-create (no legacy data).
- **HappyHourLocations / HappyHourEvents** — additive import from
  locations.json.  Skips locations whose Name already exists and events
  whose week_of is already taken.  User-created data is preserved.

Also grants HAPPY_HOUR claims to legacy accounts (BASIC|MEALBOT only).

Tables **not touched**: ``accounts``, ``account_claim_requests``,
``alembic_version``.

Usage::

    cd backend
    DATABASE_URI=<prod-db-uri> python -m scripts.fixup_production --dry-run
    DATABASE_URI=<prod-db-uri> python -m scripts.fixup_production

Or with the venv explicitly::

    cd backend
    DATABASE_URI=<prod-db-uri> .venv/bin/python -m scripts.fixup_production
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

# Ensure the backend package root is on sys.path
_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from db import Database  # noqa: E402
from models.account import Account  # noqa: E402
from models.database import Model  # noqa: E402
from models.enums import AccountClaims  # noqa: E402
from models.happyhour.event import Event  # noqa: E402
from models.happyhour.location import Location  # noqa: E402
from models.happyhour.rotation import TyrantRotation  # noqa: E402, F401
from models.mealbot import Receipt  # noqa: E402

DATA_FILE = _backend_root / "existing_db_samples" / "database.json"
LOCATIONS_FILE = _backend_root / "existing_db_samples" / "locations.json"
LEGACY_PREFIX = "legacy-"

# Tables to drop and recreate (receipts are all wrong, rotation is empty)
_DROP_TABLES = [
    "HappyHourTyrantRotation",
    "receipts",
]

# ── Address parsing (shared with import_legacy_db.py) ─────────────────
_ADDR_RE = re.compile(
    r"(\d+)\s+"  # street number
    r"(.+?),\s*"  # street name
    r"(.+?),\s*"  # city
    r"([A-Z]{2})\s+"  # state
    r"(\d{5})"  # zip
)


def _parse_address(raw: str) -> dict[str, str | int]:
    m = _ADDR_RE.search(raw)
    if m:
        return {
            "number": int(m.group(1)),
            "street_name": m.group(2).strip(),
            "city": m.group(3).strip(),
            "state": m.group(4),
            "zip_code": m.group(5),
        }
    return {"number": 0, "street_name": raw, "city": "", "state": "", "zip_code": ""}


def _compute_week_of(when: datetime) -> str:
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _parse_datetime(raw: str) -> datetime:
    """Parse ISO-8601 with nanosecond precision and mixed TZ formats."""
    s = raw.replace("Z", "+00:00")
    dot_idx = s.find(".")
    if dot_idx != -1:
        tz_idx = -1
        for i in range(dot_idx + 1, len(s)):
            if s[i] in ("+", "-"):
                tz_idx = i
                break
        if tz_idx == -1:
            frac = s[dot_idx + 1 :]
            s = s[: dot_idx + 1] + frac[:6]
        else:
            frac = s[dot_idx + 1 : tz_idx]
            s = s[: dot_idx + 1] + frac[:6] + s[tz_idx:]
    return datetime.fromisoformat(s).astimezone(timezone.utc)


# ── Step functions ────────────────────────────────────────────────────


def drop_and_recreate_tables(session, *, dry_run: bool) -> None:
    """Drop receipts + rotation tables and recreate from ORM metadata.

    Locations and events are NOT dropped — they may contain user-created
    data.  Those tables are populated additively by import_locations().
    """
    for table_name in _DROP_TABLES:
        if dry_run:
            print(f"    [DRY RUN] Would DROP TABLE IF EXISTS {table_name}")
        else:
            session.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
            print(f"    Dropped {table_name}")

    if not dry_run:
        session.commit()
        # Recreate dropped tables + ensure location/event tables exist
        engine = session.get_bind()
        tables_to_create = [
            Model.metadata.tables[t]
            for t in [
                "HappyHourLocations",
                "HappyHourEvents",
                "HappyHourTyrantRotation",
                "receipts",
            ]
        ]
        Model.metadata.create_all(engine, tables=tables_to_create)
        print("    Recreated tables from ORM metadata.")


def import_receipts(
    session,
    id_to_db_id: dict[int, int],
    id_to_upn: dict[int, str],
    *,
    dry_run: bool,
) -> int:
    """Import receipts from database.json with correct Payer/Payee mapping."""
    if not DATA_FILE.exists():
        print(f"  ERROR: {DATA_FILE} not found.", file=sys.stderr)
        return 0

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    receipts_raw = data["Reciepts"]
    print(f"  Found {len(receipts_raw)} receipts in {DATA_FILE.name}")

    imported = 0
    skipped = 0
    for r in receipts_raw:
        # Legacy semantics inverted: Payee = person who paid, Payer = person fed
        payer_legacy_id = r["Payee"]
        recipient_legacy_id = r["Payer"]

        if payer_legacy_id == recipient_legacy_id:
            skipped += 1
            continue

        payer_db_id = id_to_db_id.get(payer_legacy_id)
        recipient_db_id = id_to_db_id.get(recipient_legacy_id)

        if payer_db_id is None or recipient_db_id is None:
            payer_upn = id_to_upn.get(payer_legacy_id, f"ID={payer_legacy_id}")
            recip_upn = id_to_upn.get(recipient_legacy_id, f"ID={recipient_legacy_id}")
            print(
                f"  WARNING: Skipping receipt — unknown user: {payer_upn} / {recip_upn}"
            )
            skipped += 1
            continue

        if dry_run:
            if imported < 5:
                print(
                    f"    [DRY RUN] Receipt: Payer={id_to_upn[payer_legacy_id]} "
                    f"→ Recipient={id_to_upn[recipient_legacy_id]} "
                    f"x{r['NumMeals']}"
                )
            imported += 1
            continue

        session.add(
            Receipt(
                Credits=r["NumMeals"],
                Time=_parse_datetime(r["DateTime"]),
                PayerId=payer_db_id,
                RecipientId=recipient_db_id,
                RecorderId=None,
            )
        )
        imported += 1

    if not dry_run:
        session.flush()

    if skipped:
        print(f"  Receipts skipped: {skipped}")
    return imported


def import_locations(
    session, upn_to_account: dict[str, Account], *, dry_run: bool
) -> tuple[int, int]:
    """Additively import locations and events from locations.json.

    Skips locations whose Name already exists in the DB and events
    whose week_of is already taken.  This preserves any data created
    by real users through the app.
    """
    if not LOCATIONS_FILE.exists():
        print(f"  WARNING: {LOCATIONS_FILE} not found. Skipping.", file=sys.stderr)
        return 0, 0

    with open(LOCATIONS_FILE, "r", encoding="utf-8") as f:
        locations_raw = json.load(f)

    print(f"  Found {len(locations_raw)} locations in {LOCATIONS_FILE.name}")

    # Pre-load existing names and weeks to detect duplicates
    existing_names: set[str] = {row[0] for row in session.query(Location.Name).all()}
    existing_weeks: set[str] = {row[0] for row in session.query(Event.week_of).all()}
    # Track weeks we add in this run too (for intra-file dedup)
    seen_weeks = set(existing_weeks)

    if existing_names:
        print(f"  {len(existing_names)} location(s) already exist — will skip dupes.")
    if existing_weeks:
        print(f"  {len(existing_weeks)} event week(s) already exist — will skip dupes.")

    locations_imported = 0
    locations_skipped = 0
    events_imported = 0
    events_skipped = 0

    for loc_data in locations_raw:
        loc_name = loc_data["Name"]

        if loc_name in existing_names:
            if dry_run:
                print(f"    [DRY RUN] SKIP existing location: {loc_name}")
            locations_skipped += 1
            # Still need to track occasion weeks for this location
            # in case a user re-created the same venue
            existing_loc = (
                session.query(Location).filter(Location.Name == loc_name).first()
            )
            loc_id = existing_loc.id if existing_loc else None
            for occasion in loc_data.get("Occasions", []):
                when = datetime.strptime(occasion["Date"], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                week_of = _compute_week_of(when)
                if week_of in seen_weeks:
                    events_skipped += 1
                    continue
                seen_weeks.add(week_of)
                if loc_id is None:
                    events_skipped += 1
                    continue
                organizer = occasion.get("Organizer", "").strip()
                tyrant_id = None
                if organizer and organizer in upn_to_account:
                    tyrant_id = upn_to_account[organizer].id
                if dry_run:
                    print(
                        f"    [DRY RUN] Would add event {week_of} "
                        f"to existing location {loc_name}"
                    )
                else:
                    session.add(
                        Event(
                            LocationID=loc_id,
                            When=when,
                            week_of=week_of,
                            TyrantID=tyrant_id,
                            AutoSelected=tyrant_id is None,
                        )
                    )
                events_imported += 1
            continue

        addr = _parse_address(loc_data["Location"]["Address"])

        if dry_run:
            print(f"    [DRY RUN] Would create location: {loc_name}")
            locations_imported += 1
            for occasion in loc_data.get("Occasions", []):
                week_of = _compute_week_of(
                    datetime.strptime(occasion["Date"], "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                )
                if week_of in seen_weeks:
                    events_skipped += 1
                    continue
                seen_weeks.add(week_of)
                events_imported += 1
            continue

        loc = Location(
            Name=loc_name,
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
        session.flush()
        locations_imported += 1

        for occasion in loc_data.get("Occasions", []):
            date_str = occasion["Date"]
            when = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            week_of = _compute_week_of(when)

            if week_of in seen_weeks:
                events_skipped += 1
                continue
            seen_weeks.add(week_of)

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

    if not dry_run:
        session.flush()

    if locations_skipped:
        print(f"  Locations skipped (already exist): {locations_skipped}")
    if events_skipped:
        print(f"  Events skipped (duplicate weeks): {events_skipped}")

    return locations_imported, events_imported


def grant_happy_hour_claims(session, *, dry_run: bool) -> int:
    """Grant HAPPY_HOUR to all legacy accounts that have MEALBOT but not HAPPY_HOUR."""
    legacy_accounts = (
        session.query(Account)
        .filter(Account.external_unique_id.startswith(LEGACY_PREFIX))
        .all()
    )

    upgraded = 0
    for act in legacy_accounts:
        if not (act.claims & AccountClaims.HAPPY_HOUR):
            if dry_run:
                print(
                    f"    [DRY RUN] Would grant HAPPY_HOUR to {act.username} "
                    f"(current claims: {act.claims})"
                )
            else:
                act.claims = act.claims | AccountClaims.HAPPY_HOUR
            upgraded += 1

    if not dry_run and upgraded:
        session.flush()

    return upgraded


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix production database after code update deployment."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying the database.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN MODE — no changes will be made ===\n")

    # ── Load legacy user ID mappings ──
    if not DATA_FILE.exists():
        print(f"ERROR: {DATA_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    id_to_upn: dict[int, str] = {u["ID"]: u["UPN"] for u in data["Users"]}

    db = Database()
    db.start()

    try:
        with db.session() as session:
            # Build UPN → Account mapping (for all accounts, not just legacy)
            all_accounts = session.query(Account).all()
            upn_to_account = {act.username: act for act in all_accounts}
            print(f"Found {len(all_accounts)} accounts in database.\n")

            # Build legacy-ID → DB-ID mapping
            id_to_db_id: dict[int, int] = {}
            for legacy_id, upn in id_to_upn.items():
                if upn in upn_to_account:
                    id_to_db_id[legacy_id] = upn_to_account[upn].id
                else:
                    print(f"  WARNING: Legacy user {upn} not found in accounts table")

            # ── Step 1: Drop and recreate receipts + rotation ──
            print("Step 1: Dropping receipts + rotation tables...")
            drop_and_recreate_tables(session, dry_run=args.dry_run)

            # ── Step 2: Re-import receipts with correct payer/payee ──
            print("\nStep 2: Importing receipts (corrected payer/payee mapping)...")
            receipts_count = import_receipts(
                session, id_to_db_id, id_to_upn, dry_run=args.dry_run
            )

            # ── Step 3: Additive import of locations & events ──
            print("\nStep 3: Importing locations and events (additive)...")
            locs, events = import_locations(
                session, upn_to_account, dry_run=args.dry_run
            )

            # ── Step 4: Grant HAPPY_HOUR claims ──
            print("\nStep 4: Granting HAPPY_HOUR claims to legacy accounts...")
            upgraded = grant_happy_hour_claims(session, dry_run=args.dry_run)

            if not args.dry_run:
                session.commit()

        print("\n" + ("=== DRY RUN " if args.dry_run else "") + "Summary:")
        print(f"  Receipts imported: {receipts_count}")
        print(f"  Locations imported: {locs}")
        print(f"  Events imported: {events}")
        print(f"  Accounts granted HAPPY_HOUR: {upgraded}")

        if args.dry_run:
            print("\nRe-run without --dry-run to apply changes.")

    finally:
        db.stop()


if __name__ == "__main__":
    main()
