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
        const Detector = window.LevelUpXDetector;
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
          [['first name', 'given name', 'fname'], b.firstName],
          [['last name', 'family name', 'surname', 'lname'], b.lastName],
          [['email', 'e-mail'], b.email],
          [['phone', 'mobile', 'telephone', 'contact number', 'cell'], b.phone],
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
          [['address', 'street address', 'street'], loc.address],
          [['linkedin'], b.linkedin],
          [['github'], b.github],
          [['portfolio', 'personal site', 'personal website'], b.website],
          [['website', 'url', 'web page'], b.website || b.github],
          [['summary', 'about yourself', 'cover letter', 'tell us about', 'introduce yourself', 'brief description'], b.summary],
        ];

        // ── Pass A: Scan <label> elements ────────────────────────────
        const labels = container.querySelectorAll('label');
        for (const label of labels) {
          const labelText = label.textContent.toLowerCase().trim();
          if (!labelText || labelText.length > 100) continue;

          // Use robust 8-strategy label-to-input resolver
          let el = Detector ? Detector.findInputNearLabel(container, label) : null;

          if (!el || filledElements.has(el)) continue;
          // Skip if already has a value
          if (el.tagName === 'SELECT') {
            if (el.selectedIndex > 0) continue;
          } else if (el.value && el.value.trim()) {
            continue;
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
                console.log(`[LevelUpX] Auto-filled: "${labelText}" → "${String(value).slice(0, 30)}"`);
              }
              break;
            }
          }
        }

        // ── Pass B: Scan pseudo-label elements ───────────────────────
        // Modern React forms often use <div>, <span>, <legend> as labels
        // instead of <label>. Scan these too.
        const pseudoLabels = container.querySelectorAll(
          'legend, [class*="label"], [class*="Label"], [class*="LABEL"], [data-testid*="label"]'
        );
        for (const pseudoLabel of pseudoLabels) {
          if (pseudoLabel.tagName === 'LABEL') continue; // already handled
          const text = pseudoLabel.textContent.toLowerCase().trim();
          if (!text || text.length > 80) continue;

          let el = Detector ? Detector.findInputNearLabel(container, pseudoLabel) : null;
          if (!el || filledElements.has(el)) continue;

          if (el.tagName === 'SELECT') {
            if (el.selectedIndex > 0) continue;
          } else if (el.value && el.value.trim()) {
            continue;
          }

          for (const [patterns, value] of labelPatterns) {
            if (!value) continue;
            if (patterns.some(p => text.includes(p))) {
              if (Filler.fill(el, value)) {
                extraFilled++;
                filledElements.add(el);
                console.log(`[LevelUpX] Auto-filled (pseudo-label): "${text}" → "${String(value).slice(0, 30)}"`);
              }
              break;
            }
          }
        }

        // ── Pass C: Fallback — scan inputs by placeholder/name ───────
        // For inputs that have no label at all (some minimal ATS forms)
        const allInputs = container.querySelectorAll('input:not([type="hidden"]):not([type="file"]), textarea, select');
        for (const el of allInputs) {
          if (filledElements.has(el)) continue;
          if (el.tagName === 'SELECT') {
            if (el.selectedIndex > 0) continue;
          } else if (el.value && el.value.trim()) {
            continue;
          }

          // Try matching by placeholder text or name attribute
          const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
          const name = (el.getAttribute('name') || '').toLowerCase();
          const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
          const matchText = `${placeholder} ${name} ${ariaLabel}`;

          if (!matchText.trim()) continue;

          for (const [patterns, value] of labelPatterns) {
            if (!value) continue;
            if (patterns.some(p => matchText.includes(p))) {
              if (Filler.fill(el, value)) {
                extraFilled++;
                filledElements.add(el);
                console.log(`[LevelUpX] Auto-filled (attr match): "${matchText.trim()}" → "${String(value).slice(0, 30)}"`);
              }
              break;
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
