// Tests de la carte de la tache (core/tache.js) : node --test core/test
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');
const { creer, traiter } = require('../tache');

const DEPOT = path.join(__dirname, '..', '..');
function dossier() { return fs.mkdtempSync(path.join(os.tmpdir(), 'archi-tache-')); }
function horloge(depart) { let t = depart; const f = () => t; f.avance = ms => { t += ms; }; return f; }

test('une tache : debut, deux etapes, fin ; la page voit tout dans l ordre', () => {
  const h = horloge(1000000), c = creer({ etat: dossier(), maintenant: h });
  c.debut({ source: 'appli', texte: 'Rappelle-moi le dentiste' });
  let v = c.voir();
  assert.strictEqual(v.tache.en_cours, true);
  assert.strictEqual(v.tache.demande, 'Rappelle-moi le dentiste');
  h.avance(500);
  const n = c.etapeDebut({ outil: 'planificateur', action: 'ajouter' });
  assert.strictEqual(n, 1);
  v = c.voir();
  assert.strictEqual(v.tache.etapes[0].fin, 0, 'l etape tourne encore');
  h.avance(1200);
  assert.ok(c.etapeFin({ n, ok: true, phrase: "C'est programmé." }));
  h.avance(300);
  assert.ok(c.fin({ ok: true, outils: ['outils_maison', 'lire_page'] }));
  v = c.voir();
  assert.strictEqual(v.tache.en_cours, false);
  assert.strictEqual(v.tache.ok, true);
  assert.strictEqual(v.tache.etapes.length, 2, 'outils_maison (deja suivi en direct) n est pas ajoute une seconde fois');
  assert.deepStrictEqual(v.tache.etapes.map(s => [s.outil, s.apres, s.ok]), [['planificateur', false, true], ['lire_page', true, true]]);
  assert.strictEqual(v.tache.etapes[0].phrase, "C'est programmé.");
});

test('l estimation : la duree moyenne de l outil sert au pourcentage du passage suivant', () => {
  const h = horloge(5000000), etat = dossier(), c = creer({ etat, maintenant: h });
  c.debut({ texte: 'a' });
  let n = c.etapeDebut({ outil: 'trader' });
  assert.strictEqual(c.voir().tache.etapes[0].estime_ms, 0, 'premier passage : pas d estimation');
  h.avance(10000); c.etapeFin({ n, ok: true }); c.fin({});
  c.debut({ texte: 'b' });
  n = c.etapeDebut({ outil: 'trader' });
  assert.strictEqual(c.voir().tache.etapes[0].estime_ms, 10000);
  h.avance(20000); c.etapeFin({ n, ok: true });
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(etat, 'durees.json'), 'utf8')).trader, 13000, 'moyenne glissante 0,7 / 0,3');
  // un echec ne fausse pas la moyenne
  n = c.etapeDebut({ outil: 'trader' }); h.avance(90000); c.etapeFin({ n, ok: false });
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(etat, 'durees.json'), 'utf8')).trader, 13000);
});

test('rien n est note hors d une tache ouverte, et une tache oubliee (15 min) n est plus en cours', () => {
  const h = horloge(9000000), c = creer({ etat: dossier(), maintenant: h });
  assert.strictEqual(c.etapeDebut({ outil: 'trader' }), 0, 'aucune tache : l outil lance a la main ne cree rien');
  c.debut({ texte: 'x' });
  h.avance(16 * 60000);
  const v = c.voir();
  assert.strictEqual(v.tache.en_cours, false);
  assert.strictEqual(v.tache.abandonnee, true);
  assert.strictEqual(c.etapeDebut({ outil: 'trader' }), 0);
  assert.strictEqual(c.fin({}), false);
});

test('la fin ferme une etape restee ouverte (outil coupe) et la marque ratee', () => {
  const h = horloge(1), c = creer({ etat: dossier(), maintenant: h });
  c.debut({ texte: 'x' });
  c.etapeDebut({ outil: 'navigateur_x' });
  h.avance(4000);
  c.fin({ ok: true });
  const s = c.voir().tache.etapes[0];
  assert.strictEqual(s.ok, false);
  assert.strictEqual(s.phrase, 'interrompu');
});

test('ce qui est garde est court et propre : demande coupee, noms d outils et actions nettoyes, 12 etapes au plus', () => {
  const c = creer({ etat: dossier() });
  c.debut({ source: 'pirate', texte: 'a'.repeat(500) + '\u0007' });
  for (let i = 0; i < 20; i++) c.etapeDebut({ outil: 'Outil<script>' + i, action: 'Écrire"; rm -rf' });
  const v = c.voir();
  assert.strictEqual(v.tache.source, 'appli', 'source inconnue ramenee a appli');
  assert.ok(v.tache.demande.length <= 140);
  assert.strictEqual(v.tache.etapes.length, 12);
  assert.match(v.tache.etapes[0].outil, /^[a-z0-9_ -]+$/);
  assert.strictEqual(v.tache.etapes[0].action, 'ecrire rm -rf');
});

test('un fichier abime ou absent ne fait jamais planter : la page recoit « pas de tache »', () => {
  const etat = dossier();
  fs.writeFileSync(path.join(etat, 'tache.json'), '{abime');
  assert.deepStrictEqual(creer({ etat }).voir().tache, null);
  assert.deepStrictEqual(traiter({ action: 'inconnue' }, { etat }), { ok: false });
  // un dossier impossible a creer (un fichier porte son nom) : traiter repond, sans exception
  const bloque = path.join(etat, 'bloque');
  fs.writeFileSync(bloque, 'x');
  assert.deepStrictEqual(traiter({ action: 'debut', texte: 'x' }, { etat: path.join(bloque, 'sous') }), { ok: false });
});

test('outils_maison en ligne de commande note l etape (sans ses parametres) dans la tache ouverte', () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'archi-tache-base-'));
  const etat = dossier();
  fs.mkdirSync(path.join(base, 'outils', 'bonjour'), { recursive: true });
  fs.writeFileSync(path.join(base, 'outils', 'bonjour', 'bonjour.py'),
    'import json\nprint(json.dumps({"ok": True, "phrase_pour_utilisateur": "Bonjour toi."}))\n');
  fs.writeFileSync(path.join(base, 'outils', 'registre.json'), JSON.stringify({ bonjour: { nom: 'bonjour', description: 'dit bonjour', script: 'bonjour.py', parametres: [] } }));
  creer({ etat }).debut({ texte: 'dis bonjour' });
  const env = Object.assign({}, process.env, { ARCHI_BASE: base, ARCHI_ETAT: etat });
  const sortie = cp.execFileSync('node', [path.join(DEPOT, 'core', 'outils_maison.js')],
    { input: JSON.stringify({ action: 'utiliser', outil: 'bonjour', parametres: { action: 'saluer', texte: 'SECRET-123' } }), env }).toString();
  assert.strictEqual(JSON.parse(sortie).phrase_pour_utilisateur, 'Bonjour toi.');
  const brut = fs.readFileSync(path.join(etat, 'tache.json'), 'utf8');
  assert.ok(!brut.includes('SECRET-123'), 'les parametres ne sont jamais notes');
  const s = creer({ etat }).voir().tache.etapes[0];
  assert.deepStrictEqual([s.outil, s.action, s.ok, s.phrase], ['bonjour', 'saluer', true, 'Bonjour toi.']);
});

test('page d accueil : la carte de la tache et les six etats de la sphere sont branches', () => {
  const page = fs.readFileSync(path.join(DEPOT, 'portail', 'accueil.html'), 'utf8');
  assert.match(page, /id="carte"/);
  assert.match(page, /api\('\/api\/tache'\)/);
  assert.match(page, /'agit'/);
  assert.match(page, /'muet'/);
  // tout ce qui vient de la carte s'ecrit en texte, jamais en HTML
  const f = page.slice(page.indexOf('function dessinerCarte'), page.indexOf('async function majCarte'));
  assert.ok(f.length > 100 && !/innerHTML/.test(f));
  global.window = undefined;
  const sphere = fs.readFileSync(path.join(DEPOT, 'portail', 'sphere.js'), 'utf8');
  for (const m of ['repos', 'ecoute', 'reflechit', 'agit', 'parle', 'muet']) assert.ok(sphere.includes("'" + m + "'"), m);
});

test('deux messages en meme temps : la fin du premier ne ferme pas la carte du second', () => {
  const h = horloge(3000000), c = creer({ etat: dossier(), maintenant: h });
  const id1 = c.debut({ source: 'telegram', texte: 'premier' });
  h.avance(10);
  const id2 = c.debut({ source: 'appli', texte: 'second' });
  assert.notStrictEqual(id1, id2);
  assert.strictEqual(c.fin({ ok: true, id: id1 }), false);
  assert.strictEqual(c.voir().tache.en_cours, true);
  assert.strictEqual(c.fin({ ok: true, id: id2 }), true);
  assert.strictEqual(c.voir().tache.en_cours, false);
});
