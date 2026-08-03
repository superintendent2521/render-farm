from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile

from .config import Settings


class StorageError(RuntimeError):
    pass


class Storage(ABC):
    @abstractmethod
    def put_file(self, key: str, source: Path, content_type: str = "application/octet-stream") -> None: ...

    @abstractmethod
    def copy_to(self, key: str, destination: Path) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None: ...

    @abstractmethod
    def size(self) -> int | None: ...

    def presigned_get(self, key: str, expires: int = 900) -> str | None:
        return None

    def begin_multipart(self, key: str, content_type: str) -> str | None:
        return None

    def presign_part(self, key: str, upload_id: str, part_number: int, expires: int = 3600) -> str | None:
        return None

    def finish_multipart(self, key: str, upload_id: str, parts: list[dict]) -> None:
        raise StorageError("multipart uploads are unavailable")

    def abort_multipart(self, key: str, upload_id: str) -> None:
        return None

    @abstractmethod
    def health(self) -> None: ...


def safe_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise StorageError("invalid artifact key")
    return path


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        path = self.root.joinpath(*safe_key(key).parts).resolve()
        if self.root not in path.parents:
            raise StorageError("artifact escaped storage root")
        return path

    def put_file(self, key: str, source: Path, content_type: str = "application/octet-stream") -> None:
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".partial")
        shutil.copyfile(source, temp)
        os.replace(temp, target)

    def copy_to(self, key: str, destination: Path) -> None:
        shutil.copyfile(self.path_for(key), destination)

    def delete_prefix(self, prefix: str) -> None:
        target = self.path_for(prefix)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def size(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())

    def health(self) -> None:
        if not self.root.is_dir() or not os.access(self.root, os.R_OK | os.W_OK):
            raise StorageError("local storage is not readable and writable")


class S3Storage(Storage):
    def __init__(self, settings: Settings):
        import boto3
        if not settings.s3_bucket:
            raise StorageError("S3_BUCKET is required")
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3", endpoint_url=settings.s3_endpoint, region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key,
        )

    def put_file(self, key: str, source: Path, content_type: str = "application/octet-stream") -> None:
        self.client.upload_file(str(source), self.bucket, str(safe_key(key)), ExtraArgs={"ContentType": content_type})

    def copy_to(self, key: str, destination: Path) -> None:
        self.client.download_file(self.bucket, str(safe_key(key)), str(destination))

    def delete_prefix(self, prefix: str) -> None:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=str(safe_key(prefix))):
            objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})

    def size(self) -> int | None:
        total = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            total += sum(item["Size"] for item in page.get("Contents", []))
        return total

    def presigned_get(self, key: str, expires: int = 900) -> str:
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": str(safe_key(key))}, ExpiresIn=expires)

    def begin_multipart(self, key: str, content_type: str) -> str:
        result = self.client.create_multipart_upload(Bucket=self.bucket, Key=str(safe_key(key)), ContentType=content_type)
        return result["UploadId"]

    def presign_part(self, key: str, upload_id: str, part_number: int, expires: int = 3600) -> str:
        return self.client.generate_presigned_url("upload_part", Params={"Bucket": self.bucket, "Key": str(safe_key(key)), "UploadId": upload_id, "PartNumber": part_number}, ExpiresIn=expires)

    def finish_multipart(self, key: str, upload_id: str, parts: list[dict]) -> None:
        clean = [{"ETag": p["etag"], "PartNumber": int(p["part_number"])} for p in parts]
        self.client.complete_multipart_upload(Bucket=self.bucket, Key=str(safe_key(key)), UploadId=upload_id, MultipartUpload={"Parts": clean})

    def abort_multipart(self, key: str, upload_id: str) -> None:
        self.client.abort_multipart_upload(Bucket=self.bucket, Key=str(safe_key(key)), UploadId=upload_id)

    def health(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)


def make_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_dir)
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    raise StorageError("STORAGE_BACKEND must be local or s3")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_project_archive(path: Path, max_archive: int, max_expanded: int) -> str:
    if path.stat().st_size > max_archive:
        raise StorageError("archive exceeds configured size limit")
    try:
        with ZipFile(path) as archive:
            names: set[str] = set()
            blend_files: list[str] = []
            expanded = 0
            compressed = 0
            for item in archive.infolist():
                posix = PurePosixPath(item.filename.replace("\\", "/"))
                if posix.is_absolute() or ".." in posix.parts:
                    raise StorageError("archive contains an unsafe path")
                normalized = str(posix)
                if normalized in names:
                    raise StorageError("archive contains duplicate paths")
                names.add(normalized)
                mode = (item.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise StorageError("archive may not contain symbolic links")
                expanded += item.file_size
                compressed += max(item.compress_size, 1)
                if expanded > max_expanded or expanded > compressed * 200:
                    raise StorageError("archive expands beyond safety limits")
                if not item.is_dir() and posix.suffix.lower() == ".blend":
                    blend_files.append(normalized)
            if len(blend_files) != 1:
                raise StorageError("archive must contain exactly one .blend file")
            return blend_files[0]
    except BadZipFile as exc:
        raise StorageError("project is not a valid ZIP archive") from exc


def materialize(storage: Storage, key: str):
    """Context manager-like temporary copy; caller must unlink the returned path."""
    handle, name = tempfile.mkstemp(prefix="blend-farm-")
    os.close(handle)
    path = Path(name)
    storage.copy_to(key, path)
    return path
