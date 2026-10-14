"""Review-by-area: a Kanban Swarm recipe for reviewing a git branch.

``hermes kanban review`` turns "review this MR by area" into a durable
Kanban Swarm v1 graph: one parallel reviewer worker per review area carved
out of the branch diff, a verifier that gates on every reviewer's verdict,
and a synthesizer that merges the verdicts into one review report. The
recipe adds no scheduler and no gate types — it is a pure client of
:func:`kanban_swarm.create_swarm`, so dispatch, blackboard handoff, and the
verifier/synthesizer gates behave exactly like any other swarm.

Diff scoping is MR-style (``base...branch``, i.e. from the merge-base), with
one guard the plain git idiom lacks: files whose branch content already
matches the ``base`` tip are partitioned out as "already integrated". With
a stale merge-base, ``base...branch`` otherwise makes a review re-litigate
changes that already landed on base via another path and will merge as
no-ops.
"""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import sqlite3

from hermes_cli import kanban_swarm as ks


@dataclass(frozen=True)
class ReviewScope:
    """What the swarm will review, and what it deliberately skips."""

    repo: str
    base: str
    branch: str
    merge_base: str
    areas: dict[str, list[str]]
    already_integrated: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo, "base": self.base, "branch": self.branch,
            "merge_base": self.merge_base, "areas": self.areas,
            "already_integrated": self.already_integrated,
        }


def _git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise ValueError(f"git {' '.join(args)} in {repo}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def diff_files(repo: str, base: str, branch: str) -> tuple[list[str], str]:
    """MR-scope files (``base...branch``) plus the merge-base hash.

    Three-dot scoping matches what an MR shows: changes the branch carries
    since it diverged from base. Base-side changes made after the divergence
    are excluded, so reviewers see only what the branch itself did.
    """
    merge_base = _git(repo, "merge-base", base, branch).strip()
    if not merge_base:
        raise ValueError(f"no merge-base between {base} and {branch}")
    files = [line.strip() for line in _git(repo, "diff", "--name-only", f"{base}...{branch}").splitlines()]
    return [f for f in files if f], merge_base


def partition_integrated(repo: str, base: str, branch: str, files: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split MR-scope files into (needs-review, already-integrated).

    A file listed by ``base...branch`` whose content is identical at both
    tips will merge as a no-op — typically the same change that already
    landed on base via another branch. Reviewing it again wastes a worker
    and can block a merge for problems base has already accepted.
    """
    tip_changed = {line.strip() for line in _git(repo, "diff", "--name-only", base, branch).splitlines() if line.strip()}
    review = [f for f in files if f in tip_changed]
    integrated = [f for f in files if f not in tip_changed]
    return review, integrated


def parse_area_specs(pairs: Sequence[str]) -> list[tuple[str, tuple[str, ...]]]:
    """Parse ``NAME:GLOB[,GLOB...]`` strings into explicit area specs."""
    specs: list[tuple[str, tuple[str, ...]]] = []
    for pair in pairs:
        name, sep, globs_raw = pair.partition(":")
        name = name.strip()
        globs = tuple(g.strip() for g in globs_raw.split(",") if g.strip())
        if not sep or not name or not globs:
            raise ValueError(f"area must be NAME:GLOB[,GLOB...] — got {pair!r}")
        specs.append((name, globs))
    return specs


def _auto_area(path: str) -> str:
    """Deterministic default area: first two path components, else 'root'."""
    parts = path.split("/")
    if len(parts) >= 3:
        return "/".join(parts[:2])
    if len(parts) == 2:
        return parts[0]
    return "root"


def plan_review_areas(files: Sequence[str], specs: Optional[Sequence[tuple[str, tuple[str, ...]]]] = None) -> dict[str, list[str]]:
    """Group diff files into named review areas.

    Explicit specs win in declaration order (first match claims the file);
    files matching no spec fall into ``other``. Without specs, areas come
    from :func:`_auto_area` — stable groupings like ``src/api`` or ``docs``
    that mirror how repositories are actually owned.
    """
    areas: dict[str, list[str]] = {}
    if not specs:
        for path in files:
            areas.setdefault(_auto_area(path), []).append(path)
        return areas
    for path in files:
        for name, globs in specs:
            if any(fnmatch.fnmatch(path, glob) for glob in globs):
                areas.setdefault(name, []).append(path)
                break
        else:
            areas.setdefault("other", []).append(path)
    return areas


def _reviewer_body(repo: str, base: str, branch: str, merge_base: str, area: str, files: Sequence[str]) -> str:
    file_list = "\n".join(f"- {path}" for path in files)
    return (
        f'You are the "{area}" reviewer for branch {branch} (vs {base}) in repo {repo}.\n\n'
        f"Scope: MR diff `{base}...{branch}` (merge-base {merge_base}), limited to your area:\n"
        f"{file_list}\n\n"
        f"Protocol:\n"
        f"1. Read the area diff: `git -C {repo} diff {merge_base} {branch} -- <files>`.\n"
        f"2. Judge correctness, tests, docs claims, and integration risk against "
        f"{base} tip — these files may have moved on since the merge-base.\n"
        f"3. READ-ONLY review: do not modify the repo, do not push, do not merge.\n"
        f"4. Post one blackboard update on the swarm root with key `review:{area}` "
        f'and JSON value {{"verdict": "pass"|"concerns"|"fail", "findings": [...]}}. '
        f"Cite file:line evidence for every finding, then complete this card."
    )


def create_review_swarm(
    conn: sqlite3.Connection,
    *,
    repo: str,
    base: str,
    branch: str,
    area_specs: Optional[Sequence[tuple[str, tuple[str, ...]]]] = None,
    reviewer_profile: str,
    verifier_assignee: str,
    synthesizer_assignee: str,
    tenant: Optional[str] = None,
    created_by: str = "review-orchestrator",
    priority: int = 0,
    idempotency_key: Optional[str] = None,
    extra_context: Optional[str] = None,
) -> tuple[ks.SwarmCreated, ReviewScope]:
    """Create the review-by-area swarm and return (created, scope).

    Raises :class:`ValueError` when the branch diff is empty or consists
    entirely of already-integrated files — a swarm with nothing to review
    should not sit on the board.
    """
    files, merge_base = diff_files(repo, base, branch)
    if not files:
        raise ValueError(f"no changes between {base} and {branch}")
    review_files, integrated = partition_integrated(repo, base, branch, files)
    if not review_files:
        raise ValueError(f"all changes on {branch} are already on {base} — nothing to review")
    areas = plan_review_areas(review_files, area_specs)
    scope = ReviewScope(repo, base, branch, merge_base, areas, integrated)

    workers = [
        ks.SwarmWorkerSpec(
            profile=reviewer_profile,
            title=f"Review {area} ({len(paths)} files)",
            body=_reviewer_body(repo, base, branch, merge_base, area, paths),
            priority=priority,
        )
        for area, paths in areas.items()
    ]
    goal = (
        f"Review branch {branch} vs {base} in {repo} by area "
        f"({', '.join(areas)}), then produce one gated merge verdict."
    )
    if extra_context:
        goal += f"\n\nCoordination context:\n{extra_context}"
    created = ks.create_swarm(
        conn, goal=goal, workers=workers,
        verifier_assignee=verifier_assignee, synthesizer_assignee=synthesizer_assignee,
        root_title=f"Review {branch} by area", tenant=tenant, created_by=created_by,
        priority=priority, idempotency_key=idempotency_key,
    )
    ks.post_blackboard_update(
        conn, created.root_id, author=created_by, key="review-scope", value=scope.as_dict(),
    )
    return created, scope
