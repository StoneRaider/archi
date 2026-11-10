// sphere.js - la sphere d'Archi dans le navigateur : le meme dessin que l'appli Android (Sphere.java).
// ~950 points lumineux dans une bulle holographique verte.
//   repos = elle respire ; ecoute = des ondes, et elle gonfle avec la voix ; reflechit = tourbillon ;
//   parle = un egaliseur en amande au milieu ; des mots-cles montent puis s'effacent.
//
//   const s = ArchiSphere(canvas);        // demarre l'animation
//   s.mode('ecoute');                     // repos | ecoute | reflechit | parle
//   s.niveau(() => 0.4);                  // volume du micro (0..1) pendant l'ecoute ; sans lui, un bruit doux
//   s.mots(['Medor', 'chien']);           // mots-cles qui montent
//   s.stop();
// Aucune dependance. Sans animation si l'utilisateur a demande « moins de mouvement ».
'use strict';
(function (racine) {
  const N = 950, NL = 180, NB = 17;

  function ArchiSphere(canvas, options) {
    const o = Object.assign({ centreY: 0.5, rayon: 0.36, mots: true }, options || {});
    const c = canvas.getContext('2d');
    const hx = new Float32Array(N), hy = new Float32Array(N), ps = new Float32Array(N), ph = new Float32Array(N), pe = new Float32Array(N);
    const px = new Float32Array(N), py = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const a = Math.random() * 7, r = Math.sqrt(Math.random()) * 0.92;
      hx[i] = Math.cos(a) * r; hy[i] = Math.sin(a) * r;
      ps[i] = 0.6 + Math.random() * 1.1; ph[i] = Math.random() * 7; pe[i] = Math.random() - 0.5;
    }
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
      const parle = mode === 'parle', ecoute = mode === 'ecoute', tourne = mode === 'reflechit';
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
          c.strokeStyle = 'rgba(61,220,151,' + (0.28 * (1 - p)).toFixed(3) + ')';
          c.beginPath(); c.arc(CX, CY, R * (1.06 + p * 0.45 * (0.4 + amp)), 0, Math.PI * 2); c.stroke();
        }
      }
      // la bulle holographique
      c.beginPath();
      for (let i = 0; i <= 120; i++) {
        const a = (i / 120) * 2 * Math.PI + (tourne ? t * 0.8 : 0);
        const r = R * (1 + 0.035 * bruitRond(a, t * 1.3) + (tourne ? 0.09 * bruitRond(a * 2, t * 4) : 0));
        const x = CX + Math.cos(a) * r, y = CY + Math.sin(a) * r;
        if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
      }
      c.closePath();
      const g = c.createRadialGradient(CX - R * 0.15, CY - R * 0.18, 0, CX - R * 0.15, CY - R * 0.18, R * 1.1);
      g.addColorStop(0, 'rgba(191,247,220,0.10)'); g.addColorStop(0.72, 'rgba(61,220,151,0.03)'); g.addColorStop(1, 'rgba(127,240,192,0.28)');
      c.fillStyle = g; c.fill();
      c.lineWidth = 1.2; c.strokeStyle = 'rgba(127,240,192,0.45)'; c.stroke();

      // les points
      const q = [0, 0];
      for (let i = 0; i < N; i++) {
        let tx, ty, lerp = 0.08, lum = 0;
        if (parle && i < NL * 2) { levres(i, NL * 2, amp, 0.15, 1.15, q); tx = q[0]; ty = q[1]; lerp = 0.3; lum = 0.15; }
        else if (tourne) {
          const a = Math.atan2(hy[i], hx[i]) + 0.02 * ps[i] * f60, r = Math.hypot(hx[i], hy[i]);
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
        c.fillStyle = 'rgba(191,247,220,' + alpha.toFixed(3) + ')';
        const taille = ps[i] * 1.45 * Math.max(1, R0 / 150);   // un ecran de PC a moins de points par pouce qu'un telephone
        c.fillRect(px[i], py[i], taille, taille);
      }

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
          c.fillStyle = 'rgba(191,247,220,' + (0.85 * Math.sin(Math.PI * m.vie)).toFixed(3) + ')';
          c.fillText(m.w, m.x, m.y);
        }
      }
    }

    mesurer();
    const observateur = racine.ResizeObserver ? new ResizeObserver(mesurer) : null;
    if (observateur) observateur.observe(canvas); else racine.addEventListener('resize', mesurer);
    image = racine.requestAnimationFrame(dessiner);

    return {
      mode(m) { mode = ['repos', 'ecoute', 'reflechit', 'parle'].includes(m) ? m : 'repos'; return this; },
      etat() { return mode; },
      niveau(f) { micro = typeof f === 'function' ? f : null; return this; },
      mots(liste) { for (const w of (liste || []).slice(0, 6)) enAttente.push(String(w).slice(0, 24)); return this; },
      stop() { arret = true; racine.cancelAnimationFrame(image); if (observateur) observateur.disconnect(); },
    };
  }

  racine.ArchiSphere = ArchiSphere;
})(typeof window !== 'undefined' ? window : globalThis);
