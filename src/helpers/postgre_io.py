"""Initializes and populates the Postgres store for tagged TAMU events.

Schema design
-------------
Two tables, split along the same line as the pipeline itself:

- `events_before_tagging` holds every field `fetch_events.py` scrapes
  (nothing tagging.py touches).
- `events_after_tagging` holds only what `tagging.py` adds (`topics`,
  `event_type`), one row per event, FK'd back to the first table.

Both tables key on `(event_id, date, date_time)`, not `event_id` alone -
`fetch_events._merge_events` already treats that triple as an event's real
identity (recurring events reuse the same `event_id` across occurrences),
so the DB's primary key mirrors it to avoid silently collapsing distinct
occurrences into one row.

`categories` and `categories_audience` are scraped free text, but in
practice TAMU's calendar draws them from a small, fairly fixed set (see
the sample data: audience values are consistently things like "Faculty",
"Staff", "Students", ...). Rather than pivoting that vocabulary into
per-value columns - which breaks the moment a value has a space/slash/
ampersand in it (not a valid bare SQL identifier) or two taxonomies both
happen to use the same value (e.g. "Other") - each is kept as a Postgres
`TEXT[]` column, GIN-indexed for containment queries. The *pool* of
distinct values seen across all tagged events is additionally written to
its own small lookup table (`category_pool` / `audience_pool`), discovered
by scanning events_tagged.json up front. That pool isn't there to
constrain the array columns (Postgres can't FK into an array element
without a trigger, so it's not enforced) - it exists so the app can query
"what filter values exist" in O(1) instead of scanning every event.

`event_type` doesn't need a discovered pool either: its taxonomy is fixed
in code (`schema.py`'s EVENT_TYPE_TAXONOMY), so it's stored as plain TEXT
- it's single-valued (exactly one label per event), so there's no OR-ing
to do and TEXT is already unambiguous.

`topics` (1-3 labels per event) is stored differently: one 32-bit INTEGER
column per *top-level* topic category (`schema.TOPIC_CATEGORY_COLUMNS`,
e.g. "STEM & Technology" -> `stem_technology`), with each leaf under that
category assigned a bit position (`schema.encode_topic_flags` /
`decode_topic_flags`). There are only ~14 categories, they're stable, and
their names are controlled by us - not the 100+ scraped-ish leaf values -
so turning *them* into columns doesn't hit the naming-conflict problem a
column-per-leaf design would. Multiple topics under one category are just
OR'd into that category's column; reading a row back OR's nothing, it
just decodes each column's set bits back into leaf labels.

`date` is scraped free text ("December 11 - December 12, 2026", "Sep 11th,
2026", ...) and is never reliably comparable/sortable as-is, so it's kept
verbatim (also part of the identity key, see above) *and* parsed by
`parse_event_date_range` into real `start_date` / `end_date DATE` columns
for range queries. Parsing is best-effort (python-dateutil) and never
blocks storage - an unparseable date just leaves start_date/end_date NULL.
"""

import json
import logging
import os
import re
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Set, Tuple

import psycopg2
from dateutil import parser as date_parser
from psycopg2 import sql
from psycopg2.extras import execute_values, RealDictCursor
from dotenv import load_dotenv

from schema import TOPIC_CATEGORY_COLUMNS, decode_topic_flags, encode_topic_flags

logger = logging.getLogger(__name__)

# Ordered list of the per-category topic bitflag column names, e.g.
# "stem_technology", "health_medicine", ... - shared by table DDL, the
# upsert's INSERT column list, and the SELECT that joins events back out.
_TOPIC_COLUMNS: List[str] = list(TOPIC_CATEGORY_COLUMNS.values())

DEFAULT_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
DEFAULT_TAGGED_EVENTS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "events_tagged.json"
)

DB_NAME = "TAMU_events_storage_db"
# Only used to open a connection capable of issuing CREATE DATABASE - never
# read from or written to otherwise.
MAINTENANCE_DB_NAME = "postgres"

# Loads db_username/db_password (and anything else) from .env into
# os.environ, if present. A real environment variable always wins over
# whatever's in .env.
load_dotenv(DEFAULT_ENV_PATH)


def _get_connection_params(dbname: str) -> Dict[str, str]:
    user = os.environ.get("db_username")
    password = os.environ.get("db_password")
    if not user or not password:
        raise RuntimeError(
            "db_username / db_password environment variables are not set "
            "(set them directly or via a .env file at the repo root)"
        )
    return {
        "host": os.environ.get("db_host", "localhost"),
        "port": os.environ.get("db_port", "5432"),
        "user": user,
        "password": password,
        "dbname": dbname,
    }


def load_tagged_events(path: str = DEFAULT_TAGGED_EVENTS_PATH) -> List[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build_pool(events: Sequence[dict], field: str) -> List[str]:
    """Scan every event's `field` (a list-valued field, e.g. "categories")
    and return the sorted set of distinct values seen."""
    pool: Set[str] = set()
    for event in events:
        for value in event.get(field) or []:
            if value:
                pool.add(value)
    return sorted(pool)


_ORDINAL_SUFFIX_RE = re.compile(r"(\d+)(st|nd|rd|th)\b", re.IGNORECASE)
_RANGE_SPLIT_RE = re.compile(r"\s*(?:-|–|—|\bto\b|\bthrough\b)\s*", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def parse_event_date_range(raw_date: str) -> Tuple[Optional[date], Optional[date]]:
    """Best-effort parse of the free-text `date` field scraped from TAMU's
    calendar - e.g. "December 11 - December 12, 2026", "Sep 11th, 2026",
    "September 11th - 12th, 2026" - into a (start_date, end_date) pair.

    The two sides of a range are rarely both "complete": one side often
    carries the year, the other the month, e.g. "September 11 - 12, 2026"
    has no month on the right. So the left side is parsed first (using
    whatever 4-digit year appears anywhere in the string as a fallback),
    then the right side is parsed with the left side's result as
    dateutil's `default` - filling in any field (month/year) the right
    side doesn't spell out itself.

    Returns (None, None) if the text can't be parsed at all. Callers
    should treat that as "unknown", not drop the event - the raw text
    always stays in the `date` column regardless of whether this parses.
    """
    if not raw_date or not raw_date.strip():
        return None, None

    cleaned = _ORDINAL_SUFFIX_RE.sub(r"\1", raw_date)
    parts = [p for p in _RANGE_SPLIT_RE.split(cleaned) if p.strip()]

    year_match = _YEAR_RE.search(cleaned)
    anchor = datetime(int(year_match.group()), 1, 1) if year_match else datetime.now()

    try:
        start_dt = date_parser.parse(parts[0], fuzzy=True, default=anchor)
        if len(parts) == 1:
            return start_dt.date(), start_dt.date()

        end_part = parts[-1]
        if re.search(r"[A-Za-z]{3,}", end_part):
            # End side spells out its own month (e.g. "December 12, 2026") -
            # safe to let dateutil fill in whatever it's missing from
            # start_dt.
            end_dt = date_parser.parse(end_part, fuzzy=True, default=start_dt)
        else:
            # End side is day-only (e.g. "12" or "12, 2026"). dateutil can
            # misread a lone number as a *month* when a default day is
            # already set (it fills the day slot from the default instead
            # of the string), so pull the day/year out directly instead of
            # trusting its month/day assignment.
            day_match = re.search(r"\d{1,2}", end_part)
            end_day = int(day_match.group()) if day_match else start_dt.day
            end_year_match = _YEAR_RE.search(end_part)
            end_year = int(end_year_match.group()) if end_year_match else start_dt.year
            end_dt = start_dt.replace(year=end_year, day=end_day)

        # A "December 30 - January 2, 2027" style range with no year on the
        # left: the only year mentioned belongs to January (the end), so
        # December must be the year before it.
        if end_dt < start_dt and not _YEAR_RE.search(parts[0]):
            start_dt = start_dt.replace(year=start_dt.year - 1)

        return start_dt.date(), end_dt.date()
    except (ValueError, OverflowError) as exc:
        logger.warning("Could not parse date %r (%s)", raw_date, exc)
        return None, None


def create_database_if_not_exists(dbname: str = DB_NAME) -> None:
    """Connects to the `postgres` maintenance database and creates `dbname`
    if it doesn't already exist. Postgres has no `CREATE DATABASE IF NOT
    EXISTS`, so existence is checked via pg_database first."""
    conn = psycopg2.connect(**_get_connection_params(MAINTENANCE_DB_NAME))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if cur.fetchone() is None:
                # sql.Identifier quotes the name so its case is preserved
                # exactly as given - CREATE DATABASE would otherwise fold
                # an unquoted mixed-case name to lowercase.
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
                logger.info("Created database %r", dbname)
            else:
                logger.info("Database %r already exists", dbname)
    finally:
        conn.close()


def connect(dbname: str = DB_NAME):
    return psycopg2.connect(**_get_connection_params(dbname))


def create_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS category_pool (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audience_pool (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events_before_tagging (
                event_id BIGINT NOT NULL,
                date TEXT NOT NULL DEFAULT '',
                date_time TEXT NOT NULL DEFAULT '',
                start_date DATE,
                end_date DATE,
                group_title TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                location TEXT,
                categories TEXT[] NOT NULL DEFAULT '{}',
                categories_audience TEXT[] NOT NULL DEFAULT '{}',
                is_canceled TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (event_id, date, date_time)
            )
            """
        )
        topic_flag_columns = ",\n                ".join(
            f"{column} INTEGER NOT NULL DEFAULT 0" for column in _TOPIC_COLUMNS
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS events_after_tagging (
                event_id BIGINT NOT NULL,
                date TEXT NOT NULL DEFAULT '',
                date_time TEXT NOT NULL DEFAULT '',
                {topic_flag_columns},
                event_type TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (event_id, date, date_time),
                FOREIGN KEY (event_id, date, date_time)
                    REFERENCES events_before_tagging (event_id, date, date_time)
                    ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_before_start_date "
            "ON events_before_tagging (start_date)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_before_categories "
            "ON events_before_tagging USING GIN (categories)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_before_categories_audience "
            "ON events_before_tagging USING GIN (categories_audience)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_after_event_type "
            "ON events_after_tagging (event_type)"
        )
    conn.commit()


def populate_pools(conn, category_pool: Sequence[str], audience_pool: Sequence[str]) -> None:
    with conn.cursor() as cur:
        if category_pool:
            execute_values(
                cur,
                "INSERT INTO category_pool (name) VALUES %s ON CONFLICT (name) DO NOTHING",
                [(name,) for name in category_pool],
            )
        if audience_pool:
            execute_values(
                cur,
                "INSERT INTO audience_pool (name) VALUES %s ON CONFLICT (name) DO NOTHING",
                [(name,) for name in audience_pool],
            )
    conn.commit()
    logger.info(
        "Populated pools: %d categories, %d audiences", len(category_pool), len(audience_pool)
    )


def upsert_events(conn, events: Sequence[dict]) -> None:
    # A single multi-row INSERT ... ON CONFLICT DO UPDATE can't target the
    # same conflicting row twice in one statement, so collapse any
    # duplicate (event_id, date, date_time) keys up front - last one wins,
    # mirroring fetch_events._merge_events's "fresh data wins" behavior.
    deduped: Dict[Tuple, dict] = {}
    for e in events:
        key = (e["event_id"], e.get("date") or "", e.get("date_time") or "")
        deduped[key] = e
    events = list(deduped.values())

    before_rows = []
    for e in events:
        raw_date = e.get("date") or ""
        start_date, end_date = parse_event_date_range(raw_date)
        before_rows.append(
            (
                e["event_id"],
                raw_date,
                e.get("date_time") or "",
                start_date,
                end_date,
                e["group_title"],
                e["url"],
                e["title"],
                e.get("description"),
                e.get("location"),
                e.get("categories") or [],
                e.get("categories_audience") or [],
                e.get("is_canceled") or "",
            )
        )
    after_rows = []
    for e in events:
        flags = encode_topic_flags(e.get("topics") or [])
        row = [e["event_id"], e.get("date") or "", e.get("date_time") or ""]
        row.extend(flags.get(column, 0) for column in _TOPIC_COLUMNS)
        row.append(e.get("event_type") or "")
        after_rows.append(tuple(row))

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO events_before_tagging
                (event_id, date, date_time, start_date, end_date, group_title, url, title,
                 description, location, categories, categories_audience, is_canceled)
            VALUES %s
            ON CONFLICT (event_id, date, date_time) DO UPDATE SET
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                group_title = EXCLUDED.group_title,
                url = EXCLUDED.url,
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                location = EXCLUDED.location,
                categories = EXCLUDED.categories,
                categories_audience = EXCLUDED.categories_audience,
                is_canceled = EXCLUDED.is_canceled
            """,
            before_rows,
        )
        after_columns = ["event_id", "date", "date_time"] + _TOPIC_COLUMNS + ["event_type"]
        after_set_clause = ",\n                ".join(
            f"{column} = EXCLUDED.{column}" for column in _TOPIC_COLUMNS + ["event_type"]
        )
        execute_values(
            cur,
            f"""
            INSERT INTO events_after_tagging ({", ".join(after_columns)})
            VALUES %s
            ON CONFLICT (event_id, date, date_time) DO UPDATE SET
                {after_set_clause}
            """,
            after_rows,
        )
    conn.commit()
    logger.info("Upserted %d events into events_before_tagging / events_after_tagging", len(events))


_AFTER_TOPIC_COLUMNS_SELECT = ", ".join(f"a.{column}" for column in _TOPIC_COLUMNS)
_JOINED_EVENT_SELECT = f"""
    SELECT b.*, {_AFTER_TOPIC_COLUMNS_SELECT}, a.event_type
    FROM events_after_tagging a
    JOIN events_before_tagging b
        ON b.event_id = a.event_id
        AND b.date = a.date
        AND b.date_time = a.date_time
"""


def _attach_decoded_topics(rows: List[dict]) -> List[dict]:
    """Decode each row's per-category bitflag columns back into a friendly
    `topics` list (leaving the raw bitflag columns in place too, for
    callers that want them)."""
    for row in rows:
        row["topics"] = decode_topic_flags({col: row[col] for col in _TOPIC_COLUMNS})
    return rows


def get_events_by_topics(
    topics: Sequence[str], match_all: bool = False, conn=None
) -> List[dict]:
    """Return events (before+after tagging fields merged, with a decoded
    `topics` list attached) tagged with at least one of `topics`
    (match_all=False, the default) or with all of them (match_all=True).

    `topics` is translated to {category_column: bitmask} first
    (schema.encode_topic_flags), since a topic list can span multiple
    category columns - match_any becomes `(col & mask) <> 0` OR'd across
    those columns, match_all becomes `(col & mask) = mask` AND'd across
    them (bitwise "contains" within a column, since more than one leaf
    under the same category could be requested at once).
    """
    flags = encode_topic_flags(list(topics))
    if not flags:
        return []

    owns_conn = conn is None
    conn = conn or connect()
    try:
        if match_all:
            conditions = [f"(a.{column} & %s) = %s" for column in flags]
            params: List[int] = []
            for mask in flags.values():
                params.extend([mask, mask])
            joiner = " AND "
        else:
            conditions = [f"(a.{column} & %s) <> 0" for column in flags]
            params = list(flags.values())
            joiner = " OR "

        query = _JOINED_EVENT_SELECT + " WHERE " + joiner.join(conditions) + " ORDER BY b.event_id"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = [dict(row) for row in cur.fetchall()]
        return _attach_decoded_topics(rows)
    finally:
        if owns_conn:
            conn.close()


def get_events_by_event_type(event_type: str, conn=None) -> List[dict]:
    owns_conn = conn is None
    conn = conn or connect()
    try:
        query = _JOINED_EVENT_SELECT + " WHERE a.event_type = %s ORDER BY b.event_id"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (event_type,))
            rows = [dict(row) for row in cur.fetchall()]
        return _attach_decoded_topics(rows)
    finally:
        if owns_conn:
            conn.close()


def list_topics_in_use(conn=None) -> List[str]:
    """Distinct topic leaf labels actually present in events_after_tagging
    - decoded from the OR of every row's bitflags per category (Postgres's
    `bit_or` aggregate). Unlike categories/categories_audience, topics
    don't get a precomputed pool table (their taxonomy already lives in
    schema.py) - this is the equivalent lookup for building a topic filter
    UI on demand."""
    owns_conn = conn is None
    conn = conn or connect()
    try:
        select_cols = ", ".join(f"bit_or({column}) AS {column}" for column in _TOPIC_COLUMNS)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT {select_cols} FROM events_after_tagging")
            row = cur.fetchone()
        flags = {column: (row[column] or 0) for column in _TOPIC_COLUMNS} if row else {}
        return decode_topic_flags(flags)
    finally:
        if owns_conn:
            conn.close()


def get_events_in_date_range(
    range_start: date, range_end: date, conn=None
) -> List[dict]:
    """Return events (before+after tagging fields merged) whose
    [start_date, end_date] interval overlaps [range_start, range_end].
    Events with unparseable dates (start_date IS NULL) are excluded, since
    there's nothing to compare against."""
    owns_conn = conn is None
    conn = conn or connect()
    try:
        query = (
            _JOINED_EVENT_SELECT
            + """
            WHERE b.start_date IS NOT NULL
                AND b.start_date <= %s
                AND COALESCE(b.end_date, b.start_date) >= %s
            ORDER BY b.start_date
            """
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (range_end, range_start))
            rows = [dict(row) for row in cur.fetchall()]
        return _attach_decoded_topics(rows)
    finally:
        if owns_conn:
            conn.close()


def initialize_database(
    json_path: str = DEFAULT_TAGGED_EVENTS_PATH, dbname: str = DB_NAME
) -> None:
    """End-to-end setup: load data/events_tagged.json, discover the
    categories/categories_audience pools, create the database and tables if
    they don't exist yet, and load everything in."""
    events = load_tagged_events(json_path)
    logger.info("Loaded %d tagged events from %s", len(events), json_path)

    category_pool = build_pool(events, "categories")
    audience_pool = build_pool(events, "categories_audience")
    logger.info(
        "Discovered %d distinct categories, %d distinct audiences",
        len(category_pool),
        len(audience_pool),
    )

    create_database_if_not_exists(dbname)

    conn = connect(dbname)
    try:
        create_tables(conn)
        populate_pools(conn, category_pool, audience_pool)
        upsert_events(conn, events)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    initialize_database()
