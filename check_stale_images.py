#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🖼️ גלאי תמונות ישנות — תופס את המלכודת של --fast.

`build_catalog.py --fast` מדלג על עיבוד תמונה שכבר קיימת ב-catalog/images.
לכן החלפת תמונה בקובץ ידע קיים **לא מגיעה לאתר** — הבנייה מצליחה, הפרסום עובר,
והתמונה הישנה נשארת באוויר בשקט. כך צילומי תוויות עם ברקוד הגיעו ללקוחות.

הרצה:  python3 catalog/check_stale_images.py [--fix]
  בלי דגל — מדווח בלבד.
  --fix   — מוחק את התיקיות המעובדות הישנות כדי שהבנייה הבאה תיצור אותן מחדש.
"""
import glob, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def scan():
    stale = []
    for kd in sorted(glob.glob(os.path.join(ROOT, "knowledge", "*/"))):
        pid = os.path.basename(kd.rstrip("/"))
        src = os.path.join(kd, "images")
        dst = os.path.join(ROOT, "catalog", "images", pid)
        if not (os.path.isdir(src) and os.path.isdir(dst)):
            continue
        for f in sorted(os.listdir(src)):
            if not f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            s, d = os.path.join(src, f), os.path.join(dst, f)
            if not os.path.exists(d):
                stale.append((pid, f, "אין עותק מעובד")); continue
            if os.path.getmtime(s) > os.path.getmtime(d) + 2:
                stale.append((pid, f, "המקור חדש מהמעובד"))
    return stale


def main():
    stale = scan()
    if not stale:
        print("✅ אין תמונות ישנות — כל התמונות המעובדות עדכניות")
        return
    print(f"🔴 {len(stale)} תמונות מעובדות אינן תואמות למקור:\n")
    dirs = sorted({p for p, _, _ in stale})
    for pid, f, why in stale[:40]:
        print(f"   {pid[:56]:58s} {f:12s} {why}")
    if len(stale) > 40:
        print(f"   … ועוד {len(stale)-40}")
    print(f"\n{len(dirs)} תיקיות מושפעות.")
    if "--fix" in sys.argv:
        for pid in dirs:
            shutil.rmtree(os.path.join(ROOT, "catalog", "images", pid), ignore_errors=True)
        print(f"🧹 נמחקו {len(dirs)} תיקיות. הרץ עכשיו:  python3 catalog/build_catalog.py --fast")
    else:
        print("להרצה עם תיקון:  python3 catalog/check_stale_images.py --fix")


if __name__ == "__main__":
    main()
