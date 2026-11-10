// Tests de core/env.js : les scripts du coeur relisent le .env eux-memes, car le processus de n8n qui les lance
// (son « task runner ») ne leur transmet pas les reglages d'Archi.
//   node --test core/test/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');
const env = require('../env');

function dossier() { return fs.mkdtempSync(path.join(os.tmpdir(), 'archi_env_')); }

test('lire : memes regles que archi_env.py', () => {
  const d = dossier();
  const f = path.join(d, '.env');
  fs.writeFileSync(f, '\uFEFF# commentaire\nA=simple\nB="avec espaces # pas un commentaire"\nC=\'x\'\nD=valeur # fin\n' +
    'E="guillemets" # commentaire\nexport F=avec_export\nVIDE=\nligne bizarre\nCHEMIN=C:\\Users\\Camille Test\\Archi\r\n');
  assert.deepEqual(env.lire(f), { A: 'simple', B: 'avec espaces # pas un commentaire', C: 'x', D: 'valeur', E: 'guillemets',
    F: 'avec_export', VIDE: '', CHEMIN: 'C:\\Users\\Camille Test\\Archi' });
  assert.deepEqual(env.lire(path.join(d, 'absent')), {});
  fs.rmSync(d, { recursive: true, force: true });
});

test('charger : n\'ecrase jamais une variable deja definie, ignore les valeurs vides', () => {
  const d = dossier();
  const f = path.join(d, '.env');
  fs.writeFileSync(f, 'ARCHI_TEST_NOUVELLE=du_fichier\nARCHI_TEST_DEJA=du_fichier\nARCHI_TEST_VIDE=\n');
  process.env.ARCHI_TEST_DEJA = 'garde';
  delete process.env.ARCHI_TEST_NOUVELLE;
  assert.equal(env.charger(f), 1);
  assert.equal(process.env.ARCHI_TEST_NOUVELLE, 'du_fichier');
  assert.equal(process.env.ARCHI_TEST_DEJA, 'garde');
  assert.equal(process.env.ARCHI_TEST_VIDE, undefined);
  fs.rmSync(d, { recursive: true, force: true });
});

test('charger sans chemin : rien pendant les tests (jamais le vrai chateau)', () => {
  assert.ok(process.env.NODE_TEST_CONTEXT, 'ce test tourne sous node --test');
  assert.equal(env.charger(), 0);
});

test('un script du coeur lance SANS les reglages d\'Archi les retrouve dans le .env', () => {
  // comme le fait le « task runner » de n8n : un environnement reduit, sans ARCHI_BASE
  const d = dossier();
  const base = path.join(d, 'chateau test');
  fs.mkdirSync(path.join(base, 'outils'), { recursive: true });
  fs.writeFileSync(path.join(base, 'outils', 'registre.json'), JSON.stringify({ outil_du_test: { description: 'un outil du faux chateau', script: 'x.py' } }));
  const f = path.join(d, '.env');
  fs.writeFileSync(f, 'ARCHI_BASE=' + base + '\n');
  const reduit = { PATH: process.env.PATH, ARCHI_ENV: f };   // ni ARCHI_BASE, ni NODE_TEST_CONTEXT
  for (const k of ['SystemRoot', 'TEMP', 'TMP', 'USERPROFILE', 'HOME']) if (process.env[k]) reduit[k] = process.env[k];
  const sortie = cp.execFileSync(process.execPath, [path.join(__dirname, '..', 'outils_maison.js')],
    { input: JSON.stringify({ action: 'liste' }), env: reduit }).toString('utf8').trim().split(/\r?\n/).pop();
  assert.match(sortie, /un outil du faux chateau/);
  // et une variable deja la gagne sur le fichier
  const autre = path.join(d, 'autre');
  fs.mkdirSync(path.join(autre, 'outils'), { recursive: true });
  fs.writeFileSync(path.join(autre, 'outils', 'registre.json'), JSON.stringify({ outil_impose: { description: 'un outil du chateau impose', script: 'x.py' } }));
  const sortie2 = cp.execFileSync(process.execPath, [path.join(__dirname, '..', 'outils_maison.js')],
    { input: JSON.stringify({ action: 'liste' }), env: Object.assign({}, reduit, { ARCHI_BASE: autre }) }).toString('utf8');
  assert.match(sortie2, /un outil du chateau impose/);
  fs.rmSync(d, { recursive: true, force: true });
});
