"""OAuth2 credential management for Google Drive."""

# Standard library imports
from pathlib import Path

# Third party imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Local imports
from gdrive.constants import SCOPES


def get_credentials(credentials_file: Path, token_file: Path) -> Credentials:
    """Return valid credentials, refreshing or re-authorizing as needed."""
    creds: Credentials | None = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.write_text(creds.to_json())
    return creds
