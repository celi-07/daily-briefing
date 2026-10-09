from collections import Counter
from datetime import timedelta

import pytest
from bs4 import BeautifulSoup

from app.cluster import cluster_articles, merge_assessed_events
from app.models import Digest, TOPICS, canonical_url
from app.render import render_parts
from app.selection import select, sort_stories, source_story
from conftest import NOW


@pytest.mark.parametrize("count", [0, 3, 7, 20])
def test_every_qualifying_story_in_each_topic(count, article_factory, event_factory):
    registry, events = {}, []
    for topic in TOPICS:
        for i in range(count):
            article = article_factory(len(registry), topics=[topic])
            registry[article.id] = article
            events.append(event_factory(article))
    chosen = select(events, registry, 70)
    stories = sort_stories([source_story(event, registry) for event in chosen])
    digest = Digest(edition_date="2026-10-06", window_start=NOW-timedelta(days=1), window_end=NOW,
                    timezone="Asia/Jakarta", stories=stories, decisions=events)
    parts = render_parts(digest, 18_000, include_excerpts=True)
    assert Counter(s.topic for s in stories) == Counter({t: count for t in TOPICS}) if count else not stories
    expected = {s.event_id for s in stories}
    assert {eid for p in parts for eid in p.event_ids} == expected
    assert len([eid for p in parts for eid in p.event_ids]) == count * 4
    for part in parts:
        assert len(part.html.encode("utf-8")) <= 18_000
        soup = BeautifulSoup(part.html, "html.parser")
        assert {tag['data-event-id'] for tag in soup.select('[data-event-id]')} == set(part.event_ids)
        assert all(f"Event: {eid}" in part.text for eid in part.event_ids)
        assert "display:flex" not in part.html and "overflow-x" not in part.html


def test_no_padding_low_score_disputed_and_title_only(article_factory, event_factory):
    items = [article_factory(i) for i in range(4)]
    events = [event_factory(items[0]), event_factory(items[1], score=1),
              event_factory(items[2]), event_factory(items[3])]
    events[2].assessment.evidence = "disputed"
    items[3].text, items[3].quality = "", "title-only"
    assert len(select(events, {a.id:a for a in items}, 70)) == 1


def test_social_and_primary_evidence_gate(article_factory, event_factory):
    article = article_factory(source_type="x", trust="unknown")
    event = event_factory(article)
    assert select([event], {article.id:article}, 70) == []
    article.trust = "primary"
    event.assessment.primary_own_statement = True
    assert select([event], {article.id:article}, 70) == [event]


def test_short_primary_announcement_is_not_arbitrarily_dropped(article_factory,event_factory):
    article = article_factory(source_type='x',trust='primary',text='We raised our policy rate to 6.25%.')
    event = event_factory(article,primary_own_statement=True)
    assert select([event],{article.id:article},70) == [event]


def test_high_risk_needs_independent_origins(article_factory, event_factory):
    a, b = article_factory(), article_factory(1, source_id="other", url="https://other.example/news")
    event = event_factory(a, high_risk=True)
    event.article_ids.append(b.id)
    event.assessment.independent_origins.append(b.id)
    registry = {a.id:a, b.id:b}
    assert select([event], registry, 70) == [event]
    event.eligible = False
    b.text = a.text  # A reprint does not corroborate.
    assert select([event], registry, 70) == []


def test_canonical_urls_preserve_content_parameters():
    assert canonical_url("https://example.com/a?id=7&utm_source=x&gclid=y#here") == "https://example.com/a?id=7"
    for url in ("javascript:alert(1)", "data:text/html,hi", "https://user:pass@example.com", "https://example.com\nhi"):
        with pytest.raises(ValueError):
            canonical_url(url)


def test_html_and_attribute_escaping(article_factory, event_factory):
    article = article_factory(title='<script>alert("x")</script>', text='<img src=x onerror="alert(1)"> ' * 10,
                              url='https://example.com/path?q=" onclick="evil')
    event = event_factory(article)
    digest = Digest(edition_date="2026-10-06", window_start=NOW-timedelta(days=1), window_end=NOW,
        timezone="Asia/Jakarta", stories=[source_story(event, {article.id:article})])
    html = render_parts(digest, include_excerpts=True)[0].html
    soup = BeautifulSoup(html, "html.parser")
    assert not soup.find("script") and not soup.find("img")
    assert all(not tag.has_attr("onclick") for tag in soup.find_all())
    assert '&lt;script&gt;' in html


def test_linked_post_rss_and_duplicate_title_cluster_once(article_factory):
    a = article_factory()
    b = article_factory(1, title=a.title, url="https://other.example/a")
    post = article_factory(2, source_type="x", title="An announcement", linked_urls=[a.url], trust="unknown")
    other = article_factory(3, title="Company 0 reports different quarterly earnings figures")
    events = cluster_articles([a,b,post,other])
    assert sorted(len(e.article_ids) for e in events) == [1,3]


def test_cross_language_event_key_merge_and_distinct_actions(article_factory, event_factory):
    a, b, c = [article_factory(i) for i in range(3)]
    a.title, b.title = "Bank Indonesia holds rates", "Bank Indonesia menahan suku bunga"
    events = [event_factory(item) for item in (a,b,c)]
    for event in events:
        event.assessment.entities = ["Bank Indonesia"]
    events[0].assessment.event_key = events[1].assessment.event_key = "Bank Indonesia rate hold 2026-10-06"
    events[2].assessment.event_key = "Bank Indonesia reserve requirement change 2026-10-06"
    unchanged, merged = merge_assessed_events(events)
    assert len(unchanged) == len(merged) == 1
    assert merged[0].assessment is None and len(merged[0].article_ids) == 2


def test_last_part_notes_reserve_space_and_sources(article_factory,event_factory):
    from app.models import CitedNote
    articles = [article_factory(i) for i in range(20)]
    registry = {a.id:a for a in articles}
    stories = [source_story(event_factory(a),registry) for a in articles]
    note = CitedNote(kind='connection',text='Conditional connection. '*20,story_ids=[stories[0].event_id,stories[1].event_id])
    digest = Digest(edition_date='2026-10-06',window_start=NOW-timedelta(days=1),window_end=NOW,
                    timezone='Asia/Jakarta',stories=stories,notes=[note])
    parts = render_parts(digest,18_000, include_excerpts=True)
    assert len(parts) > 1
    assert sum(note.text in p.html for p in parts) == 1
    assert all(len(p.html.encode()) <= 18_000 for p in parts)
