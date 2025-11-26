from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize RapidAPI downloader
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), 'downloads')

# RapidAPI Downloader Class (integrated directly)
import requests
import tempfile
from urllib.parse import urlparse

class RapidAPIDownloader:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or tempfile.gettempdir()
        self.ensure_directories()
        
        # Your RapidAPI credentials
        self.api_key = "aeOfcs43b0msh12c1ac12ff2064ep1009f9jsn43915272a236"
        self.api_host = "all-media-downloaderl.p.rapidapi.com"
        self.base_url = "https://all-media-downloaderl.p.rapidapi.com/all"
        
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
                            'filesize': 'Unknown',
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
                'view_count': 0,
                'formats': formats,
                'platform': self.detect_platform(original_url),
                'api_data': data
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

# Initialize the downloader
downloader = RapidAPIDownloader(base_dir=DOWNLOAD_DIR)

@app.route('/')
def index():
    """API status page"""
    return jsonify({
        'success': True,
        'message': 'JayDL Backend API is running (RapidAPI)',
        'version': '1.0',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            'analyze': '/api/analyze (POST)',
            'download': '/api/download (POST)',
            'platforms': '/api/platforms (GET)',
            'health': '/api/health (GET)'
        }
    })

@app.route('/api/analyze', methods=['POST'])
def analyze_media():
    """Analyze a URL and return media information"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL is required'
            }), 400
        
        logger.info(f"Analyzing URL via RapidAPI: {url}")
        
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
            'error': f'Server error: {str(e)}'
        }), 500

@app.route('/api/download', methods=['POST'])
def download_media():
    """Download media from URL"""
    try:
        data = request.get_json()
        url = data.get('url')
        quality = data.get('quality', 'best')
        media_type = data.get('media_type', 'video')
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL is required'
            }), 400
        
        logger.info(f"Downloading via RapidAPI: {url} | Quality: {quality} | Type: {media_type}")
        
        result = downloader.download_media(url, quality=quality, media_type=media_type)
        
        if result['success']:
            logger.info(f"Successfully downloaded: {result['title']}")
            # Add download URL to result
            result['download_url'] = f"/api/file/{result['filename']}"
        else:
            logger.error(f"Download failed: {result['error']}")
        
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
            'supported': True
        },
        {
            'name': 'TikTok',
            'icon': 'fab fa-tiktok',
            'color': '#000000',
            'supported': True
        },
        {
            'name': 'Instagram',
            'icon': 'fab fa-instagram',
            'color': '#E4405F',
            'supported': True
        },
        {
            'name': 'Twitter/X',
            'icon': 'fab fa-twitter',
            'color': '#1DA1F2',
            'supported': True
        },
        {
            'name': 'Spotify',
            'icon': 'fab fa-spotify',
            'color': '#1DB954',
            'supported': True
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
        'timestamp': datetime.now().isoformat()
    })

# Cleanup old files periodically
@app.before_request
def cleanup_old_files():
    """Clean up files older than 1 hour"""
    try:
        if not os.path.exists(DOWNLOAD_DIR):
            return
        
        current_time = datetime.now().timestamp()
        for filename in os.listdir(DOWNLOAD_DIR):
            filepath = os.path.join(DOWNLOAD_DIR, filename)
            
            # Skip if not a file
            if not os.path.isfile(filepath):
                continue
            
            # Check file age
            file_age = current_time - os.path.getmtime(filepath)
            
            # Delete if older than 1 hour
            if file_age > 3600:
                os.remove(filepath)
                logger.info(f"Cleaned up old file: {filename}")
    
    except Exception as e:
        logger.error(f"Error in cleanup: {str(e)}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)