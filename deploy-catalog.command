#!/bin/bash
# ============================================================================
#  פרסום הקטלוג — נכתב 31/08/2026 אחרי שסנכרון עמד למחוק 462 תמונות
# ----------------------------------------------------------------------------
#  שלוש הגנות שלא היו קודם:
#    1. תיקיית העבודה **תחת הבית** ולא ב-/tmp (היא מתנקה בלי התראה).
#    2. `rsync --delete` עם **--backup-dir** — כל קובץ שנמחק נשמר, לא נעלם.
#    3. **בדיקת דלתא לפני commit**: אם מסתמנת מחיקה של קובץ תמונה שעדיין
#       מוזכר ב-index.html — הסקריפט **עוצר** ולא דוחף.
#  ובנוסף: שחזור CNAME, אימות .nojekyll, והחרגת סודות.
# ============================================================================
set -euo pipefail

REPO_URL="https://github.com/l3ilimport-alt/beauty-favorites.git"
SRC="$(cd "$(dirname "$0")" && pwd)"          # תיקיית catalog/
WORK="$HOME/bf-publish-$(date +%Y-%m-%d)"
BACKUP="$HOME/bf-deleted-$(date +%Y-%m-%d-%H%M)"
export PATH="$HOME/.local/gh-cli/gh_2.93.0_macOS_arm64/bin:$PATH"

echo "▶ מקור:  $SRC"
echo "▶ עבודה: $WORK"

# ---- 1. שיבוט רדוד (או שימוש חוזר בקיים ועדכני) ---------------------------
if [ -d "$WORK/.git" ]; then
  cd "$WORK" || exit 1
  git fetch --depth 1 origin main && git reset --hard origin/main
else
  git clone --depth 1 "$REPO_URL" "$WORK"
fi
cd "$WORK" || exit 1

# ---- 2. סנכרון עם גיבוי מחיקות --------------------------------------------
# ⚠️ 02/09/2026 — הוסרו ההחרגות `* 2.*` ו-`* 3.*` (החרגת הקבצים).
#   31 תמונות אמיתיות המוזכרות ב-index.html נקראות כך. אומת: כולן מחזירות 200 באתר.
#   ההחרגה לא מחקה אותן — rsync מגן על קובץ מוחרג מפני --delete — אבל היא **הקפיאה**
#   אותן: גרסה מעודכנת לא נדחפה, ותמונה חדשה בשם כזה לא הייתה מתפרסמת כלל, והדף
#   היה מפנה אליה ומקבל 404. אומת בניסוי מבודד.
#   החרגת התיקיות נשארת: 3,421 תיקיות `* 2`/`* 3` ריקות לחלוטין (הקובץ היחיד בהן הוא .DS_Store).
mkdir -p "$BACKUP"
rsync -a --delete --backup --backup-dir="$BACKUP" \
  --exclude='.git' --exclude='.DS_Store' \
  --exclude='* 2/' --exclude='* 3/' \
  --exclude='upc_key.txt' --exclude='.admin-env' --exclude='.sync-env' \
  --exclude='deploy-catalog.command' \
  "$SRC/" "$WORK/"

# ---- 3. CNAME ו-.nojekyll ---------------------------------------------------
# ⚠️ CNAME קיים רק בריפו. rsync --delete מוחק אותו, ואז הדומיין מתנתק.
git checkout HEAD -- CNAME 2>/dev/null || true
[ -s CNAME ] || { echo "🔴 CNAME ריק או חסר — עצירה"; exit 1; }
[ -f .nojekyll ] || touch .nojekyll
echo "✓ CNAME=$(cat CNAME) · .nojekyll קיים"

# ---- 4. שער הבטיחות: אין מחיקת תמונה שעדיין מוזכרת בדף ---------------------
git add -A
python3 - "$WORK" <<'PY'
import subprocess, sys, os
w = sys.argv[1]
out = subprocess.run(['git','status','--short','-z'], capture_output=True, cwd=w).stdout.split(b'\0')
dels = [p[3:].decode('utf-8') for p in out if p[:2] in (b'D ', b' D')]
if not dels:
    print('✓ אין מחיקות בכלל'); raise SystemExit(0)

# הדף החדש שנכנס עכשיו
html_new = open(os.path.join(w, 'index.html'), encoding='utf-8').read()

# ⚠️ 02/09/2026 — נוספה בדיקה שנייה, מול הדף שכרגע **חי באתר**.
#   השער הקודם בדק רק את הדף החדש. לכן קובץ שהדף החי עדיין מפנה אליו, אך הבנייה
#   החדשה כבר לא מזכירה, היה נמחק בשקט והשער היה מאשר. זה בדיוק התרחיש של
#   462 התמונות מ-31/08. מ-02/09 מחיקה כזו עוצרת את הפרסום.
try:
    html_live = subprocess.run(['git','show','HEAD:index.html'],
                               capture_output=True, cwd=w, check=True).stdout.decode('utf-8')
except Exception as e:
    print(f'🔴 לא ניתן לקרוא את index.html מהמאגר ({e}) — עצירה'); raise SystemExit(1)

risky_new  = [d for d in dels if d in html_new]
risky_live = [d for d in dels if d in html_live and d not in risky_new]
print(f'⚠ מסתמנות {len(dels)} מחיקות (גיבוי נשמר ב-backup-dir).')
if risky_new or risky_live:
    if risky_new:
        print(f'🔴 {len(risky_new)} מוזכרות בדף **החדש** — עצירה:')
        for r in risky_new[:10]: print('   ', r)
    if risky_live:
        print(f'🔴 {len(risky_live)} מוזכרות בדף **החי שבמאגר** — עצירה:')
        for r in risky_live[:10]: print('   ', r)
    raise SystemExit(1)
print(f'✓ אף מחיקה אינה מוזכרת לא בדף החדש ולא בדף החי — בטוח להמשיך')
PY

# ---- 5. אין סודות -----------------------------------------------------------
for f in upc_key.txt .admin-env .sync-env; do
  [ -e "$f" ] && { echo "🔴 $f נכנס לריפו — עצירה"; exit 1; }
done
echo "✓ אין סודות"

# ---- 6. קומיט ודחיפה (בלי force) -------------------------------------------
if git diff --cached --quiet; then
  echo "✓ אין שינויים — אין מה לדחוף"; exit 0
fi
git status --short | awk '{print $1}' | sort | uniq -c
git -c user.name="Nimrod" -c user.email="a0547599923@gmail.com" \
    commit -q -m "${1:-עדכון קטלוג $(date +%d/%m/%Y)}"
git push origin main
echo "✅ נדחף. גיבוי המחיקות: $BACKUP"
echo "   לאמת בעוד דקה: https://beautyfavorites.co.il/?cb=$(date +%s)"
