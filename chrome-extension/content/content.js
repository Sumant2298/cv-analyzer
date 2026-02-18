/**
 * LevelUpX AutoFill — Content Script
 *
 * Injected on supported career sites. Detects platform, shows floating panel,
 * orchestrates form filling via platform adapters.
 */

(function () {
  'use strict';

  // Prevent double-injection
  if (window._levelupxInjected) return;
  window._levelupxInjected = true;

  const ADAPTERS = [
    window.LevelUpXGreenhouse,
    window.LevelUpXLever,
    window.LevelUpXWorkday,
    window.LevelUpXNaukri,
    window.LevelUpXLinkedIn,
  ].filter(Boolean);

  let currentAdapter = null;
  let panel = null;
  let profileCache = null;

  // ── Platform detection ─────────────────────────────────────────────────

  function detectAdapter() {
    const host = location.hostname;
    for (const adapter of ADAPTERS) {
      if (adapter.matchesHost(host)) {
        return adapter;
      }
    }
    return null;
  }

  // ── Floating panel ─────────────────────────────────────────────────────

  function createPanel() {
    if (panel) return;
    panel = document.createElement('div');
    panel.id = 'levelupx-autofill-panel';
    panel.innerHTML = `
      <div class="lux-panel-header">
        <span class="lux-panel-logo">L</span>
        <span class="lux-panel-title">LevelUpX</span>
        <button class="lux-panel-close" title="Close">&times;</button>
      </div>
      <button class="lux-panel-fill-btn" id="lux-fill-btn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>
        Auto-fill from Resume
      </button>
      <div class="lux-panel-status" id="lux-status"></div>
    `;

    document.body.appendChild(panel);

    // Close button
    panel.querySelector('.lux-panel-close').addEventListener('click', () => {
      panel.style.display = 'none';
    });

    // Fill button
    panel.querySelector('#lux-fill-btn').addEventListener('click', () => {
      fillForm();
    });

    // Make draggable
    makeDraggable(panel);
  }

  function makeDraggable(el) {
    const header = el.querySelector('.lux-panel-header');
    let isDragging = false;
    let offsetX, offsetY;

    header.addEventListener('mousedown', (e) => {
      if (e.target.classList.contains('lux-panel-close')) return;
      isDragging = true;
      const rect = el.getBoundingClientRect();
      offsetX = e.clientX - rect.left;
      offsetY = e.clientY - rect.top;
      el.style.transition = 'none';
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      el.style.right = 'auto';
      el.style.bottom = 'auto';
      el.style.left = (e.clientX - offsetX) + 'px';
      el.style.top = (e.clientY - offsetY) + 'px';
    });

    document.addEventListener('mouseup', () => {
      isDragging = false;
      el.style.transition = '';
    });
  }

  function showStatus(text, isError = false) {
    const statusEl = document.getElementById('lux-status');
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.className = 'lux-panel-status ' + (isError ? 'lux-error' : 'lux-success');
    setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'lux-panel-status'; }, 5000);
  }

  // ── Fill logic ─────────────────────────────────────────────────────────

  async function fillForm(sendResponse) {
    const btn = document.getElementById('lux-fill-btn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Filling...';
    }

    try {
      // Get profile from background
      const profile = await new Promise((resolve, reject) => {
        chrome.runtime.sendMessage({ action: 'getProfile' }, (resp) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }
          if (resp && resp.error) {
            reject(new Error(resp.error));
            return;
          }
          resolve(resp);
        });
      });

      if (!profile || !profile.basics) {
        throw new Error('No profile data. Connect the extension first.');
      }
      profileCache = profile;

      if (!currentAdapter) {
        throw new Error('No supported form detected on this page');
      }

      // Let adapter fill the form
      const container = document.body;
      const result = currentAdapter.fill(container, profile);
      const filledCount = result ? (result.filledCount || 0) : 0;

      // Try to upload resume file
      let resumeUploaded = false;
      try {
        resumeUploaded = await uploadResume(container);
      } catch (e) {
        console.warn('[LevelUpX] Resume upload skipped:', e.message);
      }

      const msg = `Filled ${filledCount} field${filledCount !== 1 ? 's' : ''}` +
                  (resumeUploaded ? ' + uploaded resume' : '');
      showStatus(msg);

      if (sendResponse) sendResponse({ success: true, filledCount, resumeUploaded });
    } catch (err) {
      console.error('[LevelUpX] Fill error:', err);
      showStatus(err.message, true);
      if (sendResponse) sendResponse({ success: false, error: err.message });
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg> Auto-fill from Resume';
      }
    }
  }

  async function uploadResume(container) {
    if (!currentAdapter) return false;
    const fileInput = currentAdapter.getResumeInput(container);
    if (!fileInput) return false;

    // Get resume file from background
    const fileData = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ action: 'getResumeFile' }, (resp) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (resp && resp.error) {
          reject(new Error(resp.error));
          return;
        }
        resolve(resp);
      });
    });

    if (!fileData || !fileData.data) return false;

    return await window.LevelUpXFiller.setFileInput(
      fileInput, fileData.data, fileData.filename, fileData.type
    );
  }

  // ── Message handler (from popup) ───────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.action === 'fillForm') {
      fillForm(sendResponse);
      return true; // async
    }
    if (msg.action === 'ping') {
      sendResponse({ ready: true, adapter: currentAdapter ? currentAdapter.name : null });
      return false;
    }
  });

  // ── Init ───────────────────────────────────────────────────────────────

  function init() {
    currentAdapter = detectAdapter();
    if (!currentAdapter) return;

    // Check if we're on an application form
    if (!currentAdapter.isApplicationForm()) {
      // Watch for SPA navigation
      setupObserver();
      return;
    }

    // Check if user is authenticated
    chrome.runtime.sendMessage({ action: 'checkAuth' }, (resp) => {
      if (resp && resp.authenticated) {
        createPanel();
      }
    });
  }

  function setupObserver() {
    // Watch for SPA page changes (Workday, LinkedIn)
    let lastUrl = location.href;
    const observer = new MutationObserver(() => {
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        currentAdapter = detectAdapter();
        if (currentAdapter && currentAdapter.isApplicationForm()) {
          chrome.runtime.sendMessage({ action: 'checkAuth' }, (resp) => {
            if (resp && resp.authenticated) {
              createPanel();
            }
          });
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // Wait for DOM ready, then initialize
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    // Small delay to let other content scripts (adapters) load
    setTimeout(init, 200);
  }

})();
