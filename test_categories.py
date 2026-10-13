#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בדיקות ל-index.html הבנוי — עץ הקטגוריות **ותנאי הפרסום** (06/10/2026).

מריצים על קובץ בנוי:
    python3 catalog/build_catalog.py --fast --out ~/bf-preview/תצוגה-מקדימה
    python3 catalog/test_categories.py ~/bf-preview/תצוגה-מקדימה/index.html

**שתי משפחות בדיקה, ולכל אחת סיבה אחרת:**

1. **העץ** — שהניווט החדש באמת מגיע לדף ולא רק לקוד. עץ שלא נשלף בבנייה
   נכשל **בשקט**: הדף נבנה, נראה תקין, ופשוט חוזר לקטגוריות השטוחות.

2. **🔴 פרטי העסק והסליקה** — נדרשו במפורש (נמרוד דרך צ'אט הניהול, 06/10).
   הם יושבים באותה תבנית ענקית שאנחנו עורכים, ולכן **הנחה שהם "לא זזים"
   אינה ראיה**. חוק רשות המיסים מחייב שם עוסק ומספר; בלי תיבת אישור התקנון
   אין הסכמה לתנאי מכר; בלי "המחירים כוללים מע"מ" המחיר מטעה. כל אחד מהם
   לבדו מספיק כדי לעצור פרסום — ולכן הם בדיקה ולא זיכרון.
"""
import io, os, re, sys, unittest

PATH = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-')
        else os.path.expanduser('~/bf-preview/תצוגה-מקדימה/index.html'))
HTML = io.open(PATH, encoding='utf-8').read()


class Base(unittest.TestCase):
    def has(self, needle, why):
        self.assertTrue(needle in HTML, f'חסר בדף: {why}  ({needle!r})')


class TreeTest(Base):
    """העץ הגיע לדף."""

    def tree(self):
        import json
        i = HTML.index('const CATTREE = ') + len('const CATTREE = ')
        return json.JSONDecoder().raw_decode(HTML[i:])[0]

    def test_tree_not_empty(self):
        # 🔑 הכישלון השקט: בלי רשת בבנייה CATTREE יוצא [] והאתר חוזר לשכבה
        #    הישנה בלי שום הודעה. דף תקין למראה עם ניווט ישן.
        self.assertTrue(self.tree(), 'CATTREE ריק — העץ לא נשלף בבנייה')

    def test_page_built_from_live_db(self):
        """🔴 הדף נבנה כשהמסד נטען — לא בגרסת "בלי רשת".

        נתפס 06/10: תקלת רשת רגעית בבנייה → db_content ריק → המגן מונע דף ריק,
        אבל הדף יוצא עם 1,472 כרטיסים (כולל 968 בלתי נראים) ובלי סינון stocked_ever.
        הוא נראה תקין לגמרי. **סימן אמין:** בדף בלי מסד אין לאף כרטיס `cs`.
        """
        import json
        i = HTML.index('const GROUPS = ') + len('const GROUPS = ')
        G = json.JSONDecoder().raw_decode(HTML[i:])[0]
        with_cs = sum(1 for g in G if g.get('cs'))
        self.assertGreater(with_cs / max(len(G), 1), 0.9,
                           f'רק {with_cs}/{len(G)} כרטיסים עם שיוך — כנראה המסד לא נטען בבנייה. לבנות מחדש.')

    def test_eight_groups_with_subs(self):
        tree = self.tree()
        self.assertGreaterEqual(len(tree), 8, 'פחות מ-8 קבוצות')
        for g in tree:
            self.assertTrue(g['subs'], f'קבוצה בלי תתי-קטגוריות: {g["m"]}')
            for k in ('he', 'bg', 'ink', 'ic'):
                self.assertTrue(g.get(k), f'{g["m"]} בלי {k}')

    def test_cheeks_group_exists(self):
        self.assertTrue('cheeks' in [g['m'] for g in self.tree()], 'הקבוצה cheeks חסרה')

    def test_groups_carry_slug(self):
        import json
        i = HTML.index('const GROUPS = ') + len('const GROUPS = ')
        G = json.JSONDecoder().raw_decode(HTML[i:])[0]
        have = [g for g in G if g.get('cs')]
        self.assertGreater(len(have), 400, f'רק {len(have)} כרטיסים עם שיוך לעץ')

    def test_sub_filter_wired(self):
        # הקוד שמסנן לפי תת-קטגוריה — בלעדיו הצ'יפים נצבעים ולא מסננים.
        self.assertTrue("curSub!=='__all__'&&g.cs!==curSub" in HTML.replace(' ', ''),
                        'הסינון לפי תת-קטגוריה לא מחובר')

    def test_deep_link_wired(self):
        """קישור עמוק #c=<קבוצה>&s=<תת> — נקרא בטעינה ונכתב בכל ניווט."""
        self.assertTrue('function applyHash' in HTML, 'אין קריאת קישור עמוק')
        self.assertTrue('function writeHash' in HTML, 'אין כתיבת קישור עמוק')
        # 🔑 הקריאה חייבת לקרות **לפני** הציור הראשון, אחרת הדף נפתח
        #    בהכל ואז קופץ — והלקוחה רואה הבהוב.
        self.assertTrue('if(applyHash())buildNav();' in HTML,
                        'הקישור העמוק לא נקרא לפני הציור הראשון')
        # ואיפוס סינון מנקה גם את הכתובת, אחרת רענון מחזיר את מה שנוקה.
        i = HTML.index('function resetFilters()')
        self.assertTrue('writeHash()' in HTML[i:i + 600],
                        'איפוס הסינון לא מנקה את הכתובת')

    def test_found_in_wired(self):
        """"נמצא ב:" בחיפוש — בשתי השפות."""
        # 🔑 לא מספיק שהפונקציה מוגדרת — היא חייבת **להיקרא**. שינוי שם
        #    בלבד השאיר את הבדיקה ירוקה במוטציה הראשונה.
        self.assertTrue('function foundInHtml(' in HTML, 'חסר "נמצא ב:"')
        self.assertTrue('el.innerHTML=foundInHtml();' in HTML.replace(' ', ''),
                        '"נמצא ב:" מוגדר אבל לא נקרא בחיפוש')
        self.has('found_in:\'נמצא ב:\'', 'תווית "נמצא ב:" בעברית')
        self.has('found_in:\'موجود في:\'', 'תווית "נמצא ב:" בערבית')

    def test_cathead_has_colour_and_arabic(self):
        """פס הכותרת נושא את צבע הקבוצה ואת השם הערבי מ-main_ar."""
        self.assertTrue('function buildCatHead' in HTML, 'חסר פס הכותרת')
        self.assertTrue("style=\"background:'+g.bg" in HTML, 'פס הכותרת בלי צבע הקבוצה')
        tree = self.tree()
        self.assertTrue(all(g.get('ar') for g in tree),
                        'יש קבוצה בלי שם בערבית — main_ar לא הגיע לדף')

    def test_home_is_clean(self):
        """🧹 הקו הנקי — מה שנמרוד ביקש להוריד נשאר למטה (06/10).

        שלוש הרצועות שהעמיסו את דף הבית — שורת השירות, רצועת המותגים
        וקרוסלת "מומלץ בשבילך" — מוסתרות. הבדיקה מוודאת שהן **לא חזרו**
        בעריכה עתידית: קל מאוד להחזיר אותן בלי לשים לב, כי הקוד שבונה
        אותן עדיין קיים.
        """
        body = HTML[HTML.index('<body'):HTML.index('<footer')]
        import re
        live = re.sub(r'<!--.*?-->', '', body, flags=re.S)   # בלי מה שבהערה
        for frag, why in ((' class="services"', 'שורת השירות'),
                          ('id="brandRow"', 'רצועת המותגים'),
                          ('id="recRow"', 'קרוסלת המומלצים')):
            self.assertNotIn(frag, live, f'{why} חזרה לדף הבית')

    def test_tiles_are_a_grid(self):
        """אריחי הקטגוריות הם רשת, לא רצועה נגללת — הקו של ההדמיה."""
        self.assertTrue(".cattiles.tree{display:grid" in HTML,
                        'אריחי הקטגוריות אינם רשת')
        self.assertTrue("el.className='cattiles tree'" in HTML,
                        'מחלקת הרשת לא מוחלת בבנייה')
        # ו"הכל" ו-Best Seller באותה שפה ויזואלית כמו השאר
        # 🔑 שוב המלכודת: 'ICO_HOT' הוא תת-מחרוזת של 'ICO_HOTX', ולכן בדיקת
        #    שם בלבד נשארה ירוקה כששיניתי את השם. בודקים את **אתר השימוש**.
        flat = HTML.replace(' ', '')
        self.assertTrue("tile('__all__',ICO_ALL," in flat,
                        'אריח "הכל" אינו משתמש באייקון הקו')
        self.assertTrue("tile('__hot__',ICO_HOT," in flat,
                        'אריח "Best Seller" אינו משתמש באייקון הקו')

    def test_no_handwriting_font(self):
        """✍️ כתב היד הוסר מכל האתר — כולל כרטיסי המוצר והתקנון (נמרוד 06/10).

        הוא היה ב-12 כללי CSS, בהם כותרות מסמכי המדיניות, ולכן האתר נראה
        כאילו שני מעצבים עבדו עליו. נמדד בדפדפן: אפס אלמנטים משתמשים בו.
        """
        self.assertNotIn('Gveret+Levin', HTML, 'גופן כתב היד עדיין נטען')
        self.assertNotIn("'Gveret Levin AlefAlefAlef','Heebo'", HTML,
                         'גופן כתב היד עדיין מוגדר כמשתנה')

    def test_banner_removed(self):
        """🖼️ באנר ההירו הוסר — הוא תפס מסך שלם ודחף את הקטגוריות למטה."""
        import re
        body = HTML[HTML.index('<body'):HTML.index('<footer')]
        live = re.sub(r'<!--.*?-->', '', body, flags=re.S)
        self.assertNotIn('id="ebanner"', live, 'באנר ההירו חזר')

    def test_group_click_lands_on_category_band(self):
        """🎛️ 12/10/2026 — לחיצה על קבוצה גוללת אל פס הקטגוריה (שם כפתור הסינון
        והמגירה). עד 12/10 היא לא גללה כדי להשאיר את בועות תת-הקטגוריה על המסך;
        הבועות ירדו — תת-הקטגוריה נבחרת במגירה."""
        flat = HTML.replace(' ', '').replace('\n', '')
        self.assertIn('writeHash();buildNav();render();goShop();}', flat, 'לחיצה על קבוצה לא גוללת לפס הקטגוריה')
        self.assertIn("var el=document.getElementById('cathead');", HTML, 'הגלילה לא מכוונת לפס הקטגוריה')

    def test_single_filter_drawer(self):
        """🎛️ 12/10/2026 — מגירת סינון אחת (ספורה) במקום שלוש שכבות: בועות תת-קטגוריה,
        סרגל מותג/סינון/מועדפים ופס "מסונן לפי" — מוסתרים; הכל במגירה."""
        for frag, why in (
            ('id="fdrawer"', 'המגירה'), ('id="fbBtn"', 'כפתור הסינון'), ('id="fdShow"', 'כפתור "הצגת N"'),
            ('.toolbar,.subrow,#actFil{display:none!important}', 'השכבות הישנות מוסתרות'),
            ("dsec('sub',t('fd_sub')", 'תת-קטגוריה במגירה'), ("dsec('brand',t('fd_brand')", 'מותג במגירה'),
            ("dsec('price',t('fd_price')", 'מחיר במגירה'), ("dsec('attr:'+d.k,secLbl(d)", 'התכונות של טל במגירה'),
            ("fd_sub:'الفئة الفرعية'", 'ערבית'),
        ):
            self.assertIn(frag, HTML, f'חסר: {why}')
        self.assertEqual(HTML.count('id="rescount"'), 1, 'ספירת התוצאות כפולה')
        # סבב 2 (נמרוד 12/10): מיון בתוך המגירה, קטגוריה מבטלת חיפוש, כל המקטעים פתוחים, בועות לכל בחירה
        self.assertNotIn('id="fbSort"', HTML, 'בורר מיון נפרד חזר לשורה')
        self.assertIn('<span id="fbLbl">סינון מומלץ</span>', HTML, 'שם הכפתור אינו "סינון מומלץ"')
        self.assertIn("cat_hot:'הנמכרים ביותר'", HTML, 'האריח עדיין Best Seller')
        self.assertIn("dsec('sort',t('fd_sort')", HTML, 'אין מיון במגירה')
        self.assertIn("function goCat(c){clearSearchQ();", HTML, 'לחיצה על קטגוריה לא מבטלת חיפוש')
        self.assertIn("h+=dsec('attr:'+d.k,secLbl(d),sel,inner,true);", HTML, 'התכונות לא פתוחות')
        # סבב 3 (נמרוד 12/10): בועות בשורה התחתונה הקבועה, "חיפוש" פותח את הסינון, קבוצה ראשית במגירה
        self.assertIn('<div class="fdchips" id="fdChips"></div>', HTML, 'אין בועות בשורה התחתונה של המגירה')
        self.assertNotIn('<div class="fdsel">', HTML, 'הבועות עדיין בראש הרשימה הנגללת')
        self.assertIn('<button onclick="navFilter()">', HTML, '"חיפוש" בסרגל התחתון לא פותח את הסינון')
        self.assertIn("h+=dsec('cat',t('af_cat')", HTML, 'אין בחירת קבוצה ראשית במגירה')
        # סבב 4: "נקה הכל" מנקה גם קבוצה ראשית וחיפוש; חיפוש חופשי בראש המגירה
        self.assertIn("function drawerClear(){var so=document.getElementById('sort');if(so)so.value='default';clearSearchQ();curCat='__all__';", HTML, '"נקה הכל" לא מנקה קבוצה ראשית')
        self.assertIn('id="fdQ"', HTML, 'אין חיפוש חופשי במגירה')
        # סבב 9: פחות שטח מת במחשב; מותגים באנגלית; תמונת כרטיס תמיד בתוך הריבוע
        self.assertIn('@media(min-width:1100px){.grid{grid-template-columns:repeat(4,1fr)}}', HTML, 'אין 4 עמודות במחשב')
        self.assertIn('"אסתי לאודר": "ESTÉE LAUDER"', HTML, 'אסתי לאודר בלי שם אנגלי')
        self.assertIn('.card .imgbox img{position:absolute;inset:14px;', HTML, 'תמונת הכרטיס לא מוגבלת לריבוע')
        # סבב 8: מותגים עברית·אנגלית לפי א"ב; "אחורה" סוגר חלון; גוון בלי מחיר צרכן לא נמכר (היה ₪null)
        self.assertIn("brandsInStock().slice().sort((a,b)=>a.localeCompare(b,'he'))", HTML, 'המותגים במגירה לא לפי א"ב')
        self.assertIn("b+(BRANDS_EN[b]?' · '+BRANDS_EN[b]:'')", HTML, 'אין שם אנגלי למותג במגירה')
        self.assertIn("window.addEventListener('popstate',function(){", HTML, '"אחורה" לא סוגר חלון')
        self.assertIn("if(!WHOLESALE&&!hasConsPrice(v))return true;", HTML, 'גוון בלי מחיר צרכן עדיין נמכר')
        self.assertIn("if(p==null||!(p>0))return `<div class=\"pricewrap\"><div class=\"price ${cls||''}\">—</div></div>`;", HTML, 'מחיר חסר עדיין מוצג כ-null')
        # סבב 6 (נמרוד 12/10): גם במחשב המגירה נשלפת — בלי עמודה קבועה, המוצרים ברוחב מלא
        self.assertNotIn('.fdrawer{position:sticky', HTML, 'חזרה עמודת סינון קבועה במחשב')
        self.assertIn('function navFilter(){openDrawer();}', HTML, '"חיפוש" לא פותח את המגירה במחשב')
        # סבב 5: נעילת גלילה אמיתית בזמן שהמגירה פתוחה (אייפון), והצ'אט מעל פס הסל
        self.assertIn('body.pglock{position:fixed;', HTML, 'אין נעילת דף למגירה')
        # סבב 7: גם החלונות (ההזמנה שלי / מסך המוצר) נועלים את הדף — לא רק המגירה
        self.assertIn("pushOvState('ov',id);\n  lockPage();", HTML, 'חלון (.ov) לא נועל את הדף')
        self.assertIn("if(anyOvOpen()||drawerOpen())return;", HTML, 'סגירת חלון אחד משחררת נעילה של חלון אחר')
        # ביקורת 13/10: רשומה ישנה לא בולעת סגירה; הכתובת מתעדכנת אחרי popstate; בלי מרוץ ב"יש לי קוד"; בריחת מאפיין
        self.assertIn("if(ovStateOpen(st))return;", HTML, 'popstate בולע סגירה לפי רשומה ישנה')
        self.assertIn("if(typeof writeHash==='function')writeHash();", HTML, 'הכתובת לא מתעדכנת אחרי popstate')
        self.assertIn("onclick=\"closeOvNow('clubModal');openWsCode()\"", HTML, '"יש לי קוד" עדיין במרוץ היסטוריה')
        self.assertIn("data-k=\"'+aesc(esc(f.k))+'\">", HTML, 'מפתח הבועה בלי בריחת מאפיין')
        self.assertIn("&&!(typeof drawerOpen==='function'&&drawerOpen()))document.body.style.overflow=''", HTML, 'נגיעה במסך משחררת את נעילת המגירה')
        self.assertIn('body.has-cart .wachat{bottom:calc(150px', HTML, 'חלון הוואטסאפ לא מורם מעל פס הסל')
        self.assertEqual(HTML.count('id="sort"'), 1, 'בורר המיון כפול')

    def test_subchips_carry_group_colour(self):
        """🎨 צ׳יפי תת-הקטגוריה בצבע הקבוצה — "על אותו קו של צבעים"."""
        flat = HTML.replace(' ', '')
        self.assertIn('background:${g.ink}', flat.replace('\\', ''),
                      'הצ׳יפ הנבחר אינו בצבע הקבוצה')
        self.assertIn('color:${g.ink}', flat.replace('\\', ''),
                      'הצ׳יפים אינם בצבע הקבוצה')

    def test_no_hard_black_in_ui(self):
        """🌹 בלי שחור חזק באלמנטים הפעילים — "להמשיך את הצבעים הרכים" (נמרוד 06/10).

        השחור נשאר לטקסט, שם הוא קריאוּת. הוא ירד מהפס העליון, מכפתור
        ההוספה, מסרגל הסל, מניקוי הסינון ומתגיות המוצר — שם הוא רק צעק.
        """
        # 🏜️ 12/10/2026 — פלטת "חול ואבן" (באנר המעצבת): הגוון הוחלף מוורוד-פטל לקרמל,
        #    והפס העליון לחום כהה — עדיין לא שחור חזק.
        self.has('--brand:#a88266', 'גוון המותג (חול ואבן)')
        self.has('--brand-d:#6f523c', 'גוון המותג הכהה')
        self.assertNotIn('--brand:#a85a6d', HTML, 'נשאר הוורוד-פטל הישן')
        for frag, why in (
            ('background:linear-gradient(90deg,#3b2b20,var(--brand-d)', 'הפס העליון'),
            ('background:linear-gradient(135deg,var(--brand),var(--brand-d))', 'כפתור ההוספה'),
            ('.bdg.sale{background:var(--brand-d)}', 'תגית מבצע'),
        ):
            self.assertTrue(frag in HTML.replace(' ', '').replace(frag.replace(' ', ''), frag)
                            or frag in HTML, f'{why} עדיין שחור')
        self.assertNotIn('.bdg.sale{background:#171717}', HTML, 'תגית המבצע עדיין שחורה')

    def test_fav_fills_pink(self):
        """❤️ עיגול המועדפים מתמלא ורוד בבחירה."""
        self.assertTrue('.fav.on{background:var(--brand)' in HTML,
                        'עיגול המועדפים אינו מתמלא')

    def test_promo_has_authenticity(self):
        """✔ "מוצרים מקוריים" בפס העליון — בעברית ובערבית."""
        self.has('promo_orig', 'שורת המקוריות')
        self.has('מוצרים מקוריים בלבד', 'הנוסח העברי')
        self.has('منتجات أصلية فقط', 'הנוסח הערבי')
        self.assertTrue("['promo0','promo1','promo3']" in HTML,
                        'שורת המקוריות לא נכנסה למחזור ההודעות בטלפון')

    def test_promobar_sticky(self):
        """📌 הפס העליון מקובע בטלפון ובמחשב, ושורת החיפוש נדבקת מתחתיו ולא מתחתיו מוסתרת."""
        css = HTML.replace(' ', '')
        self.assertTrue('.promobar{position:sticky;top:0;' in css, 'הפס העליון אינו מקובע')
        self.assertTrue('.search-wrap{position:sticky;top:var(--pbh,0px);' in css,
                        'שורת החיפוש לא מתחשבת בגובה הפס — תוסתר מתחתיו')
        self.assertTrue("style.setProperty('--pbh',pb.offsetHeight+'px')" in css,
                        'גובה הפס לא נמדד — שורת החיפוש תיצמד לגובה 0')
        # 🔴 overflow-x:hidden על body הופך אותו למיכל גלילה שלעולם לא גולל — ואז שום דבר לא נדבק.
        #    clip חותך גלישה לרוחב בלי ליצור מיכל גלילה (נתפס 07/10 על הכתובת החיה).
        self.assertTrue('overflow-x:hidden;overflow-x:clip}' in css,
                        'body עם overflow-x:hidden בלי clip — ההדבקה לא תעבוד בפועל')
        # הפס לא מוסתר בטלפון — רק ההודעות מתחלפות
        self.assertNotIn('.promobar{display:none', css)

    def test_card_carries_group_tint(self):
        """🎨 גוון הקבוצה נכנס גם לכרטיס המוצר."""
        self.assertTrue('function CARD_TINT' in HTML, 'אין גוון לכרטיס')
        self.assertTrue('<div class="imgbox"${CARD_TINT(g)}>' in HTML,
                        'הגוון מוגדר אך לא מוחל על הכרטיס')

    def test_brand_list_follows_category(self):
        """🏷️ בורר המותגים מציג רק מותגים שיש להם מוצר במלאי **בקטגוריה הנוכחית**.

        נמרוד 06/10: "כשמסננים לפי קטגוריה, להציג את המותגים שבמלאי לאותו
        סינון". בלי זה הלקוחה בתוך "גלוסים" רואה 79 מותגים, בוחרת אחד — ומקבלת
        מסך ריק. inCatScope חייב להיות אותו תנאי קטגוריה של visible().
        """
        flat = HTML.replace(' ', '')
        self.assertTrue('function inCatScope(g)' in HTML, 'אין תחום קטגוריה למותגים')
        self.assertTrue('g.brand===b&&inCatScope(g)&&inStock(g)' in flat, 'brandsInStock לא מסונן לקטגוריה')
        self.assertTrue('g.brand===b&&inCatScope(g)&&' in flat, 'brandCount לא מסונן לקטגוריה')
        # ותת-הקטגוריה נלקחת בחשבון, לא רק הקבוצה
        self.assertTrue("returncurSub==='__all__'||g.cs===curSub;" in flat, 'inCatScope מתעלם מתת-הקטגוריה')

    def test_product_modal_uses_brand_tone(self):
        """🌹 מסך המוצר, הטפסים והתקנון בשפה הצבעונית — לא בשחור."""
        for frag, why in (('.pd .pr{font-size:26px;font-weight:700;color:var(--brand-d)', 'מחיר במסך המוצר'),
                          ('.pd-sw button.on{background:var(--brand)', 'גוון נבחר'),
                          ('background:linear-gradient(90deg,var(--brand-d),var(--brand));box-s', 'כפתור "הוסף לסל"'),
                          ('.policy h2{font-family:var(--font);font-size:28px;font-weight:600;letter-spacing:0;color:var(--brand-d)', 'כותרת התקנון'),
                          ('.form h4{font-family:var(--font);font-size:17px;font-weight:600;letter-spacing:0;color:var(--brand-d)', 'כותרות הטופס')):
            self.assertTrue(frag in HTML, f'{why} עדיין בשחור')

    def test_sub_shown_in_active_filters(self):
        self.assertTrue("k:'sub'" in HTML, 'תת-הקטגוריה לא מוצגת בסרגל הסינון הפעיל')


class AttrFilterTest(Base):
    """🎛️ 07/10/2026 — סינון לפי תכונות (הרשימות של טל).

    הסכנה הגדולה כאן היא **שקט**: אם עמודת attrs לא נשלפת (מיגרציה שלא הורצה,
    תקלת רשת) הבנאי ממשיך בלי תכונות — הכפתור פשוט לא מופיע ואיש לא ישים לב.
    """
    def groups(self):
        import json
        i = HTML.index('const GROUPS = ') + len('const GROUPS = ')
        return json.JSONDecoder().raw_decode(HTML[i:])[0]

    def test_attrs_reached_the_page(self):
        G = self.groups()
        n = sum(1 for g in G if g.get('at'))
        self.assertGreater(n, 200, f'רק {n} כרטיסים עם תכונות — attrs לא נשלפו מהמסד (המיגרציה רצה?)')
        face = [g for g in G if (g.get('cs') or '').startswith('face-foundation')]
        self.assertTrue(any('coverage' in (g.get('at') or {}) for g in face), 'למייקאפ אין רמת כיסוי')

    def test_powder_split_pressed_loose(self):
        st = {s for g in self.groups() if g.get('cs') == 'face-powder' for s in g.get('sts', [])}
        self.assertIn('דחוסה', st); self.assertIn('בתפזורת', st)
        self.assertNotIn('דחוסה/אבקה', st, 'בפודרה עדיין יש "דחוסה/אבקה" — הסוגים לא פוצלו')

    def test_all_variant_types_counted(self):
        """כרטיס עם גוונים מסוגים שונים — כל הסוגים נספרים, לא רק הרוב."""
        G = self.groups()
        self.assertTrue(all('sts' in g for g in G), 'חסר sts בכרטיסים')
        self.assertTrue("if(k==='st')return g.sts||" in HTML, 'הסינון קורא את סוג הרוב בלבד')

    def test_tal_order(self):
        """סוג → רמת כיסוי → גימור → סוג עור (הסדר שטל ביקשה)."""
        i = [HTML.index(f"{{k:'{k}',he:") for k in ('st', 'coverage', 'finish', 'skin')]
        self.assertEqual(i, sorted(i), 'סדר המקטעים אינו הסדר של טל')

    def test_filter_wired(self):
        c = HTML.replace(' ', '')
        self.has('id="filterBtn"', 'כפתור הסינון בשורת הסינון')
        self.has('id="filterModal"', 'חלון הסינון')
        self.assertTrue('if(s.size&&!gAttr(g,k).some(v=>s.has(v)))returnfalse;' in c,
                        'visible() לא מסנן לפי התכונות')
        self.assertTrue("goCat(c){clearSearchQ();curSub='__all__';curCat=c;BSEL.clear();for(constkinFSEL)deleteFSEL[k];" in c,
                        'מעבר קבוצה לא מנקה את הסינון')
        self.assertTrue("k.indexOf('attr:')===0" in c, 'תגית סינון פעילה לא ניתנת לניקוי')
        self.assertTrue('pruneAttrs();updateFilterBtn();' in c, 'buildNav לא מעדכן את הכפתור')
        self.assertTrue('${pdAttrsHtml(g)}' in HTML, 'דף המוצר לא מציג את התכונות')

    def test_filter_values_escaped(self):
        """ערכי התכונות מגיעים מהמסד — חייבים לעבור esc לפני innerHTML."""
        self.has("data-v=\"'+aesc(esc(v))+'\"", 'ערך בתכונה לא מוברח')
        self.has("'+esc(attrLbl(v))+'</button>", 'תווית התכונה לא מוברחת')


class BusinessDetailsTest(Base):
    """🔴 תנאי פרסום. כל כישלון כאן עוצר העלאה לאוויר."""

    def test_legal_identity(self):
        self.has('שניר שריקי', 'שם העוסק')
        self.has('040553562', 'מספר עוסק מורשה')
        self.has('עוסק מורשה', 'הכיתוב "עוסק מורשה"')

    def test_contact(self):
        self.has('053-4555501', 'טלפון העסק')
        self.has('beautyfavorites2026@gmail.com', 'מייל העסק')

    def test_vat_statement(self):
        # מחיר בלי אמירה על מע"מ הוא מחיר מטעה.
        self.assertTrue(re.search(r'המחירים\s+כוללים\s+מע', HTML),
                        'חסרה ההצהרה "המחירים כוללים מע"מ"')

    def test_six_policies_present_and_filled(self):
        for key in ('f_about', 'f_ship', 'f_ret', 'f_terms', 'f_priv', 'f_access'):
            self.has(key, f'מפתח מדיניות {key}')
        self.has('openPolicy', 'פונקציית openPolicy')
        # ותוכן — לא רק קישור. POLICIES הוא מילון הטקסטים.
        self.has('POLICIES', 'מילון תוכן המדיניות')

    def test_policy_bodies_not_empty(self):
        """שבעת מסמכי המדיניות קיימים **ויש בהם תוכן**.

        קישור שנפתח לחלון ריק גרוע מקישור שאינו קיים: הלקוחה חושבת
        שקראה תקנון. לכן נמדד אורך ולא רק קיום המפתח.
        """
        i = HTML.index('const POLICIES={')
        blk = HTML[i:HTML.index('function openPolicy', i)]
        for key in ('about', 'contact', 'shipping', 'returns', 'terms',
                    'accessibility', 'privacy'):
            m = re.search(key + r':`(.*?)`,?\n', blk, re.S)
            self.assertTrue(m, f'מסמך מדיניות חסר: {key}')
            self.assertGreater(len(m.group(1)), 200,
                               f'מסמך המדיניות {key} כמעט ריק ({len(m.group(1))} תווים)')

    def test_footer_labels_bilingual(self):
        """תוויות הפוטר קיימות בעברית **ובערבית**.

        ⚠️ זו בדיקה על **התוויות** בלבד. גוף מסמכי המדיניות עצמם כתוב
        היום בעברית בלבד (נמדד 06/10: אפס תווים בערבית ב-POLICIES) —
        מצב שקדם לשינוי הזה, ומדווח לנמרוד בנפרד.
        """
        for key in ('f_about', 'f_ship', 'f_ret', 'f_terms', 'f_priv', 'f_access'):
            self.assertGreaterEqual(HTML.count(key + ":"), 2,
                                    f'{key} אינו מוגדר בשתי השפות')
        self.has('حول المتجر', 'תווית "אודות" בערבית')

    def test_policies_arabic_embedded(self):
        """🌐 שבעת מסמכי המדיניות בערבית — קיימים, לא ריקים, עם "הנוסח העברי הוא הקובע".

        אושר 06/10 (נמרוד דרך הניהול). לפני כן לקוחה בערבית לחצה "تكنون" וקיבלה
        עברית. מסמך שחסר נופל לעברית בקוד — ולכן הבדיקה היא שמונעת מזה לקרות בשקט.
        """
        import json
        i = HTML.index('const POLICIES_AR=') + len('const POLICIES_AR=')
        ar = json.JSONDecoder().raw_decode(HTML[i:])[0]
        for key in ('about', 'contact', 'shipping', 'returns', 'terms', 'accessibility', 'privacy'):
            self.assertTrue(key in ar, f'מסמך מדיניות בערבית חסר: {key}')
            self.assertGreater(len(ar[key]), 200, f'המסמך הערבי {key} כמעט ריק')
            self.assertTrue('النص العبري هو النص الملزم' in ar[key], f'{key}: חסרה שורת "הנוסח העברי הוא הקובע"')
            self.assertEqual(ar[key].count('<h2>'), 1, f'{key}: מבנה שונה מהעברי')
        # והקוד באמת בוחר לפי השפה — לא רק מחזיק את המילון
        self.assertTrue("((LANG==='ar'&&POLICIES_AR[k])||POLICIES[k]||'')" in HTML.replace(' ', ''),
                        'openPolicy לא בוחר ערבית לפי LANG')

    def test_no_grey_boxes(self):
        """🌸 "אני לא רוצה בשום מקום מלבנים אפורים" (נמרוד 06/10).

        רוב האפור הגיע מ-`--accent-soft` (#f2f2f2) שכ-20 רכיבים יורשים ממנו,
        והשאר מאפור מפורש בתמונות ובתקציר המוצר. בודקים את המקור ואת המפורשים.
        """
        self.assertNotIn('--accent-soft:#f2f2f2', HTML, '--accent-soft חזר לאפור')
        self.assertTrue('padding:11px 13px;background:var(--brand-soft)' in HTML, 'תקציר המוצר אפור')
        import re
        css = HTML[HTML.index('<style>'):HTML.index('</style>')]
        grey = re.findall(r'background:[^;}]*#(?:f2f2f2|fafafa|f4f4f5|f6f5f3|f7f7f7|f4f4f4)\b', css)
        self.assertEqual(grey, [], f'נשארו רקעים אפורים: {grey[:4]}')

    def test_image_zoom(self):
        """🔍 לחיצה על תמונה במסך המוצר מגדילה אותה — עם מעבר בין תמונות וסגירה ב-Escape."""
        self.has('id="zoomOv"', 'שכבת ההגדלה')
        flat = HTML.replace(' ', '')
        # (לא ב-flat — הסרת הרווחים הופכת '.pd-gal img' ל-'.pd-galimg')
        self.assertTrue("e.target.closest('.pd-gal img')" in HTML, 'הלחיצה על תמונה לא מחוברת להגדלה')
        self.assertTrue('functionzoomStep(d)' in flat and 'functioncloseZoom()' in flat, 'חסר מעבר/סגירה')
        self.assertTrue("if(e.key==='Escape'){e.stopPropagation();closeZoom();}" in flat,
                        'Escape לא סוגר את ההגדלה (או סוגר גם את מסך המוצר)')
        # 12/10/2026 — "נתקע לפעמים": בלי מעקב אצבע ידני (לא טיפל ב-touchcancel). רצועה עם גלילת הטלפון.
        self.assertIn('id="zoomTrack"', HTML, 'אין רצועת תמונות')
        self.assertIn('scroll-snap-type:x mandatory;', HTML, 'הרצועה לא נעצרת בכל תמונה')
        self.assertNotIn("x0=e.touches[0].clientX", HTML, 'חזר מעקב האצבע הידני')

    def test_build_skips_never_stocked(self):
        """📦 מוצר שמעולם לא נקלט לא נבנה לדף — והסינון לא מרוקן את האתר כשאין רשת."""
        import os
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build_catalog.py'), encoding='utf-8').read()
        self.assertIn(',stocked_ever"', src, 'stocked_ever לא נשלף מהתצוגה')
        self.assertIn('if db_content:\n            _row = db_content.get(_nbc(p.get("barcode")))', src,
                      'הסינון לא מוגן מפני מסד שלא נטען — בלי רשת הוא ירוקן את כל האתר')
        self.assertIn('_row.get("stocked_ever") is not True', src, 'הסינון לפי stocked_ever חסר')
        # ומקור התרגום בתוך catalog/ — לא ב-10-עבודה/
        self.assertIn('POLICIES_AR_PATH = os.path.join(CAT, "policies_ar.json")', src,
                      'הבנייה תלויה בקובץ מחוץ ל-catalog/')

    def test_data_regions_cannot_close_script(self):
        """🛡️ אין "<" גולמי באף אזור נתונים שנצרב לתוך <script> (ביקורת אבטחה 06/10)."""
        import json
        for key in ('const GROUPS = ', 'const CATTREE = ', 'const POLICIES_AR=', 'const BRANDS_EN='):
            i = HTML.index(key) + len(key)
            _, end = json.JSONDecoder().raw_decode(HTML[i:])
            self.assertEqual(HTML[i:i + end].count('<'), 0, f'{key.strip()} מכיל "<" גולמי — אפשר לסגור את הסקריפט')

    def test_category_ids_escaped_in_html(self):
        """🛡️ מזהי קטגוריה מהמסד לא נכנסים ל-HTML או ל-JS בלי ניקוי (ביקורת אבטחה 06/10).

        categories כתיבה לכל עובד פעיל ואין כלל על צורת ה-slug. נבדק בדפדפן עם
        מטען אמיתי: הקוד הישן הריץ אותו 37 פעמים, הקוד הזה — 0.
        """
        self.has('data-c="${aesc(esc(key))}"', 'מזהה הקבוצה באריח מנוקה')
        self.has('data-s="${aesc(esc(key))}"', 'מזהה תת-הקטגוריה בצ׳יפ מנוקה')
        self.assertNotIn("onclick=\"goCat(\\''+CT_MAIN[sl]", HTML, '"נמצא ב:" עדיין בונה JS ממחרוזת מהמסד')
        flat = HTML.replace(' ', '')
        self.assertTrue("if(!CT_BY[m]||CT_MAIN[sl]!==m)return;" in flat, '"נמצא ב:" לא מאמת את הערכים מול העץ')

    def test_multi_brand_filter(self):
        """🏷️ כמה מותגים בבת אחת (נמרוד 06/10) — קבוצה, לא ערך יחיד.

        נבדק בדפדפן: אי.אל.אף (3) + הודה (2) = 5 בתוך "גלוסים"; כל מותג הוא צ'יפ
        נפרד שנמחק לבד; החלון נשאר פתוח בין בחירות.
        """
        flat = HTML.replace(' ', '')
        self.assertNotIn('curBrand', HTML, 'נשאר שימוש במותג יחיד')
        self.assertTrue('constBSEL=newSet();' in flat, 'אין קבוצת מותגים')
        self.assertTrue('if(BSEL.size&&!BSEL.has(g.brand))returnfalse;' in flat, 'הסינון לא לפי קבוצת המותגים')
        self.assertTrue("elseif(BSEL.has(b))BSEL.delete(b);elseBSEL.add(b);" in flat, 'בחירה לא מוסיפה/מסירה')
        self.assertTrue("for(constbofBSEL)out.push({k:'brand:'+b" in flat, 'אין צ׳יפ נפרד לכל מותג')
        self.assertTrue("k.indexOf('brand:')===0)BSEL.delete(k.slice(6))" in flat, 'מחיקת צ׳יפ מותג לא מוחקת רק אותו')

    def test_pay_button_not_grey(self):
        """💳 "שלם עכשיו" בגוון המותג, ובמצב נעול — רך יותר, לא אפור (נמרוד 06/10)."""
        self.has('.send.pay{background:linear-gradient(90deg,var(--brand-d),var(--brand))', 'כפתור התשלום בגוון המותג')
        import re
        locked = re.search(r'\.send\.locked\{[^}]*\}', HTML).group(0)
        self.assertNotIn('grayscale', locked, 'הכפתור הנעול עדיין מאפיר')

    def test_hidden_images_not_in_page(self):
        """🚫 תמונות לא מקצועיות לא מגיעות לדף (נמרוד 06/10: "אסור… חכי לתמונה מקצועית").

        23 תמונות ב-catalog/hidden_images.json, אחרי בדיקת עין של 1,869 תמונות.
        הקבצים לא נמחקים — הבנייה פשוט לא מעתיקה אותם.
        """
        import json, os
        H = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hidden_images.json'), encoding='utf-8'))
        H = {k: v for k, v in H.items() if not k.startswith('_')}
        self.assertGreaterEqual(sum(len(v) for v in H.values()), 23, 'רשימת ההסתרה התקצרה')
        leaks = [f'{pid}/{f}' for pid, fs in H.items() for f in fs if f'images/{pid}/{f}' in HTML]
        self.assertEqual(leaks, [], f'תמונה מוסתרת הגיעה לדף: {leaks[:3]}')

    def test_product_without_professional_image_hidden(self):
        """🖼️ כלל קבוע (נמרוד 06/10): מוצר בלי אף תמונה לא מופיע בדף עד שמגיעה תמונה."""
        import json
        i = HTML.index('const GROUPS = ') + len('const GROUPS = ')
        G = json.JSONDecoder().raw_decode(HTML[i:])[0]
        bare = [g['name_he'][:40] for g in G if not any(v.get('imgs') for v in g['variants'])]
        self.assertEqual(bare, [], f'כרטיסים בלי תמונה בדף: {bare[:3]}')
        # 11/10/2026: שני המוצרים שהיו בלי תמונה קיבלו תמונה מקצועית (01.jpg), והצילום
        #    מהיד (99-hand.jpg) מוסתר — חייבים להופיע, ורק עם התמונה החדשה.
        for bc in ('3616303472290', '609332574588'):
            self.assertIn('"barcode": "%s"' % bc, HTML, f'{bc} לא חזר לדף אחרי שקיבל תמונה')
        self.assertNotIn('99-hand.jpg', HTML, 'צילום מהיד הגיע לדף')

    def test_designer_banner_and_icons(self):
        """🏜️ 12/10/2026 — באנר המעצבת (כיתוב חי ומתורגם) + אייקוני הקטגוריות המאוירים."""
        for frag, why in (
            ('id="dhero"', 'באנר הכניסה'), ('url(hero-banner.jpg)', 'תמונת הבאנר'),
            ('onclick="goRecs()"', 'כפתור למומלצים'), ("dh_h1a:'كل المنتجات المرغوبة'", 'כיתוב בערבית'),
            ("setText('dhCta',t('dh_cta'))", 'הכיתוב מתחלף בשפה'), ('<p id="dhSub">מוצרים מקוריים', 'כותרת המשנה של המעצבת'),
            ('viewBox="0 0 48 48"', 'אייקונים מאוירים'), ('.brandbar{display:none}', 'בלי לוגו כפול'),
        ):
            self.assertIn(frag, HTML, f'חסר: {why}')
        self.assertNotIn('<span class="ci cticon"><svg viewBox="0 0 24 24"', HTML, 'נשאר אייקון ישן באריח')
        import json
        i = HTML.index('const CATTREE = ') + len('const CATTREE = ')
        T = json.JSONDecoder().raw_decode(HTML[i:])[0]
        self.assertTrue(T, 'עץ ריק')
        for g in T:
            self.assertIn('<', g['ic'], f"{g['m']} בלי אייקון")
            self.assertNotEqual(g['ic'], '<circle cx="24" cy="24" r="16"/>', f"{g['m']} קיבל אייקון ברירת מחדל")
        self.assertEqual(HTML.count('id="langBtn"'), 1, 'כפתור השפה כפול')

    def test_terms_checkbox_in_checkout(self):
        self.assertTrue(re.search(r'קראתי ואני מסכים', HTML),
                        'חסרה תיבת אישור התקנון בצ׳ק-אאוט')

    def test_bottom_nav(self):
        self.has('id="bnav"', 'הניווט התחתון')
        # 🔑 המזהים האמיתיים הם nvHome/nvSearch/… ולא nav_* — נבדק בדף הבנוי
        #    ולא נוחש. מפתח שגוי בבדיקה הופך אותה לאזעקת שווא קבועה.
        for lbl in ('nvHome', 'nvSearch', 'nvFav', 'nvCart', 'nvWa'):
            self.has(lbl, f'פריט בניווט התחתון: {lbl}')
        self.assertTrue(re.search(r'wa\.me|whatsapp', HTML, re.I), 'חסר קישור וואטסאפ')

    def test_arabic_side_exists(self):
        # האתר דו-לשוני: אם הערבית נשברת, חצי מהלקוחות מקבלים דף חלקי.
        self.has("'ar'", 'שכבת הערבית')
        self.assertTrue(re.search(r'[؀-ۿ]{3,}', HTML), 'אין טקסט ערבי בדף')


if __name__ == '__main__':
    print(f'נבדק: {PATH}  ({len(HTML)//1024} ק"ב)')
    unittest.main(argv=[sys.argv[0]], verbosity=2)
