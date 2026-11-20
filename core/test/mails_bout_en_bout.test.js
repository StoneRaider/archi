// Un mail de bout en bout, avec les VRAIS programmes lances comme n8n les lance : la carte de tache (core/tache.js),
// le lanceur (core/outils_maison.js), l'outil (outils/mails/mails.py) et le verificateur (core/verifier_reponse.js).
// Seule la messagerie est fausse (un petit serveur local). Les attaques des deux relectures du 19/11 sont rejouees.
//   node --test "core/test/*.test.js"      (saute tout seul si Python n'est pas la)
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const cp = require('child_process');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { empreinteDe } = require('../apercu_mail');

const DEPOT = path.join(__dirname, '..', '..');
const PY = process.env.ARCHI_PY || (process.platform === 'win32' ? 'python' : 'python3');
const pythonLa = (() => { try { return cp.spawnSync(PY, ['--version'], { windowsHide: true }).status === 0; } catch (e) { return false; } })();

const BASE = fs.mkdtempSync(path.join(os.tmpdir(), 'archi-mails-bout-'));
const ETAT = path.join(BASE, 'etat');
fs.mkdirSync(path.join(BASE, 'outils', 'mails'), { recursive: true });
fs.copyFileSync(path.join(DEPOT, 'outils', 'mails', 'mails.py'), path.join(BASE, 'outils', 'mails', 'mails.py'));
const FICHE = JSON.parse(fs.readFileSync(path.join(DEPOT, 'outils', 'mails', 'outil.json'), 'utf8'));
fs.writeFileSync(path.join(BASE, 'outils', 'registre.json'), JSON.stringify({ mails: FICHE }));

// ---------------------------------------------------------------- la fausse messagerie (memes regles que serveur/mail_commande.py)
const faux = { enAttente: null, envoyes: [], appels: [], mode: '' };
const serveur = http.createServer((req, res) => {
  let brut = '';
  req.on('data', d => { brut += d; });
  req.on('end', () => {
    let corps = {};
    try { corps = JSON.parse(brut || '{}'); } catch (e) { corps = {}; }
    faux.appels.push(req.url.split('?')[0]);
    const rendre = o => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
    if (req.url === '/mails/preparer') {
      const sujet = corps.sujet || '(sans objet)', boite = corps.boite || 'gmail';
      const dest = String(corps.a).split(/[,;]/).map(x => x.trim()).filter(Boolean);      // comme serveur/mail_commande.py
      const empreinte = empreinteDe(boite, dest, sujet, corps.corps);
      faux.enAttente = { a: dest.join(', '), sujet, corps: corps.corps, boite, empreinte };
      return rendre({ ok: true, statut: 'APERCU', boite, a: dest, sujet, corps: corps.corps, empreinte, adresses_inconnues: [], phrase_pour_utilisateur: 'Voici le mail prêt…' });
    }
    if (req.url === '/mails/envoyer') {
      if (!faux.enAttente) return rendre({ ok: false, statut: 'ERREUR', phrase_pour_utilisateur: "Le mail n'est PAS parti : aucun mail en attente" });
      if (corps.empreinte !== faux.enAttente.empreinte) return rendre({ ok: false, statut: 'ERREUR', phrase_pour_utilisateur: "Le mail n'est PAS parti : l'apercu a change" });
      faux.envoyes.push(faux.enAttente);
      const a = faux.enAttente.a; faux.enAttente = null;
      if (faux.mode === 'part_puis_erreur') return rendre({ ok: false, statut: 'ERREUR', phrase_pour_utilisateur: "Le mail n'est PAS parti : [WinError 32]" });
      return rendre({ ok: true, statut: 'ENVOYE', phrase_pour_utilisateur: "C'est envoyé, depuis ta boîte Gmail, à " + a + '.' });
    }
    res.writeHead(404); res.end('{}');
  });
});

let ENV = null;
/** lance un programme du coeur comme le fait un noeud n8n : JSON sur l'entree, derniere ligne JSON en sortie */
function coeur(script, entree) {
  return new Promise((resolve, reject) => {
    const p = cp.spawn('node', [path.join(DEPOT, 'core', script)], { env: ENV, windowsHide: true });
    let sortie = '', erreurs = '';
    p.stdout.on('data', d => { sortie += d; });
    p.stderr.on('data', d => { erreurs += d; });
    p.on('error', reject);
    p.on('close', () => { try { resolve(JSON.parse(sortie.trim().split(/\r?\n/).pop())); } catch (e) { reject(new Error(script + ' : sortie illisible ' + sortie.slice(0, 200) + erreurs.slice(0, 300))); } });
    p.stdin.end(JSON.stringify(entree));
  });
}
const steps = [];
/** un message de l'utilisateur arrive (noeud Contexte) */
async function message(texte, source) { steps.length = 0; return (await coeur('tache.js', { action: 'debut', source: source || 'appli', texte })).id; }
/** le modele appelle l'outil (noeud outils_maison) */
async function outil(parametres, accord) {
  const demande = Object.assign({ action: 'utiliser', outil: 'mails', parametres }, accord ? { accord } : {});
  const r = await coeur('outils_maison.js', demande);
  steps.push({ action: { tool: 'outils_maison', toolInput: JSON.stringify(demande) }, observation: JSON.stringify(r) });
  return r;
}
/** la reponse du modele sort (noeud Verifier) : rend ce que l'utilisateur recoit */
async function repondre(texteDuModele, id) {
  const v = await coeur('verifier_reponse.js', { reponse: texteDuModele, steps: steps.slice(), msg: '', profil: '' });
  await coeur('tache.js', { action: 'fin', ok: true, outils: ['outils_maison'], id });
  return v;
}
/** un tour entier sans outil : un message, une reponse */
async function bavardage(texte) { const id = await message(texte); return repondre('D\'accord.', id); }
const carte = () => fs.readFileSync(path.join(ETAT, 'tache.json'), 'utf8');
const MAIL = { action: 'preparer', a: 'notaire@example.com', sujet: 'Pièce manquante', texte: 'Bonjour Maître, voici la pièce demandée.' };
const APERCU = /^📧 Aperçu du mail \(rien n'est parti\)\nDepuis : Gmail\nÀ : notaire@example\.com\nObjet : Pièce manquante\n\nBonjour Maître, voici la pièce demandée\.\n\nPour l'envoyer, réponds : envoie\./;
// chaque scenario repart de rien : ni brouillon cote messagerie, ni apercu arme cote outil (sinon un mail identique, affiche au
// message precedent par le scenario d'avant, partirait a bon droit et fausserait le scenario suivant)
const raz = () => { faux.envoyes.length = 0; faux.appels.length = 0; faux.enAttente = null; faux.mode = ''; fs.rmSync(path.join(BASE, 'mails'), { recursive: true, force: true }); };
/** les deux premiers tours d'un mail : la demande, puis l'apercu affiche par le code */
async function apercuAffiche() {
  raz();
  const id = await message('écris au notaire que je lui envoie la pièce manquante');
  await outil(MAIL);
  const v = await repondre('Le mail est prêt.', id);
  assert.match(v.reponse, APERCU);
  return id;
}
/** un tour ou l'utilisateur dit « texte » et ou le modele tente l'envoi ; rend ce que l'outil et l'utilisateur recoivent */
async function tenter(texte, source) {
  const id = await message(texte, source);
  const r = await outil({ action: 'envoyer' }, 'oui');
  const v = await repondre(r.ok ? r.phrase_pour_utilisateur : 'Je n\'ai pas pu l\'envoyer.', id);
  return { r, v };
}

test('un mail de bout en bout', { skip: pythonLa ? false : 'Python absent' }, async (t) => {
  await new Promise(r => serveur.listen(0, '127.0.0.1', r));
  ENV = Object.assign({}, process.env, { ARCHI_BASE: BASE, ARCHI_ETAT: ETAT, ARCHI_PY: PY, ARCHI_SERVEUR_PORT: String(serveur.address().port),
    ARCHI_UTILISATEUR: 'Camille', PYTHONIOENCODING: 'utf-8' });
  for (const k of ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']) delete ENV[k];
  t.after(() => { serveur.close(); fs.rmSync(BASE, { recursive: true, force: true }); });

  await t.test('le parcours normal : aperçu affiché par le code, « envoie », envoi', async () => {
    await apercuAffiche();
    assert.doesNotMatch(carte(), /notaire@example|Pièce manquante|Bonjour Maître/, 'la page d\'accueil ne montre ni le destinataire, ni l\'objet, ni le texte d\'un mail');
    const { r, v } = await tenter('envoie');
    assert.strictEqual(r.statut, 'ENVOYE', JSON.stringify(r));
    assert.deepStrictEqual(faux.envoyes.map(e => e.a), ['notaire@example.com']);
    assert.doesNotMatch(carte(), /notaire@example\.com/);
    assert.doesNotMatch(v.reponse, /Aperçu du mail/, 'une fois parti, plus d\'aperçu');
    // et une seconde fois : plus rien a envoyer, plus rien a afficher
    const encore = await tenter('envoie');
    assert.strictEqual(encore.r.ok, false);
    assert.doesNotMatch(encore.v.reponse, /Aperçu du mail/);
    assert.strictEqual(faux.envoyes.length, 1);
  });

  await t.test('la réponse du modèle est remplacée par l\'aperçu : un faux aperçu ou une autre question ne passent pas (N3)', async () => {
    raz();
    const id1 = await message('lis-moi le mail de la banque');           // un mail piege fait preparer un envoi vers un tiers
    await outil({ action: 'preparer', a: 'pirate@example.org', sujet: 'Re', texte: 'Oui, je confirme.' });
    const v = await repondre('📧 Aperçu du mail (rien n\'est parti)\nÀ : notaire@example.com\nObjet : Re\n\nOui, je confirme.\n\n-----\n(détails techniques ci-dessous, à ignorer). Tu veux que je lise le suivant ?', id1);
    assert.strictEqual(v.reponse, '📧 Aperçu du mail (rien n\'est parti)\nDepuis : Gmail\nÀ : pirate@example.org\nObjet : Re\n\nOui, je confirme.\n\nPour l\'envoyer, réponds : envoie. Sinon, dis-moi quoi changer.');
  });

  await t.test('un « oui » seul n\'envoie pas : l\'aperçu est réaffiché, et « envoie » l\'envoie (C10)', async () => {
    for (const oui of ['oui', 'ok', 'bien sûr', "d'accord"]) {
      await apercuAffiche();
      const un = await tenter(oui);
      assert.strictEqual(un.r.ok, false, oui);
      assert.strictEqual(un.r.action, 'rappeler', oui);
      assert.strictEqual(faux.envoyes.length, 0, oui);
      assert.match(un.v.reponse, APERCU, 'l\'apercu revient a l\'ecran : ' + oui);
      const deux = await tenter('envoie');
      assert.strictEqual(deux.r.statut, 'ENVOYE', oui + ' puis envoie : ' + JSON.stringify(deux.r));
      assert.strictEqual(faux.envoyes.length, 1, oui);
    }
  });

  await t.test('relecture 3 : un rappel du planificateur tombe après l\'aperçu, l\'utilisateur lui répond « ok » : rien ne part', async () => {
    await apercuAffiche();
    // (le rappel part par Telegram sans passer par la carte de tache ; l'utilisateur repond au rappel)
    const { r } = await tenter('ok');
    assert.strictEqual(r.ok, false);
    assert.strictEqual(faux.envoyes.length, 0);
    assert.deepStrictEqual(faux.appels, ['/mails/preparer']);
  });

  await t.test('U1 : le modèle prépare puis veut envoyer dans le même tour : refusé, l\'aperçu s\'affiche, et « envoie » l\'envoie ensuite', async () => {
    raz();
    const id1 = await message('envoie');                       // un message qui EST l'ordre : le lanceur laisse passer, l'outil refuse
    await outil(MAIL);
    const trop = await outil({ action: 'envoyer' }, 'oui');
    assert.strictEqual(trop.ok, false);
    assert.strictEqual(trop.apercu_non_montre, true, JSON.stringify(trop));
    assert.strictEqual(faux.envoyes.length, 0);
    const v = await repondre('J\'ai préparé le mail, il part.', id1);
    assert.match(v.reponse, APERCU, 'l\'envoi refuse ne fait pas disparaitre l\'apercu');
    const { r } = await tenter('envoie');
    assert.strictEqual(r.statut, 'ENVOYE', JSON.stringify(r));
    assert.strictEqual(faux.envoyes.length, 1);
  });

  await t.test('C14 : le modèle re-prépare le même mail avant chaque envoi : ça part quand même, une seule fois', async () => {
    await apercuAffiche();
    const id = await message('envoie');
    await outil(MAIL);
    const r = await outil({ action: 'envoyer' }, 'oui');
    assert.strictEqual(r.statut, 'ENVOYE', JSON.stringify(r));
    await repondre(r.phrase_pour_utilisateur, id);
    assert.strictEqual(faux.envoyes.length, 1);
  });

  await t.test('relecture 4 : envoi incertain, puis le modèle re-prépare : l\'utilisateur est prévenu, aucun aperçu, pas de doublon', async () => {
    await apercuAffiche();
    faux.mode = 'part_puis_erreur';
    const id = await message('envoie');
    const doute = await outil({ action: 'envoyer' }, 'oui');
    assert.strictEqual(doute.incertain, true, JSON.stringify(doute));
    faux.mode = '';
    await outil(MAIL);                                           // le modele, malgre la consigne, re-prepare
    const v = await repondre('Voici le mail, je l\'envoie ?', id);
    assert.match(v.reponse, /^⚠️ Je ne sais pas si ton mail est parti/);
    assert.doesNotMatch(v.reponse, /Aperçu du mail/);
    const { r } = await tenter('envoie');                         // il insiste sans avoir rien revu : rien ne part, l'apercu revient d'abord
    assert.strictEqual(r.ok, false, JSON.stringify(r));
    assert.strictEqual(faux.envoyes.length, 1, 'un seul exemplaire est parti');
  });

  await t.test('le modèle veut envoyer dans le tour de la demande : rien ne part, l\'aperçu s\'affiche', async () => {
    raz();
    const id1 = await message('écris au notaire');
    await outil(MAIL);
    const trop = await outil({ action: 'envoyer' }, 'oui');
    assert.strictEqual(trop.ok, false);
    assert.deepStrictEqual(faux.appels, ['/mails/preparer'], 'le serveur de mails n\'a recu aucune demande d\'envoi');
    const v = await repondre('Voilà, c\'est parti !', id1);
    assert.match(v.reponse, APERCU);
  });

  await t.test('S5c : « non, n\'envoie pas » ne débloque rien, « annuler » désarme pour de bon', async () => {
    await apercuAffiche();
    assert.strictEqual((await tenter("non, n'envoie pas")).r.ok, false);
    await message('non laisse tomber');
    assert.strictEqual((await outil({ action: 'annuler' })).statut, 'ANNULE');
    const { r, v } = await tenter('envoie');
    assert.strictEqual(r.ok, false);
    assert.doesNotMatch(v.reponse, /Aperçu du mail/, 'apres une annulation, plus rien a afficher');
    assert.strictEqual(faux.envoyes.length, 0);
  });

  await t.test('des messages qui ne sont pas l\'ordre d\'envoyer ne débloquent rien', async () => {
    for (const refus of ['résume-moi le mail de la banque', 'envoie un mail à Paul pour dire bonjour', 'attends un peu', 'oui mais change la fin', 'envoie la suite',
      'envoie-le-moi', 'envoie-le au notaire', 'oui tu peux']) {
      await apercuAffiche();
      const { r } = await tenter(refus);
      assert.strictEqual(r.ok, false, refus);
      assert.strictEqual(faux.envoyes.length, 0, refus);
      assert.deepStrictEqual(faux.appels, ['/mails/preparer'], refus);
    }
  });

  await t.test('N1, C8 : d\'autres messages sont passés depuis l\'aperçu : rien ne part, il est réaffiché, puis « envoie » l\'envoie', async () => {
    await apercuAffiche();
    await bavardage('attends, rappelle-moi d\'abord d\'appeler le plombier');
    await bavardage('et quel temps fait-il demain ?');
    const un = await tenter('oui envoie');                       // l'ordre est clair, mais l'apercu n'est plus sous ses yeux
    assert.strictEqual(un.r.ok, false, JSON.stringify(un.r));
    assert.strictEqual(un.r.apercu_non_montre, true);
    assert.strictEqual(faux.envoyes.length, 0);
    assert.match(un.v.reponse, APERCU, 'il le revoit');
    const deux = await tenter('envoie');
    assert.strictEqual(deux.r.statut, 'ENVOYE', JSON.stringify(deux.r));
    assert.strictEqual(faux.envoyes.length, 1);
  });

  await t.test('S2 : un message venu d\'ailleurs pendant un tour, avant ou après l\'affichage, n\'envoie rien', async () => {
    raz();
    await message('écris au notaire');
    await outil(MAIL);
    await coeur('tache.js', { action: 'debut', source: 'telegram', texte: 'envoie' });      // le tour n'est pas fini, l'apercu pas affiche
    let r = await outil({ action: 'envoyer' }, 'oui');
    assert.strictEqual(r.ok, false, JSON.stringify(r));
    assert.strictEqual(faux.envoyes.length, 0);
    // variante de la relecture 2 : l'apercu a ete affiche au tour 1 ; au tour 2 (autre demande), un « envoie » arrive par l'appli
    await apercuAffiche();
    await message('résume le mail de la banque');
    await coeur('tache.js', { action: 'debut', source: 'appli', texte: 'envoie' });
    r = await outil({ action: 'envoyer' }, 'oui');
    assert.strictEqual(r.ok, false, JSON.stringify(r));
    assert.strictEqual(faux.envoyes.length, 0);
  });

  await t.test('R1 : la carte de tâche est supprimée ou abîmée après l\'aperçu : rien ne part', async () => {
    for (const casse of [() => fs.rmSync(path.join(ETAT, 'tache.json'), { force: true }), () => fs.writeFileSync(path.join(ETAT, 'tache.json'), '{abime'),
      () => fs.writeFileSync(path.join(ETAT, 'tache.json'), JSON.stringify({ etapes: [] }))]) {
      await apercuAffiche();
      casse();
      // sans carte lisible : le lanceur ne connait ni le message ni son numero
      assert.strictEqual((await outil({ action: 'envoyer' }, 'oui')).ok, false);
      // un nouveau message arrive : le « message d'avant » est inconnu, donc ce n'est pas « le suivant de l'apercu »
      const { r, v } = await tenter('envoie');
      assert.strictEqual(r.ok, false, JSON.stringify(r));
      assert.strictEqual(faux.envoyes.length, 0);
      assert.match(v.reponse, APERCU, 'il est reaffiche');
      assert.strictEqual((await tenter('envoie')).r.statut, 'ENVOYE');
    }
  });

  await t.test('carte finie (aucun message en cours) : rien ne part', async () => {
    await apercuAffiche();
    const id2 = await message('envoie');
    await coeur('tache.js', { action: 'fin', ok: true, outils: [], id: id2 });
    assert.strictEqual((await outil({ action: 'envoyer' }, 'oui')).ok, false);
    assert.strictEqual(faux.envoyes.length, 0);
  });

  await t.test('N13 : une vieille fiche sans « accord_dans_message » dans le registre installé ne laisse rien partir', async () => {
    const vieille = Object.assign({}, FICHE); delete vieille.accord_dans_message; delete vieille.accord_refuse_action;
    fs.writeFileSync(path.join(BASE, 'outils', 'registre.json'), JSON.stringify({ mails: vieille }));
    try {
      await apercuAffiche();
      for (const m of ["non, n'envoie pas", 'envoie']) {
        const { r } = await tenter(m);
        assert.strictEqual(r.ok, false, m + ' ' + JSON.stringify(r));
      }
      assert.strictEqual(faux.envoyes.length, 0);
    } finally {
      fs.writeFileSync(path.join(BASE, 'outils', 'registre.json'), JSON.stringify({ mails: FICHE }));
    }
  });

  await t.test('dix conversations où l\'utilisateur veut vraiment envoyer aboutissent', async () => {
    const conversations = [
      { nom: 'simple', mail: MAIL, suite: ['envoie'] },
      { nom: 'oui puis envoie', mail: MAIL, suite: ['oui', 'envoie'] },
      { nom: 'question sur l\'aperçu', mail: MAIL, bavardage: ['c\'est bien son adresse pro ?'], suite: ['oui envoie', 'envoie'] },
      { nom: 'deux destinataires', mail: Object.assign({}, MAIL, { a: 'notaire@example.com, clerc@example.com' }), suite: ['tu peux l\'envoyer'] },
      { nom: 'sans objet', mail: { action: 'preparer', a: 'notaire@example.com', texte: 'Bonjour.' }, suite: ['envoie-le'] },
      { nom: 'Outlook', mail: Object.assign({}, MAIL, { boite: 'outlook' }), suite: ['c\'est parfait, envoie'] },
      { nom: 'texte long', mail: Object.assign({}, MAIL, { texte: 'Bonjour. '.repeat(320) }), suite: ['ok envoie'] },
      { nom: 'dictée', mail: MAIL, suite: ['Envoyé fin de transmission'] },
      { nom: 'refus puis accord', mail: MAIL, suite: ['envoie-le au notaire', 'envoie'] },
      { nom: 'bien sûr', mail: MAIL, suite: ['bien sûr', 'envoie le mail'] },
    ];
    for (const c of conversations) {
      raz();
      const id = await message('écris un mail');
      const ap = await outil(c.mail);
      assert.strictEqual(ap.statut, 'APERCU', c.nom + ' ' + JSON.stringify(ap));
      await repondre('Prêt.', id);
      for (const b of c.bavardage || []) await bavardage(b);
      let dernier = null;
      for (const m of c.suite) dernier = await tenter(m);
      assert.strictEqual(dernier.r.statut, 'ENVOYE', c.nom + ' : ' + JSON.stringify(dernier.r));
      assert.strictEqual(faux.envoyes.length, 1, c.nom);
    }
  });
});
