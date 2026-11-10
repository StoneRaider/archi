package fr.archi.telephone;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/** La porte protegee d'Archi sur le PC (n8n, /webhook/telephone-archi). A appeler hors du fil principal. */
public class Porte {
    /** Un fichier joint (document, photo...) envoye avec le message. */
    public static class PieceJointe {
        public final File fichier;
        public final String nom, type;

        public PieceJointe(File f, String nom, String type) {
            fichier = f;
            this.nom = nom;
            this.type = type == null || type.isEmpty() ? "application/octet-stream" : type;
        }
    }

    public static class Reponse {
        public int code;
        public JSONObject json;
        public String erreur;
        /** Quand code == 0 : pourquoi l'appel n'a pas eu lieu (PAS_BRANCHEE, ADRESSE_INTROUVABLE, PAS_DE_REPONSE, SECURITE, AUTRE). */
        public String raison;
    }

    private static final String PAS_BRANCHEE = "PAS_BRANCHEE";

    private final String url;
    private final String cle;

    public Porte(Context c) {
        url = Reglages.url(c);
        cle = Reglages.cle(c);
    }

    private HttpURLConnection ouvrir(String typeContenu) throws Exception {
        return ouvrir(url, typeContenu);
    }

    private HttpURLConnection ouvrir(String adresse, String typeContenu) throws Exception {
        // sans adresse https ni cle, il n'y a nulle part ou envoyer : on le dit tel quel, pas « injoignable »
        if (!adresse.startsWith("https://") || cle.length() < 16) throw new IllegalStateException(PAS_BRANCHEE);
        HttpURLConnection cx = (HttpURLConnection) new URL(adresse).openConnection();
        cx.setRequestMethod("POST");
        cx.setDoOutput(true);
        cx.setConnectTimeout(15000);
        cx.setReadTimeout(240000);
        cx.setRequestProperty("x-archi-cle", cle);
        cx.setRequestProperty("ngrok-skip-browser-warning", "1");
        cx.setRequestProperty("User-Agent", "ArchiTelephone/1.0");
        cx.setRequestProperty("Content-Type", typeContenu);
        return cx;
    }

    /** Envoie un texte ecrit (avec une piece jointe eventuelle). */
    public Reponse texte(String texte, Double lat, Double lon, PieceJointe pj) {
        if (pj != null) return multipart(texte, null, lat, lon, pj);
        try {
            JSONObject corps = new JSONObject();
            corps.put("texte", texte);
            corps.put("source", "appli");
            if (lat != null && lon != null) {
                corps.put("lat", lat);
                corps.put("lon", lon);
            }
            HttpURLConnection cx = ouvrir("application/json; charset=utf-8");
            try (OutputStream o = cx.getOutputStream()) {
                o.write(corps.toString().getBytes(StandardCharsets.UTF_8));
            }
            return lire(cx);
        } catch (Exception e) {
            return erreur(e);
        }
    }

    /**
     * Essai de liaison, juste apres le branchement : la porte du PC repond-elle avec cette cle ?
     * L'en-tete « x-archi-essai » demande a la porte de repondre elle-meme : l'agent n'est pas reveille.
     */
    public Reponse essai() {
        try {
            // on ne touche qu'au chemin (la derniere occurrence), jamais au nom du serveur
            int i = url.lastIndexOf("telephone-archi");
            if (i < 0 || i < url.indexOf('/', 8)) {
                // une adresse saisie a la main, avec un chemin a elle : rien a essayer, et ce n'est pas une panne
                Reponse r = new Reponse();
                r.code = 0;
                r.raison = "SANS_ESSAI";
                r.erreur = "adresse sans telephone-archi";
                return r;
            }
            HttpURLConnection cx = ouvrir(url.substring(0, i) + "telephone-boite" + url.substring(i + "telephone-archi".length()),
                    "application/json; charset=utf-8");
            cx.setReadTimeout(20000);
            cx.setRequestProperty("x-archi-essai", "1");
            try (OutputStream o = cx.getOutputStream()) {
                o.write("{}".getBytes(StandardCharsets.UTF_8));
            }
            return lire(cx);
        } catch (Exception e) {
            return erreur(e);
        }
    }

    /** Envoie un vocal (fichier .m4a), avec une piece jointe eventuelle. */
    public Reponse vocal(File audio, Double lat, Double lon, PieceJointe pj) {
        return multipart(null, audio, lat, lon, pj);
    }

    private Reponse multipart(String texte, File audio, Double lat, Double lon, PieceJointe pj) {
        try {
            String limite = "----archi" + UUID.randomUUID().toString().replace("-", "");
            HttpURLConnection cx = ouvrir("multipart/form-data; boundary=" + limite);
            try (DataOutputStream o = new DataOutputStream(cx.getOutputStream())) {
                champ(o, limite, "source", "appli");
                if (texte != null) champ(o, limite, "texte", texte);
                if (lat != null && lon != null) {
                    champ(o, limite, "lat", String.valueOf(lat));
                    champ(o, limite, "lon", String.valueOf(lon));
                }
                if (pj != null) {
                    champ(o, limite, "nom_fichier", pj.nom);
                    fichier(o, limite, "fichier", ascii(pj.nom), pj.type, pj.fichier);
                }
                if (audio != null) fichier(o, limite, "audio", "question.m4a", "audio/mp4", audio);
                o.writeBytes("--" + limite + "--\r\n");
            }
            return lire(cx);
        } catch (Exception e) {
            return erreur(e);
        }
    }

    private static void fichier(DataOutputStream o, String limite, String champ, String nom, String type, File f) throws Exception {
        o.writeBytes("--" + limite + "\r\n");
        o.writeBytes("Content-Disposition: form-data; name=\"" + champ + "\"; filename=\"" + nom + "\"\r\n");
        o.writeBytes("Content-Type: " + type + "\r\n\r\n");
        try (InputStream in = new FileInputStream(f)) {
            byte[] tampon = new byte[16384];
            int n;
            while ((n = in.read(tampon)) > 0) o.write(tampon, 0, n);
        }
        o.writeBytes("\r\n");
    }

    /** Nom de fichier sans accents ni caracteres speciaux (le vrai nom part a cote, dans nom_fichier). */
    private static String ascii(String nom) {
        String s = java.text.Normalizer.normalize(nom, java.text.Normalizer.Form.NFD).replaceAll("[^\\x20-\\x7E]", "")
                .replaceAll("[\"\\\\]", "_").trim();
        return s.isEmpty() ? "fichier" : s;
    }

    private static void champ(DataOutputStream o, String limite, String nom, String valeur) throws Exception {
        o.writeBytes("--" + limite + "\r\n");
        o.writeBytes("Content-Disposition: form-data; name=\"" + nom + "\"\r\n\r\n");
        o.write(valeur.getBytes(StandardCharsets.UTF_8));
        o.writeBytes("\r\n");
    }

    private static Reponse lire(HttpURLConnection cx) throws Exception {
        Reponse r = new Reponse();
        r.code = cx.getResponseCode();
        InputStream in = r.code < 400 ? cx.getInputStream() : cx.getErrorStream();
        ByteArrayOutputStream tout = new ByteArrayOutputStream();
        if (in != null) {
            byte[] tampon = new byte[16384];
            int n;
            while ((n = in.read(tampon)) > 0) tout.write(tampon, 0, n);
            in.close();
        }
        String corps = tout.toString("UTF-8");
        try {
            r.json = new JSONObject(corps);
        } catch (Exception e) {
            r.erreur = "réponse illisible (" + r.code + ")";
        }
        cx.disconnect();
        return r;
    }

    private static Reponse erreur(Exception e) {
        Reponse r = new Reponse();
        r.code = 0;
        r.erreur = e.getClass().getSimpleName() + (e.getMessage() != null ? " : " + e.getMessage() : "");
        if (e instanceof java.net.MalformedURLException || (e instanceof IllegalStateException && PAS_BRANCHEE.equals(e.getMessage()))) {
            r.raison = PAS_BRANCHEE;
        } else if (e instanceof java.net.UnknownHostException) {
            r.raison = "ADRESSE_INTROUVABLE";
        } else if (e instanceof java.net.SocketTimeoutException || e instanceof java.net.ConnectException
                || e instanceof java.net.NoRouteToHostException) {
            r.raison = "PAS_DE_REPONSE";
        } else if (e instanceof javax.net.ssl.SSLException) {
            r.raison = "SECURITE";
        } else {
            r.raison = "AUTRE";
        }
        return r;
    }

    /**
     * La vraie raison d'un echec, en mots simples : l'appli ne dit jamais « injoignable » sans dire pourquoi ni quoi faire.
     * A appeler quand la reponse n'est pas lisible (r.json == null).
     */
    public static String explication(Context c, Reponse r) {
        String hote = null;
        try {
            hote = android.net.Uri.parse(Reglages.url(c)).getHost();
        } catch (Exception ignore) {
        }
        String ou = hote == null || hote.isEmpty() ? "" : " (" + hote + ")";
        if (r.code == 504 || r.code == 524) {
            // le tunnel a coupe parce que la reponse tardait : le PC est bien la, l'adresse est bonne
            return "Archi a mis trop de temps à répondre (réponse " + r.code + "). Réessaie, ou regarde la fenêtre « Archi » sur le PC.";
        }
        if ("SANS_ESSAI".equals(r.raison)) {
            return "Adresse enregistrée. Je ne peux pas tester la liaison : elle ne contient pas « telephone-archi ». "
                    + "Envoie un message pour l'essayer.";
        }
        if (r.code == 404 || r.code == 502 || r.code == 503 || r.code >= 520) {
            // une reponse, mais pas celle d'Archi : l'adresse du tunnel ne mene plus a ce PC
            return "Le PC n'est plus à cette adresse" + ou + " : réponse " + r.code
                    + ". L'adresse change à chaque lancement d'Archi : rescanne le QR code du PC.";
        }
        if (r.code != 0) return "Problème : " + (r.erreur == null ? "réponse " + r.code : r.erreur) + ".";
        String raison = r.raison == null ? "" : r.raison;
        if (PAS_BRANCHEE.equals(raison)) {
            return "L'appli n'est pas encore branchée sur ton PC. Sur le PC, affiche le QR code de la page d'accueil d'Archi, "
                    + "scanne-le avec l'appareil photo, puis touche « Brancher l'appli ».";
        }
        if ("ADRESSE_INTROUVABLE".equals(raison)) {
            return "Adresse du PC introuvable" + ou + ". Elle change à chaque lancement d'Archi : rescanne le QR code du PC. "
                    + "Sinon, vérifie l'Internet du téléphone.";
        }
        if ("PAS_DE_REPONSE".equals(raison)) {
            return "Le PC ne répond pas" + ou + ". Archi est-il lancé sur le PC ? Si oui, rescanne le QR code.";
        }
        if ("SECURITE".equals(raison)) {
            return "La connexion sécurisée a échoué" + ou + ". Vérifie la date et l'heure du téléphone, puis rescanne le QR code.";
        }
        return "Archi est injoignable" + ou + " : " + (r.erreur == null ? "raison inconnue" : r.erreur) + ".";
    }
}
