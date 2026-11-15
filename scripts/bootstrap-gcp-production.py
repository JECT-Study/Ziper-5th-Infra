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
CONFIG_READER=f'ziper-config-reader@{PROJECT}.iam.gserviceaccount.com'
# Secret Manager is the single source; the laptop file is read only with --import-runtime-env.
SECRET_READERS={'ziper-runtime-properties':(RUNTIME,CONFIG_READER),'ziper-db-ca':(RUNTIME,CONFIG_READER),
 'ziper-home-migration-properties':(CONFIG_READER,)}
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

def properties(values):
 escape=lambda value:value.replace('\\','\\\\').replace('\n','\\n').replace('\r','\\r')
 return ''.join(k+'='+escape(v)+'\n' for k,v in values.items()).encode()

def runtime_bundles(text):
 """Split a one-time imported env file; the Cloud Run runtime never receives migrator credentials."""
 shared,migration={},{}
 for line in text.splitlines():
  if not line or line.startswith('#') or '=' not in line: continue
  key,value=line.split('=',1)
  parsed=shlex.split(value)
  (migration if key.startswith('MIGRATION_') else shared)[key]=parsed[0] if parsed else ''
 if not shared or not migration: raise SystemExit('Imported runtime file must contain runtime and migration keys')
 return properties(shared),properties(migration)

def ensure_secret(name, data=None):
 if run(['secrets','describe',name],missing=True) is None:run(['secrets','create',name,'--replication-policy=automatic'])
 versions=run(['secrets','versions','list',name,'--filter=state:ENABLED','--sort-by=~createTime']) or []
 if data is not None:
  match=False
  if versions:
   p=subprocess.run([SDK,'secrets','versions','access','latest','--secret',name,'--project',PROJECT],capture_output=True)
   match=p.returncode==0 and p.stdout==data
  if not match:
   run(['secrets','versions','add',name,'--data-file=-'],data=data)
   versions=run(['secrets','versions','list',name,'--filter=state:ENABLED','--sort-by=~createTime']) or []
 if not versions:raise SystemExit('Secret has no enabled version; import it once: '+name)
 for email in SECRET_READERS[name]:
  run(['secrets','add-iam-policy-binding',name,'--member=serviceAccount:'+email,'--role=roles/secretmanager.secretAccessor','--condition=None'])
 # Report only the newest enabled version so config/production.json can pin it.
 print(json.dumps({'secret':name,'latestEnabledVersion':versions[0]['name'].rsplit('/',1)[-1],'readers':len(SECRET_READERS[name])}),flush=True)

def main():
 imported='--import-runtime-env' in sys.argv[1:]
 cap=json.loads((PRIVATE/'gcp-spend-cap.json').read_text())
 token=subprocess.check_output([SDK,'auth','print-access-token'],text=True).strip()
 live=json.load(urllib.request.urlopen(urllib.request.Request('https://billingbudgets.googleapis.com/v1/'+cap['name'],headers={'Authorization':'Bearer '+token,'x-goog-user-project':PROJECT})))
 validate_spend_cap(live)
 print('Cloud Run monthly KRW 1000 spend cap: CONFIGURED (not an absolute cost guarantee)',flush=True)
 for n in ['ziper-deployer','ziper-runtime','ziper-edge-invoker','ziper-config-reader']:ensure_sa(n)
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
 for email in (DEPLOY,CONFIG_READER):
  run(['iam','service-accounts','add-iam-policy-binding',email,'--member='+principal,'--role=roles/iam.workloadIdentityUser','--condition=None'])
 data={}
 if imported:
  shared,migration=runtime_bundles((PRIVATE/'runtime.env').read_text())
  data={'ziper-runtime-properties':shared,'ziper-home-migration-properties':migration,'ziper-db-ca':(PRIVATE/'db-ca.pem').read_bytes()}
 for name in SECRET_READERS:ensure_secret(name,data.get(name))
 keyfile=PRIVATE/'cloud-run-invoker.json'
 if not keyfile.exists():run(['iam','service-accounts','keys','create',str(keyfile),'--iam-account='+INVOKER])
 key=json.loads(keyfile.read_text());assert key['client_email']==INVOKER;keyfile.chmod(0o600)
 for name,value in [('CLOUD_RUN_SERVICE_ACCOUNT_JSON',json.dumps(key,separators=(',',':')).encode())]:
  p=subprocess.run(['gh','secret','set',name,'--repo','JECT-Study/Ziper-5th-Infra','--env','production'],input=value,capture_output=True)
  if p.returncode:raise SystemExit('GitHub secret registration failed')
 print(json.dumps({'project':PROJECT,'region':REGION,'artifactRepository':'ziper-releases','wifProvider':f'projects/{NUMBER}/locations/global/workloadIdentityPools/{pool}/providers/{provider}','runtimeSecretCount':len(SECRET_READERS),'runtimeImported':imported,'invokerSecretRegistered':True}),flush=True)

if __name__ == "__main__":
 main()
