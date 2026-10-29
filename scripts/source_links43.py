"""Reader links from verified source metadata only; no network or model calls."""
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import quote,urlencode,urlparse
try:from scripts import source41,policy41 as p
except ImportError:import source41,policy41 as p

LANGUAGES={'ru':'русский','en':'английский','de':'немецкий','fr':'французский','es':'испанский',
 'it':'итальянский','pt':'португальский','zh':'китайский','ja':'японский','ko':'корейский',
 'uk':'украинский','be':'белорусский','pl':'польский','cs':'чешский','sk':'словацкий',
 'nl':'нидерландский','sv':'шведский','no':'норвежский','da':'датский','fi':'финский',
 'et':'эстонский','lv':'латышский','lt':'литовский','el':'греческий','tr':'турецкий',
 'ar':'арабский','he':'иврит','hi':'хинди','bn':'бенгальский','vi':'вьетнамский',
 'th':'тайский','id':'индонезийский','ms':'малайский','ro':'румынский','hu':'венгерский',
 'bg':'болгарский','sr':'сербский','hr':'хорватский','sl':'словенский','ka':'грузинский',
 'hy':'армянский','az':'азербайджанский','kk':'казахский','uz':'узбекский','fa':'персидский',
 'is':'исландский','ga':'ирландский','ca':'каталанский','eu':'баскский','af':'африкаанс',
 'sw':'суахили','ta':'тамильский','ur':'урду','fil':'филиппинский','mk':'македонский'}


def language_code(value):
    code=value.strip().lower().replace('_','-').split('-')[0] if isinstance(value,str) else ''
    return code if code in LANGUAGES else ''


def language_name(value):return LANGUAGES.get(language_code(value),'язык не определён')


def safe_source_url(url):
    if not isinstance(url,str) or re.search(r'[\x00-\x20\x7f]',url):raise p.Blocked('SOURCE_URL_UNSAFE')
    try:
        source41.safe_url(url);parsed=urlparse(url);parsed.port
    except (ValueError,TypeError):raise p.Blocked('SOURCE_URL_UNSAFE')
    return url


def translation_url(url,language=None,*,provider='yandex'):
    url=safe_source_url(url);code=language_code(language)
    if code=='ru':return None
    if provider=='yandex':
        # Target-only direction requests automatic detection; never assume English.
        return 'https://translate.yandex.ru/translate?'+urlencode({'url':url,'lang':code+'-ru' if code else 'ru'},quote_via=quote)
    if provider=='google':
        return 'https://translate.google.com/translate?'+urlencode({'sl':code or 'auto','tl':'ru','u':url},quote_via=quote)
    raise ValueError('TRANSLATOR_UNSUPPORTED')


def html_source(source,prefix=''):
    url=safe_source_url(source['url']);language=source.get('language');code=language_code(language)
    html=('<p data-source-links-version="1" data-source-language="'+code+'">'+escape(prefix)+'Источник: '+
          escape(source['publisher'])+' — «'+escape(source['title'])+'» ('+language_name(language)+'): '+
          '<a class="source-original" href="'+escape(url,quote=True)+'" target="_blank" rel="noopener noreferrer">Оригинал</a>.</p>')
    translated=translation_url(url,language)
    if translated:html+='<p>Перевод оригинала: <a class="source-translation" href="'+escape(translated,quote=True)+'" target="_blank" rel="noopener noreferrer">Читать на русском в Яндекс Переводчике</a>.</p>'
    return html


def md_escape(text):return re.sub(r'([\\\[\]<>])',r'\\\1',str(text))


def markdown_source(source,prefix=''):
    url=safe_source_url(source['url']);language=source.get('language')
    target=quote(url,safe=":/?#[]@!$&'*+,;=%")
    text=prefix+'Источник: '+md_escape(source['publisher'])+' — «'+md_escape(source['title'])+'» ('+language_name(language)+'): [Оригинал](<'+target+'>).'
    translated=translation_url(url,language)
    if translated:text+='\n\nПеревод оригинала: [Читать на русском в Яндекс Переводчике](<'+translated+'>).'
    return text


def validate(page,required=False):
    class Reader(HTMLParser):
        def __init__(self):super().__init__();self.markers=[];self.links=[]
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if 'data-source-links-version' in attrs:self.markers.append(attrs)
            if tag=='a' and set(attrs.get('class','').split())&{'source-original','source-translation'}:self.links.append(attrs)
    reader=Reader();reader.feed(page)
    if not reader.markers:
        if required:raise p.Blocked('SOURCE_LINKS_REQUIRED')
        return False  # immutable historical releases remain valid
    if len(reader.markers)!=1 or reader.markers[0]['data-source-links-version']!='1':raise p.Blocked('SOURCE_LINKS_FORMAT')
    language=reader.markers[0].get('data-source-language','')
    if language and language not in LANGUAGES:raise p.Blocked('SOURCE_LANGUAGE_INVALID')
    originals=[a for a in reader.links if 'source-original' in a.get('class','').split()]
    translated=[a for a in reader.links if 'source-translation' in a.get('class','').split()]
    if len(originals)!=1 or len(translated)!=(0 if language=='ru' else 1):raise p.Blocked('SOURCE_LINK_COUNT')
    original=safe_source_url(originals[0].get('href'))
    if translated and translated[0].get('href')!=translation_url(original,language):raise p.Blocked('TRANSLATION_SOURCE_MISMATCH')
    if any(a.get('target')!='_blank' or not {'noopener','noreferrer'}<=set(a.get('rel','').split()) for a in reader.links):raise p.Blocked('SOURCE_LINK_SECURITY')
    return True
