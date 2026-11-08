package fr.archi.telephone;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.view.PixelCopy;
import android.widget.FrameLayout;
import org.json.JSONObject;
import java.util.function.Consumer;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.webkit.MimeTypeMap;
import android.widget.PopupMenu;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.TextView;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * Archi sur le telephone, v2 :
 *  - la sphere de points (Sphere) : toucher = ecouter ; arret tout seul apres ~1,5 s de silence (ou 2e toucher) ;
 *  - un champ texte pour ecrire ; la reponse s'affiche et la voix d'Archi la lit ;
 *  - widget / geste assistant : l'ecoute demarre tout de suite ;
 *  - bouton « Lunettes » : mode arriere-plan, un tap sur la branche des lunettes = parler (voir ServiceLunettes).
 *  - appui long sur « Lunettes » : journal des touches recues (diagnostic) ;
 *  - l'oeil (v5) : quand Archi veut montrer quelque chose (avion, lieu, camera), l'ecran se brouille en vagues
 *    et le globe apparait (EcranOeil + Vague) ; on continue a lui parler depuis cet ecran ; retour = bouton ✕ ou Retour.
 */
public class MainActivity extends Activity implements Conversation.Ecouteur {
    public static final String EXTRA_ECOUTER = "ecouter";
    private static final int DEMANDE_PERMISSIONS = 7;
    private static final int CHOISIR_DOCUMENT = 11, CHOISIR_PHOTO = 12, PRENDRE_PHOTO = 13;
    private static final long TAILLE_MAX = 15L * 1024 * 1024; // 15 Mo

    private TextView etatTxt, entendu, reponse, piece;
    private IconeBluetooth lunettes;
    private Sphere sphere;
    private android.view.View boite;
    private FrameLayout racine;
    private android.view.View contenu;
    private EcranOeil ecranOeil;
    private Vague vague;
    private String jetonOeilMontre = "", jetonTelephoneFait = "";
    private Commandes commandes;
    private EditText saisie;
    private Conversation conv;
    private final Handler fil = new Handler(Looper.getMainLooper());
    private boolean ecouterApresPermission, lunettesApresPermission, diagnostic;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setContentView(R.layout.activity_main);
        sphere = findViewById(R.id.sphere);
        etatTxt = findViewById(R.id.etat);
        entendu = findViewById(R.id.entendu);
        reponse = findViewById(R.id.reponse);
        saisie = findViewById(R.id.saisie);
        lunettes = findViewById(R.id.lunettes);
        piece = findViewById(R.id.piece);
        boite = findViewById(R.id.boite);
        findViewById(R.id.plus).setOnClickListener(this::menuPlus);
        piece.setOnClickListener(v -> {   // toucher la piece jointe = l'enlever
            conv.pieceJointe = null;
            afficherPiece();
        });
        conv = Conversation.get(this);
        racine = findViewById(R.id.racine);
        contenu = findViewById(R.id.contenu);
        ecranOeil = findViewById(R.id.ecran_oeil);
        vague = findViewById(R.id.vague);
        ecranOeil.setMicro(() -> conv.niveau());
        commandes = new Commandes(this, this::info);
        ecranOeil.setEcouteur(new EcranOeil.Ecouteur() {
            @Override public void oeilPret() { vague.pret(); }
            @Override public void oeilErreur(String message) { vague.pret(); }
            @Override public void fermer() { fermerOeil(); }
            @Override public void parler() { appuiCercle(); }
        });

        sphere.setOnClickListener(v -> appuiCercle());
        sphere.setMicro(() -> conv.niveau());
        sphere.setSurDocument(this::ouvrirDocument);
        sphere.setSurDocumentLong(this::menuDocument);
        sphere.setDocumentFichier(conv.dernierDocumentFichier);
        findViewById(R.id.envoyer).setOnClickListener(v -> envoyerTexte());
        saisie.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                envoyerTexte();
                return true;
            }
            return false;
        });
        lunettes.setOnClickListener(v -> basculerLunettes());
        // appui long sur « ARCHI » : choisir le serveur Archi ou le reglage Android « Assistant numerique »
        findViewById(R.id.titre).setOnLongClickListener(v -> {
            new android.app.AlertDialog.Builder(this)
                    .setItems(new String[]{"Serveur Archi (adresse et clé)", "Assistant numérique d'Android"}, (d, i) -> {
                        if (i == 0) Reglages.demander(this, null);
                        else ouvrirReglageAssistant();
                    })
                    .show();
            return true;
        });
        if (!Reglages.pret(this)) Reglages.demander(this, null);
        lunettes.setOnLongClickListener(v -> {
            diagnostic = !diagnostic;
            afficherDiagnostic();
            return true;
        });
        if (!conv.derniereReponse.isEmpty()) reponse(conv.dernierEntendu, conv.derniereReponse);
        afficherPiece();
        traiterIntention(getIntent());
    }

    private void ouvrirReglageAssistant() {
        {
            for (String a : new String[]{"android.settings.VOICE_INPUT_SETTINGS", "android.settings.MANAGE_DEFAULT_APPS_SETTINGS"}) {
                try {
                    startActivity(new Intent(a));
                    return;
                } catch (Exception ignore) {
                }
            }
            info("Je n'arrive pas à ouvrir le réglage de l'assistant sur ce téléphone.");
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        conv.ajouter(this);
        Boite.ecranOuvert = true;
        Boite.get(this).demarrer();
        afficherLunettes();
        afficherDiagnostic();
        ecranOeil.reprendre();
        // une cible de l'oeil arrivee pendant que l'appli etait en arriere-plan : on l'ouvre maintenant
        final JSONObject attente = conv.dernierOeil;
        if (attente != null && !attente.optString("jeton", "").equals(jetonOeilMontre)) fil.postDelayed(() -> oeil(attente), 500);
        final JSONObject ordre = conv.dernierTelephone;
        if (ordre != null && !ordre.optString("jeton", "").equals(jetonTelephoneFait)) fil.postDelayed(() -> telephone(ordre), 300);
    }

    // ---------- les mains d'Archi sur le telephone ----------
    @Override
    public void telephone(JSONObject o) {
        if (o == null) return;
        String jeton = o.optString("jeton", "");
        if (!jeton.isEmpty() && jeton.equals(jetonTelephoneFait)) return;   // deja fait
        jetonTelephoneFait = jeton;
        commandes.executer(o);
    }

    @Override
    protected void onPause() {
        conv.retirer(this);
        Boite.ecranOuvert = false;
        Boite.get(this).arreterSiPlusUtile();
        if (vague.enCours()) vague.annuler();
        ecranOeil.pause();
        super.onPause();
    }

    // ---------- l'oeil ----------
    /** Archi a quelque chose a montrer : la vague, puis le globe (charge dessous pendant que l'ecran ondule). */
    @Override
    public void oeil(JSONObject o) {
        if (o == null || o.optString("url", "").isEmpty()) return;
        if (o.optString("jeton", "").equals(jetonOeilMontre) && ecranOeil.estOuvert()) return;   // deja a l'ecran
        jetonOeilMontre = o.optString("jeton", "");
        final boolean vagueAnnulee = vague.enCours();
        if (vagueAnnulee) vague.annuler();
        final boolean miseAJour = ecranOeil.peutMettreAJour(o);
        final android.view.View bouton = ecranOeil.findViewById(R.id.bouton_oeil);
        final float[] centre = centreDe(miseAJour ? bouton : sphere);
        vague.setLegende("L’ŒIL S’OUVRE…");
        // apres une vague annulee, on laisse l'ecran se redessiner avant la photo (sinon on photographie l'ancienne vague)
        apresRedessin(vagueAnnulee, () -> capturer(bmp -> {
            vague.jouer(Vague.Sens.OUVRIR, bmp, centre[0], centre[1], null, null);
            // l'ecran de l'oeil se met en place SOUS la vague (l'image figee le cache encore)
            if (miseAJour) {
                ecranOeil.mettreAJour(o);
            } else {
                contenu.setVisibility(android.view.View.INVISIBLE);
                ecranOeil.ouvrir(o);
            }
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }));
    }

    private void apresRedessin(boolean attendre, Runnable r) {
        if (attendre) racine.postOnAnimationDelayed(r, 48);
        else r.run();
    }

    /** Retour a la sphere : la vague dans l'autre sens, le globe reste en memoire un moment. */
    private void fermerOeil() {
        if (!ecranOeil.estOuvert()) return;
        final boolean vagueAnnulee = vague.enCours();
        if (vagueAnnulee) vague.annuler();
        final android.view.View bouton = ecranOeil.findViewById(R.id.bouton_oeil);
        final float[] centre = centreDe(bouton);
        vague.setLegende("");
        conv.dernierOeil = null;   // ferme par l'utilisateur : on ne le rouvrira pas tout seul
        apresRedessin(vagueAnnulee, () -> capturer(bmp -> vague.jouer(Vague.Sens.FERMER, bmp, centre[0], centre[1], () -> {
            ecranOeil.cacher();
            contenu.setVisibility(android.view.View.VISIBLE);
            if (conv.etat() == Conversation.Etat.REPOS) getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }, null)));
    }

    /** Une photo de l'ecran tel qu'il est (pour la vague). null si le telephone ne veut pas. */
    private void capturer(Consumer<Bitmap> suite) {
        try {
            int w = racine.getWidth(), h = racine.getHeight();
            if (w <= 0 || h <= 0) { suite.accept(null); return; }
            final Bitmap b = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
            int[] loc = new int[2];
            racine.getLocationInWindow(loc);
            PixelCopy.request(getWindow(), new Rect(loc[0], loc[1], loc[0] + w, loc[1] + h), b,
                    res -> suite.accept(res == PixelCopy.SUCCESS ? b : null), fil);
        } catch (Exception e) {
            suite.accept(null);
        }
    }

    /** Le centre d'une vue dans les coordonnees de la racine (d'ou partent les ondes). */
    private float[] centreDe(android.view.View v) {
        int[] a = new int[2], r = new int[2];
        if (v == null || v.getWidth() == 0) return new float[]{racine.getWidth() / 2f, racine.getHeight() / 2f};
        v.getLocationInWindow(a);
        racine.getLocationInWindow(r);
        return new float[]{a[0] - r[0] + v.getWidth() / 2f, a[1] - r[1] + v.getHeight() / 2f};
    }

    @Override
    public void onBackPressed() {
        if (ecranOeil.estOuvert()) {
            fermerOeil();
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        traiterIntention(intent);
    }

    private void traiterIntention(Intent i) {
        if (i == null) return;
        String a = i.getAction();
        if (Intent.ACTION_SEND.equals(a)) {   // « Partager » depuis une autre appli
            Uri u = i.getParcelableExtra(Intent.EXTRA_STREAM);
            String t = i.getStringExtra(Intent.EXTRA_TEXT);
            i.setAction(Intent.ACTION_MAIN);
            if (u != null) recevoirFichier(u, i.getType());
            else if (t != null && !t.trim().isEmpty()) recevoirTexte(t.trim(), i.getStringExtra(Intent.EXTRA_SUBJECT));
            return;
        }
        boolean ecouter = i.getBooleanExtra(EXTRA_ECOUTER, false)
                || Intent.ACTION_ASSIST.equals(a) || Intent.ACTION_VOICE_COMMAND.equals(a);
        if (ecouter) {
            i.removeExtra(EXTRA_ECOUTER);
            fil.postDelayed(() -> {
                if (conv.etat() == Conversation.Etat.REPOS) appuiCercle();
            }, 250);
        }
    }

    // ---------- permissions ----------
    private List<String> manquantes(boolean pourLunettes) {
        List<String> l = new ArrayList<>();
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
            l.add(Manifest.permission.RECORD_AUDIO);
        if (checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            l.add(Manifest.permission.ACCESS_FINE_LOCATION);
            l.add(Manifest.permission.ACCESS_COARSE_LOCATION);
        }
        if (pourLunettes && Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            l.add(Manifest.permission.POST_NOTIFICATIONS);
        if (pourLunettes && Build.VERSION.SDK_INT >= 31
                && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED)
            l.add(Manifest.permission.BLUETOOTH_CONNECT);
        return l;
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        if (code == Commandes.PERMISSION_COMMANDE) {
            commandes.reprendre();
            return;
        }
        if (!conv.micAutorise()) {
            info("Sans le micro, je ne peux pas t'entendre. Tu peux m'écrire en bas.");
            return;
        }
        if (ecouterApresPermission) {
            ecouterApresPermission = false;
            conv.appui(false);
        }
        if (lunettesApresPermission) {
            lunettesApresPermission = false;
            ServiceLunettes.demarrer(this);
            fil.postDelayed(this::afficherLunettes, 300);
        }
    }

    // ---------- actions ----------
    private void appuiCercle() {
        if (!conv.micAutorise()) {
            ecouterApresPermission = true;
            requestPermissions(manquantes(false).toArray(new String[0]), DEMANDE_PERMISSIONS);
            return;
        }
        conv.appui(false);
    }

    private void envoyerTexte() {
        String t = saisie.getText().toString().trim();
        if (t.isEmpty() && conv.pieceJointe == null) return;
        saisie.setText("");
        entendu.setText(t.isEmpty() ? "Toi : (fichier envoyé)" : "Toi : " + t);
        reponse.setText("");
        conv.envoyer(t);
    }

    private void basculerLunettes() {
        if (ServiceLunettes.actif) {
            ServiceLunettes.arreter(this);
            fil.postDelayed(this::afficherLunettes, 300);
            return;
        }
        List<String> m = manquantes(true);
        if (!m.isEmpty()) {
            lunettesApresPermission = true;
            requestPermissions(m.toArray(new String[0]), DEMANDE_PERMISSIONS);
            return;
        }
        ServiceLunettes.demarrer(this);
        fil.postDelayed(this::afficherLunettes, 300);
    }

    private void afficherLunettes() {
        lunettes.setActif(ServiceLunettes.actif);
    }

    /** La boite ecrite n'apparait que pour le diagnostic, ou quelques secondes si la voix n'a pas marche. */
    private final Runnable cacherBoite = () -> { if (!diagnostic) boite.setVisibility(android.view.View.GONE); };

    private void montrerBoite(long ms) {
        fil.removeCallbacks(cacherBoite);
        boite.setVisibility(android.view.View.VISIBLE);
        if (ms > 0) fil.postDelayed(cacherBoite, ms);
    }

    private void afficherDiagnostic() {
        if (!diagnostic) {
            if (boite.getVisibility() == android.view.View.VISIBLE && entendu.getText().toString().startsWith("DIAGNOSTIC")) boite.setVisibility(android.view.View.GONE);
            return;
        }
        montrerBoite(0);
        SharedPreferences p = getSharedPreferences(ServiceLunettes.PREFS, MODE_PRIVATE);
        entendu.setText("DIAGNOSTIC (appui long sur « Lunettes » pour le cacher) :");
        String j = p.getString("journal_touches", "");
        reponse.setText(j.isEmpty() ? "Aucune touche reçue pour l'instant. Active « Lunettes », puis tape sur la branche." : j);
    }

    // ---------- bouton « + » : document, photo, appareil photo ----------
    private void menuPlus(android.view.View v) {
        PopupMenu m = new PopupMenu(this, v);
        m.getMenu().add(0, CHOISIR_DOCUMENT, 0, "Document");
        m.getMenu().add(0, CHOISIR_PHOTO, 1, "Photo de la galerie");
        m.getMenu().add(0, PRENDRE_PHOTO, 2, "Prendre une photo");
        m.setOnMenuItemClickListener(item -> {
            try {
                switch (item.getItemId()) {
                    case CHOISIR_DOCUMENT: {
                        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                        startActivityForResult(i, CHOISIR_DOCUMENT);
                        break;
                    }
                    case CHOISIR_PHOTO: {
                        Intent i = new Intent(Intent.ACTION_GET_CONTENT).addCategory(Intent.CATEGORY_OPENABLE).setType("image/*");
                        startActivityForResult(Intent.createChooser(i, "Choisir une photo"), CHOISIR_PHOTO);
                        break;
                    }
                    case PRENDRE_PHOTO: {
                        File f = Fichiers.fichierPhoto(this);
                        f.delete();
                        Intent i = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
                        i.putExtra(android.provider.MediaStore.EXTRA_OUTPUT, Fichiers.uriPhoto());
                        i.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        startActivityForResult(i, PRENDRE_PHOTO);
                        break;
                    }
                }
            } catch (Exception e) {
                info("Je n'arrive pas à ouvrir ça sur ce téléphone.");
            }
            return true;
        });
        m.show();
    }

    @Override
    protected void onActivityResult(int code, int resultat, Intent data) {
        super.onActivityResult(code, resultat, data);
        if (resultat != RESULT_OK) return;
        if (code == PRENDRE_PHOTO) {
            File f = Fichiers.fichierPhoto(this);
            if (f.length() == 0) {
                info("La photo n'a pas été enregistrée, réessaie.");
                return;
            }
            String nom = "photo_" + new java.text.SimpleDateFormat("yyyy-MM-dd_HH'h'mm", java.util.Locale.FRANCE).format(new java.util.Date()) + ".jpg";
            File dest = new File(dossierPieces(), nom);
            f.renameTo(dest);
            pieceRecue(new Porte.PieceJointe(dest, nom, "image/jpeg"));
        } else if ((code == CHOISIR_DOCUMENT || code == CHOISIR_PHOTO) && data != null && data.getData() != null) {
            recevoirFichier(data.getData(), null);
        }
    }

    private File dossierPieces() {
        File d = new File(getCacheDir(), "pieces");
        d.mkdirs();
        File[] vieux = d.listFiles();   // on ne garde que la derniere piece jointe
        if (vieux != null) for (File x : vieux) if (conv.pieceJointe == null || !x.equals(conv.pieceJointe.fichier)) x.delete();
        return d;
    }

    /** Copie le fichier choisi dans l'appli (hors du fil principal), puis le joint au prochain message. */
    private void recevoirFichier(Uri u, String typeIndique) {
        info("Je prépare le fichier…");
        new Thread(() -> {
            String nom = "fichier", type = typeIndique;
            long taille = -1;
            try (Cursor c = getContentResolver().query(u, null, null, null, null)) {
                if (c != null && c.moveToFirst()) {
                    int n = c.getColumnIndex(OpenableColumns.DISPLAY_NAME), t = c.getColumnIndex(OpenableColumns.SIZE);
                    if (n >= 0 && c.getString(n) != null) nom = c.getString(n);
                    if (t >= 0 && !c.isNull(t)) taille = c.getLong(t);
                }
            } catch (Exception ignore) {
            }
            String typeResolu = getContentResolver().getType(u);
            if (typeResolu != null) type = typeResolu;
            if (!nom.contains(".") && type != null) {
                String ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(type);
                if (ext != null) nom += "." + ext;
            }
            final String nomF = nom, typeF = type;
            if (taille > TAILLE_MAX) {
                fil.post(() -> info("Fichier trop gros (plus de 15 Mo) : envoie-le plutôt sur Telegram."));
                return;
            }
            File dest = new File(dossierPieces(), nomF.replaceAll("[\\\\/:*?\"<>|]", "_"));
            long copie = 0;
            try (InputStream in = getContentResolver().openInputStream(u); OutputStream out = new FileOutputStream(dest)) {
                byte[] b = new byte[16384];
                int n;
                while ((n = in.read(b)) > 0) {
                    copie += n;
                    if (copie > TAILLE_MAX) throw new IllegalStateException("trop gros");
                    out.write(b, 0, n);
                }
            } catch (Exception e) {
                dest.delete();
                final boolean gros = copie > TAILLE_MAX;
                fil.post(() -> info(gros ? "Fichier trop gros (plus de 15 Mo) : envoie-le plutôt sur Telegram."
                        : "Je n'arrive pas à lire ce fichier."));
                return;
            }
            fil.post(() -> pieceRecue(new Porte.PieceJointe(dest, nomF, typeF)));
        }).start();
    }

    /** Un texte ou un lien partage depuis une autre appli : il part comme une petite piece jointe. */
    private void recevoirTexte(String texte, String sujet) {
        boolean lien = texte.matches("(?s)^https?://\\S+$");
        String nom = lien ? "lien partagé.txt" : "texte partagé.txt";
        File dest = new File(dossierPieces(), lien ? "lien.txt" : "texte.txt");
        try (OutputStream out = new FileOutputStream(dest)) {
            out.write(((sujet != null && !sujet.isEmpty() ? sujet + "\n" : "") + texte).getBytes("UTF-8"));
        } catch (Exception e) {
            return;
        }
        pieceRecue(new Porte.PieceJointe(dest, nom, "text/plain"));
    }

    /** La piece jointe est prete : elle entre dans la sphere, puis Archi ecoute la consigne. */
    private void pieceRecue(Porte.PieceJointe pj) {
        conv.pieceJointe = pj;
        afficherPiece();
        sphere.absorber(pj.nom);
        info("Dis à Archi quoi faire avec « " + pj.nom + " ».");
        fil.postDelayed(() -> {
            if (conv.pieceJointe == pj && conv.etat() == Conversation.Etat.REPOS && conv.micAutorise()) conv.appui(false);
        }, 1200);
    }

    private void afficherPiece() {
        if (conv.pieceJointe == null) {
            piece.setVisibility(android.view.View.GONE);
        } else {
            piece.setText("📎  " + conv.pieceJointe.nom + "     ✕");
            piece.setVisibility(android.view.View.VISIBLE);
        }
    }

    /** Appele par la conversation quand Archi a bien recu le fichier. */
    public void pieceEnvoyee() {
        afficherPiece();
    }

    /** Petit message en haut (erreur, consigne...) : il s'efface tout seul apres quelques secondes. */
    private final Runnable effacerInfo = () -> etatTxt.setText("");

    private void info(String m) {
        fil.removeCallbacks(effacerInfo);
        etatTxt.setText(m == null ? "" : m);
        if (m != null && !m.isEmpty()) fil.postDelayed(effacerInfo, 7000);
    }

    // ---------- Conversation.Ecouteur ----------
    @Override
    public void etat(Conversation.Etat e, String message) {
        // la sphere montre l'etat (ecoute, reflexion, parole) : en haut, seulement les vrais messages
        switch (e) {
            case REPOS:
                sphere.setMode("repos");
                info(message);
                if (!ecranOeil.estOuvert()) getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                if (message != null && message.startsWith("Réponse écrite seulement")) montrerBoite(25000);
                afficherDiagnostic();
                break;
            case PREPARE:
            case ECOUTE:
                sphere.setMode("ecoute");
                info(conv.pieceJointe != null ? "Dis à Archi quoi faire avec « " + conv.pieceJointe.nom + " »." : "");
                getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                break;
            case ATTENTE:
                sphere.setMode("reflechit");
                info("");
                break;
            case PARLE:
                // la sphere prend la forme du sujet (engrenages, coeur, meteo...) ; sinon l'egaliseur
                sphere.setDocument(conv.dernierDocument);
                sphere.setMode(Sphere.estSujet(conv.dernierSujet) ? conv.dernierSujet : "parle");
                sphere.montrerMots(conv.derniersMots, conv.dureeVoix);   // les mots-cles pendant qu'il parle
                info("");
                break;
        }
        ecranOeil.setEtat(e, message, e == Conversation.Etat.PARLE ? conv.derniereReponse : null);
    }

    /** Appui long sur la bulle du document : ouvrir, partager, ranger dans Telechargements, supprimer. */
    private void menuDocument(java.io.File f) {
        if (f == null || !f.isFile()) { oublierDocument(null); return; }
        PopupMenu m = new PopupMenu(this, sphere, android.view.Gravity.CENTER);
        m.getMenu().add(0, 1, 0, "Ouvrir");
        m.getMenu().add(0, 2, 1, "Partager…");
        m.getMenu().add(0, 3, 2, "Ranger dans Téléchargements");
        m.getMenu().add(0, 4, 3, "Supprimer");
        m.setOnMenuItemClickListener(item -> {
            switch (item.getItemId()) {
                case 1: ouvrirDocument(f); break;
                case 2: partagerDocument(f); break;
                case 3: rangerDocument(f); break;
                case 4: confirmerSuppression(f); break;
            }
            return true;
        });
        m.show();
    }

    private void partagerDocument(java.io.File f) {
        try {
            Uri u = Fichiers.uriDocument(f.getName());
            Intent i = new Intent(Intent.ACTION_SEND).setType(Fichiers.typeDe(f.getName()))
                    .putExtra(Intent.EXTRA_STREAM, u).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(Intent.createChooser(i, "Partager " + f.getName()));
        } catch (Exception e) {
            info("Je n'arrive pas à partager ce document.");
        }
    }

    /** Copie le document dans Telechargements/Archi (visible dans « Fichiers »), puis retire la bulle. */
    private void rangerDocument(java.io.File f) {
        if (Build.VERSION.SDK_INT < 29) { info("Sur ce téléphone, utilise « Partager… » pour l'enregistrer."); return; }
        try {
            android.content.ContentValues v = new android.content.ContentValues();
            v.put(android.provider.MediaStore.MediaColumns.DISPLAY_NAME, f.getName());
            v.put(android.provider.MediaStore.MediaColumns.MIME_TYPE, Fichiers.typeDe(f.getName()));
            v.put(android.provider.MediaStore.MediaColumns.RELATIVE_PATH, android.os.Environment.DIRECTORY_DOWNLOADS + "/Archi");
            Uri dest = getContentResolver().insert(android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            if (dest == null) throw new IllegalStateException("pas de place");
            try (InputStream in = new java.io.FileInputStream(f); OutputStream out = getContentResolver().openOutputStream(dest)) {
                byte[] b = new byte[16384];
                int n;
                while ((n = in.read(b)) > 0) out.write(b, 0, n);
            }
            oublierDocument(f);
            f.delete();
            info("Rangé dans Téléchargements › Archi.");
        } catch (Exception e) {
            info("Je n'arrive pas à le ranger : " + e.getMessage());
        }
    }

    private void confirmerSuppression(java.io.File f) {
        new android.app.AlertDialog.Builder(this)
                .setTitle("Supprimer « " + f.getName() + " » ?")
                .setMessage("Il sera effacé du téléphone (l'original reste sur le PC).")
                .setNegativeButton("Annuler", null)
                .setPositiveButton("Supprimer", (d, w) -> {
                    oublierDocument(f);
                    f.delete();
                    info("Document supprimé du téléphone.");
                })
                .show();
    }

    /** Retire la bulle (et ne la remet pas au prochain lancement). */
    private void oublierDocument(java.io.File f) {
        conv.dernierDocumentFichier = null;
        conv.dernierDocument = "";
        getSharedPreferences("archi", MODE_PRIVATE).edit().remove("dernier_document").apply();
        sphere.setDocumentFichier(null);
    }

    /** Toucher la bulle du document : on l'ouvre avec l'appli du telephone qui sait le lire (PDF, image...). */
    private void ouvrirDocument(java.io.File f) {
        if (f == null || !f.isFile()) { info("Le document n'est plus là."); sphere.setDocumentFichier(null); return; }
        try {
            Uri u = Fichiers.uriDocument(f.getName());
            Intent i = new Intent(Intent.ACTION_VIEW).setDataAndType(u, Fichiers.typeDe(f.getName()))
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(Intent.createChooser(i, "Ouvrir " + f.getName()));
        } catch (Exception e) {
            info("Aucune appli sur ce téléphone ne sait ouvrir ce document.");
        }
    }

    @Override
    public void reponse(String quoi, String texte) {
        diagnostic = false;
        sphere.setDocumentFichier(conv.dernierDocumentFichier);
        entendu.setText(quoi == null || quoi.isEmpty() ? "" : "Toi : " + quoi);
        reponse.setText(texte);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // appli a l'ecran : le bouton des ecouteurs agit directement
        if (keyCode == KeyEvent.KEYCODE_HEADSETHOOK || keyCode == KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
                || keyCode == KeyEvent.KEYCODE_MEDIA_PLAY || keyCode == KeyEvent.KEYCODE_MEDIA_PAUSE) {
            if (event.getRepeatCount() == 0) conv.appui(true);
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        fil.removeCallbacksAndMessages(null);
        ecranOeil.detruire();
        super.onDestroy();
    }
}
