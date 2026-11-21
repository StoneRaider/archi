// La liste « Outils en construction » de la page : node --test "portail/test/*.test.js"
// Deux regles : (1) dans le depot, un projet n'y figure que s'il n'est PAS branche sur l'agent de la demo ; le jour ou il
// l'est, ce test echoue et rappelle de le sortir de la liste. (2) une installation ou il est deja branche le dit dans
// <chateau>/outils/en_service.json, et il disparait de SA page.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const P = require('../portail.js');

const DEPOT = path.join(__dirname, '..', '..');
const vitrine = JSON.parse(fs.readFileSync(path.join(DEPOT, 'config', 'vitrine.json'), 'utf8'));
const registre = JSON.parse(fs.readFileSync(path.join(DEPOT, 'chateau_exemple', 'outils', 'registre.json'), 'utf8'));
const demo = fs.readFileSync(path.join(DEPOT, 'n8n', 'archi_demo.json'), 'utf8');
const lire = f => fs.readFileSync(path.join(DEPOT, f), 'utf8');

// Pour chaque projet annonce : ce qui prouverait qu'il est branche. noeuds = un outil de ce nom sur l'agent de la demo ;
// workflows = l'identifiant de son workflow optionnel appele par la demo ; registre = un outil maison de ce nom ;
// code = [fichier, motif] : le code qui le ferait tourner.
const PREUVES = {
  'Pilotage de drone': { noeuds: ['drone', 'pilotage_drone'], registre: ['drone'] },
  'Appel à l\'expert': { noeuds: ['expert', 'appel_expert'], registre: ['expert', 'appel_expert'] },
  'Concevoir une pièce 3D': { noeuds: ['impression_3d', 'conception_3d', 'catalogues_3d', 'piece_3d'], registre: ['conception_3d', 'piece_3d'] },
};
// Sortis de la liste le 21/11, parce que branches : le tour du jour du trader (core/tournees.js), et quatre outils maison.
const BRANCHES = ['recherche_web', 'image_lien', 'agenda', 'monteur'];

test('chantiers du depot : ce qui en est sorti est bien branche (fiche, registre, script, tests hors ligne)', () => {
  for (const nom of BRANCHES) {
    assert.ok(vitrine.outils.some(f => f.nom === nom && !f.agent), nom + ' : fiche dans la vitrine');
    assert.ok(registre[nom] && registre[nom].script === nom + '.py', nom + ' : au registre');
    assert.deepStrictEqual(registre[nom], JSON.parse(lire('outils/' + nom + '/outil.json')), nom + ' : le registre recopie la fiche');
    assert.ok(fs.existsSync(path.join(DEPOT, 'outils', nom, nom + '.py')), nom + ' : script');
    assert.ok(fs.existsSync(path.join(DEPOT, 'outils', nom, 'test_' + nom + '.py')), nom + ' : tests');
    assert.ok(lire('.github/workflows/tests.yml').includes('outils/' + nom + ' && python test_' + nom + '.py'), nom + ' : tests lances par la CI');
    assert.ok(!vitrine.en_developpement.some(c => new RegExp(nom.split('_')[0], 'i').test(c.titre)), nom + ' : plus annonce en construction');
  }
  assert.match(lire('core/tournees.js'), /trader: \['trader', 'trader\.py'\]/);
  assert.ok(!vitrine.en_developpement.some(c => /trader/i.test(c.titre)));
});

test('chantiers du depot : chaque projet annonce a sa preuve a surveiller', () => {
  assert.deepStrictEqual(vitrine.en_developpement.map(c => c.titre).sort(), Object.keys(PREUVES).sort());
});

test('chantiers du depot : aucun projet « en construction » n\'est deja branche sur l\'agent de la demo', () => {
  for (const [titre, p] of Object.entries(PREUVES)) {
    for (const n of p.noeuds || []) assert.ok(!demo.includes('"name": "' + n + '"'), titre + ' : l\'outil « ' + n + ' » est branche sur l\'agent, sors-le de en_developpement');
    for (const w of p.workflows || []) assert.ok(!demo.includes(w), titre + ' : le workflow ' + w + ' est appele par la demo');
    for (const n of p.registre || []) assert.ok(!Object.prototype.hasOwnProperty.call(registre, n), titre + ' : « ' + n + ' » est au registre');
    for (const [f, motif] of p.code || []) assert.doesNotMatch(lire(f), motif, titre + ' : ' + f);
  }
});

test('chantiers : une installation dit ce qui est deja en service chez elle, et sa page ne l\'annonce plus en construction', () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'archi_chantiers_'));
  fs.mkdirSync(path.join(base, 'outils'), { recursive: true });
  const r = { depot: DEPOT, base };
  const tous = vitrine.en_developpement.map(c => c.titre);
  assert.deepStrictEqual(P.chantiers(r).map(c => c.titre), tous);                      // sans fichier : toute la liste
  const f = path.join(base, 'outils', 'en_service.json');
  fs.writeFileSync(f, JSON.stringify(['Concevoir une pièce 3D', 'appel a l expert', 'Outil qui n\'existe pas']));
  assert.deepStrictEqual(P.chantiers(r).map(c => c.titre), tous.filter(t => t !== 'Concevoir une pièce 3D' && t !== 'Appel à l\'expert'));
  for (const abime of ['{', '"Pilotage de drone"', '{"Pilotage de drone": true}', '[1, null, {}]', '']) {
    fs.writeFileSync(f, abime);
    assert.deepStrictEqual(P.chantiers(r).map(c => c.titre), tous, abime);             // fichier abime : rien ne change
  }
});
