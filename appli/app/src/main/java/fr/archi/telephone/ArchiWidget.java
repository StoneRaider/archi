package fr.archi.telephone;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;

/** Widget de l'ecran d'accueil : un rond « A » ; un appui ouvre Archi et lance l'ecoute tout de suite. */
public class ArchiWidget extends AppWidgetProvider {
    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        Intent intent = new Intent(context, MainActivity.class);
        intent.putExtra(MainActivity.EXTRA_ECOUTER, true);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pi = PendingIntent.getActivity(context, 1, intent,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        for (int id : ids) {
            RemoteViews vues = new RemoteViews(context.getPackageName(), R.layout.widget);
            vues.setOnClickPendingIntent(R.id.widget_bouton, pi);
            manager.updateAppWidget(id, vues);
        }
    }
}
