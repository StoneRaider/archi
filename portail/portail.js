// portail.js - les deux portes d'Archi sur le PC. Aucune dependance : Node seul.
//
//  1. LA PAGE D'ACCUEIL (http://127.0.0.1:5680, ARCHI_PORTAIL_PORT) : pour le navigateur DU PC seulement.
//     On y parle a Archi, on voit son etat, et on y trouve le QR code qui branche le telephone.
//  2. LA PORTE DU TELEPHONE (127.0.0.1:5681, ARCHI_PORTE_PORT) : c'est ELLE que vise le tunnel HTTPS, jamais n8n
//     ni la page d'accueil. Elle ne connait qu'une liste blanche :
//       - POST /webhook/telephone-archi et /webhook/telephone-boite, avec la bonne cle (verifiee ICI, avant n8n) ;
//       - POST du webhook Telegram : le chemin ET le jeton secret propres a cette installation, verifies ICI ;
//       - GET /telephone (page d'installation, sans aucun secret) et GET /Archi.apk.
//     Elle note l'heure de chaque passage (jamais la cle ni le contenu) : la page d'accueil montre ou en est le telephone.
//     Tout le reste repond 404 : l'editeur n8n, son API et la page d'accueil ne sont pas derriere cette porte.
//
// Lance par lancer_archi.ps1 (les reglages viennent du .env, deja charges dans l'environnement).
// Si le lanceur disparait (fenetre fermee a la croix), le portail arrete le tunnel et le serveur, puis s'arrete.
'use strict';
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const voix = require('../core/voix');   // l'oreille et la parole : la page d'accueil montre le micro si elles sont installees

const ICI = __dirname;
const MAX_CORPS = 30 * 1024 * 1024;          // une photo du telephone tient largement
const MAX_CORPS_TELEGRAM = 1024 * 1024;      // un message Telegram est petit
const DELAI_AGENT_MS = 10 * 60 * 1000;       // un petit modele local peut reflechir longtemps
const RELAIS = ['cf-connecting-ip', 'cf-ray', 'cdn-loop', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto',
  'forwarded', 'x-real-ip', 'via'];

function reglages(env) {
  env = env || process.env;
  const depot = env.ARCHI_DEPOT || path.join(ICI, '..');
  const port = parseInt(env.ARCHI_PORTAIL_PORT || '5680', 10);
  return {
    port,
    portPorte: parseInt(env.ARCHI_PORTE_PORT || String(port + 1), 10),
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
    voix: voix.reglages(env),
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

/** Comparaison en temps constant ; refuse une valeur attendue de moins de 16 caracteres. */
function memeCle(recue, attendue) {
  const e = s => crypto.createHash('sha256').update(String(s || ''), 'utf8').digest();
  return String(attendue || '').length >= 16 && crypto.timingSafeEqual(e(recue), e(attendue));
}

/**
 * Le webhook Telegram de CETTE installation : {chemin, jeton}, ou null.
 * importer_workflows.py tire au hasard l'identifiant du noeud et celui du webhook, puis les note dans ce fichier.
 * n8n donne a Telegram le jeton secret « <workflow>_<noeud> » : sans ce tirage, il serait le meme pour tout le monde.
 */
function telegramAttendu(r) {
  try {
    const t = JSON.parse(fs.readFileSync(path.join(r.base, '.workflows_archi_importes', 'telegram.json'), 'utf8'));
    const ok = v => typeof v === 'string' && /^[A-Za-z0-9_-]{8,64}$/.test(v);
    if (!ok(t.webhook_id) || !ok(t.node_id) || !ok(t.workflow_id)) return null;
    return { chemin: '/webhook/' + t.webhook_id + '/webhook', jeton: (t.workflow_id + '_' + t.node_id).replace(/[^a-zA-Z0-9_-]+/g, '') };
  } catch (e) { return null; }
}

/**
 * Que faire d'une demande arrivee a la porte du telephone ? -> {action: 'relayer' | 'page' | 'apk' | 'refuser', code, max}
 * La regle est une liste blanche : ce qui n'est pas ecrit ici est refuse.
 */
function routePublique(methode, chemin, entetes, r) {
  const refus = code => ({ action: 'refuser', code });
  if (typeof chemin !== 'string' || chemin.length > 300 || /[\\\0]|\.\.|\/\/|%2e|%2f|%5c/i.test(chemin)) return refus(404);
  if (methode === 'GET' && chemin === '/telephone') return { action: 'page' };
  if (methode === 'GET' && chemin === '/Archi.apk') return { action: 'apk' };
  if (methode !== 'POST') return refus(404);
  if (chemin === '/webhook/telephone-archi' || chemin === '/webhook/telephone-boite') {
    if (!memeCle(entetes['x-archi-cle'], r.cle)) return refus(403);
    // l'appli vient de se brancher et verifie la liaison : on lui repond ici, sans reveiller l'agent
    if (entetes['x-archi-essai'] === '1') return { action: 'essai' };
    return { action: 'relayer', max: MAX_CORPS };
  }
  if (r.telegram) {
    const tg = telegramAttendu(r);
    if (tg && chemin === tg.chemin) {
      return memeCle(entetes['x-telegram-bot-api-secret-token'], tg.jeton) ? { action: 'relayer', max: MAX_CORPS_TELEGRAM } : refus(403);
    }
  }
  return refus(404);
}

// ---------------------------------------------------------------- le suivi du telephone
/** Ce que la porte a vu passer : l'heure du dernier passage de chaque etape (0 = jamais). Rien d'autre n'est garde. */
function nouveauSuivi() { return { page: 0, apk: 0, appli: 0, refus: 0 }; }

const CHEMINS_CONNUS = ['/telephone', '/Archi.apk', '/webhook/telephone-archi', '/webhook/telephone-boite'];
const MAX_JOURNAL = 512 * 1024;
const COMPTE_AUTRES = new WeakMap();   // par suivi : combien de demandes hors liste blanche notees dans la minute

/**
 * Note un passage a la porte : dans le suivi (la page d'accueil montre ou en est le telephone) et dans
 * donnees/etat/porte.log (pour comprendre une panne). On n'ecrit JAMAIS la cle, les en-tetes, le contenu ni
 * l'adresse de l'appelant : seulement l'heure, la methode, un chemin de la liste blanche et le resultat.
 */
function noterPassage(r, suivi, methode, chemin, route, entetes) {
  // qui passe : l'appli, un navigateur de telephone (Android), ou autre chose (le verificateur du PC, un curieux).
  // Ce n'est qu'un indice pour l'affichage, jamais une preuve : la securite, c'est la cle.
  const ua = String((entetes || {})['user-agent'] || '');
  const appli = /^ArchiTelephone\//.test(ua);
  const telephone = appli || /Android/i.test(ua);
  const maintenant = Date.now();
  if (route.action === 'page') { if (telephone) suivi.page = maintenant; }
  else if (route.action === 'apk') { if (telephone) suivi.apk = maintenant; }
  else if (route.action === 'relayer' || route.action === 'essai') { if (appli) suivi.appli = maintenant; }
  else if (route.code === 403) { if (appli) suivi.refus = maintenant; }   // le verificateur ou un curieux ne sont pas « une appli »
  // les demandes hors liste blanche (robots d'Internet) ne chassent pas l'historique utile : 20 lignes par minute au plus
  if (route.action === 'refuser' && route.code === 404) {
    const minute = Math.floor(maintenant / 60000), c = COMPTE_AUTRES.get(suivi) || { minute: 0, n: 0 };
    if (c.minute !== minute) { c.minute = minute; c.n = 0; }
    c.n++; COMPTE_AUTRES.set(suivi, c);
    if (c.n > 20) return;
  }
  const ligne = [new Date(maintenant).toISOString(), methode === 'GET' || methode === 'POST' ? methode : 'AUTRE',
    CHEMINS_CONNUS.includes(chemin) ? chemin : (route.action === 'relayer' ? '(telegram)' : '(autre)'),
    route.action === 'refuser' ? String(route.code) : route.action, appli ? 'appli' : (telephone ? 'telephone' : '-')].join(' ') + '\n';
  const f = path.join(r.etat, 'porte.log');
  fs.stat(f, (e, s) => {
    const ecrire = () => fs.appendFile(f, ligne, () => { /* pas de dossier : pas de journal, la porte marche quand meme */ });
    if (!e && s.size > MAX_JOURNAL) fs.rename(f, f + '.1', ecrire); else ecrire();
  });
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

/** Code court derive de la cle : affiche sur le PC ET dans l'appli au moment du branchement, pour comparer a l'oeil. */
function codeCourt(cle) {
  return crypto.createHash('sha256').update(String(cle || ''), 'utf8').digest('hex').slice(0, 4).toUpperCase();
}

/** config/vitrine.json : le nom lisible et la phrase de chaque outil, et les projets pas encore aboutis. */
function vitrine(r) {
  try {
    const v = JSON.parse(fs.readFileSync(path.join(r.depot, 'config', 'vitrine.json'), 'utf8'));
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
  } catch (e) { return {}; }
}
const court = (x, n) => (typeof x === 'string' ? x.trim().slice(0, n) : '');

function outils(r) {
  // Les outils maison inscrits au registre, et les outils branches directement sur l'agent (agent=true dans la vitrine).
  // La vitrine donne l'ordre, le nom lisible et la phrase ; un outil qu'elle ne connait pas garde la premiere phrase de son mode d'emploi.
  let reg = {};
  try { reg = JSON.parse(fs.readFileSync(path.join(r.base, 'outils', 'registre.json'), 'utf8')); } catch (e) { reg = {}; }
  if (!reg || typeof reg !== 'object' || Array.isArray(reg)) reg = {};
  const inscrit = nom => Object.prototype.hasOwnProperty.call(reg, nom) && reg[nom] && typeof reg[nom] === 'object';
  const v = vitrine(r);
  const fiches = (Array.isArray(v.outils) ? v.outils : []).filter(f => f && typeof f.nom === 'string');
  const liste = [], vus = new Set();
  for (const f of fiches) {
    if (vus.has(f.nom) || !(f.agent === true || inscrit(f.nom))) continue;
    vus.add(f.nom);
    liste.push({ nom: f.nom.slice(0, 40), titre: court(f.titre, 60), quoi: court(f.quoi, 200), besoin: court(f.besoin, 60),
      sensible: f.agent === true ? !!f.sensible : !!reg[f.nom].sensible });
  }
  for (const nom of Object.keys(reg)) {
    if (vus.has(nom) || !inscrit(nom)) continue;
    const d = String(reg[nom].description || '').replace(/^MODE D.?EMPLOI\s*:\s*/i, '');
    const phrase = d.split(/(?<=[.!?:])\s/)[0].replace(/[:.]\s*$/, '');
    liste.push({ nom, titre: '', quoi: phrase.slice(0, 110), besoin: '', sensible: !!reg[nom].sensible });
  }
  return liste;
}

/** Menu > Outils en cours de developpement : les projets pas encore aboutis (config/vitrine.json, « en_developpement »). */
function chantiers(r) {
  const L = vitrine(r).en_developpement;
  return (Array.isArray(L) ? L : []).filter(c => c && court(c.titre, 80)).slice(0, 30).map(c => ({ titre: court(c.titre, 80), quoi: court(c.quoi, 240) }));
}

const SAIN_DEPUIS = new WeakMap();   // par portail : depuis quand n8n repond

/** Ce qu'Archi a retenu tout seul (outils/memoire) : le nombre de fiches et de faits, et les derniers faits ranges. */
function memoire(r) {
  const resume = { fiches: 0, faits: 0, derniers: [] };
  const racine = path.join(r.base, 'memoire');
  for (const piece of ['moi', 'personnes', 'projets', 'lieux', 'preferences']) {
    let fichiers = [];
    try { fichiers = fs.readdirSync(path.join(racine, piece)).filter(f => f.endsWith('.md')); } catch (e) { continue; }
    for (const f of fichiers) {
      let n = 0;
      try {
        for (const bloc of fs.readFileSync(path.join(racine, piece, f), 'utf8').split(/\*\*Faits :\*\*/).slice(1)) {
          n += bloc.split(/\n\*\*/)[0].split(/\r?\n/).filter(l => l.trim().startsWith('- ')).length;
        }
      } catch (e) { n = 0; }
      if (n) { resume.fiches++; resume.faits += n; }
    }
  }
  try {
    const lignes = fs.readFileSync(path.join(racine, '.retenu.jsonl'), 'utf8').split(/\r?\n/).filter(Boolean).slice(-8);
    for (const l of lignes) {
      let x = null;
      try { x = JSON.parse(l); } catch (e) { continue; }   // une ligne abimee ne cache pas les autres
      if (x && typeof x.fait === 'string' && typeof x.quand === 'number') resume.derniers.push({ quand: x.quand, fait: x.fait.slice(0, 240) });
    }
  } catch (e) { /* pas encore de journal : rien n'a ete retenu */ }
  return resume;
}

async function etat(r, suivi) {
  const [n8n, sonde, lm, etatVoix] = await Promise.all([
    voir('http://127.0.0.1:' + r.n8nPort + '/healthz', 2500),
    // n8n se dit en bonne sante quelques secondes AVANT d'avoir active le workflow : un message envoye a ce moment-la
    // se perd. Un GET sur le webhook (qui n'accepte que POST) ne lance rien, et sa reponse dit s'il est enregistre.
    voir('http://127.0.0.1:' + r.n8nPort + '/webhook/telephone-archi', 2500),
    voir(r.lmUrl + '/models', 2500),
    r.voix ? voix.etat(r.voix).catch(() => null) : null,
  ]);
  const sain = !!(n8n && n8n.code === 200);
  if (!sain) SAIN_DEPUIS.delete(r); else if (!SAIN_DEPUIS.has(r)) SAIN_DEPUIS.set(r, Date.now());
  const active = !!(sonde && sonde.code === 404 && /POST request/i.test(sonde.corps));
  // si la reponse de n8n change de forme un jour, on ne reste pas bloque : au bout de 90 s de bonne sante, on le croit pret
  const agentPret = sain && (active || Date.now() - SAIN_DEPUIS.get(r) > 90000);
  let modeles = [];
  try { modeles = (JSON.parse(lm.corps).data || []).map(m => String(m.id)); } catch (e) { modeles = []; }
  const pub = adressePublique(r);
  const pret = pub && r.cle.length >= 16;
  return {
    utilisateur: r.utilisateur,
    n8n: agentPret,   // pret a recevoir un message : n8n repond ET le workflow est active
    cerveau: { joignable: !!lm, modele: r.modele, pret: modeles.includes(r.modele), vision: r.modeleVision, vision_prete: modeles.includes(r.modeleVision) },
    telegram: r.telegram,
    // la memoire : ce qu'Archi a retenu tout seul, en fiches dans le chateau
    memoire: memoire(r),
    // la voix, en local : l'oreille (Whisper installe) et la parole (le serveur Pocket TTS repond)
    voix: { oreille: !!(etatVoix && etatVoix.oreille), parole: !!(etatVoix && etatVoix.parole) },
    cle_ok: r.cle.length >= 16,
    adresse_publique: pub,
    // le lien du QR code : la cle est dans le « # », que le navigateur du telephone n'envoie jamais sur le reseau
    lien_telephone: pret ? pub + '/telephone#k=' + encodeURIComponent(r.cle) : '',
    code_telephone: pret ? codeCourt(r.cle) : '',
    apk: fs.existsSync(path.join(r.depot, 'appli', 'Archi.apk')),
    // heures (ms) du dernier passage de chaque etape a la porte du telephone, 0 = jamais ; « maintenant » = l'heure du PC
    telephone: Object.assign({ maintenant: Date.now() }, suivi || nouveauSuivi()),
    outils: outils(r),
    chantiers: chantiers(r),
    n8n_url: 'http://127.0.0.1:' + r.n8nPort,
  };
}

const CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'";
// Les fichiers de la page d'accueil, servis depuis ce dossier : une liste fermee (aucun chemin ne vient de la demande).
const FICHIERS_PAGE = {
  '/qrcode.js': ['qrcode.js', 'text/javascript; charset=utf-8'],
  '/sphere.js': ['sphere.js', 'text/javascript; charset=utf-8'],     // la sphere d'Archi, comme sur le telephone
  '/ecoute.js': ['ecoute.js', 'text/javascript; charset=utf-8'],     // le micro continu et son mot magique
  '/logo.js': ['logo.js', 'text/javascript; charset=utf-8'],         // le mot Archi s'ecrit avec son logo
  '/polices/fraunces.woff2': ['polices/fraunces.woff2', 'font/woff2'],
  '/polices/fraunces-italique.woff2': ['polices/fraunces-italique.woff2', 'font/woff2'],
  '/polices/nunito.woff2': ['polices/nunito.woff2', 'font/woff2'],
};
let fileEcoute = Promise.resolve();   // une transcription a la fois : Whisper prend tous les coeurs du processeur
function fichier(res, nom, type, extra) {
  try {
    repondre(res, 200, fs.readFileSync(path.join(ICI, nom)), type, Object.assign({ 'Content-Security-Policy': CSP, 'X-Frame-Options': 'DENY' }, extra || {}));
  } catch (e) { repondre(res, 500, 'fichier manquant : ' + nom); }
}

function enveloppe(traiter) {
  return http.createServer(async (req, res) => {
    try { await traiter(req, res, String(req.url || '/').split('?')[0], req.method || 'GET'); }
    catch (e) {
      if (!res.headersSent) repondre(res, e && e.message === 'trop gros' ? 413 : 500, 'Erreur.');
      else res.end();
    }
  });
}

// ---------------------------------------------------------------- 1. la page d'accueil (navigateur du PC)
function creerServeurLocal(r, suivi) {
  return enveloppe(async (req, res, chemin, methode) => {
    // un relais, un autre nom d'hote (page piegee, DNS rebinding) : cette porte n'existe pas pour eux
    if (!estLocal(req, r.port)) return repondre(res, 404, 'Introuvable.');
    if (methode === 'GET' && (chemin === '/' || chemin === '/index.html')) return fichier(res, 'accueil.html', 'text/html; charset=utf-8');
    if (methode === 'GET' && Object.prototype.hasOwnProperty.call(FICHIERS_PAGE, chemin)) {
      const [nom, type] = FICHIERS_PAGE[chemin];
      // les polices ne changent jamais : le navigateur peut les garder (le reste n'est jamais mis en cache)
      return fichier(res, nom, type, type === 'font/woff2' ? { 'Cache-Control': 'max-age=604800, immutable' } : null);
    }
    if (methode === 'GET' && chemin === '/telephone') return fichier(res, 'telephone.html', 'text/html; charset=utf-8');
    if (chemin.startsWith('/api/')) {
      if (!appelDeLaPage(req, r.port)) return json(res, 403, { erreur: 'appel refuse' });
      if (methode === 'GET' && chemin === '/api/etat') return json(res, 200, await etat(r, suivi));
      if (methode === 'POST' && chemin === '/api/ecouter') {
        // le micro continu : une phrase a transcrire sur ce PC (whisper.cpp). Rien n'est envoye a l'agent ici :
        // la page met les phrases bout a bout et n'envoie le message qu'au mot magique.
        const son = await lireCorps(req, 6 * 1024 * 1024);
        if (son.length < 800) return json(res, 200, { ok: false, raison: 'rien_entendu' });
        const type = String(req.headers['content-type'] || '');
        const ext = /ogg/.test(type) ? '.ogg' : /mp4|m4a/.test(type) ? '.m4a' : /wav/.test(type) ? '.wav' : '.webm';
        const f = path.join(os.tmpdir(), 'archi_question_' + crypto.randomBytes(6).toString('hex') + ext);
        const transcrire = r.transcrire || (x => voix.transcrire(x, r.voix));
        const tour = fileEcoute.then(async () => {
          try { fs.writeFileSync(f, son); return await transcrire(f); }
          catch (e) { return { ok: false, raison: 'erreur_oreille' }; }
          finally { try { fs.unlinkSync(f); } catch (e) { /* deja efface */ } }
        });
        fileEcoute = tour.catch(() => null);
        return json(res, 200, await tour);
      }
      if (methode === 'POST' && chemin === '/api/message') {
        return relayer(req, res, r, '/webhook/telephone-archi', await lireCorps(req, MAX_CORPS), { 'x-archi-cle': r.cle });
      }
      if (methode === 'POST' && chemin === '/api/annonces') {
        // les rappels du planificateur, comme pour l'appli (sans accuse de reception : le telephone les recoit aussi)
        return relayer(req, res, r, '/webhook/telephone-boite', Buffer.from('{}'), { 'x-archi-cle': r.cle, 'content-type': 'application/json' });
      }
    }
    return repondre(res, 404, 'Introuvable.');
  });
}

// ---------------------------------------------------------------- 2. la porte du telephone (cible du tunnel)
function creerServeurPorte(r, suivi) {
  suivi = suivi || nouveauSuivi();
  return enveloppe(async (req, res, chemin, methode) => {
    const route = routePublique(methode, chemin, req.headers, r);
    noterPassage(r, suivi, methode, chemin, route, req.headers);
    if (route.action === 'essai') {
      await lireCorps(req, 4096);
      const [n8n, lm] = await Promise.all([voir('http://127.0.0.1:' + r.n8nPort + '/healthz', 2500), voir(r.lmUrl + '/models', 2500)]);
      return json(res, 200, { ok: true, agent: !!(n8n && n8n.code === 200), cerveau: !!lm });
    }
    if (route.action === 'page') return fichier(res, 'telephone.html', 'text/html; charset=utf-8');
    if (route.action === 'apk') {
      const apk = path.join(r.depot, 'appli', 'Archi.apk');
      if (!fs.existsSync(apk)) return repondre(res, 404, "L'appli n'est pas sur ce PC.");
      res.writeHead(200, { 'Content-Type': 'application/vnd.android.package-archive', 'Content-Length': fs.statSync(apk).size,
        'Content-Disposition': 'attachment; filename="Archi.apk"', 'X-Content-Type-Options': 'nosniff' });
      return fs.createReadStream(apk).pipe(res);
    }
    if (route.action === 'relayer') return relayer(req, res, r, chemin, await lireCorps(req, route.max));
    if (route.code === 403) await new Promise(x => setTimeout(x, 400));   // mauvaise cle : on ne repond pas a toute vitesse
    return repondre(res, route.code, route.code === 403 ? 'Cle refusee.' : 'Introuvable.');
  });
}

// ---------------------------------------------------------------- le chien de garde
/** Quand le lanceur disparait, on arrete les aides notees dans pids.txt (tunnel, serveur), puis soi-meme. */
function surveillerLanceur(pid, r, sortir) {
  const vivant = () => { try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; } };
  return setInterval(() => {
    if (vivant()) return;
    try {
      for (const ligne of fs.readFileSync(path.join(r.etat, 'pids.txt'), 'utf8').split(/\r?\n/)) {
        const p = parseInt(ligne.trim(), 10);
        if (p && p !== process.pid) { try { process.kill(p); } catch (e) { /* deja arrete */ } }
      }
    } catch (e) { /* pas de fichier : rien a arreter */ }
    try { fs.unlinkSync(path.join(r.etat, 'adresse_publique.txt')); } catch (e) { /* deja absent */ }
    sortir();
  }, 3000);
}

if (require.main === module) {
  const r = reglages();
  const demarrer = (serveur, port, nom) => {
    serveur.requestTimeout = DELAI_AGENT_MS;
    serveur.headersTimeout = 30000;
    serveur.on('error', e => { console.error(nom + ' : ' + (e.code === 'EADDRINUSE' ? 'le port ' + port + ' est deja pris.' : e.message)); process.exit(1); });
    // 127.0.0.1 seulement : ni le reseau local ni Internet n'arrivent ici, sauf par le tunnel (porte du telephone)
    serveur.listen(port, '127.0.0.1', () => console.log(nom + ' : 127.0.0.1:' + port));
  };
  const suivi = nouveauSuivi();
  demarrer(creerServeurLocal(r, suivi), r.port, "Page d'accueil");
  demarrer(creerServeurPorte(r, suivi), r.portPorte, 'Porte du telephone');
  const lanceur = parseInt(process.env.ARCHI_PID_LANCEUR || '0', 10);
  if (lanceur > 0) surveillerLanceur(lanceur, r, () => process.exit(0));
}

module.exports = { reglages, estLocal, appelDeLaPage, routePublique, memeCle, telegramAttendu, codeCourt, creerServeurLocal, creerServeurPorte,
  surveillerLanceur, adressePublique, outils, chantiers, nouveauSuivi, noterPassage, memoire };
