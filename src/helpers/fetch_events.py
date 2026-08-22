"""Scrapes TAMU calendar events.

Pipeline:
  1. Discover every calendar group's JSON feed URL from
     https://calendar.tamu.edu/feeds/ (the "feed_source" list next to each
     group heading).
  2. For groups that are due for a revisit (tracked in a small status JSON
     file, since the feeds don't change often and we only want to re-check
     every few days), fetch that group's JSON feed. It's a flat list of
     event summaries.
  3. Each summary's "url" (e.g. .../event/378574-texas-aampm-...) carries the
     slug used to look up the same event's *detail* JSON, which has the
     fields we actually want (description, categories, cancellation, ...).
  4. Combine both into an Event and return the full list.
"""

import html
import json
import logging
import os
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from schema import Event, FeedVisitStatus

logger = logging.getLogger(__name__)

FEEDS_PAGE_URL = "https://calendar.tamu.edu/feeds/"
EVENT_DETAIL_BASE_URL = "https://calendar.tamu.edu/live/calendar/view/event/slug/{slug}"
DEFAULT_TIMEZONE = "America/Chicago"
DEFAULT_REVISIT_DAYS = 3
DEFAULT_STATUS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "feed_visit_status.json"
)
DEFAULT_SAMPLE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "sample_events.json"
)
DEFAULT_EVENTS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "events.json"
)
DEFAULT_REQUEST_DELAY_SECONDS = 0.2
DEFAULT_MAX_RETRIES = 6
DEFAULT_BACKOFF_BASE_SECONDS = 10
DEFAULT_BACKOFF_MAX_SECONDS = 1000

# Flush progress to disk every this-many newly-kept events, so a crash or
# interruption partway through a big run (there can be thousands of events
# across all groups) only loses the current partial batch, not everything.
CHECKPOINT_EVERY_N_EVENTS = 20

# Events whose title contains any of these (case-insensitive) are dropped,
# e.g. recurring "Transit" shuttle/parking notices that aren't real events.
TITLE_BLACKLIST_KEYWORDS = ["transit"]

HEADERS = {"User-Agent": "tamuevent-mobile-backend/1.0 (+event scraper)"}

# Template vars / syntax widget args copied from the calendar site's own
# event-detail widget request, which is what actually returns the
# description/categories/etc. fields we need.
_DETAIL_TEMPLATE_VARS = ",".join(
    [
        "group", "title", "id", "image_src", "image_alt", "summary", "description",
        "online_instructions", "online_url", "online_button_label", "registration",
        "date_start_month_short", "date_start_day", "date_end_month_short",
        "date_end_day", "date_end_year", "date_start_year", "time",
        "location_latitude", "location_longitude", "location", "custom_room_number",
        "cost", "contact_info", "related_content", "add_to_google",
        "ical_download_href", "share_links", "tags_calendar", "logged_in",
        "is_multi_day", "is_all_day",
    ]
)
_DETAIL_SYNTAX = (
    '<widget type="events_calendar">'
    '<arg id="mini_cal_heat_map">true</arg>'
    '<arg id="thumb_width">960</arg>'
    '<arg id="thumb_height">540</arg>'
    '<arg id="hero_image_width">1200</arg>'
    '<arg id="hide_repeats">true</arg>'
    '<arg id="show_groups">true</arg>'
    '<arg id="show_tags">false</arg>'
    '<arg id="search_all_events_only">true</arg>'
    '<arg id="search_all_groups">false</arg>'
    '<arg id="default_view">week</arg>'
    "</widget>"
)

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(value: Optional[str]) -> Optional[str]:
    """Strip HTML tags (e.g. the <span> date separator) and unescape
    entities (e.g. "&amp;" -> "&"), for fields meant to be plain text."""
    if not value:
        return value
    return html.unescape(_TAG_RE.sub("", value)).strip()


def _html_to_plain_text(value: Optional[str]) -> Optional[str]:
    """Render an HTML fragment (e.g. a description with <p>/<div>/<a> tags)
    down to plain text, collapsing whitespace left behind by block tags."""
    if not value:
        return value
    text = BeautifulSoup(value, "html.parser").get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _as_str_list(value) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [_clean_text(v) for v in value if v]
    return [_clean_text(str(value))]


def _get_with_retry(
    session: requests.Session,
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_max: float = DEFAULT_BACKOFF_MAX_SECONDS,
) -> requests.Response:
    """GET a URL, retrying with exponential backoff (2s, 4s, 8s, ...) any
    time the server doesn't return 200 - e.g. the calendar site rate-limiting
    us for hitting it too often - or the request fails outright. Honors a
    Retry-After header if the server sends one. Raises once retries run out.
    """
    attempt = 0
    while True:
        try:
            response = session.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException as exc:
            if attempt >= max_retries:
                raise
            delay = min(backoff_base * (2 ** attempt), backoff_max)
            logger.warning(
                "Request error for %s (%s); retrying in %.0fs (attempt %d/%d)",
                url, exc, delay, attempt + 1, max_retries,
            )
            time.sleep(delay)
            attempt += 1
            continue

        if response.status_code == 200:
            return response

        if attempt >= max_retries:
            response.raise_for_status()
            raise requests.HTTPError(f"Non-200 status {response.status_code} for {url}")

        retry_after = response.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else min(backoff_base * (2 ** attempt), backoff_max)
        except ValueError:
            delay = min(backoff_base * (2 ** attempt), backoff_max)

        logger.warning(
            "Got HTTP %d for %s; retrying in %.0fs (attempt %d/%d)",
            response.status_code, url, delay, attempt + 1, max_retries,
        )
        time.sleep(delay)
        attempt += 1


def discover_feed_sources(session: Optional[requests.Session] = None) -> List[Tuple[str, str]]:
    """Scrape the calendar feeds page and return a list of
    (group_title, json_feed_url) for every calendar group listed there."""
    session = session or requests
    response = _get_with_retry(session, FEEDS_PAGE_URL)

    soup = BeautifulSoup(response.text, "html.parser")
    feeds: List[Tuple[str, str]] = []

    for heading in soup.select("h3.calendar_group"):
        link = heading.find("a")
        if not link:
            continue
        group_title = link.get_text(strip=True)

        feed_list = heading.find_next_sibling("ul", class_="feed_source")
        if not feed_list:
            continue

        json_url = None
        for a in feed_list.find_all("a"):
            if a.get_text(strip=True).upper() == "JSON":
                json_url = a.get("href")
                break

        if json_url:
            feeds.append((group_title, json_url))
        else:
            logger.warning("No JSON feed link found for group %r", group_title)

    return feeds


def load_visit_status(status_path: str = DEFAULT_STATUS_PATH) -> Dict[str, FeedVisitStatus]:
    """Load the per-feed last-visited tracking file. Returns {} if it
    doesn't exist yet."""
    if not os.path.exists(status_path):
        return {}

    with open(status_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    return {feed_url: FeedVisitStatus(**data) for feed_url, data in raw.items()}


def _write_json(path: str, data) -> None:
    """Write JSON to path, creating parent directories as needed. Raises a
    clearer error than a bare PermissionError traceback if the directory or
    an existing file there isn't writable by the current user - e.g. the
    data/ folder was created by a different user (root via sudo, a
    different deploy) than the one running this script now."""
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except PermissionError as exc:
        raise PermissionError(
            f"No permission to write {path!r} ({exc}). This usually means {directory!r} "
            "(or a file already in it) is owned by a different user - check with "
            f"`ls -la {directory}` and `id`, then either `chown` it to the user "
            "running this script or rerun with that same user/permissions."
        ) from exc


def save_visit_status(
    statuses: Dict[str, FeedVisitStatus], status_path: str = DEFAULT_STATUS_PATH
) -> None:
    serializable = {feed_url: asdict(status) for feed_url, status in statuses.items()}
    _write_json(status_path, serializable)


def _is_due_for_revisit(
    status: Optional[FeedVisitStatus], revisit_days: float
) -> bool:
    if status is None:
        return True

    last_visited = datetime.fromisoformat(status.last_visited)
    age = datetime.now(timezone.utc) - last_visited
    return age.total_seconds() >= revisit_days * 86400


def fetch_feed_entries(json_url: str, session: Optional[requests.Session] = None) -> List[dict]:
    """Fetch a group's JSON feed (the flat list of event summaries)."""
    session = session or requests
    response = _get_with_retry(session, json_url)
    return response.json()


def build_event_detail_url(event_url: str, tz: str = DEFAULT_TIMEZONE) -> str:
    """Given the "url" field from a feed entry (e.g.
    https://calendar.tamu.edu/athletics/event/378574-texas-aampm-...), build
    the URL for that same event's detail JSON. The slug is the last path
    segment of the event url."""
    slug = event_url.rstrip("/").rsplit("/", 1)[-1]
    query = urlencode({
        "user_tz": tz,
        "template_vars": _DETAIL_TEMPLATE_VARS,
        "syntax": _DETAIL_SYNTAX,
    })
    return f"{EVENT_DETAIL_BASE_URL.format(slug=slug)}?{query}"


def fetch_event_detail(event_url: str, session: Optional[requests.Session] = None) -> dict:
    """Fetch the event-detail JSON for a feed entry's "url"."""
    session = session or requests
    detail_url = build_event_detail_url(event_url)
    response = _get_with_retry(session, detail_url)
    return response.json()


def parse_event(entry: dict, detail: dict) -> Event:
    """Combine a feed entry with its fetched detail JSON into an Event."""
    event = detail.get("event", {})

    return Event(
        event_id=entry["id"],
        group_title=entry.get("group_title", ""),
        url=entry["url"],
        date=_clean_text(detail.get("title")) or "",
        date_time=_clean_text(event.get("date_time")) or "",
        title=_clean_text(event.get("title")) or "",
        description=_html_to_plain_text(event.get("description")),
        location=_clean_text(event.get("location")),
        categories=_as_str_list(event.get("categories")),
        categories_audience=_as_str_list(event.get("categories_audience")),
        is_canceled=event.get("is_canceled") or "",
    )


def _is_blacklisted_title(title: str) -> bool:
    title_lower = (title or "").lower()
    return any(keyword in title_lower for keyword in TITLE_BLACKLIST_KEYWORDS)


def _should_keep_event(event: Event) -> bool:
    """Shared quality/blacklist filter used by both fetch_all_events and
    fetch_sample_events, so the two paths never disagree on what counts as
    a keepable event."""
    if _is_blacklisted_title(event.title):
        return False
    if not event.description and not event.location:
        return False
    return True


def save_events_to_json(events: List[Event], output_path: str) -> None:
    _write_json(output_path, [asdict(event) for event in events])


def load_events_from_json(path: str) -> List[Event]:
    """Load previously saved events (e.g. from fetch_all_events) back into
    Event objects. Returns [] if the file doesn't exist yet."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [Event(**item) for item in raw]


def _merge_events(existing: List[Event], fresh: List[Event]) -> List[Event]:
    """Combine freshly-fetched events with whatever was already saved to
    disk, so groups skipped this run (not due for a revisit) aren't lost
    from the on-disk snapshot. Fresh data wins wherever it overlaps."""
    merged = {(e.event_id, e.date, e.date_time): e for e in existing}
    merged.update({(e.event_id, e.date, e.date_time): e for e in fresh})
    return list(merged.values())


def fetch_all_events(
    revisit_days: float = DEFAULT_REVISIT_DAYS,
    status_path: str = DEFAULT_STATUS_PATH,
    force: bool = False,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    output_path: Optional[str] = DEFAULT_EVENTS_PATH,
    save_to_file: bool = True,
) -> List[Event]:
    """Fetch events for every calendar group whose feed is due for a
    revisit (or every group, if force=True).

    Groups that were visited more recently than `revisit_days` ago are
    skipped, and the visit-status file is updated for every group that
    *was* fetched.

    By default (save_to_file=True) the freshly-fetched events are merged
    into `output_path` (data/events.json) - so groups skipped this run
    aren't dropped from the on-disk snapshot - and the full merged list is
    both written to disk and returned, ready for other modules (tagging.py,
    postgre_io.py, ...) to import and use directly. Pass save_to_file=False
    to skip the disk write and just get back whatever was fetched this run.

    Progress is also checkpointed to `output_path` every
    CHECKPOINT_EVERY_N_EVENTS newly-kept events, so an interruption partway
    through a long run doesn't lose everything fetched so far.
    """
    session = requests.Session()
    visit_status = load_visit_status(status_path)
    events: List[Event] = []
    existing_events = load_events_from_json(output_path) if save_to_file and output_path else []

    feeds = discover_feed_sources(session)
    logger.info("Discovered %d calendar group feeds", len(feeds))

    for group_title, feed_url in feeds:
        status = visit_status.get(feed_url)
        if not force and not _is_due_for_revisit(status, revisit_days):
            logger.info("Skipping %r, visited recently (%s)", group_title, status.last_visited)
            continue

        logger.info("Fetching feed for %r", group_title)
        try:
            entries = fetch_feed_entries(feed_url, session)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Failed to fetch feed %r (%s): %s", group_title, feed_url, exc)
            continue

        group_event_count = 0
        for entry in entries:
            time.sleep(request_delay_seconds)

            # Accessing the event's detail JSON is the riskiest step here
            # (rate limiting, transient network errors, malformed
            # responses) - never let one bad event abort the whole feed.
            try:
                detail = fetch_event_detail(entry["url"], session)
                parsed = parse_event(entry, detail)
            except Exception as exc:
                logger.warning(
                    "Failed to fetch/parse event detail for %r: %s",
                    entry.get("url"), exc,
                )
                continue

            if not _should_keep_event(parsed):
                continue

            events.append(parsed)
            print(f"event:{parsed}")
            group_event_count += 1

            if save_to_file and output_path and len(events) % CHECKPOINT_EVERY_N_EVENTS == 0:
                checkpoint = _merge_events(existing_events, events)
                save_events_to_json(checkpoint, output_path)
                logger.info(
                    "Checkpoint: saved %d total events (%d fetched so far this run) -> %s",
                    len(checkpoint), len(events), output_path,
                )

        visit_status[feed_url] = FeedVisitStatus(
            group_title=group_title,
            feed_url=feed_url,
            last_visited=datetime.now(timezone.utc).isoformat(),
            event_count=group_event_count,
        )

    save_visit_status(visit_status, status_path)

    if not save_to_file or not output_path:
        return events

    merged_events = _merge_events(existing_events, events)
    save_events_to_json(merged_events, output_path)
    logger.info("Wrote %d total events -> %s", len(merged_events), output_path)
    return merged_events


def fetch_sample_events(
    limit: int = 10,
    output_path: str = DEFAULT_SAMPLE_PATH,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
) -> List[Event]:
    """Fetch just the first `limit` events that pass the usual filters
    (blacklist, must have a description or location), pulled from feed
    groups in discovery order, and dump them to a JSON file for local
    Postgres testing.

    This is a standalone sampling utility for test data, not the main
    pipeline: it always hits the live feeds directly and doesn't read or
    update the feed_visit_status.json revisit tracking. Progress is also
    checkpointed to output_path every CHECKPOINT_EVERY_N_EVENTS events (in
    case a larger limit is passed in), so an interruption doesn't lose
    everything fetched so far.
    """
    session = requests.Session()
    events: List[Event] = []

    feeds = discover_feed_sources(session)
    logger.info("Discovered %d calendar group feeds", len(feeds))

    for group_title, feed_url in feeds:
        if len(events) >= limit:
            break

        logger.info("Fetching feed for %r", group_title)
        try:
            entries = fetch_feed_entries(feed_url, session)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Failed to fetch feed %r (%s): %s", group_title, feed_url, exc)
            continue

        for entry in entries:
            if len(events) >= limit:
                break

            time.sleep(request_delay_seconds)

            # Same rationale as fetch_all_events: never let one bad event's
            # detail fetch abort the whole sampling run.
            try:
                detail = fetch_event_detail(entry["url"], session)
                parsed = parse_event(entry, detail)
            except Exception as exc:
                logger.warning(
                    "Failed to fetch/parse event detail for %r: %s",
                    entry.get("url"), exc,
                )
                continue

            if not _should_keep_event(parsed):
                continue

            events.append(parsed)
            print(f"event:{parsed}")

            if len(events) % CHECKPOINT_EVERY_N_EVENTS == 0:
                save_events_to_json(events, output_path)
                logger.info(
                    "Checkpoint: saved %d events so far -> %s", len(events), output_path
                )

    save_events_to_json(events, output_path)
    logger.info("Wrote %d sample events to %s", len(events), output_path)
    return events


if __name__ == "__main__":
    fetch_all_events()