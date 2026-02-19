/**
 * LevelUpX AutoFill — Base Adapter
 *
 * Base class/factory for platform adapters.
 * Each adapter must implement: matchesHost(), isApplicationForm(), fill(), getResumeInput()
 *
 * fill() is async to support React-Select custom dropdowns that require
 * click-wait-match sequences.
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
       * Fill the form with profile data (async for custom select support).
       * @returns {Promise<{filledCount: number}>}
       */
      async fill(container, profile) {
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
            const success = Filler.fill(el, value, container);
            if (success) {
              filledCount++;
              filledElements.add(el);
            }
          }
        }

        // ── Pass 2: Generic label-scanning for custom questions ──────
        // Scan all labels and match against known patterns from profile data
        filledCount += await this._scanAndFillByLabels(container, profile, Filler, filledElements);

        // ── Flush any pending async fills (custom selects) ───────────
        if (Filler.flushAsyncFills) {
          const asyncCount = await Filler.flushAsyncFills();
          filledCount += asyncCount;
        }

        // Run any custom post-fill logic
        if (config.afterFill) {
          config.afterFill(container, profile, filledCount);
        }

        return { filledCount };
      },

      /**
       * Scan form labels and auto-fill fields that match known patterns.
       * Handles standard inputs, native selects, radio groups, and React-Select.
       * Only fills fields that haven't been filled already.
       * @returns {Promise<number>} count of additionally filled fields
       */
      async _scanAndFillByLabels(container, profile, Filler, filledElements) {
        const Detector = window.LevelUpXDetector;
        const b = profile.basics || {};
        const loc = b.location || {};
        const latestWork = (profile.work && profile.work[0]) || {};
        const latestEdu = (profile.education && profile.education[0]) || {};
        const prefs = profile.applicationPrefs || {};
        let extraFilled = 0;

        // Map of label patterns → profile values
        // Each entry: [arrayOfPatterns, value]
        const labelPatterns = [
          [['preferred name', 'nickname', 'goes by'], b.firstName],
          [['full name', 'your name', 'candidate name'], b.fullName || `${b.firstName || ''} ${b.lastName || ''}`.trim()],
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

        // ── Application preferences patterns (India + US) ──────
        const customPatterns = [
          // India: CTC & salary
          [['current ctc', 'ctc', 'current salary', 'current annual salary', 'current compensation', 'present salary', 'current package', 'annual ctc'], prefs.currentCTC],
          [['expected ctc', 'expected salary', 'expected compensation', 'expected package', 'desired salary', 'desired ctc', 'salary expectation'], prefs.expectedCTC],
          // India: Notice period
          [['notice period', 'notice', 'serving notice', 'joining time', 'when can you join', 'earliest joining'], prefs.noticePeriod],
          // India: Total experience
          [['total experience', 'years of experience', 'work experience', 'total years', 'experience in years', 'professional experience'], prefs.totalExperienceYears],
          // India: DOB
          [['date of birth', 'dob', 'birth date', 'birthday'], prefs.dateOfBirth],
          // India: Preferred location
          [['preferred location', 'preferred city', 'preferred work location', 'desired location'], (prefs.preferredLocations || [])[0]],
          // Gender (fallback chain: India → US)
          [['gender', 'gender identity'], prefs.genderIN || prefs.genderUS],
          // US: Work auth & visa
          [['authorized to work', 'work authorization', 'legally authorized', 'eligible to work', 'right to work'], prefs.workAuthorization || 'Yes'],
          [['visa sponsorship', 'require sponsorship', 'need sponsorship', 'immigration sponsorship', 'sponsor', 'now or in the future require', 'will you now or in the future require'], prefs.visaSponsorship || 'No'],
          // US: Salary
          [['salary expectation', 'salary requirement', 'compensation expectation', 'annual salary', 'desired compensation', 'desired salary', 'salary range', 'pay expectation', 'what is your desired'], prefs.salaryExpectationUSD || prefs.expectedCTC],
          // US: EEO
          [['race', 'ethnicity', 'race/ethnicity', 'racial', 'ethnic background', 'hispanic', 'latino'], prefs.raceEthnicity],
          [['veteran', 'veteran status', 'military service', 'protected veteran'], prefs.veteranStatus || 'I am not a protected veteran'],
          [['disability', 'disability status', 'disabled', 'do you have a disability'], prefs.disabilityStatus],
          // Common: Referral — multiple phrasings
          [['how did you hear', 'referral source', 'referred by', 'how did you find', 'hear about this', 'hear about us', 'source of application', 'where did you hear', 'how did you learn'], prefs.referralSource],
          // Common: "comfortable moving forward" type questions
          [['comfortable moving forward', 'comfortable with the salary'], prefs.workAuthorization ? 'Yes' : ''],
          // Start date / availability
          [['start date', 'available start', 'earliest start', 'when can you start', 'date available', 'available to start', 'availability date', 'availability', 'start a new role', 'when could you start', 'when would you be able'], prefs.earliestStartDate || prefs.noticePeriod],
          // Previously employed
          [['previously employed', 'former employee', 'worked here before', 'have you worked', 'have you previously'], 'No'],
          // Age / 18+
          [['are you 18', 'over 18', 'at least 18', 'legal age', 'over the age of 18', 'are you at least'], 'Yes'],
          // Background check consent
          [['background check', 'consent to background', 'agree to background'], 'Yes'],
          // Relocation
          [['willing to relocate', 'open to relocation', 'relocate', 'relocation', 'open to relocate'], prefs.willingToRelocate || 'Yes'],
          // Travel
          [['willing to travel', 'travel requirement', 'comfortable with travel', 'travel percentage'], prefs.willingToTravel || ''],
          // Current location (Ashby and many modern ATS)
          [['where are you currently located', 'current location', 'where are you located', 'where do you live', 'where are you based', 'your location', 'city you live in'],
           loc.city ? `${loc.city}${loc.region ? ', ' + loc.region : ''}`.trim() : ''],
          // Office / onsite work questions
          [['able to work from', 'work from our', 'work onsite', 'work in person', 'come into the office', 'work in office', 'office three days', 'office.*days per week', 'able to work.*three days'],
           prefs.canWorkOnsite || 'Yes'],
          // Additional information / free-text
          [['additional information', 'anything else', 'additional context', 'additional details', 'share anything else', 'is there anything else', 'other information', 'motivation to apply'],
           prefs.additionalInfo || b.summary || ''],
          // NDA / Non-compete
          [['non-compete', 'nda', 'non-disclosure', 'restrictive covenant'], ''],
        ];
        const allPatterns = [...labelPatterns, ...customPatterns];

        // Shared helper: try to fill a field for a label-like element
        const tryFillForLabel = (labelEl, labelText) => {
          // ── Step 1: Find associated element ─────────────────────
          let el = Detector.findInputNearLabel(container, labelEl);
          let isRadioGroup = false;
          let isCustomSelect = false;

          // Check if result is a radio button
          if (el && el.tagName === 'INPUT' && (el.getAttribute('type') || '').toLowerCase() === 'radio') {
            isRadioGroup = true;
          }

          // If no standard input, try custom select
          if (!el && Detector.findCustomSelectNearLabel) {
            el = Detector.findCustomSelectNearLabel(container, labelEl);
            if (el) isCustomSelect = true;
          }

          // If still nothing, try dedicated radio finder
          if (!el && Detector.findRadioGroupNearLabel) {
            el = Detector.findRadioGroupNearLabel(container, labelEl);
            if (el) isRadioGroup = true;
          }

          // If still nothing, try checkbox group finder
          let isCheckboxGroup = false;
          if (!el && Detector.findCheckboxGroupNearLabel) {
            el = Detector.findCheckboxGroupNearLabel(container, labelEl);
            if (el) isCheckboxGroup = true;
          }

          if (!el || filledElements.has(el)) return false;

          // ── Step 2: Skip if already has a value ─────────────────
          if (isRadioGroup) {
            // Check if a radio in the group is already checked
            const name = el.getAttribute('name');
            if (name) {
              try {
                const checked = container.querySelector(`input[type="radio"][name="${CSS.escape(name)}"]:checked`);
                if (checked) return false;
              } catch { /* ignore */ }
            }
          } else if (isCustomSelect) {
            // Custom selects: check if there's already a selected value displayed
            // (heuristic: look for a value container with text)
            const valueContainer = el.closest('[class*="select"]');
            if (valueContainer) {
              const singleValue = valueContainer.querySelector('[class*="singleValue"], [class*="single-value"]');
              if (singleValue && singleValue.textContent.trim()) return false;
            }
          } else if (el.tagName === 'SELECT') {
            if (el.selectedIndex > 0) return false;
          } else if (el.value && el.value.trim()) {
            return false;
          }

          // ── Step 3: Match label text against patterns ───────────
          for (const [patterns, value] of allPatterns) {
            if (!value) continue;
            const matched = patterns.some(p => labelText.includes(p));
            if (matched) {
              let success = false;
              if (isCheckboxGroup) {
                // Checkbox group: pass value(s) to match checkbox labels
                success = Filler.setCheckboxGroup
                  ? Filler.setCheckboxGroup(container, el, String(value))
                  : false;
              } else if (isCustomSelect) {
                // Queue async React-Select fill
                Filler._pendingAsyncFills = Filler._pendingAsyncFills || [];
                Filler._pendingAsyncFills.push(
                  Filler.setReactSelect(el, String(value)).then(ok => {
                    if (!ok) return Filler.setText(el, String(value));
                    return ok;
                  })
                );
                success = true; // optimistic
              } else {
                success = Filler.fill(el, String(value), container);
              }
              if (success) {
                extraFilled++;
                filledElements.add(el);
                const tag = isRadioGroup ? 'radio' : isCustomSelect ? 'custom-select' : isCheckboxGroup ? 'checkbox-group' : 'input';
                console.log(`[LevelUpX] Auto-filled (${tag}): "${labelText}" → "${String(value).slice(0, 30)}"`);
              }
              return true; // pattern matched (even if fill failed)
            }
          }
          return false;
        };

        // ── Pass A: Scan <label> elements ────────────────────────────
        const labels = container.querySelectorAll('label');
        for (const label of labels) {
          const labelText = label.textContent.toLowerCase().trim();
          if (!labelText || labelText.length > 100) continue;
          tryFillForLabel(label, labelText);
        }

        // ── Pass A.1: Standalone "Name" label (exact match post-pass) ──
        // Must be separate to avoid false positives: "name" would match
        // "first name", "last name", "company name" via includes()
        const fullNameVal = b.fullName || `${b.firstName || ''} ${b.lastName || ''}`.trim();
        if (fullNameVal) {
          for (const label of labels) {
            const raw = label.textContent.toLowerCase().trim();
            const clean = raw.replace(/\s*\*\s*$/, '').trim();
            if (clean === 'name') {
              const el = Detector.findInputNearLabel(container, label);
              if (el && !filledElements.has(el) && !(el.value && el.value.trim())) {
                if (Filler.fill(el, fullNameVal, container)) {
                  extraFilled++;
                  filledElements.add(el);
                  console.log(`[LevelUpX] Auto-filled (name-exact): "name" → "${fullNameVal}"`);
                }
              }
            }
          }
        }

        // ── Pass B: Scan pseudo-label elements ───────────────────────
        // Modern React forms often use <div>, <span>, <legend> as labels
        const pseudoLabels = container.querySelectorAll(
          'legend, [class*="label"], [class*="Label"], [class*="LABEL"], [data-testid*="label"]'
        );
        for (const pseudoLabel of pseudoLabels) {
          if (pseudoLabel.tagName === 'LABEL') continue; // already handled
          const text = pseudoLabel.textContent.toLowerCase().trim();
          if (!text || text.length > 80) continue;
          tryFillForLabel(pseudoLabel, text);
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

          for (const [patterns, value] of allPatterns) {
            if (!value) continue;
            if (patterns.some(p => matchText.includes(p))) {
              if (Filler.fill(el, value, container)) {
                extraFilled++;
                filledElements.add(el);
                console.log(`[LevelUpX] Auto-filled (attr match): "${matchText.trim()}" → "${String(value).slice(0, 30)}"`);
              }
              break;
            }
          }
        }

        // ── Debug: log unfilled labels ───────────────────────────────
        try {
          const unfilled = [];
          for (const label of labels) {
            const text = label.textContent.toLowerCase().trim();
            if (!text || text.length > 100) continue;
            const el = Detector.findInputNearLabel(container, label);
            if (el && !filledElements.has(el)) {
              const hasValue = (el.tagName === 'SELECT' && el.selectedIndex > 0) ||
                               (el.value && el.value.trim());
              if (!hasValue) {
                unfilled.push(text.slice(0, 60));
              }
            }
          }
          if (unfilled.length > 0) {
            console.log('[LevelUpX] Unfilled labels (no pattern match):', unfilled);
          }
        } catch { /* debug only */ }

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
