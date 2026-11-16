# ChessX · ChessMess

เกมหมากรุก หมากฮอสไทย และโหมดผสม พร้อมซ่อนสกิลและดวล Tic Tac Toe เล่นสองคนบนเครื่องเดียวหรือเข้าห้องผ่านลิงก์เชิญ หน้าเกมใช้ TypeScript, Phaser และ Vite ส่วน FastAPI ตรวจตาเดินและจัดการ session กับ Supabase

[เว็บ Production ปัจจุบัน](https://chessmess.vercel.app/) · [คู่มือตั้งค่า](docs/MANUAL-SETUP.md) · [สถาปัตยกรรม](docs/ARCHITECTURE.md) · [CI/CD](docs/CICD.md) · [ความปลอดภัย](docs/SECURITY.md) · [การตัดสินใจ](docs/DECISIONS.md) · [ผลเทสต์](docs/TEST-RESULTS.md) · [ตรวจรับ Production](docs/PRODUCTION-CHECKLIST.md)

[![CI](https://github.com/KNIGHTKRUBPOM/ChessX/actions/workflows/ci.yml/badge.svg)](https://github.com/KNIGHTKRUBPOM/ChessX/actions/workflows/ci.yml)

## เริ่มจากเครื่องเปล่า

ใช้ Node.js 24 LTS, Python 3.12, Docker และ Supabase CLI 3.1.0 ติดตั้ง Chromium สำหรับ Playwright เมื่อจะรันเทสต์เบราว์เซอร์

```powershell
npm ci
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
npm run db:start
Copy-Item .env.example .env.local
```

ใช้ `supabase status` ดู URL กับคีย์ **ของ local** ใส่ `API_URL`, `PUBLISHABLE_KEY` และ `SECRET_KEY` ใน `.env.local` ให้ตรงกับชื่อตัวแปรตัวอย่าง แล้วเปิดเกมด้วย `npm run dev:full` ที่ `http://127.0.0.1:3210` อีเมลทดสอบอยู่ที่ [Mailpit](http://127.0.0.1:54324/) หากไม่ได้ติดตั้ง CLI ใน PATH ให้กำหนด `SUPABASE_CLI` เป็นพาธไฟล์ CLI ใน shell ก่อนใช้สคริปต์ npm

บน macOS/Linux ใช้ `python3 -m venv .venv`, `.venv/bin/python` และ `cp .env.example .env.local` ติดตั้ง browser พร้อม dependency ของ OS ด้วย `python -m playwright install --with-deps chromium` เมื่อต้องการ

สำหรับหน้าเกมแบบสแตติก รัน `npm run dev` หรือใช้ไฟล์ใน `dist/` หลัง build โหมดนี้เหมาะสำหรับเล่นเครื่องเดียว

## คำสั่งทดสอบทั้งหมด

เปิด Docker และรัน `npm run db:start` หนึ่งครั้ง จากนั้นใช้คำสั่งเดียว

```text
npm run test:all
```

| คำสั่ง | งาน |
|---|---|
| `npm run lint` · `npm run typecheck` · `npm run build` | ตรวจซอร์สและสร้าง dist |
| `npm run db:start` · `npm run db:migrate` | เปิด stack local และ apply migration ที่ยังไม่เคยรัน |
| `npm run db:reset` | สร้างฐาน local ใหม่จาก migrations และ seed ข้อมูลทดสอบ ใช้เมื่อพร้อมลบข้อมูล local |
| `npm run db:lint` · `npm run db:test` | Lint SQL และ pgTAP ใน local |
| `npm run db:types` · `npm run db:types:check` | สร้างหรือเทียบ Supabase Database types |
| `npm run test:unit` · `npm run test:integration` · `npm run test:e2e` | แยกทดสอบกติกาและ Auth, API/ฐานจริงใน local, หรือ Chromium และ Mailpit |

## โครงสร้าง

- `src/` และ `public/` สำหรับหน้าเกม การจัดการบัญชี และหน้าข้อมูลผู้เล่น
- `backend/` สำหรับกติกา API ห้อง และ Auth แบบ same-origin
- `supabase/` สำหรับ config local, SQL migrations, pgTAP, seed และเทมเพลตอีเมล
- `tests/` และ `qa-report/tests/` สำหรับ unit, API และ E2E
- `.github/workflows/` และ `scripts/ci/` สำหรับ CI, deployment และ smoke test

## เผยแพร่

ใช้ GitHub Actions ตาม [คู่มือ CI/CD](docs/CICD.md) กำหนด Vercel Project และ Supabase Project คนละตัวสำหรับ staging กับ production ตั้ง SMTP และ OAuth ใน environment ที่ตรงกันก่อนเปิดปุ่มบัญชี Production deploy ใช้ release tag จาก main, รีวิวใน GitHub Environment, ตรวจ dry-run และ backup ก่อน apply migration
