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
   * Robust label-to-input resolver. Given a label-like element, finds
   * the associated input/textarea/select using 8 progressive strategies.
   * Works on React, Angular, Vue forms with arbitrary DOM structures.
   *
   * @param {Element} container - The form container to search within
   * @param {Element} label - The label (or label-like) element
   * @returns {Element|null} The associated input element, or null
   */
  findInputNearLabel(container, label) {
    const INPUT_TAGS = ['INPUT', 'TEXTAREA', 'SELECT'];

    // Strategy 1: label[for] → #id (standard HTML association)
    const forId = label.getAttribute('for');
    if (forId) {
      try {
        const el = container.querySelector(`#${CSS.escape(forId)}`);
        if (el) return el;
      } catch { /* invalid selector */ }
    }

    // Strategy 2: Nested input inside label
    const nested = label.querySelector('input, textarea, select');
    if (nested) return nested;

    // Strategy 3: Direct next sibling IS the input
    const next = label.nextElementSibling;
    if (next && INPUT_TAGS.includes(next.tagName)) return next;

    // Strategy 4: Next sibling is a wrapper div containing the input
    if (next) {
      const inside = next.querySelector('input, textarea, select');
      if (inside) return inside;
    }

    // Strategy 5: aria-labelledby back-reference
    // (input has aria-labelledby pointing to this label's id)
    const labelId = label.id || label.getAttribute('id');
    if (labelId) {
      try {
        const ariaRef = container.querySelector(`[aria-labelledby="${CSS.escape(labelId)}"]`);
        if (ariaRef) {
          if (INPUT_TAGS.includes(ariaRef.tagName)) return ariaRef;
          const insideAria = ariaRef.querySelector('input, textarea, select');
          if (insideAria) return insideAria;
        }
      } catch { /* invalid selector */ }
    }

    // Strategy 6: Walk up parent chain (up to 5 levels)
    // Look for the nearest ancestor that contains exactly 1 input
    let ancestor = label.parentElement;
    for (let i = 0; i < 5 && ancestor && ancestor !== container; i++) {
      const inputs = ancestor.querySelectorAll('input:not([type="hidden"]), textarea, select');
      if (inputs.length === 1) return inputs[0];
      // If 2-4 inputs, find the one that belongs to THIS label
      if (inputs.length > 1 && inputs.length <= 4) {
        for (const inp of inputs) {
          const inpId = inp.id;
          if (inpId) {
            try {
              const ownerLabel = ancestor.querySelector(`label[for="${CSS.escape(inpId)}"]`);
              if (ownerLabel && ownerLabel !== label) continue; // owned by DIFFERENT label
              if (ownerLabel && ownerLabel === label) return inp; // owned by THIS label
            } catch { /* invalid selector */ }
          }
          const inpLabel = inp.closest('label');
          if (inpLabel && inpLabel !== label) continue; // nested inside different label
          // No label association — skip (don't default to first)
        }
      }
      ancestor = ancestor.parentElement;
    }

    // Strategy 7: Closest common container with known class patterns
    const parent = label.closest(
      '.field, .form-group, .form-field, .form-row, .form-item, .form__field, ' +
      '[class*="field"], [class*="input"], [class*="question"], [class*="form-row"], ' +
      '[class*="FormField"], [class*="formField"], [class*="form_field"], ' +
      '[data-field], [data-qa], [data-testid]'
    );
    if (parent) {
      const input = parent.querySelector('input:not([type="hidden"]), textarea, select');
      if (input) return input;
    }

    // Strategy 8: Scan ALL following siblings (up to 5)
    let sibling = label.nextElementSibling;
    let sibCount = 0;
    while (sibling && sibCount < 5) {
      if (INPUT_TAGS.includes(sibling.tagName)) return sibling;
      const inside = sibling.querySelector('input, textarea, select');
      if (inside) return inside;
      sibling = sibling.nextElementSibling;
      sibCount++;
    }

    return null;
  },

  /**
   * Find a radio button group near a label element.
   * Simplified version of findInputNearLabel targeting radio inputs specifically.
   * Returns the first radio found — caller can use its name to find the full group.
   * @param {Element} container - Form container
   * @param {Element} label - The label element
   * @returns {Element|null} A radio button element, or null
   */
  findRadioGroupNearLabel(container, label) {
    // Strategy 1: label[for] → radio by id
    const forId = label.getAttribute('for');
    if (forId) {
      try {
        const el = container.querySelector(`#${CSS.escape(forId)}`);
        if (el && (el.getAttribute('type') || '').toLowerCase() === 'radio') return el;
      } catch { /* ignore */ }
    }

    // Strategy 2: Nested radio inside label
    const nested = label.querySelector('input[type="radio"]');
    if (nested) return nested;

    // Strategy 3: Next sibling or its children
    const next = label.nextElementSibling;
    if (next) {
      if (next.tagName === 'INPUT' && (next.getAttribute('type') || '').toLowerCase() === 'radio') return next;
      const inside = next.querySelector('input[type="radio"]');
      if (inside) return inside;
    }

    // Strategy 4: Walk up parent chain (5 levels) looking for radios
    let ancestor = label.parentElement;
    for (let i = 0; i < 5 && ancestor && ancestor !== container; i++) {
      const radios = ancestor.querySelectorAll('input[type="radio"]');
      if (radios.length > 0) return radios[0];
      ancestor = ancestor.parentElement;
    }

    // Strategy 5: Closest form-group container
    const parent = label.closest(
      '.field, .form-group, .form-field, .form-row, .form-item, ' +
      '[class*="field"], [class*="question"], [class*="radio"], ' +
      '[class*="FormField"], [data-field], [data-qa], [data-testid]'
    );
    if (parent) {
      const radio = parent.querySelector('input[type="radio"]');
      if (radio) return radio;
    }

    // Strategy 6: Scan following siblings
    let sibling = label.nextElementSibling;
    let sibCount = 0;
    while (sibling && sibCount < 5) {
      if (sibling.tagName === 'INPUT' && (sibling.getAttribute('type') || '').toLowerCase() === 'radio') return sibling;
      const inside = sibling.querySelector('input[type="radio"]');
      if (inside) return inside;
      sibling = sibling.nextElementSibling;
      sibCount++;
    }

    return null;
  },

  /**
   * Find a React-Select or custom dropdown component near a label element.
   * Returns the custom select wrapper/control element, or null.
   * @param {Element} container - Form container
   * @param {Element} label - The label element
   * @returns {Element|null}
   */
  findCustomSelectNearLabel(container, label) {
    const CUSTOM_SEL = [
      '[class*="select__control"]',
      '[class*="select-container"]',
      '[class*="selectContainer"]',
      '[class*="Select-control"]',
      '[role="combobox"]',
      '[role="listbox"]',
      '[class*="Dropdown"][class*="select"]',
      'input[aria-autocomplete="list"]',
      'input[aria-haspopup="listbox"]',
    ];
    const combinedSelector = CUSTOM_SEL.join(', ');

    // Strategy 1: label[for] → element might be inside a custom select
    const forId = label.getAttribute('for');
    if (forId) {
      try {
        const el = container.querySelector(`#${CSS.escape(forId)}`);
        if (el) {
          let cur = el;
          for (let i = 0; i < 4 && cur; i++) {
            try { if (cur.matches && cur.matches(combinedSelector)) return cur; } catch {}
            cur = cur.parentElement;
          }
        }
      } catch { /* ignore */ }
    }

    // Strategy 2: Next sibling or its children
    const next = label.nextElementSibling;
    if (next) {
      try { if (next.matches && next.matches(combinedSelector)) return next; } catch {}
      try {
        const inside = next.querySelector(combinedSelector);
        if (inside) return inside;
      } catch {}
    }

    // Strategy 3: Walk up parent chain (5 levels)
    let ancestor = label.parentElement;
    for (let i = 0; i < 5 && ancestor && ancestor !== container; i++) {
      try {
        const custom = ancestor.querySelector(combinedSelector);
        if (custom) return custom;
      } catch {}
      ancestor = ancestor.parentElement;
    }

    // Strategy 4: Closest form-group container
    const parent = label.closest(
      '.field, .form-group, .form-field, .form-row, .form-item, ' +
      '[class*="field"], [class*="question"], [class*="FormField"], ' +
      '[data-field], [data-qa], [data-testid]'
    );
    if (parent) {
      try {
        const custom = parent.querySelector(combinedSelector);
        if (custom) return custom;
      } catch {}
    }

    // Strategy 5: Scan following siblings
    let sibling = label.nextElementSibling;
    let sibCount = 0;
    while (sibling && sibCount < 5) {
      try { if (sibling.matches && sibling.matches(combinedSelector)) return sibling; } catch {}
      try {
        const inside = sibling.querySelector(combinedSelector);
        if (inside) return inside;
      } catch {}
      sibling = sibling.nextElementSibling;
      sibCount++;
    }

    return null;
  },

  /**
   * Find a checkbox group near a label element.
   * Returns the container element holding the checkboxes, or null.
   * @param {Element} container - Form container
   * @param {Element} label - The label element
   * @returns {Element|null}
   */
  findCheckboxGroupNearLabel(container, label) {
    // Strategy 1: Next sibling contains checkboxes
    const next = label.nextElementSibling;
    if (next) {
      const cbs = next.querySelectorAll('input[type="checkbox"]');
      if (cbs.length > 0) return next;
    }

    // Strategy 2: Parent chain — look for a container with 2+ checkboxes
    let ancestor = label.parentElement;
    for (let i = 0; i < 5 && ancestor && ancestor !== container; i++) {
      const cbs = ancestor.querySelectorAll('input[type="checkbox"]');
      if (cbs.length >= 2) return ancestor;
      ancestor = ancestor.parentElement;
    }

    // Strategy 3: Closest form-group-like container
    const parent = label.closest(
      '.field, .form-group, .form-field, .form-row, .form-item, ' +
      '[class*="field"], [class*="question"], [class*="checkbox-group"], ' +
      '[class*="FormField"], [data-field], [data-qa], [data-testid]'
    );
    if (parent) {
      const cbs = parent.querySelectorAll('input[type="checkbox"]');
      if (cbs.length > 0) return parent;
    }

    // Strategy 4: Scan following siblings
    let sibling = label.nextElementSibling;
    let sibCount = 0;
    while (sibling && sibCount < 5) {
      const cbs = sibling.querySelectorAll('input[type="checkbox"]');
      if (cbs.length > 0) return sibling;
      sibling = sibling.nextElementSibling;
      sibCount++;
    }

    return null;
  },

  /**
   * Find field by associated label text (case-insensitive partial match).
   * Uses findInputNearLabel() for robust label-to-input resolution.
   */
  byLabelText(container, text) {
    const textLower = text.toLowerCase();
    const labels = container.querySelectorAll('label');
    for (const label of labels) {
      if (label.textContent.toLowerCase().includes(textLower)) {
        const el = this.findInputNearLabel(container, label);
        if (el) return el;
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
