from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import limits
from app.db import engine
from app.deps import Db
from app.routers import account, auth, users
from app.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start without a database rather than fail at the first request.
    async with engine.connect() as connection:
        await connection.execute(text('SELECT 1'))
    yield
    await limits.redis.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(users.router)

    @app.get('/health', tags=['health'])
    async def health(session: Db):
        try:
            await session.execute(text('SELECT 1'))
        except SQLAlchemyError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, 'database is unreachable')
        return {'status': 'ok'}

    return app


app = create_app()
