# Drive Batch Downloader / Copier

Resumable, checksum-verified Google Drive downloader and server-side Drive copier. Download entire folders to local disk, or copy them directly to another Drive folder you own — all in batches, with progress tracked in a local manifest file so runs survive interruptions and can be spread across multiple sessions.

______________________________________________________________________

## Setup

### Requirements

- Python 3.13
- [PDM](https://pdm-project.org/)

```bash
pdm install
```

### Google Cloud credentials

You need an **OAuth 2.0 Client ID** (not an API key — API keys only work for public data and cannot access your Drive files).

1. In [Google Cloud Console](https://console.cloud.google.com/), go to **APIs & Services → Credentials**.
1. Click **Create Credentials → OAuth 2.0 Client ID** and choose **Desktop app** as the application type.
1. Download the resulting JSON file and save it as `credentials.json` in this directory.
1. Enable the **Google Drive API** for your project under **APIs & Services → Enabled APIs**.

On first run the tool opens a browser for the OAuth consent flow and caches the token in `token.json`. Subsequent runs use the cached token automatically.

This tool requests two scopes:

| Scope            | Purpose                                                                      |
| ---------------- | ---------------------------------------------------------------------------- |
| `drive.readonly` | List files, fetch metadata, download content (`build`, `status`, `download`) |
| `drive.file`     | Create copied files and destination folders (`copy`)                         |

`drive.file` only grants write access to files this app creates — it cannot modify or delete pre-existing Drive files. This is safer than the broad `drive` scope.

**When setting up OAuth consent:** click **Add or remove scopes** and add both URLs:

```
https://www.googleapis.com/auth/drive.readonly
https://www.googleapis.com/auth/drive.file
```

**Upgrading from an earlier version:** if you previously used this tool with `drive.readonly` only, your cached `token.json` will not include `drive.file`. The tool detects this automatically and opens the browser for a new consent flow — you do not need to delete `token.json` manually.

`credentials.json` and `token.json` are gitignored. Do not commit them.

______________________________________________________________________

## Workflow

```
              ┌─────────────────┐
              │ JSON query file │
              └────────┬────────┘
                       │
                  gdrive build        ← enumerates files, fetches metadata
                       │
             ┌─────────▼──────────┐
             │ JSON manifest file │   ← tracks per-file status across sessions
             └────┬───────────┬───┘
                  │           │
             gdrive       gdrive
             download      copy
                  │           │
            local disk    Drive folder
            (converted)   (native format)
                       ↑
                  gdrive status       ← inspect size and progress at any time
```

______________________________________________________________________

## Commands

### `gdrive build`

Enumerates all files matching a query, fetches file sizes and checksums, and writes a manifest. Does not download anything.

```bash
pdm run gdrive build --query queries/my_folder.json --manifest my.json
```

| Flag            | Default            | Description                            |
| --------------- | ------------------ | -------------------------------------- |
| `--query`       | *(required)*       | Path to query JSON file                |
| `--manifest`    | `manifest.json`    | Output path for the generated manifest |
| `--credentials` | `credentials.json` | OAuth2 client secret file              |
| `--token`       | `token.json`       | OAuth2 token cache                     |

______________________________________________________________________

### `gdrive status`

Shows every file with its size and download status, plus a summary of totals.

```bash
pdm run gdrive status --manifest my.json
```

| Flag         | Default         | Description              |
| ------------ | --------------- | ------------------------ |
| `--manifest` | `manifest.json` | Manifest file to inspect |

______________________________________________________________________

### `gdrive download`

Downloads pending (and previously failed) files from a manifest, verifying checksums after each file. The manifest is updated after every file so the process can be stopped and resumed at any point.

```bash
pdm run gdrive download --manifest my.json --dest /Volumes/myhome
pdm run gdrive download --manifest my.json --batch 5   # download 5 files, then stop
```

Failed files are always retried first on the next run — no flags needed.

| Flag            | Default            | Description                                                                                                                |
| --------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `--manifest`    | `manifest.json`    | Manifest to read and update                                                                                                |
| `--dest`        | *(none)*           | Destination root directory. Overrides the `dest` field in the query file. Required if `dest` is not set in the query file. |
| `--batch`       | `0` (all)          | Maximum number of files to download this run                                                                               |
| `--connections` | `4`                | Parallel connections per file (binary files only)                                                                          |
| `--retries`     | `3`                | Retry attempts per file on failure                                                                                         |
| `--progress`    | `file`             | Progress bar mode: `file` (one bar per file) or `manifest` (one bar for the whole batch)                                   |
| `--credentials` | `credentials.json` | OAuth2 client secret file                                                                                                  |
| `--token`       | `token.json`       | OAuth2 token cache                                                                                                         |

______________________________________________________________________

### `gdrive copy`

Copies pending (and previously failed) files server-side to a Drive folder you own, preserving directory structure. No local disk space is required and Google Workspace files stay in their native format — no conversion to DOCX/XLSX/PPTX occurs.

```bash
pdm run gdrive copy --manifest my.json --dest-folder 1ABCxyz123
pdm run gdrive copy --manifest my.json --dest-folder 1ABCxyz123 --batch 10   # copy 10 files, then stop
```

A file-count progress bar is shown automatically. The manifest is updated after every file so the process can be stopped and resumed.

| Flag            | Default            | Description                                                                                                                    |
| --------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `--manifest`    | `manifest.json`    | Manifest to read and update                                                                                                    |
| `--dest-folder` | *(none)*           | Destination Drive folder ID. Overrides the `drive_dest` field in the query file. Required if `drive_dest` is not in the query. |
| `--batch`       | `0` (all)          | Maximum number of files to copy this run                                                                                       |
| `--retries`     | `3`                | Retry attempts per file on failure                                                                                             |
| `--credentials` | `credentials.json` | OAuth2 client secret file                                                                                                      |
| `--token`       | `token.json`       | OAuth2 token cache                                                                                                             |

______________________________________________________________________

## Query Files

Query files are JSON and live in `queries/`. They describe what to download and, optionally, where to put it. See `queries/` for examples.

The `type` field controls which enumeration strategy is used — `"folder"` or `"query"` are the only valid values. Use `"folder"` when you need to preserve directory structure; use `"query"` when you just want a flat collection of files matching some criteria.

### Folder download

Downloads all files in a folder, preserving the directory structure. The tool traverses the hierarchy and records each file's path relative to the root folder, so the layout is recreated on disk.

```json
{
  "name": "My Files",
  "type": "folder",
  "folder_id": "<FOLDER_ID>",
  "recursive": true,
  "dest": "/Volumes/myhome/my_files"
}
```

| Field        | Required | Description                                                               |
| ------------ | -------- | ------------------------------------------------------------------------- |
| `name`       | yes      | Human label; used in manifest and status output                           |
| `type`       | yes      | `"folder"`                                                                |
| `folder_id`  | yes      | The Drive folder ID (from the URL: `drive.google.com/drive/folders/<id>`) |
| `recursive`  | no       | `true` (default) to include subfolders; `false` for top level only        |
| `dest`       | no       | Default local download destination; overridden by `--dest` on the CLI     |
| `drive_dest` | no       | Default Drive copy destination (folder ID); overridden by `--dest-folder` |

### Query download

Downloads all files matching a [Drive API query string](#drive-query-syntax).

```json
{
  "name": "Shared photos",
  "type": "query",
  "q": "(mimeType='image/jpeg' or mimeType='image/png') and trashed=false",
  "dest": "/Volumes/myhome/photos"
}
```

| Field        | Required | Description                                                               |
| ------------ | -------- | ------------------------------------------------------------------------- |
| `name`       | yes      | Human label                                                               |
| `type`       | yes      | `"query"`                                                                 |
| `q`          | yes      | Drive API query string (see below)                                        |
| `dest`       | no       | Default local download destination                                        |
| `drive_dest` | no       | Default Drive copy destination (folder ID); overridden by `--dest-folder` |

______________________________________________________________________

## Drive Query Syntax

The `q` field accepts the [Drive API search query language](https://developers.google.com/workspace/drive/api/guides/search-files). Queries are strings composed of one or more clauses joined by `and`, `or`, or `not`.

### Examples

```
# All files in a specific folder (non-recursive)
'<FOLDER_ID>' in parents and trashed=false

# All PDFs modified after 2024
mimeType='application/pdf' and modifiedTime>'2024-01-01T00:00:00' and trashed=false

# All images (JPEG or PNG) not in trash
(mimeType='image/jpeg' or mimeType='image/png') and trashed=false

# Files whose name contains "invoice"
name contains 'invoice' and trashed=false

# All Google Docs owned by a specific user
mimeType='application/vnd.google-apps.document' and 'user@example.com' in owners
```

______________________________________________________________________

## Google Workspace Files

### `gdrive download`

Google Docs, Sheets, and Presentations cannot be downloaded as-is — they are exported automatically to Office formats:

| Drive type    | Downloaded as |
| ------------- | ------------- |
| Google Doc    | `.docx`       |
| Google Sheet  | `.xlsx`       |
| Google Slides | `.pptx`       |

Exported files are downloaded sequentially (the Drive API does not support parallel range requests for exports). A local MD5 checksum is computed after download and stored in the manifest for future reference.

### `gdrive copy`

When copying to Drive, Workspace files are copied in their **native format** — a Google Doc stays a Google Doc, a Presentation stays a Presentation. No conversion occurs. This is one of the primary advantages of `gdrive copy` over `gdrive download`.

______________________________________________________________________

## Manifests

A manifest is a local JSON file created and maintained by this tool — it is not a Google Drive concept. Running `gdrive build` queries the Drive API, collects metadata for every matching file, and writes the result to a manifest. From that point on, the manifest is the source of truth: `gdrive download` reads pending files from it, writes per-file status back after each download, and uses it to determine what remains on subsequent runs.

This means you can:

- Inspect or edit the manifest manually before downloading
- Stop and resume a download at any point without losing progress
- Archive a manifest as a record of what was downloaded and when

Manifests are plain JSON and safe to inspect or edit manually.

```json
{
  "name": "My Files",
  "built_at": "2026-03-30T14:00:00+00:00",
  "query": { "type": "folder", "folder_id": "...", "recursive": true },
  "summary": {
    "total_files": 42,
    "total_bytes": 8589934592,
    "total_size": "8.0 GB",
    "remaining_bytes": 6442450944,
    "remaining_size": "6.0 GB",
    "completed": 10,
    "failed": 0,
    "pending": 32
  },
  "files": [
    {
      "id": "...",
      "name": "photo.jpg",
      "mime_type": "image/jpeg",
      "drive_mime_type": "image/jpeg",
      "relative_path": "2024/July",
      "size": 3145728,
      "md5_checksum": "d41d8cd98f00b204e9800998ecf8427e",
      "export_mime_type": "",
      "export_extension": "",
      "owner_name": "Jane Smith",
      "owner_email": "jsmith@example.com",
      "status": "completed",
      "downloaded_at": "2026-03-30T15:23:11+00:00",
      "download_path": "2024/July/photo.jpg",
      "failure_reason": "",
      "drive_copy_id": "",
      "copied_at": ""
    }
  ]
}
```

File status values: `pending`, `completed`, `failed`. Failed files are automatically retried first on the next `download` or `copy` run.

The `drive_copy_id` and `copied_at` fields are populated by `gdrive copy` on success. They are empty for files processed by `gdrive download`.

______________________________________________________________________

## Miscellaneous

**Check total size before committing to a download:**

```bash
pdm run gdrive build --query queries/my_folder.json && pdm run gdrive status
```

**Resume after an interruption:** just re-run `download` — it picks up where it left off.

**Slow connection or limited time:** use `--batch` to download a fixed number of files per session.

**Rate limits:** if you hit Drive API rate limits during `build`, re-running it will skip files that already have metadata.

**Filtering a manifest:** `scripts/filter_manifest.py` lets you produce a focused manifest from a broader one — for example, keeping only files owned by a particular set of users. See the script header for full usage and an example workflow.
