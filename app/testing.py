"""Explicit offline fixture mode; never used by production collection or delivery."""
from app.models import Assessment


class FixtureEngine:
    requests = 0
    tokens = 0

    def __init__(self, fixture):
        self.assessments = fixture.get("assessments", {})

    def assess(self, events, registry, notices):
        from app.ai import valid_assessments
        for event in events:
            # Map by article ID so event hashes need not be duplicated in fixtures.
            item = self.assessments.get(event.article_ids[0])
            if item:
                result = Assessment.model_validate({**item, "event_id": event.id})
                valid_assessments([result], [event])
                event.assessment = result
            else:
                notices.append("Offline fixture has unassessed evidence; sample content only.")

    def summarize(self, event, registry):
        return None  # Show attributed fixture excerpts; do not simulate a successful live AI audit.

    def close(self):
        pass

    def synthesize(self, stories, registry):
        return []
