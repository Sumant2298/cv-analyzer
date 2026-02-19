/**
 * LevelUpX AutoFill — Content Script
 *
 * Injected on supported career sites. Detects platform, shows floating panel,
 * orchestrates form filling via platform adapters.
 * Supports single-shot fill AND fully agentic multi-step navigation.
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
  let agenticRunning = false;

  // ── Platform detection ─────────────────────────────────────────────────

  function detectAdapter() {
    const host = location.hostname;
    // Try platform-specific adapters first
    for (const adapter of ADAPTERS) {
      if (adapter.matchesHost(host)) {
        console.log('[LevelUpX] Detected platform:', adapter.name);
        return adapter;
      }
    }
    // Fallback: try each adapter's form detector even if host doesn't match
    // (covers embedded Greenhouse forms, custom career domains, etc.)
    for (const adapter of ADAPTERS) {
      if (adapter.isApplicationForm()) {
        console.log('[LevelUpX] Detected form matching adapter:', adapter.name);
        return adapter;
      }
    }
    // Last resort: generic form detection for unknown ATS platforms
    const hasApplyForm = document.querySelector(
      'form[action*="apply"], form[action*="submit"], form[action*="job"], ' +
      'form[action*="application"], form[action*="candidate"]'
    );
    const hasApplyClasses = document.querySelector(
      '[class*="apply"], [class*="application"], [class*="job-form"], ' +
      '[class*="candidate"], [class*="career"]'
    );
    const hasNameEmail = (
      document.querySelector('input[name*="first_name"], input[name*="name"]') &&
      document.querySelector('input[type="email"], input[name*="email"]')
    );
    // Check for any form with 3+ visible inputs
    let hasSubstantialForm = false;
    for (const form of document.querySelectorAll('form')) {
      const inputs = form.querySelectorAll('input:not([type="hidden"]), textarea, select');
      if (inputs.length >= 3) { hasSubstantialForm = true; break; }
    }

    if (hasApplyForm || hasNameEmail || (hasApplyClasses && hasSubstantialForm)) {
      console.log('[LevelUpX] Detected generic application form');
      return ADAPTERS.find(a => a.name === 'Greenhouse') || ADAPTERS[0];
    }
    return null;
  }

  /**
   * Ensure we have a working adapter — creates generic fallback if needed.
   */
  function ensureAdapter() {
    if (!currentAdapter) {
      currentAdapter = detectAdapter();
    }
    if (!currentAdapter) {
      console.log('[LevelUpX] No specific adapter found, using generic label-scanner');
      currentAdapter = window.LevelUpXBaseAdapter.create({
        name: 'Generic',
        hostPatterns: [],
        formDetector() {
          return !!document.querySelector('form') &&
                 !!(document.querySelector('input:not([type="hidden"]), textarea, select'));
        },
        fieldMap() { return {}; },
        resumeInputSelectors: ['input[type="file"]'],
      });
    }
    return currentAdapter;
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
      <button class="lux-panel-apply-btn" id="lux-apply-btn">
        &#9889; Full Apply (Auto-navigate)
      </button>
      <div class="lux-panel-progress hidden" id="lux-progress">
        <span class="lux-panel-progress-text" id="lux-progress-text">Starting...</span>
        <button class="lux-panel-abort-btn" id="lux-abort-btn" title="Stop">&#9632; Stop</button>
      </div>
      <button class="lux-panel-submit-btn hidden" id="lux-submit-btn">
        &#10003; Confirm Submit
      </button>
      <div class="lux-panel-status" id="lux-status"></div>
    `;

    document.body.appendChild(panel);

    // Close button
    panel.querySelector('.lux-panel-close').addEventListener('click', () => {
      panel.style.display = 'none';
    });

    // Fill button (single-shot)
    panel.querySelector('#lux-fill-btn').addEventListener('click', () => {
      fillForm();
    });

    // Full Apply button (agentic)
    panel.querySelector('#lux-apply-btn').addEventListener('click', () => {
      runAgenticApply();
    });

    // Abort button
    panel.querySelector('#lux-abort-btn').addEventListener('click', () => {
      abortAgentic();
    });

    // Confirm Submit button
    panel.querySelector('#lux-submit-btn').addEventListener('click', () => {
      handleConfirmSubmit();
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

  // ── Panel state helpers ──────────────────────────────────────────────

  function showAgenticUI(show) {
    const applyBtn = document.getElementById('lux-apply-btn');
    const fillBtn = document.getElementById('lux-fill-btn');
    const progress = document.getElementById('lux-progress');
    const submitBtn = document.getElementById('lux-submit-btn');

    if (show) {
      if (applyBtn) applyBtn.classList.add('hidden');
      if (fillBtn) fillBtn.classList.add('hidden');
      if (progress) progress.classList.remove('hidden');
      if (submitBtn) submitBtn.classList.add('hidden');
    } else {
      if (applyBtn) applyBtn.classList.remove('hidden');
      if (fillBtn) fillBtn.classList.remove('hidden');
      if (progress) progress.classList.add('hidden');
      if (submitBtn) submitBtn.classList.add('hidden');
    }
  }

  function updateProgress(text) {
    const el = document.getElementById('lux-progress-text');
    if (el) el.textContent = text;
  }

  function showSubmitConfirmation() {
    const progress = document.getElementById('lux-progress');
    const submitBtn = document.getElementById('lux-submit-btn');
    if (progress) progress.classList.add('hidden');
    if (submitBtn) submitBtn.classList.remove('hidden');
  }

  function resetPanelToDefault() {
    showAgenticUI(false);
    agenticRunning = false;
  }

  // ── Single-shot fill logic ───────────────────────────────────────────

  async function fillForm(sendResponse) {
    const btn = document.getElementById('lux-fill-btn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Filling...';
    }

    try {
      // Get profile from background
      const profile = await getProfile();
      ensureAdapter();

      // Let adapter fill the form
      const container = document.body;
      const result = await currentAdapter.fill(container, profile);
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

  // ── Agentic apply logic ──────────────────────────────────────────────

  async function runAgenticApply(sendResponse) {
    if (agenticRunning) {
      if (sendResponse) sendResponse({ success: false, error: 'Agentic apply already running' });
      return;
    }

    const Orchestrator = window.LevelUpXOrchestrator;
    if (!Orchestrator) {
      const msg = 'Orchestrator not loaded. Please reload the extension.';
      showStatus(msg, true);
      if (sendResponse) sendResponse({ success: false, error: msg });
      return;
    }

    agenticRunning = true;
    showAgenticUI(true);
    updateProgress('Starting...');

    try {
      const profile = await getProfile();
      ensureAdapter();

      const result = await Orchestrator.run(currentAdapter, profile, (status) => {
        // Status callback from orchestrator
        updateProgress(status.message || 'Working...');
        // Notify popup if listening
        try {
          chrome.runtime.sendMessage({
            action: 'agenticStatus',
            status: status,
          });
        } catch { /* popup may be closed */ }
      });

      if (result.awaitingSubmit) {
        // Show Confirm Submit button — user must explicitly click
        showSubmitConfirmation();
        showStatus('Ready to submit! Review and click Confirm.', false);
        if (sendResponse) sendResponse({
          success: true,
          awaitingSubmit: true,
          stepsCompleted: result.stepsCompleted,
          totalFilled: result.totalFilled,
        });
      } else {
        // Completed (no submit found, or aborted)
        resetPanelToDefault();
        const msg = result.aborted
          ? 'Stopped by user'
          : `Done! ${result.stepsCompleted} step${result.stepsCompleted !== 1 ? 's' : ''}, ${result.totalFilled} fields filled`;
        showStatus(msg, result.aborted);
        if (sendResponse) sendResponse({
          success: !result.aborted,
          stepsCompleted: result.stepsCompleted,
          totalFilled: result.totalFilled,
        });
      }
    } catch (err) {
      console.error('[LevelUpX] Agentic apply error:', err);
      resetPanelToDefault();
      showStatus(err.message, true);
      if (sendResponse) sendResponse({ success: false, error: err.message });
    }
  }

  async function handleConfirmSubmit(sendResponse) {
    const Orchestrator = window.LevelUpXOrchestrator;
    const ButtonFinder = window.LevelUpXButtonFinder;
    if (!ButtonFinder) {
      if (sendResponse) sendResponse({ success: false, error: 'ButtonFinder not loaded' });
      return;
    }

    updateProgress('Submitting...');
    const submitBtn = document.getElementById('lux-submit-btn');
    if (submitBtn) submitBtn.classList.add('hidden');

    try {
      // Merge platform submit hints with generic defaults
      const stepConfig = currentAdapter ? currentAdapter.getStepConfig() : null;
      const submitTexts = [
        ...(stepConfig && stepConfig.submitButtonText ? stepConfig.submitButtonText : []),
        'Submit application', 'Submit', 'Send Application', 'Complete Application', 'Confirm & Submit',
      ];
      const submitSelectors = (stepConfig && stepConfig.submitButtonSelectors) || [];

      const container = (stepConfig && stepConfig.formContainerSelector)
        ? (document.querySelector(stepConfig.formContainerSelector) || document.body)
        : document.body;

      const clicked = ButtonFinder.findAndClick(container, submitTexts, submitSelectors);

      resetPanelToDefault();
      agenticRunning = false;

      if (clicked) {
        showStatus('Application submitted!', false);
        if (sendResponse) sendResponse({ success: true });
      } else {
        showStatus('Could not find Submit button. Please submit manually.', true);
        if (sendResponse) sendResponse({ success: false, error: 'Submit button not found' });
      }
    } catch (err) {
      resetPanelToDefault();
      showStatus('Submit failed: ' + err.message, true);
      if (sendResponse) sendResponse({ success: false, error: err.message });
    }
  }

  function abortAgentic() {
    const Orchestrator = window.LevelUpXOrchestrator;
    if (Orchestrator) {
      Orchestrator.abort();
    }
    resetPanelToDefault();
    agenticRunning = false;
    showStatus('Stopped', true);
  }

  // ── Shared helpers ───────────────────────────────────────────────────

  async function getProfile() {
    if (profileCache) return profileCache;

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
    return profile;
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
    if (msg.action === 'startAgenticApply') {
      runAgenticApply(sendResponse);
      return true; // async
    }
    if (msg.action === 'confirmSubmit') {
      handleConfirmSubmit(sendResponse);
      return true; // async
    }
    if (msg.action === 'abortAgenticApply') {
      abortAgentic();
      sendResponse({ success: true });
      return false;
    }
    if (msg.action === 'ping') {
      sendResponse({
        ready: true,
        adapter: currentAdapter ? currentAdapter.name : null,
        agenticRunning: agenticRunning,
      });
      return false;
    }
  });

  // ── Init ───────────────────────────────────────────────────────────────

  function init() {
    console.log('[LevelUpX] Content script init on', location.hostname);
    currentAdapter = detectAdapter();

    if (currentAdapter) {
      // Check if user is authenticated, then show panel
      chrome.runtime.sendMessage({ action: 'checkAuth' }, (resp) => {
        if (chrome.runtime.lastError) return;
        if (resp && resp.authenticated) {
          createPanel();
        }
      });
    }

    // Always set up observer for SPA navigation
    setupObserver();
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
