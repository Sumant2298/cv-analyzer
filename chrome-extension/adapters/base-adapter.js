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
      getFieldMap(profile) {
        if (typeof config.fieldMap === 'function') {
          return config.fieldMap(profile);
        }
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
        const filledElements = new Set();

        // ── Pass 1: Explicit fieldMap entries ────────────────────────
        for (const [value, strategies] of Object.entries(fieldMap)) {
          if (!value) continue;
          const el = Detector.findField(container, strategies);
          if (el) {
            const success = Filler.fill(el, value);
            if (success) {
              filledCount++;
              filledElements.add(el);
            }
          }
        }

        // ── Pass 2: Generic label-scanning for custom questions ──────
        // Scan all labels and match against known patterns from profile data
        filledCount += this._scanAndFillByLabels(container, profile, Filler, filledElements);

        // Run any custom post-fill logic
        if (config.afterFill) {
          config.afterFill(container, profile, filledCount);
        }

        return { filledCount };
      },

      /**
       * Scan form labels and auto-fill fields that match known patterns.
       * Only fills fields that haven't been filled already (not in filledElements set).
       * Returns count of additionally filled fields.
       */
      _scanAndFillByLabels(container, profile, Filler, filledElements) {
        const b = profile.basics || {};
        const loc = b.location || {};
        const latestWork = (profile.work && profile.work[0]) || {};
        const latestEdu = (profile.education && profile.education[0]) || {};
        let extraFilled = 0;

        // Map of label patterns → profile values
        // Each entry: [arrayOfPatterns, value]
        const labelPatterns = [
          [['preferred name', 'nickname', 'goes by'], b.firstName],
          [['full name'], b.fullName || `${b.firstName || ''} ${b.lastName || ''}`.trim()],
          [['first name', 'given name'], b.firstName],
          [['last name', 'family name', 'surname'], b.lastName],
          [['email'], b.email],
          [['phone', 'mobile', 'telephone', 'contact number'], b.phone],
          [['current company', 'current employer', 'company name', 'employer name', 'organization'], latestWork.company],
          [['current title', 'job title', 'current role', 'current position', 'designation'], latestWork.position || b.title],
          [['university', 'school', 'college', 'institution', 'alma mater'], latestEdu.institution],
          [['degree', 'highest degree', 'education level', 'qualification'], latestEdu.studyType],
          [['major', 'field of study', 'area of study', 'specialization', 'concentration'], latestEdu.area],
          [['gpa', 'grade', 'cgpa', 'score'], latestEdu.score],
          [['city'], loc.city],
          [['state', 'province', 'region'], loc.region],
          [['country'], loc.country],
          [['zip', 'postal', 'pincode', 'pin code'], loc.postalCode],
          [['linkedin'], b.linkedin],
          [['github'], b.github],
          [['portfolio', 'personal site', 'personal website'], b.website],
          [['website', 'url', 'web page'], b.website || b.github],
          [['summary', 'about yourself', 'cover letter', 'tell us about', 'introduce yourself', 'brief description'], b.summary],
        ];

        const labels = container.querySelectorAll('label');
        for (const label of labels) {
          const labelText = label.textContent.toLowerCase().trim();
          if (!labelText) continue;

          // Find the associated input/select/textarea for this label
          let el = null;
          const forId = label.getAttribute('for');
          if (forId) {
            try { el = container.querySelector(`#${CSS.escape(forId)}`); } catch {}
          }
          if (!el) el = label.querySelector('input, textarea, select');
          if (!el) {
            const next = label.nextElementSibling;
            if (next && (next.tagName === 'INPUT' || next.tagName === 'TEXTAREA' || next.tagName === 'SELECT')) {
              el = next;
            }
          }
          if (!el) {
            const parent = label.closest('.field, .form-group, .form-field, [class*="field"], [class*="input"], [class*="question"]');
            if (parent) el = parent.querySelector('input, textarea, select');
          }

          if (!el || filledElements.has(el)) continue;
          // Skip if already has a value
          if (el.tagName === 'SELECT') {
            if (el.selectedIndex > 0) continue; // already selected something beyond placeholder
          } else if (el.value && el.value.trim()) {
            continue; // already has text
          }

          // Try matching label text against known patterns
          for (const [patterns, value] of labelPatterns) {
            if (!value) continue;
            const matched = patterns.some(p => labelText.includes(p));
            if (matched) {
              const success = Filler.fill(el, value);
              if (success) {
                extraFilled++;
                filledElements.add(el);
                console.log(`[LevelUpX] Auto-filled custom field: "${labelText}" → "${String(value).slice(0, 30)}"`);
              }
              break; // don't try more patterns for this label
            }
          }
        }

        return extraFilled;
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

      /**
       * Get step configuration for multi-step agentic navigation.
       * Returns platform-specific button selectors/text, or null for generic defaults.
       * @returns {Object|null}
       */
      getStepConfig() {
        if (config.stepConfig) {
          return typeof config.stepConfig === 'function' ? config.stepConfig() : config.stepConfig;
        }
        return null;
      },
    };
  },
};
