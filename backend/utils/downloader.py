import yt_dlp
import os
import subprocess
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class JayDLDownloader:
    def __init__(self):
        # Use local downloads directory
        self.base_dir = os.path.join(os.path.expanduser('~'), 'JayDL_Downloads')
        self.setup_directories()
        print(f"Download directory: {self.base_dir}")
    
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
    
    def get_video_info(self, url: str) -> Dict[str, Any]:
        """Get available formats and info for a video"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': False,
            'extract_flat': False,
            
            # Advanced anti-bot settings
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': 'https://www.youtube.com/',
            
            # Retry settings
            'retries': 15,
            'fragment_retries': 15,
            'skip_unavailable_fragments': True,
            'ignoreerrors': True,
            'no_check_certificate': True,
            
            # YouTube specific settings
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'webpage', 'js']
                }
            },
            
            # HTTP headers
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
            }
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
                    'platform': self.detect_platform(url)
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
        """Download media from various platforms"""
        platform = self.detect_platform(url)
        
        try:
            if platform == 'spotify':
                return self.download_spotify(url)
            else:
                return self.download_with_ytdlp(url, quality, media_type, platform)
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_ytdlp_options(self, url: str, quality: str, media_type: str, platform: str):
        """Get optimized yt-dlp options for each platform"""
        # Base options for all platforms
        base_opts = {
            'quiet': False,
            'no_warnings': False,
            
            # Enhanced anti-bot settings
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': 'https://www.youtube.com/',
            
            # Retry and error handling
            'retries': 20,
            'fragment_retries': 20,
            'skip_unavailable_fragments': True,
            'ignoreerrors': True,
            'no_check_certificate': True,
            
            # YouTube specific optimizations
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'webpage', 'js'],
                    'throttled_rate': '100K'
                }
            },
            
            # HTTP settings
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Upgrade-Insecure-Requests': '1',
            },
            
            # Rate limiting to avoid detection
            'ratelimit': 1048576,  # 1 MB/s
            'throttledratelimit': 524288,  # 512 KB/s
        }
        
        if media_type == 'audio':
            base_opts.update({
                'outtmpl': os.path.join(self.base_dir, 'music', '%(title)s.%(ext)s'),
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }],
            })
        else:
            # Platform-specific format handling
            if platform == 'tiktok':
                format_spec = 'best'
            elif platform == 'instagram':
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
            
            base_opts.update({
                'outtmpl': os.path.join(self.base_dir, 'videos', '%(title)s.%(ext)s'),
                'format': format_spec,
                'merge_output_format': 'mp4',
            })
            
            # Platform-specific headers
            if platform == 'tiktok':
                base_opts['http_headers'].update({
                    'Referer': 'https://www.tiktok.com/',
                    'Origin': 'https://www.tiktok.com',
                })
            elif platform == 'instagram':
                base_opts['http_headers'].update({
                    'Referer': 'https://www.instagram.com/',
                    'Origin': 'https://www.instagram.com',
                })
            elif platform == 'twitter':
                base_opts['http_headers'].update({
                    'Referer': 'https://twitter.com/',
                    'Origin': 'https://twitter.com',
                })
        
        return base_opts
    
    def download_with_ytdlp(self, url: str, quality: str, media_type: str, platform: str) -> Dict[str, Any]:
        """Download using yt-dlp for various platforms"""
        try:
            ydl_opts = self.get_ytdlp_options(url, quality, media_type, platform)
            
            print(f"Downloading: {url}")
            print(f"Platform: {platform}, Quality: {quality}, Type: {media_type}")
            print(f"Using enhanced anti-bot configuration...")
            
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
                    'file_size': file_size
                }
                
        except Exception as e:
            print(f"Download failed: {e}")
            
            # Enhanced error handling with specific suggestions
            error_msg = str(e)
            if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
                error_msg += ". YouTube is blocking automated downloads. Try: 1) Using a different video, 2) Waiting a few hours, 3) Using the 'Best Available' quality."
            elif 'format is not available' in error_msg:
                error_msg += ". Try selecting a different quality or use 'Best Available'."
            elif 'sigi state' in error_msg:
                error_msg += ". TikTok extraction issue - try again later or use a different URL."
            elif 'Private video' in error_msg:
                error_msg += ". This video is private and cannot be downloaded."
            elif 'Video unavailable' in error_msg:
                error_msg += ". This video is not available."
            elif 'HTTP Error 429' in error_msg:
                error_msg += ". Too many requests - please wait before trying again."
            
            return {'success': False, 'error': error_msg}
    
    def download_spotify(self, url: str) -> Dict[str, Any]:
        """Download Spotify music"""
        try:
            print(f"Downloading Spotify: {url}")
            
            # Using spotdl through command line
            cmd = [
                'spotdl',
                'download',
                url,
                '--output',
                os.path.join(self.base_dir, 'music', '{title}.{ext}')
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.base_dir, timeout=300)
            
            if result.returncode == 0:
                # Find the downloaded file
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
                
        except subprocess.TimeoutExpired:
            error_msg = 'Download timed out'
            print(f"Error: {error_msg}")
            return {'success': False, 'error': error_msg}
        except Exception as e:
            print(f"Spotify download error: {e}")
            return {'success': False, 'error': str(e)}