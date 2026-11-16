"""File service: limits layering, the upload flow against a fake storage,
image compression on real images, and file answers on submissions."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image

from common.services import images
from common.services import storage as storage_mod
from common.services.images import ImagePolicy
from common.services.storage.base import ObjectInfo, StorageProvider, UploadTarget
from config import FilesEnv
from modules.files import repository as files_repo
from modules.files import service as files
from modules.files.model import FileLimit, StoredFile
from modules.files.purposes import MB, intersect_types, type_allowed
from modules.forms import repository as forms_repo
from tests.conftest import employee_token, make_form


# --- fakes ---------------------------------------------------------------------

class FakeStorage(StorageProvider):
    name = "s3"

    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []

    def signed_upload(self, key, *, content_type, size, expires_in):
        from datetime import datetime, timezone

        return UploadTarget("PUT", f"https://storage.test/{key}?sig=1", datetime.now(timezone.utc),
                            headers={"Content-Type": content_type})

    def signed_link(self, key, *, download_name, content_type, expires_in, inline=False):
        return f"https://storage.test/{key}?download={download_name}&inline={inline}"

    def head(self, key, *, content_type=""):
        if key not in self.objects:
            return None
        data, ctype = self.objects[key]
        return ObjectInfo(len(data), ctype, "etag")

    def delete(self, key, *, content_type=""):
        self.deleted.append(key)
        self.objects.pop(key, None)

    def put_bytes(self, key, data, *, content_type):
        self.objects[key] = (data, content_type)
        return ObjectInfo(len(data), content_type, "etag")

    def get_bytes(self, key, *, max_bytes, content_type=""):
        return self.objects[key][0]


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(FilesEnv, "STORAGE_PROVIDER", "s3")
    storage_mod.set_storage_for_tests("s3", fake)
    yield fake
    storage_mod.reset_storage_for_tests()


@pytest.fixture
def store(monkeypatch):
    """An in-memory files table and limits table."""
    rows: dict[int, StoredFile] = {}
    limits: list[FileLimit] = []

    def add_file(db, file):
        from datetime import datetime, timezone

        file.id = file.id or (max(rows, default=0) + 1)
        file.created_at = file.created_at or datetime.now(timezone.utc)  # the database's default
        rows[file.id] = file
        db.add(file)
        return file

    monkeypatch.setattr(files_repo, "add_file", add_file)
    monkeypatch.setattr(files_repo, "get_file", lambda db, fid, for_update=False: rows.get(fid))
    monkeypatch.setattr(
        files_repo, "limits_for",
        lambda db, organisation_id, purpose: (
            next((l for l in limits if l.purpose == purpose and l.organisation_id is None), None),
            next((l for l in limits if l.purpose == purpose and l.organisation_id == organisation_id), None),
        ),
    )
    monkeypatch.setattr(files_repo, "attached_files", lambda db, t, ids: [
        f for f in rows.values() if f.attached_type == t and f.attached_id in ids and f.status != "deleted"])
    return SimpleNamespace(rows=rows, limits=limits)


@pytest.fixture
def file_form(monkeypatch):
    form = make_form(type="questionnaire", organisation_id=1)
    form.fields[0].type = "file"
    form.fields[0].options = []
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == form.id else None)
    return form


def employee(id=1, org=1, **kw):
    from modules.auth.dto import EmployeePrincipal

    return EmployeePrincipal(id=id, jti="j", organisation_id=org, **kw)


def jpeg_bytes(w=4000, h=3000, gps=True) -> bytes:
    img = Image.new("RGB", (w, h), (120, 160, 200))
    for x in range(0, w, 50):  # some detail so it doesn't compress to nothing
        img.paste((x % 255, 80, 40), (x, 0, x + 10, h))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotated 90 degrees, like a phone held upright
    if gps:
        exif[0x8825] = {1: "N", 2: (30.0, 2.0, 40.0)}
    out = BytesIO()
    img.save(out, "JPEG", quality=95, exif=exif)
    return out.getvalue()


# --- limits ----------------------------------------------------------------------

def test_type_matching_and_blocked_types():
    assert type_allowed("image/png", ("image/*",))
    assert not type_allowed("image/svg+xml", ("image/*",))  # scripts in SVG: always blocked
    assert not type_allowed("text/html", ("*/*",))
    assert intersect_types(("image/*", "application/pdf"), ("image/png", "text/plain")) == ("image/png",)


def test_question_options_parse():
    q = files.parse_question_limits(["max_mb=2", "types=application/pdf,image/*", "keep_original=true",
                                     "image.quality=85", "image.format=jpeg", "garbage", "max_mb=oops"])
    assert q["max_bytes"] == 2 * MB
    assert q["allowed_types"] == ("application/pdf", "image/*")
    assert q["image"] == {"keep_original": True, "quality": 85, "format": "jpeg"}


def test_limits_layer_platform_then_org_then_question(store, monkeypatch):
    db = None
    base = files.effective_limits(db, organisation_id=1, purpose="form_answer")
    assert base.max_bytes == 10 * MB and base.image.max_side == 1600

    store.limits.append(FileLimit(organisation_id=None, purpose="form_answer", max_bytes=30 * MB,
                                  allowed_types=["image/*", "application/pdf"], image={"quality": 70}))
    store.limits.append(FileLimit(organisation_id=1, purpose="form_answer", max_bytes=20 * MB,
                                  allowed_types=["image/png", "application/pdf", "video/mp4"]))
    lim = files.effective_limits(db, organisation_id=1, purpose="form_answer",
                                 question_options=["max_mb=5", "types=application/pdf", "image.max_side=800"])
    assert lim.max_bytes == 5 * MB
    assert lim.allowed_types == ("application/pdf",)  # video/mp4 never allowed by the platform
    assert (lim.image.quality, lim.image.max_side) == (70, 800)

    other_org = files.effective_limits(db, organisation_id=2, purpose="form_answer")
    assert other_org.max_bytes == 30 * MB  # the platform raised it; org 1's tightening doesn't apply


def test_hard_cap_wins(store, monkeypatch):
    monkeypatch.setattr(FilesEnv, "FILES_HARD_MAX_MB", 8)
    store.limits.append(FileLimit(organisation_id=None, purpose="form_answer", max_bytes=40 * MB))
    assert files.effective_limits(None, organisation_id=1, purpose="form_answer").max_bytes == 8 * MB


def test_only_admins_set_limits(db):
    with pytest.raises(HTTPException) as e:
        files.set_limit(db, actor=employee(), purpose="form_answer", organisation_id=None, payload={})
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        files.set_limit(db, actor=employee(is_admin=True), purpose="form_answer", organisation_id=2, payload={})
    assert e.value.status_code == 403  # another organisation


# --- upload flow ---------------------------------------------------------------

def test_upload_complete_flow(db, store, storage, file_form):
    actor = employee()
    start = files.add(db, actor=actor, purpose="form_answer", name="../../report.pdf",
                      content_type="application/pdf", size=1000, form_id=file_form.id, field_id=file_form.fields[0].id)
    f = start.file
    assert f.status == "pending" and "/" not in f.name and f.name.endswith("report.pdf")
    assert f.key.startswith("org/1/form_answer/") and "report" not in f.key
    assert start.target.url.startswith("https://storage.test/")

    with pytest.raises(HTTPException) as e:  # nothing uploaded yet
        files.complete(db, file_id=f.id, actor=actor)
    assert e.value.status_code == 409

    storage.objects[f.key] = (b"%PDF" + b"x" * 996, "application/pdf")
    done = files.complete(db, file_id=f.id, actor=actor)
    assert done.status == "ready" and done.size == 1000 and done.processing == "none"
    events = [o for o in db.added if type(o).__name__ == "OutboxEvent"]
    assert [e.event_type for e in events] == ["file.uploaded"]

    url, _ = files.link(db, file_id=f.id, actor=actor)
    assert f"download={f.name}" in url and "inline=False" in url


def test_upload_limits_are_checked_before_and_after(db, store, storage, file_form):
    actor = employee()
    file_form.fields[0].options = ["max_mb=1"]
    kw = dict(actor=actor, purpose="form_answer", form_id=file_form.id, field_id=file_form.fields[0].id)
    with pytest.raises(HTTPException) as e:
        files.add(db, name="big.pdf", content_type="application/pdf", size=2 * MB, **kw)
    assert e.value.status_code == 413
    with pytest.raises(HTTPException) as e:
        files.add(db, name="x.svg", content_type="image/svg+xml", size=10, **kw)
    assert e.value.status_code == 415

    # declared small, uploaded big: refused at complete, and deleted
    f = files.add(db, name="a.pdf", content_type="application/pdf", size=100, **kw).file
    storage.objects[f.key] = (b"x" * (2 * MB), "application/pdf")
    with pytest.raises(HTTPException) as e:
        files.complete(db, file_id=f.id, actor=actor)
    assert e.value.status_code == 413
    assert f.status == "deleted"


def test_someone_else_cannot_complete_or_see(db, store, storage, file_form):
    f = files.add(db, actor=employee(id=1), purpose="form_answer", name="a.pdf", content_type="application/pdf",
                  size=10, form_id=file_form.id, field_id=file_form.fields[0].id).file
    storage.objects[f.key] = (b"x" * 10, "application/pdf")
    for actor in (employee(id=2), employee(id=1, org=2)):
        with pytest.raises(HTTPException) as e:
            files.complete(db, file_id=f.id, actor=actor)
        assert e.value.status_code == 404


def test_logo_needs_org_admin(db, store, storage):
    with pytest.raises(HTTPException) as e:
        files.add(db, actor=employee(), purpose="org_logo", name="l.png", content_type="image/png", size=10)
    assert e.value.status_code == 403
    start = files.add(db, actor=employee(is_admin=True), purpose="org_logo", name="l.png", content_type="image/png", size=10)
    assert start.file.purpose == "org_logo"


def test_replace_keeps_the_id_and_trashes_old_bytes(db, store, storage, file_form):
    actor = employee()
    kw = dict(form_id=file_form.id, field_id=file_form.fields[0].id)
    f = files.add(db, actor=actor, purpose="form_answer", name="v1.pdf", content_type="application/pdf", size=10, **kw).file
    storage.objects[f.key] = (b"x" * 10, "application/pdf")
    files.complete(db, file_id=f.id, actor=actor)
    old_key = f.key

    start = files.update(db, file_id=f.id, actor=actor, name="v2.pdf", content_type="application/pdf", size=20)
    assert f.key == old_key and f.replacement  # the old content still works meanwhile
    storage.objects[f.replacement["key"]] = (b"y" * 20, "application/pdf")
    files.complete(db, file_id=f.id, actor=actor)
    assert (f.id, f.name, f.size) == (start.file.id, "v2.pdf", 20) and f.key != old_key
    trash = [r for r in store.rows.values() if r.status == "deleted"]
    assert [t.key for t in trash] == [old_key]  # removed by the cleanup job


def test_public_upload_needs_its_token(db, store, storage, file_form):
    actor = files.PublicActor(form_id=file_form.id)
    start = files.add(db, actor=actor, purpose="form_answer", name="cv.pdf", content_type="application/pdf",
                      size=10, field_id=file_form.fields[0].id)
    assert start.file_token and start.file.owner_token_hash != start.file_token
    storage.objects[start.file.key] = (b"x" * 10, "application/pdf")
    with pytest.raises(HTTPException):
        files.complete(db, file_id=start.file.id, actor=files.PublicActor(form_id=file_form.id, token="wrong" * 4))
    done = files.complete(db, file_id=start.file.id, actor=files.PublicActor(form_id=file_form.id, token=start.file_token))
    assert done.status == "ready"


def test_answer_file_must_match_form_field_and_owner(db, store, storage, file_form):
    actor = employee()
    field = file_form.fields[0]
    f = files.add(db, actor=actor, purpose="form_answer", name="a.pdf", content_type="application/pdf",
                  size=10, form_id=file_form.id, field_id=field.id).file
    storage.objects[f.key] = (b"x" * 10, "application/pdf")
    files.complete(db, file_id=f.id, actor=actor)

    kw = dict(form_id=file_form.id, organisation_id=1, value={"file_id": f.id}, submission_id=5)
    _, stored = files.resolve_answer_file(db, field_id=field.id, actor=actor, **kw)
    assert stored == {"file_id": f.id, "name": "a.pdf", "content_type": "application/pdf", "size": 10}
    for bad in (dict(field_id=field.id + 1, actor=actor), dict(field_id=field.id, actor=employee(id=9))):
        with pytest.raises(HTTPException) as e:
            files.resolve_answer_file(db, **kw, **bad)
        assert e.value.status_code == 422

    f.attached_type, f.attached_id = "submission", 6  # used by another submission
    with pytest.raises(HTTPException):
        files.resolve_answer_file(db, field_id=field.id, actor=actor, **kw)


# --- images --------------------------------------------------------------------

def test_photo_is_shrunk_rotated_and_stripped():
    original = jpeg_bytes()
    out = images.compress(original, ImagePolicy(max_side=1600, quality=80, format="webp"))
    assert out and out.content_type == "image/webp"
    assert len(out.data) < len(original) / 5
    assert (out.width, out.height) == (1200, 1600)  # EXIF said rotated: portrait now
    img = Image.open(BytesIO(out.data))
    assert not img.getexif() and "exif" not in img.info  # GPS gone


def test_small_clean_image_is_never_made_bigger():
    out = BytesIO()
    Image.new("RGB", (200, 200), (10, 20, 30)).save(out, "PNG", optimize=True)
    data = out.getvalue()
    result = images.compress(data, ImagePolicy(format="keep"))
    assert result is None or len(result.data) < len(data)


def test_keep_original_and_animated_are_skipped():
    assert images.compress(jpeg_bytes(), ImagePolicy(keep_original=True)) is None
    frames = [Image.new("RGB", (50, 50), c) for c in ((255, 0, 0), (0, 255, 0))]
    out = BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:])
    assert images.compress(out.getvalue(), ImagePolicy()) is None


def test_thumbnail_and_unreadable():
    thumb = images.thumbnail(jpeg_bytes(), 320)
    assert max(thumb.width, thumb.height) == 320 and thumb.content_type == "image/webp"
    with pytest.raises(images.ImageError):
        images.compress(b"not an image", ImagePolicy())


def test_server_side_processing_replaces_and_trashes(db, store, storage, file_form):
    actor = employee()
    f = files.add(db, actor=actor, purpose="form_answer", name="photo.jpg", content_type="image/jpeg",
                  size=1, form_id=file_form.id, field_id=file_form.fields[0].id).file
    storage.objects[f.key] = (jpeg_bytes(), "image/jpeg")
    files.complete(db, file_id=f.id, actor=actor)
    assert f.processing == "pending"
    original_key = f.key

    assert files.process_image(db, f.id) == "compressed"
    assert f.name == "photo.webp" and f.content_type == "image/webp" and f.key.endswith("-c.webp")
    assert f.variants["thumb"]["key"].endswith("-t.webp")
    assert any(r.key == original_key and r.status == "deleted" for r in store.rows.values())
    assert files.process_image(db, f.id) == "nothing to do"  # runs once


# --- through the API -------------------------------------------------------------

def test_upload_endpoint_and_limits_endpoint(client, store, storage, file_form):
    res = client.post("/files/uploads", headers=employee_token(id=1, organisation_id=1), json={
        "purpose": "form_answer", "name": "a.pdf", "content_type": "application/pdf",
        "size": 10, "form_id": file_form.id, "field_id": file_form.fields[0].id})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["upload"]["method"] == "PUT" and body["image"]["max_side"] == 1600

    res = client.get("/files/limits/form_answer", headers=employee_token(id=1, organisation_id=1))
    assert res.status_code == 200 and res.json()["max_mb"] == 10
