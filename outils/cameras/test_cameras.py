"""Tests hors ligne de cameras.py (aucune vraie camera : reseau et ffmpeg simules)."""
import json, os, sys, tempfile
D = tempfile.mkdtemp(prefix="cams_")
os.environ.update(ARCHI_CAMERAS=os.path.join(D, "cameras.json"), ARCHI_CAMERAS_SECRET=os.path.join(D, "secret.json"),
                  ARCHI_BASE=D)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cameras as C  # noqa: E402

ok = ko = 0


def verif(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
    else:
        ko += 1
        print("ECHEC", nom, str(detail)[:300])


def essai(action, **d):
    try:
        phrase, extra = C.ACTIONS[action](d)
        return True, phrase, extra
    except C.Erreur as e:
        return False, str(e), {}


r = essai("liste")
verif("liste vide explique", r[0] and "Aucune" in r[1], r)
verif("adresse publique refusee", not essai("ajouter", nom="x", ip="8.8.8.8")[0])
verif("localhost refuse", not essai("ajouter", nom="x", ip="127.0.0.1")[0])
verif("adresse invalide", not essai("ajouter", nom="x", ip="abc")[0])
verif("marque inconnue", not essai("ajouter", nom="x", ip="192.168.1.9", marque="bidule")[0])
verif("chemin avec identifiant refuse", not essai("ajouter", nom="x", ip="192.168.1.9", marque="generique", chemin="/a@b")[0])
r = essai("ajouter", nom="Entrée principale", ip="192.168.1.20", marque="imou")
verif("ajouter", r[0] and json.load(open(os.environ["ARCHI_CAMERAS"]))["entr_e_principale"]["marque"] == "imou", r)
essai("ajouter", nom="jardin", ip="192.168.1.21", marque="reolink")
r = essai("liste")
verif("liste 2 cameras", r[0] and "2 camera" in r[1], r)

C.port_ouvert = lambda ip, port=554, delai=0.6: False
verif("camera eteinte expliquee", "ne repond pas" in essai("photo", camera="jardin")[1])
C.port_ouvert = lambda ip, port=554, delai=0.6: True
r = essai("photo", camera="jardin")
verif("code manquant explique", not r[0] and "secret.json" in r[1], r)
verif("camera inconnue", "Je ne connais pas" in essai("photo", camera="cuisine")[1])
verif("duree verifiee avant tout", "entre 1 et 120" in essai("video", camera="jardin", duree_s=500)[1])

json.dump({"jardin": {"code": "s3cr3t+/@"}}, open(os.environ["ARCHI_CAMERAS_SECRET"], "w"))
vus = []


def faux_lancer(cmd, masque, delai):
    vus.append(cmd)
    url = [c for c in cmd if str(c).startswith("rtsp://")][0]
    if "ffprobe" in cmd[0]:
        return json.dumps({"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                                        "avg_frame_rate": "20/1"}]})
    open(cmd[-1], "wb").write(b"x")
    return ""


C.lancer = faux_lancer
C.trouver_programme = lambda n: n
r = essai("verifier", camera="jardin")
verif("verifier", r[0] and "1920" in r[1], r)
url = [c for c in vus[-1] if str(c).startswith("rtsp://")][0]
verif("chemin reolink", url.endswith(":554/h264Preview_01_main"), url)
verif("code encode dans l'url", "s3cr3t%2B%2F%40" in url, url)
r = essai("photo", camera="jard")
verif("photo (nom partiel)", r[0] and r[2]["fichier"].startswith(D), r)
verif("code jamais dans la phrase", "s3cr3t" not in r[1])

# masquage du code dans une vraie erreur ffmpeg
import importlib  # noqa: E402
C2 = importlib.reload(C)
class R:  # noqa: E701
    returncode = 1; stdout = ""; stderr = "rtsp://admin:s3cr3t@192.168.1.21 401 Unauthorized"
C2.subprocess.run = lambda *a, **k: R()
try:
    C2.lancer(["ffmpeg"], ["s3cr3t"], 5)
    verif("401 traduit", False)
except C2.Erreur as e:
    verif("401 traduit, code masque", "refuse le code" in str(e) and "s3cr3t" not in str(e), e)
print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
