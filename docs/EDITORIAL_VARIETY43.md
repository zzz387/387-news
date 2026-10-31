# Editorial and visual refinement of policy4.3

The article target remains12, never a release threshold. No article-length,
feature-depth, compulsory topic quota or new literary audit is introduced.

## Stories and titles

selection43 compares the specific story: a primary DOI/canonical work, a
normalised title/focus and high-confidence paired concepts. Sleep deprivation
and appetite/weight are one practical story; the history of REM discovery is
a different focus. General words such as museum, health or space are not enough
to reject a story. Check candidates again after the full source is read but
before writing. Ready duplicates are ranked by editorial priority, verified
claims and useful distinct blocks; all drafts/counters stay in the checkpoint.
Duplicate candidates do not cancel delivery or require rewriting a good article.

Place/publisher/organisation frequency, recent14-day stories and space frequency
are preferences in candidate order. They relax automatically when alternatives
run out. No mandatory quotas or issue-level model requests are added. The
existing writer and final check receive the current selected titles and story
context. Headline wording is more varied; how-openings are advisory, not a veto,
and approved articles are never rewritten for typography or a how-count.

## Updating sources

publishers43.json registers the requested30 international and20 Russian science
publishers, plus5 sources for light/public-interest stories. Country, language,
type, topics, discovery hints, access and rights policy are data-driven. A URL
hint is not an active/verified feed. Catalogue membership grants no copyright or
permission to process restricted content. Full-text, robots, paywall and existing
per-article rights checks are mandatory before a discovered item is admitted.
News about research/press releases is not labelled peer-reviewed research merely
because its publisher is a science outlet. Actual article metadata is carried
through the writer and final check.

Production rotates through at most5 publishers per run, caches checks for6 hours,
checks at most8 complete articles and bounds the private candidate pool to120.
RSS/Atom or links on the actual public site supply URLs/metadata only; no feed
summary is substituted for the original. Full source snapshots remain in the
existing protected encrypted checkpoint. Unavailable, stale-only, restricted or
incomplete sites supply no active candidates and cannot stop the issue. No new
Secrets, paid service, parallel generator or independent production cron exists.
A separate public CI diagnostic probes catalogue availability without Gemini and
outputs only URLs/status/metadata, never full originals or private drafts.

## Optional light section

The separate light43 checkpoint prepares at most5 gentle short stories in a batch
and reviews them in one independent batch. The two-request auxiliary ceiling
also counts malformed-response/retry HTTP attempts against the SAME existing
run/day ledger; it is persisted across runs. Main article preparation and the
reserved daily budget take precedence. The section cannot trigger a literary
repair loop or veto an otherwise publishable issue. Missing/failed light stories
are omitted. High-risk advice and tragedy-based humour are excluded.

Only independently approved facts/rights/safety/wording appear, with their
primary source/date. They are not main articles and do not satisfy the target12.
The public release stores only final small-story text and public source metadata.
Display is after main contents, with id=light-news, newspaper columns on desktop
and one thin-lined column on phones. See EDITORIAL43_EXAMPLES.md for explicitly
fictional examples, which are never production input.

## Compact layout and safe deployment

Future templates remove mast-top/motto and the visible front-intro. A visually
hidden H1 retains semantic structure. Keep the green strip, date/number, logo,
menu including Overview and the newspaper typography. CSS changes are scoped
to edition-compact, so old archived HTML keeps its old layout.

The current homepage is a deterministic compact projection of its immutable,
hash-verified overview. Historical overview/article/Markdown/release metadata
are never rewritten. HTTPS checks accept either the original home hash or that
exact approved projection; any other content change still fails. No arbitrary
hash bypass or unsourced home overlay is permitted. A production-only refresh
can commit only index.html and redeploy via existing Pages without regenerating
an issue; inspect/preview paths cannot do it. Deployment uses the actually
published homepage date, not a future draft date. Every full article and old
archive checksum remains independently checked. The06:00 gate, watcher, shared
mutex,24/run and220/day limits and cooldown are unchanged.
