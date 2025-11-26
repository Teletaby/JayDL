import yt_dlp
import os
import subprocess
import logging
import requests
import random
import time
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class JayDLDownloader:
    def __init__(self):
        # Use local downloads directory
        self.base_dir = os.path.join(os.path.expanduser('~'), 'JayDL_Downloads')
        self.setup_directories()
        print(f"Download directory: {self.base_dir}")
        
        # List of Invidious instances (public APIs)
        self.invidious_instances = [
            'https://vid.puffyan.us',
            'https://inv.tux.pizza',
            'https://invidious.nerdvpn.de',
            'https://yt.artemislena.eu',
            'https://invidious.lidarshield.cloud',
            'https://yewtu.be',
            'https://invidious.privacydev.net',
            'https://inv.nadeko.net'
        ]
        
        # Rotating user agents to appear more like real browsers
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
        ]
    
    def setup_directories(self):
        """Create necessary directories"""
        directories = ['videos', 'music', 'temp']
        for dir_name in directories:
            dir_path = os.path.join(self.base_dir, dir_name)
            os.makedirs(dir_path, exist_ok=True)
            print(f"Created directory: {dir_path}")
    
    def detect_platform(self, url: str) -> str:
        """Detect which platform the URL is from"""
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        elif 'spotify.com' in url:
            return 'spotify'
        elif 'tiktok.com' in url:
            return 'tiktok'
        elif 'instagram.com' in url:
            return 'instagram'
        elif 'twitter.com' in url or 'x.com' in url:
            return 'twitter'
        else:
            return 'generic'
    
    def extract_youtube_id(self, url: str) -> str:
        """Extract YouTube video ID from URL"""
        import re
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&?\n]+)',
            r'youtube\.com\/embed\/([^&?\n]+)',
            r'youtube\.com\/v\/([^&?\n]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def get_video_info_via_invidious(self, url: str) -> Dict[str, Any]:
        """Get video info using Invidious API to bypass restrictions"""
        video_id = self.extract_youtube_id(url)
        if not video_id:
            return {'success': False, 'error': 'Could not extract YouTube video ID'}
        
        # Shuffle instances for load balancing
        instances = self.invidious_instances.copy()
        random.shuffle(instances)
        
        # Try different Invidious instances
        for instance in instances:
            try:
                api_url = f"{instance}/api/v1/videos/{video_id}"
                print(f"Trying Invidious instance: {instance}")
                
                headers = {
                    'User-Agent': random.choice(self.user_agents)
                }
                
                response = requests.get(api_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    
                    # Format the response to match our expected structure
                    formats = []
                    if 'formatStreams' in data:
                        for stream in data['formatStreams']:
                            if 'quality' in stream:
                                formats.append({
                                    'format_id': stream.get('itag', 'unknown'),
                                    'resolution': stream['quality'],
                                    'height': self.parse_resolution(stream['quality']),
                                    'filesize': 'Unknown',
                                    'format': f"{stream['quality']} - {stream.get('type', 'unknown')}"
                                })
                    
                    return {
                        'success': True,
                        'title': data.get('title', 'Unknown'),
                        'duration': self.format_duration(data.get('lengthSeconds', 0)),
                        'thumbnail': data.get('videoThumbnails', [{}])[0].get('url', ''),
                        'view_count': data.get('viewCount', 0),
                        'uploader': data.get('author', 'Unknown'),
                        'formats': formats,
                        'platform': 'youtube',
                        'source': 'invidious'
                    }
                    
            except Exception as e:
                print(f"Invidious instance {instance} failed: {e}")
                continue
        
        return {'success': False, 'error': 'All Invidious instances failed'}
    
    def download_via_invidious(self, url: str, quality: str = 'best', media_type: str = 'video') -> Dict[str, Any]:
        """Download video directly from Invidious"""
        video_id = self.extract_youtube_id(url)
        if not video_id:
            return {'success': False, 'error': 'Could not extract YouTube video ID'}
        
        # Shuffle instances
        instances = self.invidious_instances.copy()
        random.shuffle(instances)
        
        for instance in instances:
            try:
                api_url = f"{instance}/api/v1/videos/{video_id}"
                print(f"Trying to download via Invidious: {instance}")
                
                headers = {
                    'User-Agent': random.choice(self.user_agents)
                }
                
                response = requests.get(api_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    
                    # Get the appropriate stream
                    if media_type == 'audio':
                        streams = data.get('adaptiveFormats', [])
                        audio_stream = None
                        for stream in streams:
                            if stream.get('type', '').startswith('audio'):
                                audio_stream = stream
                                break
                        
                        if not audio_stream:
                            continue
                        
                        download_url = audio_stream.get('url')
                    else:
                        # Get video stream
                        streams = data.get('formatStreams', [])
                        if not streams:
                            continue
                        
                        # Find best matching quality
                        quality_map = {
                            '4k': 2160,
                            '1440p': 1440,
                            '1080p': 1080,
                            '720p': 720,
                            '480p': 480,
                            'best': 9999
                        }
                        target_height = quality_map.get(quality, 9999)
                        
                        best_stream = None
                        for stream in streams:
                            stream_quality = stream.get('quality', '')
                            stream_height = self.parse_resolution(stream_quality)
                            
                            if stream_height <= target_height:
                                if not best_stream or stream_height > self.parse_resolution(best_stream.get('quality', '')):
                                    best_stream = stream
                        
                        if not best_stream:
                            best_stream = streams[0]  # Fallback to first available
                        
                        download_url = best_stream.get('url')
                    
                    if not download_url:
                        continue
                    
                    # Download the file
                    title = data.get('title', 'video').replace('/', '_').replace('\\', '_')
                    ext = 'mp4' if media_type == 'video' else 'webm'
                    folder = 'videos' if media_type == 'video' else 'music'
                    filename = f"{title}.{ext}"
                    filepath = os.path.join(self.base_dir, folder, filename)
                    
                    print(f"Downloading: {title}")
                    file_response = requests.get(download_url, headers=headers, stream=True, timeout=60)
                    
                    if file_response.status_code == 200:
                        with open(filepath, 'wb') as f:
                            for chunk in file_response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        
                        # Convert audio to mp3 if needed
                        if media_type == 'audio':
                            mp3_filepath = filepath.rsplit('.', 1)[0] + '.mp3'
                            try:
                                subprocess.run([
                                    'ffmpeg', '-i', filepath, '-codec:a', 'libmp3lame',
                                    '-qscale:a', '2', mp3_filepath, '-y'
                                ], check=True, capture_output=True)
                                os.remove(filepath)
                                filepath = mp3_filepath
                                filename = os.path.basename(mp3_filepath)
                            except:
                                print("FFmpeg conversion failed, keeping original format")
                        
                        file_size = self.format_file_size(os.path.getsize(filepath))
                        print(f"Download completed: {filename} ({file_size})")
                        
                        return {
                            'success': True,
                            'filename': filename,
                            'title': title,
                            'duration': self.format_duration(data.get('lengthSeconds', 0)),
                            'filepath': filepath,
                            'platform': 'youtube',
                            'media_type': media_type,
                            'file_size': file_size,
                            'method': 'invidious'
                        }
                    
            except Exception as e:
                print(f"Invidious download failed on {instance}: {e}")
                continue
        
        return {'success': False, 'error': 'All Invidious instances failed to download'}
    
    def parse_resolution(self, quality: str) -> int:
        """Parse resolution from quality string"""
        if '2160' in quality or '4K' in quality:
            return 2160
        elif '1440' in quality:
            return 1440
        elif '1080' in quality:
            return 1080
        elif '720' in quality:
            return 720
        elif '480' in quality:
            return 480
        elif '360' in quality:
            return 360
        elif '240' in quality:
            return 240
        return 0
    
    def get_video_info(self, url: str) -> Dict[str, Any]:
        """Get available formats and info for a video"""
        platform = self.detect_platform(url)
        
        # For YouTube, try Invidious first, fallback to yt-dlp
        if platform == 'youtube':
            invidious_result = self.get_video_info_via_invidious(url)
            if invidious_result['success']:
                print("Successfully got info via Invidious")
                return invidious_result
            else:
                print("Invidious failed, falling back to yt-dlp")
        
        # Fallback to yt-dlp for other platforms or if Invidious fails
        ydl_opts = {
            'quiet': True,
            'no_warnings': False,
            'extract_flat': False,
            'user_agent': random.choice(self.user_agents),
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Extract available formats
                formats = []
                for f in info.get('formats', []):
                    if f.get('filesize') or f.get('filesize_approx'):
                        format_info = {
                            'format_id': f['format_id'],
                            'ext': f.get('ext', 'unknown'),
                            'resolution': f.get('format_note', 'unknown'),
                            'height': f.get('height', 0),
                            'width': f.get('width', 0),
                            'filesize': self.format_file_size(f.get('filesize') or f.get('filesize_approx', 0)),
                            'format': f['format']
                        }
                        # Only add unique resolutions
                        if format_info['height'] > 0 and not any(f['height'] == format_info['height'] for f in formats):
                            formats.append(format_info)
                
                # Sort formats by resolution
                formats.sort(key=lambda x: x['height'], reverse=True)
                
                return {
                    'success': True,
                    'title': info.get('title', 'Unknown'),
                    'duration': self.format_duration(info.get('duration', 0)),
                    'thumbnail': info.get('thumbnail', ''),
                    'view_count': info.get('view_count', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'formats': formats,
                    'platform': platform
                }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def format_file_size(self, size_bytes):
        """Format file size to human readable format"""
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names)-1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.2f} {size_names[i]}"
    
    def format_duration(self, seconds):
        """Format duration from seconds to HH:MM:SS"""
        if not seconds:
            return "Unknown"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    
    def download_media(self, url: str, quality: str = 'best', media_type: str = 'video') -> Dict[str, Any]:
        """Download media from various platforms with multiple fallback strategies"""
        platform = self.detect_platform(url)
        
        try:
            if platform == 'spotify':
                return self.download_spotify(url)
            elif platform == 'youtube':
                # For YouTube, try multiple methods in order
                print("Attempting YouTube download with fallback strategies...")
                
                # Strategy 1: Try Invidious direct download
                print("\n[Strategy 1] Trying Invidious direct download...")
                result = self.download_via_invidious(url, quality, media_type)
                if result['success']:
                    return result
                print("Invidious download failed, trying next strategy...")
                
                # Small delay between attempts
                time.sleep(1)
                
                # Strategy 2: Try yt-dlp with enhanced options
                print("\n[Strategy 2] Trying yt-dlp with anti-bot measures...")
                result = self.download_with_ytdlp_enhanced(url, quality, media_type, platform)
                if result['success']:
                    return result
                print("yt-dlp enhanced failed, trying next strategy...")
                
                # Strategy 3: Try yt-dlp with basic options
                print("\n[Strategy 3] Trying yt-dlp basic mode...")
                result = self.download_with_ytdlp(url, quality, media_type, platform)
                if result['success']:
                    return result
                
                # All strategies failed
                return {
                    'success': False,
                    'error': 'All download strategies failed. YouTube may be blocking automated downloads. Try again later or use a different video.'
                }
            else:
                return self.download_with_ytdlp(url, quality, media_type, platform)
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_ytdlp_options(self, url: str, quality: str, media_type: str, platform: str):
        """Get optimized yt-dlp options"""
        if media_type == 'audio':
            return {
                'outtmpl': os.path.join(self.base_dir, 'music', '%(title)s.%(ext)s'),
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }],
                'user_agent': random.choice(self.user_agents),
            }
        else:
            if platform in ['tiktok', 'instagram']:
                format_spec = 'best'
            else:
                quality_map = {
                    '4k': 'bestvideo[height<=2160]+bestaudio/best[height<=2160]',
                    '1440p': 'bestvideo[height<=1440]+bestaudio/best[height<=1440]',
                    '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
                    '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
                    '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
                    'best': 'best'
                }
                format_spec = quality_map.get(quality, 'best')
            
            return {
                'outtmpl': os.path.join(self.base_dir, 'videos', '%(title)s.%(ext)s'),
                'format': format_spec,
                'merge_output_format': 'mp4',
                'user_agent': random.choice(self.user_agents),
            }
    
    def download_with_ytdlp_enhanced(self, url: str, quality: str, media_type: str, platform: str) -> Dict[str, Any]:
        """Download using yt-dlp with enhanced anti-bot options"""
        try:
            ydl_opts = self.get_ytdlp_options(url, quality, media_type, platform)
            
            # Add enhanced anti-bot options
            ydl_opts.update({
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'player_skip': ['webpage', 'configs'],
                    }
                },
                'sleep_interval': 1,
                'max_sleep_interval': 3,
                'http_headers': {
                    'User-Agent': random.choice(self.user_agents),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Sec-Fetch-Mode': 'navigate',
                }
            })
            
            print(f"Downloading with enhanced options: {url}")
            print(f"Platform: {platform}, Quality: {quality}, Type: {media_type}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                if media_type == 'audio':
                    filename = filename.rsplit('.', 1)[0] + '.mp3'
                
                file_size = self.format_file_size(os.path.getsize(filename)) if os.path.exists(filename) else 'Unknown'
                print(f"Download completed: {filename} ({file_size})")
                
                return {
                    'success': True,
                    'filename': os.path.basename(filename),
                    'title': info.get('title', 'Unknown'),
                    'duration': self.format_duration(info.get('duration', 0)),
                    'filepath': filename,
                    'platform': platform,
                    'media_type': media_type,
                    'file_size': file_size,
                    'method': 'yt-dlp-enhanced'
                }
                
        except Exception as e:
            print(f"Enhanced download failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def download_with_ytdlp(self, url: str, quality: str, media_type: str, platform: str) -> Dict[str, Any]:
        """Download using yt-dlp basic mode"""
        try:
            ydl_opts = self.get_ytdlp_options(url, quality, media_type, platform)
            
            print(f"Downloading: {url}")
            print(f"Platform: {platform}, Quality: {quality}, Type: {media_type}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                if media_type == 'audio':
                    filename = filename.rsplit('.', 1)[0] + '.mp3'
                
                file_size = self.format_file_size(os.path.getsize(filename)) if os.path.exists(filename) else 'Unknown'
                print(f"Download completed: {filename} ({file_size})")
                
                return {
                    'success': True,
                    'filename': os.path.basename(filename),
                    'title': info.get('title', 'Unknown'),
                    'duration': self.format_duration(info.get('duration', 0)),
                    'filepath': filename,
                    'platform': platform,
                    'media_type': media_type,
                    'file_size': file_size,
                    'method': 'yt-dlp-basic'
                }
                
        except Exception as e:
            print(f"Download failed: {e}")
            
            error_msg = str(e)
            if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
                error_msg = "YouTube is blocking automated downloads. All fallback methods failed."
            elif 'format is not available' in error_msg:
                error_msg += " Try selecting a different quality."
            
            return {'success': False, 'error': error_msg}
    
    def download_spotify(self, url: str) -> Dict[str, Any]:
        """Download Spotify music"""
        try:
            print(f"Downloading Spotify: {url}")
            
            cmd = [
                'spotdl',
                'download',
                url,
                '--output',
                os.path.join(self.base_dir, 'music', '{title}.{ext}')
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.base_dir, timeout=300)
            
            if result.returncode == 0:
                for file in os.listdir(os.path.join(self.base_dir, 'music')):
                    if file.endswith('.mp3'):
                        file_path = os.path.join(self.base_dir, 'music', file)
                        file_size = self.format_file_size(os.path.getsize(file_path))
                        print(f"Spotify download completed: {file} ({file_size})")
                        
                        return {
                            'success': True,
                            'filename': file,
                            'title': file.rsplit('.', 1)[0],
                            'filepath': file_path,
                            'platform': 'spotify',
                            'media_type': 'audio',
                            'file_size': file_size
                        }
                return {'success': True, 'message': 'Spotify download completed'}
            else:
                print(f"Spotify download failed: {result.stderr}")
                return {'success': False, 'error': result.stderr}
                
        except Exception as e:
            print(f"Spotify download error: {e}")
            return {'success': False, 'error': str(e)}  