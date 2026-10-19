"""Render real local assets in a browser with synthetic fetch responses."""
import json,sys,re,base64,os,shutil
from pathlib import Path
from bs4 import BeautifulSoup
from types import SimpleNamespace as NS
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from ui80_browser_fixtures import env, contexts, common, route_map, ROOT
OUT=ROOT/'test-output'/'ui80';OUT.mkdir(parents=True,exist_ok=True)
def html_for(path):
 name,ct=contexts[path]
 ep=next((k for k,v in route_map.items() if v==path),'main.collections')
 vals=dict(common,**ct);vals['request']=NS(blueprint='main',endpoint=ep,method='GET',form={},args={})
 html=env.get_template(name).render(**vals)
 doc=BeautifulSoup(html,'html.parser')
 for link in list(doc.find_all('link')):
  href=link.get('href',''); f=ROOT/'cuotago'/urlparse(href).path.lstrip('/')
  if link.get('rel')==['stylesheet'] and href.startswith('/static/'):
   style=doc.new_tag('style');style.string=f.read_text();link.replace_with(style)
  else:link.decompose()
 for script in doc.find_all('script',src=True):
  src=script['src'];f=ROOT/'cuotago'/urlparse(src).path.lstrip('/')
  if src.startswith('/static/'):
   script.attrs={};script.string=f.read_text()
 for img in doc.find_all('img',src=True):
  src=img['src'];f=ROOT/'cuotago'/urlparse(src).path.lstrip('/')
  if src.startswith('/static/') and f.is_file():img['src']='data:image/png;base64,'+base64.b64encode(f.read_bytes()).decode()
 return str(doc)
def setup(page,mobile=True):
 page.set_default_timeout(6000)
 page.route('**/*',lambda route:route.abort())
 page.evaluate('''(mobile)=>{
 Object.defineProperty(navigator,'standalone',{get:()=>mobile,configurable:true});
 const store=new Map();Object.defineProperty(window,'localStorage',{value:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k)},configurable:true});
 window.fetch=async()=>({ok:true,json:async()=>({items:[],count:0,badgeCount:0,enabled:false,total:0,events:[],next_page:null})});
 }''',mobile)
def load(page,path):
 page.set_content(html_for(path),wait_until='domcontentloaded');page.wait_for_timeout(350)

CHROMIUM=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
