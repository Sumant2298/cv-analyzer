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
    return {
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
});
