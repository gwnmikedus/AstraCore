# Security policy

## Report vulnerabilities privately

Use [GitHub's private vulnerability reporting](https://github.com/gwnmikedus/AstraCore/security/advisories/new), through **Security → Report a vulnerability** in this repository. Do not open a public issue with exploit details, credentials or another pilot's data. If private reporting is temporarily unavailable, do not publish the sensitive report in a normal issue.

Include the affected version or commit, a minimal reproduction using accounts you control, expected impact and any suggested mitigation. Do not attach production databases, raw ESI responses, refresh/access tokens, session cookies or unredacted logs. Test only your own deployment and accounts; do not probe the shared service or EVE infrastructure without explicit authorization.

## Supported versions

Security fixes target the latest published AstraCore release. Older versions may require an upgrade; there is no guaranteed response time or long-term support schedule. Maintainers will coordinate a fix and public disclosure with the reporter where practical.

## Deployment secrets

Every deployment needs its own EVE application credentials, encryption key, session secret and any hosting credentials. Keep them outside Git and do not share them with contributors. A public repository does not make encrypted runtime databases safe to publish. Revoke and rotate exposed credentials before considering any history cleanup; deleting a file in a later commit does not remove earlier copies.
