"""Strict public projection: never serialize a research checkpoint to the site."""
import hashlib
import json
from urllib.parse import urlparse

ARTICLE_FIELDS = ('title','teaser','category','kind','long','source_ids','word_count','character_count','slug')
SOURCE_FIELDS = ('id','url','title','published')


def public_article(article):
    result = {k:article[k] for k in ARTICLE_FIELDS if k in article}
    result['paragraphs'] = [{k:p.get(k,'') for k in ('heading','text')} for p in article['paragraphs']]
    return result


def public_issue(state, number):
    articles = [public_article(state['articles'][str(i)]) for i in state.get('article_order',range(8))]
    used = {sid for a in articles for sid in a['source_ids']}
    sources = {s['id']:{k:s[k] for k in SOURCE_FIELDS if k in s}
               for s in state['sources'] if s['id'] in used}
    if used != set(sources) or any(urlparse(s['url']).scheme != 'https' for s in sources.values()):
        raise RuntimeError('Public references must be present and use HTTPS')
    return {'date':state['date'],'number':number,'articles':articles,'sources':sources}


def content_digest(issue):
    content = {k:issue[k] for k in ('date','articles','sources')}
    return hashlib.sha256(json.dumps(content,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def markdown(issue):
    lines = [f'# 387 News — {issue["date"]}', '']
    for a in issue['articles']:
        lines += [f'## {a["title"]}', '', f'{a["category"]} · {a["kind"]} · {a["word_count"]} слов', '', a['teaser'], '']
        for p in a['paragraphs']:
            if p['heading']:
                lines += [f'### {p["heading"]}', '']
            lines += [p['text'], '']
        lines += ['### Публичные источники', '']
        for sid in a['source_ids']:
            source = issue['sources'][sid]
            lines += [f'- {source["title"]} — {source["url"]} ({source.get("published","")})']
        lines.append('')
    return '\n'.join(lines)
