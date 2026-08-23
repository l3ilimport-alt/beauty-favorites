#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""דוגמת קטלוג ביוטי פייבוריטס — נאמנה לשפת העיצוב המלאה של קטלוג תום.

המקור: ה־CSS המלא של תום (חולץ מהדף החי, מתועד ב"שפת העיצוב של תום.md").
היסודות: לוקבוק צר שצף על אדמה כהה · רשימה עריכתית עם קווי שיער · הילת צבע
מאחורי כל מוצר חתוך · DM Serif למחירים · מיקרו־תוויות לטיניות בריווח קיצוני ·
פרנק רול ליברה כסריף העברי המקביל ל־Playfair (שאין לו עברית).

  python3 catalog/build_demo.py            בנייה מלאה
  python3 catalog/build_demo.py --fast     שימוש בתמונות שכבר נחתכו
"""
import base64
import collections
import glob
import html
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMGSRC = os.path.join(HERE, 'images')
CUT = os.path.join(HERE, '_דוגמה-תמונות')
MODES = os.path.join(CUT, '_מצב.json')
OUT = os.path.join(HERE, 'דוגמת קטלוג - ביוטי פייבוריטס.html')
IL = timezone(timedelta(hours=3))
FAST = '--fast' in sys.argv


def load(mod, path):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(ROOT, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PI = load('pi', 'תום ספק מיאמי/prepare_images.py')
CL = load('cl', 'תום ספק מיאמי/classify.py')
e = html.escape


CACHE_JSON = '/tmp/bf.json'


def products():
    """קריאה בלבד מהמסד — הדוגמה לא נוגעת בשום נתון.
    כשהמסד לא זמין נופלים למשיכה האחרונה שנשמרה, כדי שבנייה לא תיחסם."""
    r = subprocess.run(
        ['python3', os.path.join(ROOT, 'backoffice/db.py'), 'products',
         'select=sku,name_he,name_en,brand,category,main_category,stock,'
         'price_consumer,price_x3,image_url',
         'active=is.true', 'stock=gt.0', 'limit=1000'],
        capture_output=True, text=True, cwd=ROOT)
    try:
        rows = json.loads(r.stdout)
        io.open(CACHE_JSON, 'w', encoding='utf-8').write(r.stdout)
        return rows
    except Exception:
        print('⚠️ המסד לא זמין — משתמשים במשיכה השמורה האחרונה')
        return json.load(io.open(CACHE_JSON, encoding='utf-8'))


def policies():
    """שואב את טקסטי המדיניות מהאתר החי — מקור אחד לאמת, בלי לשכפל תוכן."""
    import re as _re
    h = io.open(os.path.join(HERE, 'index.html'), encoding='utf-8').read()
    m = _re.search(r'(POLICY|policies|POLICIES)\s*=\s*\{', h)
    if not m:
        return {}
    st = h.index('{', m.end() - 1)
    depth = 0
    for i in range(st, len(h)):
        if h[i] == '{':
            depth += 1
        elif h[i] == '}':
            depth -= 1
            if depth == 0:
                en = i + 1
                break
    blob = h[st:en]
    out = {}
    for k in _re.findall(r'\n?\s*(\w+)\s*:\s*`', blob):
        mm = _re.search(r'\b' + k + r'\s*:\s*`(.*?)`\s*(?:,|\n\}|\})', blob, _re.S)
        if mm:
            # התבניות באתר מזריקות משתנים; באתר החי PNOTE ריק, ולכן מנקים
            # כל הזרקה שנשארה במקום להציג אותה כטקסט גולמי.
            out[k] = _re.sub(r'\$\{[^}]*\}', '', mm.group(1))
    return out


def groups():
    """הקיבוץ לפי דגם וגוונים כבר קיים באתר החי — שואבים אותו במקום להמציא מחדש.
    מחזיר מפה מברקוד ל-(מזהה קבוצה, שם הגוון, צבע הגוון)."""
    h = io.open(os.path.join(HERE, 'index.html'), encoding='utf-8').read()
    i = h.index('const GROUPS = [')
    st = h.index('[', i)
    depth = 0
    for j in range(st, len(h)):
        if h[j] == '[':
            depth += 1
        elif h[j] == ']':
            depth -= 1
            if depth == 0:
                en = j + 1
                break
    G = json.loads(h[st:en])
    out = {}
    for gi, g in enumerate(G):
        for v in g['variants']:
            bc = re.sub(r'\D', '', str(v.get('barcode') or ''))
            if bc:
                out[bc] = (gi, v.get('shade') or '', v.get('color'), g)
    return out


def i18n_ar():
    """מילון הממשק בערבית כבר קיים באתר החי — שואבים ולא מתרגמים מחדש."""
    h = io.open(os.path.join(HERE, 'index.html'), encoding='utf-8').read()
    m = re.search(r'const\s+I18N\s*=|I18N\s*=\s*\{', h)
    if not m:
        return {}
    st = h.index('{', m.end() - 1)
    d = 0
    for j in range(st, len(h)):
        if h[j] == '{':
            d += 1
        elif h[j] == '}':
            d -= 1
            if d == 0:
                en = j + 1
                break
    blob = h[st:en]
    mm = re.search(r'\n\s*ar\s*:\s*\{', blob)
    if not mm:
        return {}
    st2 = blob.index('{', mm.end() - 1)
    d = 0
    for j in range(st2, len(blob)):
        if blob[j] == '{':
            d += 1
        elif blob[j] == '}':
            d -= 1
            if d == 0:
                en2 = j + 1
                break
    return dict(re.findall(r"(\w+)\s*:\s*'((?:[^'\\]|\\.)*)'", blob[st2:en2]))


def knowledge():
    """קבצי הידע הם הבעלים של רכיבים, אופן שימוש ומאפיינים (ראה CLAUDE.md).
    ממופה לפי ברקוד וגם לפי מזהה התיקייה, כי לא לכולם יש ברקוד."""
    out = {}
    for f in glob.glob(os.path.join(ROOT, 'knowledge', '*', 'product.json')):
        try:
            d = json.load(io.open(f, encoding='utf-8'))
        except Exception:
            continue
        rec = {k: d.get(k) for k in
               ('description', 'key_features', 'ingredients', 'usage', 'size',
                'official_url', 'name_en',
                'description_ar', 'features_ar', 'usage_ar')}
        bc = str(d.get('barcode') or '').strip()
        if bc:
            out[bc] = rec
        out['id:' + str(d.get('id'))] = rec
    return out


def local_image(url):
    m = re.search(r'/images/(.+)$', url or '')
    if not m:
        return None
    p = os.path.join(IMGSRC, m.group(1))
    if os.path.exists(p):
        return p
    folder = os.path.dirname(p)
    hits = sorted(glob.glob(os.path.join(folder, '01.*'))
                  or glob.glob(os.path.join(folder, '*.jpg'))
                  or glob.glob(os.path.join(folder, '*.png')))
    return hits[0] if hits else None


def cut_one(job):
    """מחזיר (מק"ט, מצב): "חיתוך" צף עם הילה, "לוח" מוצג במסגרת קרם כהה."""
    sku, src = job
    dst = os.path.join(CUT, f'{sku}.webp')
    if FAST and os.path.exists(dst) and os.path.getsize(dst) > 400:
        return None
    try:
        im = PI.fit(Image.open(src).convert('RGB'), 900)
    except Exception:
        return None
    mask = PI.cutout(im)
    if mask is None:
        PI.fit(im, 260).save(dst, 'WEBP', quality=80, method=6)
        return (sku, 'לוח')
    from PIL import ImageFilter
    mask = mask.filter(ImageFilter.GaussianBlur(1.0))
    over = Image.new('RGB', im.size, PI.CREAM)
    flat = Image.composite(im, over, mask.point(lambda v: 255 if v > 128 else 0))
    out = Image.merge('RGBA', (*flat.split(), mask))
    bb = mask.point(lambda v: 255 if v > 24 else 0).getbbox()
    if bb:
        out = out.crop(bb)
    out.thumbnail((260, 260), Image.LANCZOS)
    out.save(dst, 'WEBP', quality=80, method=6)
    return (sku, 'חיתוך')


def main():
    rows = products()
    os.makedirs(CUT, exist_ok=True)
    jobs = [(r['sku'], p) for r in rows if (p := local_image(r.get('image_url')))]
    print(f'מוצרים: {len(rows)} · עם תמונה מקומית: {len(jobs)}')
    done = {}
    if os.path.exists(MODES):
        done = json.load(io.open(MODES, encoding='utf-8'))
    with ThreadPoolExecutor(max_workers=6) as ex:
        done.update(x for x in ex.map(cut_one, jobs) if x)
    json.dump(done, io.open(MODES, 'w', encoding='utf-8'), ensure_ascii=False)
    ntile = sum(1 for v in done.values() if v == 'לוח')
    print(f'תמונות: {len(done)} · חיתוך {len(done)-ntile} · לוח {ntile}')

    kn = knowledge()
    print(f'קבצי ידע: {len(kn)}')
    for r in rows:
        m = re.search(r'/images/([^/]+)/', r.get('image_url') or '')
        r['kn'] = kn.get(str(r.get('sku') or '')) or (kn.get('id:' + m.group(1)) if m else None) or {}
        r['kind'] = CL.classify(f"{r.get('name_en') or ''} {r.get('category') or ''}",
                                r.get('name_he') or '', '', r.get('main_category') or '')
    kinds = collections.Counter(r['kind'] for r in rows)
    brands = collections.Counter(r['brand'] for r in rows if r.get('brand'))
    total_units = sum(r.get('stock') or 0 for r in rows)

    # ── קיבוץ לפי דגם: כל הגוונים של אותו מוצר בשורה אחת עם בורר ──
    GR = groups()
    print(f'מפת קיבוץ: {len(GR)} ברקודים')
    buckets = collections.OrderedDict()
    for r in rows:
        hit = GR.get(re.sub(r'\D', '', str(r['sku'])))
        key = f'g{hit[0]}' if hit else 'x' + str(r['sku'])
        r['shade'] = (hit[1] if hit else '') or ''
        r['color'] = hit[2] if hit else None
        buckets.setdefault(key, []).append(r)
    prods = []
    for key, vs in buckets.items():
        vs.sort(key=lambda x: x.get('shade') or '')
        head = vs[0]
        prods.append({'head': head, 'variants': vs})
    prods.sort(key=lambda p: ((p['head'].get('brand') or '').lower(),
                              p['head'].get('name_he') or ''))
    nmulti = sum(1 for p in prods if len(p['variants']) > 1)
    print(f'מוצרים אחרי קיבוץ: {len(prods)} · מתוכם רב-גווניים: {nmulti}')
    rows = [p['head'] for p in prods]

    cards = []
    for _pi, _p in enumerate(prods):
        r = _p['head']
        vlist = _p['variants']
        p = os.path.join(CUT, f"{r['sku']}.webp")
        img = ''
        if os.path.exists(p):
            img = ('data:image/webp;base64,'
                   + base64.b64encode(io.open(p, 'rb').read()).decode())
        cut = done.get(r['sku']) == 'חיתוך'
        st = r.get('stock') or 0
        pc = r.get('price_consumer') or 0
        pw = r.get('price_x3') or 0
        badge = ''
        if cut:
            frame = (f'<div class="imgframe cut"><div class="glow"></div>'
                     f'<img loading="lazy" src="{img}" alt=""></div>')
        elif img:
            frame = f'<div class="imgframe"><img loading="lazy" src="{img}" alt=""></div>'
        else:
            frame = '<div class="imgframe"><span class="ph">Beauty Favorites</span></div>'
        en = (r.get('name_en') or '').strip()
        # כשיש בורר גוונים, הכותרת היא שם הדגם — הגוון מוצג בבורר ולא בשם.
        title_he = r.get('name_he') or en
        title_en = en
        if len(vlist) > 1:
            title_he = re.sub(r'\s*\((?:גוון\s*)?[^)]{1,34}\)\s*$', '', title_he).strip()
            # השם האנגלי נגמר בגוון אחרי מקף, ולעיתים אחריו גם גודל אחרי פסיק —
            # חותכים את הזנב מהמקף האחרון ואילך.
            # נוסחת הזנב אינה אמינה כשהגוון במסד לא תואם בדיוק את השם. לכן
            # חותכים לפי המילים המשותפות לכל הגוונים בקבוצה — מה שנשאר זהה
            # בכולם הוא שם הדגם, וכל השאר הוא הגוון.
            ens = [(v.get('name_en') or '').strip() for v in vlist]
            ens = [x for x in ens if x]
            if len(ens) > 1:
                w0 = ens[0].split()
                keep = 0
                for i2 in range(len(w0)):
                    if all(len(x.split()) > i2 and x.split()[i2] == w0[i2] for x in ens):
                        keep = i2 + 1
                    else:
                        break
                if keep:
                    title_en = ' '.join(w0[:keep]).strip(' -–,')
                elif ens[0] == title_en:
                    # אין תחילית משותפת (השם נפתח בגוון) — נופלים לחיתוך במקף
                    title_en = title_en.split(' - ')[0].split(' – ')[0]
            # זנב שנשאר: הגוון יושב באמצע ואחריו גודל או תיאור
            title_en = re.sub(r'\s*[-–]\s.*$', '', title_en).strip(' -–,')
        k = r.get('kn') or {}
        det_ar = []
        if k.get('description_ar'):
            det_ar.append(f'<h4>الوصف</h4><p>{e(k["description_ar"])}</p>')
        if k.get('features_ar'):
            det_ar.append('<h4>ما يميّزه</h4><ul>'
                          + ''.join(f'<li>{e(str(x))}</li>' for x in k['features_ar']) + '</ul>')
        if k.get('usage_ar'):
            det_ar.append(f'<h4>طريقة الاستخدام</h4><p>{e(k["usage_ar"])}</p>')
        det = []
        if k.get('description'):
            det.append(f'<h4>תיאור</h4><p>{e(k["description"])}</p>')
        if k.get('key_features'):
            det.append('<h4>מה מייחד</h4><ul>'
                       + ''.join(f'<li>{e(str(x))}</li>' for x in k['key_features']) + '</ul>')
        if k.get('usage'):
            det.append(f'<h4>אופן שימוש</h4><p>{e(k["usage"])}</p>')
        if k.get('ingredients'):
            ing = str(k['ingredients']).strip()
            if len(ing) > 190:
                det.append(f'<h4>רכיבים</h4><p class="clip">{e(ing[:190])}'
                           f'<span class="rest" hidden>{e(ing[190:])}</span>'
                           f'<button class="rmore">…עוד</button></p>')
            else:
                det.append(f'<h4>רכיבים</h4><p>{e(ing)}</p>')
        meta = []
        if k.get('size'):
            meta.append(f'<span class="tag kind">{e(str(k["size"]))}</span>')
        meta.append(f'<span class="tag kind">{e(r["kind"])}</span>')
        if r.get('sku'):
            meta.append(f'<span class="barc">ברקוד {e(str(r["sku"]))}</span>')
        detail = ('<div class="detail" hidden><div class="dwrap">'
                  + f'<div class="dmeta">{"".join(meta)}</div>'
                  + '<div class="lhe">'
                  + (''.join(det) or '<p class="noinfo">אין עדיין פירוט למוצר זה</p>')
                  + '</div><div class="lar" hidden>'
                  + (''.join(det_ar) or '<p class="noinfo">لا يوجد وصف لهذا المنتج بعد</p>')
                  + '</div><button class="dclose">סגירה ✕</button></div></div>')
        sw = ''
        if len(vlist) > 1:
            chips = []
            for vi, v in enumerate(vlist):
                dot = (f'<i class="dot" style="background:{e(str(v["color"]))}"></i>'
                       if v.get('color') else '')
                lbl = e((v.get('shade') or '').strip() or f'גוון {vi + 1}')
                out = ' out' if (v.get('stock') or 0) <= 0 else ''
                vp = os.path.join(CUT, f"{v['sku']}.webp")
                vimg = ''
                if os.path.exists(vp):
                    vimg = ('data:image/webp;base64,'
                            + base64.b64encode(io.open(vp, 'rb').read()).decode())
                chips.append(
                    f'<button class="sw{" on" if vi == 0 else ""}{out}" data-i="{vi}" '
                    f'data-pc="{v.get("price_consumer") or 0}" data-pw="{v.get("price_x3") or 0}" '
                    f'data-st="{v.get("stock") or 0}" data-sku="{e(str(v["sku"]))}" '
                    f'data-img="{vimg}">{dot}{lbl}</button>')
            sw = ('<div class="shades"><div class="slbl">בחירת גוון · '
                  + str(len(vlist)) + '</div><div class="srow">'
                  + ''.join(chips) + '</div></div>')
        # "מומלץ" = מוצר עם כמה גוונים או מלאי בריא ממותג מוביל — סימן לביקוש
        _tot = sum((v.get('stock') or 0) for v in vlist)
        is_best = 1 if (len(vlist) >= 3 or _tot >= 12) else 0
        cards.append(f'''<article class="row" data-kind="{e(r['kind'])}" data-best="{is_best}"
 data-brand="{e(r.get('brand') or '')}" data-stock="{st}" data-pc="{pc}" data-pw="{pw}"
 data-nv="{len(vlist)}"
 data-name="{e(' '.join([(r.get('name_he') or ''), en, (r.get('brand') or '')] + [(v.get('shade') or '') for v in vlist]))}">
  {frame}
  <div class="info">
    <div class="rbrand">{e(r.get('brand') or '')}</div>
    <h3 class="rname"><span class="nhe">{e(title_he)}</span><span class="nar" hidden>{e(title_en or title_he)}</span></h3>
    {f'<div class="rvar">{e(title_en)}</div>' if title_en and r.get('name_he') else ''}
    {sw}
    <div class="prow">
      <div class="price"><b class="pv">{pc:,.0f}</b><span class="per"> ₪</span></div>
      <div class="pmeta"><div class="punits">In stock · {st}</div>{badge}
        <button class="add" data-sku="{e(r['sku'])}">+ לסל</button></div>
      <button class="fav" data-g="{_pi}" aria-label="מועדף">♥</button>
    </div>
  </div>
  {detail}
</article>''')

    kind_opts = ''.join(f'<option value="{e(k)}">{e(k)} · {v}</option>'
                        for k, v in kinds.most_common())
    brand_opts = ''.join(f'<option value="{e(b)}">{e(b)} · {v}</option>'
                         for b, v in sorted(brands.items()))
    POL_ORDER = [('about', 'אודות'), ('shipping', 'משלוחים'), ('returns', 'החזרות וביטולים'),
                 ('terms', 'תקנון'), ('privacy', 'פרטיות'),
                 ('accessibility', 'נגישות'), ('contact', 'צור קשר')]
    pol = policies()
    ARD = i18n_ar()
    ARD.setdefault('club', 'نادي الأعمال')
    ARD.setdefault('more', 'عرض المزيد')
    print(f'מפתחות בערבית: {len(ARD)}')
    pol_links = ''.join(
        f'<button class="plink" data-p="{k}">{e(t)}</button>'
        for k, t in POL_ORDER if pol.get(k))
    pol_sheets = ''.join(
        f'<section class="sheet" id="sheet-{k}" hidden>'
        f'<button class="sheet-x" data-close>סגירה ✕</button>'
        f'<div class="sheet-body">{pol[k]}</div></section>'
        for k, t in POL_ORDER if pol.get(k))
    print(f'עמודי מדיניות: {sum(1 for k,_ in POL_ORDER if pol.get(k))}')
    # רצועת מותגים עם הלוגו האמיתי — רק למותגים שיש להם קובץ לוגו ומלאי בפועל
    LOGOD = os.path.join(HERE, 'brand-logos')
    logo_files = {}
    if os.path.isdir(LOGOD):
        for f in os.listdir(LOGOD):
            stem = os.path.splitext(f)[0].lower()
            logo_files[stem] = f
    def slug(b):
        return re.sub(r'[^a-z0-9]+', '-', (b or '').lower()).strip('-')
    en_of = {}
    for _p in prods:
        b = _p['head'].get('brand')
        e_ = (_p['head'].get('name_en') or '').split()
        if b and b not in en_of and e_:
            en_of[b] = ' '.join(e_[:2])
    MIME = {'.svg': 'image/svg+xml', '.png': 'image/png',
            '.webp': 'image/webp', '.jpg': 'image/jpeg'}
    strip = []
    for b, cnt in brands.most_common():
        cand = [slug(b), slug(en_of.get(b, ''))]
        hit = next((logo_files[c] for c in cand if c in logo_files), None)
        if not hit:
            continue
        ext = os.path.splitext(hit)[1].lower()
        raw = io.open(os.path.join(LOGOD, hit), 'rb').read()
        if len(raw) > 90000:
            continue
        uri = ('data:' + MIME.get(ext, 'image/png') + ';base64,'
               + base64.b64encode(raw).decode())
        strip.append(f'<button class="blogo" data-b="{e(b)}" title="{e(b)} · {cnt}">'
                     f'<img src="{uri}" alt="{e(b)}"></button>')
    print(f'לוגואים ברצועה: {len(strip)}')
    stamp = datetime.now(IL).strftime('%d.%m.%Y')
    logo = ('data:image/png;base64,'
            + base64.b64encode(io.open(os.path.join(HERE, 'logo-bf.png'), 'rb').read()).decode())
    page = PAGE
    for k, v in (('@@CARDS@@', '\n'.join(cards)), ('@@KINDS@@', kind_opts),
                 ('@@BRANDS@@', brand_opts), ('@@N@@', f'{len(rows)}'),
                 ('@@NB@@', f'{len(brands)}'), ('@@NU@@', f'{total_units:,}'),
                 ('@@STAMP@@', stamp), ('@@LOGO@@', logo),
                 ('@@POLLINKS@@', pol_links), ('@@POLSHEETS@@', pol_sheets),
                 ('@@ARDICT@@', json.dumps(ARD, ensure_ascii=False)),
                 ('@@LOGOS@@', ''.join(strip))):
        page = page.replace(k, v)
    io.open(OUT, 'w', encoding='utf-8').write(page)
    mb = os.path.getsize(OUT) / 1024 / 1024
    print(f'✓ {OUT}')
    print(f'  {len(cards)} שורות · {mb:.2f} MB · {"נכנס" if mb < 15 else "גדול מדי"}')


PAGE = r'''<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ביוטי פייבוריטס — לוקבוק</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,700;0,800;1,400;1,500&family=DM+Serif+Display&family=Frank+Ruhl+Libre:wght@400;500;700;900&family=Inter:wght@400;500;600;700&family=Heebo:wght@400;500;600&display=swap">
<style>
/* שפת העיצוב של תום — לוק אחד מחויב, כל צבע מפורש */
:root{
  --bg:#F7F2EA; --surface:#FFFFFF; --image-bg:#F1EADF;
  --ink:#2A2420; --ink-soft:#6E6358; --accent:#8C5A38;
  --line:#E6DDD0; --line-strong:#B98E68; --muted:#A08A74;
  --serif:'Playfair Display','Frank Ruhl Libre',Georgia,serif;
  --serif-he:'Frank Ruhl Libre','Playfair Display',Georgia,serif;
  --sans:'Inter','Heebo',-apple-system,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:#E9E3D9;color:var(--ink);font-family:var(--sans);
font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased;padding:28px 0 60px}

/* ── הלוקבוק ── */
/* שני לקחים על אלמנט בגובה 150 אלף פיקסלים: overflow:hidden מעוגל וגם
   box-shadow יוצרים שכבת ענק שחורגת ממגבלת הטקסטורה של הדפדפן — וכל מה
   שמתחת ל~16K לא מצויר. לכן: בלי חיתוך ובלי צל על הלוקבוק עצמו; הצל יושב
   על שכבה קבועה בגובה המסך שמלווה את הגלילה. */
.device{width:100%;max-width:412px;margin:0 auto;background:var(--bg);
border-radius:30px;position:relative;z-index:1}
/* הצל יושב על שכבה קבועה ולא על הלוקבוק עצמו (ראה ההערה למעלה), אבל אז הוא
   נמתח לכל גובה החלון גם כשהדף קצר — לכן הוא מוסתר כשאין מה לגלול. */
.shadow-fx{position:fixed;top:28px;bottom:0;left:0;right:0;margin:0 auto;
width:100%;max-width:412px;border-radius:30px 30px 0 0;pointer-events:none;z-index:0;
box-shadow:0 24px 60px rgba(42,36,32,.22)}
.shadow-fx.off{display:none}
.topbar{border-radius:30px 30px 0 0}
footer{border-radius:0 0 30px 30px}
@media(min-width:768px){.device{max-width:560px;border-radius:36px}
.shadow-fx{max-width:560px;border-radius:36px 36px 0 0}
.topbar{border-radius:36px 36px 0 0}footer{border-radius:0 0 36px 36px}}

/* ── פס עליון דביק ── */
.topbar{position:sticky;top:0;z-index:20;background:rgba(247,242,234,.92);
backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
border-bottom:1px solid var(--line);text-align:center;padding:18px 20px 15px}
.eyebrow{font-size:11px;letter-spacing:.32em;color:var(--muted);
text-transform:uppercase;margin-bottom:7px}
.logo{height:58px;width:auto;display:block;margin:0 auto}
.lang{position:absolute;inset-inline-end:18px;top:16px;background:transparent;
border:1px solid var(--line);border-radius:40px;color:var(--muted);cursor:pointer;
font-family:var(--sans);font-size:10px;letter-spacing:.1em;padding:5px 12px;
transition:.15s}
.lang:hover{border-color:var(--line-strong);color:var(--accent)}
.topbar{position:sticky;top:0;z-index:20}
#wsOpen{color:var(--muted)}
#wsOpen.on{color:var(--accent);font-weight:600}
.lar,.lhe{display:block}
.lar[hidden],.lhe[hidden]{display:none!important}
html[dir="ltr"] .lar{direction:rtl}

/* ── פתיח ── */
.intro{padding:26px 24px 8px;text-align:center}
.lead{font-family:var(--serif-he);font-style:italic;font-size:17px;
color:var(--ink-soft);line-height:1.55;max-width:34ch;margin:0 auto 18px}
.terms{display:flex;justify-content:center;align-items:stretch;
border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:14px 0}
.term{flex:1;text-align:center;padding:0 6px}
.term+.term{border-inline-start:1px solid var(--line)}
.term-v.he{font-family:var(--serif-he)}
.term-v{font-family:var(--serif);font-weight:700;font-size:16px;
color:var(--ink);margin-bottom:4px;font-variant-numeric:tabular-nums}
.term-k{font-size:10px;letter-spacing:.16em;color:var(--muted);
text-transform:uppercase;line-height:1.3}

/* ── חיפוש וסינון דביקים ── */
.search{position:sticky;top:76px;z-index:15;background:rgba(247,242,234,.95);
backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
padding:14px 24px 12px;border-bottom:1px solid var(--line)}
.search-wrap{position:relative;display:flex;align-items:center}
.search-input{width:100%;background:var(--surface);border:1px solid var(--line-strong);
border-radius:40px;padding:11px 18px;font-family:var(--sans);font-size:13px;
color:var(--ink);letter-spacing:.02em;outline:none;
transition:border-color .15s ease, box-shadow .15s ease}
.search-input::placeholder{color:var(--muted);font-style:italic;letter-spacing:.04em}
.search-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(140,90,56,.12)}
.pills{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.pill{flex:1 1 128px;min-width:0;appearance:none;-webkit-appearance:none;
background:var(--surface) url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="8" height="5" viewBox="0 0 8 5"><path d="M0 0l4 5 4-5z" fill="%238C5A38"/></svg>') no-repeat left 14px center;
border:1px solid var(--line-strong);border-radius:40px;padding:9px 16px;
font-family:var(--sans);font-size:12px;color:var(--ink);cursor:pointer;outline:none;
text-overflow:ellipsis;white-space:nowrap;overflow:hidden;
transition:border-color .15s ease, box-shadow .15s ease}
.pill:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(140,90,56,.12)}
.mode{display:flex;background:var(--surface);border:1px solid var(--line-strong);
border-radius:40px;padding:3px;gap:2px;flex-shrink:0;justify-content:center}
.mode button{border:0;background:transparent;color:var(--ink-soft);border-radius:40px;
padding:6px 13px;font-family:var(--sans);font-size:11px;letter-spacing:.06em;
cursor:pointer;transition:.15s}
.mode button.on{background:var(--ink);color:var(--bg)}
.search-meta{margin-top:9px;text-align:center;font-size:10px;letter-spacing:.18em;
color:var(--muted);text-transform:uppercase}

/* ── כותרת מדור ── */
.section-head{padding:26px 24px 0;display:flex;align-items:baseline;gap:10px;
justify-content:space-between}
.section-head h2{font-family:var(--serif-he);font-weight:700;font-size:30px;
color:var(--ink);margin:0}
.count{font-size:9px;letter-spacing:.2em;color:var(--accent);text-transform:uppercase}
.rule{height:1px;background:var(--line-strong);margin:11px 24px 4px}

/* ── השורה העריכתית ── */
.row{width:100%;padding:18px 24px;border-bottom:1px solid var(--line);
display:flex;flex-direction:row;gap:14px;align-items:center;overflow:hidden;
content-visibility:auto;contain-intrinsic-size:auto 168px;
flex-wrap:wrap;cursor:pointer;transition:background .15s}
.row:hover{background:rgba(140,90,56,.035)}
.row.open{background:rgba(140,90,56,.05)}

/* ── מגירת המוצר ── */
.detail{flex:1 1 100%;width:100%}
.detail[hidden]{display:none!important}
.dwrap{border-top:1px solid var(--line-strong);margin-top:14px;padding-top:14px}
.dmeta{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-bottom:12px}
.detail h4{font-family:var(--serif-he);font-weight:700;font-size:13px;color:var(--accent);
margin:14px 0 5px;letter-spacing:.01em}
.detail h4:first-of-type{margin-top:0}
.detail p{font-size:13px;line-height:1.75;color:var(--ink-soft);margin:0}
.detail ul{margin:0;padding-inline-start:17px}
.detail li{font-size:13px;line-height:1.7;color:var(--ink-soft)}
.noinfo{font-family:var(--serif-he);font-style:italic;color:var(--muted)}
.rmore{background:transparent;border:0;color:var(--accent);cursor:pointer;
font-family:var(--sans);font-size:11.5px;padding:0 4px}
.rmore:hover{text-decoration:underline}
.nhe[hidden],.nar[hidden],.rest[hidden]{display:none}
.barc{font-size:10px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;
direction:ltr}
.dclose{display:block;margin:16px 0 0 auto;background:transparent;
border:1px solid var(--line-strong);border-radius:40px;color:var(--ink-soft);
font-family:var(--sans);font-size:10px;letter-spacing:.14em;text-transform:uppercase;
padding:6px 15px;cursor:pointer}
.dclose:hover{border-color:var(--accent);color:var(--accent)}
.chev{position:absolute;inset-inline-start:24px;bottom:14px;color:var(--muted);
font-size:10px;letter-spacing:.12em;text-transform:uppercase;pointer-events:none}
.imgframe{background:var(--image-bg);border:1px solid var(--line);border-radius:3px;
width:clamp(96px,28%,140px);aspect-ratio:1/1;flex-shrink:0;
display:flex;align-items:center;justify-content:center;overflow:hidden}
.imgframe img{width:100%;height:100%;object-fit:contain}
.imgframe.cut{background:none;border:none;overflow:visible;position:relative;border-radius:0}
.imgframe.cut .glow{position:absolute;inset:-24%;pointer-events:none;
background-size:contain;background-repeat:no-repeat;background-position:center;
filter:blur(24px) saturate(1.5);transform:scale(1.3);opacity:.5;
-webkit-mask-image:radial-gradient(closest-side,black 30%,transparent 92%);
mask-image:radial-gradient(closest-side,black 30%,transparent 92%)}
.imgframe.cut img{position:relative;z-index:1;
filter:drop-shadow(0 8px 14px rgba(36,31,25,.22))}
.ph{font-family:var(--serif);font-style:italic;font-size:11px;color:var(--muted);
text-align:center;padding:6px}
.info{flex:1;min-width:0;display:flex;flex-direction:column}
.rbrand{font-size:clamp(11px,3vw,13px);letter-spacing:.18em;color:var(--accent);
text-transform:uppercase;margin-bottom:6px;overflow-wrap:anywhere}
.rname{font-family:var(--serif-he);font-weight:700;margin:0;
font-size:clamp(15px,4.2vw,19px);line-height:1.3;color:var(--ink);overflow-wrap:anywhere}
.rvar{font-family:var(--serif);font-style:italic;font-size:clamp(11px,3vw,13px);
color:var(--ink-soft);margin-top:4px;overflow-wrap:anywhere;direction:ltr;text-align:right}
/* ── בורר הגוונים ── */
.shades{width:100%;margin-top:9px}
.slbl{font-size:9.5px;letter-spacing:.16em;color:var(--muted);text-transform:uppercase;
margin-bottom:6px}
.srow{display:flex;flex-wrap:wrap;gap:5px}
.sw{display:inline-flex;align-items:center;gap:5px;background:var(--surface);
border:1px solid var(--line);border-radius:40px;padding:4px 10px;cursor:pointer;
font-family:var(--sans);font-size:10.5px;color:var(--ink-soft);transition:.14s;
max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sw:hover{border-color:var(--line-strong)}
.sw.on{border-color:var(--accent);color:var(--accent);background:rgba(140,90,56,.07);
font-weight:600}
.sw.out{opacity:.42}
.sw .dot{width:11px;height:11px;border-radius:50%;flex-shrink:0;
border:1px solid rgba(42,36,32,.2)}
.nv{font-size:9.5px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;
margin-top:4px}

.prow{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;
width:100%;margin-top:auto;padding-top:10px}
.price{font-family:'DM Serif Display',Georgia,serif;
font-size:clamp(26px,7vw,33px);color:var(--ink);line-height:1.15;flex-shrink:0;
font-variant-numeric:tabular-nums;direction:ltr}
.price .per{font-family:var(--sans);font-size:clamp(12px,3.2vw,15px);
color:var(--ink-soft);font-weight:600}
.pmeta{text-align:left;line-height:1.5;min-width:0}
.punits{font-size:clamp(10px,2.8vw,11.5px);letter-spacing:.08em;color:var(--muted);
text-transform:uppercase;direction:ltr;white-space:nowrap}
.badge{display:inline-block;font-size:9px;letter-spacing:.14em;color:var(--accent);
text-transform:uppercase;border:1px solid var(--line-strong);border-radius:40px;
padding:3px 10px;margin-top:6px}
.badge.hot{color:#8F2F1C;border-color:#C99A8C}
.add{display:inline-block;margin-top:7px;background:transparent;color:var(--accent);
border:1px solid var(--line-strong);border-radius:40px;padding:4px 12px;
font-family:var(--sans);font-size:10px;font-weight:600;letter-spacing:.1em;
cursor:pointer;transition:.15s}
.add:hover{background:rgba(140,90,56,.08)}
.add.on{background:var(--accent);border-color:var(--accent);color:#F7F2EA}
.empty{padding:60px 24px;text-align:center;font-family:var(--serif-he);
font-style:italic;color:var(--ink-soft)}
.more{display:block;margin:22px auto 6px;background:transparent;color:var(--accent);
border:1px solid var(--line-strong);border-radius:40px;padding:11px 30px;
font-family:var(--sans);font-size:11px;font-weight:600;letter-spacing:.16em;
text-transform:uppercase;cursor:pointer;transition:.15s}
.more:hover{background:rgba(140,90,56,.08)}

/* ── כפתור דביק ותחתית ── */
.inquire{position:sticky;bottom:16px;display:block;width:max-content;max-width:calc(100% - 48px);
margin:14px auto 0;background:var(--ink);color:#F7F2EA;border:none;border-radius:40px;
padding:11px 26px;text-align:center;cursor:pointer;font-family:var(--sans);font-size:10.5px;
font-weight:600;letter-spacing:.14em;text-transform:uppercase;text-decoration:none;
box-shadow:0 8px 20px rgba(42,36,32,.26);z-index:30}
/* ── רצועת מותגים ── */
.brandstrip{display:flex;gap:9px;overflow-x:auto;padding:11px 2px 9px;margin-top:9px;
scrollbar-width:none;-webkit-overflow-scrolling:touch}
.brandstrip::-webkit-scrollbar{display:none}
.blogo{flex:0 0 auto;background:var(--surface);border:1px solid var(--line);
border-radius:11px;width:66px;height:40px;display:flex;align-items:center;
justify-content:center;cursor:pointer;padding:6px 8px;transition:.15s}
.blogo:hover{border-color:var(--line-strong)}
.blogo.on{border-color:var(--accent);box-shadow:0 0 0 2px rgba(140,90,56,.13)}
.blogo img{max-width:100%;max-height:100%;object-fit:contain;
filter:grayscale(1) opacity(.62);transition:filter .15s}
.blogo:hover img,.blogo.on img{filter:none}

/* ── צ'יפים מהירים ── */
.qchips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;justify-content:center}
.qc{background:var(--surface);border:1px solid var(--line);border-radius:40px;
padding:6px 14px;font-family:var(--sans);font-size:11px;color:var(--ink-soft);
cursor:pointer;transition:.15s;display:inline-flex;align-items:center;gap:5px}
.qc:hover{border-color:var(--line-strong)}
.qc.on{background:var(--ink);border-color:var(--ink);color:var(--bg)}
.qc i{font-style:normal;font-size:10px;opacity:.7}
.qc.clr{border-style:dashed;color:var(--muted)}
.qc.clr:hover{color:var(--accent);border-color:var(--line-strong)}
.qc.clr.on{background:transparent;border-color:var(--line);color:var(--muted)}

/* ── מועדפים ── */
.fav{position:absolute;inset-inline-start:20px;top:16px;background:transparent;border:0;
color:var(--line-strong);font-size:17px;cursor:pointer;line-height:1;padding:4px;
transition:transform .14s,color .14s}
.fav:hover{transform:scale(1.16)}
.fav.on{color:#c2607a}
.row{position:relative}

/* ── כניסת סיטונאי ── */
.wsov{position:fixed;inset:0;z-index:60;background:rgba(42,36,32,.42);
backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;padding:22px}
.wsov[hidden]{display:none!important}
.wssheet{background:var(--bg);border:1px solid var(--line-strong);border-radius:20px;
padding:26px 24px;max-width:340px;width:100%;box-shadow:0 20px 50px rgba(42,36,32,.3)}
.wssheet h3{font-family:var(--serif-he);font-weight:700;font-size:21px;margin:0 0 6px;
color:var(--ink);text-align:center}
.wsp{font-size:12.5px;color:var(--ink-soft);text-align:center;margin:0 0 16px;
font-family:var(--serif-he);font-style:italic}
.wsmsg{font-size:12px;text-align:center;min-height:18px;margin-top:8px;color:#8F2F1C}
.wsmsg.ok{color:#3f6033}
.wsgo{width:100%;margin-top:8px;background:var(--ink);color:var(--bg);border:0;
border-radius:40px;padding:12px;font-family:var(--sans);font-size:11px;font-weight:600;
letter-spacing:.16em;text-transform:uppercase;cursor:pointer}

.plinks{display:flex;flex-wrap:wrap;justify-content:center;gap:0;
padding:22px 24px 4px;border-top:1px solid var(--line);margin-top:20px}
.plink{background:transparent;border:0;color:var(--muted);cursor:pointer;
font-family:var(--sans);font-size:10px;letter-spacing:.16em;text-transform:uppercase;
padding:6px 12px;position:relative;transition:color .15s}
.plink+.plink::before{content:'';position:absolute;inset-inline-start:0;top:8px;bottom:8px;
width:1px;background:var(--line)}
.plink:hover{color:var(--accent)}
.sheet{padding:8px 24px 24px}
.sheet-x{display:block;margin:0 0 14px auto;background:transparent;border:1px solid var(--line-strong);
border-radius:40px;color:var(--ink-soft);font-family:var(--sans);font-size:10px;
letter-spacing:.14em;text-transform:uppercase;padding:6px 14px;cursor:pointer}
.sheet-x:hover{border-color:var(--accent);color:var(--accent)}
.sheet-body{border-top:1px solid var(--line-strong);padding-top:16px}
.sheet-body h2{font-family:var(--serif-he);font-weight:700;font-size:24px;
color:var(--ink);margin:0 0 12px}
.sheet-body h3{font-family:var(--serif-he);font-weight:700;font-size:15px;
color:var(--accent);margin:18px 0 6px}
.sheet-body p,.sheet-body li{font-size:13.5px;line-height:1.75;color:var(--ink-soft);margin:0 0 9px}
.sheet-body ul{padding-inline-start:18px;margin:0 0 10px}
.sheet-body a{color:var(--accent)}
.sheet-body b{color:var(--ink)}
.sheet[hidden]{display:none!important}
footer{padding:26px 24px 30px;border-top:1px solid var(--line);text-align:center;margin-top:6px}
.fm{font-size:8.5px;letter-spacing:.2em;color:var(--muted);
text-transform:uppercase;line-height:2}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>

<div class="shadow-fx"></div>
<div class="device">
  <header class="topbar">
    <button class="lang" id="lang" data-l="he">العربية</button>
    <div class="eyebrow">Original Beauty · Israel</div>
    <img class="logo" src="@@LOGO@@" alt="Beauty Favorites">
  </header>

  <section class="intro">
    <p class="lead">מוצרי היופי המקוריים, מהמלאי שעל המדף. עברו בקטלוג, ואנחנו כבר נדאג לכל השאר.</p>
    <div class="terms">
      <div class="term"><div class="term-v">@@N@@</div><div class="term-k">Products<br>In Stock</div></div>
      <div class="term"><div class="term-v">100%</div><div class="term-k">Original<br>Guaranteed</div></div>
      <div class="term"><div class="term-v he">משלוח</div><div class="term-k">Door To Door<br>Delivery</div></div>
    </div>
  </section>

  <div class="search">
    <div class="search-wrap">
      <input type="search" id="q" class="search-input" placeholder="חיפוש מוצר, מותג…">
    </div>
    <div class="pills">
      <select id="kind" class="pill"><option value="">כל הסוגים</option>@@KINDS@@</select>
      <select id="brand" class="pill"><option value="">כל המותגים</option>@@BRANDS@@</select>
      <select id="price" class="pill">
        <option value="">כל המחירים</option>
        <option value="0-50">עד ₪50</option>
        <option value="50-100">₪50–100</option>
        <option value="100-200">₪100–200</option>
        <option value="200-99999">₪200+</option>
      </select>
      <select id="sort" class="pill">
        <option value="brand">מיון: מומלץ</option>
        <option value="price_a">מחיר — עולה</option>
        <option value="price_d">מחיר — יורד</option>
        <option value="stock">מלאי נמוך קודם</option>
      </select>

    </div>
    <div class="brandstrip" id="bstrip">@@LOGOS@@</div>
    <div class="qchips">
      <button class="qc on" data-f="">הכול</button>
      <button class="qc" data-f="best">✦ מומלצים</button>
      <button class="qc" data-f="fav">♥ מועדפים <i id="favN">0</i></button>
      <button class="qc clr" id="clear">ניקוי הסינון</button>
    </div>
    <div class="search-meta" id="meta">Showing @@N@@ Items</div>
  </div>

  <div class="section-head"><h2>הקטלוג</h2><span class="count" id="count">@@N@@ Items</span></div>
  <div class="rule"></div>

  <main id="list">
@@CARDS@@
  </main>
  <div class="empty" id="empty" hidden>לא נמצאו פריטים — נסו חיפוש אחר</div>
  <button class="more" id="more" hidden>הצגת עוד מוצרים</button>

  <a class="inquire" id="order" href="https://wa.me/972534555501" target="_blank" rel="noreferrer">להזמנה בוואטסאפ</a>

  <div class="wsov" id="wsOv" hidden>
    <div class="wssheet">
      <button class="sheet-x" id="wsX">סגירה ✕</button>
      <h3>כניסת סיטונאי</h3>
      <p class="wsp">הזן קוד סיטונאי כדי לראות מחירי סיטונאי.</p>
      <input class="search-input" id="wsCode" type="text" placeholder="קוד סיטונאי" autocomplete="off">
      <div class="wsmsg" id="wsMsg"></div>
      <button class="wsgo" id="wsGo">כניסה</button>
    </div>
  </div>

  <nav class="plinks">@@POLLINKS@@<button class="plink" id="wsOpen">מועדון עסקים</button></nav>
@@POLSHEETS@@
  <footer>
    <div class="fm">BEAUTYFAVORITES.CO.IL</div>
    <div class="fm">ORDERS · 053-4555501 · BEAUTYFAVORITES2026@GMAIL.COM</div>
    <div class="fm">דוגמת עיצוב · @@STAMP@@</div>
  </footer>
</div>

<script>
(function(){
  var $=function(i){return document.getElementById(i)};
  var rows=[].slice.call(document.querySelectorAll('#list .row'));
  var MODE='pc';

  // ההילה: אותה תמונה בדיוק, מטושטשת מאחור — בלי להכפיל את משקל הקובץ
  rows.forEach(function(r){
    var g=r.querySelector('.glow'), im=r.querySelector('img');
    if(g&&im) g.style.backgroundImage='url("'+im.src+'")';
  });

  function apply(){
    var q=$('q').value.trim().toLowerCase(), k=$('kind').value,
        pr=$('price').value, b=$('brand').value;
    var n=0, units=0, val=0;
    rows.forEach(function(r){
      var d=r.dataset, ok=true;
      if(k && d.kind!==k) ok=false;
      if(b && d.brand!==b) ok=false;
      if(pr){ var lim=pr.split('-'), pv=+d[MODE];
        if(!(pv>=+lim[0] && pv<+lim[1])) ok=false; }
      if(q && d.name.toLowerCase().indexOf(q)<0) ok=false;
      if(QF==='best' && d.best!=='1') ok=false;
      if(QF==='fav'  && !FAVS[r.querySelector('.fav').dataset.g]) ok=false;
      r.style.display=ok?'':'none';
      if(ok){n++; units+=+d.stock; val+=(+d.stock)*(+d[MODE]);}
    });
    var vis=rows.filter(function(r){return r.style.display!=='none'});
    var so=$('sort').value;
    vis.sort(function(a,b){
      var x=a.dataset,y=b.dataset;
      if(so==='price_a') return (+x[MODE])-(+y[MODE]);
      if(so==='price_d') return (+y[MODE])-(+x[MODE]);
      if(so==='stock') return (+x.stock)-(+y.stock);
      return x.brand.localeCompare(y.brand,'he');
    });
    var list=document.getElementById('list');
    vis.forEach(function(r){list.appendChild(r)});
    // הצגה מדורגת: 726 שורות בבת אחת יוצרות אלמנט של ~150 אלף פיקסלים,
    // שחורג ממגבלת הציור של הדפדפן וכל מה שמתחת פשוט לא מצויר.
    SHOWN = Math.min(SHOWN, Math.max(PAGE, vis.length));
    vis.forEach(function(r,i){ if(i>=SHOWN) r.style.display='none'; });
    var m=$('more');
    m.hidden = vis.length<=SHOWN;
    m.textContent='הצגת עוד '+Math.min(PAGE, vis.length-SHOWN)+' מוצרים';
    $('count').textContent=n+' Items';
    $('meta').textContent='Showing '+n+' · '+units.toLocaleString('en')+' Units · ₪'+Math.round(val).toLocaleString('en');
    $('empty').hidden=n>0;
  }
  function repaint(){
    rows.forEach(function(r){
      r.querySelector('.pv').textContent=(+r.dataset[MODE]).toLocaleString('he-IL');
    });
  }
  ['q','kind','price','brand','sort'].forEach(function(i){
    var reset=function(){ SHOWN=PAGE; apply(); };
    $(i).addEventListener('input',reset); $(i).addEventListener('change',reset);
  });

  // ── סל ההזמנה ──
  var PAGE=60, SHOWN=PAGE, QF='', WS_OK=false;
  var FAVS={};
  try{ FAVS=JSON.parse(localStorage.getItem('bf_favs')||'{}'); }catch(e){ FAVS={}; }
  function saveFavs(){ try{localStorage.setItem('bf_favs',JSON.stringify(FAVS));}catch(e){} }
  function favCount(){ return Object.keys(FAVS).length; }

  $('more').addEventListener('click',function(){ SHOWN+=PAGE; apply(); });
  var CART={};
  function refreshOrder(){
    var n=Object.keys(CART).length, el=$('order');
    if(!n){ el.textContent='להזמנה בוואטסאפ';
      el.href='https://wa.me/972534555501'; return; }
    var lines=['היי! אשמח להזמין מביוטי פייבוריטס:',''], total=0;
    Object.keys(CART).forEach(function(k){
      var c=CART[k]; total+=c.p;
      lines.push('· '+c.n+' — '+c.p.toLocaleString('he-IL')+' ש"ח');
    });
    lines.push(''); lines.push('סה"כ: '+total.toLocaleString('he-IL')+' ש"ח');
    el.textContent='להזמנה בוואטסאפ · '+n+' פריטים · ₪'+total.toLocaleString('he-IL');
    el.href='https://wa.me/972534555501?text='+encodeURIComponent(lines.join('\n'));
  }
  [].forEach.call(document.querySelectorAll('.add'),function(b){
    b.addEventListener('click',function(){
      var row=b.closest('.row'), sku=b.dataset.sku;
      if(CART[sku]){ delete CART[sku]; b.classList.remove('on'); b.textContent='+ לסל'; }
      else{
        // שם המוצר במסד כבר כולל את המותג — אין לשכפל אותו בהודעה
        var name=row.querySelector('.rname').textContent;
        CART[sku]={n:name, p:+row.dataset[MODE]};
        b.classList.add('on'); b.textContent='✓ בסל';
      }
      refreshOrder();
    });
  });

  // ── החלפת שפה: עברית / ערבית ──
  // מילון הממשק והתיאורים בערבית נשאבים מהאתר החי ומקבצי הידע — לא מתורגמים כאן.
  var AR = @@ARDICT@@;
  var TXT = [
    ['#q',            'placeholder', 'search_ph'],
    ['.qc[data-f=""]','text',        'all'],
    ['#clear',        'text',        'reset_all'],
    ['#wsOpen',       'text',        'club'],
    ['#more',         'text',        'more'],
    ['#empty',        'text',        'empty'],
  ];
  var HE = {};
  function snapHe(){
    TXT.forEach(function(t){
      var el=document.querySelector(t[0]); if(!el) return;
      HE[t[0]] = t[1]==='placeholder' ? el.placeholder : el.textContent;
    });
    var so=$('sort');
    if(so) for(var i=0;i<so.options.length;i++) HE['opt'+i]=so.options[i].textContent;
    var pk=$('price');
    if(pk) for(var j=0;j<pk.options.length;j++) HE['pop'+j]=pk.options[j].textContent;
  }
  snapHe();
  var LANG='he';
  function setLang(l){
    LANG=l;
    var ar = l==='ar';
    document.documentElement.lang = ar?'ar':'he';
    TXT.forEach(function(t){
      var el=document.querySelector(t[0]); if(!el) return;
      var v = ar ? (AR[t[2]]||HE[t[0]]) : HE[t[0]];
      if(t[1]==='placeholder') el.placeholder=v; else el.textContent=v;
    });
    // תיאורי המוצר
    [].forEach.call(document.querySelectorAll('.lhe'),function(x){x.hidden=ar});
    [].forEach.call(document.querySelectorAll('.lar'),function(x){x.hidden=!ar});
    // שם המוצר: אין תרגום לערבית בנתונים, ולכן במצב ערבי מוצג השם האנגלי —
    // קריא לדובר ערבית ותואם את מה שכתוב על האריזה.
    [].forEach.call(document.querySelectorAll('.nhe'),function(x){x.hidden=ar});
    [].forEach.call(document.querySelectorAll('.nar'),function(x){x.hidden=!ar});
    [].forEach.call(document.querySelectorAll('.rvar'),function(x){x.hidden=ar});
    $('lang').textContent = ar ? 'עברית' : 'العربية';
    // תוויות הבוררים — משחזרים מהעברית השמורה ולא רק דורסים בערבית
    var so=$('sort');
    if(so){
      var k=['sort_default','sort_pa','sort_pd','sort_name'];
      for(var i=0;i<so.options.length && i<4;i++){
        so.options[i].textContent = ar ? (AR[k[i]]||HE['opt'+i]) : HE['opt'+i];
      }
    }
    var pk=$('price');
    if(pk){
      var pkk=['all_prices','p_u50','p_50_100','p_100_200','p_200p'];
      for(var j=0;j<pk.options.length && j<5;j++){
        pk.options[j].textContent = ar ? (AR[pkk[j]]||HE['pop'+j]) : HE['pop'+j];
      }
    }
    apply();
  }
  $('lang').addEventListener('click',function(){ setLang(LANG==='he'?'ar':'he'); });

  // ── מועדפים ──
  rows.forEach(function(r){
    var b=r.querySelector('.fav');
    if(!b) return;
    if(FAVS[b.dataset.g]) b.classList.add('on');
    b.addEventListener('click',function(ev){
      ev.stopPropagation();
      if(FAVS[b.dataset.g]){ delete FAVS[b.dataset.g]; b.classList.remove('on'); }
      else { FAVS[b.dataset.g]=1; b.classList.add('on'); }
      saveFavs(); $('favN').textContent=favCount();
      if(QF==='fav') apply();
    });
  });
  $('favN').textContent=favCount();

  $('clear').addEventListener('click',function(){
    MACRO=''; QF=''; SHOWN=PAGE;
    $('q').value=''; $('kind').value=''; $('price').value=''; $('brand').value='';
    $('sort').value='brand';
    [].forEach.call(document.querySelectorAll('.qc'),function(x){
      x.classList.toggle('on', x.dataset.f==='')});
    syncBrand(); apply();
  });

  // ── רצועת המותגים: מסונכרנת עם בורר המותג ──
  function syncBrand(){
    var b=$('brand').value;
    [].forEach.call(document.querySelectorAll('.blogo'),function(x){
      x.classList.toggle('on', x.dataset.b===b && b!=='');});
  }
  [].forEach.call(document.querySelectorAll('.blogo'),function(l){
    l.addEventListener('click',function(){
      $('brand').value = ($('brand').value===l.dataset.b) ? '' : l.dataset.b;
      syncBrand(); SHOWN=PAGE; apply();
    });
  });
  $('brand').addEventListener('change',syncBrand);

  // ── צ'יפים מהירים ──
  [].forEach.call(document.querySelectorAll('.qc'),function(c){
    if(c.id==='clear') return;
    c.addEventListener('click',function(){
      QF=c.dataset.f;
      [].forEach.call(document.querySelectorAll('.qc'),function(x){x.classList.toggle('on',x===c)});
      SHOWN=PAGE; apply();
    });
  });

  // ── כניסת סיטונאי: מחירי סיטונאי נפתחים רק בקוד, כמו באתר ──
  var WS_CODE='snir2026';
  function setWs(on){
    WS_OK=on; MODE=on?'pw':'pc';
    var b=$('wsOpen');
    b.classList.toggle('on',on);
    b.textContent=on?'מחירי סיטונאי · יציאה':'כניסת סיטונאי';
    repaint(); apply(); refreshOrder();
  }
  $('wsOpen').addEventListener('click',function(){
    if(WS_OK){ setWs(false); return; }
    $('wsOv').hidden=false; $('wsCode').value=''; $('wsMsg').textContent='';
    $('wsCode').focus();
  });
  $('wsX').addEventListener('click',function(){ $('wsOv').hidden=true; });
  addEventListener('keydown',function(ev){ if(ev.key==='Escape') $('wsOv').hidden=true; });
  $('wsOv').addEventListener('click',function(ev){ if(ev.target===$('wsOv')) $('wsOv').hidden=true; });
  function trySubmit(){
    var v=$('wsCode').value.trim().toLowerCase();
    if(v===WS_CODE){
      $('wsMsg').className='wsmsg ok'; $('wsMsg').textContent='הקוד אומת — מציג מחירי סיטונאי';
      setTimeout(function(){ $('wsOv').hidden=true; setWs(true); },550);
    } else {
      $('wsMsg').className='wsmsg'; $('wsMsg').textContent='קוד שגוי';
    }
  }
  $('wsGo').addEventListener('click',trySubmit);
  $('wsCode').addEventListener('keydown',function(ev){ if(ev.key==='Enter') trySubmit(); });

  // ── בחירת גוון: מחליפה מחיר, מלאי, ומק"ט להוספה לסל ──
  rows.forEach(function(row){
    var sws=row.querySelectorAll('.sw');
    if(!sws.length) return;
    sws.forEach(function(b){
      b.addEventListener('click',function(ev){
        ev.stopPropagation();          // לא לפתוח את המגירה בבחירת גוון
        sws.forEach(function(x){x.classList.toggle('on',x===b)});
        row.dataset.pc=b.dataset.pc; row.dataset.pw=b.dataset.pw;
        row.dataset.stock=b.dataset.st;
        var add=row.querySelector('.add');
        if(add){ add.dataset.sku=b.dataset.sku;
          add.classList.remove('on'); add.textContent='+ לסל'; }
        var u=row.querySelector('.punits');
        if(u) u.textContent='In stock · '+b.dataset.st;
        var im=row.querySelector('.imgframe img');
        if(im && b.dataset.img){
          im.src=b.dataset.img;
          var g=row.querySelector('.glow');
          if(g) g.style.backgroundImage='url("'+b.dataset.img+'")';
        }
        row.querySelector('.pv').textContent=(+row.dataset[MODE]).toLocaleString('he-IL');
      });
    });
  });

  // ── רשימת רכיבים ארוכה: קיצור עם פתיחה ──
  document.addEventListener('click',function(ev){
    var b=ev.target.closest('.rmore');
    if(!b) return;
    ev.stopPropagation();
    var rest=b.parentNode.querySelector('.rest');
    if(!rest) return;
    var open=!rest.hidden;
    rest.hidden=open;
    b.textContent = open ? '…עוד' : 'פחות';
  });

  // ── מגירת המוצר: לחיצה על השורה פותחת פירוט ──
  function closeRows(except){
    rows.forEach(function(r){
      if(r===except) return;
      var d=r.querySelector('.detail');
      if(d) d.hidden=true;
      r.classList.remove('open');
    });
  }
  rows.forEach(function(r){
    r.addEventListener('click',function(ev){
      // כפתורים בתוך השורה (הוספה לסל, סגירה) לא אמורים לפתוח או לסגור
      if(ev.target.closest('.add')||ev.target.closest('.sw')) return;
      var d=r.querySelector('.detail');
      if(!d) return;
      if(ev.target.closest('.dclose')){ d.hidden=true; r.classList.remove('open'); return; }
      var wasOpen=!d.hidden;
      closeRows(r);
      d.hidden=wasOpen;
      r.classList.toggle('open',!wasOpen);
      if(!wasOpen) r.scrollIntoView({behavior:'smooth',block:'nearest'});
    });
  });
  addEventListener('keydown',function(ev){ if(ev.key==='Escape') closeRows(null); });

  // ── עמודי המדיניות ──
  function closeSheets(){
    [].forEach.call(document.querySelectorAll('.sheet'),function(x){x.hidden=true});
  }
  [].forEach.call(document.querySelectorAll('.plink'),function(b){
    b.addEventListener('click',function(){
      var el=document.getElementById('sheet-'+b.dataset.p);
      var wasOpen=el && !el.hidden;
      closeSheets();
      if(el && !wasOpen){ el.hidden=false; el.scrollIntoView({behavior:'smooth',block:'start'}); }
    });
  });
  [].forEach.call(document.querySelectorAll('[data-close]'),function(b){
    b.addEventListener('click',closeSheets);
  });
  addEventListener('keydown',function(ev){ if(ev.key==='Escape') closeSheets(); });

  function syncShadow(){
    var sf=document.querySelector('.shadow-fx'), dv=document.querySelector('.device');
    if(sf&&dv) sf.classList.toggle('off', dv.offsetHeight < innerHeight);
  }
  addEventListener('resize',syncShadow);
  var _apply=apply; apply=function(){ _apply(); syncShadow(); };

  apply();
})();
</script>
</body></html>'''


if __name__ == '__main__':
    main()
