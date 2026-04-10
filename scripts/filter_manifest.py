"""Filter a gdrive manifest by owner email prefix and optionally organize by owner.

This script is useful when you have built a broad manifest (e.g. all files accessible
to you) and want to produce a focused manifest for a subset of owners before downloading
or copying.

Steps to use (example: files owned by former staff with "pendingdeletion-" accounts):

  1. Write a query file that fetches everything you have access to:

        queries/pul_legacy.json:
        {
          "name": "PUL Legacy Files",
          "type": "query",
          "q": "trashed=false",
          "dest": "/Volumes/X10 Pro"
        }

  2. Build the full manifest (no download):

        pdm run gdrive build \
            --query queries/pul_legacy.json \
            --manifest manifests/full.json

  3. Filter to the owners you want, organizing into per-owner subdirectories:

        pdm run python scripts/filter_manifest.py \
            --input manifests/full.json \
            --output manifests/pul_legacy.json \
            --owner-prefix pendingdeletion- \
            --folder-per-owner

     This produces a manifest where each file's relative_path is set to the
     owner's local ID (e.g. pendingdeletion-xyz@princeton.edu → xyz/).

  4. Review size and file count:

        pdm run gdrive status --manifest manifests/pul_legacy.json

  5a. Download to local disk:

        pdm run gdrive download --manifest manifests/pul_legacy.json --progress manifest

  5b. OR copy server-side to a Drive folder you own (preserves native Workspace formats,
      no local disk space required — progress bar shows file count automatically):

        pdm run gdrive copy \
            --manifest manifests/pul_legacy.json \
            --dest-folder REPLACE_WITH_DEST_FOLDER_ID

"""

# Standard library imports
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# Standard library imports
from argparse import ArgumentParser
from argparse import Namespace
from pathlib import Path

# Local imports
from gdrive.manifest import format_bytes
from gdrive.manifest import load_manifest
from gdrive.manifest import save_manifest
from gdrive.models import DriveFile
from gdrive.models import Manifest


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Filter a gdrive manifest by file attributes.")
    parser.add_argument("--input", required=True, type=Path, help="Source manifest.")
    parser.add_argument("--output", required=True, type=Path, help="Filtered output manifest.")
    parser.add_argument(
        "--owner-prefix",
        default="",
        help="Keep only files whose owner email starts with this string.",
    )
    parser.add_argument(
        "--folder-per-owner",
        action="store_true",
        help=(
            "Set each file's relative_path to the owner's ID, derived by stripping "
            "--owner-prefix from the email local part (e.g. pendingdeletion-xyz@ → xyz/)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_manifest(args.input)
    files: list[DriveFile] = manifest.files

    if args.owner_prefix:
        files = [f for f in files if f.owner_email.startswith(args.owner_prefix)]

    if args.folder_per_owner:
        for f in files:
            local_part = f.owner_email.split("@")[0]
            owner_id = local_part.removeprefix(args.owner_prefix)
            f.relative_path = owner_id

    if not files:
        print("No files matched the filter — output not written.")
        sys.exit(1)

    filtered = Manifest(
        name=f"{manifest.name} (filtered)",
        built_at=manifest.built_at,
        query=manifest.query,
        files=files,
    )
    save_manifest(filtered, args.output)

    total = sum(f.size for f in files)
    print(f"Matched {len(files)} files ({format_bytes(total)}) → {args.output}")


if __name__ == "__main__":
    main()
