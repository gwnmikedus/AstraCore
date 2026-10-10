# Releasing AstraCore

The application ships its history in `src/astracore/release_data.json`. The running site displays that packaged version, not the latest GitHub release or a version obtained from the network. `pyproject.toml` must declare the same version. Release checks run without loading the app, environment files, or database.

## Preparing a release

1. Choose a semantic version: a patch for fixes, a minor version for compatible features, and a major version for breaking changes. Update the package version and `current_version` together.
2. Add a new entry at the beginning of `releases`, with its version, publication date in `YYYY-MM-DD`, and a short title. Do not date or describe changes as released before they are actually included.
3. Write `changes` for pilots: what changed and what it means for their operation. Put implementation notes in `technical`, and material constraints or required action in `limitations`. All three fields are lists, and may be empty individually. At least one change or technical note is required.
4. Add optional `references` as objects with a readable `label` and an issue, pull request, or commit `url` in this repository. Do not invent references before the corresponding work exists.
5. Run `python scripts/check_release.py` and the relevant tests in an isolated development or CI environment. The release checker rejects inconsistent versions, duplicate releases, invalid dates, and unsafe reference URLs.
6. Review the user-facing notes and the optional technical view, then merge the completed release. Create the matching Git tag, for example `v1.1.0`, and publish a GitHub release with notes generated from the same data:

```sh
python scripts/check_release.py --tag v1.1.0
python scripts/check_release.py --notes 1.1.0 > release-notes.md
```

Do not publish releases for every individual commit. Versioned releases represent completed, reviewed changes. The 1.0.0 entry is the existing package baseline; its original publication date was not recorded and must remain unspecified.

## Deploying a release

Deploy code and packaged release metadata from the same tag, including any required migrations and assets, and restart the application as appropriate. Optionally set `ASTRACORE_COMMIT` in the process environment to the full deployed commit SHA; only a valid hexadecimal commit identifier is displayed. This is deployment metadata, not a credential. Do not set it to the current branch tip unless that exact commit is deployed.

Verify the footer version, release page, and running behavior after deployment. Notes on disk do not prove that an existing process has loaded the new release. The site does not fetch GitHub releases to determine its identity, so a newer GitHub publication cannot relabel an older running deployment.

## Reader experience

Plain-language changes and limitations are visible to everyone. Technical details are collapsed by default, and the release page offers an explicit switch that remembers the reader’s choice in browser storage. With JavaScript unavailable, native disclosure controls still allow readers to opt in. There are no automatic release banners or modal interruptions.
