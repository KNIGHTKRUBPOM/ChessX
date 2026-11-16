from contextlib import contextmanager
from pathlib import Path
import json,os,re,socket,subprocess,sys,tempfile,time
from importlib.util import spec_from_file_location,module_from_spec
sys.modules.setdefault('run_qa',sys.modules[__name__])
ROOT=Path(__file__).resolve().parents[2]
QA=ROOT/'qa-report'
run_label = os.environ.get('CHESS_QA_RUN', 'qa-2026-11-15')
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', run_label):
    raise ValueError('CHESS_QA_RUN must be a lowercase evidence folder name.')
E=QA/'evidence'/run_label
E.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT))
def load(path, name):
    spec=spec_from_file_location(name,path)
    module=module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
prior=load(QA/'tests'/'retest_local.py','prior')
fingerprint=prior.source_hashes
def report(name, results):
    (E/(name+'.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print(name, len(results), 'PASS',sum(x['status']=='PASS' for x in results),'FAIL',sum(x['status']=='FAIL' for x in results),'ERROR',sum(x['status']=='ERROR' for x in results),flush=True)
    return any(x['status'] in ('FAIL','ERROR') for x in results)
@contextmanager
def server(name, production=False):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    with (E/(name+'-server.log')).open('w',encoding='utf8') as log:
        proc=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-B','-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port),'--workers','1','--no-access-log'],cwd=ROOT,env=dict(os.environ,CHESS_ENV='production' if production else '',PYTHONDONTWRITEBYTECODE='1',SUPABASE_URL='',SUPABASE_PUBLISHABLE_KEY='',APP_ORIGIN='',CHESS_ROOM_STORE='memory',SUPABASE_SECRET_KEY=''),stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
        prior.BASE=base
        try:
            for _ in range(40):
                try:
                    if prior.request('/api/health')[0]==200: break
                except OSError: pass
                if proc.poll() is not None: break
                time.sleep(.2)
            else: raise RuntimeError('Loopback server not ready')
            if proc.poll() is not None: raise RuntimeError('Uvicorn exited')
            yield base
        finally:
            if proc.poll() is None:
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,check=False)
                else: proc.terminate()
                proc.wait(timeout=8)
def record(id,action,results):
    t=time.perf_counter()
    try:
        actual=action()
        status='PASS'
    except AssertionError as err:
        actual=str(err)
        status='FAIL'
    except Exception as err:
        actual=str(err)
        status='ERROR'
    results.append(dict(id=id,status=status,actual=actual,seconds=round(time.perf_counter()-t,3)))
    print(id,status,flush=True)
def previous_suite(kind):
    prior.E=E
    prior.RESULTS=[]
    start=time.perf_counter()
    with tempfile.TemporaryDirectory(dir=E) as tmp:
        # Compatibility with the previous Playwright fixture.
        (E/'temp').mkdir(exist_ok=True)
        with server(kind):
            getattr(prior,kind)()
    print(kind,round(time.perf_counter()-start,2),'s')
    return prior.RESULTS
def run(phase):
    if phase in ('smoke','regression','ui','a11y'):
        return load(QA/'tests/e2e/web.py','ui_tests').suite(phase)
    if phase=='baseline': return report(phase,previous_suite('browser'))
    if phase=='integration':
        started=time.perf_counter()
        results=previous_suite('api')
        module=load(QA/'tests/integration/endpoints.py','api_cases')
        with server('routes') as url:
            module.checks(url,results)
        print('Integration total',round(time.perf_counter()-started,2),'s')
        return report(phase,results)
    if phase=='performance':
        with server(phase) as url:
            prior.E=E
            prior.perf()
            return load(QA/'tests/integration/endpoints.py','perf_cases').performance(url)
    if phase=='unit':
        return subprocess.run([sys.executable,'-B',str(QA/'tests/unit/verify_rules.py')],cwd=ROOT).returncode
    if phase=='security':
        return load(QA/'tests/integration/defensive.py','defensive_cases').suite()
    if phase=='accounts':
        return load(QA/'tests/integration/accounts.py','account_api_cases').suite()
    if phase=='account-browser':
        return load(QA/'tests/e2e/accounts.py','account_ui_cases').suite()
    if phase=='rooms-db':
        return load(QA/'tests/integration/rooms_db.py','rooms_db_cases').suite()
    raise ValueError(phase)
if __name__=='__main__':
    phases=sys.argv[1:] or ('smoke','regression','integration','unit','ui','a11y','performance','security','accounts','account-browser')
    before=fingerprint()
    failed=[]
    start=time.perf_counter()
    for phase in phases:
        t=time.perf_counter()
        try:
            if run(phase): failed.append(phase)
        except Exception as exc:
            print(phase,'HARNESS ERROR',exc,flush=True)
            failed.append(phase)
        finally: print(phase,round(time.perf_counter()-t,3),'s',flush=True)
    integrity=before==fingerprint()
    (E/'source-integrity.json').write_text(json.dumps({'unchanged':integrity,'before':before,'duration_s':round(time.perf_counter()-start,3)}),encoding='utf8')
    raise SystemExit(bool(failed or not integrity))



