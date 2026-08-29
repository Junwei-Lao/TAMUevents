"""Entry point that glues the whole pipeline together.

Running this file (`python main.py`) starts the FastAPI backend
(src/helpers/backend.py) and, alongside it, a nightly maintenance job -
scheduled for 2am America/Chicago (DST-aware, via APScheduler's CronTrigger)
- that keeps the database in sync with the live calendar/ERS scrape without
redoing work that's already done:

  1. Snapshot the DB's current (source, event_id, date, date_time) ->
     is_canceled state (postgre_io.get_event_cancellation_status) - cheap,
     one query.
  2. Re-scrape everything (fetch_events.fetch_all_events(force=True), which
     already covers both sources - the TAMU calendar and TAMU ERS - and
     bypasses the usual per-feed revisit-days cadence, since this only runs
     once a day and needs a fresh look at every event's current state, not
     just feeds that happen to be "due").
  3. Diff each freshly-scraped event against that snapshot. The match key
     depends on source, since event_id's uniqueness guarantee differs
     between them (see schema.py's "Event sources" docstring):
       - TAMU calendar (schema.DEFAULT_SOURCE): matched on the full
         (source, event_id, date, date_time), same as before - this source
         legitimately reuses one event_id across multiple simultaneous
         recurring occurrences, so date/date_time can never be dropped from
         its identity without collapsing distinct events onto each other.
       - TAMU ERS (schema.ERS_SOURCE): matched on (source, event_id) alone,
         since ERS hands out a fresh, never-repeated event_id (ScheduleId)
         per real event (see tagging.py's tag_all_ers_events notes) - so
         unlike the calendar source, a date/date_time difference under the
         same id means "this event got rescheduled", not "a different
         occurrence".
     Then, per matched event:
       - key absent -> a brand new event: tag it (tagging.tag_events) and
         upsert it (postgre_io.upsert_events).
       - key present, date/date_time differs (ERS only) -> rescheduled:
         postgre_io.update_event_schedule, a plain column update (relies on
         postgre_io.patch_add_fk_update_cascade having been applied) - no
         need to re-tag, the event's content hasn't changed.
       - key present, only is_canceled differs -> postgre_io.update_is_canceled,
         a plain column update.
       - key present, nothing differs -> skip it.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "helpers"))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import fetch_events
import postgre_io
import tagging
from backend import app
from schema import ERS_SOURCE, Event

logger = logging.getLogger(__name__)

REFRESH_TIMEZONE = "America/Chicago"
REFRESH_HOUR = 2
REFRESH_MINUTE = 0


def refresh_events() -> None:
    """The nightly job body - see this module's docstring. Swallows and
    logs any failure (DB down, scrape failure, tagging API down, ...)
    rather than raising, so one bad night doesn't kill the scheduler or the
    backend process - it just retries at the next scheduled run."""
    logger.info("Nightly event refresh starting")
    try:
        conn = postgre_io.connect()
    except Exception:
        logger.exception("Nightly refresh: could not connect to the database, aborting this run")
        return

    try:
        previous_status = postgre_io.get_event_cancellation_status(conn)
        logger.info("Loaded cancellation status for %d known event(s)", len(previous_status))

        # ERS's event_id is a stable identifier for one real event (never
        # reused across occurrences - see this module's docstring), so it's
        # safe to derive a (source, event_id) -keyed view of the same
        # snapshot for it. The TAMU calendar source is deliberately left
        # out of this map: it legitimately reuses event_id across distinct
        # recurring occurrences, so collapsing it onto this key would merge
        # events that must stay separate.
        ers_previous_by_id: Dict[int, Tuple[str, str, str]] = {
            event_id: (date_, date_time, is_canceled)
            for (source, event_id, date_, date_time), is_canceled in previous_status.items()
            if source == ERS_SOURCE
        }

        fresh_events: List[Event] = fetch_events.fetch_all_events(force=True)
        logger.info("Re-fetched %d event(s) (all sources)", len(fresh_events))

        new_events: List[Event] = []
        cancellation_changes: List[Tuple[int, int, str, str, str]] = []
        reschedule_changes: List[Tuple[int, int, str, str, str, str, str]] = []

        for event in fresh_events:
            is_canceled = event.is_canceled or ""

            if event.source == ERS_SOURCE:
                previous = ers_previous_by_id.get(event.event_id)
                if previous is None:
                    new_events.append(event)
                    continue
                previous_date, previous_date_time, previous_is_canceled = previous
                if previous_date != event.date or previous_date_time != event.date_time:
                    reschedule_changes.append((
                        event.source, event.event_id, previous_date, previous_date_time,
                        event.date, event.date_time, is_canceled,
                    ))
                elif previous_is_canceled != is_canceled:
                    cancellation_changes.append(
                        (event.source, event.event_id, event.date, event.date_time, is_canceled)
                    )
                # else: same id, same date/date_time, same is_canceled - skip it.
            else:
                key = (event.source, event.event_id, event.date, event.date_time)
                previous_is_canceled = previous_status.get(key)
                if previous_is_canceled is None:
                    new_events.append(event)
                elif previous_is_canceled != is_canceled:
                    cancellation_changes.append(
                        (event.source, event.event_id, event.date, event.date_time, is_canceled)
                    )
                # else: same id, same is_canceled - nothing changed, skip it.

        if reschedule_changes:
            postgre_io.update_event_schedule(conn, reschedule_changes)

        if cancellation_changes:
            postgre_io.update_is_canceled(conn, cancellation_changes)

        if new_events:
            logger.info("Tagging %d brand-new event(s)", len(new_events))
            tagging.tag_events(new_events)
            postgre_io.upsert_events(conn, [asdict(event) for event in new_events])

        unchanged_count = len(fresh_events) - len(new_events) - len(cancellation_changes) - len(reschedule_changes)
        logger.info(
            "Nightly event refresh complete: %d new, %d rescheduled, "
            "%d cancellation update(s), %d unchanged",
            len(new_events), len(reschedule_changes), len(cancellation_changes), unchanged_count,
        )
    except Exception:
        logger.exception("Nightly event refresh failed")
    finally:
        conn.close()


scheduler = BackgroundScheduler(timezone=REFRESH_TIMEZONE)
scheduler.add_job(
    refresh_events,
    CronTrigger(hour=REFRESH_HOUR, minute=REFRESH_MINUTE, timezone=REFRESH_TIMEZONE),
    id="nightly_event_refresh",
    replace_existing=True,
)


@asynccontextmanager
async def _lifespan(_app):
    scheduler.start()
    logger.info(
        "Scheduled nightly event refresh for %02d:%02d %s",
        REFRESH_HOUR, REFRESH_MINUTE, REFRESH_TIMEZONE,
    )
    yield
    scheduler.shutdown(wait=False)


app.router.lifespan_context = _lifespan


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 9191)))
