# Garanties et limites

## ASS / SSA / SRT

Le parser conserve le document décodé et remplace uniquement ses plages de texte traduisible. pysubs2 contrôle le nombre d’événements et leurs timings avant et après reconstruction. Sans correction, les timestamps restent écrits exactement comme dans la source ; pas de normalisation par sérialisation générale. Les lignes non modifiées, styles, commentaires, métadonnées, pièces jointes textuelles et ordre restent identiques dans ce document décodé. L’encodage d’export est UTF-8 ; les fichiers legacy nécessitant une détection produisent un avertissement.

Les overrides et retours `\N`/`\n` sont protégés par placeholders ordonnés. Un modèle ne peut introduire une balise ou un événement. Les panneaux avec positionnement statique sont traduits si leur structure est prise en charge. Les dessins (y compris mêlés au texte), karaokés `\k`/`\kf`/`\ko`, transformations `\t`, mouvements `\move`, effets personnalisés et syntaxes ambiguës sont conservés et signalés. Le résultat passe en vérification requise. Il n’y a pas de traduction karaoké parallèle générée sans contrôle de rendu.

Le modèle peut conserver l’ordre des balises tout en produisant une traduction dont la mise en emphase est imparfaite ; aucune validation structurelle ne prouve la qualité sémantique. Les chevauchements intentionnels sont préservés. Les ASS non standard/incomplets peuvent être refusés : l’application ne prétend pas accepter tous les fansubs. Les polices, collisions visuelles, longueurs de panneaux et effets de composition doivent être vérifiés dans votre lecteur. Aucun test ici ne certifie toute une collection Jellyfin.

## Synchronisation

La traduction ne vérifie pas l’alignement audio. Un décalage manuel est enregistré et soumis aux mêmes contrôles de durée. La précision ASS est de 10 ms : un décalage non représentable est refusé, sans arrondi caché.

Le mode automatique extrait **uniquement la première piste audio**, mono 16 kHz, sans flux sous-titres. WebRTC VAD produit une activité de parole à 20 ms ; ffsubsync FFTAligner propose un offset global borné à ±10 s. Sillage refuse activité trop faible/continue, corrélation faible, pics concurrents, amélioration faible ou désaccord des trois fenêtres. La corrélation affichée est une mesure, pas une probabilité de justesse. Vidéos 2 min–4 h et au moins 20 répliques seulement. Les panneaux positionnés sont exclus du signal de dialogue.

Cette heuristique ne prouve pas un alignement phonétique. La mauvaise langue audio, les chansons, doublages, silences, recoupes et dérives peuvent imposer un refus ou tromper la proposition. Vérifiez l’aperçu avant d’accepter. Aucune correction incertaine n’est publiée automatiquement. Refuser la proposition exporte les timings source ; annuler laisse les checkpoints sans sortie. Le mode automatique ne fait ni rescaling ni découpe. Choix d’une autre piste audio, alass et correction des montages restent hors de cette V1.

## Fichiers et exploitation

Toutes les entrées média passent par les racines canoniques autorisées ; la navigation masque les liens symboliques. Les outils reçoivent des listes d’arguments, jamais une commande shell interpolée. Les sorties utilisent un fichier temporaire et une publication atomique exclusive dans un descripteur de dossier ouvert sans suivi de liens. Un fichier déjà présent n’est jamais remplacé. Une coupure avant publication ne laisse pas de résultat définitif partiel. Une coupure pendant l’écriture peut laisser un temporaire caché ; il n’est pas annoncé comme résultat.

Le propriétaire du stockage et l’administrateur du NAS restent des acteurs de confiance. Les racines médias et `/config` ne doivent pas être modifiées par des utilisateurs hostiles pendant le traitement. Les transactions SQLite et empreintes de source/configuration protègent la reprise ; ce n’est pas une sandbox système contre l’administrateur. Sauvegardes et espace libre restent à la charge de l’opérateur.

Les appels cloud sortants envoient le texte des répliques, leur contexte et le glossaire au provider choisi. Les requêtes en cours d’annulation peuvent déjà être facturées. Aucun tarif estimé n’est affiché ; les tokens rapportés viennent des réponses du provider et peuvent ne pas couvrir un échec réseau. Un test HTTP déterministe ne prouve ni les permissions d’un compte réel ni le français d’un modèle.
