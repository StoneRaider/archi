package fr.archi.telephone;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.drawable.Drawable;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.ReplacementSpan;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * « Archi » s'ecrit avec son logo dans l'appli, comme sur la page du PC (portail/logo.js) : le A dont la barre est un
 * egaliseur, puis RCHI, a la taille du texte autour.
 *
 * Le mot reste dans le texte (TalkBack le lit, le copier-coller le garde) : seul son dessin change. Les zones de
 * saisie, les notifications et les petits messages du systeme (toasts) gardent leurs lettres.
 */
final class Logo {
    private Logo() {}

    // le mot seul : pas « architecte », pas « archi-agent-local », pas « Archi.apk », pas un bout de chemin de fichier
    // (la meme regle que la page : portail/logo.js)
    static final Pattern MOT = Pattern.compile(
            "(?<![\\p{L}\\p{N}_\\-\\\\/.@])archi(?![\\p{L}\\p{N}_\\-\\\\/@]|\\.[\\p{L}\\p{N}])",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);

    /** Les places du mot dans le texte : {debut, fin} pour chacun. Rien d'Android : se teste seul. */
    static List<int[]> trouver(CharSequence texte) {
        List<int[]> places = new ArrayList<>();
        if (texte == null) return places;
        Matcher m = MOT.matcher(texte);
        while (m.find()) places.add(new int[]{m.start(), m.end()});
        return places;
    }

    /** Le texte, avec le logo a la place de chaque « Archi » (le texte lui-meme s'il n'y en a pas). */
    static CharSequence poser(Context c, CharSequence texte) {
        if (texte == null) return "";
        List<int[]> places = trouver(texte);
        if (places.isEmpty() || c == null) return texte;
        SpannableString s = new SpannableString(texte);
        for (int[] p : places) s.setSpan(new Dessin(c), p[0], p[1], Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        return s;
    }

    /** Le dessin du mot : sa hauteur est celle des majuscules du texte, il est pose sur la ligne. */
    static final class Dessin extends ReplacementSpan {
        private static final float HAUTEUR = 0.74f;        // comme la page : 0,74 em de haut
        private static final float RAPPORT = 120f / 34f;   // le dessin fait 120 x 34
        private final Drawable dessin;

        Dessin(Context c) {
            dessin = c.getDrawable(R.drawable.mot_archi);
        }

        private static int hauteur(Paint p) {
            return Math.max(1, Math.round(p.getTextSize() * HAUTEUR));
        }

        @Override
        public int getSize(Paint p, CharSequence t, int debut, int fin, Paint.FontMetricsInt fm) {
            if (fm != null) {                              // la ligne garde la hauteur du texte
                Paint.FontMetricsInt m = p.getFontMetricsInt();
                fm.ascent = m.ascent;
                fm.descent = m.descent;
                fm.top = m.top;
                fm.bottom = m.bottom;
                fm.leading = m.leading;
            }
            return Math.round(hauteur(p) * RAPPORT);
        }

        @Override
        public void draw(Canvas c, CharSequence t, int debut, int fin, float x, int haut, int ligne, int bas, Paint p) {
            if (dessin == null) return;
            int h = hauteur(p), w = Math.round(h * RAPPORT), g = Math.round(x);
            int sous = Math.round(p.getTextSize() * 0.03f); // un poil sous la ligne, comme la page
            dessin.setBounds(g, ligne - h + sous, g + w, ligne + sous);
            dessin.setAlpha(p.getAlpha());
            dessin.draw(c);
        }
    }
}
