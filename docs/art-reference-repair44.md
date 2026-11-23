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
