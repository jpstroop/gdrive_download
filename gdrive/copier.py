"""Server-side Google Drive file copy using the Drive files.copy API."""

# Standard library imports
from datetime import datetime
from datetime import timezone
from time import sleep

# Third party imports
from googleapiclient.errors import HttpError

# Local imports
from gdrive.constants import DEFAULT_RETRIES
from gdrive.constants import FOLDER_MIME_TYPE
from gdrive.constants import RETRY_BACKOFF_BASE
from gdrive.constants import STATUS_SKIPPED
from gdrive.models import DriveFile
from gdrive.types import JSONDict


def _ensure_folder(service: object, parent_id: str, folder_name: str, cache: dict[str, str]) -> str:
    """Return the Drive folder ID for folder_name under parent_id, creating it if absent.

    Uses cache keyed by '{parent_id}/{folder_name}' to avoid redundant API calls within
    a run. On cache miss, queries Drive before creating to prevent duplicate folders
    across runs (e.g. when resuming after a crash).
    """
    cache_key = f"{parent_id}/{folder_name}"
    if cache_key in cache:
        return cache[cache_key]

    escaped = folder_name.replace("'", "\\'")
    query = (
        f"name='{escaped}' and '{parent_id}' in parents "
        f"and mimeType='{FOLDER_MIME_TYPE}' and trashed=false"
    )
    result: JSONDict = (
        service.files()  # type: ignore[attr-defined]
        .list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True)
        .execute()
    )
    existing = result.get("files", [])
    assert isinstance(existing, list)
    if existing:
        folder_id = str(existing[0]["id"])  # type: ignore[index]
    else:
        body: JSONDict = {"name": folder_name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]}
        created: JSONDict = (
            service.files()  # type: ignore[attr-defined]
            .create(body=body, fields="id", supportsAllDrives=True)
            .execute()
        )
        folder_id = str(created["id"])

    cache[cache_key] = folder_id
    return folder_id


def copy_file(
    service: object,
    f: DriveFile,
    dest_folder_id: str,
    folder_cache: dict[str, str],
    retries: int = DEFAULT_RETRIES,
) -> bool:
    """Copy a single Drive file server-side to dest_folder_id, preserving relative_path.

    Returns True on success, False on failure. On success sets f.drive_copy_id and
    f.copied_at. On failure sets f.failure_reason. All file types copy in native format —
    Docs, Sheets, Slides, Forms, Scripts, Shortcuts, etc. are all supported by files.copy.
    Folders are the only skipped type; they are created structurally via _ensure_folder.
    The folder_cache is shared across calls to avoid redundant folder creation API calls.
    """
    if f.drive_mime_type == FOLDER_MIME_TYPE:
        f.status = STATUS_SKIPPED
        f.failure_reason = "folders are created structurally, not copied directly"
        return False

    # Walk relative_path segments to resolve (or create) the destination folder
    target_parent_id = dest_folder_id
    if f.relative_path:
        for segment in f.relative_path.split("/"):
            if segment:
                target_parent_id = _ensure_folder(service, target_parent_id, segment, folder_cache)

    body: JSONDict = {"name": f.name, "parents": [target_parent_id]}

    for attempt in range(retries + 1):
        try:
            result: JSONDict = (
                service.files()  # type: ignore[attr-defined]
                .copy(fileId=f.id, body=body, fields="id", supportsAllDrives=True)
                .execute()
            )
            f.drive_copy_id = str(result["id"])
            f.copied_at = datetime.now(timezone.utc).isoformat()
            f.failure_reason = ""
            return True
        except HttpError as e:
            if attempt == retries:
                f.failure_reason = f"failed after {retries + 1} attempt(s): {e}"
                return False
            wait = RETRY_BACKOFF_BASE ** (attempt + 1)
            print(f"  copy error ({e}), retrying in {wait}s...")
            sleep(wait)

    return False  # unreachable; satisfies type checker
