/* truth.js — tách từ index.html ở K7.1 (kịch bản B). Không build step, không CDN.
    */
import {setOpenId, show} from "./drawer.js";
import {view, writeHash} from "./router.js";
import {S, SC, emptyBox, emptyRow, listOf, source, srcOk, st} from "./state.js";
import {filter} from "./tiles.js";
import {$, Q, esc, hay, hl, num, sortRows} from "./util.js";

/* ---------- sự thật giao hàng ---------- */
export const TONE={void:"void",rc:"wait",staging_failed:"bad",staging_pending_human:"bad",staging_deployed:"wait",qa_failed:"bad",gate3_missing:"bad",
  gate3:"wait",gate3_approved:"wait",production_failed:"bad",production_pending_human:"bad",production:"done",delivered:"done",
  /* ADR-0039: deploy hỏng = container không chạy được. Cũng đỏ, nhưng là bậc riêng — ticket không bị trả về làm lại. */
  staging_deploy_failed:"bad",production_deploy_failed:"bad"};
/* C1 — phễu SẢN PHẨM. Quy tắc duy nhất đáng nhớ: n===0 thì ô XÁM. Cả trang đêm 05/09 xanh trong khi
   0 release ra production, vì "không có gì" và "không có vấn đề" được vẽ giống hệt nhau. */
export const PF_SMOKE={ok:"smoke ✓ máy chạy thật",fail:"smoke THẤT BẠI",unverified:"smoke KHÔNG kiểm được"};
export function renderProductFunnel(){
  const host=$("#product-funnel"); if(!host) return;
  const list=srcOk(SC)?(st().product_funnel||[]):null;
  $("#nav-phieu").textContent=list?list.length:"—";
  if(!list){host.innerHTML=emptyBox(SC,"Chưa đọc được xưởng phần mềm");return;}
  if(!list.length){host.innerHTML='<div class="empty"><b>Chưa có sản phẩm nào</b>Bus chưa có yêu cầu, spec hay ticket nào — không có phễu để vẽ.</div>';return;}
  host.innerHTML=list.filter(p=>hay(p.project_id)).map(p=>`<div class="prod">
    <h3>${hl(p.project_id)} ${p.delivered?'<span class="tag ok">đã giao và đã nghiệm thu</span>':'<span class="tag warn">chưa nghiệm thu xong</span>'}</h3>
    <div class="steps">${p.stages.map(x=>{
      const cls=x.empty?"zero":"has"+(x.smoke==="fail"?" smoke-fail":x.smoke==="unverified"?" smoke-unverified":"");
      return `<div class="step ${cls}"><span class="lbl">${esc(x.label)}</span><span class="n">${num(x.n)}</span>
        <span class="sm">${x.empty?"chưa có gì":x.smoke?esc(PF_SMOKE[x.smoke]||x.smoke):"&nbsp;"}</span></div>`;}).join("")}</div>
  </div>`).join("")||'<div class="empty"><b>Không sản phẩm nào khớp ô tìm</b>Xoá ô tìm để xem hết.</div>';
}

/* C4 — bế tắc IM LẶNG của ticket: kẹt mà KHÔNG gate nào chờ, tức là không ai được hỏi. Tách khỏi bảng bế tắc
   chung và đặt ở đầu trang, vì đây là loại duy nhất sẽ không bao giờ tự kêu. */
export function renderSilent(){
  const list=listOf(SC,st().silent_deadlocks), host=$("#silent");
  $("#s-silent").hidden=!list.length;
  if(!list.length){host.innerHTML="";return;}
  host.innerHTML=`<h2>⛔ ${num(list.length)} ticket kẹt mà KHÔNG gate nào chờ — không ai được hỏi</h2>`
    +list.map(d=>`<div class="row"><code>${esc(d.id)} · ${esc(d.state)}</code>
      <span>${esc(d.why)} Việc của bạn: mở gate escalation cho ticket này, hoặc gỡ nguyên nhân rồi giao lại.
      ${d.integrated?'<span class="tag ok">code đã ở integration</span>':""}</span></div>`).join("");
}

/* K2.7/S1 — chế độ đã khai và bằng chứng chạy mã khách. Subprocess tường minh luôn cần cảnh báo gate. */
export function renderSandbox(){
  const sb=st().sandbox, host=$("#sandbox"), sect=$("#s-sandbox");
  const co=(source(SC)||{}).sandbox_available===true;
  if(!sb||!(sb.mode==="subprocess"||sb.unsandboxed)){sect.hidden=true;host.innerHTML="";return;}
  sect.hidden=false;
  const names=Object.entries(sb.by_name||{}).map(([k,v])=>`${esc(k)} ×${num(v)}`).join(" · ");
  host.innerHTML=`<h2>⚠ sandbox=${esc(sb.mode||"chưa ghi nhận")} · ${num(sb.unsandboxed)}/${num(sb.runs)} lượt chạy mã khách trong ${num(sb.window_h)}h qua KHÔNG trong container</h2>
    <div class="row"><code>sandbox=subprocess</code>
    <span>Gate không chống được mã khách khi chạy subprocess: lệnh của repo khách có quyền người vận hành và thấy
    <code>HOME</code> (<code>~/.ssh</code>, <code>~/.claude</code>). ${co?"Máy này có container runtime.":"Cần cài Docker hoặc Podman."} Việc của bạn: đặt
    <code>COMPANY_SANDBOX=container</code> (hoặc <code>sandbox: container</code> trong <code>llm.yaml</code>) rồi
    khởi động lại orchestrator. Đã dùng: ${names}.${sb.last_at?" Lượt gần nhất: "+esc(sb.last_at)+".":""}</span></div>`;
}

export function renderDeadlocks(){
  const dl=listOf(SC,st().deadlocks), host=$("#deadlocks");
  $("#s-dead").hidden=!dl.length;
  if(!dl.length){host.innerHTML="";return;}
  // Gộp theo (loại, trạng thái, lý do): 10 RC cùng kẹt một kiểu là MỘT dòng kèm danh sách id, không phải 10 dòng giống nhau.
  const groups=new Map();
  dl.forEach(d=>{const k=d.kind+"|"+d.state+"|"+d.why; if(!groups.has(k)) groups.set(k,{...d,ids:[]}); groups.get(k).ids.push(d.id);});
  const label={ticket:"ticket",release:"release",idle:""};
  host.innerHTML=`<h2>Bế tắc im lặng — ${dl.length} chỗ không ai được hỏi</h2>`+[...groups.values()].map(g=>`<div class="row">
    <code>${g.kind==="idle"?"cả dự án":num(g.ids.length)+" "+label[g.kind]+(g.state?" · "+esc(g.state):"")}</code>
    <span>${esc(g.why)}${g.integrated?' <span class="tag ok">code đã ở integration</span>':""}
      ${g.kind!=="idle"?`<div class="ids" style="font-family:var(--mono);font-size:11px;color:var(--crit-ink);opacity:.85;margin-top:2px">${g.ids.map(esc).join(" · ")}</div>`:""}</span></div>`).join("");
}
export function renderDelivery(){
  const d=srcOk(SC)?st().delivery:null, host=$("#delivery");
  if(!d){host.innerHTML=emptyBox(SC,"Chưa đọc được xưởng phần mềm");return;}
  const funnel=(d.funnel||[]).filter(f=>f.n||f.stage!=="void");
  const max=Math.max(1,...funnel.map(f=>f.n));
  host.innerHTML=`<div>
      <div class="k">Đã giao (tag + push)</div>
      <div class="big">${num(d.delivered)}<small> / ${num(d.releases_live)} release</small></div>
      <dl class="facts">
        <dt>lên production</dt><dd>${num(d.production)}</dd>
        <dt>tag mới nhất</dt><dd>${d.latest_tag?esc(d.latest_tag)+(d.latest_release?" · "+esc(d.latest_release):""):"chưa có"}</dd>
        <dt>nhánh tích hợp</dt><dd>${d.integration_sha?esc(d.integration_sha)+" · "+num(d.integrated_tickets)+" ticket đã gộp":"chưa có merge commit"}</dd>
        <dt>RC bị huỷ</dt><dd>${num(d.void)} / ${num(d.releases_total)}</dd>
      </dl></div>
    <div><div class="k" style="margin-bottom:8px">Phễu release — RC đang đứng ở bậc nào</div><div class="funnel">${funnel.map(f=>`
      <div class="frow${f.n?"":" zero"}" data-tone="${TONE[f.stage]||""}"><span class="lbl">${esc(f.label)}</span>
        <span class="bar"><i style="width:${Math.round(f.n/max*100)}%"></i></span><span class="n">${num(f.n)}</span>
        ${f.n&&f.ids.length<=8?`<span class="ids">${f.ids.map(esc).join(" · ")}</span>`:""}</div>`).join("")}</div></div>`;
}
/* ADR-0021 §f (N3): journal `quality:accept` là nguồn RIÊNG của nó (cạnh bus) — hiện độc lập với `srcOk(SC)`.
   `state().quality` null = chưa ai ký profile nào (chưa có file journal), KHÔNG PHẢI xưởng đọc hỏng. */
export function renderQuality(){
  const list=st().quality, host=$("#quality"); if(!host) return;
  if(list==null){host.innerHTML='<div class="empty"><b>Không có profile</b>Chưa ai ký quality profile cho dự án nào — chưa có hợp đồng chất lượng để chấm.</div>';return;}
  if(!list.length){host.innerHTML='<div class="empty"><b>Không có run nào</b>Journal đã có nhưng chưa run nào được đăng ký.</div>';return;}
  host.innerHTML=list.map(r=>{
    const tone=r.status==="succeeded"?"ok":r.status==="failed"?"bad":"warn";
    const total=r.checks_total||[], passed=new Set(r.checks_passed||[]);
    return `<div class="row"><code>${esc(r.run_id)} · <span class="tag ${tone}">${esc(r.status)}</span></code>
      <span>${total.map(c=>`<span class="tag ${passed.has(c)?"ok":"bad"}">${esc(c)}${passed.has(c)?" ✓":" ✗"}</span>`).join(" ")}
      ${r.blocker?`<div class="note" style="margin-top:4px;color:var(--crit-ink)">chặn: ${esc(r.blocker)}</div>`:""}</span></div>`;
  }).join("");
}
export function renderRunning(){
  const r=srcOk(SC)?st().running:null, pend=listOf(SC,st().pending_decisions), host=$("#running");
  if(!r){host.innerHTML=emptyBox(SC,"Chưa đọc được xưởng phần mềm");return;}
  // C3: "việc đang chạy" là đầu hàng đợi — orchestrator xử lý tuần tự, nên đầu hàng đợi CHÍNH LÀ việc đang chạy,
  // và tuổi của nó là thời gian lượt hiện tại đã chạy. Nói thẳng ra thay vì để người suy từ chữ "hàng đợi".
  const head=r.head?`<code>${esc(r.head.topic)}</code> ${esc(r.head.key)} · đang chạy ${num(r.head.minutes)} phút`:"không có gì trong hàng đợi";
  const stale=r.last_event_minutes!=null&&r.last_event_minutes>15&&r.queue>0;
  host.innerHTML=`<div><span class="k">Việc đang chạy · hàng đợi orchestrator</span><span class="v">${num(r.queue)} event</span>
      <span>${head}</span>${r.topics.length?`<span class="note">${r.topics.map(esc).join(", ")}</span>`:""}</div>
    <div><span class="k">Bản ghi audit cuối</span><span class="v">${r.last_event_minutes==null?"—":num(r.last_event_minutes)+" phút trước"}</span>
      <span class="note">${stale?'<span class="tag bad">hàng đợi có việc mà '+num(r.last_event_minutes)+' phút không có bản ghi — orchestrator có đang chạy không?</span>':r.queue?"đang có lượt model chạy":"rảnh"}</span></div>
    <div><span class="k">Quyết định đã ký, máy chưa áp</span><span class="v">${num(pend.length)}</span>
      ${pend.length?pend.map(p=>`<span class="pd"><code>${esc(p.id)}</code><span>${esc(p.decision)} · ${esc(p.by)} · ${num(p.minutes)} phút trước${p.kind?" · gate "+esc(p.kind):""}</span></span>`).join("")
        :'<span class="note">mọi quyết định đã được áp dụng</span>'}
      ${pend.length?'<span class="note">orchestrator chỉ đọc quyết định giữa các lượt model; lượt engineering có thể kéo dài 10 phút</span>':""}</div>`;
}
export function renderReleases(){
  const d=srcOk(SC)?st().delivery:null;
  const rows=sortRows("releases",((d&&d.releases)||[]).filter(r=>hay(r.id,r.version,r.label,r.next,(r.tickets||[]).join(" "))).slice().reverse());
  $("#releases").innerHTML=rows.length?rows.map(r=>`<tr class="tr-click" data-r="${esc(r.id)}"><td class="mono">${hl(r.id)}</td><td class="mono">${esc(r.version||"")}</td>
    <td><span class="tag ${TONE[r.stage]==="done"?"ok":TONE[r.stage]==="bad"?"bad":TONE[r.stage]==="wait"?"warn":""}">${esc(r.label)}</span>${r.gate?` <span class="tag warn">gate ${esc(r.gate)} chờ</span>`:""}</td>
    <td class="mono">${(r.tickets||[]).map(esc).join(", ")}</td><td>${esc(r.next)}</td><td class="mono">${esc(r.at||"")}</td></tr>`).join("")
    :emptyRow(6,SC,!srcOk(SC)?"Chưa có dữ liệu xưởng phần mềm":Q?"Không có release nào khớp ô tìm":"Chưa có release-candidate nào");
}
$("#releases").addEventListener("click",e=>{const r=e.target.closest("tr");if(r&&r.dataset.r)openRelease(r.dataset.r);});
export function openRelease(id){
  const d=st().delivery, r=d&&(d.releases||[]).find(x=>x.id===id); if(!r) return;
  setOpenId(id); writeHash(view,"release",id,false);
  show(`<div class="dr-h"><div><div class="id">${esc(r.id)}</div><h2>${esc(r.label)}${r.version?" · v"+esc(r.version):""}</h2></div><button class="x" aria-label="Đóng">✕</button></div>
    <div class="dr-b">
      <dl class="dl"><dt>bậc</dt><dd>${esc(r.stage)}</dd><dt>ticket</dt><dd>${(r.tickets||[]).map(esc).join(", ")}</dd>
        <dt>sha staging</dt><dd>${esc(r.sha||"—")}</dd><dt>gate chờ</dt><dd>${esc(r.gate||"không")}</dd><dt>lúc</dt><dd>${esc(r.at||"—")}</dd></dl>
      <div><div class="eyebrow" style="margin-bottom:6px">Việc kế tiếp</div><div style="font-size:13px">${esc(r.next||"—")}</div></div>
      ${r.summary?`<div><div class="eyebrow" style="margin-bottom:6px">Release-engineer nói gì lần cuối</div><div class="note" style="white-space:pre-wrap;color:var(--ink-2)">${esc(r.summary)}</div></div>`:""}
      ${r.runbook?`<div><div class="eyebrow" style="margin-bottom:6px">Runbook</div><code style="font-family:var(--mono);font-size:12px">${esc(r.runbook)}</code></div>`:""}
    </div>`);
}
