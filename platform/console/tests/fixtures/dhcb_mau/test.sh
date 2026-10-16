#!/bin/sh
# Bản mẫu: kiểm cú pháp là đủ — bộ test thật của nó chính là nghiệm thu ẩn.
exec python3 -m py_compile "$(dirname "$0")/app.py"
