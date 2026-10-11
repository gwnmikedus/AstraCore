# Working on AstraCore as a coding agent

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/releases.md](docs/releases.md) first. These rules apply to every agent (Claude, Codex or any other) and to every session.

## Never without the maintainer's explicit request in this session

- Merging a pull request, or pushing to `main`. Agents use the maintainer's GitHub account, so GitHub won't stop you: this rule does.
- Deploying, rolling back or restarting production (`./astracore deploy|rollback`, `./astracore start|restart --prod`). Production runs a pinned commit from its own checkout (`~/Eve-production`); merging doesn't deploy.
- Editing anything in the production checkout (`~/Eve-production`). It's managed only by `./astracore deploy`.
- Creating or moving tags, publishing or deleting GitHub Releases, or changing repository settings or branch protection.
- Changing the version in `pyproject.toml` or `src/astracore/release_data.json`. That only happens in a minor release pull request.

An earlier session's permission doesn't carry over.

## How to work

- **Several agents may work in this repository at once.** Don't edit another checkout. Work in your own git worktree on a branch from the latest `origin/main`: `codex/<topic>` (or `feat/…`, `fix/…`), one branch and one pull request per issue.
- **Commits:** Conventional Commits. The squash commit title is the patch changelog, so make it readable.
- **Tests must not touch the network.** Run:
  - `python -m pytest -q tests`, also once with `HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9` to prove nothing reaches the network;
  - `node --test tests/test_*.cjs`;
  - `python scripts/check_release.py`.
- **Verify user-visible changes in a browser** against a local copy. Never use production or another session's data. Say what you didn't verify.
- **Pull requests:**
  - follow `.github/PULL_REQUEST_TEMPLATE.md`;
  - link the issue (`Closes #n`);
  - give a short user-facing note for the next minor release when pilots would notice the change.
- **Issues:**
  - mark the issue you're working on `status:in-progress`;
  - post follow-ups you find as new issues labelled `type:idea` + `status:under-review`, and don't fix unrelated things in the same pull request.
- **Product rules for AstraCore PI:**
  - never author or generate in-game PI templates; only refer to DalShooth templates;
  - keep the guided wizard the main flow;
  - no secrets, real pilot data or account fixtures in commits.
