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

# ─── RSS Feeds ────────────────────────────────────────────────────────
FINANCE_FEEDS = {
    "BBC Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "CNBC Top News": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "CNBC Finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "MarketWatch": "http://feeds.marketwatch.com/marketwatch/topstories/",
    "NPR Business": "https://feeds.npr.org/1006/rss.xml",
    "WSJ Markets": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
}

CRYPTO_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph": "https://cointelegraph.com/rss",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/feed",
    "The Block": "https://www.theblock.co/rss.xml",
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

# ─── Relevance Keywords ──────────────────────────────────────────────
FINANCE_KEYWORDS = [
    "stock", "market", "bank", "fed", "interest rate", "inflation", "gdp",
    "earnings", "ipo", "merger", "acquisition", "wall street", "nasdaq",
    "s&p", "dow jones", "bond", "yield", "treasury", "forex", "currency",
    "trade war", "tariff", "sanction", "geopolit", "opec", "oil", "gold",
    "commodit", "recession", "rally", "bull", "bear", "investor",
    "jpmorgan", "goldman", "morgan stanley", "blackrock", "berkshire",
    "apple", "microsoft", "google", "amazon", "meta", "nvidia", "tesla",
    "revenue", "profit", "debt", "hedge fund", "private equity",
]

CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "defi",
    "nft", "web3", "binance", "coinbase", "stablecoin", "regulation",
    "sec", "token", "altcoin", "mining", "halving", "solana", "xrp",
    "digital asset", "cbdc", "tether", "usdc",
]

INDONESIA_KEYWORDS = [
    "indonesia", "jakarta", "rupiah", "idr", "bank indonesia", "ojk",
    "idx", "ihsg", "jci", "asean", "southeast asia", "pertamina",
    "telkom", "bca", "bri", "mandiri", "nickel", "palm oil", "coal",
    "prabowo", "omnibus", "garuda", "astra", "goto", "tokopedia",
]

TECH_KEYWORDS = [
    "quantum", "ai", "artificial intelligence", "machine learning",
    "robot", "chip", "semiconductor", "5g", "6g", "spacex", "startup",
    "cyber", "hack", "privacy", "open source", "cloud", "data center",
    "apple", "google", "microsoft", "nvidia", "amd", "intel", "tsmc",
    "samsung", "openai", "anthropic", "deepmind", "biotech", "gene",
    "fusion", "battery", "ev", "autonomous", "self-driving", "llm",
    "generative ai", "chatgpt", "gemini",
]

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


def fetch_category_articles(feeds: dict, keywords: list[str], hours: int = 24) -> list[dict]:
    """Fetch and keyword-filter articles for a whole category."""
    all_articles = []
    for name, url in feeds.items():
        arts = fetch_feed_articles(name, url, hours)
        log.info(f"  ✓ {name}: {len(arts)} articles")
        all_articles.extend(arts)

    # Keyword filter (keep all if too few match)
    if keywords:
        filtered = []
        for article in all_articles:
            text = f"{article['title']} {article['summary']}".lower()
            if any(kw in text for kw in keywords):
                filtered.append(article)
        return filtered if len(filtered) >= 3 else all_articles

    return all_articles


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
- Select the 3-5 MOST impactful stories per section (quality over quantity)
- Be specific: use numbers, company names, percentages, dates
- Analysis must be ACTIONABLE — not generic "this is significant"
- For Indonesia: consider IDR/USD, Bank Indonesia policy, commodity exports, IHSG
- For crypto: note regulatory moves, whale activity, DeFi developments
- For tech: prioritize quantum computing, AI/LLM advances, semiconductor supply chain
- "connections" should demonstrate strategic, cross-sector thinking
- If a section has few/no articles, briefly note the quiet landscape and what to expect
- Return ONLY valid JSON — no markdown fences, no commentary outside the JSON"""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?\s*```\s*$", "", text)

        return json.loads(text)

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse Gemini JSON: {e}")
        log.debug(f"Raw response: {text[:500]}")
    except Exception as e:
        log.error(f"Gemini API error: {e}")

    # Fallback structure
    return {
        "market_summary": "Market analysis is temporarily unavailable.",
        "finance": {"headline": "Global Finance", "stories": []},
        "crypto": {"headline": "Cryptocurrency", "stories": []},
        "indonesia": {"headline": "Indonesian Market", "stories": []},
        "tech": {"headline": "Technology", "stories": []},
        "key_takeaways": ["Briefing generation encountered an error — check source feeds directly."],
        "what_to_watch": ["Service will resume in the next edition."],
        "connections": "Cross-sector analysis unavailable for this edition.",
    }


# ═════════════════════════════════════════════════════════════════════
# HTML EMAIL BUILDER
# ═════════════════════════════════════════════════════════════════════

def _fmt_price(price: float) -> str:
    if price >= 1000:
        return f"{price:,.0f}"
    elif price >= 1:
        return f"{price:,.2f}"
    return f"{price:,.4f}"


def _market_bar_html(market_data: list[dict]) -> str:
    """Responsive market ticker strip."""
    if not market_data:
        return '<p style="color:#9ca3af;font-size:13px;">Market data unavailable.</p>'

    cells = []
    for m in market_data:
        color = "#16a34a" if m["change_pct"] >= 0 else "#dc2626"
        arrow = "▲" if m["change_pct"] >= 0 else "▼"
        cells.append(f"""<td style="padding:10px 14px;text-align:center;border-right:1px solid #e5e7eb;">
<div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;">{escape(m['name'])}</div>
<div style="font-size:15px;font-weight:700;color:#1f2937;margin:2px 0;">{_fmt_price(m['price'])}</div>
<div style="font-size:11px;color:{color};font-weight:600;">{arrow} {m['change_pct']:+.2f}%</div>
</td>""")

    return f"""<div style="overflow-x:auto;">
<table width="100%" cellpadding="0" cellspacing="0"
       style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;">
<tr>{''.join(cells)}</tr></table></div>"""


def _story_html(story: dict) -> str:
    title = escape(story.get("title", ""))
    summary = escape(story.get("summary", ""))
    analysis = escape(story.get("analysis", ""))
    url = story.get("source_url", "")

    title_el = (
        f'<a href="{url}" style="color:#1e40af;text-decoration:none;" target="_blank">{title}</a>'
        if url else title
    )

    return f"""<div style="margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid #f3f4f6;">
<h3 style="margin:0 0 6px;font-size:15px;color:#111827;line-height:1.4;">{title_el}</h3>
<p style="margin:0 0 10px;font-size:13px;color:#4b5563;line-height:1.65;">{summary}</p>
<div style="background:#eff6ff;border-left:3px solid #3b82f6;padding:10px 14px;border-radius:0 6px 6px 0;">
<p style="margin:0;font-size:12px;color:#1e40af;line-height:1.55;">
<strong>💡 Analysis:</strong> {analysis}</p></div></div>"""


def _section_html(section: dict, icon: str, accent: str) -> str:
    headline = escape(section.get("headline", ""))
    stories = section.get("stories", [])

    body = (
        "\n".join(_story_html(s) for s in stories)
        if stories
        else '<p style="color:#9ca3af;font-style:italic;font-size:13px;">No major stories in this category today.</p>'
    )

    return f"""<div style="margin-bottom:32px;">
<h2 style="margin:0 0 16px;font-size:19px;color:#111827;border-bottom:3px solid {accent};padding-bottom:8px;">
{icon} {headline}</h2>
{body}</div>"""


def build_html_email(analysis: dict, market_data: list[dict]) -> str:
    """Assemble the full HTML email from structured analysis."""
    now = datetime.now(LOCAL_TZ)
    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M %p")

    market_bar = _market_bar_html(market_data)
    mkt_summary = escape(analysis.get("market_summary", ""))

    sections = "".join([
        _section_html(analysis.get("finance", {}), "📊", "#2563eb"),
        _section_html(analysis.get("crypto", {}), "₿", "#f59e0b"),
        _section_html(analysis.get("indonesia", {}), "🇮🇩", "#dc2626"),
        _section_html(analysis.get("tech", {}), "🚀", "#7c3aed"),
    ])

    takeaways = "\n".join(
        f'<li style="margin-bottom:8px;font-size:13px;color:#166534;line-height:1.6;">{escape(t)}</li>'
        for t in analysis.get("key_takeaways", [])
    )
    watch_items = "\n".join(
        f'<li style="margin-bottom:8px;font-size:13px;color:#9a3412;line-height:1.6;">{escape(w)}</li>'
        for w in analysis.get("what_to_watch", [])
    )
    connections = escape(analysis.get("connections", ""))

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Morning Briefing — {date_str}</title></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:20px 0;"><tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,.07);">

<!-- ═══ HEADER ═══ -->
<tr><td style="background:linear-gradient(135deg,#1e3a5f 0%,#0f172a 100%);padding:32px 40px;text-align:center;">
<h1 style="margin:0;font-size:26px;color:#fff;font-weight:800;letter-spacing:-.5px;">☀️ Morning Briefing</h1>
<p style="margin:8px 0 0;font-size:13px;color:#94a3b8;">{date_str} · Finance &amp; Technology Digest</p>
</td></tr>

<!-- ═══ MARKET SNAPSHOT ═══ -->
<tr><td style="padding:24px 40px 0;">
<h2 style="margin:0 0 10px;font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;">Market Snapshot</h2>
{market_bar}
<p style="margin:12px 0 0;font-size:13px;color:#4b5563;line-height:1.65;">{mkt_summary}</p>
</td></tr>

<tr><td style="padding:16px 40px;"><hr style="border:none;border-top:1px solid #e5e7eb;"></td></tr>

<!-- ═══ NEWS SECTIONS ═══ -->
<tr><td style="padding:0 40px;">{sections}</td></tr>

<!-- ═══ KEY TAKEAWAYS ═══ -->
<tr><td style="padding:0 40px 20px;">
<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:20px;">
<h2 style="margin:0 0 10px;font-size:17px;color:#166534;">🎯 Key Takeaways</h2>
<ul style="margin:0;padding-left:20px;">{takeaways}</ul></div>
</td></tr>

<!-- ═══ CONNECTING THE DOTS ═══ -->
<tr><td style="padding:0 40px 20px;">
<div style="background:#fdf4ff;border:1px solid #e9d5ff;border-radius:8px;padding:20px;">
<h2 style="margin:0 0 10px;font-size:17px;color:#7e22ce;">🔗 Connecting the Dots</h2>
<p style="margin:0;font-size:13px;color:#581c87;line-height:1.7;">{connections}</p></div>
</td></tr>

<!-- ═══ WHAT TO WATCH ═══ -->
<tr><td style="padding:0 40px 24px;">
<div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:20px;">
<h2 style="margin:0 0 10px;font-size:17px;color:#9a3412;">👀 What to Watch</h2>
<ul style="margin:0;padding-left:20px;">{watch_items}</ul></div>
</td></tr>

<!-- ═══ FOOTER ═══ -->
<tr><td style="background:#f9fafb;padding:24px 40px;text-align:center;border-top:1px solid #e5e7eb;">
<p style="margin:0;font-size:11px;color:#9ca3af;">Generated by your AI Morning Briefing · Powered by Gemini &amp; RSS</p>
<p style="margin:4px 0 0;font-size:10px;color:#d1d5db;">{time_str} WIB · This is an automated digest, not financial advice.</p>
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
    msg["Subject"] = f"☀️ Morning Briefing — {now.strftime('%b %d, %Y')}"
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

    # 1 ─ Fetch news ───────────────────────────────────────────────────
    log.info("📰 Fetching finance articles...")
    finance_articles = deduplicate_articles(
        fetch_category_articles(FINANCE_FEEDS, FINANCE_KEYWORDS)
    )
    log.info("📰 Fetching crypto articles...")
    crypto_articles = deduplicate_articles(
        fetch_category_articles(CRYPTO_FEEDS, CRYPTO_KEYWORDS)
    )
    log.info("📰 Fetching Indonesian market articles...")
    indonesia_articles = deduplicate_articles(
        fetch_category_articles(INDONESIA_FEEDS, INDONESIA_KEYWORDS)
    )
    log.info("📰 Fetching tech articles...")
    tech_articles = deduplicate_articles(
        fetch_category_articles(TECH_FEEDS, TECH_KEYWORDS)
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
