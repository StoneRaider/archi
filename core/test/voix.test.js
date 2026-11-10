// Tests de core/voix.js : l'oreille (ffmpeg + whisper.cpp) et la voix (Pocket TTS + ffmpeg), sans rien installer.
// Les programmes sont remplaces par des faux : on verifie ce qu'Archi leur demande et ce qu'il fait de leur reponse.
//   node --test core/test/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const cp = require('child_process');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const V = require('../voix');

function dossier() { return fs.mkdtempSync(path.join(os.tmpdir(), 'archi_voix_test_')); }
/** un faux PC installe : whisper-cli.exe et son modele existent (vides), le reste vient des faux programmes */
function installe() {
  const d = dossier();
  const w = path.join(d, 'programmes', 'whisper', 'whisper-bin-x64', 'Release');
  fs.mkdirSync(w, { recursive: true });
  fs.mkdirSync(path.join(d, 'programmes', 'whisper', 'modeles'), { recursive: true });
  fs.writeFileSync(path.join(w, 'whisper-cli.exe'), '');
  fs.writeFileSync(path.join(d, 'programmes', 'whisper', 'modeles', 'ggml-small.bin'), '');
  return d;
}

test('reglages : programmes trouves dans le dossier d Archi, langue sure, voix coupee sur demande', () => {
  const d = installe();
  try {
    const r = V.reglages({ ARCHI_DEPOT: d });
    assert.equal(r.active, true);
    assert.ok(r.whisper.endsWith(path.join('Release', 'whisper-cli.exe')), r.whisper);
    assert.ok(r.modele.endsWith('ggml-small.bin'));
    assert.equal(r.langue, 'fr');
    assert.equal(r.portVoix, 5683);
    assert.ok(r.fils >= 2 && r.fils <= 8);
    assert.equal(V.reglages({ ARCHI_DEPOT: d, ARCHI_VOIX: 'Non' }).active, false);
    assert.equal(V.reglages({ ARCHI_DEPOT: d, ARCHI_LANGUE: 'en' }).langue, 'en');
    assert.equal(V.reglages({ ARCHI_DEPOT: d, ARCHI_LANGUE: 'fr; calc' }).langue, 'fr', 'la langue part dans une ligne de commande');
    assert.equal(V.reglages({ ARCHI_DEPOT: d, ARCHI_WHISPER_EXE: 'X:/w.exe', ARCHI_VOIX_PORT: '6001' }).whisper, 'X:/w.exe');
    assert.equal(V.reglages({ ARCHI_DEPOT: path.join(d, 'vide') }).whisper, '');
  } finally { fs.rmSync(d, { recursive: true, force: true }); }
});

test('entendre : les bruits et les phrases fantomes de Whisper ne deviennent pas une question', () => {
  assert.equal(V.entendre('\n [Musique]  Quels outils   as-tu ?\n'), 'Quels outils as-tu ?');
  assert.equal(V.entendre('(rires) *soupir* Bonjour Archi.'), 'Bonjour Archi.');
  assert.equal(V.entendre('Sous-titres réalisés par la communauté d\u2019Amara.org'), '');
  assert.equal(V.entendre("Merci d'avoir regardé cette vidéo !"), '');
  assert.equal(V.entendre(' ... '), '');
  assert.equal(V.entendre(''), '');
  assert.equal(V.entendre('[BLANK_AUDIO]'), '');
});

test('raccourcir : une longue reponse s arrete a la fin d une phrase', () => {
  assert.equal(V.raccourcir('Court.'), 'Court.');
  const long = 'Premiere phrase assez longue pour compter. Deuxieme phrase qui continue encore. ' + 'mot '.repeat(400);
  const r = V.raccourcir(long, 100);
  assert.ok(r.startsWith('Premiere phrase assez longue pour compter. Deuxieme phrase qui continue encore.'), r);
  assert.ok(r.endsWith("La suite est à l'écran."));
  assert.ok(r.length < 140);
  const sansPoint = V.raccourcir('mot '.repeat(400), 100);
  assert.ok(sansPoint.endsWith(". La suite est à l'écran.") && sansPoint.length < 140, sansPoint);
});

test('nettoyerSimple : ni lien, ni symbole, ni emoji a prononcer', () => {
  assert.equal(V.nettoyerSimple('**Voici** le lien : https://exemple.fr/a?b=1 \u{1F600} `code`'), 'Voici le lien : code');
});

test('transcrire : ffmpeg puis whisper, avec les bons arguments', async () => {
  const d = installe();
  const son = path.join(d, 'question.m4a');
  fs.writeFileSync(son, 'faux son');
  const appels = [];
  const lancer = async (cmd, args) => { appels.push([path.basename(cmd)].concat(args)); return cmd.includes('whisper') ? ' [Musique] Quelle heure est-il ?\n' : ''; };
  try {
    const r = V.reglages({ ARCHI_DEPOT: d, ARCHI_LANGUE: 'fr' });
    assert.deepEqual(await V.transcrire(son, r, { lancer }), { ok: true, texte: 'Quelle heure est-il ?' });
    assert.equal(appels.length, 2);
    const [ff, wh] = appels;
    assert.equal(ff[0], 'ffmpeg');
    assert.ok(ff.includes(son) && ff.join(' ').includes('-ar 16000 -ac 1'), ff.join(' '));
    const wav = ff[ff.length - 1];
    assert.ok(wav.endsWith('.wav') && !wav.startsWith(d), 'le WAV de travail va dans le dossier temporaire');
    assert.equal(wh[0], 'whisper-cli.exe');
    assert.ok(wh.join(' ').includes('-l fr -f ' + wav + ' -nt -np'), wh.join(' '));
    // rien d'intelligible : pas de question inventee
    assert.deepEqual(await V.transcrire(son, r, { lancer: async c => (c.includes('whisper') ? 'Sous-titrage ST 501' : '') }), { ok: false, raison: 'rien_entendu' });
    // programme en panne : une raison, jamais d'exception
    const panne = await V.transcrire(son, r, { lancer: async () => { throw new Error('ffmpeg introuvable'); } });
    assert.equal(panne.ok, false); assert.equal(panne.raison, 'erreur_oreille'); assert.match(panne.detail, /ffmpeg introuvable/);
    assert.deepEqual(await V.transcrire(path.join(d, 'absent.m4a'), r, { lancer }), { ok: false, raison: 'fichier_absent' });
    assert.deepEqual(await V.transcrire(son, V.reglages({ ARCHI_DEPOT: d, ARCHI_VOIX: 'non' }), { lancer }), { ok: false, raison: 'voix_desactivee' });
    assert.deepEqual(await V.transcrire(son, V.reglages({ ARCHI_DEPOT: path.join(d, 'vide') }), { lancer }), { ok: false, raison: 'oreille_absente' });
  } finally { fs.rmSync(d, { recursive: true, force: true }); }
});

test('dire : texte nettoye -> serveur de voix -> OGG en base64', async () => {
  const d = installe();
  const demandes = [];
  const synthese = async (port, texte) => { demandes.push([port, texte]); return Buffer.from('RIFFfauxwav'); };
  const lancer = async (cmd, args) => {
    assert.equal(path.basename(cmd), 'ffmpeg');
    assert.ok(args.join(' ').includes('-c:a libopus'), args.join(' '));
    assert.equal(fs.readFileSync(args[args.indexOf('-i') + 1], 'utf8'), 'RIFFfauxwav');
    fs.writeFileSync(args[args.length - 1], 'OggSfaux');
    return '';
  };
  try {
    const r = V.reglages({ ARCHI_DEPOT: d, ARCHI_VOIX_PORT: '6002' });   // pas de nettoyeur dans ce faux depot : secours simple
    const s = await V.dire('**Bonjour** \u{1F600} tout va bien.', r, { lancer, synthese });
    assert.deepEqual(s, { ok: true, audio_ogg_base64: Buffer.from('OggSfaux').toString('base64'), texte_dit: 'Bonjour tout va bien.' });
    assert.deepEqual(demandes, [[6002, 'Bonjour tout va bien.']]);
    assert.equal(fs.readdirSync(os.tmpdir()).filter(f => f.startsWith('archi_voix_') && /\.(wav|ogg)$/.test(f)).length, 0, 'aucun son ne traine');
    // le serveur de voix ne repond pas : reponse ecrite seulement, avec la raison
    const muet = await V.dire('Bonjour.', r, { lancer, synthese: async () => { throw new Error('ECONNREFUSED'); } });
    assert.equal(muet.ok, false); assert.equal(muet.raison, 'voix_muette');
    assert.deepEqual(await V.dire(' \u{1F600} ', r, { lancer, synthese }), { ok: false, raison: 'rien_a_dire' });
    assert.deepEqual(await V.dire('Bonjour.', V.reglages({ ARCHI_DEPOT: d, ARCHI_VOIX: 'non' }), { lancer, synthese }), { ok: false, raison: 'voix_desactivee' });
  } finally { fs.rmSync(d, { recursive: true, force: true }); }
});

test('dire : le vrai nettoyeur du depot dit les heures et les montants en toutes lettres', async () => {
  const dits = [];
  const r = V.reglages({ ARCHI_DEPOT: path.join(__dirname, '..', '..'), ARCHI_VOIX_PORT: '6003' });
  const s = await V.dire('Il est 14h30, total : 12 €.', r, { synthese: async (p, t) => { dits.push(t); return Buffer.from('x'); },
    lancer: async (cmd, args, ms, entree) => {
      if (path.basename(cmd) === 'ffmpeg') { fs.writeFileSync(args[args.length - 1], 'o'); return ''; }
      return cp.execFileSync(cmd, args, { input: entree, encoding: 'utf8' });   // le nettoyeur, pour de vrai
    } });
  assert.equal(s.ok, true);
  assert.match(dits[0], /quatorze heures trente/);
  assert.match(dits[0], /douze euros/);
});

test('synthese : un POST multipart « text » vers 127.0.0.1, et un WAV en retour', async () => {
  let recu = null;
  const serveur = http.createServer((req, res) => {
    const m = []; req.on('data', x => m.push(x));
    req.on('end', () => { recu = { url: req.url, methode: req.method, type: req.headers['content-type'], corps: Buffer.concat(m).toString('utf8') };
      res.writeHead(req.url === '/tts' ? 200 : 404); res.end('RIFFson'); });
  });
  await new Promise(x => serveur.listen(0, '127.0.0.1', x));
  try {
    const wav = await V.synthese(serveur.address().port, 'Bonjour à toi.', 5000);
    assert.equal(wav.toString(), 'RIFFson');
    assert.equal(recu.methode, 'POST'); assert.equal(recu.url, '/tts');
    assert.match(recu.type, /^multipart\/form-data; boundary=----archi[0-9a-f]{24}$/);
    assert.ok(recu.corps.includes('Content-Disposition: form-data; name="text"\r\n\r\nBonjour à toi.\r\n'));
    assert.equal(await V.paroleVivante(serveur.address().port, 2000), true);
  } finally { serveur.close(); }
  assert.equal(await V.paroleVivante(1, 500), false);
  await assert.rejects(V.synthese(1, 'x', 1000));
});

test('boucle : la voix dit la phrase temoin, l oreille la reecoute, et on compare', async () => {
  const d = installe();
  const r = V.reglages({ ARCHI_DEPOT: d });
  const fabrique = entendu => ({
    synthese: async () => Buffer.from('wav'),
    lancer: async (cmd, args) => {
      if (cmd.includes('whisper')) return entendu;
      if (args.includes('libopus')) fs.writeFileSync(args[args.length - 1], 'ogg');
      return '';
    },
  });
  try {
    const bon = await V.boucle(r, fabrique(' Bonjour, quel outil as-tu ?'));
    assert.equal(bon.ok, true); assert.equal(bon.entendu, 'Bonjour, quel outil as-tu ?'); assert.equal(bon.dit, 'Bonjour, quels outils as-tu ?');
    assert.ok(bon.ms_parole >= 0 && bon.ms_oreille >= 0);
    const faux = await V.boucle(r, fabrique('Il fait beau aujourd hui.'));
    assert.equal(faux.ok, false); assert.equal(faux.raison, 'mots_differents');
    const sourd = await V.boucle(r, fabrique(''));
    assert.deepEqual([sourd.ok, sourd.etape, sourd.raison], [false, 'oreille', 'rien_entendu']);
    const muet = await V.boucle(r, { lancer: async () => '', synthese: async () => { throw new Error('port ferme'); } });
    assert.deepEqual([muet.ok, muet.etape, muet.raison], [false, 'parole', 'voix_muette']);
    assert.equal(fs.readdirSync(os.tmpdir()).filter(f => f.startsWith('archi_boucle_')).length, 0);
  } finally { fs.rmSync(d, { recursive: true, force: true }); }
});

test('en ligne de commande : une ligne JSON, meme quand la voix est coupee', () => {
  const out = cp.execFileSync(process.execPath, [path.join(__dirname, '..', 'voix.js')], {
    input: JSON.stringify({ action: 'dire', texte: 'Bonjour' }), encoding: 'utf8',
    env: Object.assign({}, process.env, { ARCHI_SANS_ENV: '1', ARCHI_VOIX: 'non' }) });
  assert.deepEqual(JSON.parse(out.trim().split(/\r?\n/).pop()), { ok: false, raison: 'voix_desactivee' });
  const etat = cp.execFileSync(process.execPath, [path.join(__dirname, '..', 'voix.js')], {
    input: '{}', encoding: 'utf8', env: Object.assign({}, process.env, { ARCHI_SANS_ENV: '1', ARCHI_VOIX: 'non' }) });
  assert.deepEqual(JSON.parse(etat.trim().split(/\r?\n/).pop()), { active: false, oreille: false, parole: false });
});
