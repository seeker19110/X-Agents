"""ADR-0064: orchestrator tự chạy phép đo NFR (perf/a11y) đã khai, trên môi trường staging ĐÃ deploy.

Lệnh đo là script có sẵn của khách. Người vận hành khai chúng trong `<project>.measure.json` cạnh file env bí mật
(`COMPANY_DEPLOY_ENV_DIR`, ADR-0061), ngoài repo khách. Chọn chỗ này thay vì trường mới trong spec để không đổi schema
và prompt của `product`, và để cùng hàng rào với override compose: file trong repo khách hoặc người khác ghi được
là lỗi cấu hình, vì ai ghi được nó là chạy được lệnh trên máy hub.

Mỗi phép đo: `{base_url}` thay bằng địa chỉ staging đã map; env = `clean_env()` cộng ĐÚNG các biến khai trong `env`, giá
trị lấy từ file env bí mật; mã thoát 0 là đạt. Bằng chứng ghi lệnh đã khai (placeholder), mã thoát, thời gian, đuôi
stdout đã che giá trị bí mật, `verified_by=orchestrator`. Không ném: hỏng là một bản ghi `ok=False`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xagents_core.sandbox import clean_env

from .deploy import ENV_SECRETS_DIR, DeployError, deploy_env_file
from .smoke import VERIFIED_BY, unverified

KINDS = ("perf", "a11y", "other")
DEFAULT_TIMEOUT_S = 900
MAX_TIMEOUT_S = 1800  # một phép đo chặn vòng orchestrator: trần cứng, không để file khai tự nới
TAIL = 1500
_RUN: Any = subprocess.run


@dataclass(frozen=True)
class Measure:
    id: str
    kind: str
    command: tuple[str, ...]
    timeout_s: int = DEFAULT_TIMEOUT_S
    env: tuple[tuple[str, str], ...] = ()  # (tên biến cho lệnh, khoá trong file env bí mật)


def measure_config(repo_root: Path, project: str) -> str:
    """Đường dẫn `<project>.measure.json`, "" khi không đặt thư mục hoặc không có file. Fail-closed như
    `deploy.deploy_override_file`: trong repo khách hoặc nhóm/người khác ghi được thì ném trước khi chạy gì."""
    root = os.environ.get(ENV_SECRETS_DIR, "").strip()
    if not root:
        return ""
    f = (Path(root).expanduser() / f"{project}.measure.json").resolve()
    if not f.is_file():
        return ""
    if f.is_relative_to(repo_root.resolve()):
        raise DeployError(f"{ENV_SECRETS_DIR} phải ở ngoài repo khách (builder ghi/commit được repo): {f.parent}")
    if f.stat().st_mode & 0o022:
        raise DeployError(f"{f} nhóm/người khác ghi được — chmod 600 rồi đo lại (ADR-0064)")
    return str(f)


def load_measures(path: str) -> list[Measure]:
    """Đọc file khai; hình hỏng là lỗi cấu hình (`DeployError`), không đoán lệnh thay người vận hành."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = data["measures"]
        if not isinstance(items, list):
            raise TypeError("measures không phải mảng")
        out = []
        for x in items:
            cmd, env = x["command"], x.get("env") or {}
            if not (isinstance(x["id"], str) and x["id"]) or x["kind"] not in KINDS:
                raise ValueError(f"id rỗng hoặc kind ngoài {KINDS}: {x}")
            if not isinstance(cmd, list) or not cmd or not all(isinstance(t, str) and t for t in cmd):
                raise ValueError(f"command phải là mảng chuỗi khác rỗng: {x['id']}")
            if not isinstance(env, dict):
                raise ValueError(f"env phải là object {{tên biến: khoá file env}}: {x['id']}")
            timeout = max(1, min(int(x.get("timeout_s") or DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S))
            out.append(
                Measure(x["id"], x["kind"], tuple(cmd), timeout, tuple((str(k), str(v)) for k, v in env.items()))
            )
        return out
    except (ValueError, TypeError, KeyError) as e:  # JSONDecodeError là ValueError
        raise DeployError(f"file khai measure hỏng ({path}): {e}") from e


def _env_file(env_file: str) -> dict[str, str]:
    """`KEY=VALUE` của file env bí mật (ADR-0061): bỏ chú thích/dòng rỗng, bỏ nháy."""
    out: dict[str, str] = {}
    for ln in Path(env_file).read_text(encoding="utf-8").splitlines():
        k, sep, v = ln.partition("=")
        if sep and k.strip() and not k.lstrip().startswith("#"):
            out[k.strip()] = v.strip().strip("'\"")
    return out


def _che(s: str, vals: list[str]) -> str:
    for v in vals:
        s = s.replace(v, "***")
    return s


def run_measures(
    repo_root: Path, measures: list[Measure], base_url: str, env_file: str, *, run: Any = _RUN
) -> list[dict[str, Any]]:
    """Chạy từng phép đo trong `repo_root` (worktree tích hợp). Không ném."""
    secrets = _env_file(env_file) if env_file else {}
    out: list[dict[str, Any]] = []
    for m in measures:
        rec: dict[str, Any] = {
            "id": m.id,
            "kind": m.kind,
            "command": list(m.command),
            "base_url": base_url,
            "ok": False,
            "verified_by": VERIFIED_BY,
        }
        missing = [key for _, key in m.env if key not in secrets]
        if missing:
            out.append(
                {
                    **rec,
                    "unverified": True,
                    "reason": f"file env bí mật không có khoá {', '.join(missing)} mà phép đo cần (ADR-0061)",
                }
            )
            continue
        env = {**clean_env(), **{name: secrets[key] for name, key in m.env}}
        vals = sorted({secrets[key] for _, key in m.env if secrets[key]}, key=len, reverse=True)
        argv = [t.replace("{base_url}", base_url) for t in m.command]
        t0 = time.monotonic()
        try:
            r = run(
                argv,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=m.timeout_s,
            )
            rec |= {
                "ok": r.returncode == 0,
                "exit_code": r.returncode,
                "stdout_tail": _che(((r.stdout or "") + (r.stderr or ""))[-TAIL:], vals),
            }
        except subprocess.TimeoutExpired:
            rec["error"] = f"quá {m.timeout_s}s"
        except OSError as e:
            rec["error"] = _che(f"không chạy được: {e.strerror or e}", vals)
        rec["elapsed_s"] = round(time.monotonic() - t0, 2)
        out.append(rec)
    return out


Records = list[dict[str, Any]]  # bằng chứng đo, một bản ghi mỗi phép đo — `orch/` dùng tên này (trần `dict[str, Any]`)


def evidence_for(root: Path, project: str, deployed: dict[str, Any] | None, sha: str) -> Records | None:
    """Bằng chứng đo cho một RC đã deploy staging: None = không khai đo. Lỗi cấu hình hay staging chưa deploy ok (có
    cổng) thành bản ghi `unverified` nói rõ; mọi bản ghi mang `sha` RC."""
    try:
        cfg = measure_config(root, project)
        if not cfg:
            return None
        ms, efile = load_measures(cfg), deploy_env_file(root, project)
    except DeployError as e:
        recs: Records = [{"id": "?", "ok": False, **unverified(str(e)[:300])}]
    else:
        dep = deployed or {}
        if dep.get("ok") and dep.get("port"):
            recs = run_measures(root, ms, f"http://127.0.0.1:{dep['port']}", efile)
        else:
            recs = [{"id": m.id, "kind": m.kind, "ok": False,
                     **unverified("staging chưa deploy ok (có cổng) — không có gì để đo")} for m in ms]
    return [{**r, "sha": sha} for r in recs]


def main(argv: list[str] | None = None) -> int:
    """`python -m company.measure run <release> --repo <repo khách>`: đo lại RC đang chạy trên staging (vd RC lên
    staging trước khi có file khai). Cùng một đường với lượt QA (`verify.measure_run`); audit vào bus thật.
    Mã thoát: 0 mọi phép đo đạt, 1 có phép đo không đạt/không đo được, 2 không có gì để đo."""
    from .llm import FakeClient
    from .orch.verify import measure_run
    from .orchestrator import Orchestrator
    from .sqlite_bus import SQLiteBus

    ap = argparse.ArgumentParser(prog="python -m company.measure")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="đo lại một release đang ở staging")
    r.add_argument("release_id")
    r.add_argument("--repo", type=Path, required=True)
    r.add_argument("--db", type=Path, default=Path("company.sqlite"))
    a = ap.parse_args(argv)
    bus = SQLiteBus(a.db)
    try:
        ev = next((e for e in reversed(list(bus.replay(topic="release-events", key=a.release_id)))
                   if e.payload.get("env") == "staging" and e.payload.get("status") == "deployed"), None)
        if ev is None:
            print(f"{a.release_id}: chưa có release-events staging deployed — không có gì để đo")
            return 2
        recs = measure_run(Orchestrator(bus, FakeClient(), repo=a.repo), ev)
        if recs is None:
            print(f"không có file khai `<project staging>.measure.json` trong {ENV_SECRETS_DIR} (ADR-0064)")
            return 2
        for m in recs:
            kq = "ĐẠT" if m["ok"] else ("KHÔNG ĐO ĐƯỢC" if m.get("unverified") else "KHÔNG ĐẠT")
            print(f"{m['id']} {m.get('kind')} {kq} exit={m.get('exit_code')} {m.get('elapsed_s')}s "
                  f"{m.get('reason') or m.get('error') or (m.get('stdout_tail') or '')[-300:]}")
        return 0 if all(m["ok"] for m in recs) else 1
    finally:
        bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
