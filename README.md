# Daily Morning Briefing

A daily briefing for world developments and market catalysts across global finance, crypto, the Indonesian economy and technology. It collects RSS, Cryptowave articles and optional X posts, assesses importance with OpenAI, and delivers a readable HTML **and plain-text** email through Gmail.

Every qualifying event with verified AI analysis is included. There is no five-story cap and no filler on quiet days. Cross-topic duplicates appear once, with their sources retained. Failed assessments and summaries are omitted from emails and live previews; JSON diagnostics retain omitted evidence and safe failure reasons. Partial failure does not block verified stories. If collected stories exist but none have verified analysis, email is withheld.

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
| `AI_PROVIDER` | OpenAI preferred by default with Gemini fallback; `gemini` selects Gemini directly |
| `OPENAI_API_KEY` | Optional Actions secret or local credential; missing key selects available Gemini |
| `OPENAI_MODEL` | Default `gpt-5.6-terra`; uses the Responses API with strict JSON output |
| `OPENAI_REASONING_EFFORT` | Default `none` to keep structured screening within the output/time budget |
| `OPENAI_FALLBACK_MODEL` | Optional alternative OpenAI model; exhausted quota skips further OpenAI attempts |
| `GEMINI_API_KEY` | Used when OpenAI is missing, unavailable or exhausted, or Gemini is explicitly selected |
| `GEMINI_MODEL` | Configurable model; default `gemini-3.5-flash-lite` (verify availability for your account) |
| `GEMINI_FALLBACK_MODEL` | Optional alternative model if the primary model fails |
| `GMAIL_ADDRESS` | Gmail sender; required for actual delivery |
| `GMAIL_APP_PASSWORD` | Gmail app password with 2-step verification; required for delivery |
| `RECIPIENT_EMAIL` | Optional; defaults to sender |
| `X_BEARER_TOKEN` | Optional separate X API credential; requires account access/credits and source queries |

```sh
python briefing.py --dry-run     # Fresh collection and configured AI, no SMTP connection
python briefing.py --preview     # Same, then open the HTML preview
python briefing.py              # Generate and send; resumes a frozen edition if already prepared
```

Outputs: `artifacts/digest.json`, `coverage.json`, `preview.html`, `preview.txt`, and numbered additional parts. The first complete HTML preview is also saved to the historic root `preview.html`. Dry-run/preview requires no Gmail credentials, but fresh live generation requires the selected AI provider's key. Live previews may consume OpenAI/Gemini/X quota; use the offline fixture for zero network requests:

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

The selected AI provider produces schema-constrained records with local ID, numeric and source validation. OpenAI uses Responses with strict JSON output and store=false. Each eligible summary receives a separate evidence audit. Failed drafts are retried once per event, then retained only in JSON diagnostics. OpenAI/Gemini failover shares one request/token/time allowance and cache: switching providers never resets total caps. Optional connections/watch items require verified stories and another evidence audit. No model-generated HTML or URLs are accepted.

Fresh assessments independently score **world significance** and **market relevance** from 0–5. `WORLD_THRESHOLD=3` and `MARKET_THRESHOLD=3` select a story when either purpose qualifies. Low immediate urgency does not suppress a meaningful AI/chip development. Material breaches, bankruptcies, asset theft, restrictions, cancelled IPOs and other company/policy catalysts are evaluated for market relevance. These are editorial judgments, not probabilities or trading signals. Legacy saved assessments retain the weighted importance score and `IMPORTANCE_THRESHOLD=70` for compatibility.

Evidence eligibility is separate. Supported reporting and usable limited excerpts with attributable facts can reach summary generation; title-only, disputed, unverified and unknown-source social claims remain excluded. A high-risk flag requires careful attribution and auditing rather than automatically rejecting one publisher's report. The email distinguishes a publisher report, a configured primary organization's own statement and multiple independent reports. Reprints do not become independent corroboration. Company confirmation reported by a publisher remains attributed reporting.

The email has **World developments** and **Market catalysts** sections. A story serving both purposes appears once in Market catalysts with both scores and geography/theme labels. Market stories include cited companies/assets/sectors, conditional implications, evidence-based timing, concrete follow-ups and uncertainty. All context is included in the evidence audit and numeric/citation guards. Invented tickers, beneficiaries, deadlines, price targets and priced-in assertions are rejected; missing context prevents a market story from being published. Prices remain latest available daily observations, and whether a catalyst is reflected in prices is not assessed.

Dedicated feeds add China technology (SCMP Technology), semiconductor industry reporting (Semiconductor Engineering), and primary NVIDIA/Google AI announcements alongside existing general technology sources. These improve collection coverage; they do not guarantee comprehensive China/US coverage or a minimum daily story count. Sources without dated evidence remain quarantined. The unconstrained TechNode feed was checked but not added because it exceeded the existing per-response download cap.

Summary attempts alternate between the strongest world and market candidates so one purpose does not monopolize remaining AI budget. Summary and audit output caps are 4,096 and 2,048 tokens respectively; overall request/token/time limits and shared provider fallback remain unchanged. When budget or auditing omits a candidate, full selection/failure reasons remain in diagnostic JSON and source-only stories stay hidden.

Verified stories are sorted by importance and recency without a count limit. Failed assessments remain unassessed source excerpts with no invented score in JSON diagnostics and are hidden from reader output. Coverage applies to collected evidence, not the entire internet. Evidence checking is not a guarantee that every publisher claim is true.

Useful `.env` settings (defaults in `.env.example`): `IMPORTANCE_THRESHOLD`, `WINDOW_HOURS`, `TIMEZONE`, `LANGUAGE`, `ENRICHMENT`, `HTTP_REQUESTS`, `HTTP_TIMEOUT`, `SOURCE_PAGES`, `AI_REQUESTS`, `AI_TOKENS`, `AI_SECONDS`, `AI_BATCH_SIZE`, `AI_ASSESSMENT_FRACTION`, `ASSESSMENT_EVIDENCE_CHARS`, `EVIDENCE_CHARS`, `HTML_BYTES`. Assessment receives 80% of the shared request/token/time allowances by default, including retries and merged-event reassessment; the remaining budget can generate summaries and audits. Checks run before each attempt, so an in-flight call can overrun a time allowance or token estimate. Unassessed events retain explicit coverage notices and excerpts in JSON diagnostics only. Overall limits still apply; this reservation does not guarantee every event receives AI analysis.

## Email and delivery

Fluid 640px editorial layout, presentation tables, inline essential CSS, readable type, descriptive source links and a real plain-text alternative. Markets use stacked rows with currency/unit and observation time; unknown change is not 0%. Dark mode is an enhancement, not a layout dependency.

Large digests split at story boundaries into numbered emails below the configured HTML byte budget (default 80 KiB). Every selected story appears once across parts. No web-hosted overflow is required. The safeguard is conservative; clipping thresholds vary by client. An extraordinarily large single story/footer causes an explicit render failure rather than truncation.

Local delivery freezes the edition in `.state/`, writes status before sending and after acceptance, and skips confirmed parts on rerun. The scheduled workflow persists these snapshots as GitHub Actions artifacts **before SMTP and after every confirmed part**. It restores only same-day default-branch scheduled/manual workflow checkpoints, refuses delivery when restoration/checkpointing fails, and retains artifacts for seven days. A failed runner does not erase its pre-send checkpoint. These artifacts contain briefing content and delivery metadata, not credentials; repository artifact access governs who can view them.

SMTP cannot promise exactly-once delivery. If a connection is lost during message submission, the part is marked uncertain; interrupted `sending` state is also treated as uncertain. Inspect your mailbox first, then explicitly use `--retry-uncertain` or the workflow's `retry_uncertain` input. Never delete delivery state merely to retry. Changing the recipient creates a separate delivery identity; a new day's edition can be sent normally.

## GitHub Actions

Configure either OPENAI_API_KEY or GEMINI_API_KEY as repository Actions secrets along with Gmail credentials. The workflow prefers OpenAI and gpt-5.6-terra. Missing OpenAI credentials select Gemini directly. With both keys present, OpenAI quota/rate limits (HTTP 429), invalid credentials or an unavailable model hand the same request to Gemini and disable OpenAI for the remaining run. Other failures try configured alternatives with bounded retries. Model, reasoning and budget settings remain repository variables. Both providers share the unchanged total job budget. Set AI_PROVIDER=gemini to select Gemini directly.

The schedule remains 00:45 UTC / 07:45 WIB daily. Use Daily Morning Briefing with preview_only=true for fresh no-email output. HTML/text show only verified stories; digest.json and coverage.json retain full diagnostics. A preview may succeed with partial coverage: inspect JSON counts, not just workflow success. Same-day reruns preserve frozen delivery state and skip confirmed parts. Pending old payloads containing failed-analysis stories cannot be sent. Restored previews are filtered without changing frozen payloads and carry a saved-edition banner with fresh_ai_run=false. Keep saved state intact. The Tests workflow runs offline checks and synthetic previews without sending email or consuming AI quota.

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

Assessment now uses at most `ASSESSMENT_EVIDENCE_CHARS=3000` characters per article, bounded by `EVIDENCE_CHARS`. The truncation flag is supplied to the model, and short evidence cannot justify invented facts. Eligible summaries and their evidence audits still receive up to `EVIDENCE_CHARS=10000` characters per article. Facts/reasons are concise to reduce output costs. Batches that do not fit the remaining token allowance split before a provider call; smaller batches also have smaller output caps and matching reservations (2,048 for one event, up to 8,192 for large batches); request/time limits and the summary/audit reservation remain enforced. No model switch or higher paid quota is required to benefit from the reduced assessment input. This does not guarantee complete coverage on every source volume or provider outage.

Every email part shows the verified-story count. Failed AI stories and per-story failure messages are omitted. Full assessment counts, source excerpts and grouped failures remain in coverage.json and digest.json for diagnostics.

The scheduled job now uses OpenAI through an explicitly configured API key. A ChatGPT login in Codex is not an API credential for this repository. [Sign in with ChatGPT](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt) is a separate app integration with its own registration, sign-in and plan-usage permission; this GitHub Actions job has no such connection. This implementation does not reuse desktop session tokens or claim that API billing is included in the ChatGPT subscription. See the [official OpenAI structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs) and [configured model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-terra).

Assessment candidates are interleaved by source, newest first within each source, before AI screening. This prevents a high-volume routine-price feed or network completion order from leaving dedicated technology sources at the tail of the assessment budget. The ordering is deterministic and preserves every event; it is not a per-source article cap. A bounded-budget regression verifies a late technology feed still gets assessed.
