from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bootstrap import ensure_admin
from app.config import get_settings
from app.db import Base, make_engine, make_session_factory
from app.routers import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine(app.state.settings.database_url)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    if app.state.settings.auto_create_tables:
        Base.metadata.create_all(engine)
    with app.state.session_factory() as session:
        ensure_admin(session, app.state.settings)
    yield
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.include_router(auth.router)
    return app
