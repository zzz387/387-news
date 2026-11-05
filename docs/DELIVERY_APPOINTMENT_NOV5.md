# 2026-11-05: approved11 restored, delivery independent of the next morning cron

## Observed facts

Main844561f had11 approved articles saved in production checkpoint13369981841,
from run41926706180 at01:36 Moscow. Watcher41936956572 at02:51 returned NOT_DUE:
its90-minute appointment horizon started only at04:30. No morning production
runs were visible before41982181673 was created at09:42. The latest preceding
configured morning slot was08:15, so the eventual scheduled execution appeared
at least87 minutes late. GitHub's API does not disclose the internal reason for
absent/delayed schedule events; this is not evidence of a PR34 scheduler change.
Both workflows execute, YAML parses, main/permissions gates pass, and there was
no active producer holding the morning production mutex in the visible history.

The09:42 run restored11, used0 Gemini requests, and failed BEFORE commit on
BROWSER_HORIZONTAL_OVERFLOW. Policy4.3 lacked4.1's complete-reader wrapping.
PR36 added wrapping without truncation, preserved the browser check, and extended
synthetic stress coverage. Production41983382810 restored the same11 and passed
44 real page/viewport checks, commit, Pages and HTTPS at09:54 Moscow. No articles
were regenerated; hashes, source panels, translations, home and archive were
checked by the existing public verifier. The current incident was reconciled.

## Minimal delivery changes

The EXISTING watcher now arms within five hours of06:00. A successful night
producer already invokes it through workflow_run; the existing watchdog cron adds
01:43/02:43 Moscow opportunities. One waiting watcher uses its existing separate
mutex, no Gemini, no draft Secret and no production mutex. Sleep is idle; it does
not repeatedly download checkpoints. At05:54 it dispatches the SAME production
workflow, phase=publish, preview=false, explicit current date. Main's existing
commit gate still waits until06:00, allowing private rendering/browser checks
before the release time. Retries/HTTPS polling run until06:10, not05:54+10min.

phase=publish is explicit delivery-only for4.3: no source discovery, writing,
headline improvement, light-news generation or model calls. It retains normal
saved-article hash/rights/safety eligibility and can use the valid no-AI source
digest if nothing is approved. Already committed editions retry delivery without
rewriting their articles. Unchanged materials do not undergo a model audit.

Legacy run and new publish recoveries keep the same Delivery YYYY-MM-DD title,
so the same public run history/incident attempt counter prevents retry resets.
Before dispatch the watcher checks both current HTTPS and active main production,
then rechecks them. The producer retains its shared mutex; a delivery dispatch
cannot start special003-R. Three attempts,12-minute recovery spacing, safe
incident deduplication and immutable archives remain in force.

## Resource and platform boundaries

The single appointment is bounded to five hours, plus up to10 minutes of result
checks. Job timeout330 minutes stays below the hosted360-minute maximum. The
normal producer's wait remains10 minutes and timeout30 minutes. The repository
uses the existing public hosted Actions infrastructure; no paid service, key,
Secret, Repository Variable or DNS change is introduced. There is no polling
Gemini or competing production while the watcher waits. This consciously uses
one bounded idle job instead of relying on an uncreated06:00 cron event.

This does not guarantee service during a GitHub Actions/Pages outage or if no
night event starts the appointment. No connected Cloudflare management tools or
Cloudflare runtime credentials exist in this session, and no Worker configuration
is present in the repository. An authenticated external timer therefore cannot
be deployed here without a separate authorized connection; no public unauthenticated
production endpoint or exported GitHub key was created. Future night timing still
needs observation in the real calendar: fake-clock tests are not that evidence.

Existing policy4.3, the20 personal interests, light news, target12 with partial or
zero-article releases, fact/copyright checks and24/run220/day quotas are preserved.
