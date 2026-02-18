/**
 * LevelUpX AutoFill — Background Service Worker
 *
 * Manages API token storage and makes all API calls to LevelUpX backend.
 * Content scripts and popup communicate via chrome.runtime.sendMessage().
 */

const API_BASE = 'https://levelupx.ai';

// ── Message handler ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
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
    return true; // async response
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
      sendResponse({ authenticated: false });
      return;
    }
    // Validate token by fetching profile
    const resp = await fetch(`${API_BASE}/api/extension/profile`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    if (resp.ok) {
      const profile = await resp.json();
      sendResponse({ authenticated: true, profile });
    } else {
      sendResponse({ authenticated: false, error: 'Invalid token' });
    }
  } catch (err) {
    sendResponse({ authenticated: false, error: err.message });
  }
}

async function handleSetToken(token, sendResponse) {
  try {
    // Validate before storing
    const resp = await fetch(`${API_BASE}/api/extension/profile`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      sendResponse({ success: false, error: data.error || 'Invalid token' });
      return;
    }
    const profile = await resp.json();
    await chrome.storage.sync.set({ levelupx_token: token });
    sendResponse({ success: true, profile });
  } catch (err) {
    sendResponse({ success: false, error: err.message });
  }
}

async function handleLogout(sendResponse) {
  await chrome.storage.sync.remove('levelupx_token');
  sendResponse({ success: true });
}

// ── API calls ────────────────────────────────────────────────────────────────

async function handleGetProfile(sendResponse) {
  try {
    const token = await getToken();
    if (!token) {
      sendResponse({ error: 'Not connected' });
      return;
    }
    const resp = await fetch(`${API_BASE}/api/extension/profile`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      sendResponse({ error: data.error || 'Failed to fetch profile' });
      return;
    }
    sendResponse(await resp.json());
  } catch (err) {
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
    const resp = await fetch(`${API_BASE}/api/extension/resume-file`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
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
    sendResponse({ error: err.message });
  }
}
