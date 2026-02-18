/**
 * LevelUpX AutoFill — Step Orchestrator
 *
 * Universal agentic loop for multi-step job application forms.
 * Works on any ATS: opens the application, fills each step, clicks Next,
 * waits for transitions, and pauses before final Submit for user confirmation.
 *
 * Platform-specific adapters can provide stepConfig hints for optimized
 * selectors, but the orchestrator falls back to generic button-text matching.
 */

window.LevelUpXOrchestrator = {

  // ── State ──────────────────────────────────────────────────────
  _running: false,
  _aborted: false,
  _currentStep: 0,
  _log: [],

  // ── Configuration ──────────────────────────────────────────────
  MAX_STEPS: 15,
  STEP_TIMEOUT_MS: 12000,
  POST_FILL_DELAY_MS: 500,
  POST_CLICK_SETTLE_MS: 600,

  // ── Generic button text defaults ───────────────────────────────
  APPLY_TEXTS: [
    'Easy Apply', 'Apply Now', 'Apply', 'Apply for this job',
    'Start Application', "I'm Interested", 'Apply for this position',
    'Apply to this job', 'Quick Apply',
  ],
  NEXT_TEXTS: [
    'Next', 'Continue', 'Save and continue', 'Save & Continue',
    'Proceed', 'Next Step', 'Review', 'Save and next',
    'Continue to next step', 'Go to next step',
  ],
  SUBMIT_TEXTS: [
    'Submit application', 'Submit', 'Send Application',
    'Complete Application', 'Confirm & Submit', 'Confirm and Submit',
    'Submit my application', 'Apply',
  ],

  /**
   * Main entry point. Runs the full agentic application flow.
   * @param {Object} adapter - the platform adapter
   * @param {Object} profile - user profile data
   * @param {Function} onStatus - callback: (message, isError, stepInfo) => void
   * @returns {Promise<Object>} - { success, stepsCompleted, totalFilled, log }
   */
  async run(adapter, profile, onStatus) {
    if (this._running) {
      return { success: false, error: 'Already running' };
    }

    this._running = true;
    this._aborted = false;
    this._currentStep = 0;
    this._log = [];

    const ButtonFinder = window.LevelUpXButtonFinder;
    const Waiters = window.LevelUpXWaiters;
    const stepConfig = (adapter.getStepConfig && adapter.getStepConfig()) || {};
    let totalFilled = 0;

    try {
      // ── Phase 1: Open the application form ──────────────────────
      const openConfig = stepConfig.openApplication || {};
      const applyTexts = this._mergeTexts(openConfig.buttonText, this.APPLY_TEXTS);
      const applySelectors = openConfig.buttonSelectors || [];

      onStatus('Looking for Apply button...', false, { step: 0 });

      const applyClicked = ButtonFinder.findAndClick(document.body, applyTexts, applySelectors);

      if (applyClicked) {
        this._addLog('apply_clicked', 'Clicked Apply button');
        onStatus('Opening application form...', false, { step: 0 });

        // Wait for modal/form to appear
        if (openConfig.waitForSelector) {
          try {
            await Waiters.waitForElement(openConfig.waitForSelector, 8000);
          } catch {
            // Selector not found, but form might still be there
            await Waiters.waitForDomSettle(500, 4000);
          }
        } else {
          await Waiters.waitForDomSettle(500, 4000);
        }
      } else {
        // No Apply button found — assume we're already on the form
        this._addLog('no_apply_button', 'No Apply button found, assuming already on form');
        console.log('[LevelUpX] No Apply button found, proceeding with form fill');
      }

      // ── Phase 2: Step loop ──────────────────────────────────────
      while (this._currentStep < this.MAX_STEPS && !this._aborted) {
        this._currentStep++;
        onStatus(`Step ${this._currentStep}: Filling fields...`, false, {
          step: this._currentStep,
        });

        // 2a. Get form container
        const container = this._getFormContainer(stepConfig);

        // 2b. Fill visible fields using existing adapter.fill()
        const result = adapter.fill(container, profile);
        const stepFilled = result ? (result.filledCount || 0) : 0;
        totalFilled += stepFilled;

        // 2c. Try resume upload on this step
        let resumeUploaded = false;
        try {
          resumeUploaded = await this._tryResumeUpload(adapter, container);
          if (resumeUploaded) totalFilled++;
        } catch (e) {
          this._addLog('resume_skip', e.message);
        }

        const stepMsg = `Step ${this._currentStep}: Filled ${stepFilled} fields` +
                        (resumeUploaded ? ' + uploaded resume' : '');
        onStatus(stepMsg, false, { step: this._currentStep, filled: stepFilled });
        this._addLog('step_filled', stepMsg);

        // 2d. Delay for field validations
        await Waiters.delay(this.POST_FILL_DELAY_MS);

        if (this._aborted) break;

        // 2e. Classify next action
        const nextAction = this._classifyNextAction(stepConfig, container);

        if (nextAction === 'submit') {
          onStatus(
            `Ready to submit! Filled ${totalFilled} fields across ${this._currentStep} step(s). Review and click Submit.`,
            false,
            { step: this._currentStep, awaitingSubmit: true, totalFilled }
          );
          this._addLog('awaiting_submit', 'Paused before final submit');
          break;
        }

        if (nextAction === 'done') {
          this._addLog('no_next_button', 'No navigation button found — done or single-page form');
          onStatus(
            `Done! Filled ${totalFilled} fields across ${this._currentStep} step(s).`,
            false,
            { step: this._currentStep, totalFilled }
          );
          break;
        }

        // nextAction === 'next' — click the Next/Continue button
        const clicked = this._clickNextButton(stepConfig, container);
        if (!clicked) {
          this._addLog('click_failed', 'Could not click Next button');
          onStatus('Could not advance to next step.', true, { step: this._currentStep });
          break;
        }

        // 2f. Wait for step transition
        const transitioned = await this._waitForStepTransition(stepConfig);
        if (!transitioned) {
          const hasErrors = this._checkForValidationErrors(container);
          if (hasErrors) {
            onStatus('Form has validation errors. Please fix and click Full Apply again.', true, {
              step: this._currentStep,
              validationErrors: true,
            });
          } else {
            onStatus('Step transition timed out.', true, { step: this._currentStep });
          }
          break;
        }
      }

      return {
        success: !this._aborted,
        stepsCompleted: this._currentStep,
        totalFilled,
        log: this._log,
      };

    } catch (err) {
      this._addLog('error', err.message);
      onStatus(err.message, true, { step: this._currentStep });
      return {
        success: false,
        error: err.message,
        stepsCompleted: this._currentStep,
        totalFilled,
        log: this._log,
      };
    } finally {
      this._running = false;
    }
  },

  /**
   * Abort the current run.
   */
  abort() {
    this._aborted = true;
    console.log('[LevelUpX] Orchestrator aborted by user');
  },

  // ── Private helpers ────────────────────────────────────────────

  /**
   * Merge platform-specific texts with generic defaults (platform first).
   */
  _mergeTexts(platformTexts, genericTexts) {
    if (!platformTexts || !platformTexts.length) return genericTexts;
    // Platform texts first (higher priority), then generics for fallback
    const merged = [...platformTexts];
    for (const t of genericTexts) {
      if (!merged.some(m => m.toLowerCase() === t.toLowerCase())) {
        merged.push(t);
      }
    }
    return merged;
  },

  /**
   * Get the DOM container for the current form step.
   */
  _getFormContainer(stepConfig) {
    if (stepConfig.formContainerSelector) {
      const container = document.querySelector(stepConfig.formContainerSelector);
      if (container) return container;
    }
    return document.body;
  },

  /**
   * Classify the next action: 'submit', 'next', or 'done'.
   * Checks submit buttons FIRST to avoid accidentally clicking Submit as "next".
   */
  _classifyNextAction(stepConfig, container) {
    const ButtonFinder = window.LevelUpXButtonFinder;

    // Check for submit button first
    const submitTexts = this._mergeTexts(stepConfig.submitButtonText, this.SUBMIT_TEXTS);
    const submitSelectors = stepConfig.submitButtonSelectors || [];
    const submitBtn = ButtonFinder.findByText(container, submitTexts, submitSelectors);
    if (submitBtn && ButtonFinder.isClickable(submitBtn)) {
      // Make sure this is really a submit (not just "Apply" text on a Next button)
      const btnText = (submitBtn.textContent || '').trim().toLowerCase();
      const ariaLabel = (submitBtn.getAttribute('aria-label') || '').toLowerCase();
      if (btnText.includes('submit') || ariaLabel.includes('submit') ||
          btnText.includes('send application') || btnText.includes('complete application') ||
          btnText.includes('confirm')) {
        return 'submit';
      }
    }

    // Check for next/continue button
    const nextTexts = this._mergeTexts(stepConfig.nextButtonText, this.NEXT_TEXTS);
    const nextSelectors = stepConfig.nextButtonSelectors || [];
    const nextBtn = ButtonFinder.findByText(container, nextTexts, nextSelectors);
    if (nextBtn && ButtonFinder.isClickable(nextBtn)) {
      return 'next';
    }

    // Also check if the submit button is actually a submit (not caught above)
    if (submitBtn && ButtonFinder.isClickable(submitBtn)) {
      return 'submit';
    }

    return 'done';
  },

  /**
   * Click the Next/Continue button.
   */
  _clickNextButton(stepConfig, container) {
    const ButtonFinder = window.LevelUpXButtonFinder;
    const nextTexts = this._mergeTexts(stepConfig.nextButtonText, this.NEXT_TEXTS);
    const nextSelectors = stepConfig.nextButtonSelectors || [];
    return ButtonFinder.findAndClick(container, nextTexts, nextSelectors);
  },

  /**
   * Wait for form to transition after clicking Next.
   */
  async _waitForStepTransition(stepConfig) {
    const Waiters = window.LevelUpXWaiters;
    try {
      await Waiters.waitForDomSettle(this.POST_CLICK_SETTLE_MS, this.STEP_TIMEOUT_MS);
      return true;
    } catch {
      return false;
    }
  },

  /**
   * Check for visible validation error messages.
   */
  _checkForValidationErrors(container) {
    const errorSelectors = [
      '[class*="error"]:not([class*="hidden"])',
      '[class*="invalid"]',
      '[aria-invalid="true"]',
      '.artdeco-inline-feedback--error',     // LinkedIn
      '[data-automation-id*="error"]',        // Workday
      '.field-error', '.form-error',
      '[class*="validation-error"]',
    ];
    for (const sel of errorSelectors) {
      try {
        const el = container.querySelector(sel);
        if (el && el.offsetParent !== null && el.textContent.trim()) {
          return true;
        }
      } catch { /* invalid selector */ }
    }
    return false;
  },

  /**
   * Attempt resume upload on the current step.
   */
  async _tryResumeUpload(adapter, container) {
    const fileInput = adapter.getResumeInput(container);
    if (!fileInput) return false;

    // Check if a file is already attached
    if (fileInput.files && fileInput.files.length > 0) return false;

    const fileData = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ action: 'getResumeFile' }, (resp) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (resp && resp.error) {
          reject(new Error(resp.error));
          return;
        }
        resolve(resp);
      });
    });

    if (!fileData || !fileData.data) return false;

    const Filler = window.LevelUpXFiller;
    if (!Filler) return false;

    return await Filler.setFileInput(
      fileInput, fileData.data, fileData.filename, fileData.type
    );
  },

  _addLog(action, detail) {
    this._log.push({
      step: this._currentStep,
      action,
      detail,
      timestamp: Date.now(),
    });
    console.log(`[LevelUpX Orchestrator] Step ${this._currentStep}: ${action} — ${detail}`);
  },
};
