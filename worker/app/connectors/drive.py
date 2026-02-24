from __future__ import annotations

import httpx


async def list_folder_files(access_token: str, folder_id: str, page_token: str | None = None) -> dict:
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
            headers={'Authorization': f'Bearer {access_token}'},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_file_text(access_token: str, file_id: str, mime_type: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        if mime_type == 'application/vnd.google-apps.document':
            resp = await client.get(
                f'https://www.googleapis.com/drive/v3/files/{file_id}/export',
                params={'mimeType': 'text/plain'},
                headers={'Authorization': f'Bearer {access_token}'},
            )
        else:
            resp = await client.get(
                f'https://www.googleapis.com/drive/v3/files/{file_id}',
                params={'alt': 'media'},
                headers={'Authorization': f'Bearer {access_token}'},
            )
        resp.raise_for_status()
        return resp.text
