from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import Organisation


def get_organisation(db: Session, org_id: int) -> Optional[Organisation]:
    return db.get(Organisation, org_id)


def get_organisation_by_external_id(db: Session, external_id: str) -> Optional[Organisation]:
    return db.execute(
        select(Organisation).where(Organisation.external_id == external_id)
    ).scalar_one_or_none()


def list_organisations(db: Session, *, limit: int = 100, offset: int = 0) -> list[Organisation]:
    stmt = select(Organisation).order_by(Organisation.name).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_organisations(db: Session) -> int:
    return db.execute(select(func.count()).select_from(Organisation)).scalar_one()


def create_organisation(
    db: Session,
    *,
    name: str,
    logo: Optional[str] = None,
    industry: Optional[str] = None,
    contact_info: Optional[str] = None,
    subscription_end: Optional[date] = None,
    subscription_plan_id: Optional[int] = None,
    external_id: Optional[str] = None,
) -> Organisation:
    org = Organisation(
        name=name,
        logo=logo,
        industry=industry,
        contact_info=contact_info,
        subscription_end=subscription_end,
        subscription_plan_id=subscription_plan_id,
        external_id=external_id,
    )
    db.add(org)
    db.flush()
    return org


def update_organisation(db: Session, org: Organisation, *, data: dict) -> Organisation:
    for key, value in data.items():
        setattr(org, key, value)
    db.flush()
    return org


def delete_organisation(db: Session, org: Organisation) -> None:
    db.delete(org)
