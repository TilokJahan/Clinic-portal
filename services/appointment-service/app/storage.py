"""Where uploaded lab reports are kept. Chosen by LAB_STORAGE:

- "local" (default; docker compose, kind, tests): a folder, LAB_STORAGE_DIR.
- "azure-blob" (cloud): a private Azure Blob Storage container, reached with workload identity
  (DefaultAzureCredential), no account keys. LAB_STORAGE_ACCOUNT_URL + LAB_STORAGE_CONTAINER.
"""

import os
from pathlib import Path
from typing import Protocol


class LabStore(Protocol):
    def save(self, name: str, content: bytes, content_type: str) -> None: ...
    def read(self, name: str) -> bytes: ...


class LocalStore:
    def __init__(self, folder: str):
        self.folder = Path(folder)

    def _path(self, name: str) -> Path:
        path = (self.folder / name).resolve()
        if self.folder.resolve() not in path.parents:  # names are generated, but be strict
            raise ValueError("invalid blob name")
        return path

    def save(self, name: str, content: bytes, content_type: str) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def read(self, name: str) -> bytes:
        return self._path(name).read_bytes()


class AzureBlobStore:
    def __init__(self, account_url: str, container: str):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient(account_url, credential=DefaultAzureCredential())
        self._container = service.get_container_client(container)

    def save(self, name: str, content: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        self._container.upload_blob(
            name, content, content_settings=ContentSettings(content_type=content_type)
        )

    def read(self, name: str) -> bytes:
        return self._container.download_blob(name).readall()


_store: LabStore | None = None


def get_store() -> LabStore:
    """FastAPI dependency (overridden in tests)."""
    global _store
    if _store is None:
        kind = os.environ.get("LAB_STORAGE", "local").strip().lower()
        if kind == "azure-blob":
            _store = AzureBlobStore(
                os.environ["LAB_STORAGE_ACCOUNT_URL"],
                os.environ.get("LAB_STORAGE_CONTAINER", "lab-reports"),
            )
        elif kind == "local":
            _store = LocalStore(os.environ.get("LAB_STORAGE_DIR", "/tmp/lab-reports"))
        else:
            raise ValueError(f"Unknown LAB_STORAGE {kind!r}. Use 'local' or 'azure-blob'.")
    return _store
