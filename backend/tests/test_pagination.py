"""Liste des projets (pagination, recherche, tri, filtre) et journal des coûts paginé."""
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Project, ProviderCall
from tests.conftest import ensure_admin


async def seed_projects(session, rows):
    """`rows` : (titre, thème, statut, coût) ; le premier est le plus ancien."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    ids = []
    user_id = (await ensure_admin(session)).id
    for i, (title, theme, status, cost) in enumerate(rows):
        p = Project(title=title, theme=theme, status=status, user_id=user_id,
                    created_at=start + timedelta(hours=i))
        session.add(p)
        await session.flush()
        ids.append(p.id)
        if cost:
            session.add(ProviderCall(project_id=p.id, step="clips", provider="fal", model="m", cost_usd=cost,
                                     status="ok"))
    await session.commit()
    return ids


async def listing(api, **params):
    r = await api.get("/api/projects", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def titles(page):
    return [p["title"] for p in page["items"]]


ROWS = [("Routine du matin", "café et sommeil", "done", 0.5), ("Trois astuces sommeil", "dormir mieux", "draft", 2.0),
        ("Pieuvre", "100% fait vrai", "draft", 0.0), ("Café noir_ou_lait", "boisson", "done", 1.0)]


async def test_default_listing_is_newest_first_with_total(api, session):
    await seed_projects(session, ROWS)
    page = await listing(api)
    assert titles(page) == ["Café noir_ou_lait", "Pieuvre", "Trois astuces sommeil", "Routine du matin"]
    assert page["total"] == 4


async def test_pages_cover_every_project_once(api, session):
    await seed_projects(session, [(f"Vidéo {i:02}", "", "draft", 0) for i in range(7)])
    seen = []
    for offset in (0, 3, 6):
        page = await listing(api, limit=3, offset=offset)
        assert page["total"] == 7
        seen += titles(page)
    assert seen == [f"Vidéo {i:02}" for i in range(6, -1, -1)]  # ni doublon ni oubli
    assert (await listing(api, limit=3, offset=9))["items"] == []


@pytest.mark.parametrize("sort, expected", [
    ("recent", ["Café noir_ou_lait", "Pieuvre", "Trois astuces sommeil", "Routine du matin"]),
    ("oldest", ["Routine du matin", "Trois astuces sommeil", "Pieuvre", "Café noir_ou_lait"]),
    ("title", ["Café noir_ou_lait", "Pieuvre", "Routine du matin", "Trois astuces sommeil"]),
    ("cost", ["Trois astuces sommeil", "Café noir_ou_lait", "Routine du matin", "Pieuvre"]),
])
async def test_sorts(api, session, sort, expected):
    await seed_projects(session, ROWS)
    assert titles(await listing(api, sort=sort)) == expected


async def test_search_matches_title_or_theme_ignoring_case(api, session):
    await seed_projects(session, ROWS)
    assert titles(await listing(api, q="SOMMEIL", sort="oldest")) == ["Routine du matin", "Trois astuces sommeil"]
    assert titles(await listing(api, q="boisson")) == ["Café noir_ou_lait"]  # dans le thème
    page = await listing(api, q="sommeil", limit=1)
    assert len(page["items"]) == 1 and page["total"] == 2  # total = correspondances, pas la page


async def test_search_treats_like_wildcards_literally(api, session):
    await seed_projects(session, ROWS)
    assert titles(await listing(api, q="_")) == ["Café noir_ou_lait"]
    assert titles(await listing(api, q="100%")) == ["Pieuvre"]
    assert (await listing(api, q="%"))["total"] == 1  # « % » seul ne veut pas dire « tout »


async def test_status_filter(api, session):
    await seed_projects(session, ROWS)
    assert titles(await listing(api, status="done", sort="oldest")) == ["Routine du matin", "Café noir_ou_lait"]
    page = await listing(api, status="draft", q="sommeil")
    assert titles(page) == ["Trois astuces sommeil"] and page["total"] == 1


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"sort": "hasard"}, {"status": "x"},
                                     {"q": "x" * 101}])
async def test_invalid_parameters_are_rejected(api, params):
    assert (await api.get("/api/projects", params=params)).status_code == 422


# --- Coûts -----------------------------------------------------------------------------------------------------------

async def test_costs_calls_are_paginated_while_totals_cover_everything(api, session):
    (pid,) = await seed_projects(session, [("p", "", "draft", 0)])
    session.add_all(ProviderCall(project_id=pid, step="clips", provider="fal", model="m", cost_usd=1.0, status="ok",
                                 created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=i)) for i in range(5))
    await session.commit()
    first = (await api.get("/api/costs", params={"limit": 2})).json()
    second = (await api.get("/api/costs", params={"limit": 2, "offset": 2})).json()
    assert first["calls_total"] == 5 and first["total_usd"] == 5.0  # totaux : tous les appels
    assert len(first["calls"]) == 2 and len(second["calls"]) == 2
    assert not {c["id"] for c in first["calls"]} & {c["id"] for c in second["calls"]}
    assert first["calls"][0]["created_at"] > second["calls"][0]["created_at"]  # du plus récent au plus ancien
    assert (await api.get("/api/costs", params={"limit": 2, "offset": 4})).json()["calls"].__len__() == 1


async def test_costs_page_size_is_bounded(api):
    assert (await api.get("/api/costs", params={"limit": 0})).status_code == 422
    assert (await api.get("/api/costs", params={"limit": 1001})).status_code == 422
    assert (await api.get("/api/costs")).json()["calls_total"] == 0
