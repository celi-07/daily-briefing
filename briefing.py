#!/usr/bin/env python3
"""
Daily Morning Briefing — Finance & Technology News Digest
=========================================================
Fetches news from RSS feeds, market data from Yahoo Finance,
generates AI-powered analysis via Gemini, and sends a beautifully
formatted HTML email digest.

Usage:
    python briefing.py              # Run with .env file (local)
    python briefing.py --dry-run    # Generate HTML without sending email
    python briefing.py --preview    # Save HTML to preview.html and open in browser

Environment Variables:
    GEMINI_API_KEY      - Google AI Studio API key (free)
    GMAIL_ADDRESS       - Gmail address to send from
    GMAIL_APP_PASSWORD  - Gmail App Password (not your regular password)
    RECIPIENT_EMAIL     - (Optional) recipient email, defaults to GMAIL_ADDRESS
"""

import feedparser
from google import genai
import smtplib
import ssl
import json
import os
import re
import sys
import logging
import math
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

# Load .env file if present (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Optional: yfinance for market data
try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

# ─── Configuration ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Timezone (UTC+7 for WIB / Jakarta)
LOCAL_TZ = timezone(timedelta(hours=7))

# Number of stories to show per category
STORIES_PER_CATEGORY = 5

# ─── RSS Feeds ────────────────────────────────────────────────────────
FINANCE_FEEDS = {
    "BBC Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "CNBC Top News": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "CNBC Finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "MarketWatch": "http://feeds.marketwatch.com/marketwatch/topstories/",
    "NPR Business": "https://feeds.npr.org/1006/rss.xml",
    "WSJ Markets": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "Bloomberg": "https://feeds.bloomberg.com/markets/news.rss",
}

CRYPTO_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph": "https://cointelegraph.com/rss",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/feed",
    "The Block": "https://www.theblock.co/rss.xml",
    "Pintu News": "https://pintu.co.id/news/rss-feed.xml",
    "Pintu Market": "https://pintu.co.id/news/categories/market/rss-feed.xml",
}

INDONESIA_FEEDS = {
    "Nikkei Asia": "https://asia.nikkei.com/rss/feed/nar",
    "SCMP SE Asia": "https://www.scmp.com/rss/318208/feed",
    "Channel News Asia": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511",
    "Straits Times Asia": "https://www.straitstimes.com/news/asia/rss.xml",
}

TECH_FEEDS = {
    "TechCrunch": "https://techcrunch.com/feed/",
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "MIT Tech Review": "https://www.technologyreview.com/feed/",
    "Wired": "https://www.wired.com/feed/rss",
}

# ─── Category Descriptions (for semantic matching) ────────────────────
CATEGORY_DESCRIPTIONS = {
    "finance": (
        "Global financial markets, stock market movements, banking, central bank policy, "
        "interest rates, inflation, GDP, corporate earnings, IPOs, mergers and acquisitions, "
        "Wall Street, bonds, yields, treasury, forex, currency exchange, trade wars, tariffs, "
        "sanctions, geopolitics affecting markets, OPEC, oil prices, gold, commodities, "
        "recession, market rally, bull and bear markets, investor sentiment, "
        "major financial institutions (JPMorgan, Goldman Sachs, Morgan Stanley, BlackRock), "
        "big tech companies financials (Apple, Microsoft, Google, Amazon, Meta, Nvidia, Tesla), "
        "revenue, profit, debt, hedge funds, private equity"
    ),
    "crypto": (
        "Cryptocurrency markets, Bitcoin, Ethereum, blockchain technology, DeFi, NFTs, Web3, "
        "crypto exchanges (Binance, Coinbase), stablecoins, crypto regulation, SEC enforcement, "
        "token launches, altcoins, crypto mining, halving events, Solana, XRP, "
        "digital assets, CBDC, Tether, USDC, whale activity, decentralized finance protocols"
    ),
    "indonesia": (
        "Indonesia economy, Jakarta, Indonesian Rupiah, Bank Indonesia monetary policy, OJK, "
        "IDX Jakarta stock exchange, IHSG/JCI index, ASEAN, Southeast Asian economics, "
        "Pertamina, Telkom, BCA, BRI, Mandiri, nickel exports, palm oil, coal, "
        "Indonesian government policy, Garuda, Astra, GoTo, Tokopedia, "
        "Indonesian infrastructure, digital economy in Indonesia"
    ),
    "tech": (
        "Quantum computing, artificial intelligence, machine learning, robotics, "
        "semiconductor chips, 5G/6G networks, SpaceX, tech startups, cybersecurity, "
        "hacking, privacy, open source software, cloud computing, data centers, "
        "major tech companies (Apple, Google, Microsoft, Nvidia, AMD, Intel, TSMC, Samsung), "
        "AI labs (OpenAI, Anthropic, DeepMind), biotech, gene editing, "
        "nuclear fusion, batteries, electric vehicles, autonomous driving, LLMs, "
        "generative AI, ChatGPT, Gemini"
    ),
}

# ─── Market Tickers ──────────────────────────────────────────────────
MARKET_TICKERS = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "Dow Jones": "^DJI",
    "Bitcoin": "BTC-USD",
    "Ethereum": "ETH-USD",
    "Gold": "GC=F",
    "Crude Oil": "CL=F",
    "USD/IDR": "IDR=X",
    "IDX Composite": "^JKSE",
}


# ─── Helpers ──────────────────────────────────────────────────────────

def get_env(key: str, required: bool = True) -> str | None:
    """Get environment variable with validation."""
    val = os.environ.get(key)
    if required and not val:
        log.error(f"Missing required environment variable: {key}")
        sys.exit(1)
    return val


# ═════════════════════════════════════════════════════════════════════
# SEMANTIC RELEVANCE SCORING (via Gemini Embeddings)
# ═════════════════════════════════════════════════════════════════════

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_semantic_relevance(
    articles: list[dict],
    category: str,
    client: genai.Client,
    threshold: float = 0.3,
) -> list[dict]:
    """Score and filter articles by semantic similarity to a category description.

    Uses Gemini's text-embedding model to compare each article's text against
    the category description. Articles scoring above the threshold are returned,
    sorted by relevance (highest first). If too few match, all articles are
    returned sorted by score.
    """
    description = CATEGORY_DESCRIPTIONS.get(category, "")
    if not description or not articles:
        return articles

    try:
        # Embed the category description
        cat_result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=description,
        )
        cat_vec = cat_result.embeddings[0].values

        # Embed all article texts in one batch
        article_texts = [
            f"{a['title']}. {a['summary'][:300]}" for a in articles
        ]

        # Batch in groups of 100 (API limit) with retry for rate limits
        all_scores: list[float] = []
        for i in range(0, len(article_texts), 100):
            batch = article_texts[i:i + 100]
            for attempt in range(3):
                try:
                    art_result = client.models.embed_content(
                        model="gemini-embedding-001",
                        contents=batch,
                    )
                    for emb in art_result.embeddings:
                        score = _cosine_similarity(cat_vec, emb.values)
                        all_scores.append(score)
                    break
                except Exception as retry_err:
                    err_str = str(retry_err)
                    if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < 2:
                        wait = (attempt + 1) * 15
                        log.info(f"    Rate limited, waiting {wait}s before retry...")
                        time.sleep(wait)
                    else:
                        raise retry_err

        # Pair articles with scores and sort
        scored = list(zip(articles, all_scores))
        scored.sort(key=lambda x: x[1], reverse=True)

        # Filter by threshold
        filtered = [a for a, s in scored if s >= threshold]
        if len(filtered) >= 3:
            log.info(f"    Semantic filter: {len(filtered)}/{len(articles)} articles above threshold {threshold}")
            return filtered
        else:
            # Not enough matched — return all sorted by relevance
            log.info(f"    Semantic filter: only {len(filtered)} above threshold, returning all {len(articles)} sorted by relevance")
            return [a for a, s in scored]

    except Exception as e:
        log.warning(f"    ⚠ Semantic scoring failed ({e}), returning all articles unsorted")
        return articles


# ═════════════════════════════════════════════════════════════════════
# RSS FETCHING
# ═════════════════════════════════════════════════════════════════════

def fetch_feed_articles(feed_name: str, feed_url: str, hours: int = 24) -> list[dict]:
    """Fetch articles from a single RSS feed published within the last N hours."""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    try:
        feed = feedparser.parse(feed_url)
        if feed.bozo and not feed.entries:
            log.warning(f"  ⚠ Failed to parse feed: {feed_name}")
            return []

        for entry in feed.entries[:25]:
            # Parse publish date
            pub_date = None
            for attr in ("published_parsed", "updated_parsed"):
                parsed = getattr(entry, attr, None)
                if parsed:
                    try:
                        pub_date = datetime(*parsed[:6], tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        pass
                    break

            # Skip old articles (if date available)
            if pub_date and pub_date < cutoff:
                continue

            # Extract summary, strip HTML tags
            summary = ""
            for attr in ("summary", "description", "content"):
                raw = ""
                if attr == "content" and hasattr(entry, "content"):
                    raw = entry.content[0].get("value", "") if entry.content else ""
                else:
                    raw = getattr(entry, attr, "")
                if raw:
                    summary = re.sub(r"<[^>]+>", "", raw).strip()[:500]
                    break

            articles.append({
                "title": entry.get("title", "Untitled").strip(),
                "link": entry.get("link", ""),
                "summary": summary,
                "source": feed_name,
                "date": pub_date.isoformat() if pub_date else "",
            })

    except Exception as e:
        log.warning(f"  ⚠ Error fetching {feed_name}: {e}")

    return articles


def fetch_category_articles(
    feeds: dict,
    category: str,
    client: genai.Client,
    hours: int = 24,
) -> list[dict]:
    """Fetch articles for a category and rank by semantic relevance."""
    all_articles = []
    for name, url in feeds.items():
        arts = fetch_feed_articles(name, url, hours)
        log.info(f"  ✓ {name}: {len(arts)} articles")
        all_articles.extend(arts)

    if not all_articles:
        return []

    # Use semantic relevance scoring instead of keyword matching
    log.info(f"  Scoring semantic relevance for '{category}'...")
    return compute_semantic_relevance(all_articles, category, client)


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """Remove near-duplicate articles by fuzzy title matching."""
    seen_titles: list[frozenset] = []
    unique = []

    for article in articles:
        normalized = re.sub(r"[^a-z0-9\s]", "", article["title"].lower())
        words = frozenset(normalized.split())
        if not words:
            continue

        is_dup = False
        for seen in seen_titles:
            overlap = len(words & seen) / max(len(words | seen), 1)
            if overlap > 0.7:
                is_dup = True
                break

        if not is_dup:
            seen_titles.append(words)
            unique.append(article)

    return unique


# ═════════════════════════════════════════════════════════════════════
# MARKET DATA
# ═════════════════════════════════════════════════════════════════════

def fetch_market_snapshot() -> list[dict]:
    """Fetch latest market prices and daily changes using yfinance."""
    if not HAS_YFINANCE:
        log.info("  ℹ yfinance not installed — skipping market snapshot")
        return []

    snapshot = []
    for name, ticker in MARKET_TICKERS.items():
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(period="5d")
            if len(hist) >= 2:
                current = hist["Close"].iloc[-1]
                previous = hist["Close"].iloc[-2]
                change = current - previous
                change_pct = (change / previous) * 100
                snapshot.append({
                    "name": name,
                    "price": float(current),
                    "change": float(change),
                    "change_pct": float(change_pct),
                })
                log.info(f"  ✓ {name}: {current:,.2f} ({change_pct:+.2f}%)")
            elif len(hist) == 1:
                snapshot.append({
                    "name": name,
                    "price": float(hist["Close"].iloc[-1]),
                    "change": 0.0,
                    "change_pct": 0.0,
                })
        except Exception as e:
            log.warning(f"  ⚠ Failed to fetch {name}: {e}")

    return snapshot


# ═════════════════════════════════════════════════════════════════════
# FALLBACK: Generate stories from raw articles when AI fails
# ═════════════════════════════════════════════════════════════════════

def _build_fallback_stories(articles: list[dict], count: int = STORIES_PER_CATEGORY) -> list[dict]:
    """Create story entries from raw RSS articles when Gemini is unavailable."""
    stories = []
    for a in articles[:count]:
        stories.append({
            "title": a["title"],
            "summary": a["summary"][:300] if a["summary"] else "Full details available at source.",
            "analysis": f"Source: {a['source']}. Read the full article for complete analysis.",
            "source_url": a.get("link", ""),
        })
    return stories


def _build_fallback_market_summary(market_data: list[dict]) -> str:
    """Generate a basic market summary from raw market data."""
    if not market_data:
        return "Market data is currently being refreshed. Check back for the latest figures."

    gainers = [m for m in market_data if m["change_pct"] > 0]
    losers = [m for m in market_data if m["change_pct"] < 0]

    parts = []
    if gainers:
        top = sorted(gainers, key=lambda x: x["change_pct"], reverse=True)[:3]
        names = ", ".join(f"{m['name']} (+{m['change_pct']:.2f}%)" for m in top)
        parts.append(f"Leading gainers: {names}.")
    if losers:
        bottom = sorted(losers, key=lambda x: x["change_pct"])[:3]
        names = ", ".join(f"{m['name']} ({m['change_pct']:.2f}%)" for m in bottom)
        parts.append(f"Notable decliners: {names}.")

    return " ".join(parts) if parts else "Markets showed mixed performance in today's session."


def _build_fallback_analysis(
    finance_articles: list[dict],
    crypto_articles: list[dict],
    indonesia_articles: list[dict],
    tech_articles: list[dict],
    market_data: list[dict],
) -> dict:
    """Build a complete analysis dict from raw data (no AI needed)."""
    return {
        "market_summary": _build_fallback_market_summary(market_data),
        "finance": {
            "headline": "Global Finance Roundup",
            "stories": _build_fallback_stories(finance_articles),
        },
        "crypto": {
            "headline": "Cryptocurrency Update",
            "stories": _build_fallback_stories(crypto_articles),
        },
        "indonesia": {
            "headline": "Indonesian Market Watch",
            "stories": _build_fallback_stories(indonesia_articles),
        },
        "tech": {
            "headline": "Technology Frontlines",
            "stories": _build_fallback_stories(tech_articles),
        },
        "key_takeaways": _build_fallback_takeaways(
            finance_articles, crypto_articles, indonesia_articles, tech_articles
        ),
        "what_to_watch": [
            "Monitor central bank announcements and monetary policy shifts this week.",
            "Track major tech earnings reports and semiconductor supply chain developments.",
            "Watch for crypto regulatory updates and institutional adoption signals.",
        ],
        "connections": _build_fallback_connections(
            finance_articles, crypto_articles, indonesia_articles, tech_articles
        ),
    }


def _build_fallback_takeaways(
    finance: list[dict], crypto: list[dict],
    indonesia: list[dict], tech: list[dict],
) -> list[str]:
    """Build key takeaways from the top article in each category."""
    takeaways = []
    if finance:
        takeaways.append(f"Finance: {finance[0]['title']}")
    if crypto:
        takeaways.append(f"Crypto: {crypto[0]['title']}")
    if indonesia:
        takeaways.append(f"Indonesia: {indonesia[0]['title']}")
    if tech:
        takeaways.append(f"Tech: {tech[0]['title']}")
    if not takeaways:
        takeaways.append("Today's news cycle is quieter than usual — a good day to review portfolio positioning.")
    return takeaways[:5]


def _build_fallback_connections(
    finance: list[dict], crypto: list[dict],
    indonesia: list[dict], tech: list[dict],
) -> str:
    """Build a connections paragraph from available categories."""
    active = []
    if finance:
        active.append("global finance")
    if crypto:
        active.append("cryptocurrency markets")
    if indonesia:
        active.append("Indonesian economy")
    if tech:
        active.append("the tech sector")

    if len(active) >= 2:
        sectors = ", ".join(active[:-1]) + f" and {active[-1]}"
        return (
            f"Today's developments across {sectors} show interconnected trends. "
            "Global monetary policy continues to ripple through digital assets and emerging markets, "
            "while technology innovation drives new investment patterns across all sectors. "
            "Keep an eye on how regulatory moves in one domain create opportunities or risks in others."
        )
    return (
        "Cross-sector dynamics remain fluid. Developments in any single sector can rapidly "
        "propagate across markets — particularly at the intersection of technology, regulation, "
        "and global capital flows."
    )


# ═════════════════════════════════════════════════════════════════════
# AI ANALYSIS (Gemini)
# ═════════════════════════════════════════════════════════════════════

def generate_analysis(
    finance_articles: list[dict],
    crypto_articles: list[dict],
    indonesia_articles: list[dict],
    tech_articles: list[dict],
    market_data: list[dict],
) -> dict:
    """Use Gemini Flash to produce a structured news analysis."""
    api_key = get_env("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    # ── Build context ──
    sections = {
        "Global Finance": finance_articles[:15],
        "Cryptocurrency": crypto_articles[:10],
        "Indonesian Market": indonesia_articles[:10],
        "Technology": tech_articles[:15],
    }

    context_parts: list[str] = []
    for section_name, articles in sections.items():
        if articles:
            context_parts.append(f"\n## {section_name} Articles:")
            for i, a in enumerate(articles, 1):
                context_parts.append(f"{i}. [{a['source']}] {a['title']}")
                if a["summary"]:
                    context_parts.append(f"   {a['summary'][:250]}")
                if a["link"]:
                    context_parts.append(f"   URL: {a['link']}")

    if market_data:
        context_parts.append("\n## Market Snapshot:")
        for m in market_data:
            arrow = "▲" if m["change_pct"] >= 0 else "▼"
            context_parts.append(
                f"  {m['name']}: {m['price']:,.2f} ({arrow} {m['change_pct']:+.2f}%)"
            )

    context = "\n".join(context_parts)

    prompt = f"""You are a senior financial and technology analyst preparing a daily morning 
briefing for a professional reader based in Indonesia who follows global finance, 
cryptocurrency, the Indonesian market, and emerging technology.

Based on the following news articles and market data from the last 24 hours, produce a 
comprehensive morning briefing. Write in a professional but engaging tone — like a premium 
newsletter (think Morning Brew meets The Economist).

{context}

Return a JSON object with this EXACT structure:
{{
    "market_summary": "2-3 sentence overview of how markets performed overnight",
    "finance": {{
        "headline": "One punchy section headline",
        "stories": [
            {{
                "title": "Story headline",
                "summary": "2-3 sentence summary of what happened",
                "analysis": "1-2 sentences: why this matters, implications, what the reader should take away",
                "source_url": "original article URL if available, otherwise empty string"
            }}
        ]
    }},
    "crypto": {{
        "headline": "One punchy section headline",
        "stories": [ ... same format ... ]
    }},
    "indonesia": {{
        "headline": "One punchy section headline",
        "stories": [ ... same format ... ]
    }},
    "tech": {{
        "headline": "One punchy section headline",
        "stories": [ ... same format ... ]
    }},
    "key_takeaways": [
        "3-5 bullet-point strings: the most important things the reader should know today"
    ],
    "what_to_watch": [
        "2-3 strings: upcoming events, data releases, or trends to monitor this week"
    ],
    "connections": "A paragraph (3-5 sentences) connecting the dots across sectors — how geopolitics is affecting crypto, how tech trends impact Indonesian commodities, cross-sector ripple effects, etc."
}}

Rules:
- Select EXACTLY {STORIES_PER_CATEGORY} stories per section (quality over quantity)
- Be specific: use numbers, company names, percentages, dates
- Analysis must be ACTIONABLE — not generic "this is significant"
- For Indonesia: consider IDR/USD, Bank Indonesia policy, commodity exports, IHSG
- For crypto: note regulatory moves, whale activity, DeFi developments
- For tech: prioritize quantum computing, AI/LLM advances, semiconductor supply chain
- "connections" should demonstrate strategic, cross-sector thinking
- If a section has few/no articles, still provide {STORIES_PER_CATEGORY} stories by synthesizing 
  from related context or noting the quiet landscape and what to expect
- Return ONLY valid JSON — no markdown fences, no commentary outside the JSON"""

    max_retries = 3
    text = ""
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.1-pro-preview",
                contents=prompt,
            )
            text = response.text.strip()

            # Strip markdown code fences if present
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*\n?", "", text)
                text = re.sub(r"\n?\s*```\s*$", "", text)

            result = json.loads(text)

            # Log what the AI produced
            for key in ("finance", "crypto", "indonesia", "tech"):
                sec = result.get(key, {})
                n = len(sec.get("stories", []))
                hl = sec.get("headline", "N/A")
                log.info(f"  AI → {key}: {n} stories, headline: {hl}")
            log.info(f"  AI → connections: {len(result.get('connections', ''))} chars")

            # Ensure each section has stories — fill from raw articles if needed
            category_map = {
                "finance": finance_articles,
                "crypto": crypto_articles,
                "indonesia": indonesia_articles,
                "tech": tech_articles,
            }
            for key, raw_articles in category_map.items():
                section = result.get(key, {})
                stories = section.get("stories", [])
                if len(stories) < STORIES_PER_CATEGORY and raw_articles:
                    # Pad with raw article data
                    existing_titles = {s.get("title", "").lower() for s in stories}
                    for a in raw_articles:
                        if len(stories) >= STORIES_PER_CATEGORY:
                            break
                        if a["title"].lower() not in existing_titles:
                            stories.append({
                                "title": a["title"],
                                "summary": a["summary"][:300] or "Details available at source.",
                                "analysis": f"Source: {a['source']}.",
                                "source_url": a.get("link", ""),
                            })
                            existing_titles.add(a["title"].lower())
                    section["stories"] = stories
                    result[key] = section

            return result

        except json.JSONDecodeError as e:
            log.error(f"Failed to parse Gemini JSON: {e}")
            if text:
                log.debug(f"Raw response: {text[:500]}")
            break  # Don't retry JSON parse errors
        except Exception as e:
            err_str = str(e)
            if ("503" in err_str or "429" in err_str or "UNAVAILABLE" in err_str
                    or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                wait = (attempt + 1) * 20
                log.warning(f"  Gemini API temporarily unavailable, retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                log.error(f"Gemini API error: {e}")
                break

    # Fallback: build from raw articles instead of returning empty placeholders
    log.info("  Building fallback analysis from raw article data...")
    return _build_fallback_analysis(
        finance_articles, crypto_articles, indonesia_articles,
        tech_articles, market_data,
    )


# ═════════════════════════════════════════════════════════════════════
# HTML EMAIL BUILDER — Premium Dark Mode Design
# ═════════════════════════════════════════════════════════════════════

def _fmt_price(price: float) -> str:
    if price >= 1000:
        return f"{price:,.0f}"
    elif price >= 1:
        return f"{price:,.2f}"
    return f"{price:,.4f}"


def _market_bar_html(market_data: list[dict]) -> str:
    """Responsive market ticker strip — dark glass design."""
    if not market_data:
        return '<p style="color:#64748b;font-size:13px;text-align:center;padding:20px;">Market data is being refreshed.</p>'

    cells = []
    for m in market_data:
        if m["change_pct"] >= 0:
            color = "#34d399"
            arrow = "▲"
            bg = "rgba(52,211,153,0.08)"
        else:
            color = "#f87171"
            arrow = "▼"
            bg = "rgba(248,113,113,0.08)"

        cells.append(f"""<td style="padding:14px 16px;text-align:center;border-right:1px solid rgba(255,255,255,0.04);">
<div style="font-size:9px;color:#94a3b8;text-transform:uppercase;letter-spacing:1.2px;font-weight:600;white-space:nowrap;">{escape(m['name'])}</div>
<div style="font-size:16px;font-weight:700;color:#f1f5f9;margin:4px 0;">{_fmt_price(m['price'])}</div>
<div style="display:inline-block;font-size:11px;color:{color};font-weight:600;background:{bg};padding:2px 8px;border-radius:4px;">{arrow} {m['change_pct']:+.2f}%</div>
</td>""")

    return f"""<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">
<table width="100%" cellpadding="0" cellspacing="0"
       style="background:rgba(15,23,42,0.6);border:1px solid rgba(255,255,255,0.06);border-radius:12px;">
<tr>{''.join(cells)}</tr></table></div>"""


def _story_html(story: dict, index: int, accent: str, accent_light: str) -> str:
    title = escape(story.get("title", ""))
    summary = escape(story.get("summary", ""))
    analysis = escape(story.get("analysis", ""))
    url = story.get("source_url", "")

    title_el = (
        f'<a href="{url}" style="color:#f1f5f9;text-decoration:none;border-bottom:1px solid rgba(255,255,255,0.15);padding-bottom:1px;transition:all 0.2s;" target="_blank">{title}</a>'
        if url else f'<span style="color:#f1f5f9;">{title}</span>'
    )

    return f"""<div style="margin-bottom:20px;padding:18px 20px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.05);border-radius:10px;border-left:3px solid {accent};">
<div style="display:flex;align-items:flex-start;gap:12px;">
<div style="flex-shrink:0;width:24px;height:24px;background:{accent};border-radius:6px;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:#0f172a;">{index}</div>
<div style="flex:1;">
<h3 style="margin:0 0 8px;font-size:14px;font-weight:600;line-height:1.5;">{title_el}</h3>
<p style="margin:0 0 12px;font-size:13px;color:#94a3b8;line-height:1.7;">{summary}</p>
<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.05);padding:10px 14px;border-radius:8px;">
<p style="margin:0;font-size:12px;color:{accent_light};line-height:1.6;">
<span style="font-weight:700;letter-spacing:0.3px;">ANALYSIS</span>&nbsp;&nbsp;{analysis}</p></div>
</div></div></div>"""


def _section_html(section: dict, label: str, accent: str, accent_light: str, symbol: str) -> str:
    headline = escape(section.get("headline", ""))
    stories = section.get("stories", [])

    body = (
        "\n".join(_story_html(s, i, accent, accent_light) for i, s in enumerate(stories, 1))
        if stories
        else f'<div style="text-align:center;padding:30px 20px;"><p style="color:#475569;font-size:13px;margin:0;">No stories available for this section. Check source feeds for the latest updates.</p></div>'
    )

    return f"""<div style="margin-bottom:36px;">
<table width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="padding:0 0 16px;">
<table cellpadding="0" cellspacing="0"><tr>
<td style="width:36px;height:36px;background:{accent};border-radius:8px;text-align:center;vertical-align:middle;font-size:18px;line-height:36px;">{symbol}</td>
<td style="padding-left:12px;">
<h2 style="margin:0;font-size:18px;color:#f1f5f9;font-weight:700;letter-spacing:-0.3px;">{headline}</h2>
<div style="margin-top:2px;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px;font-weight:600;">{label}</div>
</td></tr></table>
</td></tr></table>
{body}</div>"""


def build_html_email(analysis: dict, market_data: list[dict]) -> str:
    """Assemble the full HTML email from structured analysis."""
    now = datetime.now(LOCAL_TZ)
    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M %p")

    market_bar = _market_bar_html(market_data)
    mkt_summary = escape(analysis.get("market_summary", ""))

    sections = "".join([
        _section_html(analysis.get("finance", {}), "Global Finance", "#3b82f6", "#93c5fd", "&#36;"),
        _section_html(analysis.get("crypto", {}), "Cryptocurrency", "#f59e0b", "#fcd34d", "&#8383;"),
        _section_html(analysis.get("indonesia", {}), "Indonesian Market", "#ef4444", "#fca5a5", "&#9670;"),
        _section_html(analysis.get("tech", {}), "Technology", "#8b5cf6", "#c4b5fd", "&#9670;"),
    ])

    takeaways = "\n".join(
        f'<tr><td style="padding:0 0 10px 0;vertical-align:top;width:20px;"><div style="width:6px;height:6px;background:#34d399;border-radius:50%;margin-top:7px;"></div></td><td style="padding:0 0 10px 10px;font-size:13px;color:#d1fae5;line-height:1.7;">{escape(t)}</td></tr>'
        for t in analysis.get("key_takeaways", [])
    )
    watch_items = "\n".join(
        f'<tr><td style="padding:0 0 10px 0;vertical-align:top;width:20px;"><div style="width:6px;height:6px;background:#fbbf24;border-radius:50%;margin-top:7px;"></div></td><td style="padding:0 0 10px 10px;font-size:13px;color:#fef3c7;line-height:1.7;">{escape(w)}</td></tr>'
        for w in analysis.get("what_to_watch", [])
    )
    connections = escape(analysis.get("connections", ""))

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Morning Briefing — {date_str}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
  * {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; }}
  a:hover {{ opacity: 0.85; }}
</style>
</head>
<body style="margin:0;padding:0;background:#0a0f1a;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;-webkit-font-smoothing:antialiased;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0f1a;padding:24px 0;">
<tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0" style="max-width:680px;width:100%;background:#0f172a;border-radius:16px;overflow:hidden;border:1px solid rgba(255,255,255,0.06);box-shadow:0 25px 50px rgba(0,0,0,0.5);">

<!-- ═══ HEADER ═══ -->
<tr><td style="background:linear-gradient(135deg,#1e293b 0%,#0f172a 50%,#1a1a2e 100%);padding:40px 44px 36px;text-align:center;position:relative;">
<div style="margin-bottom:16px;">
<span style="display:inline-block;background:linear-gradient(135deg,#3b82f6,#8b5cf6);padding:6px 16px;border-radius:20px;font-size:10px;color:#fff;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;">DAILY DIGEST</span>
</div>
<h1 style="margin:0;font-size:32px;color:#f8fafc;font-weight:900;letter-spacing:-1px;line-height:1.2;">Morning Briefing</h1>
<p style="margin:10px 0 0;font-size:13px;color:#64748b;font-weight:500;">{date_str}</p>
<div style="margin-top:20px;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.1),transparent);"></div>
</td></tr>

<!-- ═══ MARKET SNAPSHOT ═══ -->
<tr><td style="padding:28px 44px 0;">
<table width="100%" cellpadding="0" cellspacing="0"><tr>
<td><span style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;font-weight:700;">Market Snapshot</span></td>
<td align="right"><span style="font-size:10px;color:#475569;">{time_str} WIB</span></td>
</tr></table>
<div style="margin-top:12px;">{market_bar}</div>
<div style="margin-top:16px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);border-radius:10px;padding:16px 20px;">
<p style="margin:0;font-size:13px;color:#cbd5e1;line-height:1.75;">{mkt_summary}</p>
</div>
</td></tr>

<!-- ═══ DIVIDER ═══ -->
<tr><td style="padding:28px 44px 0;"><div style="height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.06),transparent);"></div></td></tr>

<!-- ═══ NEWS SECTIONS ═══ -->
<tr><td style="padding:28px 44px 0;">{sections}</td></tr>

<!-- ═══ KEY TAKEAWAYS ═══ -->
<tr><td style="padding:0 44px 24px;">
<div style="background:linear-gradient(135deg,rgba(16,185,129,0.08),rgba(52,211,153,0.04));border:1px solid rgba(52,211,153,0.15);border-radius:14px;padding:24px 28px;">
<table cellpadding="0" cellspacing="0"><tr>
<td style="width:32px;height:32px;background:rgba(52,211,153,0.15);border-radius:8px;text-align:center;vertical-align:middle;font-size:14px;line-height:32px;color:#34d399;font-weight:800;">&#10003;</td>
<td style="padding-left:12px;"><h2 style="margin:0;font-size:16px;color:#6ee7b7;font-weight:700;">Key Takeaways</h2></td>
</tr></table>
<table style="margin-top:16px;" cellpadding="0" cellspacing="0">{takeaways}</table>
</div>
</td></tr>

<!-- ═══ CONNECTING THE DOTS ═══ -->
<tr><td style="padding:0 44px 24px;">
<div style="background:linear-gradient(135deg,rgba(139,92,246,0.08),rgba(167,139,250,0.04));border:1px solid rgba(139,92,246,0.15);border-radius:14px;padding:24px 28px;">
<table cellpadding="0" cellspacing="0"><tr>
<td style="width:32px;height:32px;background:rgba(139,92,246,0.15);border-radius:8px;text-align:center;vertical-align:middle;font-size:16px;line-height:32px;color:#a78bfa;">&#8644;</td>
<td style="padding-left:12px;"><h2 style="margin:0;font-size:16px;color:#c4b5fd;font-weight:700;">Connecting the Dots</h2></td>
</tr></table>
<p style="margin:16px 0 0;font-size:13px;color:#cbd5e1;line-height:1.8;">{connections}</p>
</div>
</td></tr>

<!-- ═══ WHAT TO WATCH ═══ -->
<tr><td style="padding:0 44px 32px;">
<div style="background:linear-gradient(135deg,rgba(245,158,11,0.08),rgba(251,191,36,0.04));border:1px solid rgba(245,158,11,0.15);border-radius:14px;padding:24px 28px;">
<table cellpadding="0" cellspacing="0"><tr>
<td style="width:32px;height:32px;background:rgba(245,158,11,0.15);border-radius:8px;text-align:center;vertical-align:middle;font-size:14px;line-height:32px;color:#fbbf24;font-weight:800;">&#9654;</td>
<td style="padding-left:12px;"><h2 style="margin:0;font-size:16px;color:#fde68a;font-weight:700;">What to Watch</h2></td>
</tr></table>
<table style="margin-top:16px;" cellpadding="0" cellspacing="0">{watch_items}</table>
</div>
</td></tr>

<!-- ═══ FOOTER ═══ -->
<tr><td style="background:rgba(0,0,0,0.2);padding:28px 44px;text-align:center;border-top:1px solid rgba(255,255,255,0.04);">
<p style="margin:0;font-size:11px;color:#475569;font-weight:500;">Generated by Morning Briefing &middot; Powered by Gemini &amp; RSS</p>
<p style="margin:6px 0 0;font-size:10px;color:#334155;">{time_str} WIB &middot; Automated digest, not financial advice</p>
</td></tr>

</table></td></tr></table>
</body></html>"""


# ═════════════════════════════════════════════════════════════════════
# EMAIL SENDING
# ═════════════════════════════════════════════════════════════════════

def send_email(html_content: str):
    """Send the briefing via Gmail SMTP over SSL."""
    sender = get_env("GMAIL_ADDRESS")
    password = get_env("GMAIL_APP_PASSWORD")
    recipient = get_env("RECIPIENT_EMAIL", required=False) or sender

    msg = MIMEMultipart("alternative")
    now = datetime.now(LOCAL_TZ)
    msg["Subject"] = f"Morning Briefing — {now.strftime('%b %d, %Y')}"
    msg["From"] = f"Morning Briefing <{sender}>"
    msg["To"] = recipient

    msg.attach(MIMEText(
        "Your daily morning briefing is ready. Open in an HTML-capable client for the full experience.",
        "plain",
    ))
    msg.attach(MIMEText(html_content, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())

    log.info(f"✅ Briefing sent to {recipient}")


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    dry_run = "--dry-run" in sys.argv
    preview = "--preview" in sys.argv

    log.info("🌅 Starting Morning Briefing generation...")

    # Initialize Gemini client for semantic scoring
    api_key = get_env("GEMINI_API_KEY")
    gemini_client = genai.Client(api_key=api_key)

    # 1 ─ Fetch news ───────────────────────────────────────────────────
    log.info("📰 Fetching finance articles...")
    finance_articles = deduplicate_articles(
        fetch_category_articles(FINANCE_FEEDS, "finance", gemini_client)
    )
    log.info("📰 Fetching crypto articles...")
    crypto_articles = deduplicate_articles(
        fetch_category_articles(CRYPTO_FEEDS, "crypto", gemini_client)
    )
    log.info("📰 Fetching Indonesian market articles...")
    indonesia_articles = deduplicate_articles(
        fetch_category_articles(INDONESIA_FEEDS, "indonesia", gemini_client)
    )
    log.info("📰 Fetching tech articles...")
    tech_articles = deduplicate_articles(
        fetch_category_articles(TECH_FEEDS, "tech", gemini_client)
    )

    total = sum(map(len, [finance_articles, crypto_articles, indonesia_articles, tech_articles]))
    log.info(
        f"📊 Total: {total} articles "
        f"(Finance:{len(finance_articles)} Crypto:{len(crypto_articles)} "
        f"Indonesia:{len(indonesia_articles)} Tech:{len(tech_articles)})"
    )

    # 2 ─ Market data ──────────────────────────────────────────────────
    log.info("📈 Fetching market data...")
    market_data = fetch_market_snapshot()

    # 3 ─ AI analysis ──────────────────────────────────────────────────
    log.info("🤖 Generating AI analysis with Gemini...")
    analysis = generate_analysis(
        finance_articles, crypto_articles, indonesia_articles, tech_articles, market_data
    )

    # 4 ─ Build email ──────────────────────────────────────────────────
    log.info("✉️ Building HTML email...")
    html = build_html_email(analysis, market_data)

    # 5 ─ Send or save ─────────────────────────────────────────────────
    if preview or dry_run:
        out_path = Path("preview.html")
        out_path.write_text(html, encoding="utf-8")
        log.info(f"💾 Saved to {out_path.resolve()}")
        if preview:
            import webbrowser
            webbrowser.open(str(out_path.resolve()))
    else:
        log.info("📤 Sending email...")
        send_email(html)

    log.info("🎉 Morning Briefing complete!")


if __name__ == "__main__":
    main()
