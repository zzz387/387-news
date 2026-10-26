"""Single executable policy configuration; no editorial length thresholds."""
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'config/editorial.json').read_text(encoding='utf-8'))
VERSION=CONFIG['version']
ARTICLE_COUNT=CONFIG['article_count']
CATEGORIES=tuple(CONFIG['categories'])
REQUIRED=frozenset(CONFIG['required_categories'])
TZ=ZoneInfo(CONFIG['timezone'])
RELEASE_TIME=CONFIG['release_time']
MODES=tuple(CONFIG['modes'])
STAGES=('source_verified','content_prepared','fact_checked','completeness_checked','editorial_checked','ready_to_publish')


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class Blocked(ValueError):
    def __init__(self,code,detail=''):
        self.code=code; self.detail=detail
        super().__init__(code)  # Safe public diagnostic; detail remains in the private checkpoint.
