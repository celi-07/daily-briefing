"""Public HTML + publisher-disclosed sitemap; no prohibited ?page= scraping."""
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.enrich import extract_page
from app.models import Article, SourceHealth, canonical_url, stable_id


def listing_links(data, origin):
    soup = BeautifulSoup(data, "html.parser")
    links = list(dict.fromkeys(urljoin(origin, tag["href"]) for tag in soup.select('a[href*="/articles/"]')))
    return [url for url in links if urlsplit(url).netloc == urlsplit(origin).netloc]


def sitemap_links(data, origin):
    root = ET.fromstring(data)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    is_index = root.tag.endswith("sitemapindex")
    nodes = root.findall("s:sitemap" if is_index else "s:url", ns)
    result = []
    for node in nodes:
        loc = node.findtext("s:loc", default="", namespaces=ns)
        if loc and urlsplit(loc).netloc == urlsplit(origin).netloc:
            result.append((canonical_url(loc), node.findtext("s:lastmod", default="", namespaces=ns)))
    return is_index, result


def fetch(source, fetcher, start, end):
    health = SourceHealth(source_id=source.id, name=source.name, topics=source.topics, status="ok")
    if not fetcher.permitted(source.url):
        raise ValueError("Cryptowave public retrieval not permitted or robots unavailable")
    listing, _ = fetcher.get(source.url)
    links = listing_links(listing, source.url)
    if not links:
        raise ValueError("Cryptowave layout changed: no article links found")
    # Only discover sitemaps declared in robots.txt, never guess an API/feed route.
    robots, _ = fetcher.get(urljoin(source.url, "/robots.txt"))
    maps = [line.split(":", 1)[1].strip() for line in robots.decode().splitlines()
            if line.lower().startswith("sitemap:")]
    map_urls, visited = list(maps), set()
    while map_urls and len(visited) < fetcher.settings.source_pages:
        url = map_urls.pop(0)
        if url in visited or urlsplit(url).netloc != urlsplit(source.url).netloc:
            continue
        visited.add(url)
        try:
            if not fetcher.permitted(url):
                raise ValueError("Sitemap disallowed")
            data, _ = fetcher.get(url)
            is_index, entries = sitemap_links(data, source.url)
            if is_index:
                map_urls.extend(loc for loc, _ in entries)
            else:
                # lastmod is a discovery hint only, never article publication time.
                for loc, modified in entries:
                    if "/articles/" in urlsplit(loc).path and (not modified or modified[:10] >= start.date().isoformat()):
                        links.append(loc)
        except (RuntimeError, ValueError, ET.ParseError):
            health.status, health.detail = "partial", "Sitemap unavailable; public listing coverage only."
    if map_urls:
        health.status, health.detail = "partial", "Sitemap traversal budget reached; coverage incomplete."
    if not maps:
        health.status, health.detail = "partial", "No disclosed sitemap; public listing coverage only."
    articles, quarantined, failures = [], 0, 0
    for url in dict.fromkeys(links):
        try:
            if not fetcher.permitted(url):
                raise ValueError("Article retrieval disallowed")
            data, final = fetcher.get(url)
            page = extract_page(data, final)
            published = page["date"]
            if not published or published > end:
                quarantined += 1
                continue
            if published < start:
                continue
            text = page["text"] or page["description"]
            if not page["title"]:
                raise ValueError("Article title missing")
            articles.append(Article(id=stable_id(page["url"]), source_id=source.id, source_name=source.name,
                source_type="cryptowave", trust=source.trust, url=page["url"], title=page["title"],
                text=text, author=page["author"], published_at=published, fetched_at=end,
                language="id", quality="full" if page["text"] else "excerpt" if text else "title-only",
                topics=source.topics))
        except (RuntimeError, ValueError):
            failures += 1
    if failures or quarantined:
        health.status = "partial" if articles else "failed"
        health.detail += f" {failures} article fetch/parse failures; {quarantined} unknown/future dates quarantined."
    health.fetched = len(articles)
    return articles, health
