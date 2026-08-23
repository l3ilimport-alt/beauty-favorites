#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מריץ את מנוע החיתוך ההיברידי על כל הקטלוג.

מודל ← אלגוריתם קלאסי ← לוח. ראה catalog/cutout_ai.py והסקיל
product-image-pipeline. שומר התקדמות תוך כדי, כך שהפסקה אינה מאבדת עבודה.
"""
import glob
import importlib.util
import io
import json
import os
import re
import sys
import time

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CUT = os.path.join(HERE, '_דוגמה-תמונות')
MODES = os.path.join(CUT, '_מצב.json')
LOG = os.path.join(HERE, '_חיתוך-דוח.json')


def load(mod, path):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(ROOT, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


AI = load('ai', 'catalog/cutout_ai.py')
PI = load('pi', 'תום ספק מיאמי/prepare_images.py')


def classic(im):
    return PI.cutout(PI.fit(im.convert('RGB'), 900))


def source(row):
    m = re.search(r'/images/(.+)$', row.get('image_url') or '')
    if not m:
        return None
    p = os.path.join(HERE, 'images', m.group(1))
    if os.path.exists(p):
        return p
    fd = os.path.dirname(p)
    hits = sorted(glob.glob(os.path.join(fd, '01.*')) or glob.glob(os.path.join(fd, '*.jpg'))
                  or glob.glob(os.path.join(fd, '*.png')))
    return hits[0] if hits else None


def main():
    rows = json.load(io.open('/tmp/bf.json', encoding='utf-8'))
    modes = json.load(io.open(MODES, encoding='utf-8')) if os.path.exists(MODES) else {}
    done = json.load(io.open(LOG, encoding='utf-8')) if os.path.exists(LOG) else {}
    todo = [r for r in rows if r['sku'] not in done]
    print(f'סה"כ {len(rows)} · כבר עובדו {len(done)} · נותרו {len(todo)}', flush=True)
    t0 = time.time()
    for i, r in enumerate(todo, 1):
        sku = r['sku']
        p = source(r)
        if not p:
            done[sku] = {'how': 'אין קובץ'}
            continue
        try:
            im = Image.open(p)
            im.thumbnail((1200, 1200), Image.LANCZOS)
            out, how, why = AI.best_cutout(im, classic=classic)
        except Exception as ex:
            done[sku] = {'how': 'שגיאה', 'why': str(ex)[:80]}
            continue
        if out is not None:
            out.thumbnail((260, 260), Image.LANCZOS)
            out.save(os.path.join(CUT, f'{sku}.webp'), 'WEBP', quality=82, method=6)
            modes[sku] = 'חיתוך'
        else:
            im2 = im.copy()
            im2.thumbnail((260, 260), Image.LANCZOS)
            im2.convert('RGB').save(os.path.join(CUT, f'{sku}.webp'), 'WEBP',
                                    quality=82, method=6)
            modes[sku] = 'לוח'
        done[sku] = {'how': how, 'why': why}
        if i % 25 == 0 or i == len(todo):
            json.dump(done, io.open(LOG, 'w', encoding='utf-8'), ensure_ascii=False)
            json.dump(modes, io.open(MODES, 'w', encoding='utf-8'), ensure_ascii=False)
            el = time.time() - t0
            rate = el / i
            print(f'  {i}/{len(todo)} · {el/60:.0f} דק׳ · נותרו כ-{rate*(len(todo)-i)/60:.0f} דק׳',
                  flush=True)
    json.dump(done, io.open(LOG, 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(modes, io.open(MODES, 'w', encoding='utf-8'), ensure_ascii=False)
    import collections
    c = collections.Counter(v.get('how') for v in done.values())
    print('\n=== סיכום ===')
    for k, v in c.most_common():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
