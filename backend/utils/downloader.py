import os
import yt_dlp
import requests
import json
from urllib.parse import urlparse
import tempfile

class JayDLDownloader:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or tempfile.gettempdir()
        self.ensure_directories()
        
    def ensure_directories(self):
        """Ensure necessary directories exist"""
        os.makedirs(self.base_dir, exist_ok=True)
    
    def get_base_ydl_opts(self):
        """Get base yt-dlp options optimized for public hosting"""
        opts = {
            'quiet': False,
            'no_warnings': True,
            # Use different player clients to avoid bot detection
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['webpage', 'configs'],
                }
            },
            # Additional options to bypass restrictions
            'nocheckcertificate': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            # Retry options
            'retries': 3,
            'fragment_retries': 3,
        }
        
        return opts
    
    def get_video_info(self, url):
        """Get information about the video with multiple fallback strategies"""
        strategies = [
            {'player_client': ['android', 'web']},
            {'player_client': ['ios', 'web']},
            {'player_client': ['mweb', 'web']},
        ]
        
        last_error = None
        
        for strategy in strategies:
            try:
                ydl_opts = self.get_base_ydl_opts()
                ydl_opts['extractor_args']['youtube'] = strategy
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    formats = []
                    if 'formats' in info:
                        for fmt in info['formats']:
                            if fmt.get('height'):
                                formats.append({
                                    'format_id': fmt.get('format_id'),
                                    'resolution': f"{fmt.get('height')}p",
                                    'height': fmt.get('height'),
                                    'filesize': self.format_file_size(fmt.get('filesize')),
                                    'format': f"{fmt.get('height')}p - {fmt.get('format_note', '')}"
                                })
                    
                    # Remove duplicates and sort by resolution
                    unique_formats = []
                    seen_resolutions = set()
                    for fmt in sorted(formats, key=lambda x: x['height'], reverse=True):
                        if fmt['resolution'] not in seen_resolutions:
                            seen_resolutions.add(fmt['resolution'])
                            unique_formats.append(fmt)
                    
                    # Add audio option
                    unique_formats.append({
                        'format_id': 'bestaudio',
                        'resolution': 'Audio Only',
                        'height': 0,
                        'filesize': 'Unknown',
                        'format': 'bestaudio'
                    })
                    
                    return {
                        'success': True,
                        'title': info.get('title', 'Unknown'),
                        'duration': self.format_duration(info.get('duration')),
                        'thumbnail': info.get('thumbnail'),
                        'uploader': info.get('uploader', 'Unknown'),
                        'view_count': info.get('view_count', 0),
                        'formats': unique_formats,
                        'platform': self.detect_platform(url)
                    }
            
            except Exception as e:
                last_error = str(e)
                continue  # Try next strategy
        
        # All strategies failed
        error_msg = last_error or "Unknown error"
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            error_msg = "YouTube bot detection triggered. This video may be age-restricted or require authentication. Try another video."
        
        return {
            'success': False,
            'error': error_msg
        }
    
    def download_media(self, url, quality='best', media_type='video'):
        """Download media from URL with fallback strategies"""
        strategies = [
            {'player_client': ['android', 'web']},
            {'player_client': ['ios', 'web']},
            {'player_client': ['mweb', 'web']},
        ]
        
        last_error = None
        
        for strategy in strategies:
            try:
                # Configure yt-dlp options based on media type
                ydl_opts = self.get_base_ydl_opts()
                ydl_opts['extractor_args']['youtube'] = strategy
                ydl_opts['outtmpl'] = os.path.join(self.base_dir, '%(title)s.%(ext)s')
                
                if media_type == 'audio':
                    ydl_opts.update({
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                    })
                else:
                    if quality == 'best':
                        ydl_opts['format'] = 'best'
                    elif quality == 'audio':
                        ydl_opts['format'] = 'bestaudio/best'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }]
                    else:
                        # For specific quality, try to get the best video with that resolution or lower
                        ydl_opts['format'] = f'best[height<={quality.replace("p", "")}]'
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info)
                    
                    # Handle audio extraction
                    if media_type == 'audio' or quality == 'audio':
                        filename = filename.rsplit('.', 1)[0] + '.mp3'
                    
                    return {
                        'success': True,
                        'title': info.get('title', 'Unknown'),
                        'filename': os.path.basename(filename),
                        'filepath': filename,
                        'file_size': self.format_file_size(os.path.getsize(filename)),
                        'platform': self.detect_platform(url),
                        'media_type': media_type
                    }
            
            except Exception as e:
                last_error = str(e)
                continue  # Try next strategy
        
        # All strategies failed
        error_msg = last_error or "Unknown error"
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            error_msg = "YouTube bot detection triggered. This video may be age-restricted. Try another video."
        
        return {
            'success': False,
            'error': error_msg
        }
    
    def detect_platform(self, url):
        """Detect the platform from URL"""
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
    
    def format_duration(self, seconds):
        """Format duration in seconds to HH:MM:SS"""
        if not seconds:
            return "Unknown"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"
    
    def format_file_size(self, bytes_size):
        """Format file size in human readable format"""
        if not bytes_size:
            return "Unknown"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} TB"