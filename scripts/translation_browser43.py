"""Nonblocking public-browser diagnostics. No Secrets, source bodies or model API."""
import argparse,json,re
from pathlib import Path
from datetime import datetime,timezone
from scripts import browser41,source_links43 as links

SAMPLES=[
 {'url':'https://www.unicef.org/parenting/child-development/baby-tips','language':'en','markers':[r'развити|реб[её]н|малыш',r'месяц|игр|родител']},
 {'url':'https://science.nasa.gov/solar-system/solar-system-facts/','language':'en','markers':[r'солнечн',r'планет']},
 {'url':'https://www.unicef.org/parenting/child-care/21-learning-activities-babies-and-toddlers','language':None,'markers':[r'заняти|игр',r'малыш|реб[её]н']},
]


def probe(context,sample,provider):
    url=links.translation_url(sample['url'],sample['language'],provider=provider)
    result={'original':sample['url'],'provider':provider,'url':url,'language':sample['language'],'verified':False,'code':'TRANSLATED_CONTENT_NOT_CONFIRMED'}
    page=context.new_page()
    try:
        response=page.goto(url,wait_until='domcontentloaded',timeout=30000)
        result['http_status']=response.status if response else None
        # Russian translator chrome/HTTP200 alone are explicitly insufficient.
        for attempt in range(8):
            for frame in page.frames:
                try:text=frame.locator('body').inner_text(timeout=1500)
                except Exception:continue
                if re.search(r'(?i)showcaptcha|smartcaptcha|/sorry/|/challenge/',frame.url):
                    result['code']='PROVIDER_ACCESS_CHALLENGE';continue
                if (len(re.findall('[А-Яа-яЁё]',text))>=180 and
                    all(re.search(pattern,text,re.I) for pattern in sample['markers'])):
                    result.update(verified=True,code='TRANSLATED_ORIGINAL_VISIBLE',frame_url=frame.url)
                    return result
            page.wait_for_timeout(1500)
        result['final_url']=page.url
    except Exception as exc:result['code']='BROWSER_'+type(exc).__name__.upper()
    finally:page.close()
    return result


def main():
    from playwright.sync_api import sync_playwright
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    rows=[]
    with sync_playwright() as playwright:
        browser=browser41.launch_browser(playwright);context=browser.new_context(locale='ru-RU')
        for sample in SAMPLES:
            result=probe(context,sample,'yandex');rows.append(result)
            if not result['verified']:rows.append(probe(context,sample,'google'))
        browser.close()
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'blocking':False,'gemini_requests':0,'samples':rows}
    destination=Path(args.output);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('[translation43-browser] '+json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
