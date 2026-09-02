# ADR-0001: Dùng kiến trúc event-driven thay vì gọi trực tiếp giữa agent

Trạng thái: Accepted · Ngày: 2026-09-02

## Bối cảnh
Cần chạy nhiều agent song song, chịu lỗi từng agent, truy vết mọi hành động, và thay
agent mà không sửa agent khác.

## Quyết định
Mọi giao tiếp qua topic có schema và key. Blackboard là một topic có namespace và owner.

## Hệ quả
+ Scale theo partition, replay được, audit tự nhiên.
− Phức tạp hơn gọi hàm; cần bus và schema registry. Chấp nhận vì ưu điểm áp đảo ở quy mô > 3 agent.

## Phương án bị loại
- Gọi hàm trực tiếp (LangGraph edge cứng): khó song song, khó replay.
- Blackboard duy nhất không owner: vòng lặp vô hạn, tranh ghi.
