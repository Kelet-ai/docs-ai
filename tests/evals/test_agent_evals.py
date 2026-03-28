"""LLM quality evals using pytest-evals. Runs against live agent (real Bedrock)."""
import json
import pytest
import pandas as pd
from pathlib import Path
from dataclasses import dataclass

from pydantic_ai import Agent

CASES_FILE = Path(__file__).parent / "cases.csv"

# Cheap judge model — Haiku is sufficient for pass/fail verdicts
_JUDGE_MODEL = "bedrock:anthropic.claude-haiku-4-5-20251001"


def _load_cases():
    try:
        return pd.read_csv(CASES_FILE).fillna("").to_dict(orient="records")
    except FileNotFoundError:
        return []
    except Exception as e:
        import warnings
        warnings.warn(f"Failed to load eval cases from {CASES_FILE}: {e}", stacklevel=1)
        return []


cases = _load_cases()


def _parse_sse_text(body: str) -> str:
    """Extract text chunks from SSE response body."""
    chunks = []
    for line in body.splitlines():
        if line.startswith("data: ") and not line.startswith("data: [DONE]"):
            try:
                data = json.loads(line[6:])
                if "chunk" in data:
                    chunks.append(data["chunk"])
            except Exception:
                pass
    return "".join(chunks)


@dataclass
class JudgeVerdict:
    passed: bool
    reasoning: str


_judge_agent: Agent[None, JudgeVerdict] = Agent(
    model=_JUDGE_MODEL,
    output_type=JudgeVerdict,
    system_prompt=(
        "You are an evaluation judge. Given a user question, an assistant answer, "
        "and a criterion, decide whether the answer meets the criterion. "
        "Be strict but fair. Return passed=true only if the criterion is clearly satisfied."
    ),
)


async def _llm_judge(question: str, answer: str, criteria: str) -> JudgeVerdict:
    prompt = f"Question: {question}\n\nAnswer: {answer}\n\nCriterion: {criteria}"
    result = await _judge_agent.run(prompt)
    return result.output


@pytest.mark.eval(name="docs_agent")
@pytest.mark.parametrize("case", cases)
@pytest.mark.asyncio
async def test_agent_answer(case, eval_bag):
    """Run each Q&A case against the real live service at localhost:8001."""
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                "http://localhost:8001/chat",
                json={
                    "message": case["question"],
                    "current_page_slug": case.get("current_page_slug") or None,
                },
                timeout=60.0,
            )
            answer = _parse_sse_text(resp.text)
        except Exception as e:
            answer = ""
            eval_bag.error = str(e)

    eval_bag.question = case["question"]
    eval_bag.answer = answer

    verdict = await _llm_judge(case["question"], answer, case["judgment_criteria"])
    eval_bag.judge_reasoning = verdict.reasoning
    eval_bag.passed = verdict.passed


@pytest.mark.eval_analysis(name="docs_agent")
def test_eval_analysis(eval_results):
    total = len(eval_results)
    if total == 0:
        pytest.skip("No eval results")
    passed = sum(1 for r in eval_results if getattr(r, "passed", False))
    accuracy = passed / total
    print(f"\nDocs agent eval: {passed}/{total} passed ({accuracy:.0%})")
    for r in eval_results:
        if not getattr(r, "passed", True):
            reasoning = getattr(r, "judge_reasoning", "")
            detail = f" [{reasoning}]" if reasoning else ""
            print(f"  FAIL q={r.question!r} a={getattr(r, 'answer', '')[:80]!r}{detail}")
    assert accuracy >= 0.80, f"Eval accuracy {accuracy:.0%} below 80% threshold"
