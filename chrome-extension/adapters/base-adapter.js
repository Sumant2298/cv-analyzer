/**
 * LevelUpX AutoFill — Base Adapter
 *
 * Base class/factory for platform adapters.
 * Each adapter must implement: matchesHost(), isApplicationForm(), fill(), getResumeInput()
 */

window.LevelUpXBaseAdapter = {

  /**
   * Create an adapter object with sensible defaults.
   */
  create(config) {
    return {
      name: config.name || 'unknown',

      /**
       * Check if current hostname matches this platform.
       */
      matchesHost(host) {
        return (config.hostPatterns || []).some(p => host.includes(p));
      },

      /**
       * Check if current page is an application form.
       */
      isApplicationForm() {
        if (config.formDetector) return config.formDetector();
        // Default: look for common form indicators
        return !!document.querySelector('form') &&
               !!(document.querySelector('input[type="text"], input[type="email"], textarea'));
      },

      /**
       * Get the field mapping for this platform.
       * Returns {fieldName: [strategies]} where each strategy is {method, args}.
       */
      getFieldMap() {
        return config.fieldMap || {};
      },

      /**
       * Fill the form with profile data.
       * @returns {{filledCount: number}}
       */
      fill(container, profile) {
        const Detector = window.LevelUpXDetector;
        const Filler = window.LevelUpXFiller;
        if (!Detector || !Filler) return { filledCount: 0 };

        const fieldMap = this.getFieldMap(profile);
        let filledCount = 0;

        for (const [value, strategies] of Object.entries(fieldMap)) {
          if (!value) continue;
          const el = Detector.findField(container, strategies);
          if (el) {
            const success = Filler.fill(el, value);
            if (success) filledCount++;
          }
        }

        // Run any custom post-fill logic
        if (config.afterFill) {
          config.afterFill(container, profile, filledCount);
        }

        return { filledCount };
      },

      /**
       * Get the resume file input element.
       */
      getResumeInput(container) {
        const Detector = window.LevelUpXDetector;
        if (!Detector) return null;
        const selectors = config.resumeInputSelectors || ['input[type="file"]'];
        return Detector.fileInput(container, selectors);
      },
    };
  },
};
