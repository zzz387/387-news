"""Explicit scenarios, not fabricated live Gemini measurements or editorial targets."""
import math


def estimate(mode,source_operations,review_operations,sections=4,support_operations=0,practical_operations=0):
    stages={'source_analysis':source_operations,'preparation':0,'fact_checked':review_operations,
            'completeness_checked':review_operations,'editorial_checked':review_operations,
            'independence':int(mode=='INDEPENDENT_ARTICLE'),'support_analysis':support_operations,
            'practical_manifest':practical_operations}
    if mode=='FULL_TRANSLATION': stages['preparation']=source_operations
    elif mode=='INDEPENDENT_ARTICLE': stages['preparation']=1+sections
    elif mode!='ORIGINAL_REPUBLICATION': raise ValueError('Unknown mode')
    return {'stages':stages,'operations':sum(stages.values()),
            'assumptions':{'review_operations':review_operations,'independent_sections':sections,
                           'retries':0,'generated_output_measured':False}}


def issue_scenario(articles,retry_fraction=.2,reserves=()):
    baseline=sum(a['operations'] for a in articles)+1
    planned=baseline+sum(a['operations'] for a in reserves)
    return {'article_count':len(articles),'baseline_http_without_retries':baseline,
            'including_reserves':planned,'with_retry_allowance':math.ceil(planned*(1+retry_fraction)),
            'day_limit':220,'retry_fraction':retry_fraction,
            'fits_daily_budget':math.ceil(planned*(1+retry_fraction))<=220,
            'warning':'Scenario only. Actual HTTP reservations, including errors, are recorded by stage and global ledger.'}


def actual_usage(state):
    result={}
    for owner in [state]+state.get('candidates',[]):
        for stage,value in owner.get('model_usage',{}).items():
            current=result.setdefault(stage,{'operations':0,'http_requests':0,'completed':0,'failures':0})
            for key in current: current[key]+=value.get(key,0)
    return result
