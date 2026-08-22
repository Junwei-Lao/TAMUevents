"""Tests for src/helpers/tagging.py.

Instead of hand-built Event stubs, these load the real fixture data at
data/sample_events.json (the same file tag_sample_events() reads by
default) and exercise the actual SYSTEM_PROMPT / _build_user_prompt from
tagging.py — nothing here defines its own copy of the prompt. Only the
network call (_post_with_retry) is mocked, so tests never hit the real
DeepSeek API or require a real API key.
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
        assert event.topics == []
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
    assert event.topics == ["Music"]
    assert event.event_type == "Concert"


def test_tag_event_falls_back_on_invalid_labels(sample_events, monkeypatch):
    event = sample_events[1]

    monkeypatch.setattr(
        tagging,
        "_post_with_retry",
        lambda *a, **k: _fake_response(["Not A Real Topic"], "Not A Real Type"),
    )

    tagging.tag_event(event, FAKE_API_KEY)

    assert event.topics == [tagging.OTHER_TOPIC]
    assert event.event_type == tagging.OTHER_EVENT_TYPE


def test_tag_event_falls_back_on_request_failure(sample_events, monkeypatch):
    event = sample_events[2]

    def raise_error(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(tagging, "_post_with_retry", raise_error)

    tagging.tag_event(event, FAKE_API_KEY)

    assert event.topics == [tagging.OTHER_TOPIC]
    assert event.event_type == tagging.OTHER_EVENT_TYPE


def test_tag_sample_events_end_to_end_from_data_dir(monkeypatch, tmp_path):
    """Runs the full tag_sample_events() pipeline against the real
    data/sample_events.json input, with only the network call mocked."""
    monkeypatch.setattr(
        tagging,
        "_post_with_retry",
        lambda *a, **k: _fake_response(["General Interest"], "Other"),
    )

    output_path = tmp_path / "sample_events_tagged.json"
    tagged = tagging.tag_sample_events(
        input_path=tagging.DEFAULT_SAMPLE_PATH,
        output_path=str(output_path),
        api_key=FAKE_API_KEY,
    )

    raw_input = json.load(open(tagging.DEFAULT_SAMPLE_PATH, "r", encoding="utf-8"))
    assert len(tagged) == len(raw_input)
    for event in tagged:
        assert event.topics == ["General Interest"]
        assert event.event_type == "Other"

    assert output_path.exists()
    written = json.load(open(output_path, "r", encoding="utf-8"))
    assert len(written) == len(raw_input)
    assert written[0]["topics"] == ["General Interest"]
    assert written[0]["event_type"] == "Other"


def test_tag_events_requires_api_key(sample_events, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        tagging.tag_events(sample_events[:1], api_key=None)
