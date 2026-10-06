import json
from urllib.parse import urlsplit

from app.enrich import parse_iso
from app.models import Article, SourceHealth, canonical_url, stable_id

ENDPOINT = "https://api.x.com/2/tweets/search/recent"


def fetch(source, fetcher, start, end):
    token = fetcher.settings.x_bearer_token.get_secret_value()
    health = SourceHealth(source_id=source.id, name=source.name, topics=source.topics, status="ok")
    if not token or not source.queries:
        health.status = "disabled"
        health.detail = "Configure X_BEARER_TOKEN and verified account/topic queries to enable X."
        return [], health
    articles = {}
    modern = fetcher.settings.x_api_schema == "post"
    for query in source.queries:
        params = {"query": f"({query}) -is:retweet -is:reply", "max_results": 100,
                  "start_time": start.isoformat().replace("+00:00", "Z"),
                  "end_time": end.isoformat().replace("+00:00", "Z"),
                  ("post.fields" if modern else "tweet.fields"):
                      "created_at,entities,note_post,lang,paid_partnership" if modern
                      else "created_at,author_id,entities,referenced_tweets,note_tweet,lang",
                  "expansions": "author_id,referenced_posts" if modern else "author_id", "user.fields": "username"}
        try:
            for page in range(fetcher.settings.source_pages):
                data, _ = fetcher.get(ENDPOINT, params=params, headers={"Authorization": f"Bearer {token}"})
                result = json.loads(data)
                if result.get("errors"):
                    raise ValueError("X returned incomplete/error results")
                usernames = {user["id"]: user["username"] for user in result.get("includes", {}).get("users", [])}
                for post in result.get("data", []):
                    if post.get("paid_partnership") or any(ref.get("type") == "retweeted"
                            for ref in post.get("referenced_posts", post.get("referenced_tweets", []))):
                        continue
                    published = parse_iso(post.get("created_at"))
                    if not published or not start <= published <= end:
                        health.status, health.detail = "partial", "Undated/out-of-window X posts quarantined."
                        continue
                    username = usernames.get(post.get("author_id"), "")
                    # Only explicit account configuration grants primary-source status.
                    trust = "primary" if username.lower() in {a.lower() for a in source.primary_accounts} else "unknown"
                    note = post.get("note_post") or post.get("note_tweet") or {}
                    text = note.get("text") or post.get("text", "")
                    urls = []
                    for link in note.get("entities", post.get("entities", {})).get("urls", []):
                        try:
                            url = canonical_url(link.get("unwound_url") or link.get("expanded_url", ""))
                            if urlsplit(url).hostname not in ("x.com", "twitter.com", "t.co"):
                                urls.append(url)
                        except ValueError:
                            continue
                    url = f"https://x.com/{username or 'i'}/status/{post['id']}"
                    article = Article(id=stable_id(url), source_id=source.id, source_name=f"X @{username}" if username else "X",
                        source_type="x", trust=trust, url=url, title=text.split("\n")[0][:180], text=text,
                        author=username, language=post.get("lang", "unknown"), quality="excerpt",
                        published_at=published, fetched_at=end, linked_urls=urls, topics=source.topics)
                    articles[article.id] = article
                token_next = result.get("meta", {}).get("next_token")
                if not token_next:
                    break
                params["next_token"] = token_next
            else:
                health.status, health.detail = "partial", "X pagination budget reached; coverage incomplete."
        except (RuntimeError, ValueError, KeyError):
            health.status = "partial" if articles else "failed"
            health.detail = "X access, rate limit, response, or request-budget failure; collection stopped."
            break
    health.fetched = len(articles)
    return list(articles.values()), health
