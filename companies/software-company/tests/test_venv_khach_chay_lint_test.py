"""ADR-0044: lint/test của repo khách phải chạy bằng MÔI TRƯỜNG CỦA KHÁCH, không phải venv của công ty.

Lỗi đo được 2026-09-23 trên CAMPUS-UNI/TCK-001: `stacks.PY` ghép argv bằng `sys.executable` — tức Python của
orchestrator — rồi chạy trong worktree khách. Django khai trong `pyproject.toml` của khách không có ở đó, nên
`pytest` chết ngay khâu collect (`ModuleNotFoundError: No module named 'django'`) với MỌI code builder viết ra:
ticket quay đủ 3 vòng rồi `ticket.blocked`. Đây là lỗi hạ tầng đội lốt lỗi builder.
"""

from __future__ import annotations

import sys

from company.stacks import detect

KHACH_DAY_DU = """\
[project]
name = "khach"
version = "1.0.0"
dependencies = ["django>=5.2,<6.0"]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-django>=4.9", "coverage[toml]>=7.6", "ruff>=0.6"]
"""


def test_khach_khai_pytest_va_ruff_thi_chay_bang_moi_truong_cua_khach(tmp_path):
    """Đây là hình dáng thật của `campus-company`: `uv run` để Django của khách có mặt lúc collect."""
    (tmp_path / "pyproject.toml").write_text(KHACH_DAY_DU, encoding="utf-8")

    st = detect(tmp_path)

    assert st.name == "python"
    for argv in (st.lint, st.test):
        assert argv is not None
        assert argv[:2] == ["uv", "run"], argv
        assert sys.executable not in argv, f"vẫn dùng Python của công ty: {argv}"
    assert st.test_globs, "phân vùng ghi test/code (ADR-0028) không được mất theo"


def test_khach_khong_khai_pytest_thi_giu_duong_cu_chu_khong_bia_ra_mau_do(tmp_path):
    """Khách không mang bộ test riêng: `uv run` chỉ dựng venv rỗng rồi trả `No module named pytest` — một màu đỏ
    do hạ tầng, không do code. Giữ `sys.executable` thay vì đổi lỗi hạ tầng này lấy lỗi hạ tầng khác."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "k"\nversion = "1"\ndependencies = ["django"]\n', encoding="utf-8"
    )

    st = detect(tmp_path)

    assert st.test is not None and st.test[0] == sys.executable
    assert st.lint is not None and st.lint[0] == sys.executable


def test_khai_ruff_ma_khong_khai_pytest_thi_moi_lenh_quyet_dinh_rieng(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "k"\nversion = "1"\ndependencies = ["ruff>=0.6"]\n', encoding="utf-8"
    )

    st = detect(tmp_path)

    assert st.lint is not None and st.lint[:2] == ["uv", "run"]
    assert st.test is not None and st.test[0] == sys.executable


def test_khach_khai_cong_cu_o_optional_dependencies_van_tinh(tmp_path):
    """`[project.optional-dependencies]` là cách khai extras kiểu cũ — `uv sync --extra` vẫn cài, nên vẫn tính."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "k"\nversion = "1"\ndependencies = []\n'
        '\n[project.optional-dependencies]\ndev = ["pytest>=8.3", "ruff>=0.6"]\n',
        encoding="utf-8",
    )

    st = detect(tmp_path)

    assert st.lint is not None and st.lint[:2] == ["uv", "run"]
    assert st.test is not None and st.test[:2] == ["uv", "run"]


def test_pyproject_khong_co_bang_project_thi_giu_python_cua_cong_ty(tmp_path):
    """Chỉ có `[tool.*]` thì không phải dự án uv — `uv run` không chạy được trên nó."""
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 120\n", encoding="utf-8")

    st = detect(tmp_path)

    assert st.test is not None and st.test[0] == sys.executable


def test_pyproject_hong_thi_roi_ve_duong_cu_chu_khong_no(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project\nname =", encoding="utf-8")

    st = detect(tmp_path)

    assert st.test is not None and st.test[0] == sys.executable


def test_ten_goi_doc_tu_bang_toml_chu_khong_grep(tmp_path):
    """`pytest` nằm trong chuỗi mô tả KHÔNG phải là dependency — grep sẽ nhận nhầm, `tomllib` thì không."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "k"\nversion = "1"\ndescription = "chạy pytest và ruff bằng tay"\ndependencies = []\n',
        encoding="utf-8",
    )

    st = detect(tmp_path)

    assert st.test is not None and st.test[0] == sys.executable


# ---------- ADR-0044 bổ sung (2026-10-11): phụ thuộc khai bằng `requirements*.txt` ----------
#
# Đo 2026-10-11 trên QLLH-TRUONG/TCK-01: builder dựng bố cục rất phổ biến — Django/psycopg/gunicorn trong
# `requirements.txt`, ruff/coverage/pytest/pytest-django trong `requirements-dev.txt` (`-r requirements.txt`),
# `pyproject.toml` chỉ có `[tool.ruff]`/`[tool.pytest.ini_options]`/`[tool.coverage]`. Không có `[project]` nên
# `_py_stack` rơi về `sys.executable` — đúng lỗi CAMPUS-UNI/TCK-001 ở dạng anh em: 3/3 lượt chết ở khâu collect
# (`No module named 'django'`), ~420k token đốt cho một lỗi hạ tầng.

PYPROJECT_TCK01 = """\
[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "qllh.settings"

[tool.coverage.run]
branch = true
"""

# Môi trường DỰNG TỪ file requirements, cô lập khỏi venv đang chạy orchestrator: đo 2026-10-11, thiếu `--isolated`
# thì `uv run --no-project --with-requirements` lấy venv đang kích hoạt (`VIRTUAL_ENV` của orchestrator) làm nền —
# `import pydantic` của công ty vẫn chạy được trong "môi trường của khách".
_REQ_RUN = ["uv", "run", "--isolated", "--no-project"]
_PYTEST = ["--", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
# ruff gọi THẲNG binary, không qua `python -m ruff`: đo 2026-10-11 (QLLH-TRUONG/TCK-01, Windows, uv 0.12.17), trong env
# `--with-requirements` thì `ruff/__main__.py` tìm `ruff.exe` ở thư mục Scripts của trình thông dịch TẠM
# (`cache/builds-v0/.tmp*/Scripts`) trong khi binary nằm ở lớp cache (`archive-v0/*/Scripts`) → FileNotFoundError,
# lint đỏ dù code sạch; `uv run … -- ruff check` tìm binary qua PATH của env → "All checks passed!".
_RUFF = ["--", "ruff", "check"]


def _viet(root, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def test_tck01_pyproject_chi_co_tool_va_requirements_dev_thi_chay_bang_requirements(tmp_path):
    """Đúng hình dáng QLLH-TRUONG/TCK-01: env dựng từ file dev (đã kéo `requirements.txt` qua `-r`)."""
    _viet(
        tmp_path,
        {
            "pyproject.toml": PYPROJECT_TCK01,
            "requirements.txt": "Django==5.2.7\npsycopg[binary]>=3.2\ngunicorn\n",
            "requirements-dev.txt": "-r requirements.txt\nruff>=0.6\ncoverage[toml]\npytest>=8.3\npytest-django\n",
        },
    )

    st = detect(tmp_path)

    flags = ["--with-requirements", "requirements-dev.txt"]
    assert st.name == "python"
    assert st.test == [*_REQ_RUN, *flags, *_PYTEST]
    assert st.lint == [*_REQ_RUN, *flags, *_RUFF]
    assert st.test_globs, "phân vùng ghi test/code (ADR-0028) không được mất theo"


def test_chi_co_requirements_txt_khai_pytest_thi_chay_bang_requirements(tmp_path):
    """Không có `pyproject.toml` (`MARKERS` → PY thẳng) vẫn là môi trường của khách."""
    _viet(tmp_path, {"requirements.txt": "django\npytest\n"})

    st = detect(tmp_path)

    assert st.test == [*_REQ_RUN, "--with-requirements", "requirements.txt", *_PYTEST]
    assert st.lint is not None and st.lint[0] == sys.executable, "ruff không khai → giữ đường cũ cho riêng lint"


def test_include_r_tinh_tuong_doi_theo_file_dang_doc(tmp_path):
    """`requirements/dev.txt` ghi `-r base.txt` nghĩa là `requirements/base.txt`, không phải `base.txt` ở gốc."""
    _viet(
        tmp_path,
        {
            "setup.cfg": "[metadata]\nname = k\n",
            "requirements/dev.txt": "-r base.txt\n--requirement=test.txt\n",
            "requirements/base.txt": "django\n",
            "requirements/test.txt": "-rlint.txt\npytest\n",
            "requirements/lint.txt": "ruff\n",
            "base.txt": "khong-lien-quan\n",
        },
    )

    st = detect(tmp_path)

    flags = ["--with-requirements", "requirements/dev.txt"]
    assert st.test == [*_REQ_RUN, *flags, *_PYTEST]
    assert st.lint == [*_REQ_RUN, *flags, *_RUFF]


def test_file_dev_khong_keo_requirements_txt_thi_truyen_ca_hai(tmp_path):
    """File dev không `-r requirements.txt` (khách cài hai file riêng): chỉ dựng từ file dev là thiếu Django."""
    _viet(
        tmp_path,
        {
            "requirements.txt": "django\n",
            "dev-requirements.txt": "pytest\n",
        },
    )

    st = detect(tmp_path)

    assert st.test == [
        *_REQ_RUN,
        "--with-requirements",
        "requirements.txt",
        "--with-requirements",
        "dev-requirements.txt",
        *_PYTEST,
    ]


def test_requirements_khong_khai_pytest_thi_giu_duong_cu(tmp_path):
    """Cùng lý lẽ `_py_stack`: env dựng từ requirements không có pytest chỉ đổi lỗi hạ tầng này lấy lỗi khác."""
    _viet(tmp_path, {"pyproject.toml": PYPROJECT_TCK01, "requirements.txt": "django\n"})

    st = detect(tmp_path)

    assert st.test is not None and st.test[0] == sys.executable
    assert st.lint is not None and st.lint[0] == sys.executable


def test_pyproject_co_bang_project_thi_khong_doi_sang_requirements(tmp_path):
    """Dự án uv thật vẫn đi `uv run` của ADR-0044 gốc — requirements chỉ là đường khi KHÔNG có `[project]`."""
    _viet(tmp_path, {"pyproject.toml": KHACH_DAY_DU, "requirements-dev.txt": "pytest\n"})

    st = detect(tmp_path)

    assert st.test == ["uv", "run", "--", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


def test_doc_requirements_bo_comment_tuy_chon_constraint_va_dong_hong(tmp_path):
    """Chỉ dòng yêu cầu thật mới là khai báo: comment, `--index-url`, `-e`, `-c` (constraint không cài gì) thì không."""
    _viet(
        tmp_path,
        {
            "requirements.txt": (
                "# pytest ghi trong comment không phải khai báo\n"
                "--index-url https://pypi.org/simple\n"
                "-c constraints.txt\n"
                "-e .\n"
                "\n"
                "django  # ruff cũng chỉ là comment\n"
            ),
            "constraints.txt": "pytest==8.3\nruff==0.6\n",
        },
    )

    st = detect(tmp_path)

    assert st.test is not None and st.test[0] == sys.executable
    assert st.lint is not None and st.lint[0] == sys.executable


def test_ten_goi_co_marker_va_hoa_thuong_van_nhan(tmp_path):
    _viet(tmp_path, {"requirements.txt": 'Pytest==8.3 ; python_version >= "3.10"\nRUFF\n'})

    st = detect(tmp_path)

    assert st.test is not None and st.test[:2] == ["uv", "run"]
    assert st.lint is not None and st.lint[:2] == ["uv", "run"]


def test_include_vong_thieu_file_ra_ngoai_repo_hoac_khong_doc_duoc_thi_bo_qua(tmp_path):
    """Dữ liệu khách hỏng là lý do không đổi đường, không phải crash (TRAPS: dữ liệu khách hỏng làm sập lượt)."""
    root = tmp_path / "repo"
    _viet(tmp_path, {"ngoai.txt": "pytest\n"})
    _viet(
        root,
        {
            "requirements.txt": "-r a.txt\n-r khong-co.txt\n-r ../ngoai.txt\n-r hong.txt\n-r\ndjango\n",
            "a.txt": "-r requirements.txt\n",
        },
    )
    (root / "hong.txt").write_bytes(b"\xff\xfepytest\n")

    st = detect(root)

    assert st.test is not None and st.test[0] == sys.executable


def test_lenh_requirements_di_qua_allowlist_va_sandbox_nhu_uv_run_cu(tmp_path):
    """Ranh giới tool không đổi: model chỉ chọn tên lệnh, đường dẫn nối sau `--`, argv[0] vẫn là `uv` nên backend
    container mở đúng PyPI (S2) và không gì khác; env vẫn đã lọc khoá."""
    from company.sandbox import Result, RunSpec
    from company.tools import WorkspaceTools

    class Spy:
        name = "container:test"

        def __init__(self) -> None:
            self.specs: list[RunSpec] = []

        def run(self, spec: RunSpec) -> Result:
            self.specs.append(spec)
            return Result(0, "ok", "", False, self.name)

    _viet(
        tmp_path,
        {
            "pyproject.toml": PYPROJECT_TCK01,
            "requirements.txt": "django\n",
            "requirements-dev.txt": "-r requirements.txt\npytest\n",
            "tests/test_a.py": "def test_a():\n    pass\n",
        },
    )
    spy = Spy()

    out = WorkspaceTools(tmp_path, sandbox=spy).run("test", ["tests/test_a.py"])

    assert out.startswith("exit=0")
    (spec,) = spy.specs
    assert spec.argv == [*_REQ_RUN, "--with-requirements", "requirements-dev.txt", *_PYTEST, "--", "tests/test_a.py"]
    assert spec.network is False
    assert spec.allowed_domains == ("pypi.org", "files.pythonhosted.org")
