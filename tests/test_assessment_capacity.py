import json

from app.ai import GeminiEngine
from app.config import Settings
from app.models import Assessments, Drafts
from app.pipeline import build_digest, save_outputs
from app.render import ai_coverage, render_parts
from conftest import NOW


def assessment_transport(event_factory, registry, calls):
    def generate(prompt, schema, model):
        payload = json.loads(prompt.split('DATA:\n', 1)[1])
        calls.append(payload)
        items = []
        for event in payload:
            article = registry[event['articles'][0]['id']]
            item = event_factory(article.model_copy(update={'text': article.text[:500]})).assessment.model_copy(update={'event_id': event['event_id']})
            items.append(item)
        # Deterministic capacity simulation, not a live tokenizer/model benchmark.
        return Assessments(items=items).model_dump_json(), len(prompt) // 4 + 100 * len(items)
    return generate


def test_short_assessment_keeps_full_evidence_for_summary_and_audit(article_factory, event_factory):
    article = article_factory(text='A' * 5000 + 'Material evidence at the end.')
    event = event_factory(article.model_copy(update={'text': article.text[:500]}))
    engine = GeminiEngine(Settings(assessment_evidence_chars=3000, evidence_chars=10000))
    short = engine.evidence([event], {article.id: article}, assessment=True)[0]['articles'][0]
    full = engine.evidence([event], {article.id: article})[0]['articles'][0]
    assert len(short['text']) == 3000 and short['evidence_truncated']
    assert full['text'] == article.text and not full['evidence_truncated']
    assert article.text.endswith('Material evidence at the end.')
    engine = GeminiEngine(Settings(assessment_evidence_chars=3000, evidence_chars=1000))
    assert len(engine.evidence([event], {article.id: article}, assessment=True)[0]['articles'][0]['text']) == 1000


def test_long_article_capacity_improves_without_raising_total_budget(article_factory, event_factory):
    articles = [article_factory(i, text=('Evidence about the announcement. ' * 350)) for i in range(120)]
    registry = {article.id: article for article in articles}
    results = []
    for limit in (10000, 3000):
        events = [event_factory(article.model_copy(update={'text': article.text[:500]})).model_copy(update={'assessment': None}) for article in articles]
        calls, notices = [], []
        engine = GeminiEngine(Settings(assessment_evidence_chars=limit),
                              assessment_transport(event_factory, registry, calls))
        engine.assess(events, registry, notices)
        results.append((sum(event.assessment is not None for event in events), engine.assessment_tokens))
        assert engine.tokens < engine.settings.ai_tokens
    assert results[0][0] < 120
    assert results[1][0] == 120
    assert results[1][1] < results[0][1]


def test_oversized_batch_splits_before_spending_requests(article_factory, event_factory):
    articles = [article_factory(i, text='Evidence. ' * 300) for i in range(6)]
    registry = {article.id: article for article in articles}
    events = [event_factory(article.model_copy(update={'text': article.text[:500]})).model_copy(update={'assessment': None}) for article in articles]
    sizes = []
    def transport(prompt, schema, model):
        payload = json.loads(prompt.split('DATA:\n', 1)[1])
        sizes.append(len(payload))
        by_id = {event.id: event_factory(registry[event.article_ids[0]].model_copy(update={'text': 'Evidence.'})).assessment for event in events}
        return Assessments(items=[by_id[item['event_id']] for item in payload]).model_dump_json(), 100
    engine = GeminiEngine(Settings(ai_tokens=25000), transport)
    notices = []
    engine.assess(events, registry, notices)
    assert sizes == [3, 3]  # Six-item estimate exceeds 15,000; both halves fit.
    assert all(event.assessment is not None for event in events)
    assert engine.requests == 2 and engine.tokens == 200 and not notices


def test_failure_reason_and_coverage_survive_save_and_render(tmp_path, article_factory):
    article = article_factory()
    class Rejected(Exception):
        code = 403
        message = 'private request credential DO-NOT-LEAK'
    def transport(*args):
        raise Rejected()
    settings = Settings()
    engine = GeminiEngine(settings, transport)
    digest = build_digest(settings, {article.id: article}, [], NOW, engine=engine)
    report = ai_coverage(digest)
    assert report['events'] == report['unassessed'] == 1
    assert report['assessed'] == report['verified_stories'] == 0
    assert report['assessment_failures'] == {'Gemini authentication or permission failure': 1}
    parts = render_parts(digest)
    for output in (parts[0].html, parts[0].text):
        assert '0/1 events assessed' in output
        assert 'Gemini authentication or permission failure' in output
        assert 'DO-NOT-LEAK' not in output
    save_outputs(digest, parts, tmp_path)
    assert json.loads((tmp_path / 'coverage.json').read_text())['ai'] == report


def test_budget_failure_records_reason_without_blocking_summaries(article_factory, event_factory):
    articles = [article_factory(i) for i in range(3)]
    registry = {article.id: article for article in articles}
    events = [event_factory(article.model_copy(update={'text': article.text[:500]})).model_copy(update={'assessment': None}) for article in articles]
    calls = []
    engine = GeminiEngine(Settings(ai_requests=2, ai_batch_size=1),
                          assessment_transport(event_factory, registry, calls))
    engine.assess(events, registry, [])
    assert events[0].assessment is not None
    assert all('budget reserved for summaries and audits' in event.decision for event in events[1:])
    assert engine.requests == 1 and not engine.unavailable
    engine.transport = lambda *args: (Drafts(items=[]).model_dump_json(), 100)
    assert engine.request('summarize', [], Drafts).items == []


def test_summary_provider_failure_is_not_reported_as_failed_evidence(article_factory, event_factory):
    article = article_factory()
    registry = {article.id: article}
    def transport(prompt, schema, model):
        if schema == Assessments:
            payload = json.loads(prompt.split('DATA:\n', 1)[1])
            item = event_factory(article).assessment.model_copy(update={'event_id': payload[0]['event_id']})
            return Assessments(items=[item]).model_dump_json(), 100
        raise AssertionError('Summary must stop at the configured request limit')
    settings = Settings(ai_requests=1)
    digest = build_digest(settings, registry, [], NOW, engine=GeminiEngine(settings, transport))
    assert digest.stories[0].status == 'source-excerpt'
    assert 'budget exhausted' in digest.stories[0].caveat
    assert ai_coverage(digest)['source_excerpts'] == 1
