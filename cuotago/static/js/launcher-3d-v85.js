/* Optional local artwork must never make a module unreachable. */
(() => {
  'use strict';
  const SELECTOR = '.cg-module-image-v85';
  const bind = () => {
    document.querySelectorAll(SELECTOR).forEach((image) => {
      if (image.dataset.artBound === '1') return;
      image.dataset.artBound = '1';
      const frame = image.closest('[data-module-art]');
      if (!frame) return;
      const sync = () => {
        frame.classList.toggle('cg-art-fallback-v85', image.complete && image.naturalWidth === 0);
      };
      image.addEventListener('load', sync);
      image.addEventListener('error', () => frame.classList.add('cg-art-fallback-v85'));
      sync(); // Cached images may have completed before this deferred script.
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind, { once: true });
  else bind();
  window.addEventListener('pageshow', bind);
})();
