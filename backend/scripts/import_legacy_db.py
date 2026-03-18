"""One-off script to import legacy database.json into the current database.

Reads ``existing_db_samples/database.json`` and creates:
- Legacy accounts (claimable, PENDING_APPROVAL) from the ``Users`` array
- Mealbot receipts from the ``Reciepts`` array

Usage::

    cd backend
    DATABASE_URI=sqlite:///data/app.db python -m scripts.import_legacy_db

Or with the venv explicitly::

    cd backend
    DATABASE_URI=sqlite:///data/app.db .venv/bin/python -m scripts.import_legacy_db
"""

from __future__ import annotations

import json
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
from models.mealbot import Receipt  # noqa: E402

DATA_FILE = _backend_root / "existing_db_samples" / "database.json"
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

            session.commit()

        print("\nImport complete:")
        print(f"  Accounts created: {len(users)}")
        print(f"  Receipts imported: {imported}")
        if skipped:
            print(f"  Receipts skipped: {skipped}")

    finally:
        db.stop()


if __name__ == "__main__":
    main()
