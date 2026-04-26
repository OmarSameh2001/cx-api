from sqlalchemy import select
from sqlalchemy.orm import Session

from .model import Unit


def get_descendant_unit_ids(db: Session, root_unit_id: int) -> list[int]:
    """Return root_unit_id plus every transitive child unit id."""
    base = (
        select(Unit.id, Unit.parent_unit_id)
        .where(Unit.id == root_unit_id)
        .cte(name="unit_tree", recursive=True)
    )
    tree = base.union_all(
        select(Unit.id, Unit.parent_unit_id).join(base, Unit.parent_unit_id == base.c.id)
    )
    rows = db.execute(select(tree.c.id)).all()
    return [row[0] for row in rows]
