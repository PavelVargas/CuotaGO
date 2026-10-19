(() => {
  'use strict';
  const button = document.querySelector('[data-print]');
  if (!button) return;
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    try {
      const images = [...document.images].map(image => image.complete ? Promise.resolve() :
        new Promise(resolve => { image.addEventListener('load', resolve, {once:true}); image.addEventListener('error', resolve, {once:true}); }));
      await Promise.race([Promise.all(images), new Promise(resolve => setTimeout(resolve, 5000))]);
      window.print();
    } finally { button.disabled = false; }
  });
})();
