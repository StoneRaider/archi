# -*- coding: utf-8 -*-
"""camera_imprimante.py - outil maison d'Archi : « montre-moi la fabrication » (imprimante Klipper/Moonraker avec camera WebRTC,
en direct, 05/11/2026).

  python camera_imprimante.py --fichier demande.json
    {"action": "montrer"}  (defaut) -> trouve l'imprimante (hotspot du PC ou box), allume sa lumiere si elle est eteinte,
                                       ouvre la video en direct dans le navigateur du PC (page locale http://127.0.0.1:8790)
    {"action": "photo"}             -> la derniere image de la video (page ouverte), affichee dans le panneau Archi ;
                                       champ "fichier" = le .jpg (Telegram peut l'envoyer)
    {"action": "etat"}              -> ou en est l'impression (sans video)
    {"action": "arreter"}           -> ferme le relais video
  python camera_imprimante.py --relais <ip_imprimante> <ip_du_pc>   (le relais lui-meme, lance en arriere-plan)

Pourquoi un relais : la camera parle WebRTC (port 8000, /call/webrtc_local). Le navigateur cache l'adresse du PC
(nom en .local) : la camera ne sait pas ou envoyer l'image. La page remplace ce nom par la vraie adresse du PC
sur le meme reseau que l'imprimante, et le relais transmet la demande a la camera (pas de blocage entre sites).
Tout reste sur le reseau local. Lecture seule, sauf la lumiere (SET_PIN LED), jamais d'ordre d'impression.
Repond UNE ligne JSON {"ok", "phrase_pour_utilisateur", ...}.
"""
import base64
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ICI = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
ETAT = os.path.join(ICI, "etat.json")
PHOTO = os.path.join(BASE, "camera", "fabrication_derniere.jpg")
AFFICHER = os.path.join(BASE, "pc", "affichage", "afficher.py")
PORT = 8790
# reseaux ou chercher l'imprimante (3 premiers nombres), ex. "192.168.137,192.168.1" ; ARCHI_IMPRIMANTE_IP pour la donner directement
RESEAUX = [r.strip() for r in os.environ.get("ARCHI_IMPRIMANTE_RESEAUX", "192.168.137,192.168.1").split(",") if r.strip()]
INACTIF_S = 30 * 60
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def sortir(d):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def lire_etat():
    try:
        return json.load(open(ETAT, encoding="utf-8"))
    except Exception:
        return {}


def ecrire_etat(**d):
    e = lire_etat()
    e.update(d)
    with open(ETAT, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False)


def port_ouvert(ip, port, delai=0.4):
    try:
        with socket.create_connection((ip, port), timeout=delai):
            return True
    except Exception:
        return False


def moonraker(ip, chemin, timeout=6):
    with urllib.request.urlopen(f"http://{ip}:7125{chemin}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def est_imprimante(ip):
    try:
        # toute imprimante Klipper/Moonraker ; ARCHI_IMPRIMANTE_NOM pour n'accepter que celle dont le nom commence ainsi
        nom = moonraker(ip, "/printer/info", 3)["result"].get("hostname", "").lower()
        return nom.startswith(os.environ.get("ARCHI_IMPRIMANTE_NOM", "").lower())
    except Exception:
        return False


def trouver_imprimante():
    """la derniere adresse connue, sinon on cherche le port 7125 sur le hotspot puis sur la box"""
    connue = os.environ.get("ARCHI_IMPRIMANTE_IP") or lire_etat().get("ip")
    if connue and port_ouvert(connue, 7125, 1.5) and est_imprimante(connue):
        return connue
    for reseau in RESEAUX:
        ips = [f"{reseau}.{i}" for i in range(2, 255)]
        with ThreadPoolExecutor(64) as ex:
            ouverts = [ip for ip, ok in zip(ips, ex.map(lambda ip: port_ouvert(ip, 7125), ips)) if ok]
        for ip in ouverts:
            if est_imprimante(ip):
                ecrire_etat(ip=ip)
                return ip
    return None


def ip_du_pc_vers(ip):
    """l'adresse du PC sur le meme reseau que l'imprimante (ex. 192.168.137.1 sur le hotspot)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((ip, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def etat_impression(ip):
    r = moonraker(ip, "/printer/objects/query?print_stats&display_status&output_pin%20LED")["result"]["status"]
    p = r["print_stats"]
    return {"etat": p.get("state"), "fichier": p.get("filename"), "progres": round((r["display_status"].get("progress") or 0) * 100),
            "minutes": round((p.get("print_duration") or 0) / 60), "lumiere": (r.get("output_pin LED") or {}).get("value")}


def phrase_etat(e):
    if e["etat"] == "printing":
        import re
        nom = os.path.splitext(e["fichier"] or "la pièce")[0]
        nom = re.sub(r"(?i)_(pla|petg|abs|asa|tpu|pc|pa)\d*", "", nom).replace("_", " ").strip() or "la pièce"
        return f"elle imprime {nom}, à {e['progres']} %, depuis {e['minutes']} minutes"
    return {"standby": "elle attend, rien en cours", "complete": "l'impression est terminée", "paused": "l'impression est en pause",
            "cancelled": "la dernière impression a été annulée", "error": "elle signale une erreur"}.get(e["etat"], f"état : {e['etat']}")


# ---------------------------------------------------------------- le relais (page + passage vers la camera)
PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Fabrication en direct</title>
<style>html,body{margin:0;height:100%;background:#0B1410;color:#E6F2EC;font:15px system-ui,sans-serif;overflow:hidden}
video{width:100%;height:100%;object-fit:contain;background:#000}
#bandeau{position:fixed;left:12px;top:10px;padding:6px 12px;border-radius:10px;background:#0B1410cc;border:1px solid #1E6B4C}
#bandeau b{color:#3DDC97}</style></head><body>
<video id="v" autoplay muted playsinline></video><div id="bandeau"><b>ARCHI</b> · fabrication en direct · <span id="info">connexion…</span></div>
<script>
const IP_PC = "__IP_PC__";
const v = document.getElementById('v'), info = document.getElementById('info');
let pc;
async function connecter(){
  try{ if(pc) pc.close(); }catch(e){}
  pc = new RTCPeerConnection({iceServers:[]});
  pc.addTransceiver('video',{direction:'recvonly'});
  pc.ontrack = e => { v.srcObject = e.streams[0]; };
  pc.onconnectionstatechange = () => { if(['failed','disconnected'].includes(pc.connectionState)) setTimeout(connecter, 3000); };
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise(r => { pc.onicegatheringstatechange = () => { if(pc.iceGatheringState==='complete') r(); }; setTimeout(r, 2500); });
  const sdp = pc.localDescription.sdp.replace(/[0-9a-f-]{36}\\.local/g, IP_PC);
  const rep = await fetch('/offre', {method:'POST', body: btoa(JSON.stringify({type:'offer', sdp}))});
  const txt = await rep.text(); let ans; try { ans = JSON.parse(atob(txt)); } catch(e) { ans = JSON.parse(txt); }
  await pc.setRemoteDescription(ans);
}
async function photo(){
  if(!v.videoWidth) return;
  const c = document.createElement('canvas'); c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext('2d').drawImage(v, 0, 0);
  const b = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.85));
  fetch('/photo', {method:'POST', body:b});
}
async function etat(){
  try{ const e = await (await fetch('/etat')).json(); info.textContent = e.texte; }catch(e){ info.textContent = 'imprimante injoignable'; }
}
connecter(); etat(); setInterval(etat, 15000); setInterval(photo, 10000); setTimeout(photo, 3000);
</script></body></html>"""


def relais(ip, ip_pc):
    vu = [time.time()]

    class Gestion(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def repondre(self, code, corps, type_="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", type_)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corps)

        def do_GET(self):
            vu[0] = time.time()
            if self.path in ("/", "/index.html"):
                self.repondre(200, PAGE.replace("__IP_PC__", ip_pc).encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/etat":
                try:
                    texte = phrase_etat(etat_impression(ip))
                except Exception:
                    texte = "imprimante injoignable"
                self.repondre(200, json.dumps({"texte": texte}, ensure_ascii=False).encode("utf-8"), "application/json")
            elif self.path == "/vivant":
                self.repondre(200, b"oui")
            else:
                self.repondre(404, b"")

        def do_POST(self):
            # seulement la page servie par ce relais : une autre page web ne peut ni envoyer d'offre ni ecraser la photo
            origine = self.headers.get("Origin") or ""
            if origine and origine not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
                return self.repondre(403, b"origine refusee")
            vu[0] = time.time()
            corps = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path == "/offre":
                try:
                    req = urllib.request.Request(f"http://{ip}:8000/call/webrtc_local", data=corps, method="POST",
                                                 headers={"Content-Type": "plain/text"})
                    with urllib.request.urlopen(req, timeout=10) as r:
                        self.repondre(200, r.read())
                except Exception as e:
                    self.repondre(502, str(e).encode("utf-8"))
            elif self.path == "/photo" and corps[:2] == b"\xff\xd8":
                os.makedirs(os.path.dirname(PHOTO), exist_ok=True)
                tmp = PHOTO + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(corps)
                os.replace(tmp, PHOTO)
                self.repondre(200, b"ok")
            else:
                self.repondre(404, b"")

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Gestion)

    def veilleur():  # le relais s'arrete tout seul apres 30 min sans visite
        while time.time() - vu[0] < INACTIF_S:
            time.sleep(20)
        srv.shutdown()

    threading.Thread(target=veilleur, daemon=True).start()
    ecrire_etat(relais_pid=os.getpid(), ip=ip, ip_pc=ip_pc)
    srv.serve_forever()


def relais_vivant():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/vivant", timeout=1.5) as r:
            return r.read() == b"oui"
    except Exception:
        return False


def lancer_relais(ip, ip_pc):
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    drapeaux = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | SANS_FENETRE
    subprocess.Popen([exe, os.path.abspath(__file__), "--relais", ip, ip_pc], creationflags=drapeaux, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.3)
        if relais_vivant():
            return True
    return False


def arreter_relais():
    pid = lire_etat().get("relais_pid")
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=SANS_FENETRE)
    ecrire_etat(relais_pid=None)


# ---------------------------------------------------------------- actions
def act_montrer(d):
    ip = trouver_imprimante()
    if not ip:
        sortir({"ok": False, "phrase_pour_utilisateur": "Je ne trouve pas l'imprimante sur le réseau (ni sur le hotspot du PC, ni sur la box) : elle est allumée ?"})
    e = etat_impression(ip)
    lumiere = ""
    if not e.get("lumiere"):
        try:
            req = urllib.request.Request(f"http://{ip}:7125/printer/gcode/script?script=SET_PIN%20PIN%3DLED%20VALUE%3D1", method="POST")
            urllib.request.urlopen(req, timeout=10).read()
            lumiere = " J'ai allumé sa lumière."
        except Exception:
            lumiere = " Je n'ai pas pu allumer sa lumière."
    ip_pc = ip_du_pc_vers(ip)
    if lire_etat().get("ip_pc") != ip_pc or lire_etat().get("ip") != ip:
        arreter_relais()
    if not relais_vivant() and not lancer_relais(ip, ip_pc):
        sortir({"ok": False, "phrase_pour_utilisateur": "Le relais vidéo ne démarre pas sur le PC (port 8790 déjà pris ?)."})
    url = f"http://127.0.0.1:{PORT}/"
    if d.get("ouvrir", True) not in (False, "non", "false") and os.environ.get("CAMERA_SANS_NAVIGATEUR") != "1":
        webbrowser.open(url)
    sortir({"ok": True, "url": url, "imprimante": ip, "impression": e,
            "phrase_pour_utilisateur": f"Voilà la fabrication en direct dans le navigateur : {phrase_etat(e)}.{lumiere}"})


def act_photo(d):
    if not os.path.exists(PHOTO) or time.time() - os.path.getmtime(PHOTO) > 90:
        if not relais_vivant():
            sortir({"ok": False, "phrase_pour_utilisateur": "La vidéo n'est pas ouverte : dis « montre-moi la fabrication » d'abord, puis redemande la photo."})
        for _ in range(25):
            time.sleep(1)
            if os.path.exists(PHOTO) and time.time() - os.path.getmtime(PHOTO) < 30:
                break
        else:
            sortir({"ok": False, "phrase_pour_utilisateur": "La vidéo est ouverte mais aucune image n'arrive encore : réessaie dans quelques secondes."})
    try:
        subprocess.run([sys.executable, AFFICHER, "image", PHOTO, "--titre", "Fabrication", "--legende", time.strftime("%H:%M")],
                       capture_output=True, timeout=60, creationflags=SANS_FENETRE)
    except Exception:
        pass
    sortir({"ok": True, "fichier": PHOTO, "phrase_pour_utilisateur": "Voilà une image de la fabrication, à l'instant."})


def act_etat(d):
    ip = trouver_imprimante()
    if not ip:
        sortir({"ok": False, "phrase_pour_utilisateur": "Je ne trouve pas l'imprimante sur le réseau : elle est allumée ?"})
    e = etat_impression(ip)
    sortir({"ok": True, "impression": e, "phrase_pour_utilisateur": phrase_etat(e)[0].upper() + phrase_etat(e)[1:] + "."})


def main():
    a = sys.argv[1:]
    if a[:1] == ["--relais"]:
        relais(a[1], a[2])
        return
    d = {}
    if "--fichier" in a:
        d = json.load(open(a[a.index("--fichier") + 1], encoding="utf-8-sig"))
    elif a:
        try:
            d = json.loads(a[0])
        except Exception:
            d = {"action": a[0]}
    if isinstance(d.get("parametres"), dict):
        d = {**d, **d["parametres"]}
    action = str(d.get("action") or "montrer").strip().lower()
    action = {"voir": "montrer", "video": "montrer", "camera": "montrer", "direct": "montrer", "image": "photo",
              "capture": "photo", "stop": "arreter", "fermer": "arreter", "ou_en_est": "etat"}.get(action, action)
    if action == "arreter":
        arreter_relais()
        sortir({"ok": True, "phrase_pour_utilisateur": "J'ai fermé la vidéo de l'imprimante."})
    f = {"montrer": act_montrer, "photo": act_photo, "etat": act_etat}.get(action)
    if not f:
        sortir({"ok": False, "phrase_pour_utilisateur": "Action inconnue : montrer, photo, etat ou arreter."})
    f(d)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        sortir({"ok": False, "phrase_pour_utilisateur": "La caméra de l'imprimante a eu un souci.", "erreur": repr(e)[:200]})
