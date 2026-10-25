"""Structured editorial decisions. Free-form reasons stay in encrypted state only."""
from __future__ import annotations
import hashlib
import json

CODES = ('article_quality','unsupported_claim','article_form','stale_news','duplicate_topic',
         'composition','diversity','category_balance','issue_volume','unattributed','invalid_response')
ACTIONS = ('revise_article','replace_story','reorder_issue','hold')
LABELS = {
    'article_quality':'literary quality of identified article',
    'unsupported_claim':'identified article requires factual correction',
    'article_form':'identified article fails editorial form',
    'stale_news':'identified news item is stale',
    'duplicate_topic':'identified stories overlap',
    'composition':'issue composition needs correction',
    'diversity':'identified stories lack diversity',
    'category_balance':'mandatory issue balance is not met',
    'issue_volume':'Total below editorial floor',
    'unattributed':'issue veto has no actionable attribution',
    'invalid_response':'audit response is incomplete or inconsistent',
}
MAX_AUDITS = 6
MAX_REPAIRS_PER_STORY = 2
MAX_REPAIR_ROUNDS = 4


def issue(code, *, scope='issue', article_ids=(), repair_ids=(), action='hold', reason='', instruction='', order=()):
    return dict(scope=scope,code=code,article_ids=list(article_ids),repair_ids=list(repair_ids),
                action=action,reason=reason,instruction=instruction,order=list(order))


class AuditRejected(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('; '.join(LABELS.get(i['code'],LABELS['invalid_response']) for i in issues))


def validate_response(result):
    """Do not guess targets from prose, length, score, or malformed model output."""
    if not isinstance(result,dict) or type(result.get('approve')) is not bool:
        raise AuditRejected([issue('invalid_response')])
    findings = result.get('issues')
    if not isinstance(findings,list) or len(findings)>8:
        raise AuditRejected([issue('unattributed',reason=json.dumps(result,ensure_ascii=False))])
    if result['approve']:
        if findings:
            raise AuditRejected([issue('invalid_response',reason=json.dumps(result,ensure_ascii=False))])
        return
    if not findings:
        raise AuditRejected([issue('unattributed',reason=json.dumps(result,ensure_ascii=False))])
    for finding in findings:
        if not isinstance(finding,dict):
            raise AuditRejected([issue('invalid_response')])
        ids = finding.get('article_ids'); targets = finding.get('repair_ids'); order = finding.get('order')
        valid_ids = lambda v: (isinstance(v,list) and all(type(x) is int and 1<=x<=8 for x in v)
                              and len(v)==len(set(v)))
        valid = (finding.get('scope') in ('article','issue') and finding.get('code') in CODES
                 and finding.get('action') in ACTIONS and valid_ids(ids) and valid_ids(targets)
                 and valid_ids(order) and set(targets)<=set(ids)
                 and isinstance(finding.get('reason'),str) and bool(finding['reason'].strip())
                 and isinstance(finding.get('instruction'),str))
        if valid and finding['scope']=='article':
            valid = len(ids)==1 and finding['action'] in ('revise_article','replace_story','hold')
        if valid and finding['action'] in ('revise_article','replace_story'):
            valid = bool(targets) and bool(finding['instruction'].strip()) and not order
        if valid and finding['action']=='reorder_issue':
            valid = finding['scope']=='issue' and finding['code']=='composition' and set(order)==set(range(1,9)) and not targets
        if valid and finding['action']=='hold':
            valid = not targets and not order
        if not valid:
            raise AuditRejected([issue('invalid_response',reason=json.dumps(result,ensure_ascii=False))])
    # Conflicting fixes need diagnosis; do not partially apply an ambiguous plan.
    actions = {}
    for finding in findings:
        for target in finding['repair_ids']:
            if target in actions and actions[target] != finding['action']:
                raise AuditRejected([issue('invalid_response',reason=json.dumps(result,ensure_ascii=False))])
            actions[target] = finding['action']
    if sum(f['action']=='reorder_issue' for f in findings)>1:
        raise AuditRejected([issue('invalid_response',reason=json.dumps(result,ensure_ascii=False))])
    raise AuditRejected(findings)


def fingerprint(state):
    data = {'articles':state.get('articles',{}),'plan':state.get('plan',[]),
            'order':state.get('article_order',list(range(8)))}
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def story_key(plan):
    data = {k:plan.get(k) for k in ('title','source_ids','long')}
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def safe_diagnostic(findings):
    return '; '.join(f"scope={f['scope']} code={f['code']} affected={f['article_ids']} "
                    f"repair={f['repair_ids']} action={f['action']}: {LABELS[f['code']]}" for f in findings)
