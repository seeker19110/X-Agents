"""settings.py: đọc/ghi phần model của llm.yaml từng công ty (không chạm mạng)."""

from __future__ import annotations

import pytest
import yaml

from console import settings

BASE = """\
provider: claude-code
max_tokens: 16000
prices:
  claude-opus-5: {input: 0.0, output: 0.0}
backends:
  - {name: claude-sub, provider: claude-code, models: {strong: claude-opus-5, standard: claude-sonnet-5}}
  - name: antigravity
    provider: openai
    base_url: http://127.0.0.1:8100/v1
    models: {strong: claude-sonnet-4-6, standard: gemini-3.8-flash-medium, light: gemini-3.8-flash-low}
routing:
  cooldown_s: 3600
  prefer: {strong: claude-sub, standard: antigravity}
"""


@pytest.fixture
def llm(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gateway_catalog", lambda *a, **k: [])
    path = tmp_path / "llm.yaml"
    path.write_text(BASE, encoding="utf-8")
    return path


def test_read_reports_current_state_as_the_default(llm):
    snap = settings.read_settings({"c": llm})
    entry = snap["companies"]["c"]
    assert entry["ok"] and [b["name"] for b in entry["backends"]] == ["claude-sub", "antigravity"]
    ag = entry["backends"][1]
    assert ag["via_gateway"] and ag["models"]["standard"] == "gemini-3.8-flash-medium"
    assert entry["prefer"] == {"strong": "claude-sub", "standard": "antigravity"}


def test_read_missing_file_is_a_state_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gateway_catalog", lambda *a, **k: [])
    snap = settings.read_settings({"c": tmp_path / "khong-co.yaml"})
    assert snap["companies"]["c"]["ok"] is False and "không có" in snap["companies"]["c"]["error"]


def test_unknown_model_flagged_only_for_gateway_backends(llm, monkeypatch):
    monkeypatch.setattr(settings, "gateway_catalog", lambda *a, **k: ["claude-sonnet-4-6"])
    entry = settings.read_settings({"c": llm})["companies"]["c"]
    by_name = {b["name"]: b for b in entry["backends"]}
    assert by_name["antigravity"]["unknown"] == ["gemini-3.8-flash-low", "gemini-3.8-flash-medium"]
    assert by_name["claude-sub"]["unknown"] == []   # model của CLI không phải việc của gateway


def test_set_model_keeps_other_keys_and_leaves_backup(llm):
    result = settings.update_settings(llm, models={"antigravity": {"standard": "gemini-3.7-flash-medium"}})
    data = yaml.safe_load(llm.read_text(encoding="utf-8"))
    assert data["backends"][1]["models"]["standard"] == "gemini-3.7-flash-medium"
    assert data["backends"][1]["models"]["light"] == "gemini-3.8-flash-low"   # tier khác không bị đụng
    assert data["prices"] == {"claude-opus-5": {"input": 0.0, "output": 0.0}}
    assert data["routing"]["cooldown_s"] == 3600
    assert result["changes"] == ["antigravity.standard → gemini-3.7-flash-medium"]
    assert yaml.safe_load(llm.with_suffix(".yaml.bak").read_text(encoding="utf-8"))["backends"][1]["models"][
        "standard"
    ] == "gemini-3.8-flash-medium"


def test_disable_moves_backend_out_of_the_list_read_by_the_company(llm):
    """`enabled: false` sẽ bị company.llm bỏ qua (backend vẫn chạy) — nên tắt phải là chuyển khỏi `backends:`."""
    settings.update_settings(llm, disable=["antigravity"])
    data = yaml.safe_load(llm.read_text(encoding="utf-8"))
    assert [b["name"] for b in data["backends"]] == ["claude-sub"]
    assert [b["name"] for b in data["disabled_backends"]] == ["antigravity"]
    # prefer trỏ vào backend vừa tắt bị bỏ, nếu không router sẽ chọn hụt.
    assert data["routing"]["prefer"] == {"strong": "claude-sub"}

    settings.update_settings(llm, enable=["antigravity"])
    data = yaml.safe_load(llm.read_text(encoding="utf-8"))
    assert [b["name"] for b in data["backends"]] == ["claude-sub", "antigravity"]
    assert "disabled_backends" not in data


def test_validation_rejects_bad_input_without_writing(llm):
    before = llm.read_text(encoding="utf-8")
    for kwargs in (
        {"models": {"khong-co": {"strong": "x"}}},
        {"models": {"antigravity": {"siêu": "x"}}},
        {"models": {"antigravity": {"strong": "  "}}},
        {"prefer": {"strong": "khong-co"}},
        {"disable": ["khong-co"]},
    ):
        with pytest.raises(settings.SettingsError):
            settings.update_settings(llm, **kwargs)
    assert llm.read_text(encoding="utf-8") == before


def test_prefer_cannot_point_at_a_disabled_backend(llm):
    settings.update_settings(llm, disable=["antigravity"])
    with pytest.raises(settings.SettingsError, match="đang bật"):
        settings.update_settings(llm, prefer={"light": "antigravity"})


def test_no_op_update_does_not_rewrite_the_file(llm):
    before = llm.read_text(encoding="utf-8")
    result = settings.update_settings(llm)
    assert result["changes"] == [] and result["backup"] is None
    assert llm.read_text(encoding="utf-8") == before   # giữ nguyên chú thích, không dump lại YAML


# ---------- CLI `python -m console models` ----------

def _cli(monkeypatch, llm_path, argv):
    from console import __main__ as cli

    monkeypatch.setattr(settings, "DEFAULT_LLM_YAML", {"software-company": llm_path})
    monkeypatch.setattr(settings, "gateway_catalog", lambda *a, **k: ["claude-sonnet-4-6"])
    return cli.main(["models", *argv])


def test_cli_lists_without_touching_the_file(llm, monkeypatch, capsys):
    before = llm.read_text(encoding="utf-8")
    assert _cli(monkeypatch, llm, []) == 0
    out = capsys.readouterr().out
    assert "antigravity" in out and "claude-sub" in out
    assert "gateway không có" in out or "⚠" in out      # model không nằm trong catalog được nêu rõ
    assert llm.read_text(encoding="utf-8") == before


def test_cli_set_and_prefer(llm, monkeypatch, capsys):
    code = _cli(monkeypatch, llm, ["--company", "software-company",
                                   "--set", "antigravity.standard=gemini-3.7-flash-low",
                                   "--prefer", "light=antigravity"])
    assert code == 0
    out = capsys.readouterr().out
    assert "antigravity.standard → gemini-3.7-flash-low" in out and "ưu tiên light → antigravity" in out
    data = yaml.safe_load(llm.read_text(encoding="utf-8"))
    assert data["routing"]["prefer"]["light"] == "antigravity"


def test_cli_rejects_bad_usage(llm, monkeypatch, capsys):
    assert _cli(monkeypatch, llm, ["--set", "antigravity.standard=x"]) == 1          # thiếu --company
    assert "Cần --company" in capsys.readouterr().out
    assert _cli(monkeypatch, llm, ["--company", "sai", "--set", "a.b=c"]) == 1
    assert _cli(monkeypatch, llm, ["--company", "software-company", "--set", "thieu-dau-bang"]) == 1
    assert "BACKEND.TIER=MODEL" in capsys.readouterr().out
    assert _cli(monkeypatch, llm, ["--company", "software-company", "--prefer", "sai-dinh-dang"]) == 1
    assert "TIER=BACKEND" in capsys.readouterr().out


def test_cli_reports_settings_error_without_traceback(llm, monkeypatch, capsys):
    assert _cli(monkeypatch, llm, ["--company", "software-company", "--disable", "khong-co"]) == 1
    assert "không có backend" in capsys.readouterr().out


def test_cli_says_nothing_changed_when_value_is_the_same(llm, monkeypatch, capsys):
    assert _cli(monkeypatch, llm, ["--company", "software-company", "--enable", "antigravity"]) == 0
    assert "Không có gì thay đổi" in capsys.readouterr().out


def test_cli_shows_missing_file_and_empty_catalog(tmp_path, monkeypatch, capsys):
    from console import __main__ as cli

    monkeypatch.setattr(settings, "DEFAULT_LLM_YAML", {"software-company": tmp_path / "khong-co.yaml"})
    monkeypatch.setattr(settings, "gateway_catalog", lambda *a, **k: [])
    assert cli.main(["models"]) == 0
    out = capsys.readouterr().out
    assert "không có" in out and "gateway không chạy" in out
