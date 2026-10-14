# ADR-0056: SCA và quét secret do orchestrator chạy trên máy trực trước release-check

Ngày: 2026-10-13. Trạng thái: chấp nhận. Liên quan: ADR-0046 (SBOM + license), ADR-0047 (DAST tối thiểu), ADR-0053
(bằng chứng từ compose), ADR-0055 (`image_digest`). Không đổi route, không đổi prompt của `security`, không đổi máy
trạng thái (ADR-0034).

## Bối cảnh — số đo

Hub thật 2026-10-12 → 13, `QLKH-DD-CSV` / `REL-021`, hai lượt release-check liên tiếp của `security` (lần hai sau khi
#454 đưa DAST lên môi trường compose). Cả hai lần `verdict=block`, trong đó hai finding mức `block` không liên quan tới
code của RC:

- "Vẫn không có kết quả quét lỗ hổng (pip-audit/OSV/Trivy) cho `requirements.lock` @ 9e1443c7, và cho gói Debian trong
  image `python:3.12.11-slim-bookworm@sha256:…` và `postgres:16.10-bookworm@sha256:…`. Không có bằng chứng này thì không
  khẳng định được 0 High/Critical reachable. Đây là lần thứ hai thiếu."
- "Vẫn không có kết quả quét secret (gitleaks hoặc tương đương) trên toàn bộ lịch sử git @ 9e1443c7. Đây là lần thứ hai
  thiếu."

Đúng luật của nó: `security` được dặn không đoán (ADR-0046 "Bối cảnh"), DoD của dự án đòi SCA và secret scan trước Gate 3,
và không file nào trong RC hay bus có hai thứ đó. Cùng một hình với SBOM (ADR-0046) và DAST (ADR-0047): bằng chứng chỉ
máy mới cho được, không ai đưa thì **mọi** RC bị chặn, kể cả khi sản phẩm hoàn chỉnh.

Đo tay trên máy trực (WSL2 Ubuntu, x86_64), cây RC 9e1443c:

| Lệnh | Thời gian | Kết quả |
|---|---|---|
| `trivy fs --scanners vuln --file-patterns 'pip:requirements\.lock'` | 29 s lần đầu (tải DB), 0,1 s sau | 16 gói, 6 CVE: 3 HIGH (`pg8000` 1.31.2 → 1.31.5, `starlette` 0.49.1 × 2) |
| `trivy fs` **không** `--file-patterns` | — | `Results` rỗng: trivy không nhận tên `requirements.lock` |
| `trivy image python:3.12.11-slim-bookworm` | 1,9 s | 421 CVE gói Debian (9 CRITICAL, 94 HIGH), 6 CVE Python |
| `gitleaks git --redact=100 --exit-code 0` | 0,7 s | 123 commit, 1 phát hiện (`generic-api-key` trong một file test) |

Máy trực không có `pip-audit`, `trivy`, `gitleaks`, `osv-scanner` sẵn; cả hai công cụ là một binary Go, cài vào
`~/.local/bin` (đã có trong `PATH` của `hub.env`).

## Quyết định

1. **Module `company.scanners`, hai bằng chứng mới trong `release-candidates → review-results` của security**, đi cùng
   `supply_chain` và `dast` trong `evidence_before` (`orch/verify.py`), `verified_by=orchestrator`:
   - `evidence.vuln` = `vuln_evidence(root, sha, images)`: `trivy fs` trên cây RC đúng sha đã staged (`_release_root`) với
     `--file-patterns 'pip:requirements\.lock'` (giữ nguyên nhận dạng mặc định cho `uv.lock`, `poetry.lock`,
     `package-lock.json`, `Cargo.lock`…), rồi `trivy image <ref>` cho từng image của Dockerfile/compose —
     `image_digest.references(root, pinned=True)`, tập **mọi** image kể cả đã ghim, khác tập "cần ghim" của ADR-0055.
     Lên bus: `by_severity`/`total` toàn cục, từng `targets[]` (lock file: gói, mức độ, danh sách phát hiện có trần
     `MAX_FINDINGS=50`), từng `images[]` (số đếm theo mức độ, `fixable`, `os`, `digest`; danh sách CRITICAL/HIGH từ bổ
     sung 2026-10-13 bên dưới), `errors[]` cho image không
     quét được. Một image lỗi không làm hỏng cả bằng chứng; `trivy fs` lỗi thì cả `vuln` là `unverified` kèm đuôi stderr.
   - `evidence.secrets` = `secret_evidence(root, sha)`: `gitleaks git --no-banner --redact=100 --exit-code 0` trên cây RC
     — worktree `_releases/<sha>` chia sẻ object store với repo khách nên quét được **toàn bộ lịch sử** (123 commit ở số đo).
     Lên bus chỉ vị trí: `rule`, `file`, `commit` (7 ký tự), `line`; không bao giờ `Secret`/`Match`, kể cả đã che.
     `commits_scanned` đọc từ stderr của gitleaks.
2. **Thiếu binary là `unverified` nói rõ cách cài**, không phải im lặng bỏ qua và không phải lỗi orchestrator. CI của
   repo này không có hai binary; test tiêm `which`/`run` ở mức module (như `deploy()`), fixture là JSON thật rút gọn
   của trivy/gitleaks. Quá `TIMEOUT_S=600` hay không chạy được cũng là `unverified`.
3. **Có phát hiện không phải lỗi chạy** (`--exit-code 0`; trivy không dùng `--exit-code`). Chặn hay không là chính sách
   của dự án — `security` đọc số rồi quyết, như license (ADR-0046 §3) và header thiếu (ADR-0047 §3). Máy không hạ
   verdict.
4. **Mọi bản `vuln`/`secrets` model tự khai bị bỏ** (`evidence_after`): ghi `vuln.claimed_ignored` /
   `secrets.claimed_ignored`, thay bằng bản của orchestrator — cùng luật với `supply_chain`/`dast`.
5. **Audit `vuln.run`/`secrets.run` không mang danh sách** (`targets`/`findings`): số đếm theo mức độ, image, lỗi vẫn
   ghi; toàn văn đi trong `review-results`.
6. **Chạy trên máy trực, không trong sandbox.** `trivy` cần tải DB (ghcr.io) và đọc image qua docker daemon; `gitleaks`
   chỉ đọc git. Cả hai là công cụ đọc, không chạy code của khách — khác `lock`/`image_digest` (ADR-0054/0055) là lệnh
   builder gọi trên cây ticket. Cây RC là checkout riêng theo sha, không phải worktree tích hợp.

## Bổ sung 2026-10-13 — danh sách CVE CRITICAL/HIGH của image

Đo hub thật 2026-10-13 (QLKH-DD-CSV REL-022, sau CR-DDCSV-SEC-001): image nền đã nâng (python 9→2 CRITICAL, postgres
20→4), lock sạch, gitleaks 0 — nhưng security chặn REL22-01/02 vì "RC không có danh sách CVE, không có bằng chứng
reachability, chưa có hồ sơ ngoại lệ". Quyết định 1 chỉ đưa số đếm cho image, nên security không có gì để viết hồ sơ
ngoại lệ hay chọn CVE cần vá.

- `images[].findings`: CRITICAL + HIGH (cùng dạng `targets[].findings`: package, version, id, severity, fixed),
  CRITICAL trước, có bản sửa trước, trần `MAX_FINDINGS`. MEDIUM/LOW vẫn chỉ đếm.
- Audit `vuln.run` vẫn chỉ đếm (`scanners.counts_only` bỏ `images[].findings`); danh sách đi trong `review-results`.
- Reachability, EPSS, KEV vẫn ngoài phạm vi máy — `security` đọc danh sách rồi quyết, như quyết định 3.

## Bổ sung 2026-10-14 — image ĐÃ DỰNG mà staging đang chạy

Đo hub thật 2026-10-14 (QLKH-DD-CSV REL-068 → REL-072): repo khách đổi service db từ `image: postgres:16.15-trixie@…`
sang `build: infra/db/Dockerfile` (image dẫn xuất gỡ gosu, CVE-2025-68121, CR-DDCSV-INFRA-002/004). Từ đó
`evidence.vuln.images` chỉ còn image nền của app: `infra/db/Dockerfile` sâu hai cấp nên nằm ngoài
`image_digest.DOCKERFILES`, và kể cả có quét thì image nền `postgres:16.15-trixie` vẫn còn gosu mà Dockerfile đã gỡ.
`security` chặn mọi RC, đúng luật: "RC không có bằng chứng về image db dẫn xuất (DD-CR2-03/04/26)". Đo tay trên máy
trực: `trivy image sha256:c5aabbe2…` (image id của container db staging, build tại 0f6637f) → không còn
CVE-2025-68121, 1 CRITICAL + 61 HIGH, 0 có bản sửa. Tức sản phẩm đã đạt; chỉ thiếu bằng chứng máy.

- `deploy()` (compose) ghi `image_ids` vào `evidence.deploy`, thẳng hàng `services`: image id đọc từ nhãn
  `com.docker.compose.image` của `compose ps --format json` (chuỗi `k=v,…` hay dict); thiếu nhãn là `""`, không đoán.
- `evidence_before` đưa cặp (service, image id) của `evidence.deploy` staging cùng RC cho
  `vuln_evidence(..., deployed=…)` — cùng bản ghi mà DAST đã dùng (ADR-0053). Quét **theo id**, không theo tên
  `company-<dự án>-staging-<service>`: tên bị gắn lại khi RC sau dựng lại staging, id thì không.
- Mỗi image đang chạy là một `images[]` có thêm `service` (gộp bằng dấu phẩy khi nhiều service chung id), `deployed:
  true`, `image_id` — cùng số đếm/`fixable`/`findings` như image nền. Image nền giữ nguyên hình cũ.
- Không đổi `image_digest.DOCKERFILES`: đó là tập "cần ghim" của ADR-0055 (khớp job `image-pin` của khách); thêm
  `**/Dockerfile` chỉ đưa thêm image nền mà chính Dockerfile dẫn xuất đã sửa.
- Process mode và `COMPANY_DEPLOY=off` không có `image_ids` → không thêm image nào, như trước.

## Bổ sung 2026-10-14 (2) — số đo cho điều kiện ký miễn, và hồ sơ gate mang nó

Đo hub thật 2026-10-14 (QLKH-DD-CSV REL-074, sau mục trên): ba finding block đều thuộc diện ký miễn của ADR gốc 0036
(CVE không có bản sửa ở image db và app, DPIA chỉ dữ liệu giả), nhưng `reviewer:tu-dong` giữ: hồ sơ `gate_brief` của
escalation `REL-*` chỉ chép câu chữ (đã cắt) của finding, không có `evidence.vuln`; và kể cả có, `images[].findings`
dừng ở `MAX_FINDINGS=50` trong khi image db có 62 CRITICAL/HIGH — không đối chiếu được "mọi CRITICAL/HIGH không có bản
sửa", không liệt kê đủ mã CVE.

- `images[]` thêm `serious_fixable` (số CRITICAL/HIGH có `FixedVersion`) và `serious_ids` (mã CVE CRITICAL/HIGH duy
  nhất, có thứ tự) — đếm trên **toàn bộ** kết quả trivy, không theo trần. `findings` giữ trần như cũ.
- `gate_brief` của escalation `REL-*` thêm mục "Lỗ hổng": `evidence.vuln` của review security mới nhất của chính RC đó,
  mỗi lock file/image một dòng (service nếu là image đang chạy, số theo mức độ, CRITICAL/HIGH có bản sửa, mã CVE).
  Evidence cũ không có `serious_ids` thì rút từ `findings` và ghi rõ "danh sách có trần, có thể thiếu"; `unverified`
  thì in lý do. Không có review security thì không có mục — không bịa.

## Cái giá đã biết

- Hai binary ngoài repo, phiên bản do máy trực quyết; `tool` ghi "trivy 0.75.0"/"gitleaks 8.30.1" vào bằng chứng để
  đọc lại được. Không có cơ chế ghim phiên bản hay kiểm chữ ký tải về — việc của người cài máy.
- `trivy image` cần image có trên máy hoặc kéo được qua docker; máy không có docker thì image vào `errors[]`, lock file
  vẫn có số.
- 421 CVE Debian của image nền là số thật nhưng phần lớn không "reachable"; bằng chứng chỉ đếm, `security` phải đọc
  `CRITICAL`/`HIGH` + `fixable` và quyết — không có bộ lọc reachability.
- gitleaks dùng bộ luật mặc định; `# gitleaks:allow` trong repo khách được tôn trọng (compose của QLKH đã dùng). Không
  có `.gitleaks.toml` riêng của công ty.
- Thời gian lượt security dài thêm ~2 s/image sau lần tải DB đầu (~30 s).

## Phương án đã loại

- **Script stdlib hỏi OSV API trong sandbox (như `image_digest`).** Trả lời được PyPI, không trả lời được gói Debian trong
  image — đúng nửa còn lại security đòi; và phải tự viết lại việc ghép version range mà trivy đã làm.
- **`pip-audit` vào venv của orchestrator.** Chỉ Python, không image, không secret; vẫn cần binary khác cho hai thứ kia.
- **Cho `security` tool chạy trivy/gitleaks.** Kết quả vẫn là lời khai; agent có tool vẫn có lúc không gọi tool
  (`review.no_tool_evidence`, ADR-0047 "Phương án đã loại").
- **Sửa DoD của dự án để bỏ SCA/secret.** Hạ chuẩn để qua cổng — ngược `docs/PRODUCT-EXCELLENCE.md` và luật cấm 6 theo
  tinh thần.

## Đo hai chiều

- Bỏ `vuln`/`secrets` khỏi `evidence_before` ⇒ `test_release_check_mang_vuln_va_secrets_cua_may` và
  `test_khong_co_repo_thi_vuln_va_secrets_unverified` đỏ.
- Bỏ `--file-patterns` ⇒ `test_vuln_evidence_tom_tat_trivy_fs_va_image_theo_muc_do` đỏ (và trên máy trực `Results`
  rỗng như bảng trên).
- Bỏ `pinned=True` ⇒ `test_references_pinned_giu_ca_image_da_ghim_cho_quet_lo_hong` đỏ.
- 16 test mới; 13 ca đầu đỏ trước khi có `company.scanners` (`ModuleNotFoundError`), xanh sau; 3 ca sau (OSError, timeout gitleaks, chiều ngược ngoại lệ subprocess) thêm khi cổng báo thiếu phủ và ranh giới sandbox đỏ.
