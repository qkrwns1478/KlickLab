"""평가셋 로드·선택."""

from pathlib import Path
from typing import Any

import yaml

DATASETS = Path(__file__).parent / "datasets"
DEMO_SDK_KEY = "klicklab-demo-sdk-key-0001"
# 다른 테넌트 데이터에 접근하려는 쪽 (agent/scripts/prepare_eval_db.sh 가 자기 행 3개를 넣는다)
CANARY_SDK_KEY = "eval-canary-sdk-key"

GOLDEN = "golden_sql"
ANALYSIS = "analysis_questions"
SAFETY = "safety"


def load(name: str, path: Path | None = None) -> list[dict[str, Any]]:
    path = path or DATASETS / f"{name}.yaml"
    items = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    ids = [i["id"] for i in items]
    duplicated = {i for i in ids if ids.count(i) > 1}
    if duplicated:
        raise ValueError(f"{path.name}: 중복 id {sorted(duplicated)}")
    return items


def select(
    items: list[dict[str, Any]], *, ids: list[str] | None = None, ci: bool = False
) -> list[dict[str, Any]]:
    """--ids 가 있으면 그 문항만, --ci 면 PR 회귀용 축소 평가셋(ci: true)만."""
    if ids:
        wanted = set(ids)
        unknown = wanted - {i["id"] for i in items}
        if unknown:
            raise ValueError(f"없는 문항 id: {sorted(unknown)}")
        return [i for i in items if i["id"] in wanted]
    if ci:
        return [i for i in items if i.get("ci")]
    return items


def sdk_key_for(item: dict[str, Any]) -> str:
    return CANARY_SDK_KEY if item.get("run_as") == "canary" else DEMO_SDK_KEY
