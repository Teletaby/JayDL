from flask import Flask, request, jsonify, send_file, redirect, session, url_for
from flask_cors import CORS
import os
import logging
from datetime import datetime, timedelta
import requests
import tempfile
import threading
import time
from pathlib import Path
from dotenv import load_dotenv
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json
from urllib.parse import urlencode
import secrets
import hashlib
from functools import wraps
import random
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import sys


# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.info(f"RENDER_EXTERNAL_URL at startup: {os.getenv('RENDER_EXTERNAL_URL')}")

app = Flask(__name__)

# Check for required secret key in multi-worker environments
if os.getenv('RENDER') == 'true':
    # Gunicorn sets WEB_CONCURRENCY. Default is 1.
    try:
        workers = int(os.getenv('WEB_CONCURRENCY', 1))
    except (ValueError, TypeError):
        workers = 1
    
    # Add logging to verify the secret key is consistent across workers
    secret_key = os.getenv('FLASK_SECRET_KEY')
    if secret_key:
        key_hash = hashlib.sha256(secret_key.encode()).hexdigest()
        logger.info(f"FLASK_SECRET_KEY is set. SHA256 hash: {key_hash[:16]}...")
    else:
        logger.warning("FLASK_SECRET_KEY is NOT set. An ephemeral key will be used.")

    if workers > 1 and not secret_key:
        logger.critical("FATAL: FLASK_SECRET_KEY environment variable is not set.")
        raise ValueError("A static FLASK_SECRET_KEY is required in a multi-worker environment.")

# Session configuration. Using Flask's default client-side, cookie-based sessions
# is required for stateless platforms like Render.
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)

# Set cookie settings based on environment
if os.getenv('RENDER') == 'true':
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
else:
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Add CORS configuration
CORS(app,
     supports_credentials=True,
     origins=[
         "http://localhost:8000",
         "http://127.0.0.1:8000",
         "https://jaydl.onrender.com",
         "https://jaydl-backend.onrender.com"
     ],
     allow_headers=["Content-Type", "Authorization", "Accept", "Origin"],
     methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])

# Rate limiting configuration
# NOTE: In a multi-worker environment (like Render with Gunicorn), 'memory://' storage
# means each worker has its own rate limit counter. For synchronized limits,
# a centralized backend like Redis would be needed (e.g., 'redis://...').
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per hour", "30 per minute"],
    storage_uri="memory://",
)

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')

if os.getenv('RENDER') == 'true':
    GOOGLE_REDIRECT_URI = 'https://jaydl-backend.onrender.com/api/oauth2callback'
else:
    GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:5000/api/oauth2callback')

# Ensure we have the required credentials
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    logger.warning("Google OAuth credentials not configured. OAuth features will not work.")

# Google API scopes for YouTube access
SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]

# Initialize downloader
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', os.path.join(os.path.dirname(__file__), 'downloads'))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Shared account credentials storage
SHARED_CREDENTIALS_FILE = os.path.join(DOWNLOAD_DIR, '.shared_credentials.json')

def save_shared_credentials(credentials_dict):
    """Save shared account credentials to file"""
    try:
        with open(SHARED_CREDENTIALS_FILE, 'w') as f:
            json.dump(credentials_dict, f)
        logger.info("Shared credentials saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving shared credentials: {str(e)}")
        return False

def load_shared_credentials():
    """Load shared account credentials from file"""
    try:
        if os.path.exists(SHARED_CREDENTIALS_FILE):
            with open(SHARED_CREDENTIALS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading shared credentials: {str(e)}")
    return None

class SpotifyRateLimitTracker:
    """Track Spotify downloads and enforce daily rate limits"""
    def __init__(self, limit_per_day=20):
        self.limit_per_day = limit_per_day
        self.rate_limit_file = os.path.join(DOWNLOAD_DIR, '.spotify_rate_limit.txt')
        self.load_state()
    
    def load_state(self):
        """Load rate limit state from file"""
        if os.path.exists(self.rate_limit_file):
            try:
                with open(self.rate_limit_file, 'r') as f:
                    lines = f.read().strip().split('\n')
                    if len(lines) >= 2:
                        self.last_reset_date = lines[0]
                        self.download_count = int(lines[1])
                        
                        # Check if we need to reset (new day)
                        today = datetime.now().strftime('%Y-%m-%d')
                        if self.last_reset_date != today:
                            self.download_count = 0
                            self.last_reset_date = today
                            self.save_state()
                    else:
                        self.reset()
            except Exception as e:
                logger.error(f"Error loading rate limit state: {e}")
                self.reset()
        else:
            self.reset()
    
    def reset(self):
        """Reset rate limit for new day"""
        self.last_reset_date = datetime.now().strftime('%Y-%m-%d')
        self.download_count = 0
        self.save_state()
    
    def save_state(self):
        """Save rate limit state to file"""
        try:
            with open(self.rate_limit_file, 'w') as f:
                f.write(f"{self.last_reset_date}\n{self.download_count}")
        except Exception as e:
            logger.error(f"Error saving rate limit state: {e}")
    
    def increment_and_check(self):
        """Increment download count and return (is_at_limit, remaining_downloads)"""
        self.load_state()  # Refresh state
        self.download_count += 1
        self.save_state()
        
        remaining = max(0, self.limit_per_day - self.download_count)
        is_at_limit = self.download_count >= self.limit_per_day
        
        return is_at_limit, remaining

spotify_rate_limiter = SpotifyRateLimitTracker(limit_per_day=20)

class InvidiousDownloader:
    """Download videos using Invidious API (free, no rate limits)"""
    
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or tempfile.gettempdir()
        self.ensure_directories()
        
        # Invidious instances (fallback list)
        self.invidious_instances = [
            'https://inv.vern.cc',          # Fast, user recommended
            'https://vid.puffyan.us',       # Reliable
            'https://yt.artemislena.eu',    # Reliable
            'https://yewtu.be',             # Reliable, user recommended
            'https://inv.nadeko.net',       # User recommended
            'https://invidious.nerdvpn.de', # User recommended
            'https://invidious.projectsegfau.lt', # From official list
            'https://iv.ggtyler.dev',       # From official list
            'https://invidious.slipfox.xyz' # From official list
        ]
        self.piped_instances = [
            'https://pipedapi.kavin.rocks',
            'https://pipedapi.moomoo.me',
            'https://pipedapi.smnz.de',
            'https://pipedapi.adminforge.de',
            'https://piped-api.lunar.icu'
        ]
        self.api_instance = os.getenv('INVIDIOUS_INSTANCE', self.invidious_instances[0])
    
    def ensure_directories(self):
        os.makedirs(self.base_dir, exist_ok=True)
    
    def _get_yt_dlp_base_cmd(self, user_credentials=None, platform='generic'):
        """Constructs the base command for yt-dlp, handling authentication."""
        cmd = ['yt-dlp', '--no-warnings', '--geo-bypass']

        # For YouTube, add extractor args to avoid blocking on servers
        if platform == 'youtube':
            logger.info("Using 'android' player client for YouTube to improve reliability.")
            cmd.extend(['--extractor-args', 'youtube:player_client=android'])

        # Authentication logic
        # Priority 1: Use OAuth token for YouTube if available
        if platform == 'youtube' and user_credentials and user_credentials.token:
            logger.info("Using OAuth token for YouTube request.")
            cmd.extend(['--add-header', f"Authorization: Bearer {user_credentials.token}"])
        # Priority 2: Use browser cookies for local dev (if not on Render)
        elif os.getenv('RENDER') != 'true':
            logger.info("Using browser cookies for local development as fallback.")
            cmd.extend(['--cookies-from-browser', 'chrome'])
        else:
            # Priority 3: Unauthenticated request with rotating user-agent
            logger.info("Making unauthenticated request with rotated user-agent.")
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ]
            cmd.extend(['--user-agent', random.choice(user_agents)])
        
        return cmd
    
    def get_video_info(self, url, user_credentials=None):
        """Get video information using Invidious API for YouTube, yt-dlp for others"""
        try:
            # Detect platform
            platform = self.detect_platform(url)
 
            # For YouTube, use Invidious API
            if platform == 'youtube':
                video_id = self._extract_video_id(url)
                if not video_id:
                    return {'success': False, 'error': 'Invalid YouTube URL'}
                
                # --- STRATEGY 1: Direct Invidious ID lookup (provides direct download links) ---
                invidious_result = self.get_youtube_info_from_invidious(video_id, user_credentials)
                if invidious_result and invidious_result.get('source') == 'invidious':
                    logger.info("Success with Invidious direct links.")
                    return invidious_result
 
                # --- STRATEGY 2: Piped API lookup (provides metadata, server-side download) ---
                logger.warning("Invidious direct link method failed or didn't provide links. Trying Piped API.")
                piped_result = self.get_youtube_info_from_piped(video_id, user_credentials)
                if piped_result:
                    logger.info("Success with Piped for metadata.")
                    return piped_result

                # --- STRATEGY 3: Invidious search-based fallback ---
                logger.warning("Piped API failed. Trying Invidious search-based fallback.")
                invidious_search_result = self._search_invidious_by_title(url, video_id, user_credentials)
                if invidious_search_result:
                    return invidious_search_result
 
                # --- STRATEGY 4: Final fallback to yt-dlp ---
                logger.warning("All Invidious/Piped methods failed, using yt-dlp as a final fallback.")
                return self._get_fallback_info(video_id, user_credentials=user_credentials)
 
            # For other platforms (TikTok, Instagram, Twitter, Spotify), use yt-dlp
            else:
                logger.info(f"Analyzing {platform} URL: {url}")
                return self._get_generic_platform_info(url, platform, user_credentials=user_credentials)
 
        except Exception as e:
            logger.error(f"Error getting video info: {str(e)}")
            return {'success': False, 'error': f'Failed to get video info: {str(e)}'}

    def get_youtube_info_from_invidious(self, video_id, user_credentials=None):
        """Tries to get video info and stream URLs from Invidious."""
        logger.info(f"Analyzing YouTube video ID via Invidious: {video_id}")
        for instance in self.invidious_instances:
            try:
                info_url = f"{instance}/api/v1/videos/{video_id}"
                logger.info(f"Trying Invidious instance: {instance}")
                response = requests.get(info_url, timeout=7)
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Successfully got data from {instance}")
                    return self._parse_invidious_response(data, video_id, user_credentials=user_credentials)
                logger.warning(f"{instance} returned {response.status_code}")
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logger.warning(f"Invidious instance {instance} failed: {e}")
        return None # Return None if all instances fail

    def get_youtube_info_from_piped(self, video_id, user_credentials=None):
        """Tries to get video info from Piped API."""
        logger.info(f"Analyzing YouTube video ID via Piped: {video_id}")
        for instance in self.piped_instances:
            try:
                # Piped API endpoint for stream info, which includes metadata
                info_url = f"{instance}/streams/{video_id}"
                logger.info(f"Trying Piped instance: {instance}")
                response = requests.get(info_url, timeout=7)
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Successfully got data from Piped instance {instance}")
                    return self._parse_piped_response(data, video_id, user_credentials=user_credentials)
                logger.warning(f"Piped instance {instance} returned {response.status_code}")
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logger.warning(f"Piped instance {instance} failed: {e}")
        return None

    def _parse_piped_response(self, data, video_id, user_credentials=None):
        """Parse Piped API response. Piped provides separate streams, so downloads will be server-side."""
        try:
            title = data.get('title', f'Video {video_id[:8]}...')
            duration = self._format_duration(data.get('duration', 0))
            uploader = data.get('uploader', 'Unknown')
            views = data.get('views', 0)
            thumbnail = data.get('thumbnailUrl', f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg')
            
            logger.info(f"Got video info from Piped: {title} by {uploader}")
            
            # Piped provides separate audio/video streams. We cannot provide a direct download link
            # for a combined file. We will use yt-dlp for downloading, but we can use Piped's metadata.
            # We still need to get available formats from yt-dlp.
            logger.info("Piped provided metadata. Getting available formats via yt-dlp.")
            formats = self._get_available_formats(f'https://www.youtube.com/watch?v={video_id}', user_credentials=user_credentials)
            
            return {
                'success': True, 'title': title, 'duration': duration, 'thumbnail': thumbnail,
                'uploader': uploader, 'view_count': views, 'formats': formats,
                'platform': 'youtube', 'video_id': video_id,
                'source': 'piped' # Important for download logic - indicates server-side download needed
            }
        except Exception as e:
            logger.error(f"Error parsing Piped response: {e}")
            # If parsing fails, it's not a fatal error for the whole process, we can try other sources.
            return None

    def _get_title_with_yt_dlp(self, url, user_credentials):
        """A lightweight yt-dlp call to just get the video title."""
        try:
            import subprocess
            base_cmd = self._get_yt_dlp_base_cmd(user_credentials, platform='youtube')
            cmd = base_cmd + ['--get-title', url]
            logger.info(f"Getting title with yt-dlp: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                title = result.stdout.strip()
                logger.info(f"Got title via yt-dlp: {title}")
                return title
            else:
                logger.warning(f"Failed to get title with yt-dlp. Stderr: {result.stderr.strip()}")
                return None
        except Exception as e:
            logger.error(f"Exception while getting title with yt-dlp: {e}")
            return None

    def _search_invidious_by_title(self, url, video_id, user_credentials):
        """Searches Invidious for a video by its title as a fallback."""
        logger.info(f"Starting Invidious search-based fallback for video ID: {video_id}")
        
        # 1. Get the real title of the video using a lightweight yt-dlp call
        title = self._get_title_with_yt_dlp(url, user_credentials)
        if not title:
            logger.error("Could not get title for search-based fallback. Aborting search.")
            return None

        from urllib.parse import quote
        encoded_title = quote(title)

        # 2. Loop through Invidious instances and search
        for instance in self.invidious_instances:
            try:
                search_url = f"{instance}/api/v1/search?q={encoded_title}"
                logger.info(f"Searching on Invidious instance: {search_url}")
                
                search_response = requests.get(search_url, timeout=10)
                if search_response.status_code != 200:
                    logger.warning(f"Invidious search on {instance} failed with status {search_response.status_code}")
                    continue

                search_results = search_response.json()
                
                # 3. Find the matching video in the search results
                found_video = next((item for item in search_results if item.get('type') == 'video' and item.get('videoId') == video_id), None)
                
                if found_video:
                    logger.info(f"Found matching video ID {video_id} in search results from {instance}")
                    # 4. Now that we have a working instance, make a direct API call to get full details
                    info_url = f"{instance}/api/v1/videos/{video_id}"
                    info_response = requests.get(info_url, timeout=7)
                    if info_response.status_code == 200:
                        data = info_response.json()
                        logger.info(f"Successfully got full data from {instance} after search.")
                        parsed_data = self._parse_invidious_response(data, video_id, user_credentials=user_credentials)
                        if parsed_data and parsed_data.get('success'):
                            parsed_data['source'] = 'invidious-search' # Override source
                        return parsed_data
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logger.warning(f"Invidious search on instance {instance} failed: {e}")
        
        logger.error(f"Invidious search-based fallback failed for video ID: {video_id} across all instances.")
        return None

    def _get_generic_platform_info(self, url, platform, user_credentials=None):
        """Get video info from yt-dlp for non-YouTube platforms, or RapidAPI for Spotify"""
        try:
            import subprocess
            import json
            
            # Handle Spotify with RapidAPI instead of yt-dlp
            if platform == 'spotify':
                return self._get_spotify_info(url)
            
            # For other platforms, use yt-dlp
            # Try without cookies first, as they may not be available
            base_cmd = self._get_yt_dlp_base_cmd(user_credentials, platform)
            cmd = base_cmd + ['--dump-json', url]
            logger.info(f"Getting {platform} info with command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            
            logger.info(f"yt-dlp return code: {result.returncode}")
            logger.info(f"yt-dlp stdout length: {len(result.stdout)}")
            if result.stderr:
                logger.info(f"yt-dlp stderr: {result.stderr[:500]}")
            
            if result.returncode != 0:
                error_msg = result.stderr or "Failed to get video info"
                logger.error(f"yt-dlp error for {platform}: {error_msg}")
                # Don't expose technical error details to user
                return {'success': False, 'error': f'Unable to access this {platform} content. It may be private, deleted, or require authentication.'}
            
            if not result.stdout.strip():
                logger.error(f"yt-dlp returned empty stdout for {platform}")
                return {'success': False, 'error': f'Unable to access this {platform} content. It may be private or unavailable.'}
            
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as je:
                logger.error(f"JSON parse error for {platform}: {je}")
                logger.error(f"Raw output: {result.stdout[:500]}")
                return {'success': False, 'error': f'Unable to parse {platform} content. Please try a different link.'}
            
            title = data.get('title', 'Unknown Title')
            duration_seconds = data.get('duration', 0)
            duration = self._format_duration(duration_seconds) if duration_seconds else 'Unknown'
            
            # Extract uploader/creator based on platform
            if platform == 'tiktok':
                uploader = data.get('uploader', data.get('creator', 'Unknown'))
            elif platform == 'instagram':
                uploader = data.get('uploader', data.get('creator', data.get('channel', 'Unknown')))
            elif platform == 'twitter':
                uploader = data.get('uploader', data.get('uploader_id', 'Unknown'))
            else:
                uploader = data.get('uploader', 'Unknown')
            
            # Get thumbnail - try multiple fields
            thumbnail = data.get('thumbnail', '')
            if not thumbnail:
                # Try alternative thumbnail fields
                thumbnail = data.get('thumbnails', [{}])[0].get('url', '') if data.get('thumbnails') else ''
            if not thumbnail:
                thumbnail = data.get('thumb', '')
            
            logger.info(f"Got {platform} info: {title} by {uploader}")
            logger.info(f"Thumbnail URL: {thumbnail[:100] if thumbnail else 'None'}")
            
            # Get available formats
            formats = self._get_available_formats(url, user_credentials=user_credentials)
            
            return {
                'success': True,
                'title': title,
                'duration': duration,
                'thumbnail': thumbnail,
                'uploader': uploader,
                'view_count': data.get('view_count', 0),
                'formats': formats,
                'platform': platform,
                'url': url
            }
            
        except subprocess.TimeoutExpired:
            logger.error(f"yt-dlp timeout for {platform}")
            return {'success': False, 'error': f'Request timed out. The {platform} content took too long to load. Please try again.'}
        except Exception as e:
            logger.error(f"Error getting {platform} info: {e}", exc_info=True)
            return {'success': False, 'error': f'Unable to access this content. Please check the URL and try again.'}
    
    def _get_spotify_info(self, url):
        """Get Spotify track info using RapidAPI Spotify Downloader API"""
        try:
            import requests
            
            # Get RapidAPI credentials from environment
            rapidapi_key = os.getenv('RAPIDAPI_KEY') or os.getenv('RAPIDAPI_SPOTIFY_KEY')
            rapidapi_host = os.getenv('RAPIDAPI_HOST') or 'spotify-downloader9.p.rapidapi.com'
            
            if not rapidapi_key:
                logger.error("RAPIDAPI_KEY not configured for Spotify")
                return {'success': False, 'error': 'Spotify not configured. Please set RAPIDAPI_KEY environment variable.'}
            
            logger.info(f"Getting Spotify track info: {url}")
            
            headers = {
                "x-rapidapi-key": rapidapi_key,
                "x-rapidapi-host": rapidapi_host
            }
            
            api_url = f"https://{rapidapi_host}/downloadSong"
            params = {"songId": url}
            
            logger.info(f"Calling Spotify API: {api_url}")
            response = requests.get(api_url, headers=headers, params=params, timeout=20)
            
            logger.info(f"API Response status: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"Spotify API Response: {response_data}")
                
                if response_data.get('success'):
                    # The actual track data is nested in the 'data' field
                    data = response_data.get('data', {})
                    title = data.get('title', 'Unknown Title')
                    artist = data.get('artist', 'Unknown Artist')
                    album = data.get('album', 'Unknown Album')
                    thumbnail = data.get('cover', '')
                    release_date = data.get('releaseDate', '')
                    
                    logger.info(f"Got Spotify info: {title} by {artist}")
                    
                    # For Spotify, we only support audio downloads
                    formats = [
                        {
                            'format_id': 'bestaudio',
                            'resolution': 'Best Audio',
                            'height': 0,
                            'filesize': 'Unknown',
                            'format': 'Best Audio',
                            'type': 'audio',
                            'url': ''
                        }
                    ]
                    
                    return {
                        'success': True,
                        'title': f"{title} - {artist}",
                        'duration': 'Unknown',  # Spotify API doesn't provide duration in this format
                        'thumbnail': thumbnail,
                        'uploader': artist,
                        'view_count': 0,
                        'formats': formats,
                        'platform': 'spotify',
                        'url': url,
                        'album': album,
                        'release_date': release_date
                    }
                else:
                    error_msg = data.get('error') or data.get('message') or 'Unknown error'
                    logger.error(f"Spotify API error: {error_msg}")
                    return {'success': False, 'error': f'Spotify error: {error_msg}'}
            else:
                logger.error(f"Spotify API error: {response.status_code} - {response.text}")
                return {'success': False, 'error': f'Failed to connect to Spotify API (Status: {response.status_code})'}
                
        except requests.Timeout:
            logger.error("Spotify API request timed out")
            return {'success': False, 'error': 'Spotify API request timed out'}
        except Exception as e:
            logger.error(f"Error getting Spotify info: {e}", exc_info=True)
            return {'success': False, 'error': f'Failed to analyze Spotify URL: {str(e)}'}
    
    def _parse_invidious_response(self, data, video_id, user_credentials=None):
        """Parse Invidious API response and extract native formats if available."""
        try:
            title = data.get('title', f'Video {video_id[:8]}...')
            duration = self._format_duration(data.get('lengthSeconds', 0))
            uploader = data.get('author', 'Unknown')
            views = data.get('viewCount', 0)
            thumbnail = f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg'
            
            logger.info(f"Got video info: {title} by {uploader}")
            
            # NEW: Try to get formats directly from Invidious response
            formats = []
            source = 'yt-dlp' # Default source

            # Video streams with audio (from formatStreams)
            for stream in data.get('formatStreams', []):
                if 'video' in stream.get('type', '') and stream.get('url'):
                    formats.append({
                        'format_id': f"invidious_{stream.get('qualityLabel')}",
                        'resolution': stream.get('qualityLabel'),
                        'filesize': stream.get('size'),
                        'type': 'video',
                        'container': stream.get('container'),
                        'url': stream.get('url') # Direct download URL
                    })

            # Audio-only streams (from adaptiveFormats)
            for stream in data.get('adaptiveFormats', []):
                if stream.get('type', '') == 'audio' and stream.get('url'):
                    formats.append({
                        'format_id': f"invidious_audio_{stream.get('audioQuality')}",
                        'format': f"Audio ({stream.get('encoding')})",
                        'resolution': f"Audio ({stream.get('audioQuality')})",
                        'filesize': stream.get('size'),
                        'type': 'audio',
                        'container': stream.get('container'),
                        'url': stream.get('url') # Direct download URL
                    })
            
            if formats:
                logger.info(f"Successfully extracted {len(formats)} native stream URLs from Invidious.")
                source = 'invidious'
            else:
                # Fallback to yt-dlp for formats if Invidious didn't provide them
                logger.warning("Invidious did not provide stream URLs, falling back to yt-dlp for formats.")
                formats = self._get_available_formats(f'https://www.youtube.com/watch?v={video_id}', user_credentials=user_credentials)
            
            return {
                'success': True,
                'title': title,
                'duration': duration,
                'thumbnail': thumbnail,
                'uploader': uploader,
                'view_count': views,
                'formats': formats,
                'platform': 'youtube',
                'video_id': video_id,
                'source': source # Important for download logic
            }
        except Exception as e:
            logger.error(f"Error parsing Invidious response: {e}")
            return self._get_fallback_info(video_id, user_credentials=user_credentials)
    
    def _get_fallback_info(self, video_id, user_credentials=None):
        """
        Final fallback using yt-dlp. This should return a failure if it cannot get real info.
        """
        try:
            import subprocess
            import json

            base_cmd = self._get_yt_dlp_base_cmd(user_credentials, platform='youtube')
            cmd = base_cmd + ['--dump-json', f'https://www.youtube.com/watch?v={video_id}']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and result.stdout:
                try:
                    data = json.loads(result.stdout)
                    title = data.get('title')
                    if not title: # If title is empty, it's not a valid response
                        raise ValueError("yt-dlp returned JSON without a title.")

                    duration_seconds = data.get('duration', 0)
                    duration = self._format_duration(duration_seconds) if duration_seconds else 'Unknown'
                    uploader = data.get('uploader', data.get('channel', data.get('creator', 'Unknown')))
                    logger.info(f"Got info from yt-dlp fallback: {title} by {uploader} ({duration})")

                    # Get formats
                    formats = self._get_available_formats(f'https://www.youtube.com/watch?v={video_id}', user_credentials=user_credentials)

                    return {
                        'success': True,
                        'title': title,
                        'duration': duration,
                        'thumbnail': f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg',
                        'uploader': uploader,
                        'view_count': data.get('view_count', 0),
                        'formats': formats,
                        'platform': 'youtube',
                        'video_id': video_id,
                        'source': 'yt-dlp-fallback'
                    }
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Error parsing yt-dlp data in fallback: {e}")
                    # Fall through to failure case
            
            # If we reach here, it means yt-dlp failed or parsing failed.
            error_msg = result.stderr.strip() if result.stderr else "yt-dlp fallback failed to produce valid JSON output."
            logger.error(f"yt-dlp fallback info failed for {video_id}. Stderr: {error_msg}")
            return {'success': False, 'error': error_msg}

        except subprocess.TimeoutExpired:
            logger.error(f"yt-dlp fallback timed out for video ID: {video_id}")
            return {'success': False, 'error': 'Analysis timed out. The server may be under heavy load.'}
        except Exception as e:
            logger.error(f"Exception in _get_fallback_info: {e}")
            return {'success': False, 'error': str(e)}
    
    def _get_default_formats(self):
        """Return default format options"""
        return [
            {
                'format_id': '2160',
                'resolution': '2160p (4K)',
                'height': 2160,
                'filesize': 'Unknown',
                'format': '2160p (4K)',
                'type': 'video',
                'container': 'mp4',
                'url': ''
            },
            {
                'format_id': '1440',
                'resolution': '1440p (2K)',
                'height': 1440,
                'filesize': 'Unknown',
                'format': '1440p (2K)',
                'type': 'video',
                'container': 'mp4',
                'url': ''
            },
            {
                'format_id': '1080',
                'resolution': '1080p (Full HD)',
                'height': 1080,
                'filesize': 'Unknown',
                'format': '1080p (Full HD)',
                'type': 'video',
                'container': 'mp4',
                'url': ''
            },
            {
                'format_id': '720',
                'resolution': '720p (HD)',
                'height': 720,
                'filesize': 'Unknown',
                'format': '720p (HD)',
                'type': 'video',
                'container': 'mp4',
                'url': ''
            },
            {
                'format_id': '480',
                'resolution': '480p',
                'height': 480,
                'filesize': 'Unknown',
                'format': '480p',
                'type': 'video',
                'container': 'mp4',
                'url': ''
            },
            {
                'format_id': '360',
                'resolution': '360p',
                'height': 360,
                'filesize': 'Unknown',
                'format': '360p',
                'type': 'video',
                'container': 'mp4',
                'url': ''
            },
            {
                'format_id': 'mp4',
                'resolution': 'MP4 (Best)',
                'height': 0,
                'filesize': 'Unknown',
                'format': 'MP4 (Best)',
                'type': 'video',
                'container': 'mp4',
                'url': ''
            },
            {
                'format_id': 'bestaudio',
                'resolution': 'Best Audio',
                'height': 0,
                'filesize': 'Unknown',
                'format': 'Best Audio',
                'type': 'audio',
                'url': ''
            },
            {
                'format_id': '192',
                'resolution': '192 kbps',
                'height': 0,
                'filesize': 'Unknown',
                'format': '192 kbps',
                'type': 'audio',
                'url': ''
            },
            {
                'format_id': '128',
                'resolution': '128 kbps',
                'height': 0,
                'filesize': 'Unknown',
                'format': '128 kbps',
                'type': 'audio',
                'url': ''
            }
        ]
    
    def _get_available_formats(self, url, user_credentials=None):
        """Get actual available formats from yt-dlp"""
        try:
            import subprocess
            import json
            
            base_cmd = self._get_yt_dlp_base_cmd(user_credentials, platform=self.detect_platform(url))
            cmd = base_cmd + ['--dump-json', url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            
            if result.returncode != 0:
                logger.warning("Failed to get formats from yt-dlp, using defaults")
                return self._get_default_formats()
            
            data = json.loads(result.stdout)
            formats_data = data.get('formats', [])
            
            # Extract video resolutions with container info and filesizes
            available_heights = {}  # {height: {container: filesize}}
            audio_formats = {}  # {format_id: filesize}
            audio_available = False
            
            for fmt in formats_data:
                # Check for video formats with height
                if fmt.get('vcodec') != 'none' and fmt.get('height'):
                    height = fmt.get('height')
                    container = fmt.get('ext', 'mp4').lower()  # Get container from ext field
                    filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0
                    
                    if height not in available_heights:
                        available_heights[height] = {}
                    
                    # Keep the largest filesize for each height+container combo
                    if container not in available_heights[height] or filesize > available_heights[height][container]:
                        available_heights[height][container] = filesize
                
                # Check for audio only formats
                if fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none':
                    audio_available = True
                    format_id = fmt.get('format_id', 'audio')
                    filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0
                    audio_formats[format_id] = filesize
            
            logger.info(f"Available heights with containers: {available_heights}")
            logger.info(f"Audio available: {audio_available}")
            
            # Build format list based on available heights
            formats = []
            
            # Add video formats that are available (from all containers)
            quality_options = [
                ('2160', '2160p (4K)', 2160),
                ('1440', '1440p (2K)', 1440),
                ('1080', '1080p (Full HD)', 1080),
                ('720', '720p (HD)', 720),
                ('480', '480p', 480),
                ('360', '360p', 360),
            ]
            
            # Collect all available containers
            all_containers = set()
            for height_data in available_heights.values():
                all_containers.update(height_data.keys())
            
            logger.info(f"Available containers: {all_containers}")
            
            # For each quality, add all available container versions
            for quality_id, resolution, height in quality_options:
                if height in available_heights:
                    for container, filesize in available_heights[height].items():
                        formats.append({
                            'format_id': quality_id,
                            'resolution': resolution,
                            'height': height,
                            'filesize': filesize if filesize > 0 else 'Unknown',
                            'format': resolution,
                            'type': 'video',
                            'container': container,
                            'url': ''
                        })
            
            # Add best quality options for each container if videos available
            if available_heights:
                for container in all_containers:
                    best_filesize = 0
                    for height_data in available_heights.values():
                        if container in height_data:
                            best_filesize = max(best_filesize, height_data[container])
                    
                    formats.append({
                        'format_id': container,  # Use container as format_id for best options
                        'resolution': f'{container.upper()} (Best)',
                        'height': 0,
                        'filesize': best_filesize if best_filesize > 0 else 'Unknown',
                        'format': f'{container.upper()} (Best)',
                        'type': 'video',
                        'container': container,
                        'url': ''
                    })
            
            # Add audio formats
            if audio_available:
                bestaudio_size = audio_formats.get('bestaudio', 0) or max(audio_formats.values()) if audio_formats else 0
                formats.extend([
                    {
                        'format_id': 'bestaudio',
                        'resolution': 'Best Audio',
                        'height': 0,
                        'filesize': bestaudio_size if bestaudio_size > 0 else 'Unknown',
                        'format': 'Best Audio',
                        'type': 'audio',
                        'url': ''
                    },
                    {
                        'format_id': '192',
                        'resolution': '192 kbps',
                        'height': 0,
                        'filesize': 'Unknown',
                        'format': '192 kbps',
                        'type': 'audio',
                        'url': ''
                    },
                    {
                        'format_id': '128',
                        'resolution': '128 kbps',
                        'height': 0,
                        'filesize': 'Unknown',
                        'format': '128 kbps',
                        'type': 'audio',
                        'url': ''
                    }
                ])
            
            return formats if formats else self._get_default_formats()
            
        except Exception as e:
            logger.error(f"Error getting available formats: {e}")
            return self._get_default_formats()
    
    def _format_duration(self, seconds):
        """Format duration from seconds to HH:MM:SS"""
        if not seconds:
            return 'Unknown'
        # Convert to int to handle both int and float values
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
    
    def _extract_video_id(self, url):
        """Extract YouTube video ID from various URL formats"""
        try:
            from urllib.parse import urlparse, parse_qs
            
            parsed_url = urlparse(url)
            
            # Handle youtube.com/watch?v=XXX
            if 'youtube.com' in parsed_url.netloc:
                return parse_qs(parsed_url.query).get('v', [None])[0]
            
            # Handle youtu.be/XXX
            elif 'youtu.be' in parsed_url.netloc:
                return parsed_url.path.strip('/')
            
            # Handle youtube.com/shorts/XXX
            elif 'shorts' in parsed_url.path:
                return parsed_url.path.split('/')[-1]
            
            return None
        except Exception as e:
            logger.error(f"Error extracting video ID: {e}")
            return None
    
    def download_media(self, url, quality='720', media_type='video', user_credentials=None):
        """Download media using OAuth for YouTube, yt-dlp for others"""
        try:
            import subprocess
            import json
            
            # Ensure quality is a string
            quality = str(quality).strip()
            media_type = str(media_type).strip()
            
            # Detect platform
            platform = self.detect_platform(url)
            logger.info(f"Starting download: Platform={platform}, Quality={quality}, Type={media_type}")
            
            # Handle Spotify downloads with RapidAPI
            if platform == 'spotify':
                return self._download_spotify(url, quality, media_type)
            
            # For all other platforms, use yt-dlp
            return self._download_with_yt_dlp(url, quality, media_type, platform, user_credentials)
            
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return {'success': False, 'error': f'Download failed: {str(e)}'}
    
    def _download_with_yt_dlp(self, url, quality, media_type, platform, user_credentials=None):
        """Download using yt-dlp, leveraging OAuth or browser cookies for authentication."""
        try:
            import subprocess
            import json
            
            logger.info(f"Downloading with yt-dlp (platform={platform}, quality={quality}, type={media_type})")
            
            base_cmd = self._get_yt_dlp_base_cmd(user_credentials, platform)
            
            if media_type == 'audio':
                output_template = os.path.join(self.base_dir, f'%(title)s__audio.%(ext)s')
                cmd = base_cmd + [
                    '-f', 'bestaudio',
                    '-x',
                    '--audio-format', 'mp3',
                    '--audio-quality', '192',
                    '-o', output_template,
                    url
                ]
                logger.info(f"Downloading audio from {platform}")
            else:
                quality_map = {
                    '2160': 'bestvideo[height<=2160]+bestaudio/best[height<=2160]/best',
                    '1440': 'bestvideo[height<=1440]+bestaudio/best[height<=1440]/best',
                    '1080': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
                    '720': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                    '480': 'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                    '360': 'bestvideo[height<=360]+bestaudio/best[height<=360]/best',
                    'mp4': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'webm': 'bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best',
                    'best': 'bestvideo+bestaudio/best',
                    'bestaudio': 'bestaudio',
                    '192': 'bestaudio',
                    '128': 'bestaudio'
                }
                
                format_spec = quality_map.get(quality, 'bestvideo+bestaudio/best')
                
                if quality in ['bestaudio', '192', '128']:
                    output_template = os.path.join(self.base_dir, f'%(title)s__{quality}.%(ext)s')
                    cmd = base_cmd + [
                        '-f', 'bestaudio',
                        '-x',
                        '--audio-format', 'mp3',
                        '--audio-quality', quality if quality in ['192', '128'] else '192',
                        '-o', output_template,
                        url
                    ]
                else:
                    output_template = os.path.join(self.base_dir, f'%(title)s__{quality}.%(ext)s')
                    cmd = base_cmd + [
                        '-f', format_spec,
                        '-o', output_template,
                        url
                    ]
                
                logger.info(f"Downloading video {quality} from {platform}")
            
            logger.info(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                return self._process_download_result(result, url, platform=platform, user_credentials=user_credentials,
                                                    media_type=media_type, quality=quality)
            else:
                error_msg = result.stderr[:500] if result.stderr else 'Unknown error'
                logger.error(f"Download failed: {error_msg}")
                
                # Special handling for YouTube
                if platform == 'youtube':
                    if 'private' in error_msg.lower() or 'sign in' in error_msg.lower():
                        return {
                            'success': False,
                            'error': 'This YouTube video requires authentication. Please make sure you are signed into YouTube in your browser.',
                            'need_browser_login': True
                        }
                    elif 'age restricted' in error_msg.lower():
                        return {
                            'success': False,
                            'error': 'This YouTube video is age-restricted. Please sign into YouTube in your browser to access it.',
                            'need_browser_login': True
                        }
                
                return {'success': False, 'error': f'Download failed: {error_msg}'}
                
        except subprocess.TimeoutExpired:
            logger.error("Download timed out")
            return {'success': False, 'error': 'Download timed out (>10 minutes)'}
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return {'success': False, 'error': f'Download failed: {str(e)}'}
    
    def _process_download_result(self, result, url, platform, media_type, quality, user_credentials=None):
        """Process successful download result"""
        try:
            import subprocess
            import json
            
            base_cmd = self._get_yt_dlp_base_cmd(user_credentials, platform)
            info_cmd = base_cmd + [
                '--dump-json',
                url
            ]
            info_result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)
            
            filename = f'video_{platform}'
            
            if info_result.returncode == 0:
                try:
                    info_data = json.loads(info_result.stdout)
                    filename = info_data.get('title', f'video_{platform}')
                    logger.info(f"Got title from info: {filename}")
                except Exception as parse_err:
                    logger.warning(f"Error parsing info JSON: {parse_err}")
            else:
                logger.warning(f"Could not get info: {info_result.stderr}")
            
            # Determine expected file extensions
            if media_type == 'audio' or quality in ['bestaudio', '192', '128']:
                expected_extensions = ('.mp3', '.m4a', '.aac', '.opus', '.vorbis')
                quality_suffix = '__audio' if quality == 'bestaudio' else f'__{quality}'
            else:
                expected_extensions = ('.mp4', '.mkv', '.webm', '.m4a')
                quality_suffix = f'__{quality}'
            
            logger.info(f"Looking for file with suffix: {quality_suffix}")
            
            # Search for file with quality suffix in filename
            found_filepath = None
            for root, dirs, files in os.walk(self.base_dir):
                for file in files:
                    if quality_suffix in file and file.endswith(expected_extensions):
                        full_path = os.path.join(root, file)
                        file_mtime = os.path.getmtime(full_path)
                        current_time = time.time()
                        if current_time - file_mtime < 300:
                            found_filepath = full_path
                            logger.info(f"Found matching file: {found_filepath}")
                            break
                if found_filepath:
                    break
            
            # If not found, search without quality suffix
            if not found_filepath:
                for root, dirs, files in os.walk(self.base_dir):
                    for file in files:
                        if filename.replace(' ', '').replace('_', '').lower() in file.replace(' ', '').replace('_', '').lower() and file.endswith(expected_extensions):
                            full_path = os.path.join(root, file)
                            file_mtime = os.path.getmtime(full_path)
                            current_time = time.time()
                            if current_time - file_mtime < 300:
                                found_filepath = full_path
                                logger.info(f"Found file by pattern: {found_filepath}")
                                break
                    if found_filepath:
                        break
            
            # Last resort: look for any recently created file
            if not found_filepath:
                for root, dirs, files in os.walk(self.base_dir):
                    for file in files:
                        if file.endswith(expected_extensions):
                            full_path = os.path.join(root, file)
                            file_mtime = os.path.getmtime(full_path)
                            current_time = time.time()
                            if current_time - file_mtime < 60:
                                found_filepath = full_path
                                logger.info(f"Found recent file: {found_filepath}")
                                break
                    if found_filepath:
                        break
            
            filepath = found_filepath if found_filepath else os.path.join(self.base_dir, f"{filename}{'.mp3' if media_type == 'audio' else '.mp4'}")
            
            if os.path.exists(filepath):
                file_size = os.path.getsize(filepath)
                logger.info(f"File found: {filepath} ({file_size} bytes)")
                
                return {
                    'success': True,
                    'title': filename,
                    'filename': os.path.basename(filepath),
                    'filepath': filepath,
                    'file_size': self.format_file_size(file_size),
                    'download_url': f"/api/file/{os.path.basename(filepath)}",
                    'platform': platform,
                    'media_type': media_type,
                    'quality': f'{quality}p' if media_type == 'video' else 'MP3'
                }
            else:
                logger.error(f"File not found at: {filepath}")
                return {'success': True, 'message': 'Download completed', 'filename': 'video'}
                
        except Exception as e:
            logger.error(f"Error getting file info: {e}", exc_info=True)
            return {'success': True, 'message': 'Download completed successfully', 'filename': 'video'}
    
    def _download_spotify(self, url, quality='192', media_type='audio'):
        """Download Spotify track using RapidAPI"""
        try:
            import requests
            
            # Check rate limit
            is_at_limit, remaining = spotify_rate_limiter.increment_and_check()
            
            logger.info(f"Spotify download #{spotify_rate_limiter.download_count}/20. Remaining: {remaining}")
            
            if is_at_limit:
                return {
                    'success': False,
                    'error': 'Spotify rate limit reached (20 downloads per day)',
                    'rate_limit_hit': True,
                    'remaining_downloads': 0,
                    'resets_at': f"{datetime.now().strftime('%Y-%m-%d')} 00:00:00 (next day)"
                }
            
            # Get RapidAPI credentials
            rapidapi_key = os.getenv('RAPIDAPI_KEY')
            rapidapi_host = os.getenv('RAPIDAPI_HOST', 'spotify-downloader9.p.rapidapi.com')
            
            if not rapidapi_key:
                logger.error("RAPIDAPI_KEY not configured for Spotify download")
                return {'success': False, 'error': 'Spotify download not configured.'}
            
            logger.info(f"Downloading Spotify track: {url}")
            
            # Call RapidAPI
            headers = {
                "x-rapidapi-key": rapidapi_key,
                "x-rapidapi-host": rapidapi_host
            }
            
            api_url = f"https://{rapidapi_host}/downloadSong"
            params = {"songId": url}
            
            response = requests.get(api_url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                
                if response_data.get('success'):
                    data = response_data.get('data', {})
                    download_url = data.get('downloadLink')
                    title = data.get('title', 'spotify_track')
                    artist = data.get('artist', 'Unknown')
                    
                    if download_url:
                        logger.info(f"Got download URL: {download_url}")
                        
                        # Download the file
                        file_response = requests.get(download_url, timeout=60, headers={'User-Agent': 'Mozilla/5.0'})
                        
                        if file_response.status_code == 200:
                            # Save file
                            import re
                            filename_base = re.sub(r'[<>:"/\\|?*]', '_', f"{title} - {artist}")
                            filename = f"{filename_base}.mp3"
                            filepath = os.path.join(self.base_dir, filename)
                            
                            with open(filepath, 'wb') as f:
                                f.write(file_response.content)
                            
                            file_size = os.path.getsize(filepath)
                            logger.info(f"Spotify track downloaded: {filepath} ({file_size} bytes)")
                            
                            return {
                                'success': True,
                                'title': f"{title} - {artist}",
                                'filename': os.path.basename(filepath),
                                'filepath': filepath,
                                'file_size': self.format_file_size(file_size),
                                'download_url': f"/api/file/{os.path.basename(filepath)}",
                                'platform': 'spotify',
                                'media_type': 'audio',
                                'quality': 'MP3',
                                'remaining_downloads': max(0, 20 - spotify_rate_limiter.download_count)
                            }
                        else:
                            logger.error(f"Failed to download file from URL: {file_response.status_code}")
                            return {'success': False, 'error': 'Failed to download Spotify track file'}
                    else:
                        logger.error(f"No download URL in response")
                        return {'success': False, 'error': 'Could not find download link for this Spotify track'}
                else:
                    error_msg = response_data.get('error') or response_data.get('message') or 'Unknown error'
                    logger.error(f"API error: {error_msg}")
                    return {'success': False, 'error': f'Spotify API error: {error_msg}'}
            else:
                logger.error(f"API error: {response.status_code} - {response.text}")
                return {'success': False, 'error': f'Failed to connect to Spotify API (Status: {response.status_code})'}
                
        except requests.Timeout:
            logger.error("Spotify API request timed out")
            return {'success': False, 'error': 'Spotify API request timed out'}
        except Exception as e:
            logger.error(f"Error downloading Spotify track: {e}", exc_info=True)
            return {'success': False, 'error': f'Failed to download Spotify track: {str(e)}'}
    
    def format_file_size(self, bytes_size):
        if not bytes_size:
            return "Unknown"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} TB"
    
    def detect_platform(self, url):
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'youtube'
        elif 'tiktok.com' in url_lower:
            return 'tiktok'
        elif 'instagram.com' in url_lower:
            return 'instagram'
        elif 'twitter.com' in url_lower or 'x.com' in url_lower:
            return 'twitter'
        elif 'spotify.com' in url_lower:
            return 'spotify'
        else:
            return 'generic'

# Initialize the downloader
downloader = InvidiousDownloader(base_dir=DOWNLOAD_DIR)

# =============== OAUTH HELPER FUNCTIONS ===============

def is_authenticated():
    """Check if user is authenticated with Google OAuth (personal or shared)"""
    # Check for personal credentials first
    if 'credentials' in session:
        return True
    # Fall back to shared account
    shared_creds = load_shared_credentials()
    return shared_creds is not None

def get_user_credentials():
    """Get user credentials from session or shared account"""
    # Check for personal credentials first
    if 'credentials' in session:
        creds_dict = session['credentials']
        return google.oauth2.credentials.Credentials(**creds_dict)
    
    # Fall back to shared account credentials
    shared_creds = load_shared_credentials()
    if shared_creds:
        try:
            return google.oauth2.credentials.Credentials(**shared_creds)
        except Exception as e:
            logger.warning(f"Failed to create credentials from shared account: {str(e)}")
    
    return None

def requires_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated():
            return jsonify({
                'success': False,
                'error': 'Authentication required',
                'need_auth': True,
                'auth_url': '/api/oauth2authorize'
            }), 401
        return f(*args, **kwargs)
    return decorated_function

# =============== ROUTES ===============

@app.route('/')
def index():
    """API status page"""
    return jsonify({
        'success': True,
        'message': 'JayDL Backend API is running',
        'version': '1.0',
        'timestamp': datetime.now().isoformat(),
        'authenticated': is_authenticated(),
        'endpoints': {
            'analyze': '/api/analyze (POST)',
            'download': '/api/download (POST)',
            'platforms': '/api/platforms (GET)',
            'health': '/api/health (GET)',
            'admin_login': '/api/admin/login (POST)',
            'oauth_authorize': '/api/oauth2authorize (GET)',
            'oauth_callback': '/api/oauth2callback (GET)',
            'oauth_status': '/api/oauth2status (GET)',
            'oauth_logout': '/api/oauth2logout (POST)'
        }
    })

@app.route('/api/oauth2authorize')
def authorize():
    """Start OAuth2 authorization flow by redirecting user to Google."""
    try:
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise Exception("Google OAuth credentials are not configured on the server.")

        # Create flow instance
        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            },
            scopes=SCOPES
        )
        
        flow.redirect_uri = GOOGLE_REDIRECT_URI
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        # Store state in session for CSRF protection
        session['oauth_state'] = state
        session.modified = True
        
        logger.info(f"Redirecting user to Google for OAuth. State: {state[:8]}...")
        return redirect(authorization_url)
    
    except Exception as e:
        logger.error(f"Error generating auth URL: {str(e)}", exc_info=True)
        frontend_url = "https://jaydl.onrender.com" if os.getenv('RENDER') == 'true' else "http://localhost:8000"
        params = urlencode({'auth_status': 'failed', 'error': 'start_failed'})
        return redirect(f"{frontend_url}/?{params}")

@app.route('/api/oauth2callback')
def oauth2callback():
    """OAuth2 callback endpoint for same-window redirect flow."""
    frontend_url = "https://jaydl.onrender.com" if os.getenv('RENDER') == 'true' else "http://localhost:8000"

    try:
        # State validation for CSRF protection
        request_state = request.args.get('state')
        session_state = session.pop('oauth_state', None)
        
        if not session_state or request_state != session_state:
            logger.error("OAuth state mismatch. CSRF check failed.")
            params = urlencode({'auth_status': 'failed', 'error': 'invalid_state'})
            return redirect(f"{frontend_url}/?{params}")
        
        # Check for authorization errors from Google
        if request.args.get('error'):
            error = request.args.get('error')
            logger.error(f"OAuth error from Google: {error}")
            params = urlencode({'auth_status': 'failed', 'error': error})
            return redirect(f"{frontend_url}/?{params}")
        
        request_code = request.args.get('code')
        if not request_code:
            logger.error(f"No authorization code received")
            params = urlencode({'auth_status': 'failed', 'error': 'no_code'})
            return redirect(f"{frontend_url}/?{params}")
        
        # Create a flow for token exchange
        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            },
            scopes=SCOPES
        )
        
        flow.redirect_uri = GOOGLE_REDIRECT_URI
        
        # Exchange authorization code for credentials
        logger.info("Exchanging authorization code for token")
        
        flow.fetch_token(code=request_code)
        
        # Get credentials and store in session
        credentials = flow.credentials
        creds_dict = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        session['credentials'] = creds_dict
        session.modified = True
        logger.info("User authenticated and credentials stored in session.")
        
        # Redirect back to frontend with success
        params = urlencode({'auth_status': 'success'})
        return redirect(f"{frontend_url}/?{params}")
    
    except Exception as e:
        logger.error(f"OAuth callback error: {str(e)}", exc_info=True)
        params = urlencode({'auth_status': 'failed', 'error': 'callback_failed'})
        return redirect(f"{frontend_url}/?{params}")

@app.route('/api/oauth2status')
def oauth_status():
    """Check OAuth authentication status"""
    if is_authenticated():
        try:
            creds = get_user_credentials()
            # Test the credentials by making a simple API call
            youtube = build('youtube', 'v3', credentials=creds)
            request_info = youtube.channels().list(
                part='snippet',
                mine=True
            )
            response = request_info.execute()
            
            user_info = {
                'authenticated': True,
                'user_name': response['items'][0]['snippet']['title'] if response.get('items') else 'Authenticated User',
                'expires_at': creds.expiry.isoformat() if creds.expiry else None
            }
            
            return jsonify({
                'success': True,
                'authenticated': True,
                'user_info': user_info
            })
        except Exception as e:
            # Credentials might be expired
            logger.warning(f"Credentials check failed: {str(e)}")
            session.pop('credentials', None)
            return jsonify({
                'success': True,
                'authenticated': False,
                'error': 'Session expired'
            })
    
    return jsonify({
        'success': True,
        'authenticated': False
    })

@app.route('/api/oauth2logout', methods=['POST'])
def oauth_logout():
    """Log out (clear OAuth session)"""
    session.clear()
    logger.info("User logged out")
    return jsonify({
        'success': True,
        'message': 'Logged out successfully'
    })

@app.route('/api/oauth2/setup-shared-account')
def setup_shared_account():
    """Setup endpoint for shared account - use after authenticating with shared Gmail"""
    try:
        # This endpoint should only be called after user authenticates
        # It will store the OAuth credentials as shared credentials
        if not is_authenticated():
            return jsonify({
                'success': False,
                'error': 'User must be authenticated first',
                'message': 'Please authenticate with the shared Gmail account first'
            }), 401
        
        # Get credentials from session
        if 'credentials' not in session:
            return jsonify({
                'success': False,
                'error': 'No user credentials found'
            }), 400
        
        creds_dict = session['credentials']
        
        # Verify the account is valid by getting user info
        try:
            creds = google.oauth2.credentials.Credentials(**creds_dict)
            
            # Use the more reliable userinfo endpoint, which works for any Google account
            userinfo_service = build('oauth2', 'v2', credentials=creds)
            user_info = userinfo_service.userinfo().get().execute()

            if user_info and user_info.get('name'):
                account_name = user_info.get('name')
                logger.info(f"Setting up shared account for user: {account_name}")
            else:
                logger.error("Could not get user info from token.")
                return jsonify({
                    'success': False,
                    'error': 'Could not verify account information'
                }), 400

        except Exception as e:
            logger.error(f"Error verifying account: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Failed to verify account: {str(e)}'
            }), 400
        
        # Save credentials as shared
        if save_shared_credentials(creds_dict):
            return jsonify({
                'success': True,
                'message': f'Shared account setup successful for {account_name}',
                'account_info': {
                    'channel_name': account_name,
                    'setup_timestamp': datetime.now().isoformat()
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save shared credentials'
            }), 500
            
    except Exception as e:
        logger.error(f"Error setting up shared account: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Setup failed: {str(e)}'
        }), 500

@app.route('/api/oauth2/shared-account-status')
def shared_account_status():
    """Check if shared account is configured"""
    try:
        shared_creds = load_shared_credentials()
        
        if not shared_creds:
            return jsonify({
                'success': True,
                'has_shared_account': False,
                'message': 'No shared account configured'
            })
        
        # Try to verify the shared account is still valid
        try:
            creds = google.oauth2.credentials.Credentials(**shared_creds)
            youtube = build('youtube', 'v3', credentials=creds)
            request_info = youtube.channels().list(
                part='snippet',
                mine=True
            )
            response = request_info.execute()
            
            if response.get('items'):
                channel_name = response['items'][0]['snippet']['title']
                return jsonify({
                    'success': True,
                    'has_shared_account': True,
                    'account_info': {
                        'channel_name': channel_name,
                        'is_valid': True
                    }
                })
        except Exception as e:
            logger.warning(f"Shared account credentials may be expired: {str(e)}")
            return jsonify({
                'success': True,
                'has_shared_account': True,
                'account_info': {
                    'is_valid': False,
                    'needs_refresh': True,
                    'error': 'Credentials may need refreshing'
                }
            })
    
    except Exception as e:
        logger.error(f"Error checking shared account status: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Status check failed: {str(e)}'
        }), 500

@app.route('/api/analyze', methods=['POST'])
@limiter.limit("20 per minute")
def analyze_media():
    """Analyze a URL and return media information"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data received'}), 400
            
        url = data.get('url')
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400
        
        # Basic URL validation
        if not url.startswith(('http://', 'https://')):
            return jsonify({'success': False, 'error': 'Invalid URL format'}), 400
        
        user_credentials = get_user_credentials()
        
        logger.info(f"Analyzing URL: {url}")
        result = downloader.get_video_info(url, user_credentials=user_credentials)
        
        if result['success']:
            logger.info(f"Successfully analyzed: {result['title']}")
        else:
            logger.error(f"Analysis failed: {result['error']}")
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in analyze_media: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Server error. Please try again.'
        }), 500

@app.route('/api/download', methods=['POST'])
@limiter.limit("10 per minute")
def download_media():
    """Download media from URL"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data received'}), 400
            
        url = data.get('url')
        quality = data.get('quality', 'best')
        media_type = data.get('media_type', 'video')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400
        
        # Check for Invidious direct download
        if quality and 'invidious' in quality:
            logger.info(f"Attempting direct download via Invidious for quality: {quality}")
            video_id = downloader._extract_video_id(url)
            if video_id:
                # Re-analyze with Invidious to get fresh URLs
                invidious_info = downloader.get_youtube_info_from_invidious(video_id)
                if invidious_info and invidious_info.get('source') == 'invidious':
                    selected_format = next((f for f in invidious_info.get('formats', []) if f.get('format_id') == quality), None)
                    if selected_format and selected_format.get('url'):
                        logger.info("✅ Found direct Invidious URL. Sending to client.")
                        return jsonify({
                            'success': True,
                            'download_url': selected_format['url'] # This is an absolute URL
                        })
            logger.warning("Invidious direct download failed, falling back to yt-dlp.")

        logger.info(f"Downloading: {url} | Quality: {quality} | Type: {media_type}")
        
        # Get user credentials if authenticated
        user_credentials = get_user_credentials()
        result = downloader.download_media(
            url, 
            quality=quality, 
            media_type=media_type,
            user_credentials=user_credentials
        )
        
        if result.get('success'):
            logger.info(f"Successfully downloaded: {result.get('title', 'Unknown')}")
            # Ensure download_url is set
            if 'filename' in result and 'download_url' not in result:
                result['download_url'] = f"/api/file/{result['filename']}"
        else:
            logger.error(f"Download failed: {result.get('error', 'Unknown error')}")
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in download_media: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Server error: {str(e)}'
        }), 500

@app.route('/api/file/<filename>', methods=['GET'])
def serve_file(filename):
    """Serve downloaded file"""
    try:
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        
        if not os.path.exists(filepath):
            return jsonify({
                'success': False,
                'error': 'File not found'
            }), 404
        
        logger.info(f"Serving file: {filename}")
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename
        )
    
    except Exception as e:
        logger.error(f"Error serving file: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Server error: {str(e)}'
        }), 500

@app.route('/api/platforms', methods=['GET'])
def get_platforms():
    """Return list of supported platforms"""
    platforms = [
        {
            'name': 'YouTube',
            'icon': 'fab fa-youtube',
            'color': '#FF0000',
            'supported': True,
            'requires_auth': False,  # Changed from True to False - uses browser cookies
            'auth_type': 'browser_cookies',
            'hint': 'Sign into YouTube in your browser for best results'
        },
        {
            'name': 'TikTok',
            'icon': 'fab fa-tiktok',
            'color': '#000000',
            'supported': True,
            'requires_auth': False
        },
        {
            'name': 'Instagram',
            'icon': 'fab fa-instagram',
            'color': '#E4405F',
            'supported': True,
            'requires_auth': False
        },
        {
            'name': 'Twitter/X',
            'icon': 'fab fa-twitter',
            'color': '#1DA1F2',
            'supported': True,
            'requires_auth': False
        },
        {
            'name': 'Spotify',
            'icon': 'fab fa-spotify',
            'color': '#1DB954',
            'supported': True,
            'requires_auth': False,
            'rate_limited': True,
            'hint': 'Limited to 20 downloads per day'
        }
    ]
    
    return jsonify({
        'success': True,
        'platforms': platforms
    })

@app.route('/privacy', methods=['GET'])
def privacy_policy():
    """Serve privacy policy"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Privacy Policy - JayDL</title>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; max-width: 900px; margin: 0 auto; padding: 20px; background: #f4f4f4; }
            .container { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            h1 { color: #333; border-bottom: 3px solid #007bff; padding-bottom: 10px; }
            h2 { color: #007bff; margin-top: 30px; }
            p { color: #666; }
            ul { margin: 10px 0; padding-left: 20px; }
            li { margin: 8px 0; }
            .emoji { font-size: 1.2em; margin-right: 5px; }
            code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Privacy Policy</h1>
            <p><strong>Last Updated:</strong> December 5, 2025</p>
            
            <h2>Introduction</h2>
            <p>JayDL is committed to protecting your privacy. This Privacy Policy explains how we collect, use, disclose, and safeguard your information.</p>
            
            <h2>Information We Collect</h2>
            <h3>User Authentication</h3>
            <ul>
                <li><strong>Google Account Information:</strong> When you sign in with Google OAuth, we collect your Google profile name and profile picture for display purposes.</li>
                <li><strong>User ID:</strong> A unique identifier associated with your Google account to personalize your experience.</li>
            </ul>
            
            <h3>Usage Data</h3>
            <ul>
                <li><strong>Download History:</strong> Records of videos/audio you download through our service.</li>
                <li><strong>Preferences:</strong> Your app settings and preferences.</li>
                <li><strong>Browser Information:</strong> IP address, browser type, operating system (for analytics and security).</li>
                <li><strong>Cookies:</strong> We use cookies to maintain your session and remember your preferences.</li>
            </ul>
            
            <h2>What We Do NOT Collect</h2>
            <ul>
                <li><span class="emoji">❌</span> Your Google account password</li>
                <li><span class="emoji">❌</span> Your email address (unless you voluntarily provide it)</li>
                <li><span class="emoji">❌</span> Your contacts or personal data from Google</li>
                <li><span class="emoji">❌</span> Financial or payment information</li>
                <li><span class="emoji">❌</span> Sensitive personal information</li>
            </ul>
            
            <h2>How We Use Your Information</h2>
            <ol>
                <li><strong>Authentication & Security:</strong> To verify your identity and prevent unauthorized access</li>
                <li><strong>Service Personalization:</strong> To customize your experience and show your download history</li>
                <li><strong>Improvement:</strong> To analyze usage patterns and improve our service</li>
                <li><strong>Legal Compliance:</strong> To comply with legal obligations and enforce our terms</li>
            </ol>
            
            <h2>Data Security</h2>
            <p>We implement industry-standard security measures to protect your data. However, no method of transmission over the internet is 100% secure.</p>
            
            <h2>Third-Party Services</h2>
            <ul>
                <li><strong>Google OAuth:</strong> For secure authentication (<a href="https://policies.google.com/privacy">Google's Privacy Policy</a>)</li>
                <li><strong>YouTube API:</strong> For accessing public video data (<a href="https://www.youtube.com/static?template=terms">YouTube's Terms of Service</a>)</li>
                <li><strong>Render:</strong> For hosting our service</li>
            </ul>
            
            <h2>Data Retention</h2>
            <ul>
                <li>Authentication Data: Retained while you maintain an account</li>
                <li>Download History: Retained until you clear your browser data or account</li>
                <li>Session Data: Automatically deleted when you log out</li>
            </ul>
            
            <h2>Your Rights</h2>
            <p>You have the right to:</p>
            <ul>
                <li>Access your personal information</li>
                <li>Request deletion of your data</li>
                <li>Withdraw consent at any time by discontinuing use of our service</li>
            </ul>
            
            <h2>Contact Us</h2>
            <p>If you have questions about this Privacy Policy, please contact us at:</p>
            <ul>
                <li><strong>GitHub:</strong> <a href="https://github.com/Teletaby/jaydl-render">https://github.com/Teletaby/jaydl-render</a></li>
                <li><strong>Email:</strong> gutierrezjustinjames63@gmail.com</li>
            </ul>
            
            <p><strong>By using JayDL, you agree to this Privacy Policy.</strong></p>
        </div>
    </body>
    </html>
    ''', 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/terms', methods=['GET'])
def terms_of_service():
    """Serve terms of service"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Terms of Service - JayDL</title>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; max-width: 900px; margin: 0 auto; padding: 20px; background: #f4f4f4; }
            .container { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            h1 { color: #333; border-bottom: 3px solid #007bff; padding-bottom: 10px; }
            h2 { color: #007bff; margin-top: 30px; }
            p { color: #666; }
            ul { margin: 10px 0; padding-left: 20px; }
            li { margin: 8px 0; }
            ol { margin: 10px 0; padding-left: 20px; }
            code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; }
            a { color: #007bff; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Terms of Service</h1>
            <p><strong>Last Updated:</strong> December 5, 2025</p>
            
            <h2>Acceptance of Terms</h2>
            <p>By accessing and using JayDL (the "Service"), you accept and agree to be bound by the terms and provision of this agreement.</p>
            
            <h2>Use License</h2>
            <p>Permission is granted to temporarily download one copy of the materials (information or software) on JayDL for personal, non-commercial transitory viewing only. You may not:</p>
            <ul>
                <li>Modify or copy the materials</li>
                <li>Use the materials for any commercial purpose or for any public display</li>
                <li>Attempt to decompile or reverse engineer any software contained on the Service</li>
                <li>Remove any copyright or other proprietary notations from the materials</li>
                <li>Transfer the materials to another person or "mirror" the materials on any other server</li>
                <li>Violate the Terms of Service of any third-party services (YouTube, Google, etc.)</li>
            </ul>
            
            <h2>Disclaimer</h2>
            <p>The materials on JayDL are provided on an "as is" basis. We make no warranties, expressed or implied, and hereby disclaim and negate all other warranties.</p>
            
            <h2>User Responsibilities</h2>
            <p>As a user of JayDL, you agree to:</p>
            <ol>
                <li><strong>Respect Copyright Laws:</strong> Only download content you have the right to download. Respect copyright laws and the terms of service of the platforms you're downloading from (especially YouTube's Terms of Service).</li>
                <li><strong>Lawful Use Only:</strong> Use the Service only for lawful purposes and in a way that does not infringe upon the rights of others.</li>
                <li><strong>No Illegal Content:</strong> Do not download, upload, or share content that is illegal, infringing, pornographic, hateful, threatening, or abusive.</li>
                <li><strong>Account Security:</strong> You are responsible for maintaining the confidentiality of your account information and password.</li>
                <li><strong>Browser Authentication:</strong> For YouTube downloads, you must be signed into YouTube in your browser. JayDL uses browser cookies to access YouTube content.</li>
            </ol>
            
            <h2>Third-Party Platform Terms</h2>
            <p>By using JayDL to download content from YouTube or other platforms, you agree to comply with:</p>
            <ul>
                <li><strong>YouTube Terms of Service:</strong> <a href="https://www.youtube.com/static?template=terms">https://www.youtube.com/static?template=terms</a></li>
                <li><strong>Google Terms of Service:</strong> <a href="https://policies.google.com/terms">https://policies.google.com/terms</a></li>
            </ul>
            
            <h2>Content Downloads</h2>
            <p>We do not store, host, or distribute the content you download. The Service only facilitates the download process. Users are solely responsible for ensuring they have the right to download and use any content.</p>
            
            <h2>Browser Cookies</h2>
            <p>JayDL uses browser cookies to access YouTube content. For YouTube downloads to work properly, you must:</p>
            <ul>
                <li>Be signed into YouTube in your browser</li>
                <li>Allow cookies from YouTube</li>
                <li>Not clear your browser cookies before downloading</li>
            </ul>
            
            <h2>Limitation of Liability</h2>
            <p>JayDL shall not be liable for any indirect, incidental, special, consequential, or punitive damages resulting from your use of or inability to use the Service.</p>
            
            <h2>Termination</h2>
            <p>We may terminate your access to the Service at any time, without notice, for any reason whatsoever.</p>
            
            <h2>Contact & Support</h2>
            <p>For questions about these Terms of Service:</p>
            <ul>
                <li><strong>GitHub:</strong> <a href="https://github.com/Teletaby/jaydl-render">https://github.com/Teletaby/jaydl-render</a></li>
                <li><strong>Email:</strong> gutierrezjustinjames63@gmail.com</li>
            </ul>
            
            <p><strong>By using JayDL, you acknowledge that you have read these Terms of Service and agree to be bound by them.</strong></p>
        </div>
    </body>
    </html>
    ''', 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'oauth_configured': bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        'session_active': is_authenticated()
    })

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    """Validate admin password."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data received'}), 400

    password = data.get('password')

    # IMPORTANT: This is a hardcoded password as requested.
    # In a real app, use a securely hashed password from environment variables.
    if password == 'smprime123':
        return jsonify({'success': True, 'message': 'Admin login successful'})
    else:
        return jsonify({'success': False, 'error': 'Invalid password'}), 401

@app.route('/api/debug/oauth', methods=['GET'])
def debug_oauth():
    """Debug OAuth configuration (development only)"""
    return jsonify({
        'client_id_set': bool(GOOGLE_CLIENT_ID),
        'client_id_length': len(GOOGLE_CLIENT_ID) if GOOGLE_CLIENT_ID else 0,
        'client_secret_set': bool(GOOGLE_CLIENT_SECRET),
        'client_secret_length': len(GOOGLE_CLIENT_SECRET) if GOOGLE_CLIENT_SECRET else 0,
        'redirect_uri': GOOGLE_REDIRECT_URI,
        'scopes': SCOPES
    })

# Cleanup old files periodically in a background thread
def cleanup_old_files_background():
    """Clean up files older than 2 hours in background thread"""
    while True:
        try:
            # Sleep for 30 minutes before cleaning
            time.sleep(1800)
            
            if not os.path.exists(DOWNLOAD_DIR):
                continue
            
            current_time = datetime.now().timestamp()
            cleaned_count = 0
            
            for filename in os.listdir(DOWNLOAD_DIR):
                try:
                    filepath = os.path.join(DOWNLOAD_DIR, filename)
                    
                    # Skip if not a file
                    if not os.path.isfile(filepath):
                        continue
                    
                    # Skip hidden files
                    if filename.startswith('.'):
                        continue
                    
                    # Check file age (clean up files older than 2 hours)
                    file_age = current_time - os.path.getmtime(filepath)
                    
                    # Delete if older than 2 hours
                    if file_age > 7200:
                        os.remove(filepath)
                        cleaned_count += 1
                        logger.info(f"Cleaned up old file: {filename}")
                except Exception as e:
                    logger.error(f"Error processing file {filename}: {str(e)}")
            
            if cleaned_count > 0:
                logger.info(f"Cleanup completed: removed {cleaned_count} old files")
        except Exception as e:
            logger.error(f"Error in cleanup loop: {str(e)}")

# Start cleanup thread on app startup
try:
    cleanup_thread = threading.Thread(target=cleanup_old_files_background, daemon=True)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    logger.info("Started background cleanup thread")
except Exception as e:
    logger.error(f"Failed to start cleanup thread: {str(e)}")

# Install required packages if not present
def check_dependencies():
    try:
        import google_auth_oauthlib
        import googleapiclient
        logger.info("OAuth dependencies are installed")
    except ImportError:
        logger.warning("Some OAuth dependencies may not be installed. Run: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")

check_dependencies()

# Update yt-dlp on startup to get latest fixes
def update_yt_dlp():
    """Attempt to update yt-dlp to the latest version using pip."""
    import subprocess
    logger.info("Attempting to update yt-dlp...")
    try:
        # Using python -m pip to be sure about the environment
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            logger.info("yt-dlp update successful.")
            # Log only first few lines of output to avoid clutter
            logger.info('\n'.join(result.stdout.splitlines()[:5]))
        else:
            logger.error(f"Failed to update yt-dlp. Return code: {result.returncode}\n{result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("yt-dlp update command timed out.")
    except Exception as e:
        logger.error(f"An error occurred during yt-dlp update: {e}")

update_yt_dlp()

if __name__ == '__main__':
    # Get port from environment variable or default to 5000
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'production') == 'development'
    
    logger.info(f"Starting JayDL Backend on port {port}")
    logger.info(f"Debug mode: {debug}")
    logger.info(f"Download directory: {DOWNLOAD_DIR}")
    logger.info(f"OAuth configured: {bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)}")
    
    app.run(debug=debug, host='0.0.0.0', port=port)