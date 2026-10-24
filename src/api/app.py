"""Fixture API application. CORS is open to the Vite dev server only."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.router import router


def create_app(*, api_prefix: str = "") -> FastAPI:
    """Build the fixture API.

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
    app.include_router(router, prefix=api_prefix)
    return app


app = create_app()
