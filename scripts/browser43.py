"""Synthetic browser regression for dynamic daily and link-only releases, no API."""
import json,shutil,tempfile,argparse
from pathlib import Path
try:from scripts import policy41 as p,browser41,publication43
except ImportError:import policy41 as p,browser41,publication43


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--synthetic',action='store_true',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    from scripts.test_daily43 import root,state,RESERVE_FIXTURE
    report={}
    for count in (0,1,8,12):
        with tempfile.TemporaryDirectory(prefix='387-browser43-synthetic-') as temp:
            working=root(temp);s=state(count)
            if count==12:
                from scripts import editorial43
                languages=['ru','en','de','fr',None,'es','it','zh-Hans','uk','ja','pt','sv']
                for row,language in zip(s['candidates'],languages):
                    row['source']['language']=language
                    row['source']['title']=('Непереносимоедлинноеназваниеисточника'*8)+' '+str(row['id'])
                    row['checks']['final43']['input_hash']=editorial43.fingerprint(row)
            from scripts.test_editorial_visual43 import light_ready
            n={0:0,1:1,8:3,12:5}[count]
            s['light43']={'records':[light_ready(i) for i in range(n)]}
            publication43.build(s,working,[RESERVE_FIXTURE])
            with tempfile.TemporaryDirectory(prefix='387-browser43-shots-') as images:
                report[str(count)]=browser41.check(working,s['date'],images,expected_count=count)
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n');print('[browser43-synthetic] '+json.dumps(report))


if __name__=='__main__':main()
