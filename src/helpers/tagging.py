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
  3. Tag each representative event with two independent passes, then join
     their results rather than trusting the AI call alone:
       a. A keyword pass: match taxonomy leaf phrases (schema.py's
          TOPIC_KEYWORDS / EVENT_TYPE_KEYWORDS, derived straight from the
          taxonomy - see schema.py's docstring) directly against the
          event's own title/description/categories. Deterministic and
          free - it never fails and needs no network call.
       b. The DeepSeek AI pass: build a per-event prompt, call the chat
          completion API (JSON output mode), and validate the labels it
          returns against the closed taxonomy.
     topics is the union of both passes' leaves (regrouped by category).
     event_type prefers the AI's validated pick but falls back to the
     keyword pass's guess if the AI call fails or doesn't return a
     recognized leaf. Only falls back to "Other" if neither pass found
     anything.
  4. Write topics/event_type back onto the Event, and copy the same
     result onto every other Event sharing that event_id.
"""

import json
import logging
import os
import re
import time
from dataclasses import asdict
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

from schema import (
    EVENT_TYPE_KEYWORDS,
    EVENT_TYPE_LEAF_TO_CATEGORY,
    EVENT_TYPE_TAXONOMY,
    OTHER_EVENT_TYPE,
    OTHER_TOPIC,
    TOPIC_KEYWORDS,
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
# Cap on the final, merged (keyword + AI) topics list. Each pass is
# already bounded on its own (AI validates to at most 3; keyword matches
# are limited by how many taxonomy phrases actually appear in the text),
# but this is a sanity ceiling against a description that happens to hit a
# lot of taxonomy phrases at once.
MAX_MERGED_TOPICS = 5

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
        f'taxonomies below. Never invent a label. If nothing fits well, use "{OTHER_TOPIC}" '
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


def _compile_phrase(phrase: str) -> "re.Pattern[str]":
    return re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)


# {leaf: [compiled phrase pattern, ...]}, precompiled once from schema.py's
# TOPIC_KEYWORDS/EVENT_TYPE_KEYWORDS (which are themselves derived from the
# taxonomy - see schema.py's docstring). Catch-all leaves have no phrases,
# so they're never present as keys with any patterns to match.
_TOPIC_KEYWORD_PATTERNS: Dict[str, List["re.Pattern[str]"]] = {
    leaf: [_compile_phrase(phrase) for phrase in phrases]
    for leaf, phrases in TOPIC_KEYWORDS.items()
    if phrases
}
_EVENT_TYPE_KEYWORD_PATTERNS: Dict[str, List["re.Pattern[str]"]] = {
    leaf: [_compile_phrase(phrase) for phrase in phrases]
    for leaf, phrases in EVENT_TYPE_KEYWORDS.items()
    if phrases
}


def _keyword_search_text(event: Event) -> str:
    return " ".join([event.title or "", event.description or "", " ".join(event.categories)])


def _keyword_match_topics(event: Event) -> List[str]:
    """Match taxonomy leaf phrases directly against the event's own text.
    Deterministic and free - this never fails, unlike the AI call, so it's
    the first pass run and the one event_type falls back to below."""
    text = _keyword_search_text(event)
    return [
        leaf
        for leaf, patterns in _TOPIC_KEYWORD_PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    ]


def _keyword_match_event_type(event: Event) -> Optional[str]:
    """Best-effort event_type leaf guess from keyword matches. Title
    matches are checked first and preferred over description/category-only
    matches; ties are broken by taxonomy declaration order in schema.py.
    Returns a leaf (or None if nothing matched) - the caller collapses it
    to a category the same way the AI's pick is, via _validate_event_type.
    """
    title = event.title or ""
    for leaf, patterns in _EVENT_TYPE_KEYWORD_PATTERNS.items():
        if any(pattern.search(title) for pattern in patterns):
            return leaf

    text = _keyword_search_text(event)
    for leaf, patterns in _EVENT_TYPE_KEYWORD_PATTERNS.items():
        if any(pattern.search(text) for pattern in patterns):
            return leaf

    return None


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


def _merge_topic_leaves(keyword_leaves: List[str], ai_leaves: List[str]) -> List[str]:
    """Union the keyword pass's matches with the AI pass's validated picks,
    deduping while preserving order (keyword hits first, since they're
    grounded directly in the event's own text). The AI's own OTHER_TOPIC
    placeholder means "the AI found nothing", not a real topic, so it's
    dropped from the merge rather than unioned in - it should never
    survive alongside a genuine match from either pass. Falls back to
    OTHER_TOPIC only if neither pass found anything; otherwise capped at
    MAX_MERGED_TOPICS."""
    ai_leaves = [leaf for leaf in ai_leaves if leaf != OTHER_TOPIC]
    merged = list(dict.fromkeys(keyword_leaves + ai_leaves))
    return merged[:MAX_MERGED_TOPICS] if merged else [OTHER_TOPIC]


def _validate_event_type(raw, fallback_leaf: Optional[str] = None) -> str:
    """Validate the model's event_type pick against the leaf taxonomy, then
    collapse it to its parent category - we only store the primary class
    (e.g. "Lecture" -> "Academic / Research"), not the specific leaf. If
    the model's pick doesn't validate (missing, malformed, or the AI call
    failed outright), falls back to the keyword pass's leaf guess instead
    of going straight to "Other" - so a single bad/uncertain AI response
    doesn't throw away a solid keyword-only signal."""
    for candidate in (raw, fallback_leaf):
        if isinstance(candidate, str) and candidate.strip().lower() in EVENT_TYPE_LEAF_TO_CATEGORY:
            return EVENT_TYPE_LEAF_TO_CATEGORY[candidate.strip().lower()]
    return OTHER_EVENT_TYPE


def tag_event(
    event: Event,
    api_key: str,
    session: Optional[requests.Session] = None,
) -> Event:
    """Classify a single Event in place, setting event.topics and
    event.event_type.

    Runs a keyword pass and the DeepSeek AI pass, then joins their results
    rather than trusting the AI call alone (see this module's docstring).
    The keyword pass runs first and unconditionally - it's free and can't
    fail - so even a total AI request failure still leaves the event with
    whatever the keyword pass found, instead of a blind "Other".
    """
    keyword_topic_leaves = _keyword_match_topics(event)
    keyword_event_type_leaf = _keyword_match_event_type(event)

    session = session or requests.Session()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(event)},
    ]

    ai_topic_leaves: List[str] = []
    ai_event_type_raw: Optional[str] = None
    try:
        data = _post_with_retry(session, api_key, messages)
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (requests.RequestException, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        logger.warning(
            "DeepSeek tagging failed for event %r (%s); falling back to the keyword pass",
            event.title, exc,
        )
    else:
        ai_topic_leaves = _validate_topics(parsed.get("topics"))
        ai_event_type_raw = parsed.get("event_type")

    merged_leaves = _merge_topic_leaves(keyword_topic_leaves, ai_topic_leaves)
    event.topics = _group_topics_by_category(merged_leaves)
    event.event_type = _validate_event_type(ai_event_type_raw, fallback_leaf=keyword_event_type_leaf)
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
