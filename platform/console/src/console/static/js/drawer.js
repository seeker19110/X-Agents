/* drawer.js — tách từ index.html ở K7.1 (kịch bản B). Không build step, không CDN.
    */
import {ME_KEY, READONLY, api} from "./api.js";
import {view, writeHash} from "./router.js";
import {S, setDrawerOpen, st} from "./state.js";
import {applyPending, freshLabel, load, retry} from "./stream.js";
import {ahead} from "./tables.js";
import {filter} from "./tiles.js";
import {$, $$, esc, num, setQ} from "./util.js";

/* ---------- ngăn kéo ---------- */
export const drawer=$("#drawer"), scrim=$("#scrim");
export let openId=null;                                  // id đang mở trong ngăn kéo, để route không mở lại chính nó
export function shut(){
  drawer.classList.remove("on");scrim.classList.remove("on");drawer.setAttribute("aria-hidden","true");
  setDrawerOpen(false); openId=null;
  writeHash(view,null,null,false);                // Back đóng ngăn kéo; đóng tay cũng phải rời khỏi địa chỉ chi tiết
  applyPending();                                 // dữ liệu về trong lúc đọc thì giờ mới vẽ
}
scrim.addEventListener("click",shut);
document.addEventListener("keydown",e=>{if(e.key==="Escape")shut();});
export function show(html){
  drawer.innerHTML=html;drawer.classList.add("on");scrim.classList.add("on");drawer.setAttribute("aria-hidden","false");
  setDrawerOpen(true); freshLabel();
  const c=drawer.querySelector(".x"); if(c)c.addEventListener("click",shut);
  const b=drawer.querySelector(".dr-b"); if(b)b.scrollTop=0;
}
export const toastEl=$("#toast");
export function toast(m){toastEl.textContent=m;toastEl.classList.add("on");clearTimeout(toastEl._h);toastEl._h=setTimeout(()=>toastEl.classList.remove("on"),2600);}

export const VERB={approve:"Đã duyệt",request_changes:"Đã trả lại sửa",hold:"Đã giữ lại",reject:"Đã từ chối",rollback:"Đã thu hồi"};
export const VERB_ING={request_changes:"trả lại",hold:"giữ",reject:"từ chối",rollback:"thu hồi"};
export const HINT_TMPL="root_cause: \ndecision: \nhint: ";
export const RO_NOTE='Chế độ <b>chỉ đọc</b> — nút quyết định bị khoá. Muốn duyệt gate từ trang này thì dừng server và chạy lại '
  +'<code>uv run python -m console --allow-decide</code> (chỉ nghe trên 127.0.0.1, vẫn cần token phiên).';

export function openGate(id){
  const g=(st().gates||[]).find(x=>x.id===id); if(!g) return;
  openId=id; writeHash(view,"gate",id,false);
  const cl=g.cl||[], facts=g.facts||[];
  show(`<div class="dr-h">
      <div><div class="id">${esc(g.id)}</div><h2>${esc(g.title)}</h2></div>
      <button class="x" aria-label="Đóng">✕</button>
    </div>
    <div class="dr-b">
      <div><div class="eyebrow" style="margin-bottom:8px">Hồ sơ</div>
        <dl class="dl">${facts.map(f=>`<dt>${esc(f[0])}</dt><dd>${esc(f[1])}</dd>`).join("")}
        <dt>xưởng</dt><dd>${esc(g.xuong)}</dd><dt>created_by</dt><dd>${esc(g.by)}</dd><dt>triggered_by</dt><dd>${esc(g.trigger)}</dd></dl></div>
      <div><div class="eyebrow" style="margin-bottom:4px;display:flex;align-items:center;justify-content:space-between;gap:8px">
          <span>Checklist — tick hết mới duyệt được</span>
          ${cl.length>1?'<button class="fbtn" id="cl-all" type="button">Tick tất cả</button>':""}</div>
        <div id="cl">${cl.length?cl.map((c,i)=>`<label class="check"><input type="checkbox" data-i="${i}"><span><span class="n">${esc(c[0])}</span><span class="d">${esc(c[1])}</span></span></label>`).join("")
          :'<div class="empty">Gate này không kèm checklist.</div>'}</div></div>
      ${(g.effect||g.reject)?`<div class="dead" style="border-color:var(--line);background:var(--surface-2)">
        <h2 style="color:var(--ink)">Hậu quả — cả hai chiều</h2>
        ${g.effect?`<div class="row"><code>duyệt</code><span>${esc(g.effect)}${g.agent?` Agent chạy lại: <b>${esc(g.agent)}</b>.`:""}</span></div>`:""}
        ${g.reject?`<div class="row"><code>từ chối</code><span>${esc(g.reject)}</span></div>`:""}</div>`:""}
      <div><div class="eyebrow" style="margin-bottom:6px">Hồ sơ bằng chứng (gate_brief)</div>
        <button class="fbtn" id="brief-btn" type="button">Dựng hồ sơ — nửa "người tự kiểm thêm" của checklist</button>
        <pre id="brief" hidden style="white-space:pre-wrap;font-family:var(--mono);font-size:11.5px;color:var(--ink-2);max-height:340px;overflow:auto;margin:8px 0 0"></pre></div>
      <div><div class="eyebrow" style="margin-bottom:6px">Hint agent sẽ nhận — nguyên văn</div>
        <pre id="hint-preview" style="white-space:pre-wrap;font-family:var(--mono);font-size:12px;color:var(--ink-2);margin:0;min-height:1.2em">(chưa ghi gì — agent sẽ nhận một chuỗi rỗng)</pre></div>
      <p class="note">Quyết định đi qua <code>HumanGate</code> của xưởng và ghi thẳng vào <code>audit-log</code> kèm tên bạn.
        Người duyệt phải khác người tạo (four-eyes); gate chỉ quyết một lần.${g.kind==="escalation"?" <b>Lý do bạn ghi được gửi thẳng cho agent làm hint</b> — một chữ “ok” là bảo nó không có gì để sửa.":""}</p>
    </div>
    ${g.decidable===false?`<div class="dr-f"><p class="note">${g.reviewer_signed
        ?`Reviewer ${esc(g.reviewer_signed.by)} đã ký ${esc(g.reviewer_signed.decision)}. Cờ reviewer đang tắt ở tiến trình đọc, nên quyết định chưa được áp; bật lại cờ ở orchestrator để xử lý.`
        :`Đây không phải gate — là câu hỏi agent đặt cho người. Không có nút duyệt: trả lời ở màn <b>Giao việc → Trả lời câu hỏi làm rõ</b> theo đúng <code>question_id</code> ở checklist trên.`}</p></div>`:`<div class="dr-f">
      <label class="by">Bạn là <input id="by" value="${esc(localStorage.getItem(ME_KEY)||"human:owner")}" placeholder="human:owner"></label>
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:4px">
        <button class="fbtn" id="tmpl" type="button">Chèn mẫu root_cause / decision / hint</button>
        <span class="note">lý do đi thẳng cho agent làm hint — nêu nguyên nhân gốc và việc phải làm</span></div>
      <textarea id="reason" placeholder="root_cause: vì sao hỏng&#10;decision: bạn quyết gì&#10;hint: agent phải làm gì tiếp"></textarea>
      <div class="verbs">
        <button class="vb primary" data-d="approve" disabled>Duyệt</button>
        <button class="vb" data-d="request_changes">Trả lại sửa</button>
        <button class="vb" data-d="hold">Giữ</button>
        <button class="vb danger" data-d="reject">Từ chối</button>
        ${g.kind==="publish"?'<button class="vb danger" data-d="rollback">Thu hồi</button>':""}
      </div>
      <div class="note" id="gnote"></div>
    </div>`}`);
  if(g.decidable===false) return;  // không có ô tick/nút duyệt để nối sự kiện

  const boxes=$$("#cl input");
  const sync=()=>{
    const left=boxes.filter(b=>!b.checked).length;
    // Escalation: lý do là HINT gửi thẳng cho agent — "ok" là bảo nó không có gì để sửa (đo được 13:05 2026-09-06,
    // duyệt REL-025 bằng "ok"). Chưa đủ 20 ký tự thì KHÔNG cho duyệt, không chỉ cảnh báo.
    const raw=$("#reason").value;
    $("#hint-preview").textContent=raw.trim()?raw:"(chưa ghi gì — agent sẽ nhận một chuỗi rỗng)";
    const thin=g.kind==="escalation"&&raw.trim().length<20;
    drawer.querySelector('[data-d="approve"]').disabled=READONLY||left>0||thin;
    $("#gnote").innerHTML=READONLY?RO_NOTE:left?`Còn ${left} mục chưa tick.`
      :thin?'Ghi lý do ít nhất 20 ký tự — nó là hint agent nhận: nêu root cause và việc cần làm, không phải "ok".':"Đủ điều kiện duyệt.";
  };
  boxes.forEach(b=>b.addEventListener("change",sync));
  $("#reason").addEventListener("input",sync);
  // Gate nợ kiến trúc/debt có thể mang 20-40 mục (một dòng mỗi khoản nợ) — tick từng ô một là việc vô nghĩa khi
  // đã đọc xong danh sách trong "Hồ sơ bằng chứng"; nút này chỉ đánh dấu đã đọc, không thay thế cho lý do ≥20
  // ký tự vẫn bắt buộc ở trên (`sync` vẫn chặn nếu `reason` quá ngắn).
  const clAll=$("#cl-all");
  if(clAll) clAll.addEventListener("click",()=>{boxes.forEach(b=>{b.checked=true;});sync();});
  // C6: mẫu ba dòng — người ghi "ok" vì không biết phải ghi gì, không phải vì lười.
  $("#tmpl").addEventListener("click",()=>{
    const t=$("#reason"); if(!t.value.trim()) t.value=HINT_TMPL; t.focus(); sync();});
  // C8: hồ sơ bằng chứng ngay cạnh nút duyệt, không phải trong một terminal khác.
  $("#brief-btn").addEventListener("click",async()=>{
    const btn=$("#brief-btn"), box=$("#brief");
    btn.disabled=true; box.hidden=false; box.textContent="Đang dựng hồ sơ (replay cả log — vài giây)…";
    try{
      const r=await api(`/api/gate/brief?id=${encodeURIComponent(g.id)}&xuong=${encodeURIComponent(g.xuong)}`);
      box.textContent=r.ok?r.md:"Không dựng được hồ sơ: "+r.error;
    }catch(err){ box.textContent="Không dựng được hồ sơ: "+err.message; }
    btn.disabled=false;});
  if(READONLY){$$(".vb",drawer).forEach(b=>{b.disabled=true;});}
  sync();

  drawer.querySelector(".verbs").addEventListener("click",async e=>{
    const b=e.target.closest(".vb"); if(!b||b.disabled) return;
    const d=b.dataset.d, reason=$("#reason").value.trim(), by=$("#by").value.trim();
    if(!by){$("#by").focus();toast("Ghi tên người duyệt trước đã.");return;}
    if(d!=="approve"&&!reason){$("#reason").focus();toast("Cần ghi lý do trước khi "+VERB_ING[d]+".");return;}
    localStorage.setItem(ME_KEY,by);
    const all=$$(".vb",drawer); all.forEach(x=>{x.disabled=true;});
    $("#gnote").textContent="Đang gửi quyết định…";
    try{
      await api("/api/gate/decide",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({subject_id:g.id,xuong:g.xuong,decision:d,by:by,reason:reason})});
      shut(); toast(VERB[d]+" "+g.id+".");
      await load();
    }catch(err){
      all.forEach(x=>{x.disabled=false;}); sync();
      $("#gnote").textContent="Không ghi được quyết định: "+err.message;
      toast("Không ghi được quyết định.");
    }
  });
}

export function openTicket(id){
  const t=(st().tickets||[]).find(x=>x.id===id); if(!t) return;
  openId=id; writeHash(view,"ticket",id,false);
  const pr=(st().prs||[]).find(p=>p.id===id), rv=(st().reviews||[]).filter(r=>r.id===id);
  const pct=t.bud?Math.round((t.out||0)/t.bud*100):0;
  show(`<div class="dr-h"><div><div class="id">${esc(t.id)}</div><h2>${esc(t.t)}</h2></div><button class="x" aria-label="Đóng">✕</button></div>
    <div class="dr-b">
      <dl class="dl"><dt>trạng thái</dt><dd>${esc(t.st)}${t.gate?` · <span class="tag warn">gate ${esc(t.gate)} chờ</span>`:""}</dd>
        <dt>nhánh tích hợp</dt><dd>${t.integrated?`<span class="tag ok">integration ✓</span> ${esc(t.sha||"")}`:'<span class="tag">chưa có merge commit</span>'}</dd>
        <dt>commit vượt integration</dt><dd>${t.ahead==null?'<span class="note">không đo được (dự án chạy không repo, hoặc ticket đã xong)</span>':t.ahead?`<span class="tag warn">${num(t.ahead)} commit chưa gộp</span>`:'<span class="tag ok">0 — đã gộp hết</span>'}</dd>
        ${t.pending_decision?`<dt>quyết định chờ áp</dt><dd><span class="tag warn">${esc(t.pending_decision.decision)} bởi ${esc(t.pending_decision.by)} · ${num(t.pending_decision.minutes)} phút trước, orchestrator chưa xử lý</span></dd>`:""}
        <dt>assignee</dt><dd>${esc(t.who)}</dd><dt>retry</dt><dd>${num(t.retry)}</dd>
        <dt>estimate</dt><dd>${num(t.est)}</dd><dt>budget (đầu ra)</dt><dd>${num(t.bud)}</dd>
        <dt>đầu ra đã dùng</dt><dd>${num(t.out)} · ${pct}%</dd><dt>tổng token</dt><dd>${num(t.used)} (input + output, mọi lượt)</dd></dl>
      ${(t.human_hint||t.hint)?`<div><div class="eyebrow" style="margin-bottom:6px">Hint agent đang cầm</div>
        ${t.human_hint?`<div class="check"><span><span class="n">người</span><span class="d">${esc(t.human_hint)}</span></span></div>`:""}
        ${t.hint&&t.hint!==t.human_hint?`<div class="check"><span><span class="n">máy</span><span class="d">${esc(t.hint)}</span></span></div>`:""}</div>`:""}
      <div><div class="eyebrow" style="margin-bottom:8px">Pull request</div>
        ${pr?`<dl class="dl"><dt>nhánh</dt><dd>${esc(pr.br)}</dd><dt>lint</dt><dd>${esc(pr.lint)}</dd><dt>tests</dt><dd>${esc(pr.tests)}</dd><dt>verified_by</dt><dd>${esc(pr.v)}</dd></dl>
        <p class="note" style="margin:8px 0 0">${esc(pr.s)}</p>`:'<div class="empty">Chưa có PR — ticket chưa chạy xong lượt đầu.</div>'}</div>
      <div><div class="eyebrow" style="margin-bottom:8px">Review</div>
        ${rv.length?rv.map(r=>`<div class="check"><span><span class="n">${esc(r.src)} · ${esc(r.v)} <span style="color:var(--ink-muted);font-weight:400">${esc(r.at||"")}</span></span><span class="d">${esc(r.f)}</span>${(r.trim_src||[]).length?`<span class="d" style="color:var(--warn-ink)">bằng chứng bị cắt: ${(r.trim_src||[]).map(x=>esc(x.src)+" −"+num(x.chars)+" ký tự").join(", ")}</span>`:""}</span></div>`).join(""):'<div class="empty">Chưa có review.</div>'}</div>
    </div>`);
}
/* `truth` mở ngăn kéo từ bảng phễu; xem ghi chú setQ ở util.js. */
export function setOpenId(v){ openId=v; }
