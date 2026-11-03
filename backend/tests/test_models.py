from app.models import Project, Step


async def test_project_and_step_roundtrip(session, admin):
    p = Project(title="t", theme="x", user_id=admin.id)
    session.add(p)
    await session.flush()
    session.add(Step(project_id=p.id, name="idea"))
    await session.commit()
    assert p.status == "draft"
