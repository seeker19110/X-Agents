"""`keeper.benchmark` — thước đo NGOÀI theo khuôn GAIA (ADR keeper 0003): scorer đúng công thức chính thức, sàn
không được tụt, tín hiệu vào vòng triage. Không ca nào gọi model thật (`FakeClient`); bản ghi thật là việc của
người có key (`benchmarks/gaia/README.md`).
"""
from __future__ import annotations

import json

import pytest
import yaml
from xagents_core.llm import FakeClient

from keeper import benchmark as bm
from keeper.events import Signal
from keeper.risk import risk_tier

TASKS = [
    {"task_id": "t1", "Question": "2 + 2 = ?", "Level": 1, "Final answer": "4", "file_name": ""},
    {"task_id": "t2", "Question": "Thủ đô Việt Nam?", "Level": 1, "Final answer": "Hanoi", "file_name": ""},
    {"task_id": "t3", "Question": "Liệt kê", "Level": 2, "Final answer": "a, b, c", "file_name": "x.xlsx"},
    {"task_id": "t4", "Question": "Giá?", "Level": 3, "Final answer": "1234.5", "file_name": ""},
]


def _jsonl(tmp_path, rows=TASKS):
    p = tmp_path / "metadata.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


# ---------- scorer: đúng công thức chính thức của GAIA ----------

@pytest.mark.parametrize(("answer", "truth", "ok"), [
    ("$1,234.50", "1234.5", True),          # số: bỏ $ % , rồi so float
    ("1234", "1234.5", False),
    ("50%", "50", True),
    ("abc", "4", False),                    # không parse được → inf ≠ 4
    ("Ha Noi", "Hanoi", True),              # chuỗi: bỏ khoảng trắng + dấu câu, thường hoá
    ("Hanoi.", "hanoi", True),
    ("Ha-Long", "Halong", True),
    ("Saigon", "Hanoi", False),
    ("a; b; c", "a, b, c", True),           # danh sách: tách theo , ; từng phần tử
    ("A,b ,C", "a, b, c", True),
    ("a, b", "a, b, c", False),             # lệch số phần tử
    ("1, two", "1.0, two", True),           # phần tử số so float, phần tử chuỗi GIỮ dấu câu
    ("a.b, c", "ab, c", False),
    (None, "4", False),
    ("", "", True),
])
def test_question_scorer_theo_cong_thuc_gaia(answer, truth, ok):
    assert bm.question_scorer(answer, truth) is ok


def test_extract_final_answer_lay_sau_nhan_cuoi_cung():
    text = "Suy nghĩ... FINAL ANSWER: nháp\nrồi sửa.\nFINAL ANSWER: 42 "
    assert bm.extract_final_answer(text) == "42"
    assert bm.extract_final_answer("không có nhãn") is None
    assert bm.extract_final_answer("FINAL ANSWER: [Paris]") == "Paris"


# ---------- nạp bộ đề đúng khuôn metadata.jsonl ----------

def test_load_tasks_doc_truong_cua_gaia_va_loc_level(tmp_path):
    tasks = bm.load_tasks(_jsonl(tmp_path))
    assert [t.task_id for t in tasks] == ["t1", "t2", "t3", "t4"]
    assert tasks[2].has_file and tasks[2].file_name == "x.xlsx" and not tasks[0].has_file
    assert [t.task_id for t in bm.load_tasks(_jsonl(tmp_path), levels={2, 3})] == ["t3", "t4"]
    assert [t.task_id for t in bm.load_tasks(_jsonl(tmp_path), limit=2)] == ["t1", "t2"]


def test_load_tasks_bo_dong_trong_va_bao_loi_thieu_truong(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text('\n{"task_id":"x","Question":"q","Level":1,"Final answer":"a"}\n\n', encoding="utf-8")
    assert [t.task_id for t in bm.load_tasks(p)] == ["x"]
    p.write_text('{"task_id":"x","Question":"q","Level":1}\n', encoding="utf-8")
    with pytest.raises(bm.BenchmarkError, match="Final answer"):
        bm.load_tasks(p)


# ---------- solver bằng model: prompt hệ thống CHÍNH THỨC, trả lời theo schema ----------

def test_model_solver_dung_prompt_gaia_va_doc_final_answer():
    client = FakeClient(responses=[{"reasoning": "2+2", "final_answer": "4"}])
    s = bm.ModelSolver(client, model_tier="standard")
    out = s.solve(bm.GaiaTask.from_row(TASKS[0]))
    assert out.answer == "4" and out.tokens == 1300
    call = client.calls[0]
    assert call["system"] == bm.GAIA_SYSTEM_PROMPT and "FINAL ANSWER" in call["system"]
    assert "2 + 2 = ?" in call["user"] and call["model_tier"] == "standard"


def test_model_solver_roi_ve_nhan_final_answer_trong_reasoning_khi_truong_rong():
    client = FakeClient(responses=[{"reasoning": "... FINAL ANSWER: 4", "final_answer": ""}])
    assert bm.ModelSolver(client).solve(bm.GaiaTask.from_row(TASKS[0])).answer == "4"


def test_model_solver_khong_doc_duoc_file_dinh_kem_thi_noi_ro_trong_prompt():
    client = FakeClient(responses=[{"reasoning": "", "final_answer": "a, b, c"}])
    bm.ModelSolver(client).solve(bm.GaiaTask.from_row(TASKS[2]))
    assert "x.xlsx" in client.calls[0]["user"] and "không đọc được" in client.calls[0]["user"]


# ---------- chạy và chấm ----------

def _solver(answers: dict[str, str]):
    return bm.CallableSolver(lambda t: bm.SolverAnswer(answers.get(t.task_id), tokens=10))


def test_run_cham_tung_de_va_tinh_accuracy_theo_level(tmp_path):
    tasks = bm.load_tasks(_jsonl(tmp_path))
    rep = bm.run(tasks, _solver({"t1": "4", "t2": "Saigon", "t3": "a,b,c", "t4": "$1,234.5"}))
    assert [i.correct for i in rep.items] == [True, False, True, True]
    assert rep.accuracy == pytest.approx(0.75) and rep.total == 4 and rep.tokens == 40
    assert rep.by_level == {1: pytest.approx(0.5), 2: pytest.approx(1.0), 3: pytest.approx(1.0)}
    assert rep.items[2].has_file is True
    assert rep.as_dict()["items"][0] == {"task_id": "t1", "level": 1, "answer": "4", "expected": "4",
                                          "correct": True, "tokens": 10, "has_file": False}


def test_run_rong_khong_phai_100_phan_tram():
    rep = bm.run([], _solver({}))
    assert rep.total == 0 and rep.accuracy is None and rep.by_level == {}


def test_run_solver_nem_loi_thi_de_do_la_sai_va_ghi_ly_do(tmp_path):
    tasks = bm.load_tasks(_jsonl(tmp_path), limit=1)
    def boom(t): raise bm.LLMError("quota")
    rep = bm.run(tasks, bm.CallableSolver(boom))
    assert rep.items[0].correct is False and rep.items[0].answer is None and "quota" in rep.items[0].error
    assert rep.errored == 1
    assert rep.as_dict()["items"][0]["error"].startswith("LLMError: quota")


# ---------- ghi / phát lại ----------

def test_record_roi_replay_cho_cung_ket_qua_khong_goi_model(tmp_path):
    tasks = bm.load_tasks(_jsonl(tmp_path))
    rep = bm.run(tasks, _solver({"t1": "4", "t2": "Hanoi", "t3": "a, b, c", "t4": "1234.5"}))
    rec = tmp_path / "rec.json"
    bm.save_recording(rec, rep, model="fake")
    data = json.loads(rec.read_text(encoding="utf-8"))
    assert data["model"] == "fake" and data["answers"]["t2"] == {"answer": "Hanoi", "tokens": 10}
    again = bm.run(tasks, bm.RecordedSolver(rec))
    assert again.accuracy == 1.0 and again.tokens == rep.tokens


def test_replay_thieu_de_thi_de_do_sai_va_bao_thieu(tmp_path):
    tasks = bm.load_tasks(_jsonl(tmp_path))
    rec = tmp_path / "rec.json"
    rec.write_text(json.dumps({"model": "m", "answers": {"t1": {"answer": "4", "tokens": 1}}}), encoding="utf-8")
    rep = bm.run(tasks, bm.RecordedSolver(rec))
    assert rep.accuracy == 0.25 and rep.missing == ["t2", "t3", "t4"]


def test_recorded_solver_bao_loi_khi_file_khong_co(tmp_path):
    with pytest.raises(bm.BenchmarkError, match="chưa có bản ghi"):
        bm.RecordedSolver(tmp_path / "khong-co.json")


# ---------- sàn: không được tụt; chưa đo thì KHÔNG xanh ----------

def _floor(tmp_path, data):
    p = tmp_path / "floor.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_check_floor_duoi_san_hoac_it_de_hon_la_do(tmp_path):
    tasks = bm.load_tasks(_jsonl(tmp_path))
    rep = bm.run(tasks, _solver({"t1": "4", "t2": "Hanoi"}))  # 0.5
    floor = bm.load_floor(_floor(tmp_path, {"min_accuracy": 0.6, "min_tasks": 4}))
    assert bm.check_floor(rep, floor) == ["accuracy 0.50 < sàn 0.60"]
    floor2 = bm.load_floor(_floor(tmp_path, {"min_accuracy": 0.5, "min_tasks": 5}))
    assert bm.check_floor(rep, floor2) == ["4 đề < sàn 5 đề"]
    assert bm.check_floor(rep, bm.load_floor(_floor(tmp_path, {"min_accuracy": 0.5, "min_tasks": 4}))) == []


def test_check_floor_theo_level(tmp_path):
    tasks = bm.load_tasks(_jsonl(tmp_path))
    rep = bm.run(tasks, _solver({"t1": "4", "t2": "Hanoi", "t3": "sai"}))
    floor = bm.load_floor(_floor(tmp_path, {"min_accuracy": 0.5, "min_tasks": 1, "levels": {2: {"min_accuracy": 1.0}}}))
    assert bm.check_floor(rep, floor) == ["level 2: accuracy 0.00 < sàn 1.00"]
    chua_chay = bm.load_floor(_floor(tmp_path, {"min_accuracy": 0.5, "min_tasks": 1, "levels": {9: {"min_accuracy": 1.0}}}))
    assert bm.check_floor(rep, chua_chay) == [], "level không có đề nào trong lần chạy thì không so"


def test_san_chua_do_thi_khong_xanh(tmp_path):
    rep = bm.run(bm.load_tasks(_jsonl(tmp_path)), _solver({"t1": "4", "t2": "Hanoi", "t3": "a, b, c", "t4": "1234.5"}))
    floor = bm.load_floor(_floor(tmp_path, {"min_accuracy": None, "min_tasks": None, "note": "chưa đo"}))
    assert floor.measured is False
    assert bm.check_floor(rep, floor) == ["sàn chưa đo: điền min_accuracy/min_tasks sau lần --record đầu tiên"]
    assert bm.check_floor(bm.run([], _solver({})), bm.load_floor(_floor(tmp_path, {"min_accuracy": 0.1, "min_tasks": 0}))) \
        == ["không có đề nào — xanh vì rỗng không tính"]


# ---------- tín hiệu vào vòng triage ----------

def test_benchmark_signal_khi_tut_san_va_tier_high(tmp_path):
    rep = bm.run(bm.load_tasks(_jsonl(tmp_path)), _solver({"t1": "4"}))
    floor = bm.load_floor(_floor(tmp_path, {"min_accuracy": 0.5, "min_tasks": 4}))
    sig = bm.benchmark_signal(rep, floor, name="gaia", evidence="benchmarks/gaia/recordings/x.json")
    assert isinstance(sig, Signal) and sig.kind == "benchmark" and sig.subject == "benchmark:gaia"
    assert "0.25" in sig.detail and sig.evidence.endswith("x.json")
    assert risk_tier(sig) == "high"
    ok = bm.run(bm.load_tasks(_jsonl(tmp_path)), _solver({"t1": "4", "t2": "Hanoi", "t3": "a, b, c", "t4": "1234.5"}))
    assert bm.benchmark_signal(ok, floor, name="gaia", evidence="e") is None


# ---------- CLI ----------

def test_cli_record_ghi_file_va_in_bang(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bm, "make_client", lambda: FakeClient(handler=lambda s, u: {"reasoning": "", "final_answer": "4"}))
    rec = tmp_path / "r.json"
    rc = bm.main(["gaia", "--dataset", str(_jsonl(tmp_path)), "--record", str(rec), "--level", "1"])
    out = capsys.readouterr().out
    assert rc == 0 and rec.exists() and "t1" in out and "accuracy 0.50" in out
    assert set(json.loads(rec.read_text(encoding="utf-8"))["answers"]) == {"t1", "t2"}


def test_cli_replay_strict_do_khi_duoi_san_va_xanh_khi_du(tmp_path, capsys):
    tasks = bm.load_tasks(_jsonl(tmp_path))
    rec = tmp_path / "r.json"
    bm.save_recording(rec, bm.run(tasks, _solver({"t1": "4", "t2": "Hanoi"})), model="m")
    floor = _floor(tmp_path, {"min_accuracy": 0.6, "min_tasks": 4})
    assert bm.main(["gaia", "--dataset", str(_jsonl(tmp_path)), "--replay", str(rec), "--strict", "--floor", str(floor)]) == 1
    assert "accuracy 0.50 < sàn 0.60" in capsys.readouterr().out
    floor_ok = _floor(tmp_path, {"min_accuracy": 0.5, "min_tasks": 4})
    assert bm.main(["gaia", "--dataset", str(_jsonl(tmp_path)), "--replay", str(rec), "--strict", "--floor", str(floor_ok)]) == 0
    assert bm.main(["gaia", "--dataset", str(_jsonl(tmp_path)), "--replay", str(rec)]) == 0  # không strict: chỉ báo cáo


def test_cli_chay_duoc_khi_stdout_khong_co_reconfigure(tmp_path, monkeypatch):
    import io
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    rec = tmp_path / "r.json"
    bm.save_recording(rec, bm.run(bm.load_tasks(_jsonl(tmp_path)), _solver({"t1": "4"})), model="m")
    assert bm.main(["gaia", "--dataset", str(_jsonl(tmp_path)), "--replay", str(rec)]) == 0
    assert "accuracy 0.25" in buf.getvalue()


def test_cli_strict_khong_co_san_thi_do(tmp_path, capsys):
    rec = tmp_path / "r.json"
    bm.save_recording(rec, bm.run(bm.load_tasks(_jsonl(tmp_path)), _solver({"t1": "4"})), model="m")
    assert bm.main(["gaia", "--dataset", str(_jsonl(tmp_path)), "--replay", str(rec), "--strict",
                    "--floor", str(tmp_path / "khong-co.yaml")]) == 1
    assert "sàn" in capsys.readouterr().out


def test_cli_khong_dataset_thi_dung_bo_mau_trong_repo(capsys):
    """Bộ mẫu `benchmarks/gaia/sample.jsonl` là để chạy thử KHUÔN, không phải GAIA thật — README nói rõ."""
    rc = bm.main(["gaia", "--replay", str(bm.GAIA_DIR / "recordings" / "khong-co.json")])
    assert rc == 1 and "chưa có bản ghi" in capsys.readouterr().out


# ---------- tài sản trong repo ----------

def test_bo_mau_va_san_trong_repo_dung_khuon():
    tasks = bm.load_tasks(bm.GAIA_DIR / "sample.jsonl")
    assert len(tasks) >= 3 and {t.level for t in tasks} <= {1, 2, 3}
    assert all(t.final_answer for t in tasks)
    floor = bm.load_floor(bm.GAIA_DIR / "floor.yaml")
    assert floor.measured is False, "sàn chỉ được điền sau khi có bản ghi model thật (chờ người)"
    readme = (bm.GAIA_DIR / "README.md").read_text(encoding="utf-8")
    assert "không phải GAIA" in readme and "--record" in readme
