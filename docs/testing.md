# Test workflow

Use targeted existing tests during edits, then one QUICK run for the affected
components. Do not repeatedly run the complete suite on unchanged code.

```
python -m scripts.run_tests --quick
python -m scripts.run_tests --quick --component stock --component delivery
python -m scripts.run_tests --quick --changed scripts/daily43.py
python -m scripts.run_tests --full --report /tmp/unit-summary.json
```

QUICK selects a critical base plus component-related modules. FULL discovers all
maintained unit tests, including migration, safety, quota, encryption and active
special-release checks. Failures return nonzero and print their names/tracebacks.
Successful cases and synthetic diagnostics go to the log, not standard output.
The summary records actual test counts, duration and the five slowest cases.
CI keeps detailed logs and JSON for seven days. Required check names stay intact.

Current policy 4.4 browser rendering is always checked in CI at 320, 390, 768 and
1440 pixels, including source/translation links, long text and short notes.
Legacy 4.1/4.3 browser fixtures run when shared assets/readers or legacy generators
change. External translation-provider probes run when their integration changes.
Live source discovery probes run when the catalog or source extraction changes.
An unavailable or untrustworthy diff base enables all these probes conservatively.
Production schedules do not run CI browser/source jobs. Special checks retain
their existing dedicated workflow and access restrictions.

The November 13 audit found 49 test files, 623 tests and no exact duplicate test
bodies. Historical tests cover code still shipped, migrations or active special
paths, so they were not deleted merely to reduce a number. Two single-case process
entrypoint files were consolidated without losing either scenario. Known-incident
regressions remain separate from stylistic or implementation-detail assertions.

Nine small content-classifier methods were combined into two named subtest tables.
All positive/negative cases remain, including Russian inflections, NHS guidance,
Ironman, animal stories, computing terms, hotel sleep, stale categories and health
metaphors. The real published-issue regression stays separate. Final inventory:
48 test files and 621 test methods (plus their existing parameterized subcases).
