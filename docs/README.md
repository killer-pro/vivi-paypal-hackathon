# Documentation

| Document | Contenu |
|---|---|
| `architecture.md` | Composants, flux, modèle de données, garde-fous, limites |
| `workflow-video.md` | Les 9 étapes du pipeline, états, génération en parallèle, invalidation |
| `story.md` | Étape histoire : beats, éléments suivis, contrôles de cohérence, script à partir de la story |
| `autopilot.md` | Mode automatique (enchaînement des étapes, arrêt sur erreur ou budget) |
| `api.md` | Routes de l'API, authentification, jobs et événements temps réel |
| `credits.md` | Crédits : solde à deux lots, registre, prix et devis, réservation / règlement / remboursement, balayeur, réglages `credits_*` |
| `admin-saas.md` | Admin SaaS : clients, ajustement de crédits, tarifs et marges observées |
| `paiement.md` | Paiement Stripe : abonnement, recharges, portail, webhooks signés et idempotents, configuration |
| `abonnement.md` | Accès par abonnement : fonctions réservées (profils, image de référence, styles), `subscription_locked`, motifs de refus |
| `comptes.md` | Comptes, vérification d'e-mail, isolation par propriétaire, configuration (admin, SMTP), écrans de l'admin |
| `providers.md` | Claude, Gemini, fal.ai, ComfyUI (prérequis, workflows, mesures), ElevenLabs, fakes, registre |
| `profils-generation.md` | Profils de génération vidéo (Rapide, Équilibré, Précision, Maximum) : catalogue, cartes, benchmark, ajout d'un profil |
| `settings-providers.md` | Routes de réglages, santé des providers, coûts |
| `costs.md` | Journal des appels, retries, budget par projet |
| `langfuse.md` | Journal des appels IA vers Langfuse Cloud (prompts, réponses, coûts) |
| `montage.md` | Rendu FFmpeg 9:16, sous-titres, mixage |
| `music.md` | Bibliothèque musicale |
| `imports-fichiers.md` | Imports de fichiers (clips, musiques) : clé générée par le serveur, liste d'extensions, nom d'origine |
| `assistant-ia.md` | Assistant de rédaction (Générer / Reformuler) |
| `admin.md` | Interface d'administration : écrans, éditeur Studio, comportements |
| `design-system.md` | Couleurs, typographie, formes et largeurs de l'admin (V2) |
| `marque.md` | Nom Vivi, logo, règles d'usage, identifiants techniques conservés, vérifications à faire |
| `landing.md` | Page de présentation publique `/decouvrir` : lecteur de scènes, visuels générés |
| `securite.md` | Authentification, environnements, limites, liste de contrôle de production |
| `exploitation.md` | Commandes, variables d'environnement, tests, CI, dépannage |
| `changelog.md` | Journal des modifications |

Règle du projet : une fonctionnalité = un document ; toute modification de logique met à jour le document concerné et
ajoute une ligne au changelog.
