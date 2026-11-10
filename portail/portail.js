// portail.js - la porte d'entree d'Archi sur le PC. Aucune dependance : Node seul.
//
//  1. EN LOCAL (http://127.0.0.1:5680) : la page d'accueil. On y parle a Archi, on voit son etat,
//     et on y trouve le QR code qui branche le telephone.
//  2. DEPUIS INTERNET (le tunnel HTTPS pointe ici, jamais sur n8n) : seuls passent
//       - POST /webhook/telephone-archi et /webhook/telephone-boite, avec la bonne cle (verifiee ICI, avant n8n) ;
//       - POST /webhook/... de Telegram (si un bot est branche ; n8n verifie son jeton secret) ;
//       - GET /telephone (page d'installation, sans aucun secret) et GET /Archi.apk.
//     Tout le reste repond 404 : l'editeur n8n, ses identifiants et cette page d'accueil ne sortent jamais du PC.
//
// Lance par lancer_archi.ps1 (les reglages viennent du .env, deja charges dans l'environnement).
'use strict';
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');

const ICI = __dirname;
const MAX_CORPS = 30 * 1024 * 1024;          // une photo du telephone tient largement
const DELAI_AGENT_MS = 10 * 60 * 1000;       // un petit modele local peut reflechir longtemps
const RELAIS = ['cf-connecting-ip', 'cf-ray', 'cdn-loop', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto',
  'forwarded', 'x-real-ip', 'via'];

function reglages(env) {
  env = env || process.env;
  const depot = env.ARCHI_DEPOT || path.join(ICI, '..');
  return {
    port: parseInt(env.ARCHI_PORTAIL_PORT || '5680', 10),
    n8nPort: parseInt(env.N8N_PORT || '5678', 10),
    depot,
    base: env.ARCHI_BASE || path.join(os.homedir(), '.n8n-files'),
    etat: env.ARCHI_ETAT || path.join(depot, 'donnees', 'etat'),
    cle: String(env.ARCHI_CLE_TELEPHONE || ''),
    lmUrl: String(env.ARCHI_LM_URL || 'http://127.0.0.1:1234/v1').replace(/\/+$/, ''),
    modele: env.ARCHI_MODELE || 'openai/gpt-oss-20b',
    modeleVision: env.ARCHI_MODELE_VISION || 'google/gemma-3-12b',
    utilisateur: env.ARCHI_UTILISATEUR || '',
    telegram: !!(env.TELEGRAM_BOT_TOKEN && env.ARCHI_TELEGRAM_CHAT_ID),
  };
}

// ---------------------------------------------------------------- qui parle ?
/** Vrai seulement pour un navigateur DU PC, ouvert sur 127.0.0.1 ou localhost, sans aucun relais. */
function estLocal(req, port) {
  const a = (req.socket && req.socket.remoteAddress) || '';
  const boucle = a === '127.0.0.1' || a === '::1' || a === '::ffff:127.0.0.1';
  const h = req.headers || {};
  const hote = String(h.host || '').toLowerCase();
  const hoteLocal = hote === '127.0.0.1:' + port || hote === 'localhost:' + port;
  const relaye = RELAIS.some(k => h[k] !== undefined);
  return boucle && hoteLocal && !relaye;
}

/** Les appels /api/ viennent de NOTRE page : meme origine + en-tete maison (une autre page web ouverte ne peut pas l'ajouter). */
function appelDeLaPage(req, port) {
  const h = req.headers || {};
  const origines = ['http://127.0.0.1:' + port, 'http://localhost:' + port];
  if (h.origin !== undefined && !origines.includes(h.origin)) return false;
  if (h['sec-fetch-site'] !== undefined && h['sec-fetch-site'] !== 'same-origin') return false;
  return h['x-archi-portail'] === '1';
}

function memeCle(recue, attendue) {
  const e = s => crypto.createHash('sha256').update(String(s || ''), 'utf8').digest();
  return String(attendue || '').length >= 16 && crypto.timingSafeEqual(e(recue), e(attendue));
}

/**
 * Que faire d'une demande venue d'Internet ? -> {action: 'relayer' | 'page' | 'apk' | 'refuser', code}
 * La regle est une liste blanche : ce qui n'est pas ecrit ici est refuse.
 */
function routePublique(methode, chemin, entetes, r) {
  const refus = code => ({ action: 'refuser', code });
  if (typeof chemin !== 'string' || chemin.length > 300 || /[\\\0]|\.\.|\/\/|%2e|%2f|%5c/i.test(chemin)) return refus(404);
  if (methode === 'GET' && chemin === '/telephone') return { action: 'page' };
  if (methode === 'GET' && chemin === '/Archi.apk') return { action: 'apk' };
  if (methode !== 'POST') return refus(404);
  if (chemin === '/webhook/telephone-archi' || chemin === '/webhook/telephone-boite') {
    return memeCle(entetes['x-archi-cle'], r.cle) ? { action: 'relayer' } : refus(403);
  }
  // le declencheur Telegram de n8n : /webhook/<identifiant>/webhook (ou /webhook/<workflow>/<noeud>/webhook),
  // avec le jeton secret que n8n a donne a Telegram
  if (r.telegram && /^\/webhook\/[A-Za-z0-9_-]{8,64}(\/[A-Za-z0-9_-]{1,64})?\/webhook$/.test(chemin) && entetes['x-telegram-bot-api-secret-token']) {
    return { action: 'relayer' };
  }
  return refus(404);
}

// ---------------------------------------------------------------- petits outils
function repondre(res, code, corps, type, extra) {
  const tampon = Buffer.isBuffer(corps) ? corps : Buffer.from(String(corps), 'utf8');
  res.writeHead(code, Object.assign({
    'Content-Type': type || 'text/plain; charset=utf-8',
    'Content-Length': tampon.length,
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store',
  }, extra || {}));
  res.end(tampon);
}
const json = (res, code, objet) => repondre(res, code, JSON.stringify(objet), 'application/json; charset=utf-8');

function lireCorps(req, max) {
  return new Promise((ok, non) => {
    const morceaux = [];
    let taille = 0;
    req.on('data', m => {
      taille += m.length;
      if (taille > max) { non(new Error('trop gros')); req.destroy(); return; }
      morceaux.push(m);
    });
    req.on('end', () => ok(Buffer.concat(morceaux)));
    req.on('error', non);
  });
}

/** Envoie la demande a n8n (toujours sur 127.0.0.1) et recopie sa reponse. */
function relayer(req, res, r, chemin, corps, entetesEnPlus) {
  const garder = ['content-type', 'x-archi-cle', 'x-telegram-bot-api-secret-token', 'user-agent', 'accept'];
  const entetes = {};
  for (const k of garder) if (req.headers[k] !== undefined) entetes[k] = req.headers[k];
  Object.assign(entetes, entetesEnPlus || {}, { host: '127.0.0.1:' + r.n8nPort, 'content-length': corps.length });
  const amont = http.request({ host: '127.0.0.1', port: r.n8nPort, method: 'POST', path: chemin, headers: entetes, timeout: DELAI_AGENT_MS },
    rep => {
      const type = rep.headers['content-type'] || 'application/json; charset=utf-8';
      res.writeHead(rep.statusCode || 502, { 'Content-Type': type, 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' });
      rep.pipe(res);
    });
  amont.on('timeout', () => amont.destroy(new Error('delai depasse')));
  amont.on('error', () => { if (!res.headersSent) json(res, 502, { texte: "Archi ne repond pas : n8n est-il lance ? (fenetre « Archi » sur le PC)" }); else res.end(); });
  amont.end(corps);
}

function voir(url, delaiMs) {
  // GET rapide sur une adresse LOCALE (etat de n8n, de LM Studio) : {code, corps} ou null
  return new Promise(ok => {
    let fini = false;
    const rendre = v => { if (!fini) { fini = true; ok(v); } };
    try {
      const u = new URL(url);
      const req = http.request({ host: u.hostname, port: u.port || 80, path: u.pathname + u.search, method: 'GET', timeout: delaiMs }, rep => {
        const m = [];
        rep.on('data', x => { if (m.length < 400) m.push(x); });
        rep.on('end', () => rendre({ code: rep.statusCode, corps: Buffer.concat(m).toString('utf8') }));
      });
      req.on('timeout', () => { req.destroy(); rendre(null); });
      req.on('error', () => rendre(null));
      req.end();
    } catch (e) { rendre(null); }
  });
}

function adressePublique(r) {
  // ecrite par lancer_archi.ps1 quand le tunnel est ouvert ; verifiee : https, un nom d'hote, rien d'autre
  try {
    const t = fs.readFileSync(path.join(r.etat, 'adresse_publique.txt'), 'utf8').trim().replace(/\/+$/, '');
    return /^https:\/\/[a-z0-9.-]{4,200}$/i.test(t) ? t : '';
  } catch (e) { return ''; }
}

function outils(r) {
  // la vitrine : nom + premiere phrase de chaque outil maison inscrit au registre
  try {
    const reg = JSON.parse(fs.readFileSync(path.join(r.base, 'outils', 'registre.json'), 'utf8'));
    return Object.keys(reg).map(nom => {
      const d = String(reg[nom].description || '').replace(/^MODE D.?EMPLOI\s*:\s*/i, '');
      const phrase = d.split(/(?<=[.!?:])\s/)[0].replace(/[:.]\s*$/, '');
      return { nom, quoi: phrase.slice(0, 110), sensible: !!reg[nom].sensible };
    });
  } catch (e) { return []; }
}

async function etat(r) {
  const [n8n, lm] = await Promise.all([
    voir('http://127.0.0.1:' + r.n8nPort + '/healthz', 2500),
    voir(r.lmUrl + '/models', 2500),
  ]);
  let modeles = [];
  try { modeles = (JSON.parse(lm.corps).data || []).map(m => String(m.id)); } catch (e) { modeles = []; }
  const pub = adressePublique(r);
  return {
    utilisateur: r.utilisateur,
    n8n: !!(n8n && n8n.code === 200),
    cerveau: { joignable: !!lm, modele: r.modele, pret: modeles.includes(r.modele), vision: r.modeleVision, vision_prete: modeles.includes(r.modeleVision) },
    telegram: r.telegram,
    cle_ok: r.cle.length >= 16,
    adresse_publique: pub,
    // le lien du QR code : la cle est dans le « # », que le navigateur du telephone n'envoie jamais sur le reseau
    lien_telephone: pub && r.cle.length >= 16 ? pub + '/telephone#k=' + encodeURIComponent(r.cle) : '',
    apk: fs.existsSync(path.join(r.depot, 'appli', 'Archi.apk')),
    outils: outils(r),
    n8n_url: 'http://127.0.0.1:' + r.n8nPort,
  };
}

const CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'";
function fichier(res, nom, type, extra) {
  try {
    repondre(res, 200, fs.readFileSync(path.join(ICI, nom)), type, Object.assign({ 'Content-Security-Policy': CSP, 'X-Frame-Options': 'DENY' }, extra || {}));
  } catch (e) { repondre(res, 500, 'fichier manquant : ' + nom); }
}

// ---------------------------------------------------------------- le serveur
function creerServeur(r) {
  return http.createServer(async (req, res) => {
    try {
      const chemin = String(req.url || '/').split('?')[0];
      const methode = req.method || 'GET';

      if (!estLocal(req, r.port)) {
        // ----- demande venue d'Internet (tunnel) ou d'une page piegee : liste blanche stricte
        const route = routePublique(methode, chemin, req.headers, r);
        if (route.action === 'page') return fichier(res, 'telephone.html', 'text/html; charset=utf-8');
        if (route.action === 'apk') {
          const apk = path.join(r.depot, 'appli', 'Archi.apk');
          if (!fs.existsSync(apk)) return repondre(res, 404, "L'appli n'est pas sur ce PC.");
          res.writeHead(200, { 'Content-Type': 'application/vnd.android.package-archive', 'Content-Length': fs.statSync(apk).size,
            'Content-Disposition': 'attachment; filename="Archi.apk"', 'X-Content-Type-Options': 'nosniff' });
          return fs.createReadStream(apk).pipe(res);
        }
        if (route.action === 'relayer') return relayer(req, res, r, chemin, await lireCorps(req, MAX_CORPS));
        if (route.code === 403) await new Promise(x => setTimeout(x, 400));   // mauvaise cle : on ne repond pas a toute vitesse
        return repondre(res, route.code, route.code === 403 ? 'Cle refusee.' : 'Introuvable.');
      }

      // ----- navigateur du PC
      if (methode === 'GET' && (chemin === '/' || chemin === '/index.html')) return fichier(res, 'accueil.html', 'text/html; charset=utf-8');
      if (methode === 'GET' && chemin === '/qrcode.js') return fichier(res, 'qrcode.js', 'text/javascript; charset=utf-8');
      if (methode === 'GET' && chemin === '/telephone') return fichier(res, 'telephone.html', 'text/html; charset=utf-8');
      if (chemin.startsWith('/api/')) {
        if (!appelDeLaPage(req, r.port)) return json(res, 403, { erreur: 'appel refuse' });
        if (methode === 'GET' && chemin === '/api/etat') return json(res, 200, await etat(r));
        if (methode === 'POST' && chemin === '/api/message') {
          return relayer(req, res, r, '/webhook/telephone-archi', await lireCorps(req, MAX_CORPS), { 'x-archi-cle': r.cle });
        }
        if (methode === 'POST' && chemin === '/api/annonces') {
          // les rappels du planificateur, comme pour l'appli (sans accuse de reception : le telephone les recoit aussi)
          return relayer(req, res, r, '/webhook/telephone-boite', Buffer.from('{}'), { 'x-archi-cle': r.cle, 'content-type': 'application/json' });
        }
      }
      return repondre(res, 404, 'Introuvable.');
    } catch (e) {
      if (!res.headersSent) repondre(res, e && e.message === 'trop gros' ? 413 : 500, 'Erreur.');
      else res.end();
    }
  });
}

if (require.main === module) {
  const r = reglages();
  const serveur = creerServeur(r);
  serveur.requestTimeout = DELAI_AGENT_MS;
  serveur.headersTimeout = 30000;
  serveur.on('error', e => { console.error('Portail : ' + (e.code === 'EADDRINUSE' ? 'le port ' + r.port + ' est deja pris.' : e.message)); process.exit(1); });
  // 127.0.0.1 seulement : ni le reseau local ni Internet n'arrivent ici, sauf par le tunnel
  serveur.listen(r.port, '127.0.0.1', () => console.log('Portail Archi : http://127.0.0.1:' + r.port));
}

module.exports = { reglages, estLocal, appelDeLaPage, routePublique, memeCle, creerServeur, adressePublique, outils };
