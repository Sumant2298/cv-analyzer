/**
 * LevelUpX AutoFill — Button Finder
 *
 * Locates action buttons (Apply, Next, Continue, Submit) using multiple
 * strategies: CSS selectors, text matching, aria-labels.
 * Uses React/Angular-compatible click dispatching.
 */

window.LevelUpXButtonFinder = {

  /**
   * Find a clickable element by matching its visible text, aria-label,
   * or data attributes against a list of candidate strings.
   * @param {Element} container - search scope
   * @param {string[]} textCandidates - e.g. ['Next', 'Continue']
   * @param {string[]} selectorHints - optional platform-specific CSS selectors to try first
   * @returns {Element|null}
   */
  findByText(container, textCandidates, selectorHints = []) {
    // 1. Try selector hints first (platform-specific, most reliable)
    for (const sel of selectorHints) {
      try {
        const el = container.querySelector(sel);
        if (el && this._isVisible(el)) return el;
      } catch { /* invalid selector */ }
    }

    // 2. Scan all button-like elements
    const candidates = container.querySelectorAll(
      'button, a[role="button"], [type="submit"], input[type="submit"], ' +
      '[role="button"], a[class*="btn"], a[class*="button"]'
    );

    const normalizedTexts = textCandidates.map(t => t.toLowerCase().trim());

    // 3. Exact text match pass (prefer exact over partial)
    for (const el of candidates) {
      if (!this._isVisible(el)) continue;
      const elText = (el.textContent || el.value || '').trim().toLowerCase();
      const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
      const title = (el.getAttribute('title') || '').toLowerCase();

      for (const needle of normalizedTexts) {
        if (elText === needle || ariaLabel === needle || title === needle) {
          return el;
        }
      }
    }

    // 4. Partial text match pass (fallback)
    for (const el of candidates) {
      if (!this._isVisible(el)) continue;
      const elText = (el.textContent || el.value || '').trim().toLowerCase();
      const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();

      for (const needle of normalizedTexts) {
        if (elText.includes(needle) || ariaLabel.includes(needle)) {
          return el;
        }
      }
    }

    return null;
  },

  /**
   * Check if an element is visible on the page.
   * @param {Element} el
   * @returns {boolean}
   */
  _isVisible(el) {
    if (!el) return false;
    if (el.offsetParent !== null) return true;
    // Fixed-position elements have null offsetParent
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  },

  /**
   * Check if a button is enabled and clickable.
   * @param {Element} el
   * @returns {boolean}
   */
  isClickable(el) {
    if (!el) return false;
    if (el.disabled) return false;
    if (el.getAttribute('aria-disabled') === 'true') return false;
    if (!this._isVisible(el)) return false;
    // Check for common loading/disabled class patterns
    const classes = (el.className || '').toLowerCase();
    if (classes.includes('loading') || classes.includes('disabled') || classes.includes('spinner')) {
      return false;
    }
    return true;
  },

  /**
   * Click a button with proper event sequence for React/Angular compatibility.
   * Some frameworks listen on mousedown/mouseup, not just click.
   * @param {Element} el
   * @returns {boolean}
   */
  safeClick(el) {
    if (!el) return false;
    try {
      // Scroll into view
      el.scrollIntoView({ block: 'center', behavior: 'instant' });

      // Focus the element
      el.focus();

      // Full mouse event sequence for React/Angular
      el.dispatchEvent(new MouseEvent('mousedown', {
        bubbles: true, cancelable: true, view: window
      }));
      el.dispatchEvent(new MouseEvent('mouseup', {
        bubbles: true, cancelable: true, view: window
      }));
      el.dispatchEvent(new MouseEvent('click', {
        bubbles: true, cancelable: true, view: window
      }));

      console.log(`[LevelUpX] Clicked button: "${(el.textContent || '').trim().slice(0, 40)}"`);
      return true;
    } catch (err) {
      console.error('[LevelUpX] safeClick failed:', err);
      return false;
    }
  },

  /**
   * Find and click a button. Combines findByText + isClickable + safeClick.
   * @param {Element} container
   * @param {string[]} textCandidates
   * @param {string[]} selectorHints
   * @returns {boolean} - true if button found and clicked
   */
  findAndClick(container, textCandidates, selectorHints = []) {
    const el = this.findByText(container, textCandidates, selectorHints);
    if (!el) {
      console.log(`[LevelUpX] Button not found: [${textCandidates.join(', ')}]`);
      return false;
    }
    if (!this.isClickable(el)) {
      console.log(`[LevelUpX] Button found but not clickable: "${(el.textContent || '').trim().slice(0, 40)}"`);
      return false;
    }
    return this.safeClick(el);
  },
};
