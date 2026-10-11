# Versions, releases and deployment

This is how AstraCore is versioned, merged, released and deployed. It applies to the maintainer, contributors and coding agents alike.

## In short

- **Versions are `0.MINOR.PATCH`** while AstraCore is in preview. Moving to `1.0.0` is a separate decision by the maintainer.
- **`main` is production.** Whatever is on `main` is, or is about to be, the running site. Merge only what you're ready to deploy, and deploy straight after merging.
- **Only the maintainer ([@gwnmikedus](https://github.com/gwnmikedus)) merges into `main`.** Everyone else, coding agents included, opens a pull request and stops there.
- **Every merged pull request is a patch** (`0.1.1`, `0.1.2`, …). Patches have no release notes; their Conventional Commit messages are the changelog.
- **A minor release** (`0.1.x` → `0.2.0`) is the curated update. It gets written release notes (the site's *What's new* page), a `v0.2.0` tag and a GitHub Release.

## Version numbers

AstraCore follows [Semantic Versioning](https://semver.org/) in its `0.y.z` form, which SemVer reserves for initial development: anything may still change, and the minor number marks meaningful steps.

| Part | Example | Meaning | Who sets it |
|---|---|---|---|
| MINOR | `0.1` → `0.2` | A curated release: a set of changes pilots should hear about, or a breaking change | The maintainer, in a release pull request |
| PATCH | `0.2.0` → `0.2.7` | The seventh pull request merged into `main` since `v0.2.0` | Nobody: it's derived from git |

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
5. **The maintainer squash-merges** and then deploys (see below). Nobody else merges, and agents never merge or push to `main` unless the maintainer explicitly asks for that in the current session.

Do not change the version or `release_data.json` in a regular pull request.

## Deploying (main = production)

After merging, the maintainer, or an agent the maintainer explicitly asked to deploy, updates production from `main`:

```sh
git checkout main && git pull --ff-only --tags
./astracore restart --prod
```

Then check that `/healthz` responds and that the footer shows the expected version (`v0.2.<n>`, where *n* is the number of merged pull requests since `v0.2.0`). The release page links those commits.

If a merged change can't be deployed, revert it on `main` with a new pull request rather than leaving `main` ahead of production.

## Making a minor release

1. Open a release pull request, e.g. `chore(release): 0.2.0`, that:
   - sets `version = "0.2.0"` in `pyproject.toml` and `current_version` in `release_data.json`;
   - adds a new first entry to `releases`:
     - `version` and `date` (`YYYY-MM-DD`, the day it's deployed) and a short `title`;
     - `changes`: what pilots will notice, gathered from the merged pull requests since the last release;
     - `limitations`: what they need to know or do;
     - `technical`: implementation notes, collapsed by default on the site;
     - optional `references` to issues, pull requests or commits in this repository.
2. Run `python scripts/check_release.py` and the test suites.
3. The maintainer merges it, then tags **that merge commit** and publishes the GitHub Release from the same data:

   ```sh
   git checkout main && git pull --ff-only
   python scripts/check_release.py --tag v0.2.0
   git tag -a v0.2.0 -m "AstraCore 0.2.0" && git push origin v0.2.0
   python scripts/check_release.py --notes 0.2.0 > release-notes.md
   gh release create v0.2.0 --title "AstraCore 0.2.0 · <title>" --notes-file release-notes.md
   ```

4. Deploy as above. The footer now reads `v0.2.0`, and the next merged pull request becomes `0.2.1`.

Tag only minor releases, never patches, and never move or reuse a published tag.

## Who can merge

`main` is protected, including for administrators:

- pull requests only, with the four required checks, an up-to-date branch and resolved conversations;
- linear history and squash merges only;
- no force pushes and no deletion.

The repository is personal, and the maintainer is its only collaborator, so only the maintainer can merge or push. Anyone can propose changes through a pull request from a fork; that's how open contribution works and it can't be turned off. Merging stays with the maintainer. `.github/CODEOWNERS` records the maintainer as the owner of everything, so every pull request requests their review.

Coding agents act through the maintainer's GitHub account, so GitHub can't tell them apart from the maintainer. The rule that agents don't merge or deploy unless asked is therefore part of [AGENTS.md](../AGENTS.md), not a GitHub setting.

## Reader experience

Plain-language changes and limitations are visible to everyone. Technical details are collapsed by default, and the release page has an explicit switch that remembers the reader's choice in browser storage. With JavaScript unavailable, native disclosure controls still let readers opt in. The release page shows the running patch version and links the commits since the last minor release. There are no automatic release banners or modal interruptions.
