# Policy 4.3 implementation and delivery

## Scope and current facts

The former 4.1 pipeline spent 220 request reservations on 27 October UTC: 48 daily,
172 special. It produced no finally approved special article. Five real special
works failed substantive independence checks; those refusals are not converted
into approvals. Temporary 503s were not the final blocker.

The existing `daily-v31.yml` remains the sole production scheduler, with its
original mutex, 24/run and 220/day guard, six-second spacing, persisted cooldowns,
AES-GCM checkpoints, official artifact restoration, Pages deployment, and HTTPS
monitor. No Secrets or Repository Variables change. Schedule and 06:00 Moscow
remain unchanged. GitHub scheduling and Pages availability cannot be guaranteed.

`config/daily43.json` is the new daily policy switch. Historical 4.1 modules and
configuration remain available to validate old editions, checkpoints and tests;
they no longer impose their count/depth/audit rules on new 4.3 daily production.

## Smaller active path

* Source and rights: existing full-source extractor and documented rights rules.
* Existing complete drafts and chosen A/B/C modes are retained. New ordinary
  candidates default to C rather than an unsolicited long full translation.
* C: one complete independently written narrow aspect, followed by one combined
  substantive audit of all reader content, facts, safety, rights and headline.
  It need not reproduce all source topics, a source's activity count or style.
* A: lawful full original, one combined audit. B: saved full translation operations
  plus one combined audit. Source coverage remains deterministic and complete.
* Risky advice requires independent competent source material before model work;
  its adequacy and actual claims are checked by the final reviewer. Quotes must
  bind to exact source blocks; news event dates need a literal calendar witness.
* At most two content repairs. A bad candidate is deferred; other accepted works
  remain. Exact duplicate blocks are normalized locally for C. There is no issue
  composition AI audit, mandatory genre/category balance, depth or word count.
* Normally C costs two model operations, A one, B translation operations plus one.
  Eight C notes: 16 operations before transport retries. Actual HTTP attempts,
  including malformed answers and 429/503, still use the one global ledger.

Before 06:00 the controller prepares useful material. At/after the release time,
it immediately uses every admitted article (1, 3, 8, 12, 13, etc.). If none is
admitted, it uses a source digest without Gemini. Eight is only a preparation
orientation. Due delivery never waits for the next candidate or API allowance.

## Reserve and public format

`config/fallback-sources43.json` contains bibliographic metadata from the existing
public source verification report, not article bodies or private dossiers. A
link digest explicitly says there are no new full articles. It displays source
titles, publishers, actual dates where recorded, URLs and the check timestamp.
Cached checks can be used for 14 days with that date visible. Older entries need
a fresh permitted full-source check; refresh work is bounded to eight attempts.
No usable reserve means an explicit incident, not a fabricated placeholder.

CI freshly checks real fallback sources without Secrets or Gemini. Production
can reuse the prechecked cache during provider outages. It never copies source
bodies into a digest. Its refreshed metadata is kept in the normal encrypted
checkpoint and only final public metadata is projected to the issue.

HTML, Markdown, the homepage counter, archive and HTTPS validation all understand
zero-article source digests and dynamic article counts. `release.json` contains
only public release metadata and final-file hashes. HTTPS delivery checks those
hashes, the actual date, all article pages, Markdown and archive navigation.
Only that check can report publication as verified; committing HTML is not proof.

## Preservation and queue

Special production/self-dispatch are paused in the existing workflow, with an
entrypoint guard as well. №003-R ciphertext, drafts, histories and quota remain
unchanged. The historic №003 is never edited. A 4.1 daily checkpoint migrates by
retaining its complete old payload inside the existing encrypted checkpoint;
complete drafts can receive the new final gate without being rewritten.

An older unfinished issue cannot seize today's date forever. It remains under
its original artifact label, with its original date and existing 90-day retention.
It is not relabelled or silently published as today's news. New dates have their
own checkpoints; delivery retries reuse the committed immutable issue, with the
existing bounded delivery retry mechanism. This is not indefinite archival:
longer retention needs an owner-approved private storage plan.

## Safe rollout

1. Review and pass the PR's full tests, public sources and browser CI.
2. Merge the reviewed implementation into main within owner deployment authority.
   The documentation itself does not grant production authority.
3. The existing push trigger acquires the production mutex. Do not dispatch a
   parallel producer. It restores the daily/special accounting snapshot officially.
4. Verify the 4.3 migration, unchanged ledger and special pause in safe logs. A due
   empty daily issue must build a clearly labelled source digest with zero Gemini
   requests, then use the existing browser/commit/Pages/HTTPS jobs.
5. Check the actual public overview, article count/kind and all manifest hashes.
   Close the delivery incident only after verified HTTPS.
6. Observe independent subsequent scheduled restoration and delivery. Before
   06:00 generation may resume only within the existing free quota/cooldown.
7. Keep №003-R paused until daily operation is stable and its queue is deliberately
   re-enabled. Never reset either checkpoint or the quota to do so.

Rollback: restore the policy-routing/workflow changes through a reviewed commit;
keep all already published issues immutable and retain the 4.3 ciphertext. Do not
feed a 4.3 checkpoint into an older engine, erase accounting, force-push or delete
artifacts. Keeping delivery of the existing committed public issue available is
safer than trying to regenerate an archive.
