from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from utils.downloader import JayDLDownloader
import os
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize downloader
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), 'downloads')
downloader = JayDLDownloader(base_dir=DOWNLOAD_DIR)

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

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
        
        logger.info(f"Downloading: {url} | Quality: {quality} | Type: {media_type}")
        
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