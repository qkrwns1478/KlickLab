"""모델별 토큰 단가로 실행 비용(USD)을 계산한다.

단가는 USD / 100만 토큰이다. 아래 기본값은 공급자 공시 가격이라 바뀔 수 있으며,
`LLM_PRICES="모델=입력:출력,..."` 로 덮어쓴다. 단가를 모르는 모델의 비용은 None 이다 (0 이 아니다).
"""

from dataclasses import dataclass

from app.config import Settings
from app.llm.base import Usage

# Groq gpt-oss-120b 공시 가격. K-EXAONE 는 무료 등급이라 단가를 두지 않는다
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.60),
}


@dataclass(frozen=True)
class Cost:
    input: float
    output: float

    @property
    def total(self) -> float:
        return self.input + self.output


class Pricing:
    def __init__(self, prices: dict[str, tuple[float, float]] | None = None):
        self._prices = dict(prices or {})

    @classmethod
    def from_settings(cls, settings: Settings) -> "Pricing":
        prices = dict(DEFAULT_PRICES)
        prices[settings.local_model] = (0.0, 0.0)  # 로컬 추론은 호출 비용이 없다
        prices.update(parse_prices(settings.llm_prices))
        return cls(prices)

    def cost(self, model: str, usage: Usage) -> Cost | None:
        price = self._prices.get(model)
        if price is None:
            return None
        return Cost(
            usage.prompt_tokens * price[0] / 1_000_000,
            usage.completion_tokens * price[1] / 1_000_000,
        )


def parse_prices(text: str) -> dict[str, tuple[float, float]]:
    """ "모델=입력:출력,모델2=입력:출력". 형식이 틀린 항목은 무시하지 않고 오류로 알린다."""
    prices: dict[str, tuple[float, float]] = {}
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            model, _, value = item.rpartition("=")
            price_in, _, price_out = value.partition(":")
            if not model.strip():
                raise ValueError
            prices[model.strip()] = (float(price_in), float(price_out))
        except ValueError:
            raise ValueError(f"LLM_PRICES 형식이 올바르지 않습니다: {item!r}") from None
    return prices
