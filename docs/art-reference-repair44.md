# One-reference artwork, policy 4.4

Each issue/genre owns one immutable set of four verified CC0 museum works. A
versioned deterministic selection chooses one member using configurable 70/30
metadata/tonal-fit and palette-diversity weights. Mood scores are transparent
heuristics, not asserted museum facts. Existing sets and archived genre labels
are never migrated. New prompts distinguish movement from medium.

Pillow samples image color groups; D65 CIELAB distances compare their proportions,
lightness, saturation and contrast. Cached profiles follow the file SHA-256.
COLOR_MATCH_OK/WARNING/MISMATCH concern color only. A mismatch permits at most one
extra inference with the same reference, subject to the unchanged free controller.
The first usable result is checkpointed before retry; aesthetic warnings do not
block daily publication. Missing references never silently invoke Schnell for new
reference-era pictures. Text-first emergency publication remains available.

The existing daily workflow accepts `repair_legacy_images=true` with
phase=backfill_issue_art, preview=false and target_date=2026-11-23. The explicit
owner rollout marker `[repair-legacy-art]` on a main push routes the same repair.
The default is false. Scope is issue 029; only original Schnell bindings qualify.
The initial config stage is `pilot` (features 11, 01, 02); inspect the artwork-only
Actions comparison artifact before changing the stage to `all`. The saved three
results are reused. No issue images are replaced until all target results exist.
The two original Klein files, article identities, Markdown and every text fragment
remain checked. Replacement keys/URLs include the new prompt version. Museum
references, selection and progress use the existing encrypted checkpoints and
shared stock; there is no new credential, paid provider or storage service.

Museum recovery accepts nullable official metadata without aborting the collection.
New quartet candidates retain movement evidence checks, including accented terms;
Neo-Plasticist/Vorticist descriptions are excluded from new Cubist quartets.
Existing assigned quartets remain immutable. SMK's official public API is an
independent bounded fallback: only explicit public_domain=true plus CC0 or Public
Domain Mark rights URLs, complete attribution and matching movement metadata are
accepted. Access/robots failures stay closed. License labels retain the actual
CC0/PDM distinction. A real successful API response is logged separately from
reference generation; an unavailable source never fabricates a candidate.

Repair pilot discovery now requests only its three movements, retaining the other
sets. Explicitly authorized repair runs can resume the same workflow at most four
times per stage; completed pilot results stop for review, quota/provider pauses
stop dispatch, and all completed images are reused. Actual SMK rights/date fields
and two-dimensional media are checked. A bounded six-work pool permits meaningful
color-diverse quartet selection; exact file hashes and museum identities block
duplicates, while coarse dHash neighbours alone cannot discard distinct colors.
Met fallback object seeds are verified Monet collection records (437133, 437112,
437124, 437127, 437115, 437136); every API record must independently confirm artist,
classification, public-domain rights, metadata and image bytes before admission.

The first real one-image pilot revealed a signature-like corner mark. Prompt v2
moves the unsigned/blank-corner requirement ahead of the subject; rejected trial
objects remain in checkpoint history. A corrected prompt retains the previous
selected reference for that article. Output dimensions now follow the planned
aspect ratio using supported multiples of 16. Artwork-only pushes skip unrelated
special-issue preparation. Before resuming, the workflow checks the main production
queue so an art continuation cannot evict a queued daily run. A completed all-image
repair hands control back to the ordinary daily preparation workflow.

Additional museum recovery uses the official SearchCulture EDM `/json` item URIs
and Paris Musées IIIF manifests, without search API keys. Curatorial seeds are
only hints: every live record must independently bind title, artist, date,
two-dimensional medium, movement evidence, a real thumbnail and its rights.
MOMus digital-file/thumbnail CC BY-SA 4.0 is kept distinct from CC0: library
credits include artist/title/provider/source/license and WebP transformation;
new AI compositions using such references conservatively carry the same license
and a source/adaptation notice in their illustration caption and manifest.
The Actions comparison artifact includes the same credits. No news body changes.
Paris seeds are narrowly documented Mucha/Fouquet-shop designs, admitted only
when their actual IIIF canvas declares CC0. Robots and request bounds still apply.

The unsigned real pilot retained its reference palette but drifted into a forest
scene unrelated to the marriage/alcohol article. Prompt v3 therefore binds the
owner-authorized 029 repair's concise English visual subjects to each unchanged
public text hash. These are illustrative metaphors derived from the final public
articles, not new facts, edited news text or extra model requests for translation.
The same selected reference is preserved while correcting that concrete error.

The real SearchCulture recovery returned HTTP 406 without an Accept header.
Its documented JSON-LD representation is requested explicitly using
`Accept: application/ld+json`; no access restrictions are bypassed. Optional
color retries now reserve first-pass capacity for all outstanding repair keys
before using any of the unchanged daily free allowance on an aesthetic repeat.

Visual review also found a conflicting Art-nouveau composition instruction:
"Frame the subject" encouraged a decorative border despite the no-border clause.
Prompt v4 integrates ornament into the scene without a frame and strengthens
Impressionist pigment/edge instructions against photographic rendering. These
three pilot outputs are reviewed before the all-image stage. Successful prior
trial objects remain saved; optional color retries preserve first-pass capacity.

JSON-LD parsing accepts compact and expanded official predicates/types, still
binding aggregation rights and its exact thumbnail to the same record URI.
Public schema diagnostics contain only museum node IDs, types and field names.
Known Met/Paris/MOMus collection seeds extend remaining movements, always behind
live rights, artist, medium and image checks. No record is admitted from its name
or existence alone.

Cloudflare rejected one v4 trial output (3030). Respect that rejection: retain
the rejected key without automatic retry and continue unrelated article keys;
do not disable or evade the provider's filter. Two previously accepted, visually
reviewed v3 results are bound to their actual text hash, prompt version and WebP
SHA; they are not discarded or relabelled v4. Review records disclose remaining
ornament/texture limitations. The all-eleven atomic publication gate remains.

A real runner response confirmed that `/json` returns a legacy Europeana Record
DTO rather than the documented JSON-LD graph. Request the canonical item URI with
`Accept: application/ld+json`; only an unsupported/technical representation may
fall back to the documented `/xml` RDF representation. XML facts go through the
same record-bound rights/media/thumbnail admission. HTTP 403, robots and other
access failures never trigger this fallback. Gallery proof records actual old/new
SHA values and prompt versions, and movement evidence points to its own catalogue.

When the museum adapter changes, the existing CI browser job runs a single
read-only public metadata contract probe before its normal browser checks. Its
small artifact contains only work facts, rights/file URLs and schema paths;
descriptions and private newspaper data are excluded. No Secrets, checkpoints,
Gemini or image inference are used. This advisory probe makes real schema changes
reviewable before production, without adding a workflow or publication gate.
