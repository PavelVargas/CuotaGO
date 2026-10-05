(() => {
  const form = document.getElementById('contractForm');
  if (!form) return;

  const clientSelect = document.getElementById('clientSelect');
  const clientName = document.getElementById('clientName');
  const clientPhone = document.getElementById('clientPhone');
  const assetSelect = document.getElementById('assetSelect');
  const assetName = document.getElementById('assetName');
  const assetStockQuantity = document.getElementById('assetStockQuantity');
  const contractQuantity = document.getElementById('contractQuantity');
  const stockAvailableHint = document.getElementById('stockAvailableHint');
  const detectedAssetName = document.getElementById('detectedAssetName');
  const unitPrice = document.getElementById('unitPrice');
  const installmentCount = document.getElementById('installmentCount');
  const profitMarginPercent = document.getElementById('profitMarginPercent');
  const profitAmountPreview = document.getElementById('profitAmountPreview');
  const dailyLateInterest = document.getElementById('dailyLateInterest');
  const total = document.getElementById('totalAmount');
  const down = document.getElementById('downPayment');
  const downPaymentMeta = document.querySelector('[data-down-payment-meta]');
  const installment = document.getElementById('installmentAmount');
  const startDate = document.getElementById('startDate');
  const firstDue = document.getElementById('firstDueDate');
  const preview = document.getElementById('schedulePreview');
  const money = new Intl.NumberFormat('es-DO', {style:'currency', currency:'DOP', minimumFractionDigits:0, maximumFractionDigits:2});

  let initializing = true;
  let currentStep = 1;
  let clientMode = form.dataset.clientMode || (clientSelect?.options?.length > 1 ? 'existing' : 'new');
  let assetMode = form.dataset.assetMode || (assetSelect?.options?.length > 1 ? 'existing' : 'new');
  let dueTouched = form.dataset.dueTouched === '1';
  let priceTouched = form.dataset.priceTouched === '1';
  let marginTouched = form.dataset.marginTouched === '1';

  const currentAsset = () => assetSelect?.selectedOptions?.[0] || null;
  const selectedFrequency = () => document.querySelector('input[name="frequency"]:checked')?.value || 'monthly';
  const selectedDealType = () => document.querySelector('input[name="deal_type"]:checked')?.value || 'credit_sale';
  const syncDownPaymentMeta = () => { if (downPaymentMeta) downPaymentMeta.hidden = !(Number(down?.value || 0) > 0); };
  down?.addEventListener('input', syncDownPaymentMeta);
  syncDownPaymentMeta();

  const setClientMode = (mode) => {
    clientMode = mode;
    document.querySelectorAll('button[data-client-mode]').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.clientMode === mode);
      button.setAttribute('aria-pressed', button.dataset.clientMode === mode ? 'true' : 'false');
    });
    document.querySelectorAll('[data-client-fields]').forEach((box) => {
      box.hidden = box.dataset.clientFields !== mode;
      box.querySelectorAll('input[name],select[name],textarea[name]').forEach(el => { el.disabled = box.hidden; });
    });
    if (clientName) clientName.required = mode === 'new';
    if (clientSelect) clientSelect.required = mode === 'existing';
    refreshWizardState();
  };

  const availableQuantity = () => assetMode === 'new'
    ? Math.max(0, Number(assetStockQuantity?.value || 0))
    : Math.max(0, Number(currentAsset()?.dataset?.available || 0));

  const setAssetMode = (mode) => {
    const changed = assetMode !== mode;
    assetMode = mode;
    if (changed && !initializing) { unitPrice.value = ''; profitMarginPercent.value = '0'; priceTouched = false; marginTouched = false; }
    document.querySelectorAll('button[data-asset-mode]').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.assetMode === mode);
      button.setAttribute('aria-pressed', button.dataset.assetMode === mode ? 'true' : 'false');
    });
    document.querySelectorAll('[data-asset-fields]').forEach((box) => {
      box.hidden = box.dataset.assetFields !== mode;
      box.querySelectorAll('input[name],select[name],textarea[name]').forEach(el => { el.disabled = box.hidden; });
    });
    if (assetName) assetName.required = mode === 'new';
    if (assetStockQuantity) assetStockQuantity.required = mode === 'new';
    if (assetSelect) assetSelect.required = mode === 'existing';
    if (mode === 'existing') syncAssetPrice(!initializing);
    syncStock();
    refreshWizardState();
  };

  const syncStock = () => {
    const available = availableQuantity();
    if (contractQuantity) contractQuantity.max = String(Math.max(available, 1));
    if (stockAvailableHint) stockAvailableHint.innerHTML = `<b>${available}</b><span>${available === 1 ? 'disponible' : 'disponibles'}</span>`;
  };

  const syncAssetPrice = (force = false) => {
    if (assetMode === 'new') {
      if (detectedAssetName) detectedAssetName.textContent = assetName?.value?.trim() || 'Artículo nuevo';
      return;
    }
    const option = currentAsset();
    const price = Number(option?.dataset?.price || 0);
    const salePrice = Number(option?.dataset?.salePrice || 0);
    if (detectedAssetName) detectedAssetName.textContent = option?.dataset?.name || 'Selecciona un artículo';
    if (unitPrice && (force || !priceTouched || !unitPrice.value)) {
      unitPrice.value = price > 0 ? String(price) : '';
      priceTouched = false;
    }
    if (profitMarginPercent && (force || !marginTouched)) {
      const margin = price > 0 && salePrice > 0 ? ((salePrice - price) / price) * 100 : 0;
      profitMarginPercent.value = String(Math.max(0, margin.toFixed(2)));
      marginTouched = false;
    }
  };

  const autoDue = () => {
    if (dueTouched || !startDate?.value || !firstDue) return;
    const parts = startDate.value.split('-').map(Number);
    if (parts.length !== 3) return;
    const d = new Date(parts[0], parts[1] - 1, parts[2], 12, 0, 0);
    const freq = selectedFrequency();
    if (freq === 'weekly') d.setDate(d.getDate() + 7);
    else if (freq === 'biweekly') d.setDate(d.getDate() + 14);
    else {
      const originalDay = d.getDate();
      d.setDate(1);
      d.setMonth(d.getMonth() + 1);
      const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
      d.setDate(Math.min(originalDay, lastDay));
    }
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    firstDue.value = `${y}-${m}-${day}`;
  };

  const updatePresetState = () => {
    const count = Number(installmentCount?.value || 0);
    document.querySelectorAll('[data-installment-count]').forEach((button) => {
      button.classList.toggle('is-active', Number(button.dataset.installmentCount) === count);
    });
  };

  const calculation = () => {
    const unit = Math.max(0, Number(unitPrice?.value || 0));
    const qty = Math.max(1, Number(contractQuantity?.value || 1));
    const base = unit * qty;
    const marginPercent = Math.max(0, Number(profitMarginPercent?.value || 0));
    const profit = base * (marginPercent / 100);
    const gross = base + profit;
    const initial = Math.max(0, Number(down?.value || 0));
    const pending = Math.max(0, gross - initial);
    const count = Math.max(0, Math.floor(Number(installmentCount?.value || 0)));
    const perPayment = count ? pending / count : 0;
    return {unit, qty, base, marginPercent, profit, gross, initial, pending, count, perPayment};
  };

  const updateSummary = () => {
    const calc = calculation();
    const late = Math.max(0, Number(dailyLateInterest?.value || 0));
    if (total) total.value = calc.gross > 0 ? calc.gross.toFixed(2) : '';
    if (profitAmountPreview) profitAmountPreview.textContent = `+${money.format(calc.profit || 0)}`;
    if (installment) installment.value = calc.perPayment > 0 ? calc.perPayment.toFixed(2) : '0.00';
    updatePresetState();

    if (!calc.unit || !calc.count) {
      preview.innerHTML = '<span>Plan calculado</span><strong>Completa precio y cuotas.</strong>';
    } else {
      const labels = {weekly:'semanales', biweekly:'quincenales', monthly:'mensuales'};
      const initialCopy = calc.initial > 0 ? ` &middot; inicial ${money.format(calc.initial)}` : '';
      const marginCopy = calc.marginPercent > 0 ? ` &middot; ganancia ${calc.marginPercent.toLocaleString('es-DO', {maximumFractionDigits:2})}%` : '';
      const lateCopy = late > 0 ? ` &middot; atraso ${money.format(late)}/dia` : '';
      preview.innerHTML = `<span>Base ${money.format(calc.base)}${marginCopy}${initialCopy}</span><strong>Total ${money.format(calc.gross)} &middot; ${calc.count} cuotas ${labels[selectedFrequency()]} de aprox. ${money.format(calc.perPayment)}${lateCopy}</strong>`;
    }
    updateReview();
  };

  const clientDisplay = () => clientMode === 'existing'
    ? (clientSelect?.selectedOptions?.[0]?.textContent?.trim() || 'Sin cliente')
    : (clientName?.value?.trim() || 'Cliente nuevo');

  const assetDisplay = () => {
    const qty = Math.max(1, Number(contractQuantity?.value || 1));
    const name = assetMode === 'existing'
      ? (currentAsset()?.dataset?.name || currentAsset()?.textContent?.split(' \u00b7 ')[0] || 'Sin articulo')
      : (assetName?.value?.trim() || 'Artículo nuevo');
    return `${qty} x ${name}`;
  };

  const updateReview = () => {
    const calc = calculation();
    const labels = {weekly:'semanales', biweekly:'quincenales', monthly:'mensuales'};
    const reviewClient = document.getElementById('reviewClient');
    const reviewAsset = document.getElementById('reviewAsset');
    const reviewPlan = document.getElementById('reviewPlan');
    const reviewDue = document.getElementById('reviewDue');
    const reviewTotal = document.getElementById('reviewTotal');
    const reviewExtra = document.getElementById('reviewExtra');
    if (reviewClient) reviewClient.textContent = clientDisplay();
    if (reviewAsset) reviewAsset.textContent = assetDisplay();
    if (reviewPlan) reviewPlan.textContent = calc.count ? `${calc.count} cuotas ${labels[selectedFrequency()]} de ${money.format(calc.perPayment)}` : '-';
    if (reviewDue) reviewDue.textContent = firstDue?.value ? firstDue.value.split('-').reverse().join('/') : '-';
    if (reviewTotal) reviewTotal.textContent = money.format(calc.gross || 0);
    if (reviewExtra) {
      const parts = [];
      if (calc.marginPercent > 0) parts.push(`Ganancia ${calc.marginPercent.toLocaleString('es-DO', {maximumFractionDigits:2})}% (+${money.format(calc.profit)})`);
      if (calc.initial > 0) parts.push(`Inicial ${money.format(calc.initial)}`);
      const late = Math.max(0, Number(dailyLateInterest?.value || 0));
      if (late > 0) parts.push(`Interes por atraso ${money.format(late)}/dia`);
      parts.push(selectedDealType() === 'rental' ? 'Préstamo / alquiler' : 'Venta a crédito');
      reviewExtra.textContent = parts.join(' \u00b7 ');
    }
  };

  const stepError = (step, message = '') => {
    const box = document.querySelector(`[data-step-error="${step}"]`);
    if (!box) return;
    box.textContent = message;
    box.hidden = !message;
  };

  const validateStep = (step, showError = false) => {
    let message = '';
    if (step === 1) {
      if (clientMode === 'existing' && !clientSelect?.value) message = 'Selecciona un cliente para continuar.';
      if (clientMode === 'new' && (clientName?.value?.trim()?.length || 0) < 2) message = 'Escribe el nombre del cliente.';
    }
    if (step === 2) {
      const qty = Math.max(0, Number(contractQuantity?.value || 0));
      const available = availableQuantity();
      if (assetMode === 'existing' && !assetSelect?.value) message = 'Selecciona un artículo del inventario.';
      else if (assetMode === 'new' && (assetName?.value?.trim()?.length || 0) < 2) message = 'Escribe el nombre del articulo.';
      else if (assetMode === 'new' && available < 1) message = 'Indica cuantas unidades tienes.';
      else if (!Number.isInteger(qty) || qty < 1) message = 'Indica la cantidad a entregar.';
      else if (qty > available) message = `Solo hay ${available} unidad(es) disponibles.`;
    }
    if (step === 3) {
      const calc = calculation();
      const late = Number(dailyLateInterest?.value || 0);
      if (!Number.isFinite(Number(unitPrice.value)) || Number(unitPrice.value) <= 0) message = 'Indica el precio base del articulo.';
      else if (!Number.isFinite(Number(profitMarginPercent.value)) || Number(profitMarginPercent.value) < 0 || Number(profitMarginPercent.value) > 1000) message = 'Revisa el margen de ganancia.';
      else if (!Number.isInteger(Number(installmentCount.value)) || calc.count < 1 || calc.count > 500) message = 'Elige entre 1 y 500 cuotas.';
      else if (!Number.isFinite(Number(down.value)) || Number(down.value) < 0 || calc.initial > calc.gross) message = 'Revisa el monto inicial.';
      else if (!firstDue?.value) message = 'Selecciona la fecha del primer pago.';
      else if (startDate?.value && firstDue.value < startDate.value) message = 'El primer pago no puede ser antes de la entrega.';
      else if (!Number.isFinite(late) || late < 0) message = 'El interes diario no puede ser negativo.';
    }
    if (!message) {
      const controls = step === 1 ? (clientMode === 'new' ? [clientName,clientPhone] : [clientSelect])
        : step === 2 ? [contractQuantity, ...(assetMode === 'new' ? [assetName,assetStockQuantity] : [assetSelect])]
        : [unitPrice,profitMarginPercent,installmentCount,down,dailyLateInterest,firstDue,startDate];
      const invalid = controls.find(el => el && !el.disabled && !el.checkValidity());
      if (invalid) message = invalid.validationMessage || 'Revisa los datos antes de continuar.';
    }
    if (showError) stepError(step, message);
    return !message;
  };

  const canReachStep = (target) => {
    for (let step = 1; step < target; step += 1) if (!validateStep(step, false)) return false;
    return true;
  };

  const updateProgress = () => {
    document.querySelectorAll('[data-step-target]').forEach((button) => {
      const step = Number(button.dataset.stepTarget);
      button.classList.toggle('is-active', step === currentStep);
      if (step === currentStep) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
      button.classList.toggle('is-complete', step < currentStep && validateStep(step, false));
      button.disabled = step > currentStep && !canReachStep(step);
    });
  };

  const refreshWizardState = () => {
    updateSummary();
    syncStock();
    const next = document.querySelector(`[data-wizard-step="${currentStep}"] [data-next-step]`);
    if (next) next.disabled = !validateStep(currentStep, false);
    if (validateStep(currentStep, false)) stepError(currentStep, '');
    updateProgress();
    updateVisualContext();
  };

  const setStep = (step) => {
    const previousStep = currentStep;
    if (step > currentStep && !canReachStep(step)) {
      for (let index = 1; index < step; index += 1) {
        if (!validateStep(index, false)) {
          currentStep = index;
          validateStep(index, true);
          break;
        }
      }
    } else {
      currentStep = step;
    }
    document.querySelectorAll('[data-wizard-step]').forEach((panel) => {
      const active = Number(panel.dataset.wizardStep) === currentStep;
      panel.hidden = !active;
      panel.classList.toggle('is-active', active);
    });
    if (currentStep === 3) {
      syncAssetPrice(false);
      autoDue();
    }
    updateSummary();
    refreshWizardState();
    onStepShown(previousStep);
    const pageTop = document.querySelector('.wizard-progress')?.getBoundingClientRect().top || 0;
    if (pageTop < 0) window.scrollTo({top: Math.max(0, window.scrollY + pageTop - 74), behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  };

  document.querySelectorAll('button[data-client-mode]').forEach((button) => button.addEventListener('click', () => setClientMode(button.dataset.clientMode)));
  document.querySelectorAll('button[data-asset-mode]').forEach((button) => button.addEventListener('click', () => setAssetMode(button.dataset.assetMode)));

  clientSelect?.addEventListener('change', refreshWizardState);
  clientName?.addEventListener('input', refreshWizardState);
  clientPhone?.addEventListener('input', updateReview);
  assetSelect?.addEventListener('change', () => { priceTouched = false; marginTouched = false; syncAssetPrice(true); syncStock(); refreshWizardState(); });
  assetName?.addEventListener('input', () => { syncAssetPrice(false); refreshWizardState(); });
  assetStockQuantity?.addEventListener('input', refreshWizardState);
  contractQuantity?.addEventListener('input', refreshWizardState);
  unitPrice?.addEventListener('input', () => { priceTouched = true; refreshWizardState(); });
  installmentCount?.addEventListener('input', refreshWizardState);
  profitMarginPercent?.addEventListener('input', () => { marginTouched = true; refreshWizardState(); });
  dailyLateInterest?.addEventListener('input', refreshWizardState);
  down?.addEventListener('input', refreshWizardState);
  startDate?.addEventListener('change', () => { dueTouched = false; autoDue(); refreshWizardState(); });
  firstDue?.addEventListener('change', () => { dueTouched = true; refreshWizardState(); });

  document.querySelectorAll('input[name="frequency"], input[name="deal_type"]').forEach((el) => el.addEventListener('change', () => {
    if (el.name === 'frequency') { dueTouched = false; autoDue(); }
    refreshWizardState();
  }));

  document.querySelectorAll('[data-installment-count]').forEach((button) => button.addEventListener('click', () => {
    if (installmentCount) installmentCount.value = button.dataset.installmentCount;
    refreshWizardState();
  }));

  document.querySelectorAll('[data-next-step]').forEach((button) => button.addEventListener('click', () => {
    const next = Number(button.dataset.nextStep);
    if (!validateStep(currentStep, true)) return;
    setStep(next);
  }));

  document.querySelectorAll('[data-prev-step]').forEach((button) => button.addEventListener('click', () => setStep(Number(button.dataset.prevStep))));
  document.querySelectorAll('[data-edit-step]').forEach((button) => button.addEventListener('click', () => setStep(Number(button.dataset.editStep))));
  document.querySelectorAll('[data-step-target]').forEach((button) => button.addEventListener('click', () => {
    const target = Number(button.dataset.stepTarget);
    if (target <= currentStep || canReachStep(target)) setStep(target);
  }));

  form.addEventListener('submit', (event) => {
    for (let step = 1; step <= 3; step += 1) {
      if (!validateStep(step, false)) {
        event.preventDefault();
        setStep(step);
        validateStep(step, true);
        return;
      }
    }
    if (currentStep !== 4) {
      event.preventDefault();
      setStep(4);
      return;
    }
    const createButton = document.getElementById('createContractButton');
    if (createButton) { createButton.disabled = true; createButton.textContent = 'Creando...'; }
  });

  // Photo picker: inventory photos only. No external/demo assets or hidden writes.
  const picker = document.getElementById('agreementPicker');
  const results = document.getElementById('agreementAssetResults');
  const search = document.getElementById('agreementAssetSearch');
  const status = document.getElementById('agreementResultsStatus');
  const more = document.getElementById('agreementLoadMore');
  const retry = document.getElementById('agreementRetry');
  const selectedCard = document.getElementById('agreementSelected');
  const photoInput = document.getElementById('agreementNewPhoto');
  const photoStatus = document.getElementById('agreementPhotoStatus');
  const removePhoto = document.getElementById('agreementRemovePhoto');
  let bootstrap = {items: []};
  try { bootstrap = JSON.parse(document.getElementById('agreementInventoryData')?.textContent || '{}'); } catch (_) {}
  const itemsById = new Map((bootstrap.items || []).map(item => [String(item.id), item]));
  let nextPage = null, searchTimer = null, controller = null, requestSerial = 0;
  let inventoryLoaded = false, inventoryKind = '', newPhotoUrl = '', hasStarted = false;
  let pickerOpen = !assetSelect?.value;

  const text = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
  const kindLabel = (kind) => ({car:'Veh\u00edculo', phone:'Celular', motorcycle:'Motor', computer:'Computadora', appliance:'Electrodom\u00e9stico'}[kind] || 'Art\u00edculo');
  const photoFor = (item, large) => large ? (item?.full_image_url || item?.image_url || '') : (item?.image_url || '');
  const media = (el, item, large = false) => {
    if (!el) return;
    const url = photoFor(item, large);
    const key = `${item?.id || 'new'}|${url}|${item?.kind || 'other'}`;
    if (el.dataset.mediaKey === key) return;
    el.dataset.mediaKey = key;
    el.replaceChildren();
    const placeholder = () => {
      const fallback = document.createElement('span'); fallback.className = 'ag-photo-empty';
      const template = document.getElementById(`agFallback-${item?.kind}`) || document.getElementById('agFallback-other');
      fallback.append(template.content.cloneNode(true)); el.replaceChildren(fallback);
    };
    if (!url) { placeholder(); return; }
    const img = document.createElement('img');
    img.alt = item?.name || 'Foto del art\u00edculo'; img.decoding = 'async';
    img.loading = large ? 'eager' : 'lazy'; img.width = large ? 1169 : 360; img.height = large ? 780 : 240;
    img.addEventListener('error', placeholder, {once:true}); img.src = url; el.append(img);
  };
  const metaFor = (item) => [
    item.identifier || item.serial_number || '',
    item.vehicle_year || '',
    item.mileage !== null && item.mileage !== undefined && item.mileage !== '' ? `${Number(item.mileage).toLocaleString('es-DO')} km` : '',
  ].filter(v => v !== '').join(' \u00b7 ');

  const selectedProduct = () => {
    if (assetMode === 'new') {
      if (!assetName?.value.trim()) return null;
      return {id: 'new', name: assetName.value.trim(), kind: document.getElementById('assetKind').value,
        identifier: document.getElementById('assetIdentifier').value.trim(), image_url: newPhotoUrl, full_image_url: newPhotoUrl};
    }
    if (!assetSelect?.value) return null;
    return itemsById.get(String(assetSelect.value)) || {
      id:assetSelect.value, name:currentAsset()?.dataset.name || '', kind:'other',
      available:availableQuantity(), price:currentAsset()?.dataset.price, sale_price:currentAsset()?.dataset.salePrice,
    };
  };
  const updateVisualContext = () => {
    const item = selectedProduct(); const calc = calculation();
    const hasItem = Boolean(item);
    const isExisting = assetMode === 'existing' && hasItem;
    document.getElementById('agreementOverviewEmpty').hidden = hasItem;
    document.getElementById('agreementOverviewProduct').hidden = !hasItem;
    document.getElementById('agreementReviewProduct').hidden = !hasItem;
    document.getElementById('agreementPlanProduct').hidden = !hasItem;
    selectedCard.hidden = !isExisting || pickerOpen;
    picker.hidden = isExisting && !pickerOpen;
    if (hasItem) {
      for (const prefix of ['Selected','Overview','Review','Plan']) {
        text(`agreement${prefix}Name`, item.name);
        text(`agreement${prefix}Meta`, metaFor(item) || kindLabel(item.kind));
        text(`agreement${prefix}Kind`, kindLabel(item.kind));
      }
      text('agreementSelectedPrice', Number(item.sale_price) > 0 ? money.format(Number(item.sale_price)) : 'Por definir');
      document.querySelectorAll('[data-ag-media]').forEach(el => media(el, item, ['selected','overview'].includes(el.dataset.agMedia)));
    }
    text('agreementOverviewClient', (clientMode === 'existing' ? !!clientSelect?.value : !!clientName?.value.trim()) ? clientDisplay() : 'Por seleccionar');
    text('agreementOverviewQuantity', hasItem ? `${calc.qty} unidad${calc.qty === 1 ? '' : 'es'}` : '\u2014');
    const frequency = {weekly:'semanales',biweekly:'quincenales',monthly:'mensuales'}[selectedFrequency()];
    const hasPlan = hasItem && calc.unit > 0;
    text('agreementOverviewPlan', hasPlan ? `${calc.count} cuotas ${frequency} de aprox. ${money.format(calc.perPayment)}` : 'Por definir');
    text('agreementOverviewDown', hasPlan ? money.format(calc.initial) : '\u2014');
    text('agreementOverviewTotal', hasPlan ? money.format(calc.gross) : '\u2014');
    text('agreementStepLabel', `${currentStep} / 4`);
  };
  const pick = (item) => {
    requestSerial += 1; controller?.abort();
    itemsById.set(String(item.id), item);
    let option = Array.from(assetSelect.options).find(el => el.value === String(item.id));
    if (!option) { option = document.createElement('option'); option.value = String(item.id); assetSelect.append(option); }
    option.textContent = `${item.name} \u00b7 ${item.available} disp.`;
    Object.assign(option.dataset, {name:item.name, available:item.available, price:item.price || '0', salePrice:item.sale_price || '0'});
    assetSelect.value = String(item.id); pickerOpen = false;
    contractQuantity.value = String(Math.max(1, Math.min(Number(contractQuantity.value) || 1, Number(item.available) || 1)));
    assetSelect.dispatchEvent(new Event('change', {bubbles:true}));
    window.CuotaGoMotion?.reveal(selectedCard, 'fade', 180);
    document.querySelector('[data-wizard-step="2"] [data-next-step]')?.focus({preventScroll:true});
  };
  const renderInventory = (items, append = false) => {
    if (!append) results.replaceChildren();
    const fragment = document.createDocumentFragment();
    items.forEach(item => {
      itemsById.set(String(item.id), item);
      const button = document.createElement('button'); button.type = 'button'; button.className = 'ag-asset-card';
      button.setAttribute('aria-label', `Seleccionar ${item.name}. ${item.available} disponibles`);
      const picture = document.createElement('span'); picture.className = 'ag-asset-media'; media(picture, item);
      const copy = document.createElement('span'); copy.className = 'ag-asset-copy';
      const kind = document.createElement('small'); kind.className = 'ag-overline'; kind.textContent = kindLabel(item.kind);
      const name = document.createElement('strong'); name.textContent = item.name;
      const spec = document.createElement('span'); spec.className = 'ag-asset-meta'; spec.textContent = metaFor(item) || [item.brand,item.model].filter(Boolean).join(' ') || `${item.available} disponibles`;
      const bottom = document.createElement('span'); bottom.className = 'ag-asset-bottom';
      const price = document.createElement('b'); price.textContent = Number(item.sale_price) > 0 ? money.format(Number(item.sale_price)) : 'Precio por definir';
      const stock = document.createElement('small'); stock.textContent = `${item.available} disp.`;
      bottom.append(price,stock); copy.append(kind,name,spec,bottom); button.append(picture,copy);
      button.addEventListener('click', () => pick(item)); fragment.append(button);
    });
    results.append(fragment);
  };
  const loadInventory = async (page = 1) => {
    clearTimeout(searchTimer); controller?.abort(); controller = new AbortController();
    const serial = ++requestSerial;
    const append = page > 1;
    more.disabled = true; retry.hidden = true; results.setAttribute('aria-busy','true');
    status.textContent = append ? 'Cargando m\u00e1s art\u00edculos\u2026' : 'Buscando en inventario\u2026';
    const url = new URL(form.dataset.inventoryUrl, location.origin);
    url.searchParams.set('q', search.value.trim()); url.searchParams.set('kind', inventoryKind); url.searchParams.set('page', page);
    try {
      const response = await fetch(url, {headers:{Accept:'application/json'}, credentials:'same-origin', cache:'no-store', signal:controller.signal});
      if (!response.ok) throw new Error(response.status === 403 ? 'No tienes permiso para consultar este inventario.' : response.status === 401 ? 'Tu sesi\u00f3n venci\u00f3. Vuelve a entrar.' : 'No se pudo cargar el inventario.');
      const data = await response.json(); if (serial !== requestSerial) return;
      if (!data.ok || !Array.isArray(data.items)) throw new Error('La respuesta de inventario no es v\u00e1lida.');
      renderInventory(data.items, append); nextPage = data.next_page; more.hidden = !nextPage;
      status.textContent = data.total ? `${data.total} art\u00edculo${data.total === 1 ? '' : 's'} disponible${data.total === 1 ? '' : 's'}` : 'No hay art\u00edculos disponibles con estos filtros.';
      inventoryLoaded = true;
    } catch (error) {
      if (serial !== requestSerial || error.name === 'AbortError') return;
      // Never display unrelated results underneath a failed search.
      if (!append) results.replaceChildren();
      status.textContent = navigator.onLine === false ? 'Sin conexi\u00f3n. Reconecta para consultar el inventario.' : (error instanceof SyntaxError ? 'La sesi\u00f3n puede haber vencido. Vuelve a entrar.' : error.message);
      retry.hidden = false; more.hidden = true;
    } finally {
      if (serial === requestSerial) { more.disabled = false; results.removeAttribute('aria-busy'); }
    }
  };
  const onStepShown = (previousStep) => {
    updateVisualContext();
    if (currentStep === 2 && assetMode === 'existing' && !inventoryLoaded && pickerOpen) loadInventory();
    if (hasStarted && previousStep !== currentStep) {
      const panel = form.querySelector(`[data-wizard-step="${currentStep}"]`);
      window.CuotaGoMotion?.reveal(panel, currentStep < previousStep ? 'back' : 'forward', 210);
      panel.querySelector('h2')?.focus({preventScroll:true});
    }
    hasStarted = true;
  };
  search.addEventListener('input', () => {
    controller?.abort(); requestSerial += 1; clearTimeout(searchTimer);
    // Clear old search results immediately; stale cars must not stay clickable.
    results.replaceChildren(); more.hidden = true; retry.hidden = true;
    status.textContent = 'Buscando en inventario\u2026';
    searchTimer = setTimeout(() => loadInventory(), 200);
  });
  search.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); loadInventory(); } });
  document.querySelectorAll('[data-ag-kind]').forEach(button => button.addEventListener('click', () => {
    inventoryKind = button.dataset.agKind;
    document.querySelectorAll('[data-ag-kind]').forEach(el => el.setAttribute('aria-pressed', String(el === button)));
    results.replaceChildren(); loadInventory();
  }));
  more.addEventListener('click', () => { if (nextPage) loadInventory(nextPage); });
  retry.addEventListener('click', () => loadInventory());
  document.getElementById('agreementChangeAsset').addEventListener('click', () => {
    pickerOpen = true; updateVisualContext(); loadInventory(); search.focus({preventScroll:true});
  });

  const clearPhoto = () => {
    if (newPhotoUrl) URL.revokeObjectURL(newPhotoUrl);
    newPhotoUrl = ''; if (photoInput) photoInput.value = ''; if (removePhoto) removePhoto.hidden = true;
    const preview = document.getElementById('agreementNewPhotoPreview');
    if (preview) { delete preview.dataset.mediaKey; media(preview, {kind:document.getElementById('assetKind').value}); }
    updateVisualContext();
  };
  photoInput?.addEventListener('change', () => {
    const file = photoInput.files?.[0];
    if (!file) return;
    if (file.size > 12 * 1024 * 1024 || (file.type && !['image/jpeg','image/png','image/webp'].includes(file.type))) {
      clearPhoto(); photoStatus.textContent = 'Usa una foto JPG, PNG o WebP de hasta 12 MB.'; return;
    }
    if (newPhotoUrl) URL.revokeObjectURL(newPhotoUrl);
    newPhotoUrl = URL.createObjectURL(file); removePhoto.hidden = false;
    photoStatus.textContent = `${file.name} \u00b7 Se guardar\u00e1 junto con el acuerdo.`;
    media(document.getElementById('agreementNewPhotoPreview'), {id:'new',kind:document.getElementById('assetKind').value,name:assetName.value,full_image_url:newPhotoUrl},true);
    updateVisualContext();
  });
  removePhoto?.addEventListener('click', () => { clearPhoto(); photoStatus.textContent = 'Opcional \u00b7 JPG, PNG o WebP \u00b7 hasta 12 MB'; });
  document.getElementById('assetKind').addEventListener('change', updateVisualContext);
  document.getElementById('assetIdentifier').addEventListener('input', updateVisualContext);
  const actionMenu = document.querySelector('.ag-more-menu');
  document.addEventListener('click', event => { if (actionMenu?.open && !actionMenu.contains(event.target)) actionMenu.open = false; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && actionMenu?.open) { actionMenu.open = false; actionMenu.querySelector('summary').focus(); } });
  renderInventory((bootstrap.items || []).slice(0,12));
  status.textContent = 'Art\u00edculos disponibles en inventario';
  form.classList.add('has-photo-picker');

  setClientMode(clientMode);
  setAssetMode(assetMode);
  syncAssetPrice(false);
  autoDue();
  updateSummary();
  setStep(1);
  initializing = false;
})();
