# Museum references and the art library

Policy 4.4, daily editorial requirements, the 06:00 Moscow delivery and the
existing Actions mutex/checkpoint/ledger remain unchanged. No paid image service.

`art/registry.json` is append-only public metadata. Museum WebP reproductions
are under `assets/art/{genre_id}/`; generated article art stays separate under
`assets/illustrations/`. A verified set has exactly four artwork IDs and SHA256s,
keyed by **issue identity + genre**. Assignments are immutable; all assigned IDs
are excluded from later issues, including special issues on the same date.

Discovery currently uses the official Art Institute of Chicago API, with the
Cleveland Museum of Art API as fallback. Only explicit CC0/public-domain image
records with author, title, date and genre evidence are ingested. Requests respect
robots, allowlisted HTTPS hosts, byte limits and a shared 75-second/24-request
window. Failed discovery leaves an explicit deficit and does not delay text
publication. Reproduction proportions are retained; reference derivatives have
both dimensions below 512 pixels. Museum object IDs, normalized metadata,
original/derivative SHA256 and a conservative visual hash prevent duplicates.

The encrypted existing checkpoint retains the registry, successful reproduction
bytes and generated images before proceeding. Restoring a saved set never searches
or downloads again. A quartet is shared by every article of that genre in the
issue. Finished images retain reference IDs, hashes, provider and actual model.
The reference standard applies to new issues from 2026-11-23; existing archives
are not rewritten or retroactively presented as reference-guided.

Cloudflare's documented `@cf/black-forest-labs/flux-2-klein-4b` receives multipart
binary parts `input_image_0` through `input_image_3`, separately, plus the individual
English article brief. It has fixed four-step inference: no unsupported `steps`
parameter is sent. Output is 1024x768. Model responses are decoded, verified,
compressed to WebP and cached by the existing art pipeline. Failed reference
availability explicitly falls back to the existing Schnell path, never a paid
provider, with `REFERENCE_SET_UNAVAILABLE` in metadata.

The existing live Free-subscription/account-usage guard and shared quota ledger
run before each inference. Published rates are 5.37 Neurons/input 512px tile and
26.05/output tile: four small references plus 1024x768 output estimate 125.68
Neurons. The existing conservative 256-Neuron reservation per request, 7500 image
budget, 1500 account headroom and 10000 Free account ceiling remain in force.
Actual account analytics can lag and include other workloads; estimates are not
claimed as per-request billed usage. No billing or subscription settings change.

The initial owner-authorized `[art-library]` rollout uses the same protected
production workflow and serial mutex. It selects one quartet for two independent
studies of already approved public articles, published in `/art/studies/` with a
clear label that they are studies, not a newly issued newspaper. Archived article
HTML/Markdown and release metadata remain unchanged. Future approved issues use
one set per used genre automatically. Gallery pages, reference hashes and studies
are checked before deployment and over HTTPS after Pages delivery.

QUICK: `python -m scripts.run_tests --quick --changed scripts/art_library44.py`
FULL: existing PR CI before merging. Synthetic unit fixtures never call a real AI
or pretend to be museum works. Actual inference is only protected Actions on main.

Official documentation checked on 2026-11-22:
- https://developers.cloudflare.com/changelog/post/2026-01-15-flux-2-klein-4b-workers-ai/
- https://developers.cloudflare.com/workers-ai/models/flux-2-klein-4b/
- https://developers.cloudflare.com/workers-ai/platform/pricing/
- https://api.artic.edu/docs/
- https://www.artic.edu/open-access/open-access-images
- https://www.clevelandart.org/open-access

Production recovery: forbidden museum hosts open a per-run circuit after one
401/403/429/server error, leaving requests for the independent museum fallback.
Official Cleveland image URLs are read from API records, including its
`openaccess-cdn.clevelandart.org` host; protected URLs are not bypassed. The global
reference registry and unpublished media also travel in the existing encrypted
editorial inventory, preventing cross-issue reassignment before a Git commit.
Already committed media are omitted from this shared duplicate cache. Pending
issues are labelled as preparing instead of publishing broken release links.

Art navigation is added with the explicit current publication root; legacy renderers
retain their original markup. Temporary legacy/special publication projections copy
the existing gallery dependencies so current-home links remain valid without
rewriting archived issue pages.
