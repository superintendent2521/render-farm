from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    secret_key: str
    admin_username: str
    admin_password: str
    public_url: str
    secure_cookies: bool
    storage_backend: str
    local_storage_dir: Path
    max_archive_bytes: int
    max_expanded_bytes: int
    chunk_size: int
    s3_endpoint: str | None
    s3_region: str
    s3_bucket: str | None
    s3_access_key: str | None
    s3_secret_key: str | None
    blender_version: str
    trusted_proxy_networks: tuple[str, ...]
    exposure_mode: str
    tunnel_metrics_url: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        data = Path(os.getenv("FARM_DATA_DIR", "./data"))
        return cls(
            data_dir=data,
            database_url=os.getenv("DATABASE_URL", f"sqlite:///{data / 'farm.db'}"),
            secret_key=os.getenv("SECRET_KEY", "change-me-before-production"),
            admin_username=os.getenv("ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("ADMIN_PASSWORD", "change-me-before-production"),
            public_url=os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/"),
            secure_cookies=_bool("SECURE_COOKIES", True),
            storage_backend=os.getenv("STORAGE_BACKEND", "local").lower(),
            local_storage_dir=Path(os.getenv("LOCAL_STORAGE_DIR", str(data / "artifacts"))),
            max_archive_bytes=int(os.getenv("MAX_ARCHIVE_BYTES", str(20 * 1024**3))),
            max_expanded_bytes=int(os.getenv("MAX_EXPANDED_BYTES", str(100 * 1024**3))),
            chunk_size=32 * 1024**2,
            s3_endpoint=os.getenv("S3_ENDPOINT") or None,
            s3_region=os.getenv("S3_REGION", "us-east-1"),
            s3_bucket=os.getenv("S3_BUCKET") or None,
            s3_access_key=os.getenv("S3_ACCESS_KEY") or None,
            s3_secret_key=os.getenv("S3_SECRET_KEY") or None,
            blender_version=os.getenv("BLENDER_VERSION", "4.2.5"),
            trusted_proxy_networks=tuple(x.strip() for x in os.getenv("TRUSTED_PROXY_NETWORKS", "127.0.0.1/32,172.16.0.0/12").split(",") if x.strip()),
            exposure_mode=os.getenv("EXPOSURE_MODE", "direct"),
            tunnel_metrics_url=os.getenv("TUNNEL_METRICS_URL") or None,
        )
