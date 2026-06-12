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


class _TopicFilteredSession:
    def __init__(self, articles):
        self.articles = articles
        self.last_statement = None

    def scalars(self, statement):
        self.last_statement = statement
        criteria = list(getattr(statement, "_where_criteria", ()))
        topic = None
        active_only = False

        for criterion in criteria:
            text = str(criterion)
            if "knowledge_articles.is_active" in text and "true" in text.lower():
                active_only = True
            if "knowledge_articles.topic" in text and "=" in text:
                if ":" in text:
                    # SQLAlchemy bind parameter form; the actual value is embedded in the compiled params.
                    params = getattr(statement, "_compile_options", None)
                # Best effort for tests: capture the bound value from the clause when it is rendered.
                if "'" in text:
                    first = text.find("'")
                    last = text.rfind("'")
                    if first != -1 and last != -1 and last > first:
                        topic = text[first + 1 : last]

        if topic is None:
            return _ScalarResult([])

        matches = [
            article
            for article in self.articles
            if (not active_only or article.is_active) and article.topic == topic
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


@pytest.fixture()
def topic_articles() -> list[_FakeKnowledgeArticle]:
    return [
        _FakeKnowledgeArticle(
            topic="Baggage",
            title="Carry-on size limits",
            content="Carry-on bags must fit in the overhead bin.",
        ),
        _FakeKnowledgeArticle(
            topic="Baggage",
            title="Checked bag fees",
            content="Fees depend on route and fare class.",
        ),
        _FakeKnowledgeArticle(
            topic="Check-in",
            title="Online check-in windows",
            content="Check in opens 24 hours before departure.",
        ),
        _FakeKnowledgeArticle(
            topic="Baggage",
            title="Lost luggage report",
            content="Report missing bags at the service desk immediately.",
            is_active=False,
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


def test_get_by_topic_returns_only_matching_topic_articles(topic_articles):
    session = _TopicFilteredSession(topic_articles)
    service = KnowledgeService(session)

    results = service.get_by_topic("Baggage")

    assert [article.title for article in results] == ["Carry-on size limits", "Checked bag fees"]
    assert all(article.topic == "Baggage" for article in results)
    assert all(article.is_active for article in results)


def test_get_by_topic_excludes_unrelated_topics(topic_articles):
    session = _TopicFilteredSession(topic_articles)
    service = KnowledgeService(session)

    results = service.get_by_topic("Baggage")

    assert "Online check-in windows" not in [article.title for article in results]
    assert all(article.topic != "Check-in" for article in results)
