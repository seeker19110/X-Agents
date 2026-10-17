# ADR-0064: orchestrator tự chạy phép đo NFR (perf/a11y) đã khai, trên staging đã deploy

## Bối cảnh
Checklist Gate 3 có hai mục `perf` ("perf so NFR trên staging pass") và `a11y` ("axe + thủ công trên staging pass").
Hub không có nguồn bằng chứng máy nào cho hai mục này. Chúng chỉ là trường `perf`/`a11y` tự khai trong `review-results`
của QA.

Hub thật (QLKH-DD-CSV, 2026-10-17): REL-126 lên production với perf DD-N4 và a11y DD-N6 "CHƯA ĐO". Phiên chính ký
Gate 3 với điều kiện không ký nghiệm thu (UAT) khi chưa có số đo thật. CR-DDCSV-NFR-001 nhờ agent đo, nhưng sandbox của
builder chỉ có python3 (không node, không k6, không docker) và không ra được staging. Spec quay vòng giữa ba hướng: k6
(AGPL), "đóng ở KHÔNG ĐO ĐƯỢC", và "ai chạy?". Chủ dự án chọn: **hub tự đo**.

Khảo sát repo khách: script đo đã có sẵn. `tests/perf/export_p95.py` chỉ dùng thư viện chuẩn Python (5 luồng, p95 ≤ 2 s,
mã thoát 0/1/2). `web/` có `npm run a11y` (vitest + axe-core trên jsdom, 0 vi phạm serious/critical). Thứ thiếu là một
bên đáng tin chạy chúng trên môi trường đã deploy và ghi kết quả.

## Quyết định
1. **Khai báo ngoài repo, cạnh file env bí mật** (cùng chỗ và cùng hàng rào với ADR-0061 và override compose của
   ADR-0061 bổ sung 2026-10-17):
   - File là `<compose project staging>.measure.json` trong `COMPANY_DEPLOY_ENV_DIR`.
   - Nằm trong repo khách, hoặc nhóm/người khác ghi được (`mode & 0o022`), thì là lỗi cấu hình. Ai ghi được file này
     là chạy được lệnh trên máy hub.
   - Hình dạng:
     `{"measures": [{"id", "kind": "perf|a11y|other", "command": [argv], "timeout_s", "env": {"TÊN": "KHOÁ_FILE_ENV"}}]}`.
   - Không thêm trường vào spec. Thêm trường thì phải đổi schema `approved-specs` và prompt của `product`, tức quy
     trình 7 bước kèm ghi eval bằng model thật, chỉ để khai một danh sách lệnh của chính khách.
2. **Orchestrator chạy, không phải agent**:
   - **Khi nào:** trước lượt QA hồi quy trên staging (`verify.evidence_before`, cùng chỗ với `evidence.run`), và chỉ
     khi `evidence.deploy` của staging `ok` và có cổng. Thiếu một trong hai thì ghi bản `unverified` nói rõ.
   - **Chạy thế nào:** cwd là cây đúng sha RC (`_release_root`). `{base_url}` được thay bằng
     `http://127.0.0.1:<cổng đã map>`. Env là `clean_env()` cộng đúng các biến khai trong `env`, giá trị lấy từ file env
     bí mật. Khoá khai mà không có trong file thì ghi `unverified`, không chạy.
   - **Kết quả:** mã thoát 0 là đạt. Timeout tối đa `MAX_TIMEOUT_S` = 1800 s, file khai không nới được.
3. **Bằng chứng một nguồn**:
   - Mỗi phép đo một audit `measure.run` (actor `orchestrator`), có `release_id`, `id`, `kind`, `ok`, `exit_code`,
     `elapsed_s`, `sha`, lệnh đã khai (placeholder, không giá trị), đuôi stdout đã che giá trị bí mật, và
     `verified_by=orchestrator`.
   - Review QA nhận `evidence.measure` do orchestrator gắn và đè mọi bản model tự khai.
   - Phép đo không đạt không tự hạ verdict QA, giống DAST (ADR-0047 §3): ngưỡng nào chặn release là quyết định ở gate.
4. **Gate đọc số máy**: hồ sơ gate release và gate nghiệm thu có mục "Đo NFR". Mỗi phép đo hiện lần đo mới nhất, với
   ĐẠT / KHÔNG ĐẠT / KHÔNG ĐO ĐƯỢC. Chưa đo thì nói thẳng là chưa đo.
5. **Đo lại một RC đang chạy**: lệnh `python -m company.measure run <release> --repo <repo khách>` dùng đúng
   `verify.measure_run` và ghi audit vào bus thật. Mã thoát: 0 đạt hết, 1 có phép đo không đạt, 2 không có gì để đo. Lệnh
   này cho RC đã lên staging trước khi có file khai (REL-126).

## Hệ quả
- Lệnh đo chạy trên máy hub, ngoài sandbox, cùng mức tin cậy với script deploy `process` (ADR-0040) và compose của khách
  (ADR-0039). Cả hai cũng chạy code của khách trên máy trực. Rào chắn ở đây: người vận hành chọn lệnh (không phải
  model), file ngoài repo và chỉ chủ ghi được, env đã lọc, có timeout.
- Phép đo chạy đồng bộ trong vòng orchestrator và chặn vòng tới hết `timeout_s`.
  `no-ky-thuat: đo chặn vòng orchestrator tới 1800 s mỗi phép đo, ổn với 1 worker và vài phép đo mỗi RC, quay lại khi
  một RC khai quá 3 phép đo hoặc hub chạy nhiều dự án song song.`
- Đo a11y bằng `npm` cần node và `node_modules` trên máy hub. Cài phụ thuộc là việc của người vận hành, không phải của
  ADR này. Repo khách không có `package-lock.json` thì `npm ci` không lặp lại được, và đó là finding cho khách.
- Dữ liệu đo (vd lớp 6.280 dòng của DD-N4) phải có sẵn trên staging. Nạp dữ liệu là việc của sản phẩm (CR-DDCSV-NFR-001
  §ADR-NFR1-04), hub không nạp thay.

## Phương án đã bỏ
- **Trường `runtime.measure` trong spec**: đúng chỗ về lâu dài, nhưng kéo theo đổi schema, đổi prompt và quy trình 7 bước
  có model thật, trong khi lệnh là của khách và đã có sẵn. Khi nhiều dự án cần đo thì chuyển sang hướng này.
- **Agent chạy đo trong sandbox**: sandbox không ra được staging, và nới mạng cho agent viết code là nới quá rộng.
- **Phiên chính đo tay**: nhanh, nhưng là lời khai chứ không phải bằng chứng máy (luật cấm 8).

## Test
`tests/test_measure.py`: đọc và chặn file khai, chạy và che giá trị, `unverified` khi thiếu khoá hoặc staging chưa deploy,
gắn vào review QA, audit `measure.run`, hồ sơ gate release và nghiệm thu, CLI đo lại. Hai chiều: trước khi sửa thì mọi ca
đỏ (module chưa có, `KeyError: 'measure'`, hồ sơ không có "## Đo NFR"); sau khi sửa thì xanh.
