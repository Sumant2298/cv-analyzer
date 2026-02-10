"""Google Drive service for uploading consented CVs via service account.

Setup (one-time):
  1. Google Cloud Console → enable Google Drive API
  2. Create Service Account → download JSON key
  3. In Google Drive: create folder, share with service account email (Editor)
  4. Set env vars:
     - GOOGLE_DRIVE_CREDENTIALS = entire JSON key string
     - GOOGLE_DRIVE_FOLDER_ID = folder ID from Drive URL
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Environment variables
CREDENTIALS_JSON = os.environ.get('GOOGLE_DRIVE_CREDENTIALS', '')
FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '')

_drive_service = None


def is_drive_configured() -> bool:
    """Check if Google Drive integration is configured."""
    return bool(CREDENTIALS_JSON and FOLDER_ID)


def _get_drive_service():
    """Build and cache Google Drive v3 service from service account creds."""
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    if not CREDENTIALS_JSON:
        raise RuntimeError('GOOGLE_DRIVE_CREDENTIALS not set')

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_dict = json.loads(CREDENTIALS_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://www.googleapis.com/auth/drive.file'],
    )
    _drive_service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
    logger.info('Google Drive service initialised (service account: %s)',
                creds_dict.get('client_email', 'unknown'))
    return _drive_service


def upload_cv_to_drive(file_path: str, user_email: str) -> Optional[str]:
    """Upload a CV file to the configured Google Drive folder.

    Args:
        file_path: Local path to CV file (PDF, DOCX, TXT)
        user_email: User's email (used in filename for identification)

    Returns:
        Google Drive file ID if successful, None if failed or not configured.
    """
    if not is_drive_configured():
        logger.info('Google Drive not configured, skipping upload')
        return None

    try:
        service = _get_drive_service()

        # Build filename: cv_YYYYMMDD_HHMMSS_username.ext
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        ext = file_path.rsplit('.', 1)[-1] if '.' in file_path else 'pdf'
        email_prefix = user_email.split('@')[0] if user_email else 'unknown'
        filename = f'cv_{timestamp}_{email_prefix}.{ext}'

        # Determine MIME type
        mime_types = {
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'txt': 'text/plain',
        }
        mime_type = mime_types.get(ext.lower(), 'application/octet-stream')

        from googleapiclient.http import MediaFileUpload

        file_metadata = {
            'name': filename,
            'parents': [FOLDER_ID],
            'description': f'CV from {user_email} — uploaded {datetime.now().isoformat()}',
        }

        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        result = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,name',
        ).execute()

        file_id = result.get('id')
        logger.info('CV uploaded to Google Drive: id=%s name=%s user=%s',
                     file_id, result.get('name'), user_email)
        return file_id

    except Exception as e:
        logger.error('Failed to upload CV to Google Drive for %s: %s',
                     user_email, e, exc_info=True)
        return None
