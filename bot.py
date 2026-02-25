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
    
    # User account (for relaying)
    USER_API_ID: int = int(os.getenv("USER_API_ID", "0"))
    USER_API_HASH: str = os.getenv("API_HASH", "").strip()
    USER_PHONE: str = os.getenv("USER_PHONE", "").strip()
    USER_SESSION_FILE: str = "relay_session.session"
    
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
    NEW_USER_CREDITS: int = int(os.getenv("NEW_USER_CREDITS", "0"))
    REFERRAL_REWARD: int = int(os.getenv("REFERRAL_REWARD", "1"))
    
    # Payment
    UPI_ID: str = os.getenv("UPI_ID", "durgeshraihero@oksbi")
    ADMIN_CONTACT: str = "@darkboxesAdmin"
    
    # API Configuration
    API_ENABLED: bool = bool(os.getenv("API_ENABLED", "True"))
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_RATE_LIMIT: int = int(os.getenv("API_RATE_LIMIT", "100"))
    API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", secrets.token_hex(32))
    API_BASE_URL: str = os.getenv("API_BASE_URL", "https://relay-wzlz.onrender.com")

config = BotConfig()

# ================== LOGGING SETUP ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("darkboxes.log", encoding="utf-8")
    ]
)

logger = logging.getLogger("DarkBoxes")

# ================== VALIDATION ==================

def validate_config() -> bool:
    """Validate all required configuration"""
    errors = []
    
    required_configs = [
        ("BOT_API_ID", config.BOT_API_ID, lambda x: x != 0),
        ("BOT_API_HASH", config.BOT_API_HASH, lambda x: len(x) > 0),
        ("BOT_TOKEN", config.BOT_TOKEN, lambda x: len(x) > 0),
        ("ADMIN_USER_ID", config.ADMIN_USER_ID, lambda x: x != 0),
        ("MONGODB_URI", config.MONGODB_URI, lambda x: len(x) > 0),
    ]
    
    for name, value, validator in required_configs:
        if not validator(value):
            errors.append(f"{name} is not properly configured")
    
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  {error}")
        return False
    
    return True

if not validate_config():
    sys.exit(1)

USE_USER_ACCOUNT = config.USER_API_ID != 0 and config.USER_API_HASH and config.USER_PHONE

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
        "identifier": "RAJIV_THE_LOOKUP_HUB",
        "timeout": 30,
        "weight": 10,
        "enabled": True,
        "entity": None
    },
    "secondary": {
        "name": "🌐 IntelX Network",
        "identifier": "IntelXGroup",
        "timeout": 35,
        "weight": 7,
        "enabled": True,
        "entity": None
    },
    "tertiary": {
        "name": "🔍 Basic Database",
        "identifier": "OsintInformationGroup",
        "timeout": 40,
        "weight": 5,
        "enabled": True,
        "entity": None
    },
    "advanced": {
        "name": "🚀 Advanced OSINT Engine",
        "identifier": "IntelXGroup",  # Replace with your advanced group ID
        "timeout": 25,
        "weight": 15,
        "enabled": True,
        "entity": None,
        "leak_command": "/leak"
    }
}

# Sort groups by weight (priority)
DESTINATION_GROUPS = sorted(
    [group for group in GROUP_PRIORITIES.values() if group["enabled"]],
    key=lambda x: x["weight"],
    reverse=True
)

# ================== SUBSCRIPTION PLANS ==================

SUBSCRIPTION_PLANS = {
    # ── Credit packs (one-time top-up, credits never expire) ──────────────
    "credits_5": {
        "name": "⚡ STARTER PACK",
        "price": 100,
        "searches": 5,
        "validity": "No expiry",
        "validity_days": 0,
        "daily_limit": 0,
        "plan_type": "credit",
        "features": ["5 Premium Searches", "All Databases", "Credits Never Expire", "Email Support"],
        "icon": "⚡",
        "color": "#27AE60",
        "for": "Quick one-off lookups"
    },
    "credits_15": {
        "name": "🔍 EXPLORER PACK",
        "price": 250,
        "searches": 15,
        "validity": "No expiry",
        "validity_days": 0,
        "daily_limit": 0,
        "plan_type": "credit",
        "features": ["15 Premium Searches", "All Databases", "Credits Never Expire", "Priority Support"],
        "icon": "🔍",
        "color": "#3498DB",
        "for": "Regular occasional users"
    },
    # ── Daily-limit subscriptions (30 days) ───────────────────────────────
    "daily10_30": {
        "name": "🚀 DAILY 10 — 30 Days",
        "price": 800,
        "searches": 10,
        "validity": "30 days",
        "validity_days": 30,
        "daily_limit": 10,
        "plan_type": "subscription",
        "features": ["10 Searches/Day", "30-Day Access", "All Databases", "Priority Support", "Auto daily reset"],
        "icon": "🚀",
        "color": "#F39C12",
        "for": "Regular daily researchers"
    },
    "daily20_30": {
        "name": "💎 DAILY 20 — 30 Days",
        "price": 1000,
        "searches": 20,
        "validity": "30 days",
        "validity_days": 30,
        "daily_limit": 20,
        "plan_type": "subscription",
        "features": ["20 Searches/Day", "30-Day Access", "All Databases", "24/7 Priority Support", "Auto daily reset"],
        "icon": "💎",
        "color": "#9B59B6",
        "for": "Power users needing high volume"
    },
    # ── Daily-limit subscriptions (60 days) ───────────────────────────────
    "daily10_60": {
        "name": "🌟 DAILY 10 — 2 Months",
        "price": 1500,
        "searches": 10,
        "validity": "60 days",
        "validity_days": 60,
        "daily_limit": 10,
        "plan_type": "subscription",
        "features": ["10 Searches/Day", "60-Day Access", "All Databases", "Priority Support", "Best value monthly"],
        "icon": "🌟",
        "color": "#E74C3C",
        "for": "Long-term regular researchers"
    },
    "daily20_60": {
        "name": "👑 DAILY 20 — 2 Months",
        "price": 1800,
        "searches": 20,
        "validity": "60 days",
        "validity_days": 60,
        "daily_limit": 20,
        "plan_type": "subscription",
        "features": ["20 Searches/Day", "60-Day Access", "All Databases", "24/7 VIP Support", "Best value high-volume"],
        "icon": "👑",
        "color": "#F39C12",
        "for": "Professional investigators & teams"
    }
}

# ================== SEARCH COMMANDS WITH PRIORITY ==================

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Intelligence",
        "description": "📊 **Complete Mobile Intelligence**\n\n🔸 **Input:** 10-digit Indian mobile number\n🔸 **Returns:** Full name • Father's name • Aadhar ID • Complete address • Alternate numbers\n🔸 **Sources:** Government databases • Telecom records • Public directories\n🔸 **Confidence:** 98% accurate",
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
        "description": "🏠 **Complete Family Analysis**\n\n🔸 **Input:** 12-digit Aadhar number\n🔸 **Returns:** All family members • Names • Relations • Ages • Addresses\n🔸 **Sources:** UIDAI database • Family registration • Government records\n🔸 **Depth:** 3-level relationship mapping",
        "commands": ["/familyinfo", "/familyinfo"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "cost": 1,
        "priority": "primary",
        "icon": "👨‍👩‍👧‍👦",
        "category": "identity"
    },
    "aadhar": {
        "name": "🆔 Aadhar Comprehensive",
        "description": "📈 **Complete Aadhar Cross-Reference**\n\n🔸 **Input:** 12-digit Aadhar number\n🔸 **Returns:** All linked numbers • Bank accounts • Addresses • Biometric status • Registration history\n🔸 **Sources:** UIDAI • Bank linkages • Government databases\n🔸 **Scope:** Pan-India coverage",
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
        "commands": ["/vehicle", "/vnum", "/rc"],
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
        "description": "📊 **GST Business Comprehensive Analysis**\n\n🔸 **Input:** GST number\n🔸 **Returns:** Business details • Owner information • Financial patterns • Compliance status • Tax history\n🔸 **Sources:** Government registries • Financial databases • Corporate records\n🔸 **Verification:** GST portal integration",
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
        """Format search result with premium styling"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        icon = cmd.get("icon", "✅")
        name = cmd.get("name", "Search Result")
        
        # Header
        result = f"{icon} **{name}**\n"
        result += f"🔍 **Query:** `{query}`\n"
        result += f"📊 **Source:** {source}\n"
        result += "─" * 40 + "\n\n"
        
        # Content
        if not content or len(content.strip()) < 30:
            content = "🚫 No valid information found in the response.\n\n🔒 **Premium Notice:** This query may require higher subscription level or manual processing.\nContact @darkboxesAdmin for premium assistance."
        
        result += content + "\n\n"
        
        # Footer
        result += "─" * 40 + "\n"
        result += "⚡ **Powered by DarkBoxes Intelligence System**\n"
        result += "🔐 **Developed by** @darkboxesAdmin\n"
        result += "⚠️ **Confidential** - Authorized use only\n"
        result += f"🕒 {datetime.now().strftime('%I:%M %p | %d %b %Y')}"
        
        return result
    
    @staticmethod
    def format_welcome(user_name: str, user_data: Dict) -> str:
        """Format welcome message"""
        welcome = "🎭 **DARK BOXES INTELLIGENCE SYSTEM** 🎭\n\n"
        welcome += "╔══════════════════════════════════╗\n"
        welcome += f"║   WELCOME, {user_name.upper()}   ║\n"
        welcome += "╚══════════════════════════════════╝\n\n"
        
        welcome += "📈 **ACCOUNT OVERVIEW**\n"
        welcome += "├─ Available Credits: " + ("∞" if user_data.get('subscription') else str(user_data.get('searches_remaining', 0))) + "\n"
        welcome += f"├─ Total Searches: {user_data.get('total_searches', 0)}\n"
        welcome += f"├─ Referral Code: `{user_data.get('referral_code', 'N/A')}`\n"
        welcome += f"└─ Active Referrals: {user_data.get('referrals', 0)}\n\n"
        
        welcome += "🌟 **PREMIUM FEATURES**\n"
        welcome += "• 🔓 OSINT Database\n"
        welcome += "• 👑 Celebrity Information Network\n"
        welcome += "• 🌐 International Data Sources\n"
        welcome += "• ⚡ Priority Processing\n"
        welcome += "• 🔐 Encrypted Communication\n"
        welcome += "• 📊 Real-time Intelligence\n\n"
        
        welcome += "🛠️ **SELECT SERVICE**"
        
        return welcome
    
    @staticmethod
    def format_processing(search_type: str, query: str) -> str:
        """Format processing message"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        
        processing = "🔮 **INTELLIGENCE SCAN INITIATED**\n\n"
        processing += "╔══════════════════════════════════╗\n"
        processing += f"║   {cmd.get('icon', '🔍')} {cmd.get('name', 'Search').upper()}   ║\n"
        processing += "╚══════════════════════════════════╝\n\n"
        
        processing += "📡 **ACCESSING DATABASES**\n"
        processing += "├─ Query: `" + query + "`\n"
        processing += "├─ Priority: Premium Processing\n"
        processing += "├─ Estimated Time: 15-30 seconds\n"
        processing += "└─ Sources: Multiple intelligence feeds\n\n"
        
        processing += "🔄 **PROCESSING STAGES**\n"
        processing += "1️⃣ Data aggregation\n"
        processing += "2️⃣ Cross-reference verification\n"
        processing += "3️⃣ Pattern analysis\n"
        processing += "4️⃣ Report generation\n\n"
        
        processing += "⏳ Please wait while we gather intelligence..."
        
        return processing

# ================== TEXT PROCESSOR ==================

class TextProcessor:
    @staticmethod
    def is_processing_message(text: str) -> bool:
        """Check if message indicates processing"""
        if not text:
            return True
        
        text_lower = text.lower()
        keywords = [
            'processing', 'please wait', 'fetching', 'loading', 'searching',
            'retrieving', 'hold on', 'wait a moment', 'in progress',
            'gathering data', 'working on it', 'searching for',
            'please wait while', 'getting information', 'fetching data',
            'generating', 'creating report', 'file generated'
        ]
        
        return any(keyword in text_lower for keyword in keywords)
    
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
        """Check if message indicates no information found"""
        if not text:
            return False
        
        text_lower = text.lower()
        keywords = [
            'no info', 'no information', 'not found', 'no data', 'no result',
            'no record', 'invalid', 'doesn\'t exist', 'does not exist',
            'not available', 'no details', 'unable to find', 'could not find',
            'couldn\'t find', 'no match', 'not exist', 'no information found'
        ]
        
        return any(keyword in text_lower for keyword in keywords)
    
    @staticmethod
    def clean_content(content: str, search_type: str = None) -> str:
        """Clean and format content"""
        if not content:
            return ""
        
        # Remove promotional content and personal information
        patterns = [
            r'https?://\S+',
            r'www\.\S+',
            r't\.me/\S+',
            r'@\w+',
            r'tg://\S+',
            r'powered by.*',
            r'developed by.*',
            r'created by.*',
            r'designed by.*',
            r'©.*',
            r'copyright.*',
            r'join.*channel',
            r'subscribe.*',
            r'follow.*',
            r'contact.*admin',
            r'admin.*@\w+',
            r'auto-delete.*',
            r'file generated.*',
            r'report_.*\.txt',
            r'download.*file',
            r'click.*download',
            r'designed & powered.*',
            r'join.*@\w+',
            r'channel.*@\w+',
            r'username.*:.*@\w+',
            r'telegram.*:.*@\w+',
            r'@\w+.*bot',
            r'bot.*@\w+'
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        # Clean whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)
        
        return content.strip()
    
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
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.create_index([("api_key", 1)], unique=True)
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.create_index([("user_id", 1)])
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_logs.create_index([("timestamp", -1)])
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
    
    async def update_searches(self, user_id: int, search_type: str, query: str, success: bool = True) -> bool:
        """Update user search count and log search"""
        try:
            user = await self.get_user(user_id)
            if not user:
                return False
            
            # Check subscription first
            subscription = user.get("subscription")
            subscription_expiry = user.get("subscription_expiry")
            
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

                    # Log search
                    search_log = {
                        "user_id": user_id,
                        "search_type": search_type,
                        "query": query,
                        "success": success,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "credits_used": 0,
                        "subscription_used": subscription
                    }

                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: self.db.search_logs.insert_one(search_log)
                    )
                    return True
            
            # Use credits
            searches_remaining = user.get("searches_remaining", 0)
            if searches_remaining <= 0:
                return False
            
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
            
            # Log search
            search_log = {
                "user_id": user_id,
                "search_type": search_type,
                "query": query,
                "success": success,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "credits_used": credits_used,
                "subscription_used": None
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.search_logs.insert_one(search_log)
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error updating searches: {e}")
            return False
    
    async def add_subscription(self, user_id: int, plan_id: str, days: int) -> bool:
        """Add subscription to user"""
        try:
            plan = SUBSCRIPTION_PLANS[plan_id]
            expiry_date = datetime.now(timezone.utc) + timedelta(days=days)
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "subscription": plan_id,
                            "subscription_expiry": expiry_date.isoformat(),
                            "searches_remaining": 0  # Reset as unlimited
                        }
                    }
                )
            )
            
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
        """Add credits to user"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$inc": {"searches_remaining": credits}}
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error adding credits: {e}")
            return False

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
    def main_menu(is_admin: bool = False) -> List[List[Button]]:
        """Build keyboard with ONE COMMAND PER LINE"""
        buttons = []
        
        # Add each command in its own line
        # upi, email, pak, leak temporarily disabled
        commands_in_order = [
            "phone", "family", "aadhar", "vehicle",
            "telegram", "imei", "gst", "insta", "ip", "ifsc"
        ]
        
        for cmd_key in commands_in_order:
            if cmd_key in SEARCH_COMMANDS:
                cmd = SEARCH_COMMANDS[cmd_key]
                # Special emphasis for leak command
                if cmd_key == "leak":
                    button_text = f"🚀 ADVANCED OSINT TOOL"
                else:
                    button_text = f"{cmd['icon']} {cmd['name'].split()[1]}"
                buttons.append([Button.inline(button_text, f"search_{cmd_key}")])
        
        # Add action buttons in their own lines
        buttons.append([Button.inline("👤 Profile", "profile")])
        buttons.append([Button.inline("💎 Premium Plans", "premium")])
        buttons.append([Button.inline("📊 Refer & Earn", "referrals")])
        buttons.append([Button.inline("🆘 Support", "support")])
        buttons.append([Button.inline("🔑 API Access", "api_menu")])
        buttons.append([Button.inline("🔐 Login / Link Account", "login_account")])
        buttons.append([Button.inline("💻 Download Client Script", "download_client")])
        buttons.append([Button.inline("🗝️ Get My Login Credentials", "get_credentials")])
        
        # Add admin button if admin
        if is_admin:
            buttons.append([Button.inline("⚙️ Admin Panel", "admin_panel")])
        
        return buttons
    
    @staticmethod
    def subscription_plans() -> List[List[Button]]:
        """Premium plan selection — credit packs + subscriptions"""
        buttons = [
            # Credit packs
            [Button.inline("⚡ Starter Pack  · 5 searches · ₹100", "plan_credits_5")],
            [Button.inline("🔍 Explorer Pack · 15 searches · ₹250", "plan_credits_15")],
            # 30-day subscriptions
            [Button.inline("🚀 Daily 10 · 30 Days · ₹800", "plan_daily10_30")],
            [Button.inline("💎 Daily 20 · 30 Days · ₹1000", "plan_daily20_30")],
            # 60-day subscriptions
            [Button.inline("🌟 Daily 10 · 2 Months · ₹1500", "plan_daily10_60")],
            [Button.inline("👑 Daily 20 · 2 Months · ₹1800", "plan_daily20_60")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        return buttons
    
    @staticmethod
    def admin_panel() -> List[List[Button]]:
        """Professional admin panel with all features"""
        buttons = [
            [Button.inline("📊 Today's Stats", "admin_today")],
            [Button.inline("👥 User List & Management", "admin_users")],
            [Button.inline("🕐 Last Active Users", "admin_last_active")],
            [Button.inline("📈 Search Analytics", "admin_analytics")],
            [Button.inline("🔍 All Search Logs", "admin_search_logs")],
            [Button.inline("🔍 User Search Logs", "admin_user_search_logs")],
            [Button.inline("🕵️ Intent Monitor", "admin_intent_monitor")],
            [Button.inline("💰 Payment Stats", "admin_payments")],
            [Button.inline("⏳ Pending UTR Payments", "admin_pending_utr")],
            [Button.inline("💳 Pending Payments (Legacy)", "admin_pending_payments")],
            [Button.inline("🔍 Search Users", "admin_search_user")],
            [Button.inline("📢 Broadcast (Text)", "admin_broadcast")],
            [Button.inline("🖼️ Broadcast (Media)", "admin_broadcast_media")],
            [Button.inline("📋 Broadcast History", "admin_broadcast_history")],
            [Button.inline("⚙️ Bot Settings", "admin_settings")],
            [Button.inline("🚫 Ban/Unban User", "admin_ban")],
            [Button.inline("👑 Add/Remove Admin", "admin_admin")],
            [Button.inline("🎯 Add Credits to User", "admin_add_credits")],
            [Button.inline("💎 Give Subscription", "admin_give_subscription")],
            [Button.inline("📊 Export Data", "admin_export")],
            [Button.inline("🔑 API Panel", "admin_api")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        return buttons
    
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
                [Button.inline("⚡ Starter Pack (5 credits, ₹100)", f"grant_sub_{user_id}_credits_5")],
                [Button.inline("🔍 Explorer Pack (15 credits, ₹250)", f"grant_sub_{user_id}_credits_15")],
                [Button.inline("🚀 Daily 10 × 30d (₹800)", f"grant_sub_{user_id}_daily10_30")],
                [Button.inline("💎 Daily 20 × 30d (₹1000)", f"grant_sub_{user_id}_daily20_30")],
                [Button.inline("🌟 Daily 10 × 60d (₹1500)", f"grant_sub_{user_id}_daily10_60")],
                [Button.inline("👑 Daily 20 × 60d (₹1800)", f"grant_sub_{user_id}_daily20_60")],
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
                buttons.append([Button.inline(
                    f"👁️ {bc_id} — {seen} seen",
                    f"admin_broadcast_seen_{bc_id}"
                )])

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
            "`@johndoe daily10_30`\n"
            "`DB1A2B3C4D daily20_60`",
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
    """Handle API requests"""

    def __init__(self, db_manager: DatabaseManager, search_engine):
        self.db = db_manager
        self.search_engine = search_engine
    
    async def authenticate_request(self, request: web.Request) -> Tuple[bool, Optional[Dict], str]:
        """Authenticate API request"""
        try:
            # Get API key from header or query parameter
            api_key = request.headers.get('X-API-Key') or request.query.get('api_key')
            
            if not api_key:
                return False, None, "API key required"
            
            # Validate API key
            api_info = await self.db.api_db.get_api_key(api_key)
            if not api_info:
                return False, None, "Invalid API key"
            
            # Check if API key is active
            if not api_info.get("is_active", True):
                return False, None, "API key is inactive"
            
            # Check expiry
            expires_at = datetime.fromisoformat(api_info["expires_at"])
            if expires_at < datetime.now(timezone.utc):
                return False, None, "API key expired"
            
            # Check request limits (skip for unlimited plans)
            if not api_info.get("unlimited", False):
                if api_info.get("requests_remaining", 0) <= 0:
                    return False, None, "API request limit exceeded"
            
            return True, api_info, ""
            
        except Exception as e:
            logger.error(f"❌ API authentication error: {e}")
            return False, None, "Authentication failed"
    
    async def handle_search_request(self, request: web.Request, search_type: str) -> web.Response:
        """Handle search API request"""
        try:
            # Authenticate
            auth_result, api_info, error = await self.authenticate_request(request)
            if not auth_result:
                return web.json_response(
                    APIResponseFormatter.error(error, "AUTH_FAILED"),
                    status=401
                )
            
            # Parse request data
            data = await request.json()
            query = data.get("query", "").strip()
            
            if not query:
                return web.json_response(
                    APIResponseFormatter.error("Query parameter required", "INVALID_REQUEST"),
                    status=400
                )
            
            # Validate query
            cmd = SEARCH_COMMANDS.get(search_type, {})
            validation = cmd.get("validation")
            if validation and not re.match(validation, query):
                return web.json_response(
                    APIResponseFormatter.error(f"Invalid query format. Example: {cmd['example']}", "INVALID_QUERY"),
                    status=400
                )
            
            # Get user info
            user_id = api_info["user_id"]
            user_doc = await self.db.get_user(user_id)
            
            if not user_doc:
                return web.json_response(
                    APIResponseFormatter.error("User not found", "USER_NOT_FOUND"),
                    status=404
                )
            
            # Check if user is banned
            if user_doc.get('is_banned'):
                return web.json_response(
                    APIResponseFormatter.error("Account banned", "ACCOUNT_BANNED"),
                    status=403
                )
            
            # Check if user has API access
            if not user_doc.get('has_api_access'):
                return web.json_response(
                    APIResponseFormatter.error("API access not enabled for this account", "API_ACCESS_DENIED"),
                    status=403
                )
            
            # Check API access expiry
            api_expiry = user_doc.get('api_expiry')
            if api_expiry:
                expiry_date = datetime.fromisoformat(api_expiry)
                if expiry_date < datetime.now(timezone.utc):
                    return web.json_response(
                        APIResponseFormatter.error("API access expired", "API_ACCESS_EXPIRED"),
                        status=403
                    )
            
            logger.info(f"🔍 API Search: {search_type} - {query} (User: {user_id}, API: {api_info['api_key'][:8]}...)")
            
            # Perform search
            result = await self.search_engine.perform_search(search_type, query, user_id)
            
            # Record API request
            await self.db.api_db.record_api_request(
                api_info["api_key"], 
                f"/api/v1/search/{search_type}", 
                result["success"]
            )
            
            if result["success"]:
                # Update user search count
                await self.db.update_searches(user_id, search_type, query, True)
                
                # Format response
                if search_type == "leak":
                    # Special handling for leak search
                    api_result = APIResponseFormatter.format_leak_result(
                        result.get("files", []),
                        query
                    )
                else:
                    # Regular search
                    api_result = APIResponseFormatter.format_search_result(
                        result.get("result", ""),
                        search_type,
                        query,
                        result.get("source", "Unknown")
                    )
                
                response_data = APIResponseFormatter.success(api_result, "Search completed")
                
                # Include raw content for non-leak searches
                if search_type != "leak" and result.get("has_file") and result.get("content"):
                    response_data["data"]["raw_content"] = result["content"]
                
                return web.json_response(response_data)
            else:
                await self.db.update_searches(user_id, search_type, query, False)
                return web.json_response(
                    APIResponseFormatter.error(result.get("error", "Search failed"), "SEARCH_FAILED"),
                    status=404
                )
            
        except json.JSONDecodeError:
            return web.json_response(
                APIResponseFormatter.error("Invalid JSON", "INVALID_JSON"),
                status=400
            )
        except Exception as e:
            logger.error(f"❌ API search error: {e}")
            return web.json_response(
                APIResponseFormatter.error("Internal server error", "INTERNAL_ERROR"),
                status=500
            )
    
    async def handle_batch_search(self, request: web.Request) -> web.Response:
        """Handle batch search API request"""
        try:
            # Authenticate
            auth_result, api_info, error = await self.authenticate_request(request)
            if not auth_result:
                return web.json_response(
                    APIResponseFormatter.error(error, "AUTH_FAILED"),
                    status=401
                )
            
            # Parse request data
            data = await request.json()
            searches = data.get("searches", [])
            
            if not searches or not isinstance(searches, list):
                return web.json_response(
                    APIResponseFormatter.error("Searches array required", "INVALID_REQUEST"),
                    status=400
                )
            
            if len(searches) > 10:  # Limit batch size
                return web.json_response(
                    APIResponseFormatter.error("Maximum 10 searches per batch", "BATCH_LIMIT_EXCEEDED"),
                    status=400
                )
            
            user_id = api_info["user_id"]
            user_doc = await self.db.get_user(user_id)
            
            if not user_doc:
                return web.json_response(
                    APIResponseFormatter.error("User not found", "USER_NOT_FOUND"),
                    status=404
                )
            
            # Check if user is banned
            if user_doc.get('is_banned'):
                return web.json_response(
                    APIResponseFormatter.error("Account banned", "ACCOUNT_BANNED"),
                    status=403
                )
            
            # Check if user has API access
            if not user_doc.get('has_api_access'):
                return web.json_response(
                    APIResponseFormatter.error("API access not enabled for this account", "API_ACCESS_DENIED"),
                    status=403
                )
            
            # Check API access expiry
            api_expiry = user_doc.get('api_expiry')
            if api_expiry:
                expiry_date = datetime.fromisoformat(api_expiry)
                if expiry_date < datetime.now(timezone.utc):
                    return web.json_response(
                        APIResponseFormatter.error("API access expired", "API_ACCESS_EXPIRED"),
                        status=403
                    )
            
            # Calculate total cost for limited plans
            if not api_info.get("unlimited", False):
                total_cost = 0
                for search in searches:
                    search_type = search.get("type")
                    if search_type in API_COMMANDS:
                        total_cost += API_COMMANDS[search_type].get("cost", 1)
                
                if api_info.get("requests_remaining", 0) < total_cost:
                    return web.json_response(
                        APIResponseFormatter.error(f"Insufficient API requests. Required: {total_cost}, Available: {api_info.get('requests_remaining', 0)}", "INSUFFICIENT_API_REQUESTS"),
                        status=402
                    )
            
            logger.info(f"🔍 API Batch Search: {len(searches)} queries (User: {user_id})")
            
            # Perform batch searches
            results = []
            successful_searches = 0
            
            for search in searches:
                search_type = search.get("type")
                query = search.get("query", "").strip()
                
                if not query or search_type not in SEARCH_COMMANDS:
                    results.append({
                        "type": search_type,
                        "query": query,
                        "success": False,
                        "error": "Invalid search type or query"
                    })
                    continue
                
                # Validate query
                cmd = SEARCH_COMMANDS[search_type]
                validation = cmd.get("validation")
                if validation and not re.match(validation, query):
                    results.append({
                        "type": search_type,
                        "query": query,
                        "success": False,
                        "error": f"Invalid format. Example: {cmd['example']}"
                    })
                    continue
                
                # Perform individual search
                result = await self.search_engine.perform_search(search_type, query, user_id)
                
                if result["success"]:
                    successful_searches += 1
                    await self.db.update_searches(user_id, search_type, query, True)
                    
                    # Format result
                    if search_type == "leak":
                        formatted = APIResponseFormatter.format_leak_result(
                            result.get("files", []),
                            query
                        )
                    else:
                        formatted = APIResponseFormatter.format_search_result(
                            result.get("result", ""),
                            search_type,
                            query,
                            result.get("source", "Unknown")
                        )
                    
                    results.append({
                        "type": search_type,
                        "query": query,
                        "success": True,
                        "data": formatted
                    })
                else:
                    await self.db.update_searches(user_id, search_type, query, False)
                    results.append({
                        "type": search_type,
                        "query": query,
                        "success": False,
                        "error": result.get("error", "Search failed")
                    })
            
            # Record API request
            await self.db.api_db.record_api_request(
                api_info["api_key"], 
                "/api/v1/search/batch", 
                successful_searches > 0
            )
            
            response_data = {
                "total_searches": len(searches),
                "successful": successful_searches,
                "failed": len(searches) - successful_searches,
                "results": results,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            return web.json_response(APIResponseFormatter.success(response_data, "Batch search completed"))
            
        except json.JSONDecodeError:
            return web.json_response(
                APIResponseFormatter.error("Invalid JSON", "INVALID_JSON"),
                status=400
            )
        except Exception as e:
            logger.error(f"❌ API batch search error: {e}")
            return web.json_response(
                APIResponseFormatter.error("Internal server error", "INTERNAL_ERROR"),
                status=500
            )
    
    async def handle_status_request(self, request: web.Request) -> web.Response:
        """Handle status API request"""
        try:
            # Authenticate
            auth_result, api_info, error = await self.authenticate_request(request)
            if not auth_result:
                return web.json_response(
                    APIResponseFormatter.error(error, "AUTH_FAILED"),
                    status=401
                )
            
            # Get API key info
            api_key = api_info["api_key"]
            
            # Get user info
            user_id = api_info["user_id"]
            user_doc = await self.db.get_user(user_id)
            
            status_data = {
                "api_key": api_key[:8] + "..." + api_key[-4:],  # Mask API key
                "plan": api_info.get("plan_id", "unknown"),
                "created_at": api_info.get("created_at"),
                "expires_at": api_info.get("expires_at"),
                "is_active": api_info.get("is_active", True),
                "requests": {
                    "total": api_info.get("total_requests", 0),
                    "used": api_info.get("requests_used", 0),
                    "remaining": api_info.get("requests_remaining", 999999) if api_info.get("unlimited") else api_info.get("requests_remaining", 0)
                },
                "limits": {
                    "rate_limit": api_info.get("rate_limit", 10),
                    "concurrent_limit": api_info.get("concurrent_limit", 1)
                },
                "unlimited": api_info.get("unlimited", False),
                "user": {
                    "id": user_id,
                    "username": user_doc.get("username") if user_doc else None,
                    "has_api_access": user_doc.get("has_api_access", False) if user_doc else False,
                    "api_plan": user_doc.get("api_plan") if user_doc else None,
                    "api_expiry": user_doc.get("api_expiry") if user_doc else None
                },
                "server": {
                    "status": "online",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "version": "2.0.0",
                    "base_url": config.API_BASE_URL
                }
            }
            
            # Record API request (status endpoint doesn't count against limit)
            await self.db.api_db.record_api_request(api_key, "/api/v1/status", True)
            
            return web.json_response(APIResponseFormatter.success(status_data, "API status retrieved"))
            
        except Exception as e:
            logger.error(f"❌ API status error: {e}")
            return web.json_response(
                APIResponseFormatter.error("Internal server error", "INTERNAL_ERROR"),
                status=500
            )
    
    async def handle_balance_request(self, request: web.Request) -> web.Response:
        """Handle balance API request"""
        try:
            # Authenticate
            auth_result, api_info, error = await self.authenticate_request(request)
            if not auth_result:
                return web.json_response(
                    APIResponseFormatter.error(error, "AUTH_FAILED"),
                    status=401
                )
            
            # Get user info
            user_id = api_info["user_id"]
            user_doc = await self.db.get_user(user_id)
            
            if not user_doc:
                return web.json_response(
                    APIResponseFormatter.error("User not found", "USER_NOT_FOUND"),
                    status=404
                )
            
            balance_data = {
                "user_id": user_id,
                "api_key": api_info["api_key"][:8] + "..." + api_info["api_key"][-4:],
                "api_plan": api_info.get("plan_id", "unknown"),
                "api_expires": api_info.get("expires_at"),
                "api_requests": {
                    "total": api_info.get("total_requests", 0),
                    "used": api_info.get("requests_used", 0),
                    "remaining": api_info.get("requests_remaining", 999999) if api_info.get("unlimited") else api_info.get("requests_remaining", 0)
                },
                "telegram_credits": user_doc.get("searches_remaining", 0),
                "total_searches": user_doc.get("total_searches", 0),
                "subscription": user_doc.get("subscription"),
                "subscription_expiry": user_doc.get("subscription_expiry"),
                "has_api_access": user_doc.get("has_api_access", False),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Record API request
            await self.db.api_db.record_api_request(
                api_info["api_key"], 
                "/api/v1/balance", 
                True
            )
            
            return web.json_response(APIResponseFormatter.success(balance_data, "Balance retrieved"))
            
        except Exception as e:
            logger.error(f"❌ API balance error: {e}")
            return web.json_response(
                APIResponseFormatter.error("Internal server error", "INTERNAL_ERROR"),
                status=500
            )
    
    async def handle_usage_request(self, request: web.Request) -> web.Response:
        """Handle usage API request"""
        try:
            # Authenticate
            auth_result, api_info, error = await self.authenticate_request(request)
            if not auth_result:
                return web.json_response(
                    APIResponseFormatter.error(error, "AUTH_FAILED"),
                    status=401
                )
            
            # Get API usage stats
            api_key = api_info["api_key"]
            
            # Get recent API logs
            recent_logs = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.api_logs.find(
                    {"api_key": api_key},
                    {"timestamp": 1, "endpoint": 1, "success": 1}
                ).sort("timestamp", -1).limit(50))
            )
            
            # Get daily usage for last 7 days
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            
            pipeline = [
                {"$match": {"api_key": api_key, "timestamp": {"$gte": seven_days_ago.isoformat()}}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$toDate": "$timestamp"}}},
                    "count": {"$sum": 1},
                    "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
                    "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}}
                }},
                {"$sort": {"_id": 1}}
            ]
            
            daily_usage = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.api_logs.aggregate(pipeline))
            )
            
            # Get endpoint usage
            endpoint_pipeline = [
                {"$match": {"api_key": api_key}},
                {"$group": {
                    "_id": "$endpoint",
                    "count": {"$sum": 1},
                    "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
                    "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}}
                }},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]
            
            endpoint_usage = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.api_logs.aggregate(endpoint_pipeline))
            )
            
            usage_data = {
                "api_key": api_key[:8] + "..." + api_key[-4:],
                "plan": api_info.get("plan_id", "unknown"),
                "total_requests": api_info.get("total_requests", 0),
                "requests_used": api_info.get("requests_used", 0),
                "requests_remaining": api_info.get("requests_remaining", 999999) if api_info.get("unlimited") else api_info.get("requests_remaining", 0),
                "created_at": api_info.get("created_at"),
                "expires_at": api_info.get("expires_at"),
                "daily_usage": daily_usage,
                "endpoint_usage": endpoint_usage,
                "recent_activity": recent_logs,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Record API request
            await self.db.api_db.record_api_request(api_key, "/api/v1/usage", True)
            
            return web.json_response(APIResponseFormatter.success(usage_data, "Usage data retrieved"))
            
        except Exception as e:
            logger.error(f"❌ API usage error: {e}")
            return web.json_response(
                APIResponseFormatter.error("Internal server error", "INTERNAL_ERROR"),
                status=500
            )

# ================== API SERVER ==================


class SearchEngine:
    def __init__(self, db_manager, user_manager):
        self.db = db_manager
        self.user_manager = user_manager
        self.active_searches = {}
        self.waiting_for_files = {}
        self.group_performance = {}
    
    async def perform_search(self, search_type: str, query: str, user_id: int) -> Dict:
        """Perform cascading search with priority management"""
        logger.info(f"🚀 Starting {search_type} search: {query} (User: {user_id})")
        
        # Check for leak search
        if search_type == "leak":
            return await self.perform_leak_search(query, user_id)
        
        # Get command priority
        cmd = SEARCH_COMMANDS.get(search_type, {})
        preferred_priority = cmd.get("priority", "primary")
        
        # Sort groups based on command priority and performance
        sorted_groups = self._get_priority_groups(preferred_priority)
        
        for group in sorted_groups:
            if not group.get("entity"):
                logger.warning(f"⚠️ Group {group['name']} not resolved")
                continue
            
            # Get appropriate command for this group
            command_list = cmd["commands"]
            primary_command = command_list[0]
            
            logger.info(f"📤 Trying {group['name']}: {primary_command} {query}")
            
            try:
                # Send message to group
                sent_msg = await user_client.send_message(group["entity"], f"{primary_command} {query}")
                
                # Create search tracking
                search_id = f"{user_id}_{int(time.time())}_{group['name']}"
                future = asyncio.get_running_loop().create_future()
                
                self.active_searches[search_id] = {
                    "user_id": user_id,
                    "future": future,
                    "start_time": time.time(),
                    "group": group,
                    "message_id": sent_msg.id,
                    "search_type": search_type,
                    "query": query,
                    "chat_id": group["entity"].id if hasattr(group["entity"], 'id') else str(group["entity"]),
                    "expecting_file": False,
                    "file_wait_start": None,
                    "priority": group["weight"]
                }
                
                # Wait for response
                try:
                    result = await asyncio.wait_for(future, timeout=group["timeout"])
                    
                    if result["success"]:
                        # Update group performance
                        self._update_group_performance(group["name"], True)
                        logger.info(f"✅ Success from {group['name']}")
                        return result
                    else:
                        self._update_group_performance(group["name"], False)
                        logger.info(f"⚠️ No result from {group['name']}, trying next...")
                        continue
                        
                except asyncio.TimeoutError:
                    self._update_group_performance(group["name"], False)
                    logger.info(f"⏱️ Timeout from {group['name']}")
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Error sending to {group['name']}: {e}")
                self._update_group_performance(group["name"], False)
                continue
        
        # All groups failed - notify admin and return user-friendly message
        logger.warning(f"⚠️ All groups failed for query: {query} (User: {user_id})")
        await self._notify_admin(user_id, search_type, query)
        
        return {
            "success": False,
            "error": f"🔍 **NO RESULTS FOUND**\n\nQuery: `{query}`\n\n⚠️ **Your query has been logged and escalated to our admin team.**\n\n📝 **What happens next:**\n• Admin will manually review your query\n• If data is available, you'll receive results within 24 hours\n• Check back or wait for admin response\n\n💎 **For faster results, try:**\n• Ensure correct format (e.g., phone with country code: 917204764637)\n• Use different search types\n• Upgrade to Premium for priority processing\n\nContact {config.ADMIN_CONTACT} for assistance."
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
            
            # Wait for response (5 seconds timeout for leak search)
            try:
                result = await asyncio.wait_for(future, timeout=10)  # Increased timeout to 10 seconds
                
                if result["success"]:
                    logger.info(f"✅ Advanced leak search successful")
                    return result
                else:
                    logger.info(f"⚠️ No result from advanced search")
                    return {
                        "success": False,
                        "error": "❌ No information found in our advanced databases.\n\n⚠️ **Note:** For phone searches, include country code (e.g., 917204764637)\n💎 **Try our premium sources for better results.**"
                    }
                    
            except asyncio.TimeoutError:
                logger.info(f"⏱️ Timeout from advanced search")
                return {
                    "success": False,
                    "error": "⏱️ **ADVANCED SEARCH TIMEOUT**\n\nOur advanced engine is processing your query.\nResults will be delivered shortly if available.\n\n⚠️ **For immediate results:**\n• Use specific search types (Phone, Email, etc.)\n• Ensure phone numbers include country code\n• Contact @darkboxesAdmin for premium support"
                }
                
        except Exception as e:
            logger.error(f"❌ Error in leak search: {e}")
            return {
                "success": False,
                "error": "❌ Advanced search engine error. Please try again or use specific search types."
            }
    
    def _get_priority_groups(self, preferred_priority: str) -> List:
        """Get groups sorted by priority and performance"""
        priority_order = ["primary", "secondary", "tertiary"]
        
        # Start with preferred priority group
        sorted_groups = []
        
        # Add preferred group first
        for group in DESTINATION_GROUPS:
            if group.get("name") == GROUP_PRIORITIES[preferred_priority]["name"]:
                sorted_groups.append(group)
                break
        
        # Add remaining groups by weight
        remaining_groups = [g for g in DESTINATION_GROUPS if g not in sorted_groups]
        remaining_groups.sort(key=lambda x: x["weight"], reverse=True)
        
        sorted_groups.extend(remaining_groups)
        return sorted_groups
    
    def _update_group_performance(self, group_name: str, success: bool):
        """Update group performance tracking"""
        if group_name not in self.group_performance:
            self.group_performance[group_name] = {"success": 0, "total": 0}
        
        self.group_performance[group_name]["total"] += 1
        if success:
            self.group_performance[group_name]["success"] += 1
    
    async def handle_incoming_message(self, event):
        """Handle incoming messages for search responses"""
        try:
            message = event.message
            
            # Check if this is a reply to our search
            if message.reply_to:
                reply_to_id = message.reply_to.reply_to_msg_id
                
                for search_id, search_info in list(self.active_searches.items()):
                    if reply_to_id == search_info["message_id"]:
                        await self._process_search_response(search_id, search_info, message)
                        return
            
            # Check for file messages in same chat
            for search_id, search_info in list(self.active_searches.items()):
                try:
                    chat_match = False
                    if hasattr(search_info["group"]["entity"], 'id'):
                        chat_match = event.chat_id == search_info["group"]["entity"].id
                    elif search_info.get("chat_id"):
                        chat_match = str(event.chat_id) == str(search_info["chat_id"])
                    
                    if chat_match:
                        file_check = await self._check_and_process_file(message, search_info)
                        if file_check is not None:
                            logger.info(f"📁 Found file in {search_info['group']['name']}")
                            await self._process_search_response(search_id, search_info, message)
                        return
                except:
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
            logger.info(f"📨 Processing message in {search_info['group']['name']}: {text[:100]}...")
            
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
                logger.info(f"⏳ Processing message, waiting...")
                return
            
            if TextProcessor.is_no_info_message(text):
                logger.info(f"🚫 No-info message")
                result = {"success": False}
            elif text and len(text.strip()) > 10:
                logger.info(f"📝 Processing text response")
                result = await self._process_text(text, search_info)
            else:
                logger.info(f"⚠️ Empty or short message, ignoring")
                return
            
            if search_id in self.active_searches:
                future = self.active_searches[search_id]["future"]
                if not future.done():
                    future.set_result(result)
                del self.active_searches[search_id]
                
        except Exception as e:
            logger.error(f"❌ Error processing search response: {e}")
    
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
        """Process text message"""
        cleaned = TextProcessor.clean_content(text, search_info["search_type"])
        
        if len(cleaned) < 20:
            return {"success": False}
        
        formatted = PremiumFormatter.format_result(
            cleaned,
            search_info["search_type"],
            search_info["query"],
            search_info["group"]["name"]
        )
        
        return {
            "success": True,
            "result": formatted,
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

async def start_web_server():
    """Start unified web server with API endpoints"""
    app = web.Application()
    
    # Health check endpoint
    async def health_check(request):
        return web.json_response({"status": "ok", "timestamp": datetime.now().isoformat()})
    
    # Basic routes
    app.router.add_get('/health', health_check)
    app.router.add_get('/api/v1/health', health_check)
    
    # Add API endpoints if enabled
    if config.API_ENABLED:
        logger.info("🔑 Adding API endpoints to web server...")
        
        # Create API handler
        api_handler = APIHandler(db_manager, search_engine)
        
        # Search endpoints
        async def phone_search(request):
            return await api_handler.handle_search_request(request, "phone")
        
        async def family_search(request):
            return await api_handler.handle_search_request(request, "family")
        
        async def aadhar_search(request):
            return await api_handler.handle_search_request(request, "aadhar")
        
        async def vehicle_search(request):
            return await api_handler.handle_search_request(request, "vehicle")
        
        async def upi_search(request):
            return await api_handler.handle_search_request(request, "upi")
        
        async def email_search(request):
            return await api_handler.handle_search_request(request, "email")
        
        async def telegram_search(request):
            return await api_handler.handle_search_request(request, "telegram")
        
        async def imei_search(request):
            return await api_handler.handle_search_request(request, "imei")
        
        async def gst_search(request):
            return await api_handler.handle_search_request(request, "gst")
        
        async def instagram_search(request):
            return await api_handler.handle_search_request(request, "insta")
        
        async def pakistan_search(request):
            return await api_handler.handle_search_request(request, "pak")
        
        async def ip_search(request):
            return await api_handler.handle_search_request(request, "ip")
        
        async def ifsc_search(request):
            return await api_handler.handle_search_request(request, "ifsc")
        
        async def leak_search(request):
            return await api_handler.handle_search_request(request, "leak")
        
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
        
        # Account management endpoints (no Telegram needed)
        async def register_endpoint(request):
            """Register new account with username + password (no Telegram needed)"""
            try:
                data = await request.json()
                username = (data.get("username") or "").strip()
                password = (data.get("password") or "").strip()

                if not username or not password:
                    return web.json_response(
                        {"status": "error", "message": "username and password required"},
                        status=400
                    )
                if len(password) < 6:
                    return web.json_response(
                        {"status": "error", "message": "password must be at least 6 characters"},
                        status=400
                    )
                if len(username) < 3:
                    return web.json_response(
                        {"status": "error", "message": "username must be at least 3 characters"},
                        status=400
                    )

                # Check if username already taken
                loop = asyncio.get_running_loop()
                existing = await loop.run_in_executor(
                    None, lambda: db_manager.db.accounts.find_one({"username": username.lower()})
                )
                if existing:
                    return web.json_response(
                        {"status": "error", "message": "Username already taken"},
                        status=409
                    )

                # Create account
                account_id = f"DB{secrets.token_hex(4).upper()}"
                pwd_hash = hashlib.sha256(password.encode()).hexdigest()

                new_account = {
                    "account_id": account_id,
                    "username": username.lower(),
                    "display_name": username,
                    "password_hash": pwd_hash,
                    "linked_tg_ids": [],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "searches_remaining": config.NEW_USER_CREDITS,
                    "subscription": None,
                    "subscription_expiry": None,
                    "is_banned": False,
                    "total_searches": 0,
                    "source": "client_registration"
                }

                await loop.run_in_executor(
                    None, lambda: db_manager.db.accounts.insert_one(new_account)
                )

                # Notify admin
                try:
                    await bot_client.send_message(
                        config.ADMIN_USER_ID,
                        f"🆕 **NEW CLIENT REGISTRATION**\n\n"
                        f"👤 Username: `{username}`\n"
                        f"🆔 Account ID: `{account_id}`\n"
                        f"🕐 Time: {datetime.now().strftime('%d %b %Y %H:%M')}\n"
                        f"📱 Source: Terminal Client (No Telegram)\n\n"
                        f"Starting credits: {config.NEW_USER_CREDITS}",
                        parse_mode="md"
                    )
                except Exception:
                    pass

                return web.json_response({
                    "status": "success",
                    "message": "Account created successfully",
                    "account_id": account_id,
                    "credits": config.NEW_USER_CREDITS,
                    "info": "Save your Account ID and password securely. "
                            "Contact @darkboxesAdmin or yadiify@gmail.com for support."
                })

            except Exception as e:
                logger.error(f"Register endpoint error: {e}")
                return web.json_response(
                    {"status": "error", "message": "Server error"},
                    status=500
                )

        async def auth_login_endpoint(request):
            """Authenticate with account_id/username + password, return API key"""
            try:
                data = await request.json()
                identifier = (data.get("account_id") or data.get("username") or "").strip()
                password = (data.get("password") or "").strip()

                if not identifier or not password:
                    return web.json_response(
                        {"status": "error", "message": "account_id/username and password required"},
                        status=400
                    )

                loop = asyncio.get_running_loop()
                pwd_hash = hashlib.sha256(password.encode()).hexdigest()

                # Find by account_id or username
                if identifier.upper().startswith("DB"):
                    account = await loop.run_in_executor(
                        None, lambda: db_manager.db.accounts.find_one(
                            {"account_id": identifier.upper()}
                        )
                    )
                else:
                    account = await loop.run_in_executor(
                        None, lambda: db_manager.db.accounts.find_one(
                            {"username": identifier.lower()}
                        )
                    )

                if not account:
                    return web.json_response(
                        {"status": "error", "message": "Account not found"},
                        status=404
                    )

                if account.get("password_hash") != pwd_hash:
                    return web.json_response(
                        {"status": "error", "message": "Incorrect password"},
                        status=401
                    )

                if account.get("is_banned"):
                    return web.json_response(
                        {"status": "error", "message": "Account banned. Contact @darkboxesAdmin"},
                        status=403
                    )

                account_id = account.get("account_id")
                credits = account.get("searches_remaining", 0)
                sub = account.get("subscription") or "None"

                # Generate or retrieve API key for this account
                existing_key = await loop.run_in_executor(
                    None, lambda: db_manager.db.api_keys.find_one(
                        {"account_id": account_id, "is_active": True}
                    )
                )

                if existing_key:
                    api_key = existing_key.get("api_key")
                else:
                    # Create a session API key
                    api_key = APIKeyManager.generate_api_key(0, f"client_{account_id}")
                    expiry = datetime.now(timezone.utc) + timedelta(days=365)
                    key_doc = {
                        "api_key": api_key,
                        "account_id": account_id,
                        "user_id": 0,
                        "plan_id": "client",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "expires_at": expiry.isoformat(),
                        "is_active": True,
                        "total_requests": 0,
                        "unlimited": False
                    }
                    await loop.run_in_executor(
                        None, lambda: db_manager.db.api_keys.insert_one(key_doc)
                    )

                # Update last_seen
                await loop.run_in_executor(
                    None, lambda: db_manager.db.accounts.update_one(
                        {"account_id": account_id},
                        {"$set": {"last_seen": datetime.now(timezone.utc).isoformat()}}
                    )
                )

                return web.json_response({
                    "status": "success",
                    "account_id": account_id,
                    "api_key": api_key,
                    "credits": credits,
                    "plan": sub,
                    "message": "Login successful"
                })

            except Exception as e:
                logger.error(f"Auth login endpoint error: {e}")
                return web.json_response(
                    {"status": "error", "message": "Server error"},
                    status=500
                )

        app.router.add_post('/api/v1/auth/register', register_endpoint)
        app.router.add_post('/api/v1/auth/login', auth_login_endpoint)

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
        
        # CORS middleware
        async def cors_middleware(app, handler):
            async def middleware_handler(request):
                if request.method == "OPTIONS":
                    response = web.Response()
                else:
                    response = await handler(request)
                
                response.headers['Access-Control-Allow-Origin'] = '*'
                response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key'
                return response
            return middleware_handler
        
        app.middlewares.append(cors_middleware)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.PORT)
    
    try:
        await site.start()
        logger.info(f"🌐 Web server running on port {config.PORT}")
        if config.API_ENABLED:
            logger.info(f"🔑 API endpoints available at {config.API_BASE_URL}/api/v1/")
            logger.info(f"📚 API Documentation: {config.API_BASE_URL}/api/v1/docs")
    except Exception as e:
        logger.error(f"❌ Web server failed: {e}")

# ================== GLOBAL VARIABLES ==================

bot_client = TelegramClient(config.BOT_SESSION_FILE, config.BOT_API_ID, config.BOT_API_HASH)
user_client = (
    TelegramClient(config.USER_SESSION_FILE, config.USER_API_ID, config.USER_API_HASH)
    if USE_USER_ACCOUNT
    else bot_client
)

db_manager = DatabaseManager()
search_engine = None
admin_panel = None
user_states = {}
bot_info = None
export_data_storage = {}

# ================== EVENT HANDLERS ==================

@bot_client.on(events.NewMessage(pattern=r'/start(?: (.+))?'))
async def start_handler(event):
    """Premium start handler"""
    try:
        user = await event.get_sender()
        user_id = user.id
        referral_code = event.pattern_match.group(1)
        
        # Check if user is banned
        user_doc = await db_manager.get_user(user_id)
        if user_doc and user_doc.get('is_banned'):
            await event.respond("🚫 Your account has been banned. Contact @darkboxesAdmin for assistance.")
            return
        
        # Get or create user
        if not user_doc:
            await db_manager.create_user(user_id, user.username, user.first_name, referral_code)
            user_doc = await db_manager.get_user(user_id)
            
            # Handle referral
            if referral_code and referral_code.isdigit():
                referrer_id = int(referral_code)
                referrer = await db_manager.get_user(referrer_id)
                if referrer:
                    await db_manager.add_referral_credit(referrer_id, config.REFERRAL_REWARD)
        
        is_admin = admin_panel.is_admin(user_id) if admin_panel else (user_id == config.ADMIN_USER_ID)
        
        # Send welcome message
        welcome_text = PremiumFormatter.format_welcome(user.first_name, user_doc)
        
        # Get keyboard - ONE COMMAND PER LINE
        buttons = OneLineKeyboard.main_menu(is_admin)
        
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
    """Handle search type selection"""
    try:
        user_id = event.sender_id
        search_type = event.data.decode().split('_', 1)[1]
        
        # Check if user is banned
        user_doc = await db_manager.get_user(user_id)
        if user_doc and user_doc.get('is_banned'):
            await event.answer("🚫 Your account has been banned.", alert=True)
            return
        
        if search_type not in SEARCH_COMMANDS:
            await event.answer("❌ Invalid selection", alert=True)
            return
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        # Check access — credit-based or daily-subscription
        can_search = False
        searches_remaining = user_doc.get('searches_remaining', 0)
        subscription = user_doc.get('subscription')
        subscription_expiry = user_doc.get('subscription_expiry')
        daily_limit = user_doc.get('subscription_daily_limit', 0)

        if subscription and subscription_expiry:
            try:
                expiry_date = datetime.fromisoformat(subscription_expiry)
                if expiry_date > datetime.now(timezone.utc):
                    # Active subscription — check daily limit
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    reset_date = user_doc.get("subscription_reset_date", "")
                    used_today = user_doc.get("subscription_used_today", 0)

                    if reset_date != today_str:
                        # New day — reset counter
                        await asyncio.get_running_loop().run_in_executor(
                            None, lambda: db_manager.db.users.update_one(
                                {"user_id": user_id},
                                {"$set": {"subscription_used_today": 0, "subscription_reset_date": today_str}}
                            )
                        )
                        used_today = 0

                    if daily_limit == 0 or used_today < daily_limit:
                        can_search = True
                    else:
                        await event.edit(
                            f"⏰ **DAILY LIMIT REACHED**\n\n"
                            f"You've used all {daily_limit} searches for today.\n"
                            f"Your limit resets at midnight UTC.\n\n"
                            f"📅 Subscription valid until: {expiry_date.strftime('%d %b %Y')}\n"
                            f"📊 Used today: {used_today}/{daily_limit}\n\n"
                            f"Need more? Get a higher plan or credit pack:",
                            buttons=OneLineKeyboard.subscription_plans(),
                            parse_mode="md"
                        )
                        return
            except Exception:
                pass

        if not can_search and searches_remaining <= 0:
            await event.edit(
                "🔒 **NO CREDITS REMAINING**\n\n"
                "You have 0 search credits. Choose a plan to continue:\n\n"
                "⚡ **Starter Pack** — ₹100 → 5 searches\n"
                "🔍 **Explorer Pack** — ₹250 → 15 searches\n"
                "🚀 **Daily 10/30d** — ₹800/month\n"
                "💎 **Daily 20/30d** — ₹1,000/month\n"
                "🌟 **Daily 10/60d** — ₹1,500/2 months\n"
                "👑 **Daily 20/60d** — ₹1,800/2 months\n\n"
                "📞 Issues? Message **@darkboxesAdmin**",
                buttons=OneLineKeyboard.subscription_plans(),
                parse_mode="md"
            )
            return
        
        cmd = SEARCH_COMMANDS[search_type]
        
        # Special formatting for leak search
        if search_type == "leak":
            leak_text = (
                f"🚀 **ADVANCED OSINT TOOL - SEARCH ANYTHING**\n\n"
                f"{cmd['description']}\n\n"
                f"⚡ **ULTRA-FAST PROCESSING** (5 seconds)\n"
                f"💎 **Cost:** {cmd['cost']} credits\n"
                f"📁 **Returns:** JSON + TXT files\n"
                f"🌐 **Best For:** Phone numbers with country code (e.g., 917204764637)\n\n"
                f"📝 **Enter your query below:**\n"
                f"(Email, Phone with country code, Name, Document, Username, etc.)"
            )
            
            await event.edit(
                leak_text,
                buttons=OneLineKeyboard.cancel_button(),
                parse_mode="md"
            )
        else:
            await event.edit(
                f"{cmd['icon']} **{cmd['name']}**\n\n"
                f"{cmd['description']}\n\n"
                f"⚡ **Cost:** {cmd['cost']} credit{'s' if cmd['cost'] > 1 else ''}\n"
                f"📝 **Example:** `{cmd['example']}`\n\n"
                f"Enter your query below:",
                buttons=OneLineKeyboard.cancel_button(),
                parse_mode="md"
            )
        
        user_states[user_id] = {"action": "search", "type": search_type}
        
    except Exception as e:
        logger.error(f"❌ Error in search_callback: {e}")
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^profile$'))
async def profile_callback(event):
    """Handle profile callback"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        # Format profile
        profile_text = (
            f"👤 **USER PROFILE**\n"
            f"═══════════════════════\n\n"
            f"📋 **Personal Information**\n"
            f"├─ Name: {user_doc.get('first_name', 'N/A')}\n"
            f"├─ Username: @{user_doc.get('username', 'N/A')}\n"
            f"├─ User ID: `{user_id}`\n"
            f"├─ Joined: {user_doc.get('joined_at', 'N/A')[:10]}\n"
            f"└─ Last Seen: {user_doc.get('last_seen', 'N/A')[:16]}\n\n"
        )
        
        # Credits and subscription
        profile_text += f"💰 **Account Status**\n"
        
        if user_doc.get('subscription') and user_doc.get('subscription_expiry'):
            expiry_date = datetime.fromisoformat(user_doc['subscription_expiry'])
            days_left = (expiry_date - datetime.now(timezone.utc)).days
            
            if days_left > 0:
                profile_text += f"├─ Subscription: {user_doc['subscription']}\n"
                profile_text += f"├─ Status: Active ({days_left} days left)\n"
                profile_text += f"└─ Searches: Unlimited\n\n"
            else:
                profile_text += f"├─ Credits: {user_doc.get('searches_remaining', 0)}\n"
                profile_text += f"└─ Subscription: Expired\n\n"
        else:
            profile_text += f"├─ Credits: {user_doc.get('searches_remaining', 0)}\n"
            profile_text += f"└─ Subscription: None\n\n"
        
        # Statistics
        profile_text += f"📊 **Statistics**\n"
        profile_text += f"├─ Total Searches: {user_doc.get('total_searches', 0)}\n"
        profile_text += f"├─ Successful: {user_doc.get('total_searches', 0) - user_doc.get('failed_searches', 0)}\n"
        profile_text += f"├─ Referral Code: `{user_doc.get('referral_code', 'N/A')}`\n"
        profile_text += f"├─ Referrals: {user_doc.get('referrals', 0)}\n"
        profile_text += f"└─ Referral Credits: {user_doc.get('referral_credits', 0)}\n\n"
        
        # Referral link
        referral_link = f"https://t.me/{bot_info.username}?start={user_doc.get('referral_code')}"
        profile_text += f"📢 **Referral Link**\n"
        profile_text += f"🔗 {referral_link}\n\n"
        profile_text += f"💎 **Earn 1 credit for each successful referral!**"
        
        await event.edit(
            profile_text,
            buttons=OneLineKeyboard.profile_menu(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in profile_callback: {e}")
        await event.answer("❌ Error loading profile", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^premium$'))
async def premium_callback(event):
    """Handle premium plans callback"""
    try:
        premium_text = (
            "💎 **DARKBOXES PLANS & PRICING**\n"
            "═══════════════════════\n\n"
            "━━ 🎟️ CREDIT PACKS (Never Expire) ━━\n\n"
            "⚡ **STARTER PACK** — ₹100\n"
            "└─ 5 searches (any time, no expiry)\n\n"
            "🔍 **EXPLORER PACK** — ₹250\n"
            "└─ 15 searches (any time, no expiry)\n\n"
            "━━ 📅 30-DAY SUBSCRIPTIONS ━━\n\n"
            "🚀 **DAILY 10** — ₹800/month\n"
            "└─ 10 searches/day × 30 days\n\n"
            "💎 **DAILY 20** — ₹1,000/month\n"
            "└─ 20 searches/day × 30 days\n\n"
            "━━ 📅 2-MONTH SUBSCRIPTIONS ━━\n\n"
            "🌟 **DAILY 10** — ₹1,500/2 months\n"
            "└─ 10 searches/day × 60 days\n\n"
            "👑 **DAILY 20** — ₹1,800/2 months\n"
            "└─ 20 searches/day × 60 days\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💳 **UPI ID:** `durgeshraihero@oksbi`\n"
            "📞 **Support:** @darkboxesAdmin\n\n"
            "👇 Select a plan to pay via screenshot:"
        )
        
        await event.edit(
            premium_text,
            buttons=OneLineKeyboard.subscription_plans(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in premium_callback: {e}")
        await event.answer("❌ Error loading premium plans", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^plan_(.+)$'))
async def plan_selection_callback(event):
    """Handle plan selection - guides user through payment + screenshot flow"""
    try:
        plan_id = event.data.decode().split('_', 1)[1]

        if plan_id not in SUBSCRIPTION_PLANS:
            await event.answer("❌ Invalid plan selection", alert=True)
            return

        plan = SUBSCRIPTION_PLANS[plan_id]
        user_id = event.sender_id

        # Build search description based on plan type
        plan_type = plan.get("plan_type", "credit")
        daily_limit = plan.get("daily_limit", 0)
        if plan_type == "subscription" and daily_limit > 0:
            search_desc = f"{plan['searches']} searches/day"
        else:
            search_desc = f"{plan['searches']} searches (never expire)"

        plan_details = (
            f"{plan['icon']} **{plan['name']}**\n"
            f"═══════════════════════\n\n"
            f"💰 **Price:** ₹{plan['price']}\n"
            f"🔍 **Searches:** {search_desc}\n"
            f"📅 **Validity:** {plan['validity']}\n\n"
            f"🌟 **Features:**\n"
        )
        for feature in plan['features']:
            plan_details += f"• {feature}\n"

        plan_details += (
            f"\n🎯 **Perfect For:** {plan['for']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💳 **HOW TO PURCHASE:**\n\n"
            f"1️⃣ Pay ₹{plan['price']} via UPI:\n"
            f"   🔗 `{config.UPI_ID}`\n\n"
            f"2️⃣ Note your **UTR / Transaction Reference Number**\n"
            f"   (shown in your UPI app after payment)\n\n"
            f"3️⃣ Tap **Submit UTR Number** below — admin will verify manually\n"
            f"   Your ID (auto-included): `{user_id}`\n\n"
            f"⏱️ Activation within **5–15 minutes** after admin verifies\n"
            f"❓ Issues? Message **@darkboxesAdmin** or email **yadiify@gmail.com**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        buttons = [
            [Button.inline(f"📤 Submit UTR / Transaction No", f"submit_payment_{plan_id}")],
            [Button.inline("« Back to Plans", "premium")],
            [Button.inline("« Main Menu", "main_menu")]
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
            f"🏦 **ENTER UTR / TRANSACTION NUMBER**\n\n"
            f"Plan: **{plan['name']}** — ₹{plan['price']}\n\n"
            f"After completing your UPI payment, type the **UTR number** or "
            f"**Transaction Reference Number** shown in your payment app.\n\n"
            f"📋 Where to find it:\n"
            f"• PhonePe: History → Tap transaction → UTR No\n"
            f"• GPay: Activity → Tap transaction → Transaction ID\n"
            f"• Paytm: History → Tap transaction → Reference No\n"
            f"• Bank App: Check SMS / Account Statement\n\n"
            f"**Just type the UTR/Txn number and send it here.**\n\n"
            f"⏱️ Admin will verify and activate within 5–15 minutes\n"
            f"Your User ID: `{user_id}`"
        )

        buttons = [[Button.inline("❌ Cancel", "main_menu")]]
        await event.edit(instructions, buttons=buttons, parse_mode="md")

    except Exception as e:
        logger.error(f"❌ Error in submit_payment_callback: {e}")
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^referrals$'))
async def referrals_callback(event):
    """Handle referrals callback"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        referral_code = user_doc.get('referral_code', 'N/A')
        referrals_count = user_doc.get('referrals', 0)
        referral_credits = user_doc.get('referral_credits', 0)
        
        referral_link = f"https://t.me/{bot_info.username}?start={referral_code}"
        
        referrals_text = (
            f"📊 **REFER & EARN PROGRAM**\n"
            f"═══════════════════════\n\n"
            f"💰 **How It Works:**\n"
            f"1. Share your referral link below\n"
            f"2. When someone signs up using your link\n"
            f"3. You get **{config.REFERRAL_REWARD} credit** instantly!\n"
            f"4. They get **{config.NEW_USER_CREDITS} free credits**\n\n"
            f"📈 **Your Stats:**\n"
            f"├─ Referral Code: `{referral_code}`\n"
            f"├─ Total Referrals: {referrals_count}\n"
            f"├─ Credits Earned: {referral_credits}\n"
            f"└─ Active Status: ✅\n\n"
            f"🔗 **Your Referral Link:**\n"
            f"{referral_link}\n\n"
            f"📢 **Share Message:**\n"
            f"```\n"
            f"🚀 Join DarkBoxes Intelligence System!\n"
            f"🔍 Access powerful OSINT tools\n"
            f"📊 Phone, Email, Aadhar, Vehicle searches\n"
            f"💎 Get {config.NEW_USER_CREDITS} free credits\n"
            f"🔗 Sign up: {referral_link}\n"
            f"```\n\n"
            f"💡 **Tips:** Share in groups, with friends, on social media!"
        )
        
        await event.edit(
            referrals_text,
            buttons=OneLineKeyboard.referrals_menu(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in referrals_callback: {e}")
        await event.answer("❌ Error loading referrals", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^support$'))
async def support_callback(event):
    """Handle support callback"""
    try:
        support_text = (
            f"🆘 **DARKBOXES SUPPORT**\n"
            f"═══════════════════════\n\n"
            f"📞 **Contact Admin:** @darkboxesAdmin\n"
            f"📧 **Email:** yadiify@gmail.com\n"
            f"⏰ **Response Time:** Within 1 hour\n"
            f"🌐 **Official Channel:** @darkboxesv1\n\n"
            f"❓ **Common Issues:**\n"
            f"• Payment not processed\n"
            f"• Search not working\n"
            f"• Account issues\n"
            f"• Bug reports\n"
            f"• Feature requests\n\n"
            f"⚠️ **Before Contacting:**\n"
            f"1. Check if you have sufficient credits\n"
            f"2. Verify your query format\n"
            f"3. Wait 30 seconds for search results\n"
            f"4. Check @darkboxesv1 for announcements\n\n"
            f"💳 **Payment Support:**\n"
            f"UPI: `{config.UPI_ID}`\n"
            f"After payment, submit your UTR/Transaction No in the bot\n\n"
            f"🔒 **Security Notice:**\n"
            f"Never share passwords or OTPs\n"
            f"Official admin: @darkboxesAdmin only"
        )
        
        await event.edit(
            support_text,
            buttons=OneLineKeyboard.support_menu(),
            parse_mode="md"
        )
        
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
            f"• Aadhar Information\n"
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
            f"📞 **CONTACT ADMINISTRATOR**\n"
            f"═══════════════════════\n\n"
            f"👤 **Official Admin:** @darkboxesAdmin\n\n"
            f"📧 **Contact Methods:**\n"
            f"• Telegram: @darkboxesAdmin (Preferred)\n"
            f"• Email: yadiify@gmail.com\n"
            f"• Channel: @darkboxesv1\n\n"
            f"⏰ **Response Time:**\n"
            f"• General: Within 1 hour\n"
            f"• Urgent: 15-30 minutes\n"
            f"• Payment: 5-10 minutes\n\n"
            f"💳 **Payment Issues:**\n"
            f"1. Send payment to: `{config.UPI_ID}`\n"
            f"2. Note your UTR / Transaction Number\n"
            f"3. Submit it via 💳 Buy Credits in the bot\n"
            f"4. Include your User ID: `{event.sender_id}`\n\n"
            f"⚠️ **Important:**\n"
            f"• Never share passwords/OTPs\n"
            f"• Official admin ONLY: @darkboxesAdmin\n"
            f"• Beware of impersonators\n"
            f"• Report suspicious accounts"
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

        elif state.get("action") == "enter_account_credentials":
            await handle_account_login(event)

        elif state.get("action") == "admin_view_user_search_logs":
            await handle_admin_view_user_search_logs(event)

    except Exception as e:
        logger.error(f"❌ Error in private_message_handler: {e}")

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
                "If you're having trouble, contact @darkboxesAdmin or email yadiify@gmail.com",
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
            f"✅ **UTR SUBMITTED SUCCESSFULLY!**\n\n"
            f"📋 Payment ID: `{payment_id}`\n"
            f"📦 Plan: **{plan_name}**\n"
            f"💰 Amount: ₹{plan_price}\n"
            f"🏦 UTR/Txn No: `{utr_text}`\n\n"
            f"⏳ Admin will verify your payment manually and approve within **5–15 minutes**.\n"
            f"You will receive a notification once activated.\n\n"
            f"📞 For urgent help:\n"
            f"• Telegram: @darkboxesAdmin\n"
            f"• Email: yadiify@gmail.com",
            parse_mode="md"
        )

        user_states.pop(user_id, None)

    except Exception as e:
        logger.error(f"❌ Error handling payment UTR: {e}")
        await event.respond(
            "❌ Error processing your submission. Please try again or contact "
            "@darkboxesAdmin / yadiify@gmail.com"
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
        # Plan IDs can contain underscores (e.g. credits_5, daily10_30),
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
                f"🎉 **PAYMENT APPROVED!**\n\n"
                f"✅ Your **{plan['name']}** is now active!\n"
                f"🔍 {search_info}\n\n"
                f"Thank you for subscribing to DarkBoxes! 🚀\n"
                f"Use /start to begin searching.\n"
                f"Issues? @darkboxesAdmin",
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
                f"❌ **PAYMENT REJECTED**\n\n"
                f"Payment ID: `{payment_id}`\n\n"
                f"Your UTR/Transaction number could not be verified.\n\n"
                f"Possible reasons:\n"
                f"• UTR number was incorrect\n"
                f"• Wrong amount paid\n"
                f"• Wrong UPI ID used\n"
                f"• Payment was cancelled/failed\n\n"
                f"📞 Contact @darkboxesAdmin or email yadiify@gmail.com to resolve.\n"
                f"Please provide your correct UTR number.",
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
                "`@johndoe daily10_30`\n"
                "`DB1A2B3C4D daily20_60`",
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
    """Handle search queries"""
    try:
        user_id = event.sender_id
        search_type = state["type"]
        query = event.text.strip()
        
        if not query:
            await event.respond("❌ Please enter a valid query.")
            return
        
        # Validate query
        cmd = SEARCH_COMMANDS[search_type]
        validation = cmd.get("validation")
        if validation and not re.match(validation, query):
            await event.respond(f"❌ Invalid format. Example: `{cmd['example']}`")
            return
        
        # Special handling for leak search
        if search_type == "leak":
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
        else:
            # Show premium processing message
            processing_text = PremiumFormatter.format_processing(search_type, query)
            status = await event.respond(processing_text, parse_mode="md")
        
        # Check access
        user_doc = await db_manager.get_user(user_id)
        can_search = False
        
        if user_doc.get('subscription') and user_doc.get('subscription_expiry'):
            expiry_date = datetime.fromisoformat(user_doc['subscription_expiry'])
            if expiry_date > datetime.now(timezone.utc):
                can_search = True
        
        if not can_search and user_doc.get('searches_remaining', 0) <= 0:
            await status.delete()
            await event.respond(
                "🔒 **INSUFFICIENT CREDITS**\n\n"
                "Upgrade to Premium for unlimited access:\n\n"
                "👑 **Premium Tier** - ₹499\n"
                "• Unlimited searches (30 days)\n"
                "• All premium databases\n"
                "• Priority processing\n\n"
                "Contact @darkboxesAdmin for assistance.",
                buttons=OneLineKeyboard.subscription_plans()
            )
            user_states.pop(user_id, None)
            return
        
        # Perform search
        result = await search_engine.perform_search(search_type, query, user_id)
        
        # Delete status
        try:
            await status.delete()
        except:
            pass
        
        if result["success"]:
            # Handle multiple files for leak search
            if result.get("has_multiple_files"):
                # Send summary first
                try:
                    await event.respond(result["result"], parse_mode="md")
                except Exception as e:
                    logger.error(f"Error sending formatted result: {e}")
                    await event.respond(result["result"])
                
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
                        
                        try:
                            await event.respond(
                                file=file_data["raw_bytes"],
                                caption=caption,
                                parse_mode="md"
                            )
                            logger.info(f"✅ Sent {file_type} file to user")
                        except Exception as e:
                            logger.error(f"Error sending file: {e}")
                            await event.respond(file=file_data["raw_bytes"], caption=caption)
            else:
                try:
                    await event.respond(result["result"], parse_mode="md")
                except Exception as e:
                    logger.error(f"Error sending formatted result: {e}")
                    await event.respond(result["result"])
            
            await db_manager.update_searches(user_id, search_type, query, True)
        else:
            # Send error message to user
            try:
                await event.respond(result["error"], parse_mode="md")
            except Exception as e:
                logger.error(f"Error sending error message with markdown: {e}")
                # Try without markdown
                await event.respond(result["error"])
            
            await db_manager.update_searches(user_id, search_type, query, False)
        
        # Clear state
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
        except:
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
        
        broadcast_text = f"📢 **ANNOUNCEMENT**\n\n{message}\n\n— DarkBoxes Administration"
        
        for user in users:
            try:
                await bot_client.send_message(
                    user["user_id"],
                    broadcast_text,
                    parse_mode="md"
                )
                sent += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                failed += 1
        
        # Clear state
        user_states.pop(user_id, None)
        
        result_text = (
            f"✅ **BROADCAST COMPLETE**\n\n"
            f"📊 **Results:**\n"
            f"├─ Total Users: {len(users)}\n"
            f"├─ Successfully Sent: {sent}\n"
            f"└─ Failed: {failed}\n\n"
            f"📝 **Message Preview:**\n{message[:200]}..."
        )
        
        await event.edit(result_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        
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


@bot_client.on(events.NewMessage(func=lambda e: e.is_private and e.text and '[BC:' in e.text))
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
            await event.respond(
                "🔒 **INSUFFICIENT CREDITS**\n\n"
                "You need 3 credits for advanced search.\n\n"
                "👑 **Premium Tier** - ₹499\n"
                "• Unlimited searches (30 days)\n"
                "• All premium databases\n"
                "• Priority processing\n\n"
                "Contact @darkboxesAdmin for assistance.",
                buttons=OneLineKeyboard.subscription_plans()
            )
            return
        
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
            "• `POST /api/v1/search/aadhar` - Aadhar search\n"
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
    "IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwojIC0qLSBjb2Rpbmc6IHV0Zi04IC0qLQoiIiIK4pWU4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWXCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgICAgICAgICAgREFSS0JPWEVTIElOVEVMTElHRU5DRSBTWVNURU0gICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWRICAgICAgICAgIFByb2Zlc3Npb25hbCBUZXJtaW5hbCBDbGllbnQgdjMuMCAgICAgICAgICAgICAgICAgICAgICAg4pWRCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgICAgICAgICAgRm9yIGF1dGhvcml6ZWQgdXNlIG9ubHkuICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWRICAgICAgICAgIMKpIDIwMjUgRGFya0JveGVzIEludGVsbGlnZW5jZS4gQWxsIHJpZ2h0cyByZXNlcnZlZC4gICAg4pWRCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZrilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZ0KCkNvbnRhY3QgIDogQGRhcmtib3hlc0FkbWluIChUZWxlZ3JhbSkKRW1haWwgICAgOiB5YWRpaWZ5QGdtYWlsLmNvbQpDaGFubmVsICA6IEBkYXJrYm94ZXN2MQoiIiIKCmltcG9ydCBvcwppbXBvcnQgc3lzCmltcG9ydCBqc29uCmltcG9ydCB0aW1lCmltcG9ydCBoYXNobGliCmltcG9ydCBnZXRwYXNzCmltcG9ydCB0ZXh0d3JhcAppbXBvcnQgcmUKaW1wb3J0IHBsYXRmb3JtCmZyb20gZGF0ZXRpbWUgaW1wb3J0IGRhdGV0aW1lCmZyb20gdHlwaW5nIGltcG9ydCBEaWN0LCBPcHRpb25hbCwgQW55CgojIOKUgOKUgCBEZXBlbmRlbmN5IGNoZWNrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAp0cnk6CiAgICBpbXBvcnQgcmVxdWVzdHMKZXhjZXB0IEltcG9ydEVycm9yOgogICAgcHJpbnQoIlxuWyFdIE1pc3NpbmcgZGVwZW5kZW5jeTogcmVxdWVzdHMiKQogICAgcHJpbnQoIiAgICBJbnN0YWxsIHdpdGg6ICBwaXAgaW5zdGFsbCByZXF1ZXN0cyIpCiAgICBwcmludCgiICAgIE9uIFRlcm11eDogICAgIHBpcCBpbnN0YWxsIHJlcXVlc3RzIikKICAgIHN5cy5leGl0KDEpCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIENPTkZJR1VSQVRJT04KIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCkFQSV9CQVNFX1VSTCA9IG9zLmdldGVudigiREFSS0JPWEVTX0FQSV9VUkwiLCAiaHR0cHM6Ly9yZWxheS13emx6Lm9ucmVuZGVyLmNvbSIpClJFUVVFU1RfVElNRU9VVCA9IDkwClNFU1NJT05fRklMRSAgICA9IG9zLnBhdGguZXhwYW5kdXNlcigifi8uZGFya2JveGVzX3Nlc3Npb24uanNvbiIpClJFU1VMVFNfRElSICAgICA9IG9zLnBhdGguZXhwYW5kdXNlcigifi9kYXJrYm94ZXNfcmVzdWx0cyIpCgpWRVJTSU9OICAgICAgICAgPSAiMy4wIgpCVUlMRF9EQVRFICAgICAgPSAiMjAyNSIKRlVMTF9OQU1FICAgICAgID0gIkRBUktCT1hFUyBJTlRFTExJR0VOQ0UgU1lTVEVNIgpTVVBQT1JUX1RHICAgICAgPSAiQGRhcmtib3hlc0FkbWluIgpTVVBQT1JUX0VNQUlMICAgPSAieWFkaWlmeUBnbWFpbC5jb20iCkNIQU5ORUwgICAgICAgICA9ICJAZGFya2JveGVzdjEiCgojIOKUgOKUgCBEZXRlY3QgbmFycm93IHRlcm1pbmFsIChUZXJtdXgtZnJpZW5kbHkpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAp0cnk6CiAgICBURVJNX1dJRFRIID0gb3MuZ2V0X3Rlcm1pbmFsX3NpemUoKS5jb2x1bW5zCmV4Y2VwdCBFeGNlcHRpb246CiAgICBURVJNX1dJRFRIID0gNjAgICAgIyBzYWZlIGRlZmF1bHQgZm9yIFRlcm11eAoKTkFSUk9XID0gVEVSTV9XSURUSCA8IDcyICAgIyB1c2UgMi1saW5lIG1vZGUgd2hlbiB0ZXJtaW5hbCBpcyBuYXJyb3cKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgQ09MT1JTCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgpkZWYgX3N1cHBvcnRzX2NvbG9yKCkgLT4gYm9vbDoKICAgICIiIkNoZWNrIGlmIHRlcm1pbmFsIHN1cHBvcnRzIEFOU0kgY29sb3IgY29kZXMuIiIiCiAgICBpZiBvcy5nZXRlbnYoIk5PX0NPTE9SIik6CiAgICAgICAgcmV0dXJuIEZhbHNlCiAgICBpZiBwbGF0Zm9ybS5zeXN0ZW0oKSA9PSAiV2luZG93cyI6CiAgICAgICAgcmV0dXJuIG9zLmdldGVudigiQU5TSUNPTiIpIGlzIG5vdCBOb25lCiAgICByZXR1cm4gaGFzYXR0cihzeXMuc3Rkb3V0LCAiaXNhdHR5IikgYW5kIHN5cy5zdGRvdXQuaXNhdHR5KCkKCl9VU0VfQ09MT1IgPSBfc3VwcG9ydHNfY29sb3IoKQoKY2xhc3MgQzoKICAgICIiIkNvbG9yIGNvbnN0YW50cyDigJQgYXV0by1kaXNhYmxlZCBvbiBwbGFpbiB0ZXJtaW5hbHMuIiIiCiAgICBpZiBfVVNFX0NPTE9SOgogICAgICAgIFIgICA9ICdcMDMzWzBtJyAgICAgICMgcmVzZXQKICAgICAgICBCICAgPSAnXDAzM1sxbScgICAgICAjIGJvbGQKICAgICAgICBESU0gPSAnXDAzM1sybScKICAgICAgICBVTCAgPSAnXDAzM1s0bScKCiAgICAgICAgQkxLID0gJ1wwMzNbMzg7NTsyNDBtJyAgICMgZGFyayBncmF5CiAgICAgICAgR1JOID0gJ1wwMzNbMzg7NTs0Nm0nICAgICMgYnJpZ2h0IGdyZWVuCiAgICAgICAgQ1lOID0gJ1wwMzNbMzg7NTs1MW0nICAgICMgYnJpZ2h0IGN5YW4KICAgICAgICBZTFcgPSAnXDAzM1szODs1OzIyNm0nICAgIyBicmlnaHQgeWVsbG93CiAgICAgICAgUkVEID0gJ1wwMzNbMzg7NTsxOTZtJyAgICMgYnJpZ2h0IHJlZAogICAgICAgIFdIVCA9ICdcMDMzWzk3bScKICAgICAgICBNQUcgPSAnXDAzM1szODs1OzIxM20nICAgIyBtYWdlbnRhL3BpbmsKICAgICAgICBCTFUgPSAnXDAzM1szODs1Ozc1bScgICAgIyBibHVlCgogICAgICAgIE9LICA9ICdcMDMzWzkybScKICAgICAgICBJTkYgPSAnXDAzM1s5Nm0nCiAgICAgICAgV1JOID0gJ1wwMzNbOTNtJwogICAgICAgIEVSUiA9ICdcMDMzWzkxbScKICAgIGVsc2U6CiAgICAgICAgUj1CPURJTT1VTD1CTEs9R1JOPUNZTj1ZTFc9UkVEPVdIVD1NQUc9QkxVPU9LPUlORj1XUk49RVJSID0gJycKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIERJU1BMQVkgSEVMUEVSUwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKZGVmIF9saW5lKGNoYXI6IHN0ciA9ICfilIAnLCB3aWR0aDogaW50ID0gTm9uZSkgLT4gc3RyOgogICAgdyA9IHdpZHRoIG9yIG1pbihURVJNX1dJRFRILCA3MCkKICAgIHJldHVybiBjaGFyICogdwoKZGVmIF9jZW50ZXIodGV4dDogc3RyLCB3aWR0aDogaW50ID0gTm9uZSkgLT4gc3RyOgogICAgdyA9IHdpZHRoIG9yIG1pbihURVJNX1dJRFRILCA3MCkKICAgIHJldHVybiB0ZXh0LmNlbnRlcih3KQoKZGVmIF9ib3hfbGluZSh0ZXh0OiBzdHIsIGNoYXI6IHN0ciA9ICfilZEnLCB3aWR0aDogaW50ID0gTm9uZSkgLT4gc3RyOgogICAgIiIiUHJpbnQgYSB0ZXh0IGluc2lkZSBhIGJveCByb3csIGZpdHRpbmcgdGhlIHRlcm1pbmFsLiIiIgogICAgdyA9ICh3aWR0aCBvciBtaW4oVEVSTV9XSURUSCwgNzApKSAtIDQKICAgIHJldHVybiBmIntjaGFyfSB7dGV4dDo8e3d9fSB7Y2hhcn0iCgpkZWYgcHJpbnRfYmFubmVyKCk6CiAgICAiIiJQcmludCB0aGUgRGFya0JveGVzIGJhbm5lciDigJQgYXV0by1hZGFwdHMgdG8gdGVybWluYWwgd2lkdGguIiIiCiAgICB3ID0gbWluKFRFUk1fV0lEVEgsIDcwKQogICAgcHJpbnQoKQoKICAgIGlmIE5BUlJPVzoKICAgICAgICAjIENvbXBhY3QgMi1saW5lIGJhbm5lciBmb3Igc21hbGwgdGVybWluYWxzIChUZXJtdXgpCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk59e0MuQn0iICsgIj0iICogdyArIEMuUikKICAgICAgICBwcmludChmIntDLkdSTn17Qy5CfSIgKyBfY2VudGVyKCIgREFSS0JPWEVTICIsIHcpLnJlcGxhY2UoIiAiLCAi4pWQIiwgMSkgKyBDLlIpCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk59IiArIF9jZW50ZXIoIklOVEVMTElHRU5DRSBTWVNURU0iLCB3KSArIEMuUikKICAgICAgICBwcmludChmIntDLllMV30iICsgX2NlbnRlcihmIlRlcm1pbmFsIENsaWVudCB2e1ZFUlNJT059IiwgdykgKyBDLlIpCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk59IiArICI9IiAqIHcgKyBDLlIpCiAgICBlbHNlOgogICAgICAgIGJvcmRlciA9ICLilZQiICsgIuKVkCIgKiAodyAtIDIpICsgIuKVlyIKICAgICAgICBib3JkZXJfYiA9ICLilZoiICsgIuKVkCIgKiAodyAtIDIpICsgIuKVnSIKICAgICAgICByb3dfYmxhbmsgPSAi4pWRIiArICIgIiAqICh3IC0gMikgKyAi4pWRIgogICAgICAgIHByaW50KGYie0MuR1JOfXtDLkJ9e2JvcmRlcn17Qy5SfSIpCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk59e3Jvd19ibGFua317Qy5SfSIpCgogICAgICAgIHRpdGxlID0gIiBEQVJLQk9YRVMgSU5URUxMSUdFTkNFIFNZU1RFTSAiCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk594pWRe0MuWUxXfXtDLkJ9e3RpdGxlLmNlbnRlcih3LTIpfXtDLlJ9e0MuR1JOfeKVkXtDLlJ9IikKCiAgICAgICAgc3ViID0gZiIgUHJvZmVzc2lvbmFsIFRlcm1pbmFsIENsaWVudCAgdntWRVJTSU9OfSAiCiAgICAgICAgcHJpbnQoZiJ7Qy5HUk594pWRe0MuQ1lOfXtzdWIuY2VudGVyKHctMil9e0MuUn17Qy5HUk594pWRe0MuUn0iKQogICAgICAgIHByaW50KGYie0MuR1JOfeKVkXtDLkJMS317JyBGb3IgYXV0aG9yaXplZCB1c2Ugb25seSAnLmNlbnRlcih3LTIpfXtDLlJ9e0MuR1JOfeKVkXtDLlJ9IikKICAgICAgICBwcmludChmIntDLkdSTn17cm93X2JsYW5rfXtDLlJ9IikKICAgICAgICBwcmludChmIntDLkdSTn17Ym9yZGVyX2J9e0MuUn0iKQoKICAgIHByaW50KGYie0MuQkxLfXtfbGluZSgpfXtDLlJ9IikKICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZLSVtLSVkICAlSDolTTolUyIpCiAgICBzdGF0dXNfbGluZSA9IGYiICBTdGF0dXM6IHtDLkdSTn1PTkxJTkV7Qy5SfSAgIFRpbWU6IHtDLkNZTn17dHN9e0MuUn0iCiAgICBwcmludChzdGF0dXNfbGluZSkKICAgIHByaW50KGYie0MuQkxLfXtfbGluZSgpfXtDLlJ9IikKICAgIHByaW50KCkKCgpkZWYgc2VjdGlvbih0aXRsZTogc3RyKToKICAgICIiIlByaW50IGEgc2VjdGlvbiBoZWFkaW5nLiIiIgogICAgdyA9IG1pbihURVJNX1dJRFRILCA3MCkKICAgIHByaW50KCkKICAgIHByaW50KGYie0MuQ1lOfXtfbGluZSgn4pWQJywgdyl9e0MuUn0iKQogICAgcHJpbnQoZiJ7Qy5DWU59e0MuQn0gIHt0aXRsZS51cHBlcigpfXtDLlJ9IikKICAgIHByaW50KGYie0MuQ1lOfXtfbGluZSgn4pWQJywgdyl9e0MuUn0iKQogICAgcHJpbnQoKQoKCmRlZiBzdWJzZWN0aW9uKHRpdGxlOiBzdHIpOgogICAgIiIiUHJpbnQgYSBzdWItaGVhZGluZy4iIiIKICAgIHByaW50KGYiXG57Qy5CTFV9ICDilIDilIDilIAge3RpdGxlfSB7J+KUgCcgKiBtYXgoMSwgbWluKFRFUk1fV0lEVEgsNzApIC0gbGVuKHRpdGxlKSAtIDgpfXtDLlJ9IikKCgpkZWYgb2sobXNnOiBzdHIpOgogICAgcHJpbnQoZiIgIHtDLk9LfVvinJNde0MuUn0ge21zZ30iKQoKZGVmIGluZm8obXNnOiBzdHIpOgogICAgcHJpbnQoZiIgIHtDLklORn1baV17Qy5SfSB7bXNnfSIpCgpkZWYgd2Fybihtc2c6IHN0cik6CiAgICBwcmludChmIiAge0MuV1JOfVshXXtDLlJ9IHttc2d9IikKCmRlZiBlcnIobXNnOiBzdHIpOgogICAgcHJpbnQoZiIgIHtDLkVSUn1b4pyXXXtDLlJ9IHttc2d9IikKCmRlZiBmaWVsZChrZXk6IHN0ciwgdmFsdWU6IHN0cik6CiAgICAiIiJQcmludCBhIGtleS12YWx1ZSByZXN1bHQgZmllbGQuIiIiCiAgICBpZiBOQVJST1c6CiAgICAgICAgIyBUd28gbGluZXMgb24gbmFycm93IHRlcm1pbmFscwogICAgICAgIHByaW50KGYiICB7Qy5CTEt94pSMe0MuUn0ge0MuQn17a2V5fXtDLlJ9IikKICAgICAgICBwcmludChmIiAge0MuQkxLfeKUlOKUgHtDLlJ9IHtDLkdSTn17dmFsdWV9e0MuUn0iKQogICAgZWxzZToKICAgICAgICBwYWQgPSBtYXgoMSwgMjIgLSBsZW4oa2V5KSkKICAgICAgICBwcmludChmIiAge0MuQkxLfeKUgntDLlJ9IHtDLkJ9e2tleX17Qy5SfXsnICcgKiBwYWR9e0MuR1JOfXt2YWx1ZX17Qy5SfSIpCgpkZWYgc2VwYXJhdG9yKCk6CiAgICBwcmludChmIiAge0MuQkxLfXtfbGluZSgnwrcnLCBtaW4oVEVSTV9XSURUSC00LCA2NikpfXtDLlJ9IikKCmRlZiBwcm9tcHQobGFiZWw6IHN0ciwgZGVmYXVsdDogc3RyID0gIiIpIC0+IHN0cjoKICAgICIiIlN0eWxlZCBpbnB1dCBwcm9tcHQg4oCUIGFsd2F5cyBvbiBpdHMgb3duIGxpbmUuIiIiCiAgICBpZiBOQVJST1c6CiAgICAgICAgcHJpbnQoZiJcbiAge0MuQ1lOfeKWtiAge2xhYmVsfXtDLlJ9IikKICAgICAgICByZXNwID0gaW5wdXQoZiIgIHtDLllMV33ihpIgIHtDLlJ9Iikuc3RyaXAoKQogICAgZWxzZToKICAgICAgICByZXNwID0gaW5wdXQoZiJcbiAge0MuQ1lOfeKWtiAge2xhYmVsfToge0MuWUxXfSIpLnN0cmlwKCkKICAgICAgICBwcmludChDLlIsIGVuZD0iIikKICAgIHJldHVybiByZXNwIGlmIHJlc3AgZWxzZSBkZWZhdWx0CgpkZWYgcHJvbXB0X3Bhc3N3b3JkKGxhYmVsOiBzdHIpIC0+IHN0cjoKICAgICIiIlBhc3N3b3JkIHByb21wdCAoaGlkZGVuIGlucHV0KS4iIiIKICAgIGlmIE5BUlJPVzoKICAgICAgICBwcmludChmIlxuICB7Qy5DWU594pa2ICB7bGFiZWx9e0MuUn0iKQogICAgZWxzZToKICAgICAgICBwcmludChmIlxuICB7Qy5DWU594pa2ICB7bGFiZWx9OiB7Qy5SfSIsIGVuZD0iIiwgZmx1c2g9VHJ1ZSkKICAgIHRyeToKICAgICAgICBwdyA9IGdldHBhc3MuZ2V0cGFzcygiIikKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcHcgPSBpbnB1dCgiICAiKS5zdHJpcCgpCiAgICByZXR1cm4gcHcKCmRlZiBsb2FkaW5nKG1zZzogc3RyKToKICAgIHByaW50KGYiICB7Qy5ZTFd9W+Kfs117Qy5SfSB7bXNnfSIsIGVuZD0iIiwgZmx1c2g9VHJ1ZSkKCmRlZiBjbGVhcl9sb2FkaW5nKCk6CiAgICBwcmludChmIlxyeycgJyAqIG1pbihURVJNX1dJRFRILCA3MCl9XHIiLCBlbmQ9IiIsIGZsdXNoPVRydWUpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBTRVNTSU9OIE1BTkFHRU1FTlQKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmNsYXNzIFNlc3Npb246CiAgICAiIiJQZXJzaXN0IGxvZ2luIHN0YXRlIGJldHdlZW4gcnVucy4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5hY2NvdW50X2lkOiBzdHIgID0gIiIKICAgICAgICBzZWxmLmFwaV9rZXk6IHN0ciAgICAgPSAiIgogICAgICAgIHNlbGYudXNlcm5hbWU6IHN0ciAgICA9ICIiCiAgICAgICAgc2VsZi5jcmVkaXRzOiBpbnQgICAgID0gMAogICAgICAgIHNlbGYucGxhbjogc3RyICAgICAgICA9ICJOb25lIgogICAgICAgIHNlbGYuX2xvYWRlZCAgICAgICAgICA9IEZhbHNlCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIG9zLnBhdGguZXhpc3RzKFNFU1NJT05fRklMRSk6CiAgICAgICAgICAgICAgICB3aXRoIG9wZW4oU0VTU0lPTl9GSUxFLCAiciIpIGFzIGY6CiAgICAgICAgICAgICAgICAgICAgZCA9IGpzb24ubG9hZChmKQogICAgICAgICAgICAgICAgc2VsZi5hY2NvdW50X2lkID0gZC5nZXQoImFjY291bnRfaWQiLCAiIikKICAgICAgICAgICAgICAgIHNlbGYuYXBpX2tleSAgICA9IGQuZ2V0KCJhcGlfa2V5IiwgIiIpCiAgICAgICAgICAgICAgICBzZWxmLnVzZXJuYW1lICAgPSBkLmdldCgidXNlcm5hbWUiLCAiIikKICAgICAgICAgICAgICAgIHNlbGYuY3JlZGl0cyAgICA9IGQuZ2V0KCJjcmVkaXRzIiwgMCkKICAgICAgICAgICAgICAgIHNlbGYucGxhbiAgICAgICA9IGQuZ2V0KCJwbGFuIiwgIk5vbmUiKQogICAgICAgICAgICAgICAgaWYgc2VsZi5hY2NvdW50X2lkIGFuZCBzZWxmLmFwaV9rZXk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBzYXZlKHNlbGYpOgogICAgICAgIHRyeToKICAgICAgICAgICAgb3MubWFrZWRpcnMob3MucGF0aC5kaXJuYW1lKFNFU1NJT05fRklMRSksIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHdpdGggb3BlbihTRVNTSU9OX0ZJTEUsICJ3IikgYXMgZjoKICAgICAgICAgICAgICAgIGpzb24uZHVtcCh7CiAgICAgICAgICAgICAgICAgICAgImFjY291bnRfaWQiOiBzZWxmLmFjY291bnRfaWQsCiAgICAgICAgICAgICAgICAgICAgImFwaV9rZXkiOiAgICBzZWxmLmFwaV9rZXksCiAgICAgICAgICAgICAgICAgICAgInVzZXJuYW1lIjogICBzZWxmLnVzZXJuYW1lLAogICAgICAgICAgICAgICAgICAgICJjcmVkaXRzIjogICAgc2VsZi5jcmVkaXRzLAogICAgICAgICAgICAgICAgICAgICJwbGFuIjogICAgICAgc2VsZi5wbGFuLAogICAgICAgICAgICAgICAgICAgICJzYXZlZF9hdCI6ICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgIH0sIGYsIGluZGVudD0yKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBkZWYgY2xlYXIoc2VsZik6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBvcy5wYXRoLmV4aXN0cyhTRVNTSU9OX0ZJTEUpOgogICAgICAgICAgICAgICAgb3MucmVtb3ZlKFNFU1NJT05fRklMRSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgc2VsZi5hY2NvdW50X2lkID0gIiIKICAgICAgICBzZWxmLmFwaV9rZXkgICAgPSAiIgogICAgICAgIHNlbGYudXNlcm5hbWUgICA9ICIiCiAgICAgICAgc2VsZi5jcmVkaXRzICAgID0gMAogICAgICAgIHNlbGYucGxhbiAgICAgICA9ICJOb25lIgoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGlzX3ZhbGlkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGJvb2woc2VsZi5hY2NvdW50X2lkIGFuZCBzZWxmLmFwaV9rZXkpCgoKc2Vzc2lvbiA9IFNlc3Npb24oKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgQVBJIENMSUVOVAojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKY2xhc3MgRGFya0JveGVzQVBJOgogICAgIiIiSFRUUCBjbGllbnQgZm9yIHRoZSBEYXJrQm94ZXMgYmFja2VuZC4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fc2Vzc2lvbiA9IHJlcXVlc3RzLlNlc3Npb24oKQogICAgICAgIHNlbGYuX3Nlc3Npb24uaGVhZGVycy51cGRhdGUoewogICAgICAgICAgICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICAgICAgIlVzZXItQWdlbnQiOiAgICBmIkRhcmtCb3hlcy1DbGllbnQve1ZFUlNJT059IFB5dGhvbi97c3lzLnZlcnNpb24uc3BsaXQoKVswXX0iLAogICAgICAgICAgICAiQWNjZXB0IjogICAgICAgICJhcHBsaWNhdGlvbi9qc29uIgogICAgICAgIH0pCgogICAgZGVmIF9zZXRfYXV0aChzZWxmLCBhcGlfa2V5OiBzdHIpOgogICAgICAgIHNlbGYuX3Nlc3Npb24uaGVhZGVyc1siWC1BUEktS2V5Il0gPSBhcGlfa2V5CgogICAgZGVmIF9yZXF1ZXN0KHNlbGYsIG1ldGhvZDogc3RyLCBlbmRwb2ludDogc3RyLAogICAgICAgICAgICAgICAgIGRhdGE6IERpY3QgPSBOb25lLCBub19hdXRoOiBib29sID0gRmFsc2UpIC0+IERpY3Q6CiAgICAgICAgdXJsID0gZiJ7QVBJX0JBU0VfVVJMfXtlbmRwb2ludH0iCiAgICAgICAgaWYgbm90IG5vX2F1dGggYW5kIHNlc3Npb24uYXBpX2tleToKICAgICAgICAgICAgc2VsZi5fc2V0X2F1dGgoc2Vzc2lvbi5hcGlfa2V5KQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIG1ldGhvZCA9PSAiR0VUIjoKICAgICAgICAgICAgICAgIHJlc3AgPSBzZWxmLl9zZXNzaW9uLmdldCh1cmwsIHRpbWVvdXQ9UkVRVUVTVF9USU1FT1VUKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgcmVzcCA9IHNlbGYuX3Nlc3Npb24ucG9zdCh1cmwsIGpzb249ZGF0YSBvciB7fSwgdGltZW91dD1SRVFVRVNUX1RJTUVPVVQpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1c19jb2RlID09IDIwMDoKICAgICAgICAgICAgICAgIHJldHVybiByZXNwLmpzb24oKQogICAgICAgICAgICBlbGlmIHJlc3Auc3RhdHVzX2NvZGUgPT0gNDAxOgogICAgICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiVU5BVVRIT1JJWkVEIiwKICAgICAgICAgICAgICAgICAgICAgICAgIm1lc3NhZ2UiOiAiSW52YWxpZCBvciBleHBpcmVkIGNyZWRlbnRpYWxzLiBQbGVhc2UgbG9nIGluIGFnYWluLiJ9CiAgICAgICAgICAgIGVsaWYgcmVzcC5zdGF0dXNfY29kZSA9PSA0MDM6CiAgICAgICAgICAgICAgICByZXR1cm4geyJzdGF0dXMiOiAiZXJyb3IiLCAiY29kZSI6ICJGT1JCSURERU4iLAogICAgICAgICAgICAgICAgICAgICAgICAibWVzc2FnZSI6ICJJbnN1ZmZpY2llbnQgY3JlZGl0cyBvciBhY2NvdW50IGJhbm5lZC4ifQogICAgICAgICAgICBlbGlmIHJlc3Auc3RhdHVzX2NvZGUgPT0gNDI5OgogICAgICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiUkFURV9MSU1JVCIsCiAgICAgICAgICAgICAgICAgICAgICAgICJtZXNzYWdlIjogIlRvbyBtYW55IHJlcXVlc3RzLiBQbGVhc2Ugd2FpdCBhIG1vbWVudC4ifQogICAgICAgICAgICBlbGlmIHJlc3Auc3RhdHVzX2NvZGUgPT0gNDA0OgogICAgICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiTk9UX0ZPVU5EIiwKICAgICAgICAgICAgICAgICAgICAgICAgIm1lc3NhZ2UiOiAiRW5kcG9pbnQgbm90IGZvdW5kLiJ9CiAgICAgICAgICAgIGVsaWYgcmVzcC5zdGF0dXNfY29kZSA+PSA1MDA6CiAgICAgICAgICAgICAgICByZXR1cm4geyJzdGF0dXMiOiAiZXJyb3IiLCAiY29kZSI6ICJTRVJWRVJfRVJST1IiLAogICAgICAgICAgICAgICAgICAgICAgICAibWVzc2FnZSI6IGYiU2VydmVyIGVycm9yICh7cmVzcC5zdGF0dXNfY29kZX0pLiBUcnkgYWdhaW4gbGF0ZXIuIn0KICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gcmVzcC5qc29uKCkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiSFRUUF9FUlJPUiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAibWVzc2FnZSI6IGYiSFRUUCB7cmVzcC5zdGF0dXNfY29kZX0ifQoKICAgICAgICBleGNlcHQgcmVxdWVzdHMuVGltZW91dDoKICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiVElNRU9VVCIsCiAgICAgICAgICAgICAgICAgICAgIm1lc3NhZ2UiOiAiUmVxdWVzdCB0aW1lZCBvdXQuIFNlcnZlciBtYXkgYmUgYnVzeSDigJQgdHJ5IGFnYWluLiJ9CiAgICAgICAgZXhjZXB0IHJlcXVlc3RzLkNvbm5lY3Rpb25FcnJvcjoKICAgICAgICAgICAgcmV0dXJuIHsic3RhdHVzIjogImVycm9yIiwgImNvZGUiOiAiQ09OTkVDVElPTl9FUlJPUiIsCiAgICAgICAgICAgICAgICAgICAgIm1lc3NhZ2UiOiAiQ2Fubm90IHJlYWNoIHNlcnZlci4gQ2hlY2sgeW91ciBpbnRlcm5ldCBjb25uZWN0aW9uLiJ9CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICByZXR1cm4geyJzdGF0dXMiOiAiZXJyb3IiLCAiY29kZSI6ICJDTElFTlRfRVJST1IiLCAibWVzc2FnZSI6IHN0cihlKX0KCiAgICAjIOKUgOKUgCBBdXRoIGVuZHBvaW50cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKCiAgICBkZWYgcmVnaXN0ZXIoc2VsZiwgdXNlcm5hbWU6IHN0ciwgcGFzc3dvcmQ6IHN0cikgLT4gRGljdDoKICAgICAgICByZXR1cm4gc2VsZi5fcmVxdWVzdCgiUE9TVCIsICIvYXBpL3YxL2F1dGgvcmVnaXN0ZXIiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHsidXNlcm5hbWUiOiB1c2VybmFtZSwgInBhc3N3b3JkIjogcGFzc3dvcmR9LCBub19hdXRoPVRydWUpCgogICAgZGVmIGxvZ2luKHNlbGYsIGFjY291bnRfaWRfb3JfdXNlcm5hbWU6IHN0ciwgcGFzc3dvcmQ6IHN0cikgLT4gRGljdDoKICAgICAgICByZXR1cm4gc2VsZi5fcmVxdWVzdCgiUE9TVCIsICIvYXBpL3YxL2F1dGgvbG9naW4iLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHsiYWNjb3VudF9pZCI6IGFjY291bnRfaWRfb3JfdXNlcm5hbWUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJwYXNzd29yZCI6ICAgcGFzc3dvcmR9LCBub19hdXRoPVRydWUpCgogICAgIyDilIDilIAgVXRpbGl0eSBlbmRwb2ludHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACgogICAgZGVmIHN0YXR1cyhzZWxmKSAgLT4gRGljdDogcmV0dXJuIHNlbGYuX3JlcXVlc3QoIkdFVCIsICAiL2FwaS92MS9zdGF0dXMiKQogICAgZGVmIGJhbGFuY2Uoc2VsZikgLT4gRGljdDogcmV0dXJuIHNlbGYuX3JlcXVlc3QoIkdFVCIsICAiL2FwaS92MS9iYWxhbmNlIikKICAgIGRlZiB1c2FnZShzZWxmKSAgIC0+IERpY3Q6IHJldHVybiBzZWxmLl9yZXF1ZXN0KCJHRVQiLCAgIi9hcGkvdjEvdXNhZ2UiKQogICAgZGVmIGRvY3Moc2VsZikgICAgLT4gRGljdDogcmV0dXJuIHNlbGYuX3JlcXVlc3QoIkdFVCIsICAiL2FwaS92MS9kb2NzIikKCiAgICAjIOKUgOKUgCBTZWFyY2ggZW5kcG9pbnRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKICAgIGRlZiBzZWFyY2goc2VsZiwgc2VhcmNoX3R5cGU6IHN0ciwgcXVlcnk6IHN0cikgLT4gRGljdDoKICAgICAgICBlbmRwb2ludF9tYXAgPSB7CiAgICAgICAgICAgICJwaG9uZSI6ICAgICIvYXBpL3YxL3NlYXJjaC9waG9uZSIsCiAgICAgICAgICAgICJmYW1pbHkiOiAgICIvYXBpL3YxL3NlYXJjaC9mYW1pbHkiLAogICAgICAgICAgICAiYWFkaGFyIjogICAiL2FwaS92MS9zZWFyY2gvYWFkaGFyIiwKICAgICAgICAgICAgInZlaGljbGUiOiAgIi9hcGkvdjEvc2VhcmNoL3ZlaGljbGUiLAogICAgICAgICAgICAidXBpIjogICAgICAiL2FwaS92MS9zZWFyY2gvdXBpIiwKICAgICAgICAgICAgImVtYWlsIjogICAgIi9hcGkvdjEvc2VhcmNoL2VtYWlsIiwKICAgICAgICAgICAgInRlbGVncmFtIjogIi9hcGkvdjEvc2VhcmNoL3RlbGVncmFtIiwKICAgICAgICAgICAgImltZWkiOiAgICAgIi9hcGkvdjEvc2VhcmNoL2ltZWkiLAogICAgICAgICAgICAiZ3N0IjogICAgICAiL2FwaS92MS9zZWFyY2gvZ3N0IiwKICAgICAgICAgICAgImluc3RhIjogICAgIi9hcGkvdjEvc2VhcmNoL2luc3RhZ3JhbSIsCiAgICAgICAgICAgICJpbnN0YWdyYW0iOiIvYXBpL3YxL3NlYXJjaC9pbnN0YWdyYW0iLAogICAgICAgICAgICAicGFrIjogICAgICAiL2FwaS92MS9zZWFyY2gvcGFraXN0YW4iLAogICAgICAgICAgICAiaXAiOiAgICAgICAiL2FwaS92MS9zZWFyY2gvaXAiLAogICAgICAgICAgICAiaWZzYyI6ICAgICAiL2FwaS92MS9zZWFyY2gvaWZzYyIsCiAgICAgICAgICAgICJsZWFrIjogICAgICIvYXBpL3YxL3NlYXJjaC9sZWFrIiwKICAgICAgICB9CiAgICAgICAgZW5kcG9pbnQgPSBlbmRwb2ludF9tYXAuZ2V0KHNlYXJjaF90eXBlLmxvd2VyKCkpCiAgICAgICAgaWYgbm90IGVuZHBvaW50OgogICAgICAgICAgICByZXR1cm4geyJzdGF0dXMiOiAiZXJyb3IiLCAibWVzc2FnZSI6IGYiVW5rbm93biBzZWFyY2ggdHlwZToge3NlYXJjaF90eXBlfSJ9CiAgICAgICAgcmV0dXJuIHNlbGYuX3JlcXVlc3QoIlBPU1QiLCBlbmRwb2ludCwgeyJxdWVyeSI6IHF1ZXJ5fSkKCiAgICBkZWYgYmF0Y2hfc2VhcmNoKHNlbGYsIHNlYXJjaGVzOiBsaXN0KSAtPiBEaWN0OgogICAgICAgIHJldHVybiBzZWxmLl9yZXF1ZXN0KCJQT1NUIiwgIi9hcGkvdjEvc2VhcmNoL2JhdGNoIiwgeyJzZWFyY2hlcyI6IHNlYXJjaGVzfSkKCgphcGkgPSBEYXJrQm94ZXNBUEkoKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgUkVTVUxUIERJU1BMQVkKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmRlZiBkaXNwbGF5X3Jlc3VsdChyZXN1bHQ6IERpY3QsIHNlYXJjaF90eXBlOiBzdHIgPSAiIiwgcXVlcnk6IHN0ciA9ICIiKToKICAgICIiIlJlbmRlciBhIHNlYXJjaCByZXN1bHQgaW4gYSBwcm9mZXNzaW9uYWwgc3R5bGVkIGJsb2NrLiIiIgogICAgaWYgcmVzdWx0LmdldCgic3RhdHVzIikgIT0gInN1Y2Nlc3MiOgogICAgICAgIGVycihyZXN1bHQuZ2V0KCJtZXNzYWdlIiwgIlVua25vd24gZXJyb3IiKSkKICAgICAgICBjb2RlID0gcmVzdWx0LmdldCgiY29kZSIsICIiKQogICAgICAgIGlmIGNvZGUgPT0gIlVOQVVUSE9SSVpFRCI6CiAgICAgICAgICAgIHdhcm4oIlNlc3Npb24gbWF5IGhhdmUgZXhwaXJlZC4gVXNlIG9wdGlvbiAyMiB0byBsb2cgb3V0IGFuZCBsb2cgaW4gYWdhaW4uIikKICAgICAgICBlbGlmIGNvZGUgaW4gKCJGT1JCSURERU4iLCAiSU5TVUZGSUNJRU5UX0NSRURJVFMiKToKICAgICAgICAgICAgd2FybigiTm90IGVub3VnaCBjcmVkaXRzLiBVc2Ugb3B0aW9uIDIwIHRvIGNoZWNrIGJhbGFuY2Ugb3IgYnV5IGEgcGxhbi4iKQogICAgICAgIHJldHVybgoKICAgIGRhdGEgPSByZXN1bHQuZ2V0KCJkYXRhIiwge30pCiAgICByYXcgID0gcmVzdWx0LmdldCgicmF3X3RleHQiKSBvciBkYXRhLmdldCgicmF3X3RleHQiLCAiIikKCiAgICBzdWJzZWN0aW9uKGYiUkVTVUxUIOKAlCB7c2VhcmNoX3R5cGUudXBwZXIoKX0g4oC6IHtxdWVyeX0iKQoKICAgICMgRGlzcGxheSBwYXJzZWQgZmllbGRzIGlmIGF2YWlsYWJsZQogICAgcGFyc2VkID0gZGF0YS5nZXQoInBhcnNlZF9kYXRhIiwge30pIGlmIGlzaW5zdGFuY2UoZGF0YSwgZGljdCkgZWxzZSB7fQogICAgaWYgcGFyc2VkOgogICAgICAgIGZvciBrLCB2IGluIHBhcnNlZC5pdGVtcygpOgogICAgICAgICAgICBpZiBrIGFuZCB2OgogICAgICAgICAgICAgICAgZmllbGQoc3RyKGspLCBzdHIodikpCiAgICBlbGlmIGlzaW5zdGFuY2UoZGF0YSwgZGljdCkgYW5kIGRhdGE6CiAgICAgICAgZm9yIGssIHYgaW4gZGF0YS5pdGVtcygpOgogICAgICAgICAgICBpZiBrIG5vdCBpbiAoInJhd190ZXh0IiwgInBhcnNlZF9kYXRhIiwgInNvdXJjZSIsICJ0aW1lc3RhbXAiLCAidHlwZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAibmFtZSIsICJxdWVyeSIpIGFuZCB2OgogICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZSh2LCAoc3RyLCBpbnQsIGZsb2F0KSk6CiAgICAgICAgICAgICAgICAgICAgZmllbGQoc3RyKGspLnJlcGxhY2UoIl8iLCAiICIpLnRpdGxlKCksIHN0cih2KSkKCiAgICAjIEFsd2F5cyBzaG93IHJhdyB0ZXh0IGFzIGZhbGxiYWNrCiAgICBpZiByYXcgYW5kIHJhdy5zdHJpcCgpOgogICAgICAgIGlmIG5vdCBwYXJzZWQ6CiAgICAgICAgICAgIHN1YnNlY3Rpb24oIlJhdyBJbnRlbGxpZ2VuY2UiKQogICAgICAgICAgICBsaW5lcyA9IHJhdy5zdHJpcCgpLnNwbGl0KCJcbiIpCiAgICAgICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgaWYgbGluZToKICAgICAgICAgICAgICAgICAgICBwcmludChmIiAge0MuQkxLfeKUgntDLlJ9IHtsaW5lfSIpCgogICAgc291cmNlID0gZGF0YS5nZXQoInNvdXJjZSIsICJEYXJrQm94ZXMgTmV0d29yayIpIGlmIGlzaW5zdGFuY2UoZGF0YSwgZGljdCkgZWxzZSAiIgogICAgdHMgICAgID0gZGF0YS5nZXQoInRpbWVzdGFtcCIsICIiKVs6MTZdLnJlcGxhY2UoIlQiLCAiICIpIGlmIGlzaW5zdGFuY2UoZGF0YSwgZGljdCkgZWxzZSAiIgoKICAgIHByaW50KCkKICAgIHNlcGFyYXRvcigpCiAgICBpZiBzb3VyY2U6CiAgICAgICAgaW5mbyhmIlNvdXJjZToge3NvdXJjZX0iKQogICAgaWYgdHM6CiAgICAgICAgaW5mbyhmIlRpbWUgIDoge3RzfSIpCgogICAgIyBTYXZlIHJlc3VsdAogICAgX3NhdmVfcmVzdWx0KHJlc3VsdCwgc2VhcmNoX3R5cGUsIHF1ZXJ5KQoKCmRlZiBfc2F2ZV9yZXN1bHQocmVzdWx0OiBEaWN0LCBzZWFyY2hfdHlwZTogc3RyLCBxdWVyeTogc3RyKToKICAgICIiIkF1dG8tc2F2ZSByZXN1bHQgdG8gZmlsZS4iIiIKICAgIHRyeToKICAgICAgICBvcy5tYWtlZGlycyhSRVNVTFRTX0RJUiwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICB0cyAgID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgIHNhZmUgPSByZS5zdWIocidbXmEtekEtWjAtOV9cLV0nLCAnXycsIHF1ZXJ5KVs6MjBdCiAgICAgICAgZm5hbWUgPSBmIntSRVNVTFRTX0RJUn0ve3NlYXJjaF90eXBlfV97c2FmZX1fe3RzfS5qc29uIgogICAgICAgIHdpdGggb3BlbihmbmFtZSwgInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBqc29uLmR1bXAoewogICAgICAgICAgICAgICAgInNlYXJjaF90eXBlIjogc2VhcmNoX3R5cGUsCiAgICAgICAgICAgICAgICAicXVlcnkiOiBxdWVyeSwKICAgICAgICAgICAgICAgICJ0aW1lc3RhbXAiOiBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgICAgICJyZXN1bHQiOiByZXN1bHQKICAgICAgICAgICAgfSwgZiwgaW5kZW50PTIsIGVuc3VyZV9hc2NpaT1GYWxzZSkKICAgICAgICBpbmZvKGYiU2F2ZWQg4oaSIHtmbmFtZX0iKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBwYXNzCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBBVVRIIEZMT1dTCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgpkZWYgZmxvd19yZWdpc3RlcigpOgogICAgIiIiUmVnaXN0ZXIgYSBuZXcgYWNjb3VudCDigJQgbm8gVGVsZWdyYW0gbmVlZGVkLiIiIgogICAgc2VjdGlvbigiQ1JFQVRFIE5FVyBBQ0NPVU5UIikKICAgIHByaW50KGYiICB7Qy5ZTFd9WW91IGRvIG5vdCBuZWVkIGEgVGVsZWdyYW0gYWNjb3VudCB0byByZWdpc3Rlci57Qy5SfSIpCiAgICBwcmludChmIiAge0MuQkxLfUNyZWRpdHMgYW5kIHBsYW5zIGNhbiBiZSBwdXJjaGFzZWQgZnJvbSB0aGUgVGVsZWdyYW0gYm90e0MuUn0iKQogICAgcHJpbnQoZiIgIHtDLkJMS30oQGRhcmtib3hlc0FkbWluKSBvciBkaXJlY3RseSB0aHJvdWdoIHRoZSB0ZXJtaW5hbC57Qy5SfVxuIikKCiAgICB3aGlsZSBUcnVlOgogICAgICAgIHVzZXJuYW1lID0gcHJvbXB0KCJDaG9vc2UgYSB1c2VybmFtZSAobWluIDMgY2hhcnMsIG5vIHNwYWNlcykiKQogICAgICAgIGlmIGxlbih1c2VybmFtZSkgPCAzOgogICAgICAgICAgICB3YXJuKCJVc2VybmFtZSBtdXN0IGJlIGF0IGxlYXN0IDMgY2hhcmFjdGVycy4iKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmICIgIiBpbiB1c2VybmFtZToKICAgICAgICAgICAgd2FybigiVXNlcm5hbWUgY2Fubm90IGNvbnRhaW4gc3BhY2VzLiIpCiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgYnJlYWsKCiAgICB3aGlsZSBUcnVlOgogICAgICAgIHBhc3N3b3JkID0gcHJvbXB0X3Bhc3N3b3JkKCJDaG9vc2UgYSBwYXNzd29yZCAobWluIDYgY2hhcnMsIGhpZGRlbikiKQogICAgICAgIGlmIGxlbihwYXNzd29yZCkgPCA2OgogICAgICAgICAgICB3YXJuKCJQYXNzd29yZCBtdXN0IGJlIGF0IGxlYXN0IDYgY2hhcmFjdGVycy4iKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGNvbmZpcm0gPSBwcm9tcHRfcGFzc3dvcmQoIkNvbmZpcm0gcGFzc3dvcmQgKGhpZGRlbikiKQogICAgICAgIGlmIHBhc3N3b3JkICE9IGNvbmZpcm06CiAgICAgICAgICAgIHdhcm4oIlBhc3N3b3JkcyBkbyBub3QgbWF0Y2guIFRyeSBhZ2Fpbi4iKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGJyZWFrCgogICAgbG9hZGluZygiQ3JlYXRpbmcgYWNjb3VudC4uLiIpCiAgICByZXN1bHQgPSBhcGkucmVnaXN0ZXIodXNlcm5hbWUsIHBhc3N3b3JkKQogICAgY2xlYXJfbG9hZGluZygpCgogICAgaWYgcmVzdWx0LmdldCgic3RhdHVzIikgPT0gInN1Y2Nlc3MiOgogICAgICAgIGFjY19pZCA9IHJlc3VsdC5nZXQoImFjY291bnRfaWQiLCAiIikKICAgICAgICBjcmVkaXRzID0gcmVzdWx0LmdldCgiY3JlZGl0cyIsIDApCiAgICAgICAgb2soIkFjY291bnQgY3JlYXRlZCBzdWNjZXNzZnVsbHkhIikKICAgICAgICBwcmludCgpCiAgICAgICAgcHJpbnQoZiIgIHtDLkdSTn17J+KUgCcqNTB9e0MuUn0iKQogICAgICAgIGZpZWxkKCJBY2NvdW50IElEIiwgIGFjY19pZCkKICAgICAgICBmaWVsZCgiVXNlcm5hbWUiLCAgICB1c2VybmFtZSkKICAgICAgICBmaWVsZCgiQ3JlZGl0cyIsICAgICBzdHIoY3JlZGl0cykpCiAgICAgICAgZmllbGQoIlBsYW4iLCAgICAgICAgIk5vbmUgKHB1cmNoYXNlIHRvIGFjdGl2YXRlKSIpCiAgICAgICAgcHJpbnQoZiIgIHtDLkdSTn17J+KUgCcqNTB9e0MuUn0iKQogICAgICAgIHByaW50KCkKICAgICAgICB3YXJuKCJTQVZFIHlvdXIgQWNjb3VudCBJRCBhbmQgcGFzc3dvcmQg4oCUIHRoZXkgd2lsbCBub3QgYmUgc2hvd24gYWdhaW4uIikKICAgICAgICB3YXJuKCJJZiB5b3UgbG9zZSB0aGVtLCBjb250YWN0IEBkYXJrYm94ZXNBZG1pbiBvciB5YWRpaWZ5QGdtYWlsLmNvbSIpCiAgICAgICAgcHJpbnQoKQogICAgICAgIGluZm8oIlRvIGxvZyBpbiwgdXNlIG9wdGlvbiAyIGluIHRoZSBtYWluIG1lbnUuIikKICAgICAgICBpbmZvKCJUbyBidXkgY3JlZGl0cy9wbGFucywgY29udGFjdCB0aGUgVGVsZWdyYW0gYm90IG9yIEBkYXJrYm94ZXNBZG1pbi4iKQogICAgZWxzZToKICAgICAgICBlcnIocmVzdWx0LmdldCgibWVzc2FnZSIsICJSZWdpc3RyYXRpb24gZmFpbGVkLiIpKQoKCmRlZiBmbG93X2xvZ2luKCkgLT4gYm9vbDoKICAgICIiIkxvZyBpbiB3aXRoIEFjY291bnQgSUQgb3IgdXNlcm5hbWUgKyBwYXNzd29yZC4iIiIKICAgIHNlY3Rpb24oIkxPRyBJTiIpCgogICAgcHJpbnQoZiIgIHtDLllMV31ObyBUZWxlZ3JhbSBhY2NvdW50IHJlcXVpcmVkLntDLlJ9IikKICAgIHByaW50KGYiICB7Qy5CTEt9VXNlIHlvdXIgQWNjb3VudCBJRCAoZS5nLiBEQjFBMkIzQzREKSBvciB1c2VybmFtZS57Qy5SfVxuIikKCiAgICBpZGVudGlmaWVyID0gcHJvbXB0KCJBY2NvdW50IElEIG9yIHVzZXJuYW1lIikKICAgIGlmIG5vdCBpZGVudGlmaWVyOgogICAgICAgIHdhcm4oIkNhbmNlbGxlZC4iKQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIHBhc3N3b3JkID0gcHJvbXB0X3Bhc3N3b3JkKCJQYXNzd29yZCAoaGlkZGVuKSIpCiAgICBpZiBub3QgcGFzc3dvcmQ6CiAgICAgICAgd2FybigiQ2FuY2VsbGVkLiIpCiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgbG9hZGluZygiQXV0aGVudGljYXRpbmcuLi4iKQogICAgcmVzdWx0ID0gYXBpLmxvZ2luKGlkZW50aWZpZXIsIHBhc3N3b3JkKQogICAgY2xlYXJfbG9hZGluZygpCgogICAgaWYgcmVzdWx0LmdldCgic3RhdHVzIikgPT0gInN1Y2Nlc3MiOgogICAgICAgIHNlc3Npb24uYWNjb3VudF9pZCA9IHJlc3VsdC5nZXQoImFjY291bnRfaWQiLCAiIikKICAgICAgICBzZXNzaW9uLmFwaV9rZXkgICAgPSByZXN1bHQuZ2V0KCJhcGlfa2V5IiwgIiIpCiAgICAgICAgc2Vzc2lvbi51c2VybmFtZSAgID0gaWRlbnRpZmllcgogICAgICAgIHNlc3Npb24uY3JlZGl0cyAgICA9IHJlc3VsdC5nZXQoImNyZWRpdHMiLCAwKQogICAgICAgIHNlc3Npb24ucGxhbiAgICAgICA9IHJlc3VsdC5nZXQoInBsYW4iLCAiTm9uZSIpCiAgICAgICAgc2Vzc2lvbi5zYXZlKCkKCiAgICAgICAgb2soIkxvZ2luIHN1Y2Nlc3NmdWwhIikKICAgICAgICBwcmludCgpCiAgICAgICAgZmllbGQoIkFjY291bnQgSUQiLCBzZXNzaW9uLmFjY291bnRfaWQpCiAgICAgICAgZmllbGQoIkNyZWRpdHMiLCAgICBzdHIoc2Vzc2lvbi5jcmVkaXRzKSkKICAgICAgICBmaWVsZCgiUGxhbiIsICAgICAgIHNlc3Npb24ucGxhbikKICAgICAgICByZXR1cm4gVHJ1ZQogICAgZWxzZToKICAgICAgICBlcnIocmVzdWx0LmdldCgibWVzc2FnZSIsICJMb2dpbiBmYWlsZWQuIikpCiAgICAgICAgbXNnID0gcmVzdWx0LmdldCgibWVzc2FnZSIsICIiKS5sb3dlcigpCiAgICAgICAgaWYgIm5vdCBmb3VuZCIgaW4gbXNnOgogICAgICAgICAgICB3YXJuKCJBY2NvdW50IElEIG9yIHVzZXJuYW1lIG5vdCBmb3VuZC4gQ2hlY2sgYW5kIHRyeSBhZ2Fpbi4iKQogICAgICAgIGVsaWYgImluY29ycmVjdCIgaW4gbXNnIG9yICJwYXNzd29yZCIgaW4gbXNnOgogICAgICAgICAgICB3YXJuKCJXcm9uZyBwYXNzd29yZC4gQ29udGFjdCBAZGFya2JveGVzQWRtaW4gaWYgeW91IGZvcmdvdCBpdC4iKQogICAgICAgIGVsaWYgImJhbm5lZCIgaW4gbXNnOgogICAgICAgICAgICB3YXJuKCJBY2NvdW50IGlzIGJhbm5lZC4gQ29udGFjdCBAZGFya2JveGVzQWRtaW4gdG8gYXBwZWFsLiIpCiAgICAgICAgcmV0dXJuIEZhbHNlCgoKZGVmIGZsb3dfbG9nb3V0KCk6CiAgICAiIiJMb2cgb3V0IGFuZCBjbGVhciBzYXZlZCBzZXNzaW9uLiIiIgogICAgaWYgbm90IHNlc3Npb24uaXNfdmFsaWQ6CiAgICAgICAgd2FybigiWW91IGFyZSBub3QgbG9nZ2VkIGluLiIpCiAgICAgICAgcmV0dXJuCiAgICBzZXNzaW9uLmNsZWFyKCkKICAgIG9rKCJMb2dnZWQgb3V0LiBTZXNzaW9uIGNsZWFyZWQuIikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIFNFQVJDSCBGTE9XUwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKU0VBUkNIX0NBVEFMT0cgPSBbCiAgICAjIChrZXksIGRpc3BsYXlfbmFtZSwgaGludCwgZXhhbXBsZSkKICAgICgicGhvbmUiLCAgICAiUGhvbmUgSW50ZWxsaWdlbmNlIiwgICAgICAgICIxMC0xNSBkaWdpdCBtb2JpbGUgbnVtYmVyIiwgIjk4NzY1NDMyMTAiKSwKICAgICgiZmFtaWx5IiwgICAiRmFtaWx5IE5ldHdvcmsiLCAgICAgICAgICAgICIxMi1kaWdpdCBBYWRoYXIgbnVtYmVyIiwgIjEyMzQ1Njc4OTAxMiIpLAogICAgKCJhYWRoYXIiLCAgICJBYWRoYXIgQ29tcHJlaGVuc2l2ZSIsICAgICAgIjEyLWRpZ2l0IEFhZGhhciBudW1iZXIiLCAiMTIzNDU2Nzg5MDEyIiksCiAgICAoInZlaGljbGUiLCAgIlZlaGljbGUgSW50ZWxsaWdlbmNlIiwgICAgICAiVmVoaWNsZSBudW1iZXIgKGUuZy4gVVA1M0NaMzM5MSkiLCAiVVA1M0NaMzM5MSIpLAogICAgKCJ0ZWxlZ3JhbSIsICJUZWxlZ3JhbSBJbnRlbGxpZ2VuY2UiLCAgICAgIkB1c2VybmFtZSBvciBwaG9uZSBudW1iZXIiLCAiQHVzZXJuYW1lIiksCiAgICAoImltZWkiLCAgICAgIkRldmljZSBJbnRlbGxpZ2VuY2UgKElNRUkpIiwiMTUtZGlnaXQgSU1FSSBudW1iZXIiLCAiMzU0Njc4OTAxMjM0NTY3IiksCiAgICAoImdzdCIsICAgICAgIkdTVCBJbnRlbGxpZ2VuY2UiLCAgICAgICAgICAiR1NUIG51bWJlciAoMTUgY2hhcnMpIiwgIjI3QUFQRlUwOTM5RjFaViIpLAogICAgKCJpbnN0YSIsICAgICJJbnN0YWdyYW0gSW50ZWxsaWdlbmNlIiwgICAgIkluc3RhZ3JhbSB1c2VybmFtZSIsICJ1c2VybmFtZSIpLAogICAgKCJpcCIsICAgICAgICJJUCBJbnRlbGxpZ2VuY2UiLCAgICAgICAgICAgIklQdjQgb3IgSVB2NiBhZGRyZXNzIiwgIjEuMi4zLjQiKSwKICAgICgiaWZzYyIsICAgICAiSUZTQyBDb2RlIExvb2t1cCIsICAgICAgICAgICIxMS1jaGFyIElGU0MgY29kZSIsICJTQklOMDAwMTIzNCIpLAogICAgKCJlbWFpbCIsICAgICJFbWFpbCBJbnRlbGxpZ2VuY2UiLCAgICAgICAgIkVtYWlsIGFkZHJlc3MiLCAidXNlckBleGFtcGxlLmNvbSIpLAogICAgKCJ1cGkiLCAgICAgICJVUEkgSW50ZWxsaWdlbmNlIiwgICAgICAgICAgIlVQSSBJRCIsICJ1c2VyQHVwaSIpLAogICAgKCJwYWsiLCAgICAgICJQYWtpc3RhbiBEQiIsICAgICAgICAgICAgICAgIk5hbWUgLyBwaG9uZSAvIE5JQyBudW1iZXIiLCAicXVlcnkiKSwKICAgICgibGVhayIsICAgICAiQWR2YW5jZWQgT1NJTlQgLyBMZWFrIiwgICAgICJBbnkgcXVlcnkg4oCUIG5hbWUsIHBob25lLCBlbWFpbCwgZXRjLiIsICJxdWVyeSIpLApdCgoKZGVmIF9yZXF1aXJlX2xvZ2luKCkgLT4gYm9vbDoKICAgIGlmIG5vdCBzZXNzaW9uLmlzX3ZhbGlkOgogICAgICAgIHdhcm4oIllvdSBhcmUgbm90IGxvZ2dlZCBpbi4gQ2hvb3NlIG9wdGlvbiAyIHRvIGxvZyBpbiBmaXJzdC4iKQogICAgICAgIHJldHVybiBGYWxzZQogICAgcmV0dXJuIFRydWUKCgpkZWYgZmxvd19zaW5nbGVfc2VhcmNoKGtleTogc3RyLCBuYW1lOiBzdHIsIGhpbnQ6IHN0ciwgZXhhbXBsZTogc3RyKToKICAgICIiIlBlcmZvcm0gYSBzaW5nbGUgdGFyZ2V0ZWQgc2VhcmNoLiIiIgogICAgaWYgbm90IF9yZXF1aXJlX2xvZ2luKCk6CiAgICAgICAgcmV0dXJuCgogICAgc2VjdGlvbihmIntuYW1lfSIpCiAgICBpbmZvKGYiSW5wdXQgOiB7aGludH0iKQogICAgaW5mbyhmIkV4YW1wbGU6IHtleGFtcGxlfSIpCgogICAgcXVlcnkgPSBwcm9tcHQoZiJFbnRlciBxdWVyeSAoe2hpbnR9KSIpCiAgICBpZiBub3QgcXVlcnk6CiAgICAgICAgd2FybigiQ2FuY2VsbGVkLiIpCiAgICAgICAgcmV0dXJuCgogICAgbG9hZGluZyhmIlF1ZXJ5aW5nIHtuYW1lfS4uLiIpCiAgICByZXN1bHQgPSBhcGkuc2VhcmNoKGtleSwgcXVlcnkpCiAgICBjbGVhcl9sb2FkaW5nKCkKICAgIGRpc3BsYXlfcmVzdWx0KHJlc3VsdCwga2V5LCBxdWVyeSkKCgpkZWYgZmxvd19iYXRjaF9zZWFyY2goKToKICAgICIiIlN1Ym1pdCBtdWx0aXBsZSBzZWFyY2hlcyBhdCBvbmNlLiIiIgogICAgaWYgbm90IF9yZXF1aXJlX2xvZ2luKCk6CiAgICAgICAgcmV0dXJuCgogICAgc2VjdGlvbigiQkFUQ0ggU0VBUkNIIikKICAgIGluZm8oIkVudGVyIHNlYXJjaGVzIGluIGZvcm1hdDogIHR5cGU6cXVlcnkiKQogICAgaW5mbygiQXZhaWxhYmxlIHR5cGVzOiBwaG9uZSwgZmFtaWx5LCBhYWRoYXIsIHZlaGljbGUsIGVtYWlsLCBpbWVpLCBnc3QsIGV0Yy4iKQogICAgaW5mbygiUHJlc3MgRW50ZXIgb24gYW4gZW1wdHkgbGluZSB3aGVuIGRvbmUuXG4iKQoKICAgIHNlYXJjaGVzID0gW10KICAgIHdoaWxlIFRydWU6CiAgICAgICAgaWYgTkFSUk9XOgogICAgICAgICAgICBwcmludChmIiAge0MuQ1lOfVt7bGVuKHNlYXJjaGVzKSsxfV0gdHlwZTpxdWVyeXtDLlJ9IikKICAgICAgICAgICAgbGluZSA9IGlucHV0KGYiICB7Qy5ZTFd94oaSICB7Qy5SfSIpLnN0cmlwKCkKICAgICAgICBlbHNlOgogICAgICAgICAgICBsaW5lID0gaW5wdXQoZiIgIHtDLkNZTn1be2xlbihzZWFyY2hlcykrMX1dICB7Qy5ZTFd9Iikuc3RyaXAoKQogICAgICAgICAgICBwcmludChDLlIsIGVuZD0iIikKCiAgICAgICAgaWYgbm90IGxpbmU6CiAgICAgICAgICAgIGlmIHNlYXJjaGVzOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHdhcm4oIkVudGVyIGF0IGxlYXN0IG9uZSBzZWFyY2gsIG9yIEN0cmwrQyB0byBjYW5jZWwuIikKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIGlmICI6IiBub3QgaW4gbGluZToKICAgICAgICAgICAgd2FybigiRm9ybWF0IG11c3QgYmUgIHR5cGU6cXVlcnkgIChlLmcuIHBob25lOjk4NzY1NDMyMTApIikKICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgc3R5cGUsIHNxdWVyeSA9IGxpbmUuc3BsaXQoIjoiLCAxKQogICAgICAgIHN0eXBlICA9IHN0eXBlLnN0cmlwKCkubG93ZXIoKQogICAgICAgIHNxdWVyeSA9IHNxdWVyeS5zdHJpcCgpCgogICAgICAgIGlmIG5vdCBzdHlwZSBvciBub3Qgc3F1ZXJ5OgogICAgICAgICAgICB3YXJuKCJCb3RoIHR5cGUgYW5kIHF1ZXJ5IGFyZSByZXF1aXJlZC4iKQogICAgICAgICAgICBjb250aW51ZQoKICAgICAgICBzZWFyY2hlcy5hcHBlbmQoeyJ0eXBlIjogc3R5cGUsICJxdWVyeSI6IHNxdWVyeX0pCiAgICAgICAgb2soZiJBZGRlZDoge3N0eXBlfSDihpIge3NxdWVyeX0iKQoKICAgIGlmIG5vdCBzZWFyY2hlczoKICAgICAgICB3YXJuKCJObyBzZWFyY2hlcyBhZGRlZC4iKQogICAgICAgIHJldHVybgoKICAgIGxvYWRpbmcoZiJTdWJtaXR0aW5nIHtsZW4oc2VhcmNoZXMpfSBzZWFyY2hlcy4uLiIpCiAgICByZXN1bHQgPSBhcGkuYmF0Y2hfc2VhcmNoKHNlYXJjaGVzKQogICAgY2xlYXJfbG9hZGluZygpCgogICAgaWYgcmVzdWx0LmdldCgic3RhdHVzIikgPT0gInN1Y2Nlc3MiOgogICAgICAgIG9rKGYiQmF0Y2ggc2VhcmNoIGNvbXBsZXRlIOKAlCB7bGVuKHNlYXJjaGVzKX0gcXVlcmllcyBwcm9jZXNzZWQuIikKICAgICAgICByZXN1bHRzX2RhdGEgPSByZXN1bHQuZ2V0KCJkYXRhIiwge30pLmdldCgicmVzdWx0cyIsIFtdKQogICAgICAgIGZvciBpLCByZXMgaW4gZW51bWVyYXRlKHJlc3VsdHNfZGF0YSwgMSk6CiAgICAgICAgICAgIHN1YnNlY3Rpb24oZiJSZXN1bHQge2l9IC8ge2xlbihyZXN1bHRzX2RhdGEpfSIpCiAgICAgICAgICAgIGRpc3BsYXlfcmVzdWx0KHsic3RhdHVzIjogInN1Y2Nlc3MiLCAiZGF0YSI6IHJlc30sCiAgICAgICAgICAgICAgICAgICAgICAgICAgIHJlcy5nZXQoInR5cGUiLCAiIiksIHJlcy5nZXQoInF1ZXJ5IiwgIiIpKQogICAgZWxzZToKICAgICAgICBlcnIocmVzdWx0LmdldCgibWVzc2FnZSIsICJCYXRjaCBzZWFyY2ggZmFpbGVkLiIpKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgQUNDT1VOVCAmIFVUSUxJVFkgRkxPV1MKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmRlZiBmbG93X2NoZWNrX2JhbGFuY2UoKToKICAgICIiIlNob3cgY3JlZGl0cyBhbmQgcGxhbiBpbmZvLiIiIgogICAgaWYgbm90IF9yZXF1aXJlX2xvZ2luKCk6CiAgICAgICAgcmV0dXJuCiAgICBzZWN0aW9uKCJBQ0NPVU5UIEJBTEFOQ0UiKQogICAgbG9hZGluZygiRmV0Y2hpbmcgYmFsYW5jZS4uLiIpCiAgICByZXN1bHQgPSBhcGkuYmFsYW5jZSgpCiAgICBjbGVhcl9sb2FkaW5nKCkKICAgIGlmIHJlc3VsdC5nZXQoInN0YXR1cyIpID09ICJzdWNjZXNzIjoKICAgICAgICBkID0gcmVzdWx0LmdldCgiZGF0YSIsIHt9KQogICAgICAgIG9rKCJCYWxhbmNlIHJldHJpZXZlZC4iKQogICAgICAgIGZpZWxkKCJBY2NvdW50IElEIiwgICAgc2Vzc2lvbi5hY2NvdW50X2lkKQogICAgICAgIGZpZWxkKCJDcmVkaXRzIiwgICAgICAgc3RyKGQuZ2V0KCJjcmVkaXRzIiwgc2Vzc2lvbi5jcmVkaXRzKSkpCiAgICAgICAgZmllbGQoIlBsYW4iLCAgICAgICAgICBkLmdldCgicGxhbiIsIHNlc3Npb24ucGxhbikpCiAgICAgICAgZmllbGQoIlZhbGlkIFVudGlsIiwgICBkLmdldCgidmFsaWRfdW50aWwiLCAi4oCUIikpCiAgICAgICAgZmllbGQoIkRhaWx5IFVzZWQiLCAgICBzdHIoZC5nZXQoImRhaWx5X3VzZWQiLCAi4oCUIikpKQogICAgICAgIGZpZWxkKCJEYWlseSBMaW1pdCIsICAgc3RyKGQuZ2V0KCJkYWlseV9saW1pdCIsICLigJQiKSkpCiAgICAgICAgIyBVcGRhdGUgc2Vzc2lvbgogICAgICAgIHNlc3Npb24uY3JlZGl0cyA9IGQuZ2V0KCJjcmVkaXRzIiwgc2Vzc2lvbi5jcmVkaXRzKQogICAgICAgIHNlc3Npb24ucGxhbiAgICA9IGQuZ2V0KCJwbGFuIiwgc2Vzc2lvbi5wbGFuKQogICAgICAgIHNlc3Npb24uc2F2ZSgpCiAgICBlbHNlOgogICAgICAgIGVycihyZXN1bHQuZ2V0KCJtZXNzYWdlIiwgIkNvdWxkIG5vdCBmZXRjaCBiYWxhbmNlLiIpKQoKCmRlZiBmbG93X3ZpZXdfdXNhZ2UoKToKICAgICIiIlNob3cgc2VhcmNoIHVzYWdlIHN0YXRzLiIiIgogICAgaWYgbm90IF9yZXF1aXJlX2xvZ2luKCk6CiAgICAgICAgcmV0dXJuCiAgICBzZWN0aW9uKCJVU0FHRSBTVEFUSVNUSUNTIikKICAgIGxvYWRpbmcoIkZldGNoaW5nIHVzYWdlLi4uIikKICAgIHJlc3VsdCA9IGFwaS51c2FnZSgpCiAgICBjbGVhcl9sb2FkaW5nKCkKICAgIGlmIHJlc3VsdC5nZXQoInN0YXR1cyIpID09ICJzdWNjZXNzIjoKICAgICAgICBkID0gcmVzdWx0LmdldCgiZGF0YSIsIHt9KQogICAgICAgIG9rKCJVc2FnZSByZXRyaWV2ZWQuIikKICAgICAgICBmaWVsZCgiVG90YWwgU2VhcmNoZXMiLCAgIHN0cihkLmdldCgidG90YWxfc2VhcmNoZXMiLCAwKSkpCiAgICAgICAgZmllbGQoIlRvZGF5J3MgU2VhcmNoZXMiLCBzdHIoZC5nZXQoInRvZGF5X3NlYXJjaGVzIiwgMCkpKQogICAgICAgIGZpZWxkKCJUaGlzIE1vbnRoIiwgICAgICAgc3RyKGQuZ2V0KCJtb250aF9zZWFyY2hlcyIsIDApKSkKICAgICAgICBmaWVsZCgiTGFzdCBTZWFyY2giLCAgICAgIGQuZ2V0KCJsYXN0X3NlYXJjaCIsICJOZXZlciIpKQogICAgZWxzZToKICAgICAgICBlcnIocmVzdWx0LmdldCgibWVzc2FnZSIsICJDb3VsZCBub3QgZmV0Y2ggdXNhZ2UuIikpCgoKZGVmIGZsb3dfY2hlY2tfc3RhdHVzKCk6CiAgICAiIiJQaW5nIHRoZSBBUEkgYW5kIHNob3cgc3lzdGVtIHN0YXR1cy4iIiIKICAgIHNlY3Rpb24oIlNZU1RFTSBTVEFUVVMiKQogICAgbG9hZGluZygiUGluZ2luZyBzZXJ2ZXIuLi4iKQogICAgcmVzdWx0ID0gYXBpLnN0YXR1cygpCiAgICBjbGVhcl9sb2FkaW5nKCkKICAgIGlmIHJlc3VsdC5nZXQoInN0YXR1cyIpID09ICJzdWNjZXNzIjoKICAgICAgICBkID0gcmVzdWx0LmdldCgiZGF0YSIsIHt9KQogICAgICAgIHN0YXRlID0gZiJ7Qy5HUk59T1BFUkFUSU9OQUx7Qy5SfSIgaWYgZC5nZXQoIm9ubGluZSIsIFRydWUpIGVsc2UgZiJ7Qy5FUlJ9REVHUkFERUR7Qy5SfSIKICAgICAgICBvayhmIlNlcnZlciBpcyB7c3RhdGV9IikKICAgICAgICBmaWVsZCgiVmVyc2lvbiIsIGQuZ2V0KCJ2ZXJzaW9uIiwgVkVSU0lPTikpCiAgICAgICAgZmllbGQoIlVwdGltZSIsICBkLmdldCgidXB0aW1lIiwgIuKAlCIpKQogICAgZWxzZToKICAgICAgICAjIEp1c3Qgc2hvdyB0aGF0IHdlIGNhbiByZWFjaCB0aGUgc2VydmVyCiAgICAgICAgd2FybigiU3RhdHVzIGVuZHBvaW50IHJldHVybmVkIGFuIGVycm9yLCBidXQgc2VydmVyIGlzIHJlYWNoYWJsZS4iKQoKCmRlZiBmbG93X3ZpZXdfZG9jcygpOgogICAgIiIiRGlzcGxheSBBUEkgZW5kcG9pbnQgZG9jdW1lbnRhdGlvbi4iIiIKICAgIHNlY3Rpb24oIkFQSSBET0NVTUVOVEFUSU9OIikKICAgIGxvYWRpbmcoIkxvYWRpbmcgZG9jcy4uLiIpCiAgICByZXN1bHQgPSBhcGkuZG9jcygpCiAgICBjbGVhcl9sb2FkaW5nKCkKICAgIGlmIHJlc3VsdDoKICAgICAgICBmaWVsZCgiU2VydmljZSIsICByZXN1bHQuZ2V0KCJzZXJ2aWNlIiwgIkRhcmtCb3hlcyBJbnRlbGxpZ2VuY2UgQVBJIikpCiAgICAgICAgZmllbGQoIlZlcnNpb24iLCAgcmVzdWx0LmdldCgidmVyc2lvbiIsIFZFUlNJT04pKQogICAgICAgIGZpZWxkKCJCYXNlIFVSTCIsIHJlc3VsdC5nZXQoImJhc2VfdXJsIiwgQVBJX0JBU0VfVVJMKSkKCiAgICAgICAgZW5kcG9pbnRzID0gcmVzdWx0LmdldCgiZW5kcG9pbnRzIiwge30pCiAgICAgICAgaWYgZW5kcG9pbnRzLmdldCgic2VhcmNoIik6CiAgICAgICAgICAgIHN1YnNlY3Rpb24oIlNlYXJjaCBFbmRwb2ludHMiKQogICAgICAgICAgICBmb3IgbmFtZSwgZXAgaW4gZW5kcG9pbnRzWyJzZWFyY2giXS5pdGVtcygpOgogICAgICAgICAgICAgICAgcHJpbnQoZiIgIHtDLkJMS33ilIJ7Qy5SfSB7Qy5CfXtlcC5nZXQoJ21ldGhvZCcsJ1BPU1QnKX17Qy5SfSIKICAgICAgICAgICAgICAgICAgICAgIGYiICB7ZXAuZ2V0KCdlbmRwb2ludCcsJycpfSIpCgogICAgICAgIGlmIGVuZHBvaW50cy5nZXQoInV0aWxpdHkiKToKICAgICAgICAgICAgc3Vic2VjdGlvbigiVXRpbGl0eSBFbmRwb2ludHMiKQogICAgICAgICAgICBmb3IgbmFtZSwgZXAgaW4gZW5kcG9pbnRzWyJ1dGlsaXR5Il0uaXRlbXMoKToKICAgICAgICAgICAgICAgIHByaW50KGYiICB7Qy5CTEt94pSCe0MuUn0ge0MuQn17ZXAuZ2V0KCdtZXRob2QnLCdHRVQnKX17Qy5SfSIKICAgICAgICAgICAgICAgICAgICAgIGYiICB7ZXAuZ2V0KCdlbmRwb2ludCcsJycpfSIpCiAgICBlbHNlOgogICAgICAgIGluZm8oZiJEb2NzIGF0OiB7QVBJX0JBU0VfVVJMfS9hcGkvdjEvZG9jcyIpCgoKZGVmIGZsb3dfaG93X3RvX2J1eSgpOgogICAgIiIiU2hvdyBob3cgdG8gcHVyY2hhc2UgY3JlZGl0cyAvIHBsYW5zLiIiIgogICAgc2VjdGlvbigiSE9XIFRPIEJVWSBDUkVESVRTIC8gUExBTlMiKQogICAgcHJpbnQoZiIiIgogIHtDLllMV33ilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIF7Qy5SfQoKICB7Qy5CfU9QVElPTiAxOiBWaWEgVGVsZWdyYW0gQm90e0MuUn0KICB7Qy5CTEt94pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAe0MuUn0KICAxLiBPcGVuIFRlbGVncmFtIGFuZCBmaW5kIG91ciBib3QuCiAgMi4gVGFwIHtDLkNZTn3wn5KOIFByZW1pdW0gUGxhbnN7Qy5SfSBpbiB0aGUgbWVudS4KICAzLiBTZWxlY3QgYSBwbGFuIGFuZCBwYXkgdmlhIFVQSS4KICA0LiBFbnRlciB5b3VyIFVUUiAvIFRyYW5zYWN0aW9uIE51bWJlciB3aGVuIHByb21wdGVkLgogIDUuIEFkbWluIHZlcmlmaWVzIG1hbnVhbGx5IOKAlCBhY3RpdmF0ZWQgd2l0aGluIDXigJMxNSBtaW4uCgogIHtDLkJ9T1BUSU9OIDI6IERpcmVjdCBDb250YWN0e0MuUn0KICB7Qy5CTEt94pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAe0MuUn0KICDigKIgVGVsZWdyYW0gOiB7Qy5DWU59QGRhcmtib3hlc0FkbWlue0MuUn0KICDigKIgRW1haWwgICAgOiB7Qy5DWU59eWFkaWlmeUBnbWFpbC5jb217Qy5SfQogIOKAoiBQcm92aWRlICA6IFlvdXIgQWNjb3VudCBJRCAoe0MuWUxXfXtzZXNzaW9uLmFjY291bnRfaWQgb3IgJ3NlZSBvcHRpb24gMTEnfXtDLlJ9KQoKICB7Qy5CfVVQSSBEZXRhaWxze0MuUn0KICB7Qy5CTEt94pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAe0MuUn0KICDigKIgVVBJIElEIDoge0MuR1JOfWR1cmdlc2hyYWloZXJvQG9rc2Jpe0MuUn0KCiAge0MuQn1QbGFucyBBdmFpbGFibGV7Qy5SfQogIHtDLkJMS33ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIB7Qy5SfQogIOKaoSBTdGFydGVyIFBhY2sgICAgICA1IHNlYXJjaGVzICAgICDigrkxMDAKICDwn5SNIEV4cGxvcmVyIFBhY2sgICAgMTUgc2VhcmNoZXMgICAgIOKCuTI1MAogIPCfmoAgRGFpbHkgMTAvMzBkICAgICAxMC9kYXnCtzMwIGRheXMgIOKCuTgwMAogIPCfko4gRGFpbHkgMjAvMzBkICAgICAyMC9kYXnCtzMwIGRheXMgIOKCuTEwMDAKICDwn4yfIERhaWx5IDEwLzYwZCAgICAgMTAvZGF5wrcyIG1vbnRocyDigrkxNTAwCiAg8J+RkSBEYWlseSAyMC82MGQgICAgIDIwL2RhecK3MiBtb250aHMg4oK5MTgwMAoKICB7Qy5ZTFd94pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBe0MuUn0KICAiIiIpCgoKZGVmIGZsb3dfc3VwcG9ydCgpOgogICAgIiIiU2hvdyBzdXBwb3J0IGNvbnRhY3QgaW5mb3JtYXRpb24uIiIiCiAgICBzZWN0aW9uKCJTVVBQT1JUICYgQ09OVEFDVCIpCiAgICBwcmludChmIiIiCiAge0MuR1JOfURBUktCT1hFUyBJTlRFTExJR0VOQ0UgU1lTVEVNe0MuUn0KICB7Qy5CTEt9e0ZVTExfTkFNRX17Qy5SfQoKICB7Qy5CfUNvbnRhY3QgVXN7Qy5SfQogIHtDLkJMS33ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIB7Qy5SfQogIFRlbGVncmFtICA6IHtDLkNZTn17U1VQUE9SVF9UR317Qy5SfQogIEVtYWlsICAgICA6IHtDLkNZTn17U1VQUE9SVF9FTUFJTH17Qy5SfQogIENoYW5uZWwgICA6IHtDLkNZTn17Q0hBTk5FTH17Qy5SfQoKICB7Qy5CfVJlc3BvbnNlIFRpbWVze0MuUn0KICB7Qy5CTEt94pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAe0MuUn0KICBHZW5lcmFsICAgOiB3aXRoaW4gMSBob3VyCiAgVXJnZW50ICAgIDogMTXigJMzMCBtaW51dGVzCiAgUGF5bWVudCAgIDogNeKAkzE1IG1pbnV0ZXMKCiAge0MuQn1Db21tb24gSXNzdWVze0MuUn0KICB7Qy5CTEt94pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAe0MuUn0KICDigKIgRm9yZ290IHBhc3N3b3JkICDihpIgQ29udGFjdCB7U1VQUE9SVF9UR30KICDigKIgUGF5bWVudCBub3QgZG9uZSDihpIgU2hhcmUgVVRSIHdpdGggYWRtaW4KICDigKIgU2VhcmNoIGZhaWxlZCAgICDihpIgQ2hlY2sgY3JlZGl0cyAob3B0IDIwKQogIOKAoiBBY2NvdW50IGJhbm5lZCAgIOKGkiBFbWFpbCB7U1VQUE9SVF9FTUFJTH0KCiAge0MuWUxXfU5ldmVyIHNoYXJlIHlvdXIgcGFzc3dvcmQgd2l0aCBhbnlvbmUue0MuUn0KICB7Qy5ZTFd9T2ZmaWNpYWwgYWRtaW4gb25seToge1NVUFBPUlRfVEd9e0MuUn0KICAgICIiIikKCgpkZWYgZmxvd192aWV3X3NhdmVkKCk6CiAgICAiIiJMaXN0IHNhdmVkIHJlc3VsdCBmaWxlcy4iIiIKICAgIHNlY3Rpb24oIlNBVkVEIFJFU1VMVFMiKQogICAgaWYgbm90IG9zLnBhdGguZXhpc3RzKFJFU1VMVFNfRElSKToKICAgICAgICBpbmZvKCJObyByZXN1bHRzIHNhdmVkIHlldC4iKQogICAgICAgIHJldHVybgogICAgZmlsZXMgPSBzb3J0ZWQob3MubGlzdGRpcihSRVNVTFRTX0RJUiksIHJldmVyc2U9VHJ1ZSkKICAgIGlmIG5vdCBmaWxlczoKICAgICAgICBpbmZvKCJObyByZXN1bHRzIHNhdmVkIHlldC4iKQogICAgICAgIHJldHVybgogICAgb2soZiJ7bGVuKGZpbGVzKX0gc2F2ZWQgcmVzdWx0KHMpIGluIHtSRVNVTFRTX0RJUn0iKQogICAgZm9yIGksIGYgaW4gZW51bWVyYXRlKGZpbGVzWzoyMF0sIDEpOgogICAgICAgIHByaW50KGYiICB7Qy5CTEt9e2k6PjJ9LntDLlJ9IHtmfSIpCiAgICBpZiBsZW4oZmlsZXMpID4gMjA6CiAgICAgICAgaW5mbyhmIi4uLiBhbmQge2xlbihmaWxlcyktMjB9IG1vcmUuIikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1BSU4gTUVOVQojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKZGVmIF9zdGF0dXNfYmFyKCkgLT4gc3RyOgogICAgIiIiT25lLWxpbmUgc3RhdHVzIGZvciB0aGUgcHJvbXB0IGFyZWEuIiIiCiAgICBpZiBzZXNzaW9uLmlzX3ZhbGlkOgogICAgICAgIHJldHVybiAoZiIgIHtDLkJMS31BY2NvdW50OiB7Qy5DWU59e3Nlc3Npb24uYWNjb3VudF9pZH17Qy5SfSIKICAgICAgICAgICAgICAgIGYiICB7Qy5CTEt9Q3JlZGl0czoge0MuR1JOfXtzZXNzaW9uLmNyZWRpdHN9e0MuUn0iCiAgICAgICAgICAgICAgICBmIiAge0MuQkxLfVBsYW46IHtDLllMV317c2Vzc2lvbi5wbGFufXtDLlJ9IikKICAgIGVsc2U6CiAgICAgICAgcmV0dXJuIGYiICB7Qy5XUk59Tm90IGxvZ2dlZCBpbntDLlJ9IgoKCmRlZiBkaXNwbGF5X21lbnUoKToKICAgICIiIlByaW50IG1haW4gbWVudS4iIiIKICAgIHcgPSBtaW4oVEVSTV9XSURUSCwgNzApCiAgICBwcmludCgpCiAgICBwcmludChmIntDLkNZTn17X2xpbmUoJ+KUgCcsIHcpfXtDLlJ9IikKICAgIHByaW50KGYie0MuQ1lOfXtDLkJ9ICBEQVJLQk9YRVMg4oCUIE1BSU4gTUVOVXtDLlJ9IikKICAgIHByaW50KGYie0MuQ1lOfXtfbGluZSgn4pSAJywgdyl9e0MuUn0iKQoKICAgIE1FTlUgPSBbCiAgICAgICAgKCIiLCAi4pSA4pSAIEFDQ09VTlQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAIiksCiAgICAgICAgKCIxIiwgICJSZWdpc3RlciBOZXcgQWNjb3VudCAoTm8gVGVsZWdyYW0gbmVlZGVkKSIpLAogICAgICAgICgiMiIsICAiTG9nIEluIiksCiAgICAgICAgKCIzIiwgICJMb2cgT3V0IiksCiAgICAgICAgKCIiLCAgICIiKSwKICAgICAgICAoIiIsICAi4pSA4pSAIFNFQVJDSEVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgCIpLAogICAgICAgICgiNCIsICAi8J+TsSBQaG9uZSBJbnRlbGxpZ2VuY2UiKSwKICAgICAgICAoIjUiLCAgIvCfkajigI3wn5Gp4oCN8J+Rp+KAjfCfkaYgRmFtaWx5IE5ldHdvcmsgKEFhZGhhcikiKSwKICAgICAgICAoIjYiLCAgIvCfhpQgQWFkaGFyIENvbXByZWhlbnNpdmUiKSwKICAgICAgICAoIjciLCAgIvCfmpcgVmVoaWNsZSBJbnRlbGxpZ2VuY2UiKSwKICAgICAgICAoIjgiLCAgIvCfk7IgVGVsZWdyYW0gSW50ZWxsaWdlbmNlIiksCiAgICAgICAgKCI5IiwgICLwn5OxIERldmljZSBJbnRlbGxpZ2VuY2UgKElNRUkpIiksCiAgICAgICAgKCIxMCIsICLwn4+iIEdTVCBJbnRlbGxpZ2VuY2UiKSwKICAgICAgICAoIjExIiwgIvCfk7ggSW5zdGFncmFtIEludGVsbGlnZW5jZSIpLAogICAgICAgICgiMTIiLCAi8J+MkCBJUCBJbnRlbGxpZ2VuY2UiKSwKICAgICAgICAoIjEzIiwgIvCfj6YgSUZTQyBDb2RlIExvb2t1cCIpLAogICAgICAgICgiMTQiLCAi8J+TpyBFbWFpbCBJbnRlbGxpZ2VuY2UiKSwKICAgICAgICAoIjE1IiwgIvCfkrMgVVBJIEludGVsbGlnZW5jZSIpLAogICAgICAgICgiMTYiLCAi8J+MjyBQYWtpc3RhbiBEQiIpLAogICAgICAgICgiMTciLCAi8J+agCBBZHZhbmNlZCBPU0lOVCAvIExlYWsgU2VhcmNoIiksCiAgICAgICAgKCIxOCIsICLwn5OmIEJhdGNoIFNlYXJjaCAobXVsdGlwbGUgcXVlcmllcykiKSwKICAgICAgICAoIiIsICAgIiIpLAogICAgICAgICgiIiwgICLilIDilIAgQUNDT1VOVCAmIElORk8g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAIiksCiAgICAgICAgKCIyMCIsICLwn5KwIENoZWNrIEJhbGFuY2UgJiBQbGFuIiksCiAgICAgICAgKCIyMSIsICLwn5OKIFZpZXcgVXNhZ2UgU3RhdGlzdGljcyIpLAogICAgICAgICgiMjIiLCAi8J+MkCBTeXN0ZW0gU3RhdHVzIiksCiAgICAgICAgKCIyMyIsICLwn5OWIEFQSSBEb2N1bWVudGF0aW9uIiksCiAgICAgICAgKCIyNCIsICLwn5KzIEhvdyB0byBCdXkgQ3JlZGl0cyAvIFBsYW5zIiksCiAgICAgICAgKCIyNSIsICLwn4aYIFN1cHBvcnQgJiBDb250YWN0IiksCiAgICAgICAgKCIyNiIsICLwn5OBIFZpZXcgU2F2ZWQgUmVzdWx0cyIpLAogICAgICAgICgiIiwgICAiIiksCiAgICAgICAgKCIwIiwgICJFeGl0IiksCiAgICBdCgogICAgZm9yIG9wdCwgbGFiZWwgaW4gTUVOVToKICAgICAgICBpZiBub3Qgb3B0IGFuZCBub3QgbGFiZWw6CiAgICAgICAgICAgIHByaW50KCkKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiBub3Qgb3B0OgogICAgICAgICAgICAjIFNlY3Rpb24gaGVhZGluZwogICAgICAgICAgICBwcmludChmIiAge0MuQkxLfXtsYWJlbH17Qy5SfSIpCiAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIGlmIE5BUlJPVzoKICAgICAgICAgICAgIyBUd28tbGluZSBkaXNwbGF5IGZvciBUZXJtdXgKICAgICAgICAgICAgcHJpbnQoZiIgIHtDLllMV31be29wdDo+Mn1de0MuUn0iKQogICAgICAgICAgICBwcmludChmIiAgICAgICB7bGFiZWx9IikKICAgICAgICBlbHNlOgogICAgICAgICAgICBjb2wgPSBDLkdSTiBpZiBvcHQgPT0gIjAiIGVsc2UgQy5ZTFcKICAgICAgICAgICAgcHJpbnQoZiIgIHtjb2x9W3tvcHQ6PjJ9XXtDLlJ9ICB7bGFiZWx9IikKCiAgICBwcmludCgpCiAgICBwcmludChmIntDLkNZTn17X2xpbmUoJ+KUgCcsIHcpfXtDLlJ9IikKICAgIHByaW50KF9zdGF0dXNfYmFyKCkpCiAgICBwcmludChmIntDLkNZTn17X2xpbmUoJ+KUgCcsIHcpfXtDLlJ9IikKICAgIHByaW50KCkKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1BSU4gTE9PUAojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKZGVmIG1haW4oKToKICAgICIiIkFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LiIiIgogICAgIyBTZXR1cCByZXN1bHRzIGRpcmVjdG9yeQogICAgb3MubWFrZWRpcnMoUkVTVUxUU19ESVIsIGV4aXN0X29rPVRydWUpCgogICAgIyBQcmludCBiYW5uZXIKICAgIHByaW50X2Jhbm5lcigpCgogICAgIyBUcnkgcmVzdG9yaW5nIHNhdmVkIHNlc3Npb24KICAgIGlmIHNlc3Npb24ubG9hZCgpOgogICAgICAgIG9rKGYiU2Vzc2lvbiByZXN0b3JlZCBmb3IgYWNjb3VudCB7c2Vzc2lvbi5hY2NvdW50X2lkfSIpCiAgICAgICAgaW5mbygiVXNlIG9wdGlvbiAzIHRvIGxvZyBvdXQuIikKICAgIGVsc2U6CiAgICAgICAgaW5mbygiTm8gc2F2ZWQgc2Vzc2lvbi4gVXNlIG9wdGlvbiAxIHRvIHJlZ2lzdGVyIG9yIDIgdG8gbG9nIGluLiIpCgogICAgIyBNYWluIGxvb3AKICAgIHdoaWxlIFRydWU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBkaXNwbGF5X21lbnUoKQoKICAgICAgICAgICAgaWYgTkFSUk9XOgogICAgICAgICAgICAgICAgcHJpbnQoZiIgIHtDLkNZTn3ilrYgIEVudGVyIG9wdGlvbiBudW1iZXJ7Qy5SfSIpCiAgICAgICAgICAgICAgICBjaG9pY2UgPSBpbnB1dChmIiAge0MuWUxXfeKGkiAge0MuUn0iKS5zdHJpcCgpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBjaG9pY2UgPSBpbnB1dCgKICAgICAgICAgICAgICAgICAgICBmIiAge0MuR1JOfWRhcmtib3hlc3tDLlJ9e0MuQkxLfUB7Qy5SfSIKICAgICAgICAgICAgICAgICAgICBmIntDLkNZTn1jbGllbnR7Qy5SfSB7Qy5ZTFd9wrt7Qy5SfSAiCiAgICAgICAgICAgICAgICApLnN0cmlwKCkKCiAgICAgICAgICAgIHByaW50KCkKCiAgICAgICAgICAgICMg4pSA4pSAIEFjY291bnQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgIGlmIGNob2ljZSA9PSAiMCI6CiAgICAgICAgICAgICAgICB3YXJuKCJFeGl0aW5nIERhcmtCb3hlcyBUZXJtaW5hbCBDbGllbnQuLi4iKQogICAgICAgICAgICAgICAgb2soIkdvb2RieWUuIFN0YXkgc2VjdXJlLiIpCiAgICAgICAgICAgICAgICBwcmludCgpCiAgICAgICAgICAgICAgICBicmVhawoKICAgICAgICAgICAgZWxpZiBjaG9pY2UgPT0gIjEiOgogICAgICAgICAgICAgICAgZmxvd19yZWdpc3RlcigpCgogICAgICAgICAgICBlbGlmIGNob2ljZSA9PSAiMiI6CiAgICAgICAgICAgICAgICBmbG93X2xvZ2luKCkKCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIzIjoKICAgICAgICAgICAgICAgIGZsb3dfbG9nb3V0KCkKCiAgICAgICAgICAgICMg4pSA4pSAIFNlYXJjaGVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBlbGlmIGNob2ljZSBpbiAoIjQiLCI1IiwiNiIsIjciLCI4IiwiOSIsIjEwIiwiMTEiLCIxMiIsIjEzIiwiMTQiLCIxNSIsIjE2IiwiMTciKToKICAgICAgICAgICAgICAgIGlkeF9tYXAgPSB7CiAgICAgICAgICAgICAgICAgICAgIjQiOiAwLCAiNSI6IDEsICI2IjogMiwgIjciOiAzLCAiOCI6IDQsICI5IjogNSwgIjEwIjogNiwKICAgICAgICAgICAgICAgICAgICAiMTEiOiA3LCAiMTIiOiA4LCAiMTMiOiA5LCAiMTQiOiAxMCwgIjE1IjogMTEsICIxNiI6IDEyLCAiMTciOiAxMwogICAgICAgICAgICAgICAgfQogICAgICAgICAgICAgICAgaXRlbSA9IFNFQVJDSF9DQVRBTE9HW2lkeF9tYXBbY2hvaWNlXV0KICAgICAgICAgICAgICAgIGZsb3dfc2luZ2xlX3NlYXJjaCgqaXRlbSkKCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIxOCI6CiAgICAgICAgICAgICAgICBmbG93X2JhdGNoX3NlYXJjaCgpCgogICAgICAgICAgICAjIOKUgOKUgCBVdGlsaXR5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBlbGlmIGNob2ljZSA9PSAiMjAiOgogICAgICAgICAgICAgICAgZmxvd19jaGVja19iYWxhbmNlKCkKCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIyMSI6CiAgICAgICAgICAgICAgICBmbG93X3ZpZXdfdXNhZ2UoKQoKICAgICAgICAgICAgZWxpZiBjaG9pY2UgPT0gIjIyIjoKICAgICAgICAgICAgICAgIGZsb3dfY2hlY2tfc3RhdHVzKCkKCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIyMyI6CiAgICAgICAgICAgICAgICBmbG93X3ZpZXdfZG9jcygpCgogICAgICAgICAgICBlbGlmIGNob2ljZSA9PSAiMjQiOgogICAgICAgICAgICAgICAgZmxvd19ob3dfdG9fYnV5KCkKCiAgICAgICAgICAgIGVsaWYgY2hvaWNlID09ICIyNSI6CiAgICAgICAgICAgICAgICBmbG93X3N1cHBvcnQoKQoKICAgICAgICAgICAgZWxpZiBjaG9pY2UgPT0gIjI2IjoKICAgICAgICAgICAgICAgIGZsb3dfdmlld19zYXZlZCgpCgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgd2FybihmIkludmFsaWQgb3B0aW9uOiAne2Nob2ljZX0nLiBQbGVhc2UgZW50ZXIgYSBudW1iZXIgZnJvbSB0aGUgbWVudS4iKQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgZXhjZXB0IEtleWJvYXJkSW50ZXJydXB0OgogICAgICAgICAgICBwcmludCgpCiAgICAgICAgICAgIHdhcm4oIkludGVycnVwdGVkLiBQcmVzcyBDdHJsK0MgYWdhaW4gdG8gZXhpdCBvciBFbnRlciB0byBjb250aW51ZS4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbnB1dChmIiAge0MuQkxLfVByZXNzIEVudGVyIHRvIGNvbnRpbnVlLi4ue0MuUn0iKQogICAgICAgICAgICBleGNlcHQgS2V5Ym9hcmRJbnRlcnJ1cHQ6CiAgICAgICAgICAgICAgICBwcmludCgpCiAgICAgICAgICAgICAgICBvaygiRXhpdGluZy4gU3RheSBzZWN1cmUhIikKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIGV4Y2VwdCBFT0ZFcnJvcjoKICAgICAgICAgICAgcHJpbnQoKQogICAgICAgICAgICBvaygiRU9GIGRldGVjdGVkIOKAlCBleGl0aW5nLiIpCiAgICAgICAgICAgIGJyZWFrCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgZXJyKGYiVW5leHBlY3RlZCBlcnJvcjoge2V9IikKICAgICAgICAgICAgaW5mbygiSWYgdGhpcyBwZXJzaXN0cywgY29udGFjdCB5YWRpaWZ5QGdtYWlsLmNvbSIpCgogICAgICAgICMgUGF1c2UgYWZ0ZXIgZXZlcnkgYWN0aW9uCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBOQVJST1c6CiAgICAgICAgICAgICAgICBwcmludCgpCiAgICAgICAgICAgICAgICBpbnB1dChmIiAge0MuQkxLfeKUgOKUgOKUgCBQcmVzcyBFbnRlciB0byBjb250aW51ZSDilIDilIDilIB7Qy5SfSIpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBpbnB1dChmIlxuICB7Qy5CTEt9UHJlc3MgRW50ZXIgdG8gcmV0dXJuIHRvIG1lbnUuLi57Qy5SfSIpCiAgICAgICAgZXhjZXB0IChLZXlib2FyZEludGVycnVwdCwgRU9GRXJyb3IpOgogICAgICAgICAgICBwYXNzCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBFTlRSWSBQT0lOVAojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaWYgX19uYW1lX18gPT0gIl9fbWFpbl9fIjoKICAgIHRyeToKICAgICAgICBtYWluKCkKICAgIGV4Y2VwdCBLZXlib2FyZEludGVycnVwdDoKICAgICAgICBwcmludChmIlxuICB7Qy5XUk59WyFdIFRlcm1pbmF0ZWQgYnkgdXNlci57Qy5SfVxuIikKICAgICAgICBzeXMuZXhpdCgwKQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIHByaW50KGYiXG4gIHtDLkVSUn1bIV0gRmF0YWwgZXJyb3I6IHtlfXtDLlJ9IikKICAgICAgICBwcmludChmIiAge0MuQkxLfUNvbnRhY3QgeWFkaWlmeUBnbWFpbC5jb20gaWYgdGhpcyBwZXJzaXN0cy57Qy5SfVxuIikKICAgICAgICBzeXMuZXhpdCgxKQo="
)

_INSTRUCTIONS_B64 = (
    "4pWU4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWXCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgICAgICAgIERBUktCT1hFUyBJTlRFTExJR0VOQ0UgU1lTVEVNICAgICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWRICAgICAgICBUZXJtaW5hbCBDbGllbnQg4oCUIEluc3RhbGxhdGlvbiAmIFVzYWdlIEd1aWRlICAgICAgICAgICAgICDilZEK4pWRICAgICAgICBWZXJzaW9uIDMuMCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg4pWRCuKVkSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgIFN1cHBvcnQgIDogQGRhcmtib3hlc0FkbWluIChUZWxlZ3JhbSkgICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWRICBFbWFpbCAgICA6IHlhZGlpZnlAZ21haWwuY29tICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg4pWRCuKVkSAgQ2hhbm5lbCAgOiBAZGFya2JveGVzdjEgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIOKVkQrilZEgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICDilZEK4pWa4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWdCgoK4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBClNFQ1RJT04gMTogUkVRVUlSRU1FTlRTCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQoKICDigKIgUHl0aG9uIDMuOCBvciBhYm92ZQogIOKAoiBwaXAgKFB5dGhvbiBwYWNrYWdlIG1hbmFnZXIsIGNvbWVzIHdpdGggUHl0aG9uKQogIOKAoiBJbnRlcm5ldCBjb25uZWN0aW9uCiAg4oCiIEEgRGFya0JveGVzIGFjY291bnQgKEFjY291bnQgSUQgKyBQYXNzd29yZCkKICDigKIgTk8gVGVsZWdyYW0gYWNjb3VudCByZXF1aXJlZAoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDI6IElOU1RBTExBVElPTgrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEKCk9OIFRFUk1VWCAoQW5kcm9pZCkK4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgU3RlcCAxOiBPcGVuIFRlcm11eAogIAogIFN0ZXAgMjogVXBkYXRlIHBhY2thZ2VzIGFuZCBpbnN0YWxsIFB5dGhvbgogICAgcGtnIHVwZGF0ZSAmJiBwa2cgdXBncmFkZQogICAgcGtnIGluc3RhbGwgcHl0aG9uCgogIFN0ZXAgMzogSW5zdGFsbCByZXF1aXJlZCBsaWJyYXJ5CiAgICBwaXAgaW5zdGFsbCByZXF1ZXN0cwoKICBTdGVwIDQ6IENvcHkgdGhlIGNsaWVudCBzY3JpcHQgdG8gVGVybXV4CiAgICAtIERvd25sb2FkIGRhcmtib3hlc19jbGllbnQucHkgZnJvbSB0aGUgVGVsZWdyYW0gYm90CiAgICAgIChUYXAgIkRvd25sb2FkIENsaWVudCBTY3JpcHQiIGluIHRoZSBib3QgbWVudSkKICAgIC0gT3IgdHJhbnNmZXIgaXQgbWFudWFsbHkgdG8geW91ciBUZXJtdXggaG9tZSBkaXJlY3RvcnkKCiAgU3RlcCA1OiBSdW4gdGhlIGNsaWVudAogICAgcHl0aG9uIGRhcmtib3hlc19jbGllbnQucHkKCiAgVEVSTVVYIFRJUFM6CiAg4oCiIElmIHRleHQgbG9va3MgY3JhbXBlZCwgdHVybiB5b3VyIHBob25lIHRvIGxhbmRzY2FwZSBtb2RlLgogIOKAoiBUaGUgY2xpZW50IGF1dG8tZGV0ZWN0cyBuYXJyb3cgdGVybWluYWxzIGFuZCB1c2VzIDItbGluZQogICAgZGlzcGxheSBtb2RlIGZvciBtZW51cyBhbmQgcHJvbXB0cy4KICDigKIgWW91IGNhbiBpbmNyZWFzZSBmb250IHNpemUgaW4gVGVybXV4IHNldHRpbmdzLgoKCk9OIExJTlVYIC8gS0FMSSAvIFVCVU5UVSAvIERFQklBTgrilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICBTdGVwIDE6IEluc3RhbGwgUHl0aG9uIChpZiBub3QgcHJlc2VudCkKICAgIHN1ZG8gYXB0IGluc3RhbGwgcHl0aG9uMyBweXRob24zLXBpcAoKICBTdGVwIDI6IEluc3RhbGwgcmVxdWlyZWQgbGlicmFyeQogICAgcGlwMyBpbnN0YWxsIHJlcXVlc3RzCgogIFN0ZXAgMzogUnVuIHRoZSBjbGllbnQKICAgIHB5dGhvbjMgZGFya2JveGVzX2NsaWVudC5weQoKCk9OIFdJTkRPV1MgKFBvd2VyU2hlbGwgLyBDTUQpCuKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogIFN0ZXAgMTogRG93bmxvYWQgUHl0aG9uIGZyb20gaHR0cHM6Ly9weXRob24ub3JnCiAgICAgICAgICBDaGVjayAiQWRkIFB5dGhvbiB0byBQQVRIIiBkdXJpbmcgaW5zdGFsbAoKICBTdGVwIDI6IEluc3RhbGwgcmVxdWlyZWQgbGlicmFyeQogICAgcGlwIGluc3RhbGwgcmVxdWVzdHMKCiAgU3RlcCAzOiBSdW4gdGhlIGNsaWVudAogICAgcHl0aG9uIGRhcmtib3hlc19jbGllbnQucHkKCgpPTiBtYWNPUwrilIDilIDilIDilIDilIDilIDilIDilIAKICBTdGVwIDE6IEluc3RhbGwgUHl0aG9uCiAgICBicmV3IGluc3RhbGwgcHl0aG9uICAob3IgZG93bmxvYWQgZnJvbSBweXRob24ub3JnKQoKICBTdGVwIDI6IEluc3RhbGwgcmVxdWlyZWQgbGlicmFyeQogICAgcGlwMyBpbnN0YWxsIHJlcXVlc3RzCgogIFN0ZXAgMzogUnVuIHRoZSBjbGllbnQKICAgIHB5dGhvbjMgZGFya2JveGVzX2NsaWVudC5weQoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDM6IEdFVFRJTkcgU1RBUlRFRCAoRklSU1QgUlVOKQrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEKCllvdSBkbyBOT1QgbmVlZCBhIFRlbGVncmFtIGFjY291bnQgdG8gdXNlIHRoZSB0ZXJtaW5hbCBjbGllbnQuCgpPUFRJT04gQTogUmVnaXN0ZXIgZGlyZWN0bHkgaW4gdGhlIGNsaWVudAogIDEuIFJ1bjogcHl0aG9uIGRhcmtib3hlc19jbGllbnQucHkKICAyLiBDaG9vc2UgWzFdIFJlZ2lzdGVyIE5ldyBBY2NvdW50CiAgMy4gRW50ZXIgYSB1c2VybmFtZSBhbmQgcGFzc3dvcmQKICA0LiBZb3VyIEFjY291bnQgSUQgd2lsbCBiZSBzaG93biDigJQgU0FWRSBJVC4KICA1LiBDb250YWN0IEBkYXJrYm94ZXNBZG1pbiB0byBwdXJjaGFzZSBjcmVkaXRzL3BsYW5zLgoKT1BUSU9OIEI6IEdldCBjcmVkZW50aWFscyBmcm9tIHRoZSBUZWxlZ3JhbSBib3QgKGlmIHlvdSB1c2UgVEcpCiAgMS4gT3BlbiBvdXIgVGVsZWdyYW0gYm90LgogIDIuIFRhcCAiR2V0IE15IExvZ2luIENyZWRlbnRpYWxzIiAo8J+Xne+4jykgaW4gdGhlIG1haW4gbWVudS4KICAzLiBOb3RlIHlvdXIgQWNjb3VudCBJRCBhbmQgcGFzc3dvcmQuCiAgNC4gVXNlIHRoZW0gdG8gbG9nIGluIHdpdGggb3B0aW9uIFsyXSBpbiB0aGUgY2xpZW50LgoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDQ6IEhPVyBUTyBCVVkgQ1JFRElUUyAvIFBMQU5TCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQoKTUVUSE9EIDEg4oCUIFZpYSBUZWxlZ3JhbSBCb3QKICAxLiBPcGVuIHRoZSBEYXJrQm94ZXMgVGVsZWdyYW0gYm90LgogIDIuIFRhcCDwn5KOIFByZW1pdW0gUGxhbnMuCiAgMy4gU2VsZWN0IGEgcGxhbi4KICA0LiBQYXkgdmlhIFVQSTogZHVyZ2VzaHJhaWhlcm9Ab2tzYmkKICA1LiBBZnRlciBwYXltZW50LCBlbnRlciB5b3VyIFVUUiAvIFRyYW5zYWN0aW9uIE51bWJlcgogICAgIChzaG93biBpbiB5b3VyIFVQSSBhcHAg4oCUIFBob25lUGUsIEdQYXksIFBheXRtLCBldGMuKQogIDYuIEFkbWluIHZlcmlmaWVzIG1hbnVhbGx5IOKAlCBhY3RpdmF0ZWQgd2l0aGluIDXigJMxNSBtaW51dGVzLgoKTUVUSE9EIDIg4oCUIERpcmVjdCBDb250YWN0CiAgQ29udGFjdDogQGRhcmtib3hlc0FkbWluIChUZWxlZ3JhbSkKICBFbWFpbCAgOiB5YWRpaWZ5QGdtYWlsLmNvbQogIFByb3ZpZGU6IHlvdXIgQWNjb3VudCBJRCArIHBheW1lbnQgcHJvb2YgKFVUUiBudW1iZXIpCgpBVkFJTEFCTEUgUExBTlMKICDimqEgU3RhcnRlciBQYWNrICAgICAgNSBzZWFyY2hlcyAgICAg4oK5MTAwICAobm8gZXhwaXJ5KQogIPCflI0gRXhwbG9yZXIgUGFjayAgICAxNSBzZWFyY2hlcyAgICAg4oK5MjUwICAobm8gZXhwaXJ5KQogIPCfmoAgRGFpbHkgMTAvMzBkICAgICAxMC9kYXnCtzMwIGRheXMgIOKCuTgwMAogIPCfko4gRGFpbHkgMjAvMzBkICAgICAyMC9kYXnCtzMwIGRheXMgIOKCuTEwMDAKICDwn4yfIERhaWx5IDEwLzJtICAgICAgMTAvZGF5wrc2MCBkYXlzICDigrkxNTAwCiAg8J+RkSBEYWlseSAyMC8ybSAgICAgIDIwL2RhecK3NjAgZGF5cyAg4oK5MTgwMAoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDU6IEFWQUlMQUJMRSBTRUFSQ0hFUwrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEKCiAgT3B0aW9uICBTZWFyY2ggVHlwZSAgICAgICAgICAgSW5wdXQgRXhhbXBsZQogIOKUgOKUgOKUgOKUgOKUgOKUgCAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAICDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICBbNF0gICAgIFBob25lIEludGVsbGlnZW5jZSAgICA5ODc2NTQzMjEwCiAgWzVdICAgICBGYW1pbHkgTmV0d29yayAgICAgICAgMTIzNDU2Nzg5MDEyIChBYWRoYXIpCiAgWzZdICAgICBBYWRoYXIgQ29tcHJlaGVuc2l2ZSAgMTIzNDU2Nzg5MDEyCiAgWzddICAgICBWZWhpY2xlIEludGVsbGlnZW5jZSAgVVA1M0NaMzM5MQogIFs4XSAgICAgVGVsZWdyYW0gSW50ZWxsaWdlbmNlIEB1c2VybmFtZQogIFs5XSAgICAgRGV2aWNlIElNRUkgICAgICAgICAgIDM1NDY3ODkwMTIzNDU2NwogIFsxMF0gICAgR1NUIEludGVsbGlnZW5jZSAgICAgIDI3QUFQRlUwOTM5RjFaVgogIFsxMV0gICAgSW5zdGFncmFtICAgICAgICAgICAgIHVzZXJuYW1lCiAgWzEyXSAgICBJUCBJbnRlbGxpZ2VuY2UgICAgICAgMS4yLjMuNAogIFsxM10gICAgSUZTQyBDb2RlICAgICAgICAgICAgIFNCSU4wMDAxMjM0CiAgWzE0XSAgICBFbWFpbCBJbnRlbGxpZ2VuY2UgICAgdXNlckBleGFtcGxlLmNvbQogIFsxNV0gICAgVVBJIEludGVsbGlnZW5jZSAgICAgIHVzZXJAdXBpCiAgWzE2XSAgICBQYWtpc3RhbiBEQiAgICAgICAgICAgbmFtZSAvIHBob25lIC8gTklDCiAgWzE3XSAgICBBZHZhbmNlZCBPU0lOVC9MZWFrICAgYW55IHF1ZXJ5CiAgWzE4XSAgICBCYXRjaCBTZWFyY2ggICAgICAgICAgbXVsdGlwbGUgYXQgb25jZQoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpTRUNUSU9OIDY6IFNBVkVEIFJFU1VMVFMK4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBCgpBbGwgc2VhcmNoIHJlc3VsdHMgYXJlIGF1dG9tYXRpY2FsbHkgc2F2ZWQgYXMgSlNPTiBmaWxlcyBpbjoKICB+L2Rhcmtib3hlc19yZXN1bHRzLwoKWW91IGNhbiB2aWV3IHRoZW0gd2l0aCBvcHRpb24gWzI2XSBpbiB0aGUgbWVudSwgb3Igb3Blbgp0aGUgSlNPTiBmaWxlcyBkaXJlY3RseS4KCgrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEKU0VDVElPTiA3OiBTRUNVUklUWSBOT1RJQ0VTCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQoKICDigKIgTmV2ZXIgc2hhcmUgeW91ciBwYXNzd29yZCB3aXRoIGFueW9uZSwgaW5jbHVkaW5nIGFkbWluLgogIOKAoiBPZmZpY2lhbCBhZG1pbjogQGRhcmtib3hlc0FkbWluIE9OTFkuCiAg4oCiIEJld2FyZSBvZiBpbXBlcnNvbmF0b3JzLgogIOKAoiBUaGlzIHNlcnZpY2UgaXMgZm9yIGF1dGhvcml6ZWQsIGxhd2Z1bCB1c2Ugb25seS4KICDigKIgTWlzdXNlIG1heSByZXN1bHQgaW4gYWNjb3VudCB0ZXJtaW5hdGlvbi4KCgrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEKU0VDVElPTiA4OiBUUk9VQkxFU0hPT1RJTkcK4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSB4pSBCgogIFByb2JsZW06ICJNb2R1bGVOb3RGb3VuZEVycm9yOiBObyBtb2R1bGUgbmFtZWQgJ3JlcXVlc3RzJyIKICBGaXggICAgOiBSdW4gIHBpcCBpbnN0YWxsIHJlcXVlc3RzCgogIFByb2JsZW06ICJDb25uZWN0aW9uIGZhaWxlZCIgb3IgIlRpbWVvdXQiCiAgRml4ICAgIDogQ2hlY2sgaW50ZXJuZXQuIFRyeSBhZ2FpbiBpbiBhIG1vbWVudC4KICAgICAgICAgICBTZXJ2ZXIgbWF5IGJlIHRlbXBvcmFyaWx5IGJ1c3kuCgogIFByb2JsZW06ICJJbnZhbGlkIGNyZWRlbnRpYWxzIgogIEZpeCAgICA6IENoZWNrIEFjY291bnQgSUQgYW5kIHBhc3N3b3JkIGNhcmVmdWxseS4KICAgICAgICAgICBBY2NvdW50IElEIHN0YXJ0cyB3aXRoIERCLCBlLmcuIERCMUEyQjNDNEQuCgogIFByb2JsZW06ICJJbnN1ZmZpY2llbnQgY3JlZGl0cyIKICBGaXggICAgOiBCdXkgY3JlZGl0cyB2aWEgb3B0aW9uIFsyNF0gaW4gdGhlIG1lbnUuCgogIFByb2JsZW06IERpc3BsYXkgbG9va3Mgd3JvbmcgaW4gVGVybXV4CiAgRml4ICAgIDogVGhlIGNsaWVudCBhdXRvLWFkanVzdHMgZm9yIG5hcnJvdyBzY3JlZW5zLgogICAgICAgICAgIFRyeSBsYW5kc2NhcGUgbW9kZSBvciBpbmNyZWFzZSB0ZXJtaW5hbCB3aWR0aC4KCiAgU3RpbGwgc3R1Y2s/IENvbnRhY3Q6CiAgICBUZWxlZ3JhbSA6IEBkYXJrYm94ZXNBZG1pbgogICAgRW1haWwgICAgOiB5YWRpaWZ5QGdtYWlsLmNvbQoKCuKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgeKUgQpEQVJLQk9YRVMgSU5URUxMSUdFTkNFIFNZU1RFTSAgwqkyMDI1ICBBbGwgcmlnaHRzIHJlc2VydmVkLgrilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIHilIEK"
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
                    "❓ Help: @darkboxesAdmin | yadiify@gmail.com"
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
            f"❓ Help: @darkboxesAdmin | yadiify@gmail.com",
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
            f"🔑 **Password:** *(set when account was created)*\n"
            f"💰 **Credits:** {credits}\n"
            f"📦 **Plan:** {sub}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚠️ If you forgot your password, contact @darkboxesAdmin.\n\n"
            f"💻 **Use in client:**\n"
            f"1. Run `python darkboxes_client.py`\n"
            f"2. Enter Account ID: `{acc_id}`\n"
            f"3. Enter your password\n\n"
            f"🔒 Never share your password with anyone.\n"
            f"Official support only: @darkboxesAdmin | yadiify@gmail.com"
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
                 "success": 1, "credits_used": 1}
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

            # Mask sensitive query data
            if len(query) > 12:
                masked = query[:4] + "****" + query[-3:]
            else:
                masked = query[:3] + "****"

            text += (
                f"{i}. {success} **{stype}** — `{masked}`\n"
                f"   👤 UID: `{uid}` • 🕐 {ts} • 💳 {credits}cr\n\n"
            )

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
                {"search_type": 1, "query": 1, "timestamp": 1, "success": 1, "credits_used": 1}
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

            text += (
                f"{i}. {success} **{stype}**\n"
                f"   Query: `{query}`\n"
                f"   🕐 {ts} • 💳 {credits}cr\n\n"
            )

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


async def main():
    """Main function"""
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
                logger.error("❌ User client not authorized")
                return
            logger.info("✅ User client ready")
        else:
            logger.info("ℹ️ Using bot client for all operations")
        
        # Connect to database
        if not await db_manager.connect():
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
        
        # Start background tasks
        asyncio.create_task(cleanup_expired_searches())
        asyncio.create_task(start_web_server())
        asyncio.create_task(daily_subscription_reset())
        
        logger.info("=" * 60)
        logger.info("🎭 DARK BOXES INTELLIGENCE SYSTEM - OPERATIONAL")
        logger.info("=" * 60)
        
        # Keep the bot running
        await bot_client.run_until_disconnected()
        
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    except Exception as e:
        logger.error(f"💀 Fatal error: {e}")
        logger.error(traceback.format_exc())
    finally:
        # Clean shutdown
        try:
            await bot_client.disconnect()
            if USE_USER_ACCOUNT:
                await user_client.disconnect()
            if db_manager.client:
                db_manager.client.close()
        except:
            pass

if __name__ == "__main__":
    # Set event loop policy for Windows if needed
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # Run the bot
    asyncio.run(main())
