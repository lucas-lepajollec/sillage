# Références UI et réutilisation

Inspection directe effectuée le 2026-10-26 via le connecteur GitHub puis clones locaux superficiels pour lire les composants, pas seulement les captures des README.

| Source inspectée | Révision | Composants lus | Usage dans Sillage |
| --- | --- | --- | --- |
| [FileBrowser Quantum](https://github.com/gtsteffaniak/filebrowser) | `b0f6d53f49a87eae32e2022819fa116da13349a7` | `frontend/src/components/files/Breadcrumbs.vue`, `FileTree.vue`, `ListingHeader.vue`, `ProgressBar.vue` | Navigation hiérarchique avec chargement à l’ouverture, fil d’Ariane cliquable, tableau compact. Patterns réimplémentés pour React ; aucun code Vue copié. |
| [shadcn-admin](https://github.com/satnaing/shadcn-admin) | `e16c87f213a5ba5e45964e9b67c792105ec74d26` | `src/components/ui/button.tsx`, `src/components/data-table/column-header.tsx`, `src/features/tasks/components/tasks-table.tsx`, `src/components/layout/nav-group.tsx` | Structure Button/CVA/Slot adaptée, pattern de tableau TanStack à sélection/tri/pagination contrôlés, sidebar active. |

FileBrowser est sous Apache-2.0 ; l’inspection n’a entraîné aucune copie de son code. shadcn-admin est sous MIT (Copyright 2024 Sat Naing) : notice conservée dans `frontend/notices/shadcn-admin-LICENSE`, provenance et modifications signalées dans le Button adapté. Les dépendances React, TanStack, Lucide, Radix et Tailwind sont utilisées directement avec leur licence propre ; pas de copie d’un dashboard entier.

## Brief de réalisation

- Produit personnel, interface française : parcourir → scanner → sélectionner → traduire → consulter/exporter.
- Direction : atelier de sous-titres, graphite chaud, accent ambre discret, Inter, lignes et contrôles compacts, aucun dashboard statistique ni lecteur vidéo fictif.
- Trois sections : Explorer, Traductions, Paramètres. Détails et répliques dans un drawer contextuel ; barre de sélection fixe pour lancer un lot.
- État serveur via TanStack Query ; fichiers via TanStack Table. Aucun jeu de données de démonstration dans le bundle de production. Clé d’accès uniquement en sessionStorage ; préférences thème/filtres seulement en localStorage.
- La synchronisation automatique exige une décision explicite dans l’aperçu. Les timestamps proposés ne sont affichés que lorsqu’ils proviennent du backend.

## Vérification

Les commandes et les preuves rendues sont consignées à la fin de la réalisation. Le parcours fonctionnel peut utiliser des routes HTTP interceptées uniquement dans `frontend/tests/` ; les tests métier du pipeline restent côté backend. Les appels payants réels nécessitent un provider configuré et ne doivent pas être simulés dans l’application.
