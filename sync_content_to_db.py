#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סנכרון תוכן: קבצי הידע (knowledge/) → מסד הנתונים (products) — שלב חובה אחרי כל העשרה.

דוחף שדות תוכן בלבד דרך RPC מאובטח (sync_product_content):
  description (חדש מנצח) · brand · category · main_category · name_he (רק לכרטיס דק, או עם --force-names)
  · name_en (רק אם ריק, או עם --force-text) · image_url (רק אם ריק, או עם --force-images / --force-text)
  · category_slug + sub_type (עץ הקטגוריות — **רק כשריק במסד**, ללא דגל דריסה; מ-19/10)
  · attrs (תכונות הסינון — רק כשריקות במסד; רק מפתחות/ערכים מ-ATTR_ALLOWED; מ-19/10)
לעולם לא נוגע ב: מחירים, מלאי, sku, active.

🔴 תוקן 09/09/2026 — הקטגוריה הראשית נדרסה בכל סנכרון (ראה fetch_existing_main).
   מעכשיו: ערך קיים במסד נשמר, וגזירה מהשם קורית רק לכרטיס שאין לו קטגוריה.

שימוש:
  python3 catalog/sync_content_to_db.py                  # כל המוצרים שבידע
  python3 catalog/sync_content_to_db.py 0123... 0456...  # ברקודים מסוימים בלבד
  python3 catalog/sync_content_to_db.py --force-names 0123...  # גם דריסת שם עברי לברקודים אלה
  python3 catalog/sync_content_to_db.py --force-images 0123... # גם דריסת כתובת התמונה (למשל אחרי שינוי שם תיקיית כרטיס)
  python3 catalog/sync_content_to_db.py --force-text 0123...   # דריסת כל שדות הטקסט המוגנים (name_he, name_en, image_url) — נרשם ביומן
  (אפשר את שני הדגלים יחד; כל דגל חל על הברקודים שאחריו עד הדגל הבא)

דרישות: backoffice/.sync-env עם CONTENT_SYNC_SECRET (מקומי, לא בריפו).
"""
import json, os, re, sys, glob, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOW = os.path.join(ROOT, "knowledge")
# כתובת הבסיס של האתר החי — ממנה נבנית כתובת התמונה שנשלחת למסד
SITE = "https://beautyfavorites.co.il"
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
CATALOG = os.path.join(ROOT, "catalog")

def load_env():
    env = {}
    path = os.path.join(ROOT, "backoffice", ".sync-env")
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    cfg = json.load(open(os.path.join(CATALOG, "supabase.config.json"), encoding="utf-8"))
    env["URL"] = cfg.get("url") or cfg.get("SUPABASE_URL")
    env["ANON"] = cfg.get("anonKey") or cfg.get("anon_key") or cfg.get("SUPABASE_ANON_KEY")
    return env

def digits(v):
    return re.sub(r"\D", "", str(v or ""))

# מיפוי קטגוריה ראשית — אותה לוגיקה כמו build_catalog.ptype (ייבוא ישיר)
sys.path.insert(0, CATALOG)
from build_catalog import ptype, norm_brand, brand_from_name  # noqa: E402

def fetch_existing_main(env):
    """הקטגוריה הראשית הקיימת במסד, לפי ברקוד מנורמל.

    🔴 נוסף 09/09/2026 אחרי באג: השורה הייתה `"main_category": ptype(p)` — כלומר
    **הקטגוריה חושבה מחדש מהשם בכל סנכרון ודרסה את מה שנקבע בבק אופיס.**
    בפועל אף קובץ ידע אינו נושא `category_main` (הוא נקבע רק בזיכרון בזמן בנייה),
    ולכן `ptype()` תמיד ניצח. מדידה מ-09/09: סנכרון מלא היה משנה קטגוריה
    ל-35 מוצרים, 19 מהם פעילים ובמלאי — וברובם **ערך המסד היה הנכון**
    (מאק סטרוב קרים טיפוח→איפור · מברשת מורפי איפור→אביזרים · ערכות מורד).

    ה-RPC כבר בנוי נכון: `coalesce(nullif(v_row->>'main_category',''), p.main_category)`
    — **מחרוזת ריקה אינה דורסת.** לכן די בשליחת ריק כדי לשמר ערך קיים.
    """
    out, offset = {}, 0
    while True:
        url = (env["URL"] + "/rest/v1/catalog_content"
               "?select=barcode,main_category&limit=1000&offset=" + str(offset))
        req = urllib.request.Request(url, headers={
            "apikey": env["ANON"], "Authorization": "Bearer " + env["ANON"]})
        page = json.load(urllib.request.urlopen(req, timeout=60))
        for r in page:
            out[digits(r.get("barcode"))] = (r.get("main_category") or "").strip()
        if len(page) < 1000:
            return out
        offset += 1000

def first_image_url(card_dir):
    """כתובת התמונה הראשית של הכרטיס באתר החי.

    🔴 תוקן 04/10/2026: הסקריפט הצהיר בתיעוד שהוא מסנכרן `image_url`, אבל
    השדה **מעולם לא נכלל במטען** שנשלח ל-RPC. בצד השרת הכול היה תקין
    (`coalesce(nullif(v_row->>'image_url',''), p.image_url)`), ולכן הכתיבה
    פשוט לא קרתה ואיש לא הבחין — כל כרטיס חדש הגיע למסד בלי תמונה ונשאר
    מוסתר באתר. התגלה על ידי צ'אט הניהול אחרי שסנכרון החזיר 7/7 ו-image_url
    נשאר ריק בכל השבעה.

    התמונה הראשית היא **הקובץ הראשון בסדר אלפביתי** — בדיוק מה ש-
    build_catalog.py בוחר, ולכן השתיים תמיד מסכימות.
    """
    d = os.path.join(KNOW, card_dir, "images")
    if not os.path.isdir(d):
        return ""
    # ☁️ 19/10/2026 (המחקר) — אותו סינון כמו בבנייה (מ-12/10): כפילויות אייקלאוד ("01 2.jpg") ותמונות
    #    שהוסתרו (catalog/hidden_images.json) לא נבנות לאתר — ולכן כתובת אליהן היא 404. ב-14 כרטיסים
    #    הקובץ הראשון אלפביתית היה כפילות; --force-images/--force-text היו כותבים כתובת שבורה.
    hidden = _hidden_images().get(card_dir, {})
    files = sorted(f for f in os.listdir(d)
                   if f.lower().endswith(IMG_EXT) and not re.search(r" \d+\.[a-z]+$", f, re.I) and f not in hidden)
    return f"{SITE}/images/{card_dir}/{files[0]}" if files else ""


_HIDDEN = None
def _hidden_images():
    """catalog/hidden_images.json — אותה רשימה שהבנייה מדלגת עליה ({תיקיית כרטיס: {קובץ: סיבה}})."""
    global _HIDDEN
    if _HIDDEN is None:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hidden_images.json"), encoding="utf-8") as fh:
                _HIDDEN = {k: v for k, v in json.load(fh).items() if not k.startswith("_") and isinstance(v, dict)}
        except Exception:
            _HIDDEN = {}
    return _HIDDEN


_SLUGS = None
def valid_slugs():
    """הסלאגים הקיימים בעץ (טבלת categories, קריאה ציבורית).
    🔴 19/10/2026 — category_slug הוא מפתח זר: סלאג שגוי אחד בכרטיס מפיל את **כל**
    האצווה של ה-RPC (200 מוצרים). לכן מסננים כאן, ומדווחים במקום לשבור.
    שליפה שנכשלה → קבוצה ריקה → לא שולחים סלאג כלל (בטוח: רק מדלג)."""
    global _SLUGS
    if _SLUGS is None:
        try:
            cfg = json.load(open(os.path.join(CATALOG, "supabase.config.json"), encoding="utf-8"))
            req = urllib.request.Request(cfg["url"] + "/rest/v1/categories?select=slug",
                                         headers={"apikey": cfg["anon_key"]})
            _SLUGS = {r["slug"] for r in json.load(urllib.request.urlopen(req, timeout=30))}
        except Exception as e:
            print("⚠️ רשימת הקטגוריות לא נקראה — category_slug לא יישלח בסבב הזה:", e)
            _SLUGS = set()
    return _SLUGS


BAD_SLUGS = []

# 🎛️ 19/10/2026 — תכונות הסינון (attrs). המפתחות כפי שהם **במסד** (לא extra/st של האתר:
#    extra = wear + ethics בתצוגה, st בא מ-sub_type). הערכים — ATTR_ORDER ב-build_catalog.py.
ATTR_ALLOWED = {
    "finish":   ["מאט", "טבעי", "סאטן", "זוהר", "שימרי", "מטאלי"],
    "coverage": ["קל", "בינוני", "מלא", "ניתן לבנייה"],
    "skin":     ["יבש", "שמן", "מעורב", "רגיש"],
    "tone":     ["שקופה", "בגוון"],
    "wear":     ["עמיד למים", "ארוך טווח"],
    "ethics":   ["טבעוני", "ללא אכזריות"],
}
BAD_ATTRS = []

def clean_attrs(bc, raw):
    """רק מפתחות וערכים מהרשימה; כל השאר מדולג ומודפס (לא שובר את האצווה). {} → None."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k, vals in raw.items():
        if k not in ATTR_ALLOWED:
            BAD_ATTRS.append((bc, k, vals)); continue
        vals = vals if isinstance(vals, list) else [vals]
        good = [v.strip() for v in vals if isinstance(v, str) and v.strip() in ATTR_ALLOWED[k]]
        for v in vals:
            if not (isinstance(v, str) and v.strip() in ATTR_ALLOWED[k]):
                BAD_ATTRS.append((bc, k, v))
        if good:
            out[k] = sorted(set(good), key=ATTR_ALLOWED[k].index)
    return out or None

def collect_rows(only_barcodes=None, force_names=None, existing_main=None, force_images=None, force_text=None):
    rows, seen = [], set()
    for pj in glob.glob(os.path.join(KNOW, "*", "product.json")):
        try:
            p = json.load(open(pj, encoding="utf-8"))
        except Exception as e:
            print("skip", pj, e); continue
        bc = digits(p.get("barcode"))
        if not bc or bc in seen:
            continue
        if only_barcodes and bc not in only_barcodes:
            continue
        seen.add(bc)
        brand = norm_brand(p.get("brand"))
        if brand == "אחר":
            brand = brand_from_name(p.get("name_he") or "")
        row = {
            "barcode": bc,
            "description": (p.get("description") or "").strip(),
            "brand": ("" if brand == "אחר" else brand).strip(),
            "category": (p.get("category_refined") or "").strip(),
            # קטגוריה ראשית — שלוש מדרגות, מהמפורש לנגזר:
            #   1. ערך מפורש בקובץ הידע — מנצח תמיד
            #   2. יש כבר ערך במסד — שולחים ריק, וה-RPC משאיר אותו כמות שהוא
            #   3. אין כלום — רק אז נגזר מהשם, כדי למלא כרטיס חדש
            "main_category": (
                (p.get("category_main") or "").strip()
                or ("" if (existing_main or {}).get(bc) else ptype(p))
            ),
            "name_he": (p.get("name_he") or "").strip(),
            # 🔤 19/10/2026 (המחקר): name_en לא נשלח בכלל — ה-RPC ידע לקבל אותו ונשאר ריק. נכתב רק כשריק במסד, או עם --force-text
            "name_en": (p.get("name_en") or "").strip(),
            # תמונה ראשית — ה-RPC כותב אותה **רק אם השדה במסד ריק**,
            # ולכן זה לעולם לא ידרוס תמונה שנבחרה ידנית בבק אופיס.
            "image_url": first_image_url(os.path.basename(os.path.dirname(pj))),
        }
        # 🗂️ 19/10/2026 (בקשת הניהול) — העשרה קובעת את מקום המוצר בעץ (כלל 06/10). ה-RPC כותב
        #    את שניהם **רק כשריקים במסד** — אחרי שנקבעו, הבק אופיס הוא מקור האמת. אין דגל דריסה.
        slug = (p.get("category_slug") or "").strip()
        if slug:
            if slug in valid_slugs():
                row["category_slug"] = slug
            elif valid_slugs():
                BAD_SLUGS.append((bc, slug))
        sub = (p.get("sub_type") or "").strip()
        if sub:
            row["sub_type"] = sub
        # 🎛️ תכונות סינון — ה-RPC כותב **רק כשריקות במסד**; אין דגל דריסה
        at = clean_attrs(bc, p.get("attrs"))
        if at:
            row["attrs"] = at
        if force_names and bc in force_names:
            row["force_name"] = "1"
        # 🖼️ 18/10/2026 — דריסת כתובת התמונה (ה-RPC כותב אותה רק עם הדגל, או כשהיא ריקה)
        if force_images and bc in force_images and row.get("image_url"):
            row["force_image"] = "1"
        # 🧾 19/10/2026 — דגל אחד לכל השדות המוגנים; מה שנדרס נרשם ביומן הפעולות (content_changed)
        if force_text and bc in force_text:
            row["force_text"] = "1"
        rows.append(row)
    return rows

def push(env, rows, batch=200):
    total_updated = total_missing = 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        body = json.dumps({"p_secret": env["CONTENT_SYNC_SECRET"], "p_rows": part}).encode()
        req = urllib.request.Request(
            env["URL"] + "/rest/v1/rpc/sync_product_content", data=body, method="POST",
            headers={"apikey": env["ANON"], "Authorization": "Bearer " + env["ANON"],
                     "Content-Type": "application/json"})
        res = json.load(urllib.request.urlopen(req, timeout=60))
        total_updated += res.get("updated", 0)
        total_missing += res.get("missing", 0)
        print(f"  אצווה {i//batch+1}: עודכנו {res.get('updated',0)}, לא נמצאו במסד {res.get('missing',0)}")
    return total_updated, total_missing

def main():
    # דגלים: כל דגל חל על הברקודים שאחריו עד הדגל הבא; ברקודים לפני כל דגל = "רק אלה"
    groups, cur = {"": []}, ""
    for a in sys.argv[1:]:
        if a in ("--force-names", "--force-images", "--force-text"):
            cur = a; groups.setdefault(cur, []); continue
        groups[cur].append(a)
    force = set(digits(a) for a in groups.get("--force-names", []))
    force_img = set(digits(a) for a in groups.get("--force-images", []))
    force_txt = set(digits(a) for a in groups.get("--force-text", []))
    only = set(digits(a) for a in groups[""]) or None
    if (force or force_img or force_txt) and not only:
        only = force | force_img | force_txt
    env = load_env()
    existing_main = fetch_existing_main(env)
    print(f"נקראו {len(existing_main)} קטגוריות קיימות מהמסד — הן לא יידרסו.")
    rows = collect_rows(only, force, existing_main, force_img, force_txt)
    if force_txt:
        print(f"🧾 דריסת כל שדות הטקסט ל-{sum(1 for r in rows if r.get('force_text'))} ברקודים (נרשם ביומן הפעולות)")
    if force_img:
        print(f"🖼️ דריסת כתובת תמונה ל-{sum(1 for r in rows if r.get('force_image'))} ברקודים")
    kept = sum(1 for r in rows if not r["main_category"])
    if kept:
        print(f"  🛡️  {kept} מוצרים ישמרו את הקטגוריה הקיימת שלהם.")
    if not rows:
        print("אין שורות לדחיפה."); return
    if BAD_SLUGS:
        print(f"⚠️ {len(BAD_SLUGS)} כרטיסים עם קטגוריה שאינה בעץ — לא נשלחה (לתקן בכרטיס):")
        for bc, sl in BAD_SLUGS[:20]:
            print(f"   {bc} → {sl}")
    if BAD_ATTRS:
        print(f"⚠️ {len(BAD_ATTRS)} תכונות סינון לא מוכרות — לא נשלחו (לתקן בכרטיס):")
        for bc, k, v in BAD_ATTRS[:20]:
            print(f"   {bc} → {k}: {v}")
    n_attrs = sum(1 for r in rows if r.get("attrs"))
    if n_attrs:
        print(f"🎛️ {n_attrs} מוצרים נושאים תכונות סינון — ייכתבו רק למי שעדיין ריק במסד")
    n_tree = sum(1 for r in rows if r.get("category_slug") or r.get("sub_type"))
    if n_tree:
        print(f"🗂️ {n_tree} מוצרים נושאים מקום בעץ — ייכתב רק למי שעדיין ריק במסד")
    print(f"דוחף תוכן ל-{len(rows)} מוצרים…")
    updated, missing = push(env, rows)
    print(f"✅ סונכרן: {updated} עודכנו · {missing} ברקודים לא קיימים במסד (תקין למוצרים שטרם נקלטו)")

if __name__ == "__main__":
    main()
