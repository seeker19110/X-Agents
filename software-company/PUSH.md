# Đưa lên repo Dev-Agents

```bash
git clone https://github.com/seeker19110/Dev-Agents.git
cd Dev-Agents
git checkout -b software-company
unzip ~/Downloads/software-company.zip -d .        # tạo thư mục software-company/
uv add pydantic pyyaml                             # nếu chưa có trong pyproject
uv run pytest software-company/tests -q            # 17 passed
git add software-company
git commit -m "feat(software-company): event-driven multi-agent software company (7 blocks, 18 agents)"
git push -u origin software-company
```

Sau đó mở PR `software-company → main`. Nếu muốn thay hẳn repo (không khuyến nghị):
tag bản cũ trước `git tag mep-agents-final && git push origin mep-agents-final`.
