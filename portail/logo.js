// logo.js - « Archi » s'ecrit toujours avec son logo : le A dont la barre est un egaliseur, puis RCHI.
//
// Chaque fois que le mot « Archi » apparait a l'ecran (un titre, la visite guidee, une reponse, le fil de la discussion),
// la page le remplace par le dessin du logo, a la taille du texte autour. Le mot reste dans la page, invisible, pour les
// lecteurs d'ecran et le copier-coller. Les zones de saisie, le code et les adresses gardent leurs lettres.
// La decoupe du texte (decouper) ne touche pas a la page : elle se teste seule.
'use strict';
(function (racine) {
  // le mot seul : pas « architecte », pas « archi-agent-local », pas « Archi.apk », pas un bout de chemin de fichier
  const MOT = /(?<![\p{L}\p{N}_\-\\/.@])archi(?![\p{L}\p{N}_\-\\/@]|\.[\p{L}\p{N}])/giu;

  /** « Salut, je suis Archi. » -> ['Salut, je suis ', {archi: 'Archi'}, '.'] */
  function decouper(texte) {
    const t = String(texte == null ? '' : texte), morceaux = [];
    let i = 0, m;
    MOT.lastIndex = 0;
    while ((m = MOT.exec(t))) {
      if (m.index > i) morceaux.push(t.slice(i, m.index));
      morceaux.push({ archi: m[0] });
      i = m.index + m[0].length;
    }
    if (i < t.length) morceaux.push(t.slice(i));
    return morceaux;
  }

  const SVG = 'http://www.w3.org/2000/svg';
  // la ou le mot garde ses lettres : un logo deja pose, un dessin, une saisie, du code
  const SANS_LOGO = '.mot-archi, svg, textarea, input, script, style, code, [data-sans-logo]';

  function mot(document, ecrit) {
    const s = document.createElement('span');
    s.className = 'mot-archi';
    const d = document.createElementNS(SVG, 'svg');
    d.setAttribute('viewBox', '0 0 120 34');
    d.setAttribute('aria-hidden', 'true');
    const u = document.createElementNS(SVG, 'use');
    u.setAttribute('href', '#mot-archi');
    d.appendChild(u);
    const t = document.createElement('span');
    t.textContent = ecrit;
    s.appendChild(d);
    s.appendChild(t);
    return s;
  }

  function poser(document, noeud) {
    const textes = [];
    if (noeud.nodeType === 3) textes.push(noeud);
    else if (noeud.nodeType === 1) {
      const marcheur = document.createTreeWalker(noeud, 4);   // 4 = les textes
      while (marcheur.nextNode()) textes.push(marcheur.currentNode);
    }
    for (const n of textes) {
      const parent = n.parentElement;
      if (!parent || parent.closest(SANS_LOGO)) continue;
      const morceaux = decouper(n.nodeValue);
      if (!morceaux.some(x => typeof x !== 'string')) continue;
      const f = document.createDocumentFragment();
      for (const x of morceaux) f.appendChild(typeof x === 'string' ? document.createTextNode(x) : mot(document, x.archi));
      parent.replaceChild(f, n);
    }
  }

  /** Pose le logo sur toute la page, puis sur tout ce qui s'y ecrira ensuite. */
  function installer(document) {
    poser(document, document.body);
    new racine.MutationObserver(liste => {
      for (const x of liste) {
        if (x.type === 'characterData') poser(document, x.target);
        else for (const n of x.addedNodes) poser(document, n);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  const api = { decouper, installer, MOT };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else racine.ArchiLogo = api;
})(typeof window !== 'undefined' ? window : globalThis);
