# ADR-0044 — lint/test của repo khách chạy bằng môi trường của khách, không phải venv của công ty

- Trạng thái: chấp nhận
- Ngày: 2026-09-23
- Liên quan: ADR-0013 (nhận diện stack), ADR-0010 (ranh giới tin cậy: model chọn tên lệnh, code ghép argv),
  ADR-0035 (sandbox cho lệnh con)

## Bối cảnh — số đo, không phải suy đoán

Dự án CAMPUS-UNI-20260922, ticket TCK-001 (scaffold Django + waitress + `/healthz`). Builder chạy đủ **3 lượt**,
mỗi lượt viết 43 file, mỗi lượt `local_checks` trả `{"lint": false, "tests": false}` rồi `ticket.blocked`
(`retry: 3, max_retries: 3`) và mở gate `escalation`.

Tái hiện bằng chính hai lệnh mà `stacks.py` ghép, chạy trong worktree `ticket/TCK-001` của repo khách:

| Trình thông dịch | Kết quả đo |
|---|---|
| `sys.executable` (venv của **orchestrator**) — cách đang làm | `ModuleNotFoundError: No module named 'django'`, `Interrupted: 4 errors during collection` |
| `uv run` trong worktree khách (venv của **khách**) | test chạy thật, còn đúng **2 fail nội dung** (thiếu mark `django_db`) |

Kết luận đo được: `stacks.PY` ghép argv bằng `sys.executable`, tức Python của công ty, rồi chạy nó trong repo của
khách. Phụ thuộc mà khách khai trong `pyproject.toml` (Django, `pytest-django`…) không bao giờ có ở đó. **Không
code nào của builder làm cho nó xanh được** — ticket bị chặn bởi hạ tầng nhưng mọi bằng chứng trên bus lại trỏ vào
builder. Lỗi này dính **mọi ticket Python của mọi dự án khách**, không riêng TCK-001.

Đây đúng khuôn mà chính ADR-0013 đã đặt ra và sửa một nửa: trước ADR-0013 lệnh cứng `ruff`+`pytest` khiến PR của
frontend mang bằng chứng hình thức. ADR-0013 sửa *lệnh nào*, nhưng bỏ sót *chạy bằng môi trường nào*.

## Quyết định

`detect()` trả stack `PY_UV` khi repo khách có `pyproject.toml` khai bảng `[project]` (dự án uv thật). Lệnh trở
thành `uv run -- python -m ruff check` và `uv run -- python -m pytest -q -p no:cacheprovider`. `uv run` tự đồng bộ
`.venv` của worktree trước khi chạy, nên môi trường khớp đúng thứ khách khai.

Không khai `[project]` (chỉ `[tool.*]`), hoặc chỉ có `setup.cfg`/`requirements.txt` → giữ nguyên `sys.executable`
(câu này đã được thay bởi §"Bổ sung 2026-10-11" ở cuối: có file requirements khai công cụ thì dựng env từ chúng).
Thà rơi về đường cũ còn hơn ghép một lệnh chắc chắn không chạy. `pyproject.toml` đọc bằng `tomllib`, không grep:
`[project]` nằm trong một chuỗi nhiều dòng không phải là bảng.

`.venv/` đã có sẵn trong `JUNK_PATTERNS` (`workspace.py`) nên venv do `uv run` dựng không lọt vào commit của
ticket kể cả khi `.gitignore` của khách quên nó.

## Cái giá đã biết, nói thẳng

`uv run` **cài gói từ `pyproject.toml` do chính model viết ra**. Đây là mở rộng thật sự của ranh giới tin cậy:
trước ADR này, agent không có đường nào khiến máy vận hành tải và chạy mã bên thứ ba; sau ADR này thì có, qua
danh sách dependency mà agent tự soạn. Người vận hành đã cân nhắc và chọn đúng đánh đổi này (2026-09-23) để phễu
chạy không cần người dựng venv tay cho từng repo khách.

Hai điều kiện biên còn hở, ghi ra để không ai tưởng là đã kín:

- `RunSpec.network=False` là mặc định, nhưng backend `subprocess` **không** thật sự tắt mạng — chỉ backend
  `container` mới tắt. Nên `uv sync` chạy được là vì lớp bảo vệ chưa bật, không phải vì đã được cấp phép có kiểm.
- Chưa có lọc domain/egress proxy: không có cách nào hiện nay chặn một dependency trỏ tới index lạ.

Cả hai thuộc về một ADR egress proxy riêng, chưa viết. Cho tới lúc đó, chạy công ty với repo khách **của chính
mình** là điều kiện sử dụng, không phải lời khuyên.

## Phương án đã loại

- **Chỉ dùng `.venv` có sẵn, người vận hành `uv sync` tay.** Không mở đường cài gói, nhưng mỗi ticket thêm
  dependency lại kẹt chờ người — trái đúng thứ đang muốn sửa (phễu tự chạy).
- **Dựng venv một lần lúc tạo worktree ticket đầu tiên.** Vẫn là agent gọi cài gói, cùng bề mặt rủi ro, mà thêm
  một điểm đồng bộ hỏng được (ticket sau đổi dependency thì venv cũ sai).
- **Cài phụ thuộc của khách vào venv của công ty.** Hai dự án khách khác phiên bản Django là hỏng; và trộn môi
  trường công ty với môi trường khách là đúng thứ ADR này đang gỡ.

## Bổ sung 2026-10-11 — phụ thuộc khai bằng `requirements*.txt`

**Đo.** QLLH-TRUONG, ticket TCK-01 `blocked` sau 3/3 lượt (~420k token). Builder dựng bố cục rất phổ biến:
Django/psycopg/gunicorn trong `requirements.txt`, ruff/coverage/pytest/pytest-django trong `requirements-dev.txt`
(`-r requirements.txt`), `pyproject.toml` chỉ có `[tool.ruff]`, `[tool.pytest.ini_options]`, `[tool.coverage]`.
Không có `[project]` nên câu "giữ nguyên `sys.executable`" ở trên áp vào: mọi lượt chết ở khâu collect
(`No module named 'django'`) — đúng lỗi CAMPUS-UNI/TCK-001 ở dạng anh em. Câu đó là chỗ hở của chính ADR này.

**Quyết định.** Không có `[project]` (chỉ `[tool.*]`, chỉ `setup.cfg`, chỉ `requirements.txt`, hay TOML hỏng) thì
`_py_stack` đọc file requirements: file dev đầu tiên có mặt theo thứ tự `requirements-dev.txt`,
`requirements/dev.txt`, `dev-requirements.txt`, `requirements-test.txt`; cộng `requirements.txt` khi file dev không
tự kéo nó bằng `-r`. Công cụ nào (pytest/ruff) được khai trong các file đó — theo cả `-r`/`--requirement` tương đối
với file đang đọc — thì lệnh của nó thành, ví dụ đúng bố cục TCK-01:

```
uv run --isolated --no-project --with-requirements requirements-dev.txt -- python -m pytest -q -p no:cacheprovider
```

Không khai công cụ → giữ `sys.executable` (cùng lý lẽ nhánh `[project]`). Có `[project]` → nhánh gốc ở trên,
requirements không xét. Đọc file chỉ để biết công cụ nào được khai: bỏ comment, dòng trống, mọi tuỳ chọn khác
(`-c` là constraint, không cài gì; `-e`, `--index-url`); `-r` vòng, thiếu file, không đọc được, hay trỏ ra ngoài repo
thì bỏ qua, không ném. Cài đặt (kể cả theo `-r`) là việc của `uv`. Argv vẫn do code ghép từ hằng số (ADR-0010):
tên file là hằng trong `REQ_DEV`, không lấy từ nội dung khách; argv[0] vẫn là `uv` nên allowlist `run`, sandbox và
`registry_domains` (chỉ PyPI, chỉ ở backend container) áp y như nhánh `[project]` — không nới gì.

**`--isolated` là bắt buộc, đo được.** Thiếu nó, `uv run --no-project --with-requirements` lấy venv đang kích hoạt
(`VIRTUAL_ENV` của orchestrator, `clean_env` giữ biến này) làm nền: trong env "của khách", `import pydantic` của
công ty vẫn chạy (đo 2026-10-11, uv 0.12.17, `VIRTUAL_ENV` trỏ `.venv` của hub: không `--isolated` → import được
từ `.venv` đó; có → `ModuleNotFoundError`; cùng phép đo, pytest của bố cục TCK-01 thu nhỏ chạy xanh trong env dựng
từ `requirements-dev.txt` + `-r requirements.txt`). Đó là đúng kiểu trộn môi trường ADR này gỡ, chỉ kín đáo hơn.

**Phương án đã loại.** Chỉ dựng từ file dev (bố cục cài hai file riêng thì thiếu Django); grep chuỗi `pytest` trong
mọi `*.txt` (comment và constraint thành khai báo giả); sinh `[project]` hộ khách (sửa repo khách thay cho builder).

**ruff gọi thẳng binary ở nhánh requirements (đo sau khi merge, cùng ngày).** Lượt TCK-01 kế tiếp có test xanh nhưng lint đỏ: trong env `--with-requirements`, `python -m ruff` tìm `ruff.exe` ở thư mục Scripts của trình thông dịch tạm (`cache/builds-v0/.tmp*`) trong khi binary nằm ở lớp cache (`archive-v0/*/Scripts`) → `FileNotFoundError`. Lệnh lint của nhánh này nay là `uv run --isolated --no-project --with-requirements <file> -- ruff check` (cùng worktree: "All checks passed!"). Nhánh `[project]` và đường `sys.executable` giữ `python -m ruff`: ở đó `ruff.exe` nằm đúng Scripts của trình thông dịch đang chạy.

**Còn hở, biết rõ.** `Runtime.argv` của smoke (`smoke.py`) vẫn thay `python` đầu lệnh bằng `sys.executable` —
venv của orchestrator, cho CẢ hai bố cục (`[project]` lẫn requirements); lệnh không bắt đầu bằng `python`
(`gunicorn …`) thì tìm trên `PATH` của orchestrator. Không sửa ở đây vì nó đổi đường bằng chứng release
(ADR-0029/0035) và cần quyết định riêng: bọc cả lệnh hay chỉ `python`.
