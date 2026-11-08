package fr.archi.telephone;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffXfermode;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.os.Build;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.util.AttributeSet;
import android.view.View;

/**
 * La vague : la transition vers l'oeil (et retour).
 * On fige l'ecran (une capture), les bords deviennent flous, trois ondes partent du centre
 * (« bloum, bloum, bloum ») en deformant l'image comme la surface d'une eau, puis l'image se dissout
 * et laisse apparaitre ce qu'il y a dessous (le globe, ou la sphere au retour).
 *
 * Tout est dessine avec drawBitmapMesh (une grille de points deplaces a chaque image) : rapide, meme sur
 * un telephone modeste, et sans shader. L'image floue est posee par-dessus la nette avec un masque radial
 * (saveLayer + DST_IN), si bien que le flou gagne depuis les bords.
 */
public class Vague extends View {
    public enum Sens { OUVRIR, FERMER }

    private static final int COLONNES = 22;
    private static final float[] DEPARTS_ONDES = {0.22f, 0.62f, 1.02f};   // secondes : les trois « bloum »
    private static final float VITESSE_ONDE = 1.25f;                      // en largeurs d'ecran par seconde
    private static final float FIN_ONDES = 1.55f;                         // quand les trois ondes ont fini de traverser
    private static final float DUREE_DISSOLUTION = 0.75f;
    private static final float ATTENTE_MAX = 25f;                         // on ne reste pas bloque si l'oeil ne repond pas

    private Bitmap nette, floue;
    private int lignes = 36, grilleW = -1, grilleH = -1;
    private float[] sommets, base;
    private float cx, cy;
    private Sens sens = Sens.OUVRIR;
    private long debutMs;
    private float tDissolution = -1;                                       // instant ou la dissolution a commence
    private boolean enCours, pret, couvertSignale;
    private boolean[] ondeVibree = new boolean[DEPARTS_ONDES.length];
    private Runnable quandCouvert, quandFini;
    private String legende = "";

    private final Paint pImage = new Paint(Paint.FILTER_BITMAP_FLAG | Paint.ANTI_ALIAS_FLAG);
    private final Paint pMasque = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pVignette = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pAnneau = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pTexte = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pVoile = new Paint();
    private Vibrator vibreur;

    public Vague(Context c) { super(c); init(c); }
    public Vague(Context c, AttributeSet a) { super(c, a); init(c); }

    private void init(Context c) {
        pMasque.setXfermode(new PorterDuffXfermode(PorterDuff.Mode.DST_IN));
        pAnneau.setStyle(Paint.Style.STROKE);
        pAnneau.setColor(0xFF3DDC97);
        pTexte.setColor(0xFF8FA89B);
        pTexte.setTextSize(13 * c.getResources().getDisplayMetrics().scaledDensity);
        pTexte.setTextAlign(Paint.Align.CENTER);
        pTexte.setTypeface(android.graphics.Typeface.MONOSPACE);
        pTexte.setLetterSpacing(0.12f);
        pVoile.setColor(0xFF0B1410);
        try {
            vibreur = (Vibrator) c.getSystemService(Context.VIBRATOR_SERVICE);
        } catch (Exception ignore) {
        }
        setVisibility(GONE);
        setClickable(true);   // pendant la vague, on ne touche pas ce qu'il y a dessous
    }

    public boolean enCours() { return enCours; }

    /** Texte discret en bas pendant qu'on attend que l'oeil soit pret (« L'œil s'ouvre… »). */
    public void setLegende(String l) { legende = l == null ? "" : l; }

    /**
     * Lance la vague. capture = l'ecran tel qu'il est (peut etre null : on fait alors sans image, juste
     * les ondes et le voile). (cx, cy) = d'ou partent les ondes, dans les coordonnees de cette vue.
     * quandCouvert : appele des que l'image de depart est assez brouillee pour changer ce qu'il y a dessous.
     * En sens OUVRIR, la dissolution finale attend pret() (ou 25 s). En sens FERMER, elle part toute seule.
     */
    public void jouer(Sens s, Bitmap capture, float cx, float cy, Runnable quandCouvert, Runnable quandFini) {
        if (enCours) annuler();   // une vague en cours finit tout de suite (ses suites sont jouees), la nouvelle prend la place
        liberer();
        sens = s;
        this.cx = cx;
        this.cy = cy;
        this.quandCouvert = quandCouvert;
        this.quandFini = quandFini;
        pret = s == Sens.FERMER;
        couvertSignale = false;
        tDissolution = -1;
        java.util.Arrays.fill(ondeVibree, false);
        preparer(capture);
        debutMs = SystemClock.uptimeMillis();
        enCours = true;
        setAlpha(1f);
        setVisibility(VISIBLE);
        postInvalidateOnAnimation();
    }

    /** L'oeil (ou la sphere) est pret dessous : la vague peut se dissoudre des que ses ondes ont fini. */
    public void pret() { pret = true; }

    private void preparer(Bitmap capture) {
        if (capture == null) return;
        try {
            int w = Math.max(2, capture.getWidth() / 2), h = Math.max(2, capture.getHeight() / 2);
            nette = Bitmap.createScaledBitmap(capture, w, h, true);
            Bitmap petite = Bitmap.createScaledBitmap(nette, Math.max(2, w / 14), Math.max(2, h / 14), true);
            Bitmap moyenne = Bitmap.createScaledBitmap(petite, Math.max(2, w / 4), Math.max(2, h / 4), true);
            floue = Bitmap.createScaledBitmap(moyenne, w, h, true);
            petite.recycle();
            moyenne.recycle();
            // un peu plus sombre, comme vue a travers une vitre embuee
            Canvas c = new Canvas(floue);
            c.drawColor(0x33000000);
        } catch (Throwable e) {
            nette = null;
            floue = null;
        }
        if (capture != nette) capture.recycle();
    }

    private void construireGrille(int w, int h) {
        grilleW = w;
        grilleH = h;
        lignes = Math.max(8, Math.round(COLONNES * (float) h / Math.max(1, w)));
        int n = (COLONNES + 1) * (lignes + 1) * 2;
        if (base == null || base.length != n) {
            base = new float[n];
            sommets = new float[n];
        }
        int k = 0;
        for (int j = 0; j <= lignes; j++)
            for (int i = 0; i <= COLONNES; i++) {
                base[k++] = w * (float) i / COLONNES;
                base[k++] = h * (float) j / lignes;
            }
    }

    private static float lisse(float a, float b, float x) {   // smoothstep
        float t = Math.max(0, Math.min(1, (x - a) / (b - a)));
        return t * t * (3 - 2 * t);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (!enCours) return;
        int w = getWidth(), h = getHeight();
        if (w == 0 || h == 0) return;
        if (base == null || grilleW != w || grilleH != h) construireGrille(w, h);
        float t = (SystemClock.uptimeMillis() - debutMs) / 1000f;
        float diag = (float) Math.hypot(w, h);
        boolean ouvrir = sens == Sens.OUVRIR;

        // --- deroule : bords flous, ondes, puis dissolution (qui attend pret()) ---
        float finOndes = ouvrir ? FIN_ONDES : 1.0f;
        if (tDissolution < 0 && t >= finOndes && (pret || t >= ATTENTE_MAX)) tDissolution = t;
        float dissolution = tDissolution < 0 ? 0 : Math.min(1, (t - tDissolution) / DUREE_DISSOLUTION);
        if (!couvertSignale && t >= 0.35f) {
            couvertSignale = true;
            if (quandCouvert != null) post(quandCouvert);
        }

        // rayon du disque encore net : se resserre, puis respire doucement pendant l'attente
        float rNet = diag * 0.75f * (1 - lisse(0f, 0.55f, t)) + diag * 0.17f + (float) Math.sin(t * 1.7) * diag * 0.015f;
        float plume = diag * 0.16f;

        // --- grille deformee par les ondes ---
        float ampl = w * (ouvrir ? 0.028f : 0.020f), largeur = w * 0.10f;
        float respire = (tDissolution < 0 && t > finOndes) ? 1 : 0;   // petites rides d'attente
        for (int k = 0; k < base.length; k += 2) {
            float x = base[k], y = base[k + 1];
            float dx = x - cx, dy = y - cy;
            float r = (float) Math.hypot(dx, dy) + 0.001f;
            float d = 0;
            for (int o = 0; o < DEPARTS_ONDES.length; o++) {
                float age = t - DEPARTS_ONDES[o] * (ouvrir ? 1 : 0.6f);
                if (age <= 0) continue;
                float rayon = ouvrir ? age * VITESSE_ONDE * w : Math.max(0, diag * 0.7f - age * VITESSE_ONDE * w * 1.3f);
                float e = (r - rayon) / largeur;
                float bosse = (float) Math.exp(-e * e);
                d += ampl * bosse * (float) Math.exp(-age * 0.9f) * (ouvrir ? 1 : -1);
            }
            if (respire > 0) d += w * 0.004f * (float) Math.sin(r / (w * 0.06f) - t * 5.5f) * lisse(finOndes, finOndes + 0.8f, t);
            float f = d / r;
            sommets[k] = x + dx * f;
            sommets[k + 1] = y + dy * f;
        }

        float echelle = 1 + 0.07f * dissolution * dissolution;
        int alphaImage = Math.round(255 * (1 - dissolution));
        canvas.save();
        canvas.scale(echelle, echelle, cx, cy);
        if (floue != null && nette != null) {
            // les deux images dans un meme calque, fondu une seule fois (sinon le centre s'efface moins vite que les bords)
            int calqueImage = canvas.saveLayerAlpha(0, 0, w, h, alphaImage);
            pImage.setAlpha(255);
            // 1) l'image floue partout
            canvas.drawBitmapMesh(floue, COLONNES, lignes, sommets, 0, null, 0, pImage);
            // 2) l'image nette, masquee en disque doux autour du centre
            int calque = canvas.saveLayer(0, 0, w, h, null);
            canvas.drawBitmapMesh(nette, COLONNES, lignes, sommets, 0, null, 0, pImage);
            pMasque.setShader(new RadialGradient(cx, cy, Math.max(1, rNet + plume),
                    new int[]{0xFFFFFFFF, 0xFFFFFFFF, 0x00FFFFFF}, new float[]{0, Math.max(0, rNet / (rNet + plume)), 1}, Shader.TileMode.CLAMP));
            canvas.drawRect(0, 0, w, h, pMasque);
            canvas.restoreToCount(calque);
            canvas.restoreToCount(calqueImage);
        } else {
            pVoile.setAlpha(Math.round(200 * (1 - dissolution)));
            canvas.drawRect(0, 0, w, h, pVoile);
        }
        // 3) le voile sombre qui vient des bords
        float ombre = lisse(0f, 0.6f, t) * (1 - dissolution);
        pVignette.setShader(new RadialGradient(cx, cy, diag * 0.75f, new int[]{0x000B1410, 0x000B1410, 0xCC0B1410},
                new float[]{0, 0.35f, 1}, Shader.TileMode.CLAMP));
        pVignette.setAlpha(Math.round(255 * ombre));
        canvas.drawRect(0, 0, w, h, pVignette);
        canvas.restore();

        // 4) les anneaux lumineux qui accompagnent chaque onde
        for (int o = 0; o < DEPARTS_ONDES.length; o++) {
            float age = t - DEPARTS_ONDES[o] * (ouvrir ? 1 : 0.6f);
            if (age <= 0 || age > 1.6f) continue;
            if (!ondeVibree[o]) {
                ondeVibree[o] = true;
                vibrer();
            }
            float rayon = ouvrir ? age * VITESSE_ONDE * w : Math.max(0, diag * 0.7f - age * VITESSE_ONDE * w * 1.3f);
            float vie = (float) Math.exp(-age * 1.8f) * (1 - dissolution);
            for (int i = 0; i < 4; i++) {
                pAnneau.setStrokeWidth((1.5f + i * 3f) * getResources().getDisplayMetrics().density);
                pAnneau.setAlpha(Math.round(vie * (i == 0 ? 190 : 70 / (i + 1))));
                canvas.drawCircle(cx, cy, rayon, pAnneau);
            }
        }

        // 5) la legende d'attente
        if (ouvrir && !legende.isEmpty() && tDissolution < 0 && t > finOndes) {
            pTexte.setAlpha(Math.round(255 * lisse(finOndes, finOndes + 0.6f, t) * (0.6f + 0.4f * (float) Math.sin(t * 3))));
            canvas.drawText(legende, w / 2f, h - 48 * getResources().getDisplayMetrics().density, pTexte);
        }

        if (dissolution >= 1) {
            terminer();
            return;
        }
        postInvalidateOnAnimation();
    }

    private void vibrer() {
        try {
            if (vibreur == null || !vibreur.hasVibrator()) return;
            if (Build.VERSION.SDK_INT >= 26) vibreur.vibrate(VibrationEffect.createOneShot(22, 70));
            else vibreur.vibrate(22);
        } catch (Exception ignore) {
        }
    }

    private void terminer() {
        enCours = false;
        setVisibility(GONE);
        liberer();
        Runnable f = quandFini;
        quandFini = null;
        quandCouvert = null;
        if (f != null) post(f);
    }

    /** Coupe court (par exemple si l'appli passe en arriere-plan). */
    public void annuler() {
        if (!enCours) return;
        enCours = false;
        setVisibility(GONE);
        liberer();
        Runnable c = couvertSignale ? null : quandCouvert, f = quandFini;
        quandCouvert = null;
        quandFini = null;
        if (c != null) c.run();
        if (f != null) f.run();
    }

    private void liberer() {
        if (nette != null) { nette.recycle(); nette = null; }
        if (floue != null) { floue.recycle(); floue = null; }
    }

    @Override
    protected void onDetachedFromWindow() {
        liberer();
        super.onDetachedFromWindow();
    }
}
