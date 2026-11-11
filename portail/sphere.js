// sphere.js - la sphere d'Archi dans le navigateur : le meme dessin que l'appli Android (Sphere.java).
// ~950 points lumineux dans une bulle holographique verte.
//   repos = elle respire ; ecoute = des ondes, et elle gonfle avec la voix ; reflechit = tourbillon ;
//   agit = un outil travaille (tourbillon plus lent, pouls) ; parle = un egaliseur en amande au milieu ;
//   muet = le haut-parleur est coupe (elle respire, sans couleur, un fin anneau le signale) ;
//   des mots-cles montent puis s'effacent.
// Chaque etat a sa couleur (idee reprise de Brahma, sans son code) : repos et parle verts, ecoute cyan,
// reflechit orange, agit violet, muet rouge. La couleur glisse d'un etat a l'autre, jamais de saut.
// Autour d'elle (options.orbites, oui par defaut) : un nuage translucide, quatre orbites inclinees ou filent des cometes
// qui remuent le nuage a leur passage, et des eruptions comme des tempetes solaires qui jaillissent au hasard de la surface.
// Calmes au repos, nombreuses quand elle travaille.
//   options.couleurs : 'teintes' (defaut : le vert d'Archi reste la base, l'etat teinte la bulle et ses points)
//                      ou 'pleines' (toute la sphere prend la couleur de l'etat).
//
//   const s = ArchiSphere(canvas);        // demarre l'animation
//   s.mode('ecoute');                     // repos | ecoute | reflechit | agit | parle | muet
//   s.niveau(() => 0.4);                  // volume du micro (0..1) pendant l'ecoute ; sans lui, un bruit doux
//   s.mots(['Medor', 'chien']);           // mots-cles qui montent
//   s.stop();
// Aucune dependance. Sans animation si l'utilisateur a demande « moins de mouvement ».
'use strict';
(function (racine) {
  const N = 950, NL = 180, NB = 17;
  const MODES = ['repos', 'ecoute', 'reflechit', 'agit', 'parle', 'muet'];
  // la couleur de chaque etat (r, v, b)
  const TEINTES = { repos: [61, 220, 151], parle: [61, 220, 151], ecoute: [34, 211, 238], reflechit: [251, 146, 60],
    agit: [167, 139, 250], muet: [248, 113, 113] };
  const GRIS = [150, 163, 157];
  const melange = (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
  const rgba = (c, a) => 'rgba(' + Math.round(c[0]) + ',' + Math.round(c[1]) + ',' + Math.round(c[2]) + ',' + a.toFixed(3) + ')';
  const BLANC = [236, 255, 246];

  function ArchiSphere(canvas, options) {
    const o = Object.assign({ centreY: 0.5, rayon: 0.36, mots: true, couleurs: 'teintes', orbites: true }, options || {});
    const pleines = o.couleurs === 'pleines';
    // la couleur courante de la bulle et celle de l'anneau « muet » (0 = invisible), qui glissent vers leur cible
    let teinte = TEINTES.repos.slice(), anneau = 0;
    const cible = m => (m === 'muet' && !pleines) ? GRIS : TEINTES[m];
    const c = canvas.getContext('2d');
    const hx = new Float32Array(N), hy = new Float32Array(N), ps = new Float32Array(N), ph = new Float32Array(N), pe = new Float32Array(N);
    const px = new Float32Array(N), py = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const a = Math.random() * 7, r = Math.sqrt(Math.random()) * 0.92;
      hx[i] = Math.cos(a) * r; hy[i] = Math.sin(a) * r;
      ps[i] = 0.6 + Math.random() * 1.1; ph[i] = Math.random() * 7; pe[i] = Math.random() - 0.5;
    }
    // les orbites : inclinaison (rapport des axes), angle dans le plan, rayon, vitesse ; chacune porte deux cometes
    const orbites = [0, 1, 2, 3].map(k => ({ plat: 0.18 + Math.random() * 0.25, angle: Math.random() * Math.PI, rayon: 1.2 + k * 0.12,
      vitesse: (0.25 + Math.random() * 0.3) * (k % 2 ? -1 : 1), derive: (Math.random() - 0.5) * 0.08,
      cometes: [0, 1, 2].map(() => Math.random() * 7) }));
    // le nuage : des grains et quelques bouffees, en anneau epais autour de la bulle ; ils tournent doucement,
    // et une comete qui passe les pousse dans son sens (ox, oy : l'ecart, qui se resorbe)
    const NG = 560, nA = new Float32Array(NG), nD = new Float32Array(NG), nP = new Float32Array(NG), nT = new Float32Array(NG),
      nX = new Float32Array(NG), nY = new Float32Array(NG);
    for (let i = 0; i < NG; i++) {
      nA[i] = Math.random() * 7; nD[i] = 1.04 + Math.pow(Math.random(), 1.6) * 0.85; nP[i] = Math.random() * 7; nT[i] = 0.8 + Math.random() * 1.6;
    }
    const bouffees = Array.from({ length: 22 }, () => ({ a: Math.random() * 7, d: 1.1 + Math.random() * 0.5, r: 0.22 + Math.random() * 0.3,
      v: (Math.random() - 0.5) * 0.12 }));
    const tetes = [];   // les tetes des cometes a cette image : {x, y, vx, vy}
    const eruptions = [];
    let bouffee = null, cb = null, cleBouffee = '';
    try {
      const doc = canvas.ownerDocument || (typeof document !== 'undefined' ? document : null);
      if (doc) { bouffee = doc.createElement('canvas'); bouffee.width = bouffee.height = 64; cb = bouffee.getContext('2d'); }
      if (!cb) bouffee = null;
    } catch (e) { bouffee = null; }
    function dessinerNuage(CX, CY, R, dt, agitation) {
      const k = 0.5 + agitation;
      // les bouffees : de grandes taches tres pales, qui donnent sa matiere au nuage. Une seule image de bouffee,
      // refaite quand la teinte change, puis posee 22 fois (pas 22 degrades a chaque image)
      const cle = Math.round(teinte[0]) + ',' + Math.round(teinte[1]) + ',' + Math.round(teinte[2]);
      if (bouffee && cleBouffee !== cle) {
        const g = cb.createRadialGradient(32, 32, 0, 32, 32, 32);
        g.addColorStop(0, rgba(teinte, 1)); g.addColorStop(1, rgba(teinte, 0));
        cb.clearRect(0, 0, 64, 64); cb.fillStyle = g; cb.fillRect(0, 0, 64, 64); cleBouffee = cle;
      }
      c.globalAlpha = 0.05 + 0.04 * agitation;
      for (const b of bouffees) {
        b.a += b.v * dt * k;
        const x = CX + Math.cos(b.a) * R * b.d, y = CY + Math.sin(b.a) * R * b.d * 0.92, r = R * b.r;
        if (bouffee) c.drawImage(bouffee, x - r, y - r, r * 2, r * 2);
      }
      // les grains : une seule couleur, l'eclat change par globalAlpha (pas une chaine de couleur par grain)
      const cG = melange(BLANC, teinte, 0.45), tl = Math.max(1, R / 150);
      c.fillStyle = 'rgb(' + Math.round(cG[0]) + ',' + Math.round(cG[1]) + ',' + Math.round(cG[2]) + ')';
      const portee = (R * 0.32) * (R * 0.32);
      for (let i = 0; i < NG; i++) {
        nA[i] += (0.03 + 0.09 / nD[i]) * dt * k;
        let x = CX + Math.cos(nA[i]) * R * nD[i], y = CY + Math.sin(nA[i]) * R * nD[i] * 0.92;
        // le sillage des cometes
        for (const h of tetes) {
          const dx = x + nX[i] - h.x, dy = y + nY[i] - h.y, d2 = dx * dx + dy * dy;
          if (d2 < portee) { const f = (1 - d2 / portee) * 0.9; nX[i] += h.vx * f; nY[i] += h.vy * f; }
        }
        const r = Math.min(1, 6 * dt);
        nX[i] -= nX[i] * r * 0.5; nY[i] -= nY[i] * r * 0.5;
        x += nX[i]; y += nY[i];
        const loin = (nD[i] - 1.04) / 0.85;   // les grains du bord sont plus pales
        const al = (0.1 + 0.22 * (0.5 + 0.5 * Math.sin(t * 1.3 + nP[i]))) * (1 - loin * 0.7) * (0.7 + 0.5 * agitation);
        c.globalAlpha = al;
        c.fillRect(x, y, nT[i] * tl, nT[i] * tl);
      }
      c.globalAlpha = 1;
    }
    let prochaineEruption = 0.5;
    let mode = 'repos', t = 0, amp = 0, avant = 0, pret = false, image = 0, arret = false;
    let micro = null, W = 0, H = 0, D = 1;
    const mots = [], enAttente = [];
    let prochainMot = 0;
    const calme = racine.matchMedia && racine.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const bruit = (a, b) => Math.sin(a * 3.1 + b) * 0.5 + Math.sin(a * 5.3 - b * 1.7) * 0.3 + Math.sin(a * 8.7 + b * 2.3) * 0.2;
    // le meme bruit, qui boucle parfaitement sur un tour complet (pas de cassure sur le bord de la bulle)
    const bruitRond = (a, b) => Math.sin(a * 3 + b) * 0.5 + Math.sin(a * 5 - b * 1.7) * 0.3 + Math.sin(a * 9 + b * 2.3) * 0.2;

    function mesurer() {
      const r = canvas.getBoundingClientRect();
      D = Math.min(2, racine.devicePixelRatio || 1);
      W = Math.max(1, r.width); H = Math.max(1, r.height);
      canvas.width = Math.round(W * D); canvas.height = Math.round(H * D);
      pret = false;
    }

    // la bouche : un egaliseur, 17 barres en amande qui montent et descendent avec la voix
    function levres(i, total, a, y0, k, sortie) {
      const col = i % NB, par = Math.floor(total / NB);
      const s = Math.min(1, Math.floor(i / NB) / Math.max(1, par - 1)), u = (col / (NB - 1)) * 2 - 1;
      const tp = Math.pow(Math.max(0, 1 - u * u), 0.75);
      const niv = 0.25 + 0.75 * Math.abs(Math.sin(t * 11 + col * 1.7) * Math.sin(t * 4.3 + col * 0.6));
      const h = Math.max(0.012 * k, (0.03 + 0.24 * a) * k * tp * niv);
      sortie[0] = u * 0.48 * k * 0.86 + pe[i] * 0.012 * k;
      sortie[1] = y0 + (s * 2 - 1) * h;
    }

    // un point d'une orbite (ellipse inclinee) ; z > 0 = devant la bulle
    function surOrbite(ob, a, CX, CY, R) {
      const x = Math.cos(a) * R * ob.rayon, y = Math.sin(a) * R * ob.rayon * ob.plat, ca = Math.cos(ob.angle), sa = Math.sin(ob.angle);
      return [CX + x * ca - y * sa, CY + x * sa + y * ca, Math.sin(a)];
    }
    // devant = false : la moitie arriere des orbites (sous la bulle) ; true : la moitie avant et les cometes
    function dessinerOrbites(CX, CY, R, dt, agitation, devant) {
      const cBord = melange(BLANC, teinte, 0.6);
      if (devant) tetes.length = 0;
      for (const ob of orbites) {
        if (!devant) { ob.angle += ob.derive * dt; for (let i = 0; i < ob.cometes.length; i++) ob.cometes[i] += ob.vitesse * dt * (0.6 + agitation * 1.6); }
        c.lineWidth = 1;
        c.beginPath();
        let ouvert = false;
        for (let i = 0; i <= 96; i++) {
          const a = (i / 96) * 2 * Math.PI, p = surOrbite(ob, a, CX, CY, R);
          if ((p[2] > 0) !== devant) { ouvert = false; continue; }
          if (!ouvert) { c.moveTo(p[0], p[1]); ouvert = true; } else c.lineTo(p[0], p[1]);
        }
        c.strokeStyle = rgba(cBord, (devant ? 0.16 : 0.08) + 0.08 * agitation);
        c.stroke();
        if (!devant) continue;
        // les tetes : pour le sillage dans le nuage (vitesse = un petit pas le long de l'orbite)
        for (const a0 of ob.cometes) {
          const p = surOrbite(ob, a0, CX, CY, R), q = surOrbite(ob, a0 + Math.sign(ob.vitesse) * 0.05, CX, CY, R);
          tetes.push({ x: p[0], y: p[1], vx: (q[0] - p[0]) * 0.35, vy: (q[1] - p[1]) * 0.35 });
        }
        // les cometes : une tete brillante et une trainee de points qui s'eteint
        for (const a0 of ob.cometes) {
          for (let j = 0; j < 14; j++) {
            const p = surOrbite(ob, a0 - Math.sign(ob.vitesse) * j * 0.035, CX, CY, R);
            const profondeur = 0.35 + 0.65 * (p[2] + 1) / 2;   // derriere la bulle, plus pale
            const al = (1 - j / 14) * profondeur * (0.35 + 0.55 * agitation);
            const tl = (j === 0 ? 2.6 : 1.6) * Math.max(1, R / 150);
            c.fillStyle = rgba(j === 0 ? BLANC : cBord, al);
            c.fillRect(p[0] - tl / 2, p[1] - tl / 2, tl, tl);
          }
        }
      }
    }
    // les eruptions : une boucle de matiere qui jaillit de la surface, se tend, puis retombe
    function dessinerEruptions(CX, CY, R, dt, agitation) {
      if (t >= prochaineEruption && eruptions.length < 8) {
        const a = Math.random() * 2 * Math.PI;
        eruptions.push({ a, large: 0.18 + Math.random() * 0.3, haut: 0.3 + Math.random() * (0.3 + 0.4 * agitation), vie: 0,
          duree: 1.6 + Math.random() * 1.8, sens: Math.random() < 0.5 ? -1 : 1 });
        prochaineEruption = t + (0.3 + Math.random() * 1.2) / (0.3 + agitation * 1.6);
      }
      const cE = melange(BLANC, teinte, 0.45);
      for (let i = eruptions.length - 1; i >= 0; i--) {
        const e = eruptions[i];
        e.vie += dt / e.duree;
        if (e.vie >= 1) { eruptions.splice(i, 1); continue; }
        const monte = Math.sin(Math.PI * Math.min(1, e.vie * 1.25));      // elle se tend puis retombe
        const a1 = e.a - e.large / 2, a2 = e.a + e.large / 2;
        const x1 = CX + Math.cos(a1) * R, y1 = CY + Math.sin(a1) * R, x2 = CX + Math.cos(a2) * R, y2 = CY + Math.sin(a2) * R;
        const h = R * (1 + e.haut * monte), xc = CX + Math.cos(e.a + e.sens * 0.06) * h * 1.08, yc = CY + Math.sin(e.a + e.sens * 0.06) * h * 1.08;
        const al = Math.sin(Math.PI * e.vie) * (0.45 + 0.55 * agitation);
        // une lueur le long de la boucle, puis des grains qui y courent
        c.lineWidth = 3 * Math.max(1, R / 150);
        c.strokeStyle = rgba(teinte, al * 0.55);
        c.beginPath(); c.moveTo(x1, y1); c.quadraticCurveTo(xc, yc, x2, y2); c.stroke();
        for (let j = 0; j < 22; j++) {
          const u = ((j / 22) + e.vie * 1.7 * e.sens + 10) % 1, v = 1 - u;
          const px2 = v * v * x1 + 2 * v * u * xc + u * u * x2, py2 = v * v * y1 + 2 * v * u * yc + u * u * y2;
          const tl = 1.9 * Math.max(1, R / 150);
          c.fillStyle = rgba(cE, al * (0.6 + 0.4 * Math.sin(j * 1.7 + t * 6)));
          c.fillRect(px2 + Math.sin(j * 3.1 + t * 4) * 1.5, py2 + Math.cos(j * 2.3 + t * 5) * 1.5, tl, tl);
        }
      }
    }

    function dessiner(maintenant) {
      if (arret) return;
      image = racine.requestAnimationFrame(dessiner);
      const dt = avant === 0 ? 0.016 : Math.min(0.05, (maintenant - avant) / 1000);
      avant = maintenant;
      if (calme && pret && Math.floor(t * 2) === Math.floor((t + dt) * 2)) { t += dt; return; }   // « moins de mouvement » : deux images par seconde
      t += dt;
      const f60 = dt * 60;
      const R0 = Math.min(W, H) * o.rayon, CX = W / 2, CY = H * o.centreY;
      if (!pret) { for (let i = 0; i < N; i++) { px[i] = CX + hx[i] * R0; py[i] = CY + hy[i] * R0; } pret = true; }
      const parle = mode === 'parle', ecoute = mode === 'ecoute', agit = mode === 'agit', tourne = mode === 'reflechit' || agit;
      const kc = Math.min(1, 0.07 * f60);
      teinte = melange(teinte, cible(mode), kc);
      anneau += ((mode === 'muet' && !pleines ? 1 : 0) - anneau) * kc;
      const cPoint = melange(BLANC, teinte, pleines ? 0.5 : 0.32), cBord = melange(BLANC, teinte, pleines ? 0.75 : 0.55);
      const vitesse = agit ? 0.55 : 1, pouls = agit ? 0.5 + 0.5 * Math.sin(t * 5) : 0;
      let vise = 0;
      if (ecoute) vise = micro ? Math.min(1, 0.15 + (micro() || 0)) : 0.35 + 0.6 * Math.abs(bruit(t * 2.2, 1));
      else if (parle) vise = 0.2 + 0.8 * Math.abs(Math.sin(t * 9) * Math.sin(t * 2.3));
      amp += (vise - amp) * Math.min(1, 0.25 * f60);
      const R = R0 * (1 + 0.035 * Math.sin(t * 1.6) + 0.05 * amp);

      c.setTransform(D, 0, 0, D, 0, 0);
      c.clearRect(0, 0, W, H);

      // les ondes d'ecoute
      if (ecoute) {
        c.lineWidth = 1.5;
        for (let i = 0; i < 3; i++) {
          const p = (t * 0.6 + i / 3) % 1;
          c.strokeStyle = rgba(teinte, 0.28 * (1 - p));
          c.beginPath(); c.arc(CX, CY, R * (1.06 + p * 0.45 * (0.4 + amp)), 0, Math.PI * 2); c.stroke();
        }
      }
      // l'agitation autour d'elle : douce au repos, forte quand elle reflechit ou qu'un outil travaille
      const agitation = agit ? 1 : tourne ? 0.8 : ecoute ? 0.45 : parle ? 0.35 : mode === 'muet' ? 0.08 : 0.2;
      if (o.orbites) { dessinerNuage(CX, CY, R, dt, agitation); dessinerOrbites(CX, CY, R, dt, agitation, false); }

      // la bulle holographique
      c.beginPath();
      for (let i = 0; i <= 120; i++) {
        const a = (i / 120) * 2 * Math.PI + (tourne ? t * 0.8 * vitesse : 0);
        const r = R * (1 + 0.035 * bruitRond(a, t * 1.3) + (tourne ? 0.09 * bruitRond(a * 2, t * 4) : 0));
        const x = CX + Math.cos(a) * r, y = CY + Math.sin(a) * r;
        if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
      }
      c.closePath();
      const g = c.createRadialGradient(CX - R * 0.15, CY - R * 0.18, 0, CX - R * 0.15, CY - R * 0.18, R * 1.1);
      g.addColorStop(0, rgba(cPoint, 0.10)); g.addColorStop(0.72, rgba(teinte, 0.03 + 0.04 * pouls)); g.addColorStop(1, rgba(cBord, 0.28 + 0.12 * pouls));
      c.fillStyle = g; c.fill();
      c.lineWidth = 1.2; c.strokeStyle = rgba(cBord, 0.45 + 0.2 * pouls); c.stroke();
      // muet : un fin anneau rouge autour de la bulle grise
      if (anneau > 0.02) {
        c.lineWidth = 2; c.strokeStyle = rgba(TEINTES.muet, 0.7 * anneau);
        c.beginPath(); c.arc(CX, CY, R * 1.09, 0, Math.PI * 2); c.stroke();
      }

      // les points
      const q = [0, 0];
      for (let i = 0; i < N; i++) {
        let tx, ty, lerp = 0.08, lum = 0;
        if (parle && i < NL * 2) { levres(i, NL * 2, amp, 0.15, 1.15, q); tx = q[0]; ty = q[1]; lerp = 0.3; lum = 0.15; }
        else if (tourne) {
          const a = Math.atan2(hy[i], hx[i]) + 0.02 * vitesse * ps[i] * f60, r = Math.hypot(hx[i], hy[i]);
          hx[i] = Math.cos(a) * r; hy[i] = Math.sin(a) * r;
          tx = hx[i] * (1 + 0.08 * Math.sin(t * 6 + ph[i])); ty = hy[i] * (1 + 0.08 * Math.cos(t * 5 + ph[i]));
        } else {
          tx = hx[i] * (1 + 0.25 * amp) + Math.sin(t * 0.7 + ph[i]) * 0.04;
          ty = hy[i] * (1 + 0.25 * amp) + Math.cos(t * 0.9 + ph[i]) * 0.04;
        }
        const l = 1 - Math.pow(1 - lerp, f60);
        px[i] += (CX + tx * R - px[i]) * l;
        py[i] += (CY + ty * R - py[i]) * l;
        const alpha = Math.max(0, Math.min(1, 0.45 + lum + 0.4 * Math.sin(t * 4 + ph[i])));
        c.fillStyle = rgba(cPoint, alpha);
        const taille = ps[i] * 1.45 * Math.max(1, R0 / 150);   // un ecran de PC a moins de points par pouce qu'un telephone
        c.fillRect(px[i], py[i], taille, taille);
      }

      if (o.orbites) { dessinerOrbites(CX, CY, R, 0, agitation, true); dessinerEruptions(CX, CY, R, dt, agitation); }

      // les mots-cles qui montent et s'effacent
      if (o.mots) {
        if (enAttente.length && t >= prochainMot) {
          const w = enAttente.shift(), a = -Math.PI / 2 + (Math.random() - 0.5) * 1.6;
          mots.push({ w, x: CX + Math.cos(a) * R * 0.75, y: CY + Math.sin(a) * R * 0.6, vx: (Math.random() - 0.5) * 0.25, vy: -0.35 - Math.random() * 0.2, vie: 0 });
          prochainMot = t + 0.55;
        }
        c.textAlign = 'center';
        for (let i = mots.length - 1; i >= 0; i--) {
          const m = mots[i];
          m.vie += 0.006 * f60; m.x += m.vx * f60; m.y += m.vy * f60;
          if (m.vie >= 1) { mots.splice(i, 1); continue; }
          c.font = '600 ' + Math.round(Math.max(12, R0 / 11)) + 'px "Segoe UI", system-ui, sans-serif';
          c.fillStyle = rgba(cPoint, 0.85 * Math.sin(Math.PI * m.vie));
          c.fillText(m.w, m.x, m.y);
        }
      }
    }

    mesurer();
    const observateur = racine.ResizeObserver ? new ResizeObserver(mesurer) : null;
    if (observateur) observateur.observe(canvas); else racine.addEventListener('resize', mesurer);
    image = racine.requestAnimationFrame(dessiner);

    return {
      mode(m) { mode = MODES.includes(m) ? m : 'repos'; return this; },
      couleur() { return teinte.map(Math.round); },
      etat() { return mode; },
      niveau(f) { micro = typeof f === 'function' ? f : null; return this; },
      mots(liste) { for (const w of (liste || []).slice(0, 6)) enAttente.push(String(w).slice(0, 24)); return this; },
      stop() { arret = true; racine.cancelAnimationFrame(image); if (observateur) observateur.disconnect(); },
    };
  }

  ArchiSphere.MODES = MODES;
  ArchiSphere.TEINTES = TEINTES;
  racine.ArchiSphere = ArchiSphere;
})(typeof window !== 'undefined' ? window : globalThis);
