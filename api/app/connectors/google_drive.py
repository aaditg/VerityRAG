from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx


class GoogleDriveClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    async def list_files(self, folder_id: str, page_token: str | None = None) -> dict[str, Any]:
        params = {
            'q': f"'{folder_id}' in parents and trashed=false",
            'fields': 'nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)',
            'pageSize': '100',
            'supportsAllDrives': 'true',
            'includeItemsFromAllDrives': 'true',
        }
        if page_token:
            params['pageToken'] = page_token
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                'https://www.googleapis.com/drive/v3/files',
                params=params,
                headers={'Authorization': f'Bearer {self.access_token}'},
            )
            resp.raise_for_status()
            return resp.json()

    async def export_google_doc_text(self, file_id: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f'https://www.googleapis.com/drive/v3/files/{file_id}/export',
                params={'mimeType': 'text/plain'},
                headers={'Authorization': f'Bearer {self.access_token}'},
            )
            resp.raise_for_status()
            return resp.text

    async def download_file_text(self, file_id: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f'https://www.googleapis.com/drive/v3/files/{file_id}',
                params={'alt': 'media'},
                headers={'Authorization': f'Bearer {self.access_token}'},
            )
            resp.raise_for_status()
            return resp.text


def parse_drive_file_to_document(file_json: dict, text: str, source_id: str) -> dict:
    return {
        'source_id': source_id,
        'external_id': file_json['id'],
        'title': file_json['name'],
        'canonical_url': file_json.get('webViewLink', ''),
        'updated_at': datetime.fromisoformat(file_json['modifiedTime'].replace('Z', '+00:00')),
        'text': text,
        'metadata': {'mimeType': file_json.get('mimeType')},
    }
