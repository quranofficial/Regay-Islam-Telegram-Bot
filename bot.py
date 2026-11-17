"""ڕێگای ئیسلام — Telegram edition, built from the supplied Android app data."""
from __future__ import annotations
import os, json, math, sqlite3, logging, asyncio, io, urllib.request, calendar
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from supabase_store import (is_configured, save_user, get_city, set_city, get_prayer_notifications, set_prayer_notifications, list_prayer_notification_users, claim_prayer_notification, init_user_features, save_last_read, add_favorite, remove_favorite, list_favorites, get_last_read, get_tasbih, change_tasbih, reset_tasbih, get_user_count, list_users, get_admin_stats, is_banned, ban_user, unban_user)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Baghdad"))
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("regay_islam")

# JSON collections copied without content rewriting from the supplied app.
JSON_FILES = {
    "farmwda": ("فەرموودەی پێغەمبەر ﷺ", "farmwda.json"),
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
    "zianakanygorani": ("ژیان و گۆرانی", "zianakanygorani.json"),
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
        _json_cache[key] = value if isinstance(value, list) else []
    return _json_cache[key]

def db(name: str):
    return sqlite3.connect(f"file:{DATA / name}?mode=ro", uri=True, timeout=10)

def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📖 قورئانی پیرۆز"), KeyboardButton("🕌 کاتەکانی بانگ")],
        [KeyboardButton("🕋 ئایەتی کورسی"), KeyboardButton("🗓 کاتەکانی بانگی مانگانە")],
        [KeyboardButton("🧭 ئاراستەی قیبلە"), KeyboardButton("📿 تەسبیح و زیکر")],
        [KeyboardButton("🤲 دوعاکان"), KeyboardButton("📚 کتێب و فەرموودە")],
        [KeyboardButton("🌙 ڕەمەزان"), KeyboardButton("✨ ناوەکانی خودا")],
        [KeyboardButton("🧠 تاقیکردنەوە"), KeyboardButton("🎙️ قارییەکان")],
        [KeyboardButton("🔎 گەڕان"), KeyboardButton("📚 هەموو بابەتەکان")],
        [KeyboardButton("⭐ دڵخوازەکان"), KeyboardButton("📍 دوا خوێندنەوە")],
        [KeyboardButton("⚙️ ڕێکخستن"), KeyboardButton("ℹ️ دەربارەی بۆت")]
    ], resize_keyboard=True, is_persistent=True)

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user=update.effective_user
    save_user(user.id, user.first_name or "", user.username or "")
    text=("🕌 *بەخێربێیت بۆ ڕێگای ئیسلام*\n\n"
          "ئەم بۆتە وەشانی Telegram ـی ئەپی ڕێگای ئیسلامە. زانیاری و ناوەڕۆکی بنەڕەتی لە سەرچاوەی ئەپەکەتەوە گوازراوەتەوە.\n\n"
          "📖 قورئان و ڕوونکردنەوە\n🕌 کاتەکانی بانگ بۆ شارەکانی کوردستان\n🧭 قیبلە، دوعا، زیکر و تەسبیح\n📚 فەرموودە، کتێب و بابەتە ئایینییەکان\n🌙 ڕەمەزان و ناوەکانی خودا\n\nهەڵبژاردنێک لە مێنیوەکە بکە.")
    await update.effective_message.reply_text(text, reply_markup=main_keyboard(), parse_mode=ParseMode.MARKDOWN)

async def show_favorites(update, context=None):
    uid = update.effective_user.id
    rows = list_favorites(uid)
    if not rows:
        return await update.effective_message.reply_text(
            "⭐ هێشتا هیچ ئایەتێکت زیاد نەکردووە بۆ دڵخوازەکان.",
            reply_markup=ik([[InlineKeyboardButton("📖 کردنەوەی قورئان", callback_data="q:s:0")]]))
    buttons = []
    for fid, sid, ayah, title in rows:
        buttons.append([
            InlineKeyboardButton(f"⭐ {title}"[:58], callback_data=f"fv:open:{sid}:{ayah}"),
            InlineKeyboardButton("🗑", callback_data=f"fv:del:{fid}")
        ])
    await update.effective_message.reply_text(
        f"⭐ *دڵخوازەکانت*\n{len(rows)} ئایەت — بۆ کردنەوە ناوی ئایەتەکە هەڵبژێرە.",
        reply_markup=ik(buttons), parse_mode=ParseMode.MARKDOWN)


async def show_last_read(update, context=None):
    row = get_last_read(update.effective_user.id)
    if not row:
        return await update.effective_message.reply_text(
            "📍 هێشتا شوێنی خوێندنەوەیەکت تۆمار نەکراوە. سوڕەتێک بکەرەوە و خوێندنەوەت دەست پێ بکە.")
    await show_ayahs(update, int(row[0]), int(row[1]))


async def show_settings(update, context=None):
    uid = update.effective_user.id
    city = get_city(uid)
    city_label = city or "دیاری نەکراوە"
    row = get_tasbih(uid)
    tasbih_count = row[0] if row else 0
    notifications = get_prayer_notifications(uid)
    notify_label = "🟢 چالاکە" if notifications else "🔴 ناچالاکە"
    notify_action = "off" if notifications else "on"
    await update.effective_message.reply_text(
        f"⚙️ *ڕێکخستنەکانی من*\n\n🏙 شاری هەڵبژێردراو: {city_label}\n📿 ژمارەی تەسبیح: {tasbih_count}\n🔔 ئاگادارکردنەوەی کاتی بانگ: {notify_label}\n\nدەتوانیت شاری خۆت بگۆڕیت؛ ئەو شارە بۆ کاتەکانی بانگ و قیبلە و ئاگادارکردنەوە بەکاردێت.",
        reply_markup=ik([
            [InlineKeyboardButton("🏙 گۆڕینی شار", callback_data="st:city")],
            [InlineKeyboardButton(("🔕 ناچالاککردنی ئاگادارکردنەوە" if notifications else "🔔 چالاککردنی ئاگادارکردنەوە"), callback_data=f"st:notify:{notify_action}")],
            [InlineKeyboardButton("⭐ دڵخوازەکان", callback_data="fv:list")],
            [InlineKeyboardButton("📍 دوا خوێندنەوە", callback_data="lr")]
        ]), parse_mode=ParseMode.MARKDOWN)


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
        reply_markup=ik([[InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان", callback_data="fv:add:2:255")]]),
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
    buttons.append([InlineKeyboardButton("🔙 لیستی سوڕەتەکان",callback_data="q:s:0")])
    text="\n\n".join(parts)
    if edit: await update.callback_query.edit_message_text(text,reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)
    else: await update.effective_message.reply_text(text,reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)

async def show_tafsir(update,sid,ayah):
    save_last_read(update.effective_user.id, sid, ((ayah-1)//8)*8)
    with db("regayislam.db") as c:
        r=c.execute("SELECT sura_name_ar,text,rebar,raman,puxta,asan,sanahi,hazhar,zhin,maiser,roshn,tawhid FROM ayah_text WHERE suraId=? AND ayah=?",(sid,ayah)).fetchone()
    if not r: return await update.callback_query.answer("ئایەت نەدۆزرایەوە",show_alert=True)
    labels=["ڕوونکردنەوە ١","ڕوونکردنەوە ٢","پوختە","ڕوونکردنەوە ٣","ڕوونکردنەوە ٤","ڕوونکردنەوە ٥","ڕوونکردنەوە ٦","ڕوونکردنەوە ٧","ڕوونکردنەوە ٨","ڕوونکردنەوە ٩","ڕوونکردنەوە ١٠"]
    fields=r[2:]
    text=f"📖 {r[0]} — ئایەتی {ayah}\n\n{r[1]}\n"
    for label,value in zip(labels,fields):
        if value and str(value).strip(): text+=f"\n{label}:\n{str(value)[:2500]}\n"
    await update.effective_message.reply_text(text[:3900],reply_markup=ik([[InlineKeyboardButton("⭐ زیادکردن بۆ دڵخوازەکان",callback_data=f"fv:add:{sid}:{ayah}")],[InlineKeyboardButton("🔙 گەڕانەوە بۆ ئایەتەکان",callback_data=f"q:a:{sid}:{((ayah-1)//8)*8}")]]),disable_web_page_preview=True)

async def prayer_city_list(update, page=0, edit=False, mode="prayer"):
    cities=get_cities(); chunk=cities[page*12:(page+1)*12]
    prefix = "qc" if mode == "qibla" else ("mc" if mode == "month" else "pc")
    rows=[[InlineKeyboardButton(name,callback_data=f"{prefix}:{table}")] for name,table,lat,lon in chunk]
    nav=[]
    if page: nav.append(InlineKeyboardButton("⬅️",callback_data=f"pcl:{mode}:{page-1}"))
    if (page+1)*12<len(cities): nav.append(InlineKeyboardButton("➡️",callback_data=f"pcl:{mode}:{page+1}"))
    if nav: rows.append(nav)
    text="🕌 *شارەکەت هەڵبژێرە بۆ کاتەکانی بانگ:*"
    if edit: await update.callback_query.edit_message_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)
    else: await update.effective_message.reply_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)

async def prayer_times(update, city, edit=False):
    city_names={x.get("Name"):x.get("id") for x in load_json("cityme") if isinstance(x,dict)}
    city_display=next((name for name,table in city_names.items() if str(table).casefold()==str(city).casefold()),city)
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
        msg=f"🕌 *کاتەکانی بانگ — {cityname}*\n📅 {datetime.now(TZ).strftime('%Y-%m-%d')}\n\n"
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
    city_names = {x.get("Name"): x.get("id") for x in load_json("cityme") if isinstance(x, dict)}
    city_display = next((name for name, table in city_names.items() if str(table).casefold() == str(city).casefold()), city)
    days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
    with db("katenwezh62.db") as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (city,)
        ).fetchone()
        if not exists:
            return await update.effective_message.reply_text("خشتەی بانگ بۆ ئەم شارە بەردەست نییە.")
        rows = conn.execute(
            f'SELECT D,bayani,niwaro,asr,eywara,esha FROM "{city}" WHERE D LIKE ? ORDER BY ID',
            (month_key + "-%",),
        ).fetchall()
    by_day = {int(str(row[0]).split("-")[1]): row[1:] for row in rows}
    lines = [
        f"🗓 *کاتەکانی بانگی مانگانە — {city_display}*",
        f"📅 {month_date:%Y-%m}",
        "",
        "ڕۆژ | بەیانی | نیوەڕۆ | عەسر | ئێوارە | عیشا",
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


async def request_qibla_location(update):
    """Ask Telegram to share the user's live location for a more precise Qibla bearing."""
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 ناردنی شوێنی من بۆ قیبلە", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.effective_message.reply_text(
        "🧭 بۆ دۆزینەوەی ئاراستەی وردتری قیبلە، شوێنی ئێستات بنێرە. شوێنەکەت تەنها بۆ هەژمارکردنی قیبلە بەکاردێت.",
        reply_markup=keyboard,
    )


async def handle_location(update, context):
    location = update.effective_message.location
    if not location:
        return
    lat, lon = math.radians(location.latitude), math.radians(location.longitude)
    kaaba_lat, kaaba_lon = math.radians(21.4225), math.radians(39.8262)
    dlon = kaaba_lon - lon
    y = math.sin(dlon)
    x = math.cos(lat) * math.tan(kaaba_lat) - math.sin(lat) * math.cos(dlon)
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    directions = ["باكوور", "ڕۆژهەڵات", "باشوور", "ڕۆژئاوا"]
    cardinal = directions[round(bearing / 90) % 4]
    await update.effective_message.reply_text(
        f"🧭 *ئاراستەی قیبلە بە شوێنی ئێستات*\n\n"
        f"📍 وردی شوێن: {location.horizontal_accuracy or 'نەزانراو'} مەتر\n"
        f"زاویەی قیبلە: *{bearing:.1f}°* لە باکووری ڕاستەقینەوە\n"
        f"ئاراستەی گشتی: *{cardinal}*\n\n"
        "_مۆبایلەکەت بۆ ئاراستەکردنی جەستەیی پێویستی بە قطب‌نما و ڕێکخستنی دروستی هەیە._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove(),
    )


async def qibla(update, city=None):
    if not city: city=get_city(update.effective_user.id)
    if not city:
        await prayer_city_list(update,mode="qibla"); return
    city_names={x.get("Name"):x.get("id") for x in load_json("cityme") if isinstance(x,dict)}
    city_display=next((name for name,table in city_names.items() if str(table).casefold()==str(city).casefold()),city)
    with db("katenwezh62.db") as c:
        r=c.execute("SELECT latitude,longitude FROM cities WHERE city=?",(city_display,)).fetchone()
        n=(city_display,)
    if not r or r[0] is None or r[1] is None:
        await update.effective_message.reply_text("شوێنی جوگرافی ئەم شارە لە داتابەیسی ئەپەکەدا بەردەست نییە. شارێکی تر هەڵبژێرە."); return
    lat,lon=map(math.radians,r)
    kaaba_lat,kaaba_lon=map(math.radians,(21.4225,39.8262))
    dlon=kaaba_lon-lon
    y=math.sin(dlon); x=math.cos(lat)*math.tan(kaaba_lat)-math.sin(lat)*math.cos(dlon)
    bearing=(math.degrees(math.atan2(y,x))+360)%360
    dirs=["باكوور","ڕۆژهەڵات","باشوور","ڕۆژئاوا"]
    cardinal=dirs[round(bearing/90)%4]
    await update.effective_message.reply_text(f"🧭 *ئاراستەی قیبلە — {n[0]}*\n\nئاراستەی قیبلە: *{bearing:.1f}°* لە باكووری ڕاستەقینەوە\nئاراستەی گشتی: *{cardinal}*\n\n_ئەم ژمارەیە لە کۆئۆردیناتی شاری هەڵبژێردراوەوە هەژمار کراوە؛ بۆ وردی زیاتر لەسەر شوێنی خۆت پێویستە GPS بەکاربهێنیت._",parse_mode=ParseMode.MARKDOWN,reply_markup=ik([[InlineKeyboardButton("گۆڕینی شار",callback_data="pcl:qibla:0")]]))

async def send_asset_file(update, context, item):
    """Download a media asset and send it as a Telegram file, never as a URL."""
    url = str(item.get("link") or item.get("url") or "").strip()
    if not url.startswith(("https://", "http://")):
        await update.effective_message.reply_text("⚠️ لینکی دروستی بۆ ئەم فایلە بەردەست نییە.")
        return False
    filename = str(item.get("namefile") or url.split("?", 1)[0].rsplit("/", 1)[-1] or "file").strip()
    suffix = Path(filename).suffix.lower()
    title = str(item.get("title") or item.get("name") or filename).strip()
    try:
        def download_asset():
            request = urllib.request.Request(url, headers={"User-Agent": "Regay-Islam-Telegram-Bot/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read(50 * 1024 * 1024 + 1)
            if not payload or len(payload) > 50 * 1024 * 1024:
                raise ValueError("Empty asset or asset exceeds Telegram bot upload limit")
            return payload
        payload = await asyncio.to_thread(download_asset)
        stream = io.BytesIO(payload)
        stream.name = filename
        chat_id = update.effective_chat.id
        if suffix in (".mp3", ".m4a", ".wav", ".ogg", ".flac"):
            await context.bot.send_audio(chat_id=chat_id, audio=stream, caption=title[:1024], title=title[:64])
        elif suffix in (".mp4", ".mov", ".m4v"):
            await context.bot.send_video(chat_id=chat_id, video=stream, caption=title[:1024])
        elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
            await context.bot.send_photo(chat_id=chat_id, photo=stream, caption=title[:1024])
        else:
            await context.bot.send_document(chat_id=chat_id, document=stream, caption=title[:1024], filename=filename)
        return True
    except Exception:
        log.exception("Could not download/send asset: %s", filename)
        await update.effective_message.reply_text("⚠️ ناردنی فایلەکە سەرکەوتوو نەبوو. تکایە دواتر دووبارە هەوڵ بدە.")
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
            rows.append([InlineKeyboardButton("🔙 لیستی بابەتەکان",callback_data=f"jl:{key}:0")])
            await update.effective_message.reply_text(f"📎 {title}",reply_markup=ik(rows))
            return
        body=item.get('text') or item.get('desc') or item.get('wata') or item.get('du3a') or item.get('tag') or ""
        extras=[]
        for k,v in item.items():
            if k not in {'title','name','name_ar','text','desc','wata','du3a','_id','id','sc','tag','url','link','namefile'} and v not in (None,''):
                extras.append(f"{k}: {v}")
        text=f"*{title}*\\n\\n{body}"
        if extras: text+='\\n\\n'+'\\n'.join(extras)
    else: text=f"*{JSON_FILES[key][0]}*\\n\\n{item}"
    nav=[]
    if index>0: nav.append(InlineKeyboardButton("⬅️ پێشوو",callback_data=f"j:{key}:{index-1}"))
    if index+1<len(data): nav.append(InlineKeyboardButton("دواتر ➡️",callback_data=f"j:{key}:{index+1}"))
    rows=[nav] if nav else []
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
    for i,item in enumerate(reciters[start:start+10],start=start):
        label=str(item.get("name_ar") or f"قاری {i+1}").strip()
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
        audio_file=io.BytesIO(audio_data)
        audio_file.name=f"{sid:03d}.mp3"
        await context.bot.send_audio(chat_id=update.effective_chat.id,audio=audio_file,title=f"{surah_name} — {qari_name}"[:64],performer=qari_name[:64],caption=f"📖 سوڕەتی {surah_name}\n🎙️ قاری: {qari_name}")
    except Exception:
        log.exception("Could not download or send recitation audio: %s",audio_url)
        await update.effective_message.reply_text("⚠️ ناردنی فایلەکە سەرکەوتوو نەبوو. تکایە دواتر دووبارە هەوڵ بدە.",reply_markup=ik([[InlineKeyboardButton("🔙 گەڕانەوە بۆ سوڕەتەکان",callback_data=f"qr:pick:{index}")]]))

async def content_menu(update):
    rows=[]
    keys=list(JSON_FILES)
    for i in range(0,len(keys),2):
        row=[InlineKeyboardButton(JSON_FILES[k][0],callback_data=f"jl:{k}:0") for k in keys[i:i+2]]
        rows.append(row)
    await update.effective_message.reply_text("📚 *هەموو بابەتە ئایینییەکان*\nبابەتێک هەڵبژێرە:",reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)

async def show_names(update,index=0):
    with db("name.db") as c: r=c.execute("SELECT arabic,surah_ayah,sorani,badini,english,farsi FROM name ORDER BY _id LIMIT 1 OFFSET ?",(index,)).fetchone()
    if not r: return
    text=f"✨ *ناوەکانی خودا — {index+1}/100*\n\n*{r[0]}*\nشوێنی ئاماژە: {r[1]}\n\n{r[2]}\n\n{r[3]}\n\n_{r[4]} — {r[5]}_"
    rows=[]
    nav=[]
    if index: nav.append(InlineKeyboardButton("⬅️",callback_data=f"nm:{index-1}"))
    if index<99: nav.append(InlineKeyboardButton("➡️",callback_data=f"nm:{index+1}"))
    if nav: rows.append(nav)
    await update.effective_message.reply_text(text,reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)

async def show_dua(update,index=0):
    with db("duha.db") as c: r=c.execute("SELECT du3a,wata FROM du3a ORDER BY id LIMIT 1 OFFSET ?",(index,)).fetchone()
    if not r: return
    text=f"🤲 *دوعا — {index+1}/56*\n\n{r[0]}\n\n*واتا:*\n{r[1]}"
    nav=[]
    if index: nav.append(InlineKeyboardButton("⬅️",callback_data=f"du:{index-1}"))
    if index<55: nav.append(InlineKeyboardButton("➡️",callback_data=f"du:{index+1}"))
    await update.effective_message.reply_text(text,reply_markup=ik([nav] if nav else []),parse_mode=ParseMode.MARKDOWN)

async def books_menu(update):
    with db("mu.db") as c: rows=c.execute("SELECT i,title,tag FROM sarki ORDER BY i").fetchall()
    buttons=[[InlineKeyboardButton(f"{title} ({tag})",callback_data=f"bc:{tag}:0")] for i,title,tag in rows]
    await update.effective_message.reply_text("📚 *کتێب و فەرموودە*\nبەشێک هەڵبژێرە:",reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)

async def book_list(update,tag,page=0):
    with db("mu.db") as c:
        # Tag values are read from the bundled DB, but still validate against the whitelist.
        tags={r[0] for r in c.execute("SELECT tag FROM sarki")}
        if tag not in tags: return await update.callback_query.answer("بەش نەدۆزرایەوە",show_alert=True)
        rows=c.execute("SELECT _id,sarder FROM babat WHERE dlxwaz=? ORDER BY _id LIMIT 12 OFFSET ?",(tag,page*12)).fetchall()
        total=c.execute("SELECT count(*) FROM babat WHERE dlxwaz=?",(tag,)).fetchone()[0]
    buttons=[[InlineKeyboardButton(str(title)[:58],callback_data=f"bi:{bid}")] for bid,title in rows]
    nav=[]
    if page: nav.append(InlineKeyboardButton("⬅️",callback_data=f"bc:{tag}:{page-1}"))
    if (page+1)*12<total: nav.append(InlineKeyboardButton("➡️",callback_data=f"bc:{tag}:{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 بەشەکان",callback_data="bm")])
    await update.callback_query.edit_message_text(f"📚 *{tag}* — {total} بابەت",reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)

async def book_item(update,bid):
    with db("mu.db") as c: r=c.execute("SELECT sarder,drezha FROM babat WHERE _id=?",(bid,)).fetchone()
    if not r: return await update.callback_query.answer("بابەت نەدۆزرایەوە",show_alert=True)
    await update.effective_message.reply_text(f"📚 {r[0]}\n\n{r[1][:3700]}",disable_web_page_preview=True)

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
        await update.callback_query.edit_message_text(f"🕋 {title}\nبابەتێک هەڵبژێرە:",reply_markup=ik(buttons))
    else:
        await update.effective_message.reply_text(f"🕋 {title}\n\n{body[:3700]}",disable_web_page_preview=True)

async def repentance_subitem(update,table,index):
    allowed={"bochetawbabkain","chontawbabkam","marjakanitawba","neshanayqbulitawba"}
    if table not in allowed: return await update.callback_query.answer("بەش نەدۆزرایەوە",show_alert=True)
    with db("garanawa.db") as c: row=c.execute(f'SELECT title,desc FROM "{table}" ORDER BY _id LIMIT 1 OFFSET ?',(index,)).fetchone()
    if row: await update.effective_message.reply_text(f"{row[0]}\n\n{row[1][:3700]}",disable_web_page_preview=True)

async def ramadan_menu(update):
    with db("ramazanew.db") as c:
        rows=c.execute("SELECT titles,tableName FROM Titles ORDER BY _id").fetchall()
    buttons=[[InlineKeyboardButton(title.strip(),callback_data=f"rd:{table}:0")] for title,table in rows]
    await update.effective_message.reply_text("🌙 *بابەتەکانی ڕەمەزان*",reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)

async def ramadan_list(update,table,page=0):
    allowed={r[0] for r in db("ramazanew.db").execute("SELECT tableName FROM Titles")}
    if table not in allowed: return await update.callback_query.answer("بابەت نەدۆزرایەوە",show_alert=True)
    with db("ramazanew.db") as c:
        rows=c.execute(f'SELECT _id,title FROM "{table}" ORDER BY _id LIMIT 10 OFFSET ?',(page*10,)).fetchall()
        total=c.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    buttons=[[InlineKeyboardButton(str(title)[:58],callback_data=f"ri:{table}:{rid}")] for rid,title in rows]
    nav=[]
    if page: nav.append(InlineKeyboardButton("⬅️",callback_data=f"rd:{table}:{page-1}"))
    if (page+1)*10<total: nav.append(InlineKeyboardButton("➡️",callback_data=f"rd:{table}:{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 ڕەمەزان",callback_data="rm")])
    await update.callback_query.edit_message_text("🌙 *بابەتەکانی ڕەمەزان*",reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)

async def ramadan_item(update,table,rid):
    allowed={r[0] for r in db("ramazanew.db").execute("SELECT tableName FROM Titles")}
    if table not in allowed: return await update.callback_query.answer("بابەت نەدۆزرایەوە",show_alert=True)
    with db("ramazanew.db") as c: row=c.execute(f'SELECT title,desc FROM "{table}" WHERE _id=?',(rid,)).fetchone()
    if row: await update.effective_message.reply_text(f"🌙 {row[0]}\n\n{row[1][:3700]}",disable_web_page_preview=True)

async def quiz_start(update,context):
    with db("surat.db") as c: rows=c.execute("SELECT soraid,name,aya FROM surat ORDER BY soraid").fetchall()
    import random
    target=random.choice(rows); choices=[target]+random.sample([r for r in rows if r[0]!=target[0]],3); random.shuffle(choices)
    context.user_data["quiz_answer"]=target[0]
    buttons=[[InlineKeyboardButton(r[1],callback_data=f"qa:{r[0]}")] for r in choices]
    await update.effective_message.reply_text(f"🧠 *تاقیکردنەوەی ئیسلامی*\n\nئەم سوڕەتە {target[2]} ئایەتی هەیە؟ ناوی سوڕەتەکە هەڵبژێرە:",reply_markup=ik(buttons),parse_mode=ParseMode.MARKDOWN)

async def quiz_answer(update,context,sid):
    correct=context.user_data.pop("quiz_answer",None)
    if correct is None: return await update.callback_query.answer("تاقیکردنەوەکە کۆتایی هاتووە",show_alert=True)
    if sid==correct: msg="✅ ڕاستە! وەڵامەکەت دروستە."
    else:
        with db("surat.db") as c: name=c.execute("SELECT name FROM surat WHERE soraid=?",(correct,)).fetchone()[0]
        msg=f"❌ وەڵامەکەت هەڵەیە. وەڵامی ڕاست: {name}"
    await update.effective_message.reply_text(msg,reply_markup=ik([[InlineKeyboardButton("🔁 تاقیکردنەوەیەکی تر",callback_data="qz:new")]]))

async def prayer_reminder_info(update):
    await update.effective_message.reply_text("🔔 *ئاگادارکردنەوەی بانگ*\n\nکاتەکانی بانگ لەم وەشانەدا لە خشتەی داتابەیسی ئەپەکەت پیشان دەدرێن. ئاگادارکردنەوەی ئۆتۆماتیکی لە Telegram پێویستی بە بەردەوام کارکردنی سێرڤەر و ڕێکخستنی job queue هەیە؛ لەم وەشانەدا وەک تایبەتمەندیی چالاک دانەنراوە.")

async def tasbih(update,context,change=0):
    uid=update.effective_user.id
    count=change_tasbih(uid,change)
    rows=[[InlineKeyboardButton("📿 تسبیح +1",callback_data="ts:+"),InlineKeyboardButton("🔄 سفر",callback_data="ts:reset")]]
    await update.effective_message.reply_text(f"📿 *تەسبیحی ئەلیکترۆنی*\n\nژمارەی زیکر: *{count}*\n\nزیکرێک هەڵبژێرە و دوگمەی +1 دابگرە.",reply_markup=ik(rows),parse_mode=ParseMode.MARKDOWN)


async def search_prompt(update, mode):
    context=update.effective_user
    # Set per-chat state in user_data by caller.
    await update.effective_message.reply_text("🔎 وشە یان دەستەواژەکە بنووسە بۆ گەڕان:")

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
    if "search_mode" in context.user_data:
        return await do_search(update,context,text)
    mapping={
        "📖 قورئانی پیرۆز":lambda:show_suras(update),
        "🕌 کاتەکانی بانگ":lambda:prayer_city_list(update),
        "🗓 کاتەکانی بانگی مانگانە":lambda:monthly_prayer_times(update),
        "🕋 ئایەتی کورسی":lambda:show_ayat_kursi(update),
        "🧭 ئاراستەی قیبلە":lambda:request_qibla_location(update),
        "📿 تەسبیح و زیکر":lambda:tasbih(update,context),
        "🤲 دوعاکان":lambda:show_dua(update,0),
        "📚 کتێب و فەرموودە":lambda:books_menu(update),
        "🕋 تەوبە و ئامۆژگاری":lambda:repentance_menu(update),
        "📜 ٤٠٠ فەرموودە":lambda:json_list(update,"farmwda",0),
        "🌙 ڕەمەزان":lambda:ramadan_menu(update),
        "✨ ناوەکانی خودا":lambda:show_names(update,0),
        "🧠 تاقیکردنەوە":lambda:quiz_start(update,context),
        "🎙️ قارییەکان":lambda:show_qari_menu(update,0),
        "📚 هەموو بابەتەکان":lambda:content_menu(update),
        "🔎 گەڕان":lambda:search_choose(update),
        "⭐ دڵخوازەکان":lambda:show_favorites(update),
        "📍 دوا خوێندنەوە":lambda:show_last_read(update),
        "⚙️ ڕێکخستن":lambda:show_settings(update),
        "ℹ️ دەربارەی بۆت":lambda:about(update),
    }
    fn=mapping.get(text)
    if fn: await fn()
    else: await update.effective_message.reply_text("تکایە لە مێنیوەکە هەڵبژێرە یان /start بنووسە.",reply_markup=main_keyboard())

async def search_choose(update):
    await update.effective_message.reply_text("🔎 جۆری گەڕان هەڵبژێرە:",reply_markup=ik([
        [InlineKeyboardButton("گەڕان لە قورئان",callback_data="sm:quran"),InlineKeyboardButton("گەڕان لە هەموو ناوەڕۆک",callback_data="sm:all")],
        [InlineKeyboardButton("گەڕان لە کتێب و فەرموودە",callback_data="sm:books")]
    ]))

async def about(update):
    await update.effective_message.reply_text("🕌 *ڕێگای ئیسلام — وەشانی Telegram*\n\nئەم پڕۆژەیە لەسەر سەرچاوەی ئەپی Android ـی ڕێگای ئیسلام دامەزراوە. زانیارییەکانی قورئان، خشتەی بانگ، کتێب و بابەتەکان لە داتابەیس و فایلەکانی ئەو سەرچاوەیەوە وەرگیراون.\n\nبۆ ئاگاداری و چاکسازی: پەیوەندی بە بەڕێوەبەری بۆت بکە.",parse_mode=ParseMode.MARKDOWN)

async def callback(update: Update,context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    data=q.data or ""
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
        if data.startswith("q:s:"): return await show_suras(update,int(data.split(":")[2]),True)
        if data.startswith("q:a:"):
            _,_,sid,off=data.split(":"); return await show_ayahs(update,int(sid),int(off),True)
        if data.startswith("q:t:"):
            _,_,sid,ay=data.split(":"); return await show_tafsir(update,int(sid),int(ay))
        if data.startswith("pcl:"):
            bits=data.split(":")
            if len(bits)==3: return await prayer_city_list(update,int(bits[2]),True,bits[1])
            return await prayer_city_list(update,int(bits[1]),True)
        if data.startswith("pc:"):
            city=data[3:]; set_city(q.from_user.id,city); return await prayer_times(update,city,True)
        if data.startswith("qc:"):
            city=data[3:]; set_city(q.from_user.id,city); return await qibla(update,city)
        if data.startswith("mc:"):
            city=data[3:]; set_city(q.from_user.id,city); return await monthly_prayer_times(update,city,edit=True)
        if data.startswith("pm:"):
            return await monthly_prayer_times(update,get_city(q.from_user.id),data[3:],edit=True)
        if data.startswith("j:"):
            _,key,index=data.split(":"); return await show_json_item(update,context,key,int(index),True)
        if data.startswith("jl:"):
            _,key,page=data.split(":"); return await json_list(update,key,int(page),True)
        if data.startswith("nm:"): return await show_names(update,int(data.split(":")[1]))
        if data.startswith("du:"): return await show_dua(update,int(data.split(":")[1]))
        if data=="bm": return await books_menu(update)
        if data.startswith("bc:"):
            _,tag,page=data.split(":"); return await book_list(update,tag,int(page))
        if data.startswith("bi:"): return await book_item(update,int(data.split(":")[1]))
        if data == "ts:reset":
            reset_tasbih(q.from_user.id)
            return await tasbih(update,context,0)
        if data.startswith("ts:"):
            n=1 if data.endswith("+") else 0
            return await tasbih(update,context,n)
        if data.startswith("gb:"): return await repentance_item(update,int(data.split(":")[1]))
        if data.startswith("gx:"):
            _,table,index=data.split(":"); return await repentance_subitem(update,table,int(index))
        if data=="rm": return await ramadan_menu(update)
        if data.startswith("rd:"):
            _,table,page=data.split(":"); return await ramadan_list(update,table,int(page))
        if data.startswith("ri:"):
            _,table,rid=data.split(":"); return await ramadan_item(update,table,int(rid))
        if data=="qz:new": return await quiz_start(update,context)
        if data.startswith("qa:"): return await quiz_answer(update,context,int(data.split(":")[1]))
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


async def post_init(app):
    app.create_task(prayer_notification_loop(app), name="prayer-notification-loop")
    await app.bot.set_my_commands([
        BotCommand("start","دەستپێکردن"), BotCommand("menu","مێنیوی سەرەکی"),
        BotCommand("search","گەڕان لە ناوەڕۆک"), BotCommand("quran","قورئان"),
        BotCommand("prayer","کاتەکانی بانگ"), BotCommand("favorites","دڵخوازەکان"),
        BotCommand("lastread","دوا خوێندنەوە"), BotCommand("settings","ڕێکخستن"), BotCommand("help","یارمەتی")
    ])

async def menu_cmd(update,context): await start(update,context)
async def quran_cmd(update,context): await show_suras(update)
async def prayer_cmd(update,context):
    city=get_city(update.effective_user.id)
    if city: await prayer_times(update,city)
    else: await prayer_city_list(update)
async def help_cmd(update,context):
    await update.effective_message.reply_text("/start — دەستپێکردن\n/menu — مێنیوی سەرەکی\n/quran — قورئان\n/prayer — کاتەکانی بانگ\n/favorites — دڵخوازەکان\n/lastread — دوا خوێندنەوە\n/settings — ڕێکخستن\n/search — گەڕان\n\nهەموو دوگمەکان لە مێنیوی سەرەکی بەردەستن.",reply_markup=main_keyboard())

def main():
    init_user_features()
    if not TOKEN:
        raise SystemExit("BOT_TOKEN environment variable is required.")
    if not is_configured():
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are required.")
    app=Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.ALL, block_banned), group=-1)
    app.add_handler(CallbackQueryHandler(block_banned), group=-1)
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("menu",menu_cmd)); app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(CommandHandler("quran",quran_cmd)); app.add_handler(CommandHandler("prayer",prayer_cmd)); app.add_handler(CommandHandler("search",cmd_search)); app.add_handler(CommandHandler("admin",cmd_admin)); app.add_handler(CommandHandler("cancel",cmd_cancel))
    app.add_handler(CommandHandler("favorites",show_favorites)); app.add_handler(CommandHandler("lastread",show_last_read)); app.add_handler(CommandHandler("settings",show_settings))
    app.add_handler(CallbackQueryHandler(callback)); app.add_handler(MessageHandler(filters.LOCATION, handle_location)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text)); app.add_error_handler(error_handler)
    log.info("ڕێگای ئیسلام bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES,drop_pending_updates=False)

if __name__ == "__main__": main()
