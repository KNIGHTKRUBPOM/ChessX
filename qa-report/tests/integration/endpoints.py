import json,sys,time
from pathlib import Path
import urllib.request,urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_qa import E,prior,report
def checks(url,results):
    def verify(id,expected,actual):
        results.append(dict(id=id,expected=expected,actual=actual,status='PASS' if actual==expected else 'FAIL'))
    def post(path,value):
        return prior.decoded('/api/game/'+path,value)
    schema=prior.decoded('/openapi.json')[1]
    routes={path:{method:{k:v.get(k,[]) for k in ('security','parameters','requestBody')} for method,v in ops.items()} for path,ops in schema['paths'].items()}
    (E/'api-inventory.json').write_text(json.dumps(routes,indent=2),encoding='utf8')
    for name in ['options','setup','move','duel','duel/finish']:
        verify('INT-required-'+name,422,post(name,{'mode':'hybrid'})[0])
    verify('INT-wrong-type',422,post('start',{'mode':False})[0])
    def raw(path,body=None,headers=None,method='GET'):
        req=urllib.request.Request(url+path,data=body,headers=headers or {},method=method)
        try: response=prior.opener.open(req,timeout=5)
        except urllib.error.HTTPError as err: response=err
        with response: return response.status,{k.lower():v for k,v in response.headers.items()},response.read()
    for body,id in [(b'','empty'),(b'{','json')]:
        verify('INT-'+id,422,raw('/api/game/start',body,{'Content-Type':'application/json'},'POST')[0])
    verify('INT-method',405,raw('/api/game/start',method='PUT')[0])
    base=post('start',{'mode':'hybrid'})[1]['state']
    def move(st,frm,to):
        return post('move',{'mode':'hybrid','state':st,'move':{'from':frm,'to':to}})
    verify('INT-options',200,post('options',{'mode':'hybrid','state':base})[0])
    for side,placements in [('w',{'lock':48,'revive':51,'friendly':50,'push':49}),('b',{'lock':8,'revive':1,'friendly':12,'push':17,'duel':17})]:
        status, setup=post('setup',{'mode':'hybrid','state':base,'side':side,'placements':placements})
        verify('INT-setup-'+side,200,status)
        base=setup['state']
    for frm,to in [(49,33),(17,24),(33,24)]:
        status, out=move(base,frm,to)
        verify('INT-main-'+str(frm),200,status)
        base=out['state']
    duel=out['duel']
    verify('INT-duel-unfinished',409,post('duel/finish',{'mode':'hybrid','state':base,'duel':duel})[0])
    for seq,winner in [([0,3,1,4,2],'b'),([0,3,1,4,8,5],'w'),([0,1,2,4,3,5,7,6,8],None)]:
        d=duel
        for i in seq:
            c,p=post('duel',{'mode':'hybrid','state':base,'duel':d,'cell':i})
            assert c==200
            d=p['duel']
        c,p=post('duel/finish',{'mode':'hybrid','state':base,'duel':d})
        verify('INT-duel-outcome-'+str(winner),[200,winner],[c,d['board']['winner']])
    _, data=prior.decoded('/api/rooms',{'mode':'chess','name':'QA Integration'})
    path='/api/rooms/'+data['snapshot']['code']
    h={'Authorization':'Bearer '+data['token']}
    a,head, _=raw(path,headers=h)
    b, cnd, content=raw(path,headers={**h,'If-None-Match':head['etag']})
    verify('SEC-conditional-auth',[200,304,0,'no-store',401],[a,b,len(content),cnd['cache-control'],raw(path,headers={'If-None-Match':head['etag']})[0]])
    verify('SEC-cookie-on-room',False,'set-cookie' in head)
    verify('SEC-strict-fields',422,prior.decoded('/api/rooms',{'mode':'chess','name':'QA','extra':True})[0])

def performance(url):
    sample={}
    html=prior.request('/')[2].decode('utf8')
    import re
    paths=re.findall(r'(?:src|href)="\.(\/assets\/[^"]+)"',html)
    for path in paths + [p for p in [f'/assets/{f.name}' for f in (prior.ROOT/'dist/assets').glob('phaser-*.js')] if p not in paths]:
        req=urllib.request.Request(url+path,headers={'Accept-Encoding':'gzip'})
        with prior.opener.open(req,timeout=5) as response:
            raw=response.read()
            sample[path]={'status':response.status,'wire_bytes':len(raw),'content_encoding':response.headers.get('Content-Encoding'),'cache_control':response.headers.get('Cache-Control'),'etag_present':response.headers.get('ETag') is not None}
    (E/'asset-transfer.json').write_text(json.dumps(sample,indent=2),encoding='utf8')
    return report('performance',[{'id':'PERF-compression','status':'PASS' if all(x['content_encoding']=='gzip' for x in sample.values()) else 'FAIL','actual':sample}])

