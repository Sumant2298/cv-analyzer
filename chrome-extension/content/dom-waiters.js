/**
 * LevelUpX AutoFill — DOM Waiting Utilities
 *
 * Promise-based helpers for waiting on DOM state changes.
 * Used by the step orchestrator to wait for modals, step transitions, etc.
 */

window.LevelUpXWaiters = {

  /**
   * Wait for an element matching a selector to appear in the DOM.
   * @param {string} selector - CSS selector
   * @param {number} timeoutMs - max wait time (default 8000)
   * @param {Element} root - observe within (default document.body)
   * @returns {Promise<Element>}
   */
  waitForElement(selector, timeoutMs = 8000, root = document.body) {
    return new Promise((resolve, reject) => {
      // Check if already present
      const existing = (root || document.body).querySelector(selector);
      if (existing) { resolve(existing); return; }

      let observer;
      const timer = setTimeout(() => {
        if (observer) observer.disconnect();
        reject(new Error(`waitForElement timeout: "${selector}" not found after ${timeoutMs}ms`));
      }, timeoutMs);

      observer = new MutationObserver(() => {
        const el = (root || document.body).querySelector(selector);
        if (el) {
          clearTimeout(timer);
          observer.disconnect();
          resolve(el);
        }
      });

      observer.observe(root || document.body, { childList: true, subtree: true });
    });
  },

  /**
   * Wait for an element matching a selector to be removed from the DOM.
   * Useful for waiting for loading spinners to disappear.
   * @param {string} selector
   * @param {number} timeoutMs
   * @returns {Promise<void>}
   */
  waitForElementRemoval(selector, timeoutMs = 8000) {
    return new Promise((resolve, reject) => {
      // Check if already gone
      if (!document.querySelector(selector)) { resolve(); return; }

      let observer;
      const timer = setTimeout(() => {
        if (observer) observer.disconnect();
        reject(new Error(`waitForElementRemoval timeout: "${selector}" still present after ${timeoutMs}ms`));
      }, timeoutMs);

      observer = new MutationObserver(() => {
        if (!document.querySelector(selector)) {
          clearTimeout(timer);
          observer.disconnect();
          resolve();
        }
      });

      observer.observe(document.body, { childList: true, subtree: true });
    });
  },

  /**
   * Wait for the DOM to settle — no mutations for `quietMs` milliseconds.
   * Critical after clicking Next: React/Angular re-render multiple times,
   * and we need to wait until rendering is complete.
   * @param {number} quietMs - ms of no DOM changes to consider settled (default 400)
   * @param {number} timeoutMs - max wait (default 5000)
   * @returns {Promise<void>}
   */
  waitForDomSettle(quietMs = 400, timeoutMs = 5000) {
    return new Promise((resolve) => {
      let quietTimer;
      let observer;

      const maxTimer = setTimeout(() => {
        clearTimeout(quietTimer);
        if (observer) observer.disconnect();
        resolve(); // Resolve even on timeout — best effort
      }, timeoutMs);

      const resetQuietTimer = () => {
        clearTimeout(quietTimer);
        quietTimer = setTimeout(() => {
          clearTimeout(maxTimer);
          if (observer) observer.disconnect();
          resolve();
        }, quietMs);
      };

      observer = new MutationObserver(() => {
        resetQuietTimer();
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        characterData: true,
      });

      // Start the quiet timer immediately
      resetQuietTimer();
    });
  },

  /**
   * Wait for an element to become visible (not just in DOM, but computed visible).
   * @param {string} selector
   * @param {number} timeoutMs
   * @returns {Promise<Element>}
   */
  waitForVisible(selector, timeoutMs = 8000) {
    return new Promise((resolve, reject) => {
      const checkVisible = () => {
        const el = document.querySelector(selector);
        if (el && el.offsetParent !== null) return el;
        if (el) {
          const rect = el.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) return el;
        }
        return null;
      };

      const existing = checkVisible();
      if (existing) { resolve(existing); return; }

      let observer;
      const timer = setTimeout(() => {
        if (observer) observer.disconnect();
        reject(new Error(`waitForVisible timeout: "${selector}" not visible after ${timeoutMs}ms`));
      }, timeoutMs);

      observer = new MutationObserver(() => {
        const el = checkVisible();
        if (el) {
          clearTimeout(timer);
          observer.disconnect();
          resolve(el);
        }
      });

      observer.observe(document.body, { childList: true, subtree: true, attributes: true });
    });
  },

  /**
   * Simple delay (setTimeout wrapped in Promise).
   * @param {number} ms
   * @returns {Promise<void>}
   */
  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  },
};
