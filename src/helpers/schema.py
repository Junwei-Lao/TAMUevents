"""Data structures shared across the scraping/parsing/storage pipeline.

Topic taxonomy
--------------
`TOPIC_TAXONOMY` / `EVENT_TYPE_TAXONOMY` are the canonical taxonomy
definitions - the prompt `tagging.py` sends to DeepSeek is generated from
these dicts, and `postgre_io.py` stores events against them. See
classification.md at the repo root for the human-readable copy (keep it in
sync if these change).

`topics` is multi-label (an event can be 1-3 leaves) and is stored on
`Event.topics` pre-grouped by parent category - `{category: [leaf, ...]}`,
e.g. `{"Campus & Student Life": ["Traditions"]}` - rather than a flat list
of leaves, since that's the shape the database import wants (see below).
`tagging.py` is the one that groups the model's flat leaf picks into this
shape (via `TOPIC_LEAF_TO_CATEGORY`); the prompt itself is unaffected.

Keyword pass
------------
Tagging doesn't rely on the AI call alone. `TOPIC_KEYWORDS` /
`EVENT_TYPE_KEYWORDS` (below) derive matchable phrases straight from each
taxonomy leaf's own label - no separate keyword list to author or drift out
of sync - and `tagging.py` matches those phrases against an event's own
text *before* calling the AI, then joins both results. Catch-all leaves
("Other", "Unknown", "Other STEM", ...) get no phrases, since they exist
for the no-match case and shouldn't themselves be keyword-matched.

postgre_io.py doesn't store `topics` as one column per leaf (100+ leaves
across categories, several containing spaces/slashes/ampersands - not
valid bare SQL identifiers - and some leaf names, e.g. "Other", repeat
across categories) or a single TEXT[] (see the two functions below for why
bitflags won). Instead, each *top-level category* (there are only ~11,
they're stable, and their names are controlled by us, not scraped) becomes
one 32-bit integer column, and each leaf within that category is a bit
position - `encode_topic_flags`/`decode_topic_flags` convert between the
same `{category: [leaf, ...]}` shape as `Event.topics` and
`{category_column_name: bitmask}`. Storing multiple topics under the same
category is then just OR-ing their bits.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Event:
    """A fully-parsed TAMU calendar event, combining the feed listing entry
    with the fields pulled from its event-detail JSON."""

    event_id: int
    group_title: str
    url: str
    date: str
    date_time: str
    title: str
    description: Optional[str]
    location: Optional[str]
    categories: List[str] = field(default_factory=list)
    categories_audience: List[str] = field(default_factory=list)
    is_canceled: str = ""  # "" (or absent) means not canceled
    topics: Dict[str, List[str]] = field(default_factory=dict)  # {category: [leaf, ...]}, filled in by tagging.py
    event_type: str = ""  # filled in by tagging.py


@dataclass
class FeedVisitStatus:
    """Tracks when a group's JSON feed was last scraped, so feeds can be
    revisited on a fixed cadence (e.g. every 3-4 days) instead of every run."""

    group_title: str
    feed_url: str
    last_visited: str  # ISO 8601 timestamp
    event_count: int = 0


OTHER_TOPIC = "Other / Uncategorized"
OTHER_EVENT_TYPE = "Other"

TOPIC_TAXONOMY: Dict[str, List[str]] = {
    "STEM & Technology": [
        "Computer Science",
        "Artificial Intelligence / Machine Learning",
        "Data Science",
        "Mathematics / Statistics",
        "Physics",
        "Chemistry",
        "Biology / Life Sciences",
        "Engineering",
        "Materials Science",
        "Earth & Space Sciences",
        "Energy & Energy Systems",
        "Information Technology",
        "Robotics",
        "Cybersecurity",
        "Biotechnology",
        "Nanotechnology",
        "Other STEM",
    ],

    "Health & Medicine": [
        "Public Health",
        "Medicine",
        "Nursing",
        "Mental Health & Wellness",
        "Nutrition",
        "Healthcare",
        "Epidemiology",
        "Biomedical Science",
        "Disability / Accessibility",
        "Other Health",
    ],

    "Business & Career": [
        "Business",
        "Finance",
        "Accounting",
        "Marketing",
        "Entrepreneurship",
        "Management",
        "Leadership",
        "Career Development",
        "Job Search / Recruiting",
        "Professional Development",
        "Industry / Corporate",
        "Other Business",
    ],

    "Social Sciences & Politics": [
        "Political Science",
        "Government / Public Policy",
        "Sociology",
        "Psychology",
        "Anthropology",
        "International Relations",
        "Social Justice",
        "Community Studies",
        "Economics",
        "Other Social Sciences",
    ],

    "Humanities": [
        "History",
        "Philosophy",
        "Literature",
        "English",
        "Languages",
        "Linguistics",
        "Religion",
        "Classics",
        "Ethics",
        "Cultural Studies",
        "Other Humanities",
    ],

    "Arts & Culture": [
        "Visual Arts",
        "Music",
        "Theater",
        "Dance",
        "Film / Media",
        "Photography",
        "Creative Writing",
        "Museums / Exhibitions",
        "Cultural Heritage",
        "Other Arts & Culture",
    ],

    "Architecture & Design": [
        "Architecture",
        "Urban Planning",
        "Landscape Architecture",
        "Urban Design",
        "Interior Design",
        "Construction",
        "Real Estate / Built Environment",
        "Design",
        "Other Architecture & Design",
    ],

    "Law & Legal Studies": [
        "Law",
        "Legal Studies",
        "Criminal Justice",
        "Human Rights",
        "Legal Policy",
        "Other Law",
    ],

    "Education": [
        "Teaching",
        "Pedagogy",
        "Educational Research",
        "Academic Success",
        "Study Skills",
        "Advising",
        "Student Learning",
        "Other Education",
    ],

    "Agriculture & Environment": [
        "Agriculture",
        "Agribusiness",
        "Animal Science",
        "Plant Science",
        "Food Science",
        "Environmental Science",
        "Ecology",
        "Sustainability",
        "Climate",
        "Natural Resources",
        "Conservation",
        "Horticulture",
        "Other Agriculture & Environment",
    ],

    "International & Global Studies": [
        "International Affairs",
        "Global Studies",
        "International Development",
        "Cross-cultural Studies",
        "Global Affairs",
        "Other International & Global Studies",
    ],

    "Campus & Student Life": [
        "Student Life",
        "Campus Community",
        "Student Organizations",
        "Volunteering",
        "Community Service",
        "Student Leadership",
        "Traditions",
        "Diversity & Inclusion",
        "Residential Life",
        "Other Campus & Student Life",
    ],

    "Sports & Recreation": [
    "Athletics",
    "Gymnastics",
    "Fitness",
    "Sport Competitions / Tournaments",
    "Sport Science",
    "Other Sports & Recreation",
    ],

    "General / Interdisciplinary": [
        "Interdisciplinary Research",
        "General Academic",
        "General Interest",
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

# {lowercased leaf label: category}. event_type is single-label and only
# ever stored as its primary class (e.g. "Lecture" -> "Academic / Research"),
# not the specific leaf - see tagging.py's _validate_event_type - so unlike
# topics it needs no bit position, just this lookup.
EVENT_TYPE_LEAF_TO_CATEGORY: Dict[str, str] = {
    leaf.lower(): category
    for category, leaves in EVENT_TYPE_TAXONOMY.items()
    for leaf in leaves
}

_CATCHALL_LEAVES = {"other", "unknown"}


def _keyword_phrases_for_leaf(leaf: str) -> List[str]:
    """Derive matchable keyword phrases for a taxonomy leaf straight from
    its own label, rather than hand-authoring a separate keyword list that
    would drift out of sync - e.g. "Artificial Intelligence / Machine
    Learning" becomes ["artificial intelligence", "machine learning"].
    Catch-all leaves ("Other", "Unknown", "Other STEM", ...) get no
    phrases: they exist for the no-match case, so they should never
    themselves be keyword-matched."""
    lowered = leaf.strip().lower()
    if lowered in _CATCHALL_LEAVES or lowered.startswith("other "):
        return []
    return [phrase.strip() for phrase in leaf.split(" / ") if phrase.strip()]


def _build_keyword_index(taxonomy: Dict[str, List[str]]) -> Dict[str, List[str]]:
    return {
        leaf: _keyword_phrases_for_leaf(leaf)
        for leaves in taxonomy.values()
        for leaf in leaves
    }


# {leaf label: [matchable phrase, ...]}, used by tagging.py's keyword pass
# to pre-tag an event directly from its own text, before the AI ever sees
# it - see this module's docstring and classification.md's "Keyword pass"
# section.
TOPIC_KEYWORDS: Dict[str, List[str]] = _build_keyword_index(TOPIC_TAXONOMY)
EVENT_TYPE_KEYWORDS: Dict[str, List[str]] = _build_keyword_index(EVENT_TYPE_TAXONOMY)


def _slugify_category(category: str) -> str:
    """"STEM & Technology" -> "stem_technology" - used as both a Postgres
    column name (postgre_io.py) and a dict key, so it must be a valid bare
    SQL identifier."""
    return re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")


# {category: column_name}, e.g. "STEM & Technology" -> "stem_technology".
# One events_after_tagging column per entry - see postgre_io.py.
TOPIC_CATEGORY_COLUMNS: Dict[str, str] = {
    category: _slugify_category(category) for category in TOPIC_TAXONOMY
}

# {lowercased leaf label: category}. Used by tagging.py to group the
# model's flat leaf picks into Event.topics's {category: [leaf, ...]}
# shape. OTHER_TOPIC isn't itself a leaf in any category (it's the
# validation fallback value), so it's mapped in by hand onto the
# catch-all category rather than being silently ungroupable.
_OTHER_TOPIC_CATEGORY = "General / Interdisciplinary"
if _OTHER_TOPIC_CATEGORY not in TOPIC_TAXONOMY:
    raise ValueError(
        f"{_OTHER_TOPIC_CATEGORY!r} (the catch-all category OTHER_TOPIC maps to) "
        "is no longer in TOPIC_TAXONOMY - update _OTHER_TOPIC_CATEGORY above"
    )

TOPIC_LEAF_TO_CATEGORY: Dict[str, str] = {
    leaf.lower(): category
    for category, leaves in TOPIC_TAXONOMY.items()
    for leaf in leaves
}
TOPIC_LEAF_TO_CATEGORY.setdefault(OTHER_TOPIC.lower(), _OTHER_TOPIC_CATEGORY)

for _category, _leaves in TOPIC_TAXONOMY.items():
    if len(_leaves) > 32:
        raise ValueError(
            f"Category {_category!r} has {len(_leaves)} leaves, which overflows the "
            "32-bit flag column postgre_io.py stores it in"
        )


def encode_topic_flags(topics: Dict[str, List[str]]) -> Dict[str, int]:
    """Convert the {category: [leaf, ...]} topics shape (e.g. Event.topics)
    into {category_column_name: bitmask}, OR-ing together every leaf under
    the same category. Unrecognized categories/leaves are skipped.
    Categories with no matching topic are simply absent from the result -
    callers should treat a missing key as 0."""
    flags: Dict[str, int] = {}
    for category, leaves in topics.items():
        category_leaves = TOPIC_TAXONOMY.get(category)
        if category_leaves is None:
            continue
        column = TOPIC_CATEGORY_COLUMNS[category]
        for leaf in leaves:
            try:
                bit_index = category_leaves.index(leaf)
            except ValueError:
                continue
            flags[column] = flags.get(column, 0) | (1 << bit_index)
    return flags


def decode_topic_flags(flags: Dict[str, int]) -> Dict[str, List[str]]:
    """Inverse of encode_topic_flags: given {category_column_name: bitmask}
    (missing/zero entries are fine), return {category: [leaf, ...]} - the
    same shape as Event.topics - for every set bit."""
    topics: Dict[str, List[str]] = {}
    for category, leaves in TOPIC_TAXONOMY.items():
        mask = flags.get(TOPIC_CATEGORY_COLUMNS[category]) or 0
        if not mask:
            continue
        matched = [leaf for bit_index, leaf in enumerate(leaves) if mask & (1 << bit_index)]
        if matched:
            topics[category] = matched
    return topics
