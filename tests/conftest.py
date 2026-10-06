from datetime import datetime, timedelta, timezone

import pytest

from app.models import Article, Assessment, Event, Fact, Scores

NOW = datetime(2026, 10, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def article_factory():
    def make(index=0, **changes):
        values = dict(id=f"a{index}", source_id="fixture", source_name="Fixture News", source_type="rss",
            trust="reporter", url=f"https://example.com/news/{index}", title=f"Company {index} publishes its new semiconductor factory plan",
            text=f"Company {index} announced a new semiconductor factory. The company says the new plant will supply local manufacturers. This fixture is synthetic sample evidence, not real news.",
            published_at=NOW - timedelta(hours=1), fetched_at=NOW, topics=["tech"])
        return Article(**{**values, **changes})
    return make


@pytest.fixture
def event_factory():
    def make(article, *, score=5, **changes):
        event_id = f"event-{article.id}"
        result = Assessment(event_id=event_id, event_key=article.title, topic=article.topics[0],
            entities=[f"Company {article.id}"], scores=Scores(impact=score, relevance=score, novelty=score, urgency=score),
            evidence="supported", independent_origins=[article.id], facts=[Fact(text=article.text, article_ids=[article.id])],
            reason="Supported synthetic development", **changes)
        return Event(id=event_id, article_ids=[article.id], assessment=result)
    return make
