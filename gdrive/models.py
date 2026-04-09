"""Core data models: QuerySpec, DriveFile, Manifest."""

# Standard library imports
from dataclasses import dataclass
from dataclasses import field
import json
from pathlib import Path

# Local imports
from gdrive.constants import STATUS_COMPLETED
from gdrive.constants import STATUS_PENDING
from gdrive.constants import WORKSPACE_EXPORT_MAP
from gdrive.constants import WORKSPACE_PREFIX
from gdrive.types import JSONDict


@dataclass
class QuerySpec:
    """Describes what to download from Google Drive."""

    name: str
    type: str  # "folder" | "query"
    folder_id: str = ""
    recursive: bool = True
    q: str = ""
    dest: str = ""  # optional default destination; CLI --dest takes precedence
    drive_dest: str = (
        ""  # optional Drive folder ID for gdrive copy; CLI --dest-folder takes precedence
    )

    def to_json_dict(self) -> JSONDict:
        d: JSONDict = {"name": self.name, "type": self.type}
        if self.type == "folder":
            d["folder_id"] = self.folder_id
            d["recursive"] = self.recursive
        else:
            d["q"] = self.q
        if self.dest:
            d["dest"] = self.dest
        if self.drive_dest:
            d["drive_dest"] = self.drive_dest
        return d

    @staticmethod
    def from_json_dict(d: JSONDict) -> "QuerySpec":
        return QuerySpec(
            name=str(d.get("name", "")),
            type=str(d["type"]),
            folder_id=str(d.get("folder_id", "")),
            recursive=bool(d.get("recursive", True)),
            q=str(d.get("q", "")),
            dest=str(d.get("dest", "")),
            drive_dest=str(d.get("drive_dest", "")),
        )

    @staticmethod
    def from_file(path: Path) -> "QuerySpec":
        return QuerySpec.from_json_dict(json.loads(path.read_text()))


@dataclass
class DriveFile:
    """A single file in a Drive manifest."""

    id: str
    name: str
    mime_type: str  # export MIME type for Workspace files; raw type otherwise
    drive_mime_type: str  # always the raw Drive MIME type
    relative_path: str = ""  # non-empty for folder downloads
    size: int = 0
    md5_checksum: str = ""  # Drive-provided for binary; local MD5 for exports
    export_mime_type: str = ""  # non-empty only for Workspace files
    export_extension: str = ""  # e.g. ".docx"; non-empty only for Workspace files
    owner_name: str = ""
    owner_email: str = ""
    status: str = STATUS_PENDING
    downloaded_at: str = ""
    download_path: str = ""  # relative to dest root; set on successful download
    failure_reason: str = ""
    drive_copy_id: str = ""  # Drive file ID of the copy; set by gdrive copy on success
    copied_at: str = ""  # UTC ISO timestamp; set by gdrive copy on success

    @property
    def is_workspace_file(self) -> bool:
        return self.drive_mime_type.startswith(WORKSPACE_PREFIX)

    @property
    def local_name(self) -> str:
        """Filename on disk — appends export extension for Workspace files."""
        if self.export_extension and not self.name.endswith(self.export_extension):
            return self.name + self.export_extension
        return self.name

    def to_json_dict(self) -> JSONDict:
        return {
            "id": self.id,
            "name": self.name,
            "mime_type": self.mime_type,
            "drive_mime_type": self.drive_mime_type,
            "relative_path": self.relative_path,
            "size": self.size,
            "md5_checksum": self.md5_checksum,
            "export_mime_type": self.export_mime_type,
            "export_extension": self.export_extension,
            "owner_name": self.owner_name,
            "owner_email": self.owner_email,
            "status": self.status,
            "downloaded_at": self.downloaded_at,
            "download_path": self.download_path,
            "failure_reason": self.failure_reason if self.status != STATUS_COMPLETED else "",
            "drive_copy_id": self.drive_copy_id,
            "copied_at": self.copied_at,
        }

    @staticmethod
    def from_json_dict(d: JSONDict) -> "DriveFile":
        return DriveFile(
            id=str(d["id"]),
            name=str(d["name"]),
            mime_type=str(d["mime_type"]),
            drive_mime_type=str(d["drive_mime_type"]),
            relative_path=str(d.get("relative_path", "")),
            size=int(d.get("size", 0)),
            md5_checksum=str(d.get("md5_checksum", "")),
            export_mime_type=str(d.get("export_mime_type", "")),
            export_extension=str(d.get("export_extension", "")),
            owner_name=str(d.get("owner_name", "")),
            owner_email=str(d.get("owner_email", "")),
            status=str(d.get("status", STATUS_PENDING)),
            downloaded_at=str(d.get("downloaded_at", "")),
            download_path=str(d.get("download_path", "")),
            failure_reason=str(d.get("failure_reason", "")),
            drive_copy_id=str(d.get("drive_copy_id", "")),
            copied_at=str(d.get("copied_at", "")),
        )

    @staticmethod
    def from_api_item(item: JSONDict, parent_path: str = "") -> "DriveFile":
        """Construct from a Drive API files.list() response item."""
        drive_mime = str(item.get("mimeType", ""))
        export_mime, export_ext = WORKSPACE_EXPORT_MAP.get(drive_mime, ("", ""))
        effective_mime = export_mime if export_mime else drive_mime
        owners = item.get("owners", [])
        first_owner = owners[0] if isinstance(owners, list) and owners else {}
        assert isinstance(first_owner, dict)
        return DriveFile(
            id=str(item["id"]),
            name=str(item["name"]),
            mime_type=effective_mime,
            drive_mime_type=drive_mime,
            relative_path=parent_path,
            size=int(item.get("size", 0)),
            md5_checksum=str(item.get("md5Checksum", "")),
            export_mime_type=export_mime,
            export_extension=export_ext,
            owner_name=str(first_owner.get("displayName", "")),
            owner_email=str(first_owner.get("emailAddress", "")),
        )


@dataclass
class Manifest:
    """The full download manifest: provenance + file list."""

    name: str
    built_at: str
    query: QuerySpec
    files: list[DriveFile] = field(default_factory=list)

    def to_json_dict(self) -> JSONDict:
        return {
            "name": self.name,
            "built_at": self.built_at,
            "query": self.query.to_json_dict(),
            "files": [f.to_json_dict() for f in self.files],
        }

    @staticmethod
    def from_json_dict(d: JSONDict) -> "Manifest":
        files_raw = d.get("files", [])
        assert isinstance(files_raw, list)
        return Manifest(
            name=str(d.get("name", "")),
            built_at=str(d.get("built_at", "")),
            query=QuerySpec.from_json_dict(d["query"]),  # type: ignore[arg-type]
            files=[DriveFile.from_json_dict(f) for f in files_raw],  # type: ignore[arg-type]
        )
