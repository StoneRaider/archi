# dire.py - fait parler Archi sur le PC (panneau Archi), avec SA voix : Pocket TTS, voix Charles (port 8770).
#
#   echo texte | python dire.py lancer   -> rend la main tout de suite ; la lecture se fait dans un processus detache
#   python dire.py stop                   -> coupe la lecture en cours
#   echo texte | python dire.py essai     -> lit en direct (pour tester), affiche ce qui se passe
#
# Le texte passe d'abord par nettoyer_voix.js (heures, montants, sigles... comme sur Telegram).
# Une phrase de la meme reponse ATTEND la fin de la precedente (file d'attente, 05/11) ; « stop » (nouvelle question,
# J qui parle par-dessus) coupe la lecture ET jette tout ce qui attend. Si Pocket ne repond pas, voix Windows (SAPI) en secours.
# Ne lit et n'envoie rien d'autre : tout reste sur le PC.
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

ICI = os.path.dirname(os.path.abspath(__file__))
POCKET = os.environ.get("POCKET_URL", "http://[::1]:8770/tts")
DOSSIER = os.path.join(tempfile.gettempdir(), "archi_voix")
PID = os.path.join(DOSSIER, "lecture.pid")
COUPURE = os.path.join(DOSSIER, "coupure.txt")   # heure (ns) du dernier « stop »
FINI = os.path.join(DOSSIER, "fini.txt")         # pid de la derniere lecture finie normalement
NETTOYER = os.path.join(ICI, "nettoyer_voix.js")


def nettoyer(texte):
    try:
        r = subprocess.run(["node", NETTOYER], input=texte.encode("utf-8"), capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        propre = r.stdout.decode("utf-8", "replace").strip()
        return propre or texte
    except Exception:
        return texte


def pocket(texte):
    limite = "----archi" + uuid.uuid4().hex
    corps = (f"--{limite}\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n{texte}\r\n--{limite}--\r\n").encode("utf-8")
    req = urllib.request.Request(POCKET, data=corps, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
    with urllib.request.urlopen(req, timeout=150) as r:
        return r.read()


def decouper(texte, mini=40):
    """Coupe en phrases pour parler plus vite. Une phrase trop courte est collee a la suivante
    (moins de coupures audibles) ; la 1re reste courte pour que le premier son arrive vite."""
    import re
    morceaux = [m.strip() for m in re.findall(r"[^.!?…]+[.!?…]*", texte) if m.strip()]
    phrases = []
    for m in morceaux:
        if phrases and len(phrases) > 1 and len(phrases[-1]) < mini:
            phrases[-1] += " " + m
        elif phrases and len(phrases) == 1 and len(phrases[0]) < 12:
            phrases[0] += " " + m
        else:
            phrases.append(m)
    return phrases or [texte]


def reparer_wav(wav):
    """Pocket diffuse en continu : son en-tete annonce 2 000 000 000 octets de donnees. Windows (PlaySound)
    abandonne alors la lecture au bout d'une seconde ; on remet les vraies tailles."""
    import struct
    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        return wav
    i, b = 12, bytearray(wav)
    while i < len(b) - 8:
        cid, taille = bytes(b[i:i + 4]), struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"data":
            reste = len(b) - i - 8
            b[i + 4:i + 8] = struct.pack("<I", reste)
            b[4:8] = struct.pack("<I", len(b) - 8)
            return bytes(b)
        i += 8 + taille
    return wav


def sapi(texte):
    """voix Windows de secours (francaise si elle est installee)"""
    script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'fr*' } | Select-Object -First 1; "
              "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; $s.Speak([Console]::In.ReadToEnd())")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], input=texte.encode("utf-8"), timeout=300,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def stop():
    try:   # toutes les phrases arrivees avant cet instant et encore en attente sont jetees
        os.makedirs(DOSSIER, exist_ok=True)
        with open(COUPURE, "w") as f:
            f.write(str(time.time_ns()))
    except Exception:
        pass
    try:
        pid = int(open(PID).read().strip())
        if pid != os.getpid():
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    try:
        os.remove(PID)
    except Exception:
        pass


def encore_moi():
    """UNE SEULE VOIX (05/11, deux voix entendues en meme temps) : seule la derniere lecture lancee a le droit de parler."""
    try:
        return open(PID).read().strip() == str(os.getpid())
    except Exception:
        return False


def vivant(pid):
    """le processus existe-t-il encore ? (os.kill(pid, 0) TUE le processus sous Windows : on ne l'utilise pas)"""
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259          # STILL_ACTIVE
    except Exception:
        return False


def lire(chemin):
    try:
        return open(chemin).read().strip()
    except Exception:
        return ""


def attendre_mon_tour(ticket, limite=150):
    """FILE D'ATTENTE (05/11, J : « tu commences, ca coupe, tu reprends avec une autre formulation ») :
    une phrase de la MEME reponse attend la fin de la precedente au lieu de la couper.
    Une vraie coupure (« dire.py stop », J qui parle par-dessus via ecoute.py, nouvelle question) se voit :
    la lecture en cours disparait sans avoir signe FINI -> toutes les phrases en attente sont jetees.
    Renvoie True quand c'est a nous de parler, False si on a ete annule."""
    attente = os.path.join(DOSSIER, f"attente_{ticket}_{os.getpid()}")
    open(attente, "w").close()
    vu, debut = None, time.time()
    try:
        while time.time() - debut < limite:
            if lire(COUPURE) and int(lire(COUPURE) or 0) > ticket:
                return False                                   # coupe apres notre arrivee
            tenant = lire(PID)
            if tenant and tenant != str(os.getpid()):
                if vivant(tenant):
                    vu = tenant
                    time.sleep(0.1)
                    continue
                try:
                    os.remove(PID)                             # lecture morte sans menage
                except Exception:
                    pass
                tenant = ""
            if not tenant and vu and lire(FINI) != vu:
                return False                                   # la phrase d'avant a ete coupee : on se tait aussi
            # la place est libre : seule la plus ancienne phrase en attente la prend
            import glob
            plus_vieux = True
            for f in glob.glob(os.path.join(DOSSIER, "attente_*")):
                try:
                    _, t, p = os.path.basename(f).split("_")
                    if (int(t), int(p)) < (ticket, os.getpid()) and vivant(p):
                        plus_vieux = False
                    elif not vivant(p):
                        os.remove(f)
                except Exception:
                    pass
            if plus_vieux:
                try:
                    fd = os.open(PID, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode())
                    os.close(fd)
                    return True
                except FileExistsError:
                    pass
            time.sleep(0.05)
        stop()                                                 # bloque trop longtemps : on reprend la main
        with open(PID, "w") as f:
            f.write(str(os.getpid()))
        return True
    finally:
        try:
            os.remove(attente)
        except Exception:
            pass


def jouer(texte, bavard=False, ticket=None):
    import winsound
    os.makedirs(DOSSIER, exist_ok=True)
    ticket = ticket or time.time_ns()
    a_la_parole = [False]
    import glob  # menage : sons laisses par des lectures coupees (seulement ceux des processus morts)
    for vieux in glob.glob(os.path.join(DOSSIER, "reponse_*.wav")):
        try:
            if not vivant(os.path.basename(vieux).split("_")[1]):
                os.remove(vieux)
        except Exception:
            pass
    propre = nettoyer(texte)
    if bavard:
        print("texte nettoye :", propre)
    try:
        # PHRASE PAR PHRASE (05/11) : la 1re phrase se joue pendant que Pocket fabrique la suivante.
        # Avant : on attendait tout l'audio de la reponse avant le premier son.
        # FILE D'ATTENTE (05/11 soir) : Pocket fabrique deja le son PENDANT qu'on attend la fin de la phrase d'avant.
        import queue
        import threading
        t0 = time.time()
        phrases = decouper(propre)
        prets = queue.Queue()

        def fabriquer():
            for i, p in enumerate(phrases):
                try:
                    wav = reparer_wav(pocket(p))
                    chemin = os.path.join(DOSSIER, f"reponse_{os.getpid()}_{i}.wav")  # fichiers propres a cette lecture
                    with open(chemin, "wb") as f:
                        f.write(wav)
                    prets.put(chemin)
                except Exception as e:
                    prets.put(e)
                    return
            prets.put(None)

        threading.Thread(target=fabriquer, daemon=True).start()
        if not attendre_mon_tour(ticket):
            return "annulee"
        a_la_parole[0] = True
        premier = True
        while True:
            chemin = prets.get()
            if chemin is None:
                break
            if isinstance(chemin, Exception):
                if premier:
                    raise chemin  # rien n'a ete dit : voix Windows en secours
                break
            if bavard and premier:
                print(f"premier son apres {time.time() - t0:.1f} s ({len(phrases)} phrase(s))")
            premier = False
            if not encore_moi():  # une lecture plus recente a pris la parole : on se tait
                break
            winsound.PlaySound(chemin, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            try:
                os.remove(chemin)
            except Exception:
                pass  # NODEFAULT : jamais le « bloom » de Windows en cas d echec
        via = "pocket"
    except Exception as e:
        if bavard:
            print("Pocket injoignable, voix Windows :", e)
        if not a_la_parole[0] and not attendre_mon_tour(ticket):
            return "annulee"
        sapi(propre)
        via = "windows"
    try:
        if open(PID).read().strip() == str(os.getpid()):
            with open(FINI, "w") as f:   # « j'ai fini normalement » : la phrase suivante peut parler
                f.write(str(os.getpid()))
            os.remove(PID)
    except Exception:
        pass
    return via


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "essai"
    if action == "stop":
        stop()
        print(json.dumps({"ok": True}))
    elif action == "lancer":
        texte = sys.stdin.buffer.read().decode("utf-8", "replace").strip()
        if not texte:
            print(json.dumps({"ok": False, "erreur": "texte vide"}))
            sys.exit(0)
        os.makedirs(DOSSIER, exist_ok=True)
        fichier = os.path.join(DOSSIER, f"texte_{time.time_ns()}_{uuid.uuid4().hex[:8]}.txt")   # l'heure = le ticket
        with open(fichier, "w", encoding="utf-8") as f:
            f.write(texte)
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        exe = pyw if os.path.exists(pyw) else sys.executable
        drapeaux = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([exe, os.path.abspath(__file__), "jouer", fichier], creationflags=drapeaux, close_fds=True)
        print(json.dumps({"ok": True}))
    elif action == "jouer":
        fichier = sys.argv[2]
        texte = open(fichier, encoding="utf-8").read()
        try:
            os.remove(fichier)
        except Exception:
            pass
        try:
            ticket = int(os.path.basename(fichier).split("_")[1])
        except Exception:
            ticket = None
        jouer(texte, ticket=ticket)
    else:
        texte = sys.stdin.buffer.read().decode("utf-8", "replace").strip() or "Salut BOSS, c'est Archi. Je te parle depuis Claude."
        print(json.dumps({"ok": True, "via": jouer(texte, bavard=True)}))
