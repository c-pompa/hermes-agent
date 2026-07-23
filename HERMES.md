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
