# transmettre_document.py - donne a J, sur Telegram, un PDF deja range sur le PC dans .n8n-files\documents\
#   python transmettre_document.py --fichier demande.json
# demande.json : {"action": "liste" | "donner", "nom": "bout du nom du PDF ou du dossier", "mot": "filtre pour la liste"}
# Repond UNE ligne JSON : {"ok", "phrase_pour_utilisateur", "document": chemin du PDF a transmettre (seulement pour donner)}
# Lecture seule : ne cree, ne modifie et ne supprime rien. Ne sort jamais du dossier documents.

import argparse
import json
import os
import sys
import unicodedata
from datetime import datetime

BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
DOCUMENTS = os.path.join(BASE, "documents")
MAX_LISTE = 25


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def simplifier(t):
    t = unicodedata.normalize("NFD", str(t or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.lower().replace("_", " ").replace("-", " ")


def tous_les_pdf():
    res = []
    racine = os.path.realpath(DOCUMENTS)
    if not os.path.isdir(racine):
        return res
    for dossier, sous, fichiers in os.walk(racine):
        sous[:] = [s for s in sous if not s.startswith(".")]
        for f in fichiers:
            if f.lower().endswith(".pdf"):
                chemin = os.path.realpath(os.path.join(dossier, f))
                if not chemin.startswith(racine + os.sep):
                    continue
                try:
                    st = os.stat(chemin)
                except OSError:
                    continue
                rel = os.path.relpath(chemin, racine)
                res.append({"nom": f, "dossier": os.path.dirname(rel) or ".", "chemin": chemin,
                            "date": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M"), "ko": round(st.st_size / 1024),
                            "_t": st.st_mtime})
    res.sort(key=lambda x: -x["_t"])
    return res


def filtrer(pdfs, texte):
    mots = [m for m in simplifier(texte).split() if m]
    if not mots:
        return pdfs
    out = []
    for p in pdfs:
        cible = simplifier(p["nom"] + " " + p["dossier"])
        if all(m in cible for m in mots):
            out.append(p)
    return out


def decrire(p):
    d = "" if p["dossier"] == "." else f" (dossier {p['dossier']})"
    return f"{p['nom']}{d}, {p['date']}, {p['ko']} Ko"


def liste(mot):
    pdfs = filtrer(tous_les_pdf(), mot)
    if not pdfs:
        if mot:
            return repondre(True, f"Aucun PDF ne correspond à « {mot} » dans le dossier documents.", documents=[])
        return repondre(True, "Le dossier documents ne contient aucun PDF.", documents=[])
    lignes = [decrire(p) for p in pdfs[:MAX_LISTE]]
    suite = f" (et {len(pdfs) - MAX_LISTE} autres)" if len(pdfs) > MAX_LISTE else ""
    return repondre(True, f"{len(pdfs)} PDF trouvé(s){suite} : " + " ; ".join(lignes),
                    documents=[{"nom": p["nom"], "dossier": p["dossier"], "date": p["date"]} for p in pdfs[:MAX_LISTE]])


def donner(nom):
    if not str(nom or "").strip():
        return repondre(False, "Dis-moi quel document tu veux : un bout de son nom (ex. « facture ») ou le nom du dossier (ex. « contrats »).")
    pdfs = filtrer(tous_les_pdf(), nom)
    if not pdfs:
        return repondre(False, f"Je ne trouve aucun PDF qui ressemble à « {nom} » dans le dossier documents. Demande la liste pour voir ce qu'il y a.")
    if len(pdfs) > 1:
        lignes = [decrire(p) for p in pdfs[:MAX_LISTE]]
        return repondre(False, f"Plusieurs documents correspondent à « {nom} », précise lequel : " + " ; ".join(lignes),
                        documents=[{"nom": p["nom"], "dossier": p["dossier"]} for p in pdfs[:MAX_LISTE]])
    p = pdfs[0]
    return repondre(True, f"C'est fait : je te transmets « {p['nom']} » ({p['ko']} Ko, du {p['date']}).", document=p["chemin"])


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier", required=True)
    a = pa.parse_args()
    try:
        with open(a.fichier, encoding="utf-8-sig") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {"nom": str(d)}
    except Exception:
        return repondre(False, "La demande est illisible.")
    action = simplifier(d.get("action") or "").strip()
    nom = d.get("nom") or d.get("document") or d.get("fichier") or d.get("titre") or ""
    mot = d.get("mot") or d.get("filtre") or ""
    if action in ("liste", "lister", "list", "voir"):
        return liste(mot or nom)
    if action in ("donner", "donne", "transmettre", "transmets", "recevoir", "telegram", "") :
        if not str(nom).strip() and str(mot).strip():
            nom = mot
        if not str(nom).strip() and action == "":
            return liste("")
        return donner(nom)
    return repondre(False, f"Action inconnue « {action} » : utilise liste ou donner.")


if __name__ == "__main__":
    main()
