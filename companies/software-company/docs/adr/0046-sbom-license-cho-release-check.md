# ADR-0046: SBOM + license của release-check do orchestrator sinh, không phải lời khai

Trạng thái: Accepted · Ngày: 2026-09-27 · Nối tiếp ADR-0029 (bằng chứng chạy là của orchestrator), ADR-0044
(lệnh chạy bằng môi trường của khách), ADR-0035 (sandbox). Không đổi route, không đổi prompt của `security`.

## Bối cảnh — số đo

Dự án CAMPUS-UNI-20260922. `security` chặn **mọi** release-check nó từng chạy (REL-004 ngày 24/09, REL-007 ngày
26/09) với cùng một lý do: `release-candidates` không kèm SBOM, không kèm `license_summary` — "chưa có dữ liệu để
kết luận 100% hợp lệ". Lời chặn đúng: payload RC do delivery-lead phát chỉ có `release_id`, `project_id`,
`tickets`, `version` (`delivery._create_release_candidate`), và route `release-candidates → security` không có
tool nào (`orch/routes.py`). Agent được dặn "không đoán số liệu", nên không có cách nào để nó pass.

Repo khách **có** SBOM và cổng license riêng (`scripts/gen_sbom.py`, `scripts/check_licenses.py`); phiên chính đã
chạy tay trên snapshot `5d0d7ca`: 27 thành phần, `check_licenses` rc=0 — rồi ký thay (`reviewer:phien-chinh`) vì
máy không đưa được con số đó tới security. Lặp lại ở mọi RC là đúng khuôn "chặn bởi hạ tầng, bằng chứng trỏ vào
người khác" của ADR-0044.

## Quyết định

1. Trước lượt `security` trên `release-candidates`, orchestrator tự dựng bằng chứng chuỗi cung ứng trên đúng thư
   mục RC (`_release_root`, cùng chỗ QA hồi quy đọc) và đưa vào input dưới `evidence.supply_chain`
   (`verified_by=orchestrator`):
   - **Thành phần** đọc từ `uv.lock` bằng `tomllib` (không chạy gì): tên, phiên bản, `purl`. Gói gốc/workspace
     (`source.editable`/`source.virtual`) không tính.
   - **License** đọc từ metadata gói đã cài trong môi trường của khách: `uv run --frozen -- python -c <script>`
     trong sandbox (ADR-0044, ADR-0035). Thứ tự: `License-Expression` (PEP 639) → classifier `License ::` →
     trường `License`. Chuẩn hoá sang SPDX chỉ khi không mơ hồ; "BSD License", "Apache Software License" không
     có phiên bản → `NOASSERTION` kèm chuỗi gốc. Không đoán.
   - Kết quả: số thành phần, đếm theo SPDX id, danh sách `noassertion`, danh sách `copyleft` (chuỗi gốc chứa
     GPL/SSPL), SBOM CycloneDX 1.5 đầy đủ, `sbom_ref = sha256:<băm SBOM>`.
2. Sau lượt, `evidence.supply_chain` và `sbom_ref` trong `review-results` bị **ghi đè** bằng bản của orchestrator;
   model tự khai thì bị bỏ và ghi `supply_chain.claimed_ignored` — cùng nguyên tắc `evidence.run` (ADR-0029).
3. **Không ghi đè verdict.** Smoke hỏng là sự thật khách quan; license có hợp lệ hay không là chính sách của dự
   án (GPL qua ADR vẫn được, `security.md`). Máy đưa số, security và người ký quyết.
4. Không dựng được (không có repo/worktree tích hợp, không có `uv.lock`) → `unverified` kèm lý do, như
   `smoke.unverified`. `uv run` hỏng (thiếu `uv`, sandbox tắt mạng chưa có venv) → vẫn có danh sách thành phần,
   license `NOASSERTION`, `licenses_error` nói vì sao.

## Bổ sung 2026-09-27 — lock file ngoài uv

Bản đầu chỉ đọc `uv.lock`; dự án Node/Go/Rust ra `unverified` và security chặn như trước. Nay `supply_chain.evidence`
đọc bốn loại lock ở **gốc cây RC và thư mục con một tầng** (monorepo `frontend/`, `backend/`; bỏ thư mục ẩn,
`node_modules`, `target`, `vendor`), gộp theo `purl`, ghi `lock` của từng dòng và `source = "uv.lock+frontend/…"`:

| Lock | Thành phần | License |
|---|---|---|
| `uv.lock` | như trên | metadata gói đã cài, `uv run --frozen` trong sandbox |
| `package-lock.json` v2/v3 | `packages` dưới `node_modules/` (bỏ gốc, `link`) | trường `license` npm tự ghi vào lock; thiếu thì `package.json` trong `node_modules` — không chạy gì |
| `Cargo.lock` | gói có `source` (không có là crate của workspace) | `cargo metadata --locked --offline` trong sandbox; `/` là cú pháp OR cũ Cargo còn chấp nhận nên đổi thành ` OR ` |
| `go.mod` | các dòng `require` (Go ≥ 1.17 ghi đủ gián tiếp) | không có nguồn: `NOASSERTION`, `licenses_error` nói vì sao |

Lỗi của từng lock gộp vào `licenses_error` dạng `"<lock>: <lý do>"`.

## Cái giá đã biết

- Không đọc `yarn.lock`, `pnpm-lock.yaml`, `package-lock.json` v1, `poetry.lock`, `requirements*.txt`. Dự án chỉ có
  các lock đó vẫn ra `unverified` — thêm khi có dự án thật cần.
- Go: có SBOM nhưng license toàn `NOASSERTION` (module Go không khai license); security vẫn có thể chặn vì license.
  Quét file LICENSE là nhận dạng văn bản, không phải đọc metadata — chưa làm. `replace` trong `go.mod` không áp.
- Cargo: `--offline` cần crate đã tải về máy; chưa có thì license `NOASSERTION` kèm lỗi của `cargo`.
- Gói có trong lock nhưng không cài trên máy này (chỉ dành cho OS khác) → `NOASSERTION`, `installed=false`.
- DAST **không** thuộc ADR này — xem ADR-0047 (DAST tối thiểu cùng chỗ, và lệnh `recheck` chấm lại RC cũ).

## Phương án đã loại

- **Chạy script SBOM của chính khách** (`scripts/gen_sbom.py`). Tên và vị trí là của một repo; spec không có trường
  nào khai nó. Thêm trường vào spec nghĩa là mọi dự án đã duyệt spec phải qua change request.
- **Cho route security `tools="ro"` rồi để nó tự chạy.** Kết quả vẫn là lời khai của model; và QA đã cho thấy agent
  có tool vẫn có lúc không gọi tool nào (`review.no_tool_evidence`).
- **Nhét SBOM vào payload `release-candidates`.** Topic đó do delivery-lead phát lúc tạo RC, trước khi RC được
  merge vào nhánh tích hợp (`integrate_rc`, pha `pre`); SBOM phải dựng trên đúng cây của RC.
