from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

AUTOPILOT = "autopilot"
AUTOPILOT_UNTIL = "autopilot_until"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="user", server_default="user")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Incrémenté pour invalider toutes les sessions de l'utilisateur (changement de mot de passe).
    session_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Fin de la période d'abonnement payée : abonné tant qu'elle est dans le futur (une annulation ne la prolonge pas).
    subscription_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    paypal_subscription_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    # Forfait payé (`billing_config.tiers[].id`) ; absent ou inconnu pour un abonné : le premier forfait.
    plan_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_subscribed(self) -> bool:
        """Accès aux fonctions réservées : période payée en cours, ou compte administrateur."""
        ends = self.subscription_ends_at
        return self.is_admin or (ends is not None and ends > datetime.now(ends.tzinfo))


class EmailToken(Base):
    """Jeton à usage unique envoyé par e-mail (`verify` : vérification d'adresse, `reset` : mot de passe oublié)."""
    __tablename__ = "email_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    theme: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(30), default="tiktok")
    target_duration_s: Mapped[int] = mapped_column(Integer, default=30)
    style: Mapped[str] = mapped_column(String(30), default="", server_default="")
    # Avatar parlant : les scènes où parle un personnage visible sont générées en lip-sync (voir `services/lipsync.py`).
    lipsync: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def autopilot(self) -> bool:
        """Mode automatique : drapeau `autopilot` de metadata_json, présent seulement quand il est actif."""
        return bool((self.metadata_json or {}).get(AUTOPILOT))

    @autopilot.setter
    def autopilot(self, on: bool) -> None:
        keep = (AUTOPILOT, AUTOPILOT_UNTIL)  # la borne s'éteint avec le drapeau
        rest = {k: v for k, v in (self.metadata_json or {}).items() if k not in keep}
        self.metadata_json = {**rest, AUTOPILOT: True, **self._bound()} if on else rest  # nouveau dict : JSON non suivi

    def _bound(self) -> dict:
        return {AUTOPILOT_UNTIL: self.autopilot_until} if self.autopilot_until else {}

    @property
    def autopilot_until(self) -> str | None:
        """Étape après laquelle l'autopilot s'arrête (génération du plan : `script`), None s'il va jusqu'au bout."""
        return (self.metadata_json or {}).get(AUTOPILOT_UNTIL)

    def replace_metadata(self, metadata: dict) -> None:
        """Remplace les métadonnées publiées (étape final) sans toucher à l'autopilot ni à sa borne."""
        on, until = self.autopilot, self.autopilot_until
        self.metadata_json = dict(metadata)
        self.autopilot = on
        if on and until:
            self.metadata_json = {**self.metadata_json, AUTOPILOT_UNTIL: until}


class Step(Base):
    __tablename__ = "steps"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Identifiant du dernier lancement complet des étapes par scène (clips, voix) : les assets de ce lancement le
    # portent dans `meta["run"]`, ce qui permet de le reprendre après un échec sans régénérer les scènes déjà faites.
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class QueuedRun(Base):
    """Génération demandée alors qu'une autre bloquait l'étape : lancée dans l'ordre dès que plus rien ne la bloque."""
    __tablename__ = "queued_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    step: Mapped[str] = mapped_column(String(30))
    scene_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Options du lancement (`launch_step` : overrides, resume, only_missing, visual_prompt), rejouées telles quelles.
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (Index("ix_scenes_project_position", "project_id", "position"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    voice_text: Mapped[str] = mapped_column(Text, default="")
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    duration_s: Mapped[float] = mapped_column(Float, default=5.0)
    selected_clip_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference: Mapped[str] = mapped_column(String(30), default="")  # id d'un élément de référence du script ("" : aucun)
    # "continue" : la scène part de la dernière image du clip de la précédente (chaînage) ; "cut" : des références seules
    continuity: Mapped[str] = mapped_column(String(10), default="cut", server_default="cut")
    # id du personnage qui prononce la voix off de la scène ("" : le narrateur, voix par défaut)
    speaker: Mapped[str] = mapped_column(String(30), default="", server_default="")
    # Avatar parlant : `False` = clip animé ordinaire même si le personnage qui parle est visible (voix hors champ).
    lipsync: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    elements: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")  # [{"id", "state"}] visibles dans la scène


class PlanMessage(Base):
    """Message du chat du plan. `before` : instantané du plan avant la modification qu'un message de l'IA a faite (null
    si elle n'a rien changé) ; `undone` : modification annulée."""
    __tablename__ = "plan_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Asset(Base):
    __tablename__ = "assets"
    # Couvre les lectures du projet (préfixe project_id) et « dernier asset d'un type pour une scène » (_latest_asset).
    __table_args__ = (Index("ix_assets_project_kind_scene", "project_id", "kind", "scene_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    scene_id: Mapped[int | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # reference | clip | keyframe | voice | render
    key: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(80))
    variant: Mapped[int] = mapped_column(Integer, default=1)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetOriginal(Base):
    """Nom de fichier d'origine d'un asset importé (upload) : donnée affichée seulement, nettoyée à l'import
    (`app.uploads.clean_name`), jamais utilisée pour construire une clé ou un chemin. Suit la suppression de l'asset."""
    __tablename__ = "asset_originals"
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MusicTrack(Base):
    __tablename__ = "music_library"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    key: Mapped[str] = mapped_column(String(300))


class ProviderCall(Base):
    __tablename__ = "provider_calls"
    # project_id : coût par projet (budget, cartes) ; created_at : journal des appels, du plus récent au plus ancien.
    __table_args__ = (Index("ix_provider_calls_project_id", "project_id"),
                      Index("ix_provider_calls_created_at", "created_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    step: Mapped[str] = mapped_column(String(30))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6, asdecimal=False), default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20))  # ok | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreditBalance(Base):
    """Solde d'un compte en deux lots : crédits d'abonnement (consommés en premier) puis rechargés."""
    __tablename__ = "credit_balances"
    __table_args__ = (CheckConstraint("subscription >= 0 AND topup >= 0", name="ck_credit_balances_non_negative"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    subscription: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    topup: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class CreditReservation(Base):
    """Crédits retenus au lancement d'une génération, réglés (ou rendus) à sa fin : `open` puis `closed`."""
    __tablename__ = "credit_reservations"
    __table_args__ = (Index("ix_credit_reservations_status_created_at", "status", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    step: Mapped[str] = mapped_column(String(30))
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    parts: Mapped[dict] = mapped_column(JSON)  # {"subscription": n, "topup": n} : lot d'origine de chaque crédit retenu
    scene_prices: Mapped[dict] = mapped_column(JSON, default=dict)  # {"<scene_id>": crédits} des étapes par scène
    status: Mapped[str] = mapped_column(String(10), default="open")
    used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreditEntry(Base):
    """Registre append-only : pour chaque lot, la somme des montants redonne toujours le solde."""
    __tablename__ = "credit_entries"
    # Un seul crédit d'inscription par compte, garanti par la base.
    __table_args__ = (Index("ix_credit_entries_user_id_id", "user_id", "id"),
                      Index("uq_credit_entries_signup_grant", "user_id", unique=True,
                            postgresql_where=text("kind = 'signup_grant'")))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    bucket: Mapped[str] = mapped_column(String(20))  # subscription | topup
    amount: Mapped[int] = mapped_column(Integer)  # signé, jamais nul
    kind: Mapped[str] = mapped_column(String(20))  # signup_grant | reserve | refund | adjust
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("credit_reservations.id", ondelete="SET NULL"),
                                                       nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    step: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StripeEvent(Base):
    """Événement Stripe déjà traité : un même événement (Stripe en rejoue) ne crédite jamais deux fois."""
    __tablename__ = "stripe_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    type: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
