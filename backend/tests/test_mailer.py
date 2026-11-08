import json
import ssl

import httpx
import pytest
from fastapi import HTTPException

from app.config import settings
from app.mailer import BREVO_URL, BrevoMailer, FakeMailer, Mail, SmtpMailer, get_mailer, reset_mail, verification_mail


async def test_fake_mailer_collects():
    mailer = FakeMailer()
    mail = Mail(to="a@b.fr", subject="Sujet", body="Corps")
    await mailer.send(mail)
    assert mailer.outbox == [mail]


async def test_fake_mailer_logs_the_mail_for_dev(caplog):
    """En dev (`FAKE_PROVIDERS=true`), aucun e-mail ne part : le lien se lit dans le journal du backend."""
    await FakeMailer().send(verification_mail("a@b.fr", "http://x/verify?token=abc"))
    assert "a@b.fr" in caplog.text and "http://x/verify?token=abc" in caplog.text


async def test_smtp_mailer_logs_nothing(caplog, monkeypatch):
    """Le vrai envoi ne journalise jamais le corps (il porte un jeton)."""
    monkeypatch.setattr(SmtpMailer, "_send_blocking", lambda self, mail: None)
    await SmtpMailer("h", 587, "", "", "s@b.fr").send(verification_mail("a@b.fr", "http://x/verify?token=abc"))
    assert "token=abc" not in caplog.text


async def test_mail_contents_carry_the_link():
    for build in (verification_mail, reset_mail):
        mail = build("a@b.fr", "http://x/lien")
        assert mail.to == "a@b.fr" and "http://x/lien" in mail.body and mail.subject


async def test_get_mailer_is_fake_with_fake_providers(session):
    assert isinstance(await get_mailer(session), FakeMailer)


async def test_get_mailer_503_when_unconfigured(session, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", False)
    with pytest.raises(HTTPException) as err:
        await get_mailer(session)
    assert err.value.status_code == 503


async def test_get_mailer_builds_smtp_from_settings(api, session, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", False)
    await api.put("/api/settings", json={"smtp_host": "smtp.test", "smtp_user": "u", "smtp_password": "secret",
                                         "smtp_sender": "noreply@test"})
    mailer = await get_mailer(session)
    assert isinstance(mailer, SmtpMailer)
    assert (mailer.host, mailer.port, mailer.user, mailer.password, mailer.sender) == (
        "smtp.test", 587, "u", "secret", "noreply@test")


async def test_get_mailer_prefers_brevo_when_key_set(api, session, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", False)
    await api.put("/api/settings", json={"smtp_host": "smtp.test", "brevo_api_key": "xkeysib-1",
                                         "brevo_sender": "Vivi <noreply@test>"})
    mailer = await get_mailer(session)
    assert isinstance(mailer, BrevoMailer) and (mailer.api_key, mailer.sender) == ("xkeysib-1", "Vivi <noreply@test>")


async def test_brevo_key_comes_from_environment(session, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", False)
    monkeypatch.setattr(settings, "brevo_api_key", "xkeysib-env")
    assert isinstance(await get_mailer(session), BrevoMailer)


async def test_smtp_comes_from_environment(session, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", False)
    for key, value in {"smtp_host": "smtp.env", "smtp_user": "u", "smtp_password": "secret", "smtp_sender": ""}.items():
        monkeypatch.setattr(settings, key, value)
    mailer = await get_mailer(session)
    assert isinstance(mailer, SmtpMailer) and (mailer.host, mailer.port, mailer.password, mailer.sender) == (
        "smtp.env", 587, "secret", "u")


async def test_brevo_mailer_posts_the_message():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"messageId": "x"})

    await BrevoMailer("xkeysib-1", "Vivi <noreply@test>", httpx.MockTransport(handler)).send(Mail("a@b.fr", "Sujet", "Corps"))
    (request,) = requests
    assert str(request.url) == BREVO_URL and request.headers["api-key"] == "xkeysib-1"
    assert json.loads(request.content) == {"sender": {"email": "noreply@test", "name": "Vivi"}, "to": [{"email": "a@b.fr"}],
                                           "subject": "Sujet", "textContent": "Corps"}


async def test_brevo_mailer_raises_on_refusal():
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"code": "unauthorized"}))
    with pytest.raises(httpx.HTTPStatusError):
        await BrevoMailer("mauvaise", "noreply@test", transport).send(Mail("a@b.fr", "Sujet", "Corps"))


async def test_brevo_sender_without_name():
    assert BrevoMailer("k", "noreply@test").payload(Mail("a@b.fr", "S", "C"))["sender"] == {"email": "noreply@test"}


async def test_smtp_settings_are_editable_and_password_masked(api):
    assert (await api.put("/api/settings", json={"smtp_host": "smtp.test", "smtp_password": "abcdefgh1234"})
            ).status_code == 200
    data = (await api.get("/api/settings")).json()
    assert data["smtp_host"] == "smtp.test" and data["smtp_port"] == "587"
    assert data["smtp_password"] == "••••1234"


async def test_smtp_port_rejects_non_numeric(api):
    for bad in ("abc", "0", "70000", "-1"):
        assert (await api.put("/api/settings", json={"smtp_port": bad})).status_code == 400
    assert (await api.put("/api/settings", json={"smtp_port": "465"})).status_code == 200


class FakeSMTP:
    """Remplace `smtplib.SMTP` / `SMTP_SSL` : journalise les appels dans `calls`."""
    calls: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.calls.append(("connect", type(self).__name__, port, context))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def starttls(self, context=None):
        self.calls.append(("starttls", context))

    def login(self, user, password):
        self.calls.append(("login",))

    def send_message(self, message):
        self.calls.append(("send",))


class FakeSMTP_SSL(FakeSMTP):  # noqa: N801 (nom de la classe remplacée)
    pass


@pytest.fixture
def smtp_calls(monkeypatch):
    FakeSMTP.calls = []
    monkeypatch.setattr("app.mailer.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("app.mailer.smtplib.SMTP_SSL", FakeSMTP_SSL)
    return FakeSMTP.calls


def send_with(port, user):
    SmtpMailer("smtp.test", port, user, "secret", "noreply@test")._send_blocking(Mail("a@b.fr", "Sujet", "Corps"))


@pytest.mark.parametrize("port", [587, 2525, 25])
def test_smtp_starttls_with_verified_context_before_login(smtp_calls, port):
    send_with(port, "u")
    names = [c[0] for c in smtp_calls]
    assert names == ["connect", "starttls", "login", "send"] and smtp_calls[0][1] == "FakeSMTP"
    context = smtp_calls[1][1]
    assert isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_smtp_port_465_uses_implicit_tls(smtp_calls):
    send_with(465, "u")
    assert [c[0] for c in smtp_calls] == ["connect", "login", "send"]
    assert smtp_calls[0][1] == "FakeSMTP_SSL" and isinstance(smtp_calls[0][3], ssl.SSLContext)


def test_smtp_port_25_without_credentials_stays_plain(smtp_calls):
    send_with(25, "")
    assert [c[0] for c in smtp_calls] == ["connect", "send"]
