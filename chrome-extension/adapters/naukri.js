/**
 * LevelUpX AutoFill — Naukri Adapter
 *
 * Naukri has multiple apply paths: quick apply modal, chatbot, full apply.
 * Fields use standard names/classes.
 */

window.LevelUpXNaukri = window.LevelUpXBaseAdapter.create({
  name: 'Naukri',
  hostPatterns: ['naukri.com'],

  formDetector() {
    return !!(
      document.querySelector('.apply-modal, .chatbot-container, #apply-dialog') ||
      document.querySelector('[class*="applyForm"], [class*="apply-form"]') ||
      document.querySelector('input[name="name"], input[name="email"]') ||
      location.pathname.includes('/apply')
    );
  },

  fieldMap(profile) {
    const b = profile.basics || {};
    const fullName = b.fullName || `${b.firstName || ''} ${b.lastName || ''}`.trim();
    return {
      [fullName]: [
        { method: 'byName', args: ['name'] },
        { method: 'bySelector', args: ['input[name="name"]'] },
        { method: 'byLabelText', args: ['name'] },
        { method: 'byLabelText', args: ['full name'] },
        { method: 'byPlaceholder', args: ['name'] },
        { method: 'byPlaceholder', args: ['full name'] },
      ],
      [b.email]: [
        { method: 'byName', args: ['email'] },
        { method: 'bySelector', args: ['input[type="email"]'] },
        { method: 'bySelector', args: ['input[name="email"]'] },
        { method: 'byLabelText', args: ['email'] },
        { method: 'byPlaceholder', args: ['email'] },
      ],
      [b.phone]: [
        { method: 'byName', args: ['mobile'] },
        { method: 'byName', args: ['phone'] },
        { method: 'bySelector', args: ['input[type="tel"]'] },
        { method: 'bySelector', args: ['input[name="mobile"]'] },
        { method: 'byLabelText', args: ['mobile'] },
        { method: 'byLabelText', args: ['phone'] },
        { method: 'byPlaceholder', args: ['mobile'] },
      ],
      [(b.location || {}).city]: [
        { method: 'byName', args: ['currentLocation'] },
        { method: 'byName', args: ['location'] },
        { method: 'byLabelText', args: ['current location'] },
        { method: 'byLabelText', args: ['location'] },
        { method: 'byPlaceholder', args: ['location'] },
        { method: 'byPlaceholder', args: ['city'] },
      ],
      [b.title]: [
        { method: 'byName', args: ['designation'] },
        { method: 'byLabelText', args: ['designation'] },
        { method: 'byLabelText', args: ['current designation'] },
        { method: 'byPlaceholder', args: ['designation'] },
      ],
    };
  },

  resumeInputSelectors: [
    'input[type="file"][name*="resume"]',
    'input[type="file"][name*="cv"]',
    'input[type="file"][id*="resume"]',
    '.chatbot-container input[type="file"]',
    'input[type="file"]',
  ],
});
