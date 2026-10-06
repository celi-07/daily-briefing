import json
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.models import canonical_url


def jsonld(soup):
    def walk(value):
        if isinstance(value, list):
            for child in value:
                yield from walk(child)
        elif isinstance(value, dict):
            yield value
            yield from walk(value.get("@graph", []))
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue


def parse_iso(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def extract_page(data, url):
    soup = BeautifulSoup(data, "html.parser")
    metadata = next((obj for obj in jsonld(soup)
                     if obj.get("@type") in ("NewsArticle", "Article", "BlogPosting")), {})
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        url = canonical_url(urljoin(url, canonical["href"]))
    title = metadata.get("headline") or (soup.h1.get_text(" ", strip=True) if soup.h1 else "")
    author = metadata.get("author", {})
    if isinstance(author, list):
        author = author[0] if author else {}
    author = author.get("name", "") if isinstance(author, dict) else str(author)
    date = parse_iso(metadata.get("datePublished"))
    if date is None:
        tag = soup.find("meta", property="article:published_time")
        date = parse_iso(tag.get("content")) if tag else None
    # Prefer structured articleBody, then publisher article containers. Never summarize navigation.
    text = metadata.get("articleBody", "")
    if not text:
        body = soup.select_one('[itemprop="articleBody"], .article-content, .article-body, article')
        if body:
            for unwanted in body.select("script, style, nav, aside, footer, form"):
                unwanted.decompose()
            text = "\n".join(p.get_text(" ", strip=True) for p in body.select("p"))
    return {"url": url, "title": str(title), "author": author, "date": date, "text": str(text).strip(),
            "description": str(metadata.get("description", ""))}


def enrich(article, fetcher):
    if article.source_type == "x" or article.quality == "full":
        return article
    try:
        if not fetcher.permitted(article.url):
            raise ValueError("Article retrieval not permitted or robots unavailable")
        data, url = fetcher.get(article.url)
        extracted = extract_page(data, url)
        if len(extracted["text"]) > max(150, len(article.text)):
            article.text = extracted["text"]
            article.quality = "full"
        else:
            article.warnings.append("Full text unavailable; RSS evidence retained")
    except (RuntimeError, ValueError):
        article.warnings.append("Full text unavailable; RSS evidence retained")
    return article
