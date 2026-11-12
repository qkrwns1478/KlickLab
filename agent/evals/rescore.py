"""저장된 golden 리포트(JSON)를 LLM 호출 없이 다시 채점한다.

모델이 만든 SQL(리포트의 sql)을 DB에서 다시 실행해 현재 채점기(evals/matching.py)로 비교한다.
채점 규칙을 바꿨을 때 이전 실행의 점수를 같은 기준으로 맞추고, 바뀐 문항을 확인하기 위함이다.
정답은 현재 DB 기준이므로 리포트를 만든 날과 시드 날짜가 같을 때 의미가 있다.

    cd agent
    .venv/Scripts/python -m evals.rescore evals/reports/<리포트>.json [...]
"""

import argparse
import sys
from pathlib import Path

from app.config import Settings
from app.sql.executor import SQLExecutionError
from app.sql.guard import SQLRejected, guard
from evals import datasets, report
from evals.matching import compare
from evals.run_eval import make_executor, run_gold

RESCORABLE = ("match", "mismatch")  # 공급자 오류·SQL 없음·거부·실행 오류는 SQL 로 바뀌지 않는다


def rescore_item(item: dict, saved: dict, executor) -> dict:
    """저장된 문항 하나의 새 판정. 바뀐 값만 담은 dict (없으면 빈 dict)."""
    if saved["status"] not in RESCORABLE or not saved.get("sql"):
        return {}
    gold = run_gold(executor, item["sql"], datasets.DEMO_SDK_KEY)
    try:
        pred = executor.execute(
            guard(saved["sql"], max_rows=1000).sql, datasets.DEMO_SDK_KEY, result_rows=1000
        )
    except (SQLRejected, SQLExecutionError) as e:
        return {"status": "exec_error", "reason": str(e)}
    match = compare(gold.rows, pred.rows, order_matters=bool(item.get("order_matters")))
    status = "match" if match.ok else "mismatch"
    return {
        "status": status,
        "reason": match.reason,
        "transposed": match.transposed,
        "gold_rows": gold.row_count,
        "pred_rows": pred.row_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reports", nargs="+", type=Path, help="golden 리포트 JSON")
    parser.add_argument("--out-dir", type=Path, default=report.REPORTS)
    args = parser.parse_args(argv)

    import json

    golden = {i["id"]: i for i in datasets.load(datasets.GOLDEN)}
    executor = make_executor(Settings())
    lines = ["# golden 재채점 (LLM 호출 없음)", ""]
    payload: dict = {"started_at": report.now_kst().isoformat(timespec="seconds"), "reports": []}
    try:
        for path in args.reports:
            saved = json.loads(path.read_text(encoding="utf-8"))
            changes, rows = [], []
            for it in saved["items"]:
                update = rescore_item(golden[it["id"]], it, executor)
                if update and (update["status"], update["reason"]) != (it["status"], it["reason"]):
                    changes.append((it["id"], it["status"], update))
                rows.append({**it, **update})
            before = sum(i["status"] == "match" for i in saved["items"])
            after = sum(r["status"] == "match" for r in rows)
            evaluated = sum(i["status"] != "llm_error" for i in saved["items"])
            lines += [
                f"## {path.name}",
                "",
                f"- 정답 {before}/{evaluated} → **{after}/{evaluated}** (평가 못 한 문항 "
                f"{len(saved['items']) - evaluated}개 제외)",
            ]
            lines += [
                f"- {i}: {old} → {new['status']}"
                + (" (전치 허용)" if new.get("transposed") else f" — {report.cell(new['reason'])}")
                for i, old, new in changes
            ] or ["- 바뀐 문항 없음"]
            lines.append("")
            payload["reports"].append(
                {"source": path.name, "before": before, "after": after, "items": rows}
            )
    finally:
        executor.close()
    md = report.write("rescore", payload, lines, args.out_dir)
    print("\n".join(lines))
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
