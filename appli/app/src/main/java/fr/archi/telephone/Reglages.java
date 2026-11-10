package fr.archi.telephone;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.text.InputType;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Toast;

/**
 * Adresse du serveur Archi (webhook n8n) et cle partagee, saisies au premier lancement.
 * Rien n'est compile dans l'APK : chacun branche l'appli sur SON PC (version publique).
 * Les valeurs restent dans les preferences privees de l'appli, jamais dans les journaux.
 */
public final class Reglages {
    private static final String PREFS = "archi_serveur";

    private Reglages() {
    }

    private static SharedPreferences p(Context c) {
        return c.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** Ex. https://mon-pc.exemple.net/webhook/telephone-archi */
    public static String url(Context c) {
        String u = p(c).getString("url", "");
        return u.isEmpty() ? c.getString(R.string.archi_url) : u;
    }

    public static String cle(Context c) {
        String k = p(c).getString("cle", "");
        return k.isEmpty() ? c.getString(R.string.archi_cle) : k;
    }

    public static boolean pret(Context c) {
        return url(c).startsWith("https://") && cle(c).length() >= 16;
    }

    /** Vrai pour un lien « archi://brancher?... » (QR code affiche par le PC a la fin de l'installation). */
    public static boolean estLienBrancher(Intent i) {
        if (i == null || !Intent.ACTION_VIEW.equals(i.getAction()) || i.getData() == null) return false;
        Uri d = i.getData();
        return "archi".equals(d.getScheme()) && "brancher".equals(d.getHost());
    }

    /**
     * Lien du QR code : on montre l'adresse et on demande l'accord AVANT d'enregistrer quoi que ce soit.
     * Un lien piege ne peut donc pas rebrancher l'appli en douce sur un autre serveur.
     */
    public static void proposer(Activity a, String u, String k) {
        u = u == null ? "" : u.trim();
        k = k == null ? "" : k.trim();
        Uri adresse = Uri.parse(u);
        String hote = adresse.getHost();
        boolean valide = u.startsWith("https://") && u.length() <= 300 && hote != null && !hote.isEmpty()
                && adresse.getUserInfo() == null && k.length() >= 16 && k.length() <= 128;
        if (!valide) {
            Toast.makeText(a, "Lien Archi invalide : scanne de nouveau le QR code du PC.", Toast.LENGTH_LONG).show();
            if (!pret(a)) demander(a, null);
            return;
        }
        final String url = u, cle = k;
        new AlertDialog.Builder(a)
                .setTitle("Brancher Archi sur ce PC ?")
                .setMessage("Adresse : " + hote + "\n\nTes messages, tes photos et ta position (pour les rappels de lieu) "
                        + "iront à cette adresse. Accepte seulement si tu viens de scanner le QR code de TON PC.")
                .setCancelable(false)
                .setNegativeButton("Annuler", (d, x) -> {
                    if (!pret(a)) demander(a, null);
                })
                .setPositiveButton("Brancher", (d, x) -> {
                    p(a).edit().putString("url", url).putString("cle", cle).apply();
                    Toast.makeText(a, "Appli branchée sur ton PC.", Toast.LENGTH_SHORT).show();
                })
                .show();
    }

    /** Fenetre de saisie ; apres « Enregistrer », l'appli parle a ce serveur. */
    public static void demander(Activity a, Runnable apres) {
        LinearLayout l = new LinearLayout(a);
        l.setOrientation(LinearLayout.VERTICAL);
        int m = (int) (16 * a.getResources().getDisplayMetrics().density);
        l.setPadding(m, m / 2, m, 0);
        EditText url = new EditText(a);
        url.setHint("https://…/webhook/telephone-archi");
        url.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        url.setText(p(a).getString("url", ""));
        EditText cle = new EditText(a);
        cle.setHint("Clé partagée (16 caractères ou plus)");
        cle.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        l.addView(url);
        l.addView(cle);
        AlertDialog fenetre = new AlertDialog.Builder(a)
                .setTitle("Brancher Archi sur ton PC")
                .setMessage("Le plus simple : scanne le QR code affiché par ton PC (page d'accueil d'Archi). Sinon, saisis l'adresse du webhook « telephone-archi » et la clé ARCHI_CLE_TELEPHONE de ton fichier .env.")
                .setView(l)
                .setCancelable(false)
                .setNegativeButton("Plus tard", null)
                .setPositiveButton("Enregistrer", null)
                .create();
        // bouton branche apres l'ouverture : une saisie invalide ne ferme pas la fenetre
        fenetre.setOnShowListener(x -> fenetre.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                    String u = url.getText().toString().trim();
                    String k = cle.getText().toString().trim();
                    if (!u.startsWith("https://")) {
                        Toast.makeText(a, "Adresse invalide : elle doit commencer par https://", Toast.LENGTH_LONG).show();
                        return;
                    }
                    if ((!k.isEmpty() && k.length() < 16) || (k.isEmpty() && p(a).getString("cle", "").isEmpty())) {
                        Toast.makeText(a, "Clé trop courte (16 caractères minimum).", Toast.LENGTH_LONG).show();
                        return;
                    }
                    SharedPreferences.Editor e = p(a).edit().putString("url", u);
                    if (!k.isEmpty()) e.putString("cle", k);
                    e.apply();
                    Toast.makeText(a, "Serveur enregistré.", Toast.LENGTH_SHORT).show();
                    fenetre.dismiss();
                    if (apres != null) apres.run();
                }));
        fenetre.show();
    }
}
