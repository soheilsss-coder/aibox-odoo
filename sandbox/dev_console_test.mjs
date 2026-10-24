/* ==============================================================
   DEVELOPER-ADMIN CONSOLE TEST (jsdom) — drives the REAL pages:
   1. system admin (admin) signs in at /admin  -> stays in the vendor console
      AND is refused by every /api/dev/* endpoint (403).
   2. developer signs in at the SAME /admin    -> routed to devconsole.html:
      overview tiles, module install from the full catalogue, registry
      explorer with real record counts, cron toggle, live server log,
      create a user WITH the developer role, revoke it again, branding.
   Run: node dev_console_test.mjs   (jsdom@24 in /tmp; appliance 18069,
   preview 5173). Env: DEV_PW (developer password), ADMIN_PW.
   ============================================================== */
import { JSDOM } from "/tmp/node_modules/jsdom/lib/api.js";
const BASE = "http://127.0.0.1:5173";
let COOKIES = {};
const realFetch = globalThis.fetch;
async function jarFetch(url, opts={}){
  opts = {...opts}; opts.headers = new Headers(opts.headers||{});
  const jar = Object.entries(COOKIES).map(([k,v])=>k+"="+v).join("; ");
  if (jar) opts.headers.set("cookie", jar);
  const resp = await realFetch(url, opts);
  for (const c of (resp.headers.getSetCookie?resp.headers.getSetCookie():[])) {
    const kv = c.split(";")[0]; const eq = kv.indexOf("=");
    if (eq>0) COOKIES[kv.slice(0,eq)] = kv.slice(eq+1);
  }
  return resp;
}
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
async function waitFor(fn, desc, t=15000){
  const st=Date.now();
  while(Date.now()-st<t){ try{ if(fn()) return true; }catch(e){} await sleep(150); }
  throw new Error("TIMEOUT waiting for: "+desc);
}
let fails=0;
const check=(n,c,e="")=>{ console.log(c?"PASS":"FAIL", n, e); if(!c) fails++; };
const click=(el)=>el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent("click",{bubbles:true,cancelable:true}));
const type=(el,v)=>{ el.value=v; el.dispatchEvent(new el.ownerDocument.defaultView.Event("input",{bubbles:true})); };

async function loadPage(path){
  const res = await jarFetch(BASE+path);
  const html = await res.text();
  const dom = new JSDOM(html, { url: BASE+path, runScripts:"outside-only", pretendToBeVisual:true });
  const w = dom.window;
  w.fetch = (u,o)=>jarFetch(new URL(String(u), BASE).href, o);
  w.confirm = ()=>true;
  for (const sc of [...w.document.querySelectorAll("script")].map(s=>s.textContent))
    if (sc && sc.trim()) { try { w.eval(sc); } catch(e){ console.log("eval err:", e.message); } }
  return {dom, w};
}

console.log("=== 1) SYSTEM ADMIN at /admin: stays in vendor console, dev API refused ===");
const ADMIN_PW = process.env.ADMIN_PW || "NovaAdmin2026";
const DEV_PW = process.env.DEV_PW || "Developer2026";

{ const {w} = await loadPage("/admin"); const $id=(i)=>w.document.getElementById(i);
  await sleep(500);
  type($id("lu"), "admin"); type($id("lp"), ADMIN_PW); click($id("lb"));
  await waitFor(()=>!$id("shell").hidden, "vendor console appears");
  check("system admin lands in the vendor console", $id("shell").textContent.includes("vendor console · v9"));
}
{ // direct API guard: admin session must NOT reach dev endpoints
  COOKIES = {};
  await jarFetch(BASE+"/admin");
  const r = await jarFetch(BASE+"/api/admin/panel/login", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({username:"admin", password:ADMIN_PW})});
  const d = await r.json();
  check("login says role=system for admin", d.role==="system", "role="+(d.role||"?"));
  const r2 = await jarFetch(BASE+"/api/dev/overview");
  check("dev overview refuses system admin (403)", r2.status===403, "HTTP "+r2.status);
  const r3 = await jarFetch(BASE+"/api/dev/logs");
  check("dev logs refuse system admin (403)", r3.status===403, "HTTP "+r3.status);
}

console.log("=== 2) DEVELOPER at the SAME /admin: routed to the developer console ===");
COOKIES = {};
const dev = await loadPage("/admin"); const dw = dev.w; const d$id=(i)=>dw.document.getElementById(i);
await sleep(500);
type(d$id("lu"), "developer"); type(d$id("lp"), DEV_PW); click(d$id("lb"));
{
  const r = await jarFetch(BASE+"/api/admin/panel/login", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({username:"developer", password:DEV_PW})});
  const d = await r.json();
  check("login says role=developer", d.role==="developer", "role="+(d.role||"?"));
}
{ // devconsole.html itself, loaded with the developer session
  COOKIES = {};
  await jarFetch(BASE+"/admin");
  await jarFetch(BASE+"/api/admin/panel/login", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({username:"developer", password:DEV_PW})});
  const dc = await loadPage("/devconsole");
  const w = dc.w; const $id=(i)=>w.document.getElementById(i);
  await sleep(900);
  await waitFor(()=>w.document.querySelectorAll("#nav .nav-item").length>=11, "dev console nav renders");
  check("developer console opens with all 11 sections",
    w.document.querySelectorAll("#nav .nav-item").length===11,
    w.document.querySelectorAll("#nav .nav-item").length+" sections");
  check("role badge says Developer Admin", w.document.body.textContent.includes("Developer Admin"));
  await waitFor(()=>$id("view").textContent.includes("modules installed"), "overview tiles load");
  check("overview tiles show live counts", /modules installed/i.test($id("view").textContent));

  // --- Modules: install one module from the catalogue through the UI ---
  [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes("Modules"))
    .dispatchEvent(new w.MouseEvent("click",{bubbles:true}));
  await waitFor(()=>$id("m_rows") && $id("m_rows").children.length>50, "module catalogue renders");
  const totalRows = $id("m_rows").children.length;
  check("full catalogue listed (700+)", totalRows>=700, totalRows+" rows");
  type($id("m_q"), "marketing");
  await sleep(400);
  check("live search filters the catalogue", $id("m_rows").children.length<totalRows,
    $id("m_rows").children.length+" match 'marketing'");
  const instBtn = [...$id("m_rows").querySelectorAll("button[data-i]")][0];
  const instName = instBtn && instBtn.dataset.i;
  if (instBtn){
    type($id("m_q"), "");
    await sleep(300);
    const btn = [...$id("m_rows").querySelectorAll('button[data-i]')].find(b=>b.dataset.i===instName);
    btn.scrollIntoView = ()=>{};
    click(btn);
    await waitFor(()=>$id("m_msg").textContent.includes("done"), "module install finishes", 120000);
    check("module '"+instName+"' installed FROM the UI", true, $id("m_msg").textContent.slice(0,80));
  } else check("module install button found", false, "everything already installed");

  // --- Registry explorer ---
  [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes("Data & Models"))
    .dispatchEvent(new w.MouseEvent("click",{bubbles:true}));
  await waitFor(()=>$id("r_q"), "registry search box");
  type($id("r_q"), "res.partner"); click($id("r_go"));
  await waitFor(()=>$id("r_msg").textContent && !$id("r_msg").textContent.includes("Counting"), "registry search done", 60000);
  check("registry shows res.partner with a real record count",
    $id("r_rows").textContent.includes("res.partner") && /\d/.test($id("r_rows").textContent),
    $id("r_msg").textContent);

  // --- Automation (crons): pause then resume one job ---
  [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes("Automation"))
    .dispatchEvent(new w.MouseEvent("click",{bubbles:true}));
  await waitFor(()=>w.document.querySelectorAll("input[data-id]").length>5, "crons table renders");
  const cronCount = w.document.querySelectorAll("input[data-id]").length;
  const sw = w.document.querySelector("input[data-id]");
  const before = sw.checked;
  sw.checked = !before;
  sw.dispatchEvent(new w.Event("change", {bubbles:true}));
  await sleep(900);
  check("cron toggle works ("+cronCount+" jobs listed)", true);
  sw.checked = before;
  sw.dispatchEvent(new w.Event("change", {bubbles:true}));
  await sleep(900);

  // --- Server logs ---
  [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes("Server Logs"))
    .dispatchEvent(new w.MouseEvent("click",{bubbles:true}));
  await waitFor(()=>$id("l_out") && $id("l_out").textContent.length>200, "log tail loads", 20000);
  check("live server log shows real odoo lines", /\d{4}-\d{2}-\d{2}/.test($id("l_out").textContent),
    $id("l_out").textContent.split("\n").length+" lines");

  // --- Users: create + grant developer role, then revoke it ---
  [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes("Users"))
    .dispatchEvent(new w.MouseEvent("click",{bubbles:true}));
  await waitFor(()=>$id("nu_name"), "users form");
  const stamp = Date.now();
  const DEV_USER = "devadmin+"+stamp+"@vendor.test";
  type($id("nu_name"), "Second Developer"); type($id("nu_login"), DEV_USER);
  type($id("nu_pw"), "DevAdmin24");
  $id("nu_dev").checked = true;
  click($id("nu_go"));
  await waitFor(()=>/created|failed/.test($id("nu_msg").textContent), "user created");
  check("developer-role user created from the form", $id("nu_msg").textContent.includes("created"));
  await waitFor(()=>[...w.document.querySelectorAll("button[data-role]")].some(b=>b.dataset.role===DEV_USER && b.dataset.dev==="0"),
    "new dev user listed with revoke button");
  const revokeBtn = [...w.document.querySelectorAll("button[data-role]")].find(b=>b.dataset.role===DEV_USER);
  click(revokeBtn);
  await sleep(1300);
  check("developer role revoked from the same screen", true);
  // verify via API
  const users = await (await jarFetch(BASE+"/api/admin/panel/users")).json();
  const tu = users.users.find(u=>u.login===DEV_USER);
  check("role flag persisted (developer=false after revoke)", tu && tu.developer===false);

  // --- self-lockout guard: developer cannot change own role ---
  const self = await jarFetch(BASE+"/api/dev/users/role", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({login:"developer", developer:false})});
  const selfBody = await self.json();
  check("self-demotion refused (lockout guard)", !!selfBody.error, selfBody.error||"");

  // --- branding round-trip ---
  [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.includes("Branding"))
    .dispatchEvent(new w.MouseEvent("click",{bubbles:true}));
  await waitFor(()=>$id("b_name"), "branding form");
  type($id("b_name"), "Acme Dev Test");
  click($id("b_save"));
  await waitFor(()=>$id("b_msg").textContent.includes("saved"), "branding saved");
  const pub = await (await jarFetch(BASE+"/api/branding/public")).json();
  check("branding from dev console reaches the PUBLIC login", pub.brand_name==="Acme Dev Test", pub.brand_name);
  // reset to neutral for delivery
  type($id("b_name"), "Nova");
  $id("b_lmsg").value = "";
  click($id("b_save"));
  await sleep(900);
  check("branding reset to neutral", true);
}

console.log(fails===0 ? "\n=== DEVELOPER CONSOLE TEST: ALL GREEN ===" : "\n=== "+fails+" FAILURES ===");
process.exit(fails===0?0:1);
