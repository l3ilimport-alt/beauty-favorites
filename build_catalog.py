#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build the "Beauty Favorites" digital catalog (grouped-variant model).
Reads knowledge/<id>/product.json, groups shade-variants under one card,
copies images, and emits catalog/index.html (data inline → works from file://).
Re-run after adding products to knowledge/ or editing catalog_overrides.json.
"""
import json, glob, os, shutil, re, sys

# ---- image optimization on copy (keeps the published GitHub Pages site well under the 1GB limit
#      and makes the catalog load far faster). Downscales to max 720px + recompresses. ----
IMG_MAXDIM = 720
def optimize_image(src, dst):
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(src))
        w, h = im.size
        m = max(w, h)
        if m > IMG_MAXDIM:
            r = IMG_MAXDIM / float(m)
            im = im.resize((max(1, int(w * r)), max(1, int(h * r))), Image.LANCZOS)
        ext = os.path.splitext(dst)[1].lower()
        if ext == ".png":
            im.save(dst, "PNG", optimize=True)
        elif ext == ".webp":
            im.save(dst, "WEBP", quality=74, method=4)
        else:
            if im.mode in ("RGBA", "LA", "P"):
                rgba = im.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.save(dst, "JPEG", quality=72, optimize=True, progressive=True)
        return True
    except Exception:
        shutil.copy2(src, dst)
        return False

# ---- shade -> swatch color (from the shade NAME, since shade-specific images
#      are often unavailable / shared across the line) ----
COLOR_WORDS = [
    ("chocolate", "#4a2c1d"), ("espresso", "#3d281c"), ("mocha", "#5b3a28"), ("coffee", "#4a3120"),
    ("butterscotch", "#d99e54"), ("caramel", "#b5793f"), ("toffee", "#9c6a3c"), ("cinnamon", "#8a4b2a"),
    ("honey", "#d9a martyr"[:7] if False else "#d6a14b"), ("amber", "#b06a2c"), ("copper", "#b0673c"),
    ("bronze", "#9a6a3a"), ("golden", "#c8a24a"), ("gold", "#c8a24a"),
    ("raspberry", "#a32a5a"), ("cherry", "#9b1b30"), ("ruby", "#9b1b30"), ("berry", "#8e2f54"),
    ("rose", "#cf6d86"), ("pinkgasm", "#ef7fa6"), ("peachgasm", "#f59a78"), ("peachy", "#f6a888"),
    ("peach", "#f6a888"), ("coral", "#fb7a5a"), ("pink", "#ec9ec0"), ("red", "#c0392b"),
    ("plum", "#6e2a5a"), ("mauve", "#9c6f86"), ("nude", "#d3a07f"), ("spice", "#9c5a3c"),
    ("sand", "#d8c19a"), ("beige", "#dcc6a6"), ("star", "#caa85a"), ("vanilla", "#ead9bd"),
    ("milkshake", "#efddc7"), ("custard", "#e7c79a"), ("latte", "#c79a6e"), ("macchiato", "#a9764a"),
]
DEPTHS = [("porcelain", .08), ("fair", .17), ("light-medium", .34), ("light", .25),
          ("medium", .5), ("tan", .66), ("deep", .82), ("rich", .9), ("dark", .92), ("ebony", .95)]

def _skin_hex(depth, under):
    lo, hi = (246, 223, 197), (70, 43, 28)   # light beige -> deep brown
    r = int(lo[0] + (hi[0]-lo[0])*depth); g = int(lo[1]+(hi[1]-lo[1])*depth); b = int(lo[2]+(hi[2]-lo[2])*depth)
    if under in ("w", "g"): r = min(255, r+8); b = max(0, b-12)     # warm / golden
    elif under in ("c", "p"): r = max(0, r-6); b = min(255, b+12)   # cool / pink
    elif under == "r": r = min(255, r+12); g = max(0, g-5)          # red
    return "#%02x%02x%02x" % (r, g, b)

# product types where a numbered/worded shade really means a SKIN DEPTH (so a skin-tone swatch is right)
COMPLEXION_RE = re.compile(
    r"פאונדיישן|foundation|קונסילר|concealer|סקין טינט|skin tint|קרם גוון|"
    r"\bbb\b|\bcc\b|קרם bb|קרם cc|bb cream|cc cream|color correct|קורקטור|"
    r"פודרה נסתרת|פודרה מקבעת|פודרת hd|hd powder|loose powder|setting powder|face powder", re.I)
def is_complexion(p):
    txt = " ".join(str(p.get(k) or "") for k in
                   ("category_refined", "name_he", "name_en", "excel_description"))
    return bool(COMPLEXION_RE.search(txt))

def shade_color(shade, complexion=False):
    if not shade:
        return None
    s = shade.lower()
    if complexion:   # numbered/worded shade == skin depth → skin-tone swatch
        sk = next((d for w, d in sorted(DEPTHS, key=lambda x: -len(x[0])) if w in s), None)
        mnum = re.search(r"(\d+(?:\.\d+)?)", s)
        mund = re.search(r"\d+(?:\.\d+)?\s*([nwcrgp]{1,2})\b", s)
        under = mund.group(1)[0] if mund else None
        sig = []
        if sk is not None:
            sig.append(sk)
        if mnum:
            n = float(mnum.group(1))
            if n >= 100:
                n /= 100.0
            sig.append(max(.06, min(.95, (n-1)/8.0)) if n <= 10 else .5)
        if sig:
            return _skin_hex(sum(sig)/len(sig), under)
    for w, hx in COLOR_WORDS:   # color cosmetics (lip / blush / eyeshadow) — match by colour NAME only
        if w in s:
            return hx
    return None   # numeric shade with no colour name → no fake dot; UI shows a clean number label

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOW = os.path.join(ROOT, "knowledge")
CAT  = os.path.join(ROOT, "catalog")
IMGDIR = os.path.join(CAT, "images")
OVERRIDES = os.path.join(CAT, "catalog_overrides.json")
ORDER_FILE = os.path.join(ROOT, "הזמנה 1.xlsx")

SITE_URL = "https://l3ilimport-alt.github.io/beauty-favorites"

# ---- brand normalization ----
BRAND_MAP = {
    "לא נמצא": "אחר", "לא ידוע": "אחר",
    "-417 (Minus 417) Dead Sea Cosmetics": "417", "Airspun (Coty)": "Airspun",
    "Schwarzkopf Professional": "Schwarzkopf", "Maybelline New York": "Maybelline",
    "Amorus USA": "Amorus", "Benefit Cosmetics": "Benefit",
    "Giorgio Armani": "Armani", "Armani Beauty": "Armani",
    "Charlotte Tilbury Beauty": "שרלוט טילבורי", "Charlotte Tilbury": "שרלוט טילבורי",
    "Dior": "דיור", "DIOR": "דיור", "דיור (Dior)": "דיור",
    "YSL": "ייב סן לורן", "איב סן לורן": "ייב סן לורן", "Yves Saint Laurent": "ייב סן לורן",
    "M.A.C": "MAC", "Mac": "MAC",
    "Makeup for ever": "מייק אפ פור אבר", "Make Up For Ever": "מייק אפ פור אבר",
    "מייקאפ פוראבר": "מייק אפ פור אבר",
    "ONE/SIZE": "ONE/SIZE", "וואן סייז": "ONE/SIZE", "וואן סайז (ONE/SIZE)": "ONE/SIZE",
    "Rhode": "Rhode", "RHODE": "Rhode", "רואד": "Rhode", "רואד (RHODE)": "Rhode", "רוד": "Rhode",
    "Ordinary": "The Ordinary", "The Ordinary": "The Ordinary",
    "Saie": "SAIE", "סאיי": "SAIE",
    "SEPHORA": "ספורה", "Sephora Collection": "ספורה",
    "אוארגלאס": "האורגלאס",
}
def norm_brand(b):
    if not b: return "אחר"
    return BRAND_MAP.get(b.strip(), b.strip())

# ---- product type (category) ----
FRAG = ["perfume", "fragrance", "eau de", "edp", "edt", "parfum", "בושם", "או דה"]
HAIR = ["שיער", "קרטין", "שמפו", "ווקס", "וקס", "ג'ל", "ג׳ל", "קליי", "חימר", "בלונד", "blond",
        "schwarzkopf", "3dmen", "מכונת תספורת", "תספורת", "קליפר", "trimmer", "clipper"]
SKIN = ["פילינג", "מסז", "רולר", "ספא", "אצטון", "סרום", "טיפוח", "ניקוי", "מסיר איפור", "פנים קרם", "לחות",
        "קרם פנים", "קרם עיניים", "קרם גוף", "קרם הגנה", "מסכת פנים", "מסכה", "מסיכה",
        "שקית תחת", "אנטי אייג", "טיפול מיידי", "הגנה מינרלי"]
# ---- קטגוריות חדשות (מחליפות את "אחר") ----
EQUIP  = ["ריהוט", "כיסא", "שולחן מניקור"]                                        # ציוד מקצועי / רהיטים
ACCESS = ["ריסים מלאכות", "מברש", "מכחול", "ספוג", "נרתיק", "תיק איפור", "תיק קוסמט", "אריזה",
          "שקית נשיאה", "סכין גילוח", "גילוח", "עדשות מגע", "מראת", "אפליקטור", "פאף"]   # אביזרים וכלים
NAILS  = ["ציפורנ", "מניקור", "טיפים לציפור", "soft gel", "לק ג'ל", "לק ג׳ל"]      # ציפורניים
# מונחי איפור חד-משמעיים — גוברים על "ג'ל"/"סרום"/"לחות"/"שיער" מקריים שמופיעים בתיאור
MAKEUP = ["שפתון", "ליפ", "גלוס", "גלוז", "סטיין", "lip", "gloss",
          "סומק", "בלאש", "blush", "מסקרה", "mascara", "צללי", "איישדו", "eyeshadow",
          "קונסילר", "concealer", "פאונדיישן", "foundation", "מייקאפ", "מייק-אפ", "מייק אפ", "makeup",
          "היילייטר", "highlight", "מאיר", "מבריק", "ברונזר", "bronzer", "אייליינר", "eyeliner",
          "עיפרון", "גבות", "brow", "פלטת", "palette", "פודר", "powder", "פריימר", "primer",
          "קונטור", "contour", "טינט", "tint", "צלליות", "ערכת איפור", "סט איפור", "איפור עיניים"]

# מארז/מבחר/לוט הנמכר כיחידה אחת — מזוהה לפי השם העברי בלבד (excel מכיל "MIX" רועש)
BUNDLE_RE = re.compile(r'מבחר|בולק|תפזורת|מארז|מיקס|ללא קופסה|no\s*box|nobox', re.I)
def ptype(p):
    # עקיפה מפורשת מקובץ הידע — גוברת על כל הניחושים (לתיקוני סיווג נקודתיים)
    ov = str(p.get("category_main") or "").strip()
    if ov:
        return ov
    nm = str(p.get("name_he") or "")
    if BUNDLE_RE.search(nm) and "ערבוב" not in nm:   # מארזים גובר על קטגוריית התוכן
        return "מארזים"
    txt = " ".join(str(p.get(k) or "") for k in
                   ("name_he", "name_en", "category_refined", "category_excel", "excel_description")).lower()
    # קודם הסוגים הספציפיים שאינם קוסמטיקה
    if any(w in txt for w in EQUIP):  return "ציוד"
    if any(w in txt for w in ACCESS): return "אביזרים"
    if any(w in txt for w in NAILS):  return "ציפורניים"
    # איפור חד-משמעי — לפני שיער/טיפוח/בושם (מונע דליפת ג'ל-גבות/שפתון-סרום וכד')
    if any(w in txt for w in MAKEUP): return "איפור"
    if any(w in txt for w in FRAG):   return "בושם"
    if any(w in txt for w in HAIR):   return "שיער"
    if any(w in txt for w in SKIN):   return "טיפוח"
    if (p.get("category_excel") or "").lower() == "makeup": return "איפור"
    return "איפור"   # ברירת מחדל — הקטלוג ברובו איפור (אין יותר "אחר")

def whole_price(x):
    """עיגול מחיר למספר שלם (מחירי הקטלוג שלמים)."""
    try:
        return round(float(x))
    except (TypeError, ValueError):
        return x

def detect_vegan(p):
    t = " ".join(str(p.get(k) or "") for k in ("ingredients", "description", "key_features")).lower()
    return "vegan" in t or "טבעוני" in t

# ---- order-file filter ----
def _nbc(x):
    s = re.sub(r"\D", "", str(x or "")); return s.lstrip("0") or s
def _ndesc(x):
    return re.sub(r"\s+", " ", str(x or "").strip().lower())
def load_order_keys():
    bcs, descs = set(), set()
    try:
        import openpyxl
        wb = openpyxl.load_workbook(ORDER_FILE, read_only=True, data_only=True)
        for r in list(wb["Sheet1"].iter_rows(values_only=True))[1:]:
            if not r or not r[1]: continue
            if r[0]: bcs.add(_nbc(r[0]))
            descs.add(_ndesc(r[1]))
    except Exception as e:
        print("warning: no order file, showing all:", e); return None, None
    return bcs, descs

# ---- shade-grouping helpers ----
SHADE_WORDS = set("""fair clair claire medium deep tan dore dore doré fonce foncé neutral neutre warm
chaud cool light dark rich soft rose peach peachy berry nude gold golden silver bronze sand beige black
brown blonde blond pink red cherry original mink amber star walk shame chocolate galifornia hoola
dandelion pinkgasm peachgasm dreampop pop sunset jade lilas sable mini deluxe trio set""".split())
CODE = re.compile(r"^[0-9]+(\.[0-9]+)?[a-z]{0,4}$", re.I)

def _strip_trailing_shade(name):
    toks = name.split()
    while toks:
        last = toks[-1].strip("-–/.,()#")
        if not last:
            toks.pop(); continue
        if CODE.match(last) or last.lower() in SHADE_WORDS or len(last) <= 1:
            toks.pop()
        else:
            break
    return " ".join(toks)

def group_key(p, brand):
    # prefer the (now-clean, consistent) Hebrew name; fall back to raw excel/en
    base = p.get("name_he") or p.get("excel_description") or p.get("name_en") or ""
    sh = p.get("shade") or ""
    if sh:
        base = re.sub(re.escape(sh), "", base, flags=re.I)
    base = re.sub(r"\([^)]*\)", " ", base)             # strip parenthetical shade e.g. "(גוון X)"
    base = re.sub(r"#?\d+\b", " ", base)              # drop numeric shade codes
    base = _strip_trailing_shade(re.sub(r"\s+", " ", base).strip())
    base = re.sub(r"[\s\-–/]+$", "", base).strip().lower()
    return (brand, ptype(p), base) if len(base) >= 6 else None

def _lcp(strings):
    if not strings: return ""
    s1, s2 = min(strings), max(strings)
    i = 0
    while i < len(s1) and i < len(s2) and s1[i] == s2[i]: i += 1
    return s1[:i]

def he_base(members):
    """Hebrew base name for a group: strip the shade from each member's name,
    then take the most common result (robust to one member leaking a shade)."""
    from collections import Counter
    bases = []
    for m in members:
        b = m["name_he"]; sh = m.get("shade") or ""
        if sh:
            b = re.sub(re.escape(sh), "", b, flags=re.I)
        b = re.sub(r"גוון\s*[^\s,–\-]*", "", b)          # "גוון X"
        b = re.sub(r"#?\d+(\.\d+)?[A-Za-z]{0,4}\b", "", b)  # shade codes
        b = re.sub(r"\s*[–\-]\s*,\s*", " ", b)             # dangling " – , "
        b = re.sub(r",\s*,", ",", b)
        b = re.sub(r"\s+", " ", b).strip(" –-,()|·")
        if b:
            bases.append(b)
    if not bases:
        return members[0]["name_he"]
    # prefer the most common; tie-break by shortest (the cleaner base)
    cnt = Counter(bases)
    top = cnt.most_common()
    best = sorted(top, key=lambda kv: (-kv[1], len(kv[0])))[0][0]
    # final cleanup: a leaked shade often leaves a dangling unbalanced "(" + shade fragment
    if best.count("(") > best.count(")"):
        best = best[:best.rfind("(")]
    best = re.sub(r"\s+", " ", best).strip(" –-,()|·")
    return best

def main():
    # מצב מהיר (--fast או FAST=1): לא מוחק ולא מעבד מחדש תמונות קיימות — רק בונה index.html.
    # מתאים לשינויי קוד/HTML בלבד. תמונות חדשות עדיין יעובדו (אם חסרות ביעד).
    fast = ("--fast" in sys.argv) or (os.environ.get("FAST") == "1")
    if os.path.isdir(IMGDIR):
        if not fast:
            shutil.rmtree(IMGDIR)
    os.makedirs(IMGDIR, exist_ok=True)
    if fast:
        print("⚡ מצב מהיר: מדלג על עיבוד תמונות קיימות")

    overrides = {}
    try:
        ov = json.load(open(OVERRIDES, encoding="utf-8"))
        overrides = {k: v for k, v in ov.items() if not k.startswith("_")}
    except Exception:
        pass

    order_bc, order_desc = load_order_keys()
    excluded = []
    raw = []   # individual products (variants)

    for pj in sorted(glob.glob(os.path.join(KNOW, "[0-9]*", "product.json")),
                     key=lambda x: int(os.path.basename(os.path.dirname(x)).split("-")[0])):
        d = os.path.dirname(pj); pid = os.path.basename(d)
        try:
            p = json.load(open(pj, encoding="utf-8"))
        except Exception as e:
            print("skip", pj, e); continue

        if order_bc is not None:
            try: num = int(pid.split("-")[0])
            except ValueError: num = 0
            inb = _nbc(p.get("barcode"))
            in_order = (num >= 56) or (inb in order_bc and inb != "") \
                or (_ndesc(p.get("excel_description")) in order_desc)
            if not in_order:
                excluded.append(pid); continue

        # copy images
        src = os.path.join(d, "images"); imgs = []
        if os.path.isdir(src):
            files = sorted(f for f in os.listdir(src)
                           if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
            if files:
                os.makedirs(os.path.join(IMGDIR, pid), exist_ok=True)
            for f in files:
                dst = os.path.join(IMGDIR, pid, f)
                if not (fast and os.path.exists(dst)):   # מצב מהיר: דלג אם התמונה כבר קיימת
                    optimize_image(os.path.join(src, f), dst)
                imgs.append(f"images/{pid}/{f}")

        brand = norm_brand(p.get("brand"))
        ov = overrides.get(str(p.get("barcode") or ""), {})
        badges = list(ov.get("badges") or [])
        sale = whole_price(ov.get("sale_price")) if ov.get("sale_price") not in (None, "") else None
        if sale: badges = (["sale"] + badges) if "sale" not in badges else badges
        if detect_vegan(p): badges.append("vegan")

        raw.append({
            "id": pid,
            "name_he": p.get("name_he") or p.get("name_en") or pid,
            "name_en": p.get("name_en") or "",
            "brand": brand,
            "type": ptype(p),
            "price": whole_price(p.get("price_ils")),
            "sale": sale,
            "size": p.get("size") or "",
            "shade": p.get("shade") or "",
            "barcode": p.get("barcode") or "",
            "desc": p.get("description") or "",
            "features": p.get("key_features") or [],
            "ingredients": p.get("ingredients") or "",
            "usage": p.get("usage") or "",
            "desc_ar": p.get("description_ar") or "",
            "features_ar": p.get("features_ar") or [],
            "usage_ar": p.get("usage_ar") or "",
            "contents": p.get("contents") or [],
            "imgs": imgs,
            "badges": badges,
            "color": p.get("shade_hex") or shade_color(p.get("shade") or "", is_complexion(p)),
            "_key": group_key(p, brand),
        })

    # ---- group shade-variants ----
    buckets = {}
    singles = []
    for p in raw:
        k = p["_key"]
        if k is None:
            singles.append(p)
        else:
            buckets.setdefault(k, []).append(p)

    groups = []
    def variant(p):
        d = {"id": p["id"], "shade": p["shade"] or p["name_he"], "price": p["price"],
                "sale": p["sale"], "size": p["size"], "barcode": p["barcode"], "imgs": p["imgs"],
                "desc": p["desc"], "features": p["features"], "ingredients": p["ingredients"],
                "usage": p["usage"], "badges": p["badges"], "color": p.get("color")}
        if p.get("desc_ar"): d["desc_ar"] = p["desc_ar"]
        if p.get("features_ar"): d["features_ar"] = p["features_ar"]
        if p.get("usage_ar"): d["usage_ar"] = p["usage_ar"]
        if p.get("contents"): d["contents"] = p["contents"]
        return d
    def make_group(members, base_he):
        members = sorted(members, key=lambda m: (m["shade"] or m["name_he"]))
        return {"gid": "g" + str(len(groups)), "name_he": base_he,
                "name_en": _strip_trailing_shade(members[0]["name_en"]),
                "brand": members[0]["brand"], "type": members[0]["type"],
                "variants": [variant(m) for m in members]}

    for k, members in buckets.items():
        if len(members) >= 2:
            groups.append(make_group(members, he_base(members)))
        else:
            singles.append(members[0])
    for p in singles:
        groups.append({"gid": "g" + str(len(groups)), "name_he": p["name_he"],
                       "name_en": p["name_en"], "brand": p["brand"], "type": p["type"],
                       "variants": [variant(p)]})

    # keep a stable, brand-grouped order
    groups.sort(key=lambda g: (g["brand"], g["name_he"]))
    for i, g in enumerate(groups): g["gid"] = "g" + str(i)

    barcode_seen = {}
    dup_barcodes = []
    for g in groups:
        for v in g["variants"]:
            bc = _nbc(v.get("barcode"))
            if not bc:
                continue
            if bc in barcode_seen:
                dup_barcodes.append((bc, barcode_seen[bc], v["id"]))
            else:
                barcode_seen[bc] = v["id"]

    og_image = (SITE_URL.rstrip("/") + "/og-image.png") if SITE_URL else "og-image.png"

    # ---- חיבור Supabase: מוזרק לדף כ-window.SUPA. ריק → הקטלוג עובד במצב וואטסאפ-טקסט בלבד ----
    supa_cfg = {"url": "", "anon": ""}
    try:
        sc = json.load(open(os.path.join(CAT, "supabase.config.json"), encoding="utf-8"))
        supa_cfg = {"url": sc.get("url") or "", "anon": sc.get("anon_key") or ""}
    except Exception:
        pass
    if supa_cfg["url"] and supa_cfg["anon"]:
        print(f"   Supabase מחובר: {supa_cfg['url']}")
    else:
        print("   Supabase לא מוגדר עדיין (catalog/supabase.config.json) — מצב וואטסאפ-טקסט בלבד")

    out = TEMPLATE.replace("/*__GROUPS__*/", json.dumps(groups, ensure_ascii=False))
    out = out.replace("__COUNT__", str(len(groups)))
    out = out.replace("__OG_IMAGE__", og_image)
    out = out.replace("__SUPABASE_CONFIG__", json.dumps(supa_cfg, ensure_ascii=False))
    with open(os.path.join(CAT, "index.html"), "w", encoding="utf-8") as f:
        f.write(out)

    multi = [g for g in groups if len(g["variants"]) > 1]
    nprod = sum(len(g["variants"]) for g in groups)
    nimg = sum(len(v["imgs"]) for g in groups for v in g["variants"])
    print(f"✅ index.html: {len(groups)} כרטיסים ({nprod} מוצרים, {nimg} תמונות)")
    print(f"   קבוצות-גוונים (>1 גוון): {len(multi)}")
    for g in sorted(multi, key=lambda g: -len(g["variants"]))[:8]:
        print(f"     · {g['name_he'][:42]} ({g['brand']}) — {len(g['variants'])} גוונים")
    print(f"   הוסרו (לא בהזמנה 1): {len(excluded)}")
    if dup_barcodes:
        print(f"⚠️  ברקודים כפולים: {len(dup_barcodes)} (משפיע על מלאי/הזמנות לפי sku)")
        for bc, first_id, second_id in dup_barcodes[:10]:
            print(f"     · {bc}: {first_id} / {second_id}")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Beauty Favorites — קטלוג</title>
<meta name="description" content="הקולקציה הנבחרת — איפור, טיפוח, שיער ובושם מהמותגים האהובים">
<meta property="og:type" content="website">
<meta property="og:title" content="Beauty Favorites — קטלוג מוצרים">
<meta property="og:description" content="הקולקציה הנבחרת — איפור, טיפוח, שיער ובושם ✦ לחצו לצפייה והזמנה">
<meta property="og:image" content="__OG_IMAGE__">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="he_IL">
<!-- חיבור Supabase (anon ציבורי). אם לא הוגדר — הקטלוג נופל חזרה למצב וואטסאפ-טקסט בלבד. -->
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js"></script>
<script>window.SUPA=__SUPABASE_CONFIG__;</script>
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="__OG_IMAGE__">
<meta name="theme-color" content="#7c3aed">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="apple-touch-icon" href="favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;700;900&family=Cormorant+Garamond:wght@500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#faf8ff; --surface:#ffffff; --border:#efe9f7; --border2:#e4daf5;
  --accent:#7c3aed; --accent-d:#5b21b6; --accent-l:#a855f7; --accent-soft:#f3edfe;
  --text:#1e1633; --muted:#8b85a0; --lux:#b9a16b;
  --radius:16px; --shadow:0 6px 28px rgba(91,33,182,.08); --shadow-h:0 14px 44px rgba(91,33,182,.16);
  --font:'Heebo',-apple-system,BlinkMacSystemFont,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
html,body{background:var(--bg);color:var(--text);font-family:var(--font);-webkit-font-smoothing:antialiased;overflow-x:hidden}
body{padding-bottom:90px}
a{color:inherit}img{display:block}
::-webkit-scrollbar{height:0;width:0}

.brandbar{position:relative;display:flex;justify-content:center;align-items:center;padding:14px 16px 10px;background:var(--bg)}
.brandbar img{height:58px;width:auto;display:block;transition:transform .25s ease}
.brandbar img:hover{transform:translateY(-1px)}
.langbtn{position:absolute;inset-inline-start:16px;top:50%;transform:translateY(-50%);
  background:var(--surface);border:1px solid var(--border2);color:var(--accent-d);
  font-family:var(--font);font-size:13px;font-weight:500;padding:7px 14px;border-radius:30px;
  cursor:pointer;box-shadow:var(--shadow);transition:background .2s,transform .15s}
.langbtn:hover{background:var(--accent-soft);transform:translateY(-50%) scale(1.04)}
@media(max-width:640px){.brandbar img{height:46px}.brandbar{padding:11px 16px 7px}.langbtn{font-size:12px;padding:6px 11px;inset-inline-start:12px}}
.herobanner{position:relative;width:100%;overflow:hidden;border-bottom:1px solid var(--border);
  background:linear-gradient(135deg,#ece5fb 0%,#f6f1fd 38%,#faf8ff 62%,#efe7fc 100%)}
.herobanner::before,.herobanner::after{content:'';position:absolute;border-radius:50%;pointer-events:none}
.herobanner::before{width:340px;height:340px;top:-170px;left:-110px;background:radial-gradient(circle,rgba(168,85,247,.14),transparent 70%)}
.herobanner::after{width:420px;height:420px;bottom:-230px;right:-130px;background:radial-gradient(circle,rgba(124,58,237,.12),transparent 70%)}
.hero-inner{max-width:860px;margin:0 auto;padding:58px 20px 54px;text-align:center;position:relative}
.hero-kicker{font-family:var(--font);font-size:13px;font-weight:500;letter-spacing:7px;color:var(--accent-d);text-transform:uppercase}
.hero-title{font-family:'Cormorant Garamond',Georgia,serif;font-style:italic;font-weight:600;
  font-size:clamp(44px,7.5vw,76px);line-height:1.08;margin:10px 0 14px;
  background:linear-gradient(100deg,#5b21b6,#7c3aed 55%,#a855f7);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero-line{width:120px;height:1.4px;background:var(--lux);margin:0 auto 16px;position:relative}
.hero-line::before,.hero-line::after{content:'';position:absolute;top:-1.3px;width:4px;height:4px;border-radius:50%;background:var(--lux)}
.hero-line::before{right:-9px}.hero-line::after{left:-9px}
.hero-sub{font-size:clamp(14.5px,2.4vw,18px);font-weight:400;color:var(--text);letter-spacing:.3px}
@media(max-width:640px){.hero-inner{padding:44px 16px 40px}.hero-kicker{letter-spacing:5px;font-size:11.5px}}
.hero{text-align:center;padding:30px 18px 16px;background:radial-gradient(120% 90% at 50% -10%, #f1e9ff 0%, var(--bg) 60%);border-bottom:1px solid var(--border)}
.hero .mark{font-family:'Cormorant Garamond',serif;font-size:13px;letter-spacing:5px;text-transform:uppercase;color:var(--accent);font-weight:600}
.hero h1{font-family:'Cormorant Garamond',serif;font-size:40px;font-weight:600;line-height:1.05;letter-spacing:.5px;margin:2px 0 6px;background:linear-gradient(90deg,var(--accent-d),var(--accent-l));-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{color:var(--muted);font-size:14px;font-weight:300}
.hero .count{display:inline-block;margin-top:9px;font-size:12px;color:var(--accent);background:var(--accent-soft);border:1px solid var(--border2);padding:3px 14px;border-radius:30px}
.herocount{text-align:center;margin:16px 0 2px;min-height:26px}
.herocount span{display:inline-block;font-size:13px;font-weight:600;color:var(--accent-d);background:var(--accent-soft);border:1px solid var(--border2);padding:5px 18px;border-radius:30px}
.herocount span:empty{display:none}

/* category nav (primary) */
.catnav{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;padding:14px 16px 6px;max-width:760px;margin:0 auto}
.cat{font-family:var(--font);font-size:14px;font-weight:600;cursor:pointer;padding:9px 20px;border-radius:30px;border:1px solid var(--border2);background:var(--surface);color:var(--text);transition:.18s}
.cat:hover{border-color:var(--accent-l);color:var(--accent-d)}
.cat.active{background:linear-gradient(90deg,var(--accent-d),var(--accent));color:#fff;border-color:transparent;box-shadow:0 4px 14px rgba(124,58,237,.32)}

/* search + autocomplete */
.search-wrap{position:sticky;top:0;z-index:60;background:rgba(250,248,255,.92);backdrop-filter:blur(12px);padding:10px 16px 8px;border-bottom:1px solid var(--border)}
.search{position:relative;max-width:640px;margin:0 auto}
.search input{width:100%;font-size:16px;font-family:var(--font);padding:12px 46px;border:1px solid var(--border2);border-radius:30px;background:var(--surface);color:var(--text);outline:none;transition:.2s;box-shadow:var(--shadow)}
.search input:focus{border-color:var(--accent-l);box-shadow:0 0 0 4px var(--accent-soft)}
.search input::-webkit-search-cancel-button,.search input::-webkit-search-decoration{-webkit-appearance:none;appearance:none;display:none}
.search .ico{position:absolute;right:16px;top:50%;transform:translateY(-50%);color:var(--accent-l);font-size:18px;pointer-events:none}
.search .clr{position:absolute;left:9px;top:50%;transform:translateY(-50%);width:30px;height:30px;border:none;border-radius:50%;background:var(--accent-soft);color:var(--accent-d);font-size:15px;line-height:1;cursor:pointer;display:none;align-items:center;justify-content:center;padding:0}
.search .clr.show{display:flex}
.search .clr:hover{background:var(--accent-l);color:#fff}
.ac{position:absolute;top:calc(100% + 6px);right:0;left:0;background:var(--surface);border:1px solid var(--border2);border-radius:14px;box-shadow:var(--shadow-h);overflow-y:auto;max-height:min(70vh,460px);z-index:70;display:none}
.ac.show{display:block}
.ac-item{display:flex;align-items:center;gap:10px;padding:9px 14px;cursor:pointer;font-size:14px}
.ac-item:hover,.ac-item.hl{background:var(--accent-soft)}
.ac-item .b{font-size:11px;color:var(--accent-l);font-weight:700;text-transform:uppercase}
.ac-item img{width:30px;height:30px;object-fit:contain;border-radius:6px;background:#f4eefe}
.ac-item .ac-nm{display:flex;flex-direction:column;min-width:0;flex:1}
.ac-item .ac-en{font-size:11px;color:var(--muted);font-weight:300;font-style:normal;direction:ltr;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* secondary brand + filters */
.brandnav{display:flex;gap:7px;overflow-x:auto;padding:8px 16px;max-width:960px;margin:0 auto;scrollbar-width:none}
.pill{flex:0 0 auto;font-family:var(--font);font-size:12.5px;font-weight:500;cursor:pointer;padding:6px 14px;border-radius:30px;border:1px solid var(--border2);background:var(--surface);color:var(--text);white-space:nowrap;transition:.18s}
.pill:hover{border-color:var(--accent-l);color:var(--accent-d)}
.pill.active{background:var(--accent);color:#fff;border-color:transparent}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;justify-content:center;padding:2px 16px 8px;max-width:960px;margin:0 auto}
.chip{font-size:12px;font-weight:500;cursor:pointer;padding:6px 12px;border-radius:20px;border:1px solid var(--border2);background:var(--surface);color:var(--muted);transition:.15s}
.chip:hover{color:var(--accent-d)}
.chip.active{background:var(--accent-soft);color:var(--accent-d);border-color:var(--accent-l)}
.chip.favbtn.active{background:#fff0f6;color:#d6336c;border-color:#f0a6c5}
.spacer{flex:1 1 auto;min-width:8px}
select.sort{font-family:var(--font);font-size:12px;color:var(--text);background:var(--surface);border:1px solid var(--border2);border-radius:20px;padding:6px 12px;cursor:pointer;outline:none}

/* grid */
.rescount{max-width:1160px;margin:8px auto 0;padding:0 20px;font-size:12.5px;color:var(--muted);font-weight:500;text-align:right}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:18px;max-width:1160px;margin:8px auto 40px;padding:0 18px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;display:flex;flex-direction:column;cursor:pointer;transition:.22s;position:relative}
.card:hover{transform:translateY(-4px);box-shadow:var(--shadow-h);border-color:var(--border2)}
.card .imgbox{position:relative;aspect-ratio:1/1;background:linear-gradient(160deg,#fbf9ff,#f4eefe);display:flex;align-items:center;justify-content:center;padding:14px}
.card .imgbox img{max-width:100%;max-height:100%;object-fit:contain;mix-blend-mode:multiply}
.ph{font-family:'Cormorant Garamond',serif;font-size:46px;color:var(--accent-l);opacity:.5}
.fav{position:absolute;top:9px;left:9px;z-index:3;width:34px;height:34px;border-radius:50%;border:none;background:rgba(255,255,255,.86);backdrop-filter:blur(4px);cursor:pointer;font-size:16px;line-height:1;display:flex;align-items:center;justify-content:center;color:#c9b8e8;transition:.15s;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.fav:hover{transform:scale(1.12)}.fav.on{color:#e64980}
.bdgs{position:absolute;top:9px;right:9px;z-index:3;display:flex;flex-direction:column;gap:4px;align-items:flex-end}
.bdg{font-size:10px;font-weight:700;color:#fff;padding:2px 8px;border-radius:20px;letter-spacing:.3px;box-shadow:0 2px 6px rgba(0,0,0,.12)}
.bdg.sale{background:#e0245e}.bdg.new{background:var(--lux)}.bdg.bestseller{background:var(--accent)}
.bdg.soldout{background:#6b7280}.bdg.limited{background:#0ea5a3}.bdg.vegan{background:#16a34a}
.card .body{padding:11px 13px 13px;display:flex;flex-direction:column;gap:5px;flex:1}
.card .brand{font-size:10.5px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--accent-l)}
.card .nm{font-size:13.5px;font-weight:500;line-height:1.32;color:var(--text);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:36px}
.card .nm-en{font-size:11px;color:var(--muted);font-weight:300;direction:ltr;text-align:end;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}
.card .meta{display:flex;gap:5px;flex-wrap:wrap}
.tag{font-size:10.5px;font-weight:600;color:var(--accent-d);background:var(--accent-soft);border:1px solid var(--border2);border-radius:6px;padding:1px 7px}
.shrow{display:flex;gap:6px;overflow-x:auto;padding:3px 1px;scrollbar-width:none;align-items:center}
.shrow::-webkit-scrollbar{display:none}
.sw{flex:0 0 auto;width:19px;height:19px;border-radius:50%;border:1.5px solid var(--border2);cursor:pointer;padding:0;transition:.12s;position:relative}
.sw.txt{width:auto;height:auto;border-radius:20px;font-size:10.5px;font-weight:600;padding:2px 8px;background:var(--surface);color:var(--muted);max-width:78px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sw.out{opacity:.4}
.sw.out::after{content:'';position:absolute;inset:-1px;border-radius:inherit;background:linear-gradient(to top left,transparent 45%,#c0392b 45%,#c0392b 55%,transparent 55%);pointer-events:none}
.sw.txt.out{text-decoration:line-through}.sw.txt.out::after{display:none}
.instk{color:#15803d;font-weight:700}
.sw.on{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-soft);transform:scale(1.06)}
.sw.txt.on{background:var(--accent-soft);color:var(--accent-d)}
.nsh{font-size:10.5px;color:var(--accent-l);font-weight:600;align-self:flex-start}
.card .foot{display:flex;align-items:center;justify-content:space-between;margin-top:auto;padding-top:8px}
.price{font-size:17px;font-weight:700;color:var(--text)}
.price .was{font-size:12px;font-weight:500;color:var(--muted);text-decoration:line-through;margin-inline-start:5px}
.price.sale{color:#e0245e}
.add{width:34px;height:34px;border-radius:11px;border:none;cursor:pointer;font-size:20px;line-height:1;color:#fff;background:linear-gradient(135deg,var(--accent),var(--accent-d));box-shadow:0 4px 12px rgba(124,58,237,.3);transition:.15s;touch-action:manipulation}
.add:hover{transform:translateY(-1px) scale(1.05)}
.cardqty{display:flex;align-items:center;border:1px solid var(--accent-l);border-radius:11px;overflow:hidden;background:var(--surface);box-shadow:0 2px 8px rgba(124,58,237,.12)}
.cardqty button{width:30px;height:34px;border:none;background:var(--accent-soft);color:var(--accent-d);font-size:18px;line-height:1;cursor:pointer;touch-action:manipulation;transition:.12s}
.cardqty button:hover{background:var(--accent);color:#fff}
.cardqty span{min-width:28px;text-align:center;font-size:14px;font-weight:700;color:var(--text)}
.cardqin{width:42px;height:34px;border:none;border-inline:1px solid var(--accent-l);text-align:center;font-size:14px;font-weight:700;color:var(--text);background:var(--surface);font-family:var(--font);-moz-appearance:textfield}
.cardqin::-webkit-outer-spin-button,.cardqin::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
.empty{text-align:center;color:var(--muted);padding:70px 20px;font-size:15px}

/* cart bar + back to top */
.cartbar{position:fixed;left:0;right:0;bottom:0;z-index:80;background:rgba(255,255,255,.96);backdrop-filter:blur(14px);border-top:1px solid var(--border2);padding:11px 18px;display:flex;align-items:center;gap:14px;justify-content:center;box-shadow:0 -8px 30px rgba(91,33,182,.1);transform:translateY(120%);transition:.32s cubic-bezier(.2,.8,.2,1)}
.cartbar.show{transform:translateY(0)}
.cartbar .sum{font-weight:500;font-size:14px}.cartbar .sum b{color:var(--accent-d)}
.cartbar button{font-family:var(--font);font-size:14px;font-weight:600;color:#fff;cursor:pointer;border:none;border-radius:30px;padding:11px 26px;background:linear-gradient(90deg,var(--accent-d),var(--accent));box-shadow:0 6px 18px rgba(124,58,237,.34)}
.totop{position:fixed;left:16px;bottom:84px;z-index:70;width:46px;height:46px;border-radius:50%;border:1px solid var(--border2);background:rgba(255,255,255,.94);backdrop-filter:blur(10px);color:var(--accent-d);font-size:22px;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 24px rgba(91,33,182,.18);opacity:0;transform:translateY(14px) scale(.9);pointer-events:none;transition:.25s cubic-bezier(.2,.8,.2,1)}
.totop.show{opacity:1;transform:translateY(0) scale(1);pointer-events:auto}
.totop:hover{background:linear-gradient(135deg,var(--accent),var(--accent-d));color:#fff;border-color:transparent}

/* modals */
.ov{position:fixed;inset:0;z-index:200;background:rgba(30,22,51,.42);backdrop-filter:blur(3px);display:none;align-items:flex-end;justify-content:center}
.ov.open{display:flex}
.sheet{background:var(--surface);width:100%;max-width:560px;max-height:92vh;overflow-y:auto;border-radius:22px 22px 0 0;box-shadow:0 -20px 60px rgba(0,0,0,.22);animation:up .3s cubic-bezier(.2,.8,.2,1)}
@media(min-width:600px){.ov{align-items:center}.sheet{border-radius:22px}}
@keyframes up{from{transform:translateY(40px);opacity:.4}to{transform:translateY(0);opacity:1}}
.sheet .x{position:sticky;top:0;float:left;margin:12px 12px 0 0;width:46px;height:46px;border-radius:50%;border:none;background:var(--accent-soft);color:var(--accent-d);font-size:24px;line-height:1;cursor:pointer;z-index:5;display:flex;align-items:center;justify-content:center;box-shadow:var(--shadow)}
.sheet .x:hover{background:var(--accent-l);color:#fff}
.pd-gal{display:flex;gap:8px;overflow-x:auto;padding:16px 18px 4px;scroll-snap-type:x mandatory}
.pd-gal img{height:220px;width:auto;border-radius:14px;background:#f4eefe;object-fit:contain;scroll-snap-align:center;border:1px solid var(--border);padding:8px;flex:0 0 auto;max-width:88%}
.pd-gal .ph{height:220px;width:220px;display:flex;align-items:center;justify-content:center;background:#f4eefe;border-radius:14px}
.pd{padding:6px 22px 26px}
.pd .b{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--accent-l)}
.pd h2{font-size:21px;font-weight:700;line-height:1.25;margin:3px 0 2px}
.pd .en{font-size:13px;color:var(--muted);font-weight:300;margin-bottom:8px}
.pd .row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
.pd .row .tag{font-size:12px;padding:3px 11px}
.pd .pr{font-size:26px;font-weight:700;color:var(--accent-d);margin:8px 0 2px}
.pd .pr-cons{font-size:13.5px;color:var(--muted);font-weight:500;margin:0 0 12px}
.pricewrap{display:flex;flex-direction:column;min-width:0}
.price-cons{font-size:10.5px;color:var(--muted);font-weight:500;line-height:1.2;margin-top:1px;white-space:nowrap}
.pd .pr .was{font-size:15px;color:var(--muted);text-decoration:line-through;margin-inline-start:8px;font-weight:500}
.pd-shades{margin:6px 0 4px}
.pd-shades .lbl{font-size:12px;font-weight:600;color:var(--muted);margin-bottom:6px}
.pd-sw{display:flex;gap:7px;flex-wrap:wrap}
.pd-sw button{font-family:var(--font);font-size:12px;font-weight:600;padding:6px 12px;border-radius:20px;border:1px solid var(--border2);background:var(--surface);color:var(--text);cursor:pointer;transition:.12s}
.pd-sw button.out{opacity:.5;text-decoration:line-through;border-style:dashed}
.pd-sw button.on{background:var(--accent);color:#fff;border-color:transparent}
.pd-sw .dot{display:inline-block;width:13px;height:13px;border-radius:50%;border:1px solid rgba(0,0,0,.12);margin-inline-end:6px;vertical-align:middle}
.pd h4{font-size:13px;font-weight:700;color:var(--accent-d);margin:16px 0 5px;padding-bottom:5px;border-bottom:1px solid var(--border)}
.pd p,.pd li{font-size:13.5px;line-height:1.6;color:#473d5e;font-weight:300}
.pd ul{padding-right:18px;margin-top:4px}
.pd .barc{font-size:12px;color:var(--muted);margin-top:14px;font-family:monospace;direction:ltr;text-align:right}
.pd .cta{width:100%;margin-top:18px;font-family:var(--font);font-size:16px;font-weight:600;color:#fff;border:none;border-radius:14px;padding:14px;cursor:pointer;background:linear-gradient(90deg,var(--accent-d),var(--accent));box-shadow:0 8px 22px rgba(124,58,237,.3)}
.pdfav{display:inline-flex;align-items:center;gap:7px;font-family:var(--font);font-size:13.5px;font-weight:600;cursor:pointer;border:1px solid var(--border2);background:var(--surface);color:var(--accent-d);border-radius:30px;padding:8px 16px;margin:2px 0 6px;transition:.15s}
.pdfav:hover{border-color:var(--accent-l)}.pdfav .h{color:#c9b8e8;font-size:15px}.pdfav.on{background:#fff0f6;border-color:#f0a6c5;color:#d6336c}.pdfav.on .h{color:#e64980}
.sim{margin-top:22px}
.sim h4{font-size:13px;font-weight:700;color:var(--accent-d);margin-bottom:9px;padding-bottom:5px;border-bottom:1px solid var(--border)}
.sim-row{display:flex;gap:10px;overflow-x:auto;scrollbar-width:none;padding-bottom:4px}
.sim-row::-webkit-scrollbar{display:none}
.sim-card{flex:0 0 96px;cursor:pointer}
.sim-card .si{width:96px;height:96px;border-radius:12px;background:#f4eefe;border:1px solid var(--border);display:flex;align-items:center;justify-content:center;padding:7px}
.sim-card img{max-width:100%;max-height:100%;object-fit:contain;mix-blend-mode:multiply}
.sim-card .sn{font-size:10.5px;line-height:1.25;color:var(--text);margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sim-card .sp{font-size:11.5px;font-weight:700;color:var(--accent-d)}

/* order modal */
.om{padding:8px 20px 24px}
.om h3{font-size:20px;font-weight:700;margin:6px 0 14px;text-align:center}
.om-row{display:flex;align-items:center;gap:10px;padding:11px 0;border-bottom:1px solid var(--border)}
.om-row .nm{flex:1;font-size:13.5px;font-weight:500}
.om-row .nm small{display:block;color:var(--muted);font-weight:300;font-size:11.5px}
.qy{display:flex;align-items:center;border:1px solid var(--border2);border-radius:10px;overflow:hidden}
.qy button{width:30px;height:30px;border:none;background:var(--accent-soft);color:var(--accent-d);font-size:17px;cursor:pointer;touch-action:manipulation}
.qy span{min-width:28px;text-align:center;font-size:14px;font-weight:600}
.qy .qin{width:48px;height:30px;border:none;border-inline:1px solid var(--border2);text-align:center;font-size:14px;font-weight:600;font-family:var(--font);background:#fff;-moz-appearance:textfield}
.qy .qin::-webkit-outer-spin-button,.qy .qin::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
.om-row .lt{min-width:62px;text-align:left;font-weight:700;font-size:14px;direction:ltr}
.om-del{border:none;background:none;color:#c9b8e8;font-size:16px;cursor:pointer}
.coupon{display:flex;gap:8px;margin:16px 0 6px}
.coupon input{flex:1;font-family:var(--font);font-size:16px;padding:11px 14px;border:1px solid var(--border2);border-radius:12px;outline:none;background:var(--surface)}
.coupon button{font-family:var(--font);font-weight:600;font-size:14px;border:1px solid var(--accent-l);background:var(--accent-soft);color:var(--accent-d);border-radius:12px;padding:0 18px;cursor:pointer}
.cmsg{font-size:12.5px;font-weight:500;min-height:18px;margin-bottom:6px}
.cmsg.ok{color:#15803d}.cmsg.err{color:#dc2626}
.totals{margin-top:10px;font-size:14px}
.totals .l{display:flex;justify-content:space-between;padding:4px 0;color:var(--muted)}
.totals .l.grand{font-size:19px;font-weight:700;color:var(--text);border-top:1px solid var(--border);margin-top:6px;padding-top:10px}
.totals .l.grand b{color:var(--accent-d)}
.form{margin-top:16px;display:flex;flex-direction:column;gap:9px}
.form h4{font-size:13px;font-weight:700;color:var(--accent-d);margin-bottom:1px;padding-bottom:6px;border-bottom:1px solid var(--border)}
.fld,.notes{width:100%;font-family:var(--font);font-size:16px;padding:11px 13px;border-radius:11px;border:1px solid var(--border2);outline:none;background:var(--surface);color:var(--text)}
.notes{resize:vertical;min-height:58px}
.fld:focus,.notes:focus{border-color:var(--accent-l);box-shadow:0 0 0 3px var(--accent-soft)}
.send{width:100%;margin-top:14px;font-family:var(--font);font-size:16px;font-weight:700;color:#fff;border:none;border-radius:14px;padding:15px;cursor:pointer;background:linear-gradient(90deg,#16a34a,#15803d);box-shadow:0 8px 22px rgba(22,163,74,.28)}
.send.pay{background:linear-gradient(90deg,var(--accent-d),var(--accent));box-shadow:0 8px 22px rgba(124,58,237,.3)}
.send:disabled{opacity:.6;cursor:progress}
.soldpill{font-size:12px;font-weight:700;color:#b91c1c;background:#fee2e2;border-radius:9px;padding:6px 10px;white-space:nowrap}
.hint{font-size:11.5px;color:var(--muted);text-align:center;margin-top:8px}

@media(max-width:480px){
  .hero{padding:24px 14px 14px}.hero h1{font-size:28px;letter-spacing:0}.hero p{font-size:12.5px}
  .cat{font-size:13px;padding:8px 16px}
  .grid{grid-template-columns:repeat(2,1fr);gap:11px;padding:0 12px;margin-top:10px}
  .card .nm{font-size:12.5px;min-height:33px}.price{font-size:15.5px}
}
.sitefooter{margin-top:40px;padding:26px 18px 28px;background:#1e1633;color:#cfc7e0;border-top:3px solid var(--accent)}
.sitefooter .fdisc{max-width:1000px;margin:0 auto 20px;text-align:center;font-size:12.5px;color:#b7add0;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:10px 16px}
.sitefooter .fcols{max-width:1000px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:24px}
.sitefooter h4{font-size:14px;color:#fff;margin-bottom:10px;font-weight:700}
.sitefooter p{font-size:13px;line-height:1.7;margin:2px 0;color:#cfc7e0}
.sitefooter a{color:#e9c7ff;text-decoration:none}
.sitefooter .flink{display:block;background:none;border:none;color:#cfc7e0;font-family:var(--font);font-size:13px;padding:4px 0;cursor:pointer;text-align:start}
.sitefooter .flink:hover{color:#fff;text-decoration:underline}
.sitefooter .fwa{display:inline-block;margin-top:8px;background:#25d366;color:#062b13;font-weight:700;font-size:13px;padding:8px 16px;border-radius:30px}
.sitefooter .fcopy{max-width:1000px;margin:22px auto 0;text-align:center;font-size:12px;color:#8b85a0;border-top:1px solid rgba(255,255,255,.1);padding-top:14px}
@media(max-width:640px){.sitefooter .fcols{grid-template-columns:1fr;gap:18px;text-align:center}.sitefooter .flink{text-align:center}}
.policy{padding:8px 26px 26px;line-height:1.75}
.policy h2{font-family:'Cormorant Garamond',serif;font-size:26px;color:var(--accent-d);margin-bottom:4px}
.policy .note{font-size:12px;color:var(--muted);background:var(--accent-soft);border-radius:10px;padding:8px 12px;margin:8px 0 16px}
.policy h3{font-size:15px;color:var(--text);margin:16px 0 4px}
.policy p,.policy li{font-size:14px;color:var(--text);margin:4px 0}
.policy ul{padding-inline-start:20px}
.bndl{display:flex;flex-direction:column;gap:7px;margin-top:6px}
.bndl details{border:1px solid var(--border2);border-radius:12px;background:var(--surface);overflow:hidden}
.bndl summary{cursor:pointer;padding:11px 14px;font-size:14px;font-weight:500;color:var(--accent-d);list-style:none;display:flex;align-items:center;justify-content:space-between;gap:8px}
.bndl summary::-webkit-details-marker{display:none}
.bndl summary::after{content:'+';font-size:18px;color:var(--accent-l);font-weight:400}
.bndl details[open] summary::after{content:'−'}
.bndl details[open] summary{border-bottom:1px solid var(--border)}
.bndl details p{padding:10px 14px 13px;font-size:13.5px;line-height:1.65;color:var(--text);margin:0}
.policybar{display:flex;flex-wrap:wrap;justify-content:center;gap:5px 14px;max-width:640px;margin:8px auto 0}
.policybar .plink{background:none;border:none;color:var(--muted);font-family:var(--font);font-size:12px;cursor:pointer;padding:1px 0;white-space:nowrap}
.policybar .plink:hover{color:var(--accent);text-decoration:underline}
@media(max-width:640px){.policybar{gap:4px 10px}.policybar .plink{font-size:11.5px}}
#pbWholesale{color:var(--accent);font-weight:600}
.wsbanner{display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;
  background:var(--accent);color:#fff;font-size:13px;font-weight:600;padding:8px 16px;text-align:center}
.wsbanner button{background:rgba(255,255,255,.22);border:1px solid rgba(255,255,255,.5);color:#fff;
  font-family:var(--font);font-size:12.5px;font-weight:600;padding:4px 12px;border-radius:999px;cursor:pointer}
.wsbanner button:hover{background:rgba(255,255,255,.34)}
</style>
</head>
<body>
<div class="brandbar">
  <img src="logo.svg" alt="Beauty Favorites" width="150" height="63" onclick="goTop()" style="cursor:pointer">
  <button class="langbtn" id="langBtn" onclick="toggleLang()" aria-label="Language">العربية</button>
</div>
<header class="herobanner">
  <div class="hero-inner">
    <div class="hero-kicker">Beauty &middot; Curated</div>
    <h1 class="hero-title">Beauty Favorites</h1>
    <div class="hero-line"></div>
    <p class="hero-sub" id="heroSub">הקולקציה הנבחרת — איפור · טיפוח · שיער · בושם</p>
  </div>
</header>

<div class="herocount"><span id="heroCount"></span></div>
<nav class="catnav" id="catnav"></nav>

<div class="search-wrap">
  <div class="search">
    <span class="ico">⌕</span>
    <input id="q" type="search" autocomplete="off" placeholder="חיפוש מוצר, מותג או ברקוד…" oninput="onSearch()" onkeydown="acKey(event)">
    <button class="clr" id="clrBtn" type="button" onclick="clearSearch()" aria-label="נקה חיפוש" title="נקה">✕</button>
    <div class="ac" id="ac" role="listbox"></div>
  </div>
  <div class="policybar">
    <button class="plink" onclick="openPolicy('contact')" id="pbBiz">פרטי העסק</button>
    <button class="plink" onclick="openPolicy('shipping')" id="pbShip">משלוחים</button>
    <button class="plink" onclick="openPolicy('returns')" id="pbRet">החזרות</button>
    <button class="plink" onclick="openPolicy('terms')" id="pbTerms">תקנון</button>
    <button class="plink" onclick="openPolicy('privacy')" id="pbPriv">פרטיות</button>
    <button class="plink" onclick="openWholesale()" id="pbWholesale">🔑 כניסת סיטונאי</button>
  </div>
</div>
<div class="wsbanner" id="wsBanner" style="display:none">
  <span id="wsBannerTxt">מצב סיטונאי פעיל — מוצגים מחירי סיטונאי</span>
  <button onclick="wholesaleLogout()">יציאה</button>
</div>

<nav class="brandnav" id="brandnav"></nav>
<div class="toolbar" id="prices"></div>
<div class="toolbar">
  <button class="chip favbtn" id="favchip" onclick="toggleFavOnly()">♥ המועדפים שלי</button>
  <button class="chip" id="resetchip" onclick="resetFilters()">↺ נקה הכל</button>
  <span class="spacer"></span>
  <select class="sort" id="sort" onchange="render()">
    <option value="default">מיון: מומלץ</option>
    <option value="price-asc">מחיר: מהנמוך לגבוה</option>
    <option value="price-desc">מחיר: מהגבוה לנמוך</option>
    <option value="name">שם: א׳–ת׳</option>
  </select>
</div>

<div class="rescount" id="rescount"></div>
<main class="grid" id="grid"></main>

<footer class="sitefooter">
  <div class="fdisc" id="fDisc">מכירה עצמאית של מוצרים מקוריים · כל הסימנים המסחריים שייכים לבעליהם</div>
  <div class="fcols">
    <div class="fcol">
      <h4 id="fBizT">פרטי העסק</h4>
      <p>שניר שריקי – יבוא ושיווק מותגי שיער וקוסמטיקה</p>
      <p>עוסק מורשה: 040553562</p>
      <p>טלפון: <a href="tel:0534555501">053-4555501</a></p>
      <p>אימייל: <a href="mailto:saphrafavorites@gmail.com">saphrafavorites@gmail.com</a></p>
      <p id="fVat">המחירים כוללים מע״מ · משלוחים לכל הארץ</p>
    </div>
    <div class="fcol">
      <h4 id="fInfoT">מידע ומדיניות</h4>
      <button class="flink" onclick="openPolicy('shipping')" id="fShip">משלוחים ואספקה</button>
      <button class="flink" onclick="openPolicy('returns')" id="fRet">החזרות וביטולים</button>
      <button class="flink" onclick="openPolicy('terms')" id="fTerms">תקנון</button>
      <button class="flink" onclick="openPolicy('privacy')" id="fPriv">מדיניות פרטיות</button>
    </div>
    <div class="fcol">
      <h4 id="fOrderT">הזמנות</h4>
      <p id="fShipFree">משלוח חינם בהזמנה מעל ₪299</p>
      <p id="fEta">אספקה עד 72 שעות מרגע איסוף ע״י השליח</p>
      <a class="fwa" href="https://wa.me/972547599923" id="fWa">הזמנה בוואטסאפ</a>
    </div>
  </div>
  <div class="fcopy">© שניר שריקי · Beauty Favorites</div>
</footer>

<div class="cartbar" id="cartbar">
  <span class="sum" id="cartsum"></span>
  <button id="viewOrderBtn" onclick="openOrder()">צפה בהזמנה ←</button>
</div>
<button class="totop" id="toTop" onclick="goTop()" aria-label="חזרה למעלה" title="חזרה למעלה">↑</button>

<div class="ov" id="pdModal"><div class="sheet"><button class="x" onclick="closePd()">✕</button><div id="pdContent"></div></div></div>

<div class="ov" id="orderModal"><div class="sheet">
  <button class="x" onclick="closeOrder()">✕</button>
  <div class="om">
    <h3 id="omTitle">ההזמנה שלי</h3>
    <div id="omBody"></div>
    <div class="coupon"><input id="coupon" type="text" placeholder="קוד קופון" oninput="applyCoupon()"><button id="couponBtn" onclick="applyCoupon()">החל</button></div>
    <div class="cmsg" id="cmsg"></div>
    <div class="totals" id="totals"></div>
    <div class="form">
      <h4 id="buyerTitle">פרטי המזמין</h4>
      <input class="fld" id="buyer-name" type="text" placeholder="שם מלא *">
      <input class="fld" id="buyer-biz" type="text" placeholder="שם העסק / החנות (לחשבונית)">
      <input class="fld" id="buyer-id" type="text" placeholder="מספר עוסק מורשה / ח.פ / ת.ז">
      <input class="fld" id="buyer-addr" type="text" placeholder="עיר וכתובת למשלוח">
      <input class="fld" id="buyer-phone" type="tel" placeholder="טלפון *">
      <textarea class="notes" id="notes" placeholder="הערות להזמנה (אופציונלי)…"></textarea>
    </div>
    <button class="send pay" id="payBtn" onclick="payNow()" style="display:none">שלם עכשיו 💳</button>
    <button class="send" id="sendBtn" onclick="submitWhatsApp()">שלח הזמנה לאישור (וואטסאפ)</button>
    <div class="hint" id="sendHint">ההזמנה תיפתח ב-WhatsApp עם מספר ההזמנה</div>
  </div>
</div></div>

<div class="ov" id="policyModal"><div class="sheet"><button class="x" onclick="closeOv('policyModal')">✕</button><div class="policy" id="policyBody"></div></div></div>

<div class="ov" id="wsModal"><div class="sheet"><button class="x" onclick="closeOv('wsModal')">✕</button>
  <div class="om">
    <h3 id="wsTitle">כניסת סיטונאי</h3>
    <p class="muted" id="wsSub" style="margin:2px 0 12px">הזן קוד סיטונאי כדי לראות מחירי סיטונאי.</p>
    <input class="fld" id="wsCode" type="text" placeholder="קוד סיטונאי" autocomplete="off" onkeydown="if(event.key==='Enter')submitWholesale()">
    <div class="cmsg" id="wsMsg"></div>
    <button class="send" id="wsGo" onclick="submitWholesale()">כניסה</button>
  </div>
</div></div>

<script>
const GROUPS = /*__GROUPS__*/;
const BRAND_ALIASES={
 "Dior":"דיור","DIOR":"דיור","דיור (Dior)":"דיור",
 "YSL":"ייב סן לורן","איב סן לורן":"ייב סן לורן","Yves Saint Laurent":"ייב סן לורן",
 "M.A.C":"MAC","Mac":"MAC",
 "Makeup for ever":"מייק אפ פור אבר","Make Up For Ever":"מייק אפ פור אבר","מייקאפ פוראבר":"מייק אפ פור אבר",
 "וואן סייז":"ONE/SIZE","וואן סайז (ONE/SIZE)":"ONE/SIZE",
 "RHODE":"Rhode","רואד":"Rhode","רואד (RHODE)":"Rhode","רוד":"Rhode",
 "Ordinary":"The Ordinary","Saie":"SAIE","סאיי":"SAIE",
 "SEPHORA":"ספורה","Sephora Collection":"ספורה","אוארגלאס":"האורגלאס",
 "Charlotte Tilbury":"שרלוט טילבורי","Charlotte Tilbury Beauty":"שרלוט טילבורי"
};
function canonBrand(b){return BRAND_ALIASES[b]||b||'אחר';}
GROUPS.forEach(g=>{g.brand=canonBrand(g.brand);});
GROUPS.forEach((g,i)=>{g._i=i; g.minp=Math.min(...g.variants.map(eff)); g._noimg=g.variants.every(v=>!v.imgs||!v.imgs.length);});

/* ===== i18n: UI language toggle (HE / AR). The WhatsApp order text stays Hebrew always. ===== */
const I18N={
 he:{search_ph:'חיפוש מוצר, מותג או ברקוד…',fav_only:'המועדפים שלי',in_stock:'נמצא במלאי',in_stock_short:'במלאי',reset_all:'נקה הכל',cons_rec:'מומלץ לצרכן:',
  sort_default:'מיון: מומלץ',sort_pa:'מחיר: מהנמוך לגבוה',sort_pd:'מחיר: מהגבוה לנמוך',sort_name:'שם: א׳–ת׳',
  all:'הכל',all_brands:'כל המותגים',all_prices:'כל המחירים',
  p_u50:'עד ₪50',p_50_100:'₪50–100',p_100_200:'₪100–200',p_200p:'₪200+',
  items:'מוצרים',in_stock_count:'מוצרים במלאי',cart_items:'פריטים',empty:'לא נמצאו מוצרים מתאימים 🔍',
  view_order:'צפה בהזמנה ←',totop:'חזרה למעלה',
  c_איפור:'איפור',c_טיפוח:'טיפוח',c_שיער:'שיער',c_בושם:'בושם',c_מארזים:'מארזים',c_ציפורניים:'ציפורניים',c_אביזרים:'אביזרים',c_ציוד:'ציוד',c_אחר:'אחר',
  b_sale:'מבצע',b_new:'חדש',b_bestseller:'רב-מכר',b_soldout:'אזל',b_limited:'מהדורה מוגבלת',b_vegan:'טבעוני',
  shades:'גוונים',feats:'מאפיינים עיקריים',ingredients:'רכיבים',usage:'אופן שימוש',contents_h:'מה כלול במבחר',
  pick_shade:'בחר גוון',similar:'מוצרים דומים',desc:'תיאור',barcode:'ברקוד:',
  add_order:'הוסף להזמנה',fav_remove:'במועדפים — הסר',fav_add:'הוסף למועדפים',
  my_order:'ההזמנה שלי',coupon_ph:'קוד קופון',apply:'החל',buyer_details:'פרטי המזמין',
  full_name:'שם מלא *',biz_name:'שם העסק / החנות (לחשבונית)',biz_id:'מספר עוסק מורשה / ח.פ / ת.ז',
  ship_addr:'עיר וכתובת למשלוח',phone:'טלפון *',notes_ph:'הערות להזמנה (אופציונלי)…',
  send_order:'שלח הזמנה לאישור (וואטסאפ)',send_hint:'ההזמנה תיפתח ב-WhatsApp עם מספר ההזמנה',
  pay_now:'שלם עכשיו 💳',sold_out:'אזל',sending:'שולח…',err_order:'אירעה תקלה ביצירת ההזמנה. נסה שוב.',
  cart_empty:'העגלה ריקה',subtotal:'סכום ביניים',discount:'הנחה',vat:'מע"מ 18%',grand:'סה"כ לתשלום',
  coupon_ok:'✓ קופון הוחל: ',coupon_bad:'קוד קופון לא תקין',off:'הנחה',
  ws_enter:'🔑 כניסת סיטונאי',ws_exit:'יציאה ממצב סיטונאי',ws_title:'כניסת סיטונאי',ws_sub:'הזן קוד סיטונאי כדי לראות מחירי סיטונאי.',ws_ph:'קוד סיטונאי',ws_go:'כניסה',ws_bad:'קוד שגוי',ws_unavailable:'לא זמין כרגע',ws_active:'מצב סיטונאי פעיל — מוצגים מחירי סיטונאי',
  alert_empty:'העגלה ריקה',alert_fill:'נא למלא שם מלא וטלפון לפני שליחת ההזמנה',other:'العربية',
  f_disc:'מכירה עצמאית של מוצרים מקוריים · כל הסימנים המסחריים שייכים לבעליהם',
  hero_sub:'הקולקציה הנבחרת — איפור · טיפוח · שיער · בושם',
  f_biz:'פרטי העסק',f_vat:'המחירים כוללים מע״מ · משלוחים לכל הארץ',f_info:'מידע ומדיניות',
  f_ship:'משלוחים ואספקה',f_ret:'החזרות וביטולים',f_terms:'תקנון',f_priv:'מדיניות פרטיות',
  f_order:'הזמנות',f_free:'משלוח חינם בהזמנה מעל ₪299',f_eta:'אספקה עד 72 שעות מרגע איסוף ע״י השליח',f_wa:'הזמנה בוואטסאפ',
  pb_ship:'משלוחים',pb_ret:'החזרות',pb_priv:'פרטיות'},
 ar:{search_ph:'ابحث عن منتج، ماركة أو باركود…',fav_only:'المفضلة لديّ',in_stock:'متوفر',in_stock_short:'متوفر',reset_all:'مسح الكل',cons_rec:'موصى للمستهلك:',
  sort_default:'الترتيب: موصى به',sort_pa:'السعر: من الأقل للأعلى',sort_pd:'السعر: من الأعلى للأقل',sort_name:'الاسم: أ–ي',
  all:'الكل',all_brands:'كل الماركات',all_prices:'كل الأسعار',
  p_u50:'حتى ₪50',p_50_100:'₪50–100',p_100_200:'₪100–200',p_200p:'₪200+',
  items:'منتج',in_stock_count:'منتجات متوفرة',cart_items:'عناصر',empty:'لم يتم العثور على منتجات مطابقة 🔍',
  view_order:'عرض الطلب ←',totop:'العودة للأعلى',
  c_איפור:'مكياج',c_טיפוח:'العناية بالبشرة',c_שיער:'العناية بالشعر',c_בושם:'عطر',c_מארזים:'مجموعات',c_ציפורניים:'العناية بالأظافر',c_אביזרים:'إكسسوارات',c_ציוד:'معدات',c_אחר:'أخرى',
  b_sale:'تخفيض',b_new:'جديد',b_bestseller:'الأكثر مبيعاً',b_soldout:'نفد',b_limited:'إصدار محدود',b_vegan:'نباتي',
  shades:'ألوان',feats:'أبرز المزايا',ingredients:'المكوّنات',usage:'طريقة الاستخدام',contents_h:'ما الذي تشمله التشكيلة',
  pick_shade:'اختر اللون',similar:'منتجات مشابهة',desc:'الوصف',barcode:'باركود:',
  add_order:'أضف إلى الطلب',fav_remove:'في المفضلة — إزالة',fav_add:'أضف إلى المفضلة',
  my_order:'طلبي',coupon_ph:'رمز الكوبون',apply:'تطبيق',buyer_details:'تفاصيل مقدّم الطلب',
  full_name:'الاسم الكامل *',biz_name:'اسم العمل / المتجر (للفاتورة)',biz_id:'رقم السجل التجاري / الهوية',
  ship_addr:'المدينة والعنوان للتوصيل',phone:'الهاتف *',notes_ph:'ملاحظات على الطلب (اختياري)…',
  send_order:'إرسال الطلب للموافقة (واتساب)',send_hint:'سيُفتح الطلب في WhatsApp مع رقم الطلب',
  pay_now:'ادفع الآن 💳',sold_out:'نفد',sending:'جارٍ الإرسال…',err_order:'حدث خطأ في إنشاء الطلب. حاول مرة أخرى.',
  cart_empty:'السلة فارغة',subtotal:'المجموع الفرعي',discount:'خصم',vat:'ضريبة 18%',grand:'الإجمالي للدفع',
  coupon_ok:'✓ تم تطبيق الكوبون: ',coupon_bad:'رمز كوبون غير صالح',off:'خصم',
  ws_enter:'🔑 دخول الجملة',ws_exit:'الخروج من وضع الجملة',ws_title:'دخول الجملة',ws_sub:'أدخل رمز الجملة لرؤية أسعار الجملة.',ws_ph:'رمز الجملة',ws_go:'دخول',ws_bad:'رمز غير صحيح',ws_unavailable:'غير متاح حالياً',ws_active:'وضع الجملة مُفعّل — تُعرض أسعار الجملة',
  alert_empty:'السلة فارغة',alert_fill:'يرجى تعبئة الاسم الكامل والهاتف قبل إرسال الطلب',other:'עברית',
  f_disc:'بيع مستقل لمنتجات أصلية · جميع العلامات التجارية ملك لأصحابها',
  hero_sub:'التشكيلة المختارة — مكياج · عناية · شعر · عطر',
  f_biz:'تفاصيل العمل',f_vat:'الأسعار تشمل الضريبة · توصيل لكل البلاد',f_info:'معلومات وسياسات',
  f_ship:'الشحن والتوصيل',f_ret:'الإرجاع والإلغاء',f_terms:'شروط الاستخدام',f_priv:'سياسة الخصوصية',
  f_order:'الطلبات',f_free:'توصيل مجاني للطلبات فوق ₪299',f_eta:'التوصيل خلال 72 ساعة من استلام المندوب للطرد',f_wa:'اطلب عبر واتساب',
  pb_ship:'الشحن',pb_ret:'الإرجاع',pb_priv:'الخصوصية'}
};
let LANG=localStorage.getItem('sf_lang')||'he';
function t(k){return (I18N[LANG]&&I18N[LANG][k]!=null)?I18N[LANG][k]:(I18N.he[k]!=null?I18N.he[k]:k);}
function catLabel(c){return t('c_'+c)||c;}
function setText(id,v){var e=document.getElementById(id);if(e)e.textContent=v;}
function setPh(id,v){var e=document.getElementById(id);if(e)e.placeholder=v;}
function applyStatic(){
  document.documentElement.lang=LANG;
  setPh('q',t('search_ph'));
  var fc=document.getElementById('favchip');if(fc)fc.innerHTML='♥ '+t('fav_only');
  var rc=document.getElementById('resetchip');if(rc)rc.innerHTML='↺ '+t('reset_all');
  var so=document.getElementById('sort');if(so){so.options[0].text=t('sort_default');so.options[1].text=t('sort_pa');so.options[2].text=t('sort_pd');so.options[3].text=t('sort_name');}
  setText('viewOrderBtn',t('view_order'));
  var tt=document.getElementById('toTop');if(tt){tt.title=t('totop');tt.setAttribute('aria-label',t('totop'));}
  setText('omTitle',t('my_order'));setPh('coupon',t('coupon_ph'));setText('couponBtn',t('apply'));
  setText('buyerTitle',t('buyer_details'));
  setPh('buyer-name',t('full_name'));setPh('buyer-biz',t('biz_name'));setPh('buyer-id',t('biz_id'));
  setPh('buyer-addr',t('ship_addr'));setPh('buyer-phone',t('phone'));setPh('notes',t('notes_ph'));
  setText('sendBtn',t('send_order'));setText('sendHint',t('send_hint'));setText('payBtn',t('pay_now'));
  setText('heroSub',t('hero_sub'));
  setText('fDisc',t('f_disc'));setText('fBizT',t('f_biz'));setText('fVat',t('f_vat'));setText('fInfoT',t('f_info'));
  setText('fShip',t('f_ship'));setText('fRet',t('f_ret'));setText('fTerms',t('f_terms'));setText('fPriv',t('f_priv'));
  setText('fOrderT',t('f_order'));setText('fShipFree',t('f_free'));setText('fEta',t('f_eta'));setText('fWa',t('f_wa'));
  setText('pbBiz',t('f_biz'));setText('pbShip',t('pb_ship'));setText('pbRet',t('pb_ret'));setText('pbTerms',t('f_terms'));setText('pbPriv',t('pb_priv'));
  setText('wsTitle',t('ws_title'));setText('wsSub',t('ws_sub'));setPh('wsCode',t('ws_ph'));setText('wsGo',t('ws_go'));setText('wsBannerTxt',t('ws_active'));
  updateWsUI();
  var lb=document.getElementById('langBtn');if(lb)lb.textContent=t('other');
}
function toggleLang(){LANG=(LANG==='he')?'ar':'he';localStorage.setItem('sf_lang',LANG);applyLang();}
function applyLang(){applyStatic();buildNav();render();renderCart();
  if(document.getElementById('orderModal').classList.contains('open'))renderOrder();}

// brand prestige tiers (1 = luxury/prestige … 4 = generic) for the default "מומלץ" sort
const PRESTIGE={
 "דיור":1,"שאנל":1,"ייב סן לורן":1,"YSL":1,"ארמני":1,"ז'יבנשי":1,"גוצ'י":1,"ולנטינו":1,"Bond No. 9":1,
 "אסתי לאודר":1,"לנקום":1,"קלרינס":1,"קליניק":1,"לורה מרסייה":1,"בובי בראון":1,"האורגלאס":1,"נארס":1,
 "שרלוט טילבורי":1,"נטשה דנונה":1,"פט מקגראת'":1,"טאצ'ה":1,"דראנק אלפנט":1,"קילס":1,"לה רוש פוזה":1,
 "קודלי":1,"וישי":1,"לנייג'":1,"איט קוסמטיקס":1,"מייק אפ פור אבר":1,"פיטר תומאס רות'":1,"דרמלוגיקה":1,
 "פנטי ביוטי":2,"ריר ביוטי":2,"אנסטסיה בברלי הילס":2,"הודה ביוטי":2,"בנפיט":2,"טו פייסד":2,"טארט":2,
 "קוסאס":2,"מייקאפ ביי מריו":2,"דנסה מיריקס":2,"Rhode":2,"סאמר פריידייז":2,"Glow Recipe":2,"ONE/SIZE":2,
 "מילק מייקאפ":2,"פטריק טא":2,"סמאשבוקס":2,"אורבן דקיי":2,"MAC":2,"אולפלקס":2,"K18":2,"Gisou":2,"סול דה ז'נרו":2,"מורפי":2,
 "מייבלין":3,"לוריאל":3,"NYX":3,"מילאני":3,"קאברגירל":3,"אי.אל.אף":3,"פיקסי":3,"קולורפופ":3,"קיילי קוסמטיקס":3,"ריאל טכניקס":3,"שוורצקופף":3,"רבלון":3,"גרנייה":3,
};
function prestige(b){return PRESTIGE[b]||4;}
const VMAP={}; GROUPS.forEach(g=>g.variants.forEach(v=>{VMAP[v.id]={g,v};}));
function eff(v){var p=STOCK_READY?priceMap()[nbc(v.barcode)]:undefined;return (p!=null&&p>0)?p:((v.sale&&v.sale>0)?v.sale:v.price);}

const BADGE_LABEL={sale:'מבצע',new:'חדש',bestseller:'רב-מכר',soldout:'אזל',limited:'מהדורה מוגבלת',vegan:'טבעוני'};
const BADGE_ORDER=['sale','bestseller','new','limited','soldout','vegan'];

const CATS=['איפור','טיפוח','שיער','בושם','מארזים','ציפורניים','אביזרים','ציוד'].filter(t=>GROUPS.some(g=>g.type===t));
// קטגוריות להצגה: רק כאלה עם מוצר במלאי (עד שהמלאי נטען — כולן)
function catsInStock(){
  if(!STOCK_READY)return CATS;
  return CATS.filter(c=>GROUPS.some(g=>g.type===c&&g.variants.some(v=>STOCK[nbc(v.barcode)]>0)));
}
const BRANDS=(()=>{const c={};GROUPS.forEach(g=>c[g.brand]=(c[g.brand]||0)+1);
  return Object.keys(c).sort((a,b)=>a==='אחר'?1:b==='אחר'?-1:c[b]-c[a]);})();
// מותגים להצגה: רק כאלה עם מוצר במלאי (עד שהמלאי נטען — כולם)
function brandsInStock(){
  if(!STOCK_READY)return BRANDS;
  return BRANDS.filter(b=>GROUPS.some(g=>g.brand===b&&g.variants.some(v=>STOCK[nbc(v.barcode)]>0)));
}
const PRICES=[{l:'עד ₪50',mn:0,mx:50},{l:'₪50–100',mn:50,mx:100},{l:'₪100–200',mn:100,mx:200},{l:'₪200+',mn:200,mx:1e9}];

let curCat='__all__',curBrand='__all__',curPrice=-1,favOnly=false,inStockOnly=false;
const sel={};   // gid -> variant index
const FAVS=new Set(JSON.parse(localStorage.getItem('sf_favs')||'[]'));
function saveFavs(){localStorage.setItem('sf_favs',JSON.stringify([...FAVS]))}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function aesc(s){return String(s).replace(/"/g,'&quot;')}
function imgErr(img){img.style.display='none';const ph=document.createElement('div');ph.className='ph';ph.textContent=img.dataset.l||'✦';img.parentNode.appendChild(ph)}
// default displayed variant = first IN-STOCK shade (so the card never defaults to a sold-out shade)
function defaultV(g){
  if(STOCK_READY){
    var f=g.variants.findIndex(function(v){return STOCK[nbc(v.barcode)]>0;});
    if(f>=0)return f;
    var d=g.variants.findIndex(inDB);
    if(d>=0)return d;
  }
  return 0;
}
function curIdx(g){var s=sel[g.gid];return s!=null?s:defaultV(g);}
function selV(g){return g.variants[curIdx(g)];}
function swPill(v,on,oc){
  var so=isSold(v), oc2=so?'out':'', tip=aesc(v.shade)+(so?' — '+t('sold_out'):'');
  if(v.color)return `<button class="sw ${on?'on':''} ${oc2}" style="background:${v.color}" title="${tip}" aria-label="${tip}" onclick="event.stopPropagation();${oc}"></button>`;
  return `<button class="sw txt ${on?'on':''} ${oc2}" title="${tip}" onclick="event.stopPropagation();${oc}">${esc(v.shade)}</button>`;
}

// ===== nav (rebuildable for language switch) =====
const PRICE_KEYS=['p_u50','p_50_100','p_100_200','p_200p'];
function buildNav(){
  const cn=document.getElementById('catnav');
  const cats=catsInStock();
  if(curCat!=='__all__'&&!cats.includes(curCat))curCat='__all__';   // קטגוריה שנבחרה אזלה → חזרה להכל
  const mk=(l,v)=>`<button class="cat ${v===curCat?'active':''}" data-c="${v}">${l}</button>`;
  cn.innerHTML=mk(t('all'),'__all__')+cats.map(c=>mk(catLabel(c),c)).join('');
  cn.onclick=e=>{const b=e.target.closest('[data-c]');if(!b)return;curCat=b.dataset.c;
    [...cn.children].forEach(c=>c.classList.toggle('active',c.dataset.c===curCat));render()};

  const bn=document.getElementById('brandnav');
  const brands=brandsInStock();
  if(curBrand!=='__all__'&&!brands.includes(curBrand))curBrand='__all__';   // מותג שנבחר אזל → חזרה להכל
  const mb=(l,v)=>`<button class="pill ${v===curBrand?'active':''}" data-b="${v}">${l}</button>`;
  bn.innerHTML=mb(t('all_brands'),'__all__')+brands.map(b=>mb(b,b)).join('');
  bn.onclick=e=>{const b=e.target.closest('[data-b]');if(!b)return;curBrand=b.dataset.b;
    [...bn.children].forEach(c=>c.classList.toggle('active',c.dataset.b===curBrand));render()};

  const pr=document.getElementById('prices');
  const mp=(l,i)=>`<button class="chip ${i===curPrice?'active':''}" data-p="${i}">${l}</button>`;
  pr.innerHTML=mp(t('all_prices'),-1)+PRICES.map((p,i)=>mp(t(PRICE_KEYS[i]),i)).join('');
  pr.onclick=e=>{const b=e.target.closest('[data-p]');if(!b)return;curPrice=+b.dataset.p;
    [...pr.children].forEach(c=>c.classList.toggle('active',+c.dataset.p===curPrice));render()};
}
buildNav();
function toggleFavOnly(){favOnly=!favOnly;document.getElementById('favchip').classList.toggle('active',favOnly);render()}
function resetFilters(){   // איפוס כל הסינונים (קטגוריה/מותג/מחיר/מועדפים/חיפוש)
  curCat='__all__';curBrand='__all__';curPrice=-1;favOnly=false;inStockOnly=false;
  var q=document.getElementById('q');if(q)q.value='';
  var fc=document.getElementById('favchip');if(fc)fc.classList.remove('active');
  var ac=document.getElementById('ac');if(ac)ac.classList.remove('show');
  buildNav();render();
}
function toggleStockOnly(){inStockOnly=!inStockOnly;document.getElementById('stockchip').classList.toggle('active',inStockOnly);render()}

// ===== filtering =====
const SEARCH_ALIASES=[
 ['דיאור','דיור dior'],['דיור','דיאור dior'],['dior','דיור דיאור'],
 ['ysl','ייב סן לורן איב סן לורן yves saint laurent'],['איב סן לורן','ייב סן לורן ysl'],['ייב סן לורן','איב סן לורן ysl'],
 ['מקאפ','מייקאפ makeup make up'],['מייקאפ','מקאפ makeup make up'],['מייק אפ','מייקאפ makeup'],
 ['ספורה','sephora'],['sephora','ספורה'],
 ['שרלוט','charlotte tilbury'],['charlotte','שרלוט טילבורי'],['tilbury','שרלוט טילבורי'],
 ['רוד','rhode רואד'],['רואד','rhode רוד'],['rhode','רוד רואד'],
 ['אלף','elf e.l.f אי.אל.אף'],['elf','אי.אל.אף אלף'],['e.l.f','אי.אל.אף אלף']
];
function normText(s){
  s=String(s||'').toLowerCase();
  if(s.normalize)s=s.normalize('NFKC');
  return s.replace(/[\u0591-\u05C7\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]/g,'')
    .replace(/[׳']/g,'').replace(/[״"]/g,'')
    .replace(/[-_/.,()|·:;!؟?]+/g,' ')
    .replace(/\s+/g,' ').trim();
}
function expandSearch(s){
  const n=normText(s); if(!n)return '';
  let out=' '+n+' ';
  SEARCH_ALIASES.forEach(([needle,extra])=>{if(out.includes(' '+normText(needle)+' '))out+=normText(extra)+' ';});
  return out.replace(/\s+/g,' ').trim();
}
// build a multilingual search blob per group (HE/EN/AR names, categories, descriptions, features, shades, barcodes)
function catBoth(type){return (I18N.ar['c_'+type]||'')+' '+(I18N.he['c_'+type]||'');}
function buildHay(g){
  let s=g.name_he+' '+g.name_en+' '+g.brand+' '+catBoth(g.type);
  g.variants.forEach(v=>{s+=' '+(v.shade||'')+' '+(v.barcode||'')+' '+(v.desc||'')+' '+((v.features||[]).join(' '))+' '+(v.usage||'')+' '+(v.desc_ar||'')+' '+((v.features_ar||[]).join(' '))+' '+(v.usage_ar||'');});
  return expandSearch(s);
}
function matchQ(g,q){
  q=normText(q);
  if(!q)return true;
  const hay=g._hay||(g._hay=buildHay(g));
  return hay.includes(q)||q.split(' ').every(term=>hay.includes(term));
}
function visible(){
  const q=document.getElementById('q').value.trim().toLowerCase();
  let r=GROUPS.filter(g=>{
    if(curCat!=='__all__'&&g.type!==curCat)return false;
    if(curBrand!=='__all__'&&g.brand!==curBrand)return false;
    if(curPrice>=0){const pr=PRICES[curPrice];if(!(g.minp>=pr.mn&&g.minp<pr.mx))return false}
    if(favOnly&&!FAVS.has(g.gid))return false;
    if(STOCK_READY&&!g.variants.some(v=>STOCK[nbc(v.barcode)]>0))return false;   // תמיד: להציג רק מה שבמלאי (צרכן+סיטונאי)
    if(STOCK_READY&&!g.variants.some(inDB))return false;   // הסתרת מוצרים שאינם ב-DB (לא ניתנים להזמנה)
    if(STOCK_READY&&!WHOLESALE&&!g.variants.some(hasConsPrice))return false;   // מצב צרכן: להסתיר מוצר ללא מחיר צרכן
    return matchQ(g,q);
  });
  const s=document.getElementById('sort').value;
  // cards without an image always sink to the bottom (regardless of sort)
  const byImg=(a,b)=> (a._noimg?1:0)-(b._noimg?1:0);
  if(s==='price-asc')r.sort((a,b)=>byImg(a,b)||a.minp-b.minp);
  else if(s==='price-desc')r.sort((a,b)=>byImg(a,b)||b.minp-a.minp);
  else if(s==='name')r.sort((a,b)=>byImg(a,b)||a.name_he.localeCompare(b.name_he,'he'));
  else r.sort((a,b)=> byImg(a,b)              // default "מומלץ": prestige brands first
      || prestige(a.brand)-prestige(b.brand)
      || a.brand.localeCompare(b.brand,'he')
      || a.minp-b.minp);
  return r;
}

// ===== badges & price html =====
function badgesHtml(v){
  const bs=(v.badges||[]).slice().sort((a,b)=>BADGE_ORDER.indexOf(a)-BADGE_ORDER.indexOf(b)).slice(0,2);
  if(!bs.length)return '';
  return `<div class="bdgs">${bs.map(b=>`<span class="bdg ${b}">${t('b_'+b)||b}</span>`).join('')}</div>`;
}
function priceHtml(v,cls){
  var c=WHOLESALE?PRICE_CONS[nbc(v.barcode)]:null;   // במצב סיטונאי — להציג גם מחיר צרכן מומלץ
  var sub=(c!=null&&c>0)?`<div class="price-cons">${t('cons_rec')} ₪${c}</div>`:'';
  return `<div class="pricewrap"><div class="price ${cls||''}">₪${eff(v)}</div>${sub}</div>`;
}

// ===== grid =====
function cardHtml(g){
  const v=selV(g);
  const qty=CART[v.id]?CART[v.id].qty:0;
  const fav=FAVS.has(g.gid)?'on':'';
  const img=v.imgs.length?`<img src="${aesc(v.imgs[0])}" loading="lazy" data-l="${aesc(g.name_he[0]||'✦')}" onerror="imgErr(this)">`:`<div class="ph">${esc(g.name_he[0]||'✦')}</div>`;
  let shades='';
  if(g.variants.length>1){
    const idx=curIdx(g);
    shades=`<div class="shrow" onclick="event.stopPropagation()">${g.variants.map((vv,k)=>swPill(vv,k===idx,`pickV('${g.gid}',${k})`)).join('')}</div>`;
  }
  const nInStock=STOCK_READY?g.variants.filter(vv=>STOCK[nbc(vv.barcode)]>0).length:0;
  return `<div class="card" id="card-${g.gid}" onclick="openPd(${g._i})">
      <div class="imgbox">
        <button class="fav ${fav}" onclick="event.stopPropagation();toggleFav('${g.gid}',this)">♥</button>
        ${badgesHtml(v)}${img}
      </div>
      <div class="body">
        <div class="brand">${esc(g.brand)}</div>
        <div class="nm">${esc(g.name_he)}</div>
        ${g.name_en?`<div class="nm-en">${esc(g.name_en)}</div>`:''}
        ${g.variants.length>1?`<span class="nsh">${g.variants.length} ${t('shades')}${(STOCK_READY&&nInStock>0)?` · <b class="instk">${nInStock} ${t('in_stock_short')}</b>`:''}</span>`:(v.size?`<div class="meta"><span class="tag">${esc(v.size)}</span></div>`:'')}
        ${shades}
        <div class="foot">
          ${priceHtml(v)}
          ${isSold(v)?`<span class="soldpill">${t('sold_out')}</span>`
            :qty>0?`<div class="cardqty" onclick="event.stopPropagation()"><button onclick="event.stopPropagation();cartChange('${v.id}',-1)">−</button><input class="cardqin" type="number" inputmode="numeric" min="1" value="${qty}" onclick="event.stopPropagation()" onkeydown="if(event.key==='Enter')this.blur()" onchange="event.stopPropagation();cartSetQty('${v.id}',Math.max(1,parseInt(this.value)||1))"><button onclick="event.stopPropagation();cartChange('${v.id}',1)">+</button></div>`
                 :`<button class="add" onclick="event.stopPropagation();cartChange('${v.id}',1)">+</button>`}
        </div>
      </div>
    </div>`;
}
// ---- מונה חי בהירו: מספר המוצרים שבמלאי (עד שהמלאי נטען — סה"כ הקטלוג) ----
function updateHeroCount(){
  const el=document.getElementById('heroCount'); if(!el)return;
  const n=STOCK_READY?GROUPS.reduce((s,g)=>s+g.variants.filter(v=>STOCK[nbc(v.barcode)]>0).length,0):GROUPS.length;   // ספירת מק"טים במלאי (תואם לבק אופיס)
  el.textContent=n.toLocaleString()+' '+(STOCK_READY?t('in_stock_count'):t('items'));
}
// ---- paginated render (incremental, for 1400+ cards) ----
let VIS=[], shown=0; const PAGE=60;
function render(){
  VIS=visible(); shown=0; updateHeroCount();
  const grid=document.getElementById('grid');
  const cnt=document.getElementById('rescount'); if(cnt)cnt.textContent=VIS.length.toLocaleString()+' '+t('items');
  grid.innerHTML='';
  if(!VIS.length){grid.innerHTML='<div class="empty">'+t('empty')+'</div>';return}
  loadMore();
}
function loadMore(){
  if(shown>=VIS.length)return;
  const slice=VIS.slice(shown,shown+PAGE);
  document.getElementById('grid').insertAdjacentHTML('beforeend', slice.map(cardHtml).join(''));
  shown+=slice.length;
}
function updateCard(gid){var el=document.getElementById('card-'+gid);if(!el)return;var g=GROUPS.find(x=>x.gid===gid);if(g)el.outerHTML=cardHtml(g);}
function pickV(gid,k){sel[gid]=k;updateCard(gid);}
function toggleFav(gid,btn){if(FAVS.has(gid))FAVS.delete(gid);else FAVS.add(gid);saveFavs();
  if(btn)btn.classList.toggle('on',FAVS.has(gid));if(favOnly)render()}

// ===== autocomplete =====
let acIdx=-1, acList=[];
function toggleClr(){var q=document.getElementById('q').value;var b=document.getElementById('clrBtn');if(b)b.classList.toggle('show',!!q);}
function clearSearch(){var q=document.getElementById('q');q.value='';document.getElementById('ac').classList.remove('show');toggleClr();render();q.focus();}
function onSearch(){buildAC();render();toggleClr();}
function buildAC(){
  const q=document.getElementById('q').value.trim().toLowerCase();
  const ac=document.getElementById('ac');
  if(q.length<2){ac.classList.remove('show');acList=[];return}
  acList=GROUPS.filter(g=>matchQ(g,q)&&(!STOCK_READY||g.variants.some(v=>STOCK[nbc(v.barcode)]>0))).slice(0,20);
  acIdx=-1;
  if(!acList.length){ac.classList.remove('show');return}
  ac.innerHTML=acList.map((g,i)=>{const v=selV(g);
    const im=v.imgs.length?`<img src="${aesc(v.imgs[0])}" onerror="this.style.visibility='hidden'">`:`<span style="width:30px"></span>`;
    return `<div class="ac-item" role="option" aria-label="${aesc(g.brand+' - '+g.name_he)}" data-i="${i}" onmousedown="acPick(${i})"><div class="b">${esc(g.brand)}</div>${im}<span class="ac-nm">${esc(g.name_he)}${g.name_en?`<i class="ac-en">${esc(g.name_en)}</i>`:''}</span></div>`;
  }).join('');
  ac.classList.add('show');
}
function acPick(i){const g=acList[i];if(!g)return;document.getElementById('ac').classList.remove('show');
  document.getElementById('q').blur();openPd(g._i);}
function acKey(e){
  const ac=document.getElementById('ac');if(!ac.classList.contains('show'))return;
  if(e.key==='ArrowDown'){acIdx=Math.min(acIdx+1,acList.length-1);e.preventDefault();}
  else if(e.key==='ArrowUp'){acIdx=Math.max(acIdx-1,0);e.preventDefault();}
  else if(e.key==='Enter'){ac.classList.remove('show');if(acIdx>=0)acPick(acIdx);else document.getElementById('q').blur();e.preventDefault();return;}
  else if(e.key==='Escape'){ac.classList.remove('show');return;}
  [...ac.children].forEach((c,k)=>c.classList.toggle('hl',k===acIdx));
}
document.addEventListener('click',e=>{if(!e.target.closest('.search'))document.getElementById('ac').classList.remove('show')});

// ===== product detail =====
function openPd(i){renderPd(GROUPS[i]);openOv('pdModal');}
function renderPd(g){
  const v=selV(g);
  const gal=v.imgs.length?v.imgs.map(s=>`<img src="${aesc(s)}" loading="lazy" data-l="${aesc(g.name_he[0]||'✦')}" onerror="imgErr(this)">`).join(''):`<div class="ph">${esc(g.name_he[0]||'✦')}</div>`;
  // Arabic copy when LANG=ar (fallback to Hebrew per field)
  const _dsc=(LANG==='ar'&&v.desc_ar)?v.desc_ar:v.desc;
  const _fts=(LANG==='ar'&&v.features_ar&&v.features_ar.length)?v.features_ar:v.features;
  const _usg=(LANG==='ar'&&v.usage_ar)?v.usage_ar:v.usage;
  const feats=(_fts&&_fts.length)?`<h4>${t('feats')}</h4><ul>${_fts.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>`:'';
  const contents=(v.contents&&v.contents.length)?`<h4>${t('contents_h')}</h4><div class="bndl">${v.contents.map(c=>`<details><summary>${esc(c.n||c.name||'')}</summary><p>${esc(c.d||c.desc||'')}</p></details>`).join('')}</div>`:'';
  const ing=v.ingredients?`<h4>${t('ingredients')}</h4><p>${esc(v.ingredients)}</p>`:'';
  const use=_usg?`<h4>${t('usage')}</h4><p>${esc(_usg)}</p>`:'';
  let shades='';
  if(g.variants.length>1){const idx=curIdx(g);
    shades=`<div class="pd-shades"><div class="lbl">${t('pick_shade')} (${g.variants.length}):</div><div class="pd-sw">${g.variants.map((vv,k)=>`<button class="${k===idx?'on':''} ${isSold(vv)?'out':''}" onclick="pdPick('${g.gid}',${k})">${vv.color?`<i class="dot" style="background:${vv.color}"></i>`:''}${esc(vv.shade)}${isSold(vv)?` · ${t('sold_out')}`:''}</button>`).join('')}</div></div>`;}
  const _pc=WHOLESALE?PRICE_CONS[nbc(v.barcode)]:null;   // מחיר צרכן מומלץ במצב סיטונאי
  const pr=`<div class="pr">₪${eff(v)}</div>`+((_pc!=null&&_pc>0)?`<div class="pr-cons">${t('cons_rec')} ₪${_pc}</div>`:'');
  const bdg=(v.badges||[]).map(b=>`<span class="tag" style="color:#fff;background:${b==='sale'?'#e0245e':b==='vegan'?'#16a34a':'var(--accent)'};border:none">${t('b_'+b)||b}</span>`).join('');
  // similar: other groups, same brand first then same type
  const sim=GROUPS.filter(x=>x.gid!==g.gid&&(x.brand===g.brand||x.type===g.type))
    .sort((a,b)=>(a.brand===g.brand?0:1)-(b.brand===g.brand?0:1)).slice(0,8);
  const simHtml=sim.length?`<div class="sim"><h4>${t('similar')}</h4><div class="sim-row">${sim.map(x=>{const xv=selV(x);
    const im=xv.imgs.length?`<img src="${aesc(xv.imgs[0])}" onerror="this.style.visibility='hidden'">`:'<span class="ph" style="font-size:26px">✦</span>';
    return `<div class="sim-card" onclick="openPd(${x._i})"><div class="si">${im}</div><div class="sn">${esc(x.name_he)}</div><div class="sp">₪${eff(xv)}</div></div>`;}).join('')}</div></div>`:'';
  document.getElementById('pdContent').innerHTML=`
    <div class="pd-gal">${gal}</div>
    <div class="pd">
      <div class="b">${esc(g.brand)}</div>
      <h2>${esc(g.name_he)}</h2>
      ${g.name_en?`<div class="en">${esc(g.name_en)}</div>`:''}
      <div class="row">${bdg}${v.size?`<span class="tag">${esc(v.size)}</span>`:''}<span class="tag">${esc(catLabel(g.type))}</span></div>
      ${shades}
      ${pr}
      <button class="pdfav ${FAVS.has(g.gid)?'on':''}" id="pdFav" onclick="toggleFavFromModal('${g.gid}')"><span class="h">♥</span><span class="t">${FAVS.has(g.gid)?t('fav_remove'):t('fav_add')}</span></button>
      ${_dsc?`<h4>${t('desc')}</h4><p>${esc(_dsc)}</p>`:''}
      ${contents}
      ${feats}${ing}${use}
      ${v.barcode?`<div class="barc">${t('barcode')} ${esc(v.barcode)}</div>`:''}
      ${isSold(v)?`<button class="cta" disabled style="opacity:.5;cursor:not-allowed">${t('sold_out')}</button>`
        :`<button class="cta" onclick="cartChange('${v.id}',1);closePd()">${t('add_order')}  ·  ₪${eff(v)}</button>`}
      ${simHtml}
    </div>`;
}
function pdPick(gid,k){sel[gid]=k;renderPd(GROUPS.find(g=>g.gid===gid));render();}
function closePd(){closeOv('pdModal')}
function toggleFavFromModal(gid){if(FAVS.has(gid))FAVS.delete(gid);else FAVS.add(gid);saveFavs();
  const on=FAVS.has(gid),b=document.getElementById('pdFav');
  if(b){b.classList.toggle('on',on);b.querySelector('.t').textContent=on?t('fav_remove'):t('fav_add')}render();}

// ===== cart (keyed by variant id) =====
const CART={};
function cartChange(vid,delta){
  const m=VMAP[vid];if(!m)return;
  if(delta>0&&isSold(m.v))return;
  if(delta>0){
    if(CART[vid])CART[vid].qty++;
    else CART[vid]={vid,name:m.g.name_he+(m.v.shade&&m.g.variants.length>1?' · '+m.v.shade:''),brand:m.g.brand,size:m.v.size,price:eff(m.v),qty:1};
  } else if(CART[vid]){CART[vid].qty--;if(CART[vid].qty<=0)delete CART[vid];}
  renderCart();updateCard(m.g.gid);
  if(document.getElementById('orderModal').classList.contains('open'))renderOrder();
}
function cartTotals(){let qty=0,sub=0;Object.values(CART).forEach(it=>{qty+=it.qty;sub+=it.qty*it.price});return{qty,sub};}
function renderCart(){const {qty,sub}=cartTotals();const bar=document.getElementById('cartbar');
  if(qty===0){bar.classList.remove('show');return}bar.classList.add('show');
  document.getElementById('cartsum').innerHTML=`${qty} ${t('cart_items')} · <b>₪${sub}</b>`;}
function pruneUnavailableCart(){Object.keys(CART).forEach(vid=>{const m=VMAP[vid];if(m&&isSold(m.v))delete CART[vid];});}

const COUPONS={'BEAUTY10':{type:'percent',val:10,label:'10% הנחה'},'FAV20':{type:'fixed',val:20,label:'₪20 הנחה'}};
let activeCoupon=null;
function applyCoupon(){const code=document.getElementById('coupon').value.trim().toUpperCase();const msg=document.getElementById('cmsg');
  if(!code){activeCoupon=null;msg.textContent='';msg.className='cmsg';renderTotals();return}
  if(COUPONS[code]){activeCoupon={code,...COUPONS[code]};msg.textContent=t('coupon_ok')+couponLabel(code);msg.className='cmsg ok';}
  else{activeCoupon=null;msg.textContent=t('coupon_bad');msg.className='cmsg err';}renderTotals();}
function discount(sub){if(!activeCoupon)return 0;if(activeCoupon.type==='percent')return Math.round(sub*activeCoupon.val/100);return Math.min(sub,activeCoupon.val);}
function couponLabel(code){const c=COUPONS[code];if(!c)return'';return c.type==='percent'?(c.val+'% '+t('off')):('₪'+c.val+' '+t('off'));}

/* ===== מצב סיטונאי (קוד משותף, אימות מול hash מ-app_settings) ===== */
async function sha256hex(str){const norm=String(str).trim().toUpperCase();
  const buf=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(norm));
  return Array.from(new Uint8Array(buf)).map(b=>b.toString(16).padStart(2,'0')).join('');}
function openWholesale(){if(WHOLESALE){wholesaleLogout();return;}
  var i=document.getElementById('wsCode');if(i)i.value='';var m=document.getElementById('wsMsg');if(m){m.textContent='';m.className='cmsg';}
  openOv('wsModal');setTimeout(function(){var el=document.getElementById('wsCode');if(el)el.focus();},60);}
async function submitWholesale(){const code=document.getElementById('wsCode').value.trim();const msg=document.getElementById('wsMsg');
  if(!code){msg.textContent='';msg.className='cmsg';return;}
  if(!WS_HASH){msg.textContent=t('ws_unavailable');msg.className='cmsg err';return;}
  const h=await sha256hex(code);
  if(h===WS_HASH){setWholesale(true);closeOv('wsModal');}
  else{msg.textContent=t('ws_bad');msg.className='cmsg err';}}
function wholesaleLogout(){setWholesale(false);}
function setWholesale(on){WHOLESALE=on;
  try{if(on)localStorage.setItem('wholesale_unlocked','1');else localStorage.removeItem('wholesale_unlocked');}catch(e){}
  updateWsUI();repriceCart();renderCart();render();
  if(document.getElementById('orderModal').classList.contains('open'))renderOrder();}
function updateWsUI(){var b=document.getElementById('wsBanner');if(b)b.style.display=WHOLESALE?'flex':'none';
  var pb=document.getElementById('pbWholesale');if(pb)pb.textContent=WHOLESALE?t('ws_exit'):t('ws_enter');}
function repriceCart(){Object.keys(CART).forEach(function(vid){var m=VMAP[vid];if(m)CART[vid].price=eff(m.v);});}   // עדכון מחירי פריטים בסל למצב הפעיל

function openOrder(){renderOrder();openOv('orderModal')}
function closeOrder(){closeOv('orderModal')}
function renderOrder(){
  const keys=Object.keys(CART);window._K=keys;const body=document.getElementById('omBody');
  if(!keys.length){body.innerHTML='<p style="text-align:center;color:var(--muted);padding:20px">'+t('cart_empty')+'</p>';renderTotals();return}
  body.innerHTML=keys.map((k,idx)=>{const it=CART[k];return `<div class="om-row">
    <div class="nm">${esc(it.name)}<small>${esc(it.brand)}${it.size?' · '+esc(it.size):''}</small></div>
    <div class="qy"><button data-i="${idx}" data-a="dec">−</button><input class="qin" type="number" inputmode="numeric" min="1" data-qi="${idx}" value="${it.qty}"><button data-i="${idx}" data-a="inc">+</button></div>
    <div class="lt">₪${it.qty*it.price}</div>
    <button class="om-del" data-i="${idx}" data-a="del">✕</button></div>`}).join('');
  body.onclick=e=>{const b=e.target.closest('[data-a]');if(!b)return;const key=window._K[+b.dataset.i];if(!key)return;
    cartChange(key,b.dataset.a==='inc'?1:(b.dataset.a==='dec'?-1:-(CART[key]?CART[key].qty:0)));};
  body.onchange=e=>{const inp=e.target.closest('[data-qi]');if(!inp)return;const key=window._K[+inp.dataset.qi];if(!key)return;
    let n=parseInt(inp.value,10);if(isNaN(n)||n<1)n=1;cartSetQty(key,n);};
  renderTotals();
}
function cartSetQty(vid,n){const m=VMAP[vid];if(!m||!CART[vid])return;CART[vid].qty=Math.max(1,n);
  renderCart();updateCard(m.g.gid);if(document.getElementById('orderModal').classList.contains('open'))renderOrder();}
function renderTotals(){const {sub}=cartTotals();const d=discount(sub);const el=document.getElementById('totals');
  if(!Object.keys(CART).length){el.innerHTML='';return}
  const net=sub-d, vat=Math.round(net*0.18), tot=net+vat;
  el.innerHTML=`<div class="l"><span>${t('subtotal')}</span><span>₪${sub}</span></div>
    ${d?`<div class="l" style="color:#15803d"><span>${t('discount')} (${esc(activeCoupon.code)})</span><span>−₪${d}</span></div>`:''}
    <div class="l"><span>${t('vat')}</span><span>₪${vat}</span></div>
    <div class="l grand"><span>${t('grand')}</span><b>₪${tot}</b></div>`;}

const WA_NUMBER='972547599923';
function gv(id){var e=document.getElementById(id);return e?e.value.trim():''}
function noteText(){   // עסק/עוסק-ח.פ/כתובת + הערת הלקוח + קופון — נשמר ב-orders.note (מוצג וניתן לחיפוש בבק אופיס)
  const biz=gv('buyer-biz'),bid=gv('buyer-id'),addr=gv('buyer-addr');
  let n='';
  if(biz)n+=`עסק: ${biz}`;
  if(bid)n+=(n?' | ':'')+`עוסק/ח.פ: ${bid}`;
  if(addr)n+=(n?' | ':'')+`כתובת: ${addr}`;
  const notes=gv('notes');if(notes)n=(n?n+' | ':'')+notes;
  if(activeCoupon){const d=discount(cartTotals().sub);if(d)n=(n?n+' | ':'')+`קופון ${activeCoupon.code} (−₪${d})`;}
  return n;
}
function buildOrderText(orderId){
  const keys=Object.keys(CART);if(!keys.length)return '';
  let msg='*הזמנה חדשה — Beauty Favorites*\n';
  if(orderId)msg+=`מס׳ הזמנה: #${orderId}\n`;
  const name=gv('buyer-name'),biz=gv('buyer-biz'),bid=gv('buyer-id'),addr=gv('buyer-addr'),phone=gv('buyer-phone');
  if(name)msg+=`\nשם: ${name}`;if(biz)msg+=`\nעסק: ${biz}`;if(bid)msg+=`\nעוסק/ח.פ: ${bid}`;
  if(addr)msg+=`\nכתובת: ${addr}`;if(phone)msg+=`\nטלפון: ${phone}`;msg+='\n\n';
  let sub=0;keys.forEach(k=>{const it=CART[k];const lt=it.qty*it.price;sub+=lt;
    msg+=`• ${it.name}${it.size?' ('+it.size+')':''} ×${it.qty} = ₪${lt}\n`});
  const d=discount(sub);const net=sub-d,vat=Math.round(net*0.18),tot=net+vat;
  if(d)msg+=`\nהנחה (${activeCoupon.code}): −₪${d}`;
  msg+=`\nסכום לפני מע"מ: ₪${net}\nמע"מ 18%: ₪${vat}\n*סה"כ כולל מע"מ: ₪${tot}*`;
  const notes=gv('notes');if(notes)msg+=`\n\nהערות: ${notes}`;return msg;
}

/* ===== חיבור Supabase (אופציונלי). ריק → fallback לוואטסאפ-טקסט בלבד ===== */
const SB=(window.SUPA&&window.SUPA.url&&window.SUPA.anon&&window.supabase)
  ? window.supabase.createClient(window.SUPA.url,window.SUPA.anon) : null;
var STOCK={}, PRICE_WS={}, PRICE_CONS={};   // ברקוד-מנורמל -> מלאי / מחיר סיטונאי / מחיר צרכן (var=hoisted כדי ש-eff לא יזרוק בטעינה)
var STOCK_READY=false;
var WHOLESALE=(function(){try{return localStorage.getItem('wholesale_unlocked')==='1';}catch(e){return false;}})();  // מצב סיטונאי פעיל?
var WS_HASH=null;   // hash קוד-הסיטונאי מ-app_settings (לאימות בצד-לקוח)
function priceMap(){return WHOLESALE?PRICE_WS:PRICE_CONS;}   // המפה הפעילה לפי המצב
function hasConsPrice(v){var m=PRICE_CONS[nbc(v&&v.barcode)];return m!=null&&m>0;}   // יש מחיר צרכן?
function nbc(x){return String(x||'').replace(/\D/g,'');}      // ברקוד → ספרות בלבד (תואם sku ב-DB)
function inDB(v){return STOCK_READY && v && STOCK[nbc(v.barcode)]!==undefined;}   // קיים ב-DB?
function isSold(v){if(!STOCK_READY)return false;const n=nbc(v&&v.barcode);return STOCK[n]===undefined||STOCK[n]<=0;}  // לא-ב-DB או אזל → לא זמין
async function loadStock(){
  if(!SB)return;
  try{
    const page=1000; let from=0;        // עוקף את תקרת 1000 השורות של PostgREST
    for(;;){
      const {data,error}=await SB.from('products').select('barcode,stock,active,price_x3,price_consumer').range(from,from+page-1);
      if(error)throw error;
      (data||[]).forEach(p=>{const n=nbc(p.barcode);if(n){STOCK[n]=p.active?p.stock:0;
        if(p.price_x3!=null)PRICE_WS[n]=Number(p.price_x3);
        if(p.price_consumer!=null)PRICE_CONS[n]=Number(p.price_consumer);}});
      if(!data||data.length<page)break;
      from+=page;
    }
    try{const {data:s}=await SB.from('app_settings').select('value').eq('key','wholesale_code_hash').maybeSingle();WS_HASH=(s&&s.value)||null;}catch(e){}   // hash קוד סיטונאי
    STOCK_READY=true; pruneUnavailableCart(); updateWsUI(); repriceCart(); buildNav(); renderCart(); render();    // ציור מחדש + תמחור סל למצב הפעיל (סיטונאי/צרכן) אחרי טעינת מחירים
  }catch(e){console.warn('טעינת מלאי נכשלה:',e);}
}
function cartItems(){      // [{sku, qty}] עבור create_order (sku = ברקוד מנורמל, תואם DB)
  return Object.keys(CART).map(vid=>{const m=VMAP[vid];return {sku:nbc(m&&m.v.barcode),qty:CART[vid].qty,sold:m&&isSold(m.v)};}).filter(it=>it.sku&&!it.sold).map(({sku,qty})=>({sku,qty}));
}
function validateBuyer(){
  if(!Object.keys(CART).length){alert(t('alert_empty'));return false;}
  const name=gv('buyer-name'),phone=gv('buyer-phone');
  if(!name||!phone){alert(t('alert_fill'));document.getElementById(!name?'buyer-name':'buyer-phone').focus();return false;}
  return true;
}
function setBusy(btn,on){if(!btn)return;if(on){btn.dataset.l=btn.textContent;btn.disabled=true;btn.textContent=t('sending');}else{btn.disabled=false;if(btn.dataset.l)btn.textContent=btn.dataset.l;}}
async function createOrder(channel){   // קריאה אחת ל-create_order → {id,total}. המלאי לא יורד בשלב זה.
  const items=cartItems();
  if(!items.length){alert(t('err_order'));return null;}
  const {data,error}=await SB.rpc('create_order',{
    p_customer_name:gv('buyer-name'),p_customer_phone:gv('buyer-phone'),
    p_customer_email:'',p_customer_type:gv('buyer-biz')?'barber':'retail',
    p_channel:channel,p_note:noteText(),p_items:items});
  if(error){console.error(error);alert(t('err_order'));return null;}
  const row=Array.isArray(data)?data[0]:data;
  return row?{id:row.order_id,total:row.order_total}:null;
}

// א) "שלח הזמנה לאישור (וואטסאפ)" — create_order(channel='whatsapp') ואז פתיחת wa.me עם מספר ההזמנה
async function submitWhatsApp(){
  if(!validateBuyer())return;
  if(!SB){ // עוד לא חובר Supabase — שולחים טקסט בלבד (כמו קודם)
    window.open('https://wa.me/'+WA_NUMBER+'?text='+encodeURIComponent(buildOrderText()));return;
  }
  const btn=document.getElementById('sendBtn');setBusy(btn,true);
  const ord=await createOrder('whatsapp');setBusy(btn,false);
  if(!ord)return;
  window.open('https://wa.me/'+WA_NUMBER+'?text='+encodeURIComponent(buildOrderText(ord.id)));
}
// ב) "שלם עכשיו" — create_order(channel='payment') ואז create-checkout → הפניה ללינק התשלום
async function payNow(){
  if(!validateBuyer())return;
  if(!SB)return;
  const btn=document.getElementById('payBtn');setBusy(btn,true);
  const ord=await createOrder('payment');
  if(!ord){setBusy(btn,false);return;}
  try{
    const {data,error}=await SB.functions.invoke('create-checkout',{body:{order_id:ord.id}});
    if(error)throw error;
    if(data&&data.url){window.location.href=data.url;return;}
    throw new Error('no checkout url');
  }catch(e){console.error(e);alert(t('err_order'));setBusy(btn,false);}
}

function openOv(id){document.getElementById(id).classList.add('open');document.body.style.overflow='hidden'}
function closeOv(id){document.getElementById(id).classList.remove('open');document.body.style.overflow=''}
// ===== store policies (Israeli e-commerce; review with a lawyer) =====
const PNOTE='';  /* internal template/lawyer note removed — not customer-facing */
const POLICIES={
 contact:`<h2>פרטי העסק ויצירת קשר</h2>
  <p><b>שניר שריקי</b> – יבוא ושיווק מותגי שיער וקוסמטיקה</p>
  <p>עוסק מורשה: 040553562</p>
  <h3>יצירת קשר</h3>
  <p>טלפון: <a href="tel:0534555501">053-4555501</a></p>
  <p>אימייל: <a href="mailto:saphrafavorites@gmail.com">saphrafavorites@gmail.com</a></p>
  <p>הזמנות בוואטסאפ: <a href="https://wa.me/972547599923">054-7599923</a></p>
  <p>המחירים כוללים מע״מ · משלוחים לכל הארץ · משלוח חינם מעל ₪299</p>`,
 shipping:`<h2>משלוחים ואספקה</h2>${PNOTE}
  <p>ההזמנות נשלחות באמצעות חברת שליחויות (צ׳יטה).</p>
  <h3>זמן אספקה</h3><p>עד 72 שעות מרגע איסוף החבילה ע״י השליח (בימי עסקים).</p>
  <h3>דמי משלוח</h3><ul><li><b>משלוח חינם</b> בהזמנה מעל ₪299.</li><li>בהזמנה מתחת ל-₪299 — דמי משלוח כמפורט בעת ההזמנה.</li></ul>
  <h3>אזורי חלוקה</h3><p>משלוחים לכל הארץ. ייתכנו אזורים מסוימים עם זמן אספקה ארוך יותר.</p>`,
 returns:`<h2>החזרות וביטולים</h2>${PNOTE}
  <p>בהתאם לחוק הגנת הצרכן, התשמ״א-1981.</p>
  <h3>זכות ביטול</h3><p>ניתן לבטל עסקה ולהחזיר מוצר תוך 14 יום ממועד קבלתו.</p>
  <h3>תנאי ההחזרה</h3><ul><li>המוצר יוחזר חדש, באריזתו המקורית וללא שימוש.</li><li>מטעמי היגיינה, מוצרי קוסמטיקה/טיפוח שנפתחו או נעשה בהם שימוש — ייתכנו הגבלות החזרה בהתאם לחוק.</li><li>יש לצרף חשבונית/אישור רכישה.</li></ul>
  <h3>אופן ההחזר</h3><p>ליצירת בקשת ביטול/החזרה: טלפון 053-4555501 או אימייל saphrafavorites@gmail.com. ההחזר הכספי יבוצע באמצעי התשלום המקורי בניכוי דמי ביטול כדין (אם חלים).</p>`,
 terms:`<h2>תקנון האתר</h2>${PNOTE}
  <h3>כללי</h3><p>האתר מופעל על ידי שניר שריקי – יבוא ושיווק מותגי שיער וקוסמטיקה (עוסק מורשה 040553562) ("העסק"). השימוש באתר ובהזמנה כפוף לתקנון זה.</p>
  <h3>המוצרים</h3><p>האתר מציע מוצרי קוסמטיקה וטיפוח מקוריים. תמונות המוצרים להמחשה בלבד וייתכנו הבדלי גוון/אריזה. המחירים בשקלים חדשים וכוללים מע״מ.</p>
  <h3>הזמנות</h3><p>שליחת הזמנה מהווה הצעה לרכישה; העסק רשאי לאשר או לדחות הזמנה, ולעדכן מחירים וזמינות מלאי. ההזמנה תיחשב כמאושרת רק לאחר אישור העסק.</p>
  <h3>הבהרה מותגית</h3><p>העסק פועל כמשווק עצמאי של מוצרים מקוריים בלבד, ואינו קשור, מטעמן או בשיתוף עם הרשתות או המותגים המוצגים באתר. שמות המותגים מופיעים לצורך זיהוי המוצרים בלבד, וכל הסימנים המסחריים שייכים לבעליהם.</p>
  <h3>אחריות</h3><p>אחריות המוצר היא של היצרן/היבואן בהתאם לדין.</p>`,
 privacy:`<h2>מדיניות פרטיות</h2>${PNOTE}
  <h3>איסוף מידע</h3><p>לצורך ביצוע הזמנה ואספקתה נאספים פרטים: שם, טלפון, כתובת ופרטי הזמנה.</p>
  <h3>שימוש במידע</h3><p>המידע משמש לעיבוד ההזמנה, אספקה, שירות לקוחות ויצירת קשר בנוגע להזמנה.</p>
  <h3>העברה לצד שלישי</h3><p>המידע אינו נמכר. הוא עשוי להימסר לחברת השליחויות ולספק הסליקה אך ורק לצורך השלמת ההזמנה.</p>
  <h3>יצירת קשר</h3><p>לעיון, עדכון או מחיקת פרטים: saphrafavorites@gmail.com.</p>`,
};
function openPolicy(k){var b=document.getElementById('policyBody');if(b)b.innerHTML=POLICIES[k]||'';openOv('policyModal');}
document.querySelectorAll('.ov').forEach(ov=>ov.addEventListener('click',e=>{if(e.target===ov)closeOv(ov.id)}));
document.addEventListener('touchstart',()=>{if(![...document.querySelectorAll('.ov')].some(o=>o.classList.contains('open')))document.body.style.overflow=''},{passive:true});

function goTop(){window.scrollTo(0,0);document.documentElement.scrollTop=0;document.body.scrollTop=0;}
window.addEventListener('scroll',()=>{
  var y=window.pageYOffset||document.documentElement.scrollTop||0;
  document.getElementById('toTop').classList.toggle('show',y>420);
  if(window.innerHeight+y > document.body.offsetHeight-900) loadMore();   // infinite scroll
},{passive:true});

applyStatic();
render();
if(SB){var _pb=document.getElementById('payBtn');if(_pb)_pb.style.display='';loadStock();}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
