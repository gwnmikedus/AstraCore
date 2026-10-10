# Contributing to AstraCore

Thanks for helping fellow capsuleers. Bug reports, practical ideas, documentation and code contributions are welcome at [gwnmikedus/AstraCore](https://github.com/gwnmikedus/AstraCore).

## License and contributions

Read [LICENSE](LICENSE), [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) first. AstraCore's original software is **source available under PolyForm Noncommercial 1.0.0**, not an OSI-approved open-source license. The terms permit noncommercial use, changes and distribution; they do not grant commercial rights.

By submitting original code or documentation for inclusion, you agree to provide it under the same PolyForm Noncommercial 1.0.0 license. You retain copyright in your work. Only submit material you are entitled to contribute, and identify any third-party material and its license explicitly. Existing third-party licenses must be preserved.

## Report a bug or suggest an idea

Search [existing issues](https://github.com/gwnmikedus/AstraCore/issues) first. Use the bug report or feature request form and describe the user problem, rather than only a preferred implementation. For bugs, include reproducible steps, expected and actual behavior, the app version and browser. Estimates and market snapshots should include their date and assumptions.

Issues and pull requests are public. Remove character names, colony locations, wallet or inventory details unless you intentionally want to publish them. Never include EVE tokens, credentials, session cookies, database files, private logs or `.env` files. Use fake data or a minimal anonymized example. Report security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

Suggestions start under review. Submitting an idea does not commit it to the roadmap or promise a delivery date.

## Set up a development copy

Use a separate checkout and a separate data directory. Follow the [README quick start](README.md#quick-start-fresh-clone-local-mode), copy `docs/env.example` to `.env.local`, and register your own EVE development application and callback. Do not copy the project's production secrets or database into your checkout. The Mac launchers are optional; the Python module can run directly on another supported operating system.

Install the test extras with `python -m pip install -e ".[test]"`. The test fixture creates temporary data and supplies fake credentials. Tests must not contact live character endpoints or depend on a real pilot's account.

## Make a focused change

Create a branch from `main`, keep the change small enough to review, and follow the existing Python, vanilla JavaScript and Jinja patterns. Use shared formatting, icons, asset helpers and brand tokens. Keep module-specific behavior in its module. Do not add secrets, hardcoded personal identifiers, real account fixtures or unnecessary dependencies.

For a behavior change, add a useful regression test. Verify the affected flow on the project's designated test deployment, including narrow screens where relevant. Do not restart or deploy the shared production instance as part of a contribution. Repository owners' local workflow instructions take precedence over these general development notes.

The CI checks run in isolated GitHub-hosted jobs:

```bash
python -m pytest -q tests
node --test tests/test_ui.cjs
python scripts/check_release.py
```

If you cannot run a check, state that in the pull request; do not report it as passing.

## Open a pull request

Explain the problem and resulting behavior, link the related issue, and describe validation and any remaining limitations. Use Conventional Commits for commit messages, for example `fix: keep factory restocks within storage capacity`. Include understandable release notes for changes pilots should know about, with implementation details kept separate. See [the release workflow](docs/releases.md).

Do not bump the application version in every pull request. Maintainers group changes into a release and keep the package version, release entry, tag and GitHub release consistent. Public source, contribution and release pages do not automatically remove the hosted service's invite gate.
