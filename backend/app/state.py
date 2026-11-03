STEP_NAMES = ["idea", "story", "script", "reference", "clips", "voice", "music", "montage", "final"]
OPTIONAL_STEPS = {"reference"}


class InvalidTransition(Exception):
    pass


_ALLOWED = {
    "pending": {"running"},
    "running": {"awaiting_validation", "failed"},
    "awaiting_validation": {"approved", "running"},
    "approved": {"running"},
    "failed": {"running"},
    "stale": {"running", "approved"},
}


def transition(current: str, target: str) -> str:
    if target not in _ALLOWED.get(current, set()):
        raise InvalidTransition(f"{current} -> {target}")
    return target


def downstream(step: str) -> list[str]:
    """Étapes qui suivent `step` dans l'ordre du mode automatique (une à la fois)."""
    return STEP_NAMES[STEP_NAMES.index(step) + 1 :]


# Étape -> étapes dont elle dépend directement. Seul le montage rassemble clips, voix et musique : la voix et la
# musique ne dépendent que du script (écrit en entier dès le début), pas des clips, et se génèrent en parallèle.
REQUIRES = {
    "idea": (),
    "story": ("idea",),
    "script": ("story",),
    "reference": ("script",),
    "clips": ("script", "reference"),
    "voice": ("script",),
    "music": ("script",),
    "montage": ("clips", "voice", "music"),
    "final": ("montage",),
}


def upstream(step: str) -> list[str]:
    """Étapes dont `step` dépend, directement ou non, dans l'ordre du flow."""
    found: set[str] = set()
    todo = list(REQUIRES[step])
    while todo:
        name = todo.pop()
        if name not in found:
            found.add(name)
            todo.extend(REQUIRES[name])
    return [n for n in STEP_NAMES if n in found]


def dependents(step: str) -> list[str]:
    """Étapes construites à partir de `step` : périmées quand elle change, interdites de modification pendant que l'une
    d'elles tourne."""
    return [n for n in STEP_NAMES if step in upstream(n)]


def can_start(statuses: dict[str, str], step: str) -> bool:
    """`reference` n'a besoin que du script écrit : elle peut démarrer pendant sa relecture (`awaiting_validation`)."""

    def ready(name: str) -> bool:
        if step == "reference" and name == "script":
            return statuses[name] in ("approved", "awaiting_validation")
        return statuses[name] == "approved"

    return all(ready(n) for n in upstream(step) if n not in OPTIONAL_STEPS)
