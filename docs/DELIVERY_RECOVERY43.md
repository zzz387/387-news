# Daily delivery recovery — policy4.3

## Incident on30 October2026

At the first inspection, GitHub's latest production schedule run was40988700336,
created at04:55:47 Moscow. It restored12/12 approved articles and finished at04:56
with stageAPPROVED, next_action=publish_when_due and zero model calls. Pages was
correctly skipped because release time had not arrived. The monitor was not due.
No later scheduled production run existed in the API, including the05:54 and
post06:00 recovery opportunities. The workflow reported active, cron expressions
were valid UTC schedules and no producer was active/queued. GitHub does not expose
why a scheduled event was delayed or dropped. Provider scheduling delay/loss is
therefore probable, not a proved internal GitHub cause; PR28 is not evidence of
causing missing cron events.

The urgent official job rerun at07:21 restored12/12, built the release with zero
Gemini requests, then exposed a separate code defect introduced in PR28: the
script-mode browser entry point used a late package-only source_links43 import.
PR30 fixes both import compatibility and the production module entry point, with
a fresh-process script-loader regression. The saved delivery counter and its
10-minute backoff were respected; neither quota nor attempts were reset.

Production41003444835 then committed the Oct30 edition in5dfcdba88eb84f8d988cf719f132053f43eefafa,
passed48 real article/viewport checks and verified the public12-article release
at07:33:29 Moscow. The incident was closed by the HTTPS monitor. Historical issues
and source translation links remain unchanged. See the Actions logs for evidence.

## Independent watcher

`.github/workflows/delivery-watchdog.yml` is not downstream of prepare/deploy.
It has its own cron, a protected-main push/manual trigger and a trusted-main
workflow_run completion trigger. It reads only public HTTPS/metadata, never
Secrets, encrypted drafts or model APIs. Its lock is separate from the existing
producer lock, so it cannot prevent preparation while waiting for release.

A wake between04:30 and06:00 arms a bounded06:00 appointment inside the watcher.
It can therefore deliver after an observed04:55 producer completion without
requiring any new post06:00 schedule event. Earlier wakes report normal waiting.
Each individual wait is at most30 seconds; the appointment is at most90 minutes.
The existing ten-minute producer commit gate and06:00 publication prohibition are
unchanged. A public GitHub-hosted runner is used; no paid or external resource is
created.

After06:00 the watcher uses the existing complete HTTPS checks (home/date,
overview, archive, every article/Markdown, checksums, source-link format). If
healthy, it does not dispatch or regenerate. If a producer is active or queued it
waits. Otherwise it dispatches only daily-v31.yml on main with phase=run,
preview=false,target_date=today. The controller restores its own official
checkpoint and prioritizes delivery without Gemini, including a zero-article
verified source digest. The producer's original mutex/idempotent publication
prevents parallel generation and duplicate archives even across races.

Each watcher sends at most one dispatch. At most three dated recovery dispatches
are allowed per Moscow date, observed from run metadata and bot-authored incident
counters. A12-minute recovery gap respects the controller delivery backoff.
Uncertain/incomplete API metadata fails closed. Failed/delayed dispatches are
recorded without assuming an HTTP204 response contains JSON. Only bot-authored
incidents can carry retry state; public Issue text cannot trigger production.
Failure after a bounded10-minute verification window opens/updates one safe
incident; later verified delivery closes it and retains attempt history.

## States

The existing editorial stage remains for compatible checkpoints. A separate
publication_status explicitly reports PREPARING, WAITING_FOR_RELEASE,
READY_TO_PUBLISH, PUBLISHING, PUBLISHED_VERIFIED or PUBLICATION_FAILED. A prepared
or committed issue is never labelled HTTPS-verified. Normal pre06:00 waiting is
successful; missing HTTPS delivery after due is an actionable failure. Policy4.3
special-priority flags cannot suppress a daily-publication failure.

The12-article preparation target, variable publication count, quality gates,
original language/translation links, shared24/run and220/day model limits,
request intervals/cooldowns and all private artifact paths are unchanged.

## Operational checks and external independence

Inspect both Actions workflows and publication_status. Watchdog incidents use
fixed codes, not raw exceptions/private prose. Re-run the existing producer with
an explicit current date for delivery; do not reset its counters or replace a
checkpoint when Pages is stale. Verify all public checks before claiming success.
For a current edition already verified, normal runs prepare the following date.

An additional GitHub cron alone does not guarantee06:00 during a GitHub-wide
outage. The pre-armed appointment and workflow_run event reduce dependency on
cron, but still share the Actions platform. A truly external free timer would
need separately owner-approved hosting and a repository-scoped Actions credential
or GitHub App installation. No such service/Secret has been added. GitHub Pages
alone cannot act as a reliable server-side scheduler; an unauthenticated public
production trigger is deliberately not provided. Exact delivery during a total
GitHub/Pages outage cannot be guaranteed.
