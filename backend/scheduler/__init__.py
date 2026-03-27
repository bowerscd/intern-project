"""
APScheduler jobs for happy hour tyrant rotation (v2 double-buffer pipeline).

Three cron jobs:

- **advance_rotation** (Friday 5PM PST): Advance the pipeline.
  CURRENT → finalized, ON_DECK → CURRENT, next PENDING → ON_DECK,
  next SCHEDULED → PENDING.  When the active buffer is exhausted,
  flip to the standby buffer and regenerate the exhausted one.

- **auto_select_happy_hour** (Wednesday noon PST): If the CURRENT
  person hasn't created an event, mark them MISSED, auto-select a
  random location, and create an event.

- **evaluate_strikes** (Friday 9AM PST): If the CURRENT person is
  still MISSED at this point, it counts as a strike.  Three consecutive
  strikes remove their HAPPY_HOUR_TYRANT claim.  Recovery window
  (Wed noon → Fri 9AM) closes here.
"""

import logging
from datetime import datetime, UTC, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.exc import IntegrityError
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None

PST = ZoneInfo("America/Los_Angeles")
CONSECUTIVE_MISS_LIMIT = 3


def get_scheduler() -> AsyncIOScheduler:
    """Return the global :class:`AsyncIOScheduler` singleton, creating it if needed."""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler


def _next_wednesday_noon(from_dt: datetime) -> datetime:
    """Calculate the next Wednesday 12:00 PM PST from a given datetime."""
    local = from_dt.astimezone(PST)
    days_until_wed = (2 - local.weekday()) % 7
    if days_until_wed == 0:
        if local.hour >= 12:
            days_until_wed = 7
    wed = local + timedelta(days=days_until_wed)
    return wed.replace(hour=12, minute=0, second=0, microsecond=0)


def _next_friday_5pm(from_dt: datetime) -> datetime:
    """Calculate the next Friday 5:00 PM PST from a given datetime."""
    local = from_dt.astimezone(PST)
    days_until_friday = (4 - local.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    friday = local + timedelta(days=days_until_friday)
    return friday.replace(hour=17, minute=0, second=0, microsecond=0)


async def advance_rotation() -> None:
    """Advance the rotation pipeline (Friday 5PM PST).

    Pipeline stages, processed in order:

    1. Finalize CURRENT: if CHOSEN or MISSED, leave as-is. If still
       CURRENT with an event this week, mark CHOSEN.
    2. ON_DECK → CURRENT (set Wednesday noon deadline).
    3. Next PENDING → ON_DECK (notify "you're up next").
    4. Next SCHEDULED → PENDING.
    5. If active buffer exhausted and no more SCHEDULED, flip to standby
       and regenerate the exhausted buffer.

    Idempotent — safe to run multiple times (lesson #087).
    """
    from db import Database
    from db.functions import (
        get_accounts_with_claim,
        get_current_cycle_number,
        get_current_active_assignment,
        get_current_on_deck_assignment,
        get_next_scheduled_assignment,
        get_next_pipeline_assignment,
        promote_to_on_deck,
        promote_to_current,
        activate_assignment,
        mark_assignment_chosen,
        get_events_this_week,
        create_standby_buffer,
        is_cycle_exhausted,
        get_last_resolved_account_in_cycle,
    )
    from models.enums import AccountClaims, TyrantAssignmentStatus

    now = datetime.now(UTC)

    try:
        with Database() as db:
            with db.session() as s:
                # --- Step 1: Finalize CURRENT ---
                current = get_current_active_assignment(s)
                current_resolved = current is None
                if current is not None:
                    if current.status == TyrantAssignmentStatus.CURRENT:
                        # Still CURRENT — check if an event was created
                        events = get_events_this_week(s, now)
                        if events:
                            mark_assignment_chosen(s, current.id)
                            current_resolved = True
                            logger.info(
                                "Finalized CURRENT %s → CHOSEN (event exists)",
                                current.Account.username,
                            )
                        else:
                            # No event, not MISSED yet — don't advance
                            logger.info(
                                "CURRENT %s still active (no event, not missed), "
                                "not advancing pipeline",
                                current.Account.username,
                            )
                    elif current.status == TyrantAssignmentStatus.MISSED:
                        # Already MISSED (strike evaluated at 9AM) — resolved
                        current_resolved = True

                # Only advance pipeline if CURRENT was resolved or absent
                new_current_username = None
                new_on_deck_username = None

                if current_resolved:
                    cycle = get_current_cycle_number(s)

                    # --- Step 2: SCHEDULED → PENDING (fill the queue) ---
                    scheduled = get_next_scheduled_assignment(s, cycle)
                    if scheduled is not None:
                        deadline = _next_wednesday_noon(now)
                        activate_assignment(s, scheduled.id, deadline)
                        logger.info(
                            "Activated SCHEDULED %s → PENDING (cycle %d, pos %d)",
                            scheduled.Account.username if scheduled.Account else "?",
                            cycle,
                            scheduled.position,
                        )

                    # --- Step 3: PENDING → ON_DECK ---
                    next_pending = get_next_pipeline_assignment(s, cycle)
                    if next_pending is not None:
                        promote_to_on_deck(s, next_pending.id)
                        s.refresh(next_pending)
                        new_on_deck_username = next_pending.Account.username
                        logger.info(
                            "Promoted PENDING %s → ON_DECK",
                            new_on_deck_username,
                        )

                    # --- Step 4: ON_DECK → CURRENT ---
                    on_deck = get_current_on_deck_assignment(s)
                    if on_deck is not None:
                        deadline = _next_wednesday_noon(now)
                        promote_to_current(s, on_deck.id, deadline)
                        s.refresh(on_deck)
                        new_current_username = on_deck.Account.username

                        # Ensure CURRENT tyrant also has HAPPY_HOUR claim
                        tyrant = on_deck.Account
                        if not (tyrant.claims & AccountClaims.HAPPY_HOUR):
                            from db.functions import update_account_claims

                            update_account_claims(
                                s,
                                tyrant.id,
                                tyrant.claims | AccountClaims.HAPPY_HOUR,
                            )

                        logger.info(
                            "Promoted ON_DECK %s → CURRENT (deadline %s)",
                            new_current_username,
                            deadline,
                        )

                    # --- Step 5: Buffer flip if exhausted ---
                    if new_current_username is None and is_cycle_exhausted(s, cycle):
                        admins = get_accounts_with_claim(
                            s, AccountClaims.HAPPY_HOUR_TYRANT
                        )
                        if admins:
                            last_account = get_last_resolved_account_in_cycle(s, cycle)
                            new_cycle = cycle + 1
                            rotations = create_standby_buffer(
                                s,
                                list(admins),
                                new_cycle,
                                now,
                                last_account_id=last_account,
                            )
                            logger.info(
                                "Created new buffer cycle %d with %d members "
                                "(back-to-back prevention: last=%s)",
                                new_cycle,
                                len(rotations),
                                last_account,
                            )

                            # Seed the pipeline: first → CURRENT, second → ON_DECK
                            if len(rotations) >= 1:
                                deadline = _next_wednesday_noon(now)
                                promote_to_current(s, rotations[0].id, deadline)
                                new_current_username = rotations[0].Account.username
                            if len(rotations) >= 2:
                                promote_to_on_deck(s, rotations[1].id)
                                new_on_deck_username = rotations[1].Account.username
                            if len(rotations) >= 3:
                                activate_assignment(
                                    s,
                                    rotations[2].id,
                                    _next_wednesday_noon(now),
                                )
                        else:
                            logger.warning(
                                "No HAPPY_HOUR_TYRANT users found for rotation"
                            )

                s.commit()

            # --- Notifications (outside DB transaction) ---
            if new_current_username is not None:
                try:
                    with db.session() as s2:
                        from db.functions import get_current_active_assignment

                        fresh_current = get_current_active_assignment(s2)
                        if fresh_current is not None:
                            from mail.outgoing import notify_tyrant_assigned

                            await notify_tyrant_assigned(
                                fresh_current.Account,
                                fresh_current.deadline_at,
                            )
                except Exception as e:
                    logger.error("Failed to notify current tyrant: %s", e)

            if new_on_deck_username is not None:
                try:
                    with db.session() as s2:
                        from db.functions import get_current_on_deck_assignment

                        fresh_on_deck = get_current_on_deck_assignment(s2)
                        if fresh_on_deck is not None:
                            from mail.outgoing import notify_tyrant_on_deck

                            await notify_tyrant_on_deck(
                                fresh_on_deck.Account,
                                new_current_username or "unknown",
                            )
                except Exception as e:
                    logger.error("Failed to notify on-deck user: %s", e)

    except Exception:
        logger.exception("Error during rotation advance")


async def auto_select_happy_hour() -> None:
    """Auto-select a happy hour location if no event was chosen (Wed noon PST).

    If the CURRENT person hasn't created an event by the deadline, mark
    them MISSED and auto-select a random previous location.  The MISSED
    person can recover by resubmitting before Friday 9AM.
    """
    from db import Database
    from db.functions import (
        get_events_this_week,
        get_random_previous_location,
        create_event,
        get_current_active_assignment,
        mark_assignment_chosen,
        mark_assignment_missed,
    )
    from mail.outgoing import notify_happy_hour_users

    now = datetime.now(UTC)

    try:
        with Database() as db:
            with db.session() as s:
                events = get_events_this_week(s, now)
                current = get_current_active_assignment(s)

                if events:
                    logger.info(
                        "Happy hour already decided this week, skipping auto-select"
                    )
                    if current is not None:
                        mark_assignment_chosen(s, current.id)
                        s.commit()
                    return

                if current is not None:
                    # Guard: don't mark missed if the deadline hasn't passed yet
                    deadline = current.deadline_at
                    if deadline is not None:
                        if deadline.tzinfo is None:
                            deadline = deadline.replace(tzinfo=UTC)
                        if deadline > now:
                            logger.info(
                                "Tyrant %s still has time (deadline %s > now %s), "
                                "skipping auto-select",
                                current.Account.username,
                                deadline,
                                now,
                            )
                            return

                    mark_assignment_missed(s, current.id)
                    logger.warning(
                        "Tyrant %s missed their deadline",
                        current.Account.username,
                    )

                # Pick a random previous location
                location = get_random_previous_location(s)
                if location is None:
                    logger.warning(
                        "No previous locations to choose from for auto-select"
                    )
                    if current is not None:
                        s.commit()
                    return

                friday_event = _next_friday_5pm(now)

                try:
                    event = create_event(
                        s,
                        location_id=location.id,
                        tyrant_id=None,
                        when=friday_event,
                        description=f"Auto-selected: {location.Name}",
                        auto_selected=True,
                    )
                except IntegrityError:
                    logger.info(
                        "Event already exists for this week (concurrent), "
                        "skipping auto-select"
                    )
                    return

                logger.info(
                    "Auto-selected happy hour at %s for %s",
                    location.Name,
                    friday_event,
                )
                s.commit()
                event_id = event.id

            try:
                with db.session() as s2:
                    from db.functions import get_event_by_id

                    fresh_event = get_event_by_id(s2, event_id)
                    if fresh_event is not None:
                        await notify_happy_hour_users(fresh_event, s2)
            except Exception as e:
                logger.error("Failed to send auto-select notifications: %s", e)

    except Exception:
        logger.exception("Error during happy hour auto-select")


async def evaluate_strikes() -> None:
    """Evaluate strikes for MISSED assignments (Friday 9AM PST).

    If the CURRENT person is still MISSED at this point, the recovery
    window closes.  Count consecutive misses and remove the
    HAPPY_HOUR_TYRANT claim after :data:`CONSECUTIVE_MISS_LIMIT` strikes.
    """
    from db import Database
    from db.functions import (
        get_consecutive_misses,
        remove_claim_from_account,
    )
    from models.enums import AccountClaims, TyrantAssignmentStatus
    from models.happyhour.rotation import TyrantRotation
    from sqlalchemy import select

    try:
        with Database() as db:
            with db.session() as s:
                # Find the most recent MISSED assignment (if any)
                missed = s.scalars(
                    select(TyrantRotation)
                    .where(TyrantRotation.status == TyrantAssignmentStatus.MISSED)
                    .order_by(TyrantRotation.assigned_at.desc())
                ).first()

                if missed is None:
                    logger.info("No MISSED assignments to evaluate strikes for")
                    return

                from sqlalchemy.orm import joinedload

                # Re-fetch with Account loaded
                missed = s.scalars(
                    select(TyrantRotation)
                    .options(joinedload(TyrantRotation.Account))
                    .where(TyrantRotation.id == missed.id)
                ).first()

                misses = get_consecutive_misses(s, missed.account_id)
                logger.warning(
                    "Strike evaluated: %s has %d consecutive miss(es)",
                    missed.Account.username,
                    misses,
                )

                if misses >= CONSECUTIVE_MISS_LIMIT:
                    remove_claim_from_account(
                        s, missed.account_id, AccountClaims.HAPPY_HOUR_TYRANT
                    )
                    logger.warning(
                        "Removed HAPPY_HOUR_TYRANT from %s after %d consecutive misses",
                        missed.Account.username,
                        misses,
                    )

                s.commit()

    except Exception:
        logger.exception("Error during strike evaluation")


def start_scheduler() -> None:
    """Start the APScheduler with rotation, auto-select, and strike cron jobs."""
    from config import SCHEDULER_ENABLED

    if not SCHEDULER_ENABLED:
        logger.info("Scheduler disabled via SCHEDULER_ENABLED setting — skipping")
        return

    sched = get_scheduler()

    # Friday 5PM PST — advance the rotation pipeline
    sched.add_job(
        advance_rotation,
        CronTrigger(
            day_of_week="fri",
            hour=17,
            minute=0,
            timezone="America/Los_Angeles",
        ),
        id="happy_hour_advance_rotation",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # Wednesday noon PST — auto-select if no event
    sched.add_job(
        auto_select_happy_hour,
        CronTrigger(
            day_of_week="wed",
            hour=12,
            minute=0,
            timezone="America/Los_Angeles",
        ),
        id="happy_hour_auto_select",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # Friday 9AM PST — evaluate strikes (closes recovery window)
    sched.add_job(
        evaluate_strikes,
        CronTrigger(
            day_of_week="fri",
            hour=9,
            minute=0,
            timezone="America/Los_Angeles",
        ),
        id="happy_hour_evaluate_strikes",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    sched.start()
    logger.info(
        "Happy hour scheduler started "
        "(Fri 5PM: advance, Wed 12PM: auto-select, Fri 9AM: strikes)"
    )


def stop_scheduler() -> None:
    """Stop the APScheduler if it is currently running."""
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("Happy hour scheduler stopped")
