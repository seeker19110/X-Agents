# ADR-0061: biến bí mật cho `docker compose` của khách đi qua file env NGOÀI repo

## Bối cảnh
`deploy()` (ADR-0039) chạy compose file của khách với `env=clean_env()`. `clean_env` (`xagents_core.sandbox`,
`SECRET_ENV`) bỏ mọi biến có tên dạng `*PASSWORD*`, `*TOKEN*`, `*SECRET*`, `*_DSN`, `*DATABASE*`… khỏi env của lệnh
con. Với agent thì đúng, vì agent không được thấy khoá của máy trực. Nhưng hệ quả là compose của khách không bao giờ
nhận được một biến bí mật nào, dù người vận hành đã đặt nó cho tiến trình hub.

Hub thật (QLKH-DD-CSV, 2026-10-16, REL-099): sau finding gitleaks, compose của khách bỏ giá trị mặc định
`qlkh-local` và đổi sang `${QLKH_COMPOSE_DB_PASSWORD:?chưa đặt - xem .env.example}`. Thay đổi đó đúng hướng, vì không
còn mật khẩu nằm trong repo. Nhưng deploy staging từ đó luôn hỏng với
`required variable QLKH_COMPOSE_DB_PASSWORD is missing a value`. `reviewer:tu-dong` giữ gate với hint "đặt secret
cho staging bằng kho secret hoặc biến môi trường của runner". Hub chưa có đường nào làm được việc đó.

## Quyết định
1. **Một thư mục do người vận hành khai**: `COMPANY_DEPLOY_ENV_DIR` trong env của máy trực, ví dụ
   `~/.config/x-agents/deploy-env/`. Không đặt biến này thì hành vi giữ y như trước.
2. **Tên file do code ghép**: `<compose project>.env`, với compose project là `project_name(project_id, env)`, ví dụ
   `company-qlkh-dd-csv-staging.env`. Model không chọn được file. File của staging không lọt sang production, vì
   production có tên project khác.
3. **Đi qua `--env-file`, không qua env tiến trình**:
   - Có file thì mọi lệnh con compose (`up`, `ps`, `logs`, `down`) mang `--env-file <đường dẫn tuyệt đối>`.
   - Compose dùng các biến trong file đó để nội suy chính compose file.
   - Giá trị không đi vào env của hub, của lệnh con hay của agent. `clean_env` giữ nguyên.
4. **Fail-closed** (ném `DeployError`, `verify.py` ghi `deploy_failed` kèm lý do):
   - File mà nhóm hoặc người khác đọc được (`mode & 0o077`), giống cách ssh từ chối khoá: phải `chmod 600`.
   - File nằm trong repo khách: builder ghi và commit được repo, nên secret ở đó là secret agent đọc được.
5. **Bằng chứng ghi đường dẫn, không ghi giá trị**: `DeployRecord.env_file` →
   `release-events.evidence.deploy.env_file`. Reviewer thấy được lượt deploy đã dùng file nào.

## Phương án đã loại
- **Cho một danh sách tên vượt `clean_env`** (vd `COMPANY_DEPLOY_PASS_ENV=QLKH_COMPOSE_DB_PASSWORD`). Giá trị phải
  nằm trong env của tiến trình hub, nên mọi lệnh con khác (agent, tool) đều chỉ cách một lỗi lọc là thấy được nó.
  Đây cũng là chỗ thứ hai phải giữ đồng bộ với `SECRET_ENV`.
- **File `.env` trong repo khách.** Compose tự đọc file này, nhưng builder ghi được repo. Luật cấm 3 cũng cấm commit
  secret.
- **Kho secret ngoài (Vault, SOPS).** Đúng cho production nhiều máy. Hub là self-hosted một máy (ADR gốc 0031/0032),
  file 0600 cạnh `hub.env` cùng mức bảo vệ với chính `hub.env`. Khi có nhiều máy thì quay lại.
- **Áp cho mode `process` (ADR-0040).** Script của khách tự đọc env. Đưa secret vào env của script là lặp lại phương
  án thứ nhất. Chưa có khách dùng `process` cần secret, nên chưa làm.

## Hệ quả
- Người vận hành tạo file, mỗi dòng một `KEY=giá trị`, rồi `chmod 600`. Sau đó duyệt gate REL-* với
  `decision:redeploy`.
- Postgres chỉ đặt mật khẩu ở lần khởi tạo volume. Volume staging cũ dựng bằng mật khẩu khác thì phải
  `docker compose -p <project> down -v` một lần. Đó là dữ liệu staging, không phải dữ liệu thật.
- Test: `tests/test_deploy_env_file.py` (hai chiều cho cả ba hàng rào).

## Bổ sung 2026-10-16: ops nhận sự thật máy về việc dựng staging
`deploy()` chỉ chạy khi ops khai `deployed` (ADR-0039). Hub thật (QLKH-DD-CSV, REL-105): sau khi file secret đã có, ops
vẫn khai `pending_human` vì threat-model cũ ghi "staging thiếu QLKH_COMPOSE_DB_PASSWORD". Không container, không DAST,
security chặn RC. Ops không đo được env của hub.

Quyết định: `STAGING_ROUTE` có enrich `_with_deploy_readiness` (`orch/enrich.py`). Đầu vào lượt staging mang
`deploy_readiness` (`verified_by=orchestrator`): `mode`, `project`, `compose_file` dò được trong cây tích hợp,
`secret_env_file` có/không, và `secret_env_file_error` khi file sai quyền hoặc nằm trong repo. Chỉ có/không và đường dẫn,
không bao giờ giá trị. Test: `tests/test_ops_deploy_readiness.py`.


## Bổ sung 2026-10-16 (2): che giá trị bí mật trong bằng chứng deploy, có số đo
Hub thật (QLKH-DD-CSV, REL-109): security chặn RC với TM-SEC10-05 (High), "mật khẩu DB có thể lộ vào log", vì RC
không có bằng chứng giảm nhẹ. `DeployRecord` ghi `logs_tail` (log container) và `error` (stderr compose) lên bus.
`orch/verify.py` còn đọc thẳng hai trường đó vào audit. App in chuỗi kết nối DB thì mật khẩu vào `release-events`.
Phiên chính đã đo tay, chỉ đếm: 0 lần trong `company.sqlite`/WAL, `company.artifacts`, journal của orchestrator và
repo khách. Nhưng đó là lời khai, không phải bằng chứng trong RC.

Quyết định: có file env bí mật thì `deploy()` dựng MỌI bản ghi qua `_redacted`.
- Mọi giá trị dài ≥ `SECRET_MIN` (6) của file được thay bằng `***` trong `error`, `logs_tail` và `smoke`, ngay lúc dựng
  `DeployRecord`, trước khi bất kỳ ai đọc.
- Bản ghi mang `secret_redaction = {values, hits, verified_by=orchestrator}`: số giá trị được canh, số chỗ đã che. Đây
  là bằng chứng máy sinh cho security; `hits=0` ở lần chạy sạch vẫn được ghi.
- Không có file env bí mật thì không có trường này.

Test: `tests/test_deploy_env_file.py` §bổ sung. Hai chiều: trước khi sửa, 3 ca mới đỏ (giá trị nằm nguyên trong
`logs_tail`/`error`, chưa có `secret_redaction`); sau khi sửa thì xanh.
