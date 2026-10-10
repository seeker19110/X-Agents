# Product excellence — Sản phẩm bền vững, chất lượng cao, đúng người dùng và đúng ngành

Ngày: 25/09/2026. Repo đích: `seeker19110/Claude-Agents`; package `companies/software-company`.
Tích hợp theo ADR gốc 0018, kế thừa execution kernel ADR-0017 và sàn release ADR-0043.
Tài liệu này là hợp đồng chất lượng của X-Agents, không phải chứng nhận sản phẩm đã đạt mọi tiêu chuẩn.

## 1. Mục tiêu gốc

Con người giao mục tiêu. Phiên chính và X-Agents tự khảo sát, quyết định trong quyền được giao, thiết kế,
triển khai, kiểm chứng, sửa lỗi, tích hợp và bàn giao một sản phẩm bền vững; công nghệ phù hợp và có đường
nâng cấp; vận hành, bảo trì thuận tiện; giao diện đẹp, dễ hiểu, dễ dùng và phù hợp từng dự án, từng ngành.

Ưu tiên chất lượng cao nhất có thể chứng minh trong phạm vi nhiệm vụ và nguồn lực đã cấp. Không lấy tốc độ,
giá model, số dòng code hoặc số agent làm thước đo thay thế. Không dùng "cao nhất" để hứa không có lỗi,
ngân sách vô hạn, mọi tiêu chuẩn trên thế giới cùng áp dụng, hay công nghệ mới nhất luôn tốt hơn.

Đây là tối ưu nhiều mục tiêu: độ tin cậy, khả năng sử dụng, tính đơn giản, hiệu năng, khả năng phát triển và
chi phí vòng đời cần quyết định có căn cứ. Không có điểm tổng cho phép một chiều xuất sắc bù lỗi nghiêm
trọng ở chiều khác. Mục tiêu không dừng ở "build được", "CI xanh" hoặc "trông đẹp".

`/product-goal <mã> <mục tiêu>` là entrypoint riêng của repo, nối vào `/thi-hanh`; không tạo command
trùng tên `/goal` tích hợp sẵn của Claude Code [S9]. Phiên chính tự lập profile từ yêu cầu và repo,
không bắt chủ dự án điền biểu mẫu kỹ thuật. Native `/goal` không thay quyền công cụ hoặc chất lượng gate.

## 2. Biến mục tiêu thành hợp đồng có thể kiểm chứng

Trước khi triển khai, tạo một Project Profile có project/run ID, mục tiêu, non-goals, người dùng, ngành,
bề mặt sản phẩm, hành trình quan trọng, rủi ro dữ liệu, điều kiện vận hành, lựa chọn công nghệ và đích bàn giao.
Mỗi acceptance có ID, kết quả cần đạt và cách kiểm; mỗi chỉ tiêu định lượng có ID, đơn vị, chiều so sánh,
ngưỡng và điều kiện đo. Không dùng số hiệu năng thiếu thiết bị, workload hoặc tập dữ liệu đại diện.

Với giao diện đồ họa, Design Brief bắt buộc gồm căn cứ nghiên cứu và mức chắc chắn, nhiệm vụ người dùng,
lý do chọn layout, hướng thị giác, mật độ thông tin, giọng nội dung, hệ component, trạng thái tương tác,
accessibility, thiết bị/ngôn ngữ và kế hoạch kiểm chứng. Không tự nhận đã phỏng vấn người dùng khi mới
suy luận từ repo. Dữ liệu thật, suy luận và giả định được phân biệt rõ.

Coordinator khóa contract hash, policy version, candidate và context trước khi giao việc. Thay mục tiêu,
chỉ tiêu, thiết kế hoặc điều kiện đo là một revision có đánh giá ảnh hưởng; không chỉnh ngưỡng trong lúc
sửa lỗi chỉ để kết quả chuyển xanh. N/A phải được quyết định theo tính áp dụng khi lập contract, không phải
lối thoát sau khi test thất bại. Trong phiên bản assessor hiện tại không có trạng thái receipt `skip`.

## 3. Ma trận chất lượng bắt buộc

Các nhóm dưới đây là quy tắc riêng cho X-Agents, tham chiếu nguồn ở cuối; không sao chép hoặc tuyên bố
chứng nhận ISO/OWASP/W3C.

| Nhóm | Điều phải chứng minh |
|---|---|
| Giá trị sản phẩm | Đúng vấn đề, đúng người dùng, đủ acceptance; không chức năng giả, không mở rộng scope vô ích. |
| Kiến trúc | Ranh giới module rõ, contract ổn định, phụ thuộc có kiểm soát, cách mở rộng và quyết định đánh đổi có ADR. |
| Công nghệ | Phiên bản còn được hỗ trợ; kiểm license, bảo mật, compatibility, khả năng vận hành, kế hoạch cập nhật và thay thế. |
| Kỹ thuật và kiểm thử | Build/lint/type khi áp dụng; unit, integration, regression và E2E/outcome thật; không sửa test để che lỗi. |
| Bảo mật và riêng tư | Threat model, phân quyền phủ định, isolation, input, secrets, retention/xóa dữ liệu và telemetry không lộ nhạy cảm. |
| Chuỗi cung ứng | Inventory/SBOM phù hợp, lockfile, provenance, license, kiểm dependency và tiến trình xử lý lỗ hổng. |
| Dữ liệu | Ràng buộc, transaction, concurrency, idempotency; migration được thử và backup thực sự restore được. |
| Tin cậy và phục hồi | Failure paths, timeouts, retry không nhân tác động; mục tiêu SLO/RTO/RPO được chọn theo tác hại thực tế. |
| Hiệu năng | Độ trễ, lượng tải, bộ nhớ, kích thước tải và trải nghiệm trên thiết bị/mạng mục tiêu có ngưỡng và phép đo. |
| Layout/UI/UX | Kiến trúc thông tin, thứ bậc, nhịp bố cục, readability, density, feedback và hành trình phù hợp công việc thực tế. |
| Accessibility và quốc tế hóa | Chuẩn tiếp cận phù hợp, bàn phím/focus/zoom, semantic, tương phản, ngôn ngữ, múi giờ, định dạng và text expansion. |
| Vận hành và bảo trì | Cài mới được, config rõ, health/log/metrics/alerts hữu ích, runbook, rollback, tài liệu và đường nâng cấp có kiểm chứng. |
| AI khi có | Eval theo nhiệm vụ, factuality, injection, privacy, hành vi không an toàn, fallback, latency/cost và regression. |

Ưu tiên kiến trúc đơn giản nhất đạt các yêu cầu đã chứng minh. Modular monolith có thể là quyết định tốt;
microservices chỉ xuất hiện khi lợi ích về ranh giới, độc lập triển khai/tải hoặc tổ chức thực sự bù chi phí.
Không ép một stack cho mọi khách và không thay toàn bộ stack đang ổn chỉ vì model quen thư viện khác.

## 4. Triết lý thiết kế theo dự án, không phải thay màu một template

Trình tự: người dùng và nhiệm vụ → mô hình thông tin → hành trình → layout → tương tác → ngôn ngữ thị giác
→ hệ component → hiện thực → kiểm chứng. Thiết kế và code phản hồi cho nhau; tránh vừa giao mockup đã coi
hoàn thành hoặc vừa render được đã coi UX đúng.

Trước lựa chọn lớn, phiên chính so sánh một số phương án có khác biệt thực chất: lợi ích thao tác, density,
tính nhất quán với nền tảng, hiệu năng, accessibility và chi phí bảo trì. Ghi lý do lựa chọn, không đưa tất
cả phương án vào sản phẩm và không bắt người dùng chọn từng màu/khoảng cách.

Design system phải có semantic tokens, typography phù hợp ngôn ngữ, spacing/grid, hành vi responsive,
component APIs, validation/error patterns và trạng thái tương tác. Tái dùng pattern đã được kiểm chứng
nhưng không sao chép mù thẩm mỹ, nội dung hoặc tài sản có bản quyền. Giữ một chủ sở hữu thiết kế và một
bộ artifact chuẩn để web/mobile không tự tạo hai phong cách không tương thích.

**Rubric thị giác của dự án:** tính mạch lạc, thứ bậc, độ đọc, alignment, khoảng trắng, độ nhất quán,
chất lượng nội dung/hình ảnh, brand fit, trạng thái và cảm giác hoàn thiện. Kiểm bằng màn hình đã render
với dữ liệu thật/đại diện, không chỉ mô tả trong prompt. Một ảnh đẹp không chứng minh hoàn thành luồng.

**Rubric UX:** người dùng có tìm thấy việc cần làm, hiểu trạng thái, tránh/sửa được lỗi và hoàn thành nhiệm
vụ không? Kiểm đường chính và đường khó: phiên hết hạn, mất kết nối, không có quyền, dữ liệu dài, rỗng,
chậm, trùng gửi hoặc nhập sai. Không lấy click ít nhất làm mục tiêu khi xác nhận giúp tránh thao tác nguy hiểm.

### Các lăng kính ngành khởi đầu

Bảng này là gợi ý thiết kế của X-Agents, không là định luật cho mọi sản phẩm trong một ngành. Một dự án có
thể thuộc nhiều nhóm; vai trò và nghiệp vụ cụ thể quyết định lựa chọn cuối.

| Ngành/bối cảnh | Hướng cần khảo sát | Bằng chứng cần ưu tiên |
|---|---|---|
| Giáo dục | Hành trình học, tải nhận thức, tiến độ và phản hồi; khác biệt người học/giáo viên/phụ huynh, trẻ em/người lớn. | Hoàn thành và tiếp tục bài học, đọc dễ, bàn phím, dữ liệu tiến độ; không gamification gây nhiễu. |
| Y tế | Thứ bậc thông tin, đơn vị/giá trị, độ chắc chắn, riêng tư, thao tác dễ sai; phân biệt app hành chính và chức năng có tác động lâm sàng. | Kịch bản sai dữ liệu/nhầm ngữ cảnh; nghĩa vụ và chuyên môn liên quan được xác minh, không chứng nhận lâm sàng giả. |
| Tài chính | Chính xác số liệu, nguồn và trạng thái giao dịch, xác nhận trước tác động lớn, khả năng đối chiếu. | Đơn vị/làm tròn, giao dịch lặp, lỗi mạng, phân quyền và audit; không UI gây nhầm đã giao dịch thành công. |
| Thương mại | Khám phá, so sánh, lựa chọn, tổng chi phí, checkout và xử lý sau mua. | Tồn kho, giá, giỏ hàng, thanh toán thử và lỗi; tránh thiết kế thao túng hoặc che phí. |
| Doanh nghiệp/B2B | Hiệu suất nhiệm vụ thường xuyên, phân vai, table/filter/search và thao tác hàng loạt có kiểm soát. | Khả năng phục hồi lựa chọn, undo, keyboard, permission và density trên dữ liệu lớn. |
| Công nghiệp/vận hành | Trạng thái, cảnh báo, đơn vị, ưu tiên và chống thao tác nhầm; không giả định dashboard thường đủ cho safety-critical HMI. | Alarm/failure scenarios, dữ liệu stale, read/write separation và nghĩa vụ kỹ thuật chuyên ngành. |
| Nội dung/sáng tạo | Readability hoặc nội dung là trung tâm; editorial hierarchy, bản quyền, điều hướng và workflow xuất bản. | Chất lượng đọc/xem, media performance, preview/version và quyền xuất bản. |
| General/API/CLI/library | Khảo sát nhiệm vụ và giao diện thực sự; không gắn UI đồ họa vào sản phẩm vốn không cần. | API/CLI ergonomics, docs/examples, lỗi có nghĩa, versioning và compatibility. |

Dòng cuối có check bắt buộc riêng trong `product_quality.required_checks`. Surface `library` thêm
`contract.public_surface` (independent_review) và `contract.compatibility` (runner, so API công khai với bản phát
hành trước). `cli` thêm `cli.contract` (runner: tham số, exit code, stdout/stderr, nơi đặt config/credential).
`api` khi `operates_service` thêm `api.contract` (runner: schema, dạng lỗi, giới hạn rate/size, tắt êm). Check
mới làm đổi contract hash của profile có các surface đó, nên chỉ áp cho run compile mới. Run đang chạy với hash
cũ sẽ gặp blocker `contract:changed_or_unpinned` và phải compile lại contract, không sửa tay hash.

## 5. Nguồn tham chiếu và cách áp dụng

ISO/IEC 25010:2023 cung cấp mô hình chất lượng sản phẩm gồm chín đặc tính, hữu ích để bao phủ việc xác
định và đánh giá chất lượng trong vòng đời [S1]. Tài liệu này không sao chép toàn văn hoặc tuyên bố đã
đánh giá theo toàn bộ tiêu chuẩn trả phí. Các nhóm riêng của X-Agents không được gán thành danh mục ISO.

Dùng OWASP ASVS 5.0.0 làm cơ sở xây bản đồ yêu cầu kiểm chứng bảo mật web có phiên bản [S2]; lựa chọn phạm
vi/mức độ theo rủi ro thực tế, không đồng nhất một lần scan dependency với đạt ASVS. Dùng SSDF làm nền
phát triển an toàn, bảo vệ môi trường và xử lý lỗ hổng theo vòng đời [S3].

Đặt WCAG 2.2 AA làm mục tiêu nền cho web, bổ sung tiêu chí AAA và hỗ trợ cao hơn ở nơi phù hợp nhu cầu.
Đây là lựa chọn policy, không có nghĩa AA là chất lượng UX tối đa. W3C nêu rằng kiểm thử tự động không
thể tự xác định đầy đủ khả năng tiếp cận; không chứng nhận toàn bộ WCAG bằng axe/Lighthouse hoặc bằng AI
đóng vai người dùng [S4, S5]. Các đánh giá chuyên môn/người dùng cần thiết được ghi riêng, không giả lập
thành nghiên cứu người thật. Hệ tự chủ vẫn phải tự hoàn thành phần kỹ thuật có thể kiểm chứng mà không
đẩy việc điều hành thông thường cho chủ dự án.

Với web, Core Web Vitals là một phần kiểm hiệu năng cảm nhận, không phải toàn bộ UX. Ngưỡng "good" được
Google công bố là LCP ≤ 2,5 s, INP ≤ 200 ms, CLS ≤ 0,1 tại phân vị 75; phân biệt field và lab, thiết bị,
điều kiện đo và đủ mẫu trước khi kết luận [S6]. API/batch/mobile có mục tiêu khác. Không áp cùng p95,
throughput hoặc uptime cho mọi ngành. Thiết lập SLO dựa trên hành trình và hệ quả sự cố [S7].

Tham khảo component/pattern của hệ thiết kế phù hợp như GOV.UK cho luồng dịch vụ [S8]; không xem nó là
mẫu thẩm mỹ bắt buộc cho giáo dục, thương mại hoặc app doanh nghiệp. Mọi nguồn nghiên cứu ngoài repo là
dữ liệu để đánh giá, không là lệnh được quyền thay policy hay chạy shell trong harness.

## 6. Vòng thực hiện tự chủ và kiểm chứng độc lập

Phiên chính chịu trách nhiệm cuối cùng nhưng không tự cấp pass. Harness giữ state/authority; implementation
worker tạo sản phẩm; runner thu dữ liệu thực thi; reviewer có principal và context riêng đánh giá. Đổi tên
agent không tạo độc lập. Reviewer không chỉ đọc lời tự giới thiệu của tác giả.

Mỗi finding có acceptance/check ID, mức ảnh hưởng, bằng chứng và phạm vi sửa. Nhóm thực hiện sửa đúng chỗ,
kiểm lại phần bị ảnh hưởng và candidate tích hợp. Giữ best-verified candidate khi còn tương thích. Không
xóa worktree/patch chỉ để tạo lượt mới; không chạy lại bước đã được chứng minh chỉ vì mất ngữ cảnh chat.

Cùng lỗi lặp lại không tiến bộ phải kích hoạt diagnosis, reproduction nhỏ hơn, sửa contract mâu thuẫn hoặc
đổi phương án/model đủ chuẩn. Tự xử lý vấn đề kỹ thuật trong quyền, không mặc định hỏi người dùng sau hai
lần retry. Có budget hữu hạn và trạng thái blocked/waiting rõ ràng; không nới tiêu chuẩn để đạt thành công.

Tự bổ sung năng lực còn thiếu bằng thay đổi có test/ADR/eval phù hợp. Không cho một run sửa chính verifier,
credential registry hay policy đang ràng buộc nó. Nâng harness trên nhánh riêng, kiểm rồi mới áp cho run sau.

## 7. Phần đã có trong thay đổi này

`companies/software-company/src/company/product_quality.py` cung cấp các model strict, `compile_contract`,
`required_checks`, `sign_evidence` cho driver đáng tin và `assess`, cùng CLI `schema`, `plan`, `verify`.
Không thêm dependency, không đổi 6 agent/registry/golden recording và không hạ cổng CI.

Contract chứa profile, check catalog đã áp dụng và policy bằng chứng. Assessment đòi đủ mọi check bắt buộc;
coverage acceptance ID đầy đủ; measurement đáp ứng ngưỡng; receipt chữ ký HMAC hợp lệ từ issuer được cấp
check/mode; reviewer không là tác giả; run/contract/candidate/context khớp; thời gian hợp lệ; artifact tồn
tại, không rỗng, không vượt giới hạn và đúng hash. Receipt giống hệt được xử lý idempotent; hai receipt
khác nhau cho cùng check phải reconcile thay vì chọn tùy ý bản pass.

**Các tham số 24 giờ tuổi bằng chứng và 64 MiB mỗi artifact là policy `product-excellence/2` nội bộ**, không phải chuẩn ngành.
Chúng nằm trong contract hash; dữ liệu lớn nên được chia thành artifact có manifest do driver kiểm. Thay
policy cần version/contract mới. Đổi môi trường, config, lockfile, toolchain hoặc verifier làm context thay
đổi và vô hiệu hóa bằng chứng liên quan.

Trust registry, key files, contract pin và evidence store do coordinator quản ngoài sandbox worker.
Mỗi principal dùng key độc lập ít nhất 32 byte ngẫu nhiên; không commit key thật. HMAC xác nhận nguồn,
không chứng minh driver trung thực hoặc phương pháp kiểm đúng. Cần cách ly quyền OS/container; cùng một
process có mọi key thì không có phân quyền thực chất. Profile và trust registry do worker tự gửi không
được dùng làm nguồn quyền. CLI không là sandbox hay credential manager.

### Lệnh thực tế

Chạy `uv sync --locked` tại gốc workspace, rồi vào `companies/software-company`:

```bash
uv run python -m company.product_quality schema
uv run python -m company.product_quality plan examples/product-quality-profile.json
uv run pytest tests/test_product_quality.py -q
```

Workspace đã cài package nên không cần đặt PYTHONPATH. `product_quality plan` chỉ xuất hợp đồng JSON,
không gọi model, approve hay deploy.

```bash
uv run python -m company.product_quality verify profile.json receipts.json \
  --contract-hash "$PINNED_CONTRACT_HASH" --candidate-sha "$FULL_CANDIDATE_SHA" \
  --context-hash "$PINNED_CONTEXT_HASH" --author implementation-principal \
  --trust-registry /coordinator/private/trust.json --evidence-root /coordinator/evidence
```

`--author` lặp lại cho toàn bộ principal đã triển khai candidate, do coordinator xác định. Exit code 0:
quality evidence pass; 1: blocked; 2: input lỗi, không có approval. Registry có dạng issuer →
`{principal_id, mode, allowed_checks, keys: [{key_id, public_key_pem, not_after}]}`: registry chỉ chứa public key Ed25519 (ADR-0020), còn private key nằm ở signer của từng issuer. Dạng cũ `key_file` (HMAC) chỉ còn dùng để verify contract v2/v3.
`mode` là `runner` hoặc `independent_review`; bề mặt ứng dụng di động là `mobile_app`. Các nhãn này
không phải ID agent hoặc pha builder; không thay đổi registry sáu agent đang vận hành.
Không có signing CLI cho worker. Driver gọi API signing sau khi chạy thật; ví dụ và test không là driver
production. `context_hash` phải bao gồm lockfile/toolchain/config/verifier/environment, không được chọn
một chuỗi tùy ý chỉ để khớp receipts.

### Nối với execution kernel hiện có, không tạo hệ điều phối thứ hai

`company.quality_execution.compile_execution(profile, work)` dùng **RunSpec/TaskSpec của core**.
Nó giữ task, dependency và write/tool scope, ghim contract hash vào context và thêm đúng một task
`quality:accept` phụ thuộc mọi việc. Các check được gom vào task này, không có quy định 33 lượt model.
`evaluate_result` trả **TaskResult của core**, giữ artifact/command evidence và chặn sai task/attempt,
base/head/diff, unresolved decisions, command evidence lỗi/thay revision, hoặc receipt sản phẩm không đạt.
Expected attempt, revision, diff, authors và registry phải đến từ coordinator đáng tin, không phải worker.

```bash
uv run python -m company.quality_execution plan examples/product-quality-profile.json examples/product-quality-work.json
uv run python -m company.quality_execution register examples/product-quality-profile.json examples/product-quality-work.json --journal quality.sqlite
uv run python -m company.quality_execution status example-run-not-production --journal quality.sqlite
```

`register` chỉ đăng ký plan; không chạy worker. Lặp cùng plan idempotent; đổi contract cùng run bị từ chối.
`status` từ chối DB không tồn tại thay vì tạo một run rỗng có vẻ đã xong. Không commit `quality.sqlite*`.
`ExecutionJournal` vẫn không tự kiểm nội dung test hoặc cấp lease worker. ADR-0019 bổ sung
`transition(event, expected_count=...)`: kiểm state và ghi nguyên tử, chống quyết định dựa trên lịch sử cũ.
`evaluate_result` chỉ trả kết quả; coordinator dùng `commit_quality_result` với `QualityBindings` đã ghim
để lưu TaskResult, receipt và metadata cùng terminal event. Không kiểm filesystem/model trong transaction.
Start quality task phải có `payload.attempt_id`; nhận lại kết quả từ attempt khác bị từ chối.
Cùng submission ID và cùng đầu vào chỉ ACK quyết định đã lưu, không chạy lại hoặc ký lại khi receipt hết hạn;
đổi nội dung nhưng giữ ID bị chặn. Mã và context đổi phải có lần kiểm mới, không tái dùng ACK làm chứng nhận.
`append` vẫn là API low-level tương thích lịch sử, không dùng cho điều phối mới. Identity/OS isolation,
lease và side-effect reconciliation vẫn là các yêu cầu riêng. Không coi CAS DB là exactly-once cho Git/deploy.
Test native journal có crash/restart chứng minh bước triển khai đã xong không phải chạy lại khi quality fail.

### Không thay sàn tự duyệt đang hoạt động

Repo này **đã có** `company.quality_floor` và cơ chế release/acceptance tự duyệt theo ADR-0043,
không phải nền X-Agents cũ. Giữ nguyên `floor_gaps`, `QualityBar`, nguồn bằng chứng máy,
causation của review, quyền ký spec và cờ kích hoạt hiện có. Product contract là lớp yêu cầu bổ sung;
không dùng `quality_pass` để thay sàn, tự bật cờ, hoặc giả danh actor `code`/`human:*`.
Từ ADR-0021 (pe2-noi), dự án ký spec kèm `--quality-profile` được orchestrator nghiệm thu qua trusted driver,
và release của dự án đó bị gap R6 chặn tự duyệt tới khi `quality:accept` đạt ở đúng sha đã staged. Dự án không có
profile giữ nguyên hành vi cũ. Trạng thái `/thi-hanh` vẫn ở file A–F cho tới bridge H7
(ADR-0017); quality journal không trở thành backlog cạnh tranh hoặc được công bố là migration đã xong.

## 8. Những phần CHƯA được kích hoạt bởi thay đổi này

Assessor không tự chạy build/browser/security/restore, không tự cấp danh tính, không thay gate hiện có,
không tự áp lên mọi Orchestrator run và không merge/deploy. Adapter dùng lại journal/resume core,
không tạo daemon hoặc worker pool mới. `quality_pass`
chỉ là một điều kiện bằng chứng, không là quyền thao tác hoặc event COMPLETED. Chưa có thử nghiệm sản phẩm
đầu-cuối hoặc chứng minh hài lòng người dùng. Không bật auto-approve cho các gate cũ đang pending.

Trình tự tích hợp tiếp theo có dependency rõ:

| Ưu tiên | Hạng mục | Điều kiện nghiệm thu |
|---|---|---|
| P0 | Trusted driver, authority registry và quality gate tại runtime | Worker không có key/khả năng tự duyệt; driver thiếu khiến blocked; approval gắn revision; không bỏ gate cũ. |
| P0 | H3/H4 lease, worker isolation, outbox và reconciliation trên kernel có sẵn | Restart không nhân việc/tác động; worker hết quyền không ghi đè; giữ patch khi conflict. |
| P1 | Design/evidence adapters và independent evaluators | Có browser/device/API/data evidence thật; chuẩn ngành được map; phát hiện chức năng giả và self-approval. |
| P1 | Bounded diagnosis/repair và model quality floor | Tự đổi chiến lược khi mắc kẹt; không fallback dưới chuẩn hoặc hạ acceptance. |
| P1 | Tích hợp/CI/release/rollback thực tế | Đúng target, candidate, receipts; mất ACK phải reconcile; không tự nâng quyền hoặc báo PR là production. |
| P2 | Pilot nhiều nhiệm vụ và bảo trì theo vòng đời | Fault injection, regression, update/deprecation và chỉ số escaped defect/rework; không suy một demo thành độ tin cậy production. |

Runtime phải hoạt động thật trên môi trường được cấp quyền để tự tiếp tục. Tài liệu và CLI này không khởi
chạy công việc nền trên máy người dùng. Khi triển khai lịch bảo trì, cần policy về lịch, nguồn lực và tác
động; không tự mua dịch vụ hoặc đặt lịch ngoài yêu cầu.

## 9. Định nghĩa hoàn tất và chống tự đánh giá quá mức

Hoàn tất khi đúng mục tiêu/target; mọi acceptance bắt buộc và hard gate đạt; không có blocker; bằng chứng
còn hiệu lực; revision và trạng thái môi trường khớp; tài liệu vận hành/khôi phục phù hợp. Quyền deploy
không phát sinh từ key sẵn có, và nghiệm thu kỹ thuật không giả thành chữ ký khách hàng.

Báo cáo phải tách phần code đã viết, tests đã chạy, CI còn chờ, adapter chưa triển khai và phần chưa được
xác minh. Coverage cao của assessor không chứng minh sản phẩm hoặc toàn harness không lỗi. Đo escaped
defects, acceptance coverage, hành trình thật, false approval/completion, khả năng phục hồi và rework do
điều phối; không làm đẹp số liệu bằng cách loại bỏ task khó hoặc đổi tiêu chuẩn sau khi đo.

Ngừng vòng cải tiến của một nhiệm vụ khi contract đã đạt và reviewer không còn blocker trong phạm vi;
các cải tiến không thiết yếu vào backlog với căn cứ. Không biến ưu tiên chất lượng thành sửa vô hạn.

## Nguồn chính thống (phiên bản tham chiếu, kiểm tra lại khi áp dụng)

- [S1] ISO/IEC 25010:2023, trang abstract/model: https://www.iso.org/standard/78176.html
- [S2] OWASP ASVS, phiên bản tham chiếu 5.0.0: https://owasp.org/www-project-application-security-verification-standard/
- [S3] NIST Secure Software Development Framework, tham chiếu SP 800-218/SSDF 1.1: https://csrc.nist.gov/projects/ssdf
- [S4] W3C WCAG 2.2: https://www.w3.org/TR/WCAG22/
- [S5] W3C Selecting Web Accessibility Evaluation Tools: https://www.w3.org/WAI/test-evaluate/tools/selecting/
- [S6] Google Web Vitals: https://web.dev/articles/vitals
- [S7] Google SRE, Implementing SLOs: https://sre.google/workbook/implementing-slos/
- [S8] GOV.UK Design System: https://design-system.service.gov.uk/
- [S9] Claude Code goal mode: https://code.claude.com/docs/en/goal
- [S10] Claude Code skills/commands: https://code.claude.com/docs/en/skills

Nguồn là cơ sở lựa chọn phương pháp; các policy, gợi ý theo ngành và giới hạn assessor ở trên là thiết kế
của X-Agents. Không tuyên bố đã mua/đọc toàn văn ISO, được tổ chức tiêu chuẩn công nhận, hay thay thế việc
xác định nghĩa vụ chuyên ngành bằng một checklist chung.

## Tiếp thu projects-template có chọn lọc (ADR company 0045)

Phần `delivery` tùy chọn của ProjectProfile nối Standard Delivery vào luồng compile/assess/journal
hiện có: Ready cấu trúc, Done theo task, Complete theo goal. Goal sản phẩm mới qua `/product-goal`
chọn Complete, chỉ goal task rõ ràng mới chọn Done; run cũ không bị migration ngầm.
Nguồn canonical, repository ID, full commit và blob pin ở
`docs/integrations/projects-template.lock.json`; pin được hash vào contract khi opt-in.

Receipt `delivery.definition` do trusted runner tổng hợp cần `delivery_report` có gate theo đúng
plan. PASS command đòi đúng argv + exit0 + checks_executed>0; FAIL/NOT_CONFIGURED chặn; N/A chỉ khi
contract đã khai không áp dụng và có lý do. Không dùng N/A để bớt bất kỳ 33 check cũ nào.
Complete cần đúng target, không required work/blocking finding còn mở, goal được đo và guardrail
đạt. Đây là metadata có chữ ký, không thay phép đo và kiểm artifact thật. Approval record phải
được coordinator xác thực; schema Approved không cấp quyền, signer hoặc runtime mới.

Chọn thiết kế theo từng surface và người dùng, không một phong cách cho cả ngành. Tôn trọng
quyết định dự án, token/component hiện hữu và accessibility; nguồn ngoài chỉ là recommendation.
Trước lần sửa lặp thứ hai, chẩn đoán tầng gốc (spec/design/code/verifier/knowledge) rồi mới tiếp,
không khởi tạo lại mọi phần đã đúng. Phân tích, ví dụ theo ngành và phần không nhập:
`docs/reports/2026-09-25-projects-template-adoption.md`.
