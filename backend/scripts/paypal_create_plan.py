"""Crée le plan d'abonnement mensuel PayPal d'un forfait et l'inscrit dans `billing_config` (`tiers[].paypal_plan_id`).

Usage : uv run python scripts/paypal_create_plan.py --tier starter|creator|pro
Le montant est le `paypal_amount` du forfait. Lit les identifiants PayPal des Réglages (base) et `DATABASE_URL` comme
l'API ; redémarrage inutile (réglage relu à chaque requête). Le plan est créé dans le mode des Réglages (`paypal_mode`,
bac à sable par défaut) : à refaire en mode `live`. Un réglage absent ou à l'ancien format repart des forfaits par défaut.
"""
import argparse
import asyncio
import json

from app.app_settings import AppSettings
from app.db import SessionFactory
from app.services.billing import DEFAULT_BILLING, parse_billing
from app.services.paypal_client import PayPalClient


async def main(tier_id: str) -> None:
    async with SessionFactory() as session:
        app_settings = AppSettings(session)
        client_id, secret = await app_settings.get("paypal_client_id"), await app_settings.get("paypal_client_secret")
        if not (client_id and secret):
            raise SystemExit("Saisissez d'abord les identifiants PayPal dans les Réglages")
        raw = await app_settings.get("billing_config")
        config = json.loads(raw if parse_billing(raw) else DEFAULT_BILLING)
        tier = next((t for t in config["tiers"] if t["id"] == tier_id), None)
        if tier is None or not tier.get("paypal_amount"):
            raise SystemExit(f"Forfait {tier_id} inconnu ou sans montant PayPal (paypal_amount)")
        mode = await app_settings.get("paypal_mode")
        tier["paypal_plan_id"] = await PayPalClient(client_id, secret, "", mode).create_monthly_plan(
            name=f"Vivi {tier['name']}", amount=tier["paypal_amount"])
        await app_settings.set("billing_config", json.dumps(config))
    print(f"Plan {tier['paypal_plan_id']} créé ({mode}, {tier['paypal_amount']} $ par mois) pour {tier_id}, inscrit dans billing_config")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", required=True, help="identifiant du forfait, ex. starter")
    asyncio.run(main(parser.parse_args().tier))
