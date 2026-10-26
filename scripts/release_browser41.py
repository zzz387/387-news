"""Check only fully released final HTML in the Actions worktree, before commit."""
import json
import os
from pathlib import Path
import re
import tempfile
try:
    from scripts import browser41,policy41 as p,site_checks,production_preflight41
except ImportError:
    import browser41
    import policy41 as p
    import site_checks
    import production_preflight41


def main():
    production_preflight41.require_pages()
    date=os.environ['ISSUE_DATE']
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):raise ValueError('RELEASE_DATE_INVALID')
    metadata=site_checks.validate_local_release(p.ROOT,date)
    overview=(p.ROOT/'issues'/date/'index.html').read_text()
    if 'data-policy-version="4.1"' not in overview:
        print('[release-browser] immutable legacy delivery; applicable historical validation passed');return
    if metadata['count']!=12:raise ValueError('RELEASE_TWELVE_ARTICLES_REQUIRED')
    with tempfile.TemporaryDirectory(prefix='387-final-browser-') as temp:
        report=browser41.check(p.ROOT,date,Path(temp))
    print('[release-browser] '+json.dumps(report))


if __name__=='__main__':main()
