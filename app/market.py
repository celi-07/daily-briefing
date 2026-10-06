import logging
import math
from datetime import datetime, timezone

from app.models import MarketQuote

log = logging.getLogger(__name__)
TICKERS = {
    "^GSPC": ("S&P 500", "points"), "^IXIC": ("NASDAQ", "points"), "^DJI": ("Dow Jones", "points"),
    "BTC-USD": ("Bitcoin", "USD"), "ETH-USD": ("Ethereum", "USD"), "GC=F": ("Gold futures", "USD/oz"),
    "CL=F": ("Crude oil futures", "USD/barrel"), "IDR=X": ("USD/IDR", "IDR per USD"),
    "^JKSE": ("IDX Composite", "points"),
}


def quote_from_history(ticker, label, unit, hist, cutoff):
    quote = MarketQuote(ticker=ticker, label=label, unit=unit, unavailable=True)
    rows = hist["Close"].dropna()
    if rows.empty:
        return quote
    observed = rows.index[-1].to_pydatetime()
    if observed.tzinfo is None:
        # Do not guess the timezone of a market observation.
        return quote
    session_date = observed.date().isoformat()
    observed = observed.astimezone(timezone.utc)
    price = float(rows.iloc[-1])
    if observed > cutoff or not math.isfinite(price):
        return quote
    change = None
    if len(rows) >= 2:
        previous = float(rows.iloc[-2])
        if previous and math.isfinite(previous):
            change = (price - previous) / previous * 100
    return quote.model_copy(update={"price": price, "change_pct": change, "observed_at": observed,
        "session_date": session_date,
        "stale": (cutoff - observed).total_seconds() > 36 * 3600, "unavailable": False})


def fetch_market_snapshot(cutoff):
    try:
        import yfinance as yf
    except ImportError:
        return [MarketQuote(ticker=t, label=label, unit=unit, unavailable=True) for t, (label, unit) in TICKERS.items()]
    quotes = []
    for ticker, (label, unit) in TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d", timeout=15)
            quotes.append(quote_from_history(ticker, label, unit, hist, cutoff))
        except Exception:
            log.warning("Market data unavailable for %s", ticker)
            quotes.append(MarketQuote(ticker=ticker, label=label, unit=unit, unavailable=True))
    return quotes
