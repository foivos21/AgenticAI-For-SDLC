"""ALMAS evaluation harness.

Tooling to inject controlled bugs and create matching Jira tickets for the
BugFixture dataset, and to run FeatureFixture tasks where ALMAS must implement
a missing feature from scratch.
"""

from __future__ import annotations

from app.eval.bug_catalog import (
    ALL_BUG_FIXTURES,
    BUG_FIXTURES,
    MEDIUM_BUG_FIXTURES,
    BugFixture,
    FeatureFixture,
    get_fixture,
)
from app.eval.feature_catalog import FEATURE_FIXTURES, get_feature

__all__ = [
    "ALL_BUG_FIXTURES",
    "BUG_FIXTURES",
    "MEDIUM_BUG_FIXTURES",
    "BugFixture",
    "FeatureFixture",
    "FEATURE_FIXTURES",
    "get_fixture",
    "get_feature",
]
