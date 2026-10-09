# Daily Morning Briefing

An evidence-backed news digest for global finance, crypto, the Indonesian economy and technology. It collects RSS, Cryptowave articles and optional X posts, assesses importance with Gemini, and delivers a readable HTML **and plain-text** email through Gmail.

Every qualifying important event is included. There is no five-story cap and no filler on quiet days. Cross-topic duplicates appear once, with their sources retained. When AI or source access fails, the digest reports limited coverage and uses clearly attributed excerpts rather than inventing analysis.

## Run locally

Python **3.10+**. The scheduled workflow retains Python 3.10.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put your own credentials in the ignored `.env` file. Never commit them. Rotate any credentials previously exposed in chat, code or logs.

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini API key; required for AI assessment, optional for labeled source-only fallback |
| `GEMINI_MODEL` | Configurable model; default `gemini-3.5-flash-lite` (verify availability for your account) |
| `GEMINI_FALLBACK_MODEL` | Optional alternative model if the primary model fails |
| `GMAIL_ADDRESS` | Gmail sender; required for actual delivery |
| `GMAIL_APP_PASSWORD` | Gmail app password with 2-step verification; required for delivery |
| `RECIPIENT_EMAIL` | Optional; defaults to sender |
| `X_BEARER_TOKEN` | Optional separate X API credential; requires account access/credits and source queries |

```sh
python briefing.py --dry-run     # Live collection and optional Gemini, no SMTP connection
python briefing.py --preview     # Same, then open the HTML preview
python briefing.py              # Generate and send; resumes a frozen edition if already prepared
```

Outputs: `artifacts/digest.json`, `coverage.json`, `preview.html`, `preview.txt`, and numbered additional parts. The first HTML preview is also saved to the historic root `preview.html`. Dry-run/preview requires no Gmail credentials. Live previews may consume Gemini/X quota; use the offline fixture for zero network requests:

```sh
python briefing.py --fixture tests/fixtures/sample-digest.json --dry-run
```

The fixture is **synthetic content**, including seven important crypto stories; its assessments are manually labeled and its summaries are attributed excerpts. It does not simulate a verified live Gemini response.

## Sources

Edit `config/sources.json`; existing RSS feeds are preserved. Each entry declares a stable ID, source type, topic hints, trust tier and enablement. Topics are `finance`, `crypto`, `indonesia`, `tech`. Failed sources are isolated and reported. Feed publication dates must fall within the rolling window; unknown/future dates are quarantined.

**Cryptowave associated with Gabriel Rey:** enabled by default at [cryptowave.co.id](https://cryptowave.co.id/). The adapter uses public article links and the sitemap disclosed in robots.txt, reads publisher JSON-LD dates and extracts `.article-content`. It respects robots rules, including the restriction on `/?page=`; no private API, guessed feed or login scraping is used. Layout changes and retrieval budgets are reported as partial/failed coverage.

**X:** the adapter uses the [official recent-search API](https://docs.x.com/x-api/posts/search-recent-posts). It stays disabled until a token **and** verified queries are configured. Edit the X source's `queries`, for example `from:YOUR_VERIFIED_ACCOUNT`, and list vetted institution/company accounts in `primary_accounts` only if their own announcements should qualify as primary evidence. A generic account or an engagement count does not establish credibility. Unknown third-party social claims require attributable independent reporting. API access and costs are separate from Gemini; no paid access is automatically purchased. The current documented `post.fields` / `note_post` schema is the default; set `X_API_SCHEMA=tweet` only for an account requiring legacy field names.

Full-text enrichment retrieves permitted article pages and retains labeled feed excerpts when blocked or paywalled. All fetched text is treated as untrusted model input. Requests have bounded time/size/redirect budgets; both URL validation and the actual connection backend reject private/local addresses, including DNS rebinding.

## AI and importance policy

The pipeline normalizes and clusters evidence, then assesses every collected event in bounded batches. Precise English event identities allow Indonesian/English copies to merge; merged evidence is reassessed. Fixed top-N context slices and category-embedding ranking have been removed.

Gemini produces schema-constrained records, with Python validation for IDs, source membership and numeric claims. Each eligible summary receives a separate evidence audit, including the headline and interpretation. Failed drafts are retried once per event, then replaced by source excerpts. Optional connections/watch items are generated only from verified summaries, cite supporting stories and receive their own evidence audit. Unsupported future dates and generic forecasts are omitted. No model-generated HTML or URLs are accepted.

The initial importance rubric is impact 40%, relevance 25%, novelty 20%, urgency 15%; each component is 0–5, converted to 0–100. The default threshold is **70**. This is an editorial score, not a probability. Evidence eligibility is separate: credible reporting or a configured primary source's own statement with adequate text; disputed/high-risk third-party claims need independent corroboration. Calibrate the threshold against actual editorial preferences.

All qualifying stories are sorted by importance and recency without a count limit. Failed assessments become **unassessed source excerpts with no invented score**, rather than silently disappearing or being labeled important. Coverage applies to collected evidence, not the entire internet. AI verification reduces unsupported output but is not a guarantee that every publisher claim is true.

Useful `.env` settings (defaults in `.env.example`): `IMPORTANCE_THRESHOLD`, `WINDOW_HOURS`, `TIMEZONE`, `LANGUAGE`, `ENRICHMENT`, `HTTP_REQUESTS`, `HTTP_TIMEOUT`, `SOURCE_PAGES`, `AI_REQUESTS`, `AI_TOKENS`, `AI_SECONDS`, `AI_BATCH_SIZE`, `AI_ASSESSMENT_FRACTION`, `ASSESSMENT_EVIDENCE_CHARS`, `EVIDENCE_CHARS`, `HTML_BYTES`. Assessment receives 60% of the shared request/token/time allowances by default, including retries and merged-event reassessment; the remaining budget can generate summaries and audits. Checks run before each attempt, so an in-flight call can overrun a time allowance or token estimate. Unassessed events retain explicit coverage notices and excerpts. Overall limits still apply; this reservation does not guarantee every event receives AI analysis.

## Email and delivery

Fluid 640px editorial layout, presentation tables, inline essential CSS, readable type, descriptive source links and a real plain-text alternative. Markets use stacked rows with currency/unit and observation time; unknown change is not 0%. Dark mode is an enhancement, not a layout dependency.

Large digests split at story boundaries into numbered emails below the configured HTML byte budget (default 80 KiB). Every selected story appears once across parts. No web-hosted overflow is required. The safeguard is conservative; clipping thresholds vary by client. An extraordinarily large single story/footer causes an explicit render failure rather than truncation.

Local delivery freezes the edition in `.state/`, writes status before sending and after acceptance, and skips confirmed parts on rerun. The scheduled workflow persists these snapshots as GitHub Actions artifacts **before SMTP and after every confirmed part**. It restores only same-day default-branch scheduled/manual workflow checkpoints, refuses delivery when restoration/checkpointing fails, and retains artifacts for seven days. A failed runner does not erase its pre-send checkpoint. These artifacts contain briefing content and delivery metadata, not credentials; repository artifact access governs who can view them.

SMTP cannot promise exactly-once delivery. If a connection is lost during message submission, the part is marked uncertain; interrupted `sending` state is also treated as uncertain. Inspect your mailbox first, then explicitly use `--retry-uncertain` or the workflow's `retry_uncertain` input. Never delete delivery state merely to retry. Changing the recipient creates a separate delivery identity; a new day's edition can be sent normally.

## GitHub Actions

Add the existing credential names as repository Actions secrets, plus optional `X_BEARER_TOKEN`. `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `TIMEZONE`, `AI_REQUESTS`, `AI_TOKENS`, `AI_SECONDS` and `AI_ASSESSMENT_FRACTION` can be repository variables. The delivery workflow defaults to the previously live-verified `gemini-3.5-flash-lite` with `gemini-3.8-flash` as fallback (an explicit 3.8 primary keeps Flash-Lite as its default fallback); local runs use the fallback configured in `.env`. With a distinct fallback configured, a temporary primary-model failure moves directly to it; the final model gets at most three attempts with backoff. Temporary failures affect that request and allow later events to recover. Authentication, configuration and overall budget failures stop AI for the run. Keep tokens out of source configuration.

The latest repository schedule is preserved: **00:45 UTC / 07:45 WIB daily**. GitHub scheduling and generation can delay arrival; no promise of delivery before 08:00 is made. Manually run **Daily Morning Briefing** on the default branch to deliver. To check fresh live output, enable its `preview_only` input and download the `briefing-preview-*` artifact. This skips checkpoint restoration, generates new HTML/text/JSON, and sends no email. A normal same-day rerun restores frozen content, logs its original generation time and verified-story count, and resumes only unsent parts. Its success is not evidence that new AI calls succeeded. Keep saved delivery state intact. The separate **Tests** workflow on pull requests performs offline checks and saves synthetic previews without sending email or consuming AI quota.

The artifact checkpoint SDK requires Node 24, provisioned by the workflow; ordinary local usage remains Python-only. Artifact runtime credentials are masked and exported only within the delivery job. Production checkpoints require GitHub-hosted Actions; a normal local run uses `.state/` without remote artifact uploading.

### Diagnose Gemini without sending email

Run **Gemini Diagnostics** manually using the existing Actions secret. Choose `schemas` for four small response-schema probes, or `end-to-end` to assess, summarize and audit one fresh BBC RSS article through the production AI code. The latter passes only when the resulting story is `verified-analysis`; its preview is saved as a `gemini-diagnostics-*` artifact. A sample below the normal importance threshold can be summarized solely to exercise the diagnostic and is labeled accordingly. Choose `configured` in end-to-end mode to exercise the production model/fallback pair, or `gemini-3.5-flash-lite` to test that model alone. Schema probes call the selected primary model directly. Neither mode accesses Gmail or changes delivery state; only the end-to-end mode collects news. Both may consume Gemini quota. Local equivalents: `python scripts/diagnose_gemini.py --mode schemas` and `python scripts/diagnose_gemini.py --mode end-to-end` with credentials set in the environment.

Assessment failures report the total affected event count and a safe failure category, distinguishing API rejection, authentication, quota, timeout, malformed output and budget exhaustion. HTTP 400 means the provider rejected a request before assessment; it does not mean every summary failed the evidence audit. Strict Pydantic records are sent through `response_json_schema`, preserving `additionalProperties: false` without converting it into the unsupported legacy `additional_properties` field.

## Verification

```sh
pip install -r requirements-dev.txt
python -m pytest -q
npm ci --prefix scripts/checkpoint --ignore-scripts
node scripts/checkpoint/test.cjs
```

[Architecture](docs/architecture.md) describes module boundaries. [Acceptance report](docs/acceptance.md) records measured checks, source-access limitations and email clients still requiring real-client verification.

### Why an edition can contain mostly excerpts

The October 7 full-preview report recorded 263 assessed events out of 365, with 102 unassessed excerpts after the assessment allowance ran out. Twelve stories had verified AI analysis. A successful delivery job means the email was processed; it does not mean all articles received AI analysis. A same-day rerun can also restore a frozen edition without making any new AI calls.

Assessment now uses at most `ASSESSMENT_EVIDENCE_CHARS=3000` characters per article, bounded by `EVIDENCE_CHARS`. The truncation flag is supplied to the model, and short evidence cannot justify invented facts. Eligible summaries and their evidence audits still receive up to `EVIDENCE_CHARS=10000` characters per article. Facts/reasons are concise to reduce output costs. Batches that do not fit the remaining token allowance split before a provider call; request/time limits and the summary/audit reservation remain enforced. No model switch or higher paid quota is required to benefit from the reduced assessment input. This does not guarantee complete coverage on every source volume or provider outage.

Every email part now reports assessed/total events, verified stories, summary fallbacks and unassessed events. Each unassessed excerpt carries its actual safe failure reason; `coverage.json` includes machine-readable AI counts and grouped failures. These are distinct from below-threshold stories, which are assessed and intentionally excluded. Inspect a fresh `preview_only` run after merging, and check existing repository variables if they override the model defaults.

ChatGPT account use is not enabled by being signed into Codex. [Sign in with ChatGPT](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt) requires a separate app registration/sign-in and granted plan-usage scope; this GitHub Actions job has no such connection. The code does not reuse desktop session tokens. This change repairs the existing Gemini integration rather than claiming an unconfigured ChatGPT fallback is active.
