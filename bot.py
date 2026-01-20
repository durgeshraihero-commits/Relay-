"""
Premium Information Bot - Professional Edition
Smart cascading search, txt/json support, premium UI
"""

import os
import sys
import re
import json
import time
import uuid
import logging
import asyncio
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from aiohttp import web
from telethon import TelegramClient, events, Button
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

# ================== BASIC CONFIG ==================

PORT = int(os.getenv("PORT", "10000"))

BOT_SESSION_FILE = "bot_session.session"
BOT_API_ID = int(os.getenv("API_ID", "0"))
BOT_API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

USER_SESSION_FILE = "relay_session.session"
USER_API_ID = int(os.getenv("USER_API_ID", "0"))
USER_API_HASH = os.getenv("USER_API_HASH", "").strip()
USER_PHONE = os.getenv("USER_PHONE", "").strip()

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DBNAME = "tg_bot_db"

WEBSITE = "https://relay-wzlz.onrender.com"

BOT_FOOTER = "Powered by darkboxes_bot\nDev: @darkboxesAdmin"

SEARCH_TIMEOUT_PER_GROUP = 15   # seconds per group
FETCH_WAIT_TIME = 2             # seconds before reading reply

REFERRAL_REWARD = 2
NEW_USER_CREDITS = 2

# ================== LOGGING ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
logger = logging.getLogger("premium_bot")

# ================== CONFIG VALIDATION ==================

def validate_config() -> bool:
    errors = []
    if BOT_API_ID == 0:
        errors.append("API_ID not set")
    if not BOT_API_HASH:
        errors.append("API_HASH not set")
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN not set")
    if ADMIN_USER_ID == 0:
        errors.append("ADMIN_USER_ID not set")
    if not MONGODB_URI:
        errors.append("MONGODB_URI not set")

    if errors:
        logger.error("Configuration errors:")
        for e in errors:
            logger.error(" - %s", e)
        return False
    return True

if not validate_config():
    sys.exit(1)

USE_USER_ACCOUNT = USER_API_ID != 0 and USER_API_HASH and USER_PHONE

# ================== GROUPS CONFIG ==================

DESTINATION_GROUPS = [
    {"name": "Main Group",      "identifier": -1003596998816, "entity": None, "order": 1},
    {"name": "Backup Group 2",  "identifier": "darkboxesv3",  "entity": None, "order": 2},
    {"name": "Backup Group 3",  "identifier": "nex_chats",    "entity": None, "order": 3},
]

# ================== SEARCH TYPES ==================

SEARCH_COMMANDS = {
    "phone":   {"name": "📱 Phone Number",  "command": "/num",       "desc": "Get info from phone number"},
    "vnum":    {"name": "🚗 Vehicle Number","command": "/vnum",      "desc": "Get owner from vehicle number"},
    "tg":      {"name": "📲 Telegram User", "command": "/tg",        "desc": "Get phone from Telegram username"},
    "imei":    {"name": "📱 IMEI Number",   "command": "/imei",      "desc": "Get device info from IMEI"},
    "gst":     {"name": "🏢 GST Number",    "command": "/gst",       "desc": "Get business info from GST"},
    "aadhar":  {"name": "🆔 Aadhar Number", "command": "/aadhar",    "desc": "Get info from Aadhar"},
    "email":   {"name": "📧 Email Address", "command": "/email",     "desc": "Search email details"},
    "upi":     {"name": "💳 UPI ID",        "command": "/upiinfo",   "desc": "Get info from UPI ID"},
    "insta":   {"name": "📷 Instagram",     "command": "/insta",     "desc": "Search Instagram user"},
    "family":  {"name": "👨‍👩‍👧‍👦 Family Info","command": "/familyinfo","desc": "Get family members info"},
}

PLANS = {
    "plan_5": {
        "name": "🔍 5 Searches",
        "searches": 5,
        "price": 100,
        "days": None,
        "desc": "Perfect for testing the service"
    },
    "plan_15": {
        "name": "🔎 15 Searches",
        "searches": 15,
        "price": 200,
        "days": None,
        "desc": "Best for regular users"
    },
    "plan_month": {
        "name": "⚡ Unlimited (30 Days)",
        "searches": -1,
        "price": 1000,
        "days": 30,
        "desc": "Unlimited usage for 30 days"
    }
}

# ================== DATABASE ==================

mongo_client = None
db = None
users_col = None
payments_col = None
searches_col = None
admins_col = None

def init_mongo() -> bool:
    global mongo_client, db, users_col, payments_col, searches_col, admins_col
    try:
        logger.info("🔌 Connecting to MongoDB...")
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]

        users_col = db["users"]
        payments_col = db["payments"]
        searches_col = db["searches"]
        admins_col = db["admins"]

        users_col.create_index([("user_id", 1)], unique=True)
        payments_col.create_index([("user_id", 1)])

        logger.info("✅ MongoDB connected")
        return True
    except ServerSelectionTimeoutError:
        logger.error("❌ MongoDB timeout - check URI")
        return False
    except Exception as e:
        logger.exception("MongoDB error: %s", e)
        return False

# ================== ADMIN FUNCTIONS ==================

async def is_admin(user_id: int) -> bool:
    if user_id == ADMIN_USER_ID:
        return True
    try:
        admin = await asyncio.get_running_loop().run_in_executor(
            None, admins_col.find_one, {"user_id": user_id}
        )
        return admin is not None
    except Exception:
        return False

async def add_admin(user_id: int) -> bool:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: admins_col.update_one(
                {"user_id": user_id},
                {"$set": {"user_id": user_id,
                          "added_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            ),
        )
        return True
    except Exception:
        return False

async def get_admin_stats() -> Dict:
    try:
        loop = asyncio.get_running_loop()
        total_users = await loop.run_in_executor(None, users_col.count_documents, {})
        total_searches = await loop.run_in_executor(None, searches_col.count_documents, {})
        premium_users = await loop.run_in_executor(
            None, users_col.count_documents, {"plan": {"$ne": "free"}}
        )
        approved_payments = await loop.run_in_executor(
            None, payments_col.count_documents, {"status": "approved"}
        )

        total_revenue = 0
        try:
            payments = await loop.run_in_executor(
                None, lambda: list(payments_col.find({"status": "approved"}))
            )
            total_revenue = sum(p.get("amount", 0) for p in payments)
        except Exception:
            pass

        return {
            "total_users": total_users,
            "premium_users": premium_users,
            "total_searches": total_searches,
            "approved_payments": approved_payments,
            "total_revenue": total_revenue,
        }
    except Exception:
        return {}

# ================== USER FUNCTIONS ==================

async def get_user(user_id: int) -> Optional[Dict]:
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, users_col.find_one, {"user_id": user_id}
        )
    except Exception:
        return None

async def create_user(user_id: int, username: str = None, first_name: str = None) -> Optional[Dict]:
    try:
        referral_code = secrets.token_urlsafe(6).upper()
        doc = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "plan": "free",
            "searches_remaining": NEW_USER_CREDITS,
            "plan_expiry": None,
            "total_searches": 0,
            "banned": False,
            "referral_code": referral_code,
            "referred_by": None,
        }
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: users_col.update_one(
                {"user_id": user_id}, {"$setOnInsert": doc}, upsert=True
            ),
        )
        return await get_user(user_id)
    except Exception:
        return None

async def update_user_plan(user_id: int, plan: str, searches: int, days: int = None) -> bool:
    try:
        update_doc = {"plan": plan, "searches_remaining": searches}
        if days:
            update_doc["plan_expiry"] = (
                datetime.now(timezone.utc) + timedelta(days=days)
            ).isoformat()

        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: users_col.update_one({"user_id": user_id}, {"$set": update_doc}),
        )
        return True
    except Exception:
        return False

async def decrement_search(user_id: int) -> bool:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: users_col.update_one(
                {"user_id": user_id},
                {"$inc": {"searches_remaining": -1, "total_searches": 1}},
            ),
        )
        return True
    except Exception:
        return False

async def log_search(user_id: int, search_type: str, query: str) -> bool:
    try:
        doc = {
            "user_id": user_id,
            "search_type": search_type,
            "query": query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await asyncio.get_running_loop().run_in_executor(
            None, searches_col.insert_one, doc
        )
        return True
    except Exception:
        return False

async def create_payment(user_id: int, plan: str, amount: int) -> Optional[str]:
    try:
        payment_id = uuid.uuid4().hex
        doc = {
            "payment_id": payment_id,
            "user_id": user_id,
            "plan": plan,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await asyncio.get_running_loop().run_in_executor(
            None, payments_col.insert_one, doc
        )
        return payment_id
    except Exception:
        return None

async def approve_payment_record(payment_id: str) -> bool:
    """
    Approve payment and update user plan.
    """
    try:
        loop = asyncio.get_running_loop()
        payment = await loop.run_in_executor(
            None, payments_col.find_one, {"payment_id": payment_id}
        )
        if not payment:
            return False

        plan_key = payment["plan"]
        plan = PLANS[plan_key]
        user_id = payment["user_id"]

        if plan["searches"] == -1:
            await update_user_plan(user_id, "premium", 999999, plan["days"])
        else:
            user_doc = await get_user(user_id)
            current = user_doc.get("searches_remaining", 0)
            await update_user_plan(
                user_id, "premium", current + plan["searches"], user_doc.get("plan_expiry")
            )

        await loop.run_in_executor(
            None,
            lambda: payments_col.update_one(
                {"payment_id": payment_id},
                {
                    "$set": {
                        "status": "approved",
                        "approved_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            ),
        )

        try:
            await bot_client.send_message(
                user_id,
                f"✅ Payment Approved!\n\nPlan: {plan['name']}\nAmount: ₹{plan['price']}\n\n{BOT_FOOTER}",
            )
        except Exception:
            pass

        return True
    except Exception:
        return False

# ================== TEXT HELPERS ==================

def is_processing_message(text: str) -> bool:
    if not text or len(text.strip()) < 8:
        return False
    keywords = [
        "processing",
        "please wait",
        "searching",
        "fetching",
        "loading",
        "hold on",
        "wait",
        "trying",
        "checking",
    ]
    return any(k in text.lower() for k in keywords)

def is_no_info_message(text: str) -> bool:
    if not text:
        return False
    keywords = [
        "no info",
        "not found",
        "no data",
        "no result",
        "invalid",
        "not available",
        "no record",
        "doesn't exist",
        "no details found",
    ]
    return any(k in text.lower() for k in keywords)

def has_useful_data(text: str) -> bool:
    if not text or len(text.strip()) < 20:
        return False
    keywords = [
        "name",
        "mobile",
        "phone",
        "address",
        "email",
        "number",
        "owner",
        "father",
        "mother",
        "son",
        "daughter",
        "city",
        "state",
        "country",
        "registered",
        "status",
        "device",
        "imei",
        "gst",
        "aadhar",
        "upi",
        "family",
    ]
    return any(k in text.lower() for k in keywords)

def filter_links(text: str) -> str:
    if not text:
        return text
    patterns = [
        r"https?://[^\s]+",
        r"www\.[^\s]+",
        r"t\.me/[^\s]+",
        r"tg://[^\s]+",
        r"@[a-zA-Z0-9_]{3,}",
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def clean_file(text: str) -> str:
    """
    Clean raw text from .txt/.json reports.
    Removes URLs, @usernames, hashtags, and collapses empty lines.
    """
    if not text:
        return ""

    text = re.sub(r"https?://\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"www\.\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#\w+", "", text)

    lines = [line.strip() for line in text.splitlines()]
    cleaned_lines = []
    last_blank = False
    for line in lines:
        if not line:
            if not last_blank:
                cleaned_lines.append("")
            last_blank = True
        else:
            cleaned_lines.append(line)
            last_blank = False

    return "\n".join(cleaned_lines).strip()

def format_result(text: str, search_type: str) -> str:
    if not text:
        return ""
    cleaned = filter_links(text)
    header_name = SEARCH_COMMANDS.get(search_type, {}).get("name", "Result")
    header = f"✅ Search Result - {header_name}\n\n"
    body = cleaned
    footer = f"\n\n{'─'*30}\n{BOT_FOOTER}"
    return header + body + footer

# ================== STATE ==================

user_states: Dict[int, Dict] = {}
pending_searches: Dict[str, Dict] = {}

# ================== CLIENTS ==================

bot_client = TelegramClient(BOT_SESSION_FILE, BOT_API_ID, BOT_API_HASH)
user_client = (
    TelegramClient(USER_SESSION_FILE, USER_API_ID, USER_API_HASH)
    if USE_USER_ACCOUNT
    else bot_client
)

# ================== CASCADING SEARCH ==================

async def perform_cascading_search(search_type: str, query: str, user_id: int = None) -> Dict:
    if search_type not in SEARCH_COMMANDS:
        return {"success": False, "error": "❌ Invalid search type"}

    command = SEARCH_COMMANDS[search_type]["command"]
    message = f"{command} {query}"

    logger.info(f"🔍 Starting cascading search: {search_type} = {query}")

    for attempt, group_config in enumerate(
        sorted(DESTINATION_GROUPS, key=lambda x: x["order"]), start=1
    ):
        group_entity = group_config.get("entity")
        if not group_entity:
            logger.warning("Group %s not resolved", group_config["name"])
            continue

        try:
            sent_msg = await user_client.send_message(group_entity, message)
            logger.info(
                "📤 [%d/3] Sent to %s: %s",
                attempt,
                group_config["name"],
                message,
            )

            future = asyncio.get_running_loop().create_future()
            search_id = f"{sent_msg.id}_{int(time.time() * 1000)}_{group_config['order']}"

            pending_searches[search_id] = {
                "future": future,
                "user_id": user_id,
                "query": query,
                "search_type": search_type,
                "timestamp": time.time(),
                "message_id": sent_msg.id,
                "chat_entity": group_entity,
                "group_name": group_config["name"],
                "got_processing": False,
            }

            try:
                result_text = await asyncio.wait_for(
                    future, timeout=SEARCH_TIMEOUT_PER_GROUP
                )
                logger.info("✅ Got result from %s", group_config["name"])

                if not isinstance(result_text, str):
                    result_text = str(result_text)

                if (
                    result_text
                    and len(result_text.strip()) > 20
                    and not is_no_info_message(result_text)
                ):
                    await log_search(user_id, search_type, query)
                    formatted = format_result(result_text, search_type)
                    pending_searches.pop(search_id, None)
                    return {
                        "success": True,
                        "result": formatted,
                        "source": group_config["name"],
                    }

                pending_searches.pop(search_id, None)
                logger.info(
                    "⚠️ Result from %s not useful, trying next group",
                    group_config["name"],
                )
                continue

            except asyncio.TimeoutError:
                pending_searches.pop(search_id, None)
                logger.info("⏱️ Timeout from %s (%ds)", group_config["name"], SEARCH_TIMEOUT_PER_GROUP)
                continue

        except Exception as e:
            logger.exception("Search error in %s: %s", group_config["name"], e)
            pending_searches.pop(search_id, None)
            continue

    return {
        "success": False,
        "error": "❌ No results from any group.\n\nTry another query or format.",
    }

# ================== KEYBOARDS ==================

def main_menu():
    buttons = []
    for key, cmd in SEARCH_COMMANDS.items():
        buttons.append([Button.inline(cmd["name"], f"search_{key}")])

    buttons.extend(
        [
            [Button.inline("👤 My Profile", "my_profile")],
            [Button.inline("💰 Premium Plans", "plans_menu")],
            [Button.inline("📞 Support", "support")],
        ]
    )
    return buttons

def admin_menu():
    return [
        [Button.inline("📊 Statistics", "admin_stats")],
        [Button.inline("💳 Payment Requests", "admin_payments")],
        [Button.inline("🔙 Back to Main", "back_main")],
    ]

def plans_menu():
    buttons = []
    for key, p in PLANS.items():
        buttons.append(
            [Button.inline(f"{p['name']} • ₹{p['price']}", f"buy_{key}")]
        )
    buttons.append([Button.inline("❌ Cancel", "cancel")])
    return buttons

# ================== COMMAND HANDLERS ==================

@bot_client.on(events.NewMessage(pattern=r"/start"))
async def start_handler(event):
    user = await event.get_sender()
    user_id = user.id

    user_doc = await get_user(user_id)
    if not user_doc:
        await create_user(user_id, user.username, user.first_name)
        user_doc = await get_user(user_id)

    if user_doc.get("banned"):
        await event.respond(
            "❌ Access Denied\n\nYour account has been suspended.\nContact @darkboxesAdmin if you believe this is a mistake."
        )
        return

    if await is_admin(user_id):
        stats = await get_admin_stats()
        await event.respond(
            "👮 Admin Dashboard\n\n"
            f"👥 Users: {stats.get('total_users', 0)}\n"
            f"💎 Premium: {stats.get('premium_users', 0)}\n"
            f"🔍 Searches: {stats.get('total_searches', 0)}\n"
            f"💰 Revenue: ₹{stats.get('total_revenue', 0)}\n\n"
            f"{BOT_FOOTER}",
            buttons=admin_menu(),
        )
        return

    await event.respond(
        "👋 Welcome to the Premium Info Bot!\n\n"
        f"📊 Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Credits: {user_doc.get('searches_remaining', 0)}\n"
        f"📈 Total Searches: {user_doc.get('total_searches', 0)}\n\n"
        "Choose a search type below:",
        buttons=main_menu(),
    )

@bot_client.on(events.CallbackQuery(pattern=r"^search_(.+)"))
async def search_handler(event):
    user_id = event.sender_id
    search_type = event.data.decode().split("_", 1)[1]

    user_doc = await get_user(user_id)
    if user_doc.get("banned"):
        await event.answer("❌ You are banned", alert=True)
        return

    if not await is_admin(user_id) and user_doc.get("searches_remaining", 0) <= 0:
        await event.edit(
            "❌ No credits remaining.\n\nUpgrade to a premium plan:",
            buttons=plans_menu(),
        )
        return

    cmd = SEARCH_COMMANDS[search_type]
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}

    await event.edit(
        f"{cmd['name']}\n\n"
        f"{cmd['desc']}\n\n"
        "Send your query below.\n\n"
        "Example: 9876543210",
        buttons=[[Button.inline("❌ Cancel", "cancel")]],
    )

@bot_client.on(events.CallbackQuery(pattern=r"^buy_(.+)"))
async def buy_handler(event):
    user_id = event.sender_id
    plan_key = event.data.decode().split("_", 1)[1]

    if plan_key not in PLANS:
        await event.answer("Invalid plan", alert=True)
        return

    plan = PLANS[plan_key]
    payment_id = await create_payment(user_id, plan_key, plan["price"])
    if not payment_id:
        await event.answer("Error creating payment", alert=True)
        return

    user_states[user_id] = {
        "action": "awaiting_payment",
        "payment_id": payment_id,
        "plan": plan_key,
    }

    benefit = (
        f"Unlimited searches for {plan['days']} days"
        if plan["searches"] == -1
        else f"{plan['searches']} searches"
    )

    await event.edit(
        "💳 Payment Details\n\n"
        f"Plan: {plan['name']}\n"
        f"Benefit: {benefit}\n"
        f"Amount: ₹{plan['price']}\n\n"
        f"Payment ID: `{payment_id}`\n\n"
        "Send your payment screenshot here.\n"
        "Admin will approve it shortly.",
        parse_mode="md",
        buttons=[[Button.inline("❌ Cancel", "cancel")]],
    )

@bot_client.on(events.CallbackQuery(pattern="^plans_menu$"))
async def plans_menu_handler(event):
    message = "💰 Premium Plans\n\n"
    for _, p in PLANS.items():
        if p["searches"] == -1:
            searches = f"Unlimited ({p['days']} days)"
        else:
            searches = f"{p['searches']} searches"
        message += f"{p['name']}\n- {searches}\n- ₹{p['price']}\n- {p['desc']}\n\n"

    await event.edit(message, buttons=plans_menu())

@bot_client.on(events.CallbackQuery(pattern="^my_profile$"))
async def my_profile_handler(event):
    user_doc = await get_user(event.sender_id)
    admin = await is_admin(event.sender_id)

    message = (
        "👤 My Profile\n\n"
        f"Name: {user_doc.get('first_name', 'N/A')}\n"
        f"User ID: {event.sender_id}\n"
        f"Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"Credits: {user_doc.get('searches_remaining', 0)}\n"
        f"Total Searches: {user_doc.get('total_searches', 0)}\n"
        f"Joined: {user_doc.get('joined_at', '')[:10]}\n"
        f"Role: {'Admin' if admin else 'User'}\n\n"
        f"{BOT_FOOTER}"
    )

    await event.edit(message, buttons=[[Button.inline("🔙 Back", "back_main")]])

@bot_client.on(events.CallbackQuery(pattern="^support$"))
async def support_handler(event):
    await event.edit(
        "📞 Support\n\n"
        "Admin: @darkboxesAdmin\n"
        f"Website: {WEBSITE}\n\n"
        "For payment or account issues, send your User ID and details.",
        buttons=[[Button.inline("🔙 Back", "back_main")]],
    )

@bot_client.on(events.CallbackQuery(pattern="^admin_stats$"))
async def admin_stats_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("No access", alert=True)
        return

    stats = await get_admin_stats()
    message = (
        "📊 Statistics\n\n"
        f"Users: {stats.get('total_users', 0)}\n"
        f"Premium: {stats.get('premium_users', 0)}\n"
        f"Searches: {stats.get('total_searches', 0)}\n"
        f"Approved Payments: {stats.get('approved_payments', 0)}\n"
        f"Revenue: ₹{stats.get('total_revenue', 0)}"
    )
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "admin_menu")]])

@bot_client.on(events.CallbackQuery(pattern="^admin_payments$"))
async def admin_payments_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("No access", alert=True)
        return
    try:
        pending = list(payments_col.find({"status": "pending"}).limit(10))
        if not pending:
            await event.edit(
                "✅ No pending payments",
                buttons=[[Button.inline("🔙 Back", "admin_menu")]],
            )
            return

        message = "💳 Pending Payments\n\n"
        buttons = []
        for p in pending:
            plan = PLANS.get(p["plan"], {})
            message += (
                f"User: {p['user_id']}\n"
                f"Plan: {plan.get('name', 'Unknown')}\n"
                f"Amount: ₹{p['amount']}\n"
                f"ID: {p['payment_id'][:8]}...\n\n"
            )
            buttons.append(
                [
                    Button.inline("✅ Approve", f"approve_{p['payment_id']}"),
                    Button.inline("❌ Reject", f"reject_{p['payment_id']}"),
                ]
            )

        buttons.append([Button.inline("🔙 Back", "admin_menu")])
        await event.edit(message, buttons=buttons)
    except Exception:
        await event.answer("Error loading payments", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r"^approve_(.+)"))
async def approve_payment_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("No access", alert=True)
        return

    payment_id = event.data.decode().split("_", 1)[1]
    if await approve_payment_record(payment_id):
        await event.answer("Payment approved", alert=True)
    else:
        await event.answer("Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r"^reject_(.+)"))
async def reject_payment_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("No access", alert=True)
        return

    payment_id = event.data.decode().split("_", 1)[1]
    try:
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: payments_col.update_one(
                {"payment_id": payment_id}, {"$set": {"status": "rejected"}}
            ),
        )
        await event.answer("Payment rejected", alert=True)
    except Exception:
        await event.answer("Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern="^admin_menu$"))
async def admin_menu_handler(event):
    if not await is_admin(event.sender_id):
        return
    await event.edit("Admin Panel", buttons=admin_menu())

@bot_client.on(events.CallbackQuery(pattern="^cancel$"))
async def cancel_handler(event):
    user_states.pop(event.sender_id, None)
    await event.edit("❌ Cancelled", buttons=main_menu())

@bot_client.on(events.CallbackQuery(pattern="^back_main$"))
async def back_main_handler(event):
    user_doc = await get_user(event.sender_id)
    await event.edit(
        "Main Menu\n\n"
        f"Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"Credits: {user_doc.get('searches_remaining', 0)}",
        buttons=main_menu(),
    )

# ================== PRIVATE MESSAGE HANDLER ==================

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and e.text and not e.text.startswith("/")))
async def private_message_handler(event):
    user_id = event.sender_id
    if user_id not in user_states:
        return

    state = user_states[user_id]

    # search input
    if state.get("action") == "awaiting_input":
        search_type = state["type"]
        query = event.text.strip()
        if not query:
            await event.respond("Please send a valid query.")
            return

        status = await event.respond("🔍 Searching... Please wait 10–30 seconds.")
        result = await perform_cascading_search(search_type, query, user_id)

        try:
            await status.delete()
        except Exception:
            pass

        if result["success"]:
            await event.respond(result["result"])
            if not await is_admin(user_id):
                await decrement_search(user_id)
        else:
            await event.respond(result["error"])

        user_states.pop(user_id, None)
        return

    # payment screenshot
    if state.get("action") == "awaiting_payment":
        if not event.photo:
            await event.respond("Please send a screenshot image.")
            return

        payment_id = state["payment_id"]
        plan_key = state["plan"]
        plan = PLANS.get(plan_key, {})

        # forward screenshot to admin
        try:
            await bot_client.send_file(
                ADMIN_USER_ID,
                event.photo,
                caption=(
                    f"💳 New Payment Screenshot\n\n"
                    f"User: {user_id}\n"
                    f"Plan: {plan.get('name', plan_key)}\n"
                    f"Amount: ₹{plan.get('price', '?')}\n"
                    f"Payment ID: {payment_id}"
                ),
            )
        except Exception:
            pass

        await event.respond(
            "✅ Screenshot received.\n\nAdmin will verify your payment soon."
        )
        user_states.pop(user_id, None)
        return

# ================== GROUP REPLY HANDLER ==================

@user_client.on(events.NewMessage())
async def handle_group_replies(event):
    """
    Handle all messages from destination groups.
    - Only accept direct replies to our command message.
    - If reply is 'searching / processing' -> wait for next.
    - If reply is .txt/.json -> download & parse, return text.
    - If reply is text with useful data -> return text.
    """
    message = event.message
    now = time.time()

    matched_search = None
    matched_key = None

    # Match to pending search
    for search_id, info in list(pending_searches.items()):
        if info["future"].done():
            continue
        if now - info.get("timestamp", now) > SEARCH_TIMEOUT_PER_GROUP * 5:
            continue

        if message.reply_to and message.reply_to.reply_to_msg_id == info.get("message_id"):
            matched_search = info
            matched_key = search_id
            break

    if not matched_search:
        return

    text = message.text or message.raw_text
    has_file = message.file is not None

    if not text and not has_file:
        return

    await asyncio.sleep(FETCH_WAIT_TIME)

    # processing messages
    if text and not has_file and is_processing_message(text):
        logger.info(
            "⏳ Processing message from group, waiting for real result: %r", text[:60]
        )
        matched_search["got_processing"] = True
        return

    # no-info messages
    if text and not has_file and is_no_info_message(text):
        logger.info("❌ No-info message from group")
        if not matched_search["future"].done():
            try:
                matched_search["future"].set_exception(
                    TimeoutError("No info from this group")
                )
            except Exception:
                pass
        pending_searches.pop(matched_key, None)
        return

    # files: txt/json
    if has_file:
        file_name = (message.file.name or "").lower()
        mime_type = (message.file.mime_type or "").lower()

        is_text_file = file_name.endswith(".txt") or mime_type.startswith("text/")
        is_json_file = file_name.endswith(".json") or "json" in mime_type

        if is_text_file or is_json_file:
            logger.info("📥 Downloading result file from group: %s", file_name or mime_type)
            try:
                file_bytes = await message.download_media(bytes)
                try:
                    file_text = file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        file_text = file_bytes.decode("latin-1")
                    except Exception:
                        file_text = file_bytes.decode("utf-8", errors="ignore")

                if is_json_file:
                    try:
                        parsed = json.loads(file_text)
                        file_text = json.dumps(parsed, indent=2, ensure_ascii=False)
                    except Exception:
                        pass

                cleaned = clean_file(file_text)
                cleaned = filter_links(cleaned)
                cleaned = re.sub(
                    r"Designed\s*&\s*Powered.*", "", cleaned, flags=re.IGNORECASE
                )
                cleaned = re.sub(
                    r"Powered by .*", "", cleaned, flags=re.IGNORECASE
                )
                cleaned = cleaned.strip()

                if cleaned and len(cleaned) > 15:
                    if not matched_search["future"].done():
                        logger.info("✅ Delivering text extracted from file")
                        matched_search["future"].set_result(cleaned)
                        pending_searches.pop(matched_key, None)
                        return
                else:
                    logger.info("⚠️ File content too short after cleaning")
            except Exception as e:
                logger.error("Error processing file result: %s", e)

            if not matched_search["future"].done():
                try:
                    matched_search["future"].set_exception(
                        TimeoutError("Invalid file result")
                    )
                except Exception:
                    pass
            pending_searches.pop(matched_key, None)
            return

        logger.info("📁 Non-text file received; ignoring")
        return

    # plain text
    if text and not has_file:
        if len(text.strip()) < 15:
            logger.info("Ignoring too-short text reply")
            return

        cleaned_text = filter_links(text)
        cleaned_text = re.sub(
            r"Designed\s*&\s*Powered.*", "", cleaned_text, flags=re.IGNORECASE
        )
        cleaned_text = re.sub(
            r"Powered by .*", "", cleaned_text, flags=re.IGNORECASE
        )
        cleaned_text = cleaned_text.strip()
        if not cleaned_text:
            return

        if not matched_search["future"].done():
            logger.info("✅ Delivering plain text result from group")
            matched_search["future"].set_result(cleaned_text)
            pending_searches.pop(matched_key, None)

# ================== CLEANUP TASK ==================

async def cleanup_pending():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        for sid in list(pending_searches.keys()):
            info = pending_searches[sid]
            if now - info.get("timestamp", now) > SEARCH_TIMEOUT_PER_GROUP * 5:
                if not info["future"].done():
                    try:
                        info["future"].set_exception(TimeoutError())
                    except Exception:
                        pass
                pending_searches.pop(sid, None)

# ================== WEB SERVER ==================

async def start_web():
    app = web.Application()

    async def health(request):
        return web.Response(text="OK")

    app.router.add_get("/health", health)
    app.router.add_get("/", lambda r: web.Response(text="Premium Info Bot", content_type="text/plain"))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("🌐 Web server on port %s", PORT)

# ================== MAIN ==================

async def start_bot():
    try:
        logger.info("🤖 Starting bot...")
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot connected")

        me = await bot_client.get_me()
        logger.info("Bot: @%s", me.username)

        if USE_USER_ACCOUNT:
            if not user_client.is_connected():
                await user_client.connect()
            if not await user_client.is_user_authorized():
                raise RuntimeError("User account not authorized")
            logger.info("✅ User account ready")

        logger.info("📡 Resolving groups...")
        for group in DESTINATION_GROUPS:
            try:
                group["entity"] = await user_client.get_entity(group["identifier"])
                logger.info("✅ %s (Order %d)", group["name"], group["order"])
            except Exception as e:
                logger.warning("Failed to resolve %s: %s", group["name"], e)

        if not init_mongo():
            logger.error("MongoDB connection failed, exiting")
            return

        await add_admin(ADMIN_USER_ID)

        asyncio.create_task(cleanup_pending())
        asyncio.create_task(start_web())

        logger.info("=" * 60)
        logger.info("🚀 PREMIUM BOT FULLY OPERATIONAL!")
        logger.info("=" * 60)

        await asyncio.Event().wait()
    except Exception as e:
        logger.exception("Fatal error: %s", e)

if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.exception("Crash: %s", e)
