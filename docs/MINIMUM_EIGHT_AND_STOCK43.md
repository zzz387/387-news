# Minimum eight, independent light column and protected editorial inventory

Owner-approved operational amendment, 2026-11-06. Policy stays 4.3, twenty
personal interests and PR38 story comparison stay intact. The real production
configuration is minimum_articles=8, article_target=12. There is no word/depth
minimum or extra literary audit.

## Diagnosis and release contract

№013 was allowed to contain one article because the previous policy expressly
allowed partial releases and the JSON minimum was not an effective gate. Target7
was also APPROVED with one article. The old light call ran only after twelve main
articles or an exhausted queue. Provider503 interrupted earlier runs; source
extraction/date and independent-safety holds also reduced the supply. Low request
usage alone does not prove unused callable provider capacity.

Controller, public builder and new public release metadata now enforce eight
unique eligible main articles. Light stories and source links never count.
Under eight means PREPARING / MINIMUM_ARTICLES_NOT_MET, audit_passed=false, saved
articles unchanged, automatic continuation through the existing schedule. Normal
preparation continues after06:00 if the minimum is missing. At/after the release
window, eight ready articles take priority over further generation. Complete
editions stay private before the existing06:00 commit gate. A clearly labelled
zero-article source digest remains a reference-only renderer, not an eight-article
edition or an automatic substitute for this gate.

Legacy partial published archives remain readable and immutable; historical
rendering tests explicitly use the old one-article profile. New tests use the
actual production minimum of eight. No test-only production bypass exists.

## Same production, shared encrypted inventory

`stock43` stores full reviewed records, original sources, rights, final-check
fingerprints, check times, reservation/consumption metadata and unfinished work.
It is a small extension to the existing controller, cipher, mutex and artifact
restore; no new generator, database, cron, credentials or service is introduced.

`387news43-editorial-stock` contains only `editorial-stock.enc`, encrypted using
the existing AES-256-GCM key from GitHub Secrets. It is restored with the official
cross-run download action and written before any publication commit. Retention
is30 days, usable article age14 days. The date-specific encrypted checkpoint also
contains an inventory snapshot. If upload fails, the prepare job cannot commit or
deploy; if an expected restore fails/corrupts/expires, it fails closed. Model
reservations/cooldowns are merged conservatively from both normal accounting and
the encrypted stock snapshot. No secret, draft or full dossier is exported here.

Nearest edition has first claim: draw reviewed unused non-duplicate material to
12 using existing soft diversity ranking. Once12 are secured, remaining permitted
requests prepare evergreen inventory up to20. Sensitive medical/legal/childcare
advice is not silently reused across dates: it requires fresh normal safety
review. Unknown review times, expired records, news and failed fingerprints are
not counted as usable reserve. Sources and rejection/stage histories remain
checkpointed. Inventory goals are never reported as actual ready counts.

Reservations survive independent runs and are released/consumed from the public
archive: a reserved article cannot be drawn into another date, and a published
source/story is not repeated. The release queue resumes the oldest unpublished
checkpoint instead of abandoning an under-eight date at midnight. A newer
published archive prevents backdated homepage replacement.

## Supply, safety and short stories

Normal public search retains five publishers/eight full-original checks.
Shortage mode allows at most15 publishers/24 public original checks with paced,
cached access and a bounded search window; up to two additional shortage rounds
can replace an exhausted candidate queue. Gemini caps stay24 per run/220 UTC day.
A/B/C search and missing-topic fallbacks stay active. Prospective-candidate count
requires a full verified original, not RSS snippets or thirty-four fixed URLs.
A separate discovery slot is assigned to suitable light-news publishers; actual
story content and rights decide eligibility. A dedicated light-source candidate
is not consumed as a main article later in the same issue.

Complete closed semantic article-body wrappers include supported data-testid and
Drupal/blog variants. Ambiguous/clipped, paginated, inaccessible/paywalled and
abstract-only pages remain rejected. Dated news still requires an event witness;
evergreen reviews need no event date. Actual trusted citations (up to six) can
replace an unavailable supporting page; no references are invented. A safety hold
is reconsidered only when new complete independent competent evidence arrives,
without resetting previous requests, writing attempts or genuine vetoes.

The column starts independently with headroom reserved for the main eight. It
uses at most two batch model attempts per issue. Semantic animal/museum/nature/
curiosity selection replaces blind publisher-flag trust. Accepted short records
retain fact/right/independence checks; historical/fact labels avoid false news
freshness. Main articles and previously published stories are excluded. Usually
three notes go to the edition; surplus reviewed notes accumulate toward15. No
suitable verified notes means no column, not a blocked main release. AtlasObscura
and AP are catalogued as unverified/manual until a real public check allows
activation; existing verified wildlife/nature publishers are reused, not copied.

## Verification and operational limits

Regression scenarios cover1+7,6+10,12+0,0+8 with Gemini unavailable, three with no
reserve, duplicate removal plus replacement,8+5 light notes,6+3 not being eight,
missing light supply, sensitive/expired/tampered inventory, cross-run synthetic
AES recovery, missing/corrupt artifact fail-closed, reservations, archive
immutability, real config, event dates, alternative full markup, adaptive search,
new independent evidence and independent light scheduling. Existing quota,
rights/facts, checkpoint, source/translation, mobile and watchdog checks remain.

Typical preparation costs two successful requests per main article (write plus
independent review), with bounded repairs when needed:8≈16 and12≈24, plus at most2
for light notes. A cold20-article evergreen stock costs about40 successful requests,
spread after nearest-issue work across existing windows; repairs/failures add to
these totals. None are exempt from the ledger. This is a capacity estimate, not
proof of provider availability. A GET model metadata success is not generation.

A cold bank starts at zero. The code cannot manufacture20 reviewed articles when
Gemini is unavailable. HTTP429/503 retains normal persisted backoff/cooldown and
scheduled recovery, without parallel calls, new keys, reset counters or paid
fallbacks. First production reports must state actual main/light inventory and
next-issue readiness; passing synthetic tests is not publication. №013 is left
unchanged. Ordinary delivery/watchdog, daily priority over special work and06:00
Moscow remain in force.

## Protected inspection and capacity recovery

Read-only inspect reports the current minimum and restores the latest encrypted
inventory before counting it; it does not persist state or initialize a model
budget. Light diagnostics expose only attempts/counts/reason codes, never drafts.

A503 still pauses its failed operation and persists that model's cooldown. A
later operation/run can prefer the other ALREADY configured free model; the same
key, six-second interval and total24/220 budget apply to both. Models whose
cooldowns remain active are skipped, not called. A429 now also persists a global
all-models hold for Retry-After, so changing models cannot evade rate/quota
restrictions. If both configured models are unavailable, preparation waits with
its encrypted progress. No new model, paid fallback or quota reset is introduced.

Inventory preparation uses its own existing personal-topic/diversity ranking,
rather than treating the already-full main edition as its topic allocation.
Sensitive candidates are left for fresh main preparation, not silently banked.
Known main or reserve duplicates are skipped before another paid writing stage.
