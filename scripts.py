import code

import click
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import text

import models  # noqa: F401  registers all models on Base.metadata
from db import Base
from db import SessionLocal, engine


def _alembic_cfg() -> Config:
    return Config("alembic.ini")


@click.group()
def cli():
    """cx-api management commands."""


@cli.command("dev")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
@click.option("--reload/--no-reload", default=True)
def dev(host: str, port: int, reload: bool):
    """Run the FastAPI dev server."""
    uvicorn.run("main:app", host=host, port=port, reload=reload)


@cli.command("db:ping")
def db_ping():
    """Verify the database connection."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    click.echo(f"OK — connected to {engine.url}")


@cli.command("db:create")
def db_create():
    """Create all tables from SQLAlchemy metadata."""
    Base.metadata.create_all(engine)
    click.echo("Tables created.")


@cli.command("db:drop")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def db_drop(yes: bool):
    """Drop all tables."""
    if not yes:
        click.confirm("Drop ALL tables? This is destructive.", abort=True)
    Base.metadata.drop_all(engine)
    click.echo("Tables dropped.")


@cli.command("db:reset")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def db_reset(yes: bool):
    """Drop and recreate all tables."""
    if not yes:
        click.confirm("Reset database (drop + create)?", abort=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    click.echo("Database reset.")


@cli.command("db:tables")
def db_tables():
    """List tables registered on Base.metadata."""
    for name in sorted(Base.metadata.tables):
        click.echo(name)


@cli.command("db:migrate")
@click.option("-m", "--message", required=True, help="Short description of the change.")
@click.option("--empty", is_flag=True, help="Create an empty revision (no autogenerate).")
def db_migrate(message: str, empty: bool):
    """Generate a new migration from model changes."""
    command.revision(_alembic_cfg(), message=message, autogenerate=not empty)


@cli.command("db:upgrade")
@click.argument("revision", default="head")
def db_upgrade(revision: str):
    """Apply migrations up to REVISION (default: head)."""
    command.upgrade(_alembic_cfg(), revision)


@cli.command("db:downgrade")
@click.argument("revision", default="-1")
def db_downgrade(revision: str):
    """Roll back to REVISION (default: -1, one step back)."""
    command.downgrade(_alembic_cfg(), revision)


@cli.command("db:current")
def db_current():
    """Show the current migration revision in the database."""
    command.current(_alembic_cfg(), verbose=True)


@cli.command("db:history")
def db_history():
    """List all migration revisions."""
    command.history(_alembic_cfg(), verbose=True)


@cli.command("db:stamp")
@click.argument("revision", default="head")
def db_stamp(revision: str):
    """Mark the database as being at REVISION without running migrations."""
    command.stamp(_alembic_cfg(), revision)


@cli.command("shell")
def shell():
    """Open a Python REPL with `db` session and models loaded."""
    namespace = {"db": SessionLocal(), "engine": engine, "Base": Base, "models": models}
    code.interact(banner="cx-api shell — `db`, `engine`, `Base`, `models` available.", local=namespace)


if __name__ == "__main__":
    cli()
