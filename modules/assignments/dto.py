from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AssignmentBase(BaseModel):
    user_id: int
    unit_id: int
    description: Optional[str] = None


class AssignmentCreate(AssignmentBase):
    pass


class AssignmentUpdate(BaseModel):
    user_id: Optional[int] = None
    unit_id: Optional[int] = None
    description: Optional[str] = None


class AssignmentRead(AssignmentBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    assigned_at: datetime
    assigned_by: Optional[int]
