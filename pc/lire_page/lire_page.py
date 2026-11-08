# -*- coding: utf-8 -*-
"""lire_page.py - lit une page web et renvoie son texte propre, pour Archi et la veille.
Usage : python lire_page.py --fichier demande.json   ou   python lire_page.py "https://..."
  demande.json : {"url": "https://...", "max_caracteres": 12000, "furtif": "auto" | "oui" | "non" | "strict"}
Repond UNE ligne JSON {"ok", "titre", "texte", "moteur", "phrase_pour_utilisateur"}.
Moteurs, dans l'ordre : Scrapling simple (requete qui ressemble a un navigateur) -> Scrapling furtif (vrai navigateur,
passe la plupart des protections) -> urllib (secours). Si tout echoue, ok=false : le workflow n8n garde Tavily en dernier recours.
Garde-fous : pas de pages locales (127.0.0.1, localhost, fichiers), pas de formulaire rempli, lecture seule.
Installation (une fois, par J) : venv\\Scripts\\pip install "scrapling[fetchers]"  puis  venv\\Scripts\\scrapling install
"""
import json
import logging
import os
import re
import ipaddress
import socket
import sys
import urllib.parse
import urllib.request

# LIMITE CONNUE (Scrapling) : son navigateur suit lui-meme les redirections et charge les ressources de la page ;
# l'adresse FINALE est reverifiee et le contenu refuse si elle est locale, mais la requete a deja eu lieu.
# Protection stricte : furtif="strict" ou ARCHI_LIRE_PAGE_STRICT=1 -> seulement urllib, chaque redirection controlee.
def url_autorisee(url):
    """http(s) public seulement : pas d'identifiant dans l'adresse, et TOUTES les adresses IP du nom doivent etre
    publiques (pas de PC, de box, de reseau local, de 169.254, ni d'IP deguisee en decimal ou en IPv6)."""
    try:
        u = urllib.parse.urlsplit(str(url).strip())
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or "@" in u.netloc:
        return False
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return False
    return bool(infos)


class _Redirections(urllib.request.HTTPRedirectHandler):
    """chaque redirection est reverifiee (une page publique ne peut pas renvoyer vers le reseau local)"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not url_autorisee(newurl):
            raise RuntimeError("redirection vers une adresse interdite")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OUVREUR = urllib.request.build_opener(_Redirections)
logging.getLogger("scrapling").setLevel(logging.WARNING)  # ses messages INFO ne doivent pas se meler a la reponse JSON
logging.getLogger().setLevel(logging.WARNING)


class PageAbsente(Exception):
    pass


VENV_PY = os.environ.get("ARCHI_PY", "")


def sortir(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def nettoyer(t):
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


def texte_depuis_page(page):
    """page = objet Scrapling (Selector). On enleve scripts, styles, menus."""
    for sel in ("script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe", "svg"):
        try:
            for e in page.css(sel):
                e.remove()
        except Exception:
            pass
    titre = ""
    try:
        titre = (page.css("title::text").get() or "").strip()
    except Exception:
        pass
    corps = None
    for sel in ("article", "main", "[role=main]", "body"):
        try:
            c = page.css(sel)
            if c:
                corps = c[0]
                break
        except Exception:
            pass
    txt = ""
    try:
        txt = (corps or page).get_all_text(separator="\n", strip=True)
    except Exception:
        try:
            txt = "\n".join(page.css("::text").getall())
        except Exception:
            txt = ""
    return titre, nettoyer(txt)


def via_scrapling_simple(url):
    from scrapling.fetchers import Fetcher
    page = Fetcher.get(url, impersonate="chrome", timeout=30, stealthy_headers=True)
    if getattr(page, "url", None) and not url_autorisee(page.url):
        raise RuntimeError("redirection vers une adresse interdite")
    if page.status in (404, 410):
        raise PageAbsente(f"HTTP {page.status}")
    if page.status != 200:
        raise RuntimeError(f"HTTP {page.status}")
    return texte_depuis_page(page)


def via_scrapling_furtif(url):
    from scrapling.fetchers import StealthyFetcher
    page = StealthyFetcher.fetch(url, headless=True, network_idle=True, solve_cloudflare=True, timeout=60000)
    if getattr(page, "url", None) and not url_autorisee(page.url):
        raise RuntimeError("redirection vers une adresse interdite")
    if page.status in (404, 410):
        raise PageAbsente(f"HTTP {page.status}")
    if page.status != 200:
        raise RuntimeError(f"HTTP {page.status}")
    return texte_depuis_page(page)


def via_urllib(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Archi/1.0"})
    with _OUVREUR.open(req, timeout=30) as r:
        html = r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
    titre = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    html = re.sub(r"<(script|style|noscript|nav|footer|header|aside|form|svg)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    txt = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", html, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    import html as H
    return (H.unescape(titre.group(1)).strip() if titre else ""), nettoyer(H.unescape(txt))


def main():
    args = sys.argv[1:]
    d = {}
    if "--fichier" in args:
        d = json.load(open(args[args.index("--fichier") + 1], encoding="utf-8"))
    elif args:
        try:
            d = json.loads(args[0])
        except Exception:
            d = {"url": args[0]}
    if isinstance(d.get("parametres"), dict):
        d = {**d, **d["parametres"]}
    url = str(d.get("url") or d.get("adresse") or "").strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    try:
        maxi = int(d.get("max_caracteres") or 12000)
    except Exception:
        maxi = 12000
    furtif = str(d.get("furtif") or "auto").lower()
    if not url:
        sortir({"ok": False, "phrase_pour_utilisateur": "Il me faut l'adresse de la page à lire."})
    if not url_autorisee(url):
        sortir({"ok": False, "phrase_pour_utilisateur": "Je ne lis pas les pages locales ou internes au réseau."})
    # si on n'est pas dans le venv d'Archi (ou Scrapling absent), on se relance avec lui
    try:
        import scrapling  # noqa: F401
    except ImportError:
        if os.path.exists(VENV_PY) and os.path.abspath(sys.executable).lower() != os.path.abspath(VENV_PY).lower():
            import subprocess
            r = subprocess.run([VENV_PY, os.path.abspath(__file__)] + args, capture_output=True, text=True, encoding="utf-8")
            sys.stdout.write(r.stdout or json.dumps({"ok": False, "phrase_pour_utilisateur": "Le lecteur de pages n'a pas répondu.", "erreur": (r.stderr or "")[-300:]}, ensure_ascii=False))
            return
    essais = []
    moteurs = []
    strict = furtif == "strict" or os.environ.get("ARCHI_LIRE_PAGE_STRICT") == "1"
    if furtif != "oui" and not strict:
        moteurs.append(("scrapling", via_scrapling_simple))
    if furtif not in ("non", "strict") and not strict:
        moteurs.append(("scrapling_furtif", via_scrapling_furtif))
    moteurs.append(("simple", via_urllib))
    for nom, f in moteurs:
        try:
            titre, texte = f(url)
            if len(texte) < 200 and nom != "simple":
                raise RuntimeError("page presque vide (protection ou page dynamique)")
            coupe = len(texte) > maxi
            sortir({"ok": True, "url": url, "titre": titre, "moteur": nom, "texte": texte[:maxi], "coupe": coupe,
                    "longueur": len(texte), "phrase_pour_utilisateur": f"Page lue ({nom}) : {titre or url}"[:200]})
        except SystemExit:
            raise
        except PageAbsente as e:
            sortir({"ok": False, "url": url, "phrase_pour_utilisateur": "Cette page n'existe pas (erreur 404) : vérifie l'adresse.", "essais": essais + [f"{nom}: {e}"]})
        except Exception as e:
            if "404" in str(e) and nom == "simple":
                sortir({"ok": False, "url": url, "phrase_pour_utilisateur": "Cette page n'existe pas (erreur 404) : vérifie l'adresse.", "essais": essais + [f"{nom}: {e}"]})
            essais.append(f"{nom}: {type(e).__name__} {str(e)[:100]}")
    sortir({"ok": False, "url": url, "phrase_pour_utilisateur": "Je n'arrive pas à lire cette page, même en mode furtif.", "essais": essais})


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        sortir({"ok": False, "phrase_pour_utilisateur": "Le lecteur de pages a eu un problème.", "erreur": repr(e)[:200]})
