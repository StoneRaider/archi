// monuments.js - les briques de l'allee et les monuments qu'elles forment (dessines par orbe.js), et le fil des sujets.
//
//   A chaque nouveau sujet, les monolithes de l'allee se defont en briques, se soulevent comme portes par un champ
//   anti-gravite, tournoient et vont former un monument, pres ou au loin ; le lac donne les briques qui manquent.
//   Tant qu'on reste sur le sujet, le monument reste ; un autre sujet en forme un autre. Apres un long silence,
//   les briques reviennent en allee. Les signes graves restent sur les briques pendant tout le voyage.
//
//   Monde : celui du rendu Blender (z en haut, le lac a z = 0, l'allee file vers +y, camera en (0, 0, 1.6)).
//   ArchiMonuments.creerChantier(allee) : les briques (orbe.js les envoie au shader) ;
//   ArchiMonuments.creerFil() : .nouveau(texte) dit si un message ouvre un nouveau sujet.
// Aucune dependance, rien ne vient d'Internet. Les monuments sont evoques en briques, pas copies d'un modele.
'use strict';
(function (racine) {
  const TAU = Math.PI * 2;
  function graine(s) {
    let a = s >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0; let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // une boite : centre, taille, rotation autour de z ; eclat = elle brille toujours (le pyramidion)
  // n : l'orientation de la surface (statues en voxels) : la lumiere suit la forme, pas les faces des cubes
  const B = (x, y, z, sx, sy, sz, rot, eclat, n) => ({ x, y, z, sx, sy, sz, rot: rot || 0, eclat: eclat || 0, n: n || null });
  function placer(liste, cx, cy, ang, ech) {
    ech = ech || 1; const c = Math.cos(ang), s = Math.sin(ang);
    return liste.map(b => B(cx + (b.x * c - b.y * s) * ech, cy + (b.x * s + b.y * c) * ech, b.z * ech,
      b.sx * ech, b.sy * ech, b.sz * ech, b.rot + ang, b.eclat, b.n && [b.n[0] * c - b.n[1] * s, b.n[0] * s + b.n[1] * c, b.n[2]]));
  }
  // la direction de la camera, vue depuis un monument pose en (cx, cy) et tourne de ang (pour ne garder que ce qui se voit)
  function versCamera(cx, cy, ang) {
    const l = Math.hypot(cx, cy) || 1, x = -cx / l, y = -cy / l, c = Math.cos(ang), s = Math.sin(ang);
    return [x * c + y * s, -x * s + y * c, 0];
  }

  // ------------------------------------------------------------------ les formes (distances signees) et les voxels
  const len = (x, y, z) => Math.sqrt(x * x + y * y + z * z);
  function boite(p, c, h) {
    const qx = Math.abs(p[0] - c[0]) - h[0], qy = Math.abs(p[1] - c[1]) - h[1], qz = Math.abs(p[2] - c[2]) - h[2];
    return len(Math.max(qx, 0), Math.max(qy, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qy, qz), 0);
  }
  function ellipsoide(p, c, r) {
    return (len((p[0] - c[0]) / r[0], (p[1] - c[1]) / r[1], (p[2] - c[2]) / r[2]) - 1) * Math.min(r[0], r[1], r[2]);
  }
  function capsule(p, a, b, r) {
    const pa = [p[0] - a[0], p[1] - a[1], p[2] - a[2]], ba = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const h = Math.max(0, Math.min(1, (pa[0] * ba[0] + pa[1] * ba[1] + pa[2] * ba[2]) / (ba[0] * ba[0] + ba[1] * ba[1] + ba[2] * ba[2])));
    return len(pa[0] - ba[0] * h, pa[1] - ba[1] * h, pa[2] - ba[2] * h) - r;
  }
  function cylindre(p, c, r, hz) {
    const d = Math.hypot(p[0] - c[0], p[1] - c[1]) - r, e = Math.abs(p[2] - c[2]) - hz;
    return Math.min(Math.max(d, e), 0) + Math.hypot(Math.max(d, 0), Math.max(e, 0));
  }
  // remplit une forme de cubes ; ne garde que ceux de la surface tournee vers la camera (et le dessus)
  function voxels(f, bornes, pas, vue) {
    const [x0, x1, y0, y1, z0, z1] = bornes;
    const nx = Math.ceil((x1 - x0) / pas), ny = Math.ceil((y1 - y0) / pas), nz = Math.ceil((z1 - z0) / pas);
    const dans = new Uint8Array(nx * ny * nz), id = (i, j, k) => i + nx * (j + ny * k);
    for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++)
      dans[id(i, j, k)] = f([x0 + (i + 0.5) * pas, y0 + (j + 0.5) * pas, z0 + (k + 0.5) * pas]) < 0 ? 1 : 0;
    const vide = (i, j, k) => i < 0 || j < 0 || k < 0 || i >= nx || j >= ny || k >= nz || !dans[id(i, j, k)];
    const dirs = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
    const vues = dirs.map(d => !vue || d[2] > 0 || (d[2] === 0 && d[0] * vue[0] + d[1] * vue[1] > -0.35));
    const out = [];
    for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      if (!dans[id(i, j, k)]) continue;
      if (!dirs.some((d, n) => vues[n] && vide(i + d[0], j + d[1], k + d[2]))) continue;
      const x = x0 + (i + 0.5) * pas, y = y0 + (j + 0.5) * pas, z = z0 + (k + 0.5) * pas, e = pas * 0.6;
      const g = [f([x + e, y, z]) - f([x - e, y, z]), f([x, y + e, z]) - f([x, y - e, z]), f([x, y, z + e]) - f([x, y, z - e])], l = Math.hypot(...g) || 1;
      out.push(B(x, y, z, pas, pas, pas, 0, 0, g.map(v => v / l)));
    }
    return out;
  }
  function voxelsAuPlus(f, bornes, max, pas, vue) {
    for (let n = 0; n < 40; n++, pas *= 1.06) { const v = voxels(f, bornes, pas, vue); if (v.length <= max) return v; }
    return [];
  }
  // une pyramide a degres : des anneaux de blocs, chaque assise en retrait d'un demi-bloc (les joints se croisent)
  function anneaux(L, b, hc, sommetBrille) {
    const out = [];
    for (let k = 0; k < L; k++) {
      const n = L - k, d = (n - 1) * b / 2, z = hc * (k + 0.5);
      if (n === 1) { out.push(B(0, 0, z, b, b, hc, 0, sommetBrille ? 1 : 0)); break; }
      for (let i = 0; i < n; i++) {
        const t = -d + i * b;
        out.push(B(t, -d, z, b, b, hc), B(t, d, z, b, b, hc));
        if (i > 0 && i < n - 1) out.push(B(-d, t, z, b, b, hc), B(d, t, z, b, b, hc));
      }
    }
    return out;
  }

  // ------------------------------------------------------------------ les monuments
  // la grande pyramide de Gizeh, de trois quarts, au loin ; son sommet brille
  function pyramide() { return placer(anneaux(19, 1.9, 1.2, true), 17, 82, 0.62); }

  // le sphinx, de trois quarts, la tete vers nous ; deux pyramides derriere lui
  function sphinx() {
    const f = p => Math.min(
      boite(p, [-0.6, 0, 2.0], [6.4, 2.2, 1.9]) - 0.3,             // le corps couche
      ellipsoide(p, [-5.8, 0, 2.3], [2.4, 2.6, 2.3]),              // l'arriere-train
      boite(p, [9.0, -1.45, 0.55], [3.1, 0.7, 0.55]),              // les pattes avant
      boite(p, [9.0, 1.45, 0.55], [3.1, 0.7, 0.55]),
      boite(p, [5.5, 0, 3.3], [1.6, 2.1, 3.0]) - 0.2,              // le poitrail
      boite(p, [6.3, 0, 7.6], [1.25, 1.1, 1.5]),                   // la tete
      boite(p, [5.6, 0, 6.5], [0.8, 1.95, 1.7]),                   // les pans du nemes
      boite(p, [5.9, 0, 9.0], [1.35, 1.3, 0.4]),                   // le dessus de la coiffe
      boite(p, [7.65, 0, 7.4], [0.25, 0.3, 0.45]));                // le nez
    const cx = -17, cy = 52, ang = -0.35;                         // de profil, la tete vers le centre
    const corps = placer(voxelsAuPlus(f, [-8.6, 12.4, -3, 3, 0, 9.6], 1080, 0.5, versCamera(cx, cy, ang)), cx, cy, ang);
    return corps.concat(placer(anneaux(12, 2.4, 1.5), 18, 104, 0.7), placer(anneaux(9, 2.4, 1.5), 36, 122, 0.7));
  }

  // Sacsayhuaman : trois murs en zigzag, en terrasses, de pierres enormes et inegales
  function sacsayhuaman() {
    const r = graine(7), out = [];
    const zig = x => { const ph = ((x / 8) % 1 + 1) % 1; return 2.4 * (1 - Math.abs(ph * 2 - 1)); };
    for (let k = 0; k < 3; k++) {
      const yb = k * 4.6, z0 = k * 3.0, haut = z0 + 3.6, demi = 28 - k * 3;
      let x = -demi + r() * 2;
      while (x < demi) {
        const w = 1.3 + r() * 2.6, y1 = zig(x), y2 = zig(x + w), rot = Math.atan2(y2 - y1, w), L = Math.hypot(w, y2 - y1);
        let z = k === 0 ? -0.6 : z0 - 0.5;
        while (z < haut - 0.25) {
          const h = Math.min(haut - z, 0.9 + r() * (k === 0 ? 2.8 : 1.9));
          out.push(B(x + w / 2, yb + (y1 + y2) / 2, z + h / 2, L - 0.07, 1.5 + r() * 0.5, h - 0.06, rot));
          z += h;
        }
        x += w;
      }
    }
    return placer(out, 0, 50, 0);
  }

  // la statue de Zeus a Olympie (perdue : evoquee) : assis sur son trone, le sceptre leve, la Victoire dans la main
  function zeus() {
    const f = p => Math.min(
      boite(p, [0, 1.5, 1.5], [7, 6.5, 1.5]),                                  // le socle
      boite(p, [0, 1.5, 4.6], [5.2, 4, 1.6]),                                  // l'assise
      boite(p, [-4.6, 5.0, 11], [0.6, 0.6, 5]), boite(p, [4.6, 5.0, 11], [0.6, 0.6, 5]),     // les montants du trone (pas de dossier plein : la silhouette se lit)
      boite(p, [0, 5.0, 7.2], [5.2, 0.5, 1.0]),
      boite(p, [-5.0, 1.0, 7.2], [0.5, 3.2, 0.6]), boite(p, [5.0, 1.0, 7.2], [0.5, 3.2, 0.6]),   // les accoudoirs
      capsule(p, [-1.7, 2.0, 7.0], [-1.7, -3.4, 7.0], 1.35), capsule(p, [1.7, 2.0, 7.0], [1.7, -3.4, 7.0], 1.35),
      capsule(p, [-1.7, -3.6, 6.8], [-1.8, -4.3, 3.4], 1.1), capsule(p, [1.7, -3.6, 6.8], [1.8, -4.3, 3.4], 1.1),
      boite(p, [0, -0.7, 6.9], [3.3, 3.0, 1.0]), boite(p, [0, -4.1, 5.0], [2.9, 0.7, 1.8]),       // le drape
      ellipsoide(p, [0, 1.5, 10.8], [3.1, 2.0, 3.7]),                          // le torse
      capsule(p, [-3.1, 1.5, 13.3], [3.1, 1.5, 13.3], 1.25), capsule(p, [0, 1.3, 13.5], [0, 1.1, 14.6], 0.8),
      ellipsoide(p, [0, 0.9, 15.7], [1.35, 1.45, 1.6]), ellipsoide(p, [0, 0.2, 14.4], [1.15, 0.9, 1.4]),   // tete et barbe
      ellipsoide(p, [0, 1.4, 16.4], [1.6, 1.6, 1.1]),
      capsule(p, [-3.4, 1.5, 13.0], [-3.9, 0.6, 9.8], 0.95), capsule(p, [-3.9, 0.6, 9.8], [-3.6, -3.4, 9.4], 0.8),
      capsule(p, [-3.6, -4.0, 9.6], [-3.6, -4.0, 11.6], 0.5), boite(p, [-3.6, -3.7, 11.2], [1.0, 0.15, 0.5]),   // la Victoire
      capsule(p, [3.4, 1.5, 13.0], [5.0, 0.6, 15.6], 0.95), capsule(p, [5.0, 0.6, 15.6], [5.4, -0.3, 17.6], 0.8),
      capsule(p, [5.6, -0.5, 3.2], [5.6, -0.5, 22.5], 0.38), ellipsoide(p, [5.6, -0.5, 23.2], [0.9, 0.6, 0.7]));   // sceptre et aigle
    const cx = 14, cy = 60, ang = -0.3;
    return placer(voxelsAuPlus(f, [-7.5, 7.5, -6, 8, 0, 24.2], 1350, 0.48, versCamera(cx, cy, ang)), cx, cy, ang);
  }

  // la Grande Muraille : elle arrive de la gauche, serpente sur des cretes et file au loin, avec ses tours de guet
  function muraille() {
    const P = [[-21, 22], [-9, 38], [6, 50], [16, 68], [6, 90], [-10, 110], [-2, 138], [16, 164]];   // elle file en biais vers le fond
    const dense = [];
    for (let i = 0; i < P.length - 1; i++) {
      const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(P.length - 1, i + 2)];
      for (let k = 0; k < 40; k++) {
        const t = k / 40, t2 = t * t, t3 = t2 * t;
        dense.push([0, 1].map(c => 0.5 * (2 * p1[c] + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t2 + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t3)));
      }
    }
    dense.push(P[P.length - 1]);
    const out = [], seg = 1.5, colline = s => 2.2 * Math.max(0, Math.sin(s * 0.04 + 0.4)) + 0.8 * Math.pow(Math.sin(s * 0.08 + 1.0), 2);
    let s = 0, acc = 0, i = 0;
    for (let k = 1; k < dense.length; k++) {
      const a = dense[k - 1], b = dense[k], d = Math.hypot(b[0] - a[0], b[1] - a[1]);
      acc += d; s += d;
      if (acc < seg) continue;
      acc = 0; i++;
      const ang = Math.atan2(b[1] - a[1], b[0] - a[0]), h = colline(s), x = b[0], y = b[1], nx = -Math.sin(ang), ny = Math.cos(ang);
      out.push(B(x, y, (h + 1.5) / 2, seg + 0.05, 2.0, h + 1.5, ang), B(x, y, h + 2.0, seg + 0.05, 2.0, 1.0, ang));   // le mur epouse la crete
      if (i % 2 === 0) for (const c of [-0.8, 0.8]) out.push(B(x + nx * c, y + ny * c, h + 2.85, seg * 0.55, 0.4, 0.7, ang));
      if (i % 16 === 8) {                                                                 // une tour de guet
        out.push(B(x, y, h + 2.4, 3.6, 3.6, 4.8, ang));
        for (const [u, v] of [[-1, -1], [1, -1], [-1, 1], [1, 1]])
          out.push(B(x + (u * Math.cos(ang) - v * Math.sin(ang)) * 1.4, y + (u * Math.sin(ang) + v * Math.cos(ang)) * 1.4, h + 5.2, 0.9, 0.9, 0.8, ang));
      }
    }
    return out;
  }

  // le Pantheon de Rome, de trois quarts : le portique, le fronton, l'avant-corps, la rotonde et sa coupole
  function pantheon() {
    const out = [];
    for (let x = -16.9; x <= 17; x += 2.6) out.push(B(x, 2.2, 0.5, 2.6, 5.6, 1.0));
    const colonne = (x, y) => {
      out.push(B(x, y, 1.25, 1.9, 1.9, 0.5));
      for (let k = 0; k < 11; k++) out.push(B(x, y, 2.0 + k, 1.35, 1.35, 1.0, (k % 2) * Math.PI / 4));
      out.push(B(x, y, 12.8, 2.1, 2.1, 0.6));
    };
    for (let i = 0; i < 8; i++) colonne(-14.7 + i * 4.2, 0);
    for (const i of [0, 2, 5, 7]) colonne(-14.7 + i * 4.2, 4.6);
    for (let x = -16.8; x <= 16.9; x += 2.4) out.push(B(x, 0, 14.0, 2.4, 2.2, 1.8), B(x, 4.6, 14.0, 2.4, 2.2, 1.8));
    for (let k = 0; k < 6; k++) {
      const w = 17.4 * (1 - (k + 0.5) / 6.2);
      for (let x = -w; x <= w + 0.01; x += 2.4) out.push(B(x, 0.4, 15.35 + k * 0.9, 2.4, 1.6, 0.9));
    }
    for (let z = 1.1; z < 22; z += 2.2) for (let x = -12.4; x <= 12.5; x += 2.6) out.push(B(x, 9.5, z, 2.6, 2.0, 2.2));
    const cy = 31, R = 21;
    const anneau = (r, z, h) => {
      const n = Math.max(6, Math.round(TAU * r / 2.6));
      for (let i = 0; i < n; i++) {
        const th = i / n * TAU;
        if (Math.cos(th) < -0.15) continue;                                           // le dos ne se voit pas
        out.push(B(Math.sin(th) * r, cy - Math.cos(th) * r, z, Math.min(2.6, TAU * r / n + 0.05), 2.0, h, th));
      }
    };
    for (let z = 1.1; z < 22; z += 2.2) anneau(R, z, 2.2);
    for (let k = 0; k < 12; k++) { const ph = k * 7 * Math.PI / 180; anneau(R * Math.cos(ph) - 0.6, 22 + R * 0.92 * Math.sin(ph), 2.2); }
    return placer(out, -19, 70, 0.42, 0.55);
  }

  // Stonehenge : le cercle de pierres levees et ses linteaux, le fer a cheval des trilithes, en ruine
  function stonehenge() {
    const r = graine(11), out = [], R = 13, n = 30, debout = [];
    for (let i = 0; i < n; i++) {
      const th = i / n * TAU, x = Math.sin(th) * R, y = -Math.cos(th) * R, ok = r() > 0.28;
      debout.push(ok);
      if (ok) out.push(B(x, y, 1.25, 2.2, 1.2, 2.5, th), B(x, y, 3.75, 2.2, 1.2, 2.5, th));
      else if (r() < 0.6) out.push(B(x * 1.08, y * 1.08, 0.5, 4.6, 2.2, 1.1, th + 0.4 + r()));   // tombee
    }
    for (let i = 0; i < n; i++) {
      if (!debout[i] || !debout[(i + 1) % n] || r() < 0.15) continue;
      const th = (i + 0.5) / n * TAU, rr = R * Math.cos(Math.PI / n);
      out.push(B(Math.sin(th) * rr, -Math.cos(th) * rr, 5.45, 2 * R * Math.sin(Math.PI / n) + 0.6, 1.2, 0.9, th));
    }
    [[-100, 6.2], [-50, 7.0], [0, 8.0], [50, 7.0], [100, 6.2]].forEach(([deg, H], j) => {
      const th = deg * Math.PI / 180, cx = Math.sin(th) * 7.5, cy = Math.cos(th) * 7.5, tx = Math.cos(th), ty = -Math.sin(th);
      for (const c of [-1.5, 1.5]) for (let k = 0; k < 3; k++) out.push(B(cx + tx * c, cy + ty * c, (k + 0.5) * H / 3, 2.2, 1.4, H / 3, -th));
      if (j === 3) out.push(B(cx - 2, cy - 3, 0.55, 5.2, 1.4, 1.1, -th + 0.7));            // un linteau tombe
      else out.push(B(cx, cy, H + 0.55, 5.4, 1.4, 1.1, -th, j === 2 ? 1 : 0));
    });
    out.push(B(0, 1.5, 0.3, 4.8, 1.0, 0.6, 0.1));                                         // la pierre d'autel
    return placer(out, 0, 46, 0);
  }

  // Chichen Itza : la pyramide a neuf terrasses, deux escaliers et le temple au sommet
  function chichenItza() {
    const out = [];
    for (let k = 0; k < 9; k++) {
      const n = 26 - 2 * k, d = (n - 1), z = 2 * k + 1;
      for (let i = 0; i < n; i++) {
        const t = -d + i * 2;
        out.push(B(t, -d, z, 2, 2, 2), B(t, d, z, 2, 2, 2));
        if (i > 0 && i < n - 1) out.push(B(-d, t, z, 2, 2, 2), B(d, t, z, 2, 2, 2));
      }
    }
    for (let j = 0; j < 18; j++) {
      const f = -26.5 + j, z = j + 0.5;
      for (const x of [-3, -1, 1, 3]) out.push(B(x, f, z, 2, 1, 1), B(f, x, z, 1, 2, 1));
      for (const x of [-4.6, 4.6]) out.push(B(x, f, z + 0.4, 1.2, 1, 1.8), B(f, x, z + 0.4, 1, 1.2, 1.8));
    }
    for (let c = 0; c < 3; c++) for (let i = 0; i < 5; i++) {
      const t = -4 + i * 2, z = 18.8 + c * 1.6;
      if (!(c < 2 && i === 2)) out.push(B(t, -4, z, 2, 2, 1.6, 0, c === 1 && i === 2 ? 1 : 0));
      out.push(B(t, 4, z, 2, 2, 1.6));
      if (i > 0 && i < 4) out.push(B(-4, t, z, 2, 2, 1.6), B(4, t, z, 2, 2, 1.6));
    }
    for (let x = -4; x <= 4; x += 2) out.push(B(x, 0, 23.4, 2, 10, 0.8));
    return placer(out, -14, 74, 0.6, 0.85);
  }

  // les moai d'Ahu Tongariki : une rangee de geants sur leur plate-forme, face a nous (un vide au centre : l'orbe)
  function moai() {
    const sous = (a, b) => Math.max(a, -b);
    const f = p => {
      let d = Math.min(
        boite(p, [0, 0.1, 2.0], [1.45, 0.85, 2.0]) - 0.3,                      // le corps, aux epaules arrondies
        boite(p, [0, -0.05, 4.45], [1.15, 0.8, 0.55]) - 0.15,                  // la machoire
        boite(p, [0, 0.15, 6.3], [1.1, 0.85, 1.85]) - 0.25,                    // la longue tete au sommet plat
        boite(p, [0, -0.82, 6.95], [1.12, 0.22, 0.28]) - 0.05,                 // l'arcade lourde
        boite(p, [0, -1.0, 6.0], [0.26, 0.3, 0.8]),                            // le long nez
        boite(p, [0, -1.08, 5.3], [0.48, 0.24, 0.17]),                         // ses narines evasees
        boite(p, [0, -0.92, 4.95], [0.62, 0.18, 0.1]),                         // les levres pincees
        boite(p, [0, -0.88, 4.42], [0.82, 0.24, 0.3]) - 0.08,                  // le menton
        boite(p, [-1.2, 0.25, 5.9], [0.12, 0.28, 1.15]), boite(p, [1.2, 0.25, 5.9], [0.12, 0.28, 1.15]),   // les longues oreilles
        boite(p, [-1.55, -0.1, 2.3], [0.12, 0.6, 1.5]), boite(p, [1.55, -0.1, 2.3], [0.12, 0.6, 1.5]),     // les bras
        boite(p, [0, -0.98, 1.0], [1.05, 0.12, 0.22]));                        // les mains sur le ventre
      d = sous(d, boite(p, [-0.5, -1.0, 6.55], [0.32, 0.22, 0.2]));           // les orbites, sous l'arcade
      d = sous(d, boite(p, [0.5, -1.0, 6.55], [0.32, 0.22, 0.2]));
      return d;
    };
    const g = p => Math.min(f(p), cylindre(p, [0, 0.2, 8.55], 1.0, 0.45));   // le pukao, la coiffe de pierre rouge
    const un = voxelsAuPlus(f, [-1.9, 1.9, -1.4, 1.2, 0, 8.3], 225, 0.3, [0, -1, 0]);
    const coiffe = voxelsAuPlus(g, [-1.9, 1.9, -1.4, 1.2, 0, 9.1], 235, 0.3, [0, -1, 0]);
    const out = [], places = [[-18.5, 0.96], [-12.5, 1.06], [-6.5, 1.0], [6.5, 1.1], [12.5, 0.94], [18.5, 1.02]];
    places.forEach(([x, h], i) => {
      out.push(B(x, 0.6, 0.6, 5.2, 3.2, 1.2));
      for (const b of placer(i === 1 || i === 4 ? coiffe : un, 0, 0, -x * 0.006, 1.15 * h))
        out.push(B(b.x + x, b.y + 0.6, b.z + 1.2, b.sx, b.sy, b.sz, b.rot, 0, b.n));
    });
    return placer(out, 0, 50, 0);
  }

  // le Colisee : l'anneau des arcades sur trois etages et l'attique, avec son flanc en ruine
  function colisee() {
    const out = [], a = 25, b = 20.5, n = 64, hT = 4.2, r = graine(5);
    const pt = th => [a * Math.sin(th), -b * Math.cos(th)], rotA = th => Math.atan2(b * Math.sin(th), a * Math.cos(th));
    for (let i = 0; i < n; i++) {
      const th = i / n * TAU, tm = (i + 0.5) / n * TAU, [x, y] = pt(th), [xm, ym] = pt(tm);
      const w = Math.hypot(...pt((i + 1) / n * TAU).map((v, c) => v - [x, y][c]));
      const s = Math.sin(th), nt = s >= -0.25 ? 4 : s < -0.7 ? 2 + (r() < 0.4 ? 1 : 0) : 3;
      for (let t = 0; t < Math.min(nt, 3); t++) {
        out.push(B(x, y, t * hT + hT / 2, 0.8, 1.8, hT, rotA(th)));
        out.push(B(xm, ym, t * hT + hT - 0.45, w - 0.8, 1.8, 0.9, rotA(tm)));
      }
      if (nt === 4) out.push(B(xm, ym, 3 * hT + 1.6, w + 0.05, 1.8, 3.2, rotA(tm)));
    }
    return placer(out, 0, 64, 0.15);
  }

  const MONUMENTS = { pyramide, sphinx, sacsayhuaman, zeus, muraille, pantheon, stonehenge, chichen_itza: chichenItza, moai, colisee };
  const NOMS = Object.keys(MONUMENTS);
  const fait = {};

  // ------------------------------------------------------------------ les monuments modelises dans Blender (decor/monuments.bin)
  // Chaque pierre : centre, angle, demi-taille, et sa forme : un rayon (0..1) pour chaque point d'une grille posee sur un cube
  // (6 faces de ng x ng carreaux). A l'arrivee, la brique pousse chaque point a son rayon : elle devient la pierre.
  // Format : « ARM1 », nombre de monuments ; puis par monument : nom (16 octets), N, ng, N x 8 flottants, N x K octets.
  const FORMES = {};
  function lireFormes(buf) {
    const dv = new DataView(buf), u8 = new Uint8Array(buf);
    if (String.fromCharCode(u8[0], u8[1], u8[2], u8[3]) !== 'ARM1') return 0;
    let o = 4, n = 0;
    const M = dv.getUint32(o, true); o += 4;
    for (let m = 0; m < M; m++) {
      let nom = ''; for (let i = 0; i < 16 && u8[o + i]; i++) nom += String.fromCharCode(u8[o + i]);
      o += 16;
      const N = dv.getUint32(o, true), ng = dv.getUint32(o + 4, true), K = 6 * (ng + 1) * (ng + 1); o += 8;
      const liste = [];
      for (let i = 0; i < N; i++, o += 32) {
        const f = k => dv.getFloat32(o + 4 * k, true);
        const e = f(7);      // le ton de la pierre (0..1), + 2 si elle brille
        liste.push({ x: f(0), y: f(1), z: f(2), rot: f(3), sx: 2 * f(4), sy: 2 * f(5), sz: 2 * f(6), eclat: e >= 2 ? 1 : 0, ton: e >= 2 ? e - 2 : e, n: null, forme: i });
      }
      liste.formes = { ng, K, N, r: u8.slice(o, o + N * K) };
      o += N * K;
      if (MONUMENTS[nom]) { FORMES[nom] = liste; n++; }
    }
    return n;
  }
  function chargerFormes(url) {
    if (typeof racine.fetch !== 'function' || !racine.location) return;
    racine.fetch(url).then(r => r.ok ? r.arrayBuffer() : null).then(b => { if (b) lireFormes(b); }).catch(() => {});
  }
  function monument(nom) {
    if (FORMES[nom]) return FORMES[nom];
    if (!fait[nom]) fait[nom] = MONUMENTS[nom]();
    return fait[nom];
  }
  // calcules a l'avance, un par un, quand la page n'a rien a faire : au depart d'un vol, tout est pret (pas d'a-coup)
  function preparer() {
    const reste = NOMS.filter(n => !fait[n]);
    if (!reste.length || typeof racine.setTimeout !== 'function') return;
    const suite = () => { monument(reste.shift()); if (reste.length) attendre(); };
    const attendre = () => racine.requestIdleCallback ? racine.requestIdleCallback(suite, { timeout: 4000 }) : racine.setTimeout(suite, 300);
    racine.setTimeout(attendre, 2500);
  }

  // ------------------------------------------------------------------ les quaternions (x, y, z, w)
  const qz = a => [0, 0, Math.sin(a / 2), Math.cos(a / 2)];
  const qaxe = (v, a) => { const s = Math.sin(a / 2); return [v[0] * s, v[1] * s, v[2] * s, Math.cos(a / 2)]; };
  const qmul = (a, b) => [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1], a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
    a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3], a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]];
  function slerp(a, b, t) {
    let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3], c = b;
    if (d < 0) { d = -d; c = b.map(v => -v); }
    if (d > 0.9995) { const r = a.map((v, i) => v + (c[i] - v) * t), l = Math.hypot(...r); return r.map(v => v / l); }
    const th = Math.acos(d), s = Math.sin(th), k0 = Math.sin((1 - t) * th) / s, k1 = Math.sin(t * th) / s;
    return a.map((v, i) => v * k0 + c[i] * k1);
  }
  const lisse = x => x * x * (3 - 2 * x);
  const lisse2 = x => x * x * x * (x * (x * 6 - 15) + 10);

  // ------------------------------------------------------------------ le chantier : les briques et leurs voyages
  // allee : ce que rend creerAllee (orbe.js) : les monolithes M (x, y, h, h0, rot, l, p, lueur) et le linteau.
  function creerChantier(allee, options) {
    const o = Object.assign({ total: 1800, alea: Math.random, retourAllee: 15 * 60 }, options || {});
    const alea = o.alea, M = allee.M;
    const br = [];
    M.forEach((m, mi) => {
      const nz = Math.max(3, Math.round((m.h0 + 1.2) / 0.45));
      for (let ix = 0; ix < 2; ix++) for (let iz = 0; iz < nz; iz++) br.push({ m: mi, ix, iz, nz, signes: 1, graine: mi });
    });
    while (br.length < o.total) {
      const k = br.length, ra = Math.floor(alea() * 30);
      br.push({ m: -1, rx: -30 + alea() * 60, ry: 16 + alea() * 100, signes: alea() < 0.3 ? 1 : 0, graine: 20 + (k % 97), ra });
    }
    for (const b of br) Object.assign(b, { p: [0, 0, 0], q: [0, 0, 0, 1], s: [1, 1, 1], gly: [0, 1, 0, 1], rmax: 99, lueur: 0, det: 0,
      brume: 1, eclat: 0, n: [0, 0, 1], nw: 0, vol: null, place: null, allumee: false, retard: 0, rang: 0, rang_f: 0, g: 0, ton: 0.5 });
    preparer();
    if (o.formes !== false) chargerFormes(o.formes || '/decor/monuments.bin');
    const N = br.length, F = 28, donnees = new Float32Array((N + 1) * F);
    // les formes des pierres vont dans une texture a deux etages : le monument qui se defait garde le sien pendant que le suivant arrive
    let couche = 0, aEnvoyer = null, ngActif = 0;
    let etat = 'allee', tau = 0, nom = null, pioche = [], t = 0, calme = 0, pensait = false, depuis = 0, versAllee = false;

    // la place d'une brique dans son monolithe (ou sous le lac pour les briques de reserve)
    function maison(b, out) {
      if (b.m < 0) { out.p = [b.rx, b.ry, -6]; out.q = [0, 0, 0, 1]; out.s = [0.7, 0.6, 0.6]; out.gly = [0, 1, b.ra, b.ra + 1.2]; out.rmax = 999; return out; }
      const m = M[b.m], H = m.h + 1.2, dz = H / b.nz, z = -1.2 + (b.iz + 0.5) * dz, lx = (b.ix - 0.5) * m.l / 2;
      out.p = [m.x + lx * Math.cos(m.rot), m.y + lx * Math.sin(m.rot), z]; out.q = qz(m.rot); out.s = [m.l / 2, m.p, dz];
      const pas = m.l * 0.62 * 1.08;
      out.gly = [b.ix / 2, (b.ix + 1) / 2, (z - dz / 2 - 0.55) / pas, (z + dz / 2 - 0.55) / pas]; out.rmax = (m.h - 0.85) / pas;
      return out;
    }
    const enAllee = () => { for (const b of br) { const h = maison(b, {}); b.p = h.p; b.q = h.q; b.s = h.s; b.gly = h.gly; b.rmax = h.rmax; } };
    enAllee();

    function prochain() {
      if (!pioche.length) {
        pioche = NOMS.slice();
        for (let i = pioche.length - 1; i > 0; i--) { const j = Math.floor(alea() * (i + 1)); [pioche[i], pioche[j]] = [pioche[j], pioche[i]]; }
        if (pioche[pioche.length - 1] === nom) pioche.unshift(pioche.pop());
      }
      return pioche.pop();
    }
    const visible = b => b.p[2] + b.s[2] / 2 > 0.02;
    const melanger = l => { for (let i = l.length - 1; i > 0; i--) { const j = Math.floor(alea() * (i + 1)); [l[i], l[j]] = [l[j], l[i]]; } return l; };

    // un voyage : chaque brique part d'ou elle est (S) vers sa place (E)
    function partir(cibles) {
      if (allee.congedier) allee.congedier();
      versAllee = !cibles; tau = 0; etat = 'vol'; calme = 0;
      const vus = melanger(br.filter(visible)), caches = melanger(br.filter(b => !visible(b)));
      for (const b of br) { b.vol = null; b.place = null; }
      let paires = [];
      if (versAllee) {
        for (const b of br) { const h = maison(b, {}); if (visible(b) || h.p[2] + h.s[2] / 2 > 0) paires.push([b, { p: h.p, q: h.q, s: h.s, eclat: 0 }, h.p[2] / 10]); }
      } else {
        const fo = cibles.formes;
        if (fo) { couche = 1 - couche; aEnvoyer = { couche, ng: fo.ng, K: fo.K, N: Math.min(fo.N, N), r: fo.r }; ngActif = fo.ng; }
        const T = cibles.slice(0, N).map(c => ({ p: [c.x, c.y, c.z], q: qz(c.rot), s: [c.sx, c.sy, c.sz], eclat: c.eclat, n: c.n,
          rangF: fo ? couche * N + c.forme : 0, morph: fo ? 1 : 0, ton: c.ton === undefined ? 0.5 : c.ton }));
        const zs = T.map(c => c.p[2] - c.s[2] / 2), zmin = Math.min(...zs), zmax = Math.max(...zs, zmin + 1);
        const ordre = melanger(T.map((c, i) => i));
        const qui = vus.concat(caches);
        ordre.forEach((ti, k) => paires.push([qui[k], T[ti], (zs[ti] - zmin) / (zmax - zmin)]));
        for (const b of qui.slice(ordre.length)) if (visible(b)) paires.push([b, { p: [b.p[0], b.p[1], -6], q: b.q, s: b.s, eclat: 0 }, 0]);
      }
      const sens = alea() < 0.5 ? -1 : 1;
      for (const [b, E, rang] of paires) {
        const ici = visible(b), d0 = ici ? alea() * 1.5 : 0.7 + alea() * 2.5, L = ici ? 1.2 + alea() * 0.8 : 1.9 + alea() * 0.9;
        const arrivee = 5.4 + 7.6 * rang + alea() * 0.9, axe = (() => { const v = [alea() - 0.5, alea() - 0.5, alea() - 0.5], l = Math.hypot(...v) || 1; return v.map(x => x / l); })();
        b.vol = { S: { p: b.p.slice(), q: b.q.slice(), s: b.s.slice(), nw: b.nw, g: b.g, rangF: b.rang_f, ton: b.ton }, E, d0, L, F: Math.max(2.6, arrivee - d0 - L),
          lift: ici ? 1.2 + alea() * 3.2 : 7 + alea() * 3, dx: (alea() - 0.5) * 1.2, dy: (alea() - 0.5) * 1.2, wob: 0.15 + alea() * 0.35,
          axe, axe2: axe.slice().reverse(), k: 1 + Math.floor(alea() * 2), tours: (0.8 + alea() * 1.2) * sens, th0: alea() * TAU, rs: 1.5 + alea() * 3.5,
          arc: 2 + alea() * 7, brumeS: b.brume, brumeE: versAllee ? 1 : 0.42, rang };
        b.place = E; b.rang = rang;
      }
    }
    function trajet(b, f, u) {
      const S = f.S, E = f.E;
      if (u <= 0) return;
      if (u < f.L) {
        const e = lisse(u / f.L);
        b.p = [S.p[0] + f.dx * e, S.p[1] + f.dy * e, S.p[2] + f.lift * e];
        b.q = qmul(S.q, qaxe(f.axe, f.wob * e)); b.s = S.s.slice();
        b.det = e; b.nw = S.nw * (1 - e); b.g = S.g * (1 - e); b.rang_f = S.rangF; b.ton = S.ton; return;
      }
      // chaque brique file de sa place a sa place en tournoyant en spirale autour de son chemin : elle ne passe jamais
      // devant la camera (l'orbe est a 10 m) ; elle ne prend sa taille finale qu'en arrivant
      const s = Math.min(1, (u - f.L) / f.F), e = lisse2(s);
      const P1 = [S.p[0] + f.dx, S.p[1] + f.dy, S.p[2] + f.lift];
      const R = f.rs * Math.sin(Math.PI * e), th = f.th0 + f.tours * TAU * e;
      b.p = [P1[0] + (E.p[0] - P1[0]) * e + R * Math.cos(th), Math.max(13, P1[1] + (E.p[1] - P1[1]) * e + R * Math.sin(th)),
        P1[2] + (E.p[2] - P1[2]) * e + f.arc * Math.sin(Math.PI * e)];
      b.q = qmul(slerp(qmul(S.q, qaxe(f.axe, f.wob)), E.q, e), qaxe(f.axe2, TAU * f.k * e));
      const g = lisse(Math.max(0, Math.min(1, (s - 0.45) / 0.55)));
      b.s = [0, 1, 2].map(i => S.s[i] + (E.s[i] - S.s[i]) * g);
      b.brume = f.brumeS + (f.brumeE - f.brumeS) * e;
      if (E.n) { b.n = E.n; b.nw = e; } else b.nw = 0;
      // la toute fin : la brique perd sa forme de cube et prend celle de sa pierre
      b.rang_f = E.rangF || 0; b.ton = E.ton === undefined ? 0.5 : E.ton; b.g = E.morph ? lisse(Math.max(0, Math.min(1, (s - 0.72) / 0.28))) : 0;
      b.det = 1 - s * s * (versAllee ? 1 : 0.85);
    }

    function avancer(dt, pense) {
      t += dt;
      allee.avancer(dt, pense, etat !== 'allee');
      const p1 = pense > 0.5;
      if (etat === 'allee') {
        enAllee();
        for (const b of br) { b.lueur = b.m >= 0 ? M[b.m].lueur : 0; b.det = 0; b.brume = 1; b.eclat = 0; b.nw = 0; b.g = 0; }
      } else if (etat === 'vol') {
        tau += dt;
        let fini = true;
        for (const b of br) {
          const f = b.vol; if (!f) { b.lueur = Math.max(0, b.lueur - dt / 3); continue; }
          const u = tau - f.d0; trajet(b, f, u);
          const total = f.L + f.F, k = Math.max(0, Math.min(1, u / total));
          b.lueur = Math.max(b.lueur - dt / 2.5, u > 0 && k < 1 ? 0.9 * Math.sin(Math.PI * Math.min(1, k * 1.4)) : 0);
          if (u < total) fini = false;
        }
        if (fini) {
          etat = versAllee ? 'allee' : 'monument'; depuis = 0; pensait = false;
          for (const b of br) {
            const f = b.vol; if (!f) continue;
            b.p = f.E.p.slice(); b.q = f.E.q.slice(); b.s = f.E.s.slice(); b.eclat = f.E.eclat || 0; b.nw = f.E.n ? 1 : 0;
            b.g = f.E.morph ? 1 : 0; b.rang_f = f.E.rangF || 0;
            b.det = versAllee ? 0 : 0.15; b.brume = f.brumeE; b.vol = null;
          }
        }
      } else {
        // le monument tient ; quand Archi reflechit, ses signes s'allument en vague, du pied au sommet
        if (p1 && !pensait) { depuis = 0; for (const b of br) { b.allumee = alea() < 0.5; b.retard = b.rang * 2.4 + alea() * 0.6; } }
        pensait = p1; depuis += dt;
        for (const b of br) b.lueur = b.eclat ? 1 : p1 && b.allumee && depuis > b.retard ? Math.min(1, b.lueur + dt / 1.2) : Math.max(0, b.lueur - dt / 5);
        calme = p1 ? 0 : calme + dt;
        if (calme > o.retourAllee) { nom = null; partir(null); }
      }
    }

    // pour le shader : par brique, 7 vec4 = (centre, lueur) (quaternion) (taille, brume) (signes : u0 u1 rang0 rang1)
    // (graine, rang max, a des signes, detachee) (orientation de la surface, son poids) (ligne de sa forme, part de la forme, -, -) ;
    // le linteau de l'allee en dernier. grille : 0 = de simples cubes suffisent, sinon la finesse des formes
    function ecrire() {
      let n = 0, forme = false;
      for (const b of br) {
        donnees.set([b.p[0], b.p[1], b.p[2], b.lueur, b.q[0], b.q[1], b.q[2], b.q[3], b.s[0], b.s[1], b.s[2], b.brume,
          b.gly[0], b.gly[1], b.gly[2], b.gly[3], b.graine, b.rmax, b.eclat ? 2 : b.signes, b.det, b.n[0], b.n[1], b.n[2], b.nw,
          b.rang_f, b.g, b.ton, 0], n * F);
        if (b.g > 0.001) forme = true;
        n++;
      }
      const lin = allee.lin;
      if (lin.actif) {
        const a = lin.a, c = lin.b, rot = (a.rot + c.rot) / 2, q = qz(rot);
        donnees.set([(a.x + c.x) / 2, (a.y + c.y) / 2, lin.z, 0, q[0], q[1], q[2], q[3], Math.abs(a.x - c.x) + (a.l + c.l) / 2 + 0.55,
          Math.max(a.p, c.p) + 0.3, 0.64, 1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0], n * F);
        n++;
      }
      return { n, donnees, grille: forme ? ngActif : 0 };
    }
    // la forme du monument qui arrive, a envoyer une fois dans la texture (puis plus rien)
    function prendreForme() { const a = aEnvoyer; aEnvoyer = null; return a; }

    return {
      avancer, ecrire, prendreForme, N, briques: br,
      nouveauSujet() { nom = prochain(); partir(monument(nom)); return nom; },
      former(n) { if (Array.isArray(n)) { nom = '?'; partir(n); return nom; } if (!MONUMENTS[n]) return null; nom = n; partir(monument(n)); return n; },   // un nom, ou une liste de boites (essais)
      modelise: n => !!FORMES[n],
      retour() { nom = null; partir(null); },
      etat: () => etat, nom: () => nom,
    };
  }

  // ------------------------------------------------------------------ le fil des sujets
  // Un message ouvre un nouveau sujet s'il ne partage aucun mot important avec les derniers messages du sujet en cours,
  // ou apres un long silence. Une relance courte (« et demain ? », « vas-y ») reste dans le sujet.
  const VIDES = new Set(('pour dans avec mais donc alors plus moins tres bien fait faire fais faites peux peut pourrais pourrait veux voudrais ' +
    'voudrait quoi quel quelle quels quelles comment combien pourquoi quand cette cela celui celle ceux sont etre avoir suis etes avez avons ' +
    'tout tous toute toutes rien aussi encore merci bonjour salut archi stp svp elle elles ils sais savoir dire dis donne donner montre ' +
    'montrer explique expliquer chose choses truc quelque autre autres meme memes deja juste vraiment beaucoup sans sous entre vers chez ' +
    'apres avant depuis pendant maintenant aujourd demain hier ensuite puis voila voici ceci comme ainsi faut fallait mettre mets peux-tu ' +
    'est-ce estce quoi parle parler ton tes mon mes notre votre leurs leur avais aurais serait sera seras etait vais vas allez ' +
    'cest quil quelle jaimerais aimerais besoin aide aider ok oui non').split(' '));
  const SUITE = /^(et|mais|aussi|alors|donc|ok|oui|non|vas[- ]?y|d'accord|daccord|merci|encore|pareil|plutot|sinon|parfait|super|continue)\b/;
  function motsCles(texte) {
    return new Set(String(texte || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/['’]/g, ' ')
      .split(/[^a-z0-9]+/).filter(m => m.length >= 4 && !VIDES.has(m)).map(m => m.slice(0, 6)));
  }
  function creerFil(options) {
    const o = Object.assign({ silence: 15 * 60 * 1000 }, options || {});
    let recents = [], dernier = 0;
    return {
      nouveau(texte, maintenant) {
        const now = maintenant === undefined ? Date.now() : maintenant;
        const m = motsCles(texte), loin = now - dernier > o.silence;
        const brut = String(texte || '').trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
        dernier = now;
        const commun = recents.some(s => [...m].some(x => s.has(x)));
        let neuf;
        if (!recents.length || loin) neuf = true;
        else if (commun) neuf = false;
        else if (m.size < 2 || SUITE.test(brut)) neuf = false;
        else neuf = true;
        if (neuf) recents = [m]; else { recents.push(m); if (recents.length > 4) recents.shift(); }
        return neuf;
      },
    };
  }

  racine.ArchiMonuments = { creerChantier, creerFil, monument, NOMS, motsCles, placer, lireFormes };
})(typeof window !== 'undefined' ? window : globalThis);
