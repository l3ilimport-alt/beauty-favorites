#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""חיתוך רקע מבוסס מודל — BiRefNet מקומי, בלי תשלום ובלי ענן.

למה זה מחליף את האלגוריתם הקלאסי: הקלאסי מזהה רקע לפי *צבע*, ולכן נכשל על
רקע כהה או צבעוני, ואוכל חלקי מוצר לבנים. המודל מזהה את המוצר לפי *הבנה*
ולכן צבע הרקע לא מעניין אותו כלל.

⚠️ הפלט של המודל הוא לוגיטים ולא הסתברות — חובה סיגמואיד. נרמול מינימום־מקסימום
במקומו נותן מסכה מרוחה. זה הפח המרכזי כאן.
"""
import io
import os

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageFilter

HOME_MODELS = os.path.expanduser('~/.u2net')
LITE = os.path.join(HOME_MODELS, 'birefnet-general-lite.onnx')
FULL = os.path.join(HOME_MODELS, 'birefnet-general.onnx')
CREAM = (247, 242, 234)
SIZE = 1024

_SESS = {}


def session(path):
    if path not in _SESS:
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        _SESS[path] = ort.InferenceSession(path, so, providers=['CPUExecutionProvider'])
    return _SESS[path]


def alpha(img, model=LITE):
    """מחזיר מפת אלפא רציפה בגודל התמונה המקורית."""
    s = session(model)
    inp = s.get_inputs()[0]
    im = img.convert('RGB').resize((SIZE, SIZE), Image.BILINEAR)
    x = np.asarray(im, dtype=np.float32) / 255.0
    # נרמול ImageNet — כפי שהמודל אומן
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = np.transpose(x, (2, 0, 1))[None].astype(np.float32)
    out = s.run(None, {inp.name: x})
    a = out[-1] if isinstance(out, (list, tuple)) else out
    a = np.squeeze(a)
    a = 1.0 / (1.0 + np.exp(-a))          # ⚠️ סיגמואיד — לא נרמול מינ-מקס
    a = (a * 255).clip(0, 255).astype(np.uint8)
    return Image.fromarray(a, 'L').resize(img.size, Image.BILINEAR)


def clean(a, min_frac=0.02):
    """מסיר כתמים מנותקים — שאריות רקע שהמודל סימן בטעות."""
    try:
        from scipy import ndimage
    except Exception:
        return a
    arr = np.asarray(a)
    lab, n = ndimage.label(arr > 40)
    if n <= 1:
        return a
    sizes = ndimage.sum(arr > 40, lab, range(1, n + 1))
    keep = np.zeros_like(arr)
    big = sizes.max()
    for i, sz in enumerate(sizes, start=1):
        if sz >= max(big * min_frac, 64):
            keep[lab == i] = arr[lab == i]
    return Image.fromarray(keep, 'L')


def fragments(a, min_frac=0.06):
    """כמה גושים משמעותיים במסכה. מוצר שלם הוא גוש אחד או שניים; מוצר כהה
    על רקע כהה מתפרק לרסיסים והתוצאה גרועה יותר מלהציג את הצילום כמו שהוא."""
    try:
        from scipy import ndimage
    except Exception:
        return 1
    lab, n = ndimage.label(np.asarray(a) > 120)
    if n <= 1:
        return n
    sizes = ndimage.sum(np.asarray(a) > 120, lab, range(1, n + 1))
    return int((sizes >= sizes.max() * min_frac).sum())


def cutout(img, model=LITE, feather=0.8, bg=CREAM, max_frags=3):
    """מחזיר (RGBA חתוך וקצוץ, אחוז כיסוי) או (None, כיסוי) אם נכשל."""
    a = clean(alpha(img, model))
    arr = np.asarray(a)
    cov = float((arr > 200).mean())
    if not (0.01 <= cov <= 0.97):
        return None, cov
    if fragments(a) > max_frags:
        return None, cov
    a = a.filter(ImageFilter.GaussianBlur(feather))
    rgb = img.convert('RGB')
    over = Image.new('RGB', rgb.size, bg)
    hard = a.point(lambda v: 255 if v > 128 else 0)
    flat = Image.composite(rgb, over, hard)      # מיזוג שוליים אל הרקע
    out = Image.merge('RGBA', (*flat.split(), a))
    bb = a.point(lambda v: 255 if v > 24 else 0).getbbox()
    if bb:
        out = out.crop(bb)
    return out, cov


def judge(a, check_frag=True):
    """מדרג מסכה. המודל מצוין על רוב המקרים אבל הורס מוצר כהה על רקע כהה —
    הוא מסיר את האריזה השחורה ומשאיר אותיות מרחפות. השופט תופס בדיוק את זה.

    מחזיר (ציון 0..1, סיבת פסילה או None).
    """
    arr = np.asarray(a).astype(np.float32) / 255.0
    solid = arr > 0.78
    cov = float(solid.mean())
    if cov < 0.012:
        return 0.0, 'כמעט הכול נמחק'
    if cov > 0.97:
        return 0.0, 'לא הוסר דבר'
    ys, xs = np.nonzero(solid)
    bh = ys.max() - ys.min() + 1
    bw = xs.max() - xs.min() + 1
    fill = float(solid.sum()) / float(bh * bw)      # כמה מהמסגרת באמת מלא
    frags = fragments(a)
    # אטימות ממוצעת של מה שנשמר — תוצאה "רפאית" נופלת כאן
    kept = arr[arr > 0.15]
    opacity = float(kept.mean()) if kept.size else 0.0
    # מכויל על 18 מקרים אמיתיים: חיתוך תקין נותן מילוי 0.68 עד 0.98,
    # וחיתוך הרוס (אריזה כהה שנמחקה ונשארו אותיות מרחפות) נותן 0.46.
    # ⚠️ פסילה כאן אינה "אין תמונה" אלא "נסה את האלגוריתם הקלאסי" — ולכן
    # מותר לה להיות מחמירה. מוצר דק ואלכסוני (עיפרון שפתיים) ייפסל בטעות,
    # אבל הקלאסי חותך אותו מצוין על רקע לבן, ולכן זה לא עולה באיכות.
    if check_frag and frags >= 2 and fill < 0.52:
        return 0.15, f'מפוצל (גושים {frags}, מילוי {fill:.2f})'
    if opacity < 0.72:
        return 0.2, f'שקוף מדי (אטימות {opacity:.2f})'
    score = min(1.0, 0.55 * fill + 0.30 * opacity + 0.15 * (1.0 / frags))
    return score, None


def bg_luma(img, n=40):
    """בהירות מסגרת התמונה — מזהה צילום על רקע כהה."""
    im = img.convert('RGB')
    w, h = im.size
    px = im.load()
    sx, sy = max(1, w // n), max(1, h // n)
    pts = ([px[x, 1] for x in range(0, w, sx)] + [px[x, h - 2] for x in range(0, w, sx)] +
           [px[1, y] for y in range(0, h, sy)] + [px[w - 2, y] for y in range(0, h, sy)])
    return float(np.median([0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in pts]))


def best_cutout(img, bg=CREAM, classic=None):
    """מריץ מודל, שופט, ונופל לחלופה כשהתוצאה גרועה.

    מחזיר (RGBA או None, שיטה, הסבר).
    """
    a = clean(alpha(img))
    sc, why = judge(a)
    if why is None:
        out, cov = _compose(img, a, bg)
        return out, 'מודל', f'ציון {sc:.2f}'
    if classic is not None:
        ca = classic(img)
        if ca is not None:
            cs, cw = judge(ca, check_frag=False)
            if cw is None:
                out, cov = _compose(img, ca, bg)
                return out, 'קלאסי', f'המודל נפסל ({why}); הקלאסי {cs:.2f}'
    return None, 'לוח', why


def _compose(img, a, bg=CREAM, feather=0.8):
    a = a.filter(ImageFilter.GaussianBlur(feather))
    rgb = img.convert('RGB')
    over = Image.new('RGB', rgb.size, bg)
    flat = Image.composite(rgb, over, a.point(lambda v: 255 if v > 128 else 0))
    out = Image.merge('RGBA', (*flat.split(), a))
    bb = a.point(lambda v: 255 if v > 24 else 0).getbbox()
    if bb:
        out = out.crop(bb)
    return out, float((np.asarray(a) > 200).mean())


def soft_edge_frac(a):
    """אחוז פיקסלי המעבר — מדד לרכות הקצה. חיתוך בינארי נותן כמעט אפס."""
    arr = np.asarray(a)
    return float(((arr > 40) & (arr < 200)).mean())
