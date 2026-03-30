"""Enumerate files from Google Drive via folder traversal or query."""

# Standard library imports
from collections import deque

# Third party imports
from googleapiclient.errors import HttpError

# Local imports
from gdrive.constants import FOLDER_MIME_TYPE
from gdrive.constants import LIST_FIELDS
from gdrive.constants import PAGE_SIZE
from gdrive.constants import STATUS_PENDING
from gdrive.models import DriveFile
from gdrive.types import JSONDict
from gdrive.types import JSONList


def _list_page(service: object, query: str, page_token: str) -> tuple[JSONList, str]:
    """Fetch one page of files.list() results.

    Returns (items, next_page_token). next_page_token is empty string when done.
    """
    params: JSONDict = {
        "q": query,
        "fields": LIST_FIELDS,
        "pageSize": PAGE_SIZE,
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
    }
    if page_token:
        params["pageToken"] = page_token

    result: JSONDict = service.files().list(**params).execute()  # type: ignore[attr-defined]
    items: JSONList = result.get("files", [])  # type: ignore[assignment]
    next_token: str = str(result.get("nextPageToken", ""))
    return items, next_token


def enumerate_query(service: object, q: str) -> list[DriveFile]:
    """Return all files matching a Drive API query string."""
    files: list[DriveFile] = []
    page_token = ""
    while True:
        items, page_token = _list_page(service, q, page_token)
        for item in items:
            assert isinstance(item, dict)
            if str(item.get("mimeType", "")) != FOLDER_MIME_TYPE:
                files.append(DriveFile.from_api_item(item))
        if not page_token:
            break
    return files


def enumerate_folder(
    service: object, folder_id: str, recursive: bool, parent_path: str = ""
) -> list[DriveFile]:
    """Return all non-folder files under folder_id using BFS traversal."""
    files: list[DriveFile] = []
    queue: deque[tuple[str, str]] = deque([(folder_id, parent_path)])

    while queue:
        current_id, current_path = queue.popleft()
        query = f"'{current_id}' in parents and trashed=false"
        page_token = ""

        while True:
            items, page_token = _list_page(service, query, page_token)
            for item in items:
                assert isinstance(item, dict)
                mime = str(item.get("mimeType", ""))
                if mime == FOLDER_MIME_TYPE:
                    if recursive:
                        child_path = (
                            f"{current_path}/{item['name']}" if current_path else str(item["name"])
                        )
                        queue.append((str(item["id"]), child_path))
                else:
                    files.append(DriveFile.from_api_item(item, current_path))
            if not page_token:
                break

    return files


def fetch_metadata(service: object, files: list[DriveFile]) -> None:
    """Populate size and md5_checksum for binary pending files missing them.

    Workspace files are skipped — Drive does not provide size or checksums for them.
    """
    missing = [
        f for f in files if f.status == STATUS_PENDING and not f.is_workspace_file and f.size == 0
    ]
    if not missing:
        return

    print(f"Fetching metadata for {len(missing)} files...")
    for i, f in enumerate(missing):
        try:
            meta: JSONDict = (
                service.files()  # type: ignore[attr-defined]
                .get(fileId=f.id, fields="size,md5Checksum", supportsAllDrives=True)
                .execute()
            )
            f.size = int(meta.get("size", 0))
            f.md5_checksum = str(meta.get("md5Checksum", ""))
        except HttpError:
            pass
        if (i + 1) % 20 == 0 or (i + 1) == len(missing):
            print(f"  {i + 1}/{len(missing)}")
