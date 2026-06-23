"""
storage.py — thin wrapper around Supabase Storage REST API.

All admin/guest uploads (photos, QR, feedback media) live in a single
public bucket named SUPABASE_BUCKET. The DB stores only the object key
(e.g. "qr_173_xyz.png"); the public URL is built on read via public_url().

We talk to the REST API directly rather than pulling in supabase-py:
fewer deps, transparent error handling, and we only need 3 verbs.

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to be set in env.
The service role key is required because admin uploads write to the
bucket; the anon key only has read access.
"""
import mimetypes
import requests

import config


def _api_base() -> str:
    return f"{config.SUPABASE_URL.rstrip('/')}/storage/v1"


def _headers(content_type: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}"}
    if content_type:
        h["Content-Type"] = content_type
    return h


def upload(filename: str, file_storage) -> None:
    """Upload a Werkzeug FileStorage to the bucket. Overwrites if it already exists."""
    file_storage.stream.seek(0)
    body = file_storage.stream.read()
    ctype = file_storage.mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    url = f"{_api_base()}/object/{config.SUPABASE_BUCKET}/{filename}"
    r = requests.post(
        url,
        data=body,
        headers={**_headers(ctype), "x-upsert": "true"},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase Storage upload failed {r.status_code}: {r.text}")


def delete(filename: str) -> None:
    """Best-effort delete. Swallows errors so a missing object doesn't break the admin flow."""
    if not filename:
        return
    url = f"{_api_base()}/object/{config.SUPABASE_BUCKET}/{filename}"
    try:
        requests.delete(url, headers=_headers(), timeout=15)
    except requests.RequestException as e:
        print(f"[storage] delete failed for {filename}: {e}")


def public_url(filename: str) -> str:
    """Build the public CDN URL. Bucket must be marked Public in Supabase dashboard."""
    if not filename:
        return ""
    return f"{config.SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{config.SUPABASE_BUCKET}/{filename}"
