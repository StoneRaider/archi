# recolte_lancer.py - v2 (06/11/2026) : porte d'entree de la recolte YouTube, appelee par le noeud n8n
# "Lancer la recolte" (workflow "Archi - Videos et pages", action=recolte).
#   python recolte_lancer.py --fichier demande.json     {"cible": "...", "question": "..."}
# cible :
#   - noms EXACTS de chaines (ou liens), separes par des virgules  -> verifie les noms, puis lance ou met en FILE
#   - "etat"                     -> recolte en cours, file d'attente, derniere recolte
#   - "arreter"                  -> arrete la recolte en cours (apres la video en cours) ET vide la file
#   - "suivies"                  -> chaines suivies par la veille du matin
#   - "retirer: nom1, nom2"      -> ne plus suivre ces chaines
# question : nombre de mois (6 par defaut, 120 max) ou "tout" (toute la chaine, depuis le debut).
# Repond UNE ligne JSON : {"ok": ..., "resultat": ..., "phrase_pour_utilisateur": ...}

import json
import os
import re
import sys
import ctypes
from datetime import datetime

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import recolte as R  # noqa: E402  (fait aussi os.chdir(ICI))

MAX_CHAINES = 5
MAX_TOUT = 1000          # videos maxi par chaine en mode "toute la chaine"
MAX_MOIS_VIDEOS = 300    # en mode "N mois", la date arrete avant
MIN_PAR_VIDEO = 1.0      # estimation : ~1 min par video (sous-titres + fiche par le modele local)


def _qui():
    """« , Camille » : le prenom du profil (ARCHI_UTILISATEUR, regle a l'installation) ; rien s'il manque."""
    p = " ".join((os.environ.get("ARCHI_UTILISATEUR") or "").split())[:30]
    return (", " + p) if p else ""


def sortir(ok, resultat, phrase):
    print(json.dumps({"ok": ok, "resultat": resultat, "phrase_pour_utilisateur": phrase}, ensure_ascii=False))
    sys.exit(0)


def sans_accent(t):
    return R.slug(t, 200).replace("_", " ")


def vivant(pid):
    """le processus de la recolte tourne-t-il encore ? (Windows)"""
    try:
        pid = int(pid)
    except Exception:
        return False
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259   # STILL_ACTIVE


def lire_etat():
    try:
        e = json.load(open(R.ETAT, encoding="utf-8"))
    except Exception:
        e = {}
    if e.get("en_cours"):
        pid = e.get("pid")
        if pid is None:
            # ancienne version (sans pid) : on se fie a l'heure (12 h max)
            try:
                if (datetime.now() - datetime.fromisoformat(e.get("debut"))).total_seconds() > 12 * 3600:
                    e["en_cours"] = False
            except Exception:
                e["en_cours"] = False
        elif not vivant(pid):
            e["en_cours"] = False
        if not e["en_cours"]:
            R.ecrire_etat(en_cours=False, erreur="recolte interrompue (processus disparu)")
    return e


def noms_de(liste):
    return [c.get("nom", "?") if isinstance(c, dict) else str(c) for c in liste]


def quand(iso):
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m à %H h %M")
    except Exception:
        return "?"


def duree_txt(minutes):
    minutes = int(round(minutes))
    if minutes < 60:
        return f"environ {max(minutes, 1)} min"
    h = minutes / 60
    if h < 24:
        return f"environ {round(h)} h"
    return f"environ {round(h / 24, 1)} jours".replace(".", ",")


# ---------------------------------------------------------------- commandes

def etat():
    e = lire_etat()
    f = R.lire_file()
    lignes, oral = [], []
    if e.get("en_cours"):
        prevu = f" sur {e['prevu']} prévues" if e.get("prevu") else ""
        lignes.append(f"EN COURS : {', '.join(e.get('chaines') or [])} — {e.get('faites', 0)} vidéos faites{prevu}, "
                      f"commencée le {quand(e.get('debut'))}"
                      + (f", dernière : « {e['derniere']} »" if e.get("derniere") else "") + ".")
        oral.append(f"Une récolte tourne : {', '.join(e.get('chaines') or [])}, {e.get('faites', 0)} vidéos faites{prevu}.")
    else:
        lignes.append("Aucune récolte en cours.")
        if e.get("fin"):
            lignes.append(f"Dernière récolte terminée le {quand(e['fin'])} "
                          f"({', '.join(e.get('chaines') or [])}, {e.get('faites', 0)} vidéos)"
                          + (" — arrêtée à ta demande" if e.get("arretee") else "") + ".")
        oral.append("Aucune récolte en cours.")
    if f:
        for n, d in enumerate(f, 1):
            lignes.append(f"FILE {n} : {', '.join(noms_de(d.get('chaines', [])))} ({'toute la chaîne' if d.get('mois') == 0 else str(d.get('mois')) + ' mois'}).")
        oral.append(f"{len(f)} récolte{'s' if len(f) > 1 else ''} en attente dans la file.")
    else:
        lignes.append("File d'attente vide.")
    sortir(True, "\n".join(lignes), " ".join(oral) + _qui() + ".")


def arreter():
    e = lire_etat()
    f = R.lire_file()
    if f:
        R.ecrire_file([])
    vidée = f" J'ai aussi vidé la file d'attente ({len(f)} demande{'s' if len(f) > 1 else ''} : {'; '.join(', '.join(noms_de(d.get('chaines', []))) for d in f)})." if f else ""
    if not e.get("en_cours"):
        sortir(True, "Aucune récolte en cours : rien à arrêter." + vidée,
               "Il n'y a aucune récolte en cours" + _qui() + "." + (" J'ai vidé la file d'attente." if f else ""))
    open(R.STOP, "w").write(datetime.now().isoformat(timespec="seconds"))
    sortir(True, f"ARRÊT DEMANDÉ : la récolte de {', '.join(e.get('chaines') or [])} s'arrête après la vidéo en cours "
                 f"(1 à 2 min). {e.get('faites', 0)} vidéos déjà rangées restent dans la Bibliothèque. Un message confirmera l'arrêt." + vidée,
           "Je demande l'arrêt de la récolte" + _qui() + " : elle s'arrête après la vidéo en cours, je te préviens quand c'est fait.")


def suivies():
    s = R.lire_suivies()
    if not s:
        sortir(True, "Aucune chaîne suivie.", "Je ne suis aucune chaîne pour l'instant" + _qui() + ".")
    sortir(True, "Chaînes suivies par la veille (chaque matin à 7 h 20) :\n" + "\n".join(f"- {c['nom']} (depuis le {c.get('depuis', '?')})" for c in s),
           f"Je suis {len(s)} chaînes{_qui()} : " + ", ".join(c["nom"] for c in s) + ".")


def retirer(texte):
    noms = [n.strip() for n in re.split(r"[,;\n]| et ", texte) if n.strip()]
    s = R.lire_suivies()
    retirees, introuvables = [], []
    for n in noms:
        cible = R.slug(n)
        trouve = [c for c in s if R.slug(c["nom"]) == cible] or [c for c in s if cible and cible in R.slug(c["nom"])]
        if len(trouve) == 1:
            s.remove(trouve[0])
            retirees.append(trouve[0]["nom"])
        else:
            introuvables.append(n + (" (plusieurs chaînes correspondent)" if len(trouve) > 1 else ""))
    if retirees:
        R.ecrire_suivies(s)
    res = (f"Ne sont plus suivies : {', '.join(retirees)}." if retirees else "") + \
          (f" Introuvables dans la liste : {', '.join(introuvables)}." if introuvables else "")
    sortir(bool(retirees), res.strip() + " Les fiches déjà rangées restent dans la Bibliothèque.",
           (f"C'est fait{_qui()}, je ne suis plus {', '.join(retirees)}." if retirees else "Je n'ai trouvé aucune de ces chaînes dans ma liste" + _qui() + ".")
           + (f" Pas trouvé : {', '.join(introuvables)}." if retirees and introuvables else ""))


RE_VIDEO = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s,;]*v=|shorts/|live/)|youtu\.be/)[\w\-]{6,}[^\s,;]*", re.I)


def en_attente_ou_en_cours():
    """noms de chaines et liens de videos deja en cours ou dans la file (anti-doublon)."""
    e = lire_etat()
    noms, liens = set(), set()
    if e.get("en_cours"):
        noms |= {R.slug(n) for n in (e.get("chaines") or [])}
        liens |= set(e.get("liens") or [])
    for d in R.lire_file():
        noms |= {R.slug(n) for n in noms_de(d.get("chaines", []))}
        liens |= set(d.get("videos") or [])
    return e, noms, liens


def ranger_videos(liens, reste):
    """v2 (06/11) : une ou plusieurs VIDEOS a l'unite -> une fiche chacune dans la Bibliotheque."""
    e, _, deja = en_attente_ou_en_cours()
    nouveaux = [l for l in dict.fromkeys(liens) if l not in deja]
    note = (f" (Les noms {', '.join(reste)} n'ont pas été traités : relance-les à part si l'utilisateur veut leurs chaînes.)" if reste else "")
    if not nouveaux:
        sortir(True, "Cette vidéo est déjà en cours de récolte ou dans la file : rien de plus à faire." + note,
               "Cette vidéo est déjà en route" + _qui() + ", je te préviens quand elle est rangée.")
    demande = {"videos": nouveaux, "mois": 0, "demande_le": datetime.now().isoformat(timespec="seconds")}
    n = len(nouveaux)
    quoi = f"{n} vidéo{'s' if n > 1 else ''} à l'unité"
    if e.get("en_cours"):
        f = R.lire_file()
        f.append(demande)
        R.ecrire_file(f)
        sortir(True, f"MISE EN FILE (position {len(f)}) : {quoi} ({', '.join(nouveaux)}). Fiche dans la Bibliothèque quand la récolte en cours "
                     f"({', '.join(e.get('chaines') or [])}) sera finie." + note,
               f"Une récolte tourne déjà{_qui()} : je mets ta vidéo dans la file, je la range dans la bibliothèque juste après.")
    R.demarrer(demande)
    sortir(True, f"RÉCOLTE LANCÉE : {quoi} ({', '.join(nouveaux)}) -> une fiche par vidéo dans la Bibliothèque "
                 f"(sous-titres, sinon le son). Seulement cette vidéo : la chaîne n'est PAS récoltée ni suivie. l'utilisateur sera prévenu à la fin." + note,
           f"C'est parti{_qui()} : je range {'ces vidéos' if n > 1 else 'cette vidéo'} dans ta bibliothèque, une à deux minutes par vidéo. Je te préviens à la fin.")


def recolter(cible, question):
    liens = RE_VIDEO.findall(cible or "")
    if liens:
        reste = [n.strip() for n in re.split(r"[,;\n]| et ", RE_VIDEO.sub("", cible)) if len(n.strip()) > 2]
        ranger_videos(liens, reste)
    q = sans_accent(question or "")
    tout = bool(re.search(r"\b(tout|toute|toutes|entiere|complete|debut|integral)", q))
    m = re.search(r"\d+", q)
    mois = 0 if tout else min(max(int(m.group()) if m else 6, 1), 120)
    if mois >= 120:
        mois, tout = 0, True
    noms = [n.strip() for n in re.split(r"[,;\n]| et ", cible) if n.strip()]
    if not noms:
        sortir(False, "ERREUR : donne le nom des chaînes dans cible, séparés par des virgules.", "Il me faut le nom exact de la chaîne" + _qui() + ".")
    trop = noms[MAX_CHAINES:]
    noms = noms[:MAX_CHAINES]

    # 1) VERIFIER LES NOMS avant de lancer (point 6) : rien ne part si un nom n'est pas exact
    trouvees, douteux = [], []
    for n in noms:
        try:
            url, vrai = R.trouver_chaine(n)
            trouvees.append({"nom": vrai, "url": url})
        except Exception as err:
            douteux.append(f"« {n} » : {err}")
    if douteux:
        ok_txt = f" Trouvées sans souci : {', '.join(c['nom'] for c in trouvees)}." if trouvees else ""
        sortir(False, "RIEN N'EST LANCÉ. Nom de chaîne pas sûr :\n- " + "\n- ".join(douteux) + ok_txt +
               "\nDemande à l'utilisateur le nom exact (ou un lien de la chaîne), puis relance.",
               "Je ne trouve pas exactement " + ", ".join(n.split(" : ")[0] for n in douteux) +
               "" + _qui() + ". Tu peux me redire le nom exact, ou m'envoyer un lien de la chaîne ?")

    # 2) TOUTE LA CHAINE : compter les vraies videos a faire (point 2 : ne plus mentir sur la duree)
    detail, prevu = [], None
    if tout:
        prevu = 0
        for c in trouvees:
            try:
                vids = R.lister(c["url"], MAX_TOUT)
            except Exception:
                vids = []
            index = os.path.join(R.BIBLIO, "chaine_" + R.slug(c["nom"]) + ".md")
            deja = open(index, encoding="utf-8").read() if os.path.exists(index) else ""
            neuves = sum(1 for v in vids if v["id"] not in deja)
            prevu += neuves
            limite = " (limite de 1000 atteinte)" if len(vids) >= MAX_TOUT else ""
            detail.append(f"{c['nom']} : {len(vids)} vidéos{limite}, dont {neuves} pas encore rangées")
    demande = {"chaines": trouvees, "mois": mois, "max_par_chaine": MAX_TOUT if tout else MAX_MOIS_VIDEOS, "prevu": prevu,
               "demande_le": datetime.now().isoformat(timespec="seconds")}
    periode = "toute la chaîne" if tout else f"les {mois} derniers mois"
    noms_ok = ", ".join(c["nom"] for c in trouvees)
    duree = (duree_txt(prevu * MIN_PAR_VIDEO) if prevu is not None else None)
    info = (" — " + " ; ".join(detail) + f". Durée estimée : {duree}." if tout else "") + \
           (f" (Seulement {MAX_CHAINES} chaînes par demande : {', '.join(trop)} ignorées.)" if trop else "")

    # 3) ANTI-DOUBLON (06/11 : Archi avait appele l'outil deux fois en 5 s -> meme chaine lancee ET mise en file)
    e, deja_noms, _ = en_attente_ou_en_cours()
    doublons = [c["nom"] for c in trouvees if R.slug(c["nom"]) in deja_noms]
    trouvees = [c for c in trouvees if R.slug(c["nom"]) not in deja_noms]
    if not trouvees:
        sortir(True, f"DÉJÀ EN ROUTE : {', '.join(doublons)} est déjà en cours de récolte ou dans la file. Rien de plus à faire.",
               f"{', '.join(doublons)}, c'est déjà en route{_qui()}, je te préviens à la fin.")
    if doublons:
        info += f" ({', '.join(doublons)} : déjà en route, pas relancée.)"
        demande["chaines"] = trouvees
        noms_ok = ", ".join(c["nom"] for c in trouvees)
    # 4) EN COURS -> FILE D'ATTENTE (point 1) au lieu de refuser
    if e.get("en_cours"):
        f = R.lire_file()
        f.append(demande)
        R.ecrire_file(f)
        sortir(True, f"MISE EN FILE (position {len(f)}) : {noms_ok}, {periode}{info}. Elle démarrera toute seule après la récolte en cours "
                     f"({', '.join(e.get('chaines') or [])}, {e.get('faites', 0)} vidéos faites).",
               f"Une récolte tourne déjà{_qui()} : je mets {noms_ok} dans la file, en position {len(f)}. Elle démarrera toute seule après."
               + (f" Il y a {prevu} vidéos à faire, {duree}." if tout else ""))
    R.demarrer(demande)
    sortir(True, f"RÉCOLTE LANCÉE en arrière-plan : {noms_ok}, {periode}{info}. l'utilisateur sera prévenu à la fin.",
           f"C'est parti{_qui()} : je récolte {noms_ok}, {periode}, en arrière-plan."
           + (f" Il y a {prevu} vidéos à faire, {duree}." if tout else " Ça peut prendre une à deux heures.")
           + " Je te préviens à la fin.")


def main():
    if "--fichier" not in sys.argv:
        sortir(False, "ERREUR : --fichier manquant", "Problème technique sur la récolte" + _qui() + ".")
    d = json.load(open(sys.argv[sys.argv.index("--fichier") + 1], encoding="utf-8-sig"))
    cible = str(d.get("cible") or "").strip()
    question = str(d.get("question") or "")
    c = sans_accent(cible)
    if re.fullmatch(r"(etat|statut|en cours|file|file d attente|ou en est la recolte|recap|recapitulatif)", c):
        etat()
    if re.fullmatch(r"(arret|arrete|arreter|stop|stopper|stoppe|annule|annuler)( (la |les )?(recolte|recoltes))?( (en cours|tout))?", c):
        arreter()
    if re.fullmatch(r"(suivies|chaines suivies|liste|veille)", c):
        suivies()
    mr = re.match(r"^(retirer|retire|ne plus suivre)\s*:?\s*(.*)$", c)
    if mr:
        brut = re.sub(r"^\s*(retirer|retire|ne plus suivre)\s*:?\s*", "", cible, flags=re.I)
        retirer(brut)
    recolter(cible, question)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as err:
        print(json.dumps({"ok": False, "resultat": "ERREUR recolte_lancer : " + str(err)[:300],
                          "phrase_pour_utilisateur": "La récolte a eu un souci technique" + _qui() + "."}, ensure_ascii=False))
