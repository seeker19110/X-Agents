# ADR-0003: keeper có một thước đo NGOÀI theo khuôn GAIA — scorer chính thức, sàn không tụt, tụt là tín hiệu

Ngày: 2026-10-11 · Trạng thái: được chấp nhận · Phạm vi: `companies/keeper` · Nguồn ý tưởng: đối chiếu CAMEL-AI/OWL
(`docs/thi-hanh/cm1.md`), mục "tập benchmark GAIA làm thước đo ngoài cho `keeper`".

## Bối cảnh

Mọi thước chất lượng prompt của `keeper` đều do chính repo đặt. Đo trên `main@db96a3a` (#425):

| # | Hiện trạng | Chỗ |
|---|---|---|
| 1 | 4/10 agent có bộ ca eval, tổng **21** ca (`triager` 6, ba agent còn lại 5), tiêu chí `expect` viết tay | `evals/*.yaml`, docstring `evals.py` §"Vì sao chỉ 4/10" |
| 2 | Sàn điểm `thresholds.yaml` đo **một lần** 2026-09-09, cả bốn 1.00, sàn 0.95 — không so được với hệ nào ngoài repo | `evals/thresholds.yaml:5-7` |
| 3 | Không có bộ đề nào ngoài repo, không có công thức chấm nào ngoài `xagents_core.evals.check` | `grep -rn "gaia\|benchmark" companies/keeper` → 0 trước ADR này |
| 4 | OWL/Workforce (CAMEL-AI) công bố 69,09 % (README, 2025-04-18) và 69,70 % (arXiv 2505.23885) trên GAIA validation — con số chỉ có nghĩa nếu chấm cùng công thức và cùng prompt hệ thống | `docs/thi-hanh/cm1.md` §A |

Hệ quả: một lần ghi lại eval cho điểm cao hơn không nói prompt tốt hơn hay tiêu chí dễ hơn. Không có điểm tham chiếu
ngoài thì "xanh" của `keeper-eval-replay` là xanh trong hệ quy chiếu của chính nó.

## Quyết định

1. **`keeper/benchmark.py`** nạp đề theo đúng khuôn `metadata.jsonl` của GAIA (`task_id`, `Question`, `Level`,
   `Final answer`, `file_name`), chấm bằng **`question_scorer` chép nguyên công thức của leaderboard GAIA** (số: bỏ
   `$ % ,` rồi so float; danh sách: tách `,`/`;`, so từng phần tử; chuỗi: bỏ khoảng trắng + dấu câu, thường hoá), và hỏi
   model bằng **prompt hệ thống chính thức** của bài báo (`GAIA_SYSTEM_PROMPT`, nguyên văn tiếng Anh). Đổi một
   trong ba thứ này là điểm không còn so được với bảng công khai.
2. **Hai chế độ như `evals.py`**: `--record` (model thật → `benchmarks/gaia/recordings/<tên>.json`) và `--replay`
   (chấm lại từ bản ghi, không mạng). CI và test không gọi model (`AGENTS.md` cấm 4).
3. **Sàn `benchmarks/gaia/floor.yaml`** như `evals/thresholds.yaml`: `--strict` đỏ khi accuracy < `min_accuracy`, số đề
   < `min_tasks`, level dưới sàn riêng, **hoặc sàn còn `null`** — chưa đo không phải đạt; bộ rỗng cũng không đạt.
4. **Tụt sàn là `Signal(kind="benchmark")`**, đi vào `triager` như mọi tín hiệu khác; `risk.RISK_RULES` thêm hàng
   `benchmark-regression` → tier `high` (ticket chờ người). `keeper` không có patch nào sửa được điểm benchmark; nó chỉ
   bảo đảm điểm tụt thì có người biết, không im lặng trong một file JSON.
5. **Cố ý không làm**: solver không có tool (không đọc file đính kèm, không web) — đề có `file_name` được nói rõ
   trong prompt; không tải GAIA vào repo (dataset gated, giấy phép); không nối job CI cho tới khi sàn được đo bằng
   model thật (job đỏ vô ích); không đặt sàn từ `sample.jsonl` (5 đề tự soạn, chỉ để chạy khuôn).

## Phương án đã loại

- **Thêm ca eval cho 6 agent còn lại.** Vẫn là thước tự làm; docstring `evals.py` đã đo vì sao sáu vai đó không có
  phán xét để chấm (`regression-guard` 1/5 vì làm *đúng*). Không giải quyết "không so được với ai".
- **Chạy OWL/CAMEL như một agent GAIA đầy đủ (toolkit trình duyệt, code, tài liệu).** Cho điểm so được với bảng
  công khai nhưng đo một hệ khác, không đo prompt + model của `keeper`; kéo theo ~17 nhóm phụ thuộc của `camel-ai`
  và mạng ra ngoài trong CI (ADR gốc 0010 cấm). Để lại cho ngày keeper có tool thật.
- **Viết scorer "gần đúng" bằng `check` của core.** Rẻ hơn, nhưng lệch công thức là lệch điểm (ví dụ GAIA so chuỗi
  trong danh sách **giữ** dấu câu, so chuỗi đơn **bỏ** dấu câu) — chính xác là chỗ một con số 69 % thành vô nghĩa.

## Hệ quả

- `SignalKind` thêm `benchmark` (model + `topics/schemas/maintenance-signals.json`); `RISK_RULES` 8 → 9 hàng, thứ tự
  high-trước-low giữ nguyên.
- `README.md` gốc: keeper 853 → 890 test; `CODEMAP.md` keeper thêm dòng `benchmark.py`.
- Chờ người: tải GAIA validation, `--record`, điền `floor.yaml`, rồi mới nối CI/`watch` (`benchmarks/gaia/README.md`).
- Nhận biết nếu sai: sau khi đo, điểm dao động giữa hai lần `--record` cùng model lớn hơn 0.05 → sàn phải đặt theo
  `RUNS=N` như `CONTRIBUTING.md` §3, không phải một lần đo; hoặc không ai dùng số này sau hai tháng → bỏ module,
  đừng để một thước không ai đọc.
