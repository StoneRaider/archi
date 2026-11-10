// core/voix.js - l'oreille et la voix d'Archi. Tout tourne sur le PC, rien ne part vers un service en ligne.
//
//   L'oreille : ffmpeg (-> WAV 16 kHz mono) puis whisper.cpp (whisper-cli.exe) et son modele.
//   La voix   : Pocket TTS, un petit serveur local lance par lancer_archi.ps1 (127.0.0.1 seulement) -> WAV,
//               puis ffmpeg -> OGG/Opus, que l'appli et la page d'accueil savent jouer.
//
// Appele par les noeuds Code de n8n : un objet JSON sur l'entree standard, UNE ligne JSON en sortie.
//   {"action":"transcrire","fichier":"C:/.../question.m4a"}  -> {"ok":true,"texte":"..."}
//   {"action":"dire","texte":"..."}                          -> {"ok":true,"audio_ogg_base64":"...","texte_dit":"..."}
//   {"action":"etat"}                                        -> {"active":true,"oreille":true,"parole":true}
//   {"action":"boucle"}                                      -> la voix dit une phrase, l'oreille la reecoute (controle)
// En cas d'echec : {"ok":false,"raison":"...","detail":"..."} - jamais d'exception, l'agent repond alors par ecrit.
'use strict';
require('./env').charger();   // les reglages du .env : le processus de n8n qui nous lance ne les transmet pas
const cp = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');

const BOM = new RegExp('^' + String.fromCharCode(0xFEFF));   // la marque d'ordre des octets que PowerShell glisse devant son envoi
const MAX_SON_S = 120;    // au plus deux minutes de son ecoutees (l'appli et la page s'arretent a une minute)
const DELAI_VOIX_MS = 45000;   // plafond TOTAL pour fabriquer la voix : au-dela, la reponse part par ecrit seulement
const MAX_DIT = 1200;   // au-dela, la voix s'arrete a la fin d'une phrase : la suite se lit a l'ecran
// Whisper « invente » ces phrases quand l'enregistrement est vide ou brouille
const FANTOMES = ['amara.org', 'sous-titres realises', 'sous-titrage', "merci d'avoir regarde", 'abonnez-vous', 'sous-titres par'];

/** Cherche un fichier par son nom, sur quelques niveaux (les zips officiels rangent leurs programmes dans un sous-dossier). */
function trouver(dossier, nom, profondeur) {
  let liste = [];
  try { liste = fs.readdirSync(dossier, { withFileTypes: true }); } catch (e) { return ''; }
  for (const x of liste) if (!x.isDirectory() && x.name.toLowerCase() === nom.toLowerCase()) return path.join(dossier, x.name);
  if (profondeur > 0) {
    for (const x of liste) {
      if (!x.isDirectory()) continue;
      const f = trouver(path.join(dossier, x.name), nom, profondeur - 1);
      if (f) return f;
    }
  }
  return '';
}

function reglages(env) {
  env = env || process.env;
  const depot = env.ARCHI_DEPOT || path.join(__dirname, '..');
  const prog = path.join(depot, 'programmes');
  const coeurs = Math.max(1, (os.cpus() || []).length);
  return {
    active: String(env.ARCHI_VOIX || 'oui').trim().toLowerCase() !== 'non',
    ffmpeg: env.ARCHI_FFMPEG || trouver(path.join(prog, 'ffmpeg'), 'ffmpeg.exe', 3) || 'ffmpeg',   // le ffmpeg prive, sinon celui du PATH
    whisper: env.ARCHI_WHISPER_EXE || trouver(path.join(prog, 'whisper'), 'whisper-cli.exe', 3),
    modele: env.ARCHI_WHISPER_MODELE || trouver(path.join(prog, 'whisper', 'modeles'), 'ggml-small.bin', 0),
    langue: /^[a-z]{2}$/.test(String(env.ARCHI_LANGUE || '')) ? env.ARCHI_LANGUE : 'fr',
    fils: Math.max(2, Math.min(8, coeurs - 2)),
    portVoix: parseInt(env.ARCHI_VOIX_PORT || '5683', 10),
    nettoyeur: path.join(depot, 'pc', 'voix', 'nettoyer_voix.js'),
  };
}

/** Lance un programme sans bloquer (n8n coupe un noeud qui ne repond plus pendant 30 s). Rend sa sortie standard. */
function lancer(cmd, args, ms, entree) {
  return new Promise((ok, non) => {
    const p = cp.execFile(cmd, args, { timeout: ms, windowsHide: true, encoding: 'buffer', maxBuffer: 64 * 1024 * 1024 },
      (e, out) => (e ? non(e) : ok(out.toString('utf8'))));
    p.on('error', () => { /* deja rendu par le rappel ci-dessus */ });
    try { p.stdin.end(entree === undefined ? '' : entree); } catch (e) { /* programme introuvable : le rappel le dira */ }
  });
}

/** Efface les fichiers de travail oublies par un traitement interrompu (n8n coupe un noeud trop long sans menage). */
function menage() {
  try {
    const limite = Date.now() - 30 * 60 * 1000;
    for (const f of fs.readdirSync(os.tmpdir())) {
      if (!/^archi_(oreille|voix|boucle|question|memoire)_/.test(f)) continue;
      const c = path.join(os.tmpdir(), f);
      try { if (fs.statSync(c).mtimeMs < limite) fs.unlinkSync(c); } catch (e) { /* pris par un autre programme */ }
    }
  } catch (e) { /* dossier temporaire illisible : tant pis */ }
}

// ---------------------------------------------------------------- l'oreille
/** Le texte rendu par Whisper, nettoye : sans les bruits entre crochets, et vide si c'est une phrase fantome. */
function entendre(brut) {
  const texte = String(brut || '')
    .replace(/\[[^\]]{0,40}\]|\([^)]{0,40}\)|\*[^*]{0,40}\*/g, ' ')   // [Musique], (rires), *soupir*
    .replace(/\s+/g, ' ').trim();
  const plat = texte.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[\u2018\u2019]/g, "'");
  if (!plat.replace(/[ .,;:!?…-]/g, '') || FANTOMES.some(f => plat.includes(f))) return '';
  return texte;
}

async function transcrire(fichier, r, deps) {
  r = r || reglages();
  const L = (deps && deps.lancer) || lancer;
  if (!r.active) return { ok: false, raison: 'voix_desactivee' };
  if (!r.whisper || !r.modele || !fs.existsSync(r.whisper) || !fs.existsSync(r.modele)) return { ok: false, raison: 'oreille_absente' };
  if (!fichier || !fs.existsSync(fichier)) return { ok: false, raison: 'fichier_absent' };
  menage();
  const wav = path.join(os.tmpdir(), 'archi_oreille_' + crypto.randomBytes(6).toString('hex') + '.wav');
  try {
    // delais internes (60 s + 150 s) plus courts que celui du noeud n8n qui nous attend (240 s)
    await L(r.ffmpeg, ['-y', '-loglevel', 'error', '-i', fichier, '-t', String(MAX_SON_S), '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', wav], 60000);
    const brut = await L(r.whisper, ['-m', r.modele, '-l', r.langue, '-f', wav, '-nt', '-np', '-t', String(r.fils)], 150000);
    const texte = entendre(brut);
    return texte ? { ok: true, texte } : { ok: false, raison: 'rien_entendu' };
  } catch (e) {
    return { ok: false, raison: 'erreur_oreille', detail: String((e && e.message) || e).replace(/\s+/g, ' ').slice(0, 200) };
  } finally {
    try { fs.unlinkSync(wav); } catch (e) { /* deja absent */ }
  }
}

// ---------------------------------------------------------------- la voix
/** Coupe un texte trop long a la fin d'une phrase, et le dit. */
function raccourcir(texte, max) {
  const t = String(texte || '').trim();
  max = max || MAX_DIT;
  if (t.length <= max) return t;
  const debut = t.slice(0, max);
  const fin = Math.max(debut.lastIndexOf('. '), debut.lastIndexOf('! '), debut.lastIndexOf('? '));
  return (fin > max / 3 ? debut.slice(0, fin + 1) : debut.replace(/\s+\S*$/, '') + '.') + " La suite est à l'écran.";
}

/** Ce que la voix prononcerait mal : les noms d'outils (prises_shelly, imprimante_3d) et « 3D ». */
function prononcer(texte) {
  return String(texte || '').replace(/_/g, ' ').replace(/\b3 ?d\b/gi, 'trois D');
}

/** Secours si le nettoyeur complet manque : on retire ce qui ne se prononce pas. */
function nettoyerSimple(texte) {
  return String(texte || '').replace(/https?:\/\/\S+/g, ' ').replace(/[*#_`>|~\[\]{}<]/g, ' ')
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, ' ').replace(/\s+/g, ' ').trim();
}

/** Le texte « a dire a voix haute » : heures, montants, sigles... (pc/voix/nettoyer_voix.js, le meme que sur le PC). */
async function nettoyer(texte, r, L) {
  try {
    if (!fs.existsSync(r.nettoyeur)) throw new Error('absent');
    const t = (await L(process.execPath, [r.nettoyeur], 15000, String(texte || ''))).trim();
    if (t) return t;
  } catch (e) { /* secours ci-dessous */ }
  return nettoyerSimple(texte);
}

/** Corps « multipart/form-data » d'un seul champ texte, comme l'attend Pocket TTS (POST /tts). */
function corpsMultipart(texte, limite) {
  return Buffer.from('--' + limite + '\r\nContent-Disposition: form-data; name="text"\r\n\r\n' + texte + '\r\n--' + limite + '--\r\n', 'utf8');
}

/** Demande le son au serveur de voix local : un WAV. */
function synthese(port, texte, ms) {
  return new Promise((ok, non) => {
    const limite = '----archi' + crypto.randomBytes(12).toString('hex');
    const corps = corpsMultipart(texte, limite);
    const req = http.request({ host: '127.0.0.1', port, path: '/tts', method: 'POST', timeout: ms,
      headers: { 'Content-Type': 'multipart/form-data; boundary=' + limite, 'Content-Length': corps.length } }, rep => {
      const m = [];
      rep.on('data', x => m.push(x));
      rep.on('end', () => (rep.statusCode === 200 ? ok(Buffer.concat(m)) : non(new Error('la voix a repondu ' + rep.statusCode))));
      rep.on('error', non);
    });
    // un plafond TOTAL, pas seulement un delai de silence : un serveur qui traine ne retient pas la reponse ecrite
    const plafond = setTimeout(() => req.destroy(new Error('la voix met trop de temps')), ms);
    req.on('close', () => clearTimeout(plafond));
    req.on('timeout', () => req.destroy(new Error('la voix met trop de temps')));
    req.on('error', non);
    req.end(corps);
  });
}

async function dire(texte, r, deps) {
  r = r || reglages();
  const L = (deps && deps.lancer) || lancer;
  const S = (deps && deps.synthese) || synthese;
  if (!r.active) return { ok: false, raison: 'voix_desactivee' };
  const dit = raccourcir(await nettoyer(prononcer(texte), r, L));
  if (!dit) return { ok: false, raison: 'rien_a_dire' };
  const base = path.join(os.tmpdir(), 'archi_voix_' + crypto.randomBytes(6).toString('hex'));
  try {
    let wav;
    try { wav = await S(r.portVoix, dit, DELAI_VOIX_MS); }
    catch (e) { return { ok: false, raison: 'voix_muette', detail: String((e && e.message) || e).slice(0, 200) }; }
    fs.writeFileSync(base + '.wav', wav);
    // Pocket diffuse en continu : l'en-tete de son WAV annonce une taille fictive, ffmpeg lit jusqu'au bout
    await L(r.ffmpeg, ['-y', '-loglevel', 'error', '-i', base + '.wav', '-c:a', 'libopus', '-b:a', '32k', base + '.ogg'], 30000);
    return { ok: true, audio_ogg_base64: fs.readFileSync(base + '.ogg').toString('base64'), texte_dit: dit };
  } catch (e) {
    return { ok: false, raison: 'erreur_voix', detail: String((e && e.message) || e).replace(/\s+/g, ' ').slice(0, 200) };
  } finally {
    for (const x of ['.wav', '.ogg']) { try { fs.unlinkSync(base + x); } catch (e) { /* deja absent */ } }
  }
}

/** Le serveur de voix repond-il ? (un simple GET sur sa page) */
function paroleVivante(port, ms) {
  return new Promise(ok => {
    const req = http.request({ host: '127.0.0.1', port, path: '/', method: 'GET', timeout: ms || 1500 }, rep => { rep.resume(); ok(rep.statusCode < 500); });
    req.on('timeout', () => { req.destroy(); ok(false); });
    req.on('error', () => ok(false));
    req.end();
  });
}

async function etat(r) {
  r = r || reglages();
  const oreille = !!(r.active && r.whisper && r.modele && fs.existsSync(r.whisper) && fs.existsSync(r.modele));
  return { active: r.active, oreille, parole: r.active ? await paroleVivante(r.portVoix) : false };
}

const TEMOINS = { fr: ['Bonjour, quels outils as-tu ?', 'bonjour', 'outil'], en: ['Hello, which tools do you have?', 'hello', 'tool'] };
/** Le controle complet, sans micro : la voix dit une phrase temoin, l'oreille la reecoute (verifier_archi.bat). */
async function boucle(r, deps) {
  r = r || reglages();
  const [phrase, ...mots] = TEMOINS[r.langue] || TEMOINS.fr;
  const t0 = Date.now();
  const d = await dire(phrase, r, deps);
  if (!d.ok) return { ok: false, etape: 'parole', raison: d.raison, detail: d.detail || '' };
  const f = path.join(os.tmpdir(), 'archi_boucle_' + crypto.randomBytes(6).toString('hex') + '.ogg');
  const t1 = Date.now();
  try {
    fs.writeFileSync(f, Buffer.from(d.audio_ogg_base64, 'base64'));
    const t = await transcrire(f, r, deps);
    if (!t.ok) return { ok: false, etape: 'oreille', raison: t.raison, detail: t.detail || '' };
    const plat = t.texte.toLowerCase();
    const compris = TEMOINS[r.langue] ? mots.every(m => plat.includes(m)) : plat.length > 3;   // autre langue : on ne compare pas les mots
    return { ok: compris, etape: 'comparaison', raison: compris ? '' : 'mots_differents', dit: phrase, entendu: t.texte, ms_parole: t1 - t0, ms_oreille: Date.now() - t1 };
  } finally { try { fs.unlinkSync(f); } catch (e) { /* deja absent */ } }
}

if (require.main === module) {
  (async () => {
    let e = {};
    // PowerShell (verifier_archi.bat) glisse parfois une marque d'ordre des octets devant ce qu'il envoie : on l'enleve
    try { e = JSON.parse(fs.readFileSync(0, 'utf8').replace(BOM, '').trim() || '{}'); } catch (x) { e = {}; }
    let s;
    if (e.action === 'transcrire') s = await transcrire(String(e.fichier || ''));
    else if (e.action === 'dire') s = await dire(String(e.texte || ''));
    else if (e.action === 'boucle') s = await boucle();
    else s = await etat();
    process.stdout.write('\n' + JSON.stringify(s) + '\n');
  })().catch(x => { process.stdout.write('\n' + JSON.stringify({ ok: false, raison: 'erreur', detail: String((x && x.message) || x).slice(0, 200) }) + '\n'); });
}

module.exports = { reglages, trouver, entendre, raccourcir, prononcer, nettoyerSimple, corpsMultipart, menage, transcrire, dire, etat, boucle, synthese, paroleVivante, MAX_DIT };
