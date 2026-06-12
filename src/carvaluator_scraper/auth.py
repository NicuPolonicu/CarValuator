from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request


SESSION_COOKIE_NAME = "carvaluator_session"
PASSWORD_ITERATIONS = 310_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(slots=True)
class AuthUser:
    id: int
    email: str
    username: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class PredictionHistoryItem:
    id: int
    user_id: int
    source: str
    url: str
    title: str
    image_url: str | None
    actual_price_eur: float | None
    predicted_price_eur: float
    verdict: str
    model_name: str
    delta_percent: float | None
    threshold_percent: float | None
    ensemble_method: str | None
    similar_count: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "source": self.source,
            "url": self.url,
            "title": self.title,
            "image_url": self.image_url,
            "actual_price_eur": self.actual_price_eur,
            "predicted_price_eur": self.predicted_price_eur,
            "verdict": self.verdict,
            "model_name": self.model_name,
            "delta_percent": self.delta_percent,
            "threshold_percent": self.threshold_percent,
            "ensemble_method": self.ensemble_method,
            "similar_count": self.similar_count,
            "created_at": self.created_at,
        }


def get_auth_db_path() -> Path:
    configured = os.getenv("CARVALUATOR_AUTH_DB", "data/carvaluator_users.db")
    path = Path(configured)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


@contextmanager
def get_connection():
    connection = sqlite3.connect(get_auth_db_path())
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_auth_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS prediction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                image_url TEXT,
                actual_price_eur REAL,
                predicted_price_eur REAL NOT NULL,
                verdict TEXT NOT NULL,
                model_name TEXT NOT NULL,
                delta_percent REAL,
                prediction_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_prediction_history_user_created ON prediction_history(user_id, created_at)")


def create_user(*, email: str, username: str, password: str) -> AuthUser:
    email = normalize_email(email)
    username = normalize_username(username)
    validate_password(password)
    password_hash = hash_password(password)
    now = utc_now()

    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (email, username, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (email, username, password_hash, now),
            )
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Exista deja un cont cu acest email sau username.") from exc

    return AuthUser(id=user_id, email=email, username=username, created_at=now)


def authenticate_user(*, identifier: str, password: str) -> AuthUser | None:
    normalized_identifier = (identifier or "").strip()
    if not normalized_identifier:
        return None
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, email, username, password_hash, created_at
            FROM users
            WHERE email = ? COLLATE NOCASE OR username = ? COLLATE NOCASE
            """,
            (normalized_identifier, normalized_identifier),
        ).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return AuthUser(id=int(row["id"]), email=row["email"], username=row["username"], created_at=row["created_at"])


def create_session(user_id: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=int(os.getenv("CARVALUATOR_SESSION_DAYS", "7")))
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, expires_at.isoformat(), now.isoformat()),
        )
    return token, expires_at


def delete_session(token: str | None) -> None:
    if not token:
        return
    with get_connection() as connection:
        connection.execute("DELETE FROM sessions WHERE token = ?", (token,))


def record_prediction_history(*, user_id: int, prediction: dict[str, Any]) -> PredictionHistoryItem:
    now = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO prediction_history (
                user_id,
                source,
                url,
                title,
                image_url,
                actual_price_eur,
                predicted_price_eur,
                verdict,
                model_name,
                delta_percent,
                prediction_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                prediction.get("source") or "unknown",
                prediction.get("url") or "",
                prediction.get("title") or "Anunt fara titlu",
                prediction.get("image_url"),
                prediction.get("actual_price_eur"),
                prediction.get("predicted_price_eur") or 0.0,
                prediction.get("verdict") or "unknown",
                prediction.get("model_name") or "unknown_model",
                prediction.get("delta_percent"),
                json.dumps(prediction, ensure_ascii=False),
                now,
            ),
        )
        history_id = int(cursor.lastrowid)
    return PredictionHistoryItem(
        id=history_id,
        user_id=user_id,
        source=prediction.get("source") or "unknown",
        url=prediction.get("url") or "",
        title=prediction.get("title") or "Anunt fara titlu",
        image_url=prediction.get("image_url"),
        actual_price_eur=prediction.get("actual_price_eur"),
        predicted_price_eur=prediction.get("predicted_price_eur") or 0.0,
        verdict=prediction.get("verdict") or "unknown",
        model_name=prediction.get("model_name") or "unknown_model",
        delta_percent=prediction.get("delta_percent"),
        threshold_percent=prediction.get("threshold_percent"),
        ensemble_method=_prediction_ensemble_method(prediction),
        similar_count=len(prediction.get("similar_listings") or []),
        created_at=now,
    )


def list_prediction_history(*, user_id: int, limit: int = 20) -> list[PredictionHistoryItem]:
    safe_limit = max(1, min(limit, 100))
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, source, url, title, image_url, actual_price_eur,
                   predicted_price_eur, verdict, model_name, delta_percent,
                   prediction_json, created_at
            FROM prediction_history
            WHERE user_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (user_id, safe_limit),
        ).fetchall()
    return [
        _history_item_from_row(row)
        for row in rows
    ]


def get_prediction_history_detail(*, user_id: int, history_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, user_id, prediction_json, created_at
            FROM prediction_history
            WHERE id = ? AND user_id = ?
            """,
            (history_id, user_id),
        ).fetchone()
    if row is None:
        return None

    try:
        prediction = json.loads(row["prediction_json"])
    except (json.JSONDecodeError, TypeError):
        prediction = {}
    prediction["history_id"] = int(row["id"])
    prediction["history_created_at"] = row["created_at"]
    return prediction


def delete_prediction_history_item(*, user_id: int, history_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM prediction_history WHERE id = ? AND user_id = ?",
            (history_id, user_id),
        )
    return cursor.rowcount > 0


def delete_all_prediction_history(*, user_id: int) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM prediction_history WHERE user_id = ?",
            (user_id,),
        )
    return int(cursor.rowcount)


def get_current_user(request: Request) -> AuthUser:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Trebuie sa fii autentificat pentru aceasta actiune.")

    now = datetime.now(timezone.utc)
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT users.id, users.email, users.username, users.created_at, sessions.expires_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="Sesiunea nu mai este valida. Te rog autentifica-te din nou.")

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at <= now:
        delete_session(token)
        raise HTTPException(status_code=401, detail="Sesiunea a expirat. Te rog autentifica-te din nou.")

    return AuthUser(id=int(row["id"]), email=row["email"], username=row["username"], created_at=row["created_at"])


def normalize_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if not EMAIL_RE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Te rog introdu un email valid.")
    return normalized


def normalize_username(username: str) -> str:
    normalized = (username or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", normalized):
        raise HTTPException(
            status_code=422,
            detail="Username-ul trebuie sa aiba 3-32 caractere si poate contine litere, cifre si underscore.",
        )
    return normalized


def validate_password(password: str) -> None:
    if len(password or "") < 8:
        raise HTTPException(status_code=422, detail="Parola trebuie sa aiba cel putin 8 caractere.")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_item_from_row(row: sqlite3.Row) -> PredictionHistoryItem:
    try:
        prediction = json.loads(row["prediction_json"])
    except (json.JSONDecodeError, TypeError):
        prediction = {}
    return PredictionHistoryItem(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        source=row["source"],
        url=row["url"],
        title=row["title"],
        image_url=row["image_url"],
        actual_price_eur=row["actual_price_eur"],
        predicted_price_eur=row["predicted_price_eur"],
        verdict=row["verdict"],
        model_name=row["model_name"],
        delta_percent=row["delta_percent"],
        threshold_percent=prediction.get("threshold_percent"),
        ensemble_method=_prediction_ensemble_method(prediction),
        similar_count=len(prediction.get("similar_listings") or []),
        created_at=row["created_at"],
    )


def _prediction_ensemble_method(prediction: dict[str, Any]) -> str | None:
    for estimate in prediction.get("model_estimates") or []:
        if estimate.get("model") == "weighted_average" and estimate.get("weighting"):
            return str(estimate["weighting"])
    return None
