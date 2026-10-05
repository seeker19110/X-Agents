"""CLI: `python -m company.orchestrator <lệnh>` (tách khỏi orchestrator.py, ADR-0034).

`main` chỉ parse argv, dựng `Orchestrator`/`SQLiteBus`, và gọi đúng phương thức — mọi hành vi nghiệp vụ nằm ở
`Orchestrator` hoặc các module `orch/` khác. `Orchestrator`/`ReloadRequested`/`_evidence` import LƯỜI bên trong
`main()`: `orchestrator.py` import `main` từ đây ở mức module, nên import ngược lúc nạp module sẽ vòng tròn — lúc
`main()` thật sự CHẠY thì `company.orchestrator` đã nạp xong.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ..runner import artifact_store
from . import cli_cmds

if TYPE_CHECKING:
    from ..orchestrator import StepResult
    from ..sandbox import Sandbox

COMPANY_ROOT = Path(__file__).resolve().parents[3]  # thư mục software-company (như registry.ROOT)
SOURCE_GLOBS = ("src/company/**/*.py", "agents/**/*.md", "skills/**/*.md", "gates/*.md", "llm.yaml")
# Chỉ hai lệnh được bắt đầu một bus mới; mọi lệnh khác trên đường chưa có file là chạy sai thư mục (audit B3).
NEW_BUS_CMDS = frozenset({"run", "publish"})


def source_fingerprint(root: Path | None = None) -> tuple[int, str]:
    """(số file, mô tả file mới nhất) của mọi thứ orchestrator nạp lúc khởi động. So sánh hai lần gọi là biết mã đổi;
    không cần git (worktree có thể đang ở nhánh bất kỳ)."""
    base = root or COMPANY_ROOT
    latest, n, name = 0.0, 0, ""
    for pat in SOURCE_GLOBS:
        for f in base.glob(pat):
            try: m = f.stat().st_mtime
            except OSError: continue
            n += 1
            if m > latest: latest, name = m, f.relative_to(base).as_posix()
    return n, f"{name}@{int(latest)}"


def _fmt(r: StepResult) -> str:
    tail = f"  hoãn: {r.deferred}" if r.deferred else "  " + "; ".join(r.actions)
    return f"{r.topic:<22} {r.key:<14}{tail}"


def _sandbox_for(cmd: str) -> Sandbox | None:
    """ADR-0035: chỉ ba lệnh CHẠY mã của khách (`run` gọi agent kỹ thuật và smoke, `redeploy` chạy lại lượt
    staging, `recheck` dựng lại SBOM/DAST trên cây RC) mới đọc cấu hình sandbox. Các lệnh còn lại là việc của người và của code (status/report/show/
    comment/takeover) — dựng sandbox ở đó chỉ tổ làm `COMPANY_SANDBOX=container` trên máy không có docker ném
    `SandboxError` cho một lệnh không chạy gì. `None` = `Orchestrator` tự dùng `SubprocessSandbox`.

    Fail-closed vẫn nguyên: `run` trên máy khai `container` mà thiếu binary thì ném ngay tại đây, trước khi có
    một lượt agent nào chạy — không bao giờ âm thầm tụt về subprocess."""
    if cmd not in {"run", "redeploy", "recheck"}:
        return None
    from ..llm import load_config
    from ..sandbox import sandbox_from_config
    return sandbox_from_config(load_config())


def _parser() -> argparse.ArgumentParser:
    """Toàn bộ cờ và subcommand. Tách khỏi `main` để đọc được "CLI nhận gì" mà không phải lội qua thân từng lệnh."""
    ap = argparse.ArgumentParser(description="Orchestrator: vòng lặp tự động topic → agent → topic")
    ap.add_argument("--db", type=Path, default=Path("company.sqlite"))
    ap.add_argument("--repo", type=Path, help="git repo của khách: khối kỹ thuật sửa code thật trong worktree ticket/<id>")
    ap.add_argument("--base", default="HEAD", help="nhánh/commit gốc để tạo nhánh tích hợp lần đầu (mặc định HEAD)")
    ap.add_argument("--integration", default="company/integration", help="nhánh tích hợp: ticket rẽ từ đây, merge vào đây")
    ap.add_argument("--quality-trust", type=Path,
                    help="registry khoá công khai của verifier quality contract (ADR gốc 0020/0021), đặt ngoài mọi worktree")
    ap.add_argument("--artifacts", type=Path, help="artifact store của blackboard (mặc định <db>.artifacts/)")
    ap.add_argument("--workers", type=int, default=1, help="số event khác key chạy song song (mặc định 1)")
    ap.add_argument("--web", action="store_true", help="cho researcher tool web_search/fetch_url (mạng ra ngoài)")
    ap.add_argument("--batch-release", action="store_true",
                    help="gom mọi ticket approved của dự án vào một RC khi không còn ticket đang chạy (mặc định: mỗi ticket một RC)")
    ap.add_argument("--deliver", action="store_true",
                    help="ADR-0027: production duyệt + deploy → tag v<version> và fast-forward nhánh release trong repo khách")
    ap.add_argument("--test-author", action="store_true",
                    help="ADR-0028: test-author viết test từ đặc tả TRƯỚC khi assignee viết code; assignee không ghi "
                         "được file test. Thêm một lượt model mỗi ticket. Stack không phân vùng được vùng test thì "
                         "ticket đi đường cũ và PR mang tests_authored_by=assignee")
    ap.add_argument("--push-remote", help="remote của repo khách để push nhánh release + tag sau khi giao (mặc định: không push)")
    ap.add_argument("--release-branch", default="company/release", help="nhánh 'đang chạy production' trong repo khách")
    ap.add_argument("--deliver-pr", action="store_true",
                    help="ADR-0038: sau khi giao và push, mở PR thật nhánh release → nhánh --base trên GitHub của khách "
                         "(cần --deliver, --push-remote trỏ remote GitHub, `gh` đã `auth login`); mở, không merge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rn = sub.add_parser("run"); rn.add_argument("--max-steps", type=int); rn.add_argument("--no-reload", action="store_true",
                                                help="không tự khởi động lại khi mã nguồn đổi (mặc định: có, chỉ ở --watch)")
    rn.add_argument("--watch", type=float,
        help="chạy liên tục, mỗi N giây nạp event mới (gate CLI, publish) rồi xử lý")
    pb = sub.add_parser("publish"); pb.add_argument("topic"); pb.add_argument("file", type=Path)
    pb.add_argument("--actor", required=True); pb.add_argument("--key")
    dc = sub.add_parser("decide-change", help="khách quyết định change request (sau khi delivery-lead ước lượng impact)")
    dc.add_argument("change_id"); dc.add_argument("decision", choices=["accepted", "rejected", "deferred"])
    dc.add_argument("--by", required=True); dc.add_argument("--reason", default="")
    cm = sub.add_parser("comment", help="người nhận xét ticket đang chạy: phát lại task với hint, không tính retry")
    cm.add_argument("ticket_id"); cm.add_argument("--by", required=True); cm.add_argument("--text", required=True)
    tk = sub.add_parser("takeover", help="người đã sửa tay trong worktree ticket: chạy lint/test, commit, publish PR dưới tên người")
    tk.add_argument("ticket_id"); tk.add_argument("--by", required=True); tk.add_argument("--message")
    rd = sub.add_parser("redeploy", help="chạy lại lượt staging cho một release-candidate đang kẹt (sau khi sửa lỗi hạ tầng)")
    rd.add_argument("release_id"); rd.add_argument("--by", required=True)
    rk = sub.add_parser("recheck", help="ADR-0047: chấm lại release-check của security cho một RC với bằng chứng "
                                        "máy dựng mới (SBOM/license/DAST); giữ waiver đã có")
    rk.add_argument("release_id"); rk.add_argument("--by", required=True, help="human:<tên> hoặc reviewer:<id>")
    bk = sub.add_parser("backup", help="sao lưu nhất quán company.sqlite đang chạy, gồm cả WAL")
    bk.add_argument("--out", type=Path, required=True, help="file đích mới; không ghi đè bản sao lưu cũ")
    sub.add_parser("status"); sub.add_parser("report", help="sprint report: estimate vs actual, chi phí, hành động supervisor")
    ru = sub.add_parser("rulings", help="sổ Ruling (ADR-0030): quyết định agent tự đưa ra thay vì chờ người, kèm 'sai thì mất gì'")
    ru.add_argument("--project"); ru.add_argument("--ticket")
    dg = sub.add_parser("diagnose", help="chẩn đoán: gom lỗi thô thành khuôn lặp lại, ticket quay vòng, gate chờ quyết")
    dg.add_argument("--top", type=int, default=10, help="số khuôn lỗi in ra (mặc định 10)")
    tr = sub.add_parser("trace", help="dòng thời gian một ticket/REL-xxx/dự án từ intake tới deploy: agent, tier/model, token/USD, tool, gate, chờ, retry")
    tr.add_argument("subject"); tr.add_argument("--json", action="store_true", help="in JSON thay vì bảng chữ")
    mt = sub.add_parser("metrics", help="metrics từ audit-log: gọi/token/USD/thời gian theo agent, model, ticket; gate chờ")
    mt.add_argument("--prometheus", action="store_true", help="xuất text exposition format cho Prometheus")
    sh = sub.add_parser("show", help="in toàn văn artifact mới nhất của một namespace blackboard"); sh.add_argument("namespace")
    sh.add_argument("--project", help="dự án của artifact (ADR-0018); bỏ qua nếu chỉ có một dự án dùng namespace đó")
    return ap


def main(argv: list[str] | None = None) -> int:
    """python -m company.orchestrator run [--db] [--max-steps N] [--watch GIÂY] [--workers N] [--web]
       python -m company.orchestrator publish <topic> <file.json> --actor human:po [--key K]
       python -m company.orchestrator decide-change <change_id> accepted|rejected|deferred --by human:po
       python -m company.orchestrator comment <ticket> --by human:x --text "..."   # hint giữa vòng, không tính retry
       python -m company.orchestrator takeover <ticket> --by human:x [--message]   # người sửa tay trong worktree rồi giao lại
       python -m company.orchestrator status | report | metrics [--prometheus] | show <namespace> [--db]
       python -m company.orchestrator trace <TICKET|REL-xxx|PROJECT> [--json]   # dòng thời gian intake → deploy"""

    ns = _parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows console cp1252
        if hasattr(stream, "reconfigure"): stream.reconfigure(encoding="utf-8")
    from ..sqlite_bus import SQLiteBus, missing_bus
    if ns.cmd not in NEW_BUS_CMDS and (loi := missing_bus(ns.db)):
        print(loi, file=sys.stderr); return 2
    if (file_cmd := cli_cmds.FILE_CMDS.get(ns.cmd)) is not None:
        return file_cmd(ns.db, ns)
    bus = SQLiteBus(ns.db)
    # Ba nhóm lệnh, ranh giới là chỗ dựng `Orchestrator` (đắt: `run`/`redeploy` cần client thật). Nhóm bus chạy
    # TRƯỚC nên `metrics`/`trace`/`publish` trên file bus của máy khác không đòi SDK hay API key.
    if (bus_cmd := cli_cmds.BUS_CMDS.get(ns.cmd)) is not None:
        return bus_cmd(bus, ns)
    from ..llm import FakeClient, make_client
    from ..orchestrator import Orchestrator
    # `run`, `redeploy`, `recheck` GỌI MODEL (lượt staging của release-engineer, lượt security) nên cần client thật;
    # status/report/show/comment/takeover là việc của người và của code, không được đòi SDK/API key.
    # Thiếu `redeploy` ở đây thì lệnh chạy bằng FakeClient và chết "FakeClient hết câu trả lời" — đo được 2026-09-06.
    orch = Orchestrator(bus, make_client() if ns.cmd in {"run", "redeploy", "recheck"} else FakeClient(), repo=ns.repo, base=ns.base,
                        integration=ns.integration, workers=ns.workers,
                        web=ns.web, batch_releases=ns.batch_release, artifacts=ns.artifacts or artifact_store(ns.db),
                        deliver=ns.deliver, push_remote=ns.push_remote, release_branch=ns.release_branch,
                        test_author=ns.test_author, sandbox=_sandbox_for(ns.cmd), deliver_pr=ns.deliver_pr,
                        quality_trust=ns.quality_trust)
    return cli_cmds.ORCH_CMDS[ns.cmd](orch, ns)


def _reexec(argv: list[str]) -> None:  # tách ra để test thay được; execv không trở về
    os.execv(argv[0], argv)

