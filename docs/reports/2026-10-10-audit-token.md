# Audit tiêu thụ token — 2026-10-10

Căn cứ `main@2dd4750` (#395), nhánh `claude/sharp-hypatia-x143xc`. Yêu cầu của người dùng: "audit, tối ưu giảm lượng
token tiêu thụ nhưng vẫn giữ chất lượng tốt". Không gọi model thật trong phiên này (luật cấm 4; phiên cloud không có
tài khoản model của công ty), nên mọi số dưới đây lấy từ ba nguồn đo được offline:

- `evals/recordings/*.json` của software-company — 131 lời gọi thật, ghi 2026-09-13 qua provider `claude-code`
  (`claude-opus-5`, `claude-sonnet-5`), mỗi lời gọi mang `input_tokens`/`output_tokens` do CLI báo.
- Prompt thật của từng lời gọi eval: phát lại bản ghi qua `ReplayClient` bọc một lớp ghi độ dài `system`/`user`/
  `schema` (script trong scratchpad phiên, không commit).
- `make assetbudget` trước và sau sửa.

## 0. Kết luận một đoạn

Những đòn bẩy rẻ đã có từ trước (prompt cache hai breakpoint, skill theo pha ADR-0037, `skills_core` rút gọn,
`fit` theo token, `_prune` giữ 3 lượt, `--restricted`, effort theo tier). Phần còn lại chia hai loại.
(1) **Thước đo sai**: `assetbudget`, công cụ duy nhất repo dùng để canh prompt tĩnh, báo dư 1,13–1,90 lần so với chuỗi
model thật sự nhận, và lại chia 4 ký tự/token trong khi lõi chia 3,2. Đã sửa trong PR này, kèm cấu hình coverage
làm output cổng gọn hơn. (2) **Token thật nằm ngoài prompt**: input mỗi lời gọi gấp 2,3–5,9 lần prompt ước lượng,
output gấp 1,2–6,5 lần phần chữ trả về. Hai hệ số này lớn hơn mọi phần cắt được trong skill. Muốn giảm chúng mà
không mất chất lượng thì phải đo bằng model thật (`make eval-record`, `RUNS=3`). Phiên này không làm được việc đó,
nên chúng nằm ở §4 thành khuyến nghị có thứ tự, chưa đổi gì.

## 1. Prompt tĩnh thật (sau sửa thước)

`AgentSpec.system_prompt(pha)` thật, chia `CHARS_PER_TOKEN = 3.2` của lõi. Cột "thước cũ" là con số `assetbudget`
báo trước PR này (cộng toàn văn file skill, chia 4).

| Lượt | ký tự thật | token ước | ngân sách | chiếm | thước cũ (ký tự) | cũ / thật |
|---|---:|---:|---:|---:|---:|---:|
| qa[review] | 38 175 | 11 929 | 60 000 | 20% | 59 534 | 1,56 |
| product[research] | 50 308 | 15 721 | 100 000 | 16% | 65 778 | 1,31 |
| product[plan] | 44 702 | 13 969 | 100 000 | 14% | 61 442 | 1,37 |
| builder[platform] | 45 244 | 14 138 | 120 000 | 12% | 63 765 | 1,41 |
| supervisor | 17 923 | 5 600 | 40 000 | 14% | 24 575 | 1,37 |
| builder[data] | 23 540 | 7 356 | 120 000 | 6% | 44 633 | 1,90 |

Ba nguồn gây lệch của thước cũ: `skills_core` bị tính toàn văn trong khi lõi chỉ nạp `## Quy trình` + `## Checklist`;
skill mà pha nạp đầy đủ bị tính thêm bản rút gọn cấp agent, trong khi prompt thật đã bỏ bản đó (`_load_phases`,
"pha thắng", vd `observability` của builder[platform]); front matter của file skill cũng bị tính. Keeper: 539–1 019
token/lượt, không đáng tối ưu.

Không có đoạn văn nào lặp **trong cùng một lượt**: 10 dòng ≥ 60 ký tự lặp giữa các file, nhưng đều là khối "Ngưỡng
dừng / audit-log" của sáu agent khác nhau, mỗi lượt chỉ nạp một bản. Muốn cắt prompt tĩnh nữa là cắt nội dung,
không phải khử trùng.

## 2. Token thật mỗi lời gọi (bản ghi eval 2026-09-13)

Prompt ước lượng = (`system` + `user` + 2 × `schema`) / 3,2. Schema tính hai lần vì `ClaudeCodeClient` gửi nó cả trong
user message (`hint`) lẫn qua `--json-schema`. Phần chữ trả về = ký tự `text` / 3,2.

| Agent | tier / effort | prompt ước | input ghi | × | phần chữ trả về | output ghi | × |
|---|---|---:|---:|---:|---:|---:|---:|
| product | strong / high | 13 335 | 72 411 | 5,4 | 1 598 | 9 494 | 5,9 |
| builder | strong / high | 13 313 | 54 722 | 4,1 | 4 164 | 13 768 | 3,3 |
| security | strong / high | 10 481 | 55 207 | 5,3 | 1 231 | 7 674 | 6,2 |
| ops | standard / medium | 7 768 | 45 990 | 5,9 | 810 | 5 227 | 6,5 |
| qa | standard / medium | 12 157 | 27 928 | 2,3 | 540 | 1 476 | 2,7 |
| supervisor | light / low | 6 961 | 20 364 | 2,9 | 257 | 316 | 1,2 |

Cộng 131 lời gọi: 6 065 306 token input, 1 289 502 token output. Trong prompt của các ca eval, `system` chiếm
khoảng 96% số ký tự; payload eval chỉ khoảng 1,2k ký tự. Đổi `json.dumps(indent=2)` của user message sang dạng gọn chỉ
bớt 8,8% user, tức **0,3%** prompt.

Chưa đo được nguyên nhân của hệ số input. Bản ghi không giữ `num_turns` và `cached_input_tokens`
(`RecordingClient` chỉ lưu `input_tokens`/`output_tokens`), nên chưa tách được phần nào là lượt CLI ép
`--json-schema`, phần nào là lượt sửa JSON, phần nào là cache read (vốn rẻ hơn nhiều so với input thường). Có ba giả
thuyết, chưa kiểm: (a) mỗi lượt nội bộ của `claude -p` gửi lại toàn bộ prompt cộng output của lượt trước; (b) trần
`CLI_NO_TOOL_TURNS = 6` cho phép nhiều vòng sửa JSON; (c) phần lớn hệ số là cache read nên chi phí thật nhỏ hơn con số
thô. Hệ số output cao ở effort `high` khớp với việc token suy nghĩ cũng bị tính vào output, nhưng `ops` (effort
`medium`) cũng ở mức 6,5, nên effort không giải thích hết.

## 3. Đã sửa trong PR này

| # | Sửa | Đo hai chiều |
|---|---|---|
| T1 | `assetscan budget` đo đúng `system_prompt(pha)` qua `xagents_core.registry.load_agent` (tách ra từ `load_agents`, hành vi `load_agents` giữ nguyên) | trước: 3 failed (`qa[review]` 59 534 ≠ 38 175); sau: 45 passed |
| T2 | `assetscan.CHARS_PER_TOKEN` lấy từ `xagents_core.context` (3,2), không còn tự đặt 4 | trước: `assert 4 == 3.2`; sau: xanh |
| T3 | `skip_covered = true` cho `console` và `xagents-core`, giống ba gói còn lại: cổng thôi in 37 dòng file 100% (core 23, console 14) vào ngữ cảnh mỗi lần chạy | test mới ở `test_cong_repo.py`: trước đỏ với `['platform/console', 'platform/xagents-core']`; sau xanh |

Không sửa prompt, skill hay agent nào, nên bản ghi eval, golden và `.claude/agents/sc-*` giữ nguyên. T1 làm con số
`assetbudget` nhỏ đi. Sàn 50% của `test_agent_that_khong_de_prompt_tinh_an_qua_nua_ngan_sach` vì thế canh đúng thứ
nó định canh; con số cao nhất là 20% (`qa[review]`).

## 4. Khuyến nghị chưa làm — xếp theo lợi / rủi ro

Từ R2 trở đi đều đổi thứ model thấy. Muốn làm thì đi đủ bảy bước `CONTRIBUTING.md` §3 và ghi lại eval bằng model
thật `RUNS=3`, so `pass_rate` trước/sau theo `evals/thresholds.yaml`. Riêng R2 và R3 đổi adapter hoặc cấu hình
chứ không đổi `system`/`user`, nên `prompt_key` không đổi và `--replay` **không** bắt được nếu chất lượng tụt. Với hai
mục đó, ghi lại eval là cách duy nhất để biết.

1. **R1 — ghi `num_turns`, `cached_input_tokens`, `cache_write_tokens` vào bản ghi eval và `audit-log`.** Không đổi
   prompt nên không cần ghi lại eval. Đây là điều kiện trước của R2–R3, vì không tách được hệ số 2,3–5,9 thì mọi
   "tối ưu" phía sau chỉ là đoán.
2. **R2 — schema chỉ đi một đường trong `ClaudeCodeClient`.** Mỗi lượt nội bộ hiện mang 2,3–4,4k ký tự schema hai
   lần. Phương án: bỏ phần `hint` toàn văn, chỉ giữ mô tả trường cho những schema `--json-schema` không tự giải
   thích được. ADR-0026 cố ý để hai đường ("`--json-schema` là lớp ÉP, không phải lớp giải thích"), nên đổi phải
   có ADR và số `pass_rate`.
3. **R3 — effort theo lượt, không chỉ theo tier.** Những lượt strong/high cho output gấp 3,3–6,2 lần phần chữ trả về.
   Có thể thử `medium` cho `product[intake]` và `security` trước, vì cả hai trả về ít chữ. Đây là cấu hình
   (`effort:` trong `llm.yaml`), người vận hành tự thử được trên máy mà không cần PR.
4. **R4 — cắt skill nặng nhất ở lượt đắt nhất.** `product[research]` nạp đầy đủ `ui-ux-design` (10 151 ký tự) và
   `accessibility` (5 605); `qa[review]` nạp đầy đủ `accessibility`, `code-ownership`, `observability`. Mục nào
   lượt đó không chủ quản thì có thể chuyển sang `skills_core` của pha (ADR-0008 vẫn cần một agent chủ quản nạp đầy
   đủ). Gộp luôn R6 vào cùng lần ghi lại eval.
5. **R5 — phiên Claude Code của chính repo.** Mỗi phiên nạp sẵn `AGENTS.md` + `CLAUDE.md` = 22 070 ký tự (≈ 6,9k
   token), cộng mô tả của 18 subagent, 12 skill và 11 command trong `.claude/` = 6 006 ký tự (≈ 1,9k token). Mục
   "Bảy điều" của `CLAUDE.md` (1 935 ký tự, ≈ 600 token) lặp lại luật đã có trong `AGENTS.md`. Đó là nhấn mạnh có
   chủ ý; bỏ hay giữ là việc người quyết.
6. **R6 — JSON gọn trong user message** (`build_user_message`, `indent=2` → `separators=(",", ":")`): chỉ 0,3% prompt
   eval, nhưng blackboard production lớn hơn payload eval nhiều. Không đáng một lần ghi lại eval riêng; làm cùng R4.
