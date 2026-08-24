"""Tests for src/helpers/tagging.py.

Most tests load the real fixture data at data/sample_events.json (the same
file tag_sample_events() reads by default) and exercise the actual
SYSTEM_PROMPT / _build_user_prompt from tagging.py — nothing here defines
its own copy of the prompt. Only the network call (_post_with_retry) is
mocked, so tests never hit the real DeepSeek API or require a real API
key. Tests specifically about the keyword pass use small hand-built Events
instead, where the point is to control exactly what text is (or isn't)
being matched against.
"""

import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "helpers"))

import tagging  # noqa: E402
from schema import Event  # noqa: E402

FAKE_API_KEY = "test-key"


def _load_sample_events():
    with open(tagging.DEFAULT_SAMPLE_PATH, "r", encoding="utf-8") as fh:
        raw_events = json.load(fh)
    return [Event(**item) for item in raw_events]


def _make_event(title, description="", categories=None):
    """A minimal Event for keyword-pass tests, where the point is to
    control exactly what text is being matched - real fixture text is
    unpredictable as the taxonomy evolves (see e.g. the Third Coast
    Percussion sample event, which keyword-matches "History" via "made
    history" and "Anniversary" via "20th Anniversary" - not obvious just
    from reading the title)."""
    return Event(
        event_id=999999,
        group_title="Test Group",
        url="https://example.com/test",
        date="January 1, 2099",
        date_time="",
        title=title,
        description=description,
        location=None,
        categories=categories or [],
    )


def _fake_response(topics, event_type):
    return {
        "choices": [
            {"message": {"content": json.dumps({"topics": topics, "event_type": event_type})}}
        ]
    }


@pytest.fixture
def sample_events():
    events = _load_sample_events()
    assert events, "data/sample_events.json is empty; nothing to test against"
    return events


def test_sample_events_load_from_data_dir(sample_events):
    assert tagging.DEFAULT_SAMPLE_PATH.endswith(os.path.join("data", "sample_events.json"))
    for event in sample_events:
        assert isinstance(event, Event)
        assert event.title
        # tagging fields start unset until tag_event()/tag_events() runs
        assert event.topics == {}
        assert event.event_type == ""


def test_user_prompt_reflects_real_event_fields(sample_events):
    for event in sample_events:
        prompt = tagging._build_user_prompt(event)
        assert f"Title: {event.title}" in prompt
        assert (event.location or "unknown") in prompt
        if event.description:
            assert event.description[: tagging.DESCRIPTION_CHAR_LIMIT] in prompt


def test_tag_event_sends_canonical_system_prompt_and_applies_response(sample_events, monkeypatch):
    event = sample_events[0]
    seen_messages = {}

    def fake_post_with_retry(session, api_key, messages, **kwargs):
        seen_messages["value"] = messages
        assert api_key == FAKE_API_KEY
        return _fake_response(["Music"], "Concert")

    monkeypatch.setattr(tagging, "_post_with_retry", fake_post_with_retry)

    tagging.tag_event(event, FAKE_API_KEY)

    # Every call must use the exact same, unmodified system prompt.
    assert seen_messages["value"][0] == {"role": "system", "content": tagging.SYSTEM_PROMPT}
    assert seen_messages["value"][1] == {
        "role": "user",
        "content": tagging._build_user_prompt(event),
    }
    # topics is stored grouped by parent category, not as flat leaves.
    assert event.topics == {"Arts & Culture": ["Music"]}
    # event_type is stored as the leaf's parent category, not the leaf itself.
    assert event.event_type == "Arts / Entertainment"


def test_tag_event_groups_multiple_topics_by_category(sample_events, monkeypatch):
    event = sample_events[0]
    monkeypatch.setattr(
        tagging,
        "_post_with_retry",
        lambda *a, **k: _fake_response(["Music", "Traditions"], "Other"),
    )

    tagging.tag_event(event, FAKE_API_KEY)

    assert event.topics == {
        "Arts & Culture": ["Music"],
        "Campus & Student Life": ["Traditions"],
    }


def test_group_topics_by_category_combines_leaves_under_the_same_category():
    # "Music" and "Photography" are both leaves under Arts & Culture.
    grouped = tagging._group_topics_by_category(["Music", "Photography"])
    assert grouped == {"Arts & Culture": ["Music", "Photography"]}


@pytest.mark.parametrize(
    "leaf, expected_category",
    [
        ("Lecture", "Academic / Research"),
        ("lecture", "Academic / Research"),  # case-insensitive match
        ("Commencement", "Ceremony / Tradition"),
        ("Concert", "Arts / Entertainment"),
        ("Other", "Other"),
        ("Unknown", "Other"),
    ],
)
def test_tag_event_collapses_event_type_leaf_to_category(
    sample_events, monkeypatch, leaf, expected_category
):
    event = sample_events[0]
    monkeypatch.setattr(
        tagging, "_post_with_retry", lambda *a, **k: _fake_response(["General Interest"], leaf)
    )

    tagging.tag_event(event, FAKE_API_KEY)

    assert event.event_type == expected_category


# --- Keyword pass -----------------------------------------------------


def test_keyword_match_topics_finds_leaf_phrases_in_text():
    event = _make_event(
        title="AI Ethics Workshop",
        description="A hands-on session about artificial intelligence and machine learning.",
    )
    matched = tagging._keyword_match_topics(event)
    assert set(matched) == {"Artificial Intelligence / Machine Learning", "Ethics"}


def test_keyword_match_topics_ignores_catchall_leaves():
    # Catch-all leaves ("Other STEM", "Unknown", ...) have no phrases to
    # match in the first place - see schema.py's _keyword_phrases_for_leaf.
    assert tagging._TOPIC_KEYWORD_PATTERNS.get("Other STEM") is None
    assert tagging._EVENT_TYPE_KEYWORD_PATTERNS.get("Other") is None
    assert tagging._EVENT_TYPE_KEYWORD_PATTERNS.get("Unknown") is None


def test_keyword_match_event_type_prefers_title_over_description():
    event = _make_event(
        title="Guest Lecture on Robotics",
        description="Refreshments follow; a Concert takes place later that night.",
    )
    # "Lecture" (title) should win over "Concert" (description-only match).
    assert tagging._keyword_match_event_type(event) == "Lecture"


def test_keyword_match_finds_nothing_for_unrelated_text():
    event = _make_event(
        title="Zzyzx Quorlex Session 47",
        description="An informal meetup about nothing in particular, just people talking.",
    )
    assert tagging._keyword_match_topics(event) == []
    assert tagging._keyword_match_event_type(event) is None


@pytest.mark.parametrize(
    "keyword_leaves, ai_leaves, expected",
    [
        ([], [], [tagging.OTHER_TOPIC]),
        (["Ethics"], [], ["Ethics"]),
        ([], ["Ethics"], ["Ethics"]),
        (["Ethics"], [tagging.OTHER_TOPIC], ["Ethics"]),  # AI's "Other" is dropped, not unioned
        (["Ethics"], ["Music"], ["Ethics", "Music"]),  # keyword hits ordered first
        (["Ethics"], ["Ethics", "Music"], ["Ethics", "Music"]),  # deduped
    ],
)
def test_merge_topic_leaves(keyword_leaves, ai_leaves, expected):
    assert tagging._merge_topic_leaves(keyword_leaves, ai_leaves) == expected


def test_merge_topic_leaves_caps_at_max_merged_topics():
    many_leaves = ["Ethics", "Music", "History", "Philosophy", "Literature", "English"]
    merged = tagging._merge_topic_leaves(many_leaves, [])
    assert len(merged) == tagging.MAX_MERGED_TOPICS
    assert merged == many_leaves[: tagging.MAX_MERGED_TOPICS]


def test_validate_event_type_prefers_ai_pick_over_keyword_fallback():
    # AI's pick is valid, so it wins even though the keyword fallback differs.
    assert tagging._validate_event_type("Lecture", fallback_leaf="Concert") == "Academic / Research"


def test_validate_event_type_falls_back_to_keyword_leaf_when_ai_pick_invalid():
    assert (
        tagging._validate_event_type("not a real type", fallback_leaf="Lecture")
        == "Academic / Research"
    )
    assert tagging._validate_event_type(None, fallback_leaf="Commencement") == "Ceremony / Tradition"


def test_validate_event_type_falls_back_to_other_when_neither_pass_found_anything():
    assert tagging._validate_event_type(None, fallback_leaf=None) == tagging.OTHER_EVENT_TYPE
    assert tagging._validate_event_type("bogus", fallback_leaf=None) == tagging.OTHER_EVENT_TYPE


def test_tag_event_uses_keyword_pass_when_ai_labels_are_invalid(monkeypatch):
    # Real fixture event: title literally contains "Commencement" (an
    # event_type leaf), so the keyword pass should rescue event_type even
    # though the AI's own pick is garbage.
    event = _load_sample_events()[0]
    assert event.title == "Commencement and Commissioning"

    monkeypatch.setattr(
        tagging,
        "_post_with_retry",
        lambda *a, **k: _fake_response(["Not A Real Topic"], "Not A Real Type"),
    )

    tagging.tag_event(event, FAKE_API_KEY)

    # No topic phrase in this event's text -> keyword pass finds nothing for
    # topics, so that still falls all the way back to OTHER_TOPIC.
    assert event.topics == {"General / Interdisciplinary": [tagging.OTHER_TOPIC]}
    # ...but event_type is rescued by the keyword pass instead of "Other".
    assert event.event_type == "Ceremony / Tradition"


def test_tag_event_uses_keyword_pass_on_total_request_failure(monkeypatch):
    # Real fixture event: description literally contains "made history" and
    # "20th Anniversary" - both real taxonomy phrases - so a total AI
    # request failure should still leave this event meaningfully tagged
    # instead of blindly falling back to "Other" / OTHER_TOPIC.
    event = _load_sample_events()[2]
    assert event.title == "Third Coast Percussion: Murmurs in Time"

    def raise_error(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(tagging, "_post_with_retry", raise_error)

    tagging.tag_event(event, FAKE_API_KEY)

    assert event.topics == {
        "Humanities": ["History"],
        "Arts & Culture": ["Music"],
    }
    assert event.event_type == "Ceremony / Tradition"  # from the "Anniversary" leaf


def test_tag_event_falls_back_on_invalid_labels_and_no_keyword_match(monkeypatch):
    event = _make_event(
        title="Zzyzx Quorlex Session 47",
        description="An informal meetup about nothing in particular, just people talking.",
    )

    monkeypatch.setattr(
        tagging,
        "_post_with_retry",
        lambda *a, **k: _fake_response(["Not A Real Topic"], "Not A Real Type"),
    )

    tagging.tag_event(event, FAKE_API_KEY)

    assert event.topics == {"General / Interdisciplinary": [tagging.OTHER_TOPIC]}
    assert event.event_type == tagging.OTHER_EVENT_TYPE


def test_tag_event_falls_back_on_request_failure_and_no_keyword_match(monkeypatch):
    event = _make_event(
        title="Zzyzx Quorlex Session 47",
        description="An informal meetup about nothing in particular, just people talking.",
    )

    def raise_error(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(tagging, "_post_with_retry", raise_error)

    tagging.tag_event(event, FAKE_API_KEY)

    assert event.topics == {"General / Interdisciplinary": [tagging.OTHER_TOPIC]}
    assert event.event_type == tagging.OTHER_EVENT_TYPE


def test_tag_events_deduplicates_by_id_and_propagates_results(sample_events, monkeypatch):
    # data/sample_events.json's first two entries share event_id 372167 -
    # a real duplicate from the scraper, not a fabricated one.
    duplicate_pair = [e for e in sample_events if e.event_id == 372167]
    assert len(duplicate_pair) == 2, (
        "expected the known duplicate event_id 372167 pair in the fixture data"
    )

    call_count = {"n": 0}

    def fake_post_with_retry(session, api_key, messages, **kwargs):
        call_count["n"] += 1
        return _fake_response(["Traditions"], "Ceremony")

    monkeypatch.setattr(tagging, "_post_with_retry", fake_post_with_retry)

    tagging.tag_events(sample_events, api_key=FAKE_API_KEY)

    unique_ids = {event.event_id for event in sample_events}
    assert call_count["n"] == len(unique_ids)
    assert call_count["n"] < len(sample_events)

    first, second = duplicate_pair
    assert first.topics == {"Campus & Student Life": ["Traditions"]}
    assert first.event_type == "Ceremony / Tradition"
    assert second.topics == first.topics
    assert second.event_type == first.event_type
    # Copied, not aliased - mutating one event's dict/lists must not affect the other.
    assert second.topics is not first.topics
    assert second.topics["Campus & Student Life"] is not first.topics["Campus & Student Life"]


def test_tag_sample_events_end_to_end_from_data_dir(monkeypatch, tmp_path):
    """Runs the full tag_sample_events() pipeline against the real
    data/sample_events.json input, with only the network call mocked."""
    call_count = {"n": 0}

    def fake_post_with_retry(session, api_key, messages, **kwargs):
        call_count["n"] += 1
        return _fake_response(["General Interest"], "Other")

    monkeypatch.setattr(tagging, "_post_with_retry", fake_post_with_retry)

    output_path = tmp_path / "sample_events_tagged.json"
    tagged = tagging.tag_sample_events(
        input_path=tagging.DEFAULT_SAMPLE_PATH,
        output_path=str(output_path),
        api_key=FAKE_API_KEY,
    )

    raw_input = json.load(open(tagging.DEFAULT_SAMPLE_PATH, "r", encoding="utf-8"))
    assert len(tagged) == len(raw_input)
    # Fewer API calls than events, because of the duplicate event_id 372167 pair.
    assert call_count["n"] == len({event.event_id for event in tagged})
    assert call_count["n"] < len(raw_input)
    for event in tagged:
        # The AI's pick must survive the merge for every event - some
        # events' real text also produces keyword hits of their own (e.g.
        # the Aggie Athletics events keyword-match "Athletics" via their
        # "Sports & Athletics" source category), so this doesn't assert
        # topics is *only* {"General / Interdisciplinary": [...]}.
        assert event.topics["General / Interdisciplinary"] == ["General Interest"]
        assert event.event_type == "Other"  # "Other" is always AI-valid, so it always wins

    assert output_path.exists()
    written = json.load(open(output_path, "r", encoding="utf-8"))
    assert len(written) == len(raw_input)
    # written[0] is the Commencement event, which has no topic keyword
    # matches of its own, so this one can assert the exact merged shape.
    assert written[0]["topics"] == {"General / Interdisciplinary": ["General Interest"]}
    assert written[0]["event_type"] == "Other"


def test_tag_events_requires_api_key(sample_events, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        tagging.tag_events(sample_events[:1], api_key=None)
