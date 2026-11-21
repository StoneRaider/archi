// Le plein ecran de la page d'accueil survit a la boite d'autorisation du micro : node --test "portail/test/*.test.js"
// Le bloc « pleinEcran » est extrait de accueil.html et joue dans un faux navigateur : le vrai code, sans navigateur.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const page = fs.readFileSync(path.join(__dirname, '..', 'accueil.html'), 'utf8');
const debut = page.indexOf('const pleinEcran = (() => {');
const fin = page.indexOf('})();', debut);
assert.ok(debut > 0 && fin > debut, 'bloc pleinEcran introuvable dans accueil.html');
const BLOC = page.slice(debut, fin + 5);

/** Un faux navigateur : `geste` dit si un geste de l'utilisateur est en cours (sans lui, le plein ecran est refuse). */
function navigateur(reglage) {
  const ecoutes = { pointerdown: [], keydown: [] };
  const n = { geste: false, element: null, demandes: 0, bouton: { hidden: false, firstChild: { nodeValue: 'Plein écran' }, onclick: null } };
  const documentFaux = {
    fullscreenEnabled: true,
    get fullscreenElement() { return n.element; },
    documentElement: { requestFullscreen: () => { n.demandes++; if (!n.geste) return Promise.reject(new TypeError('pas de geste')); n.element = documentFaux.documentElement; return Promise.resolve(); } },
    exitFullscreen: () => { n.element = null; return Promise.resolve(); },
    addEventListener: () => {},
  };
  const bac = {
    $: () => n.bouton, document: documentFaux, menu: () => {},
    localStorage: { getItem: () => (reglage || null), setItem: () => {} },
    addEventListener: (type, f) => { ecoutes[type].push(f); },
    removeEventListener: (type, f) => { ecoutes[type] = ecoutes[type].filter(x => x !== f); },
    Promise,
  };
  vm.createContext(bac);
  vm.runInContext(BLOC + '\nthis.pleinEcran = pleinEcran;', bac);
  n.pleinEcran = bac.pleinEcran;
  n.ecoutes = ecoutes;
  /** un clic (ou une touche) : les ecoutes tournent pendant le geste */
  n.clic = async (ev) => { n.geste = true; for (const f of ecoutes.pointerdown.slice()) f(ev || { target: null }); await attendre(); n.geste = false; };
  n.touche = async (key) => { n.geste = true; for (const f of ecoutes.keydown.slice()) f({ key, target: null }); await attendre(); n.geste = false; };
  n.boiteDuNavigateur = () => { n.element = null; };     // une boite d'autorisation fait sortir du plein ecran
  return n;
}
const attendre = () => new Promise(r => setTimeout(r, 5));

test('plein ecran : le premier clic y entre', async () => {
  const n = navigateur();
  await n.clic();
  assert.ok(n.element);
});

test('plein ecran : la boite du micro en fait sortir, le clic suivant y ramene', async () => {
  const n = navigateur();
  await n.clic();                       // le clic sur le bouton du micro : plein ecran
  n.pleinEcran.avantBoite();            // ouvrirMicro, juste avant getUserMedia
  n.boiteDuNavigateur();                // « Autoriser le micro ? » : le navigateur sort du plein ecran
  await n.pleinEcran.apresBoite();      // la reponse arrive, sans geste : le navigateur refuse d'y revenir
  assert.strictEqual(n.element, null);
  await n.clic();                       // le prochain geste
  assert.ok(n.element, 'le plein ecran doit revenir au geste suivant');
  assert.strictEqual(n.ecoutes.pointerdown.length + n.ecoutes.keydown.length, 0, 'plus aucune ecoute en attente');
});

test('plein ecran : si le navigateur accepte tout de suite, on y revient sans attendre de geste', async () => {
  const n = navigateur();
  await n.clic();
  n.pleinEcran.avantBoite();
  n.boiteDuNavigateur();
  n.geste = true;                       // certains navigateurs gardent le geste du clic sur « Autoriser »
  await n.pleinEcran.apresBoite();
  n.geste = false;
  assert.ok(n.element);
  assert.strictEqual(n.ecoutes.pointerdown.length + n.ecoutes.keydown.length, 0);
});

test('plein ecran : la boite arrive pendant l\'entree en plein ecran (tout premier clic sur le micro)', async () => {
  const n = navigateur();
  n.geste = true; for (const f of n.ecoutes.pointerdown.slice()) f({ target: null });   // pointerdown : la demande part
  n.pleinEcran.avantBoite();            // click, meme geste : ouvrirMicro, la demande n'a pas encore abouti
  await attendre(); n.geste = false;
  n.boiteDuNavigateur();
  await n.pleinEcran.apresBoite();
  assert.strictEqual(n.element, null);
  await n.touche('a');                  // une touche compte comme un geste
  assert.ok(n.element);
});

test('plein ecran : Echap reste un choix de l\'utilisateur, on n\'y revient pas', async () => {
  const n = navigateur();
  await n.clic();
  n.boiteDuNavigateur();                // ici : l'utilisateur a appuye sur Echap (aucune boite annoncee)
  await n.pleinEcran.apresBoite();
  await n.clic();
  assert.strictEqual(n.element, null);
  // et apres une boite, Echap ou F11 ne comptent pas comme le geste qui ramene
  const m = navigateur();
  await m.clic(); m.pleinEcran.avantBoite(); m.boiteDuNavigateur(); await m.pleinEcran.apresBoite();
  await m.touche('Escape');
  assert.strictEqual(m.element, null);
  await m.clic();
  assert.ok(m.element);
});

test('plein ecran : coupe dans le menu (« non »), le micro ne le rallume pas', async () => {
  const n = navigateur('non');
  await n.clic();
  assert.strictEqual(n.element, null);
  n.pleinEcran.avantBoite(); n.boiteDuNavigateur(); await n.pleinEcran.apresBoite();
  await n.clic();
  assert.strictEqual(n.element, null);
  assert.strictEqual(n.demandes, 0);
});

test('page d accueil : le micro previent le plein ecran avant la boite, et y revient que l\'acces soit donne ou refuse', () => {
  const m = page.slice(page.indexOf('async function ouvrirMicro()'), page.indexOf('function grandir()'));
  const avant = m.indexOf('pleinEcran.avantBoite()'), boite = m.indexOf('getUserMedia('), refus = m.indexOf('catch (x) { retour(); note(');
  assert.ok(avant > 0 && boite > avant, 'avantBoite doit preceder getUserMedia');
  assert.match(m, /getUserMedia\([^\n]*\); retour\(\); \}/);
  assert.ok(refus > boite, 'le refus du micro ramene aussi le plein ecran');
  assert.match(m, /const retour = \(\) => \{ try \{ pleinEcran\.apresBoite\(\); \}/);
});
