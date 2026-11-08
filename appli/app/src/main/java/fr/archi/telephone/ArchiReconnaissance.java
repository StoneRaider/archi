package fr.archi.telephone;

import android.content.Intent;
import android.speech.RecognitionService;
import android.speech.SpeechRecognizer;

/** Obligatoire pour etre « assistant » sur Android ; Archi n'offre pas la dictee aux autres applis. */
public class ArchiReconnaissance extends RecognitionService {
    @Override
    protected void onStartListening(Intent intent, Callback cb) {
        try {
            cb.error(SpeechRecognizer.ERROR_CLIENT);
        } catch (Exception ignore) {
        }
    }

    @Override
    protected void onCancel(Callback cb) {
    }

    @Override
    protected void onStopListening(Callback cb) {
    }
}
