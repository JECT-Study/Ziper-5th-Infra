#!/usr/bin/env python3
"""Provision dedicated Ziper identities/configuration without printing secret values."""
import base64,json,os,shlex,subprocess,sys,urllib.request
from pathlib import Path
os.umask(0o077)
SDK=os.environ.get('ZIPER_GCLOUD', 'gcloud')
PROJECT='ziper-production'; NUMBER='45190721178'; REGION='asia-southeast1'
PRIVATE=Path.home()/'.config/ziper/deployment'
DEPLOY=f'ziper-deployer@{PROJECT}.iam.gserviceaccount.com'
RUNTIME=f'ziper-runtime@{PROJECT}.iam.gserviceaccount.com'
INVOKER=f'ziper-edge-invoker@{PROJECT}.iam.gserviceaccount.com'
OIDC_SUBJECT='repo:JECT-Study@155141962/Ziper-5th-Server@1440603337:environment:production'
OIDC_LEGACY_SUBJECT='repo:JECT-Study/Ziper-5th-Server:environment:production'
OIDC_MAPPING={'google.subject':'assertion.sub','attribute.repository_id':'assertion.repository_id','attribute.ref':'assertion.ref'}

def oidc_condition(subject):
 return "assertion.repository_id == '1440603337' && assertion.ref == 'refs/heads/main' && assertion.sub == '"+subject+"'"

def ensure_wif_provider(pool, provider):
 args=['iam','workload-identity-pools','providers']
 location=['--location=global','--workload-identity-pool='+pool]
 expected=oidc_condition(OIDC_SUBJECT)
 current=run([*args,'describe',provider,*location],missing=True)
 if current is None:
  run([*args,'create-oidc',provider,*location,'--issuer-uri=https://token.actions.githubusercontent.com','--attribute-mapping='+','.join(k+'='+v for k,v in OIDC_MAPPING.items()),'--attribute-condition='+expected])
 else:
  if current.get('oidc',{}).get('issuerUri')!='https://token.actions.githubusercontent.com' or current.get('attributeMapping')!=OIDC_MAPPING:
   raise SystemExit('Unexpected WIF issuer or mapping drift; review before changing it')
  if current.get('attributeCondition')!=expected:
   if current.get('attributeCondition')!=oidc_condition(OIDC_LEGACY_SUBJECT):
    raise SystemExit('Unexpected WIF condition drift; review before changing it')
   run([*args,'update-oidc',provider,*location,'--attribute-condition='+expected])
 verified=run([*args,'describe',provider,*location])
 if verified.get('attributeCondition')!=expected or verified.get('attributeMapping')!=OIDC_MAPPING or verified.get('oidc',{}).get('issuerUri')!='https://token.actions.githubusercontent.com':
  raise SystemExit('WIF provider readback does not match the reviewed trust policy')

def run(args, data=None, missing=False):
 p=subprocess.run([SDK,*args,'--project',PROJECT,'--quiet','--format=json'],input=data,capture_output=True)
 if p.returncode:
  if missing and any(s in p.stderr for s in (b'NOT_FOUND',b'not found',b'does not exist')): return None
  print(json.dumps({'operation':args[:3],'result':'FAILED','diagnostic':p.stderr.decode(errors='replace').splitlines()[0][:250]}),flush=True)
  raise SystemExit(1)
 try:return json.loads(p.stdout)
 except ValueError:return {}

def ensure_sa(name):
 email=f'{name}@{PROJECT}.iam.gserviceaccount.com'
 if run(['iam','service-accounts','describe',email],missing=True) is None:
  run(['iam','service-accounts','create',name,'--display-name',name])
 print(json.dumps({'serviceAccount':name,'verified':True}),flush=True)
 return email

def project_role(member, role):
 run(['projects','add-iam-policy-binding',PROJECT,'--member',member,'--role',role,'--condition=None'])

def validate_spend_cap(value):
 cap=value.get('spendCap', {})
 filters=value.get('budgetFilter', {})
 if (cap.get('outputState') != 'CONFIGURED' or cap.get('reconciling') is True
     or value.get('amount', {}).get('specifiedAmount') != {'currencyCode':'KRW','units':'1000'}
     or filters.get('projects') != ['projects/'+NUMBER]
     or filters.get('services') != ['services/152E-C115-5142']
     or filters.get('creditTypesTreatment') != 'EXCLUDE_ALL_CREDITS'
     or filters.get('calendarPeriod') != 'MONTH'):
  raise SystemExit('Cloud Run spend cap is missing or does not match the production policy')

def main():
 cap=json.loads((PRIVATE/'gcp-spend-cap.json').read_text())
 token=subprocess.check_output([SDK,'auth','print-access-token'],text=True).strip()
 live=json.load(urllib.request.urlopen(urllib.request.Request('https://billingbudgets.googleapis.com/v1/'+cap['name'],headers={'Authorization':'Bearer '+token,'x-goog-user-project':PROJECT})))
 validate_spend_cap(live)
 print('Cloud Run monthly KRW 1000 spend cap: CONFIGURED (not an absolute cost guarantee)',flush=True)
 for n in ['ziper-deployer','ziper-runtime','ziper-edge-invoker']:ensure_sa(n)
 if run(['artifacts','repositories','describe','ziper-releases','--location',REGION],missing=True) is None:
  run(['artifacts','repositories','create','ziper-releases','--location',REGION,'--repository-format=docker','--description=Ziper immutable release images'])
 run(['artifacts','repositories','add-iam-policy-binding','ziper-releases','--location',REGION,'--member=serviceAccount:'+DEPLOY,'--role=roles/artifactregistry.writer','--condition=None'])
 project_role('serviceAccount:'+DEPLOY,'roles/run.developer')
 # Before first service creation invocation is project scoped; later runs keep it service scoped.
 service=run(['run','services','describe','ziper-backup','--region',REGION],missing=True)
 if service is None:
  for email in (DEPLOY,INVOKER):project_role('serviceAccount:'+email,'roles/run.invoker')
 else:
  policy=run(['projects','get-iam-policy',PROJECT])
  for email in (DEPLOY,INVOKER):
   member='serviceAccount:'+email
   run(['run','services','add-iam-policy-binding','ziper-backup','--region',REGION,'--member='+member,'--role=roles/run.invoker','--condition=None'])
   if any(b.get('role')=='roles/run.invoker' and member in b.get('members',[]) and 'condition' not in b for b in policy.get('bindings',[])):
    run(['projects','remove-iam-policy-binding',PROJECT,'--member='+member,'--role=roles/run.invoker','--condition=None'])
 run(['iam','service-accounts','add-iam-policy-binding',RUNTIME,'--member=serviceAccount:'+DEPLOY,'--role=roles/iam.serviceAccountUser','--condition=None'])
 pool='ziper-github';provider='ziper-server'
 if run(['iam','workload-identity-pools','describe',pool,'--location=global'],missing=True) is None:
  run(['iam','workload-identity-pools','create',pool,'--location=global','--display-name=Ziper production Actions'])
 ensure_wif_provider(pool,provider)
 principal=f'principalSet://iam.googleapis.com/projects/{NUMBER}/locations/global/workloadIdentityPools/{pool}/attribute.repository_id/1440603337'
 run(['iam','service-accounts','add-iam-policy-binding',DEPLOY,'--member='+principal,'--role=roles/iam.workloadIdentityUser','--condition=None'])
 values={}
 for line in (PRIVATE/'runtime.env').read_text().splitlines():
  if not line or line.startswith('#') or '=' not in line: continue
  key,value=line.split('=',1)
  if key.startswith('MIGRATION_'): continue
  parsed=shlex.split(value)
  values[key]=parsed[0] if parsed else ''
 def prop(value):return value.replace('\\','\\\\').replace('\n','\\n').replace('\r','\\r')
 properties=''.join(k+'='+prop(v)+'\n' for k,v in values.items()).encode()
 for name,data in [('ziper-runtime-properties',properties),('ziper-db-ca',(PRIVATE/'db-ca.pem').read_bytes())]:
  if run(['secrets','describe',name],missing=True) is None:run(['secrets','create',name,'--replication-policy=automatic'])
  versions=run(['secrets','versions','list',name,'--filter=state:ENABLED','--sort-by=~createTime']) or []
  match=False
  if versions:
   p=subprocess.run([SDK,'secrets','versions','access','latest','--secret',name,'--project',PROJECT],capture_output=True)
   match=p.returncode==0 and p.stdout==data
  if not match:run(['secrets','versions','add',name,'--data-file=-'],data=data)
  run(['secrets','add-iam-policy-binding',name,'--member=serviceAccount:'+RUNTIME,'--role=roles/secretmanager.secretAccessor','--condition=None'])
  print(json.dumps({'secret':name,'versionReady':True}),flush=True)
 keyfile=PRIVATE/'cloud-run-invoker.json'
 if not keyfile.exists():run(['iam','service-accounts','keys','create',str(keyfile),'--iam-account='+INVOKER])
 key=json.loads(keyfile.read_text());assert key['client_email']==INVOKER;keyfile.chmod(0o600)
 for name,value in [('CLOUD_RUN_SERVICE_ACCOUNT_JSON',json.dumps(key,separators=(',',':')).encode())]:
  p=subprocess.run(['gh','secret','set',name,'--repo','JECT-Study/Ziper-5th-Infra','--env','production'],input=value,capture_output=True)
  if p.returncode:raise SystemExit('GitHub secret registration failed')
 print(json.dumps({'project':PROJECT,'region':REGION,'artifactRepository':'ziper-releases','wifProvider':f'projects/{NUMBER}/locations/global/workloadIdentityPools/{pool}/providers/{provider}','runtimeSecretCount':2,'invokerSecretRegistered':True}),flush=True)

if __name__ == "__main__":
 main()
