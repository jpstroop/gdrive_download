"""Manifest persistence and summary computation.

A manifest is a local JSON file created and maintained by this tool — it is not a Google
Drive concept. Running ``gdrive build`` queries the Drive API, collects metadata for every
matching file, and writes the result to a manifest. From that point on the manifest is the
source of truth: ``gdrive download`` reads pending files from it, writes per-file status
back after each download, and uses it to determine what remains on subsequent runs.
"""

# Standard library imports
from datetime import datetime
from datetime import timezone
import json
from pathlib import Path

# Local imports
from gdrive.constants import STATUS_COMPLETED
from gdrive.constants import STATUS_FAILED
from gdrive.constants import STATUS_PENDING
from gdrive.models import DriveFile
from gdrive.models import Manifest
from gdrive.models import QuerySpec
from gdrive.types import JSONDict


def format_bytes(n: int) -> str:
    """Human-readable byte size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"


def compute_summary(files: list[DriveFile]) -> JSONDict:
    """Return summary counts and totals. Recomputed fresh on every call."""
    completed = sum(1 for f in files if f.status == STATUS_COMPLETED)
    failed = sum(1 for f in files if f.status == STATUS_FAILED)
    pending = sum(1 for f in files if f.status == STATUS_PENDING)
    total_bytes = sum(f.size for f in files)
    remaining_bytes = sum(f.size for f in files if f.status in (STATUS_PENDING, STATUS_FAILED))
    return {
        "total_files": len(files),
        "total_bytes": total_bytes,
        "total_size": format_bytes(total_bytes),
        "remaining_bytes": remaining_bytes,
        "remaining_size": format_bytes(remaining_bytes),
        "completed": completed,
        "failed": failed,
        "pending": pending,
    }


def load_manifest(path: Path) -> Manifest:
    """Read and deserialize a manifest JSON file."""
    return Manifest.from_json_dict(json.loads(path.read_text()))


def save_manifest(manifest: Manifest, path: Path) -> None:
    """Serialize manifest to JSON with a freshly-computed summary block."""
    doc = manifest.to_json_dict()
    doc["summary"] = compute_summary(manifest.files)
    # Insert summary after built_at for readability
    ordered: JSONDict = {}
    for key in ("name", "built_at", "query", "summary", "files"):
        if key in doc:
            ordered[key] = doc[key]
    path.write_text(json.dumps(ordered, indent=2))


def build_manifest(query: QuerySpec, files: list[DriveFile]) -> Manifest:
    """Construct a new Manifest from a query spec and enumerated file list."""
    return Manifest(
        name=query.name, built_at=datetime.now(timezone.utc).isoformat(), query=query, files=files
    )


def print_status(manifest: Manifest) -> None:
    """Print a formatted file list and summary to stdout."""
    files = manifest.files
    total_bytes = sum(f.size for f in files)
    pending = [f for f in files if f.status == STATUS_PENDING]
    failed = [f for f in files if f.status == STATUS_FAILED]
    completed = [f for f in files if f.status == STATUS_COMPLETED]
    pending_size = sum(f.size for f in pending) + sum(f.size for f in failed)

    status_icon = {STATUS_COMPLETED: "✔", STATUS_FAILED: "✗", STATUS_PENDING: " "}
    width = 70
    print(f"\n{'─' * width}")
    for f in files:
        display = (f.relative_path + "/" if f.relative_path else "") + f.local_name
        icon = status_icon.get(f.status, "?")
        size_str = format_bytes(f.size) if f.size else "  (unknown)"
        print(f"  [{icon}] {display:<55}  {size_str:>10}")
    print(f"{'─' * width}")
    print(f"  Total size:   {format_bytes(total_bytes)}")
    print(f"  Remaining:    {format_bytes(pending_size)}")
    print(f"  Done: {len(completed)}  Failed: {len(failed)}  Pending: {len(pending)}")
