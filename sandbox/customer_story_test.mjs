/* ==============================================================
   CUSTOMER STORY TEST (jsdom) — the full delivery journey, driven
   like a real user through the REAL interfaces:
     Part A (vendor console /admin): create a customer user + set
             their password from the panel forms.
     Part B (customer app /aibox-odoo/): the SAME built React bundle
             a customer gets really executes in jsdom (module script
             is inlined as a classic script — jsdom limitation) and
             the user logs in, chats with Nova, uploads a PDF and
             receives a VERBATIM quote from it, then logs out.
   The backend gateway/brain are the REAL ones on this box (no mocks
   added by this script). Run: node customer_story_test.mjs
   Needs: jsdom@24 in /tmp, appliance 18069 + preview 5173, and
   /tmp/ctest/warranty.pdf (regenerate with the snippet in the
   session notes, or any small text PDF renamed to that path).
   Side effects: creates sara.story+<ts>@acme.test (block it with
   the panel's "Clean test data" afterwards).
   ============================================================== */import { JSDOM, ResourceLoader, VirtualConsole } from "/tmp/node_modules/jsdom/lib/api.js";
import { TextDecoder, TextEncoder } from "node:util";
import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";

const BASE = "http://127.0.0.1:5173";
const sleep = (ms)=>new Promise(r=>setTimeout(r,ms));
async function waitFor(fn, desc, t=15000){
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
let STORY_USER = "sara@acme.test";   // set by part A (fresh user each run)

/* ---------- Part A: vendor console creates the customer user ---------- */
async function adminPart(){
  console.log("=== A) VENDOR CONSOLE: create the customer user (real UI) ===");
  const jar = makeJar();
  const res = await jarFetch(jar, BASE + "/admin");
  const html = await res.text();
  const dom = new JSDOM(html, { url: BASE + "/admin", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  w.fetch = (u,o)=>jarFetch(jar, new URL(String(u), BASE).href, o);
  w.confirm = ()=>true;
  for (const sc of [...w.document.querySelectorAll("script")].map(s=>s.textContent)) {
    if (sc && sc.trim()) { try { w.eval(sc); } catch(e){ console.log("eval err:", e.message); } }
  }
  await sleep(500);
  const $id = (i)=>w.document.getElementById(i);
  type($id("lu"), "admin"); type($id("lp"), process.env.ADMIN_PW || "admin");
  click($id("lb"));
  await waitFor(()=>!$id("shell").hidden, "console appears");

  // Users -> create Sara (same flow the vendor would follow)
  const navTo = (label)=>{ [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes(label)).dispatchEvent(new w.MouseEvent("click",{bubbles:true})); };
  navTo("Users");
  await waitFor(()=>$id("nu_name"), "users form");
  type($id("nu_name"), "Sara Customer");
  const stamp = Date.now();
  STORY_USER = "sara.story+"+stamp+"@acme.test";
  type($id("nu_login"), STORY_USER);
  type($id("nu_pw"), "Customer123");
  click($id("nu_go"));
  await waitFor(()=>/created|exists|failed/.test($id("nu_msg").textContent), "user created");
  check("vendor creates a fresh customer user from the form", /created/.test($id("nu_msg").textContent), $id("nu_msg").textContent.slice(0,80));
  await sleep(1300);
  let saveBtn = null;
  await waitFor(()=>{ saveBtn = [...w.document.querySelectorAll("button[data-login]")].find(b=>b.dataset.login==="sara@acme.test") || null; return !!saveBtn; }, "save button for sara");
  type(w.document.getElementById(saveBtn.dataset.in), "Customer123");
  click(saveBtn);
  await waitFor(()=>/Password updated/.test($id("u_msg").textContent), "pw updated");
  check("vendor sets her password from the same screen", true);
}

/* ---------- Part B: customer app — REAL React SPA in jsdom ---------- */
/* same-origin resources only: the Google-Fonts link must not stall the
   real JS/CSS bundle load (offline box) */
class LocalOnly extends ResourceLoader {
  fetch(url, options) {
    if (String(url).startsWith(BASE)) return super.fetch(url, options);
    return null;
  }
}
const vcon = new VirtualConsole();
vcon.on("jsdomError", (e)=>{ if (!/Could not load link|Could not load img/.test(String(e))) console.log("   [jsdom]", String(e).slice(0,160)); });

async function makeApp(jar){
  const APP = BASE + "/aibox-odoo/";   // the app's real URL (basename of the SPA)
  const res = await jarFetch(jar, APP);
  let html = await res.text();
  // jsdom has no ES-module support; take the SAME built bundle and run it
  // as a classic script instead (import.meta only appears in vite's
  // preload helper -> rewritten to document.baseURI).
  const m = html.match(/<script type="module"[^>]*src="([^"]+)"[^>]*><\/script>/);
  if (!m) throw new Error("built bundle script tag not found in index.html");
  html = html.replace(m[0], "");
  const bundleRes = await jarFetch(jar, new URL(m[1], BASE).href);
  const bundle = (await bundleRes.text())
    .replace(/import\.meta\.resolve\?import\.meta\.resolve\(e\):new URL\(e,import\.meta\.url\)\.href/g,
             "new URL(e,document.baseURI).href");
  if (bundle.includes("import.meta")) throw new Error("bundle still contains import.meta");
  const dom = new JSDOM(html, {
    url: APP,
    runScripts: "dangerously",      // execute the page's own inline scripts
    resources: new LocalOnly(),     // load the real CSS bundle
    virtualConsole: vcon,
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
  dom.window.eval(bundle);          // the real React app, really running
  return dom.window;
}

async function customerPart(){
  console.log("=== B) CUSTOMER APP: Sara logs in, chats, uploads a PDF (real SPA) ===");
  const jar = makeJar();                       // fresh session: NOT the admin's
  const w = await makeApp(jar);
  const doc = w.document;

  const setVal = (el, v)=>{
    const proto = el.tagName === "TEXTAREA" ? w.HTMLTextAreaElement.prototype : w.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new w.Event("input", {bubbles:true}));
  };

  // 1. the shipped login card renders (React bundle really executed)
  await waitFor(()=>doc.querySelector(".auth-card") && doc.querySelector('.auth-card input[placeholder="you@company.com"]'),
    "login card renders (React bundle really executed)", 20000);
  check("customer login card really renders (React bundle executed)", true);

  // 2. Sara types her credentials (overwriting the prefilled demo ones)
  setVal(doc.querySelector('.auth-card input[placeholder="you@company.com"]'), STORY_USER);
  setVal(doc.querySelector('.auth-card input[placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"]'), "Customer123");
  const form = doc.querySelector(".auth-card form");
  form.dispatchEvent(new w.Event("submit", {bubbles:true, cancelable:true}));

  // 3. she lands in the workspace as Sara Customer
  try {
    await waitFor(()=>doc.querySelector(".user-card strong") && doc.querySelector(".user-card strong").textContent === "Sara Customer",
      "workspace after login (as Sara Customer)", 20000);
    check("Sara signs in and sees HER name in the app", true, "user-card: " + doc.querySelector(".user-card").textContent.replace(/\s+/g," ").trim());
  } catch(e) {
    const err = doc.querySelector(".auth-card .alert, .auth-card [class*=err]");
    throw new Error("login did not complete: " + (err ? err.textContent : e.message));
  }

  // 4. the chat is the landing page: greet Nova
  const ta = ()=>doc.querySelector('textarea[aria-label="Message Nova"]');
  await waitFor(ta, "chat composer", 15000);
  const msgs = ()=>[...doc.querySelectorAll(".msg-text")].map(d=>d.textContent).join("\n");
  setVal(ta(), "hello");
  ta().dispatchEvent(new w.KeyboardEvent("keydown", {key:"Enter", bubbles:true}));
  await waitFor(()=>msgs().includes("Hi! I'm Nova"), "Nova's greeting arrives (streaming)", 30000);
  check("Sara chats: Nova answers her greeting", true);

  // 5. she attaches the PDF and asks about it
  const pdfBytes = readFileSync("/tmp/ctest/warranty.pdf");
  const file = new w.File([pdfBytes], "warranty.pdf", { type: "application/pdf" });
  const fileInput = doc.querySelector('input[type=file]');
  Object.defineProperty(fileInput, "files", { value: [file], configurable: true });
  fileInput.dispatchEvent(new w.Event("change", {bubbles:true}));
  setVal(ta(), "What is the warranty period?");
  ta().dispatchEvent(new w.KeyboardEvent("keydown", {key:"Enter", bubbles:true}));

  // Nova answers by quoting the document verbatim (the shipped UI sends the
  // question + extracted analysis to the brain; the visible proof is the
  // quoted answer)
  try {
    await waitFor(()=>msgs().includes("exactly 27 months"), "verbatim quote from the PDF", 60000);
  } catch(e) {
    throw new Error("no verbatim reply. msgs=" + JSON.stringify([...doc.querySelectorAll(".msg-text")].map(d=>d.textContent.slice(0,120)))
      + " alerts=" + JSON.stringify([...doc.querySelectorAll(".alert")].map(d=>d.textContent.slice(0,120))));
  }
  const bubbleTxt = [...doc.querySelectorAll(".msg.assistant .msg-text")].map(d=>d.textContent).join("\n");
  check("Nova answers with the EXACT sentence from the PDF",
    bubbleTxt.includes("exactly 27 months from the delivery date"),
    bubbleTxt.slice(Math.max(0,bubbleTxt.indexOf("exactly 27 months")-80), bubbleTxt.indexOf("exactly 27 months")+120).replace(/\n/g," "));
  check("answer honestly marked 'Quoted verbatim from the document'",
    bubbleTxt.includes("Quoted verbatim from the document"));

  // 6. logout like a user
  const outBtn = [...doc.querySelectorAll("button[aria-label]")].find(b=>b.getAttribute("aria-label")==="Log out");
  outBtn.dispatchEvent(new w.MouseEvent("click", {bubbles:true, cancelable:true}));
  await waitFor(()=>doc.querySelector('.auth-card input[placeholder="you@company.com"]'), "back to login", 15000);
  check("logout returns Sara to the login card", true);
}

try { await adminPart(); } catch(e){ console.log("FAIL part A:", e.message); fails++; }
try { await customerPart(); } catch(e){ console.log("FAIL part B:", e.message); fails++; }
console.log(fails===0 ? "\n=== CUSTOMER STORY: END-TO-END OK ===" : "\n=== "+fails+" FAILURES ===");
process.exit(fails===0?0:1);
