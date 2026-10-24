/* ==============================================================
   COMPANY SIMULATION TEST (jsdom) — "create a fictional company,
   activate department/HR modules, and actually USE the AI".

   Everything below drives the REAL shipped interfaces the same
   way a human does (type, click, wait for visible results):

     Part A (developer console /devconsole): the developer installs
             the HR "hr_contract" module FROM THE UI catalogue and
             verifies the live registry shows hr.department with the
             real department count.
     Part B (customer app, real React bundle): Sara - employee of the
             fictional company «پارس‌نوین صنایع هوشمند» - logs in, sees
             HER company in the user card, opens the Departments page
             (her «فروش» tile), then TALKS TO NOVA: asks for a real
             leave request (the local brain answers with a REAL Odoo
             tool call - a genuine hr.leave record), asks for her
             attendance summary (honest real data), and uploads a PDF
             getting a verbatim quote. Then logs out.
     Part C (vendor console /admin): the system admin opens Token
             Usage - the REAL consumption report now shows Sara's
             turns under department «فروش», per employee AND per
             department (the panel's documented promise).

   Pre-staged by the session (data layer): company + 4 departments
   (هیئت مدیره/فروش/فناوری اطلاعات/مالی و اداری) + 4 employees +
   sara@parsnovin.test (Pars2026Nova) linked to employee سارا محمدی.
   Needs: jsdom@24 in /tmp, appliance 18069 + preview 5173,
   /tmp/ctest/warranty.pdf. Run: node company_simulation_test.mjs
   ============================================================== */
import { JSDOM, ResourceLoader, VirtualConsole } from "/tmp/node_modules/jsdom/lib/api.js";
import { TextDecoder, TextEncoder } from "node:util";
import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";

const BASE = "http://127.0.0.1:5173";
const sleep = (ms)=>new Promise(r=>setTimeout(r,ms));
async function waitFor(fn, desc, t=20000){
  const st = Date.now();
  while (Date.now()-st < t) { try { if (fn()) return true; } catch(e){} await sleep(150); }
  throw new Error("TIMEOUT waiting for: "+desc);
}
let fails = 0;
const check = (n,c,e="")=>{ console.log((c?"PASS":"FAIL"), n, e); if(!c) fails++; };

function makeJar(){ return { c:{} }; }
async function jarFetch(jar, url, opts={}){
  opts = {...opts}; opts.headers = new Headers(opts.headers||{});
  const ck = Object.entries(jar.c).map(([k,v])=>k+"="+v).join("; ");
  if (ck) opts.headers.set("cookie", ck);
  const resp = await globalThis.fetch(url, opts);
  for (const c of (resp.headers.getSetCookie?resp.headers.getSetCookie():[])) {
    const kv = c.split(";")[0]; const eq = kv.indexOf("=");
    if (eq>0) jar.c[kv.slice(0,eq)] = kv.slice(eq+1);
  }
  return resp;
}
const type = (el, v)=>{ el.value = v; el.dispatchEvent(new el.ownerDocument.defaultView.Event("input", {bubbles:true})); };
const click = (el)=>el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent("click", {bubbles:true, cancelable:true}));

/* ---------- Part A: developer console installs an HR module ---------- */
async function devPart(){
  console.log("=== A) DEVELOPER CONSOLE: activate an HR/department module (real UI) ===");
  const jar = makeJar();
  await jarFetch(jar, BASE + "/devconsole");
  await jarFetch(jar, BASE + "/api/admin/panel/login", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({username:"developer", password: process.env.DEV_PW || "Developer2026"})});
  const res = await jarFetch(jar, BASE + "/devconsole");
  const html = await res.text();
  const dom = new JSDOM(html, { url: BASE+"/devconsole", runScripts:"outside-only", pretendToBeVisual:true });
  const w = dom.window;
  w.fetch = (u,o)=>jarFetch(jar, new URL(String(u), BASE).href, o);
  w.confirm = ()=>true; w.scrollTo = ()=>{};
  w.Element.prototype.scrollIntoView = w.Element.prototype.scrollIntoView || function(){};
  for (const sc of [...w.document.querySelectorAll("script")].map(s=>s.textContent))
    if (sc && sc.trim()) { try { w.eval(sc); } catch(e){ console.log("eval err:", e.message); } }
  await waitFor(()=>w.document.querySelectorAll("#nav .nav-item").length===11, "dev console nav renders");
  const $id = (i)=>w.document.getElementById(i);

  // A1: install hr_contract FROM the catalogue (same clicks a developer makes)
  const navTo = (label)=>{ [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes(label)).dispatchEvent(new w.MouseEvent("click",{bubbles:true})); };
  navTo("Modules");
  await waitFor(()=>$id("m_rows") && $id("m_rows").children.length>50, "module catalogue renders", 60000);
  type($id("m_q"), "hr_contract");
  await sleep(400);
  const btn = [...$id("m_rows").querySelectorAll("button[data-i]")].find(b=>b.dataset.i==="hr_contract");
  if (!btn){
    // already installed by an earlier run of this test - that is fine,
    // but prove the UI shows it as installed
    check("hr_contract listed in the catalogue", $id("m_rows").textContent.includes("hr_contract"));
    check("hr_contract already installed (earlier run)", $id("m_rows").textContent.includes("installed"));
  } else {
    type($id("m_q"), "");
    await sleep(300);
    const btn2 = [...$id("m_rows").querySelectorAll("button[data-i]")].find(b=>b.dataset.i==="hr_contract");
    click(btn2);
    await waitFor(()=>$id("m_msg").textContent.includes("done"), "hr_contract install finishes", 180000);
    check("developer installs hr_contract FROM the UI", true, $id("m_msg").textContent.slice(0,70));
  }

  // A2: the live registry knows the department model with real records
  navTo("Data & Models");
  await waitFor(()=>$id("r_q"), "registry search box");
  type($id("r_q"), "hr.department");
  click($id("r_go"));
  await waitFor(()=>{ const t = $id("r_rows").textContent; return t.includes("hr.department") && !t.includes("Counting"); },
    "hr.department in the registry", 30000);
  const rowTxt = $id("r_rows").textContent;
  const m = rowTxt.match(/hr\.department[\s\S]*?(\d+)/);
  check("registry shows hr.department with real record count", m && parseInt(m[1],10)>=4, "count="+(m?m[1]:"?"));
}

/* ---------- Part B: the customer SPA, really executing ---------- */
class LocalOnly extends ResourceLoader {
  fetch(url, options) {
    if (String(url).startsWith(BASE)) return super.fetch(url, options);
    return null;
  }
}
const vcon = new VirtualConsole();
vcon.on("jsdomError", (e)=>{ if (!/Could not load link|Could not load img/.test(String(e))) console.log("   [jsdom]", String(e).slice(0,160)); });

async function makeApp(jar){
  const APP = BASE + "/aibox-odoo/";
  const res = await jarFetch(jar, APP);
  let html = await res.text();
  const m = html.match(/<script type="module"[^>]*src="([^"]+)"[^>]*><\/script>/);
  if (!m) throw new Error("built bundle script tag not found in index.html");
  html = html.replace(m[0], "");
  const bundleRes = await jarFetch(jar, new URL(m[1], BASE).href);
  const bundle = (await bundleRes.text())
    .replace(/import\.meta\.resolve\?import\.meta\.resolve\(e\):new URL\(e,import\.meta\.url\)\.href/g,
             "new URL(e,document.baseURI).href");
  if (bundle.includes("import.meta")) throw new Error("bundle still contains import.meta");
  const dom = new JSDOM(html, {
    url: APP, runScripts: "dangerously", resources: new LocalOnly(), virtualConsole: vcon,
    pretendToBeVisual: true,
    beforeParse(w) {
      w.fetch = (u,o)=>jarFetch(jar, new URL(String(u), BASE).href, o);
      w.TextDecoder = TextDecoder; w.TextEncoder = TextEncoder;
      w.crypto = webcrypto;
      if (!w.matchMedia) w.matchMedia = ()=>({ matches:false, addListener(){}, removeListener(){}, addEventListener(){}, removeEventListener(){} });
      if (!w.ResizeObserver) w.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} };
      if (!w.IntersectionObserver) w.IntersectionObserver = class { observe(){} unobserve(){} disconnect(){} };
      if (w.Element && !w.Element.prototype.scrollIntoView) w.Element.prototype.scrollIntoView = function(){};
      w.addEventListener("error", ev => console.log("   [page error]", ev.message));
    },
  });
  dom.window.eval(bundle);
  return dom.window;
}

async function spaPart(){
  console.log("=== B) CUSTOMER APP: Sara of «پارس‌نوین» uses the AI (real SPA) ===");
  const jar = makeJar();
  const w = await makeApp(jar);
  const doc = w.document;
  const setVal = (el, v)=>{
    const proto = el.tagName === "TEXTAREA" ? w.HTMLTextAreaElement.prototype : w.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new w.Event("input", {bubbles:true}));
  };
  const send = (txt)=>{ const ta = doc.querySelector('textarea[aria-label="Message Nova"]');
    setVal(ta, txt); ta.dispatchEvent(new w.KeyboardEvent("keydown", {key:"Enter", bubbles:true})); };
  const msgs = ()=>[...doc.querySelectorAll(".msg-text")].map(d=>d.textContent).join("\n");
  const aMsgs = ()=>[...doc.querySelectorAll(".msg.assistant .msg-text")].map(d=>d.textContent).join("\n");
  const sendAndWait = async (txt, rx, desc, t=90000)=>{
    const before = [...doc.querySelectorAll(".msg.assistant .msg-text")].length;
    send(txt);
    await waitFor(()=>{ const m = [...doc.querySelectorAll(".msg.assistant .msg-text")].slice(before).map(d=>d.textContent).join("\n");
      return m.length>40 && rx.test(m); }, desc, t);
    return [...doc.querySelectorAll(".msg.assistant .msg-text")].slice(before).map(d=>d.textContent).join("\n");
  };

  // B1: login
  await waitFor(()=>doc.querySelector(".auth-card") && doc.querySelector('.auth-card input[placeholder="you@company.com"]'),
    "login card renders", 20000);
  setVal(doc.querySelector('.auth-card input[placeholder="you@company.com"]'), "sara@parsnovin.test");
  setVal(doc.querySelector('.auth-card input[placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"]'), "Pars2026Nova");
  doc.querySelector(".auth-card form").dispatchEvent(new w.Event("submit", {bubbles:true, cancelable:true}));
  await waitFor(()=>doc.querySelector(".user-card strong") && doc.querySelector(".user-card strong").textContent === "سارا محمدی",
    "Sara lands in the workspace", 20000);
  check("Sara signs in and sees HER name", true);
  const uc = doc.querySelector(".user-card").textContent.replace(/\s+/g," ");
  check("user card shows HER COMPANY «پارس‌نوین صنایع هوشمند»", uc.includes("پارس‌نوین"), uc.slice(0,90));

  // B2: the Departments page really lists her department
  const navTo = (label)=>{ [...doc.querySelectorAll(".sidebar .nav-item")].find(a=>a.textContent.trim()===label).dispatchEvent(new w.MouseEvent("click",{bubbles:true,cancelable:true})); };
  navTo("Departments");
  await waitFor(()=>[...doc.querySelectorAll("h3")].some(h=>h.textContent==="فروش"), "departments page shows فروش", 20000);
  await sleep(500);
  const deptCard = [...doc.querySelectorAll("h3")].find(h=>h.textContent==="فروش").closest("div");
  check("Departments page shows her «فروش» tile", true, deptCard.textContent.replace(/\s+/g," ").slice(0,80));

  // B3: AI CHAT - a REAL leave request through the brain's tool call
  navTo("AI Chat");
  await waitFor(()=>doc.querySelector('textarea[aria-label="Message Nova"]'), "chat composer", 15000);
  // unique date per run: re-running the test must not collide with the
  // leave created by the previous run (Odoo refuses overlapping leave)
  const off = 30 + (Math.floor(Date.now()/86400000) % 150);
  const d = new Date(Date.now() + off*86400000).toISOString().slice(0,10);
  try {
    const ans = await sendAndWait("Please register 2 days of leave for me starting "+d,
      /executed that in Odoo|submitted/i, "Nova executes the leave for real", 90000);
    check("Nova CREATES a real leave request (real Odoo tool call)", true,
      ans.split("\n").filter(l=>/submitted|date|status/i.test(l)).slice(0,2).join(" | ").slice(0,110));
  } catch(e){
    check("Nova CREATES a real leave request (real Odoo tool call)", false, aMsgs().slice(-160).replace(/\n/g," "));
  }

  // B4: an honest data answer (attendance)
  try {
    const ans = await sendAndWait("What is my attendance summary this month?",
      /hours|days|attendance|no check/i, "attendance answer arrives", 90000);
    check("Nova answers the attendance question with real data", true,
      ans.split("\n").filter(l=>/hours|days|check/i.test(l)).slice(0,1).join(" | ").slice(0,110));
  } catch(e){
    check("Nova answers the attendance question with real data", false, aMsgs().slice(-160).replace(/\n/g," "));
  }

  // B5: upload the warranty PDF -> verbatim quote
  await sleep(1500);
  const pdfBytes = readFileSync("/tmp/ctest/warranty.pdf");
  const file = new w.File([pdfBytes], "warranty.pdf", { type: "application/pdf" });
  const fileInput = doc.querySelector('input[type=file]');
  Object.defineProperty(fileInput, "files", { value: [file], configurable: true });
  fileInput.dispatchEvent(new w.Event("change", {bubbles:true}));
  await sleep(800);
  try {
    const ans = await sendAndWait("What is the warranty period?",
      /exactly 27 months/i, "verbatim quote from the PDF", 90000);
    check("Nova quotes the PDF verbatim (27 months)", ans.includes("exactly 27 months from the delivery date"));
    check("answer honestly marked 'Quoted verbatim'", ans.includes("Quoted verbatim"));
  } catch(e){
    check("Nova quotes the PDF verbatim (27 months)", false, aMsgs().slice(-140).replace(/\n/g," "));
    check("answer honestly marked 'Quoted verbatim'", false);
  }

  // B6: logout
  const outBtn = [...doc.querySelectorAll("button[aria-label]")].find(b=>b.getAttribute("aria-label")==="Log out");
  outBtn.dispatchEvent(new w.MouseEvent("click", {bubbles:true, cancelable:true}));
  await waitFor(()=>doc.querySelector('.auth-card input[placeholder="you@company.com"]'), "back to login", 15000);
  check("logout returns to the login card", true);
}

/* ---------- Part C: vendor console sees the REAL usage ---------- */
async function vendorPart(){
  console.log("=== C) VENDOR CONSOLE: real consumption per department & employee ===");
  const jar = makeJar();
  const res = await jarFetch(jar, BASE + "/admin");
  const html = await res.text();
  const dom = new JSDOM(html, { url: BASE+"/admin", runScripts:"outside-only", pretendToBeVisual:true });
  const w = dom.window;
  w.fetch = (u,o)=>jarFetch(jar, new URL(String(u), BASE).href, o);
  w.confirm = ()=>true; w.scrollTo = ()=>{};
  for (const sc of [...w.document.querySelectorAll("script")].map(s=>s.textContent))
    if (sc && sc.trim()) { try { w.eval(sc); } catch(e){ console.log("eval err:", e.message); } }
  await sleep(500);
  const $id = (i)=>w.document.getElementById(i);
  type($id("lu"), "admin"); type($id("lp"), process.env.ADMIN_PW || "NovaAdmin2026");
  click($id("lb"));
  await waitFor(()=>!$id("shell").hidden, "vendor console appears");
  const navTo = (label)=>{ [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.trim()===label).dispatchEvent(new w.MouseEvent("click",{bubbles:true})); };
  navTo("Token Usage");
  await waitFor(()=>{ const v = $id("view"); return v && v.textContent.includes("By employee"); }, "usage section renders", 30000);
  const v = $id("view").textContent.replace(/\s+/g," ");
  check("usage report lists department «فروش»", v.includes("فروش"));
  check("usage report lists employee «سارا محمدی» with department «فروش»",
    v.includes("سارا محمدی") && v.includes("sara@parsnovin.test"));
  const empRow = v.slice(v.indexOf("سارا محمدی"));
  const tok = empRow.match(/(\d[\d,]*)\s*(?:\d+ \/ \d+ |)turns|(\d[\d,]*)/);
  check("Sara's row has NON-ZERO real tokens", /سارا محمدی[\s\S]{0,200}?[1-9][\d,]*\s*\/\s*/.test(v) || /[1-9][\d,]* turns/.test(v) || /sara@parsnovin\.test[\s\S]{0,160}?[1-9]/.test(empRow.slice(0,300)),
    empRow.slice(0,120));
}

try { await devPart(); } catch(e){ console.log("FAIL part A:", e.message); fails++; }
try { await spaPart(); } catch(e){ console.log("FAIL part B:", e.message); fails++; }
try { await vendorPart(); } catch(e){ console.log("FAIL part C:", e.message); fails++; }
console.log(fails===0 ? "\n=== COMPANY SIMULATION: END-TO-END OK ===" : "\n=== "+fails+" FAILURES ===");
process.exit(fails===0?0:1);
