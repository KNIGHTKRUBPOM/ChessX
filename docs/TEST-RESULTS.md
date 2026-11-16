# ผลตรวจรับ ChessX

วันที่ 16 พฤศจิกายน 2026 · ทดสอบบน Docker และ localhost แยกจาก staging และ production ใช้บัญชีสังเคราะห์และส่ง OTP เข้า Mailpit เท่านั้น

| การทดสอบ | ผล | ขอบเขต |
| --- | --- | --- |
| Unit | Python 40/40 ผ่าน 3 รอบ; Node 3/3 | กติกาหมากรุก หมากฮอส โหมดผสม ดวล Tic Tac Toe และ helper ฝั่งเว็บ |
| API และ integration แบบจำลอง | บัญชี 13/13, API เกม 67/67, การตรวจมาตรการป้องกัน 5/5, room store 4/4 | OAuth/PKCE และการผูกบัญชีใช้ผู้ให้บริการจำลอง ตรวจห้องข้าม worker และการเขียนพร้อมกัน |
| Postgres จริงใน Supabase local | pgTAP 68/68; SQL lint ผ่าน; ไม่พบ schema drift; TypeScript types ตรง | RLS, AAL1/AAL2, ข้อจำกัดโปรไฟล์, การเขียนผลครั้งเดียว, การลบข้อมูล และการเก็บตามอายุ |
| Auth integration จริง | ผ่าน | สมัครและยืนยันอีเมล, login, refresh, logout, กู้รหัส, TOTP, โปรไฟล์ที่อ่านกลับผ่าน SDK, ยืนยันการเปลี่ยนอีเมลทั้งสองที่อยู่, export และลบบัญชีทดสอบ |
| Chromium | smoke 3/3, regression 22/22, การเข้าถึงด้วยคีย์บอร์ด 4/4, บัญชีจำลอง 2/2, บัญชีจริงใน local ผ่าน | จากหน้าเกม: สมัคร → OTP → ล็อกอิน → เปิดเกม → ออกจากระบบ → กู้รหัส → ตั้ง TOTP → ล็อกอินด้วย TOTP → ลบบัญชี |
| CI และ build | actionlint ผ่านทั้ง 7 workflows; release guard 9/9; lint, typecheck, build, SBOM และ bundle scan ผ่าน | ตรวจ pipeline ในเครื่อง และตรวจว่า bundle ไม่มีรูปแบบคีย์ฝั่งเซิร์ฟเวอร์ที่ชุดตรวจรู้จัก |

กติกาหลักฝั่ง Python ครอบคลุมบรรทัด 452/453 (99.8%) และ branch 195/198 (98.5%); มีการเรียกใช้ 41/41 ฟังก์ชันในชุดที่วัด ตัวเลขนี้ไม่รวม FastAPI, Auth และ UI จึงไม่ใช่ coverage ของทั้งโปรเจกต์

การทดสอบจริงพบว่า GoTrue ส่ง QR ของ TOTP ใหญ่กว่าขีดจำกัดเดิม จึงปรับเพดานเฉพาะการลงทะเบียนปัจจัยและทดสอบซ้ำผ่าน อีกกรณีคือชุด Chromium ต้องรอให้หน้าต่างกู้รหัสปิดก่อนเริ่มกรอกรหัสผ่านใหม่ และหน้าเกมจะอัปเดต session ก่อนคืนโฟกัสให้ฟอร์มล็อกอิน

สิ่งที่ต้องยืนยันใน staging: Google/Facebook กับ provider จริง รวมกรณีอีเมลตรงกัน, SMTP จริงและการส่งถึงปลายทาง, CAPTCHA, การตั้ง security headers และ redirect บนโดเมนจริง, Supabase Advisors และการตรวจ release จริงตาม [คู่มือ CI/CD](CICD.md) การตรวจ workflow ในเครื่องไม่ใช่ผลของ GitHub runner และการผ่าน Chromium ไม่ยืนยันเบราว์เซอร์อื่น

รันซ้ำด้วย `npm run test:all` หลังเปิด stack ตาม [README](../README.md) ผลรัน QA อยู่ใต้ `qa-report/evidence/` ในเครื่อง และหลักฐาน Chromium ที่ล้มเหลวจากชุด local auth อยู่ใต้ `test-results/local-auth/` ซึ่งไม่ถูก commit
