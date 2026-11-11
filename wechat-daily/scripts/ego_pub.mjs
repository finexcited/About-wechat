// 公众号「自动存草稿」发布模块（ego lite 唯一通道）
// ---------------------------------------------------------------------------
// 本文件是本技能**唯一**的浏览器自动化入口。所有浏览器动作（启动、导航、登录、
// 填表、上传、点击、截图、核验）都通过 ego lite 的 Node API 完成，不依赖任何
// 外部浏览器驱动进程或会话文件。
//
// 用法（输入全部走配置文件；ego-browser 既不转发命令行参数，也不继承调用方环境变量）
//   1) 让脚本找得到配置文件——解析顺序（**命中即停，不往下兜底**）：
//        ① env  WX_DAILY_OUT/_ego/pub_jobs.json   （只有直接用 node 跑时才有效）
//        ② 指针 ~/.wx-ego-dir 的第一行 + /_ego/pub_jobs.json
//        ③ 默认 ~/Documents/公众号推文/_ego/pub_jobs.json
//      第 ② 条存在的唯一理由：`dir` 写在配置里，但要读配置得先知道去哪读——
//      鸡生蛋。指针记录「配置所在目录」，`python3 scripts/bootstrap.py` 会按
//      WX_DAILY_OUT 自动维护它，所以正常流程用不着手写。
//   2) ego-browser nodejs < <技能目录>/scripts/ego_pub.mjs
//
// pub_jobs.json 结构：
//   {
//     "cmd": "login" | "article" | "cover" | "verify" | "status" | "close",
//     "space": "发布-你的号简称",        // ⚠️ ego-browser 读不到 WX_PUBLISH_SPACE，
//                                        // 所以多号必须在这里逐号写不同的 space——
//                                        // 不写就全落到 "公众号发布" 同一个会话里，
//                                        // 两个号互相顶掉登录态且**不报错**（串号）
//     "token": "1234567890",            // 可选，缺省读 _wx_token.json
//     "author": "你的笔名",             // ⚠️ ego-browser 读不到 WX_AUTHOR / WX_BRAND，
//                                        // 不写署名会退化成占位值「你的公众号」；
//                                        // 空串 "" ＝有意不填作者
//     "dir": "/Users/…/公众号推文",      // 可选。只把**产物**指到别处，不改变配置文件位置
//     "resume": true,                   // 可选，article 跳过已成功篇目
//     "haltAfter": 2,                   // 可选，连续失败几篇停机；0＝不停机（Q30 选项 2）
//     "jobs": [ {"base":"标题_2026-11-02","appmsgid":"100002766"} ]
//   }
//
// 输出：每步一行 JSON 到 stdout，并追加写 _ego/pub_log.jsonl；
//       article/cover 结果写 _ego/pub_results.json；进度写 _ego/pub_done.json。
//
// 铁律：只存草稿，绝不点「发表 / 群发」。
// ---------------------------------------------------------------------------

const fs = await import("node:fs/promises");
const os = await import("node:os");

const HOME = os.homedir();
const DEFAULT_DIR = `${HOME}/Documents/公众号推文`;
// 指针文件：记录「含 _ego/pub_jobs.json 的那个目录」。
// 为什么需要它：ego-browser 不继承调用方环境变量（实测 process.env.WX_* 全 undefined、
// cwd 变 "/"），所以 WX_DAILY_OUT 在真实调用下读不到；而 `dir` 又写在配置里——
// 想读配置得先知道去哪读，这就是鸡生蛋。指针把这个环断开。
// bootstrap.py 会按 WX_DAILY_OUT 自动写它，所以正常流程不用手建。
const POINTER_FILE = `${HOME}/.wx-ego-dir`;

const readPointer = async () => {
  const raw = await fs.readFile(POINTER_FILE, "utf8").catch(() => "");
  const first = raw.split("\n")[0].trim();
  return first || null;
};

// 命中即停，不往下兜底：一旦退回默认目录，就会**静默读到默认目录里的旧配置**，
// 表现是「明明配了自定义目录，任务却跑了别的号/别的目录」——比报错难查得多。
const resolveBase = async () => {
  const envDir = (process.env.WX_DAILY_OUT || "").trim();
  if (envDir) return { base: envDir, from: "env WX_DAILY_OUT" };
  const ptr = await readPointer();
  if (ptr) return { base: ptr, from: `指针文件 ${POINTER_FILE}` };
  return { base: DEFAULT_DIR, from: "默认目录" };
};

const { base: BASE, from: BASE_FROM } = await resolveBase();
const cfgPath = `${BASE}/_ego/pub_jobs.json`;

let cfg;
try {
  cfg = JSON.parse(await fs.readFile(cfgPath, "utf8"));
} catch (e) {
  const why = e && e.code === "ENOENT" ? "配置不存在" : "配置不是合法 JSON";
  // 这条错误以前是裸 ENOENT，看上去像「目录不存在」，实际是「找不到配置文件」。
  // 现在把解析链和修法一次说清，省一轮猜。
  console.error(JSON.stringify({
    step: "abort",
    why: "no_config",
    detail: why,
    cfgPath,
    resolvedBy: BASE_FROM,
    tried: [process.env.WX_DAILY_OUT, await readPointer(), DEFAULT_DIR].filter(Boolean),
    hint: `按「${BASE_FROM}」解析到 ${cfgPath}，读不到。`
        + `ego-browser 不继承调用方环境变量，所以 WX_DAILY_OUT 在这里通常无效。`
        + `两种修法：① 把 pub_jobs.json 放到上面这个路径；`
        + `② 写指针：echo "<含 _ego 的绝对目录>" > ${POINTER_FILE}。`
        + `（跑 python3 scripts/bootstrap.py 会按 WX_DAILY_OUT 自动维护这个指针）`,
    error: String(e).slice(0, 160),
  }));
  process.exit(3);
}

const DIR = cfg.dir || BASE;
const EGO_DIR = `${DIR}/_ego`;
const TOKEN_FILE = `${DIR}/_wx_token.json`;
const LOG_FILE = `${EGO_DIR}/pub_log.jsonl`;
const DONE_FILE = `${EGO_DIR}/pub_done.json`;
const RESULT_FILE = `${EGO_DIR}/pub_results.json`;
const QR_FILE = `${DIR}/login_qr_ego.png`;

const CMD = cfg.cmd || "status";
// 品牌名 / 会话名 / 署名优先取环境变量，脚本内不硬编码。
// ⚠️ 但走 ego-browser 通道时 env 根本拿不到（原因见文件头），真正生效的是
//    pub_jobs.json 里的 space / author；下面这几行的 env 只在直接 node 跑时有用。
const PLACEHOLDER_BRAND = "你的公众号";
const BRAND = process.env.WX_BRAND || PLACEHOLDER_BRAND;
const SPACE = process.env.WX_PUBLISH_SPACE || "公众号发布";
// 署名取值：pub_jobs.json 显式给了就用 —— **空串表示「有意不填作者」**；
// 没给（undefined）才退 WX_AUTHOR，再退品牌名。
// ⚠️ 不能写 `cfg.author || …`：空串是 falsy，会把「不填」吃成品牌名，且不报错。
const AUTHOR =
  typeof cfg.author === "string"
    ? cfg.author
    : process.env.WX_AUTHOR !== undefined
      ? process.env.WX_AUTHOR
      : BRAND;
const JOBS = Array.isArray(cfg.jobs) ? cfg.jobs : [];

await fs.mkdir(EGO_DIR, { recursive: true });

const emit = async (obj) => {
  const line = JSON.stringify(obj);
  await fs.appendFile(LOG_FILE, line + "\n");
  console.log(line);
};

const readJson = async (p, dflt) => {
  try { return JSON.parse(await fs.readFile(p, "utf8")); } catch { return dflt; }
};

const readToken = async () => {
  if (cfg.token) return String(cfg.token);
  const t = await readJson(TOKEN_FILE, null);
  return t && t.token ? String(t.token) : null;
};

// 自愈：把「本次真的读到配置的目录」记进指针，下次没有 env 也找得到。
// 只在指针不同时写，避免每次运行都去碰 $HOME。
{
  const cur = await readPointer();
  if (cur !== BASE) {
    const ok = await fs.writeFile(POINTER_FILE, `${BASE}\n`).then(() => true).catch(() => false);
    if (ok) {
      await emit({
        step: "pointer", file: POINTER_FILE, dir: BASE,
        note: "已记住配置目录，下次不必依赖 WX_DAILY_OUT",
      });
    }
  }
}

// 署名占位值告警：不写 author、又读不到 WX_AUTHOR / WX_BRAND 时，署名会写成
// 「你的公众号」。草稿照样保存成功、不报错，等人发现就晚了——所以这里主动喊一声。
if (CMD === "article" && AUTHOR === PLACEHOLDER_BRAND) {
  await emit({
    step: "warn", why: "author_placeholder", now: AUTHOR,
    hint: `ego-browser 读不到 WX_AUTHOR / WX_BRAND。请在 pub_jobs.json 写 "author": "你的笔名"；`
        + `确要有意不填就写 "author": ""`,
  });
}

const stripExt = (base) => base.replace(/_20\d{2}-\d{2}-\d{2}$/, "");

// ---------------------------------------------------------------------------
// 浏览器上下文：同一 TaskSpace 跨进程复用（ego 的浏览器常驻，不需要同进程续跑）
// ---------------------------------------------------------------------------
const task = await taskSpace(cfg.space || SPACE);
const page = task.page("p1");
const sleep = (ms) => page.waitForTimeout(ms);

const pageUrl = async () => {
  try { return (await page.url()) || ""; } catch { return ""; }
};

// 真实窗口尽量撑高：「编辑封面」弹窗的「确认」在 y≈935，窗口矮时坐标会落到视口外。
// Emulation.setDeviceMetricsOverride 只改视觉视口不改布局，必须改真实窗口。
// ⚠️ 窗口高度会被屏幕高度钳制（本机 1440×900 实测只能到 ~715），所以**不能只靠撑窗口**：
//    markBtn() 里还会逐级滚动祖先容器把按钮推进视口，这是最终保障。
const ensureWindow = async () => {
  try {
    const win = await page.cdp("Browser.getWindowForTarget", { targetId: page.targetId });
    await page.cdp("Browser.setWindowBounds", {
      windowId: win.windowId,
      bounds: { width: 1460, height: 1260, windowState: "normal" },
    });
    await sleep(800);
  } catch (e) {
    await emit({ step: "window", warn: String(e).slice(0, 120) });
  }
  return page.evaluate(() => ({ w: innerWidth, h: innerHeight }));
};

// ---------------------------------------------------------------------------
// 页面通用工具
// ---------------------------------------------------------------------------
const STATE = () =>
  page.evaluate(() => {
    const eds = [...document.querySelectorAll("[contenteditable]")];
    const body = eds.find((e) => (e.getAttribute("data-placeholder") || "").includes("正文")) || eds[2];
    const imgs = body ? [...body.querySelectorAll("img")] : [];
    const titleEl = document.querySelector("[data-placeholder='请在这里输入标题']");
    const pv = document.querySelector(".js_cover_preview_new");
    return {
      editors: eds.length,
      title: titleEl ? (titleEl.innerText || "").trim() : "",
      author: (document.querySelector("#author") || {}).value || "",
      desc: (document.querySelector("#js_description") || {}).value || "",
      bodyLen: body ? body.innerText.length : 0,
      bodyImgs: imgs.length,
      mmbiz: imgs.filter((x) => /mmbiz/.test(x.src || "")).length,
      coverBg: pv ? getComputedStyle(pv).backgroundImage : "",
    };
  });

const dialogText = () =>
  page.evaluate(() => {
    const out = [];
    document
      .querySelectorAll(".weui-desktop-dialog__bd,.weui-desktop-msg__bd,.weui-desktop-toast__content")
      .forEach((e) => {
        if (e.offsetParent === null) return;
        const t = (e.textContent || "").trim();
        if (t && t.length < 200) out.push(t);
      });
    return out.join(" || ") || "none";
  });

// 微信编辑器的引导弹窗（如「支持添加话题卡片」）会挡住焦点，先摘掉
const dismissModals = () =>
  page.evaluate(() => {
    let n = 0;
    document.querySelectorAll(".weui-desktop-dialog__bd,.weui-desktop-msg__bd").forEach((bd) => {
      if (!(bd.textContent || "").includes("话题卡片")) return;
      let node = bd;
      for (let i = 0; i < 8 && node.parentElement; i++) {
        node = node.parentElement;
        const cn = "" + (node.className || "");
        if (cn.includes("dialog__wrp") || cn.includes("mask")) break;
      }
      try { node.remove(); n++; } catch (e) {}
    });
    document.querySelectorAll(".weui-desktop-mask").forEach((m) => { try { m.remove(); n++; } catch (e) {} });
    return n;
  });

// 在可见弹窗（或全文档）里给目标按钮打标记并返回中心坐标；找不到返回 null
const markBtn = (labels, scope) =>
  page.evaluate(
    ({ labels, scope }) => {
      document.querySelectorAll("[data-ego-b]").forEach((n) => n.removeAttribute("data-ego-b"));
      const roots =
        scope === "dialog"
          ? [...document.querySelectorAll(".weui-desktop-dialog__wrp")].filter(
              (x) => x.getBoundingClientRect().width > 300,
            )
          : [document];
      const pool = roots.flatMap((d) => [...d.querySelectorAll("button")]);
      const btn = pool.filter((x) => {
        const t = (x.textContent || "").replace(/\s+/g, "");
        const r = x.getBoundingClientRect();
        return (
          labels.includes(t) &&
          r.width > 20 &&
          r.height > 10 &&
          !x.disabled &&
          !/disabled/.test("" + (x.className || "")) &&
          getComputedStyle(x).visibility !== "hidden"
        );
      })[0];
      if (!btn) return null;
      btn.setAttribute("data-ego-b", "1");
      // 逐级滚动，把按钮真正推进视口（窗口高度可能被屏幕高度钳制，不能只靠 setWindowBounds）
      btn.scrollIntoView({ block: "center" });
      for (let i = 0; i < 4; i++) {
        const r0 = btn.getBoundingClientRect();
        if (r0.top > 2 && r0.bottom < innerHeight - 2) break;
        let p = btn.parentElement;
        let sc = null;
        while (p && p !== document.body) {
          const s = getComputedStyle(p);
          if (/(auto|scroll)/.test(s.overflowY) && p.scrollHeight > p.clientHeight + 4) { sc = p; break; }
          p = p.parentElement;
        }
        if (!sc) break;
        sc.scrollTop += Math.round(r0.top - (innerHeight / 2 - r0.height / 2));
      }
      const r = btn.getBoundingClientRect();
      return {
        t: (btn.textContent || "").trim(),
        x: Math.round(r.x + r.width / 2),
        y: Math.round(r.y + r.height / 2),
        inView: r.top > 2 && r.bottom < innerHeight - 2,
      };
    },
    { labels, scope: scope || "doc" },
  );

// 真实鼠标点击（CDP Input，不受窗口前后台影响）；不在视口内则退回页内 click()
const clickMarked = async (info) => {
  if (!info) return "no-target";
  if (info.inView) {
    await page.mouse.click(info.x, info.y, { label: info.t || "click" });
    return "mouse";
  }
  await page.evaluate(() => {
    const b = document.querySelector("[data-ego-b]");
    if (b) b.click();
  });
  return "js";
};

const clickBtn = async (labels, scope) => clickMarked(await markBtn(labels, scope));

// ---------------------------------------------------------------------------
// 登录
// ---------------------------------------------------------------------------
const scanAccounts = () =>
  page.evaluate(() => {
    const rows = [...document.querySelectorAll("[class*=account],[class*=qrcode__list] li")].filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 120 && r.height > 24 && getComputedStyle(e).visibility !== "hidden";
    });
    const names = rows.map((e) => (e.innerText || "").replace(/\s+/g, " ").trim()).filter(Boolean);
    return [...new Set(names)].slice(0, 12);
  });

const qrDataUrl = () =>
  page.evaluate(() => {
    const img = document.querySelector(".login__type__container__scan__qrcode");
    if (!img || !img.naturalWidth) return null;
    const s = 4;
    const c = document.createElement("canvas");
    c.width = img.naturalWidth * s;
    c.height = img.naturalHeight * s;
    const ctx = c.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, 0, 0, c.width, c.height);
    return c.toDataURL("image/png");
  });

// 清掉既有登录态，逼出二维码。
//
// 为什么要主动清：ego 的浏览器由守护进程持有、cookie 跨 TaskSpace 共享，
// 只要之前登录过一次，`page.goto("https://mp.weixin.qq.com/")` 会**直接跳进后台**，
// 二维码根本不出现——于是「以为自己扫了码」，其实是复用了别人的登录态。
// 共用电脑、多人账号、或只是想确认「登录的确实是这个号」时，这是硬伤。
async function clearWxSession() {
  const done = [];
  // 先把当前页挪开，避免登录态留在内存里
  await page.goto("about:blank").catch(() => {});
  // ① 整源清理（cookies + 各类 storage 一起）
  try {
    await page.cdp("Storage.clearDataForOrigin", {
      origin: "https://mp.weixin.qq.com",
      storageTypes: "cookies,local_storage,session_storage,indexeddb,cache_storage,service_workers",
    });
    done.push("clearDataForOrigin");
  } catch {
    // ② 退而求其次：逐条删 cookie
    try {
      const { cookies } = await page.cdp("Network.getCookies", {
        urls: ["https://mp.weixin.qq.com", "https://mp.weixin.qq.com/"],
      });
      const list = cookies || [];
      for (const c of list) {
        await page.cdp("Network.deleteCookies", {
          name: c.name, domain: c.domain, path: c.path || "/",
        }).catch(() => {});
      }
      done.push(`deleteCookies×${list.length}`);
    } catch {
      // ③ 最后兜底：全清（会连带其他站点的 cookie，属于降级路径）
      try {
        await page.cdp("Network.clearBrowserCookies");
        done.push("clearBrowserCookies(降级)");
      } catch (e3) {
        await emit({ step: "warn", what: "清登录态失败，可能仍会复用旧登录", err: String(e3).slice(0, 140) });
      }
    }
  }
  // token 文件一并删，否则 readToken() 还会读回旧的
  await fs.unlink(TOKEN_FILE).catch(() => {});
  return done.join(" + ") || "none";
}

async function doLogin() {
  // 默认必须重新扫码。想复用登录态要显式写 "freshLogin": false（不推荐）。
  const FRESH = cfg.freshLogin !== false;
  if (FRESH) {
    const how = await clearWxSession();
    await emit({ step: "fresh_login", cleared: how, note: "已清除既有登录态，本次必须由使用者扫码" });
  }

  await page.goto("https://mp.weixin.qq.com/", { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});
  await sleep(3000);

  // 默认可能是「账号密码」形态，需切到扫码；已是扫码形态则不动
  const linkText = await page.evaluate(() => {
    const a = document.querySelector("a.login__type__container__link_text");
    return a ? a.textContent.trim() : "none";
  });
  if (linkText.includes("扫码登录")) {
    await page.evaluate(() => {
      const a = document.querySelector("a.login__type__container__link_text");
      if (a) a.click();
    });
    await sleep(1800);
  }
  await emit({ step: "login", linkText });

  await page
    .waitForFunction(() => !!document.querySelector(".login__type__container__scan__qrcode"), undefined, { timeout: 25000 })
    .catch(() => {});
  await sleep(1200);

  const durl = await qrDataUrl();
  if (durl) {
    await fs.writeFile(QR_FILE, Buffer.from(durl.split(",")[1], "base64"));
    await emit({ step: "qr", file: QR_FILE, how: "canvas" });
  } else {
    await page.screenshot({ path: QR_FILE }).catch(() => {});
    await emit({ step: "qr", file: QR_FILE, how: "screenshot" });
  }

  const limit = (cfg.loginTimeout || 300) * 1000;
  const t0 = Date.now();
  let askedAccounts = false;
  while (Date.now() - t0 < limit) {
    const u = await pageUrl();
    const m = u.match(/[?&]token=(\d+)/);
    if (m) {
      // via 记录「这个 token 是不是本次扫码换来的」。cmd=article 会校验它，
      // 所以不能只写 token 和时间——否则没法区分「刚扫的」和「祖传登录态」。
      await fs.writeFile(
        TOKEN_FILE,
        JSON.stringify({ token: m[1], at: new Date().toISOString(), via: FRESH ? "qr" : "reuse", space: cfg.space || SPACE }),
      );
      await emit({ step: "login_ok", token: m[1], via: FRESH ? "qr" : "reuse", url: u.slice(0, 120) });
      return m[1];
    }
    // 多账号页：立即停下，把账号清单交给用户，绝不代选
    if (!askedAccounts && Date.now() - t0 > 15000) {
      const accs = await scanAccounts();
      if (accs.length >= 2) {
        askedAccounts = true;
        await emit({ step: "multi_account", accounts: accs, note: "必须由用户亲自选择账号，AI 不得代选" });
        return "MULTI_ACCOUNT";
      }
    }
    const expired = await page.evaluate(() => (document.body.innerText || "").includes("二维码已失效"));
    if (expired) {
      await emit({ step: "qr_expired", repost: true });
      return "QR_EXPIRED";
    }
    await sleep(3000);
  }
  await emit({ step: "login_timeout", seconds: (cfg.loginTimeout || 300) });
  return null;
}

// ---------------------------------------------------------------------------
// 编辑器
// ---------------------------------------------------------------------------
async function openEditor(token, appmsgid) {
  const head =
    "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=10&isMul=0&lang=zh_CN";
  const url = appmsgid ? `${head}&token=${token}&appmsgid=${appmsgid}` : `${head}&isNew=1&token=${token}`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});
  await page
    .waitForFunction(() => document.querySelectorAll("[contenteditable]").length >= 3, undefined, { timeout: 60000 })
    .catch(() => {});
  await sleep(1500);
  await dismissModals();
  const st = await STATE();
  return { ok: st.editors >= 3, url: await pageUrl(), state: st };
}

// 标题：点进去用真实键盘输入（JS 写 textContent 微信编辑器不采纳）
async function fillTitle(title) {
  await dismissModals();
  const marked = await page.evaluate(() => {
    const t = [...document.querySelectorAll("[data-placeholder='请在这里输入标题']")].find(
      (e) => e.offsetParent !== null,
    );
    if (!t) return false;
    t.setAttribute("data-ego-title", "1");
    return true;
  });
  if (!marked) return { ok: false, why: "no-title-el" };

  await page.click("[data-ego-title='1']");
  await sleep(400);
  await page.keyboard.type(title);
  await sleep(700);

  const read = () =>
    page.evaluate(() => (document.querySelector("[data-ego-title='1']") || {}).innerText || "");
  let cur = await read();
  if (!cur.includes(title.slice(0, 6))) {
    await page.keyboard.paste(title);
    await sleep(700);
    cur = await read();
  }
  if (!cur.includes(title.slice(0, 6))) {
    await page.keyboard.insertText(title);
    await sleep(700);
    cur = await read();
  }
  return { ok: cur.includes(title.slice(0, 6)), now: cur.slice(0, 40) };
}

async function fillAuthor(author) {
  try {
    await page.fill("#author", author);
  } catch (e) {
    await page.click("#author").catch(() => {});
    await page.keyboard.press("ControlOrMeta+a").catch(() => {});
    await page.keyboard.type(author);
  }
  await sleep(400);
  const now = await page.evaluate(() => (document.querySelector("#author") || {}).value || "");
  return { ok: now.trim() === author.trim(), now };
}

// 正文：base64 分块塞进页面变量，再用「合成 paste 事件」注入（绕开系统剪贴板）
async function pasteHtml(htmlPath) {
  const html = await fs.readFile(htmlPath, "utf8");
  const b64 = Buffer.from(html, "utf8").toString("base64");
  await page.evaluate(() => { window.__b64 = ""; });
  for (let i = 0; i < b64.length; i += 400000) {
    const chunk = b64.slice(i, i + 400000);
    await page.evaluate((x) => { window.__b64 += x; }, chunk);
  }
  const res = await page.evaluate(() => {
    const bin = atob(window.__b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const h = new TextDecoder("utf-8").decode(bytes);
    const plain = h.replace(/<[^>]+>/g, " ");
    const eds = [...document.querySelectorAll("[contenteditable]")];
    const body = eds.find((e) => (e.getAttribute("data-placeholder") || "").includes("正文")) || eds[2];
    if (!body) return { ok: false, why: "no-body-el" };
    body.focus();
    const dt = new DataTransfer();
    dt.setData("text/html", h);
    dt.setData("text/plain", plain);
    const ev = new Event("paste", { bubbles: true, cancelable: true });
    ev.clipboardData = dt;
    body.dispatchEvent(ev);
    return { ok: true, len: h.length };
  });
  await sleep(2000);
  return res;
}

const htmlImgCount = async (htmlPath) => {
  const h = await fs.readFile(htmlPath, "utf8");
  return h.toLowerCase().split("<img").length - 1;
};

// 摘要：取正文第 2 段，剥掉 Markdown 记号（旧实现会把 ** 原样带进摘要）
async function makeSummary(mdPath, maxlen = 120) {
  const md = await fs.readFile(mdPath, "utf8");
  const paras = md
    .split(/\n{2,}/)
    .map((s) => s.trim())
    .filter((s) => s && !/^[#|>\-*]/.test(s));
  let s = paras[1] || paras[0] || "";
  s = s
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_~`#]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return s.slice(0, maxlen);
}

async function fillSummary(text) {
  if (!text) return { ok: false, why: "empty" };
  try {
    await page.fill("#js_description", text);
  } catch (e) {
    await page.click("#js_description").catch(() => {});
    await page.keyboard.press("ControlOrMeta+a").catch(() => {});
    await page.keyboard.type(text);
  }
  await sleep(400);
  const now = await page.evaluate(() => (document.querySelector("#js_description") || {}).value || "");
  return { ok: now.trim().length > 0, now };
}

// 等正文图片从 data-URI 转存为 mmbiz CDN（5MB 级长图实测 60s+，超时会直接存不上）
async function waitImages(expect, timeoutSec) {
  const limit = Date.now() + timeoutSec * 1000;
  let st = await STATE();
  while (Date.now() < limit) {
    if (st.mmbiz >= expect && st.mmbiz >= st.bodyImgs) return st;
    await sleep(2000);
    st = await STATE();
  }
  return st;
}

// ---------------------------------------------------------------------------
// 封面：图片库上传 → 选中缩略图 → 下一步 → 确认
// 判据只用 .js_cover_preview_new 的 background-image 是否含 mmbiz
// （「拖拽或选择封面」遮罩永远在 DOM 里，用它判断会误报）
// ---------------------------------------------------------------------------
const coverOk = async () => /mmbiz/.test(await page.evaluate(() => {
  const pv = document.querySelector(".js_cover_preview_new");
  return pv ? getComputedStyle(pv).backgroundImage : "";
}));

const pickerWidth = () =>
  page.evaluate(() => {
    const d = document.querySelector(".weui-desktop-dialog__wrp.weui-desktop-dialog_img-picker");
    return d ? Math.round(d.getBoundingClientRect().width) : 0;
  });

const pickerItems = () =>
  page.evaluate(() =>
    [...document.querySelectorAll(".weui-desktop-img-picker__item")].map((it, k) => {
      const r = it.getBoundingClientRect();
      return { k, sel: /selected/.test("" + it.className), txt: (it.textContent || "").trim().slice(0, 60), w: Math.round(r.width) };
    }),
  );

async function openImageLibrary() {
  // 直接点 a.js_imagedialog；不要去 hover .js_cover_btn_area 再点 .pop-opr__item
  // （那个悬浮菜单是 visibility:hidden，elementFromPoint 会命中背后的摘要框）
  const opened = await page.evaluate(() => {
    const a = document.querySelector("a.js_imagedialog");
    if (!a) return false;
    a.click();
    return true;
  });
  if (!opened) return false;
  await page
    .waitForFunction(() => document.querySelectorAll(".weui-desktop-img-picker__item").length > 0, undefined, {
      timeout: 20000,
    })
    .catch(() => {});
  await sleep(1500);
  return (await pickerWidth()) > 300;
}

async function uploadCover(coverPath) {
  const fileSel = ".weui-desktop-dialog_img-picker input[type=file]";
  try {
    await page.setInputFiles(fileSel, coverPath);
    await sleep(1500);
    return "input";
  } catch (e) {
    // 退回「上传文件」按钮 + 原生文件选择框
    const r = await page.evaluate(() => {
      const d = [...document.querySelectorAll(".weui-desktop-dialog__wrp")].filter(
        (x) => x.getBoundingClientRect().width > 300,
      )[0];
      if (!d) return null;
      const s = [...d.querySelectorAll("span,div,a,button")].filter((x) => {
        const t = (x.textContent || "").trim();
        const b = x.getBoundingClientRect();
        return (t === "上传文件" || t === "上传图片") && b.width > 20 && b.height > 12;
      })[0];
      if (!s) return null;
      const b = s.getBoundingClientRect();
      return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) };
    });
    if (!r) return "no-upload-btn";
    const chooser = page.waitForFileChooser({ timeout: 25000 });
    await page.mouse.click(r.x, r.y, { label: "上传封面图" });
    const ch = await chooser;
    await ch.setFiles(coverPath);
    await sleep(1500);
    return "chooser";
  }
}

async function setCover(base, coverPath, force) {
  // force=true：已有封面也重设。用于"封面存在但不是设计稿"（被微信首图顶替）的场景——
  // 那种情况 coverOk() 为 true，不加 force 会直接跳过、永远修不好。
  if (!force && (await coverOk())) return { ok: true, why: "already" };
  if (!(await openImageLibrary())) return { ok: false, why: "library_not_open" };

  const want = `${base}_封面.png`;
  const findIdx = () =>
    page.evaluate((w) => [...document.querySelectorAll(".weui-desktop-img-picker__item")].findIndex(
      (it) => (it.textContent || "").includes(w),
    ), want);

  let idx = await findIdx();
  let how = "existing";
  if (idx < 0) {
    how = await uploadCover(coverPath);
    for (let i = 0; i < 30; i++) {
      await sleep(1500);
      idx = await findIdx().catch(() => -1);
      if (idx >= 0) break;
    }
  }
  if (idx < 0) return { ok: false, why: "item_not_found", how };

  // 清掉其它项的选中，但绝不动目标项（新上传的图会自动选中，再点一次就是反选）
  await page.evaluate((i) => {
    const items = [...document.querySelectorAll(".weui-desktop-img-picker__item")];
    items.forEach((n, k) => {
      if (/selected/.test("" + n.className) && k !== i) {
        const b = n.getBoundingClientRect();
        n.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: b.x + 5, clientY: b.y + 5 }));
      }
    });
    if (items[i]) items[i].scrollIntoView({ block: "center" });
  }, idx);
  await sleep(900);

  const targetSel = () =>
    page.evaluate((i) => {
      const it = [...document.querySelectorAll(".weui-desktop-img-picker__item")][i];
      return it ? /selected/.test("" + it.className) : false;
    }, idx);

  if (!(await targetSel())) {
    const r = await page.evaluate((i) => {
      const it = [...document.querySelectorAll(".weui-desktop-img-picker__item")][i];
      if (!it) return null;
      const b = it.getBoundingClientRect();
      return {
        x: Math.round(b.x + b.width / 2),
        y: Math.round(b.y + b.height / 2),
        inView: b.top > 0 && b.bottom < innerHeight,
      };
    }, idx);
    if (r && r.inView) {
      await page.mouse.click(r.x, r.y, { label: "选中封面图" });
      await sleep(1200);
    }
    if (!(await targetSel())) {
      await page.evaluate((i) => {
        const it = [...document.querySelectorAll(".weui-desktop-img-picker__item")][i];
        const b = it.getBoundingClientRect();
        it.dispatchEvent(
          new MouseEvent("click", { bubbles: true, clientX: b.x + b.width / 2, clientY: b.y + b.height / 2 }),
        );
      }, idx);
      await sleep(1200);
    }
  }
  if (!(await targetSel())) return { ok: false, why: "not_selected", how, idx };

  // 下一步（未选中图片时该按钮带 _disabled，点不动）
  const next = await clickBtn(["下一步"], "dialog");
  if (next === "no-target") return { ok: false, why: "next_disabled", how };
  await sleep(4500);

  // 裁剪弹窗「确认」
  let clicked = "no-target";
  for (let i = 0; i < 4; i++) {
    clicked = await clickBtn(["确认", "完成"], "dialog");
    if (clicked !== "no-target") break;
    await sleep(2000);
  }
  await sleep(4500);

  const ok = await coverOk();
  return { ok, why: ok ? "ok" : "confirm_no_effect", how, idx, next, confirm: clicked };
}

// ---------------------------------------------------------------------------
// 保存草稿
// ---------------------------------------------------------------------------
async function saveDraft(appmsgid) {
  const before = await pageUrl();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await sleep(800);

  let how = await clickBtn(["保存为草稿"]);
  if (how === "no-target") {
    // 兜底：直接点文案匹配的按钮
    await page.evaluate(() => {
      const c = [...document.querySelectorAll("button")].filter(
        (b) => (b.textContent || "").replace(/\s+/g, "") === "保存为草稿" && b.getBoundingClientRect().width > 20,
      );
      if (c.length) c[c.length - 1].click();
    });
    how = "js-text";
  }

  let url = "";
  for (let i = 0; i < 25; i++) {
    await sleep(1000);
    url = await pageUrl();
    if (!appmsgid && /appmsgid=\d+/.test(url)) break;
    if (appmsgid) {
      const toast = await page.evaluate(() => {
        const t = [...document.querySelectorAll(".weui-desktop-toast__content")].map((e) => (e.textContent || "").trim());
        return t.join("|");
      });
      if (/成功|已保存/.test(toast)) break;
    }
  }
  const m = url.match(/appmsgid=(\d+)/);
  const id = m ? m[1] : appmsgid || null;
  const changed = url !== before;
  return { ok: !!id && (id !== appmsgid ? changed || true : true), appmsgid: id, url, how, changed };
}

// ---------------------------------------------------------------------------
// 命令
// ---------------------------------------------------------------------------
const done = await readJson(DONE_FILE, {});
const results = await readJson(RESULT_FILE, {});

async function cmdArticle() {
  const token = await readToken();
  if (!token) {
    await emit({ step: "abort", why: "no_token", hint: "先跑 cmd=login" });
    return;
  }

  // 上传闸门：必须是**本次扫码**换来的 token，且没过期。
  //
  // 为什么卡这一道：ego 的登录态跨进程共享，`_wx_token.json` 里的 token 可能是
  // 几天前甚至别人（共用电脑）留下的。复用它的后果是「稿子进了不是你的号」，
  // 而这一步不会有任何报错——草稿真的保存成功了，只是账号不对。
  // requireFreshLogin 默认开；确需复用要显式写 false，并在文档里说清风险。
  if (cfg.requireFreshLogin !== false) {
    const FRESH_MIN = Number.isFinite(cfg.freshMinutes) ? cfg.freshMinutes : 10;
    const rec = await readJson(TOKEN_FILE, null);
    const at = rec && rec.at ? Date.parse(rec.at) : 0;
    const ageMin = at ? (Date.now() - at) / 60000 : Infinity;
    const why = !rec
      ? "没有登录记录"
      : rec.via !== "qr"
        ? `这份 token 不是扫码换来的（via=${rec.via || "unknown"}），可能是复用历史登录态`
        : ageMin > FRESH_MIN
          ? `登录已过去 ${ageMin.toFixed(1)} 分钟，超过 ${FRESH_MIN} 分钟`
          : "";
    if (why) {
      await emit({
        step: "need_login",
        why,
        hint: `先跑 cmd=login 让使用者扫码（默认会清掉旧登录态强制出新码），再跑 cmd=article。`
            + `确需复用登录态：在 pub_jobs.json 里写 "requireFreshLogin": false`,
      });
      process.exit(2);
    }
  }

  await emit({ step: "start", cmd: "article", jobs: JOBS.length, token, window: await ensureWindow() });

  // 失败计数分两个：fails 累计（给 done 汇总）、streak 连续（给停机判断）。
  // 只有「连续」才说明环境坏了；用累计会把两处孤立故障误判成系统性故障。
  let fails = 0;
  let streak = 0;
  let halted = 0;
  // haltAfter：连续失败多少篇停机。0 或负数＝不停机（Q30 选项 2）。默认 2。
  const HALT_AFTER = Number.isFinite(cfg.haltAfter) ? cfg.haltAfter : 2;

  for (const job of JOBS) {
    const base = job.base;
    const rec = { base, at: new Date().toISOString() };
    if (cfg.resume !== false && done[base]) {
      await emit({ step: "skip", base, reason: "done" });
      continue;
    }

    let okThis = false;
    try {
      const htmlPath = `${DIR}/${base}_推文.html`;
      const mdPath = `${DIR}/${base}.md`;
      const coverPath = `${DIR}/${base}_封面.png`;
      await fs.access(htmlPath); // 缺正文直接失败，别走进死胡同

      const ed = await openEditor(token, job.appmsgid || null);
      if (!ed.ok) {
        rec.status = "no_editor";
        await emit({ step: "fail", ...rec });
      } else {
        rec.title = await fillTitle(stripExt(base));
        rec.author = await fillAuthor(AUTHOR);
        rec.paste = await pasteHtml(htmlPath);
        await sleep(1500);

        const imgs = await htmlImgCount(htmlPath);
        if (imgs > 0) {
          const st = await waitImages(1, cfg.imageTimeout || 120);
          rec.images = { expect: imgs, bodyImgs: st.bodyImgs, mmbiz: st.mmbiz };
        }

        if (await fs.access(mdPath).then(() => true).catch(() => false)) {
          const sum = await makeSummary(mdPath);
          rec.summary = await fillSummary(sum);
        }

        if (cfg.cover !== false && (await fs.access(coverPath).then(() => true).catch(() => false))) {
          rec.cover = await setCover(base, coverPath, cfg.forceCover === true);
        }

        const sv = await saveDraft(job.appmsgid || null);
        rec.save = sv;
        rec.state = await STATE();
        rec.status = sv.appmsgid && rec.title.ok !== false && (rec.paste.ok !== false) ? "success" : "check";
        okThis = rec.status === "success";

        if (okThis) {
          done[base] = { appmsgid: sv.appmsgid, at: rec.at };
          results[base] = { appmsgid: sv.appmsgid, coverOk: !!(rec.cover && rec.cover.ok), at: rec.at };
          await fs.writeFile(DONE_FILE, JSON.stringify(done, null, 1));
          await fs.writeFile(RESULT_FILE, JSON.stringify(results, null, 1));
        }
        await emit({ step: "article", ...rec });
      }
    } catch (e) {
      await emit({ step: "error", base, error: String(e).slice(0, 200), dialogs: await dialogText().catch(() => "") });
    }

    // 计数与停机判定收在**唯一出口**：原来 no_editor 分支里的 `continue` 会跳过停机检查，
    // 而「打不开编辑器」恰恰是最典型的环境故障——最该停的那条路反而永远不停。
    if (okThis) {
      streak = 0;
    } else {
      fails++;
      streak++;
    }
    if (HALT_AFTER > 0 && streak >= HALT_AFTER) {
      halted = streak;
      await emit({ step: "halt", why: `连续 ${streak} 篇失败，停止并交用户确认`,
                   hint: "排查环境后重跑；resume=true 会跳过已成功的篇目，不会重复存草稿" });
      break;
    }
  }
  await emit({ step: "done", cmd: "article", fails, streak, halted, haltAfter: HALT_AFTER });
}

async function cmdCover() {
  const token = await readToken();
  if (!token) return emit({ step: "abort", why: "no_token" });
  await emit({ step: "start", cmd: "cover", jobs: JOBS.length, window: await ensureWindow() });

  let fails = 0;
  for (const job of JOBS) {
    const id = job.appmsgid || (results[job.base] && results[job.base].appmsgid);
    if (!id) {
      await emit({ step: "fail", base: job.base, why: "no_appmsgid" });
      fails++;
      continue;
    }
    try {
      const ed = await openEditor(token, id);
      if (!ed.ok) { await emit({ step: "fail", base: job.base, why: "no_editor" }); fails++; continue; }
      // cmd=cover 的语义就是"把封面改对"，默认强制重设（cfg.forceCover=false 可关）
      const r = await setCover(job.base, `${DIR}/${job.base}_封面.png`, cfg.forceCover !== false);
      const sv = await saveDraft(id);
      results[job.base] = { appmsgid: id, coverOk: r.ok, at: new Date().toISOString() };
      await fs.writeFile(RESULT_FILE, JSON.stringify(results, null, 1));
      await emit({ step: "cover", base: job.base, appmsgid: id, ...r, saved: sv.how });
      if (!r.ok) fails++;
    } catch (e) {
      fails++;
      await emit({ step: "error", base: job.base, error: String(e).slice(0, 200) });
    }
  }
  await emit({ step: "done", cmd: "cover", fails });
}

// 统一署名：改「作者」字段 + 清洗正文里遗留的旧品牌名，再重存草稿（只动文本节点，不碰结构样式）
// 注意：LEGACY_BRANDS 是「待清洗词表」——故意保留历史写法，才能匹配到并替换成现用品牌名；
// 它不是本号署名。本号署名见 SKILL.md 铁律「作者固定填品牌名」。
// 词表用环境变量 WX_LEGACY_BRANDS 提供（逗号分隔），留空则跳过清洗。
const LEGACY_BRANDS = (process.env.WX_LEGACY_BRANDS || "")
  .split(",").map((x) => x.trim()).filter(Boolean);

const bodyEl = () =>
  page.evaluate((olds) => {
    const eds = [...document.querySelectorAll("[contenteditable]")];
    const body = eds.find((e) => (e.getAttribute("data-placeholder") || "").includes("正文")) || eds[2];
    if (!body) return { replaced: 0, hits: [], left: [] };
    // 长串优先：先换「旧名+文化」，再换「旧名」，否则会被截成「品牌名+文化」
    const sorted = [...olds].sort((a, b) => b.length - a.length);
    const w = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null);
    const nodes = [];
    while (w.nextNode()) nodes.push(w.currentNode);
    let n = 0;
    const hits = new Set();
    for (const node of nodes) {
      let t = node.nodeValue;
      let touched = false;
      for (const o of sorted) {
        if (t.includes(o)) {
          hits.add(o);
          t = t.split(o).join(BRAND);
          touched = true;
        }
      }
      if (touched) {
        node.nodeValue = t;
        n++;
      }
    }
    return { replaced: n, hits: [...hits], left: [] };
  }, LEGACY_BRANDS);

const brandLeft = () =>
  page.evaluate((olds) => {
    const eds = [...document.querySelectorAll("[contenteditable]")];
    const body = eds.find((e) => (e.getAttribute("data-placeholder") || "").includes("正文")) || eds[2];
    const t = body ? body.innerText : "";
    return olds.filter((o) => t.includes(o));
  }, LEGACY_BRANDS);

async function cmdAuthor() {
  const token = await readToken();
  if (!token) return emit({ step: "abort", why: "no_token" });
  const target = AUTHOR;
  await emit({ step: "start", cmd: "author", author: target, jobs: JOBS.length, brandFix: cfg.brandFix !== false });

  let fails = 0;
  for (const job of JOBS) {
    const id = job.appmsgid || (results[job.base] && results[job.base].appmsgid);
    if (!id) { await emit({ step: "fail", base: job.base, why: "no_appmsgid" }); fails++; continue; }
    try {
      const ed = await openEditor(token, id);
      if (!ed.ok) { await emit({ step: "fail", base: job.base, why: "no_editor" }); fails++; continue; }

      const au = await fillAuthor(target);
      const brand = cfg.brandFix === false ? { replaced: 0, hits: [] } : await bodyEl();
      const sv = await saveDraft(id);
      const st = await STATE();
      const left = await brandLeft();
      const ok = au.ok && left.length === 0;
      await emit({
        step: "author",
        base: job.base,
        appmsgid: id,
        author: au.now,
        authorOk: au.ok,
        brandReplaced: brand.replaced,
        brandHits: brand.hits,
        brandLeft: left,
        saved: sv.how,
        status: ok ? "ok" : "check",
      });
      if (!ok) fails++;
    } catch (e) {
      fails++;
      await emit({ step: "error", base: job.base, error: String(e).slice(0, 200) });
    }
  }
  await emit({ step: "done", cmd: "author", fails });
}

// 核验：逐篇冷加载编辑页，取服务端封面图并落盘，供色彩判定与肉眼确认
async function cmdVerify() {
  const token = await readToken();
  if (!token) return emit({ step: "abort", why: "no_token" });
  const outDir = `${EGO_DIR}/verify`;
  await fs.mkdir(outDir, { recursive: true });
  await emit({ step: "start", cmd: "verify", jobs: JOBS.length });

  const rows = [];
  for (const job of JOBS) {
    const id = job.appmsgid || (results[job.base] && results[job.base].appmsgid);
    if (!id) { rows.push({ base: job.base, status: "no_appmsgid" }); continue; }
    try {
      const ed = await openEditor(token, id);
      const st = await STATE();
      const m = (st.coverBg || "").match(/url\("?([^")]+)"?\)/);
      const src = m ? m[1] : "";
      let file = null;
      if (/mmbiz/.test(src)) {
        file = `${outDir}/${job.base}_cover_server.png`;
        await page.fetch(src, { saveAs: file }).catch(() => { file = null; });
      }
      rows.push({
        base: job.base,
        appmsgid: id,
        editors: st.editors,
        title: st.title.slice(0, 30),
        bodyLen: st.bodyLen,
        mmbiz: st.mmbiz,
        descLen: st.desc.length,
        coverOk: /mmbiz/.test(st.coverBg),
        coverSrc: src.slice(0, 90),
        coverFile: file,
      });
    } catch (e) {
      rows.push({ base: job.base, status: "error", error: String(e).slice(0, 160) });
    }
    await emit({ step: "verify", ...rows[rows.length - 1] });
  }
  await fs.writeFile(`${EGO_DIR}/verify_report.json`, JSON.stringify(rows, null, 1));
  await emit({ step: "done", cmd: "verify", file: `${EGO_DIR}/verify_report.json`, rows: rows.length });
}

async function cmdStatus() {
  const u = await pageUrl();
  const st = u.includes("mp.weixin.qq.com") ? await STATE().catch(() => null) : null;
  // 把登录态的「来源与新鲜度」一并报出来：只报 token 看不出是不是复用来的。
  const rec = await readJson(TOKEN_FILE, null);
  const login = rec
    ? {
        via: rec.via || "unknown",
        at: rec.at || null,
        ageMin: rec.at ? Number(((Date.now() - Date.parse(rec.at)) / 60000).toFixed(1)) : null,
        fresh: rec.via === "qr" && rec.at && (Date.now() - Date.parse(rec.at)) <= (Number.isFinite(cfg.freshMinutes) ? cfg.freshMinutes : 10) * 60000,
      }
    : null;
  await emit({ step: "status", url: u, state: st, dialogs: await dialogText().catch(() => "") , token: await readToken(), login });
}

async function cmdClose() {
  // ego 的浏览器由守护进程管理，不需要杀进程或清会话文件；
  // 这里只做归档，并保留页面以便下次沿用登录态。
  const u = await pageUrl();
  const token = await readToken();
  await emit({ step: "close", url: u.slice(0, 100), token, note: "页面保留以供下次复用登录态" });
  try { await task.finish({ keep: true }); } catch (e) {}
}

if (CMD === "login") {
  const t = await doLogin();
  if (t === "MULTI_ACCOUNT") await emit({ step: "need_user", why: "multi_account" });
  else if (t === "QR_EXPIRED") await emit({ step: "need_user", why: "qr_expired" });
} else if (CMD === "article") {
  await cmdArticle();
} else if (CMD === "cover") {
  await cmdCover();
} else if (CMD === "author") {
  await cmdAuthor();
} else if (CMD === "verify") {
  await cmdVerify();
} else if (CMD === "close") {
  await cmdClose();
} else {
  await cmdStatus();
}
