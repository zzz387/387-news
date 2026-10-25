"""Checkpointable, attributed repair; accepted prose is retained until replacement passes."""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import json
import os
try:
    from scripts import audit_policy as policy, editorial31 as editorial, news
except ImportError:
    import audit_policy as policy
    import editorial31 as editorial
    import news


def record_veto(state, findings, persist=lambda:None):
    digest = policy.fingerprint(state)
    state.update(audit_passed=False,stage='audit_veto')
    state['audit_note'] = json.dumps(findings,ensure_ascii=False)
    state.setdefault('audit_history',[]).append({'at':datetime.now(timezone.utc).isoformat(),
        'fingerprint':digest,'issues':copy.deepcopy(findings)})
    state.setdefault('audit_failed_fingerprints',{})[digest] = True
    print('[AUDIT VETO] '+policy.safe_diagnostic(findings)+'; private reasons checkpointed',flush=True)
    if (any(f['action']=='hold' for f in findings)
            or state.get('audit_rounds',0)>=policy.MAX_AUDITS
            or state.get('audit_repair_rounds',0)>=policy.MAX_REPAIR_ROUNDS):
        state['audit_blocked'] = 'Editorial diagnosis or repair limit requires plan review'
        persist()
        return
    targets = {target for f in findings for target in f['repair_ids']}
    counts = state.setdefault('audit_story_repairs',{})
    if any(counts.get(policy.story_key(state['plan'][i-1]),0)>=policy.MAX_REPAIRS_PER_STORY for i in targets):
        state['audit_blocked'] = 'Repeated attributable veto for the same story; no automatic rewriting'
        persist()
        return
    state['audit_repair_rounds'] = state.get('audit_repair_rounds',0)+1
    queue = state.setdefault('audit_repairs',{})
    for target in sorted(targets):
        selected = [f for f in findings if target in f['repair_ids']]
        queue[str(target-1)] = {'action':selected[0]['action'],'issues':copy.deepcopy(selected),'attempts':0}
    for finding in findings:
        if finding['action']=='reorder_issue':
            state['article_order'] = [i-1 for i in finding['order']]
            print('[audit-repair] composition reordered; all article texts retained',flush=True)
    state.pop('audit_blocked',None)
    persist()


def process_repairs(state, persist=lambda:None):
    if state.get('audit_blocked'):
        print('[audit-repair] bounded hold; accepted articles retained, no API calls',flush=True)
        return
    queue = state.setdefault('audit_repairs',{})
    for slot in list(queue):
        repair = queue[slot]
        if repair['attempts']>=policy.MAX_REPAIRS_PER_STORY:
            state['audit_blocked'] = 'Targeted revision failed twice; source/plan review required'
            persist()
            return
        plan = state['plan'][int(slot)]
        article = state['articles'][slot]
        dossier = state['dossiers'][slot]
        if repair['action']=='replace_story':
            state.setdefault('audit_retained_articles',[]).append({'slot':slot,'article':copy.deepcopy(article),
                'plan':copy.deepcopy(plan),'issues':repair['issues']})
            state.setdefault('rejected',{})[slot] = 'Attributed final audit requires a different source-backed story'
            state['articles'].pop(slot)
            queue.pop(slot)
            persist()
            continue
        try:
            candidate = dossier.get('_audit_revision_candidate')
            if candidate is None:
                candidate = editorial.revise_after_audit(article,plan,dossier,repair['issues'])
                dossier['_audit_revision_candidate'] = candidate
                persist()
            editorial.article_form(candidate,plan)
            editorial.verify_article(candidate,plan,dossier,{s['id']:s for s in state['sources']})
            candidate['slug'] = news.slugify(candidate['title'],int(slot)+1)
        except news.runtime.GenerationPaused:
            raise
        except ValueError as exc:
            repair['attempts'] += 1
            repair['issues'].append(policy.issue('article_quality',scope='article',article_ids=[int(slot)+1],
                repair_ids=[int(slot)+1],action='revise_article',reason=str(exc),instruction=str(exc)))
            dossier.pop('_audit_revision_candidate',None)
            print(f'[audit-repair] article={int(slot)+1} targeted revision rejected; original retained',flush=True)
            persist()
            continue
        state.setdefault('audit_retained_articles',[]).append({'slot':slot,'article':copy.deepcopy(article),
            'plan':copy.deepcopy(plan),'issues':repair['issues']})
        state['articles'][slot] = candidate
        dossier.pop('_audit_revision_candidate',None)
        key = policy.story_key(plan)
        counts = state.setdefault('audit_story_repairs',{})
        counts[key] = counts.get(key,0)+1
        state.setdefault('rejections',{}).pop(slot,None)
        queue.pop(slot)
        print(f'[audit-repair] article={int(slot)+1} corrected and fact-reviewed; other articles unchanged',flush=True)
        persist()


def recover_legacy_article(state, prior):
    """Only inside Actions: undo an un-attributed legacy eviction, then require a new audit."""
    if os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REF_NAME')!='main':
        raise RuntimeError('Private recovery is restricted to GitHub Actions on main')
    if state.get('legacy_audit_recovered'):
        return
    if not state.get('audit_note','').startswith('Issue editorial veto: '):
        raise RuntimeError('Prior article recovery requires an un-attributed legacy issue veto')
    for name,value in (('version',31),('preview',False),('branch','main')):
        if state.get(name)!=value or prior.get(name)!=value:
            raise RuntimeError('Private recovery provenance mismatch')
    if (state['date']!=prior['date'] or state['plan']!=prior['plan'] or state['sources']!=prior['sources']
            or len(state['articles'])!=7 or len(prior['articles'])!=8):
        raise RuntimeError('Private recovery edition or plan mismatch')
    if any(a!=prior['articles'].get(slot) for slot,a in state['articles'].items()):
        raise RuntimeError('Private recovery would discard accepted progress')
    missing = set(prior['articles'])-set(state['articles'])
    if len(missing)!=1:
        raise RuntimeError('Private recovery requires exactly one legacy eviction')
    slot = missing.pop()
    article = prior['articles'][slot]
    plan = state['plan'][int(slot)]
    if (article.get('_review_scope')!='title_teaser_body_v1'
            or article.get('source_ids')!=plan['source_ids']
            or state['dossiers'][slot]['claims']!=prior['dossiers'][slot]['claims']):
        raise RuntimeError('Prior accepted article has no matching reviewed evidence')
    editorial.article_form(article,plan)
    state.setdefault('audit_history',[]).append({'legacy':True,'issues':[policy.issue('unattributed',
        reason=state['audit_note'])],'legacy_revisions':copy.deepcopy(state.get('revisions',{}))})
    state['articles'][slot] = copy.deepcopy(article)
    if state.get('rejected',{}).get(slot)=='Repeated issue audit veto':
        state['rejected'].pop(slot)
    state.setdefault('rejections',{}).pop(slot,None)
    state.update(legacy_audit_recovered=True,audit_passed=False,stage='ready_for_audit')
    print(f'[audit-recovery] restored previously fact-reviewed article={int(slot)+1}; '
          'seven accepted articles and current quota retained; full structured audit still required',flush=True)
