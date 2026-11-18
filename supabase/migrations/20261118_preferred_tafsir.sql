-- Store each user's preferred Quran tafsir.
-- Run this migration in the Supabase SQL Editor before deploying the bot changes.

alter table public.bot_users
    add column if not exists preferred_tafsir integer not null default 0
    check (preferred_tafsir between 0 and 9);
