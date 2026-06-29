# Project rules: cpompa/hermes-agent fork

## Remote naming is per-machine — check before you push

This fork has two remotes, but they are **named differently on each
machine**. Always run `git remote -v` first; never assume.

| Machine                              | gitlab.cpompa.com (our fork) | GitHub NousResearch (upstream) |
| ------------------------------------ | ---------------------------- | ------------------------------ |
| **mini** (gateway, `~/.hermes/hermes-agent`) | `origin`             | `upstream`                     |
| **Mac** (`~/.hermes/hermes-agent`)   | `gitlab`                     | `origin`                       |

Push fork changes to **our fork remote** (the gitlab one for this
machine). The **GitHub/NousResearch remote is upstream and read-only.**

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
(see the remote table above — `origin` on the mini, `gitlab` on the Mac).
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
