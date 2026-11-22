// reponse_vide.js - Archi ne reste jamais muet : quand le modele ne rend rien, le code dit honnetement ou il en est.
//
// Vu a l'essai reel du 22/11 (modele de 9 milliards de parametres) : apres deux appels d'outil mal ecrits, le modele a
// rendu une reponse VIDE, et la page a affiche « (réponse vide) ». Autre cas : l'agent de n8n s'arrete a sa limite
// d'essais et rend la phrase anglaise « Agent stopped due to max iterations. ».
//
//   estVide(reponse)                 -> true si le modele n'a rien dit (vide, ponctuation seule, reflexion seule, phrase d'arret de n8n)
//   phraseDeSecours(reponse, steps)  -> la phrase a dire a la place, ou '' si la reponse n'est pas vide
//
// Regles tenues ici :
//   1. jamais d'exception, jamais de fichier ni de reseau (les titres lisibles des outils sont donnes par l'appelant) ;
//   2. la phrase ne dit que ce que le tour montre : quels outils ont ete appeles, et si leurs appels ont abouti. Elle
//      n'annonce jamais qu'une action est faite ;
//   3. la reponse d'un outil n'est recopiee que si c'est sa phrase pour l'utilisateur, courte, rendue par le lanceur
//      outils_maison, et qu'elle ne porte ni consigne pour le modele ni contenu exterieur. Jamais le texte d'une page.
'use strict';
const promesses = require('./promesses');

const ARRET_N8N = /^\s*agent stopped due to (?:max iterations|iteration limit|time limit)\.?\s*$/i;
const PHRASE_MAX = 400;
// ce qui trahit une consigne ecrite pour le modele, ou du contenu lu : jamais recopie a l'utilisateur
const POUR_LE_MODELE = /outils_maison|accord\s*=|confirmer\s*=|parametres|"action"|« texte »|\[\[|\]\]|rappelle[- ](?:le|l'outil|outils)|phrase_pour_utilisateur|\{|\}/i;

/** La reponse sans la reflexion d'un modele qui pense a voix haute (<think>…</think>, meme non refermee). */
function sansReflexion(reponse) {
  return String(reponse == null ? '' : reponse).replace(/<think>[\s\S]*?<\/think>/gi, '').replace(/<think>[\s\S]*$/i, '');
}

function estVide(reponse) {
  try {
    if (typeof reponse !== 'string') return reponse == null;
    if (ARRET_N8N.test(reponse)) return true;
    return !/[\p{L}\p{N}]/u.test(sansReflexion(reponse));
  } catch (e) { return false; }
}

const estObjet = x => !!x && typeof x === 'object' && !Array.isArray(x);

/** La phrase pour l'utilisateur du DERNIER appel a outils_maison, si elle peut etre recopiee ('' sinon). */
function dernierePhrase(steps) {
  try {
    for (const pas of steps.slice().reverse()) {
      if (!estObjet(pas) || !estObjet(pas.action) || !/^outils[ _-]?maison$/i.test(String(pas.action.tool || '').trim())) continue;
      const o = promesses._interne.observationDe(pas.observation);
      if (!o) return '';
      const p = o.phrase_pour_utilisateur;
      if (typeof p !== 'string' || o.erreur_format === true || o.outil_direct || Array.isArray(o.outils) || o.accord_requis === true) return '';
      const t = p.replace(/\s+/g, ' ').trim();
      return t.length >= 3 && t.length <= PHRASE_MAX && !POUR_LE_MODELE.test(t) ? t : '';
    }
  } catch (e) { /* dans le doute, rien n'est recopie */ }
  return '';
}

function enumerer(noms) {
  if (noms.length <= 1) return noms.join('');
  return noms.slice(0, -1).join(', ') + ' et ' + noms[noms.length - 1];
}

/**
 * options.titres : { nom_technique: 'Titre lisible' } (config/vitrine.json), facultatif.
 * -> la phrase de secours, ou '' si la reponse du modele n'est pas vide.
 */
function phraseDeSecours(reponse, steps, options) {
  try {
    if (!estVide(reponse)) return '';
    const titres = estObjet(options && options.titres) ? options.titres : {};
    const pas = Array.isArray(steps) ? steps : [];
    const limite = typeof reponse === 'string' && ARRET_N8N.test(reponse);
    const actes = promesses.actesDesSteps(pas);
    const lisible = n => (typeof titres[n] === 'string' && titres[n] ? titres[n] : String(n).replace(/_/g, ' ')).slice(0, 60);
    const noms = [...new Set(actes.map(a => a.outil).filter(n => n && n !== 'outils_maison'))].slice(0, 4).map(n => '« ' + lisible(n) + ' »');
    const debut = limite ? "Je me suis arrêté avant d'arriver à une réponse : trop d'essais à la suite. " : '';
    if (!actes.length) {
      return debut + "Je n'ai pas réussi à formuler de réponse, et je n'ai lancé aucun outil : rien n'a été fait. Redis-moi ta demande, avec d'autres mots si tu peux.";
    }
    const quoi = noms.length ? (noms.length > 1 ? 'les outils ' : "l'outil ") + enumerer(noms) : 'mes outils';
    const phrase = dernierePhrase(pas);
    const cite = phrase ? ' Le dernier outil a répondu : « ' + phrase + ' »' : '';
    const dernier = actes[actes.length - 1].statut;
    if (actes.every(a => a.statut === 'erreur')) {
      return debut + "Je n'ai pas réussi à utiliser " + quoi + " : aucun de mes appels n'a abouti." + cite
        + (phrase ? '' : ' Redemande-le-moi, ou dis-moi autrement ce que tu veux.');
    }
    if (dernier === 'attente_accord') {
      return debut + "J'ai appelé " + quoi + ", mais rien n'est fait : l'outil attend encore ton accord ou ta confirmation." + cite;
    }
    return debut + "J'ai appelé " + quoi + ", mais je n'ai pas réussi à formuler ma réponse." + cite
      + (phrase ? '' : ' Redemande-le-moi : je ne veux rien affirmer sans relire ce que l\'outil a répondu.');
  } catch (e) {
    return estVide(reponse) ? "Je n'ai pas réussi à formuler de réponse. Redis-moi ta demande." : '';
  }
}

module.exports = { estVide, phraseDeSecours, sansReflexion };
