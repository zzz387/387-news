"""Validate and promote an audited checkpoint entirely inside GitHub Actions.

No private material or key is exported. Only the existing encrypted artifact
is read and another encrypted artifact is written with the same repository key.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
try:
    from scripts import staged_news as stage, editorial31 as ed
except ImportError:
    import staged_news as stage
    import editorial31 as ed

EXPECTED_DATE = '2026-10-26'
EXPECTED_BRANCH = 'codex/autonomous-editorial-recovery'


def validate_prepared(state):
    if (state.get('version') != 31 or state.get('date') != EXPECTED_DATE
            or state.get('branch') != EXPECTED_BRANCH or state.get('preview') is not True
            or state.get('stage') != 'audited' or state.get('audit_passed') is not True):
        raise RuntimeError('Unexpected prepared checkpoint provenance or approval state')
    if len(state.get('plan', [])) != 8 or set(state.get('articles', {})) != {str(i) for i in range(8)}:
        raise RuntimeError('Prepared issue must contain exactly eight approved articles')
    lookup = {s['id']:s for s in state['sources']}
    total = 0
    for i, plan in enumerate(state['plan']):
        article = state['articles'][str(i)]
        total += ed.article_form(article, plan)
        if (article.get('_review_scope') != 'title_teaser_body_v1'
                or article['category'] != plan['category'] or article['kind'] != plan['kind']
                or article['source_ids'] != plan['source_ids']
                or article.get('long') != bool(plan['long'])):
            raise RuntimeError('Prepared article differs from its reviewed commission')
        if not all(sid in lookup for sid in article['source_ids']):
            raise RuntimeError('Prepared article lost its public source references')
        claims = state['dossiers'][str(i)]['claims']
        if len(claims) < (8 if plan['long'] else 5):
            raise RuntimeError('Insufficient literal source evidence in saved dossier')
        for claim in claims:
            sid = claim['source_id']
            if sid not in article['source_ids'] or ed.normalized(claim['quote']) not in ed.normalized(lookup[sid]['evidence']):
                raise RuntimeError('Saved source quotation no longer matches the saved evidence')
    if not 2 <= sum(bool(p['long']) for p in state['plan']) <= 3 or total < ed.TARGET_TOTAL:
        raise RuntimeError('Prepared issue fails the unchanged editorial volume requirements')
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--promote', action='store_true')
    args = parser.parse_args()
    if os.getenv('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Private checkpoint restoration is restricted to GitHub Actions')
    key = stage.validate_key(os.environ['DRAFT_ENCRYPTION_KEY'])
    state = stage.decipher(Path(os.environ['NEWS_CHECKPOINT_FILE']).read_bytes(), key)
    total = validate_prepared(state)
    stage.render(state, True)  # full private temporary HTML build and link validation
    print(f'[prepared] validated 8/8 articles, {total} words; no Gemini calls or private exports')
    if not args.promote:
        return
    if os.getenv('GITHUB_REF_NAME') != 'main':
        raise RuntimeError('Only main may promote the audited checkpoint to production')
    state.update(branch='main', preview=False)
    stage.save(state, key)
    output = os.environ['GITHUB_OUTPUT']
    with open(output, 'a', encoding='utf-8') as f:
        f.write('checkpoint=true\n')
        f.write(f'artifact_name={stage.artifact_label(state["date"],False)}\n')
    print('[prepared] same dated issue saved as encrypted production checkpoint; release time gate unchanged')

if __name__ == '__main__':
    main()
