"""Bounded public-only source check session: cache robots, pace each origin, no retries."""
import threading,time
from urllib.parse import urlparse
from scripts import source41


class Session:
    def __init__(self,timeout=25):self.timeout=timeout;self.locks={};self.cache={};self.last={};self.blocked={};self.guard=threading.Lock()
    def transport(self,url):
        origin=urlparse(url).netloc
        with self.guard:lock=self.locks.setdefault(origin,threading.Lock())
        with lock:
            if origin in self.blocked:raise self.blocked[origin]
            if url in self.cache:
                result=self.cache[url]
                if isinstance(result,Exception):raise result
                return result
            time.sleep(max(0,1.5-(time.monotonic()-self.last.get(origin,0))))
            self.last[origin]=time.monotonic()
            try:result=source41.transport(url) if self.timeout==25 else source41.transport(url,timeout=self.timeout)
            except Exception as exc:
                self.cache[url]=exc
                if getattr(exc,'code',None) in (429,503):self.blocked[origin]=exc
                raise
            self.cache[url]=result;return result
    def fetch(self,url):return source41.fetch(url,get=self.transport)
