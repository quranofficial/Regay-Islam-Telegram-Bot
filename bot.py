"""ڕێگای ئیسلام — Telegram edition, built from the supplied Android app data."""
from __future__ import annotations
import os, json, math, sqlite3, logging, asyncio, io, urllib.request, calendar
from pathlib import Path
from urllib.error import HTTPError, URLError
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from supabase_store import (is_configured, save_user, get_city, set_city, get_qari, set_qari, is_setup_completed, set_setup_completed, save_feedback, touch_runtime_heartbeat, get_prayer_notifications, set_prayer_notifications, list_prayer_notification_users, claim_prayer_notification, init_user_features, save_last_read, add_favorite, remove_favorite, list_favorites, get_last_read, get_tasbih, change_tasbih, reset_tasbih, get_user_count, list_users, get_admin_stats, is_banned, ban_user, unban_user, get_tasbih_zikr, set_tasbih_zikr, get_menu_order, set_menu_order)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Baghdad"))
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("regay_islam")

# JSON collections copied without content rewriting from the supplied app.
JSON_FILES = {
    "farmwda": ("فەرموودە هەڵبژێردراوەکان", "farmwda.json"),
    "zikrakan": ("زیکرەکان", "zikrakan.json"),
    "duha": ("دوعا و پاڕانەوە", "duha.json"),
    "pexambarman": ("ژیانی پێغەمبەرمان ﷺ", "pexambarman.json"),
    "pexambaran": ("ژیانی پێغەمبەران", "pexambaran.json"),
    "haram": ("حەرامکراوەکان", "haram.json"),
    "tawanakan": ("تاوانەکان", "tawanakan.json"),
    "xawn": ("خەوننامە", "xawn.json"),
    "bahasht": ("بەهەشت", "bahasht.json"),
    "dozax": ("دۆزەخ", "dozax.json"),
    "dajal": ("دەربارەی دەججاڵ", "dajal.json"),
    "hawal": ("هاوەڵانی پێغەمبەر ﷺ", "hawal.json"),
    "agr": ("ئەهلی ئاگر", "agr.json"),
    "zanyaryquran": ("زانیارییەکانی قورئان", "zanyaryquran.json"),
    "balaposhi": ("باڵاپۆشی", "balaposhi.json"),
    "rawbochwn": ("ڕاو و بۆچوون", "rawbochwn.json"),
    "swnat": ("سوننەتەکان", "swnat.json"),
    "wta": ("وتە و ئامۆژگاری", "wta.json"),
    "xaybat": ("تاوانی غەیبەت", "xaybat.json"),
    "gggg": ("چل فەرموودە دەربارەی ئافرەتان", "gggg.json"),
    "girlss": ("پرسیار و وەڵامی ئافرەتان", "girlss.json"),
    "zianakanygorani": ("زیانەکانی گۆرانی", "zianakanygorani.json"),
    "hajw": ("حەج و عومرە", "hajw.json"),
    "taybat": ("ڕوقیەی شەرعی", "taybat.json"),
    "dangakan": ("دەنگی بانگ و قارییەکان", "dangakan.json"),
    "dangebangbezh": ("بانگ و دەنگەکان", "dangebangbezh.json"),
    "cityme": ("شارەکان", "cityme.json"),
}
_json_cache: dict[str, list] = {}

def load_json(key: str) -> list:
    if key not in _json_cache:
        filename = JSON_FILES[key][1]
        with open(DATA / filename, "r", encoding="utf-8") as f:
            value = json.load(f)
        value = value if isinstance(value, list) else []
        # Show every record from zikrakan.json without trimming.
        _json_cache[key] = value
    return _json_cache[key]

def db(name: str):
    return sqlite3.connect(f"file:{DATA / name}?mode=ro", uri=True, timeout=10)


FIREBASE_DATABASE_URL = os.getenv(
    "FIREBASE_DATABASE_URL",
    "https://regayislam-1-default-rtdb.firebaseio.com",
).rstrip("/")


def _firebase_decode(value):
    if isinstance(value, str) and value.strip().startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    while isinstance(value, dict) and len(value) == 1:
        value = next(iter(value.values()))
        if isinstance(value, str) and value.strip().startswith(("[", "{")):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                break
    return value


def _firebase_get_sync(path):
    from urllib.parse import quote
    safe_path = "/".join(quote(part, safe="") for part in path.split("/") if part)
    url = f"{FIREBASE_DATABASE_URL}/{safe_path}.json"
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "Regay-Islam-Bot/1.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def download_remote_bytes(url, max_bytes, timeout):
    request = urllib.request.Request(
        url, headers={"User-Agent": "Regay-Islam-Telegram-Bot/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
    if not data or len(data) > max_bytes:
        raise ValueError("Remote file is empty or exceeds the allowed size")
    return data


async def firebase_get(path):
    try:
        return await asyncio.to_thread(_firebase_get_sync, path)
    except Exception:
        log.exception("Firebase read failed for path %s", path)
        return None


async def firebase_live_channels():
    value = _firebase_decode(await firebase_get("Live"))
    if isinstance(value, list):
        rows = [dict(x) for x in value if isinstance(x, dict)]
    elif isinstance(value, dict):
        rows = []
        for key, item in value.items():
            if isinstance(item, dict):
                rows.append({"id": str(key), **item})
    else:
        rows = []
    return [x for x in rows if str(x.get("url") or x.get("link") or "").strip()]


VIDEO_PROFILES = [
    {"image": "https://github.com/quranofficial/Profile/raw/main/IMG_20260218_221732_861.jpg", "name": "توێشووی سەفەر", "tag": "20262018102057"},
    {"image": "https://github.com/quranofficial/M.Hawre/raw/main/photo_2025-12-09_02-26-14.jpg", "name": "م.هاوڕێ (قیامەت)", "tag": "20252709022751"},
    {"image": "https://github.com/quranofficial/Profile/raw/main/IMG_8673.JPG", "name": "قورئانی پیرۆز", "tag": "20255826105848"},
    {"image": "https://github.com/quranofficial/Profile/raw/main/20240405_210531.png", "name": "ڕێگای ئیسلام", "tag": "20251908071938"},
    {"image": "https://github.com/quranofficial/Profile/raw/main/663545Image1.jpg", "name": "م.کرێکار", "tag": "20250928010945"},
    {"image": "https://github.com/quranofficial/Profile/raw/main/channels4_profile.jpg", "name": "م.محمد أحمد کەلاری", "tag": "20253612033606"},
    {"image": "https://github.com/quranofficial/Profile/raw/main/IMG_20250305_154200_574.jpg", "name": "فێربوونی قورئانی پیرۆز", "tag": "20254305034300"},
    {"image": "https://github.com/quranofficial/Profile/raw/main/600px-%D9%85%D8%AD%D9%85%D8%AF_%D9%85%D9%84%D8%A7_%D9%81%D8%A7%D8%A6%D9%82.jpg", "name": "م.محمد فائق شارەزووری", "tag": "20253505033537"},
    {"image": "https://github.com/quranofficial/Profile/raw/main/download.jpeg", "name": "م.ماکوان کەریم", "tag": "20252405032442"},
]


async def firebase_video_profiles():
    value = _firebase_decode(await firebase_get("videoall"))
    if isinstance(value, list):
        return [
            {"image": str(item.get("image") or "").strip(),
             "name": str(item.get("name") or "بێ ناو").strip(),
             "tag": str(item.get("tag") or "").strip()}
            for item in value if isinstance(item, dict) and str(item.get("tag") or "").strip()
        ]
    # Keep the supplied profile list available if the optional Firebase node is unavailable.
    return VIDEO_PROFILES


async def firebase_videos(profile_tag=None):
    value = await firebase_get(f"videoNew/{profile_tag}" if profile_tag else "videoNew")
    rows = []
    if isinstance(value, dict):
        for folder, items in ([(str(profile_tag), value)] if profile_tag else value.items()):
            if not isinstance(items, dict):
                continue
            for key, item in items.items():
                if isinstance(item, dict):
                    row = {"id": str(key), "folder": str(folder), **item}
                    row["url"] = row.get("url") or row.get("link") or row.get("video")
                    if str(row.get("url") or "").startswith(("http://", "https://")):
                        rows.append(row)
    rows.sort(key=lambda x: int(x.get("date") or 0) if str(x.get("date") or "").isdigit() else 0, reverse=True)
    return rows

MENU_ITEMS = {
    "quran": "📖 قورئانی پیرۆز", "prayer": "🕌 کاتەکانی بانگ",
    "kursi": "🕋 ئایەتی کورسی", "mushaf": "📖 مصحەف",
    "monthly": "🗓 کاتەکانی بانگی مانگانە", "tasbih": "📿 تەسبیح",
    "zikrakan": "📿 زیکرەکان", "dua": "🤲 دوعاکان",
    "hadith": "📜 فەرموودەکان", "pdf": "📚 کتێبخانەی PDF",
    "feedback": "💬 پێشنیار و ڕەخنە", "ramadan": "🌙 ڕەمەزان",
    "names": "📿 ناوەکانی خودا",
    "reciters": "🎙️ قارییەکان", "search": "🔎 گەڕان",
    "topics": "📚 هەموو بابەتەکان", "videos": "🎞️ ڤیدیۆی ئاینی", "favorites": "⭐ دڵخوازەکان",
    "lastread": "📍 دوا خوێندنەوە", "settings": "⚙️ ڕێکخستن",
    "about": "ℹ️ دەربارەی بۆت",
}
DEFAULT_MENU_ORDER = list(MENU_ITEMS)


def main_keyboard(uid=None):
    order = get_menu_order(uid) if uid is not None else []
    valid = [key for key in order if key in MENU_ITEMS]
    keys = valid + [key for key in DEFAULT_MENU_ORDER if key not in valid]
    buttons = [KeyboardButton(MENU_ITEMS[key]) for key in keys]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([KeyboardButton("شاردنەوەی مێنیو")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=False)

def ik(rows):
    return InlineKeyboardMarkup(rows)

def cut(text: str, limit=3800):
    text = str(text or "").strip()
    if len(text) <= limit: return [text]
    out=[]
    while text:
        pos=text.rfind("\n",0,limit)
        if pos < limit//2: pos=limit
        out.append(text[:pos]); text=text[pos:].lstrip()
    return out

async def send_text(update: Update, text: str, reply_markup=None, parse_mode=None):
    for i, part in enumerate(cut(text)):
        await update.effective_message.reply_text(part, reply_markup=reply_markup if i == len(cut(text))-1 else None, parse_mode=parse_mode, disable_web_page_preview=True)

CHANNEL_USERNAME = "@Regayislam_1"
CHANNEL_URL = "https://t.me/Regayislam_1"

def channel_join_markup():
    return ik([
        [InlineKeyboardButton("🔗 چوونە ناو کەناڵ", url=CHANNEL_URL)],
        [InlineKeyboardButton("🔄 پشکنین", callback_data="channel:check")],
    ])

async def is_channel_member(bot, user_id):
    member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
    return member.status in ("member", "administrator", "creator") or (
        member.status == "restricted" and bool(getattr(member, "is_member", False))
    )

async def membership_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    if query and query.data == "channel:check":
        try:
            joined = await is_channel_member(context.bot, user.id)
        except Exception:
            log.exception("Could not verify channel membership for user %s", user.id)
            await query.answer("پشکنینی ئەندامبوون سەرکەوتوو نەبوو؛ تکایە دواتر هەوڵ بدەرەوە.", show_alert=True)
            raise ApplicationHandlerStop
        if joined:
            await query.answer("✅ ئەندامبوون پشتڕاستکرایەوە.")
            await query.edit_message_text("✅ بەخێربێیت! ئێستا دەتوانیت بۆتەکە بەکاربهێنیت.\n\nبۆ دەستپێکردن /start بنووسە.")
        else:
            await query.answer("هێشتا ئەندامی کەناڵ نەبوویت.", show_alert=True)
            await query.edit_message_text(
                "🔒 بۆ بەکارهێنانی بۆتەکە، سەرەتا دەبێت ببیتە ئەندامی کەناڵەکەمان.\n\n"
                "١. بچۆ ناو کەناڵەکە.\n"
                "٢. پاشان دوگمەی «پشکنین» دابگرە.",
                reply_markup=channel_join_markup()
            )
        raise ApplicationHandlerStop
    try:
        if await is_channel_member(context.bot, user.id):
            return
    except Exception:
        log.exception("Could not verify channel membership for user %s", user.id)
    prompt = (
        "🔒 بۆ بەکارهێنانی بۆتەکە، سەرەتا دەبێت ببیتە ئەندامی کەناڵەکەمان.\n\n"
        "١. بچۆ ناو کەناڵەکە.\n"
        "٢. پاشان دوگمەی «پشکنین» دابگرە."
    )
    if query:
        await query.answer("سەرەتا دەبێت ببیتە ئەندامی کەناڵ.", show_alert=True)
        await query.edit_message_text(prompt, reply_markup=channel_join_markup())
    elif update.effective_message:
        await update.effective_message.reply_text(prompt, reply_markup=channel_join_markup())
    raise ApplicationHandlerStop

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Supabase calls are synchronous; run them off the event loop so Telegram
    # can keep responding to other users while this user's profile is saved.
    await asyncio.to_thread(save_user, user.id, user.first_name or "", user.username or "")
    setup_completed = await asyncio.to_thread(is_setup_completed, user.id)
    if not setup_completed:
        await update.effective_message.reply_text(
            "🕌 بەخێربێیت بۆ بۆتی ڕێگای ئیسلام\n\n"
            "📖 قورئانی پیرۆز و مصحەف\n🕌 کاتەکانی بانگ\n📜 فەرموودە و زانیاریی ئایینی\n🤲 دوعا و زیکر\n\n"
            "⚙️ بۆ دەستپێکردن، تکایە شارەکەت و قاریی دڵخوازت هەڵبژێرە.\n"
            "🔒 ئەم هەڵبژاردنانە پاشەکەوت دەکرێن و هەر کاتێک دەتوانیت بیانگۆڕیت."
        )
        return await setup_city_menu(update, 0)
    text = ("🕌 *بەخێربێیتەوە بۆ ڕێگای ئیسلام*\n\n"
            "✨ هەموو ئەوەی پێویستتە بۆ خوێندنەوە و فێربوونی ئایینی لێرە کۆکراوەتەوە.\n\n"
            "📖 قورئان و مصحەف\n🕌 کاتەکانی بانگ\n📜 فەرموودەکان\n"
            "🤲 دوعا و زیکر\n🎙️ قارییەکان\n📚 کتێبخانە و بابەتەکان\n\n"
            "👇 تکایە بەشێک لە مێنیوی خوارەوە هەڵبژێرە.")
    await update.effective_message.reply_text(text, reply_markup=main_keyboard(update.effective_user.id), parse_mode=ParseMode.MARKDOWN)


def setup_city_menu(update, page=0, edit=False):
    cities = get_cities()
    page_size = 10
    chunk = cities[page * page_size:(page + 1) * page_size]
    rows = [[InlineKeyboardButton(name, callback_data=f"setup:city:{table}")]
            for name, table, lat, lon in chunk]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"setup:citypage:{page-1}"))
    if (page + 1) * page_size < len(cities):
        nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"setup:citypage:{page+1}"))
    if nav:
        rows.append(nav)
    text = "🏙 یەکەم شارەکەت هەڵبژێرە بۆ کاتەکانی بانگ:"
    if edit:
        return update.callback_query.edit_message_text(text, reply_markup=ik(rows))
    return update.effective_message.reply_text(text, reply_markup=ik(rows))


def setup_qari_menu(update, page=0, edit=False, settings=False):
    reciters = [r for r in load_json("dangakan")
                if isinstance(r, dict) and str(r.get("doxx", "")).lower() == "true" and r.get("url")]
    page_size = 10
    chunk = reciters[page * page_size:(page + 1) * page_size]
    prefix = "st:qari" if settings else "setup:reciter"
    rows = []
    for item in chunk:
        rid = str(item.get("id", ""))
        name = str(item.get("name_ar") or f"قاری {rid}").strip()
        timing = "🕒" if (DATA / "recitation_timings" / f"{rid}.db").is_file() else "—"
        rows.append([InlineKeyboardButton(f"{timing} {name}"[:58], callback_data=f"{prefix}:{rid}")])
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"st:qpage:{page-1}" if settings else f"setup:qpage:{page-1}"))
    if (page + 1) * page_size < len(reciters):
        nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"st:qpage:{page+1}" if settings else f"setup:qpage:{page+1}"))
    if nav:
        rows.append(nav)
    text = "🎙️ قاریی دڵخوازت هەڵبژێرە\n🕒 = داتای کاتی ئایەت بەردەستە"
    if edit:
        return update.callback_query.edit_message_text(text, reply_markup=ik(rows))
    return update.effective_message.reply_text(text, reply_markup=ik(rows))


async def finish_setup(update, uid, qari_id, settings=False):
    set_qari(uid, str(qari_id))
    set_setup_completed(uid, True)
    if settings:
        return await update.callback_query.edit_message_text("✅ قاریی دڵخوازت پاشەکەوت کرا.")
    await update.callback_query.edit_message_text(
        "✅ ڕێکخستنەکانت پاشەکەوت کران. لە داهاتوودا داوایان لێ ناکرێتەوە؛ "
        "هەر کاتێک بتەوێت لە ⚙️ ڕێکخستن دەستکارییان بکە."
    )
    await update.effective_message.reply_text("🕌 بەخێربێیت بۆ ڕێگای ئیسلام.", reply_markup=main_keyboard(update.effective_user.id))

async def show_favorites(update, context=None):
    uid = update.effective_user.id
    rows = list_favorites(uid)
    if not rows:
        return await update.effective_message.reply_text(
            "⭐ هێشتا هیچ ناوەڕۆکێکت زیاد نەکردووە بۆ دڵخوازەکان.",
            reply_markup=ik([[InlineKeyboardButton("📖 کردنەوەی قورئان", callback_data="q:s:0")]]))
    buttons = []
    for fid, sid, ayah, title in rows:
        buttons.append([
            InlineKeyboardButton(f"⭐ {title}"[:58], callback_data=(f"fvc:open:{sid}:{ayah}" if int(sid) < 0 else f"fv:open:{sid}:{ayah}")),
            InlineKeyboardButton("🗑", callback_data=f"fv:del:{fid}")
        ])
    await update.effective_message.reply_text(
        f"⭐ *دڵخوازەکانت*\n{len(rows)} دانە — بۆ کردنەوە ناوەکە هەڵبژێرە.",
        reply_markup=ik(buttons), parse_mode=ParseMode.MARKDOWN)


async def show_last_read(update, context=None):
    row = get_last_read(update.effective_user.id)
    if not row:
        return await update.effective_message.reply_text(
            "📍 هێشتا شوێنی خوێندنەوەیەکت تۆمار نەکراوە. سوڕەتێک بکەرەوە و خوێندنەوەت دەست پێ بکە.")
    await show_ayahs(update, int(row[0]), int(row[1]))


async def show_menu_order(update, edit=False):
    uid = update.effective_user.id
    saved = get_menu_order(uid)
    order = [key for key in saved if key in MENU_ITEMS]
    order += [key for key in DEFAULT_MENU_ORDER if key not in order]
    rows = []
    for index, key in enumerate(order):
        controls = []
        if index:
            controls.append(InlineKeyboardButton("⬆️", callback_data=f"mo:up:{key}"))
        if index < len(order)-1:
            controls.append(InlineKeyboardButton("⬇️", callback_data=f"mo:down:{key}"))
        rows.append([InlineKeyboardButton(f"{index+1}. {MENU_ITEMS[key]}", callback_data="mo:done")] + controls)
    rows.append([InlineKeyboardButton("✅ تەواو", callback_data="mo:done")])
    message = "↕️ ڕێکخستنی مێنیو\n\nبە دوگمەی ⬆️ و ⬇️ شوێنی هەر بەشێک بگۆڕە. گۆڕانکارییەکان خۆکارانە پاشەکەوت دەکرێن."
    if edit:
        await update.callback_query.edit_message_text(message, reply_markup=ik(rows))
    else:
        await update.effective_message.reply_text(message, reply_markup=ik(rows))


async def show_settings(update, context=None):
    uid = update.effective_user.id
    city = get_city(uid)
    city_label = city_display_name(city) if city else "دیاری نەکراوە"
    qari_id = get_qari(uid)
    qari = next((r.get("name_ar", "نەزانراو") for r in load_json("dangakan")
                 if isinstance(r, dict) and str(r.get("id")) == str(qari_id)), "هەڵنەبژێردراو")
    row = get_tasbih(uid, get_tasbih_zikr(uid))
    tasbih_count = row[0] if row else 0
    notifications = get_prayer_notifications(uid)
    notify_label = "🟢 چالاکە" if notifications else "🔴 ناچالاکە"
    notify_action = "off" if notifications else "on"
    await update.effective_message.reply_text(
        f"⚙️ *ڕێکخستنەکانی من*\n\n🏙 شاری هەڵبژێردراو: {city_label}\n🎙️ قاری: {qari}\n📿 ژمارەی تەسبیح: {tasbih_count}\n🔔 ئاگادارکردنەوەی کاتی بانگ: {notify_label}\n\nشار و قارییەکەت پاشەکەوت دەکرێن و دەتوانیت لێرە بیگۆڕیت.",
        reply_markup=ik([
            [InlineKeyboardButton("🏙 گۆڕینی شار", callback_data="st:city")],
            [InlineKeyboardButton("🎙️ گۆڕینی قاری", callback_data="st:qari:menu")],
            [InlineKeyboardButton(("🔕 ناچالاککردنی ئاگادارکردنەوە" if notifications else "🔔 چالاککردنی ئاگادارکردنەوە"), callback_data=f"st:notify:{notify_action}")],
            [InlineKeyboardButton("⭐ دڵخوازەکان", callback_data="fv:list")],
            [InlineKeyboardButton("📍 دوا خوێندنەوە", callback_data="lr")],
            [InlineKeyboardButton("↕️ ڕێکخستنی شوێنی بەشەکان", callback_data="mo:open")]
        ]), parse_mode=ParseMode.MARKDOWN)


def city_display_name(city):
    if not city:
        return "دیاری نەکراوە"
    return next((str(item.get("Name")) for item in load_json("cityme")
                 if isinstance(item, dict) and str(item.get("id", "")).casefold() == str(city).casefold()), str(city))


def get_cities():
    # The Android app keeps Kurdish display names in cityme.json and table IDs in the prayer DB.
    mapping={x.get("Name"):x.get("id") for x in load_json("cityme") if isinstance(x,dict)}
    with db("katenwezh62.db") as c:
        coords={r[0]:(r[1],r[2]) for r in c.execute("SELECT city,latitude,longitude FROM cities")}
        tables={r[0].casefold():r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return [(name,tables.get(str(mapping.get(name) or "").casefold()),*(coords.get(name,(None,None))) ) for name in mapping if tables.get(str(mapping.get(name) or "").casefold())]

async def show_suras(update, page=0, edit=False):
    with db("surat.db") as c: rows=c.execute("SELECT soraid,name,aya,place FROM surat ORDER BY soraid").fetchall()
    chunk=rows[page*12:(page+1)*12]
    buttons=[]
    for sid,name,aya,place in chunk:
        buttons.append([InlineKeyboardButton(f"{sid}. {name} ({aya})", callback_data=f"q:a:{sid}:0")])
    nav=[]
    if page: nav.append(InlineKeyboardButton("⬅️ پێشوو",callback_data=f"q:s:{page-1}"))
    if (page+1)*12 < len(rows): nav.append(InlineKeyboardButton("دواتر ➡️",callback_data=f"q:s:{page+1}"))
    if nav: buttons.append(nav)
    markup=ik(buttons)
    text=f"📖 *سوڕەتەکانی قورئانی پیرۆز*\nلاپەڕە {page+1} لە 10 — سوڕەتێک هەڵبژێرە:"
    if edit: await update.callback_query.edit_message_text(text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)
    else: await update.effective_message.reply_text(text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)

async def show_mushaf_menu(update, context):
    context.user_data["mushaf_waiting_page"] = True
    await update.effective_message.reply_text(
        "📖 مصحەف\n\nسووڕەتێک هەڵبژێرە، یان ژمارەی پەڕەکە لە ١ تا ٦٠٤ بنووسە:",
        reply_markup=ik([[InlineKeyboardButton("📚 هەڵبژاردنی سووڕەت", callback_data="ms:list")]])
    )


async def show_mushaf_surah_list(update, page=0, edit=False):
    with db("surat.db") as conn:
        rows = conn.execute("SELECT soraid,name,aya FROM surat ORDER BY soraid").fetchall()
    chunk = rows[page*12:(page+1)*12]
    buttons = [[InlineKeyboardButton(f"{sid}. {name}", callback_data=f"ms:{sid}")]
               for sid, name, _ in chunk]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"ms:list:{page-1}"))
    if (page+1)*12 < len(rows):
        nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"ms:list:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("✍️ نووسینی ژمارەی پەڕە", callback_data="ms:number")])
    message = "📖 مصحەف — سووڕەتێک هەڵبژێرە:"
    if edit:
        await update.callback_query.edit_message_text(message, reply_markup=ik(buttons))
    else:
        await update.effective_message.reply_text(message, reply_markup=ik(buttons))


async def show_mushaf_surah_pages(update, sid, page=0, edit=False):
    info_path = DATA / "recitation_timings" / "ayah_info.db"
    with db("regayislam.db") as conn:
        conn.execute("ATTACH DATABASE ? AS info", (f"file:{info_path}?mode=ro",))
        bounds = conn.execute(
            "SELECT MIN(page_number), MAX(page_number) FROM info.page_data_line WHERE surah_id=?",
            (sid,),
        ).fetchone()
    if not bounds or bounds[0] is None:
        return await update.effective_message.reply_text("پەڕەکانی ئەم سووڕەتە لە داتابەیسدا نەدۆزرایەوە.")
    first, last = int(bounds[0]), int(bounds[1])
    page_size = 20
    pages = list(range(first, last+1))
    chunk = pages[page*page_size:(page+1)*page_size]
    with db("surat.db") as conn:
        row = conn.execute("SELECT name FROM surat WHERE soraid=?", (sid,)).fetchone()
    name = row[0] if row else f"سووڕەتی {sid}"
    buttons = [[InlineKeyboardButton(f"📄 پەڕەی {number}", callback_data=f"mpg:{number}")]
               for number in chunk]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"msp:{sid}:{page-1}"))
    if (page+1)*page_size < len(pages):
        nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"msp:{sid}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 لیستی سووڕەتەکان", callback_data="ms:list:0")])
    message = f"📖 سووڕەتی {name}\nپەڕەکان: {first} تا {last}\nپەڕەیەک هەڵبژێرە:"
    if edit:
        await update.callback_query.edit_message_text(message, reply_markup=ik(buttons))
    else:
        await update.effective_message.reply_text(message, reply_markup=ik(buttons))


async def show_quran_page(update, page=1, edit=False):
    """Show the requested Mushaf page from the supplied page-image collection."""
    page = max(1, min(604, int(page)))
    image_url = (
        "https://raw.githubusercontent.com/H4zh4n/TafseeriNoor/"
        "82a7765441154b14174a9181ad338b0949815d29/images/"
        f"page{page:03d}.png"
    )
    caption = f"📖 مصحەفی قورئانی پیرۆز — پەڕەی {page}/604"
    progress = await update.effective_message.reply_text(
        f"⏳ پەڕەی {page} ئامادە دەکرێت...\\n📥 وەرگرتنی زانیاریی پەڕە"
    )

    # Keep the page-to-ayah map for last-read tracking and the reciter shortcut.
    with db("regayislam.db") as conn:
        info_path = DATA / "recitation_timings" / "ayah_info.db"
        conn.execute("ATTACH DATABASE ? AS info", (f"file:{info_path}?mode=ro",))
        rows = conn.execute(
            """
            SELECT p.surah_id,p.verse_id
            FROM info.page_data_line p
            WHERE p.page_number=?
            ORDER BY p.line_number,p.surah_id,p.verse_id
            LIMIT 1
            """,
            (page,),
        ).fetchone()

    buttons = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ پەڕەی پێشوو", callback_data=f"qp:{page-1}"))
    if page < 604:
        nav.append(InlineKeyboardButton("پەڕەی داهاتوو ➡️", callback_data=f"qp:{page+1}"))
    if nav:
        buttons.append(nav)
    if rows:
        save_last_read(update.effective_user.id, rows[0], max(0, int(rows[1]) - 1))
        buttons.append([InlineKeyboardButton("🎧 گوێگرتن بە قاریی هەڵبژێردراو", callback_data=f"qaudio:{rows[0]}")])
    buttons.append([InlineKeyboardButton("📚 لیستی سووڕەتەکان", callback_data="ms:list:0")])
    markup = ik(buttons)

    try:
        await progress.edit_text(
            f"⏳ پەڕەی {page} ئامادە دەکرێت...\\n📤 ناردنی وێنە بۆ تێلێگرام"
        )
        photo = io.BytesIO(await asyncio.to_thread(
            download_remote_bytes, image_url, 12 * 1024 * 1024, 25
        ))
        photo.name = f"mushaf-page-{page:03d}.png"
        if edit:
            # Telegram cannot turn a text message into a photo by editing its media.
            sent = await update.effective_message.reply_photo(
                photo=photo, caption=caption, reply_markup=markup
            )
            try:
                await update.effective_message.delete()
            except Exception:
                log.warning("Could not remove previous Mushaf navigation message")
        else:
            photo.seek(0)
            sent = await update.effective_message.reply_photo(
                photo=photo, caption=caption, reply_markup=markup
            )
        try:
            await progress.delete()
        except Exception:
            pass
        return sent
    except Exception:
        try:
            await progress.edit_text("⚠️ ناردنی وێنەی پەڕەکە سەرکەوتوو نەبوو؛ تکایە دووبارە هەوڵ بدەرەوە.")
        except Exception:
            pass
        raise

async def send_ayat_kursi_audio(update, context):
    audio_url = "https://cdn.islamic.network/quran/audio/128/ar.alafasy/262.mp3"
    status = await update.effective_message.reply_text("⏳ دەنگی ئایەتی کورسی دادەبەزێت...\\n📥 وەرگرتنی فایل")
    try:
        def download():
            request = urllib.request.Request(audio_url, headers={"User-Agent": "Regay-Islam-Telegram-Bot/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(15*1024*1024+1)
            if not data or len(data) > 15*1024*1024:
                raise ValueError("Ayat audio file is empty or too large")
            return data
        data = await asyncio.to_thread(download)
        await status.edit_text("✅ دەنگەکە وەرگیرا.\\n📤 ئێستا بۆ تێلێگرام دەنێردرێت...")
        audio = io.BytesIO(data)
        audio.name = "ayat-al-kursi.mp3"
        await context.bot.send_audio(chat_id=update.effective_chat.id, audio=audio, title="Ayat al-Kursi — Mishary Alafasy", performer="مشاري العفاسي", caption="🕋 ئایەتی کورسی — البقرة ٢:٢٥٥")
        await status.delete()
    except Exception:
        log.exception("Ayat al-Kursi audio delivery failed")
        try:
            await status.edit_text("⚠️ ناردنی دەنگی ئایەتی کورسی سەرکەوتوو نەبوو.")
        except Exception:
            pass


async def show_ayat_kursi(update):
    """Open Ayat al-Kursi directly from the original Quran database."""
    with db("regayislam.db") as conn:
        row = conn.execute(
            "SELECT sura_name_ar,ayah,text FROM ayah_text WHERE suraId=2 AND ayah=255"
        ).fetchone()
    if not row:
        return await update.effective_message.reply_text("ئایەتی کورسی لە داتابەیسی قورئاندا نەدۆزرایەوە.")
    name, ayah, arabic = row
    await update.effective_message.reply_text(
        f"🕋 *ئایەتی کورسی — {name}، {ayah}*\n\n{arabic}",
        reply_markup=ik([
            [InlineKeyboardButton("🔊 گوێگرتن بە دەنگی ئایەتی کورسی", callback_data="kursi:audio")],
            [InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان", callback_data="fv:add:2:255")]
        ]),
        parse_mode=ParseMode.MARKDOWN,
    )


async def show_ayahs(update, sid, offset=0, edit=False):
    save_last_read(update.effective_user.id, sid, offset)
    with db("regayislam.db") as c:
        rows=c.execute("SELECT sura_name_ar,ayah,text,rebar,raman,puxta,asan,sanahi,hazhar,zhin,maiser,roshn,tawhid FROM ayah_text WHERE suraId=? ORDER BY ayah LIMIT 8 OFFSET ?",(sid,offset)).fetchall()
    if not rows:
        msg="ئەم سوڕەتە نەدۆزرایەوە."
        if edit: await update.callback_query.edit_message_text(msg)
        else: await update.effective_message.reply_text(msg)
        return
    name=rows[0][0]
    parts=[f"📖 *{name}*\nئایەتەکان {offset+1} تا {offset+len(rows)}\n"]
    buttons=[]
    for row in rows:
        _,ayah,arabic,*_=row
        parts.append(f"*{ayah}.* {arabic}")
        buttons.append([InlineKeyboardButton(f"📖 ڕوونکردنەوەی ئایەتی {ayah}",callback_data=f"q:t:{sid}:{ayah}"), InlineKeyboardButton("⭐",callback_data=f"fv:add:{sid}:{ayah}")])
    nav=[]
    if offset>0: nav.append(InlineKeyboardButton("⬅️ پێشوو",callback_data=f"q:a:{sid}:{max(0,offset-8)}"))
    with db("surat.db") as c: total=c.execute("SELECT aya FROM surat WHERE soraid=?",(sid,)).fetchone()[0]
    if offset+8<total: nav.append(InlineKeyboardButton("دواتر ➡️",callback_data=f"q:a:{sid}:{offset+8}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("🎧 گوێگرتن بە قاریی هەڵبژێردراو", callback_data=f"qaudio:{sid}")])
    buttons.append([InlineKeyboardButton("🔙 لیستی سوڕەتەکان",callback_data="q:s:0")])
    text="\n\n".join(parts)
    if edit: await update.callback_query.edit_message_text(text,reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)
    else: await update.effective_message.reply_text(text,reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)

async def show_tafsir(update,sid,ayah,selected=None):
    save_last_read(update.effective_user.id, sid, ((ayah-1)//8)*8)
    with db("regayislam.db") as c:
        r=c.execute("SELECT sura_name_ar,text,rebar,raman,puxta,asan,sanahi,hazhar,zhin,maiser,roshn,tawhid FROM ayah_text WHERE suraId=? AND ayah=?",(sid,ayah)).fetchone()
    if not r: return await update.callback_query.answer("ئایەت نەدۆزرایەوە",show_alert=True)
    options = [
        ("تەفسیری ڕێبەر", "rebar"), ("تەفسیری ڕامان", "raman"),
        ("پوختەی تەفسیر", "puxta"), ("تەفسیری ئاسان", "asan"),
        ("تەفسیری سەناهی", "sanahi"), ("تەفسیری هەژار", "hazhar"),
        ("تەفسیری ژین", "zhin"), ("تەفسیری مایسەر", "maiser"),
        ("تەفسیری ڕۆشن", "roshn"), ("تەفسیری تەوحید", "tawhid"),
    ]
    fields = r[2:]
    surah_title = str(r[0] or "").strip()
    if not surah_title.startswith("سوڕەتی "):
        surah_title = "سوڕەتی " + surah_title
    heading = f"📖 {surah_title}، ئایەتی {ayah}"
    buttons = []
    if selected is None:
        available = [(i, label, value) for i, ((label, _), value) in enumerate(zip(options, fields))
                     if value and str(value).strip()]
        if available:
            index, label, value = available[0]
            body = f"*{label}*\n\n{str(value)[:2600]}"
        else:
            body = "هیچ تەفسیرێک بۆ ئەم ئایەتە تۆمار نەکراوە."
    elif selected == -1:
        sections = [f"*{label}*\n{str(value)[:850]}" for (label, _), value in zip(options, fields)
                    if value and str(value).strip()]
        body = "\n\n".join(sections) if sections else "هیچ تەفسیرێک بۆ ئەم ئایەتە تۆمار نەکراوە."
    else:
        label, _ = options[selected]
        value = fields[selected]
        body = f"*{label}*\n\n{str(value)[:2600]}" if value and str(value).strip() else f"*{label}*\nئەم تەفسیرە بۆ ئەم ئایەتە بەتاڵە."
    text = f"{heading}\n\n{r[1]}\n\n{body}"
    buttons.append([InlineKeyboardButton("هەموو ١٠ تەفسیر", callback_data=f"q:tf:{sid}:{ayah}:-1")])
    buttons.extend([[InlineKeyboardButton(label, callback_data=f"q:tf:{sid}:{ayah}:{i}")]
                    for i, (label, _) in enumerate(options)])
    buttons.append([InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان", callback_data=f"fv:add:{sid}:{ayah}")])
    buttons.append([InlineKeyboardButton("🔙 گەڕانەوە بۆ ئایەتەکان", callback_data=f"q:a:{sid}:{((ayah-1)//8)*8}")])
    await update.effective_message.reply_text(text[:3900], reply_markup=ik(buttons),
                                              parse_mode=ParseMode.MARKDOWN,
                                              disable_web_page_preview=True)

async def prayer_city_list(update, page=0, edit=False, mode="prayer"):
    cities=get_cities(); chunk=cities[page*12:(page+1)*12]
    prefix = "mc" if mode == "month" else "pc"
    rows=[[InlineKeyboardButton(name,callback_data=f"{prefix}:{table}")] for name,table,lat,lon in chunk]
    nav=[]
    if page: nav.append(InlineKeyboardButton("⬅️",callback_data=f"pcl:{mode}:{page-1}"))
    if (page+1)*12<len(cities): nav.append(InlineKeyboardButton("➡️",callback_data=f"pcl:{mode}:{page+1}"))
    if nav: rows.append(nav)
    text="🕌 *شارەکەت هەڵبژێرە بۆ کاتەکانی بانگ:*"
    if edit: await update.callback_query.edit_message_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)
    else: await update.effective_message.reply_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)

def hijri_date_for(gregorian_date):
    y, m, d = gregorian_date.year, gregorian_date.month, gregorian_date.day
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    jd = d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045
    hy = (30 * (jd - 1948440) + 10646) // 10631
    def islamic_jd(year, month):
        return math.ceil(29.5 * (month - 1)) + (year - 1) * 354 + (3 + 11 * year) // 30 + 1948439
    hm = 1
    for candidate in range(1, 13):
        if islamic_jd(hy, candidate) <= jd:
            hm = candidate
        else:
            break
    hd = jd - islamic_jd(hy, hm) + 1
    months = ["محەڕەم", "سەفەر", "ڕەبیعی یەکەم", "ڕەبیعی دووەم", "جومادای یەکەم", "جومادای دووەم", "ڕەجەب", "شەعبان", "ڕەمەزان", "شەوال", "زولقەعدە", "زولحیججە"]
    return f"{hd}ی {months[hm-1]} {hy} کۆچی"


def dual_date_lines(value):
    return f"📅 زاینی: {value:%Y-%m-%d}\n🌙 هەجری: {hijri_date_for(value)}"


async def prayer_times(update, city, edit=False):
    city_display=city_display_name(city)
    with db("katenwezh62.db") as c:
        r=c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name=?",(city,)).fetchone()
        if not r:
            await update.effective_message.reply_text("کاتی بانگ بۆ ئەم شارە لە داتابەیسدا نییە."); return
        today=datetime.now(TZ).strftime("%m-%d")
        row=c.execute(f'SELECT D,bayani,xorhalatn,niwaro,asr,eywara,esha FROM "{city}" WHERE D=?',(today,)).fetchone()
        cityname=city_display
    if not row:
        msg="کاتی ئەم ڕۆژە لە خشتەی سەرچاوەدا نەدۆزرایەوە."
    else:
        labels=["بەیانی","خۆرهەڵاتن","نیوەڕۆ","عەسر","ئێوارە","عیشا"]
        msg=f"🕌 *کاتەکانی بانگ — {cityname}*\n{dual_date_lines(datetime.now(TZ).date())}\n\n"
        msg+='\n'.join(f"• {a}: *{b}*" for a,b in zip(labels,row[1:]))
        msg+="\n\n_کاتەکان وەک خشتەی ناو ئەپی ڕێگای ئیسلامن؛ پێش بەکارهێنان لەگەڵ کاتی مزگەوتی ناوچەکەت بەراوردیان بکە._"
    markup=ik([[InlineKeyboardButton("🔄 گۆڕینی شار",callback_data="pcl:prayer:0")]])
    if edit: await update.callback_query.edit_message_text(msg,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)
    else: await update.effective_message.reply_text(msg,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)

async def monthly_prayer_times(update, city=None, month=None, edit=False):
    """Show the original Android app's month-view prayer timetable."""
    if not city:
        city = get_city(update.effective_user.id)
    if not city:
        await prayer_city_list(update, mode="month")
        return
    now = datetime.now(TZ)
    try:
        month_date = date.fromisoformat(month + "-01") if month else now.date().replace(day=1)
    except ValueError:
        month_date = now.date().replace(day=1)
    month_key = month_date.strftime("%m")
    city_display = city_display_name(city)
    days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
    with db("katenwezh62.db") as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (city,)
        ).fetchone()
        if not exists:
            return await update.effective_message.reply_text("خشتەی بانگ بۆ ئەم شارە بەردەست نییە.")
        rows = conn.execute(
            f'SELECT D,bayani,xorhalatn,niwaro,asr,eywara,esha FROM "{city}" WHERE D LIKE ? ORDER BY ID',
            (month_key + "-%",),
        ).fetchall()
    by_day = {int(str(row[0]).split("-")[1]): row[1:] for row in rows}
    lines = [
        f"🗓 *کاتەکانی بانگی مانگانە — {city_display}*",
        f"📅 زاینی: {month_date:%Y-%m} — هەجری: {hijri_date_for(month_date)}",
        "",
        "ڕۆژ | بەیانی | خۆرهەڵاتن | نیوەڕۆ | عەسر | ئێوارە | عیشا",
    ]
    for day in range(1, days_in_month + 1):
        times = by_day.get(day)
        if times:
            lines.append(f"{day:02d} | " + " | ".join(str(value or "—")[:5] for value in times))
    previous = (month_date - timedelta(days=1)).replace(day=1)
    next_month = (month_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    nav = [
        InlineKeyboardButton("⬅️ مانگی پێشوو", callback_data=f"pm:{previous:%Y-%m}"),
        InlineKeyboardButton("مانگی داهاتوو ➡️", callback_data=f"pm:{next_month:%Y-%m}"),
    ]
    markup = ik([nav, [InlineKeyboardButton("🏙 گۆڕینی شار", callback_data="pcl:month:0")]])
    message = "\n".join(lines) + "\n\n_کاتەکان لە خشتەی ساڵانەی ئەپی سەرچاوەوە وەرگیراون؛ لەگەڵ مزگەوتی ناوچەکەت بەراوردیان بکە._"
    if edit:
        await update.callback_query.edit_message_text(message[:3900], reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_message.reply_text(message[:3900], reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def send_asset_file(update, context, item):
    """Download media, show progress, then upload the actual file to Telegram."""
    url = str(item.get("link") or item.get("url") or "").strip()
    if not url.startswith(("https://", "http://")):
        await update.effective_message.reply_text("⚠️ لینکی دروستی بۆ ئەم فایلە بەردەست نییە.")
        return False
    filename = str(item.get("namefile") or url.split("?", 1)[0].rsplit("/", 1)[-1] or "file").strip()
    suffix = Path(filename).suffix.lower()
    title = str(item.get("title") or item.get("name") or filename).strip()
    status = await update.effective_message.reply_text(
        f"⏳ فایلەکەی «{title[:100]}» دادەبەزێت و ئامادەی ناردن دەکرێت؛ تکایە چاوەڕێ بکە..."
    )
    downloaded = False
    try:
        def download_asset():
            request = urllib.request.Request(url, headers={"User-Agent": "Regay-Islam-Telegram-Bot/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read(50 * 1024 * 1024 + 1)
            if not payload:
                raise ValueError("The remote server returned an empty file")
            if len(payload) > 50 * 1024 * 1024:
                raise ValueError("The file exceeds the 50 MB Telegram bot upload limit")
            return payload

        payload = await asyncio.to_thread(download_asset)
        downloaded = True
        await status.edit_text("📤 فایلەکە ئامادەیە؛ ئێستا بۆ تێلێگرام دەنێردرێت...")
        stream = io.BytesIO(payload)
        stream.name = filename
        chat_id = update.effective_chat.id
        if suffix in (".mp3", ".m4a", ".wav", ".ogg", ".flac"):
            await context.bot.send_audio(chat_id=chat_id, audio=stream, caption=title[:1024], title=title[:64])
        elif suffix in (".mp4", ".mov", ".m4v"):
            await context.bot.send_video(chat_id=chat_id, video=stream, caption=title[:1024], supports_streaming=True)
        elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
            await context.bot.send_photo(chat_id=chat_id, photo=stream, caption=title[:1024])
        else:
            await context.bot.send_document(chat_id=chat_id, document=stream, caption=title[:1024], filename=filename)
        try:
            await status.delete()
        except Exception:
            pass
        return True
    except Exception as exc:
        log.exception("Could not download/send asset %s from %s", filename, url)
        if isinstance(exc, HTTPError):
            if exc.code == 404:
                message = "⚠️ فایل لە سێرڤەرەکەدا نەدۆزرایەوە (404). لینکی فایلەکە پێویستی بە پشکنین هەیە."
            else:
                message = f"⚠️ سێرڤەری فایلەکە وەڵامی نادروستی دا (HTTP {exc.code})."
        elif isinstance(exc, URLError) or isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            message = "⚠️ پەیوەندی بە سێرڤەری فایلەکەوە پچڕا یان کاتی چاوەڕوانی تەواو بوو. تکایە دواتر هەوڵ بدە."
        elif isinstance(exc, ValueError):
            message = "⚠️ فایلەکە بەتاڵە یان لە سنووری قەبارەی ڕێگەپێدراوی Telegram گەورەترە."
        elif downloaded:
            message = "⚠️ فایلەکە بە سەرکەوتوویی دابەزێنرا، بەڵام Telegram نەیتوانی بینێرێت. قەبارە یان جۆری فایلەکە پشکنین بکە."
        else:
            message = "⚠️ لە کاتی دابەزاندنی فایلەکەدا هەڵەیەک ڕوویدا. هۆکاری ورد لە لۆگی بۆتەکە تۆمار کراوە."
        try:
            await status.edit_text(message)
        except Exception:
            await update.effective_message.reply_text(message)
        return False


async def show_json_item(update,context,key,index,edit=False):
    data=load_json(key)
    if not data: return await update.effective_message.reply_text("ناوەڕۆک بەردەست نییە.")
    index=max(0,min(index,len(data)-1)); item=data[index]
    if isinstance(item,dict):
        title=item.get('title') or item.get('name') or item.get('name_ar') or f"{JSON_FILES[key][0]} — {index+1}"
        asset_url=item.get('link') or item.get('url')
        asset_name=str(item.get('namefile') or asset_url or '').split('?',1)[0].lower()
        is_asset=str(item.get('type') or '').upper()=='ASSET' or (asset_url and Path(asset_name).suffix.lower() in {'.mp3','.m4a','.wav','.ogg','.flac','.mp4','.mov','.m4v','.pdf','.doc','.docx','.xls','.xlsx','.ppt','.pptx','.jpg','.jpeg','.png','.webp'})
        if is_asset:
            await send_asset_file(update,context,item)
            nav=[]
            if index>0: nav.append(InlineKeyboardButton("⬅️ پێشوو",callback_data=f"j:{key}:{index-1}"))
            if index+1<len(data): nav.append(InlineKeyboardButton("دواتر ➡️",callback_data=f"j:{key}:{index+1}"))
            rows=[nav] if nav else []
            rows.append([InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان",callback_data=f"fvc:add:{-100-list(JSON_FILES).index(key)}:{index}")])
            rows.append([InlineKeyboardButton("🔙 لیستی بابەتەکان",callback_data=f"jl:{key}:0")])
            await update.effective_message.reply_text(f"📎 {title}",reply_markup=ik(rows))
            return
        body=item.get('text') or item.get('desc') or item.get('wata') or item.get('du3a') or item.get('tag') or ""
        translation=item.get('text2') or ""
        text=f"*{title}*"
        if body:
            text += f"\n\n{body}"
        if translation:
            text += f"\n\n{translation}"
        if not body and not translation:
            text += "\n\nناوەڕۆکی ئەم بابەتە بەردەست نییە."
    else:
        text=f"*{JSON_FILES[key][0]}*\n\n{item}"
    nav=[]
    if index>0: nav.append(InlineKeyboardButton("⬅️ پێشوو",callback_data=f"j:{key}:{index-1}"))
    if index+1<len(data): nav.append(InlineKeyboardButton("دواتر ➡️",callback_data=f"j:{key}:{index+1}"))
    rows=[nav] if nav else []
    rows.append([InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان",callback_data=f"fvc:add:{-100-list(JSON_FILES).index(key)}:{index}")])
    rows.append([InlineKeyboardButton("🔙 لیستی بابەتەکان",callback_data=f"jl:{key}:0")])
    if edit: await update.callback_query.edit_message_text(text[:3900],reply_markup=ik(rows),disable_web_page_preview=True)
    else: await update.effective_message.reply_text(text[:3900],reply_markup=ik(rows),disable_web_page_preview=True)


async def json_list(update,key,page=0,edit=False):
    data=load_json(key); title=JSON_FILES[key][0]
    rows=[]
    for i,item in enumerate(data[page*12:(page+1)*12],start=page*12):
        if isinstance(item,dict): label=item.get('title') or item.get('name') or item.get('name_ar') or f"بابەت {i+1}"
        else: label=f"بابەت {i+1}"
        rows.append([InlineKeyboardButton(str(label)[:58],callback_data=f"j:{key}:{i}")])
    nav=[]
    if page: nav.append(InlineKeyboardButton("⬅️",callback_data=f"jl:{key}:{page-1}"))
    if (page+1)*12<len(data): nav.append(InlineKeyboardButton("➡️",callback_data=f"jl:{key}:{page+1}"))
    if nav: rows.append(nav)
    text=f"📚 *{title}*\n{len(data)} بابەت — لاپەڕە {page+1}"
    if edit: await update.callback_query.edit_message_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)
    else: await update.effective_message.reply_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)

async def show_qari_menu(update,page=0,edit=False):
    reciters=[r for r in load_json("dangakan") if isinstance(r,dict) and str(r.get("doxx"," ")).lower()=="true" and r.get("url")]
    start=page*10
    rows=[]
    selected_qari = get_qari(update.effective_user.id)
    for i,item in enumerate(reciters[start:start+10],start=start):
        label=str(item.get("name_ar") or f"قاری {i+1}").strip()
        if str(item.get("id")) == str(selected_qari):
            label = "⭐ قاریی من — " + label
        rows.append([InlineKeyboardButton(label[:58],callback_data=f"qr:pick:{i}")])
    nav=[]
    if page: nav.append(InlineKeyboardButton("⬅️ پێشوو",callback_data=f"qr:list:{page-1}"))
    if start+10<len(reciters): nav.append(InlineKeyboardButton("دواتر ➡️",callback_data=f"qr:list:{page+1}"))
    if nav: rows.append(nav)
    text=f"🎙️ *قارییەکانی قورئانی پیرۆز*\n{len(reciters)} قاری — قارییەک هەڵبژێرە:"
    if edit: await update.callback_query.edit_message_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)
    else: await update.effective_message.reply_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)

async def show_qari_surahs(update,index):
    reciters=[r for r in load_json("dangakan") if isinstance(r,dict) and str(r.get("doxx"," ")).lower()=="true" and r.get("url")]
    if index<0 or index>=len(reciters): return await update.callback_query.answer("قاری نەدۆزرایەوە",show_alert=True)
    item=reciters[index]
    with db("surat.db") as c: surahs=c.execute("SELECT soraid,name,aya FROM surat ORDER BY soraid").fetchall()
    rows=[[InlineKeyboardButton(f"{sid}. {name} ({count} ئایەت)",callback_data=f"qr:play:{index}:{sid}")] for sid,name,count in surahs]
    rows.append([InlineKeyboardButton("🔙 گەڕانەوە بۆ قارییەکان",callback_data="qr:list:0")])
    title=str(item.get("name_ar") or "قاری").strip()
    await update.callback_query.edit_message_text(f"🎙️ *{title}*\n\nسوڕەتێک هەڵبژێرە بۆ گوێگرتن:",reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)

async def qari_ayah_guide(update, reciter_id, sid, page=0, edit=False):
    with db("surat.db") as conn:
        surah = conn.execute("SELECT name,aya FROM surat WHERE soraid=?", (sid,)).fetchone()
    if not surah:
        return await update.effective_message.reply_text("سوڕەتەکە نەدۆزرایەوە.")
    timing_path = DATA / "recitation_timings" / f"{reciter_id}.db"
    if not timing_path.is_file():
        text = "⚠️ داتای کاتی ئایەت بۆ ئەم قارییە بەردەست نییە."
        if edit:
            return await update.callback_query.edit_message_text(text)
        return await update.effective_message.reply_text(text)
    with sqlite3.connect(f"file:{timing_path}?mode=ro", uri=True) as conn:
        timings = conn.execute(
            "SELECT ayah,time FROM timings WHERE sura=? AND ayah BETWEEN 1 AND ? ORDER BY ayah LIMIT 8 OFFSET ?",
            (sid, int(surah[1]), page * 8)
        ).fetchall()
    if not timings:
        text = "کاتی ئایەت بۆ ئەم سوڕەتە نەدۆزرایەوە."
        if edit:
            return await update.callback_query.edit_message_text(text)
        return await update.effective_message.reply_text(text)
    with db("regayislam.db") as conn:
        verses = dict(conn.execute(
            "SELECT ayah,text FROM ayah_text WHERE suraId=? AND ayah BETWEEN ? AND ?",
            (sid, timings[0][0], timings[-1][0])
        ).fetchall())
    lines = [
        f"📖 *هاوکاتی ئایەت و دەنگ — {surah[0]}*",
        "_کاتەکان لە سەرەتای فایلەکەوە بە چرکە ژمێردراون. Telegram ڕێگە نادات بۆت شوێنی پەخشکردنی دەنگ بە شێوەی ڕاستەوخۆ بزانێت؛ ئەم لیستە کاتی هەر ئایەت و دەقی ئەو ئایەتە پیشان دەدات._",
        ""
    ]
    for ayah, milliseconds in timings:
        seconds = max(0, int(milliseconds)) // 1000
        stamp = f"{seconds // 60:02d}:{seconds % 60:02d}"
        lines.append(f"*{stamp}* — ﴿{ayah}﴾ {verses.get(ayah, '')}")
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"qg:{reciter_id}:{sid}:{page-1}"))
    if (page + 1) * 8 < int(surah[1]):
        nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"qg:{reciter_id}:{sid}:{page+1}"))
    markup = ik([nav]) if nav else None
    text = "\n".join(lines)
    if edit:
        await update.callback_query.edit_message_text(text[:3900], reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_message.reply_text(text[:3900], reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

async def play_qari_surah(update,context,index,sid):
    reciters=[r for r in load_json("dangakan") if isinstance(r,dict) and str(r.get("doxx"," ")).lower()=="true" and r.get("url")]
    if index<0 or index>=len(reciters) or not 1<=sid<=114: return await update.callback_query.answer("زانیاریی دەنگ نەدۆزرایەوە",show_alert=True)
    item=reciters[index]
    base=str(item.get("url"," ")).strip()
    if not base.startswith(("https://","http://")): return await update.callback_query.answer("لینکی دەنگ نادروستە",show_alert=True)
    audio_url=base.rstrip("/")+f"/{sid:03d}.mp3"
    with db("surat.db") as c: row=c.execute("SELECT name FROM surat WHERE soraid=?",(sid,)).fetchone()
    surah_name=row[0] if row else f"سوڕەت {sid}"
    qari_name=str(item.get("name_ar") or "قاری").strip()
    status = await update.effective_message.reply_text(
        f"⏳ دەنگی {surah_name} بە قاری {qari_name} ئامادە دەکرێت...\n📥 وەرگرتنی MP3"
    )
    try:
        # Download the MP3 first; Telegram URL fetching can fail on GitHub release redirects.
        def download_audio():
            request=urllib.request.Request(audio_url,headers={"User-Agent":"Regay-Islam-Telegram-Bot/1.0"})
            with urllib.request.urlopen(request,timeout=45) as response:
                data=response.read(50*1024*1024+1)
            if len(data)>50*1024*1024:
                raise ValueError("Audio file exceeds Telegram's 50 MB bot upload limit")
            if not data:
                raise ValueError("Empty audio response")
            return data
        audio_data=await asyncio.to_thread(download_audio)
        await status.edit_text("📤 دەنگەکە وەرگیرا؛ ئێستا بۆ تێلێگرام دەنێردرێت...")
        audio_file=io.BytesIO(audio_data)
        audio_file.name=f"{sid:03d}.mp3"
        await context.bot.send_audio(chat_id=update.effective_chat.id,audio=audio_file,title=f"{surah_name} — {qari_name}"[:64],performer=qari_name[:64],caption=f"📖 سوڕەتی {surah_name}\n🎙️ قاری: {qari_name}")
        try:
            await status.delete()
        except Exception:
            pass
        try:
            await qari_ayah_guide(update, str(item.get("id", "")), sid, 0)
        except Exception:
            log.exception("Audio was sent but the ayah timing guide could not be rendered")
    except Exception:
        log.exception("Could not download or send recitation audio: %s",audio_url)
        try:
            await status.edit_text("⚠️ ناردنی دەنگی قورئان سەرکەوتوو نەبوو؛ تکایە دواتر دووبارە هەوڵ بدەرەوە.",
                reply_markup=ik([[InlineKeyboardButton("🔙 گەڕانەوە بۆ سوڕەتەکان",callback_data=f"qr:pick:{index}")]]))
        except Exception:
            await update.effective_message.reply_text("⚠️ ناردنی دەنگی قورئان سەرکەوتوو نەبوو.")

async def play_default_qari(update, context, sid):
    selected_id = get_qari(update.effective_user.id)
    reciters = [r for r in load_json("dangakan")
                if isinstance(r, dict) and str(r.get("doxx", "")).lower() == "true" and r.get("url")]
    index = next((i for i, item in enumerate(reciters)
                  if str(item.get("id")) == str(selected_id)), None)
    if index is None:
        await update.effective_message.reply_text(
            "🎙️ سەرەتا قاریی دڵخوازت هەڵبژێرە:",
        )
        return await setup_qari_menu(update)
    return await play_qari_surah(update, context, index, sid)


async def firebase_video_profiles_menu(update):
    profiles = await firebase_video_profiles()
    if not profiles:
        return await update.effective_message.reply_text("هیچ پرۆفایلێک لە Firebase نەدۆزرایەوە.")
    # One compact keyboard replaces nine separately rate-limited photo messages.
    rows = [
        [InlineKeyboardButton(f"🎬 {p['name']}"[:58], callback_data=f"fbprofile:{p['tag']}")]
        for p in profiles
    ]
    await update.effective_message.reply_text(
        "🎞️ *ڤیدیۆی ئاینی*\n\nپرۆفایلێک هەڵبژێرە بۆ بینینی ڤیدیۆکانی:",
        reply_markup=ik(rows), parse_mode=ParseMode.MARKDOWN,
    )


async def firebase_video_menu(update, profile_tag, page=0, edit=False):
    videos = await firebase_videos(profile_tag)
    profiles = await firebase_video_profiles()
    profile = next((p for p in profiles if p["tag"] == str(profile_tag)), None)
    if not videos:
        profile_name = profile["name"] if profile else "ئەم پرۆفایلە"
        message = f"🎞️ هیچ ڤیدیۆیەک بۆ {profile_name} لە Firebase نەدۆزرایەوە."
        markup = ik([[InlineKeyboardButton("⬅️ گەڕانەوە بۆ پرۆفایلەکان", callback_data="fbprofiles")]])
        if edit:
            return await update.callback_query.edit_message_text(message, reply_markup=markup)
        return await update.effective_message.reply_text(message, reply_markup=markup)
    page_size = 10
    page = max(0, min(int(page), (len(videos)-1)//page_size))
    rows = []
    for index, item in enumerate(videos[page*page_size:(page+1)*page_size], start=page*page_size):
        title = str(item.get("name") or item.get("title") or f"ڤیدیۆی {index+1}").strip()
        rows.append([InlineKeyboardButton(f"🎬 {title}"[:58], callback_data=f"fbv:{profile_tag}:{index}")])
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"fbvp:{profile_tag}:{page-1}"))
    if (page+1)*page_size < len(videos):
        nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"fbvp:{profile_tag}:{page+1}"))
    nav.append(InlineKeyboardButton("👥 پرۆفایلەکان", callback_data="fbprofiles"))
    rows.append(nav)
    name = profile["name"] if profile else "پرۆفایل"
    message = f"👤 پرۆفایل: *{name}*\n🎞️ ڤیدیۆکان: {len(videos)} — لاپەڕە {page+1}"
    if edit:
        await update.callback_query.edit_message_text(message, reply_markup=ik(rows), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_message.reply_text(message, reply_markup=ik(rows), parse_mode=ParseMode.MARKDOWN)


async def send_firebase_video(update, context, profile_tag, index):
    videos = await firebase_videos(profile_tag)
    if not 0 <= index < len(videos):
        return await update.effective_message.reply_text("ڤیدیۆکە لە Firebase نەدۆزرایەوە.")
    item = videos[index]
    item["title"] = str(item.get("name") or item.get("title") or f"ڤیدیۆی {index+1}")
    item["namefile"] = str(item.get("namefile") or item["url"].split("?", 1)[0].rsplit("/", 1)[-1])
    await send_asset_file(update, context, item)


async def content_menu(update):
    rows=[]
    # Keep reciter data available internally; hide both old audio topics only from this list.
    keys=[key for key in JSON_FILES if key not in {"dangakan", "dangebangbezh"}]
    for i in range(0,len(keys),2):
        row=[InlineKeyboardButton(JSON_FILES[k][0],callback_data=f"jl:{k}:0") for k in keys[i:i+2]]
        rows.append(row)
    await update.effective_message.reply_text("📚 *هەموو بابەتە ئایینییەکان*\nبابەتێک هەڵبژێرە:",reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)

async def names_menu(update, page=0, edit=False):
    with db("name.db") as conn:
        rows = conn.execute("SELECT _id,arabic FROM name ORDER BY _id LIMIT 100").fetchall()
    page_size = 10
    total_pages = max(1, (len(rows)+page_size-1)//page_size)
    page = max(0, min(int(page), total_pages-1))
    buttons = [[InlineKeyboardButton(f"{int(row[0])}. {row[1]}", callback_data=f"nm:{int(row[0])-1}")] for row in rows[page*page_size:(page+1)*page_size]]
    nav = []
    if page: nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"nml:{page-1}"))
    if page+1 < total_pages: nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"nml:{page+1}"))
    if nav: buttons.append(nav)
    text = f" ناوەکانی خوای گەورە — {len(rows)} ناو\nناوێک هەڵبژێرە بۆ بینینی واتا و ئاماژەکانی."
    if edit: await update.callback_query.edit_message_text(text, reply_markup=ik(buttons))
    else: await update.effective_message.reply_text(text, reply_markup=ik(buttons))


def eastern_digits(value):
    return str(value).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


async def show_names(update,index=0):
    with db("name.db") as c:
        r=c.execute("SELECT arabic,surah_ayah,sorani,badini,english,farsi FROM name ORDER BY _id LIMIT 1 OFFSET ?",(index,)).fetchone()
    if not r: return
    import re
    ref = str(r[1] or "").strip()
    match = re.search(r"(\d+)\s*[:：/]\s*(\d+)", ref)
    reference_line = f"📖 شوێنی ئایەت: {ref}"
    ayah_text = ""
    if match:
        sid, ayah = int(match.group(1)), int(match.group(2))
        with db("regayislam.db") as qdb:
            verse = qdb.execute("SELECT sura_name_ar,text FROM ayah_text WHERE suraId=? AND ayah=?", (sid, ayah)).fetchone()
        if verse:
            reference_line = f"📖 سوڕەتی {verse[0]}، ئایەتی {eastern_digits(ayah)}"
            ayah_text = str(verse[1] or "")
    text=f"📿 *ناوەکانی خودا — {index+1}/100*\n\n*{r[0]}*\n{reference_line}"
    if ayah_text:
        text += f"\n\n{ayah_text}"
    text += f"\n\nواتا بە سۆرانی:\n{r[2]}\n\nواتا بە بادینی:\n{r[3]}\n\nEnglish: {r[4]}\nفارسی: {r[5]}"
    rows=[]
    nav=[]
    if index: nav.append(InlineKeyboardButton("⬅️ ناوی پێشوو",callback_data=f"nm:{index-1}"))
    if index<99: nav.append(InlineKeyboardButton("ناوی داهاتوو ➡️",callback_data=f"nm:{index+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان",callback_data=f"fvc:add:-2:{index}")])
    rows.append([InlineKeyboardButton("🔙 گەڕانەوە بۆ هەموو ناوەکان",callback_data=f"nml:{index//10}")])
    await update.effective_message.reply_text(text,reply_markup=ik(rows))


async def show_dua(update,index=0):
    with db("duha.db") as c: r=c.execute("SELECT du3a,wata FROM du3a ORDER BY id LIMIT 1 OFFSET ?",(index,)).fetchone()
    if not r: return
    text=f"🤲 *دوعا — {index+1}/56*\n\n{r[0]}\n\n*واتا:*\n{r[1]}"
    nav=[]
    if index: nav.append(InlineKeyboardButton("⬅️",callback_data=f"du:{index-1}"))
    if index<55: nav.append(InlineKeyboardButton("➡️",callback_data=f"du:{index+1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان",callback_data=f"fvc:add:-3:{index}")])
    await update.effective_message.reply_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)

async def books_menu(update, page=0, edit=False):
    """Browse the original Android book library, grouped by its 69 source categories."""
    with db("mu.db") as conn:
        rows = conn.execute(
            "SELECT s.i,trim(s.title),s.tag,count(b._id) "
            "FROM sarki s LEFT JOIN babat b ON b.bash=s.tag "
            "GROUP BY s.i,s.title,s.tag ORDER BY s.i"
        ).fetchall()
    total_pages = max(1, (len(rows) + 11) // 12)
    page = max(0, min(page, total_pages - 1))
    chunk = rows[page * 12:(page + 1) * 12]
    buttons = [
        [InlineKeyboardButton(f"📖 {title} — {count} بابەت"[:60], callback_data=f"bc:{tag}:0")]
        for _, title, tag, count in chunk
    ]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"bm:{page-1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"bm:{page+1}"))
    if nav:
        buttons.append(nav)
    text = (
        "📜 *پوختەی سەحیحی موسلیم*\n"
        f"بەشەکان: {len(rows)} — پەڕە {page+1}/{total_pages}\n"
        "بەشێک هەڵبژێرە بۆ بینینی فەرموودەکان بە بەش بەش."
    )
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=ik(buttons), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_message.reply_text(text, reply_markup=ik(buttons), parse_mode=ParseMode.MARKDOWN)


async def book_list(update, tag, page=0):
    with db("mu.db") as conn:
        category = conn.execute(
            "SELECT trim(title) FROM sarki WHERE tag=?", (tag,)
        ).fetchone()
        if not category:
            return await update.callback_query.answer("بەش نەدۆزرایەوە", show_alert=True)
        title = category[0]
        # In the source database, babat.bash is the category key.
        # babat.dlxwaz is NULL for all 2,009 records.
        rows = conn.execute(
            "SELECT _id,sarder FROM babat WHERE bash=? ORDER BY _id LIMIT 12 OFFSET ?",
            (tag, page * 12),
        ).fetchall()
        total = conn.execute(
            "SELECT count(*) FROM babat WHERE bash=?", (tag,)
        ).fetchone()[0]
    buttons = [
        [InlineKeyboardButton(str(label).strip()[:58], callback_data=f"bi:{bid}:{page}:0")]
        for bid, label in rows
    ]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"bc:{tag}:{page-1}"))
    if (page + 1) * 12 < total:
        nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"bc:{tag}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 گەڕانەوە بۆ کتێبخانە", callback_data="bm:0")])
    await update.callback_query.edit_message_text(
        f"📚 *{title}*\n{total} بابەت — پەڕەی {page+1}",
        reply_markup=ik(buttons), parse_mode=ParseMode.MARKDOWN,
    )


async def book_item(update, bid, list_page=0, part=0):
    with db("mu.db") as conn:
        row = conn.execute(
            "SELECT sarder,drezha,bash FROM babat WHERE _id=?", (bid,)
        ).fetchone()
        if not row:
            return await update.callback_query.answer("بابەت نەدۆزرایەوە", show_alert=True)
        title, body, tag = row
        category = conn.execute(
            "SELECT trim(title) FROM sarki WHERE tag=?", (tag,)
        ).fetchone()
        category_title = category[0] if category else "کتێبخانە"
        siblings = conn.execute(
            "SELECT _id FROM babat WHERE bash=? ORDER BY _id", (tag,)
        ).fetchall()
    sibling_ids = [int(x[0]) for x in siblings]
    try:
        position = sibling_ids.index(int(bid))
    except ValueError:
        position = 0
    body = str(body or "")
    chunks = cut(body, 3000) or ["ناوەڕۆکی ئەم بابەتە بەردەست نییە."]
    part = max(0, min(int(part), len(chunks) - 1))
    text = (
        f"📚 {category_title}\n"
        f"*{str(title).strip()}*\n"
        f"بابەت {position+1}/{len(sibling_ids)}"
        + (f" — بەشی دەق {part+1}/{len(chunks)}" if len(chunks) > 1 else "")
        + "\n\n" + chunks[part]
    )
    nav = []
    if part > 0:
        nav.append(InlineKeyboardButton("⬅️ بەشی پێشوو", callback_data=f"bi:{bid}:{list_page}:{part-1}"))
    if part + 1 < len(chunks):
        nav.append(InlineKeyboardButton("بەشی داهاتوو ➡️", callback_data=f"bi:{bid}:{list_page}:{part+1}"))
    buttons = [nav] if nav else []
    if position > 0:
        buttons.append([InlineKeyboardButton("⬅️ بابەتی پێشوو", callback_data=f"bi:{sibling_ids[position-1]}:{list_page}:0")])
    if position + 1 < len(sibling_ids):
        buttons.append([InlineKeyboardButton("بابەتی داهاتوو ➡️", callback_data=f"bi:{sibling_ids[position+1]}:{list_page}:0")])
    buttons.append([InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان", callback_data=f"fvc:add:-4:{bid}")])
    buttons.append([InlineKeyboardButton("🔙 گەڕانەوە بۆ لیستی بابەتەکان", callback_data=f"bc:{tag}:{list_page}")])
    await update.callback_query.edit_message_text(
        text[:3900], reply_markup=ik(buttons), disable_web_page_preview=True,
    )


async def repentance_menu(update):
    with db("garanawa.db") as c: rows=c.execute("SELECT _id,title,tableName FROM babatakan ORDER BY _id").fetchall()
    buttons=[]
    for rid,title,table in rows:
        buttons.append([InlineKeyboardButton(title[:58],callback_data=f"gb:{rid}")])
    await update.effective_message.reply_text("🕋 *تەوبە و ئامۆژگاری*\nبابەتێک هەڵبژێرە:",reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)

async def repentance_item(update,rid):
    with db("garanawa.db") as c:
        row=c.execute("SELECT title,desc,tableName FROM babatakan WHERE _id=?",(rid,)).fetchone()
        if not row: return await update.callback_query.answer("بابەت نەدۆزرایەوە",show_alert=True)
        title,body,table=row
        if table:
            allowed={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if table not in allowed: return await update.callback_query.answer("ناوەڕۆک نەدۆزرایەوە",show_alert=True)
            rows=c.execute(f'SELECT title,desc FROM "{table}" ORDER BY _id').fetchall()
        else: rows=[]
    if rows:
        buttons=[[InlineKeyboardButton(str(t)[:58],callback_data=f"gx:{table}:{i}")] for i,(t,d) in enumerate(rows)]
        buttons.append([InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان",callback_data=f"fvc:add:-7:{rid}")])
        await update.callback_query.edit_message_text(f"🕋 {title}\nبابەتێک هەڵبژێرە:",reply_markup=ik(buttons))
    else:
        await update.effective_message.reply_text(f"🕋 {title}\n\n{body[:3500]}",reply_markup=ik([[InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان",callback_data=f"fvc:add:-7:{rid}")]]),disable_web_page_preview=True)

async def repentance_subitem(update,table,index):
    allowed={"bochetawbabkain","chontawbabkam","marjakanitawba","neshanayqbulitawba"}
    if table not in allowed: return await update.callback_query.answer("بەش نەدۆزرایەوە",show_alert=True)
    with db("garanawa.db") as c: row=c.execute(f'SELECT title,desc FROM "{table}" ORDER BY _id LIMIT 1 OFFSET ?',(index,)).fetchone()
    if row: await update.effective_message.reply_text(f"{row[0]}\n\n{row[1][:3500]}",reply_markup=ik([[InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان",callback_data=f"fvc:add:{-8-list(sorted(allowed)).index(table)}:{index}")]]),disable_web_page_preview=True)

RAMADAN_TABLES = {
    "welcome": "پێشوازی لە ڕەمەزان",
    "barbang": "بەربانگ و دوعاکانی",
    "parshew": "پارشێو و ڕۆژوو",
    "nwezhtaraweh": "نوێژی تەراویح",
    "shawyqadr": "شەوی قەدر"
}


def valid_ramadan_tables(conn):
    existing = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )}
    return [(table, title) for table, title in RAMADAN_TABLES.items() if table in existing]


async def ramadan_menu(update):
    with db("ramazanew.db") as conn:
        tables = valid_ramadan_tables(conn)
        buttons = []
        for table, title in tables:
            count = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            buttons.append([InlineKeyboardButton(f"🌙 {title} — {count} بابەت", callback_data=f"rd:{table}:0")])
    await update.effective_message.reply_text(
        "🌙 *کتێبخانەی ڕەمەزان*\nبەشێک هەڵبژێرە بۆ خوێندنەوە:",
        reply_markup=ik(buttons), parse_mode=ParseMode.MARKDOWN
    )


async def ramadan_list(update, table, page=0):
    with db("ramazanew.db") as conn:
        allowed = {name for name, _ in valid_ramadan_tables(conn)}
        if table not in allowed:
            return await update.callback_query.answer("ئەم بەشە لە داتابەیسی سەرچاوەدا بەردەست نییە.", show_alert=True)
        rows = conn.execute(
            f'SELECT _id,title FROM "{table}" ORDER BY _id LIMIT 10 OFFSET ?', (page * 10,)
        ).fetchall()
        total = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    if not rows:
        return await update.callback_query.answer("هیچ بابەتێک لەم لاپەڕەیەدا نییە.", show_alert=True)
    buttons = [[InlineKeyboardButton(str(title)[:58], callback_data=f"ri:{table}:{rid}")]
               for rid, title in rows]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"rd:{table}:{page-1}"))
    if (page + 1) * 10 < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"rd:{table}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 کتێبخانەی ڕەمەزان", callback_data="rm")])
    await update.callback_query.edit_message_text(
        f"🌙 *{RAMADAN_TABLES.get(table, 'ڕەمەزان')}*\n{total} بابەت — لاپەڕە {page+1}",
        reply_markup=ik(buttons), parse_mode=ParseMode.MARKDOWN
    )


async def ramadan_item(update, table, rid):
    with db("ramazanew.db") as conn:
        allowed = {name for name, _ in valid_ramadan_tables(conn)}
        if table not in allowed:
            return await update.callback_query.answer("ئەم بابەتە لە داتابەیسدا نییە.", show_alert=True)
        row = conn.execute(
            f'SELECT title,desc FROM "{table}" WHERE _id=?', (rid,)
        ).fetchone()
    if not row:
        return await update.callback_query.answer("بابەت نەدۆزرایەوە.", show_alert=True)
    await update.effective_message.reply_text(
        f"🌙 {row[0]}\n\n{row[1][:3700]}",
        disable_web_page_preview=True,
        reply_markup=ik([
            [InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان", callback_data=f"fvc:add:{-20-list(RAMADAN_TABLES).index(table)}:{rid}")],
            [InlineKeyboardButton("🔙 گەڕانەوە بۆ بەش", callback_data=f"rd:{table}:0")]
        ])
    )

async def prayer_reminder_info(update):
    await update.effective_message.reply_text("🔔 *ئاگادارکردنەوەی بانگ*\n\nکاتەکانی بانگ لەم وەشانەدا لە خشتەی داتابەیسی ئەپەکەت پیشان دەدرێن. ئاگادارکردنەوەی ئۆتۆماتیکی لە Telegram پێویستی بە بەردەوام کارکردنی سێرڤەر و ڕێکخستنی job queue هەیە؛ لەم وەشانەدا وەک تایبەتمەندیی چالاک دانەنراوە.")

TASBIH_PHRASES = [
    "سُبْحَانَ اللهِ", "الْحَمْدُ لِلَّهِ", "اللهُ أَكْبَرُ",
    "لَا إِلَهَ إِلَّا اللهُ", "لَا حَوْلَ وَلَا قُوَّةَ إِلَّا بِاللهِ",
    "أَسْتَغْفِرُ اللهَ", "سُبْحَانَ اللهِ وَبِحَمْدِهِ",
    "سُبْحَانَ اللهِ الْعَظِيمِ", "اللَّهُمَّ صَلِّ وَسَلِّمْ عَلَى مُحَمَّدٍ",
    "لَا إِلَهَ إِلَّا أَنْتَ سُبْحَانَكَ إِنِّي كُنْتُ مِنَ الظَّالِمِينَ",
    "حَسْبِيَ اللهُ وَنِعْمَ الْوَكِيلُ", "اللَّهُمَّ اغْفِرْ لِي",
    "رَبِّ اغْفِرْ لِي وَتُبْ عَلَيَّ إِنَّكَ أَنْتَ التَّوَّابُ الرَّحِيمُ",
    "سُبْحَانَ اللهِ وَالْحَمْدُ لِلَّهِ وَلَا إِلَهَ إِلَّا اللهُ وَاللهُ أَكْبَرُ",
]


async def tasbih_picker(update, page=0, edit=False):
    rows = [[InlineKeyboardButton(f"{i+1}. {phrase}"[:58], callback_data=f"tz:pick:{i}")]
            for i, phrase in enumerate(TASBIH_PHRASES)]
    text = "📿 تەسبیح\n\nیەکێک لە ١٤ زیکرەکە هەڵبژێرە:"
    if edit: await update.callback_query.edit_message_text(text, reply_markup=ik(rows))
    else: await update.effective_message.reply_text(text, reply_markup=ik(rows))


async def tasbih(update, context, change=0, edit=False):
    uid = update.effective_user.id
    zikr_index = get_tasbih_zikr(uid)
    if zikr_index < 0 or zikr_index >= len(TASBIH_PHRASES):
        return await tasbih_picker(update, 0, edit)
    count = change_tasbih(uid, change, zikr_index) if change else (get_tasbih(uid, zikr_index) or (0,))[0]
    phrase = TASBIH_PHRASES[zikr_index]
    text = f"📿 تەسبیح\n\n{phrase}\n\nژمارە: {count}"
    rows = [
        [InlineKeyboardButton("➕ ١ زیاد بکە", callback_data="ts:+"), InlineKeyboardButton("🔄 سفر", callback_data="ts:reset")],
        [InlineKeyboardButton("🔁 هەڵبژاردنی زیکری تر", callback_data="tz:list:0")],
        [InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان", callback_data=f"fvc:add:-5:{zikr_index}")]
    ]
    if edit: await update.callback_query.edit_message_text(text, reply_markup=ik(rows))
    else: await update.effective_message.reply_text(text, reply_markup=ik(rows))


async def search_prompt(update, mode):
    await update.effective_message.reply_text("🔎 وشە یان دەستەواژەکە بنووسە بۆ گەڕان:")


async def feedback_prompt(update):
    await update.effective_message.reply_text(
        "💬 پێشنیار و ڕەخنە\n\nجۆری پەیامەکەت هەڵبژێرە:",
        reply_markup=ik([
            [InlineKeyboardButton("🐞 ڕاپۆرتی هەڵە", callback_data="fb:cat:bug")],
            [InlineKeyboardButton("💡 پێشنیار", callback_data="fb:cat:suggestion")],
            [InlineKeyboardButton("📚 ناوەڕۆک", callback_data="fb:cat:content")],
            [InlineKeyboardButton("✉️ گشتی", callback_data="fb:cat:general")],
            [InlineKeyboardButton("👤 پەیوەندی بە بەڕێوەبەر", url="https://t.me/ismahil_312")]
        ])
    )


async def receive_feedback(update, context, message):
    category = context.user_data.pop("feedback_category", "general")
    context.user_data.pop("feedback_waiting", None)
    uid = update.effective_user.id
    try:
        await asyncio.to_thread(save_feedback, uid, category, message[:4000])
        user = update.effective_user
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"💬 پێشنیار و ڕەخنە\n👤 {user.full_name} (@{user.username or '—'})\n🆔 {uid}\n📂 {category}\n\n{message[:3300]}",
                    reply_markup=ik([[InlineKeyboardButton("↩️ وەڵامدانەوە", callback_data=f"fb:reply:{uid}")]])
                )
            except Exception:
                log.exception("Could not notify admin about feedback from %s", uid)
        await update.effective_message.reply_text("✅ سوپاس بۆ پەیامەکەت. پێشنیارەکەت بە سەرکەوتوویی نێردرا.")
    except Exception:
        log.exception("Could not save feedback from user %s", uid)
        await update.effective_message.reply_text("⚠️ ناردنی پەیامەکەت سەرکەوتوو نەبوو. تکایە دواتر هەوڵ بدە.")


def load_pdf_books():
    with open(DATA / "ktebakan.json", "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, list) else []


async def pdf_books_menu(update, page=0, edit=False):
    books = load_pdf_books()
    page_size = 10
    total_pages = max(1, (len(books) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    rows = []
    for index, book in enumerate(books[page*page_size:(page+1)*page_size], start=page*page_size):
        rows.append([InlineKeyboardButton(str(book.get("name") or f"کتێب {index+1}")[:58],
                                          callback_data=f"pb:item:{index}:{page}")])
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"pb:list:{page-1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"pb:list:{page+1}"))
    if nav:
        rows.append(nav)
    text = f"📚 *کتێبخانەی PDF*\n{len(books)} کتێب — لاپەڕە {page+1}/{total_pages}\nکتێبێک هەڵبژێرە:"
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=ik(rows), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_message.reply_text(text, reply_markup=ik(rows), parse_mode=ParseMode.MARKDOWN)


async def pdf_book_item(update, index, page=0):
    books = load_pdf_books()
    if not 0 <= index < len(books):
        return await update.callback_query.answer("کتێب نەدۆزرایەوە", show_alert=True)
    book = books[index]
    title = str(book.get("name") or f"کتێب {index+1}")
    about_text = str(book.get("about") or "کورتەی کتێب بەردەست نییە.")
    author = str(book.get("author") or "نووسەر دیاری نەکراوە")
    buttons = [[InlineKeyboardButton("📥 ناردنی فایلەکەی PDF", callback_data=f"pb:send:{index}:{page}")]]
    buttons.append([InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان", callback_data=f"fvc:add:-6:{index}")])
    buttons.append([InlineKeyboardButton("🔙 گەڕانەوە بۆ کتێبخانە", callback_data=f"pb:list:{page}")])
    await update.callback_query.edit_message_text(
        f"📚 {title}\n\n✍️ نووسەر: {author}\n\n{about_text[:1800]}\n\nفایلەکە بە شێوەی PDF بۆت دەنێردرێت.",
        reply_markup=ik(buttons), disable_web_page_preview=True
    )


async def send_pdf_book(update, context, index, page=0):
    books = load_pdf_books()
    if not 0 <= index < len(books):
        return await update.callback_query.answer("کتێب نەدۆزرایەوە", show_alert=True)
    book = books[index]
    url = str(book.get("url") or "")
    if not url.startswith("https://"):
        return await update.effective_message.reply_text("لینکی فایلەکە دروست نییە.")
    title = str(book.get("name") or f"کتێب {index+1}")
    status = await update.effective_message.reply_text(f"⏳ فایلەکەی «{title}» ئامادە دەکرێت...\\n📥 وەرگرتنی PDF")
    try:
        def download():
            request = urllib.request.Request(url, headers={"User-Agent": "Regay-Islam-Telegram-Bot/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read(49*1024*1024+1)
            if not data:
                raise ValueError("Empty PDF response")
            if len(data) > 49*1024*1024:
                raise ValueError("PDF exceeds Telegram bot upload limit")
            if not data.startswith(b"%PDF"):
                raise ValueError("URL did not return a PDF file")
            return data
        payload = await asyncio.to_thread(download)
        await status.edit_text("✅ کتێبەکە وەرگیرا.\\n📤 ئێستا PDF ـەکە بۆ تێلێگرام دەنێردرێت...")
        document = io.BytesIO(payload)
        safe_name = "".join(ch for ch in title if ch.isalnum() or ch in " _-")[:70] or "islamic-book"
        document.name = safe_name + ".pdf"
        await context.bot.send_document(chat_id=update.effective_chat.id, document=document, caption=f"📚 {title}\n✍️ {str(book.get('author') or 'نووسەر دیاری نەکراوە')[:150]}")
        await status.delete()
    except Exception:
        log.exception("PDF delivery failed for book index %s", index)
        await status.edit_text("⚠️ ناردنی PDF سەرکەوتوو نەبوو. ڕەنگە فایلەکە گەورە بێت یان سێرڤەری سەرچاوە وەڵام نەدات.")

async def do_search(update,context,query):
    mode=context.user_data.pop("search_mode","all")
    q=query.strip()
    if not q: return
    results=[]
    if mode in ("quran","all"):
        with db("regayislam.db") as c:
            rows=c.execute("SELECT suraId,sura_name_ar,ayah,text FROM ayah_text WHERE text LIKE ? OR rebar LIKE ? OR raman LIKE ? OR puxta LIKE ? OR asan LIKE ? OR sanahi LIKE ? OR hazhar LIKE ? OR zhin LIKE ? OR maiser LIKE ? OR roshn LIKE ? OR tawhid LIKE ? LIMIT 8",tuple([f"%{q}%"]*11)).fetchall()
        for sid,name,ayah,text in rows:
            results.append((f"📖 {name} — ئایەتی {ayah}\n{text}",f"q:t:{sid}:{ayah}"))
    if mode in ("all","books"):
        with db("mu.db") as c:
            rows=c.execute("SELECT _id,sarder,substr(drezha,1,900) FROM babat WHERE sarder LIKE ? OR drezha LIKE ? LIMIT 5",(f"%{q}%",f"%{q}%")).fetchall()
        for bid,title,body in rows: results.append((f"📚 {title}\n{body}",f"bi:{bid}"))
        for key,(title,fn) in JSON_FILES.items():
            try: data=load_json(key)
            except Exception: continue
            for i,item in enumerate(data):
                s=json.dumps(item,ensure_ascii=False)
                if q.casefold() in s.casefold():
                    val=item.get('title') or item.get('name') or title if isinstance(item,dict) else title
                    body=item.get('text') or item.get('desc') or '' if isinstance(item,dict) else str(item)
                    results.append((f"{title}: {val}\n{body[:800]}",f"j:{key}:{i}"))
                    if len(results)>=15: break
            if len(results)>=15: break
    if not results: return await update.effective_message.reply_text("هیچ ئەنجامێک بۆ ئەم گەڕانە نەدۆزرایەوە.")
    for text,callback in results[:15]:
        await update.effective_message.reply_text(text[:3500],reply_markup=ik([[InlineKeyboardButton("بینینی بابەت",callback_data=callback)]]),disable_web_page_preview=True)

async def handle_text(update,context):
    text=(update.effective_message.text or "").strip()
    if context.user_data.get("admin_broadcast_waiting") and update.effective_user.id in ADMIN_IDS:
        if text == "/cancel":
            context.user_data.pop("admin_broadcast_waiting", None)
            return await update.effective_message.reply_text("❎ ناردنی پەیامی گشتی هەڵوەشایەوە.")
        return await admin_broadcast(update, context, text)
    if context.user_data.get("feedback_reply_to") and update.effective_user.id in ADMIN_IDS:
        target = int(context.user_data.pop("feedback_reply_to"))
        try:
            await context.bot.send_message(chat_id=target, text=f"💬 وەڵامی بەڕێوەبەر:\n\n{text[:4000]}")
            return await update.effective_message.reply_text(f"✅ وەڵامەکەت بۆ بەکارهێنەری {target} نێردرا.")
        except Exception:
            log.exception("Could not send admin feedback reply to %s", target)
            return await update.effective_message.reply_text("⚠️ ناردنی وەڵامەکە سەرکەوتوو نەبوو.")
    if context.user_data.get("feedback_waiting"):
        return await receive_feedback(update, context, text)
    if context.user_data.pop("mushaf_waiting_page", False):
        if not text.isdigit() or not 1 <= int(text) <= 604:
            context.user_data["mushaf_waiting_page"] = True
            return await update.effective_message.reply_text("ژمارەی پەڕەکە لە ١ تا ٦٠٤ بنووسە.")
        return await show_quran_page(update, int(text))
    if "search_mode" in context.user_data:
        return await do_search(update,context,text)
    mapping={
        "📖 قورئانی پیرۆز":lambda:show_suras(update),
        "🕌 کاتەکانی بانگ":lambda:prayer_cmd(update,context),
        "🗓 کاتەکانی بانگی مانگانە":lambda:monthly_prayer_times(update),
        "🕋 ئایەتی کورسی":lambda:show_ayat_kursi(update),
        "📖 مصحەف":lambda:show_mushaf_menu(update,context),
        "📿 تەسبیح":lambda:tasbih_picker(update),
        "شاردنەوەی مێنیو":lambda:hide_menu_cmd(update,context),
        "📿 زیکرەکان":lambda:json_list(update,"zikrakan",0),
        "🤲 دوعاکان":lambda:show_dua(update,0),
        "📜 فەرموودەکان":lambda:hadith_menu(update),
        "📚 کتێبخانەی PDF":lambda:pdf_books_menu(update),
        "💬 پێشنیار و ڕەخنە":lambda:feedback_prompt(update),
        "🕋 تەوبە و ئامۆژگاری":lambda:repentance_menu(update),
         "🌙 ڕەمەزان":lambda:ramadan_menu(update),
        "📿 ناوەکانی خودا":lambda:names_menu(update,0),
        "🎙️ قارییەکان":lambda:show_qari_menu(update,0),
        "📚 هەموو بابەتەکان":lambda:content_menu(update),
        "🎞️ ڤیدیۆی ئاینی":lambda:firebase_video_profiles_menu(update),
        "🔎 گەڕان":lambda:search_choose(update),
        "⭐ دڵخوازەکان":lambda:show_favorites(update),
        "📍 دوا خوێندنەوە":lambda:show_last_read(update),
        "⚙️ ڕێکخستن":lambda:show_settings(update),
        "ℹ️ دەربارەی بۆت":lambda:about(update),
    }
    fn=mapping.get(text)
    if fn: await fn()
    else: await update.effective_message.reply_text("تکایە لە مێنیوەکە هەڵبژێرە یان /start بنووسە.",reply_markup=main_keyboard(update.effective_user.id))

async def hadith_menu(update):
    await update.effective_message.reply_text(
        "📜 *فەرموودەکان*\n\nبەشێک هەڵبژێرە:",
        reply_markup=ik([
            [InlineKeyboardButton("٤٠٠ فەرموودە", callback_data="hd:400")],
            [InlineKeyboardButton("پوختەی سەحیحی موسلیم", callback_data="hd:muslim")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


async def search_choose(update):
    await update.effective_message.reply_text("🔎 جۆری گەڕان هەڵبژێرە:",reply_markup=ik([
        [InlineKeyboardButton("گەڕان لە قورئان",callback_data="sm:quran"),InlineKeyboardButton("گەڕان لە هەموو ناوەڕۆک",callback_data="sm:all")],
        [InlineKeyboardButton("گەڕان لە کتێب و فەرموودە",callback_data="sm:books")]
    ]))

async def about(update):
    await update.effective_message.reply_text(
        "🕌 ڕێگای ئیسلام — وەشانی Telegram\n\nقورئان، مووسحەف، کاتەکانی بانگ، فەرموودە، کتێب و زیکر لە یەک شوێندا.\n\nبۆ پێشنیار، ڕاپۆرتی هەڵە یان یارمەتی، پەیوەندی بە بەڕێوەبەر بکە.",
        reply_markup=ik([[InlineKeyboardButton("👤 پەیوەندی بە بەڕێوەبەر", url="https://t.me/ismahil_312")]])
    )

async def callback(update: Update,context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    data=q.data or ""
    if data.startswith("setup:citypage:"):
        return await setup_city_menu(update, int(data.split(":")[2]), True)
    if data.startswith("setup:qpage:"):
        return await setup_qari_menu(update, int(data.split(":")[2]), True)
    if data.startswith("setup:city:"):
        city = data.split(":", 2)[2]
        set_city(q.from_user.id, city)
        if context.user_data.pop("settings_city_flow", False):
            return await q.edit_message_text("✅ شاری نوێ پاشەکەوت کرا.")
        return await setup_qari_menu(update)
    if data.startswith("setup:reciter:"):
        rid = data.split(":")[2]
        return await finish_setup(update, q.from_user.id, rid)
    if data == "st:city":
        context.user_data["settings_city_flow"] = True
        return await setup_city_menu(update, 0, True)
    if data.startswith("st:notify:"):
        enabled = data.endswith(":on")
        set_prayer_notifications(q.from_user.id, enabled)
        return await q.edit_message_text("✅ ئاگادارکردنەوەی بانگ چالاک کرا." if enabled else "🔕 ئاگادارکردنەوەی بانگ ناچالاک کرا.")
    if data == "st:qari:menu":
        return await setup_qari_menu(update, 0, True, True)
    if data.startswith("st:qpage:"):
        return await setup_qari_menu(update, int(data.split(":")[2]), True, True)
    if data.startswith("st:qari:"):
        rid = data.split(":")[2]
        set_qari(q.from_user.id, rid)
        return await q.edit_message_text("✅ قاریی دڵخوازت پاشەکەوت کرا.")
    if data.startswith("fb:cat:"):
        category = data.split(":")[2]
        context.user_data["feedback_category"] = category
        context.user_data["feedback_waiting"] = True
        return await q.message.reply_text("✍️ تکایە پێشنیار یان ڕەخنەکەت بە ڕوونی بنووسە. بۆ هەڵوەشاندنەوە /cancel بنووسە.")
    if data.startswith("fb:reply:"):
        if q.from_user.id not in ADMIN_IDS:
            return await q.answer("⛔ دەسەڵاتت نییە.", show_alert=True)
        target = int(data.split(":")[2])
        context.user_data["feedback_reply_to"] = target
        return await q.message.reply_text(f"✍️ وەڵامەکەت بۆ بەکارهێنەری {target} بنووسە. /cancel بۆ هەڵوەشاندنەوە.")
    if data.startswith("pb:list:"):
        return await pdf_books_menu(update, int(data.split(":")[2]), True)
    if data.startswith("pb:item:"):
        _, _, index, page = data.split(":")
        return await pdf_book_item(update, int(index), int(page))
    if data.startswith("pb:send:"):
        _, _, index, page = data.split(":")
        return await send_pdf_book(update, context, int(index), int(page))
    if data == "kursi:audio":
        return await send_ayat_kursi_audio(update, context)
    if data.startswith("tz:list:"):
        return await tasbih_picker(update, 0, True)
    if data.startswith("tz:pick:"):
        index = int(data.split(":")[2])
        if not 0 <= index < len(TASBIH_PHRASES):
            return await q.answer("زیکرەکە نەدۆزرایەوە.", show_alert=True)
        set_tasbih_zikr(q.from_user.id, index)
        return await tasbih(update, context, 0, True)
    if data == "mo:open":
        return await show_menu_order(update, True)
    if data.startswith("mo:up:") or data.startswith("mo:down:"):
        _, direction, key = data.split(":", 2)
        order = get_menu_order(q.from_user.id)
        order = [item for item in order if item in MENU_ITEMS]
        order += [item for item in DEFAULT_MENU_ORDER if item not in order]
        index = order.index(key) if key in order else 0
        target = index - 1 if direction == "up" else index + 1
        if 0 <= target < len(order):
            order[index], order[target] = order[target], order[index]
        set_menu_order(q.from_user.id, order)
        return await show_menu_order(update, True)
    if data == "mo:done":
        await q.edit_message_text("✅ ڕیزبەندی مێنیوەکەت پاشەکەوت کرا.")
        return await q.message.reply_text("مێنیوی نوێت ئامادەیە:", reply_markup=main_keyboard(q.from_user.id))
    if data.startswith("qaudio:"):
        return await play_default_qari(update, context, int(data.split(":")[1]))
    if data.startswith("qg:"):
        _, rid, sid, page = data.split(":")
        return await qari_ayah_guide(update, rid, int(sid), int(page), True)
    if data.startswith("ad:"):
        if q.from_user.id not in ADMIN_IDS:
            return await q.answer("⛔ دەسەڵاتت نییە.", show_alert=True)
        bits = data.split(":")
        if data == "ad:home":
            return await q.edit_message_text("🛠 بەشی بەڕێوەبەر", reply_markup=admin_keyboard())
        if data == "ad:stats":
            return await admin_stats(update, True)
        if len(bits) == 3 and bits[1] == "users":
            return await admin_users(update, int(bits[2]), True)
        if len(bits) == 3 and bits[1] == "ban":
            uid = int(bits[2]); ban_user(uid, "لە لایەن بەڕێوەبەرەوە")
            return await q.edit_message_text(f"⛔ بەکارهێنەری {uid} بەند کرا.", reply_markup=ik([[InlineKeyboardButton("🔙 لیست", callback_data="ad:users:0")]]))
        if len(bits) == 3 and bits[1] == "unban":
            uid = int(bits[2]); unban_user(uid)
            return await q.edit_message_text(f"🔓 بەندی بەکارهێنەری {uid} لابرا.", reply_markup=ik([[InlineKeyboardButton("🔙 لیست", callback_data="ad:users:0")]]))
        if data == "ad:broadcast":
            context.user_data["admin_broadcast_waiting"] = True
            return await q.message.reply_text("📢 پەیامەکە بنووسە. بۆ هەڵوەشاندنەوە /cancel بنووسە.")
    try:
        if data == "fbprofiles":
            return await firebase_video_profiles_menu(update)
        if data.startswith("fbprofile:"):
            # Profile cards are photo messages; send the filtered list as a new text message.
            return await firebase_video_menu(update, data.split(":", 1)[1], 0, False)
        if data.startswith("fbvp:"):
            _, tag, page = data.split(":")
            return await firebase_video_menu(update, tag, int(page), True)
        if data.startswith("fbv:"):
            _, tag, index = data.split(":")
            return await send_firebase_video(update, context, tag, int(index))
        if data.startswith("qr:list:"): return await show_qari_menu(update,int(data.split(":")[2]),True)
        if data.startswith("qr:pick:"): return await show_qari_surahs(update,int(data.split(":")[2]))
        if data.startswith("qr:play:"):
            _,_,index,sid=data.split(":")
            return await play_qari_surah(update,context,int(index),int(sid))
        if data == "lr": return await show_last_read(update)
        if data == "settings": return await show_settings(update)
        if data == "fv:list": return await show_favorites(update)
        if data == "st:city": return await prayer_city_list(update, mode="prayer")
        if data == "st:notify:on":
            set_prayer_notifications(q.from_user.id, True)
            return await show_settings(update)
        if data == "st:notify:off":
            set_prayer_notifications(q.from_user.id, False)
            return await show_settings(update)
        if data.startswith("fvc:add:"):
            _, _, raw_sid, raw_item = data.split(":")
            sid, item_id = int(raw_sid), int(raw_item)
            title = "ناوەڕۆک"
            if sid == -2:
                with db("name.db") as c:
                    row = c.execute("SELECT arabic FROM name ORDER BY _id LIMIT 1 OFFSET ?", (item_id,)).fetchone()
                title = row[0] if row else "ناوی خودا"
            elif sid == -3:
                title = f"دوعا {item_id+1}"
            elif sid == -4:
                with db("mu.db") as c:
                    row = c.execute("SELECT sarder FROM babat WHERE _id=?", (item_id,)).fetchone()
                title = str(row[0]) if row else "بابەتی کتێب"
            elif sid == -5:
                title = TASBIH_PHRASES[item_id] if 0 <= item_id < len(TASBIH_PHRASES) else "تەسبیح"
            elif sid == -6:
                books = load_pdf_books()
                title = str(books[item_id].get("name") or "کتێبی PDF") if 0 <= item_id < len(books) else "کتێبی PDF"
            elif sid == -7:
                with db("garanawa.db") as c:
                    row = c.execute("SELECT title FROM babatakan WHERE _id=?", (item_id,)).fetchone()
                title = row[0] if row else "تەوبە و ئامۆژگاری"
            elif -11 <= sid <= -8:
                allowed_tables = sorted({"bochetawbabkain","chontawbabkam","marjakanitawba","neshanayqbulitawba"})
                table_index = -8 - sid
                title = f"بابەتی تەوبە {item_id+1}"
            elif -20 >= sid > -20-len(RAMADAN_TABLES):
                table_index = -20 - sid
                table = list(RAMADAN_TABLES)[table_index]
                with db("ramazanew.db") as c:
                    row = c.execute(f'SELECT title FROM "{table}" WHERE _id=?', (item_id,)).fetchone()
                title = row[0] if row else RAMADAN_TABLES[table]
            elif sid <= -100:
                key_index = -100 - sid
                keys = list(JSON_FILES)
                key = keys[key_index] if 0 <= key_index < len(keys) else None
                if key:
                    items = load_json(key)
                    if 0 <= item_id < len(items) and isinstance(items[item_id], dict):
                        title = str(items[item_id].get("title") or items[item_id].get("name") or f"{JSON_FILES[key][0]} {item_id+1}")
            added = add_favorite(q.from_user.id, sid, item_id, title[:180])
            return await q.message.reply_text("⭐ ناوەڕۆکەکە زیاد کرا بۆ دڵخوازەکان." if added else "ئەم بابەتە پێشتر لە دڵخوازەکانتدا هەیە.")
        if data.startswith("fvc:open:"):
            _, _, raw_sid, raw_item = data.split(":")
            sid, item_id = int(raw_sid), int(raw_item)
            if sid == -2: return await show_names(update, item_id)
            if sid == -3: return await show_dua(update, item_id)
            if sid == -4: return await book_item(update, item_id)
            if sid == -5:
                set_tasbih_zikr(q.from_user.id, item_id)
                return await tasbih(update, context)
            if sid == -6:
                return await pdf_book_item(update, item_id)
            if sid == -7:
                return await repentance_item(update, item_id)
            if -11 <= sid <= -8:
                allowed_tables = sorted({"bochetawbabkain","chontawbabkam","marjakanitawba","neshanayqbulitawba"})
                table_index = -8 - sid
                if 0 <= table_index < len(allowed_tables):
                    return await repentance_subitem(update, allowed_tables[table_index], item_id)
            if -20 >= sid > -20-len(RAMADAN_TABLES):
                table_index = -20 - sid
                return await ramadan_item(update, list(RAMADAN_TABLES)[table_index], item_id)
            if sid <= -100:
                key_index = -100 - sid
                keys = list(JSON_FILES)
                key = keys[key_index] if 0 <= key_index < len(keys) else None
                if key: return await show_json_item(update, context, key, item_id)
        if data.startswith("fv:add:"):
            _, _, sid, ayah = data.split(":")
            with db("regayislam.db") as c:
                name = c.execute("SELECT sura_name_ar FROM ayah_text WHERE suraId=? AND ayah=?", (int(sid), int(ayah))).fetchone()
            title = f"{name[0] if name else 'قورئان'} — ئایەتی {ayah}"
            added = add_favorite(q.from_user.id, int(sid), int(ayah), title)
            return await q.message.reply_text("⭐ ئایەتەکە زیاد کرا بۆ دڵخوازەکان." if added else "ئەم ئایەتە پێشتر لە دڵخوازەکانتدا هەیە.")
        if data.startswith("fv:open:"):
            _, _, sid, ayah = data.split(":")
            return await show_tafsir(update, int(sid), int(ayah))
        if data.startswith("fv:del:"):
            remove_favorite(q.from_user.id, int(data.split(":")[2]))
            return await show_favorites(update)
        if data.startswith("qp:"): return await show_quran_page(update,int(data.split(":")[1]),True)
        if data == "ms:list":
            context.user_data.pop("mushaf_waiting_page", None)
            return await show_mushaf_surah_list(update,0,True)
        if data.startswith("ms:list:"):
            context.user_data.pop("mushaf_waiting_page", None)
            return await show_mushaf_surah_list(update,int(data.split(":")[2]),True)
        if data == "ms:number":
            context.user_data["mushaf_waiting_page"] = True
            return await q.message.reply_text("ژمارەی پەڕەکە لە ١ تا ٦٠٤ بنووسە:")
        if data.startswith("ms:"):
            context.user_data.pop("mushaf_waiting_page", None)
            return await show_mushaf_surah_pages(update,int(data.split(":")[1]),0,True)
        if data.startswith("msp:"):
            _,sid,page=data.split(":"); return await show_mushaf_surah_pages(update,int(sid),int(page),True)
        if data.startswith("mpg:"): return await show_quran_page(update,int(data.split(":")[1]),False)
        if data.startswith("q:s:"): return await show_suras(update,int(data.split(":")[2]),True)
        if data.startswith("q:a:"):
            _,_,sid,off=data.split(":"); return await show_ayahs(update,int(sid),int(off),True)
        if data.startswith("q:t:"):
            _,_,sid,ay=data.split(":"); return await show_tafsir(update,int(sid),int(ay))
        if data.startswith("q:tf:"):
            _,_,sid,ay,choice=data.split(":"); return await show_tafsir(update,int(sid),int(ay),int(choice))
        if data.startswith("pcl:"):
            bits=data.split(":")
            if len(bits)==3: return await prayer_city_list(update,int(bits[2]),True,bits[1])
            return await prayer_city_list(update,int(bits[1]),True)
        if data.startswith("pc:"):
            city=data[3:]; set_city(q.from_user.id,city); return await prayer_times(update,city,True)
        if data.startswith("mc:"):
            city=data[3:]; set_city(q.from_user.id,city); return await monthly_prayer_times(update,city,edit=True)
        if data.startswith("pm:"):
            return await monthly_prayer_times(update,get_city(q.from_user.id),data[3:],edit=True)
        if data.startswith("hd:"):
            if data == "hd:400": return await json_list(update,"farmwda",0,True)
            if data == "hd:muslim": return await books_menu(update,0,True)
        if data.startswith("j:"):
            _,key,index=data.split(":"); return await show_json_item(update,context,key,int(index),True)
        if data.startswith("jl:"):
            _,key,page=data.split(":"); return await json_list(update,key,int(page),True)
        if data.startswith("nm:"): return await show_names(update,int(data.split(":")[1]))
        if data.startswith("nml:"): return await names_menu(update,int(data.split(":")[1]),True)
        if data.startswith("du:"): return await show_dua(update,int(data.split(":")[1]))
        if data == "bm": return await books_menu(update)
        if data.startswith("bm:"): return await books_menu(update,int(data.split(":")[1]),True)
        if data.startswith("bc:"):
            _,tag,page=data.split(":"); return await book_list(update,tag,int(page))
        if data.startswith("bi:"):
            bits=data.split(":")
            return await book_item(update,int(bits[1]),int(bits[2]) if len(bits)>2 else 0,int(bits[3]) if len(bits)>3 else 0)
        if data == "ts:reset":
            reset_tasbih(q.from_user.id, get_tasbih_zikr(q.from_user.id))
            return await tasbih(update,context,0,True)
        if data.startswith("ts:"):
            n=1 if data.endswith("+") else 0
            return await tasbih(update,context,n,True)
        if data.startswith("gb:"): return await repentance_item(update,int(data.split(":")[1]))
        if data.startswith("gx:"):
            _,table,index=data.split(":"); return await repentance_subitem(update,table,int(index))
        if data=="rm": return await ramadan_menu(update)
        if data.startswith("rd:"):
            _,table,page=data.split(":"); return await ramadan_list(update,table,int(page))
        if data.startswith("ri:"):
            _,table,rid=data.split(":"); return await ramadan_item(update,table,int(rid))
        if data.startswith("sm:"):
            context.user_data["search_mode"]=data.split(":")[1]
            return await q.message.reply_text("🔎 وشە یان دەستەواژەکە بنووسە:")
    except Exception:
        log.exception("callback failed: %s",data)
        await q.message.reply_text("هەڵەیەک ڕوویدا. تکایە دووبارە هەوڵ بدە.")

async def cmd_search(update,context):
    mode=context.args[0] if context.args and context.args[0] in ("quran","books","all") else "all"
    context.user_data["search_mode"]=mode
    if len(context.args)>1: return await do_search(update,context," ".join(context.args[1:]))
    await update.effective_message.reply_text("وشەکەت بنووسە بۆ گەڕان:")

def admin_keyboard():
    return ik([
        [InlineKeyboardButton("👥 بەکارهێنەران", callback_data="ad:users:0"),
         InlineKeyboardButton("📊 ئامار", callback_data="ad:stats")],
        [InlineKeyboardButton("📢 ناردنی پەیامی گشتی", callback_data="ad:broadcast")]
    ])


async def admin_users(update, page=0, edit=False):
    rows = list_users(10, page * 10)
    buttons = []
    lines = ["👥 لیستی بەکارهێنەران"]
    for row in rows:
        uid = int(row["user_id"])
        name = (row.get("name") or "بێ ناو").replace("\n", " ")[:30]
        username = ("@" + row["username"]) if row.get("username") else "بێ یوزەرنەیم"
        lines.append(f"\n• {name} — {username}\nID: {uid}")
        action = "unban" if is_banned(uid) else "ban"
        label = "🔓 لابردنی بەند" if action == "unban" else "⛔ بەندکردن"
        buttons.append([InlineKeyboardButton(f"{label}: {uid}", callback_data=f"ad:{action}:{uid}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️ پێشوو", callback_data=f"ad:users:{page-1}"))
    if len(rows) == 10: nav.append(InlineKeyboardButton("دواتر ➡️", callback_data=f"ad:users:{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 گەڕانەوە", callback_data="ad:home")])
    text = "\n".join(lines) if rows else "👥 هیچ بەکارهێنەرێک لەم لاپەڕەیەدا نییە."
    if edit: await update.callback_query.edit_message_text(text, reply_markup=ik(buttons))
    else: await update.effective_message.reply_text(text, reply_markup=ik(buttons))


async def admin_stats(update, edit=False):
    stats = get_admin_stats()
    text = ("📊 ئاماری بۆت\n\n"
            f"👥 بەکارهێنەران: {stats['users']}\n"
            f"⭐ دڵخوازەکان: {stats['favorites']}\n"
            f"📍 تۆماری دوا خوێندنەوە: {stats['last_reads']}\n"
            f"⛔ بەندکراوەکان: {stats['banned']}\n"
            "📖 ئایەت: 6236\n📚 فەرموودە: 400")
    markup = ik([[InlineKeyboardButton("🔙 گەڕانەوە", callback_data="ad:home")]])
    if edit: await update.callback_query.edit_message_text(text, reply_markup=markup)
    else: await update.effective_message.reply_text(text, reply_markup=markup)


async def cmd_cancel(update, context):
    if context.user_data.pop("feedback_waiting", None):
        context.user_data.pop("feedback_category", None)
        return await update.effective_message.reply_text("❎ ناردنی پەیام هەڵوەشایەوە.")
    if context.user_data.pop("feedback_reply_to", None):
        return await update.effective_message.reply_text("❎ وەڵامدانەوە هەڵوەشایەوە.")
    if context.user_data.pop("admin_broadcast_waiting", None):
        return await update.effective_message.reply_text("❎ ناردنی پەیامی گشتی هەڵوەشایەوە.")
    await update.effective_message.reply_text("هیچ کردارێکی چاوەڕوانکراو نییە.")


async def cmd_admin(update,context):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("⛔ دەسەڵاتی بەڕێوەبەریت نییە.")
    args = context.args
    if args and args[0] == "ban" and len(args) > 1:
        uid = int(args[1]); ban_user(uid, "لە لایەن بەڕێوەبەرەوە")
        return await update.effective_message.reply_text(f"⛔ بەکارهێنەری {uid} بەند کرا.")
    if args and args[0] == "unban" and len(args) > 1:
        uid = int(args[1]); unban_user(uid)
        return await update.effective_message.reply_text(f"🔓 بەندی بەکارهێنەری {uid} لابرا.")
    if args and args[0] == "broadcast":
        context.user_data["admin_broadcast_waiting"] = True
        return await update.effective_message.reply_text("📢 تکایە پەیامەکە بنووسە. بۆ هەڵوەشاندنەوە /cancel بنووسە.")
    await update.effective_message.reply_text(
        f"🛠 بەشی بەڕێوەبەر\n\n👥 ژمارەی بەکارهێنەران: {get_user_count()}\n📖 ئایەت: 6236\n📚 فەرموودە: 400",
        reply_markup=admin_keyboard())


async def admin_broadcast(update, context, message):
    context.user_data.pop("admin_broadcast_waiting", None)
    users = list_users(10000, 0)
    sent = failed = 0
    for row in users:
        uid = int(row["user_id"])
        if is_banned(uid): continue
        try:
            await context.bot.send_message(chat_id=uid, text=message)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)
    await update.effective_message.reply_text(f"📢 تەواو بوو.\n✅ گەیشتە: {sent}\n⚠️ نەگەیشتە: {failed}")


async def block_banned(update, context):
    user = update.effective_user
    if user and is_banned(user.id):
        if update.callback_query:
            await update.callback_query.answer("⛔ دەستگەیشتنت بە بۆت سنووردار کراوە.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("⛔ دەستگەیشتنت بە بۆت سنووردار کراوە.")
        raise ApplicationHandlerStop


async def error_handler(update,context):
    log.exception("Unhandled bot error",exc_info=context.error)

async def prayer_notification_loop(app):
    """Send each enabled user one Telegram reminder at each daily prayer time."""
    prayer_fields = [
        ("fajr", 1, "بەیانی"),
        ("dhuhr", 3, "نیوەڕۆ"),
        ("asr", 4, "عەسر"),
        ("maghrib", 5, "ئێوارە"),
        ("isha", 6, "عیشا"),
    ]
    while True:
        try:
            now = datetime.now(TZ)
            today = now.strftime("%m-%d")
            prayer_date = now.strftime("%Y-%m-%d")
            current_hm = now.strftime("%H:%M")
            subscribers = await asyncio.to_thread(list_prayer_notification_users)
            city_times = {}
            for subscriber in subscribers:
                uid = int(subscriber["user_id"])
                city = subscriber.get("city")
                if not city:
                    continue
                if city not in city_times:
                    try:
                        with db("katenwezh62.db") as conn:
                            exists = conn.execute(
                                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (city,)
                            ).fetchone()
                            if not exists:
                                city_times[city] = {}
                            else:
                                row = conn.execute(
                                    f'SELECT D,bayani,xorhalatn,niwaro,asr,eywara,esha FROM "{city}" WHERE D=?',
                                    (today,)
                                ).fetchone()
                                city_times[city] = row or {}
                    except Exception:
                        log.exception("Could not read prayer times for city %s", city)
                        city_times[city] = {}
                row = city_times[city]
                if not row:
                    continue
                for prayer_key, column_index, prayer_name in prayer_fields:
                    raw_time = str(row[column_index] or "").strip()
                    prayer_hm = raw_time[:5]
                    try:
                        prayer_clock = datetime.strptime(prayer_hm, "%H:%M").time()
                        prayer_at = now.replace(
                            hour=prayer_clock.hour, minute=prayer_clock.minute,
                            second=0, microsecond=0
                        )
                    except ValueError:
                        continue
                    # The GitHub Actions runner may restart on its hourly schedule.
                    # A five-minute grace window prevents missing a reminder during restart.
                    delay_seconds = (now - prayer_at).total_seconds()
                    if delay_seconds < 0 or delay_seconds > 300:
                        continue
                    try:
                        claimed = await asyncio.to_thread(
                            claim_prayer_notification, uid, prayer_date, prayer_key
                        )
                        if not claimed:
                            continue
                        await app.bot.send_message(
                            chat_id=uid,
                            text=f"🕌 ئێستا کاتی بانگی *{prayer_name}* ـە.\n\nخوا نوێژ و دوعاکانتان قبوڵ بکات. 🤲",
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    except Exception:
                        log.exception("Prayer notification failed for user %s (%s)", uid, prayer_key)
        except Exception:
            log.exception("Prayer notification worker iteration failed")
        await asyncio.sleep(25)


async def runtime_heartbeat_loop():
    while True:
        try:
            await asyncio.to_thread(touch_runtime_heartbeat, "running")
        except Exception:
            log.exception("Runtime heartbeat update failed")
        await asyncio.sleep(60)


async def post_init(app):
    try:
        await asyncio.to_thread(touch_runtime_heartbeat, "running")
    except Exception:
        log.exception("Initial runtime heartbeat failed; continuing bot startup")
    app.create_task(runtime_heartbeat_loop(), name="runtime-heartbeat-loop")
    app.create_task(prayer_notification_loop(app), name="prayer-notification-loop")
    await app.bot.set_my_commands([
        BotCommand("start","دەستپێکردن"), BotCommand("menu","مێنیوی سەرەکی"),
        BotCommand("search","گەڕان لە ناوەڕۆک"), BotCommand("quran","قورئان"),
        BotCommand("prayer","کاتەکانی بانگ"), BotCommand("favorites","دڵخوازەکان"),
        BotCommand("lastread","دوا خوێندنەوە"), BotCommand("settings","ڕێکخستن"), BotCommand("hide","شاردنەوەی مێنیو"), BotCommand("help","یارمەتی")
    ])

async def menu_cmd(update,context):
    user = update.effective_user
    await asyncio.to_thread(save_user, user.id, user.first_name or "", user.username or "")
    await update.effective_message.reply_text("📚 *مێنیوی سەرەکی*\n\n👇 بەشی دڵخوازت هەڵبژێرە بۆ دەستپێکردن.", reply_markup=main_keyboard(user.id), parse_mode=ParseMode.MARKDOWN)


async def hide_menu_cmd(update,context):
    await update.effective_message.reply_text("مێنیوی سەرەکی شاردراوەتەوە.\n\n📌 بۆ پیشاندانی دووبارە، /menu بنووسە.", reply_markup=ReplyKeyboardRemove())
async def quran_cmd(update,context): await show_suras(update)
async def prayer_cmd(update,context):
    city=get_city(update.effective_user.id)
    if city: await prayer_times(update,city)
    else: await prayer_city_list(update)
async def help_cmd(update,context):
    await update.effective_message.reply_text("/start — دەستپێکردن\n/menu — مێنیوی سەرەکی\n/quran — قورئان\n/prayer — کاتەکانی بانگ\n/favorites — دڵخوازەکان\n/lastread — دوا خوێندنەوە\n/settings — ڕێکخستن\n/search — گەڕان\n\nهەموو دوگمەکان لە مێنیوی سەرەکی بەردەستن.",reply_markup=main_keyboard(update.effective_user.id))

def main():
    init_user_features()
    if not TOKEN:
        raise SystemExit("BOT_TOKEN environment variable is required.")
    if not is_configured():
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are required.")
    # Process independent updates concurrently instead of making every user
    # wait behind a slow network/database operation from another update.
    app=Application.builder().token(TOKEN).post_init(post_init).concurrent_updates(16).build()
    app.add_handler(MessageHandler(filters.ALL, membership_gate), group=-2)
    app.add_handler(CallbackQueryHandler(membership_gate), group=-2)
    app.add_handler(MessageHandler(filters.ALL, block_banned), group=-1)
    app.add_handler(CallbackQueryHandler(block_banned), group=-1)
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("menu",menu_cmd)); app.add_handler(CommandHandler("hide",hide_menu_cmd)); app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(CommandHandler("quran",quran_cmd)); app.add_handler(CommandHandler("prayer",prayer_cmd)); app.add_handler(CommandHandler("search",cmd_search)); app.add_handler(CommandHandler("admin",cmd_admin)); app.add_handler(CommandHandler("cancel",cmd_cancel))
    app.add_handler(CommandHandler("favorites",show_favorites)); app.add_handler(CommandHandler("lastread",show_last_read)); app.add_handler(CommandHandler("settings",show_settings))
    app.add_handler(CallbackQueryHandler(callback)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text)); app.add_error_handler(error_handler)
    log.info("ڕێگای ئیسلام bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES,drop_pending_updates=False)

if __name__ == "__main__": main()
