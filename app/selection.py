from urllib.parse import urlsplit

from app.cluster import normalized
from app.models import Citation, Story


def select(events, registry, threshold):
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
        if result.evidence != "supported" or not result.facts or not credible:
            event.decision = "Insufficient or conflicting evidence"
        elif not (own_statement or reporter):
            event.decision = "Uncorroborated social claim"
        elif result.high_risk and independent < 2 and not own_statement:
            event.decision = "High-risk third-party claim needs independent corroboration"
        elif result.scores.total < threshold:
            event.decision = f"Importance {result.scores.total:g} below threshold {threshold:g}"
        else:
            event.eligible = True
            event.decision = "Meets importance and evidence policy"
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
        caveat=f"AI assessment unavailable: {event.decision}. Source text only; importance is unknown." if unassessed
               else (f"Source excerpt; AI analysis unavailable: {failure_reason}." if failure_reason
                     else "Source excerpt; AI summary could not be verified."))


def sort_stories(stories):
    return sorted(stories, key=lambda s: (-(s.importance if s.importance is not None else -1),
                                         -s.published_at.timestamp(), s.event_id))
