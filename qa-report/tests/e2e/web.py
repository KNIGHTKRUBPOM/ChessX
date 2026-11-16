from pathlib import Path
import json,sys,tempfile
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_qa import ROOT,E,server,report,record,prior,previous_suite

CHROME=r'C:\Program Files\Google\Chrome\Application\chrome.exe'
args=['--disable-background-networking','--disable-component-update','--disable-sync','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1']

def tile(page, algebraic):
    cell=page.locator(f'#board [data-coordinate="{algebraic}"]')
    cell.focus()
    page.keyboard.press('Enter')

def start(page,mode):
    page.locator(f'[name=mode][value={mode}]').check()
    page.get_by_role('button',name='Play',exact=True).click()
    expect(page.locator('#board canvas')).to_be_visible()

def action(page,name):
    page.locator(f'[data-action="{name}"]').click()

def show_lobby(page,mode='chess'):
    page.locator('#online-open').click()
    expect(page.locator('#online-name')).to_be_enabled()

def create(page, mode):
    show_lobby(page)
    page.locator('#online-name').fill('QA ขาว')
    page.locator('#online-mode').select_option(mode)
    page.locator('#online-create').click()
    expect(page.locator('#online-room')).to_be_visible()
    return page.locator('#online-invite').input_value()

def join(page,invite):
    page.goto(invite)
    expect(page.locator('#online-name')).to_be_enabled()
    page.locator('#online-name').fill('QA ดำ')
    page.locator('#online-join').click()
    expect(page.locator('[data-action=confirm]')).to_be_visible()

def setup_online(white,black):
    expect(white.locator('[data-action=confirm]')).to_be_visible()
    for i in ['a2','d2','c2','b2']:tile(white,i)
    action(white,'confirm')
    for i in ['a7','b8','e7','b6','b6']:tile(black,i)
    action(black,'confirm')
    expect(white.locator('#phase-title')).to_contain_text('ตาของคุณ')

def own_skills_and_duel(white,black):
    setup_online(white,black)
    tile(white,'b6')
    expect(white.locator('#piece-skills')).to_be_hidden()
    tile(black,'b6')
    expect(black.locator('#piece-skills')).to_contain_text('ดวล Tic Tac Toe')
    expect(black.locator('#piece-skills')).to_contain_text('เดินเปิดทาง')
    for i in ['b2','b4']:tile(white,i)
    expect(black.locator('#phase-title')).to_contain_text('ตาของคุณ')
    for i in ['b6','a5']:tile(black,i)
    expect(white.locator('#phase-title')).to_contain_text('ตาของคุณ')
    for i in ['b4','a5']:tile(white,i)
    expect(white.locator('#duel-dialog')).to_be_visible()
    expect(black.locator('#duel-dialog')).to_be_visible()

def new_page(context,url):
    p=context.new_page()
    p.set_default_timeout(6500)
    p.goto(url,wait_until='domcontentloaded',timeout=10000)
    return p

def suite(phase):
    results=[]
    if phase=='regression':
        results.extend(previous_suite('browser'))
    with server(phase) as url,tempfile.TemporaryDirectory(dir=E) as profile,sync_playwright() as p:
        ctx=p.chromium.launch_persistent_context(profile,headless=True,executable_path=CHROME,args=args,no_viewport=True)
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(url+'/') else r.abort())
        ctx.tracing.start(screenshots=True,snapshots=True,sources=False)
        one=new_page(ctx,url+'/')
        two=None
        def verify(id,fn,page=one):
            record(id,fn,results)
            if results[-1]['status']!='PASS':
                page.screenshot(path=str(E/(id+'.png')),full_page=True)
        try:
            if phase=='smoke':
                def homepage():
                    errs=[]; failed=[]
                    one.on('pageerror',lambda e:errs.append(str(e)))
                    one.on('requestfailed',lambda e:failed.append(urlsplit(e.url).path))
                    response=one.reload(wait_until='networkidle')
                    assert response.status==200 and one.locator('header h1').is_visible()
                    assert not errs and not failed,(errs,failed)
                    assert prior.request('/api/health')[0]==prior.request('/api/rooms/health')[0]==200
                    return 'หน้าแรกและ health 200'
                verify('SM-01',homepage)
                def main_surfaces():
                    one.locator('header [data-open-themes]').click()
                    expect(one.locator('#theme-dialog')).to_be_visible()
                    one.keyboard.press('Escape')
                    start(one,'chess')
                    one.locator('#rules-button').click()
                    expect(one.locator('#rules')).to_be_visible()
                    one.keyboard.press('Escape')
                    one.locator('#menu-button').click()
                    return 'ธีม, กระดาน, กติกา, กลับเมนู'
                verify('SM-02',main_surfaces)
                two=new_page(ctx,url+'/')
                def online():
                    invite=create(one,'chess')
                    join(two,invite)
                    expect(one.locator('[data-action=confirm]')).to_be_visible()
                    one.locator('#online-leave').click()
                    expect(one.locator('#menu')).to_be_visible()
                    return 'สร้าง/เข้าห้อง/กลับเมนูด้วยชื่อทดสอบ'
                verify('SM-03',online)
            elif phase=='regression':
                two=new_page(ctx,url+'/')
                def online():
                    join(two,create(one,'hybrid'))
                    own_skills_and_duel(one,two)
                    for index, page in [(0,two),(3,one),(1,two),(4,one),(2,two)]:
                        cell=page.locator(f'#duel-grid [data-cell="{index}"]')
                        expect(cell).to_have_attribute('aria-disabled','false')
                        cell.focus()
                        page.keyboard.press('Enter')
                        if index==0:
                            expect(one.locator('#duel-grid [data-cell="0"]')).to_have_attribute('data-mark','X')
                            two.reload(wait_until='domcontentloaded')
                            expect(two.locator('#duel-grid [data-cell="0"]')).to_have_attribute('data-mark','X',timeout=10000)
                    expect(one.locator('#duel-continue')).to_be_visible()
                    expect(two.locator('#duel-continue')).to_be_visible()
                    two.locator('#duel-continue').click()
                    one.locator('#duel-continue').click()
                    expect(one.locator('#board [data-coordinate="b4"]')).to_have_attribute('aria-label',__import__('re').compile('ช่องว่าง'))
                    expect(two.locator('#board [data-coordinate="a5"]')).to_have_attribute('aria-label',__import__('re').compile('เบี้ยฝ่ายดำ'))
                    return 'สองแท็บแยกที่นั่ง ตรวจสกิลลับ รีโหลดกลาง XO และผลสวนกิน'
                verify('REG-01',online)

                def permanent_leave():
                    white=new_page(ctx,url+'/')
                    white.set_viewport_size({'width':320,'height':760})
                    black=new_page(ctx,url+'/')
                    join(black,create(white,'hybrid'))
                    own_skills_and_duel(white,black)
                    white.bring_to_front()
                    leave=white.locator('#duel-leave-permanently')
                    leave.click()
                    dialog=white.locator('#online-leave-dialog')
                    cancel=white.locator('#online-leave-cancel')
                    expect(dialog).to_be_visible()
                    expect(cancel).to_be_focused()
                    bounds=dialog.bounding_box()
                    assert bounds and bounds['x']>=0 and bounds['x']+bounds['width']<=320
                    white.screenshot(path=str(E/'leave-confirmation-320.png'))
                    cancel.click()
                    expect(dialog).not_to_be_visible()
                    expect(white.locator('#duel-dialog')).to_be_visible()

                    leave.click()
                    white.locator('#online-leave-confirm').click()
                    expect(white.locator('#menu')).to_be_visible()
                    expect(white.locator('#online-status')).to_have_text('ออกจากห้องถาวรแล้ว')
                    expect(white.locator('#online-open')).to_be_focused()
                    assert 'room=' not in white.url
                    assert white.evaluate("JSON.parse(sessionStorage.getItem('hidden-orders:online-seats:v2')).length") == 0

                    black.bring_to_front()
                    expect(black.locator('#menu')).to_be_visible(timeout=15000)
                    expect(black.locator('#online-status')).to_contain_text('คู่เล่นออกจากห้องถาวร')
                    return 'ออกถาวรจาก XO ที่ 320 px ยกเลิกได้ และแจ้งคู่เล่น'

                verify('REG-02',permanent_leave)
            elif phase=='ui':
                def responsive(width):
                    one.set_viewport_size({'width':width,'height':900})
                    one.goto(url+'/')
                    expect(one.locator('#menu')).to_be_visible()
                    assert one.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    one.locator('header [data-open-themes]').click()
                    expect(one.locator('#theme-dialog')).to_be_visible()
                    bb=one.locator('#theme-dialog').bounding_box()
                    assert bb['x']>=0 and bb['x']+bb['width']<=width
                    one.keyboard.press('Escape')
                    one.screenshot(path=str(E/f'menu-{width}.png'),full_page=True)
                    return {'width':width,'dialog_width':round(bb['width'],1)}
                for width in [320,375,768,1024,1440]:
                    verify('UI-'+str(width),lambda w=width:responsive(w))
            elif phase=='a11y':
                def invalid_name():
                    show_lobby(one)
                    name=one.locator('#online-name')
                    name.fill(' '*3)
                    one.locator('#online-create').click()
                    status=one.locator('#online-dialog-status')
                    expect(status).to_be_visible()
                    expect(name).to_be_focused()
                    actual={'aria-invalid':name.get_attribute('aria-invalid'),'aria-describedby':name.get_attribute('aria-describedby'),'text':status.inner_text()}
                    assert actual['aria-invalid']=='true' and 'online-dialog-status' in (actual['aria-describedby'] or ''),str(actual)
                    return actual
                verify('A11Y-01',invalid_name)
                one.keyboard.press('Escape')
                def local_keys():
                    start(one,'hybrid')
                    for square in ['a2','d2','c2','b2']:tile(one,square)
                    action(one,'confirm'); action(one,'black')
                    for square in ['a7','b8','e7','b6','b6']:tile(one,square)
                    confirm=one.locator('[data-action="confirm"]')
                    confirm.focus()
                    one.keyboard.press('Enter')
                    expect(one.locator('#history-title')).to_be_visible()
                    focus=one.evaluate("() => ({tag:document.activeElement.tagName, inside:document.querySelector('#game-view').contains(document.activeElement)})")
                    actual=focus['inside']
                    if not actual:
                        one.screenshot(path=str(E/'A11Y-03.png'))
                    results.append({'id':'A11Y-03','expected':'focus in game after setup','actual':focus,'status':'PASS' if actual else 'FAIL'})
                    for square in ['b2','b4','b6','a5','b4','a5']:tile(one,square)
                    x=one.locator('#duel-grid [data-cell="1"]')
                    expect(x).to_be_visible()
                    x.focus(); one.keyboard.press('Enter')
                    expect(x).to_have_attribute('aria-disabled','true')
                    expect(x).to_be_focused()
                    one.keyboard.press('ArrowRight')
                    expect(one.locator('#duel-grid [data-cell="2"]')).to_be_focused()
                    return 'XO ช่องที่ลงแล้วคง focus และลูกศรทำงานตามทิศ'
                verify('A11Y-02',local_keys)
                white=new_page(ctx,url+'/')
                black=new_page(ctx,url+'/')
                def duel_connection_status():
                    join(black,create(white,'hybrid'))
                    own_skills_and_duel(white,black)
                    code=white.locator('#online-room-code').inner_text()
                    white.route(url+'/api/rooms/'+code,lambda r:r.abort() if r.request.method=='GET' else r.continue_())
                    status=white.locator('#online-status')
                    expect(status).to_contain_text('การเชื่อมต่อขัดข้อง',timeout=8000)
                    active=white.locator('#duel-dialog').inner_text()
                    evidence={'room_status':status.inner_text(),'duel_contains_connection_status':'การเชื่อมต่อขัดข้อง' in active}
                    assert evidence['duel_contains_connection_status'],str(evidence)
                    white.unroute(url+'/api/rooms/'+code)
                    white.bring_to_front()
                    expect(white.locator('#duel-connection-status')).to_have_text('',timeout=15000)
                    return {**evidence,'cleared_on_reconnect':True}
                verify('A11Y-04',duel_connection_status,page=white)
        finally:
            if any(i['status']!='PASS' for i in results):
                ctx.tracing.stop(path=str(E/(phase+'-trace.zip')))
            else: ctx.tracing.stop()
            ctx.close()
    return report(phase,results)




