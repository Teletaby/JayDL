from flask import Flask, request, jsonify, send_file, redirect, session, url_for
from flask_cors import CORS
from flask_session import Session
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
from functools import wraps

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_pyfile('config.py', silent=True)

# Session configuration for OAuth
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_COOKIE_SECURE'] = True  # Always True for HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Use Lax for same-site requests
app.config['SESSION_COOKIE_NAME'] = 'jaydl_session'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['SESSION_COOKIE_PATH'] = '/'

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

Session(app)

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:5000/api/oauth2callback')

# For production, use environment-specific redirect URIs
if os.getenv('FLASK_ENV') == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True
    if not GOOGLE_REDIRECT_URI:
        GOOGLE_REDIRECT_URI = 'https://jaydl-backend.onrender.com/api/oauth2callback'

# Google API scopes for YouTube access
SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]

# Initialize downloader
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', os.path.join(os.path.dirname(__file__), 'downloads'))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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
            'https://invidious.io',
            'https://inv.vern.cc',
            'https://invidious.snopyta.org',
            'https://inv.nadeko.net'
        ]
        self.api_instance = os.getenv('INVIDIOUS_INSTANCE', self.invidious_instances[0])
    
    def ensure_directories(self):
        os.makedirs(self.base_dir, exist_ok=True)
    
    def get_video_info(self, url):
        """Get video information using Invidious API for YouTube, yt-dlp for others"""
        try:
            # Detect platform
            platform = self.detect_platform(url)
            
            # For YouTube, use Invidious API
            if platform == 'youtube':
                # Extract video ID from URL
                video_id = self._extract_video_id(url)
                if not video_id:
                    return {'success': False, 'error': 'Invalid YouTube URL'}
                
                logger.info(f"Analyzing YouTube video ID: {video_id}")
                
                # Try each Invidious instance
                for instance in self.invidious_instances:
                    try:
                        info_url = f"{instance}/api/v1/videos/{video_id}"
                        logger.info(f"Trying Invidious instance: {instance}")
                        response = requests.get(info_url, timeout=5)
                        
                        if response.status_code == 200:
                            data = response.json()
                            logger.info(f"Successfully got data from {instance}")
                            return self._parse_invidious_response(data, video_id)
                        else:
                            logger.warning(f"{instance} returned {response.status_code}")
                            
                    except requests.exceptions.Timeout:
                        logger.warning(f"{instance} timed out")
                    except requests.exceptions.ConnectionError:
                        logger.warning(f"{instance} connection failed")
                    except Exception as e:
                        logger.warning(f"{instance} error: {e}")
                
                # All instances failed, use fallback
                logger.warning("All Invidious instances failed, using fallback info")
                return self._get_fallback_info(video_id)
            
            # For other platforms (TikTok, Instagram, Twitter, Spotify), use yt-dlp
            else:
                logger.info(f"Analyzing {platform} URL: {url}")
                return self._get_generic_platform_info(url, platform)
            
        except Exception as e:
            logger.error(f"Error getting video info: {str(e)}")
            return {'success': False, 'error': f'Failed to get video info: {str(e)}'}
    
    def _get_generic_platform_info(self, url, platform):
        """Get video info from yt-dlp for non-YouTube platforms, or RapidAPI for Spotify"""
        try:
            import subprocess
            import json
            
            # Handle Spotify with RapidAPI instead of yt-dlp
            if platform == 'spotify':
                return self._get_spotify_info(url)
            
            # For other platforms, use yt-dlp
            # Try without cookies first, as they may not be available
            cmd = ['yt-dlp', '--dump-json', '--no-warnings', url]
            
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
            formats = self._get_available_formats(url)
            
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
    
    def _parse_invidious_response(self, data, video_id):
        """Parse Invidious API response"""
        try:
            title = data.get('title', f'Video {video_id[:8]}...')
            duration = self._format_duration(data.get('length', 0))
            uploader = data.get('author', 'Unknown')
            views = data.get('viewCount', 0)
            
            # Get thumbnail
            thumbnail = f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg'
            
            logger.info(f"Got video info: {title} by {uploader}")
            
            # Get actual available formats from yt-dlp
            formats = self._get_available_formats(f'https://www.youtube.com/watch?v={video_id}')
            
            return {
                'success': True,
                'title': title,
                'duration': duration,
                'thumbnail': thumbnail,
                'uploader': uploader,
                'view_count': views,
                'formats': formats,
                'platform': 'youtube',
                'video_id': video_id
            }
        except Exception as e:
            logger.error(f"Error parsing Invidious response: {e}")
            return self._get_fallback_info(video_id)
    
    def _get_fallback_info(self, video_id):
        """Return basic info when API fails - try to get title from yt-dlp"""
        try:
            import subprocess
            import json
            
            # Try to get video info from yt-dlp
            cmd = ['yt-dlp', '--dump-json', '--no-warnings', f'https://www.youtube.com/watch?v={video_id}']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            title = f'Video {video_id[:8]}...'
            duration = 'Unknown'
            uploader = 'Unknown'
            
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    title = data.get('title', title)
                    # Extract duration in seconds and format it
                    duration_seconds = data.get('duration', 0)
                    if duration_seconds:
                        duration = self._format_duration(duration_seconds)
                    # Extract uploader/channel name
                    uploader = data.get('uploader', data.get('channel', data.get('creator', 'Unknown')))
                    logger.info(f"Got info from yt-dlp: {title} by {uploader} ({duration})")
                except Exception as e:
                    logger.warning(f"Error parsing yt-dlp data: {e}")
        except Exception as e:
            logger.error(f"Error getting fallback info: {e}")
            title = f'Video {video_id[:8]}...'
            duration = 'Unknown'
            uploader = 'Unknown'
        
        # Get actual available formats from yt-dlp
        formats = self._get_available_formats(f'https://www.youtube.com/watch?v={video_id}')
        
        return {
            'success': True,
            'title': title,
            'duration': duration,
            'thumbnail': f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg',
            'uploader': uploader,
            'view_count': 0,
            'formats': formats,
            'platform': 'youtube',
            'video_id': video_id
        }
    
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
    
    def _get_available_formats(self, url):
        """Get actual available formats from yt-dlp"""
        try:
            import subprocess
            import json
            
            # Get format information from yt-dlp
            cmd = ['yt-dlp', '--dump-json', '--no-warnings', url]
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
            
            # For YouTube, check if user has OAuth credentials
            if platform == 'youtube':
                if user_credentials:
                    # Try with OAuth credentials first
                    logger.info("Using OAuth credentials for YouTube download")
                    result = self._download_youtube_oauth(url, quality, media_type, user_credentials)
                    if result.get('success'):
                        return result
                    logger.warning("OAuth download failed, falling back to Invidious")
                
                # Fallback to Invidious
                return self._download_youtube_invidious(url, quality, media_type)
            
            # For other platforms, use standard yt-dlp
            return self._download_generic(url, quality, media_type, platform)
            
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return {'success': False, 'error': f'Download failed: {str(e)}'}
    
    def _download_youtube_oauth(self, url, quality, media_type, credentials):
        """Download YouTube video using OAuth credentials"""
        try:
            import subprocess
            import json
            import tempfile
            
            logger.info(f"Downloading YouTube with OAuth (quality={quality}, type={media_type})")
            
            # Create credentials file for yt-dlp
            creds_dict = {
                'token': credentials['token'],
                'refresh_token': credentials.get('refresh_token'),
                'token_uri': credentials['token_uri'],
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes
            }
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(creds_dict, f)
                creds_file = f.name
            
            # Build yt-dlp command with OAuth
            if media_type == 'audio':
                output_template = os.path.join(self.base_dir, f'%(title)s__audio.%(ext)s')
                cmd = [
                    'yt-dlp',
                    '--no-warnings',
                    '--cookies-from-browser', 'chrome',  # Try to use browser cookies as fallback
                    '-f', 'bestaudio',
                    '-x',
                    '--audio-format', 'mp3',
                    '--audio-quality', '192',
                    '-o', output_template,
                    url
                ]
            else:
                quality_map = {
                    '1440': 'bestvideo[height<=1440]+bestaudio/best[height<=1440]/best',
                    '1080': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
                    '720': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                    '480': 'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                    '360': 'bestvideo[height<=360]+bestaudio/best[height<=360]/best',
                    'best': 'bestvideo+bestaudio/best'
                }
                format_spec = quality_map.get(quality, 'bestvideo+bestaudio/best')
                output_template = os.path.join(self.base_dir, f'%(title)s__{quality}p.%(ext)s')
                
                cmd = [
                    'yt-dlp',
                    '--no-warnings',
                    '--cookies-from-browser', 'chrome',
                    '-f', format_spec,
                    '-o', output_template,
                    url
                ]
            
            logger.info(f"Running yt-dlp with OAuth fallback")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            # Clean up temp file
            try:
                os.remove(creds_file)
            except:
                pass
            
            if result.returncode == 0:
                return self._process_download_result(result, url, platform='youtube', 
                                                    media_type=media_type, quality=quality)
            else:
                error_msg = result.stderr[:500] if result.stderr else 'Unknown error'
                logger.error(f"OAuth download failed: {error_msg}")
                return {'success': False, 'error': 'Failed to download with OAuth'}
                
        except Exception as e:
            logger.error(f"OAuth download error: {str(e)}", exc_info=True)
            return {'success': False, 'error': f'OAuth download failed: {str(e)}'}
    
    def _download_generic(self, url, quality, media_type, platform):
        """Download generic platform content"""
        try:
            import subprocess
            import json
            
            # Build yt-dlp command based on format
            if media_type == 'audio':
                # Download as MP3 audio only with specified quality bitrate
                audio_bitrate_map = {
                    'bestaudio': '192',
                    '192': '192',
                    '128': '128'
                }
                audio_quality = audio_bitrate_map.get(quality, '192')
                
                output_template = os.path.join(self.base_dir, f'%(title)s__{audio_quality}kbps.%(ext)s')
                
                cmd = [
                    'yt-dlp',
                    '--no-warnings',
                    '-f', 'bestaudio',
                    '-x',
                    '--audio-format', 'mp3',
                    '--audio-quality', audio_quality,
                    '-o', output_template,
                    url
                ]
                
                logger.info(f"Downloading audio ({audio_quality} kbps) from {platform}")
                
                # Execute download with bestaudio first
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                
                # If bestaudio fails, try downloading best video and extracting audio
                if result.returncode != 0:
                    logger.warning(f"bestaudio extraction failed, trying fallback")
                    
                    cmd = [
                        'yt-dlp',
                        '--no-warnings',
                        '-f', 'best',
                        '-x',
                        '--audio-format', 'mp3',
                        '--audio-quality', audio_quality,
                        '-o', output_template,
                        url
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            else:
                # Download as video with specified quality
                quality_map = {
                    '1440': 'bestvideo[height<=1440]+bestaudio/best[height<=1440]/best',
                    '1080': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
                    '720': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                    '480': 'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                    '360': 'bestvideo[height<=360]+bestaudio/best[height<=360]/best',
                    'mp4': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'webm': 'bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best',
                    'best': 'bestvideo+bestaudio/best'
                }
                format_spec = quality_map.get(quality, 'bestvideo+bestaudio/best')
                
                if quality == 'mp4':
                    output_template = os.path.join(self.base_dir, f'%(title)s__mp4p.%(ext)s')
                elif quality == 'webm':
                    output_template = os.path.join(self.base_dir, f'%(title)s__webm.%(ext)s')
                else:
                    output_template = os.path.join(self.base_dir, f'%(title)s__{quality}p.%(ext)s')
                
                cmd = [
                    'yt-dlp',
                    '--no-warnings',
                    '-f', format_spec,
                    '-o', output_template,
                    '--quiet',
                    url
                ]
                logger.info(f"Downloading video {quality} from {platform}")
            
            # Execute download
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                return self._process_download_result(result, url, platform=platform, 
                                                    media_type=media_type, quality=quality)
            else:
                error_msg = result.stderr or "Unknown error"
                logger.error(f"Download failed: {error_msg}")
                return {'success': False, 'error': f'Download failed: {error_msg}'}
                
        except subprocess.TimeoutExpired:
            logger.error("Download timed out")
            return {'success': False, 'error': 'Download timed out (>10 minutes)'}
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return {'success': False, 'error': f'Download failed: {str(e)}'}
    
    def _process_download_result(self, result, url, platform, media_type, quality):
        """Process successful download result"""
        try:
            import subprocess
            import json
            
            # Get the title from yt-dlp info
            info_cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-warnings',
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
            if media_type == 'audio':
                expected_extensions = ('.mp3', '.m4a', '.aac', '.opus', '.vorbis')
                audio_bitrate_map = {
                    'bestaudio': '192',
                    '192': '192',
                    '128': '128'
                }
                audio_quality = audio_bitrate_map.get(quality, '192')
                quality_suffix = f"__{audio_quality}kbps"
            else:
                expected_extensions = ('.mp4', '.mkv', '.webm', '.m4a')
                if quality == 'mp4':
                    quality_suffix = '__mp4p'
                elif quality == 'webm':
                    quality_suffix = '__webm'
                else:
                    quality_suffix = f"__{quality}p"
            
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
    
    def _download_youtube_invidious(self, url, quality='720', media_type='video'):
        """Download YouTube video using Invidious API"""
        try:
            import requests
            import re
            import subprocess
            
            # Extract video ID
            video_id_match = re.search(r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})', url)
            if not video_id_match:
                return {'success': False, 'error': 'Invalid YouTube URL'}
            
            video_id = video_id_match.group(1)
            
            # Try multiple Invidious instances
            invidious_instances = [
                os.getenv('INVIDIOUS_INSTANCE', 'https://invidious.io'),
                'https://invidious.io',
                'https://inv.vern.cc',
                'https://invidious.snopyta.org'
            ]
            
            logger.info(f"Downloading YouTube video {video_id} via Invidious")
            
            video_info = None
            working_instance = None
            
            # Try to get video info
            for instance in invidious_instances:
                try:
                    info_url = f"{instance}/api/v1/videos/{video_id}"
                    logger.info(f"Trying Invidious instance: {instance}")
                    
                    response = requests.get(info_url, timeout=10)
                    response.raise_for_status()
                    video_info = response.json()
                    working_instance = instance
                    
                    logger.info(f"Successfully got video info from {instance}")
                    break
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Instance {instance} failed: {str(e)}")
                    continue
            
            if not video_info or not working_instance:
                logger.error("All Invidious instances failed")
                return {'success': False, 'error': 'Unable to access YouTube video'}
            
            title = video_info.get('title', f'Video_{video_id}')
            title = re.sub(r'[<>:"/\\|?*]', '_', title)
            
            logger.info(f"Video title: {title}")
            
            if media_type == 'audio':
                # For audio, use standard yt-dlp
                return self._download_generic(url, quality, media_type, 'youtube')
            else:
                # For video, try direct download from Invidious
                formats = video_info.get('formatStreams', [])
                if not formats:
                    logger.warning("No format streams from Invidious")
                    return self._download_generic(url, quality, media_type, 'youtube')
                
                # Find best format matching quality
                target_quality = int(quality.rstrip('p')) if quality != 'best' else 720
                best_format = None
                
                for fmt in formats:
                    resolution_str = fmt.get('resolution', '')
                    if resolution_str:
                        try:
                            res_height = int(resolution_str.split('p')[0])
                            if best_format is None:
                                best_format = fmt
                            elif res_height <= target_quality:
                                best_format = fmt
                        except:
                            continue
                
                if not best_format:
                    best_format = formats[0]
                
                format_url = best_format.get('url')
                if not format_url:
                    logger.warning("No URL in format stream")
                    return self._download_generic(url, quality, media_type, 'youtube')
                
                try:
                    logger.info(f"Downloading from Invidious URL")
                    
                    video_response = requests.get(format_url, timeout=300, stream=True)
                    video_response.raise_for_status()
                    
                    file_path = os.path.join(self.base_dir, f'{title}__{quality}p.mp4')
                    
                    with open(file_path, 'wb') as f:
                        for chunk in video_response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    file_size = os.path.getsize(file_path)
                    logger.info(f"Video saved to: {file_path} ({file_size} bytes)")
                    
                    return {
                        'success': True,
                        'title': title,
                        'filename': os.path.basename(file_path),
                        'filepath': file_path,
                        'file_size': self.format_file_size(file_size),
                        'download_url': f"/api/file/{os.path.basename(file_path)}",
                        'platform': 'youtube',
                        'media_type': 'video',
                        'quality': quality
                    }
                
                except Exception as e:
                    logger.error(f"Invidious direct download failed: {str(e)}")
                    return self._download_generic(url, quality, media_type, 'youtube')
        
        except Exception as e:
            logger.error(f"YouTube Invidious download error: {str(e)}", exc_info=True)
            return {'success': False, 'error': f'Download failed: {str(e)}'}
    
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
    """Check if user is authenticated with Google OAuth"""
    return 'credentials' in session

def get_user_credentials():
    """Get user credentials from session"""
    if 'credentials' in session:
        creds_dict = session['credentials']
        return google.oauth2.credentials.Credentials(**creds_dict)
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
            'oauth_authorize': '/api/oauth2authorize (GET)',
            'oauth_callback': '/api/oauth2callback (GET)',
            'oauth_status': '/api/oauth2status (GET)',
            'oauth_logout': '/api/oauth2logout (GET)'
        }
    })

@app.route('/api/oauth2authorize')
def authorize():
    """Start OAuth2 authorization flow"""
    try:
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
        
        # Use the frontend URL as redirect for better UX - UPDATED
        frontend_url = request.args.get('redirect_uri', 'https://jaydl.onrender.com')
        flow.redirect_uri = GOOGLE_REDIRECT_URI
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        # Store the state in the session as string to avoid bytes serialization issues
        session['state'] = str(state)
        session['frontend_url'] = str(frontend_url)
        session.modified = True  # Explicitly mark session as modified
        
        logger.info(f"Generated authorization URL for OAuth, state: {state}")
        
        # Return the URL for frontend to redirect to
        return jsonify({
            'success': True,
            'auth_url': authorization_url,
            'state': state,
            'message': 'Redirect user to this URL for authentication'
        })
    
    except Exception as e:
        logger.error(f"Error generating auth URL: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to start authentication: {str(e)}'
        }), 500

@app.route('/api/oauth2callback')
def oauth2callback():
    """OAuth2 callback endpoint"""
    try:
        # Get the state from the request query parameters
        request_state = request.args.get('state')
        session_state = session.get('state')
        
        if not request_state or not session_state:
            logger.error(f"State mismatch: request_state={request_state}, session_state={session_state}")
            return redirect(f"https://jaydl.onrender.com/#oauth_error=invalid_state")
        
        # Convert both to string for comparison
        if str(request_state) != str(session_state):
            logger.error(f"State mismatch: {request_state} != {session_state}")
            return redirect(f"https://jaydl.onrender.com/#oauth_error=state_mismatch")
        
        # Recreate the flow
        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            },
            scopes=SCOPES,
            state=str(session_state)
        )
        
        flow.redirect_uri = GOOGLE_REDIRECT_URI
        
        # Exchange authorization code for credentials
        authorization_response = request.url
        flow.fetch_token(authorization_response=authorization_response)
        
        # Get credentials
        credentials = flow.credentials
        
        # Store credentials in session as strings to avoid serialization issues
        session['credentials'] = {
            'token': str(credentials.token) if credentials.token else None,
            'refresh_token': str(credentials.refresh_token) if credentials.refresh_token else None,
            'token_uri': str(credentials.token_uri) if credentials.token_uri else None,
            'client_id': str(credentials.client_id) if credentials.client_id else None,
            'client_secret': str(credentials.client_secret) if credentials.client_secret else None,
            'scopes': list(credentials.scopes) if credentials.scopes else []
        }
        
        # Clear the state
        session.pop('state', None)
        session.modified = True
        
        logger.info(f"User authenticated successfully via OAuth")
        
        # Redirect back to frontend with success - UPDATED
        return redirect("https://jaydl.onrender.com/#auth_success")
    
    except Exception as e:
        logger.error(f"OAuth callback error: {str(e)}", exc_info=True)
        # UPDATED
        return redirect(f"https://jaydl.onrender.com/#oauth_error={str(e)}")

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

@app.route('/api/oauth2logout')
def oauth_logout():
    """Log out (clear OAuth session)"""
    session.clear()
    logger.info("User logged out")
    return jsonify({
        'success': True,
        'message': 'Logged out successfully'
    })

@app.route('/api/analyze', methods=['POST'])
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
        
        logger.info(f"Analyzing URL: {url}")
        result = downloader.get_video_info(url)
        
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
        
        logger.info(f"Downloading: {url} | Quality: {quality} | Type: {media_type}")
        
        # Get user credentials if authenticated
        user_credentials = None
        if is_authenticated():
            user_credentials = session['credentials']
        
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
            
            # Check if authentication is needed (for YouTube)
            if url.lower().count('youtube') > 0 and not is_authenticated():
                result['auth_suggestion'] = {
                    'message': 'For better YouTube download success, consider authenticating with Google',
                    'auth_url': '/api/oauth2authorize'
                }
        else:
            logger.error(f"Download failed: {result.get('error', 'Unknown error')}")
            
            # Check if it's an authentication error for YouTube
            if url.lower().count('youtube') > 0 and 'private' in result.get('error', '').lower():
                result['need_auth'] = True
                result['auth_url'] = '/api/oauth2authorize'
        
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
            'requires_auth': True,
            'auth_type': 'oauth'
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
            'rate_limited': True
        }
    ]
    
    return jsonify({
        'success': True,
        'platforms': platforms
    })

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

if __name__ == '__main__':
    # Get port from environment variable or default to 5000
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'production') == 'development'
    
    logger.info(f"Starting JayDL Backend on port {port}")
    logger.info(f"Debug mode: {debug}")
    logger.info(f"Download directory: {DOWNLOAD_DIR}")
    logger.info(f"OAuth configured: {bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)}")
    
    app.run(debug=debug, host='0.0.0.0', port=port)