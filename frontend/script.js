class JayDL {
    constructor() {
        // Smart API URL detection - works in both environments
        this.apiBase = this.getApiBaseUrl();
        this.currentMediaInfo = null;
        this.downloadHistory = JSON.parse(localStorage.getItem('jaydl_history')) || [];
        
        this.initializeEventListeners();
        this.loadSupportedPlatforms();
        this.loadDownloadHistory();
        
        console.log(`JayDL running in ${this.isProduction() ? 'PRODUCTION' : 'DEVELOPMENT'} mode`);
        console.log(`API Base: ${this.apiBase}`);
        
        // Auto-start keep-alive only in production
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
        
        // Production (your deployed frontend)
        if (hostname.includes('netlify.app')) {
            return 'https://your-app-name.onrender.com/api'; // UPDATE THIS WITH YOUR ACTUAL RENDER URL
        }
        
        // Fallback for other deployments
        return '/api'; // Relative URL for same-domain deployment
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

        // Media type selection
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
            const response = await fetch(`${this.apiBase}/health`);
            const data = await response.json();
            console.log('Backend connection:', data.status);
            this.showNotification('Connected to backend server', 'success');
        } catch (error) {
            console.error('Backend connection failed:', error);
            this.showNotification('Backend server not running. Please start the backend first.', 'error');
        }
    }

    startKeepAlive() {
        // Ping every 10 minutes to keep backend awake
        setInterval(async () => {
            try {
                await fetch(`${this.apiBase.replace('/api', '')}/ping`);
                console.log('Keep-alive ping sent');
            } catch (error) {
                console.log('Keep-alive ping failed');
            }
        }, 10 * 60 * 1000); // 10 minutes

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
            await fetch(`${this.apiBase.replace('/api', '')}/ping`, { 
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

    async analyzeUrl() {
        const url = document.getElementById('urlInput').value.trim();
        
        if (!url) {
            this.showNotification('Please enter a URL', 'error');
            return;
        }

        // Basic URL validation
        if (!this.isValidUrl(url)) {
            this.showNotification('Please enter a valid URL', 'error');
            return;
        }

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

    isValidUrl(url) {
        try {
            new URL(url);
            return true;
        } catch {
            return false;
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

        // Populate quality options
        this.populateQualityOptions(info.formats, info.platform);
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
            
            // Show info message
            this.showNotification(`${this.capitalizeFirstLetter(platform)} works best with 'Best Available' quality`, 'info');
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
        let quality = document.querySelector('#qualityOptions .option-btn.active')?.dataset.quality || 'best';
        
        // Auto-adjust quality for platforms with limited formats
        const platform = this.currentMediaInfo.platform;
        if (platform === 'tiktok' || platform === 'instagram') {
            quality = 'best'; // Force best quality for these platforms
        }

        this.showLoading('Starting download...', this.getEstimatedTime(platform));

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
        // Return estimated time in seconds based on platform
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
            <strong>File size:</strong> ${result.file_size}<br><br>
            <em>File saved to: C:\\Users\\rosen\\JayDL_Downloads\\videos\\</em>
        `;
        
        action.textContent = `Download ${result.filename}`;
        action.onclick = () => this.downloadFile(result.filename);
        
        // Add file browser button
        const fileBrowserBtn = document.createElement('button');
        fileBrowserBtn.textContent = 'Open File Location';
        fileBrowserBtn.className = 'close-btn';
        fileBrowserBtn.style.marginLeft = '10px';
        fileBrowserBtn.onclick = () => this.showFileBrowserOption();
        
        action.parentNode.appendChild(fileBrowserBtn);

        this.showModal('resultModal');
    }

    async downloadFile(filename) {
        try {
            this.showLoading('Preparing download...');
            
            console.log(`Starting download: ${filename}`);
            
            // Create a hidden iframe for download
            const iframe = document.createElement('iframe');
            iframe.style.display = 'none';
            iframe.src = `${this.apiBase}/downloaded-file/${filename}`;
            document.body.appendChild(iframe);
            
            // Also try the fetch method as backup
            const response = await fetch(`${this.apiBase}/downloaded-file/${filename}`);
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server error: ${response.status}`);
            }
            
            // Get file size from headers
            const contentLength = response.headers.get('Content-Length');
            const fileSize = contentLength ? this.formatFileSize(parseInt(contentLength)) : 'Unknown';
            
            console.log(`Download response OK, file size: ${fileSize}`);
            
            // Convert to blob and download
            const blob = await response.blob();
            
            if (blob.size === 0) {
                throw new Error('Downloaded file is empty (0 bytes)');
            }
            
            console.log(`Blob size: ${blob.size} bytes`);
            
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
            document.body.removeChild(iframe);
            
            this.hideLoading();
            
            // Verify download
            setTimeout(() => {
                this.showNotification(`Download started! File size: ${fileSize}`, 'success');
            }, 1000);
            
        } catch (error) {
            this.hideLoading();
            console.error('Download error:', error);
            
            let errorMessage = error.message;
            
            // Provide helpful error messages
            if (errorMessage.includes('empty') || errorMessage.includes('0 bytes')) {
                errorMessage = 'Downloaded file is empty. The file may be corrupted on the server.';
            } else if (errorMessage.includes('not found')) {
                errorMessage = 'File not found on server. It may have been deleted or the download failed.';
            } else if (errorMessage.includes('CORS') || errorMessage.includes('Network')) {
                errorMessage = 'Network error. Please check your connection and try again.';
            }
            
            this.showNotification(`Download failed: ${errorMessage}`, 'error');
            
            // Alternative download method
            this.showAlternativeDownload(filename);
        }
    }

    formatFileSize(bytes) {
        if (bytes === 0) return "0 B";
        const sizes = ["B", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + " " + sizes[i];
    }

    showAlternativeDownload(filename) {
        // Create a direct download link as fallback
        const directUrl = `${this.apiBase}/downloaded-file/${filename}`;
        
        const modal = document.getElementById('resultModal');
        const icon = document.getElementById('resultIcon');
        const title = document.getElementById('resultTitle');
        const message = document.getElementById('resultMessage');
        const action = document.getElementById('resultAction');

        icon.className = 'result-icon error';
        icon.innerHTML = '<i class="fas fa-exclamation-triangle"></i>';
        title.textContent = 'Download Issue';
        message.innerHTML = `
            Automatic download failed. <br><br>
            <strong>Try these alternatives:</strong><br>
            1. <button onclick="jaydl.directDownload('${filename}')" style="background: #667eea; color: white; border: none; padding: 5px 10px; border-radius: 5px; cursor: pointer;">Click here for direct download</button><br>
            2. <a href="${directUrl}" target="_blank" style="color: #667eea; text-decoration: underline;">Right-click and Save As</a><br>
            3. File location: C:\\Users\\rosen\\JayDL_Downloads\\videos\\${filename}
        `;
        
        action.textContent = 'Close';
        action.onclick = () => this.closeModal();

        this.showModal('resultModal');
    }

    directDownload(filename) {
        // Direct download method
        const directUrl = `${this.apiBase}/downloaded-file/${filename}`;
        window.open(directUrl, '_blank');
    }

    showFileBrowserOption() {
        const modal = document.getElementById('resultModal');
        const icon = document.getElementById('resultIcon');
        const title = document.getElementById('resultTitle');
        const message = document.getElementById('resultMessage');
        const action = document.getElementById('resultAction');

        icon.className = 'result-icon info';
        icon.innerHTML = '<i class="fas fa-folder-open"></i>';
        title.textContent = 'Access Files Manually';
        message.innerHTML = `
            <strong>Your downloaded files are here:</strong><br><br>
            <code style="background: #f0f0f0; padding: 10px; border-radius: 5px; display: block;">
                C:\\Users\\rosen\\JayDL_Downloads\\videos\\
            </code><br>
            <strong>Steps:</strong><br>
            1. Open File Explorer<br>
            2. Paste the path above in the address bar<br>
            3. Find your downloaded files<br>
            4. Copy them to your preferred location<br><br>
            <em>All successfully downloaded files are stored here automatically.</em>
        `;
        
        action.textContent = 'Copy Path to Clipboard';
        action.onclick = () => {
            navigator.clipboard.writeText('C:\\Users\\rosen\\JayDL_Downloads\\videos\\');
            this.showNotification('File path copied to clipboard!', 'success');
            this.closeModal();
        };
        
        // Add secondary button
        const secondaryBtn = document.createElement('button');
        secondaryBtn.textContent = 'Close';
        secondaryBtn.className = 'close-btn';
        secondaryBtn.style.marginLeft = '10px';
        secondaryBtn.onclick = () => this.closeModal();
        
        action.parentNode.appendChild(secondaryBtn);

        this.showModal('resultModal');
    }

    addToDownloadHistory(download) {
        const historyItem = {
            id: Date.now(),
            title: download.title,
            filename: download.filename,
            platform: download.platform,
            media_type: download.media_type,
            timestamp: new Date().toISOString(),
            file_size: download.file_size
        };

        this.downloadHistory.unshift(historyItem);
        // Keep only last 10 downloads
        this.downloadHistory = this.downloadHistory.slice(0, 10);
        
        localStorage.setItem('jaydl_history', JSON.stringify(this.downloadHistory));
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
                <div class="history-actions">
                    <button class="option-btn" onclick="jaydl.downloadFile('${item.filename}')" title="Download again">
                        <i class="fas fa-download"></i>
                    </button>
                    <button class="option-btn" onclick="jaydl.showFileBrowserOption()" title="Open file location">
                        <i class="fas fa-folder-open"></i>
                    </button>
                </div>
            </div>
        `).join('');
    }

    async loadSupportedPlatforms() {
        try {
            const response = await fetch(`${this.apiBase}/supported-platforms`);
            const platforms = await response.json();
            
            const container = document.getElementById('platformsGrid');
            container.innerHTML = platforms.map(platform => `
                <div class="platform-card">
                    <div class="platform-icon">${platform.icon}</div>
                    <h4>${platform.name}</h4>
                    <div style="font-size: 0.9em; color: #666;">
                        ${platform.types.join(', ')}
                    </div>
                </div>
            `).join('');
        } catch (error) {
            console.error('Failed to load supported platforms:', error);
            // Fallback platforms if API fails
            this.showFallbackPlatforms();
        }
    }

    showFallbackPlatforms() {
        const fallbackPlatforms = [
            { name: 'YouTube', icon: '🎥', types: ['video', 'audio'] },
            { name: 'Spotify', icon: '🎵', types: ['audio'] },
            { name: 'TikTok', icon: '📱', types: ['video'] },
            { name: 'Instagram', icon: '📸', types: ['video', 'image'] },
            { name: 'Twitter/X', icon: '🐦', types: ['video'] }
        ];
        
        const container = document.getElementById('platformsGrid');
        container.innerHTML = fallbackPlatforms.map(platform => `
            <div class="platform-card">
                <div class="platform-icon">${platform.icon}</div>
                <h4>${platform.name}</h4>
                <div style="font-size: 0.9em; color: #666;">
                    ${platform.types.join(', ')}
                </div>
            </div>
        `).join('');
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
        
        // Store timer reference to clear if needed
        this.estimatedTimer = timer;
    }

    hideLoading() {
        document.getElementById('loadingModal').classList.add('hidden');
        // Clear any running timers
        if (this.estimatedTimer) {
            clearInterval(this.estimatedTimer);
        }
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
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification ${type === 'error' ? 'error' : ''}`;
        notification.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check' : 'exclamation'}-circle"></i>
            ${message}
        `;

        document.body.appendChild(notification);

        // Remove after 3 seconds
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, 3000);
    }

    capitalizeFirstLetter(string) {
        return string.charAt(0).toUpperCase() + string.slice(1);
    }
}

// Add CSS animations for notifications if not already in style.css
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