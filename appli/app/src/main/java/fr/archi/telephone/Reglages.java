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
     * Lien du QR code : on montre l'adresse et un code court, et on demande l'accord AVANT d'enregistrer quoi que ce soit.
     * Le meme code est affiche sur la page d'accueil du PC : s'il differe, ce lien ne vient pas de ton PC.
     */
    public static void proposer(Activity a, String u, String k) {
        fermerExplication();   // le lien arrive : la fenetre « Derniere etape » n'a plus lieu d'etre
        u = u == null ? "" : u.trim();
        k = k == null ? "" : k.trim();
        // adresse : https, un nom d'hote en lettres simples (pas de sosie en Unicode), un chemin simple ;
        // cle : lettres, chiffres, - et _ seulement
        boolean valide = u.length() <= 200 && u.matches("^https://[a-z0-9.-]{4,120}(:\\d{1,5})?/[A-Za-z0-9/_-]{0,60}$")
                && k.matches("^[A-Za-z0-9_-]{16,128}$");
        String hote = valide ? Uri.parse(u).getHost() : null;
        if (hote == null || hote.isEmpty()) {
            Toast.makeText(a, "Lien Archi invalide : scanne de nouveau le QR code du PC.", Toast.LENGTH_LONG).show();
            if (!pret(a)) expliquer(a);
            return;
        }
        String message = "Adresse : " + hote + "\nCode : " + codeCourt(k)
                + "\n\nLe même code est affiché sur la page d'accueil de ton PC. S'il est différent, annule."
                + "\n\nTes messages, tes photos et ta position (pour les rappels de lieu) iront à cette adresse.";
        String ancien = pret(a) ? Uri.parse(url(a)).getHost() : null;
        if (ancien != null && !ancien.equals(hote)) message += "\n\nCela remplace le branchement actuel (" + ancien + ").";
        final String url = u, cle = k;
        new AlertDialog.Builder(a)
                .setTitle("Brancher Archi sur ce PC ?")
                .setMessage(message)
                .setCancelable(false)
                .setNegativeButton("Annuler", (d, x) -> {
                    if (!pret(a)) expliquer(a);
                })
                .setPositiveButton("Brancher", (d, x) -> {
                    p(a).edit().putString("url", url).putString("cle", cle).apply();
                    essayer(a);
                })
                .show();
    }

    /** La fenetre « Derniere etape », si elle est ouverte : le lien du QR code la referme en arrivant. */
    private static AlertDialog explication;

    private static void fermerExplication() {
        try {
            if (explication != null && explication.isShowing()) explication.dismiss();
        } catch (Exception ignore) {
        }
        explication = null;
    }

    /** Premier lancement, appli pas encore branchee : on dit quoi faire, sans champ a remplir. */
    public static void expliquer(Activity a) {
        fermerExplication();
        explication = new AlertDialog.Builder(a)
                .setTitle("Dernière étape : brancher l'appli")
                .setMessage("Retourne sur la page d'installation, dans ton navigateur, et touche « Brancher l'appli »."
                        + "\n\nTu l'as fermée ? Sur ton PC, affiche le QR code de la page d'accueil d'Archi et scanne-le de nouveau.")
                .setPositiveButton("Compris", null)
                .setNeutralButton("Saisir à la main", (d, x) -> demander(a, null))
                .setOnDismissListener(d -> explication = null)
                .show();
    }

    /** Juste apres le branchement : on appelle le PC pour de vrai, et on dit ce qu'il a repondu. */
    static void essayer(Activity a) {
        Toast.makeText(a, "Branchement enregistré : j'appelle ton PC…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            final Porte.Reponse r = new Porte(a).essai();
            a.runOnUiThread(() -> {
                if (a.isFinishing() || a.isDestroyed()) return;
                boolean ok = r.code == 200 && r.json != null;
                String message;
                if (ok) {
                    message = "Ton PC a répondu. Tu peux écrire, parler ou envoyer une photo.";
                    if (!r.json.optBoolean("cerveau", true)) {
                        message += "\n\nAttention : sur le PC, LM Studio ne répond pas encore. Regarde la fenêtre « Archi ».";
                    } else if (!r.json.optBoolean("agent", true)) {
                        message += "\n\nAttention : sur le PC, l'agent n'a pas fini de démarrer. Attends une minute.";
                    }
                } else if (r.code == 401 || r.code == 403) {
                    message = "Ton PC a refusé la clé. Rescanne le QR code de la page d'accueil d'Archi.";
                } else {
                    message = Porte.explication(a, r);
                }
                String titre = ok ? "Appli branchée ✓"
                        : (r.code == 401 || r.code == 403) ? "Clé refusée"
                        : "SANS_ESSAI".equals(r.raison) ? "Adresse enregistrée"
                        : (r.code == 504 || r.code == 524) ? "Le PC est lent à répondre"
                        : "Le PC ne répond pas";
                new AlertDialog.Builder(a)
                        .setTitle(titre)
                        .setMessage(message)
                        .setPositiveButton("OK", null)
                        .show();
            });
        }, "archi-essai").start();
    }

    /** 4 caracteres tires de l'empreinte SHA-256 de la cle : la page d'accueil du PC affiche les memes. */
    static String codeCourt(String cle) {
        try {
            byte[] e = java.security.MessageDigest.getInstance("SHA-256").digest(cle.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return String.format("%02X%02X", e[0] & 0xff, e[1] & 0xff);
        } catch (Exception x) {
            return "????";
        }
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
                    fenetre.dismiss();
                    if (apres != null) apres.run();
                    essayer(a);
                }));
        fenetre.show();
    }
}
