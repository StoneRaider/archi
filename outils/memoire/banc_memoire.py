"""Banc de mesure de la memoire, avec le VRAI modele local (LM Studio doit tourner) : 30 phrases, rien n'est range.
   python outils/memoire/banc_memoire.py            (avec le Python d'Archi : il lit le .env tout seul)
15 phrases contiennent un fait durable a retenir, 15 n'en contiennent pas (question, ordre, humeur, secret...).
Le banc dit, phrase par phrase, ce que le greffier a retenu, puis le score et le temps moyen."""
import json
import os
import subprocess
import sys
import tempfile
import time

ICI = os.path.dirname(os.path.abspath(__file__))
A_RETENIR = [
    ("Si je te parle de mon chien, qui s'appelle Médor, tu vas créer une fiche ?", "medor"),
    ("Ma sœur Léa habite à Lyon.", "lea"),
    ("Je suis né à Annecy en 1988.", "annecy"),
    ("J'adore le reblochon mais je déteste les huîtres.", "reblochon"),
    ("Je travaille comme infirmier de nuit à l'hôpital.", "infirmier"),
    ("Mon projet du moment, c'est de construire une cabane dans le jardin.", "cabane"),
    ("On a un chalet aux Contamines où on va tous les hivers.", "chalet"),
    ("Retiens que je suis allergique aux arachides.", "arachide"),
    ("Mon fils Tom a sept ans.", "tom"),
    ("Je roule en vieille Mustang de 1967.", "mustang"),
    ("Mon meilleur ami s'appelle Karim, on se connaît depuis le lycée.", "karim"),
    ("Je préfère qu'on me réponde court, sans blabla.", "court"),
    ("Mon chat Pixel dort toujours sur le clavier.", "pixel"),
    ("Je fais de l'escalade tous les mardis soir.", "escalade"),
    ("Ma femme Sofia est architecte.", "sofia"),
]
A_LAISSER = [
    "Quels outils as-tu ?",
    "Rappelle-moi dans 2 minutes de boire un verre d'eau.",
    "Quelle heure est-il ?",
    "Fais-moi un PDF qui résume ce que tu sais faire.",
    "Je suis fatigué ce soir.",
    "Il pleut chez moi aujourd'hui.",
    "Peux-tu allumer le radiateur ?",
    "Merci, c'est parfait pour moi !",
    "Je vais faire les courses, à tout à l'heure.",
    "Donne-moi la météo de demain.",
    "Mon mot de passe Netflix est tulipe42.",
    "Tu m'entends bien, là ?",
    "J'ai faim, je vais manger.",
    "Que sais-tu sur le four solaire ?",
    "Envoie un message à ma sœur pour lui dire que j'arrive.",
]


def plat(t):
    import unicodedata
    t = unicodedata.normalize("NFD", str(t).lower()).replace("œ", "oe")
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def retenir(texte, dossier):
    f = os.path.join(dossier, "d.json")
    with open(f, "w", encoding="utf-8") as h:
        json.dump({"action": "retenir", "a_blanc": "oui", "texte": texte}, h)
    debut = time.time()
    r = subprocess.run([sys.executable, os.path.join(ICI, "memoire.py"), "--fichier", f], capture_output=True,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1]), time.time() - debut


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    dossier = tempfile.mkdtemp(prefix="banc_memoire_")
    bons = total = 0
    durees = []
    print("--- 15 phrases A RETENIR")
    for texte, attendu in A_RETENIR:
        r, s = retenir(texte, dossier)
        faits = r.get("retenu") or []
        ok = any(attendu in plat(x.get("fait", "") + " " + x.get("sujet", "")) for x in faits)
        bons += ok
        total += 1
        if r.get("appel_modele"):
            durees.append(s)
        print("%s  %4.1f s  %s\n        -> %s" % ("OK   " if ok else "RATE ", s, texte,
                                                   " | ".join("[%s/%s] %s" % (x["piece"], x["sujet"], x["fait"]) for x in faits) or
                                                   ("(rien) " + json.dumps(r.get("ecartes") or r.get("erreur") or "", ensure_ascii=False)[:160])))
    retenus = bons
    print("--- 15 phrases A NE PAS RETENIR")
    for texte in A_LAISSER:
        r, s = retenir(texte, dossier)
        faits = r.get("retenu") or []
        ok = not faits
        bons += ok
        total += 1
        if r.get("appel_modele"):
            durees.append(s)
        print("%s  %4.1f s  %s%s" % ("OK   " if ok else "TROP ", s, texte,
                                      "" if ok else "\n        -> " + " | ".join("[%s/%s] %s" % (x["piece"], x["sujet"], x["fait"]) for x in faits)))
    print("\nSCORE : %d sur %d (a retenir : %d sur %d ; a laisser : %d sur %d). Temps moyen quand le modele est appele : %.1f s (%d appels)."
          % (bons, total, retenus, len(A_RETENIR), bons - retenus, len(A_LAISSER), sum(durees) / max(1, len(durees)), len(durees)))


if __name__ == "__main__":
    main()
