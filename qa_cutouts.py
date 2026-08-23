#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בקרת איכות על תוצאות החיתוך — מודד את כל התיקייה ומדרג את הגרועות.

הלקח שחוזר בפרויקט הזה: מדדים לבדם מפספסים מה שהעין תופסת, ולכן הכלי מפיק
גם גיליון מגע ויזואלי של החשודות ולא רק מספרים.
"""
import collections
import io
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CUT = os.path.join(HERE, '_דוגמה-תמונות')
CREAM = (247, 242, 234)


def measure(path):
    im = Image.open(path).convert('RGBA')
    a = np.asarray(im.split()[-1]).astype(np.float32) / 255.0
    solid = a > 0.78
    cov = float(solid.mean())
    if solid.sum() < 4:
        return {'cov': cov, 'fill': 0.0, 'soft': 0.0, 'edge': 1.0, 'opacity': 0.0}
    ys, xs = np.nonzero(solid)
    fill = float(solid.sum()) / float((ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1))
    soft = float(((a > 0.16) & (a < 0.78)).mean())
    h, w = a.shape
    edge = float(np.concatenate([a[0, :], a[-1, :], a[:, 0], a[:, -1]]).mean())
    kept = a[a > 0.15]
    opacity = float(kept.mean()) if kept.size else 0.0
    return {'cov': cov, 'fill': fill, 'soft': soft, 'edge': edge, 'opacity': opacity}


def verdict(m, mode):
    """⚠️ מילוי נמוך לבדו אינו כשל.

    בבדיקה ויזואלית של 121 "חשודות" התברר שכמעט כולן חיתוכים מושלמים:
    שפתון עם המכסה לצידו, עיפרון, קונסילר עם מברשת — מוצרים דו־חלקיים
    שממלאים מעט מהמסגרת החוסמת מטבעם. הכשל האמיתי הוא מילוי נמוך *יחד עם*
    שקיפות (תוצאה רפאית) או שוליים שנשארו.
    """
    if mode == 'לוח':
        return 'לוח — הצילום כמות שהוא'
    if m['cov'] < 0.03:
        return 'חשוד: כמעט הכול נמחק'
    if m['edge'] > 0.55:
        return 'חשוד: הרקע נשאר'
    if m['fill'] < 0.34 and m['opacity'] < 0.90:
        return 'חשוד: דליל ורפאי'
    if m['soft'] > 0.34:
        return 'חשוד: הילה רחבה'
    return 'תקין'


def main():
    modes = json.load(io.open(os.path.join(CUT, '_מצב.json'), encoding='utf-8'))
    rows = {p['sku']: p for p in json.load(io.open('/tmp/bf.json', encoding='utf-8'))}
    res, sus = [], []
    for f in sorted(os.listdir(CUT)):
        if not f.endswith('.webp'):
            continue
        sku = f[:-5]
        try:
            m = measure(os.path.join(CUT, f))
        except Exception:
            continue
        v = verdict(m, modes.get(sku))
        res.append({'sku': sku, 'verdict': v, **{k: round(x, 3) for k, x in m.items()},
                    'name': (rows.get(sku, {}).get('name_he') or '')[:52],
                    'brand': rows.get(sku, {}).get('brand')})
        if v.startswith('חשוד'):
            sus.append(sku)
    c = collections.Counter(r['verdict'] for r in res)
    print(f'נבדקו {len(res)} תמונות')
    for k, v in c.most_common():
        print(f'  {k}: {v}')
    json.dump(res, io.open(os.path.join(HERE, '_בקרת-איכות.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    if sus:
        S, C = 190, 8
        R = (len(sus) + C - 1) // C
        sh = Image.new('RGB', (C * S, R * S), CREAM)
        for i, sku in enumerate(sus):
            im = Image.open(os.path.join(CUT, f'{sku}.webp')).convert('RGBA')
            im.thumbnail((S - 14, S - 14), Image.LANCZOS)
            cell = Image.new('RGBA', (S, S), CREAM + (255,))
            cell.alpha_composite(im, ((S - im.width) // 2, (S - im.height) // 2))
            sh.paste(cell.convert('RGB'), ((i % C) * S, (i // C) * S))
        sh.save('/tmp/qa_suspects.png')
        print(f'\nגיליון החשודות: /tmp/qa_suspects.png ({len(sus)})')
        for r in res:
            if r['verdict'].startswith('חשוד'):
                print(f"  [{r['verdict'][7:]:20}] {r['brand'] or '':<14} {r['name'][:40]}")


if __name__ == '__main__':
    main()
