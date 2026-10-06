/* Sales v66. Real inventory only; no fixture data or external image dependencies. */
(() => {
  'use strict';
  const root = document.querySelector('.sls-workspace');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const currency = new Intl.NumberFormat('es-DO', { style: 'currency', currency: 'DOP', maximumFractionDigits: 2 });
  const money = (cents) => currency.format(cents / 100);
  const cents = (value) => Number.isFinite(Number(value)) ? Math.round((Number(value) + Number.EPSILON) * 100) : 0;
  const setText = (id, text) => { const element = $(id); if (element) element.textContent = text; };

  // CSS display rules must never reveal empty/hidden pictures. No empty src requests.
  const failImage = (image) => {
    const media = image.closest('.sls-media');
    if (!media) return;
    image.hidden = true;
    const fallback = media.querySelector('[data-photo-placeholder]');
    if (fallback) {
      fallback.hidden = false;
      const label = fallback.querySelector('span');
      if (label) label.textContent = 'Foto no disponible';
    }
  };
  root.addEventListener('error', (event) => {
    if (event.target.matches?.('[data-asset-image]')) failImage(event.target);
  }, true);
  root.querySelectorAll('[data-asset-image]').forEach((img) => {
    if (img.getAttribute('src') && img.complete && !img.naturalWidth) failImage(img);
  });
  const setPhoto = (image, item, large = false) => {
    if (!image) return;
    const fallback = image.closest('.sls-media').querySelector('[data-photo-placeholder]');
    image.alt = item?.name || '';
    image.removeAttribute('srcset');
    image.removeAttribute('sizes');
    const source = item && (large ? (item.full_image_url || item.image_url) : item.image_url);
    if (!source) {
      image.hidden = true;
      image.removeAttribute('src');
      if (fallback) { fallback.hidden = false; const label = fallback.querySelector('span'); if (label) label.textContent = 'Sin foto'; }
      return;
    }
    image.src = source;
    image.hidden = false;
    if (fallback) fallback.hidden = true;
  };

  root.querySelectorAll('[data-sales-filter]').forEach((select) => select.addEventListener('change', () => select.form.requestSubmit()));
  root.querySelector('[data-sale-void]')?.addEventListener('submit', (event) => {
    if (!window.confirm('Anular esta venta y devolver la unidad al inventario?')) event.preventDefault();
  });
  document.addEventListener('click', (event) => {
    root.querySelectorAll('.sls-menu[open]').forEach((menu) => { if (!menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') root.querySelectorAll('.sls-menu').forEach((menu) => { menu.open = false; });
  });

  const form = $('saleForm');
  if (!form) return;
  let initial;
  try { initial = JSON.parse($('saleInitialData').textContent); }
  catch (_) { setText('saleError', 'No se pudo cargar el inventario. Recarga la pantalla.'); $('saleError').hidden = false; return; }
  const mobile = window.matchMedia('(max-width: 760px)');
  const items = new Map((initial.items || []).map((item) => [String(item.id), item]));
  const search = $('saleAssetSearch');
  const results = $('saleAssetResults');
  const selected = $('saleSelectedAsset');
  const picker = $('salePicker');
  const price = $('saleUnitPrice');
  const quantity = $('saleQuantity');
  const client = $('saleClientSelect');
  const error = $('saleError');
  const submit = $('saleSubmit');
  const nextButton = $('saleMobileNext');
  const loadMore = $('saleLoadMore');
  let current = null;
  let kind = '';
  let nextPage = initial.next_page;
  let searchTimer = 0;
  let searchSequence = 0;
  let controller = null;
  let submitting = false;
  let uploading = false;
  let step = 1;
  form.classList.add('is-enhanced');

  const showError = (message = '') => { error.textContent = message; error.hidden = !message; };
  const cancelSearch = () => {
    window.clearTimeout(searchTimer);
    searchSequence += 1;
    controller?.abort();
    results.removeAttribute('aria-busy');
    loadMore.disabled = false;
  };
  const refresh = () => {
    const count = Math.max(1, Math.floor(Number(quantity.value) || 1));
    const amount = cents(price.value);
    const priceValid = Boolean(price.value && amount > 0 && price.validity.valid);
    const unitInvestment = current ? Math.round(cents(current.investment_total) / Math.max(1, Number(current.stock_total))) : 0;
    const cost = current ? (cents(current.price) + unitInvestment) * count : 0;
    const total = amount * count;
    const profit = total - cost;
    const hasTotal = Boolean(current && priceValid && quantity.validity.valid);
    setText('saleCostPreview', current ? money(cost) : '\u2014');
    setText('saleProfitPreview', hasTotal ? money(profit) : '\u2014');
    $('saleProfitPreview').classList.toggle('sls-negative', hasTotal && profit < 0);
    $('saleProfitPreview').classList.toggle('sls-positive', !hasTotal || profit >= 0);
    $('saleLossWarning').hidden = !hasTotal || profit >= 0;
    setText('saleFinalTotal', hasTotal ? money(total) : '\u2014');
    setText('saleMobileTotal', hasTotal ? money(total) : '\u2014');
    const clientOption = client.selectedOptions[0];
    setText('saleReviewBuyer', client.value ? clientOption.textContent.split(' \u00b7 ')[0] : ($('saleBuyerName').value.trim() || 'Cliente ocasional'));
    setText('saleReviewMethod', $('salePaymentMethod').selectedOptions[0]?.textContent || '');
    setText('saleReviewDate', $('saleDate').value.split('-').reverse().join('/'));
    submit.disabled = !current || submitting || uploading;
    nextButton.disabled = submitting || uploading;
  };
  const paintSelected = () => {
    if (!current) return;
    const isVehicle = ['car', 'motorcycle'].includes(current.kind);
    setText('saleProductHeading', isVehicle ? 'Veh\u00edculo seleccionado' : 'Art\u00edculo seleccionado');
    setText('saleSelectedKind', current.kind_label || (isVehicle ? 'Veh\u00edculo' : 'Art\u00edculo'));
    setText('saleSelectedName', current.name);
    setText('saleIdentifierLabel', isVehicle ? 'Placa / chasis' : 'Identificador / serial');
    setText('saleSelectedIdentifier', current.identifier || current.serial_number || '\u2014');
    setText('saleSelectedModel', [current.brand, current.model].filter(Boolean).join(' ') || '\u2014');
    setText('saleYearLabel', isVehicle ? 'A\u00f1o' : 'Existencia');
    setText('saleSelectedYear', isVehicle ? (current.vehicle_year || '\u2014') : `${current.available} disponibles`);
    setText('saleMileageLabel', isVehicle ? 'Kilometraje' : 'Serial');
    setText('saleSelectedMileage', isVehicle ? (current.mileage != null ? `${Number(current.mileage).toLocaleString('es-DO')} km` : '\u2014') : (current.serial_number || '\u2014'));
    setText('saleTargetPrice', Number(current.sale_price) > 0 ? money(cents(current.sale_price)) : 'Por definir');
    setText('saleReviewName', current.name);
    setText('saleReviewMeta', [current.vehicle_year, current.identifier || current.serial_number].filter(Boolean).join(' \u00b7 '));
    setPhoto($('saleSelectedImage'), current, true);
    setPhoto($('saleReviewImage'), current);
    $('saleReviewProduct').hidden = false;
    setText('salePhotoLabel', current.image_url ? 'Cambiar foto' : 'Agregar foto');
  };
  const choose = (item, preserve = false) => {
    if (!item || Number(item.available) <= 0) { showError('Esta unidad no est\u00e1 disponible. Selecciona otra.'); return; }
    cancelSearch();
    current = item;
    $('saleAssetId').value = item.id;
    const isVehicle = ['car', 'motorcycle'].includes(item.kind);
    quantity.max = isVehicle ? '1' : String(item.available);
    quantity.readOnly = isVehicle;
    if (!preserve || isVehicle) quantity.value = '1';
    if (!preserve) price.value = Number(item.sale_price) > 0 ? Number(item.sale_price).toFixed(2) : '';
    selected.hidden = false;
    picker.hidden = true;
    $('salePhotoStatus').hidden = true;
    showError();
    paintSelected();
    refresh();
    if (mobile.matches && !preserve) root.scrollIntoView({ behavior: 'auto', block: 'start' });
  };
  const renderItems = (rows, append = false) => {
    const template = $('salePickerCardTemplate');
    const fragment = document.createDocumentFragment();
    rows.forEach((item) => {
      items.set(String(item.id), item);
      const button = template.content.firstElementChild.cloneNode(true);
      button.dataset.selectAsset = String(item.id);
      button.setAttribute('aria-label', `Seleccionar ${item.name}`);
      button.querySelector('.sls-picker-title').textContent = item.name;
      button.querySelector('.sls-picker-spec').textContent = [item.vehicle_year || item.kind_label, item.identifier || item.serial_number].filter(Boolean).join(' \u00b7 ');
      button.querySelector('.sls-picker-bottom strong').textContent = Number(item.sale_price) > 0 ? money(cents(item.sale_price)) : 'Precio por definir';
      const image = button.querySelector('[data-asset-image]');
      setPhoto(image, item);
      fragment.append(button);
    });
    if (!append) results.replaceChildren();
    results.append(fragment);
    $('saleInventoryEmpty').hidden = results.children.length > 0;
  };
  const load = async (page = 1) => {
    cancelSearch();
    controller = new AbortController();
    const token = searchSequence;
    results.setAttribute('aria-busy', 'true');
    loadMore.disabled = true;
    setText('saleSearchStatus', 'Buscando inventario...');
    const url = new URL(form.dataset.lookupUrl, location.origin);
    url.searchParams.set('q', search.value.trim());
    url.searchParams.set('kind', kind);
    url.searchParams.set('page', String(page));
    const timeout = window.setTimeout(() => { if (token === searchSequence) controller?.abort(); }, 15000);
    try {
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal, headers: { Accept: 'application/json' } });
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('lookup');
      const data = await response.json();
      if (!data.ok || !Array.isArray(data.items)) throw new Error('lookup');
      if (token !== searchSequence || current) return;
      renderItems(data.items, page > 1);
      nextPage = data.next_page;
      loadMore.hidden = !nextPage;
      setText('saleSearchStatus', `${data.total} resultado${data.total === 1 ? '' : 's'} en inventario`);
      showError();
    } catch (err) {
      if (token !== searchSequence) return;
      setText('saleSearchStatus', 'No se pudo actualizar. Reintenta la b\u00fasqueda.');
      showError('No se pudo consultar el inventario. Revisa tu conexi\u00f3n.');
      // Keep the previously loaded cards, but do not present an error as empty stock.
    } finally {
      window.clearTimeout(timeout);
      if (token === searchSequence) { results.removeAttribute('aria-busy'); loadMore.disabled = false; }
    }
  };
  results.addEventListener('click', (event) => {
    const button = event.target.closest('[data-select-asset]');
    if (button) choose(items.get(button.dataset.selectAsset));
  });
  search.addEventListener('input', () => {
    cancelSearch();
    searchTimer = window.setTimeout(() => load(1), 220);
  });
  search.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); load(1); }
  });
  form.querySelectorAll('[data-kind]').forEach((button) => button.addEventListener('click', () => {
    kind = button.dataset.kind;
    form.querySelectorAll('[data-kind]').forEach((b) => b.setAttribute('aria-pressed', String(b === button)));
    load(1);
  }));
  loadMore.addEventListener('click', () => { if (nextPage) load(nextPage); });
  $('saleAssetClear').addEventListener('click', () => {
    current = null;
    $('saleAssetId').value = '';
    selected.hidden = true;
    picker.hidden = false;
    $('saleReviewProduct').hidden = true;
    setPhoto($('saleSelectedImage'), null);
    setPhoto($('saleReviewImage'), null);
    price.value = '';
    quantity.value = '1';
    quantity.readOnly = false;
    quantity.removeAttribute('max');
    setText('saleProductHeading', 'Selecciona una unidad');
    refresh();
    load(1);
  });
  const syncClient = () => {
    $('saleOccasionalFields').hidden = Boolean(client.value);
    if (!client.value) {
      const input = form.querySelector('[data-remote-target="saleClientSelect"]');
      if (input) input.value = '';
    }
    refresh();
  };
  client.addEventListener('change', syncClient);
  form.addEventListener('input', (event) => { if (event.target !== search && event.target.type !== 'file') refresh(); });
  form.addEventListener('change', refresh);
  const hasAsset = () => {
    if (current) return true;
    showError('Selecciona primero una unidad del inventario.');
    search.focus();
    return false;
  };
  const validFields = () => {
    const invalid = Array.from(form.querySelectorAll('input,select,textarea')).find((element) => element.willValidate && !element.validity.valid);
    if (!invalid) return true;
    goStep(2, false);
    const disclosure = invalid.closest('details');
    if (disclosure) disclosure.open = true;
    invalid.reportValidity();
    invalid.focus();
    return false;
  };
  function goStep(value, validate = true) {
    if (submitting) return;
    if (validate && value > 1 && !hasAsset()) return;
    if (validate && value > 2 && !validFields()) return;
    step = value;
    form.dataset.step = String(step);
    form.querySelectorAll('[data-go-step]').forEach((button) => {
      if (Number(button.dataset.goStep) === step) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
    nextButton.querySelector('span').textContent = step === 3 ? 'Registrar venta' : 'Continuar';
    showError();
    refresh();
    if (mobile.matches) root.scrollIntoView({ behavior: 'auto', block: 'start' });
  }
  form.querySelectorAll('[data-go-step]').forEach((button) => button.addEventListener('click', () => goStep(Number(button.dataset.goStep))));
  nextButton.addEventListener('click', () => {
    if (step < 3) goStep(step + 1);
    else form.requestSubmit(submit);
  });
  root.querySelector('[data-sales-back]')?.addEventListener('click', (event) => {
    if (mobile.matches && step > 1) { event.preventDefault(); goStep(step - 1, false); }
  });
  // Explicit validation can reveal a hidden mobile step before the browser focuses it.
  form.noValidate = true;
  form.addEventListener('submit', (event) => {
    if (submitting || uploading) { event.preventDefault(); return; }
    if (!hasAsset() || !validFields()) { event.preventDefault(); return; }
    if (mobile.matches && step !== 3) { event.preventDefault(); goStep(3); return; }
    submitting = true;
    refresh();
    submit.textContent = 'Registrando...';
    nextButton.querySelector('span').textContent = 'Registrando...';
  });
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    submitting = false;
    submit.textContent = 'Registrar venta';
    goStep(step, false);
    refresh();
  });
  $('salePhotoInput')?.addEventListener('change', async (event) => {
    const file = event.target.files?.[0];
    if (!file || !current?.photo_upload_url) return;
    const notice = $('salePhotoStatus');
    notice.hidden = false;
    notice.classList.remove('sls-error');
    if (file.size > 12 * 1024 * 1024) { notice.textContent = 'La foto no puede pesar m\u00e1s de 12 MB.'; notice.classList.add('sls-error'); event.target.value = ''; return; }
    const assetId = String(current.id);
    const url = current.photo_upload_url;
    const data = new FormData();
    data.append('image', file);
    data.append('csrf_token', form.elements.csrf_token.value);
    notice.textContent = 'Guardando y optimizando la foto...';
    uploading = true;
    event.target.disabled = true;
    $('saleAssetClear').disabled = true;
    refresh();
    const uploadController = new AbortController();
    const uploadTimeout = window.setTimeout(() => uploadController.abort(), 30000);
    try {
      const response = await fetch(url, { method: 'POST', body: data, credentials: 'same-origin', signal: uploadController.signal, headers: { Accept: 'application/json' } });
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('No se pudo guardar la foto. Recarga la pantalla e intenta nuevamente.');
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || 'No se pudo guardar la foto.');
      items.set(String(result.item.id), result.item);
      if (String(current?.id) === assetId) { current = result.item; paintSelected(); notice.textContent = 'Foto guardada en el inventario.'; }
    } catch (err) {
      notice.classList.add('sls-error');
      notice.textContent = err.name === 'AbortError' ? 'La carga tardó demasiado. Revisa tu conexión e intenta otra vez.' : (err.message || 'No se pudo guardar la foto.');
    } finally {
      window.clearTimeout(uploadTimeout);
      uploading = false;
      event.target.value = '';
      event.target.disabled = false;
      $('saleAssetClear').disabled = false;
      refresh();
    }
  });
  if (initial.selected) choose(initial.selected, true);
  else $('saleAssetId').value = '';
  // A preselected GET has no posted price to preserve.
  if (initial.selected && !initial.posted && !price.value && Number(initial.selected.sale_price) > 0) price.value = Number(initial.selected.sale_price).toFixed(2);
  syncClient();
  refresh();
})();
