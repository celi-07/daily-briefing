from collections import Counter
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.config import ROOT
from app.models import LABELS, TOPICS, RenderedPart

STATUS = {"verified-analysis": "Evidence-checked analysis", "source-excerpt": "Source excerpt", "unassessed": "Unassessed source excerpt"}


def ai_coverage(digest):
    assessed = sum(event.assessment is not None for event in digest.decisions)
    return {"events": len(digest.decisions), "assessed": assessed,
        "unassessed": len(digest.decisions) - assessed,
        "verified_stories": sum(story.status == "verified-analysis" for story in digest.stories),
        "source_excerpts": sum(story.status == "source-excerpt" for story in digest.stories),
        "assessment_failures": dict(Counter(event.decision for event in digest.decisions
                                             if event.assessment is None))}


def render_parts(digest, max_bytes=80 * 1024, *, include_excerpts=False):
    if not include_excerpts:
        digest = digest.model_copy(update={"stories": [s for s in digest.stories if s.status == "verified-analysis"],
            "notices": [n for n in digest.notices if not n.startswith(("AI assessment unavailable", "Some qualifying stories were omitted"))]})
    environment = Environment(loader=FileSystemLoader(ROOT / "templates"), undefined=StrictUndefined,
        autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=True),
        trim_blocks=True, lstrip_blocks=True)
    zone = ZoneInfo(digest.timezone)
    environment.filters["localtime"] = lambda value: value.astimezone(zone).strftime("%d %b %Y, %H:%M %Z") if value else "Unknown"
    templates = [environment.get_template(name) for name in ("digest.html.j2", "digest.txt.j2")]
    counts = Counter(s.topic for s in digest.stories)
    by_id = {s.event_id: s for s in digest.stories}
    empty = {}
    for topic in TOPICS:
        providers = [h for h in digest.health if topic in h.topics and h.status != "disabled"]
        if providers and all(h.status == "failed" for h in providers):
            empty[topic] = "Sources unavailable; news coverage could not be established."
        elif any(e.assessment is None or e.eligible and e.assessment.topic == topic for e in digest.decisions):
            empty[topic] = "No verified stories available from the collected evidence."
        else:
            empty[topic] = "No qualifying important stories found in the collected evidence."
    # Keep each topic together, preserving importance order within it.
    ordered = [s for topic in TOPICS for s in digest.stories if s.topic == topic]

    def render(stories, index, total, continued, reserve=False):
        context = dict(digest=digest, stories=stories, topics=TOPICS, labels=LABELS, counts=counts,
            ai_coverage=ai_coverage(digest),
            status_labels=STATUS, empty_states=empty, continued=continued, index=index, total=total,
            language_code="en", takeaways=[by_id[i] for i in digest.takeaways if i in by_id])
        context["note_sources"] = {sid: by_id[sid].citations[0] for note in digest.notes for sid in note.story_ids if sid in by_id}
        context["show_notes"] = reserve or index == total
        return [template.render(**context) for template in templates]

    groups = [[]]
    for story in ordered:
        # Reserve space for subject/continuation labels using the maximum possible part count.
        candidate = groups[-1] + [story]
        html, _ = render(candidate, len(groups), max(1, len(ordered) + 1), set(TOPICS), reserve=True)
        if len(html.encode("utf-8")) > max_bytes:
            if not groups[-1] and len(groups) > 1:
                raise ValueError("One story exceeds the HTML budget; shorten evidence output or raise HTML_BYTES")
            groups.append([story])
            html, _ = render([story], len(groups), len(ordered) + 1, set(TOPICS), reserve=True)
            if len(html.encode("utf-8")) > max_bytes:
                raise ValueError("One story exceeds the HTML budget; shorten evidence output or raise HTML_BYTES")
        else:
            groups[-1] = candidate
    seen, parts = set(), []
    for index, stories in enumerate(groups, 1):
        html, text = render(stories, index, len(groups), seen.copy())
        if len(html.encode("utf-8")) > max_bytes:
            raise ValueError("Digest header/footer exceeds HTML budget; increase HTML_BYTES")
        parts.append(RenderedPart(index=index, total=len(groups), html=html, text=text, event_ids=[s.event_id for s in stories]))
        seen.update(s.topic for s in stories)
    return parts
