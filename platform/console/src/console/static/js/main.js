/* main.js — tách từ index.html ở K7.1 (kịch bản B). Không build step, không CDN.
    */
import {READONLY, api} from "./api.js";
import {agentChart, costChart, hideTip} from "./charts.js";
import {renderQueue} from "./gates.js";
import {renderEngine} from "./engine.js";
import {renderFlow} from "./flow.js";
import {renderKeeper} from "./keeper.js";
import {renderLoops} from "./loops.js";
import {renderNotify} from "./notify.js";
import {VIEWS, applyRoute, readHash, showView, titles, view, writeHash} from "./router.js";
import {loadSettings} from "./settings.js";
import {SC, srcOk, st} from "./state.js";
import {connect, freshLabel, load, mode, skeleton} from "./stream.js";
import {renderBackends, renderBoards, renderTables} from "./tables.js";
import {filter, renderStreams, renderTiles} from "./tiles.js";
import {renderDeadlocks, renderDelivery, renderProductFunnel, renderQuality, renderRunning, renderSandbox, renderSilent} from "./truth.js";
import {$, fold, setQ} from "./util.js";
import {renderGuide, renderSubmit} from "./submit.js";
import "./drawer.js";   // chỉ để chạy phần gắn sự kiện ở top-level

/* ---------- vẽ lại toàn trang ---------- */
export function render(){
  const okCount=[SC].filter(srcOk).length;
  $("#brand-sub").textContent=`${okCount}/1 xưởng đọc được · ${st().backends.length} gói tài khoản`
    +(READONLY?" · chỉ đọc":" · duyệt được");
  $("#mode-pill").innerHTML=READONLY?'<span class="pill calm">chỉ đọc</span>':'<span class="pill accent">duyệt được</span>';
  renderSilent(); renderSandbox(); renderFlow(); renderEngine(); renderNotify(); renderDeadlocks(); renderDelivery(); renderQuality(); renderRunning(); renderQueue(); renderKeeper(); renderTiles(); renderLoops(); renderBackends(); renderBoards(); renderTables(); renderProductFunnel(); renderStreams();
  costChart(); agentChart();
  titles(); freshLabel();
}

/* ---------- ô tìm ---------- */
export const qEl=$("#q");
export let qTimer=null;
qEl.addEventListener("input",()=>{
  clearTimeout(qTimer);
  // Gõ tới đâu lọc tới đó, nhưng chờ một nhịp ngắn: vẽ lại cả trang mỗi phím là giật.
  qTimer=setTimeout(()=>{ const v=qEl.value.trim(); setQ(fold(v), v.toLowerCase()); render(); },120);
});
qEl.addEventListener("keydown",e=>{
  if(e.key==="Escape"){ e.stopPropagation(); qEl.value=""; setQ("", ""); qEl.blur(); render(); }
});

/* ---------- phím tắt ---------- */
document.addEventListener("keydown",e=>{
  if(e.ctrlKey||e.metaKey||e.altKey) return;
  const typing=/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement&&document.activeElement.tagName);
  if(e.key==="/"&&!typing){ e.preventDefault(); qEl.focus(); qEl.select(); return; }
  if(typing) return;
  const i=VIEWS.indexOf(view);
  // Bám theo VIEWS thay vì chốt "1"–"6": thêm màn mới là có phím ngay, không lệch âm thầm.
  if(e.key>="1"&&e.key<="9"&&VIEWS[+e.key-1]){ writeHash(VIEWS[+e.key-1],null,null,false); applyRoute(); }
  else if(e.key==="g"&&i>=0){ writeHash("truc-ban",null,null,false); applyRoute(); }
});

/* ---------- cài thành app (PWA) ----------
   Service worker ở đây chỉ để trang cài được thành app; nó KHÔNG cache `/api/*` (dữ liệu sống)
   và KHÔNG cache `/` (HTML mang token phiên, mà token đổi mỗi lần chạy server) — xem sw.js.
   Chỉ đăng ký ở ngữ cảnh an toàn: chạy `--host` ra ngoài loopback bằng `--i-know` thì trình
   duyệt không cho đăng ký, và im lặng bỏ qua là đúng chứ không phải lỗi. */
if("serviceWorker" in navigator && window.isSecureContext){
  addEventListener("load",()=>{navigator.serviceWorker.register("/sw.js").catch(err=>{
    // Không nuốt im: trang vẫn chạy đủ nếu không đăng ký được, nhưng người dùng bấm mãi
    // không thấy nút Cài đặt thì phải có chỗ mà tra. Một số webview nhúng chặn hẳn API này.
    console.warn("Không đăng ký được service worker (trang vẫn chạy bình thường, chỉ là không cài thành app được):",err.message);
  });});
}

/* ---------- khởi động ---------- */
addEventListener("scroll",hideTip,{passive:true});
if(!location.hash) writeHash("truc-ban",null,null,true);
showView(readHash().view);
// ADR-0011 giai đoạn 5/5: mọi section giờ luôn hiện trên một trang cuộn (showView chỉ còn cuộn tới đúng
// mục), nên ba mục trước đây CHỈ vẽ khi điều hướng tới (`phan-mem`/`huong-dan`/`cai-dat`) phải vẽ ngay từ
// đầu — nếu không, người mở console mà không bấm nav sẽ thấy ba mục đó rỗng dù đã cuộn thấy chúng.
renderSubmit("phan-mem");
renderGuide();
loadSettings();
skeleton();
connect();
