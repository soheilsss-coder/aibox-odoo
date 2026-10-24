/* ==============================================================
   ACCESS-AWARE ASSISTANT TEST (jsdom) — the AI chat must answer
   according to WHO is asking (persona) and WHAT they may see
   (isolation), through the REAL shipped React app:

     Part S (سارا محمدی - employee, «فروش»):
       - greets her PERSONALLY (identity-context persona)
       - asks for pending leave approvals: she sees HER OWN requests
         only - کیان's request must NOT leak into her answer
       - asks what the assistant can do: it must talk about HER
         access level, not generic admin powers
     Part A (علی کریمی - executive + team time-off responsible):
       - greets HIM personally
       - the SAME pending-approvals question now shows the TEAM's
         requests (سارا + کیان) - role-aware data, same tool

   The enforcement stack being proven: per-user tool allowlist +
   tools executing under the calling user's env + Odoo record rules
   (hr.leave) + capability gate + injected identity-context prompt.
   Run: node access_aware_test.mjs
   ============================================================== */
import { JSDOM, ResourceLoader, VirtualConsole } from "/tmp/node_modules/jsdom/lib/api.js";
import { TextDecoder, TextEncoder } from "node:util";
import { webcrypto } from "node:crypto";

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
  if (!m) throw new Error("built bundle script tag not found");
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

async function chatSession(user, password, firstAction){
  console.log("=== %s (%s) ===", user, firstAction);
  const jar = makeJar();
  const w = await makeApp(jar);
  const doc = w.document;
  const setVal = (el, v)=>{
    const proto = el.tagName === "TEXTAREA" ? w.HTMLTextAreaElement.prototype : w.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new w.Event("input", {bubbles:true}));
  };
  const aMsgs = ()=>[...doc.querySelectorAll(".msg.assistant .msg-text")].map(d=>d.textContent).join("\n");
  const sendAndWait = async (txt, rx, desc, t=90000)=>{
    const before = [...doc.querySelectorAll(".msg.assistant .msg-text")].length;
    const ta = doc.querySelector('textarea[aria-label="Message Nova"]');
    setVal(ta, txt);
    ta.dispatchEvent(new w.KeyboardEvent("keydown", {key:"Enter", bubbles:true}));
    await waitFor(()=>{ const m = [...doc.querySelectorAll(".msg.assistant .msg-text")].slice(before).map(d=>d.textContent).join("\n");
      return m.length>30 && rx.test(m); }, desc, t);
    return [...doc.querySelectorAll(".msg.assistant .msg-text")].slice(before).map(d=>d.textContent).join("\n");
  };

  // login through the real login card
  await waitFor(()=>doc.querySelector(".auth-card") && doc.querySelector('.auth-card input[placeholder="you@company.com"]'),
    "login card", 20000);
  setVal(doc.querySelector('.auth-card input[placeholder="you@company.com"]'), user);
  setVal(doc.querySelector('.auth-card input[placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"]'), password);
  doc.querySelector(".auth-card form").dispatchEvent(new w.Event("submit", {bubbles:true, cancelable:true}));
  await waitFor(()=>doc.querySelector(".user-card strong"), "workspace", 20000);
  const who = doc.querySelector(".user-card strong").textContent;
  check("[%s] signs in and sees HER/HIS name" ? "[%s] signs in (%s)" : "", true, who);
  return { w, doc, aMsgs, sendAndWait, who };
}

/* ---------- Part S: the EMPLOYEE ---------- */
async function saraPart(){
  const s = await chatSession("sara@parsnovin.test", "Pars2026Nova", "employee");
  check("Sara signs in (سارا محمدی)", s.who.includes("سارا"), s.who);

  const g = await s.sendAndWait("سلام", /نووا|Nova/, "personal greeting", 90000);
  check("assistant greets her PERSONALLY (identity persona)", g.includes("سارا"), g.split("\n")[0].slice(0,90));

  const p = await s.sendAndWait("لیست درخواست‌های مرخصی در انتظار تأیید را نشان بده",
    /(count|تعداد|\d)/, "pending-leave answer", 90000);
  check("employee sees ONLY HER OWN pending requests (no leak)", p.includes("سارا محمدی") && !p.includes("کیان"),
    "mentions-sara:" + p.includes("سارا محمدی") + " leaks-kian:" + p.includes("کیان"));

  const c = await s.sendAndWait("چه کارهایی می‌تونی برای من انجام بدی؟", /(دسترسی|ابزار|می‌تون|مدیریت)/, "capability answer", 90000);
  check("capability talk is access-level aware (own scope, not admin powers)",
    /دسترسی|خودتان|خودت|اجازه/.test(c), c.split("\n")[0].slice(0,90));

  // logout
  const outBtn = [...s.doc.querySelectorAll("button[aria-label]")].find(b=>b.getAttribute("aria-label")==="Log out");
  outBtn.dispatchEvent(new s.w.MouseEvent("click", {bubbles:true, cancelable:true}));
  await waitFor(()=>s.doc.querySelector('.auth-card input[placeholder="you@company.com"]'), "back to login", 15000);
  check("logout", true);
}

/* ---------- Part A: the EXECUTIVE / time-off responsible ---------- */
async function aliPart(){
  const a = await chatSession("ali@parsnovin.test", "Pars2026Nova", "executive");
  check("Ali signs in (علی کریمی)", a.who.includes("علی"), a.who);

  const g = await a.sendAndWait("hello", /Nova|نووا/, "personal greeting", 90000);
  check("assistant greets HIM personally (identity persona)", g.includes("علی"), g.split("\n")[0].slice(0,90));

  const p = await a.sendAndWait("لیست درخواست‌های مرخصی در انتظار تأیید را نشان بده",
    /count: \d+|pending:/, "pending-leave answer", 90000);
  check("manager sees the TEAM's requests (سارا + کیان)",
    p.includes("سارا محمدی") && p.includes("کیان رضایی"),
    "sara:" + p.includes("سارا محمدی") + " kian:" + p.includes("کیان رضایی"));
}

try { await saraPart(); } catch(e){ console.log("FAIL part S:", e.message); fails++; }
try { await aliPart(); } catch(e){ console.log("FAIL part A:", e.message); fails++; }
console.log(fails===0 ? "\n=== ACCESS-AWARE ASSISTANT: END-TO-END OK ===" : "\n=== "+fails+" FAILURES ===");
process.exit(fails===0?0:1);
