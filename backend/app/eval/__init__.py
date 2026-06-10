"""ALMAS evaluation harness.

Tooling to inject controlled, single-file bugs into the ``sample_app`` mini-app
and create the matching Jira tickets, so the ALMAS pipeline can be evaluated on a
reproducible dataset of easy defects.
"""

from __future__ import annotations

from app.eval.bug_catalog import BUG_FIXTURES, BugFixture, get_fixture

__all__ = ["BUG_FIXTURES", "BugFixture", "get_fixture"]
