# ADR-0055: lệnh `image_digest` cho builder — digest image trong Dockerfile/compose từ Docker Hub qua egress

Trạng thái: Accepted · Ngày: 2026-10-12 · Nối tiếp ADR-0054 (lệnh `lock`, cùng khuôn "việc cần mạng thì code mở đúng
domain"), ADR-0035 (sandbox, mạng tắt), ADR-0053 (compose là bằng chứng chạy), ADR gốc 0010 (egress Squid, allowlist
domain).

## Bối cảnh

Hub thật 2026-10-12, dự án `QLKH-DD-CSV`, ticket `DDCSV-20` (CR compose, ADR-0053): builder viết `Dockerfile` +
`docker-compose.yml` đúng acceptance, lint/test xanh, nhưng job CI `image-pin` của repo khách đòi mọi `FROM` có
`@sha256:`. Builder không có docker, không có mạng tới registry, không file nào trong repo hay blackboard có digest —
và đúng luật nó **không đoán**. Security chặn (DC-20-01), builder làm lại và ghi "việc còn lại: devops/orchestrator lấy
hai digest", qa chặn lần hai cùng lý do. Hai lượt model, một thông tin thiếu mà chỉ mạng mới trả lời được.

## Quyết định

1. **Lệnh `image_digest` trong allowlist `run`** khi repo có image chưa ghim: `image_digest.references(root)` đọc
   `Dockerfile`, `*/Dockerfile` (đúng tập job `image-pin` quét) và compose (`deploy.COMPOSE_NAMES`), lấy `FROM …` và
   `image: …`, bỏ alias stage, `${ARG}`, `scratch`, dòng đã có `@`. Không có gì cần ghim ⇒ không có lệnh.
2. **argv do code ghép**: `python -c <SCRIPT> <ref>…`, `SCRIPT` thuần stdlib chạy TRONG sandbox: token pull ẩn danh
   (`auth.docker.io`) rồi `HEAD /v2/<repo>/manifests/<tag>` (`registry-1.docker.io`) với Accept manifest list + OCI
   index. Digest là của **manifest list** — đúng thứ `docker pull` ghi vào `RepoDigests` và `FROM img:tag@sha256:` cần
   (đo trên máy chủ: `python:3.12.11-slim-bookworm` → `519591d6…`, khớp `docker image inspect` sau pull).
3. **Chỉ in, không ghi file**: mỗi dòng `ref@sha256:…`; ref lỗi in `ref LOI: …`, exit 1. Builder đọc rồi tự sửa
   `FROM`/`image:` — model quyết, code hành động, không có bước "code sửa Dockerfile hộ".
4. **Domain theo tên lệnh**: `registry_domains(argv, mode, command)` mở `auth.docker.io` + `registry-1.docker.io` chỉ
   khi `command == "image_digest"` và backend container (Squid, ADR gốc 0010). Subprocess không khai domain (như `lock`).
5. **Không nhận `paths`** (như `lock`): đối số là tham chiếu image do code đọc từ repo, model không thêm.

## Hệ quả

- Chỉ Docker Hub. `ghcr.io`, `quay.io`, registry riêng ⇒ `LOI: registry ngoai docker.io chua ho tro`, builder phải nói
  ra trong PR; mở thêm domain là một ADR khác với allowlist riêng.
- Image sandbox cần `python` (đã có từ ADR-0044); không cần docker/skopeo/crane trong image.
- Hai gọi HTTPS mỗi image, timeout 30 s; repo có 20 image vẫn dưới một phút.

## Cách đo

`tests/test_image_digest.py` (9 ca): đọc tham chiếu (alias, ARG, scratch, đã ghim, trùng), argv/domain qua `SpySandbox`
(container có domain, subprocess không), không `paths`, enum tool chỉ có lệnh khi còn image chưa ghim, script với
`urlopen` giả (token → HEAD đúng URL/Accept; registry lạ và lỗi mạng ⇒ `LOI` + exit 1). Đo thật: bản sao nhánh
`ticket/DDCSV-20` qua `ContainerSandbox("docker", "xagents-qlkh:py3.12")` trả hai dòng digest (xem PR).
