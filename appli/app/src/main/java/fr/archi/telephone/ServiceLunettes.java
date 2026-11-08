package fr.archi.telephone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.os.Build;
import android.os.IBinder;
import android.view.KeyEvent;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * Le mode « lunettes » : Archi reste pret en arriere-plan (notification permanente) et recoit le bouton
 * lecture/pause des ecouteurs Bluetooth (tap sur la branche de lunettes connectees) :
 *   1 tap = ecouter (micro des lunettes) ; 1 tap pendant l'ecoute = envoyer ; 1 tap quand la voix d'Archi parle = le faire taire.
 * Android donne le bouton a la derniere appli qui a joue du son : si tu ecoutes de la musique ailleurs,
 * le tap reste a la musique ; « Reprendre les lunettes » dans la notification rend la main a Archi.
 */
public class ServiceLunettes extends Service implements Conversation.Ecouteur {
    public static final String ACTION_DEMARRER = "fr.archi.telephone.LUNETTES_ON";
    public static final String ACTION_ARRETER = "fr.archi.telephone.LUNETTES_OFF";
    public static final String ACTION_REPRENDRE = "fr.archi.telephone.LUNETTES_REPRENDRE";
    public static final String PREFS = "archi";
    private static final String CANAL = "lunettes";
    private static final int NOTIF = 42;

    public static boolean actif;
    private MediaSession session;
    private Conversation conv;

    public static void demarrer(Context c) {
        Intent i = new Intent(c, ServiceLunettes.class).setAction(ACTION_DEMARRER);
        if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
        else c.startService(i);
    }

    public static void arreter(Context c) {
        c.startService(new Intent(c, ServiceLunettes.class).setAction(ACTION_ARRETER));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        conv = Conversation.get(this);
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CANAL) == null) {
            NotificationChannel ch = new NotificationChannel(CANAL, "Archi lunettes", NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("Archi est prêt à t'écouter depuis tes lunettes");
            nm.createNotificationChannel(ch);
        }
        session = new MediaSession(this, "Archi");
        session.setCallback(new MediaSession.Callback() {
            @Override
            public boolean onMediaButtonEvent(Intent intent) {
                KeyEvent k = intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT);
                if (k == null) return super.onMediaButtonEvent(intent);
                if (k.getAction() == KeyEvent.ACTION_DOWN) {
                    noter("touche " + KeyEvent.keyCodeToString(k.getKeyCode()) + (k.getRepeatCount() > 0 ? " (maintenue)" : ""));
                    switch (k.getKeyCode()) {
                        case KeyEvent.KEYCODE_HEADSETHOOK:
                        case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
                        case KeyEvent.KEYCODE_MEDIA_PLAY:
                        case KeyEvent.KEYCODE_MEDIA_PAUSE:
                            if (k.getRepeatCount() == 0) conv.appui(true);
                            return true;
                        default:
                            break;
                    }
                }
                return true;
            }

            @Override
            public void onPlay() {
                noter("commande PLAY");
                conv.appui(true);
            }

            @Override
            public void onPause() {
                noter("commande PAUSE");
                conv.appui(true);
            }
        });
        etatSession(false);
        session.setActive(true);
        conv.ajouter(this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String a = intent != null ? intent.getAction() : ACTION_DEMARRER;
        if (ACTION_ARRETER.equals(a)) {
            actif = false;
            stopForeground(true);
            stopSelf();
            return START_NOT_STICKY;
        }
        Notification n = notification("Tape sur la branche de tes lunettes pour parler.");
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                int types = ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE | ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK;
                // v5.3 : la position pour les rappels « quand j'arrive a... » (seulement si l'autorisation est donnee)
                if (checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) == android.content.pm.PackageManager.PERMISSION_GRANTED
                        || checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION) == android.content.pm.PackageManager.PERMISSION_GRANTED)
                    types |= ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION;
                startForeground(NOTIF, n, types);
            } else {
                startForeground(NOTIF, n);
            }
        } catch (Exception e) {
            // v5.3 : si c'est le type « position » qui est refuse, on garde au moins le micro et la voix
            boolean repris = false;
            if (Build.VERSION.SDK_INT >= 29) {
                try {
                    startForeground(NOTIF, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE | ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
                    repris = true;
                } catch (Exception e3) {
                }
            }
            // relance par Android en arriere-plan : le micro n'est pas permis tant que l'appli n'a pas ete ouverte
            if (!repris) try {
                if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF, notification("Ouvre l'appli Archi une fois pour réactiver le micro des lunettes."),
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
            } catch (Exception e2) {
                stopSelf();
                return START_NOT_STICKY;
            }
        }
        actif = true;
        Boite.get(this).demarrer();
        reprendreLaMain();
        if (ACTION_REPRENDRE.equals(a)) noter("reprise des lunettes");
        return START_STICKY;
    }

    /** Joue une seconde de silence : Android donne alors le bouton des ecouteurs a Archi. */
    private void reprendreLaMain() {
        etatSession(true);
        new Thread(() -> {
            try {
                int frequence = 16000;
                short[] silence = new short[frequence];
                AudioTrack t = new AudioTrack.Builder()
                        .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                        .setAudioFormat(new AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                                .setSampleRate(frequence).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                        .setBufferSizeInBytes(silence.length * 2)
                        .setTransferMode(AudioTrack.MODE_STATIC).build();
                t.write(silence, 0, silence.length);
                t.play();
                Thread.sleep(1100);
                t.stop();
                t.release();
            } catch (Exception ignore) {
            }
            etatSession(false);
        }).start();
    }

    private void etatSession(boolean joue) {
        if (session == null) return;
        session.setPlaybackState(new PlaybackState.Builder()
                .setActions(PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE | PlaybackState.ACTION_PLAY_PAUSE)
                .setState(joue ? PlaybackState.STATE_PLAYING : PlaybackState.STATE_PAUSED, 0, 1f).build());
    }

    private Notification notification(String texte) {
        PendingIntent ouvrir = PendingIntent.getActivity(this, 2, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent reprendre = PendingIntent.getService(this, 3,
                new Intent(this, ServiceLunettes.class).setAction(ACTION_REPRENDRE),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent couper = PendingIntent.getService(this, 4,
                new Intent(this, ServiceLunettes.class).setAction(ACTION_ARRETER),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CANAL) : new Notification.Builder(this);
        return b.setSmallIcon(R.drawable.ic_notif)
                .setContentTitle("Archi · lunettes")
                .setContentText(texte)
                .setContentIntent(ouvrir)
                .setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "Reprendre les lunettes", reprendre).build())
                .addAction(new Notification.Action.Builder(null, "Arrêter", couper).build())
                .build();
    }

    // ---------- Conversation.Ecouteur ----------
    @Override
    public void etat(Conversation.Etat e, String message) {
        if (!actif) return;
        String t;
        switch (e) {
            case ECOUTE: t = "J'écoute…"; break;
            case ATTENTE: t = "Archi réfléchit…"; break;
            case PARLE: t = "Archi parle (tape pour le couper)."; break;
            case PREPARE: t = "J'ouvre le micro…"; break;
            default: t = message == null || message.isEmpty() ? "Tape sur la branche de tes lunettes pour parler." : message;
        }
        etatSession(e == Conversation.Etat.PARLE);
        getSystemService(NotificationManager.class).notify(NOTIF, notification(t));
    }

    @Override
    public void reponse(String entendu, String texte) {
    }

    /** Journal des touches recues (affiche dans l'appli, pour le diagnostic). */
    private void noter(String quoi) {
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        String ligne = new SimpleDateFormat("HH:mm:ss", Locale.FRANCE).format(new Date()) + "  " + quoi;
        String avant = p.getString("journal_touches", "");
        String tout = (ligne + "\n" + avant);
        if (tout.length() > 1200) tout = tout.substring(0, 1200);
        p.edit().putString("journal_touches", tout).apply();
    }

    @Override
    public void onDestroy() {
        actif = false;
        Boite.get(this).arreterSiPlusUtile();
        conv.retirer(this);
        if (session != null) {
            session.setActive(false);
            session.release();
            session = null;
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
