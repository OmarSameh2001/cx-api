import code

import click
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

import models  # noqa: F401  registers all models on Base.metadata
from db import Base
from db import SessionLocal, engine
from modules.auth.service import hash_password
from modules.customers.model import Customer
from modules.employees.model import Employee
from modules.organisations.model import Organisation
from modules.roles.service import seed_default_roles
from modules.subscriptions.model import SubscriptionPlan
from modules.units.model import Unit


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


@cli.command("db:seed")
def db_seed():
    """Seed dummy data for local login (organisation, units, roles, employees, customer)."""
    db = SessionLocal()
    try:
        plan = db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.name == "Pro")
        ).scalar_one_or_none()
        if plan is None:
            plan = SubscriptionPlan(name="Pro", benefits="All features included")
            db.add(plan)
            db.flush()

        org = db.execute(
            select(Organisation).where(Organisation.name == "Acme Corp")
        ).scalar_one_or_none()
        if org is None:
            org = Organisation(
                name="Acme Corp",
                industry="Technology",
                contact_info="contact@acme.com",
                subscription_plan_id=plan.id,
            )
            db.add(org)
            db.flush()

        def upsert_unit(name, type_, parent_id=None):
            existing = db.execute(
                select(Unit).where(Unit.organisation_id == org.id, Unit.name == name)
            ).scalar_one_or_none()
            if existing:
                return existing
            unit = Unit(
                name=name,
                type=type_,
                organisation_id=org.id,
                parent_unit_id=parent_id,
                is_active=True,
            )
            db.add(unit)
            db.flush()
            return unit

        hq = upsert_unit("Headquarters", "company")
        engineering = upsert_unit("Engineering", "department", hq.id)
        sales = upsert_unit("Sales", "department", hq.id)
        upsert_unit("Backend Team", "team", engineering.id)
        upsert_unit("Frontend Team", "team", engineering.id)

        # Same default roles every new organisation gets (modules/roles/permissions.py).
        roles = {r.name: r for r in seed_default_roles(db, organisation_id=org.id)}
        admin_role, manager_role, agent_role = roles["admin"], roles["manager"], roles["agent"]

        def upsert_employee(
            *, email, username, first, last, role, unit, manager_id=None, platform_admin=False
        ):
            existing = db.execute(
                select(Employee).where(Employee.email == email)
            ).scalar_one_or_none()
            if existing:
                return existing
            employee = Employee(
                first_name=first,
                last_name=last,
                username=username,
                email=email,
                password=hash_password("Password123!"),
                is_active=True,
                is_platform_admin=platform_admin,
                organisation_id=org.id,
                unit_id=unit.id if unit else None,
                role_id=role.id,
                manager_id=manager_id,
            )
            db.add(employee)
            db.flush()
            return employee

        admin = upsert_employee(
            email="admin@acme.com",
            username="admin",
            first="Ada",
            last="Admin",
            role=admin_role,
            unit=hq,
        )
        manager = upsert_employee(
            email="manager@acme.com",
            username="manager",
            first="Mike",
            last="Manager",
            role=manager_role,
            unit=engineering,
            manager_id=admin.id,
        )
        upsert_employee(
            email="agent@acme.com",
            username="agent",
            first="Alice",
            last="Agent",
            role=agent_role,
            unit=engineering,
            manager_id=manager.id,
        )
        upsert_employee(
            email="sales@acme.com",
            username="sales",
            first="Sam",
            last="Sales",
            role=agent_role,
            unit=sales,
            manager_id=admin.id,
        )
        # Platform admin: runs organisations and tenants. Also Acme's org admin
        # so the app has something to show them.
        upsert_employee(
            email="platform@acme.com",
            username="platform",
            first="Pat",
            last="Platform",
            role=admin_role,
            unit=hq,
            platform_admin=True,
        )

        customer = db.execute(
            select(Customer).where(Customer.email == "customer@acme.com")
        ).scalar_one_or_none()
        if customer is None:
            db.add(
                Customer(
                    first_name="Carl",
                    last_name="Customer",
                    email="customer@acme.com",
                    phone="+10000000000",
                    is_auth=True,
                    password=hash_password("Password123!"),
                )
            )

        db.commit()

        click.echo("Seed complete. Login credentials (password = Password123!):")
        click.echo("  Employees:")
        click.echo("    admin@acme.com    (admin)")
        click.echo("    manager@acme.com  (manager)")
        click.echo("    agent@acme.com    (agent)")
        click.echo("    sales@acme.com    (agent)")
        click.echo("    platform@acme.com (admin + platform admin)")
        click.echo("  Customer:")
        click.echo("    customer@acme.com")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@cli.command("platform-admin")
@click.argument("email")
@click.option("--revoke", is_flag=True, help="Remove the flag instead of granting it.")
def platform_admin(email: str, revoke: bool):
    """Grant (or --revoke) platform admin to an employee by email.

    Deliberately CLI-only: no API endpoint sets this flag. The employee must
    log in again for the change to reach their token.
    """
    db = SessionLocal()
    try:
        employee = db.execute(
            select(Employee).where(Employee.email == email)
        ).scalar_one_or_none()
        if employee is None:
            raise click.ClickException(f"No employee with email {email}")
        employee.is_platform_admin = not revoke
        db.commit()
        click.echo(f"{email}: is_platform_admin = {employee.is_platform_admin}")
    finally:
        db.close()


@cli.command("shell")
def shell():
    """Open a Python REPL with `db` session and models loaded."""
    namespace = {"db": SessionLocal(), "engine": engine, "Base": Base, "models": models}
    code.interact(banner="cx-api shell — `db`, `engine`, `Base`, `models` available.", local=namespace)


if __name__ == "__main__":
    cli()
