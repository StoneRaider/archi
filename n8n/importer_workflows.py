# importer_workflows.py - importe dans n8n le workflow principal et les workflows optionnels, avec leurs ID FIXES :
# ainsi les liens entre eux (Hunter -> outils OSINT, vision...) et les identifiants (.env) marchent sans rien regler.
#   python n8n/importer_workflows.py            (lance par lancer_archi.bat au premier demarrage)
#   python n8n/importer_workflows.py --forcer   (reimporte : tes modifications dans n8n seront ECRASEES)
# n8n doit etre arrete pendant l'import (la commande ecrit directement dans sa base).
import glob
import os
import subprocess
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ICI))
import archi_env  # noqa: E402


def main():
    archi_env.charger()
    base = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
    os.makedirs(base, exist_ok=True)
    dossier_temoins = os.path.join(base, ".workflows_archi_importes")
    os.makedirs(dossier_temoins, exist_ok=True)
    forcer = "--forcer" in sys.argv
    tous = [os.path.join(ICI, "archi_demo.json")] + sorted(glob.glob(os.path.join(ICI, "optionnels", "*.json")))
    # un temoin par fichier : ce qui a deja ete importe n'est JAMAIS reimporte (tes modifications dans n8n restent)
    fichiers = [f for f in tous if forcer or not os.path.exists(os.path.join(dossier_temoins, os.path.basename(f)))]
    if not fichiers:
        print("Workflows deja importes (python n8n/importer_workflows.py --forcer pour tout reimporter et ECRASER).")
        return
    version = os.environ.get("ARCHI_N8N_VERSION") or "1"
    ok = 0
    for f in fichiers:
        r = subprocess.run('npx --yes "n8n@%s" import:workflow --input="%s"' % (version, f), shell=True,
                           capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            ok += 1
            open(os.path.join(dossier_temoins, os.path.basename(f)), "w").write("ok\n")
        else:
            print("Echec de l'import : %s" % os.path.basename(f))
    print("Workflows importes dans n8n : %d sur %d." % (ok, len(fichiers)))
    if ok != len(fichiers):
        print("Les autres : importe-les a la main dans n8n (Workflows > Import from file).")


if __name__ == "__main__":
    main()
