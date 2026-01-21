"""
DarkBoxes Intelligence System - Premium Edition
Advanced information retrieval with premium interface
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
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

# Third-party imports
try:
    from aiohttp import web
    from telethon import TelegramClient, events, Button
    from telethon.tl.types import PeerChannel, PeerUser, Channel, User, MessageMediaDocument
    from telethon.tl.functions.channels import GetParticipantRequest
    from pymongo import MongoClient
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install telethon aiohttp pymongo")
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
    NEW_USER_CREDITS: int = int(os.getenv("NEW_USER_CREDITS", "3"))
    REFERRAL_REWARD: int = int(os.getenv("REFERRAL_REWARD", "2"))
    
    # Payment
    UPI_ID: str = os.getenv("UPI_ID", "darkboxes@ybl")
    ADMIN_CONTACT: str = "@darkboxesAdmin"

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
        "name": "🔰 Basic Plan",
        "price": 100,
        "searches": 5,
        "validity": "7 days",
        "features": ["5 premium searches", "Standard data sources", "7-day access"],
        "icon": "🔰",
        "color": "#27AE60"
    },
    "standard": {
        "name": "⭐ Standard Plan",
        "price": 200,
        "searches": 10,
        "validity": "7 days",
        "features": ["10 premium searches", "Extended data sources", "Priority processing"],
        "icon": "⭐",
        "color": "#F39C12"
    },
    "premium": {
        "name": "👑 Premium Plan",
        "price": 500,
        "searches": "∞",
        "validity": "7 days",
        "features": ["Unlimited searches", "All data sources", "Priority processing", "24/7 support"],
        "icon": "👑",
        "color": "#9B59B6"
    },
    "enterprise": {
        "name": "🚀 Enterprise Plan",
        "price": 800,
        "searches": "∞",
        "validity": "30 days",
        "features": ["Unlimited searches", "All premium sources", "Highest priority", "Dedicated support", "API access"],
        "icon": "🚀",
        "color": "#E74C3C"
    }
}

# ================== SEARCH COMMANDS WITH PRIORITY ==================

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Intelligence",
        "description": "📊 **Complete Mobile Intelligence**\n\n🔸 **Input:** 10-digit Indian mobile number\n🔸 **Returns:** Full name • Father's name • Aadhar ID • Complete address • Alternate numbers\n🔸 **Sources:** Government databases • Telecom records • Public directories\n🔸 **Confidence:** 98% accurate",
        "commands": ["/num", "/phone", "/mobile"],
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
        "commands": ["/familyinfo", "/family"],
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
        "commands": ["/aadhar", "/adh", "/aadhaar"],
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
        "commands": ["/vehicle", "/vnum", "/car"],
        "example": "UP53CZ3391",
        "validation": r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$",
        "cost": 2,
        "priority": "primary",
        "icon": "🚗",
        "category": "assets"
    },
    "upi": {
        "name": "💳 UPI Financial Intelligence",
        "description": "💰 **UPI Account & Transaction Analysis**\n\n🔸 **Input:** UPI ID (username@paytm/bank)\n🔸 **Returns:** Account holder • Linked bank • Transaction patterns • KYC status • Last active\n🔸 **Sources:** NPCI databases • Bank records • Financial institutions\n🔸 **Security:** Bank-grade encryption",
        "commands": ["/upiinfo", "/upi"],
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
    }
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
        welcome += "• 🔓 Government Database Access\n"
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
        
        # Remove promotional content
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
            r'designed & powered.*'
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        # Clean whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)
        
        return content.strip()

# ================== DATABASE MANAGER ==================

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
    
    async def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            logger.info("🔌 Connecting to MongoDB...")
            self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            self.client.server_info()
            self.db = self.client[config.MONGODB_DBNAME]
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
                "wallet_balance": 0
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
    
    async def update_searches(self, user_id: int, decrement: int = 1) -> bool:
        """Update user search count"""
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
                    return True
            
            # Use credits
            searches_remaining = user.get("searches_remaining", 0)
            if searches_remaining <= 0:
                return False
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {
                            "searches_remaining": -decrement,
                            "total_searches": decrement
                        },
                        "$set": {"last_seen": datetime.now(timezone.utc).isoformat()}
                    }
                )
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
            "gst", "insta", "pak", "ip", "ifsc"
        ]
        
        for cmd_key in commands_in_order:
            if cmd_key in SEARCH_COMMANDS:
                cmd = SEARCH_COMMANDS[cmd_key]
                # Each command gets its own line
                buttons.append([Button.inline(f"{cmd['icon']} {cmd['name'].split()[1]}", f"search_{cmd_key}")])
        
        # Add action buttons in their own lines
        buttons.append([Button.inline("👤 Profile", "profile")])
        buttons.append([Button.inline("💎 Premium Plans", "premium")])
        buttons.append([Button.inline("📊 Refer & Earn", "referrals")])
        buttons.append([Button.inline("🆘 Support", "support")])
        
        # Add admin button if admin
        if is_admin:
            buttons.append([Button.inline("⚙️ Admin Panel", "admin")])
        
        return buttons
    
    @staticmethod
    def search_type_menu(search_type: str) -> List[List[Button]]:
        """Menu for specific search type"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        return [
            [Button.inline(f"{cmd.get('icon', '🔍')} {cmd.get('name', 'Search')}", f"info_{search_type}")],
            [Button.inline("« Back to Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def subscription_plans() -> List[List[Button]]:
        """Premium subscription plans - one per line"""
        buttons = []
        
        for plan_id, plan in SUBSCRIPTION_PLANS.items():
            label = f"{plan['icon']} {plan['name']} - ₹{plan['price']}"
            buttons.append([Button.inline(label, f"buy_{plan_id}")])
        
        buttons.append([Button.inline("« Back to Main Menu", "main_menu")])
        return buttons
    
    @staticmethod
    def cancel_button() -> List[List[Button]]:
        """Cancel button"""
        return [[Button.inline("❌ Cancel", "main_menu")]]
    
    @staticmethod
    def payment_buttons(plan_id: str) -> List[List[Button]]:
        """Payment confirmation buttons"""
        return [
            [Button.inline("✅ Payment Done", f"confirm_{plan_id}")],
            [Button.inline("❌ Cancel", "premium")]
        ]
    
    @staticmethod
    def admin_controls() -> List[List[Button]]:
        """Admin control panel - one per line"""
        return [
            [Button.inline("📊 Statistics", "admin_stats")],
            [Button.inline("📢 Broadcast Message", "admin_broadcast")],
            [Button.inline("⚙️ Settings", "admin_settings")],
            [Button.inline("👥 User Management", "admin_users")],
            [Button.inline("« Main Menu", "main_menu")]
        ]

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
            "error": f"🔍 **INTELLIGENCE GATHERING FAILED**\n\nQuery: `{query}`\n\n⚠️ **Premium Notice:** Your query has been escalated to our premium database.\nAdministrator will review and respond within 24 hours.\n\n💎 **For instant access, upgrade to:**\n• 👑 Premium Plan: Unlimited searches (7 days)\n• 🚀 Enterprise Plan: Unlimited searches (30 days)\n\nContact @darkboxesAdmin for immediate assistance."
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
        if message.media and hasattr(message.media, 'document'):
            logger.info(f"📁 Found document media in message")
            return await self._process_file(message, search_info)
        
        if hasattr(message, 'file') and message.file:
            logger.info(f"📁 Found file attribute in message")
            return await self._process_file(message, search_info)
        
        if message.document:
            logger.info(f"📁 Found document in message")
            return await self._process_file(message, search_info)
        
        return None
    
    async def _process_search_response(self, search_id: str, search_info: Dict, message):
        """Process a search response message"""
        try:
            text = message.text or message.raw_text or ""
            logger.info(f"📨 Processing message in {search_info['group']['name']}: {text[:100]}...")
            
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
            
            cleaned_content = TextProcessor.clean_content(content, search_info["search_type"])
            
            if len(cleaned_content.strip()) < 30:
                logger.warning(f"⚠️ Cleaned content too short: {len(cleaned_content)} chars")
                lines = content.split('\n')
                meaningful_lines = []
                for line in lines:
                    line = line.strip()
                    if len(line) > 10:
                        if not any(word in line.lower() for word in ['powered', 'developed', 'created', 'join', 'subscribe', 'channel', 'admin', '@']):
                            meaningful_lines.append(line)
                
                if meaningful_lines:
                    cleaned_content = '\n'.join(meaningful_lines)
                    cleaned_content = TextProcessor.clean_content(cleaned_content, search_info["search_type"])
                else:
                    return {"success": False}
            
            formatted_result = PremiumFormatter.format_result(
                cleaned_content,
                search_info["search_type"],
                search_info["query"],
                search_info["group"]["name"]
            )
            
            logger.info(f"✅ Processed file with {len(cleaned_content)} characters")
            return {
                "success": True,
                "result": formatted_result,
                "has_file": True
            }
            
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

# ================== EVENT HANDLERS ==================

# Initialize clients first
bot_client = TelegramClient(config.BOT_SESSION_FILE, config.BOT_API_ID, config.BOT_API_HASH)
user_client = (
    TelegramClient(config.USER_SESSION_FILE, config.USER_API_ID, config.USER_API_HASH)
    if USE_USER_ACCOUNT
    else bot_client
)

# Initialize managers
db_manager = DatabaseManager()
search_engine = None
user_states = {}
bot_info = None

# Now define event handlers
@bot_client.on(events.NewMessage(pattern=r'/start(?: (.+))?'))
async def start_handler(event):
    """Premium start handler"""
    try:
        user = await event.get_sender()
        user_id = user.id
        referral_code = event.pattern_match.group(1)
        
        # Get or create user
        user_doc = await db_manager.get_user(user_id)
        if not user_doc:
            await db_manager.create_user(user_id, user.username, user.first_name, referral_code)
            user_doc = await db_manager.get_user(user_id)
            
            # Handle referral
            if referral_code and referral_code.isdigit():
                referrer_id = int(referral_code)
                referrer = await db_manager.get_user(referrer_id)
                if referrer:
                    await db_manager.add_referral_credit(referrer_id, config.REFERRAL_REWARD)
        
        is_admin = user_id == config.ADMIN_USER_ID
        
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

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)$'))
async def search_callback(event):
    """Handle search type selection"""
    try:
        user_id = event.sender_id
        search_type = event.data.decode().split('_', 1)[1]
        
        if search_type not in SEARCH_COMMANDS:
            await event.answer("❌ Invalid selection", alert=True)
            return
        
        user_doc = await db_manager.get_user(user_id)
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
                "🔰 **Basic Plan** - ₹100\n"
                "├─ 5 Premium Searches\n"
                "├─ Standard Databases\n"
                "└─ 7-day Access\n\n"
                "⭐ **Standard Plan** - ₹200\n"
                "├─ 10 Premium Searches\n"
                "├─ Extended Databases\n"
                "└─ Priority Processing\n\n"
                "👑 **Premium Plan** - ₹500\n"
                "├─ Unlimited Searches\n"
                "├─ All Databases\n"
                "├─ Priority Processing\n"
                "└─ 24/7 Support\n\n"
                "🚀 **Enterprise Plan** - ₹800\n"
                "├─ Unlimited Searches\n"
                "├─ Premium Sources\n"
                "├─ Highest Priority\n"
                "├─ Dedicated Support\n"
                "└─ 30-day Access\n\n"
                "Select a plan to continue:",
                buttons=OneLineKeyboard.subscription_plans(),
                parse_mode="md"
            )
            return
        
        cmd = SEARCH_COMMANDS[search_type]
        
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

@bot_client.on(events.CallbackQuery(pattern='^main_menu$'))
async def main_menu_callback(event):
    """Return to main menu"""
    try:
        user_id = event.sender_id
        user_states.pop(user_id, None)
        
        user_doc = await db_manager.get_user(user_id)
        is_admin = user_id == config.ADMIN_USER_ID
        
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

@bot_client.on(events.CallbackQuery(pattern='^premium$'))
async def premium_callback(event):
    """Show premium plans"""
    try:
        plans_text = "💎 **PREMIUM SUBSCRIPTION PLANS**\n\n"
        
        for plan_id, plan in SUBSCRIPTION_PLANS.items():
            plans_text += f"{plan['icon']} **{plan['name']}** - ₹{plan['price']}\n"
            plans_text += f"├─ Searches: {plan['searches']}\n"
            plans_text += f"├─ Validity: {plan['validity']}\n"
            for feature in plan['features']:
                plans_text += f"├─ {feature}\n"
            plans_text += "\n"
        
        plans_text += "💰 **PAYMENT INSTRUCTIONS**\n"
        plans_text += f"1. Send ₹[Plan Price] to UPI: `{config.UPI_ID}`\n"
        plans_text += "2. Take screenshot of payment\n"
        plans_text += "3. Click 'Payment Done' for your plan\n"
        plans_text += "4. Send screenshot to @darkboxesAdmin\n\n"
        plans_text += "⚡ Activation within 5 minutes of verification."
        
        await event.edit(plans_text, buttons=OneLineKeyboard.subscription_plans(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in premium_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^buy_(.+)$'))
async def buy_plan_callback(event):
    """Handle plan purchase"""
    try:
        plan_id = event.data.decode().split('_', 1)[1]
        
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.answer("❌ Invalid plan", alert=True)
            return
        
        plan = SUBSCRIPTION_PLANS[plan_id]
        
        payment_msg = (
            f"💰 **PURCHASE CONFIRMATION: {plan['name']}**\n\n"
            f"**Price:** ₹{plan['price']}\n"
            f"**UPI ID:** `{config.UPI_ID}`\n"
            f"**Plan Details:**\n"
        )
        
        for feature in plan['features']:
            payment_msg += f"• {feature}\n"
        
        payment_msg += "\n**📋 PAYMENT PROCESS**\n"
        payment_msg += "1. Send exact amount to above UPI\n"
        payment_msg += "2. Take screenshot of successful payment\n"
        payment_msg += "3. Click 'Payment Done' below\n"
        payment_msg += "4. Send screenshot to @darkboxesAdmin for verification\n\n"
        payment_msg += "⚡ Subscription activated within 5 minutes of verification."
        
        await event.edit(payment_msg, buttons=OneLineKeyboard.payment_buttons(plan_id), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in buy_plan_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^confirm_(.+)$'))
async def confirm_payment_callback(event):
    """Handle payment confirmation"""
    try:
        plan_id = event.data.decode().split('_', 1)[1]
        user_id = event.sender_id
        
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.answer("❌ Invalid plan", alert=True)
            return
        
        plan = SUBSCRIPTION_PLANS[plan_id]
        
        # Notify admin
        user_doc = await db_manager.get_user(user_id)
        admin_msg = (
            f"💰 **PAYMENT CONFIRMATION REQUEST**\n\n"
            f"👤 User: {user_doc['first_name']} (@{user_doc['username']})\n"
            f"🆔 ID: `{user_id}`\n"
            f"📋 Plan: {plan['name']}\n"
            f"💰 Amount: ₹{plan['price']}\n"
            f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"⚡ Use `/activate {user_id} {plan_id}` to activate subscription."
        )
        
        await bot_client.send_message(config.ADMIN_USER_ID, admin_msg, parse_mode="md")
        
        await event.edit(
            f"✅ **PAYMENT CONFIRMATION RECEIVED**\n\n"
            f"Thank you for your payment confirmation.\n"
            f"📋 Plan: {plan['name']}\n"
            f"💰 Amount: ₹{plan['price']}\n\n"
            f"📸 Please send payment screenshot to @darkboxesAdmin for verification.\n"
            f"⚡ Your subscription will be activated within 5 minutes of verification.",
            buttons=OneLineKeyboard.cancel_button(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in confirm_payment_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern='^referrals$'))
async def referrals_callback(event):
    """Show referrals information"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        referrals_text = (
            f"📊 **REFER & EARN PROGRAM**\n\n"
            f"**📈 YOUR REFERRAL STATS**\n"
            f"├─ Referral Code: `{user_doc.get('referral_code', 'N/A')}`\n"
            f"├─ Total Referrals: {user_doc.get('referrals', 0)}\n"
            f"└─ Earned Credits: {user_doc.get('referral_credits', 0)}\n\n"
            f"**🔄 HOW IT WORKS**\n"
            f"1. Share your referral link:\n"
            f"`https://t.me/{bot_info.username}?start={user_id}`\n\n"
            f"2. When someone joins using your link:\n"
            f"• They get {config.NEW_USER_CREDITS} free credits\n"
            f"• You get {config.REFERRAL_REWARD} search credits\n\n"
            f"3. No limits - refer unlimited users\n\n"
            f"**🎁 BENEFITS**\n"
            f"• Free credits for both parties\n"
            f"• Priority support for top referrers\n"
            f"• Special discounts for active referrers"
        )
        
        await event.edit(referrals_text, buttons=OneLineKeyboard.cancel_button(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in referrals_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern='^profile$'))
async def profile_callback(event):
    """Show user profile"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        # Calculate subscription status
        subscription_status = "None"
        if user_doc.get('subscription') and user_doc.get('subscription_expiry'):
            expiry_date = datetime.fromisoformat(user_doc['subscription_expiry'])
            if expiry_date > datetime.now(timezone.utc):
                days_left = (expiry_date - datetime.now(timezone.utc)).days
                subscription_status = f"{user_doc['subscription']} ({days_left} days remaining)"
        
        profile_text = (
            f"👤 **USER PROFILE**\n\n"
            f"**📋 BASIC INFORMATION**\n"
            f"├─ Name: {user_doc.get('first_name', 'N/A')}\n"
            f"├─ Username: @{user_doc.get('username', 'N/A')}\n"
            f"├─ User ID: `{user_id}`\n"
            f"└─ Member Since: {user_doc.get('joined_at', 'N/A')[:10]}\n\n"
            f"**📊 ACCOUNT STATUS**\n"
            f"├─ Available Credits: {user_doc.get('searches_remaining', 0)}\n"
            f"├─ Total Searches: {user_doc.get('total_searches', 0)}\n"
            f"├─ Active Subscription: {subscription_status}\n"
            f"└─ Wallet Balance: ₹{user_doc.get('wallet_balance', 0)}\n\n"
            f"**📈 REFERRAL INFORMATION**\n"
            f"├─ Referral Code: `{user_doc.get('referral_code', 'N/A')}`\n"
            f"├─ Total Referrals: {user_doc.get('referrals', 0)}\n"
            f"└─ Earned Credits: {user_doc.get('referral_credits', 0)}\n\n"
            f"**⏰ LAST ACTIVITY:** {user_doc.get('last_seen', 'N/A')[:19]}"
        )
        
        await event.edit(profile_text, buttons=OneLineKeyboard.cancel_button(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in profile_callback: {e}")

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def query_handler(event):
    """Handle search queries with premium UI"""
    try:
        user_id = event.sender_id
        
        if user_id not in user_states:
            return
        
        state = user_states[user_id]
        if state.get("action") != "search":
            return
        
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
                "💎 **Premium Plan** - ₹500\n"
                "• Unlimited searches (7 days)\n"
                "• All databases\n"
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
            await event.respond(result["result"], parse_mode="md")
            await db_manager.update_searches(user_id)
        else:
            await event.respond(result["error"], parse_mode="md")
        
        # Clear state
        user_states.pop(user_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in query_handler: {e}")
        await event.respond("❌ An error occurred during processing.")

@user_client.on(events.NewMessage())
async def handle_all_messages(event):
    """Handle all incoming messages for search responses"""
    try:
        await search_engine.handle_incoming_message(event)
    except Exception as e:
        pass

@bot_client.on(events.NewMessage(pattern=r'/activate (\d+) (\w+)'))
async def activate_subscription_handler(event):
    """Admin command to activate subscription"""
    try:
        if event.sender_id != config.ADMIN_USER_ID:
            return
        
        user_id = int(event.pattern_match.group(1))
        plan_id = event.pattern_match.group(2)
        
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.respond("❌ Invalid plan ID")
            return
        
        plan = SUBSCRIPTION_PLANS[plan_id]
        days = 7 if plan_id in ["basic", "standard", "premium"] else 30
        
        success = await db_manager.add_subscription(user_id, plan_id, days)
        
        if success:
            user_doc = await db_manager.get_user(user_id)
            await bot_client.send_message(
                user_id,
                f"✅ **SUBSCRIPTION ACTIVATED**\n\n"
                f"Your {plan['name']} has been activated.\n\n"
                f"📋 **PLAN DETAILS**\n"
                f"├─ Plan: {plan['name']}\n"
                f"├─ Validity: {plan['validity']}\n"
                f"└─ Features: {', '.join(plan['features'][:3])}\n\n"
                f"⚡ You now have unlimited searches until {(datetime.now(timezone.utc) + timedelta(days=days)).strftime('%Y-%m-%d')}.\n\n"
                f"🔗 For support: @darkboxesAdmin"
            )
            
            await event.respond(f"✅ Subscription activated for user {user_id}")
        else:
            await event.respond(f"❌ Failed to activate subscription")
        
    except Exception as e:
        logger.error(f"❌ Error in activate_subscription_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/broadcast (.+)'))
async def broadcast_handler(event):
    """Admin broadcast command"""
    try:
        if event.sender_id != config.ADMIN_USER_ID:
            return
        
        message = event.pattern_match.group(1)
        
        # Get all users
        users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(db_manager.db.users.find({}, {"user_id": 1}))
        )
        
        sent = 0
        failed = 0
        
        await event.respond(f"📢 Starting broadcast to {len(users)} users...")
        
        for user in users:
            try:
                await bot_client.send_message(
                    user["user_id"],
                    f"📢 **ANNOUNCEMENT**\n\n{message}\n\n— DarkBoxes Administration"
                )
                sent += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                failed += 1
        
        await event.respond(f"✅ Broadcast complete\n📤 Sent: {sent}\n❌ Failed: {failed}")
        
    except Exception as e:
        logger.error(f"❌ Error in broadcast_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/reply (\d+) (.+)'))
async def admin_reply_handler(event):
    """Handle admin reply command"""
    try:
        if event.sender_id != config.ADMIN_USER_ID:
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

@bot_client.on(events.NewMessage(pattern=r'/priority (\w+) (\w+)'))
async def set_priority_handler(event):
    """Set group priority for specific search type"""
    try:
        if event.sender_id != config.ADMIN_USER_ID:
            return
        
        search_type = event.pattern_match.group(1)
        priority = event.pattern_match.group(2)
        
        if search_type not in SEARCH_COMMANDS:
            await event.respond("❌ Invalid search type")
            return
        
        if priority not in ["primary", "secondary", "tertiary"]:
            await event.respond("❌ Invalid priority. Use: primary, secondary, tertiary")
            return
        
        SEARCH_COMMANDS[search_type]["priority"] = priority
        await event.respond(f"✅ Set {search_type} priority to {priority}")
        
    except Exception as e:
        logger.error(f"❌ Error in set_priority_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/groupstats'))
async def group_stats_handler(event):
    """Show group performance statistics"""
    try:
        if event.sender_id != config.ADMIN_USER_ID:
            return
        
        if not hasattr(search_engine, 'group_performance'):
            await event.respond("❌ No group statistics available")
            return
        
        stats_text = "📊 **GROUP PERFORMANCE STATISTICS**\n\n"
        
        for group_name, performance in search_engine.group_performance.items():
            total = performance["total"]
            success = performance["success"]
            success_rate = (success / total * 100) if total > 0 else 0
            
            stats_text += f"**{group_name}**\n"
            stats_text += f"├─ Total Requests: {total}\n"
            stats_text += f"├─ Success: {success}\n"
            stats_text += f"├─ Success Rate: {success_rate:.1f}%\n"
            stats_text += f"└─ Current Weight: {performance.get('weight', 'N/A')}\n\n"
        
        await event.respond(stats_text, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in group_stats_handler: {e}")

# ================== MAIN FUNCTION ==================

async def main():
    """Main function"""
    global search_engine, bot_info
    
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
        
        logger.info("=" * 60)
        logger.info("🎭 DARK BOXES INTELLIGENCE SYSTEM - OPERATIONAL")
        logger.info("=" * 60)
        
        # Keep the bot running
        await bot_client.run_until_disconnected()
        
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    except Exception as e:
        logger.error(f"💀 Fatal error: {e}")
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
