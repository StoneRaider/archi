package fr.archi.telephone;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;

/**
 * La boite aux lettres du planificateur (v5.3, 03/11/2026). Tant que l'appli est ouverte ou que le mode lunettes tourne :
 * toutes les 90 s, l'appli donne sa position au PC (/webhook/telephone-boite) et recupere les annonces du planificateur
 * (rappel a l'heure, arrivee sur un lieu, action faite). Chaque annonce est lue par la voix d'Archi (dans les lunettes si elles
 * sont connectees) et affichee en notification. La position ne part que vers le PC de l'utilisateur.
 * Batterie : le GPS n'est ecoute que si le PC dit qu'un rappel « quand j'arrive a... » attend (suivre_position).
 * Fiabilite : chaque annonce est confirmee au PC au passage suivant (recus) ; sinon il la redonne (pas de doublon : ids vus).
 */
public class Boite {
    private static final long PERIODE_MS = 90_000L;
    private static final String CANAL = "annonces";
    private static Boite instance;
    /** L'ecran de l'appli est au premier plan (tenu par MainActivity.onResume / onPause). */
    public static volatile boolean ecranOuvert;

    public static synchronized Boite get(Context c) {
        if (instance == null) instance = new Boite(c.getApplicationContext());
        return instance;
    }

    private final Context ctx;
    private final Handler principal = new Handler(Looper.getMainLooper());
    /** UN seul fil reseau pour toute la vie de l'appli : jamais deux passages en meme temps. */
    private final HandlerThread filReseau;
    private final Handler reseau;
    private volatile boolean actif;
    private volatile Location derniere;
    private int notifId = 500;
    private volatile boolean ecouteGps;
    private final LinkedHashSet<String> vus = new LinkedHashSet<>();
    private final List<String> aConfirmer = new ArrayList<>();

    private final LocationListener ecoute = new LocationListener() {
        @Override
        public void onLocationChanged(Location l) {
            if (l == null) return;
            Location d = derniere;
            // la plus recente gagne ; une plus precise ne remplace que si elle n'a pas plus de 2 min de retard
            if (d == null || l.getTime() > d.getTime() + 120_000L
                    || (l.getTime() >= d.getTime() && l.getAccuracy() <= Math.max(d.getAccuracy() * 1.5f, 100f))
                    || (l.getAccuracy() < d.getAccuracy() && d.getTime() - l.getTime() < 120_000L)) derniere = l;
        }

        @Override
        public void onStatusChanged(String p, int s, Bundle b) {
        }

        @Override
        public void onProviderEnabled(String p) {
        }

        @Override
        public void onProviderDisabled(String p) {
        }
    };

    private final Runnable tour = new Runnable() {
        @Override
        public void run() {
            if (!actif) return;
            passer();
            reseau.postDelayed(this, PERIODE_MS);
        }
    };

    private Boite(Context c) {
        ctx = c;
        filReseau = new HandlerThread("archi-boite");
        filReseau.start();
        reseau = new Handler(filReseau.getLooper());
    }

    /** Demarre (ou garde) le passage regulier. Sans danger si on l'appelle plusieurs fois. */
    public synchronized void demarrer() {
        if (actif) return;
        actif = true;
        reseau.removeCallbacks(tour);
        reseau.postDelayed(tour, 3000);
        noter("boite demarree");
    }

    /** Arrete seulement si ni l'ecran ni le mode lunettes n'en ont besoin. */
    public synchronized void arreterSiPlusUtile() {
        if (!actif || ecranOuvert || ServiceLunettes.actif) return;
        actif = false;
        principal.post(this::couperPosition);
        reseau.removeCallbacks(tour);
        noter("boite arretee");
    }

    private void couperPosition() {
        try {
            ((LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE)).removeUpdates(ecoute);
        } catch (Exception ignore) {
        }
        ecouteGps = false;
    }

    /** Sur le fil principal : ecoute la position seulement si un rappel de lieu attend (le PC le dit). */
    private void suivrePosition(boolean oui) {
        if (!actif) oui = false;
        if (oui == ecouteGps) return;
        if (!oui) {
            couperPosition();
            noter("position : plus suivie");
            return;
        }
        ecouteGps = true;
        noter("position : suivie (rappel de lieu en attente)");
        try {
            if (ctx.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED
                    && ctx.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                noter("pas d'autorisation de position");
                return;
            }
            LocationManager lm = (LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE);
            for (String p : lm.getProviders(true)) {
                if (LocationManager.PASSIVE_PROVIDER.equals(p)) continue;
                // toutes les 60 s ou 50 m : assez pour un rayon de 150 m, sans vider la batterie
                lm.requestLocationUpdates(p, 60_000L, 50f, ecoute, Looper.getMainLooper());
                Location l = lm.getLastKnownLocation(p);
                if (l != null) ecoute.onLocationChanged(l);
            }
        } catch (Exception e) {
            noter("position : " + e.getMessage());
        }
    }

    private String adresse() {
        // meme porte que les conversations, autre chemin du webhook
        String u = Reglages.url(ctx);
        // jamais la position vers le webhook principal (il reveillerait l'agent) : sans « telephone-archi », pas de boite
        return u.contains("telephone-archi") ? u.replace("telephone-archi", "telephone-boite") : null;
    }

    /** Un passage : position -> PC, annonces <- PC. Sur le fil reseau. */
    /** Sans GPS actif : la derniere position connue du telephone (gratuit en batterie), pour « retiens cet endroit : ici ». */
    private void positionConnue() {
        try {
            if (ctx.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED
                    && ctx.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) return;
            LocationManager lm = (LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE);
            for (String p : lm.getProviders(true)) {
                Location l = lm.getLastKnownLocation(p);
                if (l != null) ecoute.onLocationChanged(l);
            }
        } catch (Exception ignore) {
        }
    }

    private void passer() {
        final String adr = adresse();
        if (adr == null) return;   // serveur pas encore regle (ou adresse sans « telephone-archi »)
        if (!ecouteGps) positionConnue();
        try {
            JSONObject corps = new JSONObject();
            Location l = derniere;
            long age = l == null ? Long.MAX_VALUE : System.currentTimeMillis() - l.getTime();
            if (l != null && age < 10 * 60_000L) {
                corps.put("lat", l.getLatitude());
                corps.put("lon", l.getLongitude());
                corps.put("precision_m", Math.round(l.getAccuracy()));
                corps.put("age_s", Math.max(0, age / 1000));
            }
            final List<String> envoyes = new ArrayList<>(aConfirmer);
            corps.put("recus", new JSONArray(envoyes));
            HttpURLConnection cx = (HttpURLConnection) new URL(adr).openConnection();
            cx.setRequestMethod("POST");
            cx.setDoOutput(true);
            cx.setConnectTimeout(15000);
            cx.setReadTimeout(150000);
            cx.setRequestProperty("x-archi-cle", Reglages.cle(ctx));
            cx.setRequestProperty("ngrok-skip-browser-warning", "1");
            cx.setRequestProperty("User-Agent", "ArchiTelephone/1.0");
            cx.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (OutputStream o = cx.getOutputStream()) {
                o.write(corps.toString().getBytes(StandardCharsets.UTF_8));
            }
            int code = cx.getResponseCode();
            InputStream in = code < 400 ? cx.getInputStream() : cx.getErrorStream();
            ByteArrayOutputStream tout = new ByteArrayOutputStream();
            if (in != null) {
                byte[] t = new byte[16384];
                int n;
                while ((n = in.read(t)) > 0) tout.write(t, 0, n);
            }
            if (code >= 400) {
                noter("boite : erreur " + code);
                return;
            }
            JSONObject rep = new JSONObject(tout.toString("UTF-8"));
            aConfirmer.removeAll(envoyes);           // le PC a bien recu nos accuses de reception
            final boolean suivre = rep.optBoolean("suivre_position", false);
            principal.post(() -> suivrePosition(suivre));
            JSONArray a = rep.optJSONArray("annonces");
            if (a == null) return;
            for (int i = 0; i < a.length(); i++) {
                JSONObject x = a.optJSONObject(i);
                if (x == null) continue;
                final String id = x.optString("id", "");
                final String texte = x.optString("texte", "");
                final String audio = x.optString("audio_ogg_base64", "");
                if (!id.isEmpty() && !aConfirmer.contains(id)) aConfirmer.add(id);
                if (texte.isEmpty() || (!id.isEmpty() && vus.contains(id))) continue;   // deja lue
                if (!id.isEmpty()) {
                    vus.add(id);
                    if (vus.size() > 100) vus.remove(vus.iterator().next());
                }
                noter("annonce : " + texte);
                principal.post(() -> {
                    notifier(texte);
                    Conversation.get(ctx).annoncer(texte, audio);
                });
            }
        } catch (Exception e) {
            noter("boite : " + e.getClass().getSimpleName());
        }
    }

    private void notifier(String texte) {
        try {
            NotificationManager nm = ctx.getSystemService(NotificationManager.class);
            if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CANAL) == null) {
                NotificationChannel ch = new NotificationChannel(CANAL, "Rappels d'Archi", NotificationManager.IMPORTANCE_HIGH);
                ch.setDescription("Les rappels et tâches programmées par Archi");
                nm.createNotificationChannel(ch);
            }
            PendingIntent ouvrir = PendingIntent.getActivity(ctx, 7, new Intent(ctx, MainActivity.class),
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(ctx, CANAL) : new Notification.Builder(ctx);
            nm.notify(notifId++, b.setSmallIcon(R.drawable.ic_notif).setContentTitle("Archi")
                    .setContentText(texte).setStyle(new Notification.BigTextStyle().bigText(texte))
                    .setContentIntent(ouvrir).setAutoCancel(true).build());
        } catch (Exception ignore) {
        }
    }

    private void noter(String quoi) {
        try {
            android.content.SharedPreferences p = ctx.getSharedPreferences("archi", Context.MODE_PRIVATE);
            String ligne = new SimpleDateFormat("HH:mm:ss", Locale.FRANCE).format(new Date()) + "  " + quoi;
            String tout = ligne + "\n" + p.getString("journal_boite", "");
            p.edit().putString("journal_boite", tout.length() > 1500 ? tout.substring(0, 1500) : tout).apply();
        } catch (Exception ignore) {
        }
    }
}
