# ADR-0010: domain allowlist cho mạng của `ContainerSandbox` — mạng internal và proxy ACL

Ngày: 2026-09-10 · Trạng thái: được chấp nhận (S2, 2026-10-05) · Mẫu: hạ tầng mới (egress proxy), không phải một field ·
Lớp: 1

## Bối cảnh

`RunSpec.network` (`platform/xagents-core/src/xagents_core/sandbox.py:65`) là một `bool`. `ContainerSandbox._argv`
(`sandbox.py:180-181`) dịch nó thành đúng hai trạng thái:

```python
base += (["--network", "bridge", "-p", f"127.0.0.1:{spec.port}:{spec.port}"] if spec.network
         else ["--network", "none"])
```

Bật `network=True` cho container thấy **toàn bộ Internet**, không phân biệt domain. Nhu cầu thật duy nhất đang
dùng cờ này là `company.smoke` probe `127.0.0.1:<port>` của chính container vừa dựng (`RunSpec.port` — xem
docstring module, dòng 15) — tức là ngay cả trường hợp dùng thật hôm nay cũng không cần ra ngoài Internet, chỉ
cần loopback tới cổng đã mount. Không có nơi gọi nào hôm nay cần domain ngoài thật.

Khoảng trống lộ ra khi so X-Agents với mô hình phân quyền hành động dạng Allow/Ask/Deny (không phải Allow/Deny
nhị phân theo tool, mà theo **loại đích** của hành động): repo đã có "đọc credential = Deny" (`SECRET_FILES`,
`SECRET_ENV`), "lệnh ngoài whitelist = Deny" (`COMMANDS` đóng — `companies/software-company/src/company/tools.py:194-196`,
không có lệnh cài dependency nào trong bất kỳ stack, xem `companies/software-company/src/company/stacks.py:26-47`), nhưng
**không có tầng "domain nào được ra, domain nào không"**
cho trường hợp một ticket tương lai thật sự cần gọi ra ngoài (vd tải một package registry, gọi một webhook khách
khai trong spec). Ghi lại đã kiểm chứng: không có allowlist domain nào trong repo, `grep` không ra kết quả.

**Vì sao không chỉ thêm field `RunSpec.allowed_domains: list[str]`:** Docker/Podman CLI không có cờ lọc theo
domain ở tầng `run`. `--network bridge` là bật hẳn NAT ra ngoài; không có `--network` biến thể nào chỉ cho phép
một danh sách hostname. Muốn lọc domain thật cần một trong hai, cả hai đều là **hạ tầng mới**:

1. **Egress proxy/sidecar**: container chạy với `--network` riêng (một Docker network không route thẳng ra
   ngoài), toàn bộ traffic ra đi qua một proxy (vd squid/mitmproxy cấu hình ACL theo domain) là thành viên khác
   của network đó. `HTTPS_PROXY`/`HTTP_PROXY` được set qua env, và container không có route nào khác nên không
   né được proxy.
2. **iptables/DNS injection vào chính container**: cần `--cap-add=NET_ADMIN`, tự cấy rule `iptables`/`nft` lọc
   theo IP đã resolve (không lọc được theo domain trực tiếp — phải resolve DNS trước rồi allowlist IP, dễ vỡ với
   dịch vụ dùng CDN/nhiều IP xoay vòng) — phức tạp hơn, dễ vỡ hơn, không chọn.

Field `allowed_domains` mà không có (1) hoặc (2) đứng sau nó là **an toàn giả**: lưu một danh sách rồi không ai
enforce, model đọc audit thấy `allowed_domains: [...]` và tưởng đã bị chặn trong khi container vẫn ra được mọi
domain. Đây đúng thứ luật cấm 8 của `AGENTS.md` cấm — không nói đã chặn khi chưa chứng minh được bằng lệnh chạy
thật.

## Quyết định

**Bối cảnh quyết định ban đầu (2026-09-10, được thay bởi mục thi hành S2 bên dưới).** Ba lý do khi đó dừng ở mức đề xuất:

1. **Không có nơi gọi thật cần nó hôm nay.** Nhu cầu network hiện tại (`company.smoke`) chỉ cần loopback, không
   cần domain ngoài. Xây hạ tầng proxy cho một nhu cầu chưa tồn tại là đoán trước — trái nguyên tắc "không thiết
   kế cho yêu cầu giả định" và không có test đỏ nào tả được hành vi còn thiếu (luật bắt buộc 4: không có test đỏ
   thì chưa được viết code sản xuất — ở đây không có *ca dùng thật* để viết test đỏ cho nó).
2. **Chi phí vòng đời không nhỏ**: một proxy sidecar là một tiến trình nữa phải khởi động/dừng đồng bộ với mỗi
   lần `ContainerSandbox.run`, một network Docker/Podman nữa phải dọn, và một điểm hỏng mới (`SandboxError` khi
   proxy không lên) — đúng tinh thần fail-closed của ADR-0035, nhưng là bề mặt lớn hơn nhiều so với hai backend
   hiện tại (subprocess giữ nguyên hành vi cũ, container thêm cô lập).
3. **Ghi lại quyết định NGAY BÂY GIỜ để khoanh phạm vi**, tránh phiên sau lặp lại nhầm lẫn đã xảy ra một lần
   (đề xuất field không enforce được) — đây là lý do ADR này tồn tại dù chưa có code.

**Khi có nhu cầu thật (một ticket cần gọi domain ngoài cụ thể), thiết kế phải theo khuôn sau, không lệch:**

- `RunSpec` thêm `allowed_domains: tuple[str, ...] = ()` — **rỗng nghĩa là deny hết domain ngoài**, kể cả khi
  `network=True` (tách hai khái niệm: `network` cho loopback nội bộ container hiện tại, `allowed_domains` cho ra
  ngoài Internet; không tái dùng `network=True` để ngầm định "ra được hết" như hôm nay).
- `ContainerSandbox` cần một cổng cắm `EgressProxy` (Protocol tương tự `Sandbox`, không hard-code một proxy binary
  cụ thể) — dựng network riêng cho lần `run`, khởi động proxy với ACL từ `allowed_domains`, set
  `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY` trong env truyền vào container, dọn network sau khi xong dù thành công
  hay lỗi (try/finally, cùng kỷ luật với `_ProcHandle`/`ContainerSandbox.spawn` hiện tại).
- `SubprocessSandbox` **không hỗ trợ** `allowed_domains` — nó chạy trực tiếp trên máy người vận hành, không có
  ranh giới network để lọc; khai `allowed_domains` non-empty với `SubprocessSandbox` phải là `SandboxError`
  fail-closed ngay khi dựng `RunSpec`/tại `sandbox.run`, không được âm thầm bỏ qua rồi cho chạy không lọc.
- Test bắt buộc trước khi merge (TDD, luật bắt buộc 4): dựng container thật gọi một domain KHÔNG trong
  `allowed_domains` → phải timeout/refuse tại tầng mạng (không phải tại tầng application) — chứng minh bằng
  request thật, không phải bằng đọc lại config.

## Hệ quả

**Được** (khi làm theo khuôn trên, ở một ADR/PR sau): domain allowlist thật, enforce ở tầng mạng chứ không phải
một cờ chỉ để đọc lại; `network=True` hôm nay tiếp tục hoạt động y hệt cho ca dùng loopback duy nhất đang có,
không phá `company.smoke`.

**Mất**: chưa có gì được vá hôm nay — nếu một ticket tương lai thật sự cần gọi domain ngoài trước khi ADR này
được hiện thực hoá, người vận hành phải tự set `network=True` (ra được hết) hoặc từ chối ticket đó, không có lựa
chọn ở giữa.

**Không thuộc phạm vi.** Lọc domain cho `gateway` (proxy OpenAI-compatible — mục đích khác hẳn, không phải
sandbox chạy lệnh khách) và cho `Studio-creators` (không dùng `ContainerSandbox` cho network, xem docstring
module `sandbox.py` dòng 21-25 — studio mặc định `subprocess`).

## Liên quan

- `platform/xagents-core/src/xagents_core/sandbox.py` — `RunSpec.network` (65), `ContainerSandbox._argv` (169-182),
  `SandboxError` (54) là mẫu fail-closed sẽ tái dùng cho `SubprocessSandbox` + `allowed_domains`.
- `companies/software-company/docs/adr/0035-sandbox-tien-trinh.md` — quyết định gốc "container mạng tắt mặc định,
  fail-closed khi khai đích danh mà thiếu binary"; ADR này là phần mở rộng chưa làm của cùng nguyên tắc.
- `companies/software-company/src/company/tools.py:31,194-196` — hai cơ chế Deny theo loại hành động đã có (đọc
  credential, lệnh ngoài whitelist), đối chiếu để thấy domain allowlist là mảnh còn thiếu duy nhất trong mô hình.
- `docs/adr/0001-loi-chung-xagents-core.md` — "core giữ cơ chế, package giữ nghĩa": `EgressProxy` là cơ chế ở
  core, ACL/domain cụ thể theo ticket là nghĩa của nơi gọi (`company`/`studio`), không hard-code trong core.

## Quyết định thi hành S2 — 2026-10-05

Nhu cầu thật nay có: ADR-0044 dùng `uv run` tự đồng bộ phụ thuộc khách trong lint/test; container mạng tắt làm đường này không tải được PyPI. Chủ dự án giao tự quyết và hoàn thiện ngày 05/10. Các mô tả “chưa có nơi gọi” và quyết định hoãn ở trên là lịch sử, được thay bởi mục này.

- Core thêm `allowed_domains` mặc định rỗng, tách quyền ra ngoài khỏi cờ loopback/publish. Cả `run` và `spawn` dùng cùng lifecycle; `network=True` rỗng chạy trên bridge internal riêng, không NAT ra Internet. `network=False` rỗng giữ network none.
- `EgressProxy` Protocol cấp một session có tên mạng, env proxy và close idempotent. Backend DockerSquidProxy dùng Squid image Canonical `ubuntu/squid:6.6-24.04_beta`, cấu hình ACL được code tạo, hostname chính xác (không wildcard/URL/IP), chỉ HTTP/HTTPS cổng 80/443. Chặn đích loopback/private/link-local để không tới dịch vụ host, kể cả DNS resolve vào địa chỉ nội bộ. Không decrypt TLS.
- Mỗi session tạo bridge internal, sidecar proxy nối bridge thường và internal; workload chỉ internal. Không mount socket hay config của host vào workload. Proxy nhận config qua stdin `docker exec`, không mount đường dẫn tạm Windows/WSL khó dịch. Không mở cổng proxy trên host. Proxy lỗi thì dọn và ném SandboxError trước chạy workload; cleanup khi hoàn tất, timeout, kill và lỗi spawn.
- Company chỉ khai PyPI (`pypi.org`, `files.pythonhosted.org`) cho argv `uv` khi dùng container. Các lệnh không phải uv không được Internet. Subprocess tường minh giữ đường vận hành đã chấp nhận; core từ chối RunSpec có domains khi dùng subprocess vì không thể enforce. Không thêm quyền ra ngoài vào config do model tự khai.
- Docker image Python khách có uv, dùng interpreter hệ thống và cache trong /tmp; người vận hành chọn image phù hợp stack. Không hứa mọi stack chạy được bằng image Python.
- Bằng chứng trước merge: test đỏ trước mã; test lifecycle lỗi/timeout/kill; container thật gọi PyPI qua proxy thành công, domain ngoài ACL bị 403, gọi trực tiếp không proxy bị chặn, smoke qua cổng publish vẫn HTTP 200, tài nguyên session không còn sau kết thúc. CI không pull image hoặc gọi provider trả phí; integration bỏ qua rõ khi không có Engine/images.

Nguồn cấu hình: https://www.squid-cache.org/Doc/config/http_access/ và https://hub.docker.com/r/ubuntu/squid (đọc 2026-10-05). Image được cài bởi người vận hành, không tự pull khi chạy lệnh khách. DNS/traffic ngoài HTTP(S) không có route Internet; proxy chỉ cho đúng tên, không cho IP literal. Git/deploy bằng Docker socket là ngoại lệ đặc quyền đã ghi trong SECURITY, không được tính là egress sandbox.

- Đo smoke thật 05/10: Docker bridge `--internal` không nhận publish trực tiếp (test HTTP đỏ dù process sống). Cổng publish vì vậy nằm trên relay tin cậy Python, nối bridge thường và internal, chỉ forward đúng cổng tới đúng tên workload do code tạo. Workload không có bridge thường; không có proxy tùy ý trên relay. Cả relay và proxy được dọn trong session. Image relay python:3.12-slim cũng cần cài trước, không pull trong runtime.

### Profile CAMPUS-UNI (2026-10-05)

Smoke dùng cùng allowlist PyPI khi lệnh uv chạy trong container. Với option Waitress `--listen=127.0.0.1:<port>`, harness đổi bind thành `0.0.0.0` chỉ bên trong workload container; relay vẫn publish đúng loopback host. Lệnh đo được ghi trong smoke.command, không sửa spec hay lệnh khởi động Windows của khách. Các dạng bind khác không được đoán/viết lại. Image uv dùng `UV_PROJECT_ENVIRONMENT=/tmp/xagents-venv`, tránh dùng/xóa venv Windows trong worktree mount; dependency vẫn đi qua ACL.

Container không nhận PATH/VIRTUAL_ENV của tiến trình host (so tên không phân biệt hoa thường); dùng giá trị image. Đối chứng Windows: cùng image/lệnh `uv --version`, env image exit 0/uv 0.9.9, truyền PATH host exit 127/not found. Cả env-file và env-argv phải qua cùng lọc trước run/spawn.
