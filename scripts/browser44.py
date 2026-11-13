"""4.4 synthetic browser check: actual uncapped output at four viewport widths."""
import argparse,json,tempfile
from pathlib import Path
from scripts import browser41,publication43,editorial43
from scripts.test_policy44 import issue,root

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temp,tempfile.TemporaryDirectory() as shots:
        target=root(temp);s=issue(20,16);s['light43']['records'][0]['light_kind']='source_report'
        for row,language in zip(s['candidates'],['ru','en','de','fr',None,'es','it','zh-Hans']):
            row['source']['language']=language
            row['checks']['final43']['input_hash']=editorial43.fingerprint(row)
        row=s['candidates'][0]
        row['source']['title']+=' '+'НепереносимоеНазваниеИсточника'*8
        row['checks']['final43']['input_hash']=editorial43.fingerprint(row)
        # Keep full-body/long-word stress in the current reader, not just a legacy suite.
        row=s['candidates'][-1]
        row['article']['title']='НепереносимыйДлинныйЗаголовок'*7
        row['article']['blocks'].append({'kind':'paragraph','text':'Подробное учебное объяснение. '*500+'НепереносимоеУчебноеСлово'*20})
        row['checks']['final43']['input_hash']=editorial43.fingerprint(row)
        publication43.build(s,target)
        report=browser41.check(target,s['date'],shots,expected_count=20)
        report.update(policy_version='4.4',main_articles=20,light_notes=16,synthetic=True)
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n');print('[browser44-synthetic] '+json.dumps(report))
if __name__=='__main__':main()
