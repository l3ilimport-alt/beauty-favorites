#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בוחר לכל מוצר את הצילום שממנו יוצא החיתוך הכי יפה.

הקטלוג מציג היום את הצילום הראשון בתיקייה, אבל לרוב המוצרים יש כמה צילומים —
וחלקם על רקע לבן נקי בעוד הראשון דווקא על רקע שחור או צילום אווירה. הכלי מריץ
את השופט של cutout_ai על כל אחד ובוחר את בעל הציון הגבוה.

מריצים אותו רק על מוצרים שהחיתוך שלהם לא יצא מושלם — אין טעם לשרוף זמן על
מוצר שכבר יצא נקי.

  python3 catalog/pick_best_photo.py            רק החשודים
  python3 catalog/pick_best_photo.py --all      כל מי שיש לו יותר מצילום אחד
"""
import glob
import importlib.util
import io
import json
import os
import re
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CUT = os.path.join(HERE, '_דוגמה-תמונות')
MODES = os.path.join(CUT, '_מצב.json')
PICKS = os.path.join(HERE, 'תמונה נבחרת.json')


def load(mod, path):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(ROOT, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


AI = load('ai', 'catalog/cutout_ai.py')
PI = load('pi', 'תום ספק מיאמי/prepare_images.py')


def photos(row):
    """כל הצילומים בתיקיית המוצר, ולא רק הראשון."""
    m = re.search(r'/images/([^/]+)/', row.get('image_url') or '')
    if not m:
        return []
    fd = os.path.join(HERE, 'images', m.group(1))
    if not os.path.isdir(fd):
        return []
    out = []
    for ext in ('*.jpg', '*.jpeg', '*.png', '*.webp'):
        out += glob.glob(os.path.join(fd, ext))
    return sorted(out)


def score_photo(path):
    """מחזיר (ציון, מסכה, תמונה, שיטה) — ככל שגבוה יותר, החיתוך יפה יותר."""
    try:
        im = Image.open(path)
        im.thumbnail((1100, 1100), Image.LANCZOS)
    except Exception:
        return -1, None, None, None
    a = AI.clean(AI.alpha(im))
    sc, why = AI.judge(a)
    if why is None:
        return sc, a, im, 'מודל'
    ca = PI.cutout(PI.fit(im.convert('RGB'), 900))
    if ca is not None:
        cs, cw = AI.judge(ca, check_frag=False)
        if cw is None:
            return cs * 0.95, ca, im, 'קלאסי'   # קנס קל — המודל מדויק יותר בקצוות
    return 0.0, None, im, None


def main():
    rows = json.load(io.open('/tmp/bf.json', encoding='utf-8'))
    modes = json.load(io.open(MODES, encoding='utf-8')) if os.path.exists(MODES) else {}
    qa = {}
    qp = os.path.join(HERE, '_בקרת-איכות.json')
    if os.path.exists(qp):
        qa = {r['sku']: r for r in json.load(io.open(qp, encoding='utf-8'))}

    def needs(sku):
        if '--all' in sys.argv:
            return True
        if modes.get(sku) == 'לוח':
            return True
        v = (qa.get(sku) or {}).get('verdict', '')
        return v.startswith('חשוד')

    picks = json.load(io.open(PICKS, encoding='utf-8')) if os.path.exists(PICKS) else {}
    todo = [r for r in rows if needs(r['sku']) and r['sku'] not in picks]
    print(f'מועמדים לבחירה מחדש: {len(todo)}', flush=True)
    changed = 0
    for i, r in enumerate(todo, 1):
        ph = photos(r)
        if len(ph) < 2:
            picks[r['sku']] = {'n': len(ph), 'changed': False}
            continue
        best = (-1, None, None, None, None)
        for p in ph:
            sc, a, im, how = score_photo(p)
            if sc > best[0]:
                best = (sc, a, im, how, p)
        sc, a, im, how, p = best
        if a is None or sc <= 0:
            picks[r['sku']] = {'n': len(ph), 'changed': False}
            continue
        out, _ = AI._compose(im, a)
        out.thumbnail((260, 260), Image.LANCZOS)
        out.save(os.path.join(CUT, f"{r['sku']}.webp"), 'WEBP', quality=82, method=6)
        modes[r['sku']] = 'חיתוך'
        picks[r['sku']] = {'n': len(ph), 'changed': True, 'score': round(sc, 2),
                           'how': how, 'file': os.path.basename(p)}
        changed += 1
        if i % 10 == 0 or i == len(todo):
            json.dump(picks, io.open(PICKS, 'w', encoding='utf-8'), ensure_ascii=False)
            json.dump(modes, io.open(MODES, 'w', encoding='utf-8'), ensure_ascii=False)
            print(f'  {i}/{len(todo)} · שופרו {changed}', flush=True)
    json.dump(picks, io.open(PICKS, 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(modes, io.open(MODES, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'\n✓ נבדקו {len(todo)} · הוחלף צילום ב-{changed}')


if __name__ == '__main__':
    main()
