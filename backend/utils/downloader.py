import os
import requests
import tempfile
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class RapidAPIDownloader:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or tempfile.gettempdir()
        self.ensure_directories()
        
        # Your RapidAPI credentials
        self.api_key = "aeOfcs43b0msh12c1ac12ff2064ep1009f9jsn43915272a236"
        self.api_host = "all-media-downloader1.p.rapidapi.com"
        self.base_url = f"https://{self.api_host}/all"
        
    def ensure_directories(self):
        os.makedirs(self.base_dir, exist_ok=True)
    
    def get_video_info(self, url):
        """Get video information using RapidAPI"""
        try:
            # Prepare the request
            payload = f"url={url}"
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-RapidAPI-Key': self.api_key,
                'X-RapidAPI-Host': self.api_host
            }
            
            logger.info(f"Calling RapidAPI for URL: {url}")
            
            # Make API request
            response = requests.post(self.base_url, data=payload, headers=headers, timeout=30)
            response_data = response.json()
            
            logger.info(f"RapidAPI response: {response.status_code}")
            
            if response.status_code == 200:
                return self._parse_api_response(response_data, url)
            else:
                error_msg = response_data.get('message', 'API request failed')
                return {'success': False, 'error': f'API Error: {error_msg}'}
                
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'API request timed out'}
        except requests.exceptions.RequestException as e:
            return {'success': False, 'error': f'Network error: {str(e)}'}
        except Exception as e:
            logger.error(f"RapidAPI error: {str(e)}")
            return {'success': False, 'error': f'Service error: {str(e)}'}
    
    def _parse_api_response(self, data, original_url):
        """Parse the RapidAPI response"""
        try:
            # Extract available formats
            formats = []
            
            # Check for video formats
            if data.get('video'):
                video_data = data['video']
                for quality, info in video_data.items():
                    if isinstance(info, dict) and info.get('url'):
                        formats.append({
                            'format_id': quality,
                            'resolution': quality.upper(),
                            'height': self._get_height_from_quality(quality),
                            'filesize': 'Unknown',  # API might not provide size
                            'format': f"{quality.upper()} - Video",
                            'type': 'video',
                            'url': info['url']
                        })
            
            # Check for audio format
            if data.get('audio') and data['audio'].get('url'):
                formats.append({
                    'format_id': 'audio',
                    'resolution': 'Audio',
                    'height': 0,
                    'filesize': 'Unknown',
                    'format': 'Audio Only',
                    'type': 'audio',
                    'url': data['audio']['url']
                })
            
            # If no specific formats, create a default one
            if not formats and data.get('download_url'):
                formats.append({
                    'format_id': 'default',
                    'resolution': 'Best',
                    'height': 1080,
                    'filesize': 'Unknown',
                    'format': 'Best Quality',
                    'type': 'video',
                    'url': data['download_url']
                })
            
            # Get basic info
            title = data.get('title', 'Unknown Title')
            thumbnail = data.get('thumbnail')
            duration = data.get('duration', 'Unknown')
            
            return {
                'success': True,
                'title': title,
                'duration': duration,
                'thumbnail': thumbnail,
                'uploader': data.get('author', 'Unknown'),
                'view_count': 0,  # API might not provide this
                'formats': formats,
                'platform': self.detect_platform(original_url),
                'api_data': data  # Include full API response for debugging
            }
            
        except Exception as e:
            logger.error(f"Error parsing API response: {str(e)}")
            return {'success': False, 'error': f'Failed to parse API response: {str(e)}'}
    
    def download_media(self, url, quality='best', media_type='video'):
        """Download media using RapidAPI"""
        try:
            # First get video info to get download URLs
            info_result = self.get_video_info(url)
            if not info_result['success']:
                return info_result
            
            # Find the appropriate format
            download_url = None
            format_info = None
            
            if media_type == 'audio':
                # Look for audio format
                for fmt in info_result['formats']:
                    if fmt.get('type') == 'audio':
                        download_url = fmt.get('url')
                        format_info = fmt
                        break
            else:
                # Look for video format
                if quality == 'best':
                    # Get the first available video format
                    for fmt in info_result['formats']:
                        if fmt.get('type') == 'video':
                            download_url = fmt.get('url')
                            format_info = fmt
                            break
                else:
                    # Look for specific quality
                    for fmt in info_result['formats']:
                        if fmt.get('resolution', '').lower() == quality.lower():
                            download_url = fmt.get('url')
                            format_info = fmt
                            break
            
            if not download_url:
                return {'success': False, 'error': 'No download URL found for requested format'}
            
            # Download the file
            filename = self._download_file(download_url, info_result['title'])
            
            if filename:
                return {
                    'success': True,
                    'title': info_result['title'],
                    'filename': os.path.basename(filename),
                    'filepath': filename,
                    'file_size': self.format_file_size(os.path.getsize(filename)),
                    'platform': info_result['platform'],
                    'media_type': media_type,
                    'quality': format_info.get('resolution', 'Unknown') if format_info else 'Unknown'
                }
            else:
                return {'success': False, 'error': 'Failed to download file'}
                
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return {'success': False, 'error': f'Download failed: {str(e)}'}
    
    def _download_file(self, download_url, title):
        """Download file from URL"""
        try:
            # Clean filename
            clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            filename = os.path.join(self.base_dir, f"{clean_title}.mp4")
            
            # Download with progress
            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()
            
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return filename
            
        except Exception as e:
            logger.error(f"File download error: {str(e)}")
            return None
    
    def _get_height_from_quality(self, quality):
        """Extract height from quality string"""
        quality_map = {
            '144p': 144, '240p': 240, '360p': 360, '480p': 480,
            '720p': 720, '1080p': 1080, '1440p': 1440, '2160p': 2160
        }
        return quality_map.get(quality.lower(), 0)
    
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
    
    def format_file_size(self, bytes_size):
        if not bytes_size:
            return "Unknown"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} TB"