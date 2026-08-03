import io
import tarfile
from pathlib import Path

import pytest

from renderfarm.worker import WorkerError, safe_extract_tar


def make_tar(path: Path, entries: list[tuple[str, bytes | None, str | None]]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, contents, linkname in entries:
            info = tarfile.TarInfo(name)
            if linkname is not None:
                info.type = tarfile.SYMTYPE
                info.linkname = linkname
                archive.addfile(info)
            else:
                payload = contents or b""
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))


def test_safe_extract_tar_allows_internal_symlink(tmp_path: Path) -> None:
    archive = tmp_path / "blender.tar"
    make_tar(archive, [("blender/lib/library.so", b"library", None), ("blender/library.so", None, "lib/library.so")])

    target = tmp_path / "output"
    target.mkdir()
    safe_extract_tar(archive, target)

    assert (target / "blender/library.so").read_bytes() == b"library"


@pytest.mark.parametrize("linkname", ["/etc/passwd", "../../outside"])
def test_safe_extract_tar_rejects_escaping_symlink(tmp_path: Path, linkname: str) -> None:
    archive = tmp_path / "blender.tar"
    make_tar(archive, [("blender/link", None, linkname)])

    target = tmp_path / "output"
    target.mkdir()
    with pytest.raises(WorkerError, match="unsafe link"):
        safe_extract_tar(archive, target)
