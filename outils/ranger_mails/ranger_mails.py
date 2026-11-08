# ranger_mails.py - outil maison d'Archi : ranger les mails de J dans des dossiers / sous-dossiers,
# dans Gmail (libelles « Parent/Enfant ») et dans Outlook (vrais dossiers).
#
#   python ranger_mails.py --fichier demande.json
#   demande.json : {"compte": "gmail" | "outlook", "action": "...", ...}
#     dossiers                                   liste les dossiers / sous-dossiers
#     creer_dossier   chemin="Factures/EDF"      cree le dossier (et son parent) s'il manque
#     deplacer        vers="Factures/EDF"        dossier d'arrivee (cree s'il manque)
#                     depuis="inbox"             dossier de depart (boite de reception par defaut)
#                     expediteur, sujet, apres="AAAA-MM-JJ", avant="AAAA-MM-JJ", ids=[...]   (au moins un)
#                     confirmer=true             sinon : ESSAI A BLANC (rien ne bouge)
#     annuler                                    remet a leur place les mails du dernier rangement
#     chercher        dans="envoyes"             LECTURE SEULE (05/11, accord de J) : liste les mails d'un dossier,
#                                                y compris envoyes / brouillons / indesirables / corbeille ; ne deplace RIEN.
#                     expediteur, destinataire, sujet, apres, avant ; 20 resultats au plus (les plus recents)
#     journal                                    les derniers rangements
#
# Repond UNE ligne JSON : {"ok": true/false, "phrase_pour_utilisateur": "...", ...}
#
# Connexions : celles d'Archi (gmail_tool.py / outlook_tool.py d'assistant-main), sans jamais ouvrir de
# fenetre de connexion : si la connexion a expire, l'outil le dit et s'arrete.
# Ne fait JAMAIS : supprimer un mail ou un dossier, envoyer un mail, DEPLACER les mails envoyes / brouillons
# (chercher peut seulement les LIRE : objet, expediteur, destinataires, date ; jamais le texte ni les pieces jointes).

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime

DOSSIER = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(DOSSIER, "journal.jsonl")
# connexions Gmail / Outlook du serveur Python d'Archi (dossier serveur/ du depot) ; ARCHI_ASSISTANT pour un autre dossier
ASSISTANT = os.environ.get("ARCHI_ASSISTANT") or (os.path.join(os.environ["ARCHI_DEPOT"], "serveur") if os.environ.get("ARCHI_DEPOT")
             else os.path.join(os.path.expanduser("~"), ".n8n", "assistant", "assistant-main"))
MAX_MAILS = 200
NB_EXEMPLES = 5
NOMS_RECEPTION = {"inbox", "boite de reception", "boîte de réception", "reception", "réception"}


class Erreur(Exception):
    """Probleme a expliquer simplement a J."""


def repondre(ok, phrase, **extra):
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def lire_json(chemin, defaut=None):
    try:
        with open(chemin, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return defaut


def nettoyer_chemin(chemin):
    """« Factures / EDF » -> ["Factures", "EDF"] ; refuse un chemin vide."""
    morceaux = [m.strip() for m in re.split(r"[/\\]", str(chemin or "")) if m.strip()]
    if not morceaux:
        raise Erreur("Il manque le nom du dossier (par exemple « Factures/EDF »).")
    return morceaux


def est_reception(chemin):
    return str(chemin or "inbox").strip().lower() in NOMS_RECEPTION


def dossier_special(nom):
    """« Elements envoyes », « envoyes », « sent »... -> cle commune (ou "" si dossier ordinaire)."""
    import unicodedata
    n = unicodedata.normalize("NFD", str(nom or "")).encode("ascii", "ignore").decode().lower()
    for cle, mots in (("envoyes", ("envoy", "sent", "envoi", "outbox")), ("brouillons", ("brouillon", "draft")),
                      ("indesirables", ("indesirable", "spam", "junk")),
                      ("corbeille", ("corbeille", "supprim", "trash", "deleted"))):
        if any(m in n for m in mots):
            return cle
    return ""


def lire_date(texte, nom):
    if not texte:
        return None
    try:
        return datetime.strptime(str(texte).strip()[:10], "%Y-%m-%d")
    except ValueError:
        raise Erreur(f"La date « {texte} » ({nom}) doit s'ecrire AAAA-MM-JJ, par exemple 2026-01-31.")


def lire_criteres(demande):
    ids = demande.get("ids") or []
    if isinstance(ids, str):
        ids = [i for i in re.split(r"[,\s]+", ids) if i]
    criteres = {
        "expediteur": str(demande.get("expediteur") or "").strip(),
        "sujet": str(demande.get("sujet") or "").strip(),
        "apres": lire_date(demande.get("apres"), "apres"),
        "avant": lire_date(demande.get("avant"), "avant"),
        "ids": [str(i).strip() for i in ids if str(i).strip()],
    }
    if not any(criteres.values()):
        raise Erreur("Dis-moi quels mails ranger : un expediteur, un mot du sujet, une periode, ou des mails precis.")
    return criteres


def oui(valeur):
    return valeur is True or str(valeur).strip().lower() in {"true", "oui", "1", "yes"}


# ---------- connexions d'Archi (sans fenetre de connexion) ----------

def _preparer_assistant():
    if not os.path.isdir(ASSISTANT):
        raise Erreur("Je ne trouve pas le dossier d'Archi qui contient les connexions mail.")
    os.chdir(ASSISTANT)  # les fichiers de connexion d'Archi sont lus depuis ce dossier
    if ASSISTANT not in sys.path:
        sys.path.insert(0, ASSISTANT)


class _PasDeFenetre:
    """Remplace la connexion interactive : on ne doit jamais ouvrir le navigateur depuis l'outil."""
    @staticmethod
    def from_client_secrets_file(*_a, **_k):
        raise Erreur("La connexion Gmail d'Archi a expire : il faut se reconnecter a Google une fois.")


# ---------- Gmail : libelles ----------

class Gmail:
    nom = "Gmail"

    def __init__(self):
        _preparer_assistant()
        import gmail_tool
        gmail_tool.InstalledAppFlow = _PasDeFenetre
        self.s = gmail_tool.get_service().users()
        self._libelles = None

    def libelles(self, frais=False):
        if self._libelles is None or frais:
            self._libelles = self.s.labels().list(userId="me").execute().get("labels", [])
        return self._libelles

    def dossiers(self):
        return sorted(l["name"] for l in self.libelles() if l.get("type") == "user")

    def trouver(self, chemin):
        if est_reception(chemin):
            return "INBOX"
        nom = "/".join(nettoyer_chemin(chemin)).lower()
        return next((l["id"] for l in self.libelles() if l["name"].lower() == nom), None)

    def creer(self, chemin):
        morceaux, cree = nettoyer_chemin(chemin), False
        for i in range(1, len(morceaux) + 1):  # parent d'abord, puis le sous-dossier
            nom = "/".join(morceaux[:i])
            if not self.trouver(nom):
                self.s.labels().create(userId="me", body={"name": nom, "labelListVisibility": "labelShow",
                                                          "messageListVisibility": "show"}).execute()
                self.libelles(frais=True)
                cree = True
        return self.trouver(chemin), cree

    def chercher(self, source, c):
        """Mails a ranger (au plus MAX_MAILS + 1, pour savoir s'il y en a trop)."""
        if c["ids"]:
            mails = []
            for i in c["ids"][:MAX_MAILS + 1]:
                m = self.s.messages().get(userId="me", id=i, format="metadata",
                                          metadataHeaders=["From", "Subject", "Date"]).execute()
                lbl = m.get("labelIds", [])
                if source in lbl and not {"SENT", "DRAFT"} & set(lbl):
                    mails.append(self._resume(m, source))
            return mails
        q = ["-in:sent", "-in:drafts"]
        if c["expediteur"]:
            q.append(f'from:({c["expediteur"]})')
        if c["sujet"]:
            q.append(f'subject:("{c["sujet"]}")')
        if c["apres"]:
            q.append("after:" + c["apres"].strftime("%Y/%m/%d"))
        if c["avant"]:
            q.append("before:" + c["avant"].strftime("%Y/%m/%d"))
        ids, page = [], None
        while len(ids) <= MAX_MAILS:
            r = self.s.messages().list(userId="me", labelIds=[source], q=" ".join(q), maxResults=100,
                                       pageToken=page).execute()
            ids += [m["id"] for m in r.get("messages", [])]
            page = r.get("nextPageToken")
            if not page:
                break
        return [{"id": i, "origine": source} for i in ids[:MAX_MAILS + 1]]

    def details(self, mails):
        out = []
        for m in mails:
            if "sujet" in m:
                out.append(m)
            else:
                g = self.s.messages().get(userId="me", id=m["id"], format="metadata",
                                          metadataHeaders=["From", "Subject", "Date"]).execute()
                out.append(self._resume(g, m["origine"]))
        return out

    @staticmethod
    def _resume(m, origine):
        h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
        return {"id": m["id"], "origine": origine, "de": h.get("from", ""), "sujet": h.get("subject", ""),
                "date": h.get("date", "")}

    SPECIAUX = {"envoyes": "SENT", "brouillons": "DRAFT", "indesirables": "SPAM", "corbeille": "TRASH"}

    def lister(self, dans, c, limite):
        """LECTURE SEULE : objet, expediteur, destinataires, date des mails d'un dossier (jamais le texte)."""
        special = self.SPECIAUX.get(dossier_special(dans))
        source = special or self.trouver(dans)
        if not source:
            raise Erreur(f"Je ne trouve pas le dossier « {dans} » dans Gmail.")
        q = []
        if c["expediteur"]:
            q.append(f'from:({c["expediteur"]})')
        if c["destinataire"]:
            q.append(f'to:({c["destinataire"]})')
        if c["sujet"]:
            q.append(f'subject:("{c["sujet"]}")')
        if c["apres"]:
            q.append("after:" + c["apres"].strftime("%Y/%m/%d"))
        if c["avant"]:
            q.append("before:" + c["avant"].strftime("%Y/%m/%d"))
        r = self.s.messages().list(userId="me", labelIds=[source], q=" ".join(q), maxResults=limite,
                                   includeSpamTrash=source in ("SPAM", "TRASH")).execute()
        out = []
        for m in r.get("messages", [])[:limite]:
            g = self.s.messages().get(userId="me", id=m["id"], format="metadata",
                                      metadataHeaders=["From", "To", "Cc", "Subject", "Date"]).execute()
            h = {x["name"].lower(): x["value"] for x in g.get("payload", {}).get("headers", [])}
            dest = ", ".join(x for x in (h.get("to", ""), h.get("cc", "")) if x)
            out.append({"id": g["id"], "de": h.get("from", ""), "a": dest,
                        "sujet": h.get("subject", ""), "date": h.get("date", "")})
        return out

    def deplacer(self, mails, dest):
        """Pose le libelle d'arrivee et retire celui de depart. Les identifiants Gmail ne changent pas."""
        par_origine = {}
        for m in mails:
            par_origine.setdefault(m["origine"], []).append(m["id"])
        for origine, ids in par_origine.items():
            self.s.messages().batchModify(userId="me", body={"ids": ids, "addLabelIds": [dest],
                                                             "removeLabelIds": [origine]}).execute()
        return [{"id": m["id"], "origine": m["origine"]} for m in mails]

    def remettre(self, mails, dest):
        par_origine = {}
        for m in mails:
            par_origine.setdefault(m["origine"], []).append(m["id"])
        for origine, ids in par_origine.items():
            self.s.messages().batchModify(userId="me", body={"ids": ids, "addLabelIds": [origine],
                                                             "removeLabelIds": [dest]}).execute()
        return len(mails)


# ---------- Outlook : vrais dossiers ----------

class Outlook:
    nom = "Outlook"
    INTERDITS = {"sentitems", "drafts", "deleteditems", "outbox"}  # jamais touches

    def __init__(self):
        _preparer_assistant()
        import outlook_tool
        import requests

        def pas_de_fenetre(*_a, **_k):
            raise Erreur("La connexion Outlook d'Archi a expire : il faut se reconnecter a Microsoft une fois.")
        outlook_tool._app.acquire_token_interactive = pas_de_fenetre
        self.ot, self.rq, self.G = outlook_tool, requests, outlook_tool.GRAPH
        self._arbre = None
        self.interdits_ids = None

    def appel(self, methode, url, **kw):
        if not url.startswith("http"):
            url = self.G + url
        r = self.rq.request(methode, url, headers={"Authorization": "Bearer " + self.ot.get_token()},
                            timeout=60, **kw)
        if not r.ok:
            raise Erreur(f"Outlook a refuse la demande (erreur {r.status_code}).")
        return r.json() if r.content else {}

    def arbre(self, frais=False):
        """{chemin en minuscules: (chemin, id)} de tous les dossiers et sous-dossiers."""
        if self._arbre is None or frais:
            arbre = {}

            def descendre(url, parent):
                while url:
                    r = self.appel("GET", url)
                    for d in r.get("value", []):
                        chemin = (parent + "/" if parent else "") + d["displayName"]
                        arbre[chemin.lower()] = (chemin, d["id"])
                        if d.get("childFolderCount"):
                            descendre(f"/me/mailFolders/{d['id']}/childFolders?$top=100", chemin)
                    url = r.get("@odata.nextLink")
            descendre("/me/mailFolders?$top=100", "")
            self._arbre = arbre
        return self._arbre

    def ids_interdits(self):
        if self.interdits_ids is None:
            self.interdits_ids = set()
            for nom in self.INTERDITS:
                try:
                    self.interdits_ids.add(self.appel("GET", f"/me/mailFolders/{nom}?$select=id")["id"])
                except Erreur:
                    pass
        return self.interdits_ids

    def dossiers(self):
        return sorted(c for c, _ in self.arbre().values())

    def trouver(self, chemin):
        if est_reception(chemin):
            return self.appel("GET", "/me/mailFolders/inbox?$select=id")["id"]
        trouve = self.arbre().get("/".join(nettoyer_chemin(chemin)).lower())
        return trouve[1] if trouve else None

    def creer(self, chemin):
        morceaux, parent, cree = nettoyer_chemin(chemin), None, False
        for i in range(1, len(morceaux) + 1):
            nom = "/".join(morceaux[:i])
            existe = self.trouver(nom)
            if not existe:
                url = f"/me/mailFolders/{parent}/childFolders" if parent else "/me/mailFolders"
                existe = self.appel("POST", url, json={"displayName": morceaux[i - 1]})["id"]
                self.arbre(frais=True)
                cree = True
            parent = existe
        return parent, cree

    def chercher(self, source, c):
        if source in self.ids_interdits():
            raise Erreur("Je ne touche pas aux mails envoyes, aux brouillons ni a la corbeille.")
        champs = "$select=id,subject,from,receivedDateTime,parentFolderId"
        if c["ids"]:
            mails = []
            for i in c["ids"][:MAX_MAILS + 1]:
                m = self.appel("GET", f"/me/messages/{i}?{champs}")
                if m.get("parentFolderId") == source:
                    mails.append(self._resume(m))
            return mails
        filtres = []
        if "@" in c["expediteur"]:
            filtres.append(f"from/emailAddress/address eq '{c['expediteur'].replace(chr(39), chr(39) * 2)}'")
        if c["apres"]:
            filtres.append(f"receivedDateTime ge {c['apres'].strftime('%Y-%m-%d')}T00:00:00Z")
        if c["avant"]:
            filtres.append(f"receivedDateTime lt {c['avant'].strftime('%Y-%m-%d')}T00:00:00Z")
        url = f"/me/mailFolders/{source}/messages?{champs}&$top=100"
        if filtres:
            url += "&$filter=" + " and ".join(filtres)
        mails, lus = [], 0
        while url and len(mails) <= MAX_MAILS and lus < 5000:
            r = self.appel("GET", url)
            for m in r.get("value", []):
                lus += 1
                if self._correspond(m, c):
                    mails.append(self._resume(m))
            url = r.get("@odata.nextLink")
        return mails[:MAX_MAILS + 1]

    @staticmethod
    def _correspond(m, c):
        """Criteres verifies ici : expediteur partiel (« edf ») et mot du sujet."""
        exp = m.get("from", {}).get("emailAddress", {})
        if c["expediteur"] and "@" not in c["expediteur"]:
            if c["expediteur"].lower() not in (exp.get("address", "") + " " + exp.get("name", "")).lower():
                return False
        if c["sujet"] and c["sujet"].lower() not in (m.get("subject") or "").lower():
            return False
        return True

    @staticmethod
    def _resume(m):
        exp = m.get("from", {}).get("emailAddress", {})
        return {"id": m["id"], "origine": m.get("parentFolderId"), "de": exp.get("address", ""),
                "sujet": m.get("subject", ""), "date": m.get("receivedDateTime", "")}

    def details(self, mails):
        return mails

    SPECIAUX = {"envoyes": "sentitems", "brouillons": "drafts", "indesirables": "junkemail", "corbeille": "deleteditems"}

    def lister(self, dans, c, limite):
        """LECTURE SEULE : objet, expediteur, destinataires, date des mails d'un dossier (jamais le texte).
        Les dossiers interdits au rangement (envoyes, brouillons...) sont permis ici : on ne fait que lire."""
        special = self.SPECIAUX.get(dossier_special(dans))
        if special:
            source = self.appel("GET", f"/me/mailFolders/{special}?$select=id")["id"]
        else:
            source = self.trouver(dans)
        if not source:
            raise Erreur(f"Je ne trouve pas le dossier « {dans} » dans Outlook.")
        champ_date = "sentDateTime" if special in ("sentitems", "drafts") else "receivedDateTime"
        champs = f"$select=id,subject,from,toRecipients,ccRecipients,{champ_date}&$orderby={champ_date} desc"
        filtres = []
        if c["apres"]:
            filtres.append(f"{champ_date} ge {c['apres'].strftime('%Y-%m-%d')}T00:00:00Z")
        if c["avant"]:
            filtres.append(f"{champ_date} lt {c['avant'].strftime('%Y-%m-%d')}T00:00:00Z")
        url = f"/me/mailFolders/{source}/messages?{champs}&$top=50"
        if filtres:
            url += "&$filter=" + " and ".join(filtres)
        out, lus = [], 0
        while url and len(out) < limite and lus < 2000:
            r = self.appel("GET", url)
            for m in r.get("value", []):
                lus += 1
                exp = m.get("from", {}).get("emailAddress", {})
                dest = [x.get("emailAddress", {}) for x in (m.get("toRecipients") or []) + (m.get("ccRecipients") or [])]
                texte_dest = ", ".join(f"{d.get('name', '')} <{d.get('address', '')}>" for d in dest)
                if c["expediteur"] and c["expediteur"].lower() not in (exp.get("address", "") + " " + exp.get("name", "")).lower():
                    continue
                if c["destinataire"] and c["destinataire"].lower() not in texte_dest.lower():
                    continue
                if c["sujet"] and c["sujet"].lower() not in (m.get("subject") or "").lower():
                    continue
                out.append({"id": m["id"], "de": exp.get("address", ""), "a": texte_dest,
                            "sujet": m.get("subject", ""), "date": m.get(champ_date, "")})
                if len(out) >= limite:
                    break
            url = r.get("@odata.nextLink")
        return out

    def _lot(self, demandes):
        """Envoie les deplacements par paquets de 20 ($batch). Renvoie {numero: nouvel id}."""
        nouveaux = {}
        for i in range(0, len(demandes), 20):
            paquet = [{"id": str(n), "method": "POST", "url": f"/me/messages/{mid}/move",
                       "headers": {"Content-Type": "application/json"}, "body": {"destinationId": dest}}
                      for n, (mid, dest) in enumerate(demandes[i:i + 20], start=i)]
            r = self.appel("POST", "/$batch", json={"requests": paquet})
            for rep in r.get("responses", []):
                if 200 <= rep.get("status", 500) < 300:
                    nouveaux[int(rep["id"])] = rep.get("body", {}).get("id")
        return nouveaux

    def deplacer(self, mails, dest):
        """Outlook change l'identifiant d'un mail deplace : on note le nouveau pour pouvoir annuler."""
        nouveaux = self._lot([(m["id"], dest) for m in mails])
        return [{"id": nouveaux[n], "origine": m["origine"]} for n, m in enumerate(mails) if nouveaux.get(n)]

    def remettre(self, mails, _dest):
        return len(self._lot([(m["id"], m["origine"]) for m in mails]))


COMPTES = {"gmail": Gmail, "outlook": Outlook}


# ---------- journal ----------

def journal_lire():
    lignes = []
    try:
        with open(JOURNAL, encoding="utf-8") as f:
            for l in f:
                try:
                    lignes.append(json.loads(l))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return lignes


def journal_ecrire(entree):
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")


def lots_actifs(compte=None):
    lignes = journal_lire()
    annules = {l["annule_lot"] for l in lignes if "annule_lot" in l}
    return [l for l in lignes if "lot" in l and l["lot"] not in annules and (not compte or l["compte"] == compte)]


# ---------- actions ----------

def a_dossiers(boite, _d):
    liste = boite.dossiers()
    if not liste:
        return f"Tu n'as encore aucun dossier perso dans {boite.nom}.", {"dossiers": []}
    return (f"Tu as {len(liste)} dossiers dans {boite.nom} : " + ", ".join(liste[:30])
            + (" ..." if len(liste) > 30 else "") + "."), {"dossiers": liste}


def a_creer(boite, d):
    chemin = "/".join(nettoyer_chemin(d.get("chemin")))
    _, cree = boite.creer(chemin)
    if cree:
        return f"J'ai cree le dossier « {chemin} » dans {boite.nom}.", {"chemin": chemin, "cree": True}
    return f"Le dossier « {chemin} » existait deja dans {boite.nom}, je n'ai rien cree.", {"chemin": chemin, "cree": False}


def a_deplacer(boite, d, compte):
    vers = "/".join(nettoyer_chemin(d.get("vers") or d.get("chemin")))
    criteres = lire_criteres(d)
    depuis = str(d.get("depuis") or "inbox")
    if est_reception(vers):
        raise Erreur("Pour remettre des mails dans la boite de reception, utilise « annuler ».")
    # ranger vers la corbeille, les indesirables ou un dossier systeme = supprimer : refuse
    if dossier_special(vers) or vers.strip().upper() in {"TRASH", "SPAM", "SENT", "DRAFT", "DELETEDITEMS", "JUNKEMAIL",
                                                         "SENTITEMS", "DRAFTS", "OUTBOX", "IMPORTANT", "STARRED", "UNREAD"}:
        raise Erreur("Je ne range pas vers la corbeille, les indesirables, les envoyes ni les brouillons : "
                     "ce serait supprimer ou deguiser des mails. Choisis un dossier a toi.")
    source = boite.trouver(depuis)
    if not source:
        raise Erreur(f"Je ne trouve pas le dossier de depart « {depuis} » dans {boite.nom}.")
    mails = boite.chercher(source, criteres)
    trop = len(mails) > MAX_MAILS
    mails = mails[:MAX_MAILS]
    nom_depuis = "la boite de reception" if est_reception(depuis) else f"« {depuis} »"
    if not mails:
        return f"Aucun mail ne correspond dans {nom_depuis} de {boite.nom}. Rien n'a bouge.", {"nombre": 0}
    exemples = [{k: m.get(k, "") for k in ("id", "de", "sujet", "date")} for m in boite.details(mails[:NB_EXEMPLES])]
    nombre = f"plus de {MAX_MAILS}" if trop else str(len(mails))

    if not oui(d.get("confirmer")):
        phrase = (f"Essai a blanc : {nombre} mails de {nom_depuis} iraient dans « {vers} » ({boite.nom}). "
                  "Rien n'a bouge. Pour ranger pour de vrai, redemande avec confirmer.")
        if trop:
            phrase += f" Je ne range que {MAX_MAILS} mails par fois."
        return phrase, {"essai": True, "nombre": len(mails), "trop": trop, "exemples": exemples}

    dest, cree = boite.creer(vers)
    # double verrou : on compare aussi les IDENTIFIANTS des dossiers systeme (pas seulement les noms)
    interdits = set(getattr(boite, "INTERDITS", set())) | {"junkemail", "deleteditems", "TRASH", "SPAM", "SENT", "DRAFT"}
    if str(dest) in interdits or str(dest).lower() in {x.lower() for x in interdits}:
        raise Erreur("Ce dossier est un dossier systeme (corbeille, indesirables, envoyes, boite d'envoi) : je n'y range rien.")
    if dest == source:
        raise Erreur("Le dossier d'arrivee est le meme que le dossier de depart.")
    deplaces = boite.deplacer(mails, dest)
    lot = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    journal_ecrire({"lot": lot, "date": datetime.now().isoformat(timespec="seconds"), "compte": compte,
                    "vers": dest, "vers_nom": vers, "depuis_nom": depuis, "mails": deplaces})
    phrase = f"J'ai range {len(deplaces)} mails dans « {vers} » ({boite.nom})."
    if cree:
        phrase += " J'ai cree ce dossier au passage."
    if len(deplaces) < len(mails):
        phrase += f" {len(mails) - len(deplaces)} n'ont pas pu etre deplaces."
    if trop:
        phrase += f" Il en reste d'autres : je n'en range que {MAX_MAILS} par fois."
    return phrase, {"essai": False, "lot": lot, "nombre": len(deplaces), "trop": trop, "exemples": exemples}


def a_annuler(boite, _d, compte):
    lots = lots_actifs(compte)
    if not lots:
        return f"Il n'y a aucun rangement {boite.nom} a annuler.", {"nombre": 0}
    dernier = lots[-1]
    n = boite.remettre(dernier["mails"], dernier["vers"])
    journal_ecrire({"annule_lot": dernier["lot"], "date": datetime.now().isoformat(timespec="seconds"),
                    "compte": compte, "remis": n})
    return (f"J'ai remis {n} mails a leur place d'origine (rangement du {dernier['date'][:16].replace('T', ' a ')} "
            f"vers « {dernier['vers_nom']} »)."), {"lot": dernier["lot"], "nombre": n}


def a_journal(_boite, _d, compte):
    lots = lots_actifs(compte)[-10:]
    if not lots:
        return "Aucun rangement en cours dans le journal.", {"rangements": []}
    resume = [{"date": l["date"][:16].replace("T", " "), "compte": l["compte"], "vers": l["vers_nom"],
               "nombre": len(l["mails"])} for l in lots]
    phrase = "Derniers rangements : " + " ; ".join(
        f"{r['date']}, {r['nombre']} mails {r['compte']} vers « {r['vers']} »" for r in resume) + "."
    return phrase, {"rangements": resume}


def a_chercher(boite, d, compte):
    """LECTURE SEULE : ne deplace, ne supprime et n'envoie jamais rien."""
    dans = str(d.get("dans") or d.get("depuis") or d.get("chemin") or "inbox")
    c = {"expediteur": str(d.get("expediteur") or "").strip(), "destinataire": str(d.get("destinataire") or "").strip(),
         "sujet": str(d.get("sujet") or "").strip(), "apres": lire_date(d.get("apres"), "apres"),
         "avant": lire_date(d.get("avant"), "avant")}
    try:
        limite = max(1, min(20, int(d.get("nombre") or 10)))
    except (TypeError, ValueError):
        limite = 10
    mails = boite.lister(dans, c, limite)
    sp = dossier_special(dans)
    nom = {"envoyes": "les mails envoyes", "brouillons": "les brouillons", "indesirables": "les indesirables",
           "corbeille": "la corbeille"}.get(sp, "la boite de reception" if est_reception(dans) else f"« {dans} »")
    if not mails:
        return f"Je n'ai trouve aucun mail correspondant dans {nom} de {boite.nom}.", {"nombre": 0, "mails": []}
    lignes = [f"{m['date'][:10]} : {m['sujet'] or '(sans objet)'} (de {m['de']}, a {m['a'] or '?'})" for m in mails[:5]]
    phrase = f"J'ai trouve {len(mails)} mail(s) dans {nom} de {boite.nom} (rien n'a bouge) : " + " ; ".join(lignes)
    return phrase, {"nombre": len(mails), "mails": mails}


ACTIONS = {"dossiers": a_dossiers, "creer_dossier": a_creer}
ACTIONS_COMPTE = {"deplacer": a_deplacer, "annuler": a_annuler, "journal": a_journal, "chercher": a_chercher}


def executer(demande, fabrique=None):
    """fabrique : pour les tests (fausse boite mail a la place de Gmail / Outlook)."""
    if isinstance(demande.get("parametres"), dict):  # accepte aussi {"parametres": {...}}
        demande = {**demande, **demande["parametres"]}
    if isinstance(demande.get("criteres"), dict):  # 05/11 : criteres groupes {"criteres": {...}} acceptes aussi
        demande = {**demande, **demande["criteres"]}
    # tolerance (ajout du 29/10) : le modele local oublie souvent action ou compte -> on deduit
    demande = dict(demande)
    for alias, vrai in (("de", "expediteur"), ("from", "expediteur"), ("mot", "sujet"), ("texte", "sujet"),
                        ("contient", "sujet"), ("dossier", "chemin"), ("destination", "vers")):
        if demande.get(alias) and not demande.get(vrai):
            demande[vrai] = demande[alias]
    action = str(demande.get("action") or "").strip().lower().replace("-", "_").replace(" ", "_")
    action = {"creer": "creer_dossier", "creer_un_dossier": "creer_dossier", "ranger": "deplacer", "deplace": "deplacer",
              "lister": "dossiers", "liste": "dossiers", "annule": "annuler", "rechercher": "chercher",
              "trouver": "chercher", "lire": "chercher", "voir": "chercher", "cherche": "chercher"}.get(action, action)
    if not action:
        a_des_criteres = any(demande.get(k) for k in ("expediteur", "sujet", "apres", "avant", "ids"))
        if demande.get("vers") or (demande.get("chemin") and a_des_criteres):
            action = "deplacer"
        elif demande.get("chemin"):
            action = "creer_dossier"
        else:
            action = "dossiers"
    if action not in ACTIONS and action not in ACTIONS_COMPTE:
        raise Erreur("Je ne connais pas cette commande. Choix possibles : dossiers, creer_dossier, "
                     "deplacer, annuler, journal, chercher. Exemple : {\"compte\": \"outlook\", \"action\": \"deplacer\", "
                     "\"vers\": \"Liasse fiscale\", \"sujet\": \"liasse fiscale\", \"confirmer\": true}")
    compte = str(demande.get("compte") or demande.get("boite") or "").strip().lower()
    if not compte and action != "journal":
        compte = "outlook"          # par defaut : la boite principale de J (signale dans la reponse)
        demande["_compte_par_defaut"] = True
    if action == "journal" and not compte:
        return a_journal(None, demande, None)
    if compte not in COMPTES:
        raise Erreur("Precise le compte : gmail ou outlook.")
    # verifications sans Internet d'abord
    if action == "creer_dossier":
        nettoyer_chemin(demande.get("chemin"))
    if action == "deplacer":
        nettoyer_chemin(demande.get("vers") or demande.get("chemin"))
        lire_criteres(demande)
    boite = (fabrique or COMPTES[compte])()
    if action in ACTIONS:
        return ACTIONS[action](boite, demande)
    return ACTIONS_COMPTE[action](boite, demande, compte)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fichier", required=True)
    args = p.parse_args()
    demande = lire_json(args.fichier)
    if not isinstance(demande, dict):
        return repondre(False, "La demande est illisible.")
    action = str(demande.get("action") or "")
    try:
        phrase, extra = executer(demande)
        if not demande.get("compte") and not demande.get("boite") and action != "journal":
            phrase += " (Boîte Outlook, prise par défaut.)"
        repondre(True, phrase, action=action, **extra)
    except Erreur as e:
        repondre(False, str(e), action=action)
    except Exception as e:  # imprevu : message court
        repondre(False, f"Probleme imprevu avec la boite mail ({type(e).__name__} : {str(e)[:150]}).", action=action)


if __name__ == "__main__":
    main()
