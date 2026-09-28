"""__main__.py: CLI entrypoint. server/collect/decide thật do agent khác viết; ở đây monkeypatch
make_server để không mở socket thật (trừ các test đã có sẵn ở test_server.py dùng server thật)."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

from console import __main__ as cli


class _FakeServer:
    """Server giả: không mở socket, chỉ ghi lại lời gọi để test kiểm tra."""

    def __init__(self, *, port: int = 12345, raise_on_serve: Exception | None = None) -> None:
        self.port = port
        self._raise_on_serve = raise_on_serve
        self.serve_forever_called = False
        self.server_close_called = False

    def serve_forever(self) -> None:
        self.serve_forever_called = True
        if self._raise_on_serve is not None:
            raise self._raise_on_serve

    def server_close(self) -> None:
        self.server_close_called = True


def test_argv_none_lay_tu_sys_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """argv=None -> lấy sys.argv[1:]. Dùng --host bậy để thoát sớm bằng mã 2, không đụng make_server."""
    monkeypatch.setattr(sys, "argv", ["console", "--host", "8.8.8.8"])
    assert cli.main() == 2


def test_models_subcommand_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from console import settings

    llm = tmp_path / "llm.yaml"
    llm.write_text("backends: []\n", encoding="utf-8")
    monkeypatch.setattr(settings, "DEFAULT_LLM_YAML", {"software-company": llm})
    monkeypatch.setattr(settings, "gateway_catalog", lambda *a, **k: [])
    assert cli.main(["models"]) == 0
    assert "CẤU HÌNH MODEL" in capsys.readouterr().out


def test_host_khong_loopback_khong_co_i_know_tra_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--host", "8.8.8.8"]) == 2
    out = capsys.readouterr().out
    assert "Từ chối khởi động" in out


def test_host_khong_loopback_voi_i_know_canh_bao_va_tiep_tuc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--i-know: in cảnh báo rồi vẫn đi tới make_server (mock để không mở socket ra ngoài)."""
    fake = _FakeServer()
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: fake)
    token_path = tmp_path / "tok"
    token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)
    monkeypatch.setattr(cli, "generate_token", lambda: "tok")

    code = cli.main(["--host", "8.8.8.8", "--i-know"])

    out = capsys.readouterr().out
    assert "CẢNH BÁO" in out
    assert code == 0
    assert fake.serve_forever_called
    assert fake.server_close_called
    assert not token_path.exists()  # unlink(missing_ok=True) đã dọn file token


def test_make_server_oserror_tra_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def _raise(*a: Any, **k: Any) -> Any:
        raise OSError("port đã dùng")

    monkeypatch.setattr(cli, "make_server", _raise)
    assert cli.main([]) == 1
    assert "Không mở được" in capsys.readouterr().out


def test_khoi_dong_thanh_cong_in_banner_va_dung_ctrl_c(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = _FakeServer(raise_on_serve=KeyboardInterrupt())
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: fake)
    token_path = tmp_path / "tok2"
    token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)

    code = cli.main([])

    out = capsys.readouterr().out
    assert "CONSOLE" in out
    assert "Đã dừng console" in out
    assert code == 0
    assert fake.server_close_called
    assert not token_path.exists()


def test_open_browser_thanh_cong(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _FakeServer()
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: fake)
    token_path = tmp_path / "tok3"
    token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))

    assert cli.main(["--open"]) == 0
    assert opened


def test_open_browser_that_bai_khong_lam_hong_khoi_dong(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = _FakeServer()
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: fake)
    token_path = tmp_path / "tok4"
    token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)

    def _raise(url: str) -> None:
        raise RuntimeError("không có trình duyệt")

    monkeypatch.setattr(cli.webbrowser, "open", _raise)

    assert cli.main(["--open"]) == 0
    assert "Không mở được trình duyệt" in capsys.readouterr().out


def test_dung_bang_thanh_cong_khong_ctrl_c(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """serve_forever() trả về bình thường (không KeyboardInterrupt) — nhánh finally vẫn chạy."""
    fake = _FakeServer()
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: fake)
    token_path = tmp_path / "tok5"
    token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)

    assert cli.main([]) == 0
    assert fake.serve_forever_called and fake.server_close_called
    assert not token_path.exists()


@pytest.mark.parametrize("flag, expect", [(["--allow-submit"], True), ([], False)])
def test_allow_submit_truyen_xuong_make_server_va_in_banner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: list[str], expect: bool
) -> None:
    """--allow-submit là quyền riêng: đi thẳng vào make_server(allow_submit=...), không dính --allow-decide/--allow-config."""
    fake = _FakeServer()
    seen: dict[str, Any] = {}

    def _make(*a: Any, **k: Any) -> Any:
        seen.update(k)
        return fake

    monkeypatch.setattr(cli, "make_server", _make)
    token_path = tmp_path / "tok6"
    token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)

    assert cli.main(flag) == 0
    assert seen["allow_submit"] is expect
    assert seen["readonly"] is True and seen["allow_config"] is False
    out = capsys.readouterr().out
    assert ("Giao việc:   CHO PHÉP" if expect else "--allow-submit để giao việc") in out


def test_dunder_main_goi_main_va_sys_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m console --help`: argparse tự thoát bằng SystemExit(0), không chạm make_server."""
    monkeypatch.setattr(sys, "argv", ["console", "--help"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("console.__main__", run_name="__main__")
    assert e.value.code == 0


# ---------- --with-gateway: một lệnh bật cả gateway (ADR-0011 §3) ----------

def test_with_gateway_bat_gateway_truoc_khi_phuc_vu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--with-gateway` phải chạy `gateway start` TRƯỚC khi console phục vụ. Không có nó thì người trực bật
    console, giao việc, rồi ngồi chờ một công ty không có model — không lỗi, không dấu hiệu."""
    goi: list[list[str]] = []
    monkeypatch.setattr(cli, "start_gateway", lambda: (goi.append(["gateway", "start"]), 0)[1])
    fake = _FakeServer(raise_on_serve=KeyboardInterrupt())
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: fake)
    token_path = tmp_path / "tok-gw"; token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)

    code = cli.main(["--with-gateway"])

    assert goi == [["gateway", "start"]], "phải gọi gateway start đúng một lần"
    assert code == 0 and fake.serve_forever_called


def test_with_gateway_that_bai_thi_dung_lai_khong_phuc_vu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Gateway không lên được → dừng và báo, KHÔNG im lặng chạy tiếp với công ty không có model (ADR-0011 §3)."""
    monkeypatch.setattr(cli, "start_gateway", lambda: 1)
    fake = _FakeServer()
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: fake)
    monkeypatch.setattr(cli, "write_token_file", lambda token: tmp_path / "khong-dung-toi")

    code = cli.main(["--with-gateway"])

    assert code == 1
    assert not fake.serve_forever_called, "không được phục vụ khi gateway hỏng"
    assert "gateway" in capsys.readouterr().out.lower()


# ---------- --deliver-remote: động cơ bật từ console phải giao hàng được (ADR-0027) ----------

def test_deliver_remote_di_toi_engine_manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Thiếu `--deliver --push-remote` thì `_deliver()` không bao giờ chạy: release được ký, khách nghiệm
    thu, mà tag/nhánh release không tới repo khách (sự cố 2026-09-10). Cờ phải đi tới `EngineManager`."""
    nhan: dict[str, object] = {}
    fake = _FakeServer(raise_on_serve=KeyboardInterrupt())
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: (nhan.update(k), fake)[1])
    token_path = tmp_path / "tok-dl"; token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)

    code = cli.main(["--allow-engine", "--deliver-remote", "origin"])

    assert code == 0
    assert nhan["deliver_remote"] == "origin"


def test_mac_dinh_khong_giao_hang(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Chiều ngược: không nêu remote thì không bao giờ push lên repo khách."""
    nhan: dict[str, object] = {}
    fake = _FakeServer(raise_on_serve=KeyboardInterrupt())
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: (nhan.update(k), fake)[1])
    token_path = tmp_path / "tok-nodl"; token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)

    assert cli.main([]) == 0
    assert nhan.get("deliver_remote") is None


def test_deliver_remote_khong_co_allow_engine_thi_dung_lai(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Không có `--allow-engine` thì console không bật được động cơ nào, nên `--deliver-remote` là một lời
    hứa suông. Dừng và nói ra, không im lặng nhận cờ rồi không giao gì cả (TRAPS: chế độ hỏng phải tự khai)."""
    def _khong_duoc_goi(*a: object, **k: object) -> object:  # pragma: no cover - chạy vào là test đã sai
        raise AssertionError("không được dựng server khi cờ mâu thuẫn")
    monkeypatch.setattr(cli, "make_server", _khong_duoc_goi)
    monkeypatch.setattr(cli, "write_token_file", lambda token: tmp_path / "khong-dung-toi")

    code = cli.main(["--deliver-remote", "origin"])

    assert code == 2
    assert "--allow-engine" in capsys.readouterr().out


def test_khong_co_co_thi_khong_dung_toi_gateway(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mặc định KHÔNG bật gateway: console vẫn là bảng điều hành chỉ đọc, không tự spawn tiến trình nền."""
    def _khong_duoc_goi() -> int:  # pragma: no cover - thân hàm chạy là test đã sai
        raise AssertionError("không có --with-gateway thì không được đụng tới gateway")
    monkeypatch.setattr(cli, "start_gateway", _khong_duoc_goi)
    fake = _FakeServer(raise_on_serve=KeyboardInterrupt())
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: fake)
    token_path = tmp_path / "tok-no-gw"; token_path.write_text("t", encoding="utf-8")
    monkeypatch.setattr(cli, "write_token_file", lambda token: token_path)

    assert cli.main([]) == 0


def test_start_gateway_goi_dung_lenh_va_tra_ma_thoat(monkeypatch: pytest.MonkeyPatch) -> None:
    """`start_gateway` chạy `python -m gateway start` như tiến trình con (không import gateway) và trả nguyên
    mã thoát của nó — mọi phần chờ `/health` đã nằm trong `gateway start`, đây không dựng lại vòng chờ nào."""
    da_chay: list[list[str]] = []

    class _KetQua:
        returncode = 7

    def _fake_run(cmd: list[str], **kw: Any) -> Any:
        da_chay.append(cmd)
        assert kw == {"check": False}, "phải tự xử mã thoát, không để subprocess ném"
        return _KetQua()

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    assert cli.start_gateway() == 7
    assert da_chay == [[sys.executable, "-m", "gateway", "start"]]


def test_utf8_stdio_bo_qua_stream_khong_reconfigure_va_nuot_loi() -> None:
    """Phủ nhánh (audit 2026-09-28, #366): stream không có `reconfigure` (bị thay bằng StringIO, pipe cũ) bị bỏ
    qua, stream đổi hỏng không làm CLI chết. Truyền stream giả làm tham số — không thay `sys.stdout` toàn cục,
    thay nó làm lệch phép đo coverage (cùng lý do với `platform/gateway/tests/test_x_manage_coverage.py`)."""
    calls: list[dict[str, str]] = []

    class DoiDuoc:
        def reconfigure(self, **kw: str) -> None:
            calls.append(kw)

    class Hong:
        def reconfigure(self, **kw: str) -> None:
            raise ValueError("stream đã đóng")

    cli._utf8_stdio(object(), Hong(), DoiDuoc())
    assert calls == [{"encoding": "utf-8", "errors": "replace"}]
