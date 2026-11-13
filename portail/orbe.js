// orbe.js - la sphere d'Archi en vraie 3D (WebGL 2), sur tout l'ecran : plus de cadre, elle vit dans le decor.
//
//   Une bulle de verre ; dedans, un plasma vivant et la constellation de points d'Archi ; autour, un nuage translucide
//   que les cometes des orbites remuent a leur passage, des eruptions comme des tempetes solaires, de la poussiere
//   qui flotte a differentes profondeurs (flou de mise au point), une lueur (bloom) et un grain de pellicule.
//   Decor « espace » (variante A) : une nebuleuse et des etoiles calculees ici.
//   Decor « image » (variante B) : un decor rendu dans Blender (base + lumiere de l'orbe + profondeur) ; la lumiere
//   de l'orbe y est ajoutee en direct, a la couleur de son etat : le verre et l'eau du decor changent de teinte avec elle.
//
//   Memes etats et meme interface que sphere.js (qui reste le secours sans WebGL 2) :
//   const s = ArchiOrbe(canvasPleinEcran, { ancre: elementOuSePoseLOrbe, decor: null | {...} });
//   if (!s) ... pas de WebGL 2 : prendre ArchiSphere
//   s.mode('reflechit'); s.niveau(() => 0.4); s.mots(['Medor']); s.stop();
// Aucune dependance, rien ne vient d'Internet. « Moins de mouvement » : deux images par seconde.
'use strict';
(function (racine) {
  const MODES = ['repos', 'ecoute', 'reflechit', 'agit', 'parle', 'muet'];
  const TEINTES = { repos: [61, 220, 151], parle: [61, 220, 151], ecoute: [34, 211, 238], reflechit: [251, 146, 60],
    agit: [167, 139, 250], muet: [248, 113, 113] };
  const GRIS = [150, 163, 157], MENTHE = [61, 220, 151], BLANC = [236, 255, 246];
  const CAM = 4.2;                     // distance de la camera au centre de l'orbe (rayon de l'orbe = 1)
  const lin = c => c.map(v => Math.pow(v / 255, 2.2));
  const melange = (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];

  // ------------------------------------------------------------------ les programmes (GLSL ES 3.0)
  const VS_ECRAN = `#version 300 es
const vec2 P[3] = vec2[3](vec2(-1.0,-1.0), vec2(3.0,-1.0), vec2(-1.0,3.0));
out vec2 vUv;
void main(){ vec2 p = P[gl_VertexID]; vUv = p*0.5+0.5; gl_Position = vec4(p,0.0,1.0); }`;

  const FS_SCENE = `#version 300 es
precision highp float; precision highp sampler3D;
in vec2 vUv; out vec4 sortie;
uniform vec2 uRes, uCentre, uSouris; uniform float uRayon, uT, uAgit, uAmp, uPouls, uTourne, uAnneau, uEcoute, uNuage, uFrame;
uniform vec3 uTeinte, uMenthe; uniform mat3 uVue;
uniform vec4 uCom[12]; uniform vec4 uComV[12];
uniform sampler3D uBruit;
uniform float uDecor, uLumOrbe, uExpoBase; uniform sampler2D uBase, uLum, uProf; uniform vec4 uPlaque; uniform vec3 uTeinteLum;
uniform sampler2D uHist; uniform float uMemo, uEcart, uTour, uRotC;
uniform vec4 uDoigt, uSourisP, uSourisV; uniform vec2 uRegard;
uniform sampler2D uGlyphes; uniform vec3 uCamP, uVersLune, uOrbeM; uniform mat3 uCamR; uniform vec2 uTan;
uniform sampler2D uBriques, uReflet; uniform float uBriquesOn, uEchA, uPense;
const float CAM = ${CAM.toFixed(2)};
float n3(vec3 p){ return texture(uBruit, p).r; }
float fbm(vec3 p){ return 0.5*n3(p) + 0.25*n3(p*2.03+vec3(0.31,0.17,0.53)) + 0.125*n3(p*4.07+vec3(0.67,0.41,0.13)); }
float h12(vec2 p){ vec3 q = fract(vec3(p.xyx)*0.1031); q += dot(q, q.yzx+33.33); return fract((q.x+q.y)*q.z); }
vec2 boule(vec3 ro, vec3 rd, float r){ float b = dot(ro,rd), c = dot(ro,ro)-r*r, h = b*b-c; if (h < 0.0) return vec2(-1.0); h = sqrt(h); return vec2(-b-h, -b+h); }
mat2 rot(float a){ float c = cos(a), s = sin(a); return mat2(c,-s,s,c); }

vec3 etoiles(vec2 px, float cel, float seuil){
  vec2 g = px/cel, id = floor(g), f = fract(g)-0.5; float h = h12(id);
  if (h < seuil) return vec3(0.0);
  vec2 o = vec2(h12(id+7.1), h12(id+3.7))-0.5; float d = length(f-o*0.6);
  float tw = 0.55+0.45*sin(uT*(0.7+h*2.6)+h*40.0);
  return mix(vec3(0.75,0.88,1.0), vec3(1.0,0.93,0.82), h12(id+1.3)) * smoothstep(0.11, 0.0, d) * pow((h-seuil)/(1.0-seuil), 1.5) * tw * 1.4;
}
// le decor « espace » : une nebuleuse sombre, eclairee par l'orbe, et des etoiles a deux profondeurs
vec3 espace(vec2 px){
  vec2 p = (px-uCentre)/uRes.y; float r = length(p);
  vec3 tn = mix(uMenthe, uTeinte, 0.6);
  vec3 c = mix(vec3(0.0022,0.0050,0.0046), vec3(0.0010,0.0019,0.0022), smoothstep(0.0, 1.3, r));
  vec3 q = vec3(p*0.42 + uSouris*0.02, uT*0.0015);
  float n = fbm(q), m = fbm(q*2.3 + n*0.9 + vec3(0.37, 0.11, uT*0.002));
  float neb = smoothstep(0.38, 0.86, n*0.62 + m*0.58);
  float halo = exp(-r*2.6);
  c += tn*neb*0.016*(0.12+1.8*halo)*exp(-r*1.2) + tn*0.03*halo*halo + uTeinte*0.010*exp(-r*7.0);
  c *= 0.75 + 0.5*m;
  c += etoiles(px + uSouris*uRes.y*0.008, uRes.y*0.025, 0.93)*0.55;
  c += etoiles(px + uSouris*uRes.y*0.022 + 91.0, uRes.y*0.06, 0.95)*0.9;
  return c;
}
// le decor « image » (Blender) : base + lumiere de l'orbe a sa couleur, un peu de parallaxe et une brume qui derive
vec3 allee(vec2 uv, vec3 fondc);
vec3 image(vec2 px){
  vec2 uv = (px - uPlaque.xy) * uPlaque.zw, uv0 = uv;
  float z = texture(uProf, uv).r;
  uv += uSouris * (1.0 - z) * 0.012;                       // parallaxe : le proche bouge plus que le lointain
  vec3 b = pow(texture(uBase, uv).rgb, vec3(2.2)), l = pow(texture(uLum, uv).rgb, vec3(2.2));
  vec3 c = b*uExpoBase + l*uTeinteLum*uLumOrbe;
  // une nappe de brume qui derive lentement au ras de l'eau et devant les montagnes
  float f = fbm(vec3(uv*vec2(0.9, 2.2) + vec2(uT*0.004, 0.0), uT*0.003));
  float bande = exp(-pow((uv.y - 0.40)/0.12, 2.0));
  float brume = smoothstep(0.3, 0.9, z) * smoothstep(0.38, 0.8, f) * bande;
  c += mix(vec3(0.030, 0.036, 0.040), uTeinteLum*0.04, 0.35) * brume;
  return uBriquesOn > 0.5 ? allee(uv0, c) : c;
}

// ---- l'allee (decor B) : ses briques sont dessinees a part (monuments.js les fait vivre, passes « briques » et « reflet »
// plus bas) ; ici on les pose sur le decor, avalees par la brume au loin, et leur reflet tremble dans le lac.
float brumeA(float a){ return 1.0 - exp(-max(a - 6.0, 0.0)*0.024); }
vec3 allee(vec2 uv, vec3 fondc){
  vec2 st = gl_FragCoord.xy/uRes;
  vec4 b = texture(uBriques, st);
  if (b.a > 0.0) return mix(b.rgb, fondc, brumeA(b.a/uEchA));
  vec3 ro = uCamP + vec3(uSouris.x, 0.0, uSouris.y)*0.16;
  vec3 rd = normalize(uCamR*vec3((uv.x*2.0 - 1.0)*uTan.x, (uv.y*2.0 - 1.0)*uTan.y, -1.0));
  if (rd.z < 0.0) {
    vec3 pw = ro + rd*(-ro.z/rd.z);
    vec2 q = pw.xy*vec2(0.55, 0.16);
    vec2 ond = (vec2(n3(vec3(q, uT*0.04)), n3(vec3(q + 7.3, uT*0.04))) - 0.5)*vec2(0.028, 0.012);
    vec4 r = texture(uReflet, st + ond);
    if (r.a > 0.0) return mix(fondc, mix(r.rgb, fondc, brumeA(r.a/uEchA)), 0.6);
  }
  return fondc;
}
vec3 fond(vec2 px){ return uDecor > 0.5 ? image(px) : espace(px); }

// le nuage : un anneau incline et un halo, creuse et entraine par le sillage des cometes
float nuage(vec3 p, out float eclat){
  float r = length(p); eclat = 0.0;
  vec3 a = p; a.yz = rot(0.42)*a.yz; a.xy = rot(-0.18)*a.xy;
  float anneau = exp(-pow((length(a.xz)-1.6)/0.48, 2.0)) * exp(-pow(a.y/0.30, 2.0));
  float halo = exp(-max(r-1.0, 0.0)*3.2)*0.35;
  float base = anneau + halo;
  if (base < 0.015) return 0.0;
  vec3 dep = vec3(0.0); float w = 0.0;
  for (int i = 0; i < 12; i++) {
    vec3 d = p - uCom[i].xyz, v = uComV[i].xyz;
    float derriere = dot(d, -v);
    vec3 perp = d + v*derriere;
    float s = 0.07 + 0.2*clamp(derriere/uComV[i].w, 0.0, 1.0);
    float k = exp(-dot(perp,perp)/(s*s)) * smoothstep(-0.1, 0.02, derriere) * exp(-max(derriere,0.0)/uComV[i].w) * uCom[i].w;
    dep += v*k; w += k;
  }
  // la souris remue la brume a son passage
  { vec3 d = p - uSourisP.xyz, v = uSourisV.xyz; float derriere = dot(d, -v); vec3 perp = d + v*derriere;
    float s = 0.14 + 0.3*clamp(derriere/uSourisV.w, 0.0, 1.0);
    float k = exp(-dot(perp,perp)/(s*s)) * smoothstep(-0.2, 0.02, derriere) * exp(-max(derriere, 0.0)/uSourisV.w) * uSourisP.w;
    dep += v*k*1.6; w += k*0.8; }
  vec3 q = p*0.16 - dep*0.05 + vec3(0.0, uT*0.003, uT*0.004);
  q.xz = rot(uT*0.04*(0.5+uAgit)/max(r, 0.7))*q.xz;
  float n = fbm(q + 0.45*fbm(q*1.7 + vec3(1.3, 0.2, uT*0.003)) - 0.2);
  eclat = min(w, 1.5);
  return base * smoothstep(0.42, 0.8, n) * 2.0 * (1.0 - 0.5*min(w, 1.0));
}
vec4 marcher(vec3 ro, vec3 rd, float t0, float t1, float jit){
  vec3 acc = vec3(0.0); float T = 1.0;
  if (t1 <= t0) return vec4(acc, T);
  const int N = 26; float dt = (t1-t0)/float(N), t = t0 + dt*jit;
  vec3 tn = mix(uMenthe, uTeinte, 0.65);
  for (int i = 0; i < N; i++) {
    vec3 p = ro + rd*t; float ec; float d = nuage(p, ec);
    if (d > 0.002) {
      float r = length(p);
      float lum = 0.25 + 1.5/(1.0 + 4.0*(r-1.0)*(r-1.0));
      vec3 col = mix(vec3(0.62,0.72,0.80), tn, 0.6)*lum + vec3(1.0, 0.98, 0.95)*ec*0.7;
      float a = d*dt*uNuage;
      acc += T*col*a*0.32; T *= exp(-a*0.4);
    }
    t += dt;
  }
  return vec4(acc, T);
}
// le coeur : un cristal d'architecte, douze vitraux (un dodecaedre) qui s'ecartent quand Archi travaille
// et respirent quand il parle ; leurs cadres sont de lumiere, le verre est fume
const float RC = 0.36;
const vec3 AX[6] = vec3[6](vec3(0.0, 0.5257311, 0.8506508), vec3(0.0, 0.5257311, -0.8506508), vec3(0.5257311, 0.8506508, 0.0),
                           vec3(-0.5257311, 0.8506508, 0.0), vec3(0.8506508, 0.0, 0.5257311), vec3(0.8506508, 0.0, -0.5257311));
// le cristal se tourne un peu vers la souris
vec3 tourner(vec3 p){ p.xz = rot(uRotC + uRegard.x)*p.xz; p.yz = rot(0.55 - uRegard.y)*p.yz; return p; }
vec3 detourner(vec3 p){ p.yz = rot(-0.55 + uRegard.y)*p.yz; p.xz = rot(-uRotC - uRegard.x)*p.xz; return p; }
float cristal(vec3 p, out float cadre){
  float b1 = -1.0, b2 = -1.0, id = 0.0; vec3 n1 = vec3(0.0, 1.0, 0.0), n2 = vec3(1.0, 0.0, 0.0);
  for (int i = 0; i < 6; i++) {
    float d = dot(p, AX[i]), a = abs(d); vec3 n = d < 0.0 ? -AX[i] : AX[i];
    if (a > b1) { b2 = b1; n2 = n1; b1 = a; n1 = n; id = float(i*2) + (d < 0.0 ? 1.0 : 0.0); }
    else if (a > b2) { b2 = a; n2 = n; }
  }
  float off = uEcart*(0.075 + 0.05*sin(id*2.3 + uT*1.3)) + uAmp*0.035*(0.5 + 0.5*sin(id*1.7 + uT*8.0));
  vec3 q = p - n1*off;
  cadre = dot(q, normalize(n1 - n2));               // distance au joint le plus proche
  return max(abs(dot(q, n1) - RC) - 0.014, 0.009 - cadre);
}
// deux impacts au plus (le vitrail de devant, celui de derriere) : x,z = distance, y,w = distance au joint
vec4 viser(vec3 ro, vec3 rd){
  vec4 h = vec4(-1.0);
  vec2 bc = boule(ro, rd, 0.66);
  if (bc.y < 0.0) return h;
  float t = max(bc.x, 0.0); int etat = 0;
  for (int i = 0; i < 56; i++) {
    float c; float d = cristal(tourner(ro + rd*t), c);
    if (etat == 1) { if (d > 0.002) etat = 2; t += max(abs(d), 0.004); }
    else if (d < 0.0012) { if (etat == 0) { h.xy = vec2(t, c); etat = 1; t += 0.004; } else { h.zw = vec2(t, c); break; } }
    else t += d*0.8;
    if (t > bc.y) break;
  }
  return h;
}
vec3 normaleCristal(vec3 p){
  const vec2 k = vec2(1.0, -1.0); float c; const float e = 0.0015;
  vec3 g = k.xyy*cristal(p + k.xyy*e, c) + k.yyx*cristal(p + k.yyx*e, c) + k.yxy*cristal(p + k.yxy*e, c) + k.xxx*cristal(p + k.xxx*e, c);
  return normalize(g);
}
float fenetreRefl(vec3 r){
  vec2 fw = vec2(r.x + 0.42, r.y - 0.50);
  float f = exp(-pow(abs(fw.x)/0.12, 6.0) - pow(abs(fw.y)/0.17, 6.0)) * smoothstep(-0.1, 0.3, r.z) * (0.45 + 0.55*smoothstep(-0.17, 0.17, fw.y));
  return f * (1.0 - 0.85*exp(-pow(fw.x/0.007, 2.0))) * (1.0 - 0.85*exp(-pow((fw.y - 0.03)/0.007, 2.0)));
}
// la lumiere d'un vitrail touche : cadre lumineux, epure gravee, reflet de la fenetre ; a = ce qu'il laisse passer
vec4 vitrail(vec3 ro, vec3 rd, float t, float cadre, float loin){
  vec3 p = ro + rd*t, pc = tourner(p);
  vec3 nn = detourner(normaleCristal(pc));
  if (dot(nn, rd) > 0.0) nn = -nn;
  float fr = pow(1.0 - abs(dot(rd, nn)), 3.0);
  vec3 pale = mix(vec3(0.86, 0.94, 0.96), uTeinte, 0.30);
  float joint = exp(-max(cadre - 0.009, 0.0)*150.0);
  float epure = smoothstep(0.90, 1.0, fract(cadre*30.0)) * smoothstep(0.02, 0.05, cadre) * 0.12;
  float vie = 1.0 + 0.45*uPouls + 0.6*uAmp + 0.35*uTourne + 0.45*uDoigt.w;
  vec3 c = pale*joint*(0.8*vie) + mix(uTeinte, pale, 0.4)*epure*vie
         + uTeinte*0.05*(1.0 + 2.0*uPouls)                         // le verre fume, eclaire du dedans
         + vec3(0.9, 0.95, 1.0)*fenetreRefl(reflect(rd, nn))*(0.25 + 0.75*fr)*0.7;
  return vec4(c*loin, mix(0.5, 0.25, fr));
}
// l'interieur : une lueur ramassee au centre, en volutes ; le cristal y est pris
vec4 plasma(vec3 ro, vec3 rd, vec2 ti, float jit){
  vec3 acc = vec3(0.0); float T = 1.0;
  vec4 h = viser(ro, rd);
  vec4 v1 = h.x > 0.0 ? vitrail(ro, rd, h.x, h.y, 1.0) : vec4(0.0, 0.0, 0.0, 1.0);
  vec4 v2 = h.z > 0.0 ? vitrail(ro, rd, h.z, h.w, 0.7) : vec4(0.0, 0.0, 0.0, 1.0);
  const int N = 22; float dt = (ti.y-ti.x)/float(N), t = ti.x + dt*jit;
  vec3 pale = mix(vec3(0.80, 0.90, 0.93), uTeinte, 0.22);
  for (int i = 0; i < N; i++) {
    if (h.x > 0.0 && t > h.x) { acc += T*v1.rgb; T *= v1.a; h.x = -1.0; }
    if (h.z > 0.0 && t > h.z) { acc += T*v2.rgb; T *= v2.a; h.z = -1.0; }
    vec3 p = ro + rd*t; float r = length(p);
    p.xz = rot(uTour*(1.4 - r))*p.xz;                    // tourbillon, plus vif pres du coeur
    vec3 q = p*0.42 + vec3(0.0, uT*0.003, 0.0);
    vec2 w = vec2(fbm(q*1.3 + vec3(0.0, 0.0, uT*0.005)), fbm(q*1.3 + vec3(5.2, 1.3, 0.0)));
    float n = fbm(q + vec3(w*0.4, 0.0));
    float masse = smoothstep(0.85, 0.08, r);
    float fil = exp(-pow((n-0.47)*14.0, 2.0));
    float coeur = exp(-r*r*30.0);
    float d = fil*(0.7 + 1.0*uAgit + 0.8*uAmp)*masse*masse + coeur*(0.9 + 2.2*uPouls + 1.2*uAmp);
    vec3 col = mix(uTeinte*0.5, pale, clamp(fil*masse*0.6 + coeur*1.3, 0.0, 1.0));
    acc += T*col*d*dt*0.55; T *= exp(-d*dt*0.3);
    t += dt;
  }
  if (h.x > 0.0) { acc += T*v1.rgb; T *= v1.a; }
  if (h.z > 0.0) { acc += T*v2.rgb; T *= v2.a; }
  return vec4(acc, T);
}
// la membrane : la bulle n'est pas une boule parfaite. Comme sur le telephone, son bord ondule en lobes lents ;
// elle s'agite et tourne quand Archi reflechit ou agit, et vibre quand il parle ou ecoute
float relief(vec3 n){
  vec3 m = n; m.xz = rot(uTour*1.5)*m.xz;
  float t = uT*1.3;
  float lent = sin(dot(m, vec3(0.80, 0.50, 0.33))*3.2 + t)*0.5 + sin(dot(m, vec3(-0.30, 0.88, 0.37))*5.1 - t*1.7)*0.3
             + sin(dot(m, vec3(0.48, -0.25, 0.84))*8.3 + t*2.3)*0.2;
  float vif = sin(dot(m, vec3(0.62, -0.70, 0.35))*6.0 + uT*4.0)*0.6 + sin(dot(m, vec3(-0.70, 0.12, 0.70))*9.0 - uT*5.2)*0.4;
  float vibre = sin(m.y*14.0 - uT*9.0);
  // sous la souris : la membrane se tend vers elle, et des ondes en partent
  float c = dot(n, uDoigt.xyz);
  float doigt = uDoigt.w*(0.07*pow(max(c, 0.0), 12.0) + 0.016*sin((1.0 - c)*34.0 - uT*7.0)*exp(-(1.0 - c)*5.0));
  return 0.05*lent + (0.04*uTourne + 0.02*uAgit)*vif + 0.02*uAmp*vibre + doigt;
}
float membrane(vec3 p){ float r = length(p); return r - 1.0 - relief(p/max(r, 1e-4)); }
// l'entree et la sortie du rayon dans la membrane (x < 0 : il la manque)
vec2 coque(vec3 ro, vec3 rd){
  vec2 b = boule(ro, rd, 1.22);
  if (b.y < 0.0) return vec2(-1.0);
  float t0 = max(b.x, 0.0), t1 = b.y; bool ok = false;
  for (int i = 0; i < 32; i++) { float d = membrane(ro + rd*t0); if (d < 0.0015) { ok = true; break; } t0 += d*0.6; if (t0 > t1) break; }
  if (!ok) return vec2(-1.0);
  for (int i = 0; i < 32; i++) { float d = membrane(ro + rd*t1); if (d < 0.0015) break; t1 -= d*0.6; if (t1 < t0) { t1 = t0; break; } }
  return vec2(t0, t1);
}
vec3 normaleMembrane(vec3 p){
  const vec2 k = vec2(1.0, -1.0); const float e = 0.002;
  return normalize(k.xyy*membrane(p + k.xyy*e) + k.yyx*membrane(p + k.yyx*e) + k.yxy*membrane(p + k.yxy*e) + k.xxx*membrane(p + k.xxx*e));
}
void main(){
  vec2 px = gl_FragCoord.xy;
  vec2 q = (px - uCentre)/uRayon;
  vec3 ro = uVue*vec3(0.0, 0.0, CAM), rd = uVue*normalize(vec3(q, -CAM));
  float jit = fract(52.9829189*fract(dot(px + vec2(5.588238, 5.588238)*mod(uFrame, 64.0), vec2(0.06711056, 0.00583715))));
  vec2 bn = boule(ro, rd, 2.6), bo = coque(ro, rd);
  vec3 col;
  if (bn.y < 0.0) col = fond(px);
  else if (bo.y < 0.0) { vec4 n = marcher(ro, rd, max(bn.x,0.0), bn.y, jit); col = fond(px)*n.a + n.rgb; }
  else {
    vec4 avant = marcher(ro, rd, max(bn.x,0.0), bo.x, jit);
    vec4 arriere = marcher(ro, rd, bo.y, bn.y, jit);
    vec3 n = normaleMembrane(ro + rd*bo.x);
    float fres = pow(1.0 - max(dot(-rd, n), 0.0), 3.0);
    vec2 dec = (uVue*n).xy;   // le verre devie un peu ce qu'il y a derriere
    vec2 retourne = uCentre - (px - uCentre)*0.55 - dec*uRayon*0.12;
    vec3 derriere = fond(retourne)*arriere.a*0.6 + arriere.rgb*0.4;
    vec4 pl = plasma(ro, rd, bo, jit);
    vec3 cle = normalize(vec3(-0.55, 0.65, 0.55)), reflet = reflect(rd, n);
    // le reflet d'une haute fenetre a meneaux : bords doux, plus clair en haut
    float fenetre = fenetreRefl(reflet);
    float spec = fenetre*0.9 + pow(max(dot(reflet, cle), 0.0), 400.0)*2.0 + pow(max(dot(reflet, normalize(vec3(0.7,-0.25,0.6))), 0.0), 24.0)*0.06;
    // de fins meridiens, comme une epure d'architecte, qui ne se voient qu'en bord de bulle
    vec3 nl = n; nl.xz = rot(uT*0.05)*nl.xz;
    float lon = atan(nl.z, nl.x), lat = asin(clamp(nl.y, -1.0, 1.0));
    float trame = max(1.0 - smoothstep(0.010, 0.026, 0.5 - abs(fract(lon*12.0/6.2832) - 0.5)),
                      1.0 - smoothstep(0.010, 0.026, 0.5 - abs(fract(lat*6.0/3.1416) - 0.5)));
    vec3 bord = mix(vec3(0.72, 0.84, 0.90), mix(uMenthe, uTeinte, 0.7), 0.45);
    vec3 verre = mix(vec3(0.72), uTeinte, 0.10);
    // un fin lisere irisé tout au bord (couche mince), puis le bord colore
    float lisere = smoothstep(0.82, 0.98, fres);
    vec3 iris = 0.5 + 0.5*cos(6.2832*(fres*1.6 + vec3(0.0, 0.33, 0.67)) + uT*0.2);
    vec3 orbe = pl.rgb + pl.a*verre*derriere + bord*fres*(0.22 + 0.4*uPouls) + iris*lisere*0.25 + vec3(spec)*(0.4 + 0.6*fres)
              + bord*trame*fres*0.30;
    // sous la souris : une tache de lumiere douce sur le verre, et un anneau qui s'en eloigne
    float sous = dot(normalize(ro + rd*bo.x), uDoigt.xyz);
    orbe += mix(uMenthe, vec3(1.0), 0.5)*uDoigt.w*(pow(max(sous, 0.0), 60.0)*0.35
          + exp(-pow((sous - (0.9 + 0.08*sin(uT*2.0)))*60.0, 2.0))*0.12);
    col = avant.rgb + avant.a*orbe;
  }
  // l'ecoute : des ondes ; muet : un fin anneau rouge
  float rq = length(q);
  for (int i = 0; i < 3; i++) {
    float p = fract(uT*0.55 + float(i)/3.0), rr = 1.12 + p*0.6*(0.4 + uAmp);
    col += uTeinte * exp(-pow((rq-rr)*uRayon*1.5, 2.0)) * (1.0-p)*(1.0-p) * 0.35 * uEcoute;
  }
  col += vec3(0.97,0.44,0.44) * exp(-pow((rq-1.13)*uRayon*0.7, 2.0)) * 0.9 * uAnneau;
  // un peu de l'image precedente : le grain des volumes se lisse d'une image a l'autre
  sortie = vec4(mix(col, texture(uHist, px/uRes).rgb, uMemo), 1.0);
}`;

  const VS_POINTS = `#version 300 es
layout(location=0) in vec4 aPos; layout(location=1) in vec4 aCol;
uniform mat3 uVue; uniform vec2 uRes, uCentre; uniform float uRayon, uEchelle;
out vec4 vCol; out float vFlou;
const float CAM = ${CAM.toFixed(2)};
void main(){
  vec3 p = transpose(uVue)*aPos.xyz;            // repere de l'orbe -> repere de la camera
  float prof = CAM - p.z;
  if (prof < 0.4) { gl_Position = vec4(2.0, 2.0, 0.0, 1.0); gl_PointSize = 0.0; return; }
  float s = CAM/prof;
  vec2 ecran = uCentre + p.xy*s*uRayon;
  // derriere la bulle : vu a travers le verre, plus pale
  vec3 ro = vec3(0.0, 0.0, CAM), d = p - ro; float L = length(d); d /= L;
  float b = dot(ro, d), c = dot(ro, ro) - 1.0, h = b*b - c, voile = 1.0;
  if (h > 0.0 && -b - sqrt(h) < L - 0.02 && dot(p,p) > 1.0) voile = 0.4;
  // flou de mise au point : net pres de l'orbe, en bokeh loin devant ou loin derriere
  float flou = clamp(abs(p.z)*0.42 - 0.25, 0.0, 1.0) * aPos.w;
  float taille = max(1.0, aCol.a*s*uEchelle*(1.0 + flou*5.0));
  gl_PointSize = taille;
  vCol = vec4(aCol.rgb*voile/(1.0 + flou*flou*30.0), 1.0);
  vFlou = flou;
  gl_Position = vec4(ecran/uRes*2.0 - 1.0, 0.0, 1.0);
}`;

  const FS_POINTS = `#version 300 es
precision highp float;
in vec4 vCol; in float vFlou; out vec4 o;
void main(){
  vec2 c = gl_PointCoord*2.0 - 1.0; float d = dot(c, c);
  if (d > 1.0) discard;
  float net = exp(-d*4.5), bokeh = smoothstep(1.0, 0.72, d)*(0.55 + 0.45*d);
  o = vec4(vCol.rgb*mix(net, bokeh, vFlou), 1.0);
}`;

  const FS_CLAIR = `#version 300 es
precision highp float;
in vec2 vUv; out vec4 o; uniform sampler2D uTex; uniform vec2 uTexel; uniform float uSeuil;
void main(){
  vec3 c = (texture(uTex, vUv + uTexel*vec2(-1.0,-1.0)).rgb + texture(uTex, vUv + uTexel*vec2(1.0,-1.0)).rgb
          + texture(uTex, vUv + uTexel*vec2(-1.0,1.0)).rgb + texture(uTex, vUv + uTexel*vec2(1.0,1.0)).rgb)*0.25;
  float l = max(c.r, max(c.g, c.b));
  o = vec4(c*max(l - uSeuil, 0.0)/max(l, 1e-4), 1.0);
}`;
  const FS_FLOU = `#version 300 es
precision highp float;
in vec2 vUv; out vec4 o; uniform sampler2D uTex; uniform vec2 uDir;
void main(){
  vec3 c = texture(uTex, vUv).rgb*0.2270270;
  c += (texture(uTex, vUv + uDir*1.3846154).rgb + texture(uTex, vUv - uDir*1.3846154).rgb)*0.3162162;
  c += (texture(uTex, vUv + uDir*3.2307692).rgb + texture(uTex, vUv - uDir*3.2307692).rgb)*0.0702703;
  o = vec4(c, 1.0);
}`;
  const FS_FINAL = `#version 300 es
precision highp float;
in vec2 vUv; out vec4 o; uniform sampler2D uScene, uB1, uB2; uniform float uT, uFondu, uExpo;
vec3 aces(vec3 x){ return clamp((x*(2.51*x + 0.03))/(x*(2.43*x + 0.59) + 0.14), 0.0, 1.0); }
float h12(vec2 p){ vec3 q = fract(vec3(p.xyx)*0.1031); q += dot(q, q.yzx+33.33); return fract((q.x+q.y)*q.z); }
void main(){
  vec3 c = texture(uScene, vUv).rgb + texture(uB1, vUv).rgb*0.55 + texture(uB2, vUv).rgb*0.6;
  c = aces(c*uExpo);
  vec2 v = vUv - 0.5; c *= 1.0 - 0.42*pow(length(v*vec2(1.1, 1.25)), 2.2);
  c = pow(c, vec3(1.0/2.2));
  c += (h12(gl_FragCoord.xy + fract(uT*7.3)*311.0) - 0.5)*0.022;
  o = vec4(c*uFondu, 1.0);
}`;

  // ---- les briques de l'allee et des monuments : un cube par brique ; la meme camera que Blender (et que le decor),
  // le meme tremblement d'une image a l'autre. Sortie : la couleur de la pierre, et sa distance (pour la brume).
  // uMiroir = 1 : la passe du reflet (tout est retourne sous le lac).
  const COMMUN_BRIQUES = `
float h12(vec2 p){ vec3 q = fract(vec3(p.xyx)*0.1031); q += dot(q, q.yzx+33.33); return fract((q.x+q.y)*q.z); }
vec3 qrot(vec4 q, vec3 v){ return v + 2.0*cross(q.xyz, cross(q.xyz, v) + q.w*v); }`;
  const VS_BRIQUES = `#version 300 es
layout(location=0) in vec4 aPos; layout(location=1) in vec4 aQuat; layout(location=2) in vec4 aTaille;
layout(location=3) in vec4 aGly; layout(location=4) in vec4 aGly2; layout(location=5) in vec4 aNorm; layout(location=6) in vec4 aForme;
uniform vec3 uCamP; uniform mat3 uCamR; uniform vec2 uTan, uRes, uSouris; uniform vec4 uPlaque; uniform float uMiroir, uFrame;
uniform int uN; uniform sampler2D uForme;
out vec3 vMonde, vLocal, vNl; flat out vec4 vPos, vQuat, vTaille, vGly, vGly2, vNorm, vForme; flat out int vFace;
const vec3 C[8] = vec3[8](vec3(-0.5,-0.5,-0.5), vec3(0.5,-0.5,-0.5), vec3(0.5,0.5,-0.5), vec3(-0.5,0.5,-0.5),
                          vec3(-0.5,-0.5,0.5), vec3(0.5,-0.5,0.5), vec3(0.5,0.5,0.5), vec3(-0.5,0.5,0.5));
const int I[36] = int[36](0,1,5, 0,5,4, 1,2,6, 1,6,5, 2,3,7, 2,7,6, 3,0,4, 3,4,7, 4,5,6, 4,6,7, 3,2,1, 3,1,0);
const vec3 FN[6] = vec3[6](vec3(0.0,-1.0,0.0), vec3(1.0,0.0,0.0), vec3(0.0,1.0,0.0), vec3(-1.0,0.0,0.0), vec3(0.0,0.0,1.0), vec3(0.0,0.0,-1.0));
const vec3 FU[6] = vec3[6](vec3(1.0,0.0,0.0), vec3(0.0,1.0,0.0), vec3(-1.0,0.0,0.0), vec3(0.0,-1.0,0.0), vec3(1.0,0.0,0.0), vec3(1.0,0.0,0.0));
const vec3 FV[6] = vec3[6](vec3(0.0,0.0,1.0), vec3(0.0,0.0,1.0), vec3(0.0,0.0,1.0), vec3(0.0,0.0,1.0), vec3(0.0,1.0,0.0), vec3(0.0,-1.0,0.0));
${COMMUN_BRIQUES}
// la grille posee sur le cube (uN x uN carreaux par face) et la forme de la pierre : un rayon par point (texture, une ligne par pierre)
vec3 pt(int f, int i, int j){ float n = float(uN); return 0.5*FN[f] + (float(i)/n - 0.5)*FU[f] + (float(j)/n - 0.5)*FV[f]; }
vec3 surf(int f, int i, int j, int ligne, float g){
  float r = texelFetch(uForme, ivec2(f*(uN + 1)*(uN + 1) + j*(uN + 1) + i, ligne), 0).r;
  return pt(f, i, j)*aTaille.xyz*mix(1.0, r, g);
}
void main(){
  vec3 cub, loc, nl; int face;
  float g = aForme.y; int ligne = int(aForme.x + 0.5);
  if (uN == 0) { cub = C[I[gl_VertexID]]; face = gl_VertexID/6; loc = cub*aTaille.xyz; nl = FN[face]; }
  else {
    int per = uN*uN*6, k = gl_VertexID - (gl_VertexID/per)*per, q = k/6, c = k - q*6;
    face = gl_VertexID/per;
    int i = q - (q/uN)*uN + ((c == 1 || c == 2 || c == 4) ? 1 : 0), j = q/uN + ((c == 2 || c == 4 || c == 5) ? 1 : 0);
    cub = pt(face, i, j); loc = cub*aTaille.xyz; nl = FN[face];
    if (g > 0.001) {
      loc = surf(face, i, j, ligne, g);
      vec3 du = surf(face, min(i + 1, uN), j, ligne, g) - surf(face, max(i - 1, 0), j, ligne, g);
      vec3 dv = surf(face, i, min(j + 1, uN), ligne, g) - surf(face, i, max(j - 1, 0), ligne, g);
      vec3 cr = cross(du, dv);
      if (dot(cr, cr) > 1e-14) nl = normalize(cr);
    }
  }
  vec3 w = aPos.xyz + qrot(aQuat, loc);
  if (uMiroir > 0.5) w.z = -w.z;
  vMonde = w; vLocal = cub*aTaille.xyz; vNl = nl; vPos = aPos; vQuat = aQuat; vTaille = aTaille; vGly = aGly; vGly2 = aGly2; vNorm = aNorm;
  vForme = aForme; vFace = face;
  vec3 ro = uCamP + vec3(uSouris.x, 0.0, uSouris.y)*0.16;
  vec3 d = transpose(uCamR)*(w - ro);
  float zc = -d.z;
  vec2 jit = (vec2(h12(vec2(uFrame, 1.3)), h12(vec2(uFrame, 7.1))) - 0.5)*uPlaque.zw;
  vec2 pz = ((0.5 - jit)*zc + 0.5*d.xy/uTan)/uPlaque.zw + uPlaque.xy*zc;      // (pixel du tampon) x zc
  const float N = 0.1, F = 3000.0;
  gl_Position = vec4(pz/uRes*2.0 - zc, (zc*(F + N) - 2.0*F*N)/(F - N), zc);
}`;
  const FS_BRIQUES = `#version 300 es
precision highp float;
in vec3 vMonde, vLocal, vNl; flat in vec4 vPos, vQuat, vTaille, vGly, vGly2, vNorm, vForme; flat in int vFace;
uniform vec3 uCamP, uVersLune, uOrbeM, uTeinteLum, uMenthe, uTeinte; uniform vec2 uSouris;
uniform float uMiroir, uExpoBase, uLumOrbe, uT, uPense, uEchA;
uniform sampler2D uGlyphes;
out vec4 sortie;
${COMMUN_BRIQUES}
void main(){
  vec3 p = vMonde; if (uMiroir > 0.5) p.z = -p.z;          // la vraie place (le reflet est dessine retourne)
  if (p.z < 0.0) discard;                                    // sous l'eau : le lac la cache
  vec3 n = normalize(qrot(vQuat, vNl));
  n = normalize(mix(n, vNorm.xyz, 0.8*vNorm.w));                // une statue : la lumiere suit sa forme
  float mon = clamp((1.0 - vTaille.w)*1.8, 0.0, 1.0);          // une brique de monument (moins de brume) : un peu plus claire
  vec3 base = vec3(0.035, 0.038, 0.042)*(1.0 + 1.8*mon);
  base *= mix(1.0, 0.6 + 0.8*vForme.z, vForme.y);      // chaque pierre taillee a son ton (une statue d'un bloc : un seul)
  float lune = max(dot(n, uVersLune), 0.0);
  vec3 col = base*vec3(0.72, 0.82, 1.0)*(0.05 + 0.75*lune);
  // les aretes du monolithe d'origine attrapent un fil de lune ; une brique detachee montre aussi les siennes
  vec3 u3 = clamp(vLocal/vTaille.xyz + 0.5, 0.0, 1.0);
  float U = mix(vGly.x, vGly.y, u3.x), eU = 0.035*max(vGly.y - vGly.x, 0.05)/vTaille.x;
  float arete = max(smoothstep(1.0 - eU, 1.0, U), smoothstep(eU, 0.0, U))*(1.0 - abs(n.z));
  vec3 ab = abs(vLocal)/(vTaille.xyz*0.5);
  float mx = max(ab.x, max(ab.y, ab.z)), mn = min(ab.x, min(ab.y, ab.z)), mid = ab.x + ab.y + ab.z - mx - mn;
  float bord = smoothstep(0.9, 1.0, mid)*vGly2.w*(1.0 - vForme.y);
  col += vec3(0.55, 0.64, 0.78)*0.035*max(arete, bord)*(0.3 + lune);
  col *= (1.0 - 0.35*bord*(1.0 - lune))*uExpoBase;
  vec3 L = uOrbeM - p; float d2 = dot(L, L);
  col += base*uTeinteLum*uLumOrbe*max(dot(n, L*inversesqrt(d2)), 0.0)*20.0/d2;
  // la lune est derriere : un monument est eclaire de face par l'orbe (a sa couleur), assez pour lire sa forme
  col += base*uTeinteLum*uLumOrbe*mon*(0.1 + 0.5*max(dot(n, L*inversesqrt(d2)), 0.0))*0.9;
  // et une lumiere rasante, d'en haut a gauche : elle donne le relief (epaules, tete, pattes, degres)
  col += base*mon*vec3(0.85, 0.95, 1.1)*1.5*pow(max(dot(n, normalize(vec3(-0.55, -0.45, 0.7))), 0.0), 1.5);
  vec3 ton = mix(uMenthe, uTeinte, 0.4);
  // les signes graves : chaque brique garde son morceau d'inscription, meme en vol
  float m = 0.0, v = 0.0;
  vec2 gx = dFdx(u3.xz), gy = dFdy(u3.xz);   // hors du si : les derivees doivent etre calculees partout
  if ((vFace == 0 || vFace == 2) && vGly2.z > 0.5 && vGly2.z < 1.5) {
    float R = mix(vGly.z, vGly.w, u3.z);
    if (U > 0.19 && U < 0.81 && R >= 0.0 && R < vGly2.y) {
      float rang = floor(R), fi = vGly2.x;
      if (h12(vec2(rang*1.37 + 0.5, fi*3.1 + 0.7)) >= 0.16) {
        float k = floor(h12(vec2(fi*7.13 + 1.0, rang*3.71 + 2.0))*64.0);
        vec2 g = vec2((U - 0.19)/0.62, 1.0 - fract(R))*0.86 + 0.07;
        vec2 cu = vec2((vGly.y - vGly.x)/0.62, -(vGly.w - vGly.z))*0.86/8.0;
        m = textureGrad(uGlyphes, (vec2(mod(k, 8.0), floor(k/8.0)) + g)/8.0, gx*cu, gy*cu).r;
        float onde = 0.5 + 0.5*sin(uT*(1.2 + 1.2*uPense) - rang*0.62 + fi*2.3);
        v = vPos.w*smoothstep(0.25, 0.95, onde)*(0.75 + 0.25*sin(uT*7.0 + rang*5.1 + fi));
      }
    }
  }
  col *= 1.0 - 0.2*m;
  col += ton*m*max(v, 0.015*mon)*2.6;                         // un monument garde ses signes a peine allumes
  if (vGly2.z > 1.5) col += ton*0.22*(0.75 + 0.25*sin(uT*2.0));          // la pierre qui brille (le pyramidion...)
  // le champ qui les porte : un liseré de lumiere sur les briques qui volent
  vec3 ro = uCamP + vec3(uSouris.x, 0.0, uSouris.y)*0.16, vd = normalize(vMonde - ro);
  vec3 nr = uMiroir > 0.5 ? vec3(n.xy, -n.z) : n;
  col += ton*0.06*vGly2.w*pow(1.0 - abs(dot(nr, vd)), 3.0)*(0.4 + vPos.w);
  float t = length(vMonde - ro);
  sortie = vec4(col, (6.0 + max(t - 6.0, 0.0)*vTaille.w)*uEchA);
}`;

  // ------------------------------------------------------------------ outils WebGL
  function programme(gl, vs, fs) {
    const p = gl.createProgram();
    for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(p, s);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    const u = {}, n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) { const nom = gl.getActiveUniform(p, i).name.replace(/\[0\]$/, ''); u[nom] = gl.getUniformLocation(p, nom); }
    return { p, u };
  }
  // un bruit 3D doux qui se repete sans couture (value noise lisse, deux canaux), calcule une fois
  function texBruit(gl) {
    const S = 64, L = 16, R = new Float32Array(L * L * L), G = new Float32Array(L * L * L);
    for (let i = 0; i < R.length; i++) { R[i] = Math.random(); G[i] = Math.random(); }
    const lisse = t => t * t * t * (t * (t * 6 - 15) + 10);
    const d = new Uint8Array(S * S * S * 4), k = L / S;
    for (let z = 0; z < S; z++) for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
      const fx = x * k, fy = y * k, fz = z * k, ix = Math.floor(fx), iy = Math.floor(fy), iz = Math.floor(fz);
      const ux = lisse(fx - ix), uy = lisse(fy - iy), uz = lisse(fz - iz);
      const X0 = ix % L, X1 = (ix + 1) % L, Y0 = (iy % L) * L, Y1 = ((iy + 1) % L) * L, Z0 = (iz % L) * L * L, Z1 = ((iz + 1) % L) * L * L;
      const i = (x + y * S + z * S * S) * 4;
      for (const [T, c] of [[R, 0], [G, 1]]) {
        const a = T[X0 + Y0 + Z0] + (T[X1 + Y0 + Z0] - T[X0 + Y0 + Z0]) * ux, b = T[X0 + Y1 + Z0] + (T[X1 + Y1 + Z0] - T[X0 + Y1 + Z0]) * ux;
        const e = T[X0 + Y0 + Z1] + (T[X1 + Y0 + Z1] - T[X0 + Y0 + Z1]) * ux, f = T[X0 + Y1 + Z1] + (T[X1 + Y1 + Z1] - T[X0 + Y1 + Z1]) * ux;
        const v1 = a + (b - a) * uy, v2 = e + (f - e) * uy;
        d[i + c] = Math.round((v1 + (v2 - v1) * uz) * 255);
      }
      d[i + 3] = 255;
    }
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_3D, t);
    gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGBA8, S, S, S, 0, gl.RGBA, gl.UNSIGNED_BYTE, d);
    for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.REPEAT], [gl.TEXTURE_WRAP_T, gl.REPEAT], [gl.TEXTURE_WRAP_R, gl.REPEAT]]) gl.texParameteri(gl.TEXTURE_3D, p, v);
    return t;
  }
  function tex2D(gl, source) {
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    if (source) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, source);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, p, v);
    return t;
  }

  // les signes graves sur les monolithes : un alphabet maison (pas celui d'un jeu), dessine une fois, 64 signes sur une
  // planche 8 x 8. Cinq familles de traits (epine et croissants, anneau ouvert, zigzag, barre haute et crochets, arcs
  // emboites) et des signes diacritiques (un point au-dessus, un trait dessous).
  function texSignes(gl) {
    const N = 8, C = 64, doc = racine.document;
    if (!doc) return null;
    const cv = doc.createElement('canvas'); cv.width = cv.height = N * C;
    const g = cv.getContext('2d');
    if (!g) return null;
    let graine = 20261111;
    const al = () => { graine = (graine + 0x6D2B79F5) | 0; let x = Math.imul(graine ^ (graine >>> 15), 1 | graine); x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x; return ((x ^ (x >>> 14)) >>> 0) / 4294967296; };
    g.fillStyle = '#000'; g.fillRect(0, 0, cv.width, cv.height);
    const signe = (lw) => {
      for (let k = 0; k < N * N; k++) {
        g.save(); g.translate((k % N) * C + C / 2, Math.floor(k / N) * C + C / 2);
        g.strokeStyle = g.fillStyle = '#fff'; g.lineCap = g.lineJoin = 'round'; g.lineWidth = lw;
        const R = C * 0.32, P = Math.PI, fam = Math.floor(al() * 5);
        const trait = (...p) => { g.beginPath(); g.moveTo(p[0], p[1]); for (let i = 2; i < p.length; i += 2) g.lineTo(p[i], p[i + 1]); g.stroke(); };
        const arc = (x, y, r, a0, a1) => { g.beginPath(); g.arc(x, y, r, a0, a1); g.stroke(); };
        const point = (x, y) => { g.beginPath(); g.arc(x, y, Math.max(1.6, lw * 0.85), 0, 2 * P); g.fill(); };
        if (fam === 0) {                       // une epine, droite ou courbe, et un ou deux croissants accroches
          const w = (al() - 0.5) * R * 1.1;
          g.beginPath(); g.moveTo(0, -R);
          if (al() < 0.6) g.bezierCurveTo(w, -R * 0.3, -w, R * 0.3, 0, R); else g.lineTo(0, R);
          g.stroke();
          for (let a = 0, na = 1 + Math.floor(al() * 2); a < na; a++) {
            const y = (al() * 1.4 - 0.7) * R, r = R * (0.25 + al() * 0.3), cote = al() < 0.5 ? -1 : 1, a0 = al() * 2 * P;
            arc(cote * r * 0.85, y, r, a0, a0 + P * (0.7 + al() * 0.6));
          }
        } else if (fam === 1) {                // un anneau ouvert, d'ou part une queue
          const r = R * (0.42 + al() * 0.2), y = -R * 0.2, a0 = al() * 2 * P, a1 = a0 + P * (1.3 + al() * 0.4);
          arc(0, y, r, a0, a1);
          trait(Math.cos(a1) * r, y + Math.sin(a1) * r, (al() - 0.5) * R * 0.9, R);
          if (al() < 0.6) point(0, y);
        } else if (fam === 2) {                // un zigzag anguleux, termine par un point
          const n = 3 + Math.floor(al() * 2), p = [], cote = al() < 0.5 ? -1 : 1;
          for (let q = 0; q < n; q++) p.push((q % 2 ? cote : -cote) * R * (0.25 + al() * 0.45), -R + 2 * R * q / (n - 1));
          trait(...p);
          point(p[p.length - 2] * -0.9, p[p.length - 1] - R * 0.35);
        } else if (fam === 3) {                // une barre haute, et des crochets qui en pendent
          const y0 = -R * (0.6 + al() * 0.3);
          trait(-R * 0.75, y0, R * 0.75, y0 + (al() - 0.5) * 4);
          for (let q = 0, n = 1 + Math.floor(al() * 2); q < n; q++) {
            const x = (n === 1 ? 0 : q ? 0.4 : -0.4) * R + (al() - 0.5) * R * 0.2;
            g.beginPath(); g.moveTo(x, y0); g.quadraticCurveTo(x + (al() - 0.5) * R * 1.4, y0 + R * 1.1, x + (al() - 0.5) * R * 0.6, R * 0.95); g.stroke();
          }
        } else {                               // deux arcs emboites, tournes l'un contre l'autre, un point au centre
          const a0 = al() * 2 * P, sp = P * (0.7 + al() * 0.5);
          arc(0, 0, R * 0.85, a0, a0 + sp); arc(0, 0, R * 0.45, a0 + P, a0 + P + sp);
          if (al() < 0.7) point(0, 0); else trait(-R * 0.85, 0, R * 0.85, 0);
        }
        // les diacritiques
        if (al() < 0.4) point((al() - 0.5) * R * 1.1, -R * 1.25);
        if (al() < 0.25) trait(-R * 0.35, R * 1.2, R * 0.35, R * 1.2);
        g.restore();
      }
    };
    // d'abord le halo (large, flou), puis le trait net par-dessus, avec le meme tirage
    const depart = graine;
    if ('filter' in g) { g.filter = 'blur(3px)'; g.globalAlpha = 0.55; signe(7); g.filter = 'none'; g.globalAlpha = 1; }
    graine = depart; signe(3.4);
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, cv);
    gl.generateMipmap(gl.TEXTURE_2D);
    for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, p, v);
    return t;
  }

  // l'allee vit : de temps en temps un monolithe glisse de cote, monte ou s'enfonce dans le lac ; deux voisins d'un meme rang
  // se mettent a la meme hauteur et un linteau vient se poser dessus, reste un moment, puis repart. Quand Archi reflechit,
  // tout s'accelere et les signes s'allument ; au repos, un monolithe s'eclaire parfois tout seul, a peine.
  function creerAllee(liste, alea) {
    const M = liste.slice(0, 14).map(m => ({ rang: m.rang, cote: m.cote, x0: m.x, h0: m.haut, y: m.y, l: m.l, p: m.p, rot: m.rot,
      x: m.x, h: m.haut, h0: m.haut, vx: 0, vh: 0, cx: m.x, ch: m.haut, lueur: 0, allume: false, retard: 0, porte: false }));
    const lin = { actif: false, a: null, b: null, z: 0, vz: 0, cz: 0, etape: '', jusqua: 0 };
    let prochain = 5 + alea() * 5, souffle = 25 + alea() * 20, t = 0, pensait = false, depuis = 0;
    const libres = () => M.filter(m => !m.porte);
    // force (pour les essais) : 'linteau', 'glisse' ou 'monte' ; sinon le hasard choisit
    function evenement(pense, force) {
      const r = force === 'linteau' ? 0 : force === 'glisse' ? 0.5 : force === 'monte' ? 0.9 : alea();
      if (r < (pense ? 0.3 : 0.38) && !lin.actif) {
        // un rang qui a ses deux monolithes, pas le premier (trop pres : le linteau barrerait l'ecran)
        const rangs = [...new Set(M.map(m => m.rang))].filter(k => k > 0 && M.filter(m => m.rang === k && !m.porte).length === 2);
        if (rangs.length) {
          const k = rangs[Math.floor(alea() * rangs.length)], [a, b] = M.filter(m => m.rang === k);
          const h = Math.min(8.2, Math.max(5, (a.h + b.h) / 2));
          a.ch = b.ch = h; a.cx = a.x; b.cx = b.x; a.porte = b.porte = true;
          Object.assign(lin, { actif: true, a, b, z: h + 9, vz: 0, cz: h + 9, etape: 'attend', jusqua: t + 4.5 });
          return;
        }
      }
      const L = libres(); if (!L.length) return;
      const m = L[Math.floor(alea() * L.length)];
      if (r < 0.72) {
        const dx = (alea() < 0.5 ? -1 : 1) * (0.25 + alea() * 0.6);
        m.cx = m.cote * Math.min(4.7, Math.max(2.7, Math.abs(m.x0 + dx)));
      } else {
        m.ch = alea() < 0.35 ? m.h0 : Math.min(9.5, Math.max(1.4, m.h0 + (alea() * 4 - 2.5)));
      }
    }
    const ressort = (m, k, v, c, dt) => { const a = (c - m[k]) * 1.1 - m[v] * 2.1; m[v] += a * dt; m[k] += m[v] * dt; };
    // suspendu : les briques de l'allee sont parties former un monument ; plus d'evenement tant qu'elles n'y sont pas
    function avancer(dt, pense, suspendu) {
      t += dt;
      if (!suspendu) prochain -= dt * (1 + 2.2 * pense);
      if (prochain <= 0) { evenement(pense > 0.5); prochain = 7 + alea() * 8; }
      // le souffle : au repos, de loin en loin, un monolithe s'eclaire tout seul quelques secondes
      if (!suspendu) souffle -= dt;
      if (souffle <= 0) { const m = M[Math.floor(alea() * M.length)]; if (m && !pensait) m.lueur = Math.max(m.lueur, 0.45); souffle = 30 + alea() * 30; }
      // quand il se met a reflechir : une partie des monolithes s'allume, en vague, du plus proche au plus loin ;
      // quand il a fini, ils s'eteignent doucement
      const pense1 = pense > 0.5;
      if (pense1 && !pensait) {
        depuis = 0;
        for (const m of M) { m.allume = alea() < 0.55; m.retard = m.rang * 0.45 + alea() * 0.8; }
        if (M.filter(m => m.allume).length < 2) M.slice(0, 2).forEach(m => { m.allume = true; });
      }
      pensait = pense1; depuis += dt;
      for (const m of M) {
        ressort(m, 'x', 'vx', m.cx, dt); ressort(m, 'h', 'vh', m.ch, dt);
        m.lueur = pense1 && m.allume && depuis > m.retard ? Math.min(1, m.lueur + dt / 1.2) : Math.max(0, m.lueur - dt / 5);
      }
      if (lin.actif) {
        if (lin.etape === 'attend' && t > lin.jusqua) { lin.etape = 'pose'; lin.cz = Math.max(lin.a.h, lin.b.h) + 0.32; lin.jusqua = t + 22 + alea() * 18; }
        else if (lin.etape === 'pose' && t > lin.jusqua) { lin.etape = 'part'; lin.cz = lin.z + 11; lin.jusqua = t + 6; }
        else if (lin.etape === 'part' && t > lin.jusqua) { lin.actif = false; lin.a.porte = lin.b.porte = false; }
        if (lin.etape === 'pose') lin.cz = Math.max(lin.a.h, lin.b.h) + 0.32;
        const a = (lin.cz - lin.z) * 0.9 - lin.vz * 1.9; lin.vz += a * dt; lin.z += lin.vz * dt;
      }
    }
    // les boites pour le shader : centre (x, y, z), rotation ; taille (x, y, z), lueur (-1 : un linteau, sans signes)
    const pos = new Float32Array(64), tai = new Float32Array(64);
    function boites() {
      let n = 0;
      const mettre = (x, y, z, rot, sx, sy, sz, w) => { pos.set([x, y, z, rot], n * 4); tai.set([sx, sy, sz, w], n * 4); n++; };
      for (const m of M) mettre(m.x, m.y, (m.h - 1.2) / 2, m.rot, m.l, m.p, m.h + 1.2, m.lueur);
      if (lin.actif) {
        const a = lin.a, b = lin.b;
        mettre((a.x + b.x) / 2, (a.y + b.y) / 2, lin.z, (a.rot + b.rot) / 2, Math.abs(a.x - b.x) + (a.l + b.l) / 2 + 0.55, Math.max(a.p, b.p) + 0.3, 0.64, -1);
      }
      return { n, pos, tai };
    }
    // le linteau s'en va (ses piliers partent en briques)
    function congedier() { if (lin.actif && lin.etape !== 'part') { lin.etape = 'part'; lin.cz = lin.z + 11; lin.jusqua = t + 6; } }
    return { avancer, boites, lin, M, evenement, congedier };
  }

  // ------------------------------------------------------------------ l'orbe
  function ArchiOrbe(canvas, options) {
    const o = Object.assign({ ancre: null, rayon: 0.4, decor: null, couleurs: 'teintes', mots: true, calqueMots: null, qualite: 1 }, options || {});
    let gl = null;
    try {
      gl = canvas.getContext('webgl2', { alpha: false, antialias: false, depth: false, stencil: false, premultipliedAlpha: false, powerPreference: 'high-performance' });
    } catch (e) { gl = null; }
    if (!gl) return null;
    const hdr = !!gl.getExtension('EXT_color_buffer_float');
    let P;
    try {
      P = { scene: programme(gl, VS_ECRAN, FS_SCENE), points: programme(gl, VS_POINTS, FS_POINTS), clair: programme(gl, VS_ECRAN, FS_CLAIR),
        flou: programme(gl, VS_ECRAN, FS_FLOU), final: programme(gl, VS_ECRAN, FS_FINAL), briques: programme(gl, VS_BRIQUES, FS_BRIQUES) };
    } catch (e) {
      if (racine.console) console.warn('orbe : WebGL 2 present mais les programmes ne compilent pas', e);
      return null;
    }
    const bruit = texBruit(gl);
    const vide = tex2D(gl, null);
    const vao = gl.createVertexArray();

    // --- les points (constellation, orbites, cometes, eruptions, poussiere) : simules ici, dessines en une fois
    const NC = 900, NL = 170, NB = 17, NO = 4, NCO = 3, TRAINE = 18, NR = 150, NE = 8, NEP = 34, NP = 420;
    const TOTAL = NC + NO * NR + NO * NCO * TRAINE + NE * NEP + NP;
    const donnees = new Float32Array(TOTAL * 8);
    const tampon = gl.createBuffer();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, tampon);
    gl.bufferData(gl.ARRAY_BUFFER, donnees.byteLength, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 4, gl.FLOAT, false, 32, 0);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 32, 16);
    gl.bindVertexArray(null);

    const alea = () => Math.random();
    // la constellation : une boule de points ; chacun a sa place, sa taille, sa phase
    const cx = new Float32Array(NC), cy = new Float32Array(NC), cz = new Float32Array(NC), bx = new Float32Array(NC), by = new Float32Array(NC), bz = new Float32Array(NC);
    const cs = new Float32Array(NC), cph = new Float32Array(NC);
    for (let i = 0; i < NC; i++) {
      let x, y, z; do { x = alea() * 2 - 1; y = alea() * 2 - 1; z = alea() * 2 - 1; } while (x * x + y * y + z * z > 1);
      bx[i] = x * 0.9; by[i] = y * 0.9; bz[i] = z * 0.9; cx[i] = bx[i]; cy[i] = by[i]; cz[i] = bz[i];
      cs[i] = 0.6 + alea() * 1.1; cph[i] = alea() * 7;
    }
    // les orbites : un plan incline (deux axes), un rayon, une vitesse ; trois cometes chacune
    const orbites = [];
    for (let k = 0; k < NO; k++) {
      const inc = 0.25 + alea() * 0.9 * (k % 2 ? 1 : -1), az = alea() * Math.PI * 2;
      orbites.push({ inc, az, rayon: 1.25 + k * 0.13 + alea() * 0.05, vitesse: (0.22 + alea() * 0.25) * (k % 2 ? -1 : 1),
        derive: (alea() - 0.5) * 0.05, cometes: [0, 1, 2].map(() => alea() * Math.PI * 2) });
    }
    function surOrbite(ob, a, s) {
      const x = Math.cos(a) * ob.rayon, z = Math.sin(a) * ob.rayon;
      // incliner autour de x, puis tourner autour de y
      const y1 = -z * Math.sin(ob.inc), z1 = z * Math.cos(ob.inc);
      s[0] = x * Math.cos(ob.az) + z1 * Math.sin(ob.az); s[1] = y1; s[2] = -x * Math.sin(ob.az) + z1 * Math.cos(ob.az);
      return s;
    }
    const eruptions = [];
    let prochaineEruption = 0.6;
    // la poussiere : loin devant et loin derriere, elle donne la profondeur
    const px_ = new Float32Array(NP), py_ = new Float32Array(NP), pz_ = new Float32Array(NP), pv = new Float32Array(NP), pt = new Float32Array(NP);
    for (let i = 0; i < NP; i++) {
      const r = 1.9 + Math.pow(alea(), 0.7) * 2.6, a = alea() * Math.PI * 2, y = (alea() * 2 - 1) * 1.6;
      px_[i] = Math.cos(a) * r; pz_[i] = Math.sin(a) * r; py_[i] = y; pv[i] = 0.01 + alea() * 0.03; pt[i] = 0.4 + alea() * 1.4;
    }

    // --- l'etat
    let mode = 'repos', teinte = TEINTES.repos.slice(), anneau = 0, amp = 0, pouls = 0, tourne = 0, ecoute = 0, agitLisse = 0.2;
    let ecart = 0, tour = 0, rotC = 0.6;   // le cristal : ses vitraux ecartes, l'angle du tourbillon, l'angle du cristal
    let micro = null, t = 0, avant = 0, image = 0, arret = false, fondu = 0, frame = 0, debutMs = 0;
    let souris = [0, 0], sourisL = [0, 0], centre = [0, 0], rayonPx = 100, initialise = false;
    const calme = racine.matchMedia && racine.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const pleines = o.couleurs === 'pleines';
    const cible = m => (m === 'muet' && !pleines) ? GRIS : TEINTES[m];
    // la souris : la vue tourne doucement (parallaxe) ; elle touche la bulle, remue la brume
    let sourisPx = [0, 0], sourisLa = false, toucher = 0, doigt = [0, 0, 1], brassage = 0, pPrec = null, regard = [0, 0];
    const sourisDir = [0, 0, 1], sourisPos = [0, 0, 0];
    racine.addEventListener('pointermove', ev => {
      souris = [ev.clientX / racine.innerWidth * 2 - 1, -(ev.clientY / racine.innerHeight * 2 - 1)];
      sourisPx = [ev.clientX, ev.clientY]; sourisLa = ev.pointerType !== 'touch';
    }, { passive: true });
    if (racine.document) racine.document.documentElement.addEventListener('mouseleave', () => { sourisLa = false; });

    // --- le decor image (variante B)
    const decor = { pret: false, base: vide, lum: vide, prof: vide, meta: null, scene: null, allee: null, signes: null, chantier: null };
    const sc0 = o.decor && o.decor.scene;
    if (sc0 && !sc0.monolithes_dans_image && Array.isArray(sc0.monolithes) && sc0.monolithes.length) {
      try { decor.allee = creerAllee(sc0.monolithes, Math.random); decor.signes = texSignes(gl) || vide; decor.scene = sc0; } catch (e) { decor.allee = null; }
      // les briques (monuments.js) : l'allee se defait en briques qui forment un monument a chaque nouveau sujet
      try { if (decor.allee && racine.ArchiMonuments) decor.chantier = racine.ArchiMonuments.creerChantier(decor.allee); } catch (e) { decor.chantier = null; }
    }
    let vaoB = null, tamponB = null, texForme = null, texFormeK = 0;
    if (decor.chantier) {
      vaoB = gl.createVertexArray(); tamponB = gl.createBuffer();
      gl.bindVertexArray(vaoB); gl.bindBuffer(gl.ARRAY_BUFFER, tamponB);
      gl.bufferData(gl.ARRAY_BUFFER, (decor.chantier.N + 1) * 112, gl.DYNAMIC_DRAW);
      for (let i = 0; i < 7; i++) { gl.enableVertexAttribArray(i); gl.vertexAttribPointer(i, 4, gl.FLOAT, false, 112, i * 16); gl.vertexAttribDivisor(i, 1); }
      gl.bindVertexArray(null);
    }
    if (o.decor) {
      const charger = src => new Promise((ok, ko) => { const im = new Image(); im.onload = () => ok(im); im.onerror = ko; im.src = src; });
      Promise.all([charger(o.decor.base), charger(o.decor.lumiere), charger(o.decor.profondeur)]).then(([b, l, p]) => {
        decor.base = tex2D(gl, b); decor.lum = tex2D(gl, l); decor.prof = tex2D(gl, p);
        decor.meta = o.decor; decor.pret = true;
      }).catch(() => { decor.pret = false; });
    }

    // --- les mots-cles : du texte du DOM (net, dans la police de la page), places autour de l'orbe
    const mots = [], enAttente = [];
    let prochainMot = 0;

    // --- les tampons de rendu (la qualite s'adapte : si une image prend trop de temps, on baisse la definition)
    let qualite = Math.min(1, o.qualite), cibles = null, W = 0, H = 0, moyenne = 16, dernierAjustement = 0;
    let histoire = false, pp = 0, centrePrec = [0, 0];
    function cibleRendu(w, h, flottant) {
      const tx = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tx);
      gl.texImage2D(gl.TEXTURE_2D, 0, flottant ? gl.RGBA16F : gl.RGBA8, w, h, 0, gl.RGBA, flottant ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE, null);
      for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, p, v);
      const f = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, f);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tx, 0);
      const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      if (!ok && flottant) { gl.deleteTexture(tx); gl.deleteFramebuffer(f); return cibleRendu(w, h, false); }
      return { tx, f, w, h, fl: !!flottant };
    }
    // une cible avec sa profondeur (les briques se cachent les unes les autres)
    function cibleProf(w, h) {
      const c = cibleRendu(w, h, hdr), rb = gl.createRenderbuffer();
      gl.bindRenderbuffer(gl.RENDERBUFFER, rb); gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, w, h);
      gl.bindFramebuffer(gl.FRAMEBUFFER, c.f); gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, rb);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      c.rb = rb; return c;
    }
    function liberer() { if (!cibles) return; for (const c of Object.values(cibles)) { gl.deleteTexture(c.tx); gl.deleteFramebuffer(c.f); if (c.rb) gl.deleteRenderbuffer(c.rb); } cibles = null; }
    function mesurer() {
      const d = Math.min(1.5, racine.devicePixelRatio || 1) * qualite;
      const w = Math.max(16, Math.round(racine.innerWidth * d)), h = Math.max(16, Math.round(racine.innerHeight * d));
      if (w === W && h === H && cibles) return;
      W = w; H = h; canvas.width = W; canvas.height = H;
      liberer(); histoire = false;
      const q = (k) => [Math.max(1, Math.round(W / k)), Math.max(1, Math.round(H / k))];
      cibles = { h0: cibleRendu(W, H, hdr), h1: cibleRendu(W, H, hdr), scene: cibleRendu(W, H, hdr), a1: cibleRendu(...q(4), hdr), b1: cibleRendu(...q(4), hdr), a2: cibleRendu(...q(16), hdr), b2: cibleRendu(...q(16), hdr) };
      if (decor.chantier) { cibles.briques = cibleProf(W, H); cibles.reflet = cibleProf(...q(2)); }   // le reflet, flou dans l'eau : demi-definition
    }

    function passe(prog, cibleR, textures, uniformes) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, cibleR ? cibleR.f : null);
      gl.viewport(0, 0, cibleR ? cibleR.w : W, cibleR ? cibleR.h : H);
      gl.useProgram(prog.p);
      let unite = 0;
      for (const [nom, tx, type] of textures) {
        gl.activeTexture(gl.TEXTURE0 + unite); gl.bindTexture(type || gl.TEXTURE_2D, tx);
        if (prog.u[nom]) gl.uniform1i(prog.u[nom], unite);
        unite++;
      }
      uniformes(prog.u);
      gl.bindVertexArray(vao);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    // la vue : on regarde l'orbe un peu d'en haut ; la souris la fait tourner doucement (parallaxe)
    function matriceVue() {
      const yaw = sourisL[0] * 0.22 + Math.sin(t * 0.05) * 0.08, pitch = -0.26 + sourisL[1] * 0.12;
      const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
      // R = Ry(yaw) * Rx(pitch), en colonnes (camera -> orbe)
      return new Float32Array([cy, 0, -sy, sy * sp, cp, cy * sp, sy * cp, -sp, cy * cp]);
    }

    function ancrer() {
      const kx = W / racine.innerWidth, ky = H / racine.innerHeight;
      let x = racine.innerWidth / 2, y = racine.innerHeight * 0.4, r = Math.min(racine.innerWidth, racine.innerHeight) * 0.16;
      if (o.ancre && o.ancre.getBoundingClientRect) {
        const b = o.ancre.getBoundingClientRect();
        if (b.width > 0 && b.height > 0) { x = b.left + b.width / 2; y = b.top + b.height / 2; r = Math.min(b.width, b.height) * o.rayon; }
      }
      let plaque = null;
      if (decor.pret) {
        // le decor couvre l'ecran ; on le cale pour que son orbe tombe au plus pres de l'ancre
        const m = decor.meta, ew = racine.innerWidth, eh = racine.innerHeight;
        const s = Math.max(ew / m.largeur, eh / m.hauteur) * 1.06;
        let ox = x - m.orbe[0] * s, oy = y - m.orbe[1] * s;
        ox = Math.min(0, Math.max(ew - m.largeur * s, ox)); oy = Math.min(0, Math.max(eh - m.hauteur * s, oy));
        x = ox + m.orbe[0] * s; y = oy + m.orbe[1] * s; r = m.rayon * s;
        // px du tampon (origine en bas) -> uv de la plaque (origine en bas, l'image est retournee au chargement)
        plaque = [ox * kx, (eh - (oy + m.hauteur * s)) * ky, 1 / (m.largeur * s * kx), 1 / (m.hauteur * s * ky)];
      }
      const cible = [x * kx, (racine.innerHeight - y) * ky];
      if (!initialise) { centre = cible; rayonPx = r * kx; initialise = true; }
      centre[0] += (cible[0] - centre[0]) * 0.12; centre[1] += (cible[1] - centre[1]) * 0.12;
      rayonPx += (r * kx - rayonPx) * 0.08;
      return plaque;
    }

    function simuler(dt) {
      const f60 = dt * 60;
      const parle = mode === 'parle', ec = mode === 'ecoute', agit = mode === 'agit', tourneM = mode === 'reflechit' || agit;
      const kc = Math.min(1, 0.06 * f60);
      teinte = melange(teinte, cible(mode), kc);
      anneau += ((mode === 'muet' && !pleines ? 1 : 0) - anneau) * kc;
      tourne += ((tourneM ? 1 : 0) - tourne) * kc;
      ecoute += ((ec ? 1 : 0) - ecoute) * kc;
      const agitation = agit ? 1 : tourneM ? 0.8 : ec ? 0.45 : parle ? 0.35 : mode === 'muet' ? 0.08 : 0.2;
      agitLisse += (agitation - agitLisse) * Math.min(1, 0.04 * f60);
      pouls = agit ? 0.5 + 0.5 * Math.sin(t * 5) : pouls * 0.95;
      ecart += ((agit ? 1 : 0) - ecart) * Math.min(1, 0.035 * f60);
      tour += dt * (0.06 + 0.8 * tourne);
      rotC += dt * (0.10 + 0.55 * tourne + 0.25 * ecart);
      let vise = 0;
      if (ec) vise = micro ? Math.min(1, 0.15 + (micro() || 0)) : 0.35 + 0.6 * Math.abs(Math.sin(t * 2.2) * Math.sin(t * 3.7 + 1));
      else if (parle) vise = 0.2 + 0.8 * Math.abs(Math.sin(t * 9) * Math.sin(t * 2.3));
      amp += (vise - amp) * Math.min(1, 0.25 * f60);
      sourisL[0] += (souris[0] - sourisL[0]) * Math.min(1, 0.03 * f60); sourisL[1] += (souris[1] - sourisL[1]) * Math.min(1, 0.03 * f60);

      const lt = lin(teinte), blanc = lin(BLANC), cPoint = melange(blanc, lt, pleines ? 0.5 : 0.35), cBord = melange(blanc, lt, 0.6);
      let n = 0;
      const pose = (x, y, z, flou, r, g, b, taille) => { const i = n * 8; donnees[i] = x; donnees[i + 1] = y; donnees[i + 2] = z; donnees[i + 3] = flou; donnees[i + 4] = r; donnees[i + 5] = g; donnees[i + 6] = b; donnees[i + 7] = taille; n++; };
      // la constellation
      const vue = matriceVue(), cosA = Math.cos(0.012 * f60 * (0.4 + tourne * 1.6)), sinA = Math.sin(0.012 * f60 * (0.4 + tourne * 1.6));
      for (let i = 0; i < NC; i++) {
        let tx, ty, tz, l = 0.06, lum = 0;
        if (parle && i < NL * 2) {
          // la bouche : un egaliseur en amande, face a la camera, juste devant le centre
          const col = i % NB, par = Math.floor(NL * 2 / NB), s = Math.min(1, Math.floor(i / NB) / Math.max(1, par - 1)), u = (col / (NB - 1)) * 2 - 1;
          const tp = Math.pow(Math.max(0, 1 - u * u), 0.75), niv = 0.25 + 0.75 * Math.abs(Math.sin(t * 11 + col * 1.7) * Math.sin(t * 4.3 + col * 0.6));
          const h = Math.max(0.014, (0.035 + 0.27 * amp) * tp * niv);
          const vx = u * 0.5, vy = (s * 2 - 1) * h, vz = 0.45;
          tx = vue[0] * vx + vue[3] * vy + vue[6] * vz; ty = vue[1] * vx + vue[4] * vy + vue[7] * vz; tz = vue[2] * vx + vue[5] * vy + vue[8] * vz;
          l = 0.3; lum = 0.6;
        } else {
          if (tourne > 0.05) { const x = bx[i], z = bz[i]; bx[i] = x * cosA - z * sinA; bz[i] = x * sinA + z * cosA; }
          else { const x = bx[i], z = bz[i], c = Math.cos(0.0015 * f60), s = Math.sin(0.0015 * f60); bx[i] = x * c - z * s; bz[i] = x * s + z * c; }
          const k = 1 + 0.22 * amp + 0.07 * tourne * Math.sin(t * 6 + cph[i]);
          tx = bx[i] * k + Math.sin(t * 0.7 + cph[i]) * 0.025; ty = by[i] * k + Math.cos(t * 0.9 + cph[i]) * 0.025; tz = bz[i] * k;
        }
        const lp = 1 - Math.pow(1 - l, f60);
        cx[i] += (tx - cx[i]) * lp; cy[i] += (ty - cy[i]) * lp; cz[i] += (tz - cz[i]) * lp;
        const a = Math.max(0, Math.min(1, 0.35 + lum + 0.45 * Math.sin(t * 4 + cph[i]))) * (0.42 + lum * 0.5);
        pose(cx[i], cy[i], cz[i], 0, cPoint[0] * a, cPoint[1] * a, cPoint[2] * a, cs[i] * 1.25);
      }
      // les orbites (en pointilles, comme une epure) et leurs cometes ; les tetes partent aussi au nuage
      const s = [0, 0, 0], q = [0, 0, 0], tetes = [];
      for (const ob of orbites) {
        ob.az += ob.derive * dt;
        for (let j = 0; j < ob.cometes.length; j++) ob.cometes[j] += ob.vitesse * dt * (0.6 + agitLisse * 1.7);
        const ar = (0.05 + 0.07 * agitLisse);
        for (let j = 0; j < NR; j++) { surOrbite(ob, j / NR * Math.PI * 2, s); pose(s[0], s[1], s[2], 1, cBord[0] * ar, cBord[1] * ar, cBord[2] * ar, 1.1); }
        for (const a0 of ob.cometes) {
          const sens = Math.sign(ob.vitesse);
          surOrbite(ob, a0, s); surOrbite(ob, a0 + sens * 0.02, q);
          const vx = q[0] - s[0], vy = q[1] - s[1], vz = q[2] - s[2], vl = Math.hypot(vx, vy, vz) || 1;
          tetes.push([s[0], s[1], s[2], vx / vl, vy / vl, vz / vl]);
          for (let j = 0; j < TRAINE; j++) {
            surOrbite(ob, a0 - sens * j * 0.03, s);
            const al = Math.pow(1 - j / TRAINE, 1.6) * (0.5 + 0.8 * agitLisse) * (j === 0 ? 2.2 : 1);
            const c = j === 0 ? blanc : cBord;
            pose(s[0], s[1], s[2], 1, c[0] * al, c[1] * al, c[2] * al, j === 0 ? 3.2 : 2.0);
          }
        }
      }
      // les eruptions : une boucle qui jaillit de la surface, se tend, puis retombe
      if (t >= prochaineEruption && eruptions.length < NE) {
        let x = alea() * 2 - 1, y = alea() * 2 - 1, z = alea() * 2 - 1; const l = Math.hypot(x, y, z) || 1; x /= l; y /= l; z /= l;
        // un axe perpendiculaire pour l'arc
        let ax = -z, ay = 0, az = x; if (Math.abs(y) > 0.9) { ax = 1; ay = 0; az = 0; }
        const al = Math.hypot(ax, ay, az) || 1;
        eruptions.push({ d: [x, y, z], p: [ax / al, ay / al, az / al], large: 0.2 + alea() * 0.35, haut: 0.25 + alea() * (0.35 + 0.45 * agitLisse),
          vie: 0, duree: 1.6 + alea() * 1.9, sens: alea() < 0.5 ? -1 : 1 });
        prochaineEruption = t + (0.3 + alea() * 1.2) / (0.3 + agitLisse * 1.6);
      }
      const cE = melange(blanc, lt, 0.5);
      for (let k = eruptions.length - 1; k >= 0; k--) {
        const e = eruptions[k]; e.vie += dt / e.duree;
        if (e.vie >= 1) { eruptions.splice(k, 1); continue; }
      }
      for (let k = 0; k < NE; k++) {
        const e = eruptions[k];
        if (!e) { for (let j = 0; j < NEP; j++) pose(0, 0, 0, 0, 0, 0, 0, 0); continue; }
        const monte = Math.sin(Math.PI * Math.min(1, e.vie * 1.25)), alpha = Math.sin(Math.PI * e.vie) * (0.6 + 0.8 * agitLisse);
        const [dx, dy, dz] = e.d, [qx, qy, qz] = e.p, h = 1 + e.haut * monte;
        for (let j = 0; j < NEP; j++) {
          const u = ((j / NEP) + e.vie * 1.6 * e.sens + 10) % 1, ang = (u - 0.5) * e.large;
          // le pied sur la surface, le sommet souleve : une arche
          const lev = 1 + (h - 1) * Math.sin(Math.PI * u) * 1.15;
          const c = Math.cos(ang), sn = Math.sin(ang);
          const x = (dx * c + qx * sn) * lev, y = (dy * c + qy * sn) * lev, z = (dz * c + qz * sn) * lev;
          const fl = alpha * (0.55 + 0.45 * Math.sin(j * 1.7 + t * 6));
          const jx = Math.sin(j * 3.1 + t * 4) * 0.012, jy = Math.cos(j * 2.3 + t * 5) * 0.012;
          pose(x + jx, y + jy, z, 0, (j % 3 ? cE : lt)[0] * fl * 1.5, (j % 3 ? cE : lt)[1] * fl * 1.5, (j % 3 ? cE : lt)[2] * fl * 1.5, j % 3 ? 2.2 : 4.5);
        }
      }
      // la poussiere : elle tourne lentement autour de l'orbe
      for (let i = 0; i < NP; i++) {
        const a = pv[i] * dt * (0.5 + agitLisse), x = px_[i], z = pz_[i];
        px_[i] = x * Math.cos(a) - z * Math.sin(a); pz_[i] = x * Math.sin(a) + z * Math.cos(a);
        const fl = 0.08 + 0.06 * Math.sin(t * 0.8 + i);
        pose(px_[i], py_[i], pz_[i], 1, cBord[0] * fl, cBord[1] * fl, cBord[2] * fl, pt[i] * 1.6);
      }
      // les tetes de cometes pour le nuage (12)
      const com = new Float32Array(48), comV = new Float32Array(48);
      for (let i = 0; i < 12; i++) {
        const h = tetes[i];
        if (!h) continue;
        com[i * 4] = h[0]; com[i * 4 + 1] = h[1]; com[i * 4 + 2] = h[2]; com[i * 4 + 3] = 0.7 + 0.6 * agitLisse;
        comV[i * 4] = h[3]; comV[i * 4 + 1] = h[4]; comV[i * 4 + 2] = h[5]; comV[i * 4 + 3] = 0.5 + 0.5 * agitLisse;
      }
      return { n, vue, com, comV, lt };
    }

    function motsAnimer(dt) {
      if (!o.mots || !o.calqueMots) return;
      const calque = o.calqueMots, kx = W / racine.innerWidth;
      const cxCss = centre[0] / kx, cyCss = racine.innerHeight - centre[1] / kx, r = rayonPx / kx;
      if (enAttente.length && t >= prochainMot) {
        const w = enAttente.shift(), a = -Math.PI / 2 + (alea() - 0.5) * 1.6;
        const el = document.createElement('span'); el.textContent = w; calque.appendChild(el);
        mots.push({ el, x: Math.cos(a) * 0.75, y: Math.sin(a) * 0.6, vx: (alea() - 0.5) * 0.25, vy: -0.4 - alea() * 0.2, vie: 0 });
        prochainMot = t + 0.55;
      }
      for (let i = mots.length - 1; i >= 0; i--) {
        const m = mots[i];
        m.vie += dt * 0.36; m.x += m.vx * dt * 0.8; m.y += m.vy * dt * 0.8;
        if (m.vie >= 1) { m.el.remove(); mots.splice(i, 1); continue; }
        m.el.style.transform = 'translate(' + (cxCss + m.x * r).toFixed(1) + 'px,' + (cyCss + m.y * r).toFixed(1) + 'px) translate(-50%,-50%)';
        m.el.style.opacity = (0.9 * Math.sin(Math.PI * m.vie)).toFixed(3);
        m.el.style.fontSize = Math.max(13, r / 9).toFixed(0) + 'px';
      }
    }

    // la souris vue depuis l'orbe : le rayon de la camera qui passe sous le curseur
    function rayonSouris(vue, R, cssX, cssY) {
      const kx = W / racine.innerWidth, ky = H / racine.innerHeight;
      const qx = (cssX * kx - centre[0]) / R, qy = ((racine.innerHeight - cssY) * ky - centre[1]) / R;
      const fois = (x, y, z) => [vue[0] * x + vue[3] * y + vue[6] * z, vue[1] * x + vue[4] * y + vue[7] * z, vue[2] * x + vue[5] * y + vue[8] * z];
      const l = Math.hypot(qx, qy, CAM);
      return { ro: fois(0, 0, CAM), rd: fois(qx / l, qy / l, -CAM / l), axe: fois(0, 0, 1) };
    }
    const scal = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    let derniereVue = null, dernierR = 0;
    // une eruption qui jaillit vers un point de l'ecran (un bouton survole, un volet qui s'ouvre)
    function eclat(cssX, cssY, force) {
      if (!derniereVue || !dernierR) return;
      const { ro, rd, axe } = rayonSouris(derniereVue, dernierR, cssX, cssY);
      const tp = -scal(ro, axe) / (scal(rd, axe) || 1e-4);
      let x = ro[0] + rd[0] * tp, y = ro[1] + rd[1] * tp, z = ro[2] + rd[2] * tp;
      // un peu vers la camera, pour que l'arche se voie de face
      x += axe[0] * 0.35; y += axe[1] * 0.35; z += axe[2] * 0.35;
      const l = Math.hypot(x, y, z) || 1; x /= l; y /= l; z /= l;
      const ax = y * axe[2] - z * axe[1], ay = z * axe[0] - x * axe[2], az = x * axe[1] - y * axe[0], al = Math.hypot(ax, ay, az) || 1;
      if (eruptions.length >= NE) eruptions.shift();
      const f = Math.max(0.3, Math.min(1.5, force || 1));
      eruptions.push({ d: [x, y, z], p: [ax / al, ay / al, az / al], large: 0.3 + 0.15 * f, haut: 0.35 + 0.4 * f, vie: 0, duree: 1.3 + 0.5 * f, sens: alea() < 0.5 ? -1 : 1 });
    }
    function sourisDansOrbe(vue, R, dt) {
      const k = Math.min(1, dt * 60 * 0.08);
      let touche = 0;
      if (sourisLa) {
        const { ro, rd, axe } = rayonSouris(vue, R, sourisPx[0], sourisPx[1]);
        // la bulle : ou le curseur la touche
        const b = scal(ro, rd), h = b * b - (scal(ro, ro) - 1);
        if (h > 0) { const tt = -b - Math.sqrt(h); doigt = [ro[0] + rd[0] * tt, ro[1] + rd[1] * tt, ro[2] + rd[2] * tt]; touche = 1; }
        // la brume : le point sous le curseur, dans le plan de l'orbe face a la camera, et sa vitesse
        const tp = -scal(ro, axe) / (scal(rd, axe) || 1e-4);
        const p = [ro[0] + rd[0] * tp, ro[1] + rd[1] * tp, ro[2] + rd[2] * tp];
        if (pPrec && dt > 0) {
          const v = [p[0] - pPrec[0], p[1] - pPrec[1], p[2] - pPrec[2]], vl = Math.hypot(v[0], v[1], v[2]);
          if (vl > 1e-4) { sourisDir[0] = v[0] / vl; sourisDir[1] = v[1] / vl; sourisDir[2] = v[2] / vl; }
          brassage += (Math.min(1, vl / dt * 0.35) - brassage) * k;
        }
        pPrec = p; sourisPos[0] = p[0]; sourisPos[1] = p[1]; sourisPos[2] = p[2];
      } else { pPrec = null; brassage += (0 - brassage) * k; }
      toucher += (touche - toucher) * k;
      regard[0] += ((sourisLa ? sourisL[0] * 0.6 : 0) - regard[0]) * k * 0.5;
      regard[1] += ((sourisLa ? sourisL[1] * 0.4 : 0) - regard[1]) * k * 0.5;
    }

    // les briques : la passe de face, puis la passe du reflet (retournee sous le lac), avec leur profondeur
    function dessinerBriques(plaque, sim, lumOrbe, teinteLum, echA) {
      const ch = decor.chantier, { n, donnees, grille } = ch.ecrire(), sc = decor.scene, pr = P.briques, u = pr.u;
      gl.bindBuffer(gl.ARRAY_BUFFER, tamponB); gl.bufferSubData(gl.ARRAY_BUFFER, 0, donnees, 0, n * 28);
      // la forme des pierres du monument qui arrive : une ligne de texture par pierre, dans l'etage libre
      const nf = ch.prendreForme ? ch.prendreForme() : null;
      if (nf) {
        if (!texForme || texFormeK !== nf.K) {
          if (!texForme) texForme = gl.createTexture();
          gl.bindTexture(gl.TEXTURE_2D, texForme);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, nf.K, 2 * ch.N, 0, gl.RED, gl.UNSIGNED_BYTE, null);
          for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.NEAREST], [gl.TEXTURE_MAG_FILTER, gl.NEAREST], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
          texFormeK = nf.K;
        }
        gl.bindTexture(gl.TEXTURE_2D, texForme); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
        gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, nf.couche * ch.N, nf.K, nf.N, gl.RED, gl.UNSIGNED_BYTE, nf.r.subarray(0, nf.N * nf.K));
        gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
      }
      const ng = texForme ? grille : 0;
      gl.useProgram(pr.p);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, decor.signes || vide); gl.uniform1i(u.uGlyphes, 0);
      gl.uniform3fv(u.uCamP, sc.camera); gl.uniformMatrix3fv(u.uCamR, false, sc.axes); gl.uniform2f(u.uTan, sc.tan_h, sc.tan_v);
      gl.uniform2f(u.uRes, W, H); gl.uniform2f(u.uSouris, sourisL[0], sourisL[1]); gl.uniform4fv(u.uPlaque, plaque); gl.uniform1f(u.uFrame, frame);
      gl.uniform3fv(u.uVersLune, sc.lune); gl.uniform3fv(u.uOrbeM, sc.orbe); gl.uniform3fv(u.uTeinteLum, teinteLum);
      gl.uniform3fv(u.uMenthe, lin(MENTHE)); gl.uniform3fv(u.uTeinte, sim.lt);
      gl.uniform1f(u.uExpoBase, (decor.meta && decor.meta.base_force) || 1); gl.uniform1f(u.uLumOrbe, lumOrbe);
      gl.uniform1f(u.uT, t); gl.uniform1f(u.uPense, tourne); gl.uniform1f(u.uEchA, echA);
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, texForme || vide); gl.uniform1i(u.uForme, 1); gl.uniform1i(u.uN, ng);
      gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS); gl.disable(gl.CULL_FACE);
      gl.bindVertexArray(vaoB);
      for (const [c, miroir] of [[cibles.briques, 0], [cibles.reflet, 1]]) {
        gl.bindFramebuffer(gl.FRAMEBUFFER, c.f); gl.viewport(0, 0, c.w, c.h);
        gl.clearColor(0, 0, 0, 0); gl.clearDepth(1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.uniform1f(u.uMiroir, miroir);
        gl.drawArraysInstanced(gl.TRIANGLES, 0, ng ? 36 * ng * ng : 36, n);
      }
      gl.disable(gl.DEPTH_TEST); gl.bindVertexArray(null); gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.activeTexture(gl.TEXTURE0);
    }

    function dessiner(maintenant, manuel) {
      if (arret) return;
      if (!manuel) image = racine.requestAnimationFrame(dessiner);
      if (gl.isContextLost()) return;
      const dt = manuel ? 1 / 60 : avant === 0 ? 0.016 : Math.max(0, Math.min(0.05, (maintenant - avant) / 1000));
      const ecoule = manuel ? 16 : avant === 0 ? 16 : maintenant - avant;
      if (!manuel) avant = maintenant;
      if (calme && initialise && Math.floor(t * 2) === Math.floor((t + dt) * 2)) { t += dt; return; }
      t += dt; frame++;
      // la definition s'adapte a la machine (toutes les 2 s au plus)
      moyenne += (ecoule - moyenne) * 0.05;
      // pendant un vol de briques, on ne change pas la definition (changer de tampons fait un a-coup), sauf si c'est vraiment trop lourd
      const enVol = decor.chantier && decor.chantier.etat() === 'vol';
      if (t - dernierAjustement > 2 && frame > 90 && (!enVol || moyenne > 45)) {
        if (moyenne > 24 && qualite > 0.5) { qualite = Math.max(0.5, qualite * 0.85); dernierAjustement = t; }
        else if (moyenne < 13 && qualite < Math.min(1, o.qualite)) { qualite = Math.min(1, o.qualite, qualite * 1.08); dernierAjustement = t; }
      }
      mesurer();
      const plaque = ancrer();
      const sim = simuler(dt);
      if (!debutMs) debutMs = maintenant;
      fondu = Math.min(1, (maintenant - debutMs) / 1600);   // en temps reel (un onglet ralenti ne reste pas noir)
      const respire = 1 + 0.02 * Math.sin(t * 1.6) + 0.04 * amp;
      const R = rayonPx * respire;
      sourisDansOrbe(sim.vue, R, dt); derniereVue = sim.vue; dernierR = R;

      // 1. la scene (decor, nuage, bulle), melee a l'image precedente (sauf si l'orbe vient de bouger)
      const hNeuf = pp ? cibles.h1 : cibles.h0, hVieux = pp ? cibles.h0 : cibles.h1;
      const bouge = Math.hypot(centre[0] - centrePrec[0], centre[1] - centrePrec[1]);
      const memo = !histoire || calme ? 0 : 0.6 * Math.max(0, 1 - bouge / 1.5);
      centrePrec = centre.slice();
      if (decor.chantier) decor.chantier.avancer(dt, tourne); else if (decor.allee) decor.allee.avancer(dt, tourne);
      const lumOrbe = (decor.meta && decor.meta.lumiere_force || 1) * (0.85 + 0.25 * Math.sin(t * 1.6) + 0.6 * amp + 0.4 * pouls);
      const teinteLum = melange([1, 1, 1], sim.lt.map(v => v / Math.max(sim.lt[0], sim.lt[1], sim.lt[2], 0.001)), 0.65);
      const briquesOn = !!(decor.pret && decor.chantier && plaque && cibles.briques);
      const echA = briquesOn && cibles.briques.fl ? 1 : 0.002;
      if (briquesOn) dessinerBriques(plaque, sim, lumOrbe, teinteLum, echA);
      passe(P.scene, hNeuf, [['uBruit', bruit, gl.TEXTURE_3D], ['uBase', decor.base], ['uLum', decor.lum], ['uProf', decor.prof], ['uHist', hVieux.tx], ['uGlyphes', decor.signes || vide],
        ['uBriques', briquesOn ? cibles.briques.tx : vide], ['uReflet', briquesOn ? cibles.reflet.tx : vide]], u => {
        const sc = decor.scene;
        gl.uniform1f(u.uBriquesOn, briquesOn ? 1 : 0); gl.uniform1f(u.uEchA, echA);
        if (briquesOn) {
          gl.uniform1f(u.uPense, tourne);
          gl.uniform3fv(u.uCamP, sc.camera); gl.uniformMatrix3fv(u.uCamR, false, sc.axes); gl.uniform2f(u.uTan, sc.tan_h, sc.tan_v);
          gl.uniform3fv(u.uVersLune, sc.lune); gl.uniform3fv(u.uOrbeM, sc.orbe);
        }
        gl.uniform1f(u.uMemo, memo); gl.uniform1f(u.uEcart, ecart); gl.uniform1f(u.uTour, tour); gl.uniform1f(u.uRotC, rotC);
        gl.uniform4f(u.uDoigt, doigt[0], doigt[1], doigt[2], toucher); gl.uniform2f(u.uRegard, regard[0], regard[1]);
        gl.uniform4f(u.uSourisP, sourisPos[0], sourisPos[1], sourisPos[2], brassage);
        gl.uniform4f(u.uSourisV, sourisDir[0], sourisDir[1], sourisDir[2], 0.35 + 0.6 * brassage);
        gl.uniform2f(u.uRes, W, H); gl.uniform2f(u.uCentre, centre[0], centre[1]); gl.uniform2f(u.uSouris, sourisL[0], sourisL[1]);
        gl.uniform1f(u.uRayon, R); gl.uniform1f(u.uT, t); gl.uniform1f(u.uAgit, agitLisse); gl.uniform1f(u.uAmp, amp);
        gl.uniform1f(u.uPouls, pouls); gl.uniform1f(u.uTourne, tourne); gl.uniform1f(u.uAnneau, anneau); gl.uniform1f(u.uEcoute, ecoute);
        gl.uniform1f(u.uNuage, decor.pret ? 0.22 : 1.0); gl.uniform1f(u.uFrame, frame);
        gl.uniform3fv(u.uTeinte, sim.lt); gl.uniform3fv(u.uMenthe, lin(MENTHE));
        gl.uniformMatrix3fv(u.uVue, false, sim.vue);
        gl.uniform4fv(u.uCom, sim.com); gl.uniform4fv(u.uComV, sim.comV);
        gl.uniform1f(u.uDecor, decor.pret ? 1 : 0);
        if (plaque) gl.uniform4fv(u.uPlaque, plaque);
        gl.uniform1f(u.uLumOrbe, lumOrbe); gl.uniform1f(u.uExpoBase, (decor.meta && decor.meta.base_force) || 1);
        gl.uniform3fv(u.uTeinteLum, teinteLum);
      });
      gl.bindFramebuffer(gl.READ_FRAMEBUFFER, hNeuf.f); gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, cibles.scene.f);
      gl.blitFramebuffer(0, 0, W, H, 0, 0, W, H, gl.COLOR_BUFFER_BIT, gl.NEAREST);
      gl.bindFramebuffer(gl.READ_FRAMEBUFFER, null); gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, null);
      pp ^= 1; histoire = true;
      // 2. les points, en lumiere ajoutee (pas dans l'historique : ils ne laissent pas de trainee)
      gl.bindBuffer(gl.ARRAY_BUFFER, tampon);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, donnees, 0, sim.n * 8);
      gl.bindFramebuffer(gl.FRAMEBUFFER, cibles.scene.f); gl.viewport(0, 0, W, H);
      gl.useProgram(P.points.p);
      gl.uniformMatrix3fv(P.points.u.uVue, false, sim.vue); gl.uniform2f(P.points.u.uCentre, centre[0], centre[1]);
      gl.uniform2f(P.points.u.uRes, W, H); gl.uniform1f(P.points.u.uRayon, R); gl.uniform1f(P.points.u.uEchelle, Math.max(0.6, R / 170));
      gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);
      gl.bindVertexArray(vao); gl.drawArrays(gl.POINTS, 0, sim.n);
      gl.disable(gl.BLEND);
      // 3. la lueur : ce qui brille, adouci a deux echelles
      const sc = cibles.scene, a1 = cibles.a1, b1 = cibles.b1, a2 = cibles.a2, b2 = cibles.b2;
      passe(P.clair, a1, [['uTex', sc.tx]], u => { gl.uniform2f(u.uTexel, 1 / sc.w, 1 / sc.h); gl.uniform1f(u.uSeuil, 0.8); });
      passe(P.flou, b1, [['uTex', a1.tx]], u => gl.uniform2f(u.uDir, 1.4 / a1.w, 0));
      passe(P.flou, a1, [['uTex', b1.tx]], u => gl.uniform2f(u.uDir, 0, 1.4 / a1.h));
      passe(P.clair, a2, [['uTex', a1.tx]], u => { gl.uniform2f(u.uTexel, 1 / a1.w, 1 / a1.h); gl.uniform1f(u.uSeuil, 0.0); });
      passe(P.flou, b2, [['uTex', a2.tx]], u => gl.uniform2f(u.uDir, 1.6 / a2.w, 0));
      passe(P.flou, a2, [['uTex', b2.tx]], u => gl.uniform2f(u.uDir, 0, 1.6 / a2.h));
      // 4. l'image finale
      passe(P.final, null, [['uScene', sc.tx], ['uB1', a1.tx], ['uB2', a2.tx]], u => {
        gl.uniform1f(u.uT, t); gl.uniform1f(u.uFondu, fondu); gl.uniform1f(u.uExpo, 1.15);
      });
      motsAnimer(dt);
    }

    canvas.addEventListener('webglcontextlost', ev => { ev.preventDefault(); }, false);
    image = racine.requestAnimationFrame(dessiner);

    return {
      mode(m) { mode = MODES.includes(m) ? m : 'repos'; return this; },
      couleur() { return teinte.map(Math.round); },
      etat() { return mode; },
      niveau(f) { micro = typeof f === 'function' ? f : null; return this; },
      mots(liste) { for (const w of (liste || []).slice(0, 6)) enAttente.push(String(w).slice(0, 24)); return this; },
      eclat(x, y, force) { eclat(x, y, force); return this; },
      // pour les captures (onglet en arriere-plan, ou les images sont ralenties) : n images d'affilee, 1/60 s chacune
      avancer(n) { for (let i = 0; i < (n || 1); i++) { debutMs = debutMs || 1; dessiner(debutMs + 1e6, true); } return this; },
      allee() { return decor.allee; },
      // un nouveau sujet : l'allee (ou le monument d'avant) se defait et forme un autre monument ; former('zeus') pour en choisir un
      nouveauSujet() { return decor.chantier ? decor.chantier.nouveauSujet() : null; },
      chantier() { return decor.chantier; },
      qualite() { return { qualite, largeur: W, hauteur: H, image_ms: Math.round(moyenne * 10) / 10, hdr }; },
      stop() { arret = true; racine.cancelAnimationFrame(image); for (const m of mots) m.el.remove(); liberer(); },
    };
  }

  ArchiOrbe.MODES = MODES;
  ArchiOrbe.TEINTES = TEINTES;
  racine.ArchiOrbe = ArchiOrbe;
})(typeof window !== 'undefined' ? window : globalThis);
