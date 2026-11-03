"""Isolation des comptes : un utilisateur n'atteint aucun projet, fichier ni coût d'un autre (l'admin, si)."""
import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import events as events_api
from app.api.events import owner_filter, visible_events
from app.main import app
from app.models import Asset, Project, ProviderCall

PATH_PARAM = re.compile(r"{(\w+)}")


@pytest.fixture
async def users(make_user):
    return await make_user("a@example.com"), await make_user("b@example.com")


async def create_project(client, title="Projet") -> int:
    r = await client.post("/api/projects", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def all_routes():
    """Toutes les routes de l'app, y compris celles des routeurs inclus (FastAPI ≥ 0.145 les garde dans des
    `_IncludedRouter` qui exposent leurs routes effectives, préfixe compris)."""
    for route in app.routes:
        yield from route.effective_route_contexts() if hasattr(route, "effective_route_contexts") else [route]


def project_routes() -> list[tuple[str, str]]:
    """(méthode, chemin) de chaque route dont le chemin contient `{project_id}`. Contrôlé contre le schéma OpenAPI :
    une route que le parcours manquerait fait échouer le test au lieu d'être ignorée."""
    found = [(method, r.path) for r in all_routes() if "{project_id}" in getattr(r, "path", "")
             for method in sorted(getattr(r, "methods", None) or ())]
    documented = {(method.upper(), path) for path, ops in app.openapi()["paths"].items() if "{project_id}" in path
                  for method in ops}
    assert documented <= set(found), documented - set(found)
    return found


def fill(path: str, project_id: int) -> str:
    values = {"project_id": str(project_id), "name": "idea"}
    return PATH_PARAM.sub(lambda m: values.get(m.group(1), "1"), path)


async def test_every_project_route_is_protected(api_as, users):
    a, b = users
    pid = await create_project(await api_as(a))
    client_b = await api_as(b)
    routes = project_routes()
    assert routes, "aucune route {project_id} parcourue"
    answers = {}
    for method, path in routes:
        r = await client_b.request(method, fill(path, pid), json={})
        answers[f"{method} {path}"] = (r.status_code, r.json().get("detail") if r.status_code == 404 else r.text)
    assert {route: answer for route, answer in answers.items() if answer != (404, "Projet introuvable")} == {}
    assert (await (await api_as(a)).get(f"/api/projects/{pid}")).status_code == 200  # rien n'a été supprimé


async def test_missing_and_foreign_project_give_the_same_404(api_as, users):
    a, b = users
    pid = await create_project(await api_as(a))
    client_b = await api_as(b)
    foreign, missing = await client_b.get(f"/api/projects/{pid}"), await client_b.get(f"/api/projects/{pid + 1000}")
    assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json()) == (
        404, {"detail": "Projet introuvable"})


async def test_admin_can_open_any_project(api_as, users, admin):
    pid = await create_project(await api_as(users[0]))
    assert (await (await api_as(admin)).get(f"/api/projects/{pid}")).status_code == 200


async def test_list_contains_only_own_projects(api_as, users, admin):
    a, b = users
    await create_project(await api_as(a), "De A")
    await create_project(await api_as(b), "De B")
    await create_project(await api_as(admin), "De l'admin")
    for user, title in ((a, "De A"), (b, "De B"), (admin, "De l'admin")):
        page = (await (await api_as(user)).get("/api/projects")).json()
        assert ([p["title"] for p in page["items"]], page["total"]) == ([title], 1)


async def test_create_project_sets_owner(api_as, users, session):
    pid = await create_project(await api_as(users[0]))
    assert (await session.get(Project, pid)).user_id == users[0].id


async def test_asset_of_other_project_in_url(api_as, users, session):
    a, b = users
    client_a = await api_as(a)
    pid_a, pid_b = await create_project(client_a), await create_project(await api_as(b))
    asset_b = Asset(project_id=pid_b, kind="render", key="projects/b/r.mp4", content_type="video/mp4")
    session.add(asset_b)
    await session.commit()
    assert (await client_a.get(f"/api/projects/{pid_a}/assets/{asset_b.id}/download")).status_code == 404
    assert (await client_a.delete(f"/api/projects/{pid_a}/assets/{asset_b.id}")).status_code == 404
    assert await session.get(Asset, asset_b.id) is not None


async def test_assist_with_foreign_project_id_is_404(api_as, users):
    a, b = users
    pid = await create_project(await api_as(a))
    r = await (await api_as(b)).post("/api/ai/assist", json={"field_kind": "theme", "project_id": pid})
    assert (r.status_code, r.json()) == (404, {"detail": "Projet introuvable"})


async def test_costs_filtered_by_owner(api_as, users, admin, session):
    a, b = users
    client_a = await api_as(a)
    pid_a, pid_b = await create_project(client_a), await create_project(await api_as(b))
    session.add_all(ProviderCall(project_id=pid, step="clips", provider="fal", model="m", cost_usd=cost, status="ok")
                    for pid, cost in ((pid_a, 1.0), (pid_b, 2.0), (None, 4.0)))
    await session.commit()
    mine = (await client_a.get("/api/costs")).json()
    assert (mine["total_usd"], mine["calls_total"], mine["by_project"]) == (1.0, 1, {str(pid_a): 1.0})
    assert [c["project_id"] for c in mine["calls"]] == [pid_a]
    assert (await client_a.get("/api/costs", params={"project_id": pid_b})).status_code == 404
    assert (await client_a.get("/api/costs", params={"project_id": pid_a})).json()["total_usd"] == 1.0
    everything = (await (await api_as(admin)).get("/api/costs")).json()
    assert (everything["total_usd"], everything["calls_total"]) == (7.0, 3)


async def test_non_ascii_digit_project_id_is_404(api_as, users):
    r = await (await api_as(users[0])).get("/api/projects/%C2%B2")  # « ² » : isdigit() vrai, int() impossible
    assert (r.status_code, r.json()) == (404, {"detail": "Projet introuvable"})


class ChannelClosed(Exception):
    pass


class FakePubSub:
    """Canal Redis simulé : rend les messages dans l'ordre (`None` : 15 s sans message), puis lève `ChannelClosed`."""

    def __init__(self, *events):
        self.messages = [None if e is None else {"data": json.dumps(e).encode()} for e in events]

    async def get_message(self, ignore_subscribe_messages, timeout):
        if not self.messages:
            raise ChannelClosed
        return self.messages.pop(0)


@pytest.fixture
def event_sessions(session, monkeypatch):
    """Recherches de propriétaire du flux sur le moteur de la base de test (boucle d'événements du test)."""
    monkeypatch.setattr(events_api, "SessionFactory", async_sessionmaker(session.bind, expire_on_commit=False))


async def received(user, *events) -> list[str]:
    out = []
    try:
        async for chunk in visible_events(FakePubSub(*events), owner_filter(user)):
            out.append(chunk)
    except ChannelClosed:
        pass
    return out


async def test_events_filtered_by_owner(api_as, users, admin, event_sessions):
    a, b = users
    pid_a, pid_b = await create_project(await api_as(a)), await create_project(await api_as(b))
    events = ({"project_id": pid_a, "step": "idea"}, {"project_id": pid_b, "step": "idea"}, {"step": "global"}, None,
              {"project_id": pid_a, "step": "story"})
    data = [f"data: {json.dumps(e)}\n\n" if e else ": ping\n\n" for e in events]
    assert await received(a, *events) == [data[0], ": ping\n\n", data[4]]
    assert await received(b, *events) == [data[1], ": ping\n\n"]
    assert await received(admin, *events) == data


async def test_event_owner_lookup_is_cached_per_connection(api_as, users, event_sessions, monkeypatch):
    a = users[0]
    pid = await create_project(await api_as(a))
    lookups = []
    real = events_api.project_owner

    async def counting(project_id):
        lookups.append(project_id)
        return await real(project_id)

    monkeypatch.setattr(events_api, "project_owner", counting)
    assert len(await received(a, *[{"project_id": pid}] * 3, {"project_id": pid + 1000})) == 3
    assert lookups == [pid, pid + 1000]


async def test_ping_sent_when_only_foreign_events_flow(api_as, users, event_sessions, monkeypatch):
    a, b = users
    pid_b = await create_project(await api_as(b))
    clock = iter([0, 5, 20, 20])  # départ, 1er événement filtré à 5 s, 2e à 20 s (> 15 s sans envoi), envoi du ping
    monkeypatch.setattr(events_api, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    assert await received(a, {"project_id": pid_b}, {"project_id": pid_b}) == [": ping\n\n"]
