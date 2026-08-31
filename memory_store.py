"""
Memory & Consent Manager (H6). Fuente: V2.1 §7 + CONSOLIDADA §27.

Reglas que este módulo respeta:
- Nunca se guarda PAN completo, CVV, PIN ni contraseñas (ni siquiera se
  reciben - el sistema solo conoce "banco" y "tarjeta" como texto libre).
- Guardar banco/tarjeta requiere consentimiento EXPLÍCITO (el flujo de
  pregunta sí/no vive en orchestrator.py) - este módulo solo persiste
  cuando se le pide, nunca decide por su cuenta.
- El borrado es transaccional y auditable SIN conservar el dato eliminado
  (la tabla audit_events guarda que "se borró algo", no qué era).
- La memoria de sesión (qué categoría veníamos buscando) es temporal y NO
  requiere consentimiento especial (V2.1 §7.1: "sesión: temporal, ej.
  presupuesto de esta búsqueda").

Si no hay DATABASE_URL configurada (o falla la conexión), degrada a
almacenamiento en memoria del proceso: el sistema sigue funcionando, pero
la memoria no sobrevive a un reinicio del servidor. Mismo criterio que
LLMIntentRouter (H2): nunca romper el sistema por falta de un recurso
externo opcional - y el motivo del fallback queda impreso en logs.
"""

from __future__ import annotations
import os
from datetime import datetime, timezone

from domain import PaymentContext


class MemoryStore:
    """Interfaz común, implementada por Postgres o por memoria de proceso."""

    def get_payment_context(self, user_id: str) -> PaymentContext | None:
        raise NotImplementedError

    def save_payment_context(self, user_id: str, banco: str | None, tarjeta: str | None) -> None:
        raise NotImplementedError

    def delete_all_payment_data(self, user_id: str) -> None:
        raise NotImplementedError

    def get_session_entities(self, session_id: str) -> dict:
        raise NotImplementedError

    def save_session_entities(self, session_id: str, entities: dict) -> None:
        raise NotImplementedError

    def get_pending_action(self, session_id: str) -> dict | None:
        raise NotImplementedError

    def set_pending_action(self, session_id: str, action: dict | None) -> None:
        raise NotImplementedError


class InMemoryStore(MemoryStore):
    """Fallback sin base de datos - vive solo mientras el proceso esté vivo."""

    def __init__(self):
        self._payment: dict[str, PaymentContext] = {}
        self._session: dict[str, dict] = {}
        self._pending: dict[str, dict] = {}

    def get_payment_context(self, user_id):
        return self._payment.get(user_id)

    def save_payment_context(self, user_id, banco, tarjeta):
        self._payment[user_id] = PaymentContext(banco=banco, tarjeta=tarjeta)

    def delete_all_payment_data(self, user_id):
        self._payment.pop(user_id, None)

    def get_session_entities(self, session_id):
        return dict(self._session.get(session_id, {}))

    def save_session_entities(self, session_id, entities):
        self._session[session_id] = dict(entities)

    def get_pending_action(self, session_id):
        return self._pending.get(session_id)

    def set_pending_action(self, session_id, action):
        if action is None:
            self._pending.pop(session_id, None)
        else:
            self._pending[session_id] = action


class PostgresMemoryStore(MemoryStore):
    def __init__(self, database_url: str):
        import psycopg2  # import local: no romper si el paquete no está instalado
        from psycopg2.extras import Json
        self._psycopg2 = psycopg2
        self._Json = Json
        self._database_url = database_url
        self._ensure_schema()

    def _connect(self):
        return self._psycopg2.connect(self._database_url)

    def _ensure_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payment_instruments (
                    user_id TEXT PRIMARY KEY,
                    banco TEXT,
                    tarjeta TEXT,
                    consent_given_at TIMESTAMPTZ NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS session_context (
                    session_id TEXT PRIMARY KEY,
                    entities JSONB NOT NULL DEFAULT '{}',
                    pending_action JSONB,
                    updated_at TIMESTAMPTZ NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    accion TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL
                );
            """)
            conn.commit()

    def get_payment_context(self, user_id: str) -> PaymentContext | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT banco, tarjeta FROM payment_instruments WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return PaymentContext(banco=row[0], tarjeta=row[1]) if row else None

    def save_payment_context(self, user_id: str, banco: str | None, tarjeta: str | None) -> None:
        now = datetime.now(timezone.utc)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO payment_instruments (user_id, banco, tarjeta, consent_given_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET banco = EXCLUDED.banco, tarjeta = EXCLUDED.tarjeta,
                    consent_given_at = EXCLUDED.consent_given_at;
            """, (user_id, banco, tarjeta, now))
            cur.execute(
                "INSERT INTO audit_events (user_id, accion, timestamp) VALUES (%s, %s, %s);",
                (user_id, "guardar_memoria_bancaria", now),
            )
            conn.commit()

    def delete_all_payment_data(self, user_id: str) -> None:
        # V2.1 §7.3: borrado transaccional, auditable, sin conservar el dato eliminado.
        now = datetime.now(timezone.utc)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM payment_instruments WHERE user_id = %s", (user_id,))
            cur.execute(
                "INSERT INTO audit_events (user_id, accion, timestamp) VALUES (%s, %s, %s);",
                (user_id, "borrado_total_memoria_bancaria", now),
            )
            conn.commit()

    def get_session_entities(self, session_id: str) -> dict:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT entities FROM session_context WHERE session_id = %s", (session_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else {}

    def save_session_entities(self, session_id: str, entities: dict) -> None:
        now = datetime.now(timezone.utc)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO session_context (session_id, entities, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE
                SET entities = EXCLUDED.entities, updated_at = EXCLUDED.updated_at;
            """, (session_id, self._Json(entities), now))
            conn.commit()

    def get_pending_action(self, session_id: str) -> dict | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pending_action FROM session_context WHERE session_id = %s", (session_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def set_pending_action(self, session_id: str, action: dict | None) -> None:
        now = datetime.now(timezone.utc)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO session_context (session_id, entities, pending_action, updated_at)
                VALUES (%s, '{}', %s, %s)
                ON CONFLICT (session_id) DO UPDATE
                SET pending_action = EXCLUDED.pending_action, updated_at = EXCLUDED.updated_at;
            """, (session_id, self._Json(action) if action else None, now))
            conn.commit()


def get_memory_store() -> MemoryStore:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("[memory_store] DATABASE_URL no configurada; usando memoria en "
              "proceso (no persiste si el servidor se reinicia).")
        return InMemoryStore()
    try:
        return PostgresMemoryStore(database_url)
    except Exception as exc:
        print(f"[memory_store] No se pudo conectar a Postgres; usando memoria "
              f"en proceso. Motivo: {exc!r}")
        return InMemoryStore()

