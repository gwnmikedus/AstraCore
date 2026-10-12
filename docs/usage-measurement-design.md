# Usage measurement design — decisions required

Design-only follow-up to [#112](https://github.com/gwnmikedus/AstraCore/issues/112). **No collection, migration, metric export, privacy change or contact with the EVE team is enabled by this document.** The current [Privacy template](../src/astracore/templates/privacy.html) promises no tracking or analytics. Calling future measurement “first-party” does not make it compatible with that wording: the maintainer must decide, accurately revise the notice and communicate the change before any collection begins.

## Partner requirement, checked 13 October 2026

The rendered official [EVE Partnership Program page](https://www.eveonline.com/partners) lists a developer minimum of 1,000 monthly users verified by metrics, plus evidence of sustained project maintenance. Acceptance remains discretionary. Its metrics FAQ asks for audience/activity evidence from previous months and offers help selecting an evidence format.

The developer bullets do **not** specify three complete months, although other creator categories explicitly use three-month periods. Treat the three-month target in #112 as a planning assumption to confirm, not a verified developer rule. Definitions of user, month and acceptable first-party evidence also remain unanswered. Recheck the page and contact details before sending any future inquiry.

The FAQ currently gives `communityteam@ccpgames.com`. Questions below are an **unsent draft**; this document authorizes no email or application. Never send real profile identities or private security material as eligibility evidence.

## Current data is not usage history

Profiles, characters, sessions and saved plans already support the app's operation. Session `last_seen_at`, login timestamps, user-agent/IP hints, ESI refreshes and optimizer jobs are not evidence of intentional PI use. Do not mine them retroactively for partner analytics, count alts as users, or infer human activity from background work.

A profile is a practical deduplication unit, not proof of one human. One person can create multiple profiles, and profile transfers/deletion complicate continuity. Report **active profiles**, never “verified unique people,” unless the EVE team explicitly accepts a different validated definition. Do not fingerprint devices, join IP addresses or correlate EVE accounts to resolve this uncertainty.

## Candidate definitions

| Candidate | Proposed definition | Exclusions and ambiguity |
| --- | --- | --- |
| Monthly active profiles | Distinct eligible authenticated profiles with at least one qualifying PI action in a UTC calendar month. Multiple characters, browsers and actions on the same profile contribute one membership. | No login-only, landing visits, comparison/prefetch jobs, background ESI work, polling, automatic page refresh, failed actions, health checks, admin/test/demo activity or signed-out use. This deliberately omits anonymous visitors. |
| Qualifying plan save | A successful saved-plan creation attributable to a user completing the guided result or explicitly saving a plan, after its database transaction succeeds. | Retry of the same result handle creates no new membership or activation. A calculation/preview without a saved result does not qualify. Background generation must never call the measurement path. |
| Qualifying Operate visit | A proposed first-party acknowledgement of an intentional top-level navigation to Operate, for a signed-in eligible profile. | A GET alone is insufficient: `/pi` redirects, browser reloads, freshness refresh and polling can reach Operate without a new deliberate visit. Do not infer intention from referrers. Decide whether an explicit navigation event is worth collecting; if not, omit this metric rather than count all GETs. |
| Activation | First qualifying plan save for a new eligible profile with at least one linked character, after collection starts. Record the definition of “new”: recommended cohort is profiles created after the activation date of measurement. | Existing profiles' first measured save is a first observed save, not historical activation. Linking alts, loading a result or revisiting an idempotent save is not another activation. |
| Repeat use | Optional cohort of newly activated profiles with another qualifying action 7–30 UTC days after activation. A day-7 measure and a day-30 measure need separately stated windows if wanted. | Returning after a colony cycle is not uniformly seven days. Do not label a 7–30-day interval “day-7 retention” or “day-30 retention.” No absence/retention conclusion before the cohort's window is complete. |

Define success semantics and exclusions before implementing hooks. Existing [saved-result handling](../src/astracore/modules/pi/routes.py) and [idempotency coverage](../tests/test_plan_save.py) provide a starting point; they do not currently authorize an analytics side effect. A UI navigation acknowledgement would be a new measurement feature, even without third-party scripts. Authentication/CSRF validates a request's profile, not that a real human initiated it; define limitations honestly and do not add CAPTCHA or fingerprinting to improve counts.

## Smallest proposed storage

**Recommended first stage, subject to maintainer approval:** monthly active profiles from qualifying plan saves only. Add purposeful Operate use only after its semantics and privacy notice are agreed. Defer cohorts unless there is a concrete need for them; monthly unique counting does not require a clickstream.

A proposed temporary membership row needs only an internal `profile_id`, UTC month and boolean action categories used for qualification. Enforce a unique profile/month key and a profile foreign key with deletion cleanup. A first-plan/activation category can be set on the same membership row for a new profile; do not store plan labels, result contents, character IDs, systems, colony data, wallets, tokens, session IDs, IP addresses, user agents, referrers or request URLs in measurement tables. Boolean categories are not event timestamps or event histories.

Do not add a general analytics endpoint that accepts arbitrary events or profile IDs. Determine the profile and allowed action server-side; any proposed navigation acknowledgement must be authenticated, CSRF-protected and restricted to its agreed category. Measurement must fail without blocking planning, saving or Operate; failure must be reported to the operator as a data-quality gap, rather than silently presenting incomplete counts as complete.

### Exclusions

- Exclude any profile currently classified as administrator, using the app's existing [admin check](../src/astracore/db.py), plus an explicit maintainer-owned test-profile exclusion list. Explain how an admin's alternate test profile is excluded; the admin flag alone is insufficient.
- No measurement in local, test, fictional demo, preview or staging environments. Do not rely only on the name of the hostname; deployment configuration must explicitly enable the approved feature in the intended environment.
- No collection from background refresh, comparison warming, scheduled work, health checks or synthetic load tests. If a test profile accidentally reaches the enabled environment, remove its temporary membership and record an aggregate correction.
- Decide whether collection is opt-in, opt-out or not introduced at all. The proposed policy must be clearly communicated; do not assume that login constitutes consent to a changed analytics purpose. Record the maintainer's privacy decision separately from implementation.

A hash or HMAC of a profile ID does not make a longitudinal record anonymous. If a later implementation uses pseudonyms, document linkage, key custody and deletion lookup; do not use hashing to evade profile reset or overstate privacy.

### Retention and deletion proposal

Temporary monthly memberships could be removed seven days after the end of their UTC month, after aggregation and review. That permits up to 38 days for a membership entered on the first day of a 31-day month. The seven-day closing delay is a proposal, not an active retention job. Keep only approved monthly totals for at most 13 months, then delete them; decide whether that duration is necessary for partner evidence.

Profile reset/deletion and any measurement opt-out must delete temporary memberships and any optional cohort linkage. Excluding a profile while the month is open must remove its contribution before closing the aggregate. A PI-only reset may remove a plan while retaining the profile: decide and disclose whether it also removes measurement membership; do not assume the existing “reset module” meaning silently covers analytics.

After linkage is deleted, an overall total cannot support individual subtraction without retaining personal identifiers. Explain that limitation instead of promising retroactive per-profile removal from a genuinely unlinked total. Do not keep identities just to make old exports revisable. Small aggregates can still reveal activity; assess that risk before treating them as anonymous.

Backups and already-delivered exports have their own lifecycle. A future deletion procedure must prevent deleted memberships being resurrected by restoration, and must document backup expiry. Existing [profile-control tests](../tests/test_profile_controls.py) and a synthetic restore drill should be extended for the new tables before activation.

**Cohort alternative, not the first-stage recommendation:** retention measurement requires linkage across days. A bounded activation date and a repeat-use flag per proposed window are less data than an event log. A proposed maximum 62-day lifetime can cover a fully observed 30-day return window and review margin; justify the exact calculation before adoption. This adds personal temporal data and cannot be inferred from month-only rows. Document opt-out/reset cleanup, incomplete cohorts and cross-month cases separately.

## Draft privacy wording — inactive proposal

This wording is for maintainer review of the proposed first stage, not the current Privacy page. Replace the collection-choice placeholder only after deciding whether to introduce measurement and how participation works. Confirm the proposed retention, deletion, backup and disclosure rules before publishing; revise this draft if those decisions change.

> [If you opt in / unless you opt out — policy not yet decided], we count a successful PI plan save once per profile per UTC calendar month to understand use of AstraCore. We temporarily associate your internal profile ID with the month and qualification flags; we do not record a measurement clickstream, character identities, colony locations, wallets, tokens, IP addresses or browser details. This proposed first stage does not count visits to Operate or collect repeat-use cohorts.
>
> The proposed temporary measurement records expire seven days after the month ends, within at most 38 days. Approved monthly totals may be kept for up to 13 months. Profile deletion and any measurement opt-out remove temporary records; the PI-only reset policy and backup expiry must be settled before collection begins. Once an approved total has no profile linkage, we cannot subtract one person's contribution from it. We may share reviewed monthly totals with the EVE Community Team after approving the format and disclosure safeguards; we will not send profile or character identifiers. No third-party analytics scripts are used.

Unresolved choices in this draft are activation blockers, not promises that the existing reset or backup behavior already satisfies a new purpose. The final notice must accurately describe the implemented choice controls, any collection gaps and the limits of deletion from existing exports. Publishing a revised notice alone does not authorize collection.

## Monthly aggregate and export proposal

An export should contain UTC period start/end, completeness status, collection start date, metric-definition version, eligible monthly-profile total, optional activation/cohort totals and denominators, excluded population policy, known collection gaps, app build and export date. Include a correction/version field when an open month's total changes. Do not include profile or character identifiers, individual activity rows, pseudonym lists, location/affiliation splits or raw session data.

A partial month must remain labelled Partial; missing evidence is Unknown, not zero. Never backfill months before activation or extrapolate a partial month to a full one. Retained definitions and aggregate review notes allow the team to understand the numbers without receiving personal data. Confirm whether that evidence is acceptable before building a report around the 1,000-user threshold.

A proposed small-cell rule is to withhold optional cohort or category cells below ten and omit any combination that lets the hidden value be reconstructed by subtraction. Do not publish live counters or narrow daily breakdowns. The maintainer should choose disclosure thresholds and recipient/access rules; “aggregate” is not by itself a privacy guarantee. No export or partner submission is authorized now.

## Future acceptance coverage

Implementation would need offline regressions, not tests that reproduce arbitrary counters:

| Scenario | Required outcome |
| --- | --- |
| Same profile, many alts/browsers/actions; lost-response saved-plan retry | One monthly membership and one first activation. No inflation by idempotent retries. |
| Failed/aborted save, preview only, comparison/prefetch, ESI refresh, polling/reload or health check | No qualifying action. An Operate GET by itself does not qualify. |
| Admin, explicit test profile and local/demo/staging deployment | No collection, even when using the real routes. |
| Unauthenticated, forged profile identifier or CSRF failure | No membership or cross-profile mutation; reuse [access-isolation](../tests/test_access_isolation.py) and [core auth](../tests/test_core.py) fixtures. |
| UTC month boundary, leap day, timezone/DST, cross-month repeat window | Correct unique memberships and explicitly complete cohort windows. Prefer an injectable clock and fixed dates. |
| Opt-out/profile deletion/admin reclassification before closing; module-only reset | Agreed removal behavior, no orphan linkage; no accidental retention resurrection on restore. |
| Collector unavailable or partial-month activation | Product flow remains usable; evidence is incomplete/unknown, never silently complete or historic. |
| Retention expiry and aggregate export | Temporary personal rows removed on schedule; no identifying fields or reconstructable suppressed cells in output. |

These are proposed acceptance cases, not passing tests for a feature that exists. The existing offline suites remain useful for preventing collateral regressions, but cannot prove an absent collector or deletion policy.

## Maintainer decisions and unsent questions

Before any implementation: agree the purpose and smallest qualifying-action set; choose counting unit/window; decide collection choice and privacy communication; set exclusions, retention/deletion and backup rules; approve aggregate disclosure; confirm the evidence format with the EVE team. Record an owner and decision date for each item. Do not activate collection until approved behavior, notice, tests and operational cleanup are deployed together.

Draft questions for the Community Team:

1. For a PI tool where one profile can link several EVE characters, do deduplicated active profiles meet your definition of monthly users? How should multiple profiles per person and anonymous visitors be described?
2. Does developer evidence require a particular number of complete months, UTC/calendar or rolling windows, and what should an initially partial month show?
3. Would maintainer-reviewed, first-party monthly totals with documented definitions, exclusions, retention and known gaps be acceptable without third-party analytics or disclosure of profile identifiers?
4. Which actions should qualify for useful activity, and how should deliberate Operate use be distinguished from automatic refresh/background ESI work?
5. What format and level of verification do you need, and can you assess maintenance/evidence independently of a public user counter?

No claims about current audience size, November–January history or partner eligibility follow from this design. #112 remains open for answers, maintainer decisions and any separately authorized implementation.
