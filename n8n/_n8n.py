# _n8n.py - comment lancer la commande n8n : le n8n PRIVE pose par installation.bat (programmes/n8n) s'il est la,
# sinon « npx n8n@<version> » (installation a la main, voir docs/INSTALLATION.md).
import glob
import os
import subprocess

DEPOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def n8n_prive():
    """(node.exe, script n8n) du dossier programmes/, ou None"""
    script = os.path.join(DEPOT, "programmes", "n8n", "node_modules", "n8n", "bin", "n8n")
    if not os.path.isfile(script):
        return None
    nodes = sorted(glob.glob(os.path.join(DEPOT, "programmes", "node", "*", "node.exe"))) or \
        sorted(glob.glob(os.path.join(DEPOT, "programmes", "node", "node.exe")))
    return (nodes[-1] if nodes else "node"), script


def lancer(arguments, delai=600):
    """lance « n8n <arguments> » ; rend (code de sortie, sortie). Les arguments ne sont jamais affiches (jetons)."""
    prive = n8n_prive()
    try:
        if prive:
            r = subprocess.run([prive[0], prive[1]] + list(arguments), capture_output=True, text=True, timeout=delai,
                               encoding="utf-8", errors="replace")
        else:
            version = os.environ.get("ARCHI_N8N_VERSION") or "1"
            ligne = 'npx --yes "n8n@%s" %s' % (version, " ".join('"%s"' % a if " " in a else a for a in arguments))
            r = subprocess.run(ligne, shell=True, capture_output=True, text=True, timeout=delai, encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # commande introuvable, delai depasse...
        return 1, type(e).__name__
