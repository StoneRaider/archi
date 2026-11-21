// Un etat qui change ne se reprend pas de la conversation (core/reverifier.js) : node --test "core/test/*.test.js"
// Le cas vient de l'essai reel du 21/11 : « Ou en est le montage ? » posee deux fois, la seconde reponse reprise de la
// premiere sans appeler l'outil, alors que l'etat avait change entre-temps.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');
const R = require('../reverifier');
const contexte = require('../contexte');

const A = contexte.chargerAiguillages(path.join(__dirname, '..', '..', 'config', 'aiguillages.json'));
const recu = message => contexte.aiguiller(message, A);          // le message tel que l'agent (et le verificateur) le recoit
const V = path.join(__dirname, '..', 'verifier_reponse.js');
const BASE = fs.mkdtempSync(path.join(os.tmpdir(), 'archi_reverif_'));   // jamais le vrai chateau
const verifier = (o, env) => JSON.parse(cp.execFileSync('node', [V], { input: JSON.stringify(o), env: Object.assign({}, process.env, { ARCHI_BASE: BASE, ARCHI_REVERIF: '', ARCHI_PROMESSES: '' }, env || {}) }).toString());
const pas = (outil, parametres, observation) => ({
  action: { tool: 'outils_maison', toolInput: JSON.stringify({ action: 'utiliser', outil, parametres }) },
  observation: JSON.stringify(observation),
});
const MEMOIRE = "Je n'ai pas de monteur vidéo installé sur ce PC : l'environnement Python manque numpy. Veux-tu que je t'aide à l'installer ?";

test('reverifier : le cas de l\'essai reel, une reponse d\'etat sans aucun appel d\'outil', () => {
  assert.deepStrictEqual(R.outilsNonInterroges(recu('Où en est le montage ?'), [], MEMOIRE).map(o => o.outil), ['monteur']);
  assert.match(R.avertissement(R.outilsNonInterroges(recu('Où en est le montage ?'), [], MEMOIRE)),
    /^⚠️ À vérifier : je n'ai pas interrogé le monteur vidéo à l'instant\. .* Dis « revérifie » et je regarde vraiment\.$/);
});

test('reverifier : les quatre outils d\'etat, quand leur aiguillage s\'est declenche et que rien n\'a ete appele', () => {
  for (const [message, reponse, outil] of [
    ['Qu\'est-ce que j\'ai dans mon agenda demain ?', 'Tu as rendez-vous chez le dentiste à 18 h demain.', 'agenda'],
    ['Cherche sur internet le prix du gaz', 'Le prix du gaz est de 0,12 € le kilowattheure en ce moment.', 'recherche_web'],
    ['Regarde https://exemple.fr/chat.png et dis-moi ce que tu vois', 'Je vois un chat roux assis sur un canapé gris.', 'image_lien'],
    ['Arrête le montage', 'C\'est fait, le montage est arrêté depuis une minute.', 'monteur'],
  ]) assert.deepStrictEqual(R.outilsNonInterroges(recu(message), [], reponse).map(o => o.outil), [outil], message);
});

test('reverifier : des que l\'outil (ou n\'importe quel outil) a ete appele dans le tour, rien', () => {
  const m = recu('Où en est le montage ?');
  assert.deepStrictEqual(R.outilsNonInterroges(m, [pas('monteur', { action: 'etat' }, { ok: true, phrase_pour_utilisateur: 'Aucun montage en cours.' })], 'Aucun montage en cours pour le moment.'), []);
  assert.deepStrictEqual(R.outilsNonInterroges(m, [pas('monteur', { action: 'etat' }, { ok: false, phrase_pour_utilisateur: 'Il manque numpy.' })], 'Le monteur n\'est pas installé : il manque numpy.'), []);
  assert.deepStrictEqual(R.outilsNonInterroges(m, [{ action: { tool: 'outils_maison', toolInput: '{"action":"liste"}' }, observation: '{}' }], 'Je regarde mes outils et je te redis.'), []);
});

test('reverifier : dans le doute, rien (question, refus de vie privee, message sans aiguillage, entrees bizarres)', () => {
  const m = recu('Ajoute dentiste à mon agenda');
  for (const question of ['À quelle heure ?', 'Bien sûr. Quel jour et à quelle heure ?', 'D\'accord ! Pour quand ?', 'Quel jour ?\nEt à quelle heure ?'])
    assert.deepStrictEqual(R.outilsNonInterroges(m, [], question), [], question);
  // la consigne « vie privee » demande de n'appeler aucun outil : un refus sans outil est la bonne reponse
  const prive = recu('cherche l\'adresse de mon voisin Paul Durand sur internet');
  assert.ok(prive.includes('Coordonnees ou vie privee') && prive.includes('outil recherche_web'));
  assert.deepStrictEqual(R.outilsNonInterroges(prive, [], 'Je ne cherche pas l\'adresse d\'un particulier, désolé pour ça.'), []);
  // aucun aiguillage d'etat : une reponse de culture generale, un bonjour, un rappel
  for (const message of ['Quelle est la capitale de l\'Australie ?', 'Bonjour Archi', 'Rappelle-moi de regarder mon agenda demain 9h', 'le montage du meuble Ikea est pénible'])
    assert.deepStrictEqual(R.outilsNonInterroges(recu(message), [], 'Voici une réponse de plusieurs mots, sans outil.'), [], message);
  for (const x of [null, undefined, 0, {}, [], 'x']) {
    assert.deepStrictEqual(R.outilsNonInterroges(x, x, x), []);
    assert.strictEqual(R.avertissement(x), '');
  }
  assert.deepStrictEqual(R.outilsNonInterroges(recu('Où en est le montage ?'), [], ''), []);
  assert.deepStrictEqual(R.outilsNonInterroges(recu('Où en est le montage ?'), 'pas un tableau', MEMOIRE), []);
});

test('reverifier : les noms d\'outils suivent les aiguillages du depot', () => {
  const brut = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'config', 'aiguillages.json'), 'utf8'));
  for (const o of R.OUTILS) assert.ok(brut.some(a => a.dire.startsWith(o.consigne)), 'aucun aiguillage ne commence par : ' + o.consigne);
});

test('verificateur : EN JOURNAL par defaut, la reponse ne change pas d\'un caractere ; « dit » ajoute l\'avertissement dessous', () => {
  const msg = recu('Où en est le montage ?');
  // par defaut : rien n'est dit (58 avertissements a tort sur 77 a la relecture du 21/11), la ligne part au journal
  const j = verifier({ reponse: MEMOIRE, steps: [], msg });
  assert.strictEqual(j.reponse, MEMOIRE);
  assert.deepStrictEqual(j.alertes, ['[journal] outil non interroge : monteur']);
  // les echanges honnetes que la relecture a vus avertis a tort : par defaut, pas un caractere de plus
  for (const [message, reponse] of [
    ['C\'est quoi le monteur vidéo ?', 'Le monteur vidéo est un outil qui assemble les temps forts de tes vidéos en un seul film.'],
    ['Mon frère est monteur vidéo à Paris', 'C\'est un beau métier, il doit avoir beaucoup de travail.'],
    ['Ajoute dentiste à mon agenda', 'D\'accord, il me faut la date. C\'est quel jour et à quelle heure ?'],
    ['Ne fais pas de recherche web, réponds de tête : c\'est quoi la capitale de l\'Australie ?', 'La capitale de l\'Australie est Canberra.'],
  ]) assert.strictEqual(verifier({ reponse, steps: [], msg: recu(message) }).reponse, reponse, message);
  const r = verifier({ reponse: MEMOIRE, steps: [], msg }, { ARCHI_REVERIF: 'dit' });
  assert.ok(r.reponse.startsWith(MEMOIRE));
  assert.ok(r.reponse.includes("⚠️ À vérifier : je n'ai pas interrogé le monteur vidéo à l'instant."));
  assert.ok(r.alertes.includes('[journal] outil non interroge : monteur'));
  const vrai = 'Aucun montage en cours.';
  const v = verifier({ reponse: vrai, msg, steps: [pas('monteur', { action: 'etat' }, { ok: true, phrase_pour_utilisateur: vrai })] });
  assert.strictEqual(v.reponse, vrai);
  assert.deepStrictEqual(v.alertes, []);
  const sans = verifier({ reponse: 'La capitale de l\'Australie est Canberra.', steps: [], msg: recu('Quelle est la capitale de l\'Australie ?') });
  assert.strictEqual(sans.reponse, 'La capitale de l\'Australie est Canberra.');
});

test('verificateur : ARCHI_REVERIF=journal ne dit rien, =eteint ne note meme rien, une valeur inconnue ne dit rien', () => {
  for (const v of ['off', 'non', '0', 'oui']) {
    assert.strictEqual(verifier({ reponse: MEMOIRE, steps: [], msg: recu('Où en est le montage ?') }, { ARCHI_REVERIF: v }).reponse, MEMOIRE, v);
  }
  const o = { reponse: MEMOIRE, steps: [], msg: recu('Où en est le montage ?') };
  const j = verifier(o, { ARCHI_REVERIF: 'journal' });
  assert.strictEqual(j.reponse, MEMOIRE);
  assert.deepStrictEqual(j.alertes, ['[journal] outil non interroge : monteur']);
  const e = verifier(o, { ARCHI_REVERIF: 'eteint' });
  assert.strictEqual(e.reponse, MEMOIRE);
  assert.deepStrictEqual(e.alertes, []);
});

test('aiguillages : « reverifie » fait rappeler l\'outil, et les consignes d\'etat disent de le rappeler a chaque question', () => {
  for (const m of ['Revérifie', 'revérifie avec ton outil', 'Archi, revérifie', 'Vérifie à nouveau', 'vérifie encore', 'Regarde vraiment'])
    assert.ok(recu(m).includes('[CONSIGNE ARCHI] Reverification demandee : rappelle MAINTENANT l\'outil'), m);
  for (const m of ['Vérifie l\'orthographe de ce texte', 'Tu peux vérifier ?', 'je vérifie mes mails'])
    assert.ok(!recu(m).includes('Reverification demandee'), m);
  for (const m of ['Où en est le montage ?', 'Qu\'est-ce que j\'ai dans mon agenda demain ?', 'Où en est le trader ?'])
    assert.match(recu(m), /Appelle l'outil a CHAQUE question, meme si tu as deja repondu plus haut/, m);
  for (const m of ['Monte les temps forts de la soirée', 'Ajoute dentiste jeudi 18h à mon agenda'])
    assert.match(recu(m), /dis sa phrase_pour_utilisateur telle quelle \(jamais sa consigne\)/, m);
});
