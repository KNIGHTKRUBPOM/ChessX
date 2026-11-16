# หมากซ่อนคำสั่ง

เกมสองคนบนเครื่องเดียวหรือคนละเครื่องผ่านห้องออนไลน์ มีหมากรุก หมากฮอสไทย และ Chess vs หมากฮอส กระดานหลักและ Tic Tac Toe ใช้ Phaser ส่วนหน้าเลือกโหมด ปุ่ม และกล่องคำสั่งใช้ HTML กับ CSS

## เล่นด้วย Python และ FastAPI

ติดตั้ง CPython 3.11–3.15 บน Windows x64 ดับเบิลคลิก `start-game.cmd` เพื่อเปิดเกมที่ [localhost:3210](http://localhost:3210/) ครั้งแรกตัวเปิดเกมจะสร้าง `.venv` และติดตั้ง wheel จาก `requirements.lock` พร้อมตรวจ SHA-256 ถ้ามีตัวรันเกมแบบสแตติกค้างอยู่ที่พอร์ต 3210 ให้ปิดก่อน

หาก localhost เปิดไปที่ Vite ให้เปิด [127.0.0.1:3210](http://127.0.0.1:3210/) ระหว่างที่ FastAPI ทำงาน เซฟเครื่องเดียวและธีมจะอิงกับชื่อโฮสต์ที่ใช้เปิดเกม

เปิดจากเทอร์มินัลได้ด้วย

```sh
python -m pip install -r requirements.lock
python -m backend.launch --open
```

ตัวรันจะเปิดทั้งเกมและ API ที่ URL เดียวกัน FastAPI ตรวจการวางสกิล คำนวณตาเดิน ตรวจการกินและคำสั่งบังคับ และตัดสินผล Tic Tac Toe ดู API และตัวอย่างข้อมูลได้ที่ [Swagger UI](http://localhost:3210/docs)

โปรไฟล์และเซฟของโหมดเล่นเครื่องเดียวอยู่ใน `localStorage` ของเบราว์เซอร์ หากเคยเล่นที่ `http://localhost:3210/` ให้ใช้เบราว์เซอร์และ URL เดิมเพื่อเปิดเซฟ

## บัญชีผู้เล่นด้วย Supabase Auth

เปิด **เข้าสู่ระบบ** แล้วเลือก **สมัครสมาชิก** เพื่อสมัครด้วยชื่อที่แสดง อีเมล และรหัสผ่าน ยืนยันอีเมลด้วยรหัส 6–10 หลักตามค่า Email OTP ของโปรเจกต์ แล้วล็อกอินหรือออกจากระบบได้ Supabase Auth จัดการรหัสผ่านและเก็บบัญชีใน `auth.users` โดยเก็บชื่อที่แสดงใน user metadata

### ตั้งค่า Supabase

1. เปิด Email provider, การสมัครผู้ใช้ใหม่ และ **Confirm email** ใน Supabase Auth
2. ตั้ง **Site URL** ให้ตรงกับหน้าเกม เช่น `http://localhost:3210` สำหรับการทดสอบ หรือโดเมน HTTPS ของ Production
3. ใน **Authentication → Email Templates → Confirm sign up** ตั้งหัวข้ออีเมล เช่น `รหัสยืนยันบัญชี ChessMess` แล้วใช้เทมเพลตนี้ กรอกรหัสที่ได้รับในหน้า **ยืนยันอีเมล** ของเกม

```html
<h2>ยืนยันบัญชี ChessMess</h2>
<p>กรอกรหัสนี้ในหน้าเกมเพื่อยืนยันอีเมลของคุณ</p>
<p><strong>{{ .Token }}</strong></p>
```

4. ตั้งตัวแปรฝั่ง FastAPI โดยใช้ Project URL และ **Publishable key** ของ Supabase โปรเจกต์เดียวกัน

```powershell
$env:SUPABASE_URL='https://PROJECT-REF.supabase.co'
$env:SUPABASE_PUBLISHABLE_KEY='sb_publishable_...'
$env:APP_ORIGIN='http://localhost:3210'
.\.venv\Scripts\python.exe -B -m backend.launch
```

เปิดเกมจาก origin ที่ระบุใน `APP_ORIGIN` ซึ่งต้องตรงทั้ง scheme, host และ port หาก FastAPI เปิดอยู่แล้วให้หยุดตัวที่เปิดเองแล้วสตาร์ทจากเทอร์มินัลที่ตั้งค่า การเล่นเครื่องเดียวและการเข้าห้องด้วยชื่อเล่นยังเปิดได้ระหว่างที่ยังไม่ได้ตั้งค่า Supabase

### ใช้กับโฮสต์จริง

- ตั้ง `CHESS_ENV=production` และตัวแปร `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` และ `APP_ORIGIN`ใน environment ของ FastAPI ใช้ URL HTTPS จริงเป็น `APP_ORIGIN` เก็บค่าฝั่งเซิร์ฟเวอร์และใช้ Publishable key สำหรับ Auth
- ตั้ง Custom SMTP และเทมเพลตรหัสยืนยัน แล้วทดสอบสมัคร ยืนยัน และล็อกอินจากโปรไฟล์เบราว์เซอร์ใหม่ โปรเจกต์ Supabase Free ใหม่ต้องเปิด Custom SMTP ก่อนแก้เทมเพลตของ Auth ระหว่างตั้งค่าให้ใช้ `CHESS_ACCOUNT_ENABLED=0` เพื่อเปิดเล่นแบบแขกก่อน ตั้งเป็น `1` แล้ว deploy อีกครั้งเมื่ออีเมลพร้อม [คู่มือ SMTP](https://supabase.com/docs/guides/auth/auth-smtp) · [ข้อจำกัดแผน Free](https://supabase.com/changelog/46599-changes-to-email-template-customisation-on-free-tier)
- บน Vercel ใช้โดเมน Production เป็น `APP_ORIGIN` แล้วตั้งค่าตามหัวข้อ [ขึ้น Vercel ด้วย Supabase](#ขึ้น-vercel-ด้วย-supabase)
- ข้อมูลที่ซิงก์ผ่าน Supabase รอบนี้คือบัญชี อีเมล และชื่อที่แสดง ธีมกับเซฟเล่นเครื่องเดียวยังผูกกับเบราว์เซอร์ ผู้เล่นเข้าห้องผ่านลิงก์เชิญและใช้โทเค็นที่นั่งของแท็บนั้น

## เล่นออนไลน์กับเพื่อน

เปิดเกมผ่าน FastAPI แล้วกด **เล่นออนไลน์** ใช้ชื่อเล่น เลือกโหมดและสร้างห้อง จากนั้นส่งลิงก์เชิญหรือรหัสห้องให้เพื่อน ผู้เล่นทั้งสองวางสกิลจากเครื่องของตัวเองและเริ่มเมื่อพร้อมทั้งคู่ ลองบนเครื่องเดียวได้โดยเปิดสองแท็บแยกกันหรือใช้หน้าต่างไม่ระบุตัวตนกับแท็บที่สอง

FastAPI ตรวจตาเดิน จัดการสกิลและตัดสิน XO หน้าเว็บดึงสถานะห้องประมาณทุกหนึ่งวินาที รีเฟรชแท็บเดิมเพื่อกลับเข้าฝั่งเดิมได้ ห้องที่รอเพื่อนหมดอายุใน 15 นาที ห้องที่เริ่มแล้วหมดอายุหลังไม่มีการเปลี่ยนแปลง 6 ชั่วโมง การเปิดด้วยตัวรันในเครื่องจะเก็บห้องใน RAM ส่วน Vercel เก็บห้องใน Supabase

## พัฒนาและ build หน้าเกม

ใช้ Node.js 24 LTS พร้อม npm

```sh
npm ci
npm run build
```

หลัง build ให้เปิดตัวรัน Python เพื่อทดสอบครบทั้งหน้าเกมและ API ถ้าพัฒนาเฉพาะหน้าเกมให้ใช้ `npm run dev` หรือ `start-static.cmd` เกมจะใช้กติกา TypeScript ในเบราว์เซอร์

## ขึ้นเว็บ

- **FastAPI** ใช้ CPython 3.11–3.15 บน Linux x64 หรือ ARM64 ที่ใช้ glibc หรือ Windows x64 รันคำสั่ง build อีกครั้งจาก checkout ที่จะเผยแพร่ แล้วใช้ production entrypoint ด้านล่าง
- **Static hosting** อัปโหลดไฟล์ทั้งหมดใน `dist/` เพื่อเล่นเครื่องเดียวครบทุกโหมดด้วย TypeScript ในเบราว์เซอร์ สำหรับเล่นผ่านห้องให้ใช้โฮสต์ FastAPI

```sh
python -m pip install --require-hashes -r requirements.lock
npm ci --include=dev
npm run build
python -B deploy.py --check
python -B deploy.py
```

`deploy.py --check` เปิด release ชั่วคราวบน loopback และตรวจหน้าแรก API health และการปิด developer docs หากไม่ผ่านให้แก้ก่อนเปิดบริการ `deploy.py` เปิด production บน `PORT` ที่โฮสต์ให้หรือพอร์ต 8000 โดยใช้ worker เดียว และปิด access log ของ Uvicorn เพื่อไม่ให้ URL เชิญติด log ส่วน structured audit log ยังทำงาน

### ขึ้น Vercel ด้วย Supabase

1. เปิดโปรเจกต์ใน [Supabase](https://supabase.com/dashboard) เปิด Data API และรันไฟล์ [online rooms migration](supabase/migrations/20261115180000_online_rooms.sql) หนึ่งครั้งใน SQL Editor หากจัดการ migration ด้วย Supabase CLI อยู่แล้ว ให้ใช้ workflow migration ของโปรเจกต์ ไฟล์นี้สร้างเฉพาะ schema และ RPC ของ ChessMess
2. เปิดการสมัครด้วยอีเมล เปิด Confirm email และตั้งเทมเพลต `{{ .Token }}` ตามหัวข้อบัญชี จากนั้นตั้ง custom SMTP เมื่อต้องการส่งอีเมลให้ผู้เล่นทั่วไป [คู่มือ SMTP](https://supabase.com/docs/guides/auth/auth-smtp)
3. นำ source ขึ้น GitHub แล้ว import repository ใน [Vercel](https://vercel.com/new) โดยใช้ root ของโปรเจกต์และ FastAPI preset ไฟล์ `vercel.json` มีคำสั่งติดตั้งตาม lock และ build Vite อยู่แล้ว หรือ deploy จากเครื่องที่ล็อกอิน CLI [วิธี deploy](https://vercel.com/docs/deployments)
4. ใน Vercel ที่ **Settings → Environment Variables** ตั้งค่าต่อไปนี้สำหรับ Production แล้ว deploy

| ตัวแปร | ค่าที่ใช้ |
| --- | --- |
| `SUPABASE_URL` | Project URL เช่น `https://PROJECT-REF.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | Publishable key ที่ขึ้นต้น `sb_publishable_` สำหรับบัญชีผู้เล่น |
| `SUPABASE_SECRET_KEY` | Secret key ที่ขึ้นต้น `sb_secret_` สำหรับ API ห้อง ตั้งชนิด Secret ใน Vercel |
| `APP_ORIGIN` | URL หน้าเกม Production เช่น `https://chessmess.vercel.app` ใช้โดเมนเดียวกันเป็น Supabase Auth Site URL |

เก็บ Secret key ใน environment ฝั่งเซิร์ฟเวอร์ ตัวแปรที่ขึ้นต้น `VITE_` จะอยู่ใน frontend build ใส่เฉพาะค่าที่เปิดเผยได้ในตัวแปรกลุ่มนั้น [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys) · [Vercel environment variables](https://vercel.com/docs/environment-variables)

5. เปิด Production URL ตรวจว่า `/api/rooms/health` ตอบ 200 แล้วสมัคร ยืนยันอีเมล และล็อกอินจริง ลองเปิดสองเบราว์เซอร์เพื่อสร้างห้อง เข้าด้วยลิงก์เชิญ รีเฟรชทั้งสองฝั่ง และเล่น XO ก่อนแชร์ลิงก์

ตัวเปิด Vercel บังคับโหมด production และใช้ Supabase เป็นแหล่งข้อมูลห้อง หากการตั้งค่าหรือ RPC ใช้งานไม่ได้ ระบบห้องจะตอบ 503 ให้ตรวจ URL, Secret key, Data API และ migration โหมดเล่นบนเครื่องเดียวเปิดได้ระหว่างตั้งค่า สำหรับ FastAPI ที่รันเอง เพิ่ม `CHESS_ROOM_STORE=supabase` เมื่อจะทดสอบหรือใช้ฐานข้อมูลเดียวกัน เลือกโปรเจกต์ Supabase แยกสำหรับ Preview หากต้องการทดสอบบน Vercel ก่อนขึ้น Production

### เผยแพร่ผ่าน GitHub และ Render

ให้ push ไฟล์ซอร์ส `render.yaml` และ lock files ของโปรเจกต์ขึ้น GitHub จากนั้นเลือก **New → Blueprint** บน Render แล้วเชื่อม repo เพื่อสร้างบริการ Free ตามไฟล์นี้ หรือใช้ **New → Web Service** แล้วกรอกค่าตารางด้วยตนเอง

ถ้ายังไม่มี Git repository ในเครื่อง ให้สร้าง repository เปล่าบน GitHub แล้วเปิดเทอร์มินัลในโฟลเดอร์ Chess ใช้ URL ของ repository แทนค่าในตัวอย่าง

```sh
git init -b main
git add .
git commit -m "Add online chess rooms"
git remote add origin https://github.com/USERNAME/REPOSITORY.git
git push -u origin main
```

| ค่า | กำหนดเป็น |
| --- | --- |
| Runtime | Python |
| Build Command | `python -m pip install --require-hashes -r requirements.lock && npm ci --include=dev && npm run build && python -B deploy.py --check` |
| Start Command | `python -B deploy.py` |
| Health Check Path | `/api/health` |
| จำนวน instance | 1 |
| Environment | `CHESS_ENV=production` |

ใช้ HTTPS และตั้ง HSTS ที่ reverse proxy หลังยืนยันว่าโดเมนใช้ HTTPS ครบ ตั้งเพดาน request และ timeout ให้เข้ากับแอป ปิดหรือปิดบัง invite path/query ใน access log ของ proxy หากโฮสต์ส่งต่อ IP ผู้เล่น ให้ Uvicorn รับ forwarded headers เฉพาะจาก proxy ที่เชื่อถือได้ หลัง deploy เปิด URL ของบริการแล้วสร้างห้องทดสอบ ลิงก์เชิญจะใช้ URL ของบริการ

### ดูแลห้องเมื่อรีสตาร์ต

เมื่อใช้ RAM ห้อง สิทธิ์ที่นั่ง และโควตาอยู่กับหนึ่ง worker หลัง redeploy, restart หรือพัก instance ให้สร้างห้องใหม่ เมื่อใช้ Supabase ห้องและสิทธิ์ที่นั่งอยู่ข้ามการรีสตาร์ตจนกว่าจะหมดอายุ และผู้เล่นกลับเข้าที่นั่งเดิมได้ด้วยแท็บเดิม เริ่มห้องใหม่เมื่อเปลี่ยนจาก RAM มาใช้ Supabase เซฟเล่นเครื่องเดียวเปิดจาก URL ที่เคยใช้ได้ตามเดิม
