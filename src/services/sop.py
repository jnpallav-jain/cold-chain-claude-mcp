from dataclasses import dataclass
from functools import cached_property, lru_cache
from src.config import Settings, PROJECT_ROOT
from src.services.errors import ServiceError


@lru_cache(maxsize=1)
def _local_embeddings(model_name):
    from langchain_huggingface import HuggingFaceEmbeddings

    # Reuse an already downloaded snapshot read-only; new downloads stay in this project.
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        target = snapshot_download(model_name, local_files_only=True)
    except LocalEntryNotFoundError:
        try:
            target = snapshot_download(
                model_name,
                local_files_only=True,
                cache_dir=str(PROJECT_ROOT / "data/cache/embeddings"),
            )
        except LocalEntryNotFoundError:
            raise ServiceError(
                "Local embedding model is not cached. Prepare it before starting the agent."
            ) from None
    return HuggingFaceEmbeddings(
        model_name=target,
        cache_folder=str(PROJECT_ROOT / "data/cache/embeddings"),
        model_kwargs={"device": "cpu", "local_files_only": True},
    )


def build_embeddings(settings: Settings):
    if settings.embedding_mode == "LOCAL":
        return _local_embeddings(settings.local_embedding_model)
    settings.require("openai_api_key")
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        dimensions=settings.embedding_dimension,
        api_key=settings.openai_api_key.get_secret_value(),
        max_retries=0,
        request_timeout=min(10, settings.tool_timeout),
    )


def pinecone_client(settings):
    settings.require("pinecone_api_key")
    from pinecone import Pinecone

    return Pinecone(
        api_key=settings.pinecone_api_key.get_secret_value(), pool_threads=1
    )


def describe_compatible_index(settings, client):
    desc = client.describe_index(settings.pinecone_index_name)
    if desc.dimension != settings.embedding_dimension or desc.metric != "cosine":
        raise ServiceError(
            "Pinecone index dimension or metric mismatch. Automatic deletion is disabled; choose a new project index."
        )
    if not desc.status["ready"]:
        raise ServiceError(
            "Pinecone index is not ready; retry after provisioning finishes."
        )
    return desc


class TimedQueryIndex:
    """Duck-typed vector-store index adapter with an explicit per-query socket deadline."""

    def __init__(self, index, timeout):
        self.index, self.timeout = index, timeout

    def __getattr__(self, name):
        return getattr(self.index, name)

    def query(self, **kwargs):
        return self.index.query(
            **kwargs, _request_timeout=(min(3, self.timeout), self.timeout)
        )


@dataclass(frozen=True)
class SopPassage:
    text: str
    metadata: dict


class SopService:
    def __init__(self, settings: Settings, *, retriever=None):
        self.settings, self._retriever = settings, retriever

    @cached_property
    def retriever(self):
        if self._retriever is not None:
            return self._retriever
        from langchain_pinecone import PineconeVectorStore

        client = pinecone_client(self.settings)
        desc = describe_compatible_index(self.settings, client)
        store = PineconeVectorStore(
            index=TimedQueryIndex(
                client.Index(host=desc.host, pool_threads=1),
                min(10, self.settings.tool_timeout),
            ),
            embedding=build_embeddings(self.settings),
            namespace=self.settings.pinecone_namespace,
        )
        return store.as_retriever(search_kwargs={"k": self.settings.retrieval_k})

    def search(self, query: str) -> list[SopPassage]:
        if not query.strip():
            raise ServiceError("SOP query must not be empty.")
        try:
            return [
                SopPassage(doc.page_content, dict(doc.metadata))
                for doc in self.retriever.invoke(query)
            ]
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("SOP retrieval unavailable.") from None
