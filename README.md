# Forge model catalog

Weekly, keyless model metadata updates. No Forge app source, athlete data,
conversations, provider credentials, or inference calls. No API keys to fund.
The public repository uses standard GitHub-hosted Linux runners.

## Automatic operation

Every Monday at 06:23 UTC, the workflow reads official OpenAI, Anthropic, and xAI
public model documentation. It follows each provider's explicit default
recommendation and checks documented model IDs, image inputs, and request-profile
compatibility signals. It does not guess the newest model by its name or number.

A new recommendation must appear in two observations at least six days apart
(normally consecutive weekly runs) before promotion. Ambiguous/missing/changed
documentation holds the entire catalog. Repeated manual runs cannot bypass the
observation period. The previous primary stays in the fallback ladder.

**Documentation checks are not live API compatibility tests.** No test inference
is charged to the owner or users. User-key/account access is handled only during
normal app requests, with same-provider fallback. No public scraper can guarantee
zero maintenance if the source format or provider API changes.

## Visible health and alerts

`status.json` records every check, public source links and hashes, pending models,
retained models and errors. Weekly status commits also keep this public repository
active when model IDs do not change. The schedule does not depend on app usage.
GitHub scheduling may be delayed; it is not an exact-time SLA.

Failures open **one issue assigned to the repository owner**, with the held model,
reason and run link. Repeat failures update that issue; a healthy check closes it
with a recovery note. Assignment appears through the owner's GitHub notification
settings. Workflow failures remain visibly red. GitHub outages or a disabled
workflow cannot notify through that same unavailable workflow; the public last
successful check is the independent visible freshness timestamp, not a watchdog.

The workflow uses GitHub's built-in repository token only. No custom secret,
personal access token, paid model key, or CATALOG_ENABLED variable is required.
To test notification delivery, run it manually with `test_alert=true`, then run
normally to exercise recovery. The test retains the catalog unchanged.

## Local checks

`python3 -m unittest -v test_cloud_model_catalog`

`node --test test_cloud_catalog_alert.cjs`

`python3 cloud_model_catalog.py --catalog cloud_model_policy.json --refresh --output candidate.json --status status.json`

Only public documentation GETs are allowed by the fetcher, including redirects.
Restore a prior catalog commit for rollback. App clients cache the catalog for a
week and retain their previous/shipped selection if fetching fails. An inactive
phone catches up when opened; it cannot receive data while offline or powered off.
