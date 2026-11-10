"""Private photo storage. Every upload is re-encoded (strips GPS/EXIF metadata, removes any hidden payload).

CIVICFIX_STORAGE=local     -> files in CIVICFIX_UPLOADS (default ./instance/uploads)   [development]
CIVICFIX_STORAGE=supabase  -> private Supabase Storage bucket via SUPABASE_URL + SUPABASE_SERVICE_KEY [production]
Photos are never public: the app serves them through /media/<name> after a permission check.
"""
import io
import os
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 40_000_000
BASE = Path(__file__).resolve().parent
BACKEND = os.environ.get("CIVICFIX_STORAGE", "local").lower()
LOCAL_DIR = Path(os.environ.get("CIVICFIX_UPLOADS", BASE / "instance" / "uploads"))
LEGACY_DIR = BASE / "static" / "uploads"          # photos from the first version
NAME_RE = re.compile(r"^[a-f0-9]{24}\.(jpg|png|webp)$")


def clean_image(stream):
    """Validate + re-encode as a resized JPEG. Raises ValueError for anything that isn't a real image."""
    try:
        probe = Image.open(stream)
        probe.verify()
        stream.seek(0)
        img = ImageOps.exif_transpose(Image.open(stream)).convert("RGB")
    except Exception:
        raise ValueError("That file isn't a valid image. Upload a JPG, PNG or WEBP photo.")
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)      # re-encoding drops EXIF/GPS metadata
    return out.getvalue()


def _supabase(path, method, data=None):
    base, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    bucket = os.environ.get("SUPABASE_BUCKET", "civicfix-media")
    headers = {"apikey": key, "Content-Type": "image/jpeg"}
    if key.startswith("eyJ"):                           # legacy JWT-style keys also go in Authorization
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(f"{base}/storage/v1/object/{bucket}/{path}", data=data, method=method, headers=headers)
    return urllib.request.urlopen(req, timeout=20)


def save_upload(file):
    """Store an uploaded FileStorage; returns the stored name or None when no file was chosen."""
    if not file or not file.filename:
        return None
    data = clean_image(file.stream)
    name = secrets.token_hex(12) + ".jpg"
    if BACKEND == "supabase":
        _supabase(name, "POST", data).read()
    else:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        (LOCAL_DIR / name).write_bytes(data)
    return name


def load(name):
    """Return (bytes, content_type) or None."""
    if not NAME_RE.match(name or ""):
        return None
    ctype = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[name.rsplit(".", 1)[1]]
    try:
        if BACKEND == "supabase":
            return _supabase(name, "GET").read(), ctype
        for d in (LOCAL_DIR, LEGACY_DIR):
            p = d / name
            if p.is_file():
                return p.read_bytes(), ctype
    except (urllib.error.URLError, OSError):
        return None
    return None
