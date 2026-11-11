from typing import Any

from app.agent.tools import RunState, ToolOutcome, function_schema

NAME = "request_more_budget"

SCHEMA = function_schema(
    NAME,
    "질문이 처음 판단보다 복잡해 예산이 모자랄 때 상위 난이도 예산으로 승격을 요청한다. "
    "한 번만 가능하다.",
    {
        "type": "object",
        "properties": {"reason": {"type": "string", "description": "예산이 더 필요한 이유"}},
        "required": ["reason"],
    },
)


async def request_more_budget(state: RunState, args: dict[str, Any], seq: int) -> ToolOutcome:
    budget = state.budget
    before = budget.difficulty
    if not budget.promote():
        return ToolOutcome.fail("더 이상 예산을 늘릴 수 없다.", charged=False)
    output = {"from": before, "to": budget.difficulty, "reason": str(args.get("reason") or "")}
    return ToolOutcome(
        for_model={"ok": True, "difficulty": budget.difficulty, "remaining": budget.remaining()},
        output=output,
        charged=False,
    )
