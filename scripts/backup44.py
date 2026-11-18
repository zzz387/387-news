"""Copy existing encrypted Actions snapshots without opening drafts or keys."""
import hashlib,json,os,re,subprocess,zipfile
from pathlib import Path

BASE='6d311ac68ee93bb9be4d38e45ebf40dbe60b4306'
LABEL=re.compile(r'387news31-(?:production-\d{4}-\d{2}-\d{2}|quota-\d{4}-\d{2}-\d{2}(?:-special-003-r)?)$|387news43-editorial-stock$|387news41-special-003-r$')

def choose(rows):
    result={}
    for row in rows:
        if not LABEL.fullmatch(row.get('name','')) or row.get('expired'):continue
        if row.get('workflow_run',{}).get('head_branch')!='main':continue
        previous=result.get(row['name'])
        if previous is None or row['id']>previous['id']:result[row['name']]=row
    names=list(result)
    if not any(n.startswith('387news31-production-') for n in names) or not any(n.startswith('387news31-quota-') for n in names) or '387news43-editorial-stock' not in names:
        raise RuntimeError('BACKUP_REQUIRED_STATE_MISSING')
    if sum(r['size_in_bytes'] for r in result.values())>250*1024*1024:raise RuntimeError('BACKUP_SIZE_REQUIRES_REVIEW')
    return list(result.values())

def main():
    if os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REPOSITORY')!='zzz387/387-news' or os.getenv('GITHUB_REF_NAME')!='main':raise RuntimeError('BACKUP_PROTECTED_MAIN_REQUIRED')
    output=Path(os.environ['RUNNER_TEMP'])/'pre-mosaic-backup';output.mkdir()
    repo='zzz387/387-news';rows=[]
    for page in range(1,101):
        data=json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/actions/artifacts?per_page=100&page={page}'],text=True))
        batch=data['artifacts'];rows.extend(batch)
        if len(batch)<100:break
    else:raise RuntimeError('BACKUP_ARTIFACT_LIST_INCOMPLETE')
    selected=choose(rows);manifest={'baseline_sha':BASE,'backup_branch':'backup/pre-mosaic-20261118-6d311ac','snapshots':[],'secrets':'remain in existing GitHub Secrets; values never copied','restore_rule':'Restore code through a reviewed revert. Preserve CURRENT quota/cooldowns and all later published archives; never replace them with older counters.'}
    subprocess.run(['git','bundle','create',str(output/'public-repository.bundle'),'--all'],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['git','bundle','verify',str(output/'public-repository.bundle')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['git','archive','--format=tar.gz','-o',str(output/'public-release.tar.gz'),BASE],check=True)
    for row in selected:
        target=output/(str(row['id'])+'.zip')
        with target.open('wb') as file:subprocess.run(['gh','api',f'repos/{repo}/actions/artifacts/{row["id"]}/zip'],check=True,stdout=file)
        with zipfile.ZipFile(target) as archive:
            if archive.testzip() is not None:raise RuntimeError('BACKUP_ZIP_CORRUPT')
        manifest['snapshots'].append({'id':row['id'],'name':row['name'],'file':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    for name in ('public-repository.bundle','public-release.tar.gz'):manifest[name]=hashlib.sha256((output/name).read_bytes()).hexdigest()
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('[backup44] '+json.dumps({'baseline_sha':BASE,'snapshots':len(selected),'verified':True,'decrypted':False,'gemini_requests':0}))

if __name__=='__main__':main()
