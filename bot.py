"""
Premium Information Bot - Professional Edition
Advanced data retrieval system with premium subscription model
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
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

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
    USER_API_HASH: str = os.getenv("USER_API_HASH", "").strip()
    USER_PHONE: str = os.getenv("USER_PHONE", "").strip()
    USER_SESSION_FILE: str = "relay_session.session"
    
    # Admin and mandatory channel
    ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))
    MANDATORY_CHANNEL: str = os.getenv("MANDATORY_CHANNEL", "darkboxesv1")
    
    # Database
    MONGODB_URI: str = os.getenv("MONGODB_URI", "").strip()
    MONGODB_DBNAME: str = "premium_bot_db"
    
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

# ================== SUBSCRIPTION PLANS ==================

SUBSCRIPTION_PLANS = {
    "basic": {
        "name": "Basic Plan",
        "price": 100,
        "searches": 5,
        "validity": "7 days",
        "features": ["5 premium searches", "Standard data sources", "7-day access"],
        "recommended": False
    },
    "standard": {
        "name": "Standard Plan",
        "price": 200,
        "searches": 10,
        "validity": "7 days",
        "features": ["10 premium searches", "Extended data sources", "Priority processing"],
        "recommended": False
    },
    "premium": {
        "name": "Premium Plan",
        "price": 500,
        "searches": "Unlimited",
        "validity": "7 days",
        "features": ["Unlimited searches", "All data sources", "Priority processing", "24/7 support"],
        "recommended": True
    },
    "enterprise": {
        "name": "Enterprise Plan",
        "price": 800,
        "searches": "Unlimited",
        "validity": "30 days",
        "features": ["Unlimited searches", "All premium sources", "Highest priority", "Dedicated support", "API access"],
        "recommended": False
    }
}

# ================== LOGGING SETUP ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)

logger = logging.getLogger("PremiumBot")

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

# ================== DESTINATION GROUPS ==================

DESTINATION_GROUPS = [
    {
        "name": "Main Database",
        "identifier": -1003596998816,
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 1
    },
    {
        "name": "Premium Database",
        "identifier": "darkboxesv3",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 2
    },
    {
        "name": "Enterprise Database",
        "identifier": "nex_chats",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 3
    }
]

# ================== SEARCH COMMANDS ==================

SEARCH_COMMANDS = {
    "phone": {
        "name": "Phone Number Lookup",
        "description": "Comprehensive information retrieval from mobile number\n• Input: 10-digit Indian mobile number\n• Returns: Full name, father's name, Aadhar ID, complete residential address, alternate numbers\n• Sources: Government databases, telecom records, public directories",
        "commands": ["/num", "/phone", "/mobile"],
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "cost": 1
    },
    "family": {
        "name": "Family Information",
        "description": "Complete family member details from Aadhar number\n• Input: 12-digit Aadhar number\n• Returns: All registered family members with names, relations, ages\n• Sources: UIDAI database, family registration records",
        "commands": ["/familyinfo", "/family"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "cost": 1
    },
    "aadhar": {
        "name": "Aadhar Comprehensive",
        "description": "Complete Aadhar database cross-reference\n• Input: 12-digit Aadhar number\n• Returns: All linked mobile numbers, bank accounts, addresses, biometric status\n• Sources: UIDAI, bank linkages, government records",
        "commands": ["/aadhar", "/adh", "/aadhaar"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "cost": 2
    },
    "vehicle": {
        "name": "Vehicle Intelligence",
        "description": "Complete vehicle and owner intelligence\n• Input: Vehicle number (Format: UP53CZ3391)\n• Returns: Full vehicle details, complete owner information including mobile number, address, registration history\n• Premium Feature: Access celebrity vehicle databases",
        "commands": ["/vehicle", "/vnum", "/car"],
        "example": "UP53CZ3391",
        "validation": r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$",
        "cost": 2
    },
    "upi": {
        "name": "UPI Financial Intelligence",
        "description": "UPI account and transaction analysis\n• Input: UPI ID (username@paytm/bank)\n• Returns: Account holder name, linked bank, transaction patterns, KYC status\n• Sources: NPCI databases, bank records",
        "commands": ["/upiinfo", "/upi"],
        "example": "username@paytm",
        "validation": r"^[\w\.-]+@[\w\.-]+$",
        "cost": 1
    },
    "email": {
        "name": "Email Intelligence",
        "description": "Complete email profile analysis\n• Input: Email address\n• Returns: Personal information, social media links, data breach history, associated accounts\n• Sources: Breach databases, social media, public records",
        "commands": ["/email", "/mail"],
        "example": "user@example.com",
        "validation": r"^[\w\.-]+@[\w\.-]+\.\w+$",
        "cost": 1
    },
    "telegram": {
        "name": "Telegram Intelligence",
        "description": "Telegram profile deep analysis\n• Input: Telegram username or phone\n• Returns: Mobile number, profile details, linked accounts, activity patterns\n• Daily limit applies for security",
        "commands": ["/tg", "/telegram"],
        "example": "@username or 9876543210",
        "validation": r"^(@?\w{5,32}|\d{10})$",
        "daily_limit": 1,
        "cost": 2
    },
    "imei": {
        "name": "Device Intelligence",
        "description": "Mobile device comprehensive analysis\n• Input: 15-digit IMEI number\n• Returns: Device make/model, purchase details, location history, current user\n• Sources: Manufacturer databases, carrier records",
        "commands": ["/imei", "/device"],
        "example": "123456789012345",
        "validation": r"^\d{15}$",
        "cost": 2
    },
    "gst": {
        "name": "Business Intelligence",
        "description": "GST business comprehensive analysis\n• Input: GST number\n• Returns: Business details, owner information, financial patterns, compliance status\n• Sources: Government business registries",
        "commands": ["/gst", "/gstin"],
        "example": "29ABCDE1234F1Z5",
        "validation": r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$",
        "cost": 1
    },
    "insta": {
        "name": "Instagram Intelligence",
        "description": "Instagram profile deep analysis\n• Input: Instagram username\n• Returns: Personal information, contact details, location data, linked accounts\n• Sources: Social media APIs, public databases",
        "commands": ["/insta", "/instagram"],
        "example": "username",
        "validation": r"^[a-zA-Z0-9_.]{1,30}$",
        "cost": 1
    },
    "pak": {
        "name": "International Intelligence",
        "description": "Pakistan number comprehensive analysis\n• Input: Pakistan mobile number (+92 format)\n• Returns: Complete subscriber information, location, network details\n• Sources: International telecom databases",
        "commands": ["/pak", "/pk"],
        "example": "+923001234567",
        "validation": r"^\+92\d{10}$",
        "cost": 3
    }
}

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
            logger.info(f"Detected file generation message: {text[:50]}...")
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
    def format_result(content: str, search_type: str, query: str, source: str) -> str:
        """Format search result professionally"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        name = cmd.get("name", "Search Result")
        
        header = f"**{name}**\n"
        header += f"Query: `{query}`\n"
        header += f"Source: {source}\n"
        header += "─" * 40 + "\n\n"
        
        if not content or len(content.strip()) < 30:
            content = "No valid information found in the response.\nThe data might be unavailable or the query requires premium access."
        
        footer = "\n" + "─" * 40 + "\n"
        footer += "Powered by DarkBoxes Intelligence System\n"
        footer += "Developed by @darkboxesAdmin\n"
        footer += "Confidential - For authorized use only"
        
        return header + content + footer

# ================== SEARCH ENGINE ==================

class SearchEngine:
    def __init__(self, db_manager, user_manager):
        self.db = db_manager
        self.user_manager = user_manager
        self.active_searches = {}
        self.waiting_for_files = {}
    
    async def perform_search(self, search_type: str, query: str, user_id: int) -> Dict:
        """Perform cascading search"""
        logger.info(f"Starting {search_type} search: {query} (User: {user_id})")
        
        # Sort groups by priority
        groups = sorted(DESTINATION_GROUPS, key=lambda x: x["priority"])
        
        for group in groups:
            if not group.get("entity"):
                logger.warning(f"Group {group['name']} not resolved")
                continue
            
            cmd = SEARCH_COMMANDS[search_type]["commands"][0]
            message = f"{cmd} {query}"
            
            logger.info(f"Trying {group['name']}: {message}")
            
            try:
                sent_msg = await user_client.send_message(group["entity"], message)
                
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
                    "file_wait_start": None
                }
                
                try:
                    result = await asyncio.wait_for(future, timeout=group["timeout"])
                    
                    if result["success"]:
                        logger.info(f"Success from {group['name']}")
                        return result
                    else:
                        logger.info(f"No result from {group['name']}, trying next...")
                        continue
                        
                except asyncio.TimeoutError:
                    logger.info(f"Timeout from {group['name']}")
                    continue
                    
            except Exception as e:
                logger.error(f"Error sending to {group['name']}: {e}")
                continue
        
        await self._notify_admin(user_id, search_type, query)
        return {
            "success": False,
            "error": f"No information found for `{query}`\n\n**Premium Notice:** Your query has been escalated to our premium database.\nAdministrator will review and respond within 24 hours.\n\nFor instant access, upgrade to Premium Plan."
        }
    
    async def handle_incoming_message(self, event):
        """Handle incoming messages that might be search results"""
        try:
            message = event.message
            
            if message.reply_to:
                reply_to_id = message.reply_to.reply_to_msg_id
                
                for search_id, search_info in list(self.active_searches.items()):
                    if reply_to_id == search_info["message_id"]:
                        await self._process_search_response(search_id, search_info, message)
                        return
            
            for search_id, search_info in list(self.active_searches.items()):
                chat_match = False
                try:
                    if hasattr(search_info["group"]["entity"], 'id'):
                        chat_match = event.chat_id == search_info["group"]["entity"].id
                    else:
                        chat_match = str(event.chat_id) == str(search_info.get("chat_id", ""))
                except:
                    pass
                
                if chat_match:
                    file_check = await self._check_and_process_file(message, search_info)
                    if file_check is not None:
                        logger.info(f"Found file in {search_info['group']['name']}")
                        await self._process_search_response(search_id, search_info, message)
                        return
                    
        except Exception as e:
            logger.error(f"Error handling incoming message: {e}")
    
    async def _check_and_process_file(self, message, search_info: Dict) -> Optional[Dict]:
        """Check if message has file and process it"""
        if message.media and hasattr(message.media, 'document'):
            logger.info(f"Found document media in message")
            return await self._process_file(message, search_info)
        
        if hasattr(message, 'file') and message.file:
            logger.info(f"Found file attribute in message")
            return await self._process_file(message, search_info)
        
        if message.document:
            logger.info(f"Found document in message")
            return await self._process_file(message, search_info)
        
        return None
    
    async def _process_search_response(self, search_id: str, search_info: Dict, message):
        """Process a search response message"""
        try:
            text = message.text or message.raw_text or ""
            logger.info(f"Processing message in {search_info['group']['name']}: {text[:100]}...")
            
            file_result = await self._check_and_process_file(message, search_info)
            if file_result is not None:
                logger.info(f"Processing file from message")
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result(file_result)
                    del self.active_searches[search_id]
                return
            
            if TextProcessor.is_file_generated_message(text):
                logger.info(f"File generation message detected in {search_info['group']['name']}")
                
                if message.reply_to:
                    logger.info(f"File message is a reply, checking replied message...")
                    try:
                        replied_msg = await message.get_reply_message()
                        if replied_msg:
                            replied_file_result = await self._check_and_process_file(replied_msg, search_info)
                            if replied_file_result:
                                logger.info(f"Found file in replied message")
                                if search_id in self.active_searches:
                                    future = self.active_searches[search_id]["future"]
                                    if not future.done():
                                        future.set_result(replied_file_result)
                                    del self.active_searches[search_id]
                                return
                    except Exception as e:
                        logger.error(f"Error checking replied message: {e}")
                
                search_info["expecting_file"] = True
                search_info["file_wait_start"] = time.time()
                logger.info(f"Waiting for file to arrive...")
                return
            
            if TextProcessor.is_processing_message(text):
                logger.info(f"Processing message, waiting...")
                return
            
            if TextProcessor.is_no_info_message(text):
                logger.info(f"No-info message")
                result = {"success": False}
            elif text and len(text.strip()) > 10:
                logger.info(f"Processing text response")
                result = await self._process_text(text, search_info)
            else:
                logger.info(f"Empty or short message, ignoring")
                return
            
            if search_id in self.active_searches:
                future = self.active_searches[search_id]["future"]
                if not future.done():
                    future.set_result(result)
                del self.active_searches[search_id]
                
        except Exception as e:
            logger.error(f"Error processing search response: {e}")
    
    async def _process_file(self, message, search_info: Dict) -> Dict:
        """Process file message"""
        try:
            if hasattr(message.file, 'size') and message.file.size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
                logger.warning(f"File too large: {message.file.size} bytes")
                return {"success": False}
            
            logger.info(f"Downloading file from {search_info['group']['name']}")
            file_bytes = await message.download_media(bytes)
            
            if not file_bytes:
                logger.error("Failed to download file")
                return {"success": False}
            
            content = None
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for encoding in encodings:
                try:
                    content = file_bytes.decode(encoding)
                    logger.info(f"Decoded with {encoding}")
                    break
                except UnicodeDecodeError:
                    continue
            
            if not content:
                logger.error("Could not decode file with any encoding")
                return {"success": False}
            
            cleaned_content = TextProcessor.clean_content(content, search_info["search_type"])
            
            if len(cleaned_content.strip()) < 30:
                logger.warning(f"Cleaned content too short: {len(cleaned_content)} chars")
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
            
            formatted_result = TextProcessor.format_result(
                cleaned_content,
                search_info["search_type"],
                search_info["query"],
                search_info["group"]["name"]
            )
            
            logger.info(f"Processed file with {len(cleaned_content)} characters")
            return {
                "success": True,
                "result": formatted_result,
                "has_file": True
            }
            
        except Exception as e:
            logger.error(f"Error processing file: {e}")
            return {"success": False}
    
    async def _process_text(self, text: str, search_info: Dict) -> Dict:
        """Process text message"""
        cleaned = TextProcessor.clean_content(text, search_info["search_type"])
        
        if len(cleaned) < 20:
            return {"success": False}
        
        formatted = TextProcessor.format_result(
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
                f"**Failed Search Alert**\n\n"
                f"User: {first_name} (@{username})\n"
                f"ID: `{user_id}`\n"
                f"Type: {search_type}\n"
                f"Query: `{query}`\n"
                f"Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
                f"Use `/reply {user_id} [message]` to send result"
            )
            
            await bot_client.send_message(config.ADMIN_USER_ID, admin_msg, parse_mode="md")
            logger.info(f"Notified admin about {search_type}={query}")
            
        except Exception as e:
            logger.error(f"Error notifying admin: {e}")

# ================== CLEANUP TASK ==================

async def cleanup_expired_searches():
    """Clean up expired searches and check for files"""
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
                        logger.info(f"File wait timeout in {search_info['group']['name']}")
                
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
                    logger.info(f"Cleaned expired search: {search_id}")
            
            if expired:
                logger.info(f"Cleaned {len(expired)} expired searches")
                
        except Exception as e:
            logger.error(f"Error in cleanup: {e}")

# ================== DATABASE MANAGER ==================

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
    
    async def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            logger.info("Connecting to MongoDB...")
            self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            self.client.server_info()
            self.db = self.client[config.MONGODB_DBNAME]
            logger.info("MongoDB connected")
            return True
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
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
            
            logger.info(f"Created user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return False
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self.db.users.find_one, {"user_id": user_id}
            )
        except Exception as e:
            logger.error(f"Error getting user: {e}")
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
            logger.error(f"Error updating searches: {e}")
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
            logger.error(f"Error adding subscription: {e}")
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
            logger.error(f"Error adding referral credit: {e}")
            return False

# ================== KEYBOARD BUILDER ==================

class KeyboardBuilder:
    @staticmethod
    def main_menu(is_admin: bool = False) -> List[List[Button]]:
        """Build professional main menu"""
        buttons = []
        
        # Search categories
        search_types = list(SEARCH_COMMANDS.keys())
        
        row1 = []
        for i in range(min(4, len(search_types))):
            name = SEARCH_COMMANDS[search_types[i]]["name"].split()[0]
            row1.append(Button.inline(name, f"search_{search_types[i]}"))
        if row1:
            buttons.append(row1)
        
        row2 = []
        for i in range(4, min(8, len(search_types))):
            name = SEARCH_COMMANDS[search_types[i]]["name"].split()[0]
            row2.append(Button.inline(name, f"search_{search_types[i]}"))
        if row2:
            buttons.append(row2)
        
        # User options
        buttons.append([
            Button.inline("Profile", "profile"),
            Button.inline("Premium Plans", "premium")
        ])
        buttons.append([
            Button.inline("Refer & Earn", "referrals"),
            Button.inline("Support", "support")
        ])
        
        if is_admin:
            buttons.append([
                Button.inline("Admin Panel", "admin"),
                Button.inline("Broadcast", "broadcast")
            ])
        
        return buttons
    
    @staticmethod
    def search_menu(search_type: str) -> List[List[Button]]:
        """Build search type specific menu"""
        cmd = SEARCH_COMMANDS[search_type]
        return [
            [Button.inline(f"{cmd['name']}", f"info_{search_type}")],
            [Button.inline("Cancel", "main_menu")]
        ]
    
    @staticmethod
    def subscription_plans() -> List[List[Button]]:
        """Build subscription plans menu"""
        buttons = []
        
        for plan_id, plan in SUBSCRIPTION_PLANS.items():
            if plan["recommended"]:
                label = f"⭐ {plan['name']} - ₹{plan['price']}"
            else:
                label = f"{plan['name']} - ₹{plan['price']}"
            buttons.append([Button.inline(label, f"buy_{plan_id}")])
        
        buttons.append([Button.inline("Back to Menu", "main_menu")])
        return buttons
    
    @staticmethod
    def cancel_button() -> List[List[Button]]:
        """Simple cancel button"""
        return [[Button.inline("Cancel", "main_menu")]]
    
    @staticmethod
    def payment_confirmation(plan_id: str) -> List[List[Button]]:
        """Payment confirmation buttons"""
        return [
            [Button.inline("Payment Done", f"confirm_{plan_id}")],
            [Button.inline("Cancel", "premium")]
        ]
    
    @staticmethod
    def admin_menu() -> List[List[Button]]:
        """Admin menu"""
        return [
            [Button.inline("User Stats", "admin_stats")],
            [Button.inline("Broadcast Message", "admin_broadcast")],
            [Button.inline("Back to Menu", "main_menu")]
        ]

# ================== TELEGRAM CLIENTS ==================

bot_client = TelegramClient(config.BOT_SESSION_FILE, config.BOT_API_ID, config.BOT_API_HASH)
user_client = (
    TelegramClient(config.USER_SESSION_FILE, config.USER_API_ID, config.USER_API_HASH)
    if USE_USER_ACCOUNT
    else bot_client
)

# ================== GLOBAL MANAGERS ==================

db_manager = DatabaseManager()
search_engine = None
user_states = {}

# ================== EVENT HANDLERS ==================

@bot_client.on(events.NewMessage(pattern=r'/start(?: (.+))?'))
async def start_handler(event):
    """Handle /start command with referral"""
    try:
        user = await event.get_sender()
        user_id = user.id
        referral_code = event.pattern_match.group(1)
        
        # Create/get user
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
                    await bot_client.send_message(
                        referrer_id,
                        f"**Referral Success**\n\n"
                        f"User {user.first_name} (@{user.username}) joined using your referral code.\n"
                        f"You have received {config.REFERRAL_REWARD} search credits."
                    )
        
        is_admin = user_id == config.ADMIN_USER_ID
        user_info = await db_manager.get_user(user_id)
        
        # Welcome message
        welcome = (
            f"**DarkBoxes Intelligence System**\n\n"
            f"Welcome, {user.first_name}.\n\n"
            f"**Your Account Overview:**\n"
            f"• Available Credits: {user_info.get('searches_remaining', 0)}\n"
            f"• Total Searches: {user_info.get('total_searches', 0)}\n"
            f"• Referral Code: `{user_info.get('referral_code', 'N/A')}`\n"
            f"• Referrals: {user_info.get('referrals', 0)}\n\n"
            f"**Premium Features:**\n"
            f"• Government Database Access\n"
            f"• Celebrity Information\n"
            f"• International Data Sources\n"
            f"• Priority Processing\n\n"
            f"Select a service below:"
        )
        
        await event.respond(welcome, buttons=KeyboardBuilder.main_menu(is_admin), parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in start_handler: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)$'))
async def search_callback(event):
    """Handle search type selection"""
    try:
        user_id = event.sender_id
        search_type = event.data.decode().split('_', 1)[1]
        
        if search_type not in SEARCH_COMMANDS:
            await event.answer("Invalid selection", alert=True)
            return
        
        user_doc = await db_manager.get_user(user_id)
        if not user_doc:
            await event.answer("User not found", alert=True)
            return
        
        # Check if user can search
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
                "**Access Denied**\n\n"
                "You have no search credits remaining.\n\n"
                "**Premium Access Required:**\n"
                "• Basic Plan: ₹100 for 5 searches\n"
                "• Standard Plan: ₹200 for 10 searches\n"
                "• Premium Plan: ₹500 for unlimited searches (7 days)\n"
                "• Enterprise Plan: ₹800 for unlimited searches (30 days)\n\n"
                "Select 'Premium Plans' to upgrade or contact @darkboxesAdmin for assistance.",
                buttons=KeyboardBuilder.subscription_plans()
            )
            return
        
        cmd = SEARCH_COMMANDS[search_type]
        
        await event.edit(
            f"**{cmd['name']}**\n\n"
            f"{cmd['description']}\n\n"
            f"**Cost:** {cmd['cost']} credit{'s' if cmd['cost'] > 1 else ''}\n"
            f"**Example:** `{cmd['example']}`\n\n"
            f"Enter your query below:",
            buttons=KeyboardBuilder.cancel_button(),
            parse_mode="md"
        )
        
        user_states[user_id] = {"action": "search", "type": search_type}
        
    except Exception as e:
        logger.error(f"Error in search_callback: {e}")
        await event.answer("Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^main_menu$'))
async def main_menu_callback(event):
    """Return to main menu"""
    try:
        user_id = event.sender_id
        user_states.pop(user_id, None)
        
        user_doc = await db_manager.get_user(user_id)
        is_admin = user_id == config.ADMIN_USER_ID
        
        message = (
            f"**Main Control Panel**\n\n"
            f"**Account Status:**\n"
            f"• Credits: {user_doc.get('searches_remaining', 0)}\n"
            f"• Total Searches: {user_doc.get('total_searches', 0)}\n"
            f"• Subscription: {user_doc.get('subscription', 'None')}\n\n"
            f"Select a service:"
        )
        
        await event.edit(message, buttons=KeyboardBuilder.main_menu(is_admin), parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in main_menu_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern='^premium$'))
async def premium_callback(event):
    """Show premium plans"""
    try:
        plans_text = "**Premium Subscription Plans**\n\n"
        
        for plan_id, plan in SUBSCRIPTION_PLANS.items():
            plans_text += f"**{plan['name']}** - ₹{plan['price']}\n"
            plans_text += f"• Searches: {plan['searches']}\n"
            plans_text += f"• Validity: {plan['validity']}\n"
            for feature in plan['features']:
                plans_text += f"• {feature}\n"
            if plan['recommended']:
                plans_text += "• **RECOMMENDED**\n"
            plans_text += "\n"
        
        plans_text += "**Payment Instructions:**\n"
        plans_text += f"1. Send ₹[Plan Price] to UPI: `{config.UPI_ID}`\n"
        plans_text += "2. Take screenshot of payment\n"
        plans_text += "3. Click 'Payment Done' for your plan\n"
        plans_text += "4. Send screenshot to @darkboxesAdmin\n\n"
        plans_text += "Activation within 5 minutes of payment verification."
        
        await event.edit(plans_text, buttons=KeyboardBuilder.subscription_plans(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in premium_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^buy_(.+)$'))
async def buy_plan_callback(event):
    """Handle plan purchase"""
    try:
        plan_id = event.data.decode().split('_', 1)[1]
        
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.answer("Invalid plan", alert=True)
            return
        
        plan = SUBSCRIPTION_PLANS[plan_id]
        
        payment_msg = (
            f"**Purchase Confirmation: {plan['name']}**\n\n"
            f"**Price:** ₹{plan['price']}\n"
            f"**UPI ID:** `{config.UPI_ID}`\n"
            f"**Plan Details:**\n"
        )
        
        for feature in plan['features']:
            payment_msg += f"• {feature}\n"
        
        payment_msg += "\n**Payment Process:**\n"
        payment_msg += "1. Send exact amount to above UPI\n"
        payment_msg += "2. Take screenshot of successful payment\n"
        payment_msg += "3. Click 'Payment Done' below\n"
        payment_msg += "4. Send screenshot to @darkboxesAdmin for verification\n\n"
        payment_msg += "Your subscription will be activated within 5 minutes of verification."
        
        await event.edit(payment_msg, buttons=KeyboardBuilder.payment_confirmation(plan_id), parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in buy_plan_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^confirm_(.+)$'))
async def confirm_payment_callback(event):
    """Handle payment confirmation"""
    try:
        plan_id = event.data.decode().split('_', 1)[1]
        user_id = event.sender_id
        
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.answer("Invalid plan", alert=True)
            return
        
        plan = SUBSCRIPTION_PLANS[plan_id]
        
        # Notify admin
        user = await db_manager.get_user(user_id)
        admin_msg = (
            f"**Payment Confirmation Request**\n\n"
            f"User: {user['first_name']} (@{user['username']})\n"
            f"ID: `{user_id}`\n"
            f"Plan: {plan['name']}\n"
            f"Amount: ₹{plan['price']}\n"
            f"Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"Use `/activate {user_id} {plan_id}` to activate subscription."
        )
        
        await bot_client.send_message(config.ADMIN_USER_ID, admin_msg, parse_mode="md")
        
        await event.edit(
            f"**Payment Confirmation Received**\n\n"
            f"Thank you for your payment confirmation.\n"
            f"Plan: {plan['name']}\n"
            f"Amount: ₹{plan['price']}\n\n"
            f"Please send payment screenshot to @darkboxesAdmin for verification.\n"
            f"Your subscription will be activated within 5 minutes of verification.",
            buttons=KeyboardBuilder.cancel_button(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"Error in confirm_payment_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern='^referrals$'))
async def referrals_callback(event):
    """Show referrals information"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        referrals_text = (
            f"**Refer & Earn Program**\n\n"
            f"**Your Referral Stats:**\n"
            f"• Referral Code: `{user_doc.get('referral_code', 'N/A')}`\n"
            f"• Total Referrals: {user_doc.get('referrals', 0)}\n"
            f"• Earned Credits: {user_doc.get('referral_credits', 0)}\n\n"
            f"**How It Works:**\n"
            f"1. Share your referral link:\n"
            f"`https://t.me/{bot_info.username}?start={user_id}`\n\n"
            f"2. When someone joins using your link:\n"
            f"• They get {config.NEW_USER_CREDITS} free credits\n"
            f"• You get {config.REFERRAL_REWARD} search credits\n\n"
            f"3. No limits - refer unlimited users\n\n"
            f"**Benefits:**\n"
            f"• Free credits for both parties\n"
            f"• Priority support for top referrers\n"
            f"• Special discounts for active referrers"
        )
        
        await event.edit(referrals_text, buttons=KeyboardBuilder.cancel_button(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in referrals_callback: {e}")

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
            f"**User Profile**\n\n"
            f"**Basic Information:**\n"
            f"• Name: {user_doc.get('first_name', 'N/A')}\n"
            f"• Username: @{user_doc.get('username', 'N/A')}\n"
            f"• User ID: `{user_id}`\n"
            f"• Member Since: {user_doc.get('joined_at', 'N/A')[:10]}\n\n"
            f"**Account Status:**\n"
            f"• Available Credits: {user_doc.get('searches_remaining', 0)}\n"
            f"• Total Searches: {user_doc.get('total_searches', 0)}\n"
            f"• Active Subscription: {subscription_status}\n"
            f"• Wallet Balance: ₹{user_doc.get('wallet_balance', 0)}\n\n"
            f"**Referral Information:**\n"
            f"• Referral Code: `{user_doc.get('referral_code', 'N/A')}`\n"
            f"• Total Referrals: {user_doc.get('referrals', 0)}\n"
            f"• Earned Credits: {user_doc.get('referral_credits', 0)}\n\n"
            f"**Last Activity:** {user_doc.get('last_seen', 'N/A')[:19]}"
        )
        
        await event.edit(profile_text, buttons=KeyboardBuilder.cancel_button(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in profile_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern='^admin$'))
async def admin_callback(event):
    """Admin panel"""
    try:
        user_id = event.sender_id
        if user_id != config.ADMIN_USER_ID:
            await event.answer("Access denied", alert=True)
            return
        
        admin_text = (
            f"**Administration Panel**\n\n"
            f"**Bot Statistics:**\n"
            f"• Total Users: [Loading...]\n"
            f"• Active Today: [Loading...]\n"
            f"• Total Searches: [Loading...]\n"
            f"• Revenue: [Loading...]\n\n"
            f"**Quick Actions:**\n"
            f"1. View user statistics\n"
            f"2. Broadcast message\n"
            f"3. Manage subscriptions\n"
            f"4. Generate reports"
        )
        
        await event.edit(admin_text, buttons=KeyboardBuilder.admin_menu(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in admin_callback: {e}")

@bot_client.on(events.NewMessage(pattern=r'/activate (\d+) (\w+)'))
async def activate_subscription_handler(event):
    """Admin command to activate subscription"""
    try:
        if event.sender_id != config.ADMIN_USER_ID:
            return
        
        user_id = int(event.pattern_match.group(1))
        plan_id = event.pattern_match.group(2)
        
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.respond("Invalid plan ID")
            return
        
        plan = SUBSCRIPTION_PLANS[plan_id]
        days = 7 if plan_id in ["basic", "standard", "premium"] else 30
        
        success = await db_manager.add_subscription(user_id, plan_id, days)
        
        if success:
            user_doc = await db_manager.get_user(user_id)
            await bot_client.send_message(
                user_id,
                f"**Subscription Activated**\n\n"
                f"Your {plan['name']} has been activated.\n"
                f"• Plan: {plan['name']}\n"
                f"• Validity: {plan['validity']}\n"
                f"• Features: {', '.join(plan['features'][:3])}\n\n"
                f"You now have unlimited searches until {(datetime.now(timezone.utc) + timedelta(days=days)).strftime('%Y-%m-%d')}.\n\n"
                f"For support: @darkboxesAdmin"
            )
            
            await event.respond(f"✅ Subscription activated for user {user_id}")
        else:
            await event.respond(f"❌ Failed to activate subscription")
        
    except Exception as e:
        logger.error(f"Error in activate_subscription_handler: {e}")

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
        
        await event.respond(f"Starting broadcast to {len(users)} users...")
        
        for user in users:
            try:
                await bot_client.send_message(
                    user["user_id"],
                    f"**Announcement**\n\n{message}\n\n— DarkBoxes Administration"
                )
                sent += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                failed += 1
        
        await event.respond(f"✅ Broadcast complete\nSent: {sent}\nFailed: {failed}")
        
    except Exception as e:
        logger.error(f"Error in broadcast_handler: {e}")

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
            f"**Administrator Response**\n\n{message}\n\n— DarkBoxes Support Team"
        )
        
        await event.respond(f"✅ Reply sent to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in admin_reply_handler: {e}")

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def query_handler(event):
    """Handle search queries"""
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
            await event.respond("Please enter a valid query.")
            return
        
        # Validate query
        cmd = SEARCH_COMMANDS[search_type]
        validation = cmd.get("validation")
        if validation and not re.match(validation, query):
            await event.respond(f"Invalid format. Example: `{cmd['example']}`")
            return
        
        # Show searching status
        status = await event.respond(
            f"**Search Initialized**\n\n"
            f"Query: `{query}`\n"
            f"Service: {cmd['name']}\n"
            f"Estimated Time: 15-30 seconds\n\n"
            f"Accessing premium databases...",
            parse_mode="md"
        )
        
        # Check if user can search
        user_doc = await db_manager.get_user(user_id)
        can_search = False
        
        if user_doc.get('subscription') and user_doc.get('subscription_expiry'):
            expiry_date = datetime.fromisoformat(user_doc['subscription_expiry'])
            if expiry_date > datetime.now(timezone.utc):
                can_search = True
        
        if not can_search and user_doc.get('searches_remaining', 0) <= 0:
            await status.delete()
            await event.respond(
                "**Insufficient Credits**\n\n"
                "You have no search credits remaining.\n\n"
                "**Upgrade Options:**\n"
                "• Basic Plan: ₹100 (5 searches)\n"
                "• Premium Plan: ₹500 (unlimited/7 days)\n"
                "• Enterprise Plan: ₹800 (unlimited/30 days)\n\n"
                "Select 'Premium Plans' from menu or contact @darkboxesAdmin.",
                buttons=KeyboardBuilder.subscription_plans()
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
        logger.error(f"Error in query_handler: {e}")
        await event.respond("An error occurred during processing.")

@user_client.on(events.NewMessage())
async def handle_all_messages(event):
    """Handle all incoming messages for search responses"""
    try:
        await search_engine.handle_incoming_message(event)
    except Exception as e:
        pass

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
        logger.info(f"Web server running on port {config.PORT}")
    except Exception as e:
        logger.error(f"Web server failed: {e}")

# ================== MAIN ==================

async def main():
    """Main function"""
    global search_engine, bot_info
    
    try:
        logger.info("Starting DarkBoxes Intelligence Bot...")
        
        # Start bot
        await bot_client.start(bot_token=config.BOT_TOKEN)
        bot_info = await bot_client.get_me()
        logger.info(f"Bot initialized: @{bot_info.username}")
        
        # Start user client
        if USE_USER_ACCOUNT:
            await user_client.connect()
            if not await user_client.is_user_authorized():
                logger.error("User client not authorized")
                return
            logger.info("User client authenticated")
        
        # Connect to DB
        if not await db_manager.connect():
            logger.error("Database connection failed")
            return
        
        # Initialize search engine
        search_engine = SearchEngine(db_manager, db_manager)
        
        # Resolve groups
        logger.info("Initializing database connections...")
        for group in DESTINATION_GROUPS:
            try:
                group["entity"] = await user_client.get_entity(group["identifier"])
                logger.info(f"Connected: {group['name']}")
            except Exception as e:
                logger.warning(f"Connection failed: {group['name']}: {e}")
        
        # Start background tasks
        asyncio.create_task(cleanup_expired_searches())
        asyncio.create_task(start_web_server())
        
        logger.info("=" * 60)
        logger.info("SYSTEM READY: DarkBoxes Intelligence Bot")
        logger.info("=" * 60)
        
        await asyncio.Event().wait()
        
    except KeyboardInterrupt:
        logger.info("System shutdown initiated...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        # Clean shutdown
        try:
            if bot_client.is_connected():
                await bot_client.disconnect()
            if USE_USER_ACCOUNT and user_client.is_connected():
                await user_client.disconnect()
            if db_manager.client:
                db_manager.client.close()
        except:
            pass

if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Startup failed: {e}")
