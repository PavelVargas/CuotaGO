/* Progressive enhancement: native forms work without JavaScript. */
(() => {
  'use strict';
  document.querySelectorAll('[data-go-back]').forEach(b => b.addEventListener('click', () => history.back()));
  const form = document.querySelector('[data-order-wizard]');
  if (form) {
    let step = 0;
    const steps = [...form.querySelectorAll('[data-step]')];
    const labels = [...form.querySelectorAll('[data-step-label]')];
    const prev = form.querySelector('[data-prev]'), next = form.querySelector('[data-next]');
    const submit = form.querySelector('[data-order-submit]');
    const lines = form.querySelector('[data-order-lines]');
    const seed = lines.firstElementChild.cloneNode(true);
    function valid(node) {
      if (node === steps[1]) {
        for (const row of lines.children) {
          const name = row.querySelector('[name=line_name]');
          name.setCustomValidity(!row.querySelector('[name=line_asset_id]').value && !name.value.trim() ? 'Escribe el nombre del articulo nuevo.' : '');
        }
      }
      for (const input of node.querySelectorAll('input,select,textarea')) {
        if (!input.checkValidity()) { input.reportValidity(); return false; }
      }
      if (node === steps[1]) {
        for (const row of lines.children) {
          const name = row.querySelector('[name=line_name]');
          name.setCustomValidity(!row.querySelector('[name=line_asset_id]').value && !name.value.trim() ? 'Escribe el nombre del articulo nuevo.' : '');
          if (!name.checkValidity()) {name.reportValidity(); return false;}
        }
      }
      return true;
    }
    function review() {
      const out = form.querySelector('[data-order-review]'); out.replaceChildren();
      let total = 0;
      for (const row of lines.children) {
        const select = row.querySelector('select[name=line_asset_id]');
        const name = select.value ? select.selectedOptions[0].textContent : row.querySelector('[name=line_name]').value;
        const qty = Number(row.querySelector('[name=line_quantity]').value), cost = Number(row.querySelector('[name=line_unit_cost]').value);
        const p = document.createElement('p'); p.textContent = `${name}: ${qty} x ${cost.toFixed(2)} = ${(qty * cost).toFixed(2)}`; out.append(p); total += qty*cost;
      }
      const p = document.createElement('strong'); p.textContent = `Total estimado: ${total.toFixed(2)}`; out.append(p);
    }
    function show() {
      steps.forEach((n,i) => {n.hidden=i!==step;});
      labels.forEach((n,i) => {if(i===step) n.setAttribute('aria-current','step'); else n.removeAttribute('aria-current');});
      prev.hidden = step===0; next.hidden=step===2; submit.hidden=step!==2;
      if (step===2) review();
    }
    prev.addEventListener('click', () => {step=Math.max(0,step-1);show();});
    next.addEventListener('click', () => {if(valid(steps[step])) {step=Math.min(2,step+1);show();}});
    form.querySelector('[data-add-line]').addEventListener('click', () => {if(lines.children.length>=100)return;const node=seed.cloneNode(true);lines.append(node);});
    lines.addEventListener('input', e => {if(e.target.name==='line_name') e.target.setCustomValidity('');});
    lines.addEventListener('change', e => {if(e.target.name==='line_asset_id') e.target.closest('[data-order-line]').querySelector('[name=line_name]').setCustomValidity('');});
    lines.addEventListener('click', e => {if(e.target.closest('[data-remove-line]') && lines.children.length>1)e.target.closest('[data-order-line]').remove();});
    form.noValidate=true;
    form.addEventListener('submit', e => {for(let i=0;i<steps.length;i++){steps[i].hidden=false;if(!valid(steps[i])){e.preventDefault();step=i;show();return;}} show();});
    show();
  }
  document.querySelectorAll('.op form[method=post],.op form[method=POST]').forEach(f => {
    f.addEventListener('submit', e => {
      if(e.defaultPrevented || (!f.noValidate && !f.checkValidity())) return;
      // Disabled buttons are not the financial boundary. The server persists
      // each request key and returns the same result for a repeated submission.
      f.querySelectorAll('button[type=submit],button:not([type])').forEach(b=>{b.disabled=true;});
    });
  });
  window.addEventListener('pageshow', () => document.querySelectorAll('.op button:disabled').forEach(b=>{b.disabled=false;}));
})();
