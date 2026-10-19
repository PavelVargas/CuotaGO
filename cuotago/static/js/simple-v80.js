/* Progressive disclosure: no field renaming, data mutations or new dependencies. */
(() => {
  'use strict';
  const start = () => {
    const root = document.documentElement;
    root.classList.add('cg-simple-ready');
    const tabsHost = document.querySelector('[data-report-tabs]');
    if (tabsHost) {
      const tabs = [...tabsHost.querySelectorAll('[data-report-tab]')];
      const panels = [...document.querySelectorAll('[data-report-view]')];
      tabsHost.setAttribute('role','tablist');
      const activate = (key, focus = false, updateURL = true) => {
        if (!panels.some(panel => panel.dataset.reportView === key)) key = 'summary';
        panels.forEach(panel => {
          panel.hidden = panel.dataset.reportView !== key;
          panel.setAttribute('role','tabpanel'); panel.tabIndex = 0;
        });
        tabs.forEach(tab => {
          const active = tab.dataset.reportTab === key;
          tab.setAttribute('role','tab'); tab.setAttribute('aria-selected',String(active));
          tab.setAttribute('aria-controls','report-'+tab.dataset.reportTab);
          tab.tabIndex = active ? 0 : -1;
          tab.classList.toggle('is-active',active);
          if (active && focus) tab.focus();
        });
        if (updateURL) { try { const url = new URL(location.href); url.hash = 'report-'+key; history.replaceState(null,'',url); } catch (_) {} }
        const filter = document.querySelector('.report-filters-v19');
        if (filter) filter.action = filter.action.split('#')[0]+'#report-'+key;
      };
      tabs.forEach((tab,index)=>{
        tab.addEventListener('click',()=>activate(tab.dataset.reportTab));
        tab.addEventListener('keydown',event=>{
          const keys = ['ArrowLeft','ArrowRight','Home','End']; if (!keys.includes(event.key)) return;
          event.preventDefault();
          const target = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
          activate(tabs[target].dataset.reportTab,true);
        });
      });
      activate(location.hash.replace('#report-',''),false,false);
      window.addEventListener('hashchange',()=>activate(location.hash.replace('#report-',''),false,false));
      // Printing includes every metric, even while a panel is hidden on screen.
      let printState = null;
      window.addEventListener('beforeprint', () => {
        if (printState) return;
        printState = {
          panels: panels.map(panel => [panel, panel.hidden]),
          disclosures: [...document.querySelectorAll('.cg-reports details')].map(item => [item, item.open])
        };
        panels.forEach(panel => { panel.hidden = false; });
        printState.disclosures.forEach(([item]) => { item.open = true; });
      });
      window.addEventListener('afterprint', () => {
        if (!printState) return;
        printState.panels.forEach(([panel, hidden]) => { panel.hidden = hidden; });
        printState.disclosures.forEach(([item, open]) => { item.open = open; });
        printState = null;
      });
    }
    let secondaryPrintState = null;
    window.addEventListener('beforeprint', () => {
      if (secondaryPrintState) return;
      secondaryPrintState = [...document.querySelectorAll('details.cg-disclosure')]
        .filter(item => !item.closest('.cg-reports')).map(item => [item, item.open]);
      secondaryPrintState.forEach(([item]) => { item.open = true; });
    });
    window.addEventListener('afterprint', () => {
      secondaryPrintState?.forEach(([item, open]) => { item.open = open; });
      secondaryPrintState = null;
    });
    // Existing permission-checked contextual links become mobile drawer shortcuts.
    const context = document.querySelector('.workspace-module-nav-v75');
    const drawer = document.querySelector('[data-context-drawer]');
    if (context && drawer) {
      const label = document.createElement('span'); label.className = 'cg-drawer-label'; label.textContent = 'En este m\u00f3dulo'; drawer.append(label);
      context.querySelectorAll('a').forEach(link=>drawer.append(link.cloneNode(true)));
      drawer.hidden = !context.querySelector('a');
    }
    const menu = document.querySelector('.cg-context-menu');
    document.addEventListener('click',event=>{if(menu?.open && !menu.contains(event.target)) menu.open=false;});
    document.addEventListener('keydown',event=>{if(event.key==='Escape' && menu?.open){menu.open=false;menu.querySelector('summary').focus();}});
    const reveal = field => {
      let parent = field?.parentElement;
      while(parent){if(parent.tagName==='DETAILS') parent.open=true;parent=parent.parentElement;}
    };
    document.addEventListener('invalid',event=>reveal(event.target),true);
    if (document.querySelector('.flash-error,.flash-danger')) document.querySelectorAll('[data-open-on-errors]').forEach(d=>{d.open=true;});
    if (location.hash && !location.hash.startsWith('#report-')) { try {const target=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(target) reveal(target);} catch(_){} }
    // Optional type-specific inventory disclosures must not become empty headings.
    const kind = document.querySelector('[data-asset-kind-select]');
    const syncAssetDisclosures = () => {
      if (!kind) return;
      const vehicle = ['car','motorcycle'].includes(kind.value);
      document.querySelectorAll('.cg-disclosure-body > [data-vehicle-fields],.cg-disclosure-body > [data-product-fields]').forEach(group=>{
        const details = group.closest('.cg-disclosure');
        if (details) details.hidden = group.hasAttribute('data-vehicle-fields') ? !vehicle : vehicle;
      });
    };
    kind?.addEventListener('change',syncAssetDisclosures);syncAssetDisclosures();
  };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
