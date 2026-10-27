"""SQLite review API; fixture mode is an explicit preview-only choice."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.database_router import build_database_router
from src.api.router import router
from src.persist.database import DEFAULT_DATABASE_URL, create_database_engine
from src.persist.embedding import embed_review_text
from src.persist.review import EmbedText, ReviewConflict


def create_app(
    *,
    api_prefix: str = "",
    use_fixtures: bool = False,
    database_url: str | None = None,
    reviewer_token: str | None = None,
    embed_text: EmbedText = embed_review_text,
) -> FastAPI:
    """Build the database API, or explicitly request the separate fixture preview.

    The prefix is empty for local use and the contract tests. The Vercel entry
    passes ``/api`` so those paths do not collide with the React routes.
    """
    app = FastAPI(title="Consult SI", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if use_fixtures:
        app.include_router(router, prefix=api_prefix)
    else:
        engine = create_database_engine(
            database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        )
        app.state.database_engine = engine
        app.include_router(
            build_database_router(
                engine,
                reviewer_token=reviewer_token
                if reviewer_token is not None
                else os.environ.get("REVIEWER_TOKEN"),
                embed_text=embed_text,
            ),
            prefix=api_prefix,
        )

    @app.exception_handler(LookupError)
    async def missing(_request, exc):
        return JSONResponse(status_code=404, content={"reason": str(exc)})

    @app.exception_handler(ReviewConflict)
    async def conflict(_request, exc):
        return JSONResponse(status_code=409, content={"reason": str(exc)})

    return app


app = create_app(use_fixtures=os.environ.get("USE_FIXTURES", "false").lower() == "true")
