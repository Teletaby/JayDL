// oauth.js — Start Google OAuth flow and manage authentication
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

    // Runs IN THE POPUP after redirect from Google/backend.
    // Its job is to find the cache_key and pass it to the main window.
    function handlePopupRedirect() {
        const hash = window.location.hash;

        // Success case: pass the cache key to the parent
        if (hash.includes('auth_success') && hash.includes('cache_key=')) {
            const cacheKeyMatch = hash.match(/cache_key=([a-f0-9]+)/);
            if (cacheKeyMatch) {
                const cacheKey = cacheKeyMatch[1];
                if (window.opener && window.opener.handleAuthCallback) {
                    window.opener.handleAuthCallback(cacheKey, null);
                    window.close();
                    return;
                }
            }
        }

        // Error case: pass the error to the parent
        if (hash.includes('oauth_error')) {
            const errorMatch = hash.match(/oauth_error=([^&]+)/);
            if (errorMatch) {
                const error = errorMatch[1];
                if (window.opener && window.opener.handleAuthCallback) {
                    window.opener.handleAuthCallback(null, error);
                    window.close();
                    return;
                }
            }
        }
    }

    // This function lives in the MAIN WINDOW and is called by the popup.
    window.handleAuthCallback = function(cacheKey, error) {
        if (error) {
            let errorMessage = '❌ YouTube authentication failed';
            switch (error) {
                case 'access_denied':
                    errorMessage = '❌ Access denied. Please grant permission to access YouTube.';
                    break;
                case 'invalid_state':
                    errorMessage = '❌ Invalid authentication state. The server may have restarted. Please try again.';
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
            return;
        }

        if (cacheKey) {
            // Use the cacheKey to authenticate THIS (the main) window's session
            fetch(`${API_BASE}/api/oauth2/retrieve-cached-credentials/${cacheKey}`, {
                    credentials: 'include'
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        console.log('Main window session authenticated.');
                        // Now that the main window is authenticated, run the final completion logic.
                        window.authenticationComplete();
                    } else {
                        alert('❌ Failed to complete authentication: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(err => {
                    console.error('Error retrieving cached credentials:', err);
                    alert('❌ Error completing authentication: ' + err.message);
                });
        }
    };

    // This is the final step, called only AFTER the main window has been authenticated.
    window.authenticationComplete = async function() {
        console.log('Authentication complete called from popup');

        const shouldSave = confirm(
            '✅ Authentication successful!\n\n' +
            'Do you want to save this account as the shared account for all users?\n\n' +
            'Click OK to save, or Cancel if this is a personal account.'
        );

        if (shouldSave) {
            try {
                const setupResp = await fetch(`${API_BASE}/api/oauth2/setup-shared-account`, {
                    method: 'GET',
                    credentials: 'include'
                });
                const setupData = await setupResp.json();

                if (setupData.success) {
                    alert(`✅ Shared account setup successful!\n\nAccount: ${setupData.account_info.channel_name}\n\nAll users can now download freely!`);
                    localStorage.setItem('yt_authenticated', 'true');
                    const btn = document.getElementById('ytAuthBtn');
                    if (btn) btn.classList.add('authenticated');
                } else {
                    alert(`❌ Failed to save as shared account:\n\n${setupData.error || setupData.message}`);
                }
            } catch (err) {
                console.error('Error saving shared account:', err);
                alert('❌ Error: ' + err.message);
            }
        } else {
            localStorage.setItem('yt_authenticated', 'true');
            const btn = document.getElementById('ytAuthBtn');
            if (btn) btn.classList.add('authenticated');
            alert('✅ You are now authenticated. Your personal account will be used for downloads.');
        }
    };

    // This function starts the flow from the main window.
    window.startGoogleOAuth = async function() {
        try {
            const resp = await fetch(`${API_BASE}/api/oauth2authorize`, {
                method: 'GET'
            });
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
            const popupName = 'jaydl_google_oauth_' + Date.now();
            const popup = window.open(authUrl, popupName, 'width=900,height=700,scrollbars=yes,resizable=yes');
            if (!popup) {
                alert('Popup blocked. Please allow popups and try again.');
            }

        } catch (err) {
            console.error('startGoogleOAuth error:', err);
            alert('Error starting OAuth: ' + err.message);
        }
    };

    // If this script is running in a popup, execute the redirect handler.
    // Otherwise, this code does nothing and just sets up the global functions for the main window.
    if (window.opener) {
        handlePopupRedirect();
    }

    // Expose revoke function
    window.revokeOAuth = async function() {
        try {
            const resp = await fetch(`${API_BASE}/api/oauth2logout`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
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