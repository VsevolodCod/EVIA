"""PostgreSQL account, session and recovery-code storage."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pwdlib import PasswordHash
from sqlalchemy import DateTime, ForeignKey, Integer, String, create_engine, delete, select
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

    @classmethod
    def from_row(cls, row: UserRow) -> "Account":
        return cls(row.id, row.email, row.name, row.created_at)


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

    def close(self) -> None:
        self.engine.dispose()

    def register(self, email: str, password: str, name: str) -> Account:
        if not 12 <= len(password) <= 128:
            raise ValueError("Password must contain 12–128 characters")
        email = normalized_email(email)
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Name must contain 1–80 characters")
        row = UserRow(id=str(uuid4()), email=email, name=name,
                      password_digest=password_hash.hash(password), created_at=utc_now())
        try:
            with self.sessions.begin() as session:
                session.add(row)
        except IntegrityError as exc:
            raise ValueError("Email already registered") from exc
        return Account.from_row(row)

    def bootstrap(self, email: str, password: str, name: str) -> Account:
        email = normalized_email(email)
        with self.sessions() as session:
            existing = session.scalar(select(UserRow).where(UserRow.email == email))
            if existing:
                return Account.from_row(existing)
        return self.register(email, password, name)

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

    def login_allowed(self, email: str, remote: str) -> bool:
        key = self._attempt_key(email, remote)
        with self.sessions() as session:
            row = session.get(AttemptRow, key)
            return row is None or _aware(row.resets_at) <= utc_now() or row.count < 8

    def record_login_failure(self, email: str, remote: str) -> None:
        key = self._attempt_key(email, remote)
        with self.sessions.begin() as session:
            row = session.get(AttemptRow, key, with_for_update=True)
            if row is None:
                session.add(AttemptRow(key=key, count=1, resets_at=utc_now() + timedelta(minutes=15)))
            elif _aware(row.resets_at) <= utc_now():
                row.count = 1
                row.resets_at = utc_now() + timedelta(minutes=15)
            else:
                row.count += 1

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
