# ChessMess · Test cases และผลรัน

ก่อนรันใช้ release dist ใน checkout นี้ API รันบน localhost พอร์ตแยก โปรไฟล์และชื่อเล่นใช้เฉพาะ QA Suite ที่ใช้ข้อมูลห้องจะสร้าง state เองใน RAM ตัวเลข/JSON ของผล API คือ assertions ที่ runner บันทึก ผลที่คาดสำหรับ smoke และ accessibility ระบุในตาราง [วิธีรัน](README.md)

## E2E Smoke

[หลักฐาน JSON](../evidence/qa-2026-11-15/smoke.json)

| ID | เงื่อนไขก่อนทดสอบ | ขั้นตอน | ผลคาดหวัง | ผลจริง | สถานะ |
|---|---|---|---|---|---|
| SM-01 | โปรเซสใหม่ | เปิดหน้าแรกใหม่และเรียก health ทั้งคู่ | HTTP 200, หัวข้อแสดง, ไม่มี page error หรือ request fail | หน้าแรกและ health 200 | PASS |
| SM-02 | เมนูหลักเปิดแล้ว | เปิดธีม ปิด แล้วเปิด Chess และกติกา ก่อนกลับเมนู | ธีม กระดาน กติกาและเมนูเปิดได้ | ธีม, กระดาน, กติกา, กลับเมนู | PASS |
| SM-03 | สองแท็บโปรไฟล์ทดสอบ | สร้างห้อง Chess เข้าจากแท็บที่สอง แล้วกลับเมนู | เริ่มตั้งสกิลได้ และกลับเมนูได้ | สร้าง/เข้าห้อง/กลับเมนูด้วยชื่อทดสอบ | PASS |

## E2E Regression

[หลักฐาน JSON](../evidence/qa-2026-11-15/regression.json)

| ID | เงื่อนไขก่อนทดสอบ | ขั้นตอน | ผลคาดหวัง | ผลจริง | สถานะ |
|---|---|---|---|---|---|
| UI-home-title | หน้าแรก | อ่าน document title | มีชื่อเกม | true | PASS |
| PERF-menu-no-phaser | fresh browser profile | อ่าน Resource Timing ในเมนู | ไม่มี Phaser chunk ที่เมนู | true | PASS |
| UI-width-320 | หน้าแรก Chrome | ปรับ viewport 320 px แล้ววัด viewport และขอบเนื้อหา | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | true | PASS |
| UI-width-375 | หน้าแรก Chrome | ปรับ viewport 375 px แล้ววัด viewport และขอบเนื้อหา | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | true | PASS |
| UI-width-768 | หน้าแรก Chrome | ปรับ viewport 768 px แล้ววัด viewport และขอบเนื้อหา | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | true | PASS |
| UI-width-1024 | หน้าแรก Chrome | ปรับ viewport 1024 px แล้ววัด viewport และขอบเนื้อหา | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | true | PASS |
| UI-width-1440 | หน้าแรก Chrome | ปรับ viewport 1440 px แล้ววัด viewport และขอบเนื้อหา | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | true | PASS |
| UI-themes | เปิด theme dialog | นับตัวเลือกธีม | มี 6 ตัวเลือก | 6 | PASS |
| F-theme-restore | เลือก sakura | ปิด dialog และ reload | sakura กลับมา | sakura | PASS |
| PERF-phaser-on-board | เปิดจากเมนูในโหมด Chess | กด Play และรอ canvas | พบ Phaser chunk | true | PASS |
| F-keyboard-placement | กระดานตอนตั้งสกิล | โฟกัสช่อง a2 แล้วกด Enter | จำนวนสกิลที่ลงเป็น 1/4 | true | PASS |
| A11Y-clear-focus | ตั้งสกิลแล้วหนึ่งช่อง | กด Enter ที่ปุ่มล้าง | focus ยังในพื้นที่เกม | true | PASS |
| F-resume-visible | เซฟ Local Chess ถูกสร้าง | reload | ปุ่มเล่นต่อแสดง | true | PASS |
| F-resume-setup | ปุ่มเล่นต่อแสดง | กดเล่นต่อ | กลับเข้าหน้าตั้งสกิล 0/4 ตามค่าที่ล้าง | true | PASS |
| UI-console | baseline play journey | อ่าน pageerror และ console error | ไม่มี error ใน journey นี้ | [] | PASS |
| F-name-unicode-parity | เปิด lobby | กรอก emoji 13 ตัว | ค่า browser ยังมี 13 ตัว | 13 | PASS |
| F-name-unicode-api | เปิด instance ทดสอบ | สร้างห้องด้วย emoji 13 ตัว | HTTP 200 | 200 | PASS |
| F-paused-room-recovery | ห้องเดิมเต็มและพักไว้ | เปิด invite จากหน้า game เดิม | กลับได้รหัสเดิม | รหัสห้องสังเคราะห์ตรงกัน | PASS |
| F-paused-room-original-seat | กลับห้องที่พักไว้ | อ่านที่นั่งภายหลัง resume | ยังเป็นที่นั่งเจ้าของเดิม | true | PASS |
| A11Y-zoom-200 | เมนูทดสอบ | ใช้ CSS zoom จำลอง 200% | เมนูที่วัดยังอยู่ในขอบเขต | true | PASS |
| REG-01 | สองแท็บแยก session และห้อง Hybrid | เข้าห้อง ตั้งสกิล ตรวจการเห็นสกิลทั้งสองฝั่ง เดินเข้ากล่อง XO ลงหนึ่งตาแล้ว reload ดำ เล่นต่อจนดำชนะ | สกิลตรงข้ามถูกซ่อน ที่นั่งกับ XO คงอยู่ ดำสวนกิน | สองแท็บแยกที่นั่ง ตรวจสกิลลับ รีโหลดกลาง XO และผลสวนกิน | PASS |

## API / Integration

[หลักฐาน JSON](../evidence/qa-2026-11-15/integration.json)

| ID | เงื่อนไขก่อนทดสอบ | ขั้นตอน | ผลคาดหวัง | ผลจริง | สถานะ |
|---|---|---|---|---|---|
| F-openapi-schema | dev fixture | GET OpenAPI | 200 | 200 | PASS |
| F-start-chess | public game API | POST start โหมด chess และนับหมากพร้อมตรวจตาเริ่ม | [200,"w",32] | [200,"w",32] | PASS |
| F-start-draughts | public game API | POST start โหมด draughts และนับหมากพร้อมตรวจตาเริ่ม | [200,"b",16] | [200,"b",16] | PASS |
| F-start-hybrid | public game API | POST start โหมด hybrid และนับหมากพร้อมตรวจตาเริ่ม | [200,"w",28] | [200,"w",28] | PASS |
| F-mode-invalid | public game API | POST start ด้วย mode ไม่รองรับ | 422 | 422 | PASS |
| F-name-5 | ห้องจำลอง | POST create room ด้วยชื่อว่าง | 422 | 422 | PASS |
| F-name-6 | ห้องจำลอง | POST create room ด้วยชื่อมีแต่ช่องว่าง | 422 | 422 | PASS |
| F-name-7 | ห้องจำลอง | POST create room ด้วยไทย 24 ตัว | 200 | 200 | PASS |
| F-name-8 | ห้องจำลอง | POST create room ด้วยไทย 25 ตัว | 422 | 422 | PASS |
| F-name-9 | ห้องจำลอง | POST create room ด้วยไทยกับสัญลักษณ์ | 200 | 200 | PASS |
| F-name-10 | ห้องจำลอง | POST create room ด้วยตัวอักษรพร้อม & และวงเล็บแหลม | 200 | 200 | PASS |
| F-room-full | สองที่นั่งเต็ม | เรียก join ตาม flow ปกติจากผู้เล่นที่สาม | 409 | 409 | PASS |
| D-room-auth | มีห้องทดสอบ | GET ห้องโดยไม่มี credential | 401 | 401 | PASS |
| F-room-joined | ห้องใหม่ | เข้าด้วยชื่อดำและอ่านสอง snapshots | ["setup","w","b"] | ["setup","w","b"] | PASS |
| F-setup-incomplete | ห้องพร้อมตั้งสกิล | ยืนยันโดยเลือกเพียง lock | 422 | 422 | PASS |
| F-setup-original | ห้องพร้อมตั้งสกิล | ส่ง placements ดำครบด้วย revision ปัจจุบัน | 200 | 200 | PASS |
| F-setup-both | หลังดำพร้อม | ส่ง placements ขาวครบ | 200 | 200 | PASS |
| D-private-skills | สอง mock seats ตั้งสกิลครบ | อ่าน snapshot แยกแต่ละที่นั่ง | true | true | PASS |
| F-own-skills | ดำตั้ง push และ duel บนตัวเดียว | อ่าน field skills ของหมากดำด้วยสิทธิ์ดำ | ["push","duel"] | ["push","duel"] | PASS |
| D-turn-options | ถึงตาขาว | อ่าน options ด้วยสิทธิ์ดำ | null | null | PASS |
| D-wrong-turn | ถึงตาขาว | ส่ง move ของดำตามปกติ | 409 | 409 | PASS |
| F-square--1 | ห้องพร้อมเดิน | ส่ง move จาก 49 ไป index -1 | 422 | 422 | PASS |
| F-square-64 | ห้องพร้อมเดิน | ส่ง move จาก 49 ไป index 64 | 422 | 422 | PASS |
| F-square-1.5 | ห้องพร้อมเดิน | ส่ง move จาก 49 ไป index 1.5 | 422 | 422 | PASS |
| F-square-1000000000 | ห้องพร้อมเดิน | ส่ง move จาก 49 ไป index 1000000000 | 422 | 422 | PASS |
| F-illegal | ถึงตาขาว | ขอเดินขาวจาก 49 ไป 17 ที่เดินไม่ได้ | 422 | 422 | PASS |
| F-duplicate-move | มี revision ตาเดิน | ส่งตา 49→33 พร้อมกันสองครั้ง | [200,409] | [200,409] | PASS |
| F-checker-step | ถึงตาดำ | เดินหมากฮอส 17→24 | 200 | 200 | PASS |
| F-XO-start | ดำเดินไป 24 | ขาวกินจาก 33 ไป 24 ที่มี duel | [200,"duel"] | [200,"duel"] | PASS |
| F-XO-cell-0 | ห้องเข้าสู่ XO และถึงตาในลำดับ fixture | ลงช่อง 0 ด้วยที่นั่งที่ถึงตา | 200 | 200 | PASS |
| F-XO-cell-3 | ห้องเข้าสู่ XO และถึงตาในลำดับ fixture | ลงช่อง 3 ด้วยที่นั่งที่ถึงตา | 200 | 200 | PASS |
| F-XO-cell-1 | ห้องเข้าสู่ XO และถึงตาในลำดับ fixture | ลงช่อง 1 ด้วยที่นั่งที่ถึงตา | 200 | 200 | PASS |
| F-XO-cell-4 | ห้องเข้าสู่ XO และถึงตาในลำดับ fixture | ลงช่อง 4 ด้วยที่นั่งที่ถึงตา | 200 | 200 | PASS |
| F-XO-cell-2 | ห้องเข้าสู่ XO และถึงตาในลำดับ fixture | ลงช่อง 2 ด้วยที่นั่งที่ถึงตา | 200 | 200 | PASS |
| F-XO-reverse | ดำชนะ XO | ตรวจผลและสองช่องเดิมของคู่ดวล | ["b",null,"b"] | ["b",null,"b"] | PASS |
| F-room-resume | ห้องมีผล XO | อ่านสถานะโดย seat token ดำเดิม | b | b | PASS |
| D-no-store | อ่านห้องมีสิทธิ์ | ตรวจ Cache-Control | no-store | no-store | PASS |
| D-web-/missing-qa-page | dev fixture | GET /missing-qa-page หนึ่งครั้งตาม path ปกติ | 404 | 404 | PASS |
| D-web-/.env | dev fixture | GET /.env หนึ่งครั้งตาม path ปกติ | 404 | 404 | PASS |
| D-web-/.git/config | dev fixture | GET /.git/config หนึ่งครั้งตาม path ปกติ | 404 | 404 | PASS |
| D-web-/backend/app.py | dev fixture | GET /backend/app.py หนึ่งครั้งตาม path ปกติ | 404 | 404 | PASS |
| D-web-/qa-report/REPORT.md | dev fixture | GET /qa-report/REPORT.md หนึ่งครั้งตาม path ปกติ | 404 | 404 | PASS |
| D-method | health พร้อม | ส่ง TRACE หนึ่งครั้ง | 405 | 405 | PASS |
| D-browser-csp | หน้าแรกพร้อม | อ่าน CSP และค่า frame-ancestors | true | true | PASS |
| D-browser-nosniff | หน้าแรกพร้อม | อ่าน X-Content-Type-Options | nosniff | nosniff | PASS |
| INT-required-options | public game API | POST options โดยส่งเฉพาะ mode | 422 | 422 | PASS |
| INT-required-setup | public game API | POST setup โดยส่งเฉพาะ mode | 422 | 422 | PASS |
| INT-required-move | public game API | POST move โดยส่งเฉพาะ mode | 422 | 422 | PASS |
| INT-required-duel | public game API | POST duel โดยส่งเฉพาะ mode | 422 | 422 | PASS |
| INT-required-duel/finish | public game API | POST duel/finish โดยส่งเฉพาะ mode | 422 | 422 | PASS |
| INT-wrong-type | public start | POST mode เป็น boolean | 422 | 422 | PASS |
| INT-empty | public start | POST body ว่าง Content-Type JSON | 422 | 422 | PASS |
| INT-json | public start | POST JSON เปิดปีกกาไม่ปิด | 422 | 422 | PASS |
| INT-method | public start | เรียก PUT | 405 | 405 | PASS |
| INT-options | มี Hybrid state ใหม่ | ขอ options ด้วย state จาก start | 200 | 200 | PASS |
| INT-setup-w | Hybrid fixture | POST setup ด้วย placements ของฝ่าย w | 200 | 200 | PASS |
| INT-setup-b | Hybrid fixture | POST setup ด้วย placements ของฝ่าย b | 200 | 200 | PASS |
| INT-main-49 | Hybrid fixture ตั้งสกิลแล้ว | เดินจาก 49 ตามลำดับใน fixture เข้าสู่ XO | 200 | 200 | PASS |
| INT-main-17 | Hybrid fixture ตั้งสกิลแล้ว | เดินจาก 17 ตามลำดับใน fixture เข้าสู่ XO | 200 | 200 | PASS |
| INT-main-33 | Hybrid fixture ตั้งสกิลแล้ว | เดินจาก 33 ตามลำดับใน fixture เข้าสู่ XO | 200 | 200 | PASS |
| INT-duel-unfinished | มี Hybrid duel เริ่มแล้ว | เรียก finish ก่อน XO จบ | 409 | 409 | PASS |
| INT-duel-outcome-b | XO fixture ที่เริ่มจากการกิน | เล่นจนผล XO เป็น b แล้วเรียก finish | [200,"b"] | [200,"b"] | PASS |
| INT-duel-outcome-w | XO fixture ที่เริ่มจากการกิน | เล่นจนผล XO เป็น w แล้วเรียก finish | [200,"w"] | [200,"w"] | PASS |
| INT-duel-outcome-None | XO fixture ที่เริ่มจากการกิน | เล่นจนผล XO เป็น None แล้วเรียก finish | [200,null] | [200,null] | PASS |
| SEC-conditional-auth | ห้อง Chess ใหม่ | GET มี seat token, GET ซ้ำมี ETag, GET ETag ไม่มี seat token | [200,304,0,"no-store",401] | [200,304,0,"no-store",401] | PASS |
| SEC-cookie-on-room | GET ห้องมีสิทธิ์ | ตรวจ Set-Cookie | false | false | PASS |
| SEC-strict-fields | public create room | POST ชื่อปกติพร้อม field extra | 422 | 422 | PASS |

## Unit

ค่าก่อนทดสอบและแต่ละ assertion อยู่ในฟังก์ชัน Arrange–Act–Assert ที่ระบุด้านล่าง การรันทั้ง 3 รอบใช้การ import โมดูลใหม่ [ผลทั้งสามรอบ](../evidence/qa-2026-11-15/unit-results.json) · [โค้ดเทสต์](unit/test_business_rules.py)

| ID | เงื่อนไขก่อนทดสอบ | ขั้นตอน | ผลคาดหวัง | ผลจริง |
|---|---|---|---|---|
| U01 | กระดาน Chess เริ่มต้น | `test_u01_opening_and_piece_lookup` | หมากและตัวเลือกเปิดเกมตรงกับกติกา | PASS, PASS, PASS |
| U02 | กระดาน Chess จัด en passant | `test_u02_en_passant_capture_and_expiry` | กิน en passant ได้ตามเงื่อนไขและสิทธิ์หมด | PASS, PASS, PASS |
| U03 | กระดาน Chess เปิดทาง castling | `test_u03_both_castles_move_rook` | king และ rook ย้ายถูกทั้งสองฝั่ง | PASS, PASS, PASS |
| U04 | เงื่อนไขเรือเคยเดิน/ขวาง/ถูกคุกคาม | `test_u04_castle_fails_moved_rook_block_or_check` | ห้าม castle เมื่อเงื่อนไขใดผิด | PASS, PASS, PASS |
| U05 | pawn พร้อมเลื่อนขั้น | `test_u05_promotion_offers_four_and_preserves_identity_and_skill` | สี่ตัวเลือก รักษา id และ skill | PASS, PASS, PASS |
| U06 | กระดานมีตัวถูก pin | `test_u06_detects_attacks_and_pinned_piece` | ตรวจช่องโจมตีและจำกัดหมาก pinned | PASS, PASS, PASS |
| U07 | เป้าหมายมีสกิลและหมากฝั่งเดียวกัน | `test_u07_opposing_skill_and_friendly_capture` | แสดงผลสกิลเป้าหมายและกินหมากฝ่ายเดียวกันได้ตามคำสั่ง | PASS, PASS, PASS |
| U08 | มีกำลังสำรองสำหรับคืนหมาก | `test_u08_revival_generates_new_id_and_uses_reserve` | คืนหมาก id ใหม่และหัก reserve | PASS, PASS, PASS |
| U09 | มีเบี้ยติด lock และมีทางพ้น check | `test_u09_push_locked_pawn_and_sole_check_escape` | ผ่อน lock เมื่อมีทางพ้น check ทางเดียว | PASS, PASS, PASS |
| U10 | fixture Chess พร้อมเดิน | `test_u10_low_level_errors_do_not_change_board` | error เกิดและ state ไม่เปลี่ยน | PASS, PASS, PASS |
| U11 | กระดานหมากฮอสเริ่มต้น | `test_u11_opening_black_has_seven_moves_on_dark_squares` | ดำเริ่มได้เจ็ดทางบนช่องสีเข้ม | PASS, PASS, PASS |
| U12 | กระดานกินต่อเนื่อง | `test_u12_forced_chain_defers_reveal_until_final_capture` | ซ่อนสกิลไว้จนจบการกินต่อ | PASS, PASS, PASS |
| U13 | เบี้ยใกล้ขอบและ king มีเป้าหมาย | `test_u13_crowning_and_flying_jump_lands_just_beyond_target` | ขึ้นฮอสและลงช่องหลังตัวที่กินตามกติกา | PASS, PASS, PASS |
| U14 | คู่เป้าหมาย locked/unlocked | `test_u14_lock_prefers_unlocked_capture_and_uses_locked_when_only_choice` | เลือกกินตัวไม่ถูก lock ก่อน | PASS, PASS, PASS |
| U15 | คิวคำสั่งมี revive และ friendly | `test_u15_queue_skips_revival_and_uses_friendly_jump` | ข้าม revive ที่ใช้ไม่ได้แล้วใช้ friendly jump | PASS, PASS, PASS |
| U16 | คิว revive พร้อมจุดเกิด | `test_u16_revival_requires_dark_home_square` | ต้องคืนบนช่องบ้านสีเข้ม | PASS, PASS, PASS |
| U17 | คิว push ที่มีหรือไม่มีเบี้ยที่เดินได้ | `test_u17_push_excludes_king_and_skips_when_no_pawn_moves` | ข้าม king และข้ามคำสั่งเมื่อเดินไม่ได้ | PASS, PASS, PASS |
| U18 | หมากฮอสอยู่ในระยะ king | `test_u18_hybrid_checker_cannot_directly_capture_king` | หมากฮอสกิน king โดยตรงไม่ได้ | PASS, PASS, PASS |
| U19 | กระดานหมากฮอสทดสอบ | `test_u19_invalid_draughts_origin_does_not_mutate` | ส่ง error และ state ไม่เปลี่ยน | PASS, PASS, PASS |
| U20 | Hybrid เริ่มเกม | `test_u20_armies_and_duel_deck` | จำนวนตัวและ deck ถูกกับโหมด | PASS, PASS, PASS |
| U21 | หมากมี duel ถูกกิน | `test_u21_duel_requires_resolution_before_capture` | ยังไม่ commit การกินระหว่าง XO | PASS, PASS, PASS |
| U22 | XO ฝ่ายหมากฮอสชนะ | `test_u22_checker_win_reverses_capture_and_consumes_only_duel` | สวนกินและใช้เฉพาะ duel | PASS, PASS, PASS |
| U23 | XO เสมอหรือฝ่าย Chess ชนะ | `test_u23_draw_and_chess_win_commit_capture` | commit การกินเดิม | PASS, PASS, PASS |
| U24 | king เป็นฝ่ายแพ้ในการดวล | `test_u24_king_lost_in_duel_ends_match` | เกมจบเมื่อต้องเสีย king | PASS, PASS, PASS |
| U25 | Hybrid ถึงตาหมากฮอส | `test_u25_checker_turn_uses_draughts_engine` | ใช้กติกาหมากฮอสสำหรับฝ่ายหมากฮอส | PASS, PASS, PASS |
| U26 | คิวฝั่งขาวมี entry ที่ใช้ไม่ได้ | `test_u26_white_skips_unavailable_queue_entry_then_consumes_push` | ข้ามคำสั่งที่ทำไม่ได้แล้วใช้ push | PASS, PASS, PASS |
| U27 | คิวฝั่งขาวมี revive/friendly | `test_u27_white_revival_and_friendly_capture` | คืนหมากและกินฝ่ายเดียวกันตามคำสั่ง | PASS, PASS, PASS |
| U28 | king ถูก lock และต้องหนี check | `test_u28_a_locked_king_still_can_escape_check_if_it_must` | king หนี check ได้ในทางบังคับ | PASS, PASS, PASS |
| U29 | XO boards หลายแนว | `test_u29_winning_lines_and_ninth_cell_draw` | แนวชนะและเสมอช่อง 9 ถูกต้อง | PASS, PASS, PASS |
| U30 | XO board ที่มีช่องลงและสถานะจบ | `test_u30_invalid_duplicate_and_terminal_moves_preserve_object` | move ผิดไม่แก้ object | PASS, PASS, PASS |
| U31 | Chess boards ที่ไม่มี move | `test_u31_checkmate_stalemate_and_bare_kings` | ผลรุกจน stalemate และ bare kings ถูกต้อง | PASS, PASS, PASS |
| U32 | หมากฮอสไม่มี move หรือไม่มีหมากและ XO fixture | `test_u32_draughts_no_moves_vs_no_pieces_and_xo_check` | แยก no moves/no pieces และผล XO ตามกติกา | PASS, PASS, PASS |
| U33 | Pydantic move/board coordinates | `test_u33_coordinates_bounds_require_integer` | รับ integer ในช่วงเท่านั้น | PASS, PASS, PASS |
| U34 | Pydantic player name | `test_u34_name_normalizes_and_rejects_invalid_length_controls` | normalize และปฏิเสธชื่อผิดเงื่อนไข | PASS, PASS, PASS |
| U35 | mock random สำหรับ seat creation | `test_u35_token_input_is_cryptorandom_and_only_hash_stored` | ใช้ cryptorandom และเก็บ hash ของ seat | PASS, PASS, PASS |
| U36 | Room snapshots สองที่นั่ง | `test_u36_snapshot_hides_opponent_skill_and_inactive_options` | ซ่อน skills และ options ตามสิทธิ์ | PASS, PASS, PASS |
| U37 | Room layout ไม่ผ่านเงื่อนไข | `test_u37_invalid_layout_does_not_commit` | layout ผิดไม่ commit | PASS, PASS, PASS |
| U38 | Room ขาว/ดำพร้อม mock log | `test_u38_seat_is_side_specific_and_auth_failure_logged` | credential ตรงฝั่งและมี event เมื่อถูกปฏิเสธ | PASS, PASS, PASS |
| U39 | เวลาจำลองและห้องสองสถานะ | `test_u39_waiting_lifetime_and_active_lifetime_boundaries` | expiry ถูกต้องที่ขอบของแต่ละสถานะ | PASS, PASS, PASS |
| U40 | deque quota และ clock จำลอง | `test_u40_expired_creation_entries_pruned_and_other_source_not_limited` | ตัดรายการหมดอายุและไม่แชร์โควตาข้ามแหล่ง | PASS, PASS, PASS |

## UI / Compatibility

[หลักฐาน JSON](../evidence/qa-2026-11-15/ui.json)

| ID | เงื่อนไขก่อนทดสอบ | ขั้นตอน | ผลคาดหวัง | ผลจริง | สถานะ |
|---|---|---|---|---|---|
| UI-320 | หน้าแรก Chrome | ปรับ viewport 320 px แล้ววัด viewport และขอบเนื้อหา ของกล่องธีม | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | {"width":320,"dialog_width":282} | PASS |
| UI-375 | หน้าแรก Chrome | ปรับ viewport 375 px แล้ววัด viewport และขอบเนื้อหา ของกล่องธีม | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | {"width":375,"dialog_width":337} | PASS |
| UI-768 | หน้าแรก Chrome | ปรับ viewport 768 px แล้ววัด viewport และขอบเนื้อหา ของกล่องธีม | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | {"width":768,"dialog_width":480} | PASS |
| UI-1024 | หน้าแรก Chrome | ปรับ viewport 1024 px แล้ววัด viewport และขอบเนื้อหา ของกล่องธีม | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | {"width":1024,"dialog_width":480} | PASS |
| UI-1440 | หน้าแรก Chrome | ปรับ viewport 1440 px แล้ววัด viewport และขอบเนื้อหา ของกล่องธีม | ไม่มี horizontal overflow และองค์ประกอบที่วัดอยู่ใน viewport | {"width":1440,"dialog_width":480} | PASS |

## Accessibility

[หลักฐาน JSON](../evidence/qa-2026-11-15/a11y.json)

| ID | เงื่อนไขก่อนทดสอบ | ขั้นตอน | ผลคาดหวัง | ผลจริง | สถานะ |
|---|---|---|---|---|---|
| A11Y-01 | ฟอร์มชื่อสร้างห้อง | กรอกสามช่องว่างแล้ว submit | error แสดงและมี focus, aria-invalid=true และ aria-describedby ผูกข้อความ | {'aria-invalid': None, 'aria-describedby': None, 'text': 'กรอกชื่อที่เพื่อนจะเห็น 1–24 ตัวอักษร โดยไม่ใช้อักขระควบคุม'} | FAIL |
| A11Y-03 | Local Hybrid ตั้งสกิลขาวและดำแล้ว | กด Enter ยืนยันครั้งสุดท้าย ตรวจ document.activeElement | focus อยู่ใน game view | {"tag":"BODY","inside":false} | FAIL |
| A11Y-02 | Local Hybrid เข้าตา XO | โฟกัสช่อง 1 กด Enter แล้ว ArrowRight | ช่องเดิมคง focus หลังลงและย้ายไปช่อง 2 เมื่อกดลูกศร | XO ช่องที่ลงแล้วคง focus และลูกศรทำงานตามทิศ | PASS |
| A11Y-04 | สองแท็บในห้อง Hybrid และ XO เปิด | จำลอง poll หลุดเฉพาะแท็บขาว รอ retry | ข้อความขัดข้องปรากฏใน XO dialog | {'room_status': 'การเชื่อมต่อขัดข้อง กำลังลองเชื่อมต่อใหม่', 'duel_contains_connection_status': False} | FAIL |

## Performance

[หลักฐาน JSON](../evidence/qa-2026-11-15/performance.json)

| ID | เงื่อนไขก่อนทดสอบ | ขั้นตอน | ผลคาดหวัง | ผลจริง | สถานะ |
|---|---|---|---|---|---|
| PERF-compression | ใช้ dist จริงและ Uvicorn | ขอ CSS, JS entry, Phaser ด้วย Accept-Encoding: gzip | ทุกไฟล์ 200 และ gzip | gzip ทั้ง 3 assets · ดู response headers ใน JSON | PASS |

## Security

[หลักฐาน JSON](../evidence/qa-2026-11-15/security.json)

| ID | เงื่อนไขก่อนทดสอบ | ขั้นตอน | ผลคาดหวัง | ผลจริง | สถานะ |
|---|---|---|---|---|---|
| SEC-PROD | CHESS_ENV=production | ขอหน้าแรกและ route docs/ไฟล์อ่อนไหวบน localhost | CSP, DENY, nosniff, referrer-policy ผ่าน route ที่ปิดได้ 404 | production headers และ scope static ผ่าน | PASS |
| SEC-LOG | production fixture แบบ no-access-log | สร้างห้องสังเคราะห์ อ่านหนึ่งครั้งไม่มีและมีสิทธิ์ แล้วตรวจ structured logs | มี room_created และ room_authorization_denied โดยไม่มีชื่อ, รหัสเชิญ, seat token | structured events มีเหตุการณ์และไม่มีชื่อเล่น รหัสเชิญหรือ seat token ใน test log | PASS |

A11Y-01, A11Y-03 และ A11Y-04 เป็นเทสต์บั๊กที่ทำให้เห็น FAIL บน checkout ปัจจุบัน เป้าหมายหลังแก้คือ PASS ครบโดยรักษา A11Y-02 ไว้ ยังไม่มีการรันกับโค้ดที่แก้แล้ว

