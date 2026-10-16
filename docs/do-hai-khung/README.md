# Kịch bản đo hai khung: X-Agents và X-Templates

Câu hỏi: **với cùng một dự án mới, khung nào làm ra sản phẩm tốt hơn, tốn bao nhiêu token, và cần người chạm vào bao
nhiêu lần?** Trước kịch bản này, X-Agents có số đo thật (demo donghanhcungban 2026-09-02: 2,94M token, khoảng 3 giờ, 12/12
Must; `companies/software-company/docs/reports/2026-09-02-donghanhcungban-demo.md` §7) nhưng X-Templates chưa có số
nào. So hai thứ đó với nhau là so số đo với lời khai.

| Tệp | Là gì |
|---|---|
| `DE-BAI.md` | Đề bài chung DHCB-B1 v1: 12 Must, có hợp đồng chạy (`setup.sh`/`run.sh`/`test.sh`) để chấm hộp đen |
| `TRA-LOI-SAN.md` | Câu cố định người vận hành được dán khi khung cần người. Ngoài các câu đó không trả lời gì |
| `../../scripts/nghiem_thu_dhcb.py` | Nghiệm thu **ẩn**: 23 ca HTTP, phủ cả 12 Must. Tự kiểm hai chiều bằng bản mẫu đúng và bản mẫu cài lỗi |
| `../../scripts/do_hai_khung.py` | Gom token về một khuôn (`claude-jsonl` / `xagents`), ghép lượt (`ghep`), dựng báo cáo (`bao-cao`) |
| `bang-gia.example.json` · `luot.example.json` | Khuôn bảng giá (điền vào ngày đo) và khuôn một file lượt |

## 1. Giữ gì giống nhau, đo gì

**Giữ giống nhau**: cùng đề bài nguyên văn, cùng máy, cùng tài khoản Claude, cùng họ model (strong/main = Opus,
standard/executor = Sonnet, cùng phiên bản ghi vào lượt), repo đích rỗng như nhau, trần **6 giờ đồng hồ** mỗi lượt,
cùng một bảng giá để quy đổi USD. Mỗi khung chạy **cấu hình mặc định khuyến nghị** của nó, không bật thêm tính năng
nào chỉ cho lượt đo (`--test-author` của X-Agents đang tắt mặc định thì để tắt). Ghi mọi cờ đã dùng vào `ghi_chu`.

**Đo**:

| Nhóm | Chỉ số | Nguồn |
|---|---|---|
| Chất lượng | Must đạt /12 và ca đạt /23 của nghiệm thu ẩn; `test.sh` của dự án xanh không | `nghiem_thu_dhcb.py` |
| Chất lượng | Khung có tự khai xong không, so với kết quả nghiệm thu (độ khai đúng) | người ghi + nghiệm thu |
| Token | Input không cache · ghi cache · đọc cache · output · không tách được; theo model | `do_hai_khung.py` |
| Tiền | USD quy đổi theo bảng giá ngày đo (cả hai đều chạy bằng gói tài khoản, USD thật bằng 0) | `bao-cao --gia` |
| Người | Số lần và số phút người chạm vào lượt | `--can-thiep` |
| Thời gian | Từ lệnh đầu tới bản giao | transcript / bus |

**Số lượt**: 3 lượt mỗi khung, chạy **lần lượt, không song song** (chung tài khoản thì giới hạn tốc độ của lượt này
làm chậm lượt kia), theo thứ tự xen kẽ: `xa-1, xt-1, xt-2, xa-2, xa-3, xt-3`. Ba lượt không đủ để kết luận thống kê.
Báo cáo đưa ra trung vị và khoảng min–max; hai khoảng chồng lên nhau thì kết luận là **chưa phân biệt được**, không chọn
bên nào thắng.

## 2. Chuẩn bị máy (một lần)

Máy ảo hay container Ubuntu 24.04 dùng một lần: nghiệm thu chạy mã do model viết. Máy có Python 3.12, Node.js 22, `git`
và CLI `claude` đã đăng nhập. **Không** để khoá thật nào trên máy.

```bash
export DO=/srv/do-hai-khung                  # thư mục lượt đo, NGOÀI cả hai repo khung
mkdir -p $DO/ket-qua
git clone https://github.com/seeker19110/X-Agents    $DO/X-Agents
git clone https://github.com/seeker19110/X-Templates $DO/X-Templates
cd $DO/X-Agents && uv sync
cp docs/do-hai-khung/bang-gia.example.json $DO/bang-gia.json   # điền giá USD/1M token từ trang giá chính thức hôm nay
```

**Giữ bộ nghiệm thu ẩn**: phiên X-Templates là một phiên Claude Code, đọc được mọi file trên máy. Trước mỗi lượt
X-Templates thì chuyển `scripts/nghiem_thu_dhcb.py` và `platform/console/tests/fixtures/dhcb_mau/` ra khỏi máy (hoặc
chép kit sang sau khi lượt kết thúc). Lượt X-Agents không cần làm vậy, vì tool của agent bị khoá trong worktree của
repo khách (`tools.py`).

Cấu hình model của X-Agents, `$DO/X-Agents/companies/software-company/llm.yaml`. Chỉ dùng backend `claude-code`, để
cùng họ model với X-Templates, không dùng gateway:

```yaml
backends:
  - name: claude
    provider: claude-code
    models: {strong: <id Opus đang dùng>, standard: <id Sonnet đang dùng>, light: <id Sonnet đang dùng>}
    mcp_tools: true
routing:
  prefer: {strong: claude, standard: claude, light: claude}
effort: {strong: high, standard: medium, light: low}
max_input_chars: 120000
prices:            # chép từ bang-gia.json (khoá prices của X-Agents: input/output/cached_input/cache_write)
  <tiền tố Opus>:   {input: …, output: …, cached_input: …, cache_write: …}
  <tiền tố Sonnet>: {input: …, output: …, cached_input: …, cache_write: …}
```

Phải có `prices`: thiếu giá thì supervisor mở escalation `unpriced`, tức là thêm một can thiệp không thuộc khung.
**Không** đặt `budget_usd`, vì X-Templates cũng không có trần tiền trong phiên tương tác. Trần chung của hai bên là
6 giờ.

## 3. Một lượt X-Agents (`xa-<n>`)

```bash
L=xa-1; mkdir -p $DO/$L/repo && cd $DO/$L/repo
git init -q -b main && cp $DO/X-Agents/docs/do-hai-khung/DE-BAI.md . && git add . && git commit -qm "chore: đề bài DHCB-B1 v1"
python3 -c 'import json,sys; print(json.dumps({"project_id":"B1","description":open(sys.argv[1]).read(),"repo":sys.argv[2],"base":"main"},ensure_ascii=False))' \
  DE-BAI.md $DO/$L/repo > $DO/$L/req.json

cd $DO/X-Agents/companies/software-company
O="uv run python -m company.orchestrator --db $DO/$L/company.sqlite --artifacts $DO/$L/artifacts"
$O publish research-requests $DO/$L/req.json --actor human:do        # ghi giờ bắt đầu
COMPANY_DEPLOY=off $O --repo $DO/$L/repo --base main --integration company/integration --deliver run --watch 5
```

Một terminal khác trực theo `TRA-LOI-SAN.md`: `uv run python -m company.gate_cli --db $DO/$L/company.sqlite list`, mỗi
5–10 phút. Không bật `xagents-reviewer` hay `COMPANY_GATE_REVIEWER`. Lượt kết thúc khi gate `acceptance` đã ký và
`company/release` có tag, khi dự án dừng hẳn, hoặc khi hết 6 giờ. Lúc đó Ctrl+C tiến trình `run`.

**Bản đem chấm**: `company/release` nếu có, không thì `company/integration`. Ghi rõ đã chấm nhánh nào.

## 4. Một lượt X-Templates (`xt-<n>`)

```bash
L=xt-1; mkdir -p $DO/$L/repo $DO/$L/origin.git && git init -q --bare $DO/$L/origin.git
cd $DO/$L/repo && git init -q -b main && git remote add origin $DO/$L/origin.git
cp $DO/X-Agents/docs/do-hai-khung/DE-BAI.md . && git add . && git commit -qm "chore: đề bài DHCB-B1 v1" && git push -qu origin main
python3 $DO/X-Templates/scripts/install.py $DO/$L/repo && git add -A && git commit -qm "chore: cài X-Templates" && git push -q
# chuyển bộ nghiệm thu ẩn ra khỏi máy (§2) TRƯỚC lệnh dưới
claude --permission-mode auto --model <id Opus đang dùng>
```

Trong phiên, gõ đúng một tin nhắn: `/autopilot Làm dự án theo DE-BAI.md ở gốc repo.` Sau đó chỉ can thiệp theo
`TRA-LOI-SAN.md`. Lượt kết thúc khi autopilot báo `done`, `done-pending-human` (đã trả lời theo bảng mà vẫn dừng),
`blocked`, `budget`, hoặc khi hết 6 giờ.

**Bản đem chấm**: nhánh mà báo cáo cuối hay `GO-NO-GO.md` gọi là bản giao. Không có thì lấy commit mới nhất trên
`origin`. Ghi rõ đã chấm nhánh nào.

## 5. Chấm và gom số (sau mỗi lượt)

```bash
K=$DO/X-Agents/scripts
# nghiệm thu ẩn — trên bản sao sạch của đúng nhánh bản giao, không chấm trên thư mục khung vừa làm việc
git clone -q -b <nhánh bản giao> $DO/$L/repo $DO/$L/cham
python3 $K/nghiem_thu_dhcb.py --repo $DO/$L/cham --out $DO/$L/nghiem-thu.json

# token
python3 $K/do_hai_khung.py xagents $DO/$L/company.sqlite --out $DO/$L/token.json                 # lượt xa-*
python3 $K/do_hai_khung.py claude-jsonl ~/.claude/projects/$(echo $DO/$L/repo | tr / -) --out $DO/$L/token.json   # lượt xt-*

# một file lượt
python3 $K/do_hai_khung.py ghep --khung x-agents --lan 1 --token $DO/$L/token.json \
  --nghiem-thu $DO/$L/nghiem-thu.json --ket-cuc done --khai-xong co \
  --can-thiep "2:duyệt gate SPEC-B1" --can-thiep "1:trả lời câu hỏi làm rõ" --out $DO/ket-qua/luot-$L.json
```

Đọc `canh_bao` trong `token.json` trước khi ghép:
- Với X-Agents, `day_du: false` nghĩa là reviewer tự động đã chạy và tổng token **thiếu** phần của nó. Lượt đó không
  dùng được cho cột token.
- `nguoi` là số event do `human:*` ghi trên bus. Số này phải khớp với số dòng `--can-thiep`.

## 6. Báo cáo

```bash
python3 $K/do_hai_khung.py bao-cao $DO/ket-qua/luot-*.json --gia $DO/bang-gia.json > $DO/ket-qua/BAO-CAO.md
```

Báo cáo đem nộp là `docs/reports/<ngày>-do-hai-khung.md`, gồm:
- bảng `bao-cao` nguyên văn;
- id model và phiên bản (commit) của hai khung;
- nhánh đã chấm của từng lượt;
- mọi cảnh báo;
- một đoạn "điều số này **không** nói".

Không chép dữ liệu khách hay khoá vào đó (luật cấm 3). Dữ liệu ở đây đều là dữ liệu giả của đề bài.

## 7. Giới hạn đã biết của phép đo

- **Hai khung không cùng kiểu đối tượng.** X-Agents là runtime công ty, có bước nghiệm thu với khách. X-Templates là bộ
  luật cộng một phiên Claude Code. Phép đo so *kết quả giao* trên cùng một đề bài, không so kiến trúc.
- **Token không cùng nguồn đo.** Transcript Claude Code ghi từng tin nhắn. Audit-log X-Agents ghi từng bước, và lượt
  lỗi chỉ có tổng (`khong_tach`). Hai bên cùng được quy về năm loại token. Phần ghi cache của X-Agents không rõ TTL
  nên được tính theo giá 5 phút, phần `khong_tach` tính theo giá input; vì vậy cột USD là **cận dưới**.
- **Người làm thay reviewer của X-Agents.** Điều này cố ý, để mọi lời gọi model đều có trong sổ: lượt duyệt của
  `reviewer:tu-dong` không ghi token. Cái giá là X-Agents bị tính thêm can thiệp, trong khi X-Templates tự duyệt.
  Muốn đo X-Agents ở chế độ tự động hoàn toàn thì làm một biến thể riêng, và chỉ sau khi `gate.decide` của reviewer
  đã ghi `tokens`.
- **Nghiệm thu ẩn phụ thuộc trang quản trị.** Các ca "không lưu gì" (C11–C13, C15, C21) đọc trang quản trị: M-10 hỏng
  thì các ca này trượt theo. Ghi chú trong từng ca nói rõ lý do trượt.
- **Đề bài nhỏ, khoảng một ngày công.** Kết quả không suy ra được cho dự án cỡ M/L. Muốn đo cỡ đó thì cần đề bài v2
  riêng.
- **Ước chi phí để chạy cả kịch bản**: mỗi lượt X-Agents khoảng 3M token (demo 2026-09-02, cùng cỡ đề) và khoảng 3 giờ.
  Ba lượt X-Agents cộng ba lượt X-Templates mất khoảng 18 giờ đồng hồ. Phần token của X-Templates chính là điều phép
  đo này đi tìm.
