import argparse
import html
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from app.ai import create_engine
from app.cluster import cluster_articles, merge_assessed_events
from app.config import ROOT, Settings
from app.delivery import load_state, prepare_state, send_state, state_path, validate_digest_for_delivery
from app.enrich import enrich
from app.http import Fetcher
from app.market import fetch_market_snapshot
from app.models import Article, Digest, RenderedPart, SourceHealth
from app.render import ai_coverage, render_parts
from app.selection import select, sort_stories, source_story
from app.sources import cryptowave, rss, x

log = logging.getLogger(__name__)
ADAPTERS = {"rss": rss.fetch, "x": x.fetch, "cryptowave": cryptowave.fetch}


def collect(settings, fetcher, start, end):
    articles, health = [], []
    sources = settings.sources()
    with ThreadPoolExecutor(max_workers=settings.workers) as executor:
        futures = {}
        for source in sources:
            if not source.enabled:
                health.append(SourceHealth(source_id=source.id, name=source.name, topics=source.topics,
                    status="disabled", detail="Disabled in source configuration."))
            else:
                futures[executor.submit(ADAPTERS[source.kind], source, fetcher, start, end)] = source
        for future in as_completed(futures):
            source = futures[future]
            try:
                found, status = future.result()
                articles.extend(found)
            except Exception as exc:
                log.warning("Source %s failed (%s)", source.id, type(exc).__name__)
                status = SourceHealth(source_id=source.id, name=source.name, topics=source.topics,
                    status="failed", detail="Source access, parsing, or collection-budget failure.")
            health.append(status)
    registry = {}
    for article in articles:
        if article.id in registry:
            existing = registry[article.id]
            existing.topics = sorted(set(existing.topics + article.topics))
            if len(article.text) > len(existing.text):
                existing.text = article.text
        else:
            registry[article.id] = article
    if settings.enrichment:
        with ThreadPoolExecutor(max_workers=settings.workers) as executor:
            registry = {article.id: article for article in executor.map(lambda a: enrich(a, fetcher), registry.values())}
    return registry, sorted(health, key=lambda h: h.source_id)


def build_digest(settings, registry, health, cutoff, quotes=None, engine=None):
    start = cutoff - timedelta(hours=settings.window_hours)
    notices = []
    if not registry:
        if health and any(h.status in ("ok", "partial") for h in health):
            notices.append("No dated articles available in the selected news window; coverage may be limited.")
        else:
            notices.append("News collection unavailable. This is a data-status briefing, not a quiet-market assessment.")
    if any(a.warnings or len(a.text) > settings.evidence_chars for a in registry.values()):
        notices.append("Some articles provide limited evidence. Original source links show the available context.")
    events = cluster_articles(list(registry.values()))
    owned_engine = engine is None
    engine = engine or create_engine(settings)
    try:
        engine.assess(events, registry, notices)
        unchanged, merged = merge_assessed_events(events)
        if merged:
            engine.assess(merged, registry, notices)
        events = unchanged + merged
        chosen = select(events, registry, settings.importance_threshold)
        stories = []
        for event in chosen:
            story = engine.summarize(event, registry)
            if story is None:
                notices.append("Some qualifying stories were omitted because AI analysis could not be verified.")
                story = source_story(event, registry, failure_reason=getattr(engine, "failure_reason", ""))
            stories.append(story)
        # Keep failure details in the diagnostic digest; render only verified stories.
        for event in events:
            if event.assessment is None and any(registry[aid].trust in ("primary", "reporter") for aid in event.article_ids):
                stories.append(source_story(event, registry, unassessed=True))
        stories = sort_stories(stories)
        eligible_ids = [s.event_id for s in stories if s.status == "verified-analysis"]
        notes = engine.synthesize(stories, registry)
        log.info("Events: %d; assessed: %d; eligible: %d; AI-verified: %d; excerpts/unassessed: %d; "
                 "AI requests: %d; tokens: %d",
                 len(events), sum(e.assessment is not None for e in events), len(chosen),
                 sum(s.status == "verified-analysis" for s in stories),
                 sum(s.status != "verified-analysis" for s in stories), engine.requests, engine.tokens)
        return Digest(edition_date=cutoff.astimezone(ZoneInfo(settings.timezone)).date().isoformat(),
            window_start=start, window_end=cutoff, timezone=settings.timezone, stories=stories,
            quotes=quotes or [], health=health, notices=list(dict.fromkeys(notices)),
            takeaways=eligible_ids[:5], notes=notes, decisions=events)
    finally:
        if owned_engine:
            engine.close()


def save_outputs(digest, parts, output_dir, *, restored=False, offline=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "digest.json").write_text(digest.model_dump_json(indent=2), encoding="utf-8")
    (output_dir / "coverage.json").write_text(json.dumps({"notices": digest.notices,
        "run": {"fresh_ai_run": not restored and not offline, "restored_edition": restored,
                "offline_fixture": offline,
                "generated_at": digest.window_end.isoformat()},
        "ai": ai_coverage(digest),
        "sources": [h.model_dump() for h in digest.health]}, indent=2), encoding="utf-8")
    for part in parts:
        name = "preview" if part.index == 1 else f"preview-{part.index}"
        preview_html, preview_text = part.html, part.text
        if restored:
            note = (f"Saved edition generated at {digest.window_end.isoformat()}. "
                    "This rerun restored previous content and made no new AI calls. "
                    "Use preview_only to test the current AI provider with fresh news.")
            banner = '<p role="status" style="padding:16px;background:#fff3cd;color:#412f00">' + html.escape(note) + '</p>'
            preview_html, inserted = re.subn(r"(<body\b[^>]*>)", lambda match: match[1] + banner,
                                            preview_html, count=1, flags=re.IGNORECASE)
            if not inserted:
                preview_html = banner + preview_html
            preview_text = note + "\n\n" + preview_text
        (output_dir / f"{name}.html").write_text(preview_html, encoding="utf-8")
        (output_dir / f"{name}.txt").write_text(preview_text, encoding="utf-8")
    log.info("Saved %d email part(s) to %s", len(parts), output_dir.resolve())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evidence-backed daily morning briefing")
    parser.add_argument("--dry-run", action="store_true", help="Save outputs without connecting to SMTP")
    parser.add_argument("--preview", action="store_true", help="Save outputs and open the first HTML part")
    parser.add_argument("--fixture", type=Path, help="Offline article fixture; implies dry-run (no market/network calls)")
    parser.add_argument("--retry-uncertain", action="store_true", help="Explicitly retry a previously uncertain delivery")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv(ROOT / ".env")
    settings = Settings.from_env()
    preview = args.preview or args.dry_run or args.fixture is not None
    if not preview:
        settings.validate_mail()
    cutoff = datetime.now(timezone.utc)
    edition = cutoff.astimezone(ZoneInfo(settings.timezone)).date().isoformat()
    path = state_path(settings, edition)
    existing = load_state(path) if not preview else None
    if existing:
        restored_digest = Digest.model_validate(existing["digest"])
        restored_parts = [RenderedPart.model_validate(item["payload"]) for item in existing["parts"]]
        confirmed = sum(item["status"] == "sent" for item in existing["parts"])
        verified = sum(story.status == "verified-analysis" for story in restored_digest.stories)
        log.info("Restored frozen edition generated at %s: %d/%d confirmed parts; %d/%d AI-verified stories. "
                 "No fresh collection or AI generation; use --dry-run for a fresh preview.",
                 restored_digest.window_end.isoformat(), confirmed, len(restored_parts),
                 verified, len(restored_digest.stories))
        save_outputs(restored_digest, render_parts(restored_digest, settings.html_bytes), settings.output_dir, restored=True)
        send_state(settings, path, existing, retry_uncertain=args.retry_uncertain)
        return
    if args.fixture:
        from app.testing import FixtureEngine
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        cutoff = datetime.fromisoformat(fixture["cutoff"])
        if cutoff.tzinfo is None:
            raise ValueError("Fixture cutoff requires timezone")
        articles = [Article.model_validate(a) for a in fixture["articles"]]
        registry = {a.id: a for a in articles}
        if any(a.published_at is None or not cutoff - timedelta(hours=settings.window_hours) <= a.published_at <= cutoff
               for a in articles):
            raise ValueError("Fixture articles must have in-window publication times")
        digest = build_digest(settings, registry, [], cutoff, engine=FixtureEngine(fixture))
        digest.notices.insert(0, "Offline synthetic sample; manually labeled assessments, no live AI/source/email calls.")
    else:
        # Configuration failures must stop before collection, not become hundreds
        # of unassessed source excerpts with a successful workflow status.
        settings.validate_ai()
        fetcher = Fetcher(settings)
        try:
            registry, health = collect(settings, fetcher, cutoff - timedelta(hours=settings.window_hours), cutoff)
            digest = build_digest(settings, registry, health, cutoff, quotes=fetch_market_snapshot(cutoff))
        finally:
            fetcher.close()
    parts = render_parts(digest, settings.html_bytes, include_excerpts=args.fixture is not None)
    save_outputs(digest, parts, settings.output_dir, offline=args.fixture is not None)
    if args.fixture is None and not preview:
        validate_digest_for_delivery(digest)
    if preview:
        # Preserve the historic preview.html at repository root as well as richer artifacts.
        Path("preview.html").write_text(parts[0].html, encoding="utf-8")
        if args.preview:
            import webbrowser
            webbrowser.open((settings.output_dir / "preview.html").resolve().as_uri())
        return
    path, state = prepare_state(settings, digest, parts)
    send_state(settings, path, state, retry_uncertain=args.retry_uncertain)
