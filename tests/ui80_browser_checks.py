"""Run: python tests/ui80_browser_checks.py (Playwright + BeautifulSoup required).
No live PostgreSQL, HTTP POST, or system push is used by these checks.
"""
from ui80_browser_utils import *
checks=[]
def check(condition,label):
 if not condition: raise AssertionError(label)
 checks.append(label);print(len(checks),label,flush=True)
def visible(page,selector):return page.locator(selector).first.is_visible()
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=CHROMIUM,headless=True,args=['--no-sandbox','--autoplay-policy=no-user-gesture-required'])
 for mobile in [True,False]:
  print('MODE',mobile,flush=True)
  page=b.new_page(viewport={'width':390 if mobile else 1440,'height':844 if mobile else 960},is_mobile=mobile,has_touch=mobile);errors=[];page.on('pageerror',lambda e:errors.append(str(e)));setup(page,mobile)
  load(page,'/purchases/new');n=page.locator('[data-purchase-next]')
  n.click();check(page.locator('#purchaseForm').get_attribute('data-purchase-current')=='1','invalid supplier blocked')
  page.locator('#purchaseSupplier').select_option('__new__');n.click();check(page.locator('#purchaseForm').get_attribute('data-purchase-current')=='1','invalid new supplier blocked')
  page.locator('[data-new-supplier-name]').fill('Proveedor <b>prueba</b>');n.click();check(visible(page,'[data-purchase-step="2"]'),'supplier forward step2')
  n.click();check(visible(page,'[data-purchase-step="2"]'),'invalid product blocked')
  page.locator('[data-purchase-asset]').first.select_option('1');page.locator('[data-purchase-qty]').first.fill('2');page.locator('[data-purchase-cost]').first.fill('12.35')
  page.locator('[data-add-purchase-item]').click();check(page.locator('[data-purchase-item]').count()==2,'can add row')
  page.locator('[data-purchase-asset]').nth(1).select_option('__new__');page.locator('[data-new-item-name]').nth(1).fill('Articulo <b>nuevo</b>');page.locator('[data-purchase-qty]').nth(1).fill('3');page.locator('[data-purchase-cost]').nth(1).fill('10.10')
  page.screenshot(path=str(OUT/('mobile-purchase-step2.png' if mobile else 'desktop-purchase-step2.png')),full_page=True)
  n.click();check(visible(page,'[data-purchase-step="3"]'),'review step');check(page.locator('[data-review-lines]>div').count()==2,'both review lines')
  check('55.00' in page.locator('[data-review-total]').text_content(),'correct decimal total');check(page.locator('[data-review-supplier] b').count()==0,'supplier escaped');check(page.locator('[data-review-lines] span b').count()==0,'item escaped')
  check(page.locator('[data-review-supplier]').text_content()=='Proveedor <b>prueba</b>','literal supplier preserved')
  data=page.locator('#purchaseForm').evaluate("f=>Object.fromEntries(['item_mode','item_asset_id','item_name','item_quantity','item_unit_cost','item_kind','item_notes'].map(k=>[k,new FormData(f).getAll(k)]))")
  check(all(len(v)==2 for v in data.values()),'repeated fields remain aligned');check(data['item_mode']==['existing','new'],'mixed mode alignment');check(data['item_quantity']==['2','3'],'quantities intact')
  page.screenshot(path=str(OUT/('mobile-purchase-review.png' if mobile else 'desktop-purchase-review.png')),full_page=True)
  page.locator('[data-purchase-back]').click();check(page.locator('[data-purchase-cost]').first.input_value()=='12.35','back preserves amounts')
  page.locator('[data-purchase-qty]').first.fill('0');n.click();check(visible(page,'[data-purchase-step="2"]'),'zero qty blocked')
  page.locator('[data-purchase-qty]').first.fill('1.5');n.click();check(visible(page,'[data-purchase-step="2"]'),'fraction qty blocked')
  page.locator('[data-purchase-qty]').first.fill('2');n.click()
  submitted=page.locator('#purchaseForm').evaluate("""f=>{let accepted=0;f.addEventListener('submit',e=>{if(!e.defaultPrevented)accepted++;e.preventDefault();});for(let i=0;i<20;i++)f.requestSubmit();return accepted;}""")
  check(submitted==1,'one submit for20 requests');check(page.locator('#purchaseSubmit').is_disabled(),'saving lock active')
  page.evaluate("window.dispatchEvent(new Event('pageshow'))");check(not page.locator('#purchaseSubmit').is_disabled(),'bfcache unlock')
  check(not errors,'purchase zero page errors')
  page.close()
  page=b.new_page(viewport={'width':390 if mobile else 1440,'height':844 if mobile else 960},is_mobile=mobile,has_touch=mobile);setup(page,mobile);load(page,'/reports')
  for key in ['summary','collections','results','inventory']:
   page.locator(f'[data-report-tab="{key}"]').click();check(page.locator('[data-report-view]:visible').count()==1,'one report view');check(visible(page,f'[data-report-view="{key}"]'),f'report {key}');check('#report-'+key in page.locator('.report-filters-v19').get_attribute('action'),'filter tab persists')
   page.screenshot(path=str(OUT/(('mobile-' if mobile else 'desktop-')+'report-'+key+'.png')),full_page=True)
   check(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'reports no page overflow')
  page.locator('[data-report-tab="inventory"]').press('Home');check(visible(page,'[data-report-view="summary"]'),'keyboard Home')
  page.locator('[data-report-tab="summary"]').press('ArrowRight');check(visible(page,'[data-report-view="collections"]'),'keyboard ArrowRight')
  page.evaluate("window.dispatchEvent(new Event('beforeprint'))");check(page.locator('[data-report-view]:visible').count()==4,'print all reports');check(page.locator('.cg-reports details:not([open])').count()==0,'print opens detail')
  page.evaluate("window.dispatchEvent(new Event('afterprint'))");check(page.locator('[data-report-view]:visible').count()==1,'print restores tab');check(visible(page,'[data-report-view="collections"]'),'print restores previous tab')
  if mobile:
   page.locator('#profileMenuTrigger').click();check(page.locator('#profileMenuDialog').is_visible(),'hamburger opens dialog');check(page.locator('[data-context-drawer] a:visible').count()>0,'context links in mobile drawer');page.keyboard.press('Escape');check(not visible(page,'#profileMenuDialog'),'escape closes mobile menu')
  else:
   page.locator('.cg-context-menu>summary').click();check(page.locator('.cg-context-menu[open]').count()==1,'desktop menu open');page.keyboard.press('Escape');check(page.locator('.cg-context-menu[open]').count()==0,'desktop menu escape')
  page.close()
 # Settings preview repeated calls against actual browser WebAudio.
 page=b.new_page(viewport={'width':390,'height':844},is_mobile=True);setup(page);load(page,'/settings')
 page.locator('details').filter(has=page.locator('[data-alert-sound-preview]')).last.locator(':scope>summary').click()
 out=page.evaluate("async()=>{let count=0;const AC=window.AudioContext;window.AudioContext=class extends AC{constructor(...a){super(...a);count++;}};const vals=await Promise.all(Array.from({length:40},()=>window.CuotaGoNotificationAudio.preview()));return {accepted:vals.filter(Boolean).length,contexts:count,disabled:document.querySelector('[data-alert-sound-preview]').disabled};}")
 check(out['accepted']==1,'browser rapid preview one accepted');check(out['contexts']<=1,'browser one WebAudio context');check(out['disabled'],'browser preview busy')
 page.wait_for_timeout(1700);check(not page.locator('[data-alert-sound-preview]').is_disabled(),'browser preview unlocks');page.screenshot(path=str(OUT/'mobile-sound-settings.png'),full_page=True)
 page.evaluate("document.documentElement.dataset.theme='dark'");page.screenshot(path=str(OUT/'mobile-settings-dark.png'),full_page=True);page.close()
 # Extra-small phone and tablet layout check; original fonts/fallback only, no network.
 for width in [320,360,768,1024]:
  for path in ['/','/reports','/contracts','/purchases/new','/assets/new','/settings']:
   page=b.new_page(viewport={'width':width,'height':667},is_mobile=width<720);setup(page,width<720);load(page,path)
   check(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'no overflow {width} {path}')
   if path=='/':
    page.evaluate('window.scrollTo(0,document.body.scrollHeight)');page.screenshot(path=str(OUT/f'home-{width}.png'),full_page=True)
   if path=='/assets/new':
    page.locator('[data-asset-kind-select]').select_option('phone');check(page.locator('[name="quantity_total"]').is_visible(),'stock visible for product');check(page.locator('[name="quantity_total"]').is_enabled(),'stock enabled for product')
    page.locator('[data-asset-kind-select]').select_option('car');check(not page.locator('[name="quantity_total"]').is_visible(),'stock hidden for individual car');check(page.locator('[name="quantity_total"]').is_disabled(),'stock excluded for car')
   page.close()
 b.close()
(OUT/'interactions.json').write_text(json.dumps(checks,indent=2))
print('PASS:',len(checks),'browser interaction checks')
