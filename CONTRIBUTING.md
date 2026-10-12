# Contributing to AstraCore

Thanks for helping fellow capsuleers. Bug reports, practical ideas, documentation and code contributions are welcome at [gwnmikedus/AstraCore](https://github.com/gwnmikedus/AstraCore).

## License and contributions

Read [LICENSE](LICENSE), [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) first. AstraCore's original software is **source available under PolyForm Noncommercial 1.0.0**, not an OSI-approved open-source license. The terms permit noncommercial use, changes and distribution; they do not grant commercial rights.

By submitting original code or documentation for inclusion, you agree to provide it under the same PolyForm Noncommercial 1.0.0 license. You retain copyright in your work. Only submit material you are entitled to contribute, and identify any third-party material and its license explicitly. Existing third-party licenses must be preserved. Record any new data source or integration in [docs/third-party.md](docs/third-party.md).

## Report a bug or suggest an idea

Search [existing issues](https://github.com/gwnmikedus/AstraCore/issues) first. Use the bug report or feature request form and describe the user problem, rather than only a preferred implementation. For bugs, include reproducible steps, expected and actual behavior, the app version and browser. Estimates and market snapshots should include their date and assumptions.

Issues and pull requests are public. Remove character names, colony locations, wallet or inventory details unless you intentionally want to publish them. Never include EVE tokens, credentials, session cookies, database files, private logs or `.env` files. Use fake data or a minimal anonymized example. Report security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

Suggestions start under review. Submitting an idea does not commit it to the roadmap or promise a delivery date.

## Contributor recognition

The site's introduction and [credits page](https://astracore.hoppyhome.nl/credits#contributors) showcase public
GitHub contributor profiles alphabetically. The list follows GitHub's repository contributor data and may
take a few hours to reflect merged work. Use a commit author email associated with your GitHub account;
GitHub's private `noreply` email works too. We do not publish anonymous commit names or email addresses,
and bot accounts are omitted. You retain copyright in your own contributions.

You can opt in to showing an EVE character next to your GitHub identity. Ask for the link from your
GitHub account and provide the public character name and ID; maintainers verify the public EVE identity
before adding it to `src/astracore/contributor_identities.json` in a reviewed pull request. The directory
uses GitHub's numeric account ID so a renamed or reassigned login cannot give someone else your character
credit. It supports multiple characters per contributor. These are public credits, not an account link or
proof of in-game permissions. AstraCore never discovers contributor characters from private profiles.
To change or remove a published character credit, request a directory update through the same process.

Testing, bug reports, ideas and documentation feedback help just as much, even when they do not appear in
GitHub's commit-based contributor list. They are acknowledged alongside the showcase. If a credit is missing,
open an issue with the public name and contribution you would like credited; do not post private identities.

## Set up a development copy

Use a separate checkout and a separate data directory. Follow the [README quick start](README.md#quick-start-fresh-clone-local-mode), copy `docs/env.example` to `.env.local`, and register your own EVE development application and callback. Do not copy the project's production secrets or database into your checkout. The Mac launchers are optional; the Python module can run directly on another supported operating system.

Install the test extras with `python -m pip install -e ".[test]"`. The test fixture creates temporary data and supplies fake credentials. Tests must not contact live character endpoints or depend on a real pilot's account.

## Make a focused change

Create a branch from `main`, keep the change small enough to review, and follow the existing Python, vanilla JavaScript and Jinja patterns. Use shared formatting, icons, asset helpers and brand tokens. Keep module-specific behavior in its module. Do not add secrets, hardcoded personal identifiers, real account fixtures or unnecessary dependencies.

Use a short-lived branch named `feat/<topic>`, `fix/<topic>`, `docs/<topic>` or `chore/<topic>`; coding-agent branches use `codex/<topic>`. Outside contributors should open a pull request from their fork. Keep personal editor and agent configuration, local launchers and private reviews out of commits; use `.git/info/exclude` or your global Git ignore file for those local rules. The shared rules for coding agents are in [AGENTS.md](AGENTS.md).

For a behavior change, add a useful regression test. Verify the affected flow on the project's designated test deployment, including narrow screens where relevant. Do not restart or deploy the shared production instance as part of a contribution. Repository owners' local workflow instructions take precedence over these general development notes.

The CI checks run in isolated GitHub-hosted jobs:

```bash
python -m pytest -q tests
node --test tests/test_*.cjs
python scripts/check_release.py
```

If you cannot run a check, state that in the pull request; do not report it as passing.

## Open a pull request

`main` is the integration branch; production runs a commit of it that the maintainer deploys (see [docs/releases.md](docs/releases.md)). Only the maintainer ([@gwnmikedus](https://github.com/gwnmikedus)) merges into `main` and deploys. Everyone else, coding agents included, opens a pull request and stops there.

`main` is protected, including for repository administrators. All changes go through a pull request with:
- the branch up to date;
- resolved review conversations;
- successful `Python 3.9`, `Python 3.13`, `Browser helper unit tests` and `Release metadata` checks.

Direct pushes, force pushes and deletion of `main` are blocked. Do not skip required checks or change protection settings to merge a failing pull request. The maintainer deploys straight after merging; see [Versions, releases and deployment](docs/releases.md).

Maintainers merge using squash merge and a Conventional Commit title. GitHub deletes merged branches automatically. There is no mandatory approval count while the project has a sole maintainer; maintainers should obtain another contributor's review when available, especially for authentication, privacy or licensing changes. Revisit the approval requirement when there are multiple active maintainers.

Explain the problem and resulting behavior, link the related issue, and describe validation and any remaining limitations. Use Conventional Commits for commit messages, for example `fix: keep factory restocks within storage capacity`. The squash commit title is the changelog entry for that patch, so write it for a reader. When pilots would notice the change, add a short user-facing note to the pull request; the maintainer collects these into the next minor release's notes.

AstraCore uses `0.MINOR.PATCH` versions. Every merged pull request is a patch, numbered automatically from git (`0.1.1`, `0.1.2`, …). Release notes, tags and GitHub Releases are only made for minor releases (`0.2.0`). Never change the version or `release_data.json` in a regular pull request. Public source, contribution and release pages do not automatically remove the hosted service's invite gate.
