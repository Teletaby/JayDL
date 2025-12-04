// oauth.js — Start Google OAuth flow and poll status
(function() {
    function getBackendUrl() {
        const protocol = window.location.protocol;
        const hostname = window.location.hostname;
        const port = window.location.port;
        if (hostname === 'localhost' || hostname === '127.0.0.1') {
            return `${protocol}//${hostname}:5000`;
        }
        if (hostname.includes('onrender.com')) {
            return 'https://jaydl-backend.onrender.com';
        }
        return `${protocol}//${hostname}${port ? ':' + port : ''}`;
    }

    const API_BASE = getBackendUrl();

    // Check for OAuth success/error in URL
    function checkOAuthResult() {
        const urlParams = new URLSearchParams(window.location.search);
        
        if (urlParams.get('oauth_success') === 'true') {
            // Clear the URL parameters
            window.history.replaceState({}, document.title, window.location.pathname);
            
            // Show success message
            alert('✅ YouTube authentication successful! You can now download YouTube videos.');
            
            // Update UI
            localStorage.setItem('yt_authenticated', 'true');
            const btn = document.getElementById('ytAuthBtn');
            if (btn) btn.classList.add('authenticated');
        }
        else if (urlParams.get('oauth_error')) {
            // Clear the URL parameters
            window.history.replaceState({}, document.title, window.location.pathname);
            
            const error = urlParams.get('oauth_error');
            let errorMessage = '❌ YouTube authentication failed';
            
            switch(error) {
                case 'access_denied':
                    errorMessage = '❌ Access denied. Please grant permission to access YouTube.';
                    break;
                case 'invalid_state':
                    errorMessage = '❌ Invalid authentication state. Please try again.';
                    break;
                case 'state_used':
                    errorMessage = '❌ Authentication link already used. Please try again.';
                    break;
                case 'callback_failed':
                    errorMessage = '❌ Authentication callback failed. Please try again.';
                    break;
                default:
                    errorMessage = `❌ Authentication error: ${error}`;
            }
            
            alert(errorMessage);
        }
    }

    // Check OAuth result on page load
    checkOAuthResult();

    // Expose function globally so index.html can call it
    window.startGoogleOAuth = async function() {
        try {
            // Ask backend to create an authorization URL
            const resp = await fetch(`${API_BASE}/api/oauth/google/start`, { method: 'GET' });
            if (!resp.ok) {
                const text = await resp.text();
                alert('Failed to start OAuth: ' + text);
                return;
            }

            const data = await resp.json();
            if (!data.success || !data.auth_url) {
                alert('OAuth start failed: ' + (data.error || 'No auth_url returned'));
                return;
            }

            const authUrl = data.auth_url;
            const state = data.state;

            // Open popup to auth URL
            const popupName = 'jaydl_google_oauth_' + Date.now();
            const popup = window.open(authUrl, popupName, 'width=900,height=700,scrollbars=yes,resizable=yes');
            if (!popup) {
                alert('Popup blocked. Please allow popups and try again.');
                return;
            }

            // Poll backend for token status
            const maxPolls = 60; // poll for up to ~2 minutes (60 * 2s)
            let polls = 0;

            const poll = setInterval(async () => {
                polls += 1;
                // If popup closed by user, stop
                if (popup.closed) {
                    clearInterval(poll);
                    console.log('OAuth popup closed by user');
                    return;
                }

                try {
                    const statusResp = await fetch(`${API_BASE}/api/oauth/status`);
                    if (!statusResp.ok) {
                        console.warn('OAuth status check returned non-OK');
                        return;
                    }
                    const status = await statusResp.json();
                    if (status.success && status.google_authorized) {
                        clearInterval(poll);
                        try { popup.close(); } catch (e) {}
                        // Mark locally
                        localStorage.setItem('yt_authenticated', 'true');
                        const btn = document.getElementById('ytAuthBtn');
                        if (btn) btn.classList.add('authenticated');
                        alert('✅ Google OAuth completed. YouTube access enabled.');
                        return;
                    }
                } catch (err) {
                    console.warn('Error polling OAuth status:', err);
                }

                if (polls >= maxPolls) {
                    clearInterval(poll);
                    try { popup.close(); } catch (e) {}
                    alert('OAuth timed out. If you completed the flow, try clicking the YouTube button again.');
                }
            }, 2000);

        } catch (err) {
            console.error('startGoogleOAuth error:', err);
            alert('Error starting OAuth: ' + err.message);
        }
    };

    // Expose revoke function
    window.revokeOAuth = async function() {
        try {
            const resp = await fetch(`${API_BASE}/api/oauth/revoke`, { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            const data = await resp.json();
            if (data.success) {
                localStorage.removeItem('yt_authenticated');
                const btn = document.getElementById('ytAuthBtn');
                if (btn) btn.classList.remove('authenticated');
                alert('✅ YouTube authentication revoked successfully.');
            } else {
                alert('❌ Failed to revoke authentication: ' + (data.error || 'Unknown error'));
            }
        } catch (err) {
            console.error('revokeOAuth error:', err);
            alert('Error revoking OAuth: ' + err.message);
        }
    };
})();