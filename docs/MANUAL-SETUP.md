# ตั้งค่า ChessX ด้วยตนเอง

ชื่อเกมบนเว็บคือ ChessMess ส่วน GitHub repository ใช้ชื่อ ChessX ตั้งค่า Staging และทดสอบด้วยบัญชีจำลองก่อน เปิด Production หลังอนุมัติรุ่นและรายการ migration แยกต่างหาก เอกสารนี้ใช้สำหรับผู้ดูแล Supabase, Vercel และ GitHub

## 1. กำหนด URL และแยก environment

| ค่า | Local | Staging | Production |
| --- | --- | --- | --- |
| Site URL / `APP_ORIGIN` | `http://127.0.0.1:3210` | `https://<staging-domain>` | `https://chessmess.vercel.app` |
| `SUPABASE_URL` | `http://127.0.0.1:54321` | `https://<staging-ref>.supabase.co` | `https://jgslfemwqqlilkvohhwc.supabase.co` |
| Supabase Redirect URLs สำหรับกลับเข้าเกม | `http://127.0.0.1:3210/api/account/oauth/callback` | `https://<staging-domain>/api/account/oauth/callback` | `https://chessmess.vercel.app/api/account/oauth/callback` |
| OAuth Redirect URI ที่กรอกใน Google หรือ Meta | `http://127.0.0.1:54321/auth/v1/callback` | `https://<staging-ref>.supabase.co/auth/v1/callback` | `https://jgslfemwqqlilkvohhwc.supabase.co/auth/v1/callback` |

- [ ] สร้าง Supabase project แยกสำหรับ Staging ใช้โครงการเดิมที่มี ref `jgslfemwqqlilkvohhwc` สำหรับ Production ใช้ Vercel project แยก 3 ตัวสำหรับ Preview, Staging และ Production
- [ ] เปิด Supabase Dashboard ของ project เป้าหมาย → **Authentication → URL Configuration** กรอก **Site URL** และ **Redirect URLs** จากแถวที่ตรงกันโดยใช้ URL แบบเจาะจง ทดสอบว่า redirect กลับเบราว์เซอร์เดิมเพื่อให้ PKCE ทำงานได้ ใช้ hostname เดียวกันตลอดแต่ละ flow โดยเฉพาะ `127.0.0.1` ใน Local [Supabase Redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls)
- [ ] เปิด Docker Desktop แล้วรัน `npm run db:start` และ `npm run dev:full` ตาม [README](../README.md) ใช้ Studio ที่ `http://127.0.0.1:54323` และ Mailpit ที่ `http://127.0.0.1:54324` แอปอ่านค่าท้องถิ่นจาก `.env.local` ตาม [ตัวอย่าง](../.env.example)
- [ ] สำหรับ OAuth จริงบน Local ให้เปิด `enabled` เฉพาะหัวข้อ `[auth.external.google]` หรือ `[auth.external.facebook]` ใน `supabase/config.toml` ที่ต้องทดสอบ ใส่ค่า `SUPABASE_AUTH_EXTERNAL_GOOGLE_CLIENT_ID` / `SUPABASE_AUTH_EXTERNAL_GOOGLE_SECRET` หรือ `SUPABASE_AUTH_EXTERNAL_FACEBOOK_CLIENT_ID` / `SUPABASE_AUTH_EXTERNAL_FACEBOOK_SECRET` ใน environment ของ Supabase CLI แล้วเริ่ม Local stack ด้วยค่าดังกล่าว เปิดชื่อ provider ที่สอดคล้องใน `AUTH_OAUTH_PROVIDERS` ของแอป ยืนยันว่า provider รับ loopback URI ก่อนเริ่ม flow และใช้ HTTPS Staging หาก Meta ไม่รับ HTTP loopback [Supabase CLI config](https://supabase.com/docs/guides/local-development/cli/config)

## 2. เปิด Email + Password และส่งรหัส OTP

- [ ] ใน **Authentication → Sign In / Providers → Email** เปิด Email และ **Confirm email** เปิด **Secure email change** ให้ยืนยันทั้งที่อยู่เดิมและใหม่ เปิด **Secure password change** ตาม config ของแอป และตรวจความยาวขั้นต่ำตาม Local ที่ 8 ตัวอักษร เปิด leaked password protection ถ้าแพ็กเกจรองรับ [Supabase Password Security](https://supabase.com/docs/guides/auth/password-security)
- [ ] เลือกผู้ส่ง SMTP และยืนยันโดเมนหรือ subdomain สำหรับอีเมลของเกม ตั้ง SPF และ DKIM ด้วยค่าที่ผู้ส่งระบุ ตั้ง DMARC ให้ทีมปฏิบัติการรับรายงาน แล้วปรับ policy ตามผลตรวจ ปิด link tracking สำหรับอีเมล Auth ถ้าผู้ส่งเปิดไว้ [Supabase Custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp)
- [ ] เปิด **Authentication → SMTP Settings → Enable Custom SMTP** ในแต่ละ project สำหรับ Production ใช้ [SMTP Settings](https://supabase.com/dashboard/project/jgslfemwqqlilkvohhwc/auth/smtp) กรอก **Sender email**, **Sender name** เช่น ChessMess, **Host**, **Port**, **Username** และ **Password** ตามผู้ส่ง ใช้ TLS ตามข้อกำหนดผู้ส่ง จำกัดสิทธิ์ credential ให้ส่งอีเมลได้ และเก็บค่าไว้ใน Dashboard บัญชีทดสอบที่ไม่อยู่ในทีม Supabase ต้องใช้ Custom SMTP เพื่อรับเมลจริง โปรเจกต์ใหม่บนแผน Free ต้องเปิด Custom SMTP ก่อนแก้ template เริ่มต้น [ข้อจำกัด SMTP](https://supabase.com/docs/guides/auth/auth-smtp) · [ข้อกำหนด Free tier](https://supabase.com/changelog/46599-changes-to-email-template-customisation-on-free-tier)
- [ ] เปิด **Authentication → Email Templates** ของ project สำหรับ Production ใช้ [Email Templates](https://supabase.com/dashboard/project/jgslfemwqqlilkvohhwc/auth/templates) ใส่ Subject และคัดลอก HTML จากตารางด้านล่าง แอปให้ผู้เล่นกรอกรหัส OTP จาก `{{ .Token }}` รักษา placeholder นี้ในทุก template ตั้ง OTP 6 หลักและตรวจว่าเวลาหมดอายุและ rate limit ที่ใช้อยู่เหมาะกับอีเมลยืนยันทั้งหมด [Supabase Email Templates](https://supabase.com/docs/guides/auth/auth-email-templates) · [Supabase Rate Limits](https://supabase.com/docs/guides/auth/rate-limits)
- [ ] เปิดอีเมลแจ้งเตือนเมื่อเปลี่ยนรหัสผ่านหรืออีเมล และเมื่อเพิ่มหรือถอด MFA ปรับข้อความแจ้งเตือนเป็นภาษาไทย ทดสอบจากบัญชีทดลองที่อยู่นอกทีม Supabase ว่ารับ OTP ได้จริงและใช้รหัสได้ จดเวลาส่งและตรวจกล่อง Spam เมื่อจำเป็น

| Template | Subject | HTML |
| --- | --- | --- |
| Confirm signup | รหัสยืนยันบัญชี ChessMess | [confirmation.html](../supabase/templates/confirmation.html) |
| Reset password | รหัสตั้งรหัสผ่านใหม่ ChessMess | [recovery.html](../supabase/templates/recovery.html) |
| Change email address | รหัสยืนยันการเปลี่ยนอีเมล ChessMess | [email-change.html](../supabase/templates/email-change.html) |

## 3. Google OAuth

1. [ ] ใน Google Cloud Console เลือก project ของ environment เปิด **Google Auth Platform → Branding** กรอกชื่อ ChessMess, Support email, Developer contact และ URL หน้าแรก/นโยบายความเป็นส่วนตัว/ข้อกำหนดเมื่อเผยแพร่ ใช้โดเมนที่ควบคุมและยืนยันตามที่ Console ขอ
2. [ ] เปิด **Audience** เลือก **External** สำหรับผู้เล่นทั่วไป ในสถานะ **Testing** เพิ่ม tester ที่จะใช้จริงใน Staging เปิด **Data Access** ตรวจ scopes `openid`, `email`, `profile` และเตรียมการยืนยันเมื่อ Google กำหนด
3. [ ] เปิด **Clients → Create Client → Web application** ใช้ชื่อที่บอก environment ใน **Authorized redirect URIs** ใส่ค่า OAuth Redirect URI จากตาราง หากกรอก **Authorized JavaScript origins** ให้ใช้ origin เกมแบบไม่มี path หรือ slash ปิดท้าย ตัวอย่าง Production คือ `https://chessmess.vercel.app` สำหรับ Local ใช้ `http://127.0.0.1:3210`
4. [ ] เปิด Supabase **Authentication → Sign In / Providers → Google** เปิด provider แล้ววาง Client ID และ Client Secret ของ environment นั้นในช่องที่กำหนด ตรวจว่า Callback URL ที่ Supabase แสดงตรงกับค่าใน Google
5. [ ] ทดสอบการลงชื่อเข้าใช้ การยกเลิกหน้า consent การเชื่อม provider ในหน้าบัญชี และบัญชีเดิมที่มีอีเมลยืนยันแล้วก่อนเปลี่ยน Google app เป็น **In production** เปิด `google` ใน `AUTH_OAUTH_PROVIDERS` ของ Vercel project เมื่อทดสอบครบ [Google OAuth Web Server](https://developers.google.com/identity/protocols/oauth2/web-server) · [Supabase Google OAuth](https://supabase.com/docs/guides/auth/social-sign-in/auth-google)

## 4. Facebook OAuth

1. [ ] ใน Meta for Developers เปิด **My Apps → Create App** เลือก use case ที่มี Facebook Login สำหรับลงชื่อเข้าเว็บ และเพิ่ม **Facebook Login** หาก Wizard ยังไม่สร้างให้ ใช้ App แยกตาม environment
2. [ ] เปิด **App settings → Basic** กรอก App Domains และ Website URL ของ environment นั้น เผยแพร่ Privacy Policy และ Terms ฉบับที่เจ้าของเกมตรวจแล้ว กรอก **Data Deletion Instructions URL** เป็นหน้า HTTPS ที่อธิบายวิธีเข้าหน้าบัญชีเกมแล้วลบบัญชี รวมวิธีติดต่อหากเข้าไม่ได้ กรณีเลือก **Data Deletion Callback URL** ต้องมี endpoint สำหรับตรวจ signed request และตอบสถานะการลบตามข้อกำหนดของ Meta ก่อนใช้
3. [ ] เปิด **Facebook Login → Settings** เปิด **Client OAuth Login** และ **Web OAuth Login** ใช้ strict redirect matching ตามหน้าตั้งค่า ใส่ **Valid OAuth Redirect URIs** ด้วยค่า Supabase จากตาราง เปิดสิทธิ์ขั้นต่ำ `email` และ `public_profile`
4. [ ] เปิด Supabase **Authentication → Sign In / Providers → Facebook** เปิด provider ใส่ **App ID** และ **App Secret** จาก Meta project ที่ตรงกัน ตรวจ Callback URL ที่แสดงใน Supabase อีกครั้ง
5. [ ] เพิ่มผู้ทดสอบใน **App roles** ทดสอบ Staging ด้วย tester ทดสอบบัญชีที่มีและไม่มีอีเมลให้แอป และตรวจ flow ยกเลิก consent ก่อนสลับ **Live** ทำ App Review/Business Verification หาก Meta ระบุสำหรับแอปหรือสิทธิ์ที่ใช้ เปิด `facebook` ใน `AUTH_OAUTH_PROVIDERS` เมื่อทดสอบครบ [Supabase Facebook OAuth](https://supabase.com/docs/guides/auth/social-sign-in/auth-facebook) · [Meta Data Deletion](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback/)

Google และ Facebook ใช้ allowlist `AUTH_OAUTH_PROVIDERS=google,facebook` เมื่อเปิดทั้งคู่ ตั้ง **Manual Linking** ใน Supabase สำหรับการผูก provider จากหน้าบัญชีหลังล็อกอิน ใช้ชื่อและรูปจาก provider เป็นค่าเสนอให้ผู้เล่นตรวจ ปุ่มเชื่อม provider ที่สามต้องเพิ่มใน server allowlist และทดสอบ callback, identity linking และการปิด provider ก่อนเปิดใช้ [Supabase Identity Linking](https://supabase.com/docs/guides/auth/auth-identity-linking)

## 5. Turnstile และ TOTP

- [ ] ใน Cloudflare Dashboard → **Turnstile → Add widget** สร้าง widget ต่อ environment อนุญาต hostname ของเกมนั้น เช่น `chessmess.vercel.app` ใช้ Site Key ใน `AUTH_CAPTCHA_SITE_KEY` ของ Vercel และเก็บ Secret Key ไว้ที่ Supabase **Authentication → Attack Protection → CAPTCHA Protection → Cloudflare Turnstile** เปิดทดสอบใน Staging ก่อน เปิด CAPTCHA widget ให้สมัคร เข้าระบบ และขอรหัสตั้งรหัสผ่านใหม่ได้ครบ พร้อมตรวจ error เมื่อ challenge หมดอายุ [Cloudflare Turnstile](https://developers.cloudflare.com/turnstile/get-started/) · [Supabase CAPTCHA](https://supabase.com/docs/guides/auth/auth-captcha)
- [ ] เปิด TOTP enrollment และ verification ใน **Authentication → Multi-Factor Authentication** หากมีตัวเลือกใน project ยืนยันได้จากหน้าบัญชีโดยสแกน QR ด้วยแอป Authenticator แล้วใส่รหัส ตั้งค่า MFA แบบเดียวกับ [Local config](../supabase/config.toml) และใช้ Authenticator อีกเครื่องสำรองที่ผู้ใช้ควบคุมได้ก่อนทดสอบการถอดปัจจัย กรณีทำอุปกรณ์ทั้งหมดหายให้เปิดเคสช่วยเหลือและยืนยันตัวตนตามขั้นตอนใน [SECURITY.md](SECURITY.md) [Supabase TOTP MFA](https://supabase.com/docs/guides/auth/auth-mfa/totp)
- [ ] ใช้บัญชีทดลองเปิด MFA ออกจากระบบและเข้าใหม่ กรอกรหัส TOTP และตรวจว่าการแก้ข้อมูลละเอียดอ่อนรอการยืนยัน MFA เปิด MFA แยกสำหรับบัญชีผู้ดูแล GitHub, Vercel, Supabase, Google และ Meta

## 6. Vercel

1. [ ] สร้าง project สำหรับ Preview และ Staging เลือกหรือยืนยัน project สำหรับ Production ที่มี `chessmess.vercel.app` ตรวจ **Settings → Domains** ให้แต่ละ project ใช้โดเมนของตัวเอง เปิด HTTPS ตรวจ path callback ตามตาราง และคัดลอก **Project ID** จาก **Settings → General**
2. [ ] ใน **Settings → Environment Variables** ของแต่ละ project ตั้ง `SUPABASE_PUBLISHABLE_KEY` และ `SUPABASE_SECRET_KEY` จาก **Supabase Dashboard → Project Settings → API Keys** ของ environment นั้น ใช้ `AUTH_OAUTH_PROVIDERS` และ `AUTH_CAPTCHA_SITE_KEY` ตาม provider และ CAPTCHA ที่เปิดจริง เก็บ `SUPABASE_SECRET_KEY` เป็น server-side เท่านั้น ตั้งค่าไว้ในขอบเขต Production ของ Vercel project ที่ใช้ `--prod` สำหรับ Staging/Production ค่า `SUPABASE_URL`, `APP_ORIGIN` และสวิตช์ `CHESS_ACCOUNT_ENABLED` มาจาก workflow ตอน deploy
3. [ ] ตั้ง Vercel Authentication ใน **Settings → Deployment Protection** ของ Preview project ให้ครอบคลุม Preview URLs ใช้ Staging Supabase และข้อมูลจำลองเท่านั้น Preview ใช้ `CHESS_ACCOUNT_ENABLED=0`
4. [ ] ปิด Git auto-deploy ใน Vercel project ที่ย้ายมาใช้ GitHub Actions แล้ว ตรวจว่า Git push ธรรมดาไม่สามารถข้าม GitHub Environment gate เปิด Vercel logs/monitoring และตั้งคนรับผิดชอบสำหรับ 5xx, spike และ deploy failures [Vercel Environment Variables](https://vercel.com/docs/environment-variables) · [Vercel Authentication](https://vercel.com/docs/deployment-protection/methods-to-protect-deployments/vercel-authentication)

Vercel ใช้ entrypoint `app.py` ซึ่งกำหนด `CHESS_ENV=production` และ `CHESS_ROOM_STORE=supabase` ให้อัตโนมัติ ถ้าเปิด FastAPI โดยตรงบนโฮสต์อื่น ให้ตั้งทั้งสองค่าก่อนรัน

## 7. GitHub Actions, Secrets และ approval

1. [ ] เปิด [ChessX](https://github.com/KNIGHTKRUBPOM/ChessX) → **Settings → Actions → General → Workflow permissions** ตั้งค่าเริ่มต้น read-only
2. [ ] เปิด **Settings → Environments → New environment** สร้าง `preview`, `staging`, `production` แยกกัน ให้ Staging และ Production อนุญาต deploy จาก branch `main` ตาม workflow ใน Production เปิด **Required reviewers**, **Prevent self-review** และห้ามผู้ดูแล bypass กฎ ให้ Preview มีผู้ตรวจอนุมัติก่อนรับ Vercel token ตรวจว่าแพ็กเกจ repo รองรับ protection rules ที่จำเป็นก่อนอนุญาต Production [GitHub Environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
3. [ ] เปิด **Settings → Secrets and variables → Actions → Variables → New repository variable** สร้าง `CHESS_STAGING_SUPABASE_REF`, `CHESS_PRODUCTION_SUPABASE_REF`, `CHESS_PREVIEW_VERCEL_PROJECT_ID`, `CHESS_STAGING_VERCEL_PROJECT_ID`, `CHESS_PRODUCTION_VERCEL_PROJECT_ID`, `CHESS_PRODUCTION_ORIGIN` ตามตาราง environment
4. [ ] ในแต่ละ environment เพิ่ม Variable `VERCEL_SCOPE` เป็น Team slug และ Secret `VERCEL_TOKEN` จาก **Vercel Account Settings → Tokens** แยก token ต่อ environment ตั้งอายุและสิทธิ์ขั้นต่ำ ใน Staging/Production เพิ่ม Variable `APP_ORIGIN`, `CHESS_ACCOUNT_ENABLED` และ Secret `SUPABASE_DB_URL` จาก **Supabase → Connect → Session pooler** พอร์ต 5432 พร้อม `sslmode=require` ใช้ URL encoding กับรหัสผ่านเฉพาะส่วน credential Production ใส่ `SUPABASE_BACKUP_TOKEN` เมื่อใช้ managed backup verification หรือ Variable `CHESS_BACKUP_AGE_RECIPIENT` เมื่อใช้ encrypted logical backup ตาม [CICD.md](CICD.md)
5. [ ] เปิด **Settings → Rules → Rulesets → New branch ruleset** ตั้ง target `main` เปิด required PR reviews และ status checks เลือกชื่อ job ที่แสดงจาก CI, Database CI, Browser E2E และ Security หลัง PR ทดลองรันสำเร็จ บล็อก force push และ branch deletion เปิด linear history ตาม merge strategy สร้าง tag ruleset `v*` จำกัดการสร้าง แก้ และลบ tag สำหรับผู้รับผิดชอบ release [GitHub Rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
6. [ ] ให้ Staging deploy จาก `main` หลัง merge แล้วทดสอบ signup → OTP → login → เกม → logout, reset password, เปลี่ยนอีเมล, MFA และ Google/Facebook ด้วยบัญชีทดลอง ให้ผู้ดูแลตรวจ migration history Production ก่อน release แรก เพราะ schema ห้อง legacy ถูกเพิ่มผ่าน SQL โดยตรง ให้ขออนุมัติแยกก่อนซ่อม migration history, apply migration, restore/reset DB หรือหมุน secret
7. [ ] เมื่อตรวจ Staging ผ่านแล้วจึงนัดผู้อนุมัติ Production สร้าง tag `vX.Y.Z` บน commit ที่ผ่านการตรวจ เปิด **Actions → Production deployment → Run workflow** บน main กรอก tag ยืนยันรายการ migration และรอ reviewer แยกตรวจ backup กับแผน rollback ทดสอบหลัง deploy ตาม [CICD.md](CICD.md)

## เมื่อย้ายโดเมน

- [ ] ตั้งโดเมนใหม่ใน Vercel และตรวจ HTTPS ก่อนสลับ ใช้ `APP_ORIGIN` และ `CHESS_PRODUCTION_ORIGIN` ที่ตรงกัน ตั้ง Supabase Site URL/Redirect URLs, Google Authorized JavaScript origins, Meta App Domains/Website URL, Turnstile hostname และลิงก์เอกสารสาธารณะตามโดเมนใหม่
- [ ] หากย้าย Supabase project ด้วย ให้ปรับ provider callback `/auth/v1/callback`, API keys, `SUPABASE_DB_URL` และ Project ref ต่อ environment ตรวจ CORS/allowlist และทดสอบ OTP, OAuth และ TOTP ด้วยผู้ใช้ทดลอง ลบ URL เดิมหลังยืนยันว่าการเข้าสู่ระบบบนโดเมนใหม่ทำงานครบ
