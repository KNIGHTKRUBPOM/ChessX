# ChessMess · QA runner รอบ 15 พฤศจิกายน 2026

ใช้ PowerShell จากโฟลเดอร์โปรเจกต์ มี Python ที่ import Playwright และ coverage ได้, Windows Google Chrome ที่ `C:\Program Files\Google\Chrome\Application\chrome.exe`, FastAPI ใน `.venv\Scripts\python.exe` และ build `dist` ของรุ่นที่จะตรวจ ใช้เครื่องมือที่มีอยู่แล้วในการตรวจครั้งนี้

```powershell
Set-Location -LiteralPath 'C:\Users\User\Desktop\Chess'
$env:CHESS_QA_RUN='fixes-2026-11-15'
python -B .\qa-report\tests\run_qa.py
```

คำสั่งเดียวรัน Smoke → Regression → Integration → Unit (3 รอบ) → UI → A11y → Performance → Security → Account API → Account UI และคืน exit 1 เมื่อ suite ล้มเหลวหรือ checksum ของซอร์สเปลี่ยน รุ่นหลังแก้ผ่าน A11Y-01, A11Y-03 และ A11Y-04 ดู [ผลหลังแก้](../FIX-VERIFICATION-2026-11-15.md) หลักฐานก่อนแก้อยู่ใน `qa-2026-11-15` กำหนด `CHESS_QA_RUN` เป็นชื่อโฟลเดอร์ใหม่เมื่อต้องการเก็บผลเพิ่ม

```powershell
python -B .\qa-report\tests\run_qa.py baseline
python -B .\qa-report\tests\run_qa.py smoke regression integration unit
python -B .\qa-report\tests\run_qa.py a11y
python -B .\qa-report\tests\run_qa.py ui performance security
python -B .\qa-report\tests\run_qa.py accounts account-browser
python -B .\qa-report\tests\run_qa.py rooms-db
python -B .\qa-report\tests\inventory_2026_11_15.py
```

| Script | ขอบเขต |
|---|---|
| `e2e/web.py` | Smoke, two-tab Hybrid, responsive, keyboard/focus, offline simulation ใน browser |
| `integration/endpoints.py` | API schema, validation, XO outcomes, HTTP contract และ compression |
| `integration/defensive.py` | Headers, docs off, access checks และ structured audit logs |
| `integration/rooms_db.py` | RPC จำลองผ่าน HTTPS loopback ทดสอบห้องข้าม FastAPI process, คำสั่งพร้อมกัน, สกิลลับ และ database outage |
| `integration/accounts.py` | Signup และ OTP, login, session/refresh/logout และ cookie attributes ด้วย provider จำลอง |
| `e2e/accounts.py` | ฟอร์มบัญชีและ focus ด้วย Chromium และ API จำลอง |
| `unit/test_business_rules.py` | Unit cases แยกตาม rules, validation และ room helper |
| `unit/verify_rules.py` | unittest 3 รอบ พร้อม statement/branch/function entry coverage |
| `retest_local.py` | Baseline เดิมที่ runner นำกลับมาใช้กับ browser/API |
| `inventory_2026_11_15.py` | Static inventory และ contrast pairs |

Runner เปิด Uvicorn 1 worker บน `127.0.0.1` พอร์ตชั่วคราว ใช้ rooms ใน RAM ใหม่และโปรไฟล์ Chromium ทดสอบ รายการ Playwright request อนุญาตแค่ origin ที่เปิดให้ทดสอบ ปิด server เมื่อจบ ชุด Account API ใช้ FastAPI TestClient และ HTTPX ที่มีใน Python ฝั่ง QA ส่วน Account UI ดักคำขอกับ fixture ใน loopback ทั้งสองชุดไม่ติดต่อ Supabase จริง หลักฐานอยู่ใน `../evidence/$CHESS_QA_RUN/` ใช้ชื่อเดิมเมื่อยอมให้ผลรอบนั้นถูกเขียนทับ Trace อาจมีข้อมูลชั่วคราวของห้องจำลอง ควรเก็บใน artifact store แบบจำกัดสิทธิ์

ชุด `rooms-db` ต้องใช้ OpenSSL จาก PATH หรือ Git for Windows ที่มีอยู่แล้วเพื่อสร้างใบรับรอง loopback ชั่วคราว ใช้ RPC จำลองและหลายโปรเซส FastAPI จึงยังต้องทดสอบ migration กับ PostgreSQL จริงแยกต่างหาก

## ผูกเข้า CI

ติดตั้ง runtime/เครื่องมือใน runner แยก Build frontend และติดตั้ง Python จาก lock ก่อนเริ่มทดสอบ ใช้ Windows runner กับ path ปัจจุบัน หรือปรับ Chrome/venv paths ใน test harness สำหรับ Linux รันคำสั่งเดียวข้างต้น แล้วอัปโหลด JSON, ภาพและ trace เมื่อมีผล FAIL หลังแก้ Q04–Q06 แล้วตั้ง suite ให้เป็น release gate

[Test cases](CASES.md) · [รายงาน](../REPORT.md)

