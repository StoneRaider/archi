package fr.archi.telephone;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.os.SystemClock;
import android.util.AttributeSet;
import android.view.View;

/**
 * Le petit logo Bluetooth en haut a droite (mode « appareils » : lunettes ou autre).
 * Eteint : gris. Actif : vert, avec une lueur qui respire.
 */
public class IconeBluetooth extends View {
    private final Paint rond = new Paint(Paint.ANTI_ALIAS_FLAG), signe = new Paint(Paint.ANTI_ALIAS_FLAG),
            fond = new Paint(Paint.ANTI_ALIAS_FLAG), lueur = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path chemin = new Path();
    private boolean actif;

    public IconeBluetooth(Context c) { super(c); init(); }
    public IconeBluetooth(Context c, AttributeSet a) { super(c, a); init(); }

    private void init() {
        rond.setStyle(Paint.Style.STROKE);
        lueur.setStyle(Paint.Style.STROKE);
        signe.setStyle(Paint.Style.STROKE);
        signe.setStrokeJoin(Paint.Join.ROUND);
        signe.setStrokeCap(Paint.Cap.ROUND);
        fond.setStyle(Paint.Style.FILL);
    }

    public void setActif(boolean a) {
        actif = a;
        setContentDescription(a ? "Appareils Bluetooth : actif" : "Appareils Bluetooth : éteint");
        invalidate();
    }

    @Override
    protected void onDraw(Canvas c) {
        super.onDraw(c);
        float d = getResources().getDisplayMetrics().density;
        float w = getWidth(), h = getHeight(), cx = w / 2, cy = h / 2, r = Math.min(w, h) / 2 - 4 * d;
        float u = r / 15f; // le dessin est prevu pour un rond de rayon 15
        if (actif) {
            float t = (SystemClock.uptimeMillis() % 2400) / 2400f;
            float p = (float) (0.5 - 0.5 * Math.cos(t * 2 * Math.PI)); // 0 -> 1 -> 0
            fond.setColor(Color.argb(31, 61, 220, 151));
            c.drawCircle(cx, cy, r, fond);
            lueur.setStrokeWidth(1.2f * d);
            lueur.setColor(Color.argb((int) (128 * (1 - p)), 61, 220, 151));
            c.drawCircle(cx, cy, r + 2.5f * d * p, lueur);
            rond.setColor(Color.rgb(61, 220, 151));
            signe.setColor(Color.rgb(191, 247, 220));
        } else {
            rond.setColor(Color.rgb(36, 55, 45));
            signe.setColor(Color.rgb(94, 122, 108));
        }
        rond.setStrokeWidth(1.2f * d);
        c.drawCircle(cx, cy, r, rond);
        // le signe Bluetooth : M11,12 L22,21 L17,25 L17,9 L22,13 L11,22 (dans un carre de 34)
        float ox = cx - 17 * u, oy = cy - 17 * u;
        chemin.reset();
        chemin.moveTo(ox + 11 * u, oy + 12 * u);
        chemin.lineTo(ox + 22 * u, oy + 21 * u);
        chemin.lineTo(ox + 17 * u, oy + 25 * u);
        chemin.lineTo(ox + 17 * u, oy + 9 * u);
        chemin.lineTo(ox + 22 * u, oy + 13 * u);
        chemin.lineTo(ox + 11 * u, oy + 22 * u);
        signe.setStrokeWidth(1.8f * u);
        c.drawPath(chemin, signe);
        if (actif && getWindowVisibility() == VISIBLE) postInvalidateDelayed(40);
    }
}
