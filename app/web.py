"""Optional, same-origin UI hosting; all API routes must be registered first."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, directory: Path) -> None:
    """Keep API-only development usable before the first frontend build."""
    if (directory / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=directory, html=True), name='frontend')
