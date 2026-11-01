"""Path helpers for workspace-confined FODS outputs."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


def resolve_workspace_path(workspace: Path, requested: str) -> Path:
    """Resolve portable relative paths while rejecting workspace escapes."""
    root = workspace.resolve()
    posix_path = PurePosixPath(requested.replace("\\", "/"))
    windows_path = PureWindowsPath(requested)
    if (
        not requested
        or posix_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in posix_path.parts
    ):
        raise ValueError("output path must resolve inside the approved workspace")

    try:
        candidate = root.joinpath(*posix_path.parts).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("output path must resolve inside the approved workspace") from exc
    if not candidate.is_relative_to(root):
        raise ValueError("output path must resolve inside the approved workspace")
    return candidate
