"""Compact offline QUICK/FULL entrypoint; detailed diagnostics stay in a log."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
COMPONENTS={
    'editorial':['test_policy44','test_daily43','test_review_wire43','test_editorial_topic_coverage43'],
    'delivery':['test_site_checks','test_delivery_watchdog','test_pipeline','test_delivery_appointment43','test_entrypoints43'],
    'stock':['test_minimum_stock43','test_stock_recovery43','test_checkpoint_restore','test_crossrun_restore'],
    'sources':['test_topic_discovery_checkpoint43','test_priorities43','test_source_links43'],
    'safety':['test_policy41','test_family_light43','test_independence_protocol41','test_gemini_probe'],
    'special':['test_special003r','test_special43','test_special_priority41'],
}
BASE=['test_policy44','test_site_checks','test_delivery_watchdog']

def quick_modules(components=(),changed=()):
    names=list(BASE)
    for group in components:names.extend(COMPONENTS[group])
    for file in changed:
        name=Path(file).name
        if name.startswith('test_') and name.endswith('.py'):names.append(name[:-3]);continue
        groups=[]
        if any(s in name for s in ('daily','editorial','selection','policy44','light')):groups+=['editorial','safety']
        if any(s in name for s in ('publication','site_check','release','watchdog','workflow','pipeline')) or '.github/' in file:groups+=['delivery']
        if any(s in name for s in ('stock','checkpoint','staged')):groups+=['stock']
        if any(s in name for s in ('catalog','source','priorities')):groups+=['sources']
        if 'special' in name:groups+=['special']
        for group in groups:names.extend(COMPONENTS[group])
    return ['scripts.'+name for name in dict.fromkeys(names)]

class Result(unittest.TextTestResult):
    def startTest(self,test):
        self.started=time.monotonic();super().startTest(test)
    def stopTest(self,test):
        self.timings.append((round(time.monotonic()-self.started,3),test.id()));super().stopTest(test)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.timings=[]

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--quick',action='store_true');mode.add_argument('--full',action='store_true')
    parser.add_argument('--component',action='append',choices=COMPONENTS,default=[])
    parser.add_argument('--changed',nargs='*',default=[])
    parser.add_argument('--log',type=Path,default=Path('/tmp/387-news-tests.log'))
    parser.add_argument('--report',type=Path)
    args=parser.parse_args(argv);args.log.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    with args.log.open('w') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        loader=unittest.TestLoader()
        suite=loader.discover(str(ROOT/'scripts'),pattern='test_*.py') if args.full else loader.loadTestsFromNames(quick_modules(args.component,args.changed))
        result=unittest.TextTestRunner(stream=log,verbosity=0,resultclass=Result).run(suite)
    failed=len(result.failures)+len(result.errors)
    report={'mode':'FULL' if args.full else 'QUICK','tests':result.testsRun,'passed':result.testsRun-failed-len(result.skipped),'failed':failed,'skipped':len(result.skipped),'duration_seconds':round(time.monotonic()-started,2),'slowest':sorted(result.timings,reverse=True)[:5]}
    print('Tests: {tests}\nPassed: {passed}\nFailed: {failed}\nSkipped: {skipped}\nDuration: {duration_seconds}s'.format(**report))
    print('Details: '+str(args.log))
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n')
    for test,trace in result.failures+result.errors:print(str(test)+'\n'+trace,file=sys.stderr)
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
