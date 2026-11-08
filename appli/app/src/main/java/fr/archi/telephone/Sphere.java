package fr.archi.telephone;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.os.SystemClock;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.View;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

/**
 * La sphere d'Archi : ~950 points lumineux dans une bulle holographique verte.
 * Repos = respire ; ecoute = ondes ; reflechit = tourbillon ; parle = egaliseur ;
 * quand Archi parle d'un sujet, les points dessinent la forme du sujet (engrenages, cellules, coeur...)
 * et les mots-cles montent puis s'effacent. Meme dessin que la maquette v9.
 */
public class Sphere extends View {
    public interface Niveau { float niveau(); }   // 0..1, volume du micro pendant l'ecoute

    private static final int N = 950, NL = 180, NC = 60, RS = 150; // RS : rayon de l'image d'echantillonnage
    private static final String[] SUJETS = {"meca", "bio", "maths", "argent", "personne", "animaux", "meteo",
            "lieu", "agenda", "musique", "sante", "doc"};

    private final float[] px = new float[N], py = new float[N], hx = new float[N], hy = new float[N],
            ps = new float[N], ph = new float[N], pu = new float[N], pe = new float[N], pdr = new float[N];
    private final int[] pg = new int[N];
    private final Random hasard = new Random();
    private final Paint point = new Paint(), trait = new Paint(Paint.ANTI_ALIAS_FLAG), fondBulle = new Paint(Paint.ANTI_ALIAS_FLAG),
            texte = new Paint(Paint.ANTI_ALIAS_FLAG), dessin = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path chemin = new Path();
    private final Bitmap img = Bitmap.createBitmap(2 * RS, 2 * RS, Bitmap.Config.ALPHA_8);
    private final Canvas toile = new Canvas(img);
    private final int[] pixels = new int[4 * RS * RS];

    private String mode = "repos", nomDocument = "";
    private float t = 0, amp = 0, debutCle = 0, densite = 1;
    private int cle = 0;
    private float[][] cibles;
    private long avant = 0;
    private boolean initialise;
    private Niveau micro;

    private static class Mot { String w; float x, y, vx, vy, vie; }
    private static class Bulle { float x, y, r, vie; }
    private final List<Mot> mots = new ArrayList<>();
    private final List<Bulle> bulles = new ArrayList<>();
    private final List<String> motsEnAttente = new ArrayList<>();
    private float prochainMot = 0;

    public Sphere(Context c) { super(c); init(c); }
    public Sphere(Context c, AttributeSet a) { super(c, a); init(c); }

    private void init(Context c) {
        densite = c.getResources().getDisplayMetrics().density;
        for (int i = 0; i < N; i++) {
            double a = hasard.nextDouble() * 7, r = Math.sqrt(hasard.nextDouble()) * 0.92;
            hx[i] = (float) (Math.cos(a) * r); hy[i] = (float) (Math.sin(a) * r);
            ps[i] = 0.6f + hasard.nextFloat() * 1.1f; ph[i] = hasard.nextFloat() * 7; pu[i] = hasard.nextFloat();
            pe[i] = hasard.nextFloat() - 0.5f; pg[i] = hasard.nextFloat() < 0.68f ? 0 : 1; pdr[i] = (hasard.nextFloat() - 0.5f) * 0.05f;
        }
        point.setColor(Color.rgb(191, 247, 220));
        trait.setStyle(Paint.Style.STROKE);
        texte.setTextAlign(Paint.Align.CENTER);
        dessin.setColor(Color.WHITE);
        dessin.setStrokeJoin(Paint.Join.ROUND);
        dessin.setStrokeCap(Paint.Cap.ROUND);
        dessin.setTextAlign(Paint.Align.CENTER);
    }

    // ---------------- commandes ----------------
    public void setMicro(Niveau n) { micro = n; }

    /** mode : repos, ecoute, reflechit, parle, ou un sujet (meca, bio, maths...). */
    public void setMode(String m) {
        if (m == null || m.isEmpty()) m = "repos";
        if (m.equals(mode)) return;
        mode = m;
        cle = 0; debutCle = t;
        cibles = formeEchantillonnee();
        invalidate();
    }

    public String getMode() { return mode; }

    public static boolean estSujet(String s) {
        for (String x : SUJETS) if (x.equals(s)) return true;
        return false;
    }

    public void setDocument(String nom) { nomDocument = nom == null ? "" : nom; }

    // ---- le document recu : une petite bulle sur le bord de la sphere, qui derive tres lentement, a toucher pour l'ouvrir ----
    public interface SurDocument { void ouvrir(java.io.File f); }
    private java.io.File docFichier;
    private String docNom = "";
    private float docAngle = -0.7f, docX = -1000, docY = -1000, docRayon = 0, docApparu = -1, docPresse = -1;
    private boolean docEnfonce;
    private SurDocument surDocument, surDocumentLong;
    private boolean docLongDeclenche;
    private final Runnable appuiLongDoc = () -> {
        if (!docEnfonce || docFichier == null) return;
        docEnfonce = false;
        docLongDeclenche = true;
        performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS);
        invalidate();
        if (surDocumentLong != null) surDocumentLong.ouvrir(docFichier);
    };

    public void setSurDocument(SurDocument s) { surDocument = s; }
    /** Appui long sur la bulle : le menu (partager, ranger, supprimer). */
    public void setSurDocumentLong(SurDocument s) { surDocumentLong = s; }

    /** Le document disponible (null = aucun). La bulle apparait en fondu et reste tant qu'un document existe. */
    public void setDocumentFichier(java.io.File f) {
        if (f == null || !f.isFile()) { docFichier = null; docNom = ""; invalidate(); return; }
        boolean nouveau = docFichier == null || !f.equals(docFichier);
        docFichier = f;
        docNom = f.getName();
        if (nouveau) { docApparu = t; docAngle = -0.7f; }
        invalidate();
    }

    public java.io.File getDocumentFichier() { return docFichier; }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        if (docFichier != null) {
            float dx = e.getX() - docX, dy = e.getY() - docY, zone = docRayon * 1.9f;
            boolean dessus = dx * dx + dy * dy <= zone * zone;
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    if (dessus) {
                        docEnfonce = true; docLongDeclenche = false; docPresse = t; invalidate();
                        removeCallbacks(appuiLongDoc);
                        postDelayed(appuiLongDoc, android.view.ViewConfiguration.getLongPressTimeout());
                        return true;
                    }
                    break;
                case MotionEvent.ACTION_UP:
                    removeCallbacks(appuiLongDoc);
                    if (docLongDeclenche) { docLongDeclenche = false; return true; }
                    if (docEnfonce) {
                        docEnfonce = false;
                        if (dessus && surDocument != null) surDocument.ouvrir(docFichier);
                        return true;
                    }
                    break;
                case MotionEvent.ACTION_CANCEL:
                    removeCallbacks(appuiLongDoc);
                    docLongDeclenche = false;
                    if (docEnfonce) { docEnfonce = false; return true; }
                    break;
                default:
                    if (docEnfonce) return true;
            }
        }
        return super.onTouchEvent(e);
    }

    private String absorbeNom = null;
    private float absorbeDebut = 0;

    /** Une piece jointe arrive : son icone monte du bas de l'ecran et entre dans la sphere. */
    public void absorber(String nom) {
        absorbeNom = nom == null ? "fichier" : nom;
        absorbeDebut = t;
        invalidate();
    }

    private float ecartMots = 1;

    /** Les mots-cles apparaissent un par un, etales sur la duree de la voix, derivent puis s'effacent en fondu. */
    public void montrerMots(List<String> l, long dureeMs) {
        motsEnAttente.clear();
        if (l != null) for (String w : l) if (w != null && !w.trim().isEmpty()) motsEnAttente.add(w.trim());
        float duree = dureeMs > 0 ? dureeMs / 1000f : 6f;
        ecartMots = Math.max(0.9f, Math.min(4f, (duree - 2f) / Math.max(1, motsEnAttente.size())));
        prochainMot = t + 0.4f;
    }

    // ---------------- outils ----------------
    private static float lisse(float a, float b, float v) {
        v = Math.min(1, Math.max(0, (v - a) / (b - a)));
        return v * v * (3 - 2 * v);
    }

    private static float bruit(float a, float b) {
        return (float) (Math.sin(a * 3.1 + b) * 0.5 + Math.sin(a * 5.3 - b * 1.7) * 0.3 + Math.sin(a * 8.7 + b * 2.3) * 0.2);
    }

    /** Meme bruit, mais qui boucle parfaitement sur un tour complet (pas de cassure sur le cote droit de la bulle). */
    private static float bruitRond(float a, float b) {
        return (float) (Math.sin(a * 3 + b) * 0.5 + Math.sin(a * 5 - b * 1.7) * 0.3 + Math.sin(a * 9 + b * 2.3) * 0.2);
    }

    private boolean estSujet() { return estSujet(mode); }

    private float rythme() {
        switch (mode) {
            case "maths": case "argent": case "musique": return 2.2f;
            case "meteo": return 2.4f;
            case "animaux": return 3f;
            default: return 0;
        }
    }

    // ---------------- formes dessinees puis echantillonnees ----------------
    private float[][] formeEchantillonnee() {
        String m = mode;
        if (!(m.equals("maths") || m.equals("argent") || m.equals("musique") || m.equals("animaux") || m.equals("meteo")
                || m.equals("lieu") || m.equals("agenda") || m.equals("sante") || m.equals("doc"))) return null;
        img.eraseColor(0);
        final float R = RS;
        dessin.setStyle(Paint.Style.STROKE);
        dessin.setStrokeWidth(R * 0.0625f);
        switch (m) {
            case "maths": symboles(new String[]{"x²", "√3", "π", "3,14", "Σ", "∫", "Δ", "∞", "e"}, 0.30f); break;
            case "argent": symboles(new String[]{"€", "$", "₿", "£", "¥", "%"}, 0.41f); break;
            case "musique": symboles(new String[]{"♪", "♫", "♩", "♬"}, 0.54f); break;
            case "animaux": {
                int e = cle % 3;
                if (e == 0) loup(R); else if (e == 1) oiseau(R); else chat(R);
                break;
            }
            case "meteo": {
                int e = cle % 4;
                if (e == 0 || e == 3) nuage(R, 0, 0, 1.2f);
                if (e == 1) soleil(R, 1, 1, 1.4f);
                if (e == 2) { soleil(R, 1.2f, 0.75f, 0.9f); nuage(R, -0.08f, 0.15f, 1); }
                break;
            }
            case "lieu":
                chemin.reset();
                chemin.arcTo(new RectF(R - R * 0.38f, R * 0.8f - R * 0.38f, R + R * 0.38f, R * 0.8f + R * 0.38f), 153, 234);
                chemin.lineTo(R, R * 1.6f); chemin.close();
                toile.drawPath(chemin, dessin);
                toile.drawCircle(R, R * 0.8f, R * 0.13f, dessin);
                toile.drawOval(new RectF(R - R * 0.45f, R * 1.52f, R + R * 0.45f, R * 1.72f), dessin);
                break;
            case "agenda":
                chemin.reset();
                chemin.moveTo(R, R * 0.7f);
                chemin.quadTo(R * 0.7f, R * 0.55f, R * 0.35f, R * 0.68f); chemin.lineTo(R * 0.35f, R * 1.42f);
                chemin.quadTo(R * 0.7f, R * 1.3f, R, R * 1.45f); chemin.quadTo(R * 1.3f, R * 1.3f, R * 1.65f, R * 1.42f);
                chemin.lineTo(R * 1.65f, R * 0.68f); chemin.quadTo(R * 1.3f, R * 0.55f, R, R * 0.7f); chemin.lineTo(R, R * 1.45f);
                toile.drawPath(chemin, dessin);
                dessin.setStrokeWidth(R * 0.036f);
                for (int i = 0; i < 3; i++) {
                    float y = R * (0.9f + i * 0.15f);
                    toile.drawLine(R * 0.48f, y, R * 0.86f, y, dessin);
                    toile.drawLine(R * 1.14f, y, R * 1.52f, y, dessin);
                }
                break;
            case "sante":
                chemin.reset();
                chemin.moveTo(R, R * 1.5f);
                chemin.cubicTo(R * 0.2f, R * 1.0f, R * 0.45f, R * 0.45f, R, R * 0.82f);
                chemin.cubicTo(R * 1.55f, R * 0.45f, R * 1.8f, R * 1.0f, R, R * 1.5f);
                toile.drawPath(chemin, dessin);
                break;
            case "doc":
                chemin.reset();
                chemin.moveTo(R * 0.45f, R * 0.6f); chemin.lineTo(R * 0.85f, R * 0.6f); chemin.lineTo(R * 0.97f, R * 0.75f);
                chemin.lineTo(R * 1.55f, R * 0.75f); chemin.lineTo(R * 1.55f, R * 1.45f); chemin.lineTo(R * 0.45f, R * 1.45f); chemin.close();
                toile.drawPath(chemin, dessin);
                toile.drawLine(R * 0.45f, R * 0.9f, R * 1.55f, R * 0.9f, dessin);
                break;
            default: break;
        }
        // echantillonnage : chaque point garde sa place relative (pu) d'une forme a l'autre
        img.getPixels(pixels, 0, 2 * RS, 0, 0, 2 * RS, 2 * RS);
        int compte = 0;
        int[] idx = new int[pixels.length / 9 + 4];
        for (int y = 0; y < 2 * RS; y += 2)
            for (int x = 0; x < 2 * RS; x += 2)
                if ((pixels[y * 2 * RS + x] >>> 24) > 120 && compte < idx.length) idx[compte++] = y * 2 * RS + x;
        if (compte == 0) return null;
        float[][] r = new float[N][2];
        for (int i = 0; i < N; i++) {
            int k = idx[Math.min(compte - 1, (int) (pu[i] * compte))];
            r[i][0] = ((k % (2 * RS)) - R) / R;
            r[i][1] = ((k / (2 * RS)) - R) / R;
        }
        return r;
    }

    private void symboles(String[] l, float taille) {
        dessin.setStyle(Paint.Style.FILL);
        dessin.setTextSize(RS * taille);
        for (int i = 0; i < 5; i++) {
            double a = i / 5.0 * 6.28 + cle * 0.9;
            float rr = RS * (0.25f + 0.3f * ((i * 37) % 10) / 10f);
            float x = RS + (float) Math.cos(a) * rr, y = RS + (float) Math.sin(a) * rr;
            Paint.FontMetrics fm = dessin.getFontMetrics();
            toile.drawText(l[(i + cle) % l.length], x, y - (fm.ascent + fm.descent) / 2, dessin);
        }
    }

    private void arc(float cx, float cy, float r, float debutDeg, float balayageDeg) {
        chemin.arcTo(new RectF(cx - r, cy - r, cx + r, cy + r), debutDeg, balayageDeg);
    }

    private void nuage(float R, float dx, float dy, float k) {
        chemin.reset();
        arc(R * (0.75f + dx), R * (1.0f + dy), R * 0.24f * k, 90, 180);
        arc(R * (1.0f + dx), R * (0.83f + dy), R * 0.3f * k, 189, 162);
        arc(R * (1.3f + dx), R * (1.02f + dy), R * 0.22f * k, 270, 180);
        chemin.close();
        toile.drawPath(chemin, dessin);
    }

    private void soleil(float R, float cx, float cy, float k) {
        toile.drawCircle(R * cx, R * cy, R * 0.22f * k, dessin);
        for (int i = 0; i < 8; i++) {
            double a = i / 8.0 * 6.28;
            toile.drawLine(R * cx + (float) Math.cos(a) * R * 0.32f * k, R * cy + (float) Math.sin(a) * R * 0.32f * k,
                    R * cx + (float) Math.cos(a) * R * 0.45f * k, R * cy + (float) Math.sin(a) * R * 0.45f * k, dessin);
        }
    }

    private void ovale(float cx, float cy, float rx, float ry, float rotRad, boolean plein) {
        toile.save();
        toile.rotate((float) Math.toDegrees(rotRad), cx, cy);
        dessin.setStyle(plein ? Paint.Style.FILL : Paint.Style.STROKE);
        toile.drawOval(new RectF(cx - rx, cy - ry, cx + rx, cy + ry), dessin);
        dessin.setStyle(Paint.Style.STROKE);
        toile.restore();
    }

    /** Loup qui hurle, de profil, museau vers le ciel (dessin original). */
    private void ligne(float... p) {
        chemin.reset();
        chemin.moveTo(RS * p[0], RS * p[1]);
        for (int i = 2; i + 1 < p.length; i += 2) chemin.lineTo(RS * p[i], RS * p[i + 1]);
        toile.drawPath(chemin, dessin);
    }

    private void loup(float R) {
        chemin.reset();
        chemin.moveTo(R * 0.48f, R * 0.22f);
        chemin.quadTo(R * 0.74f, R * 0.32f, R * 0.9f, R * 0.5f);
        chemin.quadTo(R * 0.97f, R * 0.6f, R * 1.08f, R * 0.66f);
        float[] nuque = {1.18f, 0.66f, 1.48f, 0.84f, 1.27f, 0.95f, 1.33f, 1.08f, 1.4f, 1.1f, 1.42f, 1.22f, 1.5f, 1.27f, 1.52f, 1.4f, 1.6f, 1.46f};
        for (int i = 0; i < nuque.length; i += 2) chemin.lineTo(R * nuque[i], R * nuque[i + 1]);
        chemin.quadTo(R * 1.68f, R * 1.62f, R * 1.7f, R * 1.8f);
        toile.drawPath(chemin, dessin);
        chemin.reset();
        chemin.moveTo(R * 0.46f, R * 0.27f); chemin.quadTo(R * 0.62f, R * 0.42f, R * 0.8f, R * 0.6f);
        toile.drawPath(chemin, dessin);
        chemin.reset();
        chemin.moveTo(R * 0.8f, R * 0.6f); chemin.lineTo(R * 0.45f, R * 0.5f); chemin.quadTo(R * 0.44f, R * 0.57f, R * 0.56f, R * 0.64f);
        float[] gorge = {0.66f, 0.74f, 0.62f, 0.8f, 0.72f, 0.88f, 0.68f, 0.98f, 0.77f, 1.06f, 0.72f, 1.18f, 0.8f, 1.26f};
        for (int i = 0; i < gorge.length; i += 2) chemin.lineTo(R * gorge[i], R * gorge[i + 1]);
        chemin.quadTo(R * 0.74f, R * 1.5f, R * 0.8f, R * 1.8f);
        toile.drawPath(chemin, dessin);
        ligne(0.86f, 0.66f, 0.96f, 0.8f, 0.93f, 0.84f, 1.05f, 0.94f, 1.02f, 0.99f, 1.14f, 1.06f);
        chemin.reset();
        chemin.moveTo(R * 1.0f, R * 1.2f); chemin.quadTo(R * 1.1f, R * 1.32f, R * 1.22f, R * 1.36f);
        chemin.moveTo(R * 0.95f, R * 1.42f); chemin.quadTo(R * 1.08f, R * 1.55f, R * 1.25f, R * 1.58f);
        chemin.moveTo(R * 0.95f, R * 0.66f); chemin.quadTo(R * 1.0f, R * 0.7f, R * 1.06f, R * 0.71f);
        toile.drawPath(chemin, dessin);
        ovale(R * 0.48f, R * 0.23f, R * 0.045f, R * 0.035f, -0.5f, true);
    }

    private void chat(float R) {
        toile.drawCircle(R, R * 1.05f, R * 0.34f, dessin);
        for (int s = -1; s <= 1; s += 2) {
            chemin.reset();
            chemin.moveTo(R + s * R * 0.3f, R * 0.88f); chemin.lineTo(R + s * R * 0.34f, R * 0.5f); chemin.lineTo(R + s * R * 0.08f, R * 0.73f);
            toile.drawPath(chemin, dessin);
            ovale(R + s * R * 0.13f, R * 0.98f, R * 0.045f, R * 0.07f, 0, true);
            for (int k = -1; k <= 1; k++)
                toile.drawLine(R + s * R * 0.12f, R * (1.17f + k * 0.04f), R + s * R * 0.5f, R * (1.13f + k * 0.09f), dessin);
        }
        chemin.reset();
        chemin.moveTo(R - R * 0.05f, R * 1.1f); chemin.lineTo(R + R * 0.05f, R * 1.1f); chemin.lineTo(R, R * 1.16f); chemin.close();
        dessin.setStyle(Paint.Style.FILL);
        toile.drawPath(chemin, dessin);
        dessin.setStyle(Paint.Style.STROKE);
    }

    /** Oiseau pose sur une branche, de profil. */
    private void oiseau(float R) {
        toile.drawCircle(R * 1.18f, R * 0.72f, R * 0.14f, dessin);
        chemin.reset();
        chemin.moveTo(R * 1.31f, R * 0.68f); chemin.lineTo(R * 1.48f, R * 0.73f); chemin.lineTo(R * 1.31f, R * 0.78f);
        toile.drawPath(chemin, dessin);
        chemin.reset();
        chemin.moveTo(R * 1.06f, R * 0.8f); chemin.quadTo(R * 0.7f, R * 0.85f, R * 0.62f, R * 1.15f);
        chemin.lineTo(R * 0.38f, R * 1.42f); chemin.lineTo(R * 0.58f, R * 1.38f);
        chemin.quadTo(R * 0.95f, R * 1.38f, R * 1.22f, R * 1.12f); chemin.quadTo(R * 1.3f, R * 0.95f, R * 1.22f, R * 0.85f);
        toile.drawPath(chemin, dessin);
        chemin.reset();
        chemin.moveTo(R * 0.82f, R); chemin.quadTo(R * 0.75f, R * 1.18f, R * 0.55f, R * 1.3f);
        toile.drawPath(chemin, dessin);
        toile.drawLine(R * 0.95f, R * 1.33f, R * 0.92f, R * 1.5f, dessin);
        toile.drawLine(R * 1.08f, R * 1.28f, R * 1.07f, R * 1.5f, dessin);
        toile.drawLine(R * 0.5f, R * 1.52f, R * 1.55f, R * 1.5f, dessin);
        ovale(R * 1.22f, R * 0.69f, R * 0.025f, R * 0.025f, 0, true);
    }

    // ---------------- formes calculees (stables) ----------------
    private final float[] o2 = new float[2];

    private float[] rouage(int i) {
        int g = pg[i];
        float dn = g == 1 ? 7 : 10, r = g == 1 ? 0.3f : 0.46f, cx = g == 1 ? 0.42f : -0.12f, cy = g == 1 ? 0.38f : -0.12f;
        float rot = g == 1 ? -t * 0.6f * 10 / 7 : t * 0.6f, a, rr;
        if (pu[i] < 0.78f) {
            a = rot + pu[i] / 0.78f * 6.28f;
            float q = ((a - rot) / 6.28f * dn * 4) % 4;
            rr = r * (q < 2 ? 1 : 0.8f);
        } else {
            a = rot + (pu[i] - 0.78f) / 0.22f * 6.28f;
            rr = r * 0.3f;
        }
        o2[0] = cx + (float) Math.cos(a) * (rr + pdr[i] * 0.3f);
        o2[1] = cy + (float) Math.sin(a) * (rr + pdr[i] * 0.3f);
        return o2;
    }

    /** La bouche : un egaliseur seul, 17 barres en amande qui montent et descendent avec la voix. */
    private static final int NB = 17;

    private float[] levres(int i, int total, float a, float y0, float k) {
        int col = i % NB, par = total / NB;
        float s = Math.min(1f, (i / NB) / (float) Math.max(1, par - 1)), u = (col / (float) (NB - 1)) * 2 - 1;
        float tp = (float) Math.pow(Math.max(0, 1 - u * u), 0.75);
        float niv = 0.25f + 0.75f * Math.abs((float) (Math.sin(t * 11 + col * 1.7) * Math.sin(t * 4.3 + col * 0.6)));
        float h = Math.max(0.012f * k, (0.03f + 0.24f * a) * k * tp * niv);
        o2[0] = u * 0.48f * k * 0.86f + pe[i % N] * 0.012f * k;
        o2[1] = y0 + (s * 2 - 1) * h;
        return o2;
    }

    /** Trace du battement (electrocardiogramme) : plat, petite bosse, pic, creux, retour. */
    private static float ecg(float u) {
        float d = u - 0.5f;
        return (float) (-0.05 * Math.exp(-(d + 0.16) * (d + 0.16) / 0.002) - 0.5 * Math.exp(-d * d / 0.0004)
                + 0.22 * Math.exp(-(d - 0.035) * (d - 0.035) / 0.0005) - 0.08 * Math.exp(-(d - 0.18) * (d - 0.18) / 0.003));
    }

    private float[] cellule(int idx) {
        int c = idx / NC, j = idx % NC;
        float decal = c == 0 ? 0 : 0.48f, phase = (t * 0.06f + decal) % 1, yc = 0.62f - phase * 1.25f;
        float env = Math.min(1, (float) Math.sin(Math.PI * phase) * 2.5f), r = 0.16f * env, xc;
        if (c == 0) {
            float d = (t % 7) / 7, s = lisse(0.25f, 0.6f, d) * (1 - lisse(0.85f, 1, d));
            xc = -0.3f + (j % 2 == 1 ? 1 : -1) * s * r * 1.1f;
        } else {
            float ecart = 0.5f + 0.5f * (float) Math.cos(t * 1.4);
            xc = 0.3f + (c == 1 ? -1 : 1) * r * (1 + 0.9f * ecart);
        }
        float a, rr;
        if (j < 12) { a = j / 12f * 6.28f + t * 1.5f; rr = r * 0.3f; }
        else { a = (j - 12) / (float) (NC - 12) * 6.28f + t * 0.4f; rr = r * (1 + 0.07f * (float) Math.sin(3 * a + t * 3)); }
        o2[0] = xc + (float) Math.cos(a) * rr;
        o2[1] = yc + (float) Math.sin(a) * rr;
        return o2;
    }

    private float[] seg(float ax, float ay, float bx, float by, float q, float ep, float e) {
        float dx = bx - ax, dy = by - ay, L = (float) Math.hypot(dx, dy);
        if (L == 0) L = 1;
        o2[0] = ax + dx * q - dy / L * ep * e;
        o2[1] = ay + dy * q + dx / L * ep * e;
        return o2;
    }

    private float[] cercle(float cx, float cy, float r, float q) {
        o2[0] = cx + (float) Math.cos(q * 6.28) * r;
        o2[1] = cy + (float) Math.sin(q * 6.28) * r;
        return o2;
    }

    private float[] personne(int i) {
        float T = t % 8, u = pu[i];
        boolean deux = T < 3.6f;
        float cx, k, w, nod = 0;
        if (deux) {
            boolean g = u < 0.5f;
            cx = g ? -0.42f : 0.42f; k = 0.72f; w = (u * 2) % 1;
            nod = 0.04f * (float) Math.sin(t * 4 + (g ? 0 : Math.PI)) * (Math.sin(t * 1.5 + (g ? 0 : 3)) > 0 ? 1 : 0.2f);
        } else { cx = -0.08f; k = 0.95f; w = u; }
        float hyy0 = -0.3f * k + nod;
        if (deux) {
            if (w < 0.4f) return cercle(cx, hyy0, 0.2f * k, w / 0.4f);
            double a = Math.PI * (1.05 + 0.9 * (w - 0.4) / 0.6);
            o2[0] = cx + (float) Math.cos(a) * 0.42f * k; o2[1] = 0.48f * k + (float) Math.sin(a) * 0.42f * k;
            return o2;
        }
        if (w < 0.28f) return cercle(cx, hyy0, 0.2f * k, w / 0.28f);
        if (w < 0.62f) {
            double a = Math.PI * (1.05 + 0.9 * (w - 0.28) / 0.34);
            o2[0] = cx + (float) Math.cos(a) * 0.42f * k; o2[1] = 0.48f * k + (float) Math.sin(a) * 0.42f * k;
            return o2;
        }
        float sx = cx + 0.3f * k, sy = 0.14f * k, ex = sx + 0.2f * k, ey = sy - 0.2f * k, f = (float) Math.sin(t * 8) * 0.4f;
        float mx = ex + 0.24f * k * (float) Math.sin(f), my = ey - 0.24f * k * (float) Math.cos(f);
        if (w < 0.72f) return seg(sx, sy, ex, ey, (w - 0.62f) / 0.1f, 0.05f * k, pe[i]);
        if (w < 0.82f) return seg(ex, ey, mx, my, (w - 0.72f) / 0.1f, 0.045f * k, pe[i]);
        float dir = (float) Math.atan2(my - ey, mx - ex), pcx = mx + (float) Math.cos(dir) * 0.05f * k, pcy = my + (float) Math.sin(dir) * 0.05f * k;
        float q = (w - 0.82f) / 0.18f;
        if (q < 0.3f) return cercle(pcx, pcy, 0.065f * k * (0.6f + 0.4f * Math.abs(pe[i] * 2)), q / 0.3f);
        float qq = (q - 0.3f) / 0.7f * 5;
        int fi = Math.min(4, (int) qq);
        float s = qq - fi;
        float[] angles = {-1.25f, -0.45f, -0.12f, 0.2f, 0.52f}, longueurs = {0.08f, 0.11f, 0.12f, 0.11f, 0.085f};
        float ang = dir + angles[fi], L = longueurs[fi] * k;
        float bx = pcx + (float) Math.cos(ang) * 0.055f * k, by = pcy + (float) Math.sin(ang) * 0.055f * k;
        o2[0] = bx + (float) Math.cos(ang) * L * s; o2[1] = by + (float) Math.sin(ang) * L * s;
        return o2;
    }

    // ---------------- dessin ----------------
    @Override
    protected void onDraw(Canvas c) {
        super.onDraw(c);
        long maintenant = SystemClock.uptimeMillis();
        float dt = avant == 0 ? 0.016f : Math.min(0.05f, (maintenant - avant) / 1000f);
        avant = maintenant;
        t += dt;
        float f60 = dt * 60;

        float W = getWidth(), H = getHeight();
        float R0 = Math.min(W * 0.36f, H * 0.33f), CX = W / 2, CY = H * 0.44f;
        if (!initialise) {
            for (int i = 0; i < N; i++) { px[i] = CX + hx[i] * R0; py[i] = CY + hy[i] * R0; }
            initialise = true;
        }
        boolean sujet = estSujet(), parle = mode.equals("parle") || sujet;
        float vise;
        if (mode.equals("ecoute")) vise = micro != null ? Math.min(1, 0.15f + micro.niveau()) : 0.35f + 0.6f * Math.abs(bruit(t * 2.2f, 1));
        else if (parle) vise = 0.2f + 0.8f * Math.abs((float) (Math.sin(t * 9) * Math.sin(t * 2.3)));
        else vise = 0;
        amp += (vise - amp) * Math.min(1, 0.25f * f60);

        float ry = rythme();
        if (ry > 0 && (int) (t / ry) != (int) ((t - dt) / ry)) { cle++; debutCle = t; cibles = formeEchantillonnee(); }
        float ev = t - debutCle;

        float R = R0 * (1 + 0.035f * (float) Math.sin(t * 1.6) + 0.05f * amp);

        // ondes d'ecoute
        if (mode.equals("ecoute")) {
            trait.setStrokeWidth(1.5f * densite);
            for (int i = 0; i < 3; i++) {
                float p = (t * 0.6f + i / 3f) % 1;
                trait.setColor(Color.argb((int) (255 * 0.28f * (1 - p)), 61, 220, 151));
                c.drawCircle(CX, CY, R * (1.06f + p * 0.45f * (0.4f + amp)), trait);
            }
        }
        // bulle holographique
        chemin.reset();
        boolean tourne = mode.equals("reflechit");
        for (int i = 0; i <= 120; i++) {
            float a = (float) (i / 120.0 * 2 * Math.PI) + (tourne ? t * 0.8f : 0);
            float r = R * (1 + 0.035f * bruitRond(a, t * 1.3f) + (tourne ? 0.09f * bruitRond(a * 2, t * 4) : 0)
                    + (mode.equals("bio") ? 0.06f * bruitRond(a, t * 2.2f) : 0));
            float x = CX + (float) Math.cos(a) * r, y = CY + (float) Math.sin(a) * r;
            if (i == 0) chemin.moveTo(x, y); else chemin.lineTo(x, y);
        }
        chemin.close();
        fondBulle.setShader(new RadialGradient(CX - R * 0.15f, CY - R * 0.18f, R * 1.1f,
                new int[]{Color.argb(26, 191, 247, 220), Color.argb(8, 61, 220, 151), Color.argb(72, 127, 240, 192)},
                new float[]{0, 0.72f, 1}, Shader.TileMode.CLAMP));
        c.drawPath(chemin, fondBulle);
        trait.setStrokeWidth(1.2f * densite);
        trait.setColor(Color.argb(115, 127, 240, 192));
        c.drawPath(chemin, trait);

        float bat = 1;
        if (mode.equals("sante")) {
            bat = 1 + 0.12f * (float) Math.pow(Math.max(0, Math.sin(t * 7)), 8) + 0.06f * (float) Math.pow(Math.max(0, Math.sin(t * 7 - 0.9)), 8);
        }

        // les points
        for (int i = 0; i < N; i++) {
            float tx, ty, lerp = 0.08f, lum = 0;
            float[] q = null;
            if (mode.equals("parle") && i < NL * 2) { q = levres(i, NL * 2, amp, 0.15f, 1.15f); lerp = 0.3f; lum = 0.15f; }
            else if (sujet && i < NL) { q = levres(i, NL, amp, 0.72f, 0.45f); lerp = 0.3f; }
            else if (mode.equals("meca")) { q = rouage(i); lerp = 0.2f; }
            else if (mode.equals("personne")) { q = personne(i); lerp = 0.14f; }
            else if (mode.equals("bio") && i < NL + 3 * NC) { q = cellule(i - NL); lerp = 0.15f; lum = 0.2f; }
            if (q != null) { tx = q[0]; ty = q[1]; }
            else if (cibles != null) {
                tx = cibles[i][0]; ty = cibles[i][1];
                tx = tx * bat + (float) Math.sin(t * 2 + ph[i]) * 0.006f;
                ty = ty * bat + (float) Math.cos(t * 2 + ph[i]) * 0.006f;
            } else if (mode.equals("bio")) {
                hy[i] -= 0.004f * ps[i] * f60;
                if (hy[i] < -0.88f) { hy[i] = 0.88f; hx[i] = (hasard.nextFloat() - 0.5f) * 1.3f; }
                tx = hx[i] + (float) Math.sin(t * 3 + ph[i]) * 0.03f; ty = hy[i]; lerp = 0.25f; lum = -0.15f;
            } else if (tourne) {
                float a = (float) Math.atan2(hy[i], hx[i]) + 0.02f * ps[i] * f60, r = (float) Math.hypot(hx[i], hy[i]);
                hx[i] = (float) Math.cos(a) * r; hy[i] = (float) Math.sin(a) * r;
                tx = hx[i] * (1 + 0.08f * (float) Math.sin(t * 6 + ph[i])); ty = hy[i] * (1 + 0.08f * (float) Math.cos(t * 5 + ph[i]));
            } else {
                tx = hx[i] * (1 + 0.25f * amp) + (float) Math.sin(t * 0.7 + ph[i]) * 0.04f;
                ty = hy[i] * (1 + 0.25f * amp) + (float) Math.cos(t * 0.9 + ph[i]) * 0.04f;
            }
            float l = 1 - (float) Math.pow(1 - lerp, f60);
            px[i] += (CX + tx * R - px[i]) * l;
            py[i] += (CY + ty * R - py[i]) * l;
            float alpha = Math.max(0, Math.min(1, 0.45f + lum + 0.4f * (float) Math.sin(t * 4 + ph[i])));
            point.setAlpha((int) (alpha * 255));
            float taille = ps[i] * densite * 0.9f;
            c.drawRect(px[i], py[i], px[i] + taille, py[i] + taille, point);
        }

        // l'eclair du battement qui traverse le coeur, avec une traine qui s'efface
        if (mode.equals("sante")) {
            float per = (float) (2 * Math.PI / 7), tete = ((t + per * 0.75f) % per) / per * 1.25f, larg = 0.8f;
            trait.setStrokeWidth(2.2f * densite);
            trait.setStrokeCap(Paint.Cap.ROUND);
            trait.setShadowLayer(6 * densite, 0, 0, Color.argb(230, 127, 240, 192));
            for (int s = 0; s < 60; s++) {
                float u0 = s / 60f, u1 = (s + 1) / 60f, d = tete - u1;
                if (d < 0 || d > 0.45f) continue;
                trait.setColor(Color.argb((int) (255 * (1 - d / 0.45f)), 220, 255, 238));
                c.drawLine(CX + (u0 * 2 - 1) * larg * R, CY + 0.02f * R + ecg(u0) * R * 0.6f,
                        CX + (u1 * 2 - 1) * larg * R, CY + 0.02f * R + ecg(u1) * R * 0.6f, trait);
            }
            trait.clearShadowLayer();
        }
        // le loup hurle : « Aouuuh » qui monte
        if (mode.equals("animaux") && cle % 3 == 0) {
            float k = Math.max(0, (ev - 0.4f) / 2.4f);
            if (k > 0 && k < 1) {
                texte.setTextSize((13 + 5 * k) * densite);
                texte.setColor(Color.argb((int) (217 * Math.sin(Math.PI * k)), 191, 247, 220));
                c.drawText("Aouuuh", CX - R * 0.55f - k * 8 * densite, CY - R * 0.9f - k * 26 * densite, texte);
            }
        }

        // bulles du soda
        if (mode.equals("bio") && hasard.nextFloat() < 0.08f * f60) {
            Bulle b = new Bulle();
            b.x = CX + (hasard.nextFloat() - 0.5f) * R; b.y = CY - R * 0.95f; b.r = (1 + hasard.nextFloat() * 3) * densite;
            bulles.add(b);
        }
        trait.setStrokeWidth(0.8f * densite);
        for (int i = bulles.size() - 1; i >= 0; i--) {
            Bulle b = bulles.get(i);
            b.vie += 0.012f * f60; b.y -= 0.4f * densite * f60; b.x += (float) Math.sin(t * 3 + b.r) * 0.3f * f60;
            if (b.vie >= 1) { bulles.remove(i); continue; }
            trait.setColor(Color.argb((int) (153 * (1 - b.vie)), 127, 240, 192));
            c.drawCircle(b.x, b.y, b.r, trait);
        }

        // la bulle du document recu : elle tourne tres doucement autour de la sphere (un tour en 2 min 30), toujours facile a toucher
        if (docFichier != null) {
            docAngle += 0.042f * dt;
            float ap = docApparu < 0 ? 1 : lisse(0, 1, (t - docApparu) / 0.9f);
            float dist = R * (1.28f + 0.03f * (float) Math.sin(t * 1.1));
            docX = CX + (float) Math.cos(docAngle) * dist;
            docY = CY + (float) Math.sin(docAngle) * dist * 0.92f;
            docRayon = 19 * densite * (0.6f + 0.4f * ap) * (docEnfonce ? 1.15f : 1);
            float halo = 0.5f + 0.5f * (float) Math.sin(t * 2.4);
            int a = (int) (255 * ap);
            // halo pulsant + disque sombre + contour, puis une petite feuille cornee
            fondBulle.setShader(new RadialGradient(docX, docY, docRayon * 2.2f, Color.argb((int) (a * (0.22f + 0.18f * halo)), 127, 240, 192), Color.argb(0, 127, 240, 192), Shader.TileMode.CLAMP));
            c.drawCircle(docX, docY, docRayon * 2.2f, fondBulle);
            fondBulle.setShader(null);
            fondBulle.setColor(Color.argb((int) (a * 0.82f), 8, 28, 20));
            c.drawCircle(docX, docY, docRayon, fondBulle);
            trait.setStrokeWidth(1.6f * densite);
            trait.setColor(Color.argb((int) (a * (docEnfonce ? 1 : 0.85f)), 127, 240, 192));
            c.drawCircle(docX, docY, docRayon, trait);
            float w = docRayon * 0.42f, h = docRayon * 0.55f, k = w * 0.45f;
            chemin.reset();
            chemin.moveTo(docX - w, docY - h); chemin.lineTo(docX + w - k, docY - h); chemin.lineTo(docX + w, docY - h + k);
            chemin.lineTo(docX + w, docY + h); chemin.lineTo(docX - w, docY + h); chemin.close();
            chemin.moveTo(docX + w - k, docY - h); chemin.lineTo(docX + w - k, docY - h + k); chemin.lineTo(docX + w, docY - h + k);
            trait.setStrokeWidth(1.3f * densite);
            c.drawPath(chemin, trait);
            for (int i = 0; i < 3; i++) c.drawLine(docX - w * 0.55f, docY - h * 0.15f + i * h * 0.38f, docX + w * 0.55f, docY - h * 0.15f + i * h * 0.38f, trait);
            texte.setTextSize(10.5f * densite);
            texte.setColor(Color.argb((int) (a * 0.9f), 230, 242, 236));
            String nom = docNom.length() > 24 ? docNom.substring(0, 23) + "…" : docNom;
            float tx = Math.min(W - 70 * densite, Math.max(70 * densite, docX));
            c.drawText(nom, tx, docY + docRayon + 14 * densite, texte);
            texte.setTextSize(9 * densite);
            texte.setColor(Color.argb((int) (a * 0.55f), 191, 247, 220));
            c.drawText("toucher pour ouvrir", tx, docY + docRayon + 26 * densite, texte);
        }

        // dossier du document, sur le cote de la sphere (quand on en parle sans l'avoir recu)
        if (mode.equals("doc") && docFichier == null) {
            float a = -0.6f + (float) Math.sin(t * 0.8) * 0.12f, dx = CX + (float) Math.cos(a) * R * 1.25f, dy = CY + (float) Math.sin(a) * R * 1.25f;
            trait.setStrokeWidth(1.5f * densite);
            trait.setColor(Color.argb(230, 127, 240, 192));
            c.drawRect(dx - 14 * densite, dy - 10 * densite, dx + 14 * densite, dy + 10 * densite, trait);
            texte.setTextSize(11 * densite);
            texte.setColor(Color.argb(230, 230, 242, 236));
            String nom = nomDocument.isEmpty() ? "document" : (nomDocument.length() > 22 ? nomDocument.substring(0, 21) + "…" : nomDocument);
            c.drawText(nom, Math.min(W - 60 * densite, Math.max(60 * densite, dx)), dy + 24 * densite, texte);
        }

        // piece jointe qui entre dans la sphere
        if (absorbeNom != null) {
            float q = (t - absorbeDebut) / 1.1f;
            if (q >= 1.4f) absorbeNom = null;
            else {
                float e = lisse(0, 1, Math.min(1, q)), x0 = CX, y0 = H - 24 * densite;
                float ix = x0 + (CX - x0) * e, iy = y0 + (CY - y0) * e, k = 1 - 0.75f * e;
                int a = (int) (255 * (q < 0.85f ? 1 : Math.max(0, 1 - (q - 0.85f) / 0.25f)));
                if (q < 1.1f) {
                    trait.setStrokeWidth(1.6f * densite);
                    trait.setColor(Color.argb((int) (a * 0.9f), 127, 240, 192));
                    float w = 16 * densite * k, h = 12 * densite * k;
                    c.drawRect(ix - w, iy - h, ix + w, iy + h, trait);
                    c.drawLine(ix - w, iy - h * 0.4f, ix + w, iy - h * 0.4f, trait);
                    texte.setTextSize(12 * densite);
                    texte.setColor(Color.argb((int) (a * (1 - e)), 230, 242, 236));
                    String nom = absorbeNom.length() > 26 ? absorbeNom.substring(0, 25) + "…" : absorbeNom;
                    c.drawText(nom, ix, iy + h + 16 * densite, texte);
                }
                if (q > 0.9f) {   // petit eclat quand le fichier est « avale »
                    float p = (q - 0.9f) / 0.5f;
                    trait.setStrokeWidth(2 * densite);
                    trait.setColor(Color.argb((int) (200 * (1 - p)), 191, 247, 220));
                    c.drawCircle(CX, CY, R * (0.2f + 0.9f * p), trait);
                }
            }
        }

        // mots-cles qui montent et s'effacent
        if (!motsEnAttente.isEmpty() && t >= prochainMot) {
            Mot m = new Mot();
            m.w = motsEnAttente.remove(0);
            m.x = CX + (hasard.nextFloat() - 0.5f) * R * 1.6f;
            m.y = CY + R * 1.2f + hasard.nextFloat() * R * 0.35f;
            m.vx = (hasard.nextFloat() - 0.5f) * 0.25f * densite; m.vy = (-0.12f - hasard.nextFloat() * 0.14f) * densite;
            mots.add(m);
            prochainMot = t + ecartMots;
        }
        for (int i = mots.size() - 1; i >= 0; i--) {
            Mot m = mots.get(i);
            m.vie += 0.0045f * f60;   // environ 3,7 s par mot m.x += m.vx * f60; m.y += m.vy * f60;
            if (m.vie >= 1) { mots.remove(i); continue; }
            float op = m.vie < 0.15f ? m.vie / 0.15f : 1 - (m.vie - 0.15f) / 0.85f;
            texte.setTextSize((15 + 6 * (1 - m.vie)) * densite);
            texte.setColor(Color.argb((int) (255 * Math.max(0, op)), 191, 247, 220));
            c.drawText(m.w, Math.min(W - 40 * densite, Math.max(40 * densite, m.x)), m.y, texte);
        }

        if (getVisibility() == VISIBLE && getWindowVisibility() == VISIBLE) postInvalidateOnAnimation();
    }

    @Override
    protected void onWindowVisibilityChanged(int v) {
        super.onWindowVisibilityChanged(v);
        if (v == VISIBLE) { avant = 0; invalidate(); }
    }
}
