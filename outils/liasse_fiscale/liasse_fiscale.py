# liasse_fiscale.py - prepare la liasse fiscale annuelle d'une petite entreprise individuelle (BIC,
# regime reel simplifie, liasse 2031 + 2033 A a D) et les cases de la declaration de revenus (2042-C-PRO).
#   python liasse_fiscale.py --fichier demande.json
#   demande.json : {"action": "...", ...}
#     etat       : ce que l'outil sait deja (annees closes, bien amorti, pret, deficits)
#     preparer   : annee + montants de l'annee -> fiche case par case (rien n'est envoye nulle part)
#                  recettes, subventions, assurance, honoraires, autres_charges, impots_taxes,
#                  interets, capital_restant (pret au 31/12), tva_collectee, tva_deductible,
#                  capital_rembourse_annee_suivante (tableau d'amortissement du pret, pour la case 195)
#                  (un montant absent est ESTIME a partir de l'annee d'avant, et la fiche le dit)
#     comparer   : annee + cases du comptable {"136": -2304, "310": ...} -> ecarts avec la preparation
#     cloturer   : annee + confirmer=true -> enregistre l'annee preparee comme close (base de l'annee suivante)
#     synthese   : resume pluriannuel (chiffre d'affaires, resultats, deficits, bien amorti, pret)
# L'outil ne declare rien, ne paie rien, n'envoie rien : J (ou son comptable) declare lui-meme.
# Montants en euros. Les liasses arrondissent a l'euro : l'outil calcule au centime et affiche a l'euro.

import argparse
import json
import os
import sys
from datetime import datetime

ICI = os.path.dirname(os.path.abspath(__file__))
# historique de l'entreprise (annees closes, bien amorti, pret) : ARCHI_LIASSE_HISTO, sinon historique.json a cote du script.
# Voir historique.exemple.json (entreprise fictive). Le vrai fichier n'est jamais publie (.gitignore).
HISTO = os.environ.get("ARCHI_LIASSE_HISTO") or os.path.join(ICI, "historique.json")
PREPA = os.environ.get("ARCHI_LIASSE_PREPA") or os.path.join(os.path.dirname(HISTO), "preparations")
SORTIE = os.path.join(os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files"), "admin", "liasses")
CASES_DEFICITS = ["5RN", "5RO", "5RP", "5RQ", "5RR", "5RW"]  # du plus ancien (N-6) au plus recent (N-1)


class Erreur(Exception):
    pass


VENV = os.environ.get("ARCHI_PY", "")
try:  # le PDF "comme le comptable" a besoin de reportlab, present dans le Python d'Archi
    import reportlab  # noqa: F401
except ImportError:
    if os.path.isfile(VENV) and os.path.abspath(sys.executable).lower() != os.path.abspath(VENV).lower():
        import subprocess
        _r = subprocess.run([VENV, os.path.abspath(__file__)] + sys.argv[1:], capture_output=True, timeout=110, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        sys.stdout.buffer.write(_r.stdout)
        sys.exit(_r.returncode)


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def lire_json(chemin, defaut=None):
    try:
        with open(chemin, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return defaut


def ecrire_json(chemin, data):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def oui(v):
    return v is True or str(v).strip().lower() in {"true", "oui", "1", "yes"}


def nombre(v, nom):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).replace(" ", "").replace("\xa0", "").replace(" ", "").replace("€", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        raise Erreur(f"Je ne comprends pas le montant « {v} » ({nom}). Écris-le en chiffres, par exemple 346,90.")


def e(x):
    """arrondi a l'euro comme sur la liasse"""
    return int(round(x + (1e-9 if x >= 0 else -1e-9)))


def f(x):
    """affichage a l'euro avec espace des milliers"""
    n = e(x)
    s = f"{abs(n):,}".replace(",", " ")
    return ("-" if n < 0 else "") + s


def annee_ok(v):
    try:
        a = int(str(v).strip()[:4])
    except ValueError:
        raise Erreur("Donne l'année de l'exercice, par exemple 2026.")
    if not 2015 <= a <= 2100:
        raise Erreur(f"L'année {a} ne me paraît pas juste.")
    return a


# ---------------------------------------------------------------- calcul

def calculer(h, annee, d):
    """h = historique ; d = montants de l'annee. Retourne (resultats, estimes)"""
    closes = h["annees"]
    if str(annee) in closes:
        prec_annee = annee - 1
    else:
        prec_annee = max(int(a) for a in closes)
        if prec_annee != annee - 1:
            raise Erreur(f"La dernière année close que je connais est {prec_annee}. Il faut d'abord clôturer {prec_annee + 1}, "
                         f"puis on pourra préparer {annee}.")
    if str(prec_annee) not in closes:
        raise Erreur(f"Je n'ai pas les chiffres de clôture de {prec_annee}.")
    p = closes[str(prec_annee)]
    imm = h["immobilisation"]
    pret = h["pret"]
    estimes = []

    def val(cle, defaut, pourquoi):
        v = nombre(d.get(cle), cle)
        if v is None:
            if not defaut and cle not in ("recettes",):
                return 0.0
            estimes.append(f"{cle.replace('_', ' ')} : {f(defaut) if defaut else '0'} € ({pourquoi})")
            return float(defaut)
        return v

    ca = val("recettes", 0, "aucune recette donnée : mets le chiffre d'affaires hors TVA de l'année")
    subv = val("subventions", 0, "aucune prime ou subvention donnée")
    autres_prod = val("autres_produits", 0, "rien d'autre")
    assurance = val("assurance", p.get("assurance", 0), f"même montant qu'en {prec_annee}")
    honoraires = val("honoraires", h.get("honoraires_habituels", 0), "honoraires habituels du comptable")
    autres_ch = val("autres_charges", 0, "rien d'autre")
    impots = val("impots_taxes", 0, "pas de CFE ni de taxe connue")
    # pret : capital rembourse estime avec la progression habituelle d'un pret a mensualites fixes
    cap_rest_p = p["emprunt"]
    remb_p = p.get("capital_rembourse") or 0
    remb_estime = min(cap_rest_p, remb_p * pret["progression"]) if remb_p else 0
    ech = (pret.get("echeancier") or {}).get(str(annee))  # tableau d'amortissement du preteur, s'il est connu
    cap_rest = nombre(d.get("capital_restant"), "capital_restant")
    if cap_rest is None and ech:
        cap_rest = max(0.0, cap_rest_p - ech["capital"])  # solde des comptes moins le capital du tableau
    elif cap_rest is None:
        cap_rest = max(0.0, cap_rest_p - remb_estime)
        estimes.append(f"capital restant du prêt au 31/12 : {f(cap_rest)} € (estimé, à remplacer par le relevé annuel {pret['preteur']})")
    remb = cap_rest_p - cap_rest
    interets = nombre(d.get("interets"), "interets")
    if interets is None and ech:
        interets = ech["interets"]
    if interets is None:
        interets = max(0.0, pret["annuite"] - remb) if cap_rest_p > 0 else 0.0
        estimes.append(f"intérêts du prêt : {f(interets)} € (estimé : annuité {f(pret['annuite'])} € moins capital remboursé ; "
                       f"le vrai chiffre est sur le relevé annuel {pret['preteur']})")
    tva_c = val("tva_collectee", 0, "aucune TVA collectée indiquée")
    tva_d = val("tva_deductible", round(honoraires * 0.2, 2) if honoraires else 0,
                "20 % des honoraires (estimation par defaut)" if honoraires else "aucune")

    # amortissement lineaire du bien (immobilisation)
    reste = imm["brut"] - p["amort_cumul"]
    dot = round(min(imm["dotation_annuelle"], max(0.0, reste)), 2)
    amort = round(p["amort_cumul"] + dot, 2)

    ext = assurance + honoraires + autres_ch
    prod_expl = ca + subv + autres_prod
    ch_expl = ext + impots + dot
    r_expl = prod_expl - ch_expl
    resultat = r_expl - interets

    # sans compte bancaire pro, tout passe par le compte perso de l'exploitant -> le capital individuel absorbe les flux
    apports = (ext + impots + interets + remb + tva_d) - (ca + subv + autres_prod + tva_c)
    capital = p["capital"] + p["resultat"] + apports
    credit_tva = p.get("credit_tva", 0) + tva_d - tva_c
    creance_tva = max(0.0, credit_tva)
    dette_tva = max(0.0, -credit_tva)

    actif_immo_net = imm["brut"] - amort
    total_actif = actif_immo_net + creance_tva
    cap_propres = capital + resultat
    total_passif = cap_propres + cap_rest + dette_tva
    remb_suivant = nombre(d.get("capital_rembourse_annee_suivante"), "capital_rembourse_annee_suivante")
    if remb_suivant is None:
        ech2 = (pret.get("echeancier") or {}).get(str(annee + 1))
        remb_suivant = min(cap_rest, ech2["capital"] if ech2 else remb * pret["progression"])
    plus_un_an = cap_rest - remb_suivant

    # deficits BIC non professionnels : imputables 6 ans, sur des BIC non professionnels seulement
    defs = {int(k): v for k, v in h.get("deficits", {}).items() if v}
    vivants = {a: v for a, v in defs.items() if annee - 6 <= a < annee}
    imputes = 0.0
    if resultat > 0:
        reste_b = resultat
        for a in sorted(vivants):
            u = min(reste_b, vivants[a])
            imputes += u
            vivants[a] -= u
            reste_b -= u
    deficit_annee = -resultat if resultat < 0 else 0.0

    R = dict(
        annee=annee, annee_precedente=prec_annee,
        ca=ca, subventions=subv, autres_produits=autres_prod, assurance=assurance, honoraires=honoraires,
        autres_charges=autres_ch, impots_taxes=impots, charges_externes=ext, dotation=dot, amort_cumul=amort,
        produits_exploitation=prod_expl, charges_exploitation=ch_expl, resultat_exploitation=r_expl,
        interets=interets, resultat=resultat, capital=capital, capitaux_propres=cap_propres,
        emprunt=cap_rest, capital_rembourse=remb, dettes_plus_un_an=plus_un_an, credit_tva=creance_tva, dette_tva=dette_tva,
        tva_collectee=tva_c, tva_deductible=tva_d, immo_net=actif_immo_net, total_actif=total_actif,
        total_passif=total_passif, apports_nets=apports, deficit_annee=deficit_annee, deficits_imputes=imputes,
        deficits_anterieurs={str(a): round(v, 2) for a, v in sorted(vivants.items())},
        deficits_expires={str(a): v for a, v in defs.items() if a < annee - 6},
        assurance_brute=assurance,
    )
    R["assurance"] = assurance
    return R, estimes


# ---------------------------------------------------------------- fiche

def fiche(h, R, estimes, questions):
    a = R["annee"]
    pa = R["annee_precedente"]
    p = h["annees"][str(pa)]
    imm = h["immobilisation"]
    L = []
    w = L.append
    w(f"# Préparation de la liasse fiscale {a} - {h['entreprise']['nom']} (SIREN {h['entreprise']['siren']})")
    w(f"_Préparée par Archi le {datetime.now().strftime('%d/%m/%Y à %H:%M')}. Brouillon à vérifier : "
      f"Archi n'est pas comptable, rien n'est déclaré ni envoyé. Exercice du 01/01/{a} au 31/12/{a}, 12 mois._")
    w("")
    w("## En bref")
    res = "un DÉFICIT de " + f(-R["resultat"]) + " €" if R["resultat"] < 0 else "un BÉNÉFICE de " + f(R["resultat"]) + " €"
    w(f"- Résultat {a} : **{res}** (en {pa} : {f(p['resultat'])} €).")
    w(f"- Recettes : {f(R['ca'])} € (ventes) + {f(R['subventions'])} € (primes). Charges : assurance {f(R['assurance'])} €, "
      f"honoraires {f(R['honoraires'])} €, amortissement {f(R['dotation'])} €, intérêts du prêt {f(R['interets'])} €.")
    w(f"- Total du bilan : {f(R['total_actif'])} €. Contrôle actif = passif : "
      + ("OK" if abs(R["total_actif"] - R["total_passif"]) < 1 else f"ÉCART de {R['total_actif'] - R['total_passif']:.2f} €"))
    if estimes:
        w("")
        w("**Montants ESTIMÉS (à remplacer par les vrais quand tu les as) :**")
        for x in estimes:
            w(f"- {x}")
    w("")
    w("## 2033-A - Bilan simplifié")
    w("| Case | Libellé | Montant |")
    w("|---|---|---:|")
    for c, lib, v in [
        ("028", f"Immobilisations corporelles - brut ({imm.get('libelle', 'bien')})", imm["brut"]),
        ("030", "Immobilisations corporelles - amortissements", R["amort_cumul"]),
        ("", "Immobilisations corporelles - net", R["immo_net"]),
        ("044 / 048", "TOTAL I - brut / amortissements", f"{f(imm['brut'])} / {f(R['amort_cumul'])}"),
        ("072", "Créances autres (crédit de TVA à reporter)", R["credit_tva"]),
        ("096", "TOTAL II", R["credit_tva"]),
        ("110 / 112", "TOTAL GÉNÉRAL brut / amortissements", f"{f(imm['brut'] + R['credit_tva'])} / {f(R['amort_cumul'])}"),
        ("", "TOTAL GÉNÉRAL net (actif)", R["total_actif"]),
        ("120", "Capital individuel", R["capital"]),
        ("136", "Résultat de l'exercice", R["resultat"]),
        ("142", "TOTAL I (capitaux propres)", R["capitaux_propres"]),
        ("156", "Emprunts et dettes assimilées (prêt " + h["pret"]["preteur"] + ")", R["emprunt"]),
        ("172", "Dettes fiscales et sociales", R["dette_tva"]),
        ("176", "TOTAL III", R["emprunt"] + R["dette_tva"]),
        ("180", "TOTAL GÉNÉRAL (passif)", R["total_passif"]),
        ("195", "Dont dettes à plus d'un an", R["dettes_plus_un_an"]),
    ]:
        w(f"| {c} | {lib} | {v if isinstance(v, str) else f(v)} |")
    w("")
    w("## 2033-B - Compte de résultat simplifié")
    w("| Case | Libellé | Montant |")
    w("|---|---|---:|")
    rows = [
        ("218", f"Production vendue services ({h['entreprise'].get('libelle_ventes', 'ventes')})", R["ca"]),
        ("226", "Subventions d'exploitation reçues", R["subventions"]),
        ("230", "Autres produits", R["autres_produits"]),
        ("232", "Total des produits d'exploitation (I)", R["produits_exploitation"]),
        ("242", "Autres charges externes (assurance + honoraires + autres)", R["charges_externes"]),
        ("244", "Impôts, taxes", R["impots_taxes"]),
        ("254", "Dotations aux amortissements", R["dotation"]),
        ("264", "Total des charges d'exploitation (II)", R["charges_exploitation"]),
        ("270", "Résultat d'exploitation (I - II)", R["resultat_exploitation"]),
        ("294", "Charges financières (intérêts du prêt)", R["interets"]),
        ("310", "Bénéfice ou perte", R["resultat"]),
    ]
    for c, lib, v in rows:
        w(f"| {c} | {lib} | {f(v)} |")
    if R["resultat"] < 0:
        w(f"| 314 | Déficit comptable reporté (col. 2) | {f(-R['resultat'])} |")
        w(f"| 354 | Résultat fiscal avant déficits antérieurs - déficit | {f(-R['resultat'])} |")
        w(f"| 372 | Résultat fiscal après déficits - déficit | {f(-R['resultat'])} |")
    else:
        w(f"| 312 | Bénéfice comptable reporté (col. 1) | {f(R['resultat'])} |")
        w(f"| 352 | Résultat fiscal avant déficits antérieurs - bénéfice | {f(R['resultat'])} |")
        w(f"| 370 | Résultat fiscal après déficits - bénéfice | {f(R['resultat'])} |")
    w("")
    w("_Aucune réintégration prévue (cases 316 à 330 à 0) : rien de non déductible connu._")
    w("")
    w("## 2033-C - Immobilisations et amortissements")
    w("| Case | Libellé | Montant |")
    w("|---|---|---:|")
    w(f"| 440 | Installations techniques - valeur brute début | {f(imm['brut'])} |")
    w(f"| 446 | Installations techniques - valeur brute fin | {f(imm['brut'])} |")
    w(f"| 530 | Amortissements début d'exercice | {f(p['amort_cumul'])} |")
    w(f"| 532 | Dotations de l'exercice | {f(R['dotation'])} |")
    w(f"| 536 | Amortissements fin d'exercice | {f(R['amort_cumul'])} |")
    w(f"| 490 / 570 / 572 / 576 | Totaux (mêmes montants) | {f(imm['brut'])} / {f(p['amort_cumul'])} / {f(R['dotation'])} / {f(R['amort_cumul'])} |")
    w("")
    w("## 2033-D - Déficits et divers")
    total_prec = sum(v for k, v in h.get("deficits", {}).items() if int(k) < R["annee"] and int(k) >= R["annee"] - 6)
    w("| Case | Libellé | Montant |")
    w("|---|---|---:|")
    w(f"| 982 | Déficits restant à reporter au titre de l'exercice précédent | {f(total_prec)} |")
    w(f"| 983 | Déficits imputés | {f(R['deficits_imputes'])} |")
    w(f"| 984 | Déficits reportables | {f(total_prec - R['deficits_imputes'])} |")
    w(f"| 860 | Déficit de l'exercice | {f(R['deficit_annee'])} |")
    w(f"| 870 | Total des déficits restant à reporter | {f(total_prec - R['deficits_imputes'] + R['deficit_annee'])} |")
    w(f"| 374 | TVA collectée | {f(R['tva_collectee'])} |")
    w(f"| 378 | TVA déductible (hors immobilisations) | {f(R['tva_deductible'])} |")
    w("")
    w("## 2031 - Déclaration de résultats BIC")
    if R["resultat"] < 0:
        w(f"- Cadre C, ligne 1 : résultat fiscal, déficit (colonne 2) : **{f(-R['resultat'])}**")
        w(f"- Ligne 4 : déficit déductible : {f(-R['resultat'])}")
        w(f"- Ligne 7 : dont BIC non professionnels, B - déficit : {f(-R['resultat'])}")
        w(f"- Annexe, cadre I : « Autres BIC non professionnels », déficit : {f(-R['resultat'])}")
    else:
        w(f"- Cadre C, ligne 1 : résultat fiscal, bénéfice (colonne 1) : **{f(R['resultat'])}**")
        w(f"- Ligne 7 : dont BIC non professionnels, A - bénéfice : {f(R['resultat'])}")
        w(f"- Annexe, cadre I : « Autres BIC non professionnels », bénéfice : {f(R['resultat'])}")
    w("- Activité : " + str(h["entreprise"].get("activite") or "à préciser") + ". Régime simplifié d'imposition. Comptabilité informatisée : à cocher selon le logiciel.")
    w("")
    w(f"## Déclaration de revenus {R['annee'] + 1} (revenus {R['annee']}) - formulaire 2042-C-PRO")
    w("Cadre « Revenus industriels et commerciaux non professionnels », régime du bénéfice réel, déclarant 1 :")
    if R["resultat"] < 0:
        w(f"- **Case 5NF (déficit) : {f(-R['resultat'])}**")
    else:
        w(f"- **Case 5NC (revenus imposables) : {f(R['resultat'])}**")
    w("- Déficits des années précédentes pas encore utilisés (ils ne servent que contre des bénéfices BIC non professionnels, pendant 6 ans) :")
    for i, an in enumerate(range(R["annee"] - 6, R["annee"])):
        v = h.get("deficits", {}).get(str(an))
        txt = f(v) if v else ("0" if str(an) in h.get("deficits", {}) else "inconnu (à demander au comptable)" if an >= h.get("debut_activite", 0) else "-")
        w(f"  - case {CASES_DEFICITS[i]} (déficit {an}) : {txt}")
    w("  _Les années glissent chaque année sur le formulaire : vérifie le libellé de la case avant de recopier._")
    if R["deficits_imputes"]:
        w(f"- Avec le bénéfice, {f(R['deficits_imputes'])} € de vieux déficits seront utilisés (le fisc le calcule lui-même).")
    if R["deficits_expires"]:
        w(f"- Déficits trop vieux, perdus : {', '.join(k + ' : ' + f(v) + ' €' for k, v in R['deficits_expires'].items())}")
    w("")
    w("## TVA")
    w(f"- TVA collectée {f(R['tva_collectee'])} €, TVA déductible {f(R['tva_deductible'])} €. Crédit de TVA au 31/12 : {f(R['credit_tva'])} €"
      + (f", dette de TVA : {f(R['dette_tva'])} €" if R["dette_tva"] else "") + ".")
    w("- La déclaration annuelle de TVA (CA12) se fait à part : à vérifier avec le comptable.")
    w("")
    w("## Comment les chiffres sont faits (pour comprendre)")
    w(f"- Bien acheté {f(imm['brut'])} €, amortis sur {imm['duree_ans']} ans : {imm['dotation_annuelle']:.2f} € d'usure par an, "
      f"jusqu'à {f(imm['brut'])} € (fin vers {imm['fin_amortissement']}).")
    w(f"- Prêt {h['pret']['preteur']} : capital remboursé cette année {f(R['capital_rembourse'])} €, reste {f(R['emprunt'])} €.")
    w(f"- Sans compte bancaire pro, tout passe par ton compte perso. Ce que tu as payé moins ce que tu as reçu "
      f"({f(R['apports_nets'])} €) s'ajoute à ton « capital individuel », avec le résultat de {pa}.")
    w("")
    w("## Pièces à rassembler")
    for x in h.get("pieces", []):
        w(f"- {x}")
    if questions:
        w("")
        w("## Questions pour le comptable")
        for q in questions:
            w(f"- {q}")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- actions

def charger():
    h = lire_json(HISTO)
    if not isinstance(h, dict) or not h.get("annees"):
        raise Erreur("Je ne trouve pas l'historique des liasses (historique.json).")
    return h


def act_etat(d):
    h = charger()
    an = sorted(h["annees"])
    der = h["annees"][an[-1]]
    imm = h["immobilisation"]
    defs = ", ".join(f"{k} : {f(v)} €" for k, v in sorted(h.get("deficits", {}).items()) if v)
    prep = sorted(x[:-5] for x in os.listdir(PREPA)) if os.path.isdir(PREPA) else []
    phrase = (f"Je connais les années closes {', '.join(an)}. Dernière clôture {an[-1]} : résultat {f(der['resultat'])} €, "
              f"bien amorti {f(der['amort_cumul'])} sur {f(imm['brut'])} €, prêt restant {f(der['emprunt'])} €. "
              f"Déficits gardés : {defs}." + (f" Préparation en cours : {', '.join(prep)}." if prep else ""))
    return repondre(True, phrase, annees=an, preparations=prep)


def act_preparer(d):
    h = charger()
    a = annee_ok(d.get("annee") or (max(int(x) for x in h["annees"]) + 1))
    R, est = calculer(h, a, d)
    questions = list(h.get("questions_comptable", []))
    if R["ca"] == 0:
        questions.insert(0, f"Aucune recette en {a} : les ventes de l'année ont-elles bien été facturées et payées ?")
    if abs(R["total_actif"] - R["total_passif"]) >= 1:
        raise Erreur("Le bilan ne tombe pas juste : je ne produis pas la fiche (erreur à corriger dans l'outil).")
    md = fiche(h, R, est, questions)
    os.makedirs(SORTIE, exist_ok=True)
    chemin = os.path.join(SORTIE, f"preparation_liasse_{a}.md")
    with open(chemin, "w", encoding="utf-8") as fo:
        fo.write(md)
    ecrire_json(os.path.join(PREPA, f"{a}.json"), {"date": datetime.now().isoformat(timespec="minutes"),
                                                   "entrees": d, "resultats": R, "estimes": est})
    pdf = None
    try:
        sys.path.insert(0, ICI)
        from liasse_pdf import faire_pdf
        pdf = faire_pdf(h, R, est, questions, os.path.join(SORTIE, f"projet_liasse_fiscale_{a}.pdf"))
    except Exception as x:
        pdf = None
        est = est + [f"(le PDF n'a pas pu être fait : {type(x).__name__})"]
    sens = f"un déficit de {f(-R['resultat'])} euros" if R["resultat"] < 0 else f"un bénéfice de {f(R['resultat'])} euros"
    phrase = (f"Liasse {a} préparée : {sens}. À reporter sur ta déclaration de revenus : case "
              f"{'5NF' if R['resultat'] < 0 else '5NC'}, {f(abs(R['resultat']))} euros."
              + (f" Attention, {len(est)} montant(s) sont estimés, les vrais chiffres sont à me donner." if est else "")
              + (" Le projet de liasse en PDF, présenté comme celui du comptable, est dans ton dossier admin, liasses."
                 if pdf else " La fiche complète, case par case, est dans ton dossier admin, liasses."))
    return repondre(True, phrase, fiche_md=chemin, projet_pdf=pdf, resultat=round(R["resultat"], 2), estimes=est,
                    cases={"136": e(R["resultat"]), "180": e(R["total_passif"]), "218": e(R["ca"]),
                           "254": e(R["dotation"]), "294": e(R["interets"]), "120": e(R["capital"]),
                           "156": e(R["emprunt"])})


CASES_LIB = {"028": ("brut", None), "030": ("amort_cumul", "Amortissements"), "072": ("credit_tva", "Crédit de TVA"),
             "120": ("capital", "Capital individuel"), "136": ("resultat", "Résultat"), "142": ("capitaux_propres", "Capitaux propres"),
             "156": ("emprunt", "Emprunt"), "180": ("total_passif", "Total du bilan"), "195": ("dettes_plus_un_an", "Dettes à plus d'un an"),
             "218": ("ca", "Ventes"), "226": ("subventions", "Subventions"), "232": ("produits_exploitation", "Produits d'exploitation"),
             "242": ("charges_externes", "Charges externes"), "254": ("dotation", "Amortissement de l'année"),
             "264": ("charges_exploitation", "Charges d'exploitation"), "270": ("resultat_exploitation", "Résultat d'exploitation"),
             "294": ("interets", "Intérêts"), "310": ("resultat", "Bénéfice ou perte"), "860": ("deficit_annee", "Déficit de l'année")}


def act_comparer(d):
    a = annee_ok(d.get("annee"))
    prep = lire_json(os.path.join(PREPA, f"{a}.json"))
    if not prep:
        raise Erreur(f"Je n'ai pas encore préparé {a} : demande d'abord « preparer ».")
    cases = d.get("cases") or {}
    if isinstance(cases, str):
        try:
            cases = json.loads(cases)
        except ValueError:
            raise Erreur("Donne les cases du comptable sous la forme {\"136\": 1200, \"180\": 5000}.")
    R = prep["resultats"]
    ecarts, ok = [], []
    for c, v in cases.items():
        c = str(c).zfill(3)
        if c not in CASES_LIB or CASES_LIB[c][1] is None:
            continue
        cle, lib = CASES_LIB[c]
        mien = e(R[cle])
        sien = e(nombre(v, c))
        (ok if abs(mien - sien) <= 1 else ecarts).append(f"case {c} ({lib}) : Archi {f(mien)}, comptable {f(sien)}")
    if not ok and not ecarts:
        raise Erreur("Je n'ai reconnu aucune case. Exemple : {\"136\": 1200, \"180\": 5000, \"294\": 300}.")
    phrase = (f"Comparaison {a} : {len(ok)} case(s) identiques à l'euro près"
              + (f", {len(ecarts)} écart(s) : " + " ; ".join(ecarts) + "." if ecarts else ", aucun écart."))
    return repondre(True, phrase, identiques=ok, ecarts=ecarts)


def act_cloturer(d):
    h = charger()
    a = annee_ok(d.get("annee"))
    prep = lire_json(os.path.join(PREPA, f"{a}.json"))
    if not prep:
        raise Erreur(f"Je n'ai pas de préparation pour {a}.")
    if str(a) in h["annees"]:
        raise Erreur(f"{a} est déjà close. Je ne l'écrase pas.")
    if not oui(d.get("confirmer")):
        R = prep["resultats"]
        return repondre(True, f"Essai à blanc : je clôturerais {a} avec un résultat de {f(R['resultat'])} euros"
                        + (f" et {len(prep['estimes'])} montant(s) encore estimé(s)" if prep["estimes"] else "")
                        + ". Redis-moi avec confirmer=oui quand la liasse est vraiment déposée.")
    R = prep["resultats"]
    h["annees"][str(a)] = {k: round(R[k], 2) for k in ("ca", "subventions", "assurance", "honoraires", "charges_externes", "dotation",
                                                       "interets", "resultat", "capital", "emprunt", "capital_rembourse",
                                                       "amort_cumul", "credit_tva", "total_passif", "dettes_plus_un_an")}
    h["annees"][str(a)]["source"] = "preparation Archi" + (" (avec estimations)" if prep["estimes"] else "")
    h["annees"][str(a)]["total_actif"] = round(R["total_actif"], 2)
    if R["resultat"] < 0:
        h.setdefault("deficits", {})[str(a)] = round(-R["resultat"], 2)
    else:
        h.setdefault("deficits", {})[str(a)] = 0
        for an, v in R["deficits_anterieurs"].items():
            h["deficits"][an] = v
    ecrire_json(HISTO, h)
    return repondre(True, f"{a} est close et servira de base pour {a + 1}.")


def act_synthese(d):
    h = charger()
    L = []
    for an in sorted(h["annees"]):
        x = h["annees"][an]
        L.append(f"{an} : ventes {f(x['ca'])}, primes {f(x.get('subventions', 0))}, résultat {f(x['resultat'])}")
    der = h["annees"][max(h["annees"])]
    imm = h["immobilisation"]
    defs = sum(v for k, v in h.get("deficits", {}).items() if v and int(k) >= int(max(h["annees"])) + 1 - 6)
    phrase = ("Ton activité, année par année : " + " ; ".join(L) + f". Le bien est amorti à "
              f"{round(100 * der['amort_cumul'] / imm['brut'])} %, il reste {f(der['emprunt'])} euros de prêt, et "
              f"{f(defs)} euros de déficits à garder pour plus tard (ils ne se déduisent que d'un bénéfice de la même activité).")
    return repondre(True, phrase)


ACTIONS = {"etat": act_etat, "preparer": act_preparer, "comparer": act_comparer, "cloturer": act_cloturer, "synthese": act_synthese}
ALIAS = {"état": "etat", "liste": "etat", "preparation": "preparer", "préparer": "preparer", "calculer": "preparer",
         "comparaison": "comparer", "clore": "cloturer", "clôturer": "cloturer", "resume": "synthese", "synthèse": "synthese"}


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier", required=True)
    args = pa.parse_args()
    d = lire_json(args.fichier)
    if not isinstance(d, dict):
        return repondre(False, "La demande est illisible.")
    act = str(d.get("action") or "").strip().lower()
    act = ALIAS.get(act, act)
    if not act:
        act = "preparer" if d.get("annee") else "etat"
    if act not in ACTIONS:
        return repondre(False, f"Je ne connais pas « {act} ». Choix : etat, preparer, comparer, cloturer, synthese.")
    try:
        return ACTIONS[act](d)
    except Erreur as x:
        return repondre(False, str(x))


if __name__ == "__main__":
    main()
