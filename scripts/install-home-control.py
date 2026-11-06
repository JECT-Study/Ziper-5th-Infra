#!/usr/bin/env python3
"""Install reviewed public control files in small chunks; never transfer image/secret data."""
import argparse,base64,hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
import re
from zoneinfo import ZoneInfo

FILES={
 'deployment/home/receive.py':'/opt/ziper/ci/receive.py',
 'deployment/home/image_identity.py':'/opt/ziper/ci/image_identity.py',
 'deployment/home/registry_release.py':'/opt/ziper/ci/registry_release.py',
 'deployment/home/deploy.sh':'/opt/ziper/ci/deploy.sh',
 'deployment/home/compose.yml':'/opt/ziper/ci/compose.yml',
 'config/production.json':'/opt/ziper/ci/production.json',
 'deployment/home/recovery.py':'/opt/ziper/ops/recovery.py',
 'deployment/home/systemd/ziper-recovery.service':'/etc/systemd/system/ziper-recovery.service',
 'deployment/home/systemd/ziper-recovery.timer':'/etc/systemd/system/ziper-recovery.timer',
}

def remote(code):
 payload=base64.b64encode(code.encode()).decode()
 launcher="import base64;exec(base64.b64decode('"+payload+"'))"
 ps='[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); & C:\\Windows\\System32\\wsl.exe -d Ubuntu -u root --exec python3 -c "'+launcher+'"; exit $LASTEXITCODE'
 command='powershell.exe -NoProfile -NonInteractive -EncodedCommand '+base64.b64encode(ps.encode('utf-16-le')).decode()
 result=subprocess.run(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10','ssh.joonamin.dev',command],capture_output=True,timeout=45)
 if result.returncode:raise RuntimeError('home_control_installation_failed_or_unknown')
 lines=result.stdout.decode(errors='replace').strip().splitlines()
 try:return json.loads(lines[-1].lstrip('\ufeff'))
 except (ValueError,IndexError):raise RuntimeError('home_control_receipt_invalid') from None

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--infra-sha',required=True);parser.add_argument('--install',action='store_true');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 if not re.fullmatch('[a-f0-9]{40}',args.infra_sha):parser.error('Supply an existing reviewed full infrastructure SHA')
 if subprocess.run(['git','merge-base','--is-ancestor',args.infra_sha,'origin/main'],capture_output=True).returncode:
  raise RuntimeError('infrastructure_commit_is_not_on_reviewed_main')
 prepared=[]
 for source,target in FILES.items():
  content=subprocess.check_output(['git','show',args.infra_sha+':'+source])
  prepared.append({'source':source,'target':target,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content),'content':content})
 report={'checkedAt':datetime.now(timezone.utc).isoformat(),'infraSha':args.infra_sha,'installed':False,'files':[{k:v for k,v in f.items() if k!='content'} for f in prepared]}
 if args.install:
  schedule=json.loads(next(f['content'] for f in prepared if f['source']=='config/production.json'))['homeSchedule']
  now=datetime.now(ZoneInfo(schedule['timeZone']));minute=now.hour*60+now.minute
  parse=lambda s:int(s[:2])*60+int(s[3:]);start=(parse(schedule['start'])-schedule['deploySafetyMinutes'])%1440;end=parse(schedule['end'])
  if start<=minute<end if start<end else minute>=start or minute<end:raise RuntimeError('home_installation_deferred_by_schedule')
  for f in prepared:
   path=f['target']+'.install-'+args.infra_sha
   for offset in range(0,len(f['content']),1024):
    piece=base64.b64encode(f['content'][offset:offset+1024]).decode()
    code="import os,base64,json;from pathlib import Path;p=Path("+repr(path)+");p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);h=open(p,'r+b' if p.exists() else 'w+b');h.seek("+str(offset)+");d=base64.b64decode('"+piece+"');h.write(d);h.truncate();h.flush();os.fsync(h.fileno());h.close();p.chmod(0o600);print(json.dumps({'chunk':"+str(offset)+",'written':len(d)}))"
    receipt=remote(code)
    if receipt.get('chunk')!=offset or receipt.get('written')!=len(f['content'][offset:offset+1024]):raise RuntimeError('home_chunk_receipt_mismatch')
  metadata=[{k:f[k] for k in ('target','sha256')} for f in prepared]
  code='''import os,json,hashlib,fcntl
from pathlib import Path
items=METADATA
with open('/opt/ziper/deploy.lock','a+b') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 for item in items:
  p=Path(item['target']+'.install-SHA');assert p.is_file() and not p.is_symlink();assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
 for item in items:
  p=Path(item['target']);os.replace(str(p)+'.install-SHA',p);p.chmod(0o600)
 print(json.dumps({'installed':True,'hashes':{x['target']:hashlib.sha256(Path(x['target']).read_bytes()).hexdigest() for x in items}}))
'''.replace('METADATA',repr(metadata)).replace('SHA',args.infra_sha)
  receipt=remote(code)
  if not receipt.get('installed') or any(receipt['hashes'].get(f['target'])!=f['sha256'] for f in prepared):raise RuntimeError('home_installed_hash_mismatch')
  report['installed']=True
 args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
 try:main()
 except (RuntimeError,subprocess.SubprocessError,OSError,ValueError):print('Home control installation failed, deferred or outcome unknown; inspect before any retry.',file=sys.stderr);raise SystemExit(1)
