# Réutilisation et architecture

Étude du code source effectuée le 26 octobre 2026, avant les moteurs et l’interface. Les révisions exactes, modules, tests et licences figurent dans les notes spécialisées : [ASS et synchronisation](research-subtitles.md), [traduction Strict](research-translation.md), [interface](research-ui.md).

| Élément | Choix | Raisons et limites |
| --- | --- | --- |
| Sublarr | Réutilisation de son lexer ASS borné ; étude de ses guards, flux, tests et issues | Son backend complet entraîne gestionnaires média, tâches et services hors périmètre. Une API Sublarr masquerait des comportements importants et imposerait deux produits. Le module indépendant et pysubs2 évitent ce couplage. Code GPL identifié ; Sillage GPL-3.0-only. |
| pysubs2 | Dépendance de validation du parsing, des comptes et timings | La sérialisation générale peut normaliser les fichiers. Sillage remplace seulement les spans textuels validés et conserve les autres lignes. |
| ffsubsync | FFTAligner comme moteur de proposition, VAD WebRTC contre extraction audio explicite | Extraction bornée et contrôle indépendant du score, de l’ambiguïté et de trois fenêtres ; pas de référence à des sous-titres intégrés. Acceptation humaine indispensable. |
| alass | Étudié, non embarqué | Dépendance binaire supplémentaire et correction plus complexe non justifiées pour V1. Aucun faux choix de moteur dans l’interface. |
| Subtitle Translator | Patterns Strict : IDs, contexte voisin, batches et checkpoints | Pas de resegmentation/adaptive, qui changerait les timings ; pas d’analyse automatique supplémentaire facturée. |
| Providers | Adaptateurs httpx explicites | LiteLLM apporterait davantage de routage et de catalogue que nécessaire ; modèle saisi librement et protocoles testés. |
| UI | React/TypeScript/Vite, TanStack Query/Table, primitives Radix/shadcn et Lucide | Patterns de navigation FileBrowser Quantum et structure/tables/boutons shadcn-admin, avec provenance MIT. |

## Périmètre construit

Un backend FastAPI sert les assets compilés et pilote un worker unique. SQLite conserve providers, jobs et checkpoints par segment. Le worker ne reçoit jamais de texte ASS complet en retour du modèle : IDs et placeholders contrôlent une reconstruction déterministe. Un résultat est validé avant publication atomique exclusive à côté du MKV.

Le système reste un outil personnel local, sans serveur Node en production, sans Redis/Celery et sans service de médiathèque tiers obligatoire. Les phases de synchronisation et de traduction restent distinctes. Les garanties observées et les limites non testées sont consignées dans [STATUS](STATUS.md).
