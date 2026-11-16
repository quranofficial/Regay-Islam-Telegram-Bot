"""ڕێگای ئیسلام — Telegram edition, built from the supplied Android app data."""
from __future__ import annotations
import os, json, math, sqlite3, logging, asyncio
from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

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
    "duha": ("دوعاکان", "duha.json"),
    "pexambarman": ("ژیاننامەی پێغەمبەر ﷺ", "pexambarman.json"),
    "pexambaran": ("چیرۆکی پێغەمبەران", "pexambaran.json"),
    "haram": ("حەرامکراوەکان", "haram.json"),
    "tawanakan": ("تاوانەکان", "tawanakan.json"),
    "xawn": ("خەوننامە", "xawn.json"),
    "bahasht": ("بەهەشت", "bahasht.json"),
    "dozax": ("دۆزەخ", "dozax.json"),
    "dajal": ("دەربارەی دەججاڵ", "dajal.json"),
    "hawal": ("هاوەڵانی پێغەمبەر ﷺ", "hawal.json"),
    "agr": ("بابەتە ئایینییەکان", "agr.json"),
    "zanyaryquran": ("زانیارییەکانی قورئان", "zanyaryquran.json"),
    "balaposhi": ("بەرگ و پۆشاک لە ئیسلامدا", "balaposhi.json"),
    "rawbochwn": ("ڕاو و بۆچوون", "rawbochwn.json"),
    "swnat": ("سوننەتەکان", "swnat.json"),
    "wta": ("وتە و ئامۆژگاری", "wta.json"),
    "xaybat": ("بابەتەکانی خەبات و ئامۆژگاری", "xaybat.json"),
    "gggg": ("بابەت و فەرموودە", "gggg.json"),
    "girlss": ("بابەتەکانی ئافرەتان", "girlss.json"),
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

def save_user(uid, name, username):
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, city TEXT, tasbih INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        c.execute("INSERT INTO users(user_id,name,username) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,username=excluded.username", (uid,name,username))

def get_city(uid):
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, city TEXT, tasbih INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        r=c.execute("SELECT city FROM users WHERE user_id=?",(uid,)).fetchone()
        return r[0] if r else None

def set_city(uid, city):
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, city TEXT, tasbih INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        c.execute("INSERT INTO users(user_id,city) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET city=excluded.city",(uid,city))



def init_user_features():
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        c.execute("""CREATE TABLE IF NOT EXISTS favorites(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            surah_id INTEGER NOT NULL,
            ayah INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, surah_id, ayah)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS last_read(
            user_id INTEGER PRIMARY KEY,
            surah_id INTEGER NOT NULL,
            ayah_offset INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")

def save_last_read(uid, sid, offset):
    init_user_features()
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        c.execute("""INSERT INTO last_read(user_id,surah_id,ayah_offset) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET surah_id=excluded.surah_id,
            ayah_offset=excluded.ayah_offset, updated_at=CURRENT_TIMESTAMP""",
            (uid, sid, offset))

def add_favorite(uid, sid, ayah, title):
    init_user_features()
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        cur = c.execute("INSERT OR IGNORE INTO favorites(user_id,surah_id,ayah,title) VALUES(?,?,?,?)",
                        (uid, sid, ayah, title))
        return cur.rowcount > 0

def remove_favorite(uid, favorite_id):
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        c.execute("DELETE FROM favorites WHERE id=? AND user_id=?", (favorite_id, uid))

async def show_favorites(update, context=None):
    init_user_features()
    uid = update.effective_user.id
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        rows = c.execute("SELECT id,surah_id,ayah,title FROM favorites WHERE user_id=? ORDER BY id DESC LIMIT 30",
                         (uid,)).fetchall()
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
        f"⭐ *دڵخوازەکانت*\\n{len(rows)} ئایەت — بۆ کردنەوە ناوی ئایەتەکە هەڵبژێرە.",
        reply_markup=ik(buttons), parse_mode=ParseMode.MARKDOWN)

async def show_last_read(update, context=None):
    init_user_features()
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        row = c.execute("SELECT surah_id,ayah_offset FROM last_read WHERE user_id=?",
                        (update.effective_user.id,)).fetchone()
    if not row:
        return await update.effective_message.reply_text(
            "📍 هێشتا شوێنی خوێندنەوەیەکت تۆمار نەکراوە. سوڕەتێک بکەرەوە و خوێندنەوەت دەست پێ بکە.")
    await show_ayahs(update, int(row[0]), int(row[1]))

async def show_settings(update, context=None):
    uid = update.effective_user.id
    city = get_city(uid)
    city_label = city or "دیاری نەکراوە"
    with sqlite3.connect(DATA / "bot_users.sqlite3") as c:
        row = c.execute("SELECT tasbih FROM users WHERE user_id=?", (uid,)).fetchone()
    tasbih_count = row[0] if row else 0
    await update.effective_message.reply_text(
        f"⚙️ *ڕێکخستنەکانی من*\\n\\n🏙 شاری هەڵبژێردراو: {city_label}\\n📿 ژمارەی تەسبیح: {tasbih_count}\\n\\nدەتوانیت شاری خۆت بگۆڕیت؛ ئەو شارە بۆ کاتەکانی بانگ و قیبلە بەکاردێت.",
        reply_markup=ik([
            [InlineKeyboardButton("🏙 گۆڕینی شار", callback_data="st:city")],
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
    prefix="qc" if mode=="qibla" else "pc"
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

async def show_json_item(update,key,index,edit=False):
    data=load_json(key)
    if not data: return await update.effective_message.reply_text("ناوەڕۆک بەردەست نییە.")
    index=max(0,min(index,len(data)-1)); item=data[index]
    if isinstance(item,dict):
        title=item.get('title') or item.get('name') or item.get('name_ar') or f"{JSON_FILES[key][0]} — {index+1}"
        body=item.get('text') or item.get('desc') or item.get('wata') or item.get('du3a') or item.get('tag') or ""
        extras=[]
        for k,v in item.items():
            if k not in {'title','name','name_ar','text','desc','wata','du3a','_id','id','sc','tag','url','link','namefile'} and v not in (None,''):
                extras.append(f"{k}: {v}")
        if item.get('sc'): extras.append(str(item['sc']))
        if item.get('url'): extras.append(str(item['url']))
        if item.get('link'): extras.append(str(item['link']))
        if item.get('namefile'): extras.append(str(item['namefile']))
        text=f"*{title}*\n\n{body}"
        if extras: text+='\n\n'+'\n'.join(extras)
    else: text=f"*{JSON_FILES[key][0]}*\n\n{item}"
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
    with sqlite3.connect(DATA/"bot_users.sqlite3") as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, city TEXT, tasbih INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        c.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)",(uid,))
        if change==0: c.execute("UPDATE users SET tasbih=0 WHERE user_id=?",(uid,))
        elif change>0: c.execute("UPDATE users SET tasbih=tasbih+1 WHERE user_id=?",(uid,))
        count=c.execute("SELECT tasbih FROM users WHERE user_id=?",(uid,)).fetchone()[0]
    rows=[[InlineKeyboardButton("📿 تسبیح +1",callback_data="ts:+"),InlineKeyboardButton("🔄 سفر",callback_data="ts:0")]]
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
    if "search_mode" in context.user_data:
        return await do_search(update,context,text)
    mapping={
        "📖 قورئانی پیرۆز":lambda:show_suras(update),
        "🕌 کاتەکانی بانگ":lambda:prayer_city_list(update),
        "🧭 ئاراستەی قیبلە":lambda:qibla(update),
        "📿 تەسبیح و زیکر":lambda:tasbih(update,context),
        "🤲 دوعاکان":lambda:show_dua(update,0),
        "📚 کتێب و فەرموودە":lambda:books_menu(update),
        "🕋 تەوبە و ئامۆژگاری":lambda:repentance_menu(update),
        "📜 ٤٠٠ فەرموودە":lambda:json_list(update,"farmwda",0),
        "🌙 ڕەمەزان":lambda:ramadan_menu(update),
        "✨ ناوەکانی خودا":lambda:show_names(update,0),
        "🧠 تاقیکردنەوە":lambda:quiz_start(update,context),
        "🎙️ قارییەکان":lambda:json_list(update,"dangakan",0),
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
    try:
        if data == "lr": return await show_last_read(update)
        if data == "settings": return await show_settings(update)
        if data == "fv:list": return await show_favorites(update)
        if data == "st:city": return await prayer_city_list(update, mode="prayer")
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
        if data.startswith("j:"):
            _,key,index=data.split(":"); return await show_json_item(update,key,int(index),True)
        if data.startswith("jl:"):
            _,key,page=data.split(":"); return await json_list(update,key,int(page),True)
        if data.startswith("nm:"): return await show_names(update,int(data.split(":")[1]))
        if data.startswith("du:"): return await show_dua(update,int(data.split(":")[1]))
        if data=="bm": return await books_menu(update)
        if data.startswith("bc:"):
            _,tag,page=data.split(":"); return await book_list(update,tag,int(page))
        if data.startswith("bi:"): return await book_item(update,int(data.split(":")[1]))
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

async def cmd_admin(update,context):
    if update.effective_user.id not in ADMIN_IDS: return
    with sqlite3.connect(DATA/"bot_users.sqlite3") as c:
        count=c.execute("SELECT count(*) FROM users").fetchone()[0]
    await update.effective_message.reply_text(f"🛠 بەشی بەڕێوەبەر\n\n👥 ژمارەی بەکارهێنەران: {count}\n📖 ئایەت: 6236\n📚 فەرموودە: 400")

async def error_handler(update,context):
    log.exception("Unhandled bot error",exc_info=context.error)

async def post_init(app):
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
        raise SystemExit("BOT_TOKEN environment variable is required. Copy .env.example to .env and set your Telegram bot token.")
    app=Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("menu",menu_cmd)); app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(CommandHandler("quran",quran_cmd)); app.add_handler(CommandHandler("prayer",prayer_cmd)); app.add_handler(CommandHandler("search",cmd_search)); app.add_handler(CommandHandler("admin",cmd_admin))
    app.add_handler(CommandHandler("favorites",show_favorites)); app.add_handler(CommandHandler("lastread",show_last_read)); app.add_handler(CommandHandler("settings",show_settings))
    app.add_handler(CallbackQueryHandler(callback)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text)); app.add_error_handler(error_handler)
    log.info("ڕێگای ئیسلام bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES,drop_pending_updates=False)

if __name__ == "__main__": main()
