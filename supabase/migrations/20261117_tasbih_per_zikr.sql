-- Per-user, per-phrase Tasbih counters.
-- Run this migration in the Supabase SQL Editor before deploying the bot changes.

create table if not exists public.bot_tasbih_counts (
    user_id bigint not null,
    zikr_index integer not null check (zikr_index between 0 and 13),
    count bigint not null default 0 check (count >= 0),
    primary key (user_id, zikr_index)
);

alter table public.bot_tasbih_counts enable row level security;
revoke all on public.bot_tasbih_counts from anon, authenticated;
grant all on public.bot_tasbih_counts to service_role;

create or replace function public.bot_change_tasbih_count(
    p_user_id bigint,
    p_zikr_index integer,
    p_change integer
)
returns bigint
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
declare
    v_count bigint;
begin
    if p_zikr_index < 0 or p_zikr_index > 13 then
        raise exception 'Invalid zikr index';
    end if;

    insert into public.bot_tasbih_counts (user_id, zikr_index, count)
    values (p_user_id, p_zikr_index, greatest(0, p_change))
    on conflict (user_id, zikr_index)
    do update set count = greatest(0, public.bot_tasbih_counts.count + p_change)
    returning count into v_count;

    return v_count;
end;
$$;

revoke all on function public.bot_change_tasbih_count(bigint, integer, integer) from public, anon, authenticated;
grant execute on function public.bot_change_tasbih_count(bigint, integer, integer) to service_role;
