# Forge model catalog

Public model metadata and synthetic compatibility automation only. No Forge app
source, athlete information, conversations, credentials, or private data.

## Activation

The workflow is deliberately disabled until setup is complete.

1. In repository Settings > Secrets and variables > Actions, add dedicated
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `XAI_API_KEY` secrets. Use budgeted CI
   accounts, never an athlete's BYOK credentials.
2. Add repository variable `CATALOG_ENABLED` with value `true`.
3. Run **Verify and refresh model catalog** manually. Check its successful result.
4. It then checks every six hours. Failed checks do not replace the catalog.

The bootstrap catalog contains documentation-verified IDs, not a claim of live
API validation. The first successful enabled workflow supplies that evidence.

## Contract

The job discovers available stable models within Claude Opus, Grok numbered
flagships, and OpenAI numbered/Astra/Sol flagship families. It uses provider
release timestamps, not a lexical model-name sort. New naming families require
an automation rule update, not a Forge app release, if the API stays compatible.

Each candidate must answer synthetic text and synthetic white-pixel image
requests in both one-shot and streaming mode within the probe budget. These are
API compatibility checks, not medical quality, privacy, cancellation-compute,
or device-performance certification. No health information is used.

Only the catalog JSON is committed by automation. The app's destinations,
credentials, privacy filtering, permissions, and tools cannot be changed here.
Revert a catalog commit to roll back. Clients refresh at most every six hours
after successful fetches and retain their cached/shipped defaults on failure.

## Local checks

`python3 cloud_model_catalog.py --catalog cloud_model_policy.json --check`

Live checks use environment keys and a separate output path:

`python3 cloud_model_catalog.py --catalog cloud_model_policy.json --live --output candidate.json`

Live checks make paid API requests on the CI accounts. They do not deploy by
themselves. The GitHub workflow publishes only a verified artifact.
