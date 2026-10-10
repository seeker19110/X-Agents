# Đối chiếu repo GitHub về "tư vấn đa dạng phần mềm" — 2026-10-10

Yêu cầu: *"tìm kiếm trên github các repo có thể tốt hơn về công việc này, tổng hợp lại những điểm tốt để tích hợp
sâu"*, nối câu hỏi trước *"dự án đã có tư vấn đa dạng phần mềm giống repo project-template chưa?"*. "Công việc này" =
**chọn yêu cầu, phép kiểm và hướng thiết kế theo loại phần mềm và ngành**. Ở X-Agents nó nằm ở `ProjectProfile`
(`companies/software-company/src/company/product_quality.py`), `docs/PRODUCT-EXCELLENCE.md` §3–4, các skill
`domain-research`, `requirements-engineering`, `ui-ux-design`, và `/product-goal`.

Làm theo `docs/PROMPT-SHEET.md` §H: ba cột **đã có và sâu hơn / đã có nhưng nông hơn / chưa có**; "chưa có" chỉ lấy
khi chỉ ra **sự cố đã xảy ra ở đây**. Không cài gì. Báo cáo này **chỉ kết luận**, chưa sửa code: mỗi mục "lấy" ở §4
là một PR riêng, test đỏ trước.

## 1. Nguồn đã đọc (clone nông, đọc file, không tin README)

| Repo | Commit | License | Phần đọc |
|---|---|---|---|
| `bmad-code-org/BMAD-METHOD` | `bda3c592` | MIT | `skills/bmad-prd/` (SKILL, `prd-template.md` Adapt-In Menu, `prd-validation-checklist.md`), `bmad-advanced-elicitation/assets/methods.csv` |
| `zoltraks/lens-skill` | `aa39d2cd` | MIT | `SKILL.md`, `references/domain-profiles.md`, `assessment/nfr-review.md`, danh mục `assessment/`, `references/stacks/` |
| `github/spec-kit` | `04437605` | MIT | `templates/commands/checklist.md` ("unit tests for English") |
| `aws-samples/sample-well-architected-skills-and-steering` | `e81835b1` | MIT-0 | `skills/aws-well-architected-framework-review/SKILL.md`, 29 thư mục `references/lenses/` |
| `nextlevelbuilder/ui-ux-pro-max-skill` | `50d8a7de` | MIT | `data/products.csv` (192 dòng), `data/ui-reasoning.csv` (192 dòng), `data/stacks/` |
| `keyurgolani/AgentSpec` | `aae3b134` | MIT | `agentspec/data/templates/domain/*.json` |

Tìm bằng web search ("spec-driven template industry profiles", "NFR catalog by application type agent skill",
"well-architected lenses agent skill"). Không có repo nào gộp đủ ba thứ: phân loại theo loại sản phẩm + ngành +
phép kiểm bắt buộc có bằng chứng. Mỗi repo mạnh một mảnh.

## 2. Cột 1 — đã có ở đây và sâu hơn (không lấy)

| Nguồn | Ý chính | Ở đây | Vì sao không lấy |
|---|---|---|---|
| AgentSpec `domain/healthcare-application.json`… | Template ngành gắn cứng stack (`react`, `node.js`, `postgresql`) + danh sách chỉ dẫn | `domain.obligations` + skill `domain-research` (mọi quy định phải có số hiệu, điều khoản, hiệu lực) | Báo cáo 2026-09-25 đã loại "stack mặc định theo ngành". Template của họ không đòi bằng chứng nào |
| ui-ux-pro-max `products.csv`/`ui-reasoning.csv` | 192 loại sản phẩm → pattern, style, màu, anti-pattern | `skills/ui-ux-design.md` `sources:` đã hấp thụ (cùng impeccable, hallmark); `design.*` check theo surface | Đã lấy từ 2026-09-05/06. Bảng màu theo ngành đi ngược `PRODUCT-EXCELLENCE.md` §4 ("không một phong cách cho cả ngành") |
| spec-kit `/checklist` | Checklist kiểm *chất lượng câu yêu cầu*, agent không được tự đánh `[x]` | Checklist của `requirements-engineering`, gate `spec` + `sc-gate-spec`, sàn tự duyệt ADR-0043, DeliveryContract Ready | Cùng ý, ở đây có chữ ký và gate người |
| AWS WA review | "Thiếu chi tiết = không biết, không phải = không có", đánh `Cannot Determine` | `unverified`, `NOT_CONFIGURED` chặn, `NOT_APPLICABLE` cần `scope_reason` khai trước (#335) | Ở đây chặn bằng máy, họ chỉ dặn bằng lời. Skill đã deprecated, gắn AWS (luật trung lập provider) |
| lens-skill "probe bị bỏ phải có lý do; không đo được → `NOT ASSESSED`, không im lặng" | | DeliveryContract: N/A chỉ khi contract khai trước | Đã có, chặt hơn |
| BMAD `.memlog.md` (log quyết định append-only) | | ExecutionJournal + bus + `docs/thi-hanh/<mã>.md` | Trùng nguồn trạng thái bền |
| BMAD rubric "Done-ness clarity", "NFR theater" (NFR chép boilerplate, không ngưỡng) | | `requirements-engineering` §NFR: số đo + đơn vị + điều kiện đo, rà ISO 25010; MoSCoW | Đã có ở dạng luật |

## 3. Cột 2 — đã có nhưng nông hơn: NÊN LẤY (đã đo khoảng trống)

### 3a. Phép kiểm bắt buộc theo loại sản phẩm phi-UI — từ lens-skill `domain-profiles.md`

**Đo:** chạy `required_checks()` với `surfaces=["cli"]`, `["library"]`, `["api"]` (các cờ khác tắt). Cả ba ra **cùng
đúng 15 check** (`BASE_CHECKS`). Không check nào phân biệt một thư viện với một CLI hay một API. Trong khi đó
`PRODUCT-EXCELLENCE.md` §4 dòng "General/API/CLI/library" đòi "versioning và compatibility", "lỗi có nghĩa". Tài liệu
đòi mà code không đòi: sản phẩm thư viện đổi API công khai mà không ai bắt.

lens-skill gắn mỗi "nature" với một bộ probe bắt buộc:

| Nature | Probe bắt buộc (của họ) | Đề xuất cho `product_quality.py` |
|---|---|---|
| `library` | kiểm kê bề mặt công khai, kỷ luật versioning, phân loại lỗi người dùng thấy | `contract.public_surface` (independent_review) + `contract.compatibility` (runner: so API với bản phát hành trước) |
| `cli` | nơi lưu credential/token, hợp đồng tham số + exit code, cwd vs vị trí config | `cli.contract` (runner: exit code/stdout/stderr theo spec, lỗi có nghĩa) |
| `api`/`service` | vòng đời session, giới hạn rate/size từng endpoint, tắt êm, giới hạn đồng thời | `api.contract` (runner: schema + lỗi + giới hạn) — gộp vào `SERVICE_CHECKS` hiện có khi `operates_service` |

Cách làm: test đỏ `required_checks(surfaces=["library"])` phải chứa `contract.compatibility` → thêm bộ check, giữ luật
"check chỉ được thêm theo tính áp dụng, không bị worker bỏ". Đụng `CATALOG` nên **profile hash đổi cho profile có
surface đó**: cần đo lại test hash cố định của profile v2 (báo cáo 2026-09-25 §5) và ghi rõ chỉ áp cho run mới.

### 3b. Truy vết producer/consumer + điểm danh stub — từ lens-skill "Cross-Cutting Probes"

**Sự cố đã xảy ra:** `docs/sessions/2026-09-09-van-hanh-qlkh.md` — ticket `TCK-CR-RUNTIME-01` tạo `runtime.yaml`
trong repo khách nhưng **không dòng mã nào đọc nó**. Phễu release QLKH kẹt 19 release, 10 lần staging thất bại.
`goal.traceability` hiện chỉ là một câu cho reviewer ("no stubs or scope drift"), không có hình dạng bằng chứng cụ thể.

lens-skill đòi hai bảng: **identifier trace** (mỗi giá trị đi qua ranh giới thành phần — đường dẫn, ID, token, khoá
config — có ma trận nơi sinh/nơi đọc) và **stub census** (hàm trả về cố định, thân `todo!`, module không ai gọi, nhánh
cờ tính năng đứng sau một khả năng đã quảng cáo).

Đề xuất: thêm hai dòng bằng chứng vào checklist gate `acceptance` (`gates/checklists.md`, khai nguồn ở
`gate_checklists.py` trước, rồi `make subagents`): "mỗi file/khoá/trường mới mà diff sinh ra có ít nhất một nơi đọc
trong mã — trỏ dòng" và "không khả năng nào trong README/spec đứng sau stub". Đây là sửa gate checklist, không thêm
agent.

### 3c. Gói mục theo mối quan tâm của sản phẩm — từ BMAD `prd-template.md` "Adapt-In Menu"

Bảng ngành ở `PRODUCT-EXCELLENCE.md` §4 có 8 dòng theo ngành; BMAD bổ sung một trục khác: **mối quan tâm** quyết định
mục nào của PRD phải có, và danh sách mở ("product mang mối quan tâm mà menu không nêu thì tự đặt mục").

| Cụm BMAD | Mục bắt buộc | Ở đây |
|---|---|---|
| Developer products | API contract, chính sách versioning/deprecation, performance budget, runtime target | Chỉ một dòng chữ trong §4 (xem 3a) |
| Embedded/hardware | Ràng buộc phần cứng, cơ chế cập nhật (OTA), môi trường | **Không có** — `Surface` không có giá trị nào cho thiết bị |
| Enterprise | SSO, RTO/RPO, rollout/đào tạo, data residency, audit trail | Rải ở ma trận §3; không gom theo cụm |
| Có Success Metrics | **Counter-metric** đặt cạnh mỗi chỉ số thành công | Chỉ `data-engineering` có "guardrail metric" cho A/B; `requirements-engineering` không đòi |

Đề xuất nhỏ nhất: thêm luật "có chỉ số thành công thì có chỉ số đối trọng" + bảng cụm vào `requirements-engineering`.
Sửa skill nên **phải đi đủ 7 bước** `CONTRIBUTING.md` §3 (version, golden, `eval-record` model thật…). Phần
embedded xếp cột 3.

## 4. Cột 3 — chưa có, xếp "chưa cần" kèm điều kiện quay lại

| Thứ | Vì sao chưa cần | Quay lại khi |
|---|---|---|
| Nature `pipeline`, `retrieval`, `agent-tooling`, `automation` (lens-skill) và surface thiết bị/embedded (BMAD) | Dự án khách đã chạy (QLKH) là web + api; không ca nào rơi ngoài `Surface` hiện có | Dự án khách đầu tiên là batch/ETL, RAG, MCP server hay firmware → mở rộng `Surface` cùng bộ probe của nó |
| Phân loại nature **từ bằng chứng** (manifest, entry point) thay vì coordinator khai | Họ hàng với sự cố QLKH (`kind` thiếu ⇒ mặc định `application`), nhưng ADR-0031 đã vá đúng chỗ đó bằng `unverified` | Một profile khai `surfaces` lệch repo thật mà không ai bắt |
| 29 lens ngành của AWS WA (games, telco, IoT, life sciences, government…) | Gắn AWS; `Domain` có 8 giá trị, chưa dự án nào ngoài 8 | Khách thuộc ngành ngoài 8 nhóm; lấy *câu hỏi* của lens, không lấy dịch vụ AWS |
| `methods.csv` 72 phương pháp khơi gợi, party-mode nhiều persona (BMAD) | Không sự cố thiếu ý; tốn token prompt (`make assetbudget`) | Gate `spec` bị trả về ≥ 2 lần cùng dự án vì thiếu khơi gợi |
| Scorecard 1–10, risk register `RSK-001` (lens-skill) | Đi ngược luật "không điểm thẩm mỹ phổ quát" của §4; gate có chữ ký đã là sổ quyết định | Khách đòi báo cáo audit dạng điểm |
| Stakes calibration (hobby/internal/launch quyết độ dài PRD) | `completion_target` + mức C1/C2/C3 đã làm việc này | PRD nội bộ nhỏ bị phình (đo `assetbudget`/token pha spec) |

## 5. Thứ tự đề xuất

1. **3a** — nhỏ, cô lập trong `product_quality.py`, khoảng trống đo được bằng một dòng lệnh. Một PR `feat(company)`.
2. **3b** — có sự cố thật đứng sau; sửa `gates/checklists.md` + `gate_checklists.py` + `make subagents`.
3. **3c** — đụng skill nên tốn nhất (7 bước, `eval-record` cần model thật); làm sau cùng hoặc gộp vào lần sửa
   `requirements-engineering` kế tiếp.

Không vendor file nào từ sáu repo: mọi mục là ý tưởng viết lại theo khuôn của repo này (MIT/MIT-0 cho phép, nhưng
luật "lớp thêm chứ không phải luật" của ADR 0028 áp như ECC).
