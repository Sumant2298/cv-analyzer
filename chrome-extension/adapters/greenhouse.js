/**
 * LevelUpX AutoFill — Greenhouse Adapter
 *
 * Greenhouse uses standard HTML forms with name attributes like:
 * job_application[first_name], job_application[last_name], etc.
 */

window.LevelUpXGreenhouse = window.LevelUpXBaseAdapter.create({
  name: 'Greenhouse',
  hostPatterns: ['greenhouse.io'],

  formDetector() {
    return !!(
      document.querySelector('#application_form, form#job_application, [id*="application"]') ||
      document.querySelector('form[action*="application"], form[action*="apply"]') ||
      document.querySelector('input[name*="first_name"], input[name*="job_application"]') ||
      document.querySelector('[class*="application"], [data-controller*="application"]')
    );
  },

  fieldMap(profile) {
    const b = profile.basics || {};
    return {
      [b.firstName]: [
        { method: 'byName', args: ['first_name'] },
        { method: 'bySelector', args: ['input[name="job_application[first_name]"]'] },
        { method: 'byLabelText', args: ['first name'] },
        { method: 'byPlaceholder', args: ['first name'] },
      ],
      [b.lastName]: [
        { method: 'byName', args: ['last_name'] },
        { method: 'bySelector', args: ['input[name="job_application[last_name]"]'] },
        { method: 'byLabelText', args: ['last name'] },
        { method: 'byPlaceholder', args: ['last name'] },
      ],
      [b.email]: [
        { method: 'byName', args: ['email'] },
        { method: 'bySelector', args: ['input[name="job_application[email]"]'] },
        { method: 'bySelector', args: ['input[type="email"]'] },
        { method: 'byLabelText', args: ['email'] },
      ],
      [b.phone]: [
        { method: 'byName', args: ['phone'] },
        { method: 'bySelector', args: ['input[name="job_application[phone]"]'] },
        { method: 'bySelector', args: ['input[type="tel"]'] },
        { method: 'byLabelText', args: ['phone'] },
      ],
      [b.linkedin]: [
        { method: 'bySelector', args: ['input[name*="linkedin"]'] },
        { method: 'byLabelText', args: ['linkedin'] },
        { method: 'byPlaceholder', args: ['linkedin'] },
      ],
      [b.website || b.github]: [
        { method: 'bySelector', args: ['input[name*="website"]'] },
        { method: 'byLabelText', args: ['website'] },
        { method: 'byPlaceholder', args: ['website'] },
      ],
      [(b.location || {}).city]: [
        { method: 'bySelector', args: ['input[name*="location"]'] },
        { method: 'byLabelText', args: ['location'] },
        { method: 'byPlaceholder', args: ['location'] },
        { method: 'byPlaceholder', args: ['city'] },
      ],
    };
  },

  resumeInputSelectors: [
    'input[type="file"][name*="resume"]',
    'input[type="file"][name*="cv"]',
    'input[type="file"][id*="resume"]',
    'input[type="file"]',
  ],
});
