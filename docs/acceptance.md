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

The previous full-preview measurements show that unassessed output was primarily an assessment-capacity problem, in addition to provider availability. Defaults now start with the previously successful Flash-Lite model. Assessment input is limited to 3,000 characters per article, with explicit truncation metadata and concise fact/reason instructions. Summary generation and auditing retain the 10,000-character evidence limit. Token-preflight failures split oversized batches before calling the provider; smaller assessment batches receive correspondingly smaller provider output caps and token reservations (2,048 for one event rather than 8,192 for every request); exhausted request/time budgets do not trigger splitting.

Local validation: **87 Python tests passed** on Python 3.12.0rc3; Node 24.19.0 checkpoint upload-order/trusted-restore checks passed; the offline 15-story CLI preview generated HTML, text and JSON successfully. New regressions cover bounded assessment evidence without losing summary/audit evidence, a deterministic 120-long-article capacity simulation under unchanged budgets, preflight batch splitting, safe per-event failure reasons, rendered/JSON coverage totals, reserved summary capacity and distinguishing summary budget failures from evidence rejection. The simulated token charges are not a live tokenizer or editorial-quality benchmark.

## October 9 OpenAI provider switch and delivery requirement

The [post-merge main run](https://github.com/celi-07/daily-briefing/actions/runs/37916024222) restored the frozen 06:44 UTC edition: all three parts already confirmed, nine verified analyses out of 118 retained stories, and 109 unassessed excerpts. Its log explicitly records no fresh collection or AI generation. That explains why rerunning after the earlier merge still displayed old unavailable-analysis labels.

The default provider is now OpenAI Responses with `gpt-5.6-terra`, strict schemas, `store=false`, and `reasoning.effort=none`. Existing overall caps are unchanged. The Gemini adapter remains explicitly selectable, with no automatic return to Gemini. Missing provider credentials fail before collection. Fresh live previews and email delivery require all collected events to be assessed and all retained stories to have verified analysis; diagnostic excerpts remain inspectable but cannot be sent. Pending restored editions meet the same requirement, while already confirmed parts remain skipped. Restored HTML/text previews carry a saved-edition banner and coverage JSON records generation provenance.

Validation: **105 Python tests passed** locally on Python 3.12.0rc3. The 18 additional cases cover the actual OpenAI HTTP request and all four strict schemas using an offline endpoint, all production AI stages, refusal/truncation handling and usage accounting, bounded transient retries, terminal auth/billing failures without private provider text in logs, missing-key preflight, quiet-day assessment, and SMTP blocking for both fresh and restored incomplete digests. The offline synthetic CLI fixture still retains all 15 stories. These mock results verify code contracts and delivery behavior, not live model availability or factual accuracy.

Live OpenAI inference is not yet verified: the repository has no `OPENAI_API_KEY` Actions secret, and no local key is set. The fresh local no-send command correctly stops before collection with that explicit configuration error. Add the secret and run a branch `preview_only=true` acceptance preview before making the PR ready. ChatGPT-plan OAuth is a separate integration and is not implemented or inferred from this Codex login.

After GitHub sign-in became available, the [October 9 delivered preview](https://github.com/celi-07/daily-briefing/actions/runs/37895097102) was inspected: 343 final events, 234 assessed, nine verified analyses, and 109 unassessed excerpts. Its only AI failure notice identifies the reserved assessment allowance. A [fresh branch preview](https://github.com/celi-07/daily-briefing/actions/runs/37912952449) was dispatched with `preview_only=true`, using the existing Actions secret without email or delivery-state access; it completed successfully with 337 events, 261 assessed, two verified analyses and 76 unassessed events. Every retained story was present in HTML and text, with no duplicate story IDs. This first trial confirmed that shorter input alone was insufficient. The final defaults rebalance the existing 400,000-token / 120-request / 1,200-second total allowances to 80% assessment and 20% summaries/audits; the former 40% reservation was largely unused. The final split has a 337-event simulated-capacity regression. The [final live no-send preview](https://github.com/celi-07/daily-briefing/actions/runs/37914235282) at code commit `1c6341f` assessed **all 331 final events**, selected seven, and generated seven evidence-checked analyses: four finance, two crypto and one technology. There were **zero unassessed events and zero source-excerpt summary fallbacks**. All seven story IDs are unique and appear in both HTML and plain text, in one email part. It used 78 attempts and 336,753 accounted tokens within the existing 120-request / 400,000-token / 1,200-second total caps. Later quota/rate and service errors affected optional synthesis; no connections/watch notes were published. No SMTP or delivery-state access occurred. The earlier production and later preview use different rolling collection windows, so these are operational recovery measurements rather than a controlled editorial-quality comparison. Shorter assessment excerpts may omit relevant details; configure `ASSESSMENT_EVIDENCE_CHARS` upward if editorial review shows that tradeoff is unacceptable. Provider quotas and overall request/token/time caps can still leave coverage incomplete. Email headers and `coverage.json` now expose that explicitly.
