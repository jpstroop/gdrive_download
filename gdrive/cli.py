"""CLI entry point: build, status, and download subcommands."""

# Standard library imports
from argparse import ArgumentParser
from argparse import Namespace
from datetime import datetime
from datetime import timezone
from pathlib import Path
from shutil import disk_usage
import sys

# Third party imports
from google.auth.transport.requests import AuthorizedSession
from googleapiclient.discovery import build
from tqdm import tqdm

# Local imports
from gdrive.auth import get_credentials
from gdrive.constants import CREDENTIALS_FILE
from gdrive.constants import DEFAULT_CONNECTIONS
from gdrive.constants import DEFAULT_MANIFEST
from gdrive.constants import DEFAULT_RETRIES
from gdrive.constants import STATUS_COMPLETED
from gdrive.constants import STATUS_FAILED
from gdrive.constants import STATUS_PENDING
from gdrive.constants import TOKEN_FILE
from gdrive.downloader import download_file
from gdrive.lister import enumerate_folder
from gdrive.lister import enumerate_query
from gdrive.lister import fetch_metadata
from gdrive.manifest import build_manifest
from gdrive.manifest import format_bytes
from gdrive.manifest import load_manifest
from gdrive.manifest import print_status
from gdrive.manifest import save_manifest
from gdrive.models import QuerySpec


def _parse_args() -> Namespace:
    parser = ArgumentParser(
        prog="gdrive", description="Download files from Google Drive in resumable batches."
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=CREDENTIALS_FILE,
        help=f"OAuth2 client secret file (default: {CREDENTIALS_FILE}).",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=TOKEN_FILE,
        help=f"OAuth2 token cache file (default: {TOKEN_FILE}).",
    )

    sub = parser.add_subparsers(dest="subcommand", required=True)

    # build
    p_build = sub.add_parser(
        "build", help="Enumerate files from Drive, fetch metadata, write manifest."
    )
    p_build.add_argument("--query", required=True, type=Path, help="Path to query JSON file.")
    p_build.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Output manifest path (default: {DEFAULT_MANIFEST}).",
    )

    # status
    p_status = sub.add_parser("status", help="Show manifest summary and per-file status.")
    p_status.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Manifest file to inspect (default: {DEFAULT_MANIFEST}).",
    )

    # download
    p_dl = sub.add_parser("download", help="Download files from an existing manifest.")
    p_dl.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Manifest to read/update (default: {DEFAULT_MANIFEST}).",
    )
    p_dl.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="Destination root directory (overrides query file 'dest' field).",
    )
    p_dl.add_argument(
        "--batch",
        type=int,
        default=0,
        help="Max files to download this run (0 = all pending, default: 0).",
    )
    p_dl.add_argument(
        "--connections",
        type=int,
        default=DEFAULT_CONNECTIONS,
        help=f"Parallel connections per binary file (default: {DEFAULT_CONNECTIONS}).",
    )
    p_dl.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"Retry attempts per file (default: {DEFAULT_RETRIES}).",
    )
    p_dl.add_argument(
        "--progress",
        choices=["file", "manifest"],
        default="file",
        help="Progress bar mode: one bar per file (default) or one bar for the whole batch.",
    )

    return parser.parse_args()


def _cmd_build(args: Namespace) -> None:
    query = QuerySpec.from_file(args.query)
    print(f"Authenticating with Google Drive...")
    creds = get_credentials(args.credentials, args.token)
    service = build("drive", "v3", credentials=creds)

    print(f"Enumerating files for '{query.name}'...")
    if query.type == "folder":
        files = enumerate_folder(service, query.folder_id, query.recursive)
    else:
        files = enumerate_query(service, query.q)
    print(f"  Found {len(files)} files.")

    fetch_metadata(service, files)

    manifest = build_manifest(query, files)
    save_manifest(manifest, args.manifest)
    print(f"Manifest written to {args.manifest}")
    print_status(manifest)


def _cmd_status(args: Namespace) -> None:
    manifest = load_manifest(args.manifest)
    print(f"Manifest: {args.manifest}  (built {manifest.built_at})")
    print_status(manifest)


def _cmd_download(args: Namespace) -> None:
    manifest = load_manifest(args.manifest)

    # Resolve destination: CLI > query file > error
    dest: Path | None = args.dest
    if dest is None and manifest.query.dest:
        dest = Path(manifest.query.dest)
    if dest is None:
        print(
            "error: no destination specified. "
            "Use --dest or add a 'dest' field to your query file."
        )
        sys.exit(1)

    dest.mkdir(parents=True, exist_ok=True)

    print(f"Authenticating with Google Drive...")
    creds = get_credentials(args.credentials, args.token)
    session = AuthorizedSession(creds)

    # Failed files always go first, then pending
    failed = [f for f in manifest.files if f.status == STATUS_FAILED]
    pending = [f for f in manifest.files if f.status == STATUS_PENDING]
    completed = [f for f in manifest.files if f.status == STATUS_COMPLETED]
    queue = failed + pending

    batch = queue if args.batch == 0 else queue[: args.batch]
    batch_bytes = sum(f.size for f in batch)
    free = disk_usage(dest).free

    print(f"\n{'=' * 60}")
    print(f"Total files:   {len(manifest.files)}")
    print(f"Completed:     {len(completed)}")
    print(f"Failed:        {len(failed)}")
    print(f"Pending:       {len(pending)}")
    print(f"This batch:    {len(batch)}  ({format_bytes(batch_bytes)})")
    print(f"Free space:    {format_bytes(free)}")
    print(f"Destination:   {dest}")
    print(f"Connections:   {args.connections} per file")
    print(f"Retries:       {args.retries} per file")
    print(f"{'=' * 60}\n")

    if not batch:
        print("Nothing to download.")
        return

    succeeded = 0
    if args.progress == "manifest":
        manifest_bar: tqdm = tqdm(  # type: ignore[type-arg]
            total=batch_bytes if batch_bytes else None,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=f"0/{len(batch)}",
            leave=True,
        )
        for i, f in enumerate(batch, 1):
            manifest_bar.write(f"[{i}/{len(batch)}] {f.local_name}")
            manifest_bar.set_description(f"[{i}/{len(batch)}]", refresh=False)
            ok = download_file(session, f, dest, args.connections, args.retries, manifest_bar)
            if ok:
                f.status = STATUS_COMPLETED
                f.downloaded_at = datetime.now(timezone.utc).isoformat()
                f.failure_reason = ""
                succeeded += 1
            else:
                f.status = STATUS_FAILED
                if f.size > 0:
                    manifest_bar.update(f.size)
            save_manifest(manifest, args.manifest)
        manifest_bar.close()
    else:
        for i, f in enumerate(batch, 1):
            print(f"[{i}/{len(batch)}]")
            ok = download_file(session, f, dest, args.connections, args.retries)
            if ok:
                f.status = STATUS_COMPLETED
                f.downloaded_at = datetime.now(timezone.utc).isoformat()
                f.failure_reason = ""
                succeeded += 1
            else:
                f.status = STATUS_FAILED
            save_manifest(manifest, args.manifest)

    remaining = len(queue) - len(batch)
    print(f"\nBatch complete: {succeeded}/{len(batch)} succeeded.")
    if remaining > 0:
        print(f"{remaining} files still pending. Re-run to continue.")
    else:
        print("All files downloaded!")


def main() -> None:
    args = _parse_args()
    if args.subcommand == "build":
        _cmd_build(args)
    elif args.subcommand == "status":
        _cmd_status(args)
    elif args.subcommand == "download":
        _cmd_download(args)
