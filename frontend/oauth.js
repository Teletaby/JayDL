// oauth.js — Start Google OAuth flow (same-window redirect) and manage authentication
(function() {
    function getBackendUrl() {
        const protocol = window.location.protocol;
        const hostname = window.location.hostname;
        const port = window.location.port;
        if (hostname === 'localhost' || hostname === '127.0.0.1') {
            return `${protocol}//${hostname}:5000`; // Local dev backend
        }
        if (hostname.includes('onrender.com')) {
            return 'https://jaydl-backend.onrender.com'; // Deployed backend
        }
        // Fallback for other environments
        return `${protocol}//${hostname}${port ? ':' + port : ''}`; 
    }

    const API_BASE = getBackendUrl();

    // This function starts the OAuth flow from the main window.
    window.startGoogleOAuth = function() {
        // Redirect the current page to the backend authorization endpoint.
        // The backend will handle the redirect to Google.
        console.log('Starting Google OAuth flow...');
        window.location.href = `${API_BASE}/api/oauth2authorize`;
    };

    // This is the final step, called only AFTER the main window has been authenticated.
    window.authenticationComplete = async function() {
        console.log('Authentication complete. Checking for shared account setup.');

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
                    const btn = document.getElementById('adminAuthBtn');
                    if (btn) {
                        btn.classList.add('authenticated');
                        btn.innerHTML = '<i class="fas fa-check-circle"></i> Shared Account Set';
                    }
                } else {
                    alert(`❌ Failed to save as shared account:\n\n${setupData.error || setupData.message}`);
                }
            } catch (err) {
                console.error('Error saving shared account:', err);
                alert('❌ Error: ' + err.message);
            }
        } else {
            localStorage.setItem('yt_authenticated', 'true');
            const btn = document.getElementById('adminAuthBtn');
            if (btn) {
                btn.classList.add('authenticated');
                btn.innerHTML = '<i class="fas fa-check"></i> Authenticated (Personal)';
            }
            alert('✅ You are now authenticated. Your personal account will be used for downloads.');
        }
    };

    // This function is called on page load to handle the redirect back from OAuth.
    function handleOAuthRedirect() {
        const urlParams = new URLSearchParams(window.location.search);
        const authStatus = urlParams.get('auth_status');
        const error = urlParams.get('error');

        if (!authStatus) {
            return; // Not an OAuth redirect.
        }

        // Clean the URL to remove the auth parameters.
        const cleanUrl = window.location.protocol + "//" + window.location.host + window.location.pathname;
        window.history.replaceState({}, document.title, cleanUrl);

        if (authStatus === 'success') {
            console.log('Main window session authenticated via redirect.');
            // Now that the main window is authenticated, run the final completion logic.
            window.authenticationComplete();
        } else if (authStatus === 'failed') {
            let errorMessage = '❌ YouTube authentication failed';
            switch (error) {
                case 'access_denied':
                    errorMessage = '❌ Access denied. Please grant permission to access YouTube.';
                    break;
                case 'invalid_state':
                    errorMessage = '❌ Invalid authentication state (CSRF). Please try again.';
                    break;
                case 'callback_failed':
                    errorMessage = '❌ Authentication callback failed. Please try again.';
                    break;
                default:
                    errorMessage = `❌ Authentication error: ${error || 'Unknown error'}`;
            }
            alert(errorMessage);
        }
    }

    // Expose revoke function
    window.revokeOAuth = async function() {
        try {
            const resp = await fetch(`${API_BASE}/api/oauth2logout`, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const data = await resp.json();
            if (data.success) {
                localStorage.removeItem('yt_authenticated');
                const btn = document.getElementById('adminAuthBtn');
                if (btn) {
                    btn.classList.remove('authenticated');
                    btn.innerHTML = '<i class="fab fa-google"></i> Authenticate with Google';
                }
                alert('✅ YouTube authentication revoked successfully.');
            } else {
                alert('❌ Failed to revoke authentication: ' + (data.error || 'Unknown error'));
            }
        } catch (err) {
            console.error('revokeOAuth error:', err);
            alert('Error revoking OAuth: ' + err.message);
        }
    };

    // Run the redirect handler on page load.
    document.addEventListener('DOMContentLoaded', handleOAuthRedirect);
})();