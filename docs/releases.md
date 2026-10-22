# Versions, releases and deployment

This is how AstraCore is versioned, merged, released and deployed. It applies to the maintainer, contributors and coding agents alike.

## In short

- **Versions are `0.MINOR.PATCH`** while AstraCore is in preview. Moving to `1.0.0` is a separate decision by the maintainer.
- **`main` is the integration branch; production runs one pinned commit of it.** Merging doesn't deploy anything. The maintainer picks the commit that goes live with `./astracore deploy`, and production stays on it until the next deploy or a `rollback`. Small fixes can pile up on `main` and ship together.
- **Only the maintainer ([@gwnmikedus](https://github.com/gwnmikedus)) merges into `main` and deploys.** Everyone else, coding agents included, opens a pull request and stops there.
- **Every merged pull request is a patch build** (`0.1.1`, `0.1.2`, …), numbered automatically. Builds have no release notes; their Conventional Commit messages are the changelog. The footer shows the build production runs.
- **A minor release** (`0.1.x` → `0.2.0`) is the curated update. It gets written release notes (the site's *What's new* page), a `v0.2.0` tag and a GitHub Release, and it describes what has actually been deployed.

## Version numbers

AstraCore follows [Semantic Versioning](https://semver.org/) in its `0.y.z` form, which SemVer reserves for initial development: anything may still change, and the minor number marks meaningful steps.

| Part | Example | Meaning | Who sets it |
|---|---|---|---|
| MINOR | `0.1` → `0.2` | A curated release: a set of changes pilots should hear about, or a breaking change | The maintainer, in a release pull request |
| PATCH | `0.2.0` → `0.2.7` | The build: the seventh pull request merged into `main` since `v0.2.0`. Production may run an earlier build than `main`'s tip | Nobody: it's derived from git |

The patch number is never written in a file. At startup the app runs `git describe --tags --match v<minor>` and counts the commits on `main` since the minor release's tag. `main` only takes squash merges, so that's one commit per pull request. Without git or the tag, the app shows the minor version itself, for example `0.2.0`. This works like [setuptools-scm](https://setuptools-scm.readthedocs.io/) and needs no version-bump commits, so pull requests never conflict over the version.

Only the minor version lives in files, and the `Release metadata` check keeps them consistent:

- `pyproject.toml` → `version = "0.2.0"`
- `src/astracore/release_data.json` → `current_version` and the newest entry in `releases`

Both must end in `.0`. The checker rejects patch versions in either file.

Builds before 0.1.0 were numbered 1.0 to 1.2.4 during early development. On 2026-10-11 those GitHub releases and tags were replaced by `v0.1.0`; the commit history keeps the details.

## Pull requests and merging

1. Work on a short-lived branch from the latest `main`: `feat/…`, `fix/…`, `docs/…` or `chore/…`, and `codex/…` for coding agents. Use one branch and one pull request per issue.
2. Use a Conventional Commit title, for example `fix: keep factory restocks within storage capacity`. The squash commit's title becomes the patch changelog entry, so write it for a reader.
3. Fill in the pull request template, including a short user-facing note when pilots would notice the change. Those notes are collected at the next minor release.
4. The required checks (`Python 3.9`, `Python 3.13`, `Browser helper unit tests`, `Release metadata`) must pass, the branch must be up to date with `main` and conversations must be resolved.
5. **The maintainer squash-merges.** Deploying is a separate step (see below), done whenever the maintainer decides. Nobody else merges or deploys, and agents never merge, push to `main` or deploy unless the maintainer explicitly asks for that in the current session.

Do not change the version or `release_data.json` in a regular pull request.

## Deploying (a pinned commit)

Production never runs the maintainer's working checkout. It runs its own git worktree next to it (`~/Eve-production` for `~/Eve`), detached at exactly the deployed commit. Branches, pulls and edits in the working checkout, by the maintainer or any agent, never reach the live site. Env files, `data/`, logs and the virtualenv stay in the working checkout (`ASTRACORE_HOME`).

```sh
./astracore deploy            # pin production to the tip of origin/main and restart it
./astracore deploy 1a2b3c4    # or to any earlier commit on origin/main
./astracore rollback          # back to the previously deployed commit
./astracore status            # shows the running build and how many merged commits aren't deployed yet
```

`deploy` fetches, refuses commits that aren't on `origin/main`, takes a database backup, runs migrations, restarts, and waits for `/healthz`. If the new build doesn't come up, it puts the previous build back by itself. Every deploy and rollback is a line in `data/deploys.log` (time, commit, build, kind). `start|restart --prod` restarts whatever is pinned.

After a deploy, check that the footer shows the expected build (`v0.2.<n>`). The release page links those commits.

The maintainer can do all of this, and the merging and release steps on this page, from **AstraCore Control.app** (see the README): it runs the same `./astracore`, `git` and `gh` commands, asks before each change and shows their output. Agents use the commands, and only when the maintainer asks.

- Hand edits in the production checkout are flagged by `status` and discarded by the next deploy. Fix things through a pull request and deploy that.
- A rollback doesn't undo database migrations. The backup taken before each start is in `data/backups/production/`.
- If a deploy changes dependencies, `deploy` says so; install them with `.venv/bin/pip install -r ~/Eve-production/requirements.txt`.
- A merged change that turns out wrong doesn't have to be deployed. Revert it on `main` with a new pull request before the next deploy.

## Making a minor release

1. Open a release pull request, e.g. `chore(release): 0.2.0`, that:
   - sets `version = "0.2.0"` in `pyproject.toml` and `current_version` in `release_data.json`;
   - adds a new first entry to `releases`:
     - `version` and `date` (`YYYY-MM-DD`, the day it's deployed) and a short `title`;
     - `changes`: what pilots will notice, gathered from the merged pull requests since the last release;
     - `limitations`: what they need to know or do;
     - `technical`: implementation notes, collapsed by default on the site;
     - optional `references` to issues, pull requests or commits in this repository.
       Link issues as `…/issues/<n>`: pilots who opted in to credit on a report for that issue are thanked as *Reported by* on the What's new page.
2. Run `python scripts/check_release.py` and the test suites.
3. The maintainer merges it, then tags **that merge commit** and publishes the GitHub Release from the same data:

   ```sh
   git checkout main && git pull --ff-only
   python scripts/check_release.py --tag v0.2.0
   git tag -a v0.2.0 -m "AstraCore 0.2.0" && git push origin v0.2.0
   python scripts/check_release.py --notes 0.2.0 > release-notes.md
   gh release create v0.2.0 --title "AstraCore 0.2.0 · <title>" --notes-file release-notes.md
   ```

4. Deploy that merge commit (`./astracore deploy`). The footer now reads `v0.2.0`, and the next merged pull request becomes `0.2.1`.

Tag only minor releases, never patches, and never move or reuse a published tag.

## Issue labels

Every issue has one **type** label and, while it's open, one **status** label. The Community page reads them.

| Label | Meaning |
|---|---|
| `type:bug` | Something doesn't work as intended (shown as *Bug*) |
| `type:idea` | An improvement or new feature (shown as *Idea*) |
| `status:under-review` | Open: new, not yet triaged or decided |
| `status:planned` | Open: accepted and planned, work not started |
| `status:in-progress` | Open: someone is working on it |
| `status:released` | Closed and live in production (set by `./astracore deploy`) |
| `source:platform` | Submitted through the site's feedback form |
| `roadmap` | A roadmap item (shown as *Planned* while open) |

- Use the `type:` labels, not GitHub's default `bug` or `enhancement`: the Community page doesn't recognise those.
- When an issue closes, its state and reason (*completed* or *not planned*) are its status. The `Issue labels` workflow removes `status:under-review`, `status:planned` and `status:in-progress` by itself, including when a merged pull request closes the issue.
- **Released means live.** `./astracore deploy` adds `status:released` to the issues closed by the pull requests it puts live, and a rollback takes it off again for what it removes. So *Released* on the Community page means pilots can use it now; merged but not deployed shows as *Completed*. Issues that pull requests only mention and that are closed by hand are caught too: each deploy labels an issue closed as completed once every merged pull request that references it is live, and names any closed without a merged pull request for a check by hand. Prefer `Closes #n` all the same. If GitHub can't be reached during a deploy, it says so; catch up with `./astracore mark-released <from> [to]`, or `./astracore mark-released` alone for the closed-by-hand sweep against what production runs now.
- The Roadmap groups work by these labels: *Now* = `status:in-progress` and closed-but-not-yet-deployed, *Next* = `status:planned` or `roadmap`, *Exploring* = curated directions in `community.py` without an issue. `status:under-review` stays in the issue list until it's decided; released and closed work folds into *Released*. A curated direction moves lanes once a `roadmap` issue carries its `<!-- astracore-roadmap:<slug> -->` marker.
- Minor releases (`0.x.0`) don't change labels: they're the curated notes on the *What's new* page.
- Reopening an issue: give it an open status label again.
- Pilots see their own reports in the same words as the roadmap: *Under review*, *Planned*, *Being built*, *Going live soon* (closed as completed, not yet deployed), *Live* (`status:released`) and *Not planned for now* (closed for any other reason; they're pointed to the reply on GitHub). Leave a short reply when you close an issue as not planned.

## Who can merge

`main` is protected, including for administrators:

- pull requests only, with the four required checks, an up-to-date branch and resolved conversations;
- linear history and squash merges only;
- no force pushes and no deletion.

The repository is personal, and the maintainer is its only collaborator, so only the maintainer can merge or push. Anyone can propose changes through a pull request from a fork; that's how open contribution works and it can't be turned off. Merging stays with the maintainer. `.github/CODEOWNERS` records the maintainer as the owner of everything, so every pull request requests their review.

Coding agents act through the maintainer's GitHub account, so GitHub can't tell them apart from the maintainer. The rule that agents don't merge or deploy unless asked is therefore part of [AGENTS.md](../AGENTS.md), not a GitHub setting.

## Reader experience

Plain-language changes and limitations are visible to everyone. Technical details are collapsed by default, and the release page has an explicit switch that remembers the reader's choice in browser storage. With JavaScript unavailable, native disclosure controls still let readers opt in. The release page shows the running patch version and links the commits since the last minor release. There are no automatic release banners or modal interruptions.
