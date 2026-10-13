/* flow.js — ô "Luồng công việc" ở đầu màn Trực ban.

   Câu hỏi ô này trả lời: *việc đang dồn ở bậc nào, và chỗ nào đang chờ chính tôi?* Một dải ngang bảy bậc của phễu
   sản phẩm (yêu cầu → … → nghiệm thu), mỗi bậc là TỔNG của mọi sản phẩm, và giữa hai bậc là điểm dừng chờ người
   (gate) chặn bậc sau. Gate đang chờ thì điểm dừng tô vàng (đỏ nếu đã quá 24 giờ) kèm số; bấm là mở gate chờ lâu nhất.

   Không tự tính gì mới: bậc và `empty` lấy từ `product_funnel` (truth.py, ADR-0003 — bậc rỗng là XÁM, không bao giờ
   xanh), gate lấy từ `gates`. Hai bảng dưới phải khớp hợp đồng Python — `tests/test_luong_cong_viec.py` canh. */
import {openGate} from "./drawer.js";
import {KIND} from "./gates.js";
import {SC, emptyBox, listOf, srcOk, st} from "./state.js";
import {$, esc, num} from "./util.js";

/* [bậc trong PRODUCT_STAGES, nhãn ngắn, id phần tử để cuộn tới khi bấm] */
export const STAGES=[["request","Yêu cầu","v-phieu"],["spec","Đặc tả","v-phieu"],["ticket","Ticket","board-tickets"],
  ["rc","Release-candidate","releases"],["staging","Staging","releases"],["production","Production","releases"],
  ["acceptance","Nghiệm thu","v-phieu"]];
/* loại gate → bậc mà nó chặn (gate đứng ngay TRƯỚC bậc đó). `escalation` mở ở bậc bất kỳ nên có ô riêng. */
export const GATE_AT={clarification:"spec",spec:"spec",release:"production",acceptance:"acceptance"};

export function stageTotals(){
  const rows=st().product_funnel||[];
  return STAGES.map(([k,label,go])=>{
    const cells=rows.map(p=>(p.stages||[]).find(s=>s.stage===k)).filter(Boolean);
    const smoke=v=>cells.filter(s=>s.smoke===v).length;
    return {k,label,go,n:cells.reduce((a,s)=>a+Number(s.n||0),0),empty:cells.every(s=>s.empty),
      fail:smoke("fail"),unverified:smoke("unverified"),ok:smoke("ok")};
  });
}

const sgates=()=>listOf(SC,st().gates).filter(g=>g.xuong===SC);
const oldest=list=>list.slice().sort((a,b)=>Number(b.hours||0)-Number(a.hours||0))[0];
const late=list=>list.some(g=>Number(g.hours||0)>=24);

function ticketSub(){
  const tk=listOf(SC,st().tickets), by=sts=>tk.filter(t=>sts.includes(t.st)).length;
  return `${num(by(["dispatched","in_progress","changes_requested"]))} đang làm · ${num(by(["in_review"]))} review`
    +(by(["blocked","escalated"])?` · <b>${num(by(["blocked","escalated"]))} kẹt</b>`:"");
}

function node(s){
  const sub=s.empty?"chưa có gì":s.k==="ticket"?ticketSub()
    :s.fail?`${num(s.fail)} smoke THẤT BẠI`:s.unverified?`${num(s.unverified)} smoke chưa kiểm`:s.ok?"smoke ✓":"&nbsp;";
  const cls=s.empty?"zero":s.fail?"bad":"has";
  return `<button class="node ${cls}" data-go="${esc(s.go)}" title="${esc(s.label)}: ${num(s.n)} — bấm để xem chi tiết">
    <span class="lbl">${esc(s.label)}</span><span class="n">${num(s.n)}</span><span class="sm">${sub}</span></button>`;
}

function stop(stage,gates){
  const kinds=Object.keys(GATE_AT).filter(k=>GATE_AT[k]===stage);
  if(!kinds.length) return '<span class="link" aria-hidden="true"></span>';
  const name=KIND[kinds.find(k=>k!=="clarification")]||kinds[0];
  const w=gates.filter(g=>kinds.includes(g.kind));
  if(!w.length) return `<span class="link"><span class="stop" title="điểm dừng chờ người: gate ${esc(name)} — không có gì đang chờ">${esc(name)}</span></span>`;
  const top=oldest(w);
  return `<span class="link"><button class="gw on${late(w)?" over":""}" data-gate="${esc(top.id)}"
    title="${num(w.length)} gate ${esc(name)} chờ bạn — bấm mở gate chờ lâu nhất (${esc(top.id)}, ${num(top.hours)} giờ)">${num(w.length)} chờ</button></span>`;
}

export function renderFlow(){
  const host=$("#flow"); if(!host) return;
  if(!srcOk(SC)){host.innerHTML=emptyBox(SC,"Chưa đọc được xưởng phần mềm");return;}
  const gates=sgates(), esc8=gates.filter(g=>g.kind==="escalation");
  host.innerHTML=`<div class="flow">${stageTotals().map((s,i)=>(i?stop(s.k,gates):"")+node(s)).join("")}</div>
    <div class="flow-foot">
      ${esc8.length?`<button class="gw on${late(esc8)?" over":""}" data-gate="${esc(oldest(esc8).id)}">${num(esc8.length)} gate leo thang chờ bạn</button>`
        :'<span class="gw">không có gate leo thang</span>'}
      <span>◆ điểm dừng chờ người — vàng: đang có gate chờ bạn, đỏ: chờ quá 24 giờ. Bậc gạch đứt: chưa có gì, không phải “ổn”.</span>
    </div>`;
}

$("#flow").addEventListener("click",e=>{
  const g=e.target.closest("[data-gate]"); if(g){ openGate(g.dataset.gate); return; }
  const n=e.target.closest("[data-go]"); if(!n) return;
  const el=document.getElementById(n.dataset.go);
  if(el) (el.closest(".sect")||el).scrollIntoView({behavior:"smooth",block:"start"});
});
