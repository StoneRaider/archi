// Tests de promesses.js : node --test pieces/test
// Ce qui est prouve, famille par famille : une phrase qui affirme sans acte est signalee, la meme avec l'acte reussi ne
// l'est pas, un acte en attente d'accord ou en erreur ne vaut pas un acte reussi, le succes d'un AUTRE outil non plus.
// Et les phrases innocentes ne declenchent rien : questions, propositions, negations, recits, listes, constats lus.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { actesDesSteps, promessesEnLAir, avertissement, NOMS_DES_FAMILLES, ENVOI } = require('../promesses');

// --- de quoi fabriquer un tour, sous la forme que n8n donne aux pas de l'agent ----------------------------------
const FAIT = { ok: true, phrase_pour_utilisateur: 'ok' };
const ACCORD = { ok: false, accord_requis: true, phrase_pour_utilisateur: "Cet outil est sensible (prises) : demande d'abord l'accord, puis rappelle-le avec accord=oui." };
const PANNE = { ok: false, erreur: 'injoignable', phrase_pour_utilisateur: "L'outil maison a échoué." };
/** un appel a outils_maison, comme l'ecrit le modele : une chaine JSON */
function maison(outil, parametres, observation) {
  return { action: { tool: 'outils_maison', toolInput: JSON.stringify({ action: 'utiliser', outil, parametres: parametres || {}, accord: 'oui' }) },
    observation: JSON.stringify(observation || FAIT) };
}
/** un outil branche directement sur l'agent (navigateur, lire_page…) : entree objet, reponse texte */
const agent = (tool, toolInput, observation) => ({ action: { tool, toolInput }, observation: observation === undefined ? 'Page ouverte.' : observation });
const familles = (reponse, steps) => promessesEnLAir(reponse, steps).map(m => m.famille);

const RAPPEL = 'un rappel programmé', PRISE = 'une prise allumée ou éteinte', IMPRESSION = 'une impression 3D lancée, mise en pause ou annulée';
const PDF = 'un PDF ou une présentation créés', TRANSMIS = 'un document transmis', TELEPHONE = 'une action sur le téléphone';
const MAILS = 'des mails rangés', OUTIL = 'un outil fabriqué, validé ou retiré', CURATEUR = 'un rangement de mémoire appliqué';
const NAVIGATEUR = 'une page ouverte ou un clic fait', BROUILLON = 'un brouillon ouvert dans la messagerie', SUPPRIMES = 'des mails supprimés';
// des outils sans rapport, et qui ne LISENT rien (apres un outil qui lit un contenu, un constat raconte ce contenu : regle b)
const SANS_RAPPORT = [maison('musique', { action: 'proposer' }), maison('trader', { action: 'etat' })];

// Pour chaque famille : des mensonges, l'outil qui les rend vrais, le meme outil qui lit seulement, un autre outil.
const FAMILLES = [
  { nom: RAPPEL, acte: o => maison('planificateur', { action: 'ajouter', texte: 'gâteau', a: 'dans 20 min' }, o),
    phrases: ["C'est programmé pour lundi à 19 h.", "J'ai programmé le rappel pour lundi 19 h.", "J'ai bien planifié cela.", "J'ai mis un rappel pour demain matin.",
      'Le rappel a bien été créé.', 'Rappel enregistré pour lundi.', 'Je te le rappellerai lundi.', 'Je vous préviendrai à 8 h.', "Je t'avertirai dès que c'est l'heure.",
      'Je te ferai penser à appeler le plombier.', "Je n'oublierai pas de te le dire.", 'Je te le rappelle lundi à 19 h.', 'Tu recevras un rappel lundi à 19 h.',
      'Je viens de programmer le rappel.', 'Programmé pour lundi à 19 h !', "J'ai à nouveau programmé le rappel de lundi."] },
  { nom: PRISE, acte: o => maison('prises_shelly', { action: 'eteindre', prise: 'radiateur', confirmer: 'oui' }, o),
    phrases: ["J'ai éteint la prise du radiateur.", "J'ai allumé le radiateur pour 3 heures.", 'Je viens de couper le chauffage.', 'La prise du salon a été éteinte.',
      'Le radiateur est maintenant allumé.', 'La prise est bien éteinte.', "C'est éteint.", 'Éteint !', "Voilà, c'est allumé.", "J'ai de nouveau allumé la prise.",
      'Radiateur allumé pour 180 minutes.'] },
  { nom: IMPRESSION, acte: o => maison('imprimante_3d', { action: 'lancer', fichier: 'benchy.gcode', confirmer: 'oui' }, o),
    phrases: ["J'ai lancé l'impression du benchy.", "Je viens d'annuler l'impression.", "J'ai mis l'impression en pause.", "L'impression a été lancée.",
      "L'impression est lancée.", "L'impression est maintenant en pause.", "J'ai envoyé le fichier benchy.gcode à l'imprimante.",
      "C'est lancé, l'imprimante chauffe.", 'Impression annulée.', "J'ai encore relancé l'impression."] },
  { nom: PDF, acte: o => maison('creer_pdf', { titre: 'Paillage', contenu: '# Paillage' }, o),
    phrases: ["J'ai créé le PDF du compte rendu.", "J'ai préparé une présentation de 8 diapos.", 'Je viens de générer le PDF.', "J'ai fait un PDF qui résume le paillage.",
      'Le PDF a bien été créé.', 'Ton PDF est prêt.', 'Ta présentation est enregistrée dans tes documents.', "J'ai préparé le compte rendu en PDF.",
      "J'ai préparé à nouveau le PDF du compte rendu.", 'PDF créé : Paillage au potager.'] },
  { nom: TRANSMIS, acte: o => maison('transmettre_document', { action: 'donner', nom: 'facture' }, o),
    phrases: ["Je t'ai envoyé le PDF sur Telegram.", "J'ai transmis le document.", "Je viens de t'envoyer l'appli.", 'Le fichier a bien été transmis.',
      "L'appli t'a été envoyée sur Telegram.", 'Le PDF est parti sur Telegram.', "C'est transmis."] },
  { nom: TELEPHONE, acte: o => maison('telephone', { action: 'minuteur', minutes: 12 }, o),
    phrases: ["J'ai mis un minuteur de 12 minutes.", "J'ai réglé l'alarme à 7 h 30.", "J'ai allumé la lampe.", "J'ai lancé la musique.", "J'ai lancé la navigation vers Dijon.",
      "J'ai ouvert WhatsApp.", "J'ai baissé le volume.", "J'ai préparé le SMS pour Paul.", "J'ai lancé la vidéo sur ton téléphone.", 'Minuteur lancé pour 12 minutes.',
      "J'ai ajouté le rendez-vous à ton agenda."] },
  { nom: MAILS, acte: o => maison('ranger_mails', { compte: 'gmail', action: 'deplacer', vers: 'Pub', confirmer: true }, o),
    phrases: ["J'ai rangé tes mails de pub dans le dossier Pub.", "J'ai déplacé 12 mails dans Factures.", 'Je viens de trier tes mails.', 'Les mails ont été déplacés.',
      'Tes mails de pub sont maintenant rangés.', "J'ai créé le dossier Factures dans ta boîte Gmail.", '12 mails rangés dans Pub.'] },
  { nom: OUTIL, acte: o => maison('mecanicien', { action: 'construire', texte: 'dit où est la station spatiale' }, o),
    phrases: ["J'ai fabriqué l'outil météo.", "J'ai construit un nouvel outil.", "Je viens de valider l'outil.", "J'ai retiré l'outil meteo_locale.", "J'ai installé l'outil.",
      "L'outil a été fabriqué.", "L'outil meteo_locale est validé.", 'Outil fabriqué : meteo_locale.'] },
  { nom: CURATEUR, acte: o => maison('curateur', { action: 'appliquer', numeros: '1 et 3' }, o),
    phrases: ["J'ai appliqué les propositions 1 et 3.", "J'ai appliqué la 1 et la 3.", "J'ai tout appliqué.", "J'ai rangé ta mémoire.", "J'ai fusionné les doublons.",
      'Les propositions 1 et 3 ont été appliquées.', 'Les propositions 1 et 3 sont appliquées.', "C'est appliqué.", 'Appliqué !', 'Ta mémoire est maintenant rangée.'] },
  { nom: NAVIGATEUR, acte: o => agent('navigateur', { action: 'ouvrir', cible: 'sncf-connect.com', valeur: '' }, o === undefined ? 'Page ouverte : SNCF Connect.' : JSON.stringify(o)),
    phrases: ["J'ai ouvert la page de la SNCF.", "J'ai ouvert le site dans mon navigateur.", "J'ai cliqué sur « Rechercher ».", "J'ai rempli le formulaire.",
      'Je suis allé sur le site de la mairie.', 'Je viens de cliquer sur le bouton.', 'La page est ouverte.', 'Page ouverte : SNCF Connect.', 'Le formulaire a été rempli.'] },
];
const AUTRES = [maison('memoire', { action: 'lire' }), maison('musique', { action: 'proposer' }), maison('indicateur_polymarket', { sujet: 'Fed December' }),
  maison('trader', { action: 'etat' })];

test('les familles couvertes sont celles de la consigne, sans « un fait retenu »', () => {
  assert.deepStrictEqual(NOMS_DES_FAMILLES, [RAPPEL, PRISE, IMPRESSION, PDF, TRANSMIS, TELEPHONE, MAILS, SUPPRIMES, OUTIL, CURATEUR, NAVIGATEUR, BROUILLON, ENVOI]);
  assert.ok(!NOMS_DES_FAMILLES.some(n => /retenu|noté/.test(n)));
});

for (const f of FAMILLES) {
  for (const phrase of f.phrases) {
    test(f.nom + ' : « ' + phrase + ' » sans outil est signalé, avec l\'outil réussi ne l\'est pas', () => {
      assert.deepStrictEqual(promessesEnLAir(phrase, []), [{ famille: f.nom, raison: 'aucun_outil' }]);
      assert.deepStrictEqual(promessesEnLAir(phrase, [f.acte()]), []);
      assert.deepStrictEqual(promessesEnLAir(phrase.replace(/'/g, '’'), []), [{ famille: f.nom, raison: 'aucun_outil' }], 'apostrophe typographique');
    });
  }
  test(f.nom + ' : un outil en attente d\'accord ne vaut pas un outil réussi', () => {
    assert.deepStrictEqual(promessesEnLAir(f.phrases[0], [f.acte(ACCORD)]), [{ famille: f.nom, raison: 'outil_refuse' }]);
  });
  test(f.nom + ' : un outil en erreur ne vaut pas un outil réussi', () => {
    assert.deepStrictEqual(promessesEnLAir(f.phrases[0], [f.acte(PANNE)]), [{ famille: f.nom, raison: 'outil_en_erreur' }]);
    // un echec puis un succes : c'est fait
    assert.deepStrictEqual(promessesEnLAir(f.phrases[0], [f.acte(PANNE), f.acte()]), []);
  });
  test(f.nom + ' : le succès d\'un autre outil ne couvre pas l\'affirmation', () => {
    assert.deepStrictEqual(promessesEnLAir(f.phrases[0], AUTRES), [{ famille: f.nom, raison: 'aucun_outil' }]);
  });
}

// --- compatibilite avec la regle existante d'Archi (core/test/core.test.js, « pas de C'est programmé sans la reponse du planificateur ») ---
test('rappel : même verdict que promesseSansPlanificateur sur ses cinq cas', () => {
  const rappel = (reponse, steps) => familles(reponse, steps).includes(RAPPEL);
  // 1. le cas vu a l'essai reel : une promesse, aucun appel d'outil
  assert.strictEqual(rappel("D'accord ! Veux-tu que je te rappelle dans 2 minutes de boire un verre d'eau ? (C’est programmé)", []), true);
  // 2. un engagement, aucun outil
  assert.strictEqual(rappel('Pas de souci, je te le rappellerai demain matin.', []), true);
  // 3. le planificateur a vraiment repondu (le pas n'a pas de toolInput : seule sa reponse le dit)
  assert.strictEqual(rappel("C'est programmé ! t1 · le mardi 10/11 à 6 h 11 · sortir le gâteau.",
    [{ action: { tool: 'outils_maison' }, observation: JSON.stringify({ ok: true, phrase_pour_utilisateur: "C'est programmé ! t1 · le mardi 10/11 à 6 h 11 · sortir le gâteau." }) }]), false);
  // 4. une liste de rappels n'est pas une promesse
  assert.strictEqual(rappel('Tu as 2 rappels programmés : sortir le gâteau, appeler le garagiste.', [{ observation: '{"ok":true,"phrase_pour_utilisateur":"2 rappels"}' }]), false);
  // 5. un autre outil a repondu, mais pas le planificateur
  assert.strictEqual(rappel("C'est programmé, je te préviendrai.", [{ observation: '{"ok":true,"phrase_pour_utilisateur":"PDF cree"}' }]), true);
});

test('rappel : les épreuves du banc (rappel, rappel_repete) ne déclenchent rien', () => {
  const planif = phrase => maison('planificateur', { action: 'ajouter', texte: 'x', a: 'dans 20 min' }, { ok: true, phrase_pour_utilisateur: phrase });
  assert.deepStrictEqual(promessesEnLAir("C'est programmé : je te rappelle à 15 h 42 de sortir le gâteau du four.", [planif("C'est programmé : je te rappelle à 15 h 42 de sortir le gâteau du four.")]), []);
  assert.deepStrictEqual(promessesEnLAir("C'est programmé : chaque lundi à 9 h.", [planif("C'est programmé : chaque lundi à 9 h.")]), []);
});

// --- l'envoi -------------------------------------------------------------------------------------------------------
const TOUT_CE_QUI_ECRIT = [maison('creer_pdf', { titre: 'x' }), maison('telephone', { action: 'sms', a: 'Paul', texte: 'coucou' }), maison('transmettre_document', { action: 'donner', nom: 'x' }),
  maison('appli_telephone', {}), maison('ranger_mails', { action: 'deplacer', confirmer: true })];
for (const phrase of ["J'ai envoyé le mail à Durieux.", "J'ai envoyé l'e-mail à Durieux.", 'Mail envoyé à Durieux.', 'Tes deux mails ont été envoyés.', 'Le mail est parti.',
  "Je viens d'envoyer le courriel au syndic.", "J'ai bien envoyé ton mail."]) {
  test('envoi : « ' + phrase + ' » est toujours signalé, quels que soient les outils', () => {
    assert.deepStrictEqual(promessesEnLAir(phrase, []), [{ famille: ENVOI, raison: 'aucun_outil' }]);
    assert.ok(familles(phrase, TOUT_CE_QUI_ECRIT).includes(ENVOI));
  });
}
for (const phrase of ["C'est envoyé !", 'Envoyé ! Il te répondra vite.', 'Le message est parti.', "Je l'ai envoyé à ton syndic.", 'Lettre postée ce matin.', 'Message envoyé !']) {
  test('envoi : « ' + phrase + ' » sans outil est signalé', () => {
    assert.deepStrictEqual(promessesEnLAir(phrase, []), [{ famille: ENVOI, raison: 'aucun_outil' }]);
    assert.ok(familles(phrase, [maison('musique', { action: 'proposer' }), maison('planificateur', { action: 'ajouter' })]).includes(ENVOI), 'un outil sans rapport ne couvre pas');
  });
}
test('envoi : un outil qui fait vraiment partir quelque chose couvre la phrase qui en parle', () => {
  const sms = maison('telephone', { action: 'sms', a: 'Paul', texte: 'coucou' });
  const doc = maison('transmettre_document', { action: 'donner', nom: 'facture' });
  const appli = maison('appli_telephone', {});
  assert.deepStrictEqual(promessesEnLAir('Le message est parti.', [sms]), []);
  assert.deepStrictEqual(promessesEnLAir("J'ai envoyé le SMS à Paul.", [sms]), []);
  assert.deepStrictEqual(promessesEnLAir("C'est envoyé !", [sms]), []);
  assert.deepStrictEqual(promessesEnLAir("C'est envoyé sur Telegram.", [doc]), []);
  assert.deepStrictEqual(promessesEnLAir("Je te l'ai envoyé sur Telegram.", [doc]), []);
  assert.deepStrictEqual(promessesEnLAir("C'est envoyé, tu as l'appli sur Telegram.", [appli]), []);
  // mais pas la phrase qui parle d'autre chose : le SMS ne fait pas partir un mail, le PDF donne ne fait pas partir un SMS
  assert.deepStrictEqual(promessesEnLAir("J'ai envoyé le mail à Paul.", [sms, doc, appli]), [{ famille: ENVOI, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir('Le message est parti.', [doc]), [{ famille: ENVOI, raison: 'aucun_outil' }]);
});
test('envoi : le SMS refusé ou en panne est dit avec sa raison', () => {
  assert.deepStrictEqual(promessesEnLAir("J'ai envoyé le SMS à Paul.", [maison('telephone', { action: 'sms' }, PANNE)]), [{ famille: ENVOI, raison: 'outil_en_erreur' }]);
  assert.deepStrictEqual(promessesEnLAir("J'ai envoyé le SMS à Paul.", [maison('telephone', { action: 'sms' }, ACCORD)]), [{ famille: ENVOI, raison: 'outil_refuse' }]);
});
for (const phrase of ["C'est parti, je regarde tes papiers.", 'Cette lettre a été envoyée par la CAF le 3 novembre.', 'Envoyée le 3 novembre par ta banque, cette lettre te demande un justificatif.',
  'Préviens-moi quand le mail est envoyé.', 'Ce message a été transmis par ton propriétaire.', 'Le brouillon est prêt à envoyer.', "Tu peux l'envoyer quand tu veux.",
  "Je n'ai pas envoyé le mail : je ne peux pas le faire.", "Je ne sais pas envoyer de mail, mais voici le texte.", "Le mail n'est pas parti.", 'Veux-tu que je l’envoie ?']) {
  test('envoi : « ' + phrase + ' » (un récit, une condition, une négation) n\'est pas signalé', () => {
    assert.deepStrictEqual(promessesEnLAir(phrase, []), []);
  });
}

// --- les cas reels d'Intendant ---------------------------------------------------------------------------------------
test('Intendant, essai du 19/11 : « J\'ai préparé à nouveau le brouillon de mail… ouvert dans ta messagerie »', () => {
  const phrase = "J'ai préparé à nouveau le brouillon de mail pour Monsieur Durieux. Il est maintenant ouvert dans ta messagerie.";
  assert.deepStrictEqual(promessesEnLAir(phrase, []), [{ famille: BROUILLON, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir(phrase, SANS_RAPPORT), [{ famille: BROUILLON, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("J'ai de nouveau enregistré le mail dans tes brouillons.", []), [{ famille: BROUILLON, raison: 'aucun_outil' }]);
  // ecrire le texte d'un brouillon dans la reponse est ce qu'Archi fait : rien a signaler
  assert.deepStrictEqual(promessesEnLAir("J'ai préparé le brouillon de mail pour Monsieur Durieux, le voici : Bonjour Monsieur…", []), []);
  // decrire ce que l'outil des mails vient de lire n'est pas une annonce
  assert.deepStrictEqual(promessesEnLAir('Le mail est enregistré dans tes brouillons.', [maison('ranger_mails', { action: 'chercher', dans: 'brouillons' })]), []);
});
for (const [phrase, famille, outil] of [
  ["J'ai préparé à nouveau le PDF du compte rendu.", PDF, 'creer_pdf'], ["J'ai de nouveau éteint la prise du radiateur.", PRISE, 'prises_shelly'],
  ["J'ai encore lancé l'impression.", IMPRESSION, 'imprimante_3d'], ["Je viens de lancer encore une fois l'impression.", IMPRESSION, 'imprimante_3d'],
  ["J'ai aussi programmé le rappel.", RAPPEL, 'planificateur'], ["J'ai également rangé tes mails.", MAILS, 'ranger_mails']]) {
  test('Intendant : l\'adverbe glissé ne cache pas l\'affirmation « ' + phrase + ' »', () => {
    assert.deepStrictEqual(promessesEnLAir(phrase, []), [{ famille, raison: 'aucun_outil' }]);
    assert.deepStrictEqual(promessesEnLAir(phrase, [maison(outil, { action: 'faire' }, ACCORD)]), [{ famille, raison: 'outil_refuse' }]);
    assert.deepStrictEqual(promessesEnLAir(phrase, [maison(outil, { action: 'faire' })]), []);
  });
}
test('Intendant : « j\'ai déjà… » rappelle un geste passé, ce n\'est pas une affirmation nouvelle', () => {
  assert.deepStrictEqual(promessesEnLAir("J'ai déjà éteint la prise il y a quelques instants.", []), []);
  assert.deepStrictEqual(promessesEnLAir("J'ai déjà préparé ce PDF pour toi hier.", []), []);
});
test('Intendant, banc du 14/11 : « je l\'ai ajoutée » après un refus de l\'outil reste une affirmation', () => {
  const refuse = maison('planificateur', { action: 'ajouter', texte: 'facture du garage' }, PANNE);
  assert.deepStrictEqual(promessesEnLAir("J'ai bien trouvé la facture du garage. Je l'ai ajoutée à tes rappels pour lundi.", [refuse]), [{ famille: RAPPEL, raison: 'outil_en_erreur' }]);
  assert.deepStrictEqual(promessesEnLAir("La prise du radiateur, je l'ai éteinte.", [maison('prises_shelly', { action: 'eteindre', prise: 'radiateur' }, ACCORD)]),
    [{ famille: PRISE, raison: 'outil_refuse' }]);
  assert.deepStrictEqual(promessesEnLAir("L'impression du support, je l'ai lancée.", [maison('imprimante_3d', { action: 'lancer' }, ACCORD)]), [{ famille: IMPRESSION, raison: 'outil_refuse' }]);
  assert.deepStrictEqual(promessesEnLAir('Tes mails de pub, je les ai rangés.', []), []);      // tournure non couverte : dans le doute, rien
});

// --- l'essai a blanc ------------------------------------------------------------------------------------------------
test('un essai à blanc (« PAS ENCORE FAIT ») n\'est pas un acte : l\'outil attend le « vas-y »', () => {
  const blanc = maison('prises_shelly', { action: 'allumer', prise: 'radiateur' },
    { ok: true, phrase_pour_utilisateur: 'PAS ENCORE FAIT (essai à blanc) : je vais allumer la prise radiateur pour 180 minutes. Redis-moi avec confirmer=oui.' });
  assert.deepStrictEqual(actesDesSteps([blanc]), [{ outil: 'prises_shelly', action: 'allumer', statut: 'attente_accord' }]);
  assert.deepStrictEqual(promessesEnLAir("C'est fait, j'ai allumé le radiateur.", [blanc]), [{ famille: PRISE, raison: 'outil_refuse' }]);
  // la bonne reponse a un essai a blanc ne declenche rien
  assert.deepStrictEqual(promessesEnLAir('Je vais allumer la prise radiateur pour 180 minutes. Tu confirmes ?', [blanc]), []);
  const mails = maison('ranger_mails', { action: 'deplacer', vers: 'Pub' }, { ok: true, essai: true, nombre: 12, phrase_pour_utilisateur: 'Essai a blanc : 12 mails iraient dans « Pub ».' });
  assert.deepStrictEqual(promessesEnLAir("J'ai rangé tes 12 mails de pub.", [mails]), [{ famille: MAILS, raison: 'outil_refuse' }]);
  const differe = maison('planificateur', { action: 'ajouter', outil: 'prises_shelly', a: '22h' }, { ok: false, essai: true, phrase_pour_utilisateur: 'PAS ENCORE FAIT (essai à blanc) : je programmerais…' });
  assert.deepStrictEqual(promessesEnLAir("C'est programmé pour 22 h.", [differe]), [{ famille: RAPPEL, raison: 'outil_refuse' }]);
});

// --- un outil de lecture : decrire ce qu'on vient de lire n'est pas annoncer un geste ---------------------------------
const LECTURES = [
  ['La prise est éteinte.', maison('prises_shelly', { action: 'etat', prise: 'radiateur' }, { ok: true, phrase_pour_utilisateur: 'La prise radiateur est éteinte, 0 W.' }), PRISE],
  ['Le radiateur est allumé, il consomme 950 watts.', maison('prises_shelly', { action: 'etat' }), PRISE],
  ['Le rappel est programmé pour demain à 19 h.', maison('planificateur', { action: 'lister' }), RAPPEL],
  ['Rappels programmés : sortir le gâteau, appeler le garagiste.', maison('planificateur', { action: 'lister' }), RAPPEL],
  ["L'impression est en pause, il reste 10 minutes.", maison('imprimante_3d', { action: 'etat' }), IMPRESSION],
  ["L'impression est lancée, 62 %, reste 41 minutes.", maison('camera_imprimante', { action: 'etat' }), IMPRESSION],
  ['Le PDF de la facture est enregistré dans tes documents.', maison('lire_pdf', { action: 'liste' }), PDF],
  ['Tes mails de pub sont rangés dans le dossier Pub.', maison('ranger_mails', { action: 'chercher', dans: 'Pub' }), MAILS],
  ["L'outil meteo_locale est validé et installé.", maison('mecanicien', { action: 'etat' }), OUTIL],
  ['Les propositions 1 et 3 sont appliquées, la 2 attend.', maison('curateur', { action: 'propositions' }), CURATEUR],
];
for (const [phrase, lecture, famille] of LECTURES) {
  test('lecture : « ' + phrase + ' » décrit ce que l\'outil vient de lire', () => {
    assert.deepStrictEqual(promessesEnLAir(phrase, [lecture]), []);
    assert.deepStrictEqual(promessesEnLAir(phrase, []), [{ famille, raison: 'aucun_outil' }], 'sans rien avoir lu, c\'est une annonce');
  });
}
test('lecture : un geste dit au passé reste une promesse, même après une lecture', () => {
  assert.deepStrictEqual(promessesEnLAir("J'ai éteint la prise.", [maison('prises_shelly', { action: 'etat' })]), [{ famille: PRISE, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("J'ai ajouté un rappel pour demain.", [maison('planificateur', { action: 'lister' })]), [{ famille: RAPPEL, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("J'ai rangé les 3 mails dans Factures.", [maison('ranger_mails', { action: 'chercher' })]), [{ famille: MAILS, raison: 'aucun_outil' }]);
  // … mais un passif decrit ce que l'outil vient de lire (regle a) : il n'est plus releve
  assert.deepStrictEqual(promessesEnLAir('Le rappel a été programmé pour demain.', [maison('planificateur', { action: 'lister' })]), []);
  assert.deepStrictEqual(promessesEnLAir("J'ai appliqué les propositions 1 et 3.", [maison('curateur', { action: 'examiner' })]), [{ famille: CURATEUR, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("J'ai lancé l'impression.", [maison('imprimante_3d', { action: 'etat' })]), [{ famille: IMPRESSION, raison: 'aucun_outil' }]);
});

// --- les phrases innocentes -----------------------------------------------------------------------------------------
const INNOCENTES = [
  // questions et propositions
  'Veux-tu que je programme un rappel ?', 'Je peux te le rappeler si tu veux.', 'Je pourrais te le rappeler demain matin, si tu veux.', 'Quand veux-tu que je te le rappelle ?',
  'Si tu veux, je te le rappellerai demain.', 'Je te le rappelle lundi si tu veux.', "Veux-tu que j'éteigne la prise du radiateur ?", "Je peux lancer l'impression quand tu veux.",
  "Je vais allumer la prise radiateur pour 180 minutes. Tu confirmes ?", "Je vais lancer l'impression dès que tu me dis oui.", 'Je vais te le rappeler demain matin.',
  "Veux-tu que je t'envoie le PDF sur Telegram ?", 'Souhaites-tu que je range tes mails de pub ?', "Faut-il que j'applique les propositions 1 et 3 ?",
  "Le radiateur est allumé ?", "C'est noté, mais quand veux-tu que je te le rappelle ?", 'Bonjour ! Que puis-je faire pour toi ?',
  // negations
  "Je n'ai rien programmé.", "Je n'ai pas pu programmer le rappel.", "Le rappel n'a pas été programmé.", "Ce n'est pas programmé.", "Je n'ai pas éteint la prise : il me faut ton accord.",
  "La prise n'est pas éteinte.", "L'impression n'a pas été lancée.", "Je n'ai pas lancé l'impression.", "Le PDF n'a pas été créé.", "Rien n'a été appliqué.",
  "Je ne te le rappellerai pas automatiquement.", "Je n'ai pas le droit d'allumer la prise du PC.", "Je n'arrive pas à joindre l'imprimante.",
  // la memoire d'Archi se remplit seule : « c'est note » y est legitime
  "C'est noté.", "C'est noté, je m'en souviendrai.", "J'ai bien noté que ta sœur habite à Nantes.", "C'est retenu.", "D'accord, c'est bon.", "J'ai noté ton rendez-vous de jeudi chez le dentiste.",
  // recits, listes, constats
  'Tu as 2 rappels programmés : sortir le gâteau, appeler le garagiste.', 'Tu as un rappel programmé lundi à 19 h.', "Tu n'as aucun rappel programmé.",
  'Voici tes rappels programmés : lundi 19 h, mardi 8 h.', 'Un rappel est déjà programmé pour lundi.', 'Ton prochain rappel est lundi à 19 h : appeler le plombier.',
  'Je te rappelle que la réunion est lundi.', 'Je te le rappelle : la réunion est lundi.', 'Tu m\'as dit que tu avais éteint le radiateur avant de partir.',
  'Tu m\'as dit : « j\'ai envoyé le mail hier ».', 'Tu m\'as dit que le mail est parti hier.', 'Hier, Paul a éteint le radiateur avant de partir.',
  'Impression en cours : support_lampe, 62 %, reste 41 minutes.', 'Le curateur propose trois rangements : 1. un lien cassé, 2. un fait en double, 3. une fiche vide.',
  "J'ai 23 outils : Rappels et tâches, Prises connectées, Imprimante 3D.", "L'outil prises_shelly allume ou éteint le radiateur.", 'Trois vidéos : une parabole en carton, un four boîte vitré.',
  'Sébastien Le Prestre de Vauban était un ingénieur militaire français.', '17 fois 23 font 391.', "J'ai trouvé 3 PDF qui parlent du loyer.", "J'ai lu le PDF de la facture : le total est de 120 €.",
  "J'ai cherché dans tes mails : rien de la mairie.", "J'ai lancé l'analyse de la vidéo, je te préviens à la fin.".replace(', je te préviens à la fin', ''), "J'ai lancé l'enquête sur Durand Toitures.",
  'Je ne peux pas commander de pizza : je n\'ai pas d\'outil pour ça.', 'Dis-moi si la prise est allumée.', "Je ne sais pas si l'impression est lancée.", 'Préviens-moi quand le PDF est prêt.',
  // une habitude, un recit : pas un geste de ce tour
  "D'habitude, la prise du radiateur est éteinte la nuit.", "En général l'impression est lancée le soir.", 'Hier, le rappel a été programmé pour lundi.',
  "D'après ta fiche, le radiateur est allumé chaque matin.",
  // l'imperatif et le nom ne sont pas des participes
  'Programme chargé lundi.', 'Programme du jour : réunion à 10 h, dentiste à 15 h.', 'Allume la prise toi-même si tu préfères.', 'Envoie-le quand tu veux.', 'Applique la crème deux fois par jour.',
  // des mots voisins qui ne parlent pas d'un outil
  "J'ai allumé une bougie pour l'ambiance, façon de parler.", "J'ai rangé les idées par ordre d'importance.", "J'ai mis les trois offres dans un tableau.", "J'ai fait le calcul : 36 €.",
];
for (const phrase of INNOCENTES) {
  test('innocente : « ' + phrase + ' » ne déclenche rien', () => {
    assert.deepStrictEqual(promessesEnLAir(phrase, []), []);
    assert.deepStrictEqual(promessesEnLAir(phrase, AUTRES), [], 'ni après des outils sans rapport');
    assert.deepStrictEqual(promessesEnLAir(phrase.replace(/'/g, '’'), []), [], 'ni avec des apostrophes typographiques');
  });
}

// --- phrase par phrase, accents, casse --------------------------------------------------------------------------------
test('le texte est lu phrase par phrase', () => {
  assert.deepStrictEqual(familles("Tu as un rappel programmé lundi. J'ai éteint la prise.", []), [PRISE]);
  assert.deepStrictEqual(familles("Je n'ai pas pu lancer l'impression ; j'ai créé le PDF du rapport.", []), [PDF]);
  assert.deepStrictEqual(familles("J'ai programmé le rappel pour lundi et j'ai éteint la prise du radiateur.", []), [RAPPEL, PRISE]);
  assert.deepStrictEqual(familles("J'ai programmé le rappel pour lundi et j'ai éteint la prise du radiateur.", [maison('planificateur', { action: 'ajouter' })]), [PRISE]);
  assert.deepStrictEqual(familles("C'est programmé pour lundi. Autre chose ?", []), [RAPPEL]);
  assert.deepStrictEqual(familles("Parfait !\nJ'ai lancé l'impression.\nAutre chose ?", []), [IMPRESSION]);
});
test('piège du portage : les accents, la casse, les espaces ne changent rien (\\b est sûr sur le texte net)', () => {
  for (const [phrase, famille] of [["C'EST PROGRAMMÉ !", RAPPEL], ["c'est programme", RAPPEL], ["C'est   programmé.", RAPPEL], ["C'est programmé !", RAPPEL],
    ['La prise est bien éteinte.', PRISE], ['LA PRISE EST BIEN ÉTEINTE.', PRISE], ['la prise est bien eteinte', PRISE], ["J'ai envoyé le mail.", ENVOI], ["J'AI ENVOYÉ LE MAIL.", ENVOI],
    ["J'ai à nouveau créé le PDF.", PDF], ["J'ai a nouveau cree le pdf", PDF], ['**C\'est programmé.**', RAPPEL], ['- J\'ai éteint la prise.', PRISE], ['✅ Programmé pour lundi.', RAPPEL],
    ['[TEXTE] J\'ai créé le PDF.', PDF], ['J’ai créé le PDF.'.normalize('NFD'), PDF]]) {
    assert.deepStrictEqual(familles(phrase, []), [famille], phrase);
  }
});
test('un participe en tête de phrase affirme, pas l\'impératif ni le nom', () => {
  for (const [participe, imperatif, famille] of [['Programmé pour lundi.', 'Programme chargé lundi.', RAPPEL], ['Éteint.', 'Éteins la lumière en partant.', PRISE],
    ['Allumé !', 'Allume le four à 180 degrés.', PRISE], ['Envoyé !', 'Envoie-le toi-même.', ENVOI], ['Appliqué.', 'Applique deux couches.', CURATEUR]]) {
    assert.deepStrictEqual(familles(participe, []), [famille], participe);
    assert.deepStrictEqual(familles(participe.toUpperCase(), []), [famille], participe.toUpperCase());
    assert.deepStrictEqual(familles(imperatif, []), [], imperatif);
  }
});

// --- des tournures qui se disent aussi d'un autre outil ---------------------------------------------------------------
test('un geste réussi avec un outil voisin n\'est pas une fausse alerte', () => {
  assert.deepStrictEqual(promessesEnLAir("C'est programmé : alarme à 7 h 30.", [maison('telephone', { action: 'alarme', heure: '7:30' })]), []);
  assert.deepStrictEqual(promessesEnLAir("J'ai programmé une alarme à 7 h 30.", [maison('telephone', { action: 'alarme', heure: '7:30' })]), []);
  assert.deepStrictEqual(promessesEnLAir("J'ai programmé une alarme à 7 h 30.", []), [{ famille: TELEPHONE, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("C'est allumé.", [maison('telephone', { action: 'lampe', etat: 'on' })]), []);
  assert.deepStrictEqual(promessesEnLAir("J'ai ouvert la page : elle parle du paillage.", [agent('lire_page', { action: 'page', cible: 'https://exemple.fr' }, { resultat: 'CONTENU DE LA PAGE…' })]), []);
  assert.deepStrictEqual(promessesEnLAir("J'ai ouvert le globe sur ton téléphone.", [maison('oeil', { action: 'montrer', cible: 'avion' })]), []);
  assert.deepStrictEqual(promessesEnLAir("Je t'ai envoyé le PDF sur Telegram.", [maison('creer_pdf', { titre: 'x' })]), []);
  assert.deepStrictEqual(promessesEnLAir("Je l'ai envoyé à l'imprimante.", [maison('imprimante_3d', { action: 'envoyer', fichier: 'x.gcode', confirmer: 'oui' })]), []);
  assert.deepStrictEqual(promessesEnLAir("J'ai ajouté le rendez-vous à ton agenda.", [maison('planificateur', { action: 'ajouter' })]), []);
});
test('« je te préviendrai » est légitime après un outil qui travaille en arrière-plan et prévient à la fin', () => {
  const phrase = "Je regarde la vidéo en entier, je te préviendrai quand la fiche sera prête.";
  assert.deepStrictEqual(promessesEnLAir(phrase, [maison('vision_video', { action: 'analyser', source: 'https://youtu.be/x' })]), []);
  assert.deepStrictEqual(promessesEnLAir("La récolte est partie, je t'avertirai à la fin.", [maison('recolte_youtube', { cible: 'Chaîne' })]), []);
  assert.deepStrictEqual(promessesEnLAir(phrase, [agent('enquete_osint', { requete: 'Durand Toitures' }, 'Fiche…')]), []);
  // sans rien avoir lance, la meme phrase reste une promesse en l'air (comme dans la regle existante d'Archi)
  assert.deepStrictEqual(promessesEnLAir(phrase, []), [{ famille: RAPPEL, raison: 'aucun_outil' }]);
  // et « je te le rappellerai » ne se dit que du planificateur
  assert.deepStrictEqual(promessesEnLAir('Je te le rappellerai demain.', [maison('vision_video', { action: 'analyser' })]), [{ famille: RAPPEL, raison: 'aucun_outil' }]);
});

// --- actesDesSteps ----------------------------------------------------------------------------------------------------
test('actesDesSteps : le vrai nom de l\'outil, son action, son statut', () => {
  const steps = [
    maison('planificateur', { action: 'ajouter', texte: 'x' }),
    maison('prises_shelly', { action: 'eteindre' }, ACCORD),
    maison('imprimante_3d', { action: 'etat' }, PANNE),
    agent('navigateur', { action: 'Ouvrir', cible: 'sncf.fr', valeur: '' }, 'Page ouverte : SNCF Connect.'),
    agent('lire_page', { action: 'page', cible: 'https://exemple.fr' }, { resultat: "ERREUR : la page n'a pas répondu" }),
    agent('Wikipedia', 'Vauban', 'Sébastien Le Prestre de Vauban…'),
  ];
  assert.deepStrictEqual(actesDesSteps(steps), [
    { outil: 'planificateur', action: 'ajouter', statut: 'fait' },
    { outil: 'prises_shelly', action: 'eteindre', statut: 'attente_accord' },
    { outil: 'imprimante_3d', action: 'etat', statut: 'erreur' },
    { outil: 'navigateur', action: 'ouvrir', statut: 'inconnu' },
    { outil: 'lire_page', action: 'page', statut: 'erreur' },
    { outil: 'wikipedia', action: '', statut: 'inconnu' },
  ]);
});
test('actesDesSteps : toutes les formes de toolInput et de parametres', () => {
  const obs = JSON.stringify(FAIT);
  const attendu = [{ outil: 'curateur', action: 'appliquer', statut: 'fait' }];
  for (const toolInput of [
    '{"action":"utiliser","outil":"curateur","parametres":{"action":"appliquer","numeros":"1 et 3"},"accord":"oui"}',            // une chaine JSON
    { action: 'utiliser', outil: 'curateur', parametres: { action: 'appliquer' }, accord: 'oui' },                                 // un objet
    { input: '{"action":"utiliser","outil":"curateur","parametres":{"action":"appliquer"}}' },                                    // l'enveloppe de n8n
    { input: { action: 'utiliser', outil: 'curateur', parametres: { action: 'appliquer' } } },
    { action: 'utiliser', outil: 'curateur', parametres: '{"action":"appliquer","numeros":"tout"}' },                              // parametres en chaine JSON
    { action: 'utiliser', outil: 'curateur', parametres: { parametres: { action: 'appliquer' } } },                                // un niveau imbrique
    { action: 'appliquer', outil: 'curateur' },                                                                                     // l'action au premier niveau
    { action: 'Utiliser', outil: ' Curateur ', parametres: { action: 'Appliquer.' } },                                             // casse, espaces, ponctuation
  ]) {
    assert.deepStrictEqual(actesDesSteps([{ action: { tool: 'outils_maison', toolInput }, observation: obs }]), attendu, JSON.stringify(toolInput));
  }
  // la liste des outils n'est pas un outil ; une entree illisible reste un appel a outils_maison dont on ne sait rien
  assert.deepStrictEqual(actesDesSteps([{ action: { tool: 'outils_maison', toolInput: '{"action":"liste"}' }, observation: '{"ok":true,"outils":[]}' }]),
    [{ outil: 'outils_maison', action: 'liste', statut: 'fait' }]);
  assert.deepStrictEqual(actesDesSteps([{ action: { tool: 'outils_maison', toolInput: 'allume le radiateur' }, observation: '{"ok":true,"outils":[]}' }]),
    [{ outil: 'outils_maison', action: 'liste', statut: 'fait' }]);
  assert.deepStrictEqual(actesDesSteps([{ action: { tool: 'outils_maison', toolInput: '{pas du json' }, observation: obs }]), [{ outil: 'outils_maison', action: '', statut: 'fait' }]);
  // le NOM de l'outil mis a la place de l'action (le lanceur l'accepte depuis le 19/11) ; une action sans outil reste une erreur
  assert.deepStrictEqual(actesDesSteps([{ action: { tool: 'outils_maison', toolInput: '{"action":"telephone","parametres":{"action":"minuteur","minutes":12}}' }, observation: obs }]),
    [{ outil: 'telephone', action: 'minuteur', statut: 'fait' }]);
  assert.deepStrictEqual(promessesEnLAir('Minuteur lancé pour 12 minutes.', [{ action: { tool: 'outils_maison', toolInput: '{"action":"telephone","parametres":{"action":"minuteur"}}' }, observation: obs }]), []);
  assert.deepStrictEqual(actesDesSteps([{ action: { tool: 'outils_maison', toolInput: '{"action":"construire","texte":"x"}' },
    observation: '{"ok":false,"phrase_pour_utilisateur":"Il manque le nom de l\'outil. « construire » est une action de : mecanicien."}' }]),
  [{ outil: 'outils_maison', action: 'construire', statut: 'erreur' }]);
});
test('actesDesSteps : les statuts', () => {
  const statut = observation => actesDesSteps([{ action: { tool: 'outils_maison', toolInput: { action: 'utiliser', outil: 'x' } }, observation }])[0].statut;
  assert.strictEqual(statut('{"ok":true,"phrase_pour_utilisateur":"fait"}'), 'fait');
  assert.strictEqual(statut({ ok: true }), 'fait');
  assert.strictEqual(statut('{"phrase_pour_utilisateur":"sans champ ok"}'), 'fait');
  assert.strictEqual(statut('{"ok":false,"accord_requis":true}'), 'attente_accord');
  assert.strictEqual(statut('{"ok":true,"essai":true}'), 'attente_accord');
  assert.strictEqual(statut('{"ok":false,"erreur":"timeout"}'), 'erreur');
  assert.strictEqual(statut('[{"json":{"ok":false,"phrase_pour_utilisateur":"non"}}]'), 'erreur');
  assert.strictEqual(statut({ response: '{"ok":false}' }), 'erreur');
  assert.strictEqual(statut('un texte libre'), 'inconnu');
  assert.strictEqual(statut(''), 'inconnu');
  assert.strictEqual(statut(undefined), 'inconnu');
  assert.strictEqual(statut(42), 'inconnu');
});
test('une réponse d\'outil illisible compte comme faite : on n\'accuse pas à tort', () => {
  const illisible = { action: { tool: 'outils_maison', toolInput: '{"action":"utiliser","outil":"prises_shelly","parametres":{"action":"eteindre"},"accord":"oui"}' }, observation: 'La prise radiateur est éteinte.' };
  assert.deepStrictEqual(actesDesSteps([illisible]), [{ outil: 'prises_shelly', action: 'eteindre', statut: 'inconnu' }]);
  assert.deepStrictEqual(promessesEnLAir("J'ai éteint la prise du radiateur.", [illisible]), []);
  // un appel a outils_maison dont l'entree est illisible et qui a reussi : on ne sait pas quel outil a tourne, rien n'est signale
  const flou = { action: { tool: 'outils_maison', toolInput: '{"action":"utiliser","outil":"prises_shelly",,' }, observation: '{"ok":true,"phrase_pour_utilisateur":"fait"}' };
  assert.deepStrictEqual(promessesEnLAir("J'ai éteint la prise du radiateur.", [flou]), []);
  // … sauf l'envoi d'un mail, qu'aucun outil d'Archi ne fait
  assert.deepStrictEqual(promessesEnLAir("J'ai envoyé le mail.", [flou]), [{ famille: ENVOI, raison: 'aucun_outil' }]);
});

// --- jamais d'exception -------------------------------------------------------------------------------------------------
test('une entrée bizarre ne lève jamais d\'exception et ne signale rien', () => {
  const cyclique = {}; cyclique.moi = cyclique;
  for (const reponse of [null, undefined, '', '   \n', 0, 42, {}, [], cyclique, () => 1, Symbol('x'), Object.create(null), NaN, true]) {
    for (const steps of [null, undefined, '', 'texte', 7, {}, [null, undefined, 3, 'x', [], {}, { action: null }, { action: 5, observation: cyclique }, { action: { tool: {}, toolInput: [] }, observation: [] }]]) {
      assert.deepStrictEqual(promessesEnLAir(reponse, steps), []);
      assert.ok(Array.isArray(actesDesSteps(steps)));
    }
  }
  // une vraie phrase avec des pas illisibles : le verdict ne depend que de la phrase
  assert.deepStrictEqual(promessesEnLAir("J'ai éteint la prise.", [null, 3, { observation: cyclique }, { action: { tool: 'outils_maison', toolInput: { action: 'utiliser', outil: {}, parametres: cyclique } } }]),
    [{ famille: PRISE, raison: 'aucun_outil' }]);
  assert.strictEqual(avertissement(null), '');
  assert.strictEqual(avertissement('x'), '');
  assert.strictEqual(avertissement([null, {}, { famille: 5 }, { famille: '  ' }]), '');
});

// --- ce qu'on dit a l'utilisateur ---------------------------------------------------------------------------------------
test('avertissement : une seule phrase, dans le ton de verifier_reponse.js, différente selon la raison', () => {
  const rien = avertissement([{ famille: RAPPEL, raison: 'aucun_outil' }]);
  const accord = avertissement([{ famille: PRISE, raison: 'outil_refuse' }]);
  const panne = avertissement([{ famille: IMPRESSION, raison: 'outil_en_erreur' }]);
  assert.strictEqual(rien, "⚠️ À vérifier : j'annonce un rappel programmé, mais je n'ai appelé aucun outil pour ça à l'instant, donc rien de nouveau n'est fait. Si tu le veux, redemande-le-moi.");
  assert.match(accord, /^⚠️ À vérifier : j'annonce une prise allumée ou éteinte, mais l'outil attend encore ton accord, donc ce n'est pas fait\./);
  assert.match(panne, /^⚠️ À vérifier : j'annonce une impression 3D lancée, mise en pause ou annulée, mais l'outil a échoué, donc ce n'est pas fait\./);
  assert.strictEqual(new Set([rien, accord, panne].map(p => p.replace(/j'annonce .*?, mais/, ''))).size, 3);
  assert.strictEqual(avertissement([]), '');
  for (const p of [rien, accord, panne]) assert.ok(!/\n/.test(p) && p.length < 230, p);
});
test('avertissement : plusieurs manques tiennent en une phrase', () => {
  const deux = avertissement([{ famille: RAPPEL, raison: 'aucun_outil' }, { famille: ENVOI, raison: 'aucun_outil' }, { famille: RAPPEL, raison: 'aucun_outil' }]);
  assert.match(deux, /j'annonce un rappel programmé et un envoi, mais je n'ai appelé aucun outil/);
  const trois = avertissement([{ famille: RAPPEL, raison: 'aucun_outil' }, { famille: PDF, raison: 'aucun_outil' }, { famille: ENVOI, raison: 'aucun_outil' }]);
  assert.match(trois, /un rappel programmé, un PDF ou une présentation créés et un envoi, mais/);
  // des raisons melees : la plus grave (rien appele), avec les seules familles qu'elle concerne ; la phrase reste vraie
  const mele = avertissement([{ famille: PRISE, raison: 'outil_refuse' }, { famille: ENVOI, raison: 'aucun_outil' }]);
  assert.match(mele, /j'annonce un envoi, mais je n'ai appelé aucun outil/);
  assert.doesNotMatch(mele, /prise/);
  assert.strictEqual((mele.match(/À vérifier/g) || []).length, 1);
});
test('du texte à l\'avertissement, comme le fera le nœud Verifier', () => {
  const steps = [maison('prises_shelly', { action: 'allumer', prise: 'radiateur' }, ACCORD)];
  const phrase = avertissement(promessesEnLAir("C'est fait, le radiateur est allumé.", steps));
  assert.match(phrase, /une prise allumée ou éteinte, mais l'outil attend encore ton accord/);
  assert.strictEqual(avertissement(promessesEnLAir('Le radiateur attend ton accord : tu confirmes ?', steps)), '');
});

// --- relecture du 19/11 : le geste d'un autre, ou ce que dit une source, n'est pas une affirmation d'Archi ---------
test('un passif dont l\'auteur est quelqu\'un d\'autre ne déclenche rien', () => {
  for (const phrase of [
    'Le document a été transmis au notaire par ton père, selon le courrier.',
    'D\'après la facture, le colis a été envoyé le 12 novembre.',
    'Selon le courrier, le dossier est parti lundi.',
    'L\'impression a été lancée par ton frère ce matin.',
  ]) assert.deepStrictEqual(promessesEnLAir(phrase, []), [], phrase);
});
test('« j\'ai… par… » reste une affirmation d\'Archi', () => {
  assert.strictEqual(promessesEnLAir('J\'ai éteint la prise par l\'appli.', []).length, 1);
  assert.strictEqual(promessesEnLAir('J\'ai envoyé le mail par la messagerie.', []).length, 1);
});

// ==========================================================================================================================
// Apres la relecture du 19/11 (RELECTURE.md) : zero avertissement a tort, quitte a relever moins de mensonges.
// Chaque regle a au moins une entree de l'annexe.
// ==========================================================================================================================
const lecturePrise = maison('prises_shelly', { action: 'etat' }, { ok: true, phrase_pour_utilisateur: 'Le radiateur est éteint, 0 W.' });
const lectureRappels = maison('planificateur', { action: 'lister' }, { ok: true, phrase_pour_utilisateur: '2 rappels : sortir le gâteau, appeler le garagiste.' });
const lectureImpression = maison('imprimante_3d', { action: 'etat' }, { ok: true, phrase_pour_utilisateur: "L'impression de benchy.gcode est en cours : 42 %." });
const mailsCherches = maison('ranger_mails', { action: 'chercher', compte: 'gmail' }, { ok: true, phrase_pour_utilisateur: '3 mails trouvés.' });
const pageLue = agent('lire_page', { url: 'https://exemple.fr' }, 'CONTENU DE LA PAGE https://exemple.fr :\n\nLe colis a été envoyé le 3 novembre.');
const pdfLu = maison('lire_pdf', { action: 'lire', nom: 'facture' }, { ok: true, texte: 'Facture EDF…', phrase_pour_utilisateur: 'PDF lu.' });
const wiki = agent('Wikipedia', { input: 'Napoleon' }, 'Page: Napoleon…');

const REGLE_A = [   // apres une LECTURE reussie de l'outil, ce qui decrit ce qu'il lit n'est jamais releve
  ["C'est éteint.", lecturePrise], ['Oui, c\'est allumé.', lecturePrise], ['Allumé, 1200 W.', lecturePrise], ['Éteint. Il consomme 0 W.', lecturePrise], ['Toujours éteint.', lecturePrise],
  ['Oui, c\'est programmé : le gâteau à 14 h 11.', lectureRappels], ['Oui, je te le rappellerai à 14 h 11 : c\'est dans la liste.', lectureRappels],
  ["J'ai programmé deux rappels pour toi : sortir le gâteau et appeler le garagiste.", lectureRappels],
  ["L'impression a été lancée à 13 h et se termine vers 15 h.", lectureImpression], ["L'impression a été annulée : l'imprimante est à l'arrêt.", lectureImpression],
  ['Le mail est bien envoyé : je le vois dans tes messages envoyés.', mailsCherches], ['Dans Envoyés : le mail à Paul est bien parti lundi.', mailsCherches],
];
for (const [phrase, lecture] of REGLE_A) {
  test('règle (a), après une lecture : « ' + phrase + ' »', () => assert.deepStrictEqual(promessesEnLAir(phrase, [lecture]), []));
}
test('règle (a) : « j\'ai… » reste une affirmation après une lecture', () => {
  assert.deepStrictEqual(promessesEnLAir("J'ai éteint le radiateur.", [lecturePrise]), [{ famille: PRISE, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("C'est fait, je l'ai éteint.", [lecturePrise]), [{ famille: PRISE, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("J'ai lancé l'impression.", [lectureImpression]), [{ famille: IMPRESSION, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("J'ai ajouté un rappel pour demain.", [lectureRappels]), [{ famille: RAPPEL, raison: 'aucun_outil' }]);
  // et la lecture d'un AUTRE outil ne fait pas taire : « c'est eteint » apres la liste des rappels reste releve
  assert.deepStrictEqual(promessesEnLAir("C'est éteint.", [lectureRappels]), [{ famille: PRISE, raison: 'aucun_outil' }]);
});

const REGLE_B = [   // des qu'un outil a LU un contenu, les passifs et les constats racontent ce contenu
  ['Résumé : le mail a été envoyé à tous les clients, puis l\'entreprise s\'est excusée.', pageLue], ['Le colis est parti. Le mail a été envoyé à tous les clients.', pageLue],
  ['Tutoriel résumé : 1) le fichier est envoyé à l\'imprimante 2) l\'impression est lancée 3) on attend.', pageLue], ['Dans la facture : la lettre de relance est partie le mois dernier.', pdfLu],
  ['Le courrier a été envoyé le 3 novembre et demande une réponse sous quinze jours.', pdfLu], ['Wikipédia : le premier courriel a été envoyé en 1971.', wiki],
  ["L'impression est lancée depuis l'écran, explique la page.", pageLue], ['Le mail est parti lundi, la prise est éteinte la nuit.', pageLue],
];
for (const [phrase, lecture] of REGLE_B) {
  test('règle (b), après un contenu lu : « ' + phrase.slice(0, 70) + ' »', () => assert.deepStrictEqual(promessesEnLAir(phrase, [lecture]), []));
}
test('règle (b) : ce que l\'assistant dit en son nom reste relevé après un contenu lu', () => {
  assert.deepStrictEqual(promessesEnLAir("J'ai envoyé le mail à tous les clients.", [pageLue]), [{ famille: ENVOI, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("C'est envoyé !", [pageLue]), [{ famille: ENVOI, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("J'ai éteint la prise.", [pdfLu]), [{ famille: PRISE, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir('Je viens de lancer l\'impression.', [wiki]), [{ famille: IMPRESSION, raison: 'aucun_outil' }]);
});

const REGLES_C_D = [   // un recit date ou situe, une generalite
  'Le premier SMS a été envoyé en 1992.', 'Le premier e-mail a été envoyé en 1971 par Ray Tomlinson.', 'En 1969, le premier message a été transmis entre deux ordinateurs sur Arpanet.',
  'Le message est parti de Marathon et le coureur est mort en arrivant à Athènes.', "L'imprimerie a été inventée par Gutenberg. La première impression est lancée vers 1450.",
  'Oui, le 14 juillet 1789 la Bastille a été prise. Le message a été envoyé au roi le soir même.', 'Morse : le premier message a été transmis en 1844, « What hath God wrought ».',
  "Chez Prusa, l'impression est lancée depuis l'écran ou depuis PrusaLink.", "Sur Klipper, l'impression est annulée avec CANCEL_PRINT.", 'Sur une Shelly, la prise est éteinte par défaut après une coupure de courant.',
  'Dans Gmail, un mail est rangé dans un libellé, pas dans un dossier.', 'Les mails sont triés par date dans ta boîte.', "Un mail est envoyé en quelques secondes, alors qu'une lettre met deux jours.",
  "C'est programmé en Python, avec un peu de JavaScript.", 'Éteint, un radiateur ne consomme rien.', 'Envoyé trop tard, un mail de relance ne sert à rien.', 'Programmé pour le 12, le concert a été reporté.',
  'Appliqué deux fois par jour, ce produit suffit.', "Tout à l'heure j'ai créé le PDF du paillage, il doit être dans tes documents.", "La dernière fois, j'ai lancé l'impression du benchy sans souci.",
  "Dis-moi oui et c'est envoyé à l'imprimante.", "Un mot de toi et c'est programmé.",
  "Ton frère dit que le mail est parti. Je n'ai aucun moyen de le vérifier.", 'Elle répond que le courrier a été posté lundi.', "Paul t'écrit : c'est envoyé, tu peux regarder.",
  "OK, c'est noté : le radiateur est éteint, tu l'as fait toi-même.", "Entendu, tu as lancé l'impression toi-même. L'impression est lancée, donc je ne touche à rien.",
  "D'accord, puisque le PDF est créé de ton côté, envoie-le-moi.",
];
for (const phrase of REGLES_C_D) {
  test('règles (c) et (d), récit ou généralité : « ' + phrase.slice(0, 70) + ' »', () => assert.deepStrictEqual(promessesEnLAir(phrase, []), []));
}

const REGLE_E = [   // le texte d'un brouillon, d'une citation, d'un exemple, d'une liste d'etats n'est pas la parole de l'assistant
  "Brouillon pour ton propriétaire :\n\nBonjour,\nJ'ai envoyé le mail avec le RIB hier. Pouvez-vous confirmer ?\nMerci",
  "Voici un brouillon :\n\nMadame, Monsieur,\n\nJe vous ai envoyé un courrier le 3 novembre, resté sans réponse.\n\nCordialement,",
  "Voici le mail :\n\nObjet : relance\n\nBonjour, j'ai envoyé le document le 3 novembre et je n'ai pas eu de réponse.",
  'Objet : chèque de caution\n\nBonjour Monsieur,\nJe vous ai transmis le document signé par courrier. Le chèque est parti ce matin.\nBien à vous',
  "Je te propose ce texte pour ta mère : Coucou maman, j'ai éteint le radiateur avant de partir, ne t'inquiète pas.", "Tu peux lui répondre : c'est fait, j'ai lancé l'impression ce matin.",
  "Texte du SMS :\nMaman, j'ai mis une alarme pour demain 7 h, je t'appelle au réveil.", "Petit poème :\nJ'ai allumé le radiateur\nEt mon chat ronronne de bonheur",
  "Histoire courte : le robot dit « c'est fait », mais rien n'était fait. J'ai éteint la prise, répéta-t-il. Personne ne le crut.",
  "En français on écrit : j'ai envoyé la lettre (participe passé en é).", "Correction de ta phrase : J'ai envoyé le courrier hier, et non « j'ai envoyer ».",
  "La conjugaison : j'ai éteint la prise, tu as éteint la prise, il a éteint la prise.", "Exemple de journal de bord : 8 h, j'ai lancé l'impression ; 9 h, j'ai rangé les mails.",
  'Étapes :\n1. Mail envoyé au client\n2. Devis signé\n3. Facture créée', '- Rappel programmé : non\n- Mail envoyé : non\n- PDF créé : non', '| Tâche | État |\n| Mail envoyé | à faire |\n| PDF créé | à faire |',
];
for (const phrase of REGLE_E) {
  test('règle (e), texte cité : ' + JSON.stringify(phrase.slice(0, 60)), () => assert.deepStrictEqual(promessesEnLAir(phrase, []), []));
}
test('règle (e) : ce que l\'assistant affirme AVANT le texte cité reste relevé', () => {
  assert.deepStrictEqual(promessesEnLAir("J'ai envoyé le mail. Voici son texte :\n\nBonjour,\nMerci de votre retour.", []), [{ famille: ENVOI, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("C'est programmé : je te rappelle à 15 h 42 de sortir le gâteau.", []), [{ famille: RAPPEL, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir("- J'ai éteint la prise\n- J'ai lancé l'impression", []), [{ famille: PRISE, raison: 'aucun_outil' }, { famille: IMPRESSION, raison: 'aucun_outil' }]);
});

// --- les mensonges nets que la relecture demandait de relever ---------------------------------------------------------------
for (const [phrase, famille] of [['Ton mail vient de partir.', ENVOI], ["J'ai supprimé les mails de pub.", SUPPRIMES], ['Les spams sont supprimés.', SUPPRIMES], ["L'impression a démarré.", IMPRESSION],
  ["L'impression a commencé.", IMPRESSION], ["L'imprimante a démarré.", IMPRESSION], ["J'ai mis le chauffage.", PRISE], ["J'ai nettoyé ta boîte mail.", MAILS], ['Ta boîte est triée.', MAILS],
  ["Je t'y ferai penser demain.", RAPPEL], ['Tu seras prévenu demain à 9 h.', RAPPEL], ['Le rappel est en place.', RAPPEL], ['Prise éteinte ✅', PRISE], ['✅ Radiateur allumé', PRISE],
  ['**Radiateur allumé** pour 3 heures.', PRISE], ["J'ai mis l'impression en pause.", IMPRESSION]]) {
  test('mensonge net relevé : « ' + phrase + ' »', () => assert.deepStrictEqual(promessesEnLAir(phrase, []), [{ famille, raison: 'aucun_outil' }]));
}
test('aucun outil ne supprime de mail : « j\'ai supprimé les mails » est relevé même après un rangement réussi', () => {
  assert.deepStrictEqual(promessesEnLAir("J'ai supprimé les mails de pub.", [maison('ranger_mails', { action: 'deplacer', vers: 'Pub', confirmer: true })]), [{ famille: SUPPRIMES, raison: 'aucun_outil' }]);
});
test('ce que la pièce ne relève pas, par choix (dans le doute, rien)', () => {
  for (const phrase of ["C'est fait.", 'Voilà, c\'est fait !', "Je m'en suis occupé.", 'Le radiateur chauffe maintenant.', "J'ai appelé le garagiste.", "J'ai payé la facture EDF.", 'Voici ton PDF.',
    "L'impression tourne."]) assert.deepStrictEqual(promessesEnLAir(phrase, []), [], phrase);
  assert.deepStrictEqual(promessesEnLAir('Les 3 mails sont rangés.', [mailsCherches]), []);      // regle (a) : on ne peut pas le distinguer d'un compte rendu
});

// --- les temps (relecture, 2) -------------------------------------------------------------------------------------------------
test('aucune entrée ne dépasse 50 ms : la réponse est bornée et resserrée avant toute lecture', () => {
  const rep = (s, n) => s.repeat(Math.ceil(n / s.length)).slice(0, n);
  const N = 20000;
  const entrees = { 'a.....a': 'a' + rep('.', N) + 'a', '?!?!': 'a' + rep('?!', N) + 'a', 'a----a': 'a' + rep('-', N) + 'a', 'a____a': 'a' + rep('_', N) + 'a', 'a****a': 'a' + rep('*', N) + 'a',
    'a,,,,a': 'a' + rep(',', N) + 'a', 'a::::a': 'a' + rep(':', N) + 'a', 'a((((a': 'a' + rep('(', N) + 'a', 'virgule espace': 'a' + rep(', ', N) + 'a', 'retours': rep('\n', N) + 'a',
    'espaces': rep(' ', N) + 'a', 'guillemets': rep('"' + 'a'.repeat(401), N), 'phrases': rep("J'ai envoyé le mail à Durieux. J'ai éteint la prise du radiateur. ", N),
    'sans point': rep("j'ai envoye le mail a durieux et j'ai eteint la prise du radiateur ", N) };
  promessesEnLAir('x', []);
  const chrono = (nom, f) => { const d = process.hrtime.bigint(); const r = f(); const ms = Number(process.hrtime.bigint() - d) / 1e6; assert.ok(Array.isArray(r), nom); assert.ok(ms < 50, nom + ' : ' + ms.toFixed(1) + ' ms'); };
  for (const nom of Object.keys(entrees)) chrono(nom, () => promessesEnLAir(entrees[nom], [lecturePrise]));
  chrono('2000 pas', () => promessesEnLAir("J'ai envoyé le mail.", Array.from({ length: 2000 }, () => lecturePrise)));
  chrono('observation de 7 Mo', () => promessesEnLAir("C'est programmé.", [{ action: { tool: 'x' }, observation: rep('rappel ', 7e6) }]));
});
test('une réponse très longue est lue par ses deux bouts : un mensonge au début ou à la fin reste relevé', () => {
  const milieu = 'Voici la suite du texte, sans rien de particulier. '.repeat(600);      // 30 000 caracteres
  assert.deepStrictEqual(promessesEnLAir("J'ai éteint la prise. " + milieu, []), [{ famille: PRISE, raison: 'aucun_outil' }]);
  assert.deepStrictEqual(promessesEnLAir(milieu + " J'ai éteint la prise.", []), [{ famille: PRISE, raison: 'aucun_outil' }]);
});

// --- une sonde a l'aveugle, ecrite apres les corrections (ni dans la relecture, ni dans les tests d'avant) ------------------
test('sonde : vingt réponses honnêtes neuves, aucune avertie ; dix mensonges neufs, tous relevés', () => {
  const lu = (outil, params) => maison(outil, params);
  for (const [steps, reponse] of [
    [[], "Le chauffage central a été inventé par les Romains : l'hypocauste."],
    [[], 'Ta question est bonne. Une impression 3D est lancée couche par couche, du bas vers le haut.'],
    [[], "Voici une idée de message pour Paul :\n\nSalut Paul, j'ai créé le PDF dont on parlait, je te l'envoie ce soir."],
    [[], "Non, rien n'a été envoyé : je n'ai pas d'outil pour les mails."],
    [[], 'Si tu confirmes, le radiateur sera éteint dans la foulée.'],
    [[], "D'après ta fiche, ton rappel du mardi est programmé depuis le mois dernier."],
    [[lu('prises_shelly', { action: 'etat' })], 'Le radiateur est éteint et la prise du PC est allumée.'],
    [[lu('planificateur', { action: 'lister' })], 'Trois rappels sont programmés, le prochain est demain à 9 h.'],
    [[lu('ranger_mails', { action: 'chercher' })], 'Le dernier mail de la CAF a été envoyé le 2 novembre ; il est rangé dans Administratif.'],
    [[lu('imprimante_3d', { action: 'etat' })], "L'impression a commencé il y a 40 minutes, elle en est à 31 %."],
    [[lu('lire_pdf', { action: 'lire', nom: 'bail' })], 'Le bail précise que le préavis a été envoyé par le propriétaire en mars.'],
    [[], 'Je note : tu as coupé le chauffage en partant. Bonne route !'],
    [[], "Je n'ai pas compris : veux-tu que j'éteigne la prise ou que je la laisse ?"],
    [[], 'Astuce : un PDF est créé plus vite si le texte est court.'],
    [[], 'Le radiateur est allumé ? Je peux regarder si tu veux.'],
    [[], "Petit rappel de vocabulaire : « j'ai éteint » est le passé composé d'éteindre."],
    [[], 'Rappel : la réunion a été programmée par ton chef pour jeudi.'],
    [[], 'Ok. Quand tu auras envoyé le mail, dis-le-moi.'],
    [[], "Ta mère t'a écrit que le colis est parti ce matin."],
    [[lu('memoire', { action: 'lire' })], "Tu m'avais dit que le radiateur du bureau est éteint l'été."],
  ]) assert.deepStrictEqual(promessesEnLAir(reponse, steps), [], reponse);
  for (const [steps, reponse] of [
    [[], "Voilà, j'ai coupé la prise du radiateur."], [[], "C'est programmé pour demain 8 h."], [[], "J'ai rangé tes 12 mails dans Factures."], [[], 'Le PDF est créé, tu le trouveras dans tes documents.'],
    [[], "Je viens d'envoyer le mail à ton propriétaire."], [[], "J'ai validé l'outil météo."], [[], "L'impression vient d'être lancée."], [[], 'Je te le rappellerai jeudi.'],
    [[lu('prises_shelly', { action: 'etat' })], "Voilà, j'ai rallumé le radiateur."], [[lu('lire_pdf', { action: 'lire' })], "J'ai envoyé le mail de relance."],
  ]) assert.strictEqual(promessesEnLAir(reponse, steps).length, 1, reponse);
});
