"""Fabrique le ZIP a telecharger : dist/Archi-<version>.zip
   = les fichiers suivis par git (au dernier commit) + l'appli Android deja compilee (appli/Archi.apk).

Usage : python outils_depot/faire_le_zip.py [--apk chemin/app-debug.apk] [--version 1.0]
Le ZIP contient un seul dossier « Archi-<version> » : on l'extrait, on double-clique sur installation.bat.
L'APK n'est jamais range dans le depot (regle du detecteur) : il est pris dans le dossier de fabrication
et glisse directement dans le ZIP. Sans APK, le ZIP est fabrique quand meme et le script le dit.
"""
import argparse
import io
import os
import subprocess
import sys
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APK_FABRIQUE = os.path.join(RACINE, "appli", "app", "build", "outputs", "apk", "debug", "app-debug.apk")
# ce qui ne sert pas a quelqu'un qui installe (le depot git, lui, garde tout)
HORS_ZIP = (".github/", ".gitattributes", ".gitignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", default=APK_FABRIQUE)
    ap.add_argument("--version", default="1.0")
    ap.add_argument("--sortie", default=os.path.join(RACINE, "dist"))
    a = ap.parse_args()

    sale = subprocess.run(["git", "status", "--porcelain"], cwd=RACINE, capture_output=True, text=True).stdout.strip()
    if sale:
        print("ATTENTION : des fichiers ne sont pas dans le dernier commit, ils ne seront PAS dans le ZIP :")
        print("\n".join("  " + l for l in sale.splitlines()[:12]))
    # git archive applique .gitattributes : les .bat sortent en CRLF, le reste en LF
    brut = subprocess.run(["git", "archive", "--format=zip", "HEAD"], cwd=RACINE, capture_output=True, check=True).stdout
    dossier = "Archi-%s" % a.version
    os.makedirs(a.sortie, exist_ok=True)
    cible = os.path.join(a.sortie, dossier + ".zip")
    n = 0
    with zipfile.ZipFile(io.BytesIO(brut)) as source, zipfile.ZipFile(cible, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for info in source.infolist():
            if info.is_dir() or info.filename.startswith(HORS_ZIP):
                continue
            z.writestr(zipfile.ZipInfo(dossier + "/" + info.filename, date_time=info.date_time), source.read(info), zipfile.ZIP_DEFLATED)
            n += 1
        if os.path.isfile(a.apk):
            z.write(a.apk, dossier + "/appli/Archi.apk")
            n += 1
            apk = "avec l'appli Android (%d Ko)" % (os.path.getsize(a.apk) // 1024)
            # la meme appli, a part, pour la page « Releases »
            with open(a.apk, "rb") as h, open(os.path.join(a.sortie, "Archi.apk"), "wb") as s:
                s.write(h.read())
        else:
            apk = "SANS l'appli Android (APK introuvable : %s)" % a.apk
    print("%s : %d fichiers, %.1f Mo, %s" % (cible, n, os.path.getsize(cible) / 1e6, apk))
    return 0


if __name__ == "__main__":
    sys.exit(main())
