import os
import re
import json
import time
import uuid
import logging
import asyncio
import secrets
from datetime import datetime, timezone, timedelta

from aiohttp import web, ClientSession
from telethon import TelegramClient, events, Button
from telethon.tl.types import User
from telethon.tl.functions.channels import GetParticipantRequest
from pymongo import MongoClient

# ============ Config ============

PORT = int(os.getenv("PORT", "10000"))

# Bot credentials
BOT_SESSION_FILE = os.getenv("BOT_SESSION_FILE", "bot_session.session")
BOT_API_ID = int(os.getenv("API_ID", "0"))
BOT_API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# User account credentials (for forwarding)
USER_SESSION_FILE = os.getenv("USER_SESSION_FILE", "relay_session.session")
USER_API_ID = int(os.getenv("USER_API_ID", "0"))
USER_API_HASH = os.getenv("USER_API_HASH", "").strip()
USER_PHONE = os.getenv("USER_PHONE", "").strip()

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
MANDATORY_CHANNEL = os.getenv("MANDATORY_CHANNEL", "darkboxesv1")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://prarthanaray147_db_user:fMuTkgFsaHa5NRIy@cluster0.txn8bv3.mongodb.net/tg_bot_db?retryWrites=true&w=majority")
MONGODB_DBNAME = os.getenv("MONGODB_DBNAME", "tg_bot_db")

PAYMENT_QR_CODE = os.getenv("PAYMENT_QR_CODE", "https://example.com/payment-qr.png")

FETCH_WAIT_TIME = int(os.getenv("FETCH_WAIT_TIME", "2"))
GROUP_TIMEOUT = int(os.getenv("GROUP_TIMEOUT", "15"))
REPLY_TIMEOUT = int(os.getenv("REPLY_TIMEOUT", "45"))
PROCESSING_WAIT_EXTRA = 8

# API endpoints
PHONE_API_URL = "https://daily-binny-ryuioggv-391a9381.koyeb.app/api/lookup"
PHONE_API_KEY = "616bd0f26e364c89"
VEHICLE_API_URL = "https://vehicle-6bh6.onrender.com/vehicle_info"
VEHICLE_API_KEY = "URSLASH123"

# Referral settings
REFERRAL_REWARD = 2
NEW_USER_CREDITS = 2

# ============ Logging ============

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("premium_bot")

# ============ Validate Config ============

if BOT_API_ID == 0 or not BOT_API_HASH:
    logger.error("API_ID and API_HASH must be set!")
    raise ValueError("Missing API_ID or API_HASH")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN must be set!")
    raise ValueError("Missing BOT_TOKEN")

USE_USER_ACCOUNT = USER_API_ID != 0 and USER_API_HASH and USER_PHONE

logger.info("=" * 60)
logger.info("Configuration Check:")
logger.info("BOT API_ID: %s", BOT_API_ID)
logger.info("BOT API_HASH: %s", BOT_API_HASH[:10] + "...")
logger.info("BOT_TOKEN: %s", BOT_TOKEN[:20] + "...")
logger.info("ADMIN_USER_ID: %s", ADMIN_USER_ID)
if USE_USER_ACCOUNT:
    logger.info("USER ACCOUNT: Enabled (Phone: %s)", USER_PHONE)
else:
    logger.info("USER ACCOUNT: Disabled (will use bot to forward)")
logger.info("=" * 60)

# ============ Destination Groups Configuration ============

DESTINATION_GROUPS = [
    {
        "name": "Main Group",
        "identifier": "darkboxesv3",
        "timeout": GROUP_TIMEOUT,
        "entity": None
    },
    {
        "name": "Backup Group 2",
        "identifier": "nex_chats",
        "timeout": GROUP_TIMEOUT,
        "entity": None
    },
    {
        "name": "Backup Group 3",
        "identifier": "marco_osintgc",
        "timeout": GROUP_TIMEOUT,
        "entity": None
    }
]

FAMILY_GROUP = {
    "name": "Family Info Group",
    "identifier": -1003596998816,  # Private group ID
    "timeout": GROUP_TIMEOUT,
    "entity": None
}

TELEGRAM_BOT = {
    "name": "Telegram Lookup Bot",
    "identifier": "@Dirgeshrai8090_bot",
    "timeout": GROUP_TIMEOUT,
    "entity": None
}

TELEGRAM_USERNAME_GROUP = {
    "name": "Telegram Username Group",
    "identifier": "darkboxesv3",  # Replace with your actual group for username searches
    "timeout": GROUP_TIMEOUT,
    "entity": None
}

MOVIE_BOT = {
    "name": "Movie/Series Bot",
    "identifier": "@iPapkornD2bot",  # Replace with your actual movie bot username
    "timeout": 60,  # Movies might take longer to respond
    "entity": None
}

VEHICLE_GROUP = {
    "name": "Vehicle Group",
    "identifier": "IntelXGroup",
    "timeout": GROUP_TIMEOUT,
    "entity": None
}

# ============ Command Mapping ============

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Number Info",
        "type": "group",
        "commands": {
            0: "/num",
            1: "/num",
            2: "/num"
        }
    },
    "family": {
        "name": "👨‍👩‍👧‍👦 Family Info",
        "type": "family_group",
        "commands": {
            0: "/family"
        }
    },
    "aadhar": {
        "name": "🆔 Aadhar Info",
        "type": "group",
        "commands": {
            0: "/adh",
            1: "/aadhar",
            2: "/aadhar"
        }
    },
    "vehicle": {
        "name": "🚗 Vehicle to Phone",
        "type": "vehicle_group",
        "commands": {
            0: "/vnum"
        }
    },
    "vehicle_detail": {
        "name": "🚙 Vehicle Details",
        "type": "group",
        "commands": {
            0: "/vehicle",
            1: "/vehicle",
            2: "/vnum"
        }
    },
    "upi": {
        "name": "💳 UPI Info",
        "type": "group",
        "commands": {
            0: "/upiinfo",
            1: "/upiinfo",
            2: "/upiinfo"
        }
    },
    "fampay": {
        "name": "💰 Fampay Info",
        "type": "group",
        "commands": {
            0: "/fam",
            1: "/fam",
            2: "/fam"
        }
    },
    "email": {
        "name": "📧 Email Info",
        "type": "group",
        "commands": {
            0: "/email",
            1: "/email",
            2: "/email"
        }
    },
    "telegram": {
        "name": "📲 Telegram to Phone",
        "type": "telegram_bot",
        "commands": {
            0: "/tg"
        }
    },
    "telegram_username": {
        "name": "👤 Telegram Username Info",
        "type": "telegram_username_group",
        "commands": {
            0: "/tguser"
        }
    },
    "imei": {
        "name": "📱 IMEI Info",
        "type": "group",
        "commands": {
            0: "/imei",
            1: "/imei",
            2: "/imei"
        }
    },
    "pak": {
        "name": "🇵🇰 Pakistan Info",
        "type": "group",
        "commands": {
            0: "/cnic",
            1: "/cnic",
            2: "/cnic"
        }
    },
    "gst": {
        "name": "🏢 GST Info",
        "type": "group",
        "commands": {
            0: "/gst",
            1: "/gst",
            2: "/gst"
        }
    },
    "insta": {
        "name": "📷 Instagram Info",
        "type": "group",
        "commands": {
            0: "/insta",
            1: "/insta",
            2: "/insta"
        }
    },
    "movies": {
        "name": "🎬 Movies/Web Series",
        "type": "movie_bot",
        "commands": {
            0: ""  # Movie bot doesn't need a command prefix, just send the name
        }
    }
}

PLANS = {
    "plan_5": {"searches": 5, "price": 100, "name": "5 Searches", "days": None},
    "plan_15": {"searches": 15, "price": 200, "name": "15 Searches", "days": None},
    "plan_week": {"searches": -1, "price": 500, "name": "Unlimited (7 Days)", "days": 7}
}

# ============ MongoDB ============

mongo_client = None
db = None
users_col = None
payments_col = None
searches_col = None
api_keys_col = None
referrals_col = None

def init_mongo():
    global mongo_client, db, users_col, payments_col, searches_col, api_keys_col, referrals_col
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        users_col = db["users"]
        payments_col = db["payments"]
        searches_col = db["searches"]
        api_keys_col = db["api_keys"]
        referrals_col = db["referrals"]
        
        # Create user_id unique index
        try:
            users_col.create_index([("user_id", 1)], unique=True)
        except Exception as e:
            if "already exists" not in str(e).lower():
                raise
            logger.info("user_id index already exists")
        
        # Drop old referral_code index if it exists
        try:
            users_col.drop_index("referral_code_1")
            logger.info("Dropped old referral_code index")
        except Exception as e:
            logger.info("No old referral_code index to drop")
        
        # Create partial unique index for referral_code (only for non-null values)
        try:
            users_col.create_index(
                [("referral_code", 1)], 
                unique=True, 
                partialFilterExpression={"referral_code": {"$type": "string"}}
            )
            logger.info("Created partial unique index for referral_code")
        except Exception as e:
            if "already exists" not in str(e).lower():
                logger.warning(f"Could not create referral_code index: {e}")
        
        # Other indexes
        for col, field in [(payments_col, "user_id"), (searches_col, "user_id"), 
                           (api_keys_col, "user_id"), (referrals_col, "referrer_id"), 
                           (referrals_col, "referred_id")]:
            try:
                col.create_index([(field, 1)])
            except:
                pass
        
        try:
            api_keys_col.create_index([("api_key", 1)], unique=True)
        except:
            pass
        
        logger.info("MongoDB connected successfully")
    except Exception as e:
        logger.exception("MongoDB connection failed: %s", e)
        raise

# ============ Referral System ============

def generate_referral_code():
    return secrets.token_urlsafe(6).upper()

async def get_or_create_referral_code(user_id: int):
    try:
        user = await get_user(user_id)
        if user and user.get('referral_code'):
            return user['referral_code']
        
        while True:
            code = generate_referral_code()
            existing = await asyncio.get_running_loop().run_in_executor(
                None, users_col.find_one, {"referral_code": code}
            )
            if not existing:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: users_col.update_one(
                        {"user_id": user_id},
                        {"$set": {"referral_code": code}}
                    )
                )
                return code
    except Exception as e:
        logger.exception("Error generating referral code: %s", e)
        return None

async def apply_referral(referred_user_id: int, referral_code: str):
    try:
        referrer = await asyncio.get_running_loop().run_in_executor(
            None, users_col.find_one, {"referral_code": referral_code.upper()}
        )
        
        if not referrer:
            return False
        
        referrer_id = referrer['user_id']
        
        if referrer_id == referred_user_id:
            return False
        
        user = await get_user(referred_user_id)
        if user.get('referred_by'):
            return False
        
        referral_doc = {
            "referrer_id": referrer_id,
            "referred_id": referred_user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reward_given": False
        }
        
        await asyncio.get_running_loop().run_in_executor(
            None, referrals_col.insert_one, referral_doc
        )
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": referred_user_id},
                {"$set": {"referred_by": referrer_id}}
            )
        )
        
        return True
    except Exception as e:
        logger.exception("Error applying referral: %s", e)
        return False

async def reward_referrer(referred_user_id: int):
    try:
        referral = await asyncio.get_running_loop().run_in_executor(
            None, referrals_col.find_one, {"referred_id": referred_user_id, "reward_given": False}
        )
        
        if not referral:
            return False
        
        referrer_id = referral['referrer_id']
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": referrer_id},
                {"$inc": {"searches_remaining": REFERRAL_REWARD}}
            )
        )
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: referrals_col.update_one(
                {"_id": referral['_id']},
                {"$set": {"reward_given": True, "rewarded_at": datetime.now(timezone.utc).isoformat()}}
            )
        )
        
        try:
            await bot_client.send_message(
                referrer_id,
                f"🎉 Congratulations!\n\n"
                f"You earned {REFERRAL_REWARD} credits because someone used your referral link!\n\n"
                f"Keep sharing to earn more credits! 💰"
            )
        except Exception as e:
            logger.error(f"Could not notify referrer {referrer_id}: {e}")
        
        return True
    except Exception as e:
        logger.exception("Error rewarding referrer: %s", e)
        return False

async def get_referral_stats(user_id: int):
    try:
        total_referrals = await asyncio.get_running_loop().run_in_executor(
            None, lambda: referrals_col.count_documents({"referrer_id": user_id})
        )
        
        rewarded_referrals = await asyncio.get_running_loop().run_in_executor(
            None, lambda: referrals_col.count_documents({"referrer_id": user_id, "reward_given": True})
        )
        
        return {
            "total": total_referrals,
            "rewarded": rewarded_referrals,
            "pending": total_referrals - rewarded_referrals
        }
    except Exception as e:
        logger.exception("Error getting referral stats: %s", e)
        return {"total": 0, "rewarded": 0, "pending": 0}

# ============ API Key Management ============

async def create_api_key(user_id: int, name: str = "Default Key"):
    try:
        api_key = f"sk_{secrets.token_urlsafe(32)}"
        doc = {
            "api_key": api_key,
            "user_id": user_id,
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "searches_used": 0,
            "active": True,
            "last_used": None
        }
        await asyncio.get_running_loop().run_in_executor(
            None, api_keys_col.insert_one, doc
        )
        return api_key
    except Exception as e:
        logger.exception("Error creating API key: %s", e)
        return None

async def get_api_key_info(api_key: str):
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, api_keys_col.find_one, {"api_key": api_key}
        )
    except Exception as e:
        logger.exception("Error fetching API key: %s", e)
        return None

async def list_user_api_keys(user_id: int):
    try:
        cursor = api_keys_col.find({"user_id": user_id})
        return await asyncio.get_running_loop().run_in_executor(
            None, list, cursor
        )
    except Exception as e:
        logger.exception("Error listing API keys: %s", e)
        return []

async def delete_api_key(api_key: str, user_id: int):
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, lambda: api_keys_col.delete_one(
                {"api_key": api_key, "user_id": user_id}
            )
        )
        return result.deleted_count > 0
    except Exception as e:
        logger.exception("Error deleting API key: %s", e)
        return False

async def increment_api_key_usage(api_key: str):
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: api_keys_col.update_one(
                {"api_key": api_key},
                {
                    "$inc": {"searches_used": 1},
                    "$set": {"last_used": datetime.now(timezone.utc).isoformat()}
                }
            )
        )
        return True
    except Exception as e:
        logger.exception("Error incrementing API usage: %s", e)
        return False

# ============ User Management ============

async def get_user(user_id: int):
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, users_col.find_one, {"user_id": user_id}
        )
    except Exception as e:
        logger.exception("Error fetching user: %s", e)
        return None

async def create_or_update_user(user_id: int, username: str = None, first_name: str = None):
    try:
        doc = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "plan": "free",
            "searches_remaining": NEW_USER_CREDITS,
            "plan_expiry": None,
            "total_searches": 0,
            "channel_joined": False,
            "referral_code": None,
            "referred_by": None
        }
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$setOnInsert": doc},
                upsert=True
            )
        )
        return await get_user(user_id)
    except Exception as e:
        logger.exception("Error creating user: %s", e)
        return None

async def update_user_plan(user_id: int, plan: str, searches: int, days: int = None):
    try:
        update_doc = {
            "plan": plan,
            "searches_remaining": searches
        }
        if days:
            update_doc["plan_expiry"] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        else:
            update_doc["plan_expiry"] = None
            
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$set": update_doc}
            )
        )
        return True
    except Exception as e:
        logger.exception("Error updating user plan: %s", e)
        return False

async def decrement_search(user_id: int):
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$inc": {"searches_remaining": -1, "total_searches": 1}}
            )
        )
        return True
    except Exception as e:
        logger.exception("Error decrementing search: %s", e)
        return False

async def log_search(user_id: int, search_type: str, query: str, result: str):
    try:
        doc = {
            "user_id": user_id,
            "search_type": search_type,
            "query": query,
            "result": result[:500],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await asyncio.get_running_loop().run_in_executor(
            None, searches_col.insert_one, doc
        )
    except Exception as e:
        logger.exception("Error logging search: %s", e)

async def create_payment_request(user_id: int, plan: str, amount: int):
    try:
        doc = {
            "payment_id": uuid.uuid4().hex,
            "user_id": user_id,
            "plan": plan,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "screenshot_file_id": None,
            "approved_at": None
        }
        result = await asyncio.get_running_loop().run_in_executor(
            None, payments_col.insert_one, doc
        )
        return doc["payment_id"]
    except Exception as e:
        logger.exception("Error creating payment: %s", e)
        return None

async def update_payment_screenshot(payment_id: str, file_id: str):
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: payments_col.update_one(
                {"payment_id": payment_id},
                {"$set": {"screenshot_file_id": file_id, "screenshot_at": datetime.now(timezone.utc).isoformat()}}
            )
        )
        return True
    except Exception as e:
        logger.exception("Error updating payment screenshot: %s", e)
        return False

async def check_telegram_daily_limit(user_id: int) -> bool:
    """Check if user has exceeded daily telegram search limit (1 per day)"""
    try:
        today = datetime.now(timezone.utc).date()
        today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        
        count = await asyncio.get_running_loop().run_in_executor(
            None, lambda: searches_col.count_documents({
                "user_id": user_id,
                "search_type": {"$in": ["telegram", "telegram_username"]},
                "timestamp": {"$gte": today_start.isoformat()}
            })
        )
        return count >= 1
    except Exception as e:
        logger.exception("Error checking telegram daily limit: %s", e)
        return False

async def get_telegram_search_reset_time(user_id: int) -> str:
    """Get when the user can search telegram again"""
    try:
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        tomorrow_start = datetime.combine(tomorrow, datetime.min.time()).replace(tzinfo=timezone.utc)
        time_diff = tomorrow_start - datetime.now(timezone.utc)
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)
        return f"{hours}h {minutes}m"
    except Exception:
        return "24h"

# ============ Response Detection Helpers ============

def is_processing_message(text: str) -> bool:
    if not text:
        return False
    
    text_lower = text.lower()
    processing_keywords = [
        'processing',
        'please wait',
        'fetching',
        'loading',
        'searching',
        'retrieving',
        'hold on',
        'wait a moment',
        'in progress',
        'gathering data',
        'working on it',
        '⏳',
        '🔍',
        'searching for',
        'processing your request'
    ]
    
    if len(text.strip()) < 30:
        return True
    
    for keyword in processing_keywords:
        if keyword in text_lower:
            return True
    
    if text.strip().startswith('/'):
        return True
    
    return False

def is_no_info_message(text: str) -> bool:
    if not text:
        return False
    
    text_lower = text.lower()
    no_info_keywords = [
        'no info',
        'no information',
        'not found',
        'no data',
        'no result',
        'no record',
        'invalid',
        'doesn\'t exist',
        'does not exist',
        'not available',
        'no details',
        'unable to find',
        'could not find',
        'couldn\'t find',
        'no match',
        'not exist',
        'no information found',
        'no result found',
        'no records found',
        # Add spam/verification keywords
        'to reduce spam',
        'must have joined',
        'must join',
        'join all channels',
        'join our channel',
        'verify your account',
        'admin to verify',
        'need to join',
        'required to join',
        'subscription required',
        'access denied'
    ]
    
    return any(keyword in text_lower for keyword in no_info_keywords)

def is_valid_result(text: str, search_type: str) -> bool:
    if not text:
        return False
    
    if is_processing_message(text):
        return False
    
    if is_no_info_message(text):
        return False
    
    # More lenient length check - reduced from 50 to 30
    if len(text.strip()) < 30:
        return False
    
    # Check for common data indicators (works for both JSON and plain text)
    data_indicators = [
        'name', 'mobile', 'address', 'email', 'father',
        'owner', 'vehicle', 'registration', 'chassis',
        'model', 'manufacturer', 'policy', 'insurance',
        'aadhar', 'upi', 'telegram', 'instagram', 'gst',
        'status', 'found', 'count', 'records', 'data'
    ]
    
    text_lower = text.lower()
    has_data = any(indicator in text_lower for indicator in data_indicators)
    
    # Additional check: if it looks like JSON with status found, it's valid
    if '"status"' in text and '"found"' in text_lower:
        return True
    
    # If it contains multiple data indicators, it's likely valid
    indicator_count = sum(1 for indicator in data_indicators if indicator in text_lower)
    if indicator_count >= 2:
        return True
    
    return has_data

# ============ Text Cleaning ============

def filter_links_and_usernames(text: str):
    if not text:
        return text

    patterns = [
        r'https?://[^\s]+',
        r'www\.[^\s]+',
        r't\.me/[^\s]+',
        r'@[a-zA-Z0-9_]{3,32}',
        r'\bfrappeash\.?\b',
        r'\bzerocyph\.?\b',
    ]

    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)

    promotional = [
        'use these commands',
        'join our',
        'visit our',
        'contact us',
        'follow us',
        'subscribe',
        'click here',
        'check out',
        'telegram channel',
        'telegram group'
    ]

    lines = cleaned.splitlines()
    safe_lines = []

    for line in lines:
        l = line.strip()
        if not l:
            continue
        if any(k in l.lower() for k in promotional):
            continue
        safe_lines.append(line)

    cleaned = "\n".join(safe_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned).strip()

    return cleaned

def extract_family_members(text: str) -> str:
    """
    Extract only family member lines from family info text.
    Removes headers, footers, and other promotional content.
    
    Example input:
        FAMILY REPORT
        ====================
        Head: NA
        RC No: NA
        
        • Rammurti (F) - SELF
        • MAHENDRA SINGH (M) - HUSBAND
        • Saurav Vairagi (M) - SON
        
        ====================
        ⚡ Designed & Powered by @DuXxZx_info
    
    Example output:
        • Rammurti (F) - SELF
        • MAHENDRA SINGH (M) - HUSBAND
        • Saurav Vairagi (M) - SON
    """
    if not text:
        return text
    
    lines = text.splitlines()
    family_members = []
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            continue
        
        # Skip separator lines
        if stripped.startswith('='):
            continue
        
        # Skip header keywords
        header_keywords = [
            'family report',
            'head:',
            'rc no:',
            'designed',
            'powered by',
            'developed by',
            '@',
            'telegram',
            '⚡',
            '©',
            'copyright'
        ]
        
        if any(keyword in stripped.lower() for keyword in header_keywords):
            continue
        
        # Keep lines that start with bullet points (family members)
        if stripped.startswith('•') or stripped.startswith('-') or stripped.startswith('*'):
            family_members.append(stripped)
    
    if family_members:
        return '\n'.join(family_members)
    
    # If no bullet points found, return original (fallback)
    return text

def format_phone_api_response(data, phone_number: str):
    try:
        result = f"📱 Phone Number Information\n\nNumber: {phone_number}\n\n"

        if isinstance(data, dict):
            data.pop('Developer', None)
            data.pop('Powered_By', None)
            data.pop('developer', None)
            data.pop('powered_by', None)

            if 'Result' in data and isinstance(data['Result'], list):
                records = data['Result']
                if records:
                    result += f"Found {len(records)} record(s):\n\n"

                    for idx, record in enumerate(records, 1):
                        if len(records) > 1:
                            result += f"━━━ Record {idx} ━━━\n"

                        if record.get('name'):
                            result += f"👤 Name: {record['name'].strip()}\n"
                        if record.get('mobile'):
                            result += f"📱 Mobile: {record['mobile']}\n"
                        if record.get('alt_mobile'):
                            result += f"📞 Alt Mobile: {record['alt_mobile']}\n"
                        if record.get('circle'):
                            result += f"📡 Circle: {record['circle']}\n"
                        if record.get('father_name'):
                            result += f"👨 Father: {record['father_name']}\n"
                        if record.get('address'):
                            addr = record['address'].replace('!', ', ').strip(', ')
                            result += f"🏠 Address: {addr}\n"
                        if record.get('email'):
                            result += f"📧 Email: {record['email']}\n"
                        if record.get('id_number'):
                            result += f"🆔 ID: {record['id_number']}\n"

                        if idx < len(records):
                            result += "\n"
                else:
                    result += "No records found.\n"
            else:
                for key, value in data.items():
                    if key.lower() not in ['status', 'success', 'developer', 'powered_by']:
                        result += f"{key.replace('_', ' ').title()}: {value}\n"
        else:
            result += str(data)

        return filter_links_and_usernames(result)

    except Exception as e:
        logger.exception(f"Error formatting phone API response: {e}")
        return f"📱 Phone Number: {phone_number}\n\nFormatting failed."

def format_vehicle_api_response(data, vehicle_no: str):
    try:
        result = (
            "╔═══════════════════════════════════╗\n"
            f"║  🚗 VEHICLE DETAILS: {vehicle_no} ║\n"
            "╚═══════════════════════════════════╝\n\n"
        )

        if not isinstance(data, dict):
            return "❌ Invalid vehicle data received."

        for k in ('Developer', 'Powered_By', 'developer', 'powered_by', 'success', 'status'):
            data.pop(k, None)

        owner = data.get('owner_name') or data.get('owner')
        father = data.get('father_name')
        mobile = data.get('mobile_number') or data.get('mobile')

        if owner or father or mobile:
            result += "┌─ 👤 OWNER INFORMATION ─┐\n"
            if owner:
                result += f" Owner Name: {owner}\n"
            if father:
                result += f" Father's Name: {father}\n"
            if mobile:
                result += f" Mobile Number: {mobile}\n"
            result += "└─────────────────────────┘\n\n"

        address = data.get('address')
        state = data.get('state')

        if address or state:
            result += "┌─ 🏠 ADDRESS DETAILS ─┐\n"
            if address:
                addr = address.replace('!', ', ').strip(', ')
                result += f" Address: {addr}\n"
            if state:
                result += f" State: {state}\n"
            result += "└─────────────────────────┘\n\n"

        manufacturer = data.get('manufacturer') or data.get('maker')
        model = data.get('model') or data.get('maker_model')
        body = data.get('body_type')
        fuel = data.get('fuel_type')
        color = data.get('color')
        mfg = data.get('manufacturing_date')

        if any([manufacturer, model, body, fuel, color, mfg]):
            result += "┌─ 🔧 VEHICLE SPECIFICATIONS ─┐\n"
            if manufacturer:
                result += f" Manufacturer: {manufacturer}\n"
            if model:
                result += f" Model: {model}\n"
            if body:
                result += f" Body Type: {body}\n"
            if fuel:
                result += f" Fuel Type: {fuel}\n"
            if color:
                result += f" Color: {color}\n"
            if mfg:
                result += f" Manufacturing Date: {mfg}\n"
            result += "└─────────────────────────┘\n\n"

        chassis = data.get('chassis_number')
        engine = data.get('engine_number')

        if chassis or engine:
            result += "┌─ 🆔 TECHNICAL IDENTIFIERS ─┐\n"
            if chassis:
                result += f" Chassis Number: {chassis}\n"
            if engine:
                result += f" Engine Number: {engine}\n"
            result += "└─────────────────────────┘\n\n"

        reg_date = data.get('registration_date')
        reg_valid = data.get('registration_valid_till')
        rto = data.get('registered_at')
        fitness = data.get('fitness_valid_till')
        status = data.get('vehicle_status')

        if any([reg_date, reg_valid, rto, fitness, status]):
            result += "┌─ 📋 REGISTRATION & VALIDITY ─┐\n"
            if reg_date:
                result += f" Registration Date: {reg_date}\n"
            if reg_valid:
                result += f" Registration Valid Till: {reg_valid}\n"
            if rto:
                result += f" Registered At: {rto}\n"
            if fitness:
                result += f" Fitness Valid Till: {fitness}\n"
            if status:
                result += f" Status: {status}\n"
            result += "└─────────────────────────┘\n\n"

        insurer = data.get('insurance_company')
        ins_valid = data.get('insurance_valid_till')
        policy = data.get('policy_number')
        puc_no = data.get('puc_number')
        puc_valid = data.get('puc_valid_till')

        if any([insurer, ins_valid, policy, puc_no, puc_valid]):
            result += "┌─ 🛡️ INSURANCE & PUC ─┐\n"
            if insurer:
                result += f" Insurance Company: {insurer}\n"
            if ins_valid:
                result += f" Insurance Valid Till: {ins_valid}\n"
            if policy:
                result += f" Policy Number: {policy}\n"
            if puc_no:
                result += f" PUC Certificate No: {puc_no}\n"
            if puc_valid:
                result += f" PUC Valid Till: {puc_valid}\n"
            result += "└─────────────────────────┘\n\n"

        value = data.get('resale_value')
        age = data.get('vehicle_age')
        norms = data.get('fuel_norms')
        category = data.get('vehicle_category')
        rto_code = data.get('rto_code')

        if any([value, age, norms, category, rto_code]):
            result += "┌─ ℹ️ ADDITIONAL INFORMATION ─┐\n"
            if value:
                result += f" Resale Value: {value}\n"
            if age:
                result += f" Vehicle Age: {age}\n"
            if norms:
                result += f" Fuel Norms: {norms}\n"
            if category:
                result += f" Vehicle Category: {category}\n"
            if rto_code:
                result += f" RTO Code: {rto_code}\n"
            result += "└─────────────────────────┘\n"

        return filter_links_and_usernames(result)

    except Exception as e:
        logger.exception("Vehicle formatter error")
        return f"🚗 Vehicle Number: {vehicle_no}\n\nFormatting failed."

# ============ Bot State ============

user_states = {}
pending_searches = {}
interactive_sessions = {}  # Tracks user sessions waiting for button clicks: {user_id: {dest_message, dest_entity, buttons_map}}

# ============ Telethon Clients ============

bot_client = TelegramClient(BOT_SESSION_FILE, BOT_API_ID, BOT_API_HASH)

if USE_USER_ACCOUNT:
    user_client = TelegramClient(USER_SESSION_FILE, USER_API_ID, USER_API_HASH)
else:
    user_client = bot_client

async def check_channel_membership(user_id: int):
    """Check if user is a member of the mandatory channel"""
    try:
        # Try to get the channel entity
        channel = await bot_client.get_entity(MANDATORY_CHANNEL)
        
        # Get the participant info
        try:
            participant = await bot_client(
                GetParticipantRequest(channel, user_id)
            )
            # If we get here, user is a participant
            # Check if they are banned or left
            from telethon.tl.types import ChannelParticipantBanned, ChannelParticipantLeft
            
            if isinstance(participant.participant, (ChannelParticipantBanned, ChannelParticipantLeft)):
                return False
            
            return True
            
        except Exception as get_participant_error:
            # User is not in the channel
            logger.info(f"User {user_id} is not in channel: {get_participant_error}")
            return False
        
    except Exception as e:
        # If there's an error accessing the channel, log it
        logger.error(f"Error checking channel membership for {user_id}: {e}")
        return False

# ============ Interactive Bot Search Functions ============

async def perform_interactive_telegram_search(query: str, user_id: int):
    """
    Perform interactive telegram search where user chooses the platform.
    Shows buttons from destination bot to user.
    """
    # Check daily limit
    if await check_telegram_daily_limit(user_id):
        reset_time = await get_telegram_search_reset_time(user_id)
        return {
            "success": False,
            "error": f"⏰ Daily telegram search limit reached (1 per day).\n\n🔄 Reset in: {reset_time}"
        }
    
    bot_entity = TELEGRAM_BOT.get('entity')
    if not bot_entity:
        return {"success": False, "error": "Telegram bot not configured"}
    
    try:
        command_prefix = SEARCH_COMMANDS['telegram']['commands'].get(0, '/tg')
        command = f"{command_prefix} {query}"
        
        # Send query to destination bot
        send_timestamp = time.time()
        forwarded = await user_client.send_message(bot_entity, command)
        logger.info(f"📤 Sent to Telegram Bot: {command}")
        
        # Wait for response with buttons
        await asyncio.sleep(4)
        
        # Get the response from destination bot (check by timestamp, not reply_to)
        messages = await user_client.get_messages(bot_entity, limit=15)
        for msg in messages:
            # Skip our own sent message
            if msg.id == forwarded.id:
                continue
            
            # Check if message is newer than our send (within last 10 seconds)
            msg_timestamp = msg.date.timestamp() if msg.date else 0
            if msg_timestamp < send_timestamp - 2:  # 2 sec buffer
                continue
            
            if msg.buttons:
                # Found buttons! Send them to user
                logger.info(f"🔘 Found inline keyboard with {len(msg.buttons)} rows")
                
                # Store session info
                interactive_sessions[user_id] = {
                    "dest_message": msg,
                    "dest_entity": bot_entity,
                    "type": "telegram",
                    "query": query,
                    "original_msg_id": forwarded.id
                }
                
                # Create same buttons for user
                user_buttons = []
                for row in msg.buttons:
                    button_row = []
                    for button in row:
                        if hasattr(button, 'text'):
                            # Create callback button with same text
                            button_row.append(Button.inline(
                                button.text, 
                                f"relay_{button.text.lower().replace(' ', '_')}"
                            ))
                    if button_row:
                        user_buttons.append(button_row)
                
                # Return special "needs_interaction" response
                return {
                    "success": False,
                    "needs_interaction": True,
                    "message": msg.text or msg.raw_text or "🔍 Please select a platform:",
                    "buttons": user_buttons
                }
            
            # If no buttons but has text, return it
            if msg.text or msg.raw_text:
                return {
                    "success": True,
                    "result": msg.text or msg.raw_text
                }
        
        return {"success": False, "error": "No response from Telegram bot"}
        
    except Exception as e:
        logger.exception(f"Error in interactive telegram search: {e}")
        return {"success": False, "error": str(e)}

async def perform_interactive_movie_search(query: str, user_id: int):
    """
    Perform interactive movie search where user chooses from file options.
    Shows buttons/files from movie bot to user.
    """
    bot_entity = MOVIE_BOT.get('entity')
    if not bot_entity:
        return {"success": False, "error": "Movie bot not configured"}
    
    try:
        # Send movie name to bot (no command prefix needed)
        send_timestamp = time.time()
        forwarded = await user_client.send_message(bot_entity, query)
        logger.info(f"🎬 Sent to Movie Bot: {query}")
        
        # Wait for response
        await asyncio.sleep(5)
        
        # Get the response from movie bot (check by timestamp, not reply_to)
        messages = await user_client.get_messages(bot_entity, limit=20)
        
        for msg in messages:
            # Skip our own sent message
            if msg.id == forwarded.id:
                continue
            
            # Check if message is newer than our send (within last 10 seconds)
            msg_timestamp = msg.date.timestamp() if msg.date else 0
            if msg_timestamp < send_timestamp - 2:  # 2 sec buffer
                continue
            
            # Check if it has buttons
            if msg.buttons:
                logger.info(f"🎬 Found movie options with {len(msg.buttons)} rows")
                
                # Store session info
                interactive_sessions[user_id] = {
                    "dest_message": msg,
                    "dest_entity": bot_entity,
                    "type": "movie",
                    "query": query,
                    "original_msg_id": forwarded.id
                }
                
                # Create same buttons for user
                user_buttons = []
                for row in msg.buttons:
                    button_row = []
                    for button in row:
                        if hasattr(button, 'text'):
                            # Create callback button with same text
                            button_row.append(Button.inline(
                                button.text,
                                f"relay_{len(user_buttons)}_{len(button_row)}"  # row_col format
                            ))
                    if button_row:
                        user_buttons.append(button_row)
                
                # Return special "needs_interaction" response
                return {
                    "success": False,
                    "needs_interaction": True,
                    "message": msg.text or msg.raw_text or "🎬 Select a file:",
                    "buttons": user_buttons
                }
            
            # Return text/file response (if no buttons)
            if msg.text or msg.file:
                return {
                    "success": True,
                    "result": msg.text or msg.raw_text or "File received",
                    "file": msg if msg.file else None
                }
        
        return {"success": False, "error": "No response from Movie bot"}
        
    except Exception as e:
        logger.exception(f"Error in interactive movie search: {e}")
        return {"success": False, "error": str(e)}

# ============ Core Search Function ============

async def perform_search(search_type: str, query: str, user_id: int = None):
    if search_type not in SEARCH_COMMANDS:
        return {"success": False, "error": "Invalid search type"}
    
    command_info = SEARCH_COMMANDS[search_type]
    search_dest_type = command_info.get('type', 'group')
    
    if search_dest_type == 'telegram_bot':
        # Use interactive search for telegram (shows buttons to user)
        if user_id:
            return await perform_interactive_telegram_search(query, user_id)
        else:
            # API calls use old method (auto-click)
            return await perform_telegram_bot_search(query, user_id)
    elif search_dest_type == 'movie_bot':
        # Use interactive search for movies
        return await perform_interactive_movie_search(query, user_id)
    elif search_dest_type == 'telegram_username_group':
        return await perform_telegram_username_search(query, user_id)
    elif search_dest_type == 'family_group':
        destinations = [FAMILY_GROUP]
    elif search_dest_type == 'vehicle_group':
        destinations = [VEHICLE_GROUP]
    else:
        destinations = DESTINATION_GROUPS
    
    for idx, dest_config in enumerate(destinations):
        dest_entity = dest_config.get('entity')
        
        if not dest_entity:
            logger.warning(f"Destination {idx} ({dest_config['name']}) not resolved, skipping")
            continue
        
        command_prefix = command_info['commands'].get(idx)
        if not command_prefix:
            logger.warning(f"No command configured for {search_type} in group {idx}")
            continue
        
        command = f"{command_prefix} {query}"
        base_timeout = dest_config.get('timeout', GROUP_TIMEOUT)
        
        try:
            forwarded = await user_client.send_message(dest_entity, command)
            logger.info(f"📤 Sent to {dest_config['name']} (Group {idx}): {command}")
            
            future = asyncio.get_running_loop().create_future()
            search_id = f"{forwarded.id}_{int(time.time() * 1000)}_{idx}"
            
            pending_searches[search_id] = {
                "future": future,
                "user_id": user_id,
                "query": query,
                "search_type": search_type,
                "timestamp": time.time(),
                "group_index": idx,
                "group_name": dest_config['name'],
                "message_id": forwarded.id,
                "chat_entity": dest_entity
            }
            
            logger.info(f"📝 Registered search {search_id} in {dest_config['name']}")
            
            try:
                result_text = await asyncio.wait_for(future, timeout=base_timeout)
                
                logger.info(f"📩 Received response from {dest_config['name']}: {result_text[:100]}...")
                
                # Handle processing messages
                if is_processing_message(result_text):
                    logger.info(f"⏳ Processing message detected, waiting {PROCESSING_WAIT_EXTRA}s more...")
                    
                    await asyncio.sleep(PROCESSING_WAIT_EXTRA)
                    
                    try:
                        messages = await user_client.get_messages(dest_entity, limit=20)
                        
                        for msg in messages:
                            if msg.reply_to and msg.reply_to.reply_to_msg_id == forwarded.id:
                                potential_text = msg.text or msg.raw_text
                                if potential_text and not is_processing_message(potential_text):
                                    result_text = potential_text
                                    logger.info(f"🔄 Found updated non-processing message")
                                    break
                            
                    except Exception as e:
                        logger.error(f"Error getting updated message: {e}")
                
                # NEW: Handle spam/no-info messages - wait for valid data
                if is_no_info_message(result_text):
                    logger.info(f"🚫 Spam/no-info message detected, waiting {PROCESSING_WAIT_EXTRA}s for valid data...")
                    
                    await asyncio.sleep(PROCESSING_WAIT_EXTRA)
                    
                    try:
                        messages = await user_client.get_messages(dest_entity, limit=20)
                        
                        for msg in messages:
                            if msg.reply_to and msg.reply_to.reply_to_msg_id == forwarded.id:
                                potential_text = msg.text or msg.raw_text
                                # Look for valid data (not spam, not processing)
                                if (potential_text and 
                                    not is_no_info_message(potential_text) and 
                                    not is_processing_message(potential_text) and
                                    is_valid_result(potential_text, search_type)):
                                    result_text = potential_text
                                    logger.info(f"✅ Found valid data message after spam message!")
                                    break
                            
                    except Exception as e:
                        logger.error(f"Error getting updated message after spam: {e}")
                
                logger.info(f"🔍 Validating result from {dest_config['name']}")
                
                if is_no_info_message(result_text):
                    logger.warning(f"⚠️ No info found in {dest_config['name']}")
                    pending_searches.pop(search_id, None)
                    
                    if idx < len(destinations) - 1:
                        logger.info(f"➡️ Cascading to next group: {destinations[idx + 1]['name']}")
                        continue
                    else:
                        logger.info(f"🔄 All groups failed, trying API fallback")
                        api_result = await try_api_fallback(search_type, query, user_id)
                        if api_result['success']:
                            return api_result
                        else:
                            return {
                                "success": False, 
                                "error": "No result found for this input. Please try another."
                            }
                
                if not is_valid_result(result_text, search_type):
                    logger.warning(f"⚠️ Invalid result format from {dest_config['name']}")
                    pending_searches.pop(search_id, None)
                    
                    if idx < len(destinations) - 1:
                        logger.info(f"➡️ Moving to next group: {destinations[idx + 1]['name']}")
                        continue
                    else:
                        api_result = await try_api_fallback(search_type, query, user_id)
                        if api_result['success']:
                            return api_result
                        else:
                            return {
                                "success": False,
                                "error": "No result found for this input. Please try another."
                            }
                
                cleaned = filter_links_and_usernames(result_text)
                
                if user_id:
                    await log_search(user_id, search_type, query, cleaned)
                
                logger.info(f"✅ Valid result from {dest_config['name']}")
                pending_searches.pop(search_id, None)
                
                return {
                    "success": True, 
                    "result": cleaned, 
                    "search_type": search_type, 
                    "source": dest_config['name'],
                    "group_index": idx
                }
                
            except asyncio.TimeoutError:
                pending_searches.pop(search_id, None)
                logger.warning(f"⏱️ Timeout in {dest_config['name']} after {base_timeout}s")
                
                if idx == len(destinations) - 1:
                    logger.info(f"🔄 All groups timed out, trying API fallback")
                    api_result = await try_api_fallback(search_type, query, user_id)
                    if api_result['success']:
                        return api_result
                    else:
                        return {
                            "success": False, 
                            "error": "Request timed out. Please try again."
                        }
                else:
                    logger.info(f"➡️ Moving to next group: {destinations[idx + 1]['name']}")
                    continue
            except Exception as search_error:
                pending_searches.pop(search_id, None)
                logger.exception(f"❌ Error waiting for result in {dest_config['name']}: {search_error}")
                
                if idx == len(destinations) - 1:
                    return {
                        "success": False,
                        "error": "An error occurred. Please try again."
                    }
                else:
                    logger.info(f"➡️ Moving to next group due to error")
                    continue
                
        except Exception as e:
            logger.exception(f"Error in {dest_config['name']}: %s", e)
            if idx == len(destinations) - 1:
                return {"success": False, "error": "All groups failed. Please try again."}
            continue
    
    return {
        "success": False, 
        "error": "No result found for this input. Please try another."
    }

async def try_api_fallback(search_type: str, query: str, user_id: int = None):
    if search_type in ['phone', 'telegram']:
        api_result = await fetch_phone_api(query)
        if api_result:
            if user_id:
                await log_search(user_id, search_type, query, api_result)
            return {
                "success": True, 
                "result": api_result, 
                "search_type": search_type, 
                "source": "Phone API (Backup)"
            }
    
    elif search_type in ['vehicle', 'vehicle_detail']:
        api_result = await fetch_vehicle_api(query)
        if api_result:
            if user_id:
                await log_search(user_id, search_type, query, api_result)
            return {
                "success": True, 
                "result": api_result, 
                "search_type": search_type, 
                "source": "Vehicle API (Backup)"
            }
    
    return {"success": False, "error": "All groups failed and no API backup available"}

async def perform_telegram_bot_search(query: str, user_id: int = None):
    """Perform telegram to phone search with auto button click and daily limit"""
    
    # Check daily limit
    if user_id and await check_telegram_daily_limit(user_id):
        reset_time = await get_telegram_search_reset_time(user_id)
        return {
            "success": False, 
            "error": f"⏰ Daily telegram search limit reached (1 per day).\n\n🔄 Reset in: {reset_time}"
        }
    
    bot_entity = TELEGRAM_BOT.get('entity')
    
    if not bot_entity:
        return {"success": False, "error": "Telegram bot not configured"}
    
    try:
        command_prefix = SEARCH_COMMANDS['telegram']['commands'].get(0, '/tg')
        command = f"{command_prefix} {query}"
        base_timeout = TELEGRAM_BOT.get('timeout', GROUP_TIMEOUT)
        
        forwarded = await user_client.send_message(bot_entity, command)
        logger.info(f"📤 Sent to Telegram Bot: {command}")
        
        future = asyncio.get_running_loop().create_future()
        search_id = f"tgbot_{forwarded.id}_{int(time.time() * 1000)}"
        
        pending_searches[search_id] = {
            "future": future,
            "user_id": user_id,
            "query": query,
            "search_type": "telegram",
            "timestamp": time.time(),
            "message_id": forwarded.id,
            "chat_entity": bot_entity,
            "button_clicked": False
        }
        
        try:
            result_text = await asyncio.wait_for(future, timeout=base_timeout)
            
            # Check if response contains inline keyboard asking for direction
            if "выберите направление" in result_text.lower() or "select" in result_text.lower():
                logger.info(f"🔘 Inline keyboard detected, looking for Telegram button...")
                
                # Wait a bit for keyboard to load
                await asyncio.sleep(2)
                
                try:
                    # Get the message with buttons
                    messages = await user_client.get_messages(bot_entity, limit=10)
                    for msg in messages:
                        if msg.reply_to and msg.reply_to.reply_to_msg_id == forwarded.id:
                            if msg.buttons:
                                # Find and click the "Telegram" button
                                for row in msg.buttons:
                                    for button in row:
                                        button_text = button.text.lower() if hasattr(button, 'text') else ''
                                        if 'telegram' in button_text:
                                            logger.info(f"✅ Found Telegram button, clicking...")
                                            await msg.click(button)
                                            pending_searches[search_id]['button_clicked'] = True
                                            
                                            # Wait for response after clicking
                                            await asyncio.sleep(PROCESSING_WAIT_EXTRA)
                                            
                                            # Get the new response
                                            new_messages = await user_client.get_messages(bot_entity, limit=20)
                                            for new_msg in new_messages:
                                                if new_msg.reply_to and new_msg.reply_to.reply_to_msg_id == msg.id:
                                                    potential_text = new_msg.text or new_msg.raw_text
                                                    if potential_text:
                                                        result_text = potential_text
                                                        logger.info(f"📨 Got response after button click")
                                                        break
                                            break
                                    if pending_searches[search_id].get('button_clicked'):
                                        break
                                break
                except Exception as e:
                    logger.error(f"Error clicking button: {e}")
            
            # Handle processing messages
            if is_processing_message(result_text):
                logger.info(f"⏳ Processing in Telegram Bot, waiting {PROCESSING_WAIT_EXTRA}s...")
                await asyncio.sleep(PROCESSING_WAIT_EXTRA)
                
                try:
                    messages = await user_client.get_messages(bot_entity, limit=20)
                    for msg in messages:
                        if msg.reply_to and msg.reply_to.reply_to_msg_id == forwarded.id:
                            potential_text = msg.text or msg.raw_text
                            if potential_text and not is_processing_message(potential_text):
                                result_text = potential_text
                                break
                except Exception as e:
                    logger.error(f"Error getting updated bot message: {e}")
            
            if is_no_info_message(result_text) or not is_valid_result(result_text, 'telegram'):
                logger.warning(f"⚠️ No valid info from Telegram Bot")
                pending_searches.pop(search_id, None)
                return await try_api_fallback('telegram', query, user_id)
            
            cleaned = filter_links_and_usernames(result_text)
            
            if user_id:
                await log_search(user_id, "telegram", query, cleaned)
            
            pending_searches.pop(search_id, None)
            
            return {
                "success": True, 
                "result": cleaned, 
                "search_type": "telegram", 
                "source": "Telegram Bot"
            }
            
        except asyncio.TimeoutError:
            pending_searches.pop(search_id, None)
            logger.warning(f"⏱️ Timeout from Telegram Bot")
            return await try_api_fallback('telegram', query, user_id)
            
    except Exception as e:
        logger.exception(f"Error with Telegram Bot: %s", e)
        return {"success": False, "error": str(e)}

async def perform_telegram_username_search(query: str, user_id: int = None):
    """Perform telegram username search using dedicated group with daily limit"""
    
    # Check daily limit
    if user_id and await check_telegram_daily_limit(user_id):
        reset_time = await get_telegram_search_reset_time(user_id)
        return {
            "success": False, 
            "error": f"⏰ Daily telegram search limit reached (1 per day).\n\n🔄 Reset in: {reset_time}"
        }
    
    group_entity = TELEGRAM_USERNAME_GROUP.get('entity')
    
    if not group_entity:
        return {"success": False, "error": "Telegram username group not configured"}
    
    try:
        command_prefix = SEARCH_COMMANDS['telegram_username']['commands'].get(0, '/tguser')
        command = f"{command_prefix} {query}"
        base_timeout = TELEGRAM_USERNAME_GROUP.get('timeout', GROUP_TIMEOUT)
        
        forwarded = await user_client.send_message(group_entity, command)
        logger.info(f"📤 Sent to Telegram Username Group: {command}")
        
        future = asyncio.get_running_loop().create_future()
        search_id = f"tguser_{forwarded.id}_{int(time.time() * 1000)}"
        
        pending_searches[search_id] = {
            "future": future,
            "user_id": user_id,
            "query": query,
            "search_type": "telegram_username",
            "timestamp": time.time(),
            "message_id": forwarded.id,
            "chat_entity": group_entity
        }
        
        try:
            result_text = await asyncio.wait_for(future, timeout=base_timeout)
            
            # Handle processing messages
            if is_processing_message(result_text):
                logger.info(f"⏳ Processing message, waiting {PROCESSING_WAIT_EXTRA}s...")
                await asyncio.sleep(PROCESSING_WAIT_EXTRA)
                
                try:
                    messages = await user_client.get_messages(group_entity, limit=20)
                    for msg in messages:
                        if msg.reply_to and msg.reply_to.reply_to_msg_id == forwarded.id:
                            potential_text = msg.text or msg.raw_text
                            if potential_text and not is_processing_message(potential_text):
                                result_text = potential_text
                                break
                except Exception as e:
                    logger.error(f"Error getting updated message: {e}")
            
            # Handle spam messages
            if is_no_info_message(result_text):
                logger.info(f"🚫 Spam/no-info message detected, waiting for valid data...")
                await asyncio.sleep(PROCESSING_WAIT_EXTRA)
                
                try:
                    messages = await user_client.get_messages(group_entity, limit=20)
                    for msg in messages:
                        if msg.reply_to and msg.reply_to.reply_to_msg_id == forwarded.id:
                            potential_text = msg.text or msg.raw_text
                            if (potential_text and 
                                not is_no_info_message(potential_text) and 
                                not is_processing_message(potential_text) and
                                is_valid_result(potential_text, 'telegram_username')):
                                result_text = potential_text
                                logger.info(f"✅ Found valid data after spam!")
                                break
                except Exception as e:
                    logger.error(f"Error getting updated message: {e}")
            
            if is_no_info_message(result_text) or not is_valid_result(result_text, 'telegram_username'):
                logger.warning(f"⚠️ No valid info from Telegram Username Group")
                pending_searches.pop(search_id, None)
                return {"success": False, "error": "No information found for this username"}
            
            cleaned = filter_links_and_usernames(result_text)
            
            if user_id:
                await log_search(user_id, "telegram_username", query, cleaned)
            
            pending_searches.pop(search_id, None)
            
            return {
                "success": True, 
                "result": cleaned, 
                "search_type": "telegram_username", 
                "source": "Telegram Username Group"
            }
            
        except asyncio.TimeoutError:
            pending_searches.pop(search_id, None)
            logger.warning(f"⏱️ Timeout from Telegram Username Group")
            return {"success": False, "error": "Search timed out. Please try again."}
            
    except Exception as e:
        logger.exception(f"Error with Telegram Username search: %s", e)
        return {"success": False, "error": str(e)}

async def fetch_phone_api(phone_number: str):
    try:
        async with ClientSession() as session:
            headers = {"X-API-Key": PHONE_API_KEY}
            params = {"phone": phone_number}
            
            async with session.get(PHONE_API_URL, headers=headers, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return format_phone_api_response(data, phone_number)
    except Exception as e:
        logger.exception(f"Phone API error: {e}")
    return None

async def fetch_vehicle_api(vehicle_no: str):
    try:
        async with ClientSession() as session:
            headers = {"X-API-Key": VEHICLE_API_KEY}
            params = {"vehicle_number": vehicle_no}
            
            async with session.get(VEHICLE_API_URL, headers=headers, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return format_vehicle_api_response(data, vehicle_no)
    except Exception as e:
        logger.exception(f"Vehicle API error: {e}")
    return None

# ============ Keyboard Menus ============

def get_main_menu():
    buttons = []
    row = []
    for key, info in SEARCH_COMMANDS.items():
        row.append(Button.inline(info["name"], f"search_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([Button.inline("🔑 API Keys", "api_menu"), Button.inline("👥 Referrals", "referral_menu")])
    return buttons

def get_api_menu():
    return [
        [Button.inline("➕ Create API Key", "api_create")],
        [Button.inline("📋 List API Keys", "api_list")],
        [Button.inline("🔙 Back to Main Menu", "back_main")]
    ]

def get_referral_menu():
    return [
        [Button.inline("📊 My Stats", "referral_stats")],
        [Button.inline("🔗 Get Referral Link", "referral_link")],
        [Button.inline("🔙 Back to Main Menu", "back_main")]
    ]

def get_plans_menu():
    buttons = []
    for plan_key, plan_info in PLANS.items():
        buttons.append([Button.inline(
            f"{plan_info['name']} - ₹{plan_info['price']}", 
            f"buy_{plan_key}"
        )])
    buttons.append([Button.inline("❌ Cancel", "cancel")])
    return buttons

def get_payment_approval_buttons(payment_id: str, user_id: int):
    return [
        [
            Button.inline("✅ Approve", f"approve_{payment_id}_{user_id}"),
            Button.inline("❌ Reject", f"reject_{payment_id}_{user_id}")
        ]
    ]

# ============ Bot Event Handlers ============
# Replace entire function with:
@bot_client.on(events.NewMessage(pattern=r'/start( (.+))?'))
async def start_handler(event):
    user = await event.get_sender()
    user_id = user.id
    
    referral_code = None
    if event.pattern_match.group(2):
        referral_code = event.pattern_match.group(2).strip()
    
    # CREATE USER FIRST
    user_doc = await get_user(user_id)
    if not user_doc:
        await create_or_update_user(user_id, user.username, user.first_name)
        if referral_code:
            success = await apply_referral(user_id, referral_code)
            if success:
                await event.respond(
                    f"🎉 Welcome! You've successfully used a referral code!\n"
                    f"You got {NEW_USER_CREDITS} free trial credits to start with."
                )
    
    # Refresh user_doc
    user_doc = await get_user(user_id)
    
    # Admin bypass
    if user_id == ADMIN_USER_ID:
        await event.respond(
            f"👋 Welcome Admin!\n\n"
            f"You have full access to all features.\n"
            f"Use the menu below:",
            buttons=get_main_menu()
        )
        return
    
    # Check membership
    is_member = await check_channel_membership(user_id)
    
    if not is_member:
        await event.respond(
            f"👋 Welcome to Premium Info Bot!\n\n"
            f"To use this bot, you must first join our channel:\n"
            f"@{MANDATORY_CHANNEL.replace('@', '')}\n\n"
            f"After joining, click the button below to verify.",
            buttons=[
                [Button.url("📢 Join Channel", f"https://t.me/{MANDATORY_CHANNEL.replace('@', '')}")],
                [Button.inline("✅ I've Joined - Check Again", "check_membership")]
            ]
        )
        return
    
    # User is member
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: users_col.update_one(
            {"user_id": user_id},
            {"$set": {"channel_joined": True}}
        )
    )
    
    await event.respond(
        f"👋 Welcome {user.first_name}!\n\n"
        f"📊 Your Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Searches Remaining: {user_doc.get('searches_remaining', 0)}\n\n"
        f"Select an option below:",
        buttons=get_main_menu()
    )


@bot_client.on(events.CallbackQuery(pattern='^referral_menu'))
async def referral_menu_callback(event):
    await event.edit(
        "👥 Referral System\n\n"
        f"Earn {REFERRAL_REWARD} credits for each friend who uses your link!\n\n"
        "Share your referral link and when they perform their first search, you get rewarded.",
        buttons=get_referral_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^referral_link'))
async def referral_link_callback(event):
    user_id = event.sender_id
    
    referral_code = await get_or_create_referral_code(user_id)
    
    if not referral_code:
        await event.answer("❌ Error generating referral code", alert=True)
        return
    
    bot_info = await bot_client.get_me()
    bot_username = bot_info.username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    await event.edit(
        f"🔗 Your Referral Link\n\n"
        f"`{referral_link}`\n\n"
        f"Share this link with friends!\n"
        f"You'll earn {REFERRAL_REWARD} credits when they use the bot.\n\n"
        f"💡 Tip: Share on social media, groups, or with friends!",
        buttons=[[Button.inline("🔙 Back", "referral_menu")]]
    )

@bot_client.on(events.CallbackQuery(pattern='^referral_stats'))
async def referral_stats_callback(event):
    user_id = event.sender_id
    
    stats = await get_referral_stats(user_id)
    user_doc = await get_user(user_id)
    
    message = (
        f"📊 Your Referral Statistics\n\n"
        f"👥 Total Referrals: {stats['total']}\n"
        f"✅ Rewarded: {stats['rewarded']}\n"
        f"⏳ Pending: {stats['pending']}\n\n"
        f"💰 Total Earned: {stats['rewarded'] * REFERRAL_REWARD} credits\n"
        f"🔍 Current Balance: {user_doc.get('searches_remaining', 0)} credits"
    )
    
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "referral_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^api_menu'))
async def api_menu_callback(event):
    await event.edit(
        "🔑 API Key Management\n\n"
        "Manage your API keys for programmatic access:",
        buttons=get_api_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^api_create'))
async def api_create_callback(event):
    user_id = event.sender_id
    user_states[user_id] = {"action": "awaiting_api_key_name"}
    
    await event.edit(
        "➕ Create New API Key\n\n"
        "Please send a name for this API key (e.g., 'My App', 'Production Server'):"
    )

@bot_client.on(events.CallbackQuery(pattern='^api_list'))
async def api_list_callback(event):
    user_id = event.sender_id
    api_keys = await list_user_api_keys(user_id)
    
    if not api_keys:
        await event.answer("You don't have any API keys yet.", alert=True)
        return
    
    message = "📋 Your API Keys:\n\n"
    buttons = []
    
    for key_doc in api_keys:
        created = datetime.fromisoformat(key_doc['created_at']).strftime('%Y-%m-%d')
        status = "🟢 Active" if key_doc.get('active', True) else "🔴 Inactive"
        
        message += f"**{key_doc['name']}**\n"
        message += f"Key: `{key_doc['api_key'][:20]}...`\n"
        message += f"Created: {created}\n"
        message += f"Used: {key_doc.get('searches_used', 0)} times\n"
        message += f"Status: {status}\n\n"
        
        buttons.append([Button.inline(
            f"🗑️ Delete {key_doc['name']}", 
            f"api_delete_{key_doc['api_key']}"
        )])
    
    buttons.append([Button.inline("🔙 Back", "api_menu")])
    
    await event.edit(message, buttons=buttons)

@bot_client.on(events.CallbackQuery(pattern=r'^api_delete_(.+)'))
async def api_delete_callback(event):
    user_id = event.sender_id
    api_key = event.data.decode().split('_', 2)[2]
    
    success = await delete_api_key(api_key, user_id)
    
    if success:
        await event.answer("✅ API key deleted successfully", alert=True)
        await api_list_callback(event)
    else:
        await event.answer("❌ Failed to delete API key", alert=True)

async def safe_edit_message(event, text, buttons=None):
    """
    Safely edit a message, catching MessageNotModifiedError.
    This error occurs when trying to edit a message with identical content.
    """
    try:
        if buttons:
            await event.edit(text, buttons=buttons)
        else:
            await event.edit(text)
    except Exception as e:
        error_name = type(e).__name__
        if 'MessageNotModified' in error_name or 'not modified' in str(e).lower():
            # Message content is the same, no need to edit
            logger.info(f"ℹ️ Message not modified (content unchanged)")
        else:
            # Some other error, log and continue
            logger.error(f"Error editing message: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^relay_'))
async def relay_button_callback(event):
    """
    Handle user button clicks and relay them to the destination bot.
    Then forward the response back to the user.
    """
    user_id = event.sender_id
    
    if user_id not in interactive_sessions:
        await event.answer("❌ Session expired. Please start a new search.", alert=True)
        return
    
    session = interactive_sessions[user_id]
    dest_message = session['dest_message']
    dest_entity = session['dest_entity']
    search_type = session['type']
    
    try:
        # Extract which button was clicked
        callback_data = event.data.decode()
        
        # Find and click the corresponding button in destination bot
        button_clicked = False
        
        # For telegram bot (text-based matching)
        if search_type == "telegram":
            button_text = callback_data.replace('relay_', '').replace('_', ' ')
            
            for row_idx, row in enumerate(dest_message.buttons):
                for col_idx, button in enumerate(row):
                    if hasattr(button, 'text') and button.text.lower() == button_text.lower():
                        logger.info(f"🔘 Clicking button '{button.text}' in destination bot")
                        await event.answer(f"⏳ Fetching from {button.text}...")
                        
                        # Click the button by position
                        await dest_message.click(row_idx, col_idx)
                        button_clicked = True
                        break
                if button_clicked:
                    break
        
        # For movie bot (position-based matching)
        elif search_type == "movie":
            # Extract row and col from callback data (format: relay_row_col)
            parts = callback_data.split('_')
            if len(parts) >= 3:
                row_idx = int(parts[1])
                col_idx = int(parts[2])
                
                if row_idx < len(dest_message.buttons) and col_idx < len(dest_message.buttons[row_idx]):
                    logger.info(f"🎬 Clicking button at position [{row_idx}][{col_idx}]")
                    await event.answer("⏳ Fetching file...")
                    
                    # Click the button using row and column indices
                    await dest_message.click(row_idx, col_idx)
                    button_clicked = True
        
        if not button_clicked:
            await event.answer("❌ Button not found", alert=True)
            return
        
        # Wait for response from destination bot - check multiple times
        logger.info(f"⏳ Waiting for response after button click...")
        
        # Try multiple times to get response (some bots are slow)
        for attempt in range(3):  # Try 3 times
            await asyncio.sleep(3 if attempt == 0 else 2)  # Wait 3s first, then 2s each
            
            logger.info(f"🔍 Checking for response (attempt {attempt + 1}/3)...")
            
            # Strategy 1: Check if original message was edited
            try:
                updated_msg = await user_client.get_messages(dest_entity, ids=dest_message.id)
                
                logger.info(f"🔄 Checking original message (ID: {dest_message.id})")
                if updated_msg:
                    logger.info(f"   - Has edit_date: {bool(updated_msg.edit_date)}")
                    logger.info(f"   - Has buttons: {bool(updated_msg.buttons)} (was: {bool(dest_message.buttons)})")
                    logger.info(f"   - Has file: {bool(updated_msg.file)}")
                    logger.info(f"   - Text length: {len(updated_msg.text) if updated_msg.text else 0}")
                
                # Check if message was edited AND has changed content
                if updated_msg and updated_msg.edit_date:
                    # Check if buttons changed or disappeared
                    buttons_changed = False
                    buttons_gone = False
                    
                    if not updated_msg.buttons and dest_message.buttons:
                        buttons_gone = True
                        logger.info(f"🔘 Buttons removed from message - likely final result")
                    elif updated_msg.buttons and dest_message.buttons:
                        # Check if button count changed
                        if len(updated_msg.buttons) != len(dest_message.buttons):
                            buttons_changed = True
                            logger.info(f"🔘 Button count changed - pagination detected")
                    
                    # If buttons gone, this is likely the final result
                    if buttons_gone:
                        logger.info(f"✅ Found final result in edited message (buttons removed)")
                        interactive_sessions.pop(user_id, None)
                        user_states.pop(user_id, None)
                        
                        if updated_msg.file:
                            await event.answer("✅ File received!")
                            logger.info(f"📁 Forwarding file to user")
                            
                            if updated_msg.text:
                                await bot_client.send_message(user_id, f"✅ Result:\n\n{updated_msg.text}")
                            
                            await bot_client.forward_messages(user_id, updated_msg)
                        elif updated_msg.text and len(updated_msg.text.strip()) >= 10:
                            logger.info(f"📝 Sending text result to user")
                            await safe_edit_message(event, f"✅ Result:\n\n{updated_msg.text.strip()}")
                        
                        # Deduct credit
                        if user_id != ADMIN_USER_ID:
                            user_doc = await get_user(user_id)
                            if user_doc.get('plan') != 'unlimited':
                                await decrement_search(user_id)
                        return
                    
                    # If buttons changed (pagination), show new buttons
                    elif buttons_changed or updated_msg.buttons:
                        if updated_msg.buttons:
                            logger.info(f"🔘 Found pagination buttons in edited message")
                            session['dest_message'] = updated_msg
                            
                            user_buttons = []
                            for row in updated_msg.buttons:
                                button_row = []
                                for button in row:
                                    if hasattr(button, 'text'):
                                        button_row.append(Button.inline(
                                            button.text,
                                            f"relay_{len(user_buttons)}_{len(button_row)}"
                                        ))
                                if button_row:
                                    user_buttons.append(button_row)
                            
                            await safe_edit_message(
                                event,
                                updated_msg.text or updated_msg.raw_text or "Select an option:",
                                buttons=user_buttons
                            )
                            return
                
            except Exception as e:
                logger.warning(f"Could not check edited message: {e}")
            
            # Strategy 2: Look for new messages from bot
            try:
                messages = await user_client.get_messages(dest_entity, limit=30)
                
                for msg in messages:
                    # Skip original message
                    if msg.id == dest_message.id:
                        continue
                    
                    # Check if message is very recent (within last 15 seconds)
                    if msg.date and msg.date.timestamp() > (time.time() - 15):
                        logger.info(f"📨 Found recent message (ID: {msg.id})")
                        logger.info(f"   - Has buttons: {bool(msg.buttons)}")
                        logger.info(f"   - Has file: {bool(msg.file)}")
                        logger.info(f"   - Text length: {len(msg.text) if msg.text else 0}")
                        logger.info(f"   - Text preview: {(msg.text[:50] + '...') if msg.text and len(msg.text) > 50 else msg.text}")
                        
                        # Check if it has pagination buttons
                        if msg.buttons:
                            logger.info(f"🔘 Message has {len(msg.buttons)} button rows - pagination")
                            session['dest_message'] = msg
                            
                            user_buttons = []
                            for row in msg.buttons:
                                button_row = []
                                for button in row:
                                    if hasattr(button, 'text'):
                                        button_row.append(Button.inline(
                                            button.text,
                                            f"relay_{len(user_buttons)}_{len(button_row)}"
                                        ))
                                if button_row:
                                    user_buttons.append(button_row)
                            
                            await safe_edit_message(
                                event,
                                msg.text or msg.raw_text or "Select an option:",
                                buttons=user_buttons
                            )
                            return
                        
                        # Check if it's a final result (file OR any text)
                        # Lowered threshold from 20 to 10 chars to catch more results
                        if msg.file or (msg.text and len(msg.text.strip()) >= 10):
                            logger.info(f"✅ Found final result message (file={bool(msg.file)}, text_len={len(msg.text) if msg.text else 0})")
                            interactive_sessions.pop(user_id, None)
                            user_states.pop(user_id, None)
                            
                            if msg.file:
                                await event.answer("✅ File received!")
                                logger.info(f"📁 Forwarding file to user")
                                
                                if msg.text:
                                    await bot_client.send_message(user_id, f"✅ Result:\n\n{msg.text}")
                                
                                await bot_client.forward_messages(user_id, msg)
                            elif msg.text:
                                logger.info(f"📝 Sending text result to user")
                                await safe_edit_message(event, f"✅ Result:\n\n{msg.text.strip()}")
                            
                            # Deduct credit
                            if user_id != ADMIN_USER_ID:
                                user_doc = await get_user(user_id)
                                if user_doc.get('plan') != 'unlimited':
                                    await decrement_search(user_id)
                            return
                        else:
                            logger.info(f"⚠️ Message found but not recognized as result (no buttons, no file, text too short)")
            
            except Exception as e:
                logger.warning(f"Could not check new messages: {e}")
            
            # If this isn't the last attempt, continue loop
            if attempt < 2:
                logger.info(f"⏳ No response yet, will try again...")
        
        # After all attempts, no response found
        logger.warning(f"❌ No response found after 3 attempts")
        await event.answer("❌ No response received from bot. Please try again.", alert=True)
        interactive_sessions.pop(user_id, None)
    
    except Exception as e:
        logger.exception(f"Error in relay button callback: {e}")
        await event.answer("❌ An error occurred", alert=True)
        interactive_sessions.pop(user_id, None)

@bot_client.on(events.CallbackQuery(pattern='^back_main'))
async def back_main_callback(event):
    user = await event.get_sender()
    user_id = user.id
    user_doc = await get_user(user_id)
    
    if user_id == ADMIN_USER_ID:
        await event.edit(
            f"👋 Welcome Admin!\n\n"
            f"You have full access to all features.\n"
            f"Use the menu below:",
            buttons=get_main_menu()
        )
        return
    
    await event.edit(
        f"👋 Welcome {user.first_name}!\n\n"
        f"📊 Your Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Searches Remaining: {user_doc.get('searches_remaining', 0)}\n\n"
        f"Select an option below:",
        buttons=get_main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)'))
async def search_callback(event):
    user_id = event.sender_id
    search_type = event.data.decode().split('_')[1]
    
    if user_id == ADMIN_USER_ID:
        user_states[user_id] = {"action": "awaiting_input", "type": search_type}
        try:
            await event.edit(
                f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
                f"Please send the {search_type} to search:"
            )
        except Exception:
            await event.answer()
            await bot_client.send_message(
                user_id,
                f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
                f"Please send the {search_type} to search:"
            )
        return
    
    user_doc = await get_user(user_id)
    
    if not user_doc:
        await event.answer("❌ Error: User not found", alert=True)
        return
    
    searches_remaining = user_doc.get('searches_remaining', 0)
    plan = user_doc.get('plan', 'free')
    plan_expiry = user_doc.get('plan_expiry')
    
    if plan == 'unlimited' and plan_expiry:
        expiry_dt = datetime.fromisoformat(plan_expiry)
        if expiry_dt < datetime.now(timezone.utc):
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"plan": "free", "searches_remaining": 0}}
                )
            )
            searches_remaining = 0
    
    if searches_remaining <= 0 and plan != 'unlimited':
        try:
            await event.edit(
                "❌ Access Not Granted\n\n"
                "You must buy a premium pack to use this bot.\n\n"
                "Select a plan below:",
                buttons=get_plans_menu()
            )
        except Exception:
            await event.answer("❌ Access Not Granted", alert=True)
        return
    
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}
    try:
        await event.edit(
            f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
            f"Searches Remaining: {searches_remaining if searches_remaining > 0 else 'Unlimited'}\n\n"
            f"Please send the {search_type} to search:"
        )
    except Exception:
        await event.answer()
        await bot_client.send_message(
            user_id,
            f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
            f"Searches Remaining: {searches_remaining if searches_remaining > 0 else 'Unlimited'}\n\n"
            f"Please send the {search_type} to search:"
        )

@bot_client.on(events.CallbackQuery(pattern=r'^buy_(.+)'))
async def buy_plan_callback(event):
    user_id = event.sender_id
    plan_key = event.data.decode().split('_', 1)[1]
    
    if plan_key not in PLANS:
        await event.answer("❌ Invalid plan", alert=True)
        return
    
    plan_info = PLANS[plan_key]
    payment_id = await create_payment_request(user_id, plan_key, plan_info['price'])
    
    if not payment_id:
        await event.answer("❌ Error creating payment request", alert=True)
        return
    
    user_states[user_id] = {"action": "awaiting_payment", "payment_id": payment_id, "plan": plan_key}
    
    try:
        user = await event.get_sender()
        await bot_client.send_message(
            ADMIN_USER_ID,
            f"💰 New Payment Request\n\n"
            f"User: {user.first_name} (@{user.username or 'N/A'})\n"
            f"User ID: {user_id}\n"
            f"Plan: {plan_info['name']}\n"
            f"Amount: ₹{plan_info['price']}\n"
            f"Payment ID: {payment_id}\n\n"
            f"Waiting for payment screenshot..."
        )
    except Exception as e:
        logger.exception("Error notifying admin: %s", e)
    
    await event.edit(
        f"💳 Payment Required\n\n"
        f"Plan: {plan_info['name']}\n"
        f"Amount: ₹{plan_info['price']}\n\n"
        f"Please scan the QR code below and send the payment screenshot:\n\n"
        f"Payment ID: `{payment_id}`",
        buttons=[[Button.inline("❌ Cancel", "cancel")]]
    )
    
    try:
        await bot_client.send_file(event.sender_id, PAYMENT_QR_CODE, caption="Scan to pay")
    except Exception as e:
        logger.exception("Error sending QR code: %s", e)
        await event.respond("Please pay and send screenshot.")

@bot_client.on(events.CallbackQuery(pattern=r'^approve_(.+)_(.+)'))
async def approve_payment_callback(event):
    if event.sender_id != ADMIN_USER_ID:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    payment_id = data_parts[1]
    target_user_id = int(data_parts[2])
    
    payment = await asyncio.get_running_loop().run_in_executor(
        None, payments_col.find_one, {"payment_id": payment_id}
    )
    
    if not payment:
        await event.answer("❌ Payment not found", alert=True)
        return
    
    plan_key = payment['plan']
    plan_info = PLANS[plan_key]
    
    if plan_info['searches'] == -1:
        await update_user_plan(target_user_id, "unlimited", 999999, plan_info['days'])
    else:
        user_doc = await get_user(target_user_id)
        current_searches = user_doc.get('searches_remaining', 0)
        await update_user_plan(target_user_id, "paid", current_searches + plan_info['searches'])
    
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: payments_col.update_one(
            {"payment_id": payment_id},
            {"$set": {"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat()}}
        )
    )
    
    await event.edit(
        f"✅ Payment Approved\n\n"
        f"Payment ID: {payment_id}\n"
        f"User ID: {target_user_id}\n"
        f"Plan: {plan_info['name']}"
    )
    
    try:
        await bot_client.send_message(
            target_user_id,
            f"✅ Payment Approved!\n\n"
            f"Your {plan_info['name']} plan has been activated.\n"
            f"Use /start to begin searching.",
            buttons=[[Button.inline("🚀 Start Searching", "start")]]
        )
    except Exception as e:
        logger.exception("Error notifying user: %s", e)

@bot_client.on(events.CallbackQuery(pattern=r'^reject_(.+)_(.+)'))
async def reject_payment_callback(event):
    if event.sender_id != ADMIN_USER_ID:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    payment_id = data_parts[1]
    target_user_id = int(data_parts[2])
    
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: payments_col.update_one(
            {"payment_id": payment_id},
            {"$set": {"status": "rejected", "rejected_at": datetime.now(timezone.utc).isoformat()}}
        )
    )
    
    await event.edit(f"❌ Payment Rejected\n\nPayment ID: {payment_id}")
    
    try:
        await bot_client.send_message(
            target_user_id,
            "❌ Payment Rejected\n\n"
            "Your payment was not approved. Please contact support or try again."
        )
    except Exception as e:
        logger.exception("Error notifying user: %s", e)

@bot_client.on(events.CallbackQuery(pattern='^cancel'))
async def cancel_callback(event):
    user_id = event.sender_id
    user_states.pop(user_id, None)
    await event.edit(
        "❌ Cancelled\n\nUse /start to begin again.",
        buttons=None
    )

@bot_client.on(events.CallbackQuery(pattern='^check_membership'))
async def check_membership_callback(event):
    user_id = event.sender_id
    
    # Check if user joined the channel
    is_member = await check_channel_membership(user_id)
    
    if not is_member:
        await event.answer(
            "❌ You haven't joined the channel yet. Please join and try again.",
            alert=True
        )
        return
    
    # User has joined! Update database and show main menu
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: users_col.update_one(
            {"user_id": user_id},
            {"$set": {"channel_joined": True}}
        )
    )
    
    user_doc = await get_user(user_id)
    user = await event.get_sender()
    
    await event.edit(
        f"✅ Great! You've joined the channel!\n\n"
        f"👋 Welcome {user.first_name}!\n\n"
        f"📊 Your Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Searches Remaining: {user_doc.get('searches_remaining', 0)}\n\n"
        f"Select an option below:",
        buttons=get_main_menu()
    )

# Replace entire function with:
@bot_client.on(events.CallbackQuery(pattern='^check_membership'))
async def check_membership_callback(event):
    user_id = event.sender_id
    
    # Ensure user exists
    user_doc = await get_user(user_id)
    if not user_doc:
        user = await event.get_sender()
        await create_or_update_user(user_id, user.username, user.first_name)
        user_doc = await get_user(user_id)
    
    # Check membership
    is_member = await check_channel_membership(user_id)
    
    if not is_member:
        await event.answer(
            "❌ You haven't joined the channel yet. Please join and try again.",
            alert=True
        )
        return
    
    # Update DB
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: users_col.update_one(
            {"user_id": user_id},
            {"$set": {"channel_joined": True}}
        )
    )
    
    user = await event.get_sender()
    
    await event.edit(
        f"✅ Great! You've joined the channel!\n\n"
        f"👋 Welcome {user.first_name}!\n\n"
        f"📊 Your Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Searches Remaining: {user_doc.get('searches_remaining', 0)}\n\n"
        f"Select an option below:",
        buttons=get_main_menu()
    )

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state.get('action') == 'awaiting_api_key_name':
        key_name = event.text.strip()
        
        if len(key_name) < 3:
            await event.respond("❌ Name must be at least 3 characters. Please try again:")
            return
        
        user_doc = await get_user(user_id)
        
        api_key = await create_api_key(user_id, key_name)
        
        if api_key:
            if user_doc.get('plan') == 'unlimited':
                credits_info = "Unlimited credits ♾️"
            else:
                credits_info = f"{user_doc.get('searches_remaining', 0)} credits remaining"
            
            await event.respond(
                f"✅ API Key Created Successfully!\n\n"
                f"**Name:** {key_name}\n"
                f"**API Key:** `{api_key}`\n"
                f"**Your Credits:** {credits_info}\n\n"
                f"⚠️ **Important:** \n"
                f"• Save this key securely\n"
                f"• API uses YOUR account credits\n"
                f"• Recharge to get more credits\n\n"
                f"**Usage Example:**\n"
                f"```bash\n"
                f"curl -X POST https://your-domain.com/api/search \\\n"
                f"  -H 'X-API-Key: {api_key}' \\\n"
                f"  -H 'Content-Type: application/json' \\\n"
                f"  -d '{{\n"
                f'    "search_type": "phone",\n'
                f'    "query": "1234567890"\n'
                f"  }}'\n"
                f"```",
                buttons=[[Button.inline("🔙 Back to API Menu", "api_menu")]]
            )
        else:
            await event.respond(
                "❌ Failed to create API key. Please try again.",
                buttons=[[Button.inline("🔙 Back to API Menu", "api_menu")]]
            )
        
        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_payment':
        if not event.photo:
            await event.respond("❌ Please send a screenshot image.")
            return

        payment_id = state['payment_id']
        plan_key = state['plan']
        plan_info = PLANS[plan_key]

        await update_payment_screenshot(payment_id, event.message.id)

        try:
            user = await event.get_sender()
            await bot_client.send_file(
                ADMIN_USER_ID,
                event.photo,
                caption=(
                    f"💰 Payment Screenshot Received\n\n"
                    f"User: {user.first_name} (@{user.username or 'N/A'})\n"
                    f"User ID: {user_id}\n"
                    f"Plan: {plan_info['name']}\n"
                    f"Amount: ₹{plan_info['price']}\n"
                    f"Payment ID: {payment_id}"
                ),
                buttons=get_payment_approval_buttons(payment_id, user_id)
            )
        except Exception as e:
            logger.exception("Error forwarding to admin: %s", e)

        await event.respond(
            "✅ Payment screenshot received!\n\n"
            "Your payment is being reviewed. You'll be notified once approved."
        )

        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_input':
        search_type = state['type']
        query = event.text.strip()

        status_msg = await event.respond("⏳ Fetching information... Please wait.")

        user_doc = await get_user(user_id)
        is_first_search = (
            user_doc.get('total_searches', 0) == 0
            and user_doc.get('referred_by')
        )

        result = await perform_search(search_type, query, user_id)

        try:
            await status_msg.delete()
        except:
            pass

        if result['success']:
            # Check if result has a file (for movie bot)
            if result.get('file'):
                file_msg = result['file']
                await event.respond(f"✅ Search Result:\n\n{result['result']}")
                
                # Forward the file
                try:
                    await bot_client.forward_messages(user_id, file_msg)
                except Exception as e:
                    logger.error(f"Error forwarding file: {e}")
            else:
                await event.respond(f"✅ Search Result:\n\n{result['result']}")

            if user_id != ADMIN_USER_ID:
                user_doc = await get_user(user_id)
                if user_doc.get('plan') != 'unlimited':
                    await decrement_search(user_id)

                if is_first_search:
                    await reward_referrer(user_id)
        elif result.get('needs_interaction'):
            # Interactive search - show buttons to user
            await event.respond(
                result['message'],
                buttons=result['buttons']
            )
            # Don't pop user_states - user still needs to click button
            return
        else:
            error_msg = result.get('error', 'An error occurred')
            await event.respond(f"❌ {error_msg}")

        user_states.pop(user_id, None)

# ============ Enhanced Message Handler for All Groups and Bots ============

@user_client.on(events.NewMessage())
async def handle_all_replies(event):
    message = event.message
    
    if not message.reply_to:
        return
    
    # Handle both text messages and files (TXT files for family info)
    text = message.text or message.raw_text
    has_file = message.file is not None
    
    # Skip if neither text nor file
    if not text and not has_file:
        return
    
    now = time.time()
    
    matched_search = None
    matched_key = None
    
    for search_id, search_info in list(pending_searches.items()):
        if search_info['future'].done():
            continue
        
        if now - search_info.get("timestamp", now) > REPLY_TIMEOUT:
            continue
        
        if message.reply_to.reply_to_msg_id == search_info.get('message_id'):
            matched_search = search_info
            matched_key = search_id
            logger.info(f"🎯 Reply matched for search_id: {search_id}")
            break
    
    if not matched_search:
        for search_id, search_info in list(pending_searches.items()):
            if search_info['future'].done():
                continue
            
            if now - search_info.get("timestamp", now) > REPLY_TIMEOUT:
                continue
            
            query = search_info['query'].strip()
            search_type = search_info['search_type']
            
            # PRIORITY 1: Check for file messages first (family TXT files)
            # This must be checked BEFORE text matching because messages can have both file + caption
            if has_file and search_type == 'family':
                logger.info(f"📄 Checking file message for family search")
                # Check if query number is in the caption or message text
                caption = message.caption or ""
                full_text = f"{text or ''} {caption}".lower()
                clean_query = re.sub(r'[^\d]', '', query)
                
                # Also check filename
                file_name = message.file.name or ""
                full_text_with_filename = f"{full_text} {file_name}".lower()
                
                if clean_query and len(clean_query) >= 10:
                    if clean_query in re.sub(r'[^\d]', '', full_text_with_filename):
                        matched_search = search_info
                        matched_key = search_id
                        logger.info(f"🎯 Family file match for search_id: {search_id} (file: {file_name})")
                        break
                # Also match if it's just a recent family search file (no number in caption)
                elif message.file.mime_type == 'text/plain' or file_name.lower().endswith('.txt'):
                    # It's a TXT file for a pending family search
                    matched_search = search_info
                    matched_key = search_id
                    logger.info(f"🎯 Family file match by type for search_id: {search_id}")
                    break
            
            # PRIORITY 2: For text messages, check content
            if text and not matched_search:
                message_text_lower = text.lower()
                is_match = False
                
                if search_type in ['phone', 'telegram', 'family']:
                    clean_query = re.sub(r'[^\d]', '', query)
                    clean_msg = re.sub(r'[^\d]', '', text)
                    if clean_query and len(clean_query) >= 10 and clean_query in clean_msg:
                        is_match = True
                        
                elif search_type == 'aadhar':
                    clean_query = re.sub(r'[^\d]', '', query)
                    if len(clean_query) == 12 and clean_query in re.sub(r'[^\d]', '', text):
                        is_match = True
                        
                elif search_type in ['vehicle', 'vehicle_detail']:
                    clean_query = re.sub(r'[^a-z0-9]', '', query.lower())
                    clean_msg = re.sub(r'[^a-z0-9]', '', message_text_lower)
                    if clean_query and len(clean_query) >= 6 and clean_query in clean_msg:
                        is_match = True
                
                elif query.lower() in message_text_lower:
                    is_match = True
                
                if is_match:
                    matched_search = search_info
                    matched_key = search_id
                    logger.info(f"🎯 Content match for search_id: {search_id}")
                    break
    
    if not matched_search:
        return
    
    # For text messages, check for processing/spam
    if text:
        if is_processing_message(text):
            logger.info(f"⏳ Processing message detected for {matched_key}, ignoring for now")
            return
        
        # NEW: Skip spam/no-info messages - don't deliver them, wait for valid data
        if is_no_info_message(text):
            logger.info(f"🚫 Spam/no-info message detected for {matched_key}, waiting for valid data")
            return
    
    await asyncio.sleep(FETCH_WAIT_TIME)
    
    # Handle file messages (TXT files for family info)
    if has_file and matched_search['search_type'] == 'family':
        try:
            # Check if it's a TXT file
            file_name = message.file.name or ""
            if file_name.lower().endswith('.txt') or message.file.mime_type == 'text/plain':
                logger.info(f"📄 Downloading family TXT file: {file_name}")
                
                # Download the file
                file_bytes = await message.download_media(bytes)
                
                # Extract text from file
                try:
                    file_text = file_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    # Try other encodings
                    try:
                        file_text = file_bytes.decode('latin-1')
                    except:
                        file_text = file_bytes.decode('utf-8', errors='ignore')
                
                # Extract only family members (remove headers/footers)
                family_members = extract_family_members(file_text)
                
                if family_members and not matched_search['future'].done():
                    matched_search['future'].set_result(family_members)
                    logger.info(f"📨 Delivered extracted family info for search {matched_key}")
                    return
        except Exception as e:
            logger.error(f"Error processing family TXT file: {e}")
            # Fall back to text if file processing fails
    
    # Handle text messages
    if text:
        try:
            chat = await event.get_chat()
            latest = await user_client.get_messages(chat, ids=message.id)
            if latest:
                final_text = latest.text or latest.raw_text
                if final_text:
                    text = final_text
        except Exception as e:
            logger.error(f"Error getting latest message: {e}")
        
        # Double-check: don't deliver if it's still a spam/no-info message after fetch
        if is_no_info_message(text):
            logger.info(f"🚫 Final check: Still spam/no-info for {matched_key}, skipping")
            return
        
        if not matched_search['future'].done():
            matched_search['future'].set_result(text)
            logger.info(f"📨 Delivered result for search {matched_key}")

# ============ Cleanup Task ============

async def cleanup_old_searches():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        to_remove = []
        
        for search_id, info in list(pending_searches.items()):
            age = now - info.get('timestamp', now)
            
            if age > REPLY_TIMEOUT:
                if not info['future'].done():
                    try:
                        info['future'].set_exception(TimeoutError("Search expired - cleaned up"))
                        logger.warning(f"⚠️ Force-cleaned expired search {search_id} (age: {age:.1f}s)")
                    except Exception as e:
                        logger.error(f"Error setting exception for {search_id}: {e}")
                to_remove.append(search_id)
        
        for search_id in to_remove:
            pending_searches.pop(search_id, None)
        
        if to_remove:
            logger.info(f"🧹 Cleanup: Removed {len(to_remove)} expired searches")
        
        if pending_searches:
            logger.info(f"📊 Active searches: {len(pending_searches)}")

# ============ API Endpoints ============

async def verify_api_key(request):
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        return web.json_response(
            {"success": False, "error": "Missing API key"},
            status=401
        )
    
    key_info = await get_api_key_info(api_key)
    
    if not key_info:
        return web.json_response(
            {"success": False, "error": "Invalid API key"},
            status=401
        )
    
    if not key_info.get('active', True):
        return web.json_response(
            {"success": False, "error": "API key is inactive"},
            status=401
        )
    
    user_id = key_info['user_id']
    user_doc = await get_user(user_id)
    
    if not user_doc:
        return web.json_response(
            {"success": False, "error": "User not found"},
            status=404
        )
    
    if user_doc.get('plan') != 'unlimited':
        searches_remaining = user_doc.get('searches_remaining', 0)
        if searches_remaining <= 0:
            return web.json_response(
                {
                    "success": False, 
                    "error": "API creator has no credits remaining. Please recharge your account.",
                    "creator_credits": 0
                },
                status=403
            )
    
    request['api_key_info'] = key_info
    request['user_doc'] = user_doc
    return None

async def api_search_handler(request):
    auth_error = await verify_api_key(request)
    if auth_error:
        return auth_error
    
    key_info = request['api_key_info']
    user_doc = request['user_doc']
    
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON"},
            status=400
        )
    
    search_type = data.get('search_type')
    query = data.get('query')
    
    if not search_type or not query:
        return web.json_response(
            {"success": False, "error": "Missing search_type or query"},
            status=400
        )
    
    if search_type not in SEARCH_COMMANDS:
        return web.json_response(
            {"success": False, "error": f"Invalid search_type. Valid types: {list(SEARCH_COMMANDS.keys())}"},
            status=400
        )
    
    user_id = key_info['user_id']
    result = await perform_search(search_type, query, user_id)
    
    if result['success']:
        await increment_api_key_usage(key_info['api_key'])
        
        if user_doc.get('plan') != 'unlimited':
            await decrement_search(user_id)
            updated_user = await get_user(user_id)
            remaining_credits = updated_user.get('searches_remaining', 0)
        else:
            remaining_credits = -1
        
        return web.json_response({
            "success": True,
            "search_type": search_type,
            "query": query,
            "result": result['result'],
            "source": result.get('source', 'primary'),
            "creator_credits_remaining": remaining_credits
        })
    else:
        return web.json_response(result, status=500)

async def api_info_handler(request):
    auth_error = await verify_api_key(request)
    if auth_error:
        return auth_error
    
    key_info = request['api_key_info']
    user_doc = request['user_doc']
    
    if user_doc.get('plan') == 'unlimited':
        credits_remaining = -1
        plan_status = "Unlimited"
    else:
        credits_remaining = user_doc.get('searches_remaining', 0)
        plan_status = user_doc.get('plan', 'free').upper()
    
    return web.json_response({
        "success": True,
        "api_key_name": key_info['name'],
        "created_at": key_info['created_at'],
        "api_searches_used": key_info.get('searches_used', 0),
        "last_used": key_info.get('last_used'),
        "creator_plan": plan_status,
        "creator_credits_remaining": credits_remaining,
        "note": "API uses creator's account credits. Recharge your account to get more credits."
    })

async def api_types_handler(request):
    return web.json_response({
        "success": True,
        "search_types": {
            key: info['name'] 
            for key, info in SEARCH_COMMANDS.items()
        }
    })

async def health_check(request):
    return web.Response(text="OK", status=200)

# ============ Web Server ============

async def start_web_server():
    app = web.Application()
    
    app.router.add_get("/health", health_check)
    app.router.add_post("/api/search", api_search_handler)
    app.router.add_get("/api/info", api_info_handler)
    app.router.add_get("/api/types", api_types_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web server started on port {PORT}")

# ============ Main ============

async def start_bot():
    try:
        logger.info("🤖 Starting Telegram bot...")
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot started successfully")
        
        me = await bot_client.get_me()
        logger.info(f"Bot username: @{me.username}")
        
        if USE_USER_ACCOUNT:
            logger.info("👤 Starting user account client...")
            if not user_client.is_connected():
                await user_client.connect()
            
            if not await user_client.is_user_authorized():
                raise RuntimeError("❌ User session not authorized")
            
            logger.info("✅ User account session loaded")

        logger.info("📡 Resolving destination groups...")
        
        for idx, group in enumerate(DESTINATION_GROUPS):
            try:
                group['entity'] = await user_client.get_entity(group['identifier'])
                logger.info(f"✅ Group {idx} ({group['name']}): {group['identifier']}")
            except Exception as e:
                logger.warning(f"❌ Could not resolve group {idx}: {e}")
        
        try:
            VEHICLE_GROUP['entity'] = await user_client.get_entity(VEHICLE_GROUP['identifier'])
            logger.info(f"✅ Vehicle Group: {VEHICLE_GROUP['identifier']}")
        except Exception as e:
            logger.warning(f"❌ Could not resolve vehicle group: {e}")
        
        try:
            FAMILY_GROUP['entity'] = await user_client.get_entity(FAMILY_GROUP['identifier'])
            logger.info(f"✅ Family Group: {FAMILY_GROUP['identifier']}")
        except Exception as e:
            logger.warning(f"❌ Could not resolve family group: {e}")
        
        try:
            TELEGRAM_BOT['entity'] = await user_client.get_entity(TELEGRAM_BOT['identifier'])
            logger.info(f"✅ Telegram Bot: {TELEGRAM_BOT['identifier']}")
        except Exception as e:
            logger.warning(f"❌ Could not resolve telegram bot: {e}")
        
        try:
            TELEGRAM_USERNAME_GROUP['entity'] = await user_client.get_entity(TELEGRAM_USERNAME_GROUP['identifier'])
            logger.info(f"✅ Telegram Username Group: {TELEGRAM_USERNAME_GROUP['identifier']}")
        except Exception as e:
            logger.warning(f"❌ Could not resolve telegram username group: {e}")
        
        try:
            MOVIE_BOT['entity'] = await user_client.get_entity(MOVIE_BOT['identifier'])
            logger.info(f"✅ Movie Bot: {MOVIE_BOT['identifier']}")
        except Exception as e:
            logger.warning(f"❌ Could not resolve movie bot: {e}")

        init_mongo()
        
        asyncio.create_task(cleanup_old_searches())
        asyncio.create_task(start_web_server())

        logger.info("🚀 Bot is fully operational")
        logger.info(f"⏱️ Group timeout: {GROUP_TIMEOUT}s per group")
        logger.info(f"⏳ Processing wait: {PROCESSING_WAIT_EXTRA}s")
        logger.info(f"💰 New users get {NEW_USER_CREDITS} free credits")
        logger.info(f"🔍 Smart detection: Processing & No-info messages")
        logger.info(f"🔄 Cascading fallback: Groups → API")

        await asyncio.Event().wait()

    except Exception as e:
        logger.exception("❌ Fatal error: %s", e)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
