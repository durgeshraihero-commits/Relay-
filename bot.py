"""
DarkBoxes Intelligence System - Premium Edition with API Support
Advanced information retrieval with premium interface
Professional Admin Panel and API Management
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
import traceback
import hashlib
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
    NEW_USER_CREDITS: int = int(os.getenv("NEW_USER_CREDITS", "1"))
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

# ================== GROUP PRIORITY MANAGEMENT ==================

GROUP_PRIORITIES = {
    "primary": {
        "name": "⚡ Premium Database",
        "identifier": -1003596998816,
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
        "identifier": "nex_chats",
        "timeout": 40,
        "weight": 5,
        "enabled": True,
        "entity": None
    },
    "advanced": {
        "name": "🚀 Advanced OSINT Engine",
        "identifier": "IntelXGroup",
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
    "basic": {
        "name": "💰 BASIC TIER",
        "price": 99,
        "searches": 10,
        "validity": "7 days",
        "features": ["10 Premium Searches", "Standard Databases", "7-day Access", "Email Support"],
        "icon": "💰",
        "color": "#27AE60",
        "for": "New users trying the service"
    },
    "standard": {
        "name": "🚀 STANDARD TIER",
        "price": 249,
        "searches": 30,
        "validity": "15 days",
        "features": ["30 Premium Searches", "All Databases", "15-day Access", "Priority Support", "Search History Saved"],
        "icon": "🚀",
        "color": "#F39C12",
        "for": "Regular users needing more searches"
    },
    "premium": {
        "name": "👑 PREMIUM TIER",
        "price": 499,
        "searches": "Unlimited",
        "validity": "30 days",
        "features": ["Unlimited Searches (30 days)", "All Premium Databases", "Priority Processing", "24/7 WhatsApp Support", "Extended Search History"],
        "icon": "👑",
        "color": "#9B59B6",
        "for": "Power users & professionals"
    }
}

# ================== API PLANS ==================

API_PLANS = {
    "basic": {
        "name": "🔑 Basic API Access",
        "price": 999,
        "requests": 1000,
        "validity_days": 30,
        "concurrent": 1,
        "rate_limit": 10,
        "features": ["1000 API requests", "30-day access", "Basic endpoints", "Email support"],
        "unlimited": False
    },
    "professional": {
        "name": "⚡ Professional API",
        "price": 2499,
        "requests": 5000,
        "validity_days": 30,
        "concurrent": 3,
        "rate_limit": 30,
        "features": ["5000 API requests", "30-day access", "All endpoints", "Priority support", "Webhook support"],
        "unlimited": False
    },
    "enterprise": {
        "name": "🏢 Enterprise API",
        "price": 4999,
        "requests": "Unlimited",
        "validity_days": 30,
        "concurrent": 10,
        "rate_limit": 100,
        "features": ["Unlimited requests", "30-day access", "All endpoints", "24/7 support", "Custom endpoints", "Bulk processing"],
        "unlimited": True
    },
    "unlimited": {
        "name": "🚀 Unlimited API",
        "price": 999,
        "requests": "Unlimited",
        "validity_days": 30,
        "concurrent": 5,
        "rate_limit": 50,
        "features": ["Unlimited searches (30 days)", "All endpoints", "Priority processing", "Email support"],
        "unlimited": True
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
    "upi": {
        "name": "💳 UPI Financial Intelligence",
        "description": "💰 **UPI Account & Transaction Analysis**\n\n🔸 **Input:** UPI ID (username@paytm/bank)\n🔸 **Returns:** Account holder • Linked bank • Transaction patterns • KYC status • Last active\n🔸 **Sources:** NPCI databases • Bank records • Financial institutions\n🔸 **Security:** Bank-grade encryption",
        "commands": ["/upiinfo", "/upiinfo"],
        "example": "username@paytm",
        "validation": r"^[\w\.-]+@[\w\.-]+$",
        "cost": 1,
        "priority": "secondary",
        "icon": "💳",
        "category": "finance"
    },
    "email": {
        "name": "📧 Email Intelligence",
        "description": "🖥️ **Complete Email Profile Analysis**\n\n🔸 **Input:** Email address\n🔸 **Returns:** Personal information • Social media links • Data breach history • Associated accounts • Location data\n🔸 **Sources:** Breach databases • Social media • Public records\n🔸 **Monitoring:** Real-time alerts",
        "commands": ["/email", "/mail"],
        "example": "user@example.com",
        "validation": r"^[\w\.-]+@[\w\.-]+\.\w+$",
        "cost": 1,
        "priority": "secondary",
        "icon": "📧",
        "category": "digital"
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
    "pak": {
        "name": "🌐 Pakistan Intelligence",
        "description": "🕌 **Pakistan Number Comprehensive Analysis**\n\n🔸 **Input:** Pakistan mobile number (+92 format)\n🔸 **Returns:** Complete subscriber information • Location • Network details • Registration data\n🔸 **Sources:** International telecom databases • Government records\n🔸 **Coverage:** All major Pakistani networks",
        "commands": ["/pak", "/pk"],
        "example": "+923001234567",
        "validation": r"^\+92\d{10}$",
        "cost": 3,
        "priority": "tertiary",
        "icon": "🌐",
        "category": "international"
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
    "leak": {
        "name": "🚀 ADVANCED OSINT TOOL",
        "description": "🔮 **SEARCH ANYTHING - MOST POWERFUL TOOL**\n\n🔸 **Universal Search:** Email • Phone (with country code) • Name • Document • Username • Any query\n🔸 **Format:** Phone must include country code (e.g., 917204764637)\n🔸 **Returns:** Comprehensive results in JSON + TXT format\n🔸 **Speed:** Ultra-fast 5-second response\n🔸 **Sources:** Deep web • Breach databases • Global intelligence\n🔸 **Cost:** 3 credits per search",
        "commands": ["/leak"],
        "example": "917204764637 or email@domain.com or John Doe",
        "validation": r"^.+$",  # Accepts any input
        "cost": 3,
        "priority": "advanced",
        "icon": "🚀",
        "category": "advanced",
        "group": "advanced"
    }
}

# ================== API COMMANDS ==================

API_COMMANDS = {
    "phone": {"endpoint": "/api/v1/search/phone", "method": "POST", "cost": 1},
    "family": {"endpoint": "/api/v1/search/family", "method": "POST", "cost": 1},
    "aadhar": {"endpoint": "/api/v1/search/aadhar", "method": "POST", "cost": 2},
    "vehicle": {"endpoint": "/api/v1/search/vehicle", "method": "POST", "cost": 2},
    "upi": {"endpoint": "/api/v1/search/upi", "method": "POST", "cost": 1},
    "email": {"endpoint": "/api/v1/search/email", "method": "POST", "cost": 1},
    "telegram": {"endpoint": "/api/v1/search/telegram", "method": "POST", "cost": 2},
    "imei": {"endpoint": "/api/v1/search/imei", "method": "POST", "cost": 2},
    "gst": {"endpoint": "/api/v1/search/gst", "method": "POST", "cost": 1},
    "insta": {"endpoint": "/api/v1/search/instagram", "method": "POST", "cost": 1},
    "pak": {"endpoint": "/api/v1/search/pakistan", "method": "POST", "cost": 3},
    "ip": {"endpoint": "/api/v1/search/ip", "method": "POST", "cost": 1},
    "ifsc": {"endpoint": "/api/v1/search/ifsc", "method": "POST", "cost": 1},
    "leak": {"endpoint": "/api/v1/search/leak", "method": "POST", "cost": 3},
    "batch": {"endpoint": "/api/v1/search/batch", "method": "POST"},
    "status": {"endpoint": "/api/v1/status", "method": "GET"},
    "balance": {"endpoint": "/api/v1/balance", "method": "GET"},
    "usage": {"endpoint": "/api/v1/usage", "method": "GET"},
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

# ================== API RESPONSE FORMATTER ==================

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

# ================== API DATABASE MANAGER ==================

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

class AdminDatabaseManager:
    def __init__(self, db_manager):
        self.db = db_manager.db
        self.api_db = APIDatabaseManager(db_manager)
    
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
        
        # API stats today
        api_logs = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.api_logs.find({
                "timestamp": {"$gte": today.isoformat()}
            }))
        )
        
        return {
            "new_users": new_users,
            "total_searches": len(search_logs),
            "total_payments": total_payments,
            "payment_count": len(payments),
            "api_requests": len(api_logs)
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
        
        # User's API keys
        api_keys = await self.api_db.get_user_api_keys(user_id)
        
        return {
            "user_info": user,
            "total_searches": len(user_searches),
            "referrals": referrals,
            "api_keys": api_keys,
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
    
    async def get_api_stats_detailed(self) -> Dict:
        """Get detailed API statistics"""
        try:
            api_stats = await self.api_db.get_api_stats()
            
            # API key distribution by plan
            pipeline = [
                {"$group": {
                    "_id": "$plan_id",
                    "count": {"$sum": 1},
                    "total_requests": {"$sum": "$total_requests"},
                    "active_keys": {"$sum": {"$cond": [{"$eq": ["$is_active", True]}, 1, 0]}}
                }},
                {"$sort": {"count": -1}}
            ]
            
            plan_distribution = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.api_keys.aggregate(pipeline))
            )
            
            # Daily API requests (last 30 days)
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            
            daily_pipeline = [
                {"$match": {"timestamp": {"$gte": thirty_days_ago.isoformat()}}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$toDate": "$timestamp"}}},
                    "count": {"$sum": 1},
                    "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
                    "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}}
                }},
                {"$sort": {"_id": 1}},
                {"$limit": 30}
            ]
            
            daily_requests = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.api_logs.aggregate(daily_pipeline))
            )
            
            # Top endpoints
            endpoint_pipeline = [
                {"$group": {
                    "_id": "$endpoint",
                    "count": {"$sum": 1},
                    "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
                    "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}}
                }},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]
            
            top_endpoints = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.api_logs.aggregate(endpoint_pipeline))
            )
            
            return {
                "summary": api_stats,
                "plan_distribution": plan_distribution,
                "daily_requests": daily_requests,
                "top_endpoints": top_endpoints
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting detailed API stats: {e}")
            return {}

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
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.create_index([("api_key", 1)], unique=True)
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.create_index([("client_token", 1)], unique=True)
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.create_index([("user_id", 1)])
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_keys.create_index([("expires_at", 1)])
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_logs.create_index([("timestamp", -1)])
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.api_logs.create_index([("api_key", 1)])
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
                "is_admin": False,
                "has_api_access": False,
                "api_plan": None
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
                expiry_date = datetime.fromisoformat(subscription_expiry)
                if expiry_date > datetime.now(timezone.utc):
                    # User has active subscription
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: self.db.users.update_one(
                            {"user_id": user_id},
                            {
                                "$inc": {"total_searches": 1},
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
    
    async def add_api_access(self, user_id: int, plan_id: str, days: int) -> bool:
        """Add API access to user"""
        try:
            plan = API_PLANS.get(plan_id, API_PLANS["unlimited"])
            expiry_date = datetime.now(timezone.utc) + timedelta(days=days)
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "has_api_access": True,
                            "api_plan": plan_id,
                            "api_expiry": expiry_date.isoformat()
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
                "type": "api_access",
                "admin_added": True
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.payments.insert_one(payment_log)
            )
            
            return True
        except Exception as e:
            logger.error(f"❌ Error adding API access: {e}")
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

class OneLineKeyboard:
    @staticmethod
    def main_menu(is_admin: bool = False) -> List[List[Button]]:
        """Build keyboard with ONE COMMAND PER LINE"""
        buttons = []
        
        # Add each command in its own line
        commands_in_order = [
            "phone", "family", "aadhar", "vehicle", 
            "upi", "email", "telegram", "imei",
            "gst", "insta", "pak", "ip", "ifsc",
            "leak"  # Advanced OSINT tool - placed at the end for emphasis
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
        buttons.append([Button.inline("🔑 API Access", "api_menu")])
        buttons.append([Button.inline("📊 Refer & Earn", "referrals")])
        buttons.append([Button.inline("🆘 Support", "support")])
        
        # Add admin button if admin
        if is_admin:
            buttons.append([Button.inline("⚙️ Admin Panel", "admin_panel")])
        
        return buttons
    
    @staticmethod
    def subscription_plans() -> List[List[Button]]:
        """Premium plan selection"""
        buttons = [
            [Button.inline("💰 Basic Tier - ₹99", "plan_basic")],
            [Button.inline("🚀 Standard Tier - ₹249", "plan_standard")],
            [Button.inline("👑 Premium Tier - ₹499", "plan_premium")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        return buttons
    
    @staticmethod
    def api_menu() -> List[List[Button]]:
        """API menu"""
        buttons = [
            [Button.inline("🔐 My API Keys", "my_api_keys")],
            [Button.inline("📊 API Usage", "api_usage")],
            [Button.inline("🛒 Buy API Access", "api_plans")],
            [Button.inline("📖 API Documentation", "api_docs")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        return buttons
    
    @staticmethod
    def api_plans() -> List[List[Button]]:
        """API plan selection"""
        buttons = [
            [Button.inline("🚀 Unlimited API - ₹999", "api_plan_unlimited")],
            [Button.inline("🔑 Basic API - ₹999", "api_plan_basic")],
            [Button.inline("⚡ Professional API - ₹2499", "api_plan_professional")],
            [Button.inline("🏢 Enterprise API - ₹4999", "api_plan_enterprise")],
            [Button.inline("« API Menu", "api_menu")]
        ]
        return buttons
    
    @staticmethod
    def admin_panel() -> List[List[Button]]:
        """Professional admin panel with all features"""
        buttons = [
            [Button.inline("📊 Today's Stats", "admin_today")],
            [Button.inline("👥 User Management", "admin_users")],
            [Button.inline("📈 Search Analytics", "admin_analytics")],
            [Button.inline("💰 Payment Stats", "admin_payments")],
            [Button.inline("🔑 API Management", "admin_api")],
            [Button.inline("🔍 Search Users", "admin_search_user")],
            [Button.inline("📢 Broadcast", "admin_broadcast")],
            [Button.inline("⚙️ Bot Settings", "admin_settings")],
            [Button.inline("🚫 Ban/Unban User", "admin_ban")],
            [Button.inline("👑 Add/Remove Admin", "admin_admin")],
            [Button.inline("🎯 Add Credits", "admin_add_credits")],
            [Button.inline("📊 Export Data", "admin_export")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        return buttons
    
    @staticmethod
    def admin_api_panel() -> List[List[Button]]:
        """Admin API management panel"""
        buttons = [
            [Button.inline("📊 API Statistics", "admin_api_stats")],
            [Button.inline("🔑 Manage User API", "admin_api_user")],
            [Button.inline("📈 API Analytics", "admin_api_analytics")],
            [Button.inline("🚫 Revoke API Key", "admin_api_revoke")],
            [Button.inline("« Admin Panel", "admin_panel")]
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
            [Button.inline("🔑 API Access", "api_menu")],
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
    def api_keys_menu() -> List[List[Button]]:
        """API keys management menu"""
        return [
            [Button.inline("🔄 Refresh", "my_api_keys")],
            [Button.inline("➕ Create API Key", "create_api_key")],
            [Button.inline("📊 Usage Stats", "api_usage")],
            [Button.inline("« API Menu", "api_menu")]
        ]
    
    @staticmethod
    def confirm_api_creation(plan_id: str, days: int) -> List[List[Button]]:
        """Confirm API key creation"""
        return [
            [Button.inline(f"✅ Create {plan_id} API ({days} days)", f"confirm_create_api_{plan_id}_{days}")],
            [Button.inline("❌ Cancel", "api_menu")]
        ]

# ================== API HANDLER ==================

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

async def start_api_server():
    """Start API server"""
    if not config.API_ENABLED:
        logger.info("ℹ️ API server disabled")
        return
    
    app = web.Application()
    
    # Create API handler
    api_handler = APIHandler(db_manager, search_engine)
    
    # Health check endpoint
    async def health_check(request):
        return web.json_response({"status": "ok", "timestamp": datetime.now().isoformat()})
    
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
    
    # Add routes
    app.router.add_get('/health', health_check)
    app.router.add_get('/api/v1/health', health_check)
    
    # Search endpoints
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
    
    # Documentation endpoint
    async def documentation(request):
        docs = {
            "service": "DarkBoxes Intelligence API",
            "version": "2.0.0",
            "base_url": config.API_BASE_URL,
            "endpoints": {
                "search": {
                    "phone": {"method": "POST", "endpoint": "/api/v1/search/phone", "description": "Phone number intelligence"},
                    "family": {"method": "POST", "endpoint": "/api/v1/search/family", "description": "Family network analysis"},
                    "aadhar": {"method": "POST", "endpoint": "/api/v1/search/aadhar", "description": "Aadhar comprehensive search"},
                    "vehicle": {"method": "POST", "endpoint": "/api/v1/search/vehicle", "description": "Vehicle intelligence"},
                    "upi": {"method": "POST", "endpoint": "/api/v1/search/upi", "description": "UPI financial intelligence"},
                    "email": {"method": "POST", "endpoint": "/api/v1/search/email", "description": "Email intelligence"},
                    "telegram": {"method": "POST", "endpoint": "/api/v1/search/telegram", "description": "Telegram intelligence"},
                    "imei": {"method": "POST", "endpoint": "/api/v1/search/imei", "description": "Device intelligence"},
                    "gst": {"method": "POST", "endpoint": "/api/v1/search/gst", "description": "Business intelligence"},
                    "instagram": {"method": "POST", "endpoint": "/api/v1/search/instagram", "description": "Instagram intelligence"},
                    "pakistan": {"method": "POST", "endpoint": "/api/v1/search/pakistan", "description": "Pakistan number intelligence"},
                    "ip": {"method": "POST", "endpoint": "/api/v1/search/ip", "description": "IP location"},
                    "ifsc": {"method": "POST", "endpoint": "/api/v1/search/ifsc", "description": "IFSC code lookup"},
                    "leak": {"method": "POST", "endpoint": "/api/v1/search/leak", "description": "Advanced OSINT search"},
                    "batch": {"method": "POST", "endpoint": "/api/v1/search/batch", "description": "Batch search multiple queries"}
                },
                "utility": {
                    "status": {"method": "GET", "endpoint": "/api/v1/status", "description": "API status and limits"},
                    "balance": {"method": "GET", "endpoint": "/api/v1/balance", "description": "User credits and balance"},
                    "usage": {"method": "GET", "endpoint": "/api/v1/usage", "description": "API usage statistics"}
                }
            },
            "authentication": {
                "header": "X-API-Key: your_api_key",
                "query_param": "?api_key=your_api_key"
            },
            "example_request": {
                "curl": "curl -X POST -H 'X-API-Key: your_api_key' -H 'Content-Type: application/json' -d '{\"query\": \"9876543210\"}' " + config.API_BASE_URL + "/api/v1/search/phone"
            },
            "contact": {
                "admin": "@darkboxesAdmin",
                "channel": "@darkboxesv1"
            }
        }
        return web.json_response(docs)
    
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
    site = web.TCPSite(runner, '0.0.0.0', config.API_PORT)
    
    try:
        await site.start()
        logger.info(f"🌐 API server running on port {config.API_PORT}")
        logger.info(f"📚 API Documentation: {config.API_BASE_URL}/api/v1/docs")
        logger.info(f"🔑 Authentication: Use X-API-Key header or api_key query parameter")
    except Exception as e:
        logger.error(f"❌ API server failed: {e}")

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
            
            elif data == "admin_search_user":
                await self.ask_for_user_search(event)
            
            elif data == "admin_broadcast":
                await self.ask_for_broadcast(event)
            
            elif data == "admin_ban":
                await self.ask_for_ban_user(event)
            
            elif data == "admin_admin":
                await self.ask_for_admin_management(event)
            
            elif data == "admin_add_credits":
                await self.ask_for_add_credits(event)
            
            elif data == "admin_settings":
                await self.show_bot_settings(event)
            
            elif data == "admin_export":
                await self.export_data(event)
            
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
            
            elif data.startswith("confirm_create_api_"):
                # Handle API key creation confirmation
                parts = data.split("_")
                if len(parts) >= 5:
                    plan_id = parts[3]
                    days = int(parts[4])
                    await self.confirm_create_api_key(event, plan_id, days)
            
            elif data.startswith("confirm_revoke_api_"):
                api_key = data.split("_", 3)[3]
                await self.confirm_revoke_api_key(event, api_key)
            
            # API Menu Callbacks
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
    
    async def show_api_menu(self, event):
        """Show API menu"""
        api_text = (
            "🔑 **DARKBOXES API ACCESS**\n"
            "═══════════════════════\n\n"
            "🚀 **Programmatic Access** to all DarkBoxes intelligence tools\n\n"
            "🌟 **Features:**\n"
            "• RESTful API endpoints\n"
            "• JSON responses\n"
            "• Batch processing\n"
            "• Rate limiting\n"
            "• Webhook support\n"
            "• 24/7 availability\n\n"
            "💼 **Perfect For:**\n"
            "• Developers\n"
            "• OSINT tools\n"
            "• Automation scripts\n"
            "• Business integrations\n\n"
            "Select an option below:"
        )
        
        await event.edit(api_text, buttons=OneLineKeyboard.api_menu(), parse_mode="md")
    
    async def show_my_api_keys(self, event):
        """Show user's API keys"""
        try:
            user_id = event.sender_id
            api_keys = await self.db.api_db.get_user_api_keys(user_id)
            
            api_text = "🔑 **MY API KEYS**\n"
            api_text += "═══════════════════════\n\n"
            
            if api_keys:
                for i, api_key in enumerate(api_keys, 1):
                    status = "✅ Active" if api_key.get("is_active") else "❌ Inactive"
                    created = api_key.get("created_at", "")[:10]
                    expires = api_key.get("expires_at", "")[:10]
                    requests = api_key.get("requests_used", 0)
                    remaining = api_key.get("requests_remaining", 0)
                    unlimited = "♾️" if api_key.get("unlimited") else ""
                    
                    api_text += (
                        f"{i}. **{api_key.get('description', 'Unnamed')}** {unlimited}\n"
                        f"   ├─ Status: {status}\n"
                        f"   ├─ Plan: {api_key.get('plan_id', 'N/A')}\n"
                        f"   ├─ Key: `{api_key['api_key'][:8]}...{api_key['api_key'][-4:]}`\n"
                        f"   ├─ Created: {created}\n"
                        f"   ├─ Expires: {expires}\n"
                        f"   ├─ Requests: {requests} used, {remaining} remaining\n"
                        f"   └─ Token: `{api_key.get('client_token', 'N/A')}`\n\n"
                    )
                
                api_text += "📝 **Usage Instructions:**\n"
                api_text += f"• Base URL: `{config.API_BASE_URL}`\n"
                api_text += "• Add header: `X-API-Key: your_api_key`\n"
                api_text += "• Or query param: `?api_key=your_api_key`\n"
                api_text += "• See /api_docs for endpoint details\n"
            else:
                api_text += "📭 No API keys found.\n\n"
                api_text += "💡 **Get started:**\n"
                api_text += "1. Purchase API access from @darkboxesAdmin\n"
                api_text += "2. Once activated, create your API key\n"
                api_text += "3. Start integrating with your tools!\n"
            
            await event.edit(api_text, buttons=OneLineKeyboard.api_keys_menu(), parse_mode="md")
            
        except Exception as e:
            logger.error(f"❌ Error showing API keys: {e}")
            await event.edit("❌ Error loading API keys", buttons=OneLineKeyboard.api_menu())
    
    async def show_api_usage(self, event):
        """Show API usage statistics"""
        try:
            user_id = event.sender_id
            api_stats = await self.db.api_db.get_api_stats(user_id)
            
            usage_text = "📊 **API USAGE STATISTICS**\n"
            usage_text += "═══════════════════════\n\n"
            
            usage_text += f"📈 **Summary**\n"
            usage_text += f"├─ Total API Keys: {api_stats.get('total_keys', 0)}\n"
            usage_text += f"├─ Active Keys: {api_stats.get('active_keys', 0)}\n"
            usage_text += f"├─ Total Requests: {api_stats.get('total_requests', 0)}\n"
            usage_text += f"└─ Requests Used: {api_stats.get('requests_used', 0)}\n\n"
            
            if api_stats.get('recent_activity'):
                usage_text += "🕒 **Recent Activity**\n"
                for activity in api_stats['recent_activity'][:5]:
                    time_str = activity.get('timestamp', '')[:16]
                    endpoint = activity.get('endpoint', 'N/A')
                    success = "✅" if activity.get('success') else "❌"
                    
                    usage_text += f"{success} {time_str} - {endpoint}\n"
            
            usage_text += "\n📋 **Available Endpoints:**\n"
            for cmd_key, cmd_info in API_COMMANDS.items():
                if cmd_key not in ['batch', 'status', 'balance', 'usage']:
                    usage_text += f"• {cmd_info['endpoint']} ({cmd_info['method']})\n"
            
            await event.edit(usage_text, buttons=OneLineKeyboard.api_keys_menu(), parse_mode="md")
            
        except Exception as e:
            logger.error(f"❌ Error showing API usage: {e}")
            await event.edit("❌ Error loading API usage", buttons=OneLineKeyboard.api_menu())
    
    async def show_api_plans(self, event):
        """Show API plans"""
        api_text = "🛒 **API ACCESS PLANS**\n"
        api_text += "═══════════════════════\n\n"
        
        for plan_id, plan in API_PLANS.items():
            unlimited_symbol = "♾️" if plan.get('unlimited') else ""
            api_text += f"{plan.get('icon', '🔑')} **{plan['name']}** {unlimited_symbol}\n"
            api_text += f"💰 **Price:** ₹{plan['price']}\n"
            api_text += f"📊 **Requests:** {plan['requests']}\n"
            api_text += f"📅 **Validity:** {plan['validity_days']} days\n"
            api_text += f"⚡ **Rate Limit:** {plan['rate_limit']}/min\n"
            api_text += f"🔗 **Concurrent:** {plan['concurrent']}\n\n"
            
            api_text += "🌟 **Features:**\n"
            for feature in plan['features']:
                api_text += f"• {feature}\n"
            
            api_text += "\n" + "─" * 30 + "\n\n"
        
        api_text += "📞 **Contact @darkboxesAdmin to purchase API access**\n"
        api_text += f"💳 **UPI ID:** `{config.UPI_ID}`\n\n"
        api_text += "🔒 **Instructions:**\n"
        api_text += "1. Send payment via UPI\n"
        api_text += "2. Send screenshot to @darkboxesAdmin\n"
        api_text += "3. Include your User ID and desired plan\n"
        api_text += "4. API access will be activated within 5 minutes"
        
        await event.edit(api_text, buttons=OneLineKeyboard.api_plans(), parse_mode="md")
    
    async def show_api_plan_details(self, event, plan_id: str):
        """Show API plan details"""
        if plan_id not in API_PLANS:
            await event.answer("❌ Invalid plan", alert=True)
            return
        
        plan = API_PLANS[plan_id]
        unlimited_symbol = "♾️" if plan.get('unlimited') else ""
        
        plan_text = f"{plan.get('icon', '🔑')} **{plan['name']}** {unlimited_symbol}\n"
        plan_text += "═══════════════════════\n\n"
        
        plan_text += f"💰 **Price:** ₹{plan['price']}\n"
        plan_text += f"📊 **Requests:** {plan['requests']}\n"
        plan_text += f"📅 **Validity:** {plan['validity_days']} days\n"
        plan_text += f"⚡ **Rate Limit:** {plan['rate_limit']} requests/minute\n"
        plan_text += f"🔗 **Concurrent Connections:** {plan['concurrent']}\n\n"
        
        plan_text += "🌟 **Features:**\n"
        for feature in plan['features']:
            plan_text += f"• {feature}\n"
        
        plan_text += f"\n🎯 **Perfect For:** {plan.get('for', 'Developers and businesses')}\n\n"
        
        if plan.get('unlimited'):
            plan_text += "💡 **Unlimited Plan:**\n"
            plan_text += "• No request limits\n"
            plan_text += "• Best for high-volume usage\n"
            plan_text += "• Perfect for OSINT tools\n\n"
        
        plan_text += "📞 **To Purchase:**\n"
        plan_text += f"1. Send ₹{plan['price']} to UPI: `{config.UPI_ID}`\n"
        plan_text += f"2. Send payment screenshot to @darkboxesAdmin\n"
        plan_text += f"3. Include your User ID: `{event.sender_id}`\n"
        plan_text += f"4. Specify plan: {plan['name']}\n"
        plan_text += f"5. API access will be activated within 5 minutes\n\n"
        
        plan_text += "💡 **Note:** Contact @darkboxesAdmin for custom plans or bulk discounts"
        
        buttons = [
            [Button.inline("🛒 Purchase This Plan", f"purchase_api_{plan_id}")],
            [Button.inline("« Back to Plans", "api_plans")],
            [Button.inline("« API Menu", "api_menu")]
        ]
        
        await event.edit(plan_text, buttons=buttons, parse_mode="md")
    
    async def show_api_docs(self, event):
        """Show API documentation"""
        docs_text = "📖 **API DOCUMENTATION**\n"
        docs_text += "═══════════════════════\n\n"
        
        docs_text += "🚀 **Getting Started**\n"
        docs_text += "1. Purchase API access from @darkboxesAdmin\n"
        docs_text += "2. Once activated, create your API key\n"
        docs_text += "3. Use the API key in your requests\n"
        docs_text += "4. Call the desired endpoint\n\n"
        
        docs_text += "🔐 **Authentication**\n"
        docs_text += "Add to headers:\n"
        docs_text += "```\n"
        docs_text += f"X-API-Key: your_api_key_here\n"
        docs_text += "```\n\n"
        docs_text += "Or as query parameter:\n"
        docs_text += "```\n"
        docs_text += f"?api_key=your_api_key_here\n"
        docs_text += "```\n\n"
        
        docs_text += f"🌐 **Base URL**\n"
        docs_text += "```\n"
        docs_text += f"{config.API_BASE_URL}\n"
        docs_text += "```\n\n"
        
        docs_text += "🔍 **Search Endpoints**\n"
        for cmd_key, cmd_info in API_COMMANDS.items():
            if cmd_key not in ['batch', 'status', 'balance', 'usage']:
                cmd = SEARCH_COMMANDS.get(cmd_key, {})
                example = cmd.get('example', 'query_value')
                
                docs_text += f"**{cmd_info['endpoint']}**\n"
                docs_text += f"Method: {cmd_info['method']}\n"
                docs_text += f"Example: {{\"query\": \"{example}\"}}\n\n"
        
        docs_text += "📦 **Batch Search**\n"
        docs_text += "**Endpoint:** `/api/v1/search/batch`\n"
        docs_text += "**Method:** POST\n"
        docs_text += "**Request Body:**\n"
        docs_text += "```json\n"
        docs_text += '{\n'
        docs_text += '  "searches": [\n'
        docs_text += '    {"type": "phone", "query": "9876543210"},\n'
        docs_text += '    {"type": "email", "query": "test@example.com"}\n'
        docs_text += '  ]\n'
        docs_text += '}\n'
        docs_text += "```\n\n"
        
        docs_text += "📊 **Utility Endpoints**\n"
        docs_text += "• `GET /api/v1/status` - API status and limits\n"
        docs_text += "• `GET /api/v1/balance` - User credits and balance\n"
        docs_text += "• `GET /api/v1/usage` - API usage statistics\n\n"
        
        docs_text += "✅ **Response Format**\n"
        docs_text += "```json\n"
        docs_text += '{\n'
        docs_text += '  "status": "success",\n'
        docs_text += '  "message": "Search completed",\n'
        docs_text += '  "data": {\n'
        docs_text += '    "query": "9876543210",\n'
        docs_text += '    "type": "phone",\n'
        docs_text += '    "parsed_data": {\n'
        docs_text += '      "Name": "John Doe",\n'
        docs_text += '      "Location": "Mumbai"\n'
        docs_text += '    }\n'
        docs_text += '  },\n'
        docs_text += '  "timestamp": "2024-01-01T12:00:00Z"\n'
        docs_text += '}\n'
        docs_text += "```\n\n"
        
        docs_text += "❌ **Error Response**\n"
        docs_text += "```json\n"
        docs_text += '{\n'
        docs_text += '  "status": "error",\n'
        docs_text += '  "message": "Invalid API key",\n'
        docs_text += '  "code": "AUTH_FAILED",\n'
        docs_text += '  "timestamp": "2024-01-01T12:00:00Z"\n'
        docs_text += '}\n'
        docs_text += "```\n\n"
        
        docs_text += "💡 **Kali Linux Integration Example:**\n"
        docs_text += "```bash\n"
        docs_text += "#!/bin/bash\n"
        docs_text += 'API_KEY="your_api_key_here"\n'
        docs_text += 'QUERY="$1"\n'
        docs_text += 'curl -s -X POST \\\n'
        docs_text += f'  -H "X-API-Key: $API_KEY" \\\n'
        docs_text += f'  -H "Content-Type: application/json" \\\n'
        docs_text += f'  -d \'{{"query": "\'$QUERY\'"}}\' \\\n'
        docs_text += f'  {config.API_BASE_URL}/api/v1/search/phone\n'
        docs_text += "```\n\n"
        
        docs_text += "💡 **Need Help?**\n"
        docs_text += "Contact @darkboxesAdmin for API support"
        
        buttons = [
            [Button.inline("🔑 My API Keys", "my_api_keys")],
            [Button.inline("🛒 API Plans", "api_plans")],
            [Button.inline("« API Menu", "api_menu")]
        ]
        
        await event.edit(docs_text, buttons=buttons, parse_mode="md")
    
    async def ask_for_api_plan_selection(self, event):
        """Ask for API plan selection"""
        try:
            user_id = event.sender_id
            user_doc = await self.db.get_user(user_id)
            
            if not user_doc:
                await event.answer("❌ User not found", alert=True)
                return
            
            # Check if user has API access
            if not user_doc.get('has_api_access'):
                await event.edit(
                    "❌ **API ACCESS REQUIRED**\n\n"
                    "You need to purchase API access before creating API keys.\n\n"
                    "💰 **Available Plans:**\n"
                    "• 🚀 Unlimited API - ₹999 (30 days, unlimited searches)\n"
                    "• 🔑 Basic API - ₹999 (30 days, 1000 requests)\n"
                    "• ⚡ Professional API - ₹2499 (30 days, 5000 requests)\n"
                    "• 🏢 Enterprise API - ₹4999 (30 days, unlimited requests)\n\n"
                    "📞 **Contact @darkboxesAdmin to purchase API access**\n",
                    buttons=OneLineKeyboard.api_plans()
                )
                return
            
            # Check API access expiry
            api_expiry = user_doc.get('api_expiry')
            if api_expiry:
                expiry_date = datetime.fromisoformat(api_expiry)
                if expiry_date < datetime.now(timezone.utc):
                    await event.edit(
                        "❌ **API ACCESS EXPIRED**\n\n"
                        "Your API access has expired. Please renew your subscription.\n\n"
                        "📞 **Contact @darkboxesAdmin to renew API access**\n",
                        buttons=OneLineKeyboard.api_plans()
                    )
                    return
            
            api_plan = user_doc.get('api_plan', 'unlimited')
            
            plan_text = f"🔑 **CREATE API KEY**\n\n"
            plan_text += f"📊 **Your API Plan:** {API_PLANS.get(api_plan, {}).get('name', 'Unlimited')}\n"
            plan_text += f"📅 **Access Valid Until:** {user_doc.get('api_expiry', 'N/A')[:10]}\n\n"
            
            plan_text += "Select validity period for your new API key:\n\n"
            
            buttons = [
                [Button.inline("🔄 30 Days", f"confirm_create_api_{api_plan}_30")],
                [Button.inline("📅 60 Days", f"confirm_create_api_{api_plan}_60")],
                [Button.inline("📆 90 Days", f"confirm_create_api_{api_plan}_90")],
                [Button.inline("❌ Cancel", "my_api_keys")]
            ]
            
            await event.edit(plan_text, buttons=buttons, parse_mode="md")
            
        except Exception as e:
            logger.error(f"❌ Error in API plan selection: {e}")
            await event.answer("❌ Error processing request", alert=True)
    
    async def confirm_create_api_key(self, event, plan_id: str, days: int):
        """Confirm and create API key"""
        try:
            user_id = event.sender_id
            user_doc = await self.db.get_user(user_id)
            
            if not user_doc:
                await event.answer("❌ User not found", alert=True)
                return
            
            # Check if user has API access
            if not user_doc.get('has_api_access'):
                await event.answer("❌ API access required", alert=True)
                return
            
            # Check API access expiry
            api_expiry = user_doc.get('api_expiry')
            if api_expiry:
                expiry_date = datetime.fromisoformat(api_expiry)
                if expiry_date < datetime.now(timezone.utc):
                    await event.answer("❌ API access expired", alert=True)
                    return
            
            # Create API key
            description = f"{API_PLANS.get(plan_id, {}).get('name', 'API')} - {days} days"
            api_info = await self.db.api_db.create_api_key(user_id, plan_id, days, description)
            
            if api_info:
                # Send API key details
                api_key_msg = (
                    f"✅ **API KEY CREATED SUCCESSFULLY**\n\n"
                    f"🔑 **API Key:** `{api_info['api_key']}`\n"
                    f"🔐 **Client Token:** `{api_info['client_token']}`\n"
                    f"📅 **Expires:** {api_info['expires_at'][:10]}\n"
                    f"📊 **Plan:** {api_info['plan_id']}\n"
                    f"📝 **Description:** {description}\n\n"
                    f"🌐 **Base URL:** `{config.API_BASE_URL}`\n\n"
                    f"📝 **Usage Example:**\n"
                    f"```bash\n"
                    f"curl -X POST \\\n"
                    f"  -H \"X-API-Key: {api_info['api_key']}\" \\\n"
                    f"  -H \"Content-Type: application/json\" \\\n"
                    f"  -d '{{\"query\": \"9876543210\"}}' \\\n"
                    f"  {config.API_BASE_URL}/api/v1/search/phone\n"
                    f"```\n\n"
                    f"⚠️ **Save this information securely!**\n"
                    f"API key will not be shown again."
                )
                
                await event.edit(api_key_msg, parse_mode="md", buttons=OneLineKeyboard.api_keys_menu())
                
                # Also send to user's private chat
                try:
                    await self.bot.send_message(
                        user_id,
                        f"🔑 **New API Key Created**\n\n"
                        f"Key: `{api_info['api_key'][:8]}...{api_info['api_key'][-4:]}`\n"
                        f"Plan: {api_info['plan_id']}\n"
                        f"Expires: {api_info['expires_at'][:10]}\n\n"
                        f"Use with: {config.API_BASE_URL}",
                        parse_mode="md"
                    )
                except:
                    pass
                
            else:
                await event.answer("❌ Failed to create API key", alert=True)
                await self.show_my_api_keys(event)
            
        except Exception as e:
            logger.error(f"❌ Error creating API key: {e}")
            await event.answer("❌ Error creating API key", alert=True)
    
    async def show_api_panel(self, event):
        """Show API management panel"""
        api_text = (
            "🔑 **API MANAGEMENT**\n"
            "═══════════════════════\n\n"
            "📊 **Manage API keys and monitor API usage**\n\n"
            "🛠️ **Available Actions:**\n"
            "• View API statistics\n"
            "• Manage user API keys\n"
            "• View API analytics\n"
            "• Revoke API keys\n"
            "• Monitor API usage\n\n"
            "Select an option below:"
        )
        
        await event.edit(api_text, buttons=OneLineKeyboard.admin_api_panel(), parse_mode="md")
    
    async def show_api_stats(self, event):
        """Show API statistics"""
        try:
            api_stats = await self.db.admin_db.get_api_stats_detailed()
            
            stats_text = "📊 **API STATISTICS**\n"
            stats_text += "═══════════════════════\n\n"
            
            # Summary
            summary = api_stats.get('summary', {})
            stats_text += f"📈 **Summary**\n"
            stats_text += f"├─ Total API Keys: {summary.get('total_keys', 0)}\n"
            stats_text += f"├─ Active Keys: {summary.get('active_keys', 0)}\n"
            stats_text += f"├─ Total Requests: {summary.get('total_requests', 0)}\n"
            stats_text += f"└─ Requests Used: {summary.get('requests_used', 0)}\n\n"
            
            # Plan distribution
            if api_stats.get('plan_distribution'):
                stats_text += "📋 **Plan Distribution**\n"
                for plan in api_stats['plan_distribution']:
                    plan_name = API_PLANS.get(plan['_id'], {}).get('name', plan['_id'])
                    unlimited = "♾️" if API_PLANS.get(plan['_id'], {}).get('unlimited') else ""
                    stats_text += (
                        f"• {plan_name} {unlimited}\n"
                        f"  ├─ Total Keys: {plan['count']}\n"
                        f"  ├─ Active: {plan['active_keys']}\n"
                        f"  └─ Requests: {plan['total_requests']}\n\n"
                    )
            
            # Daily requests
            if api_stats.get('daily_requests'):
                stats_text += "📅 **Recent Daily Requests**\n"
                for day in api_stats['daily_requests'][:5]:
                    stats_text += (
                        f"• {day['_id']}\n"
                        f"  ├─ Total: {day['count']}\n"
                        f"  ├─ Success: {day['success']}\n"
                        f"  └─ Failed: {day['failed']}\n\n"
                    )
            
            # Top endpoints
            if api_stats.get('top_endpoints'):
                stats_text += "🔝 **Top Endpoints**\n"
                for endpoint in api_stats['top_endpoints'][:5]:
                    stats_text += (
                        f"• {endpoint['_id']}\n"
                        f"  ├─ Calls: {endpoint['count']}\n"
                        f"  ├─ Success Rate: {endpoint['success']/endpoint['count']*100:.1f}%\n"
                        f"  └─ Failed: {endpoint['failed']}\n\n"
                    )
            
            stats_text += f"🌐 **API Base URL:** `{config.API_BASE_URL}`\n"
            stats_text += f"🔐 **API Documentation:** {config.API_BASE_URL}/api/v1/docs\n"
            
            await event.edit(stats_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
            
        except Exception as e:
            logger.error(f"❌ Error showing API stats: {e}")
            await event.edit("❌ Error loading API statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def ask_for_api_user_management(self, event):
        """Ask for user ID for API management"""
        await event.edit(
            "👤 **MANAGE USER API KEYS**\n\n"
            "Enter user ID to manage their API keys:\n"
            "(Numeric user ID)\n\n"
            "Type the user ID:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_api_user"}
    
    async def show_api_analytics(self, event):
        """Show API analytics with graphs"""
        try:
            api_stats = await self.db.admin_db.get_api_stats_detailed()
            
            if not api_stats.get('daily_requests'):
                await event.edit("📊 No API analytics data available.", 
                               buttons=OneLineKeyboard.back_to_admin())
                return
            
            # Create visualization
            daily_data = api_stats['daily_requests']
            dates = [data['_id'][5:] for data in daily_data]  # Remove year
            counts = [data['count'] for data in daily_data]
            successes = [data['success'] for data in daily_data]
            failures = [data['failed'] for data in daily_data]
            
            plt.figure(figsize=(14, 8))
            
            # Success vs Failure stacked bar chart
            x = range(len(dates))
            width = 0.6
            
            plt.bar(x, successes, width, label='Success', color='lightgreen', alpha=0.8)
            plt.bar(x, failures, width, bottom=successes, label='Failure', color='lightcoral', alpha=0.8)
            
            plt.title('API Requests - Success vs Failure (Last 30 Days)', fontsize=14, fontweight='bold')
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Number of Requests', fontsize=12)
            plt.xticks(x, dates, rotation=45)
            plt.legend()
            plt.grid(True, alpha=0.3)
            
            # Add value labels
            for i, (s, f) in enumerate(zip(successes, failures)):
                total = s + f
                if total > 0:
                    plt.text(i, total + max(counts)*0.01, str(total), 
                            ha='center', va='bottom', fontsize=9, fontweight='bold')
            
            plt.tight_layout()
            
            # Save to bytes
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            # Calculate statistics
            total_requests = sum(counts)
            total_success = sum(successes)
            total_failed = sum(failures)
            success_rate = (total_success / total_requests * 100) if total_requests > 0 else 0
            
            caption = (
                f"📈 **API Analytics Dashboard**\n\n"
                f"📊 **Last 30 Days Summary:**\n"
                f"├─ Total Requests: {total_requests}\n"
                f"├─ Successful: {total_success}\n"
                f"├─ Failed: {total_failed}\n"
                f"├─ Success Rate: {success_rate:.1f}%\n"
                f"└─ Average Daily: {total_requests/len(dates):.1f}\n\n"
                f"📅 **Peak Day:** {dates[counts.index(max(counts))]} ({max(counts)} requests)\n"
                f"🌐 **API Base URL:** `{config.API_BASE_URL}`"
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
            logger.error(f"❌ Error generating API analytics: {e}")
            await event.edit("❌ Error generating API analytics", 
                           buttons=OneLineKeyboard.back_to_admin())
    
    async def ask_for_api_revoke(self, event):
        """Ask for API key to revoke"""
        await event.edit(
            "🚫 **REVOKE API KEY**\n\n"
            "Enter API key to revoke:\n"
            "(Full API key or first 8 characters)\n\n"
            "Type the API key:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_api_revoke"}
    
    async def confirm_revoke_api_key(self, event, api_key: str):
        """Confirm API key revocation"""
        try:
            # Revoke API key
            success = await self.db.api_db.delete_api_key(api_key)
            
            if success:
                # Get API key info for notification
                api_info = await self.db.api_db.get_api_key(api_key)
                if api_info and api_info.get("user_id"):
                    # Notify user
                    try:
                        await self.bot.send_message(
                            api_info["user_id"],
                            f"🚫 **API KEY REVOKED**\n\n"
                            f"Your API key has been revoked by administrator.\n"
                            f"🔑 Key: `{api_key[:8]}...{api_key[-4:]}`\n"
                            f"📝 Description: {api_info.get('description', 'N/A')}\n\n"
                            f"Contact @darkboxesAdmin for more information.",
                            parse_mode="md"
                        )
                    except:
                        pass
                
                await event.answer("✅ API key revoked successfully", alert=True)
            else:
                await event.answer("❌ Failed to revoke API key", alert=True)
            
            await self.show_api_panel(event)
            
        except Exception as e:
            logger.error(f"❌ Error revoking API key: {e}")
            await event.answer("❌ Error revoking API key", alert=True)
    
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
            admin_text += f"├─ Today's API Requests: {today_stats['api_requests']}\n"
            
            total_users = await asyncio.get_running_loop().run_in_executor(
                None, self.db.db.users.count_documents, {}
            )
            admin_text += f"└─ Total Users: {total_users}\n"
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            admin_text += "⚠️ Error loading stats\n"
        
        admin_text += f"\n🌐 **API Status:** {'✅ Running' if config.API_ENABLED else '❌ Disabled'}\n"
        admin_text += f"🔗 **API URL:** {config.API_BASE_URL}\n"
        
        admin_text += "\n🔧 **Select an option below:**"
        
        await event.edit(admin_text, buttons=OneLineKeyboard.admin_panel(), parse_mode="md")
    
    # ... (rest of the admin panel methods remain the same as before, just add API-related handlers)

    async def ask_for_broadcast(self, event):
        """Ask for broadcast message"""
        await event.edit(
            "📢 **BROADCAST MESSAGE**\n\n"
            "Enter message to broadcast to all users:\n"
            "(Supports Markdown formatting)\n\n"
            "Type your message:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_broadcast"}

# ================== SEARCH ENGINE WITH PRIORITY MANAGEMENT ==================

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
        
        # All groups failed
        await self._notify_admin(user_id, search_type, query)
        return {
            "success": False,
            "error": f"🔍 **INTELLIGENCE GATHERING FAILED**\n\nQuery: `{query}`\n\n⚠️ **Premium Notice:** Your query has been escalated to our premium database.\nAdministrator will review and respond within 24 hours.\n\n💎 **For instant access, upgrade to:**\n• 👑 Premium Tier: Unlimited searches (30 days)\n• 🚀 Standard Tier: 30 searches (15 days)\n\nContact @darkboxesAdmin for immediate assistance."
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
                "processed_files": []
            }
            
            # Wait for response (5 seconds timeout for leak search)
            try:
                result = await asyncio.wait_for(future, timeout=10)
                
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
    """Start web server"""
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="OK")
    
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.PORT)
    
    try:
        await site.start()
        logger.info(f"🌐 Web server running on port {config.PORT}")
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
            await event.edit(
                "🔒 **ACCESS DENIED**\n\n"
                "You have no search credits remaining.\n\n"
                "💎 **UPGRADE TO PREMIUM**\n\n"
                "💰 **BASIC TIER** - ₹99\n"
                "├─ 10 Premium Searches\n"
                "├─ Standard Databases\n"
                "├─ 7-day Access\n"
                "└─ Email Support\n\n"
                "🚀 **STANDARD TIER** - ₹249\n"
                "├─ 30 Premium Searches\n"
                "├─ All Databases\n"
                "├─ 15-day Access\n"
                "├─ Priority Support\n"
                "└─ Search History Saved\n\n"
                "👑 **PREMIUM TIER** - ₹499\n"
                "├─ Unlimited Searches (30 days)\n"
                "├─ All Premium Databases\n"
                "├─ Priority Processing\n"
                "├─ 24/7 WhatsApp Support\n"
                "└─ Extended Search History\n\n"
                "Select a plan to continue:",
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
        
        # API access status
        if user_doc.get('has_api_access'):
            api_expiry = user_doc.get('api_expiry')
            if api_expiry:
                expiry_date = datetime.fromisoformat(api_expiry)
                days_left = (expiry_date - datetime.now(timezone.utc)).days
                
                if days_left > 0:
                    profile_text += f"🔑 **API Access**\n"
                    profile_text += f"├─ Plan: {user_doc.get('api_plan', 'Unlimited')}\n"
                    profile_text += f"├─ Status: Active ({days_left} days left)\n"
                    profile_text += f"└─ URL: {config.API_BASE_URL}\n\n"
                else:
                    profile_text += f"🔑 **API Access: Expired**\n\n"
            else:
                profile_text += f"🔑 **API Access: Active**\n\n"
        else:
            profile_text += f"🔑 **API Access: Not enabled**\n\n"
        
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
            "💎 **DARKBOXES PREMIUM PLANS**\n"
            "═══════════════════════\n\n"
            "💰 **BASIC TIER** - ₹99\n"
            "├─ 10 Premium Searches\n"
            "├─ Standard Databases\n"
            "├─ 7-day Access\n"
            "├─ Email Support\n"
            "└─ 🎯 For: New users trying the service\n\n"
            "🚀 **STANDARD TIER** - ₹249\n"
            "├─ 30 Premium Searches\n"
            "├─ All Databases\n"
            "├─ 15-day Access\n"
            "├─ Priority Support\n"
            "├─ Search History Saved\n"
            "└─ 🎯 For: Regular users needing more searches\n\n"
            "👑 **PREMIUM TIER** - ₹499\n"
            "├─ Unlimited Searches (30 days)\n"
            "├─ All Premium Databases\n"
            "├─ Priority Processing\n"
            "├─ 24/7 WhatsApp Support\n"
            "├─ Extended Search History\n"
            "└─ 🎯 For: Power users & professionals\n\n"
            "📞 **Contact @darkboxesAdmin to purchase**\n"
            f"💳 **UPI ID:** `{config.UPI_ID}`\n\n"
            "🔒 **Payment Instructions:**\n"
            "1. Send payment via UPI\n"
            "2. Send screenshot to @darkboxesAdmin\n"
            "3. Your account will be upgraded within 5 minutes"
        )
        
        await event.edit(
            premium_text,
            buttons=OneLineKeyboard.subscription_plans(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in premium_callback: {e}")
        await event.answer("❌ Error loading premium plans", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^api_menu$'))
async def api_menu_callback(event):
    """Handle API menu callback"""
    await admin_panel.show_api_menu(event)

@bot_client.on(events.CallbackQuery(pattern=r'^my_api_keys$'))
async def my_api_keys_callback(event):
    """Handle my API keys callback"""
    await admin_panel.show_my_api_keys(event)

@bot_client.on(events.CallbackQuery(pattern=r'^api_usage$'))
async def api_usage_callback(event):
    """Handle API usage callback"""
    await admin_panel.show_api_usage(event)

@bot_client.on(events.CallbackQuery(pattern=r'^api_plans$'))
async def api_plans_callback(event):
    """Handle API plans callback"""
    await admin_panel.show_api_plans(event)

@bot_client.on(events.CallbackQuery(pattern=r'^api_docs$'))
async def api_docs_callback(event):
    """Handle API docs callback"""
    await admin_panel.show_api_docs(event)

@bot_client.on(events.CallbackQuery(pattern=r'^api_plan_(.+)$'))
async def api_plan_callback(event):
    """Handle API plan selection"""
    plan_id = event.data.decode().split('_', 2)[2]
    await admin_panel.show_api_plan_details(event, plan_id)

@bot_client.on(events.CallbackQuery(pattern=r'^create_api_key$'))
async def create_api_key_callback(event):
    """Handle create API key callback"""
    await admin_panel.ask_for_api_plan_selection(event)

@bot_client.on(events.CallbackQuery(pattern=r'^plan_(.+)$'))
async def plan_selection_callback(event):
    """Handle plan selection"""
    try:
        plan_id = event.data.decode().split('_', 1)[1]
        
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.answer("❌ Invalid plan selection", alert=True)
            return
        
        plan = SUBSCRIPTION_PLANS[plan_id]
        
        plan_details = (
            f"{plan['icon']} **{plan['name']}**\n"
            f"═══════════════════════\n\n"
            f"💰 **Price:** ₹{plan['price']}\n"
            f"🔍 **Searches:** {plan['searches']}\n"
            f"📅 **Validity:** {plan['validity']}\n\n"
            f"🌟 **Features:**\n"
        )
        
        for feature in plan['features']:
            plan_details += f"• {feature}\n"
        
        plan_details += f"\n🎯 **Perfect For:** {plan['for']}\n\n"
        
        plan_details += f"📞 **To Purchase:**\n"
        plan_details += f"1. Send ₹{plan['price']} to UPI: `{config.UPI_ID}`\n"
        plan_details += f"2. Send payment screenshot to @darkboxesAdmin\n"
        plan_details += f"3. Include your User ID: `{event.sender_id}`\n"
        plan_details += f"4. Your account will be upgraded within 5 minutes\n\n"
        plan_details += f"💡 **Note:** Contact @darkboxesAdmin for bulk discounts"
        
        buttons = [
            [Button.inline("« Back to Plans", "premium")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        
        await event.edit(plan_details, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in plan_selection_callback: {e}")
        await event.answer("❌ Error loading plan details", alert=True)

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
            f"Send screenshot after payment\n\n"
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

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def private_message_handler(event):
    """Handle private messages (queries and admin actions)"""
    try:
        user_id = event.sender_id
        
        if user_id not in user_states:
            return
        
        state = user_states[user_id]
        
        if state.get("action") == "search":
            await handle_search_query(event, state)
        
        elif state.get("action") == "admin_search_user":
            await handle_admin_search_user(event)
        
        elif state.get("action") == "admin_broadcast":
            await handle_admin_broadcast(event)
        
        elif state.get("action") == "admin_ban":
            await handle_admin_ban(event)
        
        elif state.get("action") == "admin_management":
            await handle_admin_management(event)
        
        elif state.get("action") == "admin_add_credits":
            await handle_admin_add_credits(event)
        
        elif state.get("action") == "admin_api_user":
            await handle_admin_api_user(event)
        
        elif state.get("action") == "admin_api_revoke":
            await handle_admin_api_revoke(event)
        
    except Exception as e:
        logger.error(f"❌ Error in private_message_handler: {e}")

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
            
            await db_manager.update_searches(user_id, search_type, query, True)
        else:
            await event.respond(result["error"], parse_mode="md")
            await db_manager.update_searches(user_id, search_type, query, False)
        
        # Clear state
        user_states.pop(user_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_search_query: {e}")
        await event.respond("❌ An error occurred during processing.")

async def handle_admin_api_user(event):
    """Handle admin API user management"""
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
        
        # Get user's API keys
        api_keys = await db_manager.api_db.get_user_api_keys(user_id)
        
        api_text = f"🔑 **API KEYS FOR USER** {user.get('first_name', 'N/A')}\n\n"
        
        if api_keys:
            for i, api_key in enumerate(api_keys, 1):
                status = "✅ Active" if api_key.get("is_active") else "❌ Inactive"
                created = api_key.get("created_at", "")[:10]
                expires = api_key.get("expires_at", "")[:10]
                requests = api_key.get("requests_used", 0)
                remaining = api_key.get("requests_remaining", 0)
                unlimited = "♾️" if api_key.get("unlimited") else ""
                
                api_text += (
                    f"{i}. **{api_key.get('description', 'Unnamed')}** {unlimited}\n"
                    f"   ├─ Status: {status}\n"
                    f"   ├─ Plan: {api_key.get('plan_id', 'N/A')}\n"
                    f"   ├─ Key: `{api_key['api_key'][:8]}...{api_key['api_key'][-4:]}`\n"
                    f"   ├─ Created: {created}\n"
                    f"   ├─ Expires: {expires}\n"
                    f"   ├─ Requests: {requests} used, {remaining} remaining\n"
                    f"   └─ Actions: /revoke_api_{api_key['api_key']}\n\n"
                )
        else:
            api_text += "📭 No API keys found for this user.\n"
        
        api_text += f"\n🔧 **Available Actions:**\n"
        api_text += f"• Create new API key: /create_api {user_id} plan_id days description\n"
        api_text += f"• Extend API key: /extend_api api_key additional_days\n"
        api_text += f"• Revoke API key: /revoke_api api_key\n"
        api_text += f"• Add API access: /add_api_access {user_id} plan_id days\n"
        
        await event.respond(api_text, parse_mode="md")
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error handling API user management: {e}")
        await event.respond("❌ Error processing request")

async def handle_admin_api_revoke(event):
    """Handle admin API key revocation"""
    try:
        api_key_input = event.text.strip()
        
        if not api_key_input:
            await event.respond("❌ Please enter an API key.")
            return
        
        # Find API key (full or partial)
        if len(api_key_input) == 64:
            # Full API key
            api_info = await db_manager.api_db.get_api_key(api_key_input)
        else:
            # Partial key, search for it
            all_keys = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(db_manager.db.api_keys.find(
                    {"api_key": {"$regex": f"^{api_key_input}"}},
                    {"api_key": 1, "user_id": 1, "description": 1}
                ))
            )
            
            if len(all_keys) == 1:
                api_info = all_keys[0]
            elif len(all_keys) > 1:
                await event.respond(f"❌ Multiple API keys found. Please enter full API key.")
                return
            else:
                await event.respond("❌ API key not found.")
                return
        
        if not api_info:
            await event.respond("❌ API key not found.")
            user_states.pop(event.sender_id, None)
            return
        
        # Get user info
        user = await db_manager.get_user(api_info["user_id"])
        
        confirm_text = (
            f"🚫 **REVOKE API KEY CONFIRMATION**\n\n"
            f"🔑 **API Key:** `{api_info['api_key'][:8]}...{api_info['api_key'][-4:]}`\n"
            f"👤 **User:** {user.get('first_name', 'N/A')} (@{user.get('username', 'N/A')})\n"
            f"📝 **Description:** {api_info.get('description', 'N/A')}\n"
            f"📅 **Created:** {api_info.get('created_at', 'N/A')[:10]}\n"
            f"📊 **Requests Used:** {api_info.get('requests_used', 0)}\n\n"
            f"Are you sure you want to revoke this API key?\n"
            f"This action cannot be undone."
        )
        
        # Store for confirmation
        user_states[event.sender_id] = {
            "action": "confirm_api_revoke",
            "api_key": api_info["api_key"]
        }
        
        buttons = [
            [Button.inline("✅ Yes, Revoke API Key", f"confirm_revoke_api_{api_info['api_key']}")],
            [Button.inline("❌ Cancel", "admin_panel")]
        ]
        
        await event.respond(confirm_text, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error handling API revocation: {e}")
        await event.respond("❌ Error processing request")

@bot_client.on(events.CallbackQuery(pattern=r'^confirm_revoke_api_(.+)$'))
async def confirm_revoke_api_handler(event):
    """Handle API key revocation confirmation"""
    try:
        api_key = event.data.decode().split('_', 3)[3]
        
        # Revoke API key
        success = await db_manager.api_db.delete_api_key(api_key)
        
        if success:
            await event.answer("✅ API key revoked successfully", alert=True)
            
            # Get API key info for notification
            api_info = await db_manager.api_db.get_api_key(api_key)
            if api_info and api_info.get("user_id"):
                # Notify user
                await bot_client.send_message(
                    api_info["user_id"],
                    f"🚫 **API KEY REVOKED**\n\n"
                    f"Your API key has been revoked by administrator.\n"
                    f"🔑 Key: `{api_key[:8]}...{api_key[-4:]}`\n"
                    f"📝 Description: {api_info.get('description', 'N/A')}\n\n"
                    f"Contact @darkboxesAdmin for more information.",
                    parse_mode="md"
                )
        else:
            await event.answer("❌ Failed to revoke API key", alert=True)
        
        await admin_panel.show_admin_panel(event)
        
    except Exception as e:
        logger.error(f"❌ Error revoking API key: {e}")
        await event.answer("❌ Error revoking API key", alert=True)

@bot_client.on(events.NewMessage(pattern=r'/create_api (\d+) (\w+) (\d+) (.+)'))
async def create_api_command(event):
    """Handle /create_api command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Admin privileges required.")
            return
        
        target_user_id = int(event.pattern_match.group(1))
        plan_id = event.pattern_match.group(2)
        days = int(event.pattern_match.group(3))
        description = event.pattern_match.group(4)
        
        if plan_id not in API_PLANS:
            await event.respond(f"❌ Invalid plan ID. Available: {', '.join(API_PLANS.keys())}")
            return
        
        # First ensure user has API access
        user_doc = await db_manager.get_user(target_user_id)
        if not user_doc:
            await event.respond(f"❌ User {target_user_id} not found.")
            return
        
        if not user_doc.get('has_api_access'):
            # Add API access first
            await db_manager.add_api_access(target_user_id, plan_id, days)
        
        # Create API key
        api_info = await db_manager.api_db.create_api_key(target_user_id, plan_id, days, description)
        
        if api_info:
            await event.respond(
                f"✅ **API KEY CREATED**\n\n"
                f"👤 User ID: `{target_user_id}`\n"
                f"🔑 API Key: `{api_info['api_key']}`\n"
                f"📅 Expires: {api_info['expires_at'][:10]}\n"
                f"📊 Plan: {plan_id}\n"
                f"📝 Description: {description}\n\n"
                f"🌐 **API Base URL:** {config.API_BASE_URL}",
                parse_mode="md"
            )
        else:
            await event.respond("❌ Failed to create API key")
        
    except Exception as e:
        logger.error(f"❌ Error in create_api_command: {e}")
        await event.respond("❌ Error creating API key")

@bot_client.on(events.NewMessage(pattern=r'/add_api_access (\d+) (\w+) (\d+)'))
async def add_api_access_command(event):
    """Handle /add_api_access command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Admin privileges required.")
            return
        
        target_user_id = int(event.pattern_match.group(1))
        plan_id = event.pattern_match.group(2)
        days = int(event.pattern_match.group(3))
        
        if plan_id not in API_PLANS:
            await event.respond(f"❌ Invalid plan ID. Available: {', '.join(API_PLANS.keys())}")
            return
        
        # Add API access
        success = await db_manager.add_api_access(target_user_id, plan_id, days)
        
        if success:
            plan = API_PLANS[plan_id]
            await event.respond(
                f"✅ **API ACCESS ADDED**\n\n"
                f"👤 User ID: `{target_user_id}`\n"
                f"📊 Plan: {plan['name']}\n"
                f"📅 Duration: {days} days\n"
                f"💰 Price: ₹{plan['price']}\n\n"
                f"🌐 **API Base URL:** {config.API_BASE_URL}\n"
                f"🔑 **User can now create API keys in their profile.**",
                parse_mode="md"
            )
        else:
            await event.respond("❌ Failed to add API access")
        
    except Exception as e:
        logger.error(f"❌ Error in add_api_access_command: {e}")
        await event.respond("❌ Error adding API access")

@bot_client.on(events.NewMessage(pattern=r'/revoke_api (.+)'))
async def revoke_api_command(event):
    """Handle /revoke_api command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Admin privileges required.")
            return
        
        api_key = event.pattern_match.group(1).strip()
        
        # Revoke API key
        success = await db_manager.api_db.delete_api_key(api_key)
        
        if success:
            await event.respond(f"✅ API key revoked successfully")
        else:
            await event.respond("❌ Failed to revoke API key")
        
    except Exception as e:
        logger.error(f"❌ Error in revoke_api_command: {e}")
        await event.respond("❌ Error revoking API key")

@bot_client.on(events.NewMessage(pattern=r'/extend_api (.+) (\d+)'))
async def extend_api_command(event):
    """Handle /extend_api command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Admin privileges required.")
            return
        
        api_key = event.pattern_match.group(1).strip()
        additional_days = int(event.pattern_match.group(2))
        
        # Extend API key
        success = await db_manager.api_db.extend_api_key(api_key, additional_days)
        
        if success:
            await event.respond(f"✅ API key extended by {additional_days} days")
        else:
            await event.respond("❌ Failed to extend API key")
        
    except Exception as e:
        logger.error(f"❌ Error in extend_api_command: {e}")
        await event.respond("❌ Error extending API key")

# ================== MAIN FUNCTION ==================

async def main():
    """Main function"""
    global search_engine, admin_panel, bot_info
    
    try:
        logger.info("🚀 Starting DarkBoxes Intelligence System with API Support...")
        
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
        
        # Start API server if enabled
        if config.API_ENABLED:
            asyncio.create_task(start_api_server())
        
        logger.info("=" * 60)
        logger.info("🎭 DARK BOXES INTELLIGENCE SYSTEM - OPERATIONAL")
        logger.info(f"🔑 API Server: {'Enabled' if config.API_ENABLED else 'Disabled'}")
        logger.info(f"🌐 API Base URL: {config.API_BASE_URL}")
        logger.info(f"🔗 API Port: {config.API_PORT}")
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
