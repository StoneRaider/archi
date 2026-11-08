# recolte.py - recolte en arriere-plan des videos d'une ou plusieurs chaines YouTube vers la Bibliotheque du chateau.
#   python recolte.py demande.json      {"chaines": ["Nom de la chaine", ...], "mois": 6, "max_par_chaine": 60}
#   python recolte.py --veille          (tache planifiee chaque jour) : nouvelles videos des chaines suivies
# Chaque chaine recoltee est ajoutee a .n8n-files/recolte/veille_chaines.json (sauf "suivre": false dans la demande) :
# la veille quotidienne y recolte les nouvelles videos et ne previent l'utilisateur que s'il y en a.
# Pour chaque chaine : liste ses videos (des plus recentes aux plus anciennes), s'arrete a la limite de date,
# lit les sous-titres (pas de Whisper ici : trop long), fait une fiche detaillee par video avec le modele local,
# et tient un index par chaine (fichiers a plat dans la Bibliotheque). Les videos deja recoltees sont sautees. Previent l'utilisateur a la fin.

import json
import os
import re
import sys
import tempfile
import time
import shutil
import unicodedata
import urllib.request
from datetime import datetime, timedelta

ICI = os.path.dirname(os.path.abspath(__file__))
os.chdir(ICI)
sys.path.insert(0, ICI)
import video as V  # noqa: E402

BIBLIO = os.path.join(os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files"), "memoire", "bibliotheque")
DONNEES = os.path.join(os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files"), "recolte")   # etat, file d'attente, chaines suivies
os.makedirs(DONNEES, exist_ok=True)
ETAT = os.path.join(DONNEES, "recolte_etat.json")
# webhook n8n LOCAL qui previent l'utilisateur a la fin (facultatif)
RETOUR = os.environ.get("ARCHI_WEBHOOK_ALERTE", "")


def slug(t, n=50):
    t = unicodedata.normalize("NFD", str(t).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:n] or "video"


def renvoyer(d):
    if not RETOUR:
        return
    try:
        req = urllib.request.Request(RETOUR, data=json.dumps(d).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=60).read()
    except Exception:
        pass


def ecrire_etat(**kw):
    os.makedirs(os.path.dirname(ETAT), exist_ok=True)
    try:
        e = json.load(open(ETAT, encoding="utf-8"))
    except Exception:
        e = {}
    e.update(kw)
    json.dump(e, open(ETAT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


SUIVIES = os.path.join(DONNEES, "veille_chaines.json")
FILE = os.path.join(DONNEES, "recolte_file.json")     # demandes en attente, dans l'ordre
STOP = os.path.join(DONNEES, "recolte_stop.flag")     # present = arreter la recolte en cours
PYW = os.environ.get("ARCHI_PY") or sys.executable


def lire_file():
    try:
        return json.load(open(FILE, encoding="utf-8"))
    except Exception:
        return []


def ecrire_file(f):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    json.dump(f, open(FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def lancer_detache(demande):
    """lance recolte.py en arriere-plan sur une demande (dict)."""
    f = os.path.join(DONNEES, f"recolte_demande_{int(time.time() * 1000)}.json")
    json.dump(demande, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    import subprocess
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([PYW, os.path.join(ICI, "recolte.py"), f], cwd=ICI, env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=0x00000008 | 0x00000200 | 0x08000000)  # DETACHED | NEW_GROUP | NO_WINDOW
    return p.pid


def demarrer(demande):
    """lance une demande ET marque tout de suite la recolte 'en cours' (sinon un 2e appel une seconde
    plus tard la relancerait en double, vu le 06/11)."""
    pid = lancer_detache(demande)
    noms = [c.get("nom", "?") if isinstance(c, dict) else str(c) for c in demande.get("chaines", [])]
    if demande.get("videos"):
        noms = [f"{len(demande['videos'])} vidéo{'s' if len(demande['videos']) > 1 else ''} à l'unité"]
    ecrire_etat(en_cours=True, pid=pid, debut=datetime.now().isoformat(timespec="seconds"), faites=0,
                chaines=noms, liens=demande.get("videos") or [], veille=False, derniere="", arretee=False)
    return pid


def suivante():
    """a la fin d'une recolte : lance la prochaine demande de la file (s'il y en a)."""
    f = lire_file()
    if not f:
        return None
    d = f.pop(0)
    ecrire_file(f)
    demarrer(d)
    return d


def arret_demande():
    return os.path.exists(STOP)


def lire_suivies():
    """chaines suivies par la veille. Premiere fois : reprend les chaines deja recoltees (index de la Bibliotheque)."""
    try:
        return json.load(open(SUIVIES, encoding="utf-8"))
    except Exception:
        pass
    suivies = []
    try:
        for f in sorted(os.listdir(BIBLIO)):
            if f.startswith("chaine_") and f.endswith(".md"):
                tete = open(os.path.join(BIBLIO, f), encoding="utf-8").read(600)
                nom = (re.search(r"^#\s*\S+\s+(.+)$", tete, re.M) or [None, ""])[1].strip()
                url = (re.search(r"\((https?://[^)\s]+)\)", tete) or [None, ""])[1]
                if nom and url:
                    suivies.append({"nom": nom, "url": url, "depuis": datetime.now().strftime("%Y-%m-%d")})
    except Exception:
        pass
    ecrire_suivies(suivies)
    return suivies


def ecrire_suivies(suivies):
    os.makedirs(os.path.dirname(SUIVIES), exist_ok=True)
    json.dump(suivies, open(SUIVIES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def suivre(nom, url):
    suivies = lire_suivies()
    if not any(c.get("url") == url for c in suivies):
        suivies.append({"nom": nom, "url": url, "depuis": datetime.now().strftime("%Y-%m-%d")})
        ecrire_suivies(suivies)


def trouver_chaine(nom):
    if isinstance(nom, dict):   # chaine suivie : on connait deja son adresse et son vrai nom
        return nom["url"], nom["nom"]
    if nom.startswith("http"):
        return nom.rstrip("/").removesuffix("/videos"), nom
    r = V.ytdlp(["-J", "--flat-playlist", f"ytsearch10:{nom}"], timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"recherche de la chaîne « {nom} » impossible")
    cible = slug(nom)
    candidats = []
    for e in json.loads(r.stdout).get("entries", []):
        ch = e.get("channel") or e.get("uploader") or ""
        url = e.get("channel_url") or (("https://www.youtube.com/channel/" + e["channel_id"]) if e.get("channel_id") else "")
        if url:
            candidats.append((0 if slug(ch) == cible else 1 if cible in slug(ch) else 2, ch, url))
    if not candidats:
        raise RuntimeError(f"chaîne « {nom} » introuvable")
    candidats.sort(key=lambda c: c[0])
    if candidats[0][0] == 2:
        raise RuntimeError(f"aucune chaîne ne s'appelle exactement « {nom} » (la plus proche : {candidats[0][1]})")
    return candidats[0][2], candidats[0][1]


def lister(url_chaine, maxi):
    r = V.ytdlp(["-J", "--flat-playlist", "--playlist-end", str(maxi), url_chaine + "/videos"], timeout=600)
    if r.returncode != 0:
        raise RuntimeError("liste des vidéos impossible")
    return [{"id": e["id"], "titre": e.get("title", "?"), "url": "https://www.youtube.com/watch?v=" + e["id"],
             "duree": int(e.get("duration") or 0), "chaine": ""} for e in json.loads(r.stdout).get("entries", []) if e.get("id")]


def fiche(v, texte, chaine):
    consigne = ("Tu fais une fiche de connaissances en français à partir de la transcription d'une vidéo YouTube, "
                "pour la bibliothèque personnelle de l'utilisateur. N'invente rien. Format STRICT :\n"
                "THEME: un ou deux mots (ex : IA, crypto, espace, économie, géopolitique, technologie)\n"
                "RESUME: deux phrases\n"
                "POINTS:\n- 6 à 12 informations concrètes et vérifiables de la vidéo (faits, chiffres, noms, dates, mécanismes)\n"
                "A_VERIFIER:\n- affirmations douteuses, spéculatives ou présentées sans preuve (ou « Aucune »)\n"
                "UTILE_POUR_MOI: une phrase (lien possible avec ses projets : " + os.environ.get("ARCHI_CENTRES_INTERET", "ses projets en cours") + ") ou « Rien de particulier »")
    corps = {"model": V.MODELE, "temperature": 0.2, "max_tokens": 3500,
             "messages": [{"role": "system", "content": consigne},
                          {"role": "user", "content": f"Chaîne : {chaine}\nTitre : {v['titre']}\n\nTranscription :\n{texte[:V.MAX_TRANSCRIPTION]}"}]}
    req = urllib.request.Request(V.LM, data=json.dumps(corps).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        rep = json.loads(r.read().decode("utf-8"))
    return re.sub(r"(?s)<think>.*?</think>", "", rep["choices"][0]["message"].get("content") or "").strip()


SECTIONS = ("THEME", "RESUME", "POINTS", "A_VERIFIER", "UTILE_POUR_MOI")


def decouper_sections(contenu):
    """Le modele ajoute parfois du gras (**THEME:**) : on nettoie puis on decoupe par etiquette."""
    t = re.sub(r"\*\*", "", contenu)
    morceaux = re.split(r"(?im)^\s*(THEME|RESUME|R[ÉE]SUM[ÉE]|POINTS|A_VERIFIER|[ÀA] V[ÉE]RIFIER|UTILE_POUR_MOI)\s*:\s*", t)
    d = {}
    for i in range(1, len(morceaux) - 1, 2):
        cle = morceaux[i].upper().replace("É", "E").replace("À", "A").replace(" ", "_")
        cle = {"RESUME": "RESUME", "A_VERIFIER": "A_VERIFIER"}.get(cle, cle)
        d[cle] = morceaux[i + 1].strip()
    return d


def ecrire_fiche(dossier, v, date, chaine, contenu, index_nom, source="sous-titres de la vidéo"):
    d = decouper_sections(contenu)
    theme = (d.get("THEME") or "divers").splitlines()[0].strip()
    resume = re.sub(r"\s+", " ", d.get("RESUME") or "").strip()
    nom = f"{index_nom.replace('chaine_', '')[:20]}_{date}_{slug(v['titre'], 40)}"
    with open(os.path.join(dossier, nom + ".md"), "w", encoding="utf-8") as f:
        f.write(f"## Récolte du {datetime.now():%d/%m/%Y}\n**Titre :** {v['titre']} — {chaine}, {date}\n"
                f"**Thème :** {theme}\n**Résumé :** {resume or '(non fourni)'}\n"
                f"**Faits :**\n{d.get('POINTS') or '- (le modèle n’a pas fourni de points)'}\n"
                f"**À vérifier :**\n{d.get('A_VERIFIER') or '- Aucune'}\n"
                f"**Utile pour moi :** {d.get('UTILE_POUR_MOI') or 'Rien de particulier'}\n"
                f"**Sources :**\n- {v['url']} ({source})\n"
                f"**Liens :**\n- [[{index_nom}]] · [[Bibliothèque]]\n")
    return nom, theme, resume


def index_de(chaine):
    """index de la chaine dans la Bibliotheque (cree s'il n'existe pas). Pas de lien de video dans l'en-tete :
    on reconnait les videos deja rangees a leur identifiant dans l'index."""
    index_nom = "chaine_" + slug(chaine)
    os.makedirs(BIBLIO, exist_ok=True)
    index = os.path.join(BIBLIO, index_nom + ".md")
    if not os.path.exists(index):
        with open(index, "w", encoding="utf-8") as f:
            f.write(f"# 📺 {chaine}\n\nChaîne YouTube : vidéos rangées une par une par Archi (la chaîne n'est pas suivie). Une fiche par vidéo.\n\nPièce : [[Bibliothèque]]\n\n## Vidéos\n\n")
    return index_nom, index


def main_videos(demande):
    """v2 (06/11) : recolte de videos A L'UNITE (liens) -> une fiche chacune dans la Bibliotheque.
    Sous-titres, sinon le son (Whisper, 15 min maxi). La chaine n'est PAS ajoutee a la veille."""
    liens = [str(u).strip() for u in demande.get("videos", []) if str(u).strip()]
    ecrire_etat(en_cours=True, debut=datetime.now().isoformat(timespec="seconds"), faites=0, veille=False,
                chaines=[f"{len(liens)} vidéo{'s' if len(liens) > 1 else ''} à l'unité"], pid=os.getpid(), liens=liens,
                mois=0, prevu=len(liens), derniere="", arretee=False, erreur=None)
    try:
        os.remove(STOP)
    except OSError:
        pass
    bilan, total, arretee, prochaine, deja = [], 0, False, None, 0
    tmp = tempfile.mkdtemp(prefix="archi_recolte_")
    try:
        for lien in liens:
            if arret_demande():
                arretee = True
                break
            try:
                v = V.infos(lien)
            except Exception as e:
                bilan.append(f"❌ {lien} : vidéo inaccessible ({str(e)[:80]})")
                continue
            index_nom, index = index_de(v["chaine"])
            if f"({v['id']})" in open(index, encoding="utf-8").read():
                deja += 1
                bilan.append(f"☑️ « {v['titre']} » ({v['chaine']}) : déjà dans la Bibliothèque")
                continue
            texte, source = V.sous_titres(v, tmp)
            source = f"sous-titres {source}" if texte else None
            if not texte:
                texte = V.par_le_son(v, tmp)
                source = "son de la vidéo, Whisper" if texte else None
            up = v.get("upload_date") or ""
            date = f"{up[:4]}-{up[4:6]}-{up[6:]}" if up else "date-inconnue"
            if not texte:
                bilan.append(f"❌ « {v['titre']} » : ni sous-titres ni son exploitable" + (" (plus de 15 min)" if v.get("duree", 0) > V.DUREE_MAX_WHISPER else ""))
                continue
            try:
                contenu = fiche(v, texte, v["chaine"])
            except Exception as e:
                bilan.append(f"❌ « {v['titre']} » : le modèle local n'a pas répondu ({str(e)[:60]})")
                continue
            nom_f, theme, resume = ecrire_fiche(BIBLIO, v, date, v["chaine"], contenu, index_nom, source)
            with open(index, "a", encoding="utf-8") as f:
                f.write(f"- {date} — [[{nom_f}]] — {theme} — {resume[:160]} ({v['id']})\n")
            total += 1
            ecrire_etat(faites=total, derniere=v["titre"])
            bilan.append(f"✅ « {v['titre']} » ({v['chaine']}) : fiche [[{nom_f}]] ({source})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        ecrire_etat(en_cours=False, fin=datetime.now().isoformat(timespec="seconds"), arretee=arretee)
        if arretee:
            try:
                os.remove(STOP)
            except OSError:
                pass
        else:
            try:
                prochaine = suivante()
            except Exception:
                prochaine = None
    if prochaine:
        bilan.append("▶️ Récolte suivante de la file lancée : " + ", ".join(
            c.get("nom", "?") if isinstance(c, dict) else str(c) for c in prochaine.get("chaines", [])) + (" (vidéos à l'unité)" if prochaine.get("videos") else ""))
    if arretee:
        titre, vocal = "⏹ RÉCOLTE ARRÊTÉE (à ta demande)", f"J'ai arrêté BOSS : {total} vidéo{'s' if total > 1 else ''} rangée{'s' if total > 1 else ''} avant l'arrêt."
    elif total:
        titre, vocal = "📺 VIDÉO(S) RANGÉE(S) DANS LA BIBLIOTHÈQUE", f"C'est rangé BOSS : {total} fiche{'s' if total > 1 else ''} de vidéo dans ta bibliothèque."
    elif deja:
        titre, vocal = "☑️ DÉJÀ DANS LA BIBLIOTHÈQUE", "Elle est déjà dans ta bibliothèque BOSS, je n'ai rien refait."
    else:
        titre, vocal = "❌ VIDÉO NON RANGÉE", "Je n'ai pas pu ranger la vidéo BOSS, regarde le message."
    renvoyer({"type": "REPONSE", "canal": "recolte", "texte": titre + "\n\n" + "\n".join(bilan), "vocal": vocal})


def main():
    veille = "--veille" in sys.argv
    if veille:
        try:
            e = json.load(open(ETAT, encoding="utf-8"))
            if e.get("en_cours") and datetime.now() - datetime.fromisoformat(e.get("debut", "2000-01-01")) < timedelta(hours=12):
                return   # une recolte tourne deja : la veille repassera demain
        except Exception:
            pass
        demande = {"chaines": lire_suivies(), "mois": 1, "max_par_chaine": 15}
    else:
        demande = json.load(open(sys.argv[1], encoding="utf-8"))
        if os.path.basename(sys.argv[1]).startswith("recolte_demande_"):
            try:
                os.remove(sys.argv[1])   # v2 : la demande est lue, on ne la laisse pas trainer
            except OSError:
                pass
        if demande.get("videos"):
            return main_videos(demande)
    chaines = [c for c in demande.get("chaines", []) if (c if isinstance(c, dict) else str(c).strip())]
    if not chaines:
        return
    mois = int(demande.get("mois", 6))
    limite = None if mois <= 0 else datetime.now() - timedelta(days=mois * 30)   # 0 = toute la chaine
    maxi = int(demande.get("max_par_chaine", 60))
    if not veille:
        try:
            os.remove(STOP)   # un vieux drapeau d'arret ne doit pas tuer une nouvelle recolte
        except OSError:
            pass
    ecrire_etat(en_cours=True, debut=datetime.now().isoformat(timespec="seconds"), faites=0, veille=veille,
                chaines=[c["nom"] if isinstance(c, dict) else c for c in chaines], pid=os.getpid(), liens=[],
                mois=mois, prevu=demande.get("prevu"), derniere="", arretee=False, erreur=None)
    bilan, total, arretee = [], 0, False
    tmp = tempfile.mkdtemp(prefix="archi_recolte_")
    try:
        for nom in chaines:
            if arret_demande():
                arretee = True
                break
            try:
                url, vrai_nom = trouver_chaine(nom)
            except Exception as e:
                bilan.append(f"❌ {nom.get('nom') if isinstance(nom, dict) else nom} : {e}")
                continue
            if not veille and demande.get("suivre", True):
                suivre(vrai_nom, url)
            index_nom = "chaine_" + slug(vrai_nom)
            dossier = BIBLIO   # a plat : l'outil memoire d'Archi ne lit pas les sous-dossiers
            os.makedirs(dossier, exist_ok=True)
            index = os.path.join(dossier, index_nom + ".md")
            deja = open(index, encoding="utf-8").read() if os.path.exists(index) else ""
            if not deja:
                with open(index, "w", encoding="utf-8") as f:
                    f.write(f"# 📺 {vrai_nom}\n\nChaîne YouTube récoltée par Archi ({url}). Une fiche par vidéo, de la plus récente à la plus ancienne.\n\nPièce : [[Bibliothèque]]\n\n## Vidéos\n\n")
            faites = sans_sous_titres = 0
            for v in lister(url, maxi):
                if arret_demande():
                    arretee = True
                    break
                if v["id"] in deja:
                    continue
                time.sleep(3)   # pas trop vite, sinon YouTube bloque (erreur 429)
                texte, _ = V.sous_titres(v, tmp)   # remplit aussi v["duree"] et v["upload_date"]
                up = v.get("upload_date") or ""
                if limite and up and datetime.strptime(up, "%Y%m%d") < limite:
                    break   # les suivantes sont plus anciennes
                date = f"{up[:4]}-{up[4:6]}-{up[6:]}" if up else "date-inconnue"
                if not texte:
                    sans_sous_titres += 1
                    with open(index, "a", encoding="utf-8") as f:
                        f.write(f"- {date} — {v['titre']} — pas de sous-titres ({v['id']}) {v['url']}\n")
                    continue
                try:
                    contenu = fiche(v, texte, vrai_nom)
                except Exception:
                    continue
                nom_f, theme, resume = ecrire_fiche(dossier, v, date, vrai_nom, contenu, index_nom)
                with open(index, "a", encoding="utf-8") as f:
                    f.write(f"- {date} — [[{nom_f}]] — {theme} — {resume[:160]} ({v['id']})\n")
                faites += 1
                total += 1
                ecrire_etat(faites=total, derniere=v["titre"])
            if not veille or faites or sans_sous_titres:
                bilan.append(f"{'⏹' if arretee else '✅'} {vrai_nom} : {faites} vidéos rangées" + (f", {sans_sous_titres} sans sous-titres (sautées)" if sans_sous_titres else "") + (" (arrêtée en cours de route)" if arretee else ""))
            if arretee:
                break
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        ecrire_etat(en_cours=False, fin=datetime.now().isoformat(timespec="seconds"), arretee=arretee)
        if arretee:
            try:
                os.remove(STOP)
            except OSError:
                pass
        if not arretee:
            try:
                prochaine = suivante()   # la file d'attente : la demande suivante demarre toute seule
            except Exception:
                prochaine = None
            if prochaine:
                bilan.append("▶️ Récolte suivante de la file lancée : " + ", ".join(
                    c.get("nom", "?") if isinstance(c, dict) else str(c) for c in prochaine.get("chaines", [])))
    if arretee:
        texte = "⏹ RÉCOLTE YOUTUBE ARRÊTÉE (à ta demande)\n\n" + "\n".join(bilan) + "\n\nCe qui a été rangé reste dans la pièce Bibliothèque."
        renvoyer({"type": "REPONSE", "canal": "recolte", "texte": texte,
                  "vocal": f"J'ai arrêté la récolte BOSS : {total} vidéo{'s' if total > 1 else ''} rangée{'s' if total > 1 else ''} avant l'arrêt."})
        return
    if veille:
        if total == 0:
            return   # rien de neuf : on ne derange pas l'utilisateur
        texte = "📺 VEILLE YOUTUBE : nouvelles vidéos rangées\n\n" + "\n".join(bilan) + "\n\nLes fiches sont dans la pièce Bibliothèque du château."
        renvoyer({"type": "REPONSE", "canal": "recolte", "texte": texte,
                  "vocal": f"Veille YouTube BOSS : {total} nouvelle{'s' if total > 1 else ''} vidéo{'s' if total > 1 else ''} résumée{'s' if total > 1 else ''} dans ta bibliothèque."})
        return
    texte = "📺 RÉCOLTE YOUTUBE TERMINÉE\n\n" + "\n".join(bilan) + "\n\nTout est dans la pièce Bibliothèque du château (une fiche par vidéo et un index par chaîne).\nCes chaînes sont maintenant suivies : chaque matin, la veille récolte leurs nouvelles vidéos."
    renvoyer({"type": "REPONSE", "canal": "recolte", "texte": texte,
              "vocal": f"La récolte YouTube est terminée BOSS : {total} vidéos résumées et rangées dans ta bibliothèque."})


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        ecrire_etat(en_cours=False, erreur=str(err)[:200])
        if "--veille" not in sys.argv:   # la veille plante en silence : elle repassera demain
            renvoyer({"type": "ERREUR", "canal": "recolte", "vocal": "La récolte YouTube a planté BOSS.", "detail": str(err)[:300]})
