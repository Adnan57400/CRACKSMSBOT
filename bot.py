
import logging, asyncio, re, aiohttp, json, os, random, html, sqlite3
import hashlib, ssl, websockets, subprocess, shutil, uuid
from urllib.parse import urljoin, urlparse
import phonenumbers
from phonenumbers import geocoder
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.ext import (ApplicationBuilder, ContextTypes, CommandHandler,
                           MessageHandler, CallbackQueryHandler, filters)
from telegram.error import BadRequest as TelegramBadRequest, Forbidden as TelegramForbidden, TimedOut as TelegramTimedOut, NetworkError as TelegramNetworkError
from sqlalchemy import text as stext, select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

import database as db
from utils import to_bold
import bot_manager as bm

# ═══════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════
class EmojiFormatter(logging.Formatter):
    """Adds emoji prefixes + clean timestamps to console output."""
    EMOJIS = {
        logging.DEBUG:    "🔍 DEBUG",
        logging.INFO:     "📌 INFO ",
        logging.WARNING:  "⚠️  WARN ",
        logging.ERROR:    "❌ ERROR",
        logging.CRITICAL: "🔥 CRIT ",
    }
    def format(self, record):
        label = self.EMOJIS.get(record.levelno, "❓ ?????")
        ts    = self.formatTime(record, "%H:%M:%S")
        msg   = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return f"{ts} | {label} | {msg}"

# ── File handler keeps plain text (easier to grep) ──────────────
_file_fmt    = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
_file_h      = logging.FileHandler("bot.log", encoding="utf-8")
_file_h.setFormatter(_file_fmt)

# ── Console handler gets emoji-rich output ───────────────────────
_console_h   = logging.StreamHandler()
_console_h.setFormatter(EmojiFormatter())

logging.basicConfig(level=logging.INFO, handlers=[_file_h, _console_h])

# Silence noisy third-party loggers
for _noisy in ("httpx","httpcore","telegram.ext","apscheduler","aiohttp"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
#  ANIMATED EMOJI IDs  (Telegram Premium custom emoji)
#  All emojis are animated for Premium users, static for others.
#  Get IDs for any emoji via @getidsbot on Telegram.
# ═══════════════════════════════════════════════════════════

COUNTRY_EMOJI_ID = {
    "UA":"5222250679371839695","US":"5224321781321442532","PL":"5224670399521892983",
    "KZ":"5222276376161171525","AZ":"5224426544163728284","EU":"5222108911091331711",
    "UN":"5451772687993031127","AM":"5224369957969603463","RU":"5280582975270963511",
    "CN":"5224435456220868088","UZ":"5222404546575219535","DE":"5222165617544542414",
    "JP":"5222390089715299207","TR":"5224601903383457698","BY":"5280820319458707404",
    "GB":"5224518800061245598","IN":"5222300011366200403","BR":"5224688610183228070",
    "VN":"5222359651282071925","AE":"5224565851427976312","TH":"5224638530864556281",
    "TZ":"5224397364155923150","TJ":"5222217865821696536","CH":"5224707263226194753",
    "SE":"5222201098269373561","ES":"5222024776976970940","KR":"5222345550904439270",
    "ZA":"5224696216570309138","RS":"5222145396838512729","SA":"5224698145010624573",
    "QA":"5222225596762830469","PT":"5224404094369672274","PH":"5222065042295376892",
    "PE":"5224482026551258766","PK":"5224637061985742245","OM":"5222396686785066306",
    "NO":"5224465228934163949","NG":"5224723614166691638","NZ":"5224573595254009705",
    "NL":"5224516489368841614","NP":"5222444378101925267","MA":"5224530035695693965",
    "MX":"5221971386238514431","MY":"5224312886444174057","KE":"5222089648163009103",
    "IQ":"5221980268230882832","IR":"5224374154152653367","ID":"5224405893960969756",
    "HU":"5224691998912427164","GR":"5222463490706389920","GH":"5224511339703056124",
    "GE":"5222152195771742239","FR":"5222029789203804982","FI":"5224282903277482188",
    "ET":"5224467805914542024","EE":"5222195463272281351","EG":"5222161185138292290",
    "DK":"5222297215342490217","CZ":"5222073533445714675","CO":"5224455152940886669",
    "CL":"5222350726340032308","CA":"5222001124592071204","BG":"5222092074819530668",
    "BE":"5224513182244024630","BD":"5224407289825340729","BH":"5224492892818518587",
    "AU":"5224659803837574114","AR":"5221980461504411710","DZ":"5224260376174015500",
    "AL":"5224312057515486246","AF":"5222096009009575868","ZW":"5222060442385397848",
    "VE":"5294476442854247878","LB":"5222244425899455269","LV":"5224401229626484931",
    "LT":"5224245902134226386","KG":"5224388147156102493","KW":"5221949726718442491",
    "JO":"5222292177345853436","IT":"5222460101977190141","IL":"5224720599099648709",
    "IE":"5224257017509588818","RO":"5222273794885826118","UA_2":"5280587278828193324",
    "DEFAULT":"5222250679371839695",
}

APP_EMOJI_ID = {
    "whatsapp":  "5334998226636390258",
    "telegram":  "5330237710655306682",
    "instagram": "5319160079465857105",
    "facebook":  "5323261730283863478",
    "google":    "5359758030198031389",
    "gmail":     "5359758030198031389",
    "twitter":   "5330337435500951363",
    "tiktok":    "5327982530702359565",
    "snapchat":  "5330248916224983855",
    "binance":   "5359437015752401733",
    "DEFAULT":   "5373026167722876724",
}

SERVICE_HASHTAGS = {
    "whatsapp":"WS","telegram":"TG","instagram":"IG","facebook":"FB",
    "google":"GG","gmail":"GG","twitter":"TW","tiktok":"TT","snapchat":"SC",
    "netflix":"NF","amazon":"AM","paypal":"PP","binance":"BN","discord":"DC",
    "microsoft":"MS","yahoo":"YH","apple":"AP","spotify":"SP","uber":"UB",
    "bolt":"BL","careem":"CR","tinder":"TN","bumble":"BM","linkedin":"LI",
    "shopee":"SH","grab":"GR","gojek":"GJ","foodpanda":"FP","signal":"SG",
    "steam":"ST","twitch":"TC","viber":"VB","line":"LN","wechat":"WC",
}

def tg_emoji(emoji_id: str, fallback: str) -> str:
    """Return animated tg-emoji tag. Animated for Premium users; fallback for all."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

def country_flag_emoji(region: str) -> str:
    """Return animated country flag tg-emoji, or standard unicode flag fallback."""
    if not region or len(region) != 2:
        return tg_emoji(COUNTRY_EMOJI_ID["DEFAULT"], "🌍")
    eid = COUNTRY_EMOJI_ID.get(region.upper(), COUNTRY_EMOJI_ID["DEFAULT"])
    # Unicode flag fallback
    base = 127462 - ord("A")
    flag = chr(base + ord(region[0].upper())) + chr(base + ord(region[1].upper()))
    return tg_emoji(eid, flag)

def app_emoji(service_name: str) -> str:
    """Return animated app icon tg-emoji for a given service name."""
    key = service_name.lower().strip()
    for svc_key, eid in APP_EMOJI_ID.items():
        if svc_key != "DEFAULT" and svc_key in key:
            return tg_emoji(eid, "📱")
    return tg_emoji(APP_EMOJI_ID["DEFAULT"], "📱")

def app_emoji_by_code(svc_code: str) -> str:
    """Return animated app icon by short code like WS, TG, FB."""
    code_map = {
        "WS":"whatsapp","TG":"telegram","IG":"instagram","FB":"facebook",
        "GG":"google","TW":"twitter","TT":"tiktok","SC":"snapchat","BN":"binance",
        "DC":"discord","MS":"microsoft","YH":"yahoo","AP":"apple","SP":"spotify",
    }
    name = code_map.get(svc_code.upper(), "")
    if name and name in APP_EMOJI_ID:
        return tg_emoji(APP_EMOJI_ID[name], "📱")
    return tg_emoji(APP_EMOJI_ID["DEFAULT"], "📱")

# Animated UI emoji shortcuts
_UI = {
    "fire":    ("5773906538459573336","🔥"),
    "bolt":    ("5461151367559362727","⚡"),
    "crown":   ("5392399685018067802","👑"),
    "diamond": ("5471952986970267163","💎"),
    "star":    ("5368324170671202286","⭐"),
    "key":     ("5472211234521076011","🔑"),
    "lock":    ("5472308992514464048","🔒"),
    "robot":   ("5361215897565626609","🤖"),
    "shield":  ("5359311622483678195","🛡"),
    "rocket":  ("5395303611011550609","🚀"),
    "gear":    ("5359831736784843489","⚙️"),
    "chart":   ("5359735404426468588","📊"),
    "bell":    ("5359766118363525030","🔔"),
    "skull":   ("5350934059607329445","💀"),
    "zap":     ("5461151367559362727","⚡"),
    "check":   ("5368324170671202286","✅"),
}
def ui(name: str) -> str:
    """Animated UI emoji by name."""
    if name in _UI: return tg_emoji(_UI[name][0], _UI[name][1])
    return "•"


# ═══════════════════════════════════════════════════════════
#  SAFE TELEGRAM HELPERS
# ═══════════════════════════════════════════════════════════
async def safe_edit(query, text: str, reply_markup=None, parse_mode="HTML"):
    """
    Wrapper for query.edit_message_text that silently swallows
    'Message is not modified' (content unchanged) and retries
    once on timeout / network error.
    """
    kwargs = dict(text=text, parse_mode=parse_mode)
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    for attempt in range(2):
        try:
            await query.edit_message_text(**kwargs)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                return   # already showing correct content — not an error
            if attempt == 0:
                await asyncio.sleep(0.5); continue
            raise
        except (TelegramTimedOut, TelegramNetworkError):
            if attempt == 0:
                await asyncio.sleep(1); continue
            return   # give up gracefully on second timeout


# ═══════════════════════════════════════════════════════════
#  DEFAULT CONSTANTS  (overridden by config.json)
# ═══════════════════════════════════════════════════════════
BOT_TOKEN         = "7952943119:AAFGuZiurY4yiaTCPwkrmsH51EUayr_DUFU"
BOT_USERNAME      = "CrackSMSReBot"
INITIAL_ADMIN_IDS = [7763727542, 7057157722, 7968271742, 7831921606, 8222195948]

# ── Mandatory membership gates ─────────────────────────────
# Users must be in ALL of these chats to use the bot.
# Admins / super-admins bypass the check automatically.
REQUIRED_CHATS = [
    {"id": -1003866750250, "title": "CrackOTP Group",   "link": "https://t.me/crackotpgroup"},
    {"id": -1003563202204, "title": "CrackOTP Channel", "link": "https://t.me/crackotp"},
    {"id": -1003720717628, "title": "Crack Chat GC",    "link": "https://t.me/crackchatgc"},
]
SUPPORT_USER      = "@ownersigma"
DEVELOPER         = "@NONEXPERTCODER"
OTP_GROUP_LINK    = "https://t.me/crackotpgroup"
GET_NUMBER_URL    = "https://t.me/CrackSMSReBot"
NUMBER_BOT_LINK   = "https://t.me/CrackSMSReBot"
CHANNEL_LINK      = "https://t.me/crackotp"
CHANGE_COOLDOWN_S = 7
COUNTRIES_FILE    = "countries.json"
DEX_FILE          = "dex.txt"
SEEN_DB_FILE      = "sms_database_np.db"
CONFIG_FILE       = "config.json"
OTP_STORE_FILE    = "otp_store.json"
LOG_FILE          = "bot.log"
API_FETCH_INTERVAL= 1   # 1s — optimised for 48-core server
MSG_AGE_LIMIT_MIN = 120
API_MAX_RECORDS   = 200  # max 200 — server limit
CHILD_BOT_FORWARD_URL = ""  # main bot webhook URL for child→main OTP forwarding
IS_CHILD_BOT      = False
DEFAULT_ASSIGN_LIMIT = 4

PERMISSIONS = {
    "manage_panels": "🔌 Manage Panels",
    "manage_files":  "📂 Manage Files",
    "manage_logs":   "📋 Manage Log Groups",
    "broadcast":     "📢 Send Broadcasts",
    "view_stats":    "📊 View Statistics",
    "manage_admins": "👥 Manage Admins",
}

DEFAULT_IVAS_URI = (
    "wss://ivas.tempnum.qzz.io:2087/socket.io/?token=eyJpdiI6IjI4c3JCUVNJa"
    "zRWRkp5M3lHL0pLeEE9PSIsInZhbHVlIjoiU09YK0llL1llc3ZIVzhia0sxTjZYTnZLN"
    "0dFOE1QSEZqMk1GVE1EUDhOVTR2R2tqbGUrVlBNSGJmQ1Q3WjhoUllZWlFTYUlwSmI0"
    "VUZRSHYwUFNqZ1VEY0U1RzFFcmo0MHJlU1BHcHNTYitpK1BKUDRkSGU5NlRoUnB4aThE"
    "TGFwemU2NTRGeUpoczRlNEFBT2tIejlrdWFSWFM1QjlBRURlOXIzbkNaWEJpcTlNV0ZD"
    "KzNrSFVLMEhEem5wUUZlS1NDRmtUVlhX2pxUGZqT2poMWs4UW1JU1d4UmFoTC9LVVHRL"
    "3Zrc00yVkZLcXRzYU9RNkh3dUl1eGNQSWhpZG12aGttMU5qSVovVm9KcytYa0hHb1Rod"
    "TFzYUt0bEdtQ3pVN0pUQkdZR0JGL2hGV21IanJqQXBsSisrSjlMdCtzbUc2dWhVdGdWZz"
    "FPWVgwVDJpSE1jak9LTVl1Vmh4bGNVZlgrT3BWT0g5YldmYVdVWVA1S0crbk9GOTNERWF"
    "1NG5kd0k3YkdXWXBMUk56QVVNNWtFclNoYWdYVXMrQ0NkSEdwamQrZUVNOGJybTdzTmV3"
    "TlpmakU1TmxxdmZIMkVOVGYwc3Y5NTdTeE9Xdm5Jc1FhU092dmE1ZzA4aktXOCtCMTdOb"
    "FgvSmliQlkwYjdmOFkzeHJQdzlOb252NWFHWnR5L3JSQnNDK3k1L0R6U2ZTZStWeDhOQz"
    "dLL01sZDVmamtNZzIrT2NvPSIsIm1hYyI6IjY2MWE1OTcxNWQ5YzU3OTUxZjgwZjA3MW"
    "U2OTUzYmUxMDI4NmQ3Y2ZmOTBkMmRkNTU1MmM0Zjc5ODAyNTRmODAiLCJ0YWciOiIifQ"
    "%3D%3D&user=9704f70096e34e36454e6ad92265698b&EIO=4&transport=websocket"
)

# ═══════════════════════════════════════════════════════════
#  CONFIG LOAD  — reads config.json and overrides constants
# ═══════════════════════════════════════════════════════════
def load_config():
    global DEFAULT_ASSIGN_LIMIT, IS_CHILD_BOT, BOT_TOKEN, BOT_USERNAME
    global INITIAL_ADMIN_IDS, SUPPORT_USER, DEVELOPER
    global OTP_GROUP_LINK, GET_NUMBER_URL, NUMBER_BOT_LINK, CHANNEL_LINK, DEVELOPER
    if not os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE) as f:
            c = json.load(f)
        DEFAULT_ASSIGN_LIMIT = c.get("default_limit", DEFAULT_ASSIGN_LIMIT)
        IS_CHILD_BOT          = c.get("IS_CHILD_BOT",   False)
        if c.get("BOT_TOKEN"):       BOT_TOKEN         = c["BOT_TOKEN"]
        if c.get("BOT_USERNAME"):    BOT_USERNAME      = c["BOT_USERNAME"].lstrip("@")
        if c.get("ADMIN_IDS"):       INITIAL_ADMIN_IDS = c["ADMIN_IDS"]
        if c.get("SUPPORT_USER"):    SUPPORT_USER      = c["SUPPORT_USER"]
        if c.get("DEVELOPER"):       DEVELOPER         = c["DEVELOPER"]
        if c.get("OTP_GROUP_LINK"):  OTP_GROUP_LINK    = c["OTP_GROUP_LINK"]
        if c.get("GET_NUMBER_URL"):  GET_NUMBER_URL    = c["GET_NUMBER_URL"]
        if c.get("NUMBER_BOT_LINK"): NUMBER_BOT_LINK   = c["NUMBER_BOT_LINK"]
        if c.get("CHANNEL_LINK"):    CHANNEL_LINK      = c["CHANNEL_LINK"]
        global OTP_GUI_THEME, AUTO_BROADCAST_ON, REQUIRED_CHATS
        OTP_GUI_THEME     = int(c.get("OTP_GUI_THEME", 0))
        AUTO_BROADCAST_ON = bool(c.get("AUTO_BROADCAST_ON", True))
        if c.get("REQUIRED_CHATS"):
            REQUIRED_CHATS = c["REQUIRED_CHATS"]
    except Exception as e:
        print(f"Config load error: {e}")

def save_config_key(key: str, value):
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f: cfg = json.load(f)
        except Exception: pass
    cfg[key] = value
    with open(CONFIG_FILE,"w") as f: json.dump(cfg, f, indent=2)

load_config()
if not os.path.exists(LOG_FILE):
    open(LOG_FILE,"a").close()

# ═══════════════════════════════════════════════════════════
#  OTP STORE
# ═══════════════════════════════════════════════════════════
def load_otp_store() -> dict:
    if os.path.exists(OTP_STORE_FILE):
        try:
            with open(OTP_STORE_FILE) as f: return json.load(f)
        except Exception: pass
    return {}

def save_otp_store(store: dict):
    try:
        path = os.path.abspath(OTP_STORE_FILE)
        with open(path, "w") as f:
            json.dump(store, f, indent=2)
    except Exception as e:
        logger.error(f"❌ OTP store save failed ({OTP_STORE_FILE}): {e}", exc_info=True)

def append_otp(num_raw: str, otp_code: str):
    """Thread-safe single OTP save — always writes immediately."""
    try:
        store = load_otp_store()
        store[num_raw] = otp_code
        # Keep max 2000 entries — trim oldest if over limit
        if len(store) > 2000:
            keys = list(store.keys())
            for k in keys[:-2000]: del store[k]
        save_otp_store(store)
        logger.info(f"💾 OTP saved: {mask_number(num_raw)} → {otp_code}")
    except Exception as e:
        logger.error(f"❌ append_otp failed: {e}")

# ═══════════════════════════════════════════════════════════
#  SEEN-SMS  (deduplication)
# ═══════════════════════════════════════════════════════════
def init_seen_db() -> set:
    try:
        conn = sqlite3.connect(SEEN_DB_FILE)
        conn.execute("CREATE TABLE IF NOT EXISTS reported_sms (hash TEXT PRIMARY KEY)")
        conn.commit()
        rows = conn.execute("SELECT hash FROM reported_sms").fetchall()
        conn.close()
        logger.info(f"Loaded {len(rows)} seen-SMS hashes.")
        return {r[0] for r in rows}
    except Exception as e:
        logger.error(f"Seen DB: {e}")
        return set()

def save_seen_hash(h: str):
    try:
        conn = sqlite3.connect(SEEN_DB_FILE)
        conn.execute("INSERT OR IGNORE INTO reported_sms (hash) VALUES (?)", (h,))
        conn.commit(); conn.close()
    except Exception: pass

TEST_NUMBERS = [f"1202555010{i}" for i in range(10)]

# ═══════════════════════════════════════════════════════════
#  OTP EXTRACTION — 200+ patterns
# ═══════════════════════════════════════════════════════════
_OTP_RE = [
    # ── Direct keyword patterns ───────────────────────────────
    r"(?:your|the)\s+(?:OTP|one.?time.?pass(?:word|code)?)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:OTP|one.?time.?pass(?:word|code)?)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:verification|confirm(?:ation)?)\s*(?:code|pin|OTP)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:auth(?:entication)?|security|access)\s*code\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:login|sign.?in|sign.?up)\s*(?:code|pin|OTP)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:activation|account)\s*(?:code|pin)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:reset|recovery|2fa|two.?factor)\s*(?:code|pin|OTP)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:registration|signup)\s*(?:code|pin)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"code\s*(?:is|:)\s*([0-9]{4,8})",
    r"pin\s*(?:is|:)\s*([0-9]{4,8})",
    r"passcode\s*(?:is|:)?\s*([0-9]{4,8})",
    r"password\s*(?:is|:)\s*([0-9]{4,8})",
    r"otp\s*[:#=]\s*([0-9]{4,8})",
    r"code\s*[:#=]\s*([0-9]{4,8})",
    r"pin\s*[:#=]\s*([0-9]{4,8})",
    r"token\s*(?:is|:)?\s*([0-9]{4,8})",
    r"key\s*(?:is|:)?\s*([0-9]{4,8})",
    r"passcode\s+for\s+\w+\s*[:#=]?\s*([0-9]{4,8})",
    r"one.?time\s+password\s*[:#=]?\s*([0-9]{4,8})",
    r"one.?time\s+passcode\s*[:#=]?\s*([0-9]{4,8})",
    r"one.?time\s+code\s*[:#=]?\s*([0-9]{4,8})",
    r"confirmation\s*(?:number|code)\s*[:#=]?\s*([0-9]{4,8})",
    r"activation\s*(?:number|key)\s*[:#=]?\s*([0-9]{4,8})",
    r"secret\s*(?:code|key|pin)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:access|unlock)\s*(?:code|key|pin)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:transaction|txn)\s*(?:code|pin|OTP)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:payment|transfer)\s*(?:code|pin)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:approval|authorize)\s*(?:code|pin)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:backup|recovery|restore)\s*(?:code|key)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"reference\s*(?:number|code|no)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:booking|reservation)\s*(?:code|id)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:order|invoice)\s*(?:number|code|id)\s*[:#=]\s*([0-9]{4,8})",
    # ── Major services ────────────────────────────────────────
    r"(?:WhatsApp|WA)\s*(?:Business\s+)?(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",          
    r"(?:WhatsApp|WA)\s*(?:Business\s+)?(?:code|OTP)?\s*(?:is|:)?\s*\b(\d{3}-\d{3})\b",     
    r"(?:کد\s*واتساپ|WhatsApp\s*کد)\s*(?:است|:)?\s*\b(\d{3}-\d{3})\b",                       
    r"(?:Dein|Ihr)\s+WhatsApp\s+Code\s*\b(\d{3}-\d{3})\b",                                   
    yyr"(?:Telegram|TG)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:WhatsApp|WA)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Telegram|TG)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Facebook|FB)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Instagram|IG)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Twitter|TW|X)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:TikTok|TT)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Snapchat|SC)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Google|GG|Gmail|GM)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Microsoft|MS|Outlook)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Apple|iCloud)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Amazon|AM)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:PayPal|PP)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Uber|UB|Lyft|LF)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Discord|DC)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Viber|VB|LINE|LN)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:WeChat|WC|KakaoTalk)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Netflix|NF|Spotify)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:LinkedIn|LI)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Steam|Twitch)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Binance|BN|Coinbase|CB|Crypto)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Shopify|Stripe)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Signal|Skype|Zoom)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Tinder|Bumble|Hinge)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Airbnb|Booking)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Careem|Swvl|Rapido|Bolt)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Jazz|Telenor|Zong|Ufone|PTCL)\s*(?:code|OTP|PIN)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Easypaisa|JazzCash|HBL|MCB|UBL|Meezan|Allied)\s*(?:code|OTP|PIN)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Bykea|Daraz|foodpanda|Cheetay)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Ola|Didi|Grab|Gojek)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Lazada|Shopee|Tokopedia)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:GrabPay|GoPay|OVO|Dana)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Wise|Revolut|N26)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Delivery|Glovo|DoorDash)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Noon|Namshi|SHEIN)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Etisalat|Du|STC|Mobily|Zain)\s*(?:code|OTP|PIN)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Orange|Vodafone|MTN|Airtel|Safaricom)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:T-Mobile|AT&T|Verizon|Sprint)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:BRI|BCA|Mandiri|BNI|CIMB)\s*(?:code|OTP|PIN)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Paytm|PhonePe|GPay|BHIM|FreeCharge)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:HDFC|ICICI|Axis|SBI|Kotak)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Mezan|Sadapay|NayaPay|Keenu)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Alipay|WeChat\s*Pay|UnionPay)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Zalando|AboutYou|Asos)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:eBay|Etsy|Fiverr|Upwork)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Kraken|Bybit|Kucoin|OKX|Mexc)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0in-9]{4,8})",
    r"(?:Hotmail|Yahoo|AOL|Proton)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Reddit|Pinterest|Quora)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Deezer|Tidal|Pandora)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Hulu|Disney|Prime|HBO|Peacock)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Canva|Notion|Figma|Slack)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Dropbox|OneDrive|iCloud\s*Drive)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:GitHub|GitLab|Bitbucket)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Xbox|PlayStation|Nintendo)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:Epic|Origin|EA)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:PUBG|Roblox|Fortnite|Valorant)\s*(?:code|OTP)?\s*(?:is|:)?\s*([0-9]{4,8})",
    # ── Action phrases ────────────────────────────────────────
    r"use\s+(?:this\s+)?(?:code|OTP|pin)\s*(?:to|:)?\s*([0-9]{4,8})",
    r"enter\s+(?:this\s+)?(?:code|OTP|pin)\s*(?:to|:)?\s*([0-9]{4,8})",
    r"your\s+code\s+([0-9]{4,8})",
    r"code\s+([0-9]{4,8})\s+(?:is|will)",
    r"([0-9]{4,8})\s+is\s+your\s+(?:OTP|code|pin|password)",
    r"([0-9]{4,8})\s+(?:is\s+)?(?:the|your)\s+(?:verification|auth|login)\s+code",
    r"([0-9]{4,8})\s+(?:is\s+)?(?:the|your)\s+one.?time",
    r"(?:do\s+not\s+share|never\s+share).*?([0-9]{4,8})",
    r"([0-9]{4,8}).*?(?:do\s+not\s+share|never\s+share)",
    r"(?:expires?\s+in|valid\s+for).*?([0-9]{4,8})",
    r"([0-9]{4,8}).*?(?:expires?|valid)",
    r"(?:confirm|verify)\s+(?:with|using)?\s*([0-9]{4,8})",
    r"(?:use|enter)\s+([0-9]{4,8})\s+(?:to|for)\s+(?:log|sign|verif|auth)",
    r"([0-9]{4,8})\s+(?:for|to)\s+(?:log|sign|verif|auth)",
    r"not\s+share.*?([0-9]{4,8})",
    r"([0-9]{4,8}).*?not\s+share",
    r"(?:generated|created)\s+(?:for)?\s*you.*?([0-9]{4,8})",
    r"(?:valid|expires?)\s*(?:only)?\s*(?:for|in)\s*\d+\s*min.*?([0-9]{4,8})",
    r"([0-9]{4,8}).*?(?:valid|expires?)\s*(?:only)?\s*(?:for|in)",
    r"(?:send|sent)\s+you\s+(?:a\s+)?(?:code|OTP)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:SMS|text)\s+(?:code|OTP)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"phone\s+(?:verification|confirm)\s*(?:code)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"mobile\s+(?:verification|confirm)\s*(?:code)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:account|profile)\s+(?:verification|confirm)\s*(?:code)?\s*(?:is|:)?\s*([0-9]{4,8})",
    r"number\s+(?:is|:)\s*([0-9]{4,8})",
    r"(?:private|secure)\s*(?:code|key)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:unique|special)\s*(?:code|pin|key)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:temporary|temp)\s+(?:code|password|pin)\s*(?:is|:)?\s*([0-9]{4,8})",
    # ── Platform hardcoded ────────────────────────────────────
    r"msverify[\s:/]*([0-9]{4,8})",
    r"msauth[\s:/]*([0-9]{4,8})",
    r"G-([0-9]{6})",
    r"FB-([0-9]{5,8})",
    r"WA-([0-9]{4,8})",
    r"<#>.*?([0-9]{4,8})",
    r"\[([0-9]{4,8})\]\s+is\s+your",
    r"([0-9]{4,8})\s+is\s+your\s+\w+\s+code",
    r"code:\s*([0-9]{4,8})",
    r"OTP:\s*([0-9]{4,8})",
    r"PIN:\s*([0-9]{4,8})",
    r"#([0-9]{4,8})",
    r"verification\s+number\s*[:#=]?\s*([0-9]{4,8})",
    r"([0-9]{6})\s+(?:is|are)\s+your",
    # ── Separated digit formats ───────────────────────────────
    r"([0-9]{3}[-\s][0-9]{3})",
    r"([0-9]{4}[-\s][0-9]{4})",
    r"([0-9]{3}[-\s][0-9]{3}[-\s][0-9]{3})",
    r"([0-9]{2}[-\s][0-9]{2}[-\s][0-9]{2})",
    r"([0-9]{4}[-\s][0-9]{2})",
    r"([0-9]{2}[-\s][0-9]{4})",
    r"\b([0-9]{4}[-\s][0-9]{4})\b",
    r"\b([0-9]{3}[-\s][0-9]{3}[-\s][0-9]{3})\b",
    r"\b([0-9]{2}[-\s][0-9]{2}[-\s][0-9]{2})\b",
    r"\b([0-9]{4}[-\s][0-9]{2})\b",
    r"\b([0-9]{2}[-\s][0-9]{4})\b",
    # ── Language variants ─────────────────────────────────────
    r"(?:رمز|کد|کود)\s*(?:تأیید|التحقق|OTP)?\s*(?:است|:)?\s*([0-9]{4,8})",
    r"(?:کوڈ|رمز)\s*(?:ہے|:)?\s*([0-9]{4,8})",
    r"(?:código|code|clave)\s*(?:de\s+verificación|OTP)?\s*(?:es|:)?\s*([0-9]{4,8})",
    r"(?:код|OTP)\s*(?:подтверждения)?\s*(?:[:—])\s*([0-9]{4,8})",
    r"(?:驗證碼|验证码|코드)\s*(?:是|:)?\s*([0-9]{4,8})",
    r"(?:رمز\s*عبور|کد\s*تأیید)\s*(?:شما)?\s*(?:است|:)?\s*([0-9]{4,8})",
    r"(?:doğrulama|onay)\s*(?:kodu|kode)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:kode|kod)\s*(?:verifikasi|doğrulama)?\s*(?:anda|:)?\s*([0-9]{4,8})",
    r"(?:mật\s*khẩu|xác\s*nhận)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:รหัส|ยืนยัน)\s*([0-9]{4,8})",
    r"(?:otp|رمز|code)\s*(?:آپ\s+کا|تمہارا|آپکا)?\s*(?:ہے)?\s*([0-9]{4,8})",
    r"(?:hai|hain|he|hy).*?([0-9]{4,8})",
    r"([0-9]{4,8}).*?(?:hai|hain|he|hy)",
    r"(?:aapka|apka|tumhara)\s*(?:code|otp|pin)?\s*([0-9]{4,8})",
    r"(?:verification|tasdeek|tahqeeq)\s*(?:code|raqam)?\s*([0-9]{4,8})",
    r"(?:apna|apni)\s+(?:otp|code|pin)\s+([0-9]{4,8})",
    r"आपका\s*(?:OTP|कोड|पिन)?\s*(?:है)?\s*([0-9]{4,8})",
    r"আপনার\s*(?:OTP|কোড)?\s*(?:হল)?\s*([0-9]{4,8})",
    r"(?:kod\s+weryfikacyjny|kod\s+jednorazowy)\s*(?:to|:)?\s*([0-9]{4,8})",
    r"(?:einmalcode|bestätigungscode)\s*(?:ist|:)?\s*([0-9]{4,8})",
    r"(?:eenmalige\s+code|verificatiecode)\s*(?:is|:)?\s*([0-9]{4,8})",
    r"(?:votre|ton)\s+(?:code|mot\s+de\s+passe)\s+(?:est|:)?\s*([0-9]{4,8})",
    r"(?:su\s+código|su\s+contraseña)\s*(?:de)?\s*(?:acceso)?\s*(?:es|:)?\s*([0-9]{4,8})",
    r"(?:il\s+tuo|suo)\s+(?:codice|pin)\s+(?:è|:)?\s*([0-9]{4,8})",
    r"(?:الرمز|رمزك|كودك)\s*(?:هو|:)?\s*([0-9]{4,8})",
    r"أدخل\s*(?:الرمز)?\s*([0-9]{4,8})",
    r"([0-9]{4,8})\s*(?:هو\s+رمزك|هو\s+كودك)",
    # ── Position-based ────────────────────────────────────────
    r"[:\-=]\s*([0-9]{6})",
    r"[:\-=]\s*([0-9]{4})",
    r"[:\-=]\s*([0-9]{8})",
    r"is\s+([0-9]{6})",
    r"is\s+([0-9]{4})",
    r"(?<=\s)([0-9]{6})(?=\s|$|\.|,)",
    r"(?<=\s)([0-9]{8})(?=\s|$|\.|,)",
    r"(?<=\D)([0-9]{5})(?=\D|$)",
    r"(?<=\D)([0-9]{7})(?=\D|$)",
    # ── Catch-all (last resort) ───────────────────────────────
    r"([0-9]{6})",
    r"([0-9]{5})",
    r"([0-9]{8})",
    r"([0-9]{7})",
    r"([0-9]{4})",
]

def extract_otp_regex(text: str) -> Optional[str]:
    """Extract OTP from SMS body using 100 regex patterns."""
    if not text: return None
    for pat in _OTP_RE:
        try:
            m = re.search(pat, text, re.IGNORECASE | re.UNICODE)
            if m:
                raw = m.group(1).replace(" ", "").replace("-", "")
                if raw.isdigit() and 4 <= len(raw) <= 9:
                    return raw
        except re.error:
            continue
    return None

# ═══════════════════════════════════════════════════════════
#  PHONE / COUNTRY HELPERS
# ═══════════════════════════════════════════════════════════
COUNTRY_DATA: List[dict] = []

def load_countries():
    global COUNTRY_DATA
    if os.path.exists(COUNTRIES_FILE):
        try:
            with open(COUNTRIES_FILE, encoding="utf-8") as f:
                COUNTRY_DATA = json.load(f)
            logger.info(f"Loaded {len(COUNTRY_DATA)} countries.")
        except Exception as e:
            logger.error(f"Countries: {e}")

load_countries()

def get_country_info(num: str):
    try:
        n = num if num.startswith("+") else "+" + num
        p = phonenumbers.parse(n)
        country = geocoder.description_for_number(p, "en")
        region  = phonenumbers.region_code_for_number(p)
        flag = "🌍"
        if region and len(region) == 2:
            b = 127462 - ord("A")
            flag = chr(b+ord(region[0])) + chr(b+ord(region[1]))
        return country or "Unknown", flag, region or ""
    except Exception: return "Unknown", "🌍", ""

def get_country_code(num: str) -> str:
    try:
        n = num if num.startswith("+") else "+" + num
        return f"+{phonenumbers.parse(n).country_code}"
    except Exception: return ""

def get_last5(num: str) -> str:
    d = re.sub(r"[^0-9]","",num)
    return d[-5:] if len(d) >= 5 else d

def mask_number(num: str) -> str:
    c = num.replace("+","").replace(" ","")
    return f"{c[:4]}-SIGMA-{c[-4:]}" if len(c) >= 8 else num

def detect_country_from_numbers(nums: list):
    if not COUNTRY_DATA or not nums: return "Unknown", "🌍"
    sc = sorted(COUNTRY_DATA, key=lambda x: len(x["dial_code"]), reverse=True)
    votes = {}
    for raw in nums[:50]:
        chk = "+" + re.sub(r"[^0-9]","",str(raw))
        for c in sc:
            if chk.startswith(c["dial_code"]):
                k = (c["name"], c["flag"])
                votes[k] = votes.get(k,0) + 1
                break
    return max(votes, key=votes.get) if votes else ("Unknown","🌍")

_SVC_MAP = {
    "whatsapp":"WS","telegram":"TG","facebook":"FB","instagram":"IG","twitter":"TW",
    "tiktok":"TT","snapchat":"SC","google":"GG","gmail":"GM","microsoft":"MS",
    "amazon":"AM","apple":"AP","uber":"UB","lyft":"LF","paypal":"PP","viber":"VB",
    "line":"LN","wechat":"WC","yahoo":"YH","netflix":"NF","discord":"DC",
    "linkedin":"LI","shopify":"SH","binance":"BN","coinbase":"CB","steam":"ST","twitch":"TC",
}

def get_service_short(svc: str) -> str:
    s = svc.lower().strip()
    for k,v in _SVC_MAP.items():
        if k in s: return v
    clean = re.sub(r"[^a-zA-Z]","",svc)
    return clean[:2].upper() if clean else "OT"

def get_message_body(rec: list) -> Optional[str]:
    noise = {"0","0.00","€","$","null","None",""}
    for idx in [4,5]:
        if len(rec) > idx:
            v = str(rec[idx]).strip()
            if v and v not in noise and len(v) > 1: return v
    return None

def parse_panel_dt(dt_str: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d %H:%M:%S","%Y/%m/%d %H:%M:%S","%d-%m-%Y %H:%M:%S"):
        try: return datetime.strptime(dt_str.strip(), fmt)
        except Exception: pass
    return None

def pbar(cur: int, total: int, length: int = 12) -> str:
    if total <= 0: return f"[{chr(9617)*length}] 0/0"
    f = int(length * cur / total)
    return f"[{chr(9608)*f}{chr(9617)*(length-f)}] {cur}/{total}"

D = "┄" * 22

# ── OTP GUI Theme ─────────────────────────────────────────────────
# 30 compact designs. Only super-admins can change. Clamp to index %30.
OTP_GUI_THEME = 0   # 0-29

_THEME_NAMES = {
    0:  "🔥 CrackOTP Pro",          1:  "⏱ TempNum Classic",
    2:  "⚡ Electric Strike",        3:  "🌑 Dark Command",
    4:  "🤍 WhiteLine",              5:  "👑 Gold Royale",
    6:  "🚀 JackX Launch",           7:  "💀 CyberShell",
    8:  "🔴 FireBlast",              9:  "❄️ ArcticOTP",
    10: "🖤 ShadowBox",              11: "₿ CryptoCode",
    12: "🌸 SakuraSoft",             13: "🎖 SecureForce",
    14: "💚 MatrixCode",             15: "💎 DiamondVault",
    16: "🧿 SigmaPro",              17: "💓 PulseBeam",
    18: "⚡ LightningBox",           19: "🌹 RoseGold",
    20: "🌌 AstroSend",              21: "📺 RetroWave",
    22: "🟢 NeonFrame",              23: "🔐 IronVault",
    24: "🔩 SteelCore",              25: "🌈 AuroraBox",
    26: "👻 PhantomMode",            27: "💚 EmeraldTag",
    28: "🌅 SunsetBurst",            29: "🏆 UltraPrime",
}

def _get_bot_tag() -> str:
    nb = NUMBER_BOT_LINK or GET_NUMBER_URL or ""
    if "t.me/" in nb:
        u = nb.rstrip("/").split("t.me/")[-1].lstrip("@")
        if u: return f"@{u}"
    return f"@{BOT_USERNAME}" if BOT_USERNAME else "@CrackSMSReBot"

def _num_display(dial: str, last5: str) -> str:
    bt = _get_bot_tag().lstrip("@")[:9].upper()
    return f"{dial}•{bt}•{last5}"

def _e(eid, fb): return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'
_FIRE  = lambda: _e("5773906538459573336","🔥")
_KEY   = lambda: _e("5472211234521076011","🔑")
_BOLT  = lambda: _e("5461151367559362727","⚡")
_LOCK  = lambda: _e("5472308992514464048","🔒")
_GEM   = lambda: _e("5471952986970267163","💎")
_CROWN = lambda: _e("5392399685018067802","👑")
_STAR  = lambda: _e("5368324170671202286","⭐")
_SKULL = lambda: _e("5350934059607329445","💀")
_ROBOT = lambda: _e("5361215897565626609","🤖")

def build_otp_msg(header: str, count_badge: str, clean: str,
                  msg_body: str, svc: str, panel_name: str,
                  flag: str, region: str, dial: str, last5: str,
                  for_group: bool) -> str:
    """
    30 compact OTP designs. Only super-admins can change OTP_GUI_THEME.
    All designs follow the compact style seen in the reference screenshot:
    flag + service + number + OTP, ©By line. Each has a unique personality.
    """
    bot_tag  = _get_bot_tag()
    bt       = html.escape(bot_tag)
    nd       = _num_display(dial, last5)
    body160  = html.escape(msg_body[:160])
    body260  = html.escape(msg_body[:260])
    aflag    = country_flag_emoji(region)
    aicon    = app_emoji_by_code(svc)
    num_full = f"+{dial.lstrip('+')}{last5}" if dial else f"+{last5}"
    num_star = f"{num_full[:-4]}****{num_full[-4:]}" if len(num_full) > 8 else num_full
    now_ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t = OTP_GUI_THEME % 30

    # helper: formatted OTP  491-138 or 491138
    def fmt_otp(o):
        if len(o)==6: return f"{o[:3]}-{o[3:]}"
        if len(o)==8: return f"{o[:4]}-{o[4:]}"
        return o

    fotp = fmt_otp(clean) if clean else "—"

    # ── T0: SAMI OTP (from screenshot) ──────────────────────────────
    if t == 0:
        if for_group:
            return (f"{aflag} <b>{region} {svc} OTP Received!</b>\n\n"
                    f"| 📱 <b>Number:</b> <code>{num_star}</code>\n"
                    f"| {_KEY()} <b>OTP Code:</b> <code>{fotp}</code>\n\n"
                    f"<i>©By {bt}</i>") if clean else (
                    f"{aflag} {aicon} <b>{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>\n<i>©By {bt}</i>")
        return (
            f"{aflag} <b>{region} {svc} OTP Received!</b>\n\n"
            f"| 📱 <b>Number:</b> <code>{num_star}</code>\n"
            f"| {_KEY()} <b>OTP Code:</b> <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n\n<i>©By {bt}</i>"
        ) if clean else (
            f"{aflag} {aicon} <b>{svc}</b>  <code>{nd}</code>\n"
            f"<b>{header}</b>\n💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T1: TEMPNUM (structured rows, from screenshot bottom) ─────────
    elif t == 1:
        if for_group:
            return (f"{_FIRE()} {aflag} <b>{region} {svc} OTP!</b> ✨\n\n"
                    f"| 🕐 <b>Time:</b> <code>{now_ts}</code>\n"
                    f"| 🌍 <b>Country:</b> {region} {aflag}\n"
                    f"| {_KEY()} <b>OTP:</b> <code>{fotp}</code>\n"
                    f"<i>©By {bt}</i>") if clean else (
                    f"{aflag} {aicon} <b>{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>\n<i>©By {bt}</i>")
        return (
            f"{_FIRE()} <b>{aflag} {region} {svc} OTP Received!</b> ✨\n\n"
            f"| 🕐 <b>Time:</b> <code>{now_ts}</code>\n"
            f"| 🌍 <b>Country:</b> {region} {aflag}\n"
            f"| {aicon} <b>Service:</b> #{svc}\n"
            f"| 📱 <b>Number:</b> <code>{num_star}</code>\n"
            f"| {_KEY()} <b>OTP:</b> <code>{fotp}</code>\n"
            f"| 💬 <b>SMS:</b> <i>{body160}</i>\n\n"
            f"<i>©By {bt}</i>"
        ) if clean else (
            f"{_FIRE()} <b>{header}</b>\n"
            f"| 🌍 {region} {aflag}  | {aicon} #{svc}\n"
            f"| 💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T2: NEON ELECTRIC ────────────────────────────────────────────
    elif t == 2:
        if for_group:
            return (f"{_BOLT()} {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code> {_BOLT()}\n"
                    f"🔐 <code>{fotp}</code>\n<i>{bt}</i>") if clean else (
                    f"📡 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>\n<i>{bt}</i>")
        return (
            f"{_BOLT()}{_BOLT()} <b>{header}</b> {_BOLT()}{_BOLT()}\n"
            f"{'─'*22}\n"
            f"{aflag} {aicon} <b>#{svc}</b>  {_BOLT()} <code>{nd}</code>\n"
            f"{'─'*22}\n"
            f"🔐 <b>OTP:</b> {_GEM()} <code>{fotp}</code> {_GEM()}\n"
            f"{'─'*22}\n"
            f"💬 <i>{body260}</i>\n<i>{bt}</i>"
        ) if clean else (
            f"📡 <b>{header}</b>\n{aflag} {aicon} <b>#{svc}</b>\n"
            f"💬 <i>{body260}</i>\n<i>{bt}</i>")

    # ── T3: PREMIUM DARK ─────────────────────────────────────────────
    elif t == 3:
        if for_group:
            return (f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>  {_FIRE()}\n\n"
                    f"<b>{header}</b>  ·  <code>{fotp}</code>\n<i>©By {bt}</i>") if clean else (
                    f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>\n<i>©By {bt}</i>")
        return (
            f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"  {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>  {_FIRE()}\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"{_KEY()} <b>OTP:</b>  <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"  {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T4: MINIMAL CLEAN ────────────────────────────────────────────
    elif t == 4:
        if for_group:
            return (f"{aflag} #{svc}  <code>{nd}</code>  <code>{fotp}</code>\n<i>{bt}</i>") if clean else (
                    f"{aflag} #{svc}  <code>{nd}</code>\n<i>{body160}</i>\n<i>{bt}</i>")
        return (
            f"{aflag} <b>#{svc}</b>  <code>{nd}</code>\n<b>{header}</b>\n\n"
            f"<code>{fotp}</code>\n<i>{body260}</i>\n<i>{bt}</i>"
        ) if clean else (
            f"{aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"<b>{header}</b>\n<i>{body260}</i>\n<i>{bt}</i>")

    # ── T5: ROYAL GOLD ───────────────────────────────────────────────
    elif t == 5:
        if for_group:
            return (f"{_CROWN()} {aflag} <b>#{svc}</b>  <code>{nd}</code> 🌟\n"
                    f"{_KEY()} <code>{fotp}</code>\n✨ <i>{bt}</i> ✨") if clean else (
                    f"💫 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>\n✨ <i>{bt}</i> ✨")
        return (
            f"{_CROWN()} <b>━━ {header} ━━</b> {_CROWN()}\n\n"
            f"🌟 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code> 🌟\n\n"
            f"{_KEY()} <b>OTP:</b> <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n✨ <i>{bt}</i> ✨"
        ) if clean else (
            f"💫 <b>{header}</b>\n🌟 {aflag} {aicon} <b>#{svc}</b>\n"
            f"💬 <i>{body260}</i>\n✨ <i>{bt}</i> ✨")

    # ── T6: JACK-X ───────────────────────────────────────────────────
    elif t == 6:
        vbadge = f"{_STAR()} V2 {_STAR()}"
        if for_group:
            return (f"{vbadge}\n→ {aflag} <b>#{svc}</b>  {nd}  {_FIRE()}\n<i>©By {bt}</i>") if clean else (
                    f"→ {aflag} <b>#{svc}</b>  {nd}\n<i>{body160}</i>\n<i>©By {bt}</i>")
        return (
            f"{_BOLT()} <b>{bt}</b>  {vbadge}\n"
            f"→ {aflag} <b>#{svc}</b>  [{region}]  <code>{nd}</code>  {_FIRE()}\n\n"
            f"{_KEY()} <code>{fotp}</code>\n\n"
            f"<i>{body260}</i>\n{_GEM()} <i>©By {bt}</i> {_GEM()}"
        ) if clean else (
            f"{_BOLT()} <b>{bt}</b>\n→ {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"<i>{body260}</i>\n{_GEM()} <i>©By {bt}</i> {_GEM()}")

    # ── T7: CYBER MATRIX ─────────────────────────────────────────────
    elif t == 7:
        if for_group:
            return (f"{_FIRE()} {aflag} #{svc}  <code>{nd}</code> {_BOLT()}\n"
                    f"{_KEY()} <code>{fotp}</code>\n<i>©By {bt}</i>") if clean else (
                    f"{_BOLT()} {aflag} #{svc}  <code>{nd}</code>\n"
                    f"<i>{body160}</i>\n<i>©By {bt}</i>")
        return (
            f"<b>[ {_BOLT()} CRACK SMS {_BOLT()} ]</b>\n{'─'*24}\n"
            f"  {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>  {_FIRE()}\n"
            f"{'─'*24}\n  {_KEY()} <b>DECRYPTED</b>\n  <code>{fotp}</code>\n"
            f"{'─'*24}\n  {_LOCK()} <i>{body260}</i>\n"
            f"  {_SKULL()} <i>©By {bt}</i> {_SKULL()}"
        ) if clean else (
            f"<b>[ {_BOLT()} CRACK SMS {_BOLT()} ]</b>\n"
            f"  {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"  {_LOCK()} <i>{body260}</i>\n  <i>©By {bt}</i>")

    # ── T8: FIRE STORM ───────────────────────────────────────────────
    elif t == 8:
        if for_group:
            return (f"{_FIRE()}{_FIRE()} {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"{_FIRE()} {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"{_FIRE()}{_FIRE()}{_FIRE()} <b>{header}</b> {_FIRE()}{_FIRE()}{_FIRE()}\n\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 OTP: <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"{_FIRE()} <b>{header}</b>\n{aflag} {aicon}  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T9: ICE BLUE ─────────────────────────────────────────────────
    elif t == 9:
        if for_group:
            return (f"❄️ {aflag} <b>#{svc}</b>  <code>{nd}</code>  🧊\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"❄️ {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"❄️ <b>━━━━━━━━━━━━━━━━━━</b> 🧊\n"
            f"  {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"  🔑 OTP: <code>{fotp}</code>\n"
            f"❄️ <b>━━━━━━━━━━━━━━━━━━</b> 🧊\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"❄️ <b>━━━━━━━━━━━━━━━━━━</b> 🧊\n"
            f"  {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T10: SHADOW DARK ─────────────────────────────────────────────
    elif t == 10:
        if for_group:
            return (f"🖤 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"🔐 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"🖤 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"🖤 <b>◤━━━━━━━━━━━━━━━━━━◥</b>\n"
            f"    {aflag} {aicon} <b>#{svc}</b>\n"
            f"    <code>{nd}</code>\n"
            f"    🔑 <code>{fotp}</code>\n"
            f"<b>◣━━━━━━━━━━━━━━━━━━◢</b>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"🖤 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T11: CRYPTO ──────────────────────────────────────────────────
    elif t == 11:
        if for_group:
            return (f"₿ {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"₿ {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"₿ <b>CRYPTO OTP</b> {_GEM()}\n{'─'*22}\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔐 <b>Token:</b> <code>{fotp}</code>\n{'─'*22}\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"₿ {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T12: SAKURA ──────────────────────────────────────────────────
    elif t == 12:
        if for_group:
            return (f"🌸 {aflag} <b>#{svc}</b>  <code>{nd}</code> 🌸\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"🌸 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"🌸🌸 <b>{header}</b> 🌸🌸\n\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n🌸 <i>©By {bt}</i> 🌸"
        ) if clean else (
            f"🌸 {aflag} {aicon} <b>#{svc}</b>\n"
            f"💬 <i>{body260}</i>\n🌸 <i>©By {bt}</i> 🌸")

    # ── T13: MILITARY ────────────────────────────────────────────────
    elif t == 13:
        if for_group:
            return (f"🎖 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"🔐 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"🎖 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"🎖 <b>SECURE OTP RECEIVED</b> 🎖\n{'═'*22}\n"
            f"▸ REGION:   {region} {aflag}\n"
            f"▸ SERVICE:  #{svc} {aicon}\n"
            f"▸ NUMBER:   <code>{num_star}</code>\n"
            f"▸ OTP:      <code>{fotp}</code>\n"
            f"{'═'*22}\n💬 <i>{body160}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"🎖 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T14: HACKER GREEN ────────────────────────────────────────────
    elif t == 14:
        if for_group:
            return (f"💚 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"> <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"💚 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"<code>[ OTP_SYSTEM v3.0 ]</code>\n"
            f"<code>region   = {region}</code>\n"
            f"<code>service  = {svc}</code>\n"
            f"<code>number   = {num_star}</code>\n"
            f"<code>otp      = {fotp}</code>\n"
            f"<code>───────────────────</code>\n"
            f"💬 <i>{body160}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"<code>[ OTP_SYSTEM v3.0 ]</code>\n"
            f"<code>region   = {region}</code>\n"
            f"<code>service  = {svc}</code>\n"
            f"💬 <i>{body160}</i>\n<i>©By {bt}</i>")

    # ── T15: DIAMOND ─────────────────────────────────────────────────
    elif t == 15:
        if for_group:
            return (f"{_GEM()} {aflag} <b>#{svc}</b>  <code>{nd}</code> {_GEM()}\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"{_GEM()} {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"{_GEM()} {_GEM()} <b>{header}</b> {_GEM()} {_GEM()}\n\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💎 OTP: <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n{_GEM()} <i>©By {bt}</i> {_GEM()}"
        ) if clean else (
            f"{_GEM()} {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n{_GEM()} <i>©By {bt}</i> {_GEM()}")

    # ── T16: SIGMA CLASSIC ───────────────────────────────────────────
    elif t == 16:
        if for_group:
            return (f"🔥 {flag}#{region}  📱 <code>{nd}</code>\n"
                    f"🔑 <code>{fotp}</code>  📡#{svc}\n©️ {bt}") if clean else (
                    f"📩 {flag}#{region}  📱 <code>{nd}</code>\n"
                    f"💬 <i>{body160}</i>\n©️ {bt}")
        return (
            f"🔥 <b>{header}</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"📱 <code>{nd}</code>  {flag}\n"
            f"🌍 #{region}  📡 #{svc}\n\n"
            f"╔══ 🔑 OTP ══╗\n  <code>{fotp}</code>\n╚════════════╝\n\n"
            f"💬 <i>{body260}</i>\n©️ <b>{bt}</b>"
        ) if clean else (
            f"📩 <b>{header}</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"📱 <code>{nd}</code>  {flag}  #{region}\n"
            f"💬 <i>{body260}</i>\n©️ <b>{bt}</b>")

    # ── T17: PULSE ───────────────────────────────────────────────────
    elif t == 17:
        if for_group:
            return (f"💓 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"💓 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"💓 <b>PULSE · {header}</b> 💓\n{'·'*22}\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 <code>{fotp}</code>\n{'·'*22}\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"💓 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T18: BOLT ────────────────────────────────────────────────────
    elif t == 18:
        if for_group:
            return (f"{_BOLT()} {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"⚡ <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"{_BOLT()} {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"{_BOLT()} <b>⚡ {header} ⚡</b> {_BOLT()}\n\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"⚡ OTP: <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"{_BOLT()} {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T19: ROSE GOLD ───────────────────────────────────────────────
    elif t == 19:
        if for_group:
            return (f"🌹 {aflag} <b>#{svc}</b>  <code>{nd}</code> 🌹\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"🌹 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"🌹🌹 <b>{header}</b> 🌹🌹\n\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n🌹 <i>©By {bt}</i> 🌹"
        ) if clean else (
            f"🌹 {aflag} {aicon} <b>#{svc}</b>\n"
            f"💬 <i>{body260}</i>\n🌹 <i>©By {bt}</i> 🌹")

    # ── T20: ASTRO ───────────────────────────────────────────────────
    elif t == 20:
        if for_group:
            return (f"🚀 {aflag} <b>#{svc}</b>  <code>{nd}</code> 🌌\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"🚀 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"🚀 <b>ASTRO OTP</b> 🌌\n{'·'*22}\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"⭐ <code>{fotp}</code>\n{'·'*22}\n"
            f"💬 <i>{body260}</i>\n🚀 <i>©By {bt}</i>"
        ) if clean else (
            f"🚀 {aflag} {aicon} <b>#{svc}</b>\n"
            f"💬 <i>{body260}</i>\n🚀 <i>©By {bt}</i>")

    # ── T21: RETRO ───────────────────────────────────────────────────
    elif t == 21:
        if for_group:
            return (f"📟 {aflag} #{svc}  {nd}\n"
                    f"OTP: {fotp}  [{bt}]") if clean else (
                    f"📟 {aflag} #{svc}  {nd}\n"
                    f"{body160}  [{bt}]")
        return (
            f"<code>╔══════════════════╗</code>\n"
            f"<code>║ OTP TERMINAL     ║</code>\n"
            f"<code>╠══════════════════╣</code>\n"
            f"<code>║ SVC: {svc:<12}║</code>\n"
            f"<code>║ REG: {region:<12}║</code>\n"
            f"<code>║ OTP: {fotp:<12}║</code>\n"
            f"<code>╚══════════════════╝</code>\n"
            f"{aflag} {aicon}  <i>{body160}</i>\n<i>[{bt}]</i>"
        ) if clean else (
            f"<code>╔══════════════════╗</code>\n"
            f"<code>║ OTP TERMINAL     ║</code>\n"
            f"<code>╚══════════════════╝</code>\n"
            f"{aflag} {aicon} <b>#{svc}</b>\n<i>{body160}</i>\n<i>[{bt}]</i>")

    # ── T22: NEON BOX ────────────────────────────────────────────────
    elif t == 22:
        if for_group:
            return (f"🟦 {aflag} <b>#{svc}</b>  <code>{nd}</code> 🟦\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"🟦 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"🟦 <b>NEON BOX · {header}</b> 🟦\n\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"🟦 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T23: VAULT ───────────────────────────────────────────────────
    elif t == 23:
        if for_group:
            return (f"🏦 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"🔐 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"🏦 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"🏦 <b>VAULT UNLOCK</b> {_LOCK()}\n{'━'*20}\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔐 Access: <code>{fotp}</code>\n{'━'*20}\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"🏦 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T24: STEEL ───────────────────────────────────────────────────
    elif t == 24:
        if for_group:
            return (f"⚙️ {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"🔩 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"⚙️ {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"⚙️ <b>STEEL OTP</b> 🔩\n{'─'*20}\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 <code>{fotp}</code>\n{'─'*20}\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"⚙️ {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T25: AURORA ──────────────────────────────────────────────────
    elif t == 25:
        if for_group:
            return (f"🌈 {aflag} <b>#{svc}</b>  <code>{nd}</code> 🌈\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"🌈 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"🌈 <b>AURORA · {header}</b> 🌟\n\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n🌈 <i>©By {bt}</i>"
        ) if clean else (
            f"🌈 {aflag} {aicon} <b>#{svc}</b>\n"
            f"💬 <i>{body260}</i>\n🌈 <i>©By {bt}</i>")

    # ── T26: PHANTOM ─────────────────────────────────────────────────
    elif t == 26:
        if for_group:
            return (f"👻 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"👻 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"👻 <b>PHANTOM OTP</b> 🌑\n{'·'*22}\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 <code>{fotp}</code>\n{'·'*22}\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"👻 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    # ── T27: EMERALD ─────────────────────────────────────────────────
    elif t == 27:
        if for_group:
            return (f"💚 {aflag} <b>#{svc}</b>  <code>{nd}</code> 💚\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"💚 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"💚 <b>EMERALD · {header}</b> 💚\n\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 <code>{fotp}</code>\n\n"
            f"💬 <i>{body260}</i>\n💚 <i>©By {bt}</i> 💚"
        ) if clean else (
            f"💚 {aflag} {aicon} <b>#{svc}</b>\n"
            f"💬 <i>{body260}</i>\n💚 <i>©By {bt}</i> 💚")

    # ── T28: SUNSET ──────────────────────────────────────────────────
    elif t == 28:
        if for_group:
            return (f"🌅 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"🔑 <code>{fotp}</code>  <i>{bt}</i>") if clean else (
                    f"🌅 {aflag} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>  <i>{bt}</i>")
        return (
            f"🌅 <b>SUNSET OTP</b> 🌄\n{'—'*20}\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"🔑 <code>{fotp}</code>\n{'—'*20}\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>"
        ) if clean else (
            f"🌅 {aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"💬 <i>{body260}</i>\n<i>©By {bt}</i>")

    else:
        # ── T29: ULTRA (most compact — screenshot style #1) ───────────
        if for_group:
            return (f"🔑 OTP: <code>{fotp}</code>\n"
                    f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>©By {bt}</i>") if clean else (
                    f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
                    f"<i>{body160}</i>\n<i>©By {bt}</i>")
        return (
            f"🔑 <b>OTP: {fotp}</b>\n\n"
            f"MSG <b>Full Message:</b>\n<i>{body260}</i>\n\n"
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"<i>©By {bt}</i>"
        ) if clean else (
            f"{aflag} {aicon} <b>#{svc}</b>  <code>{nd}</code>\n"
            f"<i>{body260}</i>\n<i>©By {bt}</i>")


# ═══════════════════════════════════════════════════════════
#  GLOBAL STATE
# ═══════════════════════════════════════════════════════════
PANELS:               List              = []
IVAS_TASKS:           Dict[str,asyncio.Task] = {}
PROCESSED_MESSAGES:   set               = set()
OTP_SESSION_COUNTS:   Dict[str,int]     = {}
LAST_CHANGE_TIME:     Dict[int,datetime]= {}
CATEGORY_MAP:         Dict[str,str]     = {}
PANEL_ADD_STATES:     Dict[int,dict]    = {}
PANEL_EDIT_STATES:    Dict[int,dict]    = {}
AWAITING_ADMIN_ID:    Dict[int,bool]    = {}
AWAITING_PERMISSIONS: Dict[tuple,list]  = {}
AWAITING_LOG_ID:      Dict[int,bool]    = {}
BOT_ADD_STATES:       Dict[int,dict]    = {}
AWAITING_SUPER_ADMIN: Dict[int,bool]    = {}
CREATE_BOT_STATES:    Dict[int,dict]    = {}
BOT_REQUESTS:         Dict[int,dict]    = {}   # pending bot creation requests
AUTO_BROADCAST_ON:    bool              = True  # auto-broadcast on number upload
AWAITING_REQ_CHAT:    Dict[int,bool]    = {}   # waiting for group/channel ID to add
app = None

# ── OTP GUI Style (1-5, saved in config.json, changes all message formats) ──
GUI_STYLE: int = 1   # 1-8 styles

def load_gui_style():
    global GUI_STYLE
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                GUI_STYLE = int(json.load(f).get("GUI_STYLE", 1))
    except Exception:
        GUI_STYLE = 1

def save_gui_style(style: int):
    global GUI_STYLE
    GUI_STYLE = max(1, min(8, style))
    save_config_key("GUI_STYLE", GUI_STYLE)

load_gui_style()

# ═══════════════════════════════════════════════════════════
#  PANEL SESSION
# ═══════════════════════════════════════════════════════════
class PanelSession:
    """
    Each PanelSession owns a completely isolated aiohttp.ClientSession with its
    own CookieJar.  This means two different accounts on the same panel host
    (same base_url, different username/password) never share cookies or auth
    state — they are treated as entirely separate HTTP clients.
    """
    def __init__(self, base_url, username=None, password=None,
                 name="Unknown", panel_type="login", token=None, uri=None):
        self.base_url = base_url.rstrip("/")
        self.username = username; self.password = password
        self.name = name; self.panel_type = panel_type
        self.token = token; self.uri = uri
        self.login_url = f"{self.base_url}/login" if panel_type=="login" else None
        self.api_url = base_url; self.sesskey = None
        self.is_logged_in = False; self.id = None
        self.last_login_attempt = None; self.fail_count = 0
        self.stats_url: Optional[str] = None  # stored during endpoint discovery
        # Each PanelSession gets its OWN CookieJar — fully isolated from every
        # other session even when the same host is used by multiple accounts.
        self._cookie_jar = aiohttp.CookieJar(unsafe=True)
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # High-performance connector — 48-core server can handle more connections
            connector = aiohttp.TCPConnector(
                limit=100,           # max concurrent connections per session
                limit_per_host=20,   # max per host (prevents hammering one panel)
                ttl_dns_cache=300,   # cache DNS 5 minutes
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={"User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36")},
                cookie_jar=self._cookie_jar)
        return self._session

    async def reset_session(self):
        """Close HTTP session and wipe cookies — call before re-login."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        # Fresh CookieJar so stale cookies from a failed login don't interfere
        self._cookie_jar = aiohttp.CookieJar(unsafe=True)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

# ═══════════════════════════════════════════════════════════
#  PANEL DB HELPERS
# ═══════════════════════════════════════════════════════════
async def init_panels_table():
    async with db.AsyncSessionLocal() as s:
        await s.execute(stext("""
            CREATE TABLE IF NOT EXISTS panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, base_url TEXT NOT NULL,
                username TEXT, password TEXT, sesskey TEXT, api_url TEXT,
                token TEXT, uri TEXT, panel_type TEXT DEFAULT 'login',
                is_logged_in INTEGER DEFAULT 0, last_login_attempt TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""))
        await s.commit()

async def migrate_panels_table():
    async with db.AsyncSessionLocal() as s:
        cols = [r[1] for r in (await s.execute(stext("PRAGMA table_info(panels)"))).fetchall()]
        for col, defval in [("token","TEXT"),("panel_type","TEXT DEFAULT 'login'"),("uri","TEXT")]:
            if col not in cols:
                try: await s.execute(stext(f"ALTER TABLE panels ADD COLUMN {col} {defval}"))
                except Exception: pass
        await s.commit()

async def refresh_panels_from_db():
    global PANELS
    async with db.AsyncSessionLocal() as s:
        rows = (await s.execute(stext("SELECT * FROM panels"))).fetchall()
    new = []
    for r in rows:
        p = PanelSession(base_url=r[2],username=r[3],password=r[4],
                         name=r[1],panel_type=r[9] or "login",token=r[7],uri=r[8])
        p.id=r[0]; p.sesskey=r[5]; p.api_url=r[6] or r[2]
        p.is_logged_in=bool(r[10]); p.last_login_attempt=r[11]
        old = next((x for x in PANELS if x.id==p.id), None)
        if old: p._session = old._session
        new.append(p)
    PANELS = new

async def add_panel_to_db(name,base_url,username,password,panel_type="login",token=None,uri=None):
    async with db.AsyncSessionLocal() as s:
        await s.execute(stext(
            "INSERT INTO panels (name,base_url,username,password,panel_type,token,uri) "
            "VALUES (:n,:u,:us,:pw,:pt,:tk,:uri)"),
            dict(n=name,u=base_url,us=username,pw=password,pt=panel_type,tk=token,uri=uri))
        await s.commit()

async def update_panel_in_db(pid,name,base_url,username,password,panel_type,token,uri):
    async with db.AsyncSessionLocal() as s:
        await s.execute(stext(
            "UPDATE panels SET name=:n,base_url=:u,username=:us,password=:pw,"
            "panel_type=:pt,token=:tk,uri=:uri WHERE id=:id"),
            dict(n=name,u=base_url,us=username,pw=password,pt=panel_type,tk=token,uri=uri,id=pid))
        await s.commit()

async def delete_panel_from_db(pid: int):
    async with db.AsyncSessionLocal() as s:
        await s.execute(stext("DELETE FROM panels WHERE id=:id"),{"id":pid})
        await s.commit()

async def update_panel_login(pid,sesskey,api_url,logged_in:bool):
    async with db.AsyncSessionLocal() as s:
        await s.execute(stext(
            "UPDATE panels SET sesskey=:sk,api_url=:au,is_logged_in=:li,"
            "last_login_attempt=:now WHERE id=:id"),
            dict(sk=sesskey,au=api_url,li=1 if logged_in else 0,now=datetime.now(),id=pid))
        await s.commit()

async def load_panels_from_dex_to_db():
    """
    Load panels from dex.txt into the database.

    OLD behaviour: if count: return  — skipped entirely when even ONE panel
    already existed, so new dex.txt entries were never picked up after the
    first run.

    NEW behaviour: reads every entry and inserts only those whose name is not
    already in the database.  Adding panels to dex.txt and restarting is now
    enough — no need to wipe the database.

    Comment lines (starting with #) are stripped before parsing so example
    values like PANEL_BASE_URL = "<http://ip/ints>" in the header never
    accidentally create a phantom panel entry.
    """
    to_add = []

    if os.path.exists(DEX_FILE):
        try:
            raw = open(DEX_FILE, encoding="utf-8").read()
            # Remove comment lines so header examples never match the regex
            clean = "\n".join(
                l for l in raw.splitlines() if not l.strip().startswith("#"))

            for block in clean.split("panel="):
                if not block.strip():
                    continue
                name = block.strip().split("\n")[0].strip()
                if not name or name.startswith("<"):   # skip placeholder "<n>"
                    continue
                url = re.search(r'PANEL_BASE_URL\s*=\s*["\'\']([^"\'\']+)["\'\']', block)
                usr = re.search(r'PANEL_USERNAME\s*=\s*["\'\']([^"\'\']+)["\'\']', block)
                pw  = re.search(r'PANEL_PASSWORD\s*=\s*["\'\']([^"\'\']+)["\'\']', block)
                if not (url and usr and pw):
                    continue
                base_url = url.group(1).rstrip("/")
                if base_url.startswith("<") or not base_url.startswith("http"):
                    continue   # skip any remaining comment-derived junk
                to_add.append((name, base_url, usr.group(1), pw.group(1), "login", None, None))
                logger.info(f"📋 DEX entry found: {name}  →  {base_url}  user={usr.group(1)}")
        except Exception as e:
            logger.error(f"❌ DEX read error: {e}", exc_info=True)

    # Built-in CR-API panel — always ensure it is present
    to_add.append((
        "CR-API Panel 1",
        "http://147.135.212.197/crapi/had/viewstats",
        None, None, "api",
        "R1NQRTRSQopzh1aHZHSCfmiCklpycXSBeFV3QmaAdGtidFJeWItQ",
        None,
    ))

    inserted = 0
    skipped  = 0
    async with db.AsyncSessionLocal() as s:
        # Only insert panels whose name does not already exist in the database
        existing = {
            r[0] for r in
            (await s.execute(stext("SELECT name FROM panels"))).fetchall()
        }
        for name, url, usr, pw, pt, tok, uri in to_add:
            if name in existing:
                skipped += 1
                continue
            await s.execute(
                stext("INSERT INTO panels "
                      "(name,base_url,username,password,panel_type,token,uri) "
                      "VALUES (:n,:u,:us,:pw,:pt,:tk,:uri)"),
                dict(n=name, u=url, us=usr, pw=pw, pt=pt, tk=tok, uri=uri))
            inserted += 1
        await s.commit()

    logger.info(
        f"✅ DEX load done — {inserted} new panel(s) inserted, "
        f"{skipped} already in DB")


# ═══════════════════════════════════════════════════════════
#  ADMIN PERMISSIONS
# ═══════════════════════════════════════════════════════════
async def init_permissions_table():
    async with db.AsyncSessionLocal() as s:
        await s.execute(stext("""
            CREATE TABLE IF NOT EXISTS admin_permissions (
                user_id INTEGER PRIMARY KEY, permissions TEXT NOT NULL)"""))
        for uid in INITIAL_ADMIN_IDS:
            await s.execute(stext(
                "INSERT OR REPLACE INTO admin_permissions (user_id,permissions) VALUES (:u,:p)"),
                {"u":uid,"p":json.dumps(list(PERMISSIONS.keys()))})
        await s.commit()

async def get_admin_permissions(uid: int) -> List[str]:
    async with db.AsyncSessionLocal() as s:
        row = (await s.execute(stext(
            "SELECT permissions FROM admin_permissions WHERE user_id=:u"),{"u":uid})).fetchone()
        return json.loads(row[0]) if row else []

async def set_admin_permissions(uid: int, perms: List[str]):
    async with db.AsyncSessionLocal() as s:
        await s.execute(stext(
            "INSERT OR REPLACE INTO admin_permissions (user_id,permissions) VALUES (:u,:p)"),
            {"u":uid,"p":json.dumps(perms)})
        await s.commit()

async def remove_admin_permissions(uid: int):
    async with db.AsyncSessionLocal() as s:
        await s.execute(stext("DELETE FROM admin_permissions WHERE user_id=:u"),{"u":uid})
        await s.commit()

async def list_all_admins() -> List[int]:
    async with db.AsyncSessionLocal() as s:
        return [r[0] for r in (await s.execute(stext("SELECT user_id FROM admin_permissions"))).fetchall()]

def is_super_admin(uid: int) -> bool:
    return uid in INITIAL_ADMIN_IDS

# ═══════════════════════════════════════════════════════════
#  MEMBERSHIP GATE
# ═══════════════════════════════════════════════════════════
async def check_membership(bot, uid: int) -> list:
    """
    Returns list of chats the user has NOT joined.
    Returns empty list if user is a member of all REQUIRED_CHATS.
    Admins and super-admins always pass.
    """
    if is_super_admin(uid):
        return []
    perms = await get_admin_permissions(uid)
    if perms:
        return []
    missing = []
    for chat in REQUIRED_CHATS:
        try:
            member = await bot.get_chat_member(chat_id=chat["id"], user_id=uid)
            if member.status in ("left", "kicked", "banned"):
                missing.append(chat)
        except Exception:
            # Can't check → assume not joined (bot might not be admin there)
            missing.append(chat)
    return missing

def join_required_kb(missing: list) -> InlineKeyboardMarkup:
    """Keyboard with buttons for each chat the user still needs to join."""
    rows = []
    for chat in missing:
        rows.append([InlineKeyboardButton(
            f"➡️  Join {chat['title']}", url=chat["link"])])
    rows.append([InlineKeyboardButton(
        "✅  I've Joined — Check Again", callback_data="check_membership")])
    return InlineKeyboardMarkup(rows)

async def send_join_required(update_or_query, bot, uid: int, missing: list):
    """Send the 'please join first' message to a user."""
    chat_links = "\n".join(
        f"  • <a href='{c['link']}'>{c['title']}</a>" for c in missing)
    text = (
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"  🔒 {ui('lock')} <b>Access Required</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "To use <b>Crack SMS</b> you must join our communities:\n\n"
        f"{chat_links}\n\n"
        "After joining, tap <b>✅ I've Joined</b> below."
    )
    kb = join_required_kb(missing)
    if hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(text, reply_markup=kb, parse_mode="HTML",
                                                  disable_web_page_preview=True)
    elif hasattr(update_or_query, "edit_message_text"):
        try:
            await update_or_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML",
                                                     disable_web_page_preview=True)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════
#  OTP KEYBOARD  — uses bot's own configured links
# ═══════════════════════════════════════════════════════════
def otp_keyboard(otp: Optional[str], full_msg: str = "",
                 for_group: bool = False) -> InlineKeyboardMarkup:
    """
    Unified OTP keyboard — reads OTP_GUI_THEME only.
    Group: copy OTP + PANEL/INFO.
    DM: copy OTP + copy SMS + PANEL/INFO + theme label.
    """
    clean     = re.sub(r"[^0-9]", "", otp) if otp else ""
    panel_url = NUMBER_BOT_LINK or GET_NUMBER_URL or (
        f"https://t.me/{BOT_USERNAME.lstrip('@')}" if BOT_USERNAME else None)
    info_url  = OTP_GROUP_LINK or CHANNEL_LINK
    t         = OTP_GUI_THEME % 30
    kb        = []

    if for_group:
        if clean:
            kb.append([InlineKeyboardButton(
                f"»»  📋  {clean}", copy_text=CopyTextButton(text=clean))])
        row = []
        if panel_url: row.append(InlineKeyboardButton("🚀  <b>PANEL</b>  ", url=panel_url))
        if info_url:  row.append(InlineKeyboardButton("💬  <b>Numbers</b>  ",  url=info_url))
        if row: kb.append(row)
        return InlineKeyboardMarkup(kb)

    # DM — copy button style matches theme family
    if clean:
        if t in range(10, 20):    # electric / bold family
            kb.append([InlineKeyboardButton(
                f"⚡  {clean}  ⚡", copy_text=CopyTextButton(text=clean))])
        elif t in range(20, 30):  # premium family
            kb.append([InlineKeyboardButton(
                f"✅  Copy: {clean}", copy_text=CopyTextButton(text=clean))])
        else:                      # classic / dark / minimal
            kb.append([InlineKeyboardButton(
                f"»»  📋  {clean}", copy_text=CopyTextButton(text=clean))])
    if full_msg:
        kb.append([InlineKeyboardButton(
            "📩  Copy SMS", copy_text=CopyTextButton(text=full_msg[:256]))])
    row = []
    if panel_url: row.append(InlineKeyboardButton("📱  Get Number ↗", url=panel_url))
    if info_url:  row.append(InlineKeyboardButton("💬  Group ↗",      url=info_url))
    if row: kb.append(row)
    return InlineKeyboardMarkup(kb)

# ═══════════════════════════════════════════════════════════
#  USER KEYBOARDS
# ═══════════════════════════════════════════════════════════
def main_menu_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🧇  Get Number",  callback_data="buy_menu"),
         InlineKeyboardButton("🫁  My Profile",  callback_data="profile")],
        [InlineKeyboardButton("🤖  Create My Bot", callback_data="create_bot_menu")],
    ]
    if OTP_GROUP_LINK or CHANNEL_LINK:
        row2 = []
        if CHANNEL_LINK:    row2.append(InlineKeyboardButton("📢  Channel",   url=CHANNEL_LINK))
        if OTP_GROUP_LINK:  row2.append(InlineKeyboardButton("💬  OTP Group", url=OTP_GROUP_LINK))
        if row2: kb.append(row2)
    nb = NUMBER_BOT_LINK or GET_NUMBER_URL
    row3 = []
    if nb: row3.append(InlineKeyboardButton("📞  Number Bot", url=nb))
    sup = SUPPORT_USER.lstrip("@")
    if sup: row3.append(InlineKeyboardButton("🛟  Support",   url=f"https://t.me/{sup}"))
    if row3: kb.append(row3)
    dev = DEVELOPER.lstrip("@")
    if dev:
        kb.append([InlineKeyboardButton("🧠  Developer",  url=f"https://t.me/{dev}")])
    return InlineKeyboardMarkup(kb)

def services_kb(svcs: list) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(f"📱  {s}", callback_data=f"svc_{s}")] for s in svcs]
    kb.append([InlineKeyboardButton("🔙  Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(kb)

def countries_kb(svc: str, countries: list) -> InlineKeyboardMarkup:
    kb = []; row = []
    for flag, name in countries:
        row.append(InlineKeyboardButton(f"{flag} {name}", callback_data=f"cntry|{svc}|{name}"))
        if len(row)==2: kb.append(row); row=[]
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("🔙  Back", callback_data="buy_menu")])
    return InlineKeyboardMarkup(kb)

def waiting_kb(prefix=None, service=None) -> InlineKeyboardMarkup:
    pfx = f"ON ({prefix})" if prefix else "OFF"
    kb = [
        [InlineKeyboardButton("🚫  Block Number",   callback_data="ask_block"),
         InlineKeyboardButton("🔄  Change Number",  callback_data="skip_next")],
        [InlineKeyboardButton("🌍  Change Country", callback_data="change_country"),
         InlineKeyboardButton(f"🔡  Prefix: {pfx}", callback_data="set_prefix")],
        [InlineKeyboardButton("📋  Change Service", callback_data="buy_menu")],
    ]
    if OTP_GROUP_LINK:
        kb.append([InlineKeyboardButton("💬  OTP Group", url=OTP_GROUP_LINK)])
    return InlineKeyboardMarkup(kb)

def confirm_block_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅  Yes Block",  callback_data="block_yes"),
        InlineKeyboardButton("❌  No Keep",    callback_data="block_no"),
    ]])

# ═══════════════════════════════════════════════════════════
#  ADMIN KEYBOARDS  — Pro-level submenus
# ═══════════════════════════════════════════════════════════
def admin_main_kb(perms: list, is_sup: bool) -> InlineKeyboardMarkup:
    kb = []
    r1 = []
    if "manage_files" in perms: r1.append(InlineKeyboardButton("📂  Numbers",    callback_data="admin_numbers"))
    if "broadcast"    in perms: r1.append(InlineKeyboardButton("📢  Broadcast",  callback_data="admin_broadcast"))
    if r1: kb.append(r1)
    r2 = []
    if "view_stats"    in perms: r2.append(InlineKeyboardButton("📊  Statistics", callback_data="admin_stats_menu"))
    if is_sup:                   r2.append(InlineKeyboardButton("👤  Users",       callback_data="admin_users"))
    if r2: kb.append(r2)
    r3 = []
    if "manage_panels" in perms: r3.append(InlineKeyboardButton("🔌  Panels",     callback_data="admin_panel_manager"))
    if "manage_logs"   in perms: r3.append(InlineKeyboardButton("📋  Logs",        callback_data="admin_manage_logs"))
    if r3: kb.append(r3)
    r4 = []
    if is_sup: r4.append(InlineKeyboardButton("👥  Admins",    callback_data="admin_manage_admins"))
    r4.append(   InlineKeyboardButton("⚙️  Settings",          callback_data="admin_settings"))
    kb.append(r4)
    r5 = []
    if "manage_panels" in perms: r5.append(InlineKeyboardButton("📡  Fetch SMS",  callback_data="admin_fetch_sms"))
    if is_sup:                   r5.append(InlineKeyboardButton("🛠  Advanced",   callback_data="admin_advanced"))
    if r5: kb.append(r5)
    if is_sup:
        kb.append([InlineKeyboardButton("🔑  OTP Tools",        callback_data="admin_otp_tools"),
                   InlineKeyboardButton("🔔  Notify",           callback_data="admin_notify_menu")])
    if is_sup and not IS_CHILD_BOT:
        kb.append([InlineKeyboardButton("🤖  Add Bot",          callback_data="add_bot_start"),
                   InlineKeyboardButton("🖥  Manage Bots",      callback_data="admin_bots")])
        kb.append([InlineKeyboardButton("📢  Broadcast All Bots", callback_data="broadcast_all_bots")])
    return InlineKeyboardMarkup(kb)

# ── Numbers submenu ───────────────────────────────────────────
def admin_numbers_kb(cats: list) -> InlineKeyboardMarkup:
    kb = []
    for cat, cnt in cats:
        sid = hashlib.md5(cat.encode()).hexdigest()[:10]
        CATEGORY_MAP[sid] = cat
        kb.append([
            InlineKeyboardButton(f"📁 {cat}  ({cnt})", callback_data="ignore"),
            InlineKeyboardButton("📊", callback_data=f"cat_stats_{sid}"),
            InlineKeyboardButton("🗑", callback_data=f"del_{sid}"),
        ])
    kb.append([InlineKeyboardButton("📤  Upload Numbers",   callback_data="admin_upload_info"),
               InlineKeyboardButton("📋  All Categories",   callback_data="admin_files")])
    kb.append([InlineKeyboardButton("♻️  Free Cooldowns",   callback_data="admin_reset"),
               InlineKeyboardButton("🗑  Purge Used",        callback_data="purge_used")])
    kb.append([InlineKeyboardButton("🚫  Purge Blocked",    callback_data="purge_blocked"),
               InlineKeyboardButton("📊  Full Stats",        callback_data="admin_stats")])
    kb.append([InlineKeyboardButton("🔙  Back",             callback_data="admin_home")])
    return InlineKeyboardMarkup(kb)

# ── Stats submenu ─────────────────────────────────────────────
def admin_stats_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊  Live Stats",       callback_data="admin_stats"),
         InlineKeyboardButton("📈  OTP History",      callback_data="admin_otp_history")],
        [InlineKeyboardButton("🔌  Panel Status",     callback_data="test_panels"),
         InlineKeyboardButton("💾  DB Summary",       callback_data="admin_db_summary")],
        [InlineKeyboardButton("👤  User Count",       callback_data="admin_list_users"),
         InlineKeyboardButton("🔑  OTP Store",        callback_data="admin_otp_store")],
        [InlineKeyboardButton("🔙  Back",             callback_data="admin_home")],
    ])

# ── OTP Tools submenu (super only) ────────────────────────────
def admin_otp_tools_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑  View OTP Store",   callback_data="admin_otp_store"),
         InlineKeyboardButton("📤  Export OTPs",      callback_data="export_otps")],
        [InlineKeyboardButton("🗑  Clear OTP Store",  callback_data="clear_otps"),
         InlineKeyboardButton("📈  OTP History",      callback_data="admin_otp_history")],
        [InlineKeyboardButton("🔍  Find OTP by Number", callback_data="find_otp_prompt")],
        [InlineKeyboardButton("🔙  Back",             callback_data="admin_home")],
    ])

# ── Notify/Broadcast submenu ──────────────────────────────────
def admin_notify_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢  Broadcast Users",  callback_data="admin_broadcast"),
         InlineKeyboardButton("📢  Broadcast All Bots", callback_data="broadcast_all_bots")],
        [InlineKeyboardButton("📋  Log Groups",       callback_data="admin_manage_logs"),
         InlineKeyboardButton("➕  Add Log Group",    callback_data="add_log_prompt")],
        [InlineKeyboardButton("🔔  Send Test OTP",    callback_data="send_test_otp"),
         InlineKeyboardButton("📡  Ping Log Groups",  callback_data="ping_log_groups")],
        [InlineKeyboardButton("🔙  Back",             callback_data="admin_home")],
    ])

# ── Users submenu (super admin) ───────────────────────────────
def admin_users_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥  All Users",         callback_data="admin_list_users"),
         InlineKeyboardButton("📊  User Stats",        callback_data="admin_db_summary")],
        [InlineKeyboardButton("🔢  Global Limit",      callback_data="set_limit"),
         InlineKeyboardButton("🚫  Free All Numbers",  callback_data="admin_reset")],
        [InlineKeyboardButton("📢  Broadcast Users",   callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙  Back",              callback_data="admin_home")],
    ])

# ── Panel Manager ─────────────────────────────────────────────
def panel_mgr_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑  Login Panels",     callback_data="panels_login"),
         InlineKeyboardButton("🔌  API Panels",       callback_data="panels_api")],
        [InlineKeyboardButton("📡  IVAS Panels",      callback_data="panels_ivas")],
        [InlineKeyboardButton("🔄  Login All Now",    callback_data="login_all_panels"),
         InlineKeyboardButton("🔁  Restart Workers",  callback_data="restart_workers")],
        [InlineKeyboardButton("📋  View Logs",        callback_data="view_logs"),
         InlineKeyboardButton("📡  Fetch SMS Now",    callback_data="admin_fetch_sms")],
        [InlineKeyboardButton("🔙  Back",             callback_data="admin_home")],
    ])

def panel_list_kb(panels: list, ptype: str) -> InlineKeyboardMarkup:
    kb = []
    for p in panels:
        if ptype=="ivas": st="🟢" if (p.name in IVAS_TASKS and not IVAS_TASKS[p.name].done()) else "🔴"
        else:             st="🟢" if p.is_logged_in else "🔴"
        kb.append([
            InlineKeyboardButton(f"{st} {p.name}", callback_data="ignore"),
            InlineKeyboardButton("🔍", callback_data=f"p_info_{p.id}"),
            InlineKeyboardButton("🔄", callback_data=f"p_test_{p.id}"),
            InlineKeyboardButton("✏️", callback_data=f"p_edit_{p.id}"),
            InlineKeyboardButton("🗑", callback_data=f"p_del_{p.id}"),
        ])
    kb.append([InlineKeyboardButton("➕  Add Panel", callback_data="p_add")])
    kb.append([InlineKeyboardButton("🔙  Back",      callback_data="admin_panel_manager")])
    return InlineKeyboardMarkup(kb)

def ptype_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑  Login Panel",       callback_data="pt_login")],
        [InlineKeyboardButton("🔌  API Type 1 (CR-API)",  callback_data="pt_api"),
         InlineKeyboardButton("🆕  API Type 2 (Reseller)", callback_data="pt_api_v2")],
        [InlineKeyboardButton("📡  IVAS Panel",        callback_data="pt_ivas")],
        [InlineKeyboardButton("❌  Cancel",            callback_data="cancel_action")],
    ])

def confirm_del_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅  Yes, Delete", callback_data="p_del_confirm"),
        InlineKeyboardButton("❌  Cancel",      callback_data="admin_panel_manager"),
    ]])

_THEME_NAMES = {
    0: "🖤 Premium Dark",
    1: "⚡ Neon Electric",
    2: "🔥 Sigma Classic",
    3: "🤍 Minimal Clean",
    4: "👑 Royal Gold",
    5: "💫 TempNum Style   ⭐PREMIUM",
    6: "🚀 Jack-X Style    ⭐PREMIUM",
    7: "☠️  Cyber Matrix    ⭐PREMIUM",
}

def admin_settings_kb() -> InlineKeyboardMarkup:
    theme_name = _THEME_NAMES.get(OTP_GUI_THEME % 30, "Unknown")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📦  Assign Limit: {DEFAULT_ASSIGN_LIMIT}", callback_data="set_limit")],
        [InlineKeyboardButton("🔗  Bot Links",        callback_data="admin_links"),
         InlineKeyboardButton("🤖  Bot Info",         callback_data="admin_botinfo")],
        [InlineKeyboardButton(f"🎨  OTP GUI: {theme_name}", callback_data="admin_gui_theme")],
        [InlineKeyboardButton("🚪  Required Chats",   callback_data="admin_req_chats"),
         InlineKeyboardButton("📢  Auto Broadcast",   callback_data="admin_broadcast_menu")],
        [InlineKeyboardButton("🧹  Maintenance",      callback_data="admin_maintenance"),
         InlineKeyboardButton("🔑  Change Token",     callback_data="change_token_prompt")],
        [InlineKeyboardButton("🌍  Reload Countries", callback_data="reload_countries"),
         InlineKeyboardButton("📋  View Bot Logs",    callback_data="view_logs")],
        [InlineKeyboardButton("🔙  Back",             callback_data="admin_home")],
    ])

def gui_theme_kb(page: int = 0) -> InlineKeyboardMarkup:
    """30 compact designs in a scrollable 2-column grid. page=0..4 (6 per page)."""
    per_page = 6
    start    = page * per_page
    end      = min(start + per_page, 30)
    total_pages = (30 + per_page - 1) // per_page   # 5 pages
    kb = []
    row = []
    for tid in range(start, end):
        mark = "✅ " if tid == OTP_GUI_THEME % 30 else ""
        name = _THEME_NAMES.get(tid, f"Design {tid+1}")
        row.append(InlineKeyboardButton(f"{mark}{name}", callback_data=f"set_gui_theme_{tid}"))
        if len(row) == 2:
            kb.append(row); row = []
    if row: kb.append(row)
    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"gui_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"gui_page_{page+1}"))
    if nav: kb.append(nav)
    kb.append([InlineKeyboardButton("🔙  Back", callback_data="admin_settings")])
    return InlineKeyboardMarkup(kb)


def gui_theme_page_kb(page: int = 0) -> InlineKeyboardMarkup:
    """30 compact designs, 10 per page. Super admins only."""
    kb = []
    start_t = page * 10
    end_t   = min(start_t + 10, 30)
    for tid in range(start_t, end_t):
        name = _THEME_NAMES.get(tid, f"Design {tid+1}")
        mark = "✅ " if tid == OTP_GUI_THEME % 30 else ""
        kb.append([InlineKeyboardButton(f"{mark}{name}", callback_data=f"set_gui_theme_{tid}")])
    nav = []
    if page > 0:   nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"gui_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"  {page+1}/3  ", callback_data="ignore"))
    if page < 2:   nav.append(InlineKeyboardButton("Next ▶", callback_data=f"gui_page_{page+1}"))
    if nav: kb.append(nav)
    kb.append([InlineKeyboardButton("🔙  Back", callback_data="admin_settings")])
    return InlineKeyboardMarkup(kb)

def admin_links_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢  Channel Link",    callback_data="set_channel_prompt")],
        [InlineKeyboardButton("💬  OTP Group Link",  callback_data="set_otpgroup_prompt")],
        [InlineKeyboardButton("📞  Number Bot Link", callback_data="set_numbot_prompt")],
        [InlineKeyboardButton("🛟  Support User",    callback_data="set_support_prompt")],
        [InlineKeyboardButton("🧠  Developer",       callback_data="set_developer_prompt")],
        [InlineKeyboardButton("🔙  Back",            callback_data="admin_settings")],
    ])

def admin_maintenance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("♻️  Free All Cooldowns", callback_data="admin_reset"),
         InlineKeyboardButton("🗑  Clear OTP Store",    callback_data="clear_otps")],
        [InlineKeyboardButton("🗑  Purge Used Numbers", callback_data="purge_used"),
         InlineKeyboardButton("🗑  Purge Blocked Nums", callback_data="purge_blocked")],
        [InlineKeyboardButton("🔄  Reload Countries",   callback_data="reload_countries"),
         InlineKeyboardButton("🔁  Restart All Workers",callback_data="restart_workers")],
        [InlineKeyboardButton("🔙  Back",               callback_data="admin_settings")],
    ])

def limit_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(str(i), callback_data=f"glimit_{i}") for i in rng]
            for rng in [range(1,4), range(4,7), range(7,11)]]
    rows.append([InlineKeyboardButton("🔙  Back", callback_data="admin_settings")])
    return InlineKeyboardMarkup(rows)

def advanced_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄  Test All Panels",   callback_data="test_panels"),
         InlineKeyboardButton("🔌  Login All Panels",  callback_data="login_all_panels")],
        [InlineKeyboardButton("📡  Fetch SMS Now",     callback_data="admin_fetch_sms"),
         InlineKeyboardButton("🔁  Restart Workers",   callback_data="restart_workers")],
        [InlineKeyboardButton("🔑  OTP Tools",         callback_data="admin_otp_tools"),
         InlineKeyboardButton("🧹  Maintenance",       callback_data="admin_maintenance")],
        [InlineKeyboardButton("📋  View Logs",         callback_data="view_logs"),
         InlineKeyboardButton("💾  DB Summary",        callback_data="admin_db_summary")],
        [InlineKeyboardButton("📊  OTP History",       callback_data="admin_otp_history"),
         InlineKeyboardButton("🔔  Notify Menu",       callback_data="admin_notify_menu")],
        [InlineKeyboardButton("🌍  Reload Countries",  callback_data="reload_countries"),
         InlineKeyboardButton("🔢  Set Limit",         callback_data="set_limit")],
        [InlineKeyboardButton("🔙  Back",              callback_data="admin_home")],
    ])

def files_kb(cats: list) -> InlineKeyboardMarkup:
    """Legacy alias kept for compatibility — use admin_numbers_kb for new code."""
    return admin_numbers_kb(cats)

def svc_sel_kb(selected: list = None) -> InlineKeyboardMarkup:
    if not selected: selected = []
    ALL = ["WhatsApp","Telegram","Facebook","Instagram","Twitter","TikTok",
           "Google","Microsoft","Snapchat","Signal","Tinder","Uber","Amazon","PayPal"]
    kb = []; row = []
    for s in ALL:
        row.append(InlineKeyboardButton(("✅ " if s in selected else "")+s, callback_data=f"us_{s}"))
        if len(row)==2: kb.append(row); row=[]
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("✅  Done",   callback_data="us_done"),
               InlineKeyboardButton("❌  Cancel", callback_data="us_cancel")])
    return InlineKeyboardMarkup(kb)

def admin_list_kb(admins: list) -> InlineKeyboardMarkup:
    kb = []
    for aid in admins:
        crown = "👑 " if aid in INITIAL_ADMIN_IDS else ""
        kb.append([InlineKeyboardButton(f"{crown}{aid}", callback_data="ignore"),
                   InlineKeyboardButton("❌ Remove", callback_data=f"rm_admin_{aid}")])
    kb.append([InlineKeyboardButton("➕  Add Admin",  callback_data="add_admin_prompt")])
    kb.append([InlineKeyboardButton("🔙  Back",       callback_data="admin_home")])
    return InlineKeyboardMarkup(kb)

def perms_kb(selected: list, uid: int) -> InlineKeyboardMarkup:
    kb = []
    for perm, desc in PERMISSIONS.items():
        mark = "✅ " if perm in selected else "⬜ "
        kb.append([InlineKeyboardButton(f"{mark}{desc}",
                                        callback_data=f"ptoggle|{uid}|{perm}")])
    kb.append([InlineKeyboardButton("✅  Save", callback_data=f"pdone|{uid}")])
    kb.append([InlineKeyboardButton("❌  Cancel", callback_data="cancel_action")])
    return InlineKeyboardMarkup(kb)

def logs_kb(chats: list) -> InlineKeyboardMarkup:
    kb = []
    for cid in chats:
        kb.append([InlineKeyboardButton(f"📢 {cid}", callback_data="ignore"),
                   InlineKeyboardButton("❌", callback_data=f"rm_log_{cid}")])
    kb.append([InlineKeyboardButton("➕  Add Log Group", callback_data="add_log_prompt")])
    kb.append([InlineKeyboardButton("🔙  Back",          callback_data="admin_home")])
    return InlineKeyboardMarkup(kb)

def bots_list_kb(bots: list) -> InlineKeyboardMarkup:
    """Premium child bot list with status indicators and quick actions."""
    kb = []
    run_count = sum(1 for b in bots if b.get("running"))
    for info in bots:
        bid = info["id"]; st = "🟢" if info.get("running") else "🔴"
        name = html.escape(info["name"])[:18]
        kb.append([
            InlineKeyboardButton(f"{st} {name}", callback_data="ignore"),
            InlineKeyboardButton("ℹ️", callback_data=f"bot_info_{bid}"),
            InlineKeyboardButton("▶️" if not info.get("running") else "⏹", 
                                 callback_data=f"bot_start_{bid}" if not info.get("running") else f"bot_stop_{bid}"),
            InlineKeyboardButton("🔁", callback_data=f"bot_restart_{bid}"),
            InlineKeyboardButton("🗑", callback_data=f"bot_del_{bid}"),
        ])
    kb.append([
        InlineKeyboardButton("🤖  Add Bot",        callback_data="add_bot_start"),
        InlineKeyboardButton("📢  Broadcast All",  callback_data="broadcast_all_bots"),
    ])
    kb.append([
        InlineKeyboardButton("▶️  Start All",      callback_data="bots_start_all"),
        InlineKeyboardButton("⏹  Stop All",        callback_data="bots_stop_all"),
    ])
    kb.append([
        InlineKeyboardButton("📊  All Stats",      callback_data="bots_all_stats"),
        InlineKeyboardButton("🔁  Refresh",        callback_data="admin_bots"),
    ])
    kb.append([InlineKeyboardButton("🔙  Back to Admin", callback_data="admin_home")])
    return InlineKeyboardMarkup(kb)

def bot_actions_kb(bid: str, running: bool, info: dict = None) -> InlineKeyboardMarkup:
    """Expanded per-bot action panel."""
    info = info or {}
    r_row = []
    if running:
        r_row = [InlineKeyboardButton("⏹  Stop",    callback_data=f"bot_stop_{bid}"),
                 InlineKeyboardButton("🔁  Restart", callback_data=f"bot_restart_{bid}")]
    else:
        r_row = [InlineKeyboardButton("▶️  Start",   callback_data=f"bot_start_{bid}"),
                 InlineKeyboardButton("🔁  Restart", callback_data=f"bot_restart_{bid}")]
    return InlineKeyboardMarkup([
        r_row,
        [InlineKeyboardButton("📋  View Logs",    callback_data=f"bot_log_{bid}"),
         InlineKeyboardButton("📊  Bot Stats",    callback_data=f"bot_stats_{bid}")],
        [InlineKeyboardButton("📢  Broadcast",    callback_data=f"bot_bcast_{bid}"),
         InlineKeyboardButton("🔗  Edit Links",   callback_data=f"bot_editlinks_{bid}")],
        [InlineKeyboardButton("🗑  Delete Bot",   callback_data=f"bot_del_{bid}"),
         InlineKeyboardButton("🔙  Back",         callback_data="admin_bots")],
    ])

def confirm_del_bot_kb(bid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅  Yes, Delete", callback_data=f"bot_delok_{bid}"),
        InlineKeyboardButton("❌  Cancel",      callback_data=f"bot_info_{bid}"),
    ]])

def bot_edit_links_kb(bid: str) -> InlineKeyboardMarkup:
    """Edit a child bot's configured links inline."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢  Channel Link",    callback_data=f"bot_setlink_{bid}_CHANNEL_LINK")],
        [InlineKeyboardButton("💬  OTP Group Link",  callback_data=f"bot_setlink_{bid}_OTP_GROUP_LINK")],
        [InlineKeyboardButton("📞  Number Bot Link", callback_data=f"bot_setlink_{bid}_NUMBER_BOT_LINK")],
        [InlineKeyboardButton("🛟  Support User",    callback_data=f"bot_setlink_{bid}_SUPPORT_USER")],
        [InlineKeyboardButton("🔙  Back",            callback_data=f"bot_info_{bid}")],
    ])

def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅  Confirm", callback_data=f"confirm_{action}"),
        InlineKeyboardButton("❌  Cancel",  callback_data="cancel_action"),
    ]])


# ═══════════════════════════════════════════════════════════
#  PANEL LOGIN / FETCH
# ═══════════════════════════════════════════════════════════
async def test_api_panel(panel: PanelSession) -> bool:
    """Test Type 1 CR-API panel."""
    try:
        s = await panel.get_session()
        now = datetime.now(); prev = now - timedelta(hours=24)
        params = {"token":panel.token,"dt1":prev.strftime("%Y-%m-%d %H:%M:%S"),
                  "dt2":now.strftime("%Y-%m-%d %H:%M:%S"),"records":1}
        async with s.get(panel.base_url,params=params,timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200: return False
            try: data = await resp.json(content_type=None)
            except Exception: return False
            if isinstance(data, list): return True
            if isinstance(data, dict):
                st = str(data.get("status","")).lower()
                if st == "error": return False
                return st == "success" or any(k in data for k in ("data","records","sms"))
    except Exception as e: logger.error(f"API test '{panel.name}': {e}")
    return False

async def test_reseller_api(panel: PanelSession) -> bool:
    """Test Type 2 Reseller API (mdr.php endpoint)."""
    try:
        s   = await panel.get_session()
        now = datetime.now(); prev = now - timedelta(hours=1)
        params = {
            "token":    panel.token,
            "fromdate": prev.strftime("%Y-%m-%d %H:%M:%S"),
            "todate":   now.strftime("%Y-%m-%d %H:%M:%S"),
            "records":  1,
        }
        async with s.get(panel.base_url, params=params,
                         timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200: return False
            data = await resp.json(content_type=None)
            st = str(data.get("status","")).lower()
            return "success" in st or "data" in data
    except Exception as e:
        logger.error(f"Reseller API test '{panel.name}': {e}")
    return False

async def fetch_reseller_api(panel: PanelSession) -> Optional[list]:
    """
    Fetch SMS records from Type 2 Reseller API.
    URL format: http://host/crapi/reseller/mdr.php
    Response:   {"status":"Success","records":N,"data":[{"datetime":...,"number":...,"cli":...,"message":...}]}
    """
    try:
        s   = await panel.get_session()
        now = datetime.now(); prev = now - timedelta(days=1)
        params = {
            "token":    panel.token,
            "fromdate": prev.strftime("%Y-%m-%d %H:%M:%S"),
            "todate":   now.strftime("%Y-%m-%d %H:%M:%S"),
            "records":  API_MAX_RECORDS,   # max 200
        }
        async with s.get(panel.base_url, params=params,
                         timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                panel.fail_count += 1
                if panel.fail_count >= 3: panel.is_logged_in = False
                return None
            data = await resp.json(content_type=None)
            st = str(data.get("status","")).lower()
            if "error" in st:
                logger.error(f"Reseller API '{panel.name}' error: {data.get('status')}")
                panel.fail_count += 1
                if panel.fail_count >= 3: panel.is_logged_in = False
                return None
            records = data.get("data") or []
            panel.fail_count = 0; panel.is_logged_in = True
            out = []
            for rec in records:
                if not isinstance(rec, dict): continue
                dt  = rec.get("datetime") or rec.get("dt") or ""
                num = str(rec.get("number","")).replace("+","").strip()
                cli = str(rec.get("cli","") or "unknown").lower()
                msg = str(rec.get("message","") or rec.get("text","") or "")
                if not msg or not num: continue
                out.append([str(dt), num, cli, msg])
            out.sort(key=lambda x: x[0], reverse=True)
            logger.info('📥 Reseller %s → %d record(s)' % (panel.name, len(out)))
            return out
    except Exception as e:
        logger.error(f"Reseller API fetch '{panel.name}': {e}")
        panel.fail_count += 1
        if panel.fail_count >= 3: panel.is_logged_in = False
        return None

async def login_to_panel(panel: PanelSession) -> bool:
    """
    Login for panels that follow the /ints/ URL structure, e.g.:
        base_url  = http://185.2.83.39/ints          (trailing slash stripped)
        login page= http://185.2.83.39/ints/login
        form POST = http://185.2.83.39/ints/signin   (relative → urljoin)
        stats page= http://185.2.83.39/ints/SMSCDRStats
        data API  = http://185.2.83.39/ints/res/data_smscdr.php

    Key rule: panel.base_url already contains the full path prefix (/ints),
    so use it directly for all endpoint construction.  Never strip the path.
    """
    if panel.panel_type in ("api", "api_v2"):
        if panel.panel_type == "api_v2":
            ok = await test_reseller_api(panel)
        else:
            ok = await test_api_panel(panel)
        panel.is_logged_in = ok
        api_label = "Reseller API" if panel.panel_type == "api_v2" else "CR-API"
        if ok:  logger.info(f"🔌 {api_label} panel \"{panel.name}\" — token OK")
        else:   logger.warning(f"🔌 {api_label} panel \"{panel.name}\" — token FAILED")
        return ok

    logger.info(f"🔑 Logging in to \"{panel.name}\"  →  {panel.base_url}")
    await panel.reset_session()  # fresh isolated CookieJar every attempt

    try:
        s = await panel.get_session()

        # ── 1. Load the login page ────────────────────────────────────
        # base_url already has /ints, so /login gives http://ip/ints/login
        login_url = panel.login_url or f"{panel.base_url}/login"
        logger.info(f"   ↗ GET  {login_url}")
        async with s.get(login_url, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                logger.warning(f"   ✗ Login page HTTP {r.status}  panel=\"{panel.name}\"")
                return False
            pg = await r.text()

        # ── 2. Parse the form ─────────────────────────────────────────
        soup = BeautifulSoup(pg, "html.parser")
        form = soup.find("form")
        if not form:
            logger.warning(f"   ✗ No <form> found at {login_url}")
            return False

        payload = {}
        for tag in form.find_all("input"):
            nm  = tag.get("name")
            val = tag.get("value", "")
            ph  = (tag.get("placeholder", "") + " " + (nm or "")).lower()
            tp  = tag.get("type", "text").lower()
            if not nm:
                continue
            if tp == "hidden":
                # Keep all hidden fields exactly — these carry CSRF tokens
                payload[nm] = val
            elif any(k in ph for k in ("user", "email", "login", "uname", "username")):
                payload[nm] = panel.username or ""
                logger.info(f"   ↳ username field → {nm}")
            elif any(k in ph for k in ("pass", "pwd", "secret", "password")):
                payload[nm] = panel.password or ""
                logger.info(f"   ↳ password field → {nm}")
            elif any(k in ph for k in ("ans", "captcha", "answer", "result", "sum", "calc")):
                # Solve the arithmetic captcha (e.g. "What is 4 + 7?")
                cap = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", form.get_text() or pg)
                if cap:
                    n1, op, n2 = int(cap.group(1)), cap.group(2), int(cap.group(3))
                    ans = n1 + n2 if op == "+" else (n1 - n2 if op == "-" else n1 * n2)
                    payload[nm] = str(ans)
                    logger.info(f"   ↳ captcha {n1}{op}{n2} = {ans}")
            else:
                payload[nm] = val

        # ── 3. Resolve the form action URL ────────────────────────────
        # MUST use urljoin so "signin" on page "/ints/login" becomes
        # "/ints/signin", NOT "/signin".
        # e.g.  urljoin("http://ip/ints/login", "signin")
        #       → "http://ip/ints/signin"   ✓
        raw_action = (form.get("action") or "").strip()
        if raw_action:
            if raw_action.startswith("http"):
                action = raw_action                         # already absolute
            else:
                # urljoin resolves relative to the current page directory
                from urllib.parse import urljoin
                action = urljoin(login_url, raw_action)
        else:
            action = login_url                              # no action = post to same URL

        origin = login_url.split("/ints/")[0] if "/ints/" in login_url else                  "/".join(login_url.split("/")[:3])

        logger.info(f"   ↗ POST {action}")
        async with s.post(
            action, data=payload,
            headers={"Referer": login_url, "Origin": origin},
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=True,
        ) as pr:
            final_url = str(pr.url)
            body      = await pr.text()
            body_l    = body.lower()
            logger.info(f"   ← HTTP {pr.status}  final URL → {final_url}")

            # ── 4. Detect success ─────────────────────────────────────
            #
            # IMPORTANT: All /ints/ panels POST to ints/signin (that is the
            # form action).  After a successful login they redirect to
            # ints/agent/SMSDashboard.  The old "still_auth" check wrongly
            # flagged Wolf and others because "signin" appeared in either the
            # form action URL or a redirect step, even though login succeeded.
            #
            # Rule: if the response body contains dashboard/logout keywords
            # → login succeeded, regardless of what the URL says.
            # Only fall back to URL inspection when the body is ambiguous.
            _OK_BODY = {
                "logout", "log out", "sign out", "signout",
                "dashboard", "smscdr", "sms log", "sms report",
                "smscdrstats", "welcome", "my account",
                "sms dashboard", "smsdashboard",
            }
            # A failed login usually returns a page with these keywords
            # AND has no dashboard content in the body.
            _FAIL_BODY = {"invalid", "incorrect", "wrong password",
                          "failed", "error", "invalid credentials"}
            _OK_URL    = {"dashboard", "smscdr", "smscdrstats",
                          "welcome", "inbox", "report", "home"}

            body_ok    = any(k in body_l for k in _OK_BODY)
            body_fail  = any(k in body_l for k in _FAIL_BODY)
            url_ok     = any(k in final_url.lower() for k in _OK_URL)

            # body_fail + no body_ok = definite failure
            # body_ok alone = definite success (URL doesn't matter)
            # neither: use URL as tiebreaker
            if body_fail and not body_ok:
                err_el = BeautifulSoup(body,"html.parser").find(
                    class_=re.compile(r"error|alert|danger|invalid", re.I))
                hint = err_el.get_text(strip=True)[:120] if err_el else body_l[:120]
                logger.warning(
                    f"   ✗ Login FAILED  panel=\"{panel.name}\"  hint=\"{hint}\""
                )
                panel.fail_count += 1
                return False

            if not body_ok and not url_ok:
                logger.warning(
                    f"   ✗ Login FAILED  panel=\"{panel.name}\"  "
                    f"(no success signal in body or URL)  final=\"{final_url[-60:]}\""
                )
                panel.fail_count += 1
                return False

            logger.info(f"   ✓ Authenticated  panel=\"{panel.name}\""
                        f"  (body_ok={body_ok} url_ok={url_ok})")

            # ── 5. Discover the SMS data endpoint ─────────────────────
            #
            # The screenshot showed the panel redirects to:
            #   http://ip/ints/agent/SMSDashboard
            # which means the stats page is at:
            #   http://ip/ints/agent/SMSCDRStats  (agent sub-dir)
            # NOT at:
            #   http://ip/ints/SMSCDRStats         (always 404)
            #
            # Strategy: extract the directory portion of final_url
            # and try it first.  Fall back to panel.base_url if that fails.
            from urllib.parse import urlparse as _up
            parsed_final = _up(final_url)
            # directory of the redirect URL, e.g. /ints/agent from /ints/agent/SMSDashboard
            path_parts       = parsed_final.path.rstrip("/").rsplit("/", 1)
            redirect_dir     = path_parts[0] if len(path_parts) > 1 else ""
            redirect_base    = f"{parsed_final.scheme}://{parsed_final.netloc}{redirect_dir}"
            # e.g. http://185.2.83.39/ints/agent

            # Try the redirect directory first, then panel.base_url as fallback
            candidate_bases = []
            if redirect_base and redirect_base != panel.base_url:
                candidate_bases.append(redirect_base)    # /ints/agent  ← correct for your panels
            candidate_bases.append(panel.base_url)       # /ints         ← fallback

            for disc_base in candidate_bases:
                for stats_path in ["/SMSCDRStats", "/client/SMSCDRStats",
                                   "/smscdrstats", "/sms/log", "/smslogs", "/sms"]:
                    try:
                        stats_url = disc_base + stats_path
                        logger.info(f"   🔍 Trying {stats_url}")
                        async with s.get(stats_url, timeout=aiohttp.ClientTimeout(total=10)) as sr:
                            if sr.status != 200:
                                logger.info(f"      → {sr.status} skip")
                                continue
                            page = await sr.text()
                            for sc in BeautifulSoup(page, "html.parser").find_all("script"):
                                if not sc.string:
                                    continue
                                m = re.search(
                                    r'sAjaxSource["\'\\s]*:\s*["\']([^"\']+)["\']',
                                    sc.string)
                                if m:
                                    found = m.group(1)
                                    if not found.startswith("http"):
                                        found = disc_base + "/" + found.lstrip("/")
                                    if "sesskey=" in found:
                                        parts         = found.split("?", 1)
                                        panel.api_url = parts[0]
                                        sk = re.search(r"sesskey=([^&]+)", parts[1])
                                        if sk: panel.sesskey = sk.group(1)
                                    else:
                                        panel.api_url = found
                                    panel.stats_url    = stats_url   # store for Referer
                                    panel.is_logged_in = True
                                    panel.fail_count   = 0
                                    logger.info(
                                        f"   📡 Endpoint found: {panel.api_url}"
                                        + (f"  sesskey={panel.sesskey[:12]}…" if panel.sesskey else ""))
                                    return True
                    except Exception as disc_err:
                        logger.info(f"   ↳ error checking {stats_url}: {disc_err}")

            # ── 6. Fallback: use redirect directory + conventional path ──
            # e.g. http://ip/ints/agent/res/data_smscdr.php
            best_base          = candidate_bases[0]   # prefer agent-dir if found
            panel.api_url      = f"{best_base}/res/data_smscdr.php"
            panel.stats_url    = f"{best_base}/SMSCDRStats"
            panel.is_logged_in = True
            panel.fail_count   = 0
            logger.info(f"   📡 Fallback endpoint: {panel.api_url}")
            return True

    except aiohttp.ClientConnectorError as e:
        logger.error(f"🔌 Cannot connect to panel \"{panel.name}\": {e}")
    except asyncio.TimeoutError:
        logger.error(f"⏱  Connection timeout  panel=\"{panel.name}\"")
    except Exception as e:
        logger.error(f"❌ Login error  panel=\"{panel.name}\": {e}", exc_info=True)

    panel.fail_count += 1
    return False


async def fetch_panel_sms(panel: PanelSession) -> Optional[list]:
    if panel.panel_type == "api_v2":
        return await fetch_reseller_api(panel)
    if panel.panel_type == "api":
        try:
            s=await panel.get_session(); now=datetime.now(); prev=now-timedelta(days=1)
            params={"token":panel.token,"dt1":prev.strftime("%Y-%m-%d %H:%M:%S"),
                    "dt2":now.strftime("%Y-%m-%d %H:%M:%S"),"records":API_MAX_RECORDS}
            async with s.get(panel.base_url,params=params,timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status!=200:
                    panel.fail_count+=1
                    if panel.fail_count>=3: panel.is_logged_in=False
                    return None
                try: data=await resp.json(content_type=None)
                except Exception as je:
                    logger.error(f"API JSON '{panel.name}': {je}")
                    panel.fail_count+=1
                    if panel.fail_count>=3: panel.is_logged_in=False
                    return None
                records=[]
                if isinstance(data,list): records=data
                elif isinstance(data,dict):
                    st=str(data.get("status","")).lower()
                    if st=="error":
                        logger.error(f"API '{panel.name}' auth: {data.get('msg','')}")
                        panel.fail_count+=1
                        if panel.fail_count>=3: panel.is_logged_in=False
                        return None
                    records=(data.get("data") or data.get("records") or
                             data.get("sms") or data.get("messages") or [])
                panel.fail_count=0; panel.is_logged_in=True
                if not records: return []
                out=[]
                for rec in records:
                    if not isinstance(rec,dict): continue
                    dt =(rec.get("dt")      or rec.get("date")      or rec.get("timestamp") or "")
                    num=(rec.get("num")     or rec.get("number")    or rec.get("recipient") or rec.get("phone") or "")
                    cli=(rec.get("cli")     or rec.get("sender")    or rec.get("originator")or rec.get("service") or "unknown")
                    msg=(rec.get("message") or rec.get("text")      or rec.get("body")      or rec.get("content") or "")
                    if not msg and not num: continue
                    out.append([str(dt),str(num).replace("+","").strip(),str(cli).lower(),str(msg)])
                out.sort(key=lambda x:x[0],reverse=True)
                return out
        except Exception as e:
            logger.error(f"API fetch '{panel.name}': {e}")
            panel.fail_count+=1
            if panel.fail_count>=3: panel.is_logged_in=False
            return None
    elif panel.panel_type=="login":
        if not panel.api_url: return None
        try:
            s=await panel.get_session(); now=datetime.now(); prev=now-timedelta(days=1)
            params={"fdate1":prev.strftime("%Y-%m-%d %H:%M:%S"),"fdate2":now.strftime("%Y-%m-%d %H:%M:%S"),
                    "sEcho":"1","iDisplayStart":"0","iDisplayLength":"200","iSortCol_0":"0","sSortDir_0":"desc"}
            if panel.sesskey: params["sesskey"]=panel.sesskey
            # Use the discovered stats page URL as Referer (server validates this)
            _referer = panel.stats_url or f"{panel.base_url}/SMSCDRStats"
            headers={"X-Requested-With":"XMLHttpRequest",
                     "Referer": _referer,
                     "Accept":"application/json, text/javascript, */*; q=0.01"}
            async with s.get(panel.api_url,params=params,headers=headers,
                             timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status!=200:
                    panel.fail_count+=1
                    if panel.fail_count>=3: panel.is_logged_in=False
                    return None
                data=await resp.json(content_type=None)
                if "aaData" in data:
                    panel.fail_count=0; data["aaData"].sort(key=lambda x:str(x[0]),reverse=True)
                    return data["aaData"]
                panel.fail_count+=1
                if panel.fail_count>=3: panel.is_logged_in=False
                return None
        except Exception as e:
            logger.error(f"Login fetch '{panel.name}': {e}")
            panel.fail_count+=1
            if panel.fail_count>=3: panel.is_logged_in=False
            return None
    return None

# ═══════════════════════════════════════════════════════
#  IVAS WORKER  (v2 — improved)
#  From reference implementation in main.py:
#  • seen set trims to last 500 when >1000 (no blind clear)
#  • check_counter % 100 for periodic panel-removal check
#  • Proper ping task lifecycle with CancelledError handling
#  • OSError separate from WebSocketException for network faults
# ═══════════════════════════════════════════════════════
async def _ivas_ping(ws, interval_ms: int):
    while True:
        await asyncio.sleep(interval_ms / 1000)
        try:
            await ws.send("3")
        except Exception:
            break

async def ivas_worker(panel: PanelSession):
    logger.info(f"📡 IVAS worker starting → \"{panel.name}\"")
    seen: set = set()
    while True:
        try:
            if panel.panel_type != "ivas" or not panel.uri:
                logger.info(f"IVAS \"{panel.name}\" — no URI or wrong type, stopping.")
                break
            ssl_ctx = ssl._create_unverified_context()
            try:
                async with websockets.connect(panel.uri, ssl=ssl_ctx) as ws:
                    logger.info(f"✅ IVAS \"{panel.name}\" connected")
                    initial = await ws.recv()
                    ping_iv = 25000
                    try:
                        if initial.startswith("0{"):
                            ping_iv = json.loads(initial[1:]).get("pingInterval", 25000)
                    except Exception:
                        pass
                    await ws.send("40/livesms,")
                    ping_task = asyncio.create_task(_ivas_ping(ws, ping_iv))
                    try:
                        counter = 0
                        while True:
                            counter += 1
                            # Periodic check every 100 messages: panel still in DB?
                            if counter % 100 == 0:
                                ids = [p.id for p in PANELS]
                                if panel.id is not None and panel.id not in ids:
                                    logger.info(f"IVAS \"{panel.name}\" removed — stopping.")
                                    break
                            raw = await ws.recv()
                            if not raw.startswith("42/livesms,"):
                                continue
                            try:
                                d = json.loads(raw[raw.find("["):])
                                if not (isinstance(d, list) and len(d) > 1
                                        and isinstance(d[1], dict)):
                                    continue
                                sms     = d[1]
                                number  = str(sms.get("recipient", "")).replace("+", "").strip()
                                body    = str(sms.get("message", "") or "")
                                service = str(sms.get("originator", "") or "unknown")
                                otp     = extract_otp_regex(body)
                                uniq    = f"{number}-{body[:20]}"
                                if uniq in seen:
                                    continue
                                seen.add(uniq)
                                # Trim to last 500 entries when over 1000 — never blind clear
                                if len(seen) > 1000:
                                    seen = set(list(seen)[-500:])
                                logger.info(
                                    f"📨 IVAS \"{panel.name}\" …{number[-5:]} "
                                    f"svc={service[:10]} otp={otp or '—'}")
                                await process_incoming_sms(
                                    None, number, body, otp, service, panel.name)
                            except Exception as e:
                                logger.error(f"IVAS \"{panel.name}\" parse: {e}")
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass
            except websockets.exceptions.WebSocketException as e:
                logger.error(f"IVAS WS \"{panel.name}\": {e}. Retry 5s…")
                await asyncio.sleep(5)
            except OSError as e:
                logger.error(f"IVAS network \"{panel.name}\": {e}. Retry 10s…")
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"IVAS \"{panel.name}\": {e}. Retry 5s…")
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"IVAS \"{panel.name}\" critical: {e}. Retry 10s…")
            await asyncio.sleep(10)

def handle_task_exception(task: asyncio.Task):
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Task '{task.get_name()}': {e}", exc_info=True)

async def start_ivas_workers():
    for panel in PANELS:
        if panel.panel_type == "ivas":
            task = asyncio.create_task(ivas_worker(panel), name=f"IVAS-{panel.name}")
            task.add_done_callback(handle_task_exception)
            IVAS_TASKS[panel.name] = task
            logger.info(f"📡 IVAS task created for \"{panel.name}\"")

# forward_otp_to_main — REMOVED.
# Each bot (main and child) sends OTPs ONLY to its own configured log_chats.
# Main bot OTPs never go to child groups; child bot OTPs never go to main groups.
# The isolation is guaranteed by each bot having its own separate database
# with its own log_chats table.

async def process_incoming_sms(bot_app,num_raw:str,msg_body:str,
                                otp_code:Optional[str],service_name:str,panel_name:str):
    global app
    if bot_app is None: bot_app=app
    if otp_code and num_raw:
        append_otp(num_raw, otp_code)
    # ROUTING: each bot (main or child) sends ONLY to its own groups.
    # No cross-forwarding. Child bot OTPs stay in child groups.
    # Main bot OTPs stay in main groups.
    async with db.AsyncSessionLocal() as session:
        db_obj=(await session.execute(
            select(db.Number).where(db.Number.phone_number==num_raw)
        )).scalar_one_or_none()
        if db_obj and db_obj.assigned_to and db_obj.status in ("ASSIGNED","RETENTION"):
            await do_sms_hit(bot_app,db_obj,otp_code,msg_body,service_name,panel_name,num_raw,session)
        else:
            await log_unassigned(bot_app,num_raw,msg_body,otp_code,service_name,panel_name)

async def do_sms_hit(bot_app,db_obj,otp_code,msg_body,service_name,panel_name,num_raw,session):
    global app
    if bot_app is None: bot_app=app
    if bot_app is None: return
    db_obj.last_msg=msg_body
    if otp_code: db_obj.last_otp=otp_code
    cnt=OTP_SESSION_COUNTS.get(num_raw,0)
    if otp_code: cnt+=1; OTP_SESSION_COUNTS[num_raw]=cnt
    header={1:"✅ OTP RECEIVED",2:"🫟 2nd OTP",3:"🫂 3rd OTP"}.get(
        cnt,f"☠️ {cnt}th OTP" if cnt>3 else "📩 NEW MESSAGE")
    clean=re.sub(r"[^0-9]","",otp_code) if otp_code else ""
    kb=otp_keyboard(otp_code,msg_body)
    _,flag,region=get_country_info(num_raw)
    dial=get_country_code(num_raw) or ""; last5=get_last5(num_raw)
    svc=get_service_short(service_name)
    now_ts      = datetime.now().strftime("%H:%M:%S")
    count_badge = {1:"1️⃣ First OTP", 2:"2️⃣ Second OTP", 3:"3️⃣ Third OTP"}.get(
        cnt, f"🔢 OTP #{cnt}" if cnt > 0 else "📩 New SMS")

    # Use the selected OTP GUI theme (build_otp_msg dispatches by OTP_GUI_THEME)
    dm_txt  = build_otp_msg(header, count_badge, clean, msg_body,
                             svc, panel_name, flag, region, dial, last5,
                             for_group=False)
    grp_txt = build_otp_msg(header, count_badge, clean, msg_body,
                             svc, panel_name, flag, region, dial, last5,
                             for_group=True)

    dm_kb  = otp_keyboard(otp_code, msg_body, for_group=False)
    grp_kb = otp_keyboard(otp_code, msg_body, for_group=True)

    # ── DM to assigned user ───────────────────────────────
    if db_obj.assigned_to:
        try:
            await bot_app.bot.send_message(
                chat_id=db_obj.assigned_to, text=dm_txt,
                reply_markup=dm_kb, parse_mode="HTML")
        except TelegramForbidden:
            logger.warning(f"User {db_obj.assigned_to} blocked bot.")
        except Exception as e:
            logger.error(f"DM error ({db_obj.assigned_to}): {e}")

    # ── Log groups — compact reference format + 15-min auto-delete ──
    _DEL_SEC = 900   # 15 minutes
    for gid in await db.get_all_log_chats():
        try:
            sent = await bot_app.bot.send_message(
                chat_id=gid, text=grp_txt,
                reply_markup=grp_kb, parse_mode="HTML")
            # Schedule deletion
            if bot_app.job_queue:
                bot_app.job_queue.run_once(
                    _delete_msg_job, when=_DEL_SEC,
                    data={"chat_id": gid, "msg_id": sent.message_id},
                    name=f"del_{gid}_{sent.message_id}")
            else:
                asyncio.create_task(
                    _delete_msg_after(bot_app, gid, sent.message_id, _DEL_SEC))
        except TelegramForbidden:
            logger.error(f"Not in log group {gid}")
        except Exception as e:
            logger.error(f"Log group ({gid}): {e}")
    # ── Record & reassign ─────────────────────────────────
    if otp_code:
        await session.commit()
        cat,user_id,msg_id=await db.record_success(num_raw,otp_code)
        if user_id is None: return
        limit=await db.get_user_limit(user_id) or DEFAULT_ASSIGN_LIMIT
        await db.request_numbers(user_id,cat,count=limit,message_id=msg_id)
        active=await db.get_active_numbers(user_id)
        if active and msg_id:
            try:
                pfx=await db.get_user_prefix(user_id)
                pfx_txt=f"on-{pfx}" if pfx else "off"
                svc_lbl=(active[0].category.split(" - ")[1]
                         if " - " in active[0].category else active[0].category)
                lines=[]
                for idx,n in enumerate(active,1):
                    e=f"{idx}\uFE0F\u20E3" if idx<10 else ("🔟" if idx==10 else f"[{idx}]")
                    lines.append(f"{e} <code>+{n.phone_number}</code>")
                await bot_app.bot.edit_message_text(
                    chat_id=user_id,message_id=msg_id,
                    text=(f"🎉 <b>New Numbers Ready!</b>\n{D}\n"
                          f"🌍 <b>Service:</b> {html.escape(svc_lbl)}\n"
                          +"\n".join(lines)+
                          f"\n\n🔡 <b>Prefix:</b> {pfx_txt}\n⚡ <b>Waiting for SMS…</b>"),
                    reply_markup=waiting_kb(pfx,service=svc_lbl),parse_mode="HTML")
            except Exception as e: logger.error(f"Edit msg: {e}")
    else:
        session.add(db_obj); await session.commit()

async def log_unassigned(bot_app,num_raw,msg_body,otp_code,service_name,panel_name):
    global app
    if bot_app is None: bot_app=app
    if bot_app is None: return
    log_chats=await db.get_all_log_chats()
    if not log_chats: return
    _,flag,region=get_country_info(num_raw)
    dial=get_country_code(num_raw) or ""; last5=get_last5(num_raw)
    svc=get_service_short(service_name)
    clean=re.sub(r"[^0-9]","",otp_code) if otp_code else ""
    # Unassigned OTPs use "📩 UNASSIGNED" as the header in the current theme
    _ua_header = "📩 UNASSIGNED"
    _ua_badge  = ""
    txt = build_otp_msg(_ua_header, _ua_badge, clean, msg_body,
                        svc, panel_name, flag, region, dial, last5,
                        for_group=True)
    kb = otp_keyboard(otp_code, msg_body, for_group=True)
    _DEL_SEC2 = 900
    for gid in log_chats:
        try:
            sent = await bot_app.bot.send_message(chat_id=gid,text=txt,reply_markup=kb,parse_mode="HTML")
            if bot_app.job_queue:
                bot_app.job_queue.run_once(
                    _delete_msg_job, when=_DEL_SEC2,
                    data={"chat_id": gid, "msg_id": sent.message_id},
                    name=f"del_{gid}_{sent.message_id}")
            else:
                asyncio.create_task(_delete_msg_after(bot_app, gid, sent.message_id, _DEL_SEC2))
        except TelegramForbidden: logger.error(f"Not in log group {gid}")
        except Exception as e: logger.error(f"Log ({gid}): {e}")


# ═══════════════════════════════════════════════════════════
#  AUTO-DELETE HELPERS  (group messages removed after 15 min)
# ═══════════════════════════════════════════════════════════
async def _delete_msg_after(bot_app, chat_id: int, msg_id: int, delay_sec: int):
    """Coroutine: waits delay_sec then silently deletes the message."""
    await asyncio.sleep(delay_sec)
    try:
        await bot_app.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        logger.info(f"🗑️  Auto-deleted group msg {msg_id} from {chat_id}")
    except Exception:
        pass   # already deleted or bot lacks permission — ignore

async def _delete_msg_job(context):
    """PTB job_queue callback for auto-delete."""
    d = context.job.data or {}
    try:
        await context.bot.delete_message(
            chat_id=d["chat_id"], message_id=d["msg_id"])
        logger.info(f"🗑️  Auto-deleted group msg {d['msg_id']} from {d['chat_id']}")
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════
#  ACTIVE WATCHER
# ═══════════════════════════════════════════════════════════
async def active_watcher(application):
    global app, PROCESSED_MESSAGES
    app = application
    logger.info(f"🚀 Active watcher started  ({len(PANELS)} panel(s) loaded)")

    # ── Initial login pass ────────────────────────────────────────
    # IMPORTANT: panels sharing the same base_url (same server, multiple
    # accounts) MUST login sequentially with a small gap.  Concurrent logins
    # on the same server cause the server to invalidate the earlier session
    # the moment the second one completes, leaving only one account active.
    # We group by base_url and login each group one account at a time.
    from collections import defaultdict as _dd
    login_groups = _dd(list)
    api_panels   = []
    for panel in PANELS:
        if panel.panel_type == "login":
            login_groups[panel.base_url].append(panel)
        elif panel.panel_type == "api":
            api_panels.append(panel)

    # Login panels — sequentially within each host group
    for host, group in login_groups.items():
        if len(group) > 1:
            logger.info(f"🔑 Logging in {len(group)} accounts on {host} (sequential to avoid session clash)")
        for panel in group:
            logger.info(f"🔑 Initial login → \"{panel.name}\"")
            ok = await login_to_panel(panel)
            if ok:
                if panel.id: await update_panel_login(panel.id, panel.sesskey, panel.api_url, True)
                logger.info(f"✅ \"{panel.name}\" ready  →  {panel.api_url}")
            else:
                logger.warning(f"⚠️  \"{panel.name}\" login failed, will retry each cycle")
            if len(group) > 1:
                await asyncio.sleep(1.5)  # give the server time between accounts

    # Initialise API panel sessions (no login needed, just a session object)
    for panel in api_panels:
        await panel.get_session()
        logger.info(f"🔌 API panel \"{panel.name}\" session ready")
    for gid in await db.get_all_log_chats():
        try: await application.bot.send_message(gid,"🚀 <b>OTP Engine Online</b>",parse_mode="HTML")
        except Exception: pass
    first_cycle = True
    while True:
        t0 = datetime.now()
        try:
            try: await db.clean_cooldowns()
            except Exception: pass
            async with db.AsyncSessionLocal() as session:
                from sqlalchemy import or_
                active_nums=(await session.execute(
                    select(db.Number).filter(
                        or_(db.Number.status=="ASSIGNED",db.Number.status=="RETENTION"))
                )).scalars().all()
                targets={n.phone_number:n for n in active_nums}

                async def fetch_one(panel):
                    try:
                        # ── Login / reconnect if needed ──────────────────────
                        if not panel.is_logged_in:
                            if panel.panel_type == "login":
                                logger.info(f"🔄 Re-logging in to \"{panel.name}\"…")
                                ok = await login_to_panel(panel)
                                if ok:
                                    await update_panel_login(
                                        panel.id or 0, panel.sesskey, panel.api_url, True)
                                    logger.info(f"✅ \"{panel.name}\" logged in, fetching SMS")
                                else:
                                    logger.warning(f"⏸  \"{panel.name}\" login failed, skipping cycle")
                                    return None, panel
                            elif panel.panel_type == "api":
                                ok = await test_api_panel(panel)
                                panel.is_logged_in = ok
                                if not ok:
                                    logger.warning(f"⏸  API \"{panel.name}\" unreachable, skipping cycle")
                                    return None, panel
                        # ── Fetch SMS ─────────────────────────────────────────
                        sms_list = await fetch_panel_sms(panel)
                        if sms_list is not None:
                            logger.info(
                                f"📥 \"{panel.name}\" → {len(sms_list)} record(s) fetched")
                        return sms_list, panel
                    except Exception as e:
                        logger.error(f"❌ Watcher error on \"{panel.name}\": {e}", exc_info=True)
                    return None, panel

                # Run panels sequentially to avoid same-host session collisions.
                # asyncio.gather ran them all at once; for panels sharing a host
                # this caused the second login to invalidate the first mid-fetch.
                results = []
                for p in PANELS:
                    if p.panel_type not in ("ivas",):
                        results.append(await fetch_one(p))
                for sms_list,panel in results:
                    if not sms_list: continue
                    for rec in sms_list:
                        if len(rec)<4: continue
                        if panel.panel_type=="api":
                            dt_str=str(rec[0]); num_raw=str(rec[1]).replace("+","").strip()
                            svc_raw=str(rec[2]); msg_body=str(rec[3])
                        else:
                            dt_str=str(rec[0])
                            num_raw=str(rec[2]).replace("+","").strip() if len(rec)>2 else ""
                            svc_raw=str(rec[3]) if len(rec)>3 else "unknown"
                            msg_body=get_message_body(rec) or ""
                        if not msg_body or not num_raw: continue
                        msg_time=parse_panel_dt(dt_str)
                        if msg_time is None: continue
                        if (datetime.now()-msg_time).total_seconds()/60>MSG_AGE_LIMIT_MIN: continue
                        otp_code=extract_otp_regex(msg_body)
                        uid_str=hashlib.md5(f"{panel.base_url}-{dt_str}-{num_raw}-{msg_body}".encode()).hexdigest()
                        if uid_str in PROCESSED_MESSAGES: continue
                        PROCESSED_MESSAGES.add(uid_str); save_seen_hash(uid_str)
                        if first_cycle: continue
                        if num_raw in targets:
                            db_obj=targets[num_raw]
                            if db_obj.last_msg==msg_body: continue
                            await do_sms_hit(application,db_obj,otp_code,msg_body,svc_raw,panel.name,num_raw,session)
                        else:
                            await log_unassigned(application,num_raw,msg_body,otp_code,svc_raw,panel.name)
                first_cycle=False
        except Exception as e:
            logger.error(f"Watcher loop: {e}"); await asyncio.sleep(5)
        await asyncio.sleep(API_FETCH_INTERVAL)

# ═══════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = html.escape(update.effective_user.first_name)
    await db.add_user(uid)
    # ── Membership gate ──────────────────────────────────────────
    missing = await check_membership(context.bot, uid)
    if missing:
        await send_join_required(update, context.bot, uid, missing)
        return
    bot_name = f"@{BOT_USERNAME}" if BOT_USERNAME else "@CrackSMSReBot"
    perms = await get_admin_permissions(uid)
    role_line = ""
    if is_super_admin(uid): role_line = "\n👑 <b>Super Admin</b>"
    elif perms:             role_line = "\n👮 <b>Admin</b>"
    msg = (
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"💎 <b>Crack SMS V11</b>  |  🤖 {html.escape(bot_name)}\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"👋 Welcome, <a href='tg://user?id={uid}'><b>{name}</b></a>!{role_line}\n\n"
        "⚡ Real-Time OTP Delivery\n"
        "🧬 Multi-Panel + IVAS Support\n"
        "🔑 Auto-Assign Number System\n"
        "🚀 Get Numbers for Any Service\n\n"
        "👇 <b>Choose an option:</b>"
    )
    await update.message.reply_text(msg, reply_markup=main_menu_kb(), parse_mode="HTML")

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    perms= await get_admin_permissions(uid)
    sup  = is_super_admin(uid)
    if not perms and not sup:
        await update.message.reply_text(
            "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            "🚫 <b>Access Denied</b>\n"
            "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            "You are not authorised to access the admin panel.",
            parse_mode="HTML"); return
    role      = "👑 Super Admin" if sup else "👮 Admin"
    stats     = await db.get_stats()
    panel_cnt = len(PANELS)
    run_cnt   = len([p for p in PANELS if p.is_logged_in or
                     (p.panel_type=="ivas" and p.name in IVAS_TASKS
                      and not IVAS_TASKS[p.name].done())])
    # Build lines list — avoids f-string concatenation which caused the crash
    lines = [
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>",
        "🛡 <b>SIGMA ADMIN PANEL</b>",
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>",
        "",
        f"👤 {role}  |  🆔 <code>{uid}</code>",
        "",
        f"📱 Available:   <b>{stats.get('available',0)}</b>",
        f"🔌 Panels:      <b>{run_cnt}/{panel_cnt}</b> online",
    ]
    if not IS_CHILD_BOT:
        bot_cnt = len(bm.list_bots())
        lines.append(f"🤖 Child Bots:  <b>{bot_cnt}</b>")
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=admin_main_kb(perms, sup), parse_mode="HTML")

async def cmd_add_admin(u,c): await u.message.reply_text("Use Admin Panel → Admins.")
async def cmd_rm_admin(u,c):  await u.message.reply_text("Use Admin Panel → Admins.")
async def cmd_list_admins(u,c):
    admins=await list_all_admins()
    lines="\n".join(f"• <code>{a}</code>{'  👑' if a in INITIAL_ADMIN_IDS else ''}" for a in admins)
    await u.message.reply_text(f"👮 <b>Admins</b>\n\n{lines or 'None'}",parse_mode="HTML")

async def cmd_add_log(update,context):
    uid=update.effective_user.id; perms=await get_admin_permissions(uid)
    if "manage_logs" not in perms and not is_super_admin(uid):
        await update.message.reply_text("❌ No permission."); return
    if not context.args: await update.message.reply_text("Usage: /addlogchat <chat_id>"); return
    try:
        cid=int(context.args[0]); ok=await db.add_log_chat(cid)
        await update.message.reply_text(f"{'✅ Added' if ok else '⚠️ Exists'}: <code>{cid}</code>",parse_mode="HTML")
    except ValueError: await update.message.reply_text("❌ Invalid chat ID.")

async def cmd_rm_log(update,context):
    uid=update.effective_user.id; perms=await get_admin_permissions(uid)
    if "manage_logs" not in perms and not is_super_admin(uid):
        await update.message.reply_text("❌ No permission."); return
    if not context.args: await update.message.reply_text("Usage: /removelogchat <chat_id>"); return
    try:
        cid=int(context.args[0]); ok=await db.remove_log_chat(cid)
        await update.message.reply_text(f"{'✅ Removed' if ok else '❌ Not found'}: <code>{cid}</code>",parse_mode="HTML")
    except ValueError: await update.message.reply_text("❌ Invalid chat ID.")

async def cmd_list_logs(update,context):
    uid=update.effective_user.id; perms=await get_admin_permissions(uid)
    if "manage_logs" not in perms and not is_super_admin(uid):
        await update.message.reply_text("❌ No permission."); return
    chats=await db.get_all_log_chats()
    txt="📋 <b>Log Groups</b>\n\n"+"\n".join(f"• <code>{c}</code>" for c in chats) if chats else "📭 None."
    await update.message.reply_text(txt,parse_mode="HTML")

async def cmd_dox(update,context):
    uid=update.effective_user.id
    if uid not in INITIAL_ADMIN_IDS: await update.message.reply_text("❌ Unauthorized."); return
    if len(context.args)<2: await update.message.reply_text("Usage: /dox <amount> <on/off>"); return
    try:
        lim=int(context.args[0]); st=context.args[1].lower()
        if st=="on":  await db.set_user_limit(uid,lim);  await update.message.reply_text(f"✅ Limit→{lim}")
        elif st=="off": await db.set_user_limit(uid,None); await update.message.reply_text("✅ Dox OFF")
        else: await update.message.reply_text("Usage: /dox <amount> <on/off>")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def cmd_otpfor(update,context):
    if not context.args: await update.message.reply_text("Usage: /otpfor <phone>"); return
    target=context.args[0].replace("+","").strip()
    found=next((otp for num,otp in load_otp_store().items() if target in num),None)
    if found:
        await update.message.reply_text(
            f"🔑 OTP for <code>{target}</code>: <b>{found}</b>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"📋 Copy OTP: {found}", copy_text=CopyTextButton(text=found))]]),
            parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ No OTP for <code>{target}</code>.",parse_mode="HTML")

async def cmd_set_channel(update,context):
    uid=update.effective_user.id
    if not is_super_admin(uid): await update.message.reply_text("❌ Unauthorized."); return
    if not context.args: await update.message.reply_text("Usage: /set_channel <url>"); return
    global CHANNEL_LINK; CHANNEL_LINK=context.args[0]
    save_config_key("CHANNEL_LINK",CHANNEL_LINK)
    await update.message.reply_text(f"✅ Channel → {CHANNEL_LINK}")

async def cmd_set_otpgroup(update,context):
    uid=update.effective_user.id
    if not is_super_admin(uid): await update.message.reply_text("❌ Unauthorized."); return
    if not context.args: await update.message.reply_text("Usage: /set_otpgroup <url>"); return
    global OTP_GROUP_LINK; OTP_GROUP_LINK=context.args[0]
    save_config_key("OTP_GROUP_LINK",OTP_GROUP_LINK)
    await update.message.reply_text(f"✅ OTP Group → {OTP_GROUP_LINK}")

async def cmd_set_numbot(update,context):
    uid=update.effective_user.id
    if not is_super_admin(uid): await update.message.reply_text("❌ Unauthorized."); return
    if not context.args: await update.message.reply_text("Usage: /set_numberbot <url>"); return
    global NUMBER_BOT_LINK; NUMBER_BOT_LINK=context.args[0]
    save_config_key("NUMBER_BOT_LINK",NUMBER_BOT_LINK)
    await update.message.reply_text(f"✅ Number Bot → {NUMBER_BOT_LINK}")

async def cmd_groups(u,c): await cmd_list_logs(u,c)
async def cmd_addgrp(u,c): await cmd_add_log(u,c)
async def cmd_rmgrp(u,c):  await cmd_rm_log(u,c)

async def cmd_bots(update,context):
    uid=update.effective_user.id
    if not is_super_admin(uid): await update.message.reply_text("❌ Super admin only."); return
    if IS_CHILD_BOT: await update.message.reply_text("ℹ️ Not available on child bots."); return
    bots=bm.list_bots()
    if not bots: await update.message.reply_text("🤖 No bots registered yet."); return
    lines=[f"{'🟢' if b.get('running') else '🔴'} <b>{html.escape(b['name'])}</b>  <code>{b['id']}</code>" for b in bots]
    await update.message.reply_text(f"🖥 <b>Child Bots ({len(bots)})</b>\n\n"+"\n".join(lines),
                                    reply_markup=bots_list_kb(bots),parse_mode="HTML")

async def cmd_startbot(u,c):
    uid=u.effective_user.id
    if not is_super_admin(uid): await u.message.reply_text("❌ Unauthorized."); return
    if not c.args: await u.message.reply_text("Usage: /startbot <id>"); return
    ok,msg=bm.start_bot(c.args[0]); await u.message.reply_text(f"{'✅' if ok else '❌'} {msg}")

async def cmd_stopbot(u,c):
    uid=u.effective_user.id
    if not is_super_admin(uid): await u.message.reply_text("❌ Unauthorized."); return
    if not c.args: await u.message.reply_text("Usage: /stopbot <id>"); return
    ok,msg=bm.stop_bot(c.args[0]); await u.message.reply_text(f"{'✅' if ok else '❌'} {msg}")

async def cmd_test1(update,context):
    uid=update.effective_user.id
    try:
        num=random.choice(TEST_NUMBERS); cat="🇺🇸 USA - TestService"
        await db.release_number(uid)
        async with db.AsyncSessionLocal() as session:
            obj=(await session.execute(select(db.Number).where(db.Number.phone_number==num))).scalar_one_or_none()
            if not obj: obj=db.Number(phone_number=num,category=cat,status="AVAILABLE"); session.add(obj)
            obj.status="ASSIGNED"; obj.assigned_to=uid; obj.assigned_at=datetime.now()
            obj.category=cat; obj.last_msg=None; obj.last_otp=None
            await session.commit()
        pfx=await db.get_user_prefix(uid)
        msg=await context.bot.send_message(chat_id=uid,
            text=f"🎉 <b>Test Number</b>\n{D}\n📱 <code>+{num}</code>\n\nUse /send1 to simulate OTP.",
            reply_markup=waiting_kb(pfx),parse_mode="HTML")
        await db.update_message_id(num,msg.message_id)
    except Exception as e: await update.message.reply_text(f"❌ /test1: {e}")

async def cmd_send1(update,context):
    uid=update.effective_user.id
    async with db.AsyncSessionLocal() as session:
        obj=(await session.execute(
            select(db.Number).where(db.Number.assigned_to==uid,db.Number.status=="ASSIGNED")
        )).scalars().first()
        if not obj: await update.message.reply_text("❌ No active number. Use /test1."); return
        otp=str(random.randint(100000,999999))
        await do_sms_hit(context.application,obj,otp,f"Telegram code: {otp}. Do not share.",
                         "TELEGRAM","TEST-PANEL",obj.phone_number,session)
        await update.message.reply_text(f"✅ Simulated OTP <b>{otp}</b>",parse_mode="HTML")


# ═══════════════════════════════════════════════════════════
#  DOCUMENT UPLOAD
# ═══════════════════════════════════════════════════════════
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; perms=await get_admin_permissions(uid)
    if "manage_files" not in perms and not is_super_admin(uid):
        await update.message.reply_text("❌ No permission."); return
    doc=update.message.document
    if not doc or not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ Send a <code>.txt</code> file.",parse_mode="HTML"); return
    f=await doc.get_file(); path=doc.file_name
    await f.download_to_drive(path)
    try:
        lines=[l.strip() for l in open(path).readlines() if l.strip()]
        if not lines: await update.message.reply_text("❌ File empty."); os.remove(path); return
        country,flag=detect_country_from_numbers(lines)
        context.user_data.update({"upload_path":path,"upload_country":country,
                                   "upload_flag":flag,"upload_count":len(lines),"upload_svcs":[]})
        await update.message.reply_text(
            f"📂 <b>File Received</b>\n{D}\n🔢 <b>{len(lines)}</b> numbers\n"
            f"🌍 Detected: {flag} <b>{country}</b>\n\nSelect services:",
            reply_markup=svc_sel_kb(),parse_mode="HTML")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

# ═══════════════════════════════════════════════════════════
#  TEXT INPUT HANDLER
# ═══════════════════════════════════════════════════════════
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    user_text=update.message.text
    if user_text: user_text = user_text.strip()
    else: user_text = ""
    # Membership gate
    if not is_super_admin(uid):
        perms = await get_admin_permissions(uid)
        if not perms:
            missing = await check_membership(context.bot, uid)
            if missing:
                await send_join_required(update, context.bot, uid, missing)
                return

    # ── Panel Edit Flow ──────────────────────────────────
    if uid in PANEL_EDIT_STATES:
        st=PANEL_EDIT_STATES[uid]; step=st["step"]; d=st["data"]; pid=st["panel_id"]
        if user_text=="/cancel": del PANEL_EDIT_STATES[uid]; await update.message.reply_text("❌ Cancelled."); return
        if step=="name": d["name"]=user_text; st["step"]="url"; await update.message.reply_text(f"URL now: {d['base_url']}\nNew URL (/skip):")
        elif step=="url":
            if user_text.lower()!="/skip": d["base_url"]=user_text
            if d["panel_type"]=="login": st["step"]="username"; await update.message.reply_text(f"User: {d['username']}\nNew (/skip):")
            elif d["panel_type"]=="api": st["step"]="token"; await update.message.reply_text("New token (/skip):")
            else: st["step"]="uri"; await update.message.reply_text("New URI (/skip):")
        elif step=="username":
            if user_text.lower()!="/skip": d["username"]=user_text
            st["step"]="password"; await update.message.reply_text("New password (/skip):")
        elif step=="password":
            if user_text.lower()!="/skip": d["password"]=user_text
            await update_panel_in_db(pid,d["name"],d["base_url"],d.get("username"),d.get("password"),d["panel_type"],d.get("token"),d.get("uri"))
            await refresh_panels_from_db(); del PANEL_EDIT_STATES[uid]; await update.message.reply_text("✅ Panel updated!")
        elif step=="token":
            if user_text.lower()!="/skip": d["token"]=user_text
            await update_panel_in_db(pid,d["name"],d["base_url"],None,None,d["panel_type"],d.get("token"),None)
            await refresh_panels_from_db(); del PANEL_EDIT_STATES[uid]; await update.message.reply_text("✅ API panel updated!")
        elif step=="uri":
            if user_text.lower()!="/skip": d["uri"]=user_text
            await update_panel_in_db(pid,d["name"],d["base_url"],None,None,d["panel_type"],None,d.get("uri"))
            await refresh_panels_from_db(); del PANEL_EDIT_STATES[uid]; await update.message.reply_text("✅ IVAS panel updated!")
        return

    # ── Panel Add Flow ───────────────────────────────────
    if uid in PANEL_ADD_STATES:
        st=PANEL_ADD_STATES[uid]; step=st["step"]; d=st["data"]
        if user_text=="/cancel": del PANEL_ADD_STATES[uid]; await update.message.reply_text("❌ Cancelled."); return
        if step=="name": d["name"]=user_text; st["step"]="type"; await update.message.reply_text("Select panel type:",reply_markup=ptype_kb())
        elif step=="url":
            d["base_url"]=user_text
            pt=d["panel_type"]
            if pt=="login": st["step"]="username"; await update.message.reply_text("Enter username:")
            elif pt=="api": st["step"]="token"; await update.message.reply_text("Enter API token:")
            else: st["step"]="uri"; await update.message.reply_text("Paste IVAS URI (wss://...):")
        elif step=="username": d["username"]=user_text; st["step"]="password"; await update.message.reply_text("Enter password:")
        elif step=="password":
            await add_panel_to_db(d["name"],d["base_url"],d["username"],user_text,"login")
            await refresh_panels_from_db(); del PANEL_ADD_STATES[uid]; await update.message.reply_text("✅ Login panel added!")
        elif step=="token":
            await add_panel_to_db(d["name"],d["base_url"],None,None,"api",token=user_text.strip())
            await refresh_panels_from_db(); del PANEL_ADD_STATES[uid]; await update.message.reply_text("✅ API panel added!")
        elif step=="uri":
            await add_panel_to_db(d["name"],d.get("base_url",""),None,None,"ivas",uri=user_text.strip())
            await refresh_panels_from_db()
            panel=next((p for p in PANELS if p.name==d["name"]),None)
            if panel:
                task=asyncio.create_task(ivas_worker(panel),name=f"IVAS-{d['name']}")
                task.add_done_callback(handle_task_exception); IVAS_TASKS[d["name"]]=task
            del PANEL_ADD_STATES[uid]; await update.message.reply_text("✅ IVAS panel added and worker started!")
        return

    # ── Add Admin ID ─────────────────────────────────────
    # ── Create Bot text flow ──────────────────────────────────────
    if uid in CREATE_BOT_STATES:
        state = CREATE_BOT_STATES[uid]
        step  = state.get("step","")

        if step == "get_group_id":
            # User sends their group chat ID
            group_id_str = user_text.strip().replace(" ", "")
            if not group_id_str.lstrip("-").isdigit():
                await update.message.reply_text(
                    "❌ Invalid group ID. It should be a number like <code>-1001234567890</code>\n"
                    "Send /cancel to abort.", parse_mode="HTML"); return
            state["group_id"] = group_id_str
            state["step"]     = "await_verify"
            await update.message.reply_text(
                f"📋 Group ID received: <code>{group_id_str}</code>\n\n"
                f"Now tap <b>Verify</b> to confirm I am admin in your group.\n"
                f"Make sure @{BOT_USERNAME} is an admin first!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "✅  Verify Admin Status",
                        callback_data=f"cbot_verify_{group_id_str}"),
                    InlineKeyboardButton("❌  Cancel", callback_data="cancel_action"),
                ]]), parse_mode="HTML")
            return

        if step == "get_bot_name":
            state["bot_name"] = user_text.strip()
            state["step"]     = "get_token"
            await update.message.reply_text(
                "🤖 <b>Step 2/9 — Bot Token</b>\n\n"
                "Send your <b>Bot Token</b> from @BotFather\n"
                "<i>Format: 1234567890:AAXXXXXXXX</i>\n\n"
                "Type <b>skip</b> if you want us to create the bot for you.",
                parse_mode="HTML"); return

        if step == "get_token":
            if user_text.lower() == "skip":
                state["token"] = None
            else:
                state["token"] = user_text.strip()
            state["step"] = "get_username"
            await update.message.reply_text(
                "🤖 <b>Step 3/9 — Bot Username</b>\n\n"
                "Send the bot <b>@username</b> (e.g. @MyOTPBot):", parse_mode="HTML"); return

        if step == "get_username":
            state["bot_username"] = user_text.strip().lstrip("@")
            state["step"]         = "get_admin_id"
            await update.message.reply_text(
                "🤖 <b>Step 4/9 — Admin User ID</b>\n\n"
                "Send your Telegram <b>numeric User ID</b>:", parse_mode="HTML"); return

        if step == "get_admin_id":
            try: state["admin_id"] = int(user_text.strip())
            except ValueError:
                await update.message.reply_text("❌ Must be a number. Try again."); return
            state["step"] = "get_channel"
            await update.message.reply_text(
                "🤖 <b>Step 5/9 — Channel Link</b>\n\n"
                "Send your <b>channel link</b> or type <b>none</b>:", parse_mode="HTML"); return

        if step == "get_channel":
            state["channel"] = None if user_text.lower()=="none" else user_text.strip()
            state["step"] = "get_otp_group"
            await update.message.reply_text(
                "🤖 <b>Step 6/9 — OTP Group Link</b>\n\nSend your OTP group link:", parse_mode="HTML"); return

        if step == "get_otp_group":
            state["otp_group"] = user_text.strip()
            state["step"]      = "get_number_bot"
            await update.message.reply_text(
                "🤖 <b>Step 7/9 — Number Bot Link</b>\n\nLink where users get numbers:", parse_mode="HTML"); return

        if step == "get_number_bot":
            state["number_bot"] = user_text.strip()
            state["step"]       = "get_support"
            await update.message.reply_text(
                "🤖 <b>Step 8/9 — Support Username</b>\n\nYour support @username:", parse_mode="HTML"); return

        if step == "get_support":
            state["support"] = user_text.strip()
            state["step"]    = "get_group_id_panel"
            await update.message.reply_text(
                "🤖 <b>Step 9/9 — Group Chat ID</b>\n\n"
                "Send the chat ID of your OTP group (e.g. <code>-1001234567890</code>):",
                parse_mode="HTML"); return

        if step == "get_group_id_panel":
            group_id_str = user_text.strip()
            if not group_id_str.lstrip("-").isdigit():
                await update.message.reply_text("❌ Invalid ID. Must be numeric."); return
            state["group_id"] = group_id_str
            state["step"]     = "submitting"

            # Build summary and send request to super admins
            req_id = f"bot_{uid}_{int(datetime.now().timestamp())}"
            BOT_REQUESTS[req_id] = {**state, "status": "pending", "req_id": req_id,
                                     "user_name": update.effective_user.first_name,
                                     "username": f"@{update.effective_user.username}" if update.effective_user.username else str(uid)}
            summary = (
                f"🆕 <b>Bot Creation Request</b>\n\n"
                f"👤 From: {html.escape(update.effective_user.first_name)} (<code>{uid}</code>)\n"
                f"🤖 Bot Name: {html.escape(state.get('bot_name','?'))}\n"
                f"🔑 Token: <code>{'provided' if state.get('token') else 'needs creation'}</code>\n"
                f"👥 Admin ID: <code>{state.get('admin_id','?')}</code>\n"
                f"📱 Group: <code>{group_id_str}</code>\n"
                f"📢 Channel: {state.get('channel','—')}\n"
                f"💬 OTP Group: {state.get('otp_group','—')}")
            for admin_id in INITIAL_ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id, text=summary,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("✅  Approve", callback_data=f"approvebot_{req_id}"),
                            InlineKeyboardButton("❌  Reject",  callback_data=f"rejectbot_{req_id}"),
                        ]]), parse_mode="HTML")
                except Exception: pass
            del CREATE_BOT_STATES[uid]
            await update.message.reply_text(
                "✅ <b>Request Submitted!</b>\n\n"
                "Admins will review your request. You'll be notified on approval.\n\n"
                f"📋 Request ID: <code>{req_id}</code>\n\n"
                "For support contact @NONEXPERTCODER",
                parse_mode="HTML")
            return

    # ── Add required chat ────────────────────────────────────────
    if AWAITING_REQ_CHAT.get(uid):
        AWAITING_REQ_CHAT.pop(uid, None)
        if not is_super_admin(uid):
            await update.message.reply_text("❌ Unauthorized."); return
        parts = [p.strip() for p in user_text.replace("|", "||").split("||") if p.strip()]
        if len(parts) < 3:
            # Try space-separated format: -1001234 Title https://t.me/link
            parts2 = user_text.strip().split(None, 2)
            if len(parts2) == 3:
                parts = parts2
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Invalid format. Use:\n"
                "<code>CHAT_ID | Title | https://t.me/link</code>", parse_mode="HTML"); return
        try:
            chat_id = int(parts[0].strip())
        except ValueError:
            await update.message.reply_text("❌ Chat ID must be a number."); return
        title = parts[1].strip()
        link  = parts[2].strip() if len(parts) > 2 else f"https://t.me/c/{str(chat_id)[4:]}"
        new_chat = {"id": chat_id, "title": title, "link": link}
        REQUIRED_CHATS.append(new_chat)
        save_config_key("REQUIRED_CHATS", REQUIRED_CHATS)
        await update.message.reply_text(
            f"✅ Added required chat:\n"
            f"• <b>{html.escape(title)}</b>  (<code>{chat_id}</code>)\n"
            f"• Link: {html.escape(link)}",
            parse_mode="HTML")
        return

    if AWAITING_SUPER_ADMIN.get(uid):
        AWAITING_SUPER_ADMIN.pop(uid, None)
        if not is_super_admin(uid):
            await update.message.reply_text("❌ Unauthorized."); return
        try: new_sid = int(user_text.strip())
        except ValueError:
            await update.message.reply_text("❌ Invalid ID — must be a number."); return
        if new_sid in INITIAL_ADMIN_IDS:
            await update.message.reply_text(f"ℹ️ <code>{new_sid}</code> is already a super admin.",parse_mode="HTML"); return
        INITIAL_ADMIN_IDS.append(new_sid)
        await set_admin_permissions(new_sid, list(PERMISSIONS.keys()))
        save_config_key("ADMIN_IDS", INITIAL_ADMIN_IDS)
        await update.message.reply_text(
            f"✅ <b>Super Admin Added</b>\n\n👑 <code>{new_sid}</code> is now a super admin.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back",callback_data="admin_manage_admins")]]),
            parse_mode="HTML")
        return

    if uid in AWAITING_ADMIN_ID:
        if not is_super_admin(uid): del AWAITING_ADMIN_ID[uid]; await update.message.reply_text("❌ Unauthorized."); return
        del AWAITING_ADMIN_ID[uid]
        try:
            new_a=int(user_text.strip())
            if new_a in INITIAL_ADMIN_IDS: await update.message.reply_text("❌ Already super admin."); return
            AWAITING_PERMISSIONS[(uid,new_a)]=[]
            await update.message.reply_text(
                f"✅ User <code>{new_a}</code>. Select permissions:",
                reply_markup=perms_kb([],new_a),parse_mode="HTML")
        except ValueError: await update.message.reply_text("❌ Invalid user ID.")
        return

    # ── Add Log Group ID ─────────────────────────────────
    if uid in AWAITING_LOG_ID:
        perms=await get_admin_permissions(uid)
        if "manage_logs" not in perms and not is_super_admin(uid):
            del AWAITING_LOG_ID[uid]; await update.message.reply_text("❌ Unauthorized."); return
        del AWAITING_LOG_ID[uid]
        try:
            cid=int(user_text.strip()); ok=await db.add_log_chat(cid)
            await update.message.reply_text(
                f"{'✅ Added' if ok else '⚠️ Exists'}: <code>{cid}</code>",parse_mode="HTML")
        except ValueError: await update.message.reply_text("❌ Invalid chat ID.")
        return

    # ── Config Link Prompts ──────────────────────────────
    if context.user_data.get("awaiting_link"):
        link_key=context.user_data.pop("awaiting_link")
        global CHANNEL_LINK, OTP_GROUP_LINK, NUMBER_BOT_LINK, SUPPORT_USER
        val=user_text.strip()
        if link_key=="CHANNEL_LINK":    CHANNEL_LINK=val
        elif link_key=="OTP_GROUP_LINK": OTP_GROUP_LINK=val
        elif link_key=="NUMBER_BOT_LINK": NUMBER_BOT_LINK=val
        elif link_key=="SUPPORT_USER":   SUPPORT_USER=val
        elif link_key=="DEVELOPER":      DEVELOPER=val
        save_config_key(link_key,val)
        if link_key == "FIND_OTP":
            target = val.replace("+","").strip()
            found_otp = next((otp for num,otp in load_otp_store().items() if target in num), None)
            if found_otp:
                await update.message.reply_text(
                    f"🔑 OTP for <code>{target}</code>\n\n"
                    f"<code>{found_otp}</code>",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(f"📋 Copy: {found_otp}",
                                             copy_text=CopyTextButton(text=found_otp)),
                        InlineKeyboardButton("🔙 Back",callback_data="admin_otp_tools")]]),
                    parse_mode="HTML")
            else:
                await update.message.reply_text(
                    f"❌ No OTP found for <code>{target}</code>.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back",callback_data="admin_otp_tools")]]),
                    parse_mode="HTML")
            return
        label={"CHANNEL_LINK":"Channel","OTP_GROUP_LINK":"OTP Group",
               "NUMBER_BOT_LINK":"Number Bot","SUPPORT_USER":"Support",
               "DEVELOPER":"Developer"}.get(link_key,link_key)
        await update.message.reply_text(
            f"✅ {label} updated to:\n<code>{html.escape(val)}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_links")]]))
        return

    # ── Prefix Setting ───────────────────────────────────
    if context.user_data.get("awaiting_prefix"):
        cat=context.user_data.pop("prefix_cat",None)
        context.user_data["awaiting_prefix"]=False
        if user_text.lower()=="off":
            await db.set_user_prefix(uid,None); await update.message.reply_text("✅ Prefix disabled.")
        else:
            cnt=await db.check_prefix_availability(cat,user_text)
            if cnt>0:
                await db.set_user_prefix(uid,user_text)
                await update.message.reply_text(
                    f"✅ Prefix <code>{user_text}</code> set. {cnt} numbers match.",parse_mode="HTML")
                await db.release_number(uid)
                limit=await db.get_user_limit(uid) or DEFAULT_ASSIGN_LIMIT
                phones,_,_=await db.request_numbers(uid,cat,count=limit)
                if phones:
                    active=await db.get_active_numbers(uid)
                    svc=(active[0].category.split(" - ")[1] if active and " - " in active[0].category else cat)
                    lines=[f"{i+1}. <code>+{n.phone_number}</code>" for i,n in enumerate(active)]
                    msg=await context.bot.send_message(chat_id=uid,
                        text=f"🎉 <b>New Numbers</b>\n{D}\n"+"\n".join(lines)+"\n\n⚡ Waiting…",
                        reply_markup=waiting_kb(user_text,service=svc),parse_mode="HTML")
                    for n in active: await db.update_message_id(n.phone_number,msg.message_id)
            else:
                await update.message.reply_text(f"❌ No numbers with prefix <code>{user_text}</code>.",parse_mode="HTML")
        return

    # ── Child Bot Link Edit Flow ─────────────────────────
    if context.user_data.get("bot_setlink_bid") and not IS_CHILD_BOT:
        bid  = context.user_data.pop("bot_setlink_bid", None)
        key  = context.user_data.pop("bot_setlink_key", None)
        if not is_super_admin(uid):
            await update.message.reply_text("❌ Unauthorized."); return
        if user_text == "/cancel":
            await update.message.reply_text("❌ Cancelled."); return
        val = user_text.strip()
        # Update the registry entry
        reg = bm.load_registry()
        key_map = {
            "CHANNEL_LINK":    "channel_link",
            "OTP_GROUP_LINK":  "otp_group_link",
            "NUMBER_BOT_LINK": "number_bot_link",
            "SUPPORT_USER":    "support_user",
        }
        reg_key = key_map.get(key, key.lower())
        if bid and bid in reg:
            reg[bid][reg_key] = val
            bm.save_registry(reg)
            # Also update the config.json inside the child folder
            try:
                folder = reg[bid].get("folder", "")
                cfg_path = os.path.join(folder, "config.json")
                if os.path.exists(cfg_path):
                    with open(cfg_path) as f: child_cfg = json.load(f)
                    child_cfg[key] = val
                    with open(cfg_path, "w") as f: json.dump(child_cfg, f, indent=2)
            except Exception as e:
                logger.error(f"Child config update: {e}")
        label_map = {"CHANNEL_LINK":"Channel","OTP_GROUP_LINK":"OTP Group","NUMBER_BOT_LINK":"Number Bot","SUPPORT_USER":"Support"}
        await update.message.reply_text(
            f"✅ <b>{label_map.get(key,key)}</b> updated for bot <code>{bid}</code>\n"
            f"New value: <code>{html.escape(val)}</code>\n\n"
            "<i>Restart the child bot to apply changes.</i>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Bot", callback_data=f"bot_info_{bid}")]]),
            parse_mode="HTML")
        return

    # ── Multi-Bot Add Flow ───────────────────────────────
    if uid in BOT_ADD_STATES and not IS_CHILD_BOT:
        st=BOT_ADD_STATES[uid]; step=st["step"]; d=st["data"]
        if user_text=="/cancel": del BOT_ADD_STATES[uid]; await update.message.reply_text("❌ Bot creation cancelled."); return
        steps={
            "name":        ("token",       "🔑 Now send the <b>Bot Token</b>\n<i>Get from @BotFather → /newbot</i>"),
            "token":       ("username",    "🤖 Send the <b>Bot Username</b> (e.g. @MyOTPBot)\n<i>No need for @ symbol</i>"),
            "username":    ("admin_id",    "👤 Send the <b>Admin Telegram ID</b>\n<i>Numeric ID — use @userinfobot</i>"),
            "admin_id":    ("channel",     "📢 Send the <b>Channel Link</b> (https://t.me/...)\nor /skip to leave blank"),
            "channel":     ("otp_group",   "💬 Send the <b>OTP Group Link</b> (https://t.me/...)\nor /skip to leave blank"),
            "otp_group":   ("numbot",      "📞 Send the <b>Number Bot Link</b> (https://t.me/...)\nor /skip to leave blank"),
            "numbot":      ("support",     "🛟 Send the <b>Support Username</b> (e.g. @support)\nor /skip to leave blank"),
            "support":     ("developer",   "🧠 Send the <b>Developer Username</b> (e.g. @dev)\nor /skip to leave blank"),
            "developer":   (None,          ""),
        }
        if step=="token":
            if not re.match(r'^\d+:[A-Za-z0-9_-]{35,}$',user_text.strip()):
                await update.message.reply_text(
                    "❌ Invalid token format.\nExpected: <code>123456:ABCxyz...</code>\nTry again or /cancel.",
                    parse_mode="HTML"); return
        if step=="admin_id":
            try: d["admin_ids"]=[int(user_text.strip())]
            except ValueError: await update.message.reply_text("❌ Must be a numeric ID."); return
        elif step not in ("admin_id",):
            val="" if user_text.strip()=="/skip" else user_text.strip()
            d[step]=val

        nxt,prompt=steps.get(step,(None,""))
        if nxt:
            st["step"]=nxt
            await update.message.reply_text(prompt,parse_mode="HTML")
        else:
            # All steps done — create the bot
            await update.message.reply_text("⏳ Creating bot folder and files…")
            bot_id=str(uuid.uuid4())[:8]
            ok,folder,err=bm.create_bot_folder(
                bot_id=bot_id, name=d.get("name",""),
                token=d.get("token",""), bot_username=d.get("username",""),
                admin_ids=d.get("admin_ids",[uid]),
                channel_link=d.get("channel",""), otp_group_link=d.get("otp_group",""),
                number_bot_link=d.get("numbot",""), support_user=d.get("support","@ownersigma"),
                developer=d.get("developer","@NONEXPERTCODER"),
                get_number_url=d.get("numbot","https://t.me/PakOTPBOT"))
            del BOT_ADD_STATES[uid]
            if ok:
                start_ok,start_msg=bm.start_bot(bot_id)
                st_icon="🟢" if start_ok else "🔴"
                await update.message.reply_text(
                    f"✅ <b>Bot Created Successfully!</b>\n{D}\n"
                    f"🤖 <b>Name:</b>     {html.escape(d.get('name',''))}\n"
                    f"👤 <b>Username:</b> @{html.escape(d.get('username',''))}\n"
                    f"🆔 <b>Bot ID:</b>   <code>{bot_id}</code>\n"
                    f"📁 <b>Folder:</b>   <code>{html.escape(folder)}</code>\n"
                    f"📢 <b>Channel:</b>  {html.escape(d.get('channel','—') or '—')}\n"
                    f"💬 <b>OTP Group:</b>{html.escape(d.get('otp_group','—') or '—')}\n"
                    f"{st_icon} <b>Status:</b>  {start_msg}\n\n"
                    f"<i>The bot runs independently with its own database.</i>",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🖥  Manage Bots",callback_data="admin_bots")
                    ]]),parse_mode="HTML")
            else:
                await update.message.reply_text(f"❌ Failed: {err}")
        return

    # ── Broadcast Flow ───────────────────────────────────
    if context.user_data.get("awaiting_broadcast"):
        perms=await get_admin_permissions(uid)
        if "broadcast" not in perms and not is_super_admin(uid):
            context.user_data["awaiting_broadcast"]=False; await update.message.reply_text("❌ Unauthorized."); return
        context.user_data["awaiting_broadcast"]=False
        bcast_text=user_text
        all_users=await db.get_all_users()
        total=len(all_users); sent=0; failed=0
        sm=await context.bot.send_message(
            chat_id=uid,
            text=f"📢 <b>Broadcasting to {total} users…</b>\n\n{pbar(0,max(total,1))}\nStarting…",
            parse_mode="HTML")
        for target in all_users:
            try:
                await context.bot.send_message(chat_id=target,
                    text=f"📢 <b>Announcement</b>\n{D}\n{bcast_text}",parse_mode="HTML")
                sent+=1
            except TelegramForbidden: failed+=1
            except Exception: failed+=1
            if (sent+failed)%10==0 or (sent+failed)==total:
                try:
                    await sm.edit_text(
                        f"📢 Broadcasting…\n\n{pbar(sent+failed,max(total,1))}\n✅{sent} ❌{failed}",
                        parse_mode="HTML")
                except Exception: pass
            await asyncio.sleep(0.04)
        try:
            await sm.edit_text(
                f"✅ <b>Broadcast Done</b>\n\n{pbar(total,max(total,1))}\n✅{sent} ❌{failed}",
                parse_mode="HTML")
        except Exception: pass
        await context.bot.send_message(uid,"Done.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_home")]]))
        return

    # ── Broadcast to ALL bots users (master + all child bots) ──
    if context.user_data.get("bcast_all_bots") and not IS_CHILD_BOT:
        context.user_data.pop("bcast_all_bots", None)
        perms_check = await get_admin_permissions(uid)
        if not is_super_admin(uid):
            await update.message.reply_text("❌ Unauthorized."); return
        bcast_text = user_text
        # Collect all users from this master bot
        master_users = await db.get_all_users()
        # Collect users from each child bot's database
        all_targets = list(master_users)
        child_dbs_users = []
        bots_reg = bm.load_registry()
        for bid, info in bots_reg.items():
            folder = info.get("folder","")
            child_db = os.path.join(folder, "bot_database.db")
            if os.path.exists(child_db):
                try:
                    import sqlite3 as _sq
                    conn = _sq.connect(child_db)
                    rows = conn.execute("SELECT user_id FROM users").fetchall()
                    conn.close()
                    child_dbs_users.extend([r[0] for r in rows])
                except Exception: pass
        # Deduplicate
        all_targets = list(set(all_targets + child_dbs_users))
        total = len(all_targets); sent = 0; failed = 0
        sm = await context.bot.send_message(
            chat_id=uid,
            text=f"📢 <b>Broadcasting to ALL bots: {total} users…</b>",
            parse_mode="HTML")
        for target in all_targets:
            try:
                await context.bot.send_message(
                    chat_id=target,
                    text=f"📢 <b>Announcement</b>\n{D}\n{bcast_text}",
                    parse_mode="HTML")
                sent += 1
            except (TelegramForbidden, Exception): failed += 1
            if (sent+failed) % 20 == 0:
                try:
                    await sm.edit_text(
                        f"📢 Broadcasting all bots…\n{pbar(sent+failed,max(total,1))}\n✅{sent} ❌{failed}",
                        parse_mode="HTML")
                except Exception: pass
            await asyncio.sleep(0.04)
        try:
            await sm.edit_text(
                f"✅ <b>All-Bots Broadcast Done</b>\n{pbar(total,max(total,1))}\n"
                f"✅ Sent: {sent}  ❌ Failed: {failed}\n"
                f"📊 Total unique users: {total}",
                parse_mode="HTML")
        except Exception: pass
        return

    await update.message.reply_text("Use /start to see the menu.")


# ═══════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DEFAULT_ASSIGN_LIMIT, CHANNEL_LINK, OTP_GROUP_LINK, NUMBER_BOT_LINK, SUPPORT_USER
    global OTP_GUI_THEME, GUI_STYLE
    query=update.callback_query; data=query.data; uid=query.from_user.id

    if data=="ignore": await query.answer(); return

    # ── Membership re-check ───────────────────────────────────────
    if data=="check_membership":
        await query.answer("⏳ Checking…")
        missing = await check_membership(context.bot, uid)
        if missing:
            await send_join_required(query, context.bot, uid, missing)
        else:
            # All joined — show the welcome screen
            name     = html.escape(update.effective_user.first_name)
            bot_name = f"@{BOT_USERNAME}" if BOT_USERNAME else "@CrackSMSReBot"
            perms    = await get_admin_permissions(uid)
            role_line = ""
            if is_super_admin(uid): role_line = "\n👑 <b>Super Admin</b>"
            elif perms:             role_line = "\n👮 <b>Admin</b>"
            await query.edit_message_text(
                "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
                f"💎 <b>Crack SMS V11</b>  |  🤖 {html.escape(bot_name)}\n"
                "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
                f"✅ Verified! Welcome, <a href=\'tg://user?id={uid}\'><b>{name}</b></a>!{role_line}\n\n"
                "⚡ Real-Time OTP Delivery\n"
                "🧬 Multi-Panel + IVAS Support\n"
                "🔑 Auto-Assign Number System\n"
                "🚀 Get Numbers for Any Service\n\n"
                "👇 <b>Choose an option:</b>",
                reply_markup=main_menu_kb(), parse_mode="HTML")
        return

    if data=="main_menu":
        await query.answer()
        await query.edit_message_text("🏠 <b>Main Menu</b>",reply_markup=main_menu_kb(),parse_mode="HTML")
        return

    if data=="profile":
        await query.answer()
        stats=await db.get_user_stats(uid)
        active=await db.get_active_numbers(uid)
        perms=await get_admin_permissions(uid)
        role="👑 Super Admin" if is_super_admin(uid) else ("👮 Admin" if perms else "👤 User")
        ai=""
        if active: ai="\n📱 "+", ".join(f"<code>+{n.phone_number}</code>" for n in active)
        await query.edit_message_text(
            f"🫁 <b>USER PROFILE</b>\n{D}\n"
            f"🆔 <code>{uid}</code>\n👤 {html.escape(query.from_user.first_name)}\n"
            f"🎭 {role}\n{D}\n"
            f"✅ OTPs: <b>{stats['success']}</b>\n"
            f"🔄 Total: <b>{stats['total']}</b>{ai}",
            reply_markup=main_menu_kb(),parse_mode="HTML")
        return

    if data=="buy_menu":
        await query.answer()
        svcs=await db.get_distinct_services()
        if not svcs:
            await query.edit_message_text(
                "🚫 <b>No Services Available</b>\nAsk admin to upload numbers.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="main_menu")]]),
                parse_mode="HTML")
        else:
            await query.edit_message_text(
                f"📱 <b>Select Service</b>\n{D}",reply_markup=services_kb(svcs),parse_mode="HTML")
        return

    if data.startswith("svc_"):
        svc=data[4:]; await query.answer()
        countries=await db.get_countries_for_service(svc)
        if not countries:
            await query.edit_message_text(f"🚫 No countries for <b>{svc}</b>.",
                reply_markup=services_kb(await db.get_distinct_services()),parse_mode="HTML")
        else:
            await query.edit_message_text(f"🌍 <b>Select Country</b> — {svc}\n{D}",
                reply_markup=countries_kb(svc,countries),parse_mode="HTML")
        return

    if data.startswith("cntry|"):
        _,svc,country=data.split("|",2); await query.answer()
        await db.set_user_prefix(uid,None)
        clist=await db.get_countries_for_service(svc)
        flag=next((f for f,c in clist if c==country),"🌍")
        category=f"{flag} {country} - {svc}"
        limit=await db.get_user_limit(uid) or DEFAULT_ASSIGN_LIMIT
        active=await db.get_active_numbers(uid)
        if active and active[0].category!=category: await db.release_number(uid); active=[]
        if len(active)<limit:
            await db.request_numbers(uid,category,count=limit-len(active))
            active=await db.get_active_numbers(uid)
        if active:
            try: await query.message.delete()
            except Exception: pass
            pfx=await db.get_user_prefix(uid)
            lines=[f"{i+1}\uFE0F\u20E3 <code>+{n.phone_number}</code>" for i,n in enumerate(active)]
            msg=await context.bot.send_message(chat_id=uid,
                text=(f"🎉 <b>Numbers Assigned!</b>\n{D}\n"
                      f"🌍 <b>Service:</b> {svc} {flag}\n\n"+"\n".join(lines)+
                      "\n\n⚡ <b>Waiting for SMS…</b>"),
                reply_markup=waiting_kb(pfx,service=svc),parse_mode="HTML")
            for n in active: await db.update_message_id(n.phone_number,msg.message_id)
        else:
            await context.bot.send_message(uid,f"❌ <b>Out of Stock</b> — {svc} / {country}",parse_mode="HTML")
        return

    if data=="change_country":
        active=await db.get_active_numbers(uid)
        if not active: await query.answer("No active number.",show_alert=True); return
        svc=active[0].category.split(" - ")[1] if " - " in active[0].category else active[0].category
        countries=await db.get_countries_for_service(svc)
        if not countries: await query.answer("No other countries.",show_alert=True); return
        await query.answer()
        await query.edit_message_text(f"🌍 <b>Select Country</b> — {svc}",
            reply_markup=countries_kb(svc,countries),parse_mode="HTML")
        return

    if data=="skip_next":
        now_=datetime.now(); last=LAST_CHANGE_TIME.get(uid)
        if last and (now_-last).total_seconds()<CHANGE_COOLDOWN_S:
            await query.answer(f"⏳ Wait {CHANGE_COOLDOWN_S-int((now_-last).total_seconds())}s",show_alert=True); return
        LAST_CHANGE_TIME[uid]=now_; await query.answer()
        ok,cat=await db.release_number(uid)
        if ok and cat:
            limit=await db.get_user_limit(uid) or DEFAULT_ASSIGN_LIMIT
            await db.request_numbers(uid,cat,count=limit)
            active=await db.get_active_numbers(uid)
            if active:
                try: await query.message.delete()
                except Exception: pass
                svc=active[0].category.split(" - ")[1] if " - " in active[0].category else cat
                pfx=await db.get_user_prefix(uid)
                lines=[f"{i+1}. <code>+{n.phone_number}</code>" for i,n in enumerate(active)]
                msg=await context.bot.send_message(chat_id=uid,
                    text=f"🔄 <b>New Numbers</b>\n{D}\n"+"\n".join(lines)+"\n\n⚡ Waiting…",
                    reply_markup=waiting_kb(pfx,service=svc),parse_mode="HTML")
                for n in active: await db.update_message_id(n.phone_number,msg.message_id)
            else:
                await query.edit_message_text("❌ Out of stock.",reply_markup=main_menu_kb(),parse_mode="HTML")
        else: await query.answer("No active number.",show_alert=True)
        return

    if data=="ask_block":
        await query.answer()
        await query.edit_message_text(
            f"⚠️ <b>Block This Number?</b>\n{D}\nPermanently removed — no one can use it again.",
            reply_markup=confirm_block_kb(),parse_mode="HTML")
        return

    if data=="block_no":
        await query.answer()
        active=await db.get_active_numbers(uid)
        if active:
            pfx=await db.get_user_prefix(uid)
            svc=active[0].category.split(" - ")[1] if " - " in active[0].category else active[0].category
            lines=[f"{i+1}. <code>+{n.phone_number}</code>" for i,n in enumerate(active)]
            await query.edit_message_text("✅ Kept.\n\n"+"\n".join(lines)+"\n\n⚡ Waiting…",
                reply_markup=waiting_kb(pfx,service=svc),parse_mode="HTML")
        else:
            await query.edit_message_text("No active number.",reply_markup=main_menu_kb(),parse_mode="HTML")
        return

    if data=="block_yes":
        await query.answer(); await query.edit_message_text("⏳ Blocking…")
        ok,cat=await db.block_number(uid)
        if ok and cat:
            svc=cat.split(" - ")[1] if " - " in cat else cat
            cntrs=await db.get_countries_for_service(svc)
            if cntrs:
                await query.edit_message_text(f"✅ Blocked. Select new country for {svc}:",
                    reply_markup=countries_kb(svc,cntrs),parse_mode="HTML")
            else:
                await query.edit_message_text("✅ Blocked.",
                    reply_markup=services_kb(await db.get_distinct_services()),parse_mode="HTML")
        else:
            await query.edit_message_text("❌ No active number.",reply_markup=main_menu_kb(),parse_mode="HTML")
        return

    if data=="set_prefix":
        await query.answer()
        active=await db.get_active_numbers(uid)
        if not active: await query.answer("No active number.",show_alert=True); return
        cur=await db.get_user_prefix(uid)
        if cur:
            await db.set_user_prefix(uid,None); await query.answer("Prefix disabled.")
            svc=active[0].category.split(" - ")[1] if " - " in active[0].category else active[0].category
            lines=[f"{i+1}. <code>+{n.phone_number}</code>" for i,n in enumerate(active)]
            await query.edit_message_text("⚡ Waiting…\n\n"+"\n".join(lines),
                reply_markup=waiting_kb(None,service=svc),parse_mode="HTML")
        else:
            context.user_data["awaiting_prefix"]=True
            context.user_data["prefix_cat"]=active[0].category
            svc=active[0].category.split(" - ")[1] if " - " in active[0].category else active[0].category
            await context.bot.send_message(uid,
                f"🔡 <b>Set Prefix</b>\n{D}\nService: {svc}\n\n"
                "Type prefix (e.g. <code>9198</code>) or <code>off</code>:",parse_mode="HTML")
        return

    # ── Upload service selection ─────────────────────────
    if data.startswith("us_"):
        action=data[3:]
        if action=="done":
            await query.answer()
            sel=context.user_data.get("upload_svcs",[])
            path=context.user_data.get("upload_path")
            country=context.user_data.get("upload_country","Unknown")
            flag=context.user_data.get("upload_flag","🌍")
            if not sel: await query.answer("Select at least one service.",show_alert=True); return
            if not path or not os.path.exists(path): await query.edit_message_text("❌ File lost. Re-upload."); return
            lines=[l.strip() for l in open(path).readlines() if l.strip()]
            total_added=0
            for svc in sel:
                cat=f"{flag} {country} - {svc}"
                total_added+=await db.add_numbers_bulk(lines,cat)
            os.remove(path); context.user_data.pop("upload_path",None)

            # ── Total stock after upload ──────────────────────────────
            total_stock = 0
            for svc in sel:
                cat = f"{flag} {country} - {svc}"
                total_stock += await db.count_available(cat)

            await query.edit_message_text(
                f"✅ <b>Upload Complete</b>\n{D}\n📥 Added: <b>{total_added}</b>\n"
                f"📱 Services: {', '.join(sel)}\n🌍 {flag} {country}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_files")]]),
                parse_mode="HTML")

            # ── Auto-broadcast (only if enabled in settings) ─────────
            if not AUTO_BROADCAST_ON:
                return
            nb_url  = NUMBER_BOT_LINK or GET_NUMBER_URL or f"https://t.me/{BOT_USERNAME}"
            svc_str = "  ".join(sel)
            bcast_msg = (
                f"🔔 <b>New Numbers Added!</b>\n"
                f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
                f"🌍 <b>Country:</b> {flag} {country}\n"
                f"🔧 <b>Services:</b> {svc_str}\n"
                f"📞 <b>Fresh Numbers:</b> {total_added:,}\n"
                f"📦 <b>Total Stock:</b> {total_stock:,}\n"
                f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
                f"🚀 Start the bot and tap <b>Get Number</b> now!"
            )
            bcast_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🧇  Get Number", url=nb_url)]])

            # Send to log groups
            for gid in await db.get_all_log_chats():
                try:
                    await context.bot.send_message(
                        chat_id=gid, text=bcast_msg,
                        reply_markup=bcast_kb, parse_mode="HTML")
                except Exception: pass

            # Send to all registered users (background task)
            async def _bcast_users():
                users = await db.get_all_users()
                sent = 0
                for u_id in users:
                    try:
                        await context.bot.send_message(
                            chat_id=u_id, text=bcast_msg,
                            reply_markup=bcast_kb, parse_mode="HTML")
                        sent += 1
                    except Exception: pass
                    await asyncio.sleep(0.05)  # 20/sec flood-safe
                logger.info(f"📢 Auto-broadcast sent to {sent}/{len(users)} users")
            asyncio.create_task(_bcast_users())
        elif action=="cancel":
            await query.answer()
            path=context.user_data.pop("upload_path",None)
            if path and os.path.exists(path): os.remove(path)
            await query.edit_message_text("❌ Upload cancelled.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_home")]]))
        else:
            sel=context.user_data.get("upload_svcs",[])
            if action in sel: sel.remove(action)
            else: sel.append(action)
            context.user_data["upload_svcs"]=sel
            await query.edit_message_reply_markup(reply_markup=svc_sel_kb(sel)); await query.answer()
        return

    # ── ADMIN SECTION ─────────────────────────────────────
    perms=await get_admin_permissions(uid); is_sup=is_super_admin(uid)

    if data=="admin_home":
        await query.answer()
        context.user_data["awaiting_broadcast"]=False
        role="👑 Super Admin" if is_sup else "👮 Admin"
        s2=await db.get_stats(); avail=s2.get("available",0)
        online=len([p for p in PANELS if p.is_logged_in or
                    (p.panel_type=="ivas" and p.name in IVAS_TASKS
                     and not IVAS_TASKS[p.name].done())])
        await query.edit_message_text(
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"🛡 <b>SIGMA ADMIN PANEL</b>  ·  {role}\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"📱 {avail} numbers  🔌 {online}/{len(PANELS)} panels",
            reply_markup=admin_main_kb(perms,is_sup),parse_mode="HTML")
        return

    # ── OTP Tools submenu ──────────────────────────────────────────
    if data=="admin_otp_tools":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        store=load_otp_store()
        await query.edit_message_text(
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"🔑 <b>OTP Tools</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"Store entries: <b>{len(store)}</b>",
            reply_markup=admin_otp_tools_kb(),parse_mode="HTML")
        return

    # ── Notify / Broadcast menu ────────────────────────────────────
    if data=="admin_notify_menu":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        chats=await db.get_all_log_chats()
        users=await db.get_all_users()
        await query.edit_message_text(
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"🔔 <b>Notify &amp; Broadcast</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"👤 Users: <b>{len(users)}</b>   📋 Log groups: <b>{len(chats)}</b>",
            reply_markup=admin_notify_kb(),parse_mode="HTML")
        return

    if data=="ping_log_groups":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        chats=await db.get_all_log_chats()
        ok=0; fail=0
        for gid in chats:
            try:
                await context.bot.send_message(gid,"📡 <b>Sigma Fetcher — Panel Online ✅</b>",parse_mode="HTML")
                ok+=1
            except Exception: fail+=1
        await query.answer(f"✅ Pinged {ok} groups, ❌ {fail} failed",show_alert=True)
        return

    if data=="send_test_otp":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        fake_otp=str(random.randint(100000,999999))
        await query.answer()
        bot_tag=f"@{BOT_USERNAME}" if BOT_USERNAME else "@CrackSMSReBot"
        now_ts=datetime.now().strftime("%H:%M:%S")
        test_txt=(
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"  ✅ OTP RECEIVED  ·  1️⃣ First OTP\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"🤖 <b>{html.escape(bot_tag)}</b>   ⏰ <code>{now_ts}</code>\n\n"
            f"┌─────────────────────────┐\n"
            f"│  🔑  <b>OTP CODE</b>\n"
            f"│  <code>{fake_otp}</code>\n"
            f"└─────────────────────────┘\n\n"
            f"📱  <code>+92-𝗦𝗜𝗚𝗠𝗔-12345</code>   🇵🇰 #PK\n"
            f"📡  <b>Service:</b> #TG\n"
            f"🔌  <b>Panel:</b>   TEST\n\n"
            f"💬  <i>Your Telegram code: {fake_otp}. Do not share.</i>"
        )
        kb=otp_keyboard(fake_otp,"Your Telegram code: "+fake_otp,for_group=False)
        await context.bot.send_message(uid,test_txt,reply_markup=kb,parse_mode="HTML")
        await query.edit_message_text("✅ Test OTP sent to your DM.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_notify_menu")]]))
        return

    if data=="find_otp_prompt":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        context.user_data["awaiting_link"]="FIND_OTP"
        await query.answer()
        await query.edit_message_text(
            "🔍 <b>Find OTP by Number</b>\n\nSend the phone number to search:",
            parse_mode="HTML")
        return

    # ── Numbers submenu ──────────────────────────────────────
    if data=="admin_numbers":
        if "manage_files" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        cats=await db.get_categories_summary()
        if not cats:
            await query.edit_message_text(
                f"📂 <b>Numbers</b>\n{D}\n"
                "No numbers uploaded yet.\n\n"
                "📤 Upload a <code>.txt</code> file with one number per line.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙  Back",callback_data="admin_home")]]),
                parse_mode="HTML")
        else:
            s=await db.get_stats()
            await query.edit_message_text(
                f"📂 <b>Numbers Manager</b>\n{D}\n"
                f"🟢 Available: <b>{s.get('available',0)}</b>  |  "
                f"🔴 In Use: <b>{s.get('assigned',0)}</b>\n"
                f"🧊 Cooldown: <b>{s.get('cooldown',0)}</b>  |  "
                f"✅ Used: <b>{s.get('used',0)}</b>",
                reply_markup=admin_numbers_kb(cats),parse_mode="HTML")
        return

    if data=="admin_upload_info":
        if "manage_files" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        await query.edit_message_text(
            f"📤 <b>Upload Numbers</b>\n{D}\n"
            "Send a <b>.txt file</b> in this chat.\n\n"
            "Format: one phone number per line\n"
            "<code>923001234567</code>\n"
            "<code>923009876543</code>\n\n"
            "The bot will auto-detect country and ask for services.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back",callback_data="admin_numbers")]]),
            parse_mode="HTML")
        return

    if data.startswith("cat_stats_"):
        if "manage_files" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        sid=data[10:]; cat=CATEGORY_MAP.get(sid)
        if not cat: await query.answer("Expired. Reopen Numbers.",show_alert=True); return
        await query.answer()
        async with db.AsyncSessionLocal() as session:
            from sqlalchemy import func as sfunc
            statuses=["AVAILABLE","ASSIGNED","RETENTION","USED","BLOCKED"]
            lines=[]
            for st in statuses:
                cnt=await session.scalar(
                    select(sfunc.count(db.Number.id)).where(
                        db.Number.category==cat,db.Number.status==st)) or 0
                if cnt>0:
                    icons={"AVAILABLE":"🟢","ASSIGNED":"🔴","RETENTION":"🧊","USED":"✅","BLOCKED":"🚫"}
                    lines.append(f"{icons[st]} {st}: <b>{cnt}</b>")
        await query.edit_message_text(
            f"📊 <b>Category Stats</b>\n{D}\n"
            f"<b>{html.escape(cat)}</b>\n\n"+("\n".join(lines) or "Empty"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back",callback_data="admin_numbers")]]),
            parse_mode="HTML")
        return

    if data=="purge_used":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        await query.edit_message_text("⚠️ Delete ALL <b>USED</b> numbers permanently?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅  Yes Purge",callback_data="confirm_purge_used"),
                InlineKeyboardButton("❌  Cancel",   callback_data="admin_numbers"),
            ]]),parse_mode="HTML")
        return

    if data=="confirm_purge_used":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        async with db.AsyncSessionLocal() as session:
            r=await session.execute(stext("DELETE FROM numbers WHERE status='USED'"))
            await session.commit(); n=r.rowcount
        await query.answer(f"✅ Purged {n} used numbers.",show_alert=True)
        cats=await db.get_categories_summary()
        await query.edit_message_text(f"📂 <b>Numbers Manager</b>\n{D}",
            reply_markup=admin_numbers_kb(cats),parse_mode="HTML")
        return

    if data=="purge_blocked":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        async with db.AsyncSessionLocal() as session:
            r=await session.execute(stext("DELETE FROM numbers WHERE status='BLOCKED'"))
            await session.commit(); n=r.rowcount
        await query.answer(f"✅ Purged {n} blocked numbers.",show_alert=True)
        cats=await db.get_categories_summary()
        await query.edit_message_text(f"📂 <b>Numbers Manager</b>\n{D}",
            reply_markup=admin_numbers_kb(cats),parse_mode="HTML")
        return

    # ── Stats submenu ─────────────────────────────────────────
    if data=="admin_stats_menu":
        if "view_stats" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        await query.edit_message_text(f"📊 <b>Statistics</b>\n{D}",
            reply_markup=admin_stats_menu_kb(),parse_mode="HTML")
        return

    if data=="admin_db_summary":
        if "view_stats" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        users=await db.get_all_users(); logs=await db.get_all_log_chats()
        s=await db.get_stats()
        total_n=sum(s.values())
        active=[p for p in PANELS if p.is_logged_in or (p.panel_type=="ivas" and p.name in IVAS_TASKS and not IVAS_TASKS[p.name].done())]
        await query.edit_message_text(
            f"💾 <b>Database Summary</b>\n{D}\n"
            f"👤 Users:       <b>{len(users)}</b>\n"
            f"📋 Log Groups:  <b>{len(logs)}</b>\n"
            f"🔌 Panels:      <b>{len(PANELS)}</b>  (active: {len(active)})\n"
            f"📱 Numbers:     <b>{total_n}</b>\n"
            f"🟢 Available:   <b>{s.get('available',0)}</b>\n"
            f"🔴 In Use:      <b>{s.get('assigned',0)}</b>\n"
            f"🧊 Cooldown:    <b>{s.get('cooldown',0)}</b>\n"
            f"✅ Used:        <b>{s.get('used',0)}</b>\n"
            f"🚫 Blocked:     <b>{s.get('blocked',0)}</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙  Back",callback_data="admin_stats_menu")]]),
            parse_mode="HTML")
        return

    if data=="admin_otp_history":
        if "view_stats" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        async with db.AsyncSessionLocal() as session:
            rows=(await session.execute(
                stext("SELECT phone_number,otp_code,service,timestamp FROM history "
                      "ORDER BY timestamp DESC LIMIT 10")
            )).fetchall()
        if not rows:
            await query.edit_message_text("📈 No OTP history yet.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back",callback_data="admin_stats_menu")]]))
            return
        lines=[]
        for row in rows:
            ts=str(row[3])[:16] if row[3] else "?"
            lines.append(f"📱 <code>{mask_number(str(row[0]))}</code>  🔑 <code>{row[1]}</code>  ⏰ {ts}")
        await query.edit_message_text(
            f"📈 <b>Last 10 OTP Deliveries</b>\n{D}\n"+"\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back",callback_data="admin_stats_menu")]]),
            parse_mode="HTML")
        return

    # ── Users submenu ─────────────────────────────────────────
    if data=="admin_users":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        await query.edit_message_text(f"👤 <b>User Manager</b>\n{D}",
            reply_markup=admin_users_kb(),parse_mode="HTML")
        return

    if data=="admin_list_users":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        all_u=await db.get_all_users()
        lines=[]
        for u in all_u[:25]:
            stats=await db.get_user_stats(u)
            crown="👑 " if u in INITIAL_ADMIN_IDS else ""
            lines.append(f"{crown}<code>{u}</code>  ✅{stats['success']}")
        more="" if len(all_u)<=25 else f"\n<i>…and {len(all_u)-25} more</i>"
        await query.edit_message_text(
            f"👤 <b>All Users ({len(all_u)})</b>\n{D}\n"
            +("\n".join(lines) or "None")+more,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back",callback_data="admin_users")]]),
            parse_mode="HTML")
        return

    # ── Maintenance submenu ───────────────────────────────────
    if data=="admin_maintenance":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        await query.edit_message_text(f"🧹 <b>Maintenance</b>\n{D}",
            reply_markup=admin_maintenance_kb(),parse_mode="HTML")
        return

    if data=="reload_countries":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        load_countries()
        await query.answer(f"✅ Reloaded {len(COUNTRY_DATA)} countries.",show_alert=True)
        return

    if data=="login_all_panels":
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer("🔄 Logging in to all panels…")
        ok=0; fail=0
        for p in PANELS:
            if p.panel_type=="login":
                if await login_to_panel(p): ok+=1
                else: fail+=1
            elif p.panel_type=="api":
                if await test_api_panel(p): p.is_logged_in=True; ok+=1
                else: fail+=1
        await refresh_panels_from_db()
        await query.edit_message_text(
            f"🔄 <b>Login All Panels</b>\n{D}\n✅ OK: {ok}  |  ❌ Failed: {fail}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back",callback_data="admin_panel_manager")]]),
            parse_mode="HTML")
        return

    # ── Settings extras ────────────────────────────────────────
    if data=="change_token_prompt":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        context.user_data["awaiting_link"]="BOT_TOKEN"
        await query.edit_message_text(
            "⚠️ <b>Change Bot Token</b>\n{D}\n"
            "Send the new bot token.\nThe bot will need to be restarted after this.\n\n"
            "/cancel to abort.",parse_mode="HTML")
        return

    if data=="set_developer_prompt":
        context.user_data["awaiting_link"]="DEVELOPER"
        await query.edit_message_text("🧠 Send the new Developer username (@username):")
        return

    if data in ("pt_login","pt_api","pt_ivas"):
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        if uid not in PANEL_ADD_STATES: await query.answer("No pending addition."); return
        ptype=data[3:]
        PANEL_ADD_STATES[uid]["data"]["panel_type"]=ptype
        if ptype=="ivas":
            PANEL_ADD_STATES[uid]["step"]="confirm_uri"
            await query.edit_message_text("📡 <b>IVAS Panel</b>\nUse default URI or enter custom?",parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Use Default",callback_data="pt_ivas_default")],
                    [InlineKeyboardButton("✏️ Custom URI", callback_data="pt_ivas_custom")],
                    [InlineKeyboardButton("❌ Cancel",     callback_data="cancel_action")],
                ]))
        else:
            PANEL_ADD_STATES[uid]["step"]="url"
            prompts={"login":"Enter Base URL (http://…):","api":"Enter API endpoint URL:"}
            await query.edit_message_text(prompts[ptype],parse_mode="HTML")
        return

    if data=="pt_ivas_default":
        if uid not in PANEL_ADD_STATES: await query.answer("No pending addition."); return
        name=PANEL_ADD_STATES[uid]["data"]["name"]
        await add_panel_to_db(name,"",None,None,"ivas",uri=DEFAULT_IVAS_URI)
        await refresh_panels_from_db()
        panel=next((p for p in PANELS if p.name==name),None)
        if panel:
            task=asyncio.create_task(ivas_worker(panel),name=f"IVAS-{name}")
            task.add_done_callback(handle_task_exception); IVAS_TASKS[name]=task
        del PANEL_ADD_STATES[uid]
        await query.edit_message_text("✅ IVAS panel added (default URI) and worker started!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_panel_manager")]]))
        return

    if data=="pt_ivas_custom":
        if uid in PANEL_ADD_STATES: PANEL_ADD_STATES[uid]["step"]="uri"
        await query.edit_message_text("Paste the custom IVAS URI (wss://…):")
        return

    if data=="admin_stats":
        if "view_stats" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer(); s=await db.get_stats()
        pi="\n".join(f"  {'🟢' if p.is_logged_in else '🔴'} {p.name} [{p.panel_type.upper()}]" for p in PANELS) or "  None"
        await query.edit_message_text(
            f"📊 <b>Live Stats</b>\n{D}\n"
            f"📦 Total:     <b>{s.get('available',0)+s.get('assigned',0)+s.get('cooldown',0)+s.get('used',0)+s.get('blocked',0)}</b>\n"
            f"🟢 Available: <b>{s.get('available',0)}</b>\n"
            f"🔴 In Use:    <b>{s.get('assigned',0)}</b>\n"
            f"🧊 Cooldown:  <b>{s.get('cooldown',0)}</b>\n"
            f"✅ Used:      <b>{s.get('used',0)}</b>\n"
            f"🚫 Blocked:   <b>{s.get('blocked',0)}</b>\n\n"
            f"🔌 <b>Panels:</b>\n{pi}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_home")]]),
            parse_mode="HTML")
        return

    if data=="admin_reset":
        if "view_stats" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        n=await db.clean_cooldowns(); await query.answer(f"✅ {n} numbers released.",show_alert=True); return

    if data in ("admin_files","admin_numbers"):
        if "manage_files" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        cats=await db.get_categories_summary()
        s=await db.get_stats()
        if not cats:
            await query.edit_message_text(
                f"📂 <b>Numbers Manager</b>\n{D}\n"
                "No numbers uploaded yet.\n\n"
                "📤 Send a <code>.txt</code> file with one number per line.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back",callback_data="admin_home")]]),
                parse_mode="HTML")
        else:
            await query.edit_message_text(
                f"📂 <b>Numbers Manager</b>\n{D}\n"
                f"🟢 Available: <b>{s.get('available',0)}</b>  "
                f"🔴 In Use: <b>{s.get('assigned',0)}</b>  "
                f"🧊 Cooldown: <b>{s.get('cooldown',0)}</b>",
                reply_markup=admin_numbers_kb(cats),parse_mode="HTML")
        return

    if data.startswith("del_"):
        if "manage_files" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        sid=data[4:]; cat=CATEGORY_MAP.get(sid)
        if not cat: await query.edit_message_text("❌ Expired menu. Reopen File Manager."); return
        await db.delete_category(cat)
        cats=await db.get_categories_summary()
        if not cats:
            await query.edit_message_text("📂 All files deleted.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_home")]]))
        else:
            await query.edit_message_text(f"✅ Deleted.\n\n📂 <b>File Manager</b>",
                reply_markup=files_kb(cats),parse_mode="HTML")
        return

    if data=="admin_broadcast":
        if "broadcast" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        context.user_data["awaiting_broadcast"]=True
        await query.edit_message_text(
            f"📢 <b>Broadcast Mode</b>\n{D}\n"
            "Type your announcement and send it.\nDelivered to <b>all registered users</b>.",
            parse_mode="HTML")
        return

    if data=="admin_panel_manager":
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.edit_message_text(f"🔌 <b>Panel Manager</b>\n{D}",reply_markup=panel_mgr_kb(),parse_mode="HTML")
        return

    if data in ("panels_login","panels_api","panels_ivas"):
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await refresh_panels_from_db(); ptype=data.split("_")[1]
        pl=[p for p in PANELS if p.panel_type==ptype]
        icons={"login":"🔑","api":"🔌","ivas":"📡"}; labels={"login":"Login","api":"API","ivas":"IVAS"}
        if not pl:
            await query.edit_message_text(f"{icons[ptype]} <b>{labels[ptype]} Panels</b>\n\nNone yet.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add Panel",callback_data="p_add")],
                    [InlineKeyboardButton("🔙 Back",callback_data="admin_panel_manager")]]),parse_mode="HTML")
            return
        lines=[]
        for p in pl:
            if ptype=="ivas": st="🟢" if (p.name in IVAS_TASKS and not IVAS_TASKS[p.name].done()) else "🔴"
            else: st="🟢" if p.is_logged_in else "🔴"
            lines.append(f"{st} <b>{html.escape(p.name)}</b>")
        await query.edit_message_text(f"{icons[ptype]} <b>{labels[ptype]} Panels</b>\n{D}\n"+"\n".join(lines),
            reply_markup=panel_list_kb(pl,ptype),parse_mode="HTML")
        return

    if data=="p_add":
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        PANEL_ADD_STATES[uid]={"step":"name","data":{}}; await query.answer()
        await query.edit_message_text(f"➕ <b>Add Panel</b>\n{D}\nStep 1 — Enter panel name:",parse_mode="HTML")
        return

    if data.startswith("p_test_"):
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        pid=int(data.split("_")[-1]); panel=next((p for p in PANELS if p.id==pid),None)
        if not panel: await query.answer("Not found",show_alert=True); return
        await query.answer("🔄 Testing…")
        if panel.panel_type=="login":
            ok=await login_to_panel(panel)
            await update_panel_login(pid,panel.sesskey if ok else None,panel.api_url if ok else None,ok)
            result=f"{'✅ OK' if ok else '❌ FAILED'}\n{panel.base_url}"
        elif panel.panel_type=="api":
            ok=await test_api_panel(panel); panel.is_logged_in=ok
            await update_panel_login(pid,None,panel.base_url if ok else None,ok)
            result=f"{'✅ API OK' if ok else '❌ API FAILED'}\n{panel.base_url}"
        else:
            running=panel.name in IVAS_TASKS and not IVAS_TASKS[panel.name].done()
            result=f"{'✅ Running' if running else '❌ Stopped'}"
        await refresh_panels_from_db()
        back_cb={"login":"panels_login","api":"panels_api","ivas":"panels_ivas"}.get(panel.panel_type,"admin_panel_manager")
        await query.edit_message_text(f"<b>Test: {html.escape(panel.name)}</b>\n{D}\n{result}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data=back_cb)]]))
        return

    if data.startswith("p_info_"):
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        pid=int(data.split("_")[-1]); panel=next((p for p in PANELS if p.id==pid),None)
        if not panel: await query.answer("Not found",show_alert=True); return
        st="🟢 Online" if panel.is_logged_in else "🔴 Offline"
        info=f"🔍 <b>{html.escape(panel.name)}</b>\n{D}\n🆔 {panel.id} | {panel.panel_type.upper()} | {st}\n\n"
        if panel.panel_type=="login":
            info+=(f"🔗 <code>{html.escape(panel.base_url)}</code>\n"
                   f"👤 <code>{html.escape(panel.username or '')}</code>\n"
                   f"📡 API: <code>{html.escape(panel.api_url or 'N/A')}</code>")
        elif panel.panel_type=="api":
            info+=f"🌐 <code>{html.escape(panel.base_url)}</code>\n🪙 Token: {'✅' if panel.token else '❌'}"
        else:
            uri_=((panel.uri or "")[:80]+"…") if panel.uri and len(panel.uri)>80 else (panel.uri or "")
            running=panel.name in IVAS_TASKS and not IVAS_TASKS[panel.name].done()
            info+=(f"📡 <code>{html.escape(uri_)}</code>\n"
                   f"⚙️ {'🟢 Running' if running else '🔴 Stopped'}")
        back_cb={"login":"panels_login","api":"panels_api","ivas":"panels_ivas"}.get(panel.panel_type,"admin_panel_manager")
        await query.answer()
        try:
            await query.edit_message_text(info,parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Test",callback_data=f"p_test_{pid}"),
                     InlineKeyboardButton("✏️ Edit",callback_data=f"p_edit_{pid}")],
                    [InlineKeyboardButton("🔙 Back",callback_data=back_cb)],
                ]))
        except TelegramBadRequest: pass
        return

    if data.startswith("p_edit_"):
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        pid=int(data.split("_")[-1]); panel=next((p for p in PANELS if p.id==pid),None)
        if not panel: await query.answer("Not found",show_alert=True); return
        PANEL_EDIT_STATES[uid]={"step":"name","panel_id":pid,
            "data":{"name":panel.name,"base_url":panel.base_url,"username":panel.username,
                    "password":panel.password,"panel_type":panel.panel_type,"token":panel.token,"uri":panel.uri}}
        await query.answer()
        await query.edit_message_text(f"✏️ <b>Edit: {html.escape(panel.name)}</b>\n\nCurrent: <code>{html.escape(panel.name)}</code>\nNew name (/skip):",parse_mode="HTML")
        return

    if data.startswith("p_del_") and not data.endswith("confirm"):
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        pid=int(data.split("_")[-1]); context.user_data["confirm_del_panel"]=pid
        p=next((x for x in PANELS if x.id==pid),None)
        await query.answer()
        await query.edit_message_text(f"⚠️ Delete panel <b>{html.escape(p.name if p else str(pid))}</b>?",
            reply_markup=confirm_del_panel_kb(),parse_mode="HTML")
        return

    if data=="p_del_confirm":
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        pid=context.user_data.pop("confirm_del_panel",None)
        if pid:
            p=next((x for x in PANELS if x.id==pid),None)
            if p:
                if p.panel_type=="ivas" and p.name in IVAS_TASKS:
                    IVAS_TASKS[p.name].cancel(); IVAS_TASKS.pop(p.name,None)
                await p.close()
            await delete_panel_from_db(pid); await refresh_panels_from_db()
            await query.answer("✅ Deleted.")
        await query.edit_message_text(f"🔌 <b>Panel Manager</b>\n{D}",reply_markup=panel_mgr_kb(),parse_mode="HTML")
        return

    if data=="admin_manage_logs":
        if "manage_logs" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        chats=await db.get_all_log_chats()
        await query.edit_message_text(f"📋 <b>Log Groups</b>\n{D}\nTotal: <b>{len(chats)}</b>",
            reply_markup=logs_kb(chats),parse_mode="HTML")
        return

    if data.startswith("rm_log_"):
        if "manage_logs" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        cid=int(data.split("_")[-1]); ok=await db.remove_log_chat(cid)
        await query.answer(f"{'✅ Removed' if ok else '❌ Not found'}: {cid}")
        chats=await db.get_all_log_chats()
        await query.edit_message_text(f"📋 <b>Log Groups</b>\n{D}",reply_markup=logs_kb(chats),parse_mode="HTML")
        return

    if data=="add_log_prompt":
        if "manage_logs" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        AWAITING_LOG_ID[uid]=True
        await query.edit_message_text("📋 <b>Add Log Group</b>\n\nSend the numeric chat ID.\n(/cancel to abort)",parse_mode="HTML")
        return

    if data=="admin_manage_admins":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        admins = await list_all_admins()
        sup_count = len([a for a in admins if a in INITIAL_ADMIN_IDS])
        await safe_edit(query,
            f"👥 <b>Admin Manager</b>\n{D}\n"
            f"👑 Super Admins: <b>{sup_count}</b>\n"
            f"👮 Regular Admins: <b>{len(admins)-sup_count}</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥  All Admins",       callback_data="admin_list_admins_view"),
                 InlineKeyboardButton("👑  Add Super Admin",  callback_data="add_superadmin_prompt")],
                [InlineKeyboardButton("➕  Add Regular Admin", callback_data="add_admin_prompt")],
                [InlineKeyboardButton("🔙  Back",             callback_data="admin_home")],
            ]))
        return

    if data=="admin_list_admins_view":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        admins = await list_all_admins()
        await safe_edit(query,
            f"👥 <b>All Admins</b>  ({len(admins)} total)",
            reply_markup=admin_list_kb(admins))
        return

    if data=="add_superadmin_prompt":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        AWAITING_SUPER_ADMIN[uid] = True
        await safe_edit(query,
            "👑 <b>Add Super Admin</b>\n\n"
            "Send the Telegram <b>User ID</b> of the new super admin.\n\n"
            "⚠️ Super admins have <b>full access</b> to all bot functions.\n"
            "/cancel to abort.")
        return

    if data.startswith("rm_admin_"):
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        aid=int(data.split("_")[-1])
        if aid==uid: await query.answer("Can't remove yourself!",show_alert=True); return
        if aid in INITIAL_ADMIN_IDS: await query.answer("Can't remove super admin!",show_alert=True); return
        await remove_admin_permissions(aid); await query.answer(f"✅ Removed {aid}")
        admins=await list_all_admins()
        await query.edit_message_text(f"👥 <b>Admin Management</b>",reply_markup=admin_list_kb(admins),parse_mode="HTML")
        return

    if data=="add_admin_prompt":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        AWAITING_ADMIN_ID[uid]=True
        await query.edit_message_text("👥 <b>Add Admin</b>\n\nSend the user's numeric Telegram ID.",parse_mode="HTML")
        return

    if data.startswith("ptoggle|"):
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        _,tuid_str,perm=data.split("|",2); tuid=int(tuid_str)
        sel=AWAITING_PERMISSIONS.get((uid,tuid),[])
        if perm in sel: sel.remove(perm)
        else: sel.append(perm)
        AWAITING_PERMISSIONS[(uid,tuid)]=sel
        await query.edit_message_reply_markup(reply_markup=perms_kb(sel,tuid)); await query.answer()
        return

    if data.startswith("pdone|"):
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        tuid=int(data.split("|")[1]); sel=AWAITING_PERMISSIONS.pop((uid,tuid),[])
        if not sel: await query.answer("Select at least one!",show_alert=True); return
        await set_admin_permissions(tuid,sel); AWAITING_ADMIN_ID.pop(uid,None)
        plist="\n".join(f"• {PERMISSIONS.get(p,p)}" for p in sel)
        await query.edit_message_text(f"✅ <b>Admin {tuid} added!</b>\n\n<b>Permissions:</b>\n{plist}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_manage_admins")]]))
        return

    if data=="admin_settings":
        await query.answer()
        await query.edit_message_text(f"⚙️ <b>Settings</b>\n{D}",reply_markup=admin_settings_kb(),parse_mode="HTML")
        return

    if data.startswith("gui_page_"):
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        page = int(data.split("_")[-1])
        await query.answer()
        theme_name = _THEME_NAMES.get(OTP_GUI_THEME % 30, "Unknown")
        try:
            await query.edit_message_reply_markup(reply_markup=gui_theme_kb(page))
        except Exception:
            pass
        return

    if data=="admin_gui_theme":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        theme_name = _THEME_NAMES.get(OTP_GUI_THEME % 30, "Unknown")
        await query.edit_message_text(
            f"🎨 <b>OTP GUI Theme</b>\n{D}\n"
            f"Current: <b>{theme_name}</b>\n\n"
            "Select a theme to see how OTP messages will look.\n"
            "Both DM and group messages update instantly.",
            reply_markup=gui_theme_kb(), parse_mode="HTML")
        return

    if data.startswith("gui_page_"):
        # SUPER ADMIN ONLY — navigate theme pages
        if not is_super_admin(uid): await query.answer("Super Admin only", show_alert=True); return
        page = int(data.split("_")[-1])
        await query.answer()
        try:
            await query.edit_message_reply_markup(reply_markup=gui_theme_page_kb(page))
        except Exception: pass
        return

    if data.startswith("set_gui_theme_"):
        # SUPER ADMIN ONLY — only super admins can change the OTP design
        if not is_super_admin(uid):
            await query.answer("⛔ Only Super Admins can change the OTP design.", show_alert=True)
            return
        OTP_GUI_THEME = int(data.split("_")[-1]) % 30
        save_config_key("OTP_GUI_THEME", OTP_GUI_THEME)
        theme_name = _THEME_NAMES.get(OTP_GUI_THEME, "Unknown")
        await query.answer(f"✅ Design → {theme_name}", show_alert=False)
        await safe_edit(query,
            f"🎨 <b>OTP Design Selected</b>\n{D}\n"
            f"✅ <b>{theme_name}</b>\n\n"
            f"All future OTP messages will use this design.",
            reply_markup=gui_theme_page_kb(OTP_GUI_THEME // 10))
        return

    if data=="admin_links":
        await query.answer()
        ch=CHANNEL_LINK or "—"; og=OTP_GROUP_LINK or "—"; nb=NUMBER_BOT_LINK or "—"; su=SUPPORT_USER or "—"
        await query.edit_message_text(
            f"🔗 <b>Bot Links</b>\n{D}\n"
            f"📢 Channel:   <code>{html.escape(ch)}</code>\n"
            f"💬 OTP Group: <code>{html.escape(og)}</code>\n"
            f"📞 Num Bot:   <code>{html.escape(nb)}</code>\n"
            f"🛟 Support:   <code>{html.escape(su)}</code>",
            reply_markup=admin_links_kb(),parse_mode="HTML")
        return

    if data=="admin_botinfo":
        await query.answer()
        await query.edit_message_text(
            f"🤖 <b>Bot Info</b>\n{D}\n"
            f"👤 Username:  @{html.escape(BOT_USERNAME)}\n"
            f"🆔 Token:     <code>{'•'*20}</code>\n"
            f"🧸 Child Bot: {'Yes' if IS_CHILD_BOT else 'No'}\n"
            f"📦 Limit:     {DEFAULT_ASSIGN_LIMIT}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_settings")]]),
            parse_mode="HTML")
        return

    if data.endswith("_prompt") and data in ("set_channel_prompt","set_otpgroup_prompt","set_numbot_prompt","set_support_prompt"):
        key_map={"set_channel_prompt":"CHANNEL_LINK","set_otpgroup_prompt":"OTP_GROUP_LINK",
                 "set_numbot_prompt":"NUMBER_BOT_LINK","set_support_prompt":"SUPPORT_USER"}
        context.user_data["awaiting_link"]=key_map[data]
        label_map={"CHANNEL_LINK":"Channel Link (https://t.me/...)","OTP_GROUP_LINK":"OTP Group Link (https://t.me/...)","NUMBER_BOT_LINK":"Number Bot Link (https://t.me/...)","SUPPORT_USER":"Support Username (@username)"}
        k=key_map[data]
        await query.edit_message_text(f"✏️ Send new {label_map[k]}:",parse_mode="HTML")
        return

    if data=="set_limit":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.edit_message_text(f"📦 <b>Global Limit</b>\nCurrent: <b>{DEFAULT_ASSIGN_LIMIT}</b>",
            reply_markup=limit_kb(),parse_mode="HTML")
        return

    if data.startswith("glimit_"):
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        DEFAULT_ASSIGN_LIMIT=int(data.split("_")[-1])
        save_config_key("default_limit",DEFAULT_ASSIGN_LIMIT)
        await query.answer(f"✅ Limit → {DEFAULT_ASSIGN_LIMIT}")
        await query.edit_message_text(f"⚙️ <b>Settings</b>\n{D}",reply_markup=admin_settings_kb(),parse_mode="HTML")
        return

    if data=="admin_advanced":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.edit_message_text(f"🛠 <b>Advanced Tools</b>\n{D}",reply_markup=advanced_kb(),parse_mode="HTML")
        return

    if data=="test_panels":
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer("🔄 Testing…")
        lines=[]
        for p in PANELS:
            if p.panel_type=="login":   ok=await login_to_panel(p); lines.append(f"{'✅' if ok else '❌'} {html.escape(p.name)} [LOGIN]")
            elif p.panel_type=="api":   ok=await test_api_panel(p); p.is_logged_in=ok; lines.append(f"{'✅' if ok else '❌'} {html.escape(p.name)} [API]")
            else:
                running=p.name in IVAS_TASKS and not IVAS_TASKS[p.name].done()
                lines.append(f"{'🟢' if running else '🔴'} {html.escape(p.name)} [IVAS]")
        await query.edit_message_text(f"🔍 <b>Panel Tests</b>\n{D}\n"+"\n".join(lines),parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_advanced")]]))
        return

    if data=="restart_workers":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        for nm,task in list(IVAS_TASKS.items()): task.cancel(); IVAS_TASKS.pop(nm,None)
        for p in PANELS:
            if p.panel_type=="ivas":
                task=asyncio.create_task(ivas_worker(p),name=f"IVAS-{p.name}")
                task.add_done_callback(handle_task_exception); IVAS_TASKS[p.name]=task
        await query.answer("✅ Workers restarted.",show_alert=True)
        await query.edit_message_text(f"🛠 <b>Advanced Tools</b>\n{D}\n✅ Workers restarted.",
            reply_markup=advanced_kb(),parse_mode="HTML")
        return

    if data=="clear_otps":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.edit_message_text("🗑 Clear ALL OTPs?",reply_markup=confirm_kb("clear_otps"))
        return
    if data=="confirm_clear_otps":
        save_otp_store({})
        await query.edit_message_text("✅ All OTPs cleared.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_advanced")]]))
        return

    if data=="export_otps":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        store=load_otp_store()
        if not store: await query.answer("No OTPs.",show_alert=True); return
        fname=f"otp_export_{datetime.now():%Y%m%d_%H%M%S}.json"
        with open(fname,"w") as f: json.dump(store,f,indent=2)
        try:
            with open(fname,"rb") as f: await context.bot.send_document(chat_id=uid,document=f,caption="📤 OTP Export")
        finally: os.remove(fname)
        await query.answer("✅ Exported."); return

    if data=="view_logs":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        try:
            lines_=open(LOG_FILE,errors="replace").readlines()[-25:]
            await query.edit_message_text(
                f"<b>Last 25 log lines</b>\n<pre>{html.escape(''.join(lines_)[-3500:])}</pre>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_advanced")]]))
        except Exception as e: await query.edit_message_text(f"Error: {e}")
        return

    if data=="admin_fetch_sms":
        if "manage_panels" not in perms and not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer("📡 Fetching…")
        report=f"📋 <b>SMS Fetch Report</b>\n🕒 {datetime.now():%Y-%m-%d %H:%M:%S}\n{D}\n"
        for p in PANELS:
            if p.panel_type=="ivas":
                running=p.name in IVAS_TASKS and not IVAS_TASKS[p.name].done()
                report+=f"📡 <b>{html.escape(p.name)}</b> [IVAS] {'🟢 Running' if running else '🔴 Stopped'}\n\n"; continue
            if p.panel_type=="login" and not p.is_logged_in: await login_to_panel(p)
            sms=await fetch_panel_sms(p)
            if sms is None: report+=f"❌ <b>{html.escape(p.name)}</b>: Auth failed.\n\n"
            elif not sms: report+=f"✅ <b>{html.escape(p.name)}</b>: Connected — no recent SMS.\n\n"
            else:
                report+=f"✅ <b>{html.escape(p.name)}</b> — {len(sms)} records (latest 5):\n"
                for rec in sms[:5]:
                    if p.panel_type=="api": dt_=str(rec[0]); num_=str(rec[1]); msg_=str(rec[3])
                    else: dt_=str(rec[0]); num_=str(rec[2]) if len(rec)>2 else "?"; msg_=get_message_body(rec) or ""
                    otp_=extract_otp_regex(msg_) or ""; time_=dt_[11:19] if len(dt_)>=19 else dt_
                    report+=f"  ⏰{time_} 📱{mask_number(num_)} {'🔑'+otp_ if otp_ else ''}\n  {html.escape(msg_[:60])}\n"
                report+="\n"
        bkb=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_home")]])
        if len(report)>4000:
            for chunk in [report[i:i+4000] for i in range(0,len(report),4000)]:
                await context.bot.send_message(uid,chunk,parse_mode="HTML")
            await context.bot.send_message(uid,"Done.",reply_markup=bkb)
        else:
            await context.bot.send_message(uid,report,parse_mode="HTML",reply_markup=bkb)
        return

    # ── Multi-Bot Management ─────────────────────────────
    if not IS_CHILD_BOT:
        if data=="admin_bots":
            if not is_sup: await query.answer("Unauthorized",show_alert=True); return
            await query.answer(); bots=bm.list_bots()
            tr=sum(1 for b in bots if b.get("running"))
            lines_txt="\n".join(f"{'🟢' if b.get('running') else '🔴'} <b>{html.escape(b['name'])}</b>  <code>{b['id']}</code>" for b in bots) if bots else "<i>No bots yet.</i>"
            await query.edit_message_text(
                f"🖥  <b>Bot Manager</b>\n{D}\nTotal: <b>{len(bots)}</b>  |  Running: <b>{tr}</b>\n\n{lines_txt}",
                reply_markup=bots_list_kb(bots),parse_mode="HTML")
            return

        if data=="add_bot_start":
            if not is_sup: await query.answer("Unauthorized",show_alert=True); return
            BOT_ADD_STATES[uid]={"step":"name","data":{}}; await query.answer()
            await query.edit_message_text(
                f"🤖 <b>Add New Bot</b>\n{D}\n"
                "Step 1/9 — Send a <b>name</b> for this bot\n"
                "<i>e.g. MyStore, OTPBot2, SigmaV2</i>\n\nSend /cancel to abort.",
                parse_mode="HTML")
            return

        if data.startswith("bot_info_"):
            if not is_sup: await query.answer("Unauthorized",show_alert=True); return
            bid=data[9:]; info=bm.get_bot_info(bid)
            if not info: await query.answer("Not found.",show_alert=True); return
            running=bm.is_running(bid); st="🟢 Running" if running else "🔴 Stopped"
            created=info.get("created_at","?")[:16].replace("T"," ")
            uname=info.get("bot_username","?")
            bot_link=f"https://t.me/{uname.lstrip('@')}" if uname and uname!="?" else "—"
            await query.answer()
            try:
                await query.edit_message_text(
                    f"╔══════════════════════════╗\n"
                    f"║  🤖  {html.escape(info.get('name','?')):<21}║\n"
                    f"╠══════════════════════════╣\n"
                    f"║  📶 {st:<24}║\n"
                    f"║  🆔 <code>{bid}</code>         ║\n"
                    f"╠══════════════════════════╣\n"
                    f"  👤 @{html.escape(uname):<23}\n"
                    f"  👥 Admins: {str(info.get('admin_ids',[]))[:20]}\n"
                    f"  📅 Created: {created}\n"
                    f"  📁 <code>{html.escape(info.get('folder','?'))[-30:]}</code>\n"
                    f"╠══════════════════════════╣\n"
                    f"  📢 {html.escape(info.get('channel_link','—') or '—')[:30]}\n"
                    f"  💬 {html.escape(info.get('otp_group_link','—') or '—')[:30]}\n"
                    f"  📞 {html.escape(info.get('number_bot_link','—') or '—')[:30]}\n"
                    f"  🛟 {html.escape(info.get('support_user','—') or '—')}",
                    reply_markup=bot_actions_kb(bid,running,info),parse_mode="HTML")
            except TelegramBadRequest: pass
            return

        if data.startswith("bot_start_"):
            if not is_sup: await query.answer("Unauthorized",show_alert=True); return
            bid=data[10:]; ok,msg=bm.start_bot(bid)
            await query.answer(f"{'✅' if ok else '❌'} {msg}",show_alert=True)
            bots=bm.list_bots()
            try: await query.edit_message_reply_markup(reply_markup=bots_list_kb(bots))
            except TelegramBadRequest: pass
            return

        if data.startswith("bot_stop_"):
            if not is_sup: await query.answer("Unauthorized",show_alert=True); return
            bid=data[9:]; ok,msg=bm.stop_bot(bid)
            await query.answer(f"{'✅' if ok else '❌'} {msg}",show_alert=True)
            bots=bm.list_bots()
            try: await query.edit_message_reply_markup(reply_markup=bots_list_kb(bots))
            except TelegramBadRequest: pass
            return

        if data.startswith("bot_restart_"):
            if not is_sup: await query.answer("Unauthorized",show_alert=True); return
            bid=data[12:]; await query.answer("🔁 Restarting…")
            ok,msg=bm.restart_bot(bid); info=bm.get_bot_info(bid) or {}; running=bm.is_running(bid)
            try:
                await query.edit_message_text(
                    f"🤖 <b>{html.escape(info.get('name','?'))}</b>\n"
                    f"{'🟢 Running' if running else '🔴 Stopped'}\nResult: {msg}",
                    reply_markup=bot_actions_kb(bid,running,info),parse_mode="HTML")
            except TelegramBadRequest: pass
            return

        if data.startswith("bot_log_"):
            if not is_sup: await query.answer("Unauthorized",show_alert=True); return
            bid=data[8:]; log=bm.get_bot_log(bid,lines=30); info=bm.get_bot_info(bid) or {}
            await query.answer()
            try:
                await query.edit_message_text(
                    f"📋 <b>Log: {html.escape(info.get('name','?'))}</b>\n<pre>{html.escape(log[-3000:])}</pre>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔁 Refresh",callback_data=f"bot_log_{bid}"),
                        InlineKeyboardButton("🔙 Back",   callback_data=f"bot_info_{bid}"),
                    ]]))
            except TelegramBadRequest: pass
            return

        if data.startswith("bot_del_") and not data.startswith("bot_delok_"):
            if not is_sup: await query.answer("Unauthorized",show_alert=True); return
            bid=data[8:]; info=bm.get_bot_info(bid) or {}; await query.answer()
            await query.edit_message_text(
                f"⚠️ Delete bot <b>{html.escape(info.get('name','?'))}</b>?\n\n"
                "This permanently stops and deletes its folder.",
                reply_markup=confirm_del_bot_kb(bid),parse_mode="HTML")
            return

        if data.startswith("bot_delok_"):
            if not is_sup: await query.answer("Unauthorized",show_alert=True); return
            bid=data[10:]; ok,msg=bm.delete_bot(bid)
            await query.answer(f"{'✅' if ok else '❌'} {msg}",show_alert=True)
            bots=bm.list_bots()
            await query.edit_message_text(f"🖥  <b>Bot Manager</b>\nTotal: <b>{len(bots)}</b>",
                reply_markup=bots_list_kb(bots),parse_mode="HTML")
            return

    # ═══════════════════════════════════════════════════
    #  OTP STORE VIEWER
    # ═══════════════════════════════════════════════════
    if data=="admin_otp_store":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        store=load_otp_store()
        if not store:
            await query.edit_message_text("🔑 <b>OTP Store</b>\nEmpty.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_home")]]),
                parse_mode="HTML")
            return
        lines=[f"📱 <code>{mask_number(k)}</code>  🔑 <code>{v}</code>" for k,v in list(store.items())[-20:]]
        await query.edit_message_text(
            f"🔑 <b>OTP Store</b>  ({len(store)} entries, last 20)\n{D}\n"+"\n".join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Clear All", callback_data="clear_otps"),
                 InlineKeyboardButton("📤 Export",    callback_data="export_otps")],
                [InlineKeyboardButton("🔙 Back",      callback_data="admin_home")]]),
            parse_mode="HTML")
        return

    # ═══════════════════════════════════════════════════
    #  BROADCAST TO ALL BOTS USERS
    # ═══════════════════════════════════════════════════
    if data=="broadcast_all_bots":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        context.user_data["bcast_all_bots"]=True
        context.user_data["awaiting_broadcast"]=True
        await query.answer()
        bots=bm.list_bots(); total_bots=len(bots)
        await query.edit_message_text(
            f"📢 <b>Broadcast to ALL Bots</b>\n{D}\n"
            f"This will send your message to users of <b>ALL {total_bots} child bots</b> "
            f"plus this master bot.\n\n"
            "✏️ <b>Type your message and send it:</b>\n"
            "<i>(Supports HTML formatting)</i>",
            parse_mode="HTML")
        return

    # ═══════════════════════════════════════════════════
    #  CHILD BOT — START ALL / STOP ALL
    # ═══════════════════════════════════════════════════
    if data=="bots_start_all":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer("▶️ Starting all bots…")
        bots=bm.list_bots(); ok=0; fail=0
        for b in bots:
            if not bm.is_running(b["id"]):
                res,_=bm.start_bot(b["id"])
                if res: ok+=1
                else:   fail+=1
        bots=bm.list_bots(); run=sum(1 for b in bots if b.get("running"))
        await query.edit_message_text(
            f"🖥 <b>Bot Manager</b>\n{D}\n"
            f"▶️ Started: <b>{ok}</b>  ❌ Failed: <b>{fail}</b>\n"
            f"🟢 Running: <b>{run}/{len(bots)}</b>",
            reply_markup=bots_list_kb(bots),parse_mode="HTML")
        return

    if data=="bots_stop_all":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer("⏹ Stopping all bots…")
        bots=bm.list_bots(); stopped=0
        for b in bots:
            if bm.is_running(b["id"]):
                bm.stop_bot(b["id"]); stopped+=1
        bots=bm.list_bots()
        await query.edit_message_text(
            f"🖥 <b>Bot Manager</b>\n{D}\n⏹ Stopped: <b>{stopped}</b> bots",
            reply_markup=bots_list_kb(bots),parse_mode="HTML")
        return

    if data=="bots_all_stats":
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        await query.answer()
        bots=bm.list_bots(); lines=[]
        for b in bots:
            st="🟢" if b.get("running") else "🔴"
            reg=bm.load_registry().get(b["id"],{})
            lines.append(
                f"{st} <b>{html.escape(b['name'])}</b>\n"
                f"   📢 {html.escape(reg.get('channel_link','—') or '—')}\n"
                f"   💬 {html.escape(reg.get('otp_group_link','—') or '—')}\n"
                f"   👤 {reg.get('admin_ids',[])}"
            )
        await query.edit_message_text(
            f"📊 <b>All Bots Overview</b>  ({len(bots)} total)\n{D}\n"
            +("\n\n".join(lines) if lines else "None"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="admin_bots")]]),
            parse_mode="HTML")
        return

    # ═══════════════════════════════════════════════════
    #  CHILD BOT — INDIVIDUAL STATS + BROADCAST
    # ═══════════════════════════════════════════════════
    if data.startswith("bot_stats_"):
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        bid=data[10:]; info=bm.get_bot_info(bid) or {}; await query.answer()
        running=bm.is_running(bid)
        log_preview=bm.get_bot_log(bid,lines=5)
        last_lines=log_preview[-300:] if log_preview else "(no log)"
        await query.edit_message_text(
            f"📊 <b>Bot: {html.escape(info.get('name','?'))}</b>\n{D}\n"
            f"📶 Status: {'🟢 Running' if running else '🔴 Stopped'}\n"
            f"📢 Channel: {html.escape(info.get('channel_link','—') or '—')}\n"
            f"💬 OTP Grp: {html.escape(info.get('otp_group_link','—') or '—')}\n"
            f"📞 Num Bot: {html.escape(info.get('number_bot_link','—') or '—')}\n"
            f"👤 Admins:  {info.get('admin_ids',[])}\n\n"
            f"📋 <b>Last log lines:</b>\n<pre>{html.escape(last_lines)}</pre>",
            reply_markup=bot_actions_kb(bid,running,info),parse_mode="HTML")
        return

    if data.startswith("bot_bcast_"):
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        bid=data[10:]; info=bm.get_bot_info(bid) or {}; await query.answer()
        context.user_data["bcast_single_bot"]=bid
        context.user_data["awaiting_broadcast"]=True
        await query.edit_message_text(
            f"📢 <b>Broadcast — {html.escape(info.get('name','?'))}</b>\n{D}\n"
            "Type your message and send it.\n"
            "It will be delivered to users of <b>this bot only</b>.\n\n"
            "<i>(HTML formatting supported)</i>",
            parse_mode="HTML")
        return

    # ═══════════════════════════════════════════════════
    #  CHILD BOT — EDIT LINKS INLINE
    # ═══════════════════════════════════════════════════
    if data.startswith("bot_editlinks_"):
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        bid=data[14:]; info=bm.get_bot_info(bid) or {}; await query.answer()
        await query.edit_message_text(
            f"🔗 <b>Edit Links: {html.escape(info.get('name','?'))}</b>\n{D}\n"
            f"📢 Channel:  <code>{html.escape(info.get('channel_link','—') or '—')}</code>\n"
            f"💬 OTP Grp:  <code>{html.escape(info.get('otp_group_link','—') or '—')}</code>\n"
            f"📞 Num Bot:  <code>{html.escape(info.get('number_bot_link','—') or '—')}</code>\n"
            f"🛟 Support:  <code>{html.escape(info.get('support_user','—') or '—')}</code>",
            reply_markup=bot_edit_links_kb(bid),parse_mode="HTML")
        return

    if data.startswith("bot_setlink_"):
        if not is_sup: await query.answer("Unauthorized",show_alert=True); return
        parts=data.split("_",3); bid=parts[2]; link_key=parts[3]
        await query.answer()
        context.user_data["bot_setlink_bid"]=bid
        context.user_data["bot_setlink_key"]=link_key
        labels={"CHANNEL_LINK":"Channel Link (https://t.me/...)","OTP_GROUP_LINK":"OTP Group Link","NUMBER_BOT_LINK":"Number Bot Link","SUPPORT_USER":"Support Username"}
        await query.edit_message_text(
            f"✏️ Send the new <b>{labels.get(link_key,link_key)}</b> for bot <b>{bid}</b>:\n"
            "/cancel to abort.",parse_mode="HTML")
        return

    # ═══════════════════════════════════════════════════
    #  CANCEL
    # ═══════════════════════════════════════════════════
    if data=="pick_gui":
        await query.answer()
        cur = GUI_STYLE
        def _g(n): return "✅" if cur==n else f"{n}️⃣"
        await safe_edit(query,
            f"🎨 <b>Select OTP GUI Style</b>\n\nCurrent: <b>Style {cur}</b>\n\n"
            f"<b>1</b> — Screenshot  (flag + number + 🔥)\n"
            f"<b>2</b> — Neon / Electric  (⚡ dashes)\n"
            f"<b>3</b> — Sigma Classic  (━ lines)\n"
            f"<b>4</b> — Minimal Clean\n"
            f"<b>5</b> — Royal Gold  (👑)\n"
            f"<b>6</b> — ⭐ TempNum Style  (boxes)\n"
            f"<b>7</b> — ⭐ Jack-X Style  (→ arrow)\n"
            f"<b>8</b> — ⭐ Cyber Matrix  (☠️ dark)",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{_g(1)}  Screenshot", callback_data="gui_set_1"),
                 InlineKeyboardButton(f"{_g(2)}  Neon",       callback_data="gui_set_2")],
                [InlineKeyboardButton(f"{_g(3)}  Sigma",      callback_data="gui_set_3"),
                 InlineKeyboardButton(f"{_g(4)}  Minimal",    callback_data="gui_set_4")],
                [InlineKeyboardButton(f"{_g(5)}  Royal Gold", callback_data="gui_set_5")],
                [InlineKeyboardButton(f"⭐ {_g(6)}  TempNum", callback_data="gui_set_6"),
                 InlineKeyboardButton(f"⭐ {_g(7)}  Jack-X",  callback_data="gui_set_7")],
                [InlineKeyboardButton(f"⭐ {_g(8)}  Cyber",   callback_data="gui_set_8")],
                [InlineKeyboardButton("🔙  Back", callback_data="main_menu")],
            ]))
        return

    if data.startswith("gui_set_"):
        style = int(data.split("_")[-1])
        GUI_STYLE = style
        OTP_GUI_THEME = style - 1   # GUI style 1-8 → theme index 0-7
        save_config_key("OTP_GUI_THEME", OTP_GUI_THEME)
        save_config_key("GUI_STYLE", style)
        await query.answer(f"✅ GUI Style {style} activated!", show_alert=True)
        # Show preview
        bot_tag = _get_bot_tag()
        nd = f"92•{bot_tag.lstrip('@')[:9].upper()}•12345"
        preview = build_otp_msg(
            "✅ OTP RECEIVED", "1️⃣ First OTP", "491138",
            "Your code is 491138. Do not share.", "WS", "Hadi",
            "🇵🇰", "PK", "+92", "12345", for_group=False)
        await query.edit_message_text(
            f"🎨 <b>Style {style} Preview:</b>\n\n{preview}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙  Back to Styles", callback_data="pick_gui"),
                InlineKeyboardButton("✅  Keep This",      callback_data="main_menu"),
            ]]), parse_mode="HTML")
        return

    # ════════════════════════════════════════════════════════
    #  CREATE MY BOT FLOW
    # ════════════════════════════════════════════════════════
    if data=="create_bot_menu":
        await query.answer()
        bot_link = "https://t.me/CrackSMSReBot"
        await safe_edit(query,
            f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"  🤖 <b>Create Your Own OTP Bot</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"Launch your own branded OTP forwarding bot powered by our system.\n\n"
            f"<b>What you need:</b>\n"
            f"• A Telegram group (your bot must be admin)\n"
            f"• Bot token from @BotFather  <i>(optional — we can create)</i>\n"
            f"• A panel or we forward from main panels\n\n"
            f"<b>Features included:</b>\n"
            f"✅ All 8 premium OTP GUI themes\n"
            f"✅ Animated emojis + country flags\n"
            f"✅ Auto-delete messages after 15 min\n"
            f"✅ 200+ OTP regex patterns\n\n"
            f"👇 Choose an option:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅  I have a panel",    callback_data="cbot_have_panel"),
                 InlineKeyboardButton("❌  No panel needed",   callback_data="cbot_no_panel")],
                [InlineKeyboardButton("🔙  Back",              callback_data="main_menu")],
            ]))
        return

    if data=="cbot_no_panel":
        await query.answer()
        CREATE_BOT_STATES[uid] = {
            "step": "get_group_id",
            "has_panel": False,
            "uid": uid,
            "timestamp": datetime.now().isoformat(),
        }
        await safe_edit(query,
            "🤖 <b>Create Bot — Step 1/3</b>\n\n"
            "Send your Telegram <b>Group Chat ID</b>.\n\n"
            "To get it: add @userinfobot to your group, it will show the chat ID.\n"
            "It usually starts with <code>-100...</code>\n\n"
            "/cancel to abort.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙  Back", callback_data="create_bot_menu")]]))
        return

    if data=="cbot_have_panel":
        await query.answer()
        CREATE_BOT_STATES[uid] = {
            "step": "get_bot_name",
            "has_panel": True,
            "uid": uid,
            "timestamp": datetime.now().isoformat(),
        }
        await safe_edit(query,
            "🤖 <b>Create Bot — Step 1/9</b>\n\n"
            "Send your <b>Bot Name</b> (e.g. <i>My OTP Bot</i>):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙  Back", callback_data="create_bot_menu")]]))
        return

    if data.startswith("cbot_verify_"):
        group_id_str = data.split("_")[-1]
        if uid not in CREATE_BOT_STATES:
            await query.answer("Session expired. Start again.", show_alert=True); return
        await query.answer("⏳ Verifying…")
        try:
            test_msg = await context.bot.send_message(
                chat_id=int(group_id_str),
                text="✅ <b>Crack SMS Bot</b> verification check — I am admin here!",
                parse_mode="HTML")
            await context.bot.delete_message(chat_id=int(group_id_str), message_id=test_msg.message_id)
            CREATE_BOT_STATES[uid]["group_id"]  = group_id_str
            CREATE_BOT_STATES[uid]["step"]      = "confirmed"
            CREATE_BOT_STATES[uid]["user_name"] = update.effective_user.first_name
            # Submit request to super admins
            req_id = f"bot_{uid}_{int(datetime.now().timestamp())}"
            BOT_REQUESTS[req_id] = {
                "uid": uid,
                "group_id": group_id_str,
                "has_panel": False,
                "user_name": update.effective_user.first_name,
                "username": f"@{update.effective_user.username}" if update.effective_user.username else str(uid),
                "status": "pending",
                "req_id": req_id,
            }
            # Notify all super admins
            req_txt = (
                f"🆕 <b>New Bot Request</b>\n\n"
                f"👤 User: {html.escape(update.effective_user.first_name)} "
                f"(<code>{uid}</code>)\n"
                f"📱 Group: <code>{group_id_str}</code>\n"
                f"🔌 Panel: No panel (forward from main)\n\n"
                f"Approve or reject below:"
            )
            for admin_id in INITIAL_ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id, text=req_txt,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅  Approve", callback_data=f"approvebot_{req_id}"),
                             InlineKeyboardButton("❌  Reject",  callback_data=f"rejectbot_{req_id}")],
                        ]), parse_mode="HTML")
                except Exception:
                    pass
            await query.edit_message_text(
                "✅ <b>Verification Successful!</b>\n\n"
                "Your bot request has been submitted to the admins.\n"
                "You will receive a notification once approved!\n\n"
                f"📋 Request ID: <code>{req_id}</code>",
                parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(
                f"❌ <b>Verification Failed</b>\n\n"
                f"I could not send a message to group <code>{group_id_str}</code>.\n\n"
                f"<b>Please make sure:</b>\n"
                f"1. The group ID is correct\n"
                f"2. @{BOT_USERNAME} is an admin in that group\n\n"
                f"Error: <code>{html.escape(str(e))}</code>",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔁  Try Again", callback_data="cbot_no_panel"),
                    InlineKeyboardButton("🔙  Back",      callback_data="main_menu"),
                ]]), parse_mode="HTML")
        return

    # Approve/reject bot requests (super admins only)
    if data.startswith("approvebot_"):
        if not is_sup: await query.answer("Unauthorized", show_alert=True); return
        req_id = data[11:]
        if req_id not in BOT_REQUESTS:
            await query.answer("Request not found.", show_alert=True); return
        req = BOT_REQUESTS[req_id]
        req["status"] = "approved"
        await query.answer("✅ Approved!")
        await query.edit_message_text(
            f"✅ <b>Bot Request Approved</b>\n\n"
            f"👤 {html.escape(req['user_name'])} — <code>{req['uid']}</code>\n"
            f"📱 Group: <code>{req['group_id']}</code>",
            parse_mode="HTML")
        # Notify the user
        try:
            await context.bot.send_message(
                chat_id=req["uid"],
                text=(
                    f"🎉 <b>Your Bot Request is Approved!</b>\n\n"
                    f"Contact @NONEXPERTCODER to complete your bot setup.\n\n"
                    f"📋 Request ID: <code>{req_id}</code>\n"
                    f"📱 Group: <code>{req['group_id']}</code>"
                ),
                parse_mode="HTML")
        except Exception:
            pass
        return

    if data.startswith("rejectbot_"):
        if not is_sup: await query.answer("Unauthorized", show_alert=True); return
        req_id = data[10:]
        if req_id not in BOT_REQUESTS:
            await query.answer("Request not found.", show_alert=True); return
        req = BOT_REQUESTS.pop(req_id, {})
        await query.answer("❌ Rejected.")
        await query.edit_message_text(
            f"❌ <b>Bot Request Rejected</b>\n\n"
            f"👤 {html.escape(req.get('user_name','?'))} — <code>{req.get('uid','?')}</code>",
            parse_mode="HTML")
        try:
            await context.bot.send_message(
                chat_id=req.get("uid", 0),
                text="❌ <b>Your bot request was not approved at this time.</b>\n"
                     "Contact @NONEXPERTCODER for more info.",
                parse_mode="HTML")
        except Exception:
            pass
        return

    # ════════════════════════════════════════════════════════
    #  REQUIRED CHATS MANAGEMENT
    # ════════════════════════════════════════════════════════
    if data=="admin_req_chats":
        if not is_sup: await query.answer("Super admins only",show_alert=True); return
        await query.answer()
        lines = []
        for i, c in enumerate(REQUIRED_CHATS):
            lines.append(f"  <code>{i}</code>. {c['title']}  (<code>{c['id']}</code>)")
        txt = (
            "🚪 <b>Required Chats</b>\n\n"
            "Users must join <b>all</b> these before using the bot.\n\n"
            + ("\n".join(lines) if lines else "  <i>None configured</i>")
        )
        kb_rows = [[InlineKeyboardButton("➕  Add Chat/Channel", callback_data="req_chat_add")]]
        if REQUIRED_CHATS:
            for i in range(len(REQUIRED_CHATS)):
                kb_rows.append([InlineKeyboardButton(
                    f"🗑  Remove: {REQUIRED_CHATS[i]['title']}",
                    callback_data=f"req_chat_del_{i}")])
        kb_rows.append([InlineKeyboardButton("🔙  Back", callback_data="admin_settings")])
        await safe_edit(query, txt, reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    if data=="req_chat_add":
        if not is_sup: await query.answer("Super admins only",show_alert=True); return
        await query.answer()
        AWAITING_REQ_CHAT[uid] = True
        await safe_edit(query,
            "🚪 <b>Add Required Chat</b>\n\n"
            "Send the chat data in this format:\n\n"
            "<code>CHAT_ID | Title | https://t.me/invite_link</code>\n\n"
            "Example:\n"
            "<code>-1001234567890 | My Channel | https://t.me/mychannel</code>\n\n"
            "The bot must be a member of the chat.\n/cancel to abort.")
        return

    if data.startswith("req_chat_del_"):
        if not is_sup: await query.answer("Super admins only",show_alert=True); return
        idx = int(data.split("_")[-1])
        if 0 <= idx < len(REQUIRED_CHATS):
            removed = REQUIRED_CHATS.pop(idx)
            save_config_key("REQUIRED_CHATS", REQUIRED_CHATS)
            await query.answer(f"✅ Removed: {removed['title']}", show_alert=True)
        else:
            await query.answer("Invalid index", show_alert=True)
        # Refresh the required chats view
        lines = []
        for i, c in enumerate(REQUIRED_CHATS):
            lines.append(f"  <code>{i}</code>. {c['title']}  (<code>{c['id']}</code>)")
        txt = (
            "🚪 <b>Required Chats</b>\n\n"
            + ("\n".join(lines) if lines else "  <i>None configured</i>")
        )
        kb_rows = [[InlineKeyboardButton("➕  Add Chat/Channel", callback_data="req_chat_add")]]
        for i in range(len(REQUIRED_CHATS)):
            kb_rows.append([InlineKeyboardButton(
                f"🗑  Remove: {REQUIRED_CHATS[i]['title']}",
                callback_data=f"req_chat_del_{i}")])
        kb_rows.append([InlineKeyboardButton("🔙  Back", callback_data="admin_settings")])
        await safe_edit(query, txt, reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # ════════════════════════════════════════════════════════
    #  BROADCAST MENU
    # ════════════════════════════════════════════════════════
    if data=="admin_broadcast_menu":
        if not is_sup: await query.answer("Super admins only",show_alert=True); return
        await query.answer()
        toggle_lbl = "✅ ON" if AUTO_BROADCAST_ON else "❌ OFF"
        await safe_edit(query,
            "📢 <b>Broadcast Settings</b>\n\n"
            f"🔔 <b>Auto-broadcast on upload:</b> {toggle_lbl}\n\n"
            "Auto-broadcast sends a notification to all users and log groups "
            "whenever new numbers are uploaded.\n\n"
            "Manual broadcast lets you send any message to all users now.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔔  Auto-Broadcast: {toggle_lbl}",
                                      callback_data="toggle_auto_broadcast")],
                [InlineKeyboardButton("📣  Manual Broadcast Now", callback_data="admin_broadcast")],
                [InlineKeyboardButton("🔙  Back", callback_data="admin_settings")],
            ]))
        return

    if data=="toggle_auto_broadcast":
        if not is_sup: await query.answer("Super admins only",show_alert=True); return
        global AUTO_BROADCAST_ON
        AUTO_BROADCAST_ON = not AUTO_BROADCAST_ON
        save_config_key("AUTO_BROADCAST_ON", AUTO_BROADCAST_ON)
        await query.answer(f"Auto-broadcast {'enabled' if AUTO_BROADCAST_ON else 'disabled'}!")
        toggle_lbl = "✅ ON" if AUTO_BROADCAST_ON else "❌ OFF"
        await safe_edit(query,
            "📢 <b>Broadcast Settings</b>\n\n"
            f"🔔 <b>Auto-broadcast on upload:</b> {toggle_lbl}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔔  Auto-Broadcast: {toggle_lbl}",
                                      callback_data="toggle_auto_broadcast")],
                [InlineKeyboardButton("📣  Manual Broadcast Now", callback_data="admin_broadcast")],
                [InlineKeyboardButton("🔙  Back", callback_data="admin_settings")],
            ]))
        return

    if data=="cancel_action":
        PANEL_ADD_STATES.pop(uid,None); PANEL_EDIT_STATES.pop(uid,None)
        AWAITING_ADMIN_ID.pop(uid,None); AWAITING_LOG_ID.pop(uid,None); AWAITING_SUPER_ADMIN.pop(uid,None); AWAITING_REQ_CHAT.pop(uid,None)
        BOT_ADD_STATES.pop(uid,None)
        context.user_data["awaiting_broadcast"]=False
        context.user_data["awaiting_prefix"]=False
        context.user_data.pop("awaiting_link",None)
        context.user_data.pop("bot_setlink_bid",None)
        context.user_data.pop("bot_setlink_key",None)
        context.user_data.pop("bcast_all_bots",None)
        context.user_data.pop("bcast_single_bot",None)
        await query.edit_message_text("❌ Action cancelled.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin",callback_data="admin_home")]]))
        return

    await query.answer()

# ═══════════════════════════════════════════════════════════
#  STARTUP
# ═══════════════════════════════════════════════════════════
async def start_watcher_job(ctx):
    asyncio.create_task(active_watcher(ctx.application))

async def _delayed_child_bot_start():
    """
    Start child bots 5 minutes after the main bot fully initialises.

    Why 5 minutes:
      The main bot spends the first 60-70 seconds doing initial panel logins
      (14 panels × ~5s each).  During that time RAM is at peak.  The old 90s
      delay started child bots while the main bot was still logging in and at
      peak memory, triggering the OOM kill.

      At 5 minutes the main bot is fully settled: all logins done, GC has run,
      RAM is at steady-state (~80-100 MB).  The child bot then has room to
      load its own imports without pushing the server over the limit.

    Staggering:
      Each child bot is started one at a time with a 3-minute gap between
      them so their import spikes never overlap.
    """
    await asyncio.sleep(300)   # 5 minutes — main bot fully settled by then
    logger.info("🤖 Starting child bots (staggered to avoid OOM)…")

    reg = bm.load_registry()
    bots_to_start = [
        (bid, info) for bid, info in reg.items()
        if info.get("status") == "running"   # only those that were running before shutdown
    ]

    if not bots_to_start:
        logger.info("🤖 No child bots marked as running — nothing to auto-restore")
        return

    for i, (bid, info) in enumerate(bots_to_start):
        ok, msg = bm.start_bot(bid)
        logger.info(f"{'▶️' if ok else '❌'} Child bot \"{info.get('name',bid)}\": {msg}")
        if i < len(bots_to_start) - 1:
            logger.info(f"   ⏳ Waiting 3 minutes before starting next child bot…")
            await asyncio.sleep(180)   # 3-minute gap between each child bot

async def post_init(application):
    global app; app = application
    await db.init_db()
    await init_panels_table()
    await migrate_panels_table()
    await init_permissions_table()
    await load_panels_from_dex_to_db()
    await refresh_panels_from_db()
    await start_ivas_workers()
    if application.job_queue:
        application.job_queue.run_once(start_watcher_job, 10)
    else:
        asyncio.create_task(active_watcher(application))
    # Child bots are started AFTER a delay — not immediately — to prevent
    # the OOM-kill caused by two Python processes loading simultaneously.
    if not IS_CHILD_BOT:
        asyncio.create_task(_delayed_child_bot_start())
    logger.info(f"✅ Bot ready. Engine starts in 10s. IS_CHILD_BOT={IS_CHILD_BOT}")

if __name__=="__main__":
    PROCESSED_MESSAGES=init_seen_db()
    application=(ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build())
    application.add_handler(CommandHandler("start",         cmd_start))
    application.add_handler(CommandHandler("admin",         cmd_admin))
    application.add_handler(CommandHandler("addadmin",      cmd_add_admin))
    application.add_handler(CommandHandler("removeadmin",   cmd_rm_admin))
    application.add_handler(CommandHandler("listadmins",    cmd_list_admins))
    application.add_handler(CommandHandler("addlogchat",    cmd_add_log))
    application.add_handler(CommandHandler("removelogchat", cmd_rm_log))
    application.add_handler(CommandHandler("listlogchats",  cmd_list_logs))
    application.add_handler(CommandHandler("dox",           cmd_dox))
    application.add_handler(CommandHandler("test1",         cmd_test1))
    application.add_handler(CommandHandler("send1",         cmd_send1))
    application.add_handler(CommandHandler("otpfor",        cmd_otpfor))
    application.add_handler(CommandHandler("groups",        cmd_groups))
    application.add_handler(CommandHandler("addgroup",      cmd_addgrp))
    application.add_handler(CommandHandler("removegroup",   cmd_rmgrp))
    application.add_handler(CommandHandler("set_channel",   cmd_set_channel))
    application.add_handler(CommandHandler("set_otpgroup",  cmd_set_otpgroup))
    application.add_handler(CommandHandler("set_numberbot", cmd_set_numbot))
    application.add_handler(CommandHandler("bots",          cmd_bots))
    application.add_handler(CommandHandler("startbot",      cmd_startbot))
    application.add_handler(CommandHandler("stopbot",       cmd_stopbot))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.MimeType("text/plain"), handle_document))
    application.add_handler(CallbackQueryHandler(callback_handler))

    # ── Global error handler ──────────────────────────────────────
    # Without this, any unhandled exception in a PTB callback prints
    # "No error handlers are registered, logging exception" and the
    # traceback never reaches our logger properly.
    async def ptb_error_handler(update, context):
        logger.error(f"❌ PTB unhandled exception: {context.error}", exc_info=context.error)
        # Optionally notify super admins
        for admin_id in INITIAL_ADMIN_IDS:
            try:
                err_txt = str(context.error)[:300]
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ <b>Bot Error</b>\n<code>{html.escape(err_txt)}</code>",
                    parse_mode="HTML")
            except Exception:
                pass

    application.add_error_handler(ptb_error_handler)
    application.run_polling(drop_pending_updates=True)