"""PostgreSQL account, session and recovery-code storage."""

import hashlib
import hmac
import secrets
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pwdlib import PasswordHash
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, create_engine, delete, inspect, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


SESSION_DAYS = 14
RESET_MINUTES = 10
password_hash = PasswordHash.recommended()
dummy_hash = password_hash.hash("not a real user password")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalized_email(value: str) -> str:
    return value.strip().casefold()


class AuthBase(DeclarativeBase):
    pass


class UserRow(AuthBase):
    __tablename__ = "auth_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_digest: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_legacy_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    avatar_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    avatar_mime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    avatar_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionRow(AuthBase):
    __tablename__ = "auth_sessions"
    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResetRow(AuthBase):
    __tablename__ = "auth_resets"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_users.id", ondelete="CASCADE"), primary_key=True)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AttemptRow(AuthBase):
    __tablename__ = "auth_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    resets_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    name: str
    created_at: datetime
    avatar_updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: UserRow) -> "Account":
        return cls(row.id, row.email, row.name, row.created_at, row.avatar_updated_at)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class AuthStore:
    def __init__(self, database_url: str, *, secret: str):
        if not secret or len(secret) < 16:
            raise ValueError("AUTH_SECRET must have at least 16 characters")
        if database_url.startswith("postgres://"):
            database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
        elif database_url.startswith("postgresql://"):
            database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.secret = secret.encode()

    def initialize(self) -> None:
        AuthBase.metadata.create_all(self.engine)
        # create_all does not add columns to accounts created before avatars existed.
        with self.engine.begin() as connection:
            existing = {column["name"] for column in inspect(connection).get_columns("auth_users")}
            column_types = {
                "avatar_bytes": "BYTEA" if self.engine.dialect.name == "postgresql" else "BLOB",
                "avatar_mime": "VARCHAR(32)",
                "avatar_updated_at": "TIMESTAMPTZ" if self.engine.dialect.name == "postgresql" else "TIMESTAMP",
            }
            for name, kind in column_types.items():
                if name not in existing:
                    clause = "IF NOT EXISTS " if self.engine.dialect.name == "postgresql" else ""
                    connection.execute(text(f"ALTER TABLE auth_users ADD COLUMN {clause}{name} {kind}"))

    def close(self) -> None:
        self.engine.dispose()

    def register(self, email: str, password: str, name: str, *, _legacy_owner: bool = False) -> Account:
        if not 12 <= len(password) <= 128:
            raise ValueError("Password must contain 12–128 characters")
        email = normalized_email(email)
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Name must contain 1–80 characters")
        row = UserRow(id=str(uuid4()), email=email, name=name,
                      password_digest=password_hash.hash(password), created_at=utc_now(),
                      is_legacy_owner=_legacy_owner)
        try:
            with self.sessions.begin() as session:
                session.add(row)
        except IntegrityError as exc:
            raise ValueError("Email already registered") from exc
        return Account.from_row(row)

    def bootstrap(self, email: str, password: str, name: str) -> Account:
        email = normalized_email(email)
        with self.sessions() as session:
            owner = session.scalar(select(UserRow).where(UserRow.is_legacy_owner.is_(True)))
            if owner is not None and owner.email != email:
                raise ValueError("bootstrap owner cannot be changed")
            existing = session.scalar(select(UserRow).where(UserRow.email == email))
            if existing:
                if not existing.is_legacy_owner:
                    raise ValueError("bootstrap account already exists without trusted ownership")
                return Account.from_row(existing)
        return self.register(email, password, name, _legacy_owner=True)

    def authenticate(self, email: str, password: str) -> Account | None:
        with self.sessions() as session:
            row = session.scalar(select(UserRow).where(UserRow.email == normalized_email(email)))
            if not password_hash.verify(password, row.password_digest if row else dummy_hash):
                return None
            return Account.from_row(row) if row else None

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.sessions.begin() as session:
            session.add(SessionRow(token_digest=hashlib.sha256(token.encode()).hexdigest(),
                                   user_id=user_id, expires_at=utc_now() + timedelta(days=SESSION_DAYS)))
        return token

    def get_session_user(self, token: str | None) -> Account | None:
        if not token or len(token) > 256:
            return None
        with self.sessions() as session:
            record = session.get(SessionRow, hashlib.sha256(token.encode()).hexdigest())
            if record is None or _aware(record.expires_at) <= utc_now():
                return None
            user = session.get(UserRow, record.user_id)
            return Account.from_row(user) if user else None

    def revoke_session(self, token: str | None) -> None:
        if token:
            with self.sessions.begin() as session:
                session.execute(delete(SessionRow).where(SessionRow.token_digest == hashlib.sha256(token.encode()).hexdigest()))

    def reserve_login_attempt(self, email: str, remote: str) -> bool:
        key = self._attempt_key(email, remote)
        with self.sessions.begin() as session:
            insert = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
            session.execute(insert(AttemptRow).values(
                key=key, count=0, resets_at=utc_now() + timedelta(minutes=15)
            ).on_conflict_do_nothing(index_elements=["key"]))
            row = session.get(AttemptRow, key, with_for_update=True)
            if _aware(row.resets_at) <= utc_now():
                row.count = 0
                row.resets_at = utc_now() + timedelta(minutes=15)
            if row.count >= 8:
                return False
            row.count += 1
            return True

    def clear_login_failures(self, email: str, remote: str) -> None:
        with self.sessions.begin() as session:
            session.execute(delete(AttemptRow).where(AttemptRow.key == self._attempt_key(email, remote)))

    def _attempt_key(self, email: str, remote: str) -> str:
        return hmac.new(self.secret, f"{normalized_email(email)}:{remote}".encode(), hashlib.sha256).hexdigest()

    def rename(self, user_id: str, name: str) -> Account:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Name must contain 1–80 characters")
        with self.sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise ValueError("Account not found")
            row.name = name
            session.flush()
            return Account.from_row(row)

    def save_avatar(self, user_id: str, raw: bytes) -> Account:
        if not raw or len(raw) > 1_048_576:
            raise ValueError("Image must be smaller than 1 MB")
        try:
            with Image.open(BytesIO(raw)) as original:
                if original.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("Only PNG, JPEG and WebP images are supported")
                image = ImageOps.exif_transpose(original)
                image.thumbnail((256, 256))
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = BytesIO()
                image.save(output, format="WEBP", quality=82, method=4)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("Invalid image") from exc
        with self.sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise ValueError("Account not found")
            row.avatar_bytes = output.getvalue()
            row.avatar_mime = "image/webp"
            row.avatar_updated_at = utc_now()
            session.flush()
            return Account.from_row(row)

    def get_avatar(self, user_id: str) -> tuple[bytes, str] | None:
        with self.sessions() as session:
            row = session.get(UserRow, user_id)
            if row is None or row.avatar_bytes is None:
                return None
            return row.avatar_bytes, row.avatar_mime or "image/webp"

    def remove_avatar(self, user_id: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise ValueError("Account not found")
            row.avatar_bytes = None
            row.avatar_mime = None
            row.avatar_updated_at = None

    def change_password(self, user_id: str, current: str, new: str) -> bool:
        if not 12 <= len(new) <= 128:
            raise ValueError("Password must contain 12–128 characters")
        with self.sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None or not password_hash.verify(current, row.password_digest):
                return False
            row.password_digest = password_hash.hash(new)
            session.execute(delete(SessionRow).where(SessionRow.user_id == user_id))
            return True

    def _code_digest(self, user_id: str, code: str) -> str:
        return hmac.new(self.secret, f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()

    def issue_reset_code(self, email: str) -> str | None:
        with self.sessions.begin() as session:
            row = session.scalar(select(UserRow).where(UserRow.email == normalized_email(email)))
            if row is None:
                return None
            previous = session.get(ResetRow, row.id)
            if previous is not None and utc_now() - _aware(previous.sent_at) < timedelta(seconds=60):
                return None
            code = f"{secrets.randbelow(100_000_000):08d}"
            if previous is None:
                session.add(ResetRow(user_id=row.id, code_digest=self._code_digest(row.id, code),
                                     expires_at=utc_now() + timedelta(minutes=RESET_MINUTES), sent_at=utc_now(), attempts=0))
            else:
                previous.code_digest = self._code_digest(row.id, code)
                previous.expires_at = utc_now() + timedelta(minutes=RESET_MINUTES)
                previous.sent_at = utc_now()
                previous.attempts = 0
            return code

    def reset_password(self, email: str, code: str, new_password: str) -> bool:
        if not 12 <= len(new_password) <= 128:
            raise ValueError("Password must contain 12–128 characters")
        if len(code) != 8 or not code.isascii() or not code.isdigit():
            return False
        with self.sessions.begin() as session:
            row = session.scalar(select(UserRow).where(UserRow.email == normalized_email(email)))
            if row is None:
                return False
            reset = session.get(ResetRow, row.id, with_for_update=True)
            if reset is None or _aware(reset.expires_at) <= utc_now() or reset.attempts >= 5:
                return False
            reset.attempts += 1
            if not hmac.compare_digest(reset.code_digest, self._code_digest(row.id, code)):
                return False
            row.password_digest = password_hash.hash(new_password)
            session.delete(reset)
            session.execute(delete(SessionRow).where(SessionRow.user_id == row.id))
            return True
