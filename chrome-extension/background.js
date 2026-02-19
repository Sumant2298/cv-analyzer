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
    setBadge:       () => handleSetBadge(msg.text, _sender, sendResponse),
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

// ── Badge handler ───────────────────────────────────────────────────────────

async function handleSetBadge(text, sender, sendResponse) {
  try {
    const tabId = sender && sender.tab && sender.tab.id;
    if (tabId) {
      await chrome.action.setBadgeText({ text: text || '', tabId });
      await chrome.action.setBadgeBackgroundColor({ color: '#6366f1', tabId });
    }
  } catch (e) {
    console.error('[LevelUpX BG] setBadge error:', e);
  }
  if (sendResponse) sendResponse({ success: true });
}

// ── Broader job page detection via tab URL listener ─────────────────────────

const KNOWN_ATS_PATTERNS = [
  'myworkdayjobs.com', 'greenhouse.io', 'lever.co',
  'naukri.com', 'linkedin.com', 'ashbyhq.com',
  'bamboohr.com', 'icims.com', 'smartrecruiters.com', 'jobvite.com',
  'gem.com',
];

const JOB_URL_SIGNALS = [
  '/apply', '/application', '/career', '/jobs/', '/job/',
  '/hiring', '/talent', '/recruit', '/opening', '/position',
];

const CONTENT_SCRIPTS_TO_INJECT = [
  'adapters/base-adapter.js', 'adapters/greenhouse.js',
  'adapters/lever.js', 'adapters/workday.js',
  'adapters/naukri.js', 'adapters/linkedin.js',
  'adapters/ashby.js',
  'content/field-detector.js', 'content/field-filler.js',
  'content/dom-waiters.js', 'content/button-finder.js',
  'content/step-orchestrator.js', 'content/content.js',
];

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete' || !tab.url) return;

  const url = tab.url.toLowerCase();

  // Skip known ATS domains — content scripts already auto-injected via manifest
  if (KNOWN_ATS_PATTERNS.some(p => url.includes(p))) return;

  // Skip non-http(s) URLs
  if (!url.startsWith('http')) return;

  // Check for job-application-like URL signals
  if (!JOB_URL_SIGNALS.some(s => url.includes(s))) return;

  // Verify user is authenticated before injecting
  const token = await getToken();
  if (!token) return;

  // Inject content scripts on-demand for job-like pages
  try {
    await chrome.scripting.insertCSS({
      target: { tabId },
      files: ['styles/content.css'],
    });
    await chrome.scripting.executeScript({
      target: { tabId },
      files: CONTENT_SCRIPTS_TO_INJECT,
    });
    console.log('[LevelUpX BG] Injected scripts on job-like URL:', tab.url);
  } catch (e) {
    // Injection may fail on restricted pages — that's OK
    console.log('[LevelUpX BG] Could not inject on:', tab.url, e.message);
  }
});
