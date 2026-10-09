import os
import sys
from pathlib import Path

if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parent.parent
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.services.bootstrap import ensure_admin
from app.core.config import get_settings
from app.core.database import Base, make_engine, make_session_factory
from app.services.downloads import interrupt_orphans
from app.api.routes import accounts, admin, auth, shares, stats, transfers


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine(app.state.settings.database_url)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    if app.state.settings.auto_create_tables:
        Base.metadata.create_all(engine)
    with app.state.session_factory() as session:
        ensure_admin(session, app.state.settings)
        interrupt_orphans(session)
    yield
    client = getattr(app.state, "pan_http_client", None)
    if client is not None:
        client.close()
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(accounts.router)
    app.include_router(transfers.router)
    app.include_router(shares.router)
    app.include_router(stats.router)
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=8010,
        reload=True,
    )
