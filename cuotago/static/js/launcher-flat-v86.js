/* Optional local artwork must never make a module unreachable, including light/dark variants. */
(() => {
  'use strict';
  const SELECTOR = '.cg-module-art-v86[data-module-art]';
  const syncFrame = (frame) => {
    const images = Array.from(frame.querySelectorAll('.cg-module-image-v86'));
    const hasLoaded = images.some((image) => image.complete && image.naturalWidth > 0);
    frame.classList.toggle('cg-art-fallback-v86', !hasLoaded);
  };
  const bind = () => {
    document.querySelectorAll(SELECTOR).forEach((frame) => {
      if (frame.dataset.artBound === '1') {
        syncFrame(frame);
        return;
      }
      frame.dataset.artBound = '1';
      frame.querySelectorAll('.cg-module-image-v86').forEach((image) => {
        image.addEventListener('load', () => syncFrame(frame));
        image.addEventListener('error', () => syncFrame(frame));
      });
      syncFrame(frame);
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind, { once: true });
  else bind();
  window.addEventListener('pageshow', bind);
})();
