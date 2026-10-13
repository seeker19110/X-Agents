/* router.js — tách từ index.html ở K7.1 (kịch bản B). Không build step, không CDN.
    */
import {openGate, openId, openTicket, shut} from "./drawer.js";
import {CFG, loadSettings} from "./settings.js";
import {KP, SC, drawerOpen, listOf, srcOk, srcWhy, st} from "./state.js";
import {renderGuide, renderSubmit} from "./submit.js";
import {filter} from "./tiles.js";
import {openRelease, renderProductFunnel} from "./truth.js";
import {$, $$, num, vnd} from "./util.js";

/* ---------- điều hướng ---------- */
export const TITLES={
 "truc-ban":()=>["Trực ban",`${st().gates.length||0} việc chờ duyệt`
   +(st().delivery?` · đã giao ${num(st().delivery.delivered)}/${num(st().delivery.releases_live)} release`:"")+` · hàng đợi còn ${num(st().tiles.queue)} event`],
 "phieu":()=>["Phễu sản phẩm",srcOk(SC)?(st().product_funnel||[]).length?`${(st().product_funnel||[]).length} sản phẩm · ô xám là ô CHƯA CÓ GÌ, không phải ô tốt`:"chưa có sản phẩm nào trên bus":srcWhy(SC)],
 "phan-mem":()=>["Xưởng phần mềm",srcOk(SC)?`${listOf(SC,st().tickets).length} ticket, ${listOf(SC,st().tickets).filter(t=>t.st==="in_review").length} đang review, ${listOf(SC,st().prs).length} PR đã nộp`:srcWhy(SC)],
 "bao-tri":()=>["Công ty bảo trì",srcOk(KP)?((st().keeper||{}).ran?`${((st().keeper||{}).tickets||[]).length} ticket bảo trì · ${((st().keeper||{}).gates||[]).length} gate chờ`:"chưa chạy lần nào"):srcWhy(KP)],
 "chi-phi":()=>["Chi phí & hạn mức",`${vnd(st().tiles.project_cost_usd)} / ${vnd(st().tiles.project_budget_usd)} USD dự án · ${st().backends.length} gói tài khoản`],
 "nhat-ky":()=>["Nhật ký",`audit-log ${num(st().log.length)} bản ghi · lọc theo hành động`],
 "cai-dat":()=>["Cài đặt model",CFG?(CFG.can_edit?"sửa được — thay đổi ghi thẳng vào llm.yaml, bản cũ để lại .bak":"chỉ xem — chạy lại console với --allow-config để sửa"):"đang đọc cấu hình…"],
 "huong-dan":()=>["Hướng dẫn","cách giao việc, duyệt gate và đọc màn hình — không cần rời trang"]};
export let view="truc-ban";
export function titles(){const [t,s]=TITLES[view]();$("#vt").textContent=t;$("#vs").textContent=s;}

/* ---------- định tuyến ----------
   Địa chỉ mang đúng chỗ đang đứng: `#/phan-mem` là một màn, `#/phan-mem/ticket/SC-12` là màn đó
   với ngăn kéo ticket đang mở. Nhờ vậy F5 không văng về Trực ban, nút Back của trình duyệt đóng
   ngăn kéo thay vì rời trang, và gửi được link tới đúng một gate cho người khác.
   Dùng hash chứ không `history.pushState`: server chỉ phục vụ một đường `/`, đẩy đường dẫn thật
   vào thanh địa chỉ thì F5 sẽ ăn 404. */
export const VIEWS=["truc-ban","phieu","phan-mem","bao-tri","chi-phi","nhat-ky","cai-dat","huong-dan"];
export const OPENERS={gate:id=>openGate(id),ticket:id=>openTicket(id),release:id=>openRelease(id)};
export let routing=false;                                // chặn vòng lặp hash -> mở -> đặt hash

export function readHash(){
  const raw=(location.hash||"").replace("#","");
  const parts=raw.split("/").filter(Boolean).map(decodeURIComponent);
  const v=VIEWS.includes(parts[0])?parts[0]:"truc-ban";
  return {view:v,kind:parts[1]||null,id:parts.slice(2).join("/")||null};
}
export function writeHash(v,kind,id,replace){
  const parts=["#",v]; if(kind&&id) parts.push(kind,encodeURIComponent(id));
  const next=parts.join("/").replace("#/","#/");
  if(location.hash===next) return;
  routing=true;
  if(replace) history.replaceState(null,"",next); else location.hash=next;
  routing=false;
}
export function showView(v){
  view=v;
  $$(".nav").forEach(n=>n.setAttribute("aria-current",String(n.dataset.v===v)));
  // ADR-0011 giai đoạn 5/5: một trang cuộn dài, không còn ẩn/hiện — nav giờ là mục lục, bấm một mục CUỘN
  // tới đúng section thay vì ẩn mọi section khác (`.view` không còn CSS `display:none`/`class="on"`).
  const el=document.getElementById("v-"+v);
  if(el){ spyLock=Date.now()+900; el.scrollIntoView({behavior:"smooth",block:"start"}); }
  titles();
  if(v==="cai-dat") loadSettings();
  if(v==="phan-mem") renderSubmit(v);
  if(v==="huong-dan") renderGuide();
  if(v==="phieu") renderProductFunnel();
}
/* Nav là mục lục của MỘT trang cuộn: cuộn tới màn nào thì mục đó sáng và tiêu đề thanh trên đổi theo — không
   thì tiêu đề ghi "Trực ban" trong khi người đọc đang ở bảng chi phí. Chỉ đổi đánh dấu: không cuộn (vòng lặp
   cuộn), không đổi địa chỉ (mỗi lần cuộn qua một màn thành một mục lịch sử của nút Back). Trong lúc trang đang
   tự cuộn tới mục vừa bấm (`spyLock`) thì bỏ qua các màn nó lướt qua giữa đường. */
let spyLock=0;
export function spy(v){
  if(v===view||Date.now()<spyLock) return;
  view=v;
  $$(".nav").forEach(n=>n.setAttribute("aria-current",String(n.dataset.v===v)));
  titles();
}
const inBand=new Set();
const spyObs=new IntersectionObserver(es=>{
  es.forEach(e=>e.isIntersecting?inBand.add(e.target):inBand.delete(e.target));
  // Dải canh là 40% trên của khung (dưới thanh trên): màn cuối cùng (theo thứ tự trang) đã chạm dải là màn đang đọc.
  const cur=$$("section.view").filter(x=>inBand.has(x)).pop();
  if(cur) spy(cur.id.slice(2));
},{rootMargin:"-80px 0px -60% 0px"});
$$("section.view").forEach(x=>spyObs.observe(x));

export function applyRoute(){
  const r=readHash();
  showView(r.view);
  const opener=r.kind&&OPENERS[r.kind];
  if(opener&&r.id){
    if(openId!==r.id) opener(r.id);
    // Link cũ trỏ tới thứ đã đóng hoặc đã bị xoá: mở không được thì dọn địa chỉ về đúng màn,
    // đừng để thanh địa chỉ nói dối là đang mở một ticket không còn tồn tại.
    if(!drawerOpen) writeHash(r.view,null,null,true);
  }
  else if(drawerOpen) shut();
}
addEventListener("hashchange",()=>{ if(!routing) applyRoute(); });
$("#nav").addEventListener("click",e=>{
  const b=e.target.closest(".nav"); if(!b) return;
  writeHash(b.dataset.v,null,null,false);
  applyRoute();
});
