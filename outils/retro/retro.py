# retro.py - outil maison d'Archi : retro-ingenierie, triage d'une cible + mission pour l'expert.
#   python retro.py --fichier demande.json
#   demande.json : {"action": "triage"|"mission"|"liste", "cible": "<chemin ou bout de nom>", "but": "texte libre"}
#     triage (defaut) : identifie la cible (type, empreinte, structure, chaines utiles), ecrit un rapport
#                       et une MISSION pre-remplie pour l'expert (Claude Code + REA). Lecture seule.
#     mission         : regenere la mission a partir d'un triage deja fait.
#     liste           : les cibles analysables trouvees sur le PC (recentes d'abord).
#
# REGLES (methode retro, decision de J) : on analyse SEULEMENT des logiciels/appareils qui
# appartiennent a J, pour COMPRENDRE et REECRIRE a neuf (interoperabilite). JAMAIS de
# contournement de licence, d'activation, de protection anti-copie ou de DRM. Cet outil ne LANCE
# jamais la cible (analyse statique) ; l'analyse dynamique est un geste separe, decide par J.
# Il ne lit ni n'affiche aucune cle/mot de passe/jeton.

import argparse
import datetime
import hashlib
import json
import os
import re
import struct
import sys
import zipfile

ICI = os.path.dirname(os.path.abspath(__file__))
MAISON = os.path.expanduser("~")
RACINES = [os.environ.get("ARCHI_BASE") or os.path.join(MAISON, ".n8n-files"), os.path.join(MAISON, "Downloads"),
           os.path.join(MAISON, "Documents"), os.path.join(MAISON, "Desktop")]
RAPPORTS = os.path.join(ICI, "rapports")
MISSIONS = os.path.join(ICI, "missions")
IGNORER = ("node_modules", ".gradle", "buildOutputCleanup", "fileHashes", "executionHistory",
           "fileChanges", ".cache", ".git", "navigateur", os.sep + "build" + os.sep, os.sep + "venv")


def _ignorer(dossier):
    return any(x in dossier for x in IGNORER)
MAX_CHAINES_OCTETS = 8 * 1024 * 1024   # on ne lit que les 8 premiers Mo pour les chaines
EXT_ANALYSABLES = (".exe", ".dll", ".apk", ".aab", ".jar", ".dex", ".so", ".bin",
                   ".wasm", ".sqlite", ".db", ".gguf", ".asar", ".pcap", ".pcapng",
                   ".elf", ".img", ".fw", ".sys", ".node")
# mots qui trahissent un secret : on ne recopie jamais ces chaines
SECRET_MOTS = re.compile(r"(?i)(password|passwd|secret|api[_-]?key|token|authorization|bearer|private[_-]?key|x-archi-cle)")
# vrais domaines : on ne garde un hote que si son extension est une vraie extension
TLDS = set("com net org io fr ch de be uk eu co us ca es it nl pl ru cn jp in app dev cloud ai gg tv me info biz xyz online site live tech api sh gov edu local".split())
# fichiers sensibles : jamais d'analyse de contenu (ils contiennent des identifiants)
SENSIBLE = re.compile(r"(?i)(^database\.sqlite|\.sqlite-wal$|\.env$|^secret|^cle|credential|token|\.key$|\.pem$|\.pfx$|\.p12$|\.pickle$|\.pkl$)")


class Erreur(Exception):
    pass


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def empreinte(path):
    h = hashlib.sha256()
    taille = 0
    with open(path, "rb") as f:
        while True:
            bloc = f.read(1024 * 1024)
            if not bloc:
                break
            taille += len(bloc)
            h.update(bloc)
    return h.hexdigest(), taille


def lire_tete(path, n=64):
    with open(path, "rb") as f:
        return f.read(n)


# --- detection du type ---------------------------------------------------

def _zip_apk(path):
    info = {"entrees": 0, "dex": 0, "abis": [], "manifeste": False, "resources": False,
            "signature": [], "office": None, "asar": False, "noms_tete": []}
    try:
        with zipfile.ZipFile(path) as z:
            noms = z.namelist()
    except Exception:
        return info
    info["entrees"] = len(noms)
    info["noms_tete"] = noms[:20]
    abis = set()
    for n in noms:
        if n == "AndroidManifest.xml":
            info["manifeste"] = True
        elif n == "resources.arsc":
            info["resources"] = True
        elif n.startswith("classes") and n.endswith(".dex"):
            info["dex"] += 1
        elif n.startswith("lib/") and n.count("/") >= 2:
            abis.add(n.split("/")[1])
        elif n.startswith("META-INF/") and n.upper().endswith((".RSA", ".DSA", ".EC", ".SF")):
            if "v1 (jar)" not in info["signature"]:
                info["signature"].append("v1 (jar)")
        elif n.startswith("word/"):
            info["office"] = "docx"
        elif n.startswith("xl/"):
            info["office"] = "xlsx"
        elif n.startswith("ppt/"):
            info["office"] = "pptx"
    info["abis"] = sorted(abis)
    # signature APK v2/v3 : bloc "APK Sig Block 42" juste avant le central directory
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            fin = f.tell()
            f.seek(max(0, fin - 1024 * 128))
            tail = f.read()
        if b"APK Sig Block 42" in tail:
            info["signature"].append("v2/v3 (bloc APK)")
    except Exception:
        pass
    return info


def _est_pyinstaller(path):
    # cookie PyInstaller dans les derniers octets de l'exe
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            fin = f.tell()
            f.seek(max(0, fin - 1024 * 1024))
            tail = f.read()
        return b"MEI\x0c\x0b\x0a\x0b\x0e" in tail or b"pyi-" in tail or b"PYZ-00.pyz" in tail
    except Exception:
        return False


def detecter_type(path):
    tete = lire_tete(path, 64)
    nom = os.path.basename(path).lower()
    r = {"cle": "inconnu", "humain": "Type non reconnu", "details": {}}

    if tete[:2] == b"MZ":
        if _est_pyinstaller(path):
            r.update(cle="pe_pyinstaller", humain="Programme Windows empaquete avec PyInstaller (Python)")
        else:
            r.update(cle="pe", humain="Programme Windows natif (.exe/.dll)")
        r["details"].update(analyser_pe(path))
        if r["details"].get("dotnet"):
            r.update(cle="pe_dotnet", humain="Programme .NET (C#/VB, code manage)")
        return r
    if tete[:4] == b"\x7fELF":
        r.update(cle="elf", humain="Programme/binaire Linux ou composant de firmware (ELF)")
        return r
    if tete[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        if tete[:4] == b"\xca\xfe\xba\xbe":
            r.update(cle="java_ou_macho", humain="Classe Java (.class) ou binaire Mac fat (a confirmer)")
        else:
            r.update(cle="macho", humain="Programme macOS (Mach-O)")
        return r
    if tete[:4] == b"dex\n":
        r.update(cle="dex", humain="Code Android compile (DEX)")
        return r
    if tete[:4] == b"\x00asm":
        r.update(cle="wasm", humain="Module WebAssembly (WASM)")
        return r
    if tete[:16].startswith(b"SQLite format 3"):
        r.update(cle="sqlite", humain="Base de donnees SQLite")
        return r
    if tete[:4] == b"GGUF":
        r.update(cle="gguf", humain="Modele d'IA au format GGUF")
        return r
    if tete[:5] == b"%PDF-":
        r.update(cle="pdf", humain="Document PDF (utilise plutot l'outil lire_pdf)")
        return r
    if tete[:4] in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4") or tete[:4] == b"\x0a\x0d\x0d\x0a":
        r.update(cle="pcap", humain="Capture reseau (pcap/pcapng)")
        return r
    if tete[:4] == b"PK\x03\x04":
        z = _zip_apk(path)
        r["details"] = z
        if z["manifeste"] and z["dex"]:
            r.update(cle="apk", humain="Application Android (APK)")
        elif z["office"]:
            r.update(cle="office", humain="Document Office (%s)" % z["office"])
        elif any(n.endswith(".class") for n in z["noms_tete"]) or nom.endswith(".jar"):
            r.update(cle="jar", humain="Archive Java (JAR)")
        elif nom.endswith(".aab") or any(n.startswith("base/") for n in z["noms_tete"]):
            r.update(cle="aab", humain="Bundle d'application Android (AAB)")
        else:
            r.update(cle="zip", humain="Archive ZIP")
        return r
    if nom.endswith(".asar"):
        r.update(cle="asar", humain="Application Electron empaquetee (ASAR)")
        return r
    return r


def analyser_pe(path):
    d = {}
    try:
        import pefile
    except Exception:
        d["note_libs"] = "Bibliotheques d'analyse (pefile) pas encore installees : lance l'installateur."
        return d
    try:
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories()
        machines = {0x14c: "x86 (32 bits)", 0x8664: "x64 (64 bits)", 0xaa64: "ARM64", 0x1c0: "ARM"}
        d["architecture"] = machines.get(pe.FILE_HEADER.Machine, hex(pe.FILE_HEADER.Machine))
        sous = {2: "fenetre (GUI)", 3: "console"}
        d["sous_systeme"] = sous.get(pe.OPTIONAL_HEADER.Subsystem, str(pe.OPTIONAL_HEADER.Subsystem))
        d["sections"] = [s.Name.decode(errors="ignore").strip("\x00") for s in pe.sections][:20]
        try:
            d["imphash"] = pe.get_imphash()
        except Exception:
            pass
        dirs = pe.OPTIONAL_HEADER.DATA_DIRECTORY
        d["dotnet"] = len(dirs) > 14 and dirs[14].VirtualAddress != 0
        d["signe"] = len(dirs) > 4 and dirs[4].VirtualAddress != 0
        dlls = []
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            for e in pe.DIRECTORY_ENTRY_IMPORT:
                dlls.append(e.dll.decode(errors="ignore"))
        d["dll_importees"] = dlls[:30]
        pe.close()
    except Exception as e:
        d["note_pe"] = "Lecture PE partielle (%s)." % type(e).__name__
    return d


# --- chaines utiles (URL, hotes, IP), sans secrets ------------------------

RE_CHAINE = re.compile(rb"[\x20-\x7e]{4,}")
RE_URL = re.compile(r"https?://[^\s\"'<>]{4,200}")
RE_HOTE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b", re.I)
RE_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def chaines_utiles(path, cle):
    data = b""
    try:
        if cle in ("apk", "aab", "jar", "zip"):
            # pour une archive : on lit les petites entrees texte, pas les octets bruts
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    if n.endswith((".xml", ".json", ".txt", ".properties", ".ini", ".cfg", ".smali")):
                        try:
                            data += z.read(n)[:200000]
                        except Exception:
                            pass
                    if len(data) > MAX_CHAINES_OCTETS:
                        break
        else:
            with open(path, "rb") as f:
                data = f.read(MAX_CHAINES_OCTETS)
    except Exception:
        return {}
    textes = [m.decode("ascii", "ignore") for m in RE_CHAINE.findall(data)]
    urls, hotes, ips = set(), set(), set()
    for t in textes:
        if SECRET_MOTS.search(t):
            continue
        for u in RE_URL.findall(t):
            u = u.split("?")[0].split("#")[0]
            if not SECRET_MOTS.search(u):
                urls.add(u)
        for h in RE_HOTE.findall(t):
            tld = h.rsplit(".", 1)[-1].lower()
            if tld in TLDS and not h.lower().endswith("schemas.android.com"):
                hotes.add(h.lower())
        for ip in RE_IP.findall(t):
            ips.add(ip)
    return {"urls": sorted(urls)[:40], "hotes": sorted(hotes)[:40], "ips": sorted(ips)[:20]}


# --- recommandations REA + outils libres par type -------------------------

def recommander(cle, chemin):
    c = chemin.replace("\\", "/")
    T = {
        "apk": (["rea inspect-android-package \"%s\" --json" % c,
                 "rea inspect-apk-signature \"%s\" --json" % c,
                 "rea analyze \"%s\" --json   (workflow Android, JADX integre a REA)" % c],
                ["JADX (integre a REA)", "apktool (ressources/manifeste)"]),
        "aab": (["rea analyze \"%s\" --json" % c], ["bundletool -> APK, puis JADX"]),
        "dex": (["rea inspect-android-package \"%s\" --json" % c], ["JADX"]),
        "pe": (["rea analyze \"%s\" --json   (Ghidra)" % c,
                "rea inspect-pe-load-config \"%s\" --json" % c,
                "rea inspect-binary-layout \"%s\" --json" % c], ["Ghidra (decompilation)"]),
        "pe_dotnet": (["rea inspect-managed-artifact \"%s\" --json" % c,
                       "rea inspect-managed-members \"%s\" --json" % c], ["ILSpy / dnSpyEx (lecture C#)"]),
        "pe_pyinstaller": (["rea analyze \"%s\" --json   (applications Python empaquetees)" % c],
                           ["pyinstxtractor-ng (depaqueter), puis pycdc (decompiler les .pyc)"]),
        "elf": (["rea analyze \"%s\" --json   (Ghidra)" % c,
                 "rea inspect-binary-layout \"%s\" --json" % c], ["Ghidra", "binwalk/unblob si firmware"]),
        "macho": (["rea inspect-macho \"%s\" --json" % c, "rea analyze \"%s\" --json" % c], ["Ghidra"]),
        "java_ou_macho": (["rea inspect-macho \"%s\" --json" % c], ["CFR/Procyon si Java", "Ghidra si Mach-O"]),
        "jar": (["rea analyze \"%s\" --json" % c], ["CFR / Procyon (decompiler Java)"]),
        "wasm": (["rea inspect-wasm-artifact \"%s\" --json" % c], ["WABT (wasm2wat)"]),
        "sqlite": (["rea inspect-sqlite-database \"%s\" --json" % c], ["DB Browser for SQLite"]),
        "asar": (["rea analyze-javascript-application \"%s\" --json" % c,
                  "rea inspect-electron-page \"%s\" --json" % c], ["asar (extraire), lecture du JS"]),
        "pcap": (["rea inspect-packet-capture \"%s\" --json" % c], ["tshark / mitmproxy"]),
        "gguf": ([], ["inspection d'en-tete GGUF (metadonnees du modele)"]),
        "office": ([], ["c'est un document : pas de retro-ingenierie"]),
        "pdf": ([], ["utilise l'outil lire_pdf"]),
        "zip": (["rea analyze \"%s\" --json" % c], ["extraire et retrier le contenu"]),
        "inconnu": (["rea analyze \"%s\" --json   (laisser REA deviner)" % c],
                    ["binwalk/unblob (reperer un firmware ou un conteneur)"]),
    }
    return T.get(cle, T["inconnu"])


# --- mission pour l'expert ------------------------------------------------

def construire_mission(infos, but):
    moteurs, libres = recommander(infos["type"]["cle"], infos["chemin"])
    d = infos["type"]["details"]
    lignes = []
    A = lignes.append
    A("# MISSION RETRO-INGENIERIE pour l'expert")
    A("")
    A("Genere le %s par l'outil maison `retro` (triage automatique)." % infos["date"])
    A("")
    A("## Cible")
    A("- Fichier : `%s`" % infos["chemin"])
    A("- Type : %s" % infos["type"]["humain"])
    A("- Taille : %s octets" % infos["taille"])
    A("- Empreinte SHA-256 : `%s`" % infos["sha256"])
    if d:
        apercu = {k: v for k, v in d.items() if k not in ("noms_tete",)}
        A("- Details du triage : `%s`" % json.dumps(apercu, ensure_ascii=False)[:600])
    A("")
    A("## But")
    A("- %s" % (but or "Comprendre comment la cible fonctionne pour l'interoperabilite avec Archi, puis reecrire a neuf si besoin."))
    A("")
    A("## Regles permises (NON negociables)")
    A("- Cible appartenant a J, analysee pour COMPRENDRE et REECRIRE a neuf.")
    A("- INTERDIT : contourner une licence, une activation, une protection anti-copie, un chiffrement ou un DRM ; recopier du code proprietaire.")
    A("- On garde le protocole, les formats, les adresses, les commandes, la logique ; puis on reecrit a neuf.")
    A("")
    A("## Plan - analyse STATIQUE d'abord (ne lance pas la cible)")
    if moteurs:
        for m in moteurs:
            A("- `%s`" % m)
    else:
        A("- Pas de moteur REA dedie pour ce type : inspection manuelle.")
    A("- Sauver l'Evidence dans un fichier, puis en projeter un resume (les rapports REA peuvent etre tres gros).")
    A("- Ecrire le rapport final (ce que fait la cible, entrees/sorties, reseau, formats) dans le chateau.")
    A("")
    A("## Plan - analyse DYNAMIQUE (seulement APRES accord explicite de J)")
    A("- Lancer la cible et capturer son trafic / son comportement : A FAIRE SEULEMENT APRES \"vas-y\" de J.")
    A("")
    A("## Outils libres utiles")
    for o in libres:
        A("- %s" % o)
    A("")
    A("## Rappel")
    A("- REA (mcp__rea__*) n'est disponible qu'en mode execution (apres \"expert, vas-y\").")
    return "\n".join(lignes) + "\n"


# --- resolution de la cible ----------------------------------------------

def trouver_cible(nom):
    if not nom:
        raise Erreur("Il manque la cible (champ \"cible\").")
    if os.path.isabs(nom) and os.path.isfile(nom):
        return nom
    cand = os.path.join(os.getcwd(), nom)
    if os.path.isfile(cand):
        return cand
    bout = nom.lower()
    trouves = []
    for racine in RACINES:
        if not os.path.isdir(racine):
            continue
        for dossier, _sous, fichiers in os.walk(racine):
            if _ignorer(dossier):
                continue
            for f in fichiers:
                if bout in f.lower():
                    p = os.path.join(dossier, f)
                    try:
                        trouves.append((os.path.getmtime(p), p))
                    except Exception:
                        pass
    if not trouves:
        raise Erreur("Cible introuvable : « %s ». Donne le chemin complet ou un bout du nom." % nom)
    trouves.sort(reverse=True)
    return trouves[0][1]


def triage(d, avec_mission=True):
    cible = trouver_cible(str(d.get("cible") or "").strip())
    if SENSIBLE.search(os.path.basename(cible)):
        return repondre(False, "Cible sensible (identifiants/cles) : je ne l'analyse pas. Choisis un logiciel ou une appli a toi.")
    but = str(d.get("but") or "").strip()
    sha, taille = empreinte(cible)
    typ = detecter_type(cible)
    chaines = chaines_utiles(cible, typ["cle"])
    date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    infos = {"chemin": cible, "sha256": sha, "taille": taille, "type": typ,
             "chaines": chaines, "date": date, "but": but}

    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(cible))
    os.makedirs(RAPPORTS, exist_ok=True)
    os.makedirs(MISSIONS, exist_ok=True)
    chemin_rapport = os.path.join(RAPPORTS, base + "_triage.json")
    with open(chemin_rapport, "w", encoding="utf-8") as f:
        json.dump(infos, f, ensure_ascii=False, indent=1)
    chemin_mission = ""
    if avec_mission:
        chemin_mission = os.path.join(MISSIONS, base + "_mission.md")
        with open(chemin_mission, "w", encoding="utf-8") as f:
            f.write(construire_mission(infos, but))

    moteurs, _ = recommander(typ["cle"], cible)
    bout_phrase = []
    bout_phrase.append("%s : %s." % (os.path.basename(cible), typ["humain"]))
    dd = typ["details"]
    if typ["cle"] == "apk":
        bout_phrase.append("Signatures : %s ; %d dex ; ABIs : %s." % (
            ", ".join(dd.get("signature") or ["aucune vue"]), dd.get("dex", 0),
            ", ".join(dd.get("abis") or ["-"])))
    if dd.get("architecture"):
        bout_phrase.append("Archi : %s, %s." % (dd["architecture"], dd.get("sous_systeme", "")))
    n_url = len(chaines.get("urls", []))
    n_hote = len(chaines.get("hotes", []))
    if n_url or n_hote:
        bout_phrase.append("%d URL et %d hotes releves." % (n_url, n_hote))
    if avec_mission:
        bout_phrase.append("Mission prete pour l'expert : %s." % chemin_mission.replace(MAISON, "~"))
    phrase = " ".join(bout_phrase)
    return repondre(True, phrase, type=typ["cle"], sha256=sha, taille=taille,
                    rapport=chemin_rapport, mission=chemin_mission,
                    moteurs_rea=moteurs, chaines=chaines)


def liste(_d):
    trouves = []
    for racine in RACINES:
        if not os.path.isdir(racine):
            continue
        for dossier, _s, fichiers in os.walk(racine):
            if _ignorer(dossier):
                continue
            for f in fichiers:
                if f.lower().endswith(EXT_ANALYSABLES):
                    p = os.path.join(dossier, f)
                    try:
                        trouves.append((os.path.getmtime(p), p))
                    except Exception:
                        pass
    trouves.sort(reverse=True)
    liste_p = [p.replace(MAISON, "~") for _m, p in trouves[:30]]
    if not liste_p:
        return repondre(True, "Aucune cible analysable trouvee.", cibles=[])
    return repondre(True, "%d cibles analysables (recentes d'abord). Donne-m'en une a analyser." % len(liste_p),
                    cibles=liste_p)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fichier")
    a = p.parse_args()
    if not a.fichier:
        return repondre(False, "Il manque la demande (--fichier).")
    try:
        with open(a.fichier, encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
        return repondre(False, "La demande est illisible.")
    act = str(d.get("action") or "triage").strip().lower()
    act = {"analyse": "triage", "analyser": "triage", "analyze": "triage",
           "lister": "liste", "list": "liste"}.get(act, act)
    try:
        if act == "triage":
            return triage(d, avec_mission=True)
        if act == "mission":
            return triage(d, avec_mission=True)
        if act == "liste":
            return liste(d)
        return repondre(False, "Action inconnue « %s ». Choix : triage, mission, liste." % act)
    except Erreur as e:
        return repondre(False, str(e))
    except Exception as e:
        return repondre(False, "Echec du triage (%s : %s)." % (type(e).__name__, str(e)[:160]))


if __name__ == "__main__":
    main()
