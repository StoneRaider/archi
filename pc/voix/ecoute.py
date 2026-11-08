# ecoute.py - l'oreille d'Archi dans le panneau Claude (mode vocal micro).
#
#   python ecoute.py ecouter [--micro "Nom du micro"]  -> ecoute en continu, une ligne JSON par evenement
#   python ecoute.py liste      -> les micros vus par Windows (JSON)
#   python ecoute.py stop       -> arrete l'ecoute en cours
#   python ecoute.py envoyer    -> envoie tout de suite ce qui a ete dicte (bouton de secours)
#   python ecoute.py annuler    -> jette ce qui a ete dicte
#   python ecoute.py essai FICHIER.wav  -> transcrit un fichier comme en vrai (pour tester)
#
# Fonctionnement : ffmpeg lit le micro (16 kHz mono). Des que la voix depasse le bruit de fond, l'enregistrement
# demarre ; chaque morceau de phrase (coupe apres 1 s de silence) est transcrit par Whisper (local, rien ne sort du PC)
# et ajoute a la dictee. Les longs blancs ne terminent JAMAIS le message : il part quand J dit
# "fin de transmission". "Archi, annule" jette la dictee. Quand Archi parle (dire.py), le micro est ignore.
#
# Evenements (stdout) : {"etat": "ecoute"|"enregistre"|"transcrit"|"archi_parle"}, {"partiel": "..."},
#                       {"message": "..."}, {"annule": true}, {"erreur": "..."}
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import wave

_WH = os.environ.get("ARCHI_WHISPER_DIR") or os.path.join(os.path.expanduser("~"), "whisper")   # dossier de whisper.cpp
FFMPEG = os.environ.get("ENTREE_FFMPEG") or os.path.join(_WH, "ffmpeg.exe")
WHISPER_CPU = os.path.join(_WH, "whisper-bin-x64", "Release", "whisper-cli.exe")
WHISPER_GPU = os.path.join(_WH, "vulkan", "whisper-cli.exe")  # whisper.cpp compile Vulkan (cartes AMD/NVIDIA/Intel)
WHISPER = os.environ.get("ENTREE_WHISPER") or (WHISPER_GPU if os.path.exists(WHISPER_GPU) else WHISPER_CPU)
MODELE = os.environ.get("ECOUTE_MODELE") or os.path.join(_WH, "ggml-medium-q5_0.bin")
MODELE_COURT = os.environ.get("ECOUTE_MODELE_COURT", "" if WHISPER == WHISPER_GPU else os.path.join(_WH, "ggml-small.bin"))  # "" = toujours MODELE
COURT_MAX = float(os.environ.get("ECOUTE_COURT_MAX", "2.5"))  # secondes de son
MICRO = os.environ.get("ECOUTE_MICRO", "")   # nom du micro vu par Windows (python ecoute.py liste) ; vide = micro par defaut
DOSSIER = os.environ.get("ECOUTE_DOSSIER") or os.path.join(tempfile.gettempdir(), "archi_voix")
PID = os.path.join(DOSSIER, "ecoute.pid")
PID_PAROLE = os.path.join(DOSSIER, "lecture.pid")  # ecrit par dire.py pendant qu'Archi parle
DRAPEAU_ENVOYER = os.path.join(DOSSIER, "ecoute_envoyer")
DRAPEAU_ANNULER = os.path.join(DOSSIER, "ecoute_annuler")
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)

TAUX = 16000
TRAME = 480                 # 30 ms
PREROLL = 15                # 450 ms gardees avant le debut de la voix
DEBUT = (5, 8)              # 5 trames de voix sur 8 = ca parle
SILENCE_FIN = int(os.environ.get("ECOUTE_SILENCE", "23"))           # ~0,7 s de silence = fin d'un MORCEAU (pas du message)
MORCEAU_MAX = 25 * 1000 // 30
SEUIL_MIN = 300             # amplitude RMS minimale d'une voix (int16)
# 05/11 : micros faibles amplifies (un casque gamer : voix a RMS 100-670 contre 1 500-6 000 pour les
# lunettes ; la phrase de fin, dite plus bas, restait sous le seuil et n'etait jamais enregistree).
GAIN_MICRO = {}   # micro trop faible : {"bout du nom du micro": gain}, ex. {"casque": 6.0}


def gain_pour(micro):
    if os.environ.get("ECOUTE_GAIN"):
        return float(os.environ["ECOUTE_GAIN"])
    m = (micro or "").lower()
    return next((g for nom, g in GAIN_MICRO.items() if nom in m), 1.0)

# tolere la ponctuation que Whisper glisse entre les mots ("Fin. De transmission.")
# et l'anglais que Whisper invente parfois sur un morceau court ("Find the transmission")
# et les mots que Whisper met a la place de « fin » en fin de phrase (05/11 : « pas de transmission »)
FIN = re.compile(r"[\s,;:-]*\b(?:find?|fine|faim|fun|vin|pas|fait)[\s.,;:!?…-]+(?:d[eu]?|the)[\s.,'’-]*(?:la\s+)?"
                 r"transmissions?\b[\s.!?,…]*$", re.I)
# « Archi, annule » / « Archi, efface » / « Archi, oublie » (+ « le message ») a la fin = la dictee est jetee
ANNULE = re.compile(r"\b(?:arch(?:i|ie|y|is)|h?ashi|arshi)\W+(?:annule|efface|oublie)[sz]?\b(?:\W+(?:le|ce)\W+message)?[\s.!?,…]*$", re.I)
EXPIRATION = int(os.environ.get("ECOUTE_EXPIRATION", "180"))  # dictee jetee si rien n'est ajoute pendant 3 min
FIN_SEULE = re.compile(r"^\W*(?:[\w'-]+\W+){0,4}transmissions?\W*$")  # 5 mots au plus, finit par transmission
INTERJECTION = re.compile(r"^\W*(?:ah+|euh+|heu+|hum+|hm+|oh+|bah|ben|hein|ok|okay|merci)\W*$")
ANNULE_COLLE = re.compile(r"(?:arch(?:i|ie|y|is)|h?ashi|arshi)(?:a?n+ul+e?|ef+ace?|oubli?e?)[sz]?(?:lemessage|cemessage)?$")
FANTOMES = ("amara.org", "sous-titres realises", "sous-titrage", "merci d'avoir regarde", "abonnez-vous",
            "sous titres", "merci de votre attention", "[musique]", "(musique)")


def dire(evt):
    ligne = json.dumps(evt, ensure_ascii=False)
    sys.stdout.write(ligne + "\n")
    sys.stdout.flush()
    if "etat" not in evt:  # journal local (dossier temporaire) pour comprendre une transcription ratee
        try:
            with open(os.path.join(DOSSIER, "ecoute_journal.txt"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%d/%m %H:%M:%S ") + ligne + "\n")
        except Exception:
            pass


def plat(t):
    return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()


def nettoyer_morceau(t):
    t = " ".join(t.split())
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|\*[^*]{1,60}\*", " ", t).strip()  # [BLANK_AUDIO], (rires), *grognement de douleur* (05/11)...
    p = plat(t)
    if not p.strip(" .,!?-") or any(f in p for f in FANTOMES):
        return ""
    return " ".join(t.split())


def analyser(dictee):
    """-> ("message", texte) si la dictee finit par 'fin de transmission', ("annule", "") si 'Archi, annule',
    sinon (None, dictee)."""
    # Whisper deforme "annule" ("Archi a nulle", "Archie annulle") : on compare sans espaces ni ponctuation
    if ANNULE.search(plat(dictee)) or ANNULE_COLLE.search(re.sub(r"[^a-z]", "", plat(dictee))):
        return "annule", ""
    m = FIN.search(dictee)
    if m:
        texte = dictee[:m.start()].strip(" ,;:-")
        # « "Archi" ok », « Archie, ... », et « Archi » dit seul puis mal entendu (« A chier. », « Ashi, », « Ah, si ! »)
        # -> « Archi, ... » (sinon le panneau rajoute un 2e « Archi, »)
        return "message", re.sub(r"""^[\s"'«»“”]*(?:arch(?:i|ie|y|is)|a\s?chi(?:er|e)?|ashi|arshi|ah,?\s?si)\b[\s"'«»“”,.:!-]*""",
                                 "Archi, ", texte, flags=re.I).strip()
    return None, dictee


CONTEXTE_DEPART = "Archi, "  # Whisper connait le nom d'Archi des le premier morceau


def transcrire(samples_bytes, contexte=""):
    os.makedirs(DOSSIER, exist_ok=True)
    chemin = os.path.join(DOSSIER, "morceau.wav")
    with wave.open(chemin, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAUX)
        w.writeframes(samples_bytes)
    # le debut de la dictee sert de contexte : un morceau court (« Archi, ») est mieux compris dans sa phrase
    invite = ["--prompt", (contexte or CONTEXTE_DEPART)[-200:]] if os.environ.get("ECOUTE_INVITE", "0") == "1" else []
    # 05/11 16 h 20 : morceau court (« fin de transmission », « Rappelle-moi ») -> modele small, ~1 s au lieu de ~2 s
    # (mesure sur les vrais morceaux de J, meme texte). Les longs gardent medium (plus juste).
    duree = len(samples_bytes) / (TAUX * 2)
    modele = MODELE_COURT if (MODELE_COURT and os.path.exists(MODELE_COURT) and duree <= COURT_MAX) else MODELE
    args = ["-m", modele, "-l", "fr", "-f", chemin, "-nt"] + reglages_rapides(len(samples_bytes)) + invite
    r = subprocess.run([WHISPER] + args, capture_output=True, timeout=180, creationflags=SANS_FENETRE)
    if WHISPER != WHISPER_CPU and (r.returncode != 0 or not r.stdout.strip()) and os.path.exists(WHISPER_CPU):
        dire({"secours": "carte graphique en echec, Whisper sur le processeur"})  # repli automatique
        r = subprocess.run([WHISPER_CPU] + args, capture_output=True, timeout=180, creationflags=SANS_FENETRE)
    return nettoyer_morceau(r.stdout.decode("utf-8", "replace"))


def garder_morceau(samples_bytes, texte, n=12):
    """Garde les 12 derniers morceaux entendus (dossier temporaire, sur le PC seulement) pour regler l'oreille :
    morceaux\\HHMMSS_<texte>.wav"""
    try:
        d = os.path.join(DOSSIER, "morceaux")
        os.makedirs(d, exist_ok=True)
        nom = time.strftime("%H%M%S_") + (re.sub(r"[^a-z0-9]+", "_", plat(texte))[:30].strip("_") or "SANS_PAROLE") + ".wav"
        with wave.open(os.path.join(d, nom), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TAUX)
            w.writeframes(samples_bytes)
        for vieux in sorted(os.listdir(d))[:-n]:
            os.remove(os.path.join(d, vieux))
    except Exception:
        pass


# ---------- le claquement de fin (05/11) ----------
# Mesure sur le son de J (3 essais) : ~30 ms, spectre de souffle (platitude 0,67-0,69), centre vers 4 kHz,
# pic 22 000-30 000. Sa voix : 150 ms et plus, centre vers 1,2 kHz, platitude 0,07-0,10.
ATTENTE_COUP = 0.6  # s apres le dernier claquement (deja ~0,36 s de calme) : un 2e coup vient-il ?


def compter_coups(trames, plancher):
    """Nombre de claquements dans un son bref ; 0 si un des sons forts ressemble a de la voix ou a un choc sourd."""
    import numpy as np
    x = np.frombuffer(b"".join(trames), dtype=np.int16).astype(np.float32)
    tr = x[: len(x) // TRAME * TRAME].reshape(-1, TRAME)
    if not len(tr):
        return 0
    seuil = max(plancher * 12, 4000)
    fort = np.abs(tr).max(1) > seuil
    n, i = 0, 0
    while i < len(fort):
        if not fort[i]:
            i += 1
            continue
        j = i
        while j < len(fort) and fort[j]:
            j += 1
        if j - i > 2:          # plus de 60 ms de son fort : pas un claquement
            return 0
        seg = tr[i:j].reshape(-1)
        sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) + 1e-9
        fr = np.fft.rfftfreq(len(seg), 1 / TAUX)
        platitude = float(np.exp(np.mean(np.log(sp))) / np.mean(sp))
        centre = float((fr * sp).sum() / sp.sum())
        # 05/11 16 h 40 : platitude 0,45 -> 0,25 (claquement de doigts de J dans les lunettes : 0,30 rejete a tort ;
        # sa voix reste exclue par le centre < 2 500 Hz et le pic < 12 000)
        if platitude < 0.25 or centre < 2500 or np.abs(seg).max() < 12000:
            return 0
        n += 1
        i = j
    return n


def reglages_rapides(nb_octets):
    """Whisper encode toujours une fenetre de 30 s : on la reduit a la duree du morceau (+ marge).
    Comparatif du 05/11 sur le meme enregistrement : fenetre 10 s = rapide mais mots rates ("pire gage") ;
    fenetre 20 s (1000) = texte exact et ~1,2 s gagnees par rapport a 30 s. Contexte (--prompt) coupe : il fait
    sauter "Archi,". 16 coeurs."""
    duree = nb_octets / (TAUX * 2)
    ctx = max(int(os.environ.get("ECOUTE_AC_MIN", "1000")), min(1500, int((duree + 2.0) * 50) + 64))  # 1500 = 30 s
    if os.environ.get("ECOUTE_FENETRE_COURTE", "1") != "1":
        ctx = 1500
    return ["-t", "16", "-ac", str(ctx)]  # recherche par faisceau gardee (glouton = plus de mots rates)


def processus_vivant(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


# 05/11 DOUBLE FLUX : J peut parler pendant qu'Archi parle. Mesure : la voix d'Archi (barre de son) arrive
# dans le micro des lunettes a RMS <= 95 (pic 370) ; celle de J a 1 500-6 000. Au-dessus de ce seuil, tenu
# comme un debut de voix, Archi se tait et on enregistre.
PAROLE_PAR_DESSUS = int(os.environ.get("ECOUTE_PAR_DESSUS", "600"))  # 0 = ancien comportement (micro sourd quand Archi parle)
# 06/11 : micros posés près des haut-parleurs (webcam) : ils entendent la voix d'Archi aussi fort
# que J -> Archi se coupait tout seul des le debut de sa phrase. Pour eux, pas de « parler par-dessus » (0).
PAR_DESSUS_MICRO = {}   # micro pose pres des haut-parleurs : {"bout du nom": 0} (ne pas couper Archi)


def par_dessus_pour(micro):
    if "ECOUTE_PAR_DESSUS" in os.environ:
        return PAROLE_PAR_DESSUS
    m = (micro or "").lower()
    return next((s for nom, s in PAR_DESSUS_MICRO.items() if nom in m), PAROLE_PAR_DESSUS)


def couper_archi():
    """Fait taire Archi tout de suite (comme « python dire.py stop ») ; ne tue jamais le processus parent (tests)."""
    try:
        pid = int(open(PID_PAROLE).read().strip())
    except Exception:
        return
    try:
        os.remove(PID_PAROLE)
    except Exception:
        pass
    if pid not in (os.getpid(), os.getppid()):
        threading.Thread(target=lambda: subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                                                        timeout=10, creationflags=SANS_FENETRE), daemon=True).start()


def archi_parle():
    try:
        return processus_vivant(int(open(PID_PAROLE).read().strip()))
    except Exception:
        return False


def stop():
    try:
        pid = int(open(PID).read().strip())
        if pid != os.getpid() and processus_vivant(pid):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10,
                           creationflags=SANS_FENETRE)
    except Exception:
        pass
    try:
        os.remove(PID)
    except Exception:
        pass


def liste():
    r = subprocess.run([FFMPEG, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                       capture_output=True, timeout=20, creationflags=SANS_FENETRE)
    sortie = r.stderr.decode("utf-8", "replace")
    return re.findall(r'"([^"]+)"\s*\(audio\)', sortie)


class Dictee:
    """La dictee en cours : morceaux transcrits dans l'ordre, decision de fin."""

    def __init__(self):
        self.texte = ""
        self.maj = time.time()
        self.verrou = threading.Lock()

    def perimee(self, maintenant=None):
        """Dictee laissee en plan (conversation de fond, tele...) : rien d'ajoute depuis EXPIRATION secondes."""
        return bool(self.texte) and (maintenant or time.time()) - self.maj > EXPIRATION

    def ajouter(self, morceau):
        with self.verrou:
            if not morceau:
                return None, self.texte
            self.maj = time.time()
            # un « Ah… », « Euh » tout seul en debut de dictee (bruit, fin de la voix d'Archi) : ignore
            if not self.texte and INTERJECTION.match(plat(morceau)):
                return None, self.texte
            # « fin de transmission » dit seul : Whisper l'entend mal sur un morceau court (« Find a transmission »,
            # « En trouver une transmission ») mais « transmission » sort toujours. Petit morceau qui finit par
            # « transmission » = fin du message (le morceau entier est retire).
            if FIN_SEULE.match(plat(morceau)):
                t, self.texte = self.texte, ""
                return ("message", analyser(t + " Fin de transmission")[1]) if t else ("annule", "")
            self.texte = (self.texte + " " + morceau).strip()
            quoi, reste = analyser(self.texte)
            if quoi:
                self.texte = ""
            return quoi, reste

    def vider(self):
        with self.verrou:
            t, self.texte = self.texte, ""
            return t


def ecouter(micro):
    import numpy as np
    seuil_dessus = par_dessus_pour(micro)
    os.makedirs(DOSSIER, exist_ok=True)
    stop()
    with open(PID, "w") as f:
        f.write(str(os.getpid()))
    for d in (DRAPEAU_ENVOYER, DRAPEAU_ANNULER):
        try:
            os.remove(d)
        except Exception:
            pass

    source = os.environ.get("ECOUTE_SOURCE")  # tests : un fichier son joue en temps reel a la place du micro
    entree = ["-re", "-i", source] if source else ["-f", "dshow", "-audio_buffer_size", "50", "-i", "audio=" + micro]
    ff = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error"] + entree +
                          (["-af", f"volume={gain_pour(micro)}"] if gain_pour(micro) != 1.0 else []) +
                          ["-ac", "1", "-ar", str(TAUX), "-f", "s16le", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=SANS_FENETRE)
    dictee = Dictee()
    file_morceaux = queue.Queue()
    en_cours = [0]  # morceaux pas encore transcrits
    en_pause = [False]  # 05/11 : un claquement de doigts met l'ecoute en pause, un autre la relance

    def transcripteur():
        while True:
            morceau = file_morceaux.get()
            if morceau is None:
                return
            dire({"etat": "transcrit"})
            try:
                texte = transcrire(morceau, dictee.texte)
            except Exception as e:
                texte = ""
                dire({"erreur": "Whisper : " + str(e)[:150]})
            garder_morceau(morceau, texte)
            en_cours[0] -= 1
            if not texte:
                dire({"bruit": round(len(morceau) / (TAUX * 2), 2)})  # un son sans parole (claquement, sifflet...)
            quoi, reste = dictee.ajouter(texte)
            if quoi == "message":
                if reste:
                    dire({"message": reste})
                else:
                    dire({"annule": True})
            elif quoi == "annule":
                dire({"annule": True})
            elif texte:
                dire({"partiel": reste})
            dire({"etat": "pause" if en_pause[0] else "ecoute"})

    threading.Thread(target=transcripteur, daemon=True).start()

    def drapeaux():
        while True:
            time.sleep(0.3)
            if en_cours[0] == 0 and dictee.perimee():
                dictee.vider()
                dire({"annule": True, "raison": "dictee oubliee (rien depuis 3 min)"})
            if os.path.exists(DRAPEAU_ANNULER):
                try:
                    os.remove(DRAPEAU_ANNULER)
                except Exception:
                    pass
                dictee.vider()
                dire({"annule": True})
            if os.path.exists(DRAPEAU_ENVOYER):
                try:
                    os.remove(DRAPEAU_ENVOYER)
                except Exception:
                    pass
                t0 = time.time()
                while en_cours[0] > 0 and time.time() - t0 < 60:
                    time.sleep(0.2)
                t = dictee.vider().strip()
                # comme si « fin de transmission » avait ete dit : memes nettoyages (« Archie » -> « Archi, »...)
                quoi, reste = analyser(t + " Fin de transmission") if t else (None, "")
                if quoi != "message" or not reste:
                    dire({"annule": True})
                else:
                    dire({"message": reste})

    threading.Thread(target=drapeaux, daemon=True).start()

    dire({"etat": "ecoute", "micro": micro})
    plancher = 120.0
    historique = []     # ~360 ms d'audio brut avant un son bref
    coups = []          # heures des derniers claquements reconnus
    bref = None         # son bref en cours d'observation
    avant = []          # pre-roll
    fenetre = []        # voix / pas voix sur les 8 dernieres trames
    morceau = None
    silence = 0
    muet_jusqua = 0.0
    fen_parle, avant_parle = [], []  # double flux : voix forte de J pendant qu'Archi parle
    taille = TRAME * 2
    while True:
        brut = ff.stdout.read(taille)
        if not brut or len(brut) < taille:
            if source:   # fin du fichier de test : on laisse Whisper finir
                t0 = time.time()
                while en_cours[0] > 0 and time.time() - t0 < 120:
                    time.sleep(0.2)
                time.sleep(0.5)
                dire({"etat": "fin_source"})
                break
            try:
                ff.wait(timeout=3)
            except Exception:
                pass
            err = ff.stderr.read().decode("utf-8", "replace").strip()
            dire({"erreur": f"micro introuvable ou coupe ({micro}, code {ff.poll()}, {len(brut)} octets) : "
                            + (err.splitlines()[-1] if err else "pas de message de ffmpeg")[:200]})
            break
        # 05/11 : les sons brefs (claquement de doigts) sont ecoutes AVANT le test « Archi parle » : un claquement
        # pendant qu'Archi parle met en pause et le fait taire (avant, il etait ignore).
        x = np.frombuffer(brut, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(x * x)))
        pic_trame = float(np.max(np.abs(x)))
        # sons brefs (claquement, clic...) : trop courts pour l'enregistrement de la voix ; notes a part pour etude
        historique = (historique + [brut])[-12:]
        if bref is None:
            if pic_trame > max(plancher * 12, 4000):
                bref = {"trames": list(historique), "pic": pic_trame, "rms": rms, "fort": 1, "calme": 0}
        else:
            bref["trames"].append(brut)
            bref["pic"] = max(bref["pic"], pic_trame)
            bref["rms"] = max(bref["rms"], rms)
            if pic_trame > max(plancher * 12, 4000):
                bref["fort"] += 1
                bref["calme"] = 0
            else:
                bref["calme"] += 1
            if bref["calme"] >= 12 or len(bref["trames"]) > 80:
                n = compter_coups(bref["trames"], plancher)
                dire({"son_bref": {"pic": round(bref["pic"]), "rms": round(bref["rms"]), "trames_fortes": bref["fort"],
                                   "plancher": round(plancher), "coups": n}})
                garder_morceau(b"".join(bref["trames"]), "SON_BREF")
                bref = None
                maintenant = time.time()
                coups = ([t for t in coups if maintenant - t < 1.5] + [maintenant] * n) if n else []
        # SIGNAL (choix de J, 05/11 16 h 45) : un claquement de doigts = PAUSE (rien n'est enregistre ni
        # envoye, pour parler a quelqu'un) ; un autre = REPRISE. Des coups rapproches (< 1,5 s) comptent pour un.
        # L'envoi se fait par « fin de transmission ». La dictee deja retranscrite est gardee pendant la pause.
        if coups and bref is None and time.time() - coups[-1] > ATTENTE_COUP:
            nb, coups = len(coups), []
            en_pause[0] = not en_pause[0]
            if en_pause[0] and archi_parle():  # 05/11 : claquement pendant qu'Archi parle = il se tait aussi
                couper_archi()
                dire({"coupe_archi": True})
            morceau, avant, fenetre, silence = None, [], [], 0  # la phrase en cours au moment du claquement est jetee
            dire({"pause": en_pause[0], "coups": nb})
            dire({"etat": "pause" if en_pause[0] else "ecoute"})
        if archi_parle():
            # Archi parle : sa propre voix (barre de son) arrive tres faible dans le micro des lunettes ; on l'ignore.
            # Mais si J parle par-dessus (voix forte, tenue), Archi se tait et on l'enregistre (double flux).
            if seuil_dessus and not en_pause[0]:
                xr = np.frombuffer(brut, dtype=np.int16).astype(np.float32)
                fen_parle = (fen_parle + [float(np.sqrt(np.mean(xr * xr))) > seuil_dessus])[-DEBUT[1]:]
                avant_parle = (avant_parle + [brut])[-PREROLL:]
                if sum(fen_parle) >= DEBUT[0]:
                    couper_archi()
                    dire({"coupe_archi": True})
                    morceau, avant, fenetre, silence = list(avant_parle), [], [True] * DEBUT[1], 0
                    fen_parle, avant_parle, muet_jusqua = [], [], 0.0
                    dire({"etat": "enregistre"})
                    continue
            if time.time() > muet_jusqua:
                dire({"etat": "archi_parle"})
            muet_jusqua = time.time() + 0.8
            morceau, avant, fenetre, silence = None, [], [], 0
            continue
        fen_parle, avant_parle = [], []
        if time.time() < muet_jusqua:
            continue
        if en_pause[0]:
            continue
        voix = rms > max(plancher * 3.0, SEUIL_MIN)
        if not voix and morceau is None:
            plancher = plancher * 0.95 + rms * 0.05
        fenetre = (fenetre + [voix])[-DEBUT[1]:]
        if morceau is None:
            avant = (avant + [brut])[-PREROLL:]
            if sum(fenetre) >= DEBUT[0]:
                morceau = list(avant)
                silence = 0
                dire({"etat": "enregistre"})
            continue
        morceau.append(brut)
        silence = 0 if voix else silence + 1
        if silence >= SILENCE_FIN or len(morceau) >= MORCEAU_MAX:
            if len(morceau) - silence >= 12:   # au moins ~0,35 s de voix
                en_cours[0] += 1
                file_morceaux.put(b"".join(morceau))
            else:
                dire({"etat": "ecoute"})
            morceau, avant, fenetre, silence = None, [], [], 0
    try:
        ff.kill()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    action = sys.argv[1] if len(sys.argv) > 1 else "ecouter"
    if action == "ecouter":
        micro = MICRO
        if "--micro" in sys.argv:
            micro = sys.argv[sys.argv.index("--micro") + 1]
        try:
            if not micro:   # aucun micro regle : le premier que Windows connait
                micro = (liste() or [""])[0]
                if not micro:
                    raise RuntimeError("aucun micro trouve (python ecoute.py liste)")
            ecouter(micro)
        except Exception as e:
            dire({"erreur": str(e)[:200]})
        finally:
            try:
                if open(PID).read().strip() == str(os.getpid()):
                    os.remove(PID)
            except Exception:
                pass
    elif action == "liste":
        print(json.dumps({"ok": True, "micros": liste()}, ensure_ascii=False))
    elif action == "stop":
        stop()
        print(json.dumps({"ok": True}))
    elif action in ("envoyer", "annuler"):
        os.makedirs(DOSSIER, exist_ok=True)
        open(DRAPEAU_ENVOYER if action == "envoyer" else DRAPEAU_ANNULER, "w").close()
        print(json.dumps({"ok": True}))
    elif action == "essai":
        with wave.open(sys.argv[2], "rb") as w:
            texte = transcrire(w.readframes(w.getnframes()))
        print(json.dumps({"ok": True, "texte": texte, "analyse": analyser(texte)}, ensure_ascii=False))
    else:
        print(json.dumps({"ok": False, "erreur": "action inconnue : " + action}))
