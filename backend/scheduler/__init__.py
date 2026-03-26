"""
APScheduler jobs for happy hour tyrant rotation and auto-selection.

- assign_tyrant: Runs Friday at 4PM PST. Picks the next HAPPY_HOUR_TYRANT
  in round-robin order and notifies them.
- auto_select_happy_hour: Runs Wednesday at noon PST. If no event was created,
  marks the assigned tyrant as MISSED, auto-selects a location, and creates
  an event with TyrantID=NULL. After 3 consecutive misses the admin loses
  the HAPPY_HOUR_TYRANT claim.
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
    """Return the global :class:`AsyncIOScheduler` singleton, creating it if needed.

    :returns: The shared scheduler instance.
    :rtype: AsyncIOScheduler
    """
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler


def _next_wednesday_noon(from_dt: datetime) -> datetime:
    """Calculate the next Wednesday 12:00 PM PST from a given datetime.

    :param from_dt: Reference datetime (timezone-aware).
    :returns: A timezone-aware datetime for the next Wednesday at noon PST.
    :rtype: datetime
    """
    local = from_dt.astimezone(PST)
    days_until_wed = (2 - local.weekday()) % 7
    if days_until_wed == 0:
        # It's Wednesday — only skip to next week if already past noon
        if local.hour >= 12:
            days_until_wed = 7
    wed = local + timedelta(days=days_until_wed)
    return wed.replace(hour=12, minute=0, second=0, microsecond=0)


def _next_friday_event(from_dt: datetime) -> datetime:
    """Calculate the next Friday 4:00 PM PST from a given datetime.

    :param from_dt: Reference datetime (timezone-aware).
    :returns: A timezone-aware datetime for the next Friday at 4 PM PST.
    :rtype: datetime
    """
    local = from_dt.astimezone(PST)
    days_until_friday = (4 - local.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    friday = local + timedelta(days=days_until_friday)
    return friday.replace(hour=16, minute=0, second=0, microsecond=0)


async def assign_tyrant() -> None:
    """Assign the next ``HAPPY_HOUR_TYRANT`` user in rotation.

    Runs every Friday at 4 PM PST.  If a SCHEDULED assignment exists in the
    current cycle it is activated (→ PENDING) with a Wednesday noon deadline.
    Otherwise a new cycle is created with all eligible users in shuffled
    order and the first assignment is activated.

    After activation the assigned tyrant is notified, and the next person in
    the rotation (if any) receives an "on deck" heads-up.
    """
    from db import Database
    from db.functions import (
        get_accounts_with_claim,
        get_current_cycle_number,
        get_current_pending_assignment,
        get_next_scheduled_assignment,
        get_on_deck_assignment,
        create_cycle_rotation,
        activate_assignment,
    )
    from models.enums import AccountClaims

    now = datetime.now(UTC)

    try:
        with Database() as db:
            with db.session() as s:
                # Guard: if someone is already PENDING, don't activate another
                existing_pending = get_current_pending_assignment(s)
                if existing_pending is not None:
                    logger.info(
                        "Tyrant %s is already pending (deadline %s), "
                        "skipping assignment",
                        existing_pending.Account.username,
                        existing_pending.deadline_at,
                    )
                    return

                admins = get_accounts_with_claim(s, AccountClaims.HAPPY_HOUR_TYRANT)
                if not admins:
                    logger.warning(
                        "No HAPPY_HOUR_TYRANT users found for tyrant assignment"
                    )
                    return

                cycle = get_current_cycle_number(s)
                scheduled = get_next_scheduled_assignment(s, cycle)

                if scheduled is None:
                    # Current cycle is exhausted — start a new one
                    cycle += 1
                    rotations = create_cycle_rotation(s, list(admins), cycle, now)
                    logger.info(
                        f"Created new rotation cycle {cycle} with "
                        f"{len(rotations)} members: "
                        + ", ".join(r.Account.username for r in rotations)
                    )
                    scheduled = rotations[0]

                deadline = _next_wednesday_noon(now)
                activate_assignment(s, scheduled.id, deadline)

                # Refresh to pick up status change
                s.refresh(scheduled)
                tyrant = scheduled.Account

                logger.info(
                    f"Assigned tyrant: {tyrant.username} (cycle {cycle}, "
                    f"position {scheduled.position}, deadline {deadline})"
                )

                # Ensure the tyrant also has HAPPY_HOUR claim
                if not (tyrant.claims & AccountClaims.HAPPY_HOUR):
                    from db.functions import update_account_claims

                    update_account_claims(
                        s, tyrant.id, tyrant.claims | AccountClaims.HAPPY_HOUR
                    )

                s.commit()

                # Notify the assigned tyrant
                try:
                    from mail.outgoing import notify_tyrant_assigned

                    await notify_tyrant_assigned(tyrant, deadline)
                except Exception as e:
                    logger.error(f"Failed to notify tyrant {tyrant.username}: {e}")

                # Notify the on-deck person (next in rotation)
                on_deck = get_on_deck_assignment(s, cycle, scheduled.position)
                if on_deck is not None:
                    try:
                        from mail.outgoing import notify_tyrant_on_deck

                        await notify_tyrant_on_deck(on_deck.Account, tyrant.username)
                    except Exception as e:
                        logger.error(
                            f"Failed to notify on-deck user "
                            f"{on_deck.Account.username}: {e}"
                        )

    except Exception:
        logger.exception("Error during tyrant assignment")


async def auto_select_happy_hour() -> None:
    """Auto-select a happy hour location if none was chosen this week.

    Runs every Wednesday at noon PST.  If no event exists for the
    current weekly window the assigned tyrant (if any) is marked as
    ``MISSED``.  After :data:`CONSECUTIVE_MISS_LIMIT` consecutive
    misses the user loses the ``HAPPY_HOUR_TYRANT`` claim.  A random
    previous location is then selected and notifications are sent.
    """
    from db import Database
    from db.functions import (
        get_events_this_week,
        get_random_previous_location,
        create_event,
        get_current_pending_assignment,
        mark_assignment_chosen,
        mark_assignment_missed,
        get_consecutive_misses,
        remove_claim_from_account,
    )
    from models.enums import AccountClaims
    from mail.outgoing import notify_happy_hour_users

    now = datetime.now(UTC)

    try:
        with Database() as db:
            with db.session() as s:
                events = get_events_this_week(s, now)
                pending = get_current_pending_assignment(s)

                if events:
                    logger.info(
                        "Happy hour already decided this week, skipping auto-select"
                    )
                    # Mark the pending assignment as chosen since an event exists
                    if pending:
                        mark_assignment_chosen(s, pending.id)
                        s.commit()
                    return

                # No event this week — handle the pending assignment
                if pending:
                    # Guard: don't mark missed if the deadline hasn't passed yet
                    # (happens during catch-up when multiple jobs fire at once)
                    deadline = pending.deadline_at
                    if deadline is not None:
                        # Normalize timezone for comparison (SQLite stores naive)
                        if deadline.tzinfo is None:
                            deadline = deadline.replace(tzinfo=UTC)
                        if deadline > now:
                            logger.info(
                                "Tyrant %s still has time (deadline %s > now %s), "
                                "skipping auto-select",
                                pending.Account.username,
                                deadline,
                                now,
                            )
                            return

                    mark_assignment_missed(s, pending.id)
                    misses = get_consecutive_misses(s, pending.account_id)
                    logger.warning(
                        f"Tyrant {pending.Account.username} missed their deadline "
                        f"({misses} consecutive miss(es))"
                    )
                    if misses >= CONSECUTIVE_MISS_LIMIT:
                        remove_claim_from_account(
                            s, pending.account_id, AccountClaims.HAPPY_HOUR_TYRANT
                        )
                        logger.warning(
                            f"Removed HAPPY_HOUR_TYRANT from {pending.Account.username} "
                            f"after {misses} consecutive misses"
                        )

                # Pick a random previous location
                location = get_random_previous_location(s)
                if location is None:
                    logger.warning(
                        "No previous locations to choose from for auto-select"
                    )
                    if pending:
                        s.commit()  # persist missed status changes
                    return

                # Calculate next Friday at 4PM PST
                friday_event = _next_friday_event(now)

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
                        "Event already exists for this week (concurrent creation), skipping auto-select"
                    )
                    return

                logger.info(
                    f"Auto-selected happy hour at {location.Name} for {friday_event}"
                )
                s.commit()
                event_id = event.id

            # Send notifications outside the DB session, re-fetching in a fresh session
            try:
                with db.session() as s2:
                    from db.functions import get_event_by_id

                    fresh_event = get_event_by_id(s2, event_id)
                    if fresh_event is not None:
                        await notify_happy_hour_users(fresh_event, s2)
            except Exception as e:
                logger.error(f"Failed to send auto-select notifications: {e}")

    except Exception:
        logger.exception("Error during happy hour auto-select")


def start_scheduler() -> None:
    """Start the APScheduler with the tyrant-assignment and auto-select cron jobs.

    The scheduler is only started when :pydata:`config.SCHEDULER_ENABLED` is
    ``True``.  In multi-instance deployments set ``SCHEDULER_ENABLED=0`` on
    all replicas except one.
    """
    from config import SCHEDULER_ENABLED

    if not SCHEDULER_ENABLED:
        logger.info("Scheduler disabled via SCHEDULER_ENABLED setting — skipping")
        return

    sched = get_scheduler()

    # Friday 4PM PST — assign next tyrant
    sched.add_job(
        assign_tyrant,
        CronTrigger(
            day_of_week="fri",
            hour=16,
            minute=0,
            timezone="America/Los_Angeles",
        ),
        id="happy_hour_assign_tyrant",
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

    sched.start()
    logger.info(
        "Happy hour scheduler started "
        "(Friday 4PM PST: assign tyrant, Wednesday 12:00 PST: auto-select)"
    )


def stop_scheduler() -> None:
    """Stop the APScheduler if it is currently running."""
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("Happy hour scheduler stopped")
