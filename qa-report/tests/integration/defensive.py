import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_qa import E,server,prior,record,report

def suite():
    results=[]
    with server('security',production=True):
        def prod_headers():
            home, headers, _=prior.request('/')
            h={k.lower():v for k,v in headers.items()}
            assert home==200
            assert "frame-ancestors 'none'" in h.get('content-security-policy','')
            assert h.get('x-frame-options')=='DENY'
            assert h.get('x-content-type-options')=='nosniff'
            assert h.get('referrer-policy')=='no-referrer'
            assert all(prior.request(route)[0]==404 for route in ['/docs','/redoc','/openapi.json','/.env','/.git/config','/qa-report/REPORT.md'])
            return 'production headers และ scope static ผ่าน'
        record('SEC-PROD',prod_headers,results)
        def audit():
            status,created=prior.decoded('/api/rooms',{'mode':'chess','name':'QA log marker'})
            assert status==200
            public=created['snapshot']
            assert 'token' not in public
            path='/api/rooms/'+public['code']
            assert prior.decoded(path)[0]==401
            assert prior.decoded(path,token=created['token'])[0]==200
            log=(E/'security-server.log').read_text(encoding='utf8')
            assert 'room_authorization_denied' in log and 'room_created' in log
            assert all(marker not in log for marker in [created['token'],public['code'],'QA log marker'])
            return 'structured events มีเหตุการณ์และไม่มีชื่อเล่น รหัสเชิญหรือ seat token ใน test log'
        record('SEC-LOG',audit,results)
        def leave_seat():
            status, white = prior.decoded('/api/rooms', {'mode':'chess','name':'QA White'})
            assert status == 200
            path = '/api/rooms/' + white['snapshot']['code']
            status, black = prior.decoded(path+'/join', {'name':'QA Black'})
            assert status == 200
            denied, denied_headers, _ = prior.request(path+'/seat', method='DELETE')
            assert denied == 401
            assert {key.lower():val for key,val in denied_headers.items()}['cache-control'] == 'no-store'
            left, headers, body = prior.request(path+'/seat', token=white['token'], method='DELETE')
            assert left == 204 and body == b''
            assert {key.lower():val for key,val in headers.items()}['cache-control'] == 'no-store'
            assert prior.request(path, token=white['token'])[0] == 401
            status, result = prior.decoded(path, token=black['token'])
            assert (status, result['detail']) == (410, 'room_seat_departed')
            assert prior.request(path+'/seat', token=black['token'], method='DELETE')[0] == 204
            assert prior.request(path, token=black['token'])[0] == 404
            return {'no_credential':denied,'leave':left,'peer_notice':status,'cache':'no-store'}
        record('SEC-LEAVE',leave_seat,results)

        def release_cache_policy():
            for location in ('/', '/index.html'):
                status, headers, _ = prior.request(location, method='HEAD')
                assert status == 200
                assert {key.lower():val for key,val in headers.items()}['cache-control'] == 'no-cache'
            for asset in (prior.ROOT/'dist/assets').glob('*'):
                status, headers, _ = prior.request('/assets/'+asset.name)
                assert status == 200
                assert {key.lower():val for key,val in headers.items()}['cache-control'] == 'public, max-age=31536000, immutable'
            status, headers, _ = prior.request('/assets/missing-qa-01234567.js')
            assert status == 404
            assert 'immutable' not in {key.lower():val for key,val in headers.items()}.get('cache-control','')
            return {'html':'no-cache','hashed_assets':'immutable','missing_asset':status}
        record('SEC-STATIC-CACHE',release_cache_policy,results)

    def request_budget():
        from backend.body_limit import ApiBodyLimit

        async def run_case(headers, chunks, expected):
            seen, sent = [], []

            async def app(_, receive, send):
                seen.append((await receive())['body'])
                await send({'type':'http.response.start','status':200,'headers':[]})
                await send({'type':'http.response.body','body':b''})

            async def receive():
                return chunks.pop(0)

            async def send(message):
                sent.append(message)

            scope = {'type':'http','method':'POST','path':'/api/game/start','headers':headers}
            await ApiBodyLimit(app, max_bytes=8)(scope, receive, send)
            assert sent[0]['status'] == expected
            if expected == 413:
                assert not seen and 'body' in json.loads(sent[1]['body'])['detail']
            else:
                assert seen == [b'12345678']

        async def verify_budget():
            for headers, chunks, expected in [
                ([(b'content-length', b'9')], [], 413),
                ([], [{'type':'http.request','body':b'1234','more_body':True},
                      {'type':'http.request','body':b'56789'}], 413),
                ([], [{'type':'http.request','body':b'1234','more_body':True},
                      {'type':'http.request','body':b'5678'}], 200),
            ]:
                await run_case(headers, chunks, expected)

        asyncio.run(verify_budget())
        return {'limit_in_fixture':8,'content_length_over':413,'stream_over':413,'exactly_at_limit':200}
    record('SEC-BODY-BUDGET',request_budget,results)
    return report('security',results)

if __name__=='__main__':
    raise SystemExit(suite())

