package fr.archi.telephone;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationManager;
import android.media.AudioAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Base64;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * Le moteur d'une conversation avec Archi, partage par l'ecran et par le service des lunettes :
 * ecouter (micro du telephone ou des lunettes), s'arreter tout seul au silence, envoyer a la porte du PC,
 * afficher la reponse et la faire lire par la voix d'Archi. Une seule conversation a la fois.
 */
public class Conversation {
    public enum Etat { REPOS, PREPARE, ECOUTE, ATTENTE, PARLE }

    public interface Ecouteur {
        void etat(Etat e, String message);
        void reponse(String entendu, String texte);
        /** Archi veut montrer quelque chose dans l'oeil (globe) : {url, titre, sous_titre, vue, actions, jeton...}. */
        default void oeil(JSONObject o) {}
        /** Archi commande le telephone (appel, SMS, YouTube, lampe...) : {jeton, action, ...}. */
        default void telephone(JSONObject o) {}
    }

    private static Conversation instance;

    public static synchronized Conversation get(Context c) {
        if (instance == null) instance = new Conversation(c.getApplicationContext());
        return instance;
    }

    private static final int SEUIL_VOIX = 1800;
    private static final long SILENCE_FIN_MS = 1500;
    private static final long RIEN_ENTENDU_MS = 7000;
    private static final long MAX_MS = 60000;

    private final Context ctx;
    private final Handler fil = new Handler(Looper.getMainLooper());
    private final List<Ecouteur> ecouteurs = new ArrayList<>();
    private final File question;
    private Etat etat = Etat.REPOS;
    private String dernierMessage = "";
    private MediaRecorder enregistreur;
    private MediaPlayer lecteur;
    private long debut, dernierSon;
    private boolean aParle, viaBluetooth;
    private PowerManager.WakeLock reveil;
    public String dernierEntendu = "", derniereReponse = "";
    /** Ce dont parle la derniere reponse (meca, sante, meteo...), ses mots-cles et le document joint : pour la sphere. */
    public String dernierSujet = "", dernierDocument = "";
    /** Le dernier document recu du PC (PDF, fiche, lettre), enregistre dans files/documents ; null s'il n'y en a pas. */
    public File dernierDocumentFichier;
    public String dernierDocumentType = "";
    /** La derniere cible de l'oeil (null si la derniere reponse n'en avait pas). */
    public JSONObject dernierOeil;
    /** Le dernier ordre pour le telephone (null si la derniere reponse n'en avait pas). */
    public JSONObject dernierTelephone;
    public final List<String> derniersMots = new ArrayList<>();
    private volatile float niveauMicro = 0;
    /** Le fichier en attente (bouton « + » ou « Partager ») : il part avec le prochain message, vocal ou ecrit. */
    public Porte.PieceJointe pieceJointe;
    /** Duree de la voix en cours (ms), pour etaler les mots-cles pendant qu'Archi parle. */
    public long dureeVoix = 0;

    /** Volume du micro pendant l'ecoute, de 0 a 1 (pour les ondes de la sphere). */
    public float niveau() {
        return etat == Etat.ECOUTE ? niveauMicro : 0;
    }

    private Conversation(Context c) {
        ctx = c;
        question = new File(c.getCacheDir(), "question.m4a");
        // le dernier document recu reste disponible d'une ouverture de l'appli a l'autre
        try {
            android.content.SharedPreferences p = c.getSharedPreferences("archi", Context.MODE_PRIVATE);
            String nom = p.getString("dernier_document", "");
            File f = nom.isEmpty() ? null : new File(Fichiers.dossierDocuments(c), nom);
            if (f != null && f.isFile()) { dernierDocumentFichier = f; dernierDocument = nom; dernierDocumentType = Fichiers.typeDe(nom); }
        } catch (Exception ignore) {
        }
    }

    public void ajouter(Ecouteur e) {
        if (!ecouteurs.contains(e)) ecouteurs.add(e);
        e.etat(etat, dernierMessage);
    }

    public void retirer(Ecouteur e) {
        ecouteurs.remove(e);
    }

    public Etat etat() {
        return etat;
    }

    private void changer(Etat e, String msg) {
        etat = e;
        dernierMessage = msg == null ? "" : msg;
        for (Ecouteur x : new ArrayList<>(ecouteurs)) x.etat(e, dernierMessage);
        if (e == Etat.REPOS && !annonces.isEmpty()) fil.postDelayed(this::suiteAnnonces, 800);
    }

    // ---------- annonces du planificateur (v5.3) ----------
    private final java.util.ArrayDeque<String[]> annonces = new java.util.ArrayDeque<>();

    /** Une annonce du planificateur (rappel, arrivee sur un lieu) : la voix d'Archi la lit des que la conversation est libre. */
    public void annoncer(String texte, String audio) {
        if (texte == null || texte.isEmpty()) return;
        annonces.add(new String[]{texte, audio == null ? "" : audio});
        suiteAnnonces();
    }

    private void suiteAnnonces() {
        if (etat != Etat.REPOS || lecteur != null || annonces.isEmpty()) return;
        String[] a = annonces.poll();
        dernierEntendu = "";
        derniereReponse = a[0];
        for (Ecouteur x : new ArrayList<>(ecouteurs)) x.reponse("", a[0]);
        if (a[1].isEmpty()) {
            bip(ToneGenerator.TONE_PROP_ACK);
            if (!annonces.isEmpty()) fil.postDelayed(this::suiteAnnonces, 3000);
            return;
        }
        tenirEveille(true);
        jouer(a[1]);
    }

    /** Un appui (cercle, widget, lunettes) : ecouter, ou arreter l'ecoute et envoyer, ou faire taire la voix d'Archi. */
    public void appui(boolean bluetooth) {
        switch (etat) {
            case REPOS: ecouter(bluetooth); break;
            case ECOUTE: arreterEcoute(true); break;
            case PARLE: taire(); break;
            default: break;
        }
    }

    public boolean micAutorise() {
        return ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    }

    // ---------- ecoute ----------
    public void ecouter(boolean bluetooth) {
        if (etat != Etat.REPOS && etat != Etat.PARLE) return;
        taire();
        if (!micAutorise()) {
            changer(Etat.REPOS, "Autorise le micro dans l'appli Archi.");
            return;
        }
        tenirEveille(true);
        viaBluetooth = bluetooth && brancherMicroBluetooth();
        changer(Etat.PREPARE, viaBluetooth ? "Micro des lunettes…" : "");
        // le micro Bluetooth met un instant a s'ouvrir
        fil.postDelayed(this::demarrerEnregistrement, viaBluetooth ? 900 : 50);
    }

    private void demarrerEnregistrement() {
        if (etat != Etat.PREPARE) return;
        try {
            enregistreur = Build.VERSION.SDK_INT >= 31 ? new MediaRecorder(ctx) : new MediaRecorder();
            enregistreur.setAudioSource(viaBluetooth ? MediaRecorder.AudioSource.VOICE_COMMUNICATION
                    : MediaRecorder.AudioSource.VOICE_RECOGNITION);
            enregistreur.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            enregistreur.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            enregistreur.setAudioChannels(1);
            enregistreur.setAudioSamplingRate(16000);
            enregistreur.setAudioEncodingBitRate(32000);
            enregistreur.setOutputFile(question.getAbsolutePath());
            enregistreur.prepare();
            enregistreur.start();
        } catch (Exception e) {
            liberer();
            debrancherMicroBluetooth();
            tenirEveille(false);
            changer(Etat.REPOS, "Micro indisponible : " + e.getMessage());
            return;
        }
        bip(ToneGenerator.TONE_PROP_BEEP);
        debut = SystemClock.elapsedRealtime();
        dernierSon = debut;
        aParle = false;
        changer(Etat.ECOUTE, viaBluetooth ? "Je t'écoute (lunettes)…" : "Je t'écoute…");
        fil.postDelayed(surveillance, 150);
    }

    private final Runnable surveillance = new Runnable() {
        @Override
        public void run() {
            if (etat != Etat.ECOUTE || enregistreur == null) return;
            long t = SystemClock.elapsedRealtime();
            int amp = 0;
            try {
                amp = enregistreur.getMaxAmplitude();
            } catch (Exception ignore) {
            }
            niveauMicro = Math.min(1f, amp / 14000f);
            if (amp > SEUIL_VOIX) {
                aParle = true;
                dernierSon = t;
            }
            if (aParle && t - dernierSon > SILENCE_FIN_MS) arreterEcoute(true);
            else if (!aParle && t - debut > RIEN_ENTENDU_MS) arreterEcoute(false);
            else if (t - debut > MAX_MS) arreterEcoute(true);
            else fil.postDelayed(this, 100);
        }
    };

    public void arreterEcoute(boolean envoyer) {
        fil.removeCallbacks(surveillance);
        boolean ok = true;
        try {
            if (enregistreur != null) enregistreur.stop();
        } catch (Exception e) {
            ok = false;
        }
        liberer();
        debrancherMicroBluetooth();
        bip(ToneGenerator.TONE_PROP_ACK);
        if (envoyer && ok && question.length() > 1500) {
            envoyer(null);
        } else {
            tenirEveille(false);
            changer(Etat.REPOS, aParle ? "C'était trop court, réessaie." : "Je n'ai rien entendu.");
        }
    }

    private void liberer() {
        if (enregistreur != null) {
            try {
                enregistreur.release();
            } catch (Exception ignore) {
            }
            enregistreur = null;
        }
    }

    // ---------- micro des lunettes (Bluetooth « mains libres ») ----------
    private boolean brancherMicroBluetooth() {
        try {
            AudioManager am = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
            if (Build.VERSION.SDK_INT >= 31) {
                for (AudioDeviceInfo d : am.getAvailableCommunicationDevices()) {
                    if (d.getType() == AudioDeviceInfo.TYPE_BLUETOOTH_SCO) {
                        am.setMode(AudioManager.MODE_IN_COMMUNICATION);
                        return am.setCommunicationDevice(d);
                    }
                }
                return false;
            }
            am.setMode(AudioManager.MODE_IN_COMMUNICATION);
            am.startBluetoothSco();
            am.setBluetoothScoOn(true);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private void debrancherMicroBluetooth() {
        if (!viaBluetooth) return;
        try {
            AudioManager am = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
            if (Build.VERSION.SDK_INT >= 31) {
                am.clearCommunicationDevice();
            } else {
                am.setBluetoothScoOn(false);
                am.stopBluetoothSco();
            }
            am.setMode(AudioManager.MODE_NORMAL);
        } catch (Exception ignore) {
        }
        viaBluetooth = false;
    }

    // ---------- envoi ----------
    /** texte != null : message ecrit ; sinon le vocal qui vient d'etre enregistre. */
    public void envoyer(String texte) {
        if (texte != null && (etat == Etat.ECOUTE || etat == Etat.ATTENTE || etat == Etat.PREPARE)) return;
        taire();
        tenirEveille(true);
        changer(Etat.ATTENTE, "Archi réfléchit…");
        final double[] pos = position();
        final Double lat = pos == null ? null : pos[0], lon = pos == null ? null : pos[1];
        new Thread(() -> {
            Porte p = new Porte(ctx);
            final Porte.PieceJointe pj = pieceJointe;
            Porte.Reponse r = texte != null ? p.texte(texte, lat, lon, pj) : p.vocal(question, lat, lon, pj);
            fil.post(() -> recevoir(r, texte));
        }).start();
    }

    private void recevoir(Porte.Reponse r, String texteEcrit) {
        if (r.code == 401 || r.code == 403) {
            tenirEveille(false);
            changer(Etat.REPOS, "Clé refusée par ton PC : rescanne le QR code de la page d'accueil d'Archi.");
            return;
        }
        if (r.json == null) {
            tenirEveille(false);
            // la vraie raison, et quoi faire : pas branchee, adresse introuvable, PC muet...
            changer(Etat.REPOS, Porte.explication(ctx, r));
            return;
        }
        if (r.code >= 400) {
            tenirEveille(false);
            changer(Etat.REPOS, "Archi a eu un problème (erreur " + r.code + ").");
            return;
        }
        JSONObject j = r.json;
        pieceJointe = null; // bien recue par Archi
        for (Ecouteur x : new ArrayList<>(ecouteurs)) if (x instanceof MainActivity) ((MainActivity) x).pieceEnvoyee();
        dernierEntendu = texteEcrit != null ? texteEcrit : j.optString("entendu", "");
        derniereReponse = j.optString("texte", "(pas de réponse)");
        dernierSujet = j.optString("sujet", "");
        dernierDocument = j.optString("document", "");
        recevoirDocument(j);
        derniersMots.clear();
        org.json.JSONArray m = j.optJSONArray("mots");
        if (m != null) for (int i = 0; i < m.length() && i < 6; i++) derniersMots.add(m.optString(i));
        for (Ecouteur x : new ArrayList<>(ecouteurs)) x.reponse(dernierEntendu, derniereReponse);
        // l'oeil : si Archi a fait appel a l'outil oeil (montrer), la reponse porte ce qu'il faut ouvrir
        JSONObject o = j.optJSONObject("oeil");
        dernierOeil = (o != null && !o.optString("url", "").isEmpty()) ? o : null;
        if (dernierOeil != null) for (Ecouteur x : new ArrayList<>(ecouteurs)) x.oeil(dernierOeil);
        JSONObject t = j.optJSONObject("telephone");
        dernierTelephone = (t != null && !t.optString("action", "").isEmpty()) ? t : null;
        if (dernierTelephone != null) for (Ecouteur x : new ArrayList<>(ecouteurs)) x.telephone(dernierTelephone);
        String audio = j.optString("audio_ogg_base64", "");
        if (audio.isEmpty()) {
            tenirEveille(false);
            changer(Etat.REPOS, "Réponse écrite seulement (la voix n'a pas marché).");
        } else {
            jouer(audio);
        }
    }

    /** Un document joint a la reponse (document_nom + document_base64) : on l'enregistre, la sphere le montrera. */
    private void recevoirDocument(JSONObject j) {
        String nom = Fichiers.nomSur(j.optString("document_nom", ""));
        String b64 = j.optString("document_base64", "");
        if (nom.isEmpty() || b64.isEmpty()) return;
        try {
            File f = new File(Fichiers.dossierDocuments(ctx), nom);
            try (FileOutputStream o = new FileOutputStream(f)) {
                o.write(Base64.decode(b64, Base64.DEFAULT));
            }
            dernierDocumentFichier = f;
            dernierDocument = nom;
            String t = j.optString("document_type", "");
            dernierDocumentType = t.isEmpty() ? Fichiers.typeDe(nom) : t;
            ctx.getSharedPreferences("archi", Context.MODE_PRIVATE).edit().putString("dernier_document", nom).apply();
        } catch (Exception e) {
            dernierDocumentFichier = null;
        }
    }

    // ---------- voix ----------
    private void jouer(String base64) {
        try {
            File f = new File(ctx.getCacheDir(), "reponse.ogg");
            try (FileOutputStream o = new FileOutputStream(f)) {
                o.write(Base64.decode(base64, Base64.DEFAULT));
            }
            lecteur = new MediaPlayer();
            lecteur.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());
            lecteur.setDataSource(f.getAbsolutePath());
            lecteur.setOnCompletionListener(mp -> taire());
            lecteur.prepare();
            dureeVoix = Math.max(0, lecteur.getDuration());
            lecteur.start();
            changer(Etat.PARLE, "Archi parle…");
        } catch (Exception e) {
            tenirEveille(false);
            changer(Etat.REPOS, "Impossible de lire la voix : " + e.getMessage());
        }
    }

    public void taire() {
        if (lecteur != null) {
            try {
                lecteur.stop();
            } catch (Exception ignore) {
            }
            lecteur.release();
            lecteur = null;
        }
        if (etat == Etat.PARLE) {
            tenirEveille(false);
            changer(Etat.REPOS, "");
        }
    }

    // ---------- petits outils ----------
    private void bip(int ton) {
        try {
            ToneGenerator g = new ToneGenerator(AudioManager.STREAM_MUSIC, 70);
            g.startTone(ton, 150);
            fil.postDelayed(g::release, 400);
        } catch (Exception ignore) {
        }
    }

    private void tenirEveille(boolean oui) {
        try {
            if (oui) {
                if (reveil == null) {
                    PowerManager pm = (PowerManager) ctx.getSystemService(Context.POWER_SERVICE);
                    reveil = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "archi:conversation");
                }
                if (!reveil.isHeld()) reveil.acquire(5 * 60 * 1000L);
            } else if (reveil != null && reveil.isHeld()) {
                reveil.release();
            }
        } catch (Exception ignore) {
        }
    }

    private double[] position() {
        try {
            if (ctx.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) return null;
            LocationManager lm = (LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE);
            Location meilleure = null;
            for (String p : lm.getProviders(true)) {
                Location l = lm.getLastKnownLocation(p);
                if (l != null && (meilleure == null || l.getTime() > meilleure.getTime())) meilleure = l;
            }
            if (meilleure == null || System.currentTimeMillis() - meilleure.getTime() > 3600_000L) return null;
            return new double[]{meilleure.getLatitude(), meilleure.getLongitude()};
        } catch (Exception e) {
            return null;
        }
    }
}
