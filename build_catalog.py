#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build the "Beauty Favorites" digital catalog (grouped-variant model).
Reads knowledge/<id>/product.json, groups shade-variants under one card,
copies images, and emits catalog/index.html (data inline → works from file://).
Re-run after adding products to knowledge/ or editing catalog_overrides.json.
"""
import json, glob, os, shutil, re, sys, unicodedata

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

SITE_URL = "https://beautyfavorites.co.il"

# ---- שכבת תוכן מהמסד (2026-07-19): הבק אופיס הוא מקור האמת לטקסטים ----
# שולף את catalog_content (תצוגה ציבורית) ודורס name_he/description/brand/קטגוריות
# בערכי המסד — כך עריכה בבק אופיס מגיעה לאתר בפרסום הבא. נכשל בשקט אם אין רשת/תצוגה.
def fetch_db_content():
    import urllib.request, urllib.error
    try:
        cfg = json.load(open(os.path.join(CAT, "supabase.config.json"), encoding="utf-8"))
        url = cfg.get("url") or cfg.get("SUPABASE_URL")
        key = cfg.get("anonKey") or cfg.get("anon_key") or cfg.get("SUPABASE_ANON_KEY")
        out, offset = {}, 0
        # 🎛️ 07/10/2026 — attrs (תכונות לסינון). אם העמודה עוד לא קיימת במסד (המיגרציה
        # לא הורצה) — 400 מהשרת. **לא** נופלים לבנייה בלי מסד: מנסים שוב בלי attrs.
        cols = "barcode,name_he,description,brand,category,main_category,category_slug,sub_type,is_set,stocked_ever"
        with_attrs = True
        while True:
            req = urllib.request.Request(
                f"{url}/rest/v1/catalog_content?select={cols}{',attrs' if with_attrs else ''}"
                f"&limit=1000&offset={offset}",
                headers={"apikey": key, "Authorization": "Bearer " + key})
            try:
                page = json.load(urllib.request.urlopen(req, timeout=30))
            except urllib.error.HTTPError as e:
                if with_attrs and e.code == 400 and offset == 0:
                    print("ℹ️  אין עדיין עמודת attrs במסד — בונה בלי תכונות סינון")
                    with_attrs = False
                    continue
                raise
            for r in page:
                bc = _nbc(r.get("barcode"))          # אותו נירמול כמו בצד הקורא — כולל הסרת אפסים מובילים
                if bc:
                    out[bc] = r
            if len(page) < 1000:
                break
            offset += 1000
        # מחיר הצרכן החי — נצרב בקובץ כדי שהמחיר שנראה לפני שהמסד נטען יהיה הנכון.
        # בלי זה נשאר המחיר הישן מקובץ הידע, והלקוח רואה לרגע מחיר נמוך ושגוי.
        npx = 0
        try:
            offset = 0
            while True:
                req = urllib.request.Request(
                    f"{url}/rest/v1/catalog_products?select=barcode,price_consumer"
                    f"&limit=1000&offset={offset}",
                    headers={"apikey": key, "Authorization": "Bearer " + key})
                page = json.load(urllib.request.urlopen(req, timeout=30))
                for r in page:
                    bc = _nbc(r.get("barcode"))
                    pc = r.get("price_consumer")
                    if bc and pc not in (None, "") and float(pc) > 0:
                        out.setdefault(bc, {})["_live_price"] = float(pc)
                        npx += 1
                if len(page) < 1000:
                    break
                offset += 1000
        except Exception as e:
            print(f"⚠️  מחירים חיים לא נשלפו ({e}) — נשאר המחיר מקובץ הידע")
        print(f"🔗 תוכן מהמסד: {len(out)} מוצרים (הבק אופיס דורס טקסטים) · {npx} מחירי צרכן חיים")
        return out
    except Exception as e:
        print(f"⚠️  אין שכבת תוכן מהמסד ({e}) — בונה מקבצי הידע בלבד")
        return {}

# ---- 🗂️ עץ הקטגוריות (06/10/2026) ----
# שמונה קבוצות ו-50 תתי-קטגוריות, מטבלת `categories` במסד. **זה מחליף את
# הרשימה הקשיחה CATS** שהייתה שכבה שטוחה אחת (איפור · טיפוח · שיער…).
# הטבלה פתוחה לקריאה ל-anon (מדיניות categories_read_all), ולכן אותו מפתח
# ציבורי שכבר בשימוש כאן מספיק — אין צורך במפתח שירות בבנייה.
#
# 🎨 הצבע והאייקון יושבים כאן ולא במסד: הם **החלטת עיצוב של האתר**, לא נתון
# עסקי. מי שיוסיף קבוצה במסד יקבל אפור ואייקון ברירת מחדל, ויראה מיד שצריך
# לבחור לה צבע — עדיף על קבוצה שנעלמת בשקט.
CAT_STYLE = {
    # 🏜️ 12/10/2026 — פלטת "חול ואבן" לפי הבאנר של המעצבת נועה: גוני אדמה
    #    שקטים במקום שמונה צבעים חזקים. (הקודם: face #fdf2ec/#b4714f וכו' — בגיבוי.)
    "face":     ("#f6ede3", "#a87a5a"),
    "cheeks":   ("#f4e6e0", "#a86b5e"),
    "lips":     ("#f1e3e1", "#8e4f4f"),
    "eyes":     ("#ede8e2", "#6e6259"),
    "brows":    ("#f0e7dc", "#7a5c44"),
    "skincare": ("#ebebe1", "#6b7259"),
    "tools":    ("#ece7e1", "#6b625a"),
    "sets":     ("#f4eadb", "#9a7533"),
}
# ✏️ 12/10/2026 — אייקוני קו מאוירים לפי הדוגמה של המעצבת (viewBox 48).
#    fill="currentColor" + fill-opacity = מילוי עדין בצבע האריח (color נקבע ב-svg).
CAT_ICON = {
    "face":  '<circle cx="21" cy="26" r="14"/><path d="M13.5 24q2.5 2.6 5 0M23.5 24q2.5 2.6 5 0M15.5 31q5.5 5 11 0"/>'
             '<path d="M40 8l1.1 3.9 3.9 1.1-3.9 1.1-1.1 3.9-1.1-3.9-3.9-1.1 3.9-1.1zM41 27l.8 2.7 2.7.8-2.7.8-.8 2.7-.8-2.7-2.7-.8 2.7-.8z"/>',
    "cheeks": '<ellipse cx="26" cy="32" rx="16" ry="10"/><ellipse cx="26" cy="31" rx="9.5" ry="5.6" fill="currentColor" fill-opacity=".28"/>'
             '<ellipse cx="17" cy="15" rx="11" ry="7.5" transform="rotate(-28 17 15)"/><path d="M12 15.5l6-6M15 17.5l3.5-3.5"/>',
    "lips":  '<path d="M5 24c4-6.5 9.5-9.5 14-7.4 2 1 3.4 1.4 5 .4 1.6 1 3 .6 5-.4 4.5-2.1 10 .9 14 7.4"/>'
             '<path d="M5 24c5 8 12 11.5 19 11.5S38 32 43 24"/><path d="M5 24c7 2.2 13 1.6 19 1.6S36 26.2 43 24"/>',
    "eyes":  '<path d="M4 26c6-9 13-12.5 20-12.5S38 17 44 26c-6 8.5-13 11.5-20 11.5S10 34.5 4 26z"/>'
             '<circle cx="24" cy="26" r="7"/><circle cx="24" cy="26" r="2.6" fill="currentColor" fill-opacity=".45"/>'
             '<path d="M11.5 18.5l-3-4.5M17 15.2l-1.6-5M24 13.5V8M31 15.2l1.6-5M36.5 18.5l3-4.5"/>',
    "brows": '<path d="M5 31c8-10 20-14 38-8"/><path d="M10 31.5c7-6 17-8 30-5"/>'
             '<path d="M8.5 28l-2.5-4M12 25.5l-1.8-4.3M15.8 23.4l-1.1-4.5M19.6 22l-.5-4.6M23.4 21.2l.1-4.6"/>',
    "skincare": '<rect x="5" y="22" width="19" height="20" rx="4.5"/><path d="M11 22v-5h7v5M10 17h9v-5.5h-9z"/>'
             '<path d="M19 14h4M25 14h.01"/><rect x="9" y="28" width="11" height="8" rx="1.6"/>'
             '<path d="M29 6h13v3l-1.8 24h-9.4L29 9z"/><rect x="31" y="33" width="9" height="9" rx="1.6"/>',
    "tools": '<path d="M6.3 39.4l17.5-17.5 3.3 3.3L9.6 42.7c-1.2 1.2-4.5-2.1-3.3-3.3z"/><path d="M23.8 21.9l4-4 3.3 3.3-4 4"/>'
             '<path d="M27.8 17.9C29 12 33 6.6 38.6 4.8c3.7-1.2 5.8.9 4.6 4.6-1.8 5.6-7.2 9.6-12.1 11.1"/>'
             '<path d="M32.5 13.5l6-5.5M35 16.5l5.5-4.5" opacity=".6"/>',
    "sets":  '<rect x="8" y="22" width="32" height="20" rx="1.6"/><rect x="6" y="15.5" width="36" height="7" rx="1.6"/>'
             '<path d="M24 15.5V42"/><path d="M24 15.5c-3.8-6.8-11-7.2-10.6-2.7.4 3.6 6.4 3.4 10.6 2.7 4.2.7 10.2.9 10.6-2.7.4-4.5-6.8-4.1-10.6 2.7z"/>',
}
CAT_ICON_DEFAULT = '<circle cx="24" cy="24" r="16"/>'   # 12/10: viewBox 48


# 📌 כלל (הניהול 06/10): **כל מה שהבנייה צריכה יושב ב-catalog/ או ב-knowledge/.**
#    10-עבודה/ אינו בריפו ומסתדר ידנית — שינוי שם שם היה מפיל בנייה. העותק שם
#    ("מסמכי מדיניות — ערבית.json") הוא המקור הארכיוני של תרגום צ'אט המחקר.
POLICIES_AR_PATH = os.path.join(CAT, "policies_ar.json")

def load_policies_ar():
    """שבעת מסמכי המדיניות בערבית. חסר/פגום → {} והאתר נופל לעברית (ובדיקה תצעק)."""
    try:
        d = json.load(open(POLICIES_AR_PATH, encoding="utf-8"))
        ok = {k: v for k, v in d.items() if isinstance(v, str) and v.strip()}
        print(f"🌐 מדיניות בערבית: {len(ok)} מסמכים")
        return ok
    except Exception as e:
        print(f"⚠️  מדיניות בערבית לא נטענה מ-catalog/policies_ar.json ({e}) — האתר יציג עברית")
        return {}


# 🚫 06/10/2026 — תמונות לא מקצועיות לא נכנסות לאתר (נמרוד: "אסור… חכי לתמונה
#    מקצועית"). catalog/hidden_images.json — {תיקיית כרטיס: {קובץ: סיבה}}. הקבצים
#    ב-knowledge/ **לא נמחקים**; הבנייה פשוט לא מעתיקה ולא מציגה אותם.
def _load_hidden_images():
    try:
        d = json.load(open(os.path.join(CAT, "hidden_images.json"), encoding="utf-8"))
        return {k: v for k, v in d.items() if not k.startswith("_")}
    except FileNotFoundError:
        return {}
HIDDEN_IMAGES = _load_hidden_images()


def fetch_categories():
    """עץ הקטגוריות מהמסד. מחזיר [] אם אין רשת — והאתר נופל לשכבה הישנה."""
    import urllib.request
    try:
        cfg = json.load(open(os.path.join(CAT, "supabase.config.json"), encoding="utf-8"))
        url = cfg.get("url") or cfg.get("SUPABASE_URL")
        key = cfg.get("anonKey") or cfg.get("anon_key") or cfg.get("SUPABASE_ANON_KEY")
        req = urllib.request.Request(
            f"{url}/rest/v1/categories?select=slug,main,main_he,main_ar,name_he,name_ar,sort,active"
            f"&active=is.true&order=sort&limit=500",
            headers={"apikey": key, "Authorization": "Bearer " + key})
        rows = json.load(urllib.request.urlopen(req, timeout=30))
        tree, seen = [], {}
        for r in rows:
            m = r["main"]
            if m not in seen:
                bg, ink = CAT_STYLE.get(m, ("#f4f4f5", "#5a5a5a"))
                seen[m] = {"m": m, "he": re.sub(r"^\S+\s", "", r["main_he"] or m),
                           "ar": r.get("main_ar") or "", "bg": bg, "ink": ink,
                           "ic": CAT_ICON.get(m, CAT_ICON_DEFAULT), "subs": []}
                tree.append(seen[m])
            seen[m]["subs"].append({"s": r["slug"], "he": r["name_he"],
                                    "ar": r.get("name_ar") or ""})
        print(f"🗂️  עץ קטגוריות: {len(tree)} קבוצות · {len(rows)} תתי-קטגוריות")
        return tree
    except Exception as e:
        print(f"⚠️  עץ הקטגוריות לא נשלף ({e}) — האתר ייבנה בלי ניווט העץ")
        return []


def _js(x):
    """JSON בטוח להזרקה לתוך <script>: כל "<" מוברח ל-\\u003c.

    🛡️ ביקורת אבטחה 06/10/2026: json.dumps('</script>') מחזיר את הרצף כמו שהוא.
    **כל** נתון שנצרב לתבנית עובר כאן — לא רק מה שנראה מסוכן היום.
    """
    return json.dumps(x, ensure_ascii=False).replace("<", "\\u003c")


def overlay_db_content(p, db_row):
    # דורס טקסטים מהמסד (הבק אופיס = מקור אמת) — למעט name_he:
    # שמות המסד כוללים לרוב גוון ("...(גוון 15ML)"), והבנייה מנקה גוון מכותרות
    # הכרטיסים בעצמה. דריסת שם מהמסד תחזיר את הרעש — לכן השם נשאר מהידע.
    if not db_row:
        return p
    def val(k):
        v = db_row.get(k)
        return v.strip() if isinstance(v, str) and v.strip() else None
    if val("description"):  p["description"] = val("description")
    if val("brand"):        p["brand"] = val("brand")
    if val("category"):     p["category_refined"] = val("category")
    if val("main_category"): p["category_main"] = val("main_category")
    # 🗂️ 06/10/2026 — עץ הקטגוריות החדש. **המסד הוא מקור האמת היחיד כאן**:
    # לקבצי הידע אין את השדות האלה בכלל, ולכן אין מה לדרוס ואין התנגשות.
    if val("category_slug"): p["_cslug"] = val("category_slug")
    if val("sub_type"):      p["_stype"] = val("sub_type")
    if db_row.get("is_set"): p["_isset"] = True
    if isinstance(db_row.get("attrs"), dict): p["_attrs"] = db_row["attrs"]
    if db_row.get("_live_price"):        # המחיר החי גובר על המחיר שבקובץ הידע
        p["price_ils"] = db_row["_live_price"]
    return p

# ---- brand normalization ----
BRAND_MAP = {
    "לא נמצא": "אחר", "לא ידוע": "אחר",
    "-417 (Minus 417) Dead Sea Cosmetics": "417", "Airspun (Coty)": "Airspun",
    "Schwarzkopf Professional": "Schwarzkopf", "Maybelline New York": "Maybelline",
    "Amorus USA": "Amorus", "Benefit Cosmetics": "Benefit",
    "Giorgio Armani": "Armani", "Armani Beauty": "Armani",
    "Charlotte Tilbury Beauty": "שרלוט טילבורי", "Charlotte Tilbury": "שרלוט טילבורי",
    "Dior": "דיור", "DIOR": "דיור", "דיור (Dior)": "דיור",
    # 🔴 תוקן 06/09/2026 — המפה הזו קנוניזה **אל** התעתיקים השגויים ואל כתב לטיני,
    # ולכן דרסה בכל בנייה את מה שתוקן במסד. נמרוד לא מצא "רייר ביוטי" בסינון בדיוק בגלל זה.
    # הכיוון הפוך עכשיו: כל וריאציה מתלכדת לשם העברי הנכון.
    "YSL": "איב סן לורן", "ייב סן לורן": "איב סן לורן", "Yves Saint Laurent": "איב סן לורן",
    "M.A.C": "מאק", "Mac": "מאק", "MAC": "מאק",
    "Makeup for ever": "מייק אפ פור אבר", "Make Up For Ever": "מייק אפ פור אבר",
    "מייקאפ פוראבר": "מייק אפ פור אבר",
    "ONE/SIZE": "וואן סייז", "וואן/סייז": "וואן סייז", "וואן סייז (ONE/SIZE)": "וואן סייז",
    "Rhode": "רוד", "RHODE": "רוד", "רואד": "רוד", "רואד (RHODE)": "רוד",
    "Ordinary": "דה אורדינרי", "The Ordinary": "דה אורדינרי",
    "Saie": "סאיי", "SAIE": "סאיי",
    "SEPHORA": "ספורה", "Sephora Collection": "ספורה",
    # תתי-מותגים שפיצלו את הסינון לשלוש כרטיסיות נפרדות (נמרוד, 09/09)
    "ספורה קולקשן": "ספורה", "ספורה פייבוריטס": "ספורה",
    "Sephora Favorites": "ספורה", "SEPHORA COLLECTION": "ספורה",
    "אוארגלאס": "האורגלאס", "אוורגלאס": "האורגלאס", "Hourglass": "האורגלאס",
    # איחוד כפילויות איות (2026-07-12, כיוון תוקן 2026-09-06)
    "אורבן דקיי": "אורבן דיקיי",
    "סול דה ז'ניירו": "סול דה ז'נרו", "סול דה ז׳נרו": "סול דה ז'נרו",
    "Sol de Janeiro": "סול דה ז'נרו",
    "קיהל'ס": "קילס", "Kiehl's": "קילס", "KIEHL'S": "קילס",
    # תעתיקים שהיו חסרים לגמרי — מותגים שנשארו בלטינית ולכן לא נמצאו בסינון בעברית
    "ריר ביוטי": "רייר ביוטי", "Rare Beauty": "רייר ביוטי",
    "אנסטסיה בברלי הילס": "אנסטסיה בוורלי הילס", "Anastasia Beverly Hills": "אנסטסיה בוורלי הילס",
    "NYX": "נייקס", "NYX Professional Makeup": "נייקס",
    "K18": "קיי 18",
    "Glow Recipe": "גלואו רסיפי",
    "Gisou": "ג'יסו",
    "Mugler": "מוגלר",
    "Kryolan": "קריולן",
    "Too Faced": "טו פייסד",
    "Huda Beauty": "הודה ביוטי",
    "Color Wow": "קולור וואו", "ColorWow": "קולור וואו",
}
def norm_brand(b):
    if not b: return "אחר"
    return BRAND_MAP.get(b.strip(), b.strip())
# גזירת מותג משם המוצר כשהמותג חסר/"אחר" (מוצרי קליטה חדשים בפורמט "מותג – שם")
def brand_from_name(name):
    for sep in ("–", "—", " - "):
        if name and sep in name:
            return norm_brand(name.split(sep)[0].strip())
    return "אחר"

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
          "שקית נשיאה", "סכין גילוח", "גילוח", "עדשות מגע", "מראת", "אפליקטור", "פאף",
          "פיג'מה", "פיז'מה", "הלבשת שינה", "pajama"]   # אביזרים וכלים (כולל לייף-סטייל/הלבשה)
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
    # בושם מפורש בשם המוצר — גובר על מילות איפור אקראיות בתיאור
    # (מונע בושם-לגבר בקטגוריית איפור; "ספריי קיבוע" לא נתפס כי אין בו מילת בושם)
    nm_l = (nm + " " + str(p.get("name_en") or "")).lower()
    STRONG_FRAG = ["בושם", "בשמים", "או דה", "eau de", "edp", "edt", "parfum", "perfume", "cologne", "מבושם"]
    if any(w in nm_l for w in STRONG_FRAG):
        return "בושם"
    # טיפוח/שיער מפורש בשם — רק כשאין מילת איפור בשם (סרום-פאונדיישן יישאר איפור)
    _mk_in_name = any(w in nm_l for w in MAKEUP)
    STRONG_SKIN = ["סרום", "קרם לחות", "קרם עיניים", "קרם גוף", "קרם ידיים", "פילינג", "תרחיץ",
                   "טיפות לחות", "מסכת פנים", "מי פנים", "טונר", "serum", "moistur", "cleanser"]
    if not _mk_in_name and any(w in nm_l for w in STRONG_SKIN):
        return "טיפוח"
    STRONG_HAIR = ["שמפו", "מרכך", "מסכת שיער", "לשיער", "shampoo", "conditioner", "hair mask", "hair oil"]
    if not _mk_in_name and any(w in nm_l for w in STRONG_HAIR):
        return "שיער"
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

# --- ניקוי ביטויים פנימיים (שפת מחקר/בקרה) מטקסט מוצג ללקוח ---
# מוחק את המשפט/הסוגר הפוגע בלבד ושומר תוכן אמיתי. שדות "גודל" מתאפסים לגמרי.
_INTERNAL_MARKERS = [
    "טעון אימות", "טעונה אימות", "טעון בדיקה", "לא אומת", "לא אומתה", "טרם אומת",
    "לא נמצא", "לא נמצאה התאמה", "לא זוהה", "לא ידוע", "קוד ספק", "פריט פנימי",
    "בדף שנבדק", "בדף שנבדקה", "יש לאמת", "צריך לבדוק", "לברר מול",
    "לאמת מול", "לאימות מול", "אומת מול", "מקורות קמעונאיים",
    "מהאתר הרשמי", "מן האתר הרשמי", "רשימה מתוך מקורות",
    # ניסוחי "אין מידע" שהתגלו חיים בקטלוג (סריקה 2026-08-12): "לא פורסמה רשימת
    # רכיבים מלאה בדף הרשמי" וכד'. "לא פורסמ" תופס גם פורסם/פורסמה.
    "לא פורסמ", "לא צוינ", "לא צוין", "לא סופק", "לא מפורט", "לא הצלחנו",
    "בדף הרשמי", "בדף היצרן", "זמינה באתר היצרן", "זמין באתר היצרן",
]

def _has_internal(v):
    return isinstance(v, str) and any(m in v for m in _INTERNAL_MARKERS)

def strip_internal(text):
    """מסיר משפטים/סוגריים עם שפה פנימית, שומר את שאר הטקסט. מחזיר '' אם לא נשאר תוכן."""
    if not isinstance(text, str) or not text.strip():
        return text
    if not _has_internal(text):
        return text
    # 1) הסרת סוגריים שמכילים סמן פנימי:  (… טעון אימות)
    text = re.sub(r'\s*[\(（][^)）]*(?:' + '|'.join(map(re.escape, _INTERNAL_MARKERS)) + r')[^)）]*[\)）]', '', text)
    # 2) הסרת סיפא "– טעון אימות" / "- לא אומת …" עד סוף/מפריד
    text = re.sub(r'\s*[–—-]\s*[^.;\n]*(?:' + '|'.join(map(re.escape, _INTERNAL_MARKERS)) + r')[^.;\n]*', '', text)
    # 3) פיצול למשפטים והשמטת אלו שמכילים סמן פנימי
    parts = re.split(r'(?<=[.!?;])\s+|\n+', text)
    kept = [p for p in parts if not _has_internal(p)]
    out = re.sub(r'\s{2,}', ' ', ' '.join(kept)).strip(' .;–—-')
    return out

def detect_vegan(p):
    t = " ".join(str(p.get(k) or "") for k in ("ingredients", "description", "key_features")).lower()
    return "vegan" in t or "טבעוני" in t

# ---- order-file filter ----
def _nbc(x):
    """ברקוד → מפתח השוואה. אלפאנומרי נשמר (יש מותגים עם אותיות בברקוד, למשל
    ויקטוריהס סיקרט); ספרות בלבד מתנהג בדיוק כמו קודם — הסרת אפסים מובילים."""
    s = re.sub(r"[^0-9A-Za-z]", "", str(x or "")).upper()
    return (s.lstrip("0") or s) if s.isdigit() else s
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
        # 🔴 תוקן 09/09/2026 — ב-1,080 קבצי ידע שדה `shade` מכיל את **שם המוצר המלא**
        # ולא את הגוון בלבד. ההסרה העיוורת מחקה את כל השם, הבסיס יצא ריק,
        # ו-730 מוצרים לא קובצו כלל — כל אחד קיבל כרטיס נפרד.
        # לכן: מסירים רק אם נשאר בסיס משמעותי.
        trial = re.sub(re.escape(sh), "", base, flags=re.I).strip()
        if len(trial) >= 6:
            base = trial
    base = re.sub(r"\([^)]*\)", " ", base)             # strip parenthetical shade e.g. "(גוון X)"
    # 🔴 תוקן 09/09/2026 — אותו מוצר הופיע בכרטיסים נפרדים במקום ככרטיס אחד עם גוונים.
    # שתי סיבות, ושתיהן מטופלות כאן:
    #   1. חלק מהשמות נושאים "בגוון X" בגוף השם. שדה `shade` מכיל תיאור מלא
    #      ("321 Ophélie (ורוד-פוקסיה…)") שאינו מופיע מילולית בשם, ולכן ההסרה למעלה
    #      לא תפסה אותו. חותכים מ"בגוון" והלאה.
    #   2. סדר המילים משתנה בין "Petal Soft עיפרון שפתון" ל"עיפרון שפתון Petal Soft",
    #      ולכן מיון המילים הופך את הבסיס לחסין לסדר.
    # נמדד: 39 קבוצות שנשברו לשווא התאחדו, ואפס איחודי שווא (נבדקו 21 חשודים —
    # כולם אותו מוצר בגוונים שונים).
    cut = re.sub(r"בגוון\s+.*$", " ", base)
    had_shade_phrase = (cut != base)      # "בגוון X" נמצא והוסר — הגוון כבר מחוץ לבסיס
    base = re.sub(r"גוון\s*[^\s,–\-]*", " ", cut)
    base = re.sub(r"#?\d+\b", " ", base)              # drop numeric shade codes
    base = re.sub(r"\s+", " ", base).strip()
    # ⚠️ `_strip_trailing_shade` חותכת את המילה האחרונה בהנחה שהיא גוון. אחרי שכבר
    # חתכנו "בגוון X" זו הנחה שגויה — היא אכלה את ה-"Soft" מתוך "Petal Soft"
    # והשאירה את המוצר מפוצל לשני כרטיסים. מריצים אותה רק כשלא חתכנו קודם.
    if not had_shade_phrase:
        base = _strip_trailing_shade(base)
    base = re.sub(r"[\s\-–/]+$", "", base).strip().lower()
    # פיסוק דבוק למילה ("Dimension," מול "Dimension") שבר קיבוץ — מנקים לכל אסימון
    base = " ".join(sorted(w.strip(",.;:·|") for w in base.replace("–", " ").split() if w.strip(",.;:·|")))
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

# ===========================================================================
#  🛒 דף הזמנה מהירה — order.html (16/09/2026)
# ---------------------------------------------------------------------------
#  נמרוד: "קטלוג שאפשר לסמן כמויות זריז, לשתף אינטרנטי, ואז לוואטסאפ שלנו
#  לשלוח את הכמויות. תמונה חשוב, ואולי כמה מילים כמו באתר."
#
#  🔑 העיקרון: **אותו קוד בדיוק כמו האתר.** הסל, הקוד הסיטונאי, המלאי החי,
#  יצירת ההזמנה וטקסט הוואטסאפ נחתכים מתוך TEMPLATE **בזמן הבנייה** (לפי
#  עוגנים ייחודיים — _slice) ומודבקים לדף. TEMPLATE עצמו לא זז, ולכן
#  index.html נשאר זהה ביט-לביט, ואין שתי גרסאות של אותה לוגיקה שיסטו זו
#  מזו. עוגן שנעלם — הבנייה נופלת בקול, לא בשקט.
#
#  הדף מקבל רשימת מוצרים מצומצמת **באותו מבנה** של האתר (gid/variants/id/
#  barcode/imgs…), ולכן VMAP, eff, restoreCart ו-createOrder רצים כמו שהם.
#  אותם מפתחות ב-localStorage (bf_cart_v1, wholesale_code) — אותו לקוח,
#  אותו סל, אותו קוד סיטונאי בשני הדפים.
#
#  קישור ממוקד: order.html#b=מותג|מותג&c=קטגוריה&t=כותרת — הדף מציג רק אותם.
#  הקוד הסיטונאי לעולם לא בקישור; הלקוח מקליד אותו בדף.
# ===========================================================================

def _slice(src, start, end):
    """קטע מתוך התבנית — מתחילת `start` (חייב להופיע פעם אחת) ועד `end` (לא כולל)."""
    n = src.count(start)
    if n != 1:
        raise RuntimeError(f"עוגן לא יחיד ({n}): {start[:50]!r}")
    i = src.index(start)
    j = src.find(end, i + len(start))
    if j < 0:
        raise RuntimeError(f"עוגן סיום לא נמצא: {end[:50]!r}")
    return src[i:j]


def _lead(v, limit=120):
    """השורה המקדימה: summary מכרטיס הידע; בהיעדרו — המשפט הראשון של התיאור."""
    s = str(v.get("summary") or "").strip()
    if not s:
        d = str(v.get("desc") or "").strip()
        m = re.match(r"(.+?[.!?])(\s|$)", d)
        s = (m.group(1) if m else d).strip()
    if len(s) > limit:
        s = s[:limit - 1].rstrip() + "…"
    return s


ORDER_TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Beauty Favorites — הזמנה מהירה</title>
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="#3b2b20">
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.3/dist/umd/supabase.js" integrity="sha384-BWcjm9OdFth9TbhCxZPdm+gAOUMAzQy9nmTs12ioXdCcbVnJaPMn+fMUoQCLt60R" crossorigin="anonymous"></script>
<script>window.SUPA=__SUPABASE_CONFIG__;</script>
<link rel="icon" type="image/png" href="favicon-bf.png">
<link rel="apple-touch-icon" href="favicon-bf.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;700;900&display=swap" rel="stylesheet">
<style>
/*__SITE_CSS__*/
/* ===== דף ההזמנה המהירה ===== */
body{padding-bottom:90px}
.qo-top{position:sticky;top:0;z-index:60;background:rgba(255,255,255,.96);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);padding:8px 12px 10px}
.qo-head{display:flex;align-items:center;gap:10px;justify-content:space-between;margin-bottom:8px;max-width:760px;margin-inline:auto}
.qo-title{font-family:var(--font);font-size:22px;line-height:1.1;min-width:0}
.qo-ws{font-family:var(--font);font-size:12.5px;font-weight:600;padding:7px 12px;border-radius:30px;border:1px solid var(--border2);background:#fff;cursor:pointer;white-space:nowrap}
.qo-tools{display:flex;gap:6px;flex-wrap:wrap;align-items:center;max-width:760px;margin:0 auto}
.qo-tools input[type=search]{flex:1 1 150px;font-family:var(--font);font-size:16px;padding:9px 12px;border:1px solid var(--border2);border-radius:12px;min-width:0}
.qo-tools select{font-family:var(--font);font-size:13px;padding:8px 10px;border:1px solid var(--border2);border-radius:12px;background:#fff;max-width:44vw}
.qo-count{font-size:12px;color:var(--muted);white-space:nowrap}
.qo-row{display:flex;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--border);max-width:760px;margin:0 auto}
.qo-img{width:56px;height:56px;flex:0 0 56px;object-fit:contain;border:1px solid var(--border);border-radius:10px;background:#fff}
.qo-noimg{display:flex;align-items:center;justify-content:center;color:var(--accent-l);opacity:.5;font-size:22px}
.qo-main{flex:1;min-width:0}
.qo-nm{font-size:14px;font-weight:600;line-height:1.3}
.qo-meta{font-size:12px;color:var(--muted);margin-top:1px}
.qo-lead{font-size:12.5px;color:#4b4b4b;line-height:1.35;margin-top:3px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.qo-side{display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex:0 0 auto}
.qo-add{font-family:var(--font);font-size:13px;font-weight:600;padding:6px 12px;border-radius:20px;border:1px solid var(--border2);background:var(--accent-soft);color:var(--accent-d);cursor:pointer;white-space:nowrap}
.qo-empty{padding:40px 16px;text-align:center;color:var(--muted)}
</style>
</head>
<body>

<header class="qo-top">
  <div class="qo-head">
    <div class="qo-title" id="qoTitle">Beauty Favorites — הזמנה מהירה</div>
    <button class="qo-ws" id="pbWholesale" onclick="openWholesale()">💼 מועדון עסקים</button>
  </div>
  <div class="qo-tools">
    <input id="q" type="search" autocomplete="off" placeholder="חיפוש מוצר / מותג / ברקוד…" oninput="render()">
    <select id="brandSel" onchange="render()"></select>
    <select id="catSel" onchange="render()"></select>
    <span class="qo-count" id="rescount"></span>
  </div>
</header>

<div class="wsbanner" id="wsBanner" style="display:none">
  <span id="wsBannerTxt">מצב סיטונאי פעיל — מוצגים מחירי סיטונאי (לפני מע"מ) ומחיר צרכן מומלץ</span>
  <button onclick="wholesaleLogout()">יציאה</button>
</div>

<main id="list"></main>

<div class="cartbar" id="cartbar"><span class="sum" id="cartsum"></span><button onclick="openOrder()">📲 שלח הזמנה בוואטסאפ</button></div>

<div class="ov" id="orderModal"><div class="sheet">
  <button class="x" onclick="closeOrder()">✕</button>
  <div class="om">
    <h3>ההזמנה שלי</h3>
    <div id="omBody"></div>
    <div class="totals" id="totals"></div>
    <form class="form" autocomplete="on" onsubmit="return false">
      <h4>פרטי המזמין</h4>
      <div class="f-row" id="row-name">
        <label for="buyer-name">שם מלא</label>
        <input class="fld" id="buyer-name" name="name" type="text" autocomplete="name" oninput="clearErr('row-name');saveBuyer()">
        <span class="f-err" id="er-name"></span>
      </div>
      <div class="f-row" id="row-phone">
        <label for="buyer-phone">טלפון נייד</label>
        <input class="fld" id="buyer-phone" name="tel" type="tel" inputmode="tel" autocomplete="tel-national" oninput="clearErr('row-phone');saveBuyer()">
        <span class="f-err" id="er-phone"></span>
      </div>
      <div class="f-row">
        <label for="buyer-id">שם העסק / ח.פ <span class="opt">(לא חובה)</span></label>
        <input class="fld" id="buyer-id" type="text" oninput="saveBuyer()">
      </div>
      <div class="f-row">
        <label for="notes">הערות <span class="opt">(לא חובה)</span></label>
        <textarea class="notes" id="notes" oninput="saveBuyer()"></textarea>
      </div>
      <button type="button" class="send" id="sendBtn" onclick="submitWhatsApp()">📲 שלח הזמנה בוואטסאפ</button>
    </form>
  </div>
</div></div>

/*__WS_MODALS__*/
<script>
const GROUPS = /*__GROUPS__*/;
// 🗂️ 06/10/2026 — אותו עץ קטגוריות של האתר. בורר הקטגוריה הוא רשימה
// עם קבוצות (optgroup): "הכול בפנים" ואז תתי-הקטגוריות. הקישור הממוקד
// c= מקבל slug של תת-קטגוריה או m:<קבוצה>. ריק = נופל לסוגים הישנים.
const CATTREE = /*__CATTREE__*/;
const CT_MAIN={},CT_BY={};
CATTREE.forEach(function(g){CT_BY[g.m]=g;g.subs.forEach(function(sb){CT_MAIN[sb.s]=g.m;});});
const HAS_TREE=CATTREE.length>0;
function catMatch(g,c){   // c: '' · 'm:<קבוצה>' · '<slug>' · (ללא עץ) סוג ישן
  if(!c)return true;
  if(!HAS_TREE)return g.type===c;
  if(c.indexOf('m:')===0)return CT_MAIN[g.cs||'']===c.slice(2);
  return g.cs===c;
}
const LINK = readLinkParams();

// המילים שהקוד המשותף מבקש דרך t() — אותם ערכים כמו באתר (עברית בלבד כאן)
const I18N_HE={cart_items:'פריטים',cons_rec:'מומלץ לצרכן:',ws_unavailable:'לא זמין כרגע',ws_bad:'קוד שגוי',
  ws_exit:'יציאה ממצב סיטונאי',club_link:'💼 מועדון עסקים',subtotal:'סכום ביניים',discount:'הנחה',vat:'מע"מ 18%',
  incl_vat:'המחירים כוללים מע"מ',grand:'סה"כ לתשלום',alert_empty:'העגלה ריקה',
  alert_fill:'נא למלא שם מלא וטלפון לפני שליחת ההזמנה',
  err_phone:'מספר טלפון לא תקין — נייד 10 ספרות (05X) או קווי 9 ספרות',
  err_order:'אירעה תקלה ביצירת ההזמנה. נסה שוב.',sending:'שולח…',cart_empty:'העגלה ריקה'};
function t(k){return I18N_HE[k]!=null?I18N_HE[k]:k;}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function aesc(s){return String(s).replace(/"/g,'&quot;')}

// דברים שהקוד המשותף מזכיר ויש רק באתר (קופון, כתובת משלוח, יישוב) — כאן ריקים.
// ⚠️ shipParts מחזיר את **כל** המפתחות עם null: create_order במסד מצפה לסט
//    הארגומנטים המלא, ומפתח חסר (undefined) היה נשמט מהבקשה.
var activeCoupon=null; function discount(){return 0;} function shipLine(){return '';}
function shipParts(){return {city:null,cityCode:null,street:null,streetCode:null,house:null,apt:null,floor:null,entrance:null};}
var CITY=null, STREET_CODE=null;

// ===== מכאן — קוד האתר, כמות שהוא (נחתך מ-TEMPLATE בזמן הבנייה) =====
/*__JS_VMAP_EFF__*/
/*__JS_PRICE_HTML__*/
/*__JS_CART_CORE__*/
/*__JS_WHOLESALE_UI__*/
/*__JS_CART_PERSIST__*/
/*__JS_FORM_ERRORS__*/
/*__JS_QTY_TOTALS__*/
/*__JS_ORDER_CORE_A__*/
/*__JS_ORDER_CORE_B__*/
/*__JS_OVERLAY__*/
// ===== עד כאן קוד האתר =====

// קישור ממוקד: #b=מותג|מותג&c=קטגוריה&t=כותרת
function readLinkParams(){
  var p=new URLSearchParams((location.hash||'').replace(/^#/,''));
  var b=(p.get('b')||'').split('|').map(function(s){return s.trim();}).filter(Boolean);
  return {brands:b,cat:(p.get('c')||'').trim(),title:(p.get('t')||'').trim(),catApplied:false};
}
function validateBuyer(){
  if(!Object.keys(CART).length){alert(t('alert_empty'));return false;}
  ['row-name','row-phone'].forEach(clearErr);
  var first=null; var fail=function(row,er,msg){var r=setErr(row,er,msg);if(!first)first=r;};
  var name=gv('buyer-name'),phone=gv('buyer-phone');
  if(!name)fail('row-name','er-name',t('alert_fill'));
  if(!phone)fail('row-phone','er-phone',t('alert_fill'));
  else if(!validPhone(phone))fail('row-phone','er-phone',t('err_phone'));
  if(first){first.scrollIntoView({block:'center'});var i=first.querySelector('input');if(i)i.focus();return false;}
  return true;
}
function openOrder(){renderOrder();openOv('orderModal')}
function closeOrder(){closeOv('orderModal')}
function renderOrder(){
  var keys=Object.keys(CART), body=document.getElementById('omBody');
  if(!keys.length){body.innerHTML='<p style="text-align:center;color:var(--muted);padding:20px">'+t('cart_empty')+'</p>';renderTotals();return;}
  body.innerHTML=keys.map(function(k){var it=CART[k],m=VMAP[k],im=(m&&m.v.imgs&&m.v.imgs[0])||'';
    return `<div class="om-row">${im?`<img class="om-img" src="${aesc(im)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`:'<span class="om-img"></span>'}
      <div class="nm">${esc(it.name)}<small>${esc(it.brand)}${it.size?' · '+esc(it.size):''}</small></div>
      <div class="qy"><button type="button" onclick="cartChange('${aesc(k)}',-1)">−</button><input class="qin" type="number" inputmode="numeric" min="1" value="${it.qty}" onfocus="this.select()" onchange="cartSetQty('${aesc(k)}',Math.max(1,parseInt(this.value,10)||1))"><button type="button" onclick="cartChange('${aesc(k)}',1)">+</button></div>
      <div class="lt">₪${it.qty*it.price}</div>
      <button type="button" class="om-del" onclick="cartChange('${aesc(k)}',-${it.qty})">✕</button></div>`;}).join('');
  renderTotals();
}
function visibleVariants(){
  var q=(document.getElementById('q').value||'').trim().toLowerCase();
  var b=document.getElementById('brandSel').value, c=document.getElementById('catSel').value, out=[];
  GROUPS.forEach(function(g){
    if(LINK.brands.length&&LINK.brands.indexOf(g.brand)<0)return;
    if(b&&g.brand!==b)return; if(!catMatch(g,c))return;
    g.variants.forEach(function(v){
      if(SB&&STOCK_READY&&isSold(v))return;      // רק מה שבמלאי
      if(q){var hay=(g.name_he+' '+g.brand+' '+(v.shade||'')+' '+(v.barcode||'')).toLowerCase();if(hay.indexOf(q)<0)return;}
      out.push({g:g,v:v});
    });
  });
  return out;
}
function sideHtml(g,v){
  var it=CART[v.id], id=aesc(v.id);
  var q=it?`<div class="qy"><button type="button" onclick="cartChange('${id}',-1)">−</button><span>${it.qty}</span><button type="button" onclick="cartChange('${id}',1)">+</button></div>`
          :`<button type="button" class="qo-add" onclick="cartChange('${id}',1)">+ הוסף</button>`;
  return priceHtml(v)+q;   // בסיטונאי — priceHtml מוסיף מעצמו "מומלץ לצרכן"
}
function rowHtml(g,v){
  var multi=g.variants.length>1, nm=esc(g.name_he)+(multi&&v.shade?' · '+esc(v.shade):'');
  var meta=[g.brand,v.size].filter(Boolean).map(esc).join(' · ');
  var im=(v.imgs&&v.imgs[0])?`<img class="qo-img" src="${aesc(v.imgs[0])}" loading="lazy" alt="" onerror="this.style.visibility='hidden'">`:'<span class="qo-img qo-noimg">✦</span>';
  return `<div class="qo-row" data-gid="${aesc(g.gid)}">${im}<div class="qo-main"><div class="qo-nm">${nm}</div><div class="qo-meta">${meta}</div>${v.lead?`<div class="qo-lead">${esc(v.lead)}</div>`:''}</div><div class="qo-side" id="side-${aesc(v.id)}">${sideHtml(g,v)}</div></div>`;
}
function render(){
  var list=document.getElementById('list'), rc=document.getElementById('rescount');
  if(SB&&!STOCK_READY){list.innerHTML='<div class="qo-empty">טוען מלאי…</div>';rc.textContent='';return;}
  var rows=visibleVariants();
  rc.textContent=rows.length+' מוצרים';
  list.innerHTML=rows.length?rows.map(function(x){return rowHtml(x.g,x.v);}).join(''):'<div class="qo-empty">לא נמצאו מוצרים</div>';
}
function updateCard(gid){   // הסל השתנה — רק צד הכמות של השורות משתנה, בלי לצייר הכול מחדש
  var g=GROUPS.find(function(x){return x.gid===gid;});if(!g)return;
  g.variants.forEach(function(v){var el=document.getElementById('side-'+v.id);if(el)el.innerHTML=sideHtml(g,v);});
}
function buildNav(){   // בוררי מותג/קטגוריה — רק מה שיש בו מלאי, ובקישור ממוקד רק המותגים שבו
  var bs=document.getElementById('brandSel'), cs=document.getElementById('catSel'), bset={}, cset={};
  GROUPS.forEach(function(g){
    if(LINK.brands.length&&LINK.brands.indexOf(g.brand)<0)return;
    if(!g.variants.some(function(v){return !(SB&&STOCK_READY&&isSold(v));}))return;
    bset[g.brand]=1; if(g.type)cset[g.type]=1; if(g.cs)cset['s:'+g.cs]=1;
  });
  var fill=function(sel,vals,all){var cur=sel.value;sel.innerHTML='<option value="">'+esc(all)+'</option>'+vals.map(function(x){return '<option value="'+aesc(x)+'">'+esc(x)+'</option>';}).join('');if(vals.indexOf(cur)>=0)sel.value=cur;};
  fill(bs,Object.keys(bset).sort(function(a,b){return a.localeCompare(b,'he');}),LINK.brands.length?'כל המותגים בקישור':'כל המותגים');
  if(HAS_TREE){
    // רק קבוצות ותתי-קטגוריות שיש בהן מוצר במלאי — אותו כלל כמו באתר
    var cur=cs.value, h='<option value="">כל הקטגוריות</option>', ok={};
    CATTREE.forEach(function(g){
      var subs=g.subs.filter(function(sb){return cset['s:'+sb.s];});
      if(!subs.length)return;
      h+='<optgroup label="'+aesc(g.he)+'"><option value="m:'+aesc(g.m)+'">הכול ב'+esc(g.he)+'</option>';
      ok['m:'+g.m]=1;
      subs.forEach(function(sb){h+='<option value="'+aesc(sb.s)+'">'+esc(sb.he)+'</option>';ok[sb.s]=1;});
      h+='</optgroup>';
    });
    cs.innerHTML=h; if(ok[cur])cs.value=cur;
    if(LINK.cat&&!LINK.catApplied&&ok[LINK.cat]){cs.value=LINK.cat;LINK.catApplied=true;}
  } else {
    var flat=Object.keys(cset).filter(function(k){return k.indexOf('s:')!==0;});
    fill(cs,flat.sort(function(a,b){return a.localeCompare(b,'he');}),'כל הקטגוריות');
    if(LINK.cat&&!LINK.catApplied&&cset[LINK.cat]){cs.value=LINK.cat;LINK.catApplied=true;}
  }
}
function restoreBuyerLite(){   // שם, טלפון, עסק והערות — מאותה שמירה של האתר
  try{var d=JSON.parse(localStorage.getItem(BUYER_KEY)||'null');if(!d)return;
    ['buyer-name','buyer-phone','buyer-id','notes'].forEach(function(id){var e=document.getElementById(id);if(e&&d[id])e.value=d[id];});}catch(e){}
}
(function init(){
  if(LINK.title){document.getElementById('qoTitle').textContent=LINK.title;document.title=LINK.title+' — Beauty Favorites';}
  restoreBuyerLite(); updateWsUI(); buildNav(); restoreCart(); render();
  if(SB)loadStock();   // מלאי ומחירים חיים; בסיום — buildNav + render מחדש (כמו באתר)
})();
window.addEventListener('hashchange',function(){location.reload();});   // קישור אחר (מותגים/כותרת) = דף טרי
</script>
</body>
</html>
"""


def build_order_page(groups, supa_cfg, site_url="", cat_tree=None):
    """דף ההזמנה המהירה — מאותם נתונים ומאותו קוד של האתר."""
    slim = []
    for g in groups:
        vs = []
        for v in g["variants"]:
            vs.append({"id": v["id"], "shade": v.get("shade") or "", "price": v.get("price"),
                       "sale": v.get("sale"), "was": v.get("was"), "size": v.get("size") or "",
                       "barcode": v.get("barcode") or "", "imgs": list(v.get("imgs") or [])[:1],
                       "lead": _lead(v)})
        slim.append({"gid": g["gid"], "name_he": g["name_he"], "brand": g["brand"],
                     "type": g.get("type") or "", "cs": g.get("cs") or "", "variants": vs})
    T = TEMPLATE
    css = _slice(T, "\n<style>\n", "\n</style>\n")[len("\n<style>\n"):]
    parts = {
        "SITE_CSS":         css,
        "WS_MODALS":        _slice(T, '<div class="ov" id="clubModal">', '<nav class="bnav" id="bnav">'),
        "JS_VMAP_EFF":      _slice(T, "const VMAP={};", "\nconst BADGE_LABEL"),
        "JS_PRICE_HTML":    _slice(T, "function priceHtml(v,cls){", "function lowStockHtml(v){"),
        "JS_CART_CORE":     _slice(T, "const CART={};", "/* קופונים: מאומתים בשרת"),
        "JS_WHOLESALE_UI":  _slice(T, "/* ===== מצב סיטונאי", "function openOrder(){"),
        "JS_CART_PERSIST":  _slice(T, "const SAVE_KEY='bf_cart_v1'", "function restoreBuyer(){"),
        "JS_FORM_ERRORS":   _slice(T, "function clearErr(rowId)", "function checkPhone(){"),
        "JS_QTY_TOTALS":    _slice(T, "function cartSetQty(vid,n)", "const WA_NUMBER='972534555501';"),
        "JS_ORDER_CORE_A":  _slice(T, "const WA_NUMBER='972534555501';", "function validateBuyer(needEmail){"),
        "JS_ORDER_CORE_B":  _slice(T, "function setBusy(btn,on)", '// ב) "שלם עכשיו"'),
        "JS_OVERLAY":       _slice(T, "var __ovReturnFocus=null;", "// ===== store policies"),
    }
    out = ORDER_TEMPLATE
    for k, v in parts.items():
        out = out.replace(f"/*__{k}__*/", v)
    out = out.replace("/*__GROUPS__*/", _js(slim))
    out = out.replace("/*__CATTREE__*/", _js(cat_tree or []))
    out = out.replace("__SUPABASE_CONFIG__", _js(supa_cfg))
    out = out.replace("__SITE_URL__", (site_url or "").rstrip("/"))
    return out


def main():
    # מצב מהיר (--fast או FAST=1): לא מוחק ולא מעבד מחדש תמונות קיימות — רק בונה index.html.
    # מתאים לשינויי קוד/HTML בלבד. תמונות חדשות עדיין יעובדו (אם חסרות ביעד).
    fast = ("--fast" in sys.argv) or (os.environ.get("FAST") == "1")
    # --out DIR: לכתוב את הדפים לתיקייה אחרת (לבדיקות/השוואה) בלי לגעת ב-catalog/
    out_dir = CAT
    if "--out" in sys.argv:
        out_dir = os.path.abspath(sys.argv[sys.argv.index("--out") + 1])
        os.makedirs(out_dir, exist_ok=True)
    # 🖼️ 13/10/2026 — כבר לא מרוקנים את התיקייה בבנייה מלאה: יושבות בה גם תמונות של מוצרים
    #    שלא נקלטו (1,277 — הבק אופיס מציג אותן מהאתר), והבנייה בונה רק לנקלטים. ריקון + פרסום
    #    היה מוחק אותן מהאתר. בנייה מלאה עכשיו = עיבוד מחדש ודריסה של מה שנבנה, בלי מחיקה.
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
    db_content = fetch_db_content()   # הבק אופיס = מקור אמת לטקסטים
    # 🧪 --overlay FILE — **לתצוגה מקדימה בלבד**: מחיל את ההרצה היבשה (סוג/קטגוריה/תכונות)
    #    על התוכן מהמסד בזיכרון, כדי שנמרוד יראה את התוצאה לפני שכותבים למסד.
    #    לעולם לא בבנייה לפרסום — הדגל מסרב לרוץ כשהפלט הוא catalog/ עצמו.
    if "--overlay" in sys.argv:
        if os.path.abspath(out_dir) == os.path.abspath(CAT):
            raise SystemExit("⛔ --overlay אסור בבנייה לתיקיית catalog/ — רק עם --out לתצוגה מקדימה")
        ovl = json.load(open(sys.argv[sys.argv.index("--overlay") + 1], encoding="utf-8"))
        for sku, ch in ovl.items():
            row = db_content.get(_nbc(sku)) if db_content else None
            if row is not None:
                row.update(ch)
        print(f"🧪 overlay (תצוגה מקדימה): {len(ovl)} מוצרים")
    cat_tree = fetch_categories()     # 🗂️ עץ שתי הרמות — מחליף את CATS השטוח
    excluded = []
    raw = []   # individual products (variants)

    for pj in sorted(glob.glob(os.path.join(KNOW, "[0-9]*", "product.json")),
                     key=lambda x: int(os.path.basename(os.path.dirname(x)).split("-")[0])):
        d = os.path.dirname(pj); pid = os.path.basename(d)
        try:
            p = json.load(open(pj, encoding="utf-8"))
        except Exception as e:
            print("skip", pj, e); continue
        p = overlay_db_content(p, db_content.get(_nbc(p.get("barcode"))))

        # 🚫 05/10/2026 — "לא לפרסום".
        # ציוד החנות (כיסא לקוח · כיסא איפור · שולחן מניקור) נכנס לקטלוג
        # מרשימת המועמדים "אולי נזמין" של 1,846 השורות — קיבל כרטיס ידע,
        # תמונות, ונבנה לדף כמו כל מוצר. **כיבוי במסד לא הוציא אותו משם**,
        # כי הבנייה קוראת מתיקיית הידע ולא מדגל `active` שבמסד: שני
        # מקורות, ורק אחד מהם נוקה. מי שאינו מוצר מדף — לא נכנס לדף.
        if p.get("publish") is False:
            excluded.append(pid + " (לא לפרסום)")
            continue

        # 📦 06/10/2026 — "מעולם לא נקלט פיזית" לא נבנה לדף (נמרוד, דרך הניהול).
        # 1,363 מוצרים מרשימת המועמדים הישנה נשאו נתונים בדף בלי שלקוחה תראה
        # אותם אי פעם — 968 כרטיסים בלתי נראים שהכבידו על הטלפון. **הם לא
        # נמחקים:** כרטיס הידע והשורה במסד נשארים כפי שהם, וביום שהמוצר ייקלט
        # (stocked_ever=true) הוא חוזר לדף לבד בבנייה הבאה.
        # 🔒 רק כשהמסד באמת נטען — בלי רשת db_content ריק, וסינון כאן היה
        #    מרוקן את כל האתר.
        if db_content:
            _row = db_content.get(_nbc(p.get("barcode")))
            if not _row or _row.get("stocked_ever") is not True:
                excluded.append(pid + (" (מעולם לא נקלט)" if _row else " (אין במסד)"))
                continue

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
            # ☁️ 12/10/2026 — כפילויות אייקלאוד ("01 2.jpg") לא נבנות: הן אינן בריפו (הפרסום מחריג
            #    "* 2") ולכן נשברות באתר (כרטיס מורפי הציג "מ" במקום תמונה — הקובץ הראשון היה "01 2.jpg").
            files = sorted(f for f in os.listdir(src)
                           if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                           and not re.search(r" \d+\.[a-z]+$", f, re.I)
                           and f not in HIDDEN_IMAGES.get(pid, {}))   # 🚫 לא מקצועית — לא לאתר
            if files:
                os.makedirs(os.path.join(IMGDIR, pid), exist_ok=True)
            for f in files:
                dst = os.path.join(IMGDIR, pid, f)
                if not (fast and os.path.exists(dst)):   # מצב מהיר: דלג אם התמונה כבר קיימת
                    optimize_image(os.path.join(src, f), dst)
                imgs.append(f"images/{pid}/{f}")

        # 🖼️ כלל קבוע (הכרעת נמרוד 06/10): **מוצר בלי אף תמונה לא נבנה לדף** — עד
        #    שמגיעה תמונה מקצועית. נשאר פעיל בבק ובדוחות; ביום שתמונה נכנסת ל-knowledge/
        #    הכרטיס חוזר לבד. חל גם על מי שאיבד את כל התמונות לרשימת ההסתרה.
        if not imgs:
            excluded.append(pid + " (בלי תמונה)")
            continue

        brand = norm_brand(p.get("brand"))
        if brand == "אחר":                          # מותג חסר → נסה לגזור משם המוצר
            brand = brand_from_name(p.get("name_he") or "")
        ov = overrides.get(str(p.get("barcode") or ""), {})
        badges = list(ov.get("badges") or [])
        sale = whole_price(ov.get("sale_price")) if ov.get("sale_price") not in (None, "") else None
        if sale: badges = (["sale"] + badges) if "sale" not in badges else badges
        # מחיר-לפני (price_before בקובץ הידע): מוצג עם קו-חוצה + תג "מבצע" במצב צרכן בלבד
        was = whole_price(p.get("price_before")) if p.get("price_before") not in (None, "") else None
        if was and "sale" not in badges: badges = ["sale"] + badges
        if detect_vegan(p): badges.append("vegan")

        raw.append({
            "id": pid,
            "name_he": p.get("name_he") or p.get("name_en") or pid,
            "name_en": p.get("name_en") or "",
            "brand": brand,
            "type": ptype(p),
            "price": whole_price(p.get("price_ils")),
            "sale": sale,
            "was": was,
            "size": strip_internal(p.get("size") or ""),
            "shade": ("" if _has_internal(p.get("shade")) else (p.get("shade") or "")),
            "barcode": p.get("barcode") or "",
            "desc": strip_internal(p.get("description") or ""),
            "summary": strip_internal(p.get("summary") or ""),
            "summary_ar": strip_internal(p.get("summary_ar") or ""),
            "features": [strip_internal(f) for f in (p.get("key_features") or []) if strip_internal(f)],
            "ingredients": strip_internal(p.get("ingredients") or ""),
            "usage": strip_internal(p.get("usage") or ""),
            "desc_ar": strip_internal(p.get("description_ar") or ""),
            "features_ar": [strip_internal(f) for f in (p.get("features_ar") or []) if strip_internal(f)],
            "usage_ar": strip_internal(p.get("usage_ar") or ""),
            "ingredients_ar": strip_internal(p.get("ingredients_ar") or ""),
            "shade_ar": ("" if _has_internal(p.get("shade")) else (p.get("shade_ar") or "")),
            "contents": p.get("contents") or [],
            "contents_ar": p.get("contents_ar") or [],
            "imgs": imgs,
            "badges": badges,
            "color": p.get("shade_hex") or shade_color(p.get("shade") or "", is_complexion(p)),
            "cslug": p.get("_cslug") or "",
            "stype": p.get("_stype") or "",
            "isset": bool(p.get("_isset")),
            "attrs": p.get("_attrs") or {},
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
                "sale": p["sale"], "was": p.get("was"), "size": p["size"], "barcode": p["barcode"], "imgs": p["imgs"],
                "desc": p["desc"], "features": p["features"], "ingredients": p["ingredients"],
                "usage": p["usage"], "badges": p["badges"], "color": p.get("color")}
        if p.get("summary"): d["summary"] = p["summary"]
        if p.get("summary_ar"): d["summary_ar"] = p["summary_ar"]
        if p.get("desc_ar"): d["desc_ar"] = p["desc_ar"]
        if p.get("features_ar"): d["features_ar"] = p["features_ar"]
        if p.get("usage_ar"): d["usage_ar"] = p["usage_ar"]
        if p.get("contents"): d["contents"] = p["contents"]
        if p.get("contents_ar"): d["contents_ar"] = p["contents_ar"]
        if p.get("ingredients_ar"): d["ingredients_ar"] = p["ingredients_ar"]
        if p.get("shade_ar"): d["shade_ar"] = p["shade_ar"]
        return d
    # --- שם המותג באנגלית, לתצוגה לצד השם העברי ---
    # נכתב במפורש ולא נגזר אוטומטית: ניסיון לגזור אותו מתוך name_en החזיר שמות
    # של קווי מוצר ולא של מותגים ("Plump Ambition" ללוריאל, "Vanish Airbrush"
    # להאורגלאס). 79 מותגים זו רשימה קטנה שעדיף לכתוב ולתחזק ביד.
    # ⚠️ זו תצוגה בלבד — `name_en` של המוצר אינו נוגע, כי הוא עוגן זהות שלפיו
    # מצליבים מול הספק ומול אתרי המותגים.
    BRAND_EN = {
        "אי.אל.אף": "e.l.f.", "הודה ביוטי": "HUDA BEAUTY", "מייבלין": "Maybelline",
        "נארס": "NARS", "שרלוט טילבורי": "Charlotte Tilbury", "שרלוט טילברי": "Charlotte Tilbury",
        "פנטי ביוטי": "FENTY BEAUTY", "לורה מרסייה": "Laura Mercier", "ריר ביוטי": "Rare Beauty",
        "טו פייסד": "Too Faced", "אנסטסיה בברלי הילס": "Anastasia Beverly Hills",
        "אנסטסיה": "Anastasia Beverly Hills", "פיקסי": "Pixi", "מורפי": "Morphe", "מורף": "Morphe",
        "בנפיט": "Benefit", "קייאלי": "KAYALI", "לוריאל": "L'Oréal Paris",
        "לוריאל פריז": "L'Oréal Paris", "לוריאל פריס": "L'Oréal Paris",
        "פטריק טא": "PATRICK TA", "מילק מייקאפ": "Milk Makeup", "האורגלאס": "HOURGLASS",
        "ויקטוריה סיקרט": "Victoria's Secret", "ארמני": "Giorgio Armani",
        "ספורה": "SEPHORA", "ספורה קולקשן": "SEPHORA COLLECTION",
        "Sephora Collection": "SEPHORA COLLECTION", "ספורה פייבוריטס": "SEPHORA Favorites",
        "קוסאס": "Kosas", "בוי סמלס": "Boy Smells", "NYX": "NYX Professional Makeup",
        "נטשה דנונה": "Natasha Denona", "דראנק אלפנט": "Drunk Elephant",
        "בובי בראון": "Bobbi Brown", "סמאשבוקס": "Smashbox",
        "מייק אפ פור אבר": "MAKE UP FOR EVER", "מייקאפ פוראבר": "MAKE UP FOR EVER",
        "K18": "K18", "מילאני": "Milani", "מורד": "MURAD",
        "קלרינס": "Clarins", "דנסה מיריקס": "Danessa Myricks Beauty",
        "Glow Recipe": "Glow Recipe", "פי לואיז": "P.Louise", "דיור": "DIOR",
        "מייקאפ ביי מריו": "MAKEUP BY MARIO",
        "לנקום": "Lancôme", "אורבן דקיי": "Urban Decay", "קיילי קוסמטיקס": "Kylie Cosmetics",
        "Mugler": "MUGLER", "Kryolan": "Kryolan", "סברינה קרפנטר": "Sabrina Carpenter",
        "קליניק": "Clinique", "פיטר תומאס רות'": "Peter Thomas Roth", "ללין": "Laline",
        "וואן סייז": "ONE/SIZE", "ONE/SIZE": "ONE/SIZE",
        "רייר ביוטי": "Rare Beauty", "נייקס": "NYX", "קיי 18": "K18",
        "דה אורדינרי": "The Ordinary", "רוד": "rhode", "גלואו רסיפי": "Glow Recipe",
        "ג'יסו": "Gisou", "מוגלר": "MUGLER", "קריולן": "Kryolan", "מאק": "MAC",
        "אנסטסיה בוורלי הילס": "Anastasia Beverly Hills", "אורבן דיקיי": "Urban Decay",
        "איב סן לורן": "Yves Saint Laurent",
        "קולור וואו": "Color Wow", "קלר וואו": "Color Wow",
        "Ordinary": "The Ordinary", "The Ordinary": "The Ordinary",
        "גוט2בי": "got2b", "קרסטס": "Kérastase",
        "YSL": "Yves Saint Laurent", "ייב סן לורן": "Yves Saint Laurent",
        "Rhode": "rhode", "ביוטי קריאיישן": "Beauty Creations", "Gisou": "Gisou",
        "מייד ביי מיטשל": "Made By Mitchell", "איירספן": "Airspun",
        "אולפלקס": "OLAPLEX", "איט קוסמטיקס": "IT Cosmetics",
        "האוס לאבס": "Haus Labs", "האוס לאבס ביי ליידי גאגא": "Haus Labs",
    }

    def _brand_en(brand, name_en):
        """שם המותג באנגלית לתצוגה, לצד השם העברי.

        בהתחלה הוסתר כשהמותג כבר הופיע בשם המוצר, כדי לא לחזור עליו.
        נמרוד ביקש (27/08) שיוצג בכל המוצרים בלי יוצא מן הכלל — שורת
        המותג היא מקום קבוע, והלקוח מצפה למצוא בה את המותג תמיד ולא
        רק לפעמים. `name_en` של המוצר עדיין לא נוגע.
        """
        return BRAND_EN.get((brand or "").strip(), "")

    BRAND_EN.update({
        "סול דה ז'נרו": "Sol de Janeiro", "סול דה ז'ניירו": "Sol de Janeiro",
        "סול דה \u05d6\u05f3\u05e0\u05e8\u05d5": "Sol de Janeiro",
        "טאצ'ה": "TATCHA", "גוצ'י": "GUCCI", "קילס": "Kiehl's", "קיהל'ס": "Kiehl's",
        "דולצ'ה וגבאנה": "Dolce&Gabbana", "לנייג'": "LANEIGE",
        # 12/10/2026 — חסרו בכרטיסים (נמרוד)
        "אסתי לאודר": "ESTÉE LAUDER", "אסתי לאודר ": "ESTÉE LAUDER",
        "פאט מקגראת'": "PAT McGRATH LABS", "פט מקגראת'": "PAT McGRATH LABS",
        "טארט": "tarte", "ביוטיבלנדר": "beautyblender", "דייז": "dae", "אוליביה אומה": "Olivia Umma",
    })

    def _majority(members, key):
        vals = [m.get(key) for m in members if m.get(key)]
        return max(set(vals), key=vals.count) if vals else ""

    def _attrs_union(members):
        out = {}
        for m in members:
            for k, vals in (m.get("attrs") or {}).items():
                if isinstance(vals, list):
                    out.setdefault(k, set()).update(v for v in vals if isinstance(v, str) and v)
        return {k: sorted(v) for k, v in out.items() if v}

    def make_group(members, base_he):
        members = sorted(members, key=lambda m: (m["shade"] or m["name_he"]))
        return {"gid": "g" + str(len(groups)), "name_he": base_he,
                "name_en": _strip_trailing_shade(members[0]["name_en"]),
                "brand": members[0]["brand"], "type": members[0]["type"],
                "ben": _brand_en(members[0]["brand"], _strip_trailing_shade(members[0]["name_en"])),
                "cs": _majority(members, "cslug"), "st": _majority(members, "stype"),
                "set": any(m.get("isset") for m in members),
                "at": _attrs_union(members),
                "sts": sorted({m.get("stype") for m in members if m.get("stype")}),
                "variants": [variant(m) for m in members]}

    for k, members in buckets.items():
        if len(members) >= 2:
            groups.append(make_group(members, he_base(members)))
        else:
            singles.append(members[0])
    for p in singles:
        groups.append({"gid": "g" + str(len(groups)), "name_he": p["name_he"],
                       "name_en": p["name_en"], "brand": p["brand"], "type": p["type"],
                       "ben": _brand_en(p["brand"], p["name_en"]),
                       "cs": p.get("cslug") or "", "st": p.get("stype") or "",
                       "set": bool(p.get("isset")),
                       "at": _attrs_union([p]),
                       "sts": [p["stype"]] if p.get("stype") else [],
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

    og_image = (SITE_URL.rstrip("/") + "/og-image.jpg?v=noa1") if SITE_URL else "og-image.jpg?v=noa1"   # 14/10: תמונת השיתוף של נועה

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

    # 📱 --abs-img: כתובות תמונה מלאות אל האתר החי, במקום נתיבים יחסיים.
    # כך **קובץ אחד** נפתח בטלפון עם תמונות אמיתיות, בלי שרת ובלי להעביר
    # 10,745 קבצים. לתצוגה מקדימה בלבד — הפרסום האמיתי תמיד יחסי.
    if "--abs-img" in sys.argv:
        _n = 0
        for _g in groups:
            for _v in _g["variants"]:
                _v["imgs"] = [(SITE_URL.rstrip("/") + "/" + i) if not i.startswith("http") else i
                              for i in (_v.get("imgs") or [])]
                _n += len(_v["imgs"])
        print(f"📱 תמונות בכתובת מלאה: {_n} (תצוגה מקדימה לטלפון)")
        _assets = True   # נכסי האתר עצמם מטופלים אחרי בניית ה-HTML

    out = TEMPLATE.replace("/*__GROUPS__*/", _js(groups))
    out = out.replace("/*__CATTREE__*/", _js(cat_tree))
    out = out.replace("/*__POLICIES_AR__*/", _js(load_policies_ar()))
    out = out.replace("__COUNT__", str(len(groups)))
    out = out.replace("__OG_IMAGE__", og_image)
    out = out.replace("__SITE_URL__", SITE_URL.rstrip("/"))
    out = out.replace("__SUPABASE_CONFIG__", _js(supa_cfg))

    # רשימת היישובים נצרבת לדף (18 ק"ב דחוסים) כדי שבחירת עיר תהיה מיידית
    # בלי סיבוב רשת. הרחובות דווקא נשלפים לפי דרישה מהמסד — 62,261 רחובות
    # היו מוסיפים 271 ק"ב לכל כניסה לאתר, בשביל שדה שרק הקופה משתמשת בו.
    _cities_path = os.path.join(CAT, "cities.json")
    if os.path.exists(_cities_path):
        with open(_cities_path, encoding="utf-8") as _cf:
            _cities = _cf.read().strip()
        print(f"   יישובים נצרבו: {len(json.loads(_cities))}")
    else:
        _cities = "[]"
        print("   ⚠️  catalog/cities.json חסר — בורר היישובים יעבוד כשדה חופשי")
    # 🖼️ נכסי האתר (לוגו, אייקון, תמונות קטגוריה) — גם הם לכתובת מלאה
    # במצב תצוגה מקדימה. בלי זה הלוגו פשוט לא מופיע בקובץ הבודד.
    if "--abs-img" in sys.argv:
        _site = SITE_URL.rstrip("/")
        for _a in ('logo-bf.png', 'logo-bf-white.png', 'favicon-bf.png', 'cat/'):
            out = out.replace('src="' + _a, 'src="' + _site + '/' + _a)
            out = out.replace('href="' + _a, 'href="' + _site + '/' + _a)
        print("🖼️  נכסי האתר בכתובת מלאה (לוגו, אייקון, תמונות קטגוריה)")

    out = out.replace("/*__CITIES__*/", _cities)
    out = out.replace("/*__BRANDS_EN__*/", _js(BRAND_EN))
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(out)
    # 🏜️ 12/10/2026 — תמונת באנר הכניסה (נתיב יחסי) חייבת לשבת ליד הדף
    for _hn in ("hero-banner.jpg", "hero-banner-desktop.jpg"):
        _hb = os.path.join(CAT, _hn)
        if os.path.abspath(out_dir) != os.path.abspath(CAT) and os.path.exists(_hb):
            shutil.copy2(_hb, os.path.join(out_dir, _hn))
    # 🛒 דף ההזמנה המהירה — מאותם נתונים ומאותו קוד (ראה build_order_page)
    order_html = build_order_page(groups, supa_cfg, SITE_URL, cat_tree)
    # 📱 אותו טיפול בנכסי האתר גם לדף ההזמנה — אחרת האייקון והלוגו נשברים
    # בקובץ הבודד (נתפס בקובץ האתר 06/10, אותה סיבה בדיוק).
    if "--abs-img" in sys.argv:
        _site = SITE_URL.rstrip("/")
        for _a in ('logo-bf.png', 'logo-bf-white.png', 'favicon-bf.png', 'cat/'):
            order_html = order_html.replace('src="' + _a, 'src="' + _site + '/' + _a)
            order_html = order_html.replace('href="' + _a, 'href="' + _site + '/' + _a)
    with open(os.path.join(out_dir, "order.html"), "w", encoding="utf-8") as f:
        f.write(order_html)
    print(f"✅ order.html: {sum(len(g['variants']) for g in groups)} שורות ({len(order_html.encode()) // 1024} ק\"ב)")

    multi = [g for g in groups if len(g["variants"]) > 1]
    nprod = sum(len(g["variants"]) for g in groups)
    nimg = sum(len(v["imgs"]) for g in groups for v in g["variants"])
    print(f"✅ index.html: {len(groups)} כרטיסים ({nprod} מוצרים, {nimg} תמונות)")
    print(f"   קבוצות-גוונים (>1 גוון): {len(multi)}")
    for g in sorted(multi, key=lambda g: -len(g["variants"]))[:8]:
        print(f"     · {g['name_he'][:42]} ({g['brand']}) — {len(g['variants'])} גוונים")
    from collections import Counter as _C
    _why = _C(x[x.rfind("(")+1:-1] if x.endswith(")") else "לא בהזמנה 1" for x in excluded)
    print(f"   לא נבנו לדף: {len(excluded)} — " + " · ".join(f"{k} {n}" for k, n in _why.most_common()))
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
<meta property="og:url" content="__SITE_URL__/">
<meta property="og:site_name" content="Beauty Favorites">
<link rel="canonical" href="__SITE_URL__/">
<meta name="robots" content="index,follow">
<meta name="theme-color" content="#7c3aed">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Store","name":"Beauty Favorites","url":"__SITE_URL__/","image":"__OG_IMAGE__","logo":"__SITE_URL__/logo-bf.png","description":"הקולקציה הנבחרת — איפור, טיפוח, שיער ובושם מהמותגים האהובים","telephone":"+972-53-4555501","email":"beautyfavorites2026@gmail.com","priceRange":"₪₪","areaServed":"IL","currenciesAccepted":"ILS"}
</script>
<!-- חיבור Supabase (anon ציבורי). אם לא הוגדר — הקטלוג נופל חזרה למצב וואטסאפ-טקסט בלבד. -->
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.3/dist/umd/supabase.js" integrity="sha384-BWcjm9OdFth9TbhCxZPdm+gAOUMAzQy9nmTs12ioXdCcbVnJaPMn+fMUoQCLt60R" crossorigin="anonymous"></script>
<script>window.SUPA=__SUPABASE_CONFIG__;</script>
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="__OG_IMAGE__">
<meta name="theme-color" content="#3b2b20">
<link rel="icon" type="image/png" href="favicon-bf.png">
<link rel="apple-touch-icon" href="favicon-bf.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;700;900&family=Assistant:wght@300;400;500;600;700&family=Playfair+Display:wght@400&family=Montserrat:wght@600&family=Cormorant+Garamond:wght@500;600&family=Dancing+Script:wght@500;600;700&family=Suez+One&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#fbf8f4; --surface:#ffffff; --border:#ebe2d8; --border2:#dccfc1;
  /* 🏜️ 12/10/2026 — "חול ואבן" לפי הבאנר של המעצבת נועה. הקודם: שחור #171717 + ורוד-פטל #a85a6d (בגיבוי) */
  --accent:#2e2219; --accent-d:#1f1610; --accent-l:#5a4636; --accent-soft:#f5eee6;
  --text:#2e2219; --muted:#8c7b6d; --lux:#2e2219;
  --brand:#a88266; --brand-d:#6f523c; --brand-soft:#f3eae0;
  --radius:16px; --shadow:0 6px 24px rgba(0,0,0,.06); --shadow-h:0 14px 40px rgba(0,0,0,.12);
  --font:'Assistant','Heebo',-apple-system,BlinkMacSystemFont,sans-serif;   /* 12/10: הגופן של המעצבת */
  /* ✍️ 06/10/2026 — כתב היד הוסר מכל האתר (נמרוד). המשתנה נשאר
     כדי שלא ישבר שימוש ישן, אבל הוא מצביע על אותו גופן. */
  --script:var(--font);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
html,body{background:var(--bg);color:var(--text);font-family:var(--font);-webkit-font-smoothing:antialiased;overflow-x:hidden;overflow-x:clip}
body{padding-bottom:90px}
a{color:inherit}img{display:block}
::-webkit-scrollbar{height:0;width:0}

/* promo bar (free shipping / coupon / delivery) */
/* 📌 07/10: מקובע למעלה (נמרוד). z-index מעל שורת החיפוש הדביקה (60) ומתחת לסל ולחלונות. */
.promobar{position:sticky;top:0;z-index:65;display:flex;justify-content:center;align-items:center;gap:10px;flex-wrap:nowrap;overflow:hidden;
  background:linear-gradient(90deg,#3b2b20,var(--brand-d) 55%,#8f6d55);color:#f6ebe0;
  font-size:12.5px;font-weight:600;letter-spacing:.2px;padding:7px 12px;text-align:center}
.promobar span{white-space:nowrap}
.promobar .pdot{opacity:.55;font-weight:400}
@media(max-width:640px){
  .promobar{font-size:12px;padding:6px 10px}
  .promobar .pdot{display:none}
  .promobar span:not(.pdot){display:none}
  .promobar span.cur{display:inline;animation:promoIn .45s ease}
}
@keyframes promoIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}

.brandbar{position:relative;display:flex;justify-content:center;align-items:center;padding:14px 16px 10px;background:var(--bg)}
.brandbar img{height:84px;width:auto;display:block;transition:transform .25s ease}   /* 06/10: הוגדל מ-58 (נמרוד) */
.brandbar img:hover{transform:translateY(-1px)}
/* 🏜️ 12/10/2026 — באנר הכניסה של המעצבת. המיקומים באחוזים לפי הקובץ שלה (דף 810×1080),
   כך שבטלפון הוא נראה בדיוק כמו העיצוב. במחשב: התמונה בצד, הכיתוב על משטח חול. */
.brandbar{display:none}
.dhero{position:relative;overflow:hidden;width:100%;aspect-ratio:3/4;max-height:92vh;text-align:center;
  background:#5b4533 url(hero-banner.jpg) center top/cover no-repeat}   /* 14/10: באנר נועה 1080×1440 */
.dhero,.dhero *{color:#fff}
.dhero .hlogo{position:absolute;top:4.5%;left:0;right:0;line-height:1;cursor:pointer}
.dhero .hlogo img{display:block;margin:0 auto;width:clamp(108px,30vw,200px);height:auto}   /* 14/10: הלוגו של נועה */
.dhero h1{position:absolute;top:19.4%;left:4%;right:4%;margin:0;font:600 clamp(23px,6.5vw,52px)/1.1 'Assistant',sans-serif;text-wrap:balance}
.dhero p{position:absolute;top:31.6%;left:5%;right:5%;margin:0;font:400 clamp(12px,3.25vw,26px)/1.35 'Assistant',sans-serif;text-wrap:balance}
.dhero .hcta{position:absolute;top:80.7%;left:50%;transform:translateX(-50%);width:48.6%;height:10.9%;
  background:rgba(197,158,127,.86);border:0;border-radius:clamp(12px,3.4vw,24px);
  font:400 clamp(15px,4.2vw,26px)/1 'Assistant',sans-serif;cursor:pointer;
  display:flex;gap:.6em;align-items:center;justify-content:center}
.dhero .hcta .harr{font-size:1.25em}
.dhero .langbtn{top:10px;transform:none;inset-inline-start:auto;left:10px;padding:6px 14px;font-size:13px;
  background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.55);border-radius:20px;
  box-shadow:none;backdrop-filter:blur(6px);color:#fff}
.dhero .langbtn:hover{transform:scale(1.04);background:rgba(255,255,255,.26)}
@media(min-width:900px){
  /* 14/10: הבאנר הרחב של נועה (2400×900) — המוצרים משמאל, הכיתוב על הקיר הנקי מימין */
  .dhero{aspect-ratio:8/3;height:auto;max-height:78vh;min-height:420px;
    background:#5b4533 url(hero-banner-desktop.jpg) left center/cover no-repeat}
  .dhero .hlogo,.dhero h1,.dhero p{left:auto;right:5%;width:42%}
  .dhero .hlogo{top:12%}
  .dhero .hlogo img{width:clamp(170px,14vw,230px)}
  .dhero h1{top:38%;font-size:clamp(34px,3.2vw,50px)}
  .dhero p{top:58%;font-size:clamp(16px,1.35vw,21px)}
  .dhero .hcta{left:auto;right:calc(5% + 21% - 160px);transform:none;width:320px;height:62px;font-size:22px;top:auto;bottom:11%}
}

.langbtn{position:absolute;inset-inline-start:16px;top:50%;transform:translateY(-50%);
  background:var(--surface);border:1px solid var(--border2);color:var(--accent-d);
  font-family:var(--font);font-size:13px;font-weight:500;padding:7px 14px;border-radius:30px;
  cursor:pointer;box-shadow:var(--shadow);transition:background .2s,transform .15s}
.langbtn:hover{background:var(--accent-soft);transform:translateY(-50%) scale(1.04)}
@media(max-width:640px){.brandbar img{height:66px}.brandbar{padding:11px 16px 7px}.langbtn{font-size:12px;padding:6px 11px;inset-inline-start:12px}}
.herobanner{position:relative;width:100%;overflow:hidden;border-bottom:1px solid var(--border);
  background:linear-gradient(rgba(255,255,255,.28),rgba(255,255,255,.40) 55%,rgba(255,255,255,.52)),url('hero.jpg') center/cover no-repeat}
.herobanner::before,.herobanner::after{content:none}
@keyframes blobA{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(34px,22px) scale(1.1)}}
@keyframes blobB{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-38px,-20px) scale(1.07)}}
/* hero product collage (floating product cards, desktop only; images injected by JS from in-stock prestige brands) */
.hero-deco{position:absolute;top:0;bottom:0;width:190px;pointer-events:none;display:none}
.hero-deco.l{left:14px}.hero-deco.r{right:14px}
.hero-deco .hd{position:absolute;width:92px;height:92px;object-fit:contain;background:#fff;border:1px solid var(--border2);
  border-radius:16px;padding:8px;box-shadow:0 10px 28px rgba(0,0,0,.14);animation:hdFloat 7s ease-in-out infinite}
.hero-deco .hd0{top:12%;inset-inline-start:6px;transform:rotate(-6deg)}
.hero-deco .hd1{top:44%;inset-inline-start:78px;width:78px;height:78px;animation-delay:1.6s;transform:rotate(5deg)}
.hero-deco .hd2{top:70%;inset-inline-start:14px;width:70px;height:70px;animation-delay:3.1s;transform:rotate(-3deg)}
@keyframes hdFloat{0%,100%{margin-top:0}50%{margin-top:-12px}}
@media(prefers-reduced-motion:reduce){.herobanner::before,.herobanner::after,.hero-deco .hd{animation:none!important}}
.hero-inner{max-width:860px;margin:0 auto;padding:58px 20px 54px;text-align:center;position:relative}
.hero-kicker{font-family:var(--font);font-size:13px;font-weight:500;letter-spacing:7px;color:var(--accent-d);text-transform:uppercase}
.hero-title{font-family:'Dancing Script','Cormorant Garamond',cursive;font-style:normal;font-weight:700;
  font-size:clamp(54px,9vw,98px);line-height:1.12;margin:6px 0 12px;letter-spacing:.5px;
  background:linear-gradient(100deg,#333333,#171717 55%,#3a3a3a);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero-line{width:120px;height:1.4px;background:var(--lux);margin:0 auto 16px;position:relative}
.hero-line::before,.hero-line::after{content:'';position:absolute;top:-1.3px;width:4px;height:4px;border-radius:50%;background:var(--lux)}
.hero-line::before{right:-9px}.hero-line::after{left:-9px}
.hero-sub{font-family:'Suez One',var(--font);font-size:clamp(15px,2.2vw,20px);font-weight:400;color:var(--text);letter-spacing:.2px}
@media(max-width:640px){.hero-inner{padding:44px 16px 40px}.hero-kicker{letter-spacing:5px;font-size:11.5px}}
.hero{text-align:center;padding:30px 18px 16px;background:radial-gradient(120% 90% at 50% -10%, var(--brand-soft) 0%, var(--bg) 60%);border-bottom:1px solid var(--border)}
.hero .mark{font-family:'Cormorant Garamond',serif;font-size:13px;letter-spacing:5px;text-transform:uppercase;color:var(--accent);font-weight:600}
.hero h1{font-family:'Dancing Script','Cormorant Garamond',cursive;font-size:52px;font-weight:700;line-height:1.12;letter-spacing:.5px;margin:2px 0 6px;background:linear-gradient(90deg,var(--accent-d),var(--accent-l));-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{color:var(--muted);font-size:14px;font-weight:300}
.hero .count{display:inline-block;margin-top:9px;font-size:12px;color:var(--accent);background:var(--accent-soft);border:1px solid var(--border2);padding:3px 14px;border-radius:30px}
.herocount{text-align:center;margin:16px 0 2px;min-height:26px}
.herocount span{display:inline-block;font-size:13px;font-weight:600;color:var(--accent-d);background:var(--accent-soft);border:1px solid var(--border2);padding:5px 18px;border-radius:30px}
.herocount span:empty{display:none}

/* category image tiles */
.cattiles{display:flex;gap:12px;justify-content:flex-start;overflow-x:auto;scrollbar-width:none;
  max-width:1400px;margin:14px auto 2px;padding:4px 18px}
.cattiles::-webkit-scrollbar{display:none}
/* 🗂️ ניווט העץ (06/10/2026) — אריח לכל קבוצה בצבע משלה, ומתחתיו שורת
   תתי-הקטגוריות של הקבוצה שנבחרה. הצבע נושא את הזהות, האייקון הוא קו
   בגוון הכהה של אותו צבע. הלוגו והפונט לא נגעו. */
.cattiles.tree{display:grid;grid-template-columns:1fr 1fr;gap:10px;background:none;
  overflow:visible;padding:0 14px;margin:14px auto 0;max-width:1400px;border:0}
@media(min-width:760px){.cattiles.tree{grid-template-columns:repeat(5,1fr);gap:14px;padding:0 18px}}
/* ✏️ 12/10/2026 — לפי הדוגמה של המעצבת: התווית מימין, אייקון מאויר גדול משמאל */
.cattiles.tree .cattile{display:flex;flex-direction:row-reverse;align-items:center;
  justify-content:space-between;gap:8px;min-height:86px;padding:12px 14px;width:auto;
  border-radius:12px;border:1px solid rgba(111,82,60,.10);box-shadow:0 1px 3px rgba(60,40,25,.05)}
.cattiles.tree .cattile>span:last-child{font-size:15.5px;font-weight:500;line-height:1.25;text-align:start;color:var(--text)}
.cattiles.tree .cattile:active{filter:brightness(.96)}
.cattiles.tree .cattile.active{box-shadow:inset 0 0 0 2px var(--brand-d)}
.cattile .ci.cticon{display:flex;align-items:center;justify-content:center;border:0;flex:none;box-shadow:none!important;padding:0;
  width:auto;height:auto;border-radius:0;background:none!important}
.cattile .ci.cticon svg{width:44px;height:44px;fill:none;stroke-width:1.7;
  stroke-linecap:round;stroke-linejoin:round}
@media(min-width:760px){.cattile .ci.cticon svg{width:52px;height:52px}}
/* כותרת קטע מעל הרשת — כמו בהדמיה */
.catsec{max-width:1400px;margin:22px auto 0;padding:0 18px;font-size:24px;font-weight:600;
  letter-spacing:.01em}
.catsec:empty{display:none}
.subrow{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;max-width:1160px;
  margin:4px auto 0;padding:6px 18px 2px;cursor:grab}
.subrow::-webkit-scrollbar{display:none}
.subrow:empty{display:none}
/* 🏷️ פס הכותרת של הקבוצה — אותו צבע של האריח שנלחץ, עם האייקון והשם
   בערבית. בלעדיו הלקוחה לוחצת על אריח צבעוני ונוחתת ברשימה לבנה
   שאינה אומרת לה איפה היא. */
.cathead{max-width:1400px;margin:10px auto 0;padding:0 18px}
.cathead:empty{display:none}
.cathead .inner{display:flex;align-items:center;gap:13px;border-radius:14px;padding:16px 18px}
.cathead svg{width:38px;height:38px;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;flex:none}
.cathead h2{font-size:21px;font-weight:600;letter-spacing:.01em;line-height:1.2}
.cathead .ar{font-size:12.5px;opacity:.72;margin-top:3px}
.cathead .found{margin-top:9px;font-size:12.5px;color:var(--muted)}
.cathead .found b{color:var(--text);font-weight:600}
.subchip{flex:0 0 auto;border:1px solid var(--border2);border-radius:999px;background:#fff;
  padding:6px 14px;font-size:13.5px;cursor:pointer;white-space:nowrap;font-family:var(--font);color:var(--text)}
.subchip.active{background:var(--accent);border-color:var(--accent);color:#fff}
@media(min-width:900px){.subrow{justify-content:center}}
@media(min-width:900px){.cattiles{justify-content:center}}
.cattile{flex:0 0 auto;display:flex;flex-direction:column;align-items:center;gap:7px;cursor:pointer;
  background:none;border:none;font-family:var(--font);padding:2px}
.cattile .ci{width:76px;height:76px;border-radius:50%;background:var(--accent-soft);border:1px solid var(--border2);
  display:flex;align-items:center;justify-content:center;padding:0;overflow:hidden;transition:.2s;box-shadow:var(--shadow)}
.cattile img{width:100%;height:100%;object-fit:cover;mix-blend-mode:normal}
.cattile .ph{font-size:28px;color:var(--accent-l);opacity:.9}
.cattile .ci-all{background:linear-gradient(160deg,var(--accent-soft),#fff);border-color:var(--border2)}
.cattile .ci-sale{background:#171717;color:#fff;font-family:'Heebo';font-weight:900;font-size:15px;letter-spacing:.04em;display:flex;align-items:center;justify-content:center}
.cattile span{font-size:12.5px;font-weight:600;color:var(--text)}
.cattile:hover .ci{border-color:var(--accent-l);transform:translateY(-3px)}
.cattile.active .ci{border-color:var(--accent);box-shadow:0 6px 18px rgba(0,0,0,.24)}
.cattile.active span{color:var(--accent-d)}
@media(max-width:640px){.cattile .ci{width:66px;height:66px}.cattile span{font-size:11.5px}}

/* brand picker button + modal */
.brandpick{display:none}   /* 06/10/2026 — הכפתור עבר לשורת הסינון */
@media(max-width:640px){.brandpick{padding:16px 16px 14px}}   /* ריווח לכפתור "כל המותגים" במובייל — צפוף מדי בלעדיו */
.brandpickbtn{display:inline-flex;align-items:center;gap:7px;font-family:var(--font);font-size:12px;font-weight:500;
  cursor:pointer;padding:6px 14px;border-radius:20px;border:1px solid var(--border2);background:var(--surface);
  color:var(--muted);box-shadow:none;transition:.15s}
.brandpickbtn:hover{color:var(--brand-d);border-color:var(--brand)}
.brandpickbtn .bpi{display:none}
.brandpickbtn .bpchev{font-size:9px;opacity:.6;margin-inline-start:2px;font-weight:400}
/* נבחר מותג → הצ'יפ נצבע בגוון המותג, כמו כל סינון פעיל אחר */
.brandpickbtn.on{background:var(--brand-soft);color:var(--brand-d);border-color:var(--brand)}
.brandpickbtn.on .bpchev{opacity:.85}
.brandpickbtn .clr{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;
  background:rgba(255,255,255,.28);font-size:12px;line-height:1}
.brandsheet{max-width:720px}
/* 🎛️ חלון הסינון — מקטעים בסדר של טל, צ'יפים בצבע הקבוצה (כמו תתי-הקטגוריות) */
.filtersheet{max-width:560px}
.fsec{padding:12px 0;border-bottom:1px solid var(--border)}
.fsec:last-of-type{border-bottom:none}
.fsec h4{font-family:var(--font);font-size:14px;font-weight:600;margin:0 0 9px;color:var(--text)}
.fopts{display:flex;flex-wrap:wrap;gap:8px}
.fopt{font-family:var(--font);font-size:13px;font-weight:500;cursor:pointer;padding:7px 14px;border-radius:20px;border:none;transition:.15s}
.fclear{display:block;margin:12px auto 0;background:none;border:none;font-family:var(--font);font-size:13px;color:var(--brand-d);cursor:pointer;text-decoration:underline}
.bm{padding:6px 20px 24px}
.bm h3{font-family:var(--font);font-size:24px;font-weight:600;letter-spacing:0;text-align:center;margin:6px 0 12px}
.bm .bsearch{position:relative;margin-bottom:14px}
.bm .bsearch input{width:100%;font-size:16px;font-family:var(--font);padding:11px 40px;border:1px solid var(--border2);
  border-radius:30px;background:var(--surface);color:var(--text);outline:none}
.bm .bsearch input:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}
.bm .bsearch .ico{position:absolute;right:15px;top:50%;transform:translateY(-50%);color:var(--accent-l);font-size:17px}
.bgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px}
.bcard{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;cursor:pointer;
  background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px 10px;min-height:106px;transition:.15s}
.bcard:hover{border-color:var(--accent-l);box-shadow:var(--shadow);transform:translateY(-2px)}
.bcard.on{border-color:var(--brand);background:var(--brand-soft);box-shadow:0 4px 14px rgba(168,90,109,.22)}
.bdone{position:sticky;bottom:0;width:100%;margin-top:14px;font-family:var(--font);font-size:15px;font-weight:700;color:#fff;
  border:none;border-radius:14px;padding:13px;cursor:pointer;background:linear-gradient(90deg,var(--brand-d),var(--brand));
  box-shadow:0 8px 22px rgba(168,90,109,.3)}
.bcard .blogo{height:48px;max-width:92%;object-fit:contain;mix-blend-mode:multiply}
.bcard .bwm{font-family:'Cormorant Garamond',serif;font-size:17px;font-weight:600;color:var(--accent-d);text-align:center;line-height:1.15}
/* אריח בלי קובץ לוגו מקבל סמליל טיפוגרפי בגובה זהה, כדי שהרשת תישאר
   מיושרת ולא תיראה כאילו חסר בה משהו */
.bcard .bwm{min-height:48px;display:flex;align-items:center;justify-content:center}
.bcard .bname{font-size:11px;font-weight:600;color:var(--muted);text-align:center;line-height:1.2}
.bcard .bcount{font-size:10px;color:var(--accent-l);font-weight:700}
.bcard.allb{background:linear-gradient(160deg,var(--accent-soft),#fff)}
.bcard.allb .bwm{font-style:italic}
.bm .bempty{text-align:center;color:var(--muted);padding:30px 10px;font-size:14px}
@media(max-width:640px){.bgrid{grid-template-columns:repeat(3,1fr);gap:8px}.bcard{min-height:90px;padding:11px 7px}.bcard .blogo{height:38px}}

/* low-stock urgency */
.lowstock{font-size:11px;font-weight:700;color:#171717;background:var(--accent-soft);border:1px solid var(--border2);border-radius:8px;padding:1px 8px;align-self:flex-start}
.pd .lowstock{font-size:12.5px;padding:3px 10px;display:inline-block;margin:2px 0 4px}

/* trust badges row */
.trustrow{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;max-width:1000px;margin:34px auto 0;padding:0 16px}
.trustrow span{font-size:12.5px;font-weight:600;color:var(--accent-d);background:var(--surface);
  border:1px solid var(--border2);border-radius:30px;padding:8px 16px;box-shadow:var(--shadow)}

/* floating WhatsApp launcher + chat popup */
.wafloat{position:fixed;right:16px;bottom:84px;z-index:70;width:54px;height:54px;border-radius:50%;border:none;cursor:pointer;
  background:#25d366;color:#fff;display:flex;align-items:center;justify-content:center;
  box-shadow:0 10px 26px rgba(37,211,102,.42);transition:.2s}
.wafloat:hover{transform:scale(1.08)}
.wafloat svg{width:30px;height:30px;fill:#fff}
.wachat{position:fixed;right:16px;bottom:150px;z-index:85;width:300px;max-width:calc(100vw - 32px);
  background:var(--surface);border:1px solid var(--border2);border-radius:18px;box-shadow:0 18px 50px rgba(0,0,0,.22);
  overflow:hidden;display:none;animation:waUp .22s cubic-bezier(.2,.8,.2,1)}
.wachat.open{display:block}
@keyframes waUp{from{opacity:0;transform:translateY(12px) scale(.96)}to{opacity:1;transform:translateY(0) scale(1)}}
.wachat-head{background:#075e54;color:#fff;padding:12px 15px;display:flex;align-items:center;gap:9px}
.wachat-head svg{width:22px;height:22px;fill:#fff;flex:0 0 auto}
.wachat-head .wt{font-size:13.5px;font-weight:600;line-height:1.3}
.wachat-head .wx{margin-inline-start:auto;background:none;border:none;color:#fff;font-size:19px;cursor:pointer;opacity:.85;line-height:1;padding:0}
.wachat-body{padding:13px 14px}
.wachat-body .wgreet{font-size:12.5px;color:var(--muted);margin-bottom:9px;line-height:1.5}
.wachat-body textarea{width:100%;font-family:var(--font);font-size:14px;padding:10px 12px;border:1px solid var(--border2);
  border-radius:12px;outline:none;background:var(--surface);color:var(--text);resize:vertical;min-height:62px}
.wachat-body textarea:focus{border-color:#25d366;box-shadow:0 0 0 3px rgba(37,211,102,.16)}
.wachat-send{width:100%;margin-top:10px;font-family:var(--font);font-size:15px;font-weight:700;color:#fff;border:none;
  border-radius:12px;padding:12px;cursor:pointer;background:#25d366;display:flex;align-items:center;justify-content:center;gap:8px}
.wachat-send svg{width:18px;height:18px;fill:#fff}
.wachat-send:hover{background:#1fbe5a}

/* category nav (primary) */
.catnav{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;padding:14px 16px 6px;max-width:760px;margin:0 auto}
.cat{font-family:var(--font);font-size:14px;font-weight:600;cursor:pointer;padding:9px 20px;border-radius:30px;border:1px solid var(--border2);background:var(--surface);color:var(--text);transition:.18s}
.cat:hover{border-color:var(--accent-l);color:var(--accent-d)}
.cat.active{background:linear-gradient(90deg,var(--accent-d),var(--accent));color:#fff;border-color:transparent;box-shadow:0 4px 14px rgba(0,0,0,.28)}

/* search + autocomplete */
.search-wrap{position:sticky;top:var(--pbh,0px);z-index:60;background:rgba(255,255,255,.92);backdrop-filter:blur(12px);padding:10px 16px 8px;border-bottom:1px solid var(--border)}
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
.ac-item img{width:30px;height:30px;object-fit:contain;border-radius:6px;background:var(--brand-soft)}
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
.chip.favbtn.active{background:var(--accent-soft);color:#171717;border-color:var(--border2)}
.spacer{flex:1 1 auto;min-width:8px}
select.sort{font-family:var(--font);font-size:12px;color:var(--text);background:var(--surface);border:1px solid var(--border2);border-radius:20px;padding:6px 12px;cursor:pointer;outline:none}

/* grid */
.rescount{max-width:1400px;margin:8px auto 0;padding:0 20px;font-size:12.5px;color:var(--muted);font-weight:500;text-align:right}
/* 🎛️ 12/10/2026 — מגירת סינון אחת. הסרגל הישן, הבועות והפס הכחול — מוסתרים (הלוגיקה חיה) */
.toolbar,.subrow,#actFil{display:none!important}
.fbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;max-width:1400px;margin:12px auto 0;padding:0 18px}
.fbtn{display:inline-flex;align-items:center;gap:7px;font-family:var(--font);font-size:14px;font-weight:600;color:var(--text);
  background:var(--surface);border:1px solid var(--border2);border-radius:30px;padding:9px 16px;cursor:pointer;box-shadow:var(--shadow)}
.fbtn svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round}
.fbtn .fbn{display:none;min-width:20px;height:20px;border-radius:10px;background:var(--brand-d);color:#fff;font-size:12px;line-height:20px;text-align:center;padding:0 6px}
.fbtn.on{border-color:var(--brand-d);color:var(--brand-d)}
.fbtn.on .fbn{display:inline-block}
.fbar .fbcount{font-size:13px;color:var(--muted);font-weight:500;white-space:nowrap}
.fbar #sort{margin:0}
.fbchips{display:flex;gap:6px;flex-wrap:wrap;flex:1 1 100%}
.fbchips:empty{display:none}
.fbchip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:500;color:var(--brand-d);
  background:var(--brand-soft);border:1px solid transparent;border-radius:20px;padding:5px 10px}
.fbchip button{all:unset;cursor:pointer;font-size:13px;line-height:1;opacity:.7}
.fbchip button:hover{opacity:1}
.fback{position:fixed;inset:0;z-index:205;background:rgba(40,26,16,.42);display:none}
.fback.open{display:block}
.fdrawer{position:fixed;top:0;bottom:0;inset-inline-start:0;width:min(86vw,360px);z-index:210;background:var(--surface);
  display:flex;flex-direction:column;transform:translateX(100%);transition:transform .28s cubic-bezier(.2,.8,.2,1);
  box-shadow:-12px 0 40px rgba(0,0,0,.18)}
[dir=ltr] .fdrawer{transform:translateX(-100%)}
.fdrawer.open{transform:none}
.fdhead{display:flex;align-items:center;justify-content:space-between;padding:16px 18px 10px;border-bottom:1px solid var(--border)}
.fdhead h3{font-family:var(--font);font-size:19px;font-weight:600;margin:0}
.fdx{all:unset;cursor:pointer;font-size:18px;color:var(--muted);padding:4px 6px}
.fdbody{flex:1;overflow-y:auto;padding:4px 18px 12px;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;touch-action:pan-y}
.fdrawer{overscroll-behavior:contain}
.fback{touch-action:none}
body.pglock{position:fixed;left:0;right:0;width:100%;overflow:hidden}
.fdq{position:relative;padding:10px 18px 8px;border-bottom:1px solid var(--border)}
.fdq input{width:100%;box-sizing:border-box;font-family:var(--font);font-size:16px;padding:10px 38px 10px 12px;
  border:1px solid var(--border2);border-radius:24px;background:var(--bg);color:var(--text)}
.fdq .ico{position:absolute;top:50%;transform:translateY(-50%);inset-inline-start:32px;color:var(--muted);font-size:16px;pointer-events:none}
@media(min-width:900px){.fdq{padding:8px 16px}}
.fdsec{border-bottom:1px solid var(--border)}
.fdsec summary{list-style:none;display:flex;align-items:center;justify-content:space-between;cursor:pointer;
  padding:13px 0;font-size:15px;font-weight:600;color:var(--text)}
.fdsec summary::-webkit-details-marker{display:none}
.fdsec summary .chev{font-size:11px;color:var(--muted);transition:transform .2s}
.fdsec[open] summary .chev{transform:rotate(180deg)}
.fdsec summary .sel{font-size:12px;font-weight:500;color:var(--brand-d);margin-inline-start:8px;flex:1;text-align:start;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fdlist{padding:0 0 10px}
/* הבועות בשורה התחתונה הקבועה: שורה אחת, גלילה הצידה, לא זזות עם הרשימה */
.fdfoot{flex-wrap:wrap}
.fdchips{flex:1 1 100%;display:flex;flex-wrap:nowrap;gap:6px;overflow-x:auto;scrollbar-width:none;padding-bottom:2px}
.fdchips::-webkit-scrollbar{display:none}
.fdchips:empty{display:none}
.fdchips .fbchip{flex:none;white-space:nowrap}
.fdopt{display:flex;align-items:center;gap:10px;padding:7px 2px;cursor:pointer;font-size:14px;color:var(--text)}
.fdopt .box{width:18px;height:18px;border:1.5px solid var(--border2);border-radius:5px;flex:none;display:flex;align-items:center;justify-content:center;
  font-size:12px;color:#fff;background:var(--surface)}
.fdopt.radio .box{border-radius:50%}
.fdopt.on .box{background:var(--brand-d);border-color:var(--brand-d)}
.fdopt .n{margin-inline-start:auto;font-size:12px;color:var(--muted)}
.fdopt.on{font-weight:600}
.fdbq{width:100%;box-sizing:border-box;font-family:var(--font);font-size:14px;padding:8px 12px;border:1px solid var(--border2);border-radius:10px;margin:2px 0 8px;background:var(--bg)}
.fdmore{all:unset;cursor:pointer;font-size:13px;color:var(--brand-d);text-decoration:underline;padding:4px 2px 8px;display:block}
.fdfoot{display:flex;gap:10px;padding:12px 18px calc(12px + env(safe-area-inset-bottom,0px));border-top:1px solid var(--border);background:var(--surface)}
.fdclear{flex:0 0 auto;font-family:var(--font);font-size:14px;font-weight:600;color:var(--text);background:var(--surface);
  border:1px solid var(--border2);border-radius:30px;padding:12px 16px;cursor:pointer}
.fdshow{flex:1;font-family:var(--font);font-size:15px;font-weight:700;color:#fff;background:var(--brand-d);border:none;border-radius:30px;padding:12px 16px;cursor:pointer}
@media(min-width:900px){
  /* 💻 12/10 (נמרוד): גם במחשב המגירה נשלפת מהצד כמו בטלפון — המוצרים נשארים ברוחב מלא.
     (הגרסה עם עמודה קבועה — בגיבוי build_catalog-*-לפני-סבב6.py) */
  .fdrawer{width:380px}
  .fbtn{font-size:15px;padding:10px 20px}
}
/* 🔵 סרגל הסינונים הפעילים — מופיע רק כשיש סינון, כדי שתמיד יהיה ברור מה מצומצם ואיך לחזור להכל */
.actfil{display:none;max-width:1160px;margin:10px auto 0;padding:10px 14px;gap:8px;align-items:center;flex-wrap:wrap;
  background:var(--accent-soft);border:1px solid var(--accent-l);border-radius:14px}
.actfil.on{display:flex}
.actfil .afl{font-size:12.5px;font-weight:700;color:var(--accent-d);margin-inline-end:2px}
.aftag{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;color:var(--text);
  background:var(--surface);border:1px solid var(--accent-l);border-radius:20px;padding:5px 10px}
.aftag button{all:unset;cursor:pointer;font-size:14px;line-height:1;color:var(--muted);padding:0 1px}
.aftag button:hover{color:var(--accent-d)}
.afclear{margin-inline-start:auto;cursor:pointer;font-family:var(--font);font-size:13px;font-weight:700;
  color:#fff;background:var(--brand);border:none;border-radius:20px;padding:8px 18px;transition:.15s;white-space:nowrap}
.afclear:hover{filter:brightness(.93)}
@media(max-width:600px){.afclear{width:100%;margin-inline-start:0;text-align:center}}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;max-width:1400px;margin:8px auto 40px;padding:0 18px}
/* 💻 12/10 (נמרוד): פחות שטח מת במחשב — 4 עמודות ממסך 1100, 5 ממסך 1500 */
@media(min-width:1100px){.grid{grid-template-columns:repeat(4,1fr)}}
@media(min-width:1500px){.grid{grid-template-columns:repeat(5,1fr)}}
.card{background:var(--surface);border:1px solid #efe7e9;border-radius:var(--radius);overflow:hidden;display:flex;flex-direction:column;cursor:pointer;transition:.22s;position:relative}
.card:hover{transform:translateY(-4px);box-shadow:var(--shadow-h);border-color:var(--border2)}
.card .imgbox{position:relative;aspect-ratio:1/1;background:linear-gradient(160deg,#fff,var(--brand-soft));display:flex;align-items:center;justify-content:center;padding:14px;overflow:hidden}
/* 🖼️ 12/10 (נמרוד: "לא יושבים טוב / מאורכים"): בספארי max-height:100% בתוך aspect-ratio לא הגביל
   את התמונה והיא מתחה את הכרטיס. מיקום אבסולוטי = הריבוע קובע, התמונה נכנסת בו במרכז. */
.card .imgbox img{position:absolute;inset:14px;width:calc(100% - 28px);height:calc(100% - 28px);max-width:none;max-height:none;object-fit:contain;mix-blend-mode:multiply}
.ph{font-family:'Cormorant Garamond',serif;font-size:46px;color:var(--accent-l);opacity:.5}
.fav{position:absolute;top:9px;left:9px;z-index:3;width:34px;height:34px;border-radius:50%;border:1px solid rgba(0,0,0,.12);background:#fff;backdrop-filter:blur(4px);cursor:pointer;font-size:16px;line-height:1;display:flex;align-items:center;justify-content:center;color:#8a8a8a;transition:.15s;box-shadow:0 2px 10px rgba(0,0,0,.14)}
.fav:hover{transform:scale(1.12)}
/* ❤️ 06/10/2026 — העיגול **מתמלא** ורוד בבחירה (נמרוד). קודם רק הלב
   השחור התמלא, ובכרטיס לבן קטן זה כמעט לא נראה. */
.fav.on{background:var(--brand);color:#fff;border-color:var(--brand);
  box-shadow:0 2px 12px rgba(168,90,109,.45)}
.bdgs{position:absolute;top:9px;right:9px;z-index:3;display:flex;flex-direction:column;gap:4px;align-items:flex-end}
.bdg{font-size:10px;font-weight:700;color:#fff;padding:2px 8px;border-radius:20px;letter-spacing:.3px;box-shadow:0 2px 6px rgba(0,0,0,.12)}
.bdg.sale{background:var(--brand-d)}.bdg.new{background:var(--brand)}
.bdg.bestseller{background:#b4714f}
.bdg.soldout{background:#9a9aa2}.bdg.limited{background:#8a6a4b}.bdg.vegan{background:#4e7a5e}
.card .body{padding:11px 13px 13px;display:flex;flex-direction:column;gap:5px;flex:1}
.card .brand{font-size:10.5px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--brand-d)}
/* שם המותג באנגלית לצד העברי — כך הלקוח מזהה את המותג גם כשהשם
   האנגלי של המוצר עצמו אינו פותח בו. השם האנגלי של המוצר לא נגע. */
.brand-en{font-weight:500;opacity:.72;letter-spacing:.3px}
.brand-en::before{content:'·';margin:0 5px;opacity:.6}
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
.price{font-size:17px;font-weight:700;color:var(--brand-d)}
.price .was{font-size:12px;font-weight:500;color:var(--muted);text-decoration:line-through;margin-inline-start:5px}
.price.sale{color:var(--accent)}
.add{width:34px;height:34px;border-radius:11px;border:none;cursor:pointer;font-size:20px;line-height:1;color:#fff;background:linear-gradient(135deg,var(--brand),var(--brand-d));box-shadow:0 4px 12px rgba(168,90,109,.26);transition:.15s;touch-action:manipulation}
.add:hover{transform:translateY(-1px) scale(1.05)}
.cardqty{display:flex;align-items:center;border:1px solid var(--accent-l);border-radius:11px;overflow:hidden;background:var(--surface);box-shadow:0 2px 8px rgba(0,0,0,.1)}
.cardqty button{width:30px;height:34px;border:none;background:var(--accent-soft);color:var(--accent-d);font-size:18px;line-height:1;cursor:pointer;touch-action:manipulation;transition:.12s}
.cardqty button:hover{background:var(--accent);color:#fff}
.cardqty span{min-width:28px;text-align:center;font-size:14px;font-weight:700;color:var(--text)}
.cardqin{width:42px;height:34px;border:none;border-inline:1px solid var(--accent-l);text-align:center;font-size:14px;font-weight:700;color:var(--text);background:var(--surface);font-family:var(--font);-moz-appearance:textfield}
.cardqin::-webkit-outer-spin-button,.cardqin::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
.empty{text-align:center;color:var(--muted);padding:70px 20px;font-size:15px}

/* cart bar + back to top */
.cartbar{position:fixed;left:0;right:0;bottom:0;z-index:80;background:rgba(255,255,255,.96);backdrop-filter:blur(14px);border-top:1px solid var(--border2);padding:11px 18px;display:flex;align-items:center;gap:14px;justify-content:center;box-shadow:0 -8px 30px rgba(0,0,0,.1);transform:translateY(120%);transition:.32s cubic-bezier(.2,.8,.2,1)}
.cartbar.show{transform:translateY(0)}
.cartbar .sum{font-weight:500;font-size:14px}.cartbar .sum b{color:var(--accent-d)}
.cartbar button{font-family:var(--font);font-size:14px;font-weight:600;color:#fff;cursor:pointer;border:none;border-radius:30px;padding:11px 26px;background:linear-gradient(90deg,var(--brand-d),var(--brand));box-shadow:0 6px 18px rgba(168,90,109,.3)}
.totop{position:fixed;left:16px;bottom:84px;z-index:70;width:46px;height:46px;border-radius:50%;border:1px solid var(--border2);background:rgba(255,255,255,.94);backdrop-filter:blur(10px);color:var(--accent-d);font-size:22px;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 24px rgba(0,0,0,.18);opacity:0;transform:translateY(14px) scale(.9);pointer-events:none;transition:.25s cubic-bezier(.2,.8,.2,1)}
.totop.show{opacity:1;transform:translateY(0) scale(1);pointer-events:auto}
.totop:hover{background:linear-gradient(135deg,var(--accent),var(--accent-d));color:#fff;border-color:transparent}

/* modals */
.ov{position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.46);backdrop-filter:blur(3px);display:none;align-items:flex-end;justify-content:center}
.ov.open{display:flex}
.sheet{background:var(--surface);width:100%;max-width:560px;max-height:92vh;overflow-y:auto;overscroll-behavior:contain;border-radius:22px 22px 0 0;box-shadow:0 -20px 60px rgba(0,0,0,.22);animation:up .3s cubic-bezier(.2,.8,.2,1)}
@media(min-width:600px){.ov{align-items:center}.sheet{border-radius:22px}}
@keyframes up{from{transform:translateY(40px);opacity:.4}to{transform:translateY(0);opacity:1}}
.sheet .x{position:sticky;top:0;float:left;margin:12px 12px 0 0;width:46px;height:46px;border-radius:50%;border:none;background:var(--accent-soft);color:var(--accent-d);font-size:24px;line-height:1;cursor:pointer;z-index:5;display:flex;align-items:center;justify-content:center;box-shadow:var(--shadow)}
.sheet .x:hover{background:var(--accent-l);color:#fff}
.pd-gal{display:flex;gap:8px;overflow-x:auto;padding:16px 18px 4px;scroll-snap-type:x mandatory}
.pd-gal img{height:220px;width:auto;border-radius:14px;background:linear-gradient(160deg,#fff,var(--brand-soft));object-fit:contain;scroll-snap-align:center;cursor:zoom-in;border:1px solid var(--border);padding:8px;flex:0 0 auto;max-width:88%}
.zoomov{position:fixed;inset:0;z-index:300;background:rgba(43,30,22,.92);display:none;align-items:center;justify-content:center}
.zoomov.on{display:flex}
.zoomov .ztrack{display:flex;width:100%;height:100%;overflow-x:auto;overflow-y:hidden;scroll-snap-type:x mandatory;
  overscroll-behavior:contain;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.zoomov .ztrack::-webkit-scrollbar{display:none}
.zoomov .zslide{flex:0 0 100%;height:100%;display:flex;align-items:center;justify-content:center;scroll-snap-align:center;scroll-snap-stop:always}
.zoomov img{max-width:94vw;max-height:84vh;object-fit:contain;border-radius:14px;background:#fff;padding:10px;-webkit-user-drag:none;user-select:none}
.zoomov .zx,.zoomov .zn,.zoomov .zc{z-index:2}
.zoomov .zc{direction:ltr;unicode-bidi:isolate}   /* "3 / 6" ולא "6 / 3" */
.zoomov .zx{position:absolute;top:14px;left:14px;width:44px;height:44px;border-radius:50%;border:none;background:#fff;color:var(--brand-d);font-size:20px;cursor:pointer}
.zoomov .zn{position:absolute;top:50%;transform:translateY(-50%);width:44px;height:44px;border-radius:50%;border:none;background:rgba(255,255,255,.9);color:var(--brand-d);font-size:26px;cursor:pointer}
.zoomov .zp{right:12px}.zoomov .zf{left:12px}
.zoomov .zc{position:absolute;bottom:18px;left:0;right:0;text-align:center;color:#fff;font-size:13px;letter-spacing:.06em}
.pd-gal .ph{height:220px;width:220px;display:flex;align-items:center;justify-content:center;background:var(--brand-soft);border-radius:14px}
.pd{padding:6px 22px 26px}
.pd .b{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--brand-d)}
.pd h2{font-size:21px;font-weight:700;line-height:1.25;margin:3px 0 2px}
.pd .en{font-size:13px;color:var(--muted);font-weight:300;margin-bottom:8px}
.pd .row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
.pd .row .tag{font-size:12px;padding:3px 11px}
.pd .pr{font-size:26px;font-weight:700;color:var(--brand-d);margin:8px 0 2px}
.pd .pr-cons{font-size:13.5px;color:var(--muted);font-weight:500;margin:0 0 12px}
.pricewrap{display:flex;flex-direction:column;min-width:0}
.price-cons{font-size:10.5px;color:var(--muted);font-weight:500;line-height:1.2;margin-top:1px;white-space:nowrap}
.pd .pr .was{font-size:15px;color:var(--muted);text-decoration:line-through;margin-inline-start:8px;font-weight:500}
.pd-shades{margin:6px 0 4px}
.pd-shades .lbl{font-size:12px;font-weight:600;color:var(--muted);margin-bottom:6px}
.pd-sw{display:flex;gap:7px;flex-wrap:wrap}
.pd-sw button{font-family:var(--font);font-size:12px;font-weight:600;padding:6px 12px;border-radius:20px;border:1px solid var(--border2);background:var(--surface);color:var(--text);cursor:pointer;transition:.12s}
.pd-sw button.out{opacity:.5;text-decoration:line-through;border-style:dashed}
.pd-sw button.on{background:var(--brand);color:#fff;border-color:transparent}
.pd-sw .dot{display:inline-block;width:13px;height:13px;border-radius:50%;border:1px solid rgba(0,0,0,.12);margin-inline-end:6px;vertical-align:middle}
.pd h4{font-family:var(--font);font-size:17px;font-weight:600;letter-spacing:0;color:var(--brand-d);margin:16px 0 5px;padding-bottom:5px;border-bottom:1px solid var(--border)}
.pd p,.pd li{font-size:13.5px;line-height:1.6;color:#444444;font-weight:300}
.pd .pd-attrs{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 2px}
.pd .pd-attrs .pa{font-size:12.5px;line-height:1.4;padding:5px 11px;border-radius:16px;background:var(--brand-soft);color:var(--brand-d)}
.pd .pd-attrs b{font-weight:600}
.pd .pd-lead{font-size:14.5px;line-height:1.55;color:#171717;font-weight:600;margin:14px 0 2px;padding:11px 13px;background:var(--brand-soft);border-radius:10px;border-inline-start:3px solid var(--brand)}
.pd ul{padding-right:18px;margin-top:4px}
.pd .barc{font-size:12px;color:var(--muted);margin-top:14px;font-family:monospace;direction:ltr;text-align:right}
.pd .cta{width:100%;margin-top:18px;font-family:var(--font);font-size:16px;font-weight:600;color:#fff;border:none;border-radius:14px;padding:14px;cursor:pointer;background:linear-gradient(90deg,var(--brand-d),var(--brand));box-shadow:0 8px 22px rgba(0,0,0,.28)}
.pdfav{display:inline-flex;align-items:center;gap:7px;font-family:var(--font);font-size:13.5px;font-weight:600;cursor:pointer;border:1px solid var(--border2);background:var(--surface);color:var(--accent-d);border-radius:30px;padding:8px 16px;margin:2px 0 6px;transition:.15s}
.pdfav:hover{border-color:var(--accent-l)}.pdfav .h{color:#cbcbcb;font-size:15px}.pdfav.on{background:var(--brand-soft);border-color:var(--brand);color:var(--brand-d)}.pdfav.on .h{color:var(--brand)}
.sim{margin-top:22px}
.sim h4{font-family:var(--font);font-size:17px;font-weight:600;letter-spacing:0;color:var(--brand-d);margin-bottom:9px;padding-bottom:5px;border-bottom:1px solid var(--border)}
.sim-row{display:flex;gap:10px;overflow-x:auto;scrollbar-width:none;padding-bottom:4px}
.sim-row::-webkit-scrollbar{display:none}
.sim-card{flex:0 0 96px;cursor:pointer}
.sim-card .si{width:96px;height:96px;border-radius:12px;background:var(--brand-soft);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;padding:7px}
.sim-card img{max-width:100%;max-height:100%;object-fit:contain;mix-blend-mode:multiply}
.sim-card .sn{font-size:10.5px;line-height:1.25;color:var(--text);margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sim-card .sp{font-size:11.5px;font-weight:700;color:var(--accent-d)}

/* order modal */
.om{padding:8px 20px 24px}
.om h3{font-family:var(--font);font-size:24px;font-weight:600;letter-spacing:0;margin:6px 0 12px;text-align:center}
.om-row{display:flex;align-items:center;gap:10px;padding:11px 0;border-bottom:1px solid var(--border)}
.om-row .om-img{width:46px;height:46px;flex:0 0 46px;object-fit:contain;background:#fff;border:1px solid var(--border);border-radius:8px;padding:3px}
@media(max-width:640px){.om-row .om-img{width:40px;height:40px;flex-basis:40px}}
/* לחיצה על המוצר בסל → קופצים אליו במקומו ברשת (להיזכר מה הוא ולראות מה עמד לידו) */
.om-go{flex:1;display:flex;align-items:center;gap:10px;min-width:0;background:none;border:0;padding:0;margin:0;font:inherit;color:inherit;text-align:inherit;cursor:pointer;border-radius:8px;transition:.15s}
.om-go:hover{background:var(--accent-soft,#f7f4f2)}
.om-go:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.om-go .go-ico{flex:0 0 auto;font-size:12px;color:var(--muted);opacity:0;transition:.15s}
.om-go:hover .go-ico,.om-go:focus-visible .go-ico{opacity:1}
@keyframes cardJump{0%,100%{box-shadow:0 0 0 0 rgba(0,0,0,0)}18%,72%{box-shadow:0 0 0 3px var(--accent)}}
.card.jump{animation:cardJump 2.1s ease-in-out}
.om-row .nm{flex:1;min-width:0;font-size:13.5px;font-weight:500}
.om-row .nm small{display:block;color:var(--muted);font-weight:300;font-size:11.5px}
.qy{display:flex;align-items:center;border:1px solid var(--border2);border-radius:10px;overflow:hidden}
.qy button{width:30px;height:30px;border:none;background:var(--accent-soft);color:var(--accent-d);font-size:17px;cursor:pointer;touch-action:manipulation}
.qy span{min-width:28px;text-align:center;font-size:14px;font-weight:600}
.qy .qin{width:48px;height:30px;border:none;border-inline:1px solid var(--border2);text-align:center;font-size:14px;font-weight:600;font-family:var(--font);background:#fff;-moz-appearance:textfield}
.qy .qin::-webkit-outer-spin-button,.qy .qin::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
.om-row .lt{min-width:62px;text-align:left;font-weight:700;font-size:14px;direction:ltr}
.om-del{border:none;background:none;color:#bbbbbb;font-size:16px;cursor:pointer}
.coupon{display:flex;gap:8px;margin:16px 0 6px}
.coupon input{flex:1;font-family:var(--font);font-size:16px;padding:11px 14px;border:1px solid var(--border2);border-radius:12px;outline:none;background:var(--surface)}
.coupon button{font-family:var(--font);font-weight:600;font-size:14px;border:1px solid var(--accent-l);background:var(--accent-soft);color:var(--accent-d);border-radius:12px;padding:0 18px;cursor:pointer}
.cmsg{font-size:12.5px;font-weight:500;min-height:18px;margin-bottom:6px}
.cmsg.ok{color:#15803d}.cmsg.err{color:#dc2626}
.totals{margin-top:10px;font-size:14px}
.totals .l{display:flex;justify-content:space-between;padding:4px 0;color:var(--muted)}
.totals .l.grand{font-size:19px;font-weight:700;color:var(--text);border-top:1px solid var(--border);margin-top:6px;padding-top:10px}
.totals .l.grand b{color:var(--accent-d)}
/* --- טופס פרטי המזמין --- */
/* תווית אמיתית מעל כל שדה ולא placeholder בלבד: ה-placeholder נעלם ברגע
   שמתחילים להקליד, והלקוח כבר לא רואה מה השדה מבקש. "(לא חובה)" נכתב
   בתוך התווית ולא ככוכבית — כך המשתמש יודע מה מותר לדלג עליו. */
.form{margin-top:16px;display:flex;flex-direction:column;gap:9px}
.f-row{display:flex;flex-direction:column;gap:4px;position:relative}
.f-row>label{font-size:12.5px;font-weight:600;color:var(--muted);padding-inline-start:2px}
.f-row>label .opt{font-weight:400;opacity:.75}
.f-hint{font-size:11.5px;color:var(--muted);opacity:.9;padding-inline-start:2px}
.f-err{font-size:12px;color:#b91c1c;font-weight:600;padding-inline-start:2px;display:none}
.f-row.bad .f-err{display:block}
.f-row.bad .fld{border-color:#b91c1c;background:#fff5f5}
.f-grid{display:grid;grid-template-columns:2fr 1fr;gap:9px}
.f-grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:9px}
.f-toggle{align-self:flex-start;background:none;border:0;padding:2px;font:inherit;font-size:13px;color:var(--accent-d);cursor:pointer;text-decoration:underline}
/* בורר יישוב/רחוב — רשימה קופצת מעל השדה */
.f-pop{position:absolute;z-index:40;inset-inline:0;top:100%;margin-top:3px;max-height:236px;overflow-y:auto;background:var(--surface);border:1px solid var(--border2);border-radius:11px;box-shadow:0 10px 30px rgba(0,0,0,.16);display:none}
.f-pop.show{display:block}
.f-pop li{list-style:none;padding:10px 13px;font-size:15px;cursor:pointer;border-bottom:1px solid var(--border)}
.f-pop li:last-child{border-bottom:0}
.f-pop li[aria-selected="true"],.f-pop li:hover{background:var(--accent-soft,#f7f4f2)}
.f-pop li.none{color:var(--muted);cursor:default;font-size:13px}
.f-pop li .sub{color:var(--muted);font-size:12.5px;margin-inline-start:6px}
.form h4{font-family:var(--font);font-size:17px;font-weight:600;letter-spacing:0;color:var(--brand-d);margin-bottom:1px;padding-bottom:6px;border-bottom:1px solid var(--border)}
.fld,.notes{width:100%;font-family:var(--font);font-size:16px;padding:11px 13px;border-radius:11px;border:1px solid var(--border2);outline:none;background:var(--surface);color:var(--text)}
.notes{resize:vertical;min-height:58px}
.fld:focus,.notes:focus{border-color:var(--accent-l);box-shadow:0 0 0 3px var(--accent-soft)}
.send{width:100%;margin-top:14px;font-family:var(--font);font-size:16px;font-weight:700;color:#fff;border:none;border-radius:14px;padding:15px;cursor:pointer;background:linear-gradient(90deg,#16a34a,#15803d);box-shadow:0 8px 22px rgba(22,163,74,.28)}
.send.pay{background:linear-gradient(90deg,var(--brand-d),var(--brand));box-shadow:0 8px 22px rgba(168,90,109,.3)}
.send:disabled{opacity:.6;cursor:progress}
.send.locked{opacity:.55;cursor:not-allowed;box-shadow:none}   /* 06/10: בלי grayscale — נמרוד: 'עדיין אפור' */
.agree{display:flex;gap:9px;align-items:flex-start;margin-top:14px;font-size:13px;color:var(--text);line-height:1.55;cursor:pointer}
.agree input{width:18px;height:18px;margin-top:1px;flex:0 0 auto;accent-color:var(--accent-d);cursor:pointer}
.agree a{color:var(--accent-d);text-decoration:underline;font-weight:600}
.clear-cart{display:block;margin:10px auto 0;background:none;border:0;padding:6px 10px;font:inherit;font-size:13px;color:var(--muted);cursor:pointer;text-decoration:underline;border-radius:8px}
.clear-cart:hover{color:#b91c1c}
.soldpill{font-size:12px;font-weight:700;color:#b91c1c;background:#fee2e2;border-radius:9px;padding:6px 10px;white-space:nowrap}
/* מוצר שכל הגוונים שלו אזלו — נשאר בקטלוג, מעומעם, עם תג ברור */
.card.sold .imgbox img{filter:grayscale(.75);opacity:.55}
.card.sold .body{opacity:.82}
.soldflag{position:absolute;z-index:3;bottom:10px;left:50%;transform:translateX(-50%);background:#b91c1c;color:#fff;font-size:11.5px;font-weight:800;letter-spacing:.4px;border-radius:999px;padding:5px 14px;box-shadow:0 2px 10px rgba(0,0,0,.18);white-space:nowrap}
.ac-item.sold .ac-nm{opacity:.6}
.ac-sold{margin-inline-start:6px;font-size:10.5px;font-weight:800;color:#b91c1c;background:#fee2e2;border-radius:6px;padding:2px 6px;white-space:nowrap}
.hint{font-size:11.5px;color:var(--muted);text-align:center;margin-top:8px}

@media(max-width:480px){
  .hero{padding:24px 14px 14px}.hero h1{font-size:28px;letter-spacing:0}.hero p{font-size:12.5px}
  .cat{font-size:13px;padding:8px 16px}
  .grid{grid-template-columns:repeat(2,1fr);gap:11px;padding:0 12px;margin-top:10px}
  .card .nm{font-size:12.5px;min-height:33px}.price{font-size:15.5px}
}
.sitefooter{margin-top:40px;padding:26px 18px 28px;background:#111111;color:#dcdcdc;border-top:1px solid rgba(255,255,255,.16)}
.sitefooter .fdisc{max-width:1000px;margin:0 auto 20px;text-align:center;font-size:12.5px;color:#bcbcbc;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:10px 16px}
.sitefooter .fcols{max-width:1000px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:24px}
.sitefooter h4{font-family:var(--font);font-size:18px;color:#fff;margin-bottom:10px;font-weight:600;letter-spacing:0}
.sitefooter p{font-size:13px;line-height:1.7;margin:2px 0;color:#dcdcdc}
.sitefooter a{color:#eeeeee;text-decoration:none}
.sitefooter .flink{display:block;background:none;border:none;color:#dcdcdc;font-family:var(--font);font-size:13px;padding:4px 0;cursor:pointer;text-align:start}
.sitefooter .flink:hover{color:#fff;text-decoration:underline}
.sitefooter .fwa{display:inline-block;margin-top:8px;background:#25d366;color:#062b13;font-weight:700;font-size:13px;padding:8px 16px;border-radius:30px}
.sitefooter .fcopy{max-width:1000px;margin:22px auto 0;text-align:center;font-size:12px;color:#8a8a8a;border-top:1px solid rgba(255,255,255,.1);padding-top:14px}
@media(max-width:640px){.sitefooter .fcols{grid-template-columns:1fr;gap:18px;text-align:center}.sitefooter .flink{text-align:center}}
.policy{padding:8px 26px 26px;line-height:1.75}
.policy h2{font-family:var(--font);font-size:28px;font-weight:600;letter-spacing:0;color:var(--brand-d);margin-bottom:4px}
.policy .note{font-size:12px;color:var(--muted);background:var(--accent-soft);border-radius:10px;padding:8px 12px;margin:8px 0 16px}
.policy h3{font-family:var(--font);font-size:18px;font-weight:600;letter-spacing:0;color:var(--text);margin:16px 0 4px}
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

/* ===== homepage (Sephora-style) additions ===== */
/* hero entry banner (single image, replaced the 3-slide carousel 2026-07-26) */
.ebanner{position:relative;display:block;margin:8px 12px 0;border-radius:18px;overflow:hidden;max-width:1160px;cursor:pointer;background:#120b0e;line-height:0}
@media(min-width:900px){.ebanner{margin:8px auto 0}}
.ebanner picture{display:block}
.ebanner img{display:block;width:100%;height:auto}
/* גרסת הדסקטופ והמובייל מתחלפות בעיצוב בלבד (ולא ב-media של <picture>) — כך התמונה והכפתור
   שמעליה מתחלפים תמיד יחד; בורר המקורות נשאר רק לבחירת פורמט ווב-פי, שאינה תלויה ברוחב המסך */
.ebanner .eb-m{display:none}
@media(max-width:640px){.ebanner .eb-d{display:none}.ebanner .eb-m{display:block}}
/* the pink pill is baked into the artwork — this is the real, clickable/focusable hotspot on top of it */
.ehot{position:absolute;border:none;padding:0;background:transparent;border-radius:999px;cursor:pointer;
  -webkit-tap-highlight-color:transparent;transition:box-shadow .18s,transform .18s}
.ehot span{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.ehot:hover{transform:scale(1.03);box-shadow:0 0 0 3px rgba(255,255,255,.45)}
.ehot:focus-visible{outline:none;box-shadow:0 0 0 3px #fff}
.ehot.d{left:78.29%;top:63.6%;width:16.46%;height:8.56%}
.ehot.m{display:none;left:32.5%;top:84.81%;width:35.08%;height:5.39%}
@media(max-width:640px){.ehot.d{display:none}.ehot.m{display:block}}
@media(prefers-reduced-motion:reduce){.ehot:hover{transform:none}}
/* service icons */
.services{display:flex;justify-content:center;margin:20px 12px 4px;padding:14px 6px;border-top:1px solid var(--border);border-bottom:1px solid var(--border);max-width:1160px}
@media(min-width:900px){.services{margin:22px auto 4px}}
.svc{flex:1;display:flex;flex-direction:column;align-items:center;gap:7px;text-align:center;padding:0 6px;position:relative}
.svc + .svc::before{content:'';position:absolute;inset-inline-start:0;top:6px;bottom:6px;width:1px;background:var(--border)}
.svc svg{width:29px;height:29px;stroke:#171717;stroke-width:1.4;fill:none}
.svc b{font-size:12.5px;font-weight:700}
.svc small{font-size:10.5px;color:var(--muted);line-height:1.3}
@media(max-width:640px){.svc b{font-size:11px}.svc small{font-size:9.5px}.svc svg{width:25px;height:25px}}
/* promo tiles */
.promos{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:18px 12px 0;max-width:1160px}
@media(min-width:900px){.promos{margin:18px auto 0}}
.ptile{border-radius:16px;overflow:hidden;padding:20px;min-height:190px;display:flex;flex-direction:column;justify-content:center;position:relative;border:1px solid var(--border);cursor:pointer}
.ptile.a{background:var(--accent-soft)}.ptile.b{background:var(--brand-soft)}
.ptile .pimg{position:absolute;inset-inline-end:12px;bottom:12px;height:130px;object-fit:contain;border-radius:10px}
.ptile h3{font-family:var(--font);font-weight:600;font-size:24px;line-height:1.15;max-width:60%;margin-bottom:4px}
.ptile p{font-size:13px;color:var(--muted);max-width:55%;margin-bottom:14px}
.ptile .cta{align-self:flex-start;background:#171717;color:#fff;border:none;font-size:13px;font-weight:700;padding:9px 22px;border-radius:30px;cursor:pointer}
@media(max-width:640px){.promos{grid-template-columns:1fr}.ptile .pimg{height:110px}}
/* section header */
.shead{display:flex;align-items:center;justify-content:space-between;margin:26px 16px 12px;max-width:1160px}
@media(min-width:900px){.shead{margin:26px auto 12px}}
.shead h4{font-family:var(--font);font-weight:600;font-size:22px}
.shead .more{font-size:13px;color:var(--muted);text-decoration:none;font-weight:600;background:none;border:none;cursor:pointer}
/* brand logos row */
.brandrow{display:flex;gap:30px;align-items:center;padding:6px 16px 4px;overflow-x:auto;scrollbar-width:none;max-width:1160px;margin:0 auto}
.brandrow::-webkit-scrollbar{display:none}
.brandrow img{height:34px;max-width:120px;object-fit:contain;flex:0 0 auto;cursor:pointer}
.brandrow .btxt{flex:0 0 auto;cursor:pointer;font-family:'Cormorant Garamond',serif;font-size:20px;font-weight:600;color:var(--accent-d);white-space:nowrap}
@media(max-width:640px){.brandrow{padding-bottom:20px}}   /* ריווח מובטח לפני "מומלץ בשבילך" במובייל (padding לא קורס עם margin) */
/* recommended products carousel */
.recs{display:flex;gap:14px;padding:4px 16px 6px;overflow-x:auto;scrollbar-width:none;max-width:1160px;margin:0 auto}
.recs::-webkit-scrollbar{display:none}
.pcard{flex:0 0 156px;background:#fff;border:1px solid var(--border);border-radius:14px;overflow:hidden;position:relative;cursor:pointer}
.pcard .pi{aspect-ratio:1/1;background:var(--accent-soft);display:flex;align-items:center;justify-content:center;padding:12px}
.pcard .pi img{max-width:100%;max-height:100%;object-fit:contain;mix-blend-mode:normal}
.pcard .pb{padding:9px 11px 12px}
.pcard .br{font-size:10px;font-weight:700;letter-spacing:.05em;color:var(--muted);text-transform:uppercase}
.pcard .nm{font-size:12.5px;font-weight:500;line-height:1.3;margin:2px 0 6px;min-height:32px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.pcard .pr{font-size:15px;font-weight:700}
/* shop-all heading */
.shopall{max-width:1400px;margin:28px auto 2px;padding:0 16px}
.shopall h4{font-family:var(--font);font-weight:600;font-size:24px}
/* bottom nav */
.bnav{position:fixed;left:0;right:0;bottom:0;z-index:90;background:#fff;border-top:1px solid var(--border);display:flex;justify-content:space-around;padding:7px 4px calc(7px + env(safe-area-inset-bottom))}
.bnav button{background:none;border:none;display:flex;flex-direction:column;align-items:center;gap:3px;color:var(--muted);font-size:10.5px;font-weight:600;flex:1;font-family:var(--font)}
.bnav svg{width:23px;height:23px;stroke:currentColor;stroke-width:1.5;fill:none}
.bnav button.on{color:#171717}
.bnav button.wa{color:#25d366}.bnav button.wa svg{fill:#25d366;stroke:none}
/* stacking with the fixed bottom nav */
.cartbar{bottom:calc(60px + env(safe-area-inset-bottom,0px))}
.totop{bottom:calc(128px + env(safe-area-inset-bottom,0px))}
.wafloat{display:none}
.wachat{bottom:calc(78px + env(safe-area-inset-bottom,0px));inset-inline-end:12px}
/* 🟢 12/10: כשפס הסל מוצג — חלון הצ'אט מעליו, לא מאחוריו */
body.has-cart .wachat{bottom:calc(150px + env(safe-area-inset-bottom,0px))}
</style>
</head>
<body>
<div class="promobar" id="promobar">
  <span id="promo0">✔ מוצרים מקוריים בלבד</span><span class="pdot">·</span>
  <span id="promo1">🚚 משלוח חינם מעל ₪299</span><span class="pdot">·</span>
  <span id="promo3">⏱ אספקה עד 72 שעות</span>
</div>
<!-- 🏜️ 12/10/2026 — באנר הכניסה של המעצבת נועה. הלוגו שבתוכו מחליף את פס הלוגו
     (שנשאר מוסתר — להחזרה: להסיר את .brandbar{display:none}). הכיתוב טקסט חי
     ומתורגם (hero_*), הרקע = שכבת התמונה מה-PDF שלה, בלי הכיתוב. -->
<section class="dhero" id="dhero" aria-label="Beauty Favorites">
  <div class="hlogo" onclick="goTop()"><img src="logo-bf-white.png" alt="Beauty Favorites — Beauty &amp; Skincare" width="812" height="430"></div>
  <h1><span id="dhH1a">כל המוצרים הנחשקים</span><br><span id="dhH1b">של עולם הביוטי במקום אחד</span></h1>
  <p id="dhSub">מוצרים מקוריים מהמותגים המובילים בעולם שנבחרו במיוחד בשבילך</p>
  <button class="hcta" type="button" onclick="goRecs()"><span id="dhCta">למומלצים שלנו</span><span class="harr" aria-hidden="true">&#10230;</span></button>
  <button class="langbtn" id="langBtn" onclick="toggleLang()" aria-label="Language">العربية</button>
</section>
<div class="brandbar">
  <img class="brandlogo" src="logo-bf.png" width="140" height="68" onclick="goTop()" style="cursor:pointer" alt="Beauty Favorites — Beauty &amp; Skincare">
</div>
<!-- 🧹 06/10/2026 — באנר ההירו הוסר לבקשת נמרוד ("כמו בספורה").
     הוא תפס מסך שלם בטלפון ודחף את הקטגוריות מתחת לקו הקיפול.
     להחזרה: הסר את הערת ה-HTML. -->
<!--
<div class="ebanner" id="ebanner" onclick="goRecs()">
  <picture class="eb-d">
    <source srcset="banner-desktop.webp" type="image/webp">
    <img src="banner-desktop.jpg" width="1981" height="794" fetchpriority="high"
         alt="המועדפים של עולם הביוטי במקום אחד — מוצרים מקוריים מהמותגים האהובים בעולם">
  </picture>
  <picture class="eb-m">
    <source srcset="banner-mobile.webp" type="image/webp">
    <img src="banner-mobile.jpg" width="1000" height="1333" alt="" aria-hidden="true">
  </picture>
  <button class="ehot d" onclick="event.stopPropagation();goRecs()"><span id="ebtnD">למומלצים שלנו</span></button>
  <button class="ehot m" onclick="event.stopPropagation();goRecs()"><span id="ebtnM">למומלצים שלנו</span></button>
</div>
-->


<div class="catsec" id="catsec"></div>
<div class="cattiles" id="cattiles"></div>
<div class="subrow" id="subrow"></div>

<div class="search-wrap">
  <div class="search">
    <span class="ico">⌕</span>
    <input id="q" type="search" autocomplete="off" placeholder="חיפוש מוצר, מותג או ברקוד…" oninput="onSearch()" onkeydown="acKey(event)">
    <button class="clr" id="clrBtn" type="button" onclick="clearSearch()" aria-label="נקה חיפוש" title="נקה">✕</button>
    <div class="ac" id="ac" role="listbox"></div>
  </div>
  <div class="policybar">
    <button class="plink" onclick="openPolicy('about')" id="pbAbout">אודות</button>
    <button class="plink" onclick="openPolicy('contact')" id="pbBiz">צור קשר</button>
    <button class="plink" onclick="openPolicy('shipping')" id="pbShip">משלוחים</button>
    <button class="plink" onclick="openPolicy('returns')" id="pbRet">החזרות</button>
    <button class="plink" onclick="openPolicy('terms')" id="pbTerms">תקנון</button>
    <button class="plink" onclick="openPolicy('privacy')" id="pbPriv">פרטיות</button>
    <button class="plink" onclick="openWholesale()" id="pbWholesale">🔑 כניסת סיטונאי</button>
  </div>
</div>

<!-- 🧹 06/10/2026 — הוסתר לבקשת נמרוד: "לא צריך את כל השורות מתחת לחיפוש".
     משלוח חינם, החזרות, מקוריות ותשלום מאובטח **נשארים בפוטר ובמסמכי
     המדיניות** — לא נמחק שום מידע, רק ירד הרעש מעל המוצרים.
     להחזרה: הסר את הערת ה-HTML. -->
<!--
<div class="services">
  <div class="svc"><svg viewBox="0 0 24 24"><path d="M3 7h11v8H3zM14 10h4l3 3v2h-7z"/><circle cx="7" cy="17" r="1.6"/><circle cx="17.5" cy="17" r="1.6"/></svg><b id="svc1a">משלוח חינם</b><small id="svc1b">בקנייה מעל ₪299</small></div>
  <div class="svc"><svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 14-5l2 2M20 12a8 8 0 0 1-14 5l-2-2"/><path d="M20 4v5h-5M4 20v-5h5"/></svg><b id="svc2a">החזרות חינם</b><small id="svc2b">עד 30 יום</small></div>
  <div class="svc"><svg viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg><b id="svc3a">מוצרים מקוריים</b><small id="svc3b">100% מקורי</small></div>
  <div class="svc"><svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 10h18"/><path d="M9 15h3"/></svg><b id="svc4a">תשלום מאובטח</b><small id="svc4b">הצפנה מלאה</small></div>
</div>
-->

<!-- promo tiles — הוסתרו זמנית לבקשת המשתמש (2026-07-12) עד שיוחלט תוכן; להחזרה: הסר את הערת ה-HTML -->
<!--
<div class="promos">
  <div class="ptile a" data-cat="טיפוח" onclick="goCat('טיפוח')"><h3 id="pt1h">מותגי הטיפוח האהובים</h3><button class="cta">לרכישה</button><img class="pimg" src="cat/skincare.jpg" alt="" loading="lazy"></div>
  <div class="ptile b" data-cat="בושם" onclick="goCat('בושם')"><h3 id="pt2h">בשמים מקוריים</h3><p id="pt2p">מבתי האופנה המובילים</p><button class="cta">לרכישה</button><img class="pimg" src="cat/fragrance.jpg" alt="" loading="lazy"></div>
</div>
-->


<!-- 🧹 06/10/2026 — רצועת המותגים וקרוסלת "מומלץ בשבילך" הוסתרו לבקשת
     נמרוד: "לא את המומלצים והמותגים… כל העניין היה לפשט את החיפוש".
     **שתיהן עדיין נבנות ב-JS** (buildBrandRow/buildRecs) ולכן החזרה היא
     הסרת הערה בלבד; בורר המותגים המלא נשאר זמין מכפתור הסינון.
     להחזרה: הסר את הערת ה-HTML. -->
<!--
<div class="shead"><h4 id="brTitle">המותגים האהובים</h4><button class="more" onclick="openBrandModal()" id="brMore">לכל המותגים ›</button></div>
<div class="brandrow" id="brandRow"></div>
<div class="shead"><h4 id="recTitle">מומלץ בשבילך</h4><button class="more" onclick="goShop()" id="recMore">לכל המוצרים ›</button></div>
<div class="recs" id="recRow"></div>
-->

<div class="wsbanner" id="wsBanner" style="display:none">
  <span id="wsBannerTxt">מצב סיטונאי פעיל — מוצגים מחירי סיטונאי</span>
  <button onclick="wholesaleLogout()">יציאה</button>
</div>

<div class="shopall"><h4 id="shopAllT">כל המוצרים</h4></div>
<div class="toolbar">
  <button class="brandpickbtn" id="brandPickBtn" onclick="openBrandModal()">
    <span class="bpi">🏷️</span><span id="brandPickLbl">כל המותגים</span><span class="bpchev">▾</span>
  </button>
  <button class="brandpickbtn" id="filterBtn" onclick="openFilterModal()" style="display:none">
    <span id="filterLbl">סינון</span><span class="bpchev">▾</span>
  </button>
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

<!-- 🎛️ 12/10/2026 — מגירת סינון אחת (כמו בספורה) במקום שלוש שכבות. בטלפון: נשלפת מהצד;
     במחשב: עמודה קבועה ליד הרשת. סרגל הכלים הישן (.toolbar), בועות תת-הקטגוריה (.subrow)
     ופס "מסונן לפי" (.actfil) נשארים ב-DOM מוסתרים — הלוגיקה שלהם עדיין בשימוש. -->
<div class="shopwrap" id="shopwrap">
<aside class="fdrawer" id="fdrawer" aria-label="סינון">
  <div class="fdhead"><h3 id="fdTitle">סינון</h3><button class="fdx" type="button" onclick="closeDrawer()" aria-label="סגירה">✕</button></div>
  <div class="fdq"><span class="ico" aria-hidden="true">⌕</span><input id="fdQ" type="search" autocomplete="off" placeholder="חיפוש מוצר, מותג או ברקוד…" oninput="drawerSearch(this.value)"></div>
  <div class="fdbody" id="fdBody"></div>
  <div class="fdfoot">
    <div class="fdchips" id="fdChips"></div>
    <button class="fdclear" id="fdClear" type="button" onclick="drawerClear()">נקה הכל</button>
    <button class="fdshow" id="fdShow" type="button" onclick="closeDrawer()">הצגה</button>
  </div>
</aside>
<div class="shopmain">
<div class="cathead" id="cathead"></div>
<div class="fbar" id="fbar">
  <button class="fbtn" id="fbBtn" type="button" onclick="openDrawer()">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/><circle cx="9" cy="7" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="10" cy="17" r="2"/></svg>
    <span id="fbLbl">סינון מומלץ</span><b class="fbn" id="fbN"></b>
  </button>
  <span class="fbcount" id="rescount"></span>
  <div class="fbchips" id="fbChips"></div>
</div>
<div class="actfil" id="actFil"></div>
<main class="grid" id="grid"></main>
</div>
</div>
<div class="fback" id="fback" onclick="closeDrawer()"></div>


<footer class="sitefooter">
  <div class="fdisc" id="fDisc">מכירה עצמאית של מוצרים מקוריים · כל הסימנים המסחריים שייכים לבעליהם</div>
  <div class="fcols">
    <div class="fcol">
      <h4 id="fBizT">פרטי העסק</h4>
      <p>שניר שריקי – יבוא ושיווק מותגי שיער וקוסמטיקה</p>
      <p>עוסק מורשה: 040553562</p>
      <p>טלפון: <a href="tel:0534555501">053-4555501</a></p>
      <p>אימייל: <a href="mailto:beautyfavorites2026@gmail.com">beautyfavorites2026@gmail.com</a></p>
      <p id="fVat">המחירים כוללים מע״מ · משלוחים לכל הארץ</p>
    </div>
    <div class="fcol">
      <h4 id="fInfoT">מידע ומדיניות</h4>
      <button class="flink" onclick="openPolicy('about')" id="fAbout">אודות</button>
      <button class="flink" onclick="openPolicy('shipping')" id="fShip">משלוחים ואספקה</button>
      <button class="flink" onclick="openPolicy('returns')" id="fRet">החזרות וביטולים</button>
      <button class="flink" onclick="openPolicy('terms')" id="fTerms">תקנון</button>
      <button class="flink" onclick="openPolicy('privacy')" id="fPriv">מדיניות פרטיות</button>
      <button class="flink" onclick="openPolicy('accessibility')" id="fAccess">הצהרת נגישות</button>
    </div>
    <div class="fcol">
      <h4 id="fOrderT">הזמנות</h4>
      <p id="fShipFree">משלוח חינם בהזמנה מעל ₪299</p>
      <p id="fEta">אספקה עד 72 שעות מרגע איסוף ע״י השליח</p>
      <button class="flink" onclick="openWholesale()" id="fClub">💼 מועדון עסקים — מחירון סיטונאי</button>
      <a class="fwa" href="https://wa.me/972534555501" id="fWa">הזמנה בוואטסאפ</a>
    </div>
  </div>
  <div class="fcopy">© שניר שריקי · Beauty Favorites</div>
</footer>

<div class="cartbar" id="cartbar">
  <span class="sum" id="cartsum"></span>
  <button id="viewOrderBtn" onclick="openOrder()">צפה בהזמנה ←</button>
</div>
<button class="totop" id="toTop" onclick="goTop()" aria-label="חזרה למעלה" title="חזרה למעלה">↑</button>
<button class="wafloat" id="waFloat" onclick="toggleWaChat()" aria-label="יש שאלה? דברו איתנו בוואטסאפ" title="יש שאלה? דברו איתנו בוואטסאפ">
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2 22l5.25-1.38c1.45.79 3.08 1.2 4.79 1.2h.01c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2m0 18.15h-.01c-1.52 0-3.01-.41-4.3-1.18l-.31-.18-3.2.84.85-3.12-.2-.32a8.2 8.2 0 0 1-1.26-4.37c0-4.54 3.7-8.24 8.24-8.24 2.2 0 4.27.86 5.82 2.42a8.18 8.18 0 0 1 2.41 5.83c0 4.54-3.7 8.24-8.23 8.24m4.52-6.16c-.25-.12-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.13-.16.24-.64.8-.79.97-.14.16-.29.18-.54.06-.25-.12-1.05-.39-1.99-1.23-.74-.66-1.23-1.47-1.38-1.72-.14-.25-.01-.38.11-.51.11-.11.25-.29.37-.43.13-.14.17-.25.25-.41.08-.17.04-.31-.02-.43-.06-.12-.56-1.34-.76-1.84-.2-.48-.4-.42-.56-.42h-.48c-.16 0-.43.06-.66.31-.22.25-.86.85-.86 2.07 0 1.22.89 2.4 1.01 2.56.12.17 1.75 2.67 4.24 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.47-.6 1.68-1.18.21-.58.21-1.08.14-1.18-.06-.11-.22-.17-.47-.29"/></svg>
</button>
<div class="wachat" id="waChat">
  <div class="wachat-head">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2 22l5.25-1.38c1.45.79 3.08 1.2 4.79 1.2h.01c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2m4.52 11.99c-.25-.12-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.13-.16.24-.64.8-.79.97-.14.16-.29.18-.54.06-.25-.12-1.05-.39-1.99-1.23-.74-.66-1.23-1.47-1.38-1.72-.14-.25-.01-.38.11-.51.11-.11.25-.29.37-.43.13-.14.17-.25.25-.41.08-.17.04-.31-.02-.43-.06-.12-.56-1.34-.76-1.84-.2-.48-.4-.42-.56-.42h-.48c-.16 0-.43.06-.66.31-.22.25-.86.85-.86 2.07 0 1.22.89 2.4 1.01 2.56.12.17 1.75 2.67 4.24 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.47-.6 1.68-1.18.21-.58.21-1.08.14-1.18-.06-.11-.22-.17-.47-.29"/></svg>
    <span class="wt" id="waChatTitle">צריכים עזרה? כתבו לנו</span>
    <button class="wx" onclick="toggleWaChat()" aria-label="סגור">✕</button>
  </div>
  <div class="wachat-body">
    <div class="wgreet" id="waChatGreet">כתבו את ההודעה שלכם ונחזור אליכם מיד בוואטסאפ.</div>
    <textarea id="waChatMsg" placeholder="ההודעה שלי…" onkeydown="if(event.key==='Enter'&&(event.metaKey||event.ctrlKey))sendWaChat()"></textarea>
    <button class="wachat-send" onclick="sendWaChat()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z"/></svg><span id="waChatSend">שלח בוואטסאפ</span></button>
  </div>
</div>

<div class="ov" id="pdModal"><div class="sheet"><button class="x" onclick="closePd()">✕</button><div id="pdContent"></div></div></div>
<!-- 🔍 06/10/2026 — הגדלת תמונה (נמרוד). לחיצה על תמונה בגלריה פותחת אותה
     במסך מלא; חיצים/החלקה בין התמונות; לחיצה ברקע, ✕ או Escape סוגרים. -->
<div class="zoomov" id="zoomOv" onclick="if(event.target===this)closeZoom()" role="dialog" aria-modal="true" aria-label="תמונה מוגדלת">
  <button class="zx" onclick="closeZoom()" aria-label="סגירה">✕</button>
  <button class="zn zp" onclick="zoomStep(-1)" aria-label="הקודמת">›</button>
  <div class="ztrack" id="zoomTrack" dir="rtl"></div>
  <button class="zn zf" onclick="zoomStep(1)" aria-label="הבאה">‹</button>
  <div class="zc" id="zoomCnt"></div>
</div>

<div class="ov" id="orderModal"><div class="sheet">
  <button class="x" onclick="closeOrder()">✕</button>
  <div class="om">
    <h3 id="omTitle">ההזמנה שלי</h3>
    <div id="omBody"></div>
    <button type="button" class="clear-cart" id="clearCartBtn" onclick="clearCart()">🗑️ נקה את הסל</button>
    <div class="coupon"><input id="coupon" type="text" placeholder="קוד קופון" oninput="couponEdited()" onkeydown="if(event.key==='Enter'){event.preventDefault();applyCoupon();}"><button id="couponBtn" onclick="applyCoupon()">החל</button></div>
    <div class="cmsg" id="cmsg"></div>
    <div class="totals" id="totals"></div>
    <form class="form" id="buyerForm" autocomplete="on" onsubmit="return false">
      <h4 id="buyerTitle">פרטי המזמין</h4>

      <div class="f-row" id="row-name">
        <label for="buyer-name" id="lb-name">שם מלא</label>
        <input class="fld" id="buyer-name" name="name" type="text" autocomplete="name" oninput="clearErr('row-name')">
        <span class="f-err" id="er-name"></span>
      </div>

      <div class="f-row" id="row-phone">
        <label for="buyer-phone" id="lb-phone">טלפון נייד</label>
        <input class="fld" id="buyer-phone" name="tel" type="tel" inputmode="tel" autocomplete="tel-national" oninput="clearErr('row-phone')" onblur="checkPhone()">
        <span class="f-hint" id="hint-phone">לתיאום המסירה מול השליח</span>
        <span class="f-err" id="er-phone"></span>
      </div>

      <div class="f-row" id="row-city">
        <label for="buyer-city" id="lb-city">יישוב</label>
        <input class="fld" id="buyer-city" name="city" type="text" autocomplete="address-level2"
               role="combobox" aria-expanded="false" aria-autocomplete="list" aria-controls="pop-city"
               oninput="cityInput()" onkeydown="popKey(event,'city')" onblur="cityBlur()" onchange="setTimeout(resolveAutofill,60)">
        <ul class="f-pop" id="pop-city" role="listbox" aria-label="יישובים"></ul>
        <span class="f-err" id="er-city"></span>
      </div>

      <div class="f-grid">
        <div class="f-row" id="row-street">
          <label for="buyer-street" id="lb-street">רחוב</label>
          <input class="fld" id="buyer-street" name="address" type="text" autocomplete="address-line1"
                 role="combobox" aria-expanded="false" aria-autocomplete="list" aria-controls="pop-street"
                 oninput="streetInput()" onkeydown="popKey(event,'street')" onblur="streetBlur()" onchange="setTimeout(resolveAutofill,60)">
          <ul class="f-pop" id="pop-street" role="listbox" aria-label="רחובות"></ul>
          <span class="f-hint" id="hint-street"></span>
          <span class="f-err" id="er-street"></span>
        </div>
        <div class="f-row" id="row-house">
          <label for="buyer-house" id="lb-house">מספר בית</label>
          <input class="fld" id="buyer-house" name="house-number" type="text" inputmode="numeric" oninput="clearErr('row-house')" onchange="resolveAutofill()">
          <span class="f-err" id="er-house"></span>
        </div>
      </div>

      <button type="button" class="f-toggle" id="bldgToggle" onclick="toggleBldg()">+ דירה, קומה, כניסה</button>
      <div class="f-grid3" id="bldgRow" style="display:none">
        <div class="f-row"><label for="buyer-apt" id="lb-apt">דירה</label><input class="fld" id="buyer-apt" name="apartment" type="text" inputmode="numeric" autocomplete="address-line2" onchange="resolveAutofill()"></div>
        <div class="f-row"><label for="buyer-floor" id="lb-floor">קומה</label><input class="fld" id="buyer-floor" type="text" inputmode="numeric"></div>
        <div class="f-row"><label for="buyer-entrance" id="lb-entrance">כניסה</label><input class="fld" id="buyer-entrance" type="text"></div>
      </div>

      <div class="f-row" id="row-email">
        <label for="buyer-email" id="lb-email">אימייל</label>
        <input class="fld" id="buyer-email" name="email" type="email" inputmode="email" autocomplete="email" oninput="clearErr('row-email')">
        <span class="f-hint" id="hint-email"></span>
        <span class="f-err" id="er-email"></span>
      </div>

      <div class="f-row">
        <label for="buyer-id" id="lb-id">מספר עוסק / ח.פ / ת.ז</label>
        <input class="fld" id="buyer-id" type="text" inputmode="numeric" autocomplete="off">
      </div>

      <div class="f-row">
        <label for="notes" id="lb-notes">הערות לשליח</label>
        <textarea class="notes" id="notes"></textarea>
      </div>
    </form>
    <label class="agree" id="agreeWrap">
      <input type="checkbox" id="agreeTerms" onchange="syncAgree()">
      <span id="agreeTxt">קראתי ואני מסכים/ה ל<a href="#" onclick="openPolicy('terms');return false">תקנון</a> ול<a href="#" onclick="openPolicy('privacy');return false">מדיניות הפרטיות</a></span>
    </label>
    <button class="send pay" id="payBtn" onclick="payNow()" style="display:none">שלם עכשיו 💳</button>
    <button class="send" id="sendBtn" onclick="submitWhatsApp()">שלח הזמנה לאישור (וואטסאפ)</button>
    <div class="hint" id="sendHint">ההזמנה תיפתח ב-WhatsApp עם מספר ההזמנה</div>
  </div>
</div></div>

<div class="ov" id="policyModal"><div class="sheet"><button class="x" onclick="closeOv('policyModal')">✕</button><div class="policy" id="policyBody"></div></div></div>

<div class="ov" id="brandModal"><div class="sheet brandsheet"><button class="x" onclick="closeOv('brandModal')">✕</button>
  <div class="bm">
    <h3 id="brandModalTitle">בחירת מותג</h3>
    <div class="bsearch"><span class="ico">⌕</span><input id="brandSearch" type="search" autocomplete="off" placeholder="חיפוש מותג…" oninput="renderBrandGrid()"></div>
    <div class="bgrid" id="brandGrid"></div>
    <button class="bdone" id="brandDone" onclick="closeOv('brandModal')">סגירה</button>
  </div>
</div></div>

<div class="ov" id="filterModal"><div class="sheet filtersheet"><button class="x" onclick="closeOv('filterModal')">✕</button>
  <div class="bm">
    <h3 id="filterTitle">סינון</h3>
    <div id="filterBody"></div>
    <button class="bdone" id="filterDone" onclick="closeOv('filterModal')">סגירה</button>
  </div>
</div></div>

<div class="ov" id="clubModal"><div class="sheet"><button class="x" onclick="closeOv('clubModal')">✕</button>
  <div class="om">
    <h3 id="clubTitle">💼 מועדון העסקים</h3>
    <p id="clubSub" style="font-size:14px;line-height:1.7;color:#473d5e;margin:2px 0 16px">מספרה, מאפרת או חנות? הצטרפו למועדון העסקים שלנו וקבלו גישה למחירון סיטונאי מיוחד, שירות אישי והטבות לעסקים.</p>
    <a class="send" id="clubJoin" target="_blank" rel="noopener" style="display:block;text-align:center;text-decoration:none"
       href="https://wa.me/972534555501?text=%D7%A9%D7%9C%D7%95%D7%9D%21%20%D7%90%D7%A0%D7%99%20%D7%9E%D7%A2%D7%95%D7%A0%D7%99%D7%99%D7%9F%2F%D7%AA%20%D7%9C%D7%94%D7%A6%D7%98%D7%A8%D7%A3%20%D7%9C%D7%9E%D7%95%D7%A2%D7%93%D7%95%D7%9F%20%D7%94%D7%A2%D7%A1%D7%A7%D7%99%D7%9D%20%28%D7%9E%D7%97%D7%99%D7%A8%D7%95%D7%9F%20%D7%A1%D7%99%D7%98%D7%95%D7%A0%D7%90%D7%99%29">📲 הצטרפות בוואטסאפ</a>
    <button class="send pay" id="clubHave" onclick="closeOvNow('clubModal');openWsCode()" style="margin-top:10px">🔑 יש לי קוד סיטונאי</button>
  </div>
</div></div>

<div class="ov" id="wsModal"><div class="sheet"><button class="x" onclick="closeOv('wsModal')">✕</button>
  <div class="om">
    <h3 id="wsTitle">כניסת סיטונאי</h3>
    <p class="muted" id="wsSub" style="margin:2px 0 12px">הזן קוד סיטונאי כדי לראות מחירי סיטונאי.</p>
    <input class="fld" id="wsCode" type="text" placeholder="קוד סיטונאי" autocomplete="off" onkeydown="if(event.key==='Enter')submitWholesale()">
    <div class="cmsg" id="wsMsg"></div>
    <button class="send" id="wsGo" onclick="submitWholesale()">כניסה</button>
  </div>
</div></div>

<nav class="bnav" id="bnav">
  <button class="on" onclick="goTop()"><svg viewBox="0 0 24 24"><path d="M4 11l8-7 8 7M6 10v9h12v-9"/></svg><span id="nvHome">בית</span></button>
  <button onclick="navFilter()"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg><span id="nvSearch">חיפוש</span></button>
  <button onclick="showFavs()"><svg viewBox="0 0 24 24"><path d="M12 21s-7-4.6-9.3-9C1 8.5 3 5 6.5 5 8.7 5 10.5 6.4 12 8.4 13.5 6.4 15.3 5 17.5 5 21 5 23 8.5 21.3 12 19 16.4 12 21 12 21z"/></svg><span id="nvFav">מועדפים</span></button>
  <button onclick="openOrder()"><svg viewBox="0 0 24 24"><circle cx="9" cy="20" r="1.4"/><circle cx="17" cy="20" r="1.4"/><path d="M3 4h2l2.2 11h9.6l1.7-8H6.4"/></svg><span id="nvCart">עגלה</span></button>
  <button class="wa" id="navWa" onclick="toggleWaChat()"><svg viewBox="0 0 24 24"><path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2 22l5.25-1.38c1.45.79 3.08 1.2 4.79 1.2h.01c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2m4.52 11.99c-.25-.12-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.13-.16.24-.64.8-.79.97-.14.16-.29.18-.54.06-.25-.12-1.05-.39-1.99-1.23-.74-.66-1.23-1.47-1.38-1.72-.14-.25-.01-.38.11-.51.11-.11.25-.29.37-.43.13-.14.17-.25.25-.41.08-.17.04-.31-.02-.43-.06-.12-.56-1.34-.76-1.84-.2-.48-.4-.42-.56-.42h-.48c-.16 0-.43.06-.66.31-.22.25-.86.85-.86 2.07 0 1.22.89 2.4 1.01 2.56.12.17 1.75 2.67 4.24 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.47-.6 1.68-1.18.21-.58.21-1.08.14-1.18-.06-.11-.22-.17-.47-.29"/></svg><span id="nvWa">וואטסאפ</span></button>
</nav>

<script>
const GROUPS = /*__GROUPS__*/;
// 🗂️ עץ הקטגוריות — 8 קבוצות ו-50 תתי-קטגוריות מהמסד (06/10/2026).
// מחליף את CATS השטוח. ריק = אין רשת בבנייה, והאתר נופל לשכבה הישנה.
const CATTREE = /*__CATTREE__*/;
const BRAND_ALIASES={
 "Dior":"דיור","DIOR":"דיור","דיור (Dior)":"דיור",
 // 🔴 תוקן 06/09/2026 — המפה הזו רצה **בדפדפן** וממפה את המותג אחרי הבנייה.
 // היא קנוניזה אל תעתיקים שגויים ואל כתב לטיני, ולכן הפכה גם את מה שתוקן במסד
 // וגם את מה שתוקן ב-BRAND_MAP של הבנייה. הכיוון הפוך עכשיו.
 "YSL":"איב סן לורן","ייב סן לורן":"איב סן לורן","Yves Saint Laurent":"איב סן לורן",
 "M.A.C":"מאק","Mac":"מאק","MAC":"מאק",
 "Makeup for ever":"מייק אפ פור אבר","Make Up For Ever":"מייק אפ פור אבר","מייקאפ פוראבר":"מייק אפ פור אבר",
 "ONE/SIZE":"וואן סייז","וואן/סייז":"וואן סייז","וואן סייז (ONE/SIZE)":"וואן סייז",
 "RHODE":"רוד","Rhode":"רוד","רואד":"רוד","רואד (RHODE)":"רוד",
 "Ordinary":"דה אורדינרי","The Ordinary":"דה אורדינרי","Saie":"סאיי","SAIE":"סאיי",
 "ריר ביוטי":"רייר ביוטי","Rare Beauty":"רייר ביוטי",
 "NYX":"נייקס","NYX Professional Makeup":"נייקס","K18":"קיי 18",
 "Glow Recipe":"גלואו רסיפי","Gisou":"ג'יסו","Mugler":"מוגלר","Kryolan":"קריולן",
 "אורבן דקיי":"אורבן דיקיי","Urban Decay":"אורבן דיקיי",
 "SEPHORA":"ספורה","Sephora Collection":"ספורה","אוארגלאס":"האורגלאס","אוורגלאס":"האורגלאס","Hourglass":"האורגלאס",
 "ספורה קולקשן":"ספורה","ספורה פייבוריטס":"ספורה","Sephora Favorites":"ספורה",
 "Charlotte Tilbury":"שרלוט טילבורי","Charlotte Tilbury Beauty":"שרלוט טילבורי",
 // כפילויות איות שאותרו בנתונים החיים (27/08). בלעדיהן הסינון מפצל מותג
 // אחד לשניים והלקוח שבוחר איות אחד לא רואה את המוצרים של השני.
 "שרלוט טילברי":"שרלוט טילבורי",
 "סול דה ז'ניירו":"סול דה ז'נרו","סול דה ז\u05f3נרו":"סול דה ז'נרו",
 "מורף":"מורפי","אנסטסיה":"אנסטסיה בוורלי הילס","אנסטסיה בברלי הילס":"אנסטסיה בוורלי הילס","אנסטסיה בברלי הילז":"אנסטסיה בוורלי הילס",
 "קלר וואו":"קולור וואו","לוריאל פריז":"לוריאל","לוריאל פריס":"לוריאל",
 "קיהל'ס":"קילס","האוס לאבס ביי ליידי גאגא":"האוס לאבס",
 "ספורה קולקשן":"ספורה","קאיאלי":"קייאלי","KAYALI":"קייאלי","Kayali":"קייאלי"
};
function canonBrand(b){return BRAND_ALIASES[b]||b||'אחר';}
GROUPS.forEach(g=>{g.brand=canonBrand(g.brand);});
GROUPS.forEach((g,i)=>{g._i=i; g.minp=Math.min(...g.variants.map(eff)); g._noimg=g.variants.every(v=>!v.imgs||!v.imgs.length);});

/* ===== i18n: UI language toggle (HE / AR). The WhatsApp order text stays Hebrew always. ===== */
const I18N={
 he:{search_ph:'חיפוש מוצר, מותג או ברקוד…',fav_only:'המועדפים שלי',in_stock:'נמצא במלאי',in_stock_short:'במלאי',reset_all:'נקה הכל',af_lbl:'מסונן לפי:',af_clear:'✕ נקה הכל והצג הכל',af_cat:'קטגוריה',af_brand:'מותג',af_price:'מחיר',af_fav:'מועדפים',af_stock:'במלאי בלבד',af_q:'חיפוש',cons_rec:'מומלץ לצרכן:',
  sort_default:'מיון: מומלץ',sort_pa:'מחיר: מהנמוך לגבוה',sort_pd:'מחיר: מהגבוה לנמוך',sort_name:'שם: א׳–ת׳',
  all:'הכל',all_brands:'כל המותגים',all_prices:'כל המחירים',
  p_u50:'עד ₪50',p_50_100:'₪50–100',p_100_200:'₪100–200',p_200p:'₪200+',
  items:'מוצרים',cart_items:'פריטים',empty:'לא נמצאו מוצרים מתאימים 🔍',
  view_order:'צפה בהזמנה ←',totop:'חזרה למעלה',
  c_איפור:'איפור',c_טיפוח:'טיפוח',c_שיער:'שיער',c_בושם:'בושם',c_מארזים:'מארזים',c_ציפורניים:'ציפורניים',c_אביזרים:'אביזרים',c_ציוד:'ציוד',c_אחר:'אחר',
  cat_hot:'הנמכרים ביותר',   /* 12/10 נמרוד, כמו בדוגמת המעצבת. היה '🔥 Best Seller' */
  go_to_product:'הצג בקטלוג',clear_cart:'נקה את הסל',clear_cart_ask:'להסיר את כל {n} הפריטים מהסל?',
  b_sale:'מבצע',b_new:'חדש',b_bestseller:'רב-מכר',b_soldout:'אזל',b_limited:'מהדורה מוגבלת',b_vegan:'טבעוני',
  shades:'גוונים',feats:'מאפיינים עיקריים',ingredients:'רכיבים',usage:'אופן שימוש',contents_h:'מה כלול במבחר',
  pick_shade:'בחר גוון',similar:'מוצרים דומים',desc:'תיאור',barcode:'ברקוד:',
  add_order:'הוסף להזמנה',fav_remove:'במועדפים — הסר',fav_add:'הוסף למועדפים',
  my_order:'ההזמנה שלי',coupon_ph:'קוד קופון',apply:'החל',buyer_details:'פרטי המזמין',
  full_name:'שם מלא *',biz_name:'שם העסק / החנות (לחשבונית)',biz_id:'מספר עוסק מורשה / ח.פ / ת.ז',
  ship_addr:'עיר וכתובת למשלוח',phone:'טלפון *',notes_ph:'הערות להזמנה (אופציונלי)…',
  email_ph:'אימייל — לקבלת אישור וחשבונית (חובה בתשלום באתר)',alert_email:'לתשלום באתר צריך כתובת אימייל — אליה נשלח את האישור והחשבונית.',
  l_name:'שם מלא',l_phone:'טלפון נייד',l_city:'יישוב',l_street:'רחוב',l_house:'מספר בית',
  l_apt:'דירה',l_floor:'קומה',l_entrance:'כניסה',l_email:'אימייל',l_id:'מספר עוסק / ח.פ / ת.ז',l_notes:'הערות לשליח',
  l_opt:'(לא חובה)',phone_hint:'לתיאום המסירה מול השליח',
  bldg_show:'+ דירה, קומה, כניסה',bldg_hide:'− הסתר פרטי בניין',
  city_ph:'הקלד/י שם יישוב…',street_ph:'הקלד/י שם רחוב…',street_free:'רחוב או תיאור הכתובת',
  no_streets:'ביישוב זה אין רשימת רחובות — נא לכתוב את הכתובת המלאה',
  city_first:'קודם בוחרים יישוב',no_match:'לא נמצאה התאמה — אפשר להקליד חופשי',
  err_city:'נא למלא יישוב',err_street:'נא למלא רחוב או כתובת',err_house:'נא למלא מספר בית',
  err_phone:'מספר טלפון לא תקין — נייד 10 ספרות (05X) או קווי 9 ספרות',
  send_order:'שלח הזמנה לאישור (וואטסאפ)',send_hint:'ההזמנה תיפתח ב-WhatsApp עם מספר ההזמנה',
  pay_now:'שלם עכשיו 💳',sold_out:'אזל',sending:'שולח…',err_order:'אירעה תקלה ביצירת ההזמנה. נסה שוב.',
  pay_ok:'התשלום התקבל בהצלחה! 🎉 הזמנה מספר {id} אושרה — פרטי אישור נשלחו אליך. תודה שקנית בביוטי פייבוריטס!',
  pay_fail:'התשלום לא הושלם. ההזמנה שלך ({id}) שמורה אצלנו — אפשר לנסות שוב או לפנות אלינו בוואטסאפ 053-4555501.',
  cart_empty:'העגלה ריקה',subtotal:'סכום ביניים',discount:'הנחה',vat:'מע"מ 18%',grand:'סה"כ לתשלום',incl_vat:'המחירים כוללים מע"מ',
  coupon_ok:'✓ קופון הוחל: ',coupon_bad:'קוד קופון לא תקין',off:'הנחה',
  ws_enter:'🔑 כניסת סיטונאי',ws_exit:'יציאה ממצב סיטונאי',ws_title:'כניסת סיטונאי',ws_sub:'הזן קוד סיטונאי כדי לראות מחירי סיטונאי.',ws_ph:'קוד סיטונאי',ws_go:'כניסה',ws_bad:'קוד שגוי',ws_unavailable:'לא זמין כרגע',ws_active:'מצב סיטונאי פעיל — מוצגים מחירי סיטונאי',
  alert_empty:'העגלה ריקה',alert_fill:'נא למלא שם מלא וטלפון לפני שליחת ההזמנה',other:'العربية',
  alert_terms:'יש לאשר את התקנון ומדיניות הפרטיות לפני שליחת ההזמנה',
  agree_txt:'קראתי ואני מסכים/ה ל<a href="#" onclick="openPolicy(\'terms\');return false">תקנון</a> ול<a href="#" onclick="openPolicy(\'privacy\');return false">מדיניות הפרטיות</a>',
  f_about:'אודות',
  found_in:'נמצא ב:',
  brands_n:'מותגים', show_n:'הצגת {n} מוצרים', bm_close:'סגירה', filter:'סינון', f_clear:'ניקוי הסינון',
  fb_lbl:'סינון מומלץ', fd_sort:'מיון', sort_rec:'מומלץ', fd_sub:'תת־קטגוריה', fd_brand:'מותג', fd_price:'מחיר', fd_misc:'עוד', fd_bq:'חיפוש מותג…', fd_more:'עוד {n} מותגים', fd_less:'פחות מותגים',
  cat_sec:'קטגוריות',
  dh_h1a:'כל המוצרים הנחשקים',dh_h1b:'של עולם הביוטי במקום אחד',
  dh_sub:'מוצרים מקוריים מהמותגים המובילים בעולם שנבחרו במיוחד בשבילך',dh_cta:'למומלצים שלנו',
  f_disc:'מכירה עצמאית של מוצרים מקוריים · כל הסימנים המסחריים שייכים לבעליהם',
  hero_sub:'הקולקציה הנבחרת — איפור · טיפוח · שיער · בושם',
  ebtn:'למומלצים שלנו',
  svc1a:'משלוח חינם', svc1b:'בקנייה מעל ₪299', svc2a:'החזרות חינם', svc2b:'עד 30 יום', svc3a:'מוצרים מקוריים', svc3b:'100% מקורי', svc4a:'תשלום מאובטח', svc4b:'הצפנה מלאה',
  pt1h:'מותגי הטיפוח האהובים', pt2h:'בשמים מקוריים', pt2p:'מבתי האופנה המובילים', buy:'לרכישה',
  br_title:'המותגים האהובים', br_more:'לכל המותגים ›', rec_title:'מומלץ בשבילך', rec_more:'לכל המוצרים ›', shop_all:'כל המוצרים',
  nv_home:'בית', nv_search:'חיפוש', nv_fav:'מועדפים', nv_cart:'עגלה', nv_wa:'וואטסאפ',
  f_biz:'פרטי העסק',f_contact:'צור קשר',f_vat:'המחירים כוללים מע״מ · משלוחים לכל הארץ',f_info:'מידע ומדיניות',
  f_ship:'משלוחים ואספקה',f_ret:'החזרות וביטולים',f_terms:'תקנון',f_priv:'מדיניות פרטיות',
  f_order:'הזמנות',f_free:'משלוח חינם בהזמנה מעל ₪299',f_eta:'אספקה עד 72 שעות מרגע איסוף ע״י השליח',f_wa:'הזמנה בוואטסאפ',
  pb_ship:'משלוחים',pb_ret:'החזרות',pb_priv:'פרטיות',
  promo_orig:'✔ מוצרים מקוריים בלבד',
  promo_free:'🚚 משלוח חינם מעל ₪299',promo_coupon:'🎁 10% הנחה עם קופון BEAUTY10',promo_eta:'⏱ אספקה עד 72 שעות',
  club_link:'💼 מועדון עסקים',club_footer:'💼 מועדון עסקים — מחירון סיטונאי',club_title:'💼 מועדון העסקים',
  club_sub:'מספרה, מאפרת או חנות? הצטרפו למועדון העסקים שלנו וקבלו גישה למחירון סיטונאי מיוחד, שירות אישי והטבות לעסקים.',
  club_join:'📲 הצטרפות בוואטסאפ',club_have:'🔑 יש לי קוד סיטונאי',
  f_access:'הצהרת נגישות',left_only:'נותרו רק {n} במלאי!',
  tr_orig:'✔ מוצרים מקוריים בלבד',tr_eta:'🚚 אספקה עד 72 שעות',tr_wa:'💬 שירות אישי בוואטסאפ',
  wa_q:'יש שאלה? דברו איתנו בוואטסאפ',
  wa_help_title:'צריכים עזרה? כתבו לנו',wa_help_greet:'כתבו את ההודעה שלכם ונחזור אליכם מיד בוואטסאפ.',
  wa_help_ph:'ההודעה שלי…',wa_send:'שלח בוואטסאפ',wa_default:'שלום! יש לי שאלה על מוצר בקטלוג',
  brand_title:'בחירת מותג',brand_search:'חיפוש מותג…'},
 ar:{search_ph:'ابحث عن منتج، ماركة أو باركود…',fav_only:'المفضلة لديّ',in_stock:'متوفر',in_stock_short:'متوفر',reset_all:'مسح الكل',af_lbl:'مُصفّى حسب:',af_clear:'✕ مسح الكل وعرض الجميع',af_cat:'الفئة',af_brand:'الماركة',af_price:'السعر',af_fav:'المفضلة',af_stock:'المتوفر فقط',af_q:'بحث',cons_rec:'موصى للمستهلك:',
  sort_default:'الترتيب: موصى به',sort_pa:'السعر: من الأقل للأعلى',sort_pd:'السعر: من الأعلى للأقل',sort_name:'الاسم: أ–ي',
  all:'الكل',all_brands:'كل الماركات',all_prices:'كل الأسعار',
  p_u50:'حتى ₪50',p_50_100:'₪50–100',p_100_200:'₪100–200',p_200p:'₪200+',
  items:'منتج',cart_items:'عناصر',empty:'لم يتم العثور على منتجات مطابقة 🔍',
  view_order:'عرض الطلب ←',totop:'العودة للأعلى',
  c_איפור:'مكياج',c_טיפוח:'العناية بالبشرة',c_שיער:'العناية بالشعر',c_בושם:'عطر',c_מארזים:'مجموعات',c_ציפורניים:'العناية بالأظافر',c_אביזרים:'إكسسوارات',c_ציוד:'معدات',c_אחר:'أخرى',
  cat_hot:'الأكثر مبيعًا',
  go_to_product:'عرض في الكتالوج',clear_cart:'إفراغ السلة',clear_cart_ask:'إزالة كل الـ{n} منتجات من السلة؟',
  b_sale:'تخفيض',b_new:'جديد',b_bestseller:'الأكثر مبيعاً',b_soldout:'نفد',b_limited:'إصدار محدود',b_vegan:'نباتي',
  shades:'ألوان',feats:'أبرز المزايا',ingredients:'المكوّنات',usage:'طريقة الاستخدام',contents_h:'ما الذي تشمله التشكيلة',
  pick_shade:'اختر اللون',similar:'منتجات مشابهة',desc:'الوصف',barcode:'باركود:',
  add_order:'أضف إلى الطلب',fav_remove:'في المفضلة — إزالة',fav_add:'أضف إلى المفضلة',
  my_order:'طلبي',coupon_ph:'رمز الكوبون',apply:'تطبيق',buyer_details:'تفاصيل مقدّم الطلب',
  full_name:'الاسم الكامل *',biz_name:'اسم العمل / المتجر (للفاتورة)',biz_id:'رقم السجل التجاري / الهوية',
  ship_addr:'المدينة والعنوان للتوصيل',phone:'الهاتف *',notes_ph:'ملاحظات على الطلب (اختياري)…',
  email_ph:'البريد الإلكتروني — لاستلام التأكيد والفاتورة (إلزامي للدفع في الموقع)',alert_email:'للدفع في الموقع يلزم بريد إلكتروني — سنرسل إليه التأكيد والفاتورة.',
  l_name:'الاسم الكامل',l_phone:'رقم الجوال',l_city:'البلدة',l_street:'الشارع',l_house:'رقم البيت',
  l_apt:'شقة',l_floor:'طابق',l_entrance:'مدخل',l_email:'البريد الإلكتروني',l_id:'رقم المصلحة / ح.ب / هوية',l_notes:'ملاحظات للمندوب',
  l_opt:'(اختياري)',phone_hint:'لتنسيق التسليم مع المندوب',
  bldg_show:'+ شقة، طابق، مدخل',bldg_hide:'− إخفاء تفاصيل المبنى',
  city_ph:'اكتب اسم البلدة…',street_ph:'اكتب اسم الشارع…',street_free:'الشارع أو وصف العنوان',
  no_streets:'لا توجد قائمة شوارع لهذه البلدة — يرجى كتابة العنوان الكامل',
  city_first:'اختر البلدة أولاً',no_match:'لا توجد نتيجة — يمكنك الكتابة بحرية',
  err_city:'يرجى تعبئة البلدة',err_street:'يرجى تعبئة الشارع أو العنوان',err_house:'يرجى تعبئة رقم البيت',
  err_phone:'رقم هاتف غير صالح — جوال 10 أرقام (05X) أو أرضي 9 أرقام',
  send_order:'إرسال الطلب للموافقة (واتساب)',send_hint:'سيُفتح الطلب في WhatsApp مع رقم الطلب',
  pay_now:'ادفع الآن 💳',sold_out:'نفد',sending:'جارٍ الإرسال…',err_order:'حدث خطأ في إنشاء الطلب. حاول مرة أخرى.',
  pay_ok:'تم استلام الدفع بنجاح! 🎉 تم تأكيد الطلب رقم {id} — تم إرسال تفاصيل التأكيد إليك. شكراً لتسوقك في بيوتي فيفوريتس!',
  pay_fail:'لم تكتمل عملية الدفع. طلبك ({id}) محفوظ لدينا — يمكنك المحاولة مرة أخرى أو التواصل معنا عبر واتساب 053-4555501.',
  cart_empty:'السلة فارغة',subtotal:'المجموع الفرعي',discount:'خصم',vat:'ضريبة 18%',grand:'الإجمالي للدفع',incl_vat:'الأسعار تشمل الضريبة',
  coupon_ok:'✓ تم تطبيق الكوبون: ',coupon_bad:'رمز كوبون غير صالح',off:'خصم',
  ws_enter:'🔑 دخول الجملة',ws_exit:'الخروج من وضع الجملة',ws_title:'دخول الجملة',ws_sub:'أدخل رمز الجملة لرؤية أسعار الجملة.',ws_ph:'رمز الجملة',ws_go:'دخول',ws_bad:'رمز غير صحيح',ws_unavailable:'غير متاح حالياً',ws_active:'وضع الجملة مُفعّل — تُعرض أسعار الجملة',
  alert_empty:'السلة فارغة',alert_fill:'يرجى تعبئة الاسم الكامل والهاتف قبل إرسال الطلب',other:'עברית',
  alert_terms:'يجب الموافقة على شروط الاستخدام وسياسة الخصوصية قبل إرسال الطلب',
  agree_txt:'قرأت وأوافق على <a href="#" onclick="openPolicy(\'terms\');return false">شروط الاستخدام</a> و<a href="#" onclick="openPolicy(\'privacy\');return false">سياسة الخصوصية</a>',
  f_about:'حول المتجر',
  found_in:'موجود في:',
  brands_n:'علامات تجارية', show_n:'عرض {n} منتجات', bm_close:'إغلاق', filter:'تصفية', f_clear:'مسح التصفية',
  fb_lbl:'تصفية موصى بها', fd_sort:'الترتيب', sort_rec:'موصى به', fd_sub:'الفئة الفرعية', fd_brand:'الماركة', fd_price:'السعر', fd_misc:'المزيد', fd_bq:'ابحث عن ماركة…', fd_more:'{n} ماركات أخرى', fd_less:'عرض أقل',
  cat_sec:'الفئات',
  dh_h1a:'كل المنتجات المرغوبة',dh_h1b:'من عالم الجمال في مكان واحد',
  dh_sub:'منتجات أصلية من أبرز الماركات العالمية، مختارة خصيصًا لكِ',dh_cta:'إلى توصياتنا',
  f_disc:'بيع مستقل لمنتجات أصلية · جميع العلامات التجارية ملك لأصحابها',
  hero_sub:'التشكيلة المختارة — مكياج · عناية · شعر · عطر',
  ebtn:'إلى توصياتنا',
  svc1a:'شحن مجاني', svc1b:'للطلبات فوق ₪299', svc2a:'إرجاع مجاني', svc2b:'حتى 30 يوم', svc3a:'منتجات أصلية', svc3b:'أصلية 100%', svc4a:'دفع آمن', svc4b:'تشفير كامل',
  pt1h:'ماركات العناية المفضّلة', pt2h:'عطور أصلية', pt2p:'من أشهر دور الأزياء', buy:'للشراء',
  br_title:'الماركات المفضّلة', br_more:'كل الماركات ›', rec_title:'موصى به لك', rec_more:'كل المنتجات ›', shop_all:'كل المنتجات',
  nv_home:'الرئيسية', nv_search:'بحث', nv_fav:'المفضلة', nv_cart:'السلة', nv_wa:'واتساب',
  f_biz:'تفاصيل العمل',f_contact:'اتصلوا بنا',f_vat:'الأسعار تشمل الضريبة · توصيل لكل البلاد',f_info:'معلومات وسياسات',
  f_ship:'الشحن والتوصيل',f_ret:'الإرجاع والإلغاء',f_terms:'شروط الاستخدام',f_priv:'سياسة الخصوصية',
  f_order:'الطلبات',f_free:'توصيل مجاني للطلبات فوق ₪299',f_eta:'التوصيل خلال 72 ساعة من استلام المندوب للطرد',f_wa:'اطلب عبر واتساب',
  pb_ship:'الشحن',pb_ret:'الإرجاع',pb_priv:'الخصوصية',
  promo_orig:'✔ منتجات أصلية فقط',
  promo_free:'🚚 توصيل مجاني فوق ₪299',promo_coupon:'🎁 خصم 10% مع كوبون BEAUTY10',promo_eta:'⏱ التوصيل خلال 72 ساعة',
  club_link:'💼 نادي الأعمال',club_footer:'💼 نادي الأعمال — أسعار الجملة',club_title:'💼 نادي الأعمال',
  club_sub:'صالون، خبيرة مكياج أو متجر؟ انضموا إلى نادي الأعمال لدينا واحصلوا على أسعار جملة خاصة وخدمة شخصية ومزايا للأعمال.',
  club_join:'📲 الانضمام عبر واتساب',club_have:'🔑 لديّ رمز جملة',
  f_access:'إعلان إمكانية الوصول',left_only:'بقي {n} فقط في المخزون!',
  tr_orig:'✔ منتجات أصلية فقط',tr_eta:'🚚 التوصيل خلال 72 ساعة',tr_wa:'💬 خدمة شخصية عبر واتساب',
  wa_q:'لديك سؤال؟ تواصلوا معنا عبر واتساب',
  wa_help_title:'تحتاجون مساعدة؟ اكتبوا لنا',wa_help_greet:'اكتبوا رسالتكم وسنعود إليكم فوراً عبر واتساب.',
  wa_help_ph:'رسالتي…',wa_send:'إرسال عبر واتساب',wa_default:'مرحباً! لديّ سؤال عن منتج في الكتالوج',
  brand_title:'اختيار الماركة',brand_search:'ابحث عن ماركة…'}
};
let LANG=localStorage.getItem('sf_lang')||'he';
function t(k){return (I18N[LANG]&&I18N[LANG][k]!=null)?I18N[LANG][k]:(I18N.he[k]!=null?I18N.he[k]:k);}
function catLabel(c){
  if(CT_BY[c])return (LANG==='ar'&&CT_BY[c].ar)?CT_BY[c].ar:CT_BY[c].he;
  if(CT_SUB[c])return (LANG==='ar'&&CT_SUB[c].ar)?CT_SUB[c].ar:CT_SUB[c].he;
  return t('c_'+c)||c;}
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
  // תוויות אמיתיות: הטקסט מוחלף בתווית ולא ב-placeholder
  [['lb-name','l_name',0],['lb-phone','l_phone',0],['lb-city','l_city',0],['lb-street','l_street',0],
   ['lb-house','l_house',0],['lb-apt','l_apt',1],['lb-floor','l_floor',1],['lb-entrance','l_entrance',1],
   ['lb-email','l_email',1],['lb-id','l_id',1],['lb-notes','l_notes',1]].forEach(function(x){
    var e=document.getElementById(x[0]); if(!e)return;
    e.innerHTML=esc(t(x[1]))+(x[2]?' <span class="opt">'+esc(t('l_opt'))+'</span>':'');
  });
  var _cc=document.getElementById('clearCartBtn'); if(_cc)_cc.textContent='🗑️ '+t('clear_cart');
  setText('hint-phone',t('phone_hint'));setText('hint-email',t('email_ph'));
  var _bt=document.getElementById('bldgToggle');
  if(_bt)_bt.textContent=(document.getElementById('bldgRow').style.display==='none')?t('bldg_show'):t('bldg_hide');
  setPh('buyer-city',t('city_ph'));setPh('notes',t('notes_ph'));
  // שם היישוב שנבחר מתורגם יחד עם השפה
  if(CITY){var _ci=document.getElementById('buyer-city');if(_ci)_ci.value=cityLabel(CITY);}
  updateStreetMode();
  setText('sendBtn',t('send_order'));setText('sendHint',t('send_hint'));setText('payBtn',t('pay_now'));
  var _ag=document.getElementById('agreeTxt');if(_ag)_ag.innerHTML=t('agree_txt');
  setText('heroSub',t('hero_sub'));
  setText('fDisc',t('f_disc'));setText('fBizT',t('f_biz'));setText('fVat',t('f_vat'));setText('fInfoT',t('f_info'));
  setText('fAbout',t('f_about'));setText('fShip',t('f_ship'));setText('fRet',t('f_ret'));setText('fTerms',t('f_terms'));setText('fPriv',t('f_priv'));
  setText('fOrderT',t('f_order'));setText('fShipFree',t('f_free'));setText('fEta',t('f_eta'));setText('fWa',t('f_wa'));
  setText('pbAbout',t('f_about'));setText('pbBiz',t('f_contact'));setText('pbShip',t('pb_ship'));setText('pbRet',t('pb_ret'));setText('pbTerms',t('f_terms'));setText('pbPriv',t('pb_priv'));
  setText('wsTitle',t('ws_title'));setText('wsSub',t('ws_sub'));setPh('wsCode',t('ws_ph'));setText('wsGo',t('ws_go'));setText('wsBannerTxt',t('ws_active'));
  setText('brandModalTitle',t('brand_title'));setText('filterTitle',t('filter'));if(typeof updateFilterBtn==='function')updateFilterBtn();setPh('brandSearch',t('brand_search'));if(typeof updateBrandBtn==='function')updateBrandBtn();
  setText('promo0',t('promo_orig'));setText('promo1',t('promo_free'));setText('promo3',t('promo_eta'));
  setText('tr1',t('tr_orig'));setText('tr2',t('tr_eta'));setText('tr3',t('tr_wa'));
  setText('clubTitle',t('club_title'));setText('clubSub',t('club_sub'));setText('clubJoin',t('club_join'));setText('clubHave',t('club_have'));
  setText('fAccess',t('f_access'));setText('fClub',t('club_footer'));
  var wf=document.getElementById('waFloat');if(wf){wf.title=t('wa_q');wf.setAttribute('aria-label',t('wa_q'));}
  setText('waChatTitle',t('wa_help_title'));setText('waChatGreet',t('wa_help_greet'));setPh('waChatMsg',t('wa_help_ph'));setText('waChatSend',t('wa_send'));
  // homepage sections (Sephora-style)
  setText('ebtnD',t('ebtn'));setText('ebtnM',t('ebtn'));
  setText('svc1a',t('svc1a'));setText('svc1b',t('svc1b'));setText('svc2a',t('svc2a'));setText('svc2b',t('svc2b'));
  setText('svc3a',t('svc3a'));setText('svc3b',t('svc3b'));setText('svc4a',t('svc4a'));setText('svc4b',t('svc4b'));
  setText('pt1h',t('pt1h'));setText('pt2h',t('pt2h'));setText('pt2p',t('pt2p'));
  var _pb=document.querySelectorAll('.ptile .cta');for(var _i=0;_i<_pb.length;_i++)_pb[_i].textContent=t('buy');
  setText('brTitle',t('br_title'));setText('brMore',t('br_more'));setText('recTitle',t('rec_title'));setText('recMore',t('rec_more'));setText('shopAllT',t('shop_all'));
  setText('nvHome',t('nv_home'));setText('nvSearch',t('nv_search'));setText('nvFav',t('nv_fav'));setText('nvCart',t('nv_cart'));setText('nvWa',t('nv_wa'));
  updateWsUI();
  var lb=document.getElementById('langBtn');if(lb)lb.textContent=t('other');
  setText('fdTitle',t('filter'));setText('fbLbl',t('fb_lbl'));setText('fdClear',t('reset_all'));
  setText('dhH1a',t('dh_h1a'));setText('dhH1b',t('dh_h1b'));setText('dhSub',t('dh_sub'));setText('dhCta',t('dh_cta'));
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

// 🗂️ מפות העץ. CT_MAIN: slug של תת-קטגוריה → מפתח הקבוצה.
const CT_BY={},CT_MAIN={},CT_SUB={};
for(const _g of CATTREE){CT_BY[_g.m]=_g;for(const _s of _g.subs){CT_MAIN[_s.s]=_g.m;CT_SUB[_s.s]=_s;}}
const HAS_TREE=CATTREE.length>0;
function gMain(g){return CT_MAIN[g.cs||'']||'';}
// 🔁 השכבה הישנה נשארת כנפילה לאחור: אם העץ לא נשלף בבנייה (אין רשת),
//    הניווט חוזר לקטגוריות השטוחות ושום דבר לא נעלם מהאתר.
const CATS=['איפור','טיפוח','שיער','בושם','מארזים','ציפורניים','אביזרים','ציוד'].filter(t=>GROUPS.some(g=>g.type===t));
// תמונת קטגוריה ייעודית (נחתכה מהקולאז' של דף הכניסה); קטגוריה ללא תמונה כאן → נפילה לתמונת מוצר מייצג
const CAT_IMG={'איפור':'cat/makeup.jpg?v=2','טיפוח':'cat/skincare.jpg?v=2','שיער':'cat/hair.jpg?v=2','בושם':'cat/fragrance.jpg?v=2','מארזים':'cat/sets.jpg?v=2','אביזרים':'cat/accessories.jpg?v=2'};
// "לוהטים" — מוצרי הזמנה 1010 (רשימה נבחרת): קטגוריה וירטואלית + מקור לקרוסלת "מומלץ בשבילך"
const HOT_SKUS=new Set(['3548752203166','3548752227018','3548752215862','194251146065','607845058946','5056446616171','5060332320264','5060696179447','5056446655385','850018802888','602004162984','602004106643','602004140128','602004127068','602004111807','651986023424','651986009459','810912032613','810912034150','810912032576','843628141126','840026678681','840026678278','840122909801','840122900044','840122906664','840122906619','840122906442','840122906572','8720986613484','810052962818','810052960012','858511001128','609332859128','609332832572','609332830486','609332834040','609332834149','609332828056','609332859753','609332570658','609332848023','609332813465','609332847590','609332852457','609332216433']);
function isHot(g){return g.variants.some(v=>HOT_SKUS.has(nbc(v.barcode)));}
// קטגוריות להצגה: רק כאלה עם מוצר במלאי (עד שהמלאי נטען — כולן)
function catsInStock(){
  if(HAS_TREE){
    const keys=CATTREE.map(x=>x.m);
    if(!STOCK_READY)return keys.filter(m=>GROUPS.some(g=>gMain(g)===m));
    return keys.filter(m=>GROUPS.some(g=>gMain(g)===m&&g.variants.some(inDB)));
  }
  if(!STOCK_READY)return CATS;
  return CATS.filter(c=>GROUPS.some(g=>g.type===c&&g.variants.some(inDB)));
}
// תתי-הקטגוריות של הקבוצה שנבחרה — **רק כאלה שיש בהן מוצר**, כדי שלקוחה
// לא תיכנס למסך ריק. מאז שהוסרו המספרים זה הדבר היחיד שמונע את זה.
function subsInStock(m){
  const g=CT_BY[m];if(!g)return [];
  return g.subs.filter(sb=>GROUPS.some(x=>x.cs===sb.s&&(!STOCK_READY||x.variants.some(inDB))));
}
const BRANDS=(()=>{const c={};GROUPS.forEach(g=>c[g.brand]=(c[g.brand]||0)+1);
  return Object.keys(c).sort((a,b)=>a==='אחר'?1:b==='אחר'?-1:c[b]-c[a]);})();
// מותגים להצגה: רק כאלה עם מוצר במלאי (עד שהמלאי נטען — כולם)
function inCatScope(g){
  if(curCat==='__hot__')return isHot(g);
  if(curCat==='__all__')return true;
  if(HAS_TREE&&CT_BY[curCat]){
    if(gMain(g)!==curCat)return false;
    return curSub==='__all__'||g.cs===curSub;
  }
  return g.type===curCat;
}
function brandsInStock(){
  const inStock=g=>!STOCK_READY||g.variants.some(inDB);
  return BRANDS.filter(b=>GROUPS.some(g=>g.brand===b&&inCatScope(g)&&inStock(g)));
}
const PRICES=[{l:'עד ₪50',mn:0,mx:50},{l:'₪50–100',mn:50,mx:100},{l:'₪100–200',mn:100,mx:200},{l:'₪200+',mn:200,mx:1e9}];

let curCat='__all__',curSub='__all__',curPrice=-1,favOnly=false,inStockOnly=false;
// 🏷️ 06/10/2026 — כמה מותגים בבת אחת (נמרוד). ריק = כל המותגים.
const BSEL=new Set();
// 🎛️ 07/10/2026 — סינון לפי תכונות, בסדר של הרשימות של טל:
//    סוג → רמת כיסוי → גימור → סוג עור → גוון → תכונות נוספות.
//    בתוך מקטע "או", בין מקטעים "וגם". מוצר שאין לו ערך במקטע שנבחר — לא מוצג:
//    לא מנחשים שהוא מתאים (שדה ריק עדיף על ניחוש, גם בסינון).
const ATTR_SEC=[
  {k:'st',he:'סוג',ar:'النوع'},
  {k:'coverage',he:'רמת כיסוי',ar:'درجة التغطية'},
  {k:'finish',he:'גימור',ar:'اللمسة النهائية'},
  {k:'skin',he:'סוג עור',ar:'نوع البشرة'},
  {k:'tone',he:'גוון',ar:'اللون'},
  {k:'extra',he:'תכונות נוספות',ar:'مزايا إضافية'}];
const ATTR_KEYS=new Set(ATTR_SEC.map(d=>d.k));
const ATTR_ORDER={st:['נוזלי','קרם','מוס','ג׳לי','טינט','סטיק','דחוסה/אבקה','דחוסה','בתפזורת','פלטה','עיפרון'],
  coverage:['קל','בינוני','מלא','ניתן לבנייה'],finish:['מאט','טבעי','סאטן','זוהר','שימרי','מטאלי'],
  skin:['יבש','שמן','מעורב','רגיש'],tone:['שקופה','בגוון'],extra:['עמיד למים','ארוך טווח','טבעוני','ללא אכזריות']};
// הערכים נשמרים במסד כפי שהמחקר חילץ אותם; כאן רק התווית ללקוחה
const ATTR_HE={'סאטן':'סאטני','זוהר':'זוהר / גלואי','ארוך טווח':'עמיד לאורך זמן','עמיד למים':'עמיד במים','דחוסה/אבקה':'אבקה'};
const ATTR_AR={'מאט':'مطفي','טבעי':'طبيعي','סאטן':'ساتان','זוהר':'متوهج','שימרי':'لامع','מטאלי':'معدني',
  'קל':'خفيفة','בינוני':'متوسطة','מלא':'كاملة','ניתן לבנייה':'قابلة للبناء',
  'יבש':'جافة','שמן':'دهنية','מעורב':'مختلطة','רגיש':'حساسة','שקופה':'شفافة','בגוון':'ملوّنة',
  'עמיד למים':'مقاوم للماء','ארוך טווח':'يدوم طويلاً','טבעוני':'نباتي','ללא אכזריות':'خالٍ من القسوة',
  'נוזלי':'سائل','קרם':'كريمي','דחוסה/אבקה':'بودرة','דחוסה':'مضغوطة','בתפזורת':'سائبة','סטיק':'ستيك',
  'פלטה':'باليت','עיפרון':'قلم','טינט':'تينت','ג׳לי':'جل','מוס':'موس','עם גוון':'ملوّن','ללא גוון':'بدون لون',
  'נפח':'كثافة','הארכה':'تطويل','סלסול':'تجعيد','לגוף ולשיער':'للجسم والشعر','לגוף':'للجسم','לשיער':'للشعر',
  'אפרסק':'خوخي','ורוד':'وردي','מבהיר':'مُفتّح'};
const ST_SEC={'face-corrector':{he:'גוון מתקן',ar:'لون التصحيح'},'eyes-mascara':{he:'אפקט',ar:'التأثير'},
  'skin-mist':{he:'שימוש',ar:'الاستخدام'},'face-setting':{he:'גימור',ar:'اللمسة النهائية'},'lips-balm':{he:'גוון',ar:'اللون'}};
function secLbl(d){const o=(d.k==='st'&&ST_SEC[curSub])||d;return LANG==='ar'?o.ar:o.he;}
function attrLbl(v){return (LANG==='ar'&&ATTR_AR[v])?ATTR_AR[v]:(ATTR_HE[v]||v);}
const FSEL={};   // k -> Set של ערכים שנבחרו
function gAttr(g,k){
  if(k==='st')return g.sts||(g.st?[g.st]:[]);   // כל הסוגים של הגוונים — לא רק הרוב
  const a=g.at||{};
  if(k==='extra')return (a.wear||[]).concat(a.ethics||[]);
  return a[k]||[];
}
function fselCount(){let n=0;for(const k in FSEL)n+=FSEL[k].size;return n;}
const sel={};   // gid -> variant index
const FAVS=new Set(JSON.parse(localStorage.getItem('sf_favs')||'[]'));
function saveFavs(){localStorage.setItem('sf_favs',JSON.stringify([...FAVS]))}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function aesc(s){return String(s).replace(/"/g,'&quot;')}
function imgErr(img){img.style.display='none';const ph=document.createElement('div');ph.className='ph';ph.textContent=img.dataset.l||'✦';img.parentNode.appendChild(ph)}
// default displayed variant = first IN-STOCK shade (so the card never defaults to a sold-out shade)
function defaultV(g){
  if(STOCK_READY){
    var f=g.variants.findIndex(function(v){return STOCK[nbc(v.barcode)]>0&&!isSold(v);});
    if(f>=0)return f;
    var d=g.variants.findIndex(inDB);
    if(d>=0)return d;
  }
  return 0;
}
function curIdx(g){var s=sel[g.gid];return s!=null?s:defaultV(g);}
function selV(g){return g.variants[curIdx(g)];}
function swPill(v,on,oc){
  var _sh=(LANG==='ar'&&v.shade_ar)?v.shade_ar:v.shade;
  var so=isSold(v), oc2=so?'out':'', tip=aesc(_sh)+(so?' — '+t('sold_out'):'');
  if(v.color)return `<button class="sw ${on?'on':''} ${oc2}" style="background:${v.color}" title="${tip}" aria-label="${tip}" onclick="event.stopPropagation();${oc}"></button>`;
  return `<button class="sw txt ${on?'on':''} ${oc2}" title="${tip}" onclick="event.stopPropagation();${oc}">${esc(_sh)}</button>`;
}

// ===== nav (rebuildable for language switch) =====
const PRICE_KEYS=['p_u50','p_50_100','p_100_200','p_200p'];
function buildNav(){
  const cats=catsInStock();
  if(curCat!=='__all__'&&curCat!=='__hot__'&&!cats.includes(curCat))curCat='__all__';   // קטגוריה שנבחרה אזלה → חזרה להכל (אריחי הקטגוריות הם הניווט היחיד)

  const brands=brandsInStock();
  for(const b of [...BSEL])if(!brands.includes(b))BSEL.delete(b);   // מותג שאין לו מלאי בתחום → יוצא מהבחירה
  updateBrandBtn();
  pruneAttrs();updateFilterBtn();

  buildCatTiles();
  buildBrandRow();
  buildRecs();
}
// ---- ניווט עמוד-הבית: קטגוריה/חנות/חיפוש/מועדפים ----
function goShop(){var el=document.getElementById('cathead');if(!el||!el.innerHTML)el=document.getElementById('shopAllT')||document.getElementById('grid');if(el){var y=el.getBoundingClientRect().top+(window.pageYOffset||document.documentElement.scrollTop||0)-70;window.scrollTo({top:y,behavior:'smooth'});}}
function buildSubRow(){
  const el=document.getElementById('subrow');if(!el)return;
  const subs=(HAS_TREE&&CT_BY[curCat])?subsInStock(curCat):[];
  if(!subs.length){el.innerHTML='';return;}
  const g=CT_BY[curCat]||{bg:'#f3eae1',ink:'#6f523c'};
  const chip=(key,label)=>{const on=curSub===key;
    return `<button class="subchip${on?' active':''}" data-s="${aesc(esc(key))}" style="`
      +(on?`background:${g.ink};border-color:${g.ink};color:#fff`
          :`background:${g.bg};border-color:transparent;color:${g.ink}`)+`">${esc(label)}</button>`;};
  el.innerHTML=chip('__all__',t('all'))
    +subs.map(sb=>chip(sb.s,(LANG==='ar'&&sb.ar)?sb.ar:sb.he)).join('');
  el.onclick=e=>{const b=e.target.closest('[data-s]');if(!b)return;goSub(b.dataset.s);};
}
// 🏷️ פס הכותרת. מופיע רק כשיש קבוצה נבחרת — ובחיפוש מוצג במקומו
//    "נמצא ב:", שמראה ללקוחה **באילו קטגוריות** נפלו התוצאות שלה.
function buildCatHead(){
  const el=document.getElementById('cathead'); if(!el)return;
  const q=(document.getElementById('q')||{}).value||'';
  if(q.trim()){ el.innerHTML=foundInHtml(); return; }
  const g=HAS_TREE?CT_BY[curCat]:null;
  var sa=document.querySelector('.shopall');if(sa)sa.style.display=g?'none':'';
  if(!g){el.innerHTML='';return;}
  const sub=(curSub!=='__all__'&&CT_SUB[curSub])?CT_SUB[curSub]:null;
  const he=sub?((LANG==='ar'&&sub.ar)?sub.ar:sub.he):((LANG==='ar'&&g.ar)?g.ar:g.he);
  const ar=sub?sub.ar:g.ar;
  el.innerHTML='<div class="inner" style="background:'+g.bg+';color:'+g.ink+'">'
    +'<svg viewBox="0 0 48 48" style="stroke:'+g.ink+';color:'+g.ink+'">'+g.ic+'</svg>'
    +'<div><h2>'+esc(he)+'</h2>'+((ar&&LANG!=='ar')?'<div class="ar">'+esc(ar)+'</div>':'')+'</div></div>';
}
// 🔎 "נמצא ב:" — שלוש הקטגוריות שבהן יש הכי הרבה תוצאות לחיפוש.
//    זה מה שהופך חיפוש כושל ("גלוס") למסלול: הלקוחה רואה שהתוצאות
//    יושבות ב"גלוסים" ולוחצת ישר לשם.
function foundInHtml(){
  if(!HAS_TREE||!VIS||!VIS.length)return '';
  const by={};
  for(const g of VIS){if(g.cs)by[g.cs]=(by[g.cs]||0)+1;}
  const top=Object.keys(by).sort((a,b)=>by[b]-by[a]).slice(0,3);
  if(!top.length)return '';
  return '<div class="found">'+esc(t('found_in'))+' '
    +top.map(sl=>'<b class="fin" style="cursor:pointer" data-m="'+aesc(esc(CT_MAIN[sl]))+'" data-s="'+aesc(esc(sl))+'">'
      +esc(catLabel(sl))+'</b>').join(' · ')+'</div>';
}
function goSub(sl){curSub=sl;writeHash();buildNav();render();goShop();}
// 🛡️ "נמצא ב:" — מאזין אחד, והערכים מאומתים מול העץ לפני שימוש (לא מחרוזת JS מהמסד)
document.addEventListener('click',function(e){
  const b=e.target.closest&&e.target.closest('#cathead .fin'); if(!b)return;
  const m=b.dataset.m, sl=b.dataset.s;
  if(!CT_BY[m]||CT_MAIN[sl]!==m)return;
  goCat(m); goSub(sl);
});
// 🔗 קישור עמוק: #c=<קבוצה>&s=<תת-קטגוריה>. נכתב לכתובת בלי לרענן,
//    כך ש"שלח לי את הסומקים" הוא קישור אחד שנפתח ישר במקום הנכון.
function writeHash(){
  try{
    let h='';
    if(HAS_TREE&&CT_BY[curCat]){h='#c='+curCat;if(curSub!=='__all__')h+='&s='+curSub;}
    history.replaceState(history.state,'',h||location.pathname+location.search);
  }catch(e){}
}
function applyHash(){
  if(!HAS_TREE)return false;
  const p=new URLSearchParams((location.hash||'').replace(/^#/,''));
  const c=p.get('c'), sb=p.get('s');
  if(!c||!CT_BY[c])return false;
  curCat=c; curSub=(sb&&CT_SUB[sb]&&CT_MAIN[sb]===c)?sb:'__all__';
  return true;
}
function clearSearchQ(){var fq=document.getElementById('fdQ');if(fq)fq.value='';var q=document.getElementById('q');if(q&&q.value){q.value='';var ac=document.getElementById('ac');if(ac)ac.classList.remove('show');if(typeof toggleClr==='function')toggleClr();}}
function goCat(c){clearSearchQ();curSub='__all__';curCat=c;BSEL.clear();for(const k in FSEL)delete FSEL[k];favOnly=false;var fc=document.getElementById('favchip');if(fc)fc.classList.remove('active');writeHash();buildNav();render();goShop();}
// כפתור "חיפוש" בסרגל התחתון → נוחתים בדיוק על שדה החיפוש והמקלדת נפתחת.
// ⚠️ הנקודה הקריטית: focus() חייב לרוץ **בתוך אירוע הלחיצה עצמו**. הגרסה
// הקודמת קראה לו מתוך setTimeout של 360 מ"ש, וסאפארי בנייד מתייחס לזה
// כאל פוקוס שלא מגיע ממחוות משתמש — ולכן המקלדת פשוט לא נפתחה.
// שורת החיפוש דביקה ל-top:0, ולכן כשכבר גללנו מעבר למקומה הטבעי היא
// ממילא על המסך ואין לאן לגלול; גוללים רק כשהיא עוד מתחת לקפל.
function focusSearch(){
  var q=document.getElementById('q'); if(!q)return;
  q.focus({preventScroll:true});
  if(q.value)q.select();            // חזרה לחיפוש → הקלדה מחליפה את הקודם
  var wrap=document.querySelector('.search-wrap');
  if(wrap){
    var cur=window.pageYOffset||document.documentElement.scrollTop||0;
    var y=wrap.getBoundingClientRect().top+cur;   // כשהיא "נדבקה" זה שווה ל-cur
    if(cur<y-1)window.scrollTo({top:y,behavior:'smooth'});
  }
}
// כפתור הבאנר → מסנן בפועל למומלצים ומגלגל לרשת המסוננת.
// נופל חזרה לגלילה אל קרוסלת "מומלץ בשבילך" אם אין מומלצים זמינים, ומשם לכל המוצרים.
function goRecs(){
  var hasHot=GROUPS.some(function(g){return isHot(g)&&(!STOCK_READY||g.variants.some(function(v){return STOCK[nbc(v.barcode)]>0;}));});
  if(hasHot){goCat('__hot__');return;}
  var row=document.getElementById('recRow'),el=document.getElementById('recTitle');
  if(!el||!row||!row.children.length){goShop();return;}
  var y=el.getBoundingClientRect().top+(window.pageYOffset||document.documentElement.scrollTop||0)-70;
  window.scrollTo({top:y,behavior:'smooth'});}
function showFavs(){favOnly=true;var fc=document.getElementById('favchip');if(fc)fc.classList.add('active');render();goShop();}
// ---- שורת לוגואי מותגים ----
function buildBrandRow(){
  var el=document.getElementById('brandRow');if(!el)return;
  // שורת הלוגואים היא שטח פרסום — מותג שכל מוצריו אזלו לא מקודם בה
  // (לעומת רשימת המותגים לסינון, שכן כוללת אותו כדי שהמוצרים יישארו נגישים)
  var bs=brandsInStock().filter(function(b){return brandLogo(b)&&GROUPS.some(function(g){
    return g.brand===b&&g.variants.some(function(v){return !STOCK_READY||STOCK[nbc(v.barcode)]>0;});});});
  bs.sort(function(a,b){return prestige(a)-prestige(b);});
  bs=bs.slice(0,12);
  el.innerHTML=bs.map(function(b){return '<img src="'+aesc(brandLogo(b))+'" alt="'+esc(b)+'" title="'+esc(b)+'" data-b="'+esc(b)+'" loading="lazy">';}).join('');
  el.onclick=function(e){var im=e.target.closest('[data-b]');if(!im)return;pickBrand(im.getAttribute('data-b'));goShop();};
}
// ---- קרוסלת "מומלץ בשבילך" ----
function buildRecs(){
  var el=document.getElementById('recRow');if(!el)return;
  function inStk(g){return !STOCK_READY||g.variants.some(function(v){return STOCK[nbc(v.barcode)]>0;});}
  // עדיפות ראשונה: מוצרי "לוהטים" (הזמנה 1010) במלאי ועם תמונה — מותגי יוקרה קודם
  var pick=GROUPS.filter(function(g){return !g._noimg&&isHot(g)&&inStk(g);})
    .sort(function(a,b){return prestige(a.brand)-prestige(b.brand)||a.brand.localeCompare(b.brand,'he');})
    .slice(0,12);
  if(pick.length<12){
    var pool=GROUPS.filter(function(g){return !g._noimg&&prestige(g.brand)<=2&&inStk(g)&&pick.indexOf(g)<0;});
    if(pool.length<6) pool=GROUPS.filter(function(g){return !g._noimg&&inStk(g)&&pick.indexOf(g)<0;});
    var step=Math.max(1,Math.floor(pool.length/12));
    for(var i=0;i<pool.length&&pick.length<12;i+=step) pick.push(pool[i]);
  }
  el.innerHTML=pick.map(function(g){
    var v=g.variants.find(function(x){return x.imgs&&x.imgs.length;})||g.variants[0];
    var img=(v&&v.imgs&&v.imgs.length)?'<img src="'+aesc(v.imgs[0])+'" loading="lazy" alt="">':'<span class="ph" style="font-size:34px">✦</span>';
    var pr=Math.min.apply(null,g.variants.map(eff));
    return '<div class="pcard" onclick="openPd('+g._i+')"><div class="pi">'+img+'</div><div class="pb"><div class="br">'+esc(g.brand)+'</div><div class="nm">'+esc(g.name_he)+'</div><div class="pr">₪'+pr+'</div></div></div>';
  }).join('');
}
// ---- אריחי קטגוריות עם תמונה מייצגת — ניווט הקטגוריות היחיד (כולל אריח "הכל") ----
function buildCatTiles(){
  const el=document.getElementById('cattiles');if(!el)return;
  const cats=catsInStock();
  const ICO_ALL='<rect x="8" y="8" width="14" height="14" rx="3"/><rect x="26" y="8" width="14" height="14" rx="3"/>'
               +'<rect x="8" y="26" width="14" height="14" rx="3"/><rect x="26" y="26" width="14" height="14" rx="3"/>';
  const ICO_HOT='<path d="M18 14c1 8.5 3 10.5 11.5 11.5C21 26.5 19 28.5 18 37c-1-8.5-3-10.5-11.5-11.5C15 24.5 17 22.5 18 14z"/>'
               +'<path d="M35 5c.6 4.2 1.8 5.4 6 6-4.2.6-5.4 1.8-6 6-.6-4.2-1.8-5.4-6-6 4.2-.6 5.4-1.8 6-6z"/>'
               +'<path d="M36 29c.4 3 1 3.6 4 4-3 .4-3.6 1-4 4-.4-3-1-3.6-4-4 3-.4 3.6-1 4-4z"/>';
  const tile=(key,ico,label,bg,ink)=>`<button class="cattile ${curCat===key?'active':''}" data-c="${aesc(esc(key))}" style="background:${bg}">`
    +`<span class="ci cticon"><svg viewBox="0 0 48 48" style="stroke:${ink};color:${ink}">${ico}</svg></span>`
    +`<span>${esc(label)}</span></button>`;
  const allTile=HAS_TREE?tile('__all__',ICO_ALL,t('all'),'#f3eae1','#6f523c')
    :`<button class="cattile ${curCat==='__all__'?'active':''}" data-c="__all__"><span class="ci"><img src="cat/all.jpg?v=2" loading="lazy" alt="" onerror="this.parentNode.classList.add('ci-all');this.outerHTML='<span class=&quot;ph&quot;>✦</span>'"></span><span>${t('all')}</span></button>`;
  const hg=GROUPS.filter(x=>isHot(x)&&!x._noimg&&(!STOCK_READY||x.variants.some(v=>STOCK[nbc(v.barcode)]>0)))
    .sort((a,b)=>prestige(a.brand)-prestige(b.brand))[0];
  const hv=hg?hg.variants.find(x=>x.imgs&&x.imgs.length):null;
  const hotIm=hv?`<img src="${aesc(hv.imgs[0])}" loading="lazy" alt="" onerror="this.style.display='none'">`:'<span class="ph">🔥</span>';
  const hotTile=!hg?'':(HAS_TREE?tile('__hot__',ICO_HOT,t('cat_hot'),'#f2e4d9','#a0664d')
    :`<button class="cattile ${curCat==='__hot__'?'active':''}" data-c="__hot__"><span class="ci">${hotIm}</span><span>${t('cat_hot')}</span></button>`);
  if(HAS_TREE){
    el.className='cattiles tree';
    const sec=document.getElementById('catsec'); if(sec)sec.textContent=t('cat_sec');
    el.innerHTML=allTile+hotTile+cats.map(m=>{
      const g=CT_BY[m];
      return tile(m,g.ic,catLabel(m),g.bg,g.ink);
    }).join('');
    el.onclick=e=>{const b=e.target.closest('[data-c]');if(!b)return;goCat(b.dataset.c);};
    buildSubRow();
    return;
  }
  el.innerHTML=allTile+hotTile+cats.map(c=>{
    let im;
    if(CAT_IMG[c]){
      im=`<img src="${CAT_IMG[c]}" loading="lazy" alt="" onerror="this.style.display='none'">`;
    }else{
      const g=GROUPS.filter(x=>x.type===c&&!x._noimg&&(!STOCK_READY||x.variants.some(v=>STOCK[nbc(v.barcode)]>0)))
        .sort((a,b)=>prestige(a.brand)-prestige(b.brand))[0];
      const v=g?g.variants.find(x=>x.imgs&&x.imgs.length):null;
      im=v?`<img src="${aesc(v.imgs[0])}" loading="lazy" alt="" onerror="this.style.display='none'">`:'<span class="ph">✦</span>';
    }
    return `<button class="cattile ${curCat===c?'active':''}" data-c="${c}"><span class="ci">${im}</span><span>${catLabel(c)}</span></button>`;
  }).join('');
  el.onclick=e=>{const b=e.target.closest('[data-c]');if(!b)return;goCat(b.dataset.c);};
}
// ---- קולאז' מוצרים צף בהירו (דסקטופ): תמונות מוצרים במלאי ממותגי יוקרה ----
function initHeroDeco(){
  const L=document.getElementById('heroDecoL'),R=document.getElementById('heroDecoR');if(!L||!R)return;
  const pool=GROUPS.filter(g=>!g._noimg&&prestige(g.brand)<=2&&(!STOCK_READY||g.variants.some(v=>STOCK[nbc(v.barcode)]>0)));
  const srcs=[];
  for(let i=0;i<6&&pool.length;i++){
    const g=pool[Math.floor(i*pool.length/6)];
    const v=g.variants.find(x=>x.imgs&&x.imgs.length);
    if(v&&!srcs.includes(v.imgs[0]))srcs.push(v.imgs[0]);
  }
  if(srcs.length<2){L.innerHTML='';R.innerHTML='';return;}
  const half=Math.ceil(srcs.length/2);
  const mk=(s,i)=>`<img src="${aesc(s)}" class="hd hd${i%3}" loading="lazy" alt="" onerror="this.remove()">`;
  L.innerHTML=srcs.slice(0,half).map(mk).join('');
  R.innerHTML=srcs.slice(half).map(mk).join('');
}
// ---- פס פרומו: במובייל מציג הודעה אחת מתחלפת ----
(function(){
  const ids=['promo0','promo1','promo3'];let pi=0;
  const e0=document.getElementById(ids[0]);if(e0)e0.classList.add('cur');
  setInterval(function(){
    if(window.innerWidth>640)return;
    pi=(pi+1)%ids.length;
    ids.forEach((id,k)=>{const e=document.getElementById(id);if(e)e.classList.toggle('cur',k===pi)});
  },3500);
})();

// ===== בורר מותגים (כפתור + חלון גדול) =====
// זוגות [קובץ-לוגו, [שמות-מותג]] — מפתח החיפוש מנורמל (normText) כדי לעמוד בהבדלי גרש/פיסוק בין DB לקטלוג.
const BRAND_LOGO_PAIRS=[
  ["brand-logos/sephora.svg",["ספורה","ספורה קולקשן"]],
  ["brand-logos/nyx.jpg",["NYX"]],
  ["brand-logos/loreal.svg",["לוריאל","לוריאל פריז","לוריאל פריס"]],
  ["brand-logos/laura-mercier.png",["לורה מרסייה"]],
  ["brand-logos/kiehls.svg",["קילס","קיהל'ס"]],
  ["brand-logos/airspun.png",["איירספן"]],
  ["brand-logos/haus-labs.svg",["האוס לאבס ביי ליידי גאגא","האוס לאבס"]],
  ["brand-logos/made-by-mitchell.png",["מייד ביי מיטשל"]],
  ["brand-logos/sabrina-carpenter.svg",["סברינה קרפנטר"]],
  ["brand-logos/elf.png",["אי.אל.אף"]],
  ["brand-logos/rare-beauty.svg",["ריר ביוטי"]],
  ["brand-logos/patrick-ta.png",["פטריק טא"]],
  ["brand-logos/milk-makeup.png",["מילק מייקאפ"]],
  ["brand-logos/tatcha.svg",["טאצ'ה"]],
  ["brand-logos/glow-recipe.png",["Glow Recipe"]],
  ["brand-logos/kosas.png",["קוסאס"]],
  ["brand-logos/k18.png",["K18"]],
  ["brand-logos/danessa-myricks.png",["דנסה מיריקס"]],
  ["brand-logos/the-ordinary.png",["The Ordinary"]],
  ["brand-logos/milani.png",["מילאני"]],
  ["brand-logos/rhode.svg",["Rhode"]],
  ["brand-logos/smashbox.webp",["סמאשבוקס"]],
  ["brand-logos/it-cosmetics.webp",["איט קוסמטיקס"]],
  ["brand-logos/olaplex.webp",["אולפלקס"]],
  ["brand-logos/drunk-elephant.webp",["דראנק אלפנט"]],
  ["brand-logos/gisou.webp",["Gisou"]],
  ["brand-logos/mugler.webp",["Mugler"]],
  ["brand-logos/rem-beauty.webp",["ר.אי.אם ביוטי","R.E.M."]],
  ["brand-logos/fenty.png",["פנטי ביוטי"]],
  ["brand-logos/benefit.svg",["בנפיט"]],
  ["brand-logos/too-faced.png",["טו פייסד"]],
  ["brand-logos/anastasia.svg",["אנסטסיה בברלי הילס","אנסטסיה בוורלי הילס","אנסטסיה"]],
  ["brand-logos/charlotte-tilbury.svg",["שרלוט טילבורי"]],
  ["brand-logos/armani.svg",["ארמני"]],
  ["brand-logos/morphe.png",["מורפי","מורף"]],
  ["brand-logos/victorias-secret.svg",["ויקטוריה סיקרט"]],
  ["brand-logos/nars.png",["נארס"]],
  ["brand-logos/makeup-for-ever.png",["מייק אפ פור אבר"]],
  ["brand-logos/natasha-denona.png",["נטשה דנונה"]],
  ["brand-logos/sol-de-janeiro.png",["סול דה ז'נרו"]],
  ["brand-logos/bobbi-brown.png",["בובי בראון"]],
  ["brand-logos/clarins.svg",["קלרינס"]],
  ["brand-logos/ysl.svg",["ייב סן לורן"]],
  // נוספו 27/08 — לוגואים שאותרו למותגים שהיו בלי סמליל
  ["brand-logos/murad.svg",["מורד"]],
  ["brand-logos/beauty-creations.svg",["ביוטי קריאיישן"]],
  ["brand-logos/got2b.png",["גוט2בי"]],
  ["brand-logos/laline.svg",["ללין"]],
  ["brand-logos/color-wow.png",["קולור וואו","קלר וואו"]],
  ["brand-logos/kerastase.svg",["קרסטס"]],
  ["brand-logos/maybelline.svg",["מייבלין"]],
  ["brand-logos/huda-beauty.png",["הודה ביוטי"]],
  ["brand-logos/hourglass.svg",["האורגלאס","אוארגלאס"]],
  ["brand-logos/pixi.svg",["פיקסי"]],
  ["brand-logos/one-size.svg",["ONE/SIZE","וואן סייז"]],
  ["brand-logos/makeup-by-mario.png",["מייקאפ ביי מריו"]],
  ["brand-logos/kylie-cosmetics.svg",["קיילי קוסמטיקס"]],
  ["brand-logos/kayali.svg",["קייאלי","קאיאלי","KAYALI","Kayali"]],
  ["brand-logos/gucci.svg",["גוצ'י"]],
  ["brand-logos/peter-thomas-roth.svg",["פיטר תומאס רות'"]],
  ["brand-logos/p-louise.png",["פי לואיז"]],
  ["brand-logos/boy-smells.png",["בוי סמלס"]],
  // ספורה פייבוריטס אינה מותג נפרד עם סמליל משלה — משתמשת בסמליל ספורה
  ["brand-logos/sephora.svg",["ספורה","ספורה קולקשן","ספורה פייבוריטס"]],
  ["brand-logos/urban-decay.svg",["אורבן דקיי"]],
  ["brand-logos/dolce-gabbana.svg",["דולצ'ה וגבאנה"]],
  ["brand-logos/lancome.svg",["לנקום"]],
  ["brand-logos/dior.svg",["דיור"]],
  ["brand-logos/clinique.svg",["קליניק"]],
  ["brand-logos/kryolan.jpg",["Kryolan"]],
  ["brand-logos/laneige.jpg",["לנייג'"]]
];
const BRAND_LOGOS={};
BRAND_LOGO_PAIRS.forEach(function(p){p[1].forEach(function(n){BRAND_LOGOS[normText(n)]=p[0];});});
function brandLogo(b){return BRAND_LOGOS[normText(b)];}
function brandCount(b){return GROUPS.reduce((s,g)=>s+((g.brand===b&&inCatScope(g)&&(!STOCK_READY||g.variants.some(v=>STOCK[nbc(v.barcode)]>0)))?1:0),0);}
const BRANDS_EN=/*__BRANDS_EN__*/;
function brandEn(b){return BRANDS_EN[b]||'';}
// לכל מותג יש סמליל: קובץ לוגו כשקיים, ואחרת סמליל טיפוגרפי מהשם
// האנגלי. 24 מתוך 76 המותגים עדיין בלי קובץ לוגו, והכיתוב האנגלי
// שומר על מראה אחיד במקום אריח ריק. השם העברי מוצג תמיד מתחת.
function brandVisual(b){
  const lg=brandLogo(b);
  if(lg)return `<img class="blogo" src="${aesc(lg)}" alt="${aesc(b)}" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'bwm',textContent:this.alt}))">`;
  return `<span class="bwm">${esc(brandEn(b)||b)}</span>`;
}
function updateBrandBtn(){
  const lbl=document.getElementById('brandPickLbl'),btn=document.getElementById('brandPickBtn');if(!lbl||!btn)return;
  lbl.textContent=BSEL.size===0?t('all_brands'):(BSEL.size===1?[...BSEL][0]:(BSEL.size+' '+t('brands_n')));
  btn.classList.toggle('on',BSEL.size>0);
}
function openBrandModal(){const s=document.getElementById('brandSearch');if(s)s.value='';renderBrandGrid();updateBrandDone();openOv('brandModal');
  setTimeout(function(){if(s)s.focus();},60);}
function renderBrandGrid(){
  const grid=document.getElementById('brandGrid');if(!grid)return;
  const q=normText((document.getElementById('brandSearch')||{}).value||'');
  let brands=brandsInStock();
  if(q)brands=brands.filter(b=>normText(b).includes(q)||expandSearch(b).includes(q));
  const total=brandsInStock().length;
  const allCard=(!q)?`<div class="bcard allb ${BSEL.size===0?'on':''}" data-b="__all__"><span class="bwm">${t('all_brands')}</span><span class="bcount">${total}</span></div>`:'';
  grid.innerHTML=allCard+brands.map(b=>{
    return `<div class="bcard ${BSEL.has(b)?'on':''}" data-b="${aesc(b)}">${brandVisual(b)}<span class="bname">${esc(b)}</span><span class="bcount">${brandCount(b)}</span></div>`;}).join('');
  if(!brands.length)grid.innerHTML='<div class="bempty">'+t('empty')+'</div>';
  grid.onclick=e=>{const c=e.target.closest('[data-b]');if(!c)return;pickBrand(c.dataset.b);};
}
function pickBrand(b){
  if(b==='__all__'){BSEL.clear();closeOv('brandModal');}
  else if(BSEL.has(b))BSEL.delete(b); else BSEL.add(b);
  buildNav();render();renderBrandGrid();updateBrandDone();
}
// כפתור "הצגת N מוצרים" בתחתית החלון — הלקוחה רואה כמה יוצא לפני שהיא סוגרת
function updateBrandDone(){const b=document.getElementById('brandDone');if(!b)return;
  b.textContent=BSEL.size?(t('show_n').replace('{n}',VIS.length.toLocaleString())):t('bm_close');}

// 🎛️ המקטעים שיש בהם מה לבחור — **רק בתוך קבוצה** (נוזלי של סומק ונוזלי של מייקאפ
//    אינם אותו דבר), וה"סוג" רק בתוך תת-קטגוריה. ערך יחיד שמשותף לכל המוצרים — מוסתר.
function attrScope(){return GROUPS.filter(g=>inCatScope(g)&&(!STOCK_READY||g.variants.some(inDB))&&(!BSEL.size||BSEL.has(g.brand)));}
function attrSections(){
  if(!(HAS_TREE&&CT_BY[curCat]))return [];
  const sc=attrScope(); if(!sc.length)return [];
  const out=[];
  for(const d of ATTR_SEC){
    if(d.k==='st'&&curSub==='__all__')continue;
    const cnt={};
    for(const g of sc)for(const v of new Set(gAttr(g,d.k)))cnt[v]=(cnt[v]||0)+1;
    const opts=Object.keys(cnt);
    if(!opts.length||(opts.length===1&&cnt[opts[0]]===sc.length))continue;
    const ord=ATTR_ORDER[d.k]||[];
    opts.sort((a,b)=>{const ia=ord.indexOf(a),ib=ord.indexOf(b);return ((ia<0?99:ia)-(ib<0?99:ib))||(cnt[b]-cnt[a]);});
    out.push({d,opts});
  }
  return out;
}
// ערך שנבחר ואינו קיים יותר בתחום (החלפת תת-קטגוריה/מותג) — יוצא מהבחירה
function pruneAttrs(){
  const av={};for(const x of attrSections())av[x.d.k]=new Set(x.opts);
  for(const k in FSEL){for(const v of [...FSEL[k]])if(!(av[k]&&av[k].has(v)))FSEL[k].delete(v);if(!FSEL[k].size)delete FSEL[k];}
}
function updateFilterBtn(){
  const btn=document.getElementById('filterBtn'),lbl=document.getElementById('filterLbl');if(!btn||!lbl)return;
  const n=fselCount();
  btn.style.display=(n||attrSections().length)?'':'none';
  lbl.textContent=t('filter')+(n?' · '+n:'');
  btn.classList.toggle('on',n>0);
}
function openFilterModal(){renderFilterBody();updateFilterDone();openOv('filterModal');}
function renderFilterBody(){
  const el=document.getElementById('filterBody');if(!el)return;
  const g=CT_BY[curCat]||{bg:'#f3eae1',ink:'#6f523c'};
  el.innerHTML=attrSections().map(({d,opts})=>'<div class="fsec"><h4>'+esc(secLbl(d))+'</h4><div class="fopts">'
    +opts.map(v=>{const on=!!(FSEL[d.k]&&FSEL[d.k].has(v));
      return '<button type="button" class="fopt'+(on?' on':'')+'" data-k="'+aesc(esc(d.k))+'" data-v="'+aesc(esc(v))+'" style="'
        +(on?'background:'+g.ink+';color:#fff':'background:'+g.bg+';color:'+g.ink)+'">'+esc(attrLbl(v))+'</button>';}).join('')
    +'</div></div>').join('')
    +(fselCount()?'<button type="button" class="fclear" data-clear="1">'+esc(t('f_clear'))+'</button>':'');
  el.onclick=e=>{const b=e.target.closest('[data-k]');if(b){toggleAttr(b.dataset.k,b.dataset.v);return;}
    if(e.target.closest('[data-clear]'))clearAttrs();};
}
function toggleAttr(k,v){
  if(!ATTR_KEYS.has(k))return;
  const s=FSEL[k]||(FSEL[k]=new Set());
  if(s.has(v))s.delete(v);else s.add(v);
  if(!s.size)delete FSEL[k];
  render();renderFilterBody();updateFilterDone();updateFilterBtn();
}
function clearAttrs(){for(const k in FSEL)delete FSEL[k];render();renderFilterBody();updateFilterDone();updateFilterBtn();}
function updateFilterDone(){const b=document.getElementById('filterDone');if(!b)return;
  b.textContent=fselCount()?(t('show_n').replace('{n}',VIS.length.toLocaleString())):t('bm_close');}

// ===== כפתור וואטסאפ צף: חלון עם שדה הודעה שהלקוח ממלא ואז שולח =====
function toggleWaChat(){const c=document.getElementById('waChat');if(!c)return;
  const open=c.classList.toggle('open');
  if(open){const m=document.getElementById('waChatMsg');setTimeout(function(){if(m)m.focus();},60);}}
function sendWaChat(){const m=document.getElementById('waChatMsg');
  const txt=((m&&m.value.trim())||t('wa_default'));
  window.open('https://wa.me/'+WA_NUMBER+'?text='+encodeURIComponent(txt),'_blank');
  const c=document.getElementById('waChat');if(c)c.classList.remove('open');}
// סגירה בלחיצה בחוץ. 🔴 הכפתור בסרגל התחתון לא היה מוחרג כאן, ולכן
// הלחיצה עליו פתחה את החלון ומיד סגרה אותו — הכפתור פשוט לא עבד.
// כל כפתור שמפעיל את החלון חייב להיות מוחרג, אחרת הוא סוגר את עצמו.
// שדה כמות: הערך הקיים נבחר בכניסה לשדה, כך שהקלדה דורסת אותו.
// בלי זה הלקוח צריך למחוק ידנית את "1" לפני שהוא כותב "12", ולרוב
// נוצר "112" או "121". תופס גם שדות שנוצרים אחרי טעינת הדף.
document.addEventListener('focusin',function(e){
  var el=e.target;
  if(el&&el.tagName==='INPUT'&&(el.type==='number'||el.inputMode==='numeric')
     &&/qin|qty|cardqin/i.test(el.className+' '+el.id)){
    setTimeout(function(){try{el.select();}catch(_){}},0);
  }
});
// בנייד לחיצה מציבה סמן ולא בוחרת — ההשהיה מאפשרת לדפדפן לסיים ואז בוחרים
document.addEventListener('click',function(e){var c=document.getElementById('waChat');
  if(c&&c.classList.contains('open')&&!e.target.closest('#waChat')
     &&!e.target.closest('#waFloat')&&!e.target.closest('#navWa'))c.classList.remove('open');});

buildNav();
// ===== 🎛️ 12/10/2026 — מגירת סינון אחת (ספורה) =====
// מקטעים: תת-קטגוריה → מותג → מחיר → התכונות של טל → מועדפים/מלאי. כל לחיצה מסננת מיד
// (הספירה בכפתור "הצגת N" מתעדכנת), והבחירות מופיעות כבועות בשורת הסינון עם ✕.
const DOPEN={};          // אילו מקטעים פתוחים (ברירת מחדל: הכל חוץ מהתכונות)
let DBQ='', DBMORE=false;  // חיפוש מותג + "עוד מותגים"
// 🔎 חיפוש חופשי מתוך המגירה — אותו שדה חיפוש של הדף, בתוך התחום שנבחר (קטגוריה/מותג/תכונות)
function drawerSearch(v){const q=document.getElementById('q');if(!q)return;q.value=v;
  if(typeof toggleClr==='function')toggleClr();var ac=document.getElementById('ac');if(ac)ac.classList.remove('show');render();}
function drawerRefresh(){writeHash();buildNav();render();}
function drawerClear(){var so=document.getElementById('sort');if(so)so.value='default';clearSearchQ();curCat='__all__';curSub='__all__';BSEL.clear();for(const k in FSEL)delete FSEL[k];curPrice=-1;favOnly=false;inStockOnly=false;
  var fc=document.getElementById('favchip');if(fc)fc.classList.remove('active');
  var sc=document.getElementById('stockchip');if(sc)sc.classList.remove('active');
  DBQ='';drawerRefresh();}
function drawerCount(pred){return GROUPS.reduce((n,g)=>n+((pred(g)&&(!STOCK_READY||g.variants.some(inDB)))?1:0),0);}
function activeFilterN(){return activeFilterList().filter(f=>f.k!=='cat'&&f.k!=='q').length;}
function sortLbl(v){const m={'price-asc':'sort_pa','price-desc':'sort_pd','name':'sort_name'};return m[v]?t(m[v]):'';}
// כל הבחירות לבועות: קטגוריה, תת-קטגוריה, מותגים, תכונות, מחיר, מועדפים, חיפוש — ומיון שאינו "מומלץ"
function chipList(){
  const out=activeFilterList();
  const so=document.getElementById('sort');
  if(so&&so.value!=='default')out.push({k:'sort',val:sortLbl(so.value)});
  return out;
}
function chipsHtml(){return chipList().map(f=>'<span class="fbchip">'+esc(String(f.val))+'<button type="button" aria-label="'+esc(t('reset_all'))+'" data-k="'+aesc(esc(f.k))+'">✕</button></span>').join('');}
function chipClear(k){if(k==='sort'){const so=document.getElementById('sort');if(so)so.value='default';render();return;}clearOneFilter(k);}
// 🔎 12/10 (נמרוד): "חיפוש" בסרגל התחתון פותח את הסינון מתחילתו. במחשב הסינון הוא עמודה
//    קבועה — גוללים אליה במקום לפתוח מגירה (שהייתה נועלת את גלילת הדף).
function navFilter(){openDrawer();}
// 🔒 נעילת גלילת הדף בזמן שהמגירה פתוחה. overflow:hidden לבד לא עוצר את אייפון —
//    נועלים את body במקום (position:fixed) ושומרים את מיקום הגלילה לחזרה.
function openDrawer(){if(drawerOpen())return;renderDrawer();var _fb=document.getElementById('fdBody');if(_fb)_fb.scrollTop=0;document.getElementById('fdrawer').classList.add('open');document.getElementById('fback').classList.add('open');pushOvState('drawer','fdrawer');
  lockPage();}
function closeDrawer(){if(!drawerOpen())return;if(popOvState('drawer','fdrawer'))return;document.getElementById('fdrawer').classList.remove('open');document.getElementById('fback').classList.remove('open');unlockPage();}
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&document.getElementById('fdrawer').classList.contains('open'))closeDrawer();});
function renderFbar(){
  const btn=document.getElementById('fbBtn'),n=document.getElementById('fbN'),ch=document.getElementById('fbChips');if(!btn)return;
  const so=document.getElementById('sort');
  const k=activeFilterN()+((so&&so.value!=='default')?1:0); n.textContent=k; btn.classList.toggle('on',k>0);
  ch.innerHTML=chipsHtml();
  ch.querySelectorAll('button').forEach(b=>{b.onclick=()=>chipClear(b.dataset.k);});
}
function dsec(key,title,sel,inner,openDef){
  const open=(key in DOPEN)?DOPEN[key]:openDef;
  return '<details class="fdsec" data-sec="'+key+'"'+(open?' open':'')+'><summary><span>'+esc(title)+'</span>'
    +(sel?'<span class="sel">'+esc(sel)+'</span>':'')+'<span class="chev">▼</span></summary><div class="fdlist">'+inner+'</div></details>';
}
function dopt(cls,on,label,n,data){return '<div class="fdopt '+cls+(on?' on':'')+'" '+data+'><span class="box">'+(on?'✓':'')+'</span><span>'+esc(label)+'</span>'+(n!=null?'<span class="n">'+n+'</span>':'')+'</div>';}
function renderDrawer(){
  const el=document.getElementById('fdBody');if(!el)return;
  const had=document.activeElement&&document.activeElement.id==='fdBrandQ';
  const fc=document.getElementById('fdChips');
  if(fc){fc.innerHTML=chipsHtml();fc.querySelectorAll('button[data-k]').forEach(b=>{b.onclick=()=>chipClear(b.dataset.k);});}
  let h='';
  // קבוצה ראשית — גם מי שפתח את הסינון לפני שבחר אריח יכול לבחור כאן
  {
    const cats=catsInStock();
    const hasHot=GROUPS.some(g=>isHot(g)&&(!STOCK_READY||g.variants.some(inDB)));
    let inner=dopt('radio',curCat==='__all__',t('all'),drawerCount(()=>true),'data-cat="__all__"');
    if(hasHot)inner+=dopt('radio',curCat==='__hot__',t('cat_hot'),drawerCount(g=>isHot(g)),'data-cat="__hot__"');
    for(const m of cats)inner+=dopt('radio',curCat===m,catLabel(m),drawerCount(g=>HAS_TREE&&CT_BY[m]?gMain(g)===m:g.type===m),'data-cat="'+aesc(esc(m))+'"');
    h+=dsec('cat',t('af_cat'),curCat!=='__all__'?(curCat==='__hot__'?t('cat_hot'):catLabel(curCat)):'',inner,true);
  }
  // מיון — בתוך המגירה (במקום הבורר הנפרד)
  {
    const so=document.getElementById('sort'),cur=so?so.value:'default';
    const opts=[['default',t('sort_rec')],['price-asc',t('sort_pa')],['price-desc',t('sort_pd')],['name',t('sort_name')]];
    h+=dsec('sort',t('fd_sort'),cur!=='default'?sortLbl(cur):'',opts.map(([v,l])=>dopt('radio',cur===v,l,null,'data-sort="'+v+'"')).join(''),true);
  }
  // תת-קטגוריה
  if(HAS_TREE&&CT_BY[curCat]){
    const subs=subsInStock(curCat);
    if(subs.length){
      const all=drawerCount(g=>gMain(g)===curCat);
      let inner=dopt('radio',curSub==='__all__',t('all'),all,'data-sub="__all__"');
      for(const sb of subs)inner+=dopt('radio',curSub===sb.s,(LANG==='ar'&&sb.ar)?sb.ar:sb.he,drawerCount(g=>g.cs===sb.s),'data-sub="'+aesc(esc(sb.s))+'"');
      h+=dsec('sub',t('fd_sub'),curSub!=='__all__'?catLabel(curSub):'',inner,true);
    }
  }
  // מותג
  {
    let brands=brandsInStock().slice().sort((a,b)=>a.localeCompare(b,'he'));   // א"ב (נמרוד 12/10)
    const q=normText(DBQ);
    if(q)brands=brands.filter(b=>normText(b).includes(q)||expandSearch(b).includes(q)||normText(BRANDS_EN[b]||'').includes(q));
    const LIM=8, more=brands.length>LIM&&!DBMORE&&!q;
    const shown=more?brands.slice(0,LIM):brands;
    let inner=(brandsInStock().length>LIM?'<input class="fdbq" id="fdBrandQ" type="search" autocomplete="off" placeholder="'+esc(t('fd_bq'))+'" value="'+aesc(esc(DBQ))+'">':'');
    inner+=shown.map(b=>dopt('',BSEL.has(b),b+(BRANDS_EN[b]?' · '+BRANDS_EN[b]:''),brandCount(b),'data-brand="'+aesc(b)+'"')).join('');
    if(!shown.length)inner+='<div class="fdopt" style="color:var(--muted)">'+esc(t('empty'))+'</div>';
    if(more)inner+='<button type="button" class="fdmore" data-more="1">'+esc(t('fd_more').replace('{n}',brands.length-LIM))+'</button>';
    else if(DBMORE&&!q&&brands.length>LIM)inner+='<button type="button" class="fdmore" data-more="0">'+esc(t('fd_less'))+'</button>';
    h+=dsec('brand',t('fd_brand'),BSEL.size?(BSEL.size===1?[...BSEL][0]:BSEL.size+' '+t('brands_n')):'',inner,true);
  }
  // מחיר
  {
    let inner=dopt('radio',curPrice<0,t('all_prices'),null,'data-price="-1"');
    PRICES.forEach((pr,i)=>{inner+=dopt('radio',curPrice===i,pr.l,drawerCount(g=>inCatScope(g)&&g.minp>=pr.mn&&g.minp<pr.mx),'data-price="'+i+'"');});
    h+=dsec('price',t('fd_price'),curPrice>=0?PRICES[curPrice].l:'',inner,true);
  }
  // התכונות של טל — לפי הקטגוריה
  for(const {d,opts} of attrSections()){
    const sc=attrScope();
    const inner=opts.map(v=>dopt('',!!(FSEL[d.k]&&FSEL[d.k].has(v)),attrLbl(v),sc.filter(g=>gAttr(g,d.k).includes(v)).length,'data-k="'+aesc(esc(d.k))+'" data-v="'+aesc(esc(v))+'"')).join('');
    const sel=FSEL[d.k]?[...FSEL[d.k]].map(attrLbl).join(', '):'';
    h+=dsec('attr:'+d.k,secLbl(d),sel,inner,true);
  }
  // מועדפים / במלאי
  {
    let inner=dopt('',favOnly,t('fav_only'),FAVS.size,'data-fav="1"');
    if(STOCK_READY)inner+=dopt('',inStockOnly,t('in_stock'),null,'data-stock="1"');
    h+=dsec('misc',t('fd_misc'),'',inner,true);
  }
  el.innerHTML=h;
  const show=document.getElementById('fdShow');if(show)show.textContent=t('show_n').replace('{n}',VIS.length.toLocaleString());
  const clr=document.getElementById('fdClear');if(clr)clr.style.visibility=chipList().length?'':'hidden';
  const fq=document.getElementById('fdQ'),pq=document.getElementById('q');
  if(fq&&pq&&document.activeElement!==fq&&fq.value!==pq.value)fq.value=pq.value;
  el.querySelectorAll('details').forEach(d=>{d.addEventListener('toggle',()=>{DOPEN[d.dataset.sec]=d.open;});});
  const bq=document.getElementById('fdBrandQ');
  if(bq){bq.oninput=()=>{DBQ=bq.value;renderDrawer();};if(had){bq.focus();try{bq.setSelectionRange(bq.value.length,bq.value.length);}catch(_){}}}
  el.onclick=e=>{
    const o=e.target.closest('[data-cat],[data-sub],[data-brand],[data-price],[data-k],[data-fav],[data-stock],[data-more],[data-sort]');if(!o)return;
    if(o.dataset.cat!=null){clearSearchQ();const c=o.dataset.cat;
      if(c!==curCat){curCat=c;curSub='__all__';for(const k in FSEL)delete FSEL[k];}
      drawerRefresh();return;}
    if(o.dataset.sort!=null){const so=document.getElementById('sort');if(so)so.value=o.dataset.sort;render();return;}
    if(o.dataset.more!=null){DBMORE=o.dataset.more==='1';renderDrawer();return;}
    if(o.dataset.sub!=null){clearSearchQ();curSub=o.dataset.sub;drawerRefresh();return;}
    if(o.dataset.brand!=null){const b=o.dataset.brand;if(BSEL.has(b))BSEL.delete(b);else BSEL.add(b);drawerRefresh();return;}
    if(o.dataset.price!=null){curPrice=+o.dataset.price;drawerRefresh();return;}
    if(o.dataset.k!=null){toggleAttr(o.dataset.k,o.dataset.v);return;}
    if(o.dataset.fav!=null){favOnly=!favOnly;var fc=document.getElementById('favchip');if(fc)fc.classList.toggle('active',favOnly);render();return;}
    if(o.dataset.stock!=null){inStockOnly=!inStockOnly;var sc=document.getElementById('stockchip');if(sc)sc.classList.toggle('active',inStockOnly);render();return;}
  };
}
function toggleFavOnly(){favOnly=!favOnly;document.getElementById('favchip').classList.toggle('active',favOnly);render()}
function resetFilters(){   // איפוס כל הסינונים (קטגוריה/מותג/מחיר/מועדפים/חיפוש)
  curCat='__all__';curSub='__all__';BSEL.clear();for(const k in FSEL)delete FSEL[k];curPrice=-1;favOnly=false;inStockOnly=false;
  var q=document.getElementById('q');if(q)q.value='';
  var fc=document.getElementById('favchip');if(fc)fc.classList.remove('active');
  var ac=document.getElementById('ac');if(ac)ac.classList.remove('show');
  writeHash();buildNav();render();
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
 ['אלף','elf e.l.f אי.אל.אף'],['elf','אי.אל.אף אלף'],['e.l.f','אי.אל.אף אלף'],
 // 🔵 נוסף 06/09/2026 — לקוח שמקליד את שם המותג באנגלית, או באיות הישן,
 // לא מצא כלום. כל שורה מרחיבה מונח אחד לכל הווריאציות שלו.
 ['rare','רייר ביוטי ריר ביוטי'],['רייר','rare beauty'],['ריר','רייר ביוטי rare'],
 ['nyx','נייקס'],['נייקס','nyx'],
 ['one size','וואן סייז'],['onesize','וואן סייז'],['וואן סייז','one size onesize'],
 ['rhode','רוד רואד'],['ordinary','דה אורדינרי'],['דה אורדינרי','the ordinary'],
 ['anastasia','אנסטסיה בוורלי הילס'],['אנסטסיה','anastasia beverly hills'],
 ['urban decay','אורבן דיקיי'],['אורבן','urban decay'],
 ['k18','קיי 18'],['קיי 18','k18'],
 ['glow recipe','גלואו רסיפי'],['גלואו','glow recipe'],
 ['gisou','ג\'יסו'],['mugler','מוגלר'],['kryolan','קריולן'],
 ['kiehl','קילס'],['קילס','kiehls kiehl'],
 ['sol de janeiro','סול דה ז\'נרו'],['סול דה','sol de janeiro'],
 ['huda','הודה ביוטי'],['הודה','huda beauty'],
 ['fenty','פנטי ביוטי'],['פנטי','fenty beauty'],
 ['nars','נארס'],['נארס','nars'],
 ['maybelline','מייבלין'],['מייבלין','maybelline'],
 ['too faced','טו פייסד'],['טו פייסד','too faced'],
 ['morphe','מורפי מורף'],['מורפי','morphe'],
 ['laura mercier','לורה מרסייה'],['לורה','laura mercier'],
 ['benefit','בנפיט'],['בנפיט','benefit'],
 ['victoria','ויקטוריה סיקרט'],['ויקטוריה','victoria secret'],
 ['mac','מאק'],['מאק','mac'],
 // מילים נרדפות לסוגי מוצר — כך "ליפסטיק 102" ימצא מוצר שרשום "שפתון", וכן להפך ובאנגלית
 ['שפתון','ליפסטיק lipstick'],['ליפסטיק','שפתון lipstick'],['lipstick','שפתון ליפסטיק'],
 ['סומק','בלאש blush'],['בלאש','סומק blush'],['blush','סומק בלאש'],
 ['צללית','איישדו eyeshadow'],['eyeshadow','צללית'],
 ['קונסילר','concealer'],['concealer','קונסילר'],
 ['פאונדיישן','פאונדיישן foundation'],['foundation','פאונדיישן'],
 ['מסקרה','mascara'],['mascara','מסקרה'],
 ['אייליינר','eyeliner'],['eyeliner','אייליינר'],
 ['ברונזר','bronzer'],['bronzer','ברונזר'],
 ['היילייטר','מדגיש highlighter'],['highlighter','היילייטר'],
 ['פודרה','אבקה powder'],['powder','פודרה אבקה'],
 ['מארז','סט set'],['סט','מארז set'],['set','מארז סט'],
 ['בושם','perfume'],['perfume','בושם'],['edp','בושם perfume'],
 ['מיסט','mist'],['mist','מיסט'],
 ['טונר','toner'],['toner','טונר'],
 ['קרם','cream'],['cream','קרם'],
 ['גבות','גבה brow brows'],['brow','גבות'],
 ['עיפרון','pencil'],['pencil','עיפרון']
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
// חיפוש מק"ט/ברקוד: שאילתה של ספרות בלבד (4+) נבדקת מול הברקודים בלבד ולא מול
// תיאורים — אחרת קידומת יצרן כמו 6093 מחזירה מאות תוצאות. התאמה מהסוף (הספרות
// שהלקוח מקליד הן תמיד האחרונות שהוא רואה) או הכלה, וגם מק"ט מלא עם/בלי ספרת בידוק.
function bcMatch(g,d){
  return g.variants.some(v=>{
    const b=String(v.barcode||'').replace(/\D/g,'');
    if(!b)return false;
    return b===d||b.endsWith(d)||b.includes(d);
  });
}
// כתיב חסר מול כתיב מלא: "נרס" מול "נארס", "עפרון" מול "עיפרון".
// אמות הקריאה א/ו/י/ה הן מה שמשתנה בין שני הכתיבים, ולכן הסרתן משני
// הצדדים מאחדת אותם. משמש כשכבה שנייה בלבד — התאמה מדויקת מדורגת לפניה.
function looseHe(s){return String(s||'').replace(/[אוהי]/g,'');}
function matchQ(g,q){
  q=normText(q);
  if(!q)return true;
  const d=q.replace(/\s/g,'');
  if(/^\d{4,}$/.test(d))return bcMatch(g,d);
  const hay=g._hay||(g._hay=buildHay(g));
  if(hay.includes(q)||q.split(' ').every(term=>hay.includes(term))){g._mq=0;return true;}
  // שכבה שנייה: כתיב גמיש. שאילתה קצרה מדי אחרי ההסרה תתאים לכל דבר.
  const lq=looseHe(q).replace(/\s+/g,' ').trim();
  if(lq.replace(/\s/g,'').length<3)return false;
  const lhay=g._hayL||(g._hayL=looseHe(hay));
  if(lhay.includes(lq)||lq.split(' ').every(term=>term.length<2||lhay.includes(term))){g._mq=1;return true;}
  return false;
}
function visible(){
  const q=document.getElementById('q').value.trim().toLowerCase();
  let r=GROUPS.filter(g=>{
    if(curCat==='__hot__'){if(!isHot(g))return false;}
    else if(curCat!=='__all__'){
      // 🗂️ בעץ הסינון הוא על הקבוצה; `curSub` מצמצם לתת-קטגוריה.
      if(HAS_TREE&&CT_BY[curCat]){
        if(gMain(g)!==curCat)return false;
        if(curSub!=='__all__'&&g.cs!==curSub)return false;
      } else if(g.type!==curCat)return false;
    }
    if(BSEL.size&&!BSEL.has(g.brand))return false;
    for(const k in FSEL){const s=FSEL[k];if(s.size&&!gAttr(g,k).some(v=>s.has(v)))return false;}
    if(curPrice>=0){const pr=PRICES[curPrice];if(!(g.minp>=pr.mn&&g.minp<pr.mx))return false}
    if(favOnly&&!FAVS.has(g.gid))return false;
    if(STOCK_READY&&!g.variants.some(inDB))return false;   // הסתרת מוצרים שאינם ב-DB (לא ניתנים להזמנה)
    if(STOCK_READY&&inStockOnly&&grpSold(g))return false;   // "במלאי בלבד" — רק כשהצ'יפ פעיל מסתירים את מה שאזל
    if(STOCK_READY&&!WHOLESALE&&!g.variants.some(hasConsPrice))return false;   // מצב צרכן: להסתיר מוצר ללא מחיר צרכן
    return matchQ(g,q);
  });
  const s=document.getElementById('sort').value;
  // חיפוש מק"ט: התאמה מדויקת קודמת, אחריה התאמה מהסוף, ורק אז הכלה חלקית
  const dq=normText(q).replace(/\s/g,'');
  if(/^\d{4,}$/.test(dq)){
    const rank=g=>Math.min(...g.variants.map(v=>{
      const b=String(v.barcode||'').replace(/\D/g,'');
      return b===dq?0:(b.endsWith(dq)?1:2);
    }));
    return r.sort((a,b)=>bySold(a,b)||rank(a)-rank(b)||a.name_he.localeCompare(b.name_he,'he'));
  }
  // cards without an image always sink to the bottom (regardless of sort)
  // התאמה מדויקת תמיד לפני התאמת כתיב גמיש
  const byMatch=(a,b)=>(a._mq||0)-(b._mq||0);
  const byImg=(a,b)=> bySold(a,b) || byMatch(a,b) || (a._noimg?1:0)-(b._noimg?1:0);
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
  var p=eff(v);
  if(p==null||!(p>0))return `<div class="pricewrap"><div class="price ${cls||''}">—</div></div>`;   // אין מחיר — לא "₪null"
  var was=(!WHOLESALE&&v.was&&v.was>p)?`<span class="was">₪${v.was}</span>`:'';   // מחיר-לפני (price_before) — מצב צרכן בלבד
  return `<div class="pricewrap"><div class="price ${was?'sale':(cls||'')}">₪${p}${was}</div>${sub}</div>`;
}
function lowStockHtml(v){   // דחיפות מלאי חיה: "נותרו רק X!" כשהמלאי 1–3
  if(!STOCK_READY)return '';
  var n=STOCK[nbc(v&&v.barcode)];
  return (n>0&&n<=3)?`<span class="lowstock">🔥 ${t('left_only').replace('{n}',n)}</span>`:'';
}

// ===== grid =====
// 🎨 גוון רקע עדין לפי הקבוצה. מוחזר כתכונת style מוכנה או כמחרוזת ריקה,
// כדי שמוצר בלי שיוך ייראה בדיוק כמו קודם ולא ייפול.
function CARD_TINT(g){
  const m=HAS_TREE?gMain(g):''; const c=m&&CT_BY[m];
  return c?` style="background:linear-gradient(160deg,#fff,${c.bg})"`:'';
}
function cardHtml(g){
  const v=selV(g);
  const gsold=grpSold(g);   // כל הגוונים אזלו → הכרטיס נשאר, מעומעם ומסומן
  const qty=CART[v.id]?CART[v.id].qty:0;
  const fav=FAVS.has(g.gid)?'on':'';
  const img=v.imgs.length?`<img src="${aesc(v.imgs[0])}" loading="lazy" data-l="${aesc(g.name_he[0]||'✦')}" onerror="imgErr(this)">`:`<div class="ph">${esc(g.name_he[0]||'✦')}</div>`;
  let shades='';
  if(g.variants.length>1){
    const idx=curIdx(g);
    shades=`<div class="shrow" onclick="event.stopPropagation()">${g.variants.map((vv,k)=>swPill(vv,k===idx,`pickV('${g.gid}',${k})`)).join('')}</div>`;
  }
  const nInStock=STOCK_READY?g.variants.filter(vv=>STOCK[nbc(vv.barcode)]>0).length:0;
  return `<div class="card${gsold?' sold':''}" id="card-${g.gid}" role="button" tabindex="0" aria-label="${esc(g.name_he||'')} — לפרטים" onclick="openPd(${g._i})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openPd(${g._i})}">
      <div class="imgbox"${CARD_TINT(g)}>
        <button class="fav ${fav}" aria-label="הוסף למועדפים" onclick="event.stopPropagation();toggleFav('${g.gid}',this)">♥</button>
        ${badgesHtml(v)}${img}
        ${gsold?`<span class="soldflag">${t('sold_out')}</span>`:''}
      </div>
      <div class="body">
        <div class="brand">${esc(g.brand)}${g.ben?`<span class="brand-en">${esc(g.ben)}</span>`:''}</div>
        <div class="nm">${esc(g.name_he)}</div>
        ${g.name_en?`<div class="nm-en">${esc(g.name_en)}</div>`:''}
        ${g.variants.length>1?`<span class="nsh">${g.variants.length} ${t('shades')}${(STOCK_READY&&nInStock>0)?` · <b class="instk">${nInStock} ${t('in_stock_short')}</b>`:''}</span>`:(v.size?`<div class="meta"><span class="tag">${esc(v.size)}</span></div>`:'')}
        ${shades}
        ${lowStockHtml(v)}
        <div class="foot">
          ${priceHtml(v)}
          ${isSold(v)?`<span class="soldpill">${t('sold_out')}</span>`
            :qty>0?`<div class="cardqty" onclick="event.stopPropagation()"><button aria-label="הקטן כמות" onclick="event.stopPropagation();cartChange('${v.id}',-1)">−</button><input class="cardqin" type="number" inputmode="numeric" min="1" value="${qty}" aria-label="כמות" onfocus="this.select()" onclick="event.stopPropagation();this.select()" onkeydown="if(event.key==='Enter')this.blur()" onchange="event.stopPropagation();cartSetQty('${v.id}',Math.max(1,parseInt(this.value)||1))"><button aria-label="הגדל כמות" onclick="event.stopPropagation();cartChange('${v.id}',1)">+</button></div>`
                 :`<button class="add" aria-label="הוסף לסל" onclick="event.stopPropagation();cartChange('${v.id}',1)">+</button>`}
        </div>
      </div>
    </div>`;
}
// 🔵 סרגל הסינונים הפעילים.
// נמרוד: "קשה לחזור למצב של כל המוצרים" — הכפתור הישן היה צ'יפ אפור בין שאר
// הצ'יפים, ונראה זהה בין אם מסונן ובין אם לא. כאן הסרגל **מופיע רק כשמשהו מסונן**,
// אומר בדיוק מה מצומצם, ומאפשר להסיר סינון בודד או לנקות הכל בכפתור בולט.
function activeFilterList(){
  const out=[];
  const q=(document.getElementById('q')||{}).value||'';
  if(curCat==='__hot__')out.push({k:'cat',lbl:t('af_cat'),val:t('cat_hot')});
  else if(curCat!=='__all__')out.push({k:'cat',lbl:t('af_cat'),val:catLabel(curCat)});
  // 🗂️ תת-הקטגוריה חייבת להופיע כאן גם היא — אחרת הלקוחה רואה 22 מתוך 81
  //    בלי שום רמז למה, ואין לה דרך לנקות את הסינון.
  if(curSub!=='__all__')out.push({k:'sub',lbl:t('af_cat'),val:catLabel(curSub)});
  for(const b of BSEL)out.push({k:'brand:'+b,lbl:t('af_brand'),val:b});
  for(const d of ATTR_SEC){const s=FSEL[d.k];if(s)for(const v of s)out.push({k:'attr:'+d.k+':'+v,lbl:secLbl(d),val:attrLbl(v)});}
  if(curPrice>=0&&typeof PRICES!=='undefined'&&PRICES[curPrice])out.push({k:'price',lbl:t('af_price'),val:PRICES[curPrice].l});
  if(favOnly)out.push({k:'fav',lbl:'',val:t('af_fav')});
  if(inStockOnly)out.push({k:'stock',lbl:'',val:t('af_stock')});
  if(q.trim())out.push({k:'q',lbl:t('af_q'),val:q.trim()});
  return out;
}
function clearOneFilter(k){
  if(k==='cat'){curCat='__all__';curSub='__all__';}
  if(k==='sub')curSub='__all__';
  else if(k.indexOf('brand:')===0)BSEL.delete(k.slice(6));
  else if(k.indexOf('attr:')===0){const i=k.indexOf(':',5),kk=k.slice(5,i),v=k.slice(i+1);
    if(FSEL[kk]){FSEL[kk].delete(v);if(!FSEL[kk].size)delete FSEL[kk];}}
  else if(k==='price')curPrice=-1;
  else if(k==='fav'){favOnly=false;const fc=document.getElementById('favchip');if(fc)fc.classList.remove('active');}
  else if(k==='stock'){inStockOnly=false;const sc=document.getElementById('stockchip');if(sc)sc.classList.remove('active');}
  else if(k==='q'){const q=document.getElementById('q');if(q)q.value='';const ac=document.getElementById('ac');if(ac)ac.classList.remove('show');}
  writeHash();buildNav();render();
}
function renderActiveFilters(){
  const bar=document.getElementById('actFil'); if(!bar)return;
  const list=activeFilterList();
  const rc=document.getElementById('resetchip'); if(rc)rc.style.display=list.length?'':'none';
  if(!list.length){bar.className='actfil';bar.innerHTML='';return;}
  bar.className='actfil on';
  bar.innerHTML='<span class="afl">'+esc(t('af_lbl'))+'</span>'+
    list.map(f=>'<span class="aftag">'+(f.lbl?esc(f.lbl)+': ':'')+esc(String(f.val))+
      '<button type="button" aria-label="'+esc(t('reset_all'))+'" data-k="'+esc(f.k)+'">✕</button></span>').join('')+
    '<button class="afclear" type="button" onclick="resetFilters()">'+esc(t('af_clear'))+'</button>';
  bar.querySelectorAll('.aftag button').forEach(function(b){
    b.onclick=function(){clearOneFilter(b.dataset.k);};
  });
}
// ---- paginated render (incremental, for 1400+ cards) ----
let VIS=[], shown=0; const PAGE=60;
function render(){
  VIS=visible(); shown=0;
  const grid=document.getElementById('grid');
  const cnt=document.getElementById('rescount'); if(cnt)cnt.textContent=VIS.length.toLocaleString()+' '+t('items');
  renderActiveFilters();
  buildCatHead();
  renderFbar();renderDrawer();
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
  // הלקוח מחפש לפי שם — מוצר שאזל חייב להימצא, אך מסומן ומוצג אחרי הזמינים
  acList=GROUPS.filter(g=>matchQ(g,q)&&(!STOCK_READY||g.variants.some(inDB))).sort(bySold).slice(0,20);
  acIdx=-1;
  if(!acList.length){ac.classList.remove('show');return}
  ac.innerHTML=acList.map((g,i)=>{const v=selV(g);
    const im=v.imgs.length?`<img src="${aesc(v.imgs[0])}" onerror="this.style.visibility='hidden'">`:`<span style="width:30px"></span>`;
    const so=grpSold(g);
    return `<div class="ac-item${so?' sold':''}" role="option" aria-label="${aesc(g.brand+' - '+g.name_he)}" data-i="${i}" onmousedown="acPick(${i})"><div class="b">${esc(g.brand)}</div>${im}<span class="ac-nm">${esc(g.name_he)}${g.name_en?`<i class="ac-en">${esc(g.name_en)}</i>`:''}</span>${so?`<span class="ac-sold">${t('sold_out')}</span>`:''}</div>`;
  }).join('');
  ac.classList.add('show');
}
function acPick(i){const g=acList[i];if(!g)return;document.getElementById('ac').classList.remove('show');
  document.getElementById('q').blur();openPd(g._i);}
function acKey(e){
  const ac=document.getElementById('ac');if(!ac.classList.contains('show'))return;
  if(e.key==='ArrowDown'){acIdx=Math.min(acIdx+1,acList.length-1);e.preventDefault();}
  else if(e.key==='ArrowUp'){acIdx=Math.max(acIdx-1,0);e.preventDefault();}
  else if(e.key==='Enter'){
    ac.classList.remove('show');
    if(acIdx>=0){acPick(acIdx);}
    else{
      // 🔴 קודם רק סגר את הרשימה והוריד פוקוס — ומכיוון שרשת התוצאות
      // נמצאת הרבה מתחת לקפל, ובדסקטופ הבאנר גבוה, נראה כאילו החיפוש
      // לא עשה כלום. עכשיו מגלגלים אל התוצאות.
      document.getElementById('q').blur(); goShop();
    }
    e.preventDefault();return;}
  else if(e.key==='Escape'){ac.classList.remove('show');return;}
  [...ac.children].forEach((c,k)=>c.classList.toggle('hl',k===acIdx));
}
document.addEventListener('click',e=>{if(!e.target.closest('.search'))document.getElementById('ac').classList.remove('show')});

// ===== product detail =====
function openPd(i){renderPd(GROUPS[i]);openOv('pdModal');}
// 🔍 הגדלה — הגלריה של מסך המוצר. האזנה אחת על המסמך, כי הגלריה נבנית מחדש בכל פתיחה.
let ZOOM=[],ZI=0;
document.addEventListener('click',function(e){
  const im=e.target.closest&&e.target.closest('.pd-gal img'); if(!im)return;
  ZOOM=[...im.parentNode.querySelectorAll('img')].filter(x=>x.style.display!=='none').map(x=>x.src);
  ZI=Math.max(0,ZOOM.indexOf(im.src)); showZoom();
});
// 🖼️ 12/10/2026 — רצועת תמונות עם הגלילה של הטלפון עצמו (scroll-snap). קודם: מעקב אצבע ידני
//    שלא טיפל ב-touchcancel ולכן "נתקע לפעמים". כאן אין קוד מגע בכלל — הדפדפן מחליק.
function zoomTrackEl(){return document.getElementById('zoomTrack');}
function zoomGo(i,smooth){const tr=zoomTrackEl();if(!tr)return;const w=tr.clientWidth||window.innerWidth;
  const rtl=getComputedStyle(tr).direction==='rtl';tr.scrollTo({left:(rtl?-1:1)*i*w,behavior:smooth?'smooth':'auto'});}
function zoomCount(){document.getElementById('zoomCnt').textContent=ZOOM.length>1?(ZI+1)+' / '+ZOOM.length:'';}
function showZoom(){const o=document.getElementById('zoomOv'),tr=zoomTrackEl();if(!o||!tr||!ZOOM.length)return;
  tr.innerHTML=ZOOM.map(src=>'<div class="zslide"><img src="'+aesc(src)+'" alt="" draggable="false"></div>').join('');
  o.querySelectorAll('.zn').forEach(b=>b.style.display=ZOOM.length>1?'':'none');
  o.classList.add('on');zoomCount();
  zoomGo(ZI,false);   // קריאת הרוחב בתוך zoomGo מכריחה פריסה — אין צורך לחכות לציור
  tr.onscroll=()=>{const w=tr.clientWidth||1,i=Math.round(Math.abs(tr.scrollLeft)/w);
    if(i!==ZI&&i>=0&&i<ZOOM.length){ZI=i;zoomCount();}};
  tr.onclick=e=>{if(e.target===tr||e.target.classList.contains('zslide'))closeZoom();};}
function zoomStep(d){if(!ZOOM.length)return;ZI=(ZI+d+ZOOM.length)%ZOOM.length;zoomCount();zoomGo(ZI,true);}
function closeZoom(){const o=document.getElementById('zoomOv');if(o)o.classList.remove('on');}
document.addEventListener('keydown',function(e){const o=document.getElementById('zoomOv');if(!o||!o.classList.contains('on'))return;
  if(e.key==='Escape'){e.stopPropagation();closeZoom();}else if(e.key==='ArrowLeft')zoomStep(1);else if(e.key==='ArrowRight')zoomStep(-1);},true);
// 🎛️ אותן מילים כמו בחלון הסינון — הלקוחה רואה במוצר בדיוק את מה שסיננה לפיו
function pdAttrsHtml(g){
  const h=['coverage','finish','skin','tone','extra'].map(k=>{const ord=ATTR_ORDER[k]||[];
    const vs=gAttr(g,k).slice().sort((a,b)=>ord.indexOf(a)-ord.indexOf(b));if(!vs.length)return '';
    const d=ATTR_SEC.find(x=>x.k===k);
    return '<span class="pa"><b>'+esc(LANG==='ar'?d.ar:d.he)+':</b> '+vs.map(x=>esc(attrLbl(x))).join(' · ')+'</span>';}).join('');
  return h?'<div class="pd-attrs">'+h+'</div>':'';
}
function renderPd(g){
  const v=selV(g);
  const gal=v.imgs.length?v.imgs.map(s=>`<img src="${aesc(s)}" loading="lazy" data-l="${aesc(g.name_he[0]||'✦')}" onerror="imgErr(this)">`).join(''):`<div class="ph">${esc(g.name_he[0]||'✦')}</div>`;
  // Arabic copy when LANG=ar (fallback to Hebrew per field)
  const _dsc=(LANG==='ar'&&v.desc_ar)?v.desc_ar:v.desc;
  const _sum=(LANG==='ar'&&v.summary_ar)?v.summary_ar:v.summary;
  const _fts=(LANG==='ar'&&v.features_ar&&v.features_ar.length)?v.features_ar:v.features;
  const _usg=(LANG==='ar'&&v.usage_ar)?v.usage_ar:v.usage;
  const feats=(_fts&&_fts.length)?`<h4>${t('feats')}</h4><ul>${_fts.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>`:'';
  const _cts=(LANG==='ar'&&v.contents_ar&&v.contents_ar.length)?v.contents_ar:v.contents;
  const contents=(_cts&&_cts.length)?`<h4>${t('contents_h')}</h4><div class="bndl">${_cts.map(c=>`<details><summary>${esc(c.n||c.name||'')}</summary><p>${esc(c.d||c.desc||'')}</p></details>`).join('')}</div>`:'';
  const _ing=(LANG==='ar'&&v.ingredients_ar)?v.ingredients_ar:v.ingredients;
  const ing=_ing?`<h4>${t('ingredients')}</h4><p>${esc(_ing)}</p>`:'';
  const use=_usg?`<h4>${t('usage')}</h4><p>${esc(_usg)}</p>`:'';
  let shades='';
  if(g.variants.length>1){const idx=curIdx(g);
    shades=`<div class="pd-shades"><div class="lbl">${t('pick_shade')} (${g.variants.length}):</div><div class="pd-sw">${g.variants.map((vv,k)=>`<button class="${k===idx?'on':''} ${isSold(vv)?'out':''}" onclick="pdPick('${g.gid}',${k})">${vv.color?`<i class="dot" style="background:${vv.color}"></i>`:''}${esc(vv.shade)}${isSold(vv)?` · ${t('sold_out')}`:''}</button>`).join('')}</div></div>`;}
  const _pc=WHOLESALE?PRICE_CONS[nbc(v.barcode)]:null;   // מחיר צרכן מומלץ במצב סיטונאי
  const _was=(!WHOLESALE&&v.was&&v.was>eff(v))?`<span class="was">₪${v.was}</span>`:'';
  const pr=`<div class="pr">₪${eff(v)}${_was}</div>`+((_pc!=null&&_pc>0)?`<div class="pr-cons">${t('cons_rec')} ₪${_pc}</div>`:'')+lowStockHtml(v);
  const bdg=(v.badges||[]).map(b=>`<span class="tag" style="color:#fff;background:${b==='sale'?'#171717':b==='vegan'?'#3d3a35':'var(--accent)'};border:none">${t('b_'+b)||b}</span>`).join('');
  // similar: other groups, same brand first then same type
  const sim=GROUPS.filter(x=>x.gid!==g.gid&&(x.brand===g.brand||x.type===g.type)&&(!STOCK_READY||x.variants.some(v=>STOCK[nbc(v.barcode)]>0)))
    .sort((a,b)=>(a.brand===g.brand?0:1)-(b.brand===g.brand?0:1)).slice(0,8);
  const simHtml=sim.length?`<div class="sim"><h4>${t('similar')}</h4><div class="sim-row">${sim.map(x=>{const xv=selV(x);
    const im=xv.imgs.length?`<img src="${aesc(xv.imgs[0])}" onerror="this.style.visibility='hidden'">`:'<span class="ph" style="font-size:26px">✦</span>';
    return `<div class="sim-card" onclick="openPd(${x._i})"><div class="si">${im}</div><div class="sn">${esc(x.name_he)}</div><div class="sp">₪${eff(xv)}</div></div>`;}).join('')}</div></div>`:'';
  document.getElementById('pdContent').innerHTML=`
    <div class="pd-gal">${gal}</div>
    <div class="pd">
      <div class="b">${esc(g.brand)}${g.ben?`<span class="brand-en">${esc(g.ben)}</span>`:''}</div>
      <h2>${esc(g.name_he)}</h2>
      ${g.name_en?`<div class="en">${esc(g.name_en)}</div>`:''}
      <div class="row">${bdg}${v.size?`<span class="tag">${esc(v.size)}</span>`:''}<span class="tag">${esc(catLabel(g.type))}</span></div>
      ${shades}
      ${pr}
      <button class="pdfav ${FAVS.has(g.gid)?'on':''}" id="pdFav" onclick="toggleFavFromModal('${g.gid}')"><span class="h">♥</span><span class="t">${FAVS.has(g.gid)?t('fav_remove'):t('fav_add')}</span></button>
      ${_sum?`<p class="pd-lead">${esc(_sum)}</p>`:''}
      ${pdAttrsHtml(g)}
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
  } else if(CART[vid]){
    // 🔴 קודם היה `qty--` בלבד, בלי קשר לגודל ה-delta שהתבקש. לכן כפתור
    // האיקס, ששולח את מלוא הכמות במינוס, הוריד יחידה אחת בלבד ולא הסיר
    // את המוצר. עכשיו הגודל מכובד.
    CART[vid].qty-=Math.max(1,Math.abs(delta));
    if(CART[vid].qty<=0)delete CART[vid];
  }
  saveCart();
  renderCart();updateCard(m.g.gid);
  if(document.getElementById('orderModal').classList.contains('open'))renderOrder();
}
function cartTotals(){let qty=0,sub=0;Object.values(CART).forEach(it=>{qty+=it.qty;sub+=it.qty*it.price});return{qty,sub};}
function renderCart(){const {qty,sub}=cartTotals();const bar=document.getElementById('cartbar');
  document.body.classList.toggle('has-cart',qty>0);
  if(qty===0){bar.classList.remove('show');return}bar.classList.add('show');
  document.getElementById('cartsum').innerHTML=`${qty} ${t('cart_items')} · <b>₪${sub}</b>`;}
function pruneUnavailableCart(){Object.keys(CART).forEach(vid=>{const m=VMAP[vid];if(m&&isSold(m.v))delete CART[vid];});}

/* קופונים: מאומתים בשרת (check_coupon) — אין רשימה בדפדפן, וההנחה נצרבת גם בהזמנה עצמה */
let activeCoupon=null;      // {code,kind,value} מאומת מהשרת
let _cpnSeq=0;              // מונע תוצאה ישנה מלדרוס הקלדה חדשה
function couponEdited(){    // הקלדה בשדה: מנקה קופון שהוחל אם הטקסט השתנה (אימות רק בכפתור/Enter)
  const code=document.getElementById('coupon').value.trim().toUpperCase();const msg=document.getElementById('cmsg');
  if(!code||(activeCoupon&&code!==activeCoupon.code)){_cpnSeq++;activeCoupon=null;msg.textContent='';msg.className='cmsg';renderTotals();}}
async function applyCoupon(){const code=document.getElementById('coupon').value.trim().toUpperCase();const msg=document.getElementById('cmsg');
  const seq=++_cpnSeq;
  if(!code){activeCoupon=null;msg.textContent='';msg.className='cmsg';renderTotals();return}
  if(!SB){activeCoupon=null;msg.textContent=t('coupon_bad');msg.className='cmsg err';renderTotals();return}
  msg.textContent='…';msg.className='cmsg';
  try{
    const {data,error}=await SB.rpc('check_coupon',{p_code:code,p_wholesale_code:(WHOLESALE&&WS_CODE)?WS_CODE:null});
    if(seq!==_cpnSeq)return;   // הוקלד קוד אחר בינתיים
    const row=Array.isArray(data)?data[0]:data;
    if(!error&&row&&row.code){activeCoupon={code:row.code,kind:row.kind,value:Number(row.value)};
      msg.textContent=t('coupon_ok')+couponLabel();msg.className='cmsg ok';}
    else{activeCoupon=null;msg.textContent=t('coupon_bad');msg.className='cmsg err';}
  }catch(e){if(seq!==_cpnSeq)return;activeCoupon=null;msg.textContent=t('coupon_bad');msg.className='cmsg err';}
  renderTotals();}
function discount(sub){if(!activeCoupon)return 0;if(activeCoupon.kind==='percent')return Math.round(sub*activeCoupon.value/100);return Math.min(sub,activeCoupon.value);}
function couponLabel(){const c=activeCoupon;if(!c)return'';return c.kind==='percent'?(c.value+'% '+t('off')):('₪'+c.value+' '+t('off'));}

/* ===== מצב סיטונאי (אימות בצד השרת — המחירים לא נמצאים בדפדפן ללא קוד תקף) ===== */
function openWholesale(){if(WHOLESALE){wholesaleLogout();return;}
  openOv('clubModal');}   // מועדון עסקים: קודם מסך שיווקי (הצטרפות בוואטסאפ / יש לי קוד)
function openWsCode(){
  var i=document.getElementById('wsCode');if(i)i.value='';var m=document.getElementById('wsMsg');if(m){m.textContent='';m.className='cmsg';}
  openOv('wsModal');setTimeout(function(){var el=document.getElementById('wsCode');if(el)el.focus();},60);}
async function submitWholesale(){const code=document.getElementById('wsCode').value.trim();const msg=document.getElementById('wsMsg');
  if(!code){msg.textContent='';msg.className='cmsg';return;}
  if(!SB){msg.textContent=t('ws_unavailable');msg.className='cmsg err';return;}
  msg.textContent='…';msg.className='cmsg';
  const ok=await loadWholesalePrices(code);   // השרת מאמת ומחזיר מחירים רק אם הקוד נכון
  if(ok){WS_CODE=code;try{localStorage.setItem('wholesale_code',code);localStorage.removeItem('wholesale_unlocked');}catch(e){}
    setWholesale(true);closeOv('wsModal');}
  else{msg.textContent=t('ws_bad');msg.className='cmsg err';}}
function wholesaleLogout(){setWholesale(false);}
function setWholesale(on){WHOLESALE=on;
  if(!on){WS_CODE=null;PRICE_WS={};}
  try{if(!on)localStorage.removeItem('wholesale_code');}catch(e){}
  updateWsUI();repriceCart();renderCart();render();
  if(activeCoupon)applyCoupon();   // אימות-מחדש של הקופון בשרת — קהל היעד תלוי במצב (צרכן/סיטונאי)
  if(document.getElementById('orderModal').classList.contains('open'))renderOrder();}
function updateWsUI(){var b=document.getElementById('wsBanner');if(b)b.style.display=WHOLESALE?'flex':'none';
  var pb=document.getElementById('pbWholesale');if(pb)pb.textContent=WHOLESALE?t('ws_exit'):t('club_link');}
function repriceCart(){Object.keys(CART).forEach(function(vid){var m=VMAP[vid];if(m)CART[vid].price=eff(m.v);});}   // עדכון מחירי פריטים בסל למצב הפעיל

function openOrder(){renderOrder();syncAgree();openOv('orderModal')}
function closeOrder(){closeOv('orderModal')}

// ===== שמירת הסל ופרטי המזמין בין ביקורים =====
// לקוח שסגר את הדף בטעות, רענן, או חזר אחרי כמה שעות — מוצא את הסל ואת
// הפרטים שמילא. הכול נשמר **רק במכשיר שלו** ולא נשלח לשום מקום עד שהוא
// לוחץ לשלוח הזמנה.
const SAVE_KEY='bf_cart_v1', BUYER_KEY='bf_buyer_v1', SAVE_DAYS=14;
const BUYER_FIELDS=['buyer-name','buyer-phone','buyer-city','buyer-street','buyer-house',
                    'buyer-apt','buyer-floor','buyer-entrance','buyer-email','buyer-id','notes'];

function saveCart(){
  try{
    const items=Object.keys(CART).map(k=>({v:k,q:CART[k].qty}));
    if(!items.length){localStorage.removeItem(SAVE_KEY);return;}
    localStorage.setItem(SAVE_KEY,JSON.stringify({t:Date.now(),items}));
  }catch(e){}
}
function saveBuyer(){
  try{
    const d={};
    BUYER_FIELDS.forEach(function(id){const e=document.getElementById(id);if(e&&e.value.trim())d[id]=e.value.trim();});
    if(CITY)d._city=CITY.c;
    if(STREET_CODE!=null)d._street=STREET_CODE;
    if(!Object.keys(d).length){localStorage.removeItem(BUYER_KEY);return;}
    d.t=Date.now();
    localStorage.setItem(BUYER_KEY,JSON.stringify(d));
  }catch(e){}
}
function restoreCart(){
  try{
    const raw=localStorage.getItem(SAVE_KEY); if(!raw)return;
    const d=JSON.parse(raw);
    // סל ישן מדי כבר לא רלוונטי — מחירים ומלאי השתנו
    if(!d||!d.items||(Date.now()-d.t)>SAVE_DAYS*864e5){localStorage.removeItem(SAVE_KEY);return;}
    d.items.forEach(function(it){
      const m=VMAP[it.v]; if(!m)return;                 // מוצר שכבר לא בקטלוג
      CART[it.v]={vid:it.v,
        name:m.g.name_he+(m.v.shade&&m.g.variants.length>1?' · '+m.v.shade:''),
        brand:m.g.brand,size:m.v.size,price:eff(m.v),   // המחיר מהקטלוג ולא מהשמירה
        qty:Math.max(1,parseInt(it.q,10)||1)};
    });
    renderCart();
  }catch(e){}
}
function restoreBuyer(){
  try{
    const raw=localStorage.getItem(BUYER_KEY); if(!raw)return;
    const d=JSON.parse(raw);
    if(!d||(Date.now()-d.t)>SAVE_DAYS*864e5){localStorage.removeItem(BUYER_KEY);return;}
    BUYER_FIELDS.forEach(function(id){const e=document.getElementById(id);if(e&&d[id])e.value=d[id];});
    if(d._city){const c=CITIES.find(x=>x.c===d._city);
      if(c){CITY=c;document.getElementById('buyer-city').value=cityLabel(c);if(c.s)loadStreets(c.c);}}
    if(d._street!=null)STREET_CODE=d._street;
    // פרטי בניין שמורים → לפתוח את המקטע כדי שהלקוח יראה אותם
    if(d['buyer-apt']||d['buyer-floor']||d['buyer-entrance']){
      const r=document.getElementById('bldgRow');
      if(r&&r.style.display==='none')toggleBldg();
    }
    updateStreetMode();
  }catch(e){}
}
document.addEventListener('input',function(e){
  if(e.target&&BUYER_FIELDS.indexOf(e.target.id)>=0)saveBuyer();
});
document.addEventListener('change',function(e){
  if(e.target&&BUYER_FIELDS.indexOf(e.target.id)>=0)saveBuyer();
});
// ניקוי הסל כולו. שואל לפני, כי אין ממנו דרך חזרה.
function clearCart(){
  const n=Object.keys(CART).length;
  if(!n)return;
  if(!confirm(t('clear_cart_ask').replace('{n}',n)))return;
  Object.keys(CART).forEach(function(k){delete CART[k];});
  saveCart();
  activeCoupon=null;
  const c=document.getElementById('coupon'); if(c)c.value='';
  const cm=document.getElementById('cmsg'); if(cm){cm.textContent='';cm.className='cmsg';}
  renderCart(); render(); renderOrder();
}

// ===== כתובת מובנית =====
// היישובים נצרבים בדף (18 ק"ב); הרחובות נשלפים לפי דרישה מהמסד.
// 492 מתוך 1,310 היישובים בישראל (קיבוצים, מושבים, כפרים) הם בלי רחובות
// כלל — ולכן השדה מתחלף שם אוטומטית לשדה חופשי. רשימת רחובות ריקה היא
// הכשל שגורם לנטישת קופה, ולא נציג אותה אף פעם.
const CITIES = /*__CITIES__*/;
let CITY = null;                 // {c,h,a,s} היישוב שנבחר
let STREETS = null;              // מטמון רחובות ליישוב הנוכחי
let STREET_CODE = null;          // סמל הרחוב, אם נבחר מהרשימה
const _streetCache = {};
let _popIdx = -1, _popItems = [], _popKind = null;

function cityLabel(c){return (LANG==='ar'&&c.a)?c.a:c.h;}
function normHe(x){return String(x||'').replace(/["'׳״\-–—]/g,'').replace(/\s+/g,' ').trim();}
function rank(name,q){return name===q?0:1;}   // התאמה מדויקת תמיד ראשונה

function closePop(kind){
  const p=document.getElementById('pop-'+kind); if(p){p.classList.remove('show');p.innerHTML='';}
  const inp=document.getElementById('buyer-'+kind); if(inp)inp.setAttribute('aria-expanded','false');
  _popIdx=-1;_popItems=[];_popKind=null;
}
function showPop(kind,items,onPick,emptyMsg){
  const p=document.getElementById('pop-'+kind), inp=document.getElementById('buyer-'+kind);
  if(!p)return;
  if(!items.length){
    if(!emptyMsg){closePop(kind);return;}
    p.innerHTML='<li class="none">'+esc(emptyMsg)+'</li>';
    p.classList.add('show');inp.setAttribute('aria-expanded','true');
    _popItems=[];_popIdx=-1;_popKind=kind;return;
  }
  p.innerHTML=items.map((it,i)=>'<li role="option" aria-selected="false" data-i="'+i+'">'+esc(it.label)+
    (it.sub?'<span class="sub">'+esc(it.sub)+'</span>':'')+'</li>').join('');
  p.classList.add('show');inp.setAttribute('aria-expanded','true');
  _popItems=items;_popIdx=-1;_popKind=kind;
  // mousedown ולא click: blur של השדה קורה לפני click והיה סוגר את הרשימה
  p.onmousedown=function(e){const li=e.target.closest('li[data-i]');if(!li)return;e.preventDefault();onPick(items[+li.dataset.i]);};
  p._onPick=onPick;
}
function popKey(e,kind){
  const p=document.getElementById('pop-'+kind);
  if(!p||!p.classList.contains('show')||!_popItems.length){
    if(e.key==='Enter'&&p&&p.classList.contains('show'))e.preventDefault();
    return;
  }
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){
    e.preventDefault();
    _popIdx=e.key==='ArrowDown'?Math.min(_popIdx+1,_popItems.length-1):Math.max(_popIdx-1,0);
    [...p.querySelectorAll('li[data-i]')].forEach((li,i)=>li.setAttribute('aria-selected',i===_popIdx?'true':'false'));
    const cur=p.querySelector('li[aria-selected="true"]'); if(cur)cur.scrollIntoView({block:'nearest'});
  } else if(e.key==='Enter'){
    if(_popIdx>=0){e.preventDefault();p._onPick(_popItems[_popIdx]);}
  } else if(e.key==='Escape'){ closePop(kind); }
}

// ---- יישוב ----
function cityInput(){
  clearErr('row-city');
  const q=normHe(document.getElementById('buyer-city').value);
  CITY=null; STREET_CODE=null;
  if(q.length<1){closePop('city');updateStreetMode();return;}
  const pre=[],inc=[];
  for(const c of CITIES){
    const h=normHe(c.h), a=c.a?normHe(c.a):'';
    if(h.startsWith(q)||(a&&a.startsWith(q)))pre.push(c);
    else if(h.includes(q)||(a&&a.includes(q)))inc.push(c);
    if(pre.length>=40)break;
  }
  pre.sort((a,b)=>rank(normHe(a.h),q)-rank(normHe(b.h),q)||normHe(a.h).length-normHe(b.h).length);
  const list=pre.concat(inc).slice(0,40).map(c=>({label:cityLabel(c),sub:(LANG==='ar'&&c.a)?c.h:'',raw:c}));
  showPop('city',list,pickCity,list.length?'':t('no_match'));
}
function pickCity(it){
  CITY=it.raw;
  document.getElementById('buyer-city').value=cityLabel(CITY);
  closePop('city'); closePop('street'); clearErr('row-city'); clearErr('row-street');
  STREETS=null; STREET_CODE=null;   // החלפת יישוב מאפסת גם את רשימת הרחובות שנשארה פתוחה מהיישוב הקודם
  document.getElementById('buyer-street').value='';
  updateStreetMode();
  if(CITY.s)loadStreets(CITY.c);
  document.getElementById('buyer-street').focus();
}
function cityBlur(){
  setTimeout(function(){
    closePop('city');
    // הוקלד חופשי בלי בחירה — מנסים התאמה מדויקת, אחרת מכבדים את הטקסט
    if(!CITY){
      const v=normHe(document.getElementById('buyer-city').value);
      if(v){const m=CITIES.find(c=>normHe(c.h)===v||(c.a&&normHe(c.a)===v));
            if(m){CITY=m;document.getElementById('buyer-city').value=cityLabel(m);if(m.s)loadStreets(m.c);}}
      updateStreetMode();
    }
  },140);
}

// ---- רחוב ----
function updateStreetMode(){
  const hint=document.getElementById('hint-street'), lb=document.getElementById('lb-street');
  const inp=document.getElementById('buyer-street');
  const known=CITY&&CITY.s;
  if(!CITY){ hint.textContent=''; inp.placeholder=t('city_first'); }
  else if(known){ hint.textContent=''; inp.placeholder=t('street_ph'); }
  else { hint.textContent=t('no_streets'); inp.placeholder=t('street_free'); }
  if(lb)lb.firstChild&&(lb.childNodes[0].nodeValue=(known||!CITY)?t('l_street'):t('street_free'));
}
async function loadStreets(code){
  if(_streetCache[code]){STREETS=_streetCache[code];return;}
  if(!SB){STREETS=[];return;}
  // ⚠️ PostgREST מחזיר לכל היותר 1000 שורות בלי קשר ל-limit שביקשנו.
  // לתל אביב 2,768 רחובות ולירושלים 4,381 — בלי דפדוף הרשימה נחתכת
  // ולקוח שגר ברחוב מאוחר באלפבית פשוט לא מוצא אותו. נבדק ונתפס בפועל.
  const PAGE=1000, all=[];
  try{
    for(let from=0; from<8000; from+=PAGE){
      const {data,error}=await SB.from('streets').select('street_code,street_name')
        .eq('city_code',code).order('street_code').range(from,from+PAGE-1);
      if(error)throw error;
      all.push(...(data||[]));
      if(!data||data.length<PAGE)break;
    }
    STREETS=_streetCache[code]=all;
  }catch(e){ console.warn('streets',e); STREETS=[]; }   // כשל שליפה → שדה חופשי, לא קופה תקועה
}
function streetInput(){
  clearErr('row-street'); STREET_CODE=null;
  const q=normHe(document.getElementById('buyer-street').value);
  if(!CITY||!CITY.s||!STREETS||!STREETS.length||q.length<1){closePop('street');return;}
  const pre=[],inc=[];
  for(const r of STREETS){
    const n=normHe(r.street_name);
    if(n.startsWith(q))pre.push(r); else if(n.includes(q))inc.push(r);
    if(pre.length>=40)break;
  }
  pre.sort((a,b)=>rank(normHe(a.street_name),q)-rank(normHe(b.street_name),q)||a.street_name.length-b.street_name.length);
  const list=pre.concat(inc).slice(0,40).map(r=>({label:r.street_name,raw:r}));
  showPop('street',list,pickStreet,list.length?'':t('no_match'));
}
function pickStreet(it){
  document.getElementById('buyer-street').value=it.raw.street_name;
  STREET_CODE=it.raw.street_code;
  closePop('street'); clearErr('row-street');
  document.getElementById('buyer-house').focus();
}
function streetBlur(){setTimeout(function(){
  closePop('street');
  if(STREET_CODE===null&&STREETS&&STREETS.length){
    const v=normHe(document.getElementById('buyer-street').value);
    const m=STREETS.find(r=>normHe(r.street_name)===v);
    if(m){STREET_CODE=m.street_code;document.getElementById('buyer-street').value=m.street_name;}
  }
},140);}

// ===== מילוי אוטומטי =====
// שתי סיבות שבגללן המילוי האוטומטי לא השלים רחוב ומספר בית:
//
// 1. **אין אסימון תקני למספר בית.** הדפדפן שומר שורת כתובת אחת ודוחף
//    את כולה ל-address-line1 — כלומר "הרצל 5" נכנס לשדה הרחוב ושדה
//    המספר נשאר ריק. הפתרון: לפצל את המספר הנגרר בעצמנו.
//
// 2. **בורר היישוב מצפה לבחירה מהרשימה.** מילוי אוטומטי כותב ערך בלי
//    שאיש בחר, ולכן CITY נשאר ריק ורשימת הרחובות לא נטענה כלל.
//
// רץ על change של השדות — האירוע שנשלח בסיום מילוי אוטומטי — וגם
// כשנפתחת מגירת ההזמנה, למקרה שהדפדפן מילא לפני שהקוד הספיק להאזין.
function splitHouseFromStreet(){
  const st=document.getElementById('buyer-street'), hs=document.getElementById('buyer-house');
  if(!st||!hs||hs.value.trim())return false;
  const v=st.value.trim();
  // "הרצל 5" · "הרצל 5א" · "רוטשילד 12/3" — המספר תמיד בסוף
  const m=v.match(/^(.*?[^\d\s\/-])[\s,]+(\d+[\dא-ת\/\-]*)$/);
  if(!m||!m[1].trim())return false;
  st.value=m[1].trim(); hs.value=m[2];
  return true;
}
function resolveAutofill(){
  const ci=document.getElementById('buyer-city');
  if(!ci)return;
  // היישוב: התאמה מדויקת ואז גמישה, בלי לפתוח רשימה — המשתמש לא הקליד
  if(!CITY&&ci.value.trim()){
    const v=normHe(ci.value);
    let m=CITIES.find(c=>normHe(c.h)===v||(c.a&&normHe(c.a)===v));
    if(!m){const lv=looseHe(v); m=CITIES.find(c=>looseHe(normHe(c.h))===lv);}
    if(m){CITY=m; ci.value=cityLabel(m); clearErr('row-city'); if(m.s)loadStreets(m.c);}
  }
  closePop('city'); closePop('street');
  if(splitHouseFromStreet())clearErr('row-house');
  updateStreetMode();
  // אם הרחוב שהושלם קיים ברשימה — נצמיד לו את הסמל הרשמי
  if(STREET_CODE===null&&STREETS&&STREETS.length){
    const sv=normHe(document.getElementById('buyer-street').value);
    const hit=STREETS.find(r=>normHe(r.street_name)===sv);
    if(hit){STREET_CODE=hit.street_code; document.getElementById('buyer-street').value=hit.street_name;}
  }
}
function toggleBldg(){
  const r=document.getElementById('bldgRow'),b=document.getElementById('bldgToggle');
  const open=r.style.display==='none';
  r.style.display=open?'':'none';
  b.textContent=open?t('bldg_hide'):t('bldg_show');
  if(open){const a=document.getElementById('buyer-apt');if(a)a.focus();}
}

// ---- ולידציה ----
function clearErr(rowId){const r=document.getElementById(rowId);if(r)r.classList.remove('bad');}
function setErr(rowId,erId,msg){
  const r=document.getElementById(rowId),e=document.getElementById(erId);
  if(e)e.textContent=msg; if(r)r.classList.add('bad');
  return r;
}
// נייד 05X עשר ספרות · קווי תשע · לא-גיאוגרפי 07X עשר. הקידומות 07X נופלות
// ברגקסים ישראליים ישנים שרצים ברשת — ואלה מספרים אמיתיים של לקוחות.
function validPhone(v){
  const d=String(v||'').replace(/\D/g,'').replace(/^972/,'0');
  if(/^0(5\d|7\d)\d{7}$/.test(d))return true;
  if(/^0(2|3|4|8|9)\d{7}$/.test(d))return true;
  return false;
}
function checkPhone(){
  const v=gv('buyer-phone');
  if(v&&!validPhone(v))setErr('row-phone','er-phone',t('err_phone'));
  else clearErr('row-phone');
}
function shipParts(){
  return {city:gv('buyer-city'),cityCode:CITY?CITY.c:null,
          street:gv('buyer-street'),streetCode:STREET_CODE,
          house:gv('buyer-house'),apt:gv('buyer-apt'),
          floor:gv('buyer-floor'),entrance:gv('buyer-entrance')};
}
function shipLine(){
  const p=shipParts();
  const extra=[p.apt?t('l_apt')+' '+p.apt:'',p.floor?t('l_floor')+' '+p.floor:'',p.entrance?t('l_entrance')+' '+p.entrance:''].filter(Boolean).join(', ');
  return [[p.street,p.house].filter(Boolean).join(' '),extra,p.city].filter(Boolean).join(', ');
}
// לחיצה על מוצר בסל → קפיצה אליו במקומו ברשת.
// הכוונה (בקשת נמרוד 24/08): להיזכר רגע מה המוצר, וגם לראות שוב מה עמד לידו
// ולא נבחר. לכן קופצים לכרטיס בתוך הרשת ולא פותחים את המגירה שמסתירה את השכנים.
function goToProduct(vid){
  const m=VMAP[vid]; if(!m)return;
  closeOv('orderModal');
  const gi=m.g.variants.indexOf(m.v); if(gi>=0)sel[m.g.gid]=gi;   // הכרטיס יציג את הגוון שנבחר בסל
  if(visible().indexOf(m.g)<0){   // מסונן החוצה → מנקים סינון, אחרת הקפיצה תוביל לשום מקום
    curCat='__all__';curSub='__all__';BSEL.clear();for(const k in FSEL)delete FSEL[k];curPrice=-1;favOnly=false;inStockOnly=false;
    const q=document.getElementById('q'); if(q&&q.value){q.value='';toggleClr();}
    const fc=document.getElementById('favchip'); if(fc)fc.classList.remove('active');
    const sc=document.getElementById('stockchip'); if(sc)sc.classList.remove('active');
    buildNav();
  }
  render();
  const pos=VIS.indexOf(m.g);
  if(pos<0){openPd(m.g._i);return;}   // נפילה חיננית: המוצר אינו ברשת — לפחות לפתוח את המגירה
  while(shown<=pos&&shown<VIS.length)loadMore();   // הרשת מוגשת בדפים של 60
  setTimeout(function(){
    const el=document.getElementById('card-'+m.g.gid); if(!el)return;
    const y=el.getBoundingClientRect().top+(window.pageYOffset||document.documentElement.scrollTop||0)-90;
    window.scrollTo({top:y,behavior:'smooth'});
    el.classList.remove('jump'); void el.offsetWidth; el.classList.add('jump');   // reflow כדי שהאנימציה תרוץ שוב
    setTimeout(function(){el.classList.remove('jump');},2300);
  },90);
}
function renderOrder(){
  // הדפדפן עשוי למלא אוטומטית לפני שהמגירה נפתחה ובלי לשלוח change —
  // בדיקה בפתיחה מבטיחה שהעיר תזוהה והרחוב יפוצל בכל מקרה
  setTimeout(function(){try{resolveAutofill();}catch(_){}} ,120);
  const keys=Object.keys(CART);window._K=keys;const body=document.getElementById('omBody');
  if(!keys.length){body.innerHTML='<p style="text-align:center;color:var(--muted);padding:20px">'+t('cart_empty')+'</p>';renderTotals();return}
  body.innerHTML=keys.map((k,idx)=>{const it=CART[k];
    const _m=VMAP[k], _im=(_m&&_m.v.imgs&&_m.v.imgs[0])||'';   // תמונת המוצר הראשונה
    return `<div class="om-row">
    <button class="om-go" type="button" data-a="go" data-i="${idx}" title="${aesc(t('go_to_product'))}" aria-label="${aesc(t('go_to_product'))} — ${aesc(it.name)}">
      ${_im?`<img class="om-img" src="${_im}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`:'<span class="om-img"></span>'}
      <div class="nm">${esc(it.name)}<small>${esc(it.brand)}${it.size?' · '+esc(it.size):''}</small></div>
      <span class="go-ico" aria-hidden="true">↗</span>
    </button>
    <div class="qy"><button data-i="${idx}" data-a="dec">−</button><input class="qin" type="number" inputmode="numeric" min="1" data-qi="${idx}" value="${it.qty}" onfocus="this.select()" onclick="this.select()"><button data-i="${idx}" data-a="inc">+</button></div>
    <div class="lt">₪${it.qty*it.price}</div>
    <button class="om-del" data-i="${idx}" data-a="del">✕</button></div>`}).join('');
  body.onclick=e=>{const b=e.target.closest('[data-a]');if(!b)return;const key=window._K[+b.dataset.i];if(!key)return;
    if(b.dataset.a==='go'){goToProduct(key);return;}   // חייב להיבדק ראשון — אחרת הוא נופל למסלול המחיקה
    cartChange(key,b.dataset.a==='inc'?1:(b.dataset.a==='dec'?-1:-(CART[key]?CART[key].qty:0)));};
  body.onchange=e=>{const inp=e.target.closest('[data-qi]');if(!inp)return;const key=window._K[+inp.dataset.qi];if(!key)return;
    let n=parseInt(inp.value,10);if(isNaN(n)||n<1)n=1;cartSetQty(key,n);};
  renderTotals();
}
function cartSetQty(vid,n){const m=VMAP[vid];if(!m||!CART[vid])return;CART[vid].qty=Math.max(1,n);
  saveCart();
  renderCart();updateCard(m.g.gid);if(document.getElementById('orderModal').classList.contains('open'))renderOrder();}
function renderTotals(){const {sub}=cartTotals();const d=discount(sub);const el=document.getElementById('totals');
  if(!Object.keys(CART).length){el.innerHTML='';return}
  // צרכן: המחירים כבר כוללים מע"מ — אין תוספת. סיטונאי: מחירי נטו + שורת מע"מ 18%.
  const net=sub-d, vat=WHOLESALE?Math.round(net*0.18):0, tot=net+vat;
  el.innerHTML=`<div class="l"><span>${t('subtotal')}</span><span>₪${sub}</span></div>
    ${d?`<div class="l" style="color:#15803d"><span>${t('discount')} (${esc(activeCoupon.code)})</span><span>−₪${d}</span></div>`:''}
    ${WHOLESALE?`<div class="l"><span>${t('vat')}</span><span>₪${vat}</span></div>`:`<div class="l"><span style="color:var(--muted);font-size:12px">${t('incl_vat')}</span><span></span></div>`}
    <div class="l grand"><span>${t('grand')}</span><b>₪${tot}</b></div>`;}

const WA_NUMBER='972534555501';
function gv(id){var e=document.getElementById(id);return e?e.value.trim():''}
function noteText(){   // עוסק/ח.פ + הערת הלקוח + קופון — נשמר ב-orders.note
  // ⚠️ הכתובת כבר לא נכנסת לכאן. היא נשמרת בעמודות ייעודיות ב-orders
  // (ship_city/ship_street/ship_house/…) — קודם היא נדחסה למחרוזת הזו,
  // ולכן שדה הכתובת בבק אופיס היה ריק בכל ההזמנות מהקטלוג.
  const bid=gv('buyer-id');
  let n='';
  if(bid)n+=`עוסק/ח.פ: ${bid}`;
  const notes=gv('notes');if(notes)n=(n?n+' | ':'')+notes;
  if(activeCoupon){const d=discount(cartTotals().sub);if(d)n=(n?n+' | ':'')+`קופון ${activeCoupon.code} (−₪${d})`;}
  return n;
}
function buildOrderText(orderId){
  const keys=Object.keys(CART);if(!keys.length)return '';
  let msg='*הזמנה חדשה — Beauty Favorites*\n';
  if(orderId)msg+=`מס׳ הזמנה: #${orderId}\n`;
  const name=gv('buyer-name'),bid=gv('buyer-id'),phone=gv('buyer-phone'),addr=shipLine();
  if(name)msg+=`\nשם: ${name}`;if(bid)msg+=`\nעוסק/ח.פ: ${bid}`;
  if(addr)msg+=`\nכתובת: ${addr}`;if(phone)msg+=`\nטלפון: ${phone}`;msg+='\n\n';
  let sub=0;keys.forEach(k=>{const it=CART[k];const lt=it.qty*it.price;sub+=lt;
    msg+=`• ${it.name}${it.size?' ('+it.size+')':''} ×${it.qty} = ₪${lt}\n`});
  const d=discount(sub);const net=sub-d,vat=WHOLESALE?Math.round(net*0.18):0,tot=net+vat;
  if(d)msg+=`\nהנחה (${activeCoupon.code}): −₪${d}`;
  if(WHOLESALE)msg+=`\nסכום לפני מע"מ: ₪${net}\nמע"מ 18%: ₪${vat}\n*סה"כ כולל מע"מ: ₪${tot}*`;
  else msg+=`\n*סה"כ לתשלום (כולל מע"מ): ₪${tot}*`;
  const notes=gv('notes');if(notes)msg+=`\n\nהערות: ${notes}`;return msg;
}

/* ===== חיבור Supabase (אופציונלי). ריק → fallback לוואטסאפ-טקסט בלבד ===== */
const SB=(window.SUPA&&window.SUPA.url&&window.SUPA.anon&&window.supabase)
  ? window.supabase.createClient(window.SUPA.url,window.SUPA.anon) : null;
var STOCK={}, PRICE_WS={}, PRICE_CONS={};   // ברקוד-מנורמל -> מלאי / מחיר סיטונאי / מחיר צרכן (var=hoisted כדי ש-eff לא יזרוק בטעינה)
var STOCK_READY=false;
var WS_CODE=(function(){try{return localStorage.getItem('wholesale_code')||null;}catch(e){return null;}})();  // הקוד השמור (אומת בשרת)
var WHOLESALE=!!WS_CODE;   // מצב סיטונאי פעיל? (המחירים מגיעים מהשרת רק עם קוד תקף)
function priceMap(){return WHOLESALE?PRICE_WS:PRICE_CONS;}   // המפה הפעילה לפי המצב
function hasConsPrice(v){var m=PRICE_CONS[nbc(v&&v.barcode)];return m!=null&&m>0;}   // יש מחיר צרכן?
function nbc(x){return String(x||'').replace(/[^0-9A-Za-z]/g,'').toUpperCase();}   // ברקוד → מפתח השוואה. אותיות נשמרות — יש מותגים עם ברקוד אלפאנומרי (ויקטוריהס סיקרט)
function inDB(v){return STOCK_READY && v && STOCK[nbc(v.barcode)]!==undefined;}   // קיים ב-DB?
function isSold(v){if(!STOCK_READY)return false;const n=nbc(v&&v.barcode);
  if(!WHOLESALE&&!hasConsPrice(v))return true;   // 12/10: גוון בלי מחיר צרכן — לא למכירה לצרכן (היה מציג ₪null)
  if(WHOLESALE&&!(PRICE_WS[n]>0))return true;     // 13/10: גוון בלי מחיר סיטונאי — לא למכירה לסיטונאי (השרת היה מסרב)
  return STOCK[n]===undefined||STOCK[n]<=0;}  // לא-ב-DB או אזל → לא זמין
// כל הוריאנטים אזלו? (החלטת 24/08: מוצר כזה נשאר בקטלוג עם תג "אזל" ואינו נעלם)
function grpSold(g){return STOCK_READY && !g.variants.some(function(v){return STOCK[nbc(v.barcode)]>0;});}
// מה שאזל תמיד יורד לסוף הרשימה — לא תופס את הכרטיסים הראשונים.
// הצהרת פונקציה (ולא const) כי ענף חיפוש הברקוד ב-visible() קורא לה לפני נקודת ההגדרה.
function bySold(a,b){return (grpSold(a)?1:0)-(grpSold(b)?1:0);}
async function loadStock(){
  if(!SB)return;
  try{
    const page=1000; let from=0;        // עוקף את תקרת 1000 השורות של PostgREST
    for(;;){
      const {data,error}=await SB.from('catalog_products').select('barcode,stock,active,price_consumer').range(from,from+page-1);   // תצוגה ציבורית מצומצמת (~319): בלי עלות/סיטונאי — אלה נשלפים רק עם קוד תקף
      if(error)throw error;
      (data||[]).forEach(p=>{const n=nbc(p.barcode);if(n){STOCK[n]=p.active?p.stock:0;
        if(p.price_consumer!=null)PRICE_CONS[n]=Number(p.price_consumer);}});
      if(!data||data.length<page)break;
      from+=page;
    }
    if(WS_CODE){const ok=await loadWholesalePrices(WS_CODE);   // שחזור מצב סיטונאי: המחירים מהשרת, רק אם הקוד עדיין תקף
      if(!ok){WHOLESALE=false;WS_CODE=null;try{localStorage.removeItem('wholesale_code');}catch(e){}}}
    STOCK_READY=true; pruneUnavailableCart(); updateWsUI(); repriceCart(); buildNav(); renderCart(); render();    // ציור מחדש + תמחור סל למצב הפעיל (סיטונאי/צרכן) אחרי טעינת מחירים
  }catch(e){console.warn('טעינת מלאי נכשלה:',e);}
}
async function loadWholesalePrices(code){   // מחירי סיטונאי — רק מהשרת, תמורת קוד תקף
  if(!SB||!code)return false;
  try{
    const {data,error}=await SB.rpc('wholesale_prices',{p_code:code});
    if(error)throw error;
    if(!data||!data.length)return false;
    data.forEach(r=>{const n=nbc(r.barcode);if(n&&r.price_x3!=null)PRICE_WS[n]=Number(r.price_x3);});
    return true;
  }catch(e){console.warn('שליפת מחירי סיטונאי נכשלה:',e);return false;}
}
function cartItems(){      // [{sku, qty}] עבור create_order (sku = ברקוד מנורמל, תואם DB)
  return Object.keys(CART).map(vid=>{const m=VMAP[vid];return {sku:nbc(m&&m.v.barcode),qty:CART[vid].qty,sold:m&&isSold(m.v)};}).filter(it=>it.sku&&!it.sold).map(({sku,qty})=>({sku,qty}));
}
function syncAgree(){var c=document.getElementById('agreeTerms');var ok=!!(c&&c.checked);['sendBtn','payBtn'].forEach(function(id){var b=document.getElementById(id);if(b)b.classList.toggle('locked',!ok);});}
function validateBuyer(needEmail){
  if(!Object.keys(CART).length){alert(t('alert_empty'));return false;}
  // שדות ריקים נבדקים בשליחה בלבד, והשגיאה נעלמת בהקלדה — לא מציקים
  // ללקוח באמצע המילוי. הבדיקה עוצרת על השדה הראשון שנכשל ומגלגלת אליו.
  ['row-name','row-phone','row-city','row-street','row-house','row-email'].forEach(clearErr);
  let first=null;
  const fail=(row,er,msg)=>{const r=setErr(row,er,msg);if(!first)first=r;};
  const name=gv('buyer-name'),phone=gv('buyer-phone');
  if(!name)fail('row-name','er-name',t('alert_fill'));
  if(!phone)fail('row-phone','er-phone',t('alert_fill'));
  else if(!validPhone(phone))fail('row-phone','er-phone',t('err_phone'));
  if(!gv('buyer-city'))fail('row-city','er-city',t('err_city'));
  if(!gv('buyer-street'))fail('row-street','er-street',t('err_street'));
  // מספר בית נדרש רק ביישוב שיש בו רחובות; בקיבוץ/מושב הכתובת חופשית
  if(CITY&&CITY.s&&!gv('buyer-house'))fail('row-house','er-house',t('err_house'));
  if(first){first.scrollIntoView({block:'center'});const i=first.querySelector('input');if(i)i.focus();return false;}
  // אימייל חובה רק בתשלום באתר — אליו נשלחים אישור פיי פלוס והחשבונית
  if(needEmail){const em=gv('buyer-email');
    if(!em||em.indexOf('@')<1||em.indexOf('.')<0){
      const r=setErr('row-email','er-email',t('alert_email'));
      r.scrollIntoView({block:'center'});document.getElementById('buyer-email').focus();return false;}}
  var ag=document.getElementById('agreeTerms');
  if(!ag||!ag.checked){alert(t('alert_terms'));var w=document.getElementById('agreeWrap');if(w)w.scrollIntoView({block:'center'});if(ag)ag.focus();return false;}
  return true;
}
function setBusy(btn,on){if(!btn)return;if(on){btn.dataset.l=btn.textContent;btn.disabled=true;btn.textContent=t('sending');}else{btn.disabled=false;if(btn.dataset.l)btn.textContent=btn.dataset.l;}}
async function createOrder(channel){   // קריאה אחת ל-create_order → {id,total}. המלאי לא יורד בשלב זה.
  const items=cartItems();
  if(!items.length){alert(t('err_order'));return null;}
  const _sp=shipParts();
  const {data,error}=await SB.rpc('create_order',{
    p_customer_name:gv('buyer-name'),p_customer_phone:gv('buyer-phone'),
    p_customer_email:gv('buyer-email')||'',
    // הסיווג נקבע בשרת לפי קוד הסיטונאי בלבד — הפרמטר נשלח לתאימות ואינו בשימוש
    p_customer_type:'retail',
    p_channel:channel,p_note:noteText(),p_items:items,
    p_ship_city:_sp.city||null,p_ship_city_code:_sp.cityCode,
    p_ship_street:_sp.street||null,p_ship_street_code:_sp.streetCode,
    p_ship_house:_sp.house||null,p_ship_apartment:_sp.apt||null,
    p_ship_floor:_sp.floor||null,p_ship_entrance:_sp.entrance||null,
    p_wholesale_code:(WHOLESALE&&WS_CODE)?WS_CODE:null,     // התמחור נקבע בשרת: קוד תקף = סיטונאי, אחרת צרכן
    p_coupon_code:activeCoupon?activeCoupon.code:null});    // הקופון מאומת ונצרב בשרת (total כבר כולל את ההנחה)
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
  if(!validateBuyer(true))return;
  if(!SB)return;
  const btn=document.getElementById('payBtn');setBusy(btn,true);
  const ord=await createOrder('payment');
  if(!ord){setBusy(btn,false);return;}
  try{
    // 🔒 30/09/2026 — נשלח גם הטלפון. create-checkout המאובטחת משווה אותו
    // (ספרות בלבד) מול orders.customer_phone של אותה הזמנה, וזו ההוכחה שמבקש
    // הקישור הוא מי שיצר את ההזמנה. עד אז הפונקציה ענתה לכל אדם באינטרנט עם
    // order_id בלבד. זהו אותו ערך בדיוק שנשלח שורות קודם ל-create_order כ-
    // p_customer_phone, ולכן ההשוואה תמיד תתאים. הטלפון חובה ומאומת ב-
    // validateBuyer, כך שאין לקוח שנחסם בגלל השדה הזה.
    const {data,error}=await SB.functions.invoke('create-checkout',{body:{order_id:ord.id,phone:gv('buyer-phone')}});
    if(error)throw error;
    if(data&&data.url){window.location.href=data.url;return;}
    throw new Error('no checkout url');
  }catch(e){console.error(e);alert(t('err_order'));setBusy(btn,false);}
}

var __ovReturnFocus=null;
// ⬅️ 12/10 (נמרוד): "אחורה" בטלפון סוגר את החלון הפתוח. כל פתיחה דוחפת רשומה להיסטוריה;
//    חזרה אחורה (popstate) סוגרת את העליון; ✕ עושה history.back() כדי שלא תישאר רשומה מיותרת.
// 🔒 נעילת הדף — יושבת כאן כדי שתועתק גם לדף ההזמנה המהירה (ביקורת 13/10: שם היא הייתה חסרה
//    וכל פתיחת חלון זרקה ReferenceError). drawerOpen סובלני לדף בלי מגירה.
let _lockY=0;
function lockPage(){if(document.body.classList.contains('pglock'))return;   // חלון מעל חלון — נועלים פעם אחת
  _lockY=window.pageYOffset||document.documentElement.scrollTop||0;
  document.body.style.top=(-_lockY)+'px';document.body.classList.add('pglock');}
function anyOvOpen(){return [...document.querySelectorAll('.ov')].some(o=>o.classList.contains('open'));}
function drawerOpen(){const d=document.getElementById('fdrawer');return !!(d&&d.classList.contains('open'));}
function unlockPage(){if(!document.body.classList.contains('pglock'))return;
  if(anyOvOpen()||drawerOpen())return;   // עדיין יש חלון פתוח — נשארים נעולים
  document.body.classList.remove('pglock');document.body.style.top='';window.scrollTo(0,_lockY);}
let _popClosing=false;
function pushOvState(kind,id){try{history.pushState({bf:kind,id:id},'',location.href);}catch(e){}}
function popOvState(kind,id){const st=history.state;if(!_popClosing&&st&&st.bf===kind&&st.id===id){try{history.back();return true;}catch(e){}}return false;}
function ovStateOpen(st){   // האם החלון שברשומת ההיסטוריה באמת פתוח
  if(!st||!st.bf)return false;
  if(st.bf==='drawer')return drawerOpen();
  const m=document.getElementById(st.id);return !!(m&&m.classList.contains('open'));}
window.addEventListener('popstate',function(){
  const st=history.state;
  if(ovStateOpen(st))return;   // עדיין יש חלון פתוח מתחת — לא שלנו לסגור
  _popClosing=true;
  try{
    if(typeof drawerOpen==='function'&&drawerOpen()&&typeof closeDrawer==='function')closeDrawer();
    const zo=document.getElementById('zoomOv');if(zo&&zo.classList.contains('on')&&typeof closeZoom==='function')closeZoom();
    [...document.querySelectorAll('.ov.open')].reverse().forEach(o=>closeOv(o.id));
  }finally{_popClosing=false;}
  if(typeof writeHash==='function')writeHash();   // הכתובת לפי המצב בדף, לא לפי הרשומה שחזרנו אליה
});
// רשומה ישנה שמזכירה חלון (חזרה מדף התשלום / ריענון בזמן שחלון פתוח) — מנקים, אחרת הסגירה הראשונה נבלעת
try{if(history.state&&history.state.bf)history.replaceState(null,'',location.href);}catch(e){}
function closeOvNow(id){const m=document.getElementById(id);if(!m)return;m.classList.remove('open');document.body.style.overflow='';unlockPage();}
function openOv(id){
  __ovReturnFocus=document.activeElement;
  const m=document.getElementById(id); if(m.classList.contains('open'))return; m.classList.add('open'); document.body.style.overflow='hidden';
  pushOvState('ov',id);
  lockPage();   // 📱 12/10: באייפון overflow:hidden לא עוצר את הדף מאחורי "ההזמנה שלי" — נועלים באמת
  // 🔴 ל-.sheet יש overflow-y:auto והוא שומר את מיקום הגלילה מהפעם הקודמת.
  // בלי איפוס, פתיחת מוצר אחרי שגללנו בקודם נוחתת באמצע הכרטיס והלקוח
  // צריך לגלול למעלה כדי לראות את השם ואת התמונה.
  var _sh=m.querySelector('.sheet'); if(_sh)_sh.scrollTop=0;
  m.setAttribute('role','dialog'); m.setAttribute('aria-modal','true');
  const head=m.querySelector('h3,h4'); if(head){if(!head.id)head.id=id+'-h'; m.setAttribute('aria-labelledby',head.id);}
  const sheet=m.querySelector('.sheet')||m; sheet.setAttribute('tabindex','-1');
  setTimeout(function(){const f=m.querySelector('input:not([type=hidden]),.x,button,[tabindex]'); (f||sheet).focus();},40);
}
function closeOv(id){
  const m=document.getElementById(id); if(!m.classList.contains('open'))return;
  if(popOvState('ov',id))return;   // ה-popstate יקרא לנו שוב — ואז נסגור באמת
  m.classList.remove('open'); document.body.style.overflow='';
  unlockPage();
  if(__ovReturnFocus&&__ovReturnFocus.focus){try{__ovReturnFocus.focus();}catch(e){}} __ovReturnFocus=null;
}
// סגירת החלון הפתוח העליון ב-Escape (נגישות מקלדת)
document.addEventListener('keydown',function(e){
  if(e.key!=='Escape')return;
  const open=[...document.querySelectorAll('.ov.open')];
  if(open.length)closeOv(open[open.length-1].id);
});
// ===== store policies (Israeli e-commerce; review with a lawyer) =====
const PNOTE='';  /* internal template/lawyer note removed — not customer-facing */
const POLICIES={
 about:`<h2>אודות</h2>
  <p><b>Beauty Favorites</b> היא חנות אונליין לייבוא ושיווק מוצרי קוסמטיקה, איפור, טיפוח ובושם <b>מקוריים</b> מהמותגים המובילים בעולם.</p>
  <h3>מי אנחנו</h3><p>העסק מופעל על ידי שניר שריקי – יבוא ושיווק מותגי שיער וקוסמטיקה (עוסק מורשה 040553562). אנו מתמחים באספקת מוצרי יופי מקוריים במחירים משתלמים — ללקוחות פרטיים ולעסקים (מספרות, מאפרות וחנויות).</p>
  <h3>תחום העיסוק</h3><p>מכירה קמעונאית וסיטונאית של מוצרי איפור, טיפוח העור, טיפוח השיער, בשמים ואביזרי יופי. כל המוצרים מקוריים ומגיעים ממקורות מורשים בלבד.</p>
  <h3>יצירת קשר</h3><p>טלפון ווואטסאפ: <a href="tel:0534555501">053-4555501</a> · אימייל: <a href="mailto:beautyfavorites2026@gmail.com">beautyfavorites2026@gmail.com</a></p>`,
 contact:`<h2>פרטי העסק ויצירת קשר</h2>
  <p><b>שניר שריקי</b> – יבוא ושיווק מותגי שיער וקוסמטיקה</p>
  <p>עוסק מורשה: 040553562</p>
  <h3>יצירת קשר</h3>
  <p>טלפון: <a href="tel:0534555501">053-4555501</a></p>
  <p>אימייל: <a href="mailto:beautyfavorites2026@gmail.com">beautyfavorites2026@gmail.com</a></p>
  <p>הזמנות בוואטסאפ: <a href="https://wa.me/972534555501">053-4555501</a></p>
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
  <h3>אופן ההחזר</h3><p>ליצירת בקשת ביטול/החזרה: טלפון 053-4555501 או אימייל beautyfavorites2026@gmail.com. ההחזר הכספי יבוצע באמצעי התשלום המקורי בניכוי דמי ביטול כדין (אם חלים).</p>`,
 terms:`<h2>תקנון האתר</h2>${PNOTE}
  <h3>כללי</h3><p>האתר מופעל על ידי שניר שריקי – יבוא ושיווק מותגי שיער וקוסמטיקה (עוסק מורשה 040553562) ("העסק"). השימוש באתר ובהזמנה כפוף לתקנון זה.</p>
  <h3>המוצרים</h3><p>האתר מציע מוצרי קוסמטיקה וטיפוח מקוריים. תמונות המוצרים להמחשה בלבד וייתכנו הבדלי גוון/אריזה. המחירים בשקלים חדשים וכוללים מע״מ.</p>
  <h3>הזמנות</h3><p>שליחת הזמנה מהווה הצעה לרכישה; העסק רשאי לאשר או לדחות הזמנה, ולעדכן מחירים וזמינות מלאי. ההזמנה תיחשב כמאושרת רק לאחר אישור העסק.</p>
  <h3>מדיניות שילוח ואספקה</h3><p>ההזמנות נשלחות באמצעות חברת שליחויות. זמן האספקה עד 72 שעות מרגע איסוף החבילה ע״י השליח (בימי עסקים). משלוח חינם בהזמנה מעל ₪299; מתחת לכך יגבו דמי משלוח כמפורט בעת ההזמנה. משלוחים לכל הארץ (ראו גם עמוד "משלוחים ואספקה").</p>
  <h3>ביטול עסקה והחזר כספי</h3><p>הלקוח זכאי לבטל עסקה ולהחזיר מוצר תוך 14 יום ממועד קבלתו, בהתאם לחוק הגנת הצרכן, התשמ״א-1981. המוצר יוחזר חדש, באריזתו המקורית וללא שימוש (מטעמי היגיינה ייתכנו הגבלות על מוצרי קוסמטיקה/טיפוח שנפתחו). ההחזר הכספי יבוצע באמצעי התשלום המקורי בניכוי דמי ביטול כדין, אם חלים. הלקוח יקבל את המוצר שרכש, ובמקרה של אי-אספקה — יקבל את כספו חזרה (ראו גם עמוד "החזרות וביטולים").</p>
  <h3>אחריות בית העסק</h3><p>העסק אחראי לתוכן המוצג באתר, לפעולות המתבצעות בו, למכירה, לשירות ולאספקה, בהתאם לדין. אחריות המוצר עצמו היא של היצרן/היבואן בהתאם לדין. תמונות המוצרים להמחשה בלבד.</p>
  <h3>הגנת הפרטיות</h3><p>העסק שומר על פרטיות לקוחותיו. פרטי הלקוח נאספים לצורך ביצוע ההזמנה ואספקתה בלבד, אינם נמכרים, ונמסרים לחברת השליחויות ולספק הסליקה אך ורק לצורך השלמת ההזמנה. האתר פועל בחיבור מוצפן, פרטי כרטיס האשראי מוקלדים ישירות מול חברת סליקה מאובטחת בתקן PCI-DSS ואינם נשמרים אצלנו, והגישה לפרטי ההזמנות מוגבלת לעובדים מורשים בלבד (ראו מדיניות פרטיות מלאה).</p>
  <h3>הבהרה מותגית</h3><p>העסק פועל כמשווק עצמאי של מוצרים מקוריים בלבד, ואינו קשור, מטעמן או בשיתוף עם הרשתות או המותגים המוצגים באתר. שמות המותגים מופיעים לצורך זיהוי המוצרים בלבד, וכל הסימנים המסחריים שייכים לבעליהם.</p>`,
 accessibility:`<h2>הצהרת נגישות</h2>
  <p>אנו רואים חשיבות רבה במתן שירות שוויוני לכלל הלקוחות, ובכלל זה אנשים עם מוגבלות, ופועלים להנגשת האתר בהתאם לתקנות שוויון זכויות לאנשים עם מוגבלות (התאמות נגישות לשירות), התשע"ג-2013, ולתקן הישראלי ת"י 5568 ברמה AA (מבוסס WCAG 2.1).</p>
  <h3>התאמות הנגישות באתר</h3>
  <ul>
    <li>מבנה עמוד סמנטי ותמיכה מלאה בניווט מקלדת.</li>
    <li>תוויות טקסט (aria-label) לכפתורים ולרכיבים אינטראקטיביים.</li>
    <li>ניגודיות צבעים תקינה בין טקסט לרקע.</li>
    <li>טקסט ניתן להגדלה באמצעות הדפדפן ללא פגיעה בתצוגה.</li>
    <li>הפחתת אנימציות אוטומטית למשתמשים שהגדירו העדפת צמצום תנועה.</li>
    <li>האתר זמין בעברית ובערבית.</li>
  </ul>
  <h3>הסתייגות</h3>
  <p>אנו ממשיכים לפעול לשיפור נגישות האתר באופן שוטף. ייתכן שיימצאו רכיבים שטרם הונגשו במלואם; נשמח לקבל פנייה ונטפל בה בהקדם.</p>
  <h3>רכז הנגישות</h3>
  <p>שניר שריקי</p>
  <p>טלפון: <a href="tel:0534555501">053-4555501</a> · אימייל: <a href="mailto:beautyfavorites2026@gmail.com">beautyfavorites2026@gmail.com</a></p>
  <p>הצהרת הנגישות עודכנה לאחרונה: יולי 2026.</p>`,
 privacy:`<h2>מדיניות פרטיות</h2>${PNOTE}
  <h3>איסוף מידע</h3><p>לצורך ביצוע הזמנה ואספקתה נאספים פרטים: שם, טלפון, כתובת ופרטי הזמנה.</p>
  <h3>שימוש במידע</h3><p>המידע משמש לעיבוד ההזמנה, אספקה, שירות לקוחות ויצירת קשר בנוגע להזמנה.</p>
  <h3>כיצד אנו שומרים על פרטיות הלקוח ועל אבטחת המידע</h3>
  <p>אנו נוקטים באמצעי אבטחה מקובלים כדי להגן על המידע שנמסר לנו:</p>
  <ul>
    <li><strong>הצפנה בתקשורת:</strong> כל הגלישה באתר וכל שליחת הזמנה מתבצעות בחיבור מוצפן (HTTPS/SSL) בתעודה תקפה, כך שהמידע מוצפן בדרכו מהמכשיר של הלקוח אל השרת ואינו ניתן לצפייה בידי גורם שלישי.</li>
    <li><strong>פרטי אשראי אינם נשמרים אצלנו כלל:</strong> התשלום מתבצע בעמוד סליקה מאובטח של חברת הסליקה המורשית, העומדת בתקן אבטחת המידע הבינלאומי של חברות האשראי (PCI-DSS). מספר הכרטיס, תוקפו וקוד האבטחה מוקלדים ישירות מול חברת הסליקה, אינם עוברים דרך שרתי האתר ואינם נשמרים במאגרי העסק בשום שלב.</li>
    <li><strong>אחסון מאובטח והרשאות גישה:</strong> פרטי ההזמנות נשמרים בשרת ענן מאובטח, כשהגישה אליהם מוגנת בסיסמה ומוגבלת אך ורק לבעל העסק ולעובדים מורשים לפי הרשאות אישיות. פעולות במערכת נרשמות ביומן פעילות פנימי המאפשר מעקב ובקרה.</li>
    <li><strong>מזעור מידע ושמירתו לזמן הנדרש בלבד:</strong> נאספים רק הפרטים הדרושים לביצוע ההזמנה ואספקתה. המידע נשמר לפרק הזמן הנדרש לצורך השירות, האחריות והחובות החוקיות החלות על העסק, ולאחר מכן נמחק או מאוחסן באופן מצומצם בלבד.</li>
    <li><strong>ללא דיוור ללא הסכמה:</strong> איננו עושים שימוש בפרטי הלקוח לצורך פרסום או דיוור שיווקי ללא הסכמתו המפורשת, וניתן להסיר את ההסכמה בכל עת.</li>
  </ul>
  <h3>העברה לצד שלישי</h3><p>המידע אינו נמכר, אינו מושכר ואינו מועבר לצדדים שלישיים לצרכים מסחריים. הוא עשוי להימסר לחברת השליחויות ולספק הסליקה אך ורק במידה הנדרשת להשלמת ההזמנה ואספקתה, וכן לרשות מוסמכת ככל שהדבר נדרש על פי דין.</p>
  <h3>זכויות הלקוח</h3><p>כל לקוח רשאי לפנות אלינו בבקשה לעיין בפרטים השמורים לגביו, לתקנם או לבקש את מחיקתם, ואנו נטפל בפנייה בהקדם.</p>
  <h3>יצירת קשר בנושאי פרטיות</h3><p>שניר שריקי · טלפון: <a href="tel:0534555501">053-4555501</a> · אימייל: <a href="mailto:beautyfavorites2026@gmail.com">beautyfavorites2026@gmail.com</a></p>
  <p>מדיניות הפרטיות עודכנה לאחרונה: יולי 2026.</p>`,
};
// 🌐 06/10/2026 — מסמכי המדיניות בערבית (תרגום צ'אט המחקר, נאמן ולא ניסוח מחדש;
//    בראש כל מסמך: "הנוסח העברי הוא הקובע"). נטען מקובץ בבנייה; מסמך שחסר
//    בערבית נופל לעברית — לעולם לא לחלון ריק.
const POLICIES_AR=/*__POLICIES_AR__*/;
function openPolicy(k){var b=document.getElementById('policyBody');if(b)b.innerHTML=((LANG==='ar'&&POLICIES_AR[k])||POLICIES[k]||'');openOv('policyModal');}
document.querySelectorAll('.ov').forEach(ov=>ov.addEventListener('click',e=>{if(e.target===ov)closeOv(ov.id)}));
// ---- תוויות נגישות חד-פעמיות ----
document.querySelectorAll('.ov .x, .wachat .wx').forEach(b=>{if(!b.getAttribute('aria-label'))b.setAttribute('aria-label','סגור');});
(function(){var q=document.getElementById('q');if(q&&!q.getAttribute('aria-label'))q.setAttribute('aria-label','חיפוש מוצר, מותג או ברקוד');
  var bs=document.getElementById('brandSearch');if(bs)bs.setAttribute('aria-label','חיפוש מותג');})();
document.addEventListener('touchstart',()=>{if(![...document.querySelectorAll('.ov')].some(o=>o.classList.contains('open'))&&!(typeof drawerOpen==='function'&&drawerOpen()))document.body.style.overflow=''},{passive:true});

function goTop(){window.scrollTo(0,0);document.documentElement.scrollTop=0;document.body.scrollTop=0;}
window.addEventListener('scroll',()=>{
  var y=window.pageYOffset||document.documentElement.scrollTop||0;
  document.getElementById('toTop').classList.toggle('show',y>420);
  if(window.innerHeight+y > document.body.offsetHeight-900) loadMore();   // infinite scroll
},{passive:true});

applyStatic();
(function(){var pb=document.getElementById('promobar');if(!pb)return;
  var set=function(){document.documentElement.style.setProperty('--pbh',pb.offsetHeight+'px');};
  set();window.addEventListener('resize',set,{passive:true});
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(set);})();
// שחזור לפני הציור הראשון, כדי שסרגל הסל יופיע מלא מיד
restoreCart(); restoreBuyer();
if(applyHash())buildNav();   // 🔗 קישור עמוק לקטגוריה — לפני הציור הראשון
render();
if(SB){var _pb=document.getElementById('payBtn');if(_pb)_pb.style.display='';loadStock();}
// חזרה מדף התשלום של פיי פלוס (?pay=success/failure&order=N) — הודעה וניקוי הכתובת
(function(){
  try{
    var q=new URLSearchParams(location.search), st=q.get('pay');
    if(!st)return;
    var oid=q.get('order')||'';
    history.replaceState(null,'',location.pathname);
    setTimeout(function(){alert(t(st==='success'?'pay_ok':'pay_fail').replace('{id}','#'+oid));},300);
  }catch(e){}
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
