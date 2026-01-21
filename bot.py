"""
Premium Information Bot - Advanced Edition
Enhanced file waiting system with caption fix
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
    print(f"❌ Missing required dependency: {e}")
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
    GROUP_TIMEOUT: int = int(os.getenv("GROUP_TIMEOUT", "45"))  # Increased for file waiting
    FETCH_WAIT_TIME: int = int(os.getenv("FETCH_WAIT_TIME", "3"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
    
    # Credits and rewards
    NEW_USER_CREDITS: int = int(os.getenv("NEW_USER_CREDITS", "3"))
    REFERRAL_REWARD: int = int(os.getenv("REFERRAL_REWARD", "2"))

config = BotConfig()

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
            errors.append(f"❌ {name} is not properly configured")
    
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
        "name": "Main Group",
        "identifier": -1003596998816,
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 1
    },
    {
        "name": "Backup Group 2",
        "identifier": "darkboxesv3",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 2
    },
    {
        "name": "Backup Group 3",
        "identifier": "nex_chats",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 3
    }
]

# ================== SEARCH COMMANDS ==================

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Number",
        "description": "Get detailed information from phone number",
        "commands": ["/num", "/phone", "/mobile"],
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "emoji": "📱"
    },
    "family": {
        "name": "👨‍👩‍👧‍👦 Family Info",
        "description": "Get family member details from phone",
        "commands": ["/familyinfo", "/family"],
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "emoji": "👨‍👩‍👧‍👦"
    },
    "aadhar": {
        "name": "🆔 Aadhar Card",
        "description": "Get information from Aadhar number",
        "commands": ["/aadhar", "/adh", "/aadhaar"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "emoji": "🆔"
    },
    "vehicle": {
        "name": "🚗 Vehicle Info",
        "description": "Get vehicle and owner details",
        "commands": ["/vehicle", "/vnum", "/car"],
        "example": "UP16BH1234",
        "validation": r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$",
        "emoji": "🚗"
    },
    "upi": {
        "name": "💳 UPI ID",
        "description": "Get UPI account information",
        "commands": ["/upiinfo", "/upi"],
        "example": "username@paytm",
        "validation": r"^[\w\.-]+@[\w\.-]+$",
        "emoji": "💳"
    },
    "email": {
        "name": "📧 Email",
        "description": "Search email address details",
        "commands": ["/email", "/mail"],
        "example": "user@example.com",
        "validation": r"^[\w\.-]+@[\w\.-]+\.\w+$",
        "emoji": "📧"
    },
    "telegram": {
        "name": "📲 Telegram Phone",
        "description": "Get phone from Telegram username",
        "commands": ["/tg", "/telegram"],
        "example": "@username",
        "validation": r"^@?\w{5,32}$",
        "daily_limit": 1,
        "emoji": "📲"
    },
    "imei": {
        "name": "📱 IMEI",
        "description": "Get device info from IMEI",
        "commands": ["/imei", "/device"],
        "example": "123456789012345",
        "validation": r"^\d{15}$",
        "emoji": "📱"
    },
    "gst": {
        "name": "🏢 GST",
        "description": "Get business info from GST number",
        "commands": ["/gst", "/gstin"],
        "example": "29ABCDE1234F1Z5",
        "validation": r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$",
        "emoji": "🏢"
    },
    "insta": {
        "name": "📷 Instagram",
        "description": "Search Instagram profile details",
        "commands": ["/insta", "/instagram"],
        "example": "username",
        "validation": r"^[a-zA-Z0-9_.]{1,30}$",
        "emoji": "📷"
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
            'gathering data', 'working on it', '⏳', '🔍', 'searching for',
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
            '✅ file generated', '📂 report_', '.txt', 'auto-delete',
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
        
        # Remove URLs and promotional content
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
            r'✅ file generated.*',
            r'📂 report_.*\.txt',
            r'⚡.*@\w+',
            r'download.*file',
            r'click.*download',
            r'designed & powered.*'
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        # Clean whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)
        
        # Add emojis based on content type
        if search_type == "family":
            content = TextProcessor._add_family_emojis(content)
        elif search_type == "phone":
            content = TextProcessor._add_phone_emojis(content)
        elif search_type == "aadhar":
            content = TextProcessor._add_aadhar_emojis(content)
        elif search_type == "vehicle":
            content = TextProcessor._add_vehicle_emojis(content)
        
        return content.strip()
    
    @staticmethod
    def _add_family_emojis(content: str) -> str:
        """Add emojis to family info"""
        lines = content.split('\n')
        result = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if any(word in line.lower() for word in ['father', 'dad', 'papa']):
                result.append(f"👨 {line}")
            elif any(word in line.lower() for word in ['mother', 'mom', 'mummy']):
                result.append(f"👩 {line}")
            elif any(word in line.lower() for word in ['brother', 'bhai']):
                result.append(f"👦 {line}")
            elif any(word in line.lower() for word in ['sister', 'behen']):
                result.append(f"👧 {line}")
            elif any(word in line.lower() for word in ['wife', 'spouse']):
                result.append(f"👰 {line}")
            elif any(word in line.lower() for word in ['husband']):
                result.append(f"🤵 {line}")
            elif any(word in line.lower() for word in ['son', 'beta']):
                result.append(f"👶 {line}")
            elif any(word in line.lower() for word in ['daughter', 'beti']):
                result.append(f"👧 {line}")
            elif 'name' in line.lower():
                result.append(f"👤 {line}")
            elif 'age' in line.lower():
                result.append(f"🎂 {line}")
            elif 'address' in line.lower():
                result.append(f"🏠 {line}")
            elif 'relation' in line.lower():
                result.append(f"👨‍👩‍👧‍👦 {line}")
            elif any(marker in line for marker in ['•', '-', '*', '→', '●', '|', ':']):
                result.append(line)
            elif len(line) > 10:
                result.append(f"📝 {line}")
        
        return '\n'.join(result)
    
    @staticmethod
    def _add_phone_emojis(content: str) -> str:
        """Add emojis to phone info"""
        lines = content.split('\n')
        result = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if any(word in line.lower() for word in ['name', 'full name']):
                result.append(f"👤 {line}")
            elif 'phone' in line.lower() or 'mobile' in line.lower() or 'number' in line.lower():
                result.append(f"📱 {line}")
            elif 'address' in line.lower():
                result.append(f"🏠 {line}")
            elif 'email' in line.lower():
                result.append(f"📧 {line}")
            elif 'operator' in line.lower() or 'carrier' in line.lower():
                result.append(f"📶 {line}")
            elif 'state' in line.lower():
                result.append(f"🗺️ {line}")
            elif 'city' in line.lower():
                result.append(f"🏙️ {line}")
            elif 'pincode' in line.lower() or 'zip' in line.lower():
                result.append(f"📮 {line}")
            elif any(marker in line for marker in ['•', '-', '*', '→', '●', '|', ':']):
                result.append(line)
            elif len(line) > 10:
                result.append(f"📝 {line}")
        
        return '\n'.join(result)
    
    @staticmethod
    def format_result(content: str, search_type: str, query: str, source: str) -> str:
        """Format search result nicely"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        emoji = cmd.get("emoji", "✅")
        name = cmd.get("name", "Search Result")
        
        header = f"{emoji} **{name}**\n"
        header += f"🔍 Query: `{query}`\n"
        header += f"📊 Source: {source}\n"
        header += "─" * 35 + "\n\n"
        
        # Add content
        if not content or len(content.strip()) < 30:
            content = "❌ No valid information found in the response.\nThe file might be empty or contain only promotional content."
        
        footer = "\n" + "─" * 35 + "\n"
        footer += "💎 **Premium Info Bot**\n"
        footer += "⚡ Fast & Accurate Results\n"
        footer += "🔗 @darkboxesAdmin"
        
        return header + content + footer

# ================== SEARCH ENGINE ==================

   class SearchEngine:
    def __init__(self, db_manager, user_manager):
        self.db = db_manager
        self.user_manager = user_manager
        self.active_searches = {}  # {search_id: {user_id, future, start_time, group, message_id}}
        self.message_to_search = {}  # {message_id: search_id} for quick lookup
    
    async def perform_search(self, search_type: str, query: str, user_id: int) -> Dict:
        """Perform cascading search"""
        logger.info(f"🔍 Starting {search_type} search: {query} (User: {user_id})")
        
        # Sort groups by priority
        groups = sorted(DESTINATION_GROUPS, key=lambda x: x["priority"])
        
        for group in groups:
            if not group.get("entity"):
                logger.warning(f"⚠️ Group {group['name']} not resolved")
                continue
            
            # Get command for this search type
            cmd = SEARCH_COMMANDS[search_type]["commands"][0]
            message_text = f"{cmd} {query}"
            
            logger.info(f"📤 Trying {group['name']}: {message_text}")
            
            try:
                # Send message
                sent_msg = await user_client.send_message(group["entity"], message_text)
                logger.info(f"✅ Sent to {group['name']}, message ID: {sent_msg.id}")
                
                # Create search tracking
                search_id = f"{user_id}_{int(time.time())}_{group['identifier']}"
                future = asyncio.get_running_loop().create_future()
                
                # Store search info with chat details
                chat_id = sent_msg.peer_id.channel_id if hasattr(sent_msg.peer_id, 'channel_id') else None
                if not chat_id:
                    # Try to get chat_id from the entity
                    try:
                        chat_id = group["entity"].id
                    except:
                        chat_id = str(group["entity"])
                
                self.active_searches[search_id] = {
                    "user_id": user_id,
                    "future": future,
                    "start_time": time.time(),
                    "group": group,
                    "message_id": sent_msg.id,
                    "search_type": search_type,
                    "query": query,
                    "chat_id": chat_id,
                    "expecting_file": False,
                    "file_wait_start": None,
                    "last_activity": time.time()
                }
                
                # Map message ID to search ID for quick lookup
                message_key = f"{chat_id}_{sent_msg.id}"
                self.message_to_search[message_key] = search_id
                logger.info(f"📝 Mapped message {message_key} to search {search_id}")
                
                # Wait for response
                try:
                    logger.info(f"⏳ Waiting for response from {group['name']} (timeout: {group['timeout']}s)")
                    result = await asyncio.wait_for(future, timeout=group["timeout"])
                    
                    if result["success"]:
                        logger.info(f"✅ Success from {group['name']}")
                        return result
                    else:
                        logger.info(f"⚠️ No result from {group['name']}, trying next...")
                        # Clean up mapping
                        if message_key in self.message_to_search:
                            del self.message_to_search[message_key]
                        continue
                        
                except asyncio.TimeoutError:
                    logger.info(f"⏱️ Timeout from {group['name']}")
                    # Clean up mapping
                    if message_key in self.message_to_search:
                        del self.message_to_search[message_key]
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Error sending to {group['name']}: {e}")
                continue
        
        # All groups failed
        await self._notify_admin(user_id, search_type, query)
        return {
            "success": False,
            "error": f"❌ No information found for `{query}`\n\n🔍 **Don't worry!** Your query has been sent to admin for manual review.\n\nWe'll notify you when we have results."
        }
    
    async def handle_incoming_message(self, event):
        """Handle incoming messages that might be search results"""
        try:
            message = event.message
            chat_id = event.chat_id
            message_id = message.id
            
            logger.info(f"📨 Incoming message: Chat={chat_id}, ID={message_id}")
            
            # Method 1: Check if this is a reply to our search
            if message.reply_to_msg_id:
                reply_to_id = message.reply_to_msg_id
                message_key = f"{chat_id}_{reply_to_id}"
                
                if message_key in self.message_to_search:
                    search_id = self.message_to_search[message_key]
                    if search_id in self.active_searches:
                        logger.info(f"🔗 Found reply match: {message_key} -> {search_id}")
                        await self._process_search_response(search_id, self.active_searches[search_id], message)
                        return
                    else:
                        logger.warning(f"⚠️ Search ID {search_id} not in active searches")
                        del self.message_to_search[message_key]
            
            # Method 2: Check if this message contains our search query
            text = message.text or message.raw_text or ""
            for search_id, search_info in list(self.active_searches.items()):
                # Check if same chat
                if str(chat_id) == str(search_info.get("chat_id", "")):
                    logger.info(f"📨 Message in same chat as search {search_id}")
                    
                    # Update last activity
                    search_info["last_activity"] = time.time()
                    
                    # Check if this is a result
                    await self._process_search_response(search_id, search_info, message)
                    return
            
            # Method 3: Check for files in this chat (in case it's not a reply)
            for search_id, search_info in list(self.active_searches.items()):
                if str(chat_id) == str(search_info.get("chat_id", "")):
                    # Check if message has a file
                    if await self._has_file(message):
                        logger.info(f"📁 Found file in chat for search {search_id}")
                        await self._process_search_response(search_id, search_info, message)
                        return
            
        except Exception as e:
            logger.error(f"Error handling incoming message: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _has_file(self, message) -> bool:
        """Check if message has a file"""
        return bool(
            message.media or 
            (hasattr(message, 'document') and message.document) or
            (hasattr(message, 'file') and message.file)
        )
    
    async def _check_and_process_file(self, message) -> Optional[Dict]:
        """Check if message has file and return processed result"""
        if await self._has_file(message):
            logger.info(f"📁 Processing file from message")
            # We'll process it in _process_search_response
            return True
        return False
    
    async def _process_search_response(self, search_id: str, search_info: Dict, message):
        """Process a search response message"""
        try:
            text = message.text or message.raw_text or ""
            logger.info(f"📨 Processing response for search {search_id}: {text[:100]}...")
            
            # Update last activity
            search_info["last_activity"] = time.time()
            
            # FIRST: Check if message has a file/document
            if await self._has_file(message):
                logger.info(f"✅ Found file attachment, processing...")
                result = await self._process_file(message, search_info)
                
                # Complete the search
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result(result)
                    
                    # Clean up
                    message_key = f"{search_info.get('chat_id', '')}_{search_info.get('message_id', '')}"
                    if message_key in self.message_to_search:
                        del self.message_to_search[message_key]
                    del self.active_searches[search_id]
                    
                    logger.info(f"✅ Search {search_id} completed with file")
                return
            
            # SECOND: Check if it's a file generation message
            if TextProcessor.is_file_generated_message(text):
                logger.info(f"📄 File generation message detected")
                
                # Check if file might be in this message (sometimes text comes with file)
                if await self._has_file(message):
                    logger.info(f"📁 File is in same message as caption")
                    result = await self._process_file(message, search_info)
                else:
                    # Mark that we're expecting a file
                    search_info["expecting_file"] = True
                    search_info["file_wait_start"] = time.time()
                    logger.info(f"⏳ Waiting for file to arrive...")
                    return
            
            # THIRD: Check if processing message
            elif TextProcessor.is_processing_message(text):
                logger.info(f"⏳ Processing message, continuing to wait...")
                return
            
            # FOURTH: Check if no-info message
            elif TextProcessor.is_no_info_message(text):
                logger.info(f"🚫 No-info message received")
                result = {"success": False}
                
                # Complete the search
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result(result)
                    
                    # Clean up
                    message_key = f"{search_info.get('chat_id', '')}_{search_info.get('message_id', '')}"
                    if message_key in self.message_to_search:
                        del self.message_to_search[message_key]
                    del self.active_searches[search_id]
                
                return
            
            # FIFTH: Check if this is a meaningful text response
            elif text and len(text.strip()) > 20:
                # Check if it looks like a result (not just a command or short message)
                if not text.startswith('/') and len(text.strip()) > 30:
                    logger.info(f"📝 Text response received, processing...")
                    result = await self._process_text(text, search_info)
                    
                    # Complete the search
                    if search_id in self.active_searches:
                        future = self.active_searches[search_id]["future"]
                        if not future.done():
                            future.set_result(result)
                        
                        # Clean up
                        message_key = f"{search_info.get('chat_id', '')}_{search_info.get('message_id', '')}"
                        if message_key in self.message_to_search:
                            del self.message_to_search[message_key]
                        del self.active_searches[search_id]
                    
                    return
                else:
                    logger.info(f"📝 Ignoring short/command message: {text[:50]}...")
                    return
            
            else:
                logger.info(f"⚠️ Ignoring empty/unrecognized message")
                return
                
        except Exception as e:
            logger.error(f"Error processing search response: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _process_file(self, message, search_info: Dict) -> Dict:
        """Process file message"""
        try:
            logger.info(f"📁 Processing file from {search_info['group']['name']}")
            
            # Download file
            file_path = f"temp_{int(time.time())}.txt"
            file_path = await message.download_media(file_path)
            
            if not file_path or not os.path.exists(file_path):
                logger.error("❌ Failed to download file")
                return {"success": False}
            
            # Read file content
            content = None
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    logger.info(f"✅ Decoded with {encoding}")
                    break
                except UnicodeDecodeError:
                    continue
            
            # Clean up temp file
            try:
                os.remove(file_path)
            except:
                pass
            
            if not content:
                logger.error("❌ Could not decode file")
                return {"success": False}
            
            # Clean and format content
            cleaned_content = TextProcessor.clean_content(content, search_info["search_type"])
            
            if len(cleaned_content.strip()) < 30:
                logger.warning(f"⚠️ Cleaned content too short: {len(cleaned_content)} chars")
                return {"success": False}
            
            # Format the result
            formatted_result = TextProcessor.format_result(
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
        try:
            # Clean and check length
            cleaned = TextProcessor.clean_content(text, search_info["search_type"])
            
            if len(cleaned) < 20:
                logger.warning(f"⚠️ Text too short after cleaning: {len(cleaned)} chars")
                return {"success": False}
            
            formatted = TextProcessor.format_result(
                cleaned,
                search_info["search_type"],
                search_info["query"],
                search_info["group"]["name"]
            )
            
            logger.info(f"✅ Processed text with {len(cleaned)} characters")
            return {
                "success": True,
                "result": formatted,
                "has_file": False
            }
            
        except Exception as e:
            logger.error(f"Error processing text: {e}")
            return {"success": False}         
            # Clean and format content
            cleaned_content = TextProcessor.clean_content(content, search_info["search_type"])
            
            if len(cleaned_content.strip()) < 30:
                logger.warning(f"⚠️ Cleaned content too short: {len(cleaned_content)} chars")
                # Try to extract more meaningful content
                lines = content.split('\n')
                meaningful_lines = []
                for line in lines:
                    line = line.strip()
                    if len(line) > 10:
                        # Remove promotional lines
                        if not any(word in line.lower() for word in ['powered', 'developed', 'created', 'join', 'subscribe', 'channel', 'admin', '@']):
                            meaningful_lines.append(line)
                
                if meaningful_lines:
                    cleaned_content = '\n'.join(meaningful_lines)
                    cleaned_content = TextProcessor.clean_content(cleaned_content, search_info["search_type"])
                else:
                    return {"success": False}
            
            # Format the result
            formatted_result = TextProcessor.format_result(
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
        # Clean and check length
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
                f"🚨 **Failed Search**\n\n"
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
            logger.error(f"Error notifying admin: {e}")

# ================== CLEANUP TASK ==================

async def cleanup_expired_searches():
    """Clean up expired searches and check for files"""
    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            current_time = time.time()
            expired = []
            
            for search_id, search_info in list(search_engine.active_searches.items()):
                # Check overall timeout (60 seconds)
                timeout = 60
                
                # If we're expecting a file, give more time
                if search_info.get("expecting_file") and search_info.get("file_wait_start"):
                    file_wait_time = current_time - search_info["file_wait_start"]
                    if file_wait_time < 30:  # 30 seconds for file
                        continue
                
                # Check last activity
                last_activity = search_info.get("last_activity", search_info["start_time"])
                if current_time - last_activity > timeout:
                    expired.append(search_id)
            
            for search_id in expired:
                search_info = search_engine.active_searches.pop(search_id, None)
                if search_info:
                    future = search_info["future"]
                    if not future.done():
                        try:
                            future.set_result({
                                "success": False,
                                "error": "❌ Search timeout. Please try again."
                            })
                        except:
                            pass
                    
                    # Clean up mapping
                    message_key = f"{search_info.get('chat_id', '')}_{search_info.get('message_id', '')}"
                    if message_key in search_engine.message_to_search:
                        del search_engine.message_to_search[message_key]
                    
                    logger.info(f"🧹 Cleaned expired search: {search_id}")
            
            if expired:
                logger.info(f"🧹 Cleaned {len(expired)} expired searches")
                
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
            logger.info("🔌 Connecting to MongoDB...")
            self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            self.client.server_info()  # Test connection
            self.db = self.client[config.MONGODB_DBNAME]
            logger.info("✅ MongoDB connected")
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            return False
    
    async def create_user(self, user_id: int, username: str, first_name: str) -> bool:
        """Create new user"""
        try:
            user_doc = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "joined_at": datetime.now(timezone.utc).isoformat(),
                "searches_remaining": config.NEW_USER_CREDITS,
                "total_searches": 0,
                "last_seen": datetime.now(timezone.utc).isoformat()
            }
            
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

# ================== KEYBOARD BUILDER ==================

class KeyboardBuilder:
    @staticmethod
    def main_menu(is_admin: bool = False) -> List[List[Button]]:
        """Build professional main menu"""
        buttons = []
        
        # Search buttons in 2 rows of 3
        search_types = list(SEARCH_COMMANDS.keys())
        
        # First row
        row1 = []
        for i in range(min(3, len(search_types))):
            cmd = SEARCH_COMMANDS[search_types[i]]
            row1.append(Button.inline(cmd["emoji"], f"search_{search_types[i]}"))
        if row1:
            buttons.append(row1)
        
        # Second row
        row2 = []
        for i in range(3, min(6, len(search_types))):
            cmd = SEARCH_COMMANDS[search_types[i]]
            row2.append(Button.inline(cmd["emoji"], f"search_{search_types[i]}"))
        if row2:
            buttons.append(row2)
        
        # Third row
        row3 = []
        for i in range(6, min(9, len(search_types))):
            cmd = SEARCH_COMMANDS[search_types[i]]
            row3.append(Button.inline(cmd["emoji"], f"search_{search_types[i]}"))
        if row3:
            buttons.append(row3)
        
        # User options
        buttons.append([
            Button.inline("👤 Profile", "profile"),
            Button.inline("💎 Premium", "premium")
        ])
        buttons.append([
            Button.inline("🎁 Referrals", "referrals"),
            Button.inline("🆘 Support", "support")
        ])
        
        # Admin button
        if is_admin:
            buttons.append([Button.inline("⚙️ Admin", "admin")])
        
        return buttons
    
    @staticmethod
    def search_menu(search_type: str) -> List[List[Button]]:
        """Build search type specific menu"""
        cmd = SEARCH_COMMANDS[search_type]
        return [
            [Button.inline(f"{cmd['emoji']} {cmd['name']}", f"info_{search_type}")],
            [Button.inline("❌ Cancel", "main_menu")]
        ]
    
    @staticmethod
    def cancel_button() -> List[List[Button]]:
        """Simple cancel button"""
        return [[Button.inline("❌ Cancel", "main_menu")]]

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
    """Handle /start command"""
    try:
        user = await event.get_sender()
        user_id = user.id
        
        # Create/get user
        user_doc = await db_manager.get_user(user_id)
        if not user_doc:
            await db_manager.create_user(user_id, user.username, user.first_name)
            user_doc = await db_manager.get_user(user_id)
        
        is_admin = user_id == config.ADMIN_USER_ID
        
        # Welcome message
        welcome = (
            f"👋 **Welcome {user.first_name}!**\n\n"
            f"💎 **Premium Information Bot**\n"
            f"⚡ Fast & Accurate Results\n\n"
            f"📊 **Your Stats:**\n"
            f"• Credits: {user_doc.get('searches_remaining', 0)}\n"
            f"• Total Searches: {user_doc.get('total_searches', 0)}\n\n"
            f"🔍 **Select a search type:**"
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
            await event.answer("❌ Invalid", alert=True)
            return
        
        user_doc = await db_manager.get_user(user_id)
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        # Check credits
        credits = user_doc.get('searches_remaining', 0)
        if credits <= 0:
            await event.edit(
                "❌ **No Credits**\n\nYou need more credits to search.\nContact @darkboxesAdmin",
                buttons=KeyboardBuilder.cancel_button()
            )
            return
        
        cmd = SEARCH_COMMANDS[search_type]
        
        await event.edit(
            f"{cmd['emoji']} **{cmd['name']}**\n\n"
            f"📝 {cmd['description']}\n\n"
            f"📤 Example: `{cmd['example']}`\n\n"
            f"💡 **Enter your query below:**",
            buttons=KeyboardBuilder.cancel_button(),
            parse_mode="md"
        )
        
        user_states[user_id] = {"action": "search", "type": search_type}
        
    except Exception as e:
        logger.error(f"Error in search_callback: {e}")
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
            f"🏠 **Main Menu**\n\n"
            f"📊 Credits: {user_doc.get('searches_remaining', 0) if user_doc else 0}\n"
            f"🔍 Total: {user_doc.get('total_searches', 0) if user_doc else 0}\n\n"
            f"Select a search type:"
        )
        
        await event.edit(message, buttons=KeyboardBuilder.main_menu(is_admin), parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in main_menu_callback: {e}")

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
            await event.respond("❌ Please enter a valid query.")
            return
        
        # Validate query
        cmd = SEARCH_COMMANDS[search_type]
        validation = cmd.get("validation")
        if validation and not re.match(validation, query):
            await event.respond(f"❌ Invalid format. Example: `{cmd['example']}`")
            return
        
        # Show searching status
        status = await event.respond(
            f"🔍 **Searching...**\n\n"
            f"⏳ Please wait 15-30 seconds\n"
            f"💡 Query: `{query}`\n\n"
            f"⚡ Searching premium databases...",
            parse_mode="md"
        )
        
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
        await event.respond("❌ An error occurred.")

@user_client.on(events.NewMessage())
async def handle_all_messages(event):
    """Handle all incoming messages for search responses"""
    try:
        await search_engine.handle_incoming_message(event)
    except Exception as e:
        # Ignore errors in message handler
        pass

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
            f"💎 **Admin Reply**\n\n{message}\n\n🔗 @darkboxesAdmin",
            parse_mode="md"
        )
        
        await event.respond(f"✅ Reply sent to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in admin_reply_handler: {e}")

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
        logger.info(f"🌐 Web server on port {config.PORT}")
    except Exception as e:
        logger.error(f"❌ Web server failed: {e}")

# ================== MAIN ==================

async def main():
    """Main function"""
    global search_engine
    
    try:
        logger.info("🚀 Starting Premium Bot...")
        
        # Start bot
        await bot_client.start(bot_token=config.BOT_TOKEN)
        bot_info = await bot_client.get_me()
        logger.info(f"✅ Bot: @{bot_info.username}")
        
        # Start user client
        if USE_USER_ACCOUNT:
            await user_client.connect()
            if not await user_client.is_user_authorized():
                logger.error("❌ User client not authorized")
                return
            logger.info("✅ User client ready")
        
        # Connect to DB
        if not await db_manager.connect():
            logger.error("❌ DB connection failed")
            return
        
        # Initialize search engine
        search_engine = SearchEngine(db_manager, db_manager)
        
        # Resolve groups
        logger.info("📡 Resolving groups...")
        for group in DESTINATION_GROUPS:
            try:
                group["entity"] = await user_client.get_entity(group["identifier"])
                logger.info(f"✅ {group['name']}")
            except Exception as e:
                logger.warning(f"⚠️ {group['name']}: {e}")
        
        # Start tasks
        asyncio.create_task(cleanup_expired_searches())
        asyncio.create_task(start_web_server())
        
        logger.info("=" * 50)
        logger.info("🎉 BOT READY!")
        logger.info("=" * 50)
        
        await asyncio.Event().wait()
        
    except KeyboardInterrupt:
        logger.info("🛑 Stopping...")
    except Exception as e:
        logger.error(f"❌ Fatal: {e}")
    finally:
        # Cleanup
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
        logger.error(f"Failed to start: {e}")
