#!/usr/bin/env python3
"""CLI console.

  python -m console                       chạy console chỉ đọc tại http://127.0.0.1:8200
  python -m console --allow-decide        cho phép duyệt gate từ trang
  python -m console --open                mở trình duyệt sau khi khởi động

Mặc định đọc SQLite của hai xưởng cạnh repo; thiếu file DB là bình thường (chưa chạy xưởng đó).
"""

from __future__ import annotations

import argparse
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
    p.add_argument("--i-know", action="store_true", help="chấp nhận rủi ro khi bind ra ngoài loopback")
    p.add_argument("--open", dest="open_browser", action="store_true", help="mở trình duyệt (cố gắng, không bắt buộc)")
    return p


def main(argv: list[str] | None = None) -> int:
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
