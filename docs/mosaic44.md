# Artistic front page and brief selection — policy 4.4

## Backup before deployment

Baseline: `6d311ac68ee93bb9be4d38e45ebf40dbe60b4306`.
GitHub branch: `backup/pre-mosaic-20261118-6d311ac`.
Backup run: https://github.com/zzz387/387-news/actions/runs/44317542009
Artifact: `387news44-backup-pre-mosaic-20261118`, ID `14432898128`, retention 90 days.
It contains the public repository bundle, baseline public release and 55 latest
state snapshots, copied without decryption. The manifest records SHA-256 hashes;
ZIP integrity and repository-bundle integrity were verified. Total: 63,191,893 bytes.
Secrets remain in existing GitHub Secrets and are never exported.

Rollback is a normal reviewed change, never a force push. Restore the affected
Python/configuration/workflow files from the baseline branch; restore the baseline
homepage only if it is still the same dated issue. Preserve all subsequently
published archives and their `assets/illustrations`, `mosaic.css` and `mosaic.js`.
Do not blindly revert commits that would delete permanent artwork referenced by
later issues. Existing archive HTML must remain unchanged. Deploy with the same
production workflow and verify HTTPS and article/Markdown hashes.

**Never roll back the quota ledger or cooldown to the backup's older values.**
Use the current shared ledger; existing recovery merges reservations conservatively.
Private state is restored only in protected Actions using the existing keys and
checkpoint mechanism. The public backup branch alone does not contain private state.

## Briefs

New unpublished issues use `brief_policy_revision=2`: minimum eight, maximum twelve.
All eligible notes remain in the checkpoint; reusable surplus is banked in the
existing encrypted stock. No new database or publisher catalog is introduced.
Selection uses soft subject/publisher penalties and same-event deduplication.
Animal stories are allowed, but alternative subjects receive preference after a
few animal stories. There are no mandatory per-topic quotas.

Story-level criminal/tragedy exclusion is applied during discovery, before a
batch request, during admission and before selection. Strong crime phrases,
institution/action combinations and explicit crime sections are considered.
Benign police mentions are allowed; no publisher is excluded wholesale. Facts,
source binding, dates, safety and rights remain mandatory, without literary audits.
Old immutable 4.4 manifests lacking the revision retain their historical limits;
the current homepage can display a newly filtered selection without altering them.

## Final-art revision 2 (November 19)

Every eligible main article is frozen only after the whole issue passes policy
4.4, including rights, facts, story deduplication and required subjects/briefs.
The encrypted approval binds the ordered permanent candidate IDs and complete
final article payloads. `assembly_status44` records EDITORIAL_APPROVED,
ART_GENERATION and READY_FOR_PUBLICATION; the existing delivery controller keeps
its normal APPROVED/wait-until-06:00 state. Inspection never generates artwork.

All main articles receive plans: eight, twelve, twenty, twenty-seven or more.
Only the first-page composition is limited to 8–12 tiles. Its artwork comes from
the very same files displayed after the title/teaser inside the article. The
caption explicitly identifies AI artwork; factual article text is unchanged.

The key binds issue date, permanent candidate ID, the hash of title, teaser,
category, kind, mode, all final blocks and activities, and prompt version.
Prompts include a deterministic summary and facts extracted from those final
blocks. No new model call is used to summarize them. Associative genres and
palette/composition are selected before generation and retained across restarts.

Approved composition is resumed before source discovery or further text work.
There is no one-image-per-run restriction: one sequential batch uses the
remaining existing request/time budget, up to its existing 24/run and 220/day
application ceiling. Provider model quotas/billing remain model-specific; the
adapter never calls the text Flash-Lite model to manufacture an image. Every
attempt reserves the existing ledger before its request. 429/503 retain cooldown
and end the batch. There are at most three failed attempts per image key.

Every accepted result is saved immediately in the encrypted checkpoint with its
article ID, date, text hash, exact prompt, genre, model, status, byte size, SHA-256
and future path. Unchanged results survive independent restores; changed final
text invalidates that article's key. Old bytes/history remain recoverable.
Images remain private until assembly at the release gate. Published WebP files
and their small public provenance manifest remain permanent archive assets;
private prompts/descriptors are never published. Duplicate image hashes are
rejected. New images are never retroactively inserted into an old archive.

## API availability and honest fallback

Automatic image generation remains disabled. On November 19, the official Google
pricing table lists no free tier for Gemini 3.1 Flash Lite Image, Gemini 3.1 Flash
Image or Gemini 2.5 Flash Image. The documented 1K output price for Flash Lite
Image is USD 0.0336/image, plus input tokens (12: 0.4032, 20: 0.672, 27: 0.9072
before inputs). This is a candidate price, NOT an enabled paid service or charge.
Reference: https://aistudio.google.com/docs/pricing#gemini-3.1-flash-lite-image
A paid image model requires explicit owner authorization. ChatGPT subscriptions
and this chat's image tool do not supply an unattended free Actions API.

A one-time protected-main probe on the tagged deployment checks candidate model
metadata with the existing Secret. It makes no generateContent call, changes no
key, does not inspect billing credentials and never treats metadata access as
proof of generation permissions or prepaid quota. Billing access, real generation
access, usable RPM/RPD and observed batch latency remain unverified without an
authorized image request. No latency or available-credit claim is fabricated.

If the API is unavailable, final assembly records INCOMPLETE, required/ready/
missing counts and `emergency_text=true`. It publishes the safe text issue at
06:00 without claiming successful illustration. In partial failure, accepted
pictures are retained and only missing keys may be retried before publication.
After publication, the archive is immutable: ordinary deployment never generates
new art. The nine November 18 images remain historical assets, not a stock pool
for new articles. Configure a verified permitted provider before expecting a fully
illustrated new issue; do not enable a paid model on inference from metadata.

## Verification

Component QUICK is used during edits; mandatory FULL CI precedes merging.
Existing tests cover 8/12/20/27 unique images, 18/20 restore, approval and changed
text, failure persistence, uniqueness, shared article/mosaic paths and hashes.
Synthetic codecs/providers never call an external image API. Browser checks cover
320/390/768/1024/1440px. HTTPS checks preserve archive/article hashes and verify
all published image assets, including those outside the 8–12 front-page tiles.

The tagged rollout performs one ordinary workflow_dispatch after successful HTTPS
verification so the next unpublished checkpoint is exercised with the new code.
It uses the existing global production mutex and schedule; dispatch events cannot
re-enter the push-only continuation. The existing monitor requests actions:write
for this authenticated dispatch, without new Secrets or a public trigger URL.

The existing 05:54 wake-up may wait through the bounded final ten-minute release
gate when the Actions stage has sufficient time. Image requests stop before
06:00; private artwork is materialized into the public worktree only after the
release gate. The morning gate has its own regression case and does not depend
on the image API being available.

## Cloudflare Workers AI Free rollout — November 21

Provider: `cloudflare_workers_ai`; pinned model:
`@cf/black-forest-labs/flux-1-schnell`. Gemini Image and paid fallback are disabled.
Only `prompt` (maximum 2048 Unicode characters) and `steps` (four; model maximum
eight) are submitted. Cloudflare returns Base64 JPEG/PNG, verified with Pillow
and encoded using the existing bounded WebP codec. No Worker or DNS change is
needed. The daily article generator, schedule and editorial policy stay in place.

Production reads `CLOUDFLARE_ACCOUNT_ID` from Secrets (or its existing Repository
Variable) and `CLOUDFLARE_API_TOKEN` only from Secrets. Credentials are never
exported. The current tool connections do not provide a Cloudflare account token.
The protected rollout diagnoses their actual availability without printing values.
If absent, the one owner action is to add these two Actions Secrets from a
**Workers Free** account. The token must be scoped to that account and permit
Workers AI Read/Edit, Billing Read (subscription verification only) and Account
Analytics Read (whole-account Neurons). Billing Write is neither needed nor used.
Do not put credentials in chat, code, Variables containing tokens, or artifacts.

Before every inference the client reads all account subscriptions and rejects
paid/ambiguous plans; it accepts default accounts without paid subscriptions or
explicit free subscriptions. It reads the entire account's current-UTC-day
`aiInferenceAdaptiveGroups.sum.totalNeurons`. Failed permission/schema checks
stop generation. The model is called directly, without AI Gateway unified billing
or prepaid credits. No code creates subscriptions or activates billing.

Cloudflare documents 10,000 free Neurons/day, resetting at 00:00 UTC. Free plans
fail above their allocation; they do not charge for overage. The app also reserves
256 Neurons before each attempt within a 7,500/day image budget and checks a
1,500-Neuron account headroom against observed total usage. Reservations include
failed attempts and survive checkpoint merges/Gemini day rollover. Other tasks'
usage is included in the live account check. The server's Free-plan hard cap
remains the financial protection if telemetry is delayed or another task races.

Documented FLUX pricing is 4.8 Neurons per 512×512 output tile plus 9.6 per step.
For a 1024×1024 result at four steps this predicts 57.6 Neurons, not a measured
per-request charge. The client records this dimension-based estimate separately
from reservations and observed account totals. The image response does not expose
per-request Neurons; do not call an estimate an actual measurement. The tagged
rollout runs one smoke image only after live Free-plan verification, saving it in
the existing encrypted checkpoint. Missing credentials mean no smoke request.

References:
https://developers.cloudflare.com/workers-ai/platform/pricing/
https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/
https://developers.cloudflare.com/workers-ai/get-started/rest-api/

### Explicit and automatic backfill

`backfill_issue_art` is a phase of the existing production workflow. It validates
the published manifest and all article/Markdown hashes, then prepares only missing
images. A narrow recovery validator may tolerate missing illustration files, but
never changes the text/source/date checks. Existing valid public pictures and
private checkpoint bytes are reused. It patches only the dedicated AI figure,
shared stylesheet link and mosaic, then recalculates HTML/overview hashes.
`without_art44(before) == without_art44(after)` protects each article byte-for-byte.
Markdown is unchanged. A private temporary tree must validate before copying the
one authorized date into the worktree. A repeated complete backfill is a no-op.

All future releases retain public ID/text-hash/key bindings for every approved
article, including missing images. This allows a later 14/20 backfill to retain
exactly those fourteen files and generate six. One already-published incomplete
issue may be backfilled after ordinary daily work if the Free provider and time
budget permit; it never runs another producer or delays a new due release.
Dates before November 22 are limited to the explicitly authorized November 20
and 21 recovery. Missing artwork is reported as `ARTWORK_INCOMPLETE`.

The thirteen November 21 illustrations are real one-time outputs of the available
ChatGPT image tool, as authorized for this recovery. No external paid API, billing
plan or credit purchase was used. Their public provenance says `chatgpt_image_tool`,
not Cloudflare; they do not prove the Cloudflare REST integration works. Original
PNG files are retained; thirteen unique WebP files total about 2.66 MB.

### November 20 historical publication

`recover_missing_issue` explicitly selects and restores the November 20 encrypted
checkpoint. A protected-main date-specific switch permits that one backdated
publication, while preserving the newer homepage and every newer archive. It
keeps approved texts and fills actual policy 4.4 deficits. Published numbers are
not reassigned: November 19 is already number26 and November 21 is number27, so
the later-published recovered November 20 issue receives the next free integer.
Its issue date remains November 20; `recovered_at` records actual recovery time.
The tagged rollout first delivers November 21 artwork, then queues this recovery
through the existing mutex. Useful textual progress may continue at most three
controlled runs; quotas/cooldowns are never reset.
