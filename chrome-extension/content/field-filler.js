/**
 * LevelUpX AutoFill — Field Filler
 *
 * React/Angular-compatible value setting.
 * Dispatches proper events so frameworks pick up changes.
 */

window.LevelUpXFiller = {

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
   * Set a select element's value.
   * @param {HTMLSelectElement} el
   * @param {string} value - The option value or text to select
   * @returns {boolean}
   */
  setSelect(el, value) {
    if (!el || !value) return false;
    const valueLower = value.toLowerCase();

    // Try exact value match first
    for (const opt of el.options) {
      if (opt.value.toLowerCase() === valueLower || opt.textContent.toLowerCase().trim() === valueLower) {
        el.value = opt.value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
    }
    // Try partial text match
    for (const opt of el.options) {
      if (opt.textContent.toLowerCase().includes(valueLower)) {
        el.value = opt.value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
    }
    return false;
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
   * Fill a single field: auto-detect type and set value.
   * @param {HTMLElement} el
   * @param {*} value
   * @returns {boolean}
   */
  fill(el, value) {
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
      el.click();
      return true;
    }
    // Default: text/textarea
    return this.setText(el, String(value));
  },
};
