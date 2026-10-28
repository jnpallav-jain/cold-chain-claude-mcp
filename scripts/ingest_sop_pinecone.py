"""Embed SOPs only into the configured, already provisioned project index."""

import json
from src.config import get_settings
from src.services.sop import (
    build_embeddings,
    pinecone_client,
    describe_compatible_index,
)
from src.services.ingestion import ingest_policy


def main():
    settings = get_settings()
    client = pinecone_client(settings)
    description = describe_compatible_index(settings, client)
    from langchain_pinecone import PineconeVectorStore

    index = client.Index(host=description.host)
    store = PineconeVectorStore(
        index=index,
        embedding=build_embeddings(settings),
        namespace=settings.pinecone_namespace,
    )
    result = ingest_policy(
        settings, store=store, index=index, resource_identity=description.host
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
