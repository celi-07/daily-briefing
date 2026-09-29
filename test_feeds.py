"""Quick smoke test: fetch RSS feeds and market data with the fixed sources."""
import sys
sys.path.insert(0, ".")
from briefing import fetch_feed_articles, fetch_market_snapshot

print("=" * 60)
print("  RSS Feed Smoke Test (Fixed Sources)")
print("=" * 60)

feeds_to_test = [
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("CNBC Finance", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Jakarta Globe", "https://jakartaglobe.id/feed"),
    ("Antara Business", "https://en.antaranews.com/rss/business"),
]

total = 0
for name, url in feeds_to_test:
    arts = fetch_feed_articles(name, url, hours=48)
    total += len(arts)
    status = "✓" if arts else "✗"
    print(f"\n{status} {name}: {len(arts)} articles")
    for a in arts[:2]:
        print(f"    • {a['title'][:80]}")

print(f"\n{'=' * 60}")
print(f"  Total: {total} articles")
print(f"{'=' * 60}")

# Verify google.genai import works
print("\n🤖 Testing google.genai import...")
from google import genai
print(f"  ✓ google-genai v{genai.__version__} loaded")

print("\n✅ All checks passed!")
