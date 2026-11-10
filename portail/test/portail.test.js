// Tests du portail : ce qui sort du PC par le tunnel est une LISTE BLANCHE, et la page d'accueil reste locale.
//   node --test portail/test/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const P = require('../portail.js');

const CLE = 'cle-de-test-abcdefghijklmnop';

function faux(headers, adresse) {
  return { headers: headers || {}, socket: { remoteAddress: adresse || '127.0.0.1' } };
}

test('estLocal : seulement le navigateur du PC, sans relais', () => {
  assert.equal(P.estLocal(faux({ host: '127.0.0.1:5680' }), 5680), true);
  assert.equal(P.estLocal(faux({ host: 'localhost:5680' }), 5680), true);
  assert.equal(P.estLocal(faux({ host: 'LOCALHOST:5680' }), 5680), true);
  // le tunnel arrive aussi de 127.0.0.1, mais avec un autre nom d'hote et des en-tetes de relais
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
  const r = { cle: CLE, telegram: false };
  const route = (m, c, h) => P.routePublique(m, c, h || {}, r);
  assert.deepEqual(route('GET', '/telephone'), { action: 'page' });
  assert.deepEqual(route('GET', '/Archi.apk'), { action: 'apk' });
  assert.deepEqual(route('POST', '/webhook/telephone-archi', { 'x-archi-cle': CLE }), { action: 'relayer' });
  assert.deepEqual(route('POST', '/webhook/telephone-boite', { 'x-archi-cle': CLE }), { action: 'relayer' });
  assert.equal(route('POST', '/webhook/telephone-archi').code, 403, 'sans cle');
  assert.equal(route('POST', '/webhook/telephone-archi', { 'x-archi-cle': CLE + 'x' }).code, 403, 'mauvaise cle');
  for (const [m, c] of [['GET', '/'], ['GET', '/api/etat'], ['POST', '/api/message'], ['GET', '/rest/login'], ['POST', '/rest/owner/setup'],
    ['GET', '/webhook/telephone-archi'], ['POST', '/webhook-test/telephone-archi'], ['POST', '/webhook/autre'], ['GET', '/qrcode.js'],
    ['POST', '/webhook/../rest/login'], ['POST', '/webhook/telephone-archi/../../rest'], ['POST', '/webhook//telephone-archi'],
    ['POST', '/webhook/%2e%2e/rest'], ['POST', '/form/x'], ['DELETE', '/webhook/telephone-archi'], ['GET', '/healthz'], ['GET', '/.env']]) {
    assert.equal(route(m, c, { 'x-archi-cle': CLE }).code, 404, m + ' ' + c);
  }
  assert.equal(route('POST', '/webhook/' + 'a'.repeat(400), { 'x-archi-cle': CLE }).code, 404);
});

test('routePublique : Telegram seulement si un bot est branche, avec son jeton secret', () => {
  const chemin = '/webhook/1b9f5c2e-8a3d-4f6b-9c1d-2e3f4a5b6c7d/webhook';
  const jeton = { 'x-telegram-bot-api-secret-token': 'abc' };
  assert.equal(P.routePublique('POST', chemin, jeton, { cle: CLE, telegram: false }).code, 404);
  assert.equal(P.routePublique('POST', chemin, {}, { cle: CLE, telegram: true }).code, 404, 'sans jeton secret');
  assert.deepEqual(P.routePublique('POST', chemin, jeton, { cle: CLE, telegram: true }), { action: 'relayer' });
  assert.equal(P.routePublique('POST', '/webhook/court/webhook', jeton, { cle: CLE, telegram: true }).code, 404);
  assert.deepEqual(P.routePublique('POST', '/webhook/ArchiDemo0000001/telegram/webhook', jeton, { cle: CLE, telegram: true }), { action: 'relayer' });
  assert.equal(P.routePublique('POST', '/webhook/ArchiDemo0000001/a/b/webhook', jeton, { cle: CLE, telegram: true }).code, 404);
});

test('memeCle : refuse une cle attendue trop courte ou vide', () => {
  assert.equal(P.memeCle('abc', 'abc'), false);
  assert.equal(P.memeCle('', ''), false);
  assert.equal(P.memeCle(undefined, CLE), false);
  assert.equal(P.memeCle(CLE, CLE), true);
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
    const req = http.request(Object.assign({ host: '127.0.0.1', port }, options), rep => {
      const m = [];
      rep.on('data', x => m.push(x));
      rep.on('end', () => ok({ code: rep.statusCode, entetes: rep.headers, corps: Buffer.concat(m).toString('utf8') }));
    });
    req.on('error', non);
    req.end(corps || undefined);
  });
}

test('de bout en bout : le tunnel ne voit que la liste blanche, la page reste locale', async () => {
  const recus = [];
  const n8n = http.createServer((req, res) => {
    const m = [];
    req.on('data', x => m.push(x));
    req.on('end', () => {
      recus.push({ url: req.url, cle: req.headers['x-archi-cle'], corps: Buffer.concat(m).toString('utf8'), hote: req.headers.host });
      if (req.url === '/healthz') { res.writeHead(200); return res.end('ok'); }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ texte: 'reponse du faux n8n' }));
    });
  });
  await new Promise(x => n8n.listen(0, '127.0.0.1', x));
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'archi_portail_'));
  fs.writeFileSync(path.join(d, 'adresse_publique.txt'), 'https://abc-def.trycloudflare.com');
  fs.mkdirSync(path.join(d, 'outils'));
  fs.writeFileSync(path.join(d, 'outils', 'registre.json'), JSON.stringify({
    planificateur: { description: 'MODE D EMPLOI : faire quelque chose PLUS TARD. action=ajouter' }, lire_pdf: { description: 'lit un PDF. action=lire', sensible: true } }));
  const r = { port: 0, n8nPort: n8n.address().port, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: 'Camille', telegram: false };
  const portail = P.creerServeur(r);
  await new Promise(x => portail.listen(0, '127.0.0.1', x));
  r.port = portail.address().port;
  const local = { host: '127.0.0.1:' + r.port };
  const tunnel = { host: 'abc-def.trycloudflare.com', 'cf-ray': '1', 'cf-connecting-ip': '203.0.113.9', 'x-forwarded-for': '203.0.113.9' };
  try {
    // --- par le tunnel
    for (const chemin of ['/', '/api/etat', '/qrcode.js', '/rest/login', '/healthz']) {
      assert.equal((await appel(r.port, { path: chemin, headers: tunnel })).code, 404, 'tunnel GET ' + chemin);
    }
    assert.equal((await appel(r.port, { path: '/api/etat', headers: Object.assign({ 'x-archi-portail': '1' }, tunnel) })).code, 404);
    assert.equal((await appel(r.port, { path: '/api/message', method: 'POST', headers: Object.assign({ 'x-archi-portail': '1' }, tunnel) }, 'x')).code, 404);
    assert.equal((await appel(r.port, { path: '/webhook/telephone-archi', method: 'POST', headers: tunnel }, '{}')).code, 403);
    assert.equal(recus.length, 0, 'rien ne doit arriver a n8n sans la cle');
    const page = await appel(r.port, { path: '/telephone', headers: tunnel });
    assert.equal(page.code, 200);
    assert.ok(!page.corps.includes(CLE), 'la page du telephone ne contient aucun secret');
    assert.equal((await appel(r.port, { path: '/Archi.apk', headers: tunnel })).code, 404, 'pas d\'APK dans ce faux depot');
    const ok = await appel(r.port, { path: '/webhook/telephone-archi', method: 'POST', headers: Object.assign({ 'x-archi-cle': CLE, 'content-type': 'application/json' }, tunnel) }, '{"texte":"salut"}');
    assert.equal(ok.code, 200);
    assert.equal(JSON.parse(ok.corps).texte, 'reponse du faux n8n');
    assert.equal(recus.length, 1);
    assert.equal(recus[0].url, '/webhook/telephone-archi');
    assert.equal(recus[0].corps, '{"texte":"salut"}');
    assert.equal(recus[0].hote, '127.0.0.1:' + r.n8nPort);

    // --- une page piegee ouverte dans le navigateur du PC (DNS rebinding, ou appel direct sans notre en-tete)
    assert.equal((await appel(r.port, { path: '/', headers: { host: 'pirate.exemple.net:' + r.port } })).code, 404);
    assert.equal((await appel(r.port, { path: '/api/etat', headers: local })).code, 403);
    assert.equal((await appel(r.port, { path: '/api/message', method: 'POST', headers: Object.assign({ origin: 'https://pirate.exemple.net', 'x-archi-portail': '1' }, local) }, 'x')).code, 403);

    // --- le navigateur du PC
    const accueil = await appel(r.port, { path: '/', headers: local });
    assert.equal(accueil.code, 200);
    assert.match(accueil.entetes['content-security-policy'], /frame-ancestors 'none'/);
    assert.ok(!accueil.corps.includes(CLE));
    const etat = JSON.parse((await appel(r.port, { path: '/api/etat', headers: Object.assign({ 'x-archi-portail': '1' }, local) })).corps);
    assert.equal(etat.n8n, true);
    assert.equal(etat.cerveau.joignable, false);
    assert.equal(etat.utilisateur, 'Camille');
    assert.equal(etat.lien_telephone, 'https://abc-def.trycloudflare.com/telephone#k=' + CLE);
    assert.deepEqual(etat.outils.map(o => o.nom), ['planificateur', 'lire_pdf']);
    assert.equal(etat.outils[0].quoi, 'faire quelque chose PLUS TARD');
    assert.equal(etat.outils[1].sensible, true);
    const avant = recus.length;
    const msg = await appel(r.port, { path: '/api/message', method: 'POST', headers: Object.assign({ 'x-archi-portail': '1', 'content-type': 'application/json' }, local) }, '{"texte":"coucou"}');
    assert.equal(JSON.parse(msg.corps).texte, 'reponse du faux n8n');
    const dernier = recus[recus.length - 1];
    assert.equal(recus.length, avant + 1);
    assert.equal(dernier.url, '/webhook/telephone-archi');
    assert.equal(dernier.cle, CLE, 'le portail ajoute la cle cote PC');
    const boite = await appel(r.port, { path: '/api/annonces', method: 'POST', headers: Object.assign({ 'x-archi-portail': '1' }, local) });
    assert.equal(boite.code, 200);
    assert.equal(recus[recus.length - 1].url, '/webhook/telephone-boite');
  } finally {
    portail.close(); n8n.close();
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test('n8n arrete : la page recoit une phrase claire, pas une erreur brute', async () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'archi_portail_'));
  const r = { port: 0, n8nPort: 1, depot: d, base: d, etat: d, cle: CLE, lmUrl: 'http://127.0.0.1:1', modele: 'm', modeleVision: 'v', utilisateur: '', telegram: false };
  const portail = P.creerServeur(r);
  await new Promise(x => portail.listen(0, '127.0.0.1', x));
  r.port = portail.address().port;
  try {
    const rep = await appel(r.port, { path: '/api/message', method: 'POST', headers: { host: '127.0.0.1:' + r.port, 'x-archi-portail': '1' } }, '{}');
    assert.equal(rep.code, 502);
    assert.match(JSON.parse(rep.corps).texte, /n8n/);
  } finally { portail.close(); fs.rmSync(d, { recursive: true, force: true }); }
});
