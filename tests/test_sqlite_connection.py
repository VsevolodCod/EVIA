
import sqlite3

import pytest

from app.connection_manager import ConnectionManager
from app.data_sources.sqlite_adapter import SQLiteAdapter
from app.db import create_catalog_database
from app.models import DataSource


@pytest.fixture
def sqlite_db(tmp_path):
    """Создаёт тестовую БД с таблицами и тестовыми данными."""
    db_path = tmp_path / "test.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
            CREATE TABLE departments (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );

            CREATE TABLE employees (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                age INTEGER,
                department_id INTEGER,
                FOREIGN KEY (department_id) REFERENCES departments(id)
            );

            INSERT INTO departments (id, name) VALUES
                (1, 'Engineering'),
                (2, 'Analytics');

            INSERT INTO employees (id, name, age, department_id) VALUES
                (1, 'Alice', 25, 1),
                (2, 'Bob', 30, 2),
                (3, 'Charlie', NULL, 1);
        """)

    return db_path


@pytest.fixture
def adapter_and_connection(sqlite_db, tmp_path):
    """Создаёт отдельный каталог и регистрирует SQLite-подключение."""
    catalog_path = tmp_path / "catalog.db"

    catalog_engine, catalog_sessions = create_catalog_database(catalog_path)
    connection_manager = ConnectionManager(catalog_sessions)

    connection_id = connection_manager.create_connection(
        name="Test SQLite",
        connection_type="sqlite",
        properties={"path": str(sqlite_db)},
    )

    adapter = SQLiteAdapter(connection_manager)

    yield adapter, connection_id

    catalog_engine.dispose()


def test_sqlite_database_contains_expected_tables(sqlite_db):
    """Проверяет, что тестовая БД создана и содержит нужные таблицы."""
    with sqlite3.connect(sqlite_db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {"departments", "employees"} <= tables


def test_sqlite_adapter_introspects_schema(adapter_and_connection):
    """Проверяет обнаружение таблиц, колонок и внешних ключей."""
    adapter, connection_id = adapter_and_connection

    source = DataSource(
        source_id="test-source",
        name="Test SQLite.employees",
        source_type="sqlite",
        connection_id=connection_id,
        schema_name="main",
        table_name="employees",
    )

    schema = adapter.introspect_schema(source)

    assert schema.source_id == source.source_id

    # Проверяем, что адаптер обнаружил обе таблицы.
    objects_by_name = {
        obj.name.split(".", maxsplit=1)[-1]: obj
        for obj in schema.objects
    }

    assert "employees" in objects_by_name
    assert "departments" in objects_by_name

    # Проверяем поля employees.
    employees = objects_by_name["employees"]
    field_names = {field.name for field in employees.fields}

    assert {"id", "name", "age", "department_id"} <= field_names

    # Проверяем поля departments.
    departments = objects_by_name["departments"]
    department_field_names = {field.name for field in departments.fields}

    assert {"id", "name"} <= department_field_names

    # Проверяем обнаружение внешнего ключа employees.department_id
    # -> departments.id.
    assert any(
        relation.left_field == "department_id"
        and relation.right_field == "id"
        and relation.discovery_method == "foreign_key"
        for relation in schema.relations
    )
