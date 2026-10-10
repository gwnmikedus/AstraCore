# PI planner review notes

This is an anonymized record of the 2026-10-10 review. Personal character names, skills, inventories and operating locations have been removed from the current document. Earlier committed versions remain in Git history; this cleanup does not erase them. The original review is retained locally in the ignored data directory.

## Follow-up areas

- Validate estimated extraction yields against in-game production before relying on income forecasts. Use the official extraction formula and keep assumptions visible.
- Model shared deposits as an explicit estimate, rather than treating multiple colonies as independent full-yield resources.
- Apply the selling character's skills and destination-specific fees consistently.
- Distinguish quoted prices, immediate order depth and realistic sell-through; price alone is not sufficient to choose a market.
- Reconcile plan income with the selling plan, including held inventory, customs taxes and courier grouping.
- Check template command center levels, planet adaptation, links and buffer capacity before presenting a colony as ready to build.
- Keep extractor restarts, factory restocks, planet pickups and market shipment schedules separate.
- Provide a practical first-build checklist, startup costs and a command center shopping list.
- Avoid treating any existing colony as proof that it matches the proposed layout and product.
- Show contracts, stock and sales in meaningful operational states; unresolved structure access must stay visible.

## Validation guidance

Compare both source arithmetic and the actual rendered result. Use fake or anonymized character data in shared examples. Test profile isolation, login and scope transitions, revocation, CSRF, session flags, migrations, planner concurrency and changed production rules in isolated fixtures. Verify EVE login and template placement separately in a controlled environment.

These notes are historical observations, not a claim that the current application has passed new tests or that the remaining work is complete. Current release notes and tracked issues are the maintained record of changes and planned work.
