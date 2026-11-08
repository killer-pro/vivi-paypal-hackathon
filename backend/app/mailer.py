import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Protocol

import httpx
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.config import settings
from app.db import get_session

logger = logging.getLogger("app.mailer")

SMTP_PLAIN_PORT = 25  # STARTTLS seulement s'il y a des identifiants (relais local sans authentification)
SMTPS_PORT = 465  # TLS dès la connexion
SMTP_TIMEOUT_S = 15
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_TIMEOUT_S = 15


@dataclass
class Mail:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    async def send(self, mail: Mail) -> None: ...


class FakeMailer:
    """Garde les e-mails en mémoire (tests, `FAKE_PROVIDERS=true`) et les écrit au journal : en dev, rien ne part, le
    lien de vérification ou de réinitialisation se lit dans la sortie du backend. Avertissement (et non info) : seul
    niveau affiché sans configuration du journal."""

    def __init__(self) -> None:
        self.outbox: list[Mail] = []

    async def send(self, mail: Mail) -> None:
        self.outbox.append(mail)
        logger.warning("E-mail non envoyé (faux mailer) à %s : %s\n%s", mail.to, mail.subject, mail.body)


class SmtpMailer:
    def __init__(self, host: str, port: int, user: str, password: str, sender: str):
        self.host, self.port, self.user, self.password, self.sender = host, port, user, password, sender

    async def send(self, mail: Mail) -> None:
        await asyncio.to_thread(self._send_blocking, mail)

    def _send_blocking(self, mail: Mail) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self.sender, mail.to, mail.subject
        message.set_content(mail.body)
        context = ssl.create_default_context()  # certificat et nom d'hôte vérifiés
        if self.port == SMTPS_PORT:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=SMTP_TIMEOUT_S, context=context)
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=SMTP_TIMEOUT_S)
        with smtp:
            # Jamais d'identifiants en clair : STARTTLS obligatoire dès qu'il y a un login, port 25 compris.
            if self.port != SMTPS_PORT and (self.port != SMTP_PLAIN_PORT or self.user):
                smtp.starttls(context=context)
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)


class BrevoMailer:
    """Envoi par l'API HTTP de Brevo (port 443 : passe là où un hébergeur bloque le SMTP). `sender` au format
    « Nom <adresse> » ou adresse seule ; l'adresse doit être un expéditeur validé dans Brevo."""

    def __init__(self, api_key: str, sender: str, transport: httpx.AsyncBaseTransport | None = None):
        self.api_key, self.sender, self._transport = api_key, sender, transport  # transport : tests

    def payload(self, mail: Mail) -> dict:
        name, email = parseaddr(self.sender)
        return {"sender": {"email": email, **({"name": name} if name else {})}, "to": [{"email": mail.to}],
                "subject": mail.subject, "textContent": mail.body}

    async def send(self, mail: Mail) -> None:
        async with httpx.AsyncClient(timeout=BREVO_TIMEOUT_S, transport=self._transport) as client:
            response = await client.post(BREVO_URL, json=self.payload(mail),
                                         headers={"api-key": self.api_key, "accept": "application/json"})
        response.raise_for_status()  # le corps de la réponse n'est pas journalisé : il peut citer le message


async def get_mailer(session: AsyncSession = Depends(get_session)) -> Mailer:
    """Faux envoi en mode factice ; sinon Brevo si sa clé est renseignée, à défaut SMTP."""
    if settings.fake_providers:
        return FakeMailer()
    app_settings = AppSettings(session)
    brevo_key = await app_settings.get("brevo_api_key")
    if brevo_key:
        return BrevoMailer(brevo_key, await app_settings.get("brevo_sender"))
    host = await app_settings.get("smtp_host")
    if not host:
        raise HTTPException(503, "L'envoi d'e-mails n'est pas configuré (Réglages)")
    user = await app_settings.get("smtp_user")
    return SmtpMailer(host, int(await app_settings.get("smtp_port")), user, await app_settings.get("smtp_password"),
                      await app_settings.get("smtp_sender") or user)


def verification_mail(to: str, link: str) -> Mail:
    return Mail(to, "Confirmez votre adresse e-mail",
                f"Bienvenue !\n\nPour activer votre compte, confirmez votre adresse e-mail :\n{link}\n\n"
                "Si vous n'êtes pas à l'origine de cette inscription, ignorez ce message.")


def reset_mail(to: str, link: str) -> Mail:
    return Mail(to, "Réinitialisation de votre mot de passe",
                f"Pour choisir un nouveau mot de passe, ouvrez ce lien :\n{link}\n\n"
                "Si vous n'avez pas fait cette demande, ignorez ce message.")
