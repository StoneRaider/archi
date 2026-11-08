package fr.archi.telephone;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.SystemClock;
import android.util.AttributeSet;
import android.view.View;

/**
 * Le petit bouton rond de l'ecran de l'oeil : on lui parle comme a la sphere.
 * Il montre l'etat de la conversation : au repos un iris (un oeil, forcement), a l'ecoute il respire avec
 * la voix et lance des cercles, quand Archi reflechit un arc tourne, quand il parle un petit egaliseur.
 */
public class BoutonOeil extends View {
    private String mode = "repos";
    private Sphere.Niveau micro;
    private final Paint pCercle = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pPlein = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pFond = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF rect = new RectF();
    private float niveauLisse;
    private final long t0 = SystemClock.uptimeMillis();

    public BoutonOeil(Context c) { super(c); init(); }
    public BoutonOeil(Context c, AttributeSet a) { super(c, a); init(); }

    private void init() {
        pCercle.setStyle(Paint.Style.STROKE);
        pCercle.setColor(0xFF3DDC97);
        pCercle.setStrokeCap(Paint.Cap.ROUND);
        pPlein.setColor(0xFF3DDC97);
        pFond.setColor(0xD90B1410);
        setClickable(true);
        setFocusable(true);
        setContentDescription("Parler à Archi");
    }

    public void setMicro(Sphere.Niveau n) { micro = n; }

    public void setMode(String m) {
        if (m == null || m.isEmpty()) m = "repos";
        if (!m.equals(mode)) {
            mode = m;
            invalidate();
        }
    }

    @Override
    protected void onDraw(Canvas c) {
        super.onDraw(c);
        float w = getWidth(), h = getHeight(), cx = w / 2, cy = h / 2;
        float d = getResources().getDisplayMetrics().density;
        float R = Math.min(w, h) / 2 - 3 * d;
        float t = (SystemClock.uptimeMillis() - t0) / 1000f;
        boolean anime = false;

        pFond.setColor(0xD90B1410);
        c.drawCircle(cx, cy, R, pFond);
        pCercle.setStrokeWidth(1.6f * d);
        pCercle.setAlpha(255);

        switch (mode) {
            case "ecoute": {
                float n = micro == null ? 0 : micro.niveau();
                niveauLisse += (n - niveauLisse) * 0.35f;
                float r = R * (0.42f + 0.35f * niveauLisse);
                pPlein.setAlpha(230);
                c.drawCircle(cx, cy, r, pPlein);
                // deux cercles qui s'echappent
                for (int i = 0; i < 2; i++) {
                    float ph = (t * 0.9f + i * 0.5f) % 1f;
                    pCercle.setAlpha(Math.round(200 * (1 - ph)));
                    c.drawCircle(cx, cy, R * (0.5f + 0.5f * ph), pCercle);
                }
                pCercle.setAlpha(255);
                c.drawCircle(cx, cy, R, pCercle);
                anime = true;
                break;
            }
            case "reflechit": {
                pCercle.setAlpha(90);
                c.drawCircle(cx, cy, R, pCercle);
                pCercle.setAlpha(255);
                pCercle.setStrokeWidth(2.4f * d);
                rect.set(cx - R, cy - R, cx + R, cy + R);
                c.drawArc(rect, (t * 260f) % 360f, 95f, false, pCercle);
                rect.set(cx - R * 0.55f, cy - R * 0.55f, cx + R * 0.55f, cy + R * 0.55f);
                pCercle.setAlpha(170);
                c.drawArc(rect, 360f - (t * 180f) % 360f, 70f, false, pCercle);
                anime = true;
                break;
            }
            case "parle": {
                c.drawCircle(cx, cy, R, pCercle);
                int barres = 5;
                float largeur = R * 0.18f, pas = R * 0.3f, x0 = cx - pas * (barres - 1) / 2;
                pPlein.setAlpha(240);
                for (int i = 0; i < barres; i++) {
                    float hb = R * (0.28f + 0.55f * (float) Math.abs(Math.sin(t * (5.5f + i * 0.9f) + i * 1.1f)));
                    rect.set(x0 + i * pas - largeur / 2, cy - hb / 2, x0 + i * pas + largeur / 2, cy + hb / 2);
                    c.drawRoundRect(rect, largeur / 2, largeur / 2, pPlein);
                }
                anime = true;
                break;
            }
            default: {   // repos : un oeil (amande + iris)
                c.drawCircle(cx, cy, R, pCercle);
                pCercle.setStrokeWidth(1.8f * d);
                float a = R * 0.62f, b = R * 0.36f;
                android.graphics.Path p = new android.graphics.Path();
                p.moveTo(cx - a, cy);
                p.quadTo(cx, cy - b * 2, cx + a, cy);
                p.quadTo(cx, cy + b * 2, cx - a, cy);
                c.drawPath(p, pCercle);
                pPlein.setAlpha(255);
                c.drawCircle(cx, cy, R * 0.17f, pPlein);
                pFond.setAlpha(255);
                c.drawCircle(cx + R * 0.05f, cy - R * 0.05f, R * 0.05f, pFond);
                // cligne de temps en temps
                float cl = (t % 4.7f);
                if (cl > 4.5f) {
                    pFond.setAlpha(230);
                    float k = 1 - Math.abs((cl - 4.6f) / 0.1f);
                    c.drawRect(cx - a, cy - b * k, cx + a, cy + b * k, pFond);
                    pCercle.setStrokeWidth(1.8f * d);
                    c.drawLine(cx - a, cy, cx + a, cy, pCercle);
                }
                anime = true;
            }
        }
        if (anime && getVisibility() == VISIBLE && getWindowVisibility() == VISIBLE) postInvalidateOnAnimation();
    }
}
