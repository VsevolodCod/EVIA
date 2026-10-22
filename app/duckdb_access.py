"""Coordinate DuckDB connections with different access modes in one process."""

from threading import RLock


# DuckDB cannot keep a read-only query connection open beside a read-write
# import/profile connection to the same database file. Both paths use this
# lock for the entire connection lifetime, including result fetching.
DUCKDB_ACCESS_LOCK = RLock()
