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
reason and run link. Every failed run attempt explicitly mentions the owner;
repeat failures add a comment to the same issue and update its summary. A receipt
prevents duplicate comments when the notification step retries in the same
attempt. A healthy, successfully published check closes it with a recovery note.
An error annotation and job summary also link the failure to its run. For an
organization-owned fork, assign a maintainer to the alert issue; the workflow
mentions those assignees instead of guessing an organization recipient.

GitHub mention delivery still depends on the recipient's notification settings
and access. A successful API call proves the issue/comment was written, not that
email or a mobile push was received. Check the GitHub inbox for `reason:mention`
after an alert-path test. Native scheduled-workflow notifications can go to the
person who last changed the schedule or re-enabled it, so they are not the owner
alert contract. See [GitHub workflow notifications](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)
and [mentions](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax#mentioning-people-and-teams).

Workflow failures remain visibly red. GitHub outages or a disabled
workflow cannot notify through that same unavailable workflow; the public last
successful check is the independent visible freshness timestamp, not a watchdog.

The workflow uses GitHub's built-in repository token only. No custom secret,
personal access token, paid model key, or CATALOG_ENABLED variable is required.
To test notification delivery, run it manually with `test_alert=true`, then run
normally to exercise recovery. The test retains the catalog unchanged.

## Local checks

`python3 -m unittest -v test_cloud_model_catalog`

`node --test test_cloud_catalog_alert.cjs`

`node --test test_cloud_catalog_receipt.cjs`

`python3 cloud_model_catalog.py --catalog cloud_model_policy.json --refresh --output candidate.json --status status.json`

Automation reads observation history using `--previous-status status.json` and
writes `--status check-status.json`. `cloud_catalog_receipt.cjs` publishes that
fresh report, or records a current workflow failure if no valid report was
produced. A skipped check never reuses an older degraded report as its result.

Only public documentation GETs are allowed by the fetcher, including redirects.
Restore a prior catalog commit for rollback. App clients cache the catalog for a
week and retain their previous/shipped selection if fetching fails. An inactive
phone catches up when opened; it cannot receive data while offline or powered off.
