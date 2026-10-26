"""Read-only admission: trial must not consume unfinished production's quota."""
from datetime import datetime,timedelta,timezone
try:
    from scripts import policy41 as p,release_queue
except ImportError:
    import policy41 as p
    import release_queue


def production_date(now=None):
    now=now or datetime.now(p.TZ)
    return (now.astimezone(p.TZ).date()+timedelta(days=1)).isoformat()


def assess(root,production,ledger,now=None):
    now=(now or datetime.now(p.TZ)).astimezone(p.TZ)
    if now.strftime('%H:%M')<p.RELEASE_TIME or not release_queue.edition_exists(root,now.date().isoformat()):
        return False,'CURRENT_PRODUCTION_NOT_PUBLISHED'
    target=production_date(now)
    if (not production or production.get('date')!=target or production.get('branch')!='main'
            or production.get('preview') is not False or production.get('audit_passed') is not True
            or production.get('stage')!='audited'):
        return False,'UPCOMING_PRODUCTION_NOT_APPROVED'
    required=p.ARTICLE_COUNT if production.get('version')==41 else 8 if production.get('version')==31 else None
    if required is None or len(production.get('articles',{}))!=required:
        return False,'UPCOMING_PRODUCTION_INCOMPLETE'
    if (not isinstance(ledger,dict) or type(ledger.get('requests',0)) is not int
            or ledger.get('requests',0)<0): return False,'SHARED_LEDGER_INVALID'
    used=ledger.get('requests',0) if ledger.get('day')==now.astimezone(timezone.utc).date().isoformat() else 0
    # Application limits remain 24/run and 220/day. Admit only a spare full run.
    if 220-used<24: return False,'NO_SPARE_TRIAL_RUN_QUOTA'
    return True,'PRODUCTION_READY_AND_QUOTA_SPARE'
