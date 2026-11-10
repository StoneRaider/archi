package fr.archi.telephone;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * Un tout petit « passe-plat » prive : il laisse l'appareil photo ecrire la photo dans le dossier de l'appli
 * (content://fr.archi.local.fichiers/photo.jpg). Rien d'autre n'est accessible.
 */
public class Fichiers extends ContentProvider {
    /** Le nom interne de l'appli (applicationId) + « .fichiers » : le meme que dans AndroidManifest.xml. */
    public static final String AUTORITE = "fr.archi.local.fichiers";
    public static final String PHOTO = "photo.jpg";
    public static final String DOCS = "doc";

    /** Dossier prive ou sont ranges les documents recus du PC. */
    public static File dossierDocuments(android.content.Context c) {
        File d = new File(c.getFilesDir(), "documents");
        d.mkdirs();
        return d;
    }

    /** Adresse d'un document recu, a donner a l'appli qui l'ouvrira. */
    public static Uri uriDocument(String nom) {
        return Uri.parse("content://" + AUTORITE + "/" + DOCS + "/" + Uri.encode(nom));
    }

    /** Nom de fichier sans chemin ni caractere dangereux. */
    public static String nomSur(String nom) {
        String s = nom == null ? "" : nom.replace('\\', '/');
        s = s.substring(s.lastIndexOf('/') + 1).replaceAll("[\\x00-\\x1f\"*:<>?|]", "_").trim();
        if (s.equals(".") || s.equals("..")) s = "";
        return s.length() > 120 ? s.substring(s.length() - 120) : s;
    }

    /** Type MIME d'apres l'extension. */
    public static String typeDe(String nom) {
        String n = nom == null ? "" : nom.toLowerCase();
        if (n.endsWith(".pdf")) return "application/pdf";
        if (n.endsWith(".png")) return "image/png";
        if (n.endsWith(".jpg") || n.endsWith(".jpeg")) return "image/jpeg";
        if (n.endsWith(".txt")) return "text/plain";
        if (n.endsWith(".md")) return "text/markdown";
        if (n.endsWith(".csv")) return "text/csv";
        if (n.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        if (n.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        return "application/octet-stream";
    }

    private static boolean estDocument(Uri uri) {
        java.util.List<String> p = uri.getPathSegments();
        return p != null && p.size() == 2 && DOCS.equals(p.get(0));
    }

    private File fichierDocument(Uri uri) throws FileNotFoundException {
        String nom = nomSur(uri.getLastPathSegment());
        File f = new File(dossierDocuments(getContext()), nom);
        if (nom.isEmpty() || !f.isFile()) throw new FileNotFoundException("document absent");
        return f;
    }

    public static Uri uriPhoto() {
        return Uri.parse("content://" + AUTORITE + "/" + PHOTO);
    }

    public static File fichierPhoto(android.content.Context c) {
        File d = new File(c.getCacheDir(), "camera");
        d.mkdirs();
        return new File(d, PHOTO);
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (estDocument(uri)) {   // un document recu : lecture seule
            if (mode != null && mode.contains("w")) throw new FileNotFoundException("lecture seule");
            return ParcelFileDescriptor.open(fichierDocument(uri), ParcelFileDescriptor.MODE_READ_ONLY);
        }
        if (!PHOTO.equals(uri.getLastPathSegment())) throw new FileNotFoundException("interdit");
        File f = fichierPhoto(getContext());
        return ParcelFileDescriptor.open(f, ParcelFileDescriptor.parseMode(mode));
    }

    @Override
    public String getType(Uri uri) {
        if (estDocument(uri)) return typeDe(uri.getLastPathSegment());
        return "image/jpeg";
    }

    @Override
    public Cursor query(Uri uri, String[] p, String s, String[] a, String o) {
        android.database.MatrixCursor c = new android.database.MatrixCursor(
                new String[]{android.provider.OpenableColumns.DISPLAY_NAME, android.provider.OpenableColumns.SIZE});
        if (estDocument(uri)) {
            try {
                File f = fichierDocument(uri);
                c.addRow(new Object[]{f.getName(), f.length()});
            } catch (FileNotFoundException ignore) {
            }
            return c;
        }
        c.addRow(new Object[]{PHOTO, fichierPhoto(getContext()).length()});
        return c;
    }

    @Override
    public Uri insert(Uri uri, ContentValues v) {
        return null;
    }

    @Override
    public int delete(Uri uri, String s, String[] a) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues v, String s, String[] a) {
        return 0;
    }
}
