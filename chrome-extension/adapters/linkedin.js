/**
 * LevelUpX AutoFill — LinkedIn Adapter
 *
 * LinkedIn Easy Apply pre-fills most fields from the user's profile.
 * Extension mainly handles resume upload + any custom questions.
 */

window.LevelUpXLinkedIn = window.LevelUpXBaseAdapter.create({
  name: 'LinkedIn',
  hostPatterns: ['linkedin.com'],

  formDetector() {
    return !!(
      document.querySelector('.jobs-easy-apply-modal, .jobs-apply-form') ||
      document.querySelector('[class*="easy-apply"], [class*="jobs-apply"]') ||
      document.querySelector('.artdeco-modal--layer-default [class*="jobs"]')
    );
  },

  fieldMap(profile) {
    const b = profile.basics || {};
    const fullName = b.fullName || `${b.firstName || ''} ${b.lastName || ''}`.trim();
    // LinkedIn pre-fills most fields, so we target what's typically left empty
    return {
      [b.firstName]: [
        { method: 'byLabelText', args: ['first name'] },
        { method: 'byPlaceholder', args: ['first name'] },
        { method: 'byAriaLabel', args: ['first name'] },
      ],
      [b.lastName]: [
        { method: 'byLabelText', args: ['last name'] },
        { method: 'byPlaceholder', args: ['last name'] },
        { method: 'byAriaLabel', args: ['last name'] },
      ],
      [b.email]: [
        { method: 'bySelector', args: ['input[type="email"]'] },
        { method: 'byLabelText', args: ['email'] },
        { method: 'byAriaLabel', args: ['email'] },
      ],
      [b.phone]: [
        { method: 'bySelector', args: ['input[type="tel"]'] },
        { method: 'byLabelText', args: ['phone'] },
        { method: 'byLabelText', args: ['mobile phone'] },
        { method: 'byAriaLabel', args: ['phone'] },
      ],
      [(b.location || {}).city]: [
        { method: 'byLabelText', args: ['city'] },
        { method: 'byLabelText', args: ['location'] },
        { method: 'byAriaLabel', args: ['city'] },
        { method: 'byPlaceholder', args: ['city'] },
      ],
      [b.linkedin]: [
        { method: 'byLabelText', args: ['linkedin'] },
        { method: 'byPlaceholder', args: ['linkedin'] },
      ],
      [b.website || b.github]: [
        { method: 'byLabelText', args: ['website'] },
        { method: 'byLabelText', args: ['portfolio'] },
        { method: 'byPlaceholder', args: ['website'] },
      ],
    };
  },

  resumeInputSelectors: [
    '.jobs-document-upload input[type="file"]',
    '[class*="document-upload"] input[type="file"]',
    '.artdeco-modal input[type="file"]',
    'input[type="file"]',
  ],
});
