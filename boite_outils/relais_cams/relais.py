# -*- coding: utf-8 -*-
"""relais.py - petit relais d'images pour le globe (gods-eye-view).
Certaines webcams PUBLIQUES et OFFICIELLES (routes, stations, meteo) n'ont pas d'adresse d'image fixe, ou refusent
d'etre affichees depuis une autre page. Ce relais donne une adresse fixe, par ex. http://127.0.0.1:4174/cam/col_1.jpg,
va chercher la derniere image chez la source et la renvoie. Cache 60 s. Lecture seule, rien d'autre.

Sources : sources.json (meme dossier, ou RELAIS_SOURCES), une entree par camera :
  {"col_1": {"image": "https://exemple.gouv.fr/webcam/col_1.jpg"},
   "station": {"page": "https://exemple.fr/webcam.html", "motif": "src=\\"(/img/cam_[0-9]+\\\\.jpg)\\""}}
  - "image" : l'adresse de l'image (fixe) ;
  - "page" + "motif" : la page officielle qui contient le lien de la derniere image, et l'expression qui le trouve.
REGLE : uniquement des cameras publiees officiellement par leur proprietaire (collectivite, route, meteo).
Jamais une camera privee, jamais pour suivre une personne.
"""
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UA = {"User-Agent": "Mozilla/5.0 (relais de webcams publiques, usage prive)"}
CACHE = {}          # chemin -> (expire, content_type, bytes)
CACHE_S = 60
ERREUR_S = 20
FICHIER = os.environ.get("RELAIS_SOURCES") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")
NOM = re.compile(r"^/cam/([a-z0-9_\-]{1,40})\.jpe?g$")


def sources():
    try:
        with open(FICHIER, encoding="utf-8") as f:
            s = json.load(f)
        return {k: v for k, v in s.items() if isinstance(v, dict)}
    except Exception:
        return {}


def publique(url):
    """http(s), sans identifiant, et toutes les IP du nom publiques (le relais partage le reseau du globe)"""
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or "@" in u.netloc:
        return False
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    for i in infos:
        ip = ipaddress.ip_address(i[4][0].split("%")[0])
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if not ip.is_global:
            return False
    return bool(infos)


class _Redir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not publique(newurl):
            raise ValueError("redirection vers une adresse interdite")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OUVREUR = urllib.request.build_opener(_Redir)


def lire(url, timeout=10):
    if not publique(url):
        raise ValueError("adresse non publique refusee")
    with _OUVREUR.open(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.headers.get("Content-Type", ""), r.read(5_000_000)


def derniere_image(src):
    if src.get("image"):
        return lire(src["image"])
    if src.get("page") and src.get("motif"):
        _, page = lire(src["page"])
        m = re.search(src["motif"], page.decode("utf-8", "replace"))
        if not m:
            raise ValueError("lien d'image introuvable dans la page")
        return lire(urllib.parse.urljoin(src["page"], m.group(1)))
    raise ValueError("source mal decrite (image, ou page + motif)")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        chemin = self.path.split("?")[0]
        if chemin in ("/", "/sante"):
            return self.repondre(200, "text/plain", b"relais cameras ok\n")
        m = NOM.match(chemin)
        src = sources().get(m.group(1)) if m else None
        if not src:
            return self.repondre(404, "text/plain", b"camera inconnue\n")
        c = CACHE.get(chemin)
        if c and c[0] > time.time():
            if not c[2]:   # erreur recente : on ne re-sollicite pas la source, mais on ne ment pas (503)
                return self.repondre(503, "text/plain", b"indisponible (reessaie dans quelques secondes)\n")
            return self.repondre(200, c[1], c[2])
        try:
            ct, octets = derniere_image(src)
            if not ct.startswith("image/"):
                raise ValueError("reponse non image")
            CACHE[chemin] = (time.time() + CACHE_S, ct, octets)
            return self.repondre(200, ct, octets)
        except Exception as e:
            CACHE[chemin] = (time.time() + ERREUR_S, "text/plain", b"")
            return self.repondre(503, "text/plain", ("indisponible : %s\n" % str(e)[:120]).encode())

    def repondre(self, code, ct, octets):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(octets)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(octets)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4174
    print("relais cameras sur le port", port, "-", len(sources()), "source(s)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
