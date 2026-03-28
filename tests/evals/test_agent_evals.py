"""LLM quality evals using pytest-evals. Runs against live agent (real Bedrock)."""
import json
import pytest
import pandas as pd
from pathlib import Path

CASES_FILE = Path(__file__).parent / "cases.csv"


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


def _check_must_contain(answer: str, case: dict) -> bool:
    must = str(case.get("must_contain", "")).strip()
    if not must:
        return True
    # Support "a|b" for OR matching
    alts = [a.strip().lower() for a in must.split("|")]
    return any(a in answer.lower() for a in alts if a)


def _check_must_not_contain(answer: str, case: dict) -> bool:
    must_not = str(case.get("must_not_contain", "")).strip()
    if not must_not:
        return True
    return must_not.lower() not in answer.lower()


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
        eval_bag.contains_ok = _check_must_contain(answer, case)
        eval_bag.not_contains_ok = _check_must_not_contain(answer, case)
        eval_bag.passed = eval_bag.contains_ok and eval_bag.not_contains_ok


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
            print(f"  FAIL q={r.question!r} a={getattr(r, 'answer', '')[:80]!r}")
    assert accuracy >= 0.80, f"Eval accuracy {accuracy:.0%} below 80% threshold"
