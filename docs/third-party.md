# Integration register

Every outside source AstraCore reads or shows, what we use it for, on what basis, and how it is
credited. Keep this file up to date in the same pull request that adds or changes an integration.

Rules for every source:

- A public download is not permission to redistribute or relicense someone else's work. Record the
  basis here; when it is unclear, ask the owner and link to their files instead of copying them.
- Never forward a pilot's EVE tokens or data to another service.
- New providers need a demonstrated PI problem they solve, the provider's own terms, and (when they
  issue one) an app-specific key.
- Credit sources where their results appear, not only on the Credits page.

## Other community tools: talk first, then link or integrate

Before AstraCore builds something another community tool already does well, we talk to its author first.
We'd rather link to it, integrate with its author's blessing, or leave it to them than build a copy that
takes users away from people who give their time to the community.

- PI alerts and reminders: Industrial EVE, Planets in Space, eve-pi (pi.calli.fi), PIM. Contact them before
  the roadmap's reminders direction becomes work.
- Appraisal and prices: Janice, EVE Ref, Fuzzwork. Link item names rather than copying their features.
- Fittings: Pyfa, EVE Workbench, Eveship.fit. Link rather than build a fit editor.
- Kills and corp auth: zKillboard, Alliance Auth, SeAT. Link only.

Tool authors can ask for their entry to be corrected or removed through a GitHub issue. Verify a tool is
alive and its link works before listing it on the Community page.

Status: **ok** (basis documented), **open** (needs an answer from the owner), **review** (check the
terms again).

---

## EVE Online ESI and EVE SSO: ok

| | |
|---|---|
| Owner / contact | Fenris Creations (formerly CCP Games), developers.eveonline.com |
| URLs | `https://esi.evetech.net`, `https://login.eveonline.com`, `https://images.evetech.net` |
| Basis | EVE Developer License Agreement (developers.eveonline.com/license-agreement); the copyright notice in the site footer |
| What we read | Public universe, market, sovereignty and route data; per character, with the pilot's consent, only the scopes listed on What we read (`modules/pi/module.py`) |
| Version | `X-Compatibility-Date` pinned in `esi/client.py` (`COMPATIBILITY_DATE`) |
| Refresh | Respects each response's `Expires`; ETag revalidation; error-limit back-off (`esi/client.py`) |
| Private fields | Character data is personal: cached per character, deleted with the character or profile, dropped once expired |
| Attribution | Footer licence notice; What we read; Credits |
| On failure | Pages fall back to the last stored copy and say so; nothing is valued at 0 because a fetch failed |
| Removal | A pilot removes a character or resets the profile; tokens are revoked at EVE |

## Fuzzwork static data export: ok

| | |
|---|---|
| Owner / contact | Steve Ronuken, fuzzwork.co.uk |
| URL | `https://www.fuzzwork.co.uk/dump/latest/csv/<table>.csv` (`modules/pi/static_data/sde_loader.py`) |
| Basis | Public conversion of CCP's static data export; the SDE itself falls under the EVE Developer License. Credited as a courtesy |
| What we use | Planet schematics, item names, volumes, tiers and groups needed for PI |
| Stored | Source CSVs and derived recipes share one runtime database cache; legacy files in the ignored data directory are retained as fallback. Not committed |
| Refresh | The two PI CSV tables are checked at most once every 24 hours using HTTP validators. Both are validated and confirmed unchanged during the fetch before one cache write publishes their recipes. A forced load requests both tables anew; failed checks retry after an hour |
| Provenance | The shared `pi_data_v1` cache records each table's URL basis, ETag, Last-Modified and SHA-256, plus successful check/load times and the latest failed attempt. `sde_loader.source_info()` exposes these diagnostics without raw CSV text; there is no claim to know the dump's global revision number |
| Attribution | Credits page and THIRD_PARTY_NOTICES.md |
| On failure | The last validated recipes keep working, with a logged warning and stale/error diagnostics. Legacy local CSVs are a fallback when no derived cache exists; their age is unknown. If no valid copy exists, loading fails. CCP's official SDE is an alternative source, not an automatic fallback |

## DalShooth PI templates: open

| | |
|---|---|
| Owner / contact | DalShooth, github.com/DalShooth/EVE_PI_Templates |
| URLs | GitHub tree API and raw files (`modules/pi/static_data/dalshooth.py`) |
| Basis | **Not settled.** The repository has no licence file. Permission to bundle the templates in `/pi/export/templates.zip` is being asked for in #71 |
| What we use | Template layouts (structure counts, planet type, Command Center level) to plan colonies; AstraCore never authors or generates templates |
| Attribution | Credits page, home page, and a link to each template's source file on plan rows |
| Feedback upstream | Template issues the planner finds (planet type mismatch, CCU level) go back to the repository as issues (#71) |
| Until settled | Prefer linking to the files on GitHub over redistributing copies |

## VOC Hauling: review

| | |
|---|---|
| Owner / contact | United East-Indian Compagnie, vochauling.com |
| URLs | `https://vochauling.com/` (published courier tariff), `https://buyback.vochauling.com/` (link only) |
| Basis | Published service information, read from the public tariff page; buyback terms are admin settings. Their names and published service details remain theirs (THIRD_PARTY_NOTICES.md) |
| What we use | Courier routes, minimum fees and rates to price couriers; the buyback percentage for P2+ |
| Refresh | Tariff page is re-read periodically (`voc.refresh_routes`); quotes show the tariff's date |
| Attribution | Named wherever a VOC route, quote or buyback is shown; a quote is not a booking or a guarantee |
| Open points | Confirm VOC is happy with the tariff being read automatically; make other couriers possible (#73) |

## GitHub: ok

| | |
|---|---|
| Owner | GitHub, Inc. |
| URLs | `https://api.github.com` (issues, labels, contributors), `https://avatars.githubusercontent.com` |
| Basis | GitHub API terms; the AstraCore repository's own issues |
| What we use | Roadmap and issue status for the Community page; publishing feedback the pilot confirmed; contributor profiles for Credits |
| Private fields | Feedback is published only after the pilot previews and confirms it; no identity, tokens or EVE data are attached |
| Attribution | Links back to each issue and contributor profile |

## Links only (no data read)

| Source | Where | Note |
|---|---|---|
| EVE developer docs (extraction formula) | `modules/pi/static_data/extraction.py` | Formula source, credited in the code |
| Reddit thread on PI tools | Community roadmap research link | Link only |
| Other community tools | Community hub (#72, #108) | Neutral links; tool authors can ask for edits |
