"""FastAPI backend gluing the React frontend to the Postgres event store.

Implements `POST /api/events/search` per docs/front_back_contract.md: parses
the frontend's request body (grouped-by-parent topic/event_type dicts, flat
categories/categories_audience lists), translates it into the
`postgre_io.search_events` request shape per docs/back_db_contract.md, and
returns the matching events.

Import style matches the rest of src/helpers (schema.py, postgre_io.py,
tagging.py): flat `from schema import ...` / `from postgre_io import ...`,
relying on this file's own directory being on sys.path (true when run as
`uvicorn backend:app` from within src/helpers, or `uvicorn --app-dir
src/helpers backend:app`).
"""

import logging
from datetime import date
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from postgre_io import search_events
from schema import encode_topic_flags

logger = logging.getLogger(__name__)

app = FastAPI(title="TAMU Events Search API")

# Dev-friendly default (the frontend may be served from a different
# port/origin than uvicorn during local development). A same-origin
# deployment behind nginx doesn't need this, but leaving it open is
# harmless there too since this endpoint is a read-only public search.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    """Mirrors docs/front_back_contract.md's request body."""

    start_date: date
    end_date: date
    topic_taxomony: Dict[str, List[str]] = Field(default_factory=dict)
    event_type: Dict[str, List[str]] = Field(default_factory=dict)
    categories: List[str] = Field(default_factory=list)
    categories_audience: List[str] = Field(default_factory=list)


class EventOut(BaseModel):
    """JSON shape of one result event: schema.py's Event dataclass fields,
    plus the start_date/end_date columns postgre_io.py stores alongside it.
    Extra fields on the DB row (the per-category topic bitflag columns) are
    dropped automatically since they aren't declared here."""

    event_id: int
    group_title: str
    url: str
    date: str
    date_time: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    categories_audience: List[str] = Field(default_factory=list)
    is_canceled: str = ""
    topics: Dict[str, List[str]] = Field(default_factory=dict)
    event_type: str = ""


class SearchResponse(BaseModel):
    events: List[EventOut]


def _build_db_request(payload: SearchRequest) -> dict:
    """Translate the frontend's request shape into
    postgre_io.search_events's request shape (docs/back_db_contract.md).

    - topic_taxomony arrives as {category: [leaf, ...]} and is encoded into
      {category_column: bitmask} via schema.encode_topic_flags.
    - event_type arrives the same shape, but event_type is only ever stored
      at the parent-category level (see tagging.py's _validate_event_type),
      so the leaves themselves carry no extra filtering power - only the
      selected parent categories matter.
    - categories / categories_audience are already flat lists, passed
      through unchanged.
    """
    return {
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "topic_taxomony": encode_topic_flags(payload.topic_taxomony),
        "event_type": list(payload.event_type.keys()),
        "categories": payload.categories,
        "categories_audience": payload.categories_audience,
    }


@app.post("/api/events/search", response_model=SearchResponse)
def search_events_endpoint(payload: SearchRequest) -> SearchResponse:
    db_request = _build_db_request(payload)
    try:
        rows = search_events(db_request)
    except Exception:
        logger.exception("search_events failed for request %s", db_request)
        raise HTTPException(status_code=500, detail="Event search failed")
    return SearchResponse(events=rows)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9191)
