#!/usr/bin/env python3
"""CLI console.

  python -m console                       chạy console chỉ đọc tại http://127.0.0.1:8200
  python -m console --allow-decide        cho phép duyệt gate từ trang
  python -m console --allow-config        cho phép sửa model/backend của từng công ty từ trang
  python -m console --open                mở trình duyệt sau khi khởi động

  python -m console models                        xem cấu hình model của cả hai công ty
  python -m console models --company software-company --set antigravity.standard=gemini-3.8-flash-medium
  python -m console models --company software-company --prefer standard=antigravity --disable chatgpt-sub

Mặc định đọc SQLite của hai xưởng cạnh repo; thiếu file DB là bình thường (chưa chạy xưởng đó).
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import webbrowser
from pathlib import Path

from console.server import (
    DEFAULT_COMPANY_DB,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_STUDIO_DB,
    generate_token,
    is_loopback_host,
    make_server,
    write_token_file,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m console", description="Console điều hành hợp nhất (chạy cục bộ).")
    p.add_argument("--company-db", type=Path, default=DEFAULT_COMPANY_DB, help="SQLite bus của software-company")
    p.add_argument("--studio-db", type=Path, default=DEFAULT_STUDIO_DB, help="SQLite bus của Studio-creators")
    p.add_argument("--host", default=DEFAULT_HOST, help="địa chỉ bind (chỉ loopback, trừ khi có --i-know)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"cổng (mặc định {DEFAULT_PORT})")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--readonly", dest="readonly", action="store_true", default=True, help="chặn mọi POST (mặc định)")
    mode.add_argument("--allow-decide", dest="readonly", action="store_false", help="cho phép POST /api/gate/decide")
    p.add_argument("--allow-config", action="store_true",
                   help="cho phép POST /api/settings (sửa llm.yaml); tách riêng khỏi --allow-decide")
    p.add_argument("--i-know", action="store_true", help="chấp nhận rủi ro khi bind ra ngoài loopback")
    p.add_argument("--open", dest="open_browser", action="store_true", help="mở trình duyệt (cố gắng, không bắt buộc)")
    return p


def _print_settings(snapshot: dict) -> None:
    catalog = snapshot.get("catalog") or []
    print("=" * 72)
    print("  CẤU HÌNH MODEL THEO CÔNG TY  (mặc định = đúng cái đang chạy)")
    print("=" * 72)
    for company, entry in snapshot["companies"].items():
        print(f"  {company}   {entry['path']}")
        if not entry["ok"]:
            print(f"      {entry['error']}")
            continue
        for b in entry["backends"]:
            state = "bật " if b["enabled"] else "TẮT "
            tiers = "  ".join(f"{t}={b['models'][t] or '-'}" for t in snapshot["tiers"])
            warn = f"   ⚠ gateway không có: {', '.join(b['unknown'])}" if b["unknown"] else ""
            print(f"      [{state}] {b['name']:<14} {b['provider']:<12} {tiers}{warn}")
        prefer = entry["prefer"]
        print(f"      ưu tiên: {prefer if prefer else '(không đặt — router tự chọn theo thứ tự backend)'}")
    print("-" * 72)
    print(f"  Model gateway đang phục vụ: {', '.join(catalog) if catalog else '(gateway không chạy — bỏ qua kiểm tra tên)'}")
    print("=" * 72)


def cmd_models(args: argparse.Namespace) -> int:
    from console.settings import DEFAULT_LLM_YAML, SettingsError, read_settings, update_settings

    if not (args.set or args.prefer or args.enable or args.disable):
        _print_settings(read_settings())
        return 0
    if not args.company:
        print("[-] Cần --company để biết sửa llm.yaml của công ty nào.")
        return 1
    if args.company not in DEFAULT_LLM_YAML:
        print(f"[-] --company phải là một trong {sorted(DEFAULT_LLM_YAML)}")
        return 1

    models: dict[str, dict[str, str]] = {}
    for item in args.set or []:
        target, _, model = item.partition("=")
        backend, _, tier = target.partition(".")
        if not (backend and tier and model):
            print(f"[-] --set phải có dạng BACKEND.TIER=MODEL, nhận được: {item}")
            return 1
        models.setdefault(backend, {})[tier] = model
    prefer: dict[str, str] = {}
    for item in args.prefer or []:
        tier, _, backend = item.partition("=")
        if not (tier and backend):
            print(f"[-] --prefer phải có dạng TIER=BACKEND, nhận được: {item}")
            return 1
        prefer[tier] = backend

    try:
        result = update_settings(
            DEFAULT_LLM_YAML[args.company], models=models or None, prefer=prefer or None,
            enable=args.enable, disable=args.disable,
        )
    except SettingsError as e:
        print(f"[-] {e}")
        return 1
    if not result["changes"]:
        print("[*] Không có gì thay đổi.")
        return 0
    print(f"[+] Đã ghi {result['path']}  (bản cũ: {result['backup']})")
    for c in result["changes"]:
        print(f"    - {c}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Console Windows mặc định cp1252 không in được tiếng Việt.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "models":
        mp = argparse.ArgumentParser(prog="python -m console models", description="Xem/sửa model của từng công ty")
        mp.add_argument("--company", help="software-company | Studio-creators")
        mp.add_argument("--set", action="append", metavar="BACKEND.TIER=MODEL")
        mp.add_argument("--prefer", action="append", metavar="TIER=BACKEND")
        mp.add_argument("--enable", action="append", metavar="BACKEND")
        mp.add_argument("--disable", action="append", metavar="BACKEND")
        return cmd_models(mp.parse_args(argv[1:]))
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not is_loopback_host(args.host):
        if not args.i_know:
            print(f"[-] Từ chối khởi động: --host {args.host} không phải loopback.")
            print("    Console cho phép DUYỆT GATE qua HTTP; mở ra ngoài loopback là mở quyền đó cho cả mạng.")
            print("    Thật sự muốn thì thêm --i-know (và tự lo firewall/reverse proxy).")
            return 2
        print("=" * 68)
        print(f"[!] CẢNH BÁO: console đang bind {args.host}, KHÔNG phải loopback.")
        print("    Ai chạm được cổng này và lấy được token là duyệt gate thay bạn được.")
        print("    Chỉ làm vậy sau firewall/reverse proxy, và tắt ngay khi xong.")
        print("=" * 68)

    token = generate_token()
    token_path = write_token_file(token)
    try:
        server = make_server(
            args.host,
            args.port,
            token=token,
            readonly=args.readonly,
            allow_config=args.allow_config,
            company_db=args.company_db,
            studio_db=args.studio_db,
        )
    except OSError as e:
        print(f"[-] Không mở được {args.host}:{args.port}: {e}")
        return 1

    url = f"http://{args.host}:{server.port}/"
    mode = "CHỈ ĐỌC (--allow-decide để duyệt gate)" if args.readonly else "CHO PHÉP DUYỆT GATE"
    print("=" * 68)
    print("  CONSOLE — bảng điều hành hợp nhất của X-Agents")
    print("=" * 68)
    print(f"  Mở trang:    {url}")
    print(f"  Chế độ:      {mode}")
    print(f"  Cấu hình:    {'SỬA ĐƯỢC model/backend' if args.allow_config else 'chỉ xem (--allow-config để sửa)'}")
    print(f"  Token file:  {token_path}  (quyền 0600, mới mỗi lần chạy)")
    print(f"  company.db:  {args.company_db}{'' if args.company_db.exists() else '  (chưa có — phần này sẽ trống)'}")
    print(f"  studio.db:   {args.studio_db}{'' if args.studio_db.exists() else '  (chưa có — phần này sẽ trống)'}")
    print("-" * 68)
    print("  Token đã được chèn sẵn vào trang; cứ mở URL trên là dùng được. Ctrl-C để dừng.")
    print("=" * 68)

    if args.open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:  # trình duyệt là tiện ích, hỏng thì kệ
            print(f"[*] Không mở được trình duyệt: {e}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Đã dừng console.")
    finally:
        server.server_close()
        token_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
