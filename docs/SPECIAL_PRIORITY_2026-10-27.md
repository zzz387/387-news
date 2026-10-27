# Owner-authorized 003-R priority

On 27 October the owner changed production order: publish the complete eight-topic
003-R before resuming the twelve-article daily queue. Existing root concurrency,
six cron expressions, daily 06:00 Moscow release time, Secrets/Variables, model
list, 24/run and 220/UTC-day quota, and six-second gap remain unchanged.

`config/production-priority.json` names one authorization. Its ACTIVE/COMPLETED/
BLOCKED lifecycle is stored only in the existing encrypted special checkpoint.
The existing reusable special job now runs before daily preparation. Daily runs
only when special explicitly releases the queue and consumed zero requests in
that workflow. A failed restore or blank output fails closed. HTTPS verification,
not eight sources, eight drafts or CI, completes the priority. Existing public
special files use the bounded delivery recovery path. Terminal editorial holds,
four productive but stalled runs, 64 productive runs, or 72 elapsed hours release
the daily queue with an explicit BLOCKED priority; they never approve a partial
special issue. Quota/cooldown waits do not count as productive stalled runs.

Recovery uses official artifact downloads inside Actions. Special restoration
selects the actual oldest unfinished daily checkpoint as read-only quota backup;
current and previous UTC ledger aliases preserve cooldowns through rollover.
Snapshots merge conservatively before any API call. The daily encrypted file is
never uploaded or rewritten by the special job and byte equality is checked on
persistence. The logs expose only counts, stages and diagnostic codes.

Section responses use an enum for block kinds and canonical requirement IDs;
planned activities are allocated by section. Structural failures retry only that
section with bounded, persisted diagnostics. Genuine repeated activity content
is rejected. Section-local activity identifiers are namespaced during assembly.
Missing coverage receives at most the existing configured number of additional
source-grounded sections, followed by all unchanged review stages. The versioned
migration requeues only the three addressed preparation refusal codes and retains
accepted sections, rejection history and request counters. A literal evidence ID
cannot prove an arbitrary calendar date; explicit calendar witnesses are checked.

CI must pass before merging. A normal authorized main push wakes the same mutex;
if another production run is active, let it finish saving its checkpoint. An
optional owner dispatch uses daily-v31.yml, phase=run, preview=false, blank date.
Do not dispatch while a suitable production run is queued or active. No new cron,
closed trial, Codespace, paid model or separate key is needed.

A successful producer only proves saved progress. Publication requires all eight
approved articles, the source/rights gates, final issue audit, real-page browser
checks, Pages deployment, and HTTPS verification of overview/archive/eight pages.
Original 003 and the daily homepage remain unchanged. The next queue wake verifies
the delivered issue and persists COMPLETED before daily generation resumes.

After saved progress, `special-continue` can dispatch the SAME workflow once,
under the same root mutex. It has scoped `actions: write`, but no Gemini or draft
key. It restores counts-only accounting, checks quota/cooldown and other queued
production, and never dispatches after zero requests or a terminal priority hold.
The persisted priority lifetime/productive-run/stall limits also bound the chain.
No cron or request limit changes. The existing cron remains the fallback after
cooldown, quota exhaustion, or dispatch failure.
