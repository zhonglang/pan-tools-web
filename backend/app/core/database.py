from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        return create_engine(database_url, connect_args=connect_args)
    # Remote Postgres (or NAT/firewall) often drops idle sockets; without pre_ping the
    # pool hands out dead connections → "could not receive data / Can't assign requested address".
    connect_args.update(
        {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }
    )
    return create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
