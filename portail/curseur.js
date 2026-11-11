// curseur.js - la souris d'Archi : sur sa page, la fleche blanche devient une etincelle (a) ou un mini-Archi (b).
//
//   a  l'etincelle : un point de lumiere menthe, une trainee courte et quelques braises quand la souris file vite ;
//      sur ce qui se clique, elle s'ouvre en anneau ; un clic lance une onde.
//   b  le mini-Archi : un petit astre, son orbite penchee et sa lune (comme le menu) ; l'orbite se couche dans le sens
//      du mouvement, s'ouvre sur ce qui se clique, et la lune accelere.
//
// Seulement a la souris (jamais au doigt) ; les zones de texte gardent leur curseur de saisie. Le point chaud est le
// centre de la lumiere, sans retard : on clique ou l'on vise. Si quoi que ce soit casse, la fleche normale revient.
//   ArchiCurseur({ style: 'a' })   ->   { style, stop() }   (null sans souris)
'use strict';
(function (racine) {
  const CLIC = 'a[href], button:not([disabled]), [role="menuitem"], .lune, #sphere, summary, label, select';
  const TEXTE = 'textarea, input, [contenteditable="true"]';

  function ArchiCurseur(options) {
    const doc = racine.document, o = options || {};
    if (!racine.matchMedia || !racine.matchMedia('(hover: hover) and (pointer: fine)').matches) return null;
    const style = o.style === 'b' ? 'b' : 'a', calme = racine.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const c = doc.createElement('canvas');
    const g = c.getContext && c.getContext('2d');
    if (!g) return null;
    c.className = 'curseur'; c.setAttribute('aria-hidden', 'true');
    doc.body.appendChild(c);
    doc.documentElement.classList.add('curseur-archi');

    let W = 0, H = 0, dpr = 1;
    function taille() {
      dpr = Math.min(2, racine.devicePixelRatio || 1); W = racine.innerWidth; H = racine.innerHeight;
      c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
    }
    taille();
    racine.addEventListener('resize', taille);

    let x = -100, y = -100, la = false, texte = false, survolCible = 0, survol = 0, vue = 0;
    let vx = 0, vy = 0, penche = 0, lune = 0, image = 0, avant = 0, arret = false;
    const traine = [], braises = [], ondes = [];
    function lancer() { if (!image && !arret) { avant = performance.now(); image = racine.requestAnimationFrame(dessiner); } }

    function bouger(ev) {
      if (ev.pointerType && ev.pointerType !== 'mouse') { la = false; return; }
      x = ev.clientX; y = ev.clientY; la = true;
      const el = ev.target && ev.target.closest ? ev.target : null;
      texte = !!(el && el.closest(TEXTE));
      survolCible = el && el.closest(CLIC) ? 1 : 0;
      traine.push({ x, y, t: performance.now() });
      lancer();
    }
    function appuyer(ev) {
      if (ev.pointerType && ev.pointerType !== 'mouse') return;
      ondes.push({ x: ev.clientX, y: ev.clientY, vie: 0 });
      lancer();
    }
    const partir = () => { la = false; lancer(); };
    racine.addEventListener('pointermove', bouger, { passive: true });
    racine.addEventListener('pointerdown', appuyer, { passive: true });
    doc.documentElement.addEventListener('mouseleave', partir);

    const menthe = 'rgba(61,220,151,', pale = 'rgba(191,247,220,', blanc = 'rgba(239,255,247,';
    function halo(px, py, r, a) {
      const d = g.createRadialGradient(px, py, 0, px, py, r);
      d.addColorStop(0, menthe + a + ')'); d.addColorStop(0.35, menthe + (a * 0.35) + ')'); d.addColorStop(1, menthe + '0)');
      g.fillStyle = d; g.beginPath(); g.arc(px, py, r, 0, Math.PI * 2); g.fill();
    }
    function point(px, py, r, couleur) { g.fillStyle = couleur; g.beginPath(); g.arc(px, py, r, 0, Math.PI * 2); g.fill(); }

    function dessiner(maintenant) {
      image = 0;
      try {
        const dt = Math.min(0.05, (maintenant - avant) / 1000); avant = maintenant;
        // la vitesse, lissee, a partir des derniers points
        while (traine.length && maintenant - traine[0].t > (style === 'a' ? 260 : 140)) traine.shift();
        if (traine.length > 1) {
          const p = traine[traine.length - 1], q = traine[Math.max(0, traine.length - 4)], d = Math.max(0.016, (p.t - q.t) / 1000);
          vx += ((p.x - q.x) / d - vx) * Math.min(1, dt * 12); vy += ((p.y - q.y) / d - vy) * Math.min(1, dt * 12);
        } else { vx *= Math.max(0, 1 - dt * 8); vy *= Math.max(0, 1 - dt * 8); }
        const vitesse = Math.hypot(vx, vy);
        survol += (survolCible - survol) * Math.min(1, dt * 14);
        vue += ((la && !texte ? 1 : 0) - vue) * Math.min(1, dt * 16);

        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        g.clearRect(0, 0, W, H);
        g.globalCompositeOperation = 'lighter';

        // les ondes du clic
        for (let i = ondes.length - 1; i >= 0; i--) {
          const w = ondes[i]; w.vie += dt / 0.5;
          if (w.vie >= 1) { ondes.splice(i, 1); continue; }
          g.strokeStyle = pale + (0.75 * (1 - w.vie)) + ')'; g.lineWidth = 1.3;
          g.beginPath(); g.arc(w.x, w.y, 5 + 26 * Math.sqrt(w.vie), 0, Math.PI * 2); g.stroke();
        }

        if (vue > 0.01) {
          g.globalAlpha = vue;
          // la trainee : une queue de comete qui s'amincit
          if (!calme && traine.length > 1) {
            for (let i = 1; i < traine.length; i++) {
              const a = traine[i - 1], b = traine[i], age = (maintenant - b.t) / (style === 'a' ? 260 : 140), k = Math.max(0, 1 - age);
              g.strokeStyle = menthe + (k * (style === 'a' ? 0.55 : 0.3)) + ')'; g.lineWidth = 0.6 + k * (style === 'a' ? 3 : 2); g.lineCap = 'round';
              g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
            }
          }
          if (style === 'a') dessinerEtincelle(dt, vitesse); else dessinerAstre(dt);
          g.globalAlpha = 1;
        }
        // des braises qui s'envolent quand la souris file vite (etincelle seulement)
        for (let i = braises.length - 1; i >= 0; i--) {
          const e = braises[i]; e.vie += dt / e.duree;
          if (e.vie >= 1) { braises.splice(i, 1); continue; }
          e.x += e.vx * dt; e.y += e.vy * dt; e.vy -= 18 * dt;
          point(e.x, e.y, e.r * (1 - e.vie * 0.6), pale + (0.8 * (1 - e.vie)) + ')');
        }
        g.globalCompositeOperation = 'source-over';
        if (traine.length > 1 || braises.length || ondes.length || Math.abs(survol - survolCible) > 0.01 || Math.abs(vue - (la && !texte ? 1 : 0)) > 0.01
            || (style === 'b' && la) || vitesse > 2) lancer();
      } catch (err) { stop(); }
    }

    function dessinerEtincelle(dt, vitesse) {
      if (!calme && vitesse > 500 && braises.length < 40 && Math.random() < Math.min(0.9, vitesse / 2500)) {
        const a = Math.random() * Math.PI * 2, s = 20 + Math.random() * 40;
        braises.push({ x, y, vx: Math.cos(a) * s - vx * 0.04, vy: Math.sin(a) * s - vy * 0.04, r: 0.8 + Math.random() * 1.1, vie: 0, duree: 0.45 + Math.random() * 0.5 });
      }
      halo(x, y, 15 + 9 * survol, 0.5);
      if (survol > 0.02) {
        // sur ce qui se clique : un anneau qui s'ouvre, et quatre petits traits qui tournent
        const r = 4 + 8 * survol, t = performance.now() / 1000;
        g.strokeStyle = pale + (0.85 * survol) + ')'; g.lineWidth = 1.2;
        g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
        g.strokeStyle = menthe + (0.9 * survol) + ')';
        for (let k = 0; k < 4; k++) {
          const a = t * 1.6 + k * Math.PI / 2;
          g.beginPath(); g.moveTo(x + Math.cos(a) * (r + 2.5), y + Math.sin(a) * (r + 2.5)); g.lineTo(x + Math.cos(a) * (r + 5.5), y + Math.sin(a) * (r + 5.5)); g.stroke();
        }
      }
      point(x, y, 2.6 - 0.8 * survol, blanc + '1)');
    }

    function dessinerAstre(dt) {
      // l'orbite se couche dans le sens du mouvement, la lune tourne plus vite sur ce qui se clique
      penche += (Math.max(-0.7, Math.min(0.7, vx / 900)) - penche) * Math.min(1, dt * 8);
      lune += dt * (2.4 + 5 * survol) * (calme ? 0.3 : 1);
      const rx = 11 + 6 * survol, ry = 4.2 + 2.5 * survol, rot = -0.42 + penche;
      const lx = Math.cos(lune) * rx, ly = Math.sin(lune) * ry, cr = Math.cos(rot), sr = Math.sin(rot);
      const mx = x + lx * cr - ly * sr, my = y + lx * sr + ly * cr, devant = Math.sin(lune) > 0;
      halo(x, y, 13 + 6 * survol, 0.45);
      g.strokeStyle = pale + (0.45 + 0.35 * survol) + ')'; g.lineWidth = 1;
      g.beginPath(); g.ellipse(x, y, rx, ry, rot, 0, Math.PI * 2); g.stroke();
      if (!devant) { halo(mx, my, 5, 0.5); point(mx, my, 1.7, menthe + '1)'); }
      point(x, y, 3, pale + '1)');
      point(x, y, 1.6, blanc + '1)');
      if (devant) { halo(mx, my, 5, 0.6); point(mx, my, 1.8, menthe + '1)'); }
    }

    function stop() {
      arret = true;
      if (image) racine.cancelAnimationFrame(image);
      racine.removeEventListener('pointermove', bouger); racine.removeEventListener('pointerdown', appuyer);
      racine.removeEventListener('resize', taille); doc.documentElement.removeEventListener('mouseleave', partir);
      doc.documentElement.classList.remove('curseur-archi');   // la fleche normale revient
      c.remove();
    }
    return { style, stop };
  }

  racine.ArchiCurseur = ArchiCurseur;
})(typeof window !== 'undefined' ? window : globalThis);
