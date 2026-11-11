"""4.4 synthetic browser check: actual uncapped output at four viewport widths."""
import argparse,json,tempfile
from pathlib import Path
from scripts import browser41,publication43
from scripts.test_policy44 import issue,root

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temp,tempfile.TemporaryDirectory() as shots:
        target=root(temp);s=issue(20,16);publication43.build(s,target)
        report=browser41.check(target,s['date'],shots,expected_count=20)
        report.update(policy_version='4.4',main_articles=20,light_notes=16,synthetic=True)
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n');print('[browser44-synthetic] '+json.dumps(report))
if __name__=='__main__':main()
