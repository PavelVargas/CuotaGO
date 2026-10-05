/* Connected dealer records. No navigation interception, no financial retries. */
(() => {
  'use strict';
  const menus = [...document.querySelectorAll('.dlr-more')];
  document.addEventListener('click', event => {
    menus.forEach(menu => {
      if (!menu.contains(event.target) || event.target.closest('.dlr-more-menu a,.dlr-more-menu button')) menu.open = false;
    });
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') menus.forEach(menu => { if (menu.open) { menu.open = false; menu.querySelector('summary').focus(); } });
  });
  const dialog = document.getElementById('assetInvestmentDialog');
  if (!dialog) return;
  let opener = null;
  document.querySelectorAll('[data-investment-open]').forEach(button => {
    button.addEventListener('click', () => {
      opener = button;
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    });
  });
  const close = () => {
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
    opener?.focus({preventScroll:true});
  };
  dialog.querySelectorAll('[data-investment-close]').forEach(button => button.addEventListener('click',close));
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  dialog.addEventListener('close', () => opener?.focus({preventScroll:true}));
})();
