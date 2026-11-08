"""Tests hors ligne de la protection SSRF de lire_page.py (aucune page n'est lue)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lire_page as L  # noqa: E402

interdites = ["http://127.0.0.1/", "http://localhost:5678/", "http://x@127.0.0.1/", "http://2130706433/", "http://0177.0.0.1/",
              "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://169.254.169.254/latest/", "http://192.168.1.1/",
              "http://10.0.0.5/", "file:///C:/Windows/win.ini", "ftp://exemple.com/", "http://user:pass@exemple.com/"]
ko = [u for u in interdites if L.url_autorisee(u)]
print("acceptees a tort :", ko if ko else "aucune")
print(f"{len(interdites) - len(ko)} OK, {len(ko)} ECHEC")
sys.exit(1 if ko else 0)
