# Đóng góp vào X-Agents

Agent (Claude Code, Codex…) đọc [`AGENTS.md`](AGENTS.md) và [`TRAPS.md`](TRAPS.md) trước; muốn đổi X sửa ở đâu: [`CODEMAP.md`](CODEMAP.md).
Quy trình Git (nhánh, commit, PR, merge) nằm ở [`docs/QUY-TRINH-GIT.md`](docs/QUY-TRINH-GIT.md) — file này
không lặp lại, chỉ nói những thứ riêng của repo: chạy ở đâu, cổng CI nào chặn cái gì, và sửa agent thì phải
chạy lại những gì.

## 1. Cài đặt

Cần Python 3.11+ và [`uv`](https://docs.astral.sh/uv/).

Cả repo là **một project** (uv workspace): `pyproject.toml` + `uv.lock` duy nhất ở gốc, năm thư mục là năm package
thành viên, một `.venv` chung. Cài một lần ở gốc:

```bash
uv sync
```

| Thư mục | Package | Ghi chú |
| --- | --- | --- |
| `companies/software-company/` | `company` | công ty gia công phần mềm |
| `platform/gateway/` | `gateway` | proxy xoay vòng tài khoản Google Antigravity |
| `platform/console/` | `console` | trực ban hợp nhất, phụ thuộc software-company qua workspace |
| `companies/keeper/` | `keeper` | công ty bảo trì |
| `platform/xagents-core/` | `xagents_core` | lõi chung |

Mỗi thư mục vẫn có `Makefile` riêng cho các lệnh của package đó; `uv run` trong thư mục con dùng `.venv` ở gốc.
Thêm/đổi phụ thuộc: sửa `pyproject.toml` của package liên quan rồi `uv lock` ở gốc (một lock cho cả năm).
Không có `[project.scripts]`: mọi entry point đều là `python -m <package>.<module>`.

## 2. Cổng chất lượng

Chạy trước khi push — **một lệnh** ở gốc, cho gói đã sửa hoặc cả năm:

```bash
scripts/dev-task.sh gate <gói>    # gói: company | gateway | console | core | keeper | all (bỏ trống = all)
```

Script giữ lệnh khớp đúng `ci.yml` (`ruff check src tests` → `mypy src/<module>` → `pytest -q --cov`, riêng
software-company thêm `-n auto`), nên không phải nhớ biến thể của từng package; `DEV_TASK_DRY_RUN=1` in lệnh mà
không chạy. Claude Code còn chạy nó tự động trước mỗi commit cho gói bị đụng (`.claude/hooks/pre-commit-gate.sh`).
`make lint && make test` ở gốc vẫn dùng được, nhưng `make test` **không** đo coverage — xanh ở đó chưa chắc xanh CI.

Mỗi package có `Makefile` với `test`, `cov`, `lint`, `types`, `fix`; target riêng: software-company (`golden`,
`eval`, `eval-record`, `eval-replay`, `eval-thresholds`, `assetscan`, `assetbudget`, `subagents`, `gate-brief`,
`run`, `status`…), keeper (`golden`, `eval`, `eval-record`, `eval-replay`), gateway (`start`, `stop`, `status`,
`login`, `setup`, `models`, `ready`), console (`run`, `open`, `decide`). Makefile gốc: `sync`, `test`, `cov`,
`lint`, `types`, `fix`, `build`, `clean`.

Muốn các cổng nhẹ (ruff, gitleaks, YAML, khoảng trắng thừa) chạy tự động trước mỗi commit, cài pre-commit một lần
ở gốc repo:

```bash
uv tool install pre-commit && pre-commit install
```

Cấu hình ở `.pre-commit-config.yaml`; `pre-commit run --all-files` chạy tay trên toàn bộ repo.

Không có `make` (Windows): mở `Makefile` và chạy dòng `uv run` tương ứng — dùng được nguyên văn trong PowerShell
(vd. `uv run python -m company.demo`), không cần đặt biến môi trường nào.

CI chạy đúng những cổng đó cộng eval replay, golden, drift, audit, asset-scan — bảng đủ job ở
[`ARCHITECTURE.md`](ARCHITECTURE.md) §CI. Job tổng hợp tên `quality` là required status check của `main` — **thêm
job con mới thì phải nối vào `needs` của nó**, nếu không kết quả của job đó không được tính.

Ngưỡng coverage nằm trong `pyproject.toml`: `fail_under = 100` ở **cả năm** package (software-company,
gateway, console, xagents-core, keeper). Nó đặt ở mức đang đạt được để chặn tụt lùi — nâng lên
khi coverage thật tăng, đừng hạ xuống để PR qua cổng. 100 này là phủ **dòng VÀ nhánh**: cả năm package bật
`branch = true` (gateway và console bật sau cùng, audit 2026-09-27/28 #366; đo 2026-09-09 còn 198/4966 nhánh chưa
phủ). Sổ `CHUA_PHU_NHANH` trong `platform/console/tests/test_cong_repo.py` canh việc một package lặng lẽ tắt nó.

## 3. Sửa `agents/` hoặc `skills/` — checklist bắt buộc

Prompt là code: đổi prompt mà không chạy lại các bước dưới đây thì CI đỏ, và đỏ có chủ đích.

1. **Tăng `version`** của agent/skill vừa sửa.
2. **`make golden`** rồi commit lại `tests/golden/`. Job `golden-check` chạy `make golden` trong CI và so bằng
   `git diff --exit-code` — quên commit là đỏ.
3. **Ghi lại bản ghi eval bằng model thật**, commit `evals/recordings/<id>.json`. Job eval-replay chạy
   `--strict`: agent có tên trong `evals/recordings/REQUIRED.txt` mà thiếu bản ghi, hoặc bản ghi ghi ở phiên bản
   prompt cũ, đều làm CI đỏ. Bản ghi phát lại từ file, CI **không** gọi model.

   Hai đường, chọn một (K5):

   | Đường | Khi nào | Lệnh |
   |---|---|---|
   | Máy cá nhân | bạn có API key trên máy | `make eval-record AGENT=<id>` (thêm `--jobs 3` cho `AGENT=all`) |
   | GitHub Actions | **không** có key trên máy, hoặc muốn ghi cả bộ | Actions → **eval-record** → Run workflow |

   **Điểm chấm dao động, và `--runs N` là chỗ duy nhất đo được nó.** Phát lại (`--replay`) là *tất định*: khoá
   là `hash(system, user)` và giá trị là `text` đã ghi, nên chạy lại trăm lần ra đúng một số. Dao động sinh ra
   lúc **ghi**. `make eval-record AGENT=<id> RUNS=3` chạy mỗi ca 3 lần và ghi thêm `score` (tỉ lệ đạt) cùng
   `runs` vào bản ghi — thời gian chạy nhân lên đúng N lần (~2,5 phút/agent/lần), và giết ngang là mất **toàn
   bộ** ca đã chấm vì `save()` chạy sau vòng lặp (`companies/software-company/TRAPS.md`). `--runs > 1` mà không `--record`
   bị từ chối ngay: nó chỉ tốn thời gian mà không đổi kết quả.

   `score` là số đo **độ ổn định lúc ghi**, không phải nhãn pass/fail của câu trả lời được lưu — `text` giữ lần
   chạy cuối, và replay vẫn chấm chính câu trả lời ấy bằng `check`. Nó **giảm** rủi ro đọc nhầm một lần đỏ thành
   hồi quy; nó không **loại bỏ** dao động.

   Workflow `eval-record` nhận `package` (`company`), `agents` (`all` hoặc danh sách), `provider`
   (`anthropic`/`openai`), `jobs`; đọc key từ Secrets `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` và tên model từ
   Variables `<PREFIX>_MODEL_STRONG/STANDARD/LIGHT`. Kết quả **không** push thẳng `main` — nó mở một PR
   `chore(<package>): ghi lại eval <agents>` gắn nhãn `no-changelog`, để người đọc diff trước khi vào.

   **Đọc bảng điểm ở job summary trước khi merge PR bản ghi**, và đọc nó như một xu hướng: điểm chấm dao động
   giữa các lần ghi, một lần tụt chưa phải hồi quy. Điểm không phải cổng riêng lẻ — CI chỉ đỏ khi bản ghi thiếu
   hoặc lệch phiên bản prompt, **hoặc** khi agent trong `evals/thresholds.yaml` tụt dưới sàn của nó (4L-1a; cột
   "ngưỡng" trong bảng job summary). Bản ghi mới làm điểm rớt xuống dưới sàn thì CI đỏ đúng ý — đó là cơ chế
   chặn hồi quy điểm dần dần qua nhiều lần ghi lại; nâng chất lượng prompt/skill trước khi commit, đừng hạ số
   trong `thresholds.yaml` để né. Đổi ngưỡng có chủ đích thì làm tròn xuống 0.05 theo điểm đo được (`make
   eval-thresholds` để xem điểm và dòng "dưới ngưỡng").
4. Commit bản ghi đầu tiên của một agent mới thì thêm id của nó vào `REQUIRED.txt` — từ lúc đó agent ấy được
   bảo vệ như trên.
5. **`make assetscan`** (trong `companies/software-company/`, quét công ty). Prompt là tài sản chuỗi cung ứng: mẫu
   injection, ký tự vô hình, lệnh `curl … | sh`, khóa lộ trong file prompt đều làm CI đỏ (ADR-0022). Cần giữ một
   mẫu để làm ví dụ dạy học thì thêm dòng có lý do vào `assetscan-waivers.txt`, đừng nới regex.
6. Nhồi thêm skill vào một agent thì chạy **`make assetbudget`**: prompt tĩnh vượt 50% `budget_tokens_per_task`
   của chính agent đó là đỏ — nâng ngân sách có chủ đích, hoặc bớt skill.
7. **`make subagents`** (trong `companies/software-company/`) rồi commit `.claude/agents/`: trợ lý kiểm duyệt `sc-*` là bản dẫn xuất
   một chiều từ `agents/`, `skills/` và `gates/checklists.md`; CI (bước `company.subagents check` trong job
   `golden-check`) và pre-commit đỏ khi bản trên đĩa lệch nguồn. Sửa mục "Người tự kiểm thêm" trong `gates/checklists.md` thì khai nguồn bằng chứng cho nó ở
   `src/company/gate_checklists.py` trước, nếu không parser gãy.

Ở software-company, một ca eval chấm không đạt **không** làm CI đỏ (đó là tín hiệu chất lượng cho vòng sau;
`--fail-on-score` để bật khi muốn); CI chỉ đỏ khi bản ghi thiếu, lệch phiên bản prompt, hoặc điểm của agent có
trong `evals/thresholds.yaml` tụt dưới sàn. keeper chặt hơn: bất kỳ ca nào không chạy được (`errored`) cũng đỏ
(chính sách ở `companies/keeper/src/keeper/evals.py`).

## 4. Thay đổi kiến trúc → ADR trước

Thêm/bỏ agent, đổi schema topic, đổi hợp đồng event, đổi cách điều phối model: viết ADR trong
`<công ty>/docs/adr/` **trước** khi code, và link ADR trong PR. Sửa lỗi nhỏ, chỉnh prompt, sửa tài liệu thì
không cần.

## 5. Không bao giờ commit

`llm.yaml`, `media.yaml`, khóa API, token gateway, dữ liệu khách thật. Chỉ commit bản `*.example.yaml`. gitleaks
quét cả lịch sử git, nên một secret lỡ commit rồi xoá ở commit sau vẫn làm CI đỏ — xem
[`SECURITY.md`](SECURITY.md) để biết cách xử lý.

Test không được gọi provider trả phí. Provider `fake` và bản ghi eval đủ để chạy toàn bộ offline.
