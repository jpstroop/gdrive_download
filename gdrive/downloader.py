"""File download logic: parallel binary, sequential binary, and Workspace export."""

# Standard library imports
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
import hashlib
from pathlib import Path
from shutil import disk_usage
from time import sleep

# Third party imports
from google.auth.transport.requests import AuthorizedSession
from requests import Response
from tqdm import tqdm

# Local imports
from gdrive.constants import DISK_HEADROOM
from gdrive.constants import DRIVE_DOWNLOAD_URL
from gdrive.constants import DRIVE_EXPORT_URL
from gdrive.constants import PARALLEL_CHUNK_SIZE
from gdrive.constants import RETRY_BACKOFF_BASE
from gdrive.constants import SEQUENTIAL_CHUNK_SIZE
from gdrive.constants import STATUS_SKIPPED
from gdrive.manifest import format_bytes
from gdrive.models import DriveFile


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(SEQUENTIAL_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_range(
    session: AuthorizedSession,
    url: str,
    start: int,
    end: int,
    tmp_path: Path,
    bar: tqdm,  # type: ignore[type-arg]
    retries: int,
) -> None:
    """Download one byte range, writing directly to the correct file offset."""
    bytes_written = 0
    for attempt in range(retries + 1):
        try:
            headers = {"Range": f"bytes={start}-{end}"}
            resp: Response = session.get(url, headers=headers, stream=True, timeout=300)
            resp.raise_for_status()
            pos = start
            bytes_written = 0
            with open(tmp_path, "r+b") as fh:
                for data in resp.iter_content(chunk_size=PARALLEL_CHUNK_SIZE):
                    fh.seek(pos)
                    fh.write(data)
                    pos += len(data)
                    bytes_written += len(data)
                    bar.update(len(data))
            return
        except Exception as e:
            if attempt == retries:
                raise
            wait = RETRY_BACKOFF_BASE ** (attempt + 1)
            bar.write(f"  chunk {start}-{end}: error ({e}), retrying in {wait}s...")
            bar.update(-bytes_written)
            bytes_written = 0
            sleep(wait)


def _download_parallel(
    session: AuthorizedSession,
    f: DriveFile,
    tmp_path: Path,
    connections: int,
    retries: int,
    bar: tqdm,  # type: ignore[type-arg]
) -> None:
    """Split file into ranges and download concurrently."""
    url = DRIVE_DOWNLOAD_URL.format(file_id=f.id)
    chunk = f.size // connections
    ranges = [
        (i * chunk, (i + 1) * chunk - 1 if i < connections - 1 else f.size - 1)
        for i in range(connections)
    ]

    with open(tmp_path, "wb") as fh:
        fh.seek(f.size - 1)
        fh.write(b"\0")

    futures: list[Future[None]] = []
    with ThreadPoolExecutor(max_workers=connections) as pool:
        for start, end in ranges:
            futures.append(
                pool.submit(_fetch_range, session, url, start, end, tmp_path, bar, retries)
            )
        for fut in as_completed(futures):
            fut.result()


def _download_sequential(
    session: AuthorizedSession, f: DriveFile, tmp_path: Path, bar: tqdm  # type: ignore[type-arg]
) -> None:
    """Single-connection download via requests streaming."""
    url = DRIVE_DOWNLOAD_URL.format(file_id=f.id)
    resp: Response = session.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(tmp_path, "wb") as fh:
        for data in resp.iter_content(chunk_size=SEQUENTIAL_CHUNK_SIZE):
            fh.write(data)
            bar.update(len(data))


def _download_export(
    session: AuthorizedSession,
    f: DriveFile,
    tmp_path: Path,
    retries: int,
    bar: tqdm,  # type: ignore[type-arg]
) -> None:
    """Download a Google Workspace file via the Drive export endpoint."""
    url = DRIVE_EXPORT_URL.format(file_id=f.id, mime_type=f.export_mime_type)
    for attempt in range(retries + 1):
        try:
            resp: Response = session.get(url, stream=True, timeout=300)
            resp.raise_for_status()
            with open(tmp_path, "wb") as fh:
                for data in resp.iter_content(chunk_size=SEQUENTIAL_CHUNK_SIZE):
                    fh.write(data)
                    bar.update(len(data))
            return
        except Exception as e:
            if attempt == retries:
                raise
            wait = RETRY_BACKOFF_BASE ** (attempt + 1)
            bar.write(f"  export error ({e}), retrying in {wait}s...")
            if tmp_path.exists():
                tmp_path.unlink()
            sleep(wait)


def download_file(
    session: AuthorizedSession,
    f: DriveFile,
    dest_root: Path,
    connections: int,
    retries: int,
    external_bar: "tqdm | None" = None,  # type: ignore[type-arg]
) -> bool:
    """Download and verify a single file, retrying on failure. Returns True on success.

    If external_bar is provided (manifest-progress mode) it is updated directly and
    no per-file bar is created. Otherwise a new per-file bar is opened for each file.
    """
    if f.relative_path:
        dest_path = dest_root / f.relative_path / f.local_name
    else:
        dest_path = dest_root / f.local_name
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

    def _msg(text: str) -> None:
        if external_bar:
            external_bar.write(text)
        else:
            print(text)

    if f.is_workspace_file and not f.export_mime_type:
        reason = f"unsupported Workspace type: {f.drive_mime_type}"
        _msg(f"  SKIPPED {f.local_name} ({reason})")
        f.status = STATUS_SKIPPED
        f.failure_reason = reason
        return False

    if f.size > 0:
        free = disk_usage(dest_root).free
        required = f.size + DISK_HEADROOM
        if free < required:
            _msg(
                f"  ✗ Insufficient space for {f.local_name}: "
                f"need {format_bytes(required)}, have {format_bytes(free)}"
            )
            return False

    use_parallel = not f.is_workspace_file and connections > 1 and f.size > 0
    conn_label = f"{connections} connections" if use_parallel else "1 connection"
    postfix = {"conn": conn_label} if not f.is_workspace_file else {"type": "export"}

    for attempt in range(retries + 1):
        if tmp_path.exists():
            tmp_path.unlink()
        try:
            if external_bar:
                start_n: int = external_bar.n
                bar = external_bar
                if f.is_workspace_file:
                    _download_export(session, f, tmp_path, retries, bar)
                elif use_parallel:
                    _download_parallel(session, f, tmp_path, connections, retries, bar)
                else:
                    _download_sequential(session, f, tmp_path, bar)
            else:
                with tqdm(
                    total=f.size if f.size else None,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=f.local_name,
                    postfix=postfix,
                    leave=True,
                ) as bar:
                    if f.is_workspace_file:
                        _download_export(session, f, tmp_path, retries, bar)
                    elif use_parallel:
                        _download_parallel(session, f, tmp_path, connections, retries, bar)
                    else:
                        _download_sequential(session, f, tmp_path, bar)
            break
        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink()
            if external_bar:
                external_bar.update(start_n - external_bar.n)
            if attempt == retries:
                reason = f"failed after {retries + 1} attempt(s): {e}"
                _msg(f"  FAILED {f.local_name}: {reason}")
                f.failure_reason = reason
                return False
            wait = RETRY_BACKOFF_BASE ** (attempt + 1)
            _msg(f"  Attempt {attempt + 1} failed ({e}), retrying in {wait}s...")
            sleep(wait)

    if f.is_workspace_file:
        _msg(f"  Computing checksum for {f.local_name}...")
        f.md5_checksum = _md5(tmp_path)
    elif f.md5_checksum:
        actual = _md5(tmp_path)
        if actual != f.md5_checksum:
            reason = f"checksum mismatch (expected {f.md5_checksum}, got {actual})"
            _msg(f"  CHECKSUM MISMATCH for {f.local_name}: {reason}")
            f.failure_reason = reason
            tmp_path.unlink()
            return False
        _msg(f"  ✓ {f.local_name}")

    tmp_path.rename(dest_path)
    f.download_path = str(Path(f.relative_path) / f.local_name if f.relative_path else f.local_name)
    return True
