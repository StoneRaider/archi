// ecoute.js - le micro qui ecoute en continu, comme une vraie conversation : le mot magique.
//
// Quand le micro est ouvert, la page d'accueil decoupe ta voix en phrases (au silence), les fait transcrire sur le PC
// (/api/ecouter), et les met bout a bout. Rien ne part vers Archi tant que tu n'as pas dit le mot magique :
//   « fin de transmission »  -> tout ce qui precede est envoye a Archi ;
//   « Archi, annule »        -> tout ce qui attendait est jete.
// Ce fichier ne contient que cette logique (pas de micro, pas de reseau) : il se teste seul, et sert au navigateur.
'use strict';
(function (racine) {
  // Whisper ecrit parfois « faim de transmission », « fin de la transmission », « fin de transmissions »
  const FIN = /\b(?:fin|fins|faim)\s+de\s+(?:la\s+)?transmi(?:ss|t)ions?\b[\s.!?…,;:]*/i;
  const ANNULE = /\barchi[\s,.!;:]*(?:annule|annuler|efface)\b[^.!?…]*[.!?…]*/i;

  // (en francais, l'espace avant « ? ! ; : » est voulue : on ne retire que celle qui precede un point ou une virgule)
  const ranger = t => String(t || '').replace(/\s+/g, ' ').replace(/\s+([.,…])/g, '$1').trim();

  /**
   * Ajoute ce qui vient d'etre entendu a ce qui attendait deja.
   * -> { texte, envoyer, annuler } : le texte a garder ou a envoyer, et ce qu'il faut en faire.
   */
  function entendre(enAttente, nouveau) {
    const avant = ranger(enAttente), dit = String(nouveau || '');
    const annule = ANNULE.exec(dit), fin = FIN.exec(dit);
    // « Archi, annule » : on jette tout (sauf si le mot magique est dit APRES : la suite repart de zero et s'envoie)
    if (annule && (!fin || annule.index > fin.index)) return { texte: '', envoyer: false, annuler: true };
    if (fin) {
      const debut = annule ? dit.slice(annule.index + annule[0].length, fin.index) : dit.slice(0, fin.index);
      const texte = ranger((annule ? '' : avant + ' ') + debut);
      return { texte, envoyer: texte.length > 0, annuler: false };
    }
    return { texte: ranger(avant + ' ' + dit), envoyer: false, annuler: false };
  }

  const api = { entendre, FIN, ANNULE };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else racine.ArchiEcoute = api;
})(typeof window !== 'undefined' ? window : globalThis);
