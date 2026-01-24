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
    NEW_USER_CREDITS: int = int(os.getenv("NEW_USER_CREDITS", "1"))
    REFERRAL_REWARD: int = int(os.getenv("REFERRAL_REWARD", "1"))
    
    # Payment
    UPI_ID: str = os.getenv("UPI_ID", "durgeshraihero@oksbi")
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
        "category": "identity",
        "groups": ["primary", "secondary", "tertiary"]
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
        "category": "identity",
        "groups": ["primary", "secondary"]
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
        "category": "finance",
        "groups": ["primary", "secondary", "tertiary"]
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
        "category": "assets",
        "groups": ["primary", "secondary"]
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
        "category": "finance",
        "groups": ["primary", "secondary"]
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
        "category": "digital",
        "groups": ["primary", "secondary", "tertiary"]
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
        "category": "digital",
        "groups": ["primary", "secondary"]
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
        "category": "assets",
        "groups": ["primary", "secondary"]
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
        "category": "business",
        "groups": ["primary", "secondary"]
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
        "category": "social",
        "groups": ["primary", "secondary", "tertiary"]
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
        "category": "international",
        "groups": ["primary", "tertiary"]
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
        "category": "digital",
        "groups": ["primary", "secondary"]
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
        "category": "finance",
        "groups": ["primary", "secondary"]
    },
    "leak": {
        "name": "🚀 ADVANCED OSINT TOOL",
        "description": "🔮 **SEARCH ANYTHING - MOST POWERFUL TOOL**\n\n🔸 **Universal Search:** Email • Phone (with country code) • Name • Document • Username • Any query\n🔸 **Format:** Phone must include country code (e.g., 917204764637)\n🔸 **Returns:** Comprehensive results in JSON + TXT format\n🔸 **Speed:** Ultra-fast 5-second response\n🔸 **Sources:** Deep web • Breach databases • Global intelligence\n🔸 **Cost:** 3 credits per search",
        "commands": ["/leak"],
        "example": "917204764637 or email@domain.com or John Doe",
        "validation": r"^.+$",
        "cost": 3,
        "priority": "advanced",
        "icon": "🚀",
        "category": "advanced",
        "groups": ["advanced"]
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
    def is_leak_result_message(text: str) -> bool:
        """Check if message is a leak search result"""
        if not text:
            return False
        
        indicators = [
            '🔓 ʟᴇᴀᴋᴇᴅ ᴅᴀᴛᴀ ꜱᴇᴀʀᴄʜ',
            'TRUNCATED - DATA TOO LONG',
            'Full results available as JSON file',
            '📁 Full JSON results for',
            'Service: leak',
            '👤 ʀᴇǫᴜᴇꜱᴛᴇᴅ ʙʏ:',
            '"List":',
            '"HiTeckGroop',
            '"TrueCaller'
        ]
        
        count = sum(1 for ind in indicators if ind in text)
        return count >= 2
    
    @staticmethod
    def clean_content(content: str, search_type: str = None) -> str:
        """Clean and format content - remove usernames and links"""
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
    
    async def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            logger.info("🔌 Connecting to MongoDB...")
            self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            self.client.server_info()
            self.db = self.client[config.MONGODB_DBNAME]
            self.admin_db = AdminDatabaseManager(self)
            
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
                            "searches_remaining": 0
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
            "leak"
        ]
        
        for cmd_key in commands_in_order:
            if cmd_key in SEARCH_COMMANDS:
                cmd = SEARCH_COMMANDS[cmd_key]
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
    def admin_panel() -> List[List[Button]]:
        """Professional admin panel with all features"""
        buttons = [
            [Button.inline("📊 Today's Stats", "admin_today")],
            [Button.inline("👥 User Management", "admin_users")],
            [Button.inline("📈 Search Analytics", "admin_analytics")],
            [Button.inline("💰 Payment Stats", "admin_payments")],
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

# ================== ADMIN PANEL HANDLER ==================

class AdminPanelHandler:
    def __init__(self, db_manager: DatabaseManager, bot_client: TelegramClient):
        self.db = db_manager
        self.bot = bot_client
        self.admin_users = set()
        
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
                
        except Exception as e:
            logger.error(f"❌ Error in admin callback: {e}")
            await event.answer("❌ Error processing request", alert=True)
    
    async def show_admin_panel(self, event):
        """Show main admin panel"""
        admin_text = (
            "⚙️ **DARKBOXES ADMIN PANEL**\n\n"
            "📊 **Quick Stats**\n"
        )
        
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
        """Show paginated user list"""
        try:
            user_list = await self.db.admin_db.get_user_list(page, 15)
            
            users_text = f"👥 **USER LIST** (Page {page}/{user_list['total_pages']})\n"
            users_text += "═══════════════════════\n\n"
            
            for i, user in enumerate(user_list['users'], 1):
                idx = (page - 1) * 15 + i
                username = f"@{user['username']}" if user.get('username') else "No username"
                joined = user.get('joined_at', '')[:10]
                searches = user.get('total_searches', 0)
                
                users_text += (
                    f"{idx}. **{user['first_name']}**\n"
                    f"   ├─ {username}\n"
                    f"   ├─ ID: `{user['user_id']}`\n"
                    f"   ├─ Joined: {joined}\n"
                    f"   └─ Searches: {searches}\n\n"
                )
            
            users_text += f"📊 **Total Users:** {user_list['total_users']}"
            
            await event.edit(
                users_text,
                buttons=OneLineKeyboard.user_list_buttons(page, user_list['total_pages']),
                parse_mode="md"
            )
        except Exception as e:
            logger.error(f"Error showing user list: {e}")
            await event.edit("❌ Error loading user list", buttons=OneLineKeyboard.back_to_admin())
    
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
            
            commands = []
            counts = []
            
            for cmd in command_stats['all_time'][:8]:
                cmd_name = SEARCH_COMMANDS.get(cmd['command'], {}).get('name', cmd['command'])
                commands.append(cmd_name[:15])
                counts.append(cmd['count'])
            
            plt.figure(figsize=(10, 6))
            bars = plt.bar(commands, counts, color='skyblue')
            plt.title('Most Used Commands', fontsize=14, fontweight='bold')
            plt.xlabel('Commands', fontsize=12)
            plt.ylabel('Number of Searches', fontsize=12)
            plt.xticks(rotation=45, ha='right')
            
            for bar in bars:
                height = bar.get_height()
                plt.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}', ha='center', va='bottom')
            
            plt.tight_layout()
            
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
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
            
            dates = [data['date'][5:] for data in activity_data]
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
            
            for i, (s, u) in enumerate(zip(searches, users)):
                plt.text(i - width/2, s + max(searches)*0.01, str(s), 
                        ha='center', va='bottom', fontsize=8)
                plt.text(i + width/2, u + max(users)*0.01, str(u), 
                        ha='center', va='bottom', fontsize=8)
            
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
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
            
            dates = [data['date'][5:] for data in daily_data]
            searches = [data['searches'] for data in daily_data]
            
            plt.figure(figsize=(14, 7))
            plt.plot(dates, searches, marker='o', linewidth=2, markersize=6, color='royalblue')
            plt.fill_between(dates, searches, alpha=0.3, color='skyblue')
            
            plt.title('Daily Search Activity (Last 30 Days)', fontsize=16, fontweight='bold')
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Number of Searches', fontsize=12)
            plt.xticks(rotation=45, ha='right')
            plt.grid(True, alpha=0.3)
            
            max_idx = searches.index(max(searches))
            plt.plot(dates[max_idx], searches[max_idx], 'ro', markersize=10)
            plt.annotate(f'Peak: {searches[max_idx]}', 
                        xy=(dates[max_idx], searches[max_idx]),
                        xytext=(10, 10), textcoords='offset points',
                        fontsize=10, color='red', fontweight='bold')
            
            plt.tight_layout()
            
            total_searches = sum(searches)
            avg_searches = total_searches / len(searches)
            growth = ((searches[-1] - searches[0]) / searches[0] * 100) if searches[0] > 0 else 0
            
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
            if today_stats['payment_count'] > 0:
                payment_text += f"└─ Average Payment: ₹{today_stats['total_payments']/today_stats['payment_count']:.2f}\n\n"
            else:
                payment_text += f"└─ Average Payment: ₹0\n\n"
            
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
            
            dates = [day['_id'][5:] for day in payment_stats['daily_stats']]
            amounts = [day['total_amount'] for day in payment_stats['daily_stats']]
            counts = [day['count'] for day in payment_stats['daily_stats']]
            
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
            
            ax1.plot(dates, amounts, marker='o', linewidth=2, markersize=6, color='green')
            ax1.fill_between(dates, amounts, alpha=0.3, color='lightgreen')
            ax1.set_title('Daily Revenue (Last 30 Days)', fontsize=14, fontweight='bold')
            ax1.set_ylabel('Revenue (₹)', fontsize=12)
            ax1.grid(True, alpha=0.3)
            ax1.tick_params(axis='x', rotation=45)
            
            for i, (date, amount) in enumerate(zip(dates, amounts)):
                if amount == max(amounts):
                    ax1.annotate(f'₹{amount}', xy=(date, amount),
                                xytext=(0, 10), textcoords='offset points',
                                fontsize=10, color='red', fontweight='bold',
                                ha='center')
            
            bars = ax2.bar(dates, counts, color='orange', alpha=0.7)
            ax2.set_title('Daily Payment Count', fontsize=14, fontweight='bold')
            ax2.set_xlabel('Date', fontsize=12)
            ax2.set_ylabel('Number of Payments', fontsize=12)
            ax2.grid(True, alpha=0.3)
            ax2.tick_params(axis='x', rotation=45)
            
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax2.text(bar.get_x() + bar.get_width()/2., height,
                            f'{int(height)}', ha='center', va='bottom', fontsize=9)
            
            plt.tight_layout()
            
            total_revenue = sum(amounts)
            total_payments = sum(counts)
            avg_revenue = total_revenue / len(amounts) if amounts else 0
            avg_payments = total_payments / len(counts) if counts else 0
            
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
                f"└─ Average Payment Value: ₹{total_revenue/total_payments:.2f}\n\n" if total_payments > 0 else ""
                f"📈 **Insights:**\n"
            )
            
            if avg_revenue > 1000:
                caption += "• 📈 Strong revenue performance\n"
            elif avg_revenue > 500:
                caption += "• 📊 Moderate revenue growth\n"
            else:
                caption += "• ⚠️ Revenue needs improvement\n"
            
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
        """Ask for user ID and credits to add"""
        await event.edit(
            "🎯 **ADD CREDITS**\n\n"
            "Enter in format:\n"
            "`user_id credits`\n\n"
            "Example: `123456789 10`\n"
            "This will add 10 credits to user 123456789\n\n"
            "Type the command:",
            buttons=OneLineKeyboard.back_to_admin()
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
                }).limit(10000))
            )
            
            import csv
            from io import StringIO
            
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
            
            if user.get('subscription'):
                expiry = user.get('subscription_expiry', '')
                if expiry:
                    expiry_date = datetime.fromisoformat(expiry)
                    days_left = (expiry_date - datetime.now(timezone.utc)).days
                    detail_text += f"💎 **Subscription**\n"
                    detail_text += f"├─ Plan: {user['subscription']}\n"
                    detail_text += f"└─ Expires in: {days_left} days\n\n"
            
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
                self.admin_users.discard(user_id)
                await event.answer("✅ Admin privileges removed", alert=True)
                await self.show_admin_panel(event)
            else:
                await event.answer("❌ Failed to remove admin", alert=True)
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            await event.answer("❌ Error removing admin", alert=True)

# ================== SEARCH ENGINE WITH MULTI-GROUP & MULTI-RESULT SUPPORT ==================

class SearchEngine:
    def __init__(self, db_manager, user_manager):
        self.db = db_manager
        self.user_manager = user_manager
        self.active_searches = {}
        self.group_performance = {}
    
    async def perform_search(self, search_type: str, query: str, user_id: int) -> Dict:
        """Perform search across ALL groups and collect ALL results"""
        logger.info(f"🚀 Starting {search_type} search: {query} (User: {user_id})")
        
        cmd = SEARCH_COMMANDS.get(search_type, {})
        groups_to_search = cmd.get("groups", ["primary"])
        
        # Create a master search ID for this user's search
        master_search_id = f"{user_id}_{int(time.time())}_{search_type}"
        
        # Store all results from all groups
        all_results = []
        all_files = []
        
        # Create tasks for all groups
        search_tasks = []
        
        for group_key in groups_to_search:
            group = GROUP_PRIORITIES.get(group_key)
            if not group or not group.get("enabled") or not group.get("entity"):
                logger.warning(f"⚠️ Group {group_key} not available")
                continue
            
            # Get command for this group
            command_list = cmd.get("commands", [])
            if not command_list:
                continue
            
            # Use different command if available for variety
            group_idx = groups_to_search.index(group_key)
            command_idx = group_idx % len(command_list)
            primary_command = command_list[command_idx]
            
            # Special handling for leak command
            if search_type == "leak" and group_key == "advanced":
                primary_command = group.get("leak_command", "/leak")
            
            # Create search task for this group
            task = asyncio.create_task(
                self._search_single_group(
                    search_type, query, user_id, group, primary_command, group_key
                )
            )
            search_tasks.append((group_key, task))
        
        if not search_tasks:
            return {
                "success": False,
                "error": "❌ No search groups available. Please try again later."
            }
        
        # Wait for ALL groups to complete (with timeout)
        timeout = max(g.get("timeout", 30) for g in GROUP_PRIORITIES.values() if g.get("enabled"))
        
        try:
            # Use asyncio.gather to run all searches concurrently
            results = await asyncio.wait_for(
                asyncio.gather(*[task for _, task in search_tasks], return_exceptions=True),
                timeout=timeout + 10  # Extra buffer time
            )
            
            # Process results from all groups
            for (group_key, _), result in zip(search_tasks, results):
                if isinstance(result, Exception):
                    logger.error(f"❌ Error from {group_key}: {result}")
                    continue
                
                if result and result.get("success"):
                    all_results.append({
                        "group": group_key,
                        "result": result
                    })
                    
                    # Collect files
                    if result.get("files"):
                        for file_data in result["files"]:
                            file_data["source_group"] = group_key
                            all_files.append(file_data)
                    elif result.get("has_file") and result.get("raw_bytes"):
                        file_data = {
                            "raw_bytes": result["raw_bytes"],
                            "content": result.get("content", ""),
                            "filename": result.get("filename", f"result_{int(time.time())}.txt"),
                            "file_type": result.get("file_type", "txt"),
                            "source_group": group_key
                        }
                        all_files.append(file_data)
        
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Overall timeout for search {master_search_id}")
        
        # Compile final result
        if all_results or all_files:
            return self._compile_results(search_type, query, all_results, all_files)
        else:
            await self._notify_admin(user_id, search_type, query)
            return {
                "success": False,
                "error": f"🔍 **INTELLIGENCE GATHERING FAILED**\n\nQuery: `{query}`\n\n⚠️ **Premium Notice:** Your query has been escalated to our premium database.\nAdministrator will review and respond within 24 hours.\n\n💎 **For instant access, upgrade to:**\n• 👑 Premium Tier: Unlimited searches (30 days)\n• 🚀 Standard Tier: 30 searches (15 days)\n\nContact @darkboxesAdmin for immediate assistance."
            }
    
    async def _search_single_group(self, search_type: str, query: str, user_id: int, 
                                    group: Dict, command: str, group_key: str) -> Dict:
        """Search a single group and collect all results (text + files)"""
        try:
            logger.info(f"📤 Searching {group['name']}: {command} {query}")
            
            # Send message to group
            sent_msg = await user_client.send_message(group["entity"], f"{command} {query}")
            
            # Create search tracking
            search_id = f"{user_id}_{int(time.time())}_{group_key}"
            future = asyncio.get_running_loop().create_future()
            
            self.active_searches[search_id] = {
                "user_id": user_id,
                "future": future,
                "start_time": time.time(),
                "group": group,
                "group_key": group_key,
                "message_id": sent_msg.id,
                "search_type": search_type,
                "query": query,
                "chat_id": group["entity"].id if hasattr(group["entity"], 'id') else str(group["entity"]),
                "expecting_file": True,
                "files_received": [],
                "text_results": [],
                "processed_message_ids": set(),
                "last_activity": time.time()
            }
            
            # Wait for response with group timeout
            try:
                result = await asyncio.wait_for(future, timeout=group["timeout"])
                self._update_group_performance(group['name'], result.get("success", False))
                return result
            except asyncio.TimeoutError:
                # Return partial results if any
                search_info = self.active_searches.get(search_id, {})
                if search_info.get("files_received") or search_info.get("text_results"):
                    return self._compile_group_results(search_info)
                
                self._update_group_performance(group['name'], False)
                return {"success": False}
            finally:
                # Cleanup
                self.active_searches.pop(search_id, None)
                
        except Exception as e:
            logger.error(f"❌ Error searching {group['name']}: {e}")
            return {"success": False}
    
    def _compile_group_results(self, search_info: Dict) -> Dict:
        """Compile results from a single group"""
        files = search_info.get("files_received", [])
        text_results = search_info.get("text_results", [])
        
        if not files and not text_results:
            return {"success": False}
        
        result = {
            "success": True,
            "files": files,
            "text_results": text_results,
            "has_file": len(files) > 0,
            "result": ""
        }
        
        # Combine text results
        if text_results:
            result["result"] = "\n\n".join(text_results)
        
        # If we have files, also include content
        for file_data in files:
            if file_data.get("content"):
                result["content"] = file_data["content"]
                result["raw_bytes"] = file_data.get("raw_bytes")
                result["filename"] = file_data.get("filename")
                break
        
        return result
    
    def _compile_results(self, search_type: str, query: str, 
                         all_results: List[Dict], all_files: List[Dict]) -> Dict:
        """Compile all results from all groups into final response"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        
        # Create summary header
        summary = f"{cmd.get('icon', '🔍')} **{cmd.get('name', 'Search Result')}**\n"
        summary += f"🔍 **Query:** `{query}`\n"
        summary += f"📊 **Sources:** {len(all_results)} database(s)\n"
        summary += "═" * 40 + "\n\n"
        
        # Add text results from all groups
        seen_content = set()  # Avoid duplicates
        
        for result_data in all_results:
            group_key = result_data["group"]
            result = result_data["result"]
            group_name = GROUP_PRIORITIES.get(group_key, {}).get("name", group_key)
            
            # Add text results
            if result.get("result"):
                content = result["result"]
                # Clean content
                cleaned = TextProcessor.clean_content(content, search_type)
                
                # Check for duplicate
                content_hash = hash(cleaned[:200] if len(cleaned) > 200 else cleaned)
                if content_hash in seen_content:
                    continue
                seen_content.add(content_hash)
                
                summary += f"📡 **Source: {group_name}**\n"
                summary += "─" * 30 + "\n"
                summary += cleaned[:2000] + ("\n...(truncated)" if len(cleaned) > 2000 else "") + "\n\n"
            
            # Add text from files
            for text in result.get("text_results", []):
                cleaned = TextProcessor.clean_content(text, search_type)
                content_hash = hash(cleaned[:200] if len(cleaned) > 200 else cleaned)
                if content_hash in seen_content:
                    continue
                seen_content.add(content_hash)
                
                summary += f"📄 **Data from {group_name}**\n"
                summary += cleaned[:1500] + ("\n...(truncated)" if len(cleaned) > 1500 else "") + "\n\n"
        
        # Footer
        summary += "═" * 40 + "\n"
        summary += "⚡ **Powered by DarkBoxes Intelligence System**\n"
        summary += f"🕒 {datetime.now().strftime('%I:%M %p | %d %b %Y')}"
        
        # Compile final result
        final_result = {
            "success": True,
            "result": summary,
            "files": all_files,
            "has_multiple_files": len(all_files) > 0,
            "total_sources": len(all_results)
        }
        
        return final_result
    
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
            chat_id = event.chat_id
            text = message.text or message.raw_text or ""
            
            # Find matching active search
            matching_search = None
            matching_search_id = None
            
            for search_id, search_info in list(self.active_searches.items()):
                try:
                    # Check if message is from the same chat
                    search_chat_id = search_info.get("chat_id")
                    if hasattr(search_info["group"]["entity"], 'id'):
                        search_chat_id = search_info["group"]["entity"].id
                    
                    if chat_id == search_chat_id:
                        # Check if we already processed this message
                        if message.id in search_info.get("processed_message_ids", set()):
                            continue
                        
                        matching_search = search_info
                        matching_search_id = search_id
                        break
                except:
                    continue
            
            if not matching_search:
                return
            
            # Mark message as processed
            matching_search["processed_message_ids"].add(message.id)
            matching_search["last_activity"] = time.time()
            
            # Check for file/document
            file_result = await self._process_file_message(message, matching_search)
            if file_result:
                matching_search["files_received"].append(file_result)
                logger.info(f"📁 Received file from {matching_search['group']['name']}")
            
            # Check for text result
            if text and len(text.strip()) > 50:
                # Skip processing messages
                if TextProcessor.is_processing_message(text):
                    logger.info(f"⏳ Processing message from {matching_search['group']['name']}")
                    return
                
                # Check for no-info messages
                if TextProcessor.is_no_info_message(text):
                    logger.info(f"🚫 No info from {matching_search['group']['name']}")
                    # Complete the search with failure if no other results
                    if not matching_search["files_received"] and not matching_search["text_results"]:
                        self._complete_search(matching_search_id, {"success": False})
                    return
                
                # Check if this looks like leak result data
                if TextProcessor.is_leak_result_message(text) or len(text) > 500:
                    cleaned_text = TextProcessor.clean_content(text, matching_search["search_type"])
                    if cleaned_text and len(cleaned_text) > 50:
                        matching_search["text_results"].append(cleaned_text)
                        logger.info(f"📝 Received text result from {matching_search['group']['name']} ({len(cleaned_text)} chars)")
            
            # Check if we should complete the search
            # Complete if we have files OR substantial text results
            files_received = matching_search.get("files_received", [])
            text_results = matching_search.get("text_results", [])
            
            # Wait a bit more for additional files
            time_elapsed = time.time() - matching_search["start_time"]
            
            # Complete conditions:
            # 1. Have both JSON and TXT files
            # 2. Have at least one file and one text result
            # 3. Time elapsed > 5 seconds and have any result
            should_complete = False
            
            file_types = [f.get("file_type", "") for f in files_received]
            has_json = "json" in file_types
            has_txt = "txt" in file_types
            
            if has_json and has_txt:
                should_complete = True
            elif len(files_received) >= 2:
                should_complete = True
            elif (files_received or text_results) and time_elapsed > 5:
                # Wait a bit more for additional files
                await asyncio.sleep(2)
                should_complete = True
            
            if should_complete:
                result = self._compile_group_results(matching_search)
                self._complete_search(matching_search_id, result)
                
        except Exception as e:
            logger.error(f"❌ Error handling incoming message: {e}")
    
    async def _process_file_message(self, message, search_info: Dict) -> Optional[Dict]:
        """Process a file/document from message"""
        try:
            # Check for document/file
            has_file = False
            
            if message.media and hasattr(message.media, 'document'):
                has_file = True
            elif hasattr(message, 'document') and message.document:
                has_file = True
            elif hasattr(message, 'file') and message.file:
                has_file = True
            
            if not has_file:
                # Check if text message looks like TXT file content
                text = message.text or message.raw_text or ""
                if TextProcessor.is_leak_result_message(text) and len(text) > 1000:
                    # Treat as TXT file content
                    cleaned = TextProcessor.clean_content(text, search_info["search_type"])
                    return {
                        "raw_bytes": cleaned.encode('utf-8'),
                        "content": cleaned,
                        "filename": f"result_{search_info['query']}_{int(time.time())}.txt",
                        "file_type": "txt",
                        "is_text_based": True
                    }
                return None
            
            # Check file size
            if hasattr(message.file, 'size') and message.file.size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
                logger.warning(f"📁 File too large: {message.file.size} bytes")
                return None
            
            # Download file
            logger.info(f"⬇️ Downloading file from {search_info['group']['name']}")
            file_bytes = await message.download_media(bytes)
            
            if not file_bytes:
                logger.error("❌ Failed to download file")
                return None
            
            # Determine file type
            filename = ""
            if hasattr(message.file, 'name') and message.file.name:
                filename = message.file.name.lower()
            
            file_type = "unknown"
            if '.json' in filename or 'json' in filename:
                file_type = "json"
            elif '.txt' in filename or 'text' in filename:
                file_type = "txt"
            
            # Decode content
            content = None
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for encoding in encodings:
                try:
                    content = file_bytes.decode(encoding)
                    logger.info(f"✅ Decoded file with {encoding}")
                    break
                except UnicodeDecodeError:
                    continue
            
            if not content:
                logger.error("❌ Could not decode file")
                return None
            
            # Clean content (remove usernames and links)
            cleaned_content = TextProcessor.clean_content(content, search_info["search_type"])
            
            return {
                "raw_bytes": file_bytes,
                "content": cleaned_content,
                "filename": filename or f"result_{int(time.time())}.{file_type}",
                "file_type": file_type,
                "original_content": content
            }
            
        except Exception as e:
            logger.error(f"❌ Error processing file: {e}")
            return None
    
    def _complete_search(self, search_id: str, result: Dict):
        """Complete a search and set the result"""
        if search_id not in self.active_searches:
            return
        
        search_info = self.active_searches[search_id]
        future = search_info.get("future")
        
        if future and not future.done():
            try:
                future.set_result(result)
            except:
                pass
    
    async def _notify_admin(self, user_id: int, search_type: str, query: str):
        """Notify admin about failed search"""
        try:
            user_info = await self.db.get_user(user_id)
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
                timeout = search_info["group"]["timeout"] + 15
                
                # Check if search has timed out
                if current_time - search_info["start_time"] > timeout:
                    expired.append(search_id)
            
            for search_id in expired:
                search_info = search_engine.active_searches.pop(search_id, None)
                if search_info:
                    future = search_info.get("future")
                    if future and not future.done():
                        # Return partial results if any
                        result = search_engine._compile_group_results(search_info)
                        if result.get("success"):
                            try:
                                future.set_result(result)
                            except:
                                pass
                        else:
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
        
        # Get keyboard
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
        
        # Statistics
        profile_text += f"📊 **Statistics**\n"
        profile_text += f"├─ Total Searches: {user_doc.get('total_searches', 0)}\n"
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
            f"📞 **Contact @darkboxesAdmin to purchase**\n"
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

@bot_client.on(events.CallbackQuery(pattern=r'^main_menu$'))
async def main_menu_callback(event):
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
        
        buttons = OneLineKeyboard.main_menu(is_admin)
        
        await event.edit(message, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in main_menu_callback: {e}")

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
        
        # Show processing message
        if search_type == "leak":
            processing_msg = (
                "🚀 **ADVANCED OSINT SEARCH INITIATED**\n\n"
                f"🔍 **Query:** `{query}`\n"
                f"⚡ **Processing:** Searching all databases...\n"
                f"📁 **Output:** JSON + TXT files\n"
                f"💎 **Cost:** 3 credits\n\n"
                f"⏳ Processing your advanced search..."
            )
        else:
            processing_msg = PremiumFormatter.format_processing(search_type, query)
        
        status = await event.respond(processing_msg, parse_mode="md")
        
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
        
        # Delete status message
        try:
            await status.delete()
        except:
            pass
        
        if result["success"]:
            # Send main text result
            if result.get("result"):
                # Split long messages
                result_text = result["result"]
                chunks = TextProcessor.split_long_text(result_text, 4000)
                
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await event.respond(chunk, parse_mode="md")
                    else:
                        await event.respond(f"📄 **Continued ({i+1}/{len(chunks)})**\n\n{chunk}", parse_mode="md")
            
            # Send files
            if result.get("files"):
                for file_data in result["files"]:
                    await send_file_to_user(event, file_data, query, search_type)
            
            # Update search count
            await db_manager.update_searches(user_id, search_type, query, True)
        else:
            await event.respond(result.get("error", "❌ Search failed"), parse_mode="md")
            await db_manager.update_searches(user_id, search_type, query, False)
        
        # Clear state
        user_states.pop(user_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_search_query: {e}")
        await event.respond("❌ An error occurred during processing.")
        user_states.pop(event.sender_id, None)

async def send_file_to_user(event, file_data: Dict, query: str, search_type: str):
    """Send file to user with proper formatting"""
    try:
        file_type = file_data.get("file_type", "txt")
        content = file_data.get("content", "")
        raw_bytes = file_data.get("raw_bytes")
        source_group = file_data.get("source_group", "Unknown")
        
        # First, send cleaned content as text message
        if content and len(content) > 100:
            cleaned_content = TextProcessor.clean_content(content, search_type)
            
            if len(cleaned_content) > 100:
                # Split if too long
                chunks = TextProcessor.split_long_text(cleaned_content, 3500)
                
                for i, chunk in enumerate(chunks):
                    header = f"📄 **{file_type.upper()} DATA** (Source: {GROUP_PRIORITIES.get(source_group, {}).get('name', source_group)})\n"
                    header += "─" * 30 + "\n\n"
                    
                    if len(chunks) > 1:
                        header = f"📄 **{file_type.upper()} DATA** (Part {i+1}/{len(chunks)})\n"
                        header += "─" * 30 + "\n\n"
                    
                    await event.respond(header + chunk, parse_mode="md")
        
        # Then send as file (if it's a file type)
        if raw_bytes and file_type in ["json", "txt"]:
            filename = file_data.get("filename", f"result_{query}_{int(time.time())}.{file_type}")
            caption = f"📁 **{file_type.upper()} File**\n🔍 Query: `{query}`"
            
            await event.respond(
                file=raw_bytes,
                caption=caption,
                parse_mode="md"
            )
            logger.info(f"✅ Sent {file_type} file to user")
        
    except Exception as e:
        logger.error(f"❌ Error sending file to user: {e}")

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
        
        buttons = [[Button.inline("« Back to Admin", "admin_panel")]]
        
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
        
        user_states[event.sender_id] = {
            "action": "confirm_broadcast",
            "message": message
        }
        
        buttons = [
            [Button.inline("✅ Yes, Send Broadcast", "confirm_broadcast_yes")],
            [Button.inline("❌ Cancel", "admin_panel")]
        ]
        
        await event.respond(
            f"📢 **BROADCAST CONFIRMATION**\n\n"
            f"**Message:**\n{message[:500]}...\n\n"
            f"Are you sure you want to send this to all users?",
            buttons=buttons,
            parse_mode="md"
        )
        
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
        
        target_id = int(user_input)
        user = await db_manager.get_user(target_id)
        
        if not user:
            await event.respond(f"❌ User with ID {target_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        if user.get('is_banned'):
            buttons = OneLineKeyboard.confirm_buttons("unban", target_id)
            await event.respond(
                f"🚫 **USER IS ALREADY BANNED**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{target_id}`\n\n"
                f"Do you want to unban this user?",
                buttons=buttons,
                parse_mode="md"
            )
        else:
            buttons = OneLineKeyboard.confirm_buttons("ban", target_id)
            await event.respond(
                f"🚫 **BAN USER CONFIRMATION**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{target_id}`\n\n"
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
        
        target_id = int(user_input)
        user = await db_manager.get_user(target_id)
        
        if not user:
            await event.respond(f"❌ User with ID {target_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        if user.get('is_admin'):
            buttons = OneLineKeyboard.confirm_buttons("remove_admin", target_id)
            await event.respond(
                f"👑 **REMOVE ADMIN PRIVILEGES**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{target_id}`\n\n"
                f"Do you want to remove admin privileges?",
                buttons=buttons,
                parse_mode="md"
            )
        else:
            buttons = OneLineKeyboard.confirm_buttons("add_admin", target_id)
            await event.respond(
                f"👑 **ADD ADMIN PRIVILEGES**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{target_id}`\n\n"
                f"Are you sure you want to add this user as admin?",
                buttons=buttons,
                parse_mode="md"
            )
        
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_management: {e}")
        await event.respond("❌ Error processing admin management request.")

async def handle_admin_add_credits(event):
    """Handle admin add credits"""
    try:
        user_input = event.text.strip()
        parts = user_input.split()
        
        if len(parts) != 2:
            await event.respond("❌ Invalid format. Use: `user_id credits`")
            return
        
        if not parts[0].isdigit() or not parts[1].isdigit():
            await event.respond("❌ Both user ID and credits must be numbers.")
            return
        
        target_id = int(parts[0])
        credits = int(parts[1])
        
        if credits <= 0 or credits > 1000:
            await event.respond("❌ Credits must be between 1 and 1000.")
            return
        
        user = await db_manager.get_user(target_id)
        if not user:
            await event.respond(f"❌ User with ID {target_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        # Add credits
        success = await db_manager.add_credits(target_id, credits)
        
        if success:
            await event.respond(
                f"✅ **CREDITS ADDED SUCCESSFULLY**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{target_id}`\n"
                f"🎯 Credits Added: {credits}\n"
                f"💰 New Balance: {user.get('searches_remaining', 0) + credits}",
                parse_mode="md"
            )
            
            # Notify user
            try:
                await bot_client.send_message(
                    target_id,
                    f"🎁 **CREDITS ADDED**\n\n"
                    f"Administrator has added {credits} credits to your account.\n"
                    f"💰 New Balance: {user.get('searches_remaining', 0) + credits}\n\n"
                    f"Thank you for using DarkBoxes!",
                    parse_mode="md"
                )
            except:
                pass
        else:
            await event.respond("❌ Failed to add credits.")
        
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
                await asyncio.sleep(0.1)
            except:
                failed += 1
        
        user_states.pop(user_id, None)
        
        await event.edit(
            f"✅ **BROADCAST COMPLETE**\n\n"
            f"📊 **Results:**\n"
            f"├─ Successfully Sent: {sent}\n"
            f"└─ Failed: {failed}",
            buttons=OneLineKeyboard.back_to_admin(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in confirm_broadcast_handler: {e}")
        await event.answer("❌ Error sending broadcast", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^confirm_'))
async def confirm_action_handler(event):
    """Handle confirmation actions"""
    try:
        data = event.data.decode()
        parts = data.split('_')
        
        if len(parts) < 3:
            return
        
        action = parts[1]
        target_id = int(parts[2])
        
        if action == "ban":
            success = await db_manager.ban_user(target_id, "Admin action")
            if success:
                await event.answer("✅ User banned successfully", alert=True)
            else:
                await event.answer("❌ Failed to ban user", alert=True)
        
        elif action == "unban":
            success = await db_manager.unban_user(target_id)
            if success:
                await event.answer("✅ User unbanned successfully", alert=True)
            else:
                await event.answer("❌ Failed to unban user", alert=True)
        
        elif action == "add" and len(parts) > 3 and parts[2] == "admin":
            target_id = int(parts[3])
            success = await db_manager.add_admin(target_id)
            if success:
                admin_panel.admin_users.add(target_id)
                await event.answer("✅ User added as admin", alert=True)
            else:
                await event.answer("❌ Failed to add admin", alert=True)
        
        elif action == "remove" and len(parts) > 3 and parts[2] == "admin":
            target_id = int(parts[3])
            success = await db_manager.remove_admin(target_id)
            if success:
                admin_panel.admin_users.discard(target_id)
                await event.answer("✅ Admin privileges removed", alert=True)
            else:
                await event.answer("❌ Failed to remove admin", alert=True)
        
        await admin_panel.show_admin_panel(event)
        
    except Exception as e:
        logger.error(f"❌ Error in confirm_action_handler: {e}")
        await event.answer("❌ Error processing action", alert=True)

@bot_client.on(events.NewMessage(pattern=r'/reply (\d+) (.+)'))
async def admin_reply_handler(event):
    """Handle admin reply command"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            return
        
        target_id = int(event.pattern_match.group(1))
        message = event.pattern_match.group(2)
        
        await bot_client.send_message(
            target_id,
            f"👤 **ADMINISTRATOR RESPONSE**\n\n{message}\n\n— DarkBoxes Support Team",
            parse_mode="md"
        )
        
        await event.respond(f"✅ Reply sent to user {target_id}")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_reply_handler: {e}")
        await event.respond("❌ Error sending reply")

@bot_client.on(events.NewMessage(pattern=r'/addcredits (\d+) (\d+)'))
async def add_credits_command(event):
    """Handle /addcredits command"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            return
        
        target_id = int(event.pattern_match.group(1))
        credits = int(event.pattern_match.group(2))
        
        success = await db_manager.add_credits(target_id, credits)
        
        if success:
            await event.respond(f"✅ Added {credits} credits to user {target_id}")
            try:
                await bot_client.send_message(
                    target_id,
                    f"🎁 **CREDITS ADDED**\n\nAdministrator added {credits} credits to your account.",
                    parse_mode="md"
                )
            except:
                pass
        else:
            await event.respond("❌ Failed to add credits")
        
    except Exception as e:
        logger.error(f"❌ Error in add_credits_command: {e}")
        await event.respond("❌ Error adding credits")

@user_client.on(events.NewMessage())
async def handle_all_messages(event):
    """Handle all incoming messages for search responses"""
    try:
        if search_engine:
            await search_engine.handle_incoming_message(event)
    except Exception as e:
        pass

# ================== MAIN FUNCTION ==================

async def main():
    """Main function"""
    global search_engine, admin_panel, bot_info
    
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
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Run the bot
    asyncio.run(main())
            
