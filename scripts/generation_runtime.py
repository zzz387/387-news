"""Bounded, checkpointable API accounting. No credentials or prose in the ledger."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import time
import copy


def quota_labels(day):
    """Immutable snapshots of ONE shared ledger, including the same-run special tail."""
    return ('387news31-quota-'+day, '387news31-quota-'+day+'-special-003-r')


def merge_snapshot(ledger, snapshot):
    """Recover reservations conservatively; cooldowns survive UTC day rollover."""
    if not snapshot:
        return ledger
    for item in (ledger, snapshot):
        if item and (not isinstance(item.get('day'), str) or type(item.get('requests')) is not int
                     or item['requests'] < 0 or not isinstance(item.get('models'), dict)
                     or not isinstance(item.get('cooldowns', {}), dict)):
            raise ValueError('Invalid quota recovery snapshot; refusing API calls')
        for value in item.get('models', {}).values():
            if type(value) is not int or value < 0: raise ValueError('Invalid model accounting')
        for value in item.get('cooldowns', {}).values():
            if type(value) not in (int, float) or value < 0: raise ValueError('Invalid model cooldown')
    cf_rows=[copy.deepcopy(d['cloudflare_ai']) for d in (ledger,snapshot) if d.get('cloudflare_ai')]
    import math
    for record in cf_rows:
        if (not isinstance(record,dict) or not isinstance(record.get('day'),str) or type(record.get('requests')) is not int or record['requests']<0
                or any(type(record.get(n,0)) not in (int,float) or not math.isfinite(record.get(n,0)) or record.get(n,0)<0 for n in ('reserved_neurons','estimated_neurons','cooldown_until'))):raise ValueError('Invalid Cloudflare quota snapshot')
    if len({r.get('account_hash') for r in cf_rows})>1:raise ValueError('Cloudflare account mismatch')
    cooldowns={model:max(ledger.get('cooldowns',{}).get(model,0),snapshot.get('cooldowns',{}).get(model,0))
               for model in set(ledger.get('cooldowns',{})) | set(snapshot.get('cooldowns',{}))}
    if snapshot['day'] > ledger.get('day',''):
        ledger.clear();ledger.update(copy.deepcopy(snapshot))
    elif snapshot['day'] == ledger.get('day'):
        ledger['requests']=max(ledger['requests'],snapshot['requests'])
        models=ledger.setdefault('models',{})
        for model,count in snapshot['models'].items():models[model]=max(models.get(model,0),count)
    ledger['cooldowns']=cooldowns
    if cf_rows:
        if any(not isinstance(r,dict) or not isinstance(r.get('day'),str) or not isinstance(r.get('requests'),int) or r['requests']<0 for r in cf_rows):raise ValueError('Invalid Cloudflare quota snapshot')
        if len({r.get('account_hash') for r in cf_rows})!=1:raise ValueError('Cloudflare account mismatch')
        current=max(cf_rows,key=lambda r:r['day']);merged=copy.deepcopy(current)
        for name in ('reserved_neurons','estimated_neurons','requests','cooldown_until'):
            merged[name]=max(r.get(name,0) for r in cf_rows if r['day']==current['day'])
        merged['cooldown_until']=max(r.get('cooldown_until',0) for r in cf_rows)
        observed=[r.get('observed_account_neurons') for r in cf_rows if r['day']==current['day'] and isinstance(r.get('observed_account_neurons'),(int,float))]
        merged['observed_account_neurons']=max(observed,default=None)
        ledger['cloudflare_ai']=merged
    return ledger


class GenerationPaused(RuntimeError):
    """A later run may continue without rewriting accepted work."""


class EvidenceRejected(ValueError, RuntimeError):
    """The available sources cannot support this commissioned story."""


class RequestBudget:
    def __init__(self, ledger, persist=lambda: None, *, run_limit=None, day_limit=None,
                 gap=None, seconds=None):
        if not isinstance(ledger, dict):
            raise ValueError('Invalid request ledger')
        if ledger.get('day') and (type(ledger.get('requests')) is not int
                                  or ledger['requests'] < 0
                                  or not isinstance(ledger.get('models'), dict)
                                  or not isinstance(ledger.get('cooldowns', {}), dict)):
            raise ValueError('Invalid persisted request accounting; refusing API calls')
        self.ledger = ledger
        self.persist = persist
        self.run_limit = int(run_limit if run_limit is not None else os.getenv('NEWS_MAX_REQUESTS_PER_RUN', '24'))
        self.day_limit = int(day_limit if day_limit is not None else os.getenv('NEWS_MAX_REQUESTS_PER_DAY', '180'))
        self.gap = float(gap if gap is not None else os.getenv('NEWS_REQUEST_GAP_SECONDS', '6'))
        self.deadline = time.monotonic() + float(seconds if seconds is not None else os.getenv('NEWS_STAGE_SECONDS', '720'))
        if not 1 <= self.run_limit <= 40 or not 1 <= self.day_limit <= 300 or not 0 <= self.gap <= 60:
            raise ValueError('Unsafe request budget configuration')
        self.used = 0
        self.usage_counter = None  # optional v4.1 stage telemetry, saved with the reservation
        self.last = None

    def remaining_requests(self):
        day = datetime.now(timezone.utc).date().isoformat()
        used_today = self.ledger.get('requests',0) if self.ledger.get('day')==day else 0
        return max(0,min(self.run_limit-self.used,self.day_limit-used_today))

    def remaining_seconds(self):
        return max(0,self.deadline-time.monotonic())

    def can_request(self):
        # Inspection does not reset the ledger or reserve an extra request.
        return self.remaining_requests()>0 and self.remaining_seconds()>self.gap+155

    def reserve(self, model):
        day = datetime.now(timezone.utc).date().isoformat()
        if self.ledger.get('day') != day:
            cooldowns=dict(self.ledger.get('cooldowns',{}))
            cloudflare=copy.deepcopy(self.ledger.get('cloudflare_ai'))
            self.ledger.clear()
            self.ledger.update(day=day, requests=0, models={},cooldowns=cooldowns)
            if cloudflare:self.ledger['cloudflare_ai']=cloudflare
        now = time.monotonic()
        if self.used >= self.run_limit or self.ledger['requests'] >= self.day_limit:
            raise GenerationPaused('API request budget exhausted; encrypted progress retained')
        if now + self.gap + 155 >= self.deadline:
            raise GenerationPaused('Stage time budget reached; allow checkpoint upload before timeout')
        cooldowns=self.ledger.setdefault('cooldowns', {})
        cooldown = max(cooldowns.get(model,0),cooldowns.get('__all_models__',0))
        if cooldown > time.time():
            raise GenerationPaused('Model cooldown active; resume in a later run')
        if self.last is not None:
            time.sleep(max(0, self.gap - (now - self.last)))
        self.last = time.monotonic()
        self.used += 1
        self.ledger['requests'] += 1
        if self.usage_counter is not None:
            self.usage_counter['http_requests'] = self.usage_counter.get('http_requests',0)+1
        models = self.ledger['models']
        models[model] = models.get(model, 0) + 1
        print(f'[budget] request reserved run={self.used}/{self.run_limit} '
              f'day={self.ledger["requests"]}/{self.day_limit} model={model}', flush=True)
        self.persist()  # reserve BEFORE the network call, including errors

    def defer(self, model, seconds):
        self.ledger.setdefault('cooldowns', {})[model] = time.time() + max(1, seconds)
        self.persist()


ACTIVE_BUDGET = None
CHECKPOINT = None


def checkpoint():
    if CHECKPOINT:
        CHECKPOINT()
