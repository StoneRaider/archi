"""Tests hors ligne du serveur (Google, Microsoft et le modele sont simules : rien ne part)."""
import json, os, sys, tempfile, types
from datetime import datetime, timedelta
D = tempfile.mkdtemp(prefix="serveur_")
os.environ.update(ARCHI_SERVEUR_DONNEES=D, ARCHI_OUTLOOK_CLIENT_ID="test-client")
for nom in ["googleapiclient", "googleapiclient.discovery", "googleapiclient.errors", "google_auth_oauthlib", "google_auth_oauthlib.flow",
            "google", "google.auth", "google.auth.transport", "google.auth.transport.requests", "google.auth.exceptions", "msal"]:
    m = types.ModuleType(nom); sys.modules[nom] = m
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
sys.modules["googleapiclient.discovery"].build = lambda *a, **k: None
sys.modules["google_auth_oauthlib.flow"].InstalledAppFlow = object
sys.modules["google.auth.transport.requests"].Request = object
sys.modules["google.auth.exceptions"].RefreshError = Exception
class _Cache:
    has_state_changed = False
    def deserialize(self, s): pass
    def serialize(self): return ""
sys.modules["msal"].SerializableTokenCache = _Cache
sys.modules["msal"].PublicClientApplication = lambda *a, **k: types.SimpleNamespace(get_accounts=lambda: [])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reglages, mail_commande as M, email_orchestrator as E  # noqa: E402

ok = ko = 0
def verif(nom, cond, detail=""):
    global ok, ko
    ok, ko = (ok + 1, ko) if cond else (ok, ko + 1)
    if not cond:
        print("ECHEC", nom, str(detail)[:200])

verif("donnees hors du depot", reglages.DONNEES == D)
verif("adresse valide", M._destinataires("camille@example.com") == ["camille@example.com"])
try:
    M._destinataires("camille, pas une adresse"); verif("adresse invalide refusee", False)
except ValueError:
    verif("adresse invalide refusee", True)
verif("boites", M._boites("hotmail") == ["outlook"] and M._boites("") == ["gmail", "outlook"])
verif("tri : on range par defaut, on ne jette pas", E.ACTION_NON_INTERESSANT == "tri_auto")
verif("regles absentes : pas de plantage", E.load_rules() == {})
verif("journal dans les donnees", E.LOG_FILE.startswith(D))
# envoyer sans apercu, ou apercu trop vieux : refuse
def refuse():
    try:
        r = M.envoyer()
        return not r.get("ok")
    except ValueError:
        return True   # le serveur le transforme en « le mail n'est PAS parti »
verif("envoyer sans apercu refuse", refuse())
json.dump({"a": ["camille@example.com"], "sujet": "x", "corps": "y", "boite": "gmail",
           "cree_le": (datetime.now() - timedelta(hours=3)).isoformat()}, open(M.EN_ATTENTE, "w"))
verif("apercu de plus de 2 h refuse", refuse())
print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
