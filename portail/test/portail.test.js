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

test('arret : la page raccroche (clic sur le coeur), le portail raccroche aussi cote n8n', async () => {
  let raccroche = null;
  const vu = new Promise(x => { raccroche = x; });
  // un faux n8n qui reflechit sans fin : il ne repond jamais, il note seulement quand on lui raccroche au nez
  const n8n = http.createServer((req, res) => { req.resume(); res.on('close', () => raccroche(true)); });
  await new Promise(x => n8n.listen(0, '127.0.0.1', x));
  const d = chateau(false);
  const r = { port: 0, portPorte: 0, n8nPort: n8n.address().port, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: 'Camille' };
  const local = P.creerServeurLocal(r);
  await new Promise(x => local.listen(0, '127.0.0.1', x));
  r.port = local.address().port;
  try {
    const req = http.request({ host: '127.0.0.1', port: r.port, agent: false, path: '/api/message', method: 'POST',
      headers: { host: '127.0.0.1:' + r.port, 'x-archi-portail': '1', 'content-type': 'application/json' } });
    req.on('error', () => {});
    req.end('{"texte":"une longue question"}');
    await new Promise(x => setTimeout(x, 300));
    req.destroy();   // ce que fait AbortController dans la page
    const ok = await Promise.race([vu, new Promise(x => setTimeout(() => x(false), 2000))]);
    assert.equal(ok, true, 'n8n doit voir la demande annulee');
  } finally {
    await fermer(local); await fermer(n8n);
    fs.rmSync(d, { recursive: true, force: true });
  }
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  assert.ok(page.includes("if (arretDemande) arretDemande.abort();") && page.includes('signal: arret.signal'));
});

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
    assert.deepEqual(P.memoire({ base: d }), { fiches: 0, faits: 0, derniers: [], lecons: 0, dernieres_lecons: [] });
    fs.mkdirSync(path.join(d, 'memoire', 'personnes'), { recursive: true });
    fs.mkdirSync(path.join(d, 'memoire', 'preferences'), { recursive: true });
    fs.writeFileSync(path.join(d, 'memoire', 'personnes', 'medor.md'), '# Médor\n\n**Pièce :** personnes\n**Faits :**\n- (10/11/2026) Médor est le chien de Camille.\n- (10/11/2026) Médor a huit ans.\n');
    fs.writeFileSync(path.join(d, 'memoire', 'preferences', 'archi_et_moi.md'), '## x\n**Faits :**\n- Camille aime le court.\n**Hypothèses :**\n- pas un fait\n');
    fs.writeFileSync(path.join(d, 'memoire', 'personnes', 'vide.md'), '# sans fait\n');
    fs.writeFileSync(path.join(d, 'memoire', '.retenu.jsonl'), 'ligne abimee\n' + JSON.stringify({ quand: 1700000000000, piece: 'personnes', sujet: 'Médor', fait: 'Médor a huit ans.' }) + '\n');
    assert.deepEqual(P.memoire({ base: d }), { fiches: 2, faits: 3, derniers: [{ quand: 1700000000000, fait: 'Médor a huit ans.', lecon: false }],
      lecons: 0, dernieres_lecons: [] });
    // les lecons : comptees a part (pas dans les souvenirs), les plus recentes d'abord ; marquees dans le journal
    fs.mkdirSync(path.join(d, 'memoire', 'lecons'), { recursive: true });
    fs.writeFileSync(path.join(d, 'memoire', 'lecons', 'lecons_archi.md'), '# Leçons apprises\n\n**Pièce :** lecons\n**Faits :**\n'
      + '- (10/11/2026) Tu ne sais pas envoyer de vocal.\n- (11/11/2026) Relis le lieu demandé.\n');
    fs.appendFileSync(path.join(d, 'memoire', '.retenu.jsonl'), JSON.stringify({ quand: 1700000000001, piece: 'lecons', sujet: 'lecons', fait: 'Relis le lieu demandé.' }) + '\n');
    const m = P.memoire({ base: d });
    assert.deepEqual([m.fiches, m.faits, m.lecons, m.dernieres_lecons], [2, 3, 2, ['Relis le lieu demandé.', 'Tu ne sais pas envoyer de vocal.']]);
    assert.deepEqual(m.derniers[1], { quand: 1700000000001, fait: 'Relis le lieu demandé.', lecon: true });
    // une fiche curee (en-tete, sources, prochaines etapes, liens) : seules les lignes des blocs « Faits » sont des lecons
    fs.writeFileSync(path.join(d, 'memoire', 'lecons', 'lecons_archi.md'), '---\ntype: lecon\n---\n## Ajout du 29/10/2026\r\n**Titre :** Leçons\r\n**Faits :**\r\n'
      + '- Lis la méthode avant l\'outil.\r\n**Hypothèses :**\r\n- Aucune\r\n## Ajout du 12/11/2026\r\n**Faits :**\r\n- Aucune\r\n- (12/11/2026) Ne dis pas « fait » sans retour.\r\n'
      + '**Sources :**\r\n- Carnet du 12/11.\r\n**Prochaines étapes :**\r\n- Ajouter chaque nouvelle erreur ici.\r\n**Liens :**\r\n- lecon_de :: [[point_archie]]\r\n- fait_partie_de :: [[Leçons]]\r\n');
    const c = P.memoire({ base: d });
    assert.deepEqual([c.lecons, c.dernieres_lecons], [2, ['Ne dis pas « fait » sans retour.', 'Lis la méthode avant l\'outil.']]);
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
    for (const [chemin, type, debut] of [['/sphere.js', 'text/javascript', '// sphere.js'], ['/ecoute.js', 'text/javascript', '// ecoute.js'], ['/logo.js', 'text/javascript', '// logo.js'],
      ['/orbe.js', 'text/javascript', '// orbe.js'], ['/curseur.js', 'text/javascript', '// curseur.js'], ['/decor/lac_base.webp', 'image/webp', 'RIFF'], ['/decor/lac_lumiere.webp', 'image/webp', 'RIFF'],
      ['/decor/lac_profondeur.webp', 'image/webp', 'RIFF'],
      ['/polices/fraunces.woff2', 'font/woff2', 'wOF2'], ['/polices/fraunces-italique.woff2', 'font/woff2', 'wOF2'], ['/polices/nunito.woff2', 'font/woff2', 'wOF2']]) {
      const f = await voir(local, chemin);
      assert.equal(f.code, 200, chemin);
      assert.ok(String(f.type).startsWith(type), chemin + ' : ' + f.type);
      assert.ok(f.corps.toString('latin1').startsWith(debut), chemin);
      assert.equal((await voir(porte, chemin)).code, 404, chemin + ' ne sort pas du PC');
    }
    assert.match((await voir(local, '/polices/nunito.woff2')).cache, /max-age/);
    // aucun chemin ne vient de la demande : pas de fichier hors de la liste
    for (const chemin of ['/polices/../portail.js', '/polices/OFL-Nunito.txt', '/portail.js', '/polices/', '/sphere.js/..%2f..%2f.env',
      '/decor/', '/decor/lac.json', '/decor/../portail.js']) {
      assert.equal((await voir(local, chemin)).code, 404, chemin);
    }
    // la page n'appelle aucun autre site : polices et scripts viennent du PC
    const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
    assert.doesNotMatch(page, /https?:\/\/(?!www\.w3\.org)[a-z0-9.-]+\.[a-z]{2,}/i, 'aucune adresse exterieure dans la page');
    assert.ok(page.includes('url("/polices/fraunces.woff2")') && page.includes('<script src="/sphere.js">') && page.includes('<script src="/ecoute.js">'));
    assert.ok(page.includes('<script src="/orbe.js">') && page.includes("'/decor/lac_base.webp'"));
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

test('vitrine : noms lisibles, outils de l agent, « a brancher » et projets en cours ; sans vitrine, la page marche quand meme', () => {
  const d = chateau(false);
  try {
    fs.mkdirSync(path.join(d, 'outils'));
    fs.writeFileSync(path.join(d, 'outils', 'registre.json'), JSON.stringify({
      planificateur: { description: 'MODE D EMPLOI : faire quelque chose PLUS TARD. action=ajouter' },
      lire_pdf: { description: 'lit un PDF. action=lire', sensible: true },
      prises_shelly: { description: 'MODE D EMPLOI : prises connectees. action=etat', sensible: true },
      abime: 'pas une fiche' }));
    const r = { depot: d, base: d };
    // sans config/vitrine.json : la premiere phrase du mode d'emploi, dans l'ordre du registre
    assert.deepEqual(P.outils(r).map(o => [o.nom, o.titre, o.quoi]), [['planificateur', '', 'faire quelque chose PLUS TARD'], ['lire_pdf', '', 'lit un PDF'], ['prises_shelly', '', 'prises connectees']]);
    assert.deepEqual(P.chantiers(r), []);
    fs.mkdirSync(path.join(d, 'config'));
    fs.writeFileSync(path.join(d, 'config', 'vitrine.json'), JSON.stringify({
      outils: [
        { nom: 'prises_shelly', titre: 'Prises connectées', quoi: 'Écrit pour la marque Shelly, adaptable à une autre marque.', besoin: 'une prise Shelly' },
        { nom: 'enquete_osint', agent: true, titre: 'Enquêtes (OSINT)', quoi: 'Hunter enquête en sources ouvertes.' },
        { nom: 'trader', titre: 'Trader (simulation)', quoi: 'pas inscrit au registre : pas affiche' },
        { nom: 'prises_shelly', titre: 'en double' }, { titre: 'sans nom' }, null, 'texte',
        { nom: 'lire_pdf', titre: 'x'.repeat(500), quoi: 7 },
      ],
      en_developpement: [{ titre: 'Pilotage de drone', quoi: 'Piloter un drone depuis Archi.' }, { quoi: 'sans titre' }, null, { titre: '  ' }, { titre: 'Appel à l\'expert' }],
    }));
    const L = P.outils(r);
    // l'ordre de la vitrine, puis les outils du registre qu'elle ne connait pas ; l'outil de l'agent est la sans etre au registre
    assert.deepEqual(L.map(o => o.nom), ['prises_shelly', 'enquete_osint', 'lire_pdf', 'planificateur']);
    assert.deepEqual(L[0], { nom: 'prises_shelly', titre: 'Prises connectées', quoi: 'Écrit pour la marque Shelly, adaptable à une autre marque.', besoin: 'une prise Shelly', sensible: true });
    assert.deepEqual(L[1], { nom: 'enquete_osint', titre: 'Enquêtes (OSINT)', quoi: 'Hunter enquête en sources ouvertes.', besoin: '', sensible: false });
    assert.equal(L[2].titre.length, 60);   // rien de demesure n'arrive a la page
    assert.equal(L[2].quoi, '');
    assert.equal(L[2].sensible, true);     // « accord » vient du registre, pas de la vitrine
    assert.deepEqual(P.chantiers(r), [{ titre: 'Pilotage de drone', quoi: 'Piloter un drone depuis Archi.' }, { titre: 'Appel à l\'expert', quoi: '' }]);
    // une vitrine abimee ne casse rien
    for (const abime of ['{', '[]', '"texte"', '{"outils": "non", "en_developpement": {}}']) {
      fs.writeFileSync(path.join(d, 'config', 'vitrine.json'), abime);
      assert.equal(P.outils(r).length, 3, abime);
      assert.deepEqual(P.chantiers(r), [], abime);
    }
  } finally { fs.rmSync(d, { recursive: true, force: true }); }
});

test('vitrine du depot : chaque outil du registre d exemple a son nom lisible, et rien n est annonce qui ne soit pas branche', () => {
  const depot = path.join(__dirname, '..', '..');
  const v = JSON.parse(fs.readFileSync(path.join(depot, 'config', 'vitrine.json'), 'utf8'));
  const reg = JSON.parse(fs.readFileSync(path.join(depot, 'chateau_exemple', 'outils', 'registre.json'), 'utf8'));
  const fiches = v.outils.filter(f => !f.agent).map(f => f.nom);
  assert.deepEqual(Object.keys(reg).filter(n => !fiches.includes(n)), [], 'outil du registre sans fiche dans la vitrine');
  assert.deepEqual(fiches.filter(n => !reg[n]), [], 'fiche de la vitrine sans outil au registre');
  for (const f of v.outils) assert.ok(f.titre && f.titre.length <= 60 && typeof f.quoi === 'string' && f.quoi.length <= 200, f.nom);
  // une phrase courte, ou rien quand le nom parle de lui-meme (choix de J, 11/11)
  for (const nom of ['lire_page', 'Wikipedia', 'navigateur', 'creer_pdf']) assert.equal(v.outils.find(f => f.nom === nom).quoi, '', nom);
  for (const f of v.outils.filter(x => x.quoi)) assert.ok(f.quoi.length <= 130, f.nom + ' : phrase trop longue pour la vitrine');
  assert.match(v.outils.find(f => f.nom === 'planificateur').quoi, /réveil.*quand tu arrives quelque part/);
  // un outil « agent » doit etre un vrai noeud outil du workflow de la demo
  const wf = fs.readFileSync(path.join(depot, 'n8n', 'archi_demo.json'), 'utf8');
  for (const f of v.outils.filter(x => x.agent)) assert.ok(wf.includes('"name": "' + f.nom + '"') || wf.includes('"name":"' + f.nom + '"'), f.nom + ' absent du workflow');
  assert.ok(v.en_developpement.some(c => /drone/i.test(c.titre)), 'le pilotage de drone est annonce en cours de developpement');
  // la marque des prises : Shelly, mais adaptable
  assert.match(v.outils.find(f => f.nom === 'prises_shelly').quoi, /Shelly, adaptable/);
  assert.match(reg.prises_shelly.description, /ecrit pour la marque Shelly, adaptable a une autre marque/);
  // les modes d'emploi parlent de « l'utilisateur », plus de « J »
  assert.doesNotMatch(JSON.stringify(reg), /(?<![A-Za-z0-9_'’\\])J(?![A-Za-z0-9_'’])/);
  const page = P.outils({ depot, base: path.join(depot, 'chateau_exemple') });
  assert.equal(page.length, Object.keys(reg).length + v.outils.filter(x => x.agent).length);
  assert.ok(page.every(o => o.titre), 'chaque outil de la page a un nom lisible');
});

test('page d accueil : un menu (visite guidee, ses outils, outils en construction) et le logo partout ou « Archi » est ecrit', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  const menu = page.slice(page.indexOf('<nav class="haut"'), page.indexOf('</nav>'));
  // ferme au depart : invisible, et hors d'atteinte du clavier et des lecteurs d'ecran (inert)
  assert.ok(menu.includes('id="b-menu"') && menu.includes('aria-expanded="false"') && menu.includes('id="menu" role="menu" aria-hidden="true" inert'));
  const ordre = ['id="b-visite">Visite guidée', 'id="b-coulisses">Ses outils', 'id="b-chantier">Outils en construction'].map(x => menu.indexOf(x));
  assert.ok(ordre[0] > 0 && ordre[0] < ordre[1] && ordre[1] < ordre[2], JSON.stringify(ordre));
  assert.ok(page.includes('id="volet-chantier"') && page.includes('<ul id="chantiers">'));
  assert.ok(page.includes("$('b-chantier').hidden = !chantiers.length;"), 'sans projet, la ligne du menu disparait');
  assert.ok(page.includes("$('b-chantier').onclick = () => { menu(false); volet('volet-chantier'); };"));
  // le logo : un symbole dans la page, et logo.js qui le pose
  assert.ok(page.includes('<symbol id="mot-archi" viewBox="0 0 120 34"') && page.includes('<script src="/logo.js">'));
  assert.ok(page.includes('if (window.ArchiLogo) ArchiLogo.installer(document);'));
  assert.ok(page.includes('.mot-archi svg {'));
});

test('page d accueil epuree : « 100 % local » dit une fois, les modules aux bords, le logo en lettres separees, rien d inaccessible', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  // la phrase « 100 % local » : au lancement (body.annonce, retire apres quelques secondes) et pendant la visite, jamais ensuite
  assert.ok(page.includes('<body class="annonce">') && page.includes('body:not(.annonce):not(.en-visite) .nom small { opacity: 0;'));
  assert.match(page, /setTimeout\(\(\) => document\.body\.classList\.remove\('annonce'\), \d+\)/);
  // les modules se cachent seulement a la souris, sur grand ecran : au doigt et sur telephone, tout reste visible
  const epure = page.slice(page.indexOf('@media (hover: hover) and (pointer: fine) and (min-width: 981px) {'));
  assert.ok(epure.length > 100 && epure.includes('.memoire h2, .memoire li, .memoire p, .jour :is(h2, h3, p, li, .tel) { opacity: 0;'));
  assert.ok(page.includes("matchMedia('(hover: hover) and (pointer: fine) and (min-width: 981px)')"));
  // ils restent joignables au clavier (tabindex) et se montrent pendant la visite (.vise)
  assert.ok(page.includes('class="jour" id="jour" aria-label="Aujourd\'hui" tabindex="0"') && page.includes('class="memoire" id="zone-memoire" tabindex="0"'));
  assert.ok(epure.includes('.memoire.vise li') && epure.includes('.memoire:focus-within'));
  // les deux lisieres, et le logo en cinq lettres (A, R, C, H, I) qui peuvent tournoyer
  assert.ok(page.includes('id="lis-gauche"') && page.includes('id="lis-droite"'));
  const logo = page.slice(page.indexOf('<svg class="logo"'), page.indexOf('</svg>', page.indexOf('<svg class="logo"')));
  assert.equal((logo.match(/class="lettre"/g) || []).length, 5);
  // le dessin du logo n'a pas change : les memes traits qu'avant, juste ranges lettre par lettre
  for (const trait of ['M2,32 L13,2 L24,32', 'M33,32 V2 H47 A4,4 0 0 1 51,6 V13 A4,4 0 0 1 47,17 H33 M42,17 L51,32', 'M80,2 H64 A4,4 0 0 0 60,6 V28 A4,4 0 0 0 64,32 H80', 'M89,2 V32 M109,2 V32 M89,17 H109', 'M118,2 V32'])
    assert.ok(logo.includes('d="' + trait + '"'), trait);
  // le menu : un astre du decor qui se signale (ping) et dit son nom quand on approche ; la visite le montre au dernier pas
  assert.ok(page.includes('class="glyphe"') && page.includes('class="ping"') && page.includes("pointe: 'b-menu'"));
  // et l'orbe repond : une eruption vers ce que la souris survole, si l'orbe 3D sait le faire
  assert.ok(page.includes('if (!sphere.eclat || !el) return;'));
});

test('page d accueil : « Aujourd hui » au bord gauche, la discussion en haut et ce qui arrive dessous', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  const jour = page.slice(page.indexOf('<aside class="jour"'), page.indexOf('</aside>', page.indexOf('<aside class="jour"')));
  // dans cet ordre : la date, le fil, les rappels a venir (ou une phrase s'il n'y en a pas), la tache en cours, le telephone
  const ordre = ['id="j-date"', 'id="fil"', 'id="j-rappels"', 'id="j-rien"', 'id="j-tache"', 'id="j-tel"'].map(x => jour.indexOf(x));
  assert.ok(ordre.every((x, i) => x > 0 && (i === 0 || x > ordre[i - 1])), JSON.stringify(ordre));
  assert.ok(page.includes('majJour(e, branche);') && page.includes('majTache(v);') && page.includes("$('j-tel').onclick = () => volet('volet-tel');"));
  // le module de gauche de la page epuree, c'est lui ; et le fil vide ne prend pas de place
  assert.ok(page.includes("gauche: { module: $('jour')") && page.includes('.fil:empty { display: none; }'));
  // le texte du rappel s'ecrit en texte, jamais en HTML
  assert.ok(page.includes('li.appendChild(document.createTextNode(x.texte));') && !/j-rappels[^\n]*innerHTML/.test(page));
});

test('portail : les prochains rappels pour « Aujourd hui », lus dans le planificateur sans rien y changer', () => {
  const B = fs.mkdtempSync(path.join(os.tmpdir(), 'archi-rappels-'));
  const t0 = Date.parse('2026-11-11T20:00:00Z');
  assert.deepStrictEqual(P.prochains({ base: B }, t0), []);   // pas de planificateur : rien, sans erreur
  fs.mkdirSync(path.join(B, 'planificateur'));
  const F = path.join(B, 'planificateur', 'taches.json');
  fs.writeFileSync(F, 'pas du json');
  assert.deepStrictEqual(P.prochains({ base: B }, t0), []);
  const L = [
    { texte: 'Demain matin', statut: 'attente', quand: { type: 'heure', a: '2026-11-12T08:00:00Z' } },
    { texte: 'Tous les jours', statut: 'attente', quand: { type: 'boucle', prochaine: '2026-11-11T21:00:00Z' } },
    { texte: 'En arrivant', statut: 'attente', quand: { type: 'lieu', lieu_nom: 'Maison', chaque_fois: true } },
    { texte: 'Deja fait', statut: 'fait', quand: { type: 'heure', a: '2026-11-11T22:00:00Z' } },
    { texte: 'Il y a trois heures', statut: 'attente', quand: { type: 'heure', a: '2026-11-11T17:00:00Z' } },
    { texte: '', statut: 'attente', quand: { type: 'heure', a: '2026-11-11T22:00:00Z' } },
    null, { texte: 'Sans quand', statut: 'attente' },
  ];
  fs.writeFileSync(F, JSON.stringify(L));
  const avant = fs.readFileSync(F, 'utf8');
  const p = P.prochains({ base: B }, t0);
  // le plus proche d'abord, puis ceux qui attendent un lieu ; ni les faits, ni les vieux, ni les vides
  assert.deepStrictEqual(p.map(x => x.texte), ['Tous les jours', 'Demain matin', 'En arrivant']);
  assert.deepStrictEqual(p[0], { texte: 'Tous les jours', quand: Date.parse('2026-11-11T21:00:00Z'), boucle: true });
  assert.deepStrictEqual(p[2], { texte: 'En arrivant', lieu: 'Maison', chaque_fois: true });
  assert.equal(fs.readFileSync(F, 'utf8'), avant);   // lu, jamais ecrit
  // six au plus
  fs.writeFileSync(F, JSON.stringify(Array.from({ length: 9 }, (_, i) => ({ texte: 'R' + i, statut: 'attente', quand: { type: 'heure', a: new Date(t0 + (i + 1) * 60000).toISOString() } }))));
  assert.equal(P.prochains({ base: B }, t0).length, 6);
  fs.rmSync(B, { recursive: true, force: true });
});

test('portail : les documents d Archi, et seulement eux, peuvent etre ouverts sur le PC', async () => {
  const d = chateau(false);
  assert.deepStrictEqual(P.documents({ base: d }), []);   // pas encore de dossier documents : rien, sans erreur
  fs.mkdirSync(path.join(d, 'documents'));
  fs.writeFileSync(path.join(d, 'documents', 'ancien.pdf'), 'a');
  fs.utimesSync(path.join(d, 'documents', 'ancien.pdf'), new Date(Date.now() - 3600000), new Date(Date.now() - 3600000));
  fs.writeFileSync(path.join(d, 'documents', '2026-11-11_1326_Competences_d_Archi.pdf'), 'pdf');
  fs.writeFileSync(path.join(d, 'documents', '.cache'), 'x');
  fs.mkdirSync(path.join(d, 'documents', 'sous_dossier'));
  fs.writeFileSync(path.join(d, 'secret.txt'), 'non');
  const L = P.documents({ base: d });
  assert.deepStrictEqual(L.map(x => x.nom), ['2026-11-11_1326_Competences_d_Archi.pdf', 'ancien.pdf']);   // le plus recent d'abord, ni cache ni dossier
  assert.equal(L[0].taille, 3); assert.ok(L[0].quand > L[1].quand);
  // un nom simple qui existe dans documents\ ; rien d'autre (dossier parent, chemin, sous-dossier, inexistant)
  assert.equal(P.cheminDocument({ base: d }, 'ancien.pdf'), path.resolve(d, 'documents', 'ancien.pdf'));
  for (const piege of ['../secret.txt', '..\\secret.txt', 'C:\\Windows\\win.ini', '/etc/passwd', '..', '.', 'sous_dossier', 'absent.pdf', '', null, 42, 'a"b.pdf', 'x'.repeat(201)])
    assert.equal(P.cheminDocument({ base: d }, piege), null, String(piege));
  // la route : seule la page peut demander, et seulement un document du chateau
  const ouverts = [];
  const r = { port: 0, n8nPort: 1, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: '', telegram: false,
    ouvrir: (f, comment) => ouverts.push([f, comment]) };
  const local = P.creerServeurLocal(r);
  await new Promise(x => local.listen(0, '127.0.0.1', x));
  r.port = local.address().port;
  const demande = (corps, page) => appel(r.port, { path: '/api/ouvrir', method: 'POST',
    headers: Object.assign({ host: '127.0.0.1:' + r.port, 'content-type': 'application/json' }, page === false ? {} : { 'x-archi-portail': '1' }) }, JSON.stringify(corps));
  try {
    assert.equal((await demande({ nom: 'ancien.pdf', comment: 'dossier' })).code, 200);
    assert.equal((await demande({ nom: 'ancien.pdf' })).code, 200);
    assert.equal((await demande({ nom: '../secret.txt' })).code, 404);
    assert.equal((await demande({ nom: 'ancien.pdf' }, false)).code, 403);   // pas la page : refuse
    assert.deepStrictEqual(ouverts, [[path.resolve(d, 'documents', 'ancien.pdf'), 'dossier'], [path.resolve(d, 'documents', 'ancien.pdf'), 'fichier']]);
  } finally { await fermer(local); fs.rmSync(d, { recursive: true, force: true }); }
});

test('page d accueil : un chemin de fichier devient une pastille, « donne-le-moi » et « ouvre le dossier » restent sur le PC', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  // on reprend les vraies fonctions de la page et on les essaie sur la vraie phrase d'Archi
  const morceau = nom => { const i = page.indexOf(nom); assert.ok(i > 0, nom); return page.slice(i, page.indexOf('\n', i)); };
  const vm = require('vm'), bac = {};
  vm.runInNewContext(['RE_CHEMIN', 'nomDoc', 'joliNom', 'DONNE', 'FAIRE', 'DOSSIER', 'sansDonne'].map(n => morceau('const ' + n + ' =')).join('\n') + '\n' +
    page.slice(page.indexOf('function sansChemins(t) {'), page.indexOf('async function ouvrirDoc(')) +
    '\nthis.f = { sansChemins, joliNom, DONNE, FAIRE, DOSSIER, sansDonne };', bac);
  const { sansChemins, joliNom, DONNE, FAIRE, DOSSIER, sansDonne } = bac.f;
  const r = sansChemins('Le PDF « Compétences d’Archi » est prêt :\n\n`C:\\Users\\Camille\\Archi\\chateau\\documents\\2026-11-11_1326_Competences_d_Archi.pdf`.');
  assert.equal(r.texte, 'Le PDF « Compétences d’Archi » est prêt.');
  assert.deepStrictEqual([...r.noms], ['2026-11-11_1326_Competences_d_Archi.pdf']);
  const m = sansChemins('Je l\'ai mis dans C:\\docs\\plan_garage.pdf, tu veux que je l\'envoie ?');
  assert.equal(m.texte, 'Je l\'ai mis dans « plan garage », tu veux que je l\'envoie ?');
  assert.equal(sansChemins('Rien à signaler.').noms.length, 0);
  assert.equal(joliNom('2026-11-11_1326_Competences_d_Archi.pdf'), 'Competences d Archi');
  // ce que la page comprend toute seule ; « fais-moi un PDF et donne-le-moi » part bien au modele
  for (const x of ['donne-le-moi', 'Donne le moi', 'passe-les-moi', 'donne-moi le fichier', 'donne moi les documents']) assert.ok(DONNE.test(x), x);
  for (const x of ['donne-moi la météo', 'montre-moi la carte', 'donne-moi des idées']) assert.ok(!DONNE.test(x), x);
  assert.ok(FAIRE.test('crée-moi un PDF et donne-le-moi') && FAIRE.test('fais-moi un résumé') && !FAIRE.test('donne-le-moi'));
  assert.equal(sansDonne('Fais-moi un PDF qui résume ce que tu sais faire et donne-le-moi'), 'Fais-moi un PDF qui résume ce que tu sais faire');
  assert.equal(sansDonne('Crée un PDF sur Médor, puis passe-le-moi.'), 'Crée un PDF sur Médor');
  assert.ok(DOSSIER.test('ouvre-moi le dossier') && DOSSIER.test('Ouvre le dossier') && !DOSSIER.test('ouvre la porte'));
  // la parole s'efface (45 s au moins), l'orbite et « Bonjour » restent 45 s, les idees 3 minutes
  assert.ok(page.includes('Math.max(45000,') && page.includes('}, 45000);') && page.includes("$('idees').classList.add('efface'), 180000)"));
  assert.ok(page.includes('.parole.efface > :not(.idees) { opacity: 0; }'));
  // le module de gauche commence sous le nom
  assert.match(page, /\.jour \{ grid-column: 1; grid-row: 1 \/ 3; align-self: start; margin-top: 1\d\dpx;/);
});

test('page d accueil : plein ecran, curseur d Archi, et « En construction » en bas de Ses outils', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  const cur = fs.readFileSync(path.join(__dirname, '..', 'curseur.js'), 'utf8');
  // plein ecran : au premier geste (un navigateur refuse sans geste), Echap n'y renvoie pas, et le menu l'allume ou l'eteint
  assert.ok(page.includes('id="b-plein">Plein écran') && page.includes("addEventListener('pointerdown', premierGeste, true)"));
  assert.ok(page.includes("ev.key === 'Escape'") && page.includes("localStorage.setItem('archi_plein_ecran', oui ? 'oui' : 'non')"));
  // le curseur : seulement a la souris, la saisie garde son curseur, et la fleche revient si le dessin casse ; ?curseur=non l'eteint
  assert.ok(page.includes('<script src="/curseur.js">') && page.includes("s !== 'non' && window.ArchiCurseur"));
  // l'etincelle, choix de J : le mini-Archi (?curseur=b) ne vaut que pour une visite, et un ancien « b » retenu s'efface
  assert.ok(page.includes("if (q === 'a' || q === 'non') localStorage.setItem('archi_curseur', q);"));
  assert.ok(page.includes("if (localStorage.getItem('archi_curseur') === 'b') localStorage.removeItem('archi_curseur');"));
  assert.ok(page.includes("s = q === 'b' ? 'b' : (localStorage.getItem('archi_curseur') || 'a');"));
  assert.ok(page.includes('html.curseur-archi :is(textarea, input, [contenteditable="true"]) { cursor: text !important; }'));
  assert.ok(cur.includes("'(hover: hover) and (pointer: fine)'") && cur.includes("} catch (err) { stop(); }") && cur.includes("classList.remove('curseur-archi')"));
  // les projets pas encore aboutis : dans le menu (Outils en construction) et en bas de Ses outils
  assert.ok(page.includes('<h3 id="chantiers-titre" hidden>En construction</h3>') && page.includes("for (const ul of [$('chantiers'), $('chantiers-outils')])"));
  // une phrase vide n'ajoute pas de ligne vide sous le nom de l'outil
  assert.ok(page.includes('if (o.quoi) { li.appendChild(document.createElement(\'br\'))'));
});

test('orbe 3D : la souris touche la bulle, remue la brume et fait jaillir des eruptions', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'orbe.js'), 'utf8');
  for (const u of ['uDoigt', 'uSourisP', 'uSourisV', 'uRegard']) assert.ok(src.includes('u.' + u + ','), u + ' est bien envoye au shader');
  // le sillage divise par uSourisV.w : il ne doit jamais valoir 0 (sinon NaN dans la brume)
  assert.match(src, /gl\.uniform4f\(u\.uSourisV, [^;]*, 0\.35 \+ 0\.6 \* brassage\)/);
  assert.ok(src.includes('eclat(x, y, force) { eclat(x, y, force); return this; }'));
  // une page sans souris (telephone) : rien ne bouge tant que pointermove ne vient pas d'une souris
  assert.ok(src.includes("sourisLa = ev.pointerType !== 'touch'"));
});

test('orbe 3D : l allee de monolithes vit (glisse, monte, linteau) et ses signes s allument quand Archi reflechit', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'orbe.js'), 'utf8');
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  // le shader recoit l'allee, et seulement si elle n'est plus cuite dans l'image
  for (const u of ['uBriquesOn', 'uEchA', 'uPense', 'uCamR', 'uCamP', 'uTan', 'uVersLune', 'uOrbeM']) assert.ok(src.includes('u.' + u + ','), u);
  assert.ok(src.includes('!sc0.monolithes_dans_image') && src.includes("['uGlyphes', decor.signes || vide]"));
  // ses briques sont dessinees a part (monuments.js), avec leur reflet, puis posees sur le decor
  assert.ok(src.includes('ArchiMonuments.creerChantier(decor.allee)') && src.includes("['uBriques', briquesOn ? cibles.briques.tx : vide]"));
  // la page donne la scene de Blender : la camera, la lune, et les 10 monolithes de l'allee
  const i = page.indexOf('scene: {'), sc = page.slice(i, page.indexOf('] } },', i));
  assert.ok(i > 0 && sc.includes('monolithes_dans_image: false') && sc.includes('tan_h: 0.514286'));
  assert.equal((sc.match(/\{ rang: \d/g) || []).length, 10);
  // on reprend la vraie fonction creerAllee et on la fait vivre, a 60 images par seconde
  const vm = require('vm'), bac = {};
  vm.runInNewContext(src.slice(src.indexOf('  function creerAllee(liste, alea) {'), src.indexOf('  // ------------------------------------------------------------------ l\'orbe')) + '\nthis.creerAllee = creerAllee;', bac);
  const liste = [];
  for (let r = 0; r < 4; r++) for (const c of [-1, 1]) liste.push({ rang: r, cote: c, x: c * 3.7, y: 15 + r * 6, haut: 2 + r * 1.7 + (c > 0 ? 1 : 0), l: 0.6, p: 0.45, rot: 0 });
  let g = 7; const alea = () => { g = (g * 16807) % 2147483647; return g / 2147483647; };
  const A = bac.creerAllee(liste, alea);
  const vivre = (sec, pense) => { for (let k = 0; k < sec * 60; k++) A.avancer(1 / 60, pense); };
  // un linteau : il attend en l'air, descend, se pose pile sur deux monolithes mis a la meme hauteur, puis repart
  A.evenement(false, 'linteau');
  assert.ok(A.lin.actif && A.lin.a.rang > 0 && A.lin.a.rang === A.lin.b.rang, 'jamais sur le premier rang');
  vivre(20, 0);
  assert.equal(A.lin.etape, 'pose');
  assert.ok(Math.abs(A.lin.a.h - A.lin.b.h) < 0.02, 'les deux piliers a la meme hauteur');
  assert.ok(Math.abs(A.lin.z - (A.lin.a.h + 0.32)) < 0.05, 'pose pile dessus : ' + A.lin.z + ' / ' + A.lin.a.h);
  let b = A.boites();
  assert.equal(b.n, liste.length + 1);
  assert.equal(b.tai[liste.length * 4 + 3], -1, 'le linteau ne porte pas de signes');
  const paire = [A.lin.a, A.lin.b]; let parti = false;
  for (let k = 0; k < 70 * 60 && !parti; k++) { A.avancer(1 / 60, 0); parti = !A.lin.actif || A.lin.a !== paire[0]; }
  assert.ok(parti && !paire[0].porte && !paire[1].porte, 'le linteau est reparti, ses piliers sont libres');
  // glisser et monter : jamais hors de l'allee, jamais sous l'eau
  for (let k = 0; k < 40; k++) { A.evenement(false, k % 2 ? 'glisse' : 'monte'); vivre(1, 0); }
  vivre(15, 0);
  for (const m of A.M) { assert.ok(Math.abs(m.x) >= 2.6 && Math.abs(m.x) <= 4.8, 'x ' + m.x); assert.ok(m.h > 1.2 && m.h < 9.7, 'h ' + m.h); assert.equal(Math.sign(m.x), m.cote); }
  // il reflechit : une partie des monolithes s'allume (pas tous d'un coup) ; il a fini : tout s'eteint doucement
  vivre(1, 1);
  assert.ok(A.M.filter(m => m.rang === 3).every(m => m.lueur < 0.5), 'en vague : le fond ne s allume pas en premier');
  vivre(6, 1);
  const allumes = A.M.filter(m => m.lueur > 0.99).length;
  assert.ok(allumes >= 2, 'allumes ' + allumes);
  vivre(2, 0);
  assert.ok(A.M.some(m => m.lueur > 0.3), 'il ne s eteint pas d un coup');
  vivre(5, 0);
  assert.ok(A.M.every(m => m.lueur < 0.5), 'puis il s eteint');
  b = A.boites();
  for (let k = 0; k < b.n; k++) assert.ok(Number.isFinite(b.pos[k * 4]) && Number.isFinite(b.tai[k * 4 + 2]));
  // l'alphabet est fait maison : dessine ici, aucune image ni police d'un jeu
  assert.ok(src.includes('function texSignes(gl)') && src.includes("un alphabet maison (pas celui d'un jeu)"));
});

test('page d accueil : « Bonjour » et « Archi reflechit » ont leurs polices (A ou B), libres et servies par le portail', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  const portail = fs.readFileSync(path.join(__dirname, '..', 'portail.js'), 'utf8');
  const dossier = path.join(__dirname, '..', 'polices');
  // chaque police est un vrai woff2, avec sa licence libre (OFL) a cote, declaree dans la page et servie par le portail
  for (const [fichier, famille, licence] of [['cormorant-italique', 'Cormorant Garamond', 'Cormorant'], ['cinzel', 'Cinzel', 'Cinzel'], ['orbitron', 'Orbitron', 'Orbitron'], ['michroma', 'Michroma', 'Michroma']]) {
    assert.equal(fs.readFileSync(path.join(dossier, fichier + '.woff2')).subarray(0, 4).toString('latin1'), 'wOF2', fichier);
    assert.match(fs.readFileSync(path.join(dossier, 'OFL-' + licence + '.txt'), 'utf8'), /SIL Open Font License/, licence);
    assert.ok(page.includes('font-family: "' + famille + '"; src: url("/polices/' + fichier + '.woff2")'), famille);
    assert.ok(portail.includes("'/polices/" + fichier + ".woff2': ['polices/" + fichier + ".woff2', 'font/woff2']"), fichier);
  }
  // A par defaut, B avec ?police=b (et le PC s'en souvient) ; le salut garde sa police quand le prenom arrive
  assert.ok(page.includes('--salut:"Cormorant Garamond"') && page.includes('--pense:"Orbitron"'));
  assert.ok(page.includes(':root[data-police="b"] { --salut:"Cinzel"') && page.includes('--pense:"Michroma"'));
  // A, le choix de J : la B ne vaut que pour une visite (?police=b), et un ancien choix retenu s'efface
  assert.ok(page.includes("try { localStorage.removeItem('archi_police'); } catch (x) {}") && page.includes('document.documentElement.dataset.police = policeChoisie;'));
  assert.ok(page.includes("return new URLSearchParams(location.search).get('police') === 'b' ? 'b' : 'a';") && !page.includes("setItem('archi_police'"));
  // « Archi » s'ecrit avec le logo, y compris dans « Archi réfléchit… » (logo.js le pose sur tout texte de la page)
  assert.ok(page.includes("montrer((dit ? '🎙 ' : '') + (texte || '(photo)'), 'Archi réfléchit…', 'attente');") && page.includes('if (window.ArchiLogo) ArchiLogo.installer(document);'));
  assert.ok(page.includes('<div class="reponse salut" id="p-reponse">') && page.includes("$('p-reponse').className = 'reponse salut';"));
  assert.ok(page.includes('.reponse.salut {') && page.includes('.reponse.attente {') && page.includes('animation: balayage'));
  assert.ok(page.includes('@media (prefers-reduced-motion: reduce) { .reponse.attente { animation: none;'));
});

test('workflow de la demo : les outils de l agent sont relies aux deux agents, vers des workflows optionnels qui existent', () => {
  const depot = path.join(__dirname, '..', '..');
  const wf = JSON.parse(fs.readFileSync(path.join(depot, 'n8n', 'archi_demo.json'), 'utf8'));
  const ids = fs.readdirSync(path.join(depot, 'n8n', 'optionnels')).filter(f => f.endsWith('.json'))
    .map(f => JSON.parse(fs.readFileSync(path.join(depot, 'n8n', 'optionnels', f), 'utf8'))).reduce((m, w) => { if (w.id) m[w.id] = w; return m; }, {});
  const v = JSON.parse(fs.readFileSync(path.join(depot, 'config', 'vitrine.json'), 'utf8'));
  const annonces = v.outils.filter(o => o.agent).map(o => o.nom).sort();
  assert.deepEqual(annonces, ['Wikipedia', 'enquete_osint', 'lire_page', 'navigateur', 'videos_youtube']);
  for (const suffixe of ['', ' appli']) {
    const relies = Object.keys(wf.connections).filter(src => (wf.connections[src].ai_tool || []).some(l => l.some(x => x.node === 'Agent' + suffixe)));
    // ce que la page annonce = ce qui est vraiment relie a l'agent (plus le lanceur des outils maison)
    assert.deepEqual(relies.map(n => n.slice(0, n.length - suffixe.length)).sort(), annonces.concat('outils_maison').sort(), 'agent' + suffixe);
    for (const nom of relies) {
      const n = wf.nodes.find(x => x.name === nom);
      if (!n.type.endsWith('toolWorkflow')) continue;
      const cible = ids[n.parameters.workflowId.value];
      assert.ok(cible, nom + ' appelle un workflow absent du depot : ' + n.parameters.workflowId.value);
      // chaque champ envoye est une entree declaree par le workflow appele
      const entrees = cible.nodes.find(x => x.type.endsWith('executeWorkflowTrigger')).parameters.workflowInputs.values.map(x => x.name);
      assert.deepEqual(Object.keys(n.parameters.workflowInputs.value).filter(c => !entrees.includes(c)), [], nom);
      assert.ok(n.parameters.description.length > 60, nom);
    }
  }
  // lire_page ne peut QUE lire une page : l'action est fixee, le modele ne la choisit pas
  assert.equal(wf.nodes.find(x => x.name === 'lire_page').parameters.workflowInputs.value.action, 'page');
  // le navigateur : les regles dures sont rappelees au modele, et la capture sans Telegram ne casse pas l'outil
  assert.match(wf.nodes.find(x => x.name === 'navigateur').parameters.description, /JAMAIS un mot de passe/);
  const nav = ids.ArchiNavigateur1;
  assert.ok(nav.nodes.find(x => x.name === 'Navigateur').parameters.jsCode.includes('$env.TELEGRAM_BOT_TOKEN && $env.ARCHI_TELEGRAM_CHAT_ID'));
  assert.equal(nav.nodes.find(x => x.name === 'Envoyer capture').onError, 'continueRegularOutput');
  // ce qui n'est pas relie (monteur, pieces 3D, image par lien) est annonce « en cours de developpement », pas dans les outils
  for (const mot of [/monteur/i, /pi[eè]ce 3D/i, /image/i]) assert.ok(v.en_developpement.some(c => mot.test(c.titre)), String(mot));
  assert.ok(!v.outils.some(o => /monteur|impression3d|catalogues|analyse_image/.test(o.nom)));
  // le curateur et le mecanicien sont des outils, plus des projets
  const reg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'chateau_exemple', 'outils', 'registre.json'), 'utf8'));
  for (const nom of ['curateur', 'mecanicien']) {
    assert.ok(v.outils.some(o => o.nom === nom) && reg[nom], nom);
    assert.ok(!v.en_developpement.some(c => new RegExp(nom.replace('e', '[eé]'), 'i').test(c.titre)), nom);
  }
  // le reveil de chaque minute lance aussi les tournees, avant de regarder s'il y a un chat Telegram
  const reveil = wf.nodes.find(x => x.name === 'Reveil planificateur').parameters.jsCode;
  assert.ok(reveil.indexOf('tournees.js') > 0 && reveil.indexOf('tournees.js') < reveil.indexOf('ARCHI_TELEGRAM_CHAT_ID'));
});

test('atelier : la page montre les propositions du curateur (jamais leur action) et les idees du mecanicien', () => {
  const B = fs.mkdtempSync(path.join(os.tmpdir(), 'archi-atelier-'));
  const r = { base: B, depot: path.join(__dirname, '..', '..') };
  assert.deepStrictEqual(P.atelier(r).mecanicien.idees, []);
  fs.mkdirSync(path.join(B, 'curateur'));
  fs.writeFileSync(path.join(B, 'curateur', 'propositions.json'), JSON.stringify({ cree: '2026-11-08T10:00:00', fiches: 7, appliquees: [2],
    propositions: [{ n: 1, titre: 'Dans « moi », la ligne 3 ressemble a un mot de passe', action: { type: 'retirer_ligne', ligne: '- code 1234 secret' } },
      { n: 2, titre: 'Lien casse', action: { type: 'remplacer', ancien: '[[x]]', nouveau: 'x' } }, { n: 'pas un nombre', titre: 'abime' }] }));
  fs.mkdirSync(path.join(B, 'atelier', '1_position_iss'), { recursive: true });
  fs.writeFileSync(path.join(B, 'atelier', '1_position_iss', 'recette.json'), JSON.stringify({ nom: 'position_iss', hotes: ['api.wheretheiss.at'], essais: [{ x: 1 }] }));
  fs.writeFileSync(path.join(B, 'atelier', 'atelier.json'), JSON.stringify({ idees: [
    { n: 1, titre: 'Position ISS', quoi: 'Ou est la station', etat: 'teste', dossier: '1_position_iss', hotes: ['api.wheretheiss.at'],
      essais: [{ parametres: { ville: 'Lyon' }, phrase: 'La station est la.', reussi: true }] },
    { n: 2, titre: 'Piege', etat: 'teste', dossier: '../../etc' },
    { n: 3, titre: 'Etat inconnu', etat: 'pirate' }] }));
  const a = P.atelier(r);
  assert.deepStrictEqual(a.curateur.propositions.map(p => [p.n, p.faite]), [[1, false], [2, true]]);
  assert.doesNotMatch(JSON.stringify(a), /1234|retirer_ligne|\[\[x\]\]/, 'jamais le contenu d une action');
  assert.deepStrictEqual(a.mecanicien.idees.map(i => i.n), [2, 1], 'les plus recentes d abord, un etat inconnu ecarte');
  const iss = a.mecanicien.idees.find(i => i.n === 1);
  assert.match(iss.recette, /api\.wheretheiss\.at/);
  assert.doesNotMatch(iss.recette, /essais/, 'la recette sans ses essais (ils sont montres a part)');
  assert.strictEqual(iss.essais[0].entree, 'ville = Lyon');
  assert.strictEqual(a.mecanicien.idees.find(i => i.n === 2).recette, '', 'un dossier piege n est jamais lu');
  // beaucoup de propositions : celles qui attendent d'abord (la voix renvoie a la page pour les suivantes), jamais les obsoletes
  const beaucoup = Array.from({ length: 20 }, (_, i) => ({ n: i + 1, titre: 'p' + (i + 1), obsolete: i === 4 }));
  fs.writeFileSync(path.join(B, 'curateur', 'propositions.json'), JSON.stringify({ cree: '2026-11-08T10:00:00', propositions: beaucoup,
    appliquees: Array.from({ length: 12 }, (_, i) => i + 9) }));
  const vues = P.atelier(r).curateur.propositions;
  assert.deepStrictEqual(vues.filter(p => !p.faite).map(p => p.n), [1, 2, 3, 4, 6, 7, 8], 'toutes celles en attente, sans l obsolete');
  assert.strictEqual(vues.length, 12);
  assert.ok(vues.slice(0, 7).every(p => !p.faite), 'en attente d abord');
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
  for (const id of ['b-atelier', 'volet-atelier', 'cur-props', 'meca-idees']) assert.ok(page.includes('id="' + id + '"'), id);
  assert.match(page, /function dessinerAtelier[\s\S]*textContent/);
  assert.doesNotMatch(page.slice(page.indexOf('function dessinerAtelier'), page.indexOf('// ---- les volets')), /innerHTML/);
  fs.rmSync(B, { recursive: true, force: true });
});


test('monuments : a chaque nouveau sujet, les briques de l allee forment un monument, puis reviennent', () => {
  const vm = require('vm'), bac = {};
  const src = fs.readFileSync(path.join(__dirname, '..', 'orbe.js'), 'utf8');
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'monuments.js'), 'utf8'), bac);
  vm.runInNewContext(src.slice(src.indexOf('  function creerAllee(liste, alea) {'), src.indexOf('  // ------------------------------------------------------------------ l\'orbe')) + '\nthis.creerAllee = creerAllee;', bac);
  const A = bac.ArchiMonuments;
  // dix monuments, chacun tient dans le stock de briques, devant la camera et au-dessus du lac
  assert.equal(A.NOMS.length, 10);
  for (const n of A.NOMS) {
    const l = A.monument(n);
    assert.ok(l.length > 80 && l.length <= 1800, n + ' : ' + l.length);
    for (const b of l) assert.ok([b.x, b.y, b.z, b.sx, b.sy, b.sz].every(Number.isFinite) && b.y > 12 && b.z + b.sz / 2 > 0 && b.sx > 0, n);
  }
  const liste = [];
  for (let r = 0; r < 5; r++) for (const c of [-1, 1]) liste.push({ rang: r, cote: c, x: c * 3.7, y: 15 + r * 6, haut: 2 + r * 1.5, l: 0.6, p: 0.45, rot: 0 });
  let g = 7; const alea = () => { g = (g * 16807) % 2147483647; return g / 2147483647; };
  const allee = bac.creerAllee(liste, alea), C = A.creerChantier(allee, { alea, total: 1800 });
  const vivre = (sec, pense) => { for (let k = 0; k < sec * 30; k++) C.avancer(1 / 30, pense || 0); };
  vivre(2);
  // au repos, les briques recomposent exactement les monolithes : la plus haute brique touche le sommet du pilier
  const m0 = allee.M[0], hautes = C.briques.filter(b => b.m === 0).map(b => b.p[2] + b.s[2] / 2);
  assert.ok(Math.abs(Math.max(...hautes) - m0.h) < 1e-6);
  // un nouveau sujet : elles se soulevent, tournoient, puis le monument est en place, chaque brique a sa place
  const nom = C.nouveauSujet();
  assert.ok(A.NOMS.includes(nom) && C.etat() === 'vol');
  vivre(1.5);
  assert.ok(C.briques.some(b => b.m >= 0 && b.vol && b.p[2] > b.vol.S.p[2] + 0.5), 'elles s elevent');
  vivre(14);
  assert.equal(C.etat(), 'monument');
  const cibles = A.monument(nom), poses = C.briques.filter(b => b.place && b.place.p[2] > -1);
  assert.equal(poses.length, cibles.length);
  for (const b of poses) assert.ok(Math.hypot(b.p[0] - b.place.p[0], b.p[1] - b.place.p[1], b.p[2] - b.place.p[2]) < 1e-6);
  // tant que le sujet reste, le monument reste ; il pense : ses signes s'allument ; un autre sujet : un autre monument
  vivre(20, 1);
  assert.equal(C.etat(), 'monument');
  assert.ok(C.briques.some(b => b.lueur > 0.9));
  const autre = C.nouveauSujet();
  assert.notEqual(autre, nom);
  vivre(16);
  assert.equal(C.etat(), 'monument');
  // les donnees du shader : 28 nombres par brique, tous finis
  const { n, donnees } = C.ecrire();
  assert.ok(n >= 1800 && donnees.subarray(0, n * 28).every(Number.isFinite));
  // retour a l'allee : chaque brique de monolithe retrouve sa place
  C.retour(); vivre(16);
  assert.equal(C.etat(), 'allee');
  assert.ok(Math.abs(Math.max(...C.briques.filter(b => b.m === 0).map(b => b.p[2] + b.s[2] / 2)) - allee.M[0].h) < 1e-6);
  // le fil des sujets : une relance reste dans le sujet, un autre sujet en ouvre un nouveau, un long silence aussi
  const fil = A.creerFil(); let t = 0;
  assert.equal(fil.nouveau('Que sais-tu sur moi ?', t), true);
  assert.equal(fil.nouveau('Rappelle-moi dans 2 minutes de boire un verre d eau', t += 60e3), true);
  assert.equal(fil.nouveau('oui', t += 60e3), false);
  assert.equal(fil.nouveau('Fais-moi un PDF qui résume la serre', t += 60e3), true);
  assert.equal(fil.nouveau('Ajoute la température de la serre', t += 60e3), false);
  assert.equal(fil.nouveau('Et pour demain ?', t += 60e3), false);
  assert.equal(fil.nouveau('Quel temps fera-t-il à Lyon samedi ?', t += 60e3), true);
  assert.equal(fil.nouveau('Et à Lyon dimanche ?', t += 20 * 60e3), true);
  // la page : le script est servi, et chaque message passe par le fil des sujets
  const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8'), portail = fs.readFileSync(path.join(__dirname, '..', 'portail.js'), 'utf8');
  assert.ok(page.includes('<script src="/monuments.js"></script>\n<script src="/orbe.js"></script>'));
  assert.ok(portail.includes("'/monuments.js': ['monuments.js', 'text/javascript; charset=utf-8']"));
  assert.ok(page.includes("if (filSujets && filSujets.nouveau(texte || '(photo)') && sphere && sphere.nouveauSujet) sphere.nouveauSujet();"));
});

test('monuments modelises dans Blender : chaque brique prend la forme de sa pierre a l arrivee, puis la rend', () => {
  const vm = require('vm'), bac = {};
  const src = fs.readFileSync(path.join(__dirname, '..', 'orbe.js'), 'utf8');
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'monuments.js'), 'utf8'), bac);
  const debutOrbe = src.indexOf("  // ------------------------------------------------------------------ l'orbe");
  vm.runInNewContext(src.slice(src.indexOf('  function creerAllee(liste, alea) {'), debutOrbe) + ';this.creerAllee = creerAllee;', bac);
  const A = bac.ArchiMonuments;
  // le fichier des formes : les dix monuments, des pierres finies, devant la camera, et leurs rayons
  const bin = fs.readFileSync(path.join(__dirname, '..', 'decor', 'monuments.bin'));
  assert.equal(A.lireFormes(bin.buffer.slice(bin.byteOffset, bin.byteOffset + bin.length)), 10);
  for (const nom of A.NOMS) {
    const l = A.monument(nom), f = l.formes;
    assert.ok(f && f.ng === 6 && f.K === 6 * 49 && f.N === l.length && f.r.length === f.N * f.K, nom);
    assert.ok(l.length >= 40 && l.length <= 1800, nom + ' : ' + l.length);
    for (const b of l) assert.ok([b.x, b.y, b.z, b.sx, b.sy, b.sz, b.rot].every(Number.isFinite) && b.y > 12 && b.sx > 0 && b.sz > 0, nom);
  }
  const liste = [];
  for (let r = 0; r < 5; r++) for (const c of [-1, 1]) liste.push({ rang: r, cote: c, x: c * 3.7, y: 15 + r * 6, haut: 2 + r * 1.5, l: 0.6, p: 0.45, rot: 0 });
  let g = 11; const alea = () => { g = (g * 16807) % 2147483647; return g / 2147483647; };
  const C = A.creerChantier(bac.creerAllee(liste, alea), { alea, total: 1800, formes: false });
  const vivre = s => { for (let k = 0; k < s * 30; k++) C.avancer(1 / 30, 0); };
  vivre(1);
  assert.equal(C.ecrire().grille, 0, 'l allee : de simples cubes');
  C.former('sacsayhuaman');
  const f1 = C.prendreForme();
  assert.ok(f1 && f1.K === 294 && f1.N === A.monument('sacsayhuaman').length && C.prendreForme() === null, 'la forme part une seule fois');
  vivre(3);
  assert.ok(C.briques.every(b => b.g === 0), 'en vol, ce sont encore des cubes');
  vivre(16);
  assert.equal(C.etat(), 'monument');
  const poses = C.briques.filter(b => b.place && b.place.morph);
  assert.equal(poses.length, f1.N);
  assert.ok(poses.every(b => b.g === 1 && b.rang_f >= f1.couche * C.N && b.rang_f < f1.couche * C.N + f1.N));
  const e = C.ecrire();
  assert.equal(e.grille, 6);
  assert.ok(e.donnees.subarray(0, e.n * 28).every(Number.isFinite));
  // le suivant s ecrit dans l autre etage : celui qui se defait garde sa forme pendant qu il decolle
  C.former('pyramide');
  const f2 = C.prendreForme();
  assert.equal(f2.couche, 1 - f1.couche);
  vivre(0.3);
  assert.ok(poses.some(b => b.g > 0.5 && b.rang_f < f1.couche * C.N + f1.N && b.rang_f >= f1.couche * C.N));
  vivre(19);
  C.retour(); vivre(18);
  assert.equal(C.etat(), 'allee');
  assert.ok(C.briques.every(b => b.g === 0) && C.ecrire().grille === 0);
  // le portail sert le fichier, au PC seulement (comme le decor)
  assert.ok(fs.readFileSync(path.join(__dirname, '..', 'portail.js'), 'utf8').includes("'/decor/monuments.bin': ['decor/monuments.bin', 'application/octet-stream']"));
  assert.ok(src.includes('texelFetch(uForme') && src.includes('gl.R8'));
});
