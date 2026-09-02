#!/usr/bin/env python3
import asyncio,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import updater
RAIL='railway-account-token-abcdefghijklmnopqrstuvwxyz';GITHUB='github-fine-grained-token-abcdefghijklmnopqrstuvwxyz';SHA='a'*40;calls=[]
def fake(url,*,method='GET',headers=None,payload=None,timeout=12.0):
 calls.append((url,method,headers or {},payload or {}))
 if url.endswith('/repos/publisher/project/releases/latest'):return {'tag_name':'v17.1.0','html_url':'https://github.com/publisher/project/releases/tag/v17.1.0','published_at':'2026-09-02T00:00:00Z'}
 if url.endswith('/repos/user/project') and method=='GET':return {'full_name':'user/project','fork':True,'parent':{'full_name':'publisher/project'},'default_branch':'main'}
 if url.endswith('/merge-upstream'):return {'message':'Successfully synced','merge_type':'fast-forward'}
 if url.endswith('/commits/main'):return {'sha':SHA}
 if url==updater.RAILWAY_GRAPHQL:
  query=(payload or {}).get('query','')
  if 'query { me' in query:return {'data':{'me':{'id':'u1','email':'a@example.com'}}}
  if 'serviceInstanceDeployV2' in query:return {'data':{'serviceInstanceDeployV2':'deployment-1'}}
 raise AssertionError((url,method,payload))
async def main():
 with tempfile.TemporaryDirectory() as d:
  os.environ['RAILWAY_SERVICE_ID']='service-1';os.environ['RAILWAY_ENVIRONMENT_ID']='environment-1'
  updater.configure(d,'master-secret');updater._state={};updater._cache={'at':0.0,'value':None};updater._request_json=fake
  await updater.load();assert not updater.setup_status()['configured']
  public=await updater.save_setup({'upstream_repo':'','fork_repo':'user/project','branch':'main','railway_token':RAIL,'github_token':GITHUB});assert public['configured'] and public['upstream_repo']=='publisher/project' and RAIL not in json.dumps(public) and GITHUB not in json.dumps(public)
  raw=(Path(d)/'lumen_update.json').read_text();assert RAIL not in raw and GITHUB not in raw and 'gAAAA' in raw
  latest=await updater.check_latest(force=True);assert latest['available'] and latest['latest_version']=='17.1.0'
  result=await updater.apply_latest();assert result['started'] and result['commit']=='a'*12 and result['deployment']=='deployment-1'
  deploy=[c for c in calls if c[0]==updater.RAILWAY_GRAPHQL and 'serviceInstanceDeployV2' in c[3].get('query','')][-1];assert deploy[3]['variables']['commitSha']==SHA and deploy[2]['Authorization']=='Bearer '+RAIL
  merge=[c for c in calls if c[0].endswith('/merge-upstream')][-1];assert merge[3]=={'branch':'main'} and merge[2]['Authorization']=='Bearer '+GITHUB
  await updater.clear_setup();assert not (Path(d)/'lumen_update.json').exists()
asyncio.run(main())
print('updater v17: encrypted=OK fork-verify=OK release-check=OK sync=OK railway-deploy=OK secrets-redacted=OK')
