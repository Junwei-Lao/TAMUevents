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

`topics` / `event_type` don't need a discovered pool: their taxonomy is
already fixed in code (`tagging.py`'s TOPIC_TAXONOMY / EVENT_TYPE_TAXONOMY),
so they're stored the same way (TEXT[] / TEXT) without a mirrored lookup
table.
"""

import json
import logging
import os
from typing import Dict, List, Sequence, Set

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values, RealDictCursor
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events_after_tagging (
                event_id BIGINT NOT NULL,
                date TEXT NOT NULL DEFAULT '',
                date_time TEXT NOT NULL DEFAULT '',
                topics TEXT[] NOT NULL DEFAULT '{}',
                event_type TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (event_id, date, date_time),
                FOREIGN KEY (event_id, date, date_time)
                    REFERENCES events_before_tagging (event_id, date, date_time)
                    ON DELETE CASCADE
            )
            """
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
            "CREATE INDEX IF NOT EXISTS idx_events_after_topics "
            "ON events_after_tagging USING GIN (topics)"
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
    before_rows = [
        (
            e["event_id"],
            e.get("date") or "",
            e.get("date_time") or "",
            e["group_title"],
            e["url"],
            e["title"],
            e.get("description"),
            e.get("location"),
            e.get("categories") or [],
            e.get("categories_audience") or [],
            e.get("is_canceled") or "",
        )
        for e in events
    ]
    after_rows = [
        (
            e["event_id"],
            e.get("date") or "",
            e.get("date_time") or "",
            e.get("topics") or [],
            e.get("event_type") or "",
        )
        for e in events
    ]

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO events_before_tagging
                (event_id, date, date_time, group_title, url, title,
                 description, location, categories, categories_audience, is_canceled)
            VALUES %s
            ON CONFLICT (event_id, date, date_time) DO UPDATE SET
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
        execute_values(
            cur,
            """
            INSERT INTO events_after_tagging (event_id, date, date_time, topics, event_type)
            VALUES %s
            ON CONFLICT (event_id, date, date_time) DO UPDATE SET
                topics = EXCLUDED.topics,
                event_type = EXCLUDED.event_type
            """,
            after_rows,
        )
    conn.commit()
    logger.info("Upserted %d events into events_before_tagging / events_after_tagging", len(events))


_JOINED_EVENT_SELECT = """
    SELECT b.*, a.topics, a.event_type
    FROM events_after_tagging a
    JOIN events_before_tagging b
        ON b.event_id = a.event_id
        AND b.date = a.date
        AND b.date_time = a.date_time
"""


def get_events_by_topics(
    topics: Sequence[str], match_all: bool = False, conn=None
) -> List[dict]:
    """Return events (before+after tagging fields merged) tagged with at
    least one of `topics` (match_all=False, the default - array "overlap",
    `&&`) or with all of them (match_all=True - array "contains", `@>`).
    Both operators use the GIN index on events_after_tagging.topics."""
    owns_conn = conn is None
    conn = conn or connect()
    try:
        operator = "@>" if match_all else "&&"
        query = _JOINED_EVENT_SELECT + f" WHERE a.topics {operator} %s ORDER BY b.event_id"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (list(topics),))
            return [dict(row) for row in cur.fetchall()]
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
            return [dict(row) for row in cur.fetchall()]
    finally:
        if owns_conn:
            conn.close()


def list_topics_in_use(conn=None) -> List[str]:
    """Distinct topic values actually present in events_after_tagging.
    Unlike categories/categories_audience, topics don't get a precomputed
    pool table (their taxonomy already lives in tagging.py) - this is the
    equivalent lookup for building a topic filter UI on demand."""
    owns_conn = conn is None
    conn = conn or connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT unnest(topics) AS topic FROM events_after_tagging ORDER BY 1"
            )
            return [row[0] for row in cur.fetchall()]
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
