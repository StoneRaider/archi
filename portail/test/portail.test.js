// Tests du portail : deux portes separees. La porte du telephone (cible du tunnel) ne connait qu'une LISTE BLANCHE ;
// la page d'accueil n'existe que pour le navigateur du PC.
//   node --test portail/test/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');
const P = require('../portail.js');

const CLE = 'cle-de-test-abcdefghijklmnop';
const TG = { workflow_id: 'ArchiDemo0000001', node_id: '6d1f0c1e-aaaa-4bbb-8ccc-fedcbafedcba', webhook_id: '9a8b7c6d-dddd-4eee-8fff-abcdefabcdef' };
const JETON_TG = TG.workflow_id + '_' + TG.node_id;
const CHEMIN_TG = '/webhook/' + TG.webhook_id + '/webhook';

function faux(headers, adresse) {
  return { headers: headers || {}, socket: { remoteAddress: adresse || '127.0.0.1' } };
}
/** un faux chateau, avec (ou sans) le fichier qui decrit le webhook Telegram de l'installation */
function chateau(avecTelegram) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'archi_portail_'));
  if (avecTelegram) {
    fs.mkdirSync(path.join(d, '.workflows_archi_importes'));
    fs.writeFileSync(path.join(d, '.workflows_archi_importes', 'telegram.json'), JSON.stringify(TG));
  }
  return d;
}

test('estLocal : seulement le navigateur du PC, sans relais', () => {
  assert.equal(P.estLocal(faux({ host: '127.0.0.1:5680' }), 5680), true);
  assert.equal(P.estLocal(faux({ host: 'localhost:5680' }), 5680), true);
  assert.equal(P.estLocal(faux({ host: 'LOCALHOST:5680' }), 5680), true);
  assert.equal(P.estLocal(faux({ host: 'abc-def.trycloudflare.com' }), 5680), false);
  assert.equal(P.estLocal(faux({ host: '127.0.0.1:5680', 'cf-ray': 'x' }), 5680), false);
  assert.equal(P.estLocal(faux({ host: '127.0.0.1:5680', 'x-forwarded-for': '1.2.3.4' }), 5680), false);
  assert.equal(P.estLocal(faux({ host: '127.0.0.1:5680', forwarded: 'for=1.2.3.4' }), 5680), false);
  // une page piegee qui fait pointer son nom de domaine sur 127.0.0.1 (DNS rebinding)
  assert.equal(P.estLocal(faux({ host: 'pirate.exemple.net:5680' }), 5680), false);
  assert.equal(P.estLocal(faux({ host: '127.0.0.1:9999' }), 5680), false);
  assert.equal(P.estLocal(faux({ host: '127.0.0.1:5680' }, '192.168.1.20'), 5680), false);
  assert.equal(P.estLocal(faux({}), 5680), false);
});

test('appelDeLaPage : meme origine et en-tete maison', () => {
  const ok = { host: '127.0.0.1:5680', 'x-archi-portail': '1' };
  assert.equal(P.appelDeLaPage(faux(ok), 5680), true);
  assert.equal(P.appelDeLaPage(faux(Object.assign({}, ok, { origin: 'http://127.0.0.1:5680', 'sec-fetch-site': 'same-origin' })), 5680), true);
  assert.equal(P.appelDeLaPage(faux({ host: '127.0.0.1:5680' }), 5680), false, 'sans en-tete maison');
  assert.equal(P.appelDeLaPage(faux(Object.assign({}, ok, { origin: 'https://pirate.exemple.net' })), 5680), false);
  assert.equal(P.appelDeLaPage(faux(Object.assign({}, ok, { origin: 'null' })), 5680), false);
  assert.equal(P.appelDeLaPage(faux(Object.assign({}, ok, { 'sec-fetch-site': 'cross-site' })), 5680), false);
  assert.equal(P.appelDeLaPage(faux(Object.assign({}, ok, { 'sec-fetch-site': 'same-site' })), 5680), false);
});

test('routePublique : liste blanche', () => {
  const r = { cle: CLE, telegram: false, base: chateau(false) };
  const route = (m, c, h) => P.routePublique(m, c, h || {}, r);
  assert.deepEqual(route('GET', '/telephone'), { action: 'page' });
  assert.deepEqual(route('GET', '/Archi.apk'), { action: 'apk' });
  assert.equal(route('POST', '/webhook/telephone-archi', { 'x-archi-cle': CLE }).action, 'relayer');
  assert.equal(route('POST', '/webhook/telephone-boite', { 'x-archi-cle': CLE }).action, 'relayer');
  assert.equal(route('POST', '/webhook/telephone-archi').code, 403, 'sans cle');
  assert.equal(route('POST', '/webhook/telephone-archi', { 'x-archi-cle': CLE + 'x' }).code, 403, 'mauvaise cle');
  for (const [m, c] of [['GET', '/'], ['GET', '/api/etat'], ['POST', '/api/message'], ['GET', '/rest/login'], ['POST', '/rest/owner/setup'],
    ['GET', '/webhook/telephone-archi'], ['POST', '/webhook-test/telephone-archi'], ['POST', '/webhook/autre'], ['GET', '/qrcode.js'],
    ['POST', '/webhook/../rest/login'], ['POST', '/webhook/telephone-archi/../../rest'], ['POST', '/webhook//telephone-archi'],
    ['POST', '/webhook/%2e%2e/rest'], ['POST', '/form/x'], ['DELETE', '/webhook/telephone-archi'], ['GET', '/healthz'], ['GET', '/.env'],
    ['POST', CHEMIN_TG]]) {
    assert.equal(route(m, c, { 'x-archi-cle': CLE, 'x-telegram-bot-api-secret-token': JETON_TG }).code, 404, m + ' ' + c);
  }
  assert.equal(route('POST', '/webhook/' + 'a'.repeat(400), { 'x-archi-cle': CLE }).code, 404);
  fs.rmSync(r.base, { recursive: true, force: true });
});

test('routePublique : Telegram = le chemin ET le jeton de cette installation, rien d\'autre', () => {
  const base = chateau(true);
  const r = { cle: CLE, telegram: true, base };
  const jeton = j => ({ 'x-telegram-bot-api-secret-token': j });
  assert.deepEqual(P.telegramAttendu(r), { chemin: CHEMIN_TG, jeton: JETON_TG });
  assert.equal(P.routePublique('POST', CHEMIN_TG, jeton(JETON_TG), r).action, 'relayer');
  assert.ok(P.routePublique('POST', CHEMIN_TG, jeton(JETON_TG), r).max <= 1024 * 1024, 'un message Telegram est petit');
  assert.equal(P.routePublique('POST', CHEMIN_TG, jeton('x'), r).code, 403, 'un jeton quelconque ne suffit pas');
  assert.equal(P.routePublique('POST', CHEMIN_TG, {}, r).code, 403, 'sans jeton');
  // le jeton d'origine du depot (identifiants fixes, donc publics) ne vaut rien ici
  assert.equal(P.routePublique('POST', CHEMIN_TG, jeton('ArchiDemo0000001_10934613-221f-50f7-873f-627188e07a45'), r).code, 403);
  assert.equal(P.routePublique('POST', '/webhook/fd9aac3c-2628-5658-b6dc-d6246b35c35c/webhook', jeton(JETON_TG), r).code, 404, 'autre chemin');
  assert.equal(P.routePublique('POST', '/webhook/ArchiDemo0000001/telegram/webhook', jeton(JETON_TG), r).code, 404);
  // bot non branche : la route n'existe pas
  assert.equal(P.routePublique('POST', CHEMIN_TG, jeton(JETON_TG), { cle: CLE, telegram: false, base }).code, 404);
  // fichier absent ou abime : la route n'existe pas
  const vide = chateau(false);
  assert.equal(P.routePublique('POST', CHEMIN_TG, jeton(JETON_TG), { cle: CLE, telegram: true, base: vide }).code, 404);
  fs.writeFileSync(path.join(base, '.workflows_archi_importes', 'telegram.json'), JSON.stringify({ workflow_id: 'x', node_id: '../..', webhook_id: 'court' }));
  assert.equal(P.telegramAttendu(r), null);
  fs.rmSync(base, { recursive: true, force: true });
  fs.rmSync(vide, { recursive: true, force: true });
});

test('memeCle : refuse une cle attendue trop courte ou vide', () => {
  assert.equal(P.memeCle('abc', 'abc'), false);
  assert.equal(P.memeCle('', ''), false);
  assert.equal(P.memeCle(undefined, CLE), false);
  assert.equal(P.memeCle(CLE, CLE), true);
});

test('codeCourt : 4 caracteres, stables, differents d\'une cle a l\'autre', () => {
  assert.match(P.codeCourt(CLE), /^[0-9A-F]{4}$/);
  assert.equal(P.codeCourt(CLE), P.codeCourt(CLE));
  assert.notEqual(P.codeCourt(CLE), P.codeCourt(CLE + 'x'));
});

test('adressePublique : https et un nom d\'hote, rien d\'autre', () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'archi_portail_'));
  const f = path.join(d, 'adresse_publique.txt');
  const lire = t => { fs.writeFileSync(f, t); return P.adressePublique({ etat: d }); };
  assert.equal(lire('https://abc-def.trycloudflare.com\n'), 'https://abc-def.trycloudflare.com');
  assert.equal(lire('https://abc-def.trycloudflare.com/'), 'https://abc-def.trycloudflare.com');
  assert.equal(lire('http://abc.exemple.net'), '');
  assert.equal(lire('https://abc.exemple.net/chemin?x=1'), '');
  assert.equal(lire('https://a"onmouseover=x'), '');
  assert.equal(P.adressePublique({ etat: path.join(d, 'absent') }), '');
  fs.rmSync(d, { recursive: true, force: true });
});

// ---------------------------------------------------------------- de bout en bout, avec un faux n8n
function appel(port, options, corps) {
  return new Promise((ok, non) => {
    const req = http.request(Object.assign({ host: '127.0.0.1', port, agent: false }, options), rep => {
      const m = [];
      rep.on('data', x => m.push(x));
      rep.on('end', () => ok({ code: rep.statusCode, entetes: rep.headers, corps: Buffer.concat(m).toString('utf8') }));
    });
    req.on('error', non);
    req.end(corps || undefined);
  });
}
const fermer = s => new Promise(x => { s.close(x); if (s.closeAllConnections) s.closeAllConnections(); });

test('de bout en bout : la porte du telephone ne connait que la liste blanche, la page reste locale', async () => {
  const recus = [];
  const n8n = http.createServer((req, res) => {
    const m = [];
    req.on('data', x => m.push(x));
    req.on('end', () => {
      // la sonde du portail (« le workflow est-il active ? ») : un GET sur le webhook, auquel le vrai n8n repond 404
      if (req.method === 'GET' && req.url === '/webhook/telephone-archi') {
        res.writeHead(404, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ code: 404, message: 'This webhook is not registered for GET requests. Did you mean to make a POST request?' }));
      }
      recus.push({ url: req.url, cle: req.headers['x-archi-cle'], corps: Buffer.concat(m).toString('utf8'), hote: req.headers.host, entetes: req.headers });
      if (req.url === '/healthz') { res.writeHead(200); return res.end('ok'); }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ texte: 'reponse du faux n8n' }));
    });
  });
  await new Promise(x => n8n.listen(0, '127.0.0.1', x));
  const d = chateau(true);
  fs.writeFileSync(path.join(d, 'adresse_publique.txt'), 'https://abc-def.trycloudflare.com');
  fs.mkdirSync(path.join(d, 'outils'));
  fs.writeFileSync(path.join(d, 'outils', 'registre.json'), JSON.stringify({
    planificateur: { description: 'MODE D EMPLOI : faire quelque chose PLUS TARD. action=ajouter' }, lire_pdf: { description: 'lit un PDF. action=lire', sensible: true } }));
  const r = { port: 0, portPorte: 0, n8nPort: n8n.address().port, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: 'Camille', telegram: true };
  const local = P.creerServeurLocal(r), porte = P.creerServeurPorte(r);
  await new Promise(x => local.listen(0, '127.0.0.1', x));
  await new Promise(x => porte.listen(0, '127.0.0.1', x));
  r.port = local.address().port; r.portPorte = porte.address().port;
  const hLocal = { host: '127.0.0.1:' + r.port };
  const tunnel = { host: 'abc-def.trycloudflare.com', 'cf-ray': '1', 'cf-connecting-ip': '203.0.113.9', 'x-forwarded-for': '203.0.113.9' };
  // un relais qui ne signalerait rien (pas d'en-tete de relais, hote local) : la porte du telephone ne s'y fie pas
  const relaisMuet = { host: '127.0.0.1:' + r.portPorte };
  try {
    // --- la porte du telephone : meme sans aucun en-tete de relais, seule la liste blanche repond
    for (const h of [tunnel, relaisMuet]) {
      for (const chemin of ['/', '/api/etat', '/qrcode.js', '/rest/login', '/healthz', '/index.html']) {
        assert.equal((await appel(r.portPorte, { path: chemin, headers: h })).code, 404, 'porte GET ' + chemin);
      }
      assert.equal((await appel(r.portPorte, { path: '/api/etat', headers: Object.assign({ 'x-archi-portail': '1' }, h) })).code, 404);
      assert.equal((await appel(r.portPorte, { path: '/api/message', method: 'POST', headers: Object.assign({ 'x-archi-portail': '1' }, h) }, 'x')).code, 404);
      assert.equal((await appel(r.portPorte, { path: '/webhook/telephone-archi', method: 'POST', headers: h }, '{}')).code, 403);
      assert.equal((await appel(r.portPorte, { path: CHEMIN_TG, method: 'POST', headers: Object.assign({ 'x-telegram-bot-api-secret-token': 'x' }, h) }, '{}')).code, 403);
    }
    assert.equal(recus.length, 0, 'rien ne doit arriver a n8n sans la cle ou le bon jeton');
    const page = await appel(r.portPorte, { path: '/telephone', headers: tunnel });
    assert.equal(page.code, 200);
    assert.ok(!page.corps.includes(CLE), 'la page du telephone ne contient aucun secret');
    assert.equal((await appel(r.portPorte, { path: '/Archi.apk', headers: tunnel })).code, 404, 'pas d\'APK dans ce faux depot');
    const ok = await appel(r.portPorte, { path: '/webhook/telephone-archi', method: 'POST', headers: Object.assign({ 'x-archi-cle': CLE, 'content-type': 'application/json' }, tunnel) }, '{"texte":"salut"}');
    assert.equal(ok.code, 200);
    assert.equal(JSON.parse(ok.corps).texte, 'reponse du faux n8n');
    assert.equal(recus.length, 1);
    assert.equal(recus[0].url, '/webhook/telephone-archi');
    assert.equal(recus[0].corps, '{"texte":"salut"}');
    assert.equal(recus[0].hote, '127.0.0.1:' + r.n8nPort);
    assert.equal(recus[0].entetes['cf-connecting-ip'], undefined, 'les en-tetes du tunnel ne vont pas jusqu\'a n8n');
    const tg = await appel(r.portPorte, { path: CHEMIN_TG, method: 'POST', headers: Object.assign({ 'x-telegram-bot-api-secret-token': JETON_TG, 'content-type': 'application/json' }, tunnel) }, '{"update_id":1}');
    assert.equal(tg.code, 200);
    assert.equal(recus[recus.length - 1].url, CHEMIN_TG);

    // --- la page d'accueil : invisible pour le tunnel, pour une page piegee (DNS rebinding) et sans notre en-tete
    assert.equal((await appel(r.port, { path: '/', headers: tunnel })).code, 404);
    assert.equal((await appel(r.port, { path: '/telephone', headers: tunnel })).code, 404);
    assert.equal((await appel(r.port, { path: '/webhook/telephone-archi', method: 'POST', headers: Object.assign({ 'x-archi-cle': CLE }, tunnel) }, '{}')).code, 404);
    assert.equal((await appel(r.port, { path: '/', headers: { host: 'pirate.exemple.net:' + r.port } })).code, 404);
    assert.equal((await appel(r.port, { path: '/api/etat', headers: hLocal })).code, 403);
    assert.equal((await appel(r.port, { path: '/api/message', method: 'POST', headers: Object.assign({ origin: 'https://pirate.exemple.net', 'x-archi-portail': '1' }, hLocal) }, 'x')).code, 403);

    // --- le navigateur du PC
    const accueil = await appel(r.port, { path: '/', headers: hLocal });
    assert.equal(accueil.code, 200);
    assert.match(accueil.entetes['content-security-policy'], /frame-ancestors 'none'/);
    assert.ok(!accueil.corps.includes(CLE));
    const etat = JSON.parse((await appel(r.port, { path: '/api/etat', headers: Object.assign({ 'x-archi-portail': '1' }, hLocal) })).corps);
    assert.equal(etat.n8n, true);
    assert.equal(etat.cerveau.joignable, false);
    assert.equal(etat.utilisateur, 'Camille');
    assert.equal(etat.lien_telephone, 'https://abc-def.trycloudflare.com/telephone#k=' + CLE);
    assert.equal(etat.code_telephone, P.codeCourt(CLE));
    assert.deepEqual(etat.outils.map(o => o.nom), ['planificateur', 'lire_pdf']);
    assert.equal(etat.outils[0].quoi, 'faire quelque chose PLUS TARD');
    assert.equal(etat.outils[1].sensible, true);
    const avant = recus.length;
    const msg = await appel(r.port, { path: '/api/message', method: 'POST', headers: Object.assign({ 'x-archi-portail': '1', 'content-type': 'application/json' }, hLocal) }, '{"texte":"coucou"}');
    assert.equal(JSON.parse(msg.corps).texte, 'reponse du faux n8n');
    const dernier = recus[recus.length - 1];
    assert.equal(recus.length, avant + 1);
    assert.equal(dernier.url, '/webhook/telephone-archi');
    assert.equal(dernier.cle, CLE, 'le portail ajoute la cle cote PC');
    const boite = await appel(r.port, { path: '/api/annonces', method: 'POST', headers: Object.assign({ 'x-archi-portail': '1' }, hLocal) });
    assert.equal(boite.code, 200);
    assert.equal(recus[recus.length - 1].url, '/webhook/telephone-boite');
  } finally {
    await Promise.all([fermer(local), fermer(porte), fermer(n8n)]);
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test('n8n arrete : la page recoit une phrase claire, pas une erreur brute', async () => {
  const d = chateau(false);
  const r = { port: 0, portPorte: 0, n8nPort: 1, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: '', telegram: false };
  const local = P.creerServeurLocal(r);
  await new Promise(x => local.listen(0, '127.0.0.1', x));
  r.port = local.address().port;
  try {
    const rep = await appel(r.port, { path: '/api/message', method: 'POST', headers: { host: '127.0.0.1:' + r.port, 'x-archi-portail': '1' } }, '{}');
    assert.equal(rep.code, 502);
    assert.match(JSON.parse(rep.corps).texte, /n8n/);
  } finally { await fermer(local); fs.rmSync(d, { recursive: true, force: true }); }
});

test('chien de garde : quand le lanceur disparait, les aides sont arretees et l\'adresse publique effacee', async () => {
  const d = chateau(false);
  // deux processus qui dorment : le « lanceur » et une « aide » (comme le tunnel)
  const dort = () => cp.spawn(process.execPath, ['-e', 'setTimeout(() => {}, 60000)'], { stdio: 'ignore' });
  const lanceur = dort(), aide = dort();
  fs.writeFileSync(path.join(d, 'pids.txt'), aide.pid + '\n' + process.pid + '\n');   // notre propre PID ne doit jamais etre tue
  fs.writeFileSync(path.join(d, 'adresse_publique.txt'), 'https://abc-def.trycloudflare.com');
  const finAide = new Promise(x => aide.on('exit', x));
  let sorti = false;
  const minuteur = P.surveillerLanceur(lanceur.pid, { etat: d }, () => { sorti = true; clearInterval(minuteur); });
  try {
    await new Promise(x => setTimeout(x, 3500));
    assert.equal(sorti, false, 'tant que le lanceur vit, rien ne bouge');
    assert.ok(fs.existsSync(path.join(d, 'adresse_publique.txt')));
    lanceur.kill();
    await Promise.race([finAide, new Promise((_, non) => setTimeout(() => non(new Error('aide toujours en vie')), 9000))]);
    await new Promise(x => setTimeout(x, 300));
    assert.equal(sorti, true);
    assert.equal(fs.existsSync(path.join(d, 'adresse_publique.txt')), false);
  } finally {
    clearInterval(minuteur);
    try { lanceur.kill(); } catch (e) { /* deja arrete */ }
    try { aide.kill(); } catch (e) { /* deja arrete */ }
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test('appli : un seul nom interne, le meme dans Gradle, le manifeste, le passe-plat et la page du telephone', () => {
  const lire = f => fs.readFileSync(path.join(__dirname, '..', '..', f), 'utf8');
  const nom = (/applicationId\s*=\s*'([^']+)'/.exec(lire('appli/app/build.gradle')) || [])[1];
  assert.match(nom || '', /^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$/, 'applicationId introuvable dans build.gradle');
  // la version publique ne doit pas ecraser une autre appli Archi deja installee : son nom n'est pas celui des classes Java
  assert.notEqual(nom, (/namespace\s*=\s*'([^']+)'/.exec(lire('appli/app/build.gradle')) || [])[1]);
  assert.ok(lire('appli/app/src/main/AndroidManifest.xml').includes('android:authorities="' + nom + '.fichiers"'), 'manifeste');
  assert.ok(lire('appli/app/src/main/java/fr/archi/telephone/Fichiers.java').includes('AUTORITE = "' + nom + '.fichiers"'), 'Fichiers.java');
  // le bouton « Brancher l'appli » vise cette appli-la, et aucune autre
  const paquets = lire('portail/telephone.html').match(/package=[a-z0-9.]+;/g) || [];
  assert.deepEqual(paquets, ['package=' + nom + ';']);
});

test('porte : le suivi note chaque etape du telephone, le journal ne garde rien de sensible', async () => {
  const d = chateau(false);
  const r = { port: 0, portPorte: 0, n8nPort: 1, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: '', telegram: false };
  const suivi = P.nouveauSuivi();
  const porte = P.creerServeurPorte(r, suivi);
  await new Promise(x => porte.listen(0, '127.0.0.1', x));
  const appel = (methode, chemin, entetes, corps) => new Promise((ok, non) => {
    const q = http.request({ host: '127.0.0.1', port: porte.address().port, method: methode, path: chemin, headers: entetes || {} }, rep => {
      const m = []; rep.on('data', x => m.push(x)); rep.on('end', () => ok({ code: rep.statusCode, corps: Buffer.concat(m).toString('utf8') }));
    });
    q.on('error', non); q.end(corps || '');
  });
  const appli = { 'user-agent': 'ArchiTelephone/1.0', 'x-archi-essai': '1', 'content-type': 'application/json' };
  try {
    assert.deepEqual(suivi, { page: 0, apk: 0, appli: 0, refus: 0 });
    // 1. la page s'ouvre sur le telephone (y compris au retour « appli absente »). Le verificateur du PC, lui, ne coche rien.
    assert.equal((await appel('GET', '/telephone', { 'user-agent': 'Mozilla/5.0 (Windows NT) WindowsPowerShell/5.1' })).code, 200);
    assert.equal(suivi.page, 0);
    assert.equal((await appel('GET', '/telephone?absente=1', { 'user-agent': 'Mozilla/5.0 (Linux; Android 14) Chrome/130 Mobile Safari/537' })).code, 200);
    assert.ok(suivi.page > 0 && suivi.appli === 0);
    // 2. mauvaise cle : notee comme un refus, jamais comme une appli branchee
    assert.equal((await appel('POST', '/webhook/telephone-boite', Object.assign({ 'x-archi-cle': 'mauvaise-cle-abcdefghij' }, appli), '{}')).code, 403);
    assert.ok(suivi.refus > 0 && suivi.appli === 0);
    // 3. l'essai de liaison de l'appli : la porte repond elle-meme (n8n et LM Studio sont eteints ici), l'appli est « branchee »
    const e = await appel('POST', '/webhook/telephone-boite', Object.assign({ 'x-archi-cle': CLE }, appli), '{}');
    assert.equal(e.code, 200);
    assert.deepEqual(JSON.parse(e.corps), { ok: true, agent: false, cerveau: false });
    assert.ok(suivi.appli > 0);
    // un autre programme qui a la bonne cle (le verificateur) ne fait pas croire a un telephone branche
    const autre = P.nouveauSuivi();
    P.noterPassage(r, autre, 'POST', '/webhook/telephone-boite', { action: 'relayer' }, { 'user-agent': 'PowerShell' });
    P.noterPassage(r, autre, 'GET', '/Archi.apk', { action: 'apk' }, { 'user-agent': 'curl/8' });
    assert.deepEqual(autre, { page: 0, apk: 0, appli: 0, refus: 0 });
    P.noterPassage(r, autre, 'GET', '/Archi.apk', { action: 'apk' }, { 'user-agent': 'AndroidDownloadManager/14 (Linux; U; Android 14)' });
    assert.ok(autre.apk > 0);
    // le journal : l'heure, la methode, un chemin connu, le resultat. Ni cle, ni parametres, ni chemin inconnu.
    await appel('GET', '/fouille-' + CLE);
    await new Promise(x => setTimeout(x, 400));
    const journal = fs.readFileSync(path.join(d, 'porte.log'), 'utf8');
    assert.ok(journal.includes('GET /telephone page'), journal);
    assert.ok(journal.includes('POST /webhook/telephone-boite 403'), journal);
    assert.ok(journal.includes('POST /webhook/telephone-boite essai appli'), journal);
    assert.ok(journal.includes('GET (autre) 404'), journal);
    assert.ok(!journal.includes(CLE) && !journal.includes('absente') && !journal.includes('mauvaise') && !journal.includes('fouille'));
  } finally {
    porte.close();
    await new Promise(x => setTimeout(x, 100));
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test('page du telephone : si l appli est absente, le bouton ramene a la page avec un avertissement', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'telephone.html'), 'utf8');
  assert.ok(page.includes('S.browser_fallback_url='));
  assert.ok(page.includes("/telephone?absente=1#k="), 'la cle reste dans le # du lien de retour');
  assert.ok(page.includes('id="absente"'));
});

test('etat : la memoire compte les fiches et montre les derniers faits retenus', () => {
  const d = chateau(false);
  try {
    assert.deepEqual(P.memoire({ base: d }), { fiches: 0, faits: 0, derniers: [] });
    fs.mkdirSync(path.join(d, 'memoire', 'personnes'), { recursive: true });
    fs.mkdirSync(path.join(d, 'memoire', 'preferences'), { recursive: true });
    fs.writeFileSync(path.join(d, 'memoire', 'personnes', 'medor.md'), '# Médor\n\n**Pièce :** personnes\n**Faits :**\n- (10/11/2026) Médor est le chien de Camille.\n- (10/11/2026) Médor a huit ans.\n');
    fs.writeFileSync(path.join(d, 'memoire', 'preferences', 'archi_et_moi.md'), '## x\n**Faits :**\n- Camille aime le court.\n**Hypothèses :**\n- pas un fait\n');
    fs.writeFileSync(path.join(d, 'memoire', 'personnes', 'vide.md'), '# sans fait\n');
    fs.writeFileSync(path.join(d, 'memoire', '.retenu.jsonl'), 'ligne abimee\n' + JSON.stringify({ quand: 1700000000000, piece: 'personnes', sujet: 'Médor', fait: 'Médor a huit ans.' }) + '\n');
    assert.deepEqual(P.memoire({ base: d }), { fiches: 2, faits: 3, derniers: [{ quand: 1700000000000, fait: 'Médor a huit ans.' }] });
  } finally { fs.rmSync(d, { recursive: true, force: true }); }
});

test('porte : seule l appli declenche l alerte « mauvaise cle », et les robots ne remplissent pas le journal', async () => {
  const d = chateau(false);
  const r = { etat: d };
  const suivi = P.nouveauSuivi();
  try {
    // le verificateur du PC (ou un curieux) recoit 403 sans faire croire a une appli mal branchee
    P.noterPassage(r, suivi, 'POST', '/webhook/telephone-archi', { action: 'refuser', code: 403 }, { 'user-agent': 'Mozilla/5.0 WindowsPowerShell/5.1' });
    assert.equal(suivi.refus, 0);
    P.noterPassage(r, suivi, 'POST', '/webhook/telephone-archi', { action: 'refuser', code: 403 }, { 'user-agent': 'ArchiTelephone/1.0' });
    assert.ok(suivi.refus > 0);
    for (let i = 0; i < 80; i++) P.noterPassage(r, suivi, 'GET', '/robot' + i, { action: 'refuser', code: 404 }, {});
    await new Promise(x => setTimeout(x, 600));
    const lignes = fs.readFileSync(path.join(d, 'porte.log'), 'utf8').split('\n').filter(l => l.includes('(autre) 404'));
    assert.ok(lignes.length >= 1 && lignes.length <= 40, lignes.length + ' lignes pour 80 demandes');   // 20 par minute
    assert.deepEqual(Object.keys(suivi).sort(), ['apk', 'appli', 'page', 'refus'], 'le compteur ne fuit pas dans /api/etat');
  } finally { fs.rmSync(d, { recursive: true, force: true }); }
});

test('page d accueil : le micro ne peut pas s ouvrir deux fois, et il est toujours rendu', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  const micro = page.slice(page.indexOf('async function ouvrirMicro()'), page.indexOf('function grandir()'));
  assert.ok(micro.length > 200 && micro.includes('if (microEnOuverture) return;'), 'drapeau pose avant la demande d autorisation');
  assert.ok(micro.indexOf('microEnOuverture = true') < micro.indexOf('getUserMedia'));
  assert.ok(micro.includes('finally { microEnOuverture = false; }'));
  assert.ok(micro.includes('rendre();   // l\'enregistreur n\'a pas pu demarrer'), 'le micro est rendu si le demarrage echoue');
  const fermer = page.slice(page.indexOf('function fermerMicro()'), page.indexOf('async function ouvrirMicro()'));
  assert.ok(fermer.includes('m.flux.getTracks().forEach(t => t.stop())') && fermer.includes('m.contexte.close()'), 'le micro est rendu a la fermeture');
  // pendant qu'Archi reflechit ou parle, on n'ecoute pas : il ne doit pas s'entendre lui-meme
  assert.ok(page.includes('if (occupe || lecteur) { if (m.enregistreur) couper(m, false); return; }'));
});

test('etat : « agent pret » seulement quand le workflow est active, pas des que n8n repond', async () => {
  // un faux n8n : en bonne sante tout de suite, mais son webhook n'est enregistre qu'apres « activation »
  let active = false;
  const n8n = http.createServer((req, res) => {
    if (req.url === '/healthz') { res.writeHead(200); return res.end('{"status":"ok"}'); }
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ code: 404, message: active
      ? 'This webhook is not registered for GET requests. Did you mean to make a POST request?'
      : 'The requested webhook "GET telephone-archi" is not registered.' }));
  });
  await new Promise(x => n8n.listen(0, '127.0.0.1', x));
  const d = chateau(false);
  const r = { port: 0, portPorte: 0, n8nPort: n8n.address().port, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: '', telegram: false };
  const local = P.creerServeurLocal(r);
  await new Promise(x => local.listen(0, '127.0.0.1', x));
  r.port = local.address().port;
  const etat = () => new Promise((ok, non) => {
    http.get({ host: '127.0.0.1', port: r.port, path: '/api/etat', headers: { 'X-Archi-Portail': '1' } }, rep => {
      const m = []; rep.on('data', x => m.push(x)); rep.on('end', () => ok(JSON.parse(Buffer.concat(m).toString('utf8'))));
    }).on('error', non);
  });
  try {
    assert.equal((await etat()).n8n, false, 'n8n repond, mais le workflow n est pas encore active : un message se perdrait');
    active = true;
    assert.equal((await etat()).n8n, true);
    const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
    assert.ok(page.includes("if (!pret) { note('souci', 'Archi finit de démarrer"), 'la page n envoie rien tant que ce n est pas pret');
  } finally {
    local.close(); n8n.close();
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test('page d accueil : sphere, mot magique et polices sont servis au PC seulement, jamais par la porte du telephone', async () => {
  const d = chateau(false);
  const r = { port: 0, portPorte: 0, n8nPort: 1, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: '', telegram: false };
  const local = P.creerServeurLocal(r), porte = P.creerServeurPorte(r);
  await new Promise(x => local.listen(0, '127.0.0.1', x));
  await new Promise(x => porte.listen(0, '127.0.0.1', x));
  r.port = local.address().port;
  const voir = (serveur, chemin) => new Promise((ok, non) => {
    http.get({ host: '127.0.0.1', port: serveur.address().port, path: chemin, headers: serveur === local ? { host: '127.0.0.1:' + r.port } : {} }, rep => {
      const m = []; rep.on('data', x => m.push(x)); rep.on('end', () => ok({ code: rep.statusCode, type: rep.headers['content-type'], cache: rep.headers['cache-control'], corps: Buffer.concat(m) }));
    }).on('error', non);
  });
  try {
    for (const [chemin, type, debut] of [['/sphere.js', 'text/javascript', '// sphere.js'], ['/ecoute.js', 'text/javascript', '// ecoute.js'],
      ['/polices/fraunces.woff2', 'font/woff2', 'wOF2'], ['/polices/fraunces-italique.woff2', 'font/woff2', 'wOF2'], ['/polices/nunito.woff2', 'font/woff2', 'wOF2']]) {
      const f = await voir(local, chemin);
      assert.equal(f.code, 200, chemin);
      assert.ok(String(f.type).startsWith(type), chemin + ' : ' + f.type);
      assert.ok(f.corps.toString('latin1').startsWith(debut), chemin);
      assert.equal((await voir(porte, chemin)).code, 404, chemin + ' ne sort pas du PC');
    }
    assert.match((await voir(local, '/polices/nunito.woff2')).cache, /max-age/);
    // aucun chemin ne vient de la demande : pas de fichier hors de la liste
    for (const chemin of ['/polices/../portail.js', '/polices/OFL-Nunito.txt', '/portail.js', '/polices/', '/sphere.js/..%2f..%2f.env']) {
      assert.equal((await voir(local, chemin)).code, 404, chemin);
    }
    // la page n'appelle aucun autre site : polices et scripts viennent du PC
    const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
    assert.doesNotMatch(page, /https?:\/\/(?!www\.w3\.org)[a-z0-9.-]+\.[a-z]{2,}/i, 'aucune adresse exterieure dans la page');
    assert.ok(page.includes('url("/polices/fraunces.woff2")') && page.includes('<script src="/sphere.js">') && page.includes('<script src="/ecoute.js">'));
  } finally {
    local.close(); porte.close();
    await new Promise(x => setTimeout(x, 200));   // la porte finit d'ecrire son journal dans ce dossier
    fs.rmSync(d, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
});

test('micro continu : /api/ecouter transcrit une phrase sur le PC, pour la page seulement, sans rien garder', async () => {
  const d = chateau(false);
  const vus = [];
  const r = { port: 0, portPorte: 0, n8nPort: 1, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: '', telegram: false,
    transcrire: async f => { vus.push({ f, existe: fs.existsSync(f), taille: fs.statSync(f).size }); return { ok: true, texte: 'Bonjour Archi. Fin de transmission.' }; } };
  const local = P.creerServeurLocal(r), porte = P.creerServeurPorte(r);
  await new Promise(x => local.listen(0, '127.0.0.1', x));
  await new Promise(x => porte.listen(0, '127.0.0.1', x));
  r.port = local.address().port;
  const envoyer = (serveur, entetes, corps) => new Promise((ok, non) => {
    const q = http.request({ host: '127.0.0.1', port: serveur.address().port, method: 'POST', path: '/api/ecouter',
      headers: Object.assign(serveur === local ? { host: '127.0.0.1:' + r.port } : {}, entetes) }, rep => {
      const m = []; rep.on('data', x => m.push(x)); rep.on('end', () => ok({ code: rep.statusCode, corps: Buffer.concat(m).toString('utf8') }));
    });
    q.on('error', non); q.end(corps);
  });
  const son = Buffer.alloc(4000, 7);
  try {
    const bon = await envoyer(local, { 'X-Archi-Portail': '1', 'Content-Type': 'audio/webm;codecs=opus' }, son);
    assert.equal(bon.code, 200);
    assert.deepEqual(JSON.parse(bon.corps), { ok: true, texte: 'Bonjour Archi. Fin de transmission.' });
    assert.equal(vus.length, 1);
    assert.ok(vus[0].existe && vus[0].taille === 4000 && vus[0].f.endsWith('.webm') && path.dirname(vus[0].f) === os.tmpdir(), JSON.stringify(vus[0]));
    assert.equal(fs.existsSync(vus[0].f), false, 'le son est efface aussitot transcrit');
    // un bout de silence n'est pas transcrit
    assert.deepEqual(JSON.parse((await envoyer(local, { 'X-Archi-Portail': '1' }, Buffer.alloc(100))).corps), { ok: false, raison: 'rien_entendu' });
    assert.equal(vus.length, 1);
    // une autre page web du navigateur, ou la porte du telephone : rien
    assert.equal((await envoyer(local, { 'Content-Type': 'audio/webm' }, son)).code, 403);
    assert.equal((await envoyer(local, { 'X-Archi-Portail': '1', Origin: 'https://exemple.invalid' }, son)).code, 403);
    assert.equal((await envoyer(porte, { 'X-Archi-Portail': '1', 'x-archi-cle': CLE }, son)).code, 404);
    assert.equal(vus.length, 1);
    // la transcription echoue : une raison, pas un plantage, et le fichier est efface quand meme
    r.transcrire = async f => { vus.push({ f }); throw new Error('whisper absent'); };
    assert.deepEqual(JSON.parse((await envoyer(local, { 'X-Archi-Portail': '1' }, son)).corps), { ok: false, raison: 'erreur_oreille' });
    assert.equal(fs.existsSync(vus[1].f), false);
  } finally {
    local.close(); porte.close();
    await new Promise(x => setTimeout(x, 200));   // la porte finit d'ecrire son journal dans ce dossier
    fs.rmSync(d, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
});
