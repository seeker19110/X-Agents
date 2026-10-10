# keeper — công ty con bảo trì

Một trong năm package của workspace X-Agents. Khách hàng số 0 và mặc định của nó là **chính repo này**.

**Trạng thái: chạy được, chưa qua canary.** BT1–BT7 đã merge — package có mã thật, test riêng và CLI
`keeper.cli` (`run`, `watch`, `gate`, `drift`, `publish`) chạy được. Cái CHƯA có nằm ở cuối README này, đọc trước
khi tin bất kỳ con số nào.

- Quyết định: [`docs/adr/0006-cong-ty-bao-tri-keeper.md`](../../docs/adr/0006-cong-ty-bao-tri-keeper.md)
- Đặc tả triển khai, PR theo PR: [`docs/DAC-TA-KEEPER.md`](docs/DAC-TA-KEEPER.md) (BT0–BT8)
- Trạng thái từng gói BT (một chỗ duy nhất): [`../../docs/thi-hanh/keeper.md`](../../docs/thi-hanh/keeper.md) §B
- Vận hành: [`../../docs/HUONG-DAN-VAN-HANH.md`](../../docs/HUONG-DAN-VAN-HANH.md) §6

## Nó làm gì

Không viết lại Renovate / CodeQL / Scorecard — nó *tiêu thụ* đầu ra của chúng làm tín hiệu, rồi làm phần không
công cụ nào ngoài kia làm được: quyết định **cái gì đáng sửa, sửa theo luật của repo này, và chứng minh đã sửa**.

Sáu khối, **mười** agent, một human gate `keeper`:

(ADR-0006 và bản đầu của README viết "tám" — đếm lại bảng dưới
ra mười; khối `watch` một mình đã có ba. Con số cũ là lỗi đếm, không phải một danh sách khác.)

| Khối | Agent |
|---|---|
| `watch` | `dependency-scout`, `health-monitor`, `drift-detector` |
| `triage` | `triager` |
| `engineering` | `patcher`, `refactorer` |
| `quality` | `regression-guard`, `security-auditor` |
| `release` | `release-clerk` |
| `supervisor` | `keeper-supervisor` |

## Bốn thứ khiến nó khác một chồng GitHub Action

1. **Bằng chứng đo hai chiều bắt buộc** — không có output *tắt bản sửa → đỏ / bật lại → xanh* thì ticket không
   rời pha quality. `AGENTS.md` bắt buộc §4 thành cổng máy.
2. **Bậc rủi ro tự động** — patch dev-dependency tự merge; chạm `xagents-core`/`agents/`/CI thì bắt buộc gate người.
3. **Ngân sách thay đổi** — trần PR mỗi tuần và đúng một PR mở, để chính công ty này không gây bão PR.
4. **Sổ nợ có đáo hạn** — mọi thứ hoãn đều mang ngày; quá hạn thì escalate.

## Chạy

```bash
cd companies/keeper
uv run pytest -q --cov                                    # test riêng của package

# một vòng vá theo danh sách ticket — CHẠY KHÔ là mặc định của việc đọc, không chạm một byte nào
uv run python -m keeper.cli run --tickets tickets.json --root ../.. --dry-run

# vòng lặp watch → triage → patch → verify → gate? → release (một nhịp rồi thoát)
uv run python -m keeper.cli watch --db keeper.sqlite --repo ../.. --max-ticks 1

# sổ human gate: xem gate chờ, rồi đóng bằng quyết định của NGƯỜI
uv run python -m keeper.cli gate --db keeper.sqlite list
uv run python -m keeper.cli gate --db keeper.sqlite approve KT-12 --by human:truc-ban --reason "bằng chứng đủ"

# drift: bản dẫn xuất/golden lệch nguồn, CHANGELOG còn chỗ trống số PR — thuần cục bộ, như job CI drift-check
uv run python -m keeper.cli drift --repo ../..

# biến ý định mở PR (`pr.intent`) của MỘT ticket thành PR thật: git push + gh pr create (BT8 canary);
# patch phải commit sẵn trong worktree của ticket — lệnh tự mở lại worktree đó từ --repo
uv run python -m keeper.cli publish --db keeper.sqlite --repo ../.. <ticket_id>
```

Hàng đợi ticket, ngân sách còn lại, sổ nợ quá hạn và gate chờ cũng đọc được ở tab **Công ty bảo trì** của
console (`cd platform/console && uv run python -m console`). Ô nào ghi *"chưa chạy lần nào"* là chưa chạy thật — tab đó
cố ý **không** hiện số 0.

## Eval prompt

Bốn agent có bộ ca eval (`evals/<agent>.yaml`), mỗi bộ ≥ 5 ca đo **phán xét có thể sai** chứ không đo hình
dạng schema: `triager` (xếp `risk_tier`), `security-auditor` (phân loại phát hiện), `release-clerk` (soạn dòng
`CHANGELOG.md`), `keeper-supervisor` (phản ứng của watchdog). Sáu agent còn lại chưa có bộ ca — lý do ở
docstring `src/keeper/evals.py`; tóm tắt: đầu ra của chúng do CODE quyết (`scout.py`, `health.py`, `drift.py`)
hoặc được gác bằng bằng chứng đo hai chiều chứ không bằng một `expect` trong YAML.

```bash
make eval-replay                        # như CI: phát lại từ bản ghi, KHÔNG gọi model, không chạm mạng
make eval-record AGENT=triager          # model THẬT, ghi evals/recordings/triager.json (bước 3, CONTRIBUTING §3)
```

`make eval-record` cần **`keeper/llm.yaml`** — file này là bí mật (khoá API hoặc thư mục đăng nhập CLI) nên nó
**gitignored, không bao giờ commit**; bản mẫu commit được là `llm.example.yaml`, trong đó có sẵn khối
`backends:` đã dùng để ghi bộ bản ghi hiện tại (provider `claude-code`, gói subscription đã `claude login`,
không cần `ANTHROPIC_API_KEY`).

Hai cổng, hai lý do đỏ: `evals/recordings/REQUIRED.txt` gác **bản ghi** (thiếu, hoặc ghi ở phiên bản prompt cũ)
và `evals/thresholds.yaml` gác **điểm chấm** (tụt dưới sàn đã đo, hoặc bộ ca bị thu nhỏ). Đổi prompt mà chưa
ghi lại eval thì job CI `keeper-eval-replay` đỏ — đó là răng của luật "prompt là code".

Hai biến môi trường: `KEEPER_MAX_PR_PER_WEEK` (trần PR bảo trì mỗi tuần, mặc định 5) và
`KEEPER_GATE_APPROVERS` (danh sách người duyệt gate). Không đặt biến thứ hai thì allowlist TẮT — four-eyes vẫn
còn, nhưng bất kỳ ai khác người tạo gate cũng ký được. Chi tiết ở `HUONG-DAN-VAN-HANH.md` §6.4.

## Cái gì CHƯA có

Ba chỗ dưới đây là thật sự chưa có, không phải "sắp xong" — ghi ra để không ai đọc phần trên rồi tưởng công ty
này đã tự bảo trì được repo:

- **6/10 agent chưa có bộ ca eval.** Hạ tầng đã dựng và bốn agent phán xét đã có bản ghi thật (mục *Eval
  prompt* ở trên), nhưng `dependency-scout`, `health-monitor`, `drift-detector`, `patcher`, `refactorer`,
  `regression-guard` thì chưa — có chủ ý, không phải bỏ quên.
- **Canary chưa qua.** Nghiệm thu của BT8 là một chu kỳ thật trên chính X-Agents: `keeper` tự mở đúng một PR
  bảo trì có bằng chứng đo hai chiều, và PR đó merge. Đã thử hai lần, chưa lần nào tới PR: 2026-09-12 repo sạch
  đúng loại lỗi keeper vá được; 2026-09-13 chạy thật tới ngay trước `publish` trên tín hiệu thật `pr-280` rồi dừng
  đúng ở cổng ngân sách I3 vì PR #246 đang mở. #246 đã merge — lần thứ ba chờ người chạy và người merge
  (`docs/TASK-PACK.md`, sổ "Việc để lại").
- **Vòng `watch` không tự mở PR.** `open_pr()` chỉ soạn `release-notes` + ghi `pr.intent` vào `audit-log`;
  `github.py` thuần chỉ đọc (bất biến I1). Đường ghi hẹp đã chốt là `publish.py` (`git push` nhánh ticket +
  `gh pr create`), nhưng chỉ chạy khi người/script gọi `keeper.cli publish <ticket_id>`.
