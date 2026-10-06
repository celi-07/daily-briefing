import re
import unicodedata

from app.models import Event, stable_id


def normalized(text):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def cluster_articles(articles):
    """Conservative exact title/URL/link clustering; semantic merging follows assessment."""
    parents = {a.id: a.id for a in articles}

    def root(item):
        while parents[item] != item:
            item = parents[item]
        return item

    lookup = {}
    for article in articles:
        keys = ["url:" + article.url, *["url:" + url for url in article.linked_urls]]
        title = normalized(article.title)
        if len(title.split()) >= 6:
            keys.append("title:" + title)
        for key in keys:
            if key in lookup:
                parents[root(article.id)] = root(lookup[key])
            else:
                lookup[key] = article.id
    groups = {}
    for article in articles:
        groups.setdefault(root(article.id), []).append(article.id)
    return [Event(id=stable_id("|".join(sorted(ids))), article_ids=sorted(ids)) for ids in groups.values()]


def merge_assessed_events(events):
    """Language-independent precise event keys; require overlapping entities too."""
    groups = []
    for event in events:
        assessment = event.assessment
        entities = {normalized(e) for e in assessment.entities} if assessment else set()
        match = None
        for group in groups:
            other = group[0].assessment
            if assessment and other and normalized(assessment.event_key) == normalized(other.event_key):
                if entities & {normalized(e) for e in other.entities}:
                    match = group
                    break
        if match is None:
            groups.append([event])
        else:
            match.append(event)
    merged, unchanged = [], []
    for group in groups:
        if len(group) == 1:
            unchanged.extend(group)
        else:
            ids = sorted({aid for event in group for aid in event.article_ids})
            merged.append(Event(id=stable_id("|".join(ids)), article_ids=ids))
    # Merged evidence must be reassessed; do not inherit the best score/primary flag.
    return unchanged, merged
