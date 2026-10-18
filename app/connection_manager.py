import json
from typing import Any

from pydantic import BaseModel, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.catalog import ConnectionORM
from app.models import DBConnection


def _serialize_secrets(value: Any) -> Any:
    """
    Преобразует конфигурацию в JSON-совместимый вид.
    """
    if isinstance(value, SecretStr):
        return value.get_secret_value()  # Базовый случай для паролей

    if isinstance(value, BaseModel):
        return _serialize_secrets(value.model_dump())  # Переходим к сериализации словаря

    if isinstance(value, dict):
        return {
            key: _serialize_secrets(item)  # Вызываем рекурсивно для каждых значений (Будь то хоть BaseModel, хоть list)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_serialize_secrets(item) for item in value]  # Разбиваем на набор отдельных объектов

    return value  # Общий базовый случай


class ConnectionManager:
    """
    Работает с хранениями свойств подключений любых типов (в т.ч. невалидных) к БД
    """
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def create_connection(
        self,
        name: str,
        connection_type: str,
        properties: BaseModel | dict[str, Any],
    ) -> str:
        """
        Сохраняет подключение любого поддерживаемого типа.
        """
        payload = _serialize_secrets(properties)

        with self.session_factory() as session:
            connection = ConnectionORM(
                name=name,
                connection_type=connection_type.lower(),
                payload=json.dumps(payload, ensure_ascii=False),
            )
            session.add(connection)
            session.flush()
            connection_id = connection.connection_id
            session.commit()

        return connection_id

    def get_connection(self, connection_id: str) -> DBConnection | None:
        """
        Возвращает подключение вместе с его конфигурацией.
        """
        with self.session_factory() as session:
            connection = session.get(ConnectionORM, connection_id)

            if connection is None:
                return None

            connection_info = DBConnection(
                connection_id=connection.connection_id,
                name=connection.name,
                connection_type=connection.connection_type,
                properties=json.loads(connection.payload),
                created_at=connection.created_at,
            )

            return connection_info

    def list_connections(self) -> list[dict]:
        """
        Возвращает список подключений без конфигураций и паролей.
        """
        with self.session_factory() as session:
            connections = session.scalars(
                select(ConnectionORM).order_by(ConnectionORM.name)
            ).all()

            return [
                {
                    "connection_id": connection.connection_id,
                    "name": connection.name,
                    "connection_type": connection.connection_type,
                    "created_at": connection.created_at,
                }
                for connection in connections
            ]

    def delete_connection(self, connection_id: str) -> bool:
        """
        Удаляет подключение. Возвращает False, если его нет.
        """
        with self.session_factory() as session:
            connection = session.get(ConnectionORM, connection_id)

            if connection is None:
                return False

            session.delete(connection)
            session.commit()
            return True
