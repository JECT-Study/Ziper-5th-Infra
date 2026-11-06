#!/usr/bin/env python3
"""Print only non-secret identity claims to diagnose WIF conditions; never print JWTs."""
import base64,json,os,urllib.request,urllib.parse,urllib.error,sys

def main():
 try:
  url=urllib.parse.urlsplit(os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'])
  if url.scheme!='https' or not url.hostname or not url.hostname.endswith('.actions.githubusercontent.com') or url.username or url.password or url.port not in (None,443):raise ValueError()
  params=urllib.parse.parse_qsl(url.query);params.append(('audience','https://iam.googleapis.com/projects/45190721178/locations/global/workloadIdentityPools/ziper-github/providers/ziper-server'))
  endpoint=urllib.parse.urlunsplit((url.scheme,url.netloc,url.path,urllib.parse.urlencode(params),''))
  class NoRedirect(urllib.request.HTTPRedirectHandler):
   def redirect_request(self,*args):return None
  req=urllib.request.Request(endpoint,headers={'Authorization':'Bearer '+os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
  with urllib.request.build_opener(NoRedirect()).open(req,timeout=10) as r:
   jwt=json.loads(r.read(65536))['value']
  segment=jwt.split('.')[1];claims=json.loads(base64.urlsafe_b64decode(segment+'='*(-len(segment)%4)))
  allowed=('sub','repository_id','repository','ref','environment','job_workflow_ref','repository_owner_id')
  result={k:claims[k] for k in allowed if k in claims and isinstance(claims[k],(str,int)) and len(str(claims[k]))<1024}
  print(json.dumps({'event':'wif_identity_claims','claims':result}))
  return 0
 except (KeyError,ValueError,IndexError,TypeError,urllib.error.URLError,OSError):
  print('OIDC identity metadata inspection failed; no credential recorded.',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
