"""Bounded, checkpointable API accounting. No credentials or prose in the ledger."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import time


class GenerationPaused(RuntimeError):
    """A later run may continue without rewriting accepted work."""


class EvidenceRejected(ValueError, RuntimeError):
    """The available sources cannot support this commissioned story."""


class RequestBudget:
    def __init__(self, ledger, persist=lambda: None, *, run_limit=None, day_limit=None,
                 gap=None, seconds=None):
        self.ledger = ledger
        self.persist = persist
        self.run_limit = int(run_limit if run_limit is not None else os.getenv('NEWS_MAX_REQUESTS_PER_RUN', '24'))
        self.day_limit = int(day_limit if day_limit is not None else os.getenv('NEWS_MAX_REQUESTS_PER_DAY', '180'))
        self.gap = float(gap if gap is not None else os.getenv('NEWS_REQUEST_GAP_SECONDS', '6'))
        self.deadline = time.monotonic() + float(seconds if seconds is not None else os.getenv('NEWS_STAGE_SECONDS', '720'))
        if not 1 <= self.run_limit <= 40 or not 1 <= self.day_limit <= 300 or not 0 <= self.gap <= 60:
            raise ValueError('Unsafe request budget configuration')
        self.used = 0
        self.last = None

    def reserve(self, model):
        day = datetime.now(timezone.utc).date().isoformat()
        if self.ledger.get('day') != day:
            self.ledger.clear()
            self.ledger.update(day=day, requests=0, models={})
        now = time.monotonic()
        if self.used >= self.run_limit or self.ledger['requests'] >= self.day_limit:
            raise GenerationPaused('API request budget exhausted; encrypted progress retained')
        if now + self.gap + 155 >= self.deadline:
            raise GenerationPaused('Stage time budget reached; allow checkpoint upload before timeout')
        cooldown = self.ledger.setdefault('cooldowns', {}).get(model, 0)
        if cooldown > time.time():
            raise GenerationPaused('Model cooldown active; resume in a later run')
        if self.last is not None:
            time.sleep(max(0, self.gap - (now - self.last)))
        self.last = time.monotonic()
        self.used += 1
        self.ledger['requests'] += 1
        models = self.ledger['models']
        models[model] = models.get(model, 0) + 1
        self.persist()  # reserve BEFORE the network call, including errors

    def defer(self, model, seconds):
        self.ledger.setdefault('cooldowns', {})[model] = time.time() + max(1, seconds)
        self.persist()


ACTIVE_BUDGET = None
CHECKPOINT = None


def checkpoint():
    if CHECKPOINT:
        CHECKPOINT()
