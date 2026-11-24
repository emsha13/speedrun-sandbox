from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.db import engine
from app.routers import account, auth
from app.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start without a database rather than fail at the first request.
    async with engine.connect() as connection:
        await connection.execute(text('SELECT 1'))
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    app.include_router(auth.router)
    app.include_router(account.router)
    return app


app = create_app()
