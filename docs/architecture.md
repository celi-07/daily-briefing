# Architecture

Implemented against repository commit `e2358d8` (the planning document reviewed `bc28239`). The newer baseline's 07:45 WIB schedule and concurrent collection are preserved.

```text
RSS / Cryptowave public sitemap + articles / optional X recent search
    → dated, normalized Article records + SourceHealth
    → safe article enrichment
    → conservative URL / exact-title / linked-post event clusters
    → OpenAI (default) or explicitly selected Gemini structured cluster assessment
    → precise cross-language event-key merging + reassessment
    → deterministic evidence gate + importance threshold
    → per-event summary → numeric/source-ID guards → evidence audit
    → validated stories or attributed source excerpts
    → optional cited connections/watch items + separate audits
    → HTML + text templates → byte-aware continuation emails
    → verified stories only → frozen edition + durable checkpoint → Gmail SMTP
```

## Boundaries

| Module | Responsibility |
|---|---|
| `briefing.py`, `app/pipeline.py` | CLI, frozen news window, concurrent collection, orchestration and outputs |
| `app/config.py`, `config/sources.json` | Validated settings, secrets held separately, source registry |
| `app/models.py` | Strict Pydantic article, event, assessment, claim, story, quote, digest and delivery-part contracts |
| `app/http.py` | Bounded HTTP, robots policy, per-host pacing, redirect checks and DNS-pinned public-address connection backend |
| `app/sources/` | RSS parsing, official X pagination and public Cryptowave extraction; explicit coverage statuses |
| `app/enrich.py` | JSON-LD metadata, body extraction and excerpt fallback without paywall bypass |
| `app/cluster.py` | Conservative deterministic clustering; precise AI event-key consolidation retains provenance |
| `app/ai.py`, `prompts/` | Shared structured engine with OpenAI Responses and Gemini adapters, retries, budgets, cache, assessment, generation, audit and synthesis |
| `app/selection.py` | Importance/evidence rules, stable ordering and attributed extractive fallbacks |
| `app/market.py` | Existing yfinance tickers with units, timestamps, stale flags and nullable change |
| `app/render.py`, `templates/` | Autoescaped table-based HTML, equivalent text and lossless story partitioning |
| `app/delivery.py`, `scripts/checkpoint/` | Frozen editions, state transitions, TLS SMTP and immediate remote checkpoint persistence |
| `scripts/restore_state.cjs` | Trusted same-day default-branch Actions artifact restoration; fail closed on incomplete restoration |
| `app/testing.py`, `tests/fixtures/` | Explicit offline sample mode; no production AI or email impersonation |

## Policy and failure behavior

- Every adequately evidenced event scoring at least 70/100 is included. Weights: impact .40, relevance .25, novelty .20, urgency .15, each scored 0–5. There is no maximum per topic; an empty section is honest.
- Source text remains untrusted data. Importance is an editorial judgment. Schema/ID/numeric checks are deterministic; semantic claim audits use the selected AI provider and retain their limitations.
- Title-only evidence does not justify detailed analysis. A configured primary source can evidence its own announcement. High-risk third-party claims need independent original reporting; reprints and linked copies do not count twice.
- Failed summaries and assessments remain in JSON diagnostics, with safe reasons and no invented scores. Reader HTML/text omit them. Partial failure allows verified stories to be delivered. With no verified stories from collected candidates, delivery is withheld. Frozen pending payloads containing failed-analysis stories cannot be sent; confirmed parts remain skipped.
- Numeric facts and dates must be present in the cited evidence; source URLs come from the registry. Conditional analysis must not invent causation. Connections/watch items require source-backed stories and another audit.
- Collection/AI budgets are coverage limits, never hidden story caps. Unknown/future dates are quarantined. Syndication detection, cross-language identity and judgment require calibration on actual output.
- Assessment shares a configurable fraction (default .8) of request/token/time allowances across initial batches, retries and merged-event reassessment. Exhausting this allowance preserves the remaining budget for summaries/audits; overall limits remain authoritative. Explicit provider rejections refund reserved tokens; uncertain remote outcomes keep conservative estimates. Temporary provider failures do not disable later events or trigger recursive batch splitting. Invalid/truncated responses, evidence-ID errors and oversized token reservations may split assessment batches. A configured fallback within the chosen provider receives temporary primary-model failures promptly, with bounded retries on the final model and no hidden HTTP retries. OpenAI requires all schema properties, including Pydantic defaults; local validation and evidence auditing still apply. OpenAI billing/quota exhaustion immediately hands the request to Gemini and skips OpenAI for the remainder of the run. Missing OpenAI credentials select Gemini before collection; both providers share total job caps.
- Publication times use aware UTC records; presentation uses the configured timezone. Market observations retain their actual dates and comparison periods.
- Header/footer content is reserved during partitioning; story boundaries remain intact. Huge single-story/header failures are explicit rather than truncated. Browser viewport checks do not replace email-client verification.

## Delivery state

The edition key is Jakarta date plus recipient hash; payloads are frozen on preparation. Every part has a content hash and `pending`, `sending`, `sent` or `uncertain` status. Preparation and every transition are atomic locally. In production Actions, each transition is uploaded remotely before proceeding; older current-run checkpoints are deleted only after replacement upload succeeds.

SMTP connects/authenticates, checkpoints `sending`, submits the message, then checkpoints `sent`. A missing acceptance response leaves `uncertain`; interrupted `sending` is also uncertain. Retrying it requires explicit acknowledgement after mailbox inspection. Confirmed parts are never automatically resent. Checkpoint errors stop delivery. This provides conservative recovery, not an exactly-once SMTP guarantee.

The workflow restores only matching-date artifacts from scheduled/manual executions of the delivery workflow on the default branch. PR test artifacts cannot become production delivery state. Recovery freezes news content instead of regenerating different part boundaries during retries. Artifacts are access-controlled by GitHub and retained for seven days; they contain news content and delivery metadata but no credentials.

Restoration logs the frozen window end, confirmed part count and AI-verified story count, and saves the original previews for inspection. Manual `preview_only` skips restoration and calls `--dry-run`, which ignores local delivery state, generates fresh output and never sends email. A separate bounded diagnostic uses one dated BBC RSS article to exercise assessment, generation and audit through the real engine, saving previews without market or delivery access.

The Python runtime remains 3.10. Node 24 is required only for the official artifact SDK in Actions; no service/database/hosting system is introduced. X requires separate API access and configured queries. Gemini Search grounding and a persistent news-history database remain optional future additions, outside this change.
