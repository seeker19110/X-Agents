# benchmarks/gaia — thước đo ngoài cho keeper theo khuôn GAIA

Vì sao có thư mục này: bốn bộ `evals/*.yaml` chấm agent bằng tiêu chí do chính repo đặt. GAIA là bảng điểm công
khai (OWL/Workforce của CAMEL-AI báo 69,09–69,70 % trên validation, tháng 4–5/2025), có công thức chấm chính thức và
khuôn đề cố định — `keeper.benchmark` lấy đúng ba thứ đó (ADR keeper 0003). Đây là thước cho **prompt + model** của
keeper, không có tool: đề kèm file sẽ được nói rõ là không đọc được.

## Trong thư mục

| File | Là gì |
|---|---|
| `sample.jsonl` | 5 đề **tự soạn** đúng khuôn `metadata.jsonl` của GAIA để chạy thử khuôn và test offline — **không phải GAIA**, không được dùng để đặt sàn hay so với bảng công khai |
| `floor.yaml` | sàn điểm; `null` = chưa đo (`--strict` đỏ) |
| `recordings/<tên>.json` | câu trả lời đã ghi bằng model thật (tạo bởi `--record`; không commit bản ghi của bộ mẫu) |

## Chạy

```bash
cd companies/keeper
uv run python -m keeper.benchmark gaia --replay benchmarks/gaia/recordings/<tên>.json            # chấm lại, không gọi model
uv run python -m keeper.benchmark gaia --replay benchmarks/gaia/recordings/<tên>.json --strict   # + so sàn
uv run python -m keeper.benchmark gaia --dataset <GAIA>/2023/validation/metadata.jsonl \
    --record benchmarks/gaia/recordings/<model>-<ngày>.json --level 1 --tier standard             # model thật (cần llm.yaml)
```

## Việc chờ người (máy có key)

1. Xin quyền và tải `gaia-benchmark/GAIA` trên Hugging Face (dataset gated); dùng `2023/validation/metadata.jsonl`
   (165 đề, có đáp án). Không commit dataset vào repo (giấy phép và kích thước).
2. Chạy `--record` với model keeper đang dùng; đọc bảng theo level.
3. Điền `floor.yaml` (`min_accuracy`, `min_tasks`, `levels`) làm tròn xuống 0.05, ghi `note` ngày + model; commit bản ghi.
4. Khi đã có sàn, nối `--replay --strict` vào CI của keeper và `benchmark_signal()` vào `keeper watch` (chưa nối: sàn
   chưa đo thì job chỉ đỏ vô ích).
