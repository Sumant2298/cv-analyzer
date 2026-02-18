/**
 * LevelUpX AutoFill — Popup Script
 *
 * Handles connection flow, profile display, and fill trigger.
 */

document.addEventListener('DOMContentLoaded', init);

async function init() {
  showState('loading');
  console.log('[LevelUpX Popup] Checking auth...');

  chrome.runtime.sendMessage({ action: 'checkAuth' }, (resp) => {
    if (chrome.runtime.lastError) {
      console.error('[LevelUpX Popup] checkAuth error:', chrome.runtime.lastError.message);
      showState('disconnected');
      return;
    }
    console.log('[LevelUpX Popup] checkAuth response:', resp);
    if (resp && resp.authenticated) {
      showProfile(resp.profile);
      showState('connected');
    } else {
      showState('disconnected');
    }
  });
}

function showState(state) {
  document.getElementById('state-loading').classList.add('hidden');
  document.getElementById('state-disconnected').classList.add('hidden');
  document.getElementById('state-connected').classList.add('hidden');
  document.getElementById('state-' + state)?.classList.remove('hidden');
}

async function connect() {
  const input = document.getElementById('token-input');
  const btn = document.getElementById('connect-btn');
  const errEl = document.getElementById('connect-error');
  const token = input.value.trim();

  if (!token) {
    errEl.textContent = 'Please paste your API token';
    errEl.classList.remove('hidden');
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Connecting...';
  errEl.classList.add('hidden');

  console.log('[LevelUpX Popup] Connecting with token:', token.slice(0, 8) + '...');

  chrome.runtime.sendMessage({ action: 'setToken', token }, (resp) => {
    console.log('[LevelUpX Popup] setToken response:', resp, 'lastError:', chrome.runtime.lastError);

    btn.disabled = false;
    btn.textContent = 'Connect';

    // Check for Chrome runtime errors (service worker disconnected, etc.)
    if (chrome.runtime.lastError) {
      console.error('[LevelUpX Popup] Runtime error:', chrome.runtime.lastError.message);
      errEl.textContent = 'Extension error: ' + chrome.runtime.lastError.message;
      errEl.classList.remove('hidden');
      return;
    }

    // Check for undefined response (shouldn't happen if background is running)
    if (!resp) {
      console.error('[LevelUpX Popup] No response from background script');
      errEl.textContent = 'No response from extension. Try reloading the extension.';
      errEl.classList.remove('hidden');
      return;
    }

    if (resp.success) {
      console.log('[LevelUpX Popup] Connected successfully!');
      showProfile(resp.profile);
      showState('connected');
      showStatus('Connected successfully!');
    } else {
      console.log('[LevelUpX Popup] Connection failed:', resp.error);
      errEl.textContent = resp.error || 'Connection failed. Check if token is valid.';
      errEl.classList.remove('hidden');
    }
  });
}

function disconnect() {
  chrome.runtime.sendMessage({ action: 'logout' }, () => {
    if (chrome.runtime.lastError) {
      console.error('[LevelUpX Popup] logout error:', chrome.runtime.lastError.message);
    }
    showState('disconnected');
    document.getElementById('token-input').value = '';
  });
}

function showProfile(profile) {
  if (!profile || !profile.basics) return;
  const b = profile.basics;
  const name = b.fullName || `${b.firstName} ${b.lastName}`.trim() || 'User';
  document.getElementById('profile-name').textContent = name;
  document.getElementById('profile-email').textContent = b.email || '\u2014';
  document.getElementById('profile-resume').textContent = profile.resumeLabel || 'Resume';
  // Avatar initials
  const initials = name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
  document.getElementById('profile-avatar').textContent = initials || '?';
}

async function fillCurrentPage() {
  const btn = document.getElementById('fill-btn');
  btn.disabled = true;
  btn.textContent = 'Filling...';

  try {
    // Get the active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      showStatus('No active tab found', true);
      return;
    }

    console.log('[LevelUpX Popup] Sending fill command to tab', tab.id);

    // Send fill command to content script
    chrome.tabs.sendMessage(tab.id, { action: 'fillForm' }, (resp) => {
      btn.disabled = false;
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg> Auto-fill Current Page';

      if (chrome.runtime.lastError) {
        console.error('[LevelUpX Popup] Fill error:', chrome.runtime.lastError.message);
        showStatus('This page is not a supported career site', true);
        return;
      }
      console.log('[LevelUpX Popup] Fill response:', resp);
      if (resp && resp.success) {
        showStatus(`Filled ${resp.filledCount || 0} fields!`);
      } else {
        showStatus((resp && resp.error) || 'Could not find form fields', true);
      }
    });
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg> Auto-fill Current Page';
    showStatus(err.message, true);
  }
}

function showStatus(text, isError = false) {
  const bar = document.getElementById('status-bar');
  const textEl = document.getElementById('status-text');
  bar.classList.remove('hidden', 'error-state');
  if (isError) bar.classList.add('error-state');
  textEl.textContent = text;
  setTimeout(() => bar.classList.add('hidden'), 4000);
}

// Allow Enter key to connect
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !document.getElementById('state-disconnected').classList.contains('hidden')) {
    connect();
  }
});
