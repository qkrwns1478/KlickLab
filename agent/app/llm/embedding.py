"""문서·질의 임베딩.

EmbeddingClient 로 감싸 공급자를 바꿀 수 있게 한다. 기본 구현은 로컬 bge-m3(1024차원, 다국어)이다.
sentence-transformers 는 선택 의존성(`uv sync --extra embedding`)이며, 없으면 키워드 검색만 한다.
"""

import threading
from typing import Protocol

from app.config import Settings


class EmbeddingError(Exception):
    pass


class EmbeddingClient(Protocol):
    model: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """정규화한 벡터 목록 (코사인 거리 기준). 동기 함수이므로 루프에서는 to_thread 로 부른다."""
        ...


class LocalEmbedding:
    """sentence-transformers 로컬 모델. 첫 호출 때 한 번 로드한다 (bge-m3 CPU 로드 약 10~60초)."""

    def __init__(self, model: str, *, dimension: int, device: str = "cpu", batch_size: int = 16):
        self.model = model
        self.dimension = dimension
        self._device = device
        self._batch_size = batch_size
        self._encoder = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._encoder is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as e:
                    raise EmbeddingError(
                        "sentence-transformers 가 없습니다. "
                        "`uv sync --extra embedding` 으로 설치하세요."
                    ) from e
                encoder = SentenceTransformer(self.model, device=self._device)
                # sentence-transformers 6 에서 이름이 바뀌었다
                dimension_of = getattr(encoder, "get_embedding_dimension", None) or (
                    encoder.get_sentence_embedding_dimension
                )
                actual = dimension_of()
                if actual != self.dimension:
                    raise EmbeddingError(
                        f"{self.model} 의 차원({actual})이 설정({self.dimension})과 다릅니다."
                    )
                self._encoder = encoder
        return self._encoder

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        encoder = self._load()
        vectors = encoder.encode(
            texts, batch_size=self._batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        return [v.tolist() for v in vectors]


def build_embedding_client(settings: Settings) -> EmbeddingClient | None:
    """EMBEDDING_PROVIDER=none 이면 None (키워드 검색만)."""
    if settings.embedding_provider == "none":
        return None
    if settings.embedding_provider == "local":
        return LocalEmbedding(
            settings.embedding_model,
            dimension=settings.embedding_dimension,
            device=settings.embedding_device,
        )
    raise EmbeddingError(f"지원하지 않는 임베딩 공급자입니다: {settings.embedding_provider}")
