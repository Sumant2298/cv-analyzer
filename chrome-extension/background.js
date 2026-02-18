/**
 * LevelUpX AutoFill — Background Service Worker
 *
 * Manages API token storage and makes all API calls to LevelUpX backend.
 * Content scripts and popup communicate via chrome.runtime.sendMessage().
 */

const API_BASE = 'https://levelupx.ai';

// ── Message handler ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  console.log('[LevelUpX BG] Message received:', msg.action);

  const handlers = {
    checkAuth:      () => handleCheckAuth(sendResponse),
    setToken:       () => handleSetToken(msg.token, sendResponse),
    logout:         () => handleLogout(sendResponse),
    getProfile:     () => handleGetProfile(sendResponse),
    getResumeFile:  () => handleGetResumeFile(sendResponse),
  };

  const handler = handlers[msg.action];
  if (handler) {
    handler();
    return true; // async response — keeps message channel open
  }
  return false;
});

// ── Auth helpers ─────────────────────────────────────────────────────────────

async function getToken() {
  const data = await chrome.storage.sync.get('levelupx_token');
  return data.levelupx_token || null;
}

async function handleCheckAuth(sendResponse) {
  try {
    const token = await getToken();
    if (!token) {
      console.log('[LevelUpX BG] checkAuth: no token stored');
      sendResponse({ authenticated: false });
      return;
    }
    console.log('[LevelUpX BG] checkAuth: validating token...');
    const resp = await fetch(`${API_BASE}/api/extension/profile`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    console.log('[LevelUpX BG] checkAuth: API status', resp.status);
    if (resp.ok) {
      const profile = await resp.json();
      console.log('[LevelUpX BG] checkAuth: authenticated as', profile.basics?.fullName);
      sendResponse({ authenticated: true, profile });
    } else {
      console.log('[LevelUpX BG] checkAuth: token rejected');
      sendResponse({ authenticated: false, error: 'Invalid token' });
    }
  } catch (err) {
    console.error('[LevelUpX BG] checkAuth error:', err);
    sendResponse({ authenticated: false, error: err.message });
  }
}

async function handleSetToken(token, sendResponse) {
  console.log('[LevelUpX BG] setToken: validating token...');
  try {
    const resp = await fetch(`${API_BASE}/api/extension/profile`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    console.log('[LevelUpX BG] setToken: API status', resp.status);
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      console.log('[LevelUpX BG] setToken: API error:', data);
      sendResponse({ success: false, error: data.error || `API error (${resp.status})` });
      return;
    }
    const profile = await resp.json();
    console.log('[LevelUpX BG] setToken: profile received for', profile.basics?.fullName);
    await chrome.storage.sync.set({ levelupx_token: token });
    console.log('[LevelUpX BG] setToken: token stored successfully');
    sendResponse({ success: true, profile });
  } catch (err) {
    console.error('[LevelUpX BG] setToken error:', err);
    sendResponse({ success: false, error: 'Network error: ' + err.message });
  }
}

async function handleLogout(sendResponse) {
  try {
    await chrome.storage.sync.remove('levelupx_token');
    console.log('[LevelUpX BG] logout: token removed');
    sendResponse({ success: true });
  } catch (err) {
    console.error('[LevelUpX BG] logout error:', err);
    sendResponse({ success: false, error: err.message });
  }
}

// ── API calls ────────────────────────────────────────────────────────────────

async function handleGetProfile(sendResponse) {
  try {
    const token = await getToken();
    if (!token) {
      sendResponse({ error: 'Not connected' });
      return;
    }
    console.log('[LevelUpX BG] getProfile: fetching...');
    const resp = await fetch(`${API_BASE}/api/extension/profile`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    console.log('[LevelUpX BG] getProfile: API status', resp.status);
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      sendResponse({ error: data.error || 'Failed to fetch profile' });
      return;
    }
    sendResponse(await resp.json());
  } catch (err) {
    console.error('[LevelUpX BG] getProfile error:', err);
    sendResponse({ error: err.message });
  }
}

async function handleGetResumeFile(sendResponse) {
  try {
    const token = await getToken();
    if (!token) {
      sendResponse({ error: 'Not connected' });
      return;
    }
    console.log('[LevelUpX BG] getResumeFile: fetching...');
    const resp = await fetch(`${API_BASE}/api/extension/resume-file`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    console.log('[LevelUpX BG] getResumeFile: API status', resp.status);
    if (!resp.ok) {
      sendResponse({ error: 'Failed to fetch resume file' });
      return;
    }
    const blob = await resp.blob();
    // Convert blob to base64 for transfer to content script
    const reader = new FileReader();
    reader.onload = () => {
      const contentDisposition = resp.headers.get('Content-Disposition') || '';
      const filenameMatch = contentDisposition.match(/filename="?([^";\n]+)"?/);
      sendResponse({
        data: reader.result, // data URL (base64)
        filename: filenameMatch ? filenameMatch[1] : 'resume.pdf',
        type: blob.type,
      });
    };
    reader.onerror = () => sendResponse({ error: 'Failed to read file' });
    reader.readAsDataURL(blob);
  } catch (err) {
    console.error('[LevelUpX BG] getResumeFile error:', err);
    sendResponse({ error: err.message });
  }
}
