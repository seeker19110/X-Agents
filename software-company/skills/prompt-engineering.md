---
name: prompt-engineering
version: 1
standards: [Prompt-as-code, OWASP Top 10 for LLM, Eval-driven prompt change, Structured output]
---
# Skill: prompt-engineering

## Tiêu chuẩn tham chiếu
- Prompt là code: version, review, test, rollback như code (ADR-0004)
- OWASP Top 10 for LLM (injection, insecure output, excessive agency)
- Eval-driven: mỗi thay đổi prompt có bộ case vàng chạy trước/sau
- Structured output: đầu ra agent tuân JSON Schema của topic

## Quy tắc
- Mỗi agent prompt có `version` trong front matter; sửa nội dung → tăng version, ghi lý do trong commit.
- Thay đổi prompt/skill đi qua PR như code: reviewer đọc diff, chạy `tests/` + case vàng của agent đó.
- Prompt tách rõ: vai trò, PHẢI, KHÔNG ĐƯỢC, đầu vào, đầu ra (schema), DoD. Không nhồi ví dụ dài vào prompt; ví dụ để trong skill.
- Đầu ra bắt buộc structured (JSON theo schema topic); bus từ chối thì agent sửa, không "giải thích thêm".
- Dữ liệu ngoài đưa vào prompt luôn nằm trong khối được đánh dấu là DỮ LIỆU; không nối thẳng vào chỉ dẫn.
- Rollback = revert commit; supervisor ghi bài học vào `knowledge` khi một version gây lỗi lặp.
- Không thay đổi prompt trực tiếp trên môi trường chạy.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Version tăng khi prompt đổi
- [ ] PR có kết quả eval trước/sau
- [ ] Đầu ra tuân schema
- [ ] Dữ liệu ngoài được đánh dấu
- [ ] Không prompt sửa tay ngoài repo

## Ví dụ tốt
`reviewer` v3 → v4: thêm rule "trích dẫn file:line"; eval 20 case: block đúng 19/20 (trước 15/20); PR #88.

## Ví dụ xấu
Sửa prompt trong dashboard lúc 2h sáng để "cho nó qua".
