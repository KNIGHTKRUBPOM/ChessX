-- Player identities never appear in the published game snapshot.
create table public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    username text not null unique,
    display_name text not null,
    avatar_url text,
    created_at timestamptz not null default statement_timestamp(),
    updated_at timestamptz not null default statement_timestamp(),
    constraint profiles_username_format check (
        username ~ '^[a-z0-9_]{3,34}$'
        and (username !~ '^u_[0-9a-f]{32}$' or username = 'u_' || replace(id::text, '-', ''))
    ),
    constraint profiles_display_name_format check (
        char_length(display_name) between 1 and 24
        and display_name = btrim(display_name)
        and display_name ~ '[^[:space:]]'
        and display_name !~ '[[:cntrl:]]'
    ),
    constraint profiles_avatar_https check (
        avatar_url is null or (
            char_length(avatar_url) <= 512
            and avatar_url ~ '^https://[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?([/?#][^[:space:][:cntrl:]]*)?$'
        )
    )
);

create table public.player_stats (
    player_id uuid primary key references public.profiles(id) on delete cascade,
    games_played integer not null default 0 check (games_played >= 0),
    wins integer not null default 0 check (wins >= 0),
    losses integer not null default 0 check (losses >= 0),
    draws integer not null default 0 check (draws >= 0),
    updated_at timestamptz not null default statement_timestamp(),
    constraint player_stats_totals check (games_played = wins + losses + draws)
);

create table public.match_history (
    match_id text not null,
    player_id uuid not null references public.profiles(id) on delete cascade,
    mode text not null check (mode in ('chess', 'draughts', 'hybrid')),
    side text not null check (side in ('w', 'b')),
    result text not null check (result in ('win', 'loss', 'draw')),
    finished_at timestamptz not null default statement_timestamp(),
    constraint match_history_id_format check (match_id ~ '^[a-f0-9]{32}$'),
    primary key (match_id, player_id)
);

create index chessmess_match_history_for_player
    on public.match_history (player_id, finished_at desc, match_id desc);
create index chessmess_match_history_by_age on public.match_history (finished_at);

alter table public.profiles enable row level security;
alter table public.player_stats enable row level security;
alter table public.match_history enable row level security;

revoke all on public.profiles, public.player_stats, public.match_history
    from public, anon, authenticated, service_role;
grant select on public.profiles, public.player_stats, public.match_history to authenticated;
grant update (username, display_name, avatar_url) on public.profiles to authenticated;

create policy "player reads own profile" on public.profiles
    for select to authenticated using (id = (select auth.uid()));
create policy "player updates own profile" on public.profiles
    for update to authenticated
    using (id = (select auth.uid()))
    with check (id = (select auth.uid()));
create policy "player reads own stats" on public.player_stats
    for select to authenticated using (player_id = (select auth.uid()));
create policy "player reads own match history" on public.match_history
    for select to authenticated using (player_id = (select auth.uid()));

create function chessmess_private.touch_player_profile()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
    new.updated_at := pg_catalog.statement_timestamp();
    return new;
end;
$$;

revoke execute on function chessmess_private.touch_player_profile()
    from public, anon, authenticated, service_role;

create trigger chessmess_profiles_updated_at
    before update on public.profiles
    for each row execute function chessmess_private.touch_player_profile();

create function chessmess_private.default_display_name(p_metadata jsonb)
returns text language sql immutable security invoker set search_path = '' as $$
    select coalesce(
        nullif(btrim(left(regexp_replace(coalesce(
            case when jsonb_typeof(p_metadata -> 'display_name') = 'string' then p_metadata ->> 'display_name' end,
            case when jsonb_typeof(p_metadata -> 'full_name') = 'string' then p_metadata ->> 'full_name' end,
            case when jsonb_typeof(p_metadata -> 'name') = 'string' then p_metadata ->> 'name' end,
            ''
        ), '[[:space:][:cntrl:]]+', ' ', 'g'), 24)), ''),
        'ผู้เล่น'
    );
$$;

revoke execute on function chessmess_private.default_display_name(jsonb)
    from public, anon, authenticated, service_role;

create function chessmess_private.bootstrap_player_profile()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
    insert into public.profiles (id, username, display_name)
    values (
        new.id,
        'u_' || replace(new.id::text, '-', ''),
        chessmess_private.default_display_name(new.raw_user_meta_data)
    );
    insert into public.player_stats (player_id) values (new.id);
    return new;
end;
$$;

revoke execute on function chessmess_private.bootstrap_player_profile()
    from public, anon, authenticated, service_role;

create trigger chessmess_auth_user_created
    after insert on auth.users
    for each row execute function chessmess_private.bootstrap_player_profile();

-- Initialize accounts created before this migration without overwriting a chosen profile.
insert into public.profiles (id, username, display_name)
    select id, 'u_' || replace(id::text, '-', ''),
           chessmess_private.default_display_name(raw_user_meta_data)
    from auth.users
on conflict (id) do nothing;

insert into public.player_stats (player_id)
    select id from public.profiles
on conflict (player_id) do nothing;

create table chessmess_private.account_audit (
    id bigint generated always as identity primary key,
    actor_id uuid references auth.users(id) on delete set null,
    event text not null check (event in (
        'login_failed', 'login_success', 'oauth_login', 'password_changed', 'email_changed',
        'mfa_enrolled', 'mfa_removed', 'identity_linked', 'identity_unlinked', 'logout_all',
        'account_deleted', 'account_exported'
    )),
    created_at timestamptz not null default statement_timestamp()
);

create index chessmess_account_audit_by_age on chessmess_private.account_audit (created_at);
create index chessmess_account_audit_by_actor on chessmess_private.account_audit (actor_id);
alter table chessmess_private.account_audit enable row level security;
revoke all on chessmess_private.account_audit from public, anon, authenticated, service_role;

create function public.chessmess_account_audit(p_event text, p_actor_id uuid default null)
returns void language plpgsql security definer set search_path = '' as $$
declare
    actor uuid;
begin
    if p_event is null or p_event = 'account_deleted' then
        raise exception 'Invalid account audit event' using errcode = '22023';
    end if;
    if p_actor_id is not null then
        select id into actor from auth.users where id = p_actor_id for key share;
    end if;
    insert into chessmess_private.account_audit (event, actor_id) values (p_event, actor);
end;
$$;

revoke execute on function public.chessmess_account_audit(text, uuid)
    from public, anon, authenticated, service_role;
grant execute on function public.chessmess_account_audit(text, uuid) to service_role;

create function chessmess_private.record_account_deleted()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
    insert into chessmess_private.account_audit (event) values ('account_deleted');
    return old;
end;
$$;

revoke execute on function chessmess_private.record_account_deleted()
    from public, anon, authenticated, service_role;

create trigger chessmess_auth_user_deleted
    after delete on auth.users
    for each row execute function chessmess_private.record_account_deleted();

-- The server hands identity to the storage transaction; room state never retains it.
create table chessmess_private.room_players (
    room_id text not null references chessmess_private.rooms(room_id) on delete cascade,
    side text not null check (side in ('w', 'b')),
    player_id uuid not null references public.profiles(id) on delete cascade,
    primary key (room_id, side)
);

create index chessmess_room_players_by_player on chessmess_private.room_players (player_id);
alter table chessmess_private.room_players enable row level security;
revoke all on chessmess_private.room_players from public, anon, authenticated, service_role;

create function chessmess_private.record_finished_room()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
    seat_side text;
    selected_account text;
    selected_player uuid;
    scrubbed jsonb := new.payload;
    players record;
    sides uuid[];
    winner text := new.payload #>> '{outcome,winner}';
    mode_name text := new.payload ->> 'mode';
    player_result text;
begin
    foreach seat_side in array array['w', 'b'] loop
        selected_account := new.payload #>> array['seats', seat_side, 'account_id'];
        if selected_account is null then
            continue;
        end if;
        scrubbed := scrubbed #- array['seats', seat_side, 'account_id'];

        -- A profile can disappear while a room is active.
        if selected_account ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
            select id into selected_player from public.profiles
                where id = selected_account::uuid for key share;
            if found then
                insert into chessmess_private.room_players (room_id, side, player_id)
                    values (new.room_id, seat_side, selected_player)
                    on conflict (room_id, side) do nothing;
            end if;
        end if;
    end loop;

    if scrubbed is distinct from new.payload then
        update chessmess_private.rooms set payload = scrubbed where room_id = new.room_id;
    end if;

    if tg_op <> 'UPDATE'
       or jsonb_typeof(old.payload -> 'outcome') = 'object'
       or jsonb_typeof(new.payload -> 'outcome') is distinct from 'object'
       or not (new.payload -> 'outcome' ? 'winner')
       or (winner is not null and winner not in ('w', 'b'))
       or mode_name is null or mode_name not in ('chess', 'draughts', 'hybrid') then
        return new;
    end if;

    -- Locks keep the saved identities valid through this result transaction.
    select array_agg(locked_players.id order by locked_players.side) into sides
    from (
        select profile.id, participant.side
        from chessmess_private.room_players participant
        join public.profiles profile on profile.id = participant.player_id
        where participant.room_id = new.room_id
        order by profile.id
        for key share of profile
    ) locked_players;
    if cardinality(sides) is distinct from 2 or sides[1] = sides[2] then
        return new;
    end if;

    -- Two rooms ending simultaneously acquire the same player's stats locks in UUID order.
    for players in
        select participant.player_id, participant.side
        from chessmess_private.room_players participant
        where participant.room_id = new.room_id
        order by participant.player_id
    loop
        player_result := case when winner is null then 'draw'
                              when players.side = winner then 'win' else 'loss' end;
        insert into public.match_history (match_id, player_id, mode, side, result)
            values (new.room_id, players.player_id, mode_name, players.side, player_result)
            on conflict (match_id, player_id) do nothing;

        if found then
            update public.player_stats set
                games_played = games_played + 1,
                wins = wins + (player_result = 'win')::integer,
                losses = losses + (player_result = 'loss')::integer,
                draws = draws + (player_result = 'draw')::integer,
                updated_at = pg_catalog.statement_timestamp()
            where player_id = players.player_id;
        end if;
    end loop;
    return new;
end;
$$;

revoke execute on function chessmess_private.record_finished_room()
    from public, anon, authenticated, service_role;

create trigger chessmess_room_settlement
    after insert or update of payload on chessmess_private.rooms
    for each row execute function chessmess_private.record_finished_room();

-- Invoke as an authenticated operator from a retention job only.
create function public.chessmess_prune_player_data()
returns void language sql security definer set search_path = '' as $$
    delete from chessmess_private.account_audit where created_at < statement_timestamp() - interval '90 days';
    delete from public.match_history where finished_at < statement_timestamp() - interval '365 days';
$$;

revoke execute on function public.chessmess_prune_player_data()
    from public, anon, authenticated, service_role;
grant execute on function public.chessmess_prune_player_data() to service_role;

notify pgrst, 'reload schema';
