"""Bounded schema or one-article AI checks; never connect to email delivery."""
import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google import genai
from google.genai import types
from app.ai import GeminiEngine
from app.cluster import cluster_articles
from app.config import Settings, Source
from app.http import Fetcher
from app.models import Assessments, Drafts, Verdicts, Synthesis, Digest
from app.pipeline import save_outputs
from app.render import render_parts
from app.selection import select, source_story
from app.sources import rss


def end_to_end(settings, *, fetcher=None, engine=None, cutoff=None):
    """Exercise real production AI stages on one article, without delivery state/SMTP."""
    cutoff = cutoff or datetime.now(timezone.utc)
    settings = settings.model_copy(update={'ai_requests': min(settings.ai_requests, 12),
        'ai_tokens': min(settings.ai_tokens, 100_000), 'ai_seconds': min(settings.ai_seconds, 240),
        'http_requests': min(settings.http_requests, 20)})
    own_fetcher, own_engine = fetcher is None, engine is None
    fetcher, engine = fetcher or Fetcher(settings), engine or GeminiEngine(settings)
    try:
        source = Source(id='bbc-business-diagnostic', name='BBC Business', kind='rss',
            url='https://feeds.bbci.co.uk/news/business/rss.xml', topics=['finance'], trust='reporter')
        start = cutoff - timedelta(hours=settings.window_hours)
        articles, health = rss.fetch(source, fetcher, start, cutoff)
        articles = [a for a in articles if a.text.strip() and a.quality != 'title-only']
        if not articles:
            raise RuntimeError('No dated BBC article with text available for the diagnostic')
        article = max(articles, key=lambda a: (a.published_at, a.id))
        registry = {article.id: article}
        event = cluster_articles([article])[0]
        notices = ['Diagnostic sample: one fresh BBC article, not a complete daily briefing.']
        engine.assess([event], registry, notices)
        story = None
        if event.assessment is not None:
            if not select([event], registry, settings.importance_threshold):
                notices.append('This article did not qualify for the normal importance/evidence policy; '
                               'summary generation is exercised only as a diagnostic.')
            story = engine.summarize(event, registry)
        verified = story is not None and story.status == 'verified-analysis'
        story = story or source_story(event, registry, unassessed=event.assessment is None)
        digest = Digest(edition_date=cutoff.astimezone(ZoneInfo(settings.timezone)).date().isoformat(),
            window_start=start, window_end=cutoff, timezone=settings.timezone, stories=[story],
            health=[health], notices=notices, decisions=[event])
        save_outputs(digest, render_parts(digest, settings.html_bytes), settings.output_dir)
        result = {'mode': 'end-to-end', 'assessed': event.assessment is not None,
            'story_status': story.status, 'requests': engine.requests, 'tokens': engine.tokens,
            'status': 'passed' if verified else 'failed', 'failure_reason': engine.failure_reason}
        print(json.dumps(result), flush=True)
        return result
    finally:
        if own_fetcher:
            fetcher.close()
        if own_engine:
            engine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['schemas', 'end-to-end'], default='schemas')
    args = parser.parse_args()
    settings = Settings.from_env()
    key = settings.gemini_api_key.get_secret_value()
    if not key:
        raise SystemExit('GEMINI_API_KEY missing')
    if args.mode == 'end-to-end':
        return 0 if end_to_end(settings)['status'] == 'passed' else 1
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60_000,
        retry_options=types.HttpRetryOptions(attempts=1)))
    probes = [(name, 'Return an empty items array as JSON.', schema) for name, schema in
              [('assessment-schema', Assessments), ('summary-schema', Drafts),
               ('verification-schema', Verdicts), ('synthesis-schema', Synthesis)]]
    failed = False
    try:
        for label, prompt, schema in probes:
            try:
                config = types.GenerateContentConfig(max_output_tokens=8192, temperature=.2,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
                if schema:
                    config.response_mime_type = 'application/json'
                    config.response_json_schema = schema.model_json_schema()
                response = client.models.generate_content(model=settings.gemini_model, contents=prompt, config=config)
                valid_output = schema.model_validate_json(response.text or '').items == []
                failed = failed or not valid_output
                print(json.dumps({'probe': label, 'model': settings.gemini_model, 'status': 'accepted',
                    'valid_output': valid_output}), flush=True)
            except Exception as exc:
                failed = True
                # Print only the provider message, not exception repr/details/headers/prompt.
                message = str(getattr(exc, 'message', '') or type(exc).__name__)
                message = message.replace(key, '[REDACTED]')
                message = re.sub(r'(?i)(key=|Bearer\s+)[^\s&]+', r'\1[REDACTED]', message)
                message = re.sub(r'AIza[\w-]+', '[REDACTED]', message)
                print(json.dumps({'probe': label, 'model': settings.gemini_model, 'status': 'rejected',
                    'http_code': getattr(exc, 'code', None), 'message': message[:1500]}), flush=True)
        return 1 if failed else 0
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
