"""Journal des appels IA vers Langfuse Cloud, par le SDK officiel (OpenTelemetry).

Structure d'une trace (bonnes pratiques Langfuse) :
- une **trace** par lancement d'étape (`run_step` : observation racine `run-<étape>`), regroupée en **session** par projet
  (`projet-<id>`) ;
- une **generation** par tentative d'appel provider (`tracked_call`), avec modèle, entrée en messages, sortie, tokens,
  coût et erreur. Un appel hors étape (assistant d'écriture, chat du plan) est sa propre trace.
Les noms sont stables et commencent par un verbe (jamais d'identifiant ni de modèle dedans : ils servent de filtres) ;
les valeurs propres à l'exécution sont en métadonnées.

Sans clés, tout est inactif (aucun coût). Une panne de Langfuse ne retarde ni ne fait échouer une étape : le SDK envoie
en arrière-plan et ses erreurs vont aux logs."""
import logging
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any

import httpx
from langfuse import Langfuse, propagate_attributes
from opentelemetry import trace

from app.app_settings import AppSettings
from app.config import settings
from app.providers.base import GenerationResult, TextResult

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://cloud.langfuse.com"
MAX_TEXT = 20_000  # un prompt de plan ou de script reste lisible ; le reste est coupé

# Nom stable, verbe d'abord, de ce que fait chaque étape (observation racine et generations).
ACTIONS = {"idea": "write-idea", "story": "write-story", "script": "write-script", "reference": "generate-reference",
           "clips": "generate-clip", "voice": "synthesize-voice", "music": "pick-music", "montage": "assemble-montage",
           "final": "write-metadata", "plan_chat": "chat-plan"}


@dataclass(frozen=True)
class LangfuseConfig:
    public_key: str
    secret_key: str
    base_url: str


_clients: dict[LangfuseConfig, Langfuse] = {}


async def load_config(app_settings: AppSettings) -> LangfuseConfig | None:
    """Configuration saisie dans Réglages ; `None` (journal désactivé) tant qu'une des deux clés manque."""
    public, secret = await app_settings.get("langfuse_public_key"), await app_settings.get("langfuse_secret_key")
    if not (public and secret):
        return None
    return LangfuseConfig(public, secret, (await app_settings.get("langfuse_base_url")).rstrip("/") or DEFAULT_BASE_URL)


def client_for(config: LangfuseConfig) -> Langfuse:
    """Client du SDK de cette configuration, créé une fois (il porte sa file d'envoi en arrière-plan)."""
    if config not in _clients:
        _clients[config] = Langfuse(public_key=config.public_key, secret_key=config.secret_key,
                                    base_url=config.base_url, environment=settings.app_env)
    return _clients[config]


def shutdown() -> None:
    """Envoie ce qui est en attente puis ferme les clients : à l'arrêt de l'API et du worker."""
    for client in _clients.values():
        try:
            client.shutdown()
        except Exception as e:  # noqa: BLE001 — l'arrêt ne doit pas échouer à cause du journal
            log.warning("Langfuse: arrêt incomplet : %s", e)
    _clients.clear()


def messages(prompt: str, system: str | None = None) -> list[dict[str, str]]:
    """Entrée d'une generation au format messages (affichée comme une conversation dans Langfuse)."""
    return [*([{"role": "system", "content": clip(system)}] if system else []), {"role": "user", "content": clip(prompt)}]


def clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "… (coupé)"


def action(step: str) -> str:
    """Nom stable d'une étape ; l'assistant d'écriture (`assist:<type>`) garde son type, qui est un jeu fermé."""
    return ACTIONS.get(step) or step.replace(":", "-").replace("_", "-")


@contextmanager
def step_run(config: LangfuseConfig | None, *, project_id: int, title: str, step: str,
             scene_id: int | None = None) -> Iterator[Any]:
    """Trace d'un lancement d'étape : toutes les generations de l'étape s'y rattachent. Son entrée est ce qu'il faut
    lire d'un coup d'œil dans la liste des traces : le projet (titre) et l'étape ; l'identifiant reste en métadonnée."""
    if config is None:
        yield None
        return
    with client_for(config).start_as_current_observation(
            name=f"run-{step}", as_type="span", input={"project": title, "step": step, **({"scene_id": scene_id} if scene_id else {})},
    ) as root, propagate_attributes(session_id=f"projet-{project_id}", trace_name=f"run-{step}", tags=[step],
                                    metadata={"project_id": str(project_id)}):
        yield root


class Generation:
    """Une tentative d'appel provider ; sans configuration, ne fait rien."""

    def __init__(self, observation: Any = None):
        self._o = observation

    def succeed(self, result: GenerationResult | TextResult, cost_usd: float) -> None:
        if self._o is None:
            return
        if isinstance(result, TextResult):
            usage = {k: v for k, v in (("input", result.input_tokens), ("output", result.output_tokens)) if v}
            self._o.update(output={"role": "assistant", "content": clip(result.text)}, usage_details=usage or None,
                           cost_details={"total": cost_usd})
        else:  # un média n'est jamais envoyé : seulement sa nature et sa taille
            self._o.update(output={"content_type": result.content_type, "bytes": len(result.data)},
                           cost_details={"total": cost_usd})

    def fail(self, error: str) -> None:
        if self._o is not None:
            self._o.update(level="ERROR", status_message=error, cost_details={"total": 0})


@contextmanager
def generation(config: LangfuseConfig | None, *, step: str, provider: str, model: str, input: list[dict] | None,
               project_id: int | None, attempt: int) -> Iterator[Generation]:
    """`with` d'une tentative : durée et exception sont prises par le SDK ; `succeed`/`fail` complètent le résultat."""
    if config is None:
        yield Generation()
        return
    metadata = {"provider": provider, "step": step, "attempt": str(attempt),
                **({"project_id": str(project_id)} if project_id else {})}
    # Hors étape (assistant, chat du plan), la generation est la racine : session du projet et étiquette de l'étape.
    scope = propagate_attributes(session_id=f"projet-{project_id}" if project_id else None, tags=[step]) \
        if _is_root() else nullcontext()
    with scope, client_for(config).start_as_current_observation(
            name=action(step), as_type="generation", model=model, input=input, metadata=metadata) as observation:
        yield Generation(observation)


def _is_root() -> bool:
    return not trace.get_current_span().get_span_context().is_valid


async def healthy(config: LangfuseConfig | None, client: httpx.AsyncClient) -> bool:
    """Clés acceptées par Langfuse (lecture gratuite des projets de la clé) ; `False` sans clés ou service injoignable."""
    if config is None:
        return False
    try:
        response = await client.get(f"{config.base_url}/api/public/projects", auth=(config.public_key, config.secret_key),
                                    timeout=10)
    except httpx.HTTPError:
        return False
    return response.status_code == 200
