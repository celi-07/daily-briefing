"""Bounded HTTP with public-address checks on every redirect and robots policy."""
import ipaddress
import socket
import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import httpcore

from app.models import canonical_url

USER_AGENT = "DailyBriefing/2.0 (+https://github.com/celi-07/daily-briefing)"


class FetchError(RuntimeError):
    pass


class PublicNetworkBackend(httpcore.SyncBackend):
    """Validate and connect to the same resolved address, preventing DNS rebinding."""
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
                raise FetchError("Nonpublic network connection rejected")
            last_error = None
            for address in dict.fromkeys(item[4][0] for item in addresses):
                try:
                    return super().connect_tcp(address, port, timeout, local_address, socket_options)
                except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                    last_error = exc
            raise last_error
        except socket.gaierror:
            raise FetchError("Source hostname resolution failed") from None


def public_url(url: str) -> str:
    url = canonical_url(url)
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in (80, 443):
        raise FetchError("Nonstandard network port rejected")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise FetchError("Nonpublic network address rejected")
    except (socket.gaierror, ValueError) as exc:
        raise FetchError("Source hostname could not be validated") from exc
    return url


class Fetcher:
    def __init__(self, settings):
        self.settings = settings
        self.requests = 0
        self.lock = threading.Lock()
        self.robots = {}
        self.last_request = {}
        transport = httpx.HTTPTransport(retries=0)
        # Pinned httpx/httpcore versions; TLS receives the original SNI/certificate hostname.
        transport._pool._network_backend = PublicNetworkBackend()
        self.client = httpx.Client(timeout=settings.http_timeout, follow_redirects=False, transport=transport,
                                   trust_env=False, headers={"User-Agent": USER_AGENT})

    def close(self):
        self.client.close()

    def get(self, url, *, params=None, headers=None):
        for redirect in range(6):
            url = public_url(url)
            host = urlsplit(url).netloc
            with self.lock:
                if self.requests >= self.settings.http_requests:
                    raise FetchError("HTTP request budget exhausted; coverage incomplete")
                self.requests += 1
                # Gentle per-host pacing; independent hosts still fetch concurrently.
                delay = max(0, .4 - (time.monotonic() - self.last_request.get(host, 0)))
                self.last_request[host] = time.monotonic() + delay
            if delay:
                time.sleep(delay)
            try:
                with self.client.stream("GET", url, params=params, headers=headers) as response:
                    if response.is_redirect:
                        destination = urljoin(str(response.url), response.headers.get("location", ""))
                        # Authenticated APIs may not forward bearer tokens to another origin.
                        if headers and urlsplit(destination).netloc != host:
                            raise FetchError("Authenticated redirect to another host rejected")
                        url, params = destination, None
                        continue
                    if response.status_code >= 400:
                        raise FetchError(f"Source HTTP {response.status_code}")
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > self.settings.http_bytes:
                            raise FetchError("Source response exceeded size budget")
                    return bytes(data), str(response.url)
            except httpx.HTTPError as exc:
                # Do not include raw requests, query strings, or authorization headers.
                raise FetchError(f"Source network error ({type(exc).__name__})") from None
        raise FetchError("Too many redirects")

    def permitted(self, url):
        parsed = urlsplit(public_url(url))
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with self.lock:
            rule = self.robots.get(origin)
        if rule is None:
            try:
                data, _ = self.get(origin + "/robots.txt")
                rule = RobotFileParser()
                rule.parse(data.decode("utf-8", errors="replace").splitlines())
            except FetchError as exc:
                # 404 means no robots resource; other errors fail closed for article scraping.
                if str(exc) != "Source HTTP 404":
                    return False
                rule = RobotFileParser()
                rule.parse(["User-agent: *", "Allow: /"])
            with self.lock:
                self.robots[origin] = rule
        return rule.can_fetch(USER_AGENT, url)
