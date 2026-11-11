"""PC-independent scanner runner; evidence reviews remain explicit input, never fabricated."""
from base64 import b64encode,b64decode
from datetime import datetime,timezone
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import requests

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'cache'/'opportunity-scanner'
STATE_FILE='monitor-state.json'
STATE_KEYS={'attribution_reviews':'attribution_reviews.json','push_delivery':'push_delivery.json',
            'notified':'notified.json'}

def api(method,repo,**kwargs):
    response=requests.request(method,f'https://api.github.com/repos/{repo}/contents/{STATE_FILE}',
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2026-03-10','User-Agent':'DowngradeResearchScanner/1.0'},
        timeout=(8,30),**kwargs)
    if response.status_code==404 and method=='GET':return None
    if not response.ok:raise ValueError(f'GitHub cloud-state {method} failed (HTTP {response.status_code})')
    return response.json()

def read_remote(repo):
    response=api('GET',repo)
    return (json.loads(b64decode(response['content'])),response['sha']) if response else ({},None)

def restore(state):
    CACHE.mkdir(parents=True,exist_ok=True)
    for key,name in STATE_KEYS.items():
        if key in state:(CACHE/name).write_text(json.dumps(state[key],indent=2)+'\n',encoding='utf8')

def snapshot(previous):
    state=dict(previous)
    for key,name in STATE_KEYS.items():
        path=CACHE/name
        if path.exists():state[key]=json.loads(path.read_bytes())
    return state

def save_remote(repo,state,old,sha):
    if state==old:return
    payload={'message':'Update monitor delivery and review state [skip ci]',
             'content':b64encode((json.dumps(state,indent=2)+'\n').encode()).decode()}
    if sha:payload['sha']=sha
    api('PUT',repo,json=payload)

def main():
    repo=os.environ.get('GITHUB_REPOSITORY','')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('GITHUB_REPOSITORY is missing or invalid')
    from opportunity_push import config,publish
    if not os.environ.get('GITHUB_TOKEN') or not config():
        raise ValueError('GitHub workflow token and a configured phone notification channel are required')
    event_path=os.environ.get('GITHUB_EVENT_PATH')
    if not event_path or json.loads(Path(event_path).read_bytes()).get('repository',{}).get('private') is not False:
        raise ValueError('Zero-cost guard: this runner requires a public GitHub repository')
    old,sha=read_remote(repo)
    restore(old)
    failure=None
    try:
        run=subprocess.run([sys.executable,'-X','utf8','research/opportunity_scanner.py','--scheduled'],cwd=ROOT)
        if run.returncode:failure='The public-data scanner failed; no complete check can be confirmed.'
        if not failure and os.environ.get('CLOUD_SEND_TEST')=='1':
            receipt=publish(config(),'TEST - Cloud-Scanner auf GitHub',
                'Dieser Test kommt direkt von GitHub Actions. Dein PC wird fuer diesen Cloud-Lauf nicht benoetigt. Kein Handelssignal. Technische Einstiegssignale werden als Nachrichtenpruefung ausstehend gekennzeichnet.')
            save=ROOT/'cache'/'opportunity-scanner'/'cloud_test_receipt.json'
            save.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    finally:
        state=snapshot(old)
        report=ROOT/'outputs'/'opportunity-scanner'/'latest.json'
        if report.exists():
            latest=json.loads(report.read_bytes())
            state['last_market_session']=latest.get('expected_completed_session')
            state['last_price_session']=latest.get('latest_price')
            state['last_ratings_session']=latest.get('latest_ratings')
            summary=os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                Path(summary).write_text('# Technology downgrade monitor\n\n'+
                    f"Checked: {latest.get('asof_berlin')}\n\n"+
                    f"Prices through {latest.get('latest_price')}; ratings through {latest.get('latest_ratings')}.\n\n"+
                    f"Phone delivery: {json.dumps(latest.get('phone_push',{}))}\n\n"+
                    f"Warnings: {json.dumps(latest.get('warnings',[]))}\n\n"+
                    'Technical candidates require independent news review. No orders submitted.\n',encoding='utf8')
        test=CACHE/'cloud_test_receipt.json'
        if test.exists():state['cloud_test']=json.loads(test.read_bytes())
        if failure:
            state['last_failure']={'reason':failure,'at_utc':datetime.now(timezone.utc).isoformat()}
        elif 'last_failure' in state:
            del state['last_failure']
        # An API conflict is a failure, not permission to overwrite a concurrently edited review.
        save_remote(repo,state,old,sha)
    if failure:raise ValueError(failure)

if __name__=='__main__':main()
