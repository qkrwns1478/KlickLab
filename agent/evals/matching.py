"""실행 결과 비교.

생성 SQL 의 컬럼 이름·순서는 정답과 다를 수 있고 보조 컬럼이 더 있을 수도 있다.
그래서 정답의 각 컬럼에 값이 일치하는 예측 컬럼을 하나씩 대응시킨 뒤(단사), 그 대응으로
행 집합(또는 순서가 중요한 문항은 행 순서까지)이 같은지 본다.

* 수치는 상대 오차 0.5% 또는 절대 오차 0.01 까지 같다고 본다 (반올림 차이 허용)
* NULL 과 0 은 같다고 본다 (FILTER 집계의 NULL vs COALESCE 0)
* 자정(00:00:00) 타임스탬프는 날짜로 본다 (date_trunc 결과 vs date 컬럼)
* 전치 허용(좁게): 정답이 1행(K개 값)인데 예측이 K행이고, 예측의 한 컬럼 값들이 정답 행의 값들과
  순서 무시로 같으면 맞다고 본다. "두 기간 비교"를 열이 아니라 행으로 돌려준 경우다. 질문이 결과
  모양을 정하지 않으면 둘 다 정당하다. 순서가 중요한 문항에는 적용하지 않고,
  통과 시 transposed 로 표시한다
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

REL_TOL = 0.005
ABS_TOL = 0.01

_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00:00(\.0+)?([+-]\d{2}(:\d{2})?|Z)?$")


@dataclass(frozen=True)
class Match:
    ok: bool
    reason: str = ""
    transposed: bool = False  # 정답의 열을 예측이 행으로 돌려줘서 통과함


def normalize(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _MIDNIGHT.match(value)
        return m.group(1) if m else value
    if isinstance(value, (list, tuple)):
        return tuple(normalize(v) for v in value)
    return value


def values_equal(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return (a is None and b is None) or a == 0.0 or b == 0.0
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return a == b


def _sort_key(v: Any) -> tuple:
    if v is None:
        return (0, 0.0, "")
    if isinstance(v, float):
        return (1, v, "")
    return (2, 0.0, str(v))


def _column(rows: Sequence[Sequence[Any]], i: int) -> list[Any]:
    return [r[i] for r in rows]


def _columns_match(gold: list[Any], pred: list[Any], ordered: bool) -> bool:
    if not ordered:
        # NULL 은 0 과 같게 보므로 정렬 전에 0 으로 맞춘다
        gold = sorted((0.0 if v is None else v for v in gold), key=_sort_key)
        pred = sorted((0.0 if v is None else v for v in pred), key=_sort_key)
    return all(values_equal(g, p) for g, p in zip(gold, pred, strict=True))


def _rows_match(gold: list[tuple], pred: list[tuple], ordered: bool) -> bool:
    if ordered:
        return all(
            all(values_equal(g, p) for g, p in zip(gr, pr, strict=True))
            for gr, pr in zip(gold, pred, strict=True)
        )
    unused = list(range(len(pred)))
    for gr in gold:
        for k, idx in enumerate(unused):
            if all(values_equal(g, p) for g, p in zip(gr, pred[idx], strict=True)):
                del unused[k]
                break
        else:
            return False
    return True


def _transposed(gold: list[tuple], pred: list[tuple]) -> bool:
    if len(gold) != 1 or len(gold[0]) < 2 or len(pred) != len(gold[0]):
        return False
    width = len(pred[0])
    return any(_columns_match(list(gold[0]), _column(pred, j), False) for j in range(width))


def compare(
    gold_rows: Sequence[Sequence[Any]],
    pred_rows: Sequence[Sequence[Any]],
    *,
    order_matters: bool = False,
) -> Match:
    gold = [tuple(normalize(v) for v in r) for r in gold_rows]
    pred = [tuple(normalize(v) for v in r) for r in pred_rows]
    if len(gold) != len(pred):
        if not order_matters and _transposed(gold, pred):
            return Match(True, "전치 허용: 정답의 열을 행으로 반환", transposed=True)
        return Match(False, f"행 수 불일치 (정답 {len(gold)}, 예측 {len(pred)})")
    if not gold:
        return Match(True)
    n, m = len(gold[0]), len(pred[0])
    if m < n:
        return Match(False, f"컬럼 부족 (정답 {n}, 예측 {m})")

    candidates = [
        [j for j in range(m) if _columns_match(_column(gold, i), _column(pred, j), order_matters)]
        for i in range(n)
    ]
    for i, cands in enumerate(candidates):
        if not cands:
            return Match(False, f"정답 {i + 1}번째 컬럼과 값이 같은 컬럼이 없음")

    def search(i: int, used: tuple[int, ...]) -> bool:
        if i == n:
            projected = [tuple(r[j] for j in used) for r in pred]
            return _rows_match(gold, projected, order_matters)
        return any(search(i + 1, (*used, j)) for j in candidates[i] if j not in used)

    if search(0, ()):
        return Match(True)
    return Match(
        False, "컬럼별 값은 같지만 행 조합이 다름" if not order_matters else "행 순서 불일치"
    )
