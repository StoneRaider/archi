package fr.archi.telephone;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ContentResolver;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Build;
import android.os.CountDownTimer;
import android.os.Handler;
import android.os.Looper;
import android.provider.AlarmClock;
import android.provider.CalendarContract;
import android.provider.ContactsContract;
import android.provider.MediaStore;
import android.provider.Settings;
import android.telephony.SmsManager;
import android.view.KeyEvent;

import org.json.JSONObject;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Les mains d'Archi sur le telephone : il recoit un ordre (objet « telephone » dans la reponse, fabrique par
 * outils\telephone\telephone.py sur le PC) et le fait avec les fonctions d'Android.
 * Garde-fous : un appel laisse il faut appuyer sur « Appeler » ; un SMS demande une confirmation a l'ecran ; les secours
 * ouvrent le composeur sur le numero (Android interdit a une appli tierce d'appeler le 112 toute seule).
 * Les autorisations (contacts, appel, SMS) sont demandees la premiere fois ; l'ordre reprend apres l'accord.
 */
public class Commandes {
    public interface Retour { void dire(String message); }

    public static final int PERMISSION_COMMANDE = 21;
    /** false = il faut appuyer sur « Appeler » (version publique) ; true = l'appel part apres 4 s sauf annulation. */
    static final boolean APPEL_AUTO = false;
    private static final long DELAI_APPEL_MS = 4000;

    private final Activity act;
    private final Retour retour;
    private final Handler fil = new Handler(Looper.getMainLooper());
    private JSONObject enAttente;      // l'ordre qui attend une autorisation
    private boolean lampeAllumee;

    public Commandes(Activity a, Retour r) {
        act = a;
        retour = r;
    }

    private void dire(String m) { if (retour != null) retour.dire(m); }

    private static String sans(String s) {
        if (s == null) return "";
        String n = Normalizer.normalize(s, Normalizer.Form.NFD).replaceAll("\\p{M}", "");
        return n.toLowerCase(Locale.FRANCE).trim();
    }

    /** Point d'entree : execute l'ordre (ou le met en attente d'une autorisation). */
    public void executer(JSONObject o) {
        if (o == null) return;
        String action = o.optString("action", "");
        try {
            switch (action) {
                case "youtube": youtube(o); break;
                case "musique": musique(o); break;
                case "sms": sms(o); break;
                case "appel": appel(o); break;
                case "secours": secours(o); break;
                case "lampe": lampe(o.optString("etat", "on").equals("on")); break;
                case "alarme": alarme(o); break;
                case "minuteur": minuteur(o); break;
                case "navigation": navigation(o); break;
                case "ouvrir": ouvrir(o.optString("appli", "")); break;
                case "volume": volume(o); break;
                case "web": web(o); break;
                case "agenda": agenda(o); break;
                case "reglages": reglages(o.optString("panneau", "general")); break;
                case "photo": lancer(new Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA), "l'appareil photo"); break;
                default: dire("Je ne connais pas l'ordre « " + action + " ».");
            }
        } catch (SecurityException e) {
            dire("Le téléphone refuse (autorisation manquante) : " + action);
        } catch (Exception e) {
            dire("Je n'ai pas réussi : " + action + " (" + e.getClass().getSimpleName() + ")");
        }
    }

    // ---------- autorisations ----------
    private boolean autorise(String perm) {
        return act.checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED;
    }

    /** Demande les autorisations manquantes et garde l'ordre pour apres. true = il faut attendre. */
    private boolean demander(JSONObject o, String... perms) {
        List<String> m = new ArrayList<>();
        for (String p : perms) if (!autorise(p)) m.add(p);
        if (m.isEmpty()) return false;
        enAttente = o;
        act.requestPermissions(m.toArray(new String[0]), PERMISSION_COMMANDE);
        return true;
    }

    /** A appeler depuis onRequestPermissionsResult de l'activite. */
    public void reprendre() {
        JSONObject o = enAttente;
        enAttente = null;
        if (o != null) fil.postDelayed(() -> executer(o), 200);
    }

    private boolean lancer(Intent i, String quoi) {
        try {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            act.startActivity(i);
            return true;
        } catch (ActivityNotFoundException e) {
            dire("Aucune appli sur ce téléphone ne sait ouvrir " + quoi + ".");
            return false;
        }
    }

    // ---------- YouTube ----------
    // On prend la premiere appli YouTube installee et active (y compris une variante installee a cote), sinon le navigateur.
    private static final String[] YOUTUBE_CONNUS = {"app.revanced.android.youtube", "app.rvx.android.youtube", "com.google.android.youtube"};

    private boolean actif(PackageManager pm, String p) {
        try {
            ApplicationInfo ai = pm.getApplicationInfo(p, 0);
            return ai.enabled && pm.getLaunchIntentForPackage(p) != null;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    /** Le paquet de l'appli YouTube a utiliser, ou null s'il n'y en a aucune d'active. */
    private String paquetYoutube() {
        PackageManager pm = act.getPackageManager();
        for (String p : YOUTUBE_CONNUS) if (actif(pm, p)) return p;
        try {
            for (ApplicationInfo ai : pm.getInstalledApplications(0)) {
                String p = ai.packageName.toLowerCase(Locale.ROOT), l = sans(String.valueOf(pm.getApplicationLabel(ai)));
                boolean revanced = p.contains("revanced") || p.contains("rvx") || l.contains("revanced");
                boolean yt = p.contains("youtube") || l.contains("youtube");
                boolean musique = p.contains("music") || l.contains("music");
                if (revanced && yt && !musique && actif(pm, ai.packageName)) return ai.packageName;
            }
        } catch (Exception ignore) {
        }
        return null;
    }

    private boolean essayer(Intent i) {
        try {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            act.startActivity(i);
            return true;
        } catch (ActivityNotFoundException | SecurityException e) {
            return false;
        }
    }

    private void youtube(JSONObject o) {
        String id = o.optString("video_id", ""), q = o.optString("recherche", "");
        String p = paquetYoutube();
        if (!id.isEmpty()) {
            Uri web = Uri.parse("https://www.youtube.com/watch?v=" + id);
            if (p != null && (essayer(new Intent(Intent.ACTION_VIEW, Uri.parse("vnd.youtube:" + id)).setPackage(p))
                    || essayer(new Intent(Intent.ACTION_VIEW, web).setPackage(p)))) return;
            lancer(new Intent(Intent.ACTION_VIEW, web), "YouTube");
            return;
        }
        Uri web = Uri.parse("https://www.youtube.com/results?search_query=" + Uri.encode(q));
        if (p != null && (essayer(new Intent(Intent.ACTION_SEARCH).setPackage(p).putExtra("query", q))
                || essayer(new Intent(Intent.ACTION_VIEW, web).setPackage(p)))) return;
        lancer(new Intent(Intent.ACTION_VIEW, web), "YouTube");
    }

    // ---------- musique ----------
    private void musique(JSONObject o) {
        String c = o.optString("commande", "lire");
        if (c.equals("chercher")) {
            Intent i = new Intent(MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH)
                    .putExtra(MediaStore.EXTRA_MEDIA_FOCUS, "vnd.android.cursor.item/*")
                    .putExtra(android.app.SearchManager.QUERY, o.optString("recherche", ""));
            if (!lancer(i, "la musique")) return;
            return;
        }
        int touche;
        switch (c) {
            case "pause": touche = KeyEvent.KEYCODE_MEDIA_PAUSE; break;
            case "suivant": touche = KeyEvent.KEYCODE_MEDIA_NEXT; break;
            case "precedent": touche = KeyEvent.KEYCODE_MEDIA_PREVIOUS; break;
            default: touche = KeyEvent.KEYCODE_MEDIA_PLAY;
        }
        AudioManager am = (AudioManager) act.getSystemService(Activity.AUDIO_SERVICE);
        am.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, touche));
        am.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_UP, touche));
        if (c.equals("lire") && !am.isMusicActive()) {
            // rien ne jouait : on tente aussi le lecteur par defaut
            fil.postDelayed(() -> {
                if (!am.isMusicActive()) {
                    Intent i = new Intent(MediaStore.INTENT_ACTION_MUSIC_PLAYER);
                    try { i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); act.startActivity(i); } catch (Exception ignore) { }
                }
            }, 800);
        }
    }

    // ---------- contacts ----------
    private static class Contact { String nom, numero; }

    /** Trouve le numero d'un nom (ou renvoie le numero tel quel). null = introuvable. */
    private Contact trouverContact(String qui) {
        Contact c = new Contact();
        String chiffres = qui.replaceAll("[\\s.\\-()]", "");
        if (chiffres.matches("\\+?\\d{3,15}")) { c.nom = qui; c.numero = chiffres; return c; }
        if (!autorise(Manifest.permission.READ_CONTACTS)) return null;
        String voulu = sans(qui);
        ContentResolver cr = act.getContentResolver();
        Contact meilleur = null;
        int score = 0;
        try (Cursor cur = cr.query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                new String[]{ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER,
                        ContactsContract.CommonDataKinds.Phone.IS_SUPER_PRIMARY}, null, null, null)) {
            while (cur != null && cur.moveToNext()) {
                String nom = cur.getString(0), num = cur.getString(1);
                if (nom == null || num == null) continue;
                String n = sans(nom);
                int s = 0;
                if (n.equals(voulu)) s = 100;
                else if (n.startsWith(voulu + " ") || n.endsWith(" " + voulu)) s = 80;
                else if (n.contains(voulu)) s = 60;
                else {
                    // tous les mots demandes sont dans le nom ?
                    boolean tous = true;
                    for (String mot : voulu.split("\\s+")) if (!mot.isEmpty() && !n.contains(mot)) { tous = false; break; }
                    if (tous) s = 50;
                }
                if (s > 0 && cur.getInt(2) > 0) s += 5;
                if (s > score) { score = s; meilleur = new Contact(); meilleur.nom = nom; meilleur.numero = num; }
            }
        } catch (Exception ignore) {
        }
        return meilleur;
    }

    // ---------- appel ----------
    private void appel(JSONObject o) {
        if (demander(o, Manifest.permission.CALL_PHONE, Manifest.permission.READ_CONTACTS)) return;
        String qui = o.optString("a", "");
        Contact c = trouverContact(qui);
        if (c == null) { dire("Je ne trouve pas « " + qui + " » dans les contacts."); return; }
        final Contact cible = c;
        final Runnable appeler = () -> {
            try {
                act.startActivity(new Intent(Intent.ACTION_CALL, Uri.parse("tel:" + Uri.encode(cible.numero))));
            } catch (Exception e) {
                lancer(new Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(cible.numero))), "le téléphone");
            }
        };
        if (!APPEL_AUTO) {
            // version publique : l'appel ne part que sur un appui humain (un texte piege ne peut pas faire appeler)
            new AlertDialog.Builder(act)
                    .setTitle("Appeler " + cible.nom + " ?")
                    .setMessage(cible.numero)
                    .setNegativeButton("Annuler", null)
                    .setPositiveButton("Appeler", (x, w) -> appeler.run())
                    .show();
            return;
        }
        AlertDialog d = new AlertDialog.Builder(act)
                .setTitle("Appel de " + cible.nom)
                .setMessage(cible.numero + "\n\nL'appel part dans 4 s.")
                .setNegativeButton("Annuler", (x, w) -> { })
                .create();
        CountDownTimer compte = new CountDownTimer(DELAI_APPEL_MS, 1000) {
            @Override public void onTick(long reste) { d.setMessage(cible.numero + "\n\nL'appel part dans " + (reste / 1000 + 1) + " s."); }
            @Override public void onFinish() {
                if (d.isShowing()) d.dismiss();
                appeler.run();
            }
        };
        d.setOnDismissListener(x -> compte.cancel());
        d.show();
        compte.start();
    }

    private void secours(JSONObject o) {
        String n = o.optString("numero", "112");
        if (!n.matches("\\d{2,4}")) n = "112";
        lancer(new Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + n)), "le téléphone");
        dire("Appuie sur le bouton vert pour appeler le " + n + ".");
    }

    // ---------- SMS ----------
    private void sms(JSONObject o) {
        if (demander(o, Manifest.permission.SEND_SMS, Manifest.permission.READ_CONTACTS)) return;
        String qui = o.optString("a", ""), texte = o.optString("texte", "");
        Contact c = trouverContact(qui);
        if (c == null) { dire("Je ne trouve pas « " + qui + " » dans les contacts."); return; }
        final Contact cible = c;
        new AlertDialog.Builder(act)
                .setTitle("SMS à " + cible.nom)
                .setMessage(texte)
                .setNegativeButton("Annuler", null)
                .setNeutralButton("Modifier", (d, w) -> lancer(new Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + Uri.encode(cible.numero)))
                        .putExtra("sms_body", texte), "les messages"))
                .setPositiveButton("Envoyer", (d, w) -> {
                    try {
                        SmsManager sm = Build.VERSION.SDK_INT >= 31 ? act.getSystemService(SmsManager.class) : SmsManager.getDefault();
                        ArrayList<String> parts = sm.divideMessage(texte);
                        sm.sendMultipartTextMessage(cible.numero, null, parts, null, null);
                        dire("SMS envoyé à " + cible.nom + ".");
                    } catch (Exception e) {
                        lancer(new Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + Uri.encode(cible.numero))).putExtra("sms_body", texte), "les messages");
                    }
                })
                .show();
    }

    // ---------- lampe ----------
    private void lampe(boolean on) {
        try {
            CameraManager cm = (CameraManager) act.getSystemService(Activity.CAMERA_SERVICE);
            for (String id : cm.getCameraIdList()) {
                CameraCharacteristics ch = cm.getCameraCharacteristics(id);
                Boolean flash = ch.get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
                Integer face = ch.get(CameraCharacteristics.LENS_FACING);
                if (Boolean.TRUE.equals(flash) && (face == null || face == CameraCharacteristics.LENS_FACING_BACK)) {
                    cm.setTorchMode(id, on);
                    lampeAllumee = on;
                    return;
                }
            }
            dire("Pas de lampe sur ce téléphone.");
        } catch (Exception e) {
            dire("La lampe ne répond pas (" + e.getClass().getSimpleName() + ").");
        }
    }

    public void eteindreLampeSiBesoin() {
        if (lampeAllumee) lampe(false);
    }

    // ---------- alarme / minuteur ----------
    private void alarme(JSONObject o) {
        Intent i = new Intent(AlarmClock.ACTION_SET_ALARM)
                .putExtra(AlarmClock.EXTRA_HOUR, o.optInt("heure", 7))
                .putExtra(AlarmClock.EXTRA_MINUTES, o.optInt("minute", 0))
                .putExtra(AlarmClock.EXTRA_MESSAGE, o.optString("libelle", "Archi"))
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true);
        lancer(i, "l'horloge");
    }

    private void minuteur(JSONObject o) {
        Intent i = new Intent(AlarmClock.ACTION_SET_TIMER)
                .putExtra(AlarmClock.EXTRA_LENGTH, o.optInt("secondes", 300))
                .putExtra(AlarmClock.EXTRA_MESSAGE, o.optString("libelle", "Archi"))
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true);
        lancer(i, "l'horloge");
    }

    // ---------- navigation ----------
    private void navigation(JSONObject o) {
        String d = o.optString("destination", ""), mode = o.optString("mode", "voiture");
        String m = mode.equals("pied") ? "w" : mode.equals("velo") ? "b" : mode.equals("transports") ? "t" : "d";
        Intent g = new Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=" + Uri.encode(d) + "&mode=" + m)).setPackage("com.google.android.apps.maps");
        try {
            g.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            act.startActivity(g);
        } catch (ActivityNotFoundException e) {
            lancer(new Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q=" + Uri.encode(d))), "une carte");
        }
    }

    // ---------- ouvrir une appli ----------
    private void ouvrir(String nom) {
        if (nom.isEmpty()) return;
        PackageManager pm = act.getPackageManager();
        String voulu = sans(nom);
        String meilleurPaquet = null;
        int score = 0;
        for (ApplicationInfo ai : pm.getInstalledApplications(0)) {
            if (pm.getLaunchIntentForPackage(ai.packageName) == null) continue;
            String label = sans(String.valueOf(pm.getApplicationLabel(ai)));
            int s = label.equals(voulu) ? 100 : label.startsWith(voulu) ? 80 : label.contains(voulu) ? 60
                    : ai.packageName.toLowerCase(Locale.ROOT).contains(voulu.replace(" ", "")) ? 40 : 0;
            if (s > score) { score = s; meilleurPaquet = ai.packageName; }
        }
        if (meilleurPaquet == null) { dire("Je ne trouve pas d'appli « " + nom + " »."); return; }
        Intent i = pm.getLaunchIntentForPackage(meilleurPaquet);
        lancer(i, nom);
    }

    // ---------- volume ----------
    private void volume(JSONObject o) {
        AudioManager am = (AudioManager) act.getSystemService(Activity.AUDIO_SERVICE);
        Object n = o.opt("niveau");
        int max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
        if ("plus".equals(n)) am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI);
        else if ("moins".equals(n)) am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI);
        else {
            int pct = o.optInt("niveau", 50);
            am.setStreamVolume(AudioManager.STREAM_MUSIC, Math.round(max * Math.max(0, Math.min(100, pct)) / 100f), AudioManager.FLAG_SHOW_UI);
        }
    }

    // ---------- web ----------
    private void web(JSONObject o) {
        String u = o.optString("url", ""), q = o.optString("requete", "");
        if (!u.isEmpty()) lancer(new Intent(Intent.ACTION_VIEW, Uri.parse(u)), "cette page");
        else {
            Intent i = new Intent(Intent.ACTION_WEB_SEARCH).putExtra(android.app.SearchManager.QUERY, q);
            try { i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); act.startActivity(i); }
            catch (ActivityNotFoundException e) { lancer(new Intent(Intent.ACTION_VIEW, Uri.parse("https://www.google.com/search?q=" + Uri.encode(q))), "le navigateur"); }
        }
    }

    // ---------- agenda ----------
    private void agenda(JSONObject o) {
        long debut = o.optLong("debut_ms", System.currentTimeMillis() + 3600_000L);
        Intent i = new Intent(Intent.ACTION_INSERT).setData(CalendarContract.Events.CONTENT_URI)
                .putExtra(CalendarContract.Events.TITLE, o.optString("titre", ""))
                .putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, debut)
                .putExtra(CalendarContract.EXTRA_EVENT_END_TIME, debut + o.optInt("duree_min", 60) * 60_000L);
        String lieu = o.optString("lieu", "");
        if (!lieu.isEmpty()) i.putExtra(CalendarContract.Events.EVENT_LOCATION, lieu);
        lancer(i, "l'agenda");
    }

    // ---------- reglages ----------
    private void reglages(String p) {
        Intent i;
        switch (p) {
            case "wifi": i = new Intent(Build.VERSION.SDK_INT >= 29 ? Settings.Panel.ACTION_INTERNET_CONNECTIVITY : Settings.ACTION_WIFI_SETTINGS); break;
            case "bluetooth": i = new Intent(Settings.ACTION_BLUETOOTH_SETTINGS); break;
            case "son": i = new Intent(Build.VERSION.SDK_INT >= 29 ? Settings.Panel.ACTION_VOLUME : Settings.ACTION_SOUND_SETTINGS); break;
            case "batterie": i = new Intent(Intent.ACTION_POWER_USAGE_SUMMARY); break;
            case "ecran": i = new Intent(Settings.ACTION_DISPLAY_SETTINGS); break;
            default: i = new Intent(Settings.ACTION_SETTINGS);
        }
        lancer(i, "les réglages");
    }
}
