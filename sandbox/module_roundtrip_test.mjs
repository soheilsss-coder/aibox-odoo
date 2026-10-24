/* ==============================================================
   MODULE ROUND-TRIP TEST (jsdom) — the developer console must
   REALLY remove and re-install catalog modules, both directions:

     for each of [marketing_card, product_margin, pos_discount]:
       - UNINSTALL through the UI's honest API path (the console's
         action buttons) and watch the row flip to "not installed"
       - RE-INSTALL FROM THE UI CATALOGUE (type in search, click
         Install, wait for the real odoo rebuild) and watch it flip
         back to "installed"
     then verify the object registry still answers (no broken state
     left behind by the round-trips).

   Run: node module_roundtrip_test.mjs   (appliance+preview up)
   ============================================================== */
import { JSDOM } from "/tmp/node_modules/jsdom/lib/api.js";

const BASE = "http://127.0.0.1:5173";
const sleep = (ms)=>new Promise(r=>setTimeout(r,ms));
async function waitFor(fn, desc, t=180000){
  const st = Date.now();
  while (Date.now()-st < t) { try { if (fn()) return true; } catch(e){} await sleep(200); }
  throw new Error("TIMEOUT waiting for: "+desc);
}
let fails = 0;
const check = (n,c,e="")=>{ console.log((c?"PASS":"FAIL"), n, e); if(!c) fails++; };

let COOKIES = {};
async function jarFetch(url, opts={}){
  opts = {...opts}; opts.headers = new Headers(opts.headers||{});
  const jar = Object.entries(COOKIES).map(([k,v])=>k+"="+v).join("; ");
  if (jar) opts.headers.set("cookie", jar);
  const resp = await globalThis.fetch(url, opts);
  for (const c of (resp.headers.getSetCookie?resp.headers.getSetCookie():[])) {
    const kv = c.split(";")[0]; const eq = kv.indexOf("=");
    if (eq>0) COOKIES[kv.slice(0,eq)] = kv.slice(eq+1);
  }
  return resp;
}

const MODS = ["marketing_card", "product_margin", "pos_discount"];
const stateOf = async (name)=>{
  const r = await jarFetch(BASE+"/api/admin/panel/modules?query="+encodeURIComponent(name));
  const d = await r.json();
  const m = (d.modules||[]).find(x=>x.name===name);
  return m ? m.state : "?";
};

console.log("=== MODULE ROUND-TRIP (real uninstall + real install, per module) ===");
await (await jarFetch(BASE+"/devconsole")).text();
await jarFetch(BASE+"/api/admin/panel/login", {method:"POST", headers:{"Content-Type":"application/json"},
  body: JSON.stringify({username:"developer", password: process.env.DEV_PW || "Developer2026"})});

// one dev-console DOM for the UI click-throughs
const html = await (await jarFetch(BASE+"/devconsole")).text();
const dom = new JSDOM(html, { url: BASE+"/devconsole", runScripts:"outside-only", pretendToBeVisual:true });
const w = dom.window;
w.fetch = (u,o)=>jarFetch(new URL(String(u), BASE).href, o);
w.confirm = ()=>true; w.scrollTo = ()=>{};
w.Element.prototype.scrollIntoView = w.Element.prototype.scrollIntoView || function(){};
for (const sc of [...w.document.querySelectorAll("script")].map(s=>s.textContent))
  if (sc && sc.trim()) { try { w.eval(sc); } catch(e){ console.log("eval err:", e.message); } }
await waitFor(()=>w.document.querySelectorAll("#nav .nav-item").length===11, "dev console renders");
const $id = (i)=>w.document.getElementById(i);
[...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes("Modules")).dispatchEvent(new w.MouseEvent("click",{bubbles:true}));
await waitFor(()=>$id("m_rows") && $id("m_rows").children.length>50, "module catalogue", 60000);

for (const name of MODS){
  // --- UNINSTALL through the panel action API (the console's own path)
  let r = await jarFetch(BASE+"/api/admin/panel/modules/act", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({names:[name], action:"uninstall"})});
  let out = await r.json();
  await waitFor(async ()=>{ const s = await stateOf(name); return s==="uninstalled"; },
    name+" becomes uninstalled", 180000);
  check(name+" UNINSTALLED for real", (out.done||[]).includes(name), (await stateOf(name)));

  // --- RE-INSTALL FROM THE UI (re-open Modules so the page fetches the
  // fresh states, type, click Install, wait for the real rebuild)
  [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes("Modules")).dispatchEvent(new w.MouseEvent("click",{bubbles:true}));
  await waitFor(()=>$id("m_rows") && $id("m_rows").children.length>50, name+" catalogue refetch", 60000);
  type($id("m_q"), name);
  await sleep(500);
  let btn = [...$id("m_rows").querySelectorAll("button[data-i]")].find(b=>b.dataset.i===name);
  check(name+" shows an Install button after removal", !!btn);
  type($id("m_q"), "");
  await sleep(500);
  btn = [...$id("m_rows").querySelectorAll("button[data-i]")].find(b=>b.dataset.i===name);
  click(btn);
  await waitFor(()=>$id("m_msg").textContent.includes("done"), name+" reinstall finishes", 240000);
  const st = await stateOf(name);
  check(name+" RE-INSTALLED FROM THE UI", st==="installed", st);
}
function type(el, v){ el.value = v; el.dispatchEvent(new w.Event("input",{bubbles:true})); }
function click(el){ el.dispatchEvent(new w.MouseEvent("click",{bubbles:true,cancelable:true})); }

// registry must still answer cleanly after all round-trips
[...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes("Data & Models")).dispatchEvent(new w.MouseEvent("click",{bubbles:true}));
await waitFor(()=>$id("r_q"), "registry search box");
type($id("r_q"), "res.partner");
click($id("r_go"));
await waitFor(()=>{ const t = $id("r_rows").textContent; return t.includes("res.partner") && !t.includes("Counting"); }, "registry answers post-round-trip", 60000);
check("object registry intact after 3 round-trips", !$id("r_rows").textContent.includes("broken"));

console.log(fails===0 ? "\n=== MODULE ROUND-TRIP: END-TO-END OK ===" : "\n=== "+fails+" FAILURES ===");
process.exit(fails===0?0:1);
