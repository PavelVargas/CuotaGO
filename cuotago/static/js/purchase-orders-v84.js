/* Purchase editor. No wizard, no hidden business step, no offline money queue. */
(() => {
  'use strict';
  document.querySelectorAll('[data-receive-all]').forEach(button => button.addEventListener('click', () => {
    button.closest('form').querySelectorAll('input[name^="qty_"]').forEach(input => {
      input.value = input.max || '0'; input.dispatchEvent(new Event('input', {bubbles:true}));
    });
  }));
  const form = document.querySelector('[data-order-editor]');
  if (!form) return;
  const section = form.closest('.po-v84'), lines = form.querySelector('[data-order-lines]');
  const template = section.querySelector('[data-order-row-template]');
  const dialog = section.querySelector('[data-catalog]'), results = dialog.querySelector('[data-catalog-results]');
  const search = dialog.querySelector('[data-catalog-search]'), status = dialog.querySelector('[data-catalog-status]');
  const more = dialog.querySelector('[data-catalog-more]'), errorBox = form.querySelector('[data-form-error]');
  const buttons = [...form.querySelectorAll('button[type=submit]')];
  let busy = false, dirty = false, replaceRow = null, controller = null, searchTimer = null, page = 1, searchVersion = 0;
  let seed = [];
  try { seed = JSON.parse(section.querySelector('[data-catalog-seed]').textContent); } catch (_) { /* Server search remains available. */ }
  const currency = form.dataset.currency || 'DOP';
  let format;
  try { format = new Intl.NumberFormat('es-DO', {style:'currency', currency}); }
  catch (_) { format = new Intl.NumberFormat('es-DO', {minimumFractionDigits:2, maximumFractionDigits:2}); }
  const money = value => format.format(value);
  const field = (row, name) => row.querySelector(`[name="${name}"]`);
  const uid = () => typeof crypto.randomUUID === 'function' ? crypto.randomUUID().replace(/-/g,'') :
    Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2,'0')).join('');
  function showError(message) { errorBox.textContent = message; errorBox.hidden = !message; if (message) errorBox.focus({preventScroll:false}); }
  function revoke(row) { if (row.dataset.blob) { URL.revokeObjectURL(row.dataset.blob); delete row.dataset.blob; } }
  function photo(row, url, label) {
    const image = row.querySelector('[data-photo-preview]');
    image.hidden = !url; image.alt = 'Foto de ' + (label || 'producto');
    if (url) image.src = url; else image.removeAttribute('src');
    row.querySelector('[data-photo-placeholder]').hidden = !!url;
    row.querySelector('[data-clear-photo]').hidden = !url;
  }
  function sum() {
    let cents = 0;
    for (const row of lines.children) {
      const quantity = Number(field(row,'line_quantity').value), cost = Number(field(row,'line_unit_cost').value);
      const subtotal = Number.isFinite(quantity) && Number.isFinite(cost) ? quantity * Math.round(cost * 100) : 0;
      cents += subtotal;
      row.querySelector('[data-line-total]').textContent = money(subtotal / 100);
    }
    form.querySelector('[data-line-count]').textContent = String(lines.children.length);
    form.querySelector('[data-empty]').hidden = lines.children.length > 0;
    form.querySelector('[data-order-total]').textContent = money(cents / 100);
  }
  function setProduct(row, asset) {
    revoke(row);
    const upload = row.querySelector('[data-photo-input]'); upload.value = '';
    field(row,'line_clear_photo').value = '0';
    row.dataset.existing = asset ? '1' : '0';
    field(row,'line_asset_id').value = asset ? String(asset.id) : '';
    const name = field(row,'line_name'); name.value = asset ? asset.name : ''; name.readOnly = !!asset;
    name.setCustomValidity('');
    field(row,'line_kind').value = asset && asset.kind !== 'otro' ? asset.kind : 'other';
    row.querySelector('.po-kind-field').hidden = !!asset;
    row.querySelector('[data-product-origin]').textContent = asset ? 'Inventario' : 'Producto nuevo';
    field(row,'line_unit_cost').value = asset ? asset.cost : '';
    row.dataset.originalPhoto = asset ? (asset.photo || '') : '';
    photo(row, row.dataset.originalPhoto, name.value);
    dirty = true; sum();
  }
  function add(asset) {
    if (lines.children.length >= 100) { showError('La orden admite hasta 100 productos.'); return null; }
    const row = template.content.firstElementChild.cloneNode(true), key = uid();
    field(row,'line_key').value = key; row.querySelector('[data-photo-input]').name = 'photo_' + key;
    lines.append(row); setProduct(row, asset); return row;
  }
  function choose(asset) {
    const row = replaceRow && replaceRow.isConnected ? replaceRow : add(asset);
    if (replaceRow && row) setProduct(row, asset);
    replaceRow = null; dialog.close();
    if (row) field(row,'line_quantity').focus({preventScroll:false});
  }
  function renderAssets(items, append = false) {
    if (!append) results.replaceChildren();
    for (const asset of items) {
      const button = document.createElement('button'); button.type='button'; button.className='po-candidate';
      if (asset.photo) {
        const image = document.createElement('img'); image.src=asset.photo; image.alt='Foto de '+asset.name; image.loading='lazy';
        image.addEventListener('error', () => { image.hidden=true; }, {once:true}); button.append(image);
      } else { const box=document.createElement('span');box.className='po-candidate-photo';box.textContent='Sin foto';button.append(box); }
      const copy=document.createElement('span');copy.className='po-candidate-copy';
      const title=document.createElement('strong');title.textContent=asset.name;
      const meta=document.createElement('small');meta.textContent=[asset.year,asset.identifier].filter(Boolean).join(' / ');
      const price=document.createElement('small');price.textContent='Costo: '+money(Number(asset.cost)||0);
      copy.append(title);if(meta.textContent)copy.append(meta);copy.append(price);button.append(copy);
      const plus=document.createElement('span');plus.textContent='+';plus.setAttribute('aria-hidden','true');button.append(plus);
      button.addEventListener('click',()=>choose(asset));results.append(button);
    }
  }
  async function loadCatalog(append = false) {
    controller?.abort(); controller = new AbortController(); const version=++searchVersion;
    status.textContent='Buscando...';more.disabled=true;
    try {
      const url=new URL(form.dataset.catalogUrl,location.origin);url.searchParams.set('q',search.value.trim());url.searchParams.set('page',String(append?page+1:1));
      const response=await fetch(url,{signal:controller.signal,credentials:'same-origin',headers:{Accept:'application/json'}});
      if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))throw new Error('catalog');
      const data=await response.json();if(version!==searchVersion)return;
      page=data.page;renderAssets(data.items,append);more.hidden=!data.has_more;
      status.textContent=results.children.length ? `${results.children.length} productos disponibles` : 'No hay resultados. Prueba con otro nombre o registra uno nuevo.';
    } catch (error) {
      if(error.name==='AbortError')return;
      if(version!==searchVersion)return;
      status.textContent='No se pudo actualizar el inventario. Revisa la conexion e intenta buscar de nuevo.';
      more.hidden=true;
    } finally {if(version===searchVersion)more.disabled=false;}
  }
  function openCatalog(row = null) {
    replaceRow=row;search.value='';page=1;renderAssets(seed);status.textContent='';more.hidden=true;
    dialog.showModal();search.focus();loadCatalog();
  }
  section.querySelectorAll('[data-open-catalog]').forEach(button=>button.addEventListener('click',()=>openCatalog()));
  section.querySelector('[data-add-new]').addEventListener('click',()=>{const row=add(null);if(row)field(row,'line_name').focus();});
  dialog.querySelector('[data-catalog-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{controller?.abort();clearTimeout(searchTimer);});
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  search.addEventListener('input',()=>{controller?.abort();++searchVersion;clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadCatalog(),180);});
  more.addEventListener('click',()=>loadCatalog(true));
  lines.addEventListener('click',event=>{
    const row=event.target.closest('[data-order-line]');if(!row)return;
    if(event.target.closest('[data-remove-line]')){revoke(row);row.remove();dirty=true;sum();}
    if(event.target.closest('[data-change-product]'))openCatalog(row);
    if(event.target.closest('[data-clear-photo]')){revoke(row);row.querySelector('[data-photo-input]').value='';field(row,'line_clear_photo').value='1';photo(row,'','');dirty=true;}
  });
  lines.addEventListener('change',event=>{
    const input=event.target;if(!input.matches('[data-photo-input]'))return;
    const row=input.closest('[data-order-line]'), file=input.files[0];if(!file)return;
    if(file.size>6*1024*1024 || !['image/jpeg','image/png','image/webp'].includes(file.type)){
      input.value='';showError('Selecciona una foto JPG, PNG o WebP de hasta 6 MB.');return;
    }
    revoke(row);row.dataset.blob=URL.createObjectURL(file);photo(row,row.dataset.blob,field(row,'line_name').value);
    field(row,'line_clear_photo').value='0';dirty=true;showError('');
  });
  form.addEventListener('input',event=>{dirty=true;if(event.target.setCustomValidity)event.target.setCustomValidity('');sum();});
  function validate(draft) {
    if(!form.elements.supplier_id.value){showError('Selecciona un proveedor.');form.elements.supplier_id.focus();return false;}
    if(!draft&&!lines.children.length){showError('Agrega al menos un producto para confirmar la orden.');return false;}
    for(const row of lines.children){
      const name=field(row,'line_name'),cost=field(row,'line_unit_cost');
      name.setCustomValidity(name.value.trim().length<2?'Escribe el nombre del producto.':'');
      cost.setCustomValidity(!draft&&!(Number(cost.value)>0)?'Indica un costo mayor que cero para confirmar.':'');
    }
    for(const input of form.querySelectorAll('input,select,textarea')){
      if(!input.checkValidity()){input.reportValidity();return false;}
    }
    return true;
  }
  // Capture stops the older generic guards from trapping a corrected form.
  form.noValidate=true;
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(busy)return;
    const intent=event.submitter?.value==='draft'?'draft':'confirm';
    if(!validate(intent==='draft'))return;
    showError('');form.elements.action.value=intent;
    const data=new FormData(form);data.delete('intent'); // One canonical payload for replay.
    // The app caps the complete multipart request at 16 MB; leave header space.
    let uploaded=0;for(const value of data.values())if(value instanceof File)uploaded+=value.size;
    if(uploaded>15*1024*1024){showError('Las fotos juntas superan 15 MB. Reduce su peso antes de guardar.');return;}
    busy=true;buttons.forEach(b=>{b.disabled=true;b.setAttribute('aria-busy','true');});
    const submitController=new AbortController(),timeout=setTimeout(()=>submitController.abort(),45000);
    try {
      const response=await fetch(form.getAttribute('action')||location.href,{method:'POST',body:data,credentials:'same-origin',headers:{Accept:'application/json'},signal:submitController.signal});
      if(!response.headers.get('content-type')?.includes('application/json')){
        throw new Error(response.status===413?'Las fotos superan el limite del servidor. Reduce su peso.':'No llego una confirmacion valida. Revisa tu sesion o consulta la lista antes de repetir.');
      }
      const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'No se pudo guardar la orden.');
      const destination=new URL(result.redirect,location.origin);if(destination.origin!==location.origin)throw new Error('Destino no valido.');
      dirty=false;location.assign(destination.href);
    } catch(error) {
      showError(error.name==='AbortError'?'La respuesta tardo demasiado. Consulta la lista o reintenta sin cambiar los datos; se conserva la clave para evitar duplicados.':(error.message||'Revisa la conexion antes de reintentar.'));
    } finally {clearTimeout(timeout);busy=false;buttons.forEach(b=>{b.disabled=false;b.removeAttribute('aria-busy');});}
  },true);
  form.querySelector('[data-discard]').addEventListener('click',()=>{
    if(busy)return;
    if((dirty||form.dataset.saved==='1')&&!window.confirm('Descartar este borrador? No se registrara mercancia ni pagos.'))return;
    dirty=false;
    const saved=section.querySelector('[data-discard-form]');if(saved)saved.requestSubmit();else location.assign(form.dataset.discardUrl);
  });
  window.addEventListener('beforeunload',event=>{if(dirty&&!busy){event.preventDefault();event.returnValue='';}});
  window.addEventListener('pageshow',()=>{busy=false;buttons.forEach(b=>{b.disabled=false;b.removeAttribute('aria-busy');});});
  for(const row of lines.children){const img=row.querySelector('[data-photo-preview]');row.dataset.originalPhoto=img.getAttribute('src')||'';}
  sum();
})();
