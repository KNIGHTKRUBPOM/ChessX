import concurrent.futures
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
E = ROOT / 'qa-report' / 'evidence'
RESULTS = []
class LoopbackOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(BASE + '/'):
            raise ValueError('Blocked redirect outside the QA origin')
        return super().redirect_request(req, fp, code, msg, headers, newurl)

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), LoopbackOnly())

def source_hashes():
    paths = [p for d in ('backend', 'src', 'dist') for p in (ROOT/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths.extend(p for p in ROOT.iterdir() if p.is_file())
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def check(case, expected, actual):
    RESULTS.append({'id':case,'expected':expected,'actual':actual,'status':'PASS' if actual == expected else 'FAIL'})

def request(path, body=None, token=None, method=None):
    assert path.startswith('/') and not path.startswith('//')
    headers = {'Content-Type':'application/json'} if body is not None else {}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(BASE+path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
    try:
        res = opener.open(req, timeout=5)
    except urllib.error.HTTPError as err:
        res = err
    with res:
        raw = res.read()
        return res.status, dict(res.headers), raw

def decoded(path, body=None, token=None):
    status, headers, raw = request(path, body, token)
    return status, json.loads(raw)

def api():
    schema_code, schema_headers, schema_raw = request('/openapi.json')
    check('F-openapi-schema',200,schema_code)
    (E/'openapi-observation.json').write_text(json.dumps({'status':schema_code,'headers':schema_headers,'body':schema_raw.decode()[:1024]},indent=2),encoding='utf-8')
    for mode, turn, pieces in [('chess','w',32),('draughts','b',16),('hybrid','w',28)]:
        code, body = decoded('/api/game/start',{'mode':mode})
        check('F-start-'+mode,[200,turn,pieces],[code,body['state']['turn'],sum(p is not None for p in body['state']['board'])])
    check('F-mode-invalid',422,decoded('/api/game/start',{'mode':'unknown'})[0])
    for name, expected in [('',422),('  ',422),('ก'*24,200),('ก'*25,422),('ผู้เล่น ♟',200),('A & B <ทีม>',200)]:
        code,_=decoded('/api/rooms',{'mode':'hybrid','name':name})
        check('F-name-'+str(len(RESULTS)),expected,code)
    _, first = decoded('/api/rooms',{'mode':'hybrid','name':'QA ขาว'})
    path = '/api/rooms/'+first['snapshot']['code']
    wt = first['token']
    _, guest = decoded(path+'/join',{'name':'QA ดำ'})
    bt = guest['token']
    check('F-room-full',409,decoded(path+'/join',{'name':'QA ที่สาม'})[0])
    check('D-room-auth',401,decoded(path)[0])
    check('F-room-joined',['setup','w','b'],[guest['snapshot']['phase'],first['snapshot']['side'],guest['snapshot']['side']])
    def act(token, action):
        return decoded(path+'/action',action,token)
    ws={'lock':48,'revive':51,'friendly':50,'push':49}
    bs={'lock':8,'revive':1,'friendly':12,'push':17,'duel':17}
    rev=guest['snapshot']['revision']
    check('F-setup-incomplete',422,act(wt,{'type':'setup','revision':rev,'placements':{'lock':48}})[0])
    check('F-setup-original',200,act(bt,{'type':'setup','revision':rev,'placements':bs})[0])
    check('F-setup-both',200,act(wt,{'type':'setup','revision':rev,'placements':ws})[0])
    white=decoded(path,None,wt)[1]
    black=decoded(path,None,bt)[1]
    check('D-private-skills',True,all('skills' not in p and 'hasSkill' not in p for snap, own in [(white,'w'),(black,'b')] for p in snap['board'] if p and p['side'] != own))
    check('F-own-skills',['push','duel'],black['board'][17]['skills'])
    check('D-turn-options',None,black['options'])
    def move(token,snapshot,frm,to):
        return act(token,{'type':'move','revision':snapshot['revision'],'move':{'from':frm,'to':to}})
    check('D-wrong-turn',409,move(bt,black,17,24)[0])
    for target in [-1,64,1.5,10**9]:
        check('F-square-'+str(target),422,move(wt,white,49,target)[0])
    check('F-illegal',422,move(wt,white,49,17)[0])
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=sorted(pool.map(lambda _:move(wt,white,49,33)[0],range(2)))
    check('F-duplicate-move',[200,409],outcomes)
    c, black=move(bt,decoded(path,None,bt)[1],17,24)
    check('F-checker-step',200,c)
    c, white=move(wt,decoded(path,None,wt)[1],33,24)
    check('F-XO-start',[200,'duel'],[c,white['phase']])
    for cell, token in zip([0,3,1,4,2],[bt,wt,bt,wt,bt]):
        snap=decoded(path,None,token)[1]
        c,_=act(token,{'type':'duel','revision':snap['revision'],'cell':cell})
        check('F-XO-cell-'+str(cell),200,c)
    final=decoded(path,None,wt)[1]
    check('F-XO-reverse',['b',None,'b'],[final['lastDuel']['board']['winner'],final['board'][33],final['board'][24]['side']])
    check('F-room-resume','b',decoded(path,None,bt)[1]['side'])
    check('D-no-store','no-store',{k.lower():v for k,v in request(path,token=wt)[1].items()}.get('cache-control'))
    for probe in ['/missing-qa-page','/.env','/.git/config','/backend/app.py','/qa-report/REPORT.md']:
        check('D-web-'+probe,404,request(probe)[0])
    check('D-method',405,request('/api/health',method='TRACE')[0])
    obs={}
    for path in ['/','/docs','/redoc','/api/health','/api/rooms/health']:
        status,headers,raw=request(path)
        item={'status':status,'headers':headers,'bytes':len(raw)}
        if path in ('/docs','/redoc'):
            item['external_urls']=sorted(set(re.findall(r'(?:src|href)=["\'](https://[^"\']+)',raw.decode())))
        obs[path]=item
    (E/'http-observations.json').write_text(json.dumps(obs,indent=2),encoding='utf-8')
    return obs

def browser():
    captures=[]
    with sync_playwright() as p:
        profile=Path(tempfile.mkdtemp(prefix='chrome-',dir=E/'temp'))
        context=p.chromium.launch_persistent_context(str(profile), executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,args=['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--disable-default-apps','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost'])
        try:
            context.route('**/*',lambda route: route.continue_() if route.request.url.startswith(BASE+'/') else route.abort())
            context.add_init_script("""window.qaShifts=[]; new PerformanceObserver(l=>window.qaShifts.push(...l.getEntries().filter(x=>!x.hadRecentInput).map(x=>x.value))).observe({type:'layout-shift',buffered:true}); window.qaLcp=0; new PerformanceObserver(l=>{for(const x of l.getEntries()) window.qaLcp=x.startTime;}).observe({type:'largest-contentful-paint',buffered:true});""")
            page=context.pages[0]
            page.set_default_timeout(4500)
            errors=[]
            page.on('pageerror',lambda err:errors.append(str(err)))
            page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' else None)
            page.goto(BASE+'/',wait_until='networkidle')
            mode=page.locator('input[name=mode][value=chess]')
            check('UI-home-title',True,'หมาก' in page.title())
            metrics=page.evaluate("""() => ({lcp_ms:window.qaLcp,cls_sum:window.qaShifts.reduce((a,b)=>a+b,0),navigation_ms:performance.getEntriesByType('navigation')[0].loadEventEnd,assets:performance.getEntriesByType('resource').map(r=>({name:new URL(r.name).pathname,bytes:r.decodedBodySize,ms:r.duration}))})""")
            (E/'chromium-performance.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
            for width in [320,375,768,1024,1440]:
                page.set_viewport_size({'width':width,'height':900})
                viewport=page.evaluate("() => ({w:innerWidth,scroll:document.documentElement.scrollWidth,menu:document.querySelector('#menu').getBoundingClientRect().right})")
                check('UI-width-'+str(width),True,viewport['scroll']<=viewport['w'] and viewport['menu']<=viewport['w'])
                captures.append(viewport)
                if width in (320,1440): page.screenshot(path=str(E/f'menu-{width}.png'),full_page=True)
            page.locator('header [data-open-themes]').click()
            check('UI-themes',6,page.locator('#theme-dialog input[type=radio]').count())
            page.locator('#theme-dialog input[value=sakura]').check()
            page.keyboard.press('Escape')
            page.reload(wait_until='networkidle')
            check('F-theme-restore','sakura',page.locator('html').get_attribute('data-theme'))
            mode.check()
            page.get_by_role('button',name='Play',exact=True).click()
            key='[data-coordinate="a2"]'
            page.locator(key).wait_for(state='attached')
            page.locator(key).focus()
            page.keyboard.press('Enter')
            check('F-keyboard-placement',True,'1 / 4' in page.locator('.tip').inner_text())
            clear=page.locator('[data-action=clear]')
            clear.focus()
            page.keyboard.press('Enter')
            focus=page.evaluate("() => ({tag: document.activeElement.tagName, inside: document.querySelector('#game-view').contains(document.activeElement)})")
            check('A11Y-clear-focus',True,focus['inside'])
            page.screenshot(path=str(E/'clear-focus-320.png') if page.viewport_size['width']==320 else str(E/'clear-focus.png'))
            page.reload(wait_until='networkidle')
            check('F-resume-visible',True,page.locator('#resume-button').is_visible())
            page.locator('#resume-button').click()
            page.locator('.tip').wait_for()
            check('F-resume-setup',True,'0 / 4' in page.locator('.tip').inner_text())
            check('UI-console',[],errors)
            page.locator('#menu-button').click()
            page.locator('#online-open').click()
            lobby=page.locator('#online-dialog')
            name=page.locator('#online-name')
            name.fill('😀'*13)
            browser_count=len(name.input_value())
            check('F-name-unicode-parity',13,browser_count)
            check('F-name-unicode-api',200,decoded('/api/rooms',{'name':'😀'*13,'mode':'chess'})[0])
            name.fill('QA browser')
            page.locator('#online-create').click()
            page.locator('#online-room').wait_for()
            old_code=page.locator('#online-room-code').inner_text()
            # A normal guest joins so the first room is occupied.
            decoded('/api/rooms/'+old_code+'/join',{'name':'QA partner'})
            page.locator('#online-leave').click()
            page.locator('#online-open').click()
            name.fill('QA second room')
            page.locator('#online-create').click()
            page.locator('#online-room').wait_for()
            page.locator('#online-leave').click()
            page.goto(BASE+'/?room='+old_code,wait_until='domcontentloaded')
            lobby.wait_for()
            name.fill('QA browser')
            page.locator('#online-join').click()
            page.locator('#online-dialog-status').wait_for()
            check('F-paused-room-recovery',True,page.locator('#online-room').is_visible())
            (E/'room-recovery.txt').write_text(page.locator('#online-dialog-status').inner_text()+'\n',encoding='utf-8')
            page.screenshot(path=str(E/'room-recovery.png'))
            page.locator('#online-close').click()
            page.set_viewport_size({'width':640,'height':850})
            page.evaluate("document.body.style.zoom='2'")
            check('A11Y-zoom-200',True,page.evaluate("document.documentElement.scrollWidth<=innerWidth"))
            page.screenshot(path=str(E/'zoom-200.png'),full_page=True)
        finally:
            context.close()
            import shutil
            shutil.rmtree(profile,ignore_errors=True)
    (E/'layout.json').write_text(json.dumps(captures,indent=2),encoding='utf-8')

def perf():
    path='/api/health'
    def sample(_):
        t=time.perf_counter()
        status=request(path)[0]
        return (status,round((time.perf_counter()-t)*1000,3))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        samples=list(pool.map(sample,range(20)))
    times=sorted(x[1] for x in samples)
    data={'path':path,'requests':len(samples),'concurrency':2,'http_200':sum(x[0]==200 for x in samples),'median_ms':statistics.median(times),'p95_ms':times[18],'max_ms':times[-1],'samples':samples}
    (E/'safe-api-sample.json').write_text(json.dumps(data,indent=2),encoding='utf-8')

if __name__=='__main__':
    before=source_hashes()
    python=ROOT/'.venv'/'Scripts'/'python.exe'
    with socket.socket() as binding:
        binding.bind(('127.0.0.1',0))
        port=binding.getsockname()[1]
    BASE=f'http://127.0.0.1:{port}'
    (E/'run-target.txt').write_text(BASE+' (isolated loopback instance)\n',encoding='utf-8')
    temp=E/'temp'
    temp.mkdir(exist_ok=True)
    os.environ.update(TMP=str(temp),TEMP=str(temp),PYTHONDONTWRITEBYTECODE='1')
    with (E/'uvicorn.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen([str(python),'-B','-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port),'--workers','1','--no-access-log'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(30):
                try:
                    if request('/api/health')[0]==200: break
                except OSError: pass
                time.sleep(.25)
            for task in (api,browser,perf):
                try: task()
                except Exception as err:
                    RESULTS.append({'id':task.__name__,'status':'ERROR','actual':str(err)})
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            check('ROE-source-unchanged',True,before==source_hashes())
            (E/'results.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding='utf-8')
    for result in RESULTS:
        print(result['id'], result['status'])
    sys.exit(2 if any(r['status']=='ERROR' for r in RESULTS) else 1 if any(r['status']=='FAIL' for r in RESULTS) else 0)

