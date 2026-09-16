#!/usr/bin/env python3
"""בדיקות לדף ההזמנה המהירה (order.html) — 16/09/2026.

הרצה:  python3 catalog/test_order_page.py -v
בלי pytest (אינו מותקן) — unittest מהספרייה הסטנדרטית. הבנאי נטען כמודול
בלי להריץ את main(), כמו ב-build_demo.py.
"""
import importlib.util, json, os, re, subprocess, sys, unittest, glob

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("bc", os.path.join(HERE, "build_catalog.py"))
bc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bc)

CFG = {"url": "https://x.supabase.co", "anon": "sb_publishable_test"}


def fake_groups():
    return [
        {"gid": "g0", "name_he": "רייר ביוטי – סומק", "brand": "רייר ביוטי", "type": "איפור", "variants": [
            {"id": "p1", "shade": "Love", "price": 150, "sale": None, "was": None, "size": "2.8 גרם",
             "barcode": "840122906626", "imgs": ["images/p1/01.jpg", "images/p1/02.jpg"],
             "desc": "סומק פודרה זוהר. עמיד לאורך היום.", "summary": "סומק אבקתי עם גימור זוהר"},
            {"id": "p2", "shade": "Joy", "price": 150, "sale": None, "was": None, "size": "2.8 גרם",
             "barcode": "840122906602", "imgs": [], "desc": "בלי שורה מקדימה. משפט שני."},
        ]},
        {"gid": "g1", "name_he": "הודה ביוטי – פריימר", "brand": "הודה ביוטי", "type": "איפור", "variants": [
            {"id": "p3", "shade": "", "price": 200, "sale": None, "was": None, "size": "",
             "barcode": "6294018405696", "imgs": ["images/p3/01.jpg"], "desc": ""},
        ]},
    ]


class LeadLine(unittest.TestCase):
    def test_summary_wins(self):
        self.assertEqual(bc._lead({"summary": "שורה מקדימה", "desc": "תיאור ארוך."}), "שורה מקדימה")

    def test_fallback_first_sentence(self):
        self.assertEqual(bc._lead({"desc": "בלי שורה מקדימה. משפט שני."}), "בלי שורה מקדימה.")

    def test_truncated_at_limit(self):
        s = bc._lead({"desc": "א" * 300})
        self.assertLessEqual(len(s), 120)
        self.assertTrue(s.endswith("…"))

    def test_empty(self):
        self.assertEqual(bc._lead({}), "")


class OrderPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = bc.build_order_page(fake_groups(), CFG, "https://beautyfavorites.co.il")
        m = re.search(r"const GROUPS = (\[.*?\]);\n", cls.html, re.S)
        cls.data = json.loads(m.group(1))

    def test_rows_and_fields(self):
        vs = [v for g in self.data for v in g["variants"]]
        self.assertEqual(len(vs), 3)
        self.assertEqual(vs[0]["lead"], "סומק אבקתי עם גימור זוהר")
        self.assertEqual(vs[1]["lead"], "בלי שורה מקדימה.")
        self.assertEqual(vs[2]["lead"], "")
        self.assertEqual(vs[0]["imgs"], ["images/p1/01.jpg"])        # תמונה אחת בלבד
        self.assertNotIn("desc", vs[0])                                 # התיאור לא נשלח לדף
        self.assertEqual(vs[0]["barcode"], "840122906626")

    def test_shares_the_site_code(self):
        h = self.html
        for needle in ("972534555501", "SB.rpc('create_order'", "createOrder('whatsapp')", "'bf_cart_v1'",
                       "SB.rpc('wholesale_prices'", "function priceHtml(v,cls)", "t('cons_rec')",
                       "from('catalog_products')", "function buildOrderText(orderId)"):
            self.assertIn(needle, h, needle)
        self.assertNotIn("function payNow", h)                          # תשלום באתר — לא כאן
        self.assertNotIn("applyCoupon(", h.split("// ===== עד כאן קוד האתר")[1])

    def test_page_shell(self):
        h = self.html
        self.assertIn('name="robots" content="noindex', h)
        self.assertIn('window.SUPA={"url": "https://x.supabase.co"', h)
        self.assertIn("function readLinkParams()", h)
        self.assertIn('id="pbWholesale"', h)
        self.assertIn("qo-lead", h)
        self.assertIn('id="clubModal"', h)                              # חלון הקוד הסיטונאי מהאתר
        self.assertIn("shipParts(){return {city:null,cityCode:null", h)   # כל הארגומנטים ל-create_order
        self.assertTrue(h.strip().endswith("</html>"))
        self.assertNotIn("/*__", h)                                     # אין מציין מקום שלא הוחלף

    def test_missing_anchor_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            bc._slice("abc", "zzz", "c")


class RealBuild(unittest.TestCase):
    """בנייה אמיתית (--fast) לתיקייה תחת הבית — לא נוגעת ב-catalog/index.html."""
    OUT = os.path.expanduser("~/bf-test-build/unittest")

    def test_build_writes_order_html_with_a_real_summary(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, "build_catalog.py"), "--fast", "--out", self.OUT],
                           capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        path = os.path.join(self.OUT, "order.html")
        self.assertTrue(os.path.exists(path))
        h = open(path, encoding="utf-8").read()
        self.assertIn("✅ order.html", r.stdout)
        # מוצר אמיתי עם summary — השורה המקדימה שלו חייבת להופיע בדף
        found = None
        for f in sorted(glob.glob(os.path.join(bc.ROOT, "knowledge", "*", "product.json")))[:400]:
            d = json.load(open(f, encoding="utf-8"))
            s = str(d.get("summary") or "").strip()
            if 20 < len(s) < 100 and "\\" not in s and '"' not in s:
                found = s; break
        self.assertIsNotNone(found)
        self.assertIn(json.dumps(found, ensure_ascii=False)[1:-1][:40], h)


if __name__ == "__main__":
    unittest.main()
