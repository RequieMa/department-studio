"""List local directories for the human's workspace picker without reading files."""

import os
from pathlib import Path

from department_studio.domain import Invalid, workspace_path


def browse_folders(path: str | None = None) -> dict:
    directory = Path(workspace_path(Path.cwd() if path is None else path))
    folders = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_dir():
                        folders.append({"name": entry.name, "path": workspace_path(entry.path)})
                except (OSError, Invalid):
                    # A broken link or a folder that disappeared cannot be selected.
                    continue
    except OSError as exc:
        raise Invalid("This folder cannot be opened. Check that you have access to it.") from exc
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "folders": sorted(folders, key=lambda folder: (folder["name"].casefold(), folder["name"])),
    }
