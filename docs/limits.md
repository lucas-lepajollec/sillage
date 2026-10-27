# Garanties et limites

## ASS / SSA / SRT

Le parser conserve le document décodé et remplace uniquement ses plages de texte traduisible. pysubs2 contrôle le nombre d’événements et leurs timings avant et après reconstruction. Sans correction, les timestamps restent écrits exactement comme dans la source ; pas de normalisation par sérialisation générale. Les lignes non modifiées, styles, commentaires, métadonnées, pièces jointes textuelles et ordre restent identiques dans ce document décodé. L’encodage d’export est UTF-8 ; les fichiers legacy nécessitant une détection produisent un avertissement.

Les overrides et retours `\N`/`\n` sont protégés par placeholders ordonnés. Un modèle ne peut introduire une balise ou un événement. Les panneaux avec positionnement statique sont traduits si leur structure est prise en charge. Les dessins (y compris mêlés au texte), karaokés `\k`/`\kf`/`\ko`, transformations `\t`, mouvements `\move`, effets personnalisés et syntaxes ambiguës sont conservés et signalés. Le résultat passe en vérification requise. Il n’y a pas de traduction karaoké parallèle générée sans contrôle de rendu.

Le modèle peut conserver l’ordre des balises tout en produisant une traduction dont la mise en emphase est imparfaite ; aucune validation structurelle ne prouve la qualité sémantique. Les chevauchements intentionnels sont préservés. Les ASS non standard/incomplets peuvent être refusés : l’application ne prétend pas accepter tous les fansubs. Les polices, collisions visuelles, longueurs de panneaux et effets de composition doivent être vérifiés dans votre lecteur. Aucun test ici ne certifie toute une collection Jellyfin.

L’aperçu distingue les événements traduisibles de ceux conservés sans traduction ; il ne fait aucun appel au fournisseur. Le total d’une traduction compte les événements éligibles, sans dédupliquer les textes répétés. Les avertissements ASS ne sont pas des échecs d’appel au modèle. Par prudence, tout champ ASS « Effect » non vide conserve l’événement sans traduction, même si ce champ seul ne prouve pas une animation.

Le choix de piste se fait dans Sillage, indépendamment du choix de votre lecteur. L’application en groupe compare les métadonnées et ignore les correspondances absentes ou ambiguës ; elle ne garantit pas qu’un titre de piste décrit correctement son contenu. Les choix préparés ne modifient pas les traitements existants. Une reprise utilise la piste initiale ; pour en changer, créez un nouveau traitement. Les anciens traitements sans métadonnées enregistrées peuvent montrer le libellé du conteneur actuel, identifié comme tel, sans certifier son libellé au lancement.

## Synchronisation

La traduction ne vérifie pas l’alignement audio. Un décalage manuel est enregistré et soumis aux mêmes contrôles de durée. La précision ASS est de 10 ms : un décalage non représentable est refusé, sans arrondi caché.

Le mode automatique extrait **uniquement la première piste audio**, mono 16 kHz, sans flux sous-titres. WebRTC VAD produit une activité de parole à 20 ms ; ffsubsync FFTAligner propose un offset global borné à ±10 s. Sillage refuse activité trop faible/continue, corrélation faible, pics concurrents, amélioration faible ou désaccord des trois fenêtres. La corrélation affichée est une mesure, pas une probabilité de justesse. Vidéos 2 min–4 h et au moins 20 répliques seulement. Les panneaux positionnés sont exclus du signal de dialogue.

Cette heuristique ne prouve pas un alignement phonétique. La mauvaise langue audio, les chansons, doublages, silences, recoupes et dérives peuvent imposer un refus ou tromper la proposition. Vérifiez l’aperçu avant d’accepter. Aucune correction incertaine n’est publiée automatiquement. Refuser la proposition exporte les timings source ; annuler laisse les checkpoints sans sortie. Le mode automatique ne fait ni rescaling ni découpe. Choix d’une autre piste audio, alass et correction des montages restent hors de cette V1.

## Fichiers et exploitation

La suppression de l’historique est définitive pour les entrées et leurs checkpoints ; elle conserve les MKV, pistes source, profils et sous-titres exportés. Les traitements actifs doivent d’abord être annulés et avoir terminé leurs opérations en cours. Un nettoyage de fichiers temporaires refusé par les permissions est signalé, même si les entrées SQL ont déjà été supprimées. La réanalyse relit la source sans appeler le modèle ni remettre un traitement en file automatiquement ; l’ancien traitement reste disponible. Une nouvelle traduction ne peut pas écraser un export présent.

Toutes les entrées média passent par les racines canoniques autorisées ; la navigation masque les liens symboliques. Les outils reçoivent des listes d’arguments, jamais une commande shell interpolée. Les sorties utilisent un fichier temporaire et une publication atomique exclusive dans un descripteur de dossier ouvert sans suivi de liens. Un fichier déjà présent n’est jamais remplacé. Une coupure avant publication ne laisse pas de résultat définitif partiel. Une coupure pendant l’écriture peut laisser un temporaire caché ; il n’est pas annoncé comme résultat.

Le propriétaire du stockage et l’administrateur du NAS restent des acteurs de confiance. Les racines médias et `/config` ne doivent pas être modifiées par des utilisateurs hostiles pendant le traitement. Les transactions SQLite, empreintes de source et configurations de traduction enregistrées protègent la reprise ; ce n’est pas une sandbox système contre l’administrateur. Sauvegardes et espace libre restent à la charge de l’opérateur.

Les appels cloud sortants envoient le texte des répliques, leur contexte et le glossaire au provider choisi. Les requêtes en cours d’annulation peuvent déjà être facturées. Aucun tarif estimé n’est affiché ; les tokens rapportés viennent des réponses du provider et peuvent ne pas couvrir un échec réseau. Un test HTTP déterministe ne prouve ni les permissions d’un compte réel ni le français d’un modèle.

Les événements de durée nulle sont conservés sans traduction et signalés pour vérification. Une fin antérieure au début reste une erreur de la piste source : le message précise événement, ligne et horaires ; relancer le LLM ne peut pas corriger ce cas. Aucun timing invalide n’est corrigé arbitrairement.

## Lots et paramètres de reprise

Les lots réduits peuvent remonter après trois vagues complètes réussies ; un événement difficile ne fixe plus un minimum à tous les épisodes suivants. Seules les répliques à identifiant explicite et individuellement validées sont conservées d’une réponse JSON complète. Une réponse tronquée, un identifiant inconnu ou un contenu hors JSON n’est jamais réparé par déduction. Un modèle qui échoue encore sur une seule réplique peut toujours nécessiter une intervention ; aucune garantie de réussite universelle n’est revendiquée.

Le modèle et les langues restent attachés au traitement via un instantané chiffré, tandis que les limites d’exécution du profil s’appliquent à la prochaine vague. « Adapter les paramètres » permet une reprise en place, individuelle ou groupée, avec conservation des segments validés ou remise à zéro explicite. Conserver des segments après changement de modèle peut mélanger les styles ; un changement de langue connu exige de recommencer. Pour un ancien traitement dont le profil avait déjà changé avant la mise à jour, les paramètres initiaux ne sont pas reconstructibles : vérifiez les langues avant de confirmer la conservation. Ni les MKV ni les exports présents ne sont écrasés.
