# ADR-0039: Deploy thật bằng `docker compose` — `deployed` là container đang chạy, không phải lời khai

Trạng thái: Accepted · Ngày: 2026-09-08 · Thực hiện mục **D1** của `docs/archive/DAC-TA-NANG-CAP-2026-09.md`
(bảng §4 ghi "ADR-0034" là số **đặt trước** đã bị dùng cho việc tách máy trạng thái — xem cảnh báo cuối §8 của
đặc tả đó). Nối tiếp ADR-0029/0036 (smoke là bằng chứng), ADR-0035 (sandbox, fail-closed), ADR-0027 (giao hàng
thật), ADR-0031 (`runtime` trong spec).

## Bối cảnh

Ba mảng giao hàng đã có bằng chứng máy sinh: git (tag + nhánh `company/release`, ADR-0027), PR cho khách review
(ADR-0038), smoke đối chiếu verdict của qa (ADR-0029/0036). Riêng **deploy thì chưa**: `release-events` mang
`status=deployed` vì route đặt `env` và agent nói đã xong — không có tiến trình nào của sản phẩm còn sống sau
lượt ấy. `run_smoke` (ADR-0029) khởi động sản phẩm, probe, rồi **giết** — đúng cho việc chấm "chạy được", sai
cho việc "đang chạy".

Hệ quả đo được: gate `release` hỏi người ký duyệt production dựa trên một trạng thái không ai kiểm được, và
`REL-019` từng kẹt vì không phân biệt "chưa deploy" với "deploy hỏng".

Ba ràng buộc không được phá:

- **Không chạm `main` của khách** (ADR-0011, ADR-0027 §5). Deploy chạy trong worktree tích hợp, không merge,
  không push.
- **Model chỉ khai, code mới chứng** (`CLAUDE.md` ranh giới 1). `deployed` phải do orchestrator kết luận từ
  trạng thái container + smoke, không từ `payload` của agent `ops`.
- **Không âm thầm tụt hạng bảo vệ** (ADR-0035). Thiếu runtime container thì nói thiếu, không giả vờ đã deploy.

## Quyết định

1. **`runtime.deploy` mới, tuỳ chọn** trong `approved-specs` (`topics/schemas/approved-specs.json`, cùng chỗ
   `command`/`port`/`health` của ADR-0031): đường dẫn file compose trong repo khách (mặc định dò
   `docker-compose.yml`, `compose.yaml`). Không có file và không khai → `deploy_skipped` kèm lý do; **không**
   coi là deploy thành công.

2. **Hai môi trường là hai compose project tách hẳn**, tên `company-<project_id>-<env>` (`env ∈ staging |
   production`), cổng lấy từ compose file của khách chứ orchestrator không tự chọn — orchestrator chỉ **đọc**
   cổng đã map (`compose ps --format json`) để probe. Hai project không dùng chung volume: khách muốn chia
   dữ liệu thì tự khai trong compose, đó là quyết định của họ chứ không phải mặc định của công ty.

3. **`deployed` là kết luận ba phần, thiếu một phần là không deployed**:
   `compose up -d` thoát 0 **và** `compose ps` cho mọi service ở trạng thái `running` **và** smoke probe vào
   cổng đã map trả đúng `expect_status`. Đủ ba → `release-events` `status=deployed`,
   `evidence.deploy = {project, services[], container_ids[], port, image_digests[], started_at,
   smoke:{...}, verified_by: "orchestrator"}`. Thiếu bất kỳ phần nào → `status=deploy_failed`, evidence ghi
   phần nào hỏng, và orchestrator chạy `compose down` để **không bỏ lại container nửa sống** trên máy trực.

4. **Chọn runtime theo đúng khuôn ADR-0035, fail-closed.** `COMPANY_DEPLOY` = `auto` (mặc định) | `compose` |
   `off`. `auto`: có `docker` (hoặc `COMPANY_DEPLOY_RUNTIME`) trên PATH thì deploy, không có thì
   `deploy_skipped` kèm tên biến người vận hành phải đặt. `compose` khai đích danh mà thiếu binary →
   **lỗi**, không tụt về "coi như xong". `off`: bỏ qua, giữ hành vi cũ.

5. **Production chỉ sau gate `release`.** Không thêm cổng mới: `PROD_ROUTE` đã là đường duy nhất tới
   `env=production` (ADR-0037 §1.2) và `env` là của route chứ không phải lời khai. Deploy chỉ mở rộng thứ
   **xảy ra** trên đường đó.

6. **Ranh giới lệnh.** Chỉ bốn lệnh con được phép: `up -d`, `ps`, `logs --tail`, `down`. argv do code ghép,
   không nội suy chuỗi từ payload của model; env lọc qua `clean_env` (bỏ `GH_*`/`GITHUB_*`/`SECRET_ENV` như
   ADR-0035); `--project-name` do code đặt nên model không đổi được nó để giẫm sang môi trường khác. File
   compose là **của khách** — công ty chạy nó chứ không sinh nó.

7. **`docker compose` KHÔNG đi qua `Sandbox`.** Nhốt daemon-client vào container là vô nghĩa (nó gọi ra
   `/var/run/docker.sock`, tức chính quyền cao nhất). `github_pr.py` đã có ngoại lệ cùng hạng (ADR-0038 §4);
   `deploy.py` là ngoại lệ thứ hai, khai trong `CHI_GH`-tương đương của
   `tests/test_sandbox_noi_vao_cong_ty.py` với lý do ghi tại chỗ.

## Cách đo — và vì sao CI không chạy container thật

Đo trên máy phiên viết ADR: `docker` **CLI có** nhưng **không có daemon** (`/var/run/docker.sock` không tồn
tại). CI: `ubuntu-latest` có docker, nhưng ma trận `unit` còn **`windows-latest`**, không chạy được container
Linux. Bắt CI dựng compose thật nghĩa là hoặc bỏ Windows khỏi ma trận, hoặc rải `skipif` — cả hai đều đổi một
cổng đang xanh lấy một cổng giòn.

Nên chia làm hai mức, đúng cách repo đã làm với `Sandbox` và với B8/S7:

- **CI (mọi PR)**: runner compose được **tiêm vào** như `which` của `sandbox_from_settings` — test giả lập
  `up -d` thoát 0 / thoát khác 0, `ps` có service `exited`, smoke đỏ, thiếu binary. Đo được cả bốn nhánh của
  quyết định 3 và 4 mà không cần daemon.
- **Chạy thật (một lần, có báo cáo)**: nghiệm thu D1 là `docs/reports/2026-09-xx-deploy-that.md` — một REL của
  dự án mẫu lên production bằng compose, kèm `evidence.deploy` thật có container id và smoke. Cùng khuôn
  nghiệm thu của B8/S7: thứ không nhốt được vào CI thì nhốt vào một báo cáo có số.

## Hệ quả

- `docs/TRUC-VA-DUNG-KHAN.md` phải thêm lệnh dừng khẩn cho container (`docker compose -p company-<id>-<env>
  down`), và cảnh báo hai project chiếm cổng của máy trực — đây là rủi ro §6 mà đặc tả nâng cấp đã nêu trước.
- Máy trực nay chạy tiến trình **sống lâu** của sản phẩm khách, không còn chỉ là tiến trình ngắn của lượt agent.
  Ai dừng orchestrator không còn đồng nghĩa với dừng sản phẩm.
- Prompt `ops` pha `deploy` **không đổi**: deploy do code làm, agent không được khai `deployed`. Nếu prompt phải
  đổi thì đó là dấu hiệu ranh giới 1 bị phá — dừng lại xem lại thiết kế.
- Chưa làm, cố ý: rolling update / zero-downtime; nhiều máy; registry riêng; deploy không-docker (systemd, k8s).
  Cả bốn là ADR sau, cùng khuôn `deploy(project, env, spec_runtime) -> DeployRecord`.

## Đo hai chiều (ghi trong commit khi cài)

- Bỏ kiểm `compose ps` (chỉ tin `up -d` thoát 0) → ca "service exited ngay sau up" phải ĐỎ.
- Bỏ smoke khỏi điều kiện → ca "container up nhưng health 500" phải ĐỎ.
- Bỏ `compose down` ở nhánh hỏng → ca "deploy hỏng không bỏ lại container" phải ĐỎ.
- `COMPANY_DEPLOY=compose` mà `which` trả `None` → phải raise, không trả `skipped`.

## Bổ sung 2026-10-13 — `up -d --build`: container phải chạy code của đúng sha RC

Đo hub thật 2026-10-13 (QLKH-DD-CSV): REL-022 → REL-034 cùng `container_ids` `48ef5cef466d`/`58bb1578c860` qua năm sha
tích hợp (4ef9665 → 2660f02 → 93bf08b → 849f67a → 4b53291). Project compose cố định theo env (§2) nên image của service
`build:` mang tên project; `up -d` trần thấy image đã có thì dùng lại, container cũ chạy tiếp. DDCSV-26 (mount
`POST /auth/login`) đã merge mà DAST vẫn 404 ba RC liền — bằng chứng `verified_by=orchestrator` ghi sha mới nhưng đo
code cũ, đúng loại lời khai ADR này sinh ra để chặn.

- `deploy()` chạy `up -d --build` trên cây RC (`_release_root`, checkout riêng theo sha): image dựng lại từ đúng sha, image
  đổi thì compose tự tạo lại container. Service chỉ có `image:` (vd `db`) không bị đụng.
- Chế độ `process` (ADR-0040) không đổi: script của khách tự dựng.
- Đo hai chiều: bỏ `--build` ⇒ `test_up_dung_lai_image_tu_cay_rc_moi_lan_deploy` đỏ.

## Bổ sung 2026-10-16 — duyệt `redeploy` sau `deploy_failed` thì chạy lại thật

Hub thật (QLKH-DD-CSV, REL-119): Gate 3 đã ký, deploy production hỏng vì máy trực thiếu file env bí mật (ADR-0061).
Người sửa cấu hình rồi duyệt escalation `decision:redeploy|close`, nhưng `_rerun_release` chỉ nhận release-event cuối
`pending_human` ⇒ không chạy lại gì, gate đóng mà RC nằm im. Nay `deploy_failed` cũng được chạy lại, cùng route với
env của release-event cuối; production vẫn chỉ khi Gate 3 đã ký (không thêm, không bớt cổng nào). Đo hai chiều: trước
khi sửa ca production và staging đỏ (`_rerun_release` trả False), sau khi sửa xanh; ca "không vượt Gate 3" xanh cả hai chiều.
