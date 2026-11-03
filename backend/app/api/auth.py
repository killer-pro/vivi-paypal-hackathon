import logging
import re
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.config import settings
from app.db import get_session
from app.mailer import Mail, Mailer, get_mailer, reset_mail, verification_mail
from app.models import EmailToken, User
from app.security import PASSWORD_MAX, PASSWORD_MIN, hash_password, new_token, token_hash, verify_password
from app.services.credits import grant_signup_credits

logger = logging.getLogger("app.auth")

COOKIE_NAME = "session"
MAX_AGE_S = 30 * 24 * 3600
COOKIE_FLAGS: dict[str, Any] = {"httponly": True, "samesite": "lax", "secure": settings.is_prod}  # Secure : HTTPS uniquement

MAX_LOGIN_FAILURES = 5
LOGIN_WINDOW_S = 300

EMAIL_MAX = 254
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
TOKEN_TTL = {"verify": timedelta(hours=48), "reset": timedelta(hours=1)}
LINK_PATH = {"verify": "/verify", "reset": "/reset"}
INVALID_LINK = "Lien invalide ou expiré"
BAD_CREDENTIALS = "Email ou mot de passe incorrect"
OK = {"ok": True}

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginThrottle:
    """Connexions échouées par client sur une fenêtre glissante. État en mémoire : suffisant tant que l'API tourne en un
    seul processus (derrière un proxy, lancer uvicorn avec `--proxy-headers` pour distinguer les clients)."""

    def __init__(self, max_failures: int = MAX_LOGIN_FAILURES, window_s: float = LOGIN_WINDOW_S,
                 clock: Callable[[], float] = time.monotonic):
        self.max_failures, self.window_s, self._clock = max_failures, window_s, clock
        self._failures: dict[str, deque[float]] = {}

    def _recent(self, client: str) -> deque[float]:
        times = self._failures.get(client, deque())
        while times and times[0] <= self._clock() - self.window_s:
            times.popleft()
        if not times:
            self._failures.pop(client, None)
        return times

    def retry_after(self, client: str) -> int:
        """Secondes à attendre avant une nouvelle tentative ; 0 si elle est permise."""
        times = self._recent(client)
        if len(times) < self.max_failures:
            return 0
        return int(times[0] + self.window_s - self._clock()) + 1

    def fail(self, client: str) -> None:
        self._failures.setdefault(client, deque()).append(self._clock())

    def reset(self, client: str | None = None) -> None:
        self._failures.pop(client, None) if client else self._failures.clear()


throttle = LoginThrottle()
# Inscription, renvoi du lien et mot de passe oublié : chaque demande compte (elle envoie un e-mail).
signup_throttle = LoginThrottle(max_failures=5, window_s=3600)

# Haché une fois : vérifié quand l'adresse est inconnue, pour que la réponse prenne le même temps qu'un vrai compte.
_DUMMY_HASH = hash_password(new_token()[0])


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def _valid_email(raw: str) -> str:
    email = normalize_email(raw)
    if len(email) > EMAIL_MAX or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Adresse e-mail invalide")
    return email


Email = Annotated[str, Field(max_length=EMAIL_MAX + 64), AfterValidator(_valid_email)]
# Longueur contrôlée par la validation du corps (422), donc avant tout calcul scrypt.
NewPassword = Annotated[str, Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)]


class CredentialsIn(BaseModel):
    email: Email
    password: NewPassword


class LoginIn(BaseModel):
    email: Email
    password: str = Field(max_length=PASSWORD_MAX)  # pas de minimum : le mot de passe admin vient de l'environnement


class EmailIn(BaseModel):
    email: Email


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class ResetIn(TokenIn):
    password: NewPassword


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key)


def make_session_cookie(user_id: int, epoch: int) -> str:
    return _serializer().dumps({"uid": user_id, "epoch": epoch})


async def _session_user(request: Request, session: AsyncSession) -> User | None:
    """Titulaire d'un cookie valide : signé, non expiré, au format actuel, compte existant et époque à jour."""
    try:
        data = _serializer().loads(request.cookies.get(COOKIE_NAME, ""), max_age=MAX_AGE_S)
    except BadSignature:  # inclut SignatureExpired
        return None
    if not isinstance(data, dict) or not isinstance(data.get("uid"), int):  # ancien format compris
        return None
    user = await session.get(User, data["uid"])
    return user if user and data.get("epoch") == user.session_epoch else None


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    user = await _session_user(request, session)
    if user is None:
        raise HTTPException(401, "Non authentifié")
    return user


async def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Réservé à l'administrateur")
    return user


ADMIN_ONLY = [Depends(require_admin)]  # `dependencies=` d'une route de configuration globale


def _client(request: Request) -> str:
    return request.client.host if request.client else "inconnu"


def _check_throttle(limiter: LoginThrottle, client: str) -> None:
    wait = limiter.retry_after(client)
    if wait:
        raise HTTPException(429, f"Trop de tentatives : réessayez dans {wait} s", headers={"Retry-After": str(wait)})


def _count_request(request: Request) -> None:
    client = _client(request)
    _check_throttle(signup_throttle, client)
    signup_throttle.fail(client)


async def _user_by_email(session: AsyncSession, email: str) -> User | None:
    return (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def _send_quietly(mailer: Mailer, mail: Mail) -> None:
    """Envoi après la réponse : un échec SMTP est journalisé (sans le lien) et ne change rien à ce que voit le client."""
    try:
        await mailer.send(mail)
    except Exception as e:
        logger.error("Envoi de l'e-mail « %s » à %s impossible : %s", mail.subject, mail.to, type(e).__name__)


async def _send_link(session: AsyncSession, background: BackgroundTasks, mailer: Mailer, user: User, kind: str) -> None:
    """Crée un jeton `kind` (seule son empreinte est stockée) et programme l'envoi du lien après la réponse."""
    token, digest = new_token()
    session.add(EmailToken(user_id=user.id, kind=kind, token_hash=digest, expires_at=datetime.now(UTC) + TOKEN_TTL[kind]))
    await session.commit()
    link = f"{settings.public_url.rstrip('/')}{LINK_PATH[kind]}?token={token}"
    build = verification_mail if kind == "verify" else reset_mail
    background.add_task(_send_quietly, mailer, build(user.email, link))


async def _consume_token(session: AsyncSession, token: str, kind: str) -> User:
    """Marque utilisé un jeton valide du type demandé (une seule requête : deux usages simultanés ne passent pas) et
    retire les autres jetons de ce type du même compte ; 400 uniforme sinon."""
    now = datetime.now(UTC)
    user_id = (await session.execute(
        update(EmailToken)
        .where(EmailToken.token_hash == token_hash(token), EmailToken.kind == kind,
               EmailToken.used_at.is_(None), EmailToken.expires_at > now)
        .values(used_at=now).returning(EmailToken.user_id)
    )).scalar_one_or_none()
    user = await session.get(User, user_id) if user_id is not None else None
    if user is None:
        await session.rollback()
        raise HTTPException(400, INVALID_LINK)
    await session.execute(update(EmailToken).where(EmailToken.user_id == user.id, EmailToken.kind == kind,
                                                   EmailToken.used_at.is_(None)).values(used_at=now))
    return user


async def _mark_verified(session: AsyncSession, user: User) -> None:
    """Adresse vérifiée (lien de vérification ou de réinitialisation) : les crédits d'inscription sont accordés."""
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)
    await grant_signup_credits(session, user, AppSettings(session))


def _me(user: User) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role, "email_verified": user.email_verified_at is not None,
            "subscribed": user.is_subscribed, "subscription_ends_at": user.subscription_ends_at}


@router.post("/register", status_code=202)
async def register(body: CredentialsIn, request: Request, background: BackgroundTasks,
                   session: AsyncSession = Depends(get_session), mailer: Mailer = Depends(get_mailer)) -> dict:
    """Réponse identique que l'adresse soit libre ou prise (pas d'énumération des comptes). Compte existant non vérifié :
    lien de réinitialisation, et non de vérification, pour que le titulaire de la boîte reprenne la main sur un compte
    qu'un tiers aurait inscrit à son adresse avec son propre mot de passe."""
    _count_request(request)
    password_hash = hash_password(body.password)  # calculé dans tous les cas : même durée de réponse
    user = await _user_by_email(session, body.email)
    if user is None:
        user = User(email=body.email, password_hash=password_hash)
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:  # inscription simultanée de la même adresse : l'autre requête envoie le lien
            await session.rollback()
            return OK
        await _send_link(session, background, mailer, user, "verify")
    elif user.email_verified_at is None:
        await _send_link(session, background, mailer, user, "reset")
    return OK


@router.post("/verify")
async def verify(body: TokenIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Marque l'adresse vérifiée et coupe les sessions ouvertes avant (celle d'un tiers qui aurait inscrit l'adresse)."""
    user = await _consume_token(session, body.token, "verify")
    await _mark_verified(session, user)
    user.session_epoch += 1
    await session.commit()
    return OK


@router.post("/resend", status_code=202)
async def resend(request: Request, background: BackgroundTasks, user: User = Depends(current_user),
                 session: AsyncSession = Depends(get_session), mailer: Mailer = Depends(get_mailer)) -> dict:
    _count_request(request)
    if user.email_verified_at is None:
        await _send_link(session, background, mailer, user, "verify")
    return OK


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, session: AsyncSession = Depends(get_session)) -> dict:
    client = _client(request)
    _check_throttle(throttle, client)
    user = await _user_by_email(session, body.email)
    valid = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not valid:
        throttle.fail(client)
        raise HTTPException(401, BAD_CREDENTIALS)
    throttle.reset(client)
    response.set_cookie(COOKIE_NAME, make_session_cookie(user.id, user.session_epoch), max_age=MAX_AGE_S,
                        **COOKIE_FLAGS)
    return _me(user)


@router.post("/logout")
async def logout(request: Request, response: Response, session: AsyncSession = Depends(get_session)) -> dict:
    """Révoque toutes les sessions de l'appelant (un cookie copié cesse de valoir), et seulement les siennes."""
    user = await _session_user(request, session)
    if user:
        user.session_epoch += 1
        await session.commit()
    response.delete_cookie(COOKIE_NAME, **COOKIE_FLAGS)
    return OK


@router.get("/me")
async def me(user: User = Depends(current_user)) -> dict:
    return _me(user)


@router.post("/forgot", status_code=202)
async def forgot(body: EmailIn, request: Request, background: BackgroundTasks,
                 session: AsyncSession = Depends(get_session), mailer: Mailer = Depends(get_mailer)) -> dict:
    """Toujours 202 : la réponse ne dit pas si le compte existe."""
    _count_request(request)
    user = await _user_by_email(session, body.email)
    if user:
        await _send_link(session, background, mailer, user, "reset")
    return OK


@router.post("/reset")
async def reset(body: ResetIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Nouveau mot de passe ; les sessions ouvertes de ce compte sont révoquées. Le lien reçu prouve la possession de la
    boîte : l'adresse devient vérifiée."""
    user = await _consume_token(session, body.token, "reset")
    user.password_hash = hash_password(body.password)
    await _mark_verified(session, user)
    user.session_epoch += 1
    await session.commit()
    return OK
