"""Garde-fou avant tout envoi sur GitHub : cherche secrets et donnees personnelles dans le depot.
Usage : python outils_depot/verifier_depot.py .   (code de sortie 1 si quelque chose est trouve)
N'affiche JAMAIS la valeur trouvee : seulement le fichier, la ligne et la categorie."""
import os, re, sys

MOTIFS = {
    "cle_api": r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-|AIza[0-9A-Za-z_\-]{30,}|tvly-[A-Za-z0-9]{10,}|hf_[A-Za-z0-9]{20,})",
    "token_telegram": r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b",
    "jwt": r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
    "secret_en_dur": r"(?i)(api[_-]?key|token|secret|password|passwd|mot_de_passe|bearer|x-archi-cle)\s*[:=]\s*[\"'][A-Za-z0-9_\-+/=]{12,}[\"']",
    "cle_privee": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "email": r"[A-Za-z0-9._%+\-]+@(?!example\.|exemple\.|users\.noreply\.github\.com)[A-Za-z0-9\-]+\.[A-Za-z0-9.\-]*[a-z]{2,}",
    "telephone": r"(?<![\d.])(\+33|\+41|0)[1-9]([ .\-]?\d{2}){4}(?![\d.])",
    "adresse_tunnel": r"(?i)([a-z0-9\-]+\.ngrok(-free)?\.(app|io|dev)|[a-z0-9\-]+\.ts\.net|\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+\b)",
    "chat_id": r"(?i)chat_?id[\"']?\s*[:=]\s*[\"']?-?\d{6,}",
    "chemin_utilisateur": r"(?i)c:[\/]+users[\/]+(?!utilisateur|public|<)[a-z]",
}
# Mots personnels (nom, lieux, pseudos) : lus dans un fichier LOCAL ignore par git, jamais ecrits dans le depot.
# Fichier : .local/mots_perso.txt (un mot ou une expression par ligne), ou variable ARCHI_MOTS_PERSO (separes par ;).
def charger_mots_perso(racine):
    mots = [m for m in os.environ.get("ARCHI_MOTS_PERSO", "").split(";") if m.strip()]
    f = os.path.join(racine, ".local", "mots_perso.txt")
    if os.path.isfile(f):
        mots += [l for l in open(f, encoding="utf-8").read().splitlines() if l.strip() and not l.startswith("#")]
    return [re.compile(r"(?i)(?<![a-z0-9])" + re.escape(m.strip()) + r"(?![a-z0-9])") for m in mots]


MOTS_PERSO = []


def mots_perso(ligne):
    return any(m.search(ligne) for m in MOTS_PERSO)


FICHIERS_INTERDITS = re.compile(r"(?i)(^\.env$|secret|^cle.*\.txt$|\.pickle$|\.pkl$|credentials.*\.json$|\.keystore$|\.jks$|\.apk$|\.sqlite$)")
PERMIS = {".env.example"}  # le detecteur se controle lui-meme (sauf ses motifs)
IGNORER_DOSSIERS = {".git", "node_modules", "__pycache__", "build", ".gradle", ".local",
                    "programmes", "telechargements", "dist"}   # poses par installation.bat / faire_le_zip.py, ignores par git
BINAIRES = (".jar", ".png", ".jpg", ".webp", ".zip")


def main(racine):
    global MOTS_PERSO
    MOTS_PERSO = charger_mots_perso(racine)
    trouves = 0
    for d, dossiers, fichiers in os.walk(racine):
        dossiers[:] = [x for x in dossiers if x not in IGNORER_DOSSIERS]
        for f in fichiers:
            p = os.path.relpath(os.path.join(d, f), racine)
            if f in PERMIS:
                continue
            if FICHIERS_INTERDITS.search(f) and not f.endswith(".exemple.json"):  # un exemple est relu, pas interdit
                print(f"FICHIER INTERDIT\t{p}")
                trouves += 1
                continue
            if f.endswith(BINAIRES):
                continue
            try:
                texte = open(os.path.join(d, f), encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for i, ligne in enumerate(texte.splitlines(), 1):
                if mots_perso(ligne):
                    print(f"perso\t{p}:{i}")
                    trouves += 1
                if f == "verifier_depot.py" and re.match(r'\s*"[a-z_]+": r"', ligne):
                    continue  # ses propres motifs
                for cat, motif in MOTIFS.items():
                    if re.search(motif, ligne):
                        print(f"{cat}\t{p}:{i}")
                        trouves += 1
    if not MOTS_PERSO:
        print("Attention : aucune liste de mots perso (.local/mots_perso.txt) : nom et lieux prives NON verifies.")
    print(f"{trouves} probleme(s)" if trouves else "OK : aucun secret ni donnee personnelle reconnue")
    return 1 if trouves else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
