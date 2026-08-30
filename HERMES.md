# Project rules: cpompa/hermes-agent fork

## Remote naming — unified across machines (2026-07-23)

Both checkouts (Mac and mini, each at `~/.hermes/hermes-agent`) use the
same remote names. Still run `git remote -v` first to be safe.

| Remote     | Points at                                      |
| ---------- | ---------------------------------------------- |
| `origin`   | gitlab.cpompa.com/cpompa/hermes-agent (our fork) |
| `upstream` | github.com/NousResearch/hermes-agent (read-only) |

Push fork changes to `origin`. The **`upstream` remote is read-only.**
(Before 2026-07-23 the Mac used `origin` = GitHub, `gitlab` = fork — old
docs/notes may still reference that.)

## This fork vendors upstream — do NOT `git pull` upstream

The fork tracks upstream by committing **squashed snapshots** of upstream
rather than merging upstream history. As a result the histories are
structurally divergent (`git status` shows "ahead N / behind M" at the
same time) and a direct pull/merge from the upstream remote will conflict
massively.

**To take a newer upstream version:** follow the recipe in
`FORK_CHANGELOG.md` — snapshot upstream, then re-apply our delta on top.
`FORK_CHANGELOG.md` is the source of truth for what is ours.

## Pushing to gitlab from the mini needs an unlocked keychain

The mini stores its gitlab credential in the macOS **login keychain**
(`osxkeychain` helper). Over a non-interactive SSH session that keychain
is locked, so any push/fetch to gitlab fails with `-25308`
(`errSecInteractionNotAllowed`) / "could not read Username".

Workarounds, in order of preference:
1. Run the git command in a **GUI-unlocked** Terminal on the mini.
2. **Relay through the Mac**: `git fetch` the commit Mac←mini over SSH,
   then push Mac→gitlab (the Mac's login keychain is unlocked).
3. Permanent fix: store a GitLab PAT in `~/.git-credentials` with
   `git config credential.helper store` so headless pushes work.

## Contributing changes upstream (GitHub PRs) — cut from upstream/main

This fork carries fork-only files that must NEVER reach a GitHub remote:
`.gitlab-ci.yml` (homelab runner tags), `FORK_CHANGELOG.md`,
`FORK_UPDATE_RUNBOOK.md`, `HERMES.md`, `scripts/fork-*`.

Flow: `git fetch upstream` → `git checkout -b fix/xyz upstream/main` →
apply/cherry-pick ONLY the change → push to a `github*` remote → open the
PR from that branch. Never open an upstream PR from a branch based on our
`main` — the PR diff would include the fork delta.

Branch discipline (enforced by the hook below, on ALL remotes):

- **Naming cadence** on GitHub-bound working branches: `<type>/<slug>`,
  type in `feat|fix|docs|chore|refactor|test|perf|ci`
  (e.g. `fix/drain-probe-glob`).
- **No force pushes, even to our own remotes/forks** — every ref update
  must be a fast-forward. Rebase locally and push a new branch instead of
  rewriting a pushed one. Use `git worktree` for parallel work rather than
  repurposing this checkout.
- Mirror pushes of `main` to our own GitHub fork stay allowed, FF-only.

A pre-push hook (`.git/hooks/pre-push`, local per checkout — installed on
both Mac and mini) enforces all of the above. Do not bypass it with
`--no-verify`; if it fires, fix the branch, not the hook.

## fork-upgrader plugin — repo is the source of truth

The plugin (`~/.hermes/plugins/fork-upgrader/` +
`~/.hermes/desktop-plugins/fork-upgrader/`) is versioned at
gitlab.cpompa.com/hermes-plugins/fork-upgrader, cloned at
`~/Documents/gitlab-repos/fork-upgrader` on the Mac. Edit the clone, never
the live dirs; `./sync-live.sh` installs repo → live (refuses on drift,
`--check` guards). The mini's copy advances automatically on the next
plugin `deploy` (`plugin_sync` in the job result).

## Profile-scoped operation (2026-08-29)

This machine runs Hermes in profile-scoped mode: per-profile model pins
(`local`, `coder`, `homelab` → model-router roles; `default` → agg/agg-auto)
and all cron jobs explicitly pinned, so global config drift can't reroute or
drift-skip work. Operational details live in `~/AGENTS.md`; the gateway-side
piece (`profile_routes` + `multiplex_profiles` on the mini) is documented in
`docs/profile-routing.md`. When changing profile or cron model pins, update
`~/AGENTS.md` in the same pass.

## When working in a git worktree (`hermes -w` mode)

Before finishing each task or ending the session, commit any
uncommitted changes on the current branch and push to our fork remote
(`origin` on both machines — see the remote table above).
The worktree is wiped on session exit — uncommitted work is lost
otherwise.

Standard finishing sequence:

1. `git status` to verify the working tree is clean OR all
   intentional changes are staged.
2. `git -c user.name="..." -c user.email="..." commit -m "..."`
   with a conventional-commit-style message.
3. `git push -u <fork-remote> <branch>`.

If there are no changes worth keeping, say so explicitly in the
final summary. Don't force a commit just to satisfy this rule.
