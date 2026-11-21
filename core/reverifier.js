// reverifier.js - Archi ne reprend pas de la conversation un etat qui change : il rappelle l'outil.
//
// Vu a l'essai reel du 21/11 : « Ou en est le montage ? » posee deux fois. La premiere fois l'outil repond « il manque
// numpy ». On installe numpy. La seconde fois le modele n'appelle RIEN et redit « il manque numpy », de memoire : faux.
//
//   outilsNonInterroges(msg, steps, reponse) -> [{outil, nom}]
//
// msg est le message tel que l'agent l'a recu, avec ses consignes d'aiguillage (core/contexte.js). Quand l'aiguillage
// d'un outil « d'etat » s'est declenche (le message demande bien cet outil) et que le tour ne contient AUCUN appel
// d'outil, la reponse ne peut venir que de la conversation ou de l'imagination. On le signale.
//
// LIMITE MESUREE (relecture independante du 21/11) : ce filet ne sait pas distinguer « le message demande l'outil » de
// « le message contient le mot ». 58 signalements a tort sur 77 echanges honnetes, 52 reponses de memoire manquees sur
// 58 (reponses de moins de cinq mots, messages sans aiguillage). Il reste donc EN JOURNAL (core/verifier_reponse.js) :
// un signal a lire apres coup, pas une phrase dite a l'utilisateur. Le vrai remede est dans le prompt (REGLE REVERIFIER)
// et dans les consignes d'aiguillage.
//
// Regles : fonction pure, jamais d'exception, et dans le doute rien n'est signale :
//   - un seul appel d'outil dans le tour, quel qu'il soit, et on se tait (le modele a cherche, meme maladroitement) ;
//   - une reponse qui pose une question (« a quelle heure ? ») n'affirme rien : on se tait ;
//   - la consigne « vie privee » demande justement de n'appeler aucun outil : on se tait.
'use strict';

// le debut de la consigne de chaque aiguillage (config/aiguillages.json), et le nom a dire a l'utilisateur
const OUTILS = [
  { outil: 'monteur', consigne: 'Le monteur video : outil monteur', nom: 'le monteur vidéo' },
  { outil: 'agenda', consigne: "L'agenda : outil agenda", nom: 'ton agenda' },
  { outil: 'recherche_web', consigne: 'Une information recente : outil recherche_web', nom: 'la recherche sur le web' },
  { outil: 'image_lien', consigne: 'Un lien vers une image : outil image_lien', nom: "l'outil qui regarde les images" },
];
const MARQUE = '[CONSIGNE ARCHI] ';
const VIE_PRIVEE = MARQUE + 'Coordonnees ou vie privee';
const MAX = 20000;

/** La reponse affirme-t-elle quelque chose ? Une question (« A quelle heure ? »), meme precedee d'un mot (« Bien sur. »),
 *  n'affirme rien. Une phrase d'au moins cinq mots qui n'est pas une question, si : « Il manque numpy sur ce PC. Tu veux
 *  que je l'installe ? » affirme un etat. */
function affirme(reponse) {
  const phrases = reponse.match(/[^.!?\n]+[.!?]*/g) || [];
  return phrases.some(p => !/\?\s*$/.test(p.trim()) && p.trim().split(/\s+/).filter(w => /[\p{L}\p{N}]/u.test(w)).length >= 5);
}

function outilsNonInterroges(msg, steps, reponse) {
  try {
    if (typeof msg !== 'string' || typeof reponse !== 'string') return [];
    if (Array.isArray(steps) ? steps.length > 0 : steps != null) return [];
    const m = msg.slice(-MAX), r = reponse.slice(0, MAX);
    if (!affirme(r)) return [];
    if (m.includes(VIE_PRIVEE)) return [];
    return OUTILS.filter(o => m.includes(MARQUE + o.consigne)).map(o => ({ outil: o.outil, nom: o.nom }));
  } catch (e) {
    return [];
  }
}

/** La phrase ajoutee sous la reponse ('' s'il n'y a rien a dire). */
function avertissement(liste) {
  try {
    const noms = [...new Set((Array.isArray(liste) ? liste : []).map(o => o && o.nom).filter(n => typeof n === 'string' && n))];
    if (!noms.length) return '';
    const dit = noms.length === 1 ? noms[0] : noms.slice(0, -1).join(', ') + ' et ' + noms[noms.length - 1];
    return "⚠️ À vérifier : je n'ai pas interrogé " + dit + " à l'instant. Ce que je viens de dire vient de notre conversation et a pu changer. "
      + 'Dis « revérifie » et je regarde vraiment.';
  } catch (e) {
    return '';
  }
}

module.exports = { outilsNonInterroges, avertissement, OUTILS };
