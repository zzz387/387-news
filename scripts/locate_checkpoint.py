#!/usr/bin/env python3
"""Choose the newest unexpired encrypted checkpoint, without downloading it.

The official actions/download-artifact step handles cross-run artifact ZIP
retrieval, avoiding intermittent HTTP 401 errors from the direct REST redirect.
"""
from __future__ import annotations
from datetime import datetime
import os
from urllib.parse import quote
try:
    from scripts import staged_news
except ImportError:
    import staged_news


def newest_artifact(records: list, label: str) -> dict | None:
    eligible = [x for x in records if x.get('name') == label and not x.get('expired')
                and isinstance(x.get('id'), int)]
    if not eligible:
        return None
    return max(eligible, key=lambda x: (x.get('created_at', ''), x['id']))


def main():
    phase = os.environ.get('PHASE','').strip()
    if phase not in ('auto','plan','research','write','audit','publish','check'):
        raise RuntimeError('Unknown requested phase')
    raw_date = os.environ.get('TARGET_DATE','').strip() or None
    date = staged_news.phase_date(phase,datetime.now(staged_news.TZ),raw_date)
    preview = os.environ.get('PREVIEW','false').lower() == 'true'
    label = staged_news.artifact_label(date,preview)
    repo = os.environ['GITHUB_REPOSITORY']
    def records_for(name):
        result = []
        for page in range(1, 11):
            api = f'https://api.github.com/repos/{repo}/actions/artifacts?per_page=100&name={quote(name)}&page={page}'
            batch = staged_news.request_json(api).get('artifacts')
            if not isinstance(batch, list):
                raise RuntimeError('Invalid GitHub Artifacts response; refusing empty restore')
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise RuntimeError('Artifact listing exceeded pagination bound; refusing uncertain restore')

    records = records_for(label)
    if any(x.get('name') == label and x.get('expired') for x in records) and not newest_artifact(records, label):
        raise RuntimeError('Saved checkpoint expired; cannot safely restart this issue')
    newest = newest_artifact(records,label)
    outputs = {'found': 'true' if newest else 'false'}
    if newest:
        # actions/download-artifact@v4 defaults to the CURRENT run, even
        # when artifact-ids points to an artifact from an earlier run.
        # The repository artifacts API includes workflow_run.id (source run).
        source_run = (newest.get('workflow_run') or {}).get('id')
        if type(source_run) is not int or source_run <= 0:
            raise RuntimeError('Checkpoint artifact has no valid source workflow run ID; refusing unsafe restore')
        outputs['artifact_id'] = str(newest['id'])
        outputs['run_id'] = str(source_run)
        print(f'[checkpoint] selected encrypted checkpoint artifact ID={newest["id"]} '
              f'from previous workflow run {source_run}', flush=True)
    else:
        print('[checkpoint] no existing encrypted checkpoint for this date/mode',flush=True)
    # Global daily ledger prevents resetting quota when issue date/mode changes.
    quota = newest_artifact(records_for(staged_news.quota_label()), staged_news.quota_label())
    if quota:
        run = (quota.get('workflow_run') or {}).get('id')
        if type(run) is not int or run <= 0:
            raise RuntimeError('Quota artifact has no valid source workflow run ID')
        outputs.update(quota_found='true', quota_id=str(quota['id']), quota_run_id=str(run))
    out = os.environ.get('GITHUB_OUTPUT')
    if not out:
        raise RuntimeError('GITHUB_OUTPUT not set')
    with open(out, 'a', encoding='utf-8') as fh:
        for k,v in outputs.items():
            fh.write(f'{k}={v}\n')

if __name__ == '__main__':
    main()
