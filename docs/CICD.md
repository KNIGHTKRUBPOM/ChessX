# CI/CD ของ ChessX

Workflow ใช้ runner `ubuntu-24.04`, Node จาก `.nvmrc`, Python จาก `.python-version`, Supabase CLI 3.1.0 และ Vercel CLI 65.16.0 ตรึง GitHub Actions ด้วย commit SHA งาน build ใช้ `npm ci` และ `pip install --require-hashes -r requirements.lock`

## Workflow

| ไฟล์ | งาน |
| --- | --- |
| `ci.yml` | Lint, type check, unit tests, build และตรวจ secret ที่อาจหลุดเข้า bundle |
| `db-ci.yml` | เปิด Supabase local, reset/migrate, lint, pgTAP, ตรวจ drift และ generated types, integration tests |
| `e2e.yml` | ติดตั้ง Chromium แล้วทดสอบผ่าน Playwright กับ Supabase local และ Mailpit เก็บ artifact เมื่อทดสอบไม่ผ่าน 5 วัน |
| `security.yml` | สแกน secret ด้วย Gitleaks, npm audit, รายงาน license จาก SBOM, dependency review ของ PR และ CodeQL ฝั่ง TypeScript/Python ทำงานรายสัปดาห์ด้วย |
| `preview.yml` | Deploy เมื่อ PR ภายใน repo ออกจากสถานะ draft จากสมาชิกที่ได้รับอนุญาตและตั้ง GitHub Environment `preview` ใช้ Vercel project ของ Preview และข้อมูลจำลองจาก Staging Supabase ปิดบัญชีไว้สำหรับ URL ชั่วคราว |
| `deploy-staging.yml` | เมื่อ push ถึง `main` ทดสอบ commit และ migration กับ local ก่อน dry-run แล้ว apply ที่ staging จากนั้น deploy และ smoke test |
| `deploy-production.yml` | เปิดจาก Actions บน `main` พร้อม tag `vX.Y.Z` และยืนยัน migration ของรุ่นนั้น ทดสอบ commit ที่ tag ระบุ รอ Required reviewers แล้วตรวจ dry-run, backup, apply, deploy และ smoke test |
| `dependabot.yml` | ส่งอัปเดต npm, pip และ GitHub Actions รายสัปดาห์แบบ grouped |

การตรวจ generated DB types อยู่ใน Database CI เพราะต้องอ่าน schema ที่ใช้จริง จากเครื่องใช้ `npm run db:types:check` หลังเปิด Supabase local สำหรับ Python ให้อัปเดตและตรวจ `requirements.lock` ด้วยทุกครั้งที่ Dependabot เปลี่ยน manifest

ตรวจ workflow ในเครื่องด้วย `actionlint` และรันเทสต์ release guard แบบออฟไลน์ด้วย `python -m unittest discover -s scripts/ci -p "test_*.py"` เทสต์จำลองผลจาก Vercel CLI และ GitHub API โดยใช้ค่าทดสอบ

## ตั้งค่า GitHub

1. ไปที่ **Settings → Environments** สร้าง `preview`, `staging` และ `production`
2. ใน `production` เปิด **Required reviewers** และปิด **Allow administrators to bypass configured protection rules** เลือก **Selected branches and tags → Branch → main** เปิด **Prevent self-review** เมื่อมีผู้อนุมัติแยกจากผู้สั่ง release
3. ใน `staging` อนุญาต branch `main` ใน `preview` ใช้ Required reviewers เพื่อคุมผู้ที่ส่งโค้ดไปใช้ Vercel token และข้อมูล staging
4. เปิด **Settings → Rules → Rulesets** สร้างกฎ branch `main` ให้ใช้ PR, มีรีวิว, ผ่าน CI/Database CI/Browser E2E/Security, ปิด force push และลบ branch เปิด linear history หากเลือก squash merge สร้าง tag ruleset `v*` ให้เฉพาะผู้ดูแลที่ได้รับอนุญาตสร้างหรือเปลี่ยน tag
5. ใช้ **Settings → Secrets and variables → Actions → Variables** เพิ่มค่าที่ระบุในตาราง Repository Variables ตั้ง Environment Secrets ใน environment เจ้าของงานเท่านั้น
6. สำหรับแจ้งเตือน ใช้ **Settings → Notifications → Actions** แล้วเปิดการแจ้งเมื่อ workflow ที่รับผิดชอบล้มเหลว งาน release พิมพ์ผลชี้ไปหา log และขั้น rollback ใน job summary

**Repository Variables**

| ชื่อ | ค่า |
| --- | --- |
| `CHESS_STAGING_SUPABASE_REF`, `CHESS_PRODUCTION_SUPABASE_REF` | Project ref จาก Supabase Project Settings คนละโปรเจกต์ |
| `CHESS_PREVIEW_VERCEL_PROJECT_ID`, `CHESS_STAGING_VERCEL_PROJECT_ID`, `CHESS_PRODUCTION_VERCEL_PROJECT_ID` | Vercel Settings → General → Project ID คนละโปรเจกต์ |
| `CHESS_PRODUCTION_ORIGIN` | `https://chessmess.vercel.app` หรือโดเมน Production ที่ยืนยันแล้ว |

**Environment Variables**

| ชื่อ | Environment | ค่า |
| --- | --- | --- |
| `APP_ORIGIN` | staging, production | HTTPS origin ตรงกับ Web URL และ OAuth allowlist ของ environment |
| `VERCEL_SCOPE` | preview, staging, production | Team slug ใน Vercel |
| `CHESS_ACCOUNT_ENABLED` | staging, production | ตั้ง `1` เมื่อ SMTP, CAPTCHA และ providers ของ environment พร้อม ระหว่างตั้งค่าใช้ `0` |
| `CHESS_BACKUP_AGE_RECIPIENT` | production | Public key `age1…` สำหรับ logical backup เก็บ private key กับผู้ดูแลข้อมูลนอก GitHub |

**Environment Secrets**

| ชื่อ | Environment | แหล่งที่มา |
| --- | --- | --- |
| `VERCEL_TOKEN` | preview, staging, production | Vercel Account Settings → Tokens สร้างให้สิทธิ์และอายุน้อยที่สุดที่ทำงานได้ ใช้ token แยกกัน |
| `SUPABASE_DB_URL` | staging, production | Supabase **Connect → Session pooler** ค่า PostgreSQL URL พอร์ต 5432 โดย percent-encode รหัสผ่านและใส่ `?sslmode=require` ใช้ค่าเฉพาะ environment |
| `SUPABASE_BACKUP_TOKEN` | production เท่านั้น | Supabase Settings → Access Tokens แบบ fine-grained จำกัด Project และ `backups_read` เลือกใช้เมื่อต้องให้ pipeline ตรวจ managed backup หรือ PITR |

Vercel CLI ใช้ token สำหรับรับคำสั่ง deploy จาก GitHub ซึ่งเป็นคนละทิศกับ Vercel OIDC สำหรับให้ build เข้าถึงบริการภายนอก จึงยังใช้ token ที่จำกัด scope และวันหมดอายุ ขณะ deploy แอปอ่าน `SUPABASE_URL` ตาม target ส่วน `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` และ CAPTCHA runtime configuration อยู่ใน Settings → Environment Variables ของ Vercel เฉพาะโปรเจกต์นั้น OAuth client secrets, SMTP credentials และ CAPTCHA secret อยู่ใน Supabase project settings ของ environment

ตั้ง Vercel Authentication บน Preview ก่อนเปิด workflow staging ใช้ Vercel project แยกเพื่อให้ใช้ Hobby ได้โดยไม่ต้องใช้ custom environments ใช้ฐาน staging สำหรับข้อมูลจำลอง และใช้ external monitoring เฉพาะบัญชี deploy ที่กำหนด ใช้ GitHub Actions เป็นจุด deploy หลัก ปิด Vercel Git auto-deploy เพื่อให้การ deploy เดินผ่าน approval และการตรวจ backup ของ workflow นี้

## ขั้นตอน release

1. ตรวจ staging และยืนยันว่าบัญชีทดสอบสมัคร/ล็อกอินด้วยอีเมล Google และ Facebook ได้จริงตามข้อกำหนดของ provider
2. ใช้ `supabase migration list --remote=<project-ref>` จากเครื่องที่ได้รับอนุญาต ตรวจ Migration history ก่อน release ครั้งแรก ห้อง Production รุ่นแรกอาจสร้างผ่าน SQL Editor หรือ Management API จึงต้องตรวจความตรงของ schema และ migration baseline กับผู้ดูแลก่อนบันทึกประวัติ การซ่อม migration history ต้องแยกเป็นการเปลี่ยน Production ที่ขออนุมัติ
3. สร้าง tag `vX.Y.Z` ที่ commit ที่ผ่าน CI ของ `main` ใช้ **Actions → Production deployment → Run workflow** ใส่ tag และยืนยันให้ apply migration ของรุ่นนั้น แล้ว Required reviewer ตรวจรายการ migration/rollback ก่อนกด approve
4. Workflow ตรวจว่า target staging/production ต่างกันและ tag อยู่ในประวัติ `main` จากนั้น dry-run แล้วตรวจ managed recovery ถ้าไม่พบ fresh backup/PITR ให้ทำ logical backup ของ `public`, `auth`, `chessmess_private` และ migration history ด้วย `pg_dump` ตรวจเปิด catalog และเข้ารหัส age ก่อนอัปโหลด ciphertext เป็น artifact 7 วัน หากไม่มีวิธีกู้คืนที่กำหนด workflow จะหยุดก่อน apply
5. Smoke test ตรวจหน้าแรก API สถานะห้อง และ OAuth redirect พร้อม PKCE ถ้าตั้ง `CHESS_ACCOUNT_ENABLED=1` จากนั้นยืนยัน provider consent และอีเมลด้วยบัญชีทดสอบโดยผู้ดูแล CAPTCHA/OTP จริงต้องยืนยันจากเบราว์เซอร์

## Rollback

- แอป: Vercel → Deployments → เลือก Production deployment เดิมที่เข้ากันได้ → **Instant Rollback** หรือใช้ `vercel rollback <deployment-url>` หลังผู้ดูแลอนุมัติ
- ฐานข้อมูล: เลือก forward-fix migration ก่อน ถ้าต้องกู้ข้อมูลให้ทดสอบในโปรเจกต์กู้คืนแยกซึ่งมีสิทธิ์จำกัด ตรวจ migration history, RLS, auth และยอดข้อมูลกับ backup/PITR ก่อนวางแผน cutover ดาวน์โหลดและถอด backup ที่เข้ารหัสเฉพาะในเครื่องดูแลข้อมูล
- เขียน migration แบบ expand-and-contract ในหลาย release ลดเวลา lock และทดสอบโค้ดรุ่นเก่ากับ schema ใหม่ Deploy rollback ไม่ย้อน migration โดยอัตโนมัติ

[GitHub Environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments) · [Supabase CLI local/hosted](https://supabase.com/docs/guides/local-development/local-and-hosted-projects) · [Supabase Backups](https://supabase.com/docs/guides/platform/backups) · [Vercel CI](https://vercel.com/kb/guide/how-can-i-use-github-actions-with-vercel)
