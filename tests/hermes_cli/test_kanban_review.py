"""Tests for the review-by-area Kanban Swarm recipe (kanban_review.py)."""

import subprocess

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli.kanban_review import (
    create_review_swarm,
    diff_files,
    parse_area_specs,
    partition_integrated,
    plan_review_areas,
)
from hermes_cli.kanban_swarm import latest_blackboard


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A repo where ws/x changed 4 files across areas; main then moved on."""
    r = tmp_path / "repo"
    r.mkdir()
    (r / "src" / "api").mkdir(parents=True)
    (r / "src" / "web").mkdir(parents=True)
    (r / "docs").mkdir()
    (r / "src" / "api" / "a.py").write_text("a = 1\n")
    (r / "docs" / "readme.md").write_text("base\n")
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "base")
    _git(r, "checkout", "-b", "ws/x")
    (r / "src" / "api" / "a.py").write_text("a = 2\n")
    (r / "src" / "web" / "b.py").write_text("b = 1\n")
    (r / "docs" / "readme.md").write_text("base\nmore\n")
    (r / "tools" / "build").mkdir(parents=True)
    (r / "tools" / "build" / "c.py").write_text("c = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "ws changes")
    # Base-side change after divergence: must NOT appear in the MR-scope diff.
    _git(r, "checkout", "main")
    (r / "base-only.txt").write_text("z\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "base-only change")
    return r


def test_diff_files_scopes_to_branch_changes(repo):
    files, merge_base = diff_files(str(repo), "main", "ws/x")
    assert sorted(files) == ["docs/readme.md", "src/api/a.py", "src/web/b.py", "tools/build/c.py"]
    assert len(merge_base) == 40  # a full hash, usable in reviewer commands


def test_partition_integrated_flags_already_landed_changes(repo):
    # The same change lands on main via another path: identical tips → no-op merge.
    (repo / "src" / "api" / "a.py").write_text("a = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "same change on main")
    files, _ = diff_files(str(repo), "main", "ws/x")
    review, integrated = partition_integrated(str(repo), "main", "ws/x", files)
    assert integrated == ["src/api/a.py"]
    assert sorted(review) == ["docs/readme.md", "src/web/b.py", "tools/build/c.py"]


def test_plan_review_areas_auto_groups_by_path_prefix():
    files = ["src/api/a.py", "src/web/b.py", "docs/readme.md", "tools/build/c.py", "README.md"]
    areas = plan_review_areas(files)
    assert areas == {
        "src/api": ["src/api/a.py"],
        "src/web": ["src/web/b.py"],
        "docs": ["docs/readme.md"],
        "tools/build": ["tools/build/c.py"],
        "root": ["README.md"],
    }


def test_plan_review_areas_explicit_specs_claim_files_in_order():
    specs = [("api", ("src/api/*",)), ("docs", ("docs/*",))]
    areas = plan_review_areas(["src/api/a.py", "src/web/b.py", "docs/readme.md"], specs)
    assert areas == {"api": ["src/api/a.py"], "docs": ["docs/readme.md"], "other": ["src/web/b.py"]}


def test_parse_area_specs_rejects_garbage():
    assert parse_area_specs(["api:src/api/*", "build:tools/build/*,tools/*.py"]) == [
        ("api", ("src/api/*",)),
        ("build", ("tools/build/*", "tools/*.py")),
    ]
    with pytest.raises(ValueError, match="NAME:GLOB"):
        parse_area_specs(["api"])
    with pytest.raises(ValueError, match="NAME:GLOB"):
        parse_area_specs([":src/api/*"])


def test_create_review_swarm_builds_gated_graph(repo, tmp_path):
    conn = kbc.connect(tmp_path / "kanban.db")
    try:
        created, scope = create_review_swarm(
            conn, repo=str(repo), base="main", branch="ws/x",
            reviewer_profile="reviewer-a", verifier_assignee="verifier",
            synthesizer_assignee="writer", tenant="reviews", created_by="orchestrator",
            extra_context="Branch flagged do-not-merge; review feeds the user's decision.",
        )
        root = kb.get_task(conn, created.root_id)
        workers = [kb.get_task(conn, tid) for tid in created.worker_ids]
        verifier = kb.get_task(conn, created.verifier_id)
        writer = kb.get_task(conn, created.synthesizer_id)

        assert root is not None and root.assignee == "orchestrator"
        assert verifier is not None and writer is not None
        assert all(w is not None for w in workers)
        assert len(workers) == len(scope.areas) == 4
        assert scope.already_integrated == []
        by_title = {w.title: w for w in workers if w is not None}
        api = by_title["Review src/api (1 files)"]
        assert "src/api/a.py" in api.body
        assert "git -C " + str(repo) in api.body
        assert "review:src/api" in api.body  # blackboard handoff key
        assert scope.merge_base in api.body  # exact diff range, not a guess
        assert "do-not-merge" in root.body or "do-not-merge" in api.body

        blackboard = latest_blackboard(conn, created.root_id)
        assert blackboard["review-scope"]["areas"] == scope.areas
        assert blackboard["review-scope"]["already_integrated"] == []
    finally:
        conn.close()


def test_create_review_swarm_skips_already_integrated_files(repo, tmp_path):
    (repo / "src" / "api" / "a.py").write_text("a = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "same change on main")
    conn = kbc.connect(tmp_path / "kanban.db")
    try:
        created, scope = create_review_swarm(
            conn, repo=str(repo), base="main", branch="ws/x",
            reviewer_profile="reviewer-a", verifier_assignee="verifier",
            synthesizer_assignee="writer",
        )
        assert "src/api" not in scope.areas
        assert scope.already_integrated == ["src/api/a.py"]
        assert len(created.worker_ids) == 3
    finally:
        conn.close()


def test_create_review_swarm_refuses_when_nothing_to_review(repo, tmp_path):
    _git(repo, "checkout", "main")
    _git(repo, "checkout", "-b", "ws/identical")
    conn = kbc.connect(tmp_path / "kanban.db")
    try:
        with pytest.raises(ValueError, match="no changes"):
            create_review_swarm(
                conn, repo=str(repo), base="main", branch="ws/identical",
                reviewer_profile="reviewer-a", verifier_assignee="verifier",
                synthesizer_assignee="writer",
            )
    finally:
        conn.close()
