"""Fixe la fin de la période d'abonnement et le forfait d'un compte (essais, comptes de démo).

Usage : uv run python scripts/set_subscription.py --email client@exemple.fr --until 2027-01-31 [--plan creator]
        uv run python scripts/set_subscription.py --email client@exemple.fr --off
Lit `DATABASE_URL` comme l'API ; redémarrage inutile (l'état est lu à chaque requête).
"""
import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import SessionFactory
from app.models import User
from app.services.access import set_subscription_end


async def main(email: str, until: datetime | None, plan: str | None) -> None:
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise SystemExit(f"Aucun compte pour {email}")
        await set_subscription_end(session, user, until, plan if until else None)
    print(f"{email} : " + (f"abonné ({plan or 'premier forfait'}) jusqu'au {until:%d/%m/%Y}" if until else "plus abonné"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--until", type=lambda v: datetime.fromisoformat(v).replace(tzinfo=UTC), help="AAAA-MM-JJ")
    group.add_argument("--off", action="store_true")
    parser.add_argument("--plan", choices=("starter", "creator", "pro"), help="forfait (défaut : le premier)")
    args = parser.parse_args()
    asyncio.run(main(args.email, None if args.off else args.until, args.plan))
