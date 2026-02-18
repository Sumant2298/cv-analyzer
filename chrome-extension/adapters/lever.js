/**
 * LevelUpX AutoFill — Lever Adapter
 *
 * Lever uses standard HTML forms with straightforward field names.
 */

window.LevelUpXLever = window.LevelUpXBaseAdapter.create({
  name: 'Lever',
  hostPatterns: ['jobs.lever.co'],

  formDetector() {
    return !!document.querySelector('.application-form, form[action*="apply"], .postings-btn-wrapper');
  },

  fieldMap(profile) {
    const b = profile.basics || {};
    const fullName = b.fullName || `${b.firstName || ''} ${b.lastName || ''}`.trim();
    return {
      [fullName]: [
        { method: 'byName', args: ['name'] },
        { method: 'byLabelText', args: ['full name'] },
        { method: 'byLabelText', args: ['name'] },
        { method: 'byPlaceholder', args: ['full name'] },
      ],
      [b.email]: [
        { method: 'byName', args: ['email'] },
        { method: 'bySelector', args: ['input[type="email"]'] },
        { method: 'byLabelText', args: ['email'] },
      ],
      [b.phone]: [
        { method: 'byName', args: ['phone'] },
        { method: 'bySelector', args: ['input[type="tel"]'] },
        { method: 'byLabelText', args: ['phone'] },
      ],
      [b.linkedin]: [
        { method: 'bySelector', args: ['input[name*="urls[LinkedIn]"]'] },
        { method: 'bySelector', args: ['input[name*="linkedin"]'] },
        { method: 'byLabelText', args: ['linkedin'] },
      ],
      [b.github]: [
        { method: 'bySelector', args: ['input[name*="urls[GitHub]"]'] },
        { method: 'bySelector', args: ['input[name*="github"]'] },
        { method: 'byLabelText', args: ['github'] },
      ],
      [b.website]: [
        { method: 'bySelector', args: ['input[name*="urls[Portfolio]"]'] },
        { method: 'bySelector', args: ['input[name*="website"]'] },
        { method: 'byLabelText', args: ['website'] },
        { method: 'byLabelText', args: ['portfolio'] },
      ],
      [(b.location || {}).city]: [
        { method: 'byLabelText', args: ['location'] },
        { method: 'byPlaceholder', args: ['location'] },
        { method: 'byPlaceholder', args: ['city'] },
      ],
    };
  },

  resumeInputSelectors: [
    'input[type="file"][name*="resume"]',
    'input[type="file"][name*="cv"]',
    '.application-form input[type="file"]',
    'input[type="file"]',
  ],
});
