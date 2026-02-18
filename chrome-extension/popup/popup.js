/**
 * LevelUpX AutoFill — Popup Script
 *
 * Handles connection flow, profile display, and fill trigger.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Attach all event listeners (inline onclick is blocked by Manifest V3 CSP)
  document.getElementById('connect-btn').addEventListener('click', connect);
  document.getElementById('fill-btn').addEventListener('click', fillCurrentPage);
  document.getElementById('disconnect-btn').addEventListener('click', disconnect);
  document.getElementById('token-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') connect();
  });
  init();
});

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

const FILL_BTN_HTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg> Auto-fill Current Page';

function resetFillBtn() {
  const btn = document.getElementById('fill-btn');
  btn.disabled = false;
  btn.innerHTML = FILL_BTN_HTML;
}

async function fillCurrentPage() {
  const btn = document.getElementById('fill-btn');
  btn.disabled = true;
  btn.textContent = 'Filling...';

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      resetFillBtn();
      showStatus('No active tab found', true);
      return;
    }

    console.log('[LevelUpX Popup] Sending fill command to tab', tab.id, tab.url);

    // Try sending to existing content script first
    chrome.tabs.sendMessage(tab.id, { action: 'fillForm' }, async (resp) => {
      if (chrome.runtime.lastError) {
        // Content script not loaded yet — inject on-demand and retry
        console.log('[LevelUpX Popup] No content script, injecting on-demand...');
        try {
          await injectAndFill(tab.id);
        } catch (e) {
          console.error('[LevelUpX Popup] Inject failed:', e);
          resetFillBtn();
          showStatus('Could not auto-fill this page. Open a job application form and try again.', true);
        }
        return;
      }
      resetFillBtn();
      console.log('[LevelUpX Popup] Fill response:', resp);
      if (resp && resp.success) {
        showStatus(`Filled ${resp.filledCount || 0} fields!`);
      } else {
        showStatus((resp && resp.error) || 'No form fields found on this page', true);
      }
    });
  } catch (err) {
    resetFillBtn();
    showStatus(err.message, true);
  }
}

async function injectAndFill(tabId) {
  // Programmatically inject all content scripts + CSS
  await chrome.scripting.insertCSS({
    target: { tabId },
    files: ['styles/content.css'],
  });
  await chrome.scripting.executeScript({
    target: { tabId },
    files: [
      'adapters/base-adapter.js',
      'adapters/greenhouse.js',
      'adapters/lever.js',
      'adapters/workday.js',
      'adapters/naukri.js',
      'adapters/linkedin.js',
      'content/field-detector.js',
      'content/field-filler.js',
      'content/content.js',
    ],
  });

  console.log('[LevelUpX Popup] Scripts injected, waiting for init...');
  await new Promise(r => setTimeout(r, 600));

  // Now send the fill command
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, { action: 'fillForm' }, (resp) => {
      resetFillBtn();
      if (chrome.runtime.lastError) {
        showStatus('Could not auto-fill this page', true);
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (resp && resp.success) {
        showStatus(`Filled ${resp.filledCount || 0} fields!`);
      } else {
        showStatus((resp && resp.error) || 'No form fields found', true);
      }
      resolve(resp);
    });
  });
}

function showStatus(text, isError = false) {
  const bar = document.getElementById('status-bar');
  const textEl = document.getElementById('status-text');
  bar.classList.remove('hidden', 'error-state');
  if (isError) bar.classList.add('error-state');
  textEl.textContent = text;
  setTimeout(() => bar.classList.add('hidden'), 4000);
}

// Event listeners are attached in DOMContentLoaded handler above
