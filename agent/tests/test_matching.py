from evals.matching import compare


def test_ignores_column_names_order_and_extra_columns():
    gold = [["naver", 100], ["direct", 50]]
    pred = [[50, "direct", 0.5], [100, "naver", 1.0]]
    assert compare(gold, pred).ok


def test_tolerates_rounding():
    assert compare([[18.40521564694082]], [[18.41]]).ok
    assert not compare([[18.4]], [[19.0]]).ok


def test_null_equals_zero():
    assert compare([["kakao", None]], [["kakao", 0]]).ok


def test_midnight_timestamp_equals_date():
    assert compare([["2026-11-02", 3]], [["2026-11-02T00:00:00+09:00", 3]]).ok


def test_row_count_mismatch():
    result = compare([[1], [2]], [[1]])
    assert not result.ok
    assert "행 수" in result.reason


def test_missing_column():
    assert not compare([["a", 1]], [["a"]]).ok


def test_order_matters_only_when_requested():
    gold = [["/", 10], ["/cart", 5]]
    pred = [["/cart", 5], ["/", 10]]
    assert compare(gold, pred).ok
    assert not compare(gold, pred, order_matters=True).ok


def test_column_values_match_but_rows_are_paired_differently():
    gold = [["a", 1], ["b", 2]]
    pred = [["a", 2], ["b", 1]]
    assert not compare(gold, pred).ok


def test_ambiguous_candidates_are_resolved_by_search():
    # 두 숫자 컬럼이 같은 값 집합이라 첫 번째 후보가 틀릴 수 있다
    gold = [[1, 2], [2, 1]]
    pred = [[2, 1], [1, 2]]
    assert compare(gold, pred).ok


def test_empty_results_match():
    assert compare([], []).ok
