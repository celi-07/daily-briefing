from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup

from app.models import Article, SourceHealth, canonical_url, stable_id


def parse_feed(data, source, start, end):
    feed = feedparser.parse(data)
    if not feed.entries and (feed.bozo or not feed.version):
        raise ValueError("Unrecognized or malformed feed")
    articles, excluded = [], 0
    for entry in feed.entries:
        published = None
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            try:
                published = datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        if not published or published > end:
            excluded += 1
            continue
        if published < start:
            continue
        try:
            url = canonical_url(entry.get("link", ""))
        except ValueError:
            excluded += 1
            continue
        raw = entry.get("summary", entry.get("description", ""))
        if entry.get("content"):
            raw = entry.content[0].get("value", raw)
        text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
        articles.append(Article(id=stable_id(url), source_id=source.id, source_name=source.name,
            source_type="rss", trust=source.trust, url=url, title=entry.get("title", "Untitled"),
            text=text, author=entry.get("author", ""), published_at=published, fetched_at=end,
            quality="excerpt" if text else "title-only", topics=source.topics))
    detail = f"{excluded} entries quarantined (unknown/future date or invalid link)." if excluded else ""
    if feed.bozo:
        detail += " Feed parser reported malformed content; retained valid dated entries."
    return articles, SourceHealth(source_id=source.id, name=source.name, topics=source.topics,
        status="partial" if detail else "ok", fetched=len(articles), detail=detail.strip())


def fetch(source, fetcher, start, end):
    data, _ = fetcher.get(source.url)
    return parse_feed(data, source, start, end)
