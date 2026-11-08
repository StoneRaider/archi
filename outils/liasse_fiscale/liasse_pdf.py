# liasse_pdf.py - met la preparation de liasse en forme "comme le comptable" : un PDF avec les tableaux
# 2033-A (bilan), 2033-B (compte de resultat), 2033-C (immobilisations), 2033-D (deficits), 2031 (resultat BIC)
# et la case de la declaration de revenus. Colonnes N et N-1, numeros de cases officiels.
# C'est un PROJET a recopier dans l'espace professionnel impots.gouv.fr (ou a remettre au comptable) :
# il n'a pas de valeur officielle en lui-meme.

from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

GRIS = colors.HexColor("#e9ecef")
ENCRE = colors.HexColor("#1d2621")
ROUGE = colors.HexColor("#b42318")

S_TITRE = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=ENCRE)
S_SOUS = ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
S_CEL = ParagraphStyle("c", fontName="Helvetica", fontSize=8.5, leading=10.5)
S_CELB = ParagraphStyle("cb", parent=S_CEL, fontName="Helvetica-Bold")
S_NOTE = ParagraphStyle("n", fontName="Helvetica", fontSize=8.5, leading=11.5)
S_PROJET = ParagraphStyle("p", fontName="Helvetica-Bold", fontSize=9, textColor=ROUGE)


def eu(x):
    if x is None or x == "":
        return ""
    n = int(round(float(x) + (1e-9 if float(x) >= 0 else -1e-9)))
    s = f"{abs(n):,}".replace(",", " ")
    return ("-" if n < 0 else "") + s


def entete(h, a, cerfa, titre):
    ent = h["entreprise"]
    return [
        Paragraph(f"DGFiP N° {cerfa}", S_SOUS),
        Paragraph(titre, S_TITRE),
        Paragraph(f"{ent['nom']} - SIREN {ent['siren']} - Exercice du 01/01/{a} au 31/12/{a} (12 mois) - "
                  f"durée de l'exercice précédent : 12 mois", S_SOUS),
        Paragraph("PROJET préparé par Archi - à vérifier avant tout dépôt", S_PROJET),
        Spacer(1, 4 * mm),
    ]


def tableau(lignes, largeurs, gras=()):
    data = []
    for i, l in enumerate(lignes):
        st = S_CELB if (i == 0 or i in gras) else S_CEL
        data.append([Paragraph(str(c), st) if j == 0 else str(c) for j, c in enumerate(l)])
    t = Table(data, colWidths=largeurs, repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (1, 1), (-1, -1), "Helvetica", 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), GRIS),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa5a0")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    for i in gras:
        style.append(("FONT", (1, i), (-1, i), "Helvetica-Bold", 8.5))
        style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f6f7f6")))
    t.setStyle(TableStyle(style))
    return t


def faire_pdf(h, R, estimes, questions, chemin):
    a = R["annee"]
    pa = R["annee_precedente"]
    p = dict(h["annees"].get(str(pa), {}))
    imm = h["immobilisation"]
    brut = imm["brut"]
    # valeurs N-1 derivees
    p.setdefault("charges_externes", p.get("assurance", 0) + p.get("honoraires", 0))
    p_prod = p.get("ca", 0) + p.get("subventions", 0)
    p_chexp = p.get("charges_externes", 0) + p.get("dotation", 0)
    p_cp = p.get("capital", 0) + p.get("resultat", 0)
    p_total = p.get("total_passif", 0)

    L = 96 * mm
    W = [L, 18 * mm, 33 * mm, 33 * mm]
    histo = []

    # ---------- 2033-A ----------
    histo += entete(h, a, "2033-A-SD", "1. BILAN SIMPLIFIÉ")
    histo.append(Paragraph("ACTIF", S_CELB))
    actif = [
        ["Rubrique", "Case", f"31/12/{a}", f"31/12/{pa}"],
        ["Immobilisations corporelles - brut", "028", eu(brut), eu(brut)],
        ["Immobilisations corporelles - amortissements", "030", eu(R["amort_cumul"]), eu(p.get("amort_cumul"))],
        ["Immobilisations corporelles - net", "", eu(R["immo_net"]), eu(brut - p.get("amort_cumul", 0))],
        ["TOTAL I (actif immobilisé) - net", "044/048", eu(R["immo_net"]), eu(brut - p.get("amort_cumul", 0))],
        ["Créances autres (crédit de TVA à reporter)", "072", eu(R["credit_tva"]), eu(p.get("credit_tva"))],
        ["Disponibilités", "084", "0", "0"],
        ["TOTAL II (actif circulant)", "096", eu(R["credit_tva"]), eu(p.get("credit_tva"))],
        ["TOTAL GÉNÉRAL (I + II) - net", "110/112", eu(R["total_actif"]), eu(p_total)],
    ]
    histo.append(tableau(actif, W, gras=(4, 7, 8)))
    histo.append(Spacer(1, 5 * mm))
    histo.append(Paragraph("PASSIF", S_CELB))
    passif = [
        ["Rubrique", "Case", f"31/12/{a}", f"31/12/{pa}"],
        ["Capital individuel", "120", eu(R["capital"]), eu(p.get("capital"))],
        ["Résultat de l'exercice", "136", eu(R["resultat"]), eu(p.get("resultat"))],
        ["TOTAL I (capitaux propres)", "142", eu(R["capitaux_propres"]), eu(p_cp)],
        ["Provisions pour risques et charges - TOTAL II", "154", "0", "0"],
        ["Emprunts et dettes assimilées", "156", eu(R["emprunt"]), eu(p.get("emprunt"))],
        ["Dettes fiscales et sociales", "172", eu(R["dette_tva"]), "0"],
        ["TOTAL III (dettes)", "176", eu(R["emprunt"] + R["dette_tva"]), eu(p.get("emprunt"))],
        ["TOTAL GÉNÉRAL (I + II + III)", "180", eu(R["total_passif"]), eu(p_total)],
        ["Dont dettes à plus d'un an", "195", eu(R["dettes_plus_un_an"]), eu(p.get("dettes_plus_un_an"))],
        ["Coût des immobilisations acquises dans l'exercice", "182", "0", ""],
    ]
    histo.append(tableau(passif, W, gras=(3, 7, 8)))
    histo.append(PageBreak())

    # ---------- 2033-B ----------
    histo += entete(h, a, "2033-B-SD", "2. COMPTE DE RÉSULTAT SIMPLIFIÉ DE L'EXERCICE")
    cr = [
        ["A - Résultat comptable", "Case", f"{a}", f"{pa}"],
        ["Production vendue - services", "218", eu(R["ca"]), eu(p.get("ca"))],
        ["Subventions d'exploitation reçues", "226", eu(R["subventions"]), eu(p.get("subventions"))],
        ["Autres produits", "230", eu(R["autres_produits"]), "0"],
        ["Total des produits d'exploitation hors TVA (I)", "232", eu(R["produits_exploitation"]), eu(p_prod)],
        ["Autres charges externes", "242", eu(R["charges_externes"]), eu(p.get("charges_externes"))],
        ["Impôts, taxes et versements assimilés", "244", eu(R["impots_taxes"]), "0"],
        ["Dotations aux amortissements", "254", eu(R["dotation"]), eu(p.get("dotation"))],
        ["Total des charges d'exploitation (II)", "264", eu(R["charges_exploitation"]), eu(p_chexp)],
        ["1 - Résultat d'exploitation (I - II)", "270", eu(R["resultat_exploitation"]), eu(p_prod - p_chexp)],
        ["Produits financiers (III)", "280", "0", "0"],
        ["Charges financières (V) - intérêts du prêt", "294", eu(R["interets"]), eu(p.get("interets"))],
        ["2 - Bénéfice ou perte", "310", eu(R["resultat"]), eu(p.get("resultat"))],
    ]
    histo.append(tableau(cr, W, gras=(4, 8, 9, 12)))
    histo.append(Spacer(1, 5 * mm))
    deficit = R["resultat"] < 0
    v = eu(abs(R["resultat"]))
    rf = [
        ["B - Résultat fiscal", "Case", "Bénéfice (col. 1)", "Déficit (col. 2)"],
        ["Report du résultat comptable", "312 / 314", "" if deficit else v, v if deficit else ""],
        ["Réintégrations (rémunérations, amortissements, provisions, impôts non déductibles)", "316 à 330", "0", ""],
        ["Résultat fiscal avant imputation des déficits antérieurs", "352 / 354", "" if deficit else v, v if deficit else ""],
        ["Résultat fiscal après imputation des déficits", "370 / 372", "" if deficit else v, v if deficit else ""],
    ]
    histo.append(tableau(rf, W, gras=(4,)))
    histo.append(PageBreak())

    # ---------- 2033-C et D ----------
    histo += entete(h, a, "2033-C-SD", "3. IMMOBILISATIONS - AMORTISSEMENTS")
    W2 = [70 * mm, 27 * mm, 27 * mm, 23 * mm, 23 * mm]
    imml = [
        ["Installations techniques, matériel et outillage", "Début (440 / 530)", "Augmentations (442 / 532)", "Diminutions", "Fin (446 / 536)"],
        ["Valeur brute", eu(brut), "0", "0", eu(brut)],
        ["Amortissements", eu(R["amort_cumul"] - R["dotation"]), eu(R["dotation"]), "0", eu(R["amort_cumul"])],
        ["TOTAL (490 / 570 à 576)", eu(brut), eu(R["dotation"]), "0", eu(R["amort_cumul"])],
    ]
    histo.append(tableau(imml, W2, gras=(3,)))
    histo.append(Spacer(1, 8 * mm))
    histo += entete(h, a, "2033-D-SD", "4. RELEVÉ DES PROVISIONS - DÉFICITS - DIVERS")
    tot_prec = sum(x for k, x in h.get("deficits", {}).items() if x and a - 6 <= int(k) < a)
    defl = [
        ["II - Déficits reportables", "Case", "Montant", ""],
        ["Déficits restant à reporter au titre de l'exercice précédent", "982", eu(tot_prec), ""],
        ["Déficits imputés", "983", eu(R["deficits_imputes"]), ""],
        ["Déficits reportables", "984", eu(tot_prec - R["deficits_imputes"]), ""],
        ["Déficits de l'exercice", "860", eu(R["deficit_annee"]), ""],
        ["Total des déficits restant à reporter", "870", eu(tot_prec - R["deficits_imputes"] + R["deficit_annee"]), ""],
        ["III - Divers : TVA collectée", "374", eu(R["tva_collectee"]), ""],
        ["III - Divers : TVA déductible sur biens et services", "378", eu(R["tva_deductible"]), ""],
    ]
    histo.append(tableau(defl, W, gras=(5,)))
    histo.append(PageBreak())

    # ---------- 2031 et 2042-C-PRO ----------
    ent = h["entreprise"]
    histo += entete(h, a, "2031-SD", "DÉCLARATION DE RÉSULTATS - BIC (impôt sur le revenu)")
    rec = [
        ["Rubrique", "", "Bénéfice (col. 1)", "Déficit (col. 2)"],
        ["Régime simplifié d'imposition", "", "", ""],
        ["C1 - Résultat fiscal", "", "" if deficit else v, v if deficit else ""],
        ["C3 - Total", "", "" if deficit else v, v if deficit else ""],
        ["C4 - Bénéfice imposable / déficit déductible", "", "" if deficit else v, v if deficit else ""],
        ["C7 - dont BIC non professionnels", "", "" if deficit else v, v if deficit else ""],
        ["Annexe 2031, cadre I - Autres BIC non professionnels", "", "" if deficit else v, v if deficit else ""],
    ]
    histo.append(tableau(rec, W, gras=(4,)))
    histo.append(Spacer(1, 6 * mm))
    histo.append(Paragraph(f"DÉCLARATION DE REVENUS {a + 1} (revenus {a}) - formulaire 2042-C-PRO", S_TITRE))
    histo.append(Paragraph("Revenus industriels et commerciaux non professionnels - régime du bénéfice réel - déclarant 1", S_SOUS))
    histo.append(Spacer(1, 3 * mm))
    cases = [["Case", "Libellé", "Montant", ""],
             ["5NF" if deficit else "5NC", "Déficit de l'année" if deficit else "Revenus imposables", v, ""]]
    noms = ["5RN", "5RO", "5RP", "5RQ", "5RR", "5RW"]
    for i, an in enumerate(range(a - 6, a)):
        x = h.get("deficits", {}).get(str(an))
        if x:
            cases.append([noms[i], f"Déficit {an} non encore déduit", eu(x), ""])
    W3 = [20 * mm, 100 * mm, 25 * mm, 25 * mm]
    t = Table(cases, colWidths=W3)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                           ("BACKGROUND", (0, 0), (-1, 0), GRIS), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa5a0")),
                           ("ALIGN", (2, 0), (2, -1), "RIGHT"), ("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 9)]))
    histo.append(t)
    histo.append(Paragraph("Les cases des déficits antérieurs changent de lettre chaque année : vérifier l'année écrite à côté de la case.", S_SOUS))
    histo.append(Spacer(1, 6 * mm))
    if estimes:
        histo.append(Paragraph("Montants ESTIMÉS dans ce projet (à remplacer par les vrais avant dépôt)", S_CELB))
        for x in estimes:
            histo.append(Paragraph("- " + x, S_NOTE))
        histo.append(Spacer(1, 3 * mm))
    if questions:
        histo.append(Paragraph("Points à vérifier avec le comptable", S_CELB))
        for q in questions:
            histo.append(Paragraph("- " + q, S_NOTE))
    histo.append(Spacer(1, 4 * mm))
    histo.append(Paragraph(f"Préparé le {datetime.now():%d/%m/%Y à %H:%M} par Archi (outil liasse_fiscale). Archi n'est pas "
                           "comptable : ce projet ne remplace pas la liasse officielle. Dépôt : espace professionnel "
                           "impots.gouv.fr ou par le comptable.", S_SOUS))

    def pied(c, doc):
        c.saveState()
        c.setFont("Helvetica", 7.5)
        c.setFillColor(colors.HexColor("#777777"))
        c.drawString(15 * mm, 10 * mm, f"{ent['nom']} - Projet de liasse fiscale {a}")
        c.drawRightString(195 * mm, 10 * mm, f"page {doc.page}")
        c.restoreState()

    doc = SimpleDocTemplate(chemin, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=f"Projet de liasse fiscale {a} - {ent['nom']}", author="Archi")
    doc.build(histo, onFirstPage=pied, onLaterPages=pied)
    return chemin
