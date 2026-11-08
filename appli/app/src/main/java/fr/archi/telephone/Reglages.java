package fr.archi.telephone;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
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
                .setMessage("Adresse du webhook n8n « telephone-archi » et clé ARCHI_CLE_TELEPHONE de ton fichier .env (voir docs/INSTALLATION.md).")
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
