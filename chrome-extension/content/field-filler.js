/**
 * LevelUpX AutoFill — Field Filler
 *
 * React/Angular-compatible value setting.
 * Dispatches proper events so frameworks pick up changes.
 * Supports native inputs, native selects, React-Select custom dropdowns,
 * and radio button groups with intelligent value matching.
 */

window.LevelUpXFiller = {

  /** Pending async fills (custom selects). Call flushAsyncFills() to await. */
  _pendingAsyncFills: [],

  /**
   * Set a text input/textarea value in a React-compatible way.
   * @param {HTMLElement} el - The input/textarea element
   * @param {string} value - Value to set
   * @returns {boolean} true if value was set
   */
  setText(el, value) {
    if (!el || !value) return false;

    // Skip if already has the correct value
    if (el.value === value) return true;

    // Focus the element
    el.focus();
    el.click();

    // Use React's internal setter to bypass controlled component checks
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    )?.set;
    const nativeTextareaValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value'
    )?.set;

    const setter = el.tagName === 'TEXTAREA' ? nativeTextareaValueSetter : nativeInputValueSetter;
    if (setter) {
      setter.call(el, value);
    } else {
      el.value = value;
    }

    // Dispatch events in the correct order for React/Angular/Vue
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));

    return el.value === value;
  },

  /**
   * Set a native <select> element's value.
   * Tries exact match then partial text match.
   * @param {HTMLSelectElement} el
   * @param {string} value - The option value or text to select
   * @returns {boolean}
   */
  setSelect(el, value) {
    if (!el || !value) return false;
    const valueLower = value.toLowerCase().trim();

    // Try exact value match first
    for (const opt of el.options) {
      if (opt.value.toLowerCase() === valueLower || opt.textContent.toLowerCase().trim() === valueLower) {
        el.value = opt.value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
    }
    // Try partial text match (option text contains value)
    for (const opt of el.options) {
      if (opt.textContent.toLowerCase().includes(valueLower)) {
        el.value = opt.value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
    }
    // Try reverse partial (value contains option text) — e.g. "Yes" matching "Yes, I am"
    for (const opt of el.options) {
      const optText = opt.textContent.toLowerCase().trim();
      if (optText && optText.length > 1 && valueLower.includes(optText)) {
        el.value = opt.value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
    }
    return false;
  },

  /**
   * Handle React-Select and custom dropdown components.
   * These render as <div> trees instead of native <select>.
   * @param {HTMLElement} el - An element inside or near the custom select
   * @param {string} value - Value to match against option text
   * @returns {Promise<boolean>}
   */
  async setReactSelect(el, value) {
    if (!el || !value) return false;
    const valueLower = value.toLowerCase().trim();

    // ── Step 1: Find the custom select wrapper ──────────────────
    const WRAPPER_PATTERNS = [
      '[class*="select__control"]',
      '[class*="-control"]',
      '[class*="select-container"]',
      '[class*="selectContainer"]',
      '[class*="Select-control"]',
      '[role="combobox"]',
      '[role="listbox"]',
      '[data-testid*="select"]',
    ];

    let wrapper = null;
    let current = el;
    for (let i = 0; i < 6 && current; i++) {
      for (const sel of WRAPPER_PATTERNS) {
        try {
          if (current.matches && current.matches(sel)) { wrapper = current; break; }
        } catch { /* ignore */ }
      }
      if (wrapper) break;
      // Check if current contains a control child
      if (current.querySelector) {
        try {
          const ctrl = current.querySelector(
            '[class*="select__control"], [class*="-control"], [role="combobox"]'
          );
          if (ctrl) { wrapper = current; break; }
        } catch { /* ignore */ }
      }
      current = current.parentElement;
    }

    if (!wrapper) {
      console.log('[LevelUpX] React-Select wrapper not found for', el);
      return false;
    }

    // ── Step 2: Click to open the dropdown ──────────────────────
    const control = wrapper.querySelector(
      '[class*="select__control"], [class*="-control"], ' +
      '[class*="select__value-container"], [role="combobox"]'
    ) || wrapper;

    const mouseOpts = { bubbles: true, cancelable: true };
    control.dispatchEvent(new MouseEvent('mousedown', mouseOpts));
    control.dispatchEvent(new MouseEvent('mouseup', mouseOpts));
    control.dispatchEvent(new MouseEvent('click', mouseOpts));

    // If there's a searchable input, type the value to filter options
    const searchInput = wrapper.querySelector(
      'input[role="combobox"], input[type="text"], input[aria-autocomplete]'
    );
    if (searchInput) {
      const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
      )?.set;
      const searchTerm = value.length > 30 ? value.slice(0, 30) : value;
      if (nativeSetter) {
        nativeSetter.call(searchInput, searchTerm);
      } else {
        searchInput.value = searchTerm;
      }
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      searchInput.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // ── Step 3: Wait for options to appear ──────────────────────
    // React-Select renders menu in a portal (appended to <body>),
    // so search the entire document.
    const OPTION_SELECTOR = '[role="option"], [class*="option"]:not([class*="control"]), [class*="menu"] li';
    let options = [];
    for (let attempt = 0; attempt < 40; attempt++) {
      await new Promise(r => setTimeout(r, 50));
      options = document.querySelectorAll(OPTION_SELECTOR);
      if (options.length > 0) break;
    }
    if (options.length === 0) {
      console.log('[LevelUpX] No React-Select options appeared for value:', value);
      return false;
    }

    // ── Step 4: Match option text to value ──────────────────────
    let match = null;

    // Pass 1: exact match
    for (const opt of options) {
      const text = opt.textContent.trim().toLowerCase();
      if (text === valueLower) { match = opt; break; }
    }
    // Pass 2: partial match (option contains value OR value contains option)
    if (!match) {
      for (const opt of options) {
        const text = opt.textContent.trim().toLowerCase();
        if (text.includes(valueLower) || valueLower.includes(text)) { match = opt; break; }
      }
    }
    // Pass 3: Yes/No normalization
    if (!match) {
      const YES_WORDS = ['yes', 'true', '1', 'y'];
      const NO_WORDS = ['no', 'false', '0', 'n'];
      const isYes = YES_WORDS.includes(valueLower);
      const isNo = NO_WORDS.includes(valueLower);
      if (isYes || isNo) {
        const target = isYes ? 'yes' : 'no';
        for (const opt of options) {
          const text = opt.textContent.trim().toLowerCase();
          if (text.startsWith(target)) { match = opt; break; }
        }
      }
    }

    if (!match) {
      console.log('[LevelUpX] No matching React-Select option for:', value,
        'Available:', [...options].map(o => o.textContent.trim()).slice(0, 10));
      // Close the dropdown by pressing Escape
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      return false;
    }

    // ── Step 5: Click the matching option ───────────────────────
    match.dispatchEvent(new MouseEvent('mousedown', mouseOpts));
    match.dispatchEvent(new MouseEvent('mouseup', mouseOpts));
    match.dispatchEvent(new MouseEvent('click', mouseOpts));

    console.log('[LevelUpX] React-Select filled:', value, '→', match.textContent.trim());
    return true;
  },

  /**
   * Fill a radio button group by matching value to radio labels.
   * @param {HTMLElement} container - Form container to search within
   * @param {HTMLInputElement} el - One radio button from the group
   * @param {string} value - Value to match against radio option labels
   * @returns {boolean}
   */
  setRadioGroup(container, el, value) {
    if (!el || !value) return false;
    const valueLower = String(value).toLowerCase().trim();

    // Collect all radios in the same group
    const name = el.getAttribute('name');
    let radios;
    if (name) {
      try {
        radios = container.querySelectorAll(`input[type="radio"][name="${CSS.escape(name)}"]`);
      } catch {
        radios = [el];
      }
    } else {
      // Fallback: find radios near this element (walk up 3 levels)
      let ancestor = el.parentElement;
      for (let i = 0; i < 3 && ancestor; i++) ancestor = ancestor.parentElement;
      radios = ancestor ? ancestor.querySelectorAll('input[type="radio"]') : [el];
    }

    // Build map of radio → label text
    const radioLabels = [];
    for (const radio of radios) {
      let labelText = '';
      // Strategy 1: label[for=id]
      if (radio.id) {
        try {
          const lbl = container.querySelector(`label[for="${CSS.escape(radio.id)}"]`);
          if (lbl) labelText = lbl.textContent.trim();
        } catch { /* ignore */ }
      }
      // Strategy 2: enclosing <label>
      if (!labelText) {
        const enclosing = radio.closest('label');
        if (enclosing) labelText = enclosing.textContent.trim();
      }
      // Strategy 3: next sibling (text node or element)
      if (!labelText) {
        let next = radio.nextSibling;
        if (next && next.nodeType === Node.TEXT_NODE) labelText = next.textContent.trim();
        if (!labelText && next && next.tagName) labelText = next.textContent.trim();
        // Also check next element sibling
        if (!labelText) {
          const nextEl = radio.nextElementSibling;
          if (nextEl && nextEl.tagName !== 'INPUT') labelText = nextEl.textContent.trim();
        }
      }
      // Strategy 4: aria-label
      if (!labelText) {
        labelText = radio.getAttribute('aria-label') || '';
      }
      // Strategy 5: value attribute as last resort
      if (!labelText) {
        labelText = radio.getAttribute('value') || '';
      }
      radioLabels.push({ radio, labelText: labelText.toLowerCase().trim() });
    }

    // ── Matching logic ──────────────────────────────────────────
    const YES_WORDS = ['yes', 'true', '1', 'y'];
    const NO_WORDS = ['no', 'false', '0', 'n'];
    const isYes = YES_WORDS.includes(valueLower);
    const isNo = NO_WORDS.includes(valueLower);
    let match = null;

    // Pass 1: exact match
    for (const { radio, labelText } of radioLabels) {
      if (labelText === valueLower) { match = radio; break; }
    }

    // Pass 2: Yes/No normalization
    if (!match && (isYes || isNo)) {
      const target = isYes ? 'yes' : 'no';
      for (const { radio, labelText } of radioLabels) {
        if (labelText.startsWith(target) || labelText === target) { match = radio; break; }
      }
    }

    // Pass 3: partial match (label contains value or value contains label)
    if (!match) {
      for (const { radio, labelText } of radioLabels) {
        if (labelText && (labelText.includes(valueLower) || valueLower.includes(labelText))) {
          match = radio;
          break;
        }
      }
    }

    if (!match) {
      console.log('[LevelUpX] No matching radio for:', value,
        'Options:', radioLabels.map(r => r.labelText).filter(Boolean));
      return false;
    }

    // Click with full event sequence for React compatibility
    match.focus();
    const mouseOpts = { bubbles: true, cancelable: true };
    match.dispatchEvent(new MouseEvent('mousedown', mouseOpts));
    match.dispatchEvent(new MouseEvent('mouseup', mouseOpts));
    match.dispatchEvent(new MouseEvent('click', mouseOpts));
    match.dispatchEvent(new Event('change', { bubbles: true }));

    console.log('[LevelUpX] Radio filled:', value, '→', match.value || 'checked');
    return match.checked;
  },

  /**
   * Set a checkbox value.
   * @param {HTMLInputElement} el
   * @param {boolean} checked
   */
  setCheckbox(el, checked) {
    if (!el) return false;
    if (el.checked !== checked) {
      el.click();
    }
    return el.checked === checked;
  },

  /**
   * Set a file input using DataTransfer API.
   * @param {HTMLInputElement} el - file input element
   * @param {string} dataUrl - base64 data URL of the file
   * @param {string} filename - e.g. "resume.pdf"
   * @param {string} mimeType - e.g. "application/pdf"
   * @returns {boolean}
   */
  async setFileInput(el, dataUrl, filename, mimeType) {
    if (!el || !dataUrl) return false;

    try {
      // Convert data URL to blob
      const resp = await fetch(dataUrl);
      const blob = await resp.blob();
      const file = new File([blob], filename, { type: mimeType });

      // Use DataTransfer to set file programmatically
      const dt = new DataTransfer();
      dt.items.add(file);
      el.files = dt.files;

      // Dispatch change event
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('input', { bubbles: true }));

      return el.files.length > 0;
    } catch (err) {
      console.error('[LevelUpX] File upload failed:', err);
      return false;
    }
  },

  /**
   * Check if an element is an input inside a custom select component.
   * @param {HTMLElement} el
   * @returns {boolean}
   */
  _isCustomSelectInput(el) {
    if (!el || el.tagName !== 'INPUT') return false;
    if (el.getAttribute('role') === 'combobox') return true;
    if (el.getAttribute('aria-autocomplete')) return true;
    if (el.getAttribute('aria-haspopup') === 'listbox') return true;

    // Check parent for select-like classes (up to 3 levels)
    let parent = el.parentElement;
    for (let i = 0; i < 3 && parent; i++) {
      const cls = (parent.className || '').toString().toLowerCase();
      if (cls.includes('select') && (cls.includes('control') || cls.includes('container') || cls.includes('wrapper'))) {
        return true;
      }
      if (parent.getAttribute && (
        parent.getAttribute('role') === 'combobox' ||
        parent.getAttribute('role') === 'listbox'
      )) {
        return true;
      }
      parent = parent.parentElement;
    }
    return false;
  },

  /**
   * Fill a single field: auto-detect type and route to appropriate handler.
   * @param {HTMLElement} el - The field element
   * @param {*} value - Value to fill
   * @param {HTMLElement} [container] - Form container (needed for radio groups)
   * @returns {boolean}
   */
  fill(el, value, container) {
    if (!el || value === undefined || value === null || value === '') return false;

    const tag = el.tagName;
    const type = (el.getAttribute('type') || '').toLowerCase();

    if (tag === 'SELECT') {
      return this.setSelect(el, String(value));
    }
    if (type === 'checkbox') {
      return this.setCheckbox(el, !!value);
    }
    if (type === 'radio') {
      // Use intelligent radio group matching instead of blind click
      return this.setRadioGroup(container || document.body, el, String(value));
    }

    // Check if this input is part of a custom select (React-Select, etc.)
    if (this._isCustomSelectInput(el)) {
      // Queue async custom select fill with fallback to setText
      this._pendingAsyncFills.push(
        this.setReactSelect(el, String(value)).then(success => {
          if (!success) {
            // Fallback: try filling as regular text input
            return this.setText(el, String(value));
          }
          return success;
        })
      );
      return true; // optimistic return; async fill is queued
    }

    // Default: text/textarea
    return this.setText(el, String(value));
  },

  /**
   * Flush all pending async fills (custom selects).
   * Call this after all sync fills are done.
   * @returns {Promise<number>} number of successfully filled fields
   */
  async flushAsyncFills() {
    if (!this._pendingAsyncFills || this._pendingAsyncFills.length === 0) return 0;
    const results = await Promise.allSettled(this._pendingAsyncFills);
    this._pendingAsyncFills = [];
    return results.filter(r => r.status === 'fulfilled' && r.value === true).length;
  },
};
