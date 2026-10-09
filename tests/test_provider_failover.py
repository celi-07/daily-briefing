import json

import httpx
import pytest
from google import genai
from google.genai import types

from app.ai import AIError, FailoverEngine, create_engine
from app.config import Settings
from app.delivery import prepare_state, send_state, validate_digest_for_delivery
from app.models import Assessments, Digest, Drafts
from app.pipeline import save_outputs
from app.render import render_parts
from app.selection import source_story
from conftest import NOW


def gemini_response():
    return httpx.Response(200, json={"candidates": [{"content": {"role": "model",
        "parts": [{"text": '{"items":[]}'}]}, "finishReason": "STOP"}],
        "usageMetadata": {"totalTokenCount": 100}})


@pytest.mark.parametrize("status,error_code", [(429, "insufficient_quota"), (429, "rate_limit_exceeded"), (401, "invalid_api_key")])
def test_real_provider_handoff_stays_on_gemini_and_counts_attempts(status, error_code):
    settings = Settings(openai_api_key="offline-openai", gemini_api_key="offline-gemini",
                        openai_fallback_model="another-openai-model")
    engine = create_engine(settings)
    assert isinstance(engine, FailoverEngine)
    calls = []
    def openai_endpoint(request):
        calls.append("openai")
        return httpx.Response(status, json={"error": {"code": error_code}})
    def gemini_endpoint(request):
        calls.append("gemini")
        return gemini_response()
    engine.adapters["openai"].client = httpx.Client(transport=httpx.MockTransport(openai_endpoint))
    engine.adapters["gemini"].client = genai.Client(api_key="offline-gemini", http_options=types.HttpOptions(
        client_args={"transport": httpx.MockTransport(gemini_endpoint)}, retry_options=types.HttpRetryOptions(attempts=1)))
    try:
        assert engine.request("assess", [], Assessments).items == []
        assert engine.request("assess", [], Assessments).items == []  # Same cached result after switch.
        assert engine.request("assess", [{"later": True}], Assessments).items == []
        assert calls == ["openai", "gemini", "gemini"]
        assert engine.requests == engine.assessment_requests == 3
        assert engine.tokens == engine.assessment_tokens == 200
        assert engine.openai_disabled and not engine.unavailable
    finally:
        engine.close()


def test_failover_never_resets_global_request_budget():
    engine = create_engine(Settings(openai_api_key="offline-openai", gemini_api_key="offline-gemini", ai_requests=2))
    calls = []
    def openai_endpoint(request):
        calls.append("openai")
        return httpx.Response(429, json={"error": {"code": "insufficient_quota"}})
    engine.adapters["openai"].client = httpx.Client(transport=httpx.MockTransport(openai_endpoint))
    engine.adapters["gemini"].transport = lambda *args: (calls.append("gemini") or '{"items":[]}', 100)
    try:
        assert engine.request("summarize", [], Drafts).items == []
        with pytest.raises(AIError, match="budget exhausted"):
            engine.request("summarize", {"later": True}, Drafts)
        assert calls == ["openai", "gemini"] and engine.requests == 2 and engine.tokens == 100
    finally:
        engine.close()


def test_successful_openai_usage_remains_counted_after_later_quota_failure():
    engine = create_engine(Settings(openai_api_key="offline-openai", gemini_api_key="offline-gemini"))
    calls = []
    def openai_endpoint(request):
        calls.append("openai")
        if len(calls) > 1:
            return httpx.Response(429, json={"error": {"code": "insufficient_quota"}})
        return httpx.Response(200, json={"status": "completed", "usage": {"total_tokens": 250},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"items":[]}'}]}]})
    engine.adapters["openai"].client = httpx.Client(transport=httpx.MockTransport(openai_endpoint))
    engine.adapters["gemini"].transport = lambda *args: (calls.append("gemini") or '{"items":[]}', 100)
    try:
        engine.request("assess", [], Assessments)
        engine.request("summarize", {"later": True}, Drafts)
        assert calls == ["openai", "openai", "gemini"]
        assert engine.tokens == 350 and engine.assessment_tokens == 250 and engine.requests == 3
    finally:
        engine.close()


def test_only_verified_stories_are_displayed_and_delivered(tmp_path, article_factory, event_factory):
    articles = [article_factory(i) for i in range(3)]
    registry = {a.id: a for a in articles}
    events = [event_factory(a) for a in articles]
    events[2].assessment = None
    stories = [source_story(e, registry, unassessed=e.assessment is None) for e in events]
    stories[0].status = "verified-analysis"
    digest = Digest(edition_date="2026-10-06", window_start=NOW, window_end=NOW, timezone="Asia/Jakarta",
        stories=stories, decisions=events, takeaways=[s.event_id for s in stories],
        notices=["AI assessment unavailable for 1 event(s): private diagnostic reason"])
    parts = render_parts(digest)
    assert [eid for part in parts for eid in part.event_ids] == [stories[0].event_id]
    for part in parts:
        for output in (part.html, part.text):
            assert stories[0].headline in output
            assert all(s.headline not in output for s in stories[1:])
            assert "Unassessed source excerpt" not in output and "AI importance/analysis unavailable" not in output
            assert "private diagnostic reason" not in output
    save_outputs(digest, parts, tmp_path / "outputs")
    report = json.loads((tmp_path / "outputs" / "coverage.json").read_text())
    assert report["ai"]["unassessed"] == 1 and report["ai"]["source_excerpts"] == 1
    validate_digest_for_delivery(digest)  # Partial AI failure doesn't block good stories.
    settings = Settings(gmail_address="sender@example.com", gmail_app_password="offline-password", state_dir=tmp_path / "state")
    path, state = prepare_state(settings, digest, parts)
    sent = []
    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def send_message(self, message, **kwargs):
            sent.append(message)
            return {}
    send_state(settings, path, state, SMTP)
    assert len(sent) == 1 and state["parts"][0]["status"] == "sent"


def test_old_frozen_payload_cannot_deliver_hidden_excerpt(tmp_path, article_factory, event_factory):
    article = article_factory()
    story = source_story(event_factory(article), {article.id: article})
    verified = story.model_copy(update={"event_id": "verified", "status": "verified-analysis"})
    digest = Digest(edition_date="2026-10-06", window_start=NOW, window_end=NOW, timezone="Asia/Jakarta", stories=[verified, story])
    settings = Settings(gmail_address="sender@example.com", gmail_app_password="offline-password", state_dir=tmp_path)
    path, state = prepare_state(settings, digest, render_parts(digest, include_excerpts=True))
    before = path.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError("Old source-only email must not reach SMTP")
    with pytest.raises(ValueError, match="Saved email contains omitted AI stories"):
        send_state(settings, path, state, forbidden)
    assert path.read_bytes() == before
