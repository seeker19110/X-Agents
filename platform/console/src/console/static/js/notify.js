/* notify.js — ô Thông báo ở màn Trực ban (ADR-0005 bổ sung).

   Câu hỏi ô này trả lời: *nếu một gate mới mở ra lúc tôi KHÔNG nhìn trang, tôi có được báo không — và nếu không
   thì vì sao?* Ô Động cơ ngay trên trả lời "công ty có chạy không"; hai câu đứng cạnh nhau vì người trực rời máy
   cần cả hai là có.

   Mức (`verdict.level`) và lời giải thích (`verdict.say`) do `console/notify.py` tính — tầng dữ liệu, như
   `empty=True` của phễu sản phẩm (ADR-0003). Ở đây chỉ tra bảng pill và vẽ; không so số tin hỏng, không đoán.
   `off` là ô xám, không bao giờ xanh: "không có kênh nào" và "kênh đang thông" nhìn phải khác hẳn nhau. */
import {st} from "./state.js";
import {$, esc} from "./util.js";

export const PILL={off:["calm","tắt"],good:["good","đang báo"],warn:["warn","cần xem"],crit:["crit","hỏng"]};

export function facts(n){
  if(!n.enabled) return "";   // không kênh nào → console không canh gì; kể số 0 là kể một việc không diễn ra
  const parts=[];
  if(n.channels&&n.channels.length) parts.push("kênh: "+n.channels.map(esc).join(", "));
  parts.push(`đang canh ${esc(n.watching||0)} gate`);
  parts.push(`đã gửi ${esc(n.sent||0)} tin`);
  if(n.failed) parts.push(`hỏng ${esc(n.failed)} lần (từ khi console chạy)`);
  if(n.enabled&&n.public_url) parts.push(`link trong tin → <span class="mono">${esc(n.public_url)}</span>`);
  return parts.join(" · ");
}

export function renderNotify(){
  const box=$("#notify"); if(!box) return;
  const n=st().notify;
  if(!n||!n.verdict){ box.innerHTML='<div class="empty"><b>Thông báo</b>chưa đọc được /api/state</div>'; return; }
  const [cls,txt]=PILL[n.verdict.level]||PILL.off;
  box.innerHTML=`<div class="eng">
      <div class="eng-head"><b>Thông báo khi có gate mới</b> <span class="pill ${cls}">${esc(txt)}</span></div>
      <div class="note">${esc(n.verdict.say)}</div>
      ${n.enabled?`<div class="note">${facts(n)}</div>`:""}
      ${n.last_error&&!(n.failing&&n.failing.length)?`<div class="note">lỗi gần nhất (đã qua): <span class="mono">${esc(n.last_error)}</span></div>`:""}
    </div>`;
}
