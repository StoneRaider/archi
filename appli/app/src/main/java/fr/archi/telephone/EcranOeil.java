package fr.archi.telephone;

import android.annotation.SuppressLint;
import android.content.Context;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.AttributeSet;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * L'ecran de l'oeil : le globe (gods-eye-view, servi par le PC a travers la porte de l'oeil) en plein ecran,
 * un bandeau en haut (ce qu'on regarde), un bouton en bas pour continuer a parler a Archi.
 * Le globe previent l'appli quand il est pret et quand il a applique une demande (pont JavaScript « ArchiOeil »,
 * voir gods-eye-view/src/app/archi.js) ; une nouvelle cible arrive soit par un rechargement, soit, si le globe
 * est deja ouvert, par un simple message (sans recharger).
 * La toile (WebView) est creee par le code : si son moteur plante (le globe est gourmand), on la refait au lieu
 * de laisser Android tuer l'appli.
 */
public class EcranOeil extends FrameLayout {
    public interface Ecouteur {
        void oeilPret();                 // le globe est la (ou a renonce) : la vague peut se dissoudre
        void oeilErreur(String message); // l'oeil ne repond pas : on le dit, la vague se dissout quand meme
        void fermer();                   // J veut revenir a la sphere
        void parler();                   // J appuie sur le bouton
    }

    private static final long DELAI_PRET_MS = 25000;      // au-dela, on montre ce qu'on a
    private static final long DELAI_DEMANDE_MS = 12000;   // une mise a jour en direct qui ne repond pas
    private static final long VIE_CACHE_MS = 15 * 60 * 1000; // ferme depuis 15 min : on libere le globe

    private WebView toile;
    private TextView titre, sousTitre, etatTxt, legende, message, fermerBtn;
    private View jauge;
    private BoutonOeil bouton;
    private Ecouteur ecouteur;
    private final Handler fil = new Handler(Looper.getMainLooper());
    private String hote = "", jetonAttendu = "";
    private boolean ouvert, globePret, pageChargee, attendPret, attendDemande;
    private long fermeDepuis;

    public EcranOeil(Context c) { super(c); init(c); }
    public EcranOeil(Context c, AttributeSet a) { super(c, a); init(c); }

    private void init(Context c) {
        LayoutInflater.from(c).inflate(R.layout.vue_oeil, this, true);
        titre = findViewById(R.id.titre_oeil);
        sousTitre = findViewById(R.id.sous_titre_oeil);
        etatTxt = findViewById(R.id.etat_oeil);
        legende = findViewById(R.id.legende_oeil);
        message = findViewById(R.id.message_oeil);
        fermerBtn = findViewById(R.id.fermer_oeil);
        jauge = findViewById(R.id.jauge_oeil);
        bouton = findViewById(R.id.bouton_oeil);
        setBackgroundColor(0xFF0B1410);
        setVisibility(GONE);
        toile = creerToile();
        fermerBtn.setOnClickListener(v -> { if (ecouteur != null) ecouteur.fermer(); });
        bouton.setOnClickListener(v -> { if (ecouteur != null) ecouteur.parler(); });
        message.setOnClickListener(v -> message.setVisibility(GONE));
    }

    /** La toile du globe, tout en dessous des autres vues. null si le telephone n'a pas de WebView utilisable. */
    @SuppressLint("SetJavaScriptEnabled")
    private WebView creerToile() {
        WebView w;
        try {
            w = new WebView(getContext());
        } catch (Throwable e) {
            return null;
        }
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setUserAgentString(s.getUserAgentString() + " ArchiOeil/1.0");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(w, false);
        w.setBackgroundColor(0xFF0B1410);
        w.addJavascriptInterface(new Pont(), "ArchiOeil");
        w.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                // on reste chez nous : le globe ne doit pas emmener l'appli ailleurs
                return u == null || u.getHost() == null || !u.getHost().equalsIgnoreCase(hote);
            }

            @Override
            public void onPageStarted(WebView v, String url, Bitmap favicon) {
                pageChargee = false;
                jauge.setVisibility(VISIBLE);
                jauge.animate().cancel();
                jauge.setAlpha(1f);
                jauge.setScaleX(0.08f);
                jauge.animate().scaleX(0.85f).setDuration(9000).start();
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                pageChargee = true;
                // le globe dit lui-meme quand il est pret ; s'il ne le dit pas, on montre apres un instant
                fil.postDelayed(() -> { if (!globePret && attendPret) pret(); }, 6000);
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) erreur("L'œil est injoignable. Le PC ou le tunnel n'est pas allumé ?");
            }

            @Override
            public void onReceivedHttpError(WebView v, WebResourceRequest r, WebResourceResponse e) {
                if (!r.isForMainFrame()) return;
                int code = e.getStatusCode();
                if (code == 404) erreur("Le lien de l'œil a expiré. Redemande à Archi.");
                else if (code == 502 || code == 503) erreur("Le globe est éteint sur le PC (" + code + ").");
                else if (code >= 400) erreur("L'œil répond une erreur " + code + ".");
            }

            @Override
            public boolean onRenderProcessGone(WebView v, RenderProcessGoneDetail d) {
                // le moteur de la page est mort (memoire) : on refait une toile plutot que de laisser tuer l'appli
                fil.post(() -> {
                    try {
                        removeView(v);
                        v.destroy();
                    } catch (Exception ignore) {
                    }
                    if (toile == v) {
                        toile = creerToile();
                        if (toile != null) addView(toile, 0, new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
                    }
                    globePret = false;
                    pageChargee = false;
                    if (ouvert) erreur("Le globe a planté (mémoire). Redemande à Archi.");
                });
                return true;
            }
        });
        w.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                request.deny();   // ni micro ni camera pour la page
            }

            @Override
            public void onProgressChanged(WebView view, int p) {
                if (p >= 100) jauge.animate().alpha(0f).setDuration(600).withEndAction(() -> { jauge.setVisibility(GONE); jauge.setAlpha(1f); }).start();
            }
        });
        addView(w, 0, new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        return w;
    }

    public void setEcouteur(Ecouteur e) { ecouteur = e; }
    public void setMicro(Sphere.Niveau n) { bouton.setMicro(n); }
    public boolean estOuvert() { return ouvert; }
    public boolean estPret() { return globePret; }

    /** Le globe deja charge peut-il simplement recevoir la nouvelle demande (meme serveur, deja pret) ? */
    public boolean peutMettreAJour(JSONObject oeil) {
        if (!ouvert || !globePret || toile == null || toile.getUrl() == null) return false;
        Uri u = Uri.parse(oeil.optString("url", ""));
        return u.getHost() != null && u.getHost().equalsIgnoreCase(hote) && oeil.optJSONObject("vue") != null;
    }

    /** Ouvre l'oeil sur une cible : charge la page (ou la recharge si elle n'est plus la). */
    public void ouvrir(JSONObject oeil) {
        String url = oeil.optString("url", "");
        Uri u = Uri.parse(url);
        hote = u.getHost() == null ? "" : u.getHost();
        jetonAttendu = oeil.optString("jeton", "");
        afficherTitres(oeil);
        message.setVisibility(GONE);
        globePret = false;
        pageChargee = false;
        attendPret = true;
        attendDemande = false;
        ouvert = true;
        fermeDepuis = 0;
        setVisibility(VISIBLE);
        if (toile == null) {
            erreur("Ce téléphone n'a pas de navigateur intégré (WebView) utilisable.");
            return;
        }
        toile.onResume();
        toile.resumeTimers();
        toile.loadUrl(url);
        fil.removeCallbacks(delaiPret);
        fil.postDelayed(delaiPret, DELAI_PRET_MS);
    }

    /** Le globe est deja la : on lui envoie la nouvelle vue par message, sans recharger. */
    public void mettreAJour(JSONObject oeil) {
        jetonAttendu = oeil.optString("jeton", "");
        afficherTitres(oeil);
        message.setVisibility(GONE);
        attendDemande = true;
        attendPret = false;
        String js = "window.postMessage({type:'gev:archi', id:" + JSONObject.quote(jetonAttendu)
                + ", vue:" + oeil.optJSONObject("vue") + ", actions:" + (oeil.optJSONArray("actions") == null ? "[]" : oeil.optJSONArray("actions"))
                + "}, '*'); true;";
        toile.evaluateJavascript(js, null);
        fil.removeCallbacks(delaiDemande);
        fil.postDelayed(delaiDemande, DELAI_DEMANDE_MS);
    }

    private final Runnable delaiPret = () -> { if (attendPret) pret(); };
    private final Runnable delaiDemande = () -> { if (attendDemande) pret(); };

    private void afficherTitres(JSONObject oeil) {
        titre.setText(Logo.poser(getContext(), oeil.optString("titre", "L'œil")));
        String st = oeil.optString("sous_titre", "");
        sousTitre.setText(Logo.poser(getContext(), st));
        sousTitre.setVisibility(st.isEmpty() ? GONE : VISIBLE);
    }

    private void pret() {
        attendPret = false;
        attendDemande = false;
        fil.removeCallbacks(delaiPret);
        fil.removeCallbacks(delaiDemande);
        if (ecouteur != null) ecouteur.oeilPret();
    }

    private void erreur(String m) {
        message.setText(Logo.poser(getContext(), m));
        message.setVisibility(VISIBLE);
        jauge.setVisibility(GONE);
        globePret = false;
        attendPret = false;
        attendDemande = false;
        fil.removeCallbacks(delaiPret);
        fil.removeCallbacks(delaiDemande);
        if (ecouteur != null) ecouteur.oeilErreur(m);
    }

    /** Cache l'ecran (retour a la sphere). Le globe reste charge un quart d'heure, pour rouvrir vite. */
    public void cacher() {
        ouvert = false;
        setVisibility(GONE);
        if (toile != null) {
            toile.onPause();
            toile.pauseTimers();
        }
        fermeDepuis = SystemClock.uptimeMillis();
        fil.postDelayed(() -> {
            if (!ouvert && fermeDepuis > 0 && SystemClock.uptimeMillis() - fermeDepuis >= VIE_CACHE_MS && toile != null) {
                toile.resumeTimers();   // sinon la page vide ne se charge pas vraiment
                toile.loadUrl("about:blank");
                globePret = false;
            }
        }, VIE_CACHE_MS + 500);
    }

    /** L'etat de la conversation, pour le bouton et la petite ligne au-dessus. */
    public void setEtat(Conversation.Etat e, String msg, String texteReponse) {
        switch (e) {
            case PREPARE:
            case ECOUTE:
                bouton.setMode("ecoute");
                etatTxt.setText("Je t'écoute…");
                break;
            case ATTENTE:
                bouton.setMode("reflechit");
                etatTxt.setText(Logo.poser(getContext(), "Archi réfléchit…"));
                break;
            case PARLE:
                bouton.setMode("parle");
                etatTxt.setText("");
                if (texteReponse != null && !texteReponse.isEmpty()) {
                    legende.animate().cancel();
                    legende.setText(Logo.poser(getContext(), texteReponse));
                    legende.setAlpha(1f);
                    legende.setVisibility(VISIBLE);
                }
                break;
            default:
                bouton.setMode("repos");
                etatTxt.setText(Logo.poser(getContext(), msg));
                if (legende.getVisibility() == VISIBLE)
                    legende.animate().alpha(0f).setStartDelay(2500).setDuration(900).withEndAction(() -> legende.setVisibility(GONE)).start();
        }
    }

    // ---------- cycle de vie (appele par l'activite) ----------
    public void pause() {
        if (ouvert && toile != null) { toile.onPause(); toile.pauseTimers(); }
    }

    public void reprendre() {
        if (ouvert && toile != null) { toile.onResume(); toile.resumeTimers(); }
    }

    public void detruire() {
        fil.removeCallbacksAndMessages(null);
        try {
            if (toile != null) {
                toile.loadUrl("about:blank");
                removeView(toile);
                toile.destroy();
                toile = null;
            }
        } catch (Exception ignore) {
        }
    }

    /** Le pont par lequel le globe parle a l'appli (archi.js appelle ArchiOeil.evenement(json)). */
    public class Pont {
        @JavascriptInterface
        public void evenement(String json) {
            fil.post(() -> {
                try {
                    JSONObject e = new JSONObject(json);
                    String phase = e.optString("phase", "");
                    if ("pret".equals(phase)) {
                        globePret = true;
                        if (attendPret) pret();
                    } else if ("fin".equals(phase)) {
                        // la fin d'une VIEILLE demande (le globe les traite a la file) ne compte pas
                        String id = e.optString("id", "");
                        if (attendPret || (attendDemande && (id.isEmpty() || id.equals(jetonAttendu)))) pret();
                    }
                } catch (Exception ignore) {
                }
            });
        }
    }
}
