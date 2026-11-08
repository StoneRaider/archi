// porte.js - la porte de l'oeil (02/11/2026) : la SEULE entree depuis Internet vers le globe (gods-eye-view).
//
//  - /entree?b=<billet>&vers=/chemin : verifie le billet (30 min, signe avec la cle par
//    oeil.py), pose le cookie « oeil », renvoie vers le chemin
//    (le #hash de l'adresse suit tout seul la redirection) ;
//  - /sante : repond « ok » sans cookie (pour le controle) ;
//  - tout le reste : cookie obligatoire, sinon 404 « Rien ici » ; puis relais vers le globe en retirant les
//    en-tetes de proxy (le globe refuse « Proxied requests ») et en se presentant comme 127.0.0.1:4173
//    (hote toujours autorise par le globe). Les WebSockets passent aussi.
//
// Le cookie ne contient pas la cle : c'est une empreinte (HMAC) derivee de la cle. Changer la cle
// (ARCHI_CLE_OEIL dans le .env) invalide tous les cookies. Rien n'est journalise a part les entrees et les pannes.
'use strict';
const http = require('http');
const net = require('net');
const fs = require('fs');
const crypto = require('crypto');

const PORT = parseInt(process.env.PORTE_PORT || '4175', 10);
const CIBLE = new URL(process.env.OEIL_URL || 'http://oeil:4173');
const HOTE_PRESENTE = process.env.OEIL_HOTE || '127.0.0.1:4173';
const COOKIE = 'oeil';
const DUREE_COOKIE = Number(process.env.OEIL_DUREE_COOKIE_S || 30 * 24 * 3600);   // 30 jours, puis un nouveau billet

function lireCle() {
  const e = process.env.CLE_OEIL || process.env.ARCHI_CLE_OEIL;   // le .env d'Archi (env_file) d'abord
  if (e) return e.trim();
  const f = process.env.CLE_OEIL_FICHIER || '/run/cle_oeil';
  try {
    return fs.readFileSync(f, 'utf8').trim();
  } catch (e) {
    return '';
  }
}
const CLE = lireCle();
if (CLE.length < 16) {
  console.error('porte : cle absente ou trop courte (CLE_OEIL ou CLE_OEIL_FICHIER). Arret.');
  process.exit(1);
}
// cookie = expiration.signature (HMAC de la cle) : il expire vraiment, et changer la cle les invalide tous
const signerCookie = exp => crypto.createHmac('sha256', CLE).update('cookie-oeil-v2.' + exp).digest('base64url');
const nouveauCookie = () => { const exp = Math.floor(Date.now() / 1000) + DUREE_COOKIE; return exp + '.' + signerCookie(exp); };

// en-tetes que le globe considere comme la marque d'un proxy (src/localRequestGate.mjs) + ceux de Cloudflare
const RETIRER = new Set([
  'forwarded', 'via', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-port', 'x-forwarded-proto',
  'x-real-ip', 'cdn-loop', 'true-client-ip', 'origin', 'host', 'connection', 'keep-alive', 'proxy-connection',
  'transfer-encoding', 'upgrade',
]);

const egal = (a, b) => {
  const x = Buffer.from(String(a || ''), 'utf8'), y = Buffer.from(String(b || ''), 'utf8');
  return x.length === y.length && crypto.timingSafeEqual(x, y);
};

function cookies(req) {
  const out = {};
  for (const part of String(req.headers.cookie || '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

const admis = (req) => {
  const m = /^(\d{9,11})\.([A-Za-z0-9_-]{20,})$/.exec(cookies(req)[COOKIE] || '');
  return !!m && Number(m[1]) > Date.now() / 1000 && egal(m[2], signerCookie(m[1]));
};

function enTetesPourLeGlobe(req) {
  const h = {};
  for (const [k, v] of Object.entries(req.headers)) {
    const n = k.toLowerCase();
    if (RETIRER.has(n) || n.startsWith('cf-') || n.startsWith('x-forwarded-')) continue;
    if (n === 'cookie') {
      const reste = String(v).split(';').map((s) => s.trim()).filter((s) => s && !s.startsWith(COOKIE + '='));
      if (reste.length) h.cookie = reste.join('; ');
      continue;
    }
    h[k] = v;
  }
  h.host = HOTE_PRESENTE;
  return h;
}

function repondre(res, code, texte) {
  res.writeHead(code, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' });
  res.end(texte);
}

// billet d'entree a duree limitee, fabrique par oeil.py : jeton.expiration.signature(HMAC de la cle)
function billetValide(b) {
  const m = /^([a-z0-9]{6,32})\.(\d{9,11})\.([A-Za-z0-9_-]{32})$/.exec(String(b || ''));
  if (!m) return false;
  const exp = parseInt(m[2], 10);
  if (!Number.isFinite(exp) || exp < Date.now() / 1000) return false;
  const attendu = crypto.createHmac('sha256', CLE).update(`${m[1]}.${m[2]}`).digest('base64url').slice(0, 32);
  return egal(m[3], attendu);
}

function entree(req, res, url) {
  // la cle maitresse ne passe JAMAIS dans une adresse : seulement un billet signe a duree limitee (oeil.py)
  let vers = (url.searchParams.get('vers') || '/').replace(/[\x00-\x1f\x7f]/g, '');
  // chez nous seulement : un chemin absolu, sans // ni \ (qui feraient sortir vers un autre site)
  if (!vers.startsWith('/') || vers.startsWith('//') || vers.includes('\\')) vers = '/';
  // un cookie deja valable suffit (un vieux lien rouvert sur un telephone deja admis marche encore)
  const ok = admis(req) || billetValide(url.searchParams.get('b'));
  if (!ok) {
    console.log(`entree refusee ${new Date().toISOString()}`);
    setTimeout(() => repondre(res, 404, 'Rien ici.'), 800);
    return;
  }
  console.log(`entree ouverte ${new Date().toISOString()} vers ${vers.slice(0, 60)}`);
  res.writeHead(302, {
    location: vers,
    'set-cookie': `${COOKIE}=${nouveauCookie()}; Path=/; Max-Age=${DUREE_COOKIE}; HttpOnly; Secure; SameSite=Lax`,
    'cache-control': 'no-store',
  });
  res.end();
}

function relayer(req, res) {
  const options = {
    host: CIBLE.hostname, port: CIBLE.port || 80, method: req.method, path: req.url,
    headers: enTetesPourLeGlobe(req), timeout: 120000,
  };
  const p = http.request(options, (r) => {
    const h = { ...r.headers };
    res.writeHead(r.statusCode, h);
    r.pipe(res);
  });
  p.on('timeout', () => p.destroy(new Error('delai depasse')));
  p.on('error', (e) => {
    console.log(`globe injoignable : ${e.message}`);
    if (!res.headersSent) repondre(res, 502, "L'oeil ne repond pas (le globe est-il lance ?).");
    else res.destroy();
  });
  req.pipe(p);
}

const serveur = http.createServer((req, res) => {
  try {
    let url;
    try {
      url = new URL(req.url, 'http://porte');
    } catch (e) {
      return repondre(res, 400, 'Adresse illisible.');
    }
    if (url.pathname === '/sante') return repondre(res, 200, 'ok');
    if (url.pathname === '/entree') return entree(req, res, url);
    if (!admis(req)) return repondre(res, 404, 'Rien ici.');
    relayer(req, res);
  } catch (e) {   // jamais laisser tomber le processus pour une requete tordue
    console.log(`requete refusee : ${e.message}`);
    try { if (!res.headersSent) repondre(res, 400, 'Requete refusee.'); else res.destroy(); } catch (x) { /* rien */ }
  }
});

// WebSocket (rechargement a chaud de Vite, flux en direct) : meme controle, puis tuyau brut
serveur.on('upgrade', (req, socket, head) => {
  if (!admis(req)) {
    socket.write('HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n');
    return socket.destroy();
  }
  const h = enTetesPourLeGlobe(req);
  h.connection = 'Upgrade';
  h.upgrade = req.headers.upgrade || 'websocket';
  const cible = net.connect(CIBLE.port || 80, CIBLE.hostname, () => {
    let requete = `${req.method} ${req.url} HTTP/1.1\r\n`;
    for (const [k, v] of Object.entries(h)) requete += `${k}: ${Array.isArray(v) ? v.join(', ') : v}\r\n`;
    cible.write(requete + '\r\n');
    if (head && head.length) cible.write(head);
    socket.pipe(cible).pipe(socket);
  });
  cible.on('error', () => socket.destroy());
  socket.on('error', () => cible.destroy());
});

serveur.keepAliveTimeout = 65000;
serveur.headersTimeout = 66000;   // toujours un peu plus que keepAliveTimeout (sinon coupures sporadiques)
serveur.listen(PORT, '0.0.0.0', () => console.log(`porte de l'oeil sur ${PORT} -> ${CIBLE.origin} (hote presente : ${HOTE_PRESENTE})`));
