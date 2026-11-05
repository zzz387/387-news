# Policy 4.3: personal topics and narrow-story duplicates

The existing daily controller and encrypted checkpoint remain authoritative.
Selection rules version 2 and classifier version 2 are metadata migrations,
not a new pipeline or a reason to regenerate accepted work.

## Discovery and selection

Every eligible preparation run orders distinct publishers for A (family),
B (Moscow/travel/culture) and C (health/movement) before other publishers.
Weekly underrepresentation determines which group starts. Fresh cached publishers
are filtered before appointment assignment, so a cached multi-topic source cannot
silently consume another group's search slot. The first attempts share a
thread-safe, per-origin paced public fetch session; no model calls run in parallel.
They each reserve one full-original check within the existing five-publisher,
eight-article-check allowance. Remaining publisher slots first retry groups with no eligible candidates using a
different publisher, then serve other topics. Profile-specific publishers with
previous complete-original evidence are preferred to broad news portals.
Unrelated metadata and common section URLs do not consume original checks.

The 75-second discovery window and seven-second public transport timeout bound
work. Discovery is best effort, not a release gate: slow/unavailable publishers,
rights restrictions and missing groups never block an otherwise valid release.
The existing six-hour publisher cache remains. `discovery43.last_run` records
attempted groups separately from actual full-source candidate classifications.
RSS descriptions rank links only and never substitute for a complete original.
If the complete original has no bibliographic publication date, a verified
publisher feed may supply its explicit published/pubDate field, with provenance.
An updated date never substitutes for publication, and no RSS date proves an
event date; future dates and the normal factual/news checks remain enforced.

The old 120-total-record early return is removed. At most 120 untouched discovered
candidates remain active; older untouched records are marked discovery_retired.
The original record, source, evidence checks and refusal history stay in the same
checkpoint. Written or partially processed work is not retired. No quota ledger
is reset. The fixed URL list remains a reserve.

A/B/C receive preference when candidates are available, with the twenty original
directions and 7/14-day history retained. Resuming paid-for stages still has
priority over starting another story. Coverage is a search/selection objective,
not a minimum article count or a reason to fabricate an article.

## Three duplicate checks

1. Compare candidate/source metadata and verified original context before writing.
2. Compare a newly finished article with the ready set, recording related record IDs.
3. The public builder reuses deterministic unique-ready selection, retaining the
   most useful article and excluding related copies from this edition only.

Comparison includes source URLs, DOI, narrow normalized story concepts and
substantial overlap of the publisher-independent written prose. The actual two
Eos URLs and Russian titles from №012 are regression fixtures. A cryptic original
title can be understood from its verified full source. Living construction
materials do not absorb Moscow modernism or bacteria in urban river ecology.
There are no per-pair Gemini calls. Excluded records are never deleted.

## Categories and updates

Categories follow title/teaser/content, not publisher identity or inherited Science
labels. An unrecognized topic uses Society (Общество); demonstrated science stays
Science, art history stays History/Culture, and construction technology stays
Technology. New prose is classified before the existing safety/fact/rights review.
A previously written article or approved fingerprint is not relabelled during
checkpoint migration or final-format repair.

`selection_policy43` stores rules/classifier/catalog versions, catalog content
hash and candidate-set formation time. An update reranks and corrects hints for
unwritten candidates, while keeping accepted articles, model stage counters and
refusals intact. The private composition report records main article counts,
A/B/C representation, other categories, missing directions and excluded stories.
It is advisory and is never copied into public release metadata.

## Verification and deployment

Unit fixtures cover actual №012 metadata, different legitimate architecture
stories, generated-text duplicates, a 27-candidate mixed pool, exhausted queues,
checkpoint migration and idempotence, actual-content categories, unavailable
publishers, discovery allowance and main-only coverage counts. Existing checks
cover partial/zero-article releases, optional light news, rights, evidence,
quota, encrypted recovery and the 06:00 release gate.

CI also runs the actual bounded public A/B/C selector with no production checkpoint
and no Gemini key. Its public artifact reports attempts and eligible candidate
counts, not a claimed future newspaper. Normal production still uses the shared
mutex, unchanged model quotas and existing Pages/HTTPS verifier. Published №012
and all historical files remain immutable. A complete future thematic issue
cannot be claimed from synthetic tests or discovery metadata alone.
