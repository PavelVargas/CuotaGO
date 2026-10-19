/* Progressive enhancement: native forms work without JavaScript. */
(() => {
  'use strict';
  document.querySelectorAll('[data-go-back]').forEach(b => b.addEventListener('click', () => history.back()));
  document.querySelectorAll('.op form[method=post],.op form[method=POST]').forEach(f => {
    if (f.matches('[data-order-editor]')) return;
    f.addEventListener('submit', e => {
      if(e.defaultPrevented || (!f.noValidate && !f.checkValidity())) return;
      // Disabled buttons are not the financial boundary. The server persists
      // each request key and returns the same result for a repeated submission.
      f.querySelectorAll('button[type=submit],button:not([type])').forEach(b=>{b.disabled=true;});
    });
  });
  window.addEventListener('pageshow', () => document.querySelectorAll('.op button:disabled').forEach(b=>{b.disabled=false;}));
})();
