"""Le detecteur doit attraper des faux secrets et des mots perso plantes (evite un detecteur muet)."""
import os, subprocess, sys, tempfile
ICI = os.path.dirname(os.path.abspath(__file__))
d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, ".local"))
open(os.path.join(d, ".local", "mots_perso.txt"), "w", encoding="utf-8").write("Motperso Exemple\nVillage-Test\n")
open(os.path.join(d, "a.py"), "w", encoding="utf-8").write(
    'chemin = "C:/" + "Users/Bob/x et Motperso Exemple"\nlieu = "pres de Village-Test"\ntok = "123456789:' + "A" * 35 + '"\n')
r = subprocess.run([sys.executable, os.path.join(ICI, "verifier_depot.py"), d], capture_output=True, text=True)
sortie = r.stdout
ok = r.returncode == 1 and sortie.count("perso\t") == 2 and "token_telegram" in sortie
print("detecteur OK" if ok else "DETECTEUR MUET :\n" + sortie)
sys.exit(0 if ok else 1)
