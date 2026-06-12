"""Behavioural grading tests for the knowledge_service.py fake issues.

Covers: knowledge-search-prefix-only, knowledge-get-by-topic-inverted,
knowledge-search-and-instead-of-or.
"""

from __future__ import annotations


def test_search_matches_text_in_the_middle_of_a_field(knowledge_service, make_article):
    # knowledge-search-prefix-only — the term appears mid-content, not at the start
    article = make_article(
        topic="policies",
        title="Customer guidance",
        content="Please review our refund timelines before you travel.",
    )
    results = knowledge_service.search("refund")
    assert article.id in [a.id for a in results]


def test_get_by_topic_returns_only_that_topic(knowledge_service, make_article):
    # knowledge-get-by-topic-inverted
    wanted = make_article(topic="baggage", title="Baggage allowance", content="…")
    make_article(topic="refunds", title="Refund policy", content="…")
    results = knowledge_service.get_by_topic("baggage")
    assert [a.id for a in results] == [wanted.id]
    assert all(a.topic == "baggage" for a in results)


# ---------------------------------------------------------------------------
# Medium-level fixtures
# ---------------------------------------------------------------------------


def test_search_finds_article_when_term_is_only_in_title(knowledge_service, make_article):
    # knowledge-search-and-instead-of-or: a term that appears in ONLY the title field
    # must still be returned (or_ semantics); with and_ it would require the term to
    # appear in topic, title, AND content simultaneously — returning nothing
    article = make_article(
        topic="general",
        content="See our website for full terms.",
        title="Excess baggage charges explained",
    )
    results = knowledge_service.search("baggage")
    assert article.id in [a.id for a in results], (
        "Search should return articles where the query appears in any single field"
    )
