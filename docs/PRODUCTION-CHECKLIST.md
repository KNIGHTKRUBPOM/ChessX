# เช็กลิสต์เปิด ChessMess ใน Production

ให้ผู้รับผิดชอบระบุวันที่และแนบหลักฐานจาก staging หรือ production ตามรายการ โดยเก็บ log ที่ผ่านการลบข้อมูลอ่อนไหวแล้ว ดูตำแหน่งค่าที่ต้องกรอกใน [คู่มือตั้งค่า](MANUAL-SETUP.md) และขั้นตอนอนุมัติและย้อนรุ่นใน [คู่มือ CI/CD](CICD.md)

## ต้องมีก่อนเปิดบัญชีให้ผู้เล่นจริง

- [ ] Local ใช้ Supabase CLI และ Docker ส่วน staging กับ production ใช้ Supabase project และ Vercel project ที่แยกกัน ค่าของ GitHub Environments ชี้ไปยัง project และโดเมนที่ถูกต้อง
- [ ] ตั้งโดเมน HTTPS จริง บังคับ HTTPS และทดสอบ HSTS, CSP, `frame-ancestors`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` และ `Permissions-Policy` ตรวจคุกกี้ `Secure`, `HttpOnly`, `SameSite` และ `no-store` สำหรับข้อมูลบัญชีและห้อง
- [ ] กำหนด `CHESS_ENV=production` และ `APP_ORIGIN` ตรงโดเมนจริง ตรวจว่า `/docs`, `/redoc`, `/openapi.json` ไม่เปิด และ requests เขียนบัญชีจาก origin อื่นถูกปฏิเสธ ให้ frontend กับ API ของแอปใช้ origin เดียวกัน ตรวจว่า app และ Supabase ไม่มีการตั้ง CORS ที่กว้างเกินความจำเป็น ใช้ RLS และการตรวจ JWT ปกป้อง Data API
- [ ] ยืนยันว่า build และ Git ไม่มี service role key, secret key, DB password, OAuth client secret หรือ CI token ค่าดังกล่าวอยู่ใน secret store ของ environment ที่เกี่ยวข้องและไม่มีชื่อขึ้นต้น `VITE_`
- [ ] รัน migrations ตั้งแต่ฐานว่างใน local/staging ตรวจ drift, pgTAP, Data API และ Security Advisor/Performance Advisor เปิด RLS ทุกตาราง `public` และตรวจว่า anon อ่านข้อมูลบัญชีไม่ได้ ผู้ใช้เข้าถึงได้ตามเจ้าของและระดับ MFA ที่กำหนด รวมถึงเขียนสถิติหรือผลเกมเองไม่ได้
- [ ] เปิด email confirmations, secure password change, double-confirm email change และ TOTP ตามการตั้งค่าที่ทดสอบ ตั้ง OTP/JWT expiry และ rate limit ที่เหมาะสม เปิดอีเมลแจ้งเตือนเหตุเปลี่ยนรหัสผ่าน อีเมล และ MFA ตรวจ Thai OTP templates ด้วยอีเมลทดสอบ
- [ ] ตั้ง Custom SMTP และทดสอบ signup, recovery และ email change ถึงกล่องจดหมายจริง ตรวจ SPF/DKIM/DMARC, throttle, bounce และปิด link tracking ที่แก้ลิงก์ Auth
- [ ] ตั้ง callback และ exact allowlist ของ Google/Facebook แยก environment ตรวจ email verification/account linking, กรณียกเลิก consent และการ session หมดอายุ เปิดเฉพาะ provider ที่ทดสอบครบ
- [ ] เปิด CAPTCHA และ Auth rate limit ทดสอบ token ถูกต้อง/หมดอายุและการปฏิเสธด้วยตัวอย่างที่จำกัด ตรวจค่าตั้งหน้าเว็บตรงกับ provider ใน Supabase
- [ ] ยืนยันการกู้รหัสผ่านของบัญชีที่เปิด MFA ยังต้องใช้ TOTP ทดสอบ factor สำรอง เปลี่ยนรหัสผ่าน/อีเมล ผูกและยกเลิก provider การส่งออกข้อมูล ลบบัญชี และออกจากระบบทุกอุปกรณ์
- [ ] ตั้ง branch protection, แยกผู้อนุมัติ production environment, จำกัด tag/branch deploy และยืนยันว่า fork PR อ่าน deploy secrets ไม่ได้ ใช้ Git SHA และบันทึก migration dry-run ก่อนอนุมัติ release
- [ ] กำหนดระยะเวลาและผู้ดูแล backup/PITR ตามแผนบริการ ทดสอบ restore ใน environment แยก และวางขั้นตอนป้องกันการคืนข้อมูลที่ผู้ใช้เคยขอลบ ตั้ง retention job ของ account audit และประวัติการแข่งขันพร้อมตรวจผลใน staging
- [ ] ระบุผู้ควบคุมข้อมูล ช่องทางติดต่อจริง ผู้รับข้อมูล ที่ตั้ง/การส่งข้อมูล ระยะเวลาเก็บ นโยบายผู้เยาว์ และวันที่ใช้งานใน [Privacy draft](../public/privacy.html) และ [Terms draft](../public/terms.html) แล้วให้ผู้รับผิดชอบอนุมัติ ตรวจทั้งสอง URL จากโดเมนจริงก่อนส่ง app review ให้ผู้ให้บริการ OAuth
- [ ] เปิด MFA และจำกัดสิทธิ์ผู้ดูแล GitHub/Vercel/Supabase/Google/Meta ตรวจ uptime, 5xx, Auth failures, 429, SMTP และค่าใช้จ่าย ตั้งผู้รับแจ้งเตือนและทดสอบว่ารับได้จริง
- [ ] Smoke หลัง deploy ตรวจหน้าแรก หน้ากฎหมาย Health endpoint การล็อกอินอีเมลด้วยบัญชีทดสอบที่ได้รับอนุญาต การ redirect ของ OAuth และการสร้าง/เข้าห้อง เก็บหลักฐานเวอร์ชันที่ตรวจแล้ว

## ควรมี

- [ ] ตั้งการตรวจรหัสผ่านรั่วและข้อจำกัด session ตามแพ็กเกจ Runbook ระบุอายุที่ยอมรับได้ของ access token หลัง logout และเหตุที่ต้องเพิกถอน session เพิ่มเติม
- [ ] ตรวจ SSL enforcement/network restrictions สำหรับการเชื่อมฐานข้อมูลโดยตรงตามแพ็กเกจ ทดสอบว่า migration runner ยังเชื่อมได้ ตรวจการใช้งาน spend cap และผู้รับสัญญาณเตือน
- [ ] ตั้ง error tracking ที่ตัด auth payload, cookie, token, รหัส OTP, อีเมลและ URL callback ออกก่อนส่ง ตรวจ retention และสิทธิ์เข้าถึง log
- [ ] วัด latency/จำนวน polling ของห้องและคำขอ Auth ช่วง peak จาก staging กำหนดงบ p95, query latency และ refresh latency ตามข้อมูลที่วัดได้ พร้อม alert ก่อนถึง quota
- [ ] ทบทวนระยะเก็บบันทึกและ credential ทุกไตรมาส ฝึก incident/restore และทบทวนการปฏิบัติต่อคำขอใช้สิทธิ์ข้อมูลกับผู้รับผิดชอบ

## ทำภายหลังเมื่อมีความต้องการ

- [ ] พิจารณา Realtime แบบ private channel ตรวจ authorization ถ้าจำนวน polling หรือ latency ถึงเกณฑ์ที่วัดไว้
- [ ] เพิ่ม leaderboard หรือรางวัลเมื่อมีกติกาป้องกันการปั๊มอันดับและนโยบายข้อมูลสาธารณะชัดเจน
- [ ] เพิ่ม provider หรือช่องทางกู้ MFA เมื่อมีผู้ดูแลและทดสอบความปลอดภัยครบ
- [ ] พิจารณา Supavisor, compute และ read replica เมื่อมีตัวเลขจากการใช้งานจริงว่าฐานข้อมูลเป็นคอขวด ทดสอบต้นทุนและ replication lag ก่อนย้าย query

อ้างอิง [Supabase Production Checklist](https://supabase.com/docs/guides/deployment/going-into-prod) · [Supabase Production Security Checklist](https://supabase.com/docs/guides/security/production-checklist) · [Supabase Backups](https://supabase.com/docs/guides/platform/backups)
