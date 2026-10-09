from urllib.parse import urlsplit

from app.cluster import normalized
from app.models import Citation, Story


def select(events, registry, threshold, *, world_threshold=3, market_threshold=3):
    for event in events:
        event.eligible = False
        result = event.assessment
        evidence = [registry[aid] for aid in event.article_ids]
        if not result:
            continue
        credible = [a for a in evidence if a.trust in ("primary", "reporter")
                    and a.quality != "title-only" and a.text.strip()]
        origins = [registry[aid] for aid in result.independent_origins
                   if aid in event.article_ids and registry[aid].trust in ("primary", "reporter")]
        # Different domains + nonidentical content; links/reprints do not corroborate.
        origin_domains = {urlsplit(a.url).hostname for a in origins}
        origin_texts = {normalized(a.text) for a in origins}
        has_linked_copy = any(a.url in other.linked_urls for a in origins for other in origins if a.id != other.id)
        independent = min(len(origin_domains), len(origin_texts)) if not has_linked_copy else 1
        own_statement = result.primary_own_statement and any(a.trust == "primary" for a in credible)
        reporter = any(a.trust == "reporter" for a in credible)
        world = result.world_score is not None and result.world_score >= world_threshold
        market = result.market_score is not None and result.market_score >= market_threshold
        legacy = result.world_score is None and result.market_score is None
        event.reporting_basis = "primary-statement" if own_statement else "corroborated" if independent >= 2 else "reported"
        event.briefing_section = "market" if market else "world"
        credible_ids = {a.id for a in credible}
        has_attributable_fact = any(set(fact.article_ids) & credible_ids for fact in result.facts)
        if result.evidence not in ("supported", "limited") or not has_attributable_fact:
            event.decision = "Insufficient or conflicting evidence"
        elif not (own_statement or reporter):
            event.decision = "Uncorroborated social claim"
        elif legacy and result.scores.total < threshold:
            event.decision = f"Importance {result.scores.total:g} below threshold {threshold:g}"
        elif not legacy and not (world or market):
            event.decision = "Below world-development and market-catalyst thresholds"
        else:
            event.eligible = True
            event.decision = "Meets importance and evidence policy" if legacy else "Qualifies for " + ("world and market" if world and market else "market catalysts" if market else "world developments")
    return [event for event in events if event.eligible]


def source_story(event, registry, *, unassessed=False, failure_reason=""):
    articles = sorted((registry[aid] for aid in event.article_ids),
                      key=lambda a: (a.trust == "unknown", a.quality != "full", -len(a.text), a.id))
    article = articles[0]
    # Quotes/excerpts are retained verbatim, with attribution; never synthesize implications.
    text = article.text[:700].strip()
    if len(article.text) > 700:
        end = text.rfind(" ")
        text = text[:end] + "…" if end > 0 else text + "…"
    assessment = event.assessment
    topic = assessment.topic if assessment else article.topics[0] if article.topics else "finance"
    return Story(event_id=event.id, topic=topic,
        secondary_topics=assessment.secondary_topics if assessment else [], headline=article.title,
        summary=text or "Read the source for details; no article text was available.",
        citations=[Citation(article_id=a.id, source=a.source_name, url=a.url, published_at=a.published_at) for a in articles],
        importance=assessment.scores.total if assessment and not unassessed else None,
        published_at=max(a.published_at for a in articles),
        status="unassessed" if unassessed else "source-excerpt",
        briefing_section=event.briefing_section, reporting_basis=event.reporting_basis,
        world_score=assessment.world_score if assessment else None,
        market_score=assessment.market_score if assessment else None,
        regions=assessment.regions if assessment else [], themes=assessment.themes if assessment else [],
        caveat=f"AI assessment unavailable: {event.decision}. Source text only; importance is unknown." if unassessed
               else (f"Source excerpt; AI analysis unavailable: {failure_reason}." if failure_reason
                     else "Source excerpt; AI summary could not be verified."))


def sort_stories(stories):
    def priority(story):
        score = story.market_score if story.briefing_section == "market" else story.world_score
        return score * 20 if score is not None else story.importance if story.importance is not None else -1
    return sorted(stories, key=lambda s: (-priority(s), -s.published_at.timestamp(), s.event_id))
