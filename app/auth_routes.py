"""Same-origin account API and SMTP password recovery."""

import os
import smtplib
from email.message import EmailMessage

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field

from app.auth import Account, AuthStore, SESSION_DAYS


router = APIRouter(prefix="/auth", tags=["account"])
COOKIE = "evia_session"


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=80)


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class ResetRequest(BaseModel):
    email: EmailStr


class ResetConfirm(BaseModel):
    email: EmailStr
    code: str
    new_password: str


def store(request: Request) -> AuthStore:
    return request.app.state.auth_store


def account(request: Request) -> Account:
    user = getattr(request.state, "account", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def public(user: Account) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name,
            "created_at": user.created_at.isoformat()}


def set_cookie(request: Request, response: Response, token: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=secure, samesite="lax", path="/")


def mail_configured() -> bool:
    return all(os.getenv(key) for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM"))


def send_reset_code(recipient: str, code: str) -> None:
    message = EmailMessage()
    message["From"] = os.environ["MAIL_FROM"]
    message["To"] = recipient
    message["Subject"] = "EVIA — код восстановления пароля"
    message.set_content(f"Ваш код восстановления EVIA: {code}\nКод действует 10 минут. Если вы не запрашивали его, игнорируйте письмо.")
    port = int(os.getenv("SMTP_PORT", "465"))
    if port == 465:
        with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], port, timeout=10) as smtp:
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)


@router.get("/status")
def status(request: Request):
    return {"enabled": hasattr(request.app.state, "auth_store"), "recovery_available": mail_configured()}


@router.post("/register", status_code=201)
async def register(body: Registration, request: Request, response: Response):
    try:
        user = await run_in_threadpool(store(request).register, str(body.email), body.password, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=409 if "already" in str(exc) else 400, detail=str(exc)) from exc
    token = await run_in_threadpool(store(request).create_session, user.id)
    set_cookie(request, response, token)
    return public(user)


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response):
    remote = request.client.host if request.client else "unknown"
    auth = store(request)
    if not await run_in_threadpool(auth.login_allowed, str(body.email), remote):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in 15 minutes")
    user = await run_in_threadpool(auth.authenticate, str(body.email), body.password)
    if user is None:
        await run_in_threadpool(auth.record_login_failure, str(body.email), remote)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await run_in_threadpool(auth.clear_login_failures, str(body.email), remote)
    token = await run_in_threadpool(auth.create_session, user.id)
    set_cookie(request, response, token)
    return public(user)


@router.get("/me")
def me(request: Request):
    return public(account(request))


@router.patch("/profile")
async def update_profile(body: ProfileUpdate, request: Request):
    try:
        user = await run_in_threadpool(store(request).rename, account(request).id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return public(user)


@router.post("/password")
async def change_password(body: PasswordChange, request: Request, response: Response):
    try:
        changed = await run_in_threadpool(store(request).change_password, account(request).id,
                                          body.current_password, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    token = await run_in_threadpool(store(request).create_session, account(request).id)
    set_cookie(request, response, token)
    return {"ok": True}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    await run_in_threadpool(store(request).revoke_session, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")


@router.post("/reset/request")
async def request_reset(body: ResetRequest, request: Request):
    if not mail_configured():
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    code = await run_in_threadpool(store(request).issue_reset_code, str(body.email))
    if code:
        try:
            await run_in_threadpool(send_reset_code, str(body.email), code)
        except (OSError, smtplib.SMTPException) as exc:
            raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable") from exc
    return {"ok": True}


@router.post("/reset/confirm")
async def confirm_reset(body: ResetConfirm, request: Request):
    try:
        changed = await run_in_threadpool(store(request).reset_password, str(body.email), body.code, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(status_code=400, detail="Code is invalid or expired")
    return {"ok": True}
