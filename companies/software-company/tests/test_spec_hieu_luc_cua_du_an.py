"""Smoke/deploy/DAST của release chạy theo spec ĐÃ DUYỆT mới nhất của dự án — kể cả spec của change request đổi
requirement — không theo spec gốc chỉ vì nó mang key = project_id.

Hub thật 2026-10-14 (QLKH-DD-CSV): CR-DDCSV-INFRA-002 đổi runtime (thêm `runtime.deploy: docker-compose.yml`, image db
dẫn xuất build cục bộ) và spec của nó được duyệt ở gate `SPEC-CR-DDCSV-INFRA-002`. Nhưng `orch/verify.py` lấy
`approved-specs` key = project_id — spec gốc 2026-10-12, không có deploy — nên release của CR sẽ smoke trần bằng
runtime cũ: PostgreSQL không ai dựng, RC `failed` dù sản phẩm đúng spec mới.

Luật: spec hiệu lực của dự án = bản mới nhất trong các chuỗi `approved-specs` của dự án có gate `SPEC-<key>` đã duyệt;
chưa chuỗi nào duyệt (dự án cũ, test) thì như trước — bản key = project_id.
"""

from __future__ import annotations

from company.events import Envelope
from company.gates import GateRequest
from company.orch.verify import project_spec
from test_smoke_evidence import SERVER_DIE, _orch, _repo, _staging

RT_CR = {"command": "python serve.py", "port": 0, "timeout_s": 2, "deploy": "docker-compose.yml"}


def _spec_cr(bus, orch, *, duyet: bool):
    bus.publish(
        Envelope(
            topic="approved-specs",
            key="CR-1",
            actor="product",
            payload={
                "project_id": "P",
                "change_id": "CR-1",
                "status": "approved",
                "kind": "application",
                "runtime": RT_CR,
                "artifacts": {"prd": "prd", "requirements": "req"},
            },
        )
    )
    orch.gate.request(GateRequest(kind="spec", subject_id="SPEC-CR-1", created_by="product", checklist=["prd"]))
    if duyet:
        orch.gate.decide("SPEC-CR-1", "approve", by="human:po", reason="spec CR đổi runtime sang compose")


def test_release_smoke_theo_runtime_cua_spec_cr_da_duyet(tmp_path):
    repo = _repo(tmp_path, SERVER_DIE)
    bus, orch = _orch(tmp_path, repo, {"command": "python serve.py", "port": 0, "timeout_s": 2})
    _spec_cr(bus, orch, duyet=True)
    orch.run()
    st = _staging(bus)
    assert st and st[-1]["status"] == "deployed", "runtime của spec CR khai deploy — không smoke trần runtime cũ"
    assert "runtime.deploy" in st[-1]["smoke"]["reason"]


def test_spec_cr_chua_duyet_khong_thay_spec_du_an(tmp_path):
    bus, orch = _orch(tmp_path, None, {"command": "python serve.py", "port": 0, "timeout_s": 2})
    _spec_cr(bus, orch, duyet=False)
    assert project_spec(orch, "P").key == "P", "spec CR chưa qua gate không có hiệu lực"
    orch.gate.decide("SPEC-CR-1", "approve", by="human:po", reason="spec CR đổi runtime sang compose")
    assert project_spec(orch, "P").key == "CR-1"
    assert project_spec(orch, "KHAC") is None
