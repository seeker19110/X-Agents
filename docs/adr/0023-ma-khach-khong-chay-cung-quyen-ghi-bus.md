# ADR-0023: mã của khách không được chạy cùng quyền ghi bus — `sandbox: auto` hết tụt ngầm về `subprocess`

Ngày: 2026-09-25. Trạng thái: **Accepted** (phương án a, 2026-10-05).

Phát hiện F1 của `sc-security` khi chấm PR #343: `human:*` trên bus chỉ là một chuỗi tự khai. ADR này đo phát
hiện đó, và cho thấy nó rộng hơn tên người: **mọi** actor trên bus chỉ đáng tin tới đâu quyền ghi file bus còn kín.
ADR chạm `xagents_core` (bus, gate, sandbox) và `company` (chọn sandbox, orchestrator), nên nằm ở dãy ADR gốc.

## Bối cảnh

Số liệu đo trên `main@22d2702` (#343), máy Windows của chủ dự án.

### 1. ACL của bus chỉ chạy lúc `publish`, không chạy lúc đọc

`SQLiteBus` kiểm quyền ở đúng một chỗ, `self._check_publish(env)` trong `publish()`
(`platform/xagents-core/src/xagents_core/sqlite_bus.py:80`). Ba đường đọc từ đĩa dựng envelope bằng
`model_validate_json(body)` mà không kiểm lại:

| Đường đọc | Dòng | Ai dùng |
|---|---|---|
| nạp lúc mở bus | `sqlite_bus.py:72–73` | mọi tiến trình mở `company.sqlite`: orchestrator, `gate_cli`, console |
| `poll()` | `sqlite_bus.py:101–111` | `run --watch` nhận event của tiến trình khác và báo subscriber như event mới |
| `replay()` | `sqlite_bus.py:116–124` | `PersistentGate`, `rehydrate`, `BusApprovalLookup`, `quality_floor` |

Tức là ai ghi được file SQLite thì đặt được `actor` bất kỳ. Trong `src/` có 15 chỗ gọi `is_human(`: core 6,
company 8, keeper 1.
- 9 chỗ nằm trên **đường ghi**: ACL và câu lỗi của `publish`, cách `decide` chọn actor, các CLI nhận
  `--actor`/`--by`. Dòng ghi thẳng vào file bỏ qua được cả 9.
- 6 chỗ ra quyết định từ dòng **đọc lại** từ đĩa, nên dòng giả qua mặt được:
  - `xagents_core/gate_cli.py:49` (`trusted_decision`) và `:77` (`_request_actor_allowed`, gọi trong `apply`);
  - `company/gate_cli.py:125`;
  - `orch/quality_flow.py:125`;
  - `orch/rehydrate.py:48`;
  - `quality_floor.py:162`.

Đường đọc lại còn tin thêm hai thứ không đi qua `is_human`:
- `trusted_decision` tin actor hệ thống `orchestrator` trên gate `UAT-*` (`gate_cli.py:50`);
- `TRUSTED_WRITERS` của `rehydrate` tin theo tên actor, với mặc định là chỉ orchestrator
  (`orch/rehydrate.py:26,34–43`).

### 2. Mã của khách chạy cùng quyền đó khi `auto` tụt về `subprocess`

- `sandbox_from_settings("auto", …)` trả `ContainerSandbox` nếu tìm thấy runtime, không thì
  `SubprocessSandbox` (`sandbox.py:297`). `run`/`redeploy` đi qua đây (`orch/cli.py::_sandbox_for`). Máy đo
  không có docker (`docker: command not found`), nên `auto` ở đây là `subprocess`.
- `SubprocessSandbox` chỉ cô lập bằng `cwd` cộng env đã lọc khoá (`sandbox.py:53–56,170–172`), không có ranh
  giới file. Ba điểm chạy mã khách dùng nó: tool `run` của model, lint/test, smoke (`SECURITY.md:55–58`).
- `ContainerSandbox` chỉ mount `spec.cwd` vào `/w` (`sandbox.py:238`) và mặc định `--network none`
  (`sandbox.py:245–246`). Tức file bus và cổng console nằm ngoài tầm với. Điều này đọc từ code, **chưa chạy thử**
  vì máy không có runtime.
- Console `--allow-decide` đòi token, nhưng token nằm trong một file của cùng user
  (`platform/console/src/console/server.py:116`). Ở chế độ `subprocess`, token không phải một ranh giới riêng.
  Chưa đo trực tiếp, vì ghi thẳng SQLite đã là đường ngắn hơn.

### 3. Tái hiện, có đối chứng

Tiến trình con chạy qua `SubprocessSandbox().run(...)` và chỉ dùng stdlib (`sqlite3`, `json`). Nó đọc một dòng
`audit-log` có sẵn làm khuôn, đổi `actor` và `payload` thành `gate.decide` approve, rồi `INSERT` vào bảng
`events`. Mỗi lượt dùng một bus mới, có một gate đang chờ do `human:po` mở:

| Lượt | Tiến trình con ghi | Kết quả trên gate |
|---|---|---|
| 1 (đối chứng) | không ghi gì | `pending` |
| 2 | `gate.decide SPEC-P1`, actor `builder` | `pending`: `trusted_decision` không tin actor không hình người |
| 3 | `gate.decide SPEC-P1`, actor `human:attacker` | `approve by human:attacker` |
| 4 | `gate.decide UAT-P1` (gate nghiệm thu), actor `orchestrator` | `approve by orchestrator` |
| 5 | như lượt 3, nhưng bus **đang mở** | trước `poll()`: `pending`; `poll()` nạp 1 event; sau đó: `approve by human:attacker` |

Lượt 2 cho thấy phép kiểm hình dạng actor vẫn đúng việc của nó. Lượt 3–5 cho thấy phép kiểm ấy không đủ, vì
chính actor là thứ bị làm giả. Lượt 5 cho thấy không cần khởi động lại: `run --watch` nhận dòng giả ngay.

### 4. Vì sao không giữ được hiện trạng

- Human gate và four-eyes là bảo đảm an toàn chính của repo: gate release trước khi giao hàng, gate nghiệm thu,
  và sàn ADR-0043 dựa trên việc agent không tự duyệt được. Ở chế độ `subprocess`, bảo đảm đó không đứng được
  trước chính thứ nó canh: mã của repo khách, và mã agent vừa viết.
- `SECURITY.md:65–70` đã ghi rằng `subprocess` chạy mã khách "bằng quyền người vận hành và thấy `HOME`". Nó chưa
  ghi hệ quả với gate. Người đọc dễ hiểu rủi ro chỉ là lộ `~/.ssh`.
- `auto` tụt hạng **ngầm**. Người vận hành không phải chọn gì, nên cũng không biết mình đã chọn.

## Phương án

**(a) `auto` fail-closed: không có runtime thì từ chối chạy mã khách, trừ khi khai `subprocess` tường minh.**
- `sandbox_from_settings("auto")` thiếu runtime thì ném `SandboxError`, cùng khuôn với `container` thiếu binary
  (`sandbox.py:291–293`). Câu lỗi nói hai lối ra: cài docker/podman, hoặc đặt `COMPANY_SANDBOX=subprocess`, tức
  chấp nhận rằng gate không chống được mã khách.
- Chọn `subprocess` tường minh thì được ghi audit một lần mỗi lần khởi động, hiện trong `status` và console. Bằng
  chứng `local_checks.sandbox` đã có sẵn.
- Ưu: đóng F1 cho mọi máy có container. Máy không có container thì rủi ro chuyển từ ngầm sang một quyết định có
  người ký tên. Thay đổi nhỏ, nằm ở một hàm.
- Nhược: máy không có docker (gồm cả máy đo) phải làm thêm một bước trước khi `run` chạy lại. Nó đổi ngữ nghĩa
  `auto` của `companies/software-company/docs/adr/0035-sandbox-tien-trinh.md`.

**(b) Quyết định của người được ký Ed25519, verify lúc đọc.**
- `gate_cli` và console ký `gate.decide`, `quality.profile_set`, `quality.bar_set` bằng khoá riêng của từng
  người duyệt, được mã hoá bằng passphrase. Lúc đọc, chữ ký được verify với registry khoá công khai đặt ngoài
  worktree, cùng khuôn ADR-0020.
- Ưu: dòng "người" giả không qua được, kể cả ở chế độ `subprocess`.
- Nhược:
  - Không che được dòng của actor hệ thống (`orchestrator`, lượt 4). Khoá của orchestrator phải mở sẵn khi chạy
    không người trông, nên cùng user đọc được.
  - Phải nhập passphrase mỗi lần duyệt, phải quản lý và xoay khoá.
  - Lịch sử cũ chưa ký phải có mốc cắt.

**(c) Chạy mã khách dưới một OS user khác, không cần docker.** Đây là ranh giới thật, nhưng cần quyền admin để
dựng, và mỗi hệ điều hành một kiểu (`runas`/`CreateProcessAsUser`, `setuid`). Thực chất là tự viết lại phần
container làm sẵn. Loại ở vòng này.

**(d) Phát hiện sau: so các dòng được ghi trong lúc một lệnh sandbox đang chạy.** Loại. Tiến trình nền do mã
khách thả ra ghi sau cửa sổ đo được, và dòng thật mà người ghi đồng thời qua `gate_cli` thì không phân biệt được
với dòng giả.

**(e) Giữ nguyên, chỉ sửa tài liệu.** Không đóng lỗ. Phần tài liệu của nó (một câu trong `SECURITY.md`) nằm trong
PR của chính ADR này, vì nó chỉ mô tả đúng hành vi hiện tại, chọn phương án nào cũng cần.

## Quyết định (đề xuất)

Làm (a). Để (b) thành việc sau, và chỉ làm khi người cần gate chống được mã khách trên máy **không** có container.

- Không đổi `publish()`, không đổi ba đường đọc: lỗ nằm ở chỗ ai ghi được file, không nằm ở cách đọc.
- Không đổi `trusted_decision` hay `TRUSTED_WRITERS`: chúng đúng với mọi dòng đi qua `publish()`.
- `ContainerSandbox` giữ nguyên: nó đã không mount file bus.

## Kế hoạch gói (nếu chọn (a))

1. **core:** `sandbox_from_settings("auto")` thiếu runtime ⇒ `SandboxError`.
   - Test đỏ trước: `which` trả `None` với `auto` hiện trả `SubprocessSandbox`.
   - Chiều ngược: bỏ nhánh mới thì test đỏ lại.
   - Các test đang dựa vào việc tụt ngầm thì khai `subprocess` tường minh, không nới assertion.
2. **company:** `run`/`redeploy` ghi audit `sandbox.mode` một lần mỗi lần khởi động, và `status` hiện chế độ.
   Khi là `subprocess`, console hiện dòng cảnh báo "gate không chống được mã khách".
3. **Tài liệu:** `SECURITY.md`, `docs/HUONG-DAN-VAN-HANH.md` (cài runtime, hoặc khai `subprocess` kèm hệ quả),
   và ghi chú ở ADR-0035 của công ty: "`auto` được sửa bởi ADR gốc 0023".
4. **Test hồi quy của chính F1**, chạy trên runner Linux có docker: cùng tiến trình con như lượt 3, chạy qua
   `ContainerSandbox`, thì gate phải còn `pending`. Máy không có runtime thì skip có lý do, không tính là xanh
   ngầm.

## Hệ quả

- Máy không có container: `run` dừng với `SandboxError` cho tới khi người vận hành chọn. Đây là thay đổi có chủ
  đích, không phải hồi quy.
- Rủi ro nếu quyết định sai: người vận hành đặt `subprocess` chỉ để chạy tiếp, và rủi ro quay lại như hôm nay.
  Nhận biết được qua audit `sandbox.mode=subprocess` và dòng cảnh báo trên console.
- Không giải quyết, và không định giải quyết ở đây:
  - Lệnh do chính người vận hành chạy, như `gate_cli`, `publish --actor human:…` hay console, vẫn được tin.
    Người vận hành là người được tin.
  - `git` không đi qua sandbox. Đây là giới hạn đã ghi ở `SECURITY.md:65`. Repo khách trỏ `--repo` vào một
    checkout có `.git/config` do khách soạn thì chưa được đo trong ADR này.

## Bổ sung sau review `sc-security` (2026-09-25, chưa gộp vào các mục trên)

`sc-security` xác nhận các dẫn chứng ở mục 1–3 và nêu thêm những điểm dưới đây.

Phiên chính đã tự kiểm lại:
- **Đường đọc thứ tư:** `latest()` (`sqlite_bus.py:126–131`) cũng không kiểm ACL. `quality_floor.collect_evidence`
  đọc `local_checks` qua nó (`quality_floor.py:222`). Khoảng dòng đúng của `poll()` là 101–114, của nạp lúc mở là
  72–74.
- **Chỗ tin thứ ba trên đường đọc:** `quality_floor.py:211` tin `env.actor == "orchestrator"` cho `release.staged` và
  `regression.run`.
- **Keeper:** `keeper/gates.py:101` đặt `UAT_PREFIX=None`, nhưng gate của keeper vẫn tin dòng `human:*` trên
  `keeper.sqlite`. Đây là cùng lỗ, trên một bus khác.
- **`deploy.py` chạy `docker compose` của khách ngoài `Sandbox`** (ADR-0039 §7, `deploy.py:18–20`), qua docker
  socket của host. Vì vậy (a) **không** đóng được đường này, kể cả ở chế độ container. Phải nêu nó ở mục Hệ quả,
  hoặc thêm một gói riêng.

`sc-security` nêu, phiên chính **chưa** tự kiểm dòng:
- **Actor hệ thống thứ ba `code`** (`AUTOAPPROVE_ACTOR`): khi bật `COMPANY_GATE_AUTOAPPROVE`, một dòng giả dưới tên
  này được tin qua `trusted_autoapprove`. Nếu đúng, nhược điểm của (b) phải thêm `code` bên cạnh `orchestrator`.
- **Hai đường đọc riêng không kiểm ACL:** console (`collect.py`) và `gate_brief.open_read_only`. Dòng giả làm méo
  được hồ sơ mà người ký đọc cạnh nút Duyệt.

Hai phương án bị bỏ sót, phải thêm vào mục Phương án:
- **(f) Kiểm ACL lại trên đường đọc.** Không chặn được việc giả `human`, `orchestrator` hay `code`, vì các actor này
  qua được ACL. Nhưng nó chặn được dòng giả mang actor agent, và dòng sai producer.
- **(g) Log chống giả mạo:** hash-chain hoặc HMAC theo `seq`, tính lúc `publish`, verify lúc đọc. Nó phát hiện được
  mọi dòng chèn ngoài `publish()`, với mọi actor. Điểm yếu giống (b): khoá phải mở sẵn khi chạy không người trông,
  nên cùng user đọc được.

## Quyết định 2026-10-05

Người vận hành chọn (a) và yêu cầu tự khôi phục Docker. Docker Engine đã chạy được từ tiến trình orchestrator trên Windows và WSL; ca hồi quy F1 dùng container thật chứng minh file bus ngoài mount không bị mã khách ghi. `auto` thiếu runtime nay dừng; `subprocess` chỉ chạy khi khai tường minh, ghi audit và hiện cảnh báo gate. Các câu hỏi dưới đây lưu lại bối cảnh khi ADR còn Proposed.

## Câu hỏi khi còn Proposed

1. Chọn (a), (b), cả (a) lẫn (b), hay (e) chỉ sửa tài liệu? Nếu mọi repo đưa vào công ty đều là repo của chính
   bạn, tức mã khách luôn tin cậy, thì (e) có thể là đủ.
2. Nếu chọn (a): máy này không có docker. Bạn sẽ cài docker/podman, hay đặt `COMPANY_SANDBOX=subprocess` và
   chấp nhận rủi ro đã đo ở mục 3?
3. Nếu chọn (b): passphrase mỗi lần duyệt có chấp nhận được không? Registry khoá của người duyệt đặt ở đâu?

## Liên quan

ADR gốc 0020 (chữ ký Ed25519 cho receipt, khuôn cho (b)), 0021 (bổ sung pe2-duyet: `BusApprovalLookup` dựa trên
chính giả định này, trần F1); `companies/software-company/docs/adr/0035-sandbox-tien-trinh.md` (`auto`);
`companies/software-company/docs/adr/0043-tu-duyet-theo-san-chat-luong.md` (sàn dựa trên gate);
`platform/xagents-core/TRAPS.md` (`trusted_decision` đọc `env.actor`, bản vá #212); `SECURITY.md` (giới hạn
sandbox); PR #343 (F1).
