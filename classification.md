# Event classification spec

Defines how scraped TAMU calendar events (from `src/helpers/fetch_events.py`)
get tagged with `topics` and `event_type`, and the exact prompt sent to the
DeepSeek API to do it. `audience` is **not** tagged here — it's already
present in scraped data as `categories_audience`.

The taxonomy below is the human-readable copy for reference and review.
**`src/helpers/schema.py`'s `TOPIC_TAXONOMY` / `EVENT_TYPE_TAXONOMY` dicts
are the canonical source** — the prompt `tagging.py` sends to the model is
generated from those dicts, and `postgre_io.py` stores events against them
too (as per-category bitflags for `topics` - see schema.py's docstring).
If you change a label, change it in `schema.py` and mirror the edit here.

## Changes from the original draft taxonomy

- **`Economics`** was listed under both Business & Career and Social
  Sciences & Politics. Kept only under **Social Sciences & Politics** —
  Business & Career already covers the money side via Finance/Accounting.
- **`Leadership`** was listed under both Business & Career and Campus &
  Student Life with identical text, which is ambiguous to a classifier
  that only sees the label string. Renamed to **`Leadership Development`**
  (Business & Career — professional/organizational leadership training)
  and **`Student Leadership`** (Campus & Student Life — student org /
  campus leadership roles).
- Added three `event_type` leaves that TAMU's calendar plausibly needs but
  the original draft had no home for: **`Hackathon / Case Competition`**
  (under Workshop / Training), **`Fundraiser`**, and **`Religious /
  Worship Service`** (both under Social / Community).

## Output fields

| Field        | Cardinality | Stored as                                                       |
|--------------|-------------|------------------------------------------------------------------|
| `topics`     | 1-3 labels  | Leaf labels (multi-label; more than one only if genuinely interdisciplinary) |
| `event_type` | exactly 1   | **Top-level category only** — see below                          |

`topics` is stored at leaf granularity. `event_type` is not: the model is
still prompted with (and picks) a specific leaf (e.g. `"Lecture"`), since
that gives it a more concrete cue to reason from, but `tagging.py`'s
`_validate_event_type` immediately collapses that leaf to its parent
category (e.g. `"Lecture"` → `"Academic / Research"`, `"Commencement"` →
`"Ceremony / Tradition"`) before it's ever written onto the `Event` —
fine-grained event types turned out to be more depth than this needs.

The model never outputs a parent category directly for `topics` — `tagging.py`
derives it from the leaf via the taxonomy dict, so there's no risk of the
model picking a leaf/category pair that don't match. (Same idea for
`postgre_io.py`'s bitflag encoding of `topics`: it looks up each leaf's
category and bit position via `schema.py`, never trusts the model to name
a category directly.)

## Topic taxonomy

- **STEM & Technology**: Computer Science, Artificial Intelligence / Machine Learning, Data Science, Mathematics / Statistics, Physics, Chemistry, Biology / Life Sciences, Engineering, Materials Science, Information Technology, Robotics, Cybersecurity, Biotechnology, Other STEM
- **Health & Medicine**: Public Health, Medicine, Nursing, Mental Health & Wellness, Nutrition, Exercise / Fitness, Healthcare, Epidemiology, Biomedical Science, Disability / Accessibility, Other Health
- **Business & Career**: Business, Finance, Accounting, Marketing, Entrepreneurship, Management, Leadership Development, Career Development, Job Search / Recruiting, Professional Development, Industry / Corporate
- **Social Sciences & Politics**: Political Science, Government / Public Policy, Sociology, Psychology, Anthropology, International Relations, Communication, Social Justice, Community / Society, Economics
- **Humanities**: History, Philosophy, Literature, English, Languages, Linguistics, Religion, Classics, Ethics, Cultural Studies
- **Arts & Culture**: Visual Arts, Music, Theater, Dance, Film / Media, Photography, Creative Writing, Museums / Exhibitions, Cultural Events
- **Education**: Teaching, Pedagogy, Educational Research, Academic Success, Study Skills, Advising, Student Learning
- **Agriculture & Environment**: Agriculture, Agribusiness, Animal Science, Plant Science, Food Science, Environmental Science, Ecology, Sustainability, Climate, Natural Resources, Conservation, Horticulture
- **International & Cultural**: International Affairs, International Students, Global Studies, Cross-cultural, Cultural Heritage, Language / Culture
- **Campus & Student Life**: Student Life, Campus Community, Student Organizations, Volunteering, Community Service, Student Leadership, Traditions, Diversity & Inclusion, Residential Life
- **General / Interdisciplinary**: Interdisciplinary Research, General Academic, University-wide, General Interest, **Other / Uncategorized**

## Event type taxonomy

- **Academic / Research**: Lecture, Seminar, Colloquium, Research Talk, Guest Speaker, Panel Discussion, Research Presentation, Research Showcase
- **Conference / Large Academic Event**: Conference, Symposium, Summit, Convention, Research Conference, Academic Meeting
- **Workshop / Training**: Workshop, Hands-on Workshop, Training, Tutorial, Certification, Skill Development, Software / Technical Training, Hackathon / Case Competition
- **Career / Professional**: Career Fair, Job Fair, Employer Information Session, Recruiting Event, Networking, Resume / CV Workshop, Interview Preparation, Professional Development, Industry Talk, Graduate School Preparation
- **Student Organization**: Club Meeting, Organization Meeting, Student Group Event, Student Leadership, Organization Recruitment, Club Social
- **Social / Community**: Social, Mixer, Networking Social, Community Gathering, Party, Festival, Picnic, Game Night, Volunteer Event, Community Service, Fundraiser, Religious / Worship Service
- **Arts / Entertainment**: Concert, Musical Performance, Theater Performance, Dance Performance, Film Screening, Art Exhibition, Gallery Event, Cultural Performance
- **Sports / Recreation**: Sporting Event, Intramural, Club Sport, Fitness Class, Recreational Activity, Outdoor Activity, Tournament, Athletic Competition
- **Orientation / Recruitment**: New Student Orientation, Transfer Orientation, Graduate Orientation, Welcome Event, Admissions Event, Open House, Prospective Student Event, Recruitment Event
- **Health / Wellness**: Health Screening, Wellness Event, Fitness Event, Mental Health Workshop, Health Education, Medical / Health Consultation
- **Ceremony / Tradition**: Ceremony, Commencement, Memorial, University Tradition, Recognition, Award Ceremony, Dedication, Anniversary
- **Administrative / Information**: Information Session, Advising, Town Hall, Q&A, Office Hours, Policy Meeting, Administrative Meeting
- **Exhibition / Showcase**: Research Exhibition, Student Showcase, Project Showcase, Poster Session, Demonstration, Open Lab
- **Other**: Other, Unknown

## Prompt design

One DeepSeek API call per event (no batching), `temperature=0`,
`response_format={"type": "json_object"}`.

**System prompt** (taxonomy blocks are generated from the `schema.py`
dicts, one `"- Category: leaf, leaf, ..."` line per category):

```
You are a classifier for Texas A&M University calendar events.

Given an event's title, description, location, date, and source category, assign:
1. "topics": 1-3 labels from the TOPIC taxonomy below. Use more than one only if the event is genuinely interdisciplinary; prefer a single best-fitting topic.
2. "event_type": exactly 1 label from the EVENT_TYPE taxonomy below - the single best-fitting type.

Only output labels copied exactly (spelling, punctuation, capitalization) from the taxonomies below. Never invent a label. If nothing fits well, use "Other / Uncategorized" for topics or "Other" for event_type.

TOPIC taxonomy (category: leaf labels):
<generated from TOPIC_TAXONOMY>

EVENT_TYPE taxonomy (category: leaf labels):
<generated from EVENT_TYPE_TAXONOMY>

Respond with ONLY a single JSON object, no markdown fences, no explanation:
{"topics": ["<label>", ...], "event_type": "<label>"}
```

**User prompt** (per event):

```
Title: {title}
Source category: {categories joined by ", ", or "none"}
Location: {location or "unknown"}
Date: {date} {date_time}
Description: {description, truncated to 1500 chars, or "none"}
```

## Validation & fallback

The model's raw output is never trusted as-is:

- Each returned `topics` entry is matched case-insensitively against the
  full set of topic leaves; non-matching entries are dropped. If nothing
  survives, `topics` falls back to `["Other / Uncategorized"]`.
- `event_type` is matched case-insensitively against the full set of
  event-type *leaves*, then replaced with that leaf's parent category. If
  it doesn't match any leaf, it falls back to `"Other"` (which is both a
  leaf and its own category, so the fallback needs no separate mapping).
- Any request/parse failure (network error, malformed JSON, exhausted
  retries) falls back to the same `Other` values rather than dropping the
  event, so a bad API response never blocks tagging the rest of the batch.

## Cost notes

Uses `deepseek-v4-pro` — switched from `-flash` after early sample tagging
runs on `-flash` came out noticeably worse (mislabeled/near-miss picks
across the ~100-leaf taxonomy). `-pro` costs roughly 3x `-flash`, which is
still cheap for this task. The system prompt (taxonomy + instructions) is
a fixed prefix repeated on every call, which DeepSeek's API automatically
prompt-caches — after the first call, that prefix is billed at the much
cheaper cache-hit input rate on every subsequent event, so per-event cost
is dominated by the short user prompt and the small JSON output.

Events are also deduplicated by `event_id` before tagging (see below) —
scraped feeds sometimes list the same event more than once, and there's
no reason to pay for the same classification twice.

## Deduplication

`tag_events()` groups events by `event_id` before calling the API. Only
the first event in each group is actually classified; its `topics` /
`event_type` are then copied onto every other event sharing that id. This
is transparent to callers — `tag_events()` still returns every event that
was passed in, each with its tags filled in, just with fewer API calls
made than events tagged.

## Required environment variable

`DEEPSEEK_API_KEY` — must be set for `src/helpers/tagging.py` to run.
Either export it directly, or put it in a `.env` file at the repo root
(`DEEPSEEK_API_KEY=...`, no quotes needed) — `tagging.py` loads it
automatically via `python-dotenv`. `.env` is already gitignored.
