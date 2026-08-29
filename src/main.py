"""Entry point that glues the whole pipeline together.

Running this file (`python main.py`) starts the FastAPI backend
(src/helpers/backend.py) and, alongside it, a nightly maintenance job -
scheduled for 2am America/Chicago (DST-aware, via APScheduler's CronTrigger)
- that keeps the database in sync with the live TAMU calendar without
redoing work that's already done:

  1. Snapshot the DB's current (source, event_id, date, date_time) ->
     is_canceled state (postgre_io.get_event_cancellation_status) - cheap,
     one query.
  2. Re-scrape every calendar feed (fetch_events.fetch_all_events(force=True)
     bypasses the usual per-feed revisit-days cadence, since this only runs
     once a day and needs a fresh look at every event's current
     cancellation status, not just feeds that happen to be "due").
  3. Diff each freshly-scraped event's (source, event_id, date, date_time)
     identity against that snapshot:
       - key absent -> a brand new event: tag it (tagging.tag_events) and
         upsert it (postgre_io.upsert_events).
       - key present, is_canceled differs -> an existing event whose
         cancellation flipped: postgre_io.update_is_canceled, a plain
         column update - no need to re-tag or re-upsert anything else
         about the row.
       - key present, is_canceled unchanged -> nothing to do, skip it.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "helpers"))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import fetch_events
import postgre_io
import tagging
from backend import app
from schema import Event

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

        fresh_events: List[Event] = fetch_events.fetch_all_events(force=True)
        logger.info("Re-fetched %d event(s) from the live calendar", len(fresh_events))

        new_events: List[Event] = []
        cancellation_changes: List[Tuple[int, int, str, str, str]] = []

        for event in fresh_events:
            key = (event.source, event.event_id, event.date, event.date_time)
            previous_is_canceled = previous_status.get(key)
            is_canceled = event.is_canceled or ""

            if previous_is_canceled is None:
                new_events.append(event)
            elif previous_is_canceled != is_canceled:
                cancellation_changes.append(
                    (event.source, event.event_id, event.date, event.date_time, is_canceled)
                )
            # else: same id, same is_canceled - nothing changed, skip it.

        if cancellation_changes:
            postgre_io.update_is_canceled(conn, cancellation_changes)

        if new_events:
            logger.info("Tagging %d brand-new event(s)", len(new_events))
            tagging.tag_events(new_events)
            postgre_io.upsert_events(conn, [asdict(event) for event in new_events])

        logger.info(
            "Nightly event refresh complete: %d new, %d cancellation update(s), %d unchanged",
            len(new_events),
            len(cancellation_changes),
            len(fresh_events) - len(new_events) - len(cancellation_changes),
        )

        print(
            "Nightly event refresh complete: %d new, %d cancellation update(s), %d unchanged",
            len(new_events),
            len(cancellation_changes),
            len(fresh_events) - len(new_events) - len(cancellation_changes)
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
