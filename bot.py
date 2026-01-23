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
    ADMIN_WHATSAPP: str = os.getenv("ADMIN_WHATSAPP", "https://wa.me/911234567890")

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
        "name": "🚀 Advanced Search Engine",
        "identifier": -1001234567890,  # Replace with your advanced group ID
        "timeout": 10,
        "weight": 15,
        "enabled": True,
        "entity": None,
        "leak_command": "/leak",
        "returns_multiple": True,
        "formats": ["json", "text"]
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
        "features": [
            "✅ 10 Premium Searches",
            "✅ Standard Databases", 
            "✅ 7-day Access",
            "✅ Email Support"
        ],
        "description": "🎯 For: New users trying the service",
        "icon": "💰",
        "color": "#27AE60",
        "whatsapp_support": False
    },
    "standard": {
        "name": "🚀 STANDARD TIER",
        "price": 249,
        "searches": 30,
        "validity": "15 days",
        "features": [
            "✅ 30 Premium Searches",
            "✅ All Databases",
            "✅ 15-day Access",
            "✅ Priority Support",
            "✅ Search History Saved"
        ],
        "description": "🎯 For: Regular users needing more searches",
        "icon": "🚀",
        "color": "#F39C12",
        "whatsapp_support": False
    },
    "premium": {
        "name": "👑 PREMIUM TIER",
        "price": 499,
        "searches": "∞",
        "validity": "30 days",
        "features": [
            "✅ Unlimited Searches (30 days)",
            "✅ All Premium Databases",
            "✅ Priority Processing",
            "✅ 24/7 WhatsApp Support",
            "✅ Extended Search History"
        ],
        "description": "🎯 For: Power users & professionals",
        "icon": "👑",
        "color": "#9B59B6",
        "whatsapp_support": True
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
        "name": "🚀 Search Anything",
        "description": "🔮 **ADVANCED UNIVERSAL SEARCH**\n\n🔸 **Most Powerful Tool** - Finds ANY information\n🔸 **Input:** Email • Phone (with country code) • Name • Document • Username • Any query\n🔸 **Format:** Phone must include country code (e.g., 917204764637)\n🔸 **Returns:** Comprehensive results in JSON + Text format\n🔸 **Speed:** Ultra-fast 10-second response\n🔸 **Sources:** Deep web • Breach databases • Global intelligence\n🔸 **Cost:** 3 credits per search",
        "commands": ["/leak"],
        "example": "917204764637 or email@domain.com or John Doe",
        "validation": r"^.+$",  # Accepts any input
        "cost": 3,
        "priority": "advanced",
        "icon": "🚀",
        "category": "advanced",
        "group": "advanced",
        "returns_multiple": True,
        "formats": ["json", "text"]
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
    
    @staticmethod
    def format_leak_result(query: str, json_content: str = None, text_content: str = None) -> Tuple[str, Optional[str]]:
        """Format leak search results"""
        # Main result message
        result = f"🚀 **ADVANCED SEARCH COMPLETE**\n\n"
        result += f"🔍 **Query:** `{query}`\n"
        result += f"⚡ **Processing Time:** Ultra-fast\n"
        result += f"📊 **Sources:** Multiple intelligence databases\n"
        result += "─" * 40 + "\n\n"
        
        # Add text content if available
        if text_content and len(text_content.strip()) > 50:
            # Truncate text if too long for Telegram
            if len(text_content) > 2000:
                text_preview = text_content[:2000] + "\n\n... (truncated, full text in separate message)"
                result += f"📄 **TEXT REPORT:**\n{text_preview}\n\n"
            else:
                result += f"📄 **TEXT REPORT:**\n{text_content}\n\n"
        elif text_content:
            result += f"📄 **TEXT DATA:**\n{text_content}\n\n"
        else:
            result += "📄 **Text Report:** Not available\n\n"
        
        # Add JSON summary if available
        if json_content:
            try:
                json_data = json.loads(json_content)
                result += f"📊 **DATA FIELDS FOUND ({len(json_data)}):**\n"
                for key in list(json_data.keys())[:10]:  # Show first 10 keys
                    result += f"• {key}\n"
                if len(json_data) > 10:
                    result += f"• ... and {len(json_data) - 10} more fields\n"
                result += "\n"
            except:
                result += "📊 **JSON Data Available** (download file for details)\n\n"
        
        result += "─" * 40 + "\n"
        result += "⚡ **Powered by DarkBoxes Advanced Intelligence**\n"
        result += "🔐 **JSON file attached for detailed analysis**\n"
        result += f"🕒 {datetime.now().strftime('%I:%M %p | %d %b %Y')}"
        
        return result, text_content

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
    
    @staticmethod
    def extract_text_from_file(content: str) -> str:
        """Extract clean text from file content"""
        # Remove JSON-like structures
        content = re.sub(r'\{.*?\}', '', content, flags=re.DOTALL)
        content = re.sub(r'\[.*?\]', '', content, flags=re.DOTALL)
        
        # Remove excessive whitespace
        content = re.sub(r'\n\s*\n', '\n\n', content)
        
        # Remove short lines (likely metadata)
        lines = content.split('\n')
        filtered_lines = []
        for line in lines:
            line = line.strip()
            if len(line) > 10 and not line.startswith('---'):
                filtered_lines.append(line)
        
        return '\n'.join(filtered_lines)
    
    @staticmethod
    def extract_json_from_content(content: str) -> Optional[str]:
        """Extract JSON from mixed content"""
        try:
            # Try to find JSON object
            json_match = re.search(r'(\{.*\})', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                # Validate it's proper JSON
                json.loads(json_str)
                return json_str
        except:
            pass
        
        try:
            # Try to find JSON array
            json_match = re.search(r'(\[.*\])', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                json.loads(json_str)
                return json_str
        except:
            pass
        
        return None

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
            "leak"  # Advanced search
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
            buttons.append([Button.inline("⚙️ Admin Panel", "admin_panel")])
        
        return buttons
    
    @staticmethod
    def subscription_plans() -> List[List[Button]]:
        """Premium plan selection"""
        buttons = [
            [Button.inline("💰 BASIC TIER - ₹99", "plan_basic")],
            [Button.inline("🚀 STANDARD TIER - ₹249", "plan_standard")],
            [Button.inline("👑 PREMIUM TIER - ₹499", "plan_premium")],
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

# ================== SEARCH ENGINE WITH MULTIPLE FILE HANDLING ==================

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
                    "priority": group["weight"],
                    "files_received": [],
                    "text_received": None
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
            "error": f"🔍 **INTELLIGENCE GATHERING FAILED**\n\nQuery: `{query}`\n\n⚠️ **Premium Notice:** Your query has been escalated to our premium database.\nAdministrator will review and respond within 24 hours.\n\n💎 **For instant access, upgrade to premium:**\n• 🚀 Standard Tier - 30 searches (15 days)\n• 👑 Premium Tier - Unlimited searches (30 days)\n\nContact @darkboxesAdmin for immediate assistance."
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
                "expecting_multiple": True,
                "file_wait_start": None,
                "priority": advanced_group["weight"],
                "files_received": [],
                "text_received": None,
                "json_received": None,
                "expecting_formats": ["json", "text"],
                "max_wait_time": 10
            }
            
            # Wait for response (10 seconds timeout for leak search)
            try:
                result = await asyncio.wait_for(future, timeout=10)
                
                if result["success"]:
                    logger.info(f"✅ Advanced leak search successful with {len(result.get('files', []))} files")
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
                        # Check if it's a text message for leak search
                        text = message.text or message.raw_text or ""
                        if text and len(text.strip()) > 50:
                            # Check if this looks like a text report (not JSON)
                            if not text.strip().startswith('{') and not text.strip().startswith('['):
                                # This is likely a text report for leak search
                                if search_info["search_type"] == "leak":
                                    await self._process_leak_text_response(search_id, search_info, text)
                                    return
                        
                        file_check = await self._check_and_process_file(message, search_info)
                        if file_check is not None:
                            logger.info(f"📁 Found file in {search_info['group']['name']}")
                            await self._process_search_response(search_id, search_info, message)
                            return
                except:
                    continue
                    
        except Exception as e:
            logger.error(f"❌ Error handling incoming message: {e}")
    
    async def _process_leak_text_response(self, search_id: str, search_info: Dict, text: str):
        """Process text response for leak search"""
        try:
            logger.info(f"📝 Processing text response for leak search")
            
            # Clean the text
            cleaned_text = TextProcessor.clean_content(text, "leak")
            
            # Check if it's JSON
            json_content = TextProcessor.extract_json_from_content(cleaned_text)
            if json_content:
                logger.info(f"📊 Found JSON in text response")
                search_info["json_received"] = json_content
                
                # Extract text from remaining content
                remaining_text = cleaned_text.replace(json_content, '').strip()
                if len(remaining_text) > 50:
                    search_info["text_received"] = TextProcessor.extract_text_from_file(remaining_text)
            else:
                # It's plain text
                search_info["text_received"] = TextProcessor.extract_text_from_file(cleaned_text)
            
            # Check if we have both formats or waited long enough
            current_time = time.time()
            elapsed = current_time - search_info["start_time"]
            
            has_json = search_info["json_received"] is not None
            has_text = search_info["text_received"] is not None and len(search_info["text_received"]) > 50
            
            if (has_json and has_text) or elapsed > search_info.get("max_wait_time", 10):
                logger.info(f"✅ Leak search complete: JSON={has_json}, Text={has_text}")
                
                # Prepare final result
                result_text, full_text = PremiumFormatter.format_leak_result(
                    search_info["query"],
                    search_info["json_received"],
                    search_info["text_received"]
                )
                
                result = {
                    "success": True,
                    "result": result_text,
                    "has_multiple_formats": True,
                    "json_content": search_info["json_received"],
                    "text_content": full_text if full_text else search_info["text_received"]
                }
                
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result(result)
                    del self.active_searches[search_id]
                
        except Exception as e:
            logger.error(f"❌ Error processing leak text response: {e}")
    
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
            file_result = await self._check_and_process_file(message, search_info)
            
            if file_result is not None:
                logger.info(f"📁 Processing leak search file")
                
                # Determine file type from filename
                filename = ""
                if hasattr(message.file, 'name') and message.file.name:
                    filename = message.file.name.lower()
                
                # Check if it's JSON file
                if '.json' in filename:
                    logger.info(f"📊 Found JSON file")
                    search_info["json_received"] = file_result.get("content", "")
                elif '.txt' in filename or 'text' in filename:
                    logger.info(f"📄 Found TEXT file")
                    search_info["text_received"] = file_result.get("content", "")
                else:
                    # Try to determine content type
                    content = file_result.get("content", "")
                    # Check if content is JSON
                    json_content = TextProcessor.extract_json_from_content(content)
                    if json_content:
                        logger.info(f"📊 Content appears to be JSON")
                        search_info["json_received"] = json_content
                    else:
                        logger.info(f"📄 Content appears to be text")
                        search_info["text_received"] = TextProcessor.extract_text_from_file(content)
                
                # Check if we have both formats
                has_json = search_info["json_received"] is not None and len(search_info["json_received"]) > 50
                has_text = search_info["text_received"] is not None and len(search_info["text_received"]) > 50
                
                current_time = time.time()
                elapsed = current_time - search_info["start_time"]
                
                if (has_json and has_text) or elapsed > search_info.get("max_wait_time", 10):
                    logger.info(f"✅ Leak search complete: JSON={has_json}, Text={has_text}")
                    
                    # Prepare final result
                    result_text, full_text = PremiumFormatter.format_leak_result(
                        search_info["query"],
                        search_info["json_received"],
                        search_info["text_received"]
                    )
                    
                    result = {
                        "success": True,
                        "result": result_text,
                        "has_multiple_formats": True,
                        "json_content": search_info["json_received"],
                        "text_content": full_text if full_text else search_info["text_received"]
                    }
                    
                    if search_id in self.active_searches:
                        future = self.active_searches[search_id]["future"]
                        if not future.done():
                            future.set_result(result)
                        del self.active_searches[search_id]
                
                return
            
            # Check for text response
            text = message.text or message.raw_text or ""
            if text and len(text.strip()) > 50:
                # This might be the text report
                await self._process_leak_text_response(search_id, search_info, text)
                
        except Exception as e:
            logger.error(f"❌ Error processing leak response: {e}")
    
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
                "└─ Search History\n\n"
                "👑 **PREMIUM TIER** - ₹499\n"
                "├─ Unlimited Searches\n"
                "├─ Premium Databases\n"
                "├─ Priority Processing\n"
                "├─ 24/7 WhatsApp Support\n"
                "└─ Extended History\n\n"
                "Select a plan to continue:",
                buttons=OneLineKeyboard.subscription_plans(),
                parse_mode="md"
            )
            return
        
        cmd = SEARCH_COMMANDS[search_type]
        
        # Special formatting for leak search
        if search_type == "leak":
            leak_text = (
                f"🚀 **{cmd['name']}**\n\n"
                f"{cmd['description']}\n\n"
                f"⚡ **ULTRA-FAST PROCESSING** (10 seconds)\n"
                f"💎 **Cost:** {cmd['cost']} credits\n"
                f"📊 **Returns:** JSON file + Text report\n"
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
                plan = SUBSCRIPTION_PLANS.get(user_doc['subscription'], {})
                plan_name = plan.get('name', user_doc['subscription'])
                profile_text += f"├─ Subscription: {plan_name}\n"
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
            "├─ ✅ 10 Premium Searches\n"
            "├─ ✅ Standard Databases\n"
            "├─ ✅ 7-day Access\n"
            "└─ ✅ Email Support\n"
            "🎯 **For:** New users trying the service\n\n"
            "🚀 **STANDARD TIER** - ₹249\n"
            "├─ ✅ 30 Premium Searches\n"
            "├─ ✅ All Databases\n"
            "├─ ✅ 15-day Access\n"
            "├─ ✅ Priority Support\n"
            "└─ ✅ Search History Saved\n"
            "🎯 **For:** Regular users needing more searches\n\n"
            "👑 **PREMIUM TIER** - ₹499\n"
            "├─ ✅ Unlimited Searches (30 days)\n"
            "├─ ✅ All Premium Databases\n"
            "├─ ✅ Priority Processing\n"
            "├─ ✅ 24/7 WhatsApp Support\n"
            "└─ ✅ Extended Search History\n"
            "🎯 **For:** Power users & professionals\n\n"
            "📞 **Contact @darkboxesAdmin to purchase**\n"
            f"💳 **UPI ID:** `{config.UPI_ID}`\n"
            f"📱 **WhatsApp:** {config.ADMIN_WHATSAPP}\n\n"
            "🔒 **Payment Instructions:**\n"
            "1. Send payment via UPI to the ID above\n"
            "2. Send payment screenshot to @darkboxesAdmin\n"
            "3. Include your User ID in the message\n"
            "4. Your account will be upgraded within 5 minutes"
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
            plan_details += f"{feature}\n"
        
        plan_details += f"\n{plan['description']}\n\n"
        
        plan_details += f"📞 **To Purchase:**\n"
        plan_details += f"1. Send ₹{plan['price']} to UPI: `{config.UPI_ID}`\n"
        plan_details += f"2. Send payment screenshot to @darkboxesAdmin\n"
        
        if plan.get('whatsapp_support'):
            plan_details += f"3. For WhatsApp support: {config.ADMIN_WHATSAPP}\n"
        
        plan_details += f"4. Include your User ID: `{event.sender_id}`\n"
        plan_details += f"5. Your account will be upgraded within 5 minutes\n\n"
        
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
            f"📱 **WhatsApp Support:** {config.ADMIN_WHATSAPP}\n"
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
                "🚀 **ADVANCED SEARCH INITIATED**\n\n"
                f"🔍 **Query:** `{query}`\n"
                f"⚡ **Processing:** Ultra-fast (10 seconds)\n"
                f"📊 **Output:** JSON file + Text report\n"
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
                "👑 **PREMIUM TIER** - ₹499\n"
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
            # Handle leak search with multiple formats
            if search_type == "leak":
                # Send the formatted result
                await event.respond(result["result"], parse_mode="md")
                
                # Send JSON as file if available
                if result.get("json_content"):
                    # Create JSON file
                    json_filename = f"result_{int(time.time())}.json"
                    json_bytes = result["json_content"].encode('utf-8')
                    
                    await event.respond(
                        file=json_bytes,
                        caption=f"📊 **JSON Data File**\nQuery: `{query}`"
                    )
                
                # Send text report as separate message if not already included
                if result.get("text_content") and len(result["text_content"]) > 100:
                    text_report = f"📄 **TEXT REPORT**\n\n{result['text_content']}"
                    
                    # Split if too long
                    if len(text_report) > 4000:
                        chunks = [text_report[i:i+4000] for i in range(0, len(text_report), 4000)]
                        for i, chunk in enumerate(chunks, 1):
                            if i == 1:
                                await event.respond(chunk, parse_mode="md")
                            else:
                                await event.respond(chunk)
                    else:
                        await event.respond(text_report, parse_mode="md")
            else:
                # Regular search result
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
        
        # Get keyboard - ONE COMMAND PER LINE
        buttons = OneLineKeyboard.main_menu(is_admin)
        
        await event.edit(message, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in main_menu_callback: {e}")

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
                "👑 **PREMIUM TIER** - ₹499\n"
                "• Unlimited searches (30 days)\n"
                "• All premium databases\n"
                "• Priority processing\n\n"
                "Contact @darkboxesAdmin for assistance.",
                buttons=OneLineKeyboard.subscription_plans()
            )
            return
        
        # Perform leak search
        leak_warning = (
            "🚀 **ADVANCED SEARCH INITIATED**\n\n"
            f"🔍 **Query:** `{query}`\n"
            f"⚡ **Processing:** Ultra-fast (10 seconds)\n"
            f"📊 **Output:** JSON file + Text report\n"
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
            # Handle leak search with multiple formats
            # Send the formatted result
            await event.respond(result["result"], parse_mode="md")
            
            # Send JSON as file if available
            if result.get("json_content"):
                # Create JSON file
                json_filename = f"result_{int(time.time())}.json"
                json_bytes = result["json_content"].encode('utf-8')
                
                await event.respond(
                    file=json_bytes,
                    caption=f"📊 **JSON Data File**\nQuery: `{query}`"
                )
            
            # Send text report as separate message if not already included
            if result.get("text_content") and len(result["text_content"]) > 100:
                text_report = f"📄 **TEXT REPORT**\n\n{result['text_content']}"
                
                # Split if too long
                if len(text_report) > 4000:
                    chunks = [text_report[i:i+4000] for i in range(0, len(text_report), 4000)]
                    for i, chunk in enumerate(chunks, 1):
                        if i == 1:
                            await event.respond(chunk, parse_mode="md")
                        else:
                            await event.respond(chunk)
                else:
                    await event.respond(text_report, parse_mode="md")
            
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
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # Run the bot
    asyncio.run(main())
