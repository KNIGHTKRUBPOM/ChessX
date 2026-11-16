-- Synthetic player for inspecting the local database; Auth integration tests register separately.
insert into auth.users (id, aud, role, email, raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
values (
    '42000000-0000-4000-8000-000000000001', 'authenticated', 'authenticated',
    'sample-player@example.invalid', '{"provider":"email","providers":["email"]}'::jsonb,
    '{"display_name":"ผู้เล่นตัวอย่าง"}'::jsonb, statement_timestamp(), statement_timestamp()
)
on conflict (id) do nothing;
