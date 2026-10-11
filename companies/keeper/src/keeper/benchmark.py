"""Thước đo NGOÀI cho `keeper` theo khuôn GAIA (ADR keeper 0003).

Bốn bộ ca `evals/*.yaml` chấm phán xét của agent bằng tiêu chí do chính repo đặt — thước tự làm, không so được
với ai. GAIA (Mialon et al. 2023, `gaia-benchmark/GAIA` trên Hugging Face) cho ba thứ thước nội bộ không có:
khuôn đề thống nhất (`metadata.jsonl`: `task_id`, `Question`, `Level` 1–3, `Final answer`, `file_name`), **công
thức chấm chính thức** (`question_scorer` dưới đây chép đúng từ scorer của leaderboard GAIA: số so float sau khi bỏ
`$ % ,`; danh sách tách theo `,`/`;` rồi so từng phần tử; chuỗi bỏ khoảng trắng + dấu câu, thường hoá), và một
bảng điểm công khai để biết mình đứng đâu (OWL/Workforce của CAMEL-AI báo 69,09–69,70 % trên validation).

Ba luật của module, cùng tinh thần `evals.py`:

1. **Không gọi model trong CI.** `--record` chạy model thật và ghi `recordings/<tên>.json`; `--replay` chấm lại
   từ bản ghi, không chạm mạng. Test dùng `FakeClient`.
2. **Sàn không được tụt** (`floor.yaml`, như `evals/thresholds.yaml`): `--strict` đỏ khi accuracy dưới sàn, số đề
   ít hơn sàn, hoặc sàn CHƯA ĐO — "chưa đo" không phải "đạt". Bộ rỗng cũng không đạt (số xanh vì rỗng, `TRAPS.md`).
3. **Tụt sàn là tín hiệu, không phải log.** `benchmark_signal()` phát `Signal(kind="benchmark")` → `triager` →
   ticket tier `high` (`risk.RISK_RULES` hàng `benchmark-regression`) chờ người: keeper không có patch nào sửa được
   điểm benchmark, nó chỉ bảo đảm điểm tụt thì có người biết.

Giới hạn cố ý: solver ở đây không có tool (đọc file đính kèm, web) — đề có `file_name` được nói rõ trong prompt là
không đọc được, và kết quả không so được với các hệ có tool. Đây là thước cho PROMPT + MODEL của keeper, không
phải một agent GAIA. Bộ mẫu `benchmarks/gaia/sample.jsonl` chỉ để chạy thử khuôn; GAIA thật phải tải từ Hugging
Face (dataset gated) — xem `benchmarks/gaia/README.md`.
"""
from __future__ import annotations

import argparse
import json
import re
import string
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from .core import CORE
from .events import Signal
from .llm import LLMError, ModelClient, make_client

__all__ = ["GAIA_DIR", "GAIA_SYSTEM_PROMPT", "BenchmarkError", "CallableSolver", "Floor", "GaiaTask",
           "ModelSolver", "RecordedSolver", "Report", "SolverAnswer", "benchmark_signal", "check_floor",
           "extract_final_answer", "load_floor", "load_tasks", "main", "question_scorer", "run", "save_recording"]

GAIA_DIR = CORE.root / "benchmarks" / "gaia"
DEFAULT_DATASET = GAIA_DIR / "sample.jsonl"
DEFAULT_FLOOR = GAIA_DIR / "floor.yaml"

# Prompt hệ thống CHÍNH THỨC của GAIA (phụ lục bài báo, cũng là prompt leaderboard dùng để so công bằng). Giữ
# nguyên văn tiếng Anh: đổi một chữ là điểm không còn so được với bảng công khai.
GAIA_SYSTEM_PROMPT = (
    "You are a general AI assistant. I will ask you a question. Report your thoughts, and finish your answer with "
    "the following template: FINAL ANSWER: [YOUR FINAL ANSWER]. YOUR FINAL ANSWER should be a number OR as few "
    "words as possible OR a comma separated list of numbers and/or strings. If you are asked for a number, don't "
    "use comma to write your number neither use units such as $ or percent sign unless specified otherwise. If you "
    "are asked for a string, don't use articles, neither abbreviations (e.g. for cities), and write the digits in "
    "plain text unless specified otherwise. If you are asked for a comma separated list, apply the above rules "
    "depending of whether the element to be put in the list is a number or a string."
)
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {"reasoning": {"type": "string"}, "final_answer": {"type": "string"}},
    "required": ["reasoning", "final_answer"],
}
_FINAL_RE = re.compile(r"FINAL ANSWER:\s*(.+?)\s*$", re.MULTILINE)


class BenchmarkError(Exception): ...


# ---------- scorer: chép đúng công thức chính thức ----------

def _is_float(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


def _normalize_number_str(s: str) -> float:
    for ch in ("$", "%", ","):
        s = s.replace(ch, "")
    try:
        return float(s)
    except ValueError:
        return float("inf")


def _split(s: str) -> list[str]:
    return re.split(r"[,;]", s)


def _normalize_str(s: str, remove_punct: bool = True) -> str:
    no_spaces = re.sub(r"\s", "", s)
    if remove_punct:
        return no_spaces.lower().translate(str.maketrans("", "", string.punctuation))
    return no_spaces.lower()


def question_scorer(model_answer: str | None, ground_truth: str) -> bool:
    """`question_scorer` của leaderboard GAIA, nguyên công thức. `None` (không trả lời) luôn sai."""
    if model_answer is None:
        return False
    if _is_float(ground_truth):
        return _normalize_number_str(model_answer) == float(ground_truth)
    if any(ch in ground_truth for ch in (",", ";")):
        gt, ma = _split(ground_truth), _split(model_answer)
        if len(gt) != len(ma):
            return False
        return all(_normalize_number_str(m) == float(g) if _is_float(g)
                   else _normalize_str(m, remove_punct=False) == _normalize_str(g, remove_punct=False)
                   for m, g in zip(ma, gt, strict=True))
    return _normalize_str(model_answer) == _normalize_str(ground_truth)


def extract_final_answer(text: str) -> str | None:
    """Phần sau nhãn `FINAL ANSWER:` CUỐI CÙNG (model hay nháp rồi sửa); bỏ ngoặc vuông của mẫu `[YOUR FINAL ANSWER]`."""
    hits = _FINAL_RE.findall(text)
    if not hits:
        return None
    return hits[-1].strip().strip("[]").strip()


# ---------- đề và báo cáo ----------

@dataclass(frozen=True)
class GaiaTask:
    task_id: str
    question: str
    level: int
    final_answer: str
    file_name: str = ""

    @property
    def has_file(self) -> bool:
        return bool(self.file_name)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> GaiaTask:
        try:
            return cls(task_id=str(row["task_id"]), question=str(row["Question"]), level=int(row["Level"]),
                       final_answer=str(row["Final answer"]), file_name=str(row.get("file_name") or ""))
        except KeyError as e:
            raise BenchmarkError(f"dòng thiếu trường {e} (khuôn metadata.jsonl của GAIA)") from e


def load_tasks(path: Path, levels: set[int] | None = None, limit: int | None = None) -> list[GaiaTask]:
    """Đọc `metadata.jsonl` (một JSON mỗi dòng, dòng trống bỏ qua); lọc theo `levels`, cắt `limit` đề đầu."""
    out: list[GaiaTask] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        t = GaiaTask.from_row(json.loads(line))
        if levels is None or t.level in levels:
            out.append(t)
    return out[:limit] if limit is not None else out


@dataclass(frozen=True)
class SolverAnswer:
    answer: str | None
    tokens: int = 0


class Solver(Protocol):
    def solve(self, task: GaiaTask) -> SolverAnswer: ...  # một dòng: `def` chạy lúc dựng lớp nên không cần pragma


@dataclass
class CallableSolver:
    fn: Callable[[GaiaTask], SolverAnswer]

    def solve(self, task: GaiaTask) -> SolverAnswer:
        return self.fn(task)


@dataclass
class ModelSolver:
    """Hỏi model một lượt theo prompt chính thức; không tool. Trả lời theo `ANSWER_SCHEMA`; `final_answer` rỗng
    thì rơi về nhãn `FINAL ANSWER:` trong `reasoning` (model quen mẫu văn bản của GAIA hơn mẫu JSON)."""
    client: ModelClient
    model_tier: str = "standard"

    def solve(self, task: GaiaTask) -> SolverAnswer:
        user = f"Question: {task.question}"
        if task.has_file:
            user += (f"\n\nĐề này kèm file `{task.file_name}` nhưng phiên này không đọc được file đính kèm "
                     "(solver không có tool); trả lời tốt nhất có thể và nói rõ trong reasoning nếu thiếu dữ liệu.")
        c = self.client.complete(system=GAIA_SYSTEM_PROMPT, user=user, schema=ANSWER_SCHEMA, model_tier=self.model_tier)
        data = c.json()
        ans = str(data.get("final_answer") or "").strip() or extract_final_answer(str(data.get("reasoning") or ""))
        return SolverAnswer(answer=ans or None, tokens=c.tokens)


class RecordedSolver:
    """Phát lại từ `recordings/<tên>.json`; đề không có trong bản ghi → không trả lời (sai), ghi vào `missing`."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            raise BenchmarkError(f"chưa có bản ghi {self.path} — chạy `python -m keeper.benchmark gaia --record {self.path}`")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.model = str(data.get("model", ""))
        self.answers: dict[str, dict[str, Any]] = dict(data.get("answers", {}))
        self.missing: list[str] = []

    def solve(self, task: GaiaTask) -> SolverAnswer:
        rec = self.answers.get(task.task_id)
        if rec is None:
            self.missing.append(task.task_id)
            return SolverAnswer(answer=None)
        return SolverAnswer(answer=rec.get("answer"), tokens=int(rec.get("tokens") or 0))


@dataclass(frozen=True)
class Item:
    task_id: str
    level: int
    answer: str | None
    expected: str
    correct: bool
    tokens: int
    has_file: bool
    error: str | None = None


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def accuracy(self) -> float | None:
        """`None` khi không có đề — không phải 0.0 và càng không phải 1.0 (số xanh vì rỗng)."""
        return sum(i.correct for i in self.items) / self.total if self.items else None

    @property
    def by_level(self) -> dict[int, float]:
        levels = sorted({i.level for i in self.items})
        return {lv: sum(i.correct for i in self.items if i.level == lv) / sum(1 for i in self.items if i.level == lv)
                for lv in levels}

    @property
    def tokens(self) -> int:
        return sum(i.tokens for i in self.items)

    @property
    def errored(self) -> int:
        return sum(1 for i in self.items if i.error)

    def as_dict(self) -> dict[str, Any]:
        items = []
        for i in self.items:
            d = asdict(i)
            if d["error"] is None:
                d.pop("error")
            items.append(d)
        return {"total": self.total, "accuracy": self.accuracy, "by_level": self.by_level, "tokens": self.tokens,
                "errored": self.errored, "missing": list(self.missing), "items": items}


def run(tasks: list[GaiaTask], solver: Solver) -> Report:
    """Chấm từng đề; solver ném lỗi model thì đề đó sai kèm lý do, không dừng cả bộ."""
    rep = Report()
    for t in tasks:
        err = None
        try:
            a = solver.solve(t)
        except (LLMError, BenchmarkError) as e:
            a, err = SolverAnswer(answer=None), f"{type(e).__name__}: {e}"[:300]
        rep.items.append(Item(task_id=t.task_id, level=t.level, answer=a.answer, expected=t.final_answer,
                              correct=question_scorer(a.answer, t.final_answer), tokens=a.tokens,
                              has_file=t.has_file, error=err))
    if isinstance(solver, RecordedSolver):
        rep.missing = list(solver.missing)
    return rep


def save_recording(path: Path, report: Report, *, model: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = {"model": model, "answers": {i.task_id: {"answer": i.answer, "tokens": i.tokens} for i in report.items}}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------- sàn ----------

@dataclass(frozen=True)
class Floor:
    min_accuracy: float | None = None
    min_tasks: int | None = None
    levels: dict[int, float] = field(default_factory=dict)

    @property
    def measured(self) -> bool:
        return self.min_accuracy is not None and self.min_tasks is not None


def load_floor(path: Path) -> Floor:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    acc, n = data.get("min_accuracy"), data.get("min_tasks")
    levels = {int(k): float(v["min_accuracy"]) for k, v in (data.get("levels") or {}).items()
              if (v or {}).get("min_accuracy") is not None}
    return Floor(min_accuracy=float(acc) if acc is not None else None, min_tasks=int(n) if n is not None else None,
                 levels=levels)


def check_floor(report: Report, floor: Floor) -> list[str]:
    """Danh sách lý do đỏ; rỗng = đạt. Chưa đo và bộ rỗng đều là lý do."""
    if not floor.measured:
        return ["sàn chưa đo: điền min_accuracy/min_tasks sau lần --record đầu tiên"]
    if report.accuracy is None:
        return ["không có đề nào — xanh vì rỗng không tính"]
    out = []
    if report.accuracy < float(floor.min_accuracy or 0):
        out.append(f"accuracy {report.accuracy:.2f} < sàn {floor.min_accuracy:.2f}")
    if report.total < int(floor.min_tasks or 0):
        out.append(f"{report.total} đề < sàn {floor.min_tasks} đề")
    for lv, want in sorted(floor.levels.items()):
        got = report.by_level.get(lv)
        if got is not None and got < want:
            out.append(f"level {lv}: accuracy {got:.2f} < sàn {want:.2f}")
    return out


def benchmark_signal(report: Report, floor: Floor, *, name: str, evidence: str) -> Signal | None:
    """Tụt sàn → một `Signal` cho `triager` (tier `high`, chờ người); đạt → `None`."""
    why = check_floor(report, floor)
    if not why:
        return None
    acc = "n/a" if report.accuracy is None else f"{report.accuracy:.2f}"
    return Signal(subject=f"benchmark:{name}", kind="benchmark", evidence=evidence,
                  detail=f"benchmark {name}: accuracy {acc} trên {report.total} đề; " + "; ".join(why))


# ---------- CLI ----------

def _print(report: Report, name: str) -> None:
    for i in report.items:
        mark = "✓" if i.correct else "✗"
        extra = f"  ({i.error})" if i.error else ""
        print(f"{mark} {i.task_id}  L{i.level}  {i.answer!r} / {i.expected!r}{extra}")
    acc = "n/a" if report.accuracy is None else f"{report.accuracy:.2f}"
    lv = ", ".join(f"L{k}={v:.2f}" for k, v in report.by_level.items())
    print(f"{name}: accuracy {acc} trên {report.total} đề  [{lv}]  token={report.tokens}  lỗi={report.errored}"
          + (f"  thiếu bản ghi={len(report.missing)}" if report.missing else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Thước đo ngoài theo khuôn GAIA: model thật (--record) hoặc phát lại (--replay)")
    ap.add_argument("name", choices=["gaia"], help="bộ đề (hiện chỉ `gaia`)")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, metavar="JSONL",
                    help=f"metadata.jsonl theo khuôn GAIA; mặc định bộ mẫu {DEFAULT_DATASET.name} (KHÔNG phải GAIA thật)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", type=Path, metavar="JSON", help="gọi model thật rồi ghi câu trả lời vào file này")
    mode.add_argument("--replay", type=Path, metavar="JSON", help="chấm lại từ bản ghi, không gọi model")
    ap.add_argument("--level", default=None, help="chỉ các level, ví dụ `1` hay `1,2`")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tier", default="standard", help="model_tier cho --record")
    ap.add_argument("--floor", type=Path, default=DEFAULT_FLOOR, metavar="YAML")
    ap.add_argument("--strict", action="store_true", help="đỏ khi dưới sàn, ít đề hơn sàn, hoặc sàn chưa đo")
    ns = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    levels = {int(x) for x in str(ns.level).split(",")} if ns.level else None
    tasks = load_tasks(ns.dataset, levels=levels, limit=ns.limit)
    try:
        solver: Solver
        if ns.replay is not None:
            solver = RecordedSolver(ns.replay)
            rep = run(tasks, solver)
        else:
            client = make_client()
            rep = run(tasks, ModelSolver(client, model_tier=ns.tier))
            save_recording(ns.record, rep, model=type(client).__name__)
    except BenchmarkError as e:
        print(f"FAIL {ns.name}: {e}")
        return 1
    _print(rep, ns.name)
    if not ns.strict:
        return 0
    if not ns.floor.exists():
        print(f"FAIL {ns.name}: không có file sàn {ns.floor}")
        return 1
    why = check_floor(rep, load_floor(ns.floor))
    for w in why:
        print(f"FAIL {ns.name}: {w}")
    return 1 if why else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
