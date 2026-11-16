-- Store the complete, server-only state of an online room across FastAPI instances.
create schema if not exists chessmess_private;
revoke all on schema chessmess_private from public, anon, authenticated;
grant usage on schema chessmess_private to service_role;

create table if not exists chessmess_private.rooms (
    code text primary key check (code ~ '^[A-HJ-NP-Z2-9]{8}$'),
    room_id text not null unique,
    created_by text not null,
    revision integer not null check (revision >= 0),
    payload jsonb not null,
    expires_at timestamptz not null,
    constraint chessmess_room_payload_revision check (
        jsonb_typeof(payload) = 'object'
        and payload -> 'revision' is not distinct from to_jsonb(revision)
    )
);

create table if not exists chessmess_private.room_creations (
    created_by text not null,
    created_at timestamptz not null
);

create index if not exists chessmess_rooms_by_expiry on chessmess_private.rooms (expires_at);
create index if not exists chessmess_rooms_by_creator on chessmess_private.rooms (created_by);
create index if not exists chessmess_creations_by_time on chessmess_private.room_creations (created_at);
create index if not exists chessmess_creations_by_creator on chessmess_private.room_creations (created_by, created_at);

alter table chessmess_private.rooms enable row level security;
alter table chessmess_private.room_creations enable row level security;
revoke all on chessmess_private.rooms, chessmess_private.room_creations from public, anon, authenticated;
grant select, insert, update, delete on chessmess_private.rooms to service_role;
grant select, insert, delete on chessmess_private.room_creations to service_role;

create or replace function public.chessmess_room_create(
    p_code text, p_room_id text, p_source text, p_payload jsonb
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    checked_at timestamptz;
    first_creation timestamptz;
    recent_count integer;
    retry_after integer;
begin
    -- Serialize only creates, so quota checks and reservation share a transaction.
    perform pg_catalog.pg_advisory_xact_lock(1128813389, 1);
    checked_at := pg_catalog.clock_timestamp();

    delete from chessmess_private.rooms where expires_at <= checked_at;
    delete from chessmess_private.room_creations
    where created_at <= checked_at - interval '60 seconds';

    select count(*), min(created_at) into recent_count, first_creation
    from chessmess_private.room_creations where created_by = p_source;

    if recent_count >= 12 then
        retry_after := greatest(1, ceil(extract(epoch from first_creation + interval '60 seconds' - checked_at))::integer);
        return jsonb_build_object('status', 'rate', 'retry_after', retry_after);
    end if;

    if (select count(*) from chessmess_private.rooms where created_by = p_source) >= 16 then
        return '{"status":"source_limit"}'::jsonb;
    end if;

    if (select count(*) from chessmess_private.rooms) >= 256 then
        return '{"status":"capacity"}'::jsonb;
    end if;

    insert into chessmess_private.rooms (code, room_id, created_by, revision, payload, expires_at)
    values (p_code, p_room_id, p_source, 0, p_payload, checked_at + interval '15 minutes')
    on conflict do nothing;

    if not found then
        return '{"status":"collision"}'::jsonb;
    end if;

    insert into chessmess_private.room_creations (created_by, created_at)
    values (p_source, checked_at);

    return '{"status":"ok"}'::jsonb;
end;
$$;

create or replace function public.chessmess_room_read(p_code text)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select coalesce((
        select payload from chessmess_private.rooms
        where code = upper(p_code) and expires_at > statement_timestamp()
    ), 'null'::jsonb);
$$;

create or replace function public.chessmess_room_commit(
    p_code text, p_room_id text, p_revision integer, p_payload jsonb, p_short_lived boolean
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
begin
    -- Compare both revision and match identity because an expired code can be reused.
    if p_payload is null then
        delete from chessmess_private.rooms
        where code = upper(p_code) and room_id = p_room_id and revision = p_revision
          and expires_at > pg_catalog.clock_timestamp();
    else
        update chessmess_private.rooms
        set payload = p_payload, revision = p_revision + 1,
            expires_at = pg_catalog.clock_timestamp() + case
                when p_short_lived then interval '15 minutes'
                else interval '6 hours'
            end
        where code = upper(p_code) and room_id = p_room_id and revision = p_revision
          and p_short_lived is not null and expires_at > pg_catalog.clock_timestamp();
    end if;
    return to_jsonb(found);
end;
$$;

create or replace function public.chessmess_room_health()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select 'true'::jsonb;
$$;

revoke all on function public.chessmess_room_create(text, text, text, jsonb) from public, anon, authenticated;
revoke all on function public.chessmess_room_read(text) from public, anon, authenticated;
revoke all on function public.chessmess_room_commit(text, text, integer, jsonb, boolean) from public, anon, authenticated;
revoke all on function public.chessmess_room_health() from public, anon, authenticated;

grant execute on function public.chessmess_room_create(text, text, text, jsonb) to service_role;
grant execute on function public.chessmess_room_read(text) to service_role;
grant execute on function public.chessmess_room_commit(text, text, integer, jsonb, boolean) to service_role;
grant execute on function public.chessmess_room_health() to service_role;

notify pgrst, 'reload schema';
