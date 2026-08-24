"""Tags scraped TAMU calendar events with `topics` and `event_type` via the
DeepSeek API.

The taxonomy and prompt design are documented in classification.md at the
repo root; `schema.py`'s TOPIC_TAXONOMY / EVENT_TYPE_TAXONOMY dicts are the
canonical copy the prompt below is generated from (keep classification.md
in sync if those change - and see schema.py's own docstring for why the
taxonomy lives there rather than here: postgre_io.py needs it too, to
store `topics` as per-category bitflags).

The API key is read from the DEEPSEEK_API_KEY environment variable, which
can either be set directly or provided via a .env file at the repo root
(loaded automatically on import; a real environment variable always takes
priority over .env if both are set).

Pipeline:
  1. Load all Event objects, from a saved sample_events.json or (once
     postgre_io.py exists) the database.
  2. Group them by event_id and tag only one representative per id -
     scraped feeds sometimes list the same event more than once (see the
     duplicate event_id 372167 entries in data/sample_events.json), and
     there's no reason to pay for the same classification twice.
  3. Build a per-event prompt from its title/description/location/date/
     source categories.
  4. Call DeepSeek's chat completion API (JSON output mode) and validate
     the labels it returns against the closed taxonomy, falling back to
     "Other" on anything invalid or on a request failure.
  5. Write topics/event_type back onto the Event, and copy the same
     result onto every other Event sharing that event_id.
"""

import json
import logging
import os
import time
from dataclasses import asdict
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

from schema import (
    EVENT_TYPE_LEAF_TO_CATEGORY,
    EVENT_TYPE_TAXONOMY,
    OTHER_EVENT_TYPE,
    OTHER_TOPIC,
    TOPIC_LEAF_TO_CATEGORY,
    TOPIC_TAXONOMY,
    Event,
)

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
DEFAULT_SAMPLE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "sample_events.json"
)
DEFAULT_TAGGED_SAMPLE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "sample_events_tagged.json"
)
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_BASE_SECONDS = 5
DEFAULT_BACKOFF_MAX_SECONDS = 60
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60
DEFAULT_REQUEST_DELAY_SECONDS = 0.0
DESCRIPTION_CHAR_LIMIT = 1500

# Loads DEEPSEEK_API_KEY (and anything else) from .env into os.environ, if
# present. Existing environment variables are never overridden by this, so
# a real deployment env var still wins over whatever's in .env.
load_dotenv(DEFAULT_ENV_PATH)


def _format_taxonomy(taxonomy: Dict[str, List[str]]) -> str:
    return "\n".join(
        f"- {category}: {', '.join(leaves)}" for category, leaves in taxonomy.items()
    )


def _build_system_prompt() -> str:
    return (
        "You are an expert classifier for Texas A&M University calendar events.\n\n"
        "Given an event's title, description, location, date, and source category, assign:\n"
        '1. "topics": 1-3 labels from the TOPIC taxonomy below. Use more than one only if '
        "the event is genuinely interdisciplinary; prefer a single best-fitting topic.\n"
        '2. "event_type": exactly 1 label from the EVENT_TYPE taxonomy below - the single '
        "best-fitting type.\n\n"
        "Only output labels copied exactly (spelling, punctuation, capitalization) from the "
        f'taxonomies below. Never invent a label. '
        f'for topics or "{OTHER_EVENT_TYPE}" for event_type.\n\n'
        "TOPIC taxonomy (category: leaf labels):\n"
        f"{_format_taxonomy(TOPIC_TAXONOMY)}\n\n"
        "EVENT_TYPE taxonomy (category: leaf labels):\n"
        f"{_format_taxonomy(EVENT_TYPE_TAXONOMY)}\n\n"
        "Respond with ONLY a single JSON object, no markdown fences, no explanation:\n"
        '{"topics": ["<label>", ...], "event_type": "<label>"}'
    )


SYSTEM_PROMPT = _build_system_prompt()

_TOPIC_LEAVES = {
    leaf.lower(): leaf for leaves in TOPIC_TAXONOMY.values() for leaf in leaves
}


def _build_user_prompt(event: Event) -> str:
    description = (event.description or "")[:DESCRIPTION_CHAR_LIMIT]
    date_time = f"{event.date} {event.date_time}".strip()
    return (
        f"Title: {event.title}\n"
        f"Source category: {', '.join(event.categories) or 'none'}\n"
        f"Location: {event.location or 'unknown'}\n"
        f"Date: {date_time}\n"
        f"Description: {description or 'none'}"
    )


def _post_with_retry(
    session: requests.Session,
    api_key: str,
    messages: List[dict],
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_max: float = DEFAULT_BACKOFF_MAX_SECONDS,
) -> dict:
    """POST a chat completion request, retrying with exponential backoff on
    request errors or non-200 responses (honoring Retry-After if sent)."""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    attempt = 0
    while True:
        try:
            response = session.post(
                DEEPSEEK_API_URL,
                headers=headers,
                json=payload,
                timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            if attempt >= max_retries:
                raise
            delay = min(backoff_base * (2 ** attempt), backoff_max)
            logger.warning(
                "DeepSeek request error (%s); retrying in %.0fs (attempt %d/%d)",
                exc, delay, attempt + 1, max_retries,
            )
            time.sleep(delay)
            attempt += 1
            continue

        if response.status_code == 200:
            return response.json()

        if attempt >= max_retries:
            response.raise_for_status()
            raise requests.HTTPError(f"Non-200 status {response.status_code} from DeepSeek")

        retry_after = response.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else min(backoff_base * (2 ** attempt), backoff_max)
        except ValueError:
            delay = min(backoff_base * (2 ** attempt), backoff_max)

        logger.warning(
            "Got HTTP %d from DeepSeek; retrying in %.0fs (attempt %d/%d)",
            response.status_code, delay, attempt + 1, max_retries,
        )
        time.sleep(delay)
        attempt += 1


def _validate_topics(raw) -> List[str]:
    if not isinstance(raw, list):
        return [OTHER_TOPIC]
    valid = []
    for item in raw:
        if isinstance(item, str) and item.strip().lower() in _TOPIC_LEAVES:
            valid.append(_TOPIC_LEAVES[item.strip().lower()])
    return valid[:3] if valid else [OTHER_TOPIC]


def _group_topics_by_category(leaves: List[str]) -> Dict[str, List[str]]:
    """Group already-validated leaf topic labels into
    {category: [leaf, ...]} - the shape Event.topics is stored in, since
    it's what the database import wants (see schema.py's docstring)."""
    grouped: Dict[str, List[str]] = {}
    for leaf in leaves:
        category = TOPIC_LEAF_TO_CATEGORY.get(leaf.lower())
        if category is None:
            continue
        grouped.setdefault(category, []).append(leaf)
    return grouped


def _validate_event_type(raw) -> str:
    """Validate the model's event_type pick against the leaf taxonomy, then
    collapse it to its parent category - we only store the primary class
    (e.g. "Lecture" -> "Academic / Research"), not the specific leaf."""
    if isinstance(raw, str) and raw.strip().lower() in EVENT_TYPE_LEAF_TO_CATEGORY:
        return EVENT_TYPE_LEAF_TO_CATEGORY[raw.strip().lower()]
    return OTHER_EVENT_TYPE


def tag_event(
    event: Event,
    api_key: str,
    session: Optional[requests.Session] = None,
) -> Event:
    """Classify a single Event in place, setting event.topics and
    event.event_type. Falls back to the "Other" labels on any request or
    parsing failure rather than raising, so one bad event never blocks a
    batch."""
    session = session or requests.Session()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(event)},
    ]

    try:
        data = _post_with_retry(session, api_key, messages)
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (requests.RequestException, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed to tag event %r (%s); falling back to Other", event.title, exc)
        event.topics = _group_topics_by_category([OTHER_TOPIC])
        event.event_type = OTHER_EVENT_TYPE
        return event

    event.topics = _group_topics_by_category(_validate_topics(parsed.get("topics")))
    event.event_type = _validate_event_type(parsed.get("event_type"))
    return event


def load_events_from_json(path: str = DEFAULT_SAMPLE_PATH) -> List[Event]:
    """Load Events from a saved events JSON file, e.g. the output of
    fetch_events.fetch_sample_events / fetch_events.save_events_to_json."""
    with open(path, "r", encoding="utf-8") as fh:
        raw_events = json.load(fh)
    return [Event(**item) for item in raw_events]


def load_events_from_db() -> List[Event]:
    """Load Events from the database. Not wired up yet - postgre_io.py is
    still an empty placeholder with no read function to call."""
    raise NotImplementedError(
        "Loading events from the database isn't implemented yet "
        "(src/helpers/postgre_io.py has no read function). "
        "Use load_events_from_json() for now."
    )


def _group_by_event_id(events: List[Event]) -> Dict[int, List[Event]]:
    """Group events by event_id, preserving first-seen order of ids.
    Scraped feeds sometimes list the same event more than once (see the
    duplicate event_id 372167 entries in data/sample_events.json)."""
    groups: Dict[int, List[Event]] = {}
    for event in events:
        groups.setdefault(event.event_id, []).append(event)
    return groups


def tag_events(
    events: List[Event],
    api_key: Optional[str] = None,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
) -> List[Event]:
    """Classify a list of Events in place (e.g. the output of
    fetch_events.fetch_all_events) and return the same list.

    Events sharing the same event_id are only sent to the API once - the
    first occurrence is tagged, and the resulting topics/event_type are
    copied onto every other event with that id.
    """
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set")

    session = requests.Session()
    groups = _group_by_event_id(events)
    duplicate_count = len(events) - len(groups)
    if duplicate_count:
        logger.info(
            "Skipping %d duplicate event(s) by id; tagging %d unique event(s)",
            duplicate_count, len(groups),
        )

    for group in groups.values():
        representative, duplicates = group[0], group[1:]
        tag_event(representative, api_key, session)
        for duplicate in duplicates:
            duplicate.topics = {
                category: list(leaves) for category, leaves in representative.topics.items()
            }
            duplicate.event_type = representative.event_type
        if request_delay_seconds:
            time.sleep(request_delay_seconds)

    return events


def tag_sample_events(
    input_path: str = DEFAULT_SAMPLE_PATH,
    output_path: str = DEFAULT_TAGGED_SAMPLE_PATH,
    api_key: Optional[str] = None,
) -> List[Event]:
    """Load events from a saved sample_events.json, tag them (deduplicated
    by event_id), and write the tagged events to output_path. Standalone
    utility for local testing."""
    events = load_events_from_json(input_path)

    tag_events(events, api_key=api_key)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump([asdict(event) for event in events], fh, indent=2)
    logger.info("Tagged %d events -> %s", len(events), output_path)

    return events


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tag_sample_events()
