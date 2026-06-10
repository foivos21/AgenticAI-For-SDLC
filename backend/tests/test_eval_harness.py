from __future__ import annotations

import pytest

from app.eval.bug_catalog import BUG_FIXTURES, DATASET_LABEL, get_fixture
from app.eval.harness import BACKEND_DIR, REPO_ROOT, fixture_status
from app.services.jira_service import text_to_adf


@pytest.mark.parametrize("fixture", BUG_FIXTURES, ids=lambda f: f.slug)
def test_fixture_snippets_are_consistent(fixture):
    assert fixture.correct != fixture.broken
    # Neither snippet may be a substring of the other, otherwise status
    # detection cannot tell the clean and broken states apart.
    assert fixture.correct not in fixture.broken
    assert fixture.broken not in fixture.correct


@pytest.mark.parametrize("fixture", BUG_FIXTURES, ids=lambda f: f.slug)
def test_target_file_snippet_is_locatable(fixture):
    # The target must exist and be in a known state (clean or broken) so that
    # inject/restore can find their snippet. This stays valid even while an
    # evaluation is mid-flight (i.e. the bug is currently injected).
    target = REPO_ROOT / fixture.target_file
    assert target.exists(), f"missing target file: {fixture.target_file}"
    assert fixture_status(fixture) in {"clean", "broken"}


@pytest.mark.parametrize("fixture", BUG_FIXTURES, ids=lambda f: f.slug)
def test_test_file_exists_when_declared(fixture):
    if fixture.test_file:
        assert (BACKEND_DIR / fixture.test_file).exists()


@pytest.mark.parametrize("fixture", BUG_FIXTURES, ids=lambda f: f.slug)
def test_labels_include_task_slug_and_dataset(fixture):
    assert f"ai_task:{fixture.slug}" in fixture.labels
    assert DATASET_LABEL in fixture.labels


def test_slugs_are_unique():
    slugs = [f.slug for f in BUG_FIXTURES]
    assert len(slugs) == len(set(slugs))


def test_get_fixture_unknown_raises():
    with pytest.raises(KeyError):
        get_fixture("does-not-exist")


def test_text_to_adf_header_then_bullets():
    doc = text_to_adf("Steps to reproduce:\n- one\n- two\n\nA plain paragraph.")
    types = [block["type"] for block in doc["content"]]
    assert types == ["paragraph", "bulletList", "paragraph"]
    bullets = doc["content"][1]["content"]
    assert len(bullets) == 2
    assert bullets[0]["content"][0]["content"][0]["text"] == "one"


def test_text_to_adf_empty_is_valid():
    doc = text_to_adf("")
    assert doc["type"] == "doc"
    assert doc["content"][0]["type"] == "paragraph"
