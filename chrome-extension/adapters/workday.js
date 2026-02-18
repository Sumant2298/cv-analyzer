/**
 * LevelUpX AutoFill — Workday Adapter
 *
 * Workday uses React SPA with data-automation-id attributes.
 * Forms are multi-step — we fill only the visible step.
 */

window.LevelUpXWorkday = window.LevelUpXBaseAdapter.create({
  name: 'Workday',
  hostPatterns: ['myworkdayjobs.com', 'myworkday.com', 'workday.com'],

  formDetector() {
    // Workday application pages have specific automation IDs
    return !!(
      document.querySelector('[data-automation-id="jobPostingPage"]') ||
      document.querySelector('[data-automation-id="applyButton"]') ||
      document.querySelector('[data-automation-id="legalNameSection_firstName"]') ||
      document.querySelector('[data-automation-id="resumeSection"]') ||
      location.pathname.includes('/apply')
    );
  },

  fieldMap(profile) {
    const b = profile.basics || {};
    const loc = b.location || {};
    const latestWork = (profile.work && profile.work[0]) || {};
    const latestEdu = (profile.education && profile.education[0]) || {};

    const map = {
      [b.firstName]: [
        { method: 'byDataAutomation', args: ['legalNameSection_firstName'] },
        { method: 'bySelector', args: ['[data-automation-id="legalNameSection_firstName"] input'] },
        { method: 'byLabelText', args: ['first name'] },
        { method: 'byPlaceholder', args: ['first name'] },
      ],
      [b.lastName]: [
        { method: 'byDataAutomation', args: ['legalNameSection_lastName'] },
        { method: 'bySelector', args: ['[data-automation-id="legalNameSection_lastName"] input'] },
        { method: 'byLabelText', args: ['last name'] },
        { method: 'byPlaceholder', args: ['last name'] },
      ],
      [b.email]: [
        { method: 'byDataAutomation', args: ['email'] },
        { method: 'bySelector', args: ['[data-automation-id="email"] input'] },
        { method: 'bySelector', args: ['input[type="email"]'] },
        { method: 'byLabelText', args: ['email'] },
      ],
      [b.phone]: [
        { method: 'byDataAutomation', args: ['phone-number'] },
        { method: 'bySelector', args: ['[data-automation-id="phone-number"] input'] },
        { method: 'bySelector', args: ['input[type="tel"]'] },
        { method: 'byLabelText', args: ['phone'] },
      ],
      [loc.city]: [
        { method: 'byDataAutomation', args: ['addressSection_city'] },
        { method: 'bySelector', args: ['[data-automation-id="addressSection_city"] input'] },
        { method: 'byLabelText', args: ['city'] },
      ],
      [loc.region]: [
        { method: 'byDataAutomation', args: ['addressSection_region'] },
        { method: 'bySelector', args: ['[data-automation-id="addressSection_region"] input'] },
        { method: 'byLabelText', args: ['state'] },
        { method: 'byLabelText', args: ['region'] },
      ],
      [loc.country]: [
        { method: 'byDataAutomation', args: ['addressSection_country'] },
        { method: 'bySelector', args: ['[data-automation-id="addressSection_country"] input'] },
        { method: 'byLabelText', args: ['country'] },
      ],
      [b.linkedin]: [
        { method: 'byDataAutomation', args: ['linkedinQuestion'] },
        { method: 'byLabelText', args: ['linkedin'] },
        { method: 'byPlaceholder', args: ['linkedin'] },
      ],
    };

    // ── Current work ─────────────────────────────────────────────
    if (latestWork.company) {
      map[latestWork.company] = [
        { method: 'byDataAutomation', args: ['currentCompany'] },
        { method: 'byLabelText', args: ['current company'] },
        { method: 'byLabelText', args: ['company name'] },
        { method: 'byLabelText', args: ['current employer'] },
      ];
    }
    if (latestWork.position || b.title) {
      map[latestWork.position || b.title] = [
        { method: 'byDataAutomation', args: ['currentTitle'] },
        { method: 'byLabelText', args: ['current title'] },
        { method: 'byLabelText', args: ['job title'] },
        { method: 'byLabelText', args: ['current position'] },
      ];
    }

    // ── Education ────────────────────────────────────────────────
    if (latestEdu.institution) {
      map[latestEdu.institution] = [
        { method: 'byDataAutomation', args: ['schoolName'] },
        { method: 'byLabelText', args: ['school'] },
        { method: 'byLabelText', args: ['university'] },
        { method: 'byLabelText', args: ['college'] },
      ];
    }
    if (latestEdu.studyType) {
      map[latestEdu.studyType] = [
        { method: 'byDataAutomation', args: ['degree'] },
        { method: 'byLabelText', args: ['degree'] },
        { method: 'byLabelText', args: ['education level'] },
      ];
    }
    if (latestEdu.area) {
      map[latestEdu.area] = [
        { method: 'byLabelText', args: ['major'] },
        { method: 'byLabelText', args: ['field of study'] },
      ];
    }

    // ── GitHub / Website ─────────────────────────────────────────
    if (b.github) {
      map[b.github] = [
        { method: 'byLabelText', args: ['github'] },
        { method: 'byPlaceholder', args: ['github'] },
      ];
    }
    if (b.website) {
      map[b.website] = [
        { method: 'byLabelText', args: ['website'] },
        { method: 'byLabelText', args: ['portfolio'] },
      ];
    }

    return map;
  },

  afterFill(container, profile, filledCount) {
    // Workday sometimes has input wrappers that need click to activate
    const inputs = container.querySelectorAll('[data-automation-id] input');
    inputs.forEach(input => {
      if (input.value) {
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
  },

  resumeInputSelectors: [
    '[data-automation-id="file-upload-input-ref"]',
    'input[data-automation-id*="resume"]',
    'input[data-automation-id*="file-upload"]',
    'input[type="file"]',
  ],

  // ── Agentic step configuration ─────────────────────────────────
  stepConfig: {
    openApplication: {
      buttonText: ['Apply', 'Apply Now'],
      buttonSelectors: ['[data-automation-id="applyButton"]'],
      waitForSelector: '[data-automation-id="legalNameSection_firstName"]',
    },
    formContainerSelector: '[data-automation-id="applicationPage"], main',
    nextButtonText: ['Next', 'Continue', 'Save and Continue'],
    nextButtonSelectors: ['[data-automation-id="bottom-navigation-next-button"]'],
    submitButtonText: ['Submit', 'Submit Application'],
    submitButtonSelectors: ['[data-automation-id="bottom-navigation-submit-button"]'],
  },
});
