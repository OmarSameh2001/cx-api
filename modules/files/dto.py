from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from common.services.images import OutputFormat

PurposeName = Literal["form_answer", "org_logo"]


class UploadRequest(BaseModel):
    purpose: PurposeName
    name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=3, max_length=127)
    size: int = Field(gt=0)
    # form answers: the question the file answers
    form_id: Optional[int] = None
    field_id: Optional[int] = None
    # org_logo: platform admins may upload another organisation's logo
    organisation_id: Optional[int] = None


class PublicUploadRequest(BaseModel):
    field_id: int
    name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=3, max_length=127)
    size: int = Field(gt=0)


class ReplaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=3, max_length=127)
    size: int = Field(gt=0)


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class PublicCompleteRequest(BaseModel):
    file_token: str = Field(min_length=16, max_length=128)


class UploadTargetRead(BaseModel):
    method: Literal["PUT", "POST"]
    url: str
    headers: dict[str, str] = {}
    fields: dict[str, str] = {}
    expires_at: datetime


class FileVariantRead(BaseModel):
    content_type: str
    size: int
    width: Optional[int] = None
    height: Optional[int] = None


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    purpose: str
    name: str
    content_type: str
    size: int
    status: str
    width: Optional[int] = None
    height: Optional[int] = None
    processing: str
    has_thumbnail: bool = False
    attached_type: Optional[str] = None
    attached_id: Optional[int] = None
    form_id: Optional[int] = None
    field_id: Optional[int] = None
    owner_employee_id: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class UploadStartResponse(BaseModel):
    file: FileRead
    upload: UploadTargetRead
    # what the browser should do to images before uploading (WhatsApp style)
    image: Optional["ImagePolicyRead"] = None
    # public uploads only: proves the respondent owns this file; send it back
    # on complete and inside the answer
    file_token: Optional[str] = None


class FileLinkResponse(BaseModel):
    url: str
    expires_at: datetime


# --- limits --------------------------------------------------------------------

class ImagePolicyRead(BaseModel):
    compress: bool
    max_side: int
    quality: int
    format: OutputFormat
    keep_original: bool
    thumb_side: int


class ImagePolicyPatch(BaseModel):
    compress: Optional[bool] = None
    max_side: Optional[int] = Field(default=None, ge=64, le=8000)
    quality: Optional[int] = Field(default=None, ge=30, le=100)
    format: Optional[OutputFormat] = None
    keep_original: Optional[bool] = None
    thumb_side: Optional[int] = Field(default=None, ge=0, le=1024)


class LimitWrite(BaseModel):
    """Unset fields inherit from the layer below."""

    max_mb: Optional[float] = Field(default=None, gt=0)
    allowed_types: Optional[list[str]] = Field(default=None, min_length=1, max_length=64)
    image: Optional[ImagePolicyPatch] = None


class LimitRead(BaseModel):
    purpose: str
    organisation_id: Optional[int]
    max_mb: Optional[float]
    allowed_types: Optional[list[str]]
    image: Optional[dict]
    updated_at: Optional[datetime] = None


class EffectiveLimitsRead(BaseModel):
    purpose: str
    max_bytes: int
    max_mb: float
    allowed_types: list[str]
    image: ImagePolicyRead
    hard_max_mb: float
    platform: Optional[LimitRead] = None
    organisation: Optional[LimitRead] = None


UploadStartResponse.model_rebuild()
