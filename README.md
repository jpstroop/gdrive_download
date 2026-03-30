# Drive Batch Downloader

Resumable, checksum-verified Google Drive downloader. Download entire folders, or any set of files matching a Drive API query, in batches that fit available disk space. State is tracked in a manifest file so downloads survive interruptions and can be spread across multiple sessions.

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

This tool requests the `drive.readonly` scope only. It can list and download files but cannot create, modify, or delete anything in your Drive.

> **When setting up OAuth consent:** you will be asked to add scopes during the client configuration wizard. `drive.readonly` is not shown on the first page — click **Add or remove scopes** and paste in the full URL to find it:
>
> ```
> https://www.googleapis.com/auth/drive.readonly
> ```
>
> Do not grant broader scopes like `drive` or `drive.file`; `drive.readonly` is sufficient and safest.

> `credentials.json` and `token.json` are gitignored. Do not commit them.

______________________________________________________________________

## Workflow

```
              ┌──────────────────┐
              │  query JSON file │
              └────────┬─────────┘
                       │
                  gdrive build        ← enumerates files, fetches metadata
                       │
              ┌────────▼─────────┐
              │  manifest JSON   │    ← tracks per-file status across sessions
              └────────┬─────────┘
                       │
                  gdrive status       ← inspect size and progress at any time
                       │
                 gdrive download      ← downloads, verifies checksums, updates manifest
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

## Query Files

Query files are JSON and live in `queries/`. They describe what to download and, optionally, where to put it. See `queries/` for examples.

The `type` field controls which enumeration strategy is used — `"folder"` or `"query"` are the only valid values:

### Folder download

Downloads all files in a folder, preserving the directory structure.

```json
{
  "name": "My Files",
  "type": "folder",
  "folder_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
  "recursive": true,
  "dest": "/Volumes/myhome/Photos"
}
```

| Field       | Required | Description                                                               |
| ----------- | -------- | ------------------------------------------------------------------------- |
| `name`      | yes      | Human label; used in manifest and status output                           |
| `type`      | yes      | `"folder"`                                                                |
| `folder_id` | yes      | The Drive folder ID (from the URL: `drive.google.com/drive/folders/<id>`) |
| `recursive` | no       | `true` (default) to include subfolders; `false` for top level only        |
| `dest`      | no       | Default download destination; overridden by `--dest` on the CLI           |

### Query download

Downloads all files matching a [Drive API query string](#drive-query-syntax).

```json
{
  "name": "Takeout Archives",
  "type": "query",
  "q": "'1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms' in parents and trashed=false",
  "dest": "/Volumes/myhome/takeout"
}
```

| Field  | Required | Description                        |
| ------ | -------- | ---------------------------------- |
| `name` | yes      | Human label                        |
| `type` | yes      | `"query"`                          |
| `q`    | yes      | Drive API query string (see below) |
| `dest` | no       | Default download destination       |

______________________________________________________________________

## Drive Query Syntax

The `q` field accepts the [Drive API search query language](https://developers.google.com/workspace/drive/api/guides/search-files). Queries are strings composed of one or more clauses joined by `and`, `or`, or `not`.

### Operators

| Operator             | Example                                            |
| -------------------- | -------------------------------------------------- |
| `=`                  | `mimeType = 'application/pdf'`                     |
| `!=`                 | `mimeType != 'application/vnd.google-apps.folder'` |
| `contains`           | `name contains 'report'`                           |
| `in`                 | `'folder_id' in parents`                           |
| `>`, `>=`, `<`, `<=` | `modifiedTime > '2024-01-01T00:00:00'`             |
| `and`                | `name contains 'photo' and trashed=false`          |
| `or`                 | `mimeType='image/jpeg' or mimeType='image/png'`    |
| `not`                | `not name contains 'draft'`                        |

### Common fields

| Field             | Type       | Notes                                       |
| ----------------- | ---------- | ------------------------------------------- |
| `name`            | string     | Filename (use `contains` for partial match) |
| `mimeType`        | string     | Exact MIME type (see below)                 |
| `'id' in parents` | —          | Files directly inside folder with that ID   |
| `trashed`         | boolean    | `true` or `false`                           |
| `modifiedTime`    | datetime   | ISO 8601 string: `'2024-06-01T00:00:00'`    |
| `createdTime`     | datetime   | ISO 8601 string                             |
| `owners`          | collection | `'user@example.com' in owners`              |
| `fullText`        | string     | Full-text search across content             |
| `starred`         | boolean    | `starred = true`                            |

### Examples

```
# All files in a specific folder (non-recursive)
'1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms' in parents and trashed=false

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

Google Docs, Sheets, and Presentations cannot be downloaded as-is — they are exported automatically to Office formats:

| Drive type    | Downloaded as |
| ------------- | ------------- |
| Google Doc    | `.docx`       |
| Google Sheet  | `.xlsx`       |
| Google Slides | `.pptx`       |

Exported files are downloaded sequentially (the Drive API does not support parallel range requests for exports). A local MD5 checksum is computed after download and stored in the manifest for future reference.

______________________________________________________________________

## Manifest Format

Manifests are written by `build` and updated after each download. They are plain JSON and safe to inspect or edit manually.

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
      "failure_reason": ""
    }
  ]
}
```

File status values: `pending`, `completed`, `failed`. Failed files are automatically retried first on the next `download` run.

______________________________________________________________________

## Tips

**Check total size before committing to a download:**

```bash
pdm run gdrive build --query queries/my_folder.json && pdm run gdrive status
```

**Resume after an interruption:** just re-run `download` — it picks up where it left off.

**Slow connection or limited time:** use `--batch` to download a fixed number of files per session.

**Rate limits:** if you hit Drive API rate limits during `build`, re-running it will skip files that already have metadata.
