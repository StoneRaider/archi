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
    }

    private final String url;
    private final String cle;

    public Porte(Context c) {
        url = Reglages.url(c);
        cle = Reglages.cle(c);
    }

    private HttpURLConnection ouvrir(String typeContenu) throws Exception {
        HttpURLConnection cx = (HttpURLConnection) new URL(url).openConnection();
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
        return r;
    }
}
