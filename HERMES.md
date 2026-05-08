# Project rules: cpompa/hermes-agent fork

## When working in a git worktree (`hermes -w` mode)

Before finishing each task or ending the session, commit any
uncommitted changes on the current branch and push to `gitlab`
(or `origin` if `gitlab` is absent). The worktree is wiped on
session exit — uncommitted work is lost otherwise.

Standard finishing sequence:

1. `git status` to verify the working tree is clean OR all
   intentional changes are staged.
2. `git -c user.name="..." -c user.email="..." commit -m "..."`
   with a conventional-commit-style message.
3. `git push -u <remote> <branch>` (use `gitlab` for this fork's
   personal-fork remote; `origin` points at upstream NousResearch
   and is read-only).

If there are no changes worth keeping, say so explicitly in the
final summary. Don't force a commit just to satisfy this rule.
