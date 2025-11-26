class JayDL {
    constructor() {
        this.apiBase = this.getApiBaseUrl();
        this.currentMediaInfo = null;
        this.downloadHistory = JSON.parse(localStorage.getItem('jaydl_history')) || [];
        
        this.initializeEventListeners();
        this.loadSupportedPlatforms();
        this.loadDownloadHistory();
        
        console.log(`JayDL running in ${this.isProduction() ? 'PRODUCTION' : 'DEVELOPMENT'} mode`);
        
        if (this.isProduction()) {
            this.startKeepAlive();
        }
        
        this.testBackendConnection();
    }

    getApiBaseUrl() {
        const hostname = window.location.hostname;
        
        // Development (local)
        if (hostname === 'localhost' || hostname === '127.0.0.1') {
            return 'http://localhost:5000/api';
        }
        
        // Production - Vercel
        if (hostname.includes('vercel.app')) {
            return 'https://jaydl.onrender.com/api';
        }
        
        // Fallback
        return 'https://jaydl.onrender.com/api';
    }

    isProduction() {
        return !window.location.hostname.includes('localhost') && 
               !window.location.hostname.includes('127.0.0.1');
    }

    initializeEventListeners() {
        // URL input events
        document.getElementById('analyzeBtn').addEventListener('click', () => this.analyzeUrl());
        document.getElementById('pasteBtn').addEventListener('click', () => this.pasteFromClipboard());
        document.getElementById('urlInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.analyzeUrl();
        });

        // Download type selection
        document.querySelectorAll('.option-btn[data-type]').forEach(btn => {
            btn.addEventListener('click', (e) => this.selectMediaType(e.target));
        });

        // Download button
        document.getElementById('downloadBtn').addEventListener('click', () => this.startDownload());

        // Modal events
        document.getElementById('closeModal').addEventListener('click', () => this.closeModal());
        
        // Close modal when clicking outside
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) this.closeModal();
            });
        });
    }

    async testBackendConnection() {
        try {
            const response = await fetch('https://jaydl.onrender.com/api/health');
            const data = await response.json();
            console.log('Backend connection:', data.status);
            this.showNotification('Connected to download service', 'success');
        } catch (error) {
            console.error('Backend connection failed:', error);
            this.showNotification('Backend server not running. Some platforms may not work.', 'error');
        }
    }

    startKeepAlive() {
        // Ping every 10 minutes to keep backend awake
        setInterval(async () => {
            try {
                await fetch('https://jaydl.onrender.com/ping');
                console.log('Keep-alive ping sent');
            } catch (error) {
                console.log('Keep-alive ping failed');
            }
        }, 10 * 60 * 1000);

        // Also ping when user interacts with the page
        document.addEventListener('click', () => {
            this.sendPing();
        });

        // Ping when page becomes visible
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                this.sendPing();
            }
        });
    }

    async sendPing() {
        try {
            await fetch('https://jaydl.onrender.com/ping', { 
                method: 'HEAD',
                mode: 'no-cors'
            });
        } catch (error) {
            // Silent fail - expected in no-cors mode
        }
    }

    async pasteFromClipboard() {
        try {
            const text = await navigator.clipboard.readText();
            document.getElementById('urlInput').value = text;
            this.showNotification('URL pasted from clipboard!', 'success');
        } catch (err) {
            this.showNotification('Failed to paste from clipboard', 'error');
        }
    }

    detectPlatform(url) {
        const urlLower = url.toLowerCase();
        if (urlLower.includes('youtube.com') || urlLower.includes('youtu.be')) {
            return 'youtube';
        } else if (urlLower.includes('tiktok.com')) {
            return 'tiktok';
        } else if (urlLower.includes('instagram.com')) {
            return 'instagram';
        } else if (urlLower.includes('twitter.com') || urlLower.includes('x.com')) {
            return 'twitter';
        } else if (urlLower.includes('spotify.com')) {
            return 'spotify';
        }
        return 'generic';
    }

    async analyzeUrl() {
        const url = document.getElementById('urlInput').value.trim();
        
        if (!url) {
            this.showNotification('Please enter a URL', 'error');
            return;
        }

        if (!this.isValidUrl(url)) {
            this.showNotification('Please enter a valid URL', 'error');
            return;
        }

        const platform = this.detectPlatform(url);
        
        // Use client-side for YouTube if available
        if (platform === 'youtube' && typeof ytdl !== 'undefined') {
            await this.analyzeYouTubeClientSide(url);
        } else {
            // Use backend for other platforms
            await this.analyzeWithBackend(url);
        }
    }

    isValidUrl(url) {
        try {
            new URL(url);
            return true;
        } catch {
            return false;
        }
    }

    async analyzeYouTubeClientSide(url) {
        this.showLoading('Getting YouTube video info...');

        try {
            if (!ytdl.validateURL(url)) {
                throw new Error('Invalid YouTube URL format');
            }

            const videoInfo = await ytdl.getInfo(url);
            this.currentMediaInfo = {
                success: true,
                title: videoInfo.videoDetails.title,
                duration: this.formatDuration(videoInfo.videoDetails.lengthSeconds),
                thumbnail: videoInfo.videoDetails.thumbnails[0]?.url,
                uploader: videoInfo.videoDetails.author.name,
                view_count: videoInfo.videoDetails.viewCount,
                formats: this.parseYouTubeFormats(videoInfo.formats),
                platform: 'youtube'
            };

            this.displayMediaInfo(this.currentMediaInfo);
            this.showNotification('YouTube video info loaded!', 'success');

        } catch (error) {
            console.error('Error getting YouTube video info:', error);
            
            let errorMessage = error.message;
            if (errorMessage.includes('Video unavailable')) {
                errorMessage = 'This video is not available or private';
            } else if (errorMessage.includes('Sign in to confirm')) {
                errorMessage = 'Please make sure you are logged into YouTube in this browser';
            }
            
            this.showNotification(`YouTube analysis failed: ${errorMessage}`, 'error');
            
            // Fallback to backend for YouTube
            await this.analyzeWithBackend(url);
        } finally {
            this.hideLoading();
        }
    }

    parseYouTubeFormats(formats) {
        const uniqueFormats = [];
        const seenHeights = new Set();

        formats.forEach(format => {
            if (format.height && !seenHeights.has(format.height)) {
                seenHeights.add(format.height);
                uniqueFormats.push({
                    format_id: format.format_id,
                    resolution: `${format.height}p`,
                    height: format.height,
                    filesize: format.contentLength ? this.formatFileSize(format.contentLength) : 'Unknown',
                    format: `${format.height}p - ${format.qualityLabel || ''}`
                });
            }
        });

        // Add audio option
        uniqueFormats.push({
            format_id: 'audio',
            resolution: 'Audio Only',
            height: 0,
            filesize: 'Unknown',
            format: 'bestaudio'
        });

        return uniqueFormats.sort((a, b) => b.height - a.height);
    }

    async analyzeWithBackend(url) {
        this.showLoading('Analyzing URL...');

        try {
            const response = await fetch(`${this.apiBase}/info`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url })
            });

            const data = await response.json();

            if (data.success) {
                this.currentMediaInfo = data;
                this.displayMediaInfo(data);
                this.showNotification('Media info loaded successfully!', 'success');
            } else {
                throw new Error(data.error || 'Failed to analyze URL');
            }
        } catch (error) {
            this.showNotification(`Analysis failed: ${error.message}`, 'error');
        } finally {
            this.hideLoading();
        }
    }

    displayMediaInfo(info) {
        const mediaInfoSection = document.getElementById('mediaInfo');
        mediaInfoSection.classList.remove('hidden');

        // Update media details
        document.getElementById('mediaTitle').textContent = info.title;
        document.getElementById('mediaDuration').innerHTML = `<i class="fas fa-clock"></i> ${info.duration}`;
        document.getElementById('mediaUploader').innerHTML = `<i class="fas fa-user"></i> ${info.uploader}`;
        document.getElementById('mediaPlatform').innerHTML = `<i class="fas fa-globe"></i> ${this.capitalizeFirstLetter(info.platform)}`;

        // Update thumbnail
        const thumbnail = document.getElementById('mediaThumbnail');
        if (info.thumbnail) {
            thumbnail.src = info.thumbnail;
            thumbnail.style.display = 'block';
        } else {
            thumbnail.style.display = 'none';
        }

        this.populateQualityOptions(info.formats, info.platform);
        
        // Enable download button
        document.getElementById('downloadBtn').disabled = false;
    }

    populateQualityOptions(formats, platform) {
        const container = document.getElementById('qualityOptions');
        container.innerHTML = '';

        // Default quality options
        const defaultQualities = [
            { id: '4k', label: '4K Ultra HD', available: formats.some(f => f.height >= 2160) },
            { id: '1440p', label: '1440p QHD', available: formats.some(f => f.height >= 1440) },
            { id: '1080p', label: '1080p Full HD', available: formats.some(f => f.height >= 1080) },
            { id: '720p', label: '720p HD', available: formats.some(f => f.height >= 720) },
            { id: '480p', label: '480p', available: formats.some(f => f.height >= 480) },
            { id: 'best', label: 'Best Available', available: true }
        ];

        // For platforms with limited formats, only show "Best Available"
        if (platform === 'tiktok' || platform === 'instagram') {
            const bestButton = document.createElement('button');
            bestButton.className = 'option-btn active';
            bestButton.textContent = 'Best Available';
            bestButton.dataset.quality = 'best';
            bestButton.addEventListener('click', (e) => this.selectQuality(e.target));
            container.appendChild(bestButton);
        } else {
            // Show all available qualities for other platforms
            defaultQualities.forEach(quality => {
                if (quality.available) {
                    const button = document.createElement('button');
                    button.className = 'option-btn';
                    button.textContent = quality.label;
                    button.dataset.quality = quality.id;
                    button.addEventListener('click', (e) => this.selectQuality(e.target));
                    container.appendChild(button);
                }
            });

            // Select first available quality
            const firstQualityBtn = container.querySelector('.option-btn');
            if (firstQualityBtn) {
                this.selectQuality(firstQualityBtn);
            }
        }
    }

    selectMediaType(button) {
        document.querySelectorAll('.option-btn[data-type]').forEach(btn => {
            btn.classList.remove('active');
        });
        button.classList.add('active');
    }

    selectQuality(button) {
        document.querySelectorAll('#qualityOptions .option-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        button.classList.add('active');
    }

    async startDownload() {
        if (!this.currentMediaInfo) {
            this.showNotification('Please analyze a URL first', 'error');
            return;
        }

        const url = document.getElementById('urlInput').value.trim();
        const mediaType = document.querySelector('.option-btn[data-type].active').dataset.type;
        const quality = document.querySelector('#qualityOptions .option-btn.active')?.dataset.quality || 'best';
        const platform = this.currentMediaInfo.platform;

        // Use client-side for YouTube
        if (platform === 'youtube' && typeof ytdl !== 'undefined') {
            await this.downloadYouTubeClientSide(url, mediaType, quality);
        } else {
            // Use backend for other platforms
            await this.downloadWithBackend(url, quality, mediaType);
        }
    }

    async downloadYouTubeClientSide(url, mediaType, quality) {
        this.showLoading('Preparing YouTube download...');

        try {
            if (!ytdl.validateURL(url)) {
                throw new Error('Invalid YouTube URL');
            }

            const videoInfo = await ytdl.getInfo(url);
            
            let format;
            if (mediaType === 'audio') {
                format = ytdl.chooseFormat(videoInfo.formats, {
                    quality: 'highestaudio',
                    filter: 'audioonly'
                });
            } else {
                format = ytdl.chooseFormat(videoInfo.formats, {
                    quality: quality === 'best' ? 'highest' : 'lowest'
                });
            }

            if (!format) {
                throw new Error('No suitable format found');
            }

            // Create download link
            const a = document.createElement('a');
            a.href = format.url;
            
            // Set filename
            const fileExtension = mediaType === 'audio' ? 'mp3' : 'mp4';
            const fileName = this.sanitizeFilename(`${videoInfo.videoDetails.title}.${fileExtension}`);
            a.download = fileName;
            
            // Trigger download
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

            this.hideLoading();
            this.showSuccess('Download started!', 'Your YouTube video is now downloading.');

            // Add to history
            this.addToDownloadHistory({
                title: videoInfo.videoDetails.title,
                filename: fileName,
                platform: 'youtube',
                media_type: mediaType,
                file_size: format.contentLength ? this.formatFileSize(format.contentLength) : 'Unknown',
                timestamp: new Date().toISOString()
            });

        } catch (error) {
            this.hideLoading();
            console.error('YouTube download error:', error);
            
            let errorMessage = error.message;
            if (errorMessage.includes('Sign in to confirm')) {
                errorMessage = 'Please make sure you are logged into YouTube in this browser and try again';
            } else if (errorMessage.includes('format is not available')) {
                errorMessage = 'The selected quality is not available for this video';
            }
            
            this.showNotification(`YouTube download failed: ${errorMessage}`, 'error');
            
            // Fallback to backend for YouTube
            await this.downloadWithBackend(url, quality, mediaType);
        }
    }

    async downloadWithBackend(url, quality, mediaType) {
        this.showLoading('Starting download...', this.getEstimatedTime(this.currentMediaInfo.platform));

        try {
            const response = await fetch(`${this.apiBase}/download`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url,
                    quality,
                    media_type: mediaType
                })
            });

            const data = await response.json();

            if (data.success) {
                this.addToDownloadHistory(data);
                this.showDownloadResult(data);
            } else {
                throw new Error(data.error || 'Download failed');
            }
        } catch (error) {
            this.showNotification(`Download failed: ${error.message}`, 'error');
        } finally {
            this.hideLoading();
        }
    }

    getEstimatedTime(platform) {
        const times = {
            'youtube': 30,
            'tiktok': 45,
            'instagram': 40,
            'twitter': 35,
            'spotify': 60,
            'generic': 45
        };
        return times[platform] || 30;
    }

    showDownloadResult(result) {
        const modal = document.getElementById('resultModal');
        const icon = document.getElementById('resultIcon');
        const title = document.getElementById('resultTitle');
        const message = document.getElementById('resultMessage');
        const action = document.getElementById('resultAction');

        icon.className = 'result-icon success';
        icon.innerHTML = '<i class="fas fa-check-circle"></i>';
        title.textContent = 'Download Complete!';
        message.innerHTML = `
            "${result.title}" has been downloaded successfully.<br>
            <strong>File size:</strong> ${result.file_size}
        `;
        
        action.textContent = `Download ${result.filename}`;
        action.onclick = () => this.downloadFile(result.filename);
        
        this.showModal('resultModal');
    }

    async downloadFile(filename) {
        try {
            this.showLoading('Preparing download...');
            
            const response = await fetch(`${this.apiBase}/downloaded-file/${filename}`);
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server error: ${response.status}`);
            }
            
            const blob = await response.blob();
            
            if (blob.size === 0) {
                throw new Error('Downloaded file is empty (0 bytes)');
            }
            
            // Create download link
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            
            // Trigger download
            document.body.appendChild(a);
            a.click();
            
            // Cleanup
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            this.hideLoading();
            this.showNotification('Download started!', 'success');
            
        } catch (error) {
            this.hideLoading();
            console.error('Download error:', error);
            this.showNotification(`Download failed: ${error.message}`, 'error');
        }
    }

    sanitizeFilename(filename) {
        return filename.replace(/[<>:"/\\|?*]/g, '_');
    }

    formatDuration(seconds) {
        if (!seconds) return "Unknown";
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        } else {
            return `${minutes}:${secs.toString().padStart(2, '0')}`;
        }
    }

    formatFileSize(bytes) {
        if (!bytes) return "Unknown";
        const sizes = ["B", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + " " + sizes[i];
    }

    formatViews(viewCount) {
        if (!viewCount) return 'Unknown';
        const count = parseInt(viewCount);
        if (count >= 1000000) {
            return (count / 1000000).toFixed(1) + 'M';
        } else if (count >= 1000) {
            return (count / 1000).toFixed(1) + 'K';
        }
        return count.toString();
    }

    addToDownloadHistory(download) {
        let history = JSON.parse(localStorage.getItem('jaydl_history')) || [];
        history.unshift({
            id: Date.now(),
            ...download
        });
        // Keep only last 10 downloads
        history = history.slice(0, 10);
        localStorage.setItem('jaydl_history', JSON.stringify(history));
        this.loadDownloadHistory();
    }

    loadDownloadHistory() {
        const container = document.getElementById('historyList');
        
        if (this.downloadHistory.length === 0) {
            container.innerHTML = '<p style="text-align: center; color: #666;">No downloads yet</p>';
            return;
        }

        container.innerHTML = this.downloadHistory.map(item => `
            <div class="history-item">
                <div class="history-info">
                    <strong>${item.title}</strong>
                    <div style="font-size: 0.9em; color: #666;">
                        ${this.capitalizeFirstLetter(item.platform)} • ${item.media_type} • ${item.file_size}
                    </div>
                    <div style="font-size: 0.8em; color: #999;">
                        ${new Date(item.timestamp).toLocaleString()}
                    </div>
                </div>
            </div>
        `).join('');
    }

    async loadSupportedPlatforms() {
        try {
            const platforms = [
                { name: 'YouTube', icon: '🎥', types: ['video', 'audio'], note: 'Client-side download' },
                { name: 'TikTok', icon: '📱', types: ['video'] },
                { name: 'Instagram', icon: '📸', types: ['video', 'image'] },
                { name: 'Twitter/X', icon: '🐦', types: ['video'] },
                { name: 'Spotify', icon: '🎵', types: ['audio'] }
            ];
            
            const container = document.getElementById('platformsGrid');
            container.innerHTML = platforms.map(platform => `
                <div class="platform-card">
                    <div class="platform-icon">${platform.icon}</div>
                    <h4>${platform.name}</h4>
                    <div style="font-size: 0.9em; color: #666;">
                        ${platform.types.join(', ')}
                    </div>
                    ${platform.note ? `<div style="font-size: 0.8em; color: #667eea; margin-top: 5px;">${platform.note}</div>` : ''}
                </div>
            `).join('');
        } catch (error) {
            console.error('Failed to load supported platforms:', error);
        }
    }

    showLoading(message = 'Loading...', estimatedTime = null) {
        document.getElementById('loadingMessage').textContent = message;
        
        if (estimatedTime) {
            this.showEstimatedTime(estimatedTime);
        }
        
        document.getElementById('loadingModal').classList.remove('hidden');
    }

    showEstimatedTime(seconds) {
        const loadingMsg = document.getElementById('loadingMessage');
        const originalText = loadingMsg.textContent;
        
        let timeLeft = seconds;
        const timer = setInterval(() => {
            if (timeLeft > 0) {
                loadingMsg.textContent = `${originalText} (${timeLeft}s)`;
                timeLeft--;
            } else {
                clearInterval(timer);
                loadingMsg.textContent = `${originalText} (any moment now...)`;
            }
        }, 1000);
        
        this.estimatedTimer = timer;
    }

    hideLoading() {
        document.getElementById('loadingModal').classList.add('hidden');
        if (this.estimatedTimer) {
            clearInterval(this.estimatedTimer);
        }
    }

    showSuccess(title, message) {
        const modal = document.getElementById('resultModal');
        const icon = document.getElementById('resultIcon');
        const titleEl = document.getElementById('resultTitle');
        const messageEl = document.getElementById('resultMessage');
        const action = document.getElementById('resultAction');

        icon.className = 'result-icon success';
        icon.innerHTML = '<i class="fas fa-check-circle"></i>';
        titleEl.textContent = title;
        messageEl.textContent = message;
        action.style.display = 'none';
        
        this.showModal('resultModal');
    }

    showModal(modalId) {
        document.getElementById(modalId).classList.remove('hidden');
    }

    closeModal() {
        document.querySelectorAll('.modal').forEach(modal => {
            modal.classList.add('hidden');
        });
    }

    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification ${type === 'error' ? 'error' : ''}`;
        notification.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check' : 'exclamation'}-circle"></i>
            ${message}
        `;

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, 4000);
    }

    capitalizeFirstLetter(string) {
        return string.charAt(0).toUpperCase() + string.slice(1);
    }
}

// Add CSS animations for notifications
const ensureNotificationStyles = () => {
    if (!document.querySelector('#jaydl-notification-styles')) {
        const style = document.createElement('style');
        style.id = 'jaydl-notification-styles';
        style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            
            @keyframes slideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
            
            .notification {
                position: fixed;
                top: 20px;
                right: 20px;
                background: #00b894;
                color: white;
                padding: 15px 20px;
                border-radius: 10px;
                z-index: 1001;
                animation: slideIn 0.3s ease;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }
            
            .notification.error {
                background: #e17055;
            }
            
            .notification i {
                margin-right: 8px;
            }
        `;
        document.head.appendChild(style);
    }
};

// Initialize when page loads
let jaydl;
document.addEventListener('DOMContentLoaded', () => {
    ensureNotificationStyles();
    jaydl = new JayDL();
});