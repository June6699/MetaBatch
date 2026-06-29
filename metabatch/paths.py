from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import DownloadType

RESULT_SUFFIX = "_metascape"
EXTRACTED_SUFFIX = "_metascape_extracted"


@dataclass(slots=True)
class OutputPaths:
    relative_parent: Path
    output_dir: Path
    base_name: str
    download_path: Path
    extracted_dir: Path | None


def build_output_paths(
    input_root: Path,
    output_root: Path,
    source_file: Path,
    download_type: DownloadType,
) -> OutputPaths:
    relative_source = source_file.relative_to(input_root)
    relative_parent = relative_source.parent
    output_dir = output_root / relative_parent
    base_name = f"{source_file.stem}{RESULT_SUFFIX}"
    download_path = output_dir / f"{base_name}{download_type.extension}"
    extracted_dir = (
        output_dir / f"{base_name}_extracted"
        if download_type is DownloadType.ZIP_WITH_EXTRACT
        else None
    )
    return OutputPaths(
        relative_parent=relative_parent,
        output_dir=output_dir,
        base_name=base_name,
        download_path=download_path,
        extracted_dir=extracted_dir,
    )


def is_generated_result_path(path: Path) -> bool:
    lowered = path.stem.lower()
    return lowered.endswith(RESULT_SUFFIX.lower()) or lowered.endswith(EXTRACTED_SUFFIX.lower())
