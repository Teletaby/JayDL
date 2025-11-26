import yt_dlp
import os
import subprocess
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class JayDLDownloader:
    def __init__(self):
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
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'youtube'
        elif 'spotify.com' in url_lower:
            return 'spotify'
        elif 'tiktok.com' in url_lower:
            return 'tiktok'
        elif 'instagram.com' in url_lower:
            return 'instagram'
        elif 'twitter.com' in url_lower or 'x.com' in url_lower:
            return 'twitter'
        else:
            return 'generic'
    
    def get_video_info(self, url: str) -> Dict[str, Any]:
        """Get video info with platform-specific handling"""
        platform = self.detect_platform(url)
        
        # For YouTube, provide basic info without trying to extract
        if platform == 'youtube':
            return self._get_basic_youtube_info(url)
        
        # For other platforms, try to get real info
        return self._get_info_direct(url, platform)
    
    def _get_basic_youtube_info(self, url: str) -> Dict[str, Any]:
        """Provide basic YouTube info without triggering bot detection"""
        import re
        
        # Extract video ID for thumbnail
        video_id = None
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&?\n]+)',
            r'youtube\.com\/embed\/([^&?\n]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break
        
        return {
            'success': True,
            'title': 'YouTube Video (Click Download to try)',
            'duration': 'Unknown',
            'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg' if video_id else '',
            'uploader': 'YouTube',
            'formats': [
                {
                    'format_id': 'best',
                    'resolution': 'Best Available',
                    'height': 1080,
                    'filesize': 'Unknown',
                    'format': 'best'
                }
            ],
            'platform': 'youtube',
            'note': 'YouTube may block downloads due to restrictions'
        }
    
    def _get_info_direct(self, url: str, platform: str) -> Dict[str, Any]:
        """Get info for non-YouTube platforms"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return self._format_info(info, platform)
        except Exception as e:
            return {
                'success': False, 
                'error': f'Failed to get info: {str(e)}',
                'platform': platform
            }
    
    def _format_info(self, info, platform: str) -> Dict[str, Any]:
        """Format yt-dlp info to our structure"""
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
                if format_info['height'] > 0 and not any(f['height'] == format_info['height'] for f in formats):
                    formats.append(format_info)
        
        formats.sort(key=lambda x: x['height'], reverse=True)
        
        # If no formats found, add a default
        if not formats:
            formats.append({
                'format_id': 'best',
                'resolution': 'Best Available',
                'height': 1080,
                'filesize': 'Unknown',
                'format': 'best'
            })
        
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
    
    def download_media(self, url: str, quality: str = 'best', media_type: str = 'video') -> Dict[str, Any]:
        """Download media with platform-specific handling"""
        platform = self.detect_platform(url)
        
        print(f"Download request: {platform} - {quality} - {media_type}")
        
        if platform == 'spotify':
            return self.download_spotify(url)
        elif platform == 'youtube':
            return self._handle_youtube_download(url, quality, media_type)
        else:
            return self._download_with_ytdlp(url, quality, media_type, platform)
    
    def _handle_youtube_download(self, url: str, quality: str, media_type: str) -> Dict[str, Any]:
        """Handle YouTube downloads with clear messaging"""
        try:
            # Try a simple download first
            result = self._download_with_ytdlp(url, quality, media_type, 'youtube')
            if result['success']:
                return result
            else:
                # If download fails, provide helpful message
                return {
                    'success': False,
                    'error': 'YouTube is currently blocking downloads. This is a known limitation. Try using other platforms like TikTok, Instagram, or Spotify which work better.',
                    'platform': 'youtube'
                }
        except Exception as e:
            return {
                'success': False,
                'error': f'YouTube download failed: {str(e)}. Try other platforms.',
                'platform': 'youtube'
            }
    
    def _download_with_ytdlp(self, url: str, quality: str, media_type: str, platform: str) -> Dict[str, Any]:
        """Download using yt-dlp with simple options"""
        try:
            if media_type == 'audio':
                ydl_opts = {
                    'outtmpl': os.path.join(self.base_dir, 'music', '%(title)s.%(ext)s'),
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                    }],
                }
            else:
                # Simple format selection
                format_spec = 'best'
                if platform == 'youtube':
                    format_spec = 'best[height<=720]'  # Lower quality for YouTube
                
                ydl_opts = {
                    'outtmpl': os.path.join(self.base_dir, 'videos', '%(title)s.%(ext)s'),
                    'format': format_spec,
                }
            
            print(f"Attempting download with options: {ydl_opts}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                if media_type == 'audio' and not filename.endswith('.mp3'):
                    filename = filename.rsplit('.', 1)[0] + '.mp3'
                
                if os.path.exists(filename):
                    file_size = self.format_file_size(os.path.getsize(filename))
                    print(f"Download successful: {filename} ({file_size})")
                    
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
                else:
                    return {'success': False, 'error': 'Download completed but file not found'}
                    
        except Exception as e:
            error_msg = str(e)
            print(f"Download error: {error_msg}")
            return {'success': False, 'error': error_msg, 'platform': platform}
    
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
                return {'success': False, 'error': result.stderr}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def format_file_size(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names)-1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.2f} {size_names[i]}"
    
    def format_duration(self, seconds):
        if not seconds:
            return "Unknown"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"