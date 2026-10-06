import json
import socket
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from app.config import Settings, Source
from app.enrich import extract_page
from app.http import FetchError, Fetcher, PublicNetworkBackend, public_url
from app.sources import cryptowave, rss, x
from conftest import NOW

FIXTURES = Path(__file__).parent / "fixtures"


def test_rss_window_and_quarantined_dates():
    source = Source(id="rss", name="RSS", kind="rss", url="https://example.com/feed", topics=["finance"])
    articles, health = rss.parse_feed((FIXTURES/"feed.xml").read_bytes(), source, NOW-timedelta(days=1), NOW)
    assert len(articles) == 1 and health.status == "partial"
    assert articles[0].published_at.hour == 0 and articles[0].published_at.minute == 30
    assert articles[0].url == "https://example.com/a"
    with pytest.raises(ValueError):
        rss.parse_feed(b"<html>not a feed</html>", source, NOW-timedelta(days=1), NOW)


def test_rss_no_first_25_cutoff():
    source = Source(id="rss", name="RSS", kind="rss", url="https://example.com/feed", topics=["finance"])
    entries = ''.join(f'<item><title>Fixture {i}</title><link>https://example.com/{i}</link><pubDate>Tue, 06 Oct 2026 00:30:00 GMT</pubDate></item>' for i in range(40))
    data = ('<rss version="2.0"><channel><title>Feed</title>' + entries + '</channel></rss>').encode()
    articles, _ = rss.parse_feed(data, source, NOW-timedelta(days=1), NOW)
    assert len(articles) == 40


def test_cryptowave_parser_metadata_and_body():
    page = extract_page((FIXTURES/"cryptowave-article.html").read_bytes(), "https://cryptowave.co.id/articles/fixture")
    assert page["date"].hour == 0 and page["date"].minute == 30
    assert "contoh artikel sintetis" in page["text"]
    assert "navigation" not in page["text"]
    assert page["author"] == "Fixture Author"
    assert cryptowave.listing_links(b'<a href="/articles/synthetic-fixture">Story</a>', "https://cryptowave.co.id/") == [page["url"]]


class FakeFetcher:
    def __init__(self, results, settings=None):
        self.settings = settings or Settings(x_bearer_token="test-token")
        self.results = iter(results)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url,kwargs))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return json.dumps(result).encode() if isinstance(result, dict) else result, url

    def permitted(self, url):
        return True


def test_x_disabled_without_credentials_or_queries():
    source = Source(id="x", name="X", kind="x", topics=["crypto"])
    articles, status = x.fetch(source, FakeFetcher([]), NOW-timedelta(days=1), NOW)
    assert articles == [] and status.status == "disabled"


def test_x_pagination_primary_accounts_and_linked_origins():
    source = Source(id="x", name="X", kind="x", topics=["crypto"], queries=["from:example"], primary_accounts=["example"])
    payload = {"data":[{"id":"1", "text":"Primary institution publishes its own data.", "author_id":"u", "created_at":"2026-10-06T00:30:00Z",
                           "entities":{"urls":[{"expanded_url":"https://example.com/news?utm_source=x"}]}}],
               "includes":{"users":[{"id":"u", "username":"example"}]}, "meta":{"next_token":"next"}}
    fetcher = FakeFetcher([payload, {"data":[],"meta":{}}])
    articles, status = x.fetch(source, fetcher, NOW-timedelta(days=1), NOW)
    assert len(articles) == 1 and articles[0].trust == "primary"
    assert articles[0].linked_urls == ["https://example.com/news"]
    assert fetcher.calls[1][1]["params"]["next_token"] == "next"
    assert "post.fields" in fetcher.calls[0][1]["params"]
    assert status.status == "ok"


def test_x_429_and_pagination_limits_disclose_incomplete_coverage():
    source = Source(id="x", name="X", kind="x", topics=["crypto"], queries=["bitcoin"])
    _, status = x.fetch(source, FakeFetcher([FetchError("Source HTTP 429")]), NOW-timedelta(days=1), NOW)
    assert status.status == "failed"
    _, status = x.fetch(source, FakeFetcher([{"meta":{"next_token":"next"}}], Settings(source_pages=1,x_bearer_token="x")), NOW-timedelta(days=1), NOW)
    assert status.status == "partial"


def test_x_long_post_fields_and_paid_promotion_filter():
    source = Source(id='x',name='X',kind='x',topics=['crypto'],queries=['from:example'])
    post = {'id':'1','text':'Truncated text','created_at':'2026-10-06T00:30:00Z',
            'note_post':{'text':'The complete long-form announcement.','entities':{'urls':[{'expanded_url':'https://example.com/full'}]}}}
    paid = {**post,'id':'2','paid_partnership':True}
    fetcher = FakeFetcher([{'data':[post,paid],'meta':{}}])
    articles,health = x.fetch(source,fetcher,NOW-timedelta(days=1),NOW)
    assert len(articles) == 1 and articles[0].text == post['note_post']['text']
    assert articles[0].linked_urls == ['https://example.com/full']


def test_cryptowave_disclosed_sitemap_and_changed_layout():
    source = Source(id="cw", name="CW", kind="cryptowave", url="https://cryptowave.co.id/", topics=["crypto"])
    listing = b'<a href="/articles/synthetic-fixture">Story</a>'
    robots = b'User-agent: *\nAllow: /\nDisallow: /?page=\nSitemap: https://cryptowave.co.id/sitemap.xml'
    sitemap = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://cryptowave.co.id/articles/synthetic-fixture</loc><lastmod>2026-10-06</lastmod></url></urlset>'
    fetcher = FakeFetcher([listing, robots, sitemap, (FIXTURES/"cryptowave-article.html").read_bytes()])
    articles, status = cryptowave.fetch(source, fetcher, NOW-timedelta(days=1), NOW)
    assert len(articles) == 1 and status.status == "ok"
    assert all('?page=' not in url for url,_ in fetcher.calls)
    with pytest.raises(ValueError, match="layout changed"):
        cryptowave.fetch(source, FakeFetcher([b'<html>changed</html>']), NOW-timedelta(days=1), NOW)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.2", "169.254.169.254", "::1"])
def test_rejects_nonpublic_addresses(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))])
    with pytest.raises(FetchError):
        public_url("https://example.com")
    with pytest.raises(FetchError):
        PublicNetworkBackend().connect_tcp("example.com",443)


def test_redirect_is_checked_and_auth_not_forwarded(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host,*a,**k: [(socket.AF_INET,socket.SOCK_STREAM,6,'',(host if host == '127.0.0.1' else '93.184.216.34',443))])
    fetcher = Fetcher(Settings())
    fetcher.client.close()
    fetcher.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(302,headers={"location":"http://127.0.0.1/"})))
    with pytest.raises(FetchError, match="Nonpublic"):
        fetcher.get("https://example.com/")
    with pytest.raises(FetchError, match="Authenticated redirect"):
        fetcher.get("https://example.com/",headers={"Authorization":"Bearer fixture"})
    fetcher.close()


def test_response_and_request_budgets(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a,**k: [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))])
    fetcher = Fetcher(Settings(http_bytes=1024,http_requests=1))
    fetcher.client.close()
    fetcher.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200,content=b'x'*2048)))
    with pytest.raises(FetchError,match="size budget"):
        fetcher.get("https://example.com/")
    with pytest.raises(FetchError,match="request budget"):
        fetcher.get("https://example.com/")
    fetcher.close()
