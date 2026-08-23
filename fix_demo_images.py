#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מחליף את תמונות ה"לוח" (רקע שחור/צבעוני שנראה זר בלוקבוק) בתמונה רשמית
מספורה — לפי הסקיל product-image-pipeline: מקור רשמי עדיף על כל תיקון.
רץ ברקע; בסוף מדפיס סיכום ונשמר קובץ מיפוי.
"""
import io, json, os, re, subprocess, sys, unicodedata, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageFilter
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CUT = os.path.join(HERE, '_דוגמה-תמונות')
MODES = os.path.join(CUT, '_מצב.json')
MAP = os.path.join(HERE, 'תמונות ספורה לדוגמה.json')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

spec = importlib.util.spec_from_file_location('pi', os.path.join(ROOT, 'תום ספק מיאמי/prepare_images.py'))
PI = importlib.util.module_from_spec(spec); spec.loader.exec_module(PI)

# שמות המותגים במסד בעברית — ספורה מחפשת באנגלית. מותג שלא במפה או שאינו
# נמכר בספורה מסומן None ולא נשלח (חיפוש עברי החזיר תוצאות אקראיות).
BRAND_EN = {
    'K18': 'K18', 'NYX': None, 'Rhode': 'Rhode', 'The Ordinary': 'The Ordinary',
    'אולפלקס': 'Olaplex', 'אורבן דקיי': 'Urban Decay', 'אי.אל.אף': 'elf cosmetics',
    'בנפיט': 'Benefit Cosmetics', 'הודה ביוטי': 'Huda Beauty',
    'ויקטוריה סיקרט': None, 'טאצ\'ה': 'Tatcha', 'ייב סן לורן': 'Yves Saint Laurent',
    'לוריאל': None, 'מורפי': None, 'מייבלין': None, 'נארס': 'NARS',
    'פי לואיז': None, 'פנטי ביוטי': 'Fenty Beauty', 'קוסאס': 'Kosas',
    'קייאלי': 'Kayali', 'קילס': None, 'קלרינס': 'Clarins',
    'ריר ביוטי': 'Rare Beauty', 'שרלוט טילבורי': 'Charlotte Tilbury',
}


def key(s):
    s = ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9 ]', ' ', s.lower())


def toks(s):
    STOP = {'the','a','of','and','for','with','in','ml','oz','g','none','set','mini'}
    return {t for t in key(s).split() if len(t) > 1 and t not in STOP}


def fetch_brand(brand):
    en = BRAND_EN.get(brand)
    if not en:
        return []
    out = []
    for q in (en, en + ' makeup', en + ' beauty'):
        u = ('https://www.sephora.com/api/v2/catalog/search/?type=keyword&q='
             + urllib.parse.quote(q) + '&pageSize=300&currentPage=1')
        r = subprocess.run(['curl','-sL','-m','40','-A',UA,'-H','Accept: application/json',
                            '--compressed','--',u], capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except Exception:
            continue
        bk = key(en).replace(' ', '')
        for p in d.get('products') or []:
            pk = key(p.get('brandName')).replace(' ', '')
            if not (bk[:6] in pk or pk[:6] in bk):
                continue
            img = (p.get('heroImage') or p.get('image450') or '').split('?')[0]
            if img.startswith('/'):
                img = 'https://www.sephora.com' + img
            if img:
                out.append({'name': p.get('displayName') or '', 'img': img})
        if out:
            return out
    return out


def cut_from(url, dst):
    raw = subprocess.run(['curl','-sL','-m','40','-A',UA,'--',url], capture_output=True).stdout
    if len(raw) < 1500:
        return False
    try:
        im = PI.fit(Image.open(io.BytesIO(raw)).convert('RGB'), 900)
    except Exception:
        return False
    mask = PI.cutout(im)
    if mask is None:
        return False
    mask = mask.filter(ImageFilter.GaussianBlur(1.0))
    over = Image.new('RGB', im.size, PI.CREAM)
    flat = Image.composite(im, over, mask.point(lambda v: 255 if v > 128 else 0))
    out = Image.merge('RGBA', (*flat.split(), mask))
    bb = mask.point(lambda v: 255 if v > 24 else 0).getbbox()
    if bb:
        out = out.crop(bb)
    out.thumbnail((260, 260), Image.LANCZOS)
    out.save(dst, 'WEBP', quality=80, method=6)
    return True


def main():
    r = subprocess.run(['python3', os.path.join(ROOT, 'backoffice/db.py'), 'products',
                        'select=sku,name_he,name_en,brand,image_url',
                        'active=is.true', 'stock=gt.0', 'limit=1000'],
                       capture_output=True, text=True, cwd=ROOT)
    rows = {p['sku']: p for p in json.loads(r.stdout)}
    modes = json.load(io.open(MODES, encoding='utf-8'))
    prev = {}
    if os.path.exists(MAP):
        prev = json.load(io.open(MAP, encoding='utf-8'))
    tiles = sorted({s for s, v in modes.items() if v == 'לוח' and s in rows}
                   | {s for s in prev if s in rows})
    print(f'לוחות לתיקון: {len(tiles)}')
    brands = sorted({rows[s].get('brand') or '' for s in tiles if rows[s].get('brand')})
    print(f'מותגים: {len(brands)}')
    with ThreadPoolExecutor(max_workers=5) as ex:
        cat = dict(zip(brands, ex.map(fetch_brand, brands)))
    for b in brands:
        print(f'  {b}: {len(cat.get(b) or [])} בספורה')

    fixed, mapping, revert = 0, {}, []
    def one(sku):
        nonlocal fixed
        p = rows[sku]
        cands = cat.get(p.get('brand') or '') or []
        if not cands:
            return
        want = toks(p.get('name_en') or p.get('name_he') or '')
        if not want:
            return
        best, bs = None, 0.0
        for c in cands:
            have = toks(c['name'])
            if not have:
                continue
            sc = len(want & have) / max(1, len(want | have))
            if sc > bs:
                best, bs = c, sc
        if not best or bs < 0.4:
            if sku in prev:
                revert.append(sku)      # הוחלף בריצה הפגומה — לשחזר מהמקומי
            return
        dst = os.path.join(CUT, f'{sku}.webp')
        if cut_from(best['img'], dst):
            modes[sku] = 'חיתוך'
            mapping[sku] = {'img': best['img'], 'match': best['name'], 'score': round(bs, 2)}
            fixed += 1

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(one, tiles))
    # שחזור מהצילום המקומי למי שההחלפה הקודמת שלו לא שרדה את הסינון המתוקן
    import glob as _g
    for sku in revert:
        u = rows[sku].get('image_url') or ''
        m = re.search(r'/images/(.+)$', u)
        if not m:
            continue
        lp = os.path.join(HERE, 'images', m.group(1))
        if not os.path.exists(lp):
            folder = os.path.dirname(lp)
            hits = sorted(_g.glob(os.path.join(folder, '01.*')))
            lp = hits[0] if hits else None
        if lp:
            im = PI.fit(Image.open(lp).convert('RGB'), 260)
            im.save(os.path.join(CUT, f'{sku}.webp'), 'WEBP', quality=80, method=6)
            modes[sku] = 'לוח'
    if revert:
        print(f'שוחזרו מהמקומי (החלפה קודמת שגויה): {len(revert)}')
    json.dump(modes, io.open(MODES, 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(mapping, io.open(MAP, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    left = sum(1 for s in tiles if modes.get(s) == 'לוח')
    print(f'\n✓ הוחלפו {fixed} · נותרו לוחות {left}')


if __name__ == '__main__':
    main()
