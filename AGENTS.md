# Working on 387 News

Keep policy 4.4, the existing controller, encrypted Actions checkpoints, shared
quota ledger, 06:00 Moscow release and historical archives intact. Private drafts,
research and keys stay inside protected GitHub Actions; never download them.

Start with the affected component, its immediate dependencies and related tests.
Do not read the entire repository or test directory for routine changes.

After a small fix, run its existing targeted test; rerun only after a relevant
change or failure. At the end of a logical change run QUICK, for example:

    python -m scripts.run_tests --quick --changed scripts/daily43.py
    python -m scripts.run_tests --quick --component delivery

Before merging, require successful FULL CI (including required checks). FULL is
also appropriate after architectural, security or Actions changes:

    python -m scripts.run_tests --full

Do not repeat a passed suite on unchanged code without a specific reason. Do not
automatically add tests for trivial changes already covered by existing behavior.
Retain checkpoint, quota, safety, rights, fact-checking, deduplication, 4.4 minima,
HTML/HTTPS delivery, watchdog, idempotency and active special-release coverage.

Read filtered errors, tracebacks, diagnostic codes and summaries from Actions.
Do not load full successful workflow logs into context. The test runner prints
counts/duration and failures; its full log is an optional CI artifact. Reports
should be compact and distinguish a prepared issue from verified HTTPS publication.
