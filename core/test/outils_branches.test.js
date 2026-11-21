// Les quatre outils branches le 21/11, lances PAR LE VRAI LANCEUR (core/outils_maison.js) avec le registre du depot et
// un chateau temporaire : node --test "core/test/*.test.js"
// Hors ligne : sur une installation neuve (pas de cle, pas d'agenda relie, pas de monteur installe), chacun doit le DIRE
// proprement, et la liste des outils doit les annoncer.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { lancer } = require('../outils_maison');
const promesses = require('../promesses');

const DEPOT = path.join(__dirname, '..', '..');
const B = fs.mkdtempSync(path.join(os.tmpdir(), 'archi-branches-'));
const NOMS = ['agenda', 'recherche_web', 'image_lien', 'monteur', 'planificateur'];
fs.mkdirSync(path.join(B, 'outils'), { recursive: true });
for (const n of NOMS) fs.cpSync(path.join(DEPOT, 'outils', n), path.join(B, 'outils', n), { recursive: true });
fs.copyFileSync(path.join(DEPOT, 'chateau_exemple', 'outils', 'registre.json'), path.join(B, 'outils', 'registre.json'));
const PYTHON = process.env.ARCHI_PY || (process.platform === 'win32' ? 'python' : 'python3');
// une installation neuve : aucun reglage de ces outils
for (const k of ['TAVILY_API_KEY', 'ARCHI_DEPOT', 'ARCHI_SERVEUR_PY', 'ARCHI_SERVEUR_DONNEES', 'ARCHI_GOOGLE_CLIENT', 'ARCHI_WHISPER', 'ARCHI_WHISPER_DIR', 'ARCHI_WHISPER_EXE', 'ARCHI_WHISPER_MODELE', 'ARCHI_FFMPEG']) delete process.env[k];
process.env.ARCHI_WHISPER_DIR = path.join(B, 'pas_de_whisper');
const appel = (outil, parametres, accord) => lancer({ action: 'utiliser', outil, parametres, accord }, { base: B, python: PYTHON });

test('outils branches : la liste des outils les annonce', () => {
  const r = lancer({ action: 'liste' }, { base: B, python: PYTHON });
  assert.ok(r.ok);
  for (const n of ['agenda', 'recherche_web', 'image_lien', 'monteur']) assert.ok(JSON.stringify(r).includes(n), n);
});

test('recherche_web sans cle : dit qu\'elle n\'est pas branchee, sans rien inventer', () => {
  const r = appel('recherche_web', { texte: 'prix du gaz' });
  assert.strictEqual(r.ok, false);
  assert.match(r.phrase_pour_utilisateur, /n'est pas branchée/);
  assert.ok(!('texte' in r));
});

test('agenda pas relie : voir et ajouter le disent, sans essai a blanc trompeur', () => {
  for (const p of [{ action: 'voir' }, { action: 'ajouter', titre: 'Dentiste', quand: 'jeudi 18h' }, { action: 'ajouter', titre: 'Dentiste', quand: 'jeudi 18h', confirmer: 'oui' }]) {
    const r = appel('agenda', p);
    assert.strictEqual(r.ok, false, JSON.stringify(p));
    assert.match(r.phrase_pour_utilisateur, /pas branché|pas relié/);
    assert.ok(!r.essai);
  }
});

test('image_lien : une adresse du PC ou du reseau local est refusee par le code', () => {
  for (const lien of ['http://127.0.0.1:8765/sante', 'http://192.168.1.1/photo.jpg', 'file:///C:/Windows/win.ini', 'http://localhost/x.png']) {
    const r = appel('image_lien', { lien });
    assert.strictEqual(r.ok, false, lien);
    assert.match(r.phrase_pour_utilisateur, /Je n'ouvre pas cette adresse/);
  }
});

test('monteur pas installe : dit ce qui manque, ne lance rien, meme avec confirmer=oui', () => {
  for (const p of [{ action: 'etat' }, { action: 'monter', confirmer: 'oui' }]) {
    const r = appel('monteur', p);
    assert.strictEqual(r.ok, false);
    assert.match(r.phrase_pour_utilisateur, /n'est pas installé|Je n'ai rien lancé/);
    assert.ok(!r.lance);
  }
});

test('outils branches : un echec de ces outils est un echec pour le verificateur', () => {
  const pas = (outil, parametres, r) => ({ action: { tool: 'outils_maison', toolInput: JSON.stringify({ action: 'utiliser', outil, parametres }) }, observation: JSON.stringify(r) });
  const steps = [pas('monteur', { action: 'monter', confirmer: 'oui' }, appel('monteur', { action: 'monter', confirmer: 'oui' }))];
  assert.deepStrictEqual(promesses.actesDesSteps(steps).map(a => a.outil + ':' + a.action + ':' + a.statut), ['monteur:monter:erreur']);
  // une reponse honnete apres ces echecs ne declenche aucun avertissement
  for (const reponse of ["Le monteur vidéo n'est pas installé sur ce PC : il manque ffmpeg.exe. Je n'ai rien lancé.",
    "La recherche sur le web n'est pas branchée : il manque la clé du moteur de recherche. Je n'ai rien cherché.",
    "L'agenda n'est pas relié à un compte Google, je ne peux ni le lire ni y écrire."]) {
    assert.deepStrictEqual(promesses.promessesADire(reponse, steps), [], reponse);
    assert.deepStrictEqual(promesses.promessesEnLAir(reponse, steps), [], reponse);
  }
});
