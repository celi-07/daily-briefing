import json
from datetime import timedelta

import pytest
from bs4 import BeautifulSoup

from app.ai import AIError, GeminiEngine, validate_draft
from app.config import Settings
from app.models import Assessments, Claim, Digest, Draft, Drafts, MarketContext, Synthesis, Verdicts
from app.pipeline import build_digest
from app.render import render_parts
from app.selection import select, source_story
from conftest import NOW


@pytest.mark.parametrize('world,market,legacy,section', [(3, 0, 1, 'world'), (0, 3, 1, 'market'),
                                                     (4, 4, 1, 'market'), (2, 2, 5, None)])
def test_purpose_scores_are_independent_of_urgency_and_legacy_score(article_factory, event_factory,
                                                                  world, market, legacy, section):
    article = article_factory()
    event = event_factory(article, score=legacy, world_score=world, market_score=market)
    chosen = select([event], {article.id: article}, 70)
    assert bool(chosen) == bool(section)
    if section:
        assert event.briefing_section == section


@pytest.mark.parametrize('development', ['company-confirmed data breach', 'exchange bankruptcy',
                                       'BTC theft', 'gold theft', 'government restriction', 'IPO cancellation'])
def test_material_attributed_reporting_is_not_banned_by_high_risk(article_factory, event_factory, development):
    article = article_factory(text=f'Fixture News reports the named company confirmed a {development}.')
    event = event_factory(article, high_risk=True, world_score=3, market_score=4)
    assert select([event], {article.id: article}, 70) == [event]
    assert event.reporting_basis == 'reported'


def test_limited_evidence_can_be_audited_but_rumors_and_titles_cannot(article_factory, event_factory):
    article = article_factory(quality='excerpt')
    event = event_factory(article, world_score=3, market_score=0)
    event.assessment.evidence = 'limited'
    assert select([event], {article.id: article}, 70) == [event]
    event.assessment.evidence = 'unverified'
    assert not select([event], {article.id: article}, 70)
    event.assessment.evidence = 'limited'
    article.quality = 'title-only'
    assert not select([event], {article.id: article}, 70)


def context(article):
    return MarketContext(affected=[Claim(text='The company and local manufacturers.', article_ids=[article.id])],
                         mechanism='If delivered, the new plant could affect supply to local manufacturers.',
                         timing='Timing unclear from the source.', watch=[],
                         uncertainty='The source describes a plan rather than completed production.')


@pytest.mark.parametrize('field', ['affected', 'watch', 'mechanism', 'timing', 'uncertainty', 'caveat'])
def test_numeric_guard_covers_every_market_context_field(article_factory, event_factory, field):
    article = article_factory()
    event = event_factory(article)
    draft = Draft(event_id=event.id, headline='New factory plan',
                  summary=[Claim(text=article.text, article_ids=[article.id])], why_it_matters='',
                  market_context=context(article))
    if field in ('affected', 'watch'):
        setattr(draft.market_context, field, [Claim(text='Unsupported 99999 target.', article_ids=[article.id])])
    elif field == 'caveat':
        draft.caveat = 'Unsupported 99999 target.'
    else:
        setattr(draft.market_context, field, 'Unsupported 99999 target.')
    with pytest.raises(AIError, match='numeric'):
        validate_draft(draft, event, {article.id: article})


def test_market_context_unknown_citations_are_rejected(article_factory, event_factory):
    article = article_factory()
    event = event_factory(article)
    draft = Draft(event_id=event.id, headline='New factory plan',
                  summary=[Claim(text=article.text, article_ids=[article.id])], why_it_matters='',
                  market_context=context(article))
    draft.market_context.affected[0].article_ids = ['unknown']
    with pytest.raises(AIError, match='unknown'):
        validate_draft(draft, event, {article.id: article})


@pytest.mark.parametrize('accepted', [True, False])
def test_pipeline_audits_market_context_and_attribution_before_rendering(article_factory, event_factory, accepted):
    articles = [article_factory(i) for i in range(2)]
    registry = {a.id: a for a in articles}
    prompts = []
    def transport(prompt, schema, model):
        payload = json.loads(prompt.split('DATA:\n')[1])
        prompts.append((schema, payload))
        if schema == Assessments:
            return Assessments(items=[event_factory(registry[row['articles'][0]['id']],
                world_score=4, market_score=4 if i == 1 else 0, regions=['China' if i == 0 else 'US'],
                themes=['Semiconductors']).assessment.model_copy(update={'event_id': row['event_id']})
                for i, row in enumerate(payload)]).model_dump_json(), 100
        if schema == Drafts:
            row = payload['events'][0]
            article = registry[row['articles'][0]['id']]
            return Drafts(items=[Draft(event_id=row['event_id'], headline=article.title,
                summary=[Claim(text='According to Fixture News, ' + article.text, article_ids=[article.id])],
                why_it_matters='The plan could affect local manufacturers.',
                market_context=context(article) if row['market_context_required'] else None)]).model_dump_json(), 100
        if schema == Verdicts:
            return json.dumps({'items': [{'event_id': payload['drafts'][0]['event_id'],
                'supported': accepted, 'reason': 'Offline fixture verdict'}]}), 100
        assert schema == Synthesis
        return Synthesis(items=[]).model_dump_json(), 100
    digest = build_digest(Settings(), registry, [], NOW, engine=GeminiEngine(Settings(), transport))
    parts = render_parts(digest)
    if accepted:
        assert {s.briefing_section for s in digest.stories} == {'world', 'market'}
        assert len(parts[0].event_ids) == 2
        assert all(s.status == 'verified-analysis' for s in digest.stories)
        for output in (parts[0].html, parts[0].text):
            assert 'World developments'.lower() in output.lower() and 'Market catalysts'.lower() in output.lower()
            assert 'Possible implications:' in output and 'Timing unclear' in output
            assert 'Reported by Fixture News' in output
        assert len(BeautifulSoup(parts[0].html, 'html.parser').select('[data-event-id]')) == 2
    else:
        assert not parts[0].event_ids
    audits = [p for schema, p in prompts if schema == Verdicts]
    assert any(p['drafts'][0]['market_context'] is not None for p in audits)
    assert all(p['events'][0]['reporting_basis'] == 'reported' for p in audits)


def test_market_catalyst_cannot_pass_with_missing_context(article_factory, event_factory):
    article = article_factory()
    event = event_factory(article, world_score=0, market_score=4)
    select([event], {article.id: article}, 70)
    def transport(prompt, schema, model):
        assert schema == Drafts  # Never reaches the auditor with missing required context.
        return Drafts(items=[Draft(event_id=event.id, headline=article.title,
            summary=[Claim(text=article.text, article_ids=[article.id])], why_it_matters='')]).model_dump_json(), 100
    engine = GeminiEngine(Settings(), transport)
    assert engine.summarize(event, {article.id: article}) is None
    assert 'missing' in engine.failure_reason


def test_cross_purpose_story_remains_unique_through_email_partitioning(article_factory, event_factory):
    stories = []
    for i in range(20):
        article = article_factory(i)
        event = event_factory(article, world_score=4, market_score=4)
        select([event], {article.id: article}, 70)
        story = source_story(event, {article.id: article})
        story.status = 'verified-analysis'
        story.market_context = context(article)
        stories.append(story)
    digest = Digest(edition_date='2026-10-06', window_start=NOW-timedelta(days=1), window_end=NOW,
                    timezone='Asia/Jakarta', stories=stories)
    parts = render_parts(digest, 18000)
    ids = [eid for p in parts for eid in p.event_ids]
    assert len(ids) == len(set(ids)) == 20
    assert all(len(p.html.encode()) <= 18000 for p in parts)
    assert all(f'Event: {eid}' in p.text for p in parts for eid in p.event_ids)
