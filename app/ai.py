import json
import logging
import random
import re
import time
from collections import Counter
from hashlib import sha256

import httpx
from pydantic import ValidationError

from app.config import ROOT
from app.models import Assessments, Citation, Claim, Draft, Drafts, Story, Synthesis, Verdicts

log = logging.getLogger(__name__)


class AIError(RuntimeError):
    def __init__(self, message, *, category="validation", splittable=False):
        super().__init__(message)
        self.category = category
        self.splittable = splittable


def transient_failure(exc):
    code = getattr(exc, "code", None)
    return (code in (408, 429) or isinstance(code, int) and 500 <= code < 600
            or isinstance(exc, (TimeoutError, ConnectionError, httpx.TransportError)))


def rejected_request(exc):
    # An explicit provider rejection produced no usable output. Timeouts may
    # have completed remotely, so retain their conservative token reservation.
    code = getattr(exc, "code", None)
    return isinstance(code, int) and 400 <= code < 600 and code not in (408, 504)


def provider_failure(exc):
    """Classify provider errors without logging raw requests, details, or secrets."""
    code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", "") or "").lower()
    if re.search(r"api key (?:is )?(?:not valid|invalid|expired)|invalid api key", message):
        return "Gemini API key invalid or expired; replace GEMINI_API_KEY"
    if "api key" in message and any(word in message for word in ("blocked", "leaked")):
        return "Gemini API key blocked; replace GEMINI_API_KEY"
    if code in (401, 403):
        return "Gemini authentication or permission failure"
    if code == 404:
        return "Configured Gemini model or endpoint unavailable"
    if code == 429:
        return "Gemini quota or rate limit exhausted"
    if code == 400 and any(word in message for word in ("schema", "generation_config", "generationconfig")):
        return "Gemini rejected the structured-output schema or generation configuration (HTTP 400)"
    if code == 400:
        return "Gemini rejected the request (HTTP 400); run Gemini Diagnostics for the provider reason"
    if code in (408, 504) or isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "Gemini request timed out"
    if code in (500, 502, 503):
        return "Gemini service temporarily unavailable"
    return "Gemini request failed; run Gemini Diagnostics for details"


def same_ids(items, expected):
    ids = [item.event_id for item in items]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise AIError("Missing, duplicate, or unexpected AI event IDs", splittable=True)


def valid_assessments(items, events):
    same_ids(items, [event.id for event in events])
    members = {event.id: set(event.article_ids) for event in events}
    for item in items:
        if not set(item.independent_origins) <= members[item.event_id]:
            raise AIError("Unknown evidence origin IDs", splittable=True)
        if any(not set(fact.article_ids) <= members[item.event_id] for fact in item.facts):
            raise AIError("Unknown fact evidence IDs", splittable=True)


def numbers(text):
    # Require numbers to be evidenced; punctuation and currency formatting may differ.
    return {token.replace(",", "").rstrip(".") for token in re.findall(r"\d+(?:[,.]\d+)*", text)}


def validate_draft(draft, event, registry):
    allowed = set(event.article_ids)
    for claim in draft.summary:
        if not set(claim.article_ids) <= allowed:
            raise AIError("Draft cites unknown article IDs")
        evidence = " ".join(registry[aid].title + " " + registry[aid].text + " " +
                            registry[aid].published_at.isoformat() for aid in claim.article_ids)
        if not numbers(claim.text) <= numbers(evidence):
            raise AIError("Draft introduces unsupported numeric values")
    evidence = " ".join(registry[aid].title + " " + registry[aid].text for aid in event.article_ids)
    if not numbers(draft.headline + " " + draft.why_it_matters) <= numbers(evidence):
        raise AIError("Headline/analysis introduces unsupported numeric values")


class GeminiEngine:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.requests = 0
        self.tokens = 0
        self.assessment_requests = 0
        self.assessment_tokens = 0
        self.assessment_seconds = 0.0
        self.started = time.monotonic()
        self.cache = {}
        self.client = None
        self.transport = transport
        self.preferred_model = None
        self.unavailable = False
        self.failure_reason = ""

    def _generate(self, prompt, schema, model):
        if self.transport:
            return self.transport(prompt, schema, model)
        if self.client is None:
            from google import genai
            from google.genai import types
            key = self.settings.gemini_api_key.get_secret_value()
            if not key:
                raise AIError("GEMINI_API_KEY unavailable", category="configuration")
            self.client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60_000,
                retry_options=types.HttpRetryOptions(attempts=1)))
        from google.genai import types
        response = self.client.models.generate_content(model=model, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json",
                response_json_schema=schema.model_json_schema(), temperature=.2, max_output_tokens=8192,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
        if response.candidates and str(response.candidates[0].finish_reason).endswith("MAX_TOKENS"):
            raise AIError("AI output truncated", splittable=True)
        usage = response.usage_metadata
        return response.text or "", usage.total_token_count if usage else None

    def _account_tokens(self, amount, stage):
        self.tokens += amount
        if stage == "assess":
            self.assessment_tokens += amount

    def request(self, stage, payload, schema):
        instructions = (ROOT / "prompts" / f"{stage}.txt").read_text(encoding="utf-8")
        prompt = instructions + "\nOutput language: " + self.settings.language + "\nDATA:\n" + json.dumps(payload, ensure_ascii=False)
        key = sha256((stage + self.settings.gemini_model + prompt).encode()).hexdigest()
        if key in self.cache:
            return self.cache[key]
        if self.unavailable:
            raise AIError(self.failure_reason or "AI unavailable for this run", category="unavailable")
        reserve = len(prompt) // 2 + 8192
        configured_models = list(dict.fromkeys(filter(None, [self.settings.gemini_model, self.settings.gemini_fallback_model])))
        preferred = self.preferred_model if self.preferred_model in configured_models else None
        models = list(dict.fromkeys(filter(None, [preferred, *configured_models])))
        transient_reason = ""
        for model in models:
            # Give a configured alternative a turn before spending retries on
            # a temporarily unavailable primary. Only the final model retries.
            attempts = 3 if model == models[-1] else 1
            for attempt in range(attempts):
                total_exhausted = (self.requests >= self.settings.ai_requests
                    or self.tokens >= self.settings.ai_tokens
                    or time.monotonic() - self.started >= self.settings.ai_seconds)
                fraction = self.settings.ai_assessment_fraction
                if stage == "assess" and not total_exhausted and (
                        self.assessment_requests >= max(1, int(self.settings.ai_requests * fraction))
                        or self.assessment_tokens + reserve > self.settings.ai_tokens * fraction
                        or self.assessment_seconds >= self.settings.ai_seconds * fraction):
                    self.failure_reason = "AI assessment allowance exhausted; budget reserved for summaries and audits"
                    raise AIError(self.failure_reason, category="assessment-budget")
                if total_exhausted or self.tokens + reserve > self.settings.ai_tokens:
                    self.unavailable = True
                    self.failure_reason = "AI request/token/time budget exhausted"
                    raise AIError(self.failure_reason, category="budget")
                self.requests += 1
                if stage == "assess":
                    self.assessment_requests += 1
                self._account_tokens(reserve, stage)
                attempt_started = time.monotonic() if stage == "assess" else None
                try:
                    text, tokens = self._generate(prompt, schema, model)
                    if tokens is not None:
                        self._account_tokens(tokens - reserve, stage)
                    result = schema.model_validate_json(text)
                    self.cache[key] = result
                    if self.preferred_model != model:
                        if self.preferred_model is not None or model != self.settings.gemini_model:
                            log.info("Gemini model switched for this run: %s", model)
                        self.preferred_model = model
                    self.failure_reason = ""
                    return result
                except (ValidationError, ValueError) as exc:
                    self.failure_reason = "Invalid structured AI response"
                    raise AIError(self.failure_reason, splittable=True) from exc
                except AIError as exc:
                    if exc.category == "configuration":
                        self._account_tokens(-reserve, stage)
                        self.unavailable = True
                        self.failure_reason = str(exc)
                    raise
                except Exception as exc:
                    code = getattr(exc, "code", None)
                    if rejected_request(exc):
                        self._account_tokens(-reserve, stage)
                    temporary = transient_failure(exc)
                    if temporary and attempt < attempts - 1:
                        time.sleep(min(20, 2 ** attempt + random.random()))
                        continue
                    # Never log provider exception text (may include request data/API key).
                    self.failure_reason = provider_failure(exc)
                    log.warning("Gemini request failed (%s, status %s): %s", type(exc).__name__,
                                code or "unknown", self.failure_reason)
                    if temporary:
                        transient_reason = self.failure_reason
                    if code in (401, 403):
                        self.unavailable = True
                        raise AIError(self.failure_reason, category="provider") from None
                    break
                finally:
                    if attempt_started is not None:
                        self.assessment_seconds += time.monotonic() - attempt_started
        if transient_reason:
            self.failure_reason = transient_reason
            raise AIError(self.failure_reason, category="transient")
        self.unavailable = True
        raise AIError(self.failure_reason or "Configured Gemini models unavailable", category="provider")

    def evidence(self, events, registry):
        data = []
        for event in events:
            articles = []
            for aid in event.article_ids:
                a = registry[aid]
                text = a.text[:self.settings.evidence_chars]
                articles.append({"id": a.id, "title": a.title, "text": text, "trust": a.trust,
                    "source": a.source_name, "source_type": a.source_type, "url": a.url,
                    "published_at": a.published_at.isoformat(), "topic_hints": a.topics,
                    "content_quality": a.quality, "evidence_truncated": len(text) < len(a.text),
                    "linked_urls": a.linked_urls})
            data.append({"event_id": event.id, "articles": articles})
        return data

    def assess_batch(self, events, registry):
        response = self.request("assess", self.evidence(events, registry), Assessments)
        valid_assessments(response.items, events)
        by_id = {item.event_id: item for item in response.items}
        for event in events:
            event.assessment = by_id[event.id]

    def assess(self, events, registry, notices):
        failures = Counter()
        def batch(items):
            try:
                self.assess_batch(items, registry)
            except AIError as exc:
                # Malformed/truncated batches split without silently dropping the tail.
                if len(items) > 1 and exc.splittable and not self.unavailable:
                    middle = len(items) // 2
                    batch(items[:middle])
                    batch(items[middle:])
                else:
                    failures[str(exc)] += len(items)
        size = self.settings.ai_batch_size
        for offset in range(0, len(events), size):
            batch(events[offset:offset + size])
        for reason, count in failures.items():
            log.warning("AI assessment unavailable for %d event(s): %s", count, reason)
            notices.append(f"AI assessment unavailable for {count} event(s): {reason}; coverage incomplete.")

    def summarize(self, event, registry):
        data = self.evidence([event], registry)
        data[0]["assessment"] = event.assessment.model_dump(mode="json")
        # Retry only the failed event. A failed verification never becomes confident prose.
        for attempt in range(2):
            try:
                drafts = self.request("summarize", {"events": data, "revision_attempt": attempt}, Drafts)
                same_ids(drafts.items, [event.id])
                draft = drafts.items[0]
                validate_draft(draft, event, registry)
                verdicts = self.request("verify", {"events": data, "drafts": [draft.model_dump(mode="json")]}, Verdicts)
                same_ids(verdicts.items, [event.id])
                if not verdicts.items[0].supported:
                    self.failure_reason = "Evidence audit rejected the generated draft"
                    log.warning("AI summary unavailable for event %s, attempt %d: %s",
                                event.id, attempt + 1, self.failure_reason)
                    data[0]["repair_reason"] = verdicts.items[0].reason
                    continue
                cited = sorted({aid for claim in draft.summary for aid in claim.article_ids})
                return Story(event_id=event.id, topic=event.assessment.topic,
                    secondary_topics=event.assessment.secondary_topics, headline=draft.headline,
                    summary=" ".join(claim.text for claim in draft.summary), why_it_matters=draft.why_it_matters,
                    claims=draft.summary, caveat=draft.caveat,
                    citations=[Citation(article_id=aid, source=registry[aid].source_name, url=registry[aid].url,
                                        published_at=registry[aid].published_at) for aid in cited],
                    importance=event.assessment.scores.total, status="verified-analysis",
                    published_at=max(registry[aid].published_at for aid in event.article_ids))
            except AIError as exc:
                self.failure_reason = str(exc)
                log.warning("AI summary unavailable for event %s, attempt %d: %s",
                            event.id, attempt + 1, self.failure_reason)
                data[0]["repair_reason"] = self.failure_reason
                if self.unavailable:
                    break
        return None

    def synthesize(self, stories, registry):
        verified = {s.event_id: s for s in stories if s.status == "verified-analysis"}
        if len(verified) < 2 or self.unavailable:
            return []
        try:
            payload = [s.model_dump(mode="json") for s in verified.values()]
            result = self.request("synthesize", payload, Synthesis)
            accepted = []
            for index, note in enumerate(result.items):
                if not set(note.story_ids) <= set(verified) or (note.kind == "connection" and len(set(note.story_ids)) < 2):
                    continue
                ids = sorted({c.article_id for sid in note.story_ids for c in verified[sid].citations})
                evidence = " ".join(registry[aid].title + " " + registry[aid].text for aid in ids)
                if not numbers(note.text) <= numbers(evidence):
                    continue
                event_id = f"note-{index}"
                articles = [{"id": aid, "title": registry[aid].title,
                             "text": registry[aid].text[:self.settings.evidence_chars]} for aid in ids]
                draft = Draft(event_id=event_id, headline="Connecting the dots" if note.kind == "connection" else "What to watch",
                              summary=[Claim(text=note.text,article_ids=ids)], why_it_matters="")
                verdicts = self.request("verify", {"events":[{"event_id":event_id,"articles":articles}],
                                                   "drafts":[draft.model_dump(mode="json")]}, Verdicts)
                same_ids(verdicts.items, [event_id])
                if verdicts.items[0].supported:
                    accepted.append(note)
            return accepted
        except AIError:
            return []

    def close(self):
        if self.client:
            self.client.close()
