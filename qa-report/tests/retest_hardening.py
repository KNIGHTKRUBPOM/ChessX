from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest.mock

spec = spec_from_file_location("retest", Path(__file__).with_name("retest_local.py"))
qa = module_from_spec(spec)
spec.loader.exec_module(qa)
sys.path.insert(0, str(qa.ROOT))
from backend import rooms
from fastapi.testclient import TestClient
from backend.app import app

def limits():
    alice = TestClient(app, client=('127.0.0.1', 50000))
    bob = TestClient(app, client=('127.0.0.2', 50000))
    with unittest.mock.patch.object(rooms, 'SOURCE_ROOM_LIMIT', 1):
        first = alice.post('/api/rooms', json={'mode':'chess','name':'QA Alice'})
        second = alice.post('/api/rooms', json={'mode':'chess','name':'QA Alice'})
        other = bob.post('/api/rooms', json={'mode':'chess','name':'QA Bob'})
        qa.check('S01-quota-isolated',[200,429,200],[first.status_code,second.status_code,other.status_code])
        data = first.json()
        path = '/api/rooms/' + data['snapshot']['code']
        auth = {'Authorization': 'Bearer ' + data['token']}
        read = alice.get(path, headers=auth)
        tag=read.headers.get('etag')
        if tag:
            qa.check('P02-conditional',[200,304,401],[read.status_code, alice.get(path,headers={**auth,'If-None-Match':tag}).status_code,alice.get(path,headers={'If-None-Match':tag}).status_code])
            created = bob.post(path+'/join',json={'name':'QA Guest'})
            fresh = alice.get(path,headers={**auth,'If-None-Match':tag})
            qa.check('P02-revision-change',[200,200,True],[created.status_code,fresh.status_code,fresh.headers.get('etag') != tag])
        else:
            qa.check('P02-conditional',True,False)
        pending=other.json()
        pending_code=pending['snapshot']['code']
        rooms._rooms[pending_code].changed_at -= 16*60
        qa.check('S01-waiting-expiry',404,bob.get('/api/rooms/'+pending_code,headers={'Authorization':'Bearer '+pending['token']}).status_code)

def prod():
    code = """from fastapi.testclient import TestClient
from backend.app import app
import json
with TestClient(app) as c:
 r=c.get('/')
 a=c.get('/docs')
 b=c.get('/openapi.json')
 print(json.dumps([r.status_code,a.status_code,b.status_code,'frame-ancestors' in r.headers.get('content-security-policy','')]))
"""
    env={**os.environ,'CHESS_ENV':'production'}
    got=subprocess.check_output([sys.executable,'-B','-c',code],cwd=qa.ROOT,env=env,text=True)
    qa.check('S03-production',[200,404,404,True],json.loads(got))

if __name__=='__main__':
    limits()
    prod()
    (qa.E/'hardening.json').write_text(json.dumps(qa.RESULTS,indent=2),encoding='utf-8')
    print(json.dumps(qa.RESULTS,indent=2))
    sys.exit(any(r['status']!='PASS' for r in qa.RESULTS))

