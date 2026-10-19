(() => {
  'use strict';
  const f=document.querySelector('[data-portal-entry]');if(!f)return;
  const token=location.hash.slice(1);
  // Clear the fragment from history immediately, before any navigation.
  history.replaceState(null,'',location.pathname);
  if(/^[A-Za-z0-9_-]{43}$/.test(token)){
    f.elements.token.value=token;
    f.querySelector('button').disabled=false;
    document.querySelector('[data-portal-status]').textContent='Enlace recibido. Abre la consulta en este dispositivo privado.';
  }
})();
