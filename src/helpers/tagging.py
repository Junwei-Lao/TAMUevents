"""Tags scraped TAMU calendar events with `topics` and `event_type` via the
DeepSeek API.

The taxonomy and prompt design are documented in classification.md at the
repo root; the dicts below are the canonical copy that prompt is generated
from (keep classification.md in sync if these change).

The API key is read from the DEEPSEEK_API_KEY environment variable, which
can either be set directly or provided via a .env file at the repo root
(loaded automatically on import; a real environment variable always takes
priority over .env if both are set).

Pipeline:
  1. Take Event objects, e.g. the output of fetch_events.py, or loaded from
     a saved sample_events.json.
  2. Build a per-event prompt from its title/description/location/date/
     source categories.
  3. Call DeepSeek's chat completion API (JSON output mode) and validate
     the labels it returns against the closed taxonomy, falling back to
     "Other" on anything invalid or on a request failure.
  4. Write topics/event_type back onto the Event.
"""

import json
import logging
import os
import time
from dataclasses import asdict
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

from schema import Event

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"
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

OTHER_TOPIC = "Other / Uncategorized"
OTHER_EVENT_TYPE = "Other"

TOPIC_TAXONOMY: Dict[str, List[str]] = {
    "STEM & Technology": [
        "Computer Science", "Artificial Intelligence / Machine Learning", "Data Science",
        "Mathematics / Statistics", "Physics", "Chemistry", "Biology / Life Sciences",
        "Engineering", "Materials Science", "Information Technology", "Robotics",
        "Cybersecurity", "Biotechnology", "Other STEM",
    ],
    "Health & Medicine": [
        "Public Health", "Medicine", "Nursing", "Mental Health & Wellness", "Nutrition",
        "Exercise / Fitness", "Healthcare", "Epidemiology", "Biomedical Science",
        "Disability / Accessibility", "Other Health",
    ],
    "Business & Career": [
        "Business", "Finance", "Accounting", "Marketing", "Entrepreneurship", "Management",
        "Leadership Development", "Career Development", "Job Search / Recruiting",
        "Professional Development", "Industry / Corporate",
    ],
    "Social Sciences & Politics": [
        "Political Science", "Government / Public Policy", "Sociology", "Psychology",
        "Anthropology", "International Relations", "Communication", "Social Justice",
        "Community / Society", "Economics",
    ],
    "Humanities": [
        "History", "Philosophy", "Literature", "English", "Languages", "Linguistics",
        "Religion", "Classics", "Ethics", "Cultural Studies",
    ],
    "Arts & Culture": [
        "Visual Arts", "Music", "Theater", "Dance", "Film / Media", "Photography",
        "Creative Writing", "Museums / Exhibitions", "Cultural Events",
    ],
    "Education": [
        "Teaching", "Pedagogy", "Educational Research", "Academic Success", "Study Skills",
        "Advising", "Student Learning",
    ],
    "Agriculture & Environment": [
        "Agriculture", "Agribusiness", "Animal Science", "Plant Science", "Food Science",
        "Environmental Science", "Ecology", "Sustainability", "Climate", "Natural Resources",
        "Conservation", "Horticulture",
    ],
    "International & Cultural": [
        "International Affairs", "International Students", "Global Studies",
        "Cross-cultural", "Cultural Heritage", "Language / Culture",
    ],
    "Campus & Student Life": [
        "Student Life", "Campus Community", "Student Organizations", "Volunteering",
        "Community Service", "Student Leadership", "Traditions", "Diversity & Inclusion",
        "Residential Life",
    ],
    "General / Interdisciplinary": [
        "Interdisciplinary Research", "General Academic", "University-wide",
        "General Interest", OTHER_TOPIC,
    ],
}

EVENT_TYPE_TAXONOMY: Dict[str, List[str]] = {
    "Academic / Research": [
        "Lecture", "Seminar", "Colloquium", "Research Talk", "Guest Speaker",
        "Panel Discussion", "Research Presentation", "Research Showcase",
    ],
    "Conference / Large Academic Event": [
        "Conference", "Symposium", "Summit", "Convention", "Research Conference",
        "Academic Meeting",
    ],
    "Workshop / Training": [
        "Workshop", "Hands-on Workshop", "Training", "Tutorial", "Certification",
        "Skill Development", "Software / Technical Training", "Hackathon / Case Competition",
    ],
    "Career / Professional": [
        "Career Fair", "Job Fair", "Employer Information Session", "Recruiting Event",
        "Networking", "Resume / CV Workshop", "Interview Preparation",
        "Professional Development", "Industry Talk", "Graduate School Preparation",
    ],
    "Student Organization": [
        "Club Meeting", "Organization Meeting", "Student Group Event", "Student Leadership",
        "Organization Recruitment", "Club Social",
    ],
    "Social / Community": [
        "Social", "Mixer", "Networking Social", "Community Gathering", "Party", "Festival",
        "Picnic", "Game Night", "Volunteer Event", "Community Service", "Fundraiser",
        "Religious / Worship Service",
    ],
    "Arts / Entertainment": [
        "Concert", "Musical Performance", "Theater Performance", "Dance Performance",
        "Film Screening", "Art Exhibition", "Gallery Event", "Cultural Performance",
    ],
    "Sports / Recreation": [
        "Sporting Event", "Intramural", "Club Sport", "Fitness Class",
        "Recreational Activity", "Outdoor Activity", "Tournament", "Athletic Competition",
    ],
    "Orientation / Recruitment": [
        "New Student Orientation", "Transfer Orientation", "Graduate Orientation",
        "Welcome Event", "Admissions Event", "Open House", "Prospective Student Event",
        "Recruitment Event",
    ],
    "Health / Wellness": [
        "Health Screening", "Wellness Event", "Fitness Event", "Mental Health Workshop",
        "Health Education", "Medical / Health Consultation",
    ],
    "Ceremony / Tradition": [
        "Ceremony", "Commencement", "Memorial", "University Tradition", "Recognition",
        "Award Ceremony", "Dedication", "Anniversary",
    ],
    "Administrative / Information": [
        "Information Session", "Advising", "Town Hall", "Q&A", "Office Hours",
        "Policy Meeting", "Administrative Meeting",
    ],
    "Exhibition / Showcase": [
        "Research Exhibition", "Student Showcase", "Project Showcase", "Poster Session",
        "Demonstration", "Open Lab",
    ],
    "Other": [OTHER_EVENT_TYPE, "Unknown"],
}


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
_EVENT_TYPE_LEAVES = {
    leaf.lower(): leaf for leaves in EVENT_TYPE_TAXONOMY.values() for leaf in leaves
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


def _validate_event_type(raw) -> str:
    if isinstance(raw, str) and raw.strip().lower() in _EVENT_TYPE_LEAVES:
        return _EVENT_TYPE_LEAVES[raw.strip().lower()]
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
        event.topics = [OTHER_TOPIC]
        event.event_type = OTHER_EVENT_TYPE
        return event

    event.topics = _validate_topics(parsed.get("topics"))
    event.event_type = _validate_event_type(parsed.get("event_type"))
    return event


def tag_events(
    events: List[Event],
    api_key: Optional[str] = None,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
) -> List[Event]:
    """Classify a list of Events in place (e.g. the output of
    fetch_events.fetch_all_events) and return the same list."""
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set")

    session = requests.Session()
    for event in events:
        tag_event(event, api_key, session)
        if request_delay_seconds:
            time.sleep(request_delay_seconds)

    return events


def tag_sample_events(
    input_path: str = DEFAULT_SAMPLE_PATH,
    output_path: str = DEFAULT_TAGGED_SAMPLE_PATH,
    api_key: Optional[str] = None,
) -> List[Event]:
    """Load events from a saved sample_events.json (e.g. from
    fetch_events.fetch_sample_events), tag them, and write the tagged
    events to output_path. Standalone utility for local testing."""
    with open(input_path, "r", encoding="utf-8") as fh:
        raw_events = json.load(fh)
    events = [Event(**item) for item in raw_events]

    tag_events(events, api_key=api_key)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump([asdict(event) for event in events], fh, indent=2)
    logger.info("Tagged %d events -> %s", len(events), output_path)

    return events


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tag_sample_events()
