/**
 * LevelUpX AutoFill — Field Detector
 *
 * Multi-strategy form field detection. Finds input/textarea/select elements
 * using various matching strategies.
 */

window.LevelUpXDetector = {

  /**
   * Find field by CSS selector.
   */
  bySelector(container, selector) {
    try {
      return container.querySelector(selector);
    } catch { return null; }
  },

  /**
   * Find field by input name attribute (exact or partial match).
   */
  byName(container, name, exact = false) {
    if (exact) {
      return container.querySelector(`input[name="${name}"], textarea[name="${name}"], select[name="${name}"]`);
    }
    const all = container.querySelectorAll('input, textarea, select');
    const nameLower = name.toLowerCase();
    for (const el of all) {
      const elName = (el.getAttribute('name') || '').toLowerCase();
      if (elName.includes(nameLower)) return el;
    }
    return null;
  },

  /**
   * Find field by associated label text (case-insensitive partial match).
   */
  byLabelText(container, text) {
    const textLower = text.toLowerCase();
    const labels = container.querySelectorAll('label');
    for (const label of labels) {
      if (label.textContent.toLowerCase().includes(textLower)) {
        // Check for "for" attribute
        const forId = label.getAttribute('for');
        if (forId) {
          const target = container.querySelector(`#${CSS.escape(forId)}`);
          if (target) return target;
        }
        // Check for nested input
        const nested = label.querySelector('input, textarea, select');
        if (nested) return nested;
        // Check next sibling
        const next = label.nextElementSibling;
        if (next && (next.tagName === 'INPUT' || next.tagName === 'TEXTAREA' || next.tagName === 'SELECT')) {
          return next;
        }
        // Check parent's next input
        const parent = label.closest('.field, .form-group, .form-field, [class*="field"], [class*="input"]');
        if (parent) {
          const input = parent.querySelector('input, textarea, select');
          if (input) return input;
        }
      }
    }
    return null;
  },

  /**
   * Find field by placeholder text (case-insensitive partial match).
   */
  byPlaceholder(container, text) {
    const textLower = text.toLowerCase();
    const all = container.querySelectorAll('input[placeholder], textarea[placeholder]');
    for (const el of all) {
      if (el.placeholder.toLowerCase().includes(textLower)) return el;
    }
    return null;
  },

  /**
   * Find field by data-automation-id (Workday).
   */
  byDataAutomation(container, id) {
    return container.querySelector(`[data-automation-id="${id}"]`) ||
           container.querySelector(`[data-automation-id*="${id}"]`);
  },

  /**
   * Find field by aria-label (case-insensitive partial match).
   */
  byAriaLabel(container, label) {
    const labelLower = label.toLowerCase();
    const all = container.querySelectorAll('[aria-label]');
    for (const el of all) {
      if (el.getAttribute('aria-label').toLowerCase().includes(labelLower)) return el;
    }
    return null;
  },

  /**
   * Find file input element.
   */
  fileInput(container, hints = []) {
    // Try specific selectors first
    for (const hint of hints) {
      const el = this.bySelector(container, hint);
      if (el) return el;
    }
    // Generic file input
    return container.querySelector('input[type="file"]');
  },

  /**
   * Try multiple strategies in order to find a field.
   * @param {Element} container - Container to search in
   * @param {Array} strategies - [{method, args}] e.g. [{method:'byName', args:['first_name']}, {method:'byLabelText', args:['First Name']}]
   * @returns {Element|null}
   */
  findField(container, strategies) {
    for (const strat of strategies) {
      const fn = this[strat.method];
      if (!fn) continue;
      const el = fn.call(this, container, ...strat.args);
      if (el && el.offsetParent !== null) return el; // visible element
    }
    // Second pass: include hidden elements
    for (const strat of strategies) {
      const fn = this[strat.method];
      if (!fn) continue;
      const el = fn.call(this, container, ...strat.args);
      if (el) return el;
    }
    return null;
  },
};
