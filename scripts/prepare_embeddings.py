"""Copy already-cached BGE-M3 repository to a portable local directory; never downloads."""

from pathlib import Path
import shutil
from huggingface_hub import snapshot_download
from src.config import PROJECT_ROOT


def main():
    snapshot = Path(snapshot_download("BAAI/bge-m3", local_files_only=True))
    source = snapshot.parent.parent
    target = PROJECT_ROOT / "data/cache/embeddings" / source.name
    if target.exists():
        print("Portable embedding cache already exists; no overwrite performed.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=True)
    print(
        "Copied cached BGE-M3 repository to ignored data/cache/embeddings. No network download."
    )


if __name__ == "__main__":
    main()
