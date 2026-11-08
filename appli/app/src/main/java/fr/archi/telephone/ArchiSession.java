package fr.archi.telephone;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.service.voice.VoiceInteractionSession;

/**
 * Le geste « assistant » (appui long sur le bouton d'allumage).
 * Si le mode lunettes est actif, Archi ecoute directement en arriere-plan (meme ecran eteint ou verrouille),
 * avec le micro des lunettes si elles sont branchees, sinon celui du telephone. Sinon, il ouvre l'appli.
 */
public class ArchiSession extends VoiceInteractionSession {
    public ArchiSession(Context c) {
        super(c);
    }

    @Override
    public void onShow(Bundle args, int showFlags) {
        super.onShow(args, showFlags);
        Conversation conv = Conversation.get(getContext());
        if (ServiceLunettes.actif && conv.micAutorise()) {
            conv.appui(true);
            hide();
            return;
        }
        Intent i = new Intent(getContext(), MainActivity.class);
        i.putExtra(MainActivity.EXTRA_ECOUTER, true);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        try {
            if (Build.VERSION.SDK_INT >= 29) startAssistantActivity(i);
            else getContext().startActivity(i);
        } catch (Exception e) {
            try {
                getContext().startActivity(i);
            } catch (Exception ignore) {
            }
        }
        hide();
    }
}
