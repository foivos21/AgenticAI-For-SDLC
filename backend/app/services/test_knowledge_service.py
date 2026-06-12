from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.knowledge_service import KnowledgeService


@dataclass
class _FakeKnowledgeArticle:
    topic: str
    title: str
    content: str
    is_active: bool = True


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, articles):
        self.articles = articles
        self.last_statement = None

    def scalars(self, statement):
        self.last_statement = statement
        pattern = None
        criteria = list(getattr(statement, "_where_criteria", ()))
        for criterion in criteria:
            text = str(criterion)
            if "LIKE" in text or "like" in text:
                # Extract the bind-like pattern from the SQL string representation when possible.
                if "%" in text:
                    first = text.find("%")
                    last = text.rfind("%")
                    if first != -1 and last != -1 and last > first:
                        pattern = text[first : last + 1].replace("'", "")
                        break
        if pattern is None:
            return _ScalarResult([])

        needle = pattern.strip("%").lower()
        matches = [
            article
            for article in self.articles
            if article.is_active
            and (
                needle in article.topic.lower()
                or needle in article.title.lower()
                or needle in article.content.lower()
            )
        ]
        return _ScalarResult(matches)


@pytest.fixture()
def sample_articles() -> list[_FakeKnowledgeArticle]:
    return [
        _FakeKnowledgeArticle(
            topic="Billing",
            title="How to update payment details",
            content="You can update your card in the billing portal after logging in.",
        ),
        _FakeKnowledgeArticle(
            topic="Shipping",
            title="Tracking orders",
            content="Order tracking becomes available after the package is scanned at the depot.",
        ),
        _FakeKnowledgeArticle(
            topic="Returns",
            title="Refund timeline",
            content="Refunds are processed within five business days.",
            is_active=False,
        ),
        _FakeKnowledgeArticle(
            topic="Getting Started",
            title="Using search effectively",
            content="Learn how to find results quickly with the knowledge base.",
        ),
    ]


def test_search_returns_mid_field_matches_in_content(sample_articles):
    session = _FakeSession(sample_articles)
    service = KnowledgeService(session)

    results = service.search("scanned")

    assert [article.title for article in results] == ["Tracking orders"]


def test_search_returns_mid_field_matches_in_title(sample_articles):
    session = _FakeSession(sample_articles)
    service = KnowledgeService(session)

    results = service.search("search")

    assert [article.title for article in results] == ["Using search effectively"]


def test_search_returns_mid_field_matches_in_topic(sample_articles):
    session = _FakeSession(sample_articles)
    service = KnowledgeService(session)

    results = service.search("Started")

    assert [article.title for article in results] == ["Using search effectively"]


def test_search_still_returns_prefix_matches(sample_articles):
    session = _FakeSession(sample_articles)
    service = KnowledgeService(session)

    results = service.search("Billing")

    assert [article.title for article in results] == ["How to update payment details"]


def test_search_returns_no_results_for_missing_term(sample_articles):
    session = _FakeSession(sample_articles)
    service = KnowledgeService(session)

    results = service.search("nonexistent")

    assert results == []
