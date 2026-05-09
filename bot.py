"""
DarkBoxes Intelligence System - Premium Edition
Advanced information retrieval with premium interface
Professional Admin Panel
"""

import os
import sys
import re
import json
import time
import uuid
import hashlib  # <-- Add this line here
import logging
import asyncio
import secrets
import traceback
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from collections import Counter, defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO

# Third-party imports
try:
    from aiohttp import web
    from telethon import TelegramClient, events, Button
    from telethon.sessions import StringSession
    from telethon.tl.types import PeerChannel, PeerUser, Channel, User, MessageMediaDocument
    from telethon.tl.functions.channels import GetParticipantRequest
    from pymongo import MongoClient
    import pandas as pd
    from bson import ObjectId
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install telethon aiohttp pymongo pandas matplotlib")
    sys.exit(1)

# ================== CONFIGURATION ==================

@dataclass
class BotConfig:
    # Server
    PORT: int = int(os.getenv("PORT", "10000"))
    
    # Bot credentials
    BOT_API_ID: int = int(os.getenv("API_ID", "0"))
    BOT_API_HASH: str = os.getenv("API_HASH", "").strip()
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    BOT_SESSION_FILE: str = "bot_session.session"
    BOT_SESSION_STRING: str = os.getenv("BOT_SESSION_STRING", "").strip()
    
    # User account (for relaying)
    USER_API_ID: int = int(os.getenv("USER_API_ID", "0"))
    USER_API_HASH: str = os.getenv("API_HASH", "").strip()
    USER_PHONE: str = os.getenv("USER_PHONE", "").strip()
    USER_SESSION_FILE: str = "relay_session.session"
    USER_SESSION_STRING: str = os.getenv("USER_SESSION_STRING", "").strip()
    
    # Admin and mandatory channel
    ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))
    MANDATORY_CHANNEL: str = os.getenv("MANDATORY_CHANNEL", "darkboxesv1")
    
    # Database
    MONGODB_URI: str = os.getenv("MONGODB_URI", "").strip()
    MONGODB_DBNAME: str = "darkboxes_db"
    
    # Timeouts and limits
    GROUP_TIMEOUT: int = int(os.getenv("GROUP_TIMEOUT", "45"))
    FETCH_WAIT_TIME: int = int(os.getenv("FETCH_WAIT_TIME", "3"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
    
    # Credits and rewards
    NEW_USER_CREDITS: int = int(os.getenv("NEW_USER_CREDITS", "1"))
    REFERRAL_REWARD: int = int(os.getenv("REFERRAL_REWARD", "1"))
    
    # Payment
    UPI_ID: str = os.getenv("UPI_ID", "darkboxes@ybl")
    ADMIN_CONTACT: str = "@darkboxesAdmin"
    
    # Payment — UPI only (manual admin approval)
    # Instamojo removed: credentials were exposed in payment links
    INSTAMOJO_API_KEY:    str = ""
    INSTAMOJO_AUTH_TOKEN: str = ""
    INSTAMOJO_BASE_URL:   str = ""
    PAYMENT_RETURN_URL:   str = ""

    # API Configuration
    API_ENABLED: bool = bool(os.getenv("API_ENABLED", "True"))
    INTELGRID_SECRET: str = os.getenv("INTELGRID_SECRET", "")  # shared secret with IntelGrid website
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_RATE_LIMIT: int = int(os.getenv("API_RATE_LIMIT", "100"))
    API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", secrets.token_hex(32))
    API_BASE_URL: str = os.getenv("API_BASE_URL", "").strip()  # Set via env var
    # Web Admin Panel password (set WEB_ADMIN_PASSWORD env var; falls back to API_SECRET_KEY)
    WEB_ADMIN_PASSWORD: str = os.getenv("WEB_ADMIN_PASSWORD", "").strip()

print("[STARTUP] Initialising BotConfig...", flush=True)
try:
    config = BotConfig()
    print("[STARTUP] BotConfig OK", flush=True)
except Exception as _cfg_err:
    print(f"[STARTUP] FATAL: BotConfig failed — {_cfg_err}", flush=True)
    import traceback as _tb; _tb.print_exc()
    sys.exit(1)

# ================== LOGGING SETUP ==================
# Use StreamHandler only — Render captures stdout/stderr directly.
# FileHandler is omitted to avoid silent crashes on read-only filesystems.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger("DarkBoxes")

# ================== VALIDATION ==================

def validate_config() -> bool:
    """Validate all required configuration"""
    errors = []
    
    required_configs = [
        ("BOT_API_ID (env: API_ID)",     config.BOT_API_ID,    lambda x: x != 0),
        ("BOT_API_HASH (env: API_HASH)", config.BOT_API_HASH,  lambda x: len(x) > 0),
        ("BOT_TOKEN",                    config.BOT_TOKEN,     lambda x: len(x) > 0),
        ("ADMIN_USER_ID",                config.ADMIN_USER_ID, lambda x: x != 0),
        ("MONGODB_URI",                  config.MONGODB_URI,   lambda x: len(x) > 0),
    ]
    
    for name, value, validator in required_configs:
        try:
            ok = validator(value)
        except Exception:
            ok = False
        if not ok:
            errors.append(f"{name} is not properly configured (got: {repr(value)[:40]})")
    
    if errors:
        print("[STARTUP] FATAL: Configuration validation failed:", flush=True)
        for error in errors:
            print(f"[STARTUP]   ✗ {error}", flush=True)
        logger.error("Configuration validation failed — see stdout for details")
        return False

    print("[STARTUP] All required env vars OK", flush=True)
    return True

if not validate_config():
    sys.exit(1)

USE_USER_ACCOUNT = config.USER_API_ID != 0 and bool(config.USER_API_HASH) and bool(config.USER_PHONE)
print(f"[STARTUP] USE_USER_ACCOUNT={USE_USER_ACCOUNT} "
      f"(USER_API_ID={'set' if config.USER_API_ID else 'NOT SET'}, "
      f"USER_PHONE={'set' if config.USER_PHONE else 'NOT SET'})", flush=True)

# ================== API KEY MANAGEMENT ==================

class APIKeyManager:
    """Manage API keys for external access"""
    
    @staticmethod
    def generate_api_key(user_id: int, description: str = "") -> str:
        """Generate a new API key"""
        timestamp = int(time.time())
        random_part = secrets.token_hex(16)
        data = f"{user_id}:{timestamp}:{random_part}:{secrets.token_hex(8)}"
        api_key = hashlib.sha256(data.encode()).hexdigest()
        return api_key
    
    @staticmethod
    def generate_client_token(api_key: str) -> str:
        """Generate client token from API key"""
        return hashlib.sha256(f"{api_key}:{config.API_SECRET_KEY}".encode()).hexdigest()[:32]
    
    @staticmethod
    def validate_api_key_format(api_key: str) -> bool:
        """Validate API key format"""
        return len(api_key) == 64 and all(c in '0123456789abcdef' for c in api_key)


class APIResponseFormatter:
    """Format API responses"""
    
    @staticmethod
    def success(data: Any = None, message: str = "Success") -> Dict:
        """Format successful response"""
        response = {
            "status": "success",
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if data is not None:
            response["data"] = data
        return response
    
    @staticmethod
    def error(message: str = "Error", code: str = "UNKNOWN_ERROR") -> Dict:
        """Format error response"""
        return {
            "status": "error",
            "message": message,
            "code": code,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    @staticmethod
    def format_search_result(content: str, search_type: str, query: str, source: str) -> Dict:
        """Format search result for API"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        
        # Clean and structure the content
        lines = content.split('\n')
        structured_data = {
            "query": query,
            "type": search_type,
            "name": cmd.get("name", "Search Result"),
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_text": content,
            "parsed_data": {}
        }
        
        # Try to parse structured data from content
        for line in lines:
            line = line.strip()
            if ': ' in line:
                key, value = line.split(': ', 1)
                key = key.replace('•', '').replace('🔸', '').strip()
                if key and value and len(key) < 50:
                    structured_data["parsed_data"][key] = value
        
        return structured_data
    
    @staticmethod
    def format_leak_result(files_data: List[Dict], query: str) -> Dict:
        """Format leak search result for API"""
        result = {
            "query": query,
            "type": "leak",
            "name": "Advanced OSINT Search",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "files_count": len(files_data),
            "files": []
        }
        
        for file_data in files_data:
            file_info = {
                "type": file_data.get("file_type", "unknown"),
                "size": len(file_data.get("content", "")),
                "has_content": bool(file_data.get("content"))
            }
            
            # Try to parse JSON if available
            if file_data.get("file_type") == "json" and file_data.get("content"):
                try:
                    file_info["parsed_json"] = json.loads(file_data["content"])
                except:
                    file_info["parsed_json"] = None
            
            result["files"].append(file_info)
        
        return result

# ================== TEXT PROCESSOR ==================



# ================== GROUP PRIORITY MANAGEMENT ==================

GROUP_PRIORITIES = {
    "primary": {
        "name": "⚡ Premium Database",
        "identifier": -1003320004816,
        "timeout": 45,
        "weight": 10,
        "enabled": True,
        "entity": None,
        "direct_reply_only": True,   # ← shared group: ONLY accept direct replies to our message
        "commands": {
            "phone":   "/num",
            "family":  "/familyinfo",
            "aadhar":  "/aadhar",
            "vehicle": "/vnum",
            "telegram": "/tg",
            "imei":    "/imei",
            "gst":     "/gst",
            "insta":   "/insta",
            "ip":      "/ip",
            "ifsc":    "/ifsc",
        }
    },
    "secondary": {
        "name": "🌐 IntelX Network",
        "identifier": "@Ethicalosinterr_bot",
        "timeout": 45,
        "weight": 7,
        "enabled": True,
        "entity": None,
        "commands": {
            "phone":   "",
            "family":  "",
            "aadhar":  "",
            "vehicle": "",
            "telegram": "",
            "imei":    "",
            "gst":     "",
            "insta":   "",
            "ip":      "",
            "ifsc":    "",
        }
    },
    "tertiary": {
        "name": "🔍 Basic Database",
        "identifier": "@EncoreXgroup",
        "timeout": 20,           # Basic DB: wait up to 20s for group replies
        "weight": 5,
        "enabled": True,
        "entity": None,
        "basic_db": True,        # ← SPECIAL: replies go to group, not to our account
        "basic_db_wait": 20,     # seconds to monitor the group for matching replies
        "commands": {
            "phone":   "/num",
            "family":  "/family",
            "aadhar":  "/aadhar",
            "vehicle": "/vnum",
            "telegram": "/tg",
            "imei":    "/imei",
            "gst":     "/gst",
            "insta":   "/insta",
            "ip":      "/geo",
            "ifsc":    "/ifsc",
        }
    },
    "advanced": {
        "name": "🚀 Advanced OSINT Engine",
        "identifier": "RAJIV_THE_LOOKUP_HUB",
        "timeout": 35,
        "weight": 15,
        "enabled": True,
        "entity": None,
        "leak_command": "/leak",
        "commands": {}
    }
}

# Sort groups by weight (priority)
DESTINATION_GROUPS = sorted(
    [group for group in GROUP_PRIORITIES.values() if group["enabled"]],
    key=lambda x: x["weight"],
    reverse=True
)


# ================== VALIDITY TYPE DEFINITIONS ==================
# Each validity type defines what constitutes a "real" result for that command.
# Admin can assign any of these to any command via the admin panel.
VALIDITY_TYPES = {
    "num": {
        "label": "Phone/NUM (name, address, mobile)",
        "required_any": [
            # Standard formatted results
            "owner name", "owner_name", "name", "fname", "father name", "father_name",
            "mobile no", "mobile", "alt mobile", "alt_mobile", "address", "circle",
            "id no", "id_no", "id_number",
            # JSON format (BDG / hiteckgroop.in leak format)
            '"name"', '"father_name"', '"mobile"', '"address"', '"alt_mobile"',
            '"circle"', '"id_number"',
            # Hiteckgroop masked format (contains special block characters)
            "telephone", "adres", "full name", "the name of the father",
            "region", "hiteckgroop", "hiteck",
            # Any record-style data
            "record #",
        ],
        "min_fields": 1,
    },
    "family": {
        "label": "Family/Ration (household members)",
        "required_any": [
            "card id", "card type", "household", "member", "ration",
            "full address", "fps name", "e-kyc", "id mask",
        ],
        "min_fields": 1,
    },
    "vehicle": {
        "label": "Vehicle (plate, owner, RTO, insurance)",
        "required_any": [
            "plate", "vehicle", "vehicle_number", "make", "model", "fuel",
            "engine", "chassis", "rto", "registration", "insurer", "insurance",
            "asset_number", "owner_name", "permanent_address",
        ],
        "min_fields": 1,
    },
    "telegram": {
        "label": "Telegram (ID, phone, verification)",
        "required_any": [
            "telegram id", "telegram_id", "phone number", "country",
            "verification", "account status", "data source",
        ],
        "min_fields": 1,
    },
    "generic": {
        "label": "Generic (any non-empty result)",
        "required_any": [],
        "min_fields": 0,
    },
}

# ================== FREE USER CONFIGURATION ==================
# Admin-configurable at runtime via DB; these are boot-time defaults.
FREE_USER_CONFIG = {
    "allowed_groups": [],    # Group keys for free users; empty = all groups
    "allowed_commands": [],  # Command keys for free users; empty = all commands
}

def _load_free_user_config():
    global FREE_USER_CONFIG
    try:
        client_mg = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=3000)
        db_tmp = client_mg[config.MONGODB_DBNAME]
        doc = db_tmp.bot_config.find_one({"_id": "free_user_config"})
        if doc:
            FREE_USER_CONFIG["allowed_groups"]  = doc.get("allowed_groups", [])
            FREE_USER_CONFIG["allowed_commands"] = doc.get("allowed_commands", [])
        client_mg.close()
    except Exception:
        pass

_load_free_user_config()


# ================== FORCE JOIN CHANNELS ==================
# Stored in DB — admin can add/remove at runtime without restarting.
# Each entry: {"username": "@channelusername", "title": "Display Name", "url": "https://t.me/..."}

FORCE_JOIN_CHANNELS: List[Dict] = []


def _load_force_join_channels():
    """Load force-join channel list from DB at boot."""
    global FORCE_JOIN_CHANNELS
    try:
        from pymongo import MongoClient as _MC
        _cl = _MC(config.MONGODB_URI, serverSelectionTimeoutMS=3000)
        _doc = _cl[config.MONGODB_DBNAME].bot_config.find_one({"_id": "force_join_channels"})
        if _doc:
            FORCE_JOIN_CHANNELS = _doc.get("channels", [])
        _cl.close()
    except Exception:
        pass


_load_force_join_channels()


async def _save_force_join_channels():
    """Persist FORCE_JOIN_CHANNELS to MongoDB."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: db_manager.db.bot_config.update_one(
            {"_id": "force_join_channels"},
            {"$set": {"channels": FORCE_JOIN_CHANNELS}},
            upsert=True,
        ),
    )


async def check_force_join(user_id: int) -> List[Dict]:
    """Return list of channels the user has NOT joined.

    Uses the Bot HTTP API getChatMember endpoint — works for ANY public
    channel/group without the bot needing to be an admin.
    Returns empty list if all joined or no channels configured.
    """
    if not FORCE_JOIN_CHANNELS:
        return []

    import aiohttp as _aiohttp

    bot_token  = config.BOT_TOKEN
    not_joined = []

    for ch in FORCE_JOIN_CHANNELS:
        uname = ch.get("username", "").strip().lstrip("@")
        if not uname:
            continue
        try:
            url = (
                f"https://api.telegram.org/bot{bot_token}/getChatMember"
                f"?chat_id=@{uname}&user_id={user_id}"
            )
            async with _aiohttp.ClientSession() as session:
                async with session.get(url, timeout=_aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json()
            if not data.get("ok"):
                # API error — bot probably not in channel; treat as not-joined
                logger.warning(
                    f"force_join getChatMember error for @{uname}: {data.get('description','')}"
                    f" — make sure bot is added to the channel as admin"
                )
                not_joined.append(ch)
                continue
            status = data.get("result", {}).get("status", "left")
            if status not in ("member", "administrator", "creator"):
                not_joined.append(ch)
        except Exception as e:
            logger.warning(f"force_join check failed for @{uname}: {e}")
            not_joined.append(ch)

    return not_joined


def _build_join_keyboard(missing: List[Dict]) -> List[List]:
    """One join button per missing channel + a verify button."""
    rows = []
    for ch in missing:
        title = ch.get("title") or ch.get("username", "Channel")
        url = ch.get("url") or ("https://t.me/" + ch.get("username", "").lstrip("@"))
        rows.append([Button.url("📢 Join  " + title, url)])
    rows.append([Button.inline("✅  I've Joined — Verify & Continue", "check_join")])
    return rows


async def enforce_force_join(event) -> bool:
    """Returns True if user may proceed; False if blocked and prompt was shown."""
    user_id = event.sender_id
    missing = await check_force_join(user_id)
    if not missing:
        return True
    ch_lines = "\n".join("  ▸ " + (ch.get("title") or ch.get("username", "")) for ch in missing)
    msg = (
        "🔐 **ACCESS REQUIRED**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "You must join our official channel(s) to use DarkBoxes:\n\n"
        + ch_lines +
        "\n\nTap the buttons below to join, then tap\n"
        "**✅ I've Joined — Verify & Continue**"
    )
    try:
        await event.edit(msg, buttons=_build_join_keyboard(missing), parse_mode="md")
    except Exception:
        await event.respond(msg, buttons=_build_join_keyboard(missing), parse_mode="md")
    return False


# ================== SUBSCRIPTION PLANS ==================

SUBSCRIPTION_PLANS = {
    # ── Credit packs (one-time top-up, credits never expire) ──────────────
    "credits_5": {
        "name": "⚡ 5 CREDITS PACK",
        "price": 200,
        "searches": 5,
        "validity": "No expiry",
        "validity_days": 0,
        "daily_limit": 0,
        "plan_type": "credit",
        "features": ["5 Premium Searches", "All Databases", "Credits Never Expire", "Email Support"],
        "icon": "⚡",
        "color": "#27AE60",
        "for": "Occasional searches"
    },
    # ── Monthly subscriptions ──────────────────────────────────────────────
    "sub_num_monthly": {
        "name": "📱 NUM UNLIMITED — Monthly",
        "price": 300,
        "searches": 999999,
        "validity": "30 days",
        "validity_days": 30,
        "daily_limit": 0,
        "plan_type": "subscription",
        "allowed_commands": ["phone"],   # Only phone/num command
        "features": ["Unlimited Phone Searches", "30-Day Validity", "Priority Processing", "Email Support"],
        "icon": "📱",
        "color": "#3498DB",
        "for": "Phone number lookups"
    },
    "sub_all_monthly": {
        "name": "💎 ALL COMMANDS — Monthly",
        "price": 499,
        "searches": 999999,
        "validity": "30 days",
        "validity_days": 30,
        "daily_limit": 0,
        "plan_type": "subscription",
        "allowed_commands": [],          # Empty = all commands allowed
        "features": ["Unlimited All Searches", "All Databases", "30-Day Validity", "Priority Support"],
        "icon": "💎",
        "color": "#9B59B6",
        "for": "Power users — all commands"
    },
}

# ================== SEARCH COMMANDS WITH PRIORITY ==================

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Intelligence",
        "description": "📊 **Complete Mobile Intelligence**\n\n🔸 **Input:** 10-digit Indian mobile number\n🔸 **Returns:** Full name • Father's name • ID Number • Complete address • Alternate numbers\n🔸 **Sources:** Public databases • Network records • Public directories\n🔸 **Confidence:** 98% accurate",
        "commands": ["/num", "/num", "/num"],
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "cost": 1,
        "priority": "primary",
        "icon": "📱",
        "category": "identity"
    },
    "family": {
        "name": "👨‍👩‍👧‍👦 Family Network",
        "description": "🏠 **Complete Family Analysis**\n\n🔸 **Input:** 12-digit ID number\n🔸 **Returns:** All family members • Names • Relations • Ages • Addresses\n🔸 **Sources:** Basic data • Family records • Public records\n🔸 **Depth:** 3-level relationship mapping",
        "commands": ["/family", "/familyinfo"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "cost": 1,
        "priority": "primary",
        "icon": "👨‍👩‍👧‍👦",
        "category": "identity"
    },
    "aadhar": {
        "name": "🆔 ID Comprehensive",
        "description": "📈 **Complete ID Cross-Reference**\n\n🔸 **Input:** 12-digit ID number\n🔸 **Returns:** All linked numbers • Bank accounts • Addresses • Active status • Registration history\n🔸 **Sources:** Basic data • Bank linkages • Public databases\n🔸 **Scope:** Nationwide coverage",
        "commands": ["/aadhar", "/aadhar", "/aadhar"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "cost": 2,
        "priority": "primary",
        "icon": "🆔",
        "category": "finance"
    },
    "vehicle": {
        "name": "🚗 Vehicle Intelligence",
        "description": "🏎️ **Complete Vehicle & Owner Analysis**\n\n🔸 **Input:** Vehicle number (Format: UP53CZ3391)\n🔸 **Returns:** Vehicle details • Owner information • Mobile number • Address • Registration history • Insurance\n🔸 **Premium Feature:** Celebrity vehicle database access\n🔸 **Real-time:** Current registration status",
        "commands": ["/vnum", "/vehicle", "/rto"],
        "example": "UP53CZ3391",
        "validation": r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$",
        "cost": 2,
        "priority": "secondary",
        "icon": "🚗",
        "category": "assets"
    },
    "telegram": {
        "name": "📲 Telegram Intelligence",
        "description": "⚡ **Telegram Profile Deep Analysis**\n\n🔸 **Input:** Telegram username or phone\n🔸 **Returns:** Mobile number • Profile details • Linked accounts • Activity patterns • Group memberships\n🔸 **Daily Limit:** 1 search for security\n🔸 **Privacy:** Encrypted processing",
        "commands": ["/tg", "/telegram"],
        "example": "@username or 9876543210",
        "validation": r"^(@?\w{5,32}|\d{10})$",
        "daily_limit": 1,
        "cost": 2,
        "priority": "primary",
        "icon": "📲",
        "category": "digital"
    },
    "imei": {
        "name": "📱 Device Intelligence",
        "description": "🔧 **Mobile Device Comprehensive Analysis**\n\n🔸 **Input:** 15-digit IMEI number\n🔸 **Returns:** Device make/model • Purchase details • Location history • Current user • Service history\n🔸 **Sources:** Manufacturer databases • Carrier records • Global databases\n🔸 **Tracking:** Real-time status",
        "commands": ["/imei", "/device"],
        "example": "123456789012345",
        "validation": r"^\d{15}$",
        "cost": 2,
        "priority": "secondary",
        "icon": "📱",
        "category": "assets"
    },
    "gst": {
        "name": "🏢 Business Intelligence",
        "description": "📊 **GST Business Comprehensive Analysis**\n\n🔸 **Input:** GST number\n🔸 **Returns:** Business details • Owner information • Financial patterns • Compliance status • Tax history\n🔸 **Sources:** Basic data • Financial databases • Business records\n🔸 **Verification:** GST data integration",
        "commands": ["/gst", "/gstin"],
        "example": "29ABCDE1234F1Z5",
        "validation": r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$",
        "cost": 1,
        "priority": "secondary",
        "icon": "🏢",
        "category": "business"
    },
    "insta": {
        "name": "📸 Instagram Intelligence",
        "description": "✨ **Instagram Profile Deep Analysis**\n\n🔸 **Input:** Instagram username\n🔸 **Returns:** Personal information • Contact details • Location data • Linked accounts • Activity history\n🔸 **Sources:** Social media APIs • Public databases • Metadata analysis\n🔸 **Insights:** Engagement patterns",
        "commands": ["/insta", "/instagram"],
        "example": "username",
        "validation": r"^[a-zA-Z0-9_.]{1,30}$",
        "cost": 1,
        "priority": "tertiary",
        "icon": "📸",
        "category": "social"
    },
    "ip": {
        "name": "🌍 IP Location",
        "description": "📍 **IP Address Geolocation Analysis**\n\n🔸 **Input:** IP address (IPv4/IPv6)\n🔸 **Returns:** Country • City • ISP • Coordinates • Timezone • Threat level\n🔸 **Sources:** GeoIP databases • Threat intelligence • ASN records\n🔸 **Accuracy:** Street-level precision",
        "commands": ["/ip", "/location", "/geo"],
        "example": "8.8.8.8",
        "validation": r"^(\d{1,3}\.){3}\d{1,3}$|^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$",
        "cost": 1,
        "priority": "secondary",
        "icon": "🌍",
        "category": "digital"
    },
    "ifsc": {
        "name": "🏦 IFSC Code Lookup",
        "description": "💼 **Bank Branch Information**\n\n🔸 **Input:** 11-digit IFSC code\n🔸 **Returns:** Bank name • Branch • Address • Contact • MICR code • Services\n🔸 **Sources:** RBI database • Bank records • Financial institutions\n🔸 **Verification:** Real-time validation",
        "commands": ["/ifsc", "/bank"],
        "example": "SBIN0001707",
        "validation": r"^[A-Z]{4}0[A-Z0-9]{6}$",
        "cost": 1,
        "priority": "secondary",
        "icon": "🏦",
        "category": "finance"
    },
}

# ================== PREMIUM TEXT FORMATTER ==================

class PremiumFormatter:
    @staticmethod
    def format_header(title: str, icon: str = "⚡") -> str:
        """Format premium header"""
        line = "═" * 40
        return f"{icon} **{title}**\n{line}\n"
    
    @staticmethod
    def format_section(title: str, content: str, icon: str = "▸") -> str:
        """Format section with icon"""
        return f"{icon} **{title}:** {content}\n"
    
    @staticmethod
    def format_list(items: List[str], icon: str = "•") -> str:
        """Format list with icons"""
        return "\n".join(f"{icon} {item}" for item in items) + "\n"
    
    @staticmethod
    def format_result(content: str, search_type: str, query: str, source: str) -> str:
        """Format result using Telegram quote blocks. Wraps sensitive fields in spoilers."""
        import re as _re
        cmd  = SEARCH_COMMANDS.get(search_type, {})
        name = cmd.get("name", "Result")

        def wrap_sensitive(text: str) -> str:
            # Aadhar / UID-like 12-digit numbers → spoiler
            text = _re.sub(r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b",
                           lambda m: f"||{m.group(0)}||", text)
            # Tax ID format → spoiler
            text = _re.sub(r"\b([A-Z]{5}\d{4}[A-Z])\b",
                           lambda m: f"||{m.group(0)}||", text)
            return text

        if not content or len(content.strip()) < 20:
            return (
                f"**{name}**\n"
                f"\n"
                f"> Query: `{query}`\n"
                f"> No results found for this query.\n"
                f"\n"
                f"_Try a different format, or contact @darkboxesAdmin._"
            )

        safe_content = wrap_sensitive(content)

        return (
            f"**{name}**\n"
            f"\n"
            f"> Query: `{query}`\n"
            f"\n"
            + safe_content +
            f"\n\n> Source: {source}  ·  {datetime.now().strftime('%d %b %Y %H:%M')}"
        )

    @staticmethod
    def format_welcome(user_name: str, user_data: Dict) -> str:
        """Professional welcome message using Telegram quote blocks."""
        raw_credits = user_data.get("searches_remaining", 0)
        subscription = user_data.get("subscription")
        sub_expiry   = user_data.get("subscription_expiry")

        # Check if subscription is still active
        sub_active = False
        if subscription and sub_expiry:
            try:
                exp = datetime.fromisoformat(sub_expiry)
                if exp > datetime.now(timezone.utc):
                    sub_active = True
            except Exception:
                pass

        if sub_active:
            credits_line = f"Plan: **{subscription}** (active)"
        elif raw_credits > 0:
            credits_line = f"Credits: **{raw_credits}**"
        else:
            credits_line = "Credits: **0** — _searches return masked preview_"

        searches = user_data.get("total_searches", 0)
        ref_code = user_data.get("referral_code", "N/A")
        refs     = user_data.get("referrals", 0)
        name     = user_name

        free_note = ""
        if not sub_active and raw_credits <= 0:
            free_note = (
                "\n\n"
                "> ⚠️ **No credits** — you can still search!\n"
                "> Results will be **masked**. Tap 🔓 to unlock data."
            )

        return (
            f"**Welcome, {name}**"
            f"\n\n"
            f"__Dark Boxes Intelligence System__"
            f"\n\n"
            f"> {credits_line}"
            f"\n"
            f"> Searches done: **{searches}**"
            f"\n"
            f"> Referral code: `{ref_code}` · {refs} referral{'s' if refs != 1 else ''}"
            f"{free_note}"
            f"\n\n"
            f"Select a search tool below."
        )
    
    @staticmethod
    def format_processing(search_type: str, query: str) -> str:
        """Waiting message in quote format."""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        name = cmd.get("name", "Search")
        return (
            f"**{name}**\n"
            f"\n"
            f"> Query: `{query}`\n"
            f"> Checking all sources at once...\n"
            f"\n"
            f"_Please wait. This usually takes under 30 seconds._"
        )

# ================== TEXT PROCESSOR ==================

class TextProcessor:
    @staticmethod
    def is_processing_message(text: str) -> bool:
        """Check if a message is a placeholder/confirmation, NOT a real result.

        Returns True  → ignore this message, wait for the real reply
        Returns False → this is actual data, use it

        CRITICAL: IntelX sends 3 messages in sequence:
          1. "Breached: 🔎Request: ..." — header/summary — NOT a placeholder
          2. Masked data with █ chars — real result
          3. "Subscription is over" — footer — NOT a placeholder
        None of these should return True.
        """
        if not text:
            return True

        text_lower = text.lower()
        text_stripped = text.strip()

        # ── EARLY EXIT: known result/data signals — never treat as processing ──
        result_signals = [
            # JSON fields
            '"success":', '"status":', '"result":', '"results":',
            '"mobile":', '"name":', '"address":', '"father_name":',
            '"alt_mobile":', '"circle":', '"id_number":', '"email":',
            '"aadhar":', '"fname":', '"country":', '"number":',
            # Formatted fields
            'owner name', 'father name', 'mobile no', 'alt mobile',
            'owner_name', 'father_name',
            # IntelX masked data signals
            'telephone', 'adres', 'full name', 'the name of the father',
            'region', 'hiteckgroop', '█',
            # 1Win / leak breach data
            'encrypted password', 'date of registration',
            # Result frames
            '✅ success', '║  ✅', 'encorex osint', 'encorex intelx',
            '╔═══《', '╘══《',
            # Record-style headers from various group bots
            'record #', '━━━', '═══', '▬▬▬',
            # "NUMBER TO DETAILS:" style headers
            'number to details', 'details:', 'result:', 'data:',
            # IntelX header lines — these mean real data is coming next
            'breached:', '🔎request:', 'subjects made:',
            'number of results:', 'number of leaks:', 'search time:',
            # IntelX footer — data already sent before this
            'subscription is over', 'trial period', '/shop',
            'free version', 'buying a subscription',
            # Ration/vehicle data
            'card id', 'card type', 'household', 'member #',
            'plate no', 'vehicle_number', 'engine no', 'chassis',
        ]
        if any(sig in text_lower for sig in result_signals):
            return False

        # Real results have JSON-like key:value pairs
        if text_lower.count('": ') >= 2 or text_lower.count(': ') >= 4:
            return False

        # Real results are usually long
        if len(text_stripped) > 300:
            return False

        # Short messages that look like real data rows
        real_data_patterns = [
            'name:', 'mobile:', 'phone:', 'address:', 'father:', 'dob:',
            'operator:', 'circle:', 'state:', 'district:', 'email:',
            'owner:', 'vehicle:', 'company:', 'gst:', 'ifsc:', 'bank:',
        ]
        if any(p in text_lower for p in real_data_patterns):
            return False

        # ── PLACEHOLDER / CONFIRMATION keywords ───────────────────────────────
        placeholder_keywords = [
            'please wait', 'hold on', 'wait a moment', 'in progress',
            'gathering data', 'working on it', 'please wait while',
            'getting information', 'fetching data', 'creating report',
            'searching...', 'searching mobile', '🔍 searching',
            '🔎 searching', 'search initiated', 'looking up',
            'processing...', 'processing your', '⏳ processing',
            'please wait...', '⏳ please wait',
            'scanning...', 'scanning mobile', 'encorex tunnel',
            'intelx tunnel',
            'powered by darkboxes intelligence system',
            '🔐 developed by',
            '⚠️ confidential',
            'query received', 'request received', 'fetching result',
            'fetch initiated', 'initiated search', 'initiating',
            'standby', 'one moment', 'just a moment',
        ]
        if any(kw in text_lower for kw in placeholder_keywords):
            return True

        # Short messages with no data pairs are placeholders
        if len(text_stripped) < 200 and text_stripped.count('\n') <= 5:
            lines = [l.strip() for l in text_stripped.split('\n') if l.strip()]
            non_empty = [l for l in lines if l and not l.startswith('─') and not l.startswith('━')]
            if len(non_empty) <= 4 and not any(':' in l and len(l) > 10 for l in non_empty):
                return True

        return False
    
    @staticmethod
    def is_file_generated_message(text: str) -> bool:
        """Check if message indicates file generation"""
        if not text:
            return False
        
        text_lower = text.lower()
        keywords = [
            'file generated', 'report generated', 'download file',
            'txt file', 'download txt', 'successfully generated',
            'file generated', 'report_', '.txt', 'auto-delete',
            'file ready', 'file is ready', 'report is ready'
        ]
        
        result = any(keyword in text_lower for keyword in keywords)
        if result:
            logger.info(f"📄 Detected file generation message: {text[:50]}...")
        return result
    
    @staticmethod
    def is_no_info_message(text: str) -> bool:
        """Check if message truly means no data found.

        IMPORTANT rules:
        - IntelX "subscription over" message is NOT no-info — the real data
          comes as a SEPARATE message immediately after it. Never reject it.
        - Any message containing telephone/adres/full name/father fields is data.
        - Any message > 150 chars with block-char masking (█) is masked data.
        - Only short, clearly negative phrases qualify as no-info.
        """
        if not text:
            return False

        text_lower = text.lower().strip()

        # ── NEVER reject if message contains real data signals ────────────────
        always_data_signals = [
            # JSON fields
            '"success":', '"status":', '"result":', '"results":',
            '"mobile":', '"name":', '"address":', '"father_name":',
            '"alt_mobile":', '"circle":', '"id_number":', '"email":',
            '"aadhar":', '"fname":', '"country":', '"number":',
            # Formatted record fields
            'owner name', 'father name', 'mobile no', 'alt mobile',
            'owner_name', 'father_name', 'alt_mobile', 'id_number',
            # IntelX / hiteckgroop masked format
            'telephone', 'adres', 'full name', 'the name of the father',
            'region', 'hiteckgroop', 'hiteck',
            # 1Win / leak format
            'encrypted password', 'date of registration',
            # "NUMBER TO DETAILS:" style group headers — data follows
            'number to details', 'details :', 'result :', 'data :',
            # Result frames
            '✅ success', '✅ found', '╔═══《', 'encorex osint', 'encorex intelx',
            # Record separators
            'record #', '---', '━━━', '═══',
            # Ration / vehicle
            'card id', 'card type', 'household', 'member #',
            'plate no', 'vehicle_number', 'engine no', 'chassis',
        ]
        if any(sig in text_lower for sig in always_data_signals):
            return False

        # Multiple JSON key-value pairs → definitely a result
        if text_lower.count('": ') >= 2:
            return False

        # Long messages with masked chars are data
        if len(text_lower) > 150 and '█' in text:
            return False

        # Long messages are almost certainly results
        if len(text_lower) > 250:
            return False

        # ── IntelX multi-message pattern ──────────────────────────────────────
        # Message 1: "Breached:\n🔎Request: ..." — this is a HEADER, not no-info
        # Message 2: the actual masked data
        # Message 3: "Your subscription is over!" — also NOT no-info
        intelx_header_signals = [
            'breached:', '🔎request:', 'subjects made:', 'number of results:',
            'number of leaks:', 'search time:', 'free version',
            'subscription is over', 'trial period', '/shop', '/referral',
            '/mirrors', 'mirror', 'buying a subscription',
        ]
        if any(sig in text_lower for sig in intelx_header_signals):
            return False  # IntelX header/footer — NOT no-info, real data follows

        # ── Only short clearly-negative phrases count as no-info ──────────────
        strict_phrases = [
            'no info found', 'no information found', 'no result found',
            'no data found', 'no record found', 'no match found',
            'not found in database', 'no results found', 'data not found',
            'record not found', 'details not found', 'does not exist',
            "doesn't exist", 'unable to find', 'could not find',
            "couldn't find", 'no entry found', 'no info',
            'invalid number', 'invalid query',
        ]
        return any(phrase in text_lower for phrase in strict_phrases)

    @staticmethod
    def clean_content(content: str, search_type: str = None) -> str:
        """Clean group/bot response — remove branding/promo but PRESERVE all data lines.

        Critical: IntelX masked lines (📞Telephone, 🏘️Adres, 👤Full name, etc.)
        and block-char masked values (█) must NEVER be stripped — they are the
        actual data that the user paid to see (or will pay to unlock).
        """
        if not content:
            return ""

        lines_in  = content.split('\n')
        lines_out = []

        # Patterns that identify purely promotional / branding lines to DROP.
        # We match whole lines only — never strip partial line content.
        promo_line_patterns = [
            r'^\s*https?://\S+\s*$',            # bare URL line
            r'^\s*www\.\S+\s*$',                 # bare www line
            r'powered by.*darkboxes.*$',
            r'powered by\s+@\w+.*$',         # Powered by @AnyUsername
            r'powered by\s+\w.*$',            # Powered by AnythingElse
            r'developed by.*$',
            r'created by.*$',
            r'designed by.*$',
            r'©.*$',
            r'copyright.*$',
            r'join.*channel.*$',
            r'subscribe.*channel.*$',
            r'auto-delete.*$',
            r'file generated.*$',
            r'report_.*\.txt.*$',
            r'download.*file.*$',
            r'click.*download.*$',
            r'designed & powered.*$',
            # ENCOREX tunnel scanning frame lines only
            r'╔════════+╗\s*$',
            r'╚════════+╝\s*$',
            r'║.*encorex tunnel.*║\s*$',
            r'║.*intelx tunnel.*║\s*$',
            r'║.*scanning\.\.\..*║\s*$',
            r'║.*service:.*node:.*║\s*$',
        ]
        compiled_promo = [re.compile(p, re.IGNORECASE) for p in promo_line_patterns]

        # Lines that contain these strings are ALWAYS kept (data lines)
        always_keep_signals = [
            '█',                            # masked data char
            'telephone', 'adres',           # IntelX masked labels
            'full name', 'the name of the father', 'region',
            'hiteckgroop', 'hiteck',
            'encrypted password', 'date of registration',
            'owner name', 'father name', 'mobile no', 'alt mobile',
            '"name"', '"mobile"', '"address"', '"father_name"',
            '"alt_mobile"', '"circle"', '"id_number"',
            'record #', '---', '═══', '━━━',
            'breached:', '🔎request:', 'subjects made:',
            'number of results:', 'number of leaks:', 'search time:',
            'card id', 'card type', 'household', 'member #',
            'plate no', 'engine no', 'chassis',
        ]

        for line in lines_in:
            line_lower = line.lower()

            # Always keep data lines — never apply promo filter to them
            if any(sig in line_lower for sig in always_keep_signals):
                lines_out.append(line)
                continue

            # Skip purely promotional / branding lines
            if any(pat.search(line) for pat in compiled_promo):
                continue

            # Drop lines that are ONLY a @username mention with no other content
            stripped = line.strip()
            if re.match(r'^@\w+\s*$', stripped):
                continue
            # Drop bare t.me links
            if re.match(r'^t\.me/\S+\s*$', stripped, re.IGNORECASE):
                continue

            lines_out.append(line)

        cleaned = '\n'.join(lines_out)

        # Collapse 3+ consecutive blank lines to 2
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        # Collapse multiple spaces
        cleaned = re.sub(r' {2,}', ' ', cleaned)

        return cleaned.strip()
    
    @staticmethod
    def split_long_text(text: str, max_length: int = 4000) -> List[str]:
        """Split long text into chunks"""
        if len(text) <= max_length:
            return [text]
        
        chunks = []
        while len(text) > max_length:
            # Try to split at paragraph
            split_pos = text.rfind('\n\n', 0, max_length)
            if split_pos == -1:
                split_pos = text.rfind('\n', 0, max_length)
            if split_pos == -1:
                split_pos = max_length
            
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip()
        
        if text:
            chunks.append(text)
        
        return chunks

    @staticmethod
    def is_valid_result(text: str, search_type: str) -> bool:
        """Check if the response from a group/bot is actually a valid data result.

        Extended to recognise ALL result formats:
        - Standard KEY : VALUE  (OWNER NAME, FATHER NAME, etc.)
        - JSON array/object     (BDG / hiteckgroop leak format)
        - IntelX masked format  (Telephone: 9██, Adres: ..., Full name: ...)
        - 1Win / breach format  (Email, Encrypted password, Telephone, ...)
        - IntelX header message ("Breached: 🔎Request: ..." — valid, data follows)
        - Block-char masked     (any message containing █ with context)
        """
        if not text or len(text.strip()) < 10:
            return False

        text_lower = text.lower()

        # ── Universal data signals that always mean VALID ────────────────────
        universal_valid = [
            # Standard formatted records
            'owner name', 'father name', 'mobile no', 'alt mobile',
            'owner_name', 'father_name', 'alt_mobile', 'id_number',
            'id no', 'circle', 'record #',
            # JSON field keys
            '"name"', '"mobile"', '"father_name"', '"address"',
            '"alt_mobile"', '"circle"', '"id_number"', '"id"',
            # IntelX masked format (all lowercase for matching)
            'telephone', 'adres', 'full name', 'the name of the father',
            'region', 'hiteckgroop', 'hiteck',
            # 1Win / breach data fields
            'encrypted password', 'date of registration',
            # Ration / family
            'card id', 'card type', 'household', 'member #',
            'fps name', 'e-kyc', 'id mask',
            # Vehicle
            'plate no', 'vehicle_number', 'engine no', 'chassis',
            'rto', 'registration_date', 'insurer',
            # Telegram
            'telegram id', 'telegram_id',
            # "NUMBER TO DETAILS:" / other group-specific headers
            'number to details',
            'number of results:', 'number of leaks:', 'search time:',
        ]
        if any(sig in text_lower for sig in universal_valid):
            return True

        # ── Block-char masked data (█) with minimum context ─────────────────
        if '█' in text and len(text.strip()) >= 30:
            return True

        # ── JSON array with objects containing data fields ───────────────────
        if text_lower.count('": ') >= 2 or text_lower.count('"mobile"') >= 1:
            return True

        # ── Fallback to VALIDITY_TYPES config ───────────────────────────────
        cmd_info     = SEARCH_COMMANDS.get(search_type, {})
        validity_key = cmd_info.get("validity_type", "generic")
        vtype        = VALIDITY_TYPES.get(validity_key, VALIDITY_TYPES["generic"])
        required     = vtype.get("required_any", [])
        min_fields   = vtype.get("min_fields", 0)

        if not required and min_fields == 0:
            return len(text.strip()) >= 20

        matched = sum(1 for field in required if field.lower() in text_lower)
        return matched >= max(min_fields, 1)

    @staticmethod
    def mask_result(text: str) -> str:
        """Mask sensitive data in a result for free/no-credit users.

        Keeps the structure visible but obscures the actual values so the user
        can see that data exists while being incentivised to purchase.
        """
        import random

        def _mask_value(val: str) -> str:
            """Mask a string value keeping first and last chars."""
            val = val.strip()
            if not val or val in ("NA", "N/A", "-", "—"):
                return val
            if len(val) <= 3:
                return val[0] + "█" * (len(val) - 1)
            # Keep up to 2 chars at start, rest masked
            visible_start = min(2, len(val) // 4)
            visible_end = 1 if len(val) > 6 else 0
            masked_len = len(val) - visible_start - visible_end
            return val[:visible_start] + "█" * masked_len + (val[-visible_end:] if visible_end else "")

        masked_lines = []
        for line in text.split("\n"):
            # Try to detect "KEY : VALUE" or "KEY: VALUE" patterns
            colon_pos = -1
            for sep in (" : ", ": ", ":", " = "):
                idx = line.find(sep)
                if idx > 0:
                    colon_pos = idx
                    sep_used = sep
                    break
            if colon_pos > 0:
                key_part = line[:colon_pos]
                value_part = line[colon_pos + len(sep_used):]
                masked_value = _mask_value(value_part)
                masked_lines.append(f"{key_part}{sep_used}{masked_value}")
            else:
                # Non key-value lines: mask most of the content
                if len(line.strip()) > 10 and not line.strip().startswith("─") \
                        and not line.strip().startswith("━") and not line.strip().startswith("#"):
                    masked_lines.append(_mask_value(line) if line.strip() else line)
                else:
                    masked_lines.append(line)
        return "\n".join(masked_lines)

# ================== ADMIN DATABASE MANAGER ==================

class AdminDatabaseManager:
    def __init__(self, db_manager):
        self.db = db_manager.db
    
    async def get_today_stats(self) -> Dict:
        """Get today's statistics"""
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Total users today
        new_users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.db.users.count_documents({
                "joined_at": {"$gte": today.isoformat()}
            })
        )
        
        # Total searches today
        search_logs = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.find({
                "timestamp": {"$gte": today.isoformat()}
            }))
        )
        
        # Total payments today
        payments = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.payments.find({
                "timestamp": {"$gte": today.isoformat()},
                "status": "completed"
            }))
        )
        
        total_payments = sum(p.get('amount', 0) for p in payments)
        
        return {
            "new_users": new_users,
            "total_searches": len(search_logs),
            "total_payments": total_payments,
            "payment_count": len(payments)
        }
    
    async def get_user_stats(self, user_id: int) -> Dict:
        """Get detailed user statistics"""
        user = await asyncio.get_running_loop().run_in_executor(
            None, self.db.users.find_one, {"user_id": user_id}
        )
        
        if not user:
            return {}
        
        # User's searches
        user_searches = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.find({"user_id": user_id}))
        )
        
        # User's referrals
        referrals = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.db.users.count_documents({"referred_by": str(user.get('referral_code', ''))})
        )
        
        return {
            "user_info": user,
            "total_searches": len(user_searches),
            "referrals": referrals,
            "last_searches": user_searches[-10:] if len(user_searches) > 10 else user_searches
        }
    
    async def get_top_users(self, limit: int = 10) -> List[Dict]:
        """Get top users by searches"""
        pipeline = [
            {"$group": {
                "_id": "$user_id",
                "total_searches": {"$sum": 1},
                "last_search": {"$max": "$timestamp"}
            }},
            {"$sort": {"total_searches": -1}},
            {"$limit": limit},
            {"$lookup": {
                "from": "users",
                "localField": "_id",
                "foreignField": "user_id",
                "as": "user_info"
            }},
            {"$unwind": "$user_info"},
            {"$project": {
                "user_id": "$_id",
                "username": "$user_info.username",
                "first_name": "$user_info.first_name",
                "total_searches": 1,
                "last_search": 1,
                "searches_remaining": "$user_info.searches_remaining",
                "subscription": "$user_info.subscription"
            }}
        ]
        
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.aggregate(pipeline))
        )
    
    async def get_command_stats(self) -> Dict:
        """Get command usage statistics"""
        pipeline = [
            {"$group": {
                "_id": "$search_type",
                "count": {"$sum": 1},
                "unique_users": {"$addToSet": "$user_id"}
            }},
            {"$project": {
                "command": "$_id",
                "count": 1,
                "unique_users": {"$size": "$unique_users"}
            }},
            {"$sort": {"count": -1}}
        ]
        
        command_stats = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.aggregate(pipeline))
        )
        
        # Get today's command stats
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_pipeline = [
            {"$match": {"timestamp": {"$gte": today.isoformat()}}},
            {"$group": {
                "_id": "$search_type",
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}}
        ]
        
        today_stats = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.aggregate(today_pipeline))
        )
        
        return {
            "all_time": command_stats,
            "today": today_stats
        }
    
    async def get_referral_stats(self) -> Dict:
        """Get referral statistics"""
        pipeline = [
            {"$match": {"referrals": {"$gt": 0}}},
            {"$sort": {"referrals": -1}},
            {"$limit": 20},
            {"$project": {
                "user_id": 1,
                "username": 1,
                "first_name": 1,
                "referrals": 1,
                "referral_code": 1,
                "referral_credits": 1
            }}
        ]
        
        top_referrers = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.users.aggregate(pipeline))
        )
        
        total_referrals = sum(user.get('referrals', 0) for user in top_referrers)
        
        return {
            "top_referrers": top_referrers,
            "total_referrals": total_referrals
        }
    
    async def get_payment_stats(self) -> Dict:
        """Get payment statistics"""
        pipeline = [
            {"$match": {"status": "completed"}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$toDate": "$timestamp"}}},
                "total_amount": {"$sum": "$amount"},
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": -1}},
            {"$limit": 30}
        ]
        
        daily_stats = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.payments.aggregate(pipeline))
        )
        
        # Total revenue
        total_revenue = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.db.payments.aggregate([
                {"$match": {"status": "completed"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ])
        )
        
        total_revenue = list(total_revenue)
        total = total_revenue[0]['total'] if total_revenue else 0
        
        return {
            "daily_stats": daily_stats,
            "total_revenue": total
        }
    
    async def get_user_list(self, page: int = 1, limit: int = 20) -> Dict:
        """Get paginated user list"""
        skip = (page - 1) * limit
        
        users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.users.find(
                {},
                {"user_id": 1, "username": 1, "first_name": 1, "joined_at": 1, "total_searches": 1}
            ).sort("joined_at", -1).skip(skip).limit(limit))
        )
        
        total_users = await asyncio.get_running_loop().run_in_executor(
            None, self.db.users.count_documents, {}
        )
        
        total_pages = (total_users + limit - 1) // limit
        
        return {
            "users": users,
            "page": page,
            "total_pages": total_pages,
            "total_users": total_users
        }
    
    async def search_users(self, query: str) -> List[Dict]:
        """Search users by username, name, or user_id"""
        try:
            # Try user_id if query is numeric
            if query.isdigit():
                user_id = int(query)
                users = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: list(self.db.users.find(
                        {"user_id": user_id},
                        {"user_id": 1, "username": 1, "first_name": 1, "joined_at": 1, "total_searches": 1}
                    ))
                )
            else:
                # Search by username or first name
                regex = re.compile(f".*{re.escape(query)}.*", re.IGNORECASE)
                users = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: list(self.db.users.find(
                        {"$or": [
                            {"username": regex},
                            {"first_name": regex}
                        ]},
                        {"user_id": 1, "username": 1, "first_name": 1, "joined_at": 1, "total_searches": 1}
                    ))
                )
            
            return users
        except Exception as e:
            logger.error(f"Error searching users: {e}")
            return []

# ================== PROTECTED QUERIES MANAGER ==================

class ProtectedQueriesManager:
    """Manage protected queries and payment verification"""
    
    def __init__(self, db_manager):
        self.db = db_manager.db
        self.protected_queries = self.db.protected_queries
        self.protection_payments = self.db.protection_payments
        
    async def is_query_protected(self, query: str) -> bool:
        """Check if a query is protected"""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.protected_queries.find_one({
                "query": query.lower().strip(),
                "status": "active"
            })
        )
        return result is not None
    
    async def add_protected_query(self, query: str, added_by: int, reason: str = "admin"):
        """Add a query to protected list"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.protected_queries.insert_one({
                "query": query.lower().strip(),
                "added_by": added_by,
                "reason": reason,
                "status": "active",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        )
        logger.info(f"🔒 Protected query added: {query}")
    
    async def remove_protected_query(self, query: str):
        """Remove a query from protected list"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.protected_queries.update_one(
                {"query": query.lower().strip()},
                {"$set": {"status": "removed"}}
            )
        )
        logger.info(f"🔓 Protected query removed: {query}")
    
    async def create_protection_request(self, user_id: int, query: str, utr: str):
        """Create a new protection request"""
        loop = asyncio.get_running_loop()
        request_id = str(uuid.uuid4())[:8]
        await loop.run_in_executor(
            None,
            lambda: self.protection_payments.insert_one({
                "request_id": request_id,
                "user_id": user_id,
                "query": query,
                "utr": utr,
                "amount": 50,
                "status": "pending",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        )
        return request_id
    
    async def approve_protection_request(self, request_id: str):
        """Approve a protection request"""
        loop = asyncio.get_running_loop()
        request = await loop.run_in_executor(
            None,
            lambda: self.protection_payments.find_one({"request_id": request_id})
        )
        
        if request:
            # Add query to protected list
            await self.add_protected_query(
                request["query"],
                request["user_id"],
                reason="user_paid"
            )
            
            # Update request status
            await loop.run_in_executor(
                None,
                lambda: self.protection_payments.update_one(
                    {"request_id": request_id},
                    {"$set": {
                        "status": "approved",
                        "approved_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
            )
            return True
        return False
    
    async def get_pending_protection_requests(self):
        """Get all pending protection requests"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: list(self.protection_payments.find(
                {"status": "pending"}
            ).sort("timestamp", -1).limit(20))
        )

# ================== DATABASE MANAGER ==================

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.admin_db = None
        self.api_db = None
    
    async def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            logger.info("🔌 Connecting to MongoDB...")
            self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            self.client.server_info()
            self.db = self.client[config.MONGODB_DBNAME]
            self.admin_db = AdminDatabaseManager(self)
            self.api_db = APIDatabaseManager(self)
            self.protected_manager = ProtectedQueriesManager(self)
            
            # Create indexes
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.create_index([("user_id", 1)], unique=True)
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.search_logs.create_index([("timestamp", -1)])
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.search_logs.create_index([("user_id", 1), ("timestamp", -1)])
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.payments.create_index([("timestamp", -1)])
            )
            
            # Create API-specific indexes
            # ── Drop old non-sparse client_token index BEFORE recreating ──
            # Must happen first; create_index fails if same name exists with
            # different options (e.g. missing sparse=True).
            loop = asyncio.get_running_loop()
            def _fix_client_token_index():
                try:
                    self.db.api_keys.drop_index("client_token_1")
                    logger.info("🔧 Dropped old client_token_1 index — will recreate as sparse")
                except Exception:
                    pass  # didn't exist, nothing to drop
                self.db.api_keys.create_index(
                    [("client_token", 1)],
                    unique=True,
                    sparse=True,
                    name="client_token_1"
                )
            await loop.run_in_executor(None, _fix_client_token_index)

            await loop.run_in_executor(
                None, lambda: self.db.api_keys.create_index([("api_key", 1)], unique=True)
            )
            await loop.run_in_executor(
                None, lambda: self.db.api_keys.create_index([("user_id", 1)])
            )
            await loop.run_in_executor(
                None, lambda: self.db.api_logs.create_index([("timestamp", -1)])
            )

            # Create protected queries indexes
            await loop.run_in_executor(
                None, lambda: self.db.protected_queries.create_index([("query", 1)])
            )
            await loop.run_in_executor(
                None, lambda: self.db.protection_payments.create_index([("request_id", 1)], unique=True)
            )

            logger.info("✅ MongoDB connected")
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            return False
    
    async def create_user(self, user_id: int, username: str, first_name: str, referral_code: str = None) -> bool:
        """Create new user with referral tracking"""
        try:
            referral_info = {}
            if referral_code:
                referral_info = {
                    "referred_by": referral_code,
                    "referral_code": str(user_id)[-6:],
                    "referral_date": datetime.now(timezone.utc).isoformat()
                }
            
            user_doc = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "joined_at": datetime.now(timezone.utc).isoformat(),
                "searches_remaining": config.NEW_USER_CREDITS,
                "total_searches": 0,
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "referral_code": str(user_id)[-6:],
                "referrals": 0,
                "referral_credits": 0,
                "subscription": None,
                "subscription_expiry": None,
                "wallet_balance": 0,
                "is_banned": False,
                "is_admin": False
            }
            
            if referral_info:
                user_doc.update(referral_info)
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$setOnInsert": user_doc},
                    upsert=True
                )
            )
            
            logger.info(f"✅ Created user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error creating user: {e}")
            return False
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self.db.users.find_one, {"user_id": user_id}
            )
        except Exception as e:
            logger.error(f"❌ Error getting user: {e}")
            return None
    
    async def update_searches(self, user_id: int, search_type: str, query: str,
                               success: bool = True, response_preview: str = "",
                               is_free_user: bool = False) -> bool:
        """Update user search count and log search with response for admin monitoring.
        
        Free/zero-credit users: log is always written (for admin trail) but no credits deducted.
        """
        try:
            user = await self.get_user(user_id)
            if not user and user_id != 0:
                # Still log even if user doc missing
                search_log = {
                    "user_id": user_id,
                    "search_type": search_type,
                    "query": query,
                    "success": success,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "credits_used": 0,
                    "subscription_used": None,
                    "response_preview": response_preview[:2000] if response_preview else "",
                    "is_free_user": True,
                }
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self.db.search_logs.insert_one(search_log)
                )
                return False
            
            # Check subscription first
            subscription = user.get("subscription") if user else None
            subscription_expiry = user.get("subscription_expiry") if user else None
            
            if subscription and subscription_expiry:
                try:
                    expiry_date = datetime.fromisoformat(subscription_expiry)
                except Exception:
                    expiry_date = None
                if expiry_date and expiry_date > datetime.now(timezone.utc):
                    # Daily-limit subscription: increment today's usage
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: self.db.users.update_one(
                            {"user_id": user_id},
                            {
                                "$inc": {"total_searches": 1, "subscription_used_today": 1},
                                "$set": {"last_seen": datetime.now(timezone.utc).isoformat(),
                                         "subscription_reset_date": today_str}
                            }
                        )
                    )

                    # Log search — store full response for admin trail
                    search_log = {
                        "user_id": user_id,
                        "search_type": search_type,
                        "query": query,
                        "success": success,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "credits_used": 0,
                        "subscription_used": subscription,
                        "response_preview": response_preview[:2000] if response_preview else "",
                        "is_free_user": False,
                    }

                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: self.db.search_logs.insert_one(search_log)
                    )
                    return True
            
            # Use credits
            searches_remaining = user.get("searches_remaining", 0) if user else 0
            
            if searches_remaining <= 0 or is_free_user:
                # Zero-credit / free user: log but don't deduct
                search_log = {
                    "user_id": user_id,
                    "search_type": search_type,
                    "query": query,
                    "success": success,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "credits_used": 0,
                    "subscription_used": None,
                    "response_preview": response_preview[:2000] if response_preview else "",
                    "is_free_user": True,
                }
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self.db.search_logs.insert_one(search_log)
                )
                if user:
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: self.db.users.update_one(
                            {"user_id": user_id},
                            {"$inc": {"total_searches": 1},
                             "$set": {"last_seen": datetime.now(timezone.utc).isoformat()}}
                        )
                    )
                return True  # log succeeded even though no credits deducted
            
            credits_used = SEARCH_COMMANDS.get(search_type, {}).get("cost", 1)
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {
                            "searches_remaining": -credits_used,
                            "total_searches": 1
                        },
                        "$set": {"last_seen": datetime.now(timezone.utc).isoformat()}
                    }
                )
            )
            
            # Log search — full response for admin trail
            search_log = {
                "user_id": user_id,
                "search_type": search_type,
                "query": query,
                "success": success,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "credits_used": credits_used,
                "subscription_used": None,
                "response_preview": response_preview[:2000] if response_preview else "",
                "is_free_user": False,
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.search_logs.insert_one(search_log)
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error updating searches: {e}")
            return False
    
    async def add_subscription(self, user_id: int, plan_id: str, days: int) -> bool:
        """Add subscription to user and sync to linked client account"""
        try:
            plan = SUBSCRIPTION_PLANS[plan_id]
            expiry_date = datetime.now(timezone.utc) + timedelta(days=days)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            
            sub_update = {
                "subscription": plan_id,
                "subscription_expiry": expiry_date.isoformat(),
                "searches_remaining": 0,  # subscription replaces credits
                "subscription_used_today": 0,
                "subscription_reset_date": today_str
            }

            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$set": sub_update}
                )
            )

            # Sync subscription to linked accounts collection so client script works
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self.db.accounts.update_one(
                        {"linked_tg_ids": user_id},
                        {"$set": {
                            "subscription": plan_id,
                            "subscription_expiry": expiry_date.isoformat(),
                            "subscription_used_today": 0,
                            "subscription_reset_date": today_str
                        }}
                    )
                )
            except Exception as _se:
                logger.warning(f"Could not sync subscription to accounts collection for user {user_id}: {_se}")
            
            # Log payment
            payment_log = {
                "user_id": user_id,
                "plan_id": plan_id,
                "amount": plan["price"],
                "status": "completed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "admin_added": True
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.payments.insert_one(payment_log)
            )
            
            return True
        except Exception as e:
            logger.error(f"❌ Error adding subscription: {e}")
            return False
    
    async def add_referral_credit(self, referrer_id: int, credits: int = 1) -> bool:
        """Add referral credits to referrer"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": referrer_id},
                    {
                        "$inc": {
                            "referrals": 1,
                            "referral_credits": credits,
                            "searches_remaining": credits
                        }
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error adding referral credit: {e}")
            return False
    
    async def ban_user(self, user_id: int, reason: str = "Violation of terms") -> bool:
        """Ban a user"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "is_banned": True,
                            "ban_reason": reason,
                            "banned_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error banning user: {e}")
            return False
    
    async def unban_user(self, user_id: int) -> bool:
        """Unban a user"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "is_banned": False
                        },
                        "$unset": {
                            "ban_reason": "",
                            "banned_at": ""
                        }
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error unbanning user: {e}")
            return False
    
    async def add_admin(self, user_id: int) -> bool:
        """Add user as admin"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_admin": True}}
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error adding admin: {e}")
            return False
    
    async def remove_admin(self, user_id: int) -> bool:
        """Remove user from admin"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_admin": False}}
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error removing admin: {e}")
            return False
    
    async def add_credits(self, user_id: int, credits: int) -> bool:
        """Add credits to user and sync to linked client account"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$inc": {"searches_remaining": credits}}
                )
            )
            # Sync to linked accounts collection
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self.db.accounts.update_one(
                        {"linked_tg_ids": user_id},
                        {"$inc": {"searches_remaining": credits}}
                    )
                )
            except Exception as _se:
                logger.warning(f"Could not sync credits to accounts collection for user {user_id}: {_se}")
            return True
        except Exception as e:
            logger.error(f"❌ Error adding credits: {e}")
            return False

    async def take_credits(self, user_id: int, credits: int) -> bool:
        """Subtract credits from a user (floors at 0, never goes negative)"""
        try:
            user = await asyncio.get_running_loop().run_in_executor(
                None, self.db.users.find_one, {"user_id": user_id}
            )
            if not user:
                return False
            current = user.get("searches_remaining", 0)
            deduct = min(credits, current)
            if deduct <= 0:
                return True
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$inc": {"searches_remaining": -deduct}}
                )
            )
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self.db.accounts.update_one(
                        {"linked_tg_ids": user_id},
                        {"$inc": {"searches_remaining": -deduct}}
                    )
                )
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"❌ Error taking credits: {e}")
            return False

    async def give_credits_all_users(self, credits: int) -> int:
        """Add credits to EVERY user. Returns count of updated users."""
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_many(
                    {},
                    {"$inc": {"searches_remaining": credits}}
                )
            )
            return result.modified_count
        except Exception as e:
            logger.error(f"❌ Error giving credits to all: {e}")
            return 0

    async def take_credits_all_users(self, credits: int) -> int:
        """Subtract up to `credits` from every user (each floored at 0).
        Returns count of updated users."""
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_many(
                    {"searches_remaining": {"$gt": 0}},
                    [{"$set": {
                        "searches_remaining": {
                            "$max": [0, {"$subtract": ["$searches_remaining", credits]}]
                        }
                    }}]
                )
            )
            return result.modified_count
        except Exception as e:
            logger.error(f"❌ Error taking credits from all: {e}")
            return 0

# ================== ONE COMMAND PER LINE KEYBOARD ==================

class APIDatabaseManager:
    """Manage API keys and access"""
    
    def __init__(self, db_manager):
        self.db = db_manager.db
    
    async def create_api_key(self, user_id: int, plan_id: str, days: int, description: str = "") -> Dict:
        """Create a new API key"""
        try:
            api_key = APIKeyManager.generate_api_key(user_id, description)
            client_token = APIKeyManager.generate_client_token(api_key)
            
            expiry_date = datetime.now(timezone.utc) + timedelta(days=days)
            
            # Get plan details
            plan = API_PLANS.get(plan_id, API_PLANS["unlimited"])
            
            api_doc = {
                "api_key": api_key,
                "client_token": client_token,
                "user_id": user_id,
                "plan_id": plan_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": expiry_date.isoformat(),
                "description": description,
                "is_active": True,
                "total_requests": 0,
                "requests_used": 0,
                "requests_remaining": plan.get("requests", "Unlimited") if not plan.get("unlimited") else 999999,
                "rate_limit": plan.get("rate_limit", 10),
                "concurrent_limit": plan.get("concurrent", 1),
                "last_used": None,
                "unlimited": plan.get("unlimited", False)
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.insert_one(api_doc)
            )
            
            return api_doc
            
        except Exception as e:
            logger.error(f"❌ Error creating API key: {e}")
            return None
    
    async def get_api_key(self, api_key: str) -> Optional[Dict]:
        """Get API key information"""
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self.db.api_keys.find_one, {"api_key": api_key}
            )
        except Exception as e:
            logger.error(f"❌ Error getting API key: {e}")
            return None
    
    async def get_api_key_by_client_token(self, client_token: str) -> Optional[Dict]:
        """Get API key by client token"""
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self.db.api_keys.find_one, {"client_token": client_token, "is_active": True}
            )
        except Exception as e:
            logger.error(f"❌ Error getting API key by token: {e}")
            return None
    
    async def validate_api_key(self, api_key: str) -> Tuple[bool, str]:
        """Validate API key"""
        api_info = await self.get_api_key(api_key)
        
        if not api_info:
            return False, "Invalid API key"
        
        if not api_info.get("is_active", True):
            return False, "API key is inactive"
        
        # Check expiry
        expires_at = datetime.fromisoformat(api_info["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            return False, "API key expired"
        
        # Check usage limits (skip for unlimited plans)
        if not api_info.get("unlimited", False):
            if api_info.get("requests_remaining", 0) <= 0:
                return False, "API request limit exceeded"
        
        return True, ""
    
    async def record_api_request(self, api_key: str, endpoint: str, success: bool = True):
        """Record API request"""
        try:
            api_info = await self.get_api_key(api_key)
            if not api_info:
                return
            
            update_data = {
                "$inc": {
                    "total_requests": 1,
                    "requests_used": 1
                },
                "$set": {
                    "last_used": datetime.now(timezone.utc).isoformat(),
                    "last_endpoint": endpoint
                }
            }
            
            # Decrease remaining requests for limited plans
            if not api_info.get("unlimited", False):
                update_data["$inc"]["requests_remaining"] = -1
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.update_one(
                    {"api_key": api_key},
                    update_data
                )
            )
            
            # Log API request
            log_doc = {
                "api_key": api_key,
                "endpoint": endpoint,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": success
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_logs.insert_one(log_doc)
            )
            
        except Exception as e:
            logger.error(f"❌ Error recording API request: {e}")
    
    async def get_user_api_keys(self, user_id: int) -> List[Dict]:
        """Get all API keys for a user"""
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.api_keys.find(
                    {"user_id": user_id},
                    {"api_key": 1, "plan_id": 1, "created_at": 1, 
                     "expires_at": 1, "description": 1, "is_active": 1,
                     "requests_used": 1, "requests_remaining": 1, "total_requests": 1}
                ).sort("created_at", -1))
            )
        except Exception as e:
            logger.error(f"❌ Error getting user API keys: {e}")
            return []
    
    async def delete_api_key(self, api_key: str) -> bool:
        """Delete (deactivate) an API key"""
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.update_one(
                    {"api_key": api_key},
                    {"$set": {"is_active": False, "deactivated_at": datetime.now(timezone.utc).isoformat()}}
                )
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"❌ Error deleting API key: {e}")
            return False
    
    async def extend_api_key(self, api_key: str, additional_days: int) -> bool:
        """Extend API key expiry"""
        try:
            api_info = await self.get_api_key(api_key)
            if not api_info:
                return False
            
            current_expiry = datetime.fromisoformat(api_info["expires_at"])
            new_expiry = current_expiry + timedelta(days=additional_days)
            
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.update_one(
                    {"api_key": api_key},
                    {"$set": {"expires_at": new_expiry.isoformat()}}
                )
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"❌ Error extending API key: {e}")
            return False
    
    async def get_api_stats(self, user_id: int = None) -> Dict:
        """Get API statistics"""
        try:
            query = {}
            if user_id is not None:
                query["user_id"] = user_id
            
            # Total API keys
            total_keys = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.count_documents(query)
            )
            
            # Active API keys
            active_keys = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.count_documents({**query, "is_active": True})
            )
            
            # Total API requests
            pipeline = [
                {"$match": query},
                {"$group": {
                    "_id": None,
                    "total_requests": {"$sum": "$total_requests"},
                    "total_used": {"$sum": "$requests_used"}
                }}
            ]
            
            stats_result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.api_keys.aggregate(pipeline))
            )
            
            total_requests = stats_result[0]["total_requests"] if stats_result else 0
            total_used = stats_result[0]["total_used"] if stats_result else 0
            
            # Recent API activity
            recent_activity = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.api_logs.find(
                    query,
                    {"timestamp": 1, "endpoint": 1, "success": 1}
                ).sort("timestamp", -1).limit(10))
            )
            
            return {
                "total_keys": total_keys,
                "active_keys": active_keys,
                "total_requests": total_requests,
                "requests_used": total_used,
                "recent_activity": recent_activity
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting API stats: {e}")
            return {}

# ================== ADMIN DATABASE MANAGER ==================



class OneLineKeyboard:
    @staticmethod
    def main_menu(is_admin: bool = False, disabled_buttons: set = None) -> List[List[Button]]:
        """Clean keyboard — no emojis, real command names, 2 per row."""
        if disabled_buttons is None:
            disabled_buttons = set()

        # (key, label shown on button)
        search_items = [
            ("phone",    "Phone Lookup"),
            ("family",   "Family Search"),
            ("aadhar",   "ID Search"),
            ("vehicle",  "Vehicle Info"),
            ("telegram", "Telegram Lookup"),
            ("imei",     "IMEI Trace"),
            ("gst",      "GST Business"),
            ("insta",    "Instagram Info"),
            ("ip",       "IP Location"),
            ("ifsc",     "Bank / IFSC"),
        ]

        buttons = []
        visible = [(k, l) for k, l in search_items
                   if k not in disabled_buttons and k in SEARCH_COMMANDS]

        for i in range(0, len(visible), 2):
            row = [Button.inline(label, f"search_{key}") for key, label in visible[i:i+2]]
            buttons.append(row)

        buttons.append([Button.inline("My Profile",     "profile"),
                        Button.inline("Buy Credits",    "premium")])
        buttons.append([Button.inline("Refer & Earn",   "referrals"),
                        Button.inline("Support",        "support")])
        buttons.append([Button.inline("API Access",     "api_menu"),
                        Button.inline("Message Admin",  "user_message_admin")])

        if is_admin:
            buttons.append([Button.inline("Admin Panel", "admin_panel")])

        return buttons
    
    @staticmethod
    def subscription_plans() -> List[List[Button]]:
        """Premium plan selection — credit packs + monthly subscriptions"""
        buttons = [
            [Button.inline("⚡ 5 Credits · ₹200", "plan_credits_5")],
            [Button.inline("📱 Unlimited NUM · ₹300/mo", "plan_sub_num_monthly")],
            [Button.inline("💎 Unlimited ALL · ₹499/mo  (Best Value)", "plan_sub_all_monthly")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        return buttons
    
    @staticmethod
    def admin_panel() -> List[List[Button]]:
        """Compact admin panel — grouped into sections, 2 per row."""
        return [
            # Stats & users
            [Button.inline("Stats",          "admin_today"),
             Button.inline("Users",          "admin_users")],
            [Button.inline("Search Logs",    "admin_search_logs"),
             Button.inline("Analytics",      "admin_analytics")],
            [Button.inline("Payments",       "admin_payments"),
             Button.inline("Pending UTR",    "admin_pending_utr")],
            [Button.inline("Search User",    "admin_search_user"),
             Button.inline("Intent Monitor", "admin_intent_monitor")],
            # Credits & subscriptions
            [Button.inline("Add Credits",    "admin_add_credits"),
             Button.inline("Give Sub",       "admin_give_subscription")],
            [Button.inline("Credits All",    "admin_give_credits_all"),
             Button.inline("Take Credits",   "admin_take_credits_user")],
            # Broadcasts & polls
            [Button.inline("Text Broadcast", "admin_broadcast"),
             Button.inline("Media Broadcast","admin_broadcast_media")],
            [Button.inline("Send Poll",      "admin_send_poll"),
             Button.inline("Broadcast History","admin_broadcast_history")],
            # Moderation
            [Button.inline("Ban / Unban",    "admin_ban"),
             Button.inline("Add Admin",      "admin_admin")],
            [Button.inline("Restrict Queries","admin_restricted_queries"),
             Button.inline("Restrict Buttons","admin_restrict_buttons")],
            # Group & Command config (NEW)
            [Button.inline("⚙️ Groups & Commands", "admin_group_cmd_mgmt"),
             Button.inline("🆓 Free User Config",  "admin_free_user_config")],
            [Button.inline("📢 Force-Join Channels", "admin_force_join"),
             Button.inline("🤖 Bot Settings",       "admin_settings")],
            # Other
            [Button.inline("API Panel",      "admin_api"),
             Button.inline("Export Data",    "admin_export")],
            [Button.inline("Reset Password", "admin_reset_password"),
             Button.inline("Bot Settings",   "admin_settings")],
            [Button.inline("Main Menu",      "main_menu")],
        ]
    
    @staticmethod
    def user_management_panel() -> List[List[Button]]:
        """User management panel"""
        buttons = [
            [Button.inline("📋 User List", "admin_user_list_1")],
            [Button.inline("🏆 Top Users", "admin_top_users")],
            [Button.inline("📊 Referral Stats", "admin_referrals")],
            [Button.inline("« Admin Panel", "admin_panel")]
        ]
        return buttons
    
    @staticmethod
    def analytics_panel() -> List[List[Button]]:
        """Analytics panel"""
        buttons = [
            [Button.inline("📈 Command Usage", "admin_command_stats")],
            [Button.inline("📊 Daily Stats Graph", "admin_graph_daily")],
            [Button.inline("📋 Most Used Commands", "admin_top_commands")],
            [Button.inline("👤 User Activity", "admin_user_activity")],
            [Button.inline("« Admin Panel", "admin_panel")]
        ]
        return buttons
    
    @staticmethod
    def payment_panel() -> List[List[Button]]:
        """Payment management panel"""
        buttons = [
            [Button.inline("💰 Today's Revenue", "admin_today_payments")],
            [Button.inline("📊 Revenue Graph", "admin_graph_revenue")],
            [Button.inline("💸 Total Revenue", "admin_total_revenue")],
            [Button.inline("« Admin Panel", "admin_panel")]
        ]
        return buttons
    
    @staticmethod
    def user_list_buttons(page: int, total_pages: int) -> List[List[Button]]:
        """User list pagination buttons"""
        buttons = []
        
        # Navigation buttons
        nav_row = []
        if page > 1:
            nav_row.append(Button.inline("⬅️ Previous", f"admin_user_list_{page-1}"))
        nav_row.append(Button.inline(f"{page}/{total_pages}", "noop"))
        if page < total_pages:
            nav_row.append(Button.inline("Next ➡️", f"admin_user_list_{page+1}"))
        
        if nav_row:
            buttons.append(nav_row)
        
        buttons.append([Button.inline("« User Management", "admin_users")])
        buttons.append([Button.inline("« Admin Panel", "admin_panel")])
        
        return buttons
    
    @staticmethod
    def cancel_button() -> List[List[Button]]:
        """Cancel button"""
        return [[Button.inline("❌ Cancel", "main_menu")]]
    
    @staticmethod
    def back_to_admin() -> List[List[Button]]:
        """Back to admin panel button"""
        return [[Button.inline("« Back to Admin", "admin_panel")]]
    
    @staticmethod
    def confirm_buttons(action: str, target_id: int) -> List[List[Button]]:
        """Confirmation buttons for actions"""
        return [
            [Button.inline(f"✅ Confirm {action}", f"confirm_{action}_{target_id}")],
            [Button.inline("❌ Cancel", "admin_panel")]
        ]
    
    @staticmethod
    def profile_menu() -> List[List[Button]]:
        """Profile menu buttons"""
        return [
            [Button.inline("🔄 Refresh", "profile")],
            [Button.inline("💳 Add Credits", "buy_credits")],
            [Button.inline("💎 Upgrade Plan", "premium")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def support_menu() -> List[List[Button]]:
        """Support menu buttons"""
        return [
            [Button.inline("📞 Contact Admin", "contact_admin")],
            [Button.inline("❓ FAQ", "faq")],
            [Button.inline("⚠️ Report Issue", "report_issue")],
            [Button.inline("📖 Tutorial", "tutorial")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def referrals_menu() -> List[List[Button]]:
        """Referrals menu buttons"""
        return [
            [Button.inline("📋 My Referrals", "my_referrals")],
            [Button.inline("📊 Referral Stats", "referral_stats")],
            [Button.inline("📢 Share Referral", "share_referral")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def api_menu() -> List[List[Button]]:
        """API access menu"""
        return [
            [Button.inline("🔑 My API Keys", "my_api_keys")],
            [Button.inline("📊 API Usage Stats", "api_usage")],
            [Button.inline("📖 API Documentation", "api_docs")],
            [Button.inline("💎 API Plans", "api_plans")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def api_plans_menu() -> List[List[Button]]:
        """API plans selection"""
        return [
            [Button.inline("💰 Basic API - ₹499/month", "api_plan_basic")],
            [Button.inline("🚀 Pro API - ₹999/month", "api_plan_pro")],
            [Button.inline("👑 Enterprise API - ₹2999/month", "api_plan_enterprise")],
            [Button.inline("« API Menu", "api_menu")]
        ]
    
    @staticmethod
    def api_admin_panel() -> List[List[Button]]:
        """API admin panel buttons"""
        return [
            [Button.inline("📊 API Statistics", "admin_api_stats")],
            [Button.inline("🔑 Manage API Keys", "admin_api_keys")],
            [Button.inline("📈 API Analytics", "admin_api_analytics")],
            [Button.inline("« Admin Panel", "admin_panel")]
        ]

# ================== ADMIN PANEL HANDLER ==================

class AdminPanelHandler:
    def __init__(self, db_manager: DatabaseManager, bot_client: TelegramClient):
        self.db = db_manager
        self.bot = bot_client
        self.admin_users = set()
        
        # Load admin users from database
        asyncio.create_task(self.load_admin_users())
    
    async def load_admin_users(self):
        """Load admin users from database"""
        try:
            admins = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.users.find({"is_admin": True}, {"user_id": 1}))
            )
            self.admin_users = {admin["user_id"] for admin in admins}
            logger.info(f"✅ Loaded {len(self.admin_users)} admin users")
        except Exception as e:
            logger.error(f"❌ Error loading admin users: {e}")
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in self.admin_users or user_id == config.ADMIN_USER_ID
    
    async def handle_admin_callback(self, event):
        """Handle admin panel callbacks"""
        try:
            user_id = event.sender_id

            if not self.is_admin(user_id):
                await event.answer("❌ Access denied", alert=True)
                return

            data = event.data.decode()

            if data == "admin_panel":
                await self.show_admin_panel(event)
            elif data == "admin_today":
                await self.show_today_stats(event)
            elif data.startswith("admin_user_list_"):
                page = int(data.split("_")[-1])
                await self.show_user_list(event, page)
            elif data == "admin_users":
                await self.show_user_management(event)
            elif data == "admin_top_users":
                await self.show_top_users(event)
            elif data == "admin_referrals":
                await self.show_referral_stats(event)
            elif data == "admin_analytics":
                await self.show_analytics_panel(event)
            elif data == "admin_command_stats":
                await self.show_command_stats(event)
            elif data == "admin_top_commands":
                await self.show_top_commands(event)
            elif data == "admin_user_activity":
                await self.show_user_activity(event)
            elif data == "admin_graph_daily":
                await self.generate_daily_graph(event)
            elif data == "admin_payments":
                await self.show_payment_panel(event)
            elif data == "admin_today_payments":
                await self.show_today_payments(event)
            elif data == "admin_total_revenue":
                await self.show_total_revenue(event)
            elif data == "admin_graph_revenue":
                await self.generate_revenue_graph(event)
            elif data == "admin_search_user":
                await self.ask_for_user_search(event)
            elif data == "admin_broadcast":
                await self.ask_for_broadcast(event)
            elif data == "admin_broadcast_media":
                await self.ask_for_broadcast_media(event)
            elif data == "admin_broadcast_history":
                await self.show_broadcast_history(event)
            elif data == "admin_pending_payments":
                await self.show_pending_payments(event)
            elif data == "admin_last_active":
                await admin_last_active_callback(event)
            elif data == "admin_search_logs":
                await admin_search_logs_callback(event)
            elif data == "admin_user_search_logs":
                await admin_user_search_logs_ask(event)
            elif data == "admin_intent_monitor":
                await admin_intent_monitor_callback(event)
            elif data == "admin_pending_utr":
                await admin_pending_utr_callback(event)
            elif data.startswith("admin_broadcast_seen_"):
                broadcast_id = data[len("admin_broadcast_seen_"):]
                await self.show_broadcast_seen(event, broadcast_id)
            elif data == "admin_ban":
                await self.ask_for_ban_user(event)
            elif data == "admin_admin":
                await self.ask_for_admin_management(event)
            elif data == "admin_add_credits":
                await self.ask_for_add_credits(event)
            elif data == "admin_give_subscription":
                await self.ask_for_give_subscription(event)
            elif data == "admin_settings":
                await self.show_bot_settings(event)
            elif data == "admin_export":
                await self.export_data(event)
            elif data == "admin_api":
                await self.show_api_panel(event)
            elif data == "admin_api_stats":
                await self.show_api_stats(event)
            elif data == "admin_api_user":
                await self.ask_for_api_user_management(event)
            elif data == "admin_api_analytics":
                await self.show_api_analytics(event)
            elif data == "admin_api_revoke":
                await self.ask_for_api_revoke(event)
            elif data == "admin_group_cmd_mgmt":
                await self.show_group_cmd_mgmt(event)
            elif data == "admin_free_user_config":
                await self.show_free_user_config(event)
            elif data.startswith("admin_gcmd_group_"):
                await self.show_group_detail(event, data[len("admin_gcmd_group_"):])
            elif data.startswith("admin_gcmd_setcmd_"):
                # admin_gcmd_setcmd_<group_key>_<search_type>
                parts = data[len("admin_gcmd_setcmd_"):].split("_", 1)
                if len(parts) == 2:
                    await self.prompt_set_group_cmd(event, parts[0], parts[1])
            elif data.startswith("admin_gcmd_vtype_"):
                # admin_gcmd_vtype_<search_type>
                stype = data[len("admin_gcmd_vtype_"):]
                await self.prompt_set_validity_type(event, stype)
            elif data.startswith("admin_freegroup_toggle_"):
                gkey = data[len("admin_freegroup_toggle_"):]
                await self.toggle_free_group(event, gkey)
            elif data.startswith("admin_freecmd_toggle_"):
                ckey = data[len("admin_freecmd_toggle_"):]
                await self.toggle_free_command(event, ckey)
            elif data.startswith("confirm_ban_"):
                target_id = int(data.split("_")[-1])
                await self.confirm_ban_user(event, target_id)
            elif data.startswith("confirm_unban_"):
                target_id = int(data.split("_")[-1])
                await self.confirm_unban_user(event, target_id)
            elif data.startswith("confirm_add_admin_"):
                target_id = int(data.split("_")[-1])
                await self.confirm_add_admin(event, target_id)
            elif data.startswith("confirm_remove_admin_"):
                target_id = int(data.split("_")[-1])
                await self.confirm_remove_admin(event, target_id)
            elif data.startswith("user_detail_"):
                target_id = int(data.split("_")[-1])
                await self.show_user_detail(event, target_id)
            elif data.startswith("admin_give_sub_"):
                target_id = int(data.split("_")[-1])
                await self.show_give_sub_for_user(event, target_id)
            elif data.startswith("admin_add_credits_user_"):
                target_id = int(data.split("_")[-1])
                user_states[event.sender_id] = {
                    "action": "admin_add_credits",
                    "preset_user_id": target_id
                }
                await event.edit(
                    f"🎯 **ADD CREDITS TO USER** `{target_id}`\n\n"
                    f"Enter number of credits to add (1–10000):\n"
                    f"Just type the number:",
                    buttons=OneLineKeyboard.back_to_admin(),
                    parse_mode="md"
                )
            elif data.startswith("confirm_create_api_"):
                parts = data.split("_")
                if len(parts) >= 5:
                    plan_id = parts[3]
                    days = int(parts[4])
                    await self.confirm_create_api_key(event, plan_id, days)
            elif data.startswith("confirm_revoke_api_"):
                api_key = data.split("_", 3)[3]
                await self.confirm_revoke_api_key(event, api_key)
            elif data == "api_menu":
                await self.show_api_menu(event)
            elif data == "my_api_keys":
                await self.show_my_api_keys(event)
            elif data == "api_usage":
                await self.show_api_usage(event)
            elif data == "api_plans":
                await self.show_api_plans(event)
            elif data == "api_docs":
                await self.show_api_docs(event)
            elif data.startswith("api_plan_"):
                plan_id = data.split("_", 2)[2]
                await self.show_api_plan_details(event, plan_id)
            elif data == "create_api_key":
                await self.ask_for_api_plan_selection(event)
            elif data == "admin_reset_password":
                await self.ask_for_password_reset(event)
            elif data.startswith("admin_reset_pass_confirm_"):
                account_id_target = data.split("admin_reset_pass_confirm_")[1]
                await self.confirm_password_reset(event, account_id_target)
            elif data == "admin_give_credits_all":
                await self.ask_for_give_credits_all(event)
            elif data == "admin_take_credits_user":
                await self.ask_for_take_credits_user(event)
            elif data == "admin_take_credits_all":
                await self.ask_for_take_credits_all(event)

        except Exception as e:
            logger.error(f"❌ Error in admin callback: {e}")
            await event.answer("❌ Error processing request", alert=True)
    
    async def show_admin_panel(self, event):
        """Show main admin panel"""
        admin_text = (
            "⚙️ **DARKBOXES ADMIN PANEL**\n\n"
            "📊 **Quick Stats**\n"
        )
        
        # Get quick stats
        try:
            today_stats = await self.db.admin_db.get_today_stats()
            admin_text += f"├─ Today's Users: {today_stats['new_users']}\n"
            admin_text += f"├─ Today's Searches: {today_stats['total_searches']}\n"
            admin_text += f"├─ Today's Payments: ₹{today_stats['total_payments']}\n"
            
            total_users = await asyncio.get_running_loop().run_in_executor(
                None, self.db.db.users.count_documents, {}
            )
            admin_text += f"└─ Total Users: {total_users}\n"
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            admin_text += "⚠️ Error loading stats\n"
        
        admin_text += "\n🔧 **Select an option below:**"
        
        await event.edit(admin_text, buttons=OneLineKeyboard.admin_panel(), parse_mode="md")
    
    async def show_today_stats(self, event):
        """Show today's statistics in detail"""
        try:
            today_stats = await self.db.admin_db.get_today_stats()
            command_stats = await self.db.admin_db.get_command_stats()
            
            stats_text = (
                "📊 **TODAY'S STATISTICS**\n"
                "═══════════════════════\n\n"
                f"📈 **User Statistics**\n"
                f"├─ New Users: {today_stats['new_users']}\n"
                f"├─ Total Searches: {today_stats['total_searches']}\n"
                f"├─ Total Payments: ₹{today_stats['total_payments']}\n"
                f"└─ Payment Count: {today_stats['payment_count']}\n\n"
            )
            
            if command_stats['today']:
                stats_text += "🔍 **Top Commands Today**\n"
                for i, cmd in enumerate(command_stats['today'][:5], 1):
                    cmd_name = SEARCH_COMMANDS.get(cmd['_id'], {}).get('name', cmd['_id'])
                    stats_text += f"{i}. {cmd_name}: {cmd['count']} searches\n"
            
            await event.edit(stats_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing today stats: {e}")
            await event.edit("❌ Error loading statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_user_list(self, event, page: int = 1):
        """Show paginated user list with full details"""
        try:
            # Fetch from DB with all fields
            limit = 10
            skip = (page - 1) * limit
            loop = asyncio.get_running_loop()

            users = await loop.run_in_executor(
                None, lambda: list(self.db.db.users.find(
                    {},
                    {"user_id": 1, "username": 1, "first_name": 1, "joined_at": 1,
                     "total_searches": 1, "searches_remaining": 1, "subscription": 1,
                     "is_banned": 1}
                ).sort("joined_at", -1).skip(skip).limit(limit))
            )
            total_users = await loop.run_in_executor(
                None, self.db.db.users.count_documents, {}
            )
            total_pages = max(1, (total_users + limit - 1) // limit)

            users_text = (
                f"👥 **USER LIST** — Page {page}/{total_pages}\n"
                f"📊 Total Registered: **{total_users}**\n"
                "═══════════════════════\n\n"
            )

            if not users:
                users_text += "No users found on this page."
            else:
                for i, user in enumerate(users, 1):
                    idx = (page - 1) * limit + i
                    username = f"@{user['username']}" if user.get('username') else "—"
                    joined = user.get('joined_at', '')[:10]
                    searches = user.get('total_searches', 0)
                    credits = user.get('searches_remaining', 0)
                    sub = user.get('subscription') or "None"
                    banned = "🚫" if user.get('is_banned') else "✅"

                    users_text += (
                        f"{banned} **{idx}. {user.get('first_name', 'N/A')}**\n"
                        f"   ├─ {username} | ID: `{user['user_id']}`\n"
                        f"   ├─ Joined: {joined}\n"
                        f"   ├─ Searches: {searches} | Credits: {credits}\n"
                        f"   └─ Plan: {sub}\n\n"
                    )

            # Build nav buttons
            buttons = []
            nav_row = []
            if page > 1:
                nav_row.append(Button.inline("⬅️ Prev", f"admin_user_list_{page-1}"))
            nav_row.append(Button.inline(f"{page}/{total_pages}", "noop"))
            if page < total_pages:
                nav_row.append(Button.inline("Next ➡️", f"admin_user_list_{page+1}"))
            if nav_row:
                buttons.append(nav_row)
            buttons.append([Button.inline("🔍 Search User", "admin_search_user")])
            buttons.append([Button.inline("« User Mgmt", "admin_users"), Button.inline("« Admin", "admin_panel")])

            await event.edit(users_text, buttons=buttons, parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing user list: {e}")
            await event.edit(f"❌ Error loading user list: {e}", buttons=OneLineKeyboard.back_to_admin())
    
    async def ask_for_password_reset(self, event):
        """Admin: prompt for account ID to reset password"""
        user_states[event.sender_id] = {"action": "admin_reset_password"}
        await event.edit(
            "🔑 **RESET USER PASSWORD**\n\n"
            "Enter the **Account ID** (e.g. `DBEFBF325A`) of the account\n"
            "whose password you want to reset.\n\n"
            "The user will receive their new temporary password via this bot.",
            buttons=[[Button.inline("« Admin Panel", "admin_panel")]],
            parse_mode="md"
        )

    async def confirm_password_reset(self, event, account_id_target: str):
        """Admin: show confirmation before resetting password"""
        loop = asyncio.get_running_loop()
        account = await loop.run_in_executor(
            None, lambda: db_manager.db.accounts.find_one({"account_id": account_id_target.upper()})
        )
        if not account:
            await event.answer(f"❌ Account {account_id_target} not found", alert=True)
            return
        # Generate a temp password
        import secrets as _sec
        temp_pass = _sec.token_urlsafe(8)
        pwd_hash = __import__("hashlib").sha256(temp_pass.encode()).hexdigest()
        await loop.run_in_executor(
            None, lambda: db_manager.db.accounts.update_one(
                {"account_id": account_id_target.upper()},
                {"$set": {"password_hash": pwd_hash, "temp_password": True}}
            )
        )
        # Notify all linked TG users
        linked_ids = account.get("linked_tg_ids", [])
        notified = 0
        for tg_id in linked_ids:
            try:
                await bot_client.send_message(
                    tg_id,
                    f"🔑 **PASSWORD RESET — DARKBOXES**\n\n"
                    f"An admin has reset your account password.\n\n"
                    f"🆔 **Account ID:** `{account_id_target.upper()}`\n"
                    f"🔐 **New Temporary Password:** `{temp_pass}`\n\n"
                    f"⚠️ Please log in and note this password securely.\n"
                    f"Contact @darkboxesAdmin if you need further help.",
                    parse_mode="md"
                )
                notified += 1
            except Exception:
                pass
        await event.edit(
            f"✅ **PASSWORD RESET SUCCESSFUL**\n\n"
            f"🆔 Account: `{account_id_target.upper()}`\n"
            f"🔐 New temp password: `{temp_pass}`\n"
            f"📲 Notified {notified}/{len(linked_ids)} linked TG account(s)\n\n"
            f"Share this password with the user via a secure channel.",
            buttons=[[Button.inline("« Admin Panel", "admin_panel")]],
            parse_mode="md"
        )

    async def show_user_management(self, event):
        """Show user management panel"""
        management_text = (
            "👥 **USER MANAGEMENT**\n"
            "═══════════════════════\n\n"
            "📋 **Available Actions:**\n"
            "• View all users with pagination\n"
            "• View top users by searches\n"
            "• View referral statistics\n"
            "• Search for specific users\n"
            "• View user details\n\n"
            "Select an option below:"
        )
        
        await event.edit(management_text, buttons=OneLineKeyboard.user_management_panel(), parse_mode="md")
    
    async def show_top_users(self, event):
        """Show top users by searches"""
        try:
            top_users = await self.db.admin_db.get_top_users(15)
            
            top_text = "🏆 **TOP USERS BY SEARCHES**\n"
            top_text += "═══════════════════════\n\n"
            
            for i, user in enumerate(top_users, 1):
                username = f"@{user['username']}" if user.get('username') else "No username"
                sub_status = user.get('subscription', 'None')
                
                top_text += (
                    f"{i}. **{user['first_name']}**\n"
                    f"   ├─ {username}\n"
                    f"   ├─ ID: `{user['user_id']}`\n"
                    f"   ├─ Searches: {user['total_searches']}\n"
                    f"   ├─ Credits: {user.get('searches_remaining', 0)}\n"
                    f"   ├─ Subscription: {sub_status}\n"
                    f"   └─ Last: {user.get('last_search', '')[:10]}\n\n"
                )
            
            await event.edit(top_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing top users: {e}")
            await event.edit("❌ Error loading top users", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_referral_stats(self, event):
        """Show referral statistics"""
        try:
            referral_stats = await self.db.admin_db.get_referral_stats()
            
            ref_text = "📊 **REFERRAL STATISTICS**\n"
            ref_text += "═══════════════════════\n\n"
            
            ref_text += f"📈 **Total Referrals:** {referral_stats['total_referrals']}\n\n"
            
            if referral_stats['top_referrers']:
                ref_text += "🏆 **TOP REFERRERS**\n"
                for i, user in enumerate(referral_stats['top_referrers'][:10], 1):
                    username = f"@{user['username']}" if user.get('username') else "No username"
                    ref_text += (
                        f"{i}. **{user['first_name']}**\n"
                        f"   ├─ {username}\n"
                        f"   ├─ Referrals: {user['referrals']}\n"
                        f"   ├─ Code: `{user.get('referral_code', 'N/A')}`\n"
                        f"   └─ Credits: {user.get('referral_credits', 0)}\n\n"
                    )
            else:
                ref_text += "No referrals yet.\n"
            
            await event.edit(ref_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing referral stats: {e}")
            await event.edit("❌ Error loading referral statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_analytics_panel(self, event):
        """Show analytics panel"""
        analytics_text = (
            "📈 **SEARCH ANALYTICS**\n"
            "═══════════════════════\n\n"
            "📊 **Available Reports:**\n"
            "• Command usage statistics\n"
            "• Daily activity graphs\n"
            "• Most used commands\n"
            "• User activity patterns\n\n"
            "Select an option below:"
        )
        
        await event.edit(analytics_text, buttons=OneLineKeyboard.analytics_panel(), parse_mode="md")
    
    async def show_command_stats(self, event):
        """Show command usage statistics"""
        try:
            command_stats = await self.db.admin_db.get_command_stats()
            
            stats_text = "🔍 **COMMAND USAGE STATISTICS**\n"
            stats_text += "═══════════════════════\n\n"
            
            # All-time stats
            stats_text += "📊 **ALL-TIME STATS**\n"
            total_searches = sum(cmd['count'] for cmd in command_stats['all_time'])
            stats_text += f"Total Searches: {total_searches}\n\n"
            
            for cmd in command_stats['all_time'][:10]:
                cmd_name = SEARCH_COMMANDS.get(cmd['command'], {}).get('name', cmd['command'])
                percentage = (cmd['count'] / total_searches * 100) if total_searches > 0 else 0
                stats_text += (
                    f"• **{cmd_name}**\n"
                    f"  ├─ Searches: {cmd['count']}\n"
                    f"  ├─ Unique Users: {cmd['unique_users']}\n"
                    f"  └─ Usage: {percentage:.1f}%\n\n"
                )
            
            # Today's stats
            if command_stats['today']:
                stats_text += "📅 **TODAY'S STATS**\n"
                for cmd in command_stats['today'][:5]:
                    cmd_name = SEARCH_COMMANDS.get(cmd['_id'], {}).get('name', cmd['_id'])
                    stats_text += f"• {cmd_name}: {cmd['count']}\n"
            
            await event.edit(stats_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing command stats: {e}")
            await event.edit("❌ Error loading command statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_top_commands(self, event):
        """Show most used commands"""
        try:
            command_stats = await self.db.admin_db.get_command_stats()
            
            top_text = "🎯 **MOST USED COMMANDS**\n"
            top_text += "═══════════════════════\n\n"
            
            # Prepare data for bar chart
            commands = []
            counts = []
            
            for cmd in command_stats['all_time'][:8]:
                cmd_name = SEARCH_COMMANDS.get(cmd['command'], {}).get('name', cmd['command'])
                commands.append(cmd_name[:15])  # Truncate long names
                counts.append(cmd['count'])
            
            # Create bar chart
            plt.figure(figsize=(10, 6))
            bars = plt.bar(commands, counts, color='skyblue')
            plt.title('Most Used Commands', fontsize=14, fontweight='bold')
            plt.xlabel('Commands', fontsize=12)
            plt.ylabel('Number of Searches', fontsize=12)
            plt.xticks(rotation=45, ha='right')
            
            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                plt.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}', ha='center', va='bottom')
            
            plt.tight_layout()
            
            # Save to bytes
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            # Send image
            await event.delete()
            await self.bot.send_file(
                event.chat_id,
                buf,
                caption="📊 **Command Usage Visualization**",
                buttons=OneLineKeyboard.back_to_admin()
            )
            
        except Exception as e:
            logger.error(f"Error generating command chart: {e}")
            await event.edit("❌ Error generating visualization", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_user_activity(self, event):
        """Show user activity patterns"""
        try:
            # Get activity data for last 7 days
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            
            pipeline = [
                {"$match": {"timestamp": {"$gte": seven_days_ago.isoformat()}}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$toDate": "$timestamp"}}},
                    "count": {"$sum": 1},
                    "unique_users": {"$addToSet": "$user_id"}
                }},
                {"$project": {
                    "date": "$_id",
                    "searches": "$count",
                    "unique_users": {"$size": "$unique_users"}
                }},
                {"$sort": {"date": 1}}
            ]
            
            activity_data = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.search_logs.aggregate(pipeline))
            )
            
            if not activity_data:
                await event.edit("📊 No activity data available for the last 7 days.", 
                               buttons=OneLineKeyboard.back_to_admin())
                return
            
            # Create visualization
            dates = [data['date'][5:] for data in activity_data]  # Remove year
            searches = [data['searches'] for data in activity_data]
            users = [data['unique_users'] for data in activity_data]
            
            plt.figure(figsize=(12, 6))
            
            x = range(len(dates))
            width = 0.35
            
            plt.bar([i - width/2 for i in x], searches, width, label='Searches', color='skyblue')
            plt.bar([i + width/2 for i in x], users, width, label='Unique Users', color='lightcoral')
            
            plt.title('User Activity (Last 7 Days)', fontsize=14, fontweight='bold')
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Count', fontsize=12)
            plt.xticks(x, dates, rotation=45)
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            # Add value labels
            for i, (s, u) in enumerate(zip(searches, users)):
                plt.text(i - width/2, s + max(searches)*0.01, str(s), 
                        ha='center', va='bottom', fontsize=8)
                plt.text(i + width/2, u + max(users)*0.01, str(u), 
                        ha='center', va='bottom', fontsize=8)
            
            # Save to bytes
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            # Calculate totals
            total_searches = sum(searches)
            total_users = sum(users)
            avg_searches = total_searches / len(activity_data)
            
            caption = (
                f"📊 **User Activity Analysis**\n\n"
                f"📈 **Last 7 Days Summary:**\n"
                f"├─ Total Searches: {total_searches}\n"
                f"├─ Total Unique Users: {total_users}\n"
                f"├─ Average Daily Searches: {avg_searches:.1f}\n"
                f"└─ Peak Day: {dates[searches.index(max(searches))]} ({max(searches)} searches)"
            )
            
            # Send image
            await event.delete()
            await self.bot.send_file(
                event.chat_id,
                buf,
                caption=caption,
                buttons=OneLineKeyboard.back_to_admin()
            )
            
        except Exception as e:
            logger.error(f"Error generating activity chart: {e}")
            await event.edit("❌ Error generating activity visualization", 
                           buttons=OneLineKeyboard.back_to_admin())
    
    async def generate_daily_graph(self, event):
        """Generate daily activity graph"""
        try:
            # Get daily stats for last 30 days
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            
            pipeline = [
                {"$match": {"timestamp": {"$gte": thirty_days_ago.isoformat()}}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$toDate": "$timestamp"}}},
                    "searches": {"$sum": 1},
                    "users": {"$addToSet": "$user_id"}
                }},
                {"$project": {
                    "date": "$_id",
                    "searches": 1,
                    "users": {"$size": "$users"}
                }},
                {"$sort": {"date": 1}}
            ]
            
            daily_data = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.search_logs.aggregate(pipeline))
            )
            
            if not daily_data:
                await event.edit("📊 No activity data available.", 
                               buttons=OneLineKeyboard.back_to_admin())
                return
            
            # Prepare data
            dates = [data['date'][5:] for data in daily_data]  # Remove year
            searches = [data['searches'] for data in daily_data]
            
            # Create line chart
            plt.figure(figsize=(14, 7))
            plt.plot(dates, searches, marker='o', linewidth=2, markersize=6, color='royalblue')
            plt.fill_between(dates, searches, alpha=0.3, color='skyblue')
            
            plt.title('Daily Search Activity (Last 30 Days)', fontsize=16, fontweight='bold')
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Number of Searches', fontsize=12)
            plt.xticks(rotation=45, ha='right')
            plt.grid(True, alpha=0.3)
            
            # Highlight max point
            max_idx = searches.index(max(searches))
            plt.plot(dates[max_idx], searches[max_idx], 'ro', markersize=10)
            plt.annotate(f'Peak: {searches[max_idx]}', 
                        xy=(dates[max_idx], searches[max_idx]),
                        xytext=(10, 10), textcoords='offset points',
                        fontsize=10, color='red', fontweight='bold')
            
            plt.tight_layout()
            
            # Calculate statistics
            total_searches = sum(searches)
            avg_searches = total_searches / len(searches)
            growth = ((searches[-1] - searches[0]) / searches[0] * 100) if searches[0] > 0 else 0
            
            # Save to bytes
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            caption = (
                f"📈 **Daily Activity Analysis**\n\n"
                f"📊 **Statistics (Last 30 Days):**\n"
                f"├─ Total Searches: {total_searches}\n"
                f"├─ Average Daily: {avg_searches:.1f}\n"
                f"├─ Peak Activity: {searches[max_idx]} searches\n"
                f"└─ Growth Rate: {growth:+.1f}%\n\n"
                f"📅 **Trend Analysis:**\n"
            )
            
            if growth > 0:
                caption += "📈 Positive growth trend detected\n"
            else:
                caption += "📉 Negative growth trend detected\n"
            
            # Send image
            await event.delete()
            await self.bot.send_file(
                event.chat_id,
                buf,
                caption=caption,
                buttons=OneLineKeyboard.back_to_admin()
            )
            
        except Exception as e:
            logger.error(f"Error generating daily graph: {e}")
            await event.edit("❌ Error generating daily graph", 
                           buttons=OneLineKeyboard.back_to_admin())
    
    async def show_payment_panel(self, event):
        """Show payment management panel"""
        payment_text = (
            "💰 **PAYMENT MANAGEMENT**\n"
            "═══════════════════════\n\n"
            "📊 **Available Reports:**\n"
            "• Today's revenue\n"
            "• Revenue graphs\n"
            "• Total revenue\n"
            "• Payment history\n\n"
            "Select an option below:"
        )
        
        await event.edit(payment_text, buttons=OneLineKeyboard.payment_panel(), parse_mode="md")
    
    async def show_today_payments(self, event):
        """Show today's payment statistics"""
        try:
            today_stats = await self.db.admin_db.get_today_stats()
            payment_stats = await self.db.admin_db.get_payment_stats()
            
            # Get today's payments
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            today_payments = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.payments.find({
                    "timestamp": {"$gte": today.isoformat()},
                    "status": "completed"
                }).sort("timestamp", -1).limit(10))
            )
            
            payment_text = "💰 **TODAY'S PAYMENTS**\n"
            payment_text += "═══════════════════════\n\n"
            
            payment_text += f"📊 **Summary**\n"
            payment_text += f"├─ Total Revenue: ₹{today_stats['total_payments']}\n"
            payment_text += f"├─ Number of Payments: {today_stats['payment_count']}\n"
            payment_text += f"└─ Average Payment: ₹{today_stats['total_payments']/today_stats['payment_count']:.2f}\n\n"
            
            if today_payments:
                payment_text += "📋 **Recent Payments**\n"
                for i, payment in enumerate(today_payments[:5], 1):
                    plan = SUBSCRIPTION_PLANS.get(payment.get('plan_id', ''), {})
                    plan_name = plan.get('name', payment.get('plan_id', 'N/A'))
                    time_str = payment.get('timestamp', '')[:16]
                    
                    payment_text += (
                        f"{i}. **₹{payment.get('amount', 0)}**\n"
                        f"   ├─ Plan: {plan_name}\n"
                        f"   ├─ User: `{payment.get('user_id', 'N/A')}`\n"
                        f"   └─ Time: {time_str}\n\n"
                    )
            else:
                payment_text += "No payments today.\n"
            
            await event.edit(payment_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing today payments: {e}")
            await event.edit("❌ Error loading payment statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_total_revenue(self, event):
        """Show total revenue statistics"""
        try:
            payment_stats = await self.db.admin_db.get_payment_stats()
            
            revenue_text = "💰 **TOTAL REVENUE**\n"
            revenue_text += "═══════════════════════\n\n"
            
            revenue_text += f"📊 **Overall Statistics**\n"
            revenue_text += f"├─ Total Revenue: ₹{payment_stats['total_revenue']}\n"
            revenue_text += f"├─ Daily Average: ₹{payment_stats['total_revenue']/30:.2f}\n"
            revenue_text += f"└─ Projected Monthly: ₹{payment_stats['total_revenue']:.2f}\n\n"
            
            if payment_stats['daily_stats']:
                revenue_text += "📅 **Last 30 Days Revenue**\n"
                total_last_30 = sum(day['total_amount'] for day in payment_stats['daily_stats'])
                avg_last_30 = total_last_30 / len(payment_stats['daily_stats'])
                
                revenue_text += f"├─ Total (30 days): ₹{total_last_30}\n"
                revenue_text += f"├─ Daily Average: ₹{avg_last_30:.2f}\n"
                revenue_text += f"└─ Growth Potential: ₹{avg_last_30 * 30:.2f}/month\n\n"
                
                revenue_text += "📈 **Top 5 Revenue Days**\n"
                top_days = sorted(payment_stats['daily_stats'], key=lambda x: x['total_amount'], reverse=True)[:5]
                for i, day in enumerate(top_days, 1):
                    revenue_text += f"{i}. {day['_id']}: ₹{day['total_amount']} ({day['count']} payments)\n"
            
            await event.edit(revenue_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing total revenue: {e}")
            await event.edit("❌ Error loading revenue statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def generate_revenue_graph(self, event):
        """Generate revenue graph"""
        try:
            payment_stats = await self.db.admin_db.get_payment_stats()
            
            if not payment_stats['daily_stats']:
                await event.edit("💰 No revenue data available.", 
                               buttons=OneLineKeyboard.back_to_admin())
                return
            
            # Prepare data
            dates = [day['_id'][5:] for day in payment_stats['daily_stats']]  # Remove year
            amounts = [day['total_amount'] for day in payment_stats['daily_stats']]
            counts = [day['count'] for day in payment_stats['daily_stats']]
            
            # Create figure with two subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
            
            # Revenue line chart
            ax1.plot(dates, amounts, marker='o', linewidth=2, markersize=6, color='green')
            ax1.fill_between(dates, amounts, alpha=0.3, color='lightgreen')
            ax1.set_title('Daily Revenue (Last 30 Days)', fontsize=14, fontweight='bold')
            ax1.set_ylabel('Revenue (₹)', fontsize=12)
            ax1.grid(True, alpha=0.3)
            ax1.tick_params(axis='x', rotation=45)
            
            # Add value labels for peaks
            for i, (date, amount) in enumerate(zip(dates, amounts)):
                if amount == max(amounts):
                    ax1.annotate(f'₹{amount}', xy=(date, amount),
                                xytext=(0, 10), textcoords='offset points',
                                fontsize=10, color='red', fontweight='bold',
                                ha='center')
            
            # Payment count bar chart
            bars = ax2.bar(dates, counts, color='orange', alpha=0.7)
            ax2.set_title('Daily Payment Count', fontsize=14, fontweight='bold')
            ax2.set_xlabel('Date', fontsize=12)
            ax2.set_ylabel('Number of Payments', fontsize=12)
            ax2.grid(True, alpha=0.3)
            ax2.tick_params(axis='x', rotation=45)
            
            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax2.text(bar.get_x() + bar.get_width()/2., height,
                            f'{int(height)}', ha='center', va='bottom', fontsize=9)
            
            plt.tight_layout()
            
            # Calculate statistics
            total_revenue = sum(amounts)
            total_payments = sum(counts)
            avg_revenue = total_revenue / len(amounts)
            avg_payments = total_payments / len(counts)
            
            # Save to bytes
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            caption = (
                f"📊 **Revenue Analysis**\n\n"
                f"💰 **Last 30 Days Summary:**\n"
                f"├─ Total Revenue: ₹{total_revenue}\n"
                f"├─ Total Payments: {total_payments}\n"
                f"├─ Average Daily Revenue: ₹{avg_revenue:.2f}\n"
                f"├─ Average Daily Payments: {avg_payments:.1f}\n"
                f"└─ Average Payment Value: ₹{total_revenue/total_payments:.2f}\n\n"
                f"📈 **Insights:**\n"
            )
            
            if avg_revenue > 1000:
                caption += "• 📈 Strong revenue performance\n"
            elif avg_revenue > 500:
                caption += "• 📊 Moderate revenue growth\n"
            else:
                caption += "• ⚠️ Revenue needs improvement\n"
            
            # Send image
            await event.delete()
            await self.bot.send_file(
                event.chat_id,
                buf,
                caption=caption,
                buttons=OneLineKeyboard.back_to_admin()
            )
            
        except Exception as e:
            logger.error(f"Error generating revenue graph: {e}")
            await event.edit("❌ Error generating revenue visualization", 
                           buttons=OneLineKeyboard.back_to_admin())
    
    async def ask_for_user_search(self, event):
        """Ask for user search query"""
        await event.edit(
            "🔍 **SEARCH USER**\n\n"
            "Enter search criteria:\n"
            "• User ID (numeric)\n"
            "• Username (with or without @)\n"
            "• First name\n\n"
            "Type your search query:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        # Set state for message handler
        user_states[event.sender_id] = {"action": "admin_search_user"}
    
    async def ask_for_broadcast(self, event):
        """Ask for broadcast message"""
        await event.edit(
            "📢 **BROADCAST MESSAGE**\n\n"
            "Enter your broadcast message:\n"
            "(Supports Markdown formatting)\n\n"
            "Type your message:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_broadcast"}
    
    async def ask_for_ban_user(self, event):
        """Ask for user ID to ban/unban"""
        await event.edit(
            "🚫 **BAN/UNBAN USER**\n\n"
            "Enter user ID to ban/unban:\n"
            "(Numeric user ID)\n\n"
            "Type the user ID:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_ban"}
    
    async def ask_for_admin_management(self, event):
        """Ask for user ID for admin management"""
        await event.edit(
            "👑 **ADMIN MANAGEMENT**\n\n"
            "Enter user ID to add/remove as admin:\n"
            "(Numeric user ID)\n\n"
            "Type the user ID:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_management"}
    
    async def ask_for_add_credits(self, event):
        """Ask for user identifier and credits to add"""
        plan_ids_list = "\n".join(
            f"  • `{k}` — {v['name']}"
            for k, v in SUBSCRIPTION_PLANS.items()
        )
        await event.edit(
            "🎯 **ADD CREDITS TO USER**\n\n"
            "Format: `identifier amount`\n\n"
            "**Identifier can be:**\n"
            "• Telegram user ID: `123456789 50`\n"
            "• @username: `@johndoe 50`\n"
            "• Account ID: `DB1A2B3C4D 50`\n\n"
            "Type your command below:",
            buttons=OneLineKeyboard.back_to_admin(),
            parse_mode="md"
        )
        user_states[event.sender_id] = {"action": "admin_add_credits"}
    
    async def ask_for_give_credits_all(self, event):
        """Ask admin how many credits to give ALL users"""
        await event.edit(
            "💰 **GIVE CREDITS TO ALL USERS**\n\n"
            "⚠️ This will add credits to EVERY registered user.\n\n"
            "Enter the number of credits to add:\n"
            "(e.g. `5` to give 5 credits to everyone)\n\n"
            "Type the number:",
            buttons=OneLineKeyboard.back_to_admin(),
            parse_mode="md"
        )
        user_states[event.sender_id] = {"action": "admin_give_credits_all"}

    async def ask_for_take_credits_user(self, event):
        """Ask admin which user to take credits from"""
        await event.edit(
            "➖ **TAKE CREDITS FROM A USER**\n\n"
            "Format: `identifier amount`\n\n"
            "Examples:\n"
            "• `123456789 10`  — take 10 credits from user ID\n"
            "• `@username 5`   — take 5 credits from @username\n\n"
            "Credits floor at 0 — user will never go negative.\n\n"
            "Type your command:",
            buttons=OneLineKeyboard.back_to_admin(),
            parse_mode="md"
        )
        user_states[event.sender_id] = {"action": "admin_take_credits_user"}

    async def ask_for_take_credits_all(self, event):
        """Ask admin how many credits to remove from ALL users"""
        await event.edit(
            "🔥 **TAKE CREDITS FROM ALL USERS**\n\n"
            "⚠️ This will remove credits from EVERY registered user.\n"
            "Each user's credits floor at 0 (never go negative).\n\n"
            "Enter the number of credits to remove:\n"
            "(e.g. `3` to remove up to 3 credits from everyone)\n\n"
            "Type the number:",
            buttons=OneLineKeyboard.back_to_admin(),
            parse_mode="md"
        )
        user_states[event.sender_id] = {"action": "admin_take_credits_all"}

    async def show_group_cmd_mgmt(self, event):
        """Show group/bot management panel with command config per group"""
        try:
            text = "⚙️ **GROUPS & COMMANDS MANAGEMENT**\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            text += "Select a group to configure its commands:\n\n"
            for key, g in GROUP_PRIORITIES.items():
                status = "✅" if g.get("enabled") else "❌"
                entity = g.get("identifier", "?")
                text += f"{status} **{g['name']}** (`{key}`)\n└ ID/Username: `{entity}`\n\n"
            text += "\n📌 Tap a group button to set per-command commands or toggle enabled."
            buttons = []
            for key, g in GROUP_PRIORITIES.items():
                buttons.append([Button.inline(
                    f"{'✅' if g.get('enabled') else '❌'} {g['name'][:28]}",
                    f"admin_gcmd_group_{key}"
                )])
            text += "\n\n🔧 **Search Command Validity Types:**\n"
            for stype, cmd in SEARCH_COMMANDS.items():
                vtype = cmd.get("validity_type", "generic")
                text += f"• `{stype}` → `{vtype}`\n"
            buttons.append([Button.inline("🔄 Set Validity Types", "admin_gcmd_vtypes")])
            buttons.append([Button.inline("« Admin Panel", "admin_panel")])
            await event.edit(text, buttons=buttons, parse_mode="md")
        except Exception as e:
            logger.error(f"show_group_cmd_mgmt: {e}")
            await event.answer("❌ Error", alert=True)

    async def show_group_detail(self, event, group_key: str):
        """Show command config for a specific group"""
        try:
            g = GROUP_PRIORITIES.get(group_key)
            if not g:
                await event.answer("❌ Group not found", alert=True)
                return
            text = f"⚙️ **{g['name']}** — Command Config\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            text += f"🔑 Key: `{group_key}`\n"
            text += f"📡 Entity: `{g.get('identifier', '?')}`\n"
            text += f"{'✅ Enabled' if g.get('enabled') else '❌ Disabled'}\n\n"
            text += "**Per-command settings** (tap to change):\n\n"
            group_cmds = g.get("commands", {})
            buttons = []
            for stype in SEARCH_COMMANDS:
                current = group_cmds.get(stype, "")
                display = current if current else "(direct / no command)"
                text += f"• `{stype}`: `{display}`\n"
                buttons.append([Button.inline(
                    f"✏️ {stype}: {display[:22]}",
                    f"admin_gcmd_setcmd_{group_key}_{stype}"
                )])
            text += "\n💡 Empty command = send query directly without prefix."
            buttons.append([Button.inline("« Back", "admin_group_cmd_mgmt")])
            await event.edit(text, buttons=buttons, parse_mode="md")
        except Exception as e:
            logger.error(f"show_group_detail: {e}")
            await event.answer("❌ Error", alert=True)

    async def prompt_set_group_cmd(self, event, group_key: str, search_type: str):
        """Prompt admin to type new command for a group+search_type"""
        try:
            g = GROUP_PRIORITIES.get(group_key, {})
            current = g.get("commands", {}).get(search_type, "")
            await event.edit(
                f"✏️ **Set command for `{group_key}` → `{search_type}`**\n\n"
                f"Current: `{current if current else '(none — direct query)'}`\n\n"
                "Type the new command (e.g. `/num`, `/familyinfo`) or send a single dash `-` to set **no command** (direct query mode):",
                buttons=[[Button.inline("❌ Cancel", f"admin_gcmd_group_{group_key}")]],
                parse_mode="md"
            )
            user_states[event.sender_id] = {
                "action": "admin_set_group_cmd",
                "group_key": group_key,
                "search_type": search_type,
            }
        except Exception as e:
            logger.error(f"prompt_set_group_cmd: {e}")

    async def prompt_set_validity_type(self, event, search_type: str):
        """Prompt admin to choose a validity type for a command"""
        try:
            current = SEARCH_COMMANDS.get(search_type, {}).get("validity_type", "generic")
            text = (
                f"🔧 **Validity Type for `{search_type}`**\n\n"
                f"Current: `{current}`\n\n"
                "Select new validity type:\n"
            )
            for vkey, vinfo in VALIDITY_TYPES.items():
                text += f"• `{vkey}` — {vinfo['label']}\n"
            buttons = [[Button.inline(f"{'✅ ' if vkey == current else ''}{vkey}", f"admin_setvtype_{search_type}_{vkey}")]
                       for vkey in VALIDITY_TYPES]
            buttons.append([Button.inline("« Back", "admin_group_cmd_mgmt")])
            await event.edit(text, buttons=buttons, parse_mode="md")
        except Exception as e:
            logger.error(f"prompt_set_validity_type: {e}")

    async def show_free_user_config(self, event):
        """Show free-user restriction panel"""
        try:
            allowed_groups  = FREE_USER_CONFIG.get("allowed_groups", [])
            allowed_commands = FREE_USER_CONFIG.get("allowed_commands", [])

            text = "🆓 **FREE USER CONFIGURATION**\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            text += "**Groups allowed for free users:**\n"
            text += "(Empty = all groups; toggle to restrict)\n\n"
            group_buttons = []
            for key in ["primary", "secondary", "tertiary"]:
                g = GROUP_PRIORITIES.get(key)
                if not g:
                    continue
                active = key in allowed_groups if allowed_groups else True
                text += f"{'✅' if active else '❌'} `{key}` — {g['name']}\n"
                group_buttons.append([Button.inline(
                    f"{'✅' if active else '❌'} {g['name'][:28]}",
                    f"admin_freegroup_toggle_{key}"
                )])

            text += "\n**Commands allowed for free users:**\n"
            text += "(Empty = all commands; toggle to restrict)\n\n"
            cmd_buttons = []
            for stype in SEARCH_COMMANDS:
                active = stype in allowed_commands if allowed_commands else True
                text += f"{'✅' if active else '❌'} `{stype}`\n"
                cmd_buttons.append([Button.inline(
                    f"{'✅' if active else '❌'} {stype}",
                    f"admin_freecmd_toggle_{stype}"
                )])

            buttons = group_buttons + cmd_buttons + [[Button.inline("« Admin Panel", "admin_panel")]]
            await event.edit(text, buttons=buttons, parse_mode="md")
        except Exception as e:
            logger.error(f"show_free_user_config: {e}")
            await event.answer("❌ Error", alert=True)

    async def toggle_free_group(self, event, group_key: str):
        """Toggle whether a group is allowed for free users"""
        try:
            allowed = list(FREE_USER_CONFIG.get("allowed_groups", []))
            if not allowed:
                # Currently "all allowed" — toggling means restricting to all EXCEPT this one
                allowed = [k for k in ["primary", "secondary", "tertiary"] if k != group_key]
            else:
                if group_key in allowed:
                    allowed.remove(group_key)
                else:
                    allowed.append(group_key)
            FREE_USER_CONFIG["allowed_groups"] = allowed
            # Persist to DB
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: db_manager.db.bot_config.update_one(
                    {"_id": "free_user_config"},
                    {"$set": {"allowed_groups": allowed}},
                    upsert=True
                )
            )
            await self.show_free_user_config(event)
        except Exception as e:
            logger.error(f"toggle_free_group: {e}")

    async def toggle_free_command(self, event, cmd_key: str):
        """Toggle whether a command is allowed for free users"""
        try:
            allowed = list(FREE_USER_CONFIG.get("allowed_commands", []))
            if not allowed:
                allowed = [k for k in SEARCH_COMMANDS if k != cmd_key]
            else:
                if cmd_key in allowed:
                    allowed.remove(cmd_key)
                else:
                    allowed.append(cmd_key)
            FREE_USER_CONFIG["allowed_commands"] = allowed
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: db_manager.db.bot_config.update_one(
                    {"_id": "free_user_config"},
                    {"$set": {"allowed_commands": allowed}},
                    upsert=True
                )
            )
            await self.show_free_user_config(event)
        except Exception as e:
            logger.error(f"toggle_free_command: {e}")

    async def show_bot_settings(self, event):
        """Show bot settings"""
        settings_text = (
            "⚙️ **BOT SETTINGS**\n"
            "═══════════════════════\n\n"
            "📊 **Current Configuration:**\n"
            f"├─ Bot: @{bot_info.username}\n"
            f"├─ Admin: {config.ADMIN_USER_ID}\n"
            f"├─ New User Credits: {config.NEW_USER_CREDITS}\n"
            f"├─ Referral Reward: {config.REFERRAL_REWARD}\n"
            f"├─ Max File Size: {config.MAX_FILE_SIZE_MB}MB\n"
            f"├─ Group Timeout: {config.GROUP_TIMEOUT}s\n"
            f"└─ UPI ID: {config.UPI_ID}\n\n"
            "🔄 **Available Actions:**\n"
            "• Adjust user credits\n"
            "• Modify referral rewards\n"
            "• Update configuration\n"
            "• Restart services\n\n"
            "⚠️ **Note:** Some settings require bot restart."
        )
        
        await event.edit(settings_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
    
    async def export_data(self, event):
        """Export bot data"""
        try:
            await event.edit("📥 **EXPORTING DATA...**\n\nThis may take a moment...")
            
            # Get all data
            users = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.users.find({}, {
                    "user_id": 1, "username": 1, "first_name": 1, 
                    "joined_at": 1, "total_searches": 1, "searches_remaining": 1,
                    "subscription": 1, "referrals": 1, "is_banned": 1
                }))
            )
            
            payments = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.payments.find({}, {
                    "user_id": 1, "amount": 1, "plan_id": 1, 
                    "timestamp": 1, "status": 1
                }))
            )
            
            searches = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.search_logs.find({}, {
                    "user_id": 1, "search_type": 1, "query": 1,
                    "timestamp": 1, "success": 1, "credits_used": 1
                }).limit(10000))  # Limit to prevent memory issues
            )
            
            # Create CSV data
            import csv
            from io import StringIO
            
            # Users CSV
            users_csv = StringIO()
            users_writer = csv.writer(users_csv)
            users_writer.writerow(['User ID', 'Username', 'Name', 'Joined', 'Searches', 'Credits', 'Subscription', 'Referrals', 'Banned'])
            for user in users:
                users_writer.writerow([
                    user.get('user_id', ''),
                    user.get('username', ''),
                    user.get('first_name', ''),
                    user.get('joined_at', '')[:10],
                    user.get('total_searches', 0),
                    user.get('searches_remaining', 0),
                    user.get('subscription', 'None'),
                    user.get('referrals', 0),
                    'Yes' if user.get('is_banned') else 'No'
                ])
            
            users_csv.seek(0)
            
            # Payments CSV
            payments_csv = StringIO()
            payments_writer = csv.writer(payments_csv)
            payments_writer.writerow(['User ID', 'Amount', 'Plan', 'Date', 'Status'])
            for payment in payments:
                payments_writer.writerow([
                    payment.get('user_id', ''),
                    payment.get('amount', 0),
                    payment.get('plan_id', ''),
                    payment.get('timestamp', '')[:10],
                    payment.get('status', '')
                ])
            
            payments_csv.seek(0)
            
            # Prepare message
            export_text = (
                "📊 **DATA EXPORT COMPLETE**\n\n"
                f"✅ **Exported Data:**\n"
                f"├─ Users: {len(users)} records\n"
                f"├─ Payments: {len(payments)} records\n"
                f"└─ Searches: {len(searches)} records\n\n"
                "📁 **Files are ready for download.**\n"
                "Use the buttons below to download:"
            )
            
            buttons = [
                [Button.inline("📥 Download Users CSV", "export_users")],
                [Button.inline("📥 Download Payments CSV", "export_payments")],
                [Button.inline("📥 Download Searches CSV", "export_searches")],
                [Button.inline("« Admin Panel", "admin_panel")]
            ]
            
            # Store export data temporarily
            export_data_storage[event.sender_id] = {
                "users": users_csv.getvalue(),
                "payments": payments_csv.getvalue(),
                "timestamp": datetime.now().isoformat()
            }
            
            await event.edit(export_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error exporting data: {e}")
            await event.edit("❌ Error exporting data", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_user_detail(self, event, user_id: int):
        """Show detailed user information"""
        try:
            user_stats = await self.db.admin_db.get_user_stats(user_id)
            
            if not user_stats.get('user_info'):
                await event.answer("❌ User not found", alert=True)
                return
            
            user = user_stats['user_info']
            
            detail_text = f"👤 **USER DETAILS**\n"
            detail_text += "═══════════════════════\n\n"
            
            detail_text += f"📋 **Basic Information**\n"
            detail_text += f"├─ Name: {user.get('first_name', 'N/A')}\n"
            detail_text += f"├─ Username: @{user.get('username', 'N/A')}\n"
            detail_text += f"├─ User ID: `{user_id}`\n"
            detail_text += f"├─ Joined: {user.get('joined_at', 'N/A')[:10]}\n"
            detail_text += f"├─ Last Seen: {user.get('last_seen', 'N/A')[:16]}\n"
            detail_text += f"├─ Credits: {user.get('searches_remaining', 0)}\n"
            detail_text += f"├─ Total Searches: {user_stats['total_searches']}\n"
            detail_text += f"├─ Referrals: {user_stats['referrals']}\n"
            detail_text += f"└─ Banned: {'Yes' if user.get('is_banned') else 'No'}\n\n"
            
            # Subscription info
            if user.get('subscription'):
                expiry = user.get('subscription_expiry', '')
                if expiry:
                    expiry_date = datetime.fromisoformat(expiry)
                    days_left = (expiry_date - datetime.now(timezone.utc)).days
                    detail_text += f"💎 **Subscription**\n"
                    detail_text += f"├─ Plan: {user['subscription']}\n"
                    detail_text += f"└─ Expires in: {days_left} days\n\n"
            
            # Recent searches
            if user_stats.get('last_searches'):
                detail_text += "🔍 **Recent Searches**\n"
                for search in user_stats['last_searches'][:5]:
                    search_type = search.get('search_type', 'N/A')
                    cmd_name = SEARCH_COMMANDS.get(search_type, {}).get('name', search_type)
                    time_str = search.get('timestamp', '')[:16]
                    success = "✅" if search.get('success') else "❌"
                    
                    detail_text += f"{success} {cmd_name}\n"
                    detail_text += f"   ├─ Query: `{search.get('query', 'N/A')}`\n"
                    detail_text += f"   └─ Time: {time_str}\n\n"
            
            # Action buttons
            buttons = []
            if user.get('is_banned'):
                buttons.append([Button.inline("🔓 Unban User", f"confirm_unban_{user_id}")])
            else:
                buttons.append([Button.inline("🚫 Ban User", f"confirm_ban_{user_id}")])
            
            if user.get('is_admin'):
                buttons.append([Button.inline("👑 Remove Admin", f"confirm_remove_admin_{user_id}")])
            else:
                buttons.append([Button.inline("👑 Add Admin", f"confirm_add_admin_{user_id}")])
            
            buttons.append([Button.inline("🎯 Add Credits", f"admin_add_credits_user_{user_id}")])
            buttons.append([Button.inline("💎 Give Subscription", f"admin_give_sub_{user_id}")])
            buttons.append([Button.inline("« User Management", "admin_users")])
            
            await event.edit(detail_text, buttons=buttons, parse_mode="md")
            
        except Exception as e:
            logger.error(f"Error showing user detail: {e}")
            await event.answer("❌ Error loading user details", alert=True)
    
    async def confirm_ban_user(self, event, user_id: int):
        """Confirm ban user"""
        try:
            success = await self.db.ban_user(user_id, "Admin action")
            if success:
                # Remove from admin cache if they were admin
                if user_id in self.admin_users:
                    self.admin_users.remove(user_id)
                
                await event.answer("✅ User banned successfully", alert=True)
                await self.show_admin_panel(event)
            else:
                await event.answer("❌ Failed to ban user", alert=True)
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            await event.answer("❌ Error banning user", alert=True)
    
    async def confirm_unban_user(self, event, user_id: int):
        """Confirm unban user"""
        try:
            success = await self.db.unban_user(user_id)
            if success:
                await event.answer("✅ User unbanned successfully", alert=True)
                await self.show_admin_panel(event)
            else:
                await event.answer("❌ Failed to unban user", alert=True)
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            await event.answer("❌ Error unbanning user", alert=True)
    
    async def confirm_add_admin(self, event, user_id: int):
        """Confirm add admin"""
        try:
            success = await self.db.add_admin(user_id)
            if success:
                self.admin_users.add(user_id)
                await event.answer("✅ User added as admin", alert=True)
                await self.show_admin_panel(event)
            else:
                await event.answer("❌ Failed to add admin", alert=True)
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            await event.answer("❌ Error adding admin", alert=True)
    
    async def confirm_remove_admin(self, event, user_id: int):
        """Confirm remove admin"""
        try:
            success = await self.db.remove_admin(user_id)
            if success:
                self.admin_users.remove(user_id)
                await event.answer("✅ Admin privileges removed", alert=True)
                await self.show_admin_panel(event)
            else:
                await event.answer("❌ Failed to remove admin", alert=True)
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            await event.answer("❌ Error removing admin", alert=True)
    
    async def show_give_sub_for_user(self, event, user_id: int):
        """Show subscription options for a specific user"""
        try:
            user = await self.db.get_user(user_id)
            if not user:
                await event.answer("❌ User not found", alert=True)
                return
            
            text = (
                f"💎 **GIVE SUBSCRIPTION**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')} (`{user_id}`)\n"
                f"Current plan: {user.get('subscription', 'None')}\n\n"
                f"Select a plan to grant:"
            )
            
            buttons = [
                [Button.inline("⚡ 5 Credits (₹200)", f"grant_sub_{user_id}_credits_5")],
                [Button.inline("📱 Unlimited NUM Monthly (₹300)", f"grant_sub_{user_id}_sub_num_monthly")],
                [Button.inline("💎 Unlimited ALL Monthly (₹499)", f"grant_sub_{user_id}_sub_all_monthly")],
                [Button.inline("« Back", f"user_detail_{user_id}")]
            ]
            
            await event.edit(text, buttons=buttons, parse_mode="md")
        except Exception as e:
            logger.error(f"Error in show_give_sub_for_user: {e}")
            await event.answer("❌ Error", alert=True)

    async def ask_for_broadcast_media(self, event):
        """Ask admin to choose media broadcast target"""
        buttons = [
            [Button.inline("👥 All Users", "broadcast_media_all")],
            [Button.inline("🎯 Selected Users (by ID)", "broadcast_media_selected")],
            [Button.inline("« Admin Panel", "admin_panel")]
        ]
        await event.edit(
            "🖼️ **MEDIA BROADCAST**\n\n"
            "Send a photo or video with caption to users.\n\n"
            "Choose target audience:",
            buttons=buttons,
            parse_mode="md"
        )

    async def show_broadcast_history(self, event):
        """Show broadcast history with seen counts"""
        try:
            broadcasts = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(db_manager.db.broadcasts.find(
                    {}, {"broadcast_id": 1, "caption": 1, "total_recipients": 1,
                         "sent_count": 1, "seen_by": 1, "timestamp": 1, "media_type": 1}
                ).sort("timestamp", -1).limit(10))
            )

            if not broadcasts:
                await event.edit(
                    "📋 **BROADCAST HISTORY**\n\nNo broadcasts sent yet.",
                    buttons=[[Button.inline("« Admin Panel", "admin_panel")]]
                )
                return

            hist_text = "📋 **BROADCAST HISTORY** (Last 10)\n═══════════════════════\n\n"
            buttons = []

            for bc in broadcasts:
                bc_id = bc.get("broadcast_id", "N/A")
                caption_raw = bc.get("caption", "N/A")
                caption = (caption_raw[:35] + "...") if len(caption_raw) > 35 else caption_raw
                sent = bc.get("sent_count", 0)
                seen = len(bc.get("seen_by", []))
                timestamp = bc.get("timestamp", "")[:16]
                media_type = bc.get("media_type", "text")

                hist_text += (
                    f"📡 **{bc_id}** [{media_type}]\n"
                    f"   ├─ {caption}\n"
                    f"   ├─ Sent: {sent} | Seen: {seen}\n"
                    f"   └─ {timestamp}\n\n"
                )
                is_deleted = bc.get("deleted", False)
            del_label = "✅ Deleted" if is_deleted else "🗑 Delete"
            buttons.append([
                Button.inline(f"👁 {bc_id} · {seen} seen", f"admin_broadcast_seen_{bc_id}"),
                Button.inline(del_label, f"del_broadcast_{bc_id}"),
            ])

            buttons.append([Button.inline("« Admin Panel", "admin_panel")])
            await event.edit(hist_text, buttons=buttons, parse_mode="md")

        except Exception as e:
            logger.error(f"Error showing broadcast history: {e}")
            await event.edit("❌ Error loading broadcast history", buttons=OneLineKeyboard.back_to_admin())

    async def show_broadcast_seen(self, event, broadcast_id: str):
        """Show who has seen a specific broadcast"""
        try:
            broadcast = await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.broadcasts.find_one({"broadcast_id": broadcast_id})
            )

            if not broadcast:
                await event.answer("❌ Broadcast not found", alert=True)
                return

            seen_by = broadcast.get("seen_by", [])
            sent_count = broadcast.get("sent_count", 0)
            seen_rate = f"{(len(seen_by)/sent_count*100):.1f}%" if sent_count > 0 else "N/A"

            seen_text = (
                f"👁️ **BROADCAST SEEN REPORT**\n\n"
                f"📡 ID: `{broadcast_id}`\n"
                f"📤 Total Sent: {sent_count}\n"
                f"👁️ Seen By: {len(seen_by)}\n"
                f"📊 Seen Rate: {seen_rate}\n\n"
            )

            if seen_by:
                seen_text += "**Users who have seen:**\n"
                for uid in seen_by[:25]:
                    seen_text += f"• `{uid}`\n"
                if len(seen_by) > 25:
                    seen_text += f"... and {len(seen_by)-25} more\n"
            else:
                seen_text += "_No users have seen this broadcast yet._"

            await event.edit(
                seen_text,
                buttons=[[Button.inline("« Broadcast History", "admin_broadcast_history")]],
                parse_mode="md"
            )

        except Exception as e:
            logger.error(f"Error showing broadcast seen: {e}")
            await event.answer("❌ Error loading seen report", alert=True)

    async def show_pending_payments(self, event):
        """Show all pending UTR/payment submissions awaiting admin approval"""
        try:
            pending = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(db_manager.db.pending_payments.find(
                    {"status": "pending"}
                ).sort("timestamp", -1).limit(20))
            )

            if not pending:
                await event.edit(
                    "💳 **PENDING PAYMENTS**\n\n✅ No pending payments! All clear.",
                    buttons=[[Button.inline("« Admin Panel", "admin_panel")]]
                )
                return

            text = f"💳 **PENDING PAYMENTS** ({len(pending)} awaiting)\n═══════════════════════\n\n"
            buttons = []

            for p in pending:
                pay_id = p.get("payment_id", "N/A")
                uid = p.get("user_id", "N/A")
                fname = p.get("first_name", "N/A")
                plan_name = p.get("plan_name", "N/A")
                amount = p.get("amount", 0)
                ts = p.get("timestamp", "")[:16]
                plan_id = p.get("plan_id", "basic")

                text += (
                    f"🔖 **{pay_id}**\n"
                    f"   ├─ {fname} (`{uid}`)\n"
                    f"   ├─ {plan_name} — ₹{amount}\n"
                    f"   └─ {ts}\n\n"
                )
                buttons.append([
                    Button.inline(f"✅ {pay_id}", f"approve_payment_{pay_id}_{uid}_{plan_id}"),
                    Button.inline("❌ Reject", f"reject_payment_{pay_id}_{uid}")
                ])

            buttons.append([Button.inline("« Admin Panel", "admin_panel")])
            await event.edit(text, buttons=buttons, parse_mode="md")

        except Exception as e:
            logger.error(f"Error showing pending payments: {e}")
            await event.edit("❌ Error loading pending payments", buttons=OneLineKeyboard.back_to_admin())

    async def ask_for_give_subscription(self, event):
        """Ask admin for user identifier and plan to give subscription"""
        plan_lines = "\n".join(
            f"  • `{k}` — {v['name']} (₹{v['price']})"
            for k, v in SUBSCRIPTION_PLANS.items()
        )
        await event.edit(
            "💎 **GIVE PLAN / SUBSCRIPTION**\n\n"
            "Format: `identifier plan_id`\n\n"
            "**Identifier can be:**\n"
            "• Telegram user ID: `123456789`\n"
            "• @username: `@johndoe`\n"
            "• Account ID: `DB1A2B3C4D`\n\n"
            "**Available plan IDs:**\n"
            f"{plan_lines}\n\n"
            "**Examples:**\n"
            "`123456789 credits_5`\n"
            "`@johndoe sub_num_monthly`\n"
            "`DB1A2B3C4D sub_all_monthly`",
            buttons=OneLineKeyboard.back_to_admin(),
            parse_mode="md"
        )
        user_states[event.sender_id] = {"action": "admin_give_subscription"}

    async def show_api_panel(self, event):
        """Show API admin panel"""
        await event.edit(
            "🔑 **API ADMIN PANEL**\n═══════════════════════\n\n"
            "Manage API keys and access for users.\n\n"
            "Select an option:",
            buttons=OneLineKeyboard.api_admin_panel(),
            parse_mode="md"
        )

    async def show_api_stats(self, event):
        """Show API statistics"""
        try:
            stats = await db_manager.api_db.get_api_stats()
            text = (
                f"📊 **API STATISTICS**\n═══════════════════════\n\n"
                f"🔑 Total Keys: {stats.get('total_keys', 0)}\n"
                f"✅ Active Keys: {stats.get('active_keys', 0)}\n"
                f"📡 Total Requests: {stats.get('total_requests', 0)}\n"
                f"📈 Requests Used: {stats.get('requests_used', 0)}\n"
            )
            await event.edit(text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing API stats: {e}")
            await event.edit("❌ Error loading API stats", buttons=OneLineKeyboard.back_to_admin())

    async def ask_for_api_user_management(self, event):
        """Ask for user ID for API management"""
        await event.edit(
            "🔑 **API USER MANAGEMENT**\n\n"
            "Enter user ID to manage their API keys:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        user_states[event.sender_id] = {"action": "admin_api_user"}

    async def show_api_analytics(self, event):
        """Show API analytics"""
        try:
            keys = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(db_manager.db.api_keys.find({}).limit(20))
            )
            text = f"📈 **API ANALYTICS**\n═══════════════════════\n\n"
            if not keys:
                text += "No API keys found."
            else:
                for k in keys:
                    uid = k.get("user_id", "N/A")
                    plan = k.get("plan_id", "N/A")
                    used = k.get("requests_used", 0)
                    active = "✅" if k.get("is_active") else "❌"
                    text += f"{active} User `{uid}` | {plan} | {used} calls\n"
            await event.edit(text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error in API analytics: {e}")
            await event.edit("❌ Error", buttons=OneLineKeyboard.back_to_admin())

    async def ask_for_api_revoke(self, event):
        """Ask for API key to revoke"""
        await event.edit(
            "🔑 **REVOKE API KEY**\n\n"
            "Enter the API key to revoke (first 16 chars are enough):",
            buttons=OneLineKeyboard.back_to_admin()
        )
        user_states[event.sender_id] = {"action": "admin_api_revoke"}

    async def confirm_revoke_api_key(self, event, api_key: str):
        """Confirm revoke API key"""
        try:
            success = await db_manager.api_db.delete_api_key(api_key)
            if success:
                await event.answer("✅ API key revoked", alert=True)
            else:
                await event.answer("❌ Failed to revoke key", alert=True)
            await self.show_api_panel(event)
        except Exception as e:
            logger.error(f"Error revoking API key: {e}")
            await event.answer("❌ Error", alert=True)

    async def show_api_menu(self, event):
        """Show API menu for users"""
        api_text = (
            "🔑 **DARKBOXES API ACCESS**\n═══════════════════════\n\n"
            "🚀 Programmatic access to all DarkBoxes intelligence tools.\n\n"
            "Select an option:"
        )
        await event.edit(api_text, buttons=OneLineKeyboard.api_menu(), parse_mode="md")

    async def show_my_api_keys(self, event):
        """Show user's API keys"""
        try:
            user_id = event.sender_id
            api_keys = await db_manager.api_db.get_user_api_keys(user_id)

            keys_text = "🔑 **MY API KEYS**\n═══════════════════════\n\n"

            if not api_keys:
                keys_text += "⚠️ You don't have any API keys yet.\n\n💡 Purchase an API plan to get started!"
            else:
                for i, key_info in enumerate(api_keys, 1):
                    api_key = key_info['api_key']
                    created = key_info.get('created_at', '')[:10]
                    expires = key_info.get('expires_at', '')[:10]
                    is_active = key_info.get('is_active', True)
                    requests_used = key_info.get('total_requests', 0)
                    status = "✅ Active" if is_active else "❌ Inactive"

                    keys_text += (
                        f"**Key #{i}**\n"
                        f"├─ Key: `{api_key[:16]}...{api_key[-8:]}`\n"
                        f"├─ Status: {status}\n"
                        f"├─ Created: {created}\n"
                        f"├─ Expires: {expires}\n"
                        f"└─ Requests: {requests_used}\n\n"
                    )

            await event.edit(keys_text, buttons=OneLineKeyboard.api_menu(), parse_mode="md")

        except Exception as e:
            logger.error(f"❌ Error in show_my_api_keys: {e}")
            await event.answer("❌ Error loading API keys", alert=True)

    async def show_api_usage(self, event):
        """Show API usage for user"""
        try:
            user_id = event.sender_id
            stats = await db_manager.api_db.get_api_stats(user_id)

            usage_text = "📊 **API USAGE STATISTICS**\n═══════════════════════\n\n"

            if stats.get('total_requests', 0) == 0:
                usage_text += "⚠️ No API usage recorded yet.\n\n💡 Start using your API key to see statistics here!"
            else:
                usage_text += (
                    f"📈 **Overall Statistics**\n"
                    f"├─ Total Requests: {stats['total_requests']}\n"
                    f"├─ Requests Used: {stats['requests_used']}\n"
                    f"└─ Active Keys: {stats.get('active_keys', 0)}\n\n"
                )

                if stats.get('recent_activity'):
                    usage_text += "🕐 **Recent Activity**\n"
                    for req in stats['recent_activity'][:5]:
                        endpoint = req.get('endpoint', 'Unknown')
                        timestamp = req.get('timestamp', '')[:16]
                        success = "✅" if req.get('success') else "❌"
                        usage_text += f"{success} {endpoint} - {timestamp}\n"

            await event.edit(usage_text, buttons=OneLineKeyboard.api_menu(), parse_mode="md")

        except Exception as e:
            logger.error(f"❌ Error in show_api_usage: {e}")
            await event.answer("❌ Error loading API usage", alert=True)

    async def show_api_plans(self, event):
        """Show API plans"""
        plans_text = (
            "💎 **API SUBSCRIPTION PLANS**\n═══════════════════════\n\n"
            "💰 **BASIC API** — ₹499/month\n"
            "├─ 1,000 API calls/month\n"
            "└─ All search endpoints\n\n"
            "🚀 **PRO API** — ₹999/month\n"
            "├─ 5,000 API calls/month\n"
            "└─ Priority support + webhooks\n\n"
            "👑 **ENTERPRISE API** — ₹2,999/month\n"
            "├─ 20,000 API calls/month\n"
            "└─ Dedicated manager + custom integrations\n\n"
            "📤 Tap a plan to pay via screenshot:"
        )
        await event.edit(plans_text, buttons=OneLineKeyboard.api_plans_menu(), parse_mode="md")

    async def show_api_plan_details(self, event, plan_id: str):
        """Show details for a specific API plan"""
        prices = {'basic': 499, 'pro': 999, 'enterprise': 2999}
        calls = {'basic': 1000, 'pro': 5000, 'enterprise': 20000}
        user_id = event.sender_id

        if plan_id not in prices:
            await event.answer("❌ Invalid plan", alert=True)
            return

        text = (
            f"🔑 **API {plan_id.upper()} PLAN**\n\n"
            f"💰 Price: ₹{prices[plan_id]}/month\n"
            f"📊 API Calls: {calls[plan_id]:,}/month\n\n"
            f"**To purchase:**\n"
            f"1️⃣ Pay ₹{prices[plan_id]} to: `{config.UPI_ID}`\n"
            f"2️⃣ Tap the button below to submit screenshot\n"
            f"3️⃣ Activated within 5–10 minutes\n\n"
            f"Your ID: `{user_id}`"
        )

        buttons = [
            [Button.inline("📤 Submit Payment Screenshot", f"submit_api_payment_{plan_id}")],
            [Button.inline("« Back", "api_plans")]
        ]
        await event.edit(text, buttons=buttons, parse_mode="md")

    async def show_api_docs(self, event):
        """Show API documentation"""
        docs_text = (
            "📖 **API DOCUMENTATION**\n═══════════════════════\n\n"
            f"🌐 **Base URL:** `{config.API_BASE_URL}`\n\n"
            "🔑 **Auth:** Include API key in header:\n"
            "`X-API-Key: your_api_key_here`\n\n"
            "📡 **Endpoints:**\n"
            "• `POST /api/v1/search/phone`\n"
            "• `POST /api/v1/search/email`\n"
            "• `POST /api/v1/search/aadhar`\n"
            "• `POST /api/v1/search/vehicle`\n"
            "• `POST /api/v1/search/leak`\n"
            "• `GET /api/v1/status`\n"
            "• `GET /api/v1/balance`\n\n"
            f"📚 Full docs: {config.API_BASE_URL}/api/v1/docs\n"
            f"💬 Support: @darkboxesAdmin"
        )
        await event.edit(docs_text, buttons=OneLineKeyboard.api_menu(), parse_mode="md")

    async def ask_for_api_plan_selection(self, event):
        """Ask admin to select API plan for creation"""
        await event.edit(
            "🔑 **CREATE API KEY**\n\n"
            "Select plan to create for user:",
            buttons=[
                [Button.inline("💰 Basic (30 days)", "confirm_create_api_basic_30")],
                [Button.inline("🚀 Pro (30 days)", "confirm_create_api_pro_30")],
                [Button.inline("👑 Enterprise (30 days)", "confirm_create_api_enterprise_30")],
                [Button.inline("« Admin Panel", "admin_panel")]
            ]
        )

    async def confirm_create_api_key(self, event, plan_id: str, days: int):
        """Create API key for the last searched user"""
        try:
            # Get the user from state
            user_id = event.sender_id
            state = user_states.get(user_id, {})
            target_user = state.get("target_user_id")

            if not target_user:
                await event.answer("❌ No user selected. Search a user first.", alert=True)
                return

            result = await db_manager.api_db.create_api_key(target_user, plan_id, days, "Admin created")

            if result:
                api_key = result.get("api_key", "N/A")
                await event.edit(
                    f"✅ **API KEY CREATED**\n\n"
                    f"👤 User: `{target_user}`\n"
                    f"🔑 Key: `{api_key}`\n"
                    f"📦 Plan: {plan_id}\n"
                    f"⏰ Days: {days}\n\n"
                    f"User notified.",
                    buttons=OneLineKeyboard.back_to_admin(),
                    parse_mode="md"
                )
                try:
                    await bot_client.send_message(target_user, f"🎉 **API KEY ACTIVATED!**\n\nKey: `{api_key}`\nPlan: {plan_id}\n\nTest at: {config.API_BASE_URL}/api/v1/docs", parse_mode="md")
                except Exception:
                    pass
            else:
                await event.edit("❌ Failed to create API key", buttons=OneLineKeyboard.back_to_admin())

        except Exception as e:
            logger.error(f"Error creating API key: {e}")
            await event.answer("❌ Error creating API key", alert=True)


# ================== SEARCH ENGINE WITH PRIORITY MANAGEMENT ==================

class APIHandler:
    """Handle API requests.

    Authentication is a single shared secret (INTELGRID_SECRET env var).
    IntelGrid passes this key on every request — no per-user accounts,
    no api_keys collection, no Telegram required.
    """

    def __init__(self, db_manager: DatabaseManager, search_engine):
        self.db = db_manager
        self.search_engine = search_engine

    def _check_secret(self, request: web.Request) -> bool:
        """Verify the shared IntelGrid secret key."""
        secret = os.getenv("INTELGRID_SECRET", "")
        if not secret:
            logger.warning("⚠️  INTELGRID_SECRET not set — all API requests will be rejected")
            return False
        provided = request.headers.get("X-API-Key") or request.query.get("api_key")
        return provided == secret
    
    async def handle_search_request(self, request: web.Request, search_type: str) -> web.Response:
        """Handle search request. Auth = shared INTELGRID_SECRET."""
        try:
            if not self._check_secret(request):
                return web.json_response(
                    APIResponseFormatter.error("Invalid or missing API key", "AUTH_FAILED"),
                    status=401
                )

            data = await request.json()
            query = data.get("query", "").strip()
            if not query:
                return web.json_response(
                    APIResponseFormatter.error("query is required", "INVALID_REQUEST"),
                    status=400
                )

            cmd = SEARCH_COMMANDS.get(search_type, {})
            validation = cmd.get("validation")
            if validation and not re.match(validation, query):
                return web.json_response(
                    APIResponseFormatter.error(
                        f"Invalid query format. Example: {cmd['example']}", "INVALID_QUERY"
                    ),
                    status=400
                )

            # Use a neutral user_id=0 — credits/quota are managed by IntelGrid, not here
            result = await self.search_engine.perform_search(search_type, query, 0)

            if result["success"]:
                if search_type == "leak":
                    api_result = APIResponseFormatter.format_leak_result(result.get("files", []), query)
                else:
                    api_result = APIResponseFormatter.format_search_result(
                        result.get("result", ""), search_type, query, result.get("source", "Unknown")
                    )
                response_data = APIResponseFormatter.success(api_result, "Search completed")
                if search_type != "leak" and result.get("has_file") and result.get("content"):
                    response_data["data"]["raw_content"] = result["content"]
                logger.info(f"🔍 IntelGrid Search: {search_type} — {query}")
                return web.json_response(response_data)
            else:
                return web.json_response(
                    APIResponseFormatter.error(result.get("error", "Search failed"), "SEARCH_FAILED"),
                    status=404
                )

        except json.JSONDecodeError:
            return web.json_response(APIResponseFormatter.error("Invalid JSON", "INVALID_JSON"), status=400)
        except Exception as e:
            logger.error(f"❌ API search error: {e}")
            return web.json_response(
                APIResponseFormatter.error("Internal server error", "INTERNAL_ERROR"), status=500
            )

    async def handle_batch_search(self, request: web.Request) -> web.Response:
        """Handle batch search. Max 10 queries per call."""
        try:
            if not self._check_secret(request):
                return web.json_response(
                    APIResponseFormatter.error("Invalid or missing API key", "AUTH_FAILED"), status=401
                )

            data = await request.json()
            searches = data.get("searches", [])
            if not searches or not isinstance(searches, list):
                return web.json_response(
                    APIResponseFormatter.error("searches array required", "INVALID_REQUEST"), status=400
                )
            if len(searches) > 10:
                return web.json_response(
                    APIResponseFormatter.error("Maximum 10 searches per batch", "BATCH_LIMIT_EXCEEDED"), status=400
                )

            results = []
            successful = 0
            for search in searches:
                stype = search.get("type")
                query = search.get("query", "").strip()
                cmd = SEARCH_COMMANDS.get(stype, {})
                if not query or not cmd:
                    results.append({"type": stype, "query": query, "success": False, "error": "Invalid type or query"})
                    continue
                validation = cmd.get("validation")
                if validation and not re.match(validation, query):
                    results.append({"type": stype, "query": query, "success": False, "error": f"Invalid format. Example: {cmd['example']}"})
                    continue
                result = await self.search_engine.perform_search(stype, query, 0)
                if result["success"]:
                    successful += 1
                    if stype == "leak":
                        formatted = APIResponseFormatter.format_leak_result(result.get("files", []), query)
                    else:
                        formatted = APIResponseFormatter.format_search_result(
                            result.get("result", ""), stype, query, result.get("source", "Unknown")
                        )
                    results.append({"type": stype, "query": query, "success": True, "data": formatted})
                else:
                    results.append({"type": stype, "query": query, "success": False, "error": result.get("error", "Search failed")})

            logger.info(f"🔍 IntelGrid Batch: {successful}/{len(searches)} succeeded")
            return web.json_response(APIResponseFormatter.success({
                "total_searches": len(searches), "successful": successful,
                "failed": len(searches) - successful, "results": results,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, "Batch search completed"))

        except json.JSONDecodeError:
            return web.json_response(APIResponseFormatter.error("Invalid JSON", "INVALID_JSON"), status=400)
        except Exception as e:
            logger.error(f"❌ API batch error: {e}")
            return web.json_response(APIResponseFormatter.error("Internal server error", "INTERNAL_ERROR"), status=500)

    async def handle_status_request(self, request: web.Request) -> web.Response:
        """Return server status."""
        try:
            if not self._check_secret(request):
                return web.json_response(APIResponseFormatter.error("Auth failed", "AUTH_FAILED"), status=401)
            return web.json_response(APIResponseFormatter.success({
                "status": "online",
                "version": "2.0.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "base_url": config.API_BASE_URL
            }, "Server online"))
        except Exception as e:
            return web.json_response(APIResponseFormatter.error("Internal error", "INTERNAL_ERROR"), status=500)

    async def handle_balance_request(self, request: web.Request) -> web.Response:
        """Balance is managed by IntelGrid — relay just confirms it's alive."""
        try:
            if not self._check_secret(request):
                return web.json_response(APIResponseFormatter.error("Auth failed", "AUTH_FAILED"), status=401)
            return web.json_response(APIResponseFormatter.success(
                {"message": "Credits are managed by IntelGrid", "relay_status": "online"},
                "OK"
            ))
        except Exception as e:
            return web.json_response(APIResponseFormatter.error("Internal error", "INTERNAL_ERROR"), status=500)

    async def handle_usage_request(self, request: web.Request) -> web.Response:
        """Usage stats are managed by IntelGrid."""
        try:
            if not self._check_secret(request):
                return web.json_response(APIResponseFormatter.error("Auth failed", "AUTH_FAILED"), status=401)
            return web.json_response(APIResponseFormatter.success(
                {"message": "Usage tracking is managed by IntelGrid"},
                "OK"
            ))
        except Exception as e:
            return web.json_response(APIResponseFormatter.error("Internal error", "INTERNAL_ERROR"), status=500)


# ================== API SERVER ==================



# Search types that should wait 8s and pick the richest result from multiple responses
# ALL search types collect from every group simultaneously.
# Results from all groups that pass validity check are merged and all sent to user.
MULTI_COLLECT_TYPES = set()
MULTI_COLLECT_WINDOW = 8   # seconds to wait for additional results
COLLECT_ALL_RESULTS = True  # send ALL valid group results to user, not just best


def _score_result_richness(text: str) -> int:
    """Score a result message by how much data it contains.
    Higher = more information = better candidate to show the user.
    """
    if not text:
        return 0
    score = len(text)   # base: length in characters

    # Each key-value-style pair adds a bonus
    kv_patterns = [
        '": ', ': ', ' : ',
        'name', 'mobile', 'number', 'address', 'email',
        'father', 'mother', 'dob', 'gender', 'state',
        'district', 'operator', 'circle', 'uid', 'aadhar',
        'pan', 'gst', 'ifsc', 'bank', 'country', 'ip',
        'username', 'bio', 'followers', 'following',
        'company', 'phone', 'gstin', 'turnover',
        'city', 'pincode', 'village', 'relation',
    ]
    for kp in kv_patterns:
        score += text.lower().count(kp) * 25

    # Bonus for structured dividers (formatted output)
    for divider in ['━', '═', '─', '║', '╔', '╚']:
        if divider in text:
            score += 50

    # Penalty for very short messages
    if len(text.strip()) < 50:
        score -= 500

    return score


class SearchEngine:
    def __init__(self, db_manager, user_manager):
        self.db = db_manager
        self.user_manager = user_manager
        self.active_searches = {}
        self.waiting_for_files = {}
        self.group_performance = {}
    
    async def _auto_cleanup(self, search_id: str):
        """Auto-remove a search entry after 90 seconds.
        
        Cancels the future explicitly before removing so the polling loop in
        _search_single_group exits cleanly — prevents asyncio's
        'Task was destroyed but it is pending!' warning.
        """
        await asyncio.sleep(90)
        entry = self.active_searches.pop(search_id, None)
        if entry:
            future = entry.get("future")
            if future and not future.done():
                future.cancel()

    def _get_group_command(self, group: Dict, search_type: str) -> Optional[str]:
        """Get the correct command for a specific group and search type.
        
        Each group can define its own command map so e.g. one group accepts
        /family and another accepts /familyinfo for the same search type.
        Falls back to the first entry in SEARCH_COMMANDS[type]["commands"].

        Returns None  → send just the query (no command prefix, "no command" mode).
        Returns ""    → same as None (no command).
        Returns str   → use that as the command prefix.
        """
        # Per-group override takes priority
        group_cmds = group.get("commands", {})
        if search_type in group_cmds:
            cmd = group_cmds[search_type]
            # Explicit empty string or None means "no command" — send raw query
            return cmd if cmd else None
        # Fallback: use the global SEARCH_COMMANDS list
        cmd_list = SEARCH_COMMANDS.get(search_type, {}).get("commands", ["/search"])
        cmd = cmd_list[0] if cmd_list else "/search"
        return cmd if cmd else None

    async def _search_single_group(
        self,
        group: Dict,
        search_type: str,
        query: str,
        user_id: int,
        is_multi_collect: bool,
        multi_collect_window: float,
    ) -> Dict:
        """Send a search command to ONE group and wait for its reply.

        BASIC DB SPECIAL MODE (group["basic_db"] == True):
          The Basic Database group (EncoreXgroup) does NOT reply to our user
          account directly — instead its bot posts replies inside the group.
          For this group we:
            1. Send the command to the group
            2. Monitor ALL incoming messages in that group for up to
               `basic_db_wait` seconds (default 10)
            3. Accept any message whose text contains the user's query AND
               passes the validity check as a valid result

        Returns a result dict with at least {"success": bool}.
        This coroutine is run in parallel with other groups via asyncio.gather.
        """
        SCAN_EXTRA_WAIT = 20   # seconds grace after a scanning placeholder
        POLL_INTERVAL   = 0.25
        is_basic_db     = bool(group.get("basic_db"))

        command = self._get_group_command(group, search_type)
        outgoing_text = f"{command} {query}".strip() if command else query

        try:
            sent_msg = await user_client.send_message(group["entity"], outgoing_text)
        except Exception as e:
            logger.error(f"❌ Could not send to {group['name']}: {e}")
            self._update_group_performance(group["name"], False)
            return {"success": False}

        logger.info(f"📤 [{group['name']}] Sent: {outgoing_text!r} (basic_db={is_basic_db})")

        search_id     = f"{user_id}_{int(time.time() * 1000)}_{group['name']}"
        future        = asyncio.get_running_loop().create_future()
        collect_until = time.time() + multi_collect_window if is_multi_collect else None
        wait_secs     = group.get("basic_db_wait", 10) if is_basic_db else group["timeout"]

        self.active_searches[search_id] = {
            "user_id":        user_id,
            "future":         future,
            "start_time":     time.time(),
            "group":          group,
            "message_id":     sent_msg.id,
            "search_type":    search_type,
            "query":          query,
            "chat_id":        self._normalize_chat_id(group["entity"].id) if hasattr(group["entity"], "id") else str(group["entity"]),
            "expecting_file": False,
            "file_wait_start": None,
            "priority":       group["weight"],
            "multi_collect":  is_multi_collect,
            "candidates":     [],
            "collect_until":  collect_until,
            # Basic DB flags
            "basic_db":       is_basic_db,
            "basic_db_found": False,
        }
        asyncio.create_task(self._auto_cleanup(search_id))

        # ── BASIC DB: poll the group — handle_incoming_message matches replies ─
        if is_basic_db:
            deadline = time.time() + wait_secs
            result   = None
            logger.info(f"🔍 [{group['name']}] Basic DB mode — watching group for {wait_secs}s")

            while time.time() < deadline:
                if future.done():
                    try:
                        result = future.result()
                    except Exception:
                        result = {"success": False}
                    break
                await asyncio.sleep(POLL_INTERVAL)

            entry = self.active_searches.pop(search_id, None)
            if entry and not future.done():
                future.cancel()

            if result and result.get("success"):
                self._update_group_performance(group["name"], True)
                logger.info(f"✅ [{group['name']}] Basic DB valid result")
                return result
            else:
                self._update_group_performance(group["name"], False)
                logger.info(f"⏱️ [{group['name']}] Basic DB — no result in {wait_secs}s")
                return {"success": False}

        # ── NORMAL groups: wait for direct reply or matching message ──────────
        deadline  = time.time() + wait_secs
        result    = None
        timed_out = False

        while True:
            now = time.time()

            if is_multi_collect:
                search_ref  = self.active_searches.get(search_id, {})
                collect_end = search_ref.get("collect_until", 0)
                if collect_end and now >= collect_end:
                    candidates = search_ref.get("candidates", [])
                    if candidates:
                        candidates.sort(key=lambda x: x[0], reverse=True)
                        best_score, best_result = candidates[0]
                        logger.info(
                            f"🏆 [{group['name']}] Multi-collect: best of "
                            f"{len(candidates)} (score={best_score})"
                        )
                        result = best_result
                    else:
                        timed_out = True
                    break

            if future.done():
                try:
                    result = future.result()
                except Exception:
                    result = {"success": False}
                break

            search_ref = self.active_searches.get(search_id, {})
            if search_ref.get("pending_encorex"):
                scan_start = search_ref.get("encorex_wait_start", now)
                extended   = scan_start + SCAN_EXTRA_WAIT
                if extended > deadline:
                    logger.info(f"⏳ [{group['name']}] Scanning — extending deadline by {SCAN_EXTRA_WAIT}s")
                    deadline = extended

            if now >= deadline:
                timed_out = True
                break

            await asyncio.sleep(POLL_INTERVAL)

        entry = self.active_searches.pop(search_id, None)
        if entry and not future.done():
            future.cancel()

        if timed_out or result is None:
            self._update_group_performance(group["name"], False)
            logger.info(f"⏱️ [{group['name']}] Timed out")
            return {"success": False}

        if result.get("success"):
            self._update_group_performance(group["name"], True)
            logger.info(f"✅ [{group['name']}] Valid result")
        else:
            self._update_group_performance(group["name"], False)
            logger.info(f"⚠️ [{group['name']}] No data found")

        return result

    async def perform_search(self, search_type: str, query: str, user_id: int,
                              is_free_user: bool = False) -> Dict:
        """Perform PARALLEL search across all groups simultaneously.

        All enabled groups receive the query at the same time.
        • For normal search types: first group to return a valid result wins;
          remaining group tasks are cancelled immediately.
        • For multi-collect types: all groups collect for MULTI_COLLECT_WINDOW
          seconds, then the richest result across all groups is returned.

        is_free_user: if True, restrict to FREE_USER_CONFIG["allowed_groups"].
        """
        # Guard against runaway memory growth
        if len(self.active_searches) > 200:
            logger.warning("⚠️ active_searches > 200 — clearing to prevent memory leak")
            self.active_searches.clear()

        logger.info(f"🚀 Parallel {search_type} search: {query!r} (user={user_id}, free={is_free_user})")

        if search_type == "leak":
            return await self.perform_leak_search(query, user_id)

        is_multi_collect = search_type in MULTI_COLLECT_TYPES
        cmd              = SEARCH_COMMANDS.get(search_type, {})
        preferred_priority = cmd.get("priority", "primary")

        # Collect all valid (unique) groups — respects free-user restriction
        groups = self._get_priority_groups(preferred_priority, is_free_user=is_free_user)
        if not groups:
            logger.error("❌ No groups available for search")
            return {
                "success": False,
                "error": "❌ No search networks are currently available. Please try again later."
            }

        logger.info(f"📡 Querying {len(groups)} group(s) in parallel: {[g['name'] for g in groups]}")

        # ── PARALLEL execution — query ALL groups simultaneously ─────────────
        # Every group is queried at the same time. ALL valid results are
        # collected and returned together so the user sees data from every
        # source that has it.
        tasks = [
            asyncio.create_task(
                self._search_single_group(
                    group, search_type, query, user_id,
                    is_multi_collect=False,
                    multi_collect_window=0,
                )
            )
            for group in groups
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results: List[Dict] = []
        for r in raw_results:
            if isinstance(r, Exception) or not isinstance(r, dict):
                continue
            if r.get("success"):
                valid_results.append(r)

        if valid_results:
            # De-duplicate by actual data fingerprint — NOT raw[:200] which causes
            # false-duplicate collisions when two sources share the same header text
            # (e.g. two IntelX messages that both start with the HiTeckGroop preamble).
            def _content_fingerprint(r: Dict) -> str:
                raw = r.get("raw_result", r.get("result", ""))
                # Strip all non-alphanumeric chars so formatting differences don't
                # create false non-duplicates, and hash full content so two results
                # with even one different data field are treated as distinct.
                core = re.sub(r"[^a-zA-Z0-9]", "", raw)
                return hashlib.md5(core.encode(errors="ignore")).hexdigest()

            seen_hashes: set = set()
            unique_results: List[Dict] = []
            for r in valid_results:
                h = _content_fingerprint(r)
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    unique_results.append(r)

            logger.info(f"✅ {len(unique_results)} unique valid result(s) from {len(valid_results)} group(s)")

            if len(unique_results) == 1:
                # Single result — return as-is
                return unique_results[0]
            else:
                # Multiple results — combine into multi_results payload
                combined_raw = "\n\n".join(
                    r.get("raw_result", r.get("result", "")) for r in unique_results
                )
                return {
                    "success": True,
                    "multi_results": unique_results,   # list of individual result dicts
                    "result": unique_results[0].get("result", ""),  # fallback for compat
                    "raw_result": combined_raw,
                    "has_file": False,
                    "result_count": len(unique_results),
                }

        # All groups returned no data
        logger.warning(f"⚠️ All groups returned no data for {search_type}:{query} (user={user_id})")
        await self._notify_admin(user_id, search_type, query)

        return {
            "success": False,
            "error": (
                f"🔍 **NO RESULTS FOUND**\n\nQuery: `{query}`\n\n"
                f"⚠️ Your query has been escalated to the admin team.\n\n"
                f"📝 **Next steps:**\n"
                f"• Admin will manually review your query\n"
                f"• If data is available you'll receive it within 24 hours\n\n"
                f"💎 **Tips:** Verify the query format • Try a different search type\n\n"
                f"Contact {config.ADMIN_CONTACT} for assistance."
            )
        }
    
    async def perform_leak_search(self, query: str, user_id: int) -> Dict:
        """Perform advanced leak search (Search Anything)"""
        try:
            logger.info(f"🚀 ADVANCED LEAK SEARCH: {query} (User: {user_id})")
            
            # Get the advanced group
            advanced_group = GROUP_PRIORITIES["advanced"]
            if not advanced_group.get("entity"):
                logger.error("❌ Advanced group not resolved")
                return {
                    "success": False,
                    "error": "❌ Advanced search engine is currently unavailable. Please try again later."
                }
            
            # Send leak command
            leak_command = advanced_group.get("leak_command", "/leak")
            sent_msg = await user_client.send_message(advanced_group["entity"], f"{leak_command} {query}")
            
            # Create search tracking
            search_id = f"{user_id}_{int(time.time())}_leak"
            future = asyncio.get_running_loop().create_future()
            
            self.active_searches[search_id] = {
                "user_id": user_id,
                "future": future,
                "start_time": time.time(),
                "group": advanced_group,
                "message_id": sent_msg.id,
                "search_type": "leak",
                "query": query,
                "chat_id": advanced_group["entity"].id if hasattr(advanced_group["entity"], 'id') else str(advanced_group["entity"]),
                "expecting_file": True,
                "file_wait_start": None,
                "priority": advanced_group["weight"],
                "expect_multiple_files": True,
                "files_received": [],
                "file_types": ["json", "txt"],
                "processed_files": []  # NEW: Track which files we've already processed
            }
            # Auto-cleanup this search after 180 seconds to prevent memory leaks
            asyncio.create_task(self._auto_cleanup(search_id))
            
            # ── Scanning-aware wait (same pattern as perform_search) ──────────
            SCAN_EXTRA_WAIT = 20
            POLL_INTERVAL   = 0.3
            deadline  = time.time() + 15   # base 15s for leak
            result    = None
            timed_out = False

            while True:
                if future.done():
                    try:
                        result = future.result()
                    except Exception:
                        result = {"success": False}
                    break

                now = time.time()
                search_ref = self.active_searches.get(search_id, {})
                if search_ref.get("pending_encorex"):
                    scan_start = search_ref.get("encorex_wait_start", now)
                    extended   = scan_start + SCAN_EXTRA_WAIT
                    if extended > deadline:
                        logger.info(f"⏳ Leak: scanning detected — extending deadline {SCAN_EXTRA_WAIT}s")
                        deadline = extended

                if now >= deadline:
                    timed_out = True
                    break

                await asyncio.sleep(POLL_INTERVAL)

            if search_id in self.active_searches:
                if not future.done():
                    future.cancel()
                self.active_searches.pop(search_id, None)

            if timed_out or result is None:
                logger.info(f"⏱️ Timeout from advanced search")
                return {
                    "success": False,
                    "error": "⏱️ **ADVANCED SEARCH TIMEOUT**\n\nOur advanced engine is processing your query.\nResults will be delivered shortly if available.\n\n⚠️ **For immediate results:**\n• Use specific search types (Phone, Email, etc.)\n• Ensure phone numbers include country code\n• Contact @darkboxesAdmin for premium support"
                }

            if result["success"]:
                logger.info(f"✅ Advanced leak search successful")
                return result
            else:
                logger.info(f"⚠️ No result from advanced search")
                return {
                    "success": False,
                    "error": "❌ No information found in our advanced databases.\n\n⚠️ **Note:** For phone searches, include country code (e.g., 917204764637)\n💎 **Try our premium sources for better results.**"
                }
                
        except Exception as e:
            logger.error(f"❌ Error in leak search: {e}")
            return {
                "success": False,
                "error": "❌ Advanced search engine error. Please try again or use specific search types."
            }
    
    def _get_priority_groups(self, preferred_priority: str, is_free_user: bool = False) -> List:
        """Get groups sorted in configured priority order: primary → secondary → tertiary.
        The preferred_priority group always goes first, then the remaining keys in order.
        The 'advanced' group is excluded (used only for leak searches).
        Groups sharing the same identifier (same chat) are de-duplicated.

        If is_free_user=True and FREE_USER_CONFIG["allowed_groups"] is set,
        only the listed group keys are included.
        """
        priority_keys = ["primary", "secondary", "tertiary"]
        # Put preferred priority first
        if preferred_priority in priority_keys:
            priority_keys.remove(preferred_priority)
            priority_keys.insert(0, preferred_priority)

        # Free user group restriction
        free_allowed = FREE_USER_CONFIG.get("allowed_groups", []) if is_free_user else []

        seen_identifiers = set()
        sorted_groups = []
        for key in priority_keys:
            # If free user restriction is active and this key isn't allowed, skip
            if is_free_user and free_allowed and key not in free_allowed:
                continue
            group_data = GROUP_PRIORITIES.get(key)
            if not group_data:
                continue
            if not group_data.get("enabled", True):
                continue
            if not group_data.get("entity"):
                logger.warning(f"⚠️ Group {group_data['name']} ({key}) has no entity — skipping")
                continue
            ident = group_data.get("identifier", group_data["name"])
            if ident in seen_identifiers:
                logger.info(f"⏩ Skipping duplicate group identifier: {ident}")
                continue
            seen_identifiers.add(ident)
            sorted_groups.append(group_data)

        logger.info(f"📋 Search cascade order: {[g['name'] for g in sorted_groups]}")
        return sorted_groups
    
    def _update_group_performance(self, group_name: str, success: bool):
        """Update group performance tracking"""
        if group_name not in self.group_performance:
            self.group_performance[group_name] = {"success": 0, "total": 0}
        
        self.group_performance[group_name]["total"] += 1
        if success:
            self.group_performance[group_name]["success"] += 1
    
    @staticmethod
    def _normalize_chat_id(cid) -> int:
        """Normalize a Telegram chat ID to its bare positive channel ID.

        Telethon stores Channel entities with their bare positive ID
        (e.g. 1234567890), but event.chat_id for supergroup messages
        arrives as the negative -100-prefixed form (e.g. -1001234567890).
        This helper converts both forms to the same bare integer so they
        can be compared reliably.
        """
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return 0
        if cid < 0:
            s = str(-cid)
            if s.startswith("100") and len(s) > 3:
                return int(s[3:])   # strip -100 prefix
            return -cid             # regular group (no -100 prefix)
        return cid

    async def handle_incoming_message(self, event):
        """Handle incoming messages for search responses"""
        try:
            message = event.message

            # ── CRITICAL: Skip our OWN outgoing messages ──────────────────────
            # user_client fires events for messages WE send (outgoing=True).
            # Without this guard, the /num command we just sent would instantly
            # resolve the future with success=False before any bot can reply.
            if getattr(message, 'out', False):
                return

            text = message.text or message.raw_text or ""

            # Normalize incoming chat_id once for all comparisons below
            incoming_chat_norm = self._normalize_chat_id(event.chat_id)

            # ── Priority 1: Direct reply to our sent command ──────────────────
            if message.reply_to:
                reply_to_id = message.reply_to.reply_to_msg_id
                for search_id, search_info in list(self.active_searches.items()):
                    if reply_to_id == search_info["message_id"]:
                        logger.info(f"📩 Found direct reply to our search message")
                        await self._process_search_response(search_id, search_info, message)
                        # Never return early while other searches (any group) are still
                        # active — each parallel group task has its own future and we
                        # must keep the event handler alive so they can all resolve.
                        has_other_pending = any(
                            sid != search_id
                            for sid in self.active_searches
                        )
                        if not search_info.get("multi_collect") and not has_other_pending:
                            return
            
            # ── Priority 1.5: Edited IntelX paginated message ──────────────
            # The IntelX bot paginates by editing its own message in-place.
            # Route edited messages back to the right search via message_id.
            incoming_msg_id = getattr(message, "id", None)
            if incoming_msg_id:
                for _sid, _sinfo in list(self.active_searches.items()):
                    if _sinfo.get("intelx_paged_msg_id") == incoming_msg_id:
                        logger.info(
                            f"⏭️ IntelX edited page matched (msg_id={incoming_msg_id}) — routing"
                        )
                        await self._process_search_response(_sid, _sinfo, message)
                        break

            # ── Priority 2: Any message in the same chat ──────────────────────
            for search_id, search_info in list(self.active_searches.items()):
                try:
                    chat_match = False
                    entity = search_info["group"].get("entity")
                    if entity and hasattr(entity, 'id'):
                        chat_match = incoming_chat_norm == self._normalize_chat_id(entity.id)
                    elif search_info.get("chat_id"):
                        chat_match = incoming_chat_norm == self._normalize_chat_id(search_info["chat_id"])
                    
                    if not chat_match:
                        continue

                    # ── DIRECT_REPLY_ONLY guard ────────────────────────────────
                    # For shared group chats (like premium DB) the bot replies to
                    # our command with a direct reply. Any other message in the
                    # same group belongs to a DIFFERENT user's query and must be
                    # ignored — otherwise we'd steal their result.
                    # basic_db is exempt because it NEVER sends direct replies.
                    if search_info["group"].get("direct_reply_only") and not search_info.get("basic_db"):
                        is_direct_reply = (
                            message.reply_to
                            and message.reply_to.reply_to_msg_id == search_info["message_id"]
                        )
                        if not is_direct_reply:
                            logger.debug(
                                f"⛔ [{search_info['group']['name']}] Skipping non-reply message "
                                f"(direct_reply_only, our_msg={search_info['message_id']})"
                            )
                            continue

                    # Check if this is a file attachment
                    file_check = await self._check_and_process_file(message, search_info)
                    if file_check is not None:
                        logger.info(f"📁 Found file in {search_info['group']['name']}")
                        await self._process_search_response(search_id, search_info, message)
                        if not search_info.get("multi_collect"):
                            return
                        continue
                    
                    query = search_info.get("query", "").lower().strip()
                    text_lower = text.lower()

                    # ── Skip if this is a scanning placeholder ─────────────
                    if self._is_encorex_scanning_message(text):
                        await self._process_search_response(search_id, search_info, message)
                        # Use continue — not return — so other active searches
                        # (especially basic_db) still get a chance to match
                        # this same message event.
                        continue

                    # ── Skip obviously empty / too-short messages ──────────────
                    if not text or len(text.strip()) < 5:
                        continue

                    search_type    = search_info.get("search_type", "")
                    pending_encorex = bool(search_info.get("pending_encorex"))

                    # ─────────────────────────────────────────────────────────────
                    # RESULT DETECTION — ordered from most-specific to broadest
                    # ─────────────────────────────────────────────────────────────

                    # A) Query string appears anywhere in the message
                    query_in_message = bool(query and len(query) >= 4 and query in text_lower)

                    # B) After a scanning placeholder, accept ANY substantive non-scanning msg
                    pending_any_result = (
                        pending_encorex
                        and len(text.strip()) >= 15
                    )

                    # C) ENCOREX OSINT / INTELX result frame
                    is_encorex_osint_result = (
                        (
                            'encorex osint' in text_lower
                            or 'encorex intelx' in text_lower
                            or '╔═══《' in text
                            or '╘══《' in text
                        )
                        and (
                            '✅' in text
                            or '"result"' in text_lower
                            or '"success"' in text_lower
                            or '"status"' in text_lower
                        )
                    )

                    # D) Plain JSON / key-value result (any search type)
                    data_field_indicators = [
                        '"name":', '"mobile":', '"number":', '"address":',
                        '"result":', '"results":', '"aadhar":', '"fname":',
                        '"circle":', '"country":', '"email":', '"alt":',
                        '"dob":', '"gender":', '"operator":', '"telecom":',
                        '"state":', '"district":', '"uid":', '"pan":',
                        '"father_name":', '"alt_mobile":', '"id_number":',
                        'name:', 'mobile:', 'number:', 'address:',
                        'operator:', 'circle:', 'state:', 'dob:',
                    ]
                    has_data_fields = any(f in text_lower for f in data_field_indicators)
                    looks_like_result = (
                        has_data_fields
                        and text_lower.count(':') >= 2
                        and len(text.strip()) >= 20
                    )

                    # E) Common result-style patterns for ALL search types
                    universal_result_patterns = [
                        'number fetched', 'fetched :-', 'fetched:',
                        'mobile:', 'phone:', 'telecom:', 'operator:',
                        'ration', 'family member', 'relation:',
                        'father name', 'mother name', 'father:', 'mother:',
                        'husband:', 'wife:', 'dob:', 'date of birth',
                        'gender:', 'village:', 'district:', 'state:', 'pincode:',
                        'aadhar:', 'uid:', 'head of family',
                        'pan:', 'gstin:', 'ifsc:', 'bank:',
                        '✅ result', '✅ found', '✅ success',
                        'name :', 'mobile :', 'address :',
                        'result :', 'info :', 'details :',
                        '━━━━', '────', '═══', '║', '╔', '╚',
                    ]
                    universal_match = (
                        len(text.strip()) >= 20
                        and any(p in text_lower for p in universal_result_patterns)
                    )

                    # F) Large substantive message from this group
                    large_message_result = (
                        len(text.strip()) >= 100
                        and not TextProcessor.is_processing_message(text)
                    )

                    # G) IntelX / hiteckgroop / NUMBER TO DETAILS multi-message pattern
                    intelx_signals = [
                        'breached:', '🔎request:', 'subjects made:',
                        'number of results:', 'number of leaks:', 'search time:',
                        'telephone', 'adres', 'full name',
                        'the name of the father', 'region',
                        'hiteckgroop', 'hiteck',
                        'encrypted password', 'date of registration',
                        # "NUMBER TO DETAILS:" format from third group
                        'number to details',
                        '"father_name":', '"alt_mobile":', '"id_number":',
                    ]
                    is_intelx_message = any(sig in text_lower for sig in intelx_signals)

                    # Block-char masked data — always a valid result
                    has_masked_data = '█' in text and len(text.strip()) >= 30

                    # ── BASIC DB: always accept if query in message text ───────
                    # The Basic DB group bot replies to the group, not to us.
                    # So we accept any message containing the query that is
                    # not our own outgoing command, and passes validity check.
                    # NOTE: query may appear inside JSON quotes e.g. "9939608735"
                    # so we strip non-alphanumeric chars for comparison too.
                    _query_digits = re.sub(r'\D', '', query)  # digits only for phone
                    _text_nodots  = re.sub(r'["\'\s]', '', text_lower)  # strip quotes/spaces
                    _query_clean  = re.sub(r'[^a-z0-9]', '', query)      # alphanumeric only
                    _text_clean   = re.sub(r'[^a-z0-9]', '', text_lower) # alphanumeric only
                    _query_in_stripped = bool(
                        (_query_digits and len(_query_digits) >= 6 and _query_digits in _text_nodots)
                        or (_query_clean and len(_query_clean) >= 4 and _query_clean in _text_clean)
                    )
                    is_basic_db_match = (
                        search_info.get("basic_db")
                        and not getattr(message, 'out', False)
                        and query
                        and len(query) >= 3
                        and (query in text_lower or _query_in_stripped)
                        and len(text.strip()) >= 10
                        and not TextProcessor.is_processing_message(text)
                    )

                    # For basic_db group, ONLY accept if our exact query is present.
                    # All the broad universal matchers (looks_like_result,
                    # universal_match, large_message_result, is_intelx_message,
                    # has_masked_data) would match OTHER users' results posted in
                    # the shared group. Strict query-match keeps us from stealing
                    # someone else's result.
                    if search_info.get("basic_db"):
                        matched = is_basic_db_match
                    else:
                        matched = (
                            query_in_message
                            or pending_any_result
                            or is_encorex_osint_result
                            or looks_like_result
                            or universal_match
                            or large_message_result
                            or is_intelx_message
                            or has_masked_data
                        )

                    if matched:
                        logger.info(
                            f"📨 Candidate result in {search_info['group']['name']} "
                            f"(query={query_in_message}, basic_db={is_basic_db_match}, "
                            f"pending={pending_any_result}, "
                            f"encorex={is_encorex_osint_result}, json={looks_like_result}, "
                            f"universal={universal_match}, large={large_message_result}, "
                            f"intelx={is_intelx_message}, masked={has_masked_data})"
                        )
                        await self._process_search_response(search_id, search_info, message)
                        # For basic_db searches, always continue the loop — their
                        # future is resolved independently and other search_ids
                        # in the loop may also need this message.
                        # For normal searches, only return early if NO basic_db
                        # searches are still pending (otherwise they'd be cut off).
                        if search_info.get("basic_db"):
                            continue  # basic_db: never return early, keep looping
                        if not search_info.get("multi_collect"):
                            has_pending_basic_db = any(
                                si.get("basic_db")
                                for si in self.active_searches.values()
                            )
                            if not has_pending_basic_db:
                                return
                        # else: multi_collect or pending basic_db — continue loop

                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"❌ Error handling incoming message: {e}")

    async def _check_and_process_file(self, message, search_info: Dict) -> Optional[Dict]:
        """Check if message has file and process it"""
        try:
            # First check for actual file/document
            if message.media and hasattr(message.media, 'document'):
                logger.info(f"📁 Found document media in message")
                return await self._process_file(message, search_info)
        
            if hasattr(message, 'file') and message.file:
                logger.info(f"📁 Found file attribute in message")
                return await self._process_file(message, search_info)
        
            if message.document:
                logger.info(f"📁 Found document in message")
                return await self._process_file(message, search_info)
        
            # Check for text that might be a TXT file
            text = message.text or message.raw_text or ""
            if text and len(text) > 1000:
                # Check for TXT file indicators in the text
                txt_indicators = [
                    'Full results available as JSON file',
                    'Total length:',
                    'TRUNCATED - DATA TOO LONG',
                    '───────────────────────',
                    '━━━━━━━━━━━━━━━━━━━━━━━━',
                    'Service: leak',
                    'Requested by:',
                    '👤 ʀᴇǫᴜᴇꜱᴛᴇᴅ ʙʏ:',
                    '🔍 ǫᴜᴇʀʏ:',
                    '⏰ ᴛɪᴍᴇ:'
                ]
            
                indicator_count = 0
                for indicator in txt_indicators:
                    if indicator in text:
                        indicator_count += 1
            
                # If multiple indicators found, treat as TXT file
                if indicator_count >= 3:
                    logger.info(f"📄 Detected TXT file content in message text ({indicator_count} indicators)")
                
                    # Clean the text content
                    cleaned_content = TextProcessor.clean_content(text, search_info["search_type"])
                
                    result = {
                        "success": True,
                        "result": None,
                        "has_file": True,
                        "content": cleaned_content,
                        "raw_bytes": cleaned_content.encode('utf-8'),
                        "filename": f"leak_{search_info['query']}_{int(time.time())}.txt",
                        "is_text_based": True
                    }
                
                    # For non-leak searches, format the result
                    if search_info["search_type"] != "leak":
                        formatted_result = PremiumFormatter.format_result(
                            cleaned_content,
                            search_info["search_type"],
                            search_info["query"],
                            search_info["group"]["name"]
                        )
                        result["result"] = formatted_result
                
                    logger.info(f"✅ Processed TXT content with {len(cleaned_content)} characters")
                    return result
        
            return None
        
        except Exception as e:
            logger.error(f"❌ Error checking for file: {e}")
            return None
    
    async def _process_search_response(self, search_id: str, search_info: Dict, message):
        """Process a search response message"""
        try:
            text = message.text or message.raw_text or ""
            logger.info(f"📨 Processing message in {search_info['group']['name']}: {text[:120]}...")
            
            # ===== SCANNING PLACEHOLDER FILTER =====
            # Skip for basic_db groups — they post results directly into the group
            # and their messages should never be treated as scanning placeholders.
            if self._is_encorex_scanning_message(text) and not search_info.get("basic_db"):
                logger.info(
                    f"🛰️ Scanning placeholder from {search_info['group']['name']} "
                    f"— marking pending_encorex, waiting for real result..."
                )
                if not search_info.get("pending_encorex"):
                    search_info["pending_encorex"]      = True
                    search_info["encorex_wait_start"]   = time.time()
                    search_info["scanning_message_id"]  = message.id
                return  # Do NOT resolve future — wait for edit or next message

            if search_info.get("pending_encorex"):
                logger.info(
                    f"✅ Result received after scanning wait from {search_info['group']['name']} "
                    f"(msg_id={message.id}, scanning_msg_id={search_info.get('scanning_message_id')})"
                )
                search_info["pending_encorex"]  = False
                search_info["_came_after_scan"] = True
            # ===== END SCANNING FILTER =====
            
            # Special handling for leak search
            if search_info["search_type"] == "leak":
                return await self._process_leak_response(search_id, search_info, message)
            
            file_result = await self._check_and_process_file(message, search_info)
            if file_result is not None:
                logger.info(f"✅ Processing file from message")
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result(file_result)
                    del self.active_searches[search_id]
                return
            
            if TextProcessor.is_file_generated_message(text):
                logger.info(f"📄 File generation message detected in {search_info['group']['name']}")
                
                if message.reply_to:
                    logger.info(f"🔗 File message is a reply, checking replied message...")
                    try:
                        replied_msg = await message.get_reply_message()
                        if replied_msg:
                            replied_file_result = await self._check_and_process_file(replied_msg, search_info)
                            if replied_file_result:
                                logger.info(f"✅ Found file in replied message")
                                if search_id in self.active_searches:
                                    future = self.active_searches[search_id]["future"]
                                    if not future.done():
                                        future.set_result(replied_file_result)
                                    del self.active_searches[search_id]
                                return
                    except Exception as e:
                        logger.error(f"❌ Error checking replied message: {e}")
                
                search_info["expecting_file"] = True
                search_info["file_wait_start"] = time.time()
                logger.info(f"⏳ Waiting for file to arrive...")
                return
            
            if TextProcessor.is_processing_message(text):
                logger.info(f"⏳ Placeholder/confirmation detected — waiting for real result: {text[:80]!r}")
                if not search_info.get("pending_encorex"):
                    search_info["pending_encorex"]    = True
                    search_info["encorex_wait_start"] = time.time()
                return

            # ── IntelX multi-message accumulation ─────────────────────────────
            # IntelX sends 3 separate messages:
            #   Msg 1: summary header ("Breached: 🔎Request: ...")  → NOT the data
            #   Msg 2: masked data lines (Telephone, Adres, Full name, ...)  → DATA
            #   Msg 3: "Your subscription is over!" footer  → ignore/skip
            text_lower_ps = text.lower()

            intelx_footer_only = any(sig in text_lower_ps for sig in [
                'subscription is over', 'trial period lasted',
                '/shop', '/referral', '/mirrors',
                'buying a subscription reduces',
            ])
            intelx_header_only = any(sig in text_lower_ps for sig in [
                'breached:', '🔎request:', 'subjects made:',
                'number of results:', 'number of leaks:', 'search time:',
                'free version of the bot', 'mirror',
            ]) and '█' not in text  # header has no masked data

            if intelx_footer_only:
                # Footer message — the actual data was (or will be) a separate message
                # If we already have accumulated data, resolve now
                accumulated = search_info.get("intelx_accumulated", "")
                if accumulated and search_id in self.active_searches:
                    logger.info(f"✅ IntelX footer received — resolving with accumulated data")
                    result = await self._process_text(accumulated, search_info)
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result(result)
                    del self.active_searches[search_id]
                else:
                    # Footer arrived but no data yet — keep waiting briefly
                    logger.info(f"⏭️ IntelX footer — no data yet, keep waiting")
                    if not search_info.get("pending_encorex"):
                        search_info["pending_encorex"]    = True
                        search_info["encorex_wait_start"] = time.time()
                return

            if intelx_header_only:
                # Header message — mark that IntelX data is coming next
                logger.info(f"📋 IntelX header received — data message(s) expected next")
                search_info["intelx_pending"]     = True
                search_info["intelx_accumulated"] = ""
                if not search_info.get("pending_encorex"):
                    search_info["pending_encorex"]    = True
                    search_info["encorex_wait_start"] = time.time()
                return

            # If this looks like IntelX masked data, accumulate it
            is_intelx_data = (
                '█' in text
                or any(sig in text_lower_ps for sig in [
                    'telephone', 'adres', 'full name',
                    'the name of the father', 'region',
                    'encrypted password', 'date of registration',
                ])
            )
            if is_intelx_data and search_info.get("intelx_pending"):
                prev = search_info.get("intelx_accumulated", "")
                search_info["intelx_accumulated"] = (prev + "\n\n" + text).strip()
                logger.info(
                    f"📥 IntelX data chunk accumulated "
                    f"({len(search_info['intelx_accumulated'])} chars total)"
                )
                # ── IntelX inline keyboard pagination (edit-based) ───────
                # The IntelX bot paginates by EDITING its own message in-place.
                # Each edit replaces the text with the next result page.
                # We track the bot's message_id; MessageEdited events re-enter
                # this handler.  When the edited message no longer has a ➡️ button
                # (last page), we stop accumulating and let the footer resolve us.
                try:
                    msg_id  = getattr(message, "id", None)
                    buttons = getattr(message, "buttons", None)
                    has_next = False
                    if buttons:
                        for row in buttons:
                            for btn in row:
                                btn_text = getattr(btn, "text", "") or ""
                                if any(arrow in btn_text for arrow in ("➡", "→", "Next", "next")):
                                    has_next = True
                                    break
                            if has_next:
                                break
                    # Record this message's id so edits are matched back here
                    if msg_id and not search_info.get("intelx_paged_msg_id"):
                        search_info["intelx_paged_msg_id"] = msg_id
                    if has_next:
                        # More pages coming via future edits — keep waiting
                        logger.info(
                            f"⏭️ IntelX page received (msg_id={msg_id}) — "
                            f"➡️ button present, waiting for next edit"
                        )
                        search_info["pending_encorex"]    = True
                        search_info["encorex_wait_start"] = time.time()
                        return  # wait for the next edited message
                    else:
                        # No ➡️ button — this is the final page; fall through to resolve
                        logger.info(
                            f"✅ IntelX final page received (msg_id={msg_id}) — "
                            f"no more pages, resolving with accumulated data"
                        )
                except Exception as _btn_err:
                    logger.warning(f"⚠️ IntelX pagination check failed: {_btn_err}")
                # ── End pagination ─────────────────────────────
                # Final page (or no pagination): resolve immediately with all accumulated data
                all_data = search_info.get("intelx_accumulated", "")
                if all_data and search_id in self.active_searches:
                    logger.info(
                        f"✅ IntelX all pages collected — resolving "
                        f"({len(all_data)} chars)"
                    )
                    result = await self._process_text(all_data, search_info)
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result(result)
                    del self.active_searches[search_id]
                else:
                    # No accumulated data yet — keep waiting
                    if not search_info.get("pending_encorex"):
                        search_info["pending_encorex"]    = True
                        search_info["encorex_wait_start"] = time.time()
                return

            # ── No-info / result decision ──────────────────────────────────────
            came_after_scan = search_info.pop("_came_after_scan", False)

            # Check if we have accumulated IntelX data to use instead
            accumulated_intelx = search_info.get("intelx_accumulated", "")
            if accumulated_intelx and TextProcessor.is_no_info_message(text):
                logger.info(f"✅ Using accumulated IntelX data instead of no-info message")
                result = await self._process_text(accumulated_intelx, search_info)
            elif TextProcessor.is_no_info_message(text) and not came_after_scan:
                logger.info(f"🚫 No-info message")
                result = {"success": False}
            elif text and len(text.strip()) > 10:
                # If we have IntelX accumulated data AND new data, merge them
                if accumulated_intelx and is_intelx_data:
                    merged = accumulated_intelx
                    logger.info(f"📝 Using accumulated IntelX data ({len(merged)} chars)")
                else:
                    merged = text
                result = await self._process_text(merged, search_info)
            else:
                logger.info(f"⚠️ Empty or short message, ignoring")
                return

            # ── Multi-collect: accumulate candidate instead of resolving early ──
            if search_info.get("multi_collect") and search_id in self.active_searches:
                if result.get("success"):
                    score = _score_result_richness(
                        result.get("result") or result.get("content") or text
                    )
                    search_info["candidates"].append((score, result))
                    logger.info(
                        f"📥 Multi-collect candidate added "
                        f"(score={score}, total={len(search_info['candidates'])}) "
                        f"for {search_info['search_type']}/{search_info['query']}"
                    )
                # Do NOT resolve future — polling loop will pick best after 8s
                return

            # ── Normal mode: resolve future immediately ──────────────────────
            if search_id in self.active_searches:
                # BASIC DB: if result failed validity, do NOT kill the search —
                # other users' results post into the same shared group constantly.
                # Keep the entry alive so we can catch the *real* matching reply
                # that arrives a moment later.
                if search_info.get("basic_db") and not result.get("success"):
                    logger.info(
                        f"⏳ [{search_info['group']['name']}] basic_db: "
                        f"message matched query but failed validity — keeping entry, waiting for valid reply"
                    )
                    return  # do NOT resolve future or delete entry
                future = self.active_searches[search_id]["future"]
                if not future.done():
                    future.set_result(result)
                del self.active_searches[search_id]
                
        except Exception as e:
            logger.error(f"❌ Error processing search response: {e}")
    
    def _is_encorex_scanning_message(self, text: str) -> bool:
        """Return True ONLY for ENCOREX TUNNEL scanning/processing placeholders.
        
        SCANNING (return True):
            🛰️ ENCOREX TUNNEL
            ╔════════════════════════════╗
            ║ 🔍 scanning...
            ║ 📡 service: NUM
            ║ 🖥️ node: ip-172-31-24-227
            ╚════════════════════════════╝

        RESULT (return False — even if small):
            🛡️ ENCOREX OSINT / ENCOREX INTELX
            ╔═══《 ... 》═══╗
            ║  ✅ SUCCESS
            ║  { ... JSON ... }
            ╚════════════════════════════╝
            ╘══《 ⚡ ...ms  ⏳ ...s 》══╛
        """
        if not text or len(text.strip()) < 5:
            return False

        text_lower = text.lower()

        # ── RULE 1: ENCOREX OSINT / INTELX result frames are NEVER scanning ──
        # These contain the result header with timing footer
        if ('encorex osint' in text_lower or 'encorex intelx' in text_lower
                or '╔═══《' in text or '╘══《' in text):
            return False

        # ── RULE 2: Any message with real data fields is a result ─────────────
        result_data_indicators = [
            '"success":', '"status":', '"result":', '"results":',
            '"country":', '"number":', '"mobile":', '"name":',
            '"address":', '"aadhar":', '"fname":', '"circle":',
            '"msg":', '"_powered_by":', '"email":', '"alt":',
            '✅ success', '✅ found',
        ]
        if any(ind in text_lower for ind in result_data_indicators):
            return False

        # JSON with 3+ key-value pairs → definitely a result
        if text_lower.count('": ') >= 3:
            return False

        # ── RULE 3: ENCOREX TUNNEL scanning pattern — ALL THREE must be present ──
        has_tunnel   = 'encorex tunnel' in text_lower or 'intelx tunnel' in text_lower
        has_scanning = 'scanning' in text_lower
        has_service  = '📡 service:' in text or 'service:' in text_lower
        has_node     = '🖥️' in text or 'node:' in text_lower

        # Must have tunnel branding OR (scanning + service/node)
        if has_tunnel:
            logger.info("🚫 ENCOREX TUNNEL branding detected — scanning message")
            return True
        if has_scanning and (has_service or has_node):
            logger.info("🚫 scanning + service/node pattern — scanning message")
            return True

        # ── Also catch DarkBoxes own "Searching..." confirmation messages ──────
        # e.g. "🔍 **Searching...**\n`9939353201`\n⚡ Powered by DarkBoxes..."
        if ('searching...' in text_lower or '🔍 **searching' in text_lower
                or '🔎 searching' in text_lower or 'powered by darkboxes' in text_lower):
            # Only if there's no real data present
            if not any(ind in text_lower for ind in [
                '"success":', '"number":', '"name":', '"address":',
                'name:', 'mobile:', 'operator:', 'circle:', '✅'
            ]):
                logger.info("🚫 DarkBoxes searching confirmation — placeholder message")
                return True

        return False
    
    async def _process_leak_response(self, search_id: str, search_info: Dict, message):
        """Process leak search response"""
        try:
            # First, check if this is a file
            file_result = await self._check_and_process_file(message, search_info)
            
            if file_result is not None:
                logger.info(f"📁 Processing leak search file")
                
                # Check if we've already processed this file (prevent duplicate processing)
                message_id = message.id
                if "processed_files" not in search_info:
                    search_info["processed_files"] = []
                
                if message_id in search_info["processed_files"]:
                    logger.info(f"⚠️ Already processed file with ID {message_id}, skipping")
                    return
                
                search_info["processed_files"].append(message_id)
                
                # Add file to received files
                if "files_received" not in search_info:
                    search_info["files_received"] = []
                
                # Determine file type
                filename = ""
                if hasattr(message.file, 'name') and message.file.name:
                    filename = message.file.name.lower()
                elif hasattr(message, 'file') and message.file and hasattr(message.file, 'name'):
                    filename = message.file.name.lower()
                
                file_type = "unknown"
                if '.json' in filename:
                    file_type = "json"
                elif '.txt' in filename:
                    file_type = "txt"
                elif '.text' in filename:
                    file_type = "txt"
                elif 'json' in filename:
                    file_type = "json"
                
                file_result["file_type"] = file_type
                file_result["message_id"] = message_id
                search_info["files_received"].append(file_result)
                
                logger.info(f"✅ Added {file_type} file to leak search results. Total files: {len(search_info['files_received'])}")
                
                # Check if we should complete the search
                received_types = [f["file_type"] for f in search_info["files_received"]]
                has_json = "json" in received_types
                has_txt = "txt" in received_types
                has_enough_files = len(search_info["files_received"]) >= 2
                time_elapsed = time.time() - search_info["start_time"]
                
                # Complete if we have both file types OR enough files OR timeout
                if (has_json and has_txt) or has_enough_files or time_elapsed > 10:
                    await self._complete_leak_search(search_id, search_info)
                return
            
            # Check for text message that might be a TXT file content
            text = message.text or message.raw_text or ""
            
            # Check if this looks like a TXT file result
            is_txt_result = False
            
            # Patterns that indicate this is a TXT file result
            txt_patterns = [
                r'Full results available as JSON file',
                r'📁 Full JSON results for',
                r'Service: leak',
                r'Requested by:',
                r'───────────────────────',
                r'━━━━━━━━━━━━━━━━━━━━━━━━',
                r'Total length: \d+ characters',
                r'\.\.\. \[TRUNCATED - DATA TOO LONG\] \.\.\.',
                r'👤 ʀᴇǫᴜᴇꜱᴛᴇᴅ ʙʏ:',
                r'🔍 ǫᴜᴇʀʏ:',
                r'⏰ ᴛɪᴍᴇ:'
            ]
            
            # Check if text contains TXT result patterns
            pattern_count = 0
            for pattern in txt_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    pattern_count += 1
            
            # If at least 3 patterns match, consider it a TXT file
            if pattern_count >= 3 and len(text) > 500:
                is_txt_result = True
                logger.info(f"📄 Detected TXT file content in message (matched {pattern_count} patterns)")
            
            if text and (is_txt_result or len(text.strip()) > 1000):
                logger.info(f"📝 Processing text message as potential TXT file ({len(text)} chars)")
                
                # Check if we've already processed this message
                message_id = message.id
                if "processed_files" not in search_info:
                    search_info["processed_files"] = []
                
                if message_id in search_info["processed_files"]:
                    logger.info(f"⚠️ Already processed message with ID {message_id}, skipping")
                    return
                
                search_info["processed_files"].append(message_id)
                
                # Create a file result from the text
                txt_result = {
                    "success": True,
                    "has_file": True,
                    "content": text,
                    "raw_bytes": text.encode('utf-8'),
                    "file_type": "txt",
                    "filename": f"leak_{search_info['query']}_{int(time.time())}.txt",
                    "message_id": message_id,
                    "is_text_message": True
                }
                
                # Add to received files
                if "files_received" not in search_info:
                    search_info["files_received"] = []
                
                search_info["files_received"].append(txt_result)
                logger.info(f"✅ Added TXT content from message to leak search results. Total files: {len(search_info['files_received'])}")
                
                # Check if we should complete the search
                received_types = [f["file_type"] for f in search_info["files_received"]]
                has_json = "json" in received_types
                has_txt = "txt" in received_types
                has_enough_files = len(search_info["files_received"]) >= 2
                time_elapsed = time.time() - search_info["start_time"]
                
                # Complete if we have both file types OR enough files OR timeout
                if (has_json and has_txt) or has_enough_files or time_elapsed > 10:
                    await self._complete_leak_search(search_id, search_info)
                return
            
            # Check for processing or no-info messages
            if TextProcessor.is_processing_message(text):
                logger.info(f"⏳ Processing message for leak search")
                return
            
            if TextProcessor.is_no_info_message(text):
                logger.info(f"🚫 No info for leak search")
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result({"success": False})
                    del self.active_searches[search_id]
            
        except Exception as e:
            logger.error(f"❌ Error processing leak response: {e}")
    
    async def _complete_leak_search(self, search_id: str, search_info: Dict):
        """Complete leak search and send results"""
        try:
            logger.info(f"✅ Completing leak search with {len(search_info.get('files_received', []))} files")
            
            if "files_received" not in search_info or not search_info["files_received"]:
                logger.warning("⚠️ No files received for leak search")
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result({
                            "success": False,
                            "error": "❌ No results found in our advanced databases."
                        })
                    del self.active_searches[search_id]
                return
            
            # Combine results
            combined_result = {
                "success": True,
                "result": "🚀 **ADVANCED OSINT SEARCH COMPLETE**\n\n",
                "files": search_info["files_received"],
                "has_multiple_files": len(search_info["files_received"]) > 1
            }
            
            # Create summary
            json_data = None
            txt_data = None
            
            for file in search_info["files_received"]:
                if file["file_type"] == "json" and json_data is None:
                    json_data = file.get("content", "")
                elif file["file_type"] == "txt" and txt_data is None:
                    txt_data = file.get("content", "")
            
            # Format result summary
            summary = f"🔮 **ADVANCED UNIVERSAL SEARCH RESULT**\n"
            summary += f"═══════════════════════════════════\n\n"
            summary += f"🔍 **Query:** `{search_info['query']}`\n"
            summary += f"🚀 **Source:** Advanced OSINT Engine\n"
            summary += f"⚡ **Files Found:** {len(search_info['files_received'])}\n"
            
            if json_data and txt_data:
                summary += f"📊 **Includes:** JSON + TXT files\n\n"
            elif json_data:
                summary += f"📊 **Includes:** JSON file\n\n"
            elif txt_data:
                summary += f"📊 **Includes:** TXT file\n\n"
            
            if txt_data:
                # Extract preview from TXT data
                txt_preview = txt_data[:300].replace('\n', '\n')
                summary += f"📄 **PREVIEW:**\n"
                summary += f"─────────────────────────────\n"
                summary += f"{txt_preview}\n"
                if len(txt_data) > 300:
                    summary += f"... (see full TXT file below)\n\n"
            
            summary += f"📁 **Files available for download below**\n"
            summary += f"⚡ **Powered by DarkBoxes Advanced Intelligence**\n"
            
            combined_result["result"] = summary
            
            if search_id in self.active_searches:
                future = self.active_searches[search_id]["future"]
                if not future.done():
                    future.set_result(combined_result)
                del self.active_searches[search_id]
                logger.info(f"✅ Leak search completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Error completing leak search: {e}")
            if search_id in self.active_searches:
                future = self.active_searches[search_id]["future"]
                if not future.done():
                    future.set_result({"success": False})
                del self.active_searches[search_id]
    
    async def _process_file(self, message, search_info: Dict) -> Dict:
        """Process file message"""
        try:
            if hasattr(message.file, 'size') and message.file.size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
                logger.warning(f"📁 File too large: {message.file.size} bytes")
                return {"success": False}
            
            logger.info(f"⬇️ Downloading file from {search_info['group']['name']}")
            file_bytes = await message.download_media(bytes)
            
            if not file_bytes:
                logger.error("❌ Failed to download file")
                return {"success": False}
            
            content = None
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for encoding in encodings:
                try:
                    content = file_bytes.decode(encoding)
                    logger.info(f"✅ Decoded with {encoding}")
                    break
                except UnicodeDecodeError:
                    continue
            
            if not content:
                logger.error("❌ Could not decode file with any encoding")
                return {"success": False}
            
            # Clean content - remove usernames and links
            cleaned_content = TextProcessor.clean_content(content, search_info["search_type"])
            
            if len(cleaned_content.strip()) < 30:
                logger.warning(f"⚠️ Cleaned content too short: {len(cleaned_content)} chars")
                lines = content.split('\n')
                meaningful_lines = []
                for line in lines:
                    line = line.strip()
                    if len(line) > 10:
                        if not any(word in line.lower() for word in ['powered', 'developed', 'created', 'join', 'subscribe', 'channel', 'admin', '@', 't.me', 'http']):
                            meaningful_lines.append(line)
                
                if meaningful_lines:
                    cleaned_content = '\n'.join(meaningful_lines)
                    cleaned_content = TextProcessor.clean_content(cleaned_content, search_info["search_type"])
                else:
                    return {"success": False}
            
            result = {
                "success": True,
                "result": None,
                "has_file": True,
                "content": cleaned_content,
                "raw_bytes": file_bytes,
                "filename": message.file.name if hasattr(message.file, 'name') else f"result_{int(time.time())}.txt"
            }
            
            # For non-leak searches, format the result
            if search_info["search_type"] != "leak":
                formatted_result = PremiumFormatter.format_result(
                    cleaned_content,
                    search_info["search_type"],
                    search_info["query"],
                    search_info["group"]["name"]
                )
                result["result"] = formatted_result
            
            logger.info(f"✅ Processed file with {len(cleaned_content)} characters")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error processing file: {e}")
            return {"success": False}
    
    async def _process_text(self, text: str, search_info: Dict) -> Dict:
        """Process text message — handles ENCOREX OSINT frames and plain responses"""

        # Helper: strip ENCOREX/IntelX branding words from any string shown to users
        def _strip_branding(s: str) -> str:
            """Remove ENCOREX, INTELX, OSINT branding words from a display string"""
            s = re.sub(r'ENCOREX\s*(OSINT|INTELX|TUNNEL)?', '', s, flags=re.IGNORECASE).strip()
            s = re.sub(r'INTELX\s*(OSINT|TUNNEL)?', '', s, flags=re.IGNORECASE).strip()
            s = re.sub(r'\bINTELX\b', '', s, flags=re.IGNORECASE).strip()
            s = re.sub(r'\s{2,}', ' ', s).strip(' -|:')
            return s

        # ── Detect ENCOREX OSINT / INTELX result frame ───────────────────────
        # Frame format:
        #   🛡️ ENCOREX OSINT  ← header line (branding — strip this)
        #   ╔═══《 CMD 》═══╗
        #   ║  ✅ SUCCESS
        #   ║  { ...JSON... }
        #   ╚════════════════════════════╝
        #   ╘══《 ⚡ Xms  ⏳ Ys 》══╛   ← timing footer (strip this)
        text_lower = text.lower()
        is_encorex_frame = (
            ('encorex osint' in text_lower or 'encorex intelx' in text_lower
             or '╔═══《' in text or '╘══《' in text)
            and ('✅' in text or '"' in text)
        )

        if is_encorex_frame:
            # Extract the JSON block between the first { and last }
            json_start = text.find('{')
            json_end   = text.rfind('}')
            extracted_json = ""

            if json_start != -1 and json_end > json_start:
                raw_json = text[json_start:json_end + 1].strip()
                try:
                    parsed_data = json.loads(raw_json)
                    # Remove _powered_by and similar internal fields before showing user
                    if isinstance(parsed_data, dict):
                        parsed_data.pop('_powered_by', None)
                        parsed_data.pop('powered_by', None)
                        # If there's a nested result list, clean each entry
                        if isinstance(parsed_data.get('result'), list):
                            for item in parsed_data['result']:
                                if isinstance(item, dict):
                                    item.pop('_powered_by', None)
                        if isinstance(parsed_data.get('results'), list):
                            for item in parsed_data['results']:
                                if isinstance(item, dict):
                                    item.pop('_powered_by', None)
                    extracted_json = json.dumps(parsed_data, indent=2, ensure_ascii=False)
                    logger.info(f"✅ Extracted clean JSON from ENCOREX frame ({len(extracted_json)} chars)")
                except json.JSONDecodeError:
                    extracted_json = raw_json
                    logger.info(f"⚠️ Raw JSON from ENCOREX frame ({len(extracted_json)} chars)")

            if not extracted_json or len(extracted_json.strip()) < 5:
                logger.info(f"⚠️ ENCOREX frame but no JSON — using cleaned full text")
                extracted_json = TextProcessor.clean_content(text, search_info["search_type"])

            # Use cleaned group name (no ENCOREX/INTELX branding shown to user)
            clean_source = _strip_branding(search_info["group"]["name"])
            if not clean_source:
                clean_source = "Intelligence Source"

            # Validity check for ENCOREX frame results too
            if not TextProcessor.is_valid_result(extracted_json, search_info["search_type"]):
                logger.info(f"⚠️ ENCOREX frame failed validity check for {search_info['search_type']}")
                return {"success": False}

            formatted = PremiumFormatter.format_result(
                extracted_json,
                search_info["search_type"],
                search_info["query"],
                clean_source
            )
            return {"success": True, "result": formatted, "raw_result": extracted_json, "has_file": False}

        # ── "NUMBER TO DETAILS:" JSON array format (Basic DB group) ──────────
        # Format: "NUMBER TO DETAILS:\n[{...}]"  or  "[{...}]" alone
        # The JSON is an array; extract and pretty-print it.
        if 'number to details' in text_lower or (text_lower.strip().startswith('[{') and '"mobile"' in text_lower):
            arr_start = text.find('[')
            arr_end   = text.rfind(']')
            if arr_start != -1 and arr_end > arr_start:
                raw_arr = text[arr_start:arr_end + 1].strip()
                try:
                    parsed = json.loads(raw_arr)
                    # Remove internal/powered_by fields
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict):
                                item.pop('_powered_by', None)
                                item.pop('powered_by', None)
                    elif isinstance(parsed, dict):
                        parsed.pop('_powered_by', None)
                        parsed.pop('powered_by', None)
                    extracted_json = json.dumps(parsed, indent=2, ensure_ascii=False)
                    logger.info(f"✅ Extracted JSON array from NUMBER TO DETAILS format ({len(extracted_json)} chars)")
                except json.JSONDecodeError:
                    extracted_json = raw_arr
                    logger.info(f"⚠️ Raw JSON array from NUMBER TO DETAILS ({len(extracted_json)} chars)")

                if extracted_json and len(extracted_json.strip()) >= 5:
                    clean_source = _strip_branding(search_info["group"]["name"])
                    if not clean_source:
                        clean_source = "Intelligence Source"
                    if not TextProcessor.is_valid_result(extracted_json, search_info["search_type"]):
                        # Still valid if it contains mobile/name — force accept
                        if '"mobile"' in extracted_json or '"name"' in extracted_json:
                            pass  # proceed
                        else:
                            logger.info(f"⚠️ NUMBER TO DETAILS array failed validity check")
                            return {"success": False}
                    formatted = PremiumFormatter.format_result(
                        extracted_json,
                        search_info["search_type"],
                        search_info["query"],
                        clean_source
                    )
                    return {"success": True, "result": formatted, "raw_result": extracted_json, "has_file": False}

        cleaned = TextProcessor.clean_content(text, search_info["search_type"])

        if len(cleaned) < 20:
            return {"success": False}

        # ── Validity check: ensure response actually contains expected data fields ──
        search_type = search_info.get("search_type", "")
        if not TextProcessor.is_valid_result(cleaned, search_type):
            logger.info(f"⚠️ [{search_info['group']['name']}] Response failed validity check for {search_type}")
            return {"success": False}

        # Strip branding from source name for non-frame responses too
        clean_source = _strip_branding(search_info["group"]["name"])
        if not clean_source:
            clean_source = "Intelligence Source"

        formatted = PremiumFormatter.format_result(
            cleaned,
            search_info["search_type"],
            search_info["query"],
            clean_source
        )

        return {
            "success": True,
            "result": formatted,
            "raw_result": cleaned,   # unformatted — used for masking
            "has_file": False
        }
    
    async def _notify_admin(self, user_id: int, search_type: str, query: str):
        """Notify admin about failed search"""
        try:
            user_info = await self.user_manager.get_user(user_id)
            username = user_info.get('username', 'N/A') if user_info else 'N/A'
            first_name = user_info.get('first_name', 'N/A') if user_info else 'N/A'
            
            admin_msg = (
                f"🚨 **FAILED SEARCH ALERT**\n\n"
                f"👤 User: {first_name} (@{username})\n"
                f"🆔 ID: `{user_id}`\n"
                f"🔍 Type: {search_type}\n"
                f"📝 Query: `{query}`\n"
                f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
                f"💡 Use `/reply {user_id} [message]` to send result"
            )
            
            await bot_client.send_message(config.ADMIN_USER_ID, admin_msg, parse_mode="md")
            logger.info(f"📋 Notified admin about {search_type}={query}")
            
        except Exception as e:
            logger.error(f"❌ Error notifying admin: {e}")

# ================== CLEANUP TASK ==================

async def cleanup_expired_searches():
    """Clean up expired searches"""
    while True:
        try:
            await asyncio.sleep(30)
            
            current_time = time.time()
            expired = []
            
            for search_id, search_info in list(search_engine.active_searches.items()):
                timeout = search_info["group"]["timeout"]
                
                if search_info.get("expecting_file") and search_info.get("file_wait_start"):
                    file_wait_time = current_time - search_info["file_wait_start"]
                    if file_wait_time < 20:
                        continue
                    else:
                        logger.info(f"⏱️ File wait timeout in {search_info['group']['name']}")
                
                if current_time - search_info["start_time"] > timeout:
                    expired.append(search_id)
            
            for search_id in expired:
                search_info = search_engine.active_searches.pop(search_id, None)
                if search_info:
                    future = search_info["future"]
                    if not future.done():
                        try:
                            future.set_result({"success": False})
                        except:
                            pass
                    logger.info(f"🧹 Cleaned expired search: {search_id}")
            
            if expired:
                logger.info(f"🧹 Cleaned {len(expired)} expired searches")
                
        except Exception as e:
            logger.error(f"❌ Error in cleanup: {e}")

# ================== WEB SERVER ==================

_WEB_SERVER_STARTED = False  # singleton guard — only one instance ever binds


# ══════════════════════════════════════════════════════════
# PAYMENT HELPERS  (UPI manual flow — Instamojo removed)
# All payments are now UPI → UTR submission → admin approval.
# ══════════════════════════════════════════════════════════






async def start_web_server():
    """Start unified web server with API endpoints.

    Singleton: if the port is already bound (e.g. after a bot reconnect),
    this coroutine parks itself forever so _safe_task does not spin-restart.

    Waits for DB to be connected before binding, so auth endpoints never
    hit db_manager.db = None.
    """
    global _WEB_SERVER_STARTED
    if _WEB_SERVER_STARTED:
        logger.info("🌐 Web server already running — skipping duplicate start.")
        await asyncio.Event().wait()  # park forever
        return

    # NOTE: _WEB_SERVER_STARTED is set to True AFTER site.start() succeeds
    # so the main() wait loop only exits once the port is truly bound.

    # ── Build app and bind port ────────────────────────────────────


    # ── CORS middleware (must be passed at construction, not appended after) ──
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key'
        return response

    app = web.Application(middlewares=[cors_middleware])

    # Health check endpoint
    async def health_check(request):
        db_ok = db_manager.db is not None
        return web.json_response({
            "status": "ok" if db_ok else "starting",
            "db": "connected" if db_ok else "initialising",
            "timestamp": datetime.now().isoformat()
        })

    # Root handler — Render pings GET / to check liveness
    # NOTE: do NOT add HEAD separately — aiohttp auto-creates HEAD for every GET
    async def root_handler(request):
        return web.json_response({"status": "ok", "service": "DarkBoxes Relay"})

    # Basic routes
    app.router.add_get('/',  root_handler)
    app.router.add_get('/health', health_check)
    app.router.add_get('/api/v1/health', health_check)

    # Add API endpoints if enabled
    if config.API_ENABLED:

        # NOTE: Do NOT create a local api_handler here — search_engine is None at
        # this point. Instead, each search endpoint calls the GLOBAL api_handler
        # which is set in _run_bot() after search_engine is initialized.
        # Auth endpoints (login/register) access db_manager.db directly — safe
        # because we waited above.
        
        # Search endpoints — use GLOBAL api_handler (set after DB+search_engine init)
        # Guard: return 503 if still initialising (port is bound but DB not ready yet)
        async def _api_guard(request, search_type):
            if api_handler is None or db_manager.db is None:
                return web.json_response(
                    {"status": "error", "message": "Service is starting up, retry in a few seconds."},
                    status=503
                )
            return await api_handler.handle_search_request(request, search_type)

        async def phone_search(request):
            return await _api_guard(request, "phone")

        async def family_search(request):
            return await _api_guard(request, "family")

        async def aadhar_search(request):
            return await _api_guard(request, "aadhar")

        async def vehicle_search(request):
            return await _api_guard(request, "vehicle")

        async def upi_search(request):
            return await _api_guard(request, "upi")

        async def email_search(request):
            return await _api_guard(request, "email")

        async def telegram_search(request):
            return await _api_guard(request, "telegram")

        async def imei_search(request):
            return await _api_guard(request, "imei")

        async def gst_search(request):
            return await _api_guard(request, "gst")

        async def instagram_search(request):
            return await _api_guard(request, "insta")

        async def pakistan_search(request):
            return await _api_guard(request, "pak")

        async def ip_search(request):
            return await _api_guard(request, "ip")

        async def ifsc_search(request):
            return await _api_guard(request, "ifsc")

        async def leak_search(request):
            return await _api_guard(request, "leak")
        
        # Utility endpoints
        async def batch_search(request):
            return await api_handler.handle_batch_search(request)
        
        async def status_endpoint(request):
            return await api_handler.handle_status_request(request)
        
        async def balance_endpoint(request):
            return await api_handler.handle_balance_request(request)
        
        async def usage_endpoint(request):
            return await api_handler.handle_usage_request(request)
        
        # Documentation endpoint
        async def documentation(request):
            docs = {
                "service": "DarkBoxes Intelligence API",
                "version": "2.0.0",
                "base_url": config.API_BASE_URL,
                "endpoints": {
                    "search": {
                        "phone": {"method": "POST", "endpoint": "/api/v1/search/phone"},
                        "family": {"method": "POST", "endpoint": "/api/v1/search/family"},
                        "aadhar": {"method": "POST", "endpoint": "/api/v1/search/aadhar"},
                        "vehicle": {"method": "POST", "endpoint": "/api/v1/search/vehicle"},
                        "upi": {"method": "POST", "endpoint": "/api/v1/search/upi"},
                        "email": {"method": "POST", "endpoint": "/api/v1/search/email"},
                        "telegram": {"method": "POST", "endpoint": "/api/v1/search/telegram"},
                        "imei": {"method": "POST", "endpoint": "/api/v1/search/imei"},
                        "gst": {"method": "POST", "endpoint": "/api/v1/search/gst"},
                        "instagram": {"method": "POST", "endpoint": "/api/v1/search/instagram"},
                        "pakistan": {"method": "POST", "endpoint": "/api/v1/search/pakistan"},
                        "ip": {"method": "POST", "endpoint": "/api/v1/search/ip"},
                        "ifsc": {"method": "POST", "endpoint": "/api/v1/search/ifsc"},
                        "leak": {"method": "POST", "endpoint": "/api/v1/search/leak"},
                        "batch": {"method": "POST", "endpoint": "/api/v1/search/batch"}
                    },
                    "utility": {
                        "status": {"method": "GET", "endpoint": "/api/v1/status"},
                        "balance": {"method": "GET", "endpoint": "/api/v1/balance"},
                        "usage": {"method": "GET", "endpoint": "/api/v1/usage"}
                    }
                },
                "authentication": {
                    "header": "X-API-Key: your_api_key",
                    "query_param": "?api_key=your_api_key"
                },
                "contact": {
                    "admin": "@darkboxesAdmin",
                    "channel": "@darkboxesv1"
                }
            }
            return web.json_response(docs)
        

        # Add API routes
        app.router.add_post('/api/v1/search/phone', phone_search)
        app.router.add_post('/api/v1/search/family', family_search)
        app.router.add_post('/api/v1/search/aadhar', aadhar_search)
        app.router.add_post('/api/v1/search/vehicle', vehicle_search)
        app.router.add_post('/api/v1/search/upi', upi_search)
        app.router.add_post('/api/v1/search/email', email_search)
        app.router.add_post('/api/v1/search/telegram', telegram_search)
        app.router.add_post('/api/v1/search/imei', imei_search)
        app.router.add_post('/api/v1/search/gst', gst_search)
        app.router.add_post('/api/v1/search/instagram', instagram_search)
        app.router.add_post('/api/v1/search/pakistan', pakistan_search)
        app.router.add_post('/api/v1/search/ip', ip_search)
        app.router.add_post('/api/v1/search/ifsc', ifsc_search)
        app.router.add_post('/api/v1/search/leak', leak_search)
        app.router.add_post('/api/v1/search/batch', batch_search)
        
        # Utility endpoints
        app.router.add_get('/api/v1/status', status_endpoint)
        app.router.add_get('/api/v1/balance', balance_endpoint)
        app.router.add_get('/api/v1/usage', usage_endpoint)
        app.router.add_get('/api/v1/docs', documentation)
        
        # ── Web Admin Panel endpoints ────────────────────────────────────────
        import hashlib as _hashlib

        def _web_admin_auth(request) -> bool:
            """Check Bearer token or ?token= against WEB_ADMIN_PASSWORD."""
            pwd = config.WEB_ADMIN_PASSWORD or config.API_SECRET_KEY
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                return auth[7:] == pwd
            return request.rel_url.query.get("token", "") == pwd

        async def web_admin_stats(request):
            if not _web_admin_auth(request):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                today_stats   = await db_manager.admin_db.get_today_stats()
                cmd_stats     = await db_manager.admin_db.get_command_stats()
                payment_stats = await db_manager.admin_db.get_payment_stats()
                total_users   = await asyncio.get_running_loop().run_in_executor(
                    None, db_manager.db.users.count_documents, {}
                )
                total_searches = await asyncio.get_running_loop().run_in_executor(
                    None, db_manager.db.search_logs.count_documents, {}
                )
                success_count = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: db_manager.db.search_logs.count_documents({"success": True})
                )
                fail_count = total_searches - success_count
                return web.json_response({
                    "today": today_stats,
                    "commands": cmd_stats,
                    "payments": payment_stats,
                    "totals": {
                        "users": total_users,
                        "searches": total_searches,
                        "success": success_count,
                        "failed": fail_count,
                        "success_rate": round(success_count / max(total_searches, 1) * 100, 1),
                    }
                }, dumps=lambda o: __import__("json").dumps(o, default=str))
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def web_admin_users(request):
            if not _web_admin_auth(request):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                page  = int(request.rel_url.query.get("page", 1))
                limit = int(request.rel_url.query.get("limit", 25))
                q     = request.rel_url.query.get("q", "")
                if q:
                    users = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: list(db_manager.db.users.find(
                            {"$or": [
                                {"username": {"$regex": q, "$options": "i"}},
                                {"first_name": {"$regex": q, "$options": "i"}},
                            ]},
                            {"_id": 0, "user_id": 1, "username": 1, "first_name": 1,
                             "joined_at": 1, "total_searches": 1, "searches_remaining": 1,
                             "subscription": 1, "subscription_expiry": 1, "is_banned": 1, "is_admin": 1}
                        ).limit(limit))
                    )
                    return web.json_response({"users": users, "total": len(users)},
                                             dumps=lambda o: __import__("json").dumps(o, default=str))
                skip  = (page - 1) * limit
                users = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: list(db_manager.db.users.find(
                        {},
                        {"_id": 0, "user_id": 1, "username": 1, "first_name": 1,
                         "joined_at": 1, "total_searches": 1, "searches_remaining": 1,
                         "subscription": 1, "subscription_expiry": 1, "is_banned": 1, "is_admin": 1}
                    ).sort("joined_at", -1).skip(skip).limit(limit))
                )
                total = await asyncio.get_running_loop().run_in_executor(
                    None, db_manager.db.users.count_documents, {}
                )
                return web.json_response(
                    {"users": users, "total": total, "page": page,
                     "pages": (total + limit - 1) // limit},
                    dumps=lambda o: __import__("json").dumps(o, default=str)
                )
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def web_admin_user_action(request):
            if not _web_admin_auth(request):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                body   = await request.json()
                action = body.get("action")
                uid    = int(body.get("user_id", 0))
                if not uid:
                    return web.json_response({"error": "user_id required"}, status=400)
                if action == "add_credits":
                    amount = int(body.get("amount", 0))
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: db_manager.db.users.update_one(
                            {"user_id": uid}, {"$inc": {"searches_remaining": amount}}
                        )
                    )
                    return web.json_response({"ok": True, "added": amount})
                elif action == "ban":
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: db_manager.db.users.update_one(
                            {"user_id": uid}, {"$set": {"is_banned": True}}
                        )
                    )
                    return web.json_response({"ok": True})
                elif action == "unban":
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: db_manager.db.users.update_one(
                            {"user_id": uid}, {"$set": {"is_banned": False}}
                        )
                    )
                    return web.json_response({"ok": True})
                elif action == "give_subscription":
                    plan_id = body.get("plan_id", "sub_all_monthly")
                    days    = int(body.get("days", 30))
                    expiry  = (datetime.now(timezone.utc) + __import__("datetime").timedelta(days=days)).isoformat()
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: db_manager.db.users.update_one(
                            {"user_id": uid},
                            {"$set": {"subscription": plan_id, "subscription_expiry": expiry}}
                        )
                    )
                    return web.json_response({"ok": True, "expiry": expiry})
                elif action == "remove_subscription":
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: db_manager.db.users.update_one(
                            {"user_id": uid},
                            {"$unset": {"subscription": "", "subscription_expiry": ""}}
                        )
                    )
                    return web.json_response({"ok": True})
                else:
                    return web.json_response({"error": "unknown action"}, status=400)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def web_admin_logs(request):
            if not _web_admin_auth(request):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                limit  = int(request.rel_url.query.get("limit", 100))
                uid    = request.rel_url.query.get("user_id")
                stype  = request.rel_url.query.get("type")
                success_filter = request.rel_url.query.get("success")
                free_filter    = request.rel_url.query.get("free")
                flt: dict = {}
                if uid:
                    flt["user_id"] = int(uid)
                if stype:
                    flt["search_type"] = stype
                if success_filter is not None:
                    flt["success"] = success_filter.lower() == "true"
                if free_filter is not None:
                    flt["is_free_user"] = free_filter.lower() == "true"
                logs = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: list(db_manager.db.search_logs.find(
                        flt,
                        {"_id": 0, "user_id": 1, "search_type": 1, "query": 1,
                         "timestamp": 1, "success": 1, "credits_used": 1,
                         "response_preview": 1, "is_free_user": 1, "subscription_used": 1}
                    ).sort("timestamp", -1).limit(limit))
                )
                # Analytics
                total = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: db_manager.db.search_logs.count_documents(flt)
                )
                success_c = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: db_manager.db.search_logs.count_documents({**flt, "success": True})
                )
                fail_c = total - success_c
                return web.json_response({
                    "logs": logs,
                    "analytics": {
                        "total": total,
                        "success": success_c,
                        "failed": fail_c,
                        "success_rate": round(success_c / max(total, 1) * 100, 1),
                        "no_data_rate": round(fail_c / max(total, 1) * 100, 1),
                    }
                }, dumps=lambda o: __import__("json").dumps(o, default=str))
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def web_admin_groups(request):
            if not _web_admin_auth(request):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                groups_out = {}
                for key, g in GROUP_PRIORITIES.items():
                    groups_out[key] = {
                        "name": g.get("name"),
                        "enabled": g.get("enabled", True),
                        "identifier": g.get("identifier", ""),
                        "weight": g.get("weight", 0),
                        "commands": g.get("commands", {}),
                    }
                return web.json_response({
                    "groups": groups_out,
                    "validity_types": {k: v["label"] for k, v in VALIDITY_TYPES.items()},
                    "search_commands": {
                        k: {"validity_type": v.get("validity_type", "generic"), "cost": v.get("cost", 1)}
                        for k, v in SEARCH_COMMANDS.items()
                    },
                    "free_user_config": FREE_USER_CONFIG,
                })
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def web_admin_groups_update(request):
            if not _web_admin_auth(request):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                body = await request.json()
                action = body.get("action")
                if action == "set_group_command":
                    gkey   = body["group_key"]
                    stype  = body["search_type"]
                    cmd    = body.get("command", "")
                    if gkey in GROUP_PRIORITIES and stype in SEARCH_COMMANDS:
                        GROUP_PRIORITIES[gkey].setdefault("commands", {})[stype] = cmd
                        return web.json_response({"ok": True})
                    return web.json_response({"error": "unknown group or type"}, status=400)
                elif action == "toggle_group":
                    gkey = body["group_key"]
                    if gkey in GROUP_PRIORITIES:
                        GROUP_PRIORITIES[gkey]["enabled"] = not GROUP_PRIORITIES[gkey].get("enabled", True)
                        return web.json_response({"ok": True, "enabled": GROUP_PRIORITIES[gkey]["enabled"]})
                    return web.json_response({"error": "unknown group"}, status=400)
                elif action == "set_validity_type":
                    stype = body["search_type"]
                    vtype = body["validity_type"]
                    if stype in SEARCH_COMMANDS and vtype in VALIDITY_TYPES:
                        SEARCH_COMMANDS[stype]["validity_type"] = vtype
                        return web.json_response({"ok": True})
                    return web.json_response({"error": "unknown type"}, status=400)
                elif action == "set_free_user_config":
                    allowed_groups   = body.get("allowed_groups", [])
                    allowed_commands = body.get("allowed_commands", [])
                    FREE_USER_CONFIG["allowed_groups"]   = allowed_groups
                    FREE_USER_CONFIG["allowed_commands"] = allowed_commands
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: db_manager.db.bot_config.update_one(
                            {"_id": "free_user_config"},
                            {"$set": {"allowed_groups": allowed_groups, "allowed_commands": allowed_commands}},
                            upsert=True
                        )
                    )
                    return web.json_response({"ok": True})
                else:
                    return web.json_response({"error": "unknown action"}, status=400)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def web_admin_plans(request):
            if not _web_admin_auth(request):
                return web.json_response({"error": "unauthorized"}, status=401)
            return web.json_response({"plans": SUBSCRIPTION_PLANS},
                                     dumps=lambda o: __import__("json").dumps(o, default=str))

        async def web_admin_plans_update(request):
            if not _web_admin_auth(request):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                body    = await request.json()
                plan_id = body.get("plan_id")
                updates = body.get("updates", {})
                if plan_id not in SUBSCRIPTION_PLANS:
                    return web.json_response({"error": "unknown plan"}, status=400)
                SUBSCRIPTION_PLANS[plan_id].update(updates)
                return web.json_response({"ok": True, "plan": SUBSCRIPTION_PLANS[plan_id]},
                                         dumps=lambda o: __import__("json").dumps(o, default=str))
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def web_admin_broadcast(request):
            if not _web_admin_auth(request):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                body = await request.json()
                msg  = body.get("message", "").strip()
                if not msg:
                    return web.json_response({"error": "message required"}, status=400)
                all_users = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: list(db_manager.db.users.find({}, {"user_id": 1}))
                )
                sent = 0
                failed = 0
                for u in all_users:
                    try:
                        await bot_client.send_message(u["user_id"], msg, parse_mode="md")
                        sent += 1
                        await asyncio.sleep(0.05)
                    except Exception:
                        failed += 1
                return web.json_response({"ok": True, "sent": sent, "failed": failed})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        # ── Serve web admin panel HTML ───────────────────────────────────────
        async def serve_admin_panel(request):
            """Serve the admin_panel.html file directly from disk (or embedded)."""
            import os as _os
            # Look for admin_panel.html next to bot.py
            candidates = [
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "admin_panel.html"),
                _os.path.join(_os.getcwd(), "admin_panel.html"),
                "/app/admin_panel.html",
            ]
            for path in candidates:
                if _os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as f:
                        html = f.read()
                    return web.Response(text=html, content_type="text/html")
            # Fallback — redirect to login instructions
            return web.Response(
                text="<h1>Admin Panel</h1><p>admin_panel.html not found. Make sure it is in the same directory as bot.py.</p>",
                content_type="text/html",
                status=404
            )

        app.router.add_get("/admin", serve_admin_panel)
        app.router.add_get("/admin/", serve_admin_panel)
        app.router.add_get("/admin_panel.html", serve_admin_panel)
        app.router.add_get("/panel", serve_admin_panel)

        # ── Register admin API routes ────────────────────────────────────────
        app.router.add_get ("/admin/api/stats",          web_admin_stats)
        app.router.add_get ("/admin/api/users",          web_admin_users)
        app.router.add_post("/admin/api/users/action",   web_admin_user_action)
        app.router.add_get ("/admin/api/logs",           web_admin_logs)
        app.router.add_get ("/admin/api/groups",         web_admin_groups)
        app.router.add_post("/admin/api/groups",         web_admin_groups_update)
        app.router.add_get ("/admin/api/plans",          web_admin_plans)
        app.router.add_post("/admin/api/plans",          web_admin_plans_update)
        app.router.add_post("/admin/api/broadcast",      web_admin_broadcast)

        # CORS middleware
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.PORT)
    
    try:
        await site.start()
        _WEB_SERVER_STARTED = True  # ← signal main() that port is bound
        logger.info(f"🌐 Web server running on port {config.PORT}")
        if config.API_ENABLED:
            logger.info("🔑 API endpoints active on web server.")
            logger.info(f"🔑 API endpoints available at {config.API_BASE_URL}/api/v1/")
            logger.info(f"📚 API Documentation: {config.API_BASE_URL}/api/v1/docs")
        # Keep running until cancelled
        await asyncio.Event().wait()
    except OSError as e:
        if e.errno == 98:  # EADDRINUSE — already bound by another process/instance
            logger.warning(f"⚠️  Port {config.PORT} already in use — web server skipping bind, parking task.")
            _WEB_SERVER_STARTED = False  # allow future retry after real restart
            await asyncio.Event().wait()  # park forever — do NOT return (avoids _safe_task spam)
        else:
            logger.error(f"❌ Web server OS error: {e}")
            _WEB_SERVER_STARTED = False
            raise  # let _safe_task handle retry with delay
    except Exception as e:
        logger.error(f"❌ Web server failed: {e}")
        _WEB_SERVER_STARTED = False
        raise  # let _safe_task handle retry with delay

# ================== GLOBAL VARIABLES ==================

# Use StringSession if env var is set (required on Render/cloud — prevents AuthKeyDuplicatedError)
_bot_session  = StringSession(config.BOT_SESSION_STRING)  if config.BOT_SESSION_STRING  else config.BOT_SESSION_FILE
_user_session = StringSession(config.USER_SESSION_STRING) if config.USER_SESSION_STRING else config.USER_SESSION_FILE
bot_client = TelegramClient(_bot_session, config.BOT_API_ID, config.BOT_API_HASH)
user_client = (
    TelegramClient(_user_session, config.USER_API_ID, config.USER_API_HASH)
    if USE_USER_ACCOUNT
    else bot_client
)

db_manager = DatabaseManager()
search_engine = None
api_handler = None  # set in _run_bot() after DB + search_engine init
admin_panel = None
user_states = {}
bot_info = None
export_data_storage = {}

# ================== EVENT HANDLERS ==================

@bot_client.on(events.NewMessage(pattern=r'/start(?: (.+))?'))
async def start_handler(event):
    """Premium start handler — force-join checked for ALL users before anything else."""
    try:
        user = await event.get_sender()
        user_id = user.id
        referral_code = event.pattern_match.group(1)

        # ── STEP 1: Force-join check — runs for EVERY user, new or returning ──
        # Must happen before creating user or showing menu.
        if FORCE_JOIN_CHANNELS:
            missing = await check_force_join(user_id)
            if missing:
                ch_lines = "\n".join(
                    "  ▸ " + (ch.get("title") or ch.get("username", ""))
                    for ch in missing
                )
                msg = (
                    "👋 **Welcome to DarkBoxes Intelligence!**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "Before you can use this bot, please join our\n"
                    "official channel(s):\n\n"
                    + ch_lines +
                    "\n\n"
                    "Tap the button(s) below to join, then tap\n"
                    "**✅ I've Joined — Verify & Continue**"
                )
                await event.respond(
                    msg,
                    buttons=_build_join_keyboard(missing),
                    parse_mode="md"
                )
                return  # stop here — do not create user or show menu

        # ── STEP 2: Ban check ─────────────────────────────────────────────────
        user_doc = await db_manager.get_user(user_id)
        if user_doc and user_doc.get('is_banned'):
            await event.respond(
                "🚫 **Account Suspended**\n\n"
                "Your account has been suspended.\n"
                "Contact @darkboxesAdmin if you believe this is a mistake.",
                parse_mode="md"
            )
            return

        # ── STEP 3: Create user if new ────────────────────────────────────────
        if not user_doc:
            await db_manager.create_user(user_id, user.username, user.first_name, referral_code)
            user_doc = await db_manager.get_user(user_id)

            if referral_code and referral_code.isdigit():
                referrer_id = int(referral_code)
                referrer = await db_manager.get_user(referrer_id)
                if referrer:
                    await db_manager.add_referral_credit(referrer_id, config.REFERRAL_REWARD)

            # Auto-create client account and send credentials
            try:
                import secrets as _sec, hashlib as _hl
                loop = asyncio.get_running_loop()
                existing_acc = await loop.run_in_executor(
                    None, lambda: db_manager.db.accounts.find_one({"linked_tg_ids": user_id})
                )
                if not existing_acc:
                    auto_pass = _sec.token_urlsafe(10)
                    acc_id    = f"DB{_sec.token_hex(4).upper()}"
                    pwd_hash  = _hl.sha256(auto_pass.encode()).hexdigest()
                    new_acc   = {
                        "account_id": acc_id,
                        "telegram_user_id": user_id,
                        "username": (user.username or "").lower() or acc_id.lower(),
                        "display_name": user.first_name or "User",
                        "password_hash": pwd_hash,
                        "linked_tg_ids": [user_id],
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "searches_remaining": config.NEW_USER_CREDITS,
                        "subscription": None, "subscription_expiry": None,
                        "is_banned": False, "total_searches": 0,
                        "source": "telegram_start",
                    }
                    await loop.run_in_executor(None, lambda: db_manager.db.accounts.insert_one(new_acc))
                    await loop.run_in_executor(
                        None, lambda: db_manager.db.users.update_one(
                            {"user_id": user_id}, {"$set": {"client_account_id": acc_id}}
                        )
                    )
                    await bot_client.send_message(
                        user_id,
                        "🎉 **Welcome to DarkBoxes!**\n\n"
                        "Your account has been created automatically.\n\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "🆔 **Account ID:** `" + acc_id + "`\n"
                        "🔐 **Password:**   `" + auto_pass + "`\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        "⚠️ **Save this now** — password shown only once.\n"
                        "🔒 Never share your password with anyone.",
                        parse_mode="md"
                    )
            except Exception as _ce:
                logger.error(f"Auto account creation failed: {_ce}")
        else:
            # Returning user — sync account link
            try:
                loop = asyncio.get_running_loop()
                existing_acc = await loop.run_in_executor(
                    None, lambda: db_manager.db.accounts.find_one({"linked_tg_ids": user_id})
                )
                if existing_acc:
                    await loop.run_in_executor(
                        None, lambda: db_manager.db.accounts.update_one(
                            {"_id": existing_acc["_id"]},
                            {"$set": {"telegram_user_id": user_id},
                             "$addToSet": {"linked_tg_ids": user_id}}
                        )
                    )
                    await loop.run_in_executor(
                        None, lambda: db_manager.db.users.update_one(
                            {"user_id": user_id},
                            {"$set": {"client_account_id": existing_acc.get("account_id", "")}}
                        )
                    )
            except Exception as _le:
                logger.warning(f"Account sync failed on /start for {user_id}: {_le}")

        # ── STEP 4: Show welcome menu ─────────────────────────────────────────
        is_admin     = admin_panel.is_admin(user_id) if admin_panel else (user_id == config.ADMIN_USER_ID)
        welcome_text = PremiumFormatter.format_welcome(user.first_name, user_doc)
        try:
            _dis_doc = await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.settings.find_one({"_id": "disabled_buttons"})
            )
            _disabled = set(_dis_doc.get("keys", []) if _dis_doc else [])
        except Exception:
            _disabled = set()

        buttons = OneLineKeyboard.main_menu(is_admin, disabled_buttons=_disabled)

        await event.respond(
            welcome_text,
            buttons=buttons,
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in start_handler: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^admin_'))
async def admin_callback_handler(event):
    """Handle admin panel callbacks"""
    await admin_panel.handle_admin_callback(event)


# ── CRITICAL FIX: Route confirm_* and user_detail_* callbacks ────────────
# These callbacks are generated by admin panel buttons but do NOT start with
# "admin_", so they were silently dropped by the handler above. This handler
# catches them all and routes them to handle_admin_callback.
@bot_client.on(events.CallbackQuery(
    pattern=r'^(confirm_ban_|confirm_unban_|confirm_add_admin_|'
            r'confirm_remove_admin_|user_detail_|admin_give_sub_|'
            r'admin_add_credits_user_|confirm_create_api_|confirm_revoke_api_)'))
async def admin_confirm_action_callback_handler(event):
    """Route confirm/user-detail action callbacks to the admin panel handler"""
    await admin_panel.handle_admin_callback(event)


@bot_client.on(events.CallbackQuery(pattern=r'^grant_sub_(\d+)_(.+)$'))
async def grant_sub_callback(event):
    """Grant subscription to a user directly"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        
        data = event.data.decode()
        # Format: grant_sub_USERID_PLANID  (plan_id may contain underscores)
        parts = data.split('_', 3)
        # parts = ['grant', 'sub', USERID, PLANID]
        user_id = int(parts[2])
        plan_id = parts[3]

        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            await event.answer(
                f"❌ Plan '{plan_id}' not recognised. "
                f"Valid: {', '.join(SUBSCRIPTION_PLANS.keys())}",
                alert=True
            )
            return
        
        plan_type = plan.get("plan_type", "credit")
        validity_days = plan.get("validity_days", 0)
        daily_limit = plan.get("daily_limit", 0)
        searches = plan.get('searches', 0)

        if plan_type == "credit":
            # Credit pack: add credits, no expiry
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.users.update_one(
                    {"user_id": user_id},
                    {"$inc": {"searches_remaining": searches},
                     "$set": {"last_seen": datetime.now(timezone.utc).isoformat()}}
                )
            )
            expiry_str = "Never"
            search_str = f"{searches} credits added"
        else:
            # Subscription plan with daily limit
            expiry = datetime.now(timezone.utc) + timedelta(days=validity_days)
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "subscription": plan_id,
                        "subscription_expiry": expiry.isoformat(),
                        "subscription_daily_limit": daily_limit,
                        "subscription_used_today": 0,
                        "subscription_reset_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "last_seen": datetime.now(timezone.utc).isoformat()
                    }}
                )
            )
            expiry_str = expiry.strftime("%d %b %Y")
            search_str = f"{daily_limit}/day for {validity_days} days"

        # Notify user
        try:
            await bot_client.send_message(
                user_id,
                f"🎁 **PLAN GRANTED BY ADMIN!**\n\n"
                f"✅ **{plan['name']}** has been activated!\n"
                f"🔍 {search_str}\n"
                f"📅 Valid: {expiry_str}\n\n"
                f"Enjoy DarkBoxes! 🚀  Use /start to begin.",
                parse_mode="md"
            )
        except Exception:
            pass

        await event.edit(
            f"✅ **PLAN GRANTED**\n\n"
            f"User `{user_id}` → **{plan['name']}**\n"
            f"Searches: {search_str}\n"
            f"Valid: {expiry_str}\n\n"
            f"User has been notified.",
            buttons=OneLineKeyboard.back_to_admin(),
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ Error in grant_sub_callback: {e}")
        await event.answer("❌ Error granting subscription", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)$'))
async def search_callback(event):
    """Premium search type selection — force-join aware, masked-preview support."""
    try:
        user_id = event.sender_id
        search_type = event.data.decode().split('_', 1)[1]

        # ── Force-join gate ──────────────────────────────────────────────────
        if not await enforce_force_join(event):
            return

        user_doc = await db_manager.get_user(user_id)
        if user_doc and user_doc.get('is_banned'):
            await event.answer("🚫 Account suspended. Contact @darkboxesAdmin.", alert=True)
            return
        if search_type not in SEARCH_COMMANDS:
            await event.answer("❌ Invalid command selection.", alert=True)
            return
        if not user_doc:
            await event.answer("❌ Account not found. Send /start first.", alert=True)
            return

        # ── Access check ─────────────────────────────────────────────────────
        can_search          = False
        searches_remaining  = user_doc.get('searches_remaining', 0)
        subscription        = user_doc.get('subscription')
        subscription_expiry = user_doc.get('subscription_expiry')
        daily_limit         = user_doc.get('subscription_daily_limit', 0)

        if subscription and subscription_expiry:
            try:
                expiry_date = datetime.fromisoformat(subscription_expiry)
                if expiry_date > datetime.now(timezone.utc):
                    today_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    reset_date = user_doc.get("subscription_reset_date", "")
                    used_today = user_doc.get("subscription_used_today", 0)
                    if reset_date != today_str:
                        await asyncio.get_running_loop().run_in_executor(
                            None, lambda: db_manager.db.users.update_one(
                                {"user_id": user_id},
                                {"$set": {"subscription_used_today": 0,
                                          "subscription_reset_date": today_str}}
                            )
                        )
                        used_today = 0
                    if daily_limit == 0 or used_today < daily_limit:
                        can_search = True
                    else:
                        exp_fmt  = expiry_date.strftime("%d %b %Y")
                        limit_txt = (
                            "⏰ **Daily Search Limit Reached**\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                            "> Used today: **" + str(used_today) + " / " + str(daily_limit) + "**\n"
                            "> Resets: **midnight UTC**\n"
                            "> Plan valid till: **" + exp_fmt + "**\n\n"
                            "Upgrade for higher daily limits or buy extra credits:"
                        )
                        await event.edit(limit_txt,
                            buttons=OneLineKeyboard.subscription_plans(), parse_mode="md")
                        return
            except Exception:
                pass

        is_free = not can_search and searches_remaining <= 0
        cmd  = SEARCH_COMMANDS[search_type]
        cost = cmd['cost']
        ICONS = {
            "phone": "📱", "vehicle": "🚗", "family": "👨‍👩‍👧",
            "telegram": "✈️", "aadhar": "🪪", "gst": "🏢",
            "imei": "📲", "ip": "🌐", "ifsc": "🏦",
            "insta": "📸", "leak": "💾",
        }
        icon = ICONS.get(search_type, "🔍")
        cost_str = str(cost) + " credit" + ("s" if cost != 1 else "")

        if is_free:
            txt = (
                icon + " **" + cmd['name'] + "**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "> ⚠️ **No credits** — you will receive a **masked preview**\n"
                "> Tap 🔓 **Buy This Data** after results to unlock full info.\n\n"
                "**Example format:** `" + cmd['example'] + "`\n\n"
                "✏️ _Type your query and send it:_"
            )
        else:
            bal = str(searches_remaining) + " credit" + ("s" if searches_remaining != 1 else "")
            if can_search and subscription:
                bal += " + active plan"
            txt = (
                icon + " **" + cmd['name'] + "**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "> **Format:**  `" + cmd['example'] + "`\n"
                "> **Cost:**    " + cost_str + "\n"
                "> **Balance:** " + bal + "\n\n"
                "✏️ _Type your query and send it:_"
            )

        await event.edit(txt, buttons=[[Button.inline("✖  Cancel", "main_menu")]], parse_mode="md")
        user_states[user_id] = {"action": "search", "type": search_type}

    except Exception as e:
        logger.error(f"search_callback error: {e}")
        await event.answer("❌ Error loading search", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^profile$'))
async def profile_callback(event):
    """Premium profile view."""
    try:
        user_id  = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        if not user_doc:
            await event.answer("❌ Account not found. Send /start.", alert=True)
            return

        cred        = user_doc.get("searches_remaining", 0)
        sub         = user_doc.get("subscription")
        expiry_str  = user_doc.get("subscription_expiry", "")
        total       = user_doc.get("total_searches", 0)
        refs        = user_doc.get("referrals", 0)
        ref_code    = user_doc.get("referral_code", "N/A")
        joined      = (user_doc.get("joined_at") or "")[:10] or "N/A"
        username    = user_doc.get("username") or "—"
        name        = user_doc.get("first_name") or "User"

        # Build balance line
        if sub and expiry_str:
            try:
                exp       = datetime.fromisoformat(expiry_str)
                days_left = (exp - datetime.now(timezone.utc)).days
                if days_left > 0:
                    plan_obj   = SUBSCRIPTION_PLANS.get(sub, {})
                    plan_name  = plan_obj.get("name", sub)
                    bal_line   = "✅ " + plan_name + "  (" + str(days_left) + " days left)"
                    bal_line2  = str(cred) + " bonus credit" + ("s" if cred != 1 else "") + " also available"
                else:
                    bal_line  = "⚠️ Subscription expired"
                    bal_line2 = str(cred) + " credit" + ("s" if cred != 1 else "") + " remaining"
            except Exception:
                bal_line  = str(cred) + " credit" + ("s" if cred != 1 else "")
                bal_line2 = ""
        else:
            bal_line  = str(cred) + " credit" + ("s" if cred != 1 else "")
            bal_line2 = "No active subscription"

        ref_link = "https://t.me/" + bot_info.username + "?start=" + ref_code

        txt = (
            "👤 **My Profile**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "> **Name:**     " + name + "\n"
            "> **Username:** @" + username + "\n"
            "> **User ID:**  `" + str(user_id) + "`\n"
            "> **Joined:**   " + joined + "\n\n"
            "💳 **Balance**\n"
            "> " + bal_line + "\n"
            "> " + bal_line2 + "\n\n"
            "📊 **Activity**\n"
            "> Total searches:  **" + str(total) + "**\n"
            "> Referrals made:  **" + str(refs) + "**\n"
            "> Earn **1 credit** per successful referral\n\n"
            "🔗 **Your referral link:**\n"
            "`" + ref_link + "`"
        )
        await event.edit(txt, buttons=OneLineKeyboard.profile_menu(), parse_mode="md")

    except Exception as e:
        logger.error(f"profile_callback error: {e}")
        await event.answer("❌ Error loading profile", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^premium$'))
async def premium_callback(event):
    """Premium plans page — polished UX."""
    try:
        user_id  = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        cred     = user_doc.get("searches_remaining", 0) if user_doc else 0

        txt = (
            "💎 **Plans & Credits**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Your current balance: **" + str(cred) + " credit" + ("s" if cred != 1 else "") + "**\n\n"
            "**Available Plans**\n\n"
            "⚡ **5 Credits Pack** — ₹200\n"
            "> Works on any command · Never expire\n\n"
            "📱 **NUM Unlimited** — ₹300 / month\n"
            "> Unlimited phone/number searches · 30 days\n\n"
            "💎 **All Commands** — ₹499 / month  _(Best Value)_\n"
            "> Unlimited searches on every command · 30 days\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**How to buy:**\n"
            "> 1️⃣ Tap a plan button below\n"
            "> 2️⃣ Pay via UPI to the shown ID\n"
            "> 3️⃣ Submit your UTR / Transaction ID\n"
            "> 4️⃣ Admin activates within **5–15 min**\n\n"
            "_UPI: `" + config.UPI_ID + "`_\n"
            "_Support: @darkboxesAdmin_"
        )
        await event.edit(txt, buttons=OneLineKeyboard.subscription_plans(), parse_mode="md")

    except Exception as e:
        logger.error(f"premium_callback error: {e}")
        await event.answer("❌ Error loading plans", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^plan_(.+)$'))
async def plan_selection_callback(event):
    """Handle plan selection — UPI manual payment flow only"""
    try:
        plan_id = event.data.decode().split('_', 1)[1]
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.answer("❌ Invalid plan selection", alert=True)
            return
        plan = SUBSCRIPTION_PLANS[plan_id]
        user_id = event.sender_id
        plan_type = plan.get("plan_type", "credit")
        daily_limit = plan.get("daily_limit", 0)
        if plan_type == "subscription" and daily_limit > 0:
            search_desc = f"{plan['searches']} searches/day"
        else:
            search_desc = f"{plan['searches']} searches · no expiry"
        plan_details = (
            f"**{plan['name']}**"
            f"\n\n"
            f"> 💰 Price   : ₹{plan['price']}"
            f"\n"
            f"> 🔍 Searches: {search_desc}"
            f"\n"
            f"> 📅 Validity: {plan['validity']}"
            f"\n\n"
            f"**How to pay:**"
            f"\n"
            f"> 1️⃣ Open any UPI app (GPay, PhonePe, Paytm…)"
            f"\n"
            f"> 2️⃣ Send ₹{plan['price']} to `{config.UPI_ID}`"
            f"\n"
            f"> 3️⃣ Note the UTR / Transaction Reference Number"
            f"\n"
            f"> 4️⃣ Tap **I've Paid** below and enter it"
            f"\n\n"
            f"_Activated within 5–15 min after admin verification._"
        )
        buttons = [
            [Button.inline(f"✅ I've Paid — Submit UTR", f"submit_payment_{plan_id}")],
            [Button.inline("« Back to Plans", "premium"),
             Button.inline("Main Menu", "main_menu")]
        ]
        await event.edit(plan_details, buttons=buttons, parse_mode="md")
    except Exception as e:
        logger.error(f"❌ Error in plan_selection_callback: {e}")
        await event.answer("❌ Error loading plan details", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^submit_payment_(.+)$'))
async def submit_payment_callback(event):
    """Guide user to enter UTR/Transaction number"""
    try:
        plan_id = event.data.decode().split('_', 2)[2]
        user_id = event.sender_id

        if plan_id not in SUBSCRIPTION_PLANS:
            await event.answer("❌ Invalid plan", alert=True)
            return

        plan = SUBSCRIPTION_PLANS[plan_id]

        # Set state to await UTR
        user_states[user_id] = {
            "action": "awaiting_payment_utr",
            "plan_id": plan_id,
            "plan_name": plan['name'],
            "plan_price": plan['price']
        }

        instructions = (
            f"**Submit Payment**"
            f"\n\n"
            f"> Plan   : {plan['name']}"
            f"\n"
            f"> Amount : ₹{plan['price']}"
            f"\n"
            f"> UPI ID : `{config.UPI_ID}`"
            f"\n\n"
            f"After paying, type your **UTR** or **Transaction ID** and send it here."
            f"\n\n"
            f"> PhonePe: History → transaction → UTR No"
            f"\n"
            f"> GPay: Activity → transaction → Transaction ID"
            f"\n"
            f"> Paytm: History → Reference No"
            f"\n\n"
            f"_Admin will verify and activate within 5–15 min._"
        )

        buttons = [[Button.inline("❌ Cancel", "main_menu")]]
        await event.edit(instructions, buttons=buttons, parse_mode="md")

    except Exception as e:
        logger.error(f"❌ Error in submit_payment_callback: {e}")
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^referrals$'))
async def referrals_callback(event):
    """Premium refer & earn page."""
    try:
        user_id  = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        if not user_doc:
            await event.answer("❌ Account not found. Send /start.", alert=True)
            return

        ref_code  = user_doc.get('referral_code', 'N/A')
        ref_count = user_doc.get('referrals', 0)
        ref_creds = user_doc.get('referral_credits', 0)
        ref_link  = "https://t.me/" + bot_info.username + "?start=" + ref_code

        txt = (
            "🎁 **Refer & Earn**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**How it works:**\n"
            "> 1️⃣ Share your link below\n"
            "> 2️⃣ Friend signs up using your link\n"
            "> 3️⃣ You get **" + str(config.REFERRAL_REWARD) + " credit** instantly\n"
            "> 4️⃣ They get **" + str(config.NEW_USER_CREDITS) + " free credits** too\n\n"
            "**Your Stats**\n"
            "> Referral code:   `" + ref_code + "`\n"
            "> Total referrals: **" + str(ref_count) + "**\n"
            "> Credits earned:  **" + str(ref_creds) + "**\n\n"
            "**Your referral link:**\n"
            "`" + ref_link + "`\n\n"
            "**Ready-to-share message:**\n"
            "```\n"
            "🔍 DarkBoxes — India's most powerful search tool!\n"
            "Phone lookups, vehicle info, ID records & more.\n"
            "Get " + str(config.NEW_USER_CREDITS) + " free credits when you join:\n"
            + ref_link + "\n"
            "```"
        )
        await event.edit(txt, buttons=OneLineKeyboard.referrals_menu(), parse_mode="md")

    except Exception as e:
        logger.error(f"referrals_callback error: {e}")
        await event.answer("❌ Error loading referrals", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^support$'))
async def support_callback(event):
    """Premium support page."""
    try:
        txt = (
            "🛟 **Support Center**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**Contact Us**\n"
            "> 👤 Admin:   @darkboxesAdmin\n"
            "> 📢 Channel: @darkboxesv1\n"
            "> ⏰ Response: typically within 1 hour\n\n"
            "**Common Issues**\n"
            "> • _Payment not activated_ → submit UTR in the bot\n"
            "> • _Search not working_ → check credit balance\n"
            "> • _Wrong / no result_ → try different format\n"
            "> • _Account banned_ → contact admin\n\n"
            "**How to Pay**\n"
            "> UPI ID: `" + config.UPI_ID + "`\n"
            "> After paying tap **Buy Credits** → **I've Paid**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ _Official admin is @darkboxesAdmin only._\n"
            "_Never share your password or OTP with anyone._"
        )
        await event.edit(txt, buttons=OneLineKeyboard.support_menu(), parse_mode="md")

    except Exception as e:
        logger.error(f"support_callback error: {e}")
        await event.answer("❌ Error loading support", alert=True)
        
    except Exception as e:
        logger.error(f"❌ Error in support_callback: {e}")
        await event.answer("❌ Error loading support", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^my_referrals$'))
async def my_referrals_callback(event):
    """Handle my referrals callback"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        # Get referrals from database
        referral_code = user_doc.get('referral_code', '')
        referrals = []
        
        if referral_code:
            referrals = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(db_manager.db.users.find(
                    {"referred_by": referral_code},
                    {"user_id": 1, "username": 1, "first_name": 1, "joined_at": 1}
                ).limit(20))
            )
        
        referrals_text = (
            f"📋 **MY REFERRALS**\n"
            f"═══════════════════════\n\n"
        )
        
        if referrals:
            referrals_text += f"👥 **Total Referrals:** {len(referrals)}\n\n"
            
            for i, ref in enumerate(referrals[:10], 1):
                username = f"@{ref['username']}" if ref.get('username') else "No username"
                joined = ref.get('joined_at', '')[:10]
                
                referrals_text += (
                    f"{i}. **{ref['first_name']}**\n"
                    f"   ├─ {username}\n"
                    f"   ├─ ID: `{ref['user_id']}`\n"
                    f"   └─ Joined: {joined}\n\n"
                )
            
            if len(referrals) > 10:
                referrals_text += f"... and {len(referrals) - 10} more referrals\n"
        else:
            referrals_text += "📭 No referrals yet.\n\n"
            referrals_text += f"🔗 **Your Referral Code:** `{user_doc.get('referral_code', 'N/A')}`\n"
            referrals_text += "💡 Share your referral link to earn credits!"
        
        buttons = [
            [Button.inline("📢 Share Referral", "share_referral")],
            [Button.inline("« Refer & Earn", "referrals")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        
        await event.edit(referrals_text, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in my_referrals_callback: {e}")
        await event.answer("❌ Error loading referrals", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^share_referral$'))
async def share_referral_callback(event):
    """Handle share referral callback"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        referral_code = user_doc.get('referral_code', '')
        referral_link = f"https://t.me/{bot_info.username}?start={referral_code}"
        
        share_text = (
            f"📢 **SHARE REFERRAL LINK**\n"
            f"═══════════════════════\n\n"
            f"🔗 **Your Referral Link:**\n"
            f"{referral_link}\n\n"
            f"📝 **Copy-Paste Message:**\n"
            f"```\n"
            f"🚀 Join DarkBoxes Intelligence System!\n\n"
            f"🔍 **Powerful OSINT Tools:**\n"
            f"• Phone Number Lookup\n"
            f"• Email Intelligence\n"
            f"• ID Information\n"
            f"• Vehicle Details\n"
            f"• Telegram Analysis\n"
            f"• ADVANCED OSINT TOOL (Search Anything)\n"
            f"• And much more!\n\n"
            f"💎 **Get {config.NEW_USER_CREDITS} FREE Credits**\n"
            f"🔗 Sign up now: {referral_link}\n\n"
            f"⚡ **Features:**\n"
            f"• Fast & Accurate Results\n"
            f"• Premium Databases\n"
            f"• 24/7 Support\n"
            f"• Affordable Plans\n"
            f"```\n\n"
            f"💡 **Where to Share:**\n"
            f"• Telegram Groups\n"
            f"• Friends & Family\n"
            f"• Social Media\n"
            f"• Forums\n\n"
            f"💰 **Earn {config.REFERRAL_REWARD} credit for each successful referral!**"
        )
        
        buttons = [
            [Button.inline("« Back to Referrals", "referrals")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        
        await event.edit(share_text, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in share_referral_callback: {e}")
        await event.answer("❌ Error loading share referral", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^contact_admin$'))
async def contact_admin_callback(event):
    """Handle contact admin callback"""
    try:
        contact_text = (
            "**Contact Admin**"
            "\n\n"
            "> 📞 Telegram: @darkboxesAdmin _(preferred)_"
            "\n"
            "> 📢 Channel: @darkboxesv1"
            "\n"
            "> ⏰ Response: within 1 hour"
            "\n\n"
            "**Payment issues**"
            "\n"
            f"> 1. Pay to `{config.UPI_ID}`"
            "\n"
            "> 2. Note your UTR / Transaction Number"
            "\n"
            "> 3. Submit it via 💎 Buy Credits in the bot"
            f"\n"
            f"> Your ID: `{event.sender_id}`"
            "\n\n"
            "_Official admin: @darkboxesAdmin only. Never share your password._"
        )
        
        buttons = [
            [Button.inline("📋 Report Issue", "report_issue")],
            [Button.inline("« Support", "support")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        
        await event.edit(contact_text, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in contact_admin_callback: {e}")
        await event.answer("❌ Error loading contact info", alert=True)

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not (e.text or '').startswith('/')))
async def private_message_handler(event):
    """Handle private messages (queries, admin actions, payment screenshots, media)"""
    try:
        user_id = event.sender_id

        if user_id not in user_states:
            return

        state = user_states[user_id]

        if state.get("action") == "search":
            await handle_search_query(event, state)

        elif state.get("action") == "awaiting_payment_utr":
            await handle_payment_utr(event, state)

        elif state.get("action") == "admin_search_user":
            await handle_admin_search_user(event)

        elif state.get("action") == "admin_broadcast":
            await handle_admin_broadcast(event)

        elif state.get("action") == "admin_broadcast_media":
            await handle_admin_broadcast_media(event)

        elif state.get("action") == "admin_broadcast_select_users":
            await handle_admin_broadcast_select_users(event)

        elif state.get("action") == "admin_ban":
            await handle_admin_ban(event)

        elif state.get("action") == "admin_management":
            await handle_admin_management(event)

        elif state.get("action") == "admin_add_credits":
            await handle_admin_add_credits(event)

        elif state.get("action") == "admin_give_subscription":
            await handle_admin_give_subscription(event)
        elif state.get("action") == "admin_reset_password":
            await handle_admin_reset_password(event)

        elif state.get("action") == "admin_give_credits_all":
            await handle_admin_give_credits_all(event)

        elif state.get("action") == "admin_take_credits_user":
            await handle_admin_take_credits_user(event)

        elif state.get("action") == "admin_take_credits_all":
            await handle_admin_take_credits_all(event)

        elif state.get("action") == "admin_fj_add":
            # Admin typed: "@username  Optional Title"
            raw   = event.text.strip()
            parts = raw.split(None, 1)
            uname = parts[0].lstrip("@") if parts else ""
            title = parts[1].strip() if len(parts) > 1 else uname
            if not uname:
                await event.respond("❌ Invalid format. Use: `@username Title`", parse_mode="md")
                return
            url = "https://t.me/" + uname
            entry = {"username": "@" + uname, "title": title, "url": url}
            # Check duplicate
            if any(ch.get("username", "").lstrip("@") == uname for ch in FORCE_JOIN_CHANNELS):
                await event.respond(
                    "⚠️ `@" + uname + "` is already in the force-join list.",
                    parse_mode="md",
                    buttons=[[Button.inline("« Force-Join Panel", "admin_force_join")]]
                )
            else:
                FORCE_JOIN_CHANNELS.append(entry)
                await _save_force_join_channels()
                await event.respond(
                    "✅ **Channel Added**\n\n"
                    "> Username: `@" + uname + "`\n"
                    "> Title:    " + title + "\n"
                    "> URL:      " + url + "\n\n"
                    "Users must now join this channel before using the bot.",
                    parse_mode="md",
                    buttons=[[Button.inline("« Force-Join Panel", "admin_force_join")]]
                )
            user_states.pop(user_id, None)

        elif state.get("action") == "enter_account_credentials":
            await handle_account_login(event)

        elif state.get("action") == "admin_view_user_search_logs":
            await handle_admin_view_user_search_logs(event)

        elif state.get("action") == "admin_set_group_cmd":
            # Admin typed a new command for a group+search_type
            group_key   = state.get("group_key", "")
            search_type = state.get("search_type", "")
            new_cmd     = event.text.strip()
            # "-" means "no command" (direct query mode)
            if new_cmd == "-":
                new_cmd = ""
            g = GROUP_PRIORITIES.get(group_key)
            if g is not None and search_type in SEARCH_COMMANDS:
                g.setdefault("commands", {})[search_type] = new_cmd
                display = new_cmd if new_cmd else "(direct / no command)"
                await event.respond(
                    f"✅ Updated `{group_key}` → `{search_type}` to `{display}`",
                    parse_mode="md",
                    buttons=[[Button.inline("⬅️ Back to Group", f"admin_gcmd_group_{group_key}")]]
                )
            else:
                await event.respond("❌ Invalid group or command key.")
            user_states.pop(user_id, None)

        elif state.get("action") == "admin_restrict_query":
            query = event.text.strip()
            if not query or len(query) < 2:
                await event.respond("❌ Please enter a valid query to restrict.")
                return
            await db_manager.protected_manager.add_protected_query(query, event.sender_id, reason="admin_restricted")
            user_states.pop(user_id, None)
            await event.respond(
                f"✅ **QUERY RESTRICTED SUCCESSFULLY**\n\n"
                f"🔍 Query: `{query}`\n"
                f"🚫 Status: Blocked\n\n"
                f"Users will see a 'Protected/Blocked' message when searching this query.\n\n"
                f"Use the Admin Panel → Manage Restricted Queries to view all restrictions.",
                parse_mode="md",
                buttons=[[Button.inline("🔒 Manage Restricted Queries", "admin_restricted_queries")]]
            )

        elif state.get("action") == "admin_unrestrict_query":
            query = event.text.strip()
            if not query or len(query) < 2:
                await event.respond("❌ Please enter a valid query to unrestrict.")
                return
            await db_manager.protected_manager.remove_protected_query(query)
            user_states.pop(user_id, None)
            await event.respond(
                f"✅ **QUERY UNRESTRICTED**\n\n"
                f"🔍 Query: `{query}`\n"
                f"🔓 Status: Unrestricted\n\n"
                f"Users can now search this query normally.",
                parse_mode="md",
                buttons=[[Button.inline("🔒 Manage Restricted Queries", "admin_restricted_queries")]]
            )

        elif state.get("action") == "admin_reply_to_user":
            # Admin typed a reply to a user who messaged the bot
            target_uid = state.get("reply_to_user_id")
            reply_text = (event.text or "").strip()
            if target_uid and reply_text:
                try:
                    await bot_client.send_message(
                        target_uid,
                        f"> ✉️ **Message from Admin**\n\n{reply_text}",
                        parse_mode="md"
                    )
                    user_states.pop(user_id, None)
                    await event.respond("✅ Reply sent to user.", buttons=OneLineKeyboard.back_to_admin())
                except Exception as _re:
                    await event.respond(f"❌ Could not send: {_re}")
            return

    except Exception as e:
        logger.error(f"❌ Error in private_message_handler: {e}")


@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not (e.text or "").startswith("/")))
async def user_freetext_handler(event):
    """Forward message to admin ONLY when user is in 'messaging_admin' state.
    Prevents false triggers on search queries, UTR submissions, etc.
    """
    try:
        user_id = event.sender_id
        state = user_states.get(user_id, {})

        # ONLY forward if user explicitly tapped "Message Admin"
        if state.get("action") != "messaging_admin":
            return

        if admin_panel and admin_panel.is_admin(user_id):
            return

        text = (event.text or "").strip()
        if not text:
            return

        sender = await event.get_sender()
        uname = f"@{sender.username}" if sender.username else f"ID {user_id}"

        admin_msg = (
            f"**Support message**\n"
            f"\n"
            f"> From: {sender.first_name or ''} ({uname})\n"
            f"> User ID: `{user_id}`\n"
            f"\n"
            f"{text}"
        )
        await bot_client.send_message(
            config.ADMIN_USER_ID,
            admin_msg,
            parse_mode="md",
            buttons=[[Button.inline(f"Reply to {sender.first_name or user_id}", f"admin_reply_user_{user_id}")]]
        )

        user_states.pop(user_id, None)
        await event.respond(
            "**Message sent**\n"
            "\n"
            "> Admin has been notified and will reply shortly.",
            parse_mode="md",
            buttons=[[Button.inline("Back to Menu", "main_menu")]]
        )
    except Exception as e:
        logger.error(f"❌ user_freetext_handler: {e}")


@bot_client.on(events.CallbackQuery(pattern=r"^user_message_admin$"))
async def user_message_admin_callback(event):
    """User pressed 'Message Admin' — set state so freetext handler picks it up."""
    try:
        user_states[event.sender_id] = {"action": "messaging_admin"}
        await event.edit(
            "**Message Admin**\n"
            "\n"
            "> Type your message and send it.\n"
            "> Admin will reply directly here.",
            parse_mode="md",
            buttons=[[Button.inline("Cancel", "main_menu")]]
        )
    except Exception as e:
        logger.error(f"❌ user_message_admin_callback: {e}")


@bot_client.on(events.CallbackQuery(pattern=r"^admin_reply_user_(\d+)$"))
async def admin_reply_user_callback(event):
    """Admin pressed Reply button on a user support message."""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admins only", alert=True)
            return
        target_uid = int(event.pattern_match.group(1))
        user_states[event.sender_id] = {"action": "admin_reply_to_user", "reply_to_user_id": target_uid}
        await event.edit(
            f"> ↩ **Reply to user `{target_uid}`**\n"
            f"> Type your reply and send it.\n"
            f"> It will be delivered instantly.",
            parse_mode="md",
            buttons=[[Button.inline("❌ Cancel", "admin_panel")]]
        )
    except Exception as e:
        logger.error(f"❌ admin_reply_user_callback: {e}")

async def handle_payment_utr(event, state):
    """Handle UTR/Transaction number submission from user (no screenshot required)"""
    try:
        user_id = event.sender_id
        plan_id = state.get("plan_id")
        plan_name = state.get("plan_name")
        plan_price = state.get("plan_price")

        utr_text = (event.text or "").strip()

        # Basic validation - UTR is typically 12 digits, but allow 8-25 alphanumeric
        if not utr_text or len(utr_text) < 6 or len(utr_text) > 30:
            await event.respond(
                "⚠️ **Invalid UTR / Transaction Number.**\n\n"
                "Please enter the exact UTR or Transaction Reference Number "
                "shown in your UPI payment app.\n\n"
                "Example: `123456789012` or `T2504201234567890`\n\n"
                "If you're having trouble, contact @darkboxesAdmin",
                parse_mode="md"
            )
            return

        user_doc = await db_manager.get_user(user_id)
        username = f"@{user_doc.get('username', 'N/A')}" if user_doc else "N/A"
        first_name = user_doc.get('first_name', 'N/A') if user_doc else 'N/A'

        # Store pending payment in DB
        payment_id = str(uuid.uuid4())[:8].upper()
        pending_payment = {
            "payment_id": payment_id,
            "user_id": user_id,
            "username": user_doc.get('username', '') if user_doc else '',
            "first_name": first_name,
            "plan_id": plan_id,
            "plan_name": plan_name,
            "amount": plan_price,
            "utr": utr_text,
            "status": "pending",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.pending_payments.insert_one(pending_payment)
        )

        # Notify admin with approve/reject buttons
        admin_caption = (
            f"💳 **NEW PAYMENT — UTR SUBMITTED**\n\n"
            f"🆔 Payment ID: `{payment_id}`\n"
            f"👤 User: {first_name} ({username})\n"
            f"🔢 User ID: `{user_id}`\n"
            f"📦 Plan: **{plan_name}**\n"
            f"💰 Amount: ₹{plan_price}\n"
            f"🏦 UTR/Txn No: `{utr_text}`\n"
            f"🕐 Time: {datetime.now().strftime('%d %b %Y %H:%M')}\n\n"
            f"✅ Approve after verifying UTR in your UPI app.\n"
            f"❌ Reject if UTR is invalid or payment not received."
        )

        admin_buttons = [
            [Button.inline(f"✅ APPROVE — {plan_name}", f"approve_payment_{payment_id}_{user_id}_{plan_id}")],
            [Button.inline(f"❌ REJECT", f"reject_payment_{payment_id}_{user_id}")]
        ]

        try:
            await bot_client.send_message(
                config.ADMIN_USER_ID,
                admin_caption,
                buttons=admin_buttons,
                parse_mode="md"
            )
        except Exception as e:
            logger.error(f"Error notifying admin about UTR payment: {e}")

        # Confirm to user
        await event.respond(
            f"**Payment submitted**"
            f"\n\n"
            f"> Payment ID: `{payment_id}`"
            f"\n"
            f"> Plan: {plan_name}"
            f"\n"
            f"> Amount: ₹{plan_price}"
            f"\n"
            f"> UTR: `{utr_text}`"
            f"\n\n"
            f"_Admin will verify and activate within 5–15 min. You'll get a notification here._"
            f"\n\n"
            f"For urgent help: @darkboxesAdmin",
            parse_mode="md"
        )

        user_states.pop(user_id, None)

    except Exception as e:
        logger.error(f"❌ Error handling payment UTR: {e}")
        await event.respond(
            "❌ Error processing your submission. Please try again or contact "
            "@darkboxesAdmin"
        )
        user_states.pop(user_id, None)


async def handle_payment_screenshot(event, state):
    """Legacy: redirect to UTR flow"""
    await handle_payment_utr(event, state)


@bot_client.on(events.CallbackQuery(pattern=r'^approve_payment_([A-Z0-9]+)_(\d+)_(.+)$'))
async def approve_payment_callback(event):
    """Admin approves payment"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return

        data = event.data.decode()
        # Format: approve_payment_PAYID_USERID_PLANID
        # Plan IDs can contain underscores (e.g. credits_1, credits_12, credits_20),
        # so we split on the first 4 underscores only.
        parts = data.split('_', 4)
        # parts = ['approve', 'payment', PAYID, USERID, PLANID]
        if len(parts) < 5:
            await event.answer("❌ Malformed approval data", alert=True)
            return

        payment_id = parts[2]
        user_id    = int(parts[3])
        plan_id    = parts[4]   # preserved intact even if it contains underscores

        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            # Fallback: check pending_payments for the plan_id stored there
            loop = asyncio.get_running_loop()
            pending = await loop.run_in_executor(
                None, lambda: db_manager.db.pending_payments.find_one({"payment_id": payment_id})
            )
            if pending:
                plan_id = pending.get("plan_id", plan_id)
                plan = SUBSCRIPTION_PLANS.get(plan_id)

        if not plan:
            await event.answer(
                f"❌ Plan '{plan_id}' not found in SUBSCRIPTION_PLANS. "
                f"Valid: {', '.join(SUBSCRIPTION_PLANS.keys())}",
                alert=True
            )
            return

        # Grant plan (credit pack or subscription)
        plan_type = plan.get("plan_type", "credit")
        daily_limit = plan.get("daily_limit", 0)
        validity_days = plan.get("validity_days", 0)
        searches = plan.get("searches", 0)

        if plan_type == "credit":
            # Credit pack: just top-up credits, no expiry
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.users.update_one(
                    {"user_id": user_id},
                    {"$inc": {"searches_remaining": searches},
                     "$set": {"last_seen": datetime.now(timezone.utc).isoformat()}}
                )
            )
            expiry_str = "Never"
            search_info = f"{searches} credits added to balance"
        else:
            # Daily-limit subscription
            expiry = datetime.now(timezone.utc) + timedelta(days=validity_days)
            expiry_str = expiry.strftime("%d %b %Y")
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "subscription": plan_id,
                        "subscription_expiry": expiry.isoformat(),
                        "subscription_daily_limit": daily_limit,
                        "subscription_used_today": 0,
                        "subscription_reset_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "last_seen": datetime.now(timezone.utc).isoformat()
                    }}
                )
            )
            search_info = f"{daily_limit} searches/day until {expiry_str}"

        # Update payment status
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.pending_payments.update_one(
                {"payment_id": payment_id},
                {"$set": {"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat(),
                          "approved_by": event.sender_id}}
            )
        )

        # Record payment
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.payments.insert_one({
                "user_id": user_id,
                "plan_id": plan_id,
                "amount": plan.get("price", 0),
                "status": "completed",
                "payment_id": payment_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        )

        # Notify user
        try:
            await bot_client.send_message(
                user_id,
                f"**Credits activated**"
                f"\n\n"
                f"> Plan: {plan['name']}"
                f"\n"
                f"> {search_info}"
                f"\n\n"
                f"Use /start to begin searching. Questions? @darkboxesAdmin",
                parse_mode="md"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

        await event.edit(
            f"✅ **PAYMENT APPROVED**\n\n"
            f"Payment ID: `{payment_id}`\n"
            f"User: `{user_id}`\n"
            f"Plan: {plan['name']}\n"
            f"{search_info}\n\n"
            f"User notified.",
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ Error approving payment: {e}")
        await event.answer("❌ Error approving payment", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^reject_payment_([A-Z0-9]+)_(\d+)$'))
async def reject_payment_callback(event):
    """Admin rejects payment"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return

        data = event.data.decode()
        parts = data.split('_')
        payment_id = parts[2]
        user_id = int(parts[3])

        # Update payment status
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.pending_payments.update_one(
                {"payment_id": payment_id},
                {"$set": {"status": "rejected", "rejected_at": datetime.now(timezone.utc).isoformat()}}
            )
        )

        # Notify user
        try:
            await bot_client.send_message(
                user_id,
                f"**Payment not verified**"
                f"\n\n"
                f"> Payment ID: `{payment_id}`"
                f"\n\n"
                f"Your UTR could not be verified. Common reasons: wrong UTR, wrong amount, or wrong UPI ID."
                f"\n\n"
                f"Contact @darkboxesAdmin with your correct UTR number to resolve.",
                parse_mode="md"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

        await event.edit(
            f"❌ **PAYMENT REJECTED**\n\nPayment ID: `{payment_id}`\nUser `{user_id}` has been notified.",
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ Error rejecting payment: {e}")
        await event.answer("❌ Error rejecting payment", alert=True)


async def handle_admin_reset_password(event):
    """Admin typed an account ID for password reset — confirm and do it."""
    try:
        account_id_input = event.text.strip().upper()
        if not account_id_input.startswith("DB") or len(account_id_input) < 4:
            await event.respond(
                "❌ Invalid Account ID. Format: `DBXXXXXX` (e.g. `DBEFBF325A`)\n"
                "Try again or press « Admin Panel to cancel.",
                parse_mode="md"
            )
            return

        loop = asyncio.get_running_loop()
        account = await loop.run_in_executor(
            None, lambda: db_manager.db.accounts.find_one({"account_id": account_id_input})
        )
        if not account:
            await event.respond(
                f"❌ Account `{account_id_input}` not found in the database.\n"
                "Check the ID and try again.",
                parse_mode="md"
            )
            return

        import secrets as _sec
        import hashlib as _hl
        temp_pass = _sec.token_urlsafe(8)
        pwd_hash = _hl.sha256(temp_pass.encode()).hexdigest()
        await loop.run_in_executor(
            None, lambda: db_manager.db.accounts.update_one(
                {"account_id": account_id_input},
                {"$set": {"password_hash": pwd_hash, "temp_password": True}}
            )
        )
        user_states.pop(event.sender_id, None)

        linked_ids = account.get("linked_tg_ids", [])
        notified = 0
        for tg_id in linked_ids:
            try:
                await bot_client.send_message(
                    tg_id,
                    f"🔑 **PASSWORD RESET — DARKBOXES**\n\n"
                    f"An admin has reset your account password.\n\n"
                    f"🆔 **Account ID:** `{account_id_input}`\n"
                    f"🔐 **New Temporary Password:** `{temp_pass}`\n\n"
                    f"⚠️ Please log in and note this password securely.\n"
                    f"Contact @darkboxesAdmin if you need further help.",
                    parse_mode="md"
                )
                notified += 1
            except Exception:
                pass

        await event.respond(
            f"✅ **PASSWORD RESET DONE**\n\n"
            f"🆔 Account ID: `{account_id_input}`\n"
            f"🔐 New Temporary Password: `{temp_pass}`\n"
            f"📲 Notified {notified}/{len(linked_ids)} linked Telegram account(s)\n\n"
            f"📋 Share this with the user via a secure channel.\n"
            f"They should change it after logging in.",
            buttons=[[Button.inline("« Admin Panel", "admin_panel")]],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ handle_admin_reset_password: {e}")
        await event.respond("❌ Error resetting password.")


async def handle_admin_give_subscription(event):
    """Handle admin giving subscription — accepts TG user ID, @username, or Account ID (DB…)"""
    try:
        user_input = event.text.strip()
        parts = user_input.split()

        plan_ids_list = "\n".join(
            f"  • `{k}` — {v['name']} (₹{v['price']})"
            for k, v in SUBSCRIPTION_PLANS.items()
        )

        if len(parts) < 2:
            await event.respond(
                "❌ **Invalid format.**\n\n"
                "Use: `identifier plan_id`\n\n"
                "**Identifier can be:**\n"
                "• Telegram user ID: `123456789`\n"
                "• @username: `@johndoe`\n"
                "• Account ID: `DB1A2B3C4D`\n\n"
                "**Available plan IDs:**\n"
                f"{plan_ids_list}\n\n"
                "**Examples:**\n"
                "`123456789 credits_5`\n"
                "`@johndoe sub_num_monthly`\n"
                "`DB1A2B3C4D sub_all_monthly`",
                parse_mode="md"
            )
            return

        identifier = parts[0].strip()
        plan_id    = parts[1].strip().lower()

        # Validate plan
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.respond(
                f"❌ **Unknown plan:** `{plan_id}`\n\n"
                f"**Valid plan IDs:**\n{plan_ids_list}",
                parse_mode="md"
            )
            return

        plan = SUBSCRIPTION_PLANS[plan_id]

        # Resolve identifier → user_id + user doc
        loop = asyncio.get_running_loop()
        user = None
        user_id = None

        if identifier.lstrip('@').upper().startswith('DB') and len(identifier) >= 6:
            # Account ID (DB…)
            acc_id = identifier.lstrip('@').upper()
            account = await loop.run_in_executor(
                None, lambda: db_manager.db.accounts.find_one({"account_id": acc_id})
            )
            if account:
                tg_ids = account.get("linked_tg_ids", [])
                if tg_ids:
                    user_id = tg_ids[0]
                    user = await db_manager.get_user(user_id)
                    # Also update the accounts collection directly
                else:
                    # No linked TG — update account directly
                    await _apply_plan_to_account(acc_id, plan_id, plan)
                    await event.respond(
                        f"✅ **PLAN APPLIED TO ACCOUNT**\n\n"
                        f"🆔 Account: `{acc_id}`\n"
                        f"📦 Plan: {plan['name']}\n\n"
                        f"⚠️ Account has no linked Telegram ID — user could not be notified.",
                        parse_mode="md"
                    )
                    user_states.pop(event.sender_id, None)
                    return
            else:
                await event.respond(f"❌ Account ID `{acc_id}` not found.", parse_mode="md")
                return

        elif identifier.startswith('@'):
            # @username
            uname = identifier.lstrip('@').lower()
            user = await loop.run_in_executor(
                None, lambda: db_manager.db.users.find_one({"username": {"$regex": f"^{re.escape(uname)}$", "$options": "i"}})
            )
            if not user:
                await event.respond(f"❌ Username `@{uname}` not found.", parse_mode="md")
                return
            user_id = user["user_id"]

        elif identifier.isdigit():
            # Numeric TG user ID
            user_id = int(identifier)
            user = await db_manager.get_user(user_id)
            if not user:
                await event.respond(f"❌ No user found with Telegram ID `{user_id}`.", parse_mode="md")
                return

        else:
            # Try as username without @
            user = await loop.run_in_executor(
                None, lambda: db_manager.db.users.find_one({"username": {"$regex": f"^{re.escape(identifier)}$", "$options": "i"}})
            )
            if not user:
                await event.respond(
                    f"❌ Could not resolve `{identifier}`.\n\n"
                    "Accepted formats: TG user ID, @username, or Account ID (DB…)",
                    parse_mode="md"
                )
                return
            user_id = user["user_id"]

        # Apply plan
        plan_type     = plan.get("plan_type", "credit")
        validity_days = plan.get("validity_days", 0)
        daily_limit   = plan.get("daily_limit", 0)
        searches      = plan.get("searches", 0)
        plan_name     = plan.get("name", plan_id)

        if plan_type == "credit":
            await loop.run_in_executor(
                None, lambda: db_manager.db.users.update_one(
                    {"user_id": user_id},
                    {"$inc": {"searches_remaining": searches},
                     "$set": {"last_seen": datetime.now(timezone.utc).isoformat()}}
                )
            )
            result_str = f"{searches} credits added to balance"
            expiry_str = "Never (credits never expire)"
        else:
            expiry = datetime.now(timezone.utc) + timedelta(days=validity_days)
            expiry_str = expiry.strftime("%d %b %Y")
            await loop.run_in_executor(
                None, lambda: db_manager.db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "subscription": plan_id,
                        "subscription_expiry": expiry.isoformat(),
                        "subscription_daily_limit": daily_limit,
                        "subscription_used_today": 0,
                        "subscription_reset_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "last_seen": datetime.now(timezone.utc).isoformat()
                    }}
                )
            )
            result_str = f"{daily_limit} searches/day for {validity_days} days"

        fname = user.get('first_name', 'N/A') if user else 'N/A'
        uname_disp = f"@{user.get('username')}" if user and user.get('username') else str(user_id)

        await event.respond(
            f"✅ **PLAN GRANTED SUCCESSFULLY**\n\n"
            f"👤 User: {fname} ({uname_disp})\n"
            f"🆔 TG ID: `{user_id}`\n"
            f"📦 Plan: **{plan_name}**\n"
            f"🔍 {result_str}\n"
            f"📅 Valid: {expiry_str}\n\n"
            f"User has been notified.",
            parse_mode="md"
        )

        # Notify user in Telegram
        try:
            await bot_client.send_message(
                user_id,
                f"🎁 **PLAN ACTIVATED BY ADMIN!**\n\n"
                f"✅ **{plan_name}** has been activated on your account!\n"
                f"🔍 {result_str}\n"
                f"📅 Valid: {expiry_str}\n\n"
                f"Use /start to begin searching 🚀",
                parse_mode="md"
            )
        except Exception:
            pass

        user_states.pop(event.sender_id, None)

    except Exception as e:
        logger.error(f"❌ Error giving subscription: {e}")
        await event.respond("❌ Error processing subscription. Check logs.")


async def _apply_plan_to_account(acc_id: str, plan_id: str, plan: dict):
    """Apply a plan directly to an accounts document (no TG link)."""
    loop = asyncio.get_running_loop()
    plan_type     = plan.get("plan_type", "credit")
    validity_days = plan.get("validity_days", 0)
    daily_limit   = plan.get("daily_limit", 0)
    searches      = plan.get("searches", 0)

    if plan_type == "credit":
        await loop.run_in_executor(
            None, lambda: db_manager.db.accounts.update_one(
                {"account_id": acc_id},
                {"$inc": {"searches_remaining": searches}}
            )
        )
    else:
        expiry = datetime.now(timezone.utc) + timedelta(days=validity_days)
        await loop.run_in_executor(
            None, lambda: db_manager.db.accounts.update_one(
                {"account_id": acc_id},
                {"$set": {
                    "subscription": plan_id,
                    "subscription_expiry": expiry.isoformat(),
                    "subscription_daily_limit": daily_limit,
                    "subscription_used_today": 0,
                    "subscription_reset_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }}
            )
        )


async def handle_admin_broadcast_select_users(event):
    """Handle admin entering user IDs for selected media broadcast"""
    try:
        sender_id = event.sender_id
        text = (event.text or "").strip()

        # Parse user IDs from comma-separated input
        raw_ids = [x.strip() for x in text.replace(" ", ",").split(",") if x.strip().isdigit()]
        if not raw_ids:
            await event.respond(
                "❌ No valid user IDs found.\n\n"
                "Enter numeric user IDs separated by commas:\n"
                "Example: `123456789, 987654321`"
            )
            return

        target_ids = [int(uid) for uid in raw_ids]

        # Update state to await media
        user_states[sender_id] = {
            "action": "admin_broadcast_media",
            "broadcast_target": target_ids,
            "broadcast_caption": ""
        }

        await event.respond(
            f"✅ **{len(target_ids)} users selected**\n\n"
            f"IDs: {', '.join(raw_ids[:5])}{'...' if len(raw_ids) > 5 else ''}\n\n"
            f"Now send your **photo or video** (with optional caption):",
            buttons=[[Button.inline("❌ Cancel", "admin_panel")]]
        )

    except Exception as e:
        logger.error(f"❌ Error in handle_admin_broadcast_select_users: {e}")
        await event.respond("❌ Error processing user IDs.")


async def handle_admin_broadcast_media(event):
    """Handle admin media broadcast (photo/video with caption)"""
    try:
        sender_id = event.sender_id
        state = user_states.get(sender_id, {})
        target_type = state.get("broadcast_target", "all")  # "all" or user_id list
        caption = state.get("broadcast_caption", "")

        if not (event.photo or event.video or event.document):
            await event.respond(
                "⚠️ Please send a **photo or video** (with optional caption).\n"
                "Or type /cancel to cancel."
            )
            return

        media = event.media
        final_caption = event.message.message or caption or "📢 Announcement from DarkBoxes"

        await event.respond("📢 **SENDING MEDIA BROADCAST...**\n\nPlease wait...")

        if target_type == "all":
            users = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(db_manager.db.users.find({}, {"user_id": 1}))
            )
            target_ids = [u["user_id"] for u in users]
        else:
            target_ids = target_type if isinstance(target_type, list) else [target_type]

        # Create broadcast record for seen tracking
        broadcast_id = str(uuid.uuid4())[:12].upper()
        broadcast_doc = {
            "broadcast_id": broadcast_id,
            "sender_id": sender_id,
            "media_type": "photo" if event.photo else "video",
            "caption": final_caption,
            "total_recipients": len(target_ids),
            "sent_count": 0,
            "failed_count": 0,
            "seen_by": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.broadcasts.insert_one(broadcast_doc)
        )

        sent = 0
        failed = 0

        for uid in target_ids:
            try:
                msg = await bot_client.send_file(
                    uid,
                    file=media,
                    caption=f"{final_caption}\n\n[BC:{broadcast_id}]",
                    parse_mode="md"
                )
                sent += 1
                await asyncio.sleep(0.1)
            except Exception:
                failed += 1

        # Update broadcast record
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.broadcasts.update_one(
                {"broadcast_id": broadcast_id},
                {"$set": {"sent_count": sent, "failed_count": failed}}
            )
        )

        user_states.pop(sender_id, None)

        await event.respond(
            f"✅ **MEDIA BROADCAST SENT**\n\n"
            f"📊 Broadcast ID: `{broadcast_id}`\n"
            f"📤 Sent: {sent}\n"
            f"❌ Failed: {failed}\n"
            f"📋 Total: {len(target_ids)}\n\n"
            f"Use Admin Panel → View Broadcasts to see who has seen it.",
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ Error in handle_admin_broadcast_media: {e}")
        await event.respond("❌ Error sending media broadcast.")


async def handle_search_query(event, state):
    """Handle search queries with free-user gating, validity checking, and result masking."""
    try:
        user_id = event.sender_id
        search_type = state["type"]
        query = event.text.strip()

        if not query:
            await event.respond("❌ Please enter a valid query.")
            return

        # Check if query is protected
        is_protected = await db_manager.protected_manager.is_query_protected(query)
        if is_protected:
            await event.respond(
                "🔒 **QUERY PROTECTED**\n\n"
                f"This query has been restricted by administration.\n\n"
                f"📝 **Query:** `{query}`\n"
                f"⚠️ **Status:** Protected\n\n"
                "If you believe this is an error, please contact @darkboxesAdmin for assistance.",
                parse_mode="md"
            )
            user_states.pop(user_id, None)
            return

        # Validate query format
        cmd = SEARCH_COMMANDS.get(search_type, {})
        validation = cmd.get("validation")
        if validation and not re.match(validation, query):
            await event.respond(f"❌ Invalid format. Example: `{cmd.get('example', 'N/A')}`")
            return

        # ── Determine user access level ───────────────────────────────────────
        user_doc = await db_manager.get_user(user_id)
        has_active_sub = False
        sub_allows_command = True   # does subscription cover this command?
        has_credits = (user_doc.get("searches_remaining", 0) > 0) if user_doc else False

        if user_doc and user_doc.get("subscription") and user_doc.get("subscription_expiry"):
            try:
                expiry_date = datetime.fromisoformat(user_doc["subscription_expiry"])
                if expiry_date > datetime.now(timezone.utc):
                    has_active_sub = True
                    # Check subscription command scope
                    plan_id = user_doc.get("subscription")
                    plan = SUBSCRIPTION_PLANS.get(plan_id, {})
                    allowed_cmds = plan.get("allowed_commands", [])
                    if allowed_cmds and search_type not in allowed_cmds:
                        sub_allows_command = False
            except Exception:
                pass

        can_search_paid = has_active_sub and sub_allows_command
        can_search_credit = has_credits and not (has_active_sub and not sub_allows_command)

        is_free_user = not can_search_paid and not can_search_credit

        # Free-user command restriction check
        free_cmd_restriction = FREE_USER_CONFIG.get("allowed_commands", [])
        if is_free_user and free_cmd_restriction and search_type not in free_cmd_restriction:
            await event.respond(
                "🔒 **COMMAND RESTRICTED**\n\n"
                f"The `{search_type}` search requires a paid plan or credits.\n\n"
                "Choose a plan below to unlock this command:",
                buttons=OneLineKeyboard.subscription_plans(),
                parse_mode="md"
            )
            user_states.pop(user_id, None)
            return

        # ── ACCESS POLICY ────────────────────────────────────────────────────
        # ALL users (including zero-credit and expired-sub users) can search.
        # Paid users → full unmasked result.
        # Free / zero-credit / expired-sub users → masked result + buy prompt.
        # Only exception: if admin has set a free_cmd_restriction and this
        # command isn't in it, block the search entirely (no masked fallback).
        # ─────────────────────────────────────────────────────────────────────
        should_mask = is_free_user  # mask for free/zero-credit users

        # If subscription covers a command-restricted plan and user has no credits,
        # we still let them search but mask the result (treat as free user).
        if has_active_sub and not sub_allows_command:
            if not has_credits:
                # subscription doesn't cover this command AND no credits → mask
                is_free_user = True
                should_mask = True

        # Show processing message
        if search_type == "leak":
            status = await event.respond(
                "🚀 **ADVANCED OSINT SEARCH INITIATED**\n\n"
                f"🔍 **Query:** `{query}`\n"
                f"⚡ **Processing:** Ultra-fast (5 seconds)\n"
                f"📁 **Output:** JSON + TXT files\n"
                f"💎 **Cost:** 3 credits\n\n"
                f"⚠️ **Note:** For phone numbers, include country code (e.g., 917204764637)\n"
                f"⏳ Processing your advanced search...",
                parse_mode="md"
            )
        else:
            status = await event.respond(PremiumFormatter.format_processing(search_type, query), parse_mode="md")

        # ── Perform the search ────────────────────────────────────────────────
        result = await search_engine.perform_search(
            search_type, query, user_id, is_free_user=is_free_user
        )

        try:
            await status.delete()
        except Exception:
            pass

        if result["success"]:
            if should_mask:
                # Zero-credit / free users: show masked preview + buy button
                raw_for_mask = result.get("raw_result") or result.get("result", "")
                multi = result.get("multi_results", [])
                if not raw_for_mask and multi:
                    raw_for_mask = multi[0].get("raw_result", "")
                masked_text = TextProcessor.mask_result(raw_for_mask)
                buy_buttons = [
                    [Button.inline("🔓 Buy This Data! — Subscribe or Get Credits", "buy_data_prompt")],
                    [Button.inline("📋 View Plans", "premium")],
                ]
                await event.respond(
                    "🔍 **RESULT FOUND — PREVIEW (MASKED)**\n\n"
                    f"Data exists for `{query}`. Unlock to see full details:\n\n"
                    f"```\n{masked_text[:800]}\n```\n\n"
                    "🔒 _Purchase to reveal complete unmasked data_",
                    buttons=buy_buttons,
                    parse_mode="md"
                )
                # Log but don't charge credits for free preview
                await db_manager.update_searches(user_id, search_type, query, True,
                    response_preview=raw_for_mask[:2000], is_free_user=True)

            elif result.get("has_multiple_files"):
                # Leak search — send files
                try:
                    await event.respond(result["result"], parse_mode="md")
                except Exception:
                    await event.respond(result["result"])
                for file_data in result.get("files", []):
                    if file_data.get("raw_bytes"):
                        file_type = file_data.get("file_type", "unknown")
                        caption = f"📁 **{file_type.upper()} DATA**\nQuery: `{query}`"
                        filename = file_data.get("filename") or f"leak_{query}_{int(time.time())}.{file_type}"
                        try:
                            await event.respond(file=file_data["raw_bytes"], caption=caption, parse_mode="md")
                        except Exception:
                            await event.respond(file=file_data["raw_bytes"], caption=caption)
                preview = result.get("raw_result", result.get("result", ""))[:200]
                await db_manager.update_searches(user_id, search_type, query, True, response_preview=preview)

            elif result.get("multi_results") and len(result["multi_results"]) > 1:
                # Multiple valid results from different groups — send all
                multi = result["multi_results"]
                count = len(multi)
                await event.respond(
                    f"📊 **{count} SOURCES FOUND** for `{query}`\n"
                    f"Sending all results below ↓",
                    parse_mode="md"
                )
                for idx, r in enumerate(multi, 1):
                    header = f"**━━ Result {idx}/{count} ━━**\n"
                    body = r.get("result", "")
                    try:
                        await event.respond(header + body, parse_mode="md")
                    except Exception:
                        await event.respond(header + body)
                preview = result.get("raw_result", "")[:200]
                await db_manager.update_searches(user_id, search_type, query, True, response_preview=preview)

            else:
                # Single result
                try:
                    await event.respond(result["result"], parse_mode="md")
                except Exception as e:
                    logger.error(f"Error sending formatted result: {e}")
                    await event.respond(result["result"])
                preview = result.get("raw_result", result.get("result", ""))[:200]
                await db_manager.update_searches(user_id, search_type, query, True, response_preview=preview)

        else:
            error_msg = result.get("error", "❌ No results found.")
            try:
                await event.respond(error_msg, parse_mode="md")
            except Exception:
                await event.respond(error_msg)
            await db_manager.update_searches(user_id, search_type, query, False, response_preview="")

        user_states.pop(user_id, None)

    except Exception as e:
        logger.error(f"❌ Error in handle_search_query: {e}")
        logger.error(traceback.format_exc())
        try:
            await event.respond(
                "❌ **SYSTEM ERROR**\n\n"
                "An unexpected error occurred while processing your search.\n\n"
                f"📝 **Query:** `{query if 'query' in locals() else 'Unknown'}`\n"
                f"🔍 **Type:** {search_type if 'search_type' in locals() else 'Unknown'}\n\n"
                "⚠️ **This error has been logged.**\n"
                "Please try again or contact @darkboxesAdmin for assistance.",
                parse_mode="md"
            )
        except Exception:
            await event.respond("❌ An error occurred. Please try again or contact support.")
        finally:
            user_states.pop(user_id, None)

async def handle_admin_search_user(event):
    """Handle admin user search"""
    try:
        query = event.text.strip()
        if not query:
            await event.respond("❌ Please enter a search query.")
            return
        
        users = await db_manager.admin_db.search_users(query)
        
        if not users:
            await event.respond("❌ No users found matching your query.")
            user_states.pop(event.sender_id, None)
            return
        
        if len(users) == 1:
            # Show single user detail
            user = users[0]
            await admin_panel.show_user_detail(event, user['user_id'])
        else:
            # Show list of users
            result_text = f"🔍 **SEARCH RESULTS** ({len(users)} users found)\n\n"
            
            for i, user in enumerate(users[:10], 1):
                username = f"@{user['username']}" if user.get('username') else "No username"
                joined = user.get('joined_at', '')[:10]
                searches = user.get('total_searches', 0)
                
                result_text += (
                    f"{i}. **{user['first_name']}**\n"
                    f"   ├─ {username}\n"
                    f"   ├─ ID: `{user['user_id']}`\n"
                    f"   ├─ Joined: {joined}\n"
                    f"   └─ Searches: {searches}\n\n"
                )
            
            if len(users) > 10:
                result_text += f"... and {len(users) - 10} more users\n"
            
            result_text += "\nClick on a user ID to view details:"
            
            # Create buttons with user IDs
            buttons = []
            for user in users[:5]:
                buttons.append([Button.inline(
                    f"👤 {user['first_name']} (ID: {user['user_id']})",
                    f"user_detail_{user['user_id']}"
                )])
            
            buttons.append([Button.inline("« Back to Admin", "admin_panel")])
            
            await event.respond(result_text, buttons=buttons, parse_mode="md")
        
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_search_user: {e}")
        await event.respond("❌ Error searching users.")

async def handle_admin_broadcast(event):
    """Handle admin broadcast"""
    try:
        message = event.text.strip()
        if not message or len(message) < 5:
            await event.respond("❌ Message too short. Minimum 5 characters required.")
            return
        
        # Confirm broadcast
        confirm_text = (
            f"📢 **BROADCAST CONFIRMATION**\n\n"
            f"**Message:**\n{message[:500]}...\n\n"
            f"**This message will be sent to all users.**\n"
            f"Estimated recipients: [Calculating...]\n\n"
            f"Are you sure you want to proceed?"
        )
        
        # Store message for confirmation
        user_states[event.sender_id] = {
            "action": "confirm_broadcast",
            "message": message
        }
        
        buttons = [
            [Button.inline("✅ Yes, Send Broadcast", "confirm_broadcast_yes")],
            [Button.inline("❌ Cancel", "admin_panel")]
        ]
        
        await event.respond(confirm_text, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_broadcast: {e}")
        await event.respond("❌ Error processing broadcast message.")

async def handle_admin_ban(event):
    """Handle admin ban user"""
    try:
        user_input = event.text.strip()
        if not user_input.isdigit():
            await event.respond("❌ Please enter a valid numeric user ID.")
            return
        
        user_id = int(user_input)
        user = await db_manager.get_user(user_id)
        
        if not user:
            await event.respond(f"❌ User with ID {user_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        if user.get('is_banned'):
            # User is already banned, show unban option
            buttons = OneLineKeyboard.confirm_buttons("unban", user_id)
            await event.respond(
                f"🚫 **USER IS ALREADY BANNED**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📅 Banned on: {user.get('banned_at', 'N/A')[:10]}\n"
                f"📝 Reason: {user.get('ban_reason', 'N/A')}\n\n"
                f"Do you want to unban this user?",
                buttons=buttons,
                parse_mode="md"
            )
        else:
            # User is not banned, show ban option
            buttons = OneLineKeyboard.confirm_buttons("ban", user_id)
            await event.respond(
                f"🚫 **BAN USER CONFIRMATION**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📅 Joined: {user.get('joined_at', 'N/A')[:10]}\n"
                f"📊 Searches: {user.get('total_searches', 0)}\n\n"
                f"Are you sure you want to ban this user?",
                buttons=buttons,
                parse_mode="md"
            )
        
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_ban: {e}")
        await event.respond("❌ Error processing ban request.")

async def handle_admin_management(event):
    """Handle admin management"""
    try:
        user_input = event.text.strip()
        if not user_input.isdigit():
            await event.respond("❌ Please enter a valid numeric user ID.")
            return
        
        user_id = int(user_input)
        user = await db_manager.get_user(user_id)
        
        if not user:
            await event.respond(f"❌ User with ID {user_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        if user.get('is_admin'):
            # User is already admin, show remove option
            buttons = OneLineKeyboard.confirm_buttons("remove_admin", user_id)
            await event.respond(
                f"👑 **REMOVE ADMIN PRIVILEGES**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📅 Joined: {user.get('joined_at', 'N/A')[:10]}\n\n"
                f"This user currently has admin privileges.\n"
                f"Do you want to remove admin privileges?",
                buttons=buttons,
                parse_mode="md"
            )
        else:
            # User is not admin, show add option
            buttons = OneLineKeyboard.confirm_buttons("add_admin", user_id)
            await event.respond(
                f"👑 **ADD ADMIN PRIVILEGES**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📅 Joined: {user.get('joined_at', 'N/A')[:10]}\n"
                f"📊 Searches: {user.get('total_searches', 0)}\n\n"
                f"Are you sure you want to add this user as admin?",
                buttons=buttons,
                parse_mode="md"
            )
        
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_management: {e}")
        await event.respond("❌ Error processing admin management request.")

async def handle_admin_add_credits(event):
    """Handle admin add credits — accepts TG user ID, @username, or Account ID (DB…)"""
    try:
        user_input = event.text.strip()
        state = user_states.get(event.sender_id, {})
        preset_user_id = state.get("preset_user_id")
        loop = asyncio.get_running_loop()

        if preset_user_id:
            # User was pre-selected from the user detail panel — only need credits amount
            if not user_input.isdigit():
                await event.respond(
                    "❌ Please enter a valid number of credits (1–10000).",
                    parse_mode="md"
                )
                return
            user_id = preset_user_id
            credits = int(user_input)
            user = await db_manager.get_user(user_id)

        else:
            # Expect: identifier credits
            # Identifier: TG ID, @username, or Account ID (DB…)
            parts = user_input.rsplit(None, 1)   # split from the right so username spaces don't break it
            if len(parts) != 2:
                await event.respond(
                    "❌ **Invalid format.**\n\n"
                    "Use: `identifier credits`\n\n"
                    "**Identifier can be:**\n"
                    "• Telegram user ID: `123456789 10`\n"
                    "• @username: `@johndoe 10`\n"
                    "• Account ID: `DB1A2B3C4D 10`",
                    parse_mode="md"
                )
                return

            identifier, credits_str = parts[0].strip(), parts[1].strip()

            if not credits_str.isdigit():
                await event.respond("❌ Credits must be a number. Format: `identifier credits`", parse_mode="md")
                return

            credits = int(credits_str)
            user = None
            user_id = None

            # Resolve identifier
            if identifier.lstrip('@').upper().startswith('DB') and len(identifier) >= 6:
                # Account ID
                acc_id = identifier.lstrip('@').upper()
                account = await loop.run_in_executor(
                    None, lambda: db_manager.db.accounts.find_one({"account_id": acc_id})
                )
                if account:
                    tg_ids = account.get("linked_tg_ids", [])
                    if tg_ids:
                        user_id = tg_ids[0]
                        user = await db_manager.get_user(user_id)
                    else:
                        # Apply directly to accounts collection
                        await loop.run_in_executor(
                            None, lambda: db_manager.db.accounts.update_one(
                                {"account_id": acc_id},
                                {"$inc": {"searches_remaining": credits}}
                            )
                        )
                        await event.respond(
                            f"✅ **{credits} CREDITS ADDED** to account `{acc_id}`\n\n"
                            f"⚠️ Account has no linked Telegram ID — user could not be notified.",
                            parse_mode="md"
                        )
                        user_states.pop(event.sender_id, None)
                        return
                else:
                    await event.respond(f"❌ Account ID `{acc_id}` not found.", parse_mode="md")
                    return

            elif identifier.startswith('@'):
                uname = identifier.lstrip('@').lower()
                user = await loop.run_in_executor(
                    None, lambda: db_manager.db.users.find_one(
                        {"username": {"$regex": f"^{re.escape(uname)}$", "$options": "i"}}
                    )
                )
                if not user:
                    await event.respond(f"❌ Username `@{uname}` not found.", parse_mode="md")
                    return
                user_id = user["user_id"]

            elif identifier.isdigit():
                user_id = int(identifier)
                user = await db_manager.get_user(user_id)
                if not user:
                    await event.respond(f"❌ No user found with Telegram ID `{user_id}`.", parse_mode="md")
                    return

            else:
                # Try as bare username
                user = await loop.run_in_executor(
                    None, lambda: db_manager.db.users.find_one(
                        {"username": {"$regex": f"^{re.escape(identifier)}$", "$options": "i"}}
                    )
                )
                if not user:
                    await event.respond(
                        f"❌ Could not resolve `{identifier}`.\n\n"
                        "Use TG user ID, @username, or Account ID (DB…)",
                        parse_mode="md"
                    )
                    return
                user_id = user["user_id"]

        if credits <= 0 or credits > 10000:
            await event.respond("❌ Credits must be between 1 and 10,000.")
            return

        if not user:
            user = await db_manager.get_user(user_id)
        if not user:
            await event.respond(f"❌ User `{user_id}` not found in database.")
            user_states.pop(event.sender_id, None)
            return

        success = await db_manager.add_credits(user_id, credits)

        if success:
            new_balance = user.get('searches_remaining', 0) + credits
            fname      = user.get('first_name', 'N/A')
            uname_disp = f"@{user.get('username')}" if user.get('username') else str(user_id)

            await event.respond(
                f"✅ **CREDITS ADDED SUCCESSFULLY**\n\n"
                f"👤 User: {fname} ({uname_disp})\n"
                f"🆔 TG ID: `{user_id}`\n"
                f"🎯 Credits Added: **{credits}**\n"
                f"💰 New Balance: **{new_balance}**\n\n"
                f"User has been notified.",
                parse_mode="md"
            )

            try:
                await bot_client.send_message(
                    user_id,
                    f"🎁 **{credits} CREDITS ADDED!**\n\n"
                    f"Administrator has added **{credits} credits** to your account.\n"
                    f"💰 New Balance: **{new_balance} credits**\n\n"
                    f"Thank you for using DarkBoxes! 🚀",
                    parse_mode="md"
                )
            except Exception:
                pass
        else:
            await event.respond("❌ Failed to add credits. Check logs.")

        user_states.pop(event.sender_id, None)

    except Exception as e:
        logger.error(f"❌ Error in handle_admin_add_credits: {e}")
        await event.respond("❌ Error adding credits.")

async def handle_admin_give_credits_all(event):
    """Handle admin giving credits to ALL users"""
    try:
        user_input = event.text.strip()
        if not user_input.isdigit() or int(user_input) <= 0:
            await event.respond("❌ Please enter a valid positive number of credits.")
            return
        credits = int(user_input)
        if credits > 10000:
            await event.respond("❌ Maximum 10,000 credits per operation.")
            return

        user_states.pop(event.sender_id, None)
        buttons = [
            [Button.inline(f"✅ YES — Give {credits} credits to ALL users", f"admin_confirm_give_all_{credits}")],
            [Button.inline("❌ Cancel", "admin_panel")]
        ]
        await event.respond(
            f"⚠️ **CONFIRM BULK CREDIT GRANT**\n\n"
            f"You are about to give **{credits} credits** to EVERY registered user.\n"
            f"This action cannot be undone.\n\n"
            f"Are you sure?",
            buttons=buttons,
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ handle_admin_give_credits_all: {e}")
        await event.respond("❌ Error processing request.")
        user_states.pop(event.sender_id, None)


async def handle_admin_take_credits_user(event):
    """Handle admin taking credits from a specific user"""
    try:
        user_input = event.text.strip()
        loop = asyncio.get_running_loop()

        parts = user_input.rsplit(None, 1)
        if len(parts) != 2:
            await event.respond(
                "❌ **Invalid format.**\n\nUse: `identifier amount`\n"
                "Example: `123456789 10` or `@username 5`",
                parse_mode="md"
            )
            return

        identifier, amount_str = parts[0].strip(), parts[1].strip()
        if not amount_str.isdigit() or int(amount_str) <= 0:
            await event.respond("❌ Amount must be a positive number.")
            return

        credits = int(amount_str)
        user = None
        user_id = None

        if identifier.startswith('@'):
            uname = identifier.lstrip('@').lower()
            user = await loop.run_in_executor(
                None, lambda: db_manager.db.users.find_one(
                    {"username": {"$regex": f"^{re.escape(uname)}$", "$options": "i"}}
                )
            )
            if user:
                user_id = user["user_id"]
        elif identifier.isdigit():
            user_id = int(identifier)
            user = await db_manager.get_user(user_id)
        else:
            user = await loop.run_in_executor(
                None, lambda: db_manager.db.users.find_one(
                    {"username": {"$regex": f"^{re.escape(identifier)}$", "$options": "i"}}
                )
            )
            if user:
                user_id = user["user_id"]

        if not user or not user_id:
            await event.respond(f"❌ User `{identifier}` not found.", parse_mode="md")
            user_states.pop(event.sender_id, None)
            return

        current_credits = user.get("searches_remaining", 0)
        actual_deduct   = min(credits, current_credits)
        success = await db_manager.take_credits(user_id, credits)

        fname  = user.get('first_name', 'N/A')
        uname  = f"@{user.get('username')}" if user.get('username') else str(user_id)

        if success:
            new_balance = max(0, current_credits - credits)
            await event.respond(
                f"✅ **CREDITS REMOVED SUCCESSFULLY**\n\n"
                f"👤 User: {fname} ({uname})\n"
                f"🔢 UID: `{user_id}`\n"
                f"➖ Removed: **{actual_deduct}** credits\n"
                f"💰 Old balance: {current_credits}\n"
                f"💰 New balance: **{new_balance}**\n"
                + (f"\n⚠️ User had fewer credits — floored at 0." if actual_deduct < credits else ""),
                parse_mode="md",
                buttons=OneLineKeyboard.back_to_admin()
            )
            try:
                await bot_client.send_message(
                    user_id,
                    f"⚠️ **CREDITS ADJUSTED BY ADMIN**\n\n"
                    f"An admin has removed **{actual_deduct} credits** from your account.\n"
                    f"💰 New balance: **{new_balance} credits**\n\n"
                    f"Contact @darkboxesAdmin for questions.",
                    parse_mode="md"
                )
            except Exception:
                pass
        else:
            await event.respond("❌ Failed to remove credits. Check logs.")

        user_states.pop(event.sender_id, None)

    except Exception as e:
        logger.error(f"❌ handle_admin_take_credits_user: {e}")
        await event.respond("❌ Error processing request.")
        user_states.pop(event.sender_id, None)


async def handle_admin_take_credits_all(event):
    """Handle admin removing credits from ALL users"""
    try:
        user_input = event.text.strip()
        if not user_input.isdigit() or int(user_input) <= 0:
            await event.respond("❌ Please enter a valid positive number of credits.")
            return
        credits = int(user_input)
        if credits > 10000:
            await event.respond("❌ Maximum 10,000 credits per operation.")
            return

        user_states.pop(event.sender_id, None)
        buttons = [
            [Button.inline(f"✅ YES — Remove {credits} credits from ALL users", f"admin_confirm_take_all_{credits}")],
            [Button.inline("❌ Cancel", "admin_panel")]
        ]
        await event.respond(
            f"⚠️ **CONFIRM BULK CREDIT REMOVAL**\n\n"
            f"You are about to remove up to **{credits} credits** from EVERY user.\n"
            f"Credits floor at 0 — no user will go negative.\n"
            f"This action cannot be undone.\n\n"
            f"Are you sure?",
            buttons=buttons,
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ handle_admin_take_credits_all: {e}")
        await event.respond("❌ Error processing request.")
        user_states.pop(event.sender_id, None)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_confirm_give_all_(\d+)$'))
async def admin_confirm_give_all_callback(event):
    """Execute bulk credit grant to ALL users"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        credits = int(event.data.decode().split("_")[-1])
        await event.edit(f"⏳ Giving {credits} credits to all users... please wait.")
        count = await db_manager.give_credits_all_users(credits)
        await event.edit(
            f"✅ **BULK CREDIT GRANT COMPLETE**\n\n"
            f"💰 Credits Added: **{credits}** per user\n"
            f"👥 Users Updated: **{count}**\n"
            f"💎 Total Credits Distributed: **{credits * count:,}**",
            buttons=OneLineKeyboard.back_to_admin(),
            parse_mode="md"
        )
        logger.info(f"✅ Admin {event.sender_id} gave {credits} credits to {count} users")
    except Exception as e:
        logger.error(f"❌ admin_confirm_give_all_callback: {e}")
        await event.answer("❌ Error executing bulk grant", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_confirm_take_all_(\d+)$'))
async def admin_confirm_take_all_callback(event):
    """Execute bulk credit removal from ALL users"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        credits = int(event.data.decode().split("_")[-1])
        await event.edit(f"⏳ Removing up to {credits} credits from all users... please wait.")
        count = await db_manager.take_credits_all_users(credits)
        await event.edit(
            f"✅ **BULK CREDIT REMOVAL COMPLETE**\n\n"
            f"➖ Credits Removed: up to **{credits}** per user\n"
            f"👥 Users Affected: **{count}**\n"
            f"⚠️ All balances floored at 0 — no negatives.",
            buttons=OneLineKeyboard.back_to_admin(),
            parse_mode="md"
        )
        logger.info(f"✅ Admin {event.sender_id} removed up to {credits} credits from {count} users")
    except Exception as e:
        logger.error(f"❌ admin_confirm_take_all_callback: {e}")
        await event.answer("❌ Error executing bulk removal", alert=True)



@bot_client.on(events.CallbackQuery(pattern=r'^confirm_broadcast_yes$'))
async def confirm_broadcast_handler(event):
    """Handle broadcast confirmation"""
    try:
        user_id = event.sender_id
        state = user_states.get(user_id, {})
        
        if state.get("action") != "confirm_broadcast":
            await event.answer("❌ No broadcast pending", alert=True)
            return
        
        message = state.get("message", "")
        if not message:
            await event.answer("❌ No message found", alert=True)
            return
        
        await event.edit("📢 **SENDING BROADCAST...**\n\nPlease wait...")
        
        # Get all users
        users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(db_manager.db.users.find({}, {"user_id": 1}))
        )
        
        sent = 0
        failed = 0
        
        broadcast_id = str(uuid.uuid4())[:12].upper()
        broadcast_text = (
            f"> 📢 **Announcement**\n"
            f"\n"
            f"{message}\n"
            f"\n"
            f"_— Dark Boxes Team_"
        )

        sent_msg_ids = {}  # {user_id: message_id}
        for user in users:
            try:
                msg = await bot_client.send_message(
                    user["user_id"],
                    broadcast_text,
                    parse_mode="md"
                )
                sent_msg_ids[str(user["user_id"])] = msg.id
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

        # Store broadcast with message IDs so admin can delete later
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.broadcasts.insert_one({
                "broadcast_id": broadcast_id,
                "sender_id": user_id,
                "media_type": "text",
                "caption": message[:200],
                "total_recipients": len(users),
                "sent_count": sent,
                "failed_count": failed,
                "seen_by": [],
                "sent_msg_ids": sent_msg_ids,
                "deleted": False,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        )

        user_states.pop(user_id, None)

        result_text = (
            f"✅ **Broadcast sent**\n"
            f"\n"
            f"> ID: `{broadcast_id}`\n"
            f"> Sent: {sent}  ·  Failed: {failed}\n"
            f"\n"
            f"_You can delete this broadcast from Broadcast History._"
        )

        await event.edit(result_text,
            buttons=[[Button.inline("🗑 Delete This Broadcast", f"del_broadcast_{broadcast_id}"),
                      Button.inline("« Admin", "admin_panel")]],
            parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in confirm_broadcast_handler: {e}")
        await event.answer("❌ Error sending broadcast", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^broadcast_media_(all|selected)$'))
async def broadcast_media_target_callback(event):
    """Handle broadcast media target selection"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        
        target = event.data.decode().split('_')[-1]
        sender_id = event.sender_id
        
        if target == "all":
            user_states[sender_id] = {
                "action": "admin_broadcast_media",
                "broadcast_target": "all",
                "broadcast_caption": ""
            }
            await event.edit(
                "🖼️ **MEDIA BROADCAST — ALL USERS**\n\n"
                "Send your photo or video now.\n"
                "You can add a caption directly in your message.\n\n"
                "📌 Supported: Photos, Videos, GIFs",
                buttons=[[Button.inline("❌ Cancel", "admin_panel")]]
            )
        else:
            await event.edit(
                "🔍 **MEDIA BROADCAST — SELECTED USERS**\n\n"
                "Enter the user IDs separated by commas:\n"
                "Example: `123456, 789012, 345678`\n\n"
                "Then send the media after confirming.",
                buttons=[[Button.inline("❌ Cancel", "admin_panel")]]
            )
            user_states[sender_id] = {
                "action": "admin_broadcast_select_users",
                "broadcast_target": "selected"
            }
    except Exception as e:
        logger.error(f"❌ Error in broadcast_media_target_callback: {e}")
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^buy_credits$'))
async def buy_credits_callback(event):
    """Handle buy credits callback"""
    try:
        await event.edit(
            "💳 **BUY CREDITS / UPGRADE PLAN**\n\n"
            "Select a plan to purchase:\n",
            buttons=OneLineKeyboard.subscription_plans(),
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"Error in buy_credits_callback: {e}")
        await event.answer("❌ Error", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^buy_data_prompt$'))
async def buy_data_prompt_callback(event):
    """Show buy options when user taps 'Buy This Data' on a masked result"""
    try:
        await event.edit(
            "🔓 **UNLOCK FULL DATA**\n\n"
            "Choose how to get the complete unmasked result:\n\n"
            "⚡ **₹200** → 5 credits (any command, no expiry)\n"
            "📱 **₹300/month** → Unlimited phone (NUM) searches\n"
            "💎 **₹499/month** → Unlimited ALL commands _(best value)_\n\n"
            f"> UPI: `{config.UPI_ID}`\n"
            "> After payment, contact @darkboxesAdmin with your UTR.\n\n"
            "_Activated within 5–15 min after admin verification._",
            buttons=[
                [Button.inline("⚡ 5 Credits · ₹200", "plan_credits_5")],
                [Button.inline("📱 Unlimited NUM · ₹300/mo", "plan_sub_num_monthly")],
                [Button.inline("💎 Unlimited ALL · ₹499/mo", "plan_sub_all_monthly")],
                [Button.inline("« Main Menu", "main_menu")],
            ],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"Error in buy_data_prompt_callback: {e}")
        await event.answer("❌ Error", alert=True)


async def track_broadcast_seen(event):
    """Track when users interact with broadcast messages (passive seen tracking)"""
    pass  # Seen tracking happens via read receipts in Telegram naturally


@bot_client.on(events.CallbackQuery(pattern=r'^noop$'))
async def noop_callback(event):
    """No-op callback for pagination display"""
    await event.answer("", alert=False)
    """Return to main menu"""
    try:
        user_id = event.sender_id
        user_states.pop(user_id, None)
        
        user_doc = await db_manager.get_user(user_id)
        is_admin = admin_panel.is_admin(user_id) if admin_panel else (user_id == config.ADMIN_USER_ID)
        
        message = (
            f"🎭 **DARK BOXES INTELLIGENCE**\n\n"
            f"📊 **ACCOUNT STATUS**\n"
            f"├─ Credits: {user_doc.get('searches_remaining', 0)}\n"
            f"├─ Total Searches: {user_doc.get('total_searches', 0)}\n"
            f"└─ Subscription: {user_doc.get('subscription', 'None')}\n\n"
            f"🛠️ **SELECT SERVICE**"
        )
        
        # Get keyboard - ONE COMMAND PER LINE
        buttons = OneLineKeyboard.main_menu(is_admin)
        
        await event.edit(message, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in main_menu_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^check_join$'))
async def check_join_callback(event):
    """Verify force-join membership after user taps the button."""
    try:
        user_id = event.sender_id
        missing = await check_force_join(user_id)
        if missing:
            await event.answer("❌ You haven't joined all required channels yet!", alert=True)
            ch_lines = "\n".join(
                "  ▸ " + (ch.get("title") or ch.get("username", "")) for ch in missing
            )
            msg = (
                "🔐 **Still not joined!**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Please join ALL channels listed below first:\n\n"
                + ch_lines +
                "\n\nAfter joining, tap **✅ I've Joined** again."
            )
            await event.edit(msg, buttons=_build_join_keyboard(missing), parse_mode="md")
        else:
            await event.answer("✅ Verified! Welcome to DarkBoxes.", alert=False)
            user_doc = await db_manager.get_user(user_id)
            sender   = await event.get_sender()
            if not user_doc:
                await db_manager.create_user(user_id, sender.username, sender.first_name, None)
                user_doc = await db_manager.get_user(user_id)
            is_admin = admin_panel.is_admin(user_id) if admin_panel else (user_id == config.ADMIN_USER_ID)
            welcome  = PremiumFormatter.format_welcome(sender.first_name, user_doc)
            try:
                _dis_doc = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: db_manager.db.settings.find_one({"_id": "disabled_buttons"})
                )
                _dis = set(_dis_doc.get("keys", []) if _dis_doc else [])
            except Exception:
                _dis = set()
            await event.edit(welcome, buttons=OneLineKeyboard.main_menu(is_admin, _dis), parse_mode="md")
    except Exception as e:
        logger.error(f"check_join_callback error: {e}")
        await event.answer("❌ Error verifying membership", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_force_join$'))
async def admin_force_join_callback(event):
    """Admin panel: manage force-join channels."""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        await _show_force_join_panel(event)
    except Exception as e:
        logger.error(f"admin_force_join_callback error: {e}")
        await event.answer("❌ Error", alert=True)


async def _show_force_join_panel(event):
    """Render the force-join management panel."""
    if FORCE_JOIN_CHANNELS:
        ch_lines = "\n".join(
            str(i + 1) + ".  " + (ch.get("title") or ch.get("username", "?"))
            + "  (@" + ch.get("username", "").lstrip("@") + ")"
            for i, ch in enumerate(FORCE_JOIN_CHANNELS)
        )
    else:
        ch_lines = "_No channels configured yet._"

    txt = (
        "📢 **Force-Join Channels**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Users must join these channels before using the bot:\n\n"
        + ch_lines +
        "\n\n"
        "Use the buttons below to add or remove channels.\n"
        "_Max 5 channels recommended._"
    )
    buttons = [
        [Button.inline("➕ Add Channel", "admin_fj_add"),
         Button.inline("🗑 Remove Channel", "admin_fj_remove")],
        [Button.inline("🔄 Reload from DB", "admin_fj_reload")],
        [Button.inline("« Admin Panel", "admin_panel")],
    ]
    try:
        await event.edit(txt, buttons=buttons, parse_mode="md")
    except Exception:
        await event.respond(txt, buttons=buttons, parse_mode="md")


@bot_client.on(events.CallbackQuery(pattern=r'^admin_fj_add$'))
async def admin_fj_add_callback(event):
    if not admin_panel.is_admin(event.sender_id):
        await event.answer("❌ Admin only", alert=True)
        return
    user_states[event.sender_id] = {"action": "admin_fj_add"}
    await event.edit(
        "➕ **Add Force-Join Channel**\n\n"
        "Send the channel **username** (with @) and optionally a display title.\n\n"
        "**Format:**\n"
        "> `@username  Display Title`\n\n"
        "**Examples:**\n"
        "> `@darkboxesv1  DarkBoxes Official`\n"
        "> `@darkboxesv1`   _(title auto-set to username)_\n\n"
        "Type and send now:",
        buttons=[[Button.inline("✖ Cancel", "admin_force_join")]],
        parse_mode="md"
    )


@bot_client.on(events.CallbackQuery(pattern=r'^admin_fj_remove$'))
async def admin_fj_remove_callback(event):
    if not admin_panel.is_admin(event.sender_id):
        await event.answer("❌ Admin only", alert=True)
        return
    if not FORCE_JOIN_CHANNELS:
        await event.answer("No channels to remove.", alert=True)
        return
    buttons = []
    for i, ch in enumerate(FORCE_JOIN_CHANNELS):
        label = "🗑 " + str(i + 1) + ". " + (ch.get("title") or ch.get("username", "?"))
        buttons.append([Button.inline(label, "admin_fj_del_" + str(i))])
    buttons.append([Button.inline("✖ Cancel", "admin_force_join")])
    await event.edit(
        "🗑 **Remove Force-Join Channel**\n\nTap a channel to remove it:",
        buttons=buttons, parse_mode="md"
    )


@bot_client.on(events.CallbackQuery(pattern=r'^admin_fj_del_(\d+)$'))
async def admin_fj_del_callback(event):
    if not admin_panel.is_admin(event.sender_id):
        await event.answer("❌ Admin only", alert=True)
        return
    try:
        idx = int(event.data.decode().split("_")[-1])
        if 0 <= idx < len(FORCE_JOIN_CHANNELS):
            removed = FORCE_JOIN_CHANNELS.pop(idx)
            await _save_force_join_channels()
            await event.answer("✅ Removed: " + (removed.get("title") or removed.get("username", "")), alert=False)
        await _show_force_join_panel(event)
    except Exception as e:
        logger.error(f"admin_fj_del error: {e}")
        await event.answer("❌ Error removing channel", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_fj_reload$'))
async def admin_fj_reload_callback(event):
    if not admin_panel.is_admin(event.sender_id):
        await event.answer("❌ Admin only", alert=True)
        return
    _load_force_join_channels()
    await event.answer("✅ Reloaded from DB", alert=False)
    await _show_force_join_panel(event)


@bot_client.on(events.CallbackQuery(pattern=r'^main_menu$'))
async def main_menu_callback(event):
    """Return to main menu — handles ALL « Main Menu button presses"""
    try:
        user_id = event.sender_id
        user_states.pop(user_id, None)

        user_doc = await db_manager.get_user(user_id)
        is_admin = admin_panel.is_admin(user_id) if admin_panel else (user_id == config.ADMIN_USER_ID)

        credits = user_doc.get('searches_remaining', 0) if user_doc else 0
        total   = user_doc.get('total_searches', 0) if user_doc else 0
        sub     = (user_doc.get('subscription') or 'None') if user_doc else 'None'

        message = (
            f"**DarkBoxes Intelligence**"
            f"\n\n"
            f"> Credits: **{credits}**  ·  Searches: {total}"
            f"\n"
            f"> Plan: {sub}"
            f"\n\n"
            f"Select a tool below."
        )

        await event.edit(message, buttons=OneLineKeyboard.main_menu(is_admin), parse_mode="md")

    except Exception as e:
        logger.error(f"❌ Error in main_menu_callback: {e}")
        await event.answer("❌ Error loading menu", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^faq$'))
async def faq_callback(event):
    """FAQ inline button handler"""
    await event.edit(
        "❓ **FREQUENTLY ASKED QUESTIONS**\n\n"
        "**Q: How do I get credits?**\n"
        "Buy via the 💎 Premium Plans button or contact @darkboxesAdmin.\n\n"
        "**Q: I forgot my password for the client script.**\n"
        "Contact @darkboxesAdmin with your Account ID. They can reset it.\n\n"
        "**Q: What data sources do you use?**\n"
        "We aggregate data from multiple verified databases. Results are for lawful OSINT only.\n\n"
        "**Q: Is my search history saved?**\n"
        "Search logs are stored for security and compliance purposes.\n\n"
        "**Q: Can I use the API?**\n"
        "Yes — tap 🔑 API Access from the main menu for API keys and docs.",
        buttons=[[Button.inline("« Main Menu", "main_menu")]],
        parse_mode="md"
    )


@bot_client.on(events.CallbackQuery(pattern=r'^tutorial$'))
async def tutorial_callback(event):
    """Tutorial inline button handler"""
    await event.edit(
        "📖 **HOW TO USE DARKBOXES**\n\n"
        "**1️⃣ Get Credits**\n"
        "Tap 💎 Premium Plans → choose a pack → pay via UPI → submit UTR.\n\n"
        "**2️⃣ Run a Search**\n"
        "Tap any search button (e.g. 📱 Phone Intelligence) → enter your query.\n\n"
        "**3️⃣ Read Results**\n"
        "Results arrive in seconds. Use the copy button to save them.\n\n"
        "**4️⃣ Client Script**\n"
        "Download the terminal client via 💻 Download Client Script.\n"
        "Your Account ID and Password are shown when you first started the bot.\n"
        "Forgot password? → 🗝️ Get My Login Credentials → contact admin.\n\n"
        "**5️⃣ API Access**\n"
        "For developers: tap 🔑 API Access to generate keys and view docs.",
        buttons=[[Button.inline("« Main Menu", "main_menu")]],
        parse_mode="md"
    )


@bot_client.on(events.CallbackQuery(pattern=r'^report_issue$'))
async def report_issue_callback(event):
    """Report issue inline button handler"""
    await event.edit(
        "⚠️ **REPORT AN ISSUE**\n\n"
        "Please describe your issue to our support team:\n\n"
        "📬 **Telegram:** @darkboxesAdmin\n"
        "When reporting, include:\n"
        "• Your Account ID (tap 🗝️ Get My Login Credentials)\n"
        "• What you searched for\n"
        "• What went wrong\n"
        "• Screenshot if possible\n\n"
        "We respond within 24 hours.",
        buttons=[
            [Button.inline("📞 Contact Admin", "contact_admin")],
            [Button.inline("« Main Menu", "main_menu")]
        ],
        parse_mode="md"
    )


@bot_client.on(events.CallbackQuery(pattern=r'^referral_stats$'))
async def referral_stats_callback(event):
    """Referral stats for regular users"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        if not user_doc:
            await event.answer("❌ Account not found", alert=True)
            return
        referrals = user_doc.get('referrals', [])
        earned = user_doc.get('referral_credits_earned', 0)
        ref_link = f"https://t.me/{(await bot_client.get_me()).username}?start={user_id}"
        text = (
            f"📊 **YOUR REFERRAL STATS**\n\n"
            f"👥 Total Referrals: {len(referrals)}\n"
            f"💰 Credits Earned: {earned}\n\n"
            f"🔗 **Your Referral Link:**\n`{ref_link}`\n\n"
            f"Share this link — earn {config.REFERRAL_REWARD} credit per referral!"
        )
        await event.edit(
            text,
            buttons=[
                [Button.inline("📢 Share Referral", "share_referral")],
                [Button.inline("« Main Menu", "main_menu")]
            ],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ referral_stats_callback: {e}")
        await event.answer("❌ Error loading referral stats", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^user_detail_(\d+)$'))
async def user_detail_callback(event):
    """Handle user detail callback"""
    try:
        user_id = int(event.data.decode().split('_')[-1])
        await admin_panel.show_user_detail(event, user_id)
    except Exception as e:
        logger.error(f"❌ Error in user_detail_callback: {e}")
        await event.answer("❌ Error loading user details", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^export_'))
async def export_data_callback(event):
    """Handle export data callbacks"""
    try:
        data_type = event.data.decode().split('_', 1)[1]
        user_id = event.sender_id
        
        if user_id not in export_data_storage:
            await event.answer("❌ No export data available", alert=True)
            return
        
        data = export_data_storage[user_id].get(data_type)
        if not data:
            await event.answer("❌ No data available for export", alert=True)
            return
        
        # Create file
        filename = f"darkboxes_{data_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        # Send file
        await event.delete()
        await bot_client.send_file(
            event.chat_id,
            bytes(data, 'utf-8'),
            filename=filename,
            caption=f"📊 **{data_type.upper()} DATA EXPORT**\n\nExported on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in export_data_callback: {e}")
        await event.answer("❌ Error exporting data", alert=True)

# ================== ADMIN COMMANDS ==================

@bot_client.on(events.NewMessage(pattern=r'/approve_client (.+)'))
async def approve_client_payment(event):
    """Admin approves a client script payment: /approve_client DBXXXX plan_key"""
    if event.sender_id != config.ADMIN_USER_ID and not (admin_panel and admin_panel.is_admin(event.sender_id)):
        return
    try:
        parts = event.pattern_match.group(1).strip().split()
        if len(parts) < 2:
            await event.respond("Usage: `/approve_client DBXXXX plan_key`", parse_mode="md")
            return
        acc_id_a, plan_key_a = parts[0].upper(), parts[1]

        CREDIT_PLANS = {"credits_5": 5}
        SUB_PLANS    = {}
        loop = asyncio.get_running_loop()

        if plan_key_a in CREDIT_PLANS:
            credits_to_add = CREDIT_PLANS[plan_key_a]
            await loop.run_in_executor(
                None, lambda: db_manager.db.accounts.update_one(
                    {"account_id": acc_id_a},
                    {"$inc": {"searches_remaining": credits_to_add}}
                )
            )
            # Also add credits to linked TG users collection
            acc_doc_tmp = await loop.run_in_executor(
                None, lambda: db_manager.db.accounts.find_one({"account_id": acc_id_a})
            )
            for tg_id_sync in (acc_doc_tmp or {}).get("linked_tg_ids", []):
                try:
                    await loop.run_in_executor(
                        None, lambda tid=tg_id_sync: db_manager.db.users.update_one(
                            {"user_id": tid},
                            {"$inc": {"searches_remaining": credits_to_add}}
                        )
                    )
                except Exception as _se:
                    logger.warning(f"Could not sync credits to TG user {tg_id_sync}: {_se}")
            result_msg = f"✅ Added {credits_to_add} credits to `{acc_id_a}`"
        elif plan_key_a in SUB_PLANS:
            sub_name, days = SUB_PLANS[plan_key_a]
            expiry = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            await loop.run_in_executor(
                None, lambda: db_manager.db.accounts.update_one(
                    {"account_id": acc_id_a},
                    {"$set": {
                        "subscription": sub_name,
                        "subscription_expiry": expiry,
                        "subscription_used_today": 0,
                        "subscription_reset_date": today_str
                    }}
                )
            )
            # Sync subscription to linked TG users so both can search with it
            acc_doc_tmp = await loop.run_in_executor(
                None, lambda: db_manager.db.accounts.find_one({"account_id": acc_id_a})
            )
            for tg_id_sync in (acc_doc_tmp or {}).get("linked_tg_ids", []):
                try:
                    await loop.run_in_executor(
                        None, lambda tid=tg_id_sync: db_manager.db.users.update_one(
                            {"user_id": tid},
                            {"$set": {
                                "subscription": sub_name,
                                "subscription_expiry": expiry,
                                "subscription_used_today": 0,
                                "subscription_reset_date": today_str
                            }}
                        )
                    )
                except Exception as _se:
                    logger.warning(f"Could not sync subscription to TG user {tg_id_sync}: {_se}")
            result_msg = f"✅ Activated `{sub_name}` subscription for `{acc_id_a}` ({days} days)"
        else:
            await event.respond(f"❌ Unknown plan: `{plan_key_a}`", parse_mode="md")
            return

        # Update payment record — find latest pending doc first, then update by _id
        # (update_one does NOT support a sort parameter in PyMongo)
        pending_pay = await loop.run_in_executor(
            None, lambda: db_manager.db.client_payments.find_one(
                {"account_id": acc_id_a, "status": "pending"},
                sort=[("submitted_at", -1)]
            )
        )
        if pending_pay:
            pay_oid = pending_pay["_id"]
            await loop.run_in_executor(
                None, lambda: db_manager.db.client_payments.update_one(
                    {"_id": pay_oid},
                    {"$set": {"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat()}}
                )
            )

        # Notify linked TG users
        acc_doc = await loop.run_in_executor(
            None, lambda: db_manager.db.accounts.find_one({"account_id": acc_id_a})
        )
        for tg_id in (acc_doc or {}).get("linked_tg_ids", []):
            try:
                await bot_client.send_message(
                    tg_id,
                    f"✅ **PAYMENT APPROVED**\n\n"
                    f"Your payment for account `{acc_id_a}` has been approved!\n"
                    f"{result_msg.replace('✅ ', '')}\n\n"
                    f"You can now search using the client script and the Telegram bot.",
                    parse_mode="md"
                )
            except Exception:
                pass
        await event.respond(result_msg, parse_mode="md")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")


@bot_client.on(events.NewMessage(pattern=r'/reject_client (.+)'))
async def reject_client_payment(event):
    """Admin rejects a client payment: /reject_client DBXXXX"""
    if event.sender_id != config.ADMIN_USER_ID and not (admin_panel and admin_panel.is_admin(event.sender_id)):
        return
    try:
        acc_id_r = event.pattern_match.group(1).strip().upper()
        loop = asyncio.get_running_loop()
        # find_one with sort first, then update by _id (update_one has no sort param in PyMongo)
        pending_pay_r = await loop.run_in_executor(
            None, lambda: db_manager.db.client_payments.find_one(
                {"account_id": acc_id_r, "status": "pending"},
                sort=[("submitted_at", -1)]
            )
        )
        if pending_pay_r:
            await loop.run_in_executor(
                None, lambda: db_manager.db.client_payments.update_one(
                    {"_id": pending_pay_r["_id"]},
                    {"$set": {"status": "rejected", "rejected_at": datetime.now(timezone.utc).isoformat()}}
                )
            )
        acc_doc = await loop.run_in_executor(
            None, lambda: db_manager.db.accounts.find_one({"account_id": acc_id_r})
        )
        for tg_id in (acc_doc or {}).get("linked_tg_ids", []):
            try:
                await bot_client.send_message(
                    tg_id,
                    f"❌ **PAYMENT REJECTED**\n\n"
                    f"Payment for account `{acc_id_r}` was rejected.\n"
                    f"Contact @darkboxesAdmin for help.",
                    parse_mode="md"
                )
            except Exception:
                pass
        await event.respond(f"✅ Payment for `{acc_id_r}` rejected.", parse_mode="md")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")


@bot_client.on(events.NewMessage(pattern=r'/admin'))
async def admin_command_handler(event):
    """Handle /admin command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        await admin_panel.show_admin_panel(event)
        
    except Exception as e:
        logger.error(f"❌ Error in admin_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/stats'))
async def stats_command_handler(event):
    """Handle /stats command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        await admin_panel.show_today_stats(event)
        
    except Exception as e:
        logger.error(f"❌ Error in stats_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/broadcast (.+)'))
async def broadcast_command_handler(event):
    """Handle /broadcast command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        message = event.pattern_match.group(1)
        user_states[user_id] = {
            "action": "confirm_broadcast",
            "message": message
        }
        
        await admin_panel.ask_for_broadcast(event)
        
    except Exception as e:
        logger.error(f"❌ Error in broadcast_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/ban (\d+)'))
async def ban_command_handler(event):
    """Handle /ban command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        target_id = int(event.pattern_match.group(1))
        user_states[user_id] = {"action": "admin_ban"}
        
        # Simulate message event
        event.text = str(target_id)
        await handle_admin_ban(event)
        
    except Exception as e:
        logger.error(f"❌ Error in ban_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/addcredits (\d+) (\d+)'))
async def add_credits_command_handler(event):
    """Handle /addcredits command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        target_id = int(event.pattern_match.group(1))
        credits = int(event.pattern_match.group(2))
        user_states[user_id] = {"action": "admin_add_credits"}
        
        # Simulate message event
        event.text = f"{target_id} {credits}"
        await handle_admin_add_credits(event)
        
    except Exception as e:
        logger.error(f"❌ Error in add_credits_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/reply (\d+) (.+)'))
async def admin_reply_handler(event):
    """Handle admin reply command"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            return
        
        user_id = int(event.pattern_match.group(1))
        message = event.pattern_match.group(2)
        
        await bot_client.send_message(
            user_id,
            f"👤 **ADMINISTRATOR RESPONSE**\n\n{message}\n\n— DarkBoxes Support Team"
        )
        
        await event.respond(f"✅ Reply sent to user {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_reply_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/leak (.+)'))
async def leak_command_handler(event):
    """Handle /leak command directly"""
    try:
        user_id = event.sender_id
        query = event.pattern_match.group(1).strip()
        
        if not query:
            await event.respond("❌ Please provide a query. Example: `/leak 917204764637`")
            return
        
        # Check if user is banned
        user_doc = await db_manager.get_user(user_id)
        if user_doc and user_doc.get('is_banned'):
            await event.respond("🚫 Your account has been banned. Contact @darkboxesAdmin for assistance.")
            return
        
        if not user_doc:
            await event.respond("❌ User not found. Please use /start first.")
            return
        
        # Check access
        can_search = False
        searches_remaining = user_doc.get('searches_remaining', 0)
        subscription = user_doc.get('subscription')
        subscription_expiry = user_doc.get('subscription_expiry')
        
        if subscription and subscription_expiry:
            expiry_date = datetime.fromisoformat(subscription_expiry)
            if expiry_date > datetime.now(timezone.utc):
                can_search = True
        
        if not can_search and searches_remaining <= 0:
            # Allow but warn it will be masked
            pass  # fall through — handle_search_query will mask the result
        
        # Perform leak search
        leak_warning = (
            "🚀 **ADVANCED OSINT SEARCH INITIATED**\n\n"
            f"🔍 **Query:** `{query}`\n"
            f"⚡ **Processing:** Ultra-fast (5 seconds)\n"
            f"📁 **Output:** JSON + TXT files\n"
            f"💎 **Cost:** 3 credits\n\n"
            f"⚠️ **Note:** For phone numbers, include country code (e.g., 917204764637)\n"
            f"⏳ Processing your advanced search..."
        )
        status = await event.respond(leak_warning, parse_mode="md")
        
        result = await search_engine.perform_search("leak", query, user_id)
        
        try:
            await status.delete()
        except:
            pass
        
        if result["success"]:
            # Handle multiple files for leak search
            if result.get("has_multiple_files"):
                # Send summary first
                await event.respond(result["result"], parse_mode="md")
                
                # Send all files
                for file_data in result.get("files", []):
                    if file_data.get("raw_bytes"):
                        file_type = file_data.get("file_type", "unknown")
                        caption = f"📁 **{file_type.upper()} DATA**\nQuery: `{query}`"
                        
                        # Determine filename
                        filename = file_data.get("filename", "")
                        if not filename:
                            timestamp = int(time.time())
                            filename = f"leak_{query}_{timestamp}.{file_type}"
                        
                        await event.respond(
                            file=file_data["raw_bytes"],
                            caption=caption
                        )
                        
                        logger.info(f"✅ Sent {file_type} file to user")
            else:
                await event.respond(result["result"], parse_mode="md")
            
            await db_manager.update_searches(user_id, "leak", query, True)
        else:
            await event.respond(result["error"], parse_mode="md")
            await db_manager.update_searches(user_id, "leak", query, False)
        
    except Exception as e:
        logger.error(f"❌ Error in leak_command_handler: {e}")
        await event.respond("❌ An error occurred during advanced search.")

@user_client.on(events.NewMessage())
async def handle_all_messages(event):
    """Handle all incoming messages for search responses"""
    try:
        if search_engine:
            await search_engine.handle_incoming_message(event)
    except Exception as e:
        pass

@user_client.on(events.MessageEdited())
async def handle_edited_messages(event):
    """Handle edited messages - important for catching final results after scanning"""
    try:
        if search_engine:
            await search_engine.handle_incoming_message(event)
    except Exception as e:
        pass


@bot_client.on(events.CallbackQuery(pattern=r'^api_menu$'))
async def api_menu_callback(event):
    """Handle API menu callback"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        api_text = (
            "🔑 **API ACCESS MENU**\n"
            "═══════════════════════\n\n"
            "🌐 **Professional API Integration**\n"
            "Integrate DarkBoxes intelligence into your applications!\n\n"
            "📋 **Available Options:**\n"
            "• View your API keys\n"
            "• Monitor API usage\n"
            "• Access documentation\n"
            "• Purchase API plans\n\n"
        )
        
        # Check if user has API access
        has_api = user_doc.get('has_api_access', False)
        if has_api:
            expiry = user_doc.get('api_expiry')
            if expiry:
                expiry_date = datetime.fromisoformat(expiry)
                days_left = (expiry_date - datetime.now(timezone.utc)).days
                api_text += f"✅ **API Status:** Active ({days_left} days remaining)\n"
            else:
                api_text += "✅ **API Status:** Active (Lifetime)\n"
        else:
            api_text += "⚠️ **API Status:** Not activated\n"
            api_text += "\n💡 Purchase an API plan to get started!"
        
        await event.edit(api_text, buttons=OneLineKeyboard.api_menu(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in api_menu_callback: {e}")
        await event.answer("❌ Error loading API menu", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^my_api_keys$'))
async def my_api_keys_callback(event):
    """Handle my API keys callback"""
    try:
        user_id = event.sender_id
        
        # Get user's API keys
        api_keys = await db_manager.api_db.get_user_api_keys(user_id)
        
        keys_text = "🔑 **MY API KEYS**\n═══════════════════════\n\n"
        
        if not api_keys:
            keys_text += "⚠️ You don't have any API keys yet.\n\n"
            keys_text += "💡 Purchase an API plan to create your first key!"
        else:
            for i, key_info in enumerate(api_keys, 1):
                api_key = key_info['api_key']
                created = key_info.get('created_at', '')[:10]
                expires = key_info.get('expires_at', '')[:10]
                is_active = key_info.get('is_active', True)
                requests_used = key_info.get('total_requests', 0)
                
                status = "✅ Active" if is_active else "❌ Inactive"
                
                keys_text += f"**Key #{i}**\n"
                keys_text += f"├─ Key: `{api_key[:16]}...{api_key[-8:]}`\n"
                keys_text += f"├─ Status: {status}\n"
                keys_text += f"├─ Created: {created}\n"
                keys_text += f"├─ Expires: {expires}\n"
                keys_text += f"└─ Requests: {requests_used}\n\n"
        
        await event.edit(keys_text, buttons=OneLineKeyboard.api_menu(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in my_api_keys_callback: {e}")
        await event.answer("❌ Error loading API keys", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^api_usage$'))
async def api_usage_callback(event):
    """Handle API usage callback"""
    try:
        user_id = event.sender_id
        
        # Get API stats
        stats = await db_manager.api_db.get_api_stats(user_id)
        
        usage_text = "📊 **API USAGE STATISTICS**\n═══════════════════════\n\n"
        
        if stats.get('total_requests', 0) == 0:
            usage_text += "⚠️ No API usage recorded yet.\n\n"
            usage_text += "💡 Start using your API key to see statistics here!"
        else:
            usage_text += f"📈 **Overall Statistics**\n"
            usage_text += f"├─ Total Requests: {stats['total_requests']}\n"
            usage_text += f"├─ Successful: {stats['successful_requests']}\n"
            usage_text += f"├─ Failed: {stats['failed_requests']}\n"
            usage_text += f"└─ Success Rate: {stats['success_rate']:.1f}%\n\n"
            
            if stats.get('recent_requests'):
                usage_text += "🕐 **Recent Activity**\n"
                for req in stats['recent_requests'][:5]:
                    endpoint = req.get('endpoint', 'Unknown')
                    timestamp = req.get('timestamp', '')[:16]
                    success = "✅" if req.get('success') else "❌"
                    usage_text += f"{success} {endpoint} - {timestamp}\n"
        
        await event.edit(usage_text, buttons=OneLineKeyboard.api_menu(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in api_usage_callback: {e}")
        await event.answer("❌ Error loading API usage", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^api_docs$'))
async def api_docs_callback(event):
    """Handle API documentation callback"""
    try:
        docs_text = (
            "📖 **API DOCUMENTATION**\n"
            "═══════════════════════\n\n"
            "🌐 **Base URL:**\n"
            f"`{config.API_BASE_URL}`\n\n"
            "🔑 **Authentication:**\n"
            "Include your API key in the request header:\n"
            "`X-API-Key: your_api_key_here`\n\n"
            "📡 **Available Endpoints:**\n\n"
            "**Search Endpoints:**\n"
            "• `POST /api/v1/search/phone` - Phone search\n"
            "• `POST /api/v1/search/email` - Email search\n"
            "• `POST /api/v1/search/aadhar` - ID search\n"
            "• `POST /api/v1/search/vehicle` - Vehicle search\n"
            "• `POST /api/v1/search/leak` - Advanced OSINT\n"
            "• And more...\n\n"
            "**Utility Endpoints:**\n"
            "• `GET /api/v1/status` - API status\n"
            "• `GET /api/v1/balance` - Check credits\n"
            "• `GET /api/v1/usage` - Usage stats\n\n"
            f"📚 **Full Docs:** {config.API_BASE_URL}/api/v1/docs\n"
            "💬 **Support:** @darkboxesAdmin"
        )
        
        await event.edit(docs_text, buttons=OneLineKeyboard.api_menu(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in api_docs_callback: {e}")
        await event.answer("❌ Error loading documentation", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^api_plans$'))
async def api_plans_callback(event):
    """Handle API plans callback"""
    try:
        plans_text = (
            "💎 **API SUBSCRIPTION PLANS**\n"
            "═══════════════════════\n\n"
            "Choose the perfect plan for your needs:\n\n"
            "💰 **BASIC API** - ₹499/month\n"
            "├─ 1,000 API calls/month\n"
            "├─ All search endpoints\n"
            "├─ Email support\n"
            "└─ 99.9% uptime SLA\n\n"
            "🚀 **PRO API** - ₹999/month\n"
            "├─ 5,000 API calls/month\n"
            "├─ All search endpoints\n"
            "├─ Priority support\n"
            "├─ 99.9% uptime SLA\n"
            "└─ Webhook support\n\n"
            "👑 **ENTERPRISE API** - ₹2,999/month\n"
            "├─ 20,000 API calls/month\n"
            "├─ All search endpoints\n"
            "├─ 24/7 priority support\n"
            "├─ 99.9% uptime SLA\n"
            "├─ Webhook support\n"
            "├─ Dedicated account manager\n"
            "└─ Custom integrations\n\n"
            "📞 **Contact @darkboxesAdmin to activate!**"
        )
        
        await event.edit(plans_text, buttons=OneLineKeyboard.api_plans_menu(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in api_plans_callback: {e}")
        await event.answer("❌ Error loading API plans", alert=True)


# ================== ADMIN API COMMANDS ==================

@bot_client.on(events.NewMessage(pattern=r'/create_api (\d+) (\w+) (\d+)'))
async def create_api_command(event):
    """Create API key - Admin only"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.respond("❌ Admin only")
            return
        
        target_user = int(event.pattern_match.group(1))
        plan = event.pattern_match.group(2).lower()
        days = int(event.pattern_match.group(3))
        
        result = await db_manager.api_db.create_api_key(target_user, plan, days, f"Admin created")

        if result and result.get('api_key'):
            key = result['api_key']
            await event.respond(
                f"✅ **API KEY CREATED**\n\n"
                f"👤 User: `{target_user}`\n"
                f"🔑 Key: `{key}`\n"
                f"📦 Plan: {plan}\n"
                f"⏰ Days: {days}\n\n"
                f"Test: {config.API_BASE_URL}/api/v1/docs",
                parse_mode="md"
            )
            # Notify user
            try:
                await bot_client.send_message(target_user, f"🎉 API key created!\n`{key}`", parse_mode="md")
            except:
                pass
        else:
            await event.respond(f"❌ Failed: {result.get('error')}")
    except Exception as e:
        logger.error(f"create_api error: {e}")
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/list_api'))
async def list_api_command(event):
    """List API keys - Admin only"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            return
        
        keys = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(db_manager.db.api_keys.find({}).limit(10))
        )
        
        if not keys:
            await event.respond("No API keys")
            return
        
        msg = "🔑 **API KEYS**\n\n"
        for k in keys:
            msg += f"User {k['user_id']}: `{k['api_key'][:16]}...`\n"
        
        await event.respond(msg, parse_mode="md")
    except Exception as e:
        logger.error(f"list_api error: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^api_plan_(basic|pro|enterprise)$'))
async def api_plan_callback(event):
    """Handle plan selection with screenshot payment flow"""
    try:
        plan = event.data.decode().split('_')[-1]
        prices = {'basic': 499, 'pro': 999, 'enterprise': 2999}
        calls = {'basic': 1000, 'pro': 5000, 'enterprise': 20000}
        user_id = event.sender_id
        
        plan_text = (
            f"🔑 **API {plan.upper()} PLAN**\n\n"
            f"💰 Price: ₹{prices[plan]}/month\n"
            f"📊 API Calls: {calls[plan]:,}/month\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**How to purchase:**\n\n"
            f"1️⃣ Pay ₹{prices[plan]} to UPI:\n"
            f"   `{config.UPI_ID}`\n\n"
            f"2️⃣ Note your **UTR / Transaction Reference Number**\n\n"
            f"3️⃣ Tap button below to submit UTR\n"
            f"   Your ID: `{user_id}`\n\n"
            f"⏱️ Activation within 5-15 minutes after manual verification\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        buttons = [
            [Button.inline(f"📤 Submit UTR Number", f"submit_api_payment_{plan}")],
            [Button.inline("« Back", "api_plans")]
        ]
        
        await event.edit(plan_text, buttons=buttons, parse_mode="md")
    except Exception as e:
        logger.error(f"plan callback error: {e}")
        await event.answer("❌ Error", alert=True)


# ================== QUERY PROTECTION COMMANDS ==================

@bot_client.on(events.NewMessage(pattern=r'/protect_query (.+)'))
async def protect_query_admin_command(event):
    """Admin command to protect a query"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.respond("❌ Admin only")
            return
        
        query = event.pattern_match.group(1).strip()
        
        # Add query to protected list
        await db_manager.protected_manager.add_protected_query(
            query, 
            event.sender_id,
            reason="admin"
        )
        
        await event.respond(
            f"✅ **QUERY PROTECTED**\n\n"
            f"Query: `{query}`\n"
            f"Status: Protected by admin\n\n"
            f"This query is now restricted and cannot be searched by users.",
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ protect_query error: {e}")
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/unprotect_query (.+)'))
async def unprotect_query_command(event):
    """Admin command to unprotect a query"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.respond("❌ Admin only")
            return
        
        query = event.pattern_match.group(1).strip()
        
        # Remove query from protected list
        await db_manager.protected_manager.remove_protected_query(query)
        
        await event.respond(
            f"✅ **QUERY UNPROTECTED**\n\n"
            f"Query: `{query}`\n"
            f"Status: Removed from protected list\n\n"
            f"This query can now be searched by users.",
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ unprotect_query error: {e}")
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/list_protected'))
async def list_protected_queries_command(event):
    """Admin command to list all protected queries"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.respond("❌ Admin only")
            return
        
        loop = asyncio.get_running_loop()
        protected = await loop.run_in_executor(
            None,
            lambda: list(db_manager.db.protected_queries.find(
                {"status": "active"}
            ).sort("timestamp", -1).limit(50))
        )
        
        if not protected:
            await event.respond("✅ No protected queries found.")
            return
        
        msg = f"🔒 **PROTECTED QUERIES** ({len(protected)} total)\n\n"
        
        for i, pq in enumerate(protected[:20], 1):
            query = pq.get('query', 'N/A')
            reason = pq.get('reason', 'N/A')
            ts = pq.get('timestamp', '')[:10]
            
            msg += f"{i}. `{query}`\n   Reason: {reason} | {ts}\n\n"
        
        if len(protected) > 20:
            msg += f"\n... and {len(protected) - 20} more\n"
        
        await event.respond(msg, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ list_protected error: {e}")
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/request_protection'))
async def request_protection_command(event):
    """User command to request query protection"""
    try:
        user_id = event.sender_id
        
        user_states[user_id] = {
            "state": "request_protection_query",
            "timestamp": time.time()
        }
        
        await event.respond(
            "🔒 **REQUEST QUERY PROTECTION**\n\n"
            "💰 **Cost:** ₹50 per query\n\n"
            "📝 **How it works:**\n"
            "1. You provide the query to protect\n"
            "2. You pay ₹50 via UPI\n"
            "3. Admin verifies payment\n"
            "4. Your query gets protected\n\n"
            "🔐 **Protected queries cannot be searched by anyone.**\n\n"
            "Please send the query you want to protect:",
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ request_protection error: {e}")
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage())
async def handle_protection_request_flow(event):
    """Handle query protection request flow"""
    try:
        user_id = event.sender_id
        
        if user_id not in user_states:
            return
        
        state = user_states[user_id]
        
        if state.get("state") == "request_protection_query":
            query = event.text.strip()
            
            if not query or len(query) < 3:
                await event.respond("❌ Please enter a valid query (min 3 characters)")
                return
            
            # Store query and move to UTR step
            user_states[user_id] = {
                "state": "request_protection_utr",
                "query": query,
                "timestamp": time.time()
            }
            
            await event.respond(
                f"📝 **QUERY TO PROTECT:**\n`{query}`\n\n"
                f"💰 **Amount:** ₹50\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Payment Instructions:**\n\n"
                f"1️⃣ Pay ₹50 to UPI:\n"
                f"`{config.UPI_ID}`\n\n"
                f"2️⃣ Send your 12-digit UTR number here\n\n"
                f"⚠️ **Important:**\n"
                f"• Use the exact amount: ₹50\n"
                f"• Save your UTR number\n"
                f"• Admin will verify within 24 hours\n\n"
                f"💡 Send /cancel to cancel this request",
                parse_mode="md"
            )
            
        elif state.get("state") == "request_protection_utr":
            utr = event.text.strip()
            
            # UTRs can be 6-30 chars, alphanumeric (UPI reference numbers vary by bank)
            if len(utr) < 6 or len(utr) > 35 or not all(c.isalnum() or c in '-_' for c in utr):
                await event.respond("❌ Invalid UTR. Please enter your UTR/Transaction Reference Number (6-35 alphanumeric characters).")
                return
            
            query = state.get("query")
            
            # Create protection request
            request_id = await db_manager.protected_manager.create_protection_request(
                user_id, query, utr
            )
            
            # Clear state
            user_states.pop(user_id, None)
            
            # Notify user
            await event.respond(
                f"✅ **PROTECTION REQUEST SUBMITTED**\n\n"
                f"📝 Request ID: `{request_id}`\n"
                f"🔍 Query: `{query}`\n"
                f"💳 UTR: `{utr}`\n"
                f"💰 Amount: ₹50\n\n"
                f"⏳ **Status:** Pending verification\n\n"
                f"Admin will verify your payment within 24 hours.\n"
                f"You'll be notified once approved!",
                parse_mode="md"
            )
            
            # Notify admin
            try:
                await bot_client.send_message(
                    config.ADMIN_USER_ID,
                    f"🔒 **NEW PROTECTION REQUEST**\n\n"
                    f"Request ID: `{request_id}`\n"
                    f"User ID: `{user_id}`\n"
                    f"Query: `{query}`\n"
                    f"UTR: `{utr}`\n"
                    f"Amount: ₹50\n\n"
                    f"Use /approve_protection {request_id} to approve",
                    parse_mode="md"
                )
            except Exception as e:
                logger.error(f"Error notifying admin: {e}")
            
    except Exception as e:
        logger.error(f"❌ handle_protection_request_flow error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/approve_protection (.+)'))
async def approve_protection_command(event):
    """Admin command to approve protection request"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.respond("❌ Admin only")
            return
        
        request_id = event.pattern_match.group(1).strip()
        
        # Approve the request
        success = await db_manager.protected_manager.approve_protection_request(request_id)
        
        if success:
            # Get request details to notify user
            loop = asyncio.get_running_loop()
            request = await loop.run_in_executor(
                None,
                lambda: db_manager.db.protection_payments.find_one({"request_id": request_id})
            )
            
            if request:
                user_id = request['user_id']
                query = request['query']
                
                await event.respond(
                    f"✅ **PROTECTION REQUEST APPROVED**\n\n"
                    f"Request ID: `{request_id}`\n"
                    f"Query: `{query}`\n"
                    f"User: `{user_id}`\n\n"
                    f"Query is now protected!",
                    parse_mode="md"
                )
                
                # Notify user
                try:
                    await bot_client.send_message(
                        user_id,
                        f"✅ **PROTECTION APPROVED**\n\n"
                        f"Your query has been protected!\n\n"
                        f"🔍 Query: `{query}`\n"
                        f"🔒 Status: Protected\n\n"
                        f"This query can no longer be searched by anyone.",
                        parse_mode="md"
                    )
                except Exception as e:
                    logger.error(f"Error notifying user: {e}")
        else:
            await event.respond(f"❌ Request ID not found: {request_id}")
        
    except Exception as e:
        logger.error(f"❌ approve_protection error: {e}")
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/pending_protections'))
async def list_pending_protections_command(event):
    """Admin command to list pending protection requests"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.respond("❌ Admin only")
            return
        
        pending = await db_manager.protected_manager.get_pending_protection_requests()
        
        if not pending:
            await event.respond("✅ No pending protection requests.")
            return
        
        msg = f"⏳ **PENDING PROTECTION REQUESTS** ({len(pending)} pending)\n\n"
        
        for i, req in enumerate(pending[:10], 1):
            request_id = req.get('request_id', 'N/A')
            user_id = req.get('user_id', 'N/A')
            query = req.get('query', 'N/A')
            utr = req.get('utr', 'N/A')
            ts = req.get('timestamp', '')[:16].replace('T', ' ')
            
            msg += (
                f"{i}. **Request {request_id}**\n"
                f"   User: `{user_id}`\n"
                f"   Query: `{query}`\n"
                f"   UTR: `{utr}`\n"
                f"   Time: {ts}\n"
                f"   `/approve_protection {request_id}`\n\n"
            )
        
        if len(pending) > 10:
            msg += f"\n... and {len(pending) - 10} more\n"
        
        await event.respond(msg, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ pending_protections error: {e}")
        await event.respond(f"❌ Error: {e}")


@bot_client.on(events.CallbackQuery(pattern=r'^protect_query_menu$'))
async def protect_query_menu_callback(event):
    """Show protect query menu for users"""
    try:
        user_id = event.sender_id
        text = (
            "🔐 **PROTECT MY QUERY**\n"
            "═══════════════════════\n\n"
            "🛡️ **What is Query Protection?**\n"
            "When your query (phone number, ID, etc.) is protected, "
            "no one else can search it through this bot.\n\n"
            "💰 **Cost:** ₹50 per query (one-time)\n\n"
            "📋 **How it works:**\n"
            "1️⃣ Tap 'Protect a Query' below\n"
            "2️⃣ Enter the query you want to protect\n"
            "3️⃣ Pay ₹50 via UPI and enter UTR\n"
            "4️⃣ Admin verifies and activates within 24h\n\n"
            f"💳 **UPI ID:** `{config.UPI_ID}`\n\n"
            "⚠️ **Note:** Protection is permanent once approved.\n"
            "Admin can also manually restrict any query."
        )
        buttons = [
            [Button.inline("🔒 Protect a Query (₹50)", "protect_query_start")],
            [Button.inline("📋 My Protection Requests", "my_protection_requests")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        await event.edit(text, buttons=buttons, parse_mode="md")
    except Exception as e:
        logger.error(f"❌ protect_query_menu_callback: {e}")
        await event.answer("❌ Error", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^protect_query_start$'))
async def protect_query_start_callback(event):
    """Start the protect query flow via inline button"""
    try:
        user_id = event.sender_id
        user_states[user_id] = {
            "state": "request_protection_query",
            "timestamp": time.time()
        }
        await event.edit(
            "🔒 **PROTECT YOUR QUERY**\n\n"
            "Please type the query you want to protect.\n"
            "This can be a phone number, ID, email, vehicle number, etc.\n\n"
            "📝 **Enter your query:**",
            buttons=[[Button.inline("❌ Cancel", "protect_query_menu")]],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ protect_query_start_callback: {e}")
        await event.answer("❌ Error", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^my_protection_requests$'))
async def my_protection_requests_callback(event):
    """Show user's protection requests"""
    try:
        user_id = event.sender_id
        loop = asyncio.get_running_loop()
        reqs = await loop.run_in_executor(
            None,
            lambda: list(db_manager.db.protection_payments.find(
                {"user_id": user_id}
            ).sort("timestamp", -1).limit(10))
        )
        if not reqs:
            text = "📋 **MY PROTECTION REQUESTS**\n\nYou have no protection requests yet."
        else:
            text = f"📋 **MY PROTECTION REQUESTS** ({len(reqs)} found)\n\n"
            for i, req in enumerate(reqs, 1):
                status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(req.get("status", ""), "❓")
                text += (
                    f"{i}. `{req.get('query', 'N/A')}`\n"
                    f"   {status_icon} {req.get('status', 'N/A').title()} | "
                    f"ID: `{req.get('request_id', 'N/A')}`\n"
                    f"   UTR: `{req.get('utr', 'N/A')}` | {req.get('timestamp', '')[:10]}\n\n"
                )
        await event.edit(
            text,
            buttons=[[Button.inline("« Back", "protect_query_menu")]],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ my_protection_requests_callback: {e}")
        await event.answer("❌ Error", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_restricted_queries$'))
async def admin_restricted_queries_callback(event):
    """Admin: view and manage restricted/protected queries"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        loop = asyncio.get_running_loop()
        protected = await loop.run_in_executor(
            None,
            lambda: list(db_manager.db.protected_queries.find(
                {"status": "active"}
            ).sort("timestamp", -1).limit(30))
        )
        if not protected:
            text = "🔒 **RESTRICTED QUERIES**\n\nNo queries are currently restricted."
        else:
            text = f"🔒 **RESTRICTED QUERIES** ({len(protected)} active)\n\n"
            for i, pq in enumerate(protected[:20], 1):
                reason = pq.get('reason', 'admin')
                ts = pq.get('timestamp', '')[:10]
                text += f"{i}. `{pq.get('query', 'N/A')}`\n   Reason: {reason} | {ts}\n\n"
            if len(protected) > 20:
                text += f"... and {len(protected) - 20} more\n"
        buttons = [
            [Button.inline("🚫 Restrict a Query", "admin_restrict_query_prompt")],
            [Button.inline("🔓 Remove Restriction", "admin_unrestrict_query_prompt")],
            [Button.inline("⏳ Pending Requests", "admin_pending_protections")],
            [Button.inline("« Admin Panel", "admin_panel")]
        ]
        await event.edit(text, buttons=buttons, parse_mode="md")
    except Exception as e:
        logger.error(f"❌ admin_restricted_queries_callback: {e}")
        await event.answer("❌ Error loading restricted queries", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_restrict_query_prompt$'))
async def admin_restrict_query_prompt_callback(event):
    """Prompt admin to enter query to restrict"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        user_states[event.sender_id] = {"action": "admin_restrict_query"}
        await event.edit(
            "🚫 **RESTRICT QUERY**\n\n"
            "Enter the query you want to block/restrict.\n"
            "Users who search this query will see a 'Protected/Blocked' message.\n\n"
            "📝 Type the query:",
            buttons=[[Button.inline("❌ Cancel", "admin_restricted_queries")]],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ admin_restrict_query_prompt_callback: {e}")
        await event.answer("❌ Error", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_unrestrict_query_prompt$'))
async def admin_unrestrict_query_prompt_callback(event):
    """Prompt admin to enter query to unrestrict"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        user_states[event.sender_id] = {"action": "admin_unrestrict_query"}
        await event.edit(
            "🔓 **REMOVE RESTRICTION**\n\n"
            "Enter the query you want to unrestrict.\n\n"
            "📝 Type the query:",
            buttons=[[Button.inline("❌ Cancel", "admin_restricted_queries")]],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ admin_unrestrict_query_prompt_callback: {e}")
        await event.answer("❌ Error", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_pending_protections$'))
async def admin_pending_protections_callback(event):
    """Admin: view pending query protection requests with approve/reject buttons"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        pending = await db_manager.protected_manager.get_pending_protection_requests()
        if not pending:
            await event.edit(
                "✅ **NO PENDING PROTECTION REQUESTS**\n\nAll requests processed.",
                buttons=[[Button.inline("« Admin Panel", "admin_panel")]],
                parse_mode="md"
            )
            return
        text = f"⏳ **PENDING PROTECTION REQUESTS** ({len(pending)})\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        buttons = []
        for i, req in enumerate(pending[:10], 1):
            rid = req.get('request_id', 'N/A')
            uid = req.get('user_id', 'N/A')
            query = req.get('query', 'N/A')
            utr = req.get('utr', 'N/A')
            ts = req.get('timestamp', '')[:16].replace('T', ' ')
            text += (
                f"{i}. **Request `{rid}`**\n"
                f"   👤 User: `{uid}`\n"
                f"   🔍 Query: `{query}`\n"
                f"   🏦 UTR: `{utr}`\n"
                f"   💰 Amount: ₹50\n"
                f"   🕐 {ts}\n\n"
            )
            buttons.append([
                Button.inline(f"✅ Approve {rid}", f"approve_prot_{rid}_{uid}"),
                Button.inline(f"❌ Reject {rid}", f"reject_prot_{rid}_{uid}")
            ])
        buttons.append([Button.inline("🔄 Refresh", "admin_pending_protections")])
        buttons.append([Button.inline("« Admin Panel", "admin_panel")])
        await event.edit(text, buttons=buttons, parse_mode="md")
    except Exception as e:
        logger.error(f"❌ admin_pending_protections_callback: {e}")
        await event.answer("❌ Error loading pending protections", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^approve_prot_(.+)_(\d+)$'))
async def approve_prot_callback(event):
    """Admin: approve protection request via inline button"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        data = event.data.decode()
        # format: approve_prot_REQID_USERID
        parts = data.split('_', 3)
        # parts[0]=approve, parts[1]=prot, parts[2]=REQID, parts[3]=USERID
        request_id = parts[2]
        user_id = int(parts[3])
        success = await db_manager.protected_manager.approve_protection_request(request_id)
        if success:
            loop = asyncio.get_running_loop()
            request = await loop.run_in_executor(
                None, lambda: db_manager.db.protection_payments.find_one({"request_id": request_id})
            )
            query = request['query'] if request else 'N/A'
            await event.answer(f"✅ Approved!", alert=False)
            try:
                await bot_client.send_message(
                    user_id,
                    f"✅ **QUERY PROTECTION APPROVED!**\n\n"
                    f"🔍 Query: `{query}`\n"
                    f"🔒 Status: **Protected**\n\n"
                    f"This query can no longer be searched by anyone in the bot.\n"
                    f"Request ID: `{request_id}`",
                    parse_mode="md"
                )
            except Exception:
                pass
            await admin_pending_protections_callback(event)
        else:
            await event.answer("❌ Request not found or already processed", alert=True)
    except Exception as e:
        logger.error(f"❌ approve_prot_callback: {e}")
        await event.answer("❌ Error approving request", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^reject_prot_(.+)_(\d+)$'))
async def reject_prot_callback(event):
    """Admin: reject protection request via inline button"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return
        data = event.data.decode()
        parts = data.split('_', 3)
        request_id = parts[2]
        user_id = int(parts[3])
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: db_manager.db.protection_payments.update_one(
                {"request_id": request_id},
                {"$set": {"status": "rejected", "rejected_at": datetime.now(timezone.utc).isoformat()}}
            )
        )
        await event.answer(f"❌ Rejected", alert=False)
        try:
            req = await loop.run_in_executor(
                None, lambda: db_manager.db.protection_payments.find_one({"request_id": request_id})
            )
            query = req['query'] if req else 'N/A'
            await bot_client.send_message(
                user_id,
                f"❌ **PROTECTION REQUEST REJECTED**\n\n"
                f"Request ID: `{request_id}`\n"
                f"Query: `{query}`\n\n"
                f"Your payment could not be verified.\n"
                f"Please contact @darkboxesAdmin for assistance.",
                parse_mode="md"
            )
        except Exception:
            pass
        await admin_pending_protections_callback(event)
    except Exception as e:
        logger.error(f"❌ reject_prot_callback: {e}")
        await event.answer("❌ Error rejecting request", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^submit_api_payment_(basic|pro|enterprise)$'))
async def submit_api_payment_callback(event):
    """Handle API plan UTR submission"""
    try:
        plan = event.data.decode().split('_')[-1]
        prices = {'basic': 499, 'pro': 999, 'enterprise': 2999}
        user_id = event.sender_id
        
        user_states[user_id] = {
            "action": "awaiting_payment_utr",
            "plan_id": f"api_{plan}",
            "plan_name": f"API {plan.title()} Plan",
            "plan_price": prices[plan]
        }
        
        await event.edit(
            f"🏦 **ENTER UTR / TRANSACTION NUMBER**\n\n"
            f"Plan: **API {plan.title()}** — ₹{prices[plan]}/month\n\n"
            f"After completing your UPI payment, type the UTR number\n"
            f"or Transaction Reference Number from your payment app.\n\n"
            f"Admin will verify manually and activate your API key.\n\n"
            f"Your ID: `{user_id}`",
            buttons=[[Button.inline("❌ Cancel", "api_menu")]],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"submit_api_payment error: {e}")
        await event.answer("❌ Error", alert=True)


# ================== CLEANUP TASK ==================
# ================== ACCOUNT SYSTEM — LOGIN & LINKING ==================

def generate_password(length: int = 10) -> str:
    """Generate a random alphanumeric password"""
    import string
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


async def get_or_create_db_account(user_id: int, username: str, first_name: str) -> dict:
    """Return existing DB account or create a fresh one with credentials"""
    account = await asyncio.get_running_loop().run_in_executor(
        None, lambda: db_manager.db.accounts.find_one({"linked_tg_ids": user_id})
    )
    if account:
        return account

    # Create new account
    account_id = f"DB{secrets.token_hex(4).upper()}"
    password = generate_password(10)
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()

    new_account = {
        "account_id": account_id,
        "password_hash": pwd_hash,
        "plain_password_shown_once": password,   # cleared after first show
        "linked_tg_ids": [user_id],
        "linked_usernames": [username or ""],
        "first_name": first_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "searches_remaining": 0,
        "subscription": None,
        "subscription_expiry": None,
        "subscription_daily_limit": 0,
        "subscription_used_today": 0,
        "subscription_reset_date": "",
        "is_banned": False,
        "total_searches": 0
    }

    await asyncio.get_running_loop().run_in_executor(
        None, lambda: db_manager.db.accounts.insert_one(new_account)
    )

    # Also link user doc
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: db_manager.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"account_id": account_id}},
            upsert=False
        )
    )
    return new_account


@bot_client.on(events.CallbackQuery(pattern=r'^login_account$'))
async def login_account_callback(event):
    """Show login options"""
    try:
        user_id = event.sender_id
        # Check if already linked
        account = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.accounts.find_one({"linked_tg_ids": user_id})
        )

        if account:
            acc_id = account.get("account_id", "N/A")
            sub = account.get("subscription") or "None"
            credits = account.get("searches_remaining", 0)
            await event.edit(
                f"🔐 **ACCOUNT LINKED**\n\n"
                f"Your Telegram account is already connected to:\n"
                f"🆔 Account ID: `{acc_id}`\n"
                f"💰 Credits: {credits}\n"
                f"📦 Plan: {sub}\n\n"
                f"Use this **Account ID** and your **password** in the terminal client.\n"
                f"If you forgot your password, contact @darkboxesAdmin.",
                buttons=[
                    [Button.inline("🔑 Show My Account ID", "show_account_id")],
                    [Button.inline("« Main Menu", "main_menu")]
                ],
                parse_mode="md"
            )
        else:
            await event.edit(
                "🔐 **ACCOUNT SYSTEM**\n\n"
                "Link your Telegram account with a DarkBoxes account to:\n"
                "• Use the terminal client with the same credits\n"
                "• Access the API with shared balance\n"
                "• Log in from multiple devices\n\n"
                "Choose an option:",
                buttons=[
                    [Button.inline("🆕 Create New Account", "create_account")],
                    [Button.inline("🔑 Login with Existing Account", "login_existing")],
                    [Button.inline("« Main Menu", "main_menu")]
                ],
                parse_mode="md"
            )
    except Exception as e:
        logger.error(f"❌ login_account_callback: {e}")
        await event.answer("❌ Error", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^show_account_id$'))
async def show_account_id_callback(event):
    """Show user's account ID"""
    try:
        user_id = event.sender_id
        account = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.accounts.find_one({"linked_tg_ids": user_id})
        )
        if account:
            acc_id = account.get("account_id", "N/A")
            await event.answer(f"Your Account ID: {acc_id}", alert=True)
        else:
            await event.answer("No account linked yet.", alert=True)
    except Exception as e:
        logger.error(f"❌ show_account_id: {e}")


@bot_client.on(events.CallbackQuery(pattern=r'^create_account$'))
async def create_account_callback(event):
    """Create a new DarkBoxes account and link Telegram"""
    try:
        user_id = event.sender_id
        user = await event.get_sender()

        # Check if already exists
        existing = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.accounts.find_one({"linked_tg_ids": user_id})
        )
        if existing:
            await event.answer("✅ Account already exists!", alert=True)
            await login_account_callback(event)
            return

        account = await get_or_create_db_account(user_id, user.username or "", user.first_name or "User")
        acc_id = account.get("account_id")
        raw_pw = account.get("plain_password_shown_once", "")

        # Clear the plain password from DB now that we're showing it
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.accounts.update_one(
                {"account_id": acc_id},
                {"$unset": {"plain_password_shown_once": ""}}
            )
        )

        await event.edit(
            f"✅ **ACCOUNT CREATED!**\n\n"
            f"Save these credentials — they will **not** be shown again:\n\n"
            f"🆔 **Account ID:** `{acc_id}`\n"
            f"🔑 **Password:** `{raw_pw}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 **Use in Bot:** Tap Login → Login with Existing Account\n"
            f"💻 **Use in Client:** Enter Account ID + Password at login\n"
            f"🔗 Your Telegram is already linked to this account.\n\n"
            f"Credits & subscriptions are shared across all linked accounts.\n"
            f"❓ Help: @darkboxesAdmin",
            buttons=[[Button.inline("« Main Menu", "main_menu")]],
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ create_account_callback: {e}")
        await event.answer("❌ Error creating account", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^login_existing$'))
async def login_existing_callback(event):
    """Ask user to enter account credentials to link"""
    try:
        user_id = event.sender_id
        user_states[user_id] = {"action": "enter_account_credentials"}
        await event.edit(
            "🔑 **LOGIN TO EXISTING ACCOUNT**\n\n"
            "Enter your Account ID and password:\n"
            "Format: `ACCOUNT_ID PASSWORD`\n\n"
            "Example: `DB1A2B3C4D myPassword123`\n\n"
            "Don't have an account yet? Go back and create one.\n"
            "Forgot credentials? Contact @darkboxesAdmin",
            buttons=[[Button.inline("❌ Cancel", "main_menu")]],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ login_existing_callback: {e}")
        await event.answer("❌ Error", alert=True)


async def handle_account_login(event):
    """Handle account ID + password login from user text"""
    try:
        user_id = event.sender_id
        text = (event.text or "").strip()
        parts = text.split(maxsplit=1)

        if len(parts) != 2:
            await event.respond(
                "❌ Invalid format. Use: `ACCOUNT_ID PASSWORD`\n"
                "Example: `DB1A2B3C4D myPassword123`",
                parse_mode="md"
            )
            return

        acc_id, password = parts[0].strip(), parts[1].strip()
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()

        account = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.accounts.find_one({"account_id": acc_id})
        )

        if not account:
            await event.respond("❌ Account ID not found. Check and try again.")
            return

        if account.get("password_hash") != pwd_hash:
            await event.respond("❌ Incorrect password. Contact @darkboxesAdmin if you forgot it.")
            return

        # Link this Telegram ID to the account
        linked_ids = account.get("linked_tg_ids", [])
        if user_id not in linked_ids:
            linked_ids.append(user_id)
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.accounts.update_one(
                    {"account_id": acc_id},
                    {"$addToSet": {"linked_tg_ids": user_id}}
                )
            )
            # Also link account_id on user doc
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"account_id": acc_id}}
                )
            )

        user_states.pop(user_id, None)

        sub = account.get("subscription") or "None"
        credits = account.get("searches_remaining", 0)

        await event.respond(
            f"✅ **LOGGED IN SUCCESSFULLY!**\n\n"
            f"🔗 Your Telegram is now linked to account `{acc_id}`\n"
            f"💰 Credits: {credits}\n"
            f"📦 Plan: {sub}\n\n"
            f"Credits and subscriptions are now shared with this account.\n"
            f"Use /start to begin searching.",
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ handle_account_login: {e}")
        await event.respond("❌ Error during login. Contact @darkboxesAdmin.")


# ================== DOWNLOAD CLIENT & CREDENTIALS CALLBACKS ==================

# ================== EMBEDDED CLIENT FILES ==================
# Client script and instructions are embedded as base64 so they
# can be sent to users without needing any file on disk.

import base64 as _b64
from io import BytesIO as _BytesIO

_CLIENT_SCRIPT_B64 = (
    "IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwojIC0qLSBjb2Rpbmc6IHV0Zi04IC0qLQoiIiIK4pWU4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWXCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgICAgICAgICAgREFSS0JPWEVTIElOVEVMTElHRU5DRSBTWVNURU0gICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWRICAgICAgICAgIFByb2Zlc3Npb25hbCBUZXJtaW5hbCBDbGllbnQgdjMuMCAgICAgICAgICAgICAgICAgICAgICAg4pWRCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgICAgICAgICAgRm9yIGF1dGhvcml6ZWQgdXNlIG9ubHkuICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWRICAgICAgICAgIMKpIDIwMjUgRGFya0JveGVzIEludGVsbGlnZW5jZS4gQWxsIHJpZ2h0cyByZXNlcnZlZC4gICAg4pWRCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZrilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZ0KCkNvbnRhY3QgIDogQGRhcmtib3hlc0FkbWluIChUZWxlZ3JhbSkKRW1haWwgICAgOiB5YWRpaWZ5QGdtYWlsLmNvbQpDaGFubmVsICA6IEBkYXJrYm94ZXN2MQoiIiIKCmltcG9ydCBvcwppbXBvcnQgc3lzCmltcG9ydCBqc29uCmltcG9ydCB0aW1lCmltcG9ydCBoYXNobGliCmltcG9ydCBnZXRwYXNzCmltcG9ydCB0ZXh0d3JhcAppbXBvcnQgcmUKaW1wb3J0IHBsYXRmb3JtCmZyb20gZGF0ZXRpbWUgaW1wb3J0IGRhdGV0aW1lCmZyb20gdHlwaW5nIGltcG9ydCBEaWN0LCBPcHRpb25hbCwgQW55CgojIOKUgOKUgCBEZXBlbmRlbmN5IGNoZWNrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAp0cnk6CiAgICBpbXBvcnQgcmVxdWVzdHMKZXhjZXB0IEltcG9ydEVycm9yOgogICAgcHJpbnQoIlxuWyFdIE1pc3NpbmcgZGVwZW5kZW5jeTogcmVxdWVzdHMiKQogICAgcHJpbnQoIiAgICBJbnN0YWxsIHdpdGg6ICBwaXAgaW5zdGFsbCByZXF1ZXN0cyIpCiAgICBwcmludCgiICAgIE9uIFRlcm11eDogICAgIHBpcCBpbnN0YWxsIHJlcXVlc3RzIikKICAgIHN5cy5leGl0KDEpCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIENPTkZJR1VSQVRJT04KIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCkFQSV9CQVNFX1VSTCA9IG9zLmdldGVudigiREFSS0JPWEVTX0FQSV9VUkwiLCAiaHR0cHM6Ly9yZWxheS13emx6Lm9ucmVuZGVyLmNvbSIpClJFUVVFU1RfVElNRU9VVCA9IDkwClNFU1NJT05fRklMRSAgICA9IG9zLnBhdGguZXhwYW5kdXNlcigifi8uZGFya2JveGVzX3Nlc3Npb24uanNvbiIpClJFU1VMVFNfRElSICAgICA9IG9zLnBhdGguZXhwYW5kdXNlcigifi9kYXJrYm94ZXNfcmVzdWx0cyIpCgpWRVJTSU9OICAgICAgICAgPSAiMy4wIgpCVUlMRF9EQVRFICAgICAgPSAiMjAyNSIKRlVMTF9OQU1FICAgICAgID0gIkRBUktCT1hFUyBJTlRFTExJR0VOQ0UgU1lTVEVNIgpTVVBQT1JUX1RHICAgICAgPSAiQGRhcmtib3hlc0FkbWluIgpTVVBQT1JUX0VNQUlMICAgPSAieWFkaWlmeUBnbWFpbC5jb20iCkNIQU5ORUwgICAgICAgICA9ICJAZGFya2JveGVzdjEiCgojIOKUgOKUgCBEZXRlY3QgbmFycm93IHRlcm1pbmFsIChUZXJtdXgtZnJpZW5kbHkpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAp0cnk6CiAgICBURVJNX1dJRFRIID0gb3MuZ2V0X3Rlcm1pbmFsX3NpemUoKS5jb2x1bW5zCmV4Y2VwdCBFeGNlcHRpb246CiAgICBURVJNX1dJRFRIID0gNjAgICAgIyBzYWZlIGRlZmF1bHQgZm9yIFRlcm11eAoKTkFSUk9XID0gVEVSTV9XSURUSCA8IDcyICAgIyB1c2UgMi1saW5lIG1vZGUgd2hlbiB0ZXJtaW5hbCBpcyBuYXJyb3cKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgQ09MT1JTCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgpkZWYgX3N1cHBvcnRzX2NvbG9yKCkgLT4gYm9vbDoKICAgICIiIkNoZWNrIGlmIHRlcm1pbmFsIHN1cHBvcnRzIEFOU0kgY29sb3IgY29kZXMuIiIiCiAgICBpZiBvcy5nZXRlbnYoIk5PX0NPTE9SIik6CiAgICAgICAgcmV0dXJuIEZhbHNlCiAgICBpZiBwbGF0Zm9ybS5zeXN0ZW0oKSA9PSAiV2luZG93cyI6CiAgICAgICAgcmV0dXJuIG9zLmdldGVudigiQU5TSUNPTiIpIGlzIG5vdCBOb25lCiAgICByZXR1cm4gaGFzYXR0cihzeXMuc3Rkb3V0LCAiaXNhdHR5IikgYW5kIHN5cy5zdGRvdXQuaXNhdHR5KCkKCl9VU0VfQ09MT1IgPSBfc3VwcG9ydHNfY29sb3IoKQoKY2xhc3MgQzoKICAgICIiIkNvbG9yIGNvbnN0YW50cyDigJQgYXV0by1kaXNhYmxlZCBvbiBwbGFpbiB0ZXJtaW5hbHMuIiIiCiAgICBpZiBfVVNFX0NPTE9SOgogICAgICAgIFIgICA9ICdcMDMzWzBtJyAgICAgICMgcmVzZXQKICAgICAgICBCICAgPSAnXDAzM1sxbScgICAgICAjIGJvbGQKICAgICAgICBESU0gPSAnXDAzM1sybScKICAgICAgICBVTCAgPSAnXDAzM1s0bScKCiAgICAgICAgQkxLID0gJ1wwMzNbMzg7NTsyNDBtJyAgICMgZGFyayBncmF5CiAgICAgICAgR1JOID0gJ1wwMzNbMzg7NTs0Nm0nICAgICMgYnJpZ2h0IGdyZWVuCiAgICAgICAgQ1lOID0gJ1wwMzNbMzg7NTs1MW0nICAgICMgYnJpZ2h0IGN5YW4KICAgICAgICBZTFcgPSAnXDAzM1szODs1OzIyNm0nICAgIyBicmlnaHQgeWVsbG93CiAgICAgICAgUkVEID0gJ1wwMzNbMzg7NTsxOTZtJyAgICMgYnJpZ2h0IHJlZAogICAgICAgIFdIVCA9ICdcMDMzWzk3bScKICAgICAgICBNQUcgPSAnXDAzM1szODs1OzIxM20nICAgIyBtYWdlbnRhL3BpbmsKICAgICAgICBCTFUgPSAnXDAzM1szODs1Ozc1bScgICAgIyBibHVlCgogICAgICAgIE9LICA9ICdcMDMzWzkybScKICAgICAgICBJTkYgPSAnXDAzM1s5Nm0nCiAgICAgICAgV1JOID0gJ1wwMzNbOTNtJwogICAgICAgIEVSUiA9ICdcMDMzWzkxbScKICAgIGVsc2U6CiAgICAgICAgUj1CPURJTT1VTD1CTEs9R1JOPUNZTj1ZTFc9UkVEPVdIVD1NQUc9QkxVPU9LPUlORj1XUk49RVJSID0gJycKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIERJU1BMQVkgSEVMUEVSUwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKZGVmIF9saW5lKGNoYXI6IHN0ciA9ICfilIAnLCB3aWR0aDogaW50ID0gTm9uZSkgLT4gc3RyOgogICAgdyA9IHdpZHRoIG9yIG1pbihURVJNX1dJRFRILCA3MCkKICAgIHJldHVybiBjaGFyICogdwoKZGVmIF9jZW50ZXIodGV4dDogc3RyLCB3aWR0aDogaW50ID0gTm9uZSkgLT4gc3RyOgogICAgdyA9IHdpZHRoIG9yIG1pbihURVJNX1dJRFRILCA3MCkKICAgIHJldHVybiB0ZXh0LmNlbnRlcih3KQoKZGVmIF9ib3hfbGluZSh0ZXh0OiBzdHIsIGNoYXI6IHN0ciA9ICfilZEnLCB3aWR0aDogaW50ID0gTm9uZSkgLT4gc3RyOgogICAgIiIiUHJpbnQgYSB0ZXh0IGluc2lkZSBhIGJveCByb3csIGZpdHRpbmcgdGhlIHRlcm1pbmFsLiIiIgogICAgdyA9ICh3aWR0aCBvciBtaW4oVEVSTV9XSURUSCwgNzApKSAtIDQKICAgIHJldHVybiBmIntjaGFyfSB7dGV4dDo8e3d9fSB7Y2hhcn0iCgpkZWYgcHJpbnRfYmFubmVyKCk6CiAgICAiIiJQcmludCB0aGUgRGFya0JveGVzIGJhbm5lciDigJQgYXV0by1hZGFwdHMgdG8gdGVybWluYWwgd2lkdGguIiIiCiAgICB3ID0gbWluKFRFUk1fV0lEVEgsIDcwKQogICAgcHJpbnQoKQoKICAgIGlmIE5BUlJPVzoKICAgICAgICAjIENvbXBhY3QgMi1saW5lIGJhbm5lciBmb3Igc21hbGwgdGVybWluYWxzIChUZXJtdXgpCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk59e0MuQn0iICsgIj0iICogdyArIEMuUikKICAgICAgICBwcmludChmIntDLkdSTn17Qy5CfSIgKyBfY2VudGVyKCIgREFSS0JPWEVTICIsIHcpLnJlcGxhY2UoIiAiLCAi4pWQIiwgMSkgKyBDLlIpCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk59IiArIF9jZW50ZXIoIklOVEVMTElHRU5DRSBTWVNURU0iLCB3KSArIEMuUikKICAgICAgICBwcmludChmIntDLllMV30iICsgX2NlbnRlcihmIlRlcm1pbmFsIENsaWVudCB2e1ZFUlNJT059IiwgdykgKyBDLlIpCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk59IiArICI9IiAqIHcgKyBDLlIpCiAgICBlbHNlOgogICAgICAgIGJvcmRlciA9ICLilZQiICsgIuKVkCIgKiAodyAtIDIpICsgIuKVlyIKICAgICAgICBib3JkZXJfYiA9ICLilZoiICsgIuKVkCIgKiAodyAtIDIpICsgIuKVnSIKICAgICAgICByb3dfYmxhbmsgPSAi4pWRIiArICIgIiAqICh3IC0gMikgKyAi4pWRIgogICAgICAgIHByaW50KGYie0MuR1JOfXtDLkJ9e2JvcmRlcn17Qy5SfSIpCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk59e3Jvd19ibGFua317Qy5SfSIpCgogICAgICAgIHRpdGxlID0gIiBEQVJLQk9YRVMgSU5URUxMSUdFTkNFIFNZU1RFTSAiCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk594pWRe0MuWUxXfXtDLkJ9e3RpdGxlLmNlbnRlcih3LTIpfXtDLlJ9e0MuR1JOfeKVkXtDLlJ9IikKCiAgICAgICAgc3ViID0gZiIgUHJvZmVzc2lvbmFsIFRlcm1pbmFsIENsaWVudCAgdntWRVJTSU9OfSAiCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk594pWRe0MuQ1lOfXtzdWIuY2VudGVyKHctMil9e0MuUn17Qy5HUk594pWRe0MuUn0iKQogICAgICAgIHByaW50KGYie0MuR1JOfeKVkXtDLkJMS317JyBGb3IgYXV0aG9yaXplZCB1c2Ugb25seSAnLmNlbnRlcih3LTIpfXtDLlJ9e0MuR1JOfeKVkXtDLlJ9IikKICAgICAgICBwcmludChmIntDLkdSTn17cm93X2JsYW5rfXtDLlJ9IikKICAgICAgICBwcmludChmIntDLkdSTn17Ym9yZGVyX2J9e0MuUn0iKQoKICAgIHByaW50KGYie0MuQkxLfXtfbGluZSgpfXtDLlJ9IikKICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZLSVtLSVkICAlSDolTTolUyIpCiAgICBzdGF0dXNfbGluZSA9IGYiICBTdGF0dXM6IHtDLkdSTn1PTkxJTkV7Qy5SfSAgIFRpbWU6IHtDLkNZTn17dHN9e0MuUn0iCiAgICBwcmludChzdGF0dXNfbGluZSkKICAgIHByaW50KGYie0MuQkxLfXtfbGluZSgpfXtDLlJ9IikKICAgIHByaW50KCkKCgpkZWYgc2VjdGlvbih0aXRsZTogc3RyKToKICAgICIiIlByaW50IGEgc2VjdGlvbiBoZWFkaW5nLiIiIgogICAgdyA9IG1pbihURVJNX1dJRFRILCA3MCkKICAgIHByaW50KCkKICAgIHByaW50KGYie0MuQ1lOfXtfbGluZSgn4pWQJywgdyl9e0MuUn0iKQogICAgcHJpbnQoZiJ7Qy5DWU59e0MuQn0gIHt0aXRsZS51cHBlcigpfXtDLlJ9IikKICAgIHByaW50KGYie0MuQ1lOfXtfbGluZSgn4pWQJywgdyl9e0MuUn0iKQogICAgcHJpbnQoKQoKCmRlZiBzdWJzZWN0aW9uKHRpdGxlOiBzdHIpOgogICAgIiIiUHJpbnQgYSBzdWItaGVhZGluZy4iIiIKICAgIHByaW50KGYiXG57Qy5CTFV9ICDilIDilIDilIAge3RpdGxlfSB7J+KUgCcgKiBtYXgoMSwgbWluKFRFUk1fV0lEVEgsNzApIC0gbGVuKHRpdGxlKSAtIDgpfXtDLlJ9IikKCgpkZWYgb2sobXNnOiBzdHIpOgogICAgcHJpbnQoZiIgIHtDLk9LfVvinJNde0MuUn0ge21zZ30iKQoKZGVmIGluZm8obXNnOiBzdHIpOgogICAgcHJpbnQoZiIgIHtDLklORn1baV17Qy5SfSB7bXNnfSIpCgpkZWYgd2Fybihtc2c6IHN0cik6CiAgICBwcmludChmIiAge0MuV1JOfVshXXtDLlJ9IHttc2d9IikKCmRlZiBlcnIobXNnOiBzdHIpOgogICAgcHJpbnQoZiIgIHtDLkVSUn1b4pyXXXtDLlJ9IHttc2d9IikKCmRlZiBmaWVsZChrZXk6IHN0ciwgdmFsdWU6IHN0cik6CiAgICAiIiJQcmludCBhIGtleS12YWx1ZSByZXN1bHQgZmllbGQuIiIiCiAgICBpZiBOQVJST1c6CiAgICAgICAgIyBUd28gbGluZXMgb24gbmFycm93IHRlcm1pbmFscwogICAgICAgIHByaW50KGYiICB7Qy5CTEt94pSMe0MuUn0ge0MuQn17a2V5fXtDLlJ9IikKICAgICAgICBwcmludChmIiAge0MuQkxLfeKUlOKUgHtDLlJ9IHtDLkdSTn17dmFsdWV9e0MuUn0iKQogICAgZWxzZToKICAgICAgICBwYWQgPSBtYXgoMSwgMjIgLSBsZW4oa2V5KSkKICAgICAgICBwcmludChmIiAge0MuQkxLfeKUgntDLlJ9IHtDLkJ9e2tleX17Qy5SfXsnICcgKiBwYWR9e0MuR1JOfXt2YWx1ZX17Qy5SfSIpCgpkZWYgc2VwYXJhdG9yKCk6CiAgICBwcmludChmIiAge0MuQkxLfXtfbGluZSgnwrcnLCBtaW4oVEVSTV9XSURUSC00LCA2NikpfXtDLlJ9IikKCmRlZiBwcm9tcHQobGFiZWw6IHN0ciwgZGVmYXVsdDogc3RyID0gIiIpIC0+IHN0cjoKICAgICIiIlN0eWxlZCBpbnB1dCBwcm9tcHQg4oCUIGFsd2F5cyBvbiBpdHMgb3duIGxpbmUuIiIiCiAgICBpZiBOQVJST1c6CiAgICAgICAgcHJpbnQoZiJcbiAge0MuQ1lOfeKWtiAge2xhYmVsfXtDLlJ9IikKICAgICAgICByZXNwID0gaW5wdXQoZiIgIHtDLllMV33ihpIgIHtDLlJ9Iikuc3RyaXAoKQogICAgZWxzZToKICAgICAgICByZXNwID0gaW5wdXQoZiJcbiAge0MuQ1lOfeKWtiAge2xhYmVsfToge0MuWUxXfSIpLnN0cmlwKCkKICAgICAgICBwcmludChDLlIsIGVuZD0iIikKICAgIHJldHVybiByZXNwIGlmIHJlc3AgZWxzZSBkZWZhdWx0CgpkZWYgcHJvbXB0X3Bhc3N3b3JkKGxhYmVsOiBzdHIpIC0+IHN0cjoKICAgICIiIlBhc3N3b3JkIHByb21wdCAoaGlkZGVuIGlucHV0KS4iIiIKICAgIGlmIE5BUlJPVzoKICAgICAgICBwcmludChmIlxuICB7Qy5DWU594pa2ICB7bGFiZWx9e0MuUn0iKQogICAgZWxzZToKICAgICAgICBwcmludChmIlxuICB7Qy5DWU594pa2ICB7bGFiZWx9OiB7Qy5SfSIsIGVuZD0iIiwgZmx1c2g9VHJ1ZSkKICAgIHRyeToKICAgICAgICBwdyA9IGdldHBhc3MuZ2V0cGFzcygiIikKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcHcgPSBpbnB1dCgiICAiKS5zdHJpcCgpCiAgICByZXR1cm4gcHcKCmRlZiBsb2FkaW5nKG1zZzogc3RyKToKICAgIHByaW50KGYiICB7Qy5ZTFd9W+Kfs117Qy5SfSB7bXNnfSIsIGVuZD0iIiwgZmx1c2g9VHJ1ZSkKCmRlZiBjbGVhcl9sb2FkaW5nKCk6CiAgICBwcmludChmIlxyeycgJyAqIG1pbihURVJNX1dJRFRILCA3MCl9XHIiLCBlbmQ9IiIsIGZsdXNoPVRydWUpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBTRVNTSU9OIE1BTkFHRU1FTlQKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmNsYXNzIFNlc3Npb246CiAgICAiIiJQZXJzaXN0IGxvZ2luIHN0YXRlIGJldHdlZW4gcnVucy4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5hY2NvdW50X2lkOiBzdHIgID0gIiIKICAgICAgICBzZWxmLmFwaV9rZXk6IHN0ciAgICAgPSAiIgogICAgICAgIHNlbGYudXNlcm5hbWU6IHN0ciAgICA9ICIiCiAgICAgICAgc2VsZi5jcmVkaXRzOiBpbnQgICAgID0gMAogICAgICAgIHNlbGYucGxhbjogc3RyICAgICAgICA9ICJOb25lIgogICAgICAgIHNlbGYuX2xvYWRlZCAgICAgICAgICA9IEZhbHNlCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIG9zLnBhdGguZXhpc3RzKFNFU1NJT05fRklMRSk6CiAgICAgICAgICAgICAgICB3aXRoIG9wZW4oU0VTU0lPTl9GSUxFLCAiciIpIGFzIGY6CiAgICAgICAgICAgICAgICAgICAgZCA9IGpzb24ubG9hZChmKQogICAgICAgICAgICAgICAgc2VsZi5hY2NvdW50X2lkID0gZC5nZXQoImFjY291bnRfaWQiLCAiIikKICAgICAgICAgICAgICAgIHNlbGYuYXBpX2tleSAgICA9IGQuZ2V0KCJhcGlfa2V5IiwgIiIpCiAgICAgICAgICAgICAgICBzZWxmLnVzZXJuYW1lICAgPSBkLmdldCgidXNlcm5hbWUiLCAiIikKICAgICAgICAgICAgICAgIHNlbGYuY3JlZGl0cyAgICA9IGQuZ2V0KCJjcmVkaXRzIiwgMCkKICAgICAgICAgICAgICAgIHNlbGYucGxhbiAgICAgICA9IGQuZ2V0KCJwbGFuIiwgIk5vbmUiKQogICAgICAgICAgICAgICAgaWYgc2VsZi5hY2NvdW50X2lkIGFuZCBzZWxmLmFwaV9rZXk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBzYXZlKHNlbGYpOgogICAgICAgIHRyeToKICAgICAgICAgICAgb3MubWFrZWRpcnMob3MucGF0aC5kaXJuYW1lKFNFU1NJT05fRklMRSksIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHdpdGggb3BlbihTRVNTSU9OX0ZJTEUsICJ3IikgYXMgZjoKICAgICAgICAgICAgICAgIGpzb24uZHVtcCh7CiAgICAgICAgICAgICAgICAgICAgImFjY291bnRfaWQiOiBzZWxmLmFjY291bnRfaWQsCiAgICAgICAgICAgICAgICAgICAgImFwaV9rZXkiOiAgICBzZWxmLmFwaV9rZXksCiAgICAgICAgICAgICAgICAgICAgInVzZXJuYW1lIjogICBzZWxmLnVzZXJuYW1lLAogICAgICAgICAgICAgICAgICAgICJjcmVkaXRzIjogICAgc2VsZi5jcmVkaXRzLAogICAgICAgICAgICAgICAgICAgICJwbGFuIjogICAgICAgc2VsZi5wbGFuLAogICAgICAgICAgICAgICAgICAgICJzYXZlZF9hdCI6ICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgIH0sIGYsIGluZGVudD0yKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBkZWYgY2xlYXIoc2VsZik6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBvcy5wYXRoLmV4aXN0cyhTRVNTSU9OX0ZJTEUpOgogICAgICAgICAgICAgICAgb3MucmVtb3ZlKFNFU1NJT05fRklMRSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgc2VsZi5hY2NvdW50X2lkID0gIiIKICAgICAgICBzZWxmLmFwaV9rZXkgICAgPSAiIgogICAgICAgIHNlbGYudXNlcm5hbWUgICA9ICIiCiAgICAgICAgc2VsZi5jcmVkaXRzICAgID0gMAogICAgICAgIHNlbGYucGxhbiAgICAgICA9ICJOb25lIgoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGlzX3ZhbGlkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGJvb2woc2VsZi5hY2NvdW50X2lkIGFuZCBzZWxmLmFwaV9rZXkpCgoKc2Vzc2lvbiA9IFNlc3Npb24oKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgQVBJIENMSUVOVAojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKY2xhc3MgRGFya0JveGVzQVBJOgogICAgIiIiSFRUUCBjbGllbnQgZm9yIHRoZSBEYXJrQm94ZXMgYmFja2VuZC4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fc2Vzc2lvbiA9IHJlcXVlc3RzLlNlc3Npb24oKQogICAgICAgIHNlbGYuX3Nlc3Npb24uaGVhZGVycy51cGRhdGUoewogICAgICAgICAgICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICAgICAgIlVzZXItQWdlbnQiOiAgICBmIkRhcmtCb3hlcy1DbGllbnQve1ZFUlNJT059IFB5dGhvbi97c3lzLnZlcnNpb24uc3BsaXQoKVswXX0iLAogICAgICAgICAgICAiQWNjZXB0IjogICAgICAgICJhcHBsaWNhdGlvbi9qc29uIgogICAgICAgIH0pCgogICAgZGVmIF9zZXRfYXV0aChzZWxmLCBhcGlfa2V5OiBzdHIpOgogICAgICAgIHNlbGYuX3Nlc3Npb24uaGVhZGVyc1siWC1BUEktS2V5Il0gPSBhcGlfa2V5CgogICAgZGVmIF9yZXF1ZXN0KHNlbGYsIG1ldGhvZDogc3RyLCBlbmRwb2ludDogc3RyLAogICAgICAgICAgICAgICAgIGRhdGE6IERpY3QgPSBOb25lLCBub19hdXRoOiBib29sID0gRmFsc2UpIC0+IERpY3Q6CiAgICAgICAgdXJsID0gZiJ7QVBJX0JBU0VfVVJMfXtlbmRwb2ludH0iCiAgICAgICAgaWYgbm90IG5vX2F1dGggYW5kIHNlc3Npb24uYXBpX2tleToKICAgICAgICAgICAgc2VsZi5fc2V0X2F1dGgoc2Vzc2lvbi5hcGlfa2V5KQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIG1ldGhvZCA9PSAiR0VUIjoKICAgICAgICAgICAgICAgIHJlc3AgPSBzZWxmLl9zZXNzaW9uLmdldCh1cmwsIHRpbWVvdXQ9UkVRVUVTVF9USU1FT1VUKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgcmVzcCA9IHNlbGYuX3Nlc3Npb24ucG9zdCh1cmwsIGpzb249ZGF0YSBvciB7fSwgdGltZW91dD1SRVFVRVNUX1RJTUVPVVQpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1c19jb2RlID09IDIwMDoKICAgICAgICAgICAgICAgIHJldHVybiByZXNwLmpzb24oKQogICAgICAgICAgICBlbGlmIHJlc3Auc3RhdHVzX2NvZGUgPT0gNDAxOgogICAgICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiVU5BVVRIT1JJWkVEIiwKICAgICAgICAgICAgICAgICAgICAgICAgIm1lc3NhZ2UiOiAiSW52YWxpZCBvciBleHBpcmVkIGNyZWRlbnRpYWxzLiBQbGVhc2UgbG9nIGluIGFnYWluLiJ9CiAgICAgICAgICAgIGVsaWYgcmVzcC5zdGF0dXNfY29kZSA9PSA0MDM6CiAgICAgICAgICAgICAgICByZXR1cm4geyJzdGF0dXMiOiAiZXJyb3IiLCAiY29kZSI6ICJGT1JCSURERU4iLAogICAgICAgICAgICAgICAgICAgICAgICAibWVzc2FnZSI6ICJJbnN1ZmZpY2llbnQgY3JlZGl0cyBvciBhY2NvdW50IGJhbm5lZC4ifQogICAgICAgICAgICBlbGlmIHJlc3Auc3RhdHVzX2NvZGUgPT0gNDI5OgogICAgICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiUkFURV9MSU1JVCIsCiAgICAgICAgICAgICAgICAgICAgICAgICJtZXNzYWdlIjogIlRvbyBtYW55IHJlcXVlc3RzLiBQbGVhc2Ugd2FpdCBhIG1vbWVudC4ifQogICAgICAgICAgICBlbGlmIHJlc3Auc3RhdHVzX2NvZGUgPT0gNDA0OgogICAgICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiTk9UX0ZPVU5EIiwKICAgICAgICAgICAgICAgICAgICAgICAgIm1lc3NhZ2UiOiAiRW5kcG9pbnQgbm90IGZvdW5kLiJ9CiAgICAgICAgICAgIGVsaWYgcmVzcC5zdGF0dXNfY29kZSA+PSA1MDA6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgZXJyX2JvZHkgPSByZXNwLmpzb24oKQogICAgICAgICAgICAgICAgICAgIGVycl9tc2cgPSBlcnJfYm9keS5nZXQoIm1lc3NhZ2UiLCBmIlNlcnZlciBlcnJvciAoe3Jlc3Auc3RhdHVzX2NvZGV9KSIpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIGVycl9tc2cgPSBmIlNlcnZlciBlcnJvciAoe3Jlc3Auc3RhdHVzX2NvZGV9KSIKICAgICAgICAgICAgICAgIHJldHVybiB7InN0YXR1cyI6ICJlcnJvciIsICJjb2RlIjogIlNFUlZFUl9FUlJPUiIsICJtZXNzYWdlIjogZXJyX21zZ30KICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gcmVzcC5qc29uKCkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiSFRUUF9FUlJPUiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAibWVzc2FnZSI6IGYiSFRUUCB7cmVzcC5zdGF0dXNfY29kZX0ifQoKICAgICAgICBleGNlcHQgcmVxdWVzdHMuVGltZW91dDoKICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiVElNRU9VVCIsCiAgICAgICAgICAgICAgICAgICAgIm1lc3NhZ2UiOiAiUmVxdWVzdCB0aW1lZCBvdXQuIFNlcnZlciBtYXkgYmUgYnVzeSDigJQgdHJ5IGFnYWluLiJ9CiAgICAgICAgZXhjZXB0IHJlcXVlc3RzLkNvbm5lY3Rpb25FcnJvcjoKICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiQ09OTkVDVElPTl9FUlJPUiIsCiAgICAgICAgICAgICAgICAgICAgIm1lc3NhZ2UiOiAiQ2Fubm90IHJlYWNoIHNlcnZlci4gQ2hlY2sgeW91ciBpbnRlcm5ldCBjb25uZWN0aW9uLiJ9CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICByZXR1cm4geyJzdGF0dXMiOiAiZXJyb3IiLCAiY29kZSI6ICJDTElFTlRfRVJST1IiLCAibWVzc2FnZSI6IHN0cihlKX0KCiAgICAjIOKUgOKUgCBBdXRoIGVuZHBvaW50cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKCiAgICBkZWYgcmVnaXN0ZXIoc2VsZiwgdXNlcm5hbWU6IHN0ciwgcGFzc3dvcmQ6IHN0cikgLT4gRGljdDoKICAgICAgICByZXR1cm4gc2VsZi5fcmVxdWVzdCgiUE9TVCIsICIvYXBpL3YxL2F1dGgvcmVnaXN0ZXIiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHsidXNlcm5hbWUiOiB1c2VybmFtZSwgInBhc3N3b3JkIjogcGFzc3dvcmR9LCBub19hdXRoPVRydWUpCgogICAgZGVmIGxvZ2luKHNlbGYsIGFjY291bnRfaWRfb3JfdXNlcm5hbWU6IHN0ciwgcGFzc3dvcmQ6IHN0cikgLT4gRGljdDoKICAgICAgICByZXR1cm4gc2VsZi5fcmVxdWVzdCgiUE9TVCIsICIvYXBpL3YxL2F1dGgvbG9naW4iLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHsiYWNjb3VudF9pZCI6IGFjY291bnRfaWRfb3JfdXNlcm5hbWUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJwYXNzd29yZCI6ICAgcGFzc3dvcmR9LCBub19hdXRoPVRydWUpCgogICAgIyDilIDilIAgVXRpbGl0eSBlbmRwb2ludHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACgogICAgZGVmIHN0YXR1cyhzZWxmKSAgLT4gRGljdDogcmV0dXJuIHNlbGYuX3JlcXVlc3QoIkdFVCIsICAiL2FwaS92MS9zdGF0dXMiKQogICAgZGVmIGJhbGFuY2Uoc2VsZikgLT4gRGljdDogcmV0dXJuIHNlbGYuX3JlcXVlc3QoIkdFVCIsICAiL2FwaS92MS9iYWxhbmNlIikKICAgIGRlZiB1c2FnZShzZWxmKSAgIC0+IERpY3Q6IHJldHVybiBzZWxmLl9yZXF1ZXN0KCJHRVQiLCAgIi9hcGkvdjEvdXNhZ2UiKQogICAgZGVmIGRvY3Moc2VsZikgICAgLT4gRGljdDogcmV0dXJuIHNlbGYuX3JlcXVlc3QoIkdFVCIsICAiL2FwaS92MS9kb2NzIikKCiAgICAjIOKUgOKUgCBTZWFyY2ggZW5kcG9pbnRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKICAgIGRlZiBzZWFyY2goc2VsZiwgc2VhcmNoX3R5cGU6IHN0ciwgcXVlcnk6IHN0cikgLT4gRGljdDoKICAgICAgICBlbmRwb2ludF9tYXAgPSB7CiAgICAgICAgICAgICJwaG9uZSI6ICAgICIvYXBpL3YxL3NlYXJjaC9waG9uZSIsCiAgICAgICAgICAgICJmYW1pbHkiOiAgICIvYXBpL3YxL3NlYXJjaC9mYW1pbHkiLAogICAgICAgICAgICAiYWFkaGFyIjogICAiL2FwaS92MS9zZWFyY2gvYWFkaGFyIiwKICAgICAgICAgICAgInZlaGljbGUiOiAgIi9hcGkvdjEvc2VhcmNoL3ZlaGljbGUiLAogICAgICAgICAgICAidXBpIjogICAgICAiL2FwaS92MS9zZWFyY2gvdXBpIiwKICAgICAgICAgICAgImVtYWlsIjogICAgIi9hcGkvdjEvc2VhcmNoL2VtYWlsIiwKICAgICAgICAgICAgInRlbGVncmFtIjogIi9hcGkvdjEvc2VhcmNoL3RlbGVncmFtIiwKICAgICAgICAgICAgImltZWkiOiAgICAgIi9hcGkvdjEvc2VhcmNoL2ltZWkiLAogICAgICAgICAgICAiZ3N0IjogICAgICAiL2FwaS92MS9zZWFyY2gvZ3N0IiwKICAgICAgICAgICAgImluc3RhIjogICAgIi9hcGkvdjEvc2VhcmNoL2luc3RhZ3JhbSIsCiAgICAgICAgICAgICJpbnN0YWdyYW0iOiIvYXBpL3YxL3NlYXJjaC9pbnN0YWdyYW0iLAogICAgICAgICAgICAicGFrIjogICAgICAiL2FwaS92MS9zZWFyY2gvcGFraXN0YW4iLAogICAgICAgICAgICAiaXAiOiAgICAgICAiL2FwaS92MS9zZWFyY2gvaXAiLAogICAgICAgICAgICAiaWZzYyI6ICAgICAiL2FwaS92MS9zZWFyY2gvaWZzYyIsCiAgICAgICAgICAgICJsZWFrIjogICAgICIvYXBpL3YxL3NlYXJjaC9sZWFrIiwKICAgICAgICB9CiAgICAgICAgZW5kcG9pbnQgPSBlbmRwb2ludF9tYXAuZ2V0KHNlYXJjaF90eXBlLmxvd2VyKCkpCiAgICAgICAgaWYgbm90IGVuZHBvaW50OgogICAgICAgICAgICByZXR1cm4geyJzdGF0dXMiOiAiZXJyb3IiLCAibWVzc2FnZSI6IGYiVW5rbm93biBzZWFyY2ggdHlwZToge3NlYXJjaF90eXBlfSJ9CiAgICAgICAgcmV0dXJuIHNlbGYuX3JlcXVlc3QoIlBPU1QiLCBlbmRwb2ludCwgeyJxdWVyeSI6IHF1ZXJ5fSkKCiAgICBkZWYgYmF0Y2hfc2VhcmNoKHNlbGYsIHNlYXJjaGVzOiBsaXN0KSAtPiBEaWN0OgogICAgICAgIHJldHVybiBzZWxmLl9yZXF1ZXN0KCJQT1NUIiwgIi9hcGkvdjEvc2VhcmNoL2JhdGNoIiwgeyJzZWFyY2hlcyI6IHNlYXJjaGVzfSkKCiAgICBkZWYgc3VibWl0X3V0cihzZWxmLCB1dHI6IHN0ciwgcGxhbjogc3RyKSAtPiBEaWN0OgogICAgICAgIHJldHVybiBzZWxmLl9yZXF1ZXN0KCJQT1NUIiwgIi9hcGkvdjEvcGF5bWVudC91dHIiLCB7InV0ciI6IHV0ciwgInBsYW4iOiBwbGFufSkKCgphcGkgPSBEYXJrQm94ZXNBUEkoKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgUkVTVUxUIERJU1BMQVkKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmRlZiBkaXNwbGF5X3Jlc3VsdChyZXN1bHQ6IERpY3QsIHNlYXJjaF90eXBlOiBzdHIgPSAiIiwgcXVlcnk6IHN0ciA9ICIiKToKICAgICIiIlJlbmRlciBhIHNlYXJjaCByZXN1bHQgaW4gYSBwcm9mZXNzaW9uYWwgc3R5bGVkIGJsb2NrLiIiIgogICAgaWYgcmVzdWx0LmdldCgic3RhdHVzIikgIT0gInN1Y2Nlc3MiOgogICAgICAgIGVycihyZXN1bHQuZ2V0KCJtZXNzYWdlIiwgIlVua25vd24gZXJyb3IiKSkKICAgICAgICBjb2RlID0gcmVzdWx0LmdldCgiY29kZSIsICIiKQogICAgICAgIGlmIGNvZGUgPT0gIlVOQVVUSE9SSVpFRCI6CiAgICAgICAgICAgIHdhcm4oIlNlc3Npb24gZXhwaXJlZCBvciBpbnZhbGlkLiBVc2Ugb3B0aW9uIDMgdG8gTG9nIE91dCwgdGhlbiBvcHRpb24gMiB0byBMb2cgSW4gYWdhaW4uIikKICAgICAgICBlbGlmIGNvZGUgaW4gKCJGT1JCSURERU4iLCAiSU5TVUZGSUNJRU5UX0NSRURJVFMiKToKICAgICAgICAgICAgd2FybigiTm8gY3JlZGl0cyByZW1haW5pbmcuIENvbnRhY3QgQGRhcmtib3hlc0FkbWluIHRvIGJ1eSBtb3JlIGNyZWRpdHMgb3IgYSBwbGFuLiIpCiAgICAgICAgcmV0dXJuCgogICAgZGF0YSA9IHJlc3VsdC5nZXQoImRhdGEiLCB7fSkKICAgIHJhdyAgPSByZXN1bHQuZ2V0KCJyYXdfdGV4dCIpIG9yIGRhdGEuZ2V0KCJyYXdfdGV4dCIsICIiKQoKICAgIHN1YnNlY3Rpb24oZiJSRVNVTFQg4oCUIHtzZWFyY2hfdHlwZS51cHBlcigpfSDigLoge3F1ZXJ5fSIpCgogICAgIyBEaXNwbGF5IHBhcnNlZCBmaWVsZHMgaWYgYXZhaWxhYmxlCiAgICBwYXJzZWQgPSBkYXRhLmdldCgicGFyc2VkX2RhdGEiLCB7fSkgaWYgaXNpbnN0YW5jZShkYXRhLCBkaWN0KSBlbHNlIHt9CiAgICBpZiBwYXJzZWQ6CiAgICAgICAgZm9yIGssIHYgaW4gcGFyc2VkLml0ZW1zKCk6CiAgICAgICAgICAgIGlmIGsgYW5kIHY6CiAgICAgICAgICAgICAgICBmaWVsZChzdHIoayksIHN0cih2KSkKICAgIGVsaWYgaXNpbnN0YW5jZShkYXRhLCBkaWN0KSBhbmQgZGF0YToKICAgICAgICBmb3IgaywgdiBpbiBkYXRhLml0ZW1zKCk6CiAgICAgICAgICAgIGlmIGsgbm90IGluICgicmF3X3RleHQiLCAicGFyc2VkX2RhdGEiLCAic291cmNlIiwgInRpbWVzdGFtcCIsICJ0eXBlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICJuYW1lIiwgInF1ZXJ5IikgYW5kIHY6CiAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKHYsIChzdHIsIGludCwgZmxvYXQpKToKICAgICAgICAgICAgICAgICAgICBmaWVsZChzdHIoaykucmVwbGFjZSgiXyIsICIgIikudGl0bGUoKSwgc3RyKHYpKQoKICAgICMgQWx3YXlzIHNob3cgcmF3IHRleHQgYXMgZmFsbGJhY2sKICAgIGlmIHJhdyBhbmQgcmF3LnN0cmlwKCk6CiAgICAgICAgaWYgbm90IHBhcnNlZDoKICAgICAgICAgICAgc3Vic2VjdGlvbigiUmF3IEludGVsbGlnZW5jZSIpCiAgICAgICAgICAgIGxpbmVzID0gcmF3LnN0cmlwKCkuc3BsaXQoIlxuIikKICAgICAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpZiBsaW5lOgogICAgICAgICAgICAgICAgICAgIHByaW50KGYiICB7Qy5CTEt94pSCe0MuUn0ge2xpbmV9IikKCiAgICBzb3VyY2UgPSBkYXRhLmdldCgic291cmNlIiwgIkRhcmtCb3hlcyBOZXR3b3JrIikgaWYgaXNpbnN0YW5jZShkYXRhLCBkaWN0KSBlbHNlICIiCiAgICB0cyAgICAgPSBkYXRhLmdldCgidGltZXN0YW1wIiwgIiIpWzoxNl0ucmVwbGFjZSgiVCIsICIgIikgaWYgaXNpbnN0YW5jZShkYXRhLCBkaWN0KSBlbHNlICIiCgogICAgcHJpbnQoKQogICAgc2VwYXJhdG9yKCkKICAgIGlmIHNvdXJjZToKICAgICAgICBpbmZvKGYiU291cmNlOiB7c291cmNlfSIpCiAgICBpZiB0czoKICAgICAgICBpbmZvKGYiVGltZSAgOiB7dHN9IikKCiAgICAjIFNhdmUgcmVzdWx0CiAgICBfc2F2ZV9yZXN1bHQocmVzdWx0LCBzZWFyY2hfdHlwZSwgcXVlcnkpCgoKZGVmIF9zYXZlX3Jlc3VsdChyZXN1bHQ6IERpY3QsIHNlYXJjaF90eXBlOiBzdHIsIHF1ZXJ5OiBzdHIpOgogICAgIiIiQXV0by1zYXZlIHJlc3VsdCB0byBmaWxlLiIiIgogICAgdHJ5OgogICAgICAgIG9zLm1ha2VkaXJzKFJFU1VMVFNfRElSLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHRzICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVkXyVIJU0lUyIpCiAgICAgICAgc2FmZSA9IHJlLnN1YihyJ1teYS16QS1aMC05X1wtXScsICdfJywgcXVlcnkpWzoyMF0KICAgICAgICBmbmFtZSA9IGYie1JFU1VMVFNfRElSfS97c2VhcmNoX3R5cGV9X3tzYWZlfV97dHN9Lmpzb24iCiAgICAgICAgd2l0aCBvcGVuKGZuYW1lLCAidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIGpzb24uZHVtcCh7CiAgICAgICAgICAgICAgICAic2VhcmNoX3R5cGUiOiBzZWFyY2hfdHlwZSwKICAgICAgICAgICAgICAgICJxdWVyeSI6IHF1ZXJ5LAogICAgICAgICAgICAgICAgInRpbWVzdGFtcCI6IGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICAgICAgInJlc3VsdCI6IHJlc3VsdAogICAgICAgICAgICB9LCBmLCBpbmRlbnQ9MiwgZW5zdXJlX2FzY2lpPUZhbHNlKQogICAgICAgIGluZm8oZiJTYXZlZCDihpIge2ZuYW1lfSIpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHBhc3MKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIEFVVEggRkxPV1MKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmRlZiBmbG93X3JlZ2lzdGVyKCk6CiAgICAiIiJSZWdpc3RlciBhIG5ldyBhY2NvdW50IOKAlCBubyBUZWxlZ3JhbSBuZWVkZWQuIiIiCiAgICBzZWN0aW9uKCJDUkVBVEUgTkVXIEFDQ09VTlQiKQogICAgcHJpbnQoZiIgIHtDLllMV31Zb3UgZG8gbm90IG5lZWQgYSBUZWxlZ3JhbSBhY2NvdW50IHRvIHJlZ2lzdGVyLntDLlJ9IikKICAgIHByaW50KGYiICB7Qy5CTEt9Q3JlZGl0cyBhbmQgcGxhbnMgY2FuIGJlIHB1cmNoYXNlZCBmcm9tIHRoZSBUZWxlZ3JhbSBib3R7Qy5SfSIpCiAgICBwcmludChmIiAge0MuQkxLfShAZGFya2JveGVzQWRtaW4pIG9yIGRpcmVjdGx5IHRocm91Z2ggdGhlIHRlcm1pbmFsLntDLlJ9XG4iKQoKICAgIHdoaWxlIFRydWU6CiAgICAgICAgdXNlcm5hbWUgPSBwcm9tcHQoIkNob29zZSBhIHVzZXJuYW1lIChtaW4gMyBjaGFycywgbm8gc3BhY2VzKSIpCiAgICAgICAgaWYgbGVuKHVzZXJuYW1lKSA8IDM6CiAgICAgICAgICAgIHdhcm4oIlVzZXJuYW1lIG11c3QgYmUgYXQgbGVhc3QgMyBjaGFyYWN0ZXJzLiIpCiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgIiAiIGluIHVzZXJuYW1lOgogICAgICAgICAgICB3YXJuKCJVc2VybmFtZSBjYW5ub3QgY29udGFpbiBzcGFjZXMuIikKICAgICAgICAgICAgY29udGludWUKICAgICAgICBicmVhawoKICAgIHdoaWxlIFRydWU6CiAgICAgICAgcGFzc3dvcmQgPSBwcm9tcHRfcGFzc3dvcmQoIkNob29zZSBhIHBhc3N3b3JkIChtaW4gNiBjaGFycywgaGlkZGVuKSIpCiAgICAgICAgaWYgbGVuKHBhc3N3b3JkKSA8IDY6CiAgICAgICAgICAgIHdhcm4oIlBhc3N3b3JkIG11c3QgYmUgYXQgbGVhc3QgNiBjaGFyYWN0ZXJzLiIpCiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgY29uZmlybSA9IHByb21wdF9wYXNzd29yZCgiQ29uZmlybSBwYXNzd29yZCAoaGlkZGVuKSIpCiAgICAgICAgaWYgcGFzc3dvcmQgIT0gY29uZmlybToKICAgICAgICAgICAgd2FybigiUGFzc3dvcmRzIGRvIG5vdCBtYXRjaC4gVHJ5IGFnYWluLiIpCiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgYnJlYWsKCiAgICBsb2FkaW5nKCJDcmVhdGluZyBhY2NvdW50Li4uIikKICAgIHJlc3VsdCA9IGFwaS5yZWdpc3Rlcih1c2VybmFtZSwgcGFzc3dvcmQpCiAgICBjbGVhcl9sb2FkaW5nKCkKCiAgICBpZiByZXN1bHQuZ2V0KCJzdGF0dXMiKSA9PSAic3VjY2VzcyI6CiAgICAgICAgYWNjX2lkID0gcmVzdWx0LmdldCgiYWNjb3VudF9pZCIsICIiKQogICAgICAgIGNyZWRpdHMgPSByZXN1bHQuZ2V0KCJjcmVkaXRzIiwgMCkKICAgICAgICBvaygiQWNjb3VudCBjcmVhdGVkIHN1Y2Nlc3NmdWxseSEiKQogICAgICAgIHByaW50KCkKICAgICAgICBwcmludChmIiAge0MuR1JOfXsn4pSAJyo1MH17Qy5SfSIpCiAgICAgICAgZmllbGQoIkFjY291bnQgSUQiLCAgYWNjX2lkKQogICAgICAgIGZpZWxkKCJVc2VybmFtZSIsICAgIHVzZXJuYW1lKQogICAgICAgIGZpZWxkKCJDcmVkaXRzIiwgICAgIHN0cihjcmVkaXRzKSkKICAgICAgICBmaWVsZCgiUGxhbiIsICAgICAgICAiTm9uZSAocHVyY2hhc2UgdG8gYWN0aXZhdGUpIikKICAgICAgICBwcmludChmIiAge0MuR1JOfXsn4pSAJyo1MH17Qy5SfSIpCiAgICAgICAgcHJpbnQoKQogICAgICAgIHdhcm4oIlNBVkUgeW91ciBBY2NvdW50IElEIGFuZCBwYXNzd29yZCDigJQgdGhleSB3aWxsIG5vdCBiZSBzaG93biBhZ2Fpbi4iKQogICAgICAgIHdhcm4oIklmIHlvdSBsb3NlIHRoZW0sIGNvbnRhY3QgQGRhcmtib3hlc0FkbWluIG9yIHlhZGlpZnlAZ21haWwuY29tIikKICAgICAgICBwcmludCgpCiAgICAgICAgaW5mbygiVG8gbG9nIGluLCB1c2Ugb3B0aW9uIDIgaW4gdGhlIG1haW4gbWVudS4iKQogICAgICAgIGluZm8oIlRvIGJ1eSBjcmVkaXRzL3BsYW5zLCBjb250YWN0IHRoZSBUZWxlZ3JhbSBib3Qgb3IgQGRhcmtib3hlc0FkbWluLiIpCiAgICBlbHNlOgogICAgICAgIGVycihyZXN1bHQuZ2V0KCJtZXNzYWdlIiwgIlJlZ2lzdHJhdGlvbiBmYWlsZWQuIikpCgoKZGVmIGZsb3dfbG9naW4oKSAtPiBib29sOgogICAgIiIiTG9nIGluIHdpdGggQWNjb3VudCBJRCBvciB1c2VybmFtZSArIHBhc3N3b3JkLiIiIgogICAgc2VjdGlvbigiTE9HIElOIikKCiAgICBwcmludChmIiAge0MuWUxXfU5vIFRlbGVncmFtIGFjY291bnQgcmVxdWlyZWQue0MuUn0iKQogICAgcHJpbnQoZiIgIHtDLkJMS31Vc2UgeW91ciBBY2NvdW50IElEIChlLmcuIERCMUEyQjNDNEQpIG9yIHVzZXJuYW1lLntDLlJ9XG4iKQoKICAgIGlkZW50aWZpZXIgPSBwcm9tcHQoIkFjY291bnQgSUQgb3IgdXNlcm5hbWUiKQogICAgaWYgbm90IGlkZW50aWZpZXI6CiAgICAgICAgd2FybigiQ2FuY2VsbGVkLiIpCiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgcGFzc3dvcmQgPSBwcm9tcHRfcGFzc3dvcmQoIlBhc3N3b3JkIChoaWRkZW4pIikKICAgIGlmIG5vdCBwYXNzd29yZDoKICAgICAgICB3YXJuKCJDYW5jZWxsZWQuIikKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBsb2FkaW5nKCJBdXRoZW50aWNhdGluZy4uLiIpCiAgICByZXN1bHQgPSBhcGkubG9naW4oaWRlbnRpZmllciwgcGFzc3dvcmQpCiAgICBjbGVhcl9sb2FkaW5nKCkKCiAgICBpZiByZXN1bHQuZ2V0KCJzdGF0dXMiKSA9PSAic3VjY2VzcyI6CiAgICAgICAgc2Vzc2lvbi5hY2NvdW50X2lkID0gcmVzdWx0LmdldCgiYWNjb3VudF9pZCIsICIiKQogICAgICAgIHNlc3Npb24uYXBpX2tleSAgICA9IHJlc3VsdC5nZXQoImFwaV9rZXkiLCAiIikKICAgICAgICBzZXNzaW9uLnVzZXJuYW1lICAgPSBpZGVudGlmaWVyCiAgICAgICAgc2Vzc2lvbi5jcmVkaXRzICAgID0gcmVzdWx0LmdldCgiY3JlZGl0cyIsIDApCiAgICAgICAgc2Vzc2lvbi5wbGFuICAgICAgID0gcmVzdWx0LmdldCgicGxhbiIsICJOb25lIikKICAgICAgICBzZXNzaW9uLnNhdmUoKQoKICAgICAgICBvaygiTG9naW4gc3VjY2Vzc2Z1bCEiKQogICAgICAgIHByaW50KCkKICAgICAgICBmaWVsZCgiQWNjb3VudCBJRCIsIHNlc3Npb24uYWNjb3VudF9pZCkKICAgICAgICBmaWVsZCgiQ3JlZGl0cyIsICAgIHN0cihzZXNzaW9uLmNyZWRpdHMpKQogICAgICAgIGZpZWxkKCJQbGFuIiwgICAgICAgc2Vzc2lvbi5wbGFuKQogICAgICAgIHJldHVybiBUcnVlCiAgICBlbHNlOgogICAgICAgIGVycihyZXN1bHQuZ2V0KCJtZXNzYWdlIiwgIkxvZ2luIGZhaWxlZC4iKSkKICAgICAgICBtc2cgPSByZXN1bHQuZ2V0KCJtZXNzYWdlIiwgIiIpLmxvd2VyKCkKICAgICAgICBpZiAibm90IGZvdW5kIiBpbiBtc2c6CiAgICAgICAgICAgIHdhcm4oIkFjY291bnQgSUQgb3IgdXNlcm5hbWUgbm90IGZvdW5kLiBDaGVjayBhbmQgdHJ5IGFnYWluLiIpCiAgICAgICAgZWxpZiAiaW5jb3JyZWN0IiBpbiBtc2cgb3IgInBhc3N3b3JkIiBpbiBtc2c6CiAgICAgICAgICAgIHdhcm4oIldyb25nIHBhc3N3b3JkLiBDb250YWN0IEBkYXJrYm94ZXNBZG1pbiBpZiB5b3UgZm9yZ290IGl0LiIpCiAgICAgICAgZWxpZiAiYmFubmVkIiBpbiBtc2c6CiAgICAgICAgICAgIHdhcm4oIkFjY291bnQgaXMgYmFubmVkLiBDb250YWN0IEBkYXJrYm94ZXNBZG1pbiB0byBhcHBlYWwuIikKICAgICAgICByZXR1cm4gRmFsc2UKCgpkZWYgZmxvd19sb2dvdXQoKToKICAgICIiIkxvZyBvdXQgYW5kIGNsZWFyIHNhdmVkIHNlc3Npb24uIiIiCiAgICBpZiBub3Qgc2Vzc2lvbi5pc192YWxpZDoKICAgICAgICB3YXJuKCJZb3UgYXJlIG5vdCBsb2dnZWQgaW4uIikKICAgICAgICByZXR1cm4KICAgIHNlc3Npb24uY2xlYXIoKQogICAgb2soIkxvZ2dlZCBvdXQuIFNlc3Npb24gY2xlYXJlZC4iKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgU0VBUkNIIEZMT1dTCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgpTRUFSQ0hfQ0FUQUxPRyA9IFsKICAgICMgKGtleSwgZGlzcGxheV9uYW1lLCBoaW50LCBleGFtcGxlKQogICAgKCJwaG9uZSIsICAgICJQaG9uZSBJbnRlbGxpZ2VuY2UiLCAgICAgICAgIjEwLTE1IGRpZ2l0IG1vYmlsZSBudW1iZXIiLCAiOTg3NjU0MzIxMCIpLAogICAgKCJmYW1pbHkiLCAgICJGYW1pbHkgTmV0d29yayIsICAgICAgICAgICAgIjEyLWRpZ2l0IEFhZGhhciBudW1iZXIiLCAiMTIzNDU2Nzg5MDEyIiksCiAgICAoImFhZGhhciIsICAgIkFhZGhhciBDb21wcmVoZW5zaXZlIiwgICAgICAiMTItZGlnaXQgQWFkaGFyIG51bWJlciIsICIxMjM0NTY3ODkwMTIiKSwKICAgICgidmVoaWNsZSIsICAiVmVoaWNsZSBJbnRlbGxpZ2VuY2UiLCAgICAgICJWZWhpY2xlIG51bWJlciAoZS5nLiBVUDUzQ1ozMzkxKSIsICJVUDUzQ1ozMzkxIiksCiAgICAoInRlbGVncmFtIiwgIlRlbGVncmFtIEludGVsbGlnZW5jZSIsICAgICAiQHVzZXJuYW1lIG9yIHBob25lIG51bWJlciIsICJAdXNlcm5hbWUiKSwKICAgICgiaW1laSIsICAgICAiRGV2aWNlIEludGVsbGlnZW5jZSAoSU1FSSkiLCIxNS1kaWdpdCBJTUVJIG51bWJlciIsICIzNTQ2Nzg5MDEyMzQ1NjciKSwKICAgICgiZ3N0IiwgICAgICAiR1NUIEludGVsbGlnZW5jZSIsICAgICAgICAgICJHU1QgbnVtYmVyICgxNSBjaGFycykiLCAiMjdBQVBGVTA5MzlGMVpWIiksCiAgICAoImluc3RhIiwgICAgIkluc3RhZ3JhbSBJbnRlbGxpZ2VuY2UiLCAgICAiSW5zdGFncmFtIHVzZXJuYW1lIiwgInVzZXJuYW1lIiksCiAgICAoImlwIiwgICAgICAgIklQIEludGVsbGlnZW5jZSIsICAgICAgICAgICAiSVB2NCBvciBJUHY2IGFkZHJlc3MiLCAiMS4yLjMuNCIpLAogICAgKCJpZnNjIiwgICAgICJJRlNDIENvZGUgTG9va3VwIiwgICAgICAgICAgIjExLWNoYXIgSUZTQyBjb2RlIiwgIlNCSU4wMDAxMjM0IiksCiAgICAoImVtYWlsIiwgICAgIkVtYWlsIEludGVsbGlnZW5jZSIsICAgICAgICAiRW1haWwgYWRkcmVzcyIsICJ1c2VyQGV4YW1wbGUuY29tIiksCiAgICAoInVwaSIsICAgICAgIlVQSSBJbnRlbGxpZ2VuY2UiLCAgICAgICAgICAiVVBJIElEIiwgInVzZXJAdXBpIiksCiAgICAoInBhayIsICAgICAgIlBha2lzdGFuIERCIiwgICAgICAgICAgICAgICAiTmFtZSAvIHBob25lIC8gTklDIG51bWJlciIsICJxdWVyeSIpLAogICAgKCJsZWFrIiwgICAgICJBZHZhbmNlZCBPU0lOVCAvIExlYWsiLCAgICAgIkFueSBxdWVyeSDigJQgbmFtZSwgcGhvbmUsIGVtYWlsLCBldGMuIiwgInF1ZXJ5IiksCl0KCgpkZWYgX3JlcXVpcmVfbG9naW4oKSAtPiBib29sOgogICAgaWYgbm90IHNlc3Npb24uaXNfdmFsaWQ6CiAgICAgICAgd2FybigiWW91IGFyZSBub3QgbG9nZ2VkIGluLiBDaG9vc2Ugb3B0aW9uIDIgdG8gbG9nIGluIGZpcnN0LiIpCiAgICAgICAgcmV0dXJuIEZhbHNlCiAgICByZXR1cm4gVHJ1ZQoKCmRlZiBmbG93X3NpbmdsZV9zZWFyY2goa2V5OiBzdHIsIG5hbWU6IHN0ciwgaGludDogc3RyLCBleGFtcGxlOiBzdHIpOgogICAgIiIiUGVyZm9ybSBhIHNpbmdsZSB0YXJnZXRlZCBzZWFyY2guIiIiCiAgICBpZiBub3QgX3JlcXVpcmVfbG9naW4oKToKICAgICAgICByZXR1cm4KCiAgICBzZWN0aW9uKGYie25hbWV9IikKICAgIGluZm8oZiJJbnB1dCA6IHtoaW50fSIpCiAgICBpbmZvKGYiRXhhbXBsZToge2V4YW1wbGV9IikKCiAgICBxdWVyeSA9IHByb21wdChmIkVudGVyIHF1ZXJ5ICh7aGludH0pIikKICAgIGlmIG5vdCBxdWVyeToKICAgICAgICB3YXJuKCJDYW5jZWxsZWQuIikKICAgICAgICByZXR1cm4KCiAgICBsb2FkaW5nKGYiUXVlcnlpbmcge25hbWV9Li4uIikKICAgIHJlc3VsdCA9IGFwaS5zZWFyY2goa2V5LCBxdWVyeSkKICAgIGNsZWFyX2xvYWRpbmcoKQogICAgZGlzcGxheV9yZXN1bHQocmVzdWx0LCBrZXksIHF1ZXJ5KQogICAgIyBSZWZyZXNoIGNyZWRpdHMgaW4gc3RhdHVzIGJhciBhZnRlciBlYWNoIHNlYXJjaAogICAgaWYgcmVzdWx0LmdldCgic3RhdHVzIikgPT0gInN1Y2Nlc3MiOgogICAgICAgIHRyeToKICAgICAgICAgICAgX2JyID0gYXBpLmJhbGFuY2UoKQogICAgICAgICAgICBpZiBfYnIuZ2V0KCJzdGF0dXMiKSA9PSAic3VjY2VzcyI6CiAgICAgICAgICAgICAgICBfYmQgPSBfYnIuZ2V0KCJkYXRhIiwge30pCiAgICAgICAgICAgICAgICBzZXNzaW9uLmNyZWRpdHMgPSBfYmQuZ2V0KCJjcmVkaXRzIiwgc2Vzc2lvbi5jcmVkaXRzKQogICAgICAgICAgICAgICAgc2Vzc2lvbi5wbGFuICAgID0gX2JkLmdldCgicGxhbiIsIHNlc3Npb24ucGxhbikKICAgICAgICAgICAgICAgIHNlc3Npb24uc2F2ZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKCmRlZiBmbG93X2JhdGNoX3NlYXJjaCgpOgogICAgIiIiU3VibWl0IG11bHRpcGxlIHNlYXJjaGVzIGF0IG9uY2UuIiIiCiAgICBpZiBub3QgX3JlcXVpcmVfbG9naW4oKToKICAgICAgICByZXR1cm4KCiAgICBzZWN0aW9uKCJCQVRDSCBTRUFSQ0giKQogICAgaW5mbygiRW50ZXIgc2VhcmNoZXMgaW4gZm9ybWF0OiAgdHlwZTpxdWVyeSIpCiAgICBpbmZvKCJBdmFpbGFibGUgdHlwZXM6IHBob25lLCBmYW1pbHksIGFhZGhhciwgdmVoaWNsZSwgZW1haWwsIGltZWksIGdzdCwgZXRjLiIpCiAgICBpbmZvKCJQcmVzcyBFbnRlciBvbiBhbiBlbXB0eSBsaW5lIHdoZW4gZG9uZS5cbiIpCgogICAgc2VhcmNoZXMgPSBbXQogICAgd2hpbGUgVHJ1ZToKICAgICAgICBpZiBOQVJST1c6CiAgICAgICAgICAgIHByaW50KGYiICB7Qy5DWU59W3tsZW4oc2VhcmNoZXMpKzF9XSB0eXBlOnF1ZXJ5e0MuUn0iKQogICAgICAgICAgICBsaW5lID0gaW5wdXQoZiIgIHtDLllMV33ihpIgIHtDLlJ9Iikuc3RyaXAoKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGxpbmUgPSBpbnB1dChmIiAge0MuQ1lOfVt7bGVuKHNlYXJjaGVzKSsxfV0gIHtDLllMV30iKS5zdHJpcCgpCiAgICAgICAgICAgIHByaW50KEMuUiwgZW5kPSIiKQoKICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAgICAgaWYgc2VhcmNoZXM6CiAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgd2FybigiRW50ZXIgYXQgbGVhc3Qgb25lIHNlYXJjaCwgb3IgQ3RybCtDIHRvIGNhbmNlbC4iKQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgaWYgIjoiIG5vdCBpbiBsaW5lOgogICAgICAgICAgICB3YXJuKCJGb3JtYXQgbXVzdCBiZSAgdHlwZTpxdWVyeSAgKGUuZy4gcGhvbmU6OTg3NjU0MzIxMCkiKQogICAgICAgICAgICBjb250aW51ZQoKICAgICAgICBzdHlwZSwgc3F1ZXJ5ID0gbGluZS5zcGxpdCgiOiIsIDEpCiAgICAgICAgc3R5cGUgID0gc3R5cGUuc3RyaXAoKS5sb3dlcigpCiAgICAgICAgc3F1ZXJ5ID0gc3F1ZXJ5LnN0cmlwKCkKCiAgICAgICAgaWYgbm90IHN0eXBlIG9yIG5vdCBzcXVlcnk6CiAgICAgICAgICAgIHdhcm4oIkJvdGggdHlwZSBhbmQgcXVlcnkgYXJlIHJlcXVpcmVkLiIpCiAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIHNlYXJjaGVzLmFwcGVuZCh7InR5cGUiOiBzdHlwZSwgInF1ZXJ5Ijogc3F1ZXJ5fSkKICAgICAgICBvayhmIkFkZGVkOiB7c3R5cGV9IOKGkiB7c3F1ZXJ5fSIpCgogICAgaWYgbm90IHNlYXJjaGVzOgogICAgICAgIHdhcm4oIk5vIHNlYXJjaGVzIGFkZGVkLiIpCiAgICAgICAgcmV0dXJuCgogICAgbG9hZGluZyhmIlN1Ym1pdHRpbmcge2xlbihzZWFyY2hlcyl9IHNlYXJjaGVzLi4uIikKICAgIHJlc3VsdCA9IGFwaS5iYXRjaF9zZWFyY2goc2VhcmNoZXMpCiAgICBjbGVhcl9sb2FkaW5nKCkKCiAgICBpZiByZXN1bHQuZ2V0KCJzdGF0dXMiKSA9PSAic3VjY2VzcyI6CiAgICAgICAgb2soZiJCYXRjaCBzZWFyY2ggY29tcGxldGUg4oCUIHtsZW4oc2VhcmNoZXMpfSBxdWVyaWVzIHByb2Nlc3NlZC4iKQogICAgICAgIHJlc3VsdHNfZGF0YSA9IHJlc3VsdC5nZXQoImRhdGEiLCB7fSkuZ2V0KCJyZXN1bHRzIiwgW10pCiAgICAgICAgZm9yIGksIHJlcyBpbiBlbnVtZXJhdGUocmVzdWx0c19kYXRhLCAxKToKICAgICAgICAgICAgc3Vic2VjdGlvbihmIlJlc3VsdCB7aX0gLyB7bGVuKHJlc3VsdHNfZGF0YSl9IikKICAgICAgICAgICAgZGlzcGxheV9yZXN1bHQoeyJzdGF0dXMiOiAic3VjY2VzcyIsICJkYXRhIjogcmVzfSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgcmVzLmdldCgidHlwZSIsICIiKSwgcmVzLmdldCgicXVlcnkiLCAiIikpCiAgICBlbHNlOgogICAgICAgIGVycihyZXN1bHQuZ2V0KCJtZXNzYWdlIiwgIkJhdGNoIHNlYXJjaCBmYWlsZWQuIikpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBBQ0NPVU5UICYgVVRJTElUWSBGTE9XUwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKZGVmIGZsb3dfY2hlY2tfYmFsYW5jZSgpOgogICAgIiIiU2hvdyBjcmVkaXRzIGFuZCBwbGFuIGluZm8uIiIiCiAgICBpZiBub3QgX3JlcXVpcmVfbG9naW4oKToKICAgICAgICByZXR1cm4KICAgIHNlY3Rpb24oIkFDQ09VTlQgQkFMQU5DRSIpCiAgICBsb2FkaW5nKCJGZXRjaGluZyBiYWxhbmNlLi4uIikKICAgIHJlc3VsdCA9IGFwaS5iYWxhbmNlKCkKICAgIGNsZWFyX2xvYWRpbmcoKQogICAgaWYgcmVzdWx0LmdldCgic3RhdHVzIikgPT0gInN1Y2Nlc3MiOgogICAgICAgIGQgPSByZXN1bHQuZ2V0KCJkYXRhIiwge30pCiAgICAgICAgb2soIkJhbGFuY2UgcmV0cmlldmVkLiIpCiAgICAgICAgcHJpbnQoKQogICAgICAgIGZpZWxkKCJBY2NvdW50IElEIiwgICAgc2Vzc2lvbi5hY2NvdW50X2lkKQogICAgICAgIGZpZWxkKCJDcmVkaXRzIiwgICAgICAgc3RyKGQuZ2V0KCJjcmVkaXRzIiwgc2Vzc2lvbi5jcmVkaXRzKSkpCiAgICAgICAgcGxhbiA9IGQuZ2V0KCJwbGFuIiwgc2Vzc2lvbi5wbGFuKSBvciAiTm9uZSIKICAgICAgICBmaWVsZCgiUGxhbiIsICAgICAgICAgIHBsYW4pCiAgICAgICAgaWYgcGxhbiBhbmQgcGxhbiAhPSAiTm9uZSI6CiAgICAgICAgICAgIGZpZWxkKCJWYWxpZCBVbnRpbCIsICAgZC5nZXQoInZhbGlkX3VudGlsIiwgIuKAlCIpKQogICAgICAgICAgICBpZiBkLmdldCgiZGFpbHlfbGltaXQiLCAwKSA+IDA6CiAgICAgICAgICAgICAgICBmaWVsZCgiRGFpbHkgVXNlZCIsICAgIGYie2QuZ2V0KCdkYWlseV91c2VkJywwKX0gLyB7ZC5nZXQoJ2RhaWx5X2xpbWl0JywwKX0iKQogICAgICAgIGZpZWxkKCJUb3RhbCBTZWFyY2hlcyIsIHN0cihkLmdldCgidG90YWxfc2VhcmNoZXMiLCAwKSkpCiAgICAgICAgIyBVcGRhdGUgc2Vzc2lvbgogICAgICAgIHNlc3Npb24uY3JlZGl0cyA9IGQuZ2V0KCJjcmVkaXRzIiwgc2Vzc2lvbi5jcmVkaXRzKQogICAgICAgIHNlc3Npb24ucGxhbiAgICA9IGQuZ2V0KCJwbGFuIiwgc2Vzc2lvbi5wbGFuKQogICAgICAgIHNlc3Npb24uc2F2ZSgpCiAgICBlbHNlOgogICAgICAgIGVycihyZXN1bHQuZ2V0KCJtZXNzYWdlIiwgIkNvdWxkIG5vdCBmZXRjaCBiYWxhbmNlLiIpKQogICAgICAgIHdhcm4oIlRpcDogVXNlIG9wdGlvbiAyMCB0byBidXkgY3JlZGl0cyBpZiBiYWxhbmNlIGlzIDAuIikKCgpkZWYgZmxvd192aWV3X3VzYWdlKCk6CiAgICAiIiJTaG93IHNlYXJjaCB1c2FnZSBzdGF0cy4iIiIKICAgIGlmIG5vdCBfcmVxdWlyZV9sb2dpbigpOgogICAgICAgIHJldHVybgogICAgc2VjdGlvbigiVVNBR0UgU1RBVElTVElDUyIpCiAgICBsb2FkaW5nKCJGZXRjaGluZyB1c2FnZS4uLiIpCiAgICByZXN1bHQgPSBhcGkudXNhZ2UoKQogICAgY2xlYXJfbG9hZGluZygpCiAgICBpZiByZXN1bHQuZ2V0KCJzdGF0dXMiKSA9PSAic3VjY2VzcyI6CiAgICAgICAgZCA9IHJlc3VsdC5nZXQoImRhdGEiLCB7fSkKICAgICAgICBvaygiVXNhZ2UgcmV0cmlldmVkLiIpCiAgICAgICAgZmllbGQoIlRvdGFsIFNlYXJjaGVzIiwgICBzdHIoZC5nZXQoInRvdGFsX3NlYXJjaGVzIiwgMCkpKQogICAgICAgIGZpZWxkKCJUb2RheSdzIFNlYXJjaGVzIiwgc3RyKGQuZ2V0KCJ0b2RheV9zZWFyY2hlcyIsIDApKSkKICAgICAgICBmaWVsZCgiVGhpcyBNb250aCIsICAgICAgIHN0cihkLmdldCgibW9udGhfc2VhcmNoZXMiLCAwKSkpCiAgICAgICAgZmllbGQoIkxhc3QgU2VhcmNoIiwgICAgICBkLmdldCgibGFzdF9zZWFyY2giLCAiTmV2ZXIiKSkKICAgIGVsc2U6CiAgICAgICAgZXJyKHJlc3VsdC5nZXQoIm1lc3NhZ2UiLCAiQ291bGQgbm90IGZldGNoIHVzYWdlLiIpKQoKCmRlZiBmbG93X2NoZWNrX3N0YXR1cygpOgogICAgIiIiUGluZyB0aGUgQVBJIGFuZCBzaG93IHN5c3RlbSBzdGF0dXMuIiIiCiAgICBzZWN0aW9uKCJTWVNURU0gU1RBVFVTIikKICAgIGxvYWRpbmcoIlBpbmdpbmcgc2VydmVyLi4uIikKICAgIHJlc3VsdCA9IGFwaS5zdGF0dXMoKQogICAgY2xlYXJfbG9hZGluZygpCiAgICBpZiByZXN1bHQuZ2V0KCJzdGF0dXMiKSA9PSAic3VjY2VzcyI6CiAgICAgICAgZCA9IHJlc3VsdC5nZXQoImRhdGEiLCB7fSkKICAgICAgICBzdGF0ZSA9IGYie0MuR1JOfU9QRVJBVElPTkFMe0MuUn0iIGlmIGQuZ2V0KCJvbmxpbmUiLCBUcnVlKSBlbHNlIGYie0MuRVJSfURFR1JBREVEe0MuUn0iCiAgICAgICAgb2soZiJTZXJ2ZXIgaXMge3N0YXRlfSIpCiAgICAgICAgZmllbGQoIlZlcnNpb24iLCBkLmdldCgidmVyc2lvbiIsIFZFUlNJT04pKQogICAgICAgIGZpZWxkKCJVcHRpbWUiLCAgZC5nZXQoInVwdGltZSIsICLigJQiKSkKICAgIGVsc2U6CiAgICAgICAgIyBKdXN0IHNob3cgdGhhdCB3ZSBjYW4gcmVhY2ggdGhlIHNlcnZlcgogICAgICAgIHdhcm4oIlN0YXR1cyBlbmRwb2ludCByZXR1cm5lZCBhbiBlcnJvciwgYnV0IHNlcnZlciBpcyByZWFjaGFibGUuIikKCgpkZWYgZmxvd192aWV3X2RvY3MoKToKICAgICIiIkRpc3BsYXkgQVBJIGVuZHBvaW50IGRvY3VtZW50YXRpb24uIiIiCiAgICBzZWN0aW9uKCJBUEkgRE9DVU1FTlRBVElPTiIpCiAgICBsb2FkaW5nKCJMb2FkaW5nIGRvY3MuLi4iKQogICAgcmVzdWx0ID0gYXBpLmRvY3MoKQogICAgY2xlYXJfbG9hZGluZygpCiAgICBpZiByZXN1bHQ6CiAgICAgICAgZmllbGQoIlNlcnZpY2UiLCAgcmVzdWx0LmdldCgic2VydmljZSIsICJEYXJrQm94ZXMgSW50ZWxsaWdlbmNlIEFQSSIpKQogICAgICAgIGZpZWxkKCJWZXJzaW9uIiwgIHJlc3VsdC5nZXQoInZlcnNpb24iLCBWRVJTSU9OKSkKICAgICAgICBmaWVsZCgiQmFzZSBVUkwiLCByZXN1bHQuZ2V0KCJiYXNlX3VybCIsIEFQSV9CQVNFX1VSTCkpCgogICAgICAgIGVuZHBvaW50cyA9IHJlc3VsdC5nZXQoImVuZHBvaW50cyIsIHt9KQogICAgICAgIGlmIGVuZHBvaW50cy5nZXQoInNlYXJjaCIpOgogICAgICAgICAgICBzdWJzZWN0aW9uKCJTZWFyY2ggRW5kcG9pbnRzIikKICAgICAgICAgICAgZm9yIG5hbWUsIGVwIGluIGVuZHBvaW50c1sic2VhcmNoIl0uaXRlbXMoKToKICAgICAgICAgICAgICAgIHByaW50KGYiICB7Qy5CTEt94pSCe0MuUn0ge0MuQn17ZXAuZ2V0KCdtZXRob2QnLCdQT1NUJyl9e0MuUn0iCiAgICAgICAgICAgICAgICAgICAgICBmIiAge2VwLmdldCgnZW5kcG9pbnQnLCcnKX0iKQoKICAgICAgICBpZiBlbmRwb2ludHMuZ2V0KCJ1dGlsaXR5Iik6CiAgICAgICAgICAgIHN1YnNlY3Rpb24oIlV0aWxpdHkgRW5kcG9pbnRzIikKICAgICAgICAgICAgZm9yIG5hbWUsIGVwIGluIGVuZHBvaW50c1sidXRpbGl0eSJdLml0ZW1zKCk6CiAgICAgICAgICAgICAgICBwcmludChmIiAge0MuQkxLfeKUgntDLlJ9IHtDLkJ9e2VwLmdldCgnbWV0aG9kJywnR0VUJyl9e0MuUn0iCiAgICAgICAgICAgICAgICAgICAgICBmIiAge2VwLmdldCgnZW5kcG9pbnQnLCcnKX0iKQogICAgZWxzZToKICAgICAgICBpbmZvKGYiRG9jcyBhdDoge0FQSV9CQVNFX1VSTH0vYXBpL3YxL2RvY3MiKQoKCmRlZiBmbG93X2hvd190b19idXkoKToKICAgICIiIlNob3cgaG93IHRvIHB1cmNoYXNlIGNyZWRpdHMgLyBwbGFucy4iIiIKICAgIHNlY3Rpb24oIkhPVyBUTyBCVVkgQ1JFRElUUyAvIFBMQU5TIikKICAgIHByaW50KGYiIiIKICB7Qy5ZTFd94pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBe0MuUn0KCiAge0MuQn1PUFRJT04gMTogVmlhIFRlbGVncmFtIEJvdHtDLlJ9CiAge0MuQkxLfeKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgHtDLlJ9CiAgMS4gT3BlbiBUZWxlZ3JhbSBhbmQgZmluZCBvdXIgYm90LgogIDIuIFRhcCB7Qy5DWU598J+SjiBQcmVtaXVtIFBsYW5ze0MuUn0gaW4gdGhlIG1lbnUuCiAgMy4gU2VsZWN0IGEgcGxhbiBhbmQgcGF5IHZpYSBVUEkuCiAgNC4gRW50ZXIgeW91ciBVVFIgLyBUcmFuc2FjdGlvbiBOdW1iZXIgd2hlbiBwcm9tcHRlZC4KICA1LiBBZG1pbiB2ZXJpZmllcyBtYW51YWxseSDigJQgYWN0aXZhdGVkIHdpdGhpbiA14oCTMTUgbWluLgoKICB7Qy5CfU9QVElPTiAyOiBEaXJlY3QgQ29udGFjdHtDLlJ9CiAge0MuQkxLfeKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgHtDLlJ9CiAg4oCiIFRlbGVncmFtIDoge0MuQ1lOfUBkYXJrYm94ZXNBZG1pbntDLlJ9CiAg4oCiIEVtYWlsICAgIDoge0MuQ1lOfXlhZGlpZnlAZ21haWwuY29te0MuUn0KICDigKIgUHJvdmlkZSAgOiBZb3VyIEFjY291bnQgSUQgKHtDLllMV317c2Vzc2lvbi5hY2NvdW50X2lkIG9yICdzZWUgb3B0aW9uIDExJ317Qy5SfSkKCiAge0MuQn1VUEkgRGV0YWlsc3tDLlJ9CiAge0MuQkxLfeKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgHtDLlJ9CiAg4oCiIFVQSSBJRCA6IHtDLkdSTn1kYXJrYm94ZXNAeWJse0MuUn0KCiAge0MuQn1QbGFucyBBdmFpbGFibGV7Qy5SfQogIHtDLkJMS33ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIB7Qy5SfQogIOKaoSBTdGFydGVyIFBhY2sgICAgICA1IHNlYXJjaGVzICAgICDigrkxMDAKICDwn5SNIEV4cGxvcmVyIFBhY2sgICAgMTUgc2VhcmNoZXMgICAgIOKCuTI1MAogIPCfmoAgRGFpbHkgMTAvMzBkICAgICAxMC9kYXnCtzMwIGRheXMgIOKCuTgwMAogIPCfko4gRGFpbHkgMjAvMzBkICAgICAyMC9kYXnCtzMwIGRheXMgIOKCuTEwMDAKICDwn4yfIERhaWx5IDEwLzYwZCAgICAgMTAvZGF5wrcyIG1vbnRocyDigrkxNTAwCiAg8J+RkSBEYWlseSAyMC82MGQgICAgIDIwL2RhecK3MiBtb250aHMg4oK5MTgwMAoKICB7Qy5ZTFd94pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBe0MuUn0KICAiIiIpCgoKZGVmIGZsb3dfYnV5X2NyZWRpdHMoKToKICAgICIiIkludGVyYWN0aXZlIGJ1eSBmbG93OiBzaG93IHBsYW5zIOKGkiB1c2VyIHBpY2tzIOKGkiBwYXlzIFVQSSDihpIgc3VibWl0cyBVVFIuIiIiCiAgICBpZiBub3QgX3JlcXVpcmVfbG9naW4oKToKICAgICAgICByZXR1cm4KICAgIHNlY3Rpb24oIkJVWSBDUkVESVRTIC8gUExBTlMiKQoKICAgIFBMQU5TID0gWwogICAgICAgICgiY3JlZGl0c181IiwgICLimqEgU3RhcnRlciBQYWNrIiwgICAgIjUgc2VhcmNoZXMiLCAgICAgICAgICAi4oK5MTAwIiksCiAgICAgICAgKCJjcmVkaXRzXzE1IiwgIvCflI0gRXhwbG9yZXIgUGFjayIsICAgIjE1IHNlYXJjaGVzIiwgICAgICAgICAi4oK5MjUwIiksCiAgICAgICAgKCJkYWlseTEwXzMwIiwgIvCfmoAgRGFpbHkgMTAvMzBkIiwgICAgIjEwL2RheSDCtyAzMCBkYXlzIiwgICAgIuKCuTgwMCIpLAogICAgICAgICgiZGFpbHkyMF8zMCIsICLwn5KOIERhaWx5IDIwLzMwZCIsICAgICIyMC9kYXkgwrcgMzAgZGF5cyIsICAgICLigrkxMDAwIiksCiAgICAgICAgKCJkYWlseTEwXzYwIiwgIvCfjJ8gRGFpbHkgMTAvNjBkIiwgICAgIjEwL2RheSDCtyAyIG1vbnRocyIsICAgIuKCuTE1MDAiKSwKICAgICAgICAoImRhaWx5MjBfNjAiLCAi8J+RkSBEYWlseSAyMC82MGQiLCAgICAiMjAvZGF5IMK3IDIgbW9udGhzIiwgICAi4oK5MTgwMCIpLAogICAgXQoKICAgIHcgPSBtaW4oVEVSTV9XSURUSCwgNjApCiAgICBwcmludChmIiAge0MuQkxLfXsn4pSAJyp3fXtDLlJ9IikKICAgIHByaW50KGYiICB7Qy5CfUF2YWlsYWJsZSBQbGFuc3tDLlJ9IikKICAgIHByaW50KGYiICB7Qy5CTEt9eyfilIAnKnd9e0MuUn0iKQogICAgZm9yIGksIChrZXksIG5hbWUsIGRlc2MsIHByaWNlKSBpbiBlbnVtZXJhdGUoUExBTlMsIDEpOgogICAgICAgIGlmIE5BUlJPVzoKICAgICAgICAgICAgcHJpbnQoZiIgIHtDLllMV31be2l9XXtDLlJ9IikKICAgICAgICAgICAgcHJpbnQoZiIgICAgICB7bmFtZX0gIHtDLkJMS317ZGVzY317Qy5SfSAge0MuR1JOfXtwcmljZX17Qy5SfSIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgcHJpbnQoZiIgIHtDLllMV31be2l9XXtDLlJ9ICB7bmFtZTo8MjJ9IHtDLkJMS317ZGVzYzo8MjJ9e0MuUn0gIHtDLkdSTn17cHJpY2V9e0MuUn0iKQogICAgcHJpbnQoZiIgIHtDLllMV31bMF17Qy5SfSAgQ2FuY2VsIikKICAgIHByaW50KGYiICB7Qy5CTEt9eyfilIAnKnd9e0MuUn1cbiIpCgogICAgY2hvaWNlX3AgPSBwcm9tcHQoIlNlbGVjdCBwbGFuIG51bWJlciIpCiAgICBpZiBub3QgY2hvaWNlX3Agb3IgY2hvaWNlX3AgPT0gIjAiOgogICAgICAgIHdhcm4oIkNhbmNlbGxlZC4iKQogICAgICAgIHJldHVybgoKICAgIHRyeToKICAgICAgICBpZHggPSBpbnQoY2hvaWNlX3ApIC0gMQogICAgICAgIGlmIGlkeCA8IDAgb3IgaWR4ID49IGxlbihQTEFOUyk6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IKICAgIGV4Y2VwdCBWYWx1ZUVycm9yOgogICAgICAgIHdhcm4oIkludmFsaWQgc2VsZWN0aW9uLiIpCiAgICAgICAgcmV0dXJuCgogICAgcGxhbl9rZXksIHBsYW5fbmFtZSwgcGxhbl9kZXNjLCBwbGFuX3ByaWNlID0gUExBTlNbaWR4XQoKICAgIHByaW50KCkKICAgIHByaW50KGYiICB7Qy5CfVBheW1lbnQgSW5zdHJ1Y3Rpb25ze0MuUn0iKQogICAgcHJpbnQoZiIgIHtDLkJMS317J+KUgCcqd317Qy5SfSIpCiAgICBwcmludChmIiAgUGxhbiAgICAgOiB7cGxhbl9uYW1lfSAgKHtwbGFuX2Rlc2N9KSIpCiAgICBwcmludChmIiAgQW1vdW50ICAgOiB7Qy5HUk59e3BsYW5fcHJpY2V9e0MuUn0iKQogICAgcHJpbnQoZiIgIFVQSSBJRCAgIDoge0MuQ1lOfWRhcmtib3hlc0B5Ymx7Qy5SfSIpCiAgICBwcmludChmIiAge0MuQkxLfXsn4pSAJyp3fXtDLlJ9IikKICAgIHByaW50KGYiICB7Qy5ZTFd9MS4gT3BlbiBhbnkgVVBJIGFwcCAoR1BheSwgUGhvbmVQZSwgUGF5dG0sIGV0Yy4pe0MuUn0iKQogICAgcHJpbnQoZiIgIHtDLllMV30yLiBQYXkge3BsYW5fcHJpY2V9IHRvICBkYXJrYm94ZXNAeWJse0MuUn0iKQogICAgcHJpbnQoZiIgIHtDLllMV30zLiBOb3RlIHRoZSAxMi1kaWdpdCBVVFIgLyBUcmFuc2FjdGlvbiBJRHtDLlJ9IikKICAgIHByaW50KGYiICB7Qy5ZTFd9NC4gRW50ZXIgaXQgYmVsb3cg4oCUIGFkbWluIHdpbGwgYWN0aXZhdGUgd2l0aGluIDXigJMxNSBtaW57Qy5SfSIpCiAgICBwcmludCgpCgogICAgdXRyID0gcHJvbXB0KCJFbnRlciBVVFIgLyBUcmFuc2FjdGlvbiBJRCAob3IgMCB0byBjYW5jZWwpIikKICAgIGlmIG5vdCB1dHIgb3IgdXRyID09ICIwIjoKICAgICAgICB3YXJuKCJDYW5jZWxsZWQuIikKICAgICAgICByZXR1cm4KICAgIGlmIGxlbih1dHIpIDwgNjoKICAgICAgICB3YXJuKCJVVFIgdG9vIHNob3J0LiBQbGVhc2UgZW50ZXIgdGhlIGZ1bGwgdHJhbnNhY3Rpb24gSUQuIikKICAgICAgICByZXR1cm4KCiAgICBsb2FkaW5nKCJTdWJtaXR0aW5nIHBheW1lbnQuLi4iKQogICAgcmVzdWx0ID0gYXBpLnN1Ym1pdF91dHIodXRyLCBwbGFuX2tleSkKICAgIGNsZWFyX2xvYWRpbmcoKQoKICAgIGlmIHJlc3VsdC5nZXQoInN0YXR1cyIpID09ICJzdWNjZXNzIjoKICAgICAgICBvaygiUGF5bWVudCBzdWJtaXR0ZWQgc3VjY2Vzc2Z1bGx5ISIpCiAgICAgICAgcHJpbnQoKQogICAgICAgIGZpZWxkKCJQbGFuIiwgICByZXN1bHQuZ2V0KCJwbGFuIiwgcGxhbl9uYW1lKSkKICAgICAgICBmaWVsZCgiVVRSIiwgICAgdXRyKQogICAgICAgIGZpZWxkKCJTdGF0dXMiLCAiUGVuZGluZyBhZG1pbiBhcHByb3ZhbCIpCiAgICAgICAgcHJpbnQoKQogICAgICAgIGluZm8oIllvdSB3aWxsIGJlIG5vdGlmaWVkIG9uIFRlbGVncmFtIG9uY2UgYWN0aXZhdGVkICg14oCTMTUgbWluKS4iKQogICAgICAgIGluZm8oIklmIG5vdCBhY3RpdmF0ZWQgaW4gMzAgbWluLCBjb250YWN0IEBkYXJrYm94ZXNBZG1pbiB3aXRoIHlvdXIgVVRSLiIpCiAgICBlbHNlOgogICAgICAgIGVycihyZXN1bHQuZ2V0KCJtZXNzYWdlIiwgIlN1Ym1pc3Npb24gZmFpbGVkLiIpKQogICAgICAgIHdhcm4oIklmIHBheW1lbnQgd2FzIG1hZGUsIGNvbnRhY3QgQGRhcmtib3hlc0FkbWluIHdpdGggeW91ciBVVFIgYW5kIEFjY291bnQgSUQuIikKICAgICAgICBmaWVsZCgiQWNjb3VudCBJRCIsIHNlc3Npb24uYWNjb3VudF9pZCkKICAgICAgICBmaWVsZCgiVVRSIiwgICAgICAgIHV0cikKCgpkZWYgZmxvd19zdXBwb3J0KCk6CiAgICAiIiJTaG93IHN1cHBvcnQgY29udGFjdCBpbmZvcm1hdGlvbi4iIiIKICAgIHNlY3Rpb24oIlNVUFBPUlQgJiBDT05UQUNUIikKICAgIHByaW50KGYiIiIKICB7Qy5HUk59REFSS0JPWEVTIElOVEVMTElHRU5DRSBTWVNURU17Qy5SfQogIHtDLkJMS317RlVMTF9OQU1FfXtDLlJ9CgogIHtDLkJ9Q29udGFjdCBVc3tDLlJ9CiAge0MuQkxLfeKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgHtDLlJ9CiAgVGVsZWdyYW0gIDoge0MuQ1lOfXtTVVBQT1JUX1RHfXtDLlJ9CiAgRW1haWwgICAgIDoge0MuQ1lOfXtTVVBQT1JUX0VNQUlMfXtDLlJ9CiAgQ2hhbm5lbCAgIDoge0MuQ1lOfXtDSEFOTkVMfXtDLlJ9CgogIHtDLkJ9UmVzcG9uc2UgVGltZXN7Qy5SfQogIHtDLkJMS33ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIB7Qy5SfQogIEdlbmVyYWwgICA6IHdpdGhpbiAxIGhvdXIKICBVcmdlbnQgICAgOiAxNeKAkzMwIG1pbnV0ZXMKICBQYXltZW50ICAgOiA14oCTMTUgbWludXRlcwoKICB7Qy5CfUNvbW1vbiBJc3N1ZXN7Qy5SfQogIHtDLkJMS33ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIB7Qy5SfQogIOKAoiBGb3Jnb3QgcGFzc3dvcmQgIOKGkiBDb250YWN0IHtTVVBQT1JUX1RHfQogIOKAoiBQYXltZW50IG5vdCBkb25lIOKGkiBTaGFyZSBVVFIgd2l0aCBhZG1pbgogIOKAoiBTZWFyY2ggZmFpbGVkICAgIOKGkiBDaGVjayBjcmVkaXRzIChvcHQgMjApCiAg4oCiIEFjY291bnQgYmFubmVkICAg4oaSIEVtYWlsIHtTVVBQT1JUX0VNQUlMfQoKICB7Qy5ZTFd9TmV2ZXIgc2hhcmUgeW91ciBwYXNzd29yZCB3aXRoIGFueW9uZS57Qy5SfQogIHtDLllMV31PZmZpY2lhbCBhZG1pbiBvbmx5OiB7U1VQUE9SVF9UR317Qy5SfQogICAgIiIiKQoKCmRlZiBmbG93X3ZpZXdfc2F2ZWQoKToKICAgICIiIkxpc3Qgc2F2ZWQgcmVzdWx0IGZpbGVzLiIiIgogICAgc2VjdGlvbigiU0FWRUQgUkVTVUxUUyIpCiAgICBpZiBub3Qgb3MucGF0aC5leGlzdHMoUkVTVUxUU19ESVIpOgogICAgICAgIGluZm8oIk5vIHJlc3VsdHMgc2F2ZWQgeWV0LiIpCiAgICAgICAgcmV0dXJuCiAgICBmaWxlcyA9IHNvcnRlZChvcy5saXN0ZGlyKFJFU1VMVFNfRElSKSwgcmV2ZXJzZT1UcnVlKQogICAgaWYgbm90IGZpbGVzOgogICAgICAgIGluZm8oIk5vIHJlc3VsdHMgc2F2ZWQgeWV0LiIpCiAgICAgICAgcmV0dXJuCiAgICBvayhmIntsZW4oZmlsZXMpfSBzYXZlZCByZXN1bHQocykgaW4ge1JFU1VMVFNfRElSfSIpCiAgICBmb3IgaSwgZiBpbiBlbnVtZXJhdGUoZmlsZXNbOjIwXSwgMSk6CiAgICAgICAgcHJpbnQoZiIgIHtDLkJMS317aTo+Mn0ue0MuUn0ge2Z9IikKICAgIGlmIGxlbihmaWxlcykgPiAyMDoKICAgICAgICBpbmZvKGYiLi4uIGFuZCB7bGVuKGZpbGVzKS0yMH0gbW9yZS4iKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTUFJTiBNRU5VCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgpkZWYgX3N0YXR1c19iYXIoKSAtPiBzdHI6CiAgICAiIiJPbmUtbGluZSBzdGF0dXMgZm9yIHRoZSBwcm9tcHQgYXJlYS4iIiIKICAgIGlmIHNlc3Npb24uaXNfdmFsaWQ6CiAgICAgICAgcmV0dXJuIChmIiAge0MuQkxLfUFjY291bnQ6IHtDLkNZTn17c2Vzc2lvbi5hY2NvdW50X2lkfXtDLlJ9IgogICAgICAgICAgICAgICAgZiIgIHtDLkJMS31DcmVkaXRzOiB7Qy5HUk59e3Nlc3Npb24uY3JlZGl0c317Qy5SfSIKICAgICAgICAgICAgICAgIGYiICB7Qy5CTEt9UGxhbjoge0MuWUxXfXtzZXNzaW9uLnBsYW59e0MuUn0iKQogICAgZWxzZToKICAgICAgICByZXR1cm4gZiIgIHtDLldSTn1Ob3QgbG9nZ2VkIGlue0MuUn0iCgoKZGVmIGRpc3BsYXlfYXV0aF9tZW51KCk6CiAgICAiIiJQcmludCBhdXRoZW50aWNhdGlvbi1vbmx5IG1lbnUgc2hvd24gd2hlbiBub3QgbG9nZ2VkIGluLiIiIgogICAgdyA9IG1pbihURVJNX1dJRFRILCA3MCkKICAgIHByaW50KCkKICAgIHByaW50KGYie0MuQ1lOfXtfbGluZSgn4pSAJywgdyl9e0MuUn0iKQogICAgcHJpbnQoZiJ7Qy5DWU59e0MuQn0gIERBUktCT1hFUyBJTlRFTExJR0VOQ0Ug4oCUIFdFTENPTUV7Qy5SfSIpCiAgICBwcmludChmIntDLkNZTn17X2xpbmUoJ+KUgCcsIHcpfXtDLlJ9IikKICAgIEFVVEhfTUVOVSA9IFsKICAgICAgICAoIjEiLCAiUmVnaXN0ZXIgTmV3IEFjY291bnQgIChObyBUZWxlZ3JhbSBuZWVkZWQpIiksCiAgICAgICAgKCIyIiwgIkxvZyBJbiIpLAogICAgICAgICgiMCIsICJFeGl0IiksCiAgICBdCiAgICBmb3Igb3B0LCBsYWJlbCBpbiBBVVRIX01FTlU6CiAgICAgICAgaWYgTkFSUk9XOgogICAgICAgICAgICBwcmludChmIiAge0MuWUxXfVt7b3B0fV17Qy5SfSIpCiAgICAgICAgICAgIHByaW50KGYiICAgICAgIHtsYWJlbH0iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGNvbCA9IEMuR1JOIGlmIG9wdCA9PSAiMCIgZWxzZSBDLllMVwogICAgICAgICAgICBwcmludChmIiAge2NvbH1be29wdH1de0MuUn0gIHtsYWJlbH0iKQogICAgcHJpbnQoKQogICAgcHJpbnQoZiJ7Qy5DWU59e19saW5lKCfilIAnLCB3KX17Qy5SfSIpCiAgICBwcmludChmIiAge0MuWUxXfeKaoCAgTm90IGxvZ2dlZCBpbiDigJQgcmVnaXN0ZXIgb3IgbG9nIGluIHRvIGNvbnRpbnVle0MuUn0iKQogICAgcHJpbnQoZiJ7Qy5DWU59e19saW5lKCfilIAnLCB3KX17Qy5SfSIpCiAgICBwcmludCgpCgoKZGVmIGRpc3BsYXlfbWVudSgpOgogICAgIiIiUHJpbnQgZnVsbCBtYWluIG1lbnUgc2hvd24gb25seSB3aGVuIGxvZ2dlZCBpbi4iIiIKICAgIHcgPSBtaW4oVEVSTV9XSURUSCwgNzApCiAgICBwcmludCgpCiAgICBwcmludChmIntDLkNZTn17X2xpbmUoJ+KUgCcsIHcpfXtDLlJ9IikKICAgIHByaW50KGYie0MuQ1lOfXtDLkJ9ICBEQVJLQk9YRVMg4oCUIE1BSU4gTUVOVXtDLlJ9IikKICAgIHByaW50KGYie0MuQ1lOfXtfbGluZSgn4pSAJywgdyl9e0MuUn0iKQoKICAgIE1FTlUgPSBbCiAgICAgICAgKCIiLCAgIuKUgOKUgCBTRUFSQ0hFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAiKSwKICAgICAgICAoIjEiLCAgIvCfk7EgUGhvbmUgSW50ZWxsaWdlbmNlIiksCiAgICAgICAgKCIyIiwgICLwn5Go4oCN8J+RqeKAjfCfkafigI3wn5GmIEZhbWlseSBOZXR3b3JrIChBYWRoYXIpIiksCiAgICAgICAgKCIzIiwgICLwn4aUIEFhZGhhciBDb21wcmVoZW5zaXZlIiksCiAgICAgICAgKCI0IiwgICLwn5qXIFZlaGljbGUgSW50ZWxsaWdlbmNlIiksCiAgICAgICAgKCI1IiwgICLwn5OyIFRlbGVncmFtIEludGVsbGlnZW5jZSIpLAogICAgICAgICgiNiIsICAi8J+TsSBEZXZpY2UgSW50ZWxsaWdlbmNlIChJTUVJKSIpLAogICAgICAgICgiNyIsICAi8J+PoiBHU1QgSW50ZWxsaWdlbmNlIiksCiAgICAgICAgKCI4IiwgICLwn5O4IEluc3RhZ3JhbSBJbnRlbGxpZ2VuY2UiKSwKICAgICAgICAoIjkiLCAgIvCfjJAgSVAgSW50ZWxsaWdlbmNlIiksCiAgICAgICAgKCIxMCIsICLwn4+mIElGU0MgQ29kZSBMb29rdXAiKSwKICAgICAgICAoIjExIiwgIvCfk6cgRW1haWwgSW50ZWxsaWdlbmNlIiksCiAgICAgICAgKCIxMiIsICLwn5KzIFVQSSBJbnRlbGxpZ2VuY2UiKSwKICAgICAgICAoIjEzIiwgIvCfjI8gUGFraXN0YW4gREIiKSwKICAgICAgICAoIjE0IiwgIvCfmoAgQWR2YW5jZWQgT1NJTlQgLyBMZWFrIFNlYXJjaCIpLAogICAgICAgICgiMTUiLCAi8J+TpiBCYXRjaCBTZWFyY2ggKG11bHRpcGxlIHF1ZXJpZXMpIiksCiAgICAgICAgKCIiLCAgICIiKSwKICAgICAgICAoIiIsICAi4pSA4pSAIEFDQ09VTlQgJiBJTkZPIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgCIpLAogICAgICAgICgiMTYiLCAi8J+SsCBDaGVjayBCYWxhbmNlICYgUGxhbiIpLAogICAgICAgICgiMTciLCAi8J+TiiBWaWV3IFVzYWdlIFN0YXRpc3RpY3MiKSwKICAgICAgICAoIjE4IiwgIvCfjJAgU3lzdGVtIFN0YXR1cyIpLAogICAgICAgICgiMTkiLCAi8J+TliBBUEkgRG9jdW1lbnRhdGlvbiIpLAogICAgICAgICgiMjAiLCAi8J+SsyBCdXkgQ3JlZGl0cyAvIFBsYW5zICAoUGF5IHZpYSBVUEkpIiksCiAgICAgICAgKCIyMSIsICLwn4aYIFN1cHBvcnQgJiBDb250YWN0IiksCiAgICAgICAgKCIyMiIsICLwn5OBIFZpZXcgU2F2ZWQgUmVzdWx0cyIpLAogICAgICAgICgiIiwgICAiIiksCiAgICAgICAgKCIwIiwgICLwn5STIExvZyBPdXQgJiBFeGl0IiksCiAgICBdCgogICAgZm9yIG9wdCwgbGFiZWwgaW4gTUVOVToKICAgICAgICBpZiBub3Qgb3B0IGFuZCBub3QgbGFiZWw6CiAgICAgICAgICAgIHByaW50KCkKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiBub3Qgb3B0OgogICAgICAgICAgICBwcmludChmIiAge0MuQkxLfXtsYWJlbH17Qy5SfSIpCiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgTkFSUk9XOgogICAgICAgICAgICBwcmludChmIiAge0MuWUxXfVt7b3B0Oj4yfV17Qy5SfSIpCiAgICAgICAgICAgIHByaW50KGYiICAgICAgIHtsYWJlbH0iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGNvbCA9IEMuR1JOIGlmIG9wdCA9PSAiMCIgZWxzZSAoQy5ZTFcgaWYgb3B0ICE9ICIzIiBlbHNlICJcMDMzWzkxbSIpCiAgICAgICAgICAgIHByaW50KGYiICB7Y29sfVt7b3B0Oj4yfV17Qy5SfSAge2xhYmVsfSIpCgogICAgcHJpbnQoKQogICAgcHJpbnQoZiJ7Qy5DWU59e19saW5lKCfilIAnLCB3KX17Qy5SfSIpCiAgICBwcmludChfc3RhdHVzX2JhcigpKQogICAgcHJpbnQoZiJ7Qy5DWU59e19saW5lKCfilIAnLCB3KX17Qy5SfSIpCiAgICBwcmludCgpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNQUlOIExPT1AKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmRlZiBfcHJvbXB0KGxhYmVsOiBzdHIgPSAiRW50ZXIgb3B0aW9uIG51bWJlciIpIC0+IHN0cjoKICAgICIiIlVuaWZpZWQgaW5wdXQgcHJvbXB0LiIiIgogICAgaWYgTkFSUk9XOgogICAgICAgIHByaW50KGYiICB7Qy5DWU594pa2ICB7bGFiZWx9e0MuUn0iKQogICAgICAgIHJldHVybiBpbnB1dChmIiAge0MuWUxXfeKGkiAge0MuUn0iKS5zdHJpcCgpCiAgICByZXR1cm4gaW5wdXQoCiAgICAgICAgZiIgIHtDLkdSTn1kYXJrYm94ZXN7Qy5SfXtDLkJMS31Ae0MuUn17Qy5DWU59Y2xpZW50e0MuUn0ge0MuWUxXfcK7e0MuUn0gIgogICAgKS5zdHJpcCgpCgoKZGVmIF9hdXRoX2xvb3AoKSAtPiBib29sOgogICAgIiIiU2hvdyByZWdpc3Rlci9sb2dpbiBtZW51IHVudGlsIHNlc3Npb24gaXMgdmFsaWQuCiAgICBSZXR1cm5zIFRydWUgaWYgbG9nZ2VkIGluLCBGYWxzZSBpZiB1c2VyIGNob3NlIHRvIGV4aXQuIiIiCiAgICB3aGlsZSBub3Qgc2Vzc2lvbi5pc192YWxpZDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGRpc3BsYXlfYXV0aF9tZW51KCkKICAgICAgICAgICAgY2hvaWNlID0gX3Byb21wdCgpCiAgICAgICAgICAgIHByaW50KCkKCiAgICAgICAgICAgIGlmIGNob2ljZSA9PSAiMCI6CiAgICAgICAgICAgICAgICBvaygiR29vZGJ5ZS4gU3RheSBzZWN1cmUuIikKICAgICAgICAgICAgICAgIHJldHVybiBGYWxzZQoKICAgICAgICAgICAgZWxpZiBjaG9pY2UgPT0gIjEiOgogICAgICAgICAgICAgICAgZmxvd19yZWdpc3RlcigpCiAgICAgICAgICAgICAgICBpZiBzZXNzaW9uLmlzX3ZhbGlkOgogICAgICAgICAgICAgICAgICAgIG9rKCLinIUgUmVnaXN0cmF0aW9uIGNvbXBsZXRlIOKAlCB5b3UgYXJlIG5vdyBsb2dnZWQgaW4hIikKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGlucHV0KGYiICB7Qy5CTEt9UHJlc3MgRW50ZXIgdG8gY29udGludWUuLi57Qy5SfSIpCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IChLZXlib2FyZEludGVycnVwdCwgRU9GRXJyb3IpOgogICAgICAgICAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICAgICBlbGlmIGNob2ljZSA9PSAiMiI6CiAgICAgICAgICAgICAgICBpZiBmbG93X2xvZ2luKCk6CiAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBpbnB1dChmIiAge0MuQkxLfVByZXNzIEVudGVyIHRvIGNvbnRpbnVlLi4ue0MuUn0iKQogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCAoS2V5Ym9hcmRJbnRlcnJ1cHQsIEVPRkVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHdhcm4oZiJJbnZhbGlkIG9wdGlvbjogJ3tjaG9pY2V9Jy4gRW50ZXIgMSwgMiwgb3IgMC4iKQoKICAgICAgICBleGNlcHQgS2V5Ym9hcmRJbnRlcnJ1cHQ6CiAgICAgICAgICAgIHByaW50KCkKICAgICAgICAgICAgd2FybigiUHJlc3MgQ3RybCtDIGFnYWluIHRvIGV4aXQsIG9yIEVudGVyIHRvIGNvbnRpbnVlLiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlucHV0KGYiICB7Qy5CTEt9UHJlc3MgRW50ZXIgdG8gY29udGludWUuLi57Qy5SfSIpCiAgICAgICAgICAgIGV4Y2VwdCBLZXlib2FyZEludGVycnVwdDoKICAgICAgICAgICAgICAgIHByaW50KCkKICAgICAgICAgICAgICAgIG9rKCJFeGl0aW5nLiBTdGF5IHNlY3VyZSEiKQogICAgICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgZXhjZXB0IEVPRkVycm9yOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgIHJldHVybiBUcnVlCgoKZGVmIG1haW4oKToKICAgICIiIkFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9uIHN0YXJ0OiBzaG93IGF1dGgtb25seSBtZW51IChSZWdpc3RlciAvIExvZ2luIC8gRXhpdCkuCiAgICBBZnRlciBsb2dpbjogc2hvdyBmdWxsIHNlYXJjaCBtZW51IHdpdGhvdXQgUmVnaXN0ZXIvTG9naW4gb3B0aW9ucy4KICAgIE9uIGxvZ291dDogcmV0dXJuIHRvIGF1dGggbWVudSBhdXRvbWF0aWNhbGx5LgogICAgIiIiCiAgICBvcy5tYWtlZGlycyhSRVNVTFRTX0RJUiwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHByaW50X2Jhbm5lcigpCgogICAgIyBUcnkgcmVzdG9yaW5nIHNhdmVkIHNlc3Npb24gc2lsZW50bHkKICAgIGlmIHNlc3Npb24ubG9hZCgpOgogICAgICAgICMgU2lsZW50bHkgcmVmcmVzaCBjcmVkaXRzIGZyb20gc2VydmVyIHNvIHN0YXR1cyBiYXIgaXMgYWNjdXJhdGUKICAgICAgICB0cnk6CiAgICAgICAgICAgIF9yID0gYXBpLmJhbGFuY2UoKQogICAgICAgICAgICBpZiBfci5nZXQoInN0YXR1cyIpID09ICJzdWNjZXNzIjoKICAgICAgICAgICAgICAgIF9kID0gX3IuZ2V0KCJkYXRhIiwge30pCiAgICAgICAgICAgICAgICBzZXNzaW9uLmNyZWRpdHMgPSBfZC5nZXQoImNyZWRpdHMiLCBzZXNzaW9uLmNyZWRpdHMpCiAgICAgICAgICAgICAgICBzZXNzaW9uLnBsYW4gICAgPSBfZC5nZXQoInBsYW4iLCBzZXNzaW9uLnBsYW4pCiAgICAgICAgICAgICAgICBzZXNzaW9uLnNhdmUoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICBvayhmIlNlc3Npb24gcmVzdG9yZWQgIMK3ICBBY2NvdW50OiB7c2Vzc2lvbi5hY2NvdW50X2lkfSAgwrcgIENyZWRpdHM6IHtzZXNzaW9uLmNyZWRpdHN9ICDCtyAgUGxhbjoge3Nlc3Npb24ucGxhbiBvciAnTm9uZSd9IikKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlucHV0KGYiICB7Qy5CTEt9UHJlc3MgRW50ZXIgdG8gY29udGludWUuLi57Qy5SfSIpCiAgICAgICAgZXhjZXB0IChLZXlib2FyZEludGVycnVwdCwgRU9GRXJyb3IpOgogICAgICAgICAgICBwYXNzCiAgICBlbHNlOgogICAgICAgIGluZm8oIldlbGNvbWUhIFBsZWFzZSByZWdpc3RlciBvciBsb2cgaW4gdG8gY29udGludWUuIikKCiAgICAjIFNob3cgYXV0aCBsb29wIGlmIG5vdCBhbHJlYWR5IGxvZ2dlZCBpbgogICAgaWYgbm90IHNlc3Npb24uaXNfdmFsaWQ6CiAgICAgICAgaWYgbm90IF9hdXRoX2xvb3AoKToKICAgICAgICAgICAgcmV0dXJuICAjIHVzZXIgY2hvc2UgZXhpdAoKICAgICMg4pSA4pSAIE1BSU4gTUVOVSBMT09QIChsb2dnZWQgaW4pIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgd2hpbGUgVHJ1ZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGRpc3BsYXlfbWVudSgpCiAgICAgICAgICAgIGNob2ljZSA9IF9wcm9tcHQoKQogICAgICAgICAgICBwcmludCgpCgogICAgICAgICAgICBpZiBjaG9pY2UgPT0gIjAiOgogICAgICAgICAgICAgICAgIyBMb2cgT3V0ICYgRXhpdAogICAgICAgICAgICAgICAgaWYgc2Vzc2lvbi5pc192YWxpZDoKICAgICAgICAgICAgICAgICAgICBmbG93X2xvZ291dCgpCiAgICAgICAgICAgICAgICBvaygiR29vZGJ5ZS4gU3RheSBzZWN1cmUuIikKICAgICAgICAgICAgICAgIHByaW50KCkKICAgICAgICAgICAgICAgIGJyZWFrCgogICAgICAgICAgICAjIOKUgOKUgCBTZWFyY2hlcyAxLTE0IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBlbGlmIGNob2ljZSBpbiAoIjEiLCIyIiwiMyIsIjQiLCI1IiwiNiIsIjciLCI4IiwiOSIsIjEwIiwiMTEiLCIxMiIsIjEzIiwiMTQiKToKICAgICAgICAgICAgICAgIGlkeF9tYXAgPSB7c3RyKGkpOiBpLTEgZm9yIGkgaW4gcmFuZ2UoMSwgMTUpfQogICAgICAgICAgICAgICAgaXRlbSA9IFNFQVJDSF9DQVRBTE9HW2lkeF9tYXBbY2hvaWNlXV0KICAgICAgICAgICAgICAgIGZsb3dfc2luZ2xlX3NlYXJjaCgqaXRlbSkKCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIxNSI6CiAgICAgICAgICAgICAgICBmbG93X2JhdGNoX3NlYXJjaCgpCgogICAgICAgICAgICAjIOKUgOKUgCBVdGlsaXR5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBlbGlmIGNob2ljZSA9PSAiMTYiOgogICAgICAgICAgICAgICAgZmxvd19jaGVja19iYWxhbmNlKCkKICAgICAgICAgICAgZWxpZiBjaG9pY2UgPT0gIjE3IjoKICAgICAgICAgICAgICAgIGZsb3dfdmlld191c2FnZSgpCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIxOCI6CiAgICAgICAgICAgICAgICBmbG93X2NoZWNrX3N0YXR1cygpCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIxOSI6CiAgICAgICAgICAgICAgICBmbG93X3ZpZXdfZG9jcygpCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIyMCI6CiAgICAgICAgICAgICAgICBmbG93X2J1eV9jcmVkaXRzKCkKICAgICAgICAgICAgZWxpZiBjaG9pY2UgPT0gIjIxIjoKICAgICAgICAgICAgICAgIGZsb3dfc3VwcG9ydCgpCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIyMiI6CiAgICAgICAgICAgICAgICBmbG93X3ZpZXdfc2F2ZWQoKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgd2FybihmIkludmFsaWQgb3B0aW9uOiAne2Nob2ljZX0nLiBQbGVhc2UgZW50ZXIgYSBudW1iZXIgZnJvbSB0aGUgbWVudS4iKQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgZXhjZXB0IEtleWJvYXJkSW50ZXJydXB0OgogICAgICAgICAgICBwcmludCgpCiAgICAgICAgICAgIHdhcm4oIkludGVycnVwdGVkLiBQcmVzcyBDdHJsK0MgYWdhaW4gdG8gZXhpdCBvciBFbnRlciB0byBjb250aW51ZS4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbnB1dChmIiAge0MuQkxLfVByZXNzIEVudGVyIHRvIGNvbnRpbnVlLi4ue0MuUn0iKQogICAgICAgICAgICBleGNlcHQgS2V5Ym9hcmRJbnRlcnJ1cHQ6CiAgICAgICAgICAgICAgICBwcmludCgpCiAgICAgICAgICAgICAgICBvaygiRXhpdGluZy4gU3RheSBzZWN1cmUhIikKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIGV4Y2VwdCBFT0ZFcnJvcjoKICAgICAgICAgICAgcHJpbnQoKQogICAgICAgICAgICBvaygiRU9GIGRldGVjdGVkIOKAlCBleGl0aW5nLiIpCiAgICAgICAgICAgIGJyZWFrCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgZXJyKGYiVW5leHBlY3RlZCBlcnJvcjoge2V9IikKICAgICAgICAgICAgaW5mbygiSWYgdGhpcyBwZXJzaXN0cywgY29udGFjdCB5YWRpaWZ5QGdtYWlsLmNvbSIpCgogICAgICAgICMgUGF1c2UgYWZ0ZXIgZXZlcnkgYWN0aW9uCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBOQVJST1c6CiAgICAgICAgICAgICAgICBwcmludCgpCiAgICAgICAgICAgICAgICBpbnB1dChmIiAge0MuQkxLfeKUgOKUgOKUgCBQcmVzcyBFbnRlciB0byBjb250aW51ZSDilIDilIDilIB7Qy5SfSIpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBpbnB1dChmIlxuICB7Qy5CTEt9UHJlc3MgRW50ZXIgdG8gcmV0dXJuIHRvIG1lbnUuLi57Qy5SfSIpCiAgICAgICAgZXhjZXB0IChLZXlib2FyZEludGVycnVwdCwgRU9GRXJyb3IpOgogICAgICAgICAgICBwYXNzCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBFTlRSWSBQT0lOVAojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaWYgX19uYW1lX18gPT0gIl9fbWFpbl9fIjoKICAgIHRyeToKICAgICAgICBtYWluKCkKICAgIGV4Y2VwdCBLZXlib2FyZEludGVycnVwdDoKICAgICAgICBwcmludChmIlxuICB7Qy5XUk59WyFdIFRlcm1pbmF0ZWQgYnkgdXNlci57Qy5SfVxuIikKICAgICAgICBzeXMuZXhpdCgwKQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIHByaW50KGYiXG4gIHtDLkVSUn1bIV0gRmF0YWwgZXJyb3I6IHtlfXtDLlJ9IikKICAgICAgICBwcmludChmIiAge0MuQkxLfUNvbnRhY3QgeWFkaWlmeUBnbWFpbC5jb20gaWYgdGhpcyBwZXJzaXN0cy57Qy5SfVxuIikKICAgICAgICBzeXMuZXhpdCgxKQo="
)

_INSTRUCTIONS_B64 = (
    "4pWU4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWXCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgICAgICAgIERBUktCT1hFUyBJTlRFTExJR0VOQ0UgU1lTVEVNICAgICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWRICAgICAgICBUZXJtaW5hbCBDbGllbnQg4oCUIEluc3RhbGxhdGlvbiAmIFVzYWdlIEd1aWRlICAgICAgICAgICAgICDilZEK4pWRICAgICAgICBWZXJzaW9uIDMuMCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg4pWRCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgIFN1cHBvcnQgIDogQGRhcmtib3hlc0FkbWluIChUZWxlZ3JhbSkgICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWRICBFbWFpbCAgICA6IHlhZGlpZnlAZ21haWwuY29tICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg4pWRCuKVkSAgQ2hhbm5lbCAgOiBAZGFya2JveGVzdjEgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWa4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWdCgoK4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBClNFQ1RJT04gMTogUkVRVUlSRU1FTlRTCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQoKICDigKIgUHl0aG9uIDMuOCBvciBhYm92ZQogIOKAoiBwaXAgKFB5dGhvbiBwYWNrYWdlIG1hbmFnZXIsIGNvbWVzIHdpdGggUHl0aG9uKQogIOKAoiBJbnRlcm5ldCBjb25uZWN0aW9uCiAg4oCiIEEgRGFya0JveGVzIGFjY291bnQgKEFjY291bnQgSUQgKyBQYXNzd29yZCkKICDigKIgTk8gVGVsZWdyYW0gYWNjb3VudCByZXF1aXJlZAoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDI6IElOU1RBTExBVElPTgrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEKCk9OIFRFUk1VWCAoQW5kcm9pZCkK4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgU3RlcCAxOiBPcGVuIFRlcm11eAogIAogIFN0ZXAgMjogVXBkYXRlIHBhY2thZ2VzIGFuZCBpbnN0YWxsIFB5dGhvbgogICAgcGtnIHVwZGF0ZSAmJiBwa2cgdXBncmFkZQogICAgcGtnIGluc3RhbGwgcHl0aG9uCgogIFN0ZXAgMzogSW5zdGFsbCByZXF1aXJlZCBsaWJyYXJ5CiAgICBwaXAgaW5zdGFsbCByZXF1ZXN0cwoKICBTdGVwIDQ6IENvcHkgdGhlIGNsaWVudCBzY3JpcHQgdG8gVGVybXV4CiAgICAtIERvd25sb2FkIGRhcmtib3hlc19jbGllbnQucHkgZnJvbSB0aGUgVGVsZWdyYW0gYm90CiAgICAgIChUYXAgIkRvd25sb2FkIENsaWVudCBTY3JpcHQiIGluIHRoZSBib3QgbWVudSkKICAgIC0gT3IgdHJhbnNmZXIgaXQgbWFudWFsbHkgdG8geW91ciBUZXJtdXggaG9tZSBkaXJlY3RvcnkKCiAgU3RlcCA1OiBSdW4gdGhlIGNsaWVudAogICAgcHl0aG9uIGRhcmtib3hlc19jbGllbnQucHkKCiAgVEVSTVVYIFRJUFM6CiAg4oCiIElmIHRleHQgbG9va3MgY3JhbXBlZCwgdHVybiB5b3VyIHBob25lIHRvIGxhbmRzY2FwZSBtb2RlLgogIOKAoiBUaGUgY2xpZW50IGF1dG8tZGV0ZWN0cyBuYXJyb3cgdGVybWluYWxzIGFuZCB1c2VzIDItbGluZQogICAgZGlzcGxheSBtb2RlIGZvciBtZW51cyBhbmQgcHJvbXB0cy4KICDigKIgWW91IGNhbiBpbmNyZWFzZSBmb250IHNpemUgaW4gVGVybXV4IHNldHRpbmdzLgoKCk9OIExJTlVYIC8gS0FMSSAvIFVCVU5UVSAvIERFQklBTgrilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICBTdGVwIDE6IEluc3RhbGwgUHl0aG9uIChpZiBub3QgcHJlc2VudCkKICAgIHN1ZG8gYXB0IGluc3RhbGwgcHl0aG9uMyBweXRob24zLXBpcAoKICBTdGVwIDI6IEluc3RhbGwgcmVxdWlyZWQgbGlicmFyeQogICAgcGlwMyBpbnN0YWxsIHJlcXVlc3RzCgogIFN0ZXAgMzogUnVuIHRoZSBjbGllbnQKICAgIHB5dGhvbjMgZGFya2JveGVzX2NsaWVudC5weQoKCk9OIFdJTkRPV1MgKFBvd2VyU2hlbGwgLyBDTUQpCuKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogIFN0ZXAgMTogRG93bmxvYWQgUHl0aG9uIGZyb20gaHR0cHM6Ly9weXRob24ub3JnCiAgICAgICAgICBDaGVjayAiQWRkIFB5dGhvbiB0byBQQVRIIiBkdXJpbmcgaW5zdGFsbAoKICBTdGVwIDI6IEluc3RhbGwgcmVxdWlyZWQgbGlicmFyeQogICAgcGlwIGluc3RhbGwgcmVxdWVzdHMKCiAgU3RlcCAzOiBSdW4gdGhlIGNsaWVudAogICAgcHl0aG9uIGRhcmtib3hlc19jbGllbnQucHkKCgpPTiBtYWNPUwrilIDilIDilIDilIDilIDilIDilIDilIAKICBTdGVwIDE6IEluc3RhbGwgUHl0aG9uCiAgICBicmV3IGluc3RhbGwgcHl0aG9uICAob3IgZG93bmxvYWQgZnJvbSBweXRob24ub3JnKQoKICBTdGVwIDI6IEluc3RhbGwgcmVxdWlyZWQgbGlicmFyeQogICAgcGlwMyBpbnN0YWxsIHJlcXVlc3RzCgogIFN0ZXAgMzogUnVuIHRoZSBjbGllbnQKICAgIHB5dGhvbjMgZGFya2JveGVzX2NsaWVudC5weQoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDM6IEdFVFRJTkcgU1RBUlRFRCAoRklSU1QgUlVOKQrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEKCllvdSBkbyBOT1QgbmVlZCBhIFRlbGVncmFtIGFjY291bnQgdG8gdXNlIHRoZSB0ZXJtaW5hbCBjbGllbnQuCgpPUFRJT04gQTogUmVnaXN0ZXIgZGlyZWN0bHkgaW4gdGhlIGNsaWVudAogIDEuIFJ1bjogcHl0aG9uIGRhcmtib3hlc19jbGllbnQucHkKICAyLiBDaG9vc2UgWzFdIFJlZ2lzdGVyIE5ldyBBY2NvdW50CiAgMy4gRW50ZXIgYSB1c2VybmFtZSBhbmQgcGFzc3dvcmQKICA0LiBZb3VyIEFjY291bnQgSUQgd2lsbCBiZSBzaG93biDigJQgU0FWRSBJVC4KICA1LiBDb250YWN0IEBkYXJrYm94ZXNBZG1pbiB0byBwdXJjaGFzZSBjcmVkaXRzL3BsYW5zLgoKT1BUSU9OIEI6IEdldCBjcmVkZW50aWFscyBmcm9tIHRoZSBUZWxlZ3JhbSBib3QgKGlmIHlvdSB1c2UgVEcpCiAgMS4gT3BlbiBvdXIgVGVsZWdyYW0gYm90LgogIDIuIFRhcCAiR2V0IE15IExvZ2luIENyZWRlbnRpYWxzIiAo8J+Xne+4jykgaW4gdGhlIG1haW4gbWVudS4KICAzLiBOb3RlIHlvdXIgQWNjb3VudCBJRCBhbmQgcGFzc3dvcmQuCiAgNC4gVXNlIHRoZW0gdG8gbG9nIGluIHdpdGggb3B0aW9uIFsyXSBpbiB0aGUgY2xpZW50LgoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDQ6IEhPVyBUTyBCVVkgQ1JFRElUUyAvIFBMQU5TCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQoKTUVUSE9EIDEg4oCUIFZpYSBUZWxlZ3JhbSBCb3QKICAxLiBPcGVuIHRoZSBEYXJrQm94ZXMgVGVsZWdyYW0gYm90LgogIDIuIFRhcCDwn5KOIFByZW1pdW0gUGxhbnMuCiAgMy4gU2VsZWN0IGEgcGxhbi4KICA0LiBQYXkgdmlhIFVQSTogZGFya2JveGVzQHlibAogIDUuIEFmdGVyIHBheW1lbnQsIGVudGVyIHlvdXIgVVRSIC8gVHJhbnNhY3Rpb24gTnVtYmVyCiAgICAgKHNob3duIGluIHlvdXIgVVBJIGFwcCDigJQgUGhvbmVQZSwgR1BheSwgUGF5dG0sIGV0Yy4pCiAgNi4gQWRtaW4gdmVyaWZpZXMgbWFudWFsbHkg4oCUIGFjdGl2YXRlZCB3aXRoaW4gNeKAkzE1IG1pbnV0ZXMuCgpNRVRIT0QgMiDigJQgRGlyZWN0IENvbnRhY3QKICBDb250YWN0OiBAZGFya2JveGVzQWRtaW4gKFRlbGVncmFtKQogIEVtYWlsICA6IHlhZGlpZnlAZ21haWwuY29tCiAgUHJvdmlkZTogeW91ciBBY2NvdW50IElEICsgcGF5bWVudCBwcm9vZiAoVVRSIG51bWJlcikKCkFWQUlMQUJMRSBQTEFOUwogIOKaoSBTdGFydGVyIFBhY2sgICAgICA1IHNlYXJjaGVzICAgICDigrkxMDAgIChubyBleHBpcnkpCiAg8J+UjSBFeHBsb3JlciBQYWNrICAgIDE1IHNlYXJjaGVzICAgICDigrkyNTAgIChubyBleHBpcnkpCiAg8J+agCBEYWlseSAxMC8zMGQgICAgIDEwL2RhecK3MzAgZGF5cyAg4oK5ODAwCiAg8J+SjiBEYWlseSAyMC8zMGQgICAgIDIwL2RhecK3MzAgZGF5cyAg4oK5MTAwMAogIPCfjJ8gRGFpbHkgMTAvMm0gICAgICAxMC9kYXnCtzYwIGRheXMgIOKCuTE1MDAKICDwn5GRIERhaWx5IDIwLzJtICAgICAgMjAvZGF5wrc2MCBkYXlzICDigrkxODAwCgoK4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBClNFQ1RJT04gNTogQVZBSUxBQkxFIFNFQVJDSEVTCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQoKICBPcHRpb24gIFNlYXJjaCBUeXBlICAgICAgICAgICBJbnB1dCBFeGFtcGxlCiAg4pSA4pSA4pSA4pSA4pSA4pSAICDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAgIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogIFs0XSAgICAgUGhvbmUgSW50ZWxsaWdlbmNlICAgIDk4NzY1NDMyMTAKICBbNV0gICAgIEZhbWlseSBOZXR3b3JrICAgICAgICAxMjM0NTY3ODkwMTIgKEFhZGhhcikKICBbNl0gICAgIEFhZGhhciBDb21wcmVoZW5zaXZlICAxMjM0NTY3ODkwMTIKICBbN10gICAgIFZlaGljbGUgSW50ZWxsaWdlbmNlICBVUDUzQ1ozMzkxCiAgWzhdICAgICBUZWxlZ3JhbSBJbnRlbGxpZ2VuY2UgQHVzZXJuYW1lCiAgWzldICAgICBEZXZpY2UgSU1FSSAgICAgICAgICAgMzU0Njc4OTAxMjM0NTY3CiAgWzEwXSAgICBHU1QgSW50ZWxsaWdlbmNlICAgICAgMjdBQVBGVTA5MzlGMVpWCiAgWzExXSAgICBJbnN0YWdyYW0gICAgICAgICAgICAgdXNlcm5hbWUKICBbMTJdICAgIElQIEludGVsbGlnZW5jZSAgICAgICAxLjIuMy40CiAgWzEzXSAgICBJRlNDIENvZGUgICAgICAgICAgICAgU0JJTjAwMDEyMzQKICBbMTRdICAgIEVtYWlsIEludGVsbGlnZW5jZSAgICB1c2VyQGV4YW1wbGUuY29tCiAgWzE1XSAgICBVUEkgSW50ZWxsaWdlbmNlICAgICAgdXNlckB1cGkKICBbMTZdICAgIFBha2lzdGFuIERCICAgICAgICAgICBuYW1lIC8gcGhvbmUgLyBOSUMKICBbMTddICAgIEFkdmFuY2VkIE9TSU5UL0xlYWsgICBhbnkgcXVlcnkKICBbMThdICAgIEJhdGNoIFNlYXJjaCAgICAgICAgICBtdWx0aXBsZSBhdCBvbmNlCgoK4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBClNFQ1RJT04gNjogU0FWRUQgUkVTVUxUUwrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEKCkFsbCBzZWFyY2ggcmVzdWx0cyBhcmUgYXV0b21hdGljYWxseSBzYXZlZCBhcyBKU09OIGZpbGVzIGluOgogIH4vZGFya2JveGVzX3Jlc3VsdHMvCgpZb3UgY2FuIHZpZXcgdGhlbSB3aXRoIG9wdGlvbiBbMjZdIGluIHRoZSBtZW51LCBvciBvcGVuCnRoZSBKU09OIGZpbGVzIGRpcmVjdGx5LgoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDc6IFNFQ1VSSVRZIE5PVElDRVMK4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBCgogIOKAoiBOZXZlciBzaGFyZSB5b3VyIHBhc3N3b3JkIHdpdGggYW55b25lLCBpbmNsdWRpbmcgYWRtaW4uCiAg4oCiIE9mZmljaWFsIGFkbWluOiBAZGFya2JveGVzQWRtaW4gT05MWS4KICDigKIgQmV3YXJlIG9mIGltcGVyc29uYXRvcnMuCiAg4oCiIFRoaXMgc2VydmljZSBpcyBmb3IgYXV0aG9yaXplZCwgbGF3ZnVsIHVzZSBvbmx5LgogIOKAoiBNaXN1c2UgbWF5IHJlc3VsdCBpbiBhY2NvdW50IHRlcm1pbmF0aW9uLgoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDg6IFRST1VCTEVTSE9PVElORwrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEKCiAgUHJvYmxlbTogIk1vZHVsZU5vdEZvdW5kRXJyb3I6IE5vIG1vZHVsZSBuYW1lZCAncmVxdWVzdHMnIgogIEZpeCAgICA6IFJ1biAgcGlwIGluc3RhbGwgcmVxdWVzdHMKCiAgUHJvYmxlbTogIkNvbm5lY3Rpb24gZmFpbGVkIiBvciAiVGltZW91dCIKICBGaXggICAgOiBDaGVjayBpbnRlcm5ldC4gVHJ5IGFnYWluIGluIGEgbW9tZW50LgogICAgICAgICAgIFNlcnZlciBtYXkgYmUgdGVtcG9yYXJpbHkgYnVzeS4KCiAgUHJvYmxlbTogIkludmFsaWQgY3JlZGVudGlhbHMiCiAgRml4ICAgIDogQ2hlY2sgQWNjb3VudCBJRCBhbmQgcGFzc3dvcmQgY2FyZWZ1bGx5LgogICAgICAgICAgIEFjY291bnQgSUQgc3RhcnRzIHdpdGggREIsIGUuZy4gREIxQTJCM0M0RC4KCiAgUHJvYmxlbTogIkluc3VmZmljaWVudCBjcmVkaXRzIgogIEZpeCAgICA6IEJ1eSBjcmVkaXRzIHZpYSBvcHRpb24gWzI0XSBpbiB0aGUgbWVudS4KCiAgUHJvYmxlbTogRGlzcGxheSBsb29rcyB3cm9uZyBpbiBUZXJtdXgKICBGaXggICAgOiBUaGUgY2xpZW50IGF1dG8tYWRqdXN0cyBmb3IgbmFycm93IHNjcmVlbnMuCiAgICAgICAgICAgVHJ5IGxhbmRzY2FwZSBtb2RlIG9yIGluY3JlYXNlIHRlcm1pbmFsIHdpZHRoLgoKICBTdGlsbCBzdHVjaz8gQ29udGFjdDoKICAgIFRlbGVncmFtIDogQGRhcmtib3hlc0FkbWluCiAgICBFbWFpbCAgICA6IHlhZGlpZnlAZ21haWwuY29tCgoK4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBCkRBUktCT1hFUyBJTlRFTExJR0VOQ0UgU1lTVEVNICDCqTIwMjUgIEFsbCByaWdodHMgcmVzZXJ2ZWQuCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQo="
)

def _get_client_bytes() -> bytes:
    """Decode embedded client script."""
    return _b64.b64decode(_CLIENT_SCRIPT_B64)

def _get_instructions_bytes() -> bytes:
    """Decode embedded instructions."""
    return _b64.b64decode(_INSTRUCTIONS_B64)


@bot_client.on(events.CallbackQuery(pattern=r'^download_client$'))
async def download_client_callback(event):
    """Send client script and instructions directly from embedded content."""
    try:
        user_id = event.sender_id

        user_doc = await db_manager.get_user(user_id)
        if not user_doc:
            await event.answer("❌ Please /start the bot first.", alert=True)
            return

        await event.answer("📦 Preparing download...", alert=False)

        sent_files = []

        # ── Send darkboxes_client.py from embedded bytes ──────────
        try:
            client_bytes = _get_client_bytes()
            client_buf = _BytesIO(client_bytes)
            client_buf.name = "darkboxes_client.py"
            await bot_client.send_file(
                user_id,
                client_buf,
                caption=(
                    "💻 **DARKBOXES INTELLIGENCE CLIENT**\n\n"
                    "**Version:** 3.0 — Professional Terminal Edition\n"
                    "**Compatible:** Termux · Linux · Kali · Windows · macOS\n\n"
                    "📋 **Quick Start:**\n"
                    "`pip install requests`\n"
                    "`python darkboxes_client.py`\n\n"
                    "🔑 Log in with your Account ID & Password (see 🗝️ button below).\n"
                    "❌ No Telegram account needed to use the client.\n\n"
                    "📖 Installation guide sent separately (INSTRUCTIONS.txt)"
                ),
                parse_mode="md"
            )
            sent_files.append("darkboxes_client.py ✅")
            logger.info(f"✅ Sent darkboxes_client.py to {user_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send client script to {user_id}: {e}")
            sent_files.append("darkboxes_client.py ❌")

        # ── Send INSTRUCTIONS.txt from embedded bytes ─────────────
        try:
            instr_bytes = _get_instructions_bytes()
            instr_buf = _BytesIO(instr_bytes)
            instr_buf.name = "INSTRUCTIONS.txt"
            await bot_client.send_file(
                user_id,
                instr_buf,
                caption=(
                    "📖 **DARKBOXES — INSTALLATION & USAGE GUIDE**\n\n"
                    "Read this before running the client.\n"
                    "• Termux (Android), Linux, Kali, Windows, macOS steps included.\n\n"
                    "❓ Help: @darkboxesAdmin"
                ),
                parse_mode="md"
            )
            sent_files.append("INSTRUCTIONS.txt ✅")
            logger.info(f"✅ Sent INSTRUCTIONS.txt to {user_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send instructions to {user_id}: {e}")
            sent_files.append("INSTRUCTIONS.txt ❌")

        await event.edit(
            f"✅ **FILES SENT TO YOUR CHAT**\n\n"
            f"📦 **Sent:**\n"
            + "\n".join(f"  • {f}" for f in sent_files) +
            f"\n\n"
            f"📋 **Next Steps:**\n"
            f"1. Install: `pip install requests`\n"
            f"2. Run: `python darkboxes_client.py`\n"
            f"3. Register (option 1) or log in (option 2)\n"
            f"4. Use option 24 inside the client to buy credits\n\n"
            f"❓ Help: @darkboxesAdmin",
            buttons=[
                [Button.inline("🗝️ Get My Login Credentials", "get_credentials")],
                [Button.inline("« Main Menu", "main_menu")]
            ],
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ download_client_callback: {e}")
        await event.answer("❌ Error preparing download. Contact @darkboxesAdmin.", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^get_credentials$'))
async def get_credentials_callback(event):
    """Show user their account credentials for the client script"""
    try:
        user_id = event.sender_id

        account = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.accounts.find_one({"linked_tg_ids": user_id})
        )

        if not account:
            # Auto-create account
            user = await event.get_sender()
            account = await get_or_create_db_account(
                user_id,
                getattr(user, 'username', '') or '',
                getattr(user, 'first_name', '') or 'User'
            )

        acc_id = account.get("account_id", "N/A")
        sub = account.get("subscription") or "None"
        credits = account.get("searches_remaining", 0)

        cred_text = (
            f"🗝️ **YOUR LOGIN CREDENTIALS**\n\n"
            f"Use these to log into the terminal client.\n"
            f"No Telegram account needed — just these details.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Account ID:** `{acc_id}`\n"
            f"🔑 **Password:** Your password was sent when you first started the bot.\n"
            f"   If you can't find it, scroll up in this chat to the welcome message,\n"
            f"   or contact @darkboxesAdmin with your Account ID to reset it.\n"
            f"💰 **Credits:** {credits}\n"
            f"📦 **Plan:** {sub}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💻 **Use in client:**\n"
            f"1. Run `python darkboxes_client.py`\n"
            f"2. Choose Log In (option 2)\n"
            f"3. Enter Account ID: `{acc_id}`\n"
            f"4. Enter your password\n\n"
            f"🔒 Never share your password with anyone.\n"
            f"Official support: @darkboxesAdmin"
        )

        await event.edit(
            cred_text,
            buttons=[
                [Button.inline("💻 Download Client", "download_client")],
                [Button.inline("🔄 Refresh Account Info", "get_credentials")],
                [Button.inline("« Main Menu", "main_menu")]
            ],
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ get_credentials_callback: {e}")
        await event.answer("❌ Error fetching credentials", alert=True)


# ================== ENHANCED ADMIN — LAST ACTIVE USERS & SEARCH LOGS ==================

@bot_client.on(events.CallbackQuery(pattern=r'^admin_last_active$'))
async def admin_last_active_callback(event):
    """Admin: show recently active users"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return

        loop = asyncio.get_running_loop()
        users = await loop.run_in_executor(
            None, lambda: list(db_manager.db.users.find(
                {},
                {"user_id": 1, "username": 1, "first_name": 1, "last_seen": 1,
                 "searches_remaining": 1, "subscription": 1, "total_searches": 1}
            ).sort("last_seen", -1).limit(20))
        )

        if not users:
            await event.edit(
                "👥 **LAST ACTIVE USERS**\n\nNo users found.",
                buttons=[[Button.inline("« Admin Panel", "admin_panel")]],
                parse_mode="md"
            )
            return

        text = "👥 **LAST ACTIVE USERS** (Top 20)\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        now = datetime.now(timezone.utc)

        for i, u in enumerate(users, 1):
            uname = f"@{u.get('username')}" if u.get('username') else "no_username"
            fname = u.get('first_name', 'Unknown')
            uid = u.get('user_id', 'N/A')
            last_seen_raw = u.get('last_seen', '')
            sub = u.get('subscription') or "—"
            credits = u.get('searches_remaining', 0)
            searches = u.get('total_searches', 0)

            # Format time ago
            if last_seen_raw:
                try:
                    ls = datetime.fromisoformat(last_seen_raw.replace('Z', '+00:00'))
                    diff = now - ls
                    if diff.seconds < 60:
                        ago = "just now"
                    elif diff.seconds < 3600:
                        ago = f"{diff.seconds // 60}m ago"
                    elif diff.days == 0:
                        ago = f"{diff.seconds // 3600}h ago"
                    else:
                        ago = f"{diff.days}d ago"
                except Exception:
                    ago = last_seen_raw[:10]
            else:
                ago = "unknown"

            text += (
                f"{i}. **{fname}** ({uname})\n"
                f"   🆔 `{uid}` • 🕐 {ago}\n"
                f"   💰 Credits: {credits} • 📦 Plan: {sub} • 🔍 Searches: {searches}\n\n"
            )

        await event.edit(
            text,
            buttons=[
                [Button.inline("🔄 Refresh", "admin_last_active")],
                [Button.inline("« Admin Panel", "admin_panel")]
            ],
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ admin_last_active_callback: {e}")
        await event.answer("❌ Error loading last active users", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_search_logs$'))
async def admin_search_logs_callback(event):
    """Admin: show recent search logs across all users"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return

        loop = asyncio.get_running_loop()
        logs = await loop.run_in_executor(
            None, lambda: list(db_manager.db.search_logs.find(
                {},
                {"user_id": 1, "search_type": 1, "query": 1, "timestamp": 1,
                 "success": 1, "credits_used": 1, "response_preview": 1}
            ).sort("timestamp", -1).limit(25))
        )

        if not logs:
            await event.edit(
                "🔍 **SEARCH LOGS**\n\nNo search logs found.",
                buttons=[[Button.inline("« Admin Panel", "admin_panel")]],
                parse_mode="md"
            )
            return

        text = "🔍 **RECENT SEARCH LOGS** (Last 25)\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, log in enumerate(logs, 1):
            uid = log.get('user_id', 'N/A')
            stype = log.get('search_type', 'unknown')
            query = log.get('query', '—')
            ts = log.get('timestamp', '')[:16].replace('T', ' ')
            success = "✅" if log.get('success') else "❌"
            credits = log.get('credits_used', 0)
            response_preview = log.get('response_preview', '')

            # Admin sees FULL unmasked queries (for monitoring trial accuracy)
            text += (
                f"{i}. {success} **{stype}** — `{query}`\n"
                f"   👤 UID: `{uid}` • 🕐 {ts} • 💳 {credits}cr\n"
            )
            if response_preview:
                preview_short = response_preview[:120].replace('\n', ' ')
                text += f"   📄 _Response:_ `{preview_short}...`\n"
            text += "\n"

        await event.edit(
            text,
            buttons=[
                [Button.inline("🔄 Refresh", "admin_search_logs")],
                [Button.inline("📊 User Search Logs", "admin_user_search_logs")],
                [Button.inline("« Admin Panel", "admin_panel")]
            ],
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ admin_search_logs_callback: {e}")
        await event.answer("❌ Error loading search logs", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_user_search_logs$'))
async def admin_user_search_logs_ask(event):
    """Admin: ask for user ID to see their search logs"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return

        user_states[event.sender_id] = {"action": "admin_view_user_search_logs"}
        await event.edit(
            "🔍 **VIEW USER SEARCH LOGS**\n\n"
            "Enter the User ID to see their complete search history:",
            buttons=[[Button.inline("❌ Cancel", "admin_panel")]],
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"❌ admin_user_search_logs_ask: {e}")


@bot_client.on(events.CallbackQuery(pattern=r'^admin_intent_monitor$'))
async def admin_intent_monitor_callback(event):
    """Admin: intent monitoring — show suspicious/high-volume users"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return

        loop = asyncio.get_running_loop()
        now = datetime.now(timezone.utc)
        one_hour_ago = (now - timedelta(hours=1)).isoformat()

        # High-volume in last hour
        pipeline = [
            {"$match": {"timestamp": {"$gte": one_hour_ago}}},
            {"$group": {
                "_id": "$user_id",
                "count": {"$sum": 1},
                "types": {"$addToSet": "$search_type"}
            }},
            {"$sort": {"count": -1}},
            {"$limit": 15}
        ]

        high_vol = await loop.run_in_executor(
            None, lambda: list(db_manager.db.search_logs.aggregate(pipeline))
        )

        text = (
            "🕵️ **INTENT MONITOR — ACTIVITY ANALYSIS**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**High Volume Users (Last 1 Hour):**\n\n"
        )

        if not high_vol:
            text += "No significant activity in the last hour.\n\n"
        else:
            for i, entry in enumerate(high_vol, 1):
                uid = entry.get('_id', 'N/A')
                count = entry.get('count', 0)
                types = ", ".join(entry.get('types', []))

                # Flag if suspicious
                flag = "🚨" if count >= 10 else ("⚠️" if count >= 5 else "ℹ️")

                # Look up username
                u = await loop.run_in_executor(
                    None, lambda: db_manager.db.users.find_one(
                        {"user_id": uid}, {"username": 1, "first_name": 1}
                    )
                )
                uname = f"@{u.get('username', '?')}" if u else "unknown"
                fname = u.get('first_name', 'Unknown') if u else 'Unknown'

                text += (
                    f"{flag} {i}. **{fname}** ({uname})\n"
                    f"   UID: `{uid}` • {count} searches\n"
                    f"   Types: {types}\n\n"
                )

        text += "\n💡 High-volume = 10+ searches in 1 hour. Review manually."

        await event.edit(
            text,
            buttons=[
                [Button.inline("🔄 Refresh", "admin_intent_monitor")],
                [Button.inline("📋 Search Logs", "admin_search_logs")],
                [Button.inline("👥 Last Active", "admin_last_active")],
                [Button.inline("« Admin Panel", "admin_panel")]
            ],
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ admin_intent_monitor_callback: {e}")
        await event.answer("❌ Error loading intent monitor", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_pending_utr$'))
async def admin_pending_utr_callback(event):
    """Admin: view all pending UTR payments"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admin only", alert=True)
            return

        loop = asyncio.get_running_loop()
        pending = await loop.run_in_executor(
            None, lambda: list(db_manager.db.pending_payments.find(
                {"status": "pending"}
            ).sort("timestamp", -1).limit(20))
        )

        if not pending:
            await event.edit(
                "✅ **NO PENDING PAYMENTS**\n\nAll payments have been processed.",
                buttons=[[Button.inline("« Admin Panel", "admin_panel")]],
                parse_mode="md"
            )
            return

        text = f"⏳ **PENDING UTR PAYMENTS** ({len(pending)} pending)\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, pay in enumerate(pending[:10], 1):
            pid = pay.get('payment_id', 'N/A')
            uid = pay.get('user_id', 'N/A')
            fname = pay.get('first_name', 'N/A')
            plan = pay.get('plan_name', 'N/A')
            amount = pay.get('amount', 0)
            utr = pay.get('utr', '—')
            ts = pay.get('timestamp', '')[:16].replace('T', ' ')
            plan_id = pay.get('plan_id', '')

            text += (
                f"{i}. **{fname}** — UID: `{uid}`\n"
                f"   💳 Plan: {plan} (₹{amount})\n"
                f"   🏦 UTR: `{utr}`\n"
                f"   🕐 {ts}\n"
                f"   [✅ Approve](tg://btn/approve_payment_{pid}_{uid}_{plan_id})\n\n"
            )

        await event.edit(
            text,
            buttons=[
                [Button.inline("🔄 Refresh", "admin_pending_utr")],
                [Button.inline("« Admin Panel", "admin_panel")]
            ],
            parse_mode="md"
        )

    except Exception as e:
        logger.error(f"❌ admin_pending_utr_callback: {e}")
        await event.answer("❌ Error loading pending payments", alert=True)


async def handle_admin_view_user_search_logs(event):
    """Handle admin request to view a specific user's search logs"""
    try:
        user_input = (event.text or "").strip()
        if not user_input.isdigit():
            await event.respond("❌ Please enter a valid numeric user ID.")
            return

        target_uid = int(user_input)
        loop = asyncio.get_running_loop()

        logs = await loop.run_in_executor(
            None, lambda: list(db_manager.db.search_logs.find(
                {"user_id": target_uid},
                {"search_type": 1, "query": 1, "timestamp": 1, "success": 1,
                 "credits_used": 1, "response_preview": 1}
            ).sort("timestamp", -1).limit(30))
        )

        user_doc = await db_manager.get_user(target_uid)
        uname = f"@{user_doc.get('username', '?')}" if user_doc else "unknown"
        fname = user_doc.get('first_name', 'Unknown') if user_doc else 'Unknown'

        if not logs:
            await event.respond(
                f"📋 **SEARCH LOGS — {fname} ({uname})**\n\nNo search logs found for this user."
            )
            user_states.pop(event.sender_id, None)
            return

        text = f"📋 **SEARCH LOGS — {fname} ({uname})**\nUID: `{target_uid}`\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, log in enumerate(logs, 1):
            stype = log.get('search_type', 'unknown')
            query = log.get('query', '—')
            ts = log.get('timestamp', '')[:16].replace('T', ' ')
            success = "✅" if log.get('success') else "❌"
            credits = log.get('credits_used', 0)
            response_preview = log.get('response_preview', '')

            text += (
                f"{i}. {success} **{stype}**\n"
                f"   Query: `{query}`\n"
                f"   🕐 {ts} • 💳 {credits}cr\n"
            )
            if response_preview:
                preview_short = response_preview[:100].replace('\n', ' ')
                text += f"   📄 _Response:_ `{preview_short}...`\n"
            text += "\n"

        await event.respond(text, parse_mode="md")
        user_states.pop(event.sender_id, None)

    except Exception as e:
        logger.error(f"❌ handle_admin_view_user_search_logs: {e}")
        await event.respond("❌ Error retrieving search logs.")
        user_states.pop(event.sender_id, None)

async def daily_subscription_reset():
    """Background task: reset daily usage counter at midnight UTC"""
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Sleep until next midnight UTC
            next_midnight = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=5, microsecond=0
            )
            sleep_secs = (next_midnight - now).total_seconds()
            logger.info(f"⏰ Next subscription reset in {sleep_secs/3600:.1f}h")
            await asyncio.sleep(sleep_secs)

            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.users.update_many(
                    {"subscription_reset_date": {"$ne": today_str}, "subscription": {"$ne": None}},
                    {"$set": {"subscription_used_today": 0, "subscription_reset_date": today_str}}
                )
            )
            logger.info(f"✅ Daily reset: {result.modified_count} subscriptions reset")
        except Exception as e:
            logger.error(f"❌ Error in daily_subscription_reset: {e}")
            await asyncio.sleep(3600)



# ================== WEB SERVER ==================


async def memory_monitor():
    """Background task: monitor memory every 5 minutes and aggressively clear
    stale state to prevent OOM kills on Render's 512 MB free tier.
    """
    import gc

    def _get_rss_mb() -> float:
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024  # kB → MB
        except Exception:
            pass
        return 0.0

    while True:
        try:
            mem_mb = _get_rss_mb()
            active = len(search_engine.active_searches) if search_engine else 0
            logger.info(f"📊 Memory: {mem_mb:.1f} MB | Active searches: {active}")

            # Aggressively clean up if memory is high (>380 MB on Render free = danger zone)
            if mem_mb > 380:
                logger.warning(f"⚠️ High memory ({mem_mb:.1f} MB) — clearing stale state")
                if search_engine:
                    # Cancel and remove searches older than 60 seconds
                    now = time.time()
                    stale = [
                        sid for sid, info in list(search_engine.active_searches.items())
                        if now - info.get("start_time", now) > 60
                    ]
                    for sid in stale:
                        entry = search_engine.active_searches.pop(sid, None)
                        if entry:
                            fut = entry.get("future")
                            if fut and not fut.done():
                                fut.cancel()
                    if stale:
                        logger.info(f"🧹 Cleared {len(stale)} stale search(es)")
                gc.collect()
                mem_after = _get_rss_mb()
                logger.info(f"🧹 Memory after GC: {mem_after:.1f} MB")

            if mem_mb > 450:
                logger.error(f"🚨 Critical memory ({mem_mb:.1f} MB) — forcing full active_searches clear")
                if search_engine:
                    search_engine.active_searches.clear()
                gc.collect()

        except Exception as e:
            logger.error(f"❌ memory_monitor error: {e}")
        await asyncio.sleep(300)


async def render_self_ping():
    """Ping our own /health endpoint every 10 minutes to prevent Render spin-down.

    Waits until _WEB_SERVER_STARTED is True before pinging so we never hit
    the "Cannot connect to host" error during startup.
    """
    from aiohttp import ClientSession, ClientTimeout

    # Wait until the web server has actually bound the port
    waited = 0
    while not _WEB_SERVER_STARTED:
        await asyncio.sleep(3)
        waited += 3
        if waited > 120:
            logger.warning("⚠️ Self-ping: web server not ready after 120s, proceeding anyway")
            break
    # Extra grace period for TCPSite to fully accept connections
    await asyncio.sleep(5)

    url = f"http://127.0.0.1:{config.PORT}/health"
    logger.info(f"🏓 Self-ping armed → {url}")

    while True:
        try:
            async with ClientSession(timeout=ClientTimeout(total=15)) as session:
                async with session.get(url) as resp:
                    logger.info(f"🏓 Self-ping → HTTP {resp.status} (Render inactivity timer reset)")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"⚠️ Self-ping failed: {e}")
        await asyncio.sleep(600)  # every 10 minutes


async def telegram_keepalive():
    """Ping Telegram every 3 minutes to prevent silent disconnects.

    Waits for bot_info to be set (i.e. _run_bot has fully started) before
    sending any pings — prevents crashing on startup before clients connect.
    """
    # Wait until bot is fully started
    while bot_info is None:
        await asyncio.sleep(5)

    while True:
        await asyncio.sleep(180)  # 3 minutes
        try:
            if not bot_client.is_connected():
                logger.warning("⚠️ Telegram keepalive: bot_client not connected, skipping ping")
                continue
            await bot_client.get_me()
            if USE_USER_ACCOUNT and user_client is not bot_client:
                if user_client.is_connected():
                    await user_client.get_me()
            logger.info("💓 Telegram keepalive OK")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"⚠️ Telegram keepalive failed: {e}")
            # Don't raise — just log and continue. The reconnect loop in
            # main() handles actual disconnections.


async def event_loop_watchdog():
    """Detect event loop stalls caused by thread pool exhaustion."""
    # Brief startup delay so initial DC migration doesn't look like a stall
    await asyncio.sleep(30)
    last_tick = time.time()
    while True:
        try:
            await asyncio.sleep(60)
            now = time.time()
            gap = now - last_tick
            last_tick = now
            if gap > 90:
                logger.error(
                    f"🚨 Event loop STALLED for {gap:.1f}s! "
                    f"Thread pool may be exhausted. "
                    f"Active searches: {len(search_engine.active_searches) if search_engine else '?'}"
                )
            elif gap > 70:
                logger.warning(f"⚠️ Event loop slow tick: {gap:.1f}s")
            else:
                logger.info(f"⏱️ Event loop healthy (tick={gap:.1f}s)")
        except asyncio.CancelledError:
            raise


async def mongodb_watchdog():
    """Ping MongoDB every 5 minutes to detect stale connections and reconnect.

    Waits for DB to be initially connected before starting the ping loop.
    """
    # Wait until DB is connected for the first time
    while db_manager.db is None:
        await asyncio.sleep(5)

    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            if db_manager.db is not None:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: db_manager.client.admin.command("ping")
                )
                logger.info("🗄️ MongoDB watchdog ping OK")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"⚠️ MongoDB watchdog: connection lost ({e}) — reconnecting...")
            try:
                await db_manager.connect()
                logger.info("✅ MongoDB reconnected by watchdog")
            except Exception as re_err:
                logger.error(f"❌ MongoDB reconnect failed: {re_err}")
                # Don't raise — watchdog keeps running and retries next cycle


async def _run_bot():
    """Inner bot runner with auto-reconnect on disconnect"""
    global search_engine, admin_panel, bot_info, api_handler

    try:
        logger.info("🚀 Starting DarkBoxes Intelligence System...")

        # Start bot client
        await bot_client.start(bot_token=config.BOT_TOKEN)
        bot_info = await bot_client.get_me()
        logger.info(f"✅ Bot: @{bot_info.username}")

        # Start user client if configured
        if USE_USER_ACCOUNT:
            await user_client.connect()
            if not await user_client.is_user_authorized():
                print("[STARTUP] FATAL: User client not authorized. "
                      "Set USER_SESSION_STRING env var with a valid StringSession.", flush=True)
                logger.error("❌ User client not authorized — set USER_SESSION_STRING on Render")
                return
            logger.info("✅ User client ready")
        else:
            logger.info("ℹ️ Using bot client for all operations")

        # Connect to database
        if not await db_manager.connect():
            print("[STARTUP] FATAL: Database connection failed — check MONGODB_URI", flush=True)
            logger.error("❌ Database connection failed")
            return

        # Initialize admin panel
        admin_panel = AdminPanelHandler(db_manager, bot_client)

        # Initialize search engine
        search_engine = SearchEngine(db_manager, db_manager)

        # Initialize API handler
        logger.info("🔑 Initializing API handler...")
        api_handler = APIHandler(db_manager, search_engine)

        # Resolve groups
        logger.info("📡 Connecting to intelligence networks...")
        for group_name, group_data in GROUP_PRIORITIES.items():
            if group_data["enabled"]:
                try:
                    group_data["entity"] = await user_client.get_entity(group_data["identifier"])
                    logger.info(f"✅ Connected: {group_data['name']}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed: {group_data['name']} - {e}")

        # Register user_client incoming message handler
        # (handlers already registered globally via @user_client.on decorators below)

        logger.info("=" * 60)
        logger.info("🎭 DARK BOXES INTELLIGENCE SYSTEM - OPERATIONAL")
        logger.info("=" * 60)

        # Background tasks are started ONCE from main() — NOT here.
        # Restarting them on every reconnect causes task duplication/deadlock.
        await bot_client.run_until_disconnected()

    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
        raise
    except Exception as e:
        logger.error(f"💀 Fatal error: {e}")
        logger.error(traceback.format_exc())
        raise
    finally:
        try:
            await bot_client.disconnect()
            if USE_USER_ACCOUNT and user_client is not bot_client:
                await user_client.disconnect()
            if db_manager.client:
                db_manager.client.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════
# POLL BROADCAST
# ══════════════════════════════════════════════════
@bot_client.on(events.CallbackQuery(pattern=r"^admin_send_poll$"))
async def admin_send_poll_callback(event):
    """Admin initiates a poll broadcast."""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admins only", alert=True)
            return
        user_states[event.sender_id] = {"action": "admin_poll_question"}
        await event.edit(
            "> 📊 **Create a Poll**\n"
            "> \n"
            "> Step 1 of 2: Type your **poll question** and send it.",
            parse_mode="md",
            buttons=[[Button.inline("❌ Cancel", "admin_panel")]]
        )
    except Exception as e:
        logger.error(f"admin_send_poll_callback: {e}")


@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not (e.text or "").startswith("/")))
async def poll_question_handler(event):
    """Step 1: admin provides poll question."""
    try:
        uid = event.sender_id
        state = user_states.get(uid, {})
        if state.get("action") != "admin_poll_question":
            return
        question = (event.text or "").strip()
        if not question:
            return
        user_states[uid] = {"action": "admin_poll_options", "poll_question": question}
        await event.respond(
            f"**Poll question saved**\n"
            f"\n"
            f"> {question}\n"
            f"\n"
            f"Now send the answer options, **one per line** (2 to 10 options):\n"
            f"Example:\n`Yes\nNo\nMaybe`",
            parse_mode="md",
            buttons=[[Button.inline("Cancel", "admin_panel")]]
        )
    except Exception as e:
        logger.error(f"poll_question_handler: {e}")


@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not (e.text or "").startswith("/")))
async def poll_options_handler(event):
    """Step 2: admin provides options → send native Telegram poll to all users."""
    try:
        uid = event.sender_id
        state = user_states.get(uid, {})
        if state.get("action") != "admin_poll_options":
            return
        raw = (event.text or "").strip()
        options = [o.strip() for o in raw.split("\n") if o.strip()]
        if len(options) < 2:
            await event.respond("Please provide at least 2 options, one per line.")
            return
        options = options[:10]
        question = state["poll_question"]
        user_states.pop(uid, None)

        # Bots can only send polls via sendPoll API, not via Telethon MTProto directly
        # Use the Bot API (requests) to send polls to each user
        import aiohttp
        BOT_API = f"https://api.telegram.org/bot{config.BOT_TOKEN}"

        users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(db_manager.db.users.find({}, {"user_id": 1}))
        )

        sent = failed = 0
        poll_id = str(uuid.uuid4())[:10].upper()
        # Track poll: store question + options + per-user message ids for results
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.polls.insert_one({
                "poll_id": poll_id,
                "question": question,
                "options": options,
                "votes": {o: [] for o in options},  # option → [user_ids]
                "telegram_poll_ids": {},  # user_id → telegram poll id
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": uid,
            })
        )

        status_msg = await event.respond(f"Sending poll to {len(users)} users...")

        async with aiohttp.ClientSession() as session:
            for i, u in enumerate(users):
                try:
                    payload = {
                        "chat_id": u["user_id"],
                        "question": question,
                        "options": options,
                        "is_anonymous": False,  # NON-ANONYMOUS so admin can see who voted
                        "allows_multiple_answers": False,
                    }
                    async with session.post(f"{BOT_API}/sendPoll", json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        data = await resp.json()
                        if data.get("ok"):
                            tg_poll_id = data["result"]["poll"]["id"]
                            msg_id = data["result"]["message_id"]
                            await asyncio.get_running_loop().run_in_executor(
                                None, lambda pid=poll_id, uid2=u["user_id"], tpid=tg_poll_id, mid=msg_id:
                                    db_manager.db.polls.update_one(
                                        {"poll_id": pid},
                                        {"$set": {f"telegram_poll_ids.{uid2}": {"tg_poll_id": tpid, "msg_id": mid}}}
                                    )
                            )
                            sent += 1
                        else:
                            failed += 1
                    await asyncio.sleep(0.05)
                except Exception as _pe:
                    failed += 1
                # Progress update every 50 users
                if (i + 1) % 50 == 0:
                    try:
                        await bot_client.edit_message(uid, status_msg.id, f"Sending... {i+1}/{len(users)}")
                    except Exception:
                        pass

        await bot_client.edit_message(
            uid, status_msg.id,
            f"**Poll sent**\n"
            f"\n"
            f"> ID: `{poll_id}`\n"
            f"> Sent to {sent} users · {failed} failed\n"
            f"\n"
            f"Since the poll is non-anonymous, you can see who voted from Poll Results.",
            parse_mode="md",
            buttons=[
                [Button.inline(f"View Results: {poll_id}", f"poll_results_{poll_id}")],
                [Button.inline("Back to Admin", "admin_panel")],
            ]
        )
    except Exception as e:
        logger.error(f"poll_options_handler: {e}")
        await event.respond("Error sending poll. Check logs.")


@bot_client.on(events.CallbackQuery(pattern=r"^poll_results_(.+)$"))
async def poll_results_callback(event):
    """Show admin who voted for what in a poll."""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("Admins only", alert=True)
            return
        poll_id = event.pattern_match.group(1)
        if isinstance(poll_id, bytes): poll_id = poll_id.decode()

        poll_doc = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.polls.find_one({"poll_id": poll_id})
        )
        if not poll_doc:
            await event.answer("Poll not found", alert=True)
            return

        votes = poll_doc.get("votes", {})
        total_voters = sum(len(v) for v in votes.values())
        question = poll_doc.get("question", "?")

        lines = [f"**Poll Results**", "", f"> {question}", ""]
        for opt, voter_ids in votes.items():
            count = len(voter_ids)
            bar = "█" * count + "░" * max(0, 10 - count)
            vote_word = "votes" if count != 1 else "vote"
            lines.append(f"**{opt}** — {count} {vote_word}")
            if voter_ids:
                id_list = ", ".join(f"`{v}`" for v in voter_ids[:10])
                lines.append(f"> Voters: {id_list}")
            lines.append("")
        lines.append(f"Total votes received: {total_voters}")

        await event.edit(
            "\n".join(lines),
            parse_mode="md",
            buttons=[[Button.inline("Back to Admin", "admin_panel")]]
        )
    except Exception as e:
        logger.error(f"poll_results_callback: {e}")


@bot_client.on(events.Raw(types=[__import__("telethon.tl.types", fromlist=["UpdateMessagePoll"]).UpdateMessagePoll]))
async def poll_vote_handler(update):
    """Listen for poll votes and record who voted for what."""
    try:
        tg_poll_id = str(update.poll_id)
        results = update.results
        if not results or not results.results:
            return
        # Find poll in DB by telegram poll id
        poll_doc = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.polls.find_one(
                {f"telegram_poll_ids.{tg_poll_id}": {"$exists": True}}
            )
        )
        if not poll_doc:
            return
        options = poll_doc.get("options", [])
        for r in results.results:
            if r.chosen and r.option is not None:
                opt_idx = int(r.option) if r.option.isdigit() else 0
                if opt_idx < len(options):
                    opt_text = options[opt_idx]
                    # Voter ID comes from results.recent_voters if available
                    pass  # vote tracking via UpdateMessagePollVote below
    except Exception as e:
        logger.error(f"poll_vote_handler: {e}")




# ══════════════════════════════════════════════════
# DELETE BROADCAST
# ══════════════════════════════════════════════════
@bot_client.on(events.CallbackQuery(pattern=r"^del_broadcast_(.+)$"))
async def delete_broadcast_callback(event):
    """Delete a broadcast — remove messages from all users who received it."""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admins only", alert=True)
            return

        broadcast_id = event.pattern_match.group(1).decode() if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1)

        bc = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.broadcasts.find_one({"broadcast_id": broadcast_id})
        )

        if not bc:
            await event.answer("❌ Broadcast not found", alert=True)
            return

        if bc.get("deleted"):
            await event.answer("ℹ️ Already deleted", alert=True)
            return

        await event.answer("🗑 Deleting…")

        sent_msg_ids = bc.get("sent_msg_ids", {})  # {user_id_str: msg_id}
        deleted = failed = 0

        for uid_str, msg_id in sent_msg_ids.items():
            try:
                await bot_client.delete_messages(int(uid_str), [msg_id])
                deleted += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

        # Mark as deleted in DB
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.broadcasts.update_one(
                {"broadcast_id": broadcast_id},
                {"$set": {"deleted": True}}
            )
        )

        await event.edit(
            f"> 🗑 **Broadcast deleted**\n"
            f"> ID: `{broadcast_id}`\n"
            f"> Removed from {deleted} chats ({failed} failed)",
            parse_mode="md",
            buttons=[[Button.inline("« Broadcast History", "admin_broadcast_history"),
                      Button.inline("« Admin", "admin_panel")]]
        )
    except Exception as e:
        logger.error(f"delete_broadcast_callback: {e}")
        await event.answer("❌ Error deleting broadcast", alert=True)


# ══════════════════════════════════════════════════
# GROUP/COMMAND MANAGEMENT CALLBACKS
# ══════════════════════════════════════════════════

@bot_client.on(events.CallbackQuery(pattern=r'^admin_gcmd_vtypes$'))
async def admin_gcmd_vtypes_callback(event):
    """Show validity type chooser for all commands"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admins only", alert=True)
            return
        text = "🔧 **VALIDITY TYPES PER COMMAND**\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += "Tap a command to change its validity type:\n\n"
        for stype, cmd in SEARCH_COMMANDS.items():
            vtype = cmd.get("validity_type", "generic")
            text += f"• `{stype}` → `{vtype}`\n"
        buttons = [[Button.inline(f"✏️ {stype}", f"admin_gcmd_vtype_{stype}")] for stype in SEARCH_COMMANDS]
        buttons.append([Button.inline("« Back", "admin_group_cmd_mgmt")])
        await event.edit(text, buttons=buttons, parse_mode="md")
    except Exception as e:
        logger.error(f"admin_gcmd_vtypes_callback: {e}")
        await event.answer("❌ Error", alert=True)


@bot_client.on(events.CallbackQuery(pattern=r'^admin_setvtype_(.+)_(.+)$'))
async def admin_setvtype_callback(event):
    """Set validity type for a command"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admins only", alert=True)
            return
        raw = event.data.decode()
        # Format: admin_setvtype_<search_type>_<vtype>
        parts = raw[len("admin_setvtype_"):].rsplit("_", 1)
        if len(parts) != 2:
            await event.answer("❌ Invalid", alert=True)
            return
        search_type, vtype = parts
        if search_type not in SEARCH_COMMANDS or vtype not in VALIDITY_TYPES:
            await event.answer("❌ Unknown type", alert=True)
            return
        SEARCH_COMMANDS[search_type]["validity_type"] = vtype
        await event.answer(f"✅ {search_type} → {vtype}", alert=False)
        # Go back to validity types list
        text = "🔧 **VALIDITY TYPES PER COMMAND**\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for stype, cmd in SEARCH_COMMANDS.items():
            vt = cmd.get("validity_type", "generic")
            text += f"• `{stype}` → `{vt}`\n"
        buttons = [[Button.inline(f"✏️ {stype}", f"admin_gcmd_vtype_{stype}")] for stype in SEARCH_COMMANDS]
        buttons.append([Button.inline("« Back", "admin_group_cmd_mgmt")])
        await event.edit(text, buttons=buttons, parse_mode="md")
    except Exception as e:
        logger.error(f"admin_setvtype_callback: {e}")
        await event.answer("❌ Error", alert=True)


# ══════════════════════════════════════════════════
# RESTRICT MENU BUTTONS (Admin disables search types)
# ══════════════════════════════════════════════════
@bot_client.on(events.CallbackQuery(pattern=r"^admin_restrict_buttons$"))
async def admin_restrict_buttons_callback(event):
    """Show admin the button restriction panel."""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admins only", alert=True)
            return

        disabled = set(await asyncio.get_running_loop().run_in_executor(
            None, lambda: (db_manager.db.settings.find_one({"_id": "disabled_buttons"}) or {}).get("keys", [])
        ))

        all_buttons = [
            ("phone", "📱 Phone"), ("family", "👨‍👩‍👧 Family"),
            ("aadhar", "🆔 ID"), ("vehicle", "🚗 Vehicle"),
            ("telegram", "📲 Telegram"), ("imei", "📱 IMEI"),
            ("gst", "🏢 GST"), ("insta", "📸 Instagram"),
            ("ip", "🌍 IP"), ("ifsc", "🏦 IFSC"),
        ]

        btns = []
        for key, label in all_buttons:
            status = "🔴 OFF" if key in disabled else "🟢 ON"
            btns.append([Button.inline(f"{label}  [{status}]", f"toggle_btn_{key}")])
        btns.append([Button.inline("« Admin Panel", "admin_panel")])

        await event.edit(
            "> ⚙️ **Menu Button Control**\n"
            "> Tap a button to toggle it ON/OFF for all users.",
            parse_mode="md",
            buttons=btns
        )
    except Exception as e:
        logger.error(f"admin_restrict_buttons_callback: {e}")


@bot_client.on(events.CallbackQuery(pattern=r"^toggle_btn_(.+)$"))
async def toggle_button_callback(event):
    """Toggle a search button on or off."""
    try:
        if not admin_panel.is_admin(event.sender_id):
            await event.answer("❌ Admins only", alert=True)
            return

        key = event.pattern_match.group(1).decode() if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1)

        doc = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.settings.find_one({"_id": "disabled_buttons"})
        )
        disabled = set(doc.get("keys", []) if doc else [])

        if key in disabled:
            disabled.remove(key)
            action = "enabled"
        else:
            disabled.add(key)
            action = "disabled"

        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.settings.update_one(
                {"_id": "disabled_buttons"},
                {"$set": {"keys": list(disabled)}},
                upsert=True
            )
        )

        await event.answer(f"✅ {key} {action}")
        # Refresh the panel
        await admin_restrict_buttons_callback(event)
    except Exception as e:
        logger.error(f"toggle_button_callback: {e}")


async def _safe_task(coro_fn, name: str):
    """Wrap a background coroutine so crashes are logged and it auto-restarts."""
    while True:
        try:
            await coro_fn()
        except asyncio.CancelledError:
            logger.info(f"🛑 Background task '{name}' cancelled cleanly")
            return  # clean shutdown — do NOT restart
        except Exception as _e:
            logger.error(f"❌ Background task '{name}' crashed: {_e} — restarting in 10s")
            await asyncio.sleep(10)


async def main():
    """Main entry point.

    Background tasks (web server, keepalive, watchdog, cleanup) are started
    ONCE here and live for the entire process lifetime.

    Only the Telegram connection (_run_bot) is restarted on disconnect.
    This prevents the task-duplication bug where every reconnect spawned a
    duplicate set of background workers that then deadlocked the event loop.
    """
    # ── Start web server FIRST so Render's port scan passes ─────────────
    # start_web_server binds the port synchronously before returning,
    # so by the time _run_bot() starts, port 10000 is already open.
    web_task = asyncio.create_task(_safe_task(start_web_server, "start_web_server"), name="start_web_server")
    # Give the web server up to 15 seconds to bind (Render health check window)
    for _ in range(75):
        if _WEB_SERVER_STARTED:
            break
        await asyncio.sleep(0.2)
    if _WEB_SERVER_STARTED:
        logger.info(f"✅ Web server bound on port {config.PORT} — starting bot")
    else:
        logger.warning("⚠️ Web server did not bind within 15s — continuing anyway")

    # ── Start all other background tasks ONCE ────────────────────────────
    bg_task_fns = [
        (cleanup_expired_searches,  "cleanup_expired_searches"),
        (daily_subscription_reset,  "daily_subscription_reset"),
        (memory_monitor,            "memory_monitor"),
        (telegram_keepalive,        "telegram_keepalive"),
        (mongodb_watchdog,          "mongodb_watchdog"),
        (event_loop_watchdog,       "event_loop_watchdog"),
        (render_self_ping,          "render_self_ping"),
    ]
    bg_tasks = [web_task] + [
        asyncio.create_task(_safe_task(fn, name), name=name)
        for fn, name in bg_task_fns
    ]
    logger.info(f"✅ Started {len(bg_tasks)} background tasks")

    try:
        # ── Reconnect loop — only restarts the Telegram connection ────────
        while True:
            try:
                await _run_bot()
                logger.info("🔄 Telegram disconnected — reconnecting in 5 seconds...")
            except KeyboardInterrupt:
                logger.info("🛑 Shutting down by user request.")
                break
            except Exception as e:
                logger.error(f"🔄 _run_bot error: {e} — retrying in 5 seconds...")
            await asyncio.sleep(5)
    finally:
        # ── Cancel all background tasks cleanly on exit ───────────────────
        logger.info("🛑 Cancelling background tasks...")
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        logger.info("🛑 All background tasks stopped")

if __name__ == "__main__":
    import concurrent.futures

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # ── Bounded thread pool for run_in_executor calls ─────────────────────
    # The default executor is unbounded — under load, 157 run_in_executor
    # calls (all sync PyMongo ops) spawn unlimited threads, starving the event
    # loop and causing the bot to freeze while still "alive" to Render.
    # 20 threads is enough for all concurrent DB ops without overwhelming a
    # Render free-tier container.
    _executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=20,
        thread_name_prefix="db-worker"
    )

    loop = asyncio.new_event_loop()
    loop.set_default_executor(_executor)
    asyncio.set_event_loop(loop)

    print("[STARTUP] Event loop ready with bounded 20-thread executor", flush=True)

    try:
        loop.run_until_complete(main())
    finally:
        _executor.shutdown(wait=False)
        loop.close()
