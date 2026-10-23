# -*- coding: utf-8 -*-
"""🛡️ 23/10/2026 — בדיקות רגרסיה לתיקוני ביקורת קודקס על האתר (F1 · F2 · F4 · F5 · F10 · F12 · F15).

הדף הבנוי נטען **כולו** בדפדפן מדומה (jsdom מתיקיית הבק אופיס), עם קבוצה אחת שהשם שלה עוין,
ובודקים את מה שהדפדפן באמת בונה — לא את המחרוזת בקוד.
שימוש:  python3 catalog/test_site_safety.py [index.html]
"""
import json, os, subprocess, sys, unittest, importlib.util, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith('.html') else os.path.join(HERE, 'index.html')
ORDER = os.path.join(os.path.dirname(PAGE), 'order.html')
JSDOM = os.path.join(HERE, '..', 'backoffice', 'app', 'node_modules', 'jsdom')

EVIL_NAME = 'X"><img src=x onerror="window.__pwn=1">\'q'
EVIL_COLOR = 'red" onmouseover="window.__pwn2=1'

JS = r"""
const fs=require('fs'); const {JSDOM}=require(process.argv[2]);
let html=fs.readFileSync(process.argv[1],'utf8');
const EVIL_NAME=process.argv[3], EVIL_COLOR=process.argv[4], mode=process.argv[5];
const gm=html.match(/const GROUPS = (\[.*?\]);\n/s); if(!gm)throw new Error('GROUPS not found');
const G=JSON.parse(gm[1]);
const g0=G.find(g=>!g._noimg&&g.variants.length>1)||G[0];
g0.name_he=EVIL_NAME; g0.variants[0].color=EVIL_COLOR; g0.variants[0].shade=EVIL_NAME;
html=html.replace(gm[0],()=>'const GROUPS = '+JSON.stringify(G).replace(/</g,'\\u003c')+';\n');
const opens=[];
const dom=new JSDOM(html,{runScripts:'dangerously',url:'https://beautyfavorites.co.il/',pretendToBeVisual:true,
  beforeParse(w){
    if(mode==='badfavs'){w.localStorage.setItem('sf_favs','{not json');}
    if(mode==='ar'){w.localStorage.setItem('sf_lang','ar');}
    w.matchMedia=w.matchMedia||(()=>({matches:false,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}));
    w.IntersectionObserver=w.IntersectionObserver||class{observe(){}unobserve(){}disconnect(){}};
    w.scrollTo=()=>{}; w.__alertWinClosed=[]; w.alert=()=>{const o=opens[opens.length-1];w.__alertWinClosed.push(!!(o&&o.closed));};
    // מסד מדומה: SB קיים (המסלול האמיתי), בלי רשת. createOrder מוחלף בבדיקה עצמה.
    const q={select(){return q;},range(){return Promise.resolve({data:[],error:null});},eq(){return q;},order(){return q;},limit(){return q;},then(r){return Promise.resolve({data:[],error:null}).then(r);}};
    w.supabase={createClient:()=>({from:()=>q,rpc:()=>Promise.resolve({data:[],error:null}),functions:{invoke:()=>Promise.resolve({data:null,error:'x'})}})};
    w.open=(u,t)=>{const fake={closed:false,location:{href:u||''},close(){this.closed=true;}};opens.push(fake);return fake;};
    w.__errors=[]; w.addEventListener('error',e=>w.__errors.push(String(e.message||e.error)));
  }});
const w=dom.window, d=w.document, E=s=>w.eval(s), T=s=>{try{return w.eval(s);}catch(e){return 'ERR:'+e.message;}};
const out={errors:w.__errors.slice(), cards:d.querySelectorAll('.card').length};
// F1 — שם עוין לא יוצר אלמנט ולא תכונה
out.pwnImg=d.querySelectorAll('img[src="x"]').length;
out.onerrorAttrs=[...d.querySelectorAll('[onerror]')].filter(e=>/__pwn/.test(e.getAttribute('onerror'))).length;
out.onmouseover=[...d.querySelectorAll('[onmouseover]')].length;
const cbox=d.createElement('div'); cbox.innerHTML=E(`cardHtml(GROUPS.find(g=>g.gid===${JSON.stringify(g0.gid)}))`);
out.cardImgX=cbox.querySelectorAll('img[src="x"]').length;
out.cardPwnAttr=[...cbox.querySelectorAll('*')].flatMap(e=>[...e.attributes].filter(x=>/__pwn/.test(x.value)&&!['aria-label','data-l','title'].includes(x.name)).map(x=>e.tagName+'.'+x.name)).length;
out.cardPwnNames=[...cbox.querySelectorAll('*')].flatMap(e=>[...e.attributes].filter(x=>/__pwn/.test(x.value)).map(x=>e.tagName+'.'+x.name));
const card=cbox.querySelector('#card-'+g0.gid);
out.cardFound=!!card; out.ariaOk=!!card&&card.getAttribute('aria-label')===EVIL_NAME+' — לפרטים';
const pill=E(`swPill(GROUPS.find(g=>g.gid===${JSON.stringify(g0.gid)}).variants[0],true,'')`);
const box=d.createElement('div'); box.innerHTML=pill; const b=box.firstElementChild;
out.pillOneEl=box.children.length===1&&!b.hasAttribute('onmouseover'); out.pillNoStyle=!(b.getAttribute('style')||'').includes('red');
out.pillTitleOk=b.getAttribute('title')===EVIL_NAME;
// F5 — אפס מוביל: אותו מפתח, והמסד מקבל את הברקוד שלו
out.nbcSame=T(`nbc('027131969808')===nbc('27131969808')`); out.nbcAlpha=T(`nbc('3600000428597spas')`);
T(`STOCK[nbc('27131969808')]=6; DBCODE[nbc('27131969808')]=rawbc('27131969808'); PRICE_CONS[nbc('27131969808')]=150; STOCK_READY=true;`);
out.soldWithZero=T(`isSold({barcode:'027131969808'})`);
T(`VMAP['__t']={g:{name_he:'t',brand:'b',variants:[]},v:{barcode:'027131969808',shade:''}}; CART['__t']={vid:'__t',name:'t',price:150,qty:2};`);
out.cartSku=T(`JSON.stringify(cartItems())`);
// סבב 2 — כמות בסל ≤ מלאי
T(`(function(){const g=GROUPS.find(x=>x.variants.length===1&&!x._noimg);window.__sg=g;const v=g.variants[0];
  STOCK[nbc(v.barcode)]=3;PRICE_CONS[nbc(v.barcode)]=100;DBCODE[nbc(v.barcode)]=rawbc(v.barcode);})()`);
const a0=w.__alertWinClosed.length;
T(`(function(){const id=__sg.variants[0].id;for(let i=0;i<4;i++)cartChange(id,1);})()`);
out.capQty=T(`CART[__sg.variants[0].id].qty`); out.capAlert=w.__alertWinClosed.length-a0;
T(`cartSetQty(__sg.variants[0].id,10)`); out.capSet=T(`CART[__sg.variants[0].id].qty`);
T(`delete CART[__sg.variants[0].id]`);
// סבב 2 — שם אנגלי לפי הגוון הנבחר
out.enGroups=T(`GROUPS.filter(g=>g.variants.length>1&&g.variants.some(v=>v.en&&v.en!==g.variants[0].en)).length`);
out.enFollows=T(`(function(){const g=GROUPS.find(g=>g.variants.length>1&&g.variants[1].en&&g.variants[1].en!==g.variants[0].en);
  sel[g.gid]=1;const b=document.createElement('div');b.innerHTML=cardHtml(g);delete sel[g.gid];
  const e=b.querySelector('.nm-en');return !!e&&e.textContent===g.variants[1].en;})()`);
// סבב 2 — imgErr מנסה שוב פעם אחת לפני placeholder
out.imgRetry=T(`(function(){const b=document.createElement('div');b.innerHTML='<img src="images/x/01.jpg" data-l="א">';const im=b.firstChild;
  imgErr(im);const first=im.style.display!=='none'&&!b.querySelector('.ph');imgErr(im);return first&&im.style.display==='none'&&!!b.querySelector('.ph');})()`);
// סבב 2 — תוויות נגישות לפי שפה
out.aria=T(`JSON.stringify({lang:LANG,he:[...document.querySelectorAll('[aria-label]')].map(e=>e.getAttribute('aria-label')).filter(x=>ARIA_AR[x]!=null).length,
  q:(document.getElementById('q')||{}).getAttribute&&document.getElementById('q').getAttribute('aria-label'),
  card:(function(){const b=document.createElement('div');b.innerHTML=cardHtml(GROUPS.find(g=>!g._noimg));return b.querySelector('.fav').getAttribute('aria-label');})()})`);
// F2 — הודעה: מחיר מהשרת כשהוא שונה
out.msgSame=E(`buildOrderText(77,300)`); out.msgDiff=E(`buildOrderText(77,999)`);
// F12 — החלון נפתח בלחיצה, הזמנה אחת לשני ניסיונות
E(`validateBuyer=function(){return true;}; window.__calls=0; createOrder=async function(){window.__calls++;await new Promise(r=>setTimeout(r,5));return {id:4242,total:300};};`);
(async()=>{
  const n0=opens.length; const p=E(`submitWhatsApp()`); out.openedSync=opens.length===n0+1; await p;
  out.firstHref=opens[n0]&&opens[n0].location.href;
  await E(`submitWhatsApp()`); out.calls=w.__calls; out.secondHref=opens[opens.length-1].location.href;
  out.opener=opens[opens.length-1].opener;
  const nm=d.getElementById('buyer-name'); out.hasName=!!nm; if(nm)nm.value='שם אחר לגמרי';
  await E(`submitWhatsApp()`); out.callsAfterEdit=w.__calls;
  E(`createOrder=async function(ch,onFail){if(onFail)onFail();alert('x');return null;}; sessionStorage.clear();`); const n1=opens.length;
  await E(`submitWhatsApp()`); out.failClosed=opens.length===n1+1&&opens[n1].closed; out.closedBeforeAlert=w.__alertWinClosed.slice(-1)[0]===true;
  out.errorsAfter=w.__errors.slice();
  console.log(JSON.stringify(out)); w.close(); process.exit(0);
})().catch(e=>{console.error(e);process.exit(1);});
"""


def run(page, mode=''):
    r = subprocess.run(['node', '-e', JS, page, JSDOM, EVIL_NAME, EVIL_COLOR, mode],
                       capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class SiteSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run(PAGE)

    def test_page_boots(self):
        self.assertGreater(self.r['cards'], 50, self.r)
        self.assertEqual(self.r['errors'], [])

    def test_F1_evil_name_creates_nothing(self):
        self.assertEqual(self.r['pwnImg'], 0)
        self.assertEqual(self.r['cardImgX'], 0)
        self.assertEqual(self.r['cardPwnAttr'], 0, self.r['cardPwnNames'])                     # שם עוין לא פותח תכונה חדשה בכרטיס
        self.assertEqual(self.r['onerrorAttrs'], 0)
        self.assertEqual(self.r['onmouseover'], 0)

    def test_F1_aria_label_holds_the_name(self):
        self.assertTrue(self.r['cardFound'])
        self.assertTrue(self.r['ariaOk'])

    def test_F1_shade_color_and_title(self):
        self.assertTrue(self.r['pillOneEl'])
        self.assertTrue(self.r['pillNoStyle'])
        self.assertTrue(self.r['pillTitleOk'])

    def test_F5_leading_zero(self):
        self.assertTrue(self.r['nbcSame'])
        self.assertEqual(self.r['nbcAlpha'], '3600000428597SPAS')
        self.assertFalse(self.r['soldWithZero'])                       # היה "אזל" עם מלאי 6
        self.assertEqual(json.loads(self.r['cartSku']), [{'sku': '27131969808', 'qty': 2}])

    def test_F2_message_uses_server_total(self):
        self.assertIn('= ₪300', self.r['msgSame'])
        self.assertNotIn('= ₪', self.r['msgDiff'])
        self.assertIn('₪999', self.r['msgDiff'])

    def test_F12_window_opens_in_click_and_no_duplicate(self):
        self.assertTrue(self.r['openedSync'])
        self.assertTrue(self.r['firstHref'].startswith('https://wa.me/972534555501?text='))
        self.assertIn('4242', urllib.request.unquote(self.r['firstHref']))
        self.assertEqual(self.r['calls'], 1)                            # ניסיון חוזר = אותה הזמנה
        self.assertIn('4242', urllib.request.unquote(self.r['secondHref']))
        self.assertTrue(self.r['failClosed'])                           # כשל → הלשונית הריקה נסגרת
        self.assertTrue(self.r['closedBeforeAlert'])                    # ...לפני הודעת השגיאה (אחרת היא קופצת מאחורי דף ריק)
        self.assertIsNone(self.r['opener'])                             # וואטסאפ לא מקבל קישור חזרה לדף
        self.assertTrue(self.r['hasName'])
        self.assertEqual(self.r['callsAfterEdit'], 2)                   # שם/כתובת השתנו → הזמנה חדשה, לא הישנה
        self.assertEqual(self.r['errorsAfter'], [])

    def test_F10_bad_favs_do_not_break_boot(self):
        r = run(PAGE, 'badfavs')
        self.assertEqual(r['errors'], [])
        self.assertGreater(r['cards'], 50)

    def test_R2_cart_capped_at_stock(self):
        self.assertEqual(self.r['capQty'], 3)                         # 4 לחיצות, מלאי 3
        self.assertEqual(self.r['capAlert'], 1)                       # הודעה אחת ללקוחה
        self.assertEqual(self.r['capSet'], 3)                         # הקלדת 10 → 3

    def test_R2_english_name_follows_shade(self):
        self.assertGreater(self.r['enGroups'], 20)
        self.assertTrue(self.r['enFollows'])

    def test_R2_image_retries_once(self):
        self.assertTrue(self.r['imgRetry'])

    def test_R2_aria_hebrew_in_hebrew_mode(self):
        a = json.loads(self.r['aria'])
        self.assertEqual(a['lang'], 'he')
        self.assertEqual(a['card'], 'הוסף למועדפים')

    def test_R2_aria_arabic_in_arabic_mode(self):
        a = json.loads(run(PAGE, 'ar')['aria'])
        self.assertEqual(a['lang'], 'ar')
        self.assertEqual(a['he'], 0, 'תווית נגישות בעברית במצב ערבית')
        self.assertEqual(a['q'], 'ابحث عن منتج أو ماركة أو باركود')
        self.assertEqual(a['card'], 'أضف إلى المفضلة')

    def test_F15_zoom_allowed(self):
        for f in (PAGE, ORDER):
            if os.path.exists(f):
                with open(f, encoding='utf-8') as fh: h = fh.read(3000)
                self.assertNotIn('maximum-scale', h, f)


class BuildFailsLoud(unittest.TestCase):
    """F4 — כשל בשליפה מהמסד עוצר את הבנייה (אלא אם --offline-preview)."""
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("bc_f4", os.path.join(HERE, "build_catalog.py"))
        cls.bc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.bc)

    def _no_net(self):
        import urllib.request as u
        orig = u.urlopen
        def boom(*a, **k): raise OSError("אין רשת (בדיקה)")
        u.urlopen = boom
        self.addCleanup(setattr, u, 'urlopen', orig)

    def test_categories_fail_loud(self):
        self._no_net(); self.bc.OFFLINE_PREVIEW = False
        with self.assertRaises(SystemExit):
            self.bc.fetch_categories()

    def test_content_fail_loud(self):
        self._no_net(); self.bc.OFFLINE_PREVIEW = False
        with self.assertRaises(SystemExit):
            self.bc.fetch_db_content()

    def test_offline_preview_allows(self):
        self._no_net(); self.bc.OFFLINE_PREVIEW = True
        self.addCleanup(setattr, self.bc, 'OFFLINE_PREVIEW', False)
        self.assertEqual(self.bc.fetch_categories(), [])
        self.assertEqual(self.bc.fetch_db_content(), {})


if __name__ == '__main__':
    print('נבדק:', PAGE)
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if not a.endswith('.html')], verbosity=1)
