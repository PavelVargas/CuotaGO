"""Render 16 real templates at phone/desktop sizes with synthetic data.
Run: python tests/ui80_layout_checks.py (Playwright + BeautifulSoup required).
External networks, OS notifications, and the production database are not used.
"""
from ui80_browser_utils import *

def main():
    results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=CHROMIUM,headless=True,args=['--no-sandbox'])
        for mode,width,height in [('mobile',390,844),('desktop',1440,960)]:
            context=browser.new_context(viewport={'width':width,'height':height},is_mobile=mode=='mobile',has_touch=mode=='mobile')
            for path in contexts:
                page=context.new_page(); errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                setup(page,mode=='mobile');load(page,path)
                dimensions=page.evaluate('''()=>({width:innerWidth,document:document.documentElement.scrollWidth,visibleInputs:[...document.querySelectorAll('main input:not([type=hidden]),main select,main textarea')].filter(e=>e.checkVisibility()).length})''')
                results.append({'mode':mode,'path':path,'errors':errors,**dimensions})
                page.screenshot(path=str(OUT/(mode+'-'+(path.strip('/').replace('/','-') or 'home')+'.png')),full_page=True)
                page.close()
            context.close()
        browser.close()
    (OUT/'layout-results.json').write_text(json.dumps(results,indent=2))
    failures=[item for item in results if item['errors'] or item['document']>item['width']]
    if failures:raise AssertionError(json.dumps(failures,indent=2))
    print(f'PASS: {len(results)} rendered views without page errors or horizontal document overflow')
if __name__=='__main__':main()
