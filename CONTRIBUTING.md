# Đóng góp vào X-Agents

Quy trình Git (nhánh, commit, PR, merge) nằm ở [`docs/QUY-TRINH-GIT.md`](docs/QUY-TRINH-GIT.md) — file này
không lặp lại, chỉ nói những thứ riêng của repo: chạy ở đâu, cổng CI nào chặn cái gì, và sửa agent thì phải
chạy lại những gì.

## 1. Cài đặt

Cần Python 3.11+ và [`uv`](https://docs.astral.sh/uv/). `ffmpeg` chỉ cần khi muốn render video thật ở
Studio-creators (thiếu thì test render tự bỏ qua).

Mỗi thư mục là một package độc lập, có `pyproject.toml` + `uv.lock` + `Makefile` riêng. **Mọi lệnh chạy bên
trong thư mục đó**, không có lệnh nào ở gốc repo:

| Thư mục | Package | Lệnh cài |
| --- | --- | --- |
| `software-company/` | `company` | `cd software-company && uv sync` |
| `Studio-creators/` | `studio` | `cd Studio-creators && uv sync` |
| `gateway/` | `gateway` | `cd gateway && uv sync` |

Không có `[project.scripts]`: mọi entry point đều là `python -m <package>.<module>`.

## 2. Cổng chất lượng

Chạy trước khi mở PR, trong thư mục đã sửa:

```bash
make lint && make test
```

`software-company` và `Studio-creators` có cùng bộ target: `test`, `cov`, `lint` (ruff + mypy), `types`, `fix`,
`golden`, `eval`, `eval-record`, `eval-replay`, `demo`, `run`, `status`. `gateway` có `test`, `cov`, `lint`,
`types`, `fix` cùng nghĩa.

Muốn các cổng nhẹ (ruff, gitleaks, YAML, khoảng trắng thừa) chạy tự động trước mỗi commit, cài pre-commit một lần
ở gốc repo:

```bash
uv tool install pre-commit && pre-commit install
```

Cấu hình ở `.pre-commit-config.yaml`; `pre-commit run --all-files` chạy tay trên toàn bộ repo.

Không có `make` (Windows): mở `Makefile` và chạy dòng `uv run` tương ứng. Với target có `PYTHONPATH=src`, trong
PowerShell viết `$env:PYTHONPATH='src'; uv run python -m studio.demo`.

CI (`.github/workflows/ci.yml`) chạy đúng những cổng đó, thêm `audit` (pip-audit + gitleaks trên cả lịch sử) và
`golden-check`. Job tổng hợp tên `quality` là required status check của `main` — **thêm job con mới thì phải nối
vào `needs` của nó**, nếu không kết quả của job đó không được tính.

Ngưỡng coverage nằm trong `pyproject.toml` (`fail_under`: 90 cho software-company, 84 cho Studio-creators, 73 cho
gateway). Nó
đặt ở mức đang đạt được để chặn tụt lùi — nâng lên khi coverage thật tăng, đừng hạ xuống để PR qua cổng.

## 3. Sửa `agents/` hoặc `skills/` — checklist bắt buộc

Prompt là code: đổi prompt mà không chạy lại các bước dưới đây thì CI đỏ, và đỏ có chủ đích.

1. **Tăng `version`** của agent/skill vừa sửa.
2. **`make golden`** rồi commit lại `tests/golden/`. Job `golden-check` chạy `make golden` trong CI và so bằng
   `git diff --exit-code` — quên commit là đỏ.
3. **`make eval-record AGENT=<id>`** bằng model thật, commit `evals/recordings/<id>.json`. Job eval-replay chạy
   `--strict`: agent có tên trong `evals/recordings/REQUIRED.txt` mà thiếu bản ghi, hoặc bản ghi ghi ở phiên bản
   prompt cũ, đều làm CI đỏ. Bản ghi phát lại từ file, CI **không** gọi model.
4. Commit bản ghi đầu tiên của một agent mới thì thêm id của nó vào `REQUIRED.txt` — từ lúc đó agent ấy được
   bảo vệ như trên.
5. **`make assetscan`** (trong `software-company/`, quét cả hai công ty). Prompt là tài sản chuỗi cung ứng: mẫu
   injection, ký tự vô hình, lệnh `curl … | sh`, khóa lộ trong file prompt đều làm CI đỏ (ADR-0022). Cần giữ một
   mẫu để làm ví dụ dạy học thì thêm dòng có lý do vào `assetscan-waivers.txt`, đừng nới regex.
6. Nhồi thêm skill vào một agent thì chạy **`make assetbudget`**: prompt tĩnh vượt 50% `budget_tokens_per_task`
   của chính agent đó là đỏ — nâng ngân sách có chủ đích, hoặc bớt skill.

Ca eval chấm không đạt **không** làm CI đỏ (đó là tín hiệu chất lượng cho vòng sau); chỉ bản ghi thiếu hoặc lệch
mới đỏ.

## 4. Thay đổi kiến trúc → ADR trước

Thêm/bỏ agent, đổi schema topic, đổi hợp đồng event, đổi cách điều phối model: viết ADR trong
`<công ty>/docs/adr/` **trước** khi code, và link ADR trong PR. Sửa lỗi nhỏ, chỉnh prompt, sửa tài liệu thì
không cần.

## 5. Không bao giờ commit

`llm.yaml`, `media.yaml`, khóa API, token gateway, dữ liệu khách thật. Chỉ commit bản `*.example.yaml`. gitleaks
quét cả lịch sử git, nên một secret lỡ commit rồi xoá ở commit sau vẫn làm CI đỏ — xem
[`SECURITY.md`](SECURITY.md) để biết cách xử lý.

Test không được gọi provider trả phí. Provider `fake` và bản ghi eval đủ để chạy toàn bộ offline.
