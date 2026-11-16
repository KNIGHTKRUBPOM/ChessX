-- Keep the direct Data API at the same assurance level as the account API.
create function public.chessmess_account_aal_ok()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select auth.uid() is not null and (
        auth.jwt() ->> 'aal' = 'aal2'
        or not exists (
            select 1 from auth.mfa_factors
            where user_id = auth.uid() and status = 'verified'
        )
    );
$$;

revoke all on function public.chessmess_account_aal_ok() from public, anon, authenticated;
grant execute on function public.chessmess_account_aal_ok() to authenticated;

create policy "profile needs verified account assurance"
on public.profiles as restrictive for all to authenticated
using ((select public.chessmess_account_aal_ok()))
with check ((select public.chessmess_account_aal_ok()));

create policy "stats need verified account assurance"
on public.player_stats as restrictive for select to authenticated
using ((select public.chessmess_account_aal_ok()));

create policy "match history needs verified account assurance"
on public.match_history as restrictive for select to authenticated
using ((select public.chessmess_account_aal_ok()));

notify pgrst, 'reload schema';
