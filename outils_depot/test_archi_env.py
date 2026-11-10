"""Tests du chargeur .env (archi_env.py) : lecture, guillemets, commentaires, pas d'ecrasement, valeurs jamais affichees."""
import io, os, sys, tempfile, contextlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import archi_env as A  # noqa: E402
d = tempfile.mkdtemp()
f = os.path.join(d, ".env")
open(f, "w", encoding="utf-8").write('# commentaire\nTEST_A=simple\nTEST_B="avec espaces # pas un commentaire"\n'
                                     "TEST_C='x'\nTEST_E=\"guillemets\" # commentaire\nexport TEST_F=avec_export\n"
                                     "TEST_D=valeur # commentaire de fin\nTEST_VIDE=\nTEST_DEJA=du_fichier\nligne bizarre\n")
os.environ["TEST_DEJA"] = "garde"
n = A.charger(f)
ok = (os.environ["TEST_A"] == "simple" and os.environ["TEST_B"] == "avec espaces # pas un commentaire"
      and os.environ["TEST_C"] == "x" and os.environ["TEST_D"] == "valeur" and "TEST_VIDE" not in os.environ
      and os.environ["TEST_DEJA"] == "garde" and os.environ["TEST_E"] == "guillemets"
      and os.environ["TEST_F"] == "avec_export" and n == 6)
open(f, "a", encoding="utf-8").write("TELEGRAM_BOT_TOKEN=123456:SECRETSECRET\n")
os.environ["ARCHI_ENV"] = f
import subprocess
r = subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(A.__file__)), "archi_env.py")],
                   capture_output=True, text=True, env=dict(os.environ, ARCHI_ENV=f))
b = io.StringIO(r.stdout)
ok = ok and "SECRET" not in b.getvalue() and "Telegram" in b.getvalue()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "n8n"))
import creer_identifiants as C  # noqa: E402
c = {x["name"]: x for x in C.identifiants({"TELEGRAM_BOT_TOKEN": "1:abc", "TAVILY_API_KEY": "tvly-x", "HUNTERIO_API_KEY": "h"})}
ok = ok and c["Tavily (recherche web)"]["data"]["value"] == "Bearer tvly-x" and c["Hunter.io (domaines)"]["data"]["name"] == "api_key"     and c["Bot Telegram Archi"]["id"] == "ArchiTelegram001" and len(C.identifiants({})) == 1
# --brancher : un Python « branche » charge le .env tout seul, sauf pour un test ou avec ARCHI_SANS_ENV=1
site = tempfile.mkdtemp()
A.brancher(site)
genere = open(os.path.join(site, A.NOM_AUTO + ".py"), encoding="utf-8").read()
ok = ok and os.path.isfile(os.path.join(site, A.NOM_AUTO + ".pth")) and "SECRET" not in genere
depot_faux = tempfile.mkdtemp()
import shutil
shutil.copy(A.__file__, os.path.join(depot_faux, "archi_env.py"))
open(os.path.join(depot_faux, ".env"), "w", encoding="utf-8").write("TEST_BRANCHE=oui\nTEST_DEJA_LA=du_fichier\n")
open(os.path.join(site, A.NOM_AUTO + ".py"), "w", encoding="utf-8").write(A.MODELE_AUTO % depot_faux)
voir = "import os; print(os.environ.get('TEST_BRANCHE', '-'), os.environ.get('TEST_DEJA_LA', '-'))"
for nom_script, env_plus, attendu in [("outil.py", {}, "oui garde"), ("test_outil.py", {}, "- garde"),
                                      ("outil.py", {"ARCHI_SANS_ENV": "1"}, "- garde")]:
    s = os.path.join(depot_faux, nom_script)
    open(s, "w", encoding="utf-8").write(voir + "\n")
    env = {k: v for k, v in os.environ.items() if k not in ("TEST_BRANCHE", "ARCHI_ENV", "ARCHI_SANS_ENV")}
    env.update(PYTHONPATH=site, TEST_DEJA_LA="garde", **env_plus)
    # sitecustomize joue ici le role du fichier .pth : il importe le module pose par --brancher au demarrage de Python
    open(os.path.join(site, "sitecustomize.py"), "w", encoding="utf-8").write("import %s\n" % A.NOM_AUTO)
    r = subprocess.run([sys.executable, s], capture_output=True, text=True, env=env)
    if r.stdout.strip() != attendu:
        ok = False
        b.write("brancher %s %s : %r (attendu %r) %s" % (nom_script, env_plus, r.stdout.strip(), attendu, r.stderr[-300:]))
A.debrancher(site)
ok = ok and not os.path.exists(os.path.join(site, A.NOM_AUTO + ".pth")) and not os.path.exists(os.path.join(site, A.NOM_AUTO + ".py"))
print("archi_env OK" if ok else "archi_env ECHEC " + b.getvalue())
sys.exit(0 if ok else 1)
