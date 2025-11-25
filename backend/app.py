from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import time
import logging
from utils.downloader import JayDLDownloader

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size

# Initialize downloader with local path
downloader = JayDLDownloader()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/')
def home():
    return jsonify({
        'message': 'JayDL API is running locally',
        'status': 'healthy',
        'version': '1.0.0',
        'environment': 'local'
    })

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy', 
        'message': 'JayDL API is running locally',
        'timestamp': time.time(),
        'environment': 'local'
    })

@app.route('/ping', methods=['GET', 'HEAD'])
def ping():
    return '', 200

@app.route('/api/status', methods=['GET'])
def status_check():
    return jsonify({
        'status': 'healthy',
        'environment': 'local',
        'active': True
    })

@app.route('/api/info', methods=['POST'])
def get_media_info():
    """Get information about the media"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'success': False, 'error': 'No URL provided'})
        
        info = downloader.get_video_info(url)
        return jsonify(info)
        
    except Exception as e:
        logger.error(f"Info error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/download', methods=['POST'])
def download_media():
    """Download media from provided URL"""
    try:
        data = request.get_json()
        url = data.get('url')
        quality = data.get('quality', 'best')
        media_type = data.get('media_type', 'video')
        
        if not url:
            return jsonify({'success': False, 'error': 'No URL provided'})
        
        logger.info(f"Download request: {url} - Quality: {quality} - Type: {media_type}")
        
        result = downloader.download_media(url, quality, media_type)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/downloaded-file/<filename>', methods=['GET'])
def get_downloaded_file(filename):
    """Serve downloaded files with proper headers and error handling"""
    try:
        # Security check - prevent directory traversal
        if '..' in filename or filename.startswith('/') or '/' in filename:
            return jsonify({'success': False, 'error': 'Invalid filename'})
        
        # Check both videos and music directories
        video_path = os.path.join(downloader.base_dir, 'videos', filename)
        music_path = os.path.join(downloader.base_dir, 'music', filename)
        
        file_path = None
        if os.path.exists(video_path):
            file_path = video_path
        elif os.path.exists(music_path):
            file_path = music_path
        else:
            print(f"File not found: {filename}")
            return jsonify({'success': False, 'error': 'File not found on server'})
        
        # Check if file is valid and has content
        file_size = os.path.getsize(file_path)
        print(f"File found: {file_path} ({file_size} bytes)")
        
        if file_size == 0:
            print(f"File is empty: {filename}")
            return jsonify({'success': False, 'error': 'File is empty (0 bytes)'})
        
        if file_size < 1024:  # Less than 1KB
            print(f"File too small, likely corrupted: {filename} ({file_size} bytes)")
            # Read the file to see if it contains an error message
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    print(f"File content: {content}")
            except:
                pass
        
        # Determine MIME type based on file extension
        mimetype = 'application/octet-stream'
        if filename.lower().endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.lower().endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif filename.lower().endswith('.webm'):
            mimetype = 'video/webm'
        
        print(f"Serving file: {filename} ({file_size} bytes) as {mimetype}")
        
        # Serve file with proper headers
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )
        
        # Add headers for better download handling
        response.headers['Content-Length'] = file_size
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Accept-Ranges'] = 'bytes'
        
        return response
            
    except Exception as e:
        logger.error(f"File serve error: {e}")
        return jsonify({'success': False, 'error': f'Download failed: {str(e)}'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)