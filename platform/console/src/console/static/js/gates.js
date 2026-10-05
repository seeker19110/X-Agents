/* gates.js — tách từ index.html ở K7.1 (kịch bản B). Không build step, không CDN.
    */
import {openGate} from "./drawer.js";
import {S, SC, srcOk, srcWhy, st} from "./state.js";
import {filter} from "./tiles.js";
import {$, $$, Q, esc, hay, hl} from "./util.js";

/* ---------- hàng đợi gate ---------- */
export const KIND={plan:"kế hoạch",publish:"đăng",escalation:"leo thang",acceptance:"nghiệm thu",replies:"trả lời",spec:"đặc tả",release:"phát hành",patch:"bản vá",clarification:"câu hỏi làm rõ"};
export function renderQueue(){
  const all=st().gates||[], q=$("#queue");
  const gates=all.filter(g=>hay(g.id,g.title,g.xuong,g.by,KIND[g.kind]||g.kind));
  const dead=[SC].filter(k=>!srcOk(k));
  if(!gates.length&&Q&&all.length){
    q.innerHTML=`<div class="empty"><b>Không có gate nào khớp “${esc($("#q").value.trim())}”</b>${all.length} gate đang chờ, xoá ô tìm để xem hết.</div>`;
    $("#nav-gates").textContent=all.length; $("#chip-gates").textContent=all.length;
    return;
  }
  if(!gates.length){
    q.innerHTML=dead.length
      ? `<div class="empty"><b>Chưa đọc được xưởng nào</b>${esc(dead.map(k=>k+": "+srcWhy(k)).join(" · "))}</div>`
      : `<div class="empty"><b>Sạch hàng đợi</b>Không có gì chờ bạn duyệt.</div>`;
  }else q.innerHTML=gates.map(g=>{
    const h=Number(g.hours||0);
    const flag=g.reviewer_signed?'<span class="pill ok">reviewer đã ký, cờ tắt</span>':h>=24?'<span class="pill crit">quá hạn</span>':h>=12?'<span class="pill warn">sắp quá hạn</span>':'<span class="pill calm">còn hạn</span>';
    return `<button class="gate" data-id="${esc(g.id)}" data-sev="${esc(g.sev||"calm")}" data-kind="${esc(g.kind)}">
      <span class="stripe"></span>
      <span class="body">
        <span class="id">${hl(g.id)} <span class="tag ${g.kind==="release"?"ok":g.kind==="escalation"?"warn":""}">gate ${esc(KIND[g.kind]||g.kind)}</span></span>
        <h3>${hl(g.title)}</h3>
        ${g.effect?`<span class="effect"><b>Duyệt thì sao?</b> ${esc(g.effect)}${g.agent?` Chạy lại ngay sau đó: <code>${esc(g.agent)}</code>.`:""}</span>`:""}
        ${g.reject?`<span class="effect"><b>Từ chối thì sao?</b> ${esc(g.reject)}</span>`:""}
        <span class="meta"><span>${esc(g.xuong)}</span><span>tạo bởi <code>${esc(g.by)}</code></span></span>
        <span class="cl">${(g.cl||[]).map(c=>`<code>${esc(c[0])}</code>`).join("")}</span>
      </span>
      <span class="side">${flag}<span class="age">${h} giờ</span></span>
    </button>`;}).join("");
  $("#nav-gates").textContent=all.length; $("#chip-gates").textContent=all.length;
  $$(".nav")[0].querySelector(".dot").style.display=all.length?"":"none";
}
$("#queue").addEventListener("click",e=>{const b=e.target.closest(".gate"); if(b) openGate(b.dataset.id);});
