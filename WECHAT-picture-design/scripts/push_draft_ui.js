// push_draft_ui.js — 无 API 凭证时，用已登录的浏览器把贴图写入公众号草稿箱
// 由 scripts/push_ui.py 调用：ego-browser nodejs < push_draft_ui.js
// 入参从 /tmp/xh_push_payload.json 读取（ego 运行时拿不到环境变量，只能走文件）
//   { mode:"create"|"list", space_id, token?, title, paras[], files[], note }
//
// 血泪教训（都在这个文件里被硬编码修掉了）：
//   1. 编辑器标题旁的 "8/20" 是标题字数上限，不是图片张数，别拿它判断上传结果
//   2. 必须等缩略图变成 mmbiz 服务端地址才能保存，否则草稿会存成「有文案、无图」
//   3. 保存后绝对不要再打开这篇草稿做校验：贴图编辑器有自动保存，
//      内容没加载完打开=把空状态写回去，会把标题和正文清空
//   4. 缩略图是 background-image，不是 <img>，用 img 选择器会永远数到 0
//   5. 空态是「选择或拖拽图片」拖拽框，已有图时是缩略图条末尾的 +，坐标必须动态取

const fs = await import("node:fs");
const D = JSON.parse(fs.readFileSync("/tmp/xh_push_payload.json", "utf8"));

const t = await claimTaskSpace(D.space_id || 2);
const p = await t.newPage();

async function clickAt(x, y) {
  await p.cdp("Input.dispatchMouseEvent", {type: "mouseMoved", x, y});
  await p.cdp("Input.dispatchMouseEvent", {type: "mousePressed", x, y, button: "left", clickCount: 1});
  await p.cdp("Input.dispatchMouseEvent", {type: "mouseReleased", x, y, button: "left", clickCount: 1});
}

async function token() {
  if (D.token) return D.token;
  await p.goto("https://mp.weixin.qq.com/", {timeout: 45000});
  await p.waitForTimeout(3000);
  const tk = await p.evaluate(() => {
    const m = (location.href + " " + [...document.querySelectorAll("a")].map(a => a.getAttribute("href") || "").join(" "))
      .match(/token=(\d+)/);
    return m ? m[1] : null;
  });
  if (!tk) throw new Error("未登录或拿不到 token，请先在浏览器里登录公众号后台");
  return tk;
}

// 缩略图（服务端 mmbiz 地址）数量
async function thumbs() {
  return await p.evaluate(() => {
    let n = 0;
    document.querySelectorAll("*").forEach(e => {
      const bg = getComputedStyle(e).backgroundImage || "";
      if (!bg.includes("mmbiz")) return;
      const b = e.getBoundingClientRect();
      if (b.width > 0 && b.width <= 70 && b.height <= 70) n++;
    });
    return n;
  });
}

async function listDrafts(tk) {
  const u = "https://mp.weixin.qq.com/cgi-bin/appmsg?begin=0&count=50&t=media/appmsg_list&type=77"
    + "&action=list_ex&token=" + tk + "&lang=zh_CN&is_draft=1&_=" + Date.now();
  await p.goto(u, {timeout: 45000});
  await p.waitForTimeout(5000);
  const raw = await p.evaluate(() => document.body.innerText);
  const d = JSON.parse(raw.slice(raw.indexOf("{")));
  return (d.app_msg_list || []).filter(x => x.item_show_type === 8)
    .map(x => ({id: x.appmsgid, title: (x.title || "").trim(), cover: !!x.cover, digest_len: (x.digest || "").length}));
}

async function create(tk) {
  await p.goto("https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1"
    + "&type=77&createType=8&token=" + tk + "&lang=zh_CN", {timeout: 45000});
  await p.waitForTimeout(7000);

  // 1) 打开上传菜单（动态定位添加图块）
  const add = await p.evaluate(() => {
    let el = document.querySelector(".image-selector__add");
    if (el && el.offsetParent) {
      const b = el.getBoundingClientRect();
      return {x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2)};
    }
    el = [...document.querySelectorAll("div,span")].find(e => {
      if (!e.offsetParent) return false;
      const b = e.getBoundingClientRect();
      return (e.innerText || "").trim().startsWith("选择或拖拽图片") && b.width < 220 && b.height < 220;
    });
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return {x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2)};
  });
  if (!add) throw new Error("找不到添加图片入口");
  await clickAt(add.x, add.y);
  await p.waitForTimeout(1800);

  // 2) 本地上传 → 原生文件选择器
  const item = await p.evaluate(() => {
    const el = [...document.querySelectorAll("a,div,span")].find(e => (e.innerText || "").trim() === "本地上传" && e.offsetParent);
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return {x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2)};
  });
  if (!item) throw new Error("上传菜单未出现");
  const cp = p.waitForFileChooser({timeout: 12000});
  await clickAt(item.x, item.y);
  const chooser = await cp;
  await chooser.setFiles(D.files);
  console.log("UPLOAD_SENT");

  // 3) 等图片真正落到服务端
  let n = 0;
  for (let i = 0; i < 25; i++) {
    await p.waitForTimeout(4000);
    n = await thumbs();
    if (n >= D.files.length) break;
  }
  console.log("THUMBS=" + n);
  if (n < D.files.length) throw new Error("上传未完成：仅 " + n + "/" + D.files.length + " 张");
  await p.waitForTimeout(4000);

  // 4) 标题（contenteditable，非 input）
  await p.evaluate(() => {
    const el = document.querySelector('.ProseMirror[data-placeholder="请在这里输入标题"]');
    if (el) el.focus();
  });
  await p.keyboard.insertText(D.title);
  await p.waitForTimeout(800);

  // 5) 描述正文：逐段输入 + 空行（insertText 会吞掉换行）
  await p.evaluate(() => {
    const list = [...document.querySelectorAll(".ProseMirror")].filter(e => !e.getAttribute("data-placeholder"));
    if (list[0]) list[0].focus();
  });
  for (let i = 0; i < D.paras.length; i++) {
    await p.keyboard.insertText(D.paras[i]);
    if (i < D.paras.length - 1) { await p.keyboard.press("Enter"); await p.keyboard.press("Enter"); }
    await p.waitForTimeout(160);
  }
  await p.waitForTimeout(1500);

  // 6) 保存
  const save = await p.evaluate(() => {
    const el = [...document.querySelectorAll("a,button,div,span")].reverse()
      .find(e => (e.innerText || "").trim() === "保存为草稿" && e.offsetParent);
    if (!el) return null;
    el.scrollIntoView({block: "center"});
    const b = el.getBoundingClientRect();
    return {x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2)};
  });
  if (!save) throw new Error("找不到保存为草稿按钮");
  await clickAt(save.x, save.y);
  await p.waitForTimeout(9000);

  const url = await p.evaluate(() => location.href);
  const m = url.match(/appmsgid=(\d+)/);
  console.log("SAVED id=" + (m ? m[1] : "none"));
  // 保存后直接收工：不要 reopen 校验（会触发自动保存覆盖）
  return m ? m[1] : null;
}

try {
  const tk = await token();
  if (D.mode === "list") {
    const rows = await listDrafts(tk);
    console.log("LIST " + JSON.stringify(rows));
  } else {
    const id = await create(tk);
    console.log("DONE " + D.note + " id=" + id);
  }
} catch (e) {
  console.log("ERROR " + e.message);
  try { await p.screenshot({path: "/tmp/xh_push_err_" + D.note + ".png"}); } catch (_) {}
} finally {
  await t.finish({keep: []});
}
