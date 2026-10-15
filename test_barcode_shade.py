# -*- coding: utf-8 -*-
"""🔎 15/10/2026 — "סורקים ברקוד באתר ונפתח גוון אחר" (נמרוד, רייר ביוטי / טו פייסד).
מריץ בנוד את פונקציות ההתאמה **מהדף הבנוי** על **הנתונים האמיתיים שבדף**: לכל קבוצה עם כמה גוונים,
ברקוד מלא של כל גוון חייב לבחור בדיוק את הגוון הזה (ולא את הראשון), ולא להתאים לאף קבוצה אחרת.
שימוש:  python3 catalog/test_barcode_shade.py [index.html]
"""
import json, os, re, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith('.html') else os.path.join(HERE, 'index.html')

JS = r"""
const fs=require('fs'); const html=fs.readFileSync(process.argv[1],'utf8');
const gm=html.match(/const GROUPS = (\[.*?\]);\n/s); if(!gm)throw new Error('GROUPS not found');
const GROUPS=JSON.parse(gm[1]);
const fm=html.match(/function bcKey[\s\S]*?\nfunction bcMatch\(g,d\)\{[\s\S]*?\n\}/); if(!fm)throw new Error('bc functions not found');
const sel={}; eval(fm[0]);
const out={groups:0,checked:0,wrongShade:[],cross:[],partialOk:0,partialChecked:0};
const key=x=>String(x||'').replace(/\D/g,'').replace(/^0+/,'');
for(const g of GROUPS){
  const vs=(g.variants||[]).filter(v=>key(v.barcode).length>=11);
  if((g.variants||[]).length<2)continue; out.groups++;
  for(const v of vs){
    const raw=String(v.barcode).replace(/\D/g,''); const full=raw.length>=12?raw:raw.padStart(12,'0');
    out.checked++;
    for(const k in sel)delete sel[k];
    const ok=bcMatch(g,full);
    const want=g.variants.indexOf(v);
    // אותו ברקוד יכול להופיע בשני גוונים בטעות נתונים — אז כל אחד מהם תקין
    const same=g.variants.map((x,i)=>key(x.barcode)===key(v.barcode)?i:-1).filter(i=>i>=0);
    if(!ok||!same.includes(sel[g.gid]))out.wrongShade.push({gid:g.gid,bc:raw,got:sel[g.gid],want});
    // ברקוד מלא לא מתאים לקבוצה אחרת (אלא אם אותו ברקוד באמת קיים בה)
    for(const h of GROUPS){ if(h===g)continue;
      if(bcMatch(h,full)&&!h.variants.some(x=>key(x.barcode)===key(v.barcode)))out.cross.push({bc:raw,from:g.gid,to:h.gid}); }
    // חיפוש חלקי — 6 הספרות האחרונות: אם תואם, הגוון שנבחר מסתיים בהן
    const tail=raw.slice(-6); out.partialChecked++;
    for(const k in sel)delete sel[k];
    if(bcMatch(g,tail)&&sel[g.gid]!=null&&key(g.variants[sel[g.gid]].barcode).endsWith(key(tail)))out.partialOk++;
  }
}
console.log(JSON.stringify(out));
"""

def run(page):
    r = subprocess.run(['node', '-e', JS, page], capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class BarcodeShade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run(PAGE)

    def test_checked_enough(self):
        self.assertGreater(self.r['groups'], 20, self.r)
        self.assertGreater(self.r['checked'], 100, self.r)

    def test_full_barcode_opens_its_own_shade(self):
        self.assertEqual(self.r['wrongShade'], [], 'ברקוד מלא פתח גוון אחר: %s' % self.r['wrongShade'][:5])

    def test_full_barcode_no_cross_group_match(self):
        self.assertEqual(self.r['cross'], [], 'ברקוד מלא תאם קבוצה אחרת: %s' % self.r['cross'][:5])

    def test_partial_picks_matching_shade(self):
        self.assertEqual(self.r['partialOk'], self.r['partialChecked'], self.r)


if __name__ == '__main__':
    print('נבדק:', PAGE)
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if not a.endswith('.html')], verbosity=1)
