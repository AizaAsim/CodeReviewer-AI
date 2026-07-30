from __future__ import annotations

import logging
from importlib.metadata import version

from fastapi import FastAPI

from codereviewer.config import settings
from codereviewer.evalapi.router import router as eval_router
from codereviewer.webhooks.router import router as webhooks_router

__version__ = version("codereviewer")


def create_app() -> FastAPI:
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    app = FastAPI(title="CodeReviewer AI", version=__version__)
    app.include_router(webhooks_router)
    app.include_router(eval_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
