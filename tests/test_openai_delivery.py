import json

import httpx
import pytest

from app.ai import AIError, GeminiEngine, OpenAIEngine, create_engine, openai_schema
from app.config import Settings
from app.delivery import load_state, prepare_state, send_state, validate_digest_for_delivery
from app.models import Assessments, Drafts, Synthesis, Verdicts
from app.pipeline import build_digest, main
from app.render import render_parts
from app.testing import FixtureEngine
from conftest import NOW


def response(text='{"items":[]}', *, status="completed", usage=19, **fields):
    return {"status": status, "usage": {"total_tokens": usage},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}], **fields}


@pytest.mark.parametrize("schema", [Assessments, Drafts, Verdicts, Synthesis])
def test_openai_strict_schema_and_real_http_contract(schema):
    original = schema.model_json_schema()
    def check(node):
        if isinstance(node, dict):
            assert "default" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(openai_schema(schema))
    assert schema.model_json_schema() == original  # Gemini schema remains unchanged.
    captured = []
    def endpoint(request):
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer offline-placeholder"
        body = json.loads(request.content)
        captured.append(body)
        assert body["model"] == "gpt-5.6-terra"
        assert body["store"] is False and body["reasoning"] == {"effort": "none"}
        assert body["max_output_tokens"] == 2048
        assert body["text"]["format"] == {"type": "json_schema", "name": schema.__name__,
            "strict": True, "schema": openai_schema(schema)}
        return httpx.Response(200, json=response())
    engine = OpenAIEngine(Settings(openai_api_key="offline-placeholder"))
    engine.client = httpx.Client(transport=httpx.MockTransport(endpoint))
    try:
        text, tokens = engine._generate("Return an empty items array.", schema, engine.primary_model, max_output_tokens=2048)
        assert schema.model_validate_json(text).items == [] and tokens == 19
        assert len(captured) == 1
    finally:
        engine.close()


def test_missing_openai_key_selects_available_gemini():
    settings = Settings(gemini_api_key="existing-gemini-key")
    assert isinstance(create_engine(settings), GeminiEngine)
    settings.validate_ai()
    explicit = Settings(ai_provider="gemini", gemini_api_key="existing-gemini-key")
    explicit.validate_ai()
    assert isinstance(create_engine(explicit), GeminiEngine)


@pytest.mark.parametrize("http_status,error_code,expected_calls", [
    (401, "invalid_api_key", 1), (400, "invalid_schema", 1),
    (429, "insufficient_quota", 1), (429, "rate_limit_exceeded", 3), (503, "unavailable", 3),
])
def test_openai_provider_failures_are_bounded_and_never_leak_details(monkeypatch, caplog, http_status, error_code, expected_calls):
    monkeypatch.setattr("app.ai.time.sleep", lambda seconds: None)
    calls = []
    def endpoint(request):
        calls.append(1)
        return httpx.Response(http_status, json={"error": {"code": error_code,
            "message": "PRIVATE-KEY-AND-ARTICLE-MUST-NOT-BE-LOGGED"}})
    engine = OpenAIEngine(Settings(openai_api_key="offline-placeholder"))
    engine.client = httpx.Client(transport=httpx.MockTransport(endpoint))
    try:
        with pytest.raises(AIError) as failed:
            engine.request("assess", [], Assessments)
        assert len(calls) == engine.requests == expected_calls
        assert engine.tokens == 0
        assert "OpenAI" in str(failed.value)
        assert "Gemini" not in str(failed.value)
        assert "PRIVATE-KEY" not in caplog.text + str(failed.value)
    finally:
        engine.close()


@pytest.mark.parametrize("kind", ["truncated", "refusal", "failed"])
def test_openai_noncompleted_or_refused_output_cannot_become_analysis(kind):
    body = response(usage=37)
    if kind == "truncated":
        body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    elif kind == "refusal":
        body["output"][0]["content"] = [{"type": "refusal", "refusal": "Raw private provider text"}]
    else:
        body["status"] = "failed"
    engine = OpenAIEngine(Settings(openai_api_key="offline-placeholder"))
    engine.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
    try:
        with pytest.raises(AIError) as failed:
            engine.request("assess", [], Assessments)
        assert failed.value.splittable == (kind == "truncated")
        assert engine.requests == 1 and engine.tokens == 37
        assert "Raw private" not in str(failed.value)
    finally:
        engine.close()


def test_openai_all_production_stages_produce_only_verified_stories(article_factory, event_factory):
    articles = [article_factory(i) for i in range(2)]
    registry = {a.id: a for a in articles}
    stages = []
    def endpoint(request):
        body = json.loads(request.content)
        stage = body["text"]["format"]["name"]
        stages.append(stage)
        payload = json.loads(body["input"].split("DATA:\n", 1)[1])
        if stage == "Assessments":
            items = []
            for event in payload:
                assessment = event_factory(registry[event["articles"][0]["id"]]).assessment
                assessment.event_id = event["event_id"]
                items.append(assessment.model_dump(mode="json"))
        elif stage == "Drafts":
            event = payload["events"][0]
            aid = event["articles"][0]["id"]
            items = [{"event_id": event["event_id"], "headline": registry[aid].title,
                "summary": [{"text": registry[aid].text, "article_ids": [aid]}],
                "why_it_matters": "The company says the plant will supply local manufacturers.", "caveat": ""}]
        elif stage == "Verdicts":
            items = [{"event_id": e["event_id"], "supported": True, "reason": "Supported by supplied evidence"}
                     for e in payload["events"]]
        else:
            items = []
        return httpx.Response(200, json=response(json.dumps({"items": items})))
    engine = OpenAIEngine(Settings(openai_api_key="offline-placeholder"))
    engine.client = httpx.Client(transport=httpx.MockTransport(endpoint))
    try:
        digest = build_digest(engine.settings, registry, [], NOW, engine=engine)
        validate_digest_for_delivery(digest)
        assert len(digest.stories) == 2 and all(s.status == "verified-analysis" for s in digest.stories)
        assert stages == ["Assessments", "Drafts", "Verdicts", "Drafts", "Verdicts", "Synthesis"]
        assert engine.tokens == 19 * 6 and engine.requests == 6
        assert not any("AI importance/analysis unavailable" in p.text for p in render_parts(digest))
    finally:
        engine.close()


def test_missing_openai_connection_stops_before_collection(tmp_path, monkeypatch):
    settings = Settings(output_dir=tmp_path / "outputs")
    monkeypatch.setattr("app.pipeline.Settings.from_env", lambda: settings)
    def forbidden(*args, **kwargs):
        raise AssertionError("Missing key must stop before source collection or AI calls")
    monkeypatch.setattr("app.pipeline.Fetcher", forbidden)
    monkeypatch.setattr("app.pipeline.create_engine", forbidden)
    with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
        main(["--dry-run"])
    assert not settings.output_dir.exists()


@pytest.mark.parametrize("unassessed", [False, True])
def test_incomplete_ai_blocks_fresh_and_restored_pending_delivery(tmp_path, article_factory, event_factory, unassessed):
    article = article_factory()
    fixture = {} if unassessed else {"assessments": {
        article.id: event_factory(article).assessment.model_dump(mode="json")}}
    digest = build_digest(Settings(), {article.id: article}, [], NOW, engine=FixtureEngine(fixture))
    if not unassessed:
        assert digest.stories[0].status == "source-excerpt"
    with pytest.raises(ValueError, match="No verified AI stories"):
        validate_digest_for_delivery(digest)
    settings = Settings(gmail_address="sender@example.com", gmail_app_password="offline-password", state_dir=tmp_path)
    path, state = prepare_state(settings, digest, render_parts(digest))
    def forbidden(*args, **kwargs):
        raise AssertionError("An incomplete edition must not connect to SMTP or update its frozen state")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="No verified AI stories"):
        send_state(settings, path, load_state(path), forbidden, retry_uncertain=True)
    assert path.read_bytes() == before and all(p["status"] == "pending" for p in state["parts"])


def test_below_threshold_assessed_event_is_valid_quiet_day(article_factory, event_factory):
    article = article_factory()
    event = event_factory(article, score=1)
    digest = build_digest(Settings(), {article.id: article}, [], NOW, engine=FixtureEngine({
        "assessments": {article.id: event.assessment.model_dump(mode="json")}}))
    assert digest.decisions and not digest.stories
    validate_digest_for_delivery(digest)
