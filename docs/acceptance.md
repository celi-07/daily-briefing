# Acceptance report

6 October 2026. Implementation baseline: `e2358d8`. Tests use synthetic evidence unless explicitly identified as a read-only live check.

## Measured verification

| Check | Result |
|---|---|
| Offline Python suite | 43 tests pass on Python 3.10.20 and 3.12.14 |
| Artifact SDK | Real SDK imports under Node 24; mocked upload-before-delete and trusted-restore checks pass |
| Source checks | BBC Business: 12 dated RSS articles; Cryptowave: nine dated articles, all with extracted full text, both `ok` at check time |
| Viewport checks | Edge/Chromium at 320, 375, 768 and 1440px, both light/dark: no horizontal overflow; all 15 sample stories retained |
| Offline CLI | `--fixture ... --dry-run` saves HTML, equivalent text, digest JSON and coverage JSON; no SMTP/source/market network calls |
| Important story counts | 0, 3, 7 and 20 per topic preserved exactly; oversized output partitions without missing or duplicate event IDs |
| Citation coverage | All 15 sample stories have source citations; no duplicate story/event IDs |
| Package audit | Checkpoint package lock resolves with zero reported npm vulnerabilities at installation time |

The same saved synthetic sample was compared with the baseline's actual `_build_fallback_stories` implementation:

| Topic | Manually labeled important | Baseline fallback | New pipeline |
|---|---:|---:|---:|
| Finance | 3 | 3 | 3 |
| Crypto | 7 | 5 | 7 |
| Indonesia | 2 | 2 | 2 |
| Technology | 3 | 3 | 3 |

This demonstrates removal of the fallback cap: sample recall rises from 13/15 to 15/15. It is **not** a live AI quality benchmark. New fixture orchestration takes approximately 0.003 seconds excluding imports, collection and rendering; AI requests/tokens are zero. Live editorial accuracy remains unmeasured; the targeted October 7 diagnostic below records request and token use for one real article.

## Behavior exercised

- Below-threshold, disputed and title-only events are not padded into confirmed sections. Unknown social claims cannot pass the configured-primary-source gate.
- Exact-title copies, X links and RSS evidence retain a single event with provenance. Indonesian/English copies with the same precise event identity merge and are reassessed; distinct actions remain distinct.
- Missing/future/old dates, WIB conversion, malformed feeds, the former first-25 RSS limitation, changed Cryptowave listing markup, X pagination and missing credentials, 429 failures and request/response budgets are tested.
- Invalid/truncated structured responses split without dropping the final event; missing/duplicate/unknown IDs, invented numeric values/citations, hostile source input, authentication failures, fallback models and exhausted AI budgets have explicit failure behavior.
- Generated drafts need an evidence-audit pass. Rejected drafts fall back to source excerpts. Optional synthesis rejects unsupported schedules/source IDs and audits retained connections.
- HTML text/attributes are escaped; disallowed URL schemes, authenticated cross-host redirects, loopback/private/link-local addresses and nonpublic network connections are rejected. Fetched source instructions cannot bypass deterministic citation/numeric guards.
- One market observation has unknown change, explicit units and its own timestamp. Older observations are labeled; unknown timezones remain unavailable.
- Plain text contains the same event IDs and original links as HTML. Header/footer/synthesis space is reserved during email partitioning. Delivery state freezes part payloads; corrupt manifests, uncertain acceptance and failed remote checkpoints prevent an unprotected resend.

## Setup and remaining verification

- X is implemented and fixture-tested but not live-tested: no X credential or verified query list was supplied. Configure separate API access, bearer token and vetted account/topic queries before enabling it.
- Cryptowave public article extraction is live-verified; there is no claim of a private API/RSS integration. Publisher layout and robots policy may change.
- Chat-pasted credentials are not copied into the repository; live diagnostics below use only the existing GitHub Actions secret. The October 7 one-article check verifies generation and auditing on that sample; full-edition editorial quality still requires review.
- No actual email was sent. Gmail web/iOS/Android, Apple Mail macOS/iOS, Outlook web/mobile and classic Outlook Windows still need recipient-side rendering checks, including dark mode and clipping. Browser previews verify layout, not email-client compatibility.
- The checkpoint SDK and restoration logic are offline-tested; actual cross-run artifact persistence must be verified in GitHub Actions on the default branch. The workflow fails closed before SMTP if remote state cannot be persisted/restored.
- Importance calibration and cross-language clustering require human review on real news. Gemini evidence audits reduce unsupported output but do not guarantee factual correctness of the underlying reporting. No numerical live hallucination-rate claim is made.

Reviewable sample artifacts are produced in the CI **Tests** workflow and through `python briefing.py --fixture tests/fixtures/sample-digest.json --dry-run`.

## Gemini schema regression and diagnosis

The first production run after merge collected 322 events but made just one AI request, rejected with HTTP 400. A targeted live probe reproduced the exact failure: the SDK serialized strict Pydantic `additionalProperties: false` through the legacy response-schema field as `additional_properties`, which the API rejected. This was request rejection, not 322 failed summary audits.

The fix uses `response_json_schema=model.model_json_schema()` and retains strict local validation. Four regression cases inspect real SDK HTTP serialization without network access. Safe error categories and aggregated affected-event counts replace repeated generic batch notices. The suite now has 54 passing tests on Python 3.10 and 3.12.

[Live corrected-schema probes](https://github.com/celi-07/daily-briefing/actions/runs/37445989576) accepted and validated empty assessment and summary responses using the configured Gemini secret/model. Verification and synthesis probes received temporary HTTP 503 high-demand errors; their live success is not claimed. [Original-schema probe](https://github.com/celi-07/daily-briefing/actions/runs/37445705544) reproduced the unsupported field. No news collection, SMTP, or production delivery-state mutation occurred in these probes. The diagnostic workflow is manual-only in the final change.

## October 7 recovery and live generation

The [13:29 WIB delivery run](https://github.com/celi-07/daily-briefing/actions/runs/37581765155) used the old schema code and recorded one HTTP 400 failure for 326 events. PR #3 merged at 13:58 WIB. The [13:59 WIB rerun](https://github.com/celi-07/daily-briefing/actions/runs/37584554342) restored that day's frozen edition and made no fresh AI calls, so its unchanged excerpts did not test the schema fix.

A [fresh one-article diagnostic using gemini-3.8-flash](https://github.com/celi-07/daily-briefing/actions/runs/37588240060) failed after three requests with HTTP 503 service-unavailable errors. A [direct gemini-3.5-flash-lite diagnostic](https://github.com/celi-07/daily-briefing/actions/runs/37589249681) then passed assessment, summary generation and evidence audit on a fresh BBC article: `verified-analysis`, three requests, 2,840 reported tokens. It saved rendered previews without SMTP or delivery-state access. This confirms the key and corrected structured schemas worked for that live sample; it is not an editorial-quality benchmark or availability guarantee.

Recovery changes preserve frozen delivery content, save its original preview, and expose manual fresh-preview and end-to-end diagnostic modes. Temporary API failures no longer disable all later batches; failed requests are not recursively split. Assessment now reserves budget for summaries/audits, including merged reassessment. The workflow includes the live-verified fallback, while keeping total request/token/time caps and evidence checks.

The recovery suite has 79 passing tests on Python 3.10 and 3.12, locally and in GitHub Actions. Regression cases cover later-batch recovery, no recursive splitting on service outages, request/token/time reservations, shared merged-event allowance, refunded provider rejections, prompt fallback and persistent preference for the model that succeeds, explicit SDK HTTP attempt counts, fresh previews bypassing saved state, and restored editions retaining original parts. Checkpoint upload-order and trusted-restoration checks also pass.

The [configured production-model diagnostic](https://github.com/celi-07/daily-briefing/actions/runs/37591120784) also passed after the primary request timed out and automatically fell back: four attempts, one assessed article, a generated summary and a passing evidence audit. Conservative token accounting includes the uncertain primary request.

The [full fresh preview](https://github.com/celi-07/daily-briefing/actions/runs/37589741409) completed without checkpoint restoration or email delivery. It switched from a primary HTTP 503 to Flash-Lite, processed 365 events and assessed 263. Of 13 events selected by the importance/evidence policy, 12 produced evidence-checked summaries (eight finance, three Indonesia, one crypto); one retained a source excerpt after quota/rate and service failures. Another 102 events retained unassessed excerpts after the assessment token allowance was reached. All 115 retained story IDs are unique and present in both HTML and plain text across three parts. The run accounted for 84 attempts and 321,398 tokens/estimates. These results demonstrate fresh analysis and more than five finance stories; remaining excerpts and incomplete coverage are disclosed rather than presented as complete AI assessment.

## October 9 assessment capacity repair

The previous full-preview measurements show that unassessed output was primarily an assessment-capacity problem, in addition to provider availability. Defaults now start with the previously successful Flash-Lite model. Assessment input is limited to 3,000 characters per article, with explicit truncation metadata and concise fact/reason instructions. Summary generation and auditing retain the 10,000-character evidence limit. Token-preflight failures split oversized batches before calling the provider; exhausted request/time budgets do not trigger splitting.

Local validation: **85 Python tests passed** on Python 3.12.0rc3; Node 24.19.0 checkpoint upload-order/trusted-restore checks passed; the offline 15-story CLI preview generated HTML, text and JSON successfully. New regressions cover bounded assessment evidence without losing summary/audit evidence, a deterministic 120-long-article capacity simulation under unchanged budgets, preflight batch splitting, safe per-event failure reasons, rendered/JSON coverage totals, reserved summary capacity and distinguishing summary budget failures from evidence rejection. The simulated token charges are not a live tokenizer or editorial-quality benchmark.

This change has **not** been validated with a fresh live Gemini call: no local provider credential was available, and GitHub authentication was unavailable for dispatching a secret-backed preview or reading the October 8–9 logs/artifacts. The older live run is evidence of the failure mechanism, not a claim about every current run. Shorter assessment excerpts may omit relevant details; configure `ASSESSMENT_EVIDENCE_CHARS` upward if editorial review shows that tradeoff is unacceptable. Provider quotas and overall request/token/time caps can still leave coverage incomplete. Email headers and `coverage.json` now expose that explicitly.
