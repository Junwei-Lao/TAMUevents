"""Data structures shared across the scraping/parsing pipeline."""

from dataclasses import dataclass, field
from typing import List, Optional


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


@dataclass
class FeedVisitStatus:
    """Tracks when a group's JSON feed was last scraped, so feeds can be
    revisited on a fixed cadence (e.g. every 3-4 days) instead of every run."""

    group_title: str
    feed_url: str
    last_visited: str  # ISO 8601 timestamp
    event_count: int = 0
