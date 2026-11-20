# test_liaison.py - l'outil mails branche sur le VRAI serveur d'Archi (serveur/archi_server.py : ses routes, son garde-fou
# anti-navigateur, son brouillon fige), avec une fausse messagerie Gmail. Rien ne sort du PC, aucun compte n'est lu.
#   python test_liaison.py        (saute tout seul si fastapi ou uvicorn ne sont pas installes)
import contextlib, io, json, os, socket, sys, tempfile, threading, time, types, urllib.error, urllib.request
from datetime import datetime, timedelta

try:
    import fastapi, uvicorn  # noqa: F401
except ImportError:
    print("fastapi ou uvicorn absent : test de liaison sauté")
    sys.exit(0)

ICI = os.path.dirname(os.path.abspath(__file__))
SERVEUR = os.path.join(os.path.dirname(os.path.dirname(ICI)), "serveur")
H = tempfile.mkdtemp(prefix="mails_liaison_")
libre = socket.socket(); libre.bind(("127.0.0.1", 0)); PORT = libre.getsockname()[1]; libre.close()
# tout est fixe AVANT les imports : le .env du depot ne remplace jamais une variable deja la
os.environ.update(ARCHI_BASE=os.path.join(H, ".n8n-files"), ARCHI_SERVEUR_DONNEES=os.path.join(H, "donnees"),
                  ARCHI_SERVEUR_PORT=str(PORT), ARCHI_OUTLOOK_CLIENT_ID="test-client", ARCHI_OUTLOOK_TENANT="consumers",
                  ARCHI_GOOGLE_CLIENT=os.path.join(H, "absent.json"), ARCHI_UTILISATEUR="Camille")

# les bibliotheques Google et Microsoft sont remplacees par des coquilles vides (comme serveur/test_serveur.py)
for nom in ["googleapiclient", "googleapiclient.discovery", "googleapiclient.errors", "google_auth_oauthlib", "google_auth_oauthlib.flow",
            "google", "google.auth", "google.auth.transport", "google.auth.transport.requests", "google.auth.exceptions",
            "google.oauth2", "google.oauth2.credentials", "msal"]:
    sys.modules[nom] = types.ModuleType(nom)
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
sys.modules["googleapiclient.discovery"].build = lambda *a, **k: None
sys.modules["google_auth_oauthlib.flow"].InstalledAppFlow = object
sys.modules["google.auth.transport.requests"].Request = object
sys.modules["google.auth.exceptions"].RefreshError = Exception
sys.modules["google.oauth2.credentials"].Credentials = object


class _Cache:
    has_state_changed = False

    def deserialize(self, s):
        pass

    def serialize(self):
        return ""


sys.modules["msal"].SerializableTokenCache = _Cache
sys.modules["msal"].PublicClientApplication = lambda *a, **k: types.SimpleNamespace(get_accounts=lambda: [])
sys.path.insert(0, SERVEUR)
sys.path.insert(0, ICI)
import archi_server, mail_commande  # noqa: E402
import mails as M  # noqa: E402

OK = KO = 0


def verif(nom, cond, detail=""):
    global OK, KO
    if cond:
        OK += 1
    else:
        KO += 1
        print("ECHEC", nom, str(detail)[:400])


# ---------------------------------------------------------------- la fausse messagerie Gmail
JOURNAL = []          # ((users, drafts, create), parametres)


class Faux:
    def __init__(self, chemin=(), kw=None):
        self.chemin, self.kw = chemin, kw or {}

    def __getattr__(self, nom):
        return Faux(self.chemin + (nom,))

    def __call__(self, **kw):
        return Faux(self.chemin, kw)

    def execute(self):
        JOURNAL.append((self.chemin, self.kw))
        if self.chemin[-2:] == ("drafts", "create"):
            return {"id": "brouillon-1"}
        if self.chemin[-2:] == ("messages", "list"):
            return {"messages": [{"id": "deja-vu"}]}       # l'adresse est connue : pas d'alerte d'orthographe
        return {}


RELIE = {"gmail": True}


def faux_service():
    if not RELIE["gmail"]:
        raise RuntimeError("Gmail non branche : il manque le fichier OAuth Google (voir serveur/LISEZMOI.md)")
    return Faux()


def outlook_absent(*_a, **_k):
    raise RuntimeError("Outlook non branche : mets ARCHI_OUTLOOK_CLIENT_ID dans le .env (voir serveur/LISEZMOI.md)")


mail_commande.get_service = faux_service
mail_commande._call = outlook_absent

# ---------------------------------------------------------------- le vrai serveur, sur un port libre
serveur = uvicorn.Server(uvicorn.Config(archi_server.app, host="127.0.0.1", port=PORT, log_level="error"))
threading.Thread(target=serveur.run, daemon=True).start()
for _ in range(100):
    try:
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://127.0.0.1:%d/sante" % PORT, timeout=1).read()
        break
    except Exception:
        time.sleep(0.1)
else:
    print("le serveur n'a pas démarré"); sys.exit(1)


def appel(**d):
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        try:
            M.executer(d)
        except M.Erreur as e:
            M.repondre(False, str(e))
    return json.loads(b.getvalue().strip().splitlines()[-1])


def faits(*fin):
    return [k for c, k in JOURNAL if c[-2:] == fin]


# le garde-fou du serveur est bien actif ici : un navigateur est refuse, l'outil passe
req = urllib.request.Request("http://127.0.0.1:%d/mails/envoyer" % PORT, data=b"{}", method="POST",
                             headers={"Origin": "http://example.org", "Content-Type": "application/json"})
try:
    urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5)
    verif("une page web est refusée par le serveur", False)
except urllib.error.HTTPError as e:
    verif("une page web est refusée par le serveur", e.code == 403, e.code)

def afficher(tache):
    """Ce que fait core/apercu_mail.js a la fin du tour : il note l'empreinte de l'apercu affiche et le numero du message."""
    M.ecrire_json(M.MONTRE, {"empreinte": json.load(open(M.APERCU, encoding="utf-8"))["empreinte"], "tache": tache})


def preparer(tache, montre=True, **plus):
    r = appel(**dict({"action": "preparer", "a": "notaire@example.com", "texte": "Bonjour", "_tache": tache}, **plus))
    if montre and r.get("ok"):
        afficher(tache)
    return r


def envoyer(tache, avant, **plus):
    return appel(**dict({"action": "envoyer", "_accord": "oui", "_accord_message": "oui", "_tache": tache, "_tache_avant": avant}, **plus))


def envois():
    return [x["body"]["id"] for x in faits("drafts", "send")]


# une adresse web qui pointerait vers ce PC est refusee (anti-rebinding), comme une page ouverte dans un navigateur
for nom, en_tetes in (("un autre hôte", {"Host": "example.org"}), ("une page (Sec-Fetch-Site)", {"Sec-Fetch-Site": "cross-site"})):
    req = urllib.request.Request("http://127.0.0.1:%d/mails/chercher?texte=x" % PORT, headers=en_tetes)
    try:
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5)
        verif("serveur : %s est refusé" % nom, False)
    except urllib.error.HTTPError as e:
        verif("serveur : %s est refusé" % nom, e.code == 403, e.code)

# preparer : le vrai serveur cree le brouillon, fige l'apercu et rend son empreinte
r = preparer("msg001", montre=False, sujet="Pièce manquante", texte="Bonjour, voici la pièce.")
verif("preparer : apercu rendu par le vrai serveur", r["ok"] and r.get("statut") == "APERCU"
      and r.get("apercu") == {"boite": "gmail", "a": ["notaire@example.com"], "sujet": "Pièce manquante", "texte": "Bonjour, voici la pièce."}, r)
verif("preparer : un brouillon créé, rien d'envoyé", len(faits("drafts", "create")) == 1 and envois() == [])
fige = json.load(open(mail_commande.EN_ATTENTE, encoding="utf-8"))
verif("preparer : l'aperçu est figé côté serveur, et le serveur et l'outil calculent la même empreinte", fige.get("empreinte") == r.get("empreinte")
      == mail_commande.empreinte_de("gmail", ["notaire@example.com"], "Pièce manquante", "Bonjour, voici la pièce.")
      == M.empreinte_de("gmail", ["notaire@example.com"], "Pièce manquante", "Bonjour, voici la pièce."), (fige, r))
r = preparer("msg001", montre=False, texte="  Bonjour  ")
verif("preparer : sans objet, le serveur écrit « (sans objet) » et l'outil l'accepte", r.get("apercu", {}).get("sujet") == "(sans objet)", r)
r = preparer("msg001", montre=False, a="notaire@example.com ; clerc@example.com", sujet="Deux", texte="Bonjour à vous deux")
verif("preparer : deux destinataires, le serveur les rend dans l'ordre et l'outil les accepte", r["ok"] and r["apercu"]["a"] == ["notaire@example.com", "clerc@example.com"], r)
r = preparer("msg001", montre=False, sujet="Objet\nsur deux lignes", texte="Bonjour")
verif("preparer : un objet sur deux lignes est aplati avant d'aller au serveur", r["ok"] and r["apercu"]["sujet"] == "Objet sur deux lignes", r)
r = preparer("msg001", montre=False, sujet="Pièce manquante", texte="Bonjour, voici la pièce.")

# le serveur lui-meme refuse un envoi qui ne nomme pas cet apercu (un autre appelant, une vieille version de l'outil)
for corps in ({}, {"empreinte": ""}, {"empreinte": "0" * 32}):
    x = M.appeler("POST", "/mails/envoyer", corps=corps)
    verif("serveur : envoi sans la bonne empreinte refusé %s" % json.dumps(corps), x.get("ok") is False and envois() == []
          and "apercu a change" in x.get("phrase_pour_utilisateur", ""), x)
verif("serveur : le brouillon est toujours en attente après ces refus", os.path.exists(mail_commande.EN_ATTENTE))

# envoyer : les refus de l'outil ne touchent pas la messagerie
r = envoyer("msg001", "msg000")
verif("envoyer dans le même message que l'aperçu : rien ne part, l'aperçu reste", not r["ok"] and r.get("apercu_en_attente") is True and envois() == [], r)
r = envoyer("msg002", "msg001")
verif("envoyer un aperçu jamais affiché : rien ne part, il sera affiché", not r["ok"] and r.get("apercu_non_montre") and r.get("statut") == "APERCU" and envois() == [], r)
afficher("msg001")
r = appel(action="envoyer", _tache="msg002", _tache_avant="msg001")
verif("envoyer sans accord : rien ne part", not r["ok"] and envois() == [], r)
r = appel(action="envoyer", _accord="oui", _tache="msg002", _tache_avant="msg001")
verif("envoyer sans la preuve du contrôle du message : rien ne part", not r["ok"] and envois() == [], r)
r = envoyer("msg003", "msg002")
verif("envoyer deux messages après l'affichage : rien ne part", not r["ok"] and envois() == [], r)
afficher("msg003")

# le message suivant : c'est le brouillon fige qui part, une seule fois
dernier = faits("drafts", "create")[-1]
r = envoyer("msg004", "msg003", a="pirate@example.org", texte="autre chose")
verif("envoyer : parti", r["ok"] and r.get("statut") == "ENVOYE" and "C'est envoyé, Camille" in r["phrase_pour_utilisateur"]
      and "notaire@example.com" in r["phrase_pour_utilisateur"], r)
verif("envoyer : un seul envoi, celui du brouillon créé", envois() == ["brouillon-1"], envois())
verif("envoyer : l'aperçu est oublié des deux côtés", not os.path.exists(mail_commande.EN_ATTENTE) and not os.path.exists(M.APERCU))
r = envoyer("msg005", "msg004")
verif("un deuxième envoi : refusé, rien ne repart", not r["ok"] and len(envois()) == 1, r)

# S5 de la relecture, avec le vrai serveur : un second brouillon prend la place du premier sans que l'outil le sache
preparer("msg006", texte="Version A")
mail_commande.preparer("pirate@example.org", "B", "Version B", "gmail")       # un autre appelant fige B
r = envoyer("msg007", "msg006")
verif("un autre brouillon a pris la place : le serveur refuse, rien ne part", not r["ok"] and "plus valable" in r["phrase_pour_utilisateur"] and len(envois()) == 1, r)

# un apercu que le serveur a oublie (redemarrage) : l'outil le dit
preparer("msg008")
os.remove(mail_commande.EN_ATTENTE)
r = envoyer("msg009", "msg008")
verif("aperçu oublié par le serveur : dit clairement", not r["ok"] and "plus valable" in r["phrase_pour_utilisateur"] and len(envois()) == 1, r)

# un apercu de plus de deux heures cote serveur (l'outil, lui, le croit encore frais) : le serveur refuse
preparer("msg010")
vieux = json.load(open(mail_commande.EN_ATTENTE, encoding="utf-8"))
vieux["cree_le"] = (datetime.now() - timedelta(hours=2, minutes=1)).isoformat(timespec="seconds")
json.dump(vieux, open(mail_commande.EN_ATTENTE, "w", encoding="utf-8"))
r = envoyer("msg011", "msg010")
verif("aperçu de plus de 2 h côté serveur : rien ne part", not r["ok"] and "plus valable" in r["phrase_pour_utilisateur"] and len(envois()) == 1, r)

# un brouillon en attente d'une ancienne version du serveur (sans empreinte) : jamais envoye
preparer("msg012")
vieux = json.load(open(mail_commande.EN_ATTENTE, encoding="utf-8")); del vieux["empreinte"]
json.dump(vieux, open(mail_commande.EN_ATTENTE, "w", encoding="utf-8"))
r = envoyer("msg013", "msg012")
verif("brouillon en attente sans empreinte : rien ne part", not r["ok"] and len(envois()) == 1, r)

# le mail part, puis le serveur n'arrive pas a effacer son fichier : il dit quand meme « envoye »
preparer("msg014")
vrai_remove, mail_commande.os.remove = mail_commande.os.remove, lambda *_a: (_ for _ in ()).throw(PermissionError("fichier utilise"))
try:
    r = envoyer("msg015", "msg014")
finally:
    mail_commande.os.remove = vrai_remove
verif("mail parti malgré une erreur de fichier : le serveur dit « envoyé »", r["ok"] and r.get("statut") == "ENVOYE" and len(envois()) == 2, r)
M.oublier(mail_commande.EN_ATTENTE)

# la boite Outlook non reliee, puis Gmail non relie
r = preparer("msg016", boite="outlook")
verif("Outlook non relié : dit, et le brouillon en texte est proposé", not r["ok"] and r.get("non_relie") and "en texte" in r["phrase_pour_utilisateur"], r)
RELIE["gmail"] = False
r = preparer("msg017")
verif("Gmail non relié : dit, sans détail technique", not r["ok"] and r.get("non_relie") and "OAuth" not in json.dumps(r, ensure_ascii=False), r)
r = appel(action="chercher", texte="notaire")
verif("chercher sans compte relié : dit", not r["ok"] and r.get("non_relie"), r)
r = appel(action="contact", nom="notaire")
verif("contact sans compte relié : aucune adresse, pas de plantage", r.get("nombre", 0) == 0, r)

serveur.should_exit = True
print(f"{OK} OK, {KO} ECHEC")
sys.exit(1 if KO else 0)
