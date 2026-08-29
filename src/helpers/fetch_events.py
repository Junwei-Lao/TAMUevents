"""Scrapes TAMU events from two sources - the TAMU calendar (schema.DEFAULT_SOURCE)
and TAMU ERS (schema.ERS_SOURCE) - into the shared Event schema.

TAMU calendar pipeline:
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

TAMU ERS pipeline (see discover_ers_sources / fetch_ers_events below): ERS
(https://ers.tamu.edu/default.aspx) has no JSON feed at all - it's a single
server-rendered ASPX page listing every event in one table - so discovery
and the calendar pipeline's per-group "feed" step collapse into one HTML
scrape, followed by the same fetch-detail-page -> parse -> Event shape as
the calendar pipeline.
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
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from schema import ERS_SOURCE, Event, FeedVisitStatus

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
# Kept separate from DEFAULT_EVENTS_PATH (the calendar source's file) - the
# two sources are merged/checkpointed independently, each against its own
# file, rather than sharing one output path.
DEFAULT_ERS_EVENTS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "ers_events.json"
)
DEFAULT_REQUEST_DELAY_SECONDS = 0.2
DEFAULT_MAX_RETRIES = 6
DEFAULT_BACKOFF_BASE_SECONDS = 30
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


def _event_identity(event: Event) -> Tuple[int, int, str, str]:
    """(source, event_id, date, date_time) - matches the identity key
    schema.py/postgre_io.py use, since event_id is only unique *within* one
    source (see schema.py's "Event sources" docstring section) - two
    different sources (TAMU calendar, TAMU ERS, ...) could hand out the
    same event_id for unrelated events."""
    return (event.source, event.event_id, event.date, event.date_time)


def _merge_events(existing: List[Event], fresh: List[Event]) -> List[Event]:
    """Combine freshly-fetched events with whatever was already saved to
    disk, so groups skipped this run (not due for a revisit) aren't lost
    from the on-disk snapshot. Fresh data wins wherever it overlaps."""
    merged = {_event_identity(e): e for e in existing}
    merged.update({_event_identity(e): e for e in fresh})
    return list(merged.values())


def fetch_all_events(
    revisit_days: float = DEFAULT_REVISIT_DAYS,
    status_path: str = DEFAULT_STATUS_PATH,
    force: bool = False,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    output_path: Optional[str] = DEFAULT_EVENTS_PATH,
    save_to_file: bool = True,
    include_ers: bool = True,
    ers_output_path: Optional[str] = DEFAULT_ERS_EVENTS_PATH,
) -> List[Event]:
    """Fetch events for every calendar group whose feed is due for a
    revisit (or every group, if force=True), plus - by default - every
    current TAMU ERS event (include_ers=True; see fetch_ers_events).

    Groups that were visited more recently than `revisit_days` ago are
    skipped, and the visit-status file is updated for every group that
    *was* fetched. ERS has no per-group revisit cadence of its own (see
    fetch_ers_events's docstring) - its whole listing is re-scraped every
    time this runs, regardless of `revisit_days`/`force`.

    The two sources are merged/checkpointed independently, each against its
    own file - calendar events into `output_path` (data/events.json), ERS
    events into `ers_output_path` (data/ers_events.json) - so neither run
    can overwrite or drop the other's on-disk data. The *return value* is
    still the combined list from both sources in one place, for callers
    (tagging.py, postgre_io.py, ...) that want everything fetched this run
    regardless of source; schema.Event.source tells them apart.

    Pass save_to_file=False to skip both disk writes and just get back
    whatever was fetched this run.

    Progress is checkpointed every CHECKPOINT_EVERY_N_EVENTS newly-kept
    events to each source's own file (calendar events to `output_path` as
    they're fetched below; ERS events to `ers_output_path`, inside
    fetch_ers_events), so an interruption partway through a long run
    doesn't lose everything fetched so far from either source.
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
        calendar_events = events
    else:
        calendar_events = _merge_events(existing_events, events)
        save_events_to_json(calendar_events, output_path)
        logger.info("Wrote %d total calendar events -> %s", len(calendar_events), output_path)

    combined_events = list(calendar_events)

    if include_ers:
        # fetch_ers_events merges/checkpoints against its own file
        # (ers_output_path), independent of the calendar events above, so
        # this can just delegate to it directly - no risk of the two
        # sources' writes colliding or one dropping the other's data.
        try:
            ers_events = fetch_ers_events(
                request_delay_seconds=request_delay_seconds,
                output_path=ers_output_path,
                save_to_file=save_to_file,
            )
            logger.info("Fetched %d ERS events", len(ers_events))
            combined_events.extend(ers_events)
        except Exception as exc:
            logger.warning("Failed to fetch ERS events: %s", exc)

    return combined_events


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


# --- TAMU ERS (https://ers.tamu.edu) -----------------------------------

ERS_MAIN_PAGE_URL = "https://ers.tamu.edu/default.aspx"

# ERS has no per-event category of its own (unlike the calendar source's
# scraped event_types), so every ERS event is tagged with this one fixed
# value - "Campus Life" already exists in the calendar source's own
# categories vocabulary, so this reuses it rather than introducing a
# parallel, ERS-only category value.
ERS_CATEGORY = "Campus Life"

# Maps ERS's "Eligibility" wording onto the same categories_audience
# vocabulary the TAMU calendar source already uses (see schema.py), so
# audience filtering works the same regardless of which source an event
# came from. Undergraduate/Graduate both mean "open to students"; Graduate
# additionally means "open to researchers", since grad students are the
# ones doing research. "TAMU Guest" is folded into "Visitors" - the
# calendar source's closest existing equivalent - rather than introducing
# a parallel, ERS-only audience value.
ERS_ELIGIBILITY_TO_AUDIENCE: Dict[str, List[str]] = {
    "faculty": ["Faculty"],
    "staff": ["Staff"],
    "undergraduate": ["Students"],
    "graduate": ["Students", "Researcher"],
    "tamu guest": ["Visitors"],
}

# Not eligibility values at all (e.g. "Student Departments: (ECON)",
# "Student Majors: (CPEN)", "Student Colleges: (EN)") - extra qualifying
# detail on one of the eligibility lines above them, so they're dropped
# rather than mapped.
_ERS_SKIP_LINE_PREFIXES = ("student departments", "student majors", "student colleges")

# Events flagged with this are restricted to a hand-picked list of people
# rather than open to whoever fits the eligibility list above, so the
# eligibility list itself would be misleading if kept - the whole event is
# dropped instead.
ERS_INVITATION_ONLY_MARKER = "by invitation only"

_ERS_DATETIME_RE = re.compile(
    r"^(?P<weekday>[A-Za-z]+)\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+(?P<time>.+)$"
)


def discover_ers_sources(session: Optional[requests.Session] = None) -> List[dict]:
    """Scrape the ERS main listing page for every event. ERS renders its
    listing server-side with no JSON feed, so - unlike the calendar
    source's discover_feed_sources, which only finds *feed URLs* to fetch
    separately - this does the calendar source's "discover feeds" and
    "fetch feed entries" steps in one pass, straight off the rendered HTML
    table: each row's event name + detail-page link (a.el-name) and its
    "Eligibility" cell, mapped onto categories_audience via
    ERS_ELIGIBILITY_TO_AUDIENCE.

    Events marked "By Invitation only" are dropped entirely here (not
    returned at all), since their eligibility list would otherwise imply
    they're open to anyone matching it rather than restricted to specific
    invitees.

    Returns a list of dicts: {"title", "url" (absolute detail-page URL),
    "group_title" (the "Hosted By:" department), "categories_audience"}.
    """
    session = session or requests
    response = _get_with_retry(session, ERS_MAIN_PAGE_URL)
    soup = BeautifulSoup(response.text, "html.parser")

    entries: List[dict] = []
    for link in soup.select("a.el-name"):
        title = link.get_text(strip=True)
        href = link.get("href")
        if not href:
            logger.warning("ERS event %r has no detail link; skipping", title)
            continue
        detail_url = urljoin(ERS_MAIN_PAGE_URL, href)

        event_cell = link.find_parent("td")
        row = event_cell.find_parent("tr") if event_cell is not None else None
        if row is None:
            logger.warning("Could not find table row for ERS event %r; skipping", title)
            continue

        group_title = ""
        hosted_by_label = event_cell.find("strong", string=re.compile("Hosted By", re.I))
        if hosted_by_label is not None and hosted_by_label.next_sibling:
            group_title = str(hosted_by_label.next_sibling).strip()

        eligibility_cell = row.find("td", attrs={"data-label": "Eligibility"})
        if eligibility_cell is None:
            logger.warning("No eligibility cell for ERS event %r; skipping", title)
            continue

        raw_lines = [
            line.strip()
            for line in eligibility_cell.get_text(separator="\n").split("\n")
            if line.strip()
        ]

        if any(line.lower() == ERS_INVITATION_ONLY_MARKER for line in raw_lines):
            continue

        categories_audience: List[str] = []
        for line in raw_lines:
            line_lower = line.lower()
            if line_lower.startswith(_ERS_SKIP_LINE_PREFIXES):
                continue
            mapped_values = ERS_ELIGIBILITY_TO_AUDIENCE.get(line_lower)
            if mapped_values is None:
                logger.warning(
                    "Unrecognized ERS eligibility line %r for event %r - "
                    "add it to ERS_ELIGIBILITY_TO_AUDIENCE or "
                    "_ERS_SKIP_LINE_PREFIXES if it's expected",
                    line, title,
                )
                continue
            for mapped in mapped_values:
                if mapped not in categories_audience:
                    categories_audience.append(mapped)

        entries.append({
            "title": title,
            "url": detail_url,
            "group_title": group_title,
            "categories_audience": categories_audience,
        })

    return entries


def fetch_ers_event_detail(detail_url: str, session: Optional[requests.Session] = None) -> dict:
    """Fetch an ERS event's own detail page and pull out its start/end
    time, location, and description by element id. Description is kept as
    raw inner HTML (it uses <br> for line breaks) so parse_ers_event can
    clean it the same way as the calendar source's (_html_to_plain_text)."""
    session = session or requests
    response = _get_with_retry(session, detail_url)
    soup = BeautifulSoup(response.text, "html.parser")

    def _text(element_id: str) -> Optional[str]:
        element = soup.find(id=element_id)
        return element.get_text(strip=True) if element is not None else None

    def _inner_html(element_id: str) -> Optional[str]:
        element = soup.find(id=element_id)
        return element.decode_contents() if element is not None else None

    return {
        "start_date": _text("ContentPlaceHolder1_startdate"),
        "end_date": _text("ContentPlaceHolder1_enddate"),
        "location": _text("ContentPlaceHolder1_location"),
        "description": _inner_html("ContentPlaceHolder1_longdescription"),
    }


def _split_ers_datetime(raw: Optional[str]) -> Tuple[str, str]:
    """Split an ERS start/end string like "Monday 8/31/2026 11:30 AM" into
    its (date, time) halves - e.g. ("Monday 8/31/2026", "11:30 AM") - so
    the start and end times can be combined into one "H:MM AM - H:MM PM"
    date_time without repeating the date twice."""
    if not raw:
        return "", ""
    match = _ERS_DATETIME_RE.match(raw.strip())
    if not match:
        return raw.strip(), ""
    return f"{match.group('weekday')} {match.group('date')}", match.group("time")


def parse_ers_event(entry: dict, detail: dict) -> Event:
    """Combine an ERS listing entry (discover_ers_sources) with its fetched
    detail page (fetch_ers_event_detail) into an Event. event_id is the
    ScheduleId query parameter of the event's own URL - the only stable
    unique identifier ERS exposes per event."""
    start_date, start_time = _split_ers_datetime(detail.get("start_date"))
    end_date, end_time = _split_ers_datetime(detail.get("end_date"))

    date = start_date if (not end_date or end_date == start_date) else f"{start_date} - {end_date}"
    if start_time and end_time:
        date_time = f"{start_time} - {end_time}"
    else:
        date_time = start_time or end_time or ""

    schedule_id = int(parse_qs(urlparse(entry["url"]).query)["ScheduleId"][0])

    return Event(
        event_id=schedule_id,
        group_title=entry.get("group_title", ""),
        url=entry["url"],
        date=date,
        date_time=date_time,
        title=_clean_text(entry["title"]) or "",
        description=_html_to_plain_text(detail.get("description")),
        location=_clean_text(detail.get("location")),
        categories=[ERS_CATEGORY],
        categories_audience=entry.get("categories_audience", []),
        is_canceled="",
        source=ERS_SOURCE,
    )


def fetch_ers_events(
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    output_path: Optional[str] = DEFAULT_ERS_EVENTS_PATH,
    save_to_file: bool = True,
) -> List[Event]:
    """Fetch every (non-invitation-only) event currently listed on ERS.

    Unlike fetch_all_events, there's no per-group revisit cadence here -
    ERS is one page listing every event directly, not ~165 separate feeds -
    so this simply re-scrapes the whole listing and fetches every event's
    detail page each time it's called.

    By default (save_to_file=True) the results are merged into
    `output_path` (data/ers_events.json - kept separate from the calendar
    source's data/events.json, so the two sources' files never collide or
    get overwritten by each other) and the full merged list is returned,
    ready for tagging.py / postgre_io.py to use directly (schema.py's
    `source` field still tells the two sources' events apart wherever
    they're loaded together). Progress is also checkpointed every
    CHECKPOINT_EVERY_N_EVENTS events, same rationale as fetch_all_events.
    """
    session = requests.Session()
    events: List[Event] = []
    existing_events = load_events_from_json(output_path) if save_to_file and output_path else []

    entries = discover_ers_sources(session)
    logger.info("Discovered %d ERS events (before per-event detail fetch)", len(entries))

    for entry in entries:
        time.sleep(request_delay_seconds)

        # Same rationale as the calendar pipeline: never let one bad
        # event's detail fetch abort the whole run.
        try:
            detail = fetch_ers_event_detail(entry["url"], session)
            parsed = parse_ers_event(entry, detail)
        except Exception as exc:
            logger.warning(
                "Failed to fetch/parse ERS event detail for %r: %s", entry.get("url"), exc,
            )
            continue

        if not _should_keep_event(parsed):
            continue

        events.append(parsed)
        print(f"event:{parsed}")

        if save_to_file and output_path and len(events) % CHECKPOINT_EVERY_N_EVENTS == 0:
            checkpoint = _merge_events(existing_events, events)
            save_events_to_json(checkpoint, output_path)
            logger.info(
                "Checkpoint: saved %d total events (%d fetched so far this run) -> %s",
                len(checkpoint), len(events), output_path,
            )

    if not save_to_file or not output_path:
        return events

    merged_events = _merge_events(existing_events, events)
    save_events_to_json(merged_events, output_path)
    logger.info("Wrote %d total events -> %s", len(merged_events), output_path)
    return merged_events


if __name__ == "__main__":
    fetch_ers_events()