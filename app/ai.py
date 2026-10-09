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
    def __init__(self, message, *, category="validation", splittable=False, tokens=None):
        super().__init__(message)
        self.category = category
        self.splittable = splittable
        self.tokens = tokens


def transient_failure(exc):
    if getattr(exc, "terminal", False):
        return False
    code = getattr(exc, "code", None)
    return (code in (408, 429) or isinstance(code, int) and 500 <= code < 600
            or isinstance(exc, (TimeoutError, ConnectionError, httpx.TransportError)))


def rejected_request(exc):
    # An explicit provider rejection produced no usable output. Timeouts may
    # have completed remotely, so retain their conservative token reservation.
    code = getattr(exc, "code", None)
    return isinstance(code, int) and 400 <= code < 600 and code not in (408, 504)


def provider_failure(exc, provider="Gemini"):
    """Classify provider errors without logging raw requests, details, or secrets."""
    code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", "") or "").lower()
    if re.search(r"api key (?:is )?(?:not valid|invalid|expired)|invalid api key", message):
        return f"{provider} API key invalid or expired; replace {provider.upper()}_API_KEY"
    if "api key" in message and any(word in message for word in ("blocked", "leaked")):
        return f"{provider} API key blocked; replace {provider.upper()}_API_KEY"
    if code in (401, 403):
        return f"{provider} authentication or permission failure"
    if code == 404:
        return f"Configured {provider} model or endpoint unavailable"
    if code == 429:
        return f"{provider} quota or rate limit exhausted"
    if code == 400 and any(word in message for word in ("schema", "generation_config", "generationconfig")):
        return f"{provider} rejected the structured-output schema or generation configuration (HTTP 400)"
    if code == 400:
        return ("Gemini rejected the request (HTTP 400); run Gemini Diagnostics for the provider reason"
                if provider == "Gemini" else f"{provider} rejected the request (HTTP 400); check model/configuration compatibility")
    if code in (408, 504) or isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return f"{provider} request timed out"
    if code in (500, 502, 503):
        return f"{provider} service temporarily unavailable"
    return ("Gemini request failed; run Gemini Diagnostics for details" if provider == "Gemini"
            else f"{provider} request failed")


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
    context = draft.market_context
    claims = draft.summary + (context.affected + context.watch if context else [])
    for claim in claims:
        if not set(claim.article_ids) <= allowed:
            raise AIError("Draft cites unknown article IDs")
        evidence = " ".join(registry[aid].title + " " + registry[aid].text + " " +
                            registry[aid].published_at.isoformat() for aid in claim.article_ids)
        if not numbers(claim.text) <= numbers(evidence):
            raise AIError("Draft introduces unsupported numeric values")
    evidence = " ".join(registry[aid].title + " " + registry[aid].text + " " +
                        registry[aid].published_at.isoformat() for aid in event.article_ids)
    prose = draft.headline + " " + draft.why_it_matters + " " + draft.caveat
    if context:
        prose += " " + context.mechanism + " " + context.timing + " " + context.uncertainty
    if not numbers(prose) <= numbers(evidence):
        raise AIError("Headline/analysis introduces unsupported numeric values")


class StructuredEngine:
    provider = "AI"
    model_field = ""

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

    def _generate(self, prompt, schema, model, *, max_output_tokens=8192):
        raise NotImplementedError

    @property
    def primary_model(self):
        return getattr(self.settings, self.model_field)

    def configured_models(self):
        return list(dict.fromkeys(filter(None, [self.primary_model,
            getattr(self.settings, self.model_field.replace("_model", "_fallback_model"))])))

    def provider_for_model(self, model):
        return self.provider

    def model_enabled(self, model):
        return True

    def provider_handoff(self, model, exc):
        return False

    def _account_tokens(self, amount, stage):
        self.tokens += amount
        if stage == "assess":
            self.assessment_tokens += amount

    def request(self, stage, payload, schema):
        instructions = (ROOT / "prompts" / f"{stage}.txt").read_text(encoding="utf-8")
        prompt = instructions + "\nOutput language: " + self.settings.language + "\nDATA:\n" + json.dumps(payload, ensure_ascii=False)
        key = sha256((stage + self.provider + self.primary_model + prompt).encode()).hexdigest()
        if key in self.cache:
            return self.cache[key]
        if self.unavailable:
            raise AIError(self.failure_reason or "AI unavailable for this run", category="unavailable")
        # A one-event assessment cannot need the output space of a six-event
        # batch. Scale both the actual provider cap and its budget reservation.
        output_limit = min(8192, 1024 * (len(payload) + 1)) if stage == "assess" and isinstance(payload, list) else 8192
        if stage == "summarize":
            output_limit = 4096
        elif stage == "verify":
            output_limit = 2048
        reserve = len(prompt) // 2 + output_limit
        configured_models = self.configured_models()
        preferred = self.preferred_model if self.preferred_model in configured_models else None
        models = list(dict.fromkeys(filter(None, [preferred, *configured_models])))
        transient_reason = ""
        for model in models:
            if not self.model_enabled(model):
                continue
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
                    # A large batch may not fit even though smaller batches do.
                    # Split before making a paid request, but never split once
                    # the request/time allowance or minimum token reserve is gone.
                    can_split = (isinstance(payload, list) and len(payload) > 1
                        and self.assessment_requests < max(1, int(self.settings.ai_requests * fraction))
                        and self.assessment_seconds < self.settings.ai_seconds * fraction
                        and self.assessment_tokens + 2048 < self.settings.ai_tokens * fraction)
                    raise AIError(self.failure_reason, category="assessment-budget", splittable=can_split)
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
                    text, tokens = self._generate(prompt, schema, model, max_output_tokens=output_limit)
                    if tokens is not None:
                        self._account_tokens(tokens - reserve, stage)
                    result = schema.model_validate_json(text)
                    self.cache[key] = result
                    if self.preferred_model != model:
                        if self.preferred_model is not None or model != self.primary_model:
                            log.info("%s model switched for this run: %s", self.provider, model)
                        self.preferred_model = model
                    self.failure_reason = ""
                    return result
                except (ValidationError, ValueError) as exc:
                    self.failure_reason = "Invalid structured AI response"
                    raise AIError(self.failure_reason, splittable=True) from exc
                except AIError as exc:
                    if exc.tokens is not None:
                        self._account_tokens(exc.tokens - reserve, stage)
                    if exc.category == "configuration":
                        self._account_tokens(-reserve, stage)
                        self.unavailable = True
                        self.failure_reason = str(exc)
                    raise
                except Exception as exc:
                    code = getattr(exc, "code", None)
                    if rejected_request(exc):
                        self._account_tokens(-reserve, stage)
                    handoff = self.provider_handoff(model, exc)
                    temporary = transient_failure(exc)
                    if temporary and not handoff and attempt < attempts - 1:
                        time.sleep(min(20, 2 ** attempt + random.random()))
                        continue
                    # Never log provider exception text (may include request data/API key).
                    provider = self.provider_for_model(model)
                    self.failure_reason = provider_failure(exc, provider)
                    log.warning("%s request failed (%s, status %s): %s", provider, type(exc).__name__,
                                code or "unknown", self.failure_reason)
                    if temporary:
                        transient_reason = self.failure_reason
                    if code in (401, 403) and not handoff:
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
        raise AIError(self.failure_reason or f"Configured {self.provider} models unavailable", category="provider")

    def evidence(self, events, registry, *, assessment=False):
        data = []
        for event in events:
            articles = []
            for aid in event.article_ids:
                a = registry[aid]
                limit = self.settings.evidence_chars
                if assessment:
                    limit = min(limit, self.settings.assessment_evidence_chars)
                text = a.text[:limit]
                articles.append({"id": a.id, "title": a.title, "text": text, "trust": a.trust,
                    "source": a.source_name, "source_type": a.source_type, "url": a.url,
                    "published_at": a.published_at.isoformat(), "topic_hints": a.topics,
                    "content_quality": a.quality, "evidence_truncated": len(text) < len(a.text),
                    "linked_urls": a.linked_urls})
            data.append({"event_id": event.id, "articles": articles})
        return data

    def assess_batch(self, events, registry):
        response = self.request("assess", self.evidence(events, registry, assessment=True), Assessments)
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
                    for event in items:
                        event.decision = str(exc)
        size = self.settings.ai_batch_size
        for offset in range(0, len(events), size):
            batch(events[offset:offset + size])
        for reason, count in failures.items():
            log.warning("AI assessment unavailable for %d event(s): %s", count, reason)
            notices.append(f"AI assessment unavailable for {count} event(s): {reason}; coverage incomplete.")

    def summarize(self, event, registry):
        data = self.evidence([event], registry)
        data[0]["assessment"] = event.assessment.model_dump(mode="json")
        data[0]["briefing_section"] = event.briefing_section
        data[0]["reporting_basis"] = event.reporting_basis
        data[0]["market_context_required"] = event.briefing_section == "market"
        # Retry only the failed event. A failed verification never becomes confident prose.
        for attempt in range(2):
            try:
                drafts = self.request("summarize", {"events": data, "revision_attempt": attempt}, Drafts)
                same_ids(drafts.items, [event.id])
                draft = drafts.items[0]
                if event.briefing_section == "market" and draft.market_context is None:
                    raise AIError("Market catalyst is missing evidence-backed market context")
                validate_draft(draft, event, registry)
                verdicts = self.request("verify", {"events": data, "drafts": [draft.model_dump(mode="json")]}, Verdicts)
                same_ids(verdicts.items, [event.id])
                if not verdicts.items[0].supported:
                    self.failure_reason = "Evidence audit rejected the generated draft"
                    log.warning("AI summary unavailable for event %s, attempt %d: %s",
                                event.id, attempt + 1, self.failure_reason)
                    data[0]["repair_reason"] = verdicts.items[0].reason
                    continue
                context_claims = draft.market_context.affected + draft.market_context.watch if draft.market_context else []
                cited = sorted({aid for claim in draft.summary + context_claims for aid in claim.article_ids})
                return Story(event_id=event.id, topic=event.assessment.topic,
                    secondary_topics=event.assessment.secondary_topics, headline=draft.headline,
                    summary=" ".join(claim.text for claim in draft.summary), why_it_matters=draft.why_it_matters,
                    claims=draft.summary, caveat=draft.caveat,
                    citations=[Citation(article_id=aid, source=registry[aid].source_name, url=registry[aid].url,
                                        published_at=registry[aid].published_at) for aid in cited],
                    importance=event.assessment.scores.total, status="verified-analysis",
                    briefing_section=event.briefing_section, reporting_basis=event.reporting_basis,
                    world_score=event.assessment.world_score, market_score=event.assessment.market_score,
                    regions=event.assessment.regions, themes=event.assessment.themes,
                    market_context=draft.market_context,
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


class GeminiEngine(StructuredEngine):
    provider = "Gemini"
    model_field = "gemini_model"

    def _generate(self, prompt, schema, model, *, max_output_tokens=8192):
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
                response_json_schema=schema.model_json_schema(), temperature=.2, max_output_tokens=max_output_tokens,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
        if response.candidates and str(response.candidates[0].finish_reason).endswith("MAX_TOKENS"):
            raise AIError("AI output truncated", splittable=True)
        usage = response.usage_metadata
        return response.text or "", usage.total_token_count if usage else None


def openai_schema(schema):
    """Require every property (including Pydantic defaults) in OpenAI strict mode."""
    def strict(node):
        if isinstance(node, dict):
            result = {key: strict(value) for key, value in node.items() if key != "default"}
            if result.get("type") == "object":
                result["required"] = list(result.get("properties", {}))
                result["additionalProperties"] = False
            return result
        if isinstance(node, list):
            return [strict(value) for value in node]
        return node
    return strict(schema.model_json_schema())


class ProviderHTTPError(Exception):
    def __init__(self, code, *, terminal=False):
        # Do not retain raw provider response bodies, prompts or authorization headers.
        super().__init__(f"Provider HTTP {code}")
        self.code = code
        self.terminal = terminal


class OpenAIEngine(StructuredEngine):
    provider = "OpenAI"
    model_field = "openai_model"

    def _generate(self, prompt, schema, model, *, max_output_tokens=8192):
        if self.transport:
            return self.transport(prompt, schema, model)
        key = self.settings.openai_api_key.get_secret_value().strip()
        if not key:
            raise AIError("OPENAI_API_KEY unavailable", category="configuration")
        if self.client is None:
            self.client = httpx.Client(timeout=httpx.Timeout(60, connect=15))
        response = self.client.post("https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}"}, json={
                "model": model, "input": prompt, "store": False,
                "reasoning": {"effort": self.settings.openai_reasoning_effort},
                "max_output_tokens": max_output_tokens,
                "text": {"format": {"type": "json_schema", "name": schema.__name__,
                    "strict": True, "schema": openai_schema(schema)}}})
        if response.status_code >= 400:
            terminal = False
            if response.status_code == 429:
                try:
                    terminal = response.json().get("error", {}).get("code") in (
                        "insufficient_quota", "billing_hard_limit_reached")
                except (ValueError, AttributeError):
                    pass
            raise ProviderHTTPError(response.status_code, terminal=terminal)
        body = response.json()
        tokens = (body.get("usage") or {}).get("total_tokens")
        if body.get("status") == "incomplete":
            truncated = (body.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
            raise AIError("OpenAI output truncated" if truncated else "OpenAI response incomplete",
                          splittable=truncated, tokens=tokens)
        if body.get("status") != "completed":
            raise AIError("OpenAI response did not complete", category="provider", tokens=tokens)
        contents = [content for item in body.get("output", []) if item.get("type") == "message"
                    for content in item.get("content", [])]
        if any(content.get("type") == "refusal" for content in contents):
            raise AIError("OpenAI declined this request", category="refusal", tokens=tokens)
        text = "".join(content.get("text", "") for content in contents if content.get("type") == "output_text")
        return text, tokens


class FailoverEngine(StructuredEngine):
    """Route providers within one request/token/time budget, without resetting it."""
    provider = "OpenAI/Gemini"

    def __init__(self, settings, transport=None):
        super().__init__(settings, transport)
        self.adapters = {"openai": OpenAIEngine(settings, transport), "gemini": GeminiEngine(settings, transport)}
        self.openai_disabled = False

    @property
    def primary_model(self):
        return "openai:" + self.settings.openai_model

    def configured_models(self):
        return [provider + ":" + model for provider, adapter in self.adapters.items()
                for model in adapter.configured_models() if self.model_enabled(provider + ":" + model)]

    def provider_for_model(self, model):
        return self.adapters[model.split(":", 1)[0]].provider

    def model_enabled(self, model):
        return not (self.openai_disabled and model.startswith("openai:"))

    def provider_handoff(self, model, exc):
        if model.startswith("openai:") and getattr(exc, "code", None) in (401, 403, 404, 429):
            self.openai_disabled = True
            log.info("OpenAI connection/quota unavailable; using Gemini for remaining requests")
            return True
        return False

    def _generate(self, prompt, schema, model, *, max_output_tokens=8192):
        provider, name = model.split(":", 1)
        return self.adapters[provider]._generate(prompt, schema, name, max_output_tokens=max_output_tokens)

    def close(self):
        for adapter in self.adapters.values():
            adapter.close()


def create_engine(settings, transport=None):
    openai_key = bool(settings.openai_api_key.get_secret_value().strip())
    gemini_key = bool(settings.gemini_api_key.get_secret_value().strip())
    if settings.ai_provider == "gemini" or not openai_key and gemini_key:
        engine = GeminiEngine(settings, transport)
    elif openai_key and gemini_key:
        engine = FailoverEngine(settings, transport)
    else:
        engine = OpenAIEngine(settings, transport)
    log.info("AI provider: %s; model: %s", engine.provider, engine.primary_model)
    return engine
