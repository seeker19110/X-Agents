# Audit và bản vá bổ sung — 2026-09-27

Căn cứ `main@573f1d9113c48ceceb33bdcfbe142445d6db788e` (#364), worktree riêng
`fix/audit-hardening-20260927`. Môi trường đo: Linux, Python 3.12.14, dependency từ `uv.lock`.
Đây là audit mã nguồn và bản vá theo yêu cầu người dùng; bổ sung báo cáo
[`2026-09-27-audit.md`](2026-09-27-audit.md), không thay kết quả vận hành đã đo ở máy khác.

## Phát hiện và bản sửa

| Mã | Mức | Bằng chứng trước sửa | Thay đổi |
|---|---|---|---|
| H1 | Cao | 10 ca `test_glob_rechecks_resolved_symlink_parent` đọc/liệt kê được file qua symlink thư mục dẫn ra ngoài worktree hoặc vào `.git`/`.aws`, kể cả alias tới `.git` lồng và `.venv` | `_walk()` kiểm lại đường dẫn đã resolve qua `_path()`, dùng cùng ranh giới với đọc file trực tiếp; chỉ dữ liệu giả trong thư mục tạm được dùng để tái hiện |
| H2 | Cao | `test_spawn_kill_stops_real_descendant`: sau `handle.kill()`, tiến trình cháu thật vẫn tạo marker; 2 ca điều phối POSIX/Windows cũng đỏ | `SubprocessSandbox.spawn()` tạo session riêng trên POSIX; handle dừng qua `_kill_tree()` để dùng process group/taskkill giống đường `run()` |
| H3 | Vừa | SQLite thật commit vào WAL, file DB chính không thay đổi, `db_fingerprint()` giữ nguyên | Console theo dõi cả `<db>-wal`; không cần chờ checkpoint mới báo SSE cập nhật |
| H4 | Vừa | 5 kiểu JSON hợp lệ nhưng không phải object trả HTTP 500 và đi tới discovery | Gateway trả 400 `invalid_request_error` trước discovery/gọi model |
| H5 | Vừa | `test_dev_task_typecheck_dung_module[core]` đỏ: script thêm `--ignore-missing-imports` trong khi CI không có | Giữ strict core đúng CI, bốn package khác giữ cờ hiện hữu |
| H6 | Vừa | Lệnh trực tiếp `scripts/dev-task.sh gate all` thoát 126; test Git mode đọc `100644` | Commit mode `100755` và test canh mode executable, không phụ thuộc Windows có biểu diễn quyền POSIX hay không |
| H7 | Thấp | Baseline company: 1 failed, 1969 passed; sandbox test gọi binary `python` với env không PATH, máy này không có `/usr/bin/python` | Dùng `sys.executable`, giữ nguyên môi trường đã lọc của sandbox |

Các test hồi quy được chạy đỏ **trước** bản vá. Tổng 21 ca đỏ có chủ đích cho H1–H6
(10 + 3 + 1 + 5 + 1 + 1); H7 được bắt bởi baseline. Không thay prompt/agent, schema event,
chính sách human gate hay `fail_under`.

Sổ skip của company tăng từ 2 lên 3 vì một điểm skip dành cho quyền tạo symlink không có trên một số máy
Windows. Cả mười biến thể H1 đều chạy thật trên Linux trong phiên này. Không thêm pragma miễn coverage.
README gốc và README package được cập nhật số test cùng bản vá.

## Rà cùng họ lỗi

| Câu hỏi | Chỗ rà | Kết luận trong phạm vi |
|---|---|---|
| Đường dẫn được kiểm sau resolve hay chỉ so chuỗi? | `company.tools._path`, `_walk`; `keeper.patcher.check_path` | Đọc/ghi trực tiếp và keeper đã resolve trước kiểm; tìm kiếm/liệt kê của company thiếu bước này, H1 bổ sung |
| SQLite WAL có làm mất tín hiệu cập nhật? | `xagents_core.sqlite_bus`, `console.server.db_fingerprint`, `console.collect` | Bus bật WAL; fingerprint là điểm làm mất tín hiệu. Collector truy vấn DB thay vì đọc bytes file chính |
| Chỉ kill launcher hay cả cây? | `xagents_core.sandbox._run_tree`, `SubprocessSandbox.spawn`, `ContainerSandbox.run/spawn` | Run đã dừng cây; spawn thiếu, H2 vá. Container có `rm -f` theo tên ở timeout/kill. Đây không phải bảo đảm dừng tiến trình cố ý tự tách session hay container bên ngoài sandbox |
| JSON parse được có chắc là object? | gateway chat handler; `console.server._read_json_body` | Console đã kiểm `dict`; gateway thiếu, H4 bổ sung |
| Cổng local có đúng cổng CI? | `scripts/dev-task.sh`, `.github/workflows/ci.yml` | Core sai cờ, H5 vá; lệnh pytest có coverage cho cả năm package, company có xdist. Test mode Git canh H6 |

Phạm vi rà này không chứng minh mọi đường gọi subprocess hoặc mọi file reader trong repo đều an toàn.
`console.engine._terminate()` vẫn quản lý tiến trình orchestrator trực tiếp; dừng toàn bộ cây công việc của
orchestrator, đặc biệt container do daemon giữ, cần một hợp đồng vòng đời riêng. Không đổi cơ chế đó trong bản vá này.

## Xác minh

Cổng toàn repo hoàn tất với exit 0, `cổng XANH (lint + typecheck + test)`.
Output nguyên văn: [`2026-09-27-audit-hardening-gate.txt`](2026-09-27-audit-hardening-gate.txt).

| Package | Test pass | Coverage | Mypy |
|---|---:|---|---:|
| company | 1980 | 100% dòng + nhánh | 65 file |
| gateway | 274 | 100% dòng | 6 file |
| console | 514 | 100% dòng | 12 file |
| core | 594 | 100% dòng + nhánh | 22 file |
| keeper | 582 | 100% dòng + nhánh | 29 file |
| **Tổng** | **3944** | **Giữ `fail_under=100` cả năm** | **134 file** |

0 failed, 0 skipped. Gateway còn một `RuntimeWarning` có sẵn từ test dùng `runpy` chạy lại
`gateway.manage`; warning không bị ẩn. Ruff sạch ở cả năm package. Đây là kết quả Linux/Python 3.12,
không thay lần chạy matrix Python 3.11/3.13 và Windows của GitHub CI sau khi có PR.

Lệnh đã chạy:

```bash
PYTEST_XDIST_AUTO_NUM_WORKERS=4 scripts/dev-task.sh gate all
```

Giới hạn số worker chỉ điều chỉnh tài nguyên của pytest-xdist; không bỏ test hay thay ngưỡng.
Máy kiểm thử có proxy SOCKS, vì vậy đã cài thêm `socksio==1.0.0` vào venv để HTTPX khởi tạo client trong các
mock test. Không sửa proxy, không gọi Google/provider thật, không thêm dependency này vào repo.

Các phép đã chạy độc lập:

- `company.evals all --selftest`: 59/59; replay strict: 59/59, 6 agent.
- `keeper.evals all --replay --strict`: 21/21, 4 agent có bản ghi.
- `company.subagents check`: khớp nguồn.
- `company.assetscan scan . ../keeper`: 96 + 22 file, 0 lỗi nặng, 0 cảnh báo; budget cũng đạt.
- `keeper.cli drift --repo ../..`: sạch ở bản chưa mở PR này.
- Gitleaks 8.30.1, binary chính thức đã kiểm SHA-256: 759 commit có nội dung được quét, 32,93 MB, không phát hiện secret; clone đã lấy đủ lịch sử (`--is-shallow-repository=false`). Quét staged diff cũng không có phát hiện.
- `uv export --locked --no-hashes --no-dev --all-packages` và `pip-audit --strict`: không có lỗ hổng đã biết.
- Đối chiếu cấu hình: 5 workspace member; cả 5 `fail_under=100`; company/core/keeper đo nhánh;
  gateway/console đo dòng. CI có 17 job con và đủ cả 17 trong `quality.needs`.
- Quy mô company: 6 agent, 45 skill, 19 schema, 14 template, 10 subagent dẫn xuất.

## Những việc chưa thể gọi là hoàn thiện sản phẩm

Báo cáo cũ đã có các bản vá #362/#363: B1, B3, B5, một phần B6, B7 và C1. Không ghi đè kết quả lịch sử của chúng.
Các mục còn lại không được tự đánh dấu xong vì bộ test của phiên này xanh:

- B2/B4: cách hiển thị quyết định reviewer khi cờ tắt và đối chiếu sổ token cần tiếp tục theo kế hoạch cũ;
  phiên này không có bản sao bus CAMPUS-UNI để đo lại.
- S1/S2 và ADR-0023: cô lập quyền OS, runtime container/egress; không đổi lựa chọn triển khai hoặc cấu hình máy vận hành.
- Canary keeper BT8, Docker/deploy thật, RC và nghiệm thu CAMPUS-UNI: chưa chạy ở đây.
- Gateway/console chưa đo branch coverage; không gọi coverage dòng 100% là coverage nhánh 100%.
- Không gọi API/model trả phí để tạo bản eval mới; không chỉnh trạng thái ADR thay người có thẩm quyền.

Bản vá được chuẩn bị trong nhánh riêng. `SECURITY.md` yêu cầu không công khai lỗ hổng chưa được vá;
repo là public, nên chưa đưa phát hiện H1 lên PR/issue công khai trong phiên chuẩn bị này.
