# ☀️ Daily Morning Briefing

AI-powered daily news digest covering **finance, crypto, Indonesian markets, and technology** — delivered to your inbox at 8:00 AM WIB every morning.

## What You Get

A beautifully formatted email containing:

- **📈 Market Snapshot** — S&P 500, NASDAQ, Dow, BTC, ETH, Gold, Oil, USD/IDR, IDX Composite
- **📊 Global Finance** — Major financial news with analysis
- **₿ Cryptocurrency** — Crypto market moves and regulatory developments
- **🇮🇩 Indonesian Market** — IDX, rupiah, commodities, local business
- **🚀 Technology** — Quantum computing, AI, semiconductors, big tech
- **🎯 Key Takeaways** — The 3–5 things you *must* know today
- **🔗 Connecting the Dots** — Cross-sector analysis and implications
- **👀 What to Watch** — Upcoming events and trends

## Cost

**$0/month.** Everything uses free tiers:
- GitHub Actions free tier (you'll use ~30 of 2,000 free minutes/month)
- Gemini Flash API free tier (15 RPM, more than enough)
- Gmail SMTP (your existing account)
- RSS feeds (public, free)
- Yahoo Finance data (free, no API key)

---

## Setup Guide (15 minutes)

### Step 1: Get API Keys

#### Gemini API Key (free)
1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click **"Create API Key"**
4. Copy the key

#### Gmail App Password
1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Make sure **2-Step Verification** is turned ON
3. Go to [App Passwords](https://myaccount.google.com/apppasswords)
4. Select app: **Mail**, select device: **Other** → name it "Morning Briefing"
5. Copy the 16-character password

### Step 2: Create GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Name it `morning-briefing` (private recommended)
3. Push this project:

```bash
cd daily-briefing
git init
git add .
git commit -m "Initial commit: morning briefing"
git remote add origin https://github.com/YOUR_USERNAME/morning-briefing.git
git branch -M main
git push -u origin main
```

### Step 3: Add Secrets to GitHub

1. In your GitHub repo, go to **Settings → Secrets and variables → Actions**
2. Click **"New repository secret"** and add these:

| Secret Name         | Value                           |
|---------------------|---------------------------------|
| `GEMINI_API_KEY`    | Your Gemini API key             |
| `GMAIL_ADDRESS`     | Your Gmail address              |
| `GMAIL_APP_PASSWORD`| Your 16-char app password       |
| `RECIPIENT_EMAIL`   | *(Optional)* Different recipient|

### Step 4: Done! 🎉

The workflow will automatically run at **8:00 AM WIB** every day.

To test immediately:
1. Go to your repo → **Actions** tab
2. Click **"Daily Morning Briefing"** on the left
3. Click **"Run workflow"** → **"Run workflow"**

---

## Local Development

### Test locally before deploying:

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment
copy .env.example .env
# Edit .env with your actual keys

# 4. Preview in browser (no email sent)
python briefing.py --preview

# 5. Dry run (saves HTML, no email)
python briefing.py --dry-run

# 6. Full run (sends email)
python briefing.py
```

---

## Customization

### Add/remove news sources
Edit the feed dictionaries at the top of `briefing.py`:
```python
FINANCE_FEEDS = {
    "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
    # Add more RSS feeds here...
}
```

### Change market tickers
Edit `MARKET_TICKERS` in `briefing.py`:
```python
MARKET_TICKERS = {
    "S&P 500": "^GSPC",
    "Your Stock": "TICKER",
    # ...
}
```

### Change schedule
Edit the cron in `.github/workflows/daily-briefing.yml`:
```yaml
schedule:
  - cron: '0 1 * * *'    # 8am WIB (UTC+7)
  - cron: '0 1 * * 1-5'  # Weekdays only
  - cron: '0 23 * * *'   # 6am WIB
```

### Change timezone
Edit `LOCAL_TZ` in `briefing.py`:
```python
LOCAL_TZ = timezone(timedelta(hours=7))  # UTC+7 (WIB)
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No email received | Check GitHub Actions logs; verify secrets are set correctly |
| Gmail authentication error | Make sure 2FA is on, use App Password (not regular password) |
| Empty news sections | Some RSS feeds may be down; check feed URLs |
| Market data missing | `yfinance` may be rate-limited; data appears next run |
| JSON parse error | Gemini returned invalid JSON; the fallback template will be used |

## License

MIT — use it however you want.
