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
    const loc = b.location || {};
    const latestWork = (profile.work && profile.work[0]) || {};
    const latestEdu = (profile.education && profile.education[0]) || {};
    // LinkedIn pre-fills most fields, so we target what's typically left empty

    const map = {
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
      [loc.city]: [
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

    // ── Custom question fields (LinkedIn Easy Apply extra questions) ──
    if (latestWork.company) {
      map[latestWork.company] = [
        { method: 'byLabelText', args: ['current company'] },
        { method: 'byAriaLabel', args: ['current company'] },
        { method: 'byLabelText', args: ['company name'] },
      ];
    }
    if (latestWork.position || b.title) {
      map[latestWork.position || b.title] = [
        { method: 'byLabelText', args: ['current title'] },
        { method: 'byAriaLabel', args: ['current title'] },
        { method: 'byLabelText', args: ['job title'] },
      ];
    }
    if (latestEdu.institution) {
      map[latestEdu.institution] = [
        { method: 'byLabelText', args: ['school'] },
        { method: 'byLabelText', args: ['university'] },
        { method: 'byAriaLabel', args: ['school'] },
      ];
    }
    if (latestEdu.studyType) {
      map[latestEdu.studyType] = [
        { method: 'byLabelText', args: ['degree'] },
        { method: 'byAriaLabel', args: ['degree'] },
      ];
    }
    if (latestEdu.area) {
      map[latestEdu.area] = [
        { method: 'byLabelText', args: ['major'] },
        { method: 'byLabelText', args: ['field of study'] },
      ];
    }
    if (b.github) {
      map[b.github] = [
        { method: 'byLabelText', args: ['github'] },
        { method: 'byPlaceholder', args: ['github'] },
      ];
    }
    if (b.summary) {
      map[b.summary] = [
        { method: 'byLabelText', args: ['summary'] },
        { method: 'byLabelText', args: ['cover letter'] },
        { method: 'byLabelText', args: ['additional information'] },
      ];
    }

    return map;
  },

  resumeInputSelectors: [
    '.jobs-document-upload input[type="file"]',
    '[class*="document-upload"] input[type="file"]',
    '.artdeco-modal input[type="file"]',
    'input[type="file"]',
  ],

  // ── Agentic step configuration ─────────────────────────────────
  stepConfig: {
    openApplication: {
      buttonText: ['Easy Apply'],
      buttonSelectors: ['.jobs-apply-button', 'button[aria-label*="Easy Apply"]'],
      waitForSelector: '.jobs-easy-apply-modal, .artdeco-modal',
    },
    formContainerSelector: '.jobs-easy-apply-modal, .artdeco-modal',
    nextButtonText: ['Next', 'Continue', 'Review'],
    nextButtonSelectors: [
      'button[aria-label="Continue to next step"]',
      'button[aria-label="Review your application"]',
      'footer button.artdeco-button--primary',
    ],
    submitButtonText: ['Submit application'],
    submitButtonSelectors: ['button[aria-label="Submit application"]'],
  },
});
