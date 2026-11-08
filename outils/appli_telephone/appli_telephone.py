# -*- coding: utf-8 -*-
r"""appli_telephone.py - donne a J sur Telegram la derniere version de l'appli Archi (pc\telephone\Archi.apk).
Le noeud « Outils maison » joint le fichier (champ document) et l'envoie sur Telegram. Lecture seule."""
import json, os, re, sys, zipfile
BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
# l'APK fabrique (GitHub Actions ou gradlew) est depose ici ; ARCHI_APK pour un autre chemin
APK = os.environ.get("ARCHI_APK") or os.path.join(BASE, "pc", "telephone", "Archi.apk")
GRADLE = os.path.join(os.environ.get("ARCHI_DEPOT", ""), "appli", "app", "build.gradle")
def sortir(d):
    print(json.dumps(d, ensure_ascii=False)); sys.exit(0)
if not os.path.exists(APK):
    sortir({"ok": False, "phrase_pour_utilisateur": "Je ne trouve pas l'appli Archi sur le PC."})
try:
    zipfile.ZipFile(APK).testzip()
except Exception:
    sortir({"ok": False, "phrase_pour_utilisateur": "Le fichier de l'appli Archi est abîmé sur le PC : il faut la refabriquer."})
v = ""
try:
    m = re.search(r"versionName\s*=\s*'([^']+)'", open(GRADLE, encoding="utf-8").read()); v = m.group(1) if m else ""
except Exception:
    pass
mo = os.path.getsize(APK) / 1048576
sortir({"ok": True, "document": APK, "version": v,
        "phrase_pour_utilisateur": f"Je t'envoie l'appli Archi{(' version ' + v) if v else ''} sur Telegram ({mo:.1f} Mo). Sur le téléphone : touche le fichier, puis Installer (par-dessus l'ancienne, tes réglages restent)."})
