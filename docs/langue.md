# Langue de l'interface (français / anglais)

L'admin existe en français (langue par défaut) et en anglais. Le choix se fait avec la bascule **FR | EN** : barre latérale des écrans connectés, barre de la page `/decouvrir`, cartes de connexion et d'inscription.

## Fonctionnement
- `admin/src/i18n.ts` : `lang` est fixée au chargement de la page. Ordre : paramètre `?lang=fr|en` de l'adresse (mémorisé), sinon dernier choix (`localStorage`, clé `vivi.lang`), sinon français. `setLang` mémorise le choix et recharge la page : les libellés calculés à l'import (`STEP_LABELS`, `TEMPLATES`…) suivent sans rien rendre réactif. `<html lang>` et `locale` (`fr-FR` / `en-US`, utilisée par tous les `Intl` et `toLocaleString`) en dépendent.
- **La clé est le texte français** : `t("Valider")`, `t("scène {n}", { n })`, `tn(n, "{n} scène", "{n} scènes")` (singulier si `n` ≤ 1). Le dictionnaire anglais est `admin/src/locales/en.ts` ; un texte absent reste en français, jamais de clé brute à l'écran.
- `LangSwitch` (`components/LangSwitch.tsx`) est la bascule.

## Ajouter ou modifier un texte
1. Écrire le texte en français dans `t("…")` (les variables en `{nom}`).
2. Ajouter la ligne correspondante dans `locales/en.ts`.
3. `src/i18n.test.ts` échoue si un `t("…")` n'a pas de traduction ou si les `{variables}` diffèrent entre les deux langues.

## Ce qui n'est pas traduit
- Les messages d'erreur renvoyés par l'API, les contenus générés (titres, scripts, histoires) et les libellés venus du serveur autres que les profils vidéo et les styles : ils restent dans la langue du backend.
- Les prompts envoyés aux modèles (ils sont en français côté backend).
