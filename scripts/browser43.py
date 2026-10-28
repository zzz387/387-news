"""Synthetic browser regression for dynamic daily and link-only releases, no API."""
import json,shutil,tempfile,argparse
from pathlib import Path
try:from scripts import policy41 as p,browser41,publication43
except ImportError:import policy41 as p,browser41,publication43


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--synthetic',action='store_true',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    from scripts.test_daily43 import root,state,NOW
    from scripts.daily43 import reserve_rows
    report={}
    for count in (0,1,3):
        with tempfile.TemporaryDirectory(prefix='387-browser43-synthetic-') as temp:
            working=root(temp);s=state(count);publication43.build(s,working,reserve_rows(s,NOW))
            with tempfile.TemporaryDirectory(prefix='387-browser43-shots-') as images:
                report[str(count)]=browser41.check(working,s['date'],images,expected_count=count)
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n');print('[browser43-synthetic] '+json.dumps(report))


if __name__=='__main__':main()
