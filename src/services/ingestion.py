"""Target-scoped ingestion with retryable cache updates and no index deletion."""

import hashlib
import json
from src.config import PROJECT_ROOT, Settings
from src.services.documents import parse_and_chunk_document


def ingest_policy(settings: Settings, *, store, index, resource_identity: str):
    identity = {
        "index": settings.pinecone_index_name,
        "namespace": settings.pinecone_namespace,
        "host": resource_identity,
        "mode": settings.embedding_mode,
        "model": settings.local_embedding_model
        if settings.embedding_mode == "LOCAL"
        else settings.openai_embedding_model,
        "dimension": settings.embedding_dimension,
        "splitter": "headers-600-60-v1",
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    cache_path = PROJECT_ROOT / "data/cache" / f"ingestion-{key}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    saved = {}
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
        if payload.get("identity") == identity:
            saved = payload.get("files", {})
    policy_dir = settings.resolve_path(settings.policy_dir)
    if not policy_dir.is_dir():
        raise ValueError("Configured policy directory does not exist.")
    paths = {
        p.name: p
        for p in policy_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".md", ".txt", ".pdf", ".csv", ".xlsx"}
    }
    counts = {"processed": 0, "skipped": 0, "removed": 0}

    def save():
        temp = cache_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps({"identity": identity, "files": saved}, indent=2) + "\n"
        )
        temp.replace(cache_path)

    for filename in sorted(set(saved) - set(paths)):
        ids = saved[filename]["ids"]
        for offset in range(0, len(ids), 1000):
            index.delete(
                ids=ids[offset : offset + 1000], namespace=settings.pinecone_namespace
            )
        del saved[filename]
        save()
        counts["removed"] += 1
    for filename, path in sorted(paths.items()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        previous = saved.get(filename, {})
        if previous.get("sha256") == digest:
            counts["skipped"] += 1
            continue
        chunks = parse_and_chunk_document(path)
        if not chunks:
            raise ValueError(
                f"No usable content in {filename}; old cache and vectors retained."
            )
        # Content-versioned IDs keep previous vectors intact if an upload fails.
        prefix = hashlib.sha256(filename.encode()).hexdigest()[:16]
        ids = [f"{prefix}-{digest}-{i}" for i in range(len(chunks))]
        for chunk in chunks:
            chunk.metadata.update(
                source_file=filename,
                file_format=path.suffix[1:].upper(),
                document_type="Compliance Asset",
            )
        for offset in range(0, len(chunks), 100):
            store.add_documents(
                chunks[offset : offset + 100],
                ids=ids[offset : offset + 100],
                namespace=settings.pinecone_namespace,
            )
        stale = [item for item in previous.get("ids", []) if item not in ids]
        for offset in range(0, len(stale), 1000):
            index.delete(
                ids=stale[offset : offset + 1000], namespace=settings.pinecone_namespace
            )
        saved[filename] = {"sha256": digest, "ids": ids}
        save()
        counts["processed"] += 1
    return counts
