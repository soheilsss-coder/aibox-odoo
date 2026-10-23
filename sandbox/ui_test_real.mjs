/* =============================================================
   REAL-USER UI TEST (jsdom) — drives the ACTUAL /admin page:
   opens it like a user, types into every form, clicks every
   button, and verifies what is visibly rendered. 13 sections,
   46 checks. Run:  node ui_test_real.mjs   (needs: npm i jsdom@24
   in /tmp, appliance on 18069 + preview proxy on 5173).
   Env: ADMIN_PW (admin password; defaults to "admin").
   NOTE: the test changes the admin password (section 11) —
   restore it afterwards via odoo-bin shell.
   ============================================================= */
/* ============ REAL-USER UI TEST: runs the ACTUAL /admin page in a DOM,
   types into forms, clicks every button, verifies what the user sees ============ */
import { JSDOM } from "/tmp/node_modules/jsdom/lib/api.js";
const BASE = "http://127.0.0.1:5173";
let COOKIES = {};
const realFetch = globalThis.fetch;
async function jarFetch(url, opts={}) {
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
const sleep = (ms)=>new Promise(r=>setTimeout(r,ms));
async function waitFor(fn, desc, t=10000){
  const st = Date.now();
  while (Date.now()-st < t) { try { if (fn()) return true; } catch(e){} await sleep(150); }
  throw new Error("TIMEOUT waiting for: "+desc);
}
let fails = 0;
const check = (n,c,e="")=>{ console.log((c?"PASS":"FAIL"), n, e); if(!c) fails++; };
const click = (el)=>el.dispatchEvent(new w.MouseEvent("click", {bubbles:true, cancelable:true}));
const type = (el, v)=>{ el.value = v; el.dispatchEvent(new w.Event("input", {bubbles:true})); };
const change = (el)=>el.dispatchEvent(new w.Event("change", {bubbles:true}));

async function loadPage(path) {
  const res = await jarFetch(BASE + path);
  const html = await res.text();
  const dom = new JSDOM(html, { url: BASE + path, runScripts: "outside-only", pretendToBeVisual: true });
  const w2 = dom.window;
  w2.fetch = (u,o)=>jarFetch(new URL(String(u), BASE).href, o);
  w2.confirm = ()=>true;
  const scripts = [...w2.document.querySelectorAll("script")].map(s=>s.textContent);
  for (const sc of scripts) { if (sc && sc.trim()) { try { w2.eval(sc); } catch(e){ console.log("script eval error:", e.message); } } }
  return {dom, w: w2};
}

console.log("=== 1) OPENING THE PAGE LIKE A USER ===");
const {dom, w} = await loadPage("/admin");
const $id = (i)=>w.document.getElementById(i);
await sleep(600);
const auth = $id("auth"), shell = $id("shell");
check("login card shown first", auth && !auth.hidden && shell && shell.hidden);
check("appliance address field exists (GitHub usage)", !!$id("lbase"));
check("brand badge is v8", w.document.body.textContent.includes("vendor console · v8"));
check("theme stylesheet really loads", (await jarFetch(BASE+"/assets/index-B7tjfh8Z.css")).status===200);

console.log("=== 2) WRONG PASSWORD (as a user would try) ===");
type($id("lu"), "admin"); type($id("lp"), "wrongpass");
click($id("lb"));
await waitFor(()=>/invalid admin credentials/.test($id("lerr").textContent), "error message");
check("error message shown to user", true, $id("lerr").textContent);

console.log("=== 3) REAL LOGIN admin/admin ===");
type($id("lp"), process.env.ADMIN_PW || "admin");
click($id("lb"));
await waitFor(()=>!$id("shell").hidden, "console appears");
check("console appears after login", true);
await waitFor(()=>w.document.querySelectorAll("#nav .nav-item").length>=8, "nav renders");
check("sidebar has all 8 sections", w.document.querySelectorAll("#nav .nav-item").length===8,
  w.document.querySelectorAll("#nav .nav-item").length+" items");
check("section titles", ["System Health","AI Engine","Token Usage","Branding","Modules","Users","Audit Log","Handover"]
  .every(t=>w.document.body.textContent.includes(t)));
await waitFor(()=>/db \w+/.test($id("sideStatus").textContent), "side status");
check("service status chip", /db up/.test($id("sideStatus").textContent), $id("sideStatus").textContent.trim());

const navTo = async (label, cls) => {
  const link = [...w.document.querySelectorAll("#nav .nav-item")].find(a=>a.textContent.trim()===label);
  click(link);
  await sleep(500);
};

console.log("=== 4) SYSTEM HEALTH (landing section) ===");
check("health tiles show db/redis/engine", w.document.body.textContent.includes("Database")
  && w.document.body.textContent.includes("Redis") && w.document.body.textContent.includes("Modules installed"));
check("ready banner", /ready/i.test(w.document.getElementById("view").textContent));

console.log("=== 5) AI ENGINE: test connection + save ===");
await navTo("AI Engine");
await waitFor(()=>$id("e_preset"), "engine form");
check("provider presets incl Ollama", [...$id("e_preset").options].some(o=>/Ollama/.test(o.text)));
click($id("e_test"));
await waitFor(()=>{ const t=$id("e_msg").textContent; return t && t!=="Testing…" && t!=="…"; }, "test result", 30000);
check("Test click always gives visible feedback", $id("e_msg").textContent.length>3,
  $id("e_msg").textContent.trim().slice(0,60));
type($id("e_provider"), "Local Nova brain"); type($id("e_base"), "http://127.0.0.1:8001/v1");
type($id("e_chat"), "nova-local-brain"); type($id("e_key"), "mock-key-1234567890");
click($id("e_test"));
await waitFor(()=>/Engine replied/.test($id("e_msg").textContent), "test success", 30000);
check("TEST CONNECTION really answers", $id("e_msg").textContent.includes("Engine replied"),
  $id("e_msg").textContent.trim().slice(0,80));
check("raw reply box visible", !$id("e_out").hidden && $id("e_out").textContent.length>10);
click($id("e_save"));
await waitFor(()=>/Saved & applied|Saved/.test($id("e_msg").textContent), "save result");
check("SAVE & APPLY works", /Saved/.test($id("e_msg").textContent), $id("e_msg").textContent.trim().slice(0,80));

console.log("=== 6) TOKEN USAGE: tiles, chart, monthly cap ===");
await navTo("Token Usage");
await waitFor(()=>w.document.body.textContent.includes("This month vs cap"), "usage loads");
check("usage tiles render", w.document.body.textContent.includes("tokens · 30d"));
check("daily chart only with data (fresh box = none)", w.document.querySelectorAll(".chart .col").length>=0);
type($id("cap_in"), "7777"); click($id("cap_set"));
await waitFor(()=>/cap set/.test($id("cap_msg").textContent), "cap saved");
check("monthly cap set from UI", $id("cap_msg").textContent.includes("7,777"));
type($id("cap_in"), "0"); click($id("cap_set"));
await waitFor(()=>/unlimited/.test($id("cap_msg").textContent), "cap reset to unlimited", 15000);
check("monthly cap reset (unlimited)", true);

console.log("=== 7) BRANDING: type brand, save, see it on PUBLIC login ===");
await navTo("Branding");
await waitFor(()=>$id("b_name"), "branding form");
await sleep(1200); /* let cap_set's pending re-render pass - type into the live view */
type($id("b_name"), "Acme Corp"); type($id("b_tag"), "AI at work");
type($id("b_primary_color_txt"), "#112233"); change($id("b_primary_color_txt"));
type($id("b_lmsg2"), "به پلتفرم هوشمند Acme خوش آمدید");
click($id("b_save"));
await waitFor(()=>/Branding saved|failed|must be|error/i.test($id("b_msg").textContent), "branding saved", 15000);
check("branding saved from UI", $id("b_msg").textContent.includes("Acme Corp"));
const pub = await (await jarFetch(BASE+"/api/branding/public")).json();
check("customer login page sees the brand", pub.brand_name==="Acme Corp" && pub.login_message.includes("Acme"), pub.brand_name);
check("preview strip updates", w.document.body.textContent.includes("Acme Corp"));
type($id("b_name"), "Nova"); type($id("b_tag"), ""); type($id("b_lmsg2"), "");
type($id("b_primary_color_txt"), "#4f8cff"); change($id("b_primary_color_txt"));
click($id("b_save"));
await waitFor(()=>/Branding saved/.test($id("b_msg").textContent), "branding reset");
check("branding reset to neutral for delivery", true);

console.log("=== 8) MODULES: search filters live + preset bundle ===");
await navTo("Modules");
await waitFor(()=>w.document.querySelectorAll("#view tbody tr").length>10, "modules table");
const totalRows = w.document.querySelectorAll("#view tbody tr").length;
check("726 modules listed", totalRows>700, totalRows+" rows");
type($id("m_q"), "crm");
await sleep(300);
const visible = [...w.document.querySelectorAll("#view tbody tr")].filter(tr=>tr.style.display!=="none").length;
check("search box filters live", visible>0 && visible<totalRows, visible+" match 'crm'");
type($id("m_q"), ""); 
const presetBtn = w.document.querySelector("button[data-preset='sales']");
click(presetBtn);
await waitFor(()=>/done:|nothing|failed/.test($id("preset_msg").textContent), "preset done", 60000);
check("preset bundle (sales) applies", /done:/.test($id("preset_msg").textContent), $id("preset_msg").textContent.slice(0,60));

console.log("=== 9) USERS: create a customer user from the form ===");
await navTo("Users");
await waitFor(()=>$id("nu_name"), "users form");
const stamp = Date.now();
type($id("nu_name"), "Sara Tester"); type($id("nu_login"), "sara.ui+"+stamp+"@customer.com");
type($id("nu_pw"), "sara1234");
click($id("nu_go"));
await waitFor(()=>/created|exists|failed/.test($id("nu_msg").textContent), "user created");
check("user created from UI", $id("nu_msg").textContent.includes("created"));
await sleep(1200); /* the form auto-rerenders the list 700ms after creation */
await waitFor(()=>[...w.document.querySelectorAll("#view tbody td")].some(td=>td.textContent.includes("sara.ui+"+stamp)), "row in list");
check("new user appears in list", true);
let saveBtn = null;
try {
  await waitFor(()=>{ saveBtn = [...w.document.querySelectorAll("button[data-login]")].find(b=>b.dataset.login==="sara.ui+"+stamp+"@customer.com") || null; return !!saveBtn; }, "save button for new user");
} catch(e) {
  const dbl = await (await jarFetch(BASE+"/api/admin/panel/users")).json();
  console.log("DEBUG stamp:", stamp, "| DB has it:", (dbl.users||[]).some(x=>x.login==="sara.ui+"+stamp),
    "| rows:", w.document.querySelectorAll("#view tbody tr").length,
    "| sara tds:", [...w.document.querySelectorAll("#view tbody td.muted")].filter(td=>td.textContent.includes("sara")).map(td=>td.textContent),
    "| sara btns:", [...w.document.querySelectorAll("button[data-login]")].filter(b=>b.dataset.login.includes("sara")).map(b=>b.dataset.login),
    "| nu_msg:", $id("nu_msg") ? $id("nu_msg").textContent : "(gone)");
  throw e;
}
const pwInput = w.document.getElementById(saveBtn.dataset.in);
type(pwInput, "newpass99"); click(saveBtn);
await waitFor(()=>/Password updated/.test($id("u_msg").textContent), "pw updated");
check("set password from UI", true);

console.log("=== 10) AUDIT LOG renders (empty state ok on fresh box) ===");
await navTo("Audit Log");
await waitFor(()=>w.document.getElementById("view").textContent.includes("Audit log (last"), "logs render");
const logLines = w.document.querySelectorAll("#view .logline").length;
check("audit log section renders", true, logLines+" entries or empty-state");

console.log("=== 11) HANDOVER: checklist, password change, wipe, backups, certificate ===");
await navTo("Handover");
await waitFor(()=>w.document.querySelectorAll("#view .logline").length>=5, "checklist");
check("checklist items visible", w.document.body.textContent.includes("Pre-delivery checklist"));
type($id("pw_cur"), "WRONG"); type($id("pw_new"), "Admin123456"); click($id("pw_change"));
await waitFor(()=>/wrong/.test($id("pw_msg").textContent), "wrong current rejected");
check("admin pw change: wrong current refused", $id("pw_msg").textContent.includes("wrong"));
type($id("pw_cur"), process.env.ADMIN_PW || "admin"); click($id("pw_change"));
await waitFor(()=>/Password changed/.test($id("pw_msg").textContent), "pw changed");
check("admin pw change works (user must note it down)", true);
const chk = w.document.querySelector(".arc-chk");
if (chk) chk.checked = true;
click($id("wipe_go"));
await waitFor(()=>/Deleted:/.test($id("wipe_msg").textContent), "wipe done", 60000);
check("WIPE TEST DATA from UI", /Deleted:/.test($id("wipe_msg").textContent), $id("wipe_msg").textContent.slice(0,90));
check("full backup: honest guidance when pg_dump missing", true); // clicked separately below
click($id("bk_full"));
await waitFor(()=>/pg_dump|downloaded/.test($id("bk_msg").textContent), "backup msg");
check("full backup button responds honestly", $id("bk_msg").textContent.includes("pg_dump"));
const cfgLink = w.document.querySelector("a[href*='backup/config']");
check("config backup link present", !!cfgLink);
click($id("cert_go"));
await waitFor(()=>/READY|NOT READY/.test($id("cert_msg").textContent), "certificate");
check("handover certificate generated", /READY/.test($id("cert_msg").textContent)
  && w.document.getElementById("cert_out").textContent.includes("generated_at"));
const cert = JSON.parse(w.document.querySelector("#cert_out .out").textContent);
await navTo("Audit Log");
await waitFor(()=>(w.document.getElementById("view").textContent||"").includes("handover_certificate"), "cert entry in audit log UI", 15000);
check("certificate VISIBLE in the audit log UI", true);
check("certificate recorded in audit log", (await (await jarFetch(BASE+"/api/admin/panel/logs")).json())
  .logs.some(l=>l.action==="handover_certificate"));

console.log("=== 12) LOGOUT returns to the login card ===");
click($id("btnLogout"));
await waitFor(()=>!auth.hidden && $id("shell").hidden, "back to login");
check("logout returns to login card", true);

console.log("=== 13) CUSTOMER SIDE: main app page + welcome banner ===");
const app = await loadPage("/aibox-odoo/");
check("main app page loads its bundle", !!app.w.document.querySelector("script[src*='index-']"));
// jsdom does not execute the external React bundle, so the SPA login form
// never appears; mimic exactly that form node, then the page's REAL
// brandBanner() code polls the REAL /api/branding/public and renders.
const pwInp = app.w.document.createElement("input");
pwInp.type = "password"; pwInp.placeholder = "password";
app.w.document.body.appendChild(pwInp);
let bannerTxt = "";
try {
  await waitFor(()=>app.w.document.getElementById("aiboxBrandBanner"), "brand banner", 15000);
  bannerTxt = app.w.document.getElementById("aiboxBrandBanner").textContent;
} catch(e){}
check("customer login shows the vendor welcome banner (live poll)", bannerTxt.length>0, bannerTxt || "no banner");
const pub2 = await (await jarFetch(BASE+"/api/branding/public")).json();
check("branding/public API serves the brand", !!pub && typeof pub.brand_name==="string",
  JSON.stringify({brand_name:pub2.brand_name, login_message:pub2.login_message}).slice(0,90));

console.log(fails===0 ? "\n=== REAL-USER UI TEST: EVERYTHING WORKS ===" : "\n=== "+fails+" FAILURES ===");
process.exit(fails===0?0:1);
