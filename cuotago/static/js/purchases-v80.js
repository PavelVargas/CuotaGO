/* Three steps, same server POST. Keep repeated hidden row fields enabled so
   request.form.getlist retains positional alignment for new/existing items. */
(() => {
  'use strict';
  const form = document.getElementById('purchaseForm');
  if (!form || !form.classList.contains('cg-purchase-form')) return;
  const panels = [...form.querySelectorAll('[data-purchase-step]')];
  const tabs = [...form.querySelectorAll('[data-purchase-go]')];
  const items = document.getElementById('purchaseItems');
  const supplier = document.getElementById('purchaseSupplier');
  const supplierFields = document.getElementById('newSupplierFields');
  const next = form.querySelector('[data-purchase-next]');
  const back = form.querySelector('[data-purchase-back]');
  const submit = document.getElementById('purchaseSubmit');
  const error = form.querySelector('[data-purchase-error]');
  const money = new Intl.NumberFormat('es-DO', {style:'currency',currency:'DOP',minimumFractionDigits:2,maximumFractionDigits:2});
  let step = 1, saving = false;
  const rows = () => [...items.querySelectorAll('[data-purchase-item]')];
  const number = value => { const n = Number(value); return Number.isFinite(n) ? Math.max(0,n) : 0; };
  const value = name => form.elements.namedItem(name)?.value || '';
  const totalOf = row => Math.round(number(row.querySelector('[data-purchase-cost]').value) * 100) * number(row.querySelector('[data-purchase-qty]').value) / 100;
  const sum = () => rows().reduce((total,row) => total + totalOf(row), 0);
  const openAncestors = node => {
    let parent = node.parentElement;
    while (parent && parent !== form) { if (parent.tagName === 'DETAILS') parent.open = true; parent = parent.parentElement; }
  };
  const syncSupplier = () => {
    const isNew = supplier.value === '__new__';
    supplierFields.hidden = !isNew;
    supplierFields.querySelector('[data-new-supplier-name]').required = isNew;
  };
  const syncRow = (row, fillCost = false) => {
    const select = row.querySelector('[data-purchase-asset]');
    const isNew = select.value === '__new__';
    row.querySelector('[data-item-mode]').value = isNew ? 'new' : 'existing';
    row.querySelector('[data-new-item-fields]').hidden = !isNew;
    row.querySelector('[data-new-item-name]').required = isNew;
    const cost = row.querySelector('[data-purchase-cost]');
    if (fillCost && !isNew && select.value && !cost.value) {
      const suggested = number(select.selectedOptions[0]?.dataset.cost);
      if (suggested > 0) cost.value = suggested.toFixed(2);
    }
    row.querySelector('[data-line-cost]').textContent = money.format(totalOf(row));
  };
  const update = () => {
    const all = rows(); all.forEach(row => syncRow(row));
    document.getElementById('purchaseTotalCost').textContent = money.format(sum());
    const units = all.reduce((n,row)=>n+number(row.querySelector('[data-purchase-qty]').value),0);
    document.getElementById('purchaseItemCount').textContent = `${all.length} art\u00edculos \u00b7 ${units} unidades`;
    all.forEach(row => { row.querySelector('[data-remove-purchase-item]').disabled = all.length === 1; });
  };
  const review = () => {
    form.querySelector('[data-review-supplier]').textContent = supplier.value === '__new__' ? value('new_supplier_name') : (supplier.selectedOptions[0]?.textContent || '');
    const iso = value('purchase_date');
    form.querySelector('[data-review-date]').textContent = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split('-').reverse().join('/') : iso;
    form.querySelector('[data-review-reference]').textContent = value('reference') || 'Sin referencia';
    form.querySelector('[data-review-total]').textContent = money.format(sum());
    const host = form.querySelector('[data-review-lines]'); host.replaceChildren();
    rows().forEach(row => {
      const select = row.querySelector('[data-purchase-asset]');
      const entry = document.createElement('div');
      const copy = document.createElement('span'); const title = document.createElement('strong');
      const meta = document.createElement('small'); const amount = document.createElement('b');
      title.textContent = select.value === '__new__' ? row.querySelector('[data-new-item-name]').value : select.selectedOptions[0]?.textContent;
      meta.textContent = `${row.querySelector('[data-purchase-qty]').value} \u00d7 ${money.format(number(row.querySelector('[data-purchase-cost]').value))}`;
      amount.textContent = money.format(totalOf(row)); copy.append(title,meta); entry.append(copy,amount); host.append(entry);
    });
  };
  const show = (target, focus = true) => {
    step = target; form.dataset.purchaseCurrent = String(step);
    panels.forEach(panel => { panel.hidden = Number(panel.dataset.purchaseStep) !== step; });
    tabs.forEach(tab => {
      const active = Number(tab.dataset.purchaseGo) === step;
      tab.classList.toggle('is-active',active);
      if (active) tab.setAttribute('aria-current','step'); else tab.removeAttribute('aria-current');
    });
    next.hidden = step === 3; back.hidden = step === 1; submit.hidden = step !== 3;
    next.textContent = step === 2 ? 'Revisar compra' : 'Continuar'; error.hidden = true;
    if (step === 3) review();
    if (focus) panels[step-1].querySelector('h2')?.focus({preventScroll:false});
  };
  const validate = target => {
    syncSupplier(); update();
    const fields = [...panels[target-1].querySelectorAll('input,select,textarea')];
    fields.filter(field => field.required && field.type === 'text').forEach(field => { field.value = field.value.trim(); });
    const invalid = fields.find(field => field.willValidate && !field.checkValidity());
    if (invalid) {
      show(target,false); openAncestors(invalid); invalid.focus(); invalid.reportValidity();
      error.textContent = 'Revisa el campo marcado para continuar.'; error.hidden = false;
      return false;
    }
    return true;
  };
  const go = target => {
    if (saving || target < 1 || target > 3) return;
    if (target > step) for (let n = 1; n < target; n++) { if (!validate(n)) return; }
    show(target);
  };
  form.noValidate = true;
  supplier.addEventListener('change',syncSupplier);
  items.addEventListener('input', () => { error.hidden = true; update(); });
  items.addEventListener('change', event => { const row = event.target.closest('[data-purchase-item]'); if (row) syncRow(row,event.target.matches('[data-purchase-asset]')); update(); });
  items.addEventListener('click', event => {
    const remove = event.target.closest('[data-remove-purchase-item]');
    if (remove && rows().length > 1) { remove.closest('[data-purchase-item]').remove(); update(); }
  });
  form.querySelector('[data-add-purchase-item]').addEventListener('click', () => {
    const row = rows()[0].cloneNode(true);
    row.querySelectorAll('input').forEach(input => { input.value = input.name === 'item_quantity' ? '1' : ''; });
    row.querySelectorAll('select').forEach(select => { select.selectedIndex = 0; });
    row.querySelector('[data-purchase-asset]').value = form.dataset.hasAssets === '1' ? '' : '__new__';
    row.querySelector('[name="item_kind"]').value = 'other';
    row.querySelectorAll('details').forEach(detail => { detail.open = false; });
    items.append(row); update(); row.querySelector('[data-purchase-asset]').focus();
  });
  next.addEventListener('click',()=>go(step+1)); back.addEventListener('click',()=>go(step-1));
  tabs.forEach(tab=>tab.addEventListener('click',()=>go(Number(tab.dataset.purchaseGo))));
  form.addEventListener('submit', event => {
    if (saving) { event.preventDefault(); return; }
    if (step < 3) { event.preventDefault(); go(step+1); return; }
    if (!validate(1) || !validate(2)) { event.preventDefault(); return; }
    saving = true; submit.disabled = true; submit.querySelector('span').textContent = 'Guardando...';
  });
  window.addEventListener('pageshow',()=>{ saving = false; submit.disabled = false; submit.querySelector('span').textContent = 'Guardar compra'; });
  syncSupplier(); update(); show(1,false);
})();
