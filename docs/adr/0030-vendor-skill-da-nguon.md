# ADR-0030: Vendor skill đa nguồn — một script, mỗi nguồn một lock và một tiền tố

Ngày: 2026-10-10 · Trạng thái: **đề xuất** (chờ duyệt qua PR) · Mở rộng ADR-0028 (vendor ECC chọn lọc) từ một nguồn
sang nhiều nguồn. Mọi quyết định của 0028 giữ nguyên; ADR này chỉ đổi chỗ chúng được cấu hình (lock thay hằng số trong
script) và thêm nguồn thứ hai.

## Bối cảnh

Hồ sơ `docs/thi-hanh/ib1.md` (đối chiếu ba infographic, báo cáo `docs/reports/2026-10-10-doi-chieu-ba-infographic.md`
§3) chọn hai skill của `mattpocock/skills` có sự cố tương ứng ở repo: `writing-for-agents` (luật nạp mỗi phiên 26,5 KB,
pe2 P0) và `retro` (bốn audit hồi cứu thủ công trong một ngày). Cơ chế vendor hiện có chỉ biết ECC:

| Chỗ cứng | Ở đâu |
|---|---|
| tiền tố `ecc-`, lock `docs/integrations/ecc.lock.json`, giấy phép `ecc.LICENSE` | ba hằng `PREFIX`, `LOCK_REL`, `LICENSE_REL` của `scripts/ecc_vendor.py` |
| khuôn thư mục `skills/<x>/`, `commands/<x>.md`, `agents/<x>.md` | `_sources`, `_measured` |
| ghi chú nguồn "ECC (MIT)" | `_note` |
| dấu hiệu plugin `ecc:` | `COUPLING` chung |
| cổng offline | `test_cong_ecc.py` đọc đúng một lock |

Nguồn thứ hai khác ECC ở ba chỗ đã đo trên `mattpocock/skills@49dd158d1076134a641b33efb035946536778336` (MIT,
`package.json` 1.3.1):

- **Khuôn thư mục**: 38 skill nằm ở `skills/<bucket>/<tên>/` (engineering 20, productivity 7, in-progress 7, misc 4);
  27 ở hai bucket được promote. Không có thư mục `commands/` hay `agents/` ở gốc.
- **Tệp phụ**: **mọi** skill (38/38) có `agents/openai.yaml` (metadata cho Codex), không phải `.md`. ECC không có.
  Ngoài nó chỉ có bốn tệp mã: `wizard/template.sh`, `diagnosing-bugs/scripts/hitl-loop.template.sh`,
  `setup-ts-deep-modules/dependency-cruiser.config.cjs`, `git-guardrails-claude-code/scripts/block-dangerous-git.sh`.
- **Cách gọi skill khác**: `Call the Skill tool with "x"` hoặc `` `x` `` — dạng nháy kép chưa có trong bộ đổi tên.

## Quyết định

**(a) Một script cho mọi nguồn.** `scripts/ecc_vendor.py` → `scripts/vendor_skills.py` (`git mv`), CLI
`build|check --lock <đường dẫn lock>` (`--lock` bắt buộc). Hành vi với ECC không đổi ngoài hai dòng ghi chú nguồn.

**(b) Mỗi nguồn một lock** `docs/integrations/<tên>.lock.json`, giữ mọi trường cũ, thêm:

| Khoá | Bắt buộc | Nghĩa |
|---|---|---|
| `prefix` | có | tiền tố tên trong `.claude/`, khớp `^[a-z0-9]+-$` (`ecc-`, `mp-`) |
| `label` | có | tên nguồn trong ghi chú đầu tệp và thông điệp (`ECC`, `mattpocock/skills`) |
| `license_path` | có | nơi chép `LICENSE` của nguồn |
| `license_holder` | có | cổng offline kiểm tên này có trong giấy phép |
| `ignore` | không, mặc định `[]` | mẫu fnmatch trên đường dẫn trong thư mục mục; tệp khớp bị **bỏ qua** thay vì dừng build. Rỗng thì tệp không phải `.md` vẫn bị từ chối như cũ |
| `coupling` | không, mặc định `{}` | dấu hiệu "chỉ chạy khi là plugin" riêng của nguồn, gộp với `COUPLING` chung |
| `paths` | không, mặc định `skills/{name}`, `commands/{name}.md`, `agents/{name}.md` | khuôn thư mục ở nguồn; glob phải khớp **đúng một** chỗ, 0 hay ≥ 2 là lỗi |

**(c) Hai trần mô tả.** Mỗi lock giữ `budget_description_chars` riêng (ECC 6 000, Pocock 1 500). Thêm trần **chung**
cho mô tả skill + lệnh của cả `.claude/` (vendor lẫn của repo) ở cổng: `BUDGET_TOTAL = 8000`. Trần riêng không chặn
được tổng khi nguồn thứ ba hay lệnh mới của repo cộng vào cùng danh sách Claude Code nạp mỗi phiên.

**(d) Tiền tố không lồng nhau.** Build xoá mọi `<tiền tố>*` cũ trước khi ghi. `build`/`check` tự tìm lock anh em (mọi
`*.lock.json` cùng thư mục có khoá `select`; `projects-template.lock.json` khác khuôn nên bỏ qua) và từ chối khi hai
tiền tố là tiền tố của nhau. `sc-` (của `make subagents`, `.claude/agents/sc-*`) là tiền tố đã có chủ, cấm. Hai tiền
tố không lồng nhau thì `<tiền tố><tên>` không thể đụng nhau, nên không cần kiểm thêm tên mục.

**(e) Ghi chú nguồn** nêu `label`, giấy phép, đường dẫn lock, "luật `AGENTS.md` thắng khi trùng" và tiền tố của nguồn
đó.

**(f) Tham chiếu `"x"` trong nháy kép cũng đổi** sang `"<tiền tố>x"` — cùng luật "chỉ dạng tường minh" của ADR-0028 §2.

**(g) `COUPLING` chung + `coupling` riêng.** Năm mẫu chung giữ trong script; `\becc:[a-z]` chuyển vào
`ecc.lock.json["coupling"]` vì chỉ là namespace plugin của ECC.

**(h) Nguồn thứ hai**: `docs/integrations/mattpocock.lock.json`, tiền tố `mp-`, `paths.skills = "skills/*/{name}"`,
`ignore = ["agents/openai.yaml"]`. Chọn `writing-for-agents` (kèm `SKILL-MECHANICS.md`) và `retro` (giữ
`disable-model-invocation: true` — chỉ người gõ `/mp-retro` mới gọi). 36 mục còn lại nằm trong `rejected`, mỗi mục một
lý do (theo `ib1.md` §B "Cố ý không làm" và báo cáo §3).

**G1 — `grilling`/`grill-me`/`grill-with-docs`: giữ loại.** Repo đã loại `/grill` ba lần vì ngược `AGENTS.md` §"Khi
bối rối" (2026-09-14, `CHANGELOG.md`, đối chiếu projects-template v4). Quyết định giữ nguyên ngày 2026-10-10; lý do
ghi trong `rejected` của lock. Lật lại phải qua người, không qua phiên.

**Makefile và CI**: `make vendor LOCK=<lock>` (thiếu `LOCK` là lỗi), `make vendor-check` lặp mọi lock có `select`;
`ecc-vendor`/`ecc-check` còn là alias. Job CI `ecc-check` đổi thành `vendor-check` (vẫn trong `needs` của `quality`).
Cổng offline `test_cong_ecc.py` → `test_cong_vendor.py`, mọi phép canh parametrize theo lock.

## Phương án đã loại

- **Script thứ hai chép từ `ecc_vendor.py`.** Ưu điểm thật: không chạm đường ECC đang chạy. Loại vì thành hai bản
  của cùng một cơ chế (đổi tên, quét coupling, ghim sha256) — sửa một bản thì bản kia lệch im lặng, đúng họ lỗi
  `TRAPS.md` §1.
- **Plugin `mattpocock-skills@claude-plugins-official`.** ADR-0028 §"Đo" đã đo: plugin không nạp ở phiên Claude Code
  on the web; kéo cả 38 skill và không ghim commit.
- **`npx skills add mattpocock/skills`.** Chép không ghim, không sha256, không lock; cần `node` mà repo không dùng.
- **Giữ tên không tiền tố.** Đụng tên built-in (`/code-review`, `/pr`), không nhìn ra nguồn khi gọi — như ADR-0028
  §"Phương án đã loại".
- **Kiểm đụng tên mục giữa các lock.** Thừa khi tiền tố đã không lồng nhau (d); thêm nhánh mà không bắt thêm lỗi nào.

## Hệ quả

- Lệnh mới `/mp-retro`, `/mp-writing-for-agents`. `mp-writing-for-agents` là model-invoked (mô tả 103 ký tự nạp mỗi
  phiên); `mp-retro` user-invoked.
- Luật cấm 5 mở rộng: `.claude/skills/mp-*` và `docs/integrations/mattpocock.LICENSE` là bản dẫn xuất.
- Thêm nguồn thứ ba: một lock mới + `make vendor LOCK=…`; không sửa script trừ khi nguồn có khuôn mới thật sự.
- `retro` nhắc `CODING_STANDARDS.md` (repo không có) — ghi chú đầu tệp chỉ đường về `AGENTS.md`/`/gate`, cùng cách
  ADR-0028 xử lý câu "80%" của `python-testing`.
- Rủi ro: con số `BUDGET_TOTAL` lấy từ nguồn thứ cấp (xem "Đo"). Nếu Claude Code công bố trần thật thấp hơn, hạ số ở
  cổng.

## Đo

Đo ngày 2026-10-10 tại gốc repo. Nguồn: ECC v2.2.2 @ `c70874fae9eb0e5ad0365beb7e2955899fd1d30f`; mattpocock/skills
1.3.1 @ `49dd158d1076134a641b33efb035946536778336`.

| Đo | Trước | Sau |
|---|---|---|
| tệp ECC (`measured.files`) | 25 | 25 — 24 tệp `.md` đổi đúng 2 dòng ghi chú (48+/48−), `ecc.LICENSE` không đổi |
| mô tả ECC | 5 035 / 6 000 | 5 035 / 6 000 |
| tệp mattpocock | — | 4 (`mp-writing-for-agents/{SKILL.md,SKILL-MECHANICS.md}`, `mp-retro/SKILL.md`, giấy phép), 21 132 byte |
| mô tả mattpocock | — | 147 / 1 500 |
| mô tả skill + lệnh toàn `.claude/` (25 tệp sau) | 4 813 | 4 960 / `BUDGET_TOTAL` 8 000 |
| mô tả agent `.claude/agents/*` (không vào trần chung) | 2 783 | 2 783 |
| `upstream` mattpocock theo `paths` | — | 38 skill, 0 lệnh, 0 agent |
| quét coupling lớp 1 trên 2 mục chọn | — | 0 dấu hiệu |
| `company.assetscan` trên tệp `mp-*` | — | 0 phát hiện `high` |

**Trần chung — chưa kiểm được.** Nguồn thứ cấp (thảo luận cộng đồng, không phải tài liệu Anthropic) nói Claude Code
cắt danh sách mô tả skill quanh ~15,5–16k ký tự. Chưa có tài liệu chính thức, chưa đo trực tiếp; cổng lấy nửa con số
đó (8 000) để còn chỗ cho mô tả lệnh dựng sẵn và plugin builtin.

**Chưa đo:** phiên Claude Code thật liệt kê `/mp-retro`, `/mp-writing-for-agents` (cơ chế quét `.claude/skills/` giống
ECC, ADR-0028 §"Đo"); mức `--restricted` với `mp-*` (dự kiến 0 như `ecc-*`).

## Liên quan

- `scripts/vendor_skills.py`; test `platform/console/tests/test_vendor_skills.py`; cổng offline
  `platform/console/tests/test_cong_vendor.py`; job CI `vendor-check`.
- `docs/integrations/ecc.lock.json`, `docs/integrations/mattpocock.lock.json`.
- ADR-0028 (vendor ECC chọn lọc), ADR-0027 §4 (`--restricted`), ADR-0022 (`company.assetscan`).
- `docs/thi-hanh/ib1.md` V1–V5; `docs/reports/2026-10-10-doi-chieu-ba-infographic.md` §3.
