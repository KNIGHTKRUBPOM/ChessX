# การตัดสินใจทางสถาปัตยกรรม

| เรื่อง | เลือกและเหตุผล | ทางเลือกที่ประเมิน |
|---|---|---|
| ฐาน Git | ใช้ `main` ของ ChessX เป็น parent แล้ว import โค้ด ChessMess ที่ deploy อยู่เข้า `feat/auth-cicd` เพราะ remote มีเพียง README | สร้างโปรเจกต์ใหม่ หรือ rewrite ประวัติ remote |
| Auth | เก็บ FastAPI แบบ same-origin และใช้ GoTrue REST/PKCE ใน runtime เพื่อคง access และ refresh ในคุกกี้ HttpOnly ใช้ `@supabase/supabase-js` จริงใน integration test เพื่อทดสอบ RLS และ Auth โดยตรง | ใช้ browser SDK ถือ session หรือย้าย BFF ไป Node และใช้ `@supabase/ssr` |
| Providers | Google, Facebook และอีเมล ใช้ OTP ใน Mailpit local, Custom SMTP บน hosted | Provider อื่นรวม LINE ต้องกำหนดขอบเขตและตรวจการรองรับก่อนเปิด |
| MFA | TOTP เป็นตัวเลือกผู้เล่นและบังคับ AAL2 ต่อรายการสำคัญเมื่อเปิดใช้ รองรับปัจจัยสำรองโดยเพิ่ม Authenticator ก่อนทำอุปกรณ์เดิมหาย | SMS มีต้นทุนและความเสี่ยงจาก SIM swap |
| เกม | คงผู้เล่นแขก, HTTP poll, FastAPI กติกา, RPC revision check และ snapshot เฉพาะที่นั่ง | Realtime private channel, server WebSocket และ public leaderboard รอหลักฐานความต้องการ |
| ข้อมูล | บัญชี โปรไฟล์ ประวัติ และสถิติของตัวเอง ไม่มีข้อมูลการเงินหรือรายการซื้อ ยืนยันทั้งสองบัญชีก่อนบันทึกสถิติ | หากเพิ่มทรัพย์สินในเกม ให้เพิ่ม ledger ฝั่ง server ใน migration ใหม่ |
| Environment | local ใช้ Docker, staging และ production ใช้คนละ Supabase Project; preview ใช้ staging URL/DB พร้อมปิด Auth ตามแผน | Shared production credentials หรือ wildcard redirect ข้าม environment |
| Approval | production workflow manual จาก tag ที่อยู่บน main มี reviewer, explicit approval, backup และ migration dry-run | Deploy อัตโนมัติจาก merge หรือรัน SQL ใน Dashboard |

สมมติฐานที่ใช้คือเกมสำหรับกลุ่มเล็กในช่วงแรก เกมแขกยังสำคัญ ไม่มีระบบเงินจริง และยังไม่มีคำขอ Provider เพิ่มเติมหรือ webhook แจ้งเตือนภายนอก ตั้งสมมติฐานด้านอายุข้อมูลให้ทบทวนกับผู้ดูแลตาม [Security](SECURITY.md) ก่อนเปิดใช้งานบัญชีสาธารณะ
