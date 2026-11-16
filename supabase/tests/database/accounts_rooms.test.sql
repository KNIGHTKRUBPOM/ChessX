begin;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(68);

create temporary table chessmess_test_audit_start as
    select coalesce(max(id), 0) as id from chessmess_private.account_audit;

select ok((select relrowsecurity from pg_class where oid = 'public.profiles'::regclass), 'profiles enables RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.player_stats'::regclass), 'stats enables RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.match_history'::regclass), 'match history enables RLS');
select ok(not has_table_privilege('anon', 'public.profiles', 'SELECT'), 'guests have no profile table access');
select ok(not has_table_privilege('authenticated', 'public.profiles', 'INSERT'), 'clients cannot create profile rows');
select ok(has_column_privilege('authenticated', 'public.profiles', 'display_name', 'UPDATE'), 'clients can edit approved profile fields');
select ok(not has_column_privilege('authenticated', 'public.profiles', 'id', 'UPDATE'), 'clients cannot change profile identity');
select ok(not has_column_privilege('authenticated', 'public.profiles', 'created_at', 'UPDATE'), 'clients cannot edit profile timestamps');
select ok(not has_table_privilege('authenticated', 'public.player_stats', 'UPDATE'), 'clients cannot update wins');
select ok(not has_table_privilege('authenticated', 'public.match_history', 'INSERT'), 'clients cannot write a match outcome');
select ok(not has_table_privilege('authenticated', 'chessmess_private.account_audit', 'SELECT'), 'audit records stay private');
select ok(not has_schema_privilege('anon', 'chessmess_private', 'USAGE'), 'guests cannot enumerate room tables');
select ok(not has_function_privilege('anon', 'public.chessmess_room_read(text)', 'EXECUTE'), 'guests cannot invoke room storage RPC');
select ok(not has_function_privilege('authenticated', 'public.chessmess_room_commit(text,text,integer,jsonb,boolean)', 'EXECUTE'), 'authenticated clients cannot invoke the room commit RPC');
select ok(not has_function_privilege('authenticated', 'public.chessmess_account_audit(text,uuid)', 'EXECUTE'), 'clients cannot write audit records');
select ok(has_function_privilege('service_role', 'public.chessmess_account_audit(text,uuid)', 'EXECUTE'), 'server can write allowed audit events');
select ok(not has_function_privilege('authenticated', 'public.chessmess_prune_player_data()', 'EXECUTE'), 'client cannot invoke retention tasks');

insert into auth.users (id, aud, role, email, raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
values
    ('54000000-0000-4000-8000-000000000001', 'authenticated', 'authenticated', 'pgtap-a@example.invalid',
        '{"provider":"email"}', '{"display_name":"ณัฐ  Chess"}', statement_timestamp(), statement_timestamp()),
    ('54000000-0000-4000-8000-000000000002', 'authenticated', 'authenticated', 'pgtap-b@example.invalid',
        '{"provider":"email"}', '{"full_name":"Chess Player B"}', statement_timestamp(), statement_timestamp());

select is((select count(*) from public.profiles where id::text like '54000000-%'), 2::bigint, 'Auth trigger creates exactly one profile per user');
select is((select display_name from public.profiles where id = '54000000-0000-4000-8000-000000000001'), 'ณัฐ Chess', 'Auth name normalization');
select is((select avatar_url from public.profiles where id = '54000000-0000-4000-8000-000000000002'), null::text, 'provider media stays absent by default');

set local role authenticated;
set local "request.jwt.claims" = '{"sub":"54000000-0000-4000-8000-000000000001","role":"authenticated"}';

select is((select count(*) from public.profiles), 1::bigint, 'player sees only their own profile');
select is((select count(*) from public.player_stats), 1::bigint, 'player sees only their own stats');
select is((select games_played from public.player_stats), 0, 'new player starts at zero games');
with edited as (
    update public.profiles set display_name = 'First Player' returning display_name
)
select is((select display_name from edited), 'First Player', 'player can edit their own name');
select ok((select updated_at > created_at from public.profiles), 'profile update touches timestamp');
with edited as (
    update public.profiles set display_name = 'Another Player'
    where id = '54000000-0000-4000-8000-000000000002' returning id
)
select is((select count(*) from edited), 0::bigint, 'the other profile remains uneditable');

select throws_ok($$ update public.profiles set username = 'Bad Name' $$,
    '23514', null, 'username format constraint is enforced');
select throws_ok($$ update public.profiles set avatar_url = 'http://example.invalid/avatar.png' $$,
    '23514', null, 'avatar metadata requires HTTPS');

reset role;
set local role service_role;
select is(public.chessmess_room_health(), 'true'::jsonb, 'prior release room health is compatible');
select is(public.chessmess_room_create(
    'ABCD2345', '9876543210abcdef9876543210abcdef', 'pgtap-legacy-room',
    '{"revision":0,"mode":"chess","seats":{"w":{"name":"Guest"}},"outcome":null}'::jsonb
), '{"status":"ok"}'::jsonb, 'guest room creation is compatible');
select is(public.chessmess_room_read('abcd2345') ->> 'mode', 'chess', 'prior lower-case room lookup is compatible');
select is(public.chessmess_room_commit(
    'ABCD2345', '9876543210abcdef9876543210abcdef', 0, null, false
), 'true'::jsonb, 'closing a guest room remains compatible');
select is(public.chessmess_room_read('ABCD2345'), 'null'::jsonb, 'closed guest room no longer found');

select is(public.chessmess_room_create(
    'ABCD2346', '9876543210abcdef9876543210abcdee', 'pgtap-account-room',
    '{"revision":0,"mode":"hybrid","seats":{"w":{"name":"Player A","account_id":"54000000-0000-4000-8000-000000000001"}},"outcome":null}'::jsonb
), '{"status":"ok"}'::jsonb, 'server creates room with signed-in player');
select is(public.chessmess_room_read('ABCD2346') #>> '{seats,w,account_id}', null::text, 'room JSON excludes user UUID');
select is(public.chessmess_room_commit('ABCD2346', '9876543210abcdef9876543210abcdee', 0,
    '{"revision":1,"mode":"hybrid","seats":{"w":{"name":"Player A"},"b":{"name":"Player B","account_id":"54000000-0000-4000-8000-000000000002"}},"outcome":null}'::jsonb, false
), 'true'::jsonb, 'server associates second signed-in player');
select is(public.chessmess_room_commit('ABCD2346', '9876543210abcdef9876543210abcdee', 1,
    '{"revision":2,"mode":"hybrid","seats":{"w":{"name":"Player A"},"b":{"name":"Player B"}},"outcome":{"winner":"w","reason":"fixture"}}'::jsonb, false
), 'true'::jsonb, 'authority commits a finished match');
select is(public.chessmess_room_commit('ABCD2346', '9876543210abcdef9876543210abcdee', 1,
    '{"revision":2,"mode":"hybrid","seats":{"w":{"name":"Player A"},"b":{"name":"Player B"}},"outcome":{"winner":"w","reason":"fixture"}}'::jsonb, false
), 'false'::jsonb, 'replayed revision cannot write a second result');
select is(public.chessmess_room_commit('ABCD2346', '9876543210abcdef9876543210abcdee', 2,
    '{"revision":3,"mode":"hybrid","seats":{"w":{"name":"Player A"},"b":{"name":"Player B"}},"outcome":{"winner":"w","reason":"fixture"}}'::jsonb, true
), 'true'::jsonb, 'subsequent changes on finished room remain compatible');

select lives_ok($$ select public.chessmess_account_audit('login_success','54000000-0000-4000-8000-000000000001') $$,
    'service-only API records a permitted event');

reset role;
select is((select count(*) from public.match_history where match_id = '9876543210abcdef9876543210abcdee'), 2::bigint,
    'both distinct verified players receive exactly one result');
select is((select wins from public.player_stats where player_id = '54000000-0000-4000-8000-000000000001'), 1,
    'white win counted once');
select is((select losses from public.player_stats where player_id = '54000000-0000-4000-8000-000000000002'), 1,
    'black loss counted once');

set local role authenticated;
set local "request.jwt.claims" = '{"sub":"54000000-0000-4000-8000-000000000002","role":"authenticated"}';
select is((select count(*) from public.match_history), 1::bigint, 'player sees no opponent result row');
select is((select result from public.match_history), 'loss', 'players see only their own outcome');

reset role;
delete from auth.users where id = '54000000-0000-4000-8000-000000000001';
select is((select count(*) from public.profiles where id = '54000000-0000-4000-8000-000000000001'), 0::bigint,
    'account deletion cascades to profile');
select is((select count(*) from public.player_stats where player_id = '54000000-0000-4000-8000-000000000001'), 0::bigint,
    'account deletion cascades to stats');
select is((select count(*) from public.match_history where match_id = '9876543210abcdef9876543210abcdee'), 1::bigint,
    'account deletion removes own history without discarding opponent history');
select is((select count(*) from chessmess_private.room_players where player_id = '54000000-0000-4000-8000-000000000001'), 0::bigint,
    'account deletion removes the room binding even while the room exists');
select is((select count(*) from chessmess_private.account_audit where event = 'login_success' and actor_id is null
        and id > (select id from chessmess_test_audit_start)), 1::bigint,
    'account deletion anonymizes existing audit row');
select is((select count(*) from chessmess_private.account_audit where event = 'account_deleted' and actor_id is null
        and id > (select id from chessmess_test_audit_start)), 1::bigint,
    'account deletion logs exactly one anonymized event');

set local role service_role;

select is(public.chessmess_room_create(
    'ABCD2347', '9876543210abcdef9876543210abcded', 'pgtap-shared-account',
    '{"revision":0,"mode":"chess","seats":{"w":{"account_id":"54000000-0000-4000-8000-000000000002"}},"outcome":null}'::jsonb
), '{"status":"ok"}'::jsonb, 'one account can still open a casual room');
select is(public.chessmess_room_commit('ABCD2347', '9876543210abcdef9876543210abcded', 0,
    '{"revision":1,"mode":"chess","seats":{"w":{},"b":{"account_id":"54000000-0000-4000-8000-000000000002"}},"outcome":null}'::jsonb, false
), 'true'::jsonb, 'same-account second seat remains playable');
select is(public.chessmess_room_commit('ABCD2347', '9876543210abcdef9876543210abcded', 1,
    '{"revision":2,"mode":"chess","seats":{"w":{},"b":{}},"outcome":{"winner":null}}'::jsonb, false
), 'true'::jsonb, 'casual game can still finish without counting same-account result');

select is(public.chessmess_room_create(
    'ABCD2348', '9876543210abcdef9876543210abcdec', 'pgtap-mixed-account-room',
    '{"revision":0,"mode":"chess","seats":{"w":{"account_id":"54000000-0000-4000-8000-000000000002"}},"outcome":null}'::jsonb
), '{"status":"ok"}'::jsonb, 'member can play against guests');
select is(public.chessmess_room_commit('ABCD2348', '9876543210abcdef9876543210abcdec', 0,
    '{"revision":1,"mode":"chess","seats":{"w":{},"b":{}},"outcome":null}'::jsonb, false
), 'true'::jsonb, 'guest can join a member room');
select is(public.chessmess_room_commit('ABCD2348', '9876543210abcdef9876543210abcdec', 1,
    '{"revision":2,"mode":"chess","seats":{"w":{},"b":{}},"outcome":{"winner":"w"}}'::jsonb, false
), 'true'::jsonb, 'member and guest can finish a casual game');

reset role;
select is((select count(*) from public.match_history where match_id in ('9876543210abcdef9876543210abcdee','9876543210abcdef9876543210abcded','9876543210abcdef9876543210abcdec')), 1::bigint, 'casual matches do not award account stats');
select is((select games_played from public.player_stats where player_id = '54000000-0000-4000-8000-000000000002'), 1,
    'only the original distinct-account result counts');

update chessmess_private.account_audit
    set created_at = statement_timestamp() - interval '91 days'
    where event = 'login_success' and id > (select id from chessmess_test_audit_start);
update public.match_history set finished_at = statement_timestamp() - interval '366 days'
    where match_id = '9876543210abcdef9876543210abcdee';
set local role service_role;
select lives_ok($$ select public.chessmess_prune_player_data() $$, 'server retention task succeeds');
reset role;
select is((select count(*) from chessmess_private.account_audit where id > (select id from chessmess_test_audit_start)), 1::bigint, 'expiry removes only the older audit row');
select is((select count(*) from public.match_history where match_id = '9876543210abcdef9876543210abcdee'), 0::bigint, 'expiry removes old match history');
select is((select games_played from public.player_stats where player_id = '54000000-0000-4000-8000-000000000002'), 1,
    'retention preserves aggregate player stats');


insert into auth.mfa_factors (id, user_id, factor_type, status, created_at, updated_at)
values ('54000000-0000-4000-8000-000000000010', '54000000-0000-4000-8000-000000000002',
        'totp', 'verified', statement_timestamp(), statement_timestamp());
select ok(not has_function_privilege('anon', 'public.chessmess_account_aal_ok()', 'EXECUTE'), 'guest cannot invoke assurance helper');

set local role authenticated;
set local "request.jwt.claims" = '{"sub":"54000000-0000-4000-8000-000000000002","role":"authenticated","aal":"aal1"}';
select is((select count(*) from public.profiles), 0::bigint, 'MFA account needs AAL2 to read profile via Data API');
select is((select count(*) from public.player_stats), 0::bigint, 'MFA account needs AAL2 to read stats via Data API');
with changed as (update public.profiles set display_name = 'No AAL2' returning id)
select is((select count(*) from changed), 0::bigint, 'MFA account needs AAL2 to edit profile via Data API');
set local "request.jwt.claims" = '{"sub":"54000000-0000-4000-8000-000000000002","role":"authenticated","aal":"aal2"}';
select is((select count(*) from public.profiles), 1::bigint, 'AAL2 allows the owners profile');
reset role;

select * from finish();
rollback;
