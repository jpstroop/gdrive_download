"""Package-wide constants for the gdrive downloader."""

# Standard library imports
from pathlib import Path

SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

TOKEN_FILE: Path = Path("token.json")
CREDENTIALS_FILE: Path = Path("credentials.json")
DEFAULT_MANIFEST: Path = Path("manifest.json")

DEFAULT_CONNECTIONS: int = 4
DEFAULT_RETRIES: int = 3
RETRY_BACKOFF_BASE: int = 2  # seconds; doubles each attempt: 2s, 4s, 8s

SEQUENTIAL_CHUNK_SIZE: int = 32 * 1024 * 1024  # 32 MB
PARALLEL_CHUNK_SIZE: int = 8 * 1024 * 1024  # 8 MB — stream buffer per thread
DISK_HEADROOM: int = 512 * 1024 * 1024  # 512 MB safety margin

DRIVE_DOWNLOAD_URL: str = (
    "https://www.googleapis.com/drive/v3/files/{file_id}" "?alt=media&supportsAllDrives=true"
)
DRIVE_EXPORT_URL: str = (
    "https://www.googleapis.com/drive/v3/files/{file_id}" "/export?mimeType={mime_type}"
)

FOLDER_MIME_TYPE: str = "application/vnd.google-apps.folder"
WORKSPACE_PREFIX: str = "application/vnd.google-apps."

# Maps Google Workspace MIME types to (export MIME type, file extension)
WORKSPACE_EXPORT_MAP: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
}

# Workspace types that cannot be meaningfully exported — skipped with a warning
WORKSPACE_SKIP_TYPES: set[str] = {
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.script",
    "application/vnd.google-apps.shortcut",
    "application/vnd.google-apps.site",
    "application/vnd.google-apps.map",
    "application/vnd.google-apps.jam",
    "application/vnd.google-apps.folder",
}

STATUS_PENDING: str = "pending"
STATUS_COMPLETED: str = "completed"
STATUS_FAILED: str = "failed"
STATUS_SKIPPED: str = "skipped"

LIST_FIELDS: str = (
    "nextPageToken, files(id, name, mimeType, size, md5Checksum, owners(displayName,emailAddress))"
)
PAGE_SIZE: int = 1000
