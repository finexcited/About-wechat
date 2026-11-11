# -*- coding: utf-8 -*-
"""common.py — WECHAT-picture-design 公共工具：配置、运行目录、日志、JSON 读写。"""
import json
import os
import sys
import time
import hashlib
import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
CONFIG_PATH = os.path.join(SCRIPTS_DIR, "config.json")

STAGES = ["S0", "S1", "S2", "S3", "S4", "S5", "S6"]


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def skill_path(*parts):
    return os.path.join(SKILL_DIR, *parts)


def jload(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def jdump(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_text(path, default=""):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_run_id(keyword):
    slug = "".join(ch for ch in keyword if ch.isalnum())[:12] or "kw"
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slug


def create_run(workdir, keyword):
    run_id = new_run_id(keyword)
    root = os.path.join(os.path.abspath(workdir), run_id)
    for sub in ("data", "data/covers", "notes"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    return root


def note_dir(run_root, idx):
    d = os.path.join(run_root, "notes", "%02d" % idx)
    os.makedirs(d, exist_ok=True)
    return d


def run_meta_path(run_root):
    return os.path.join(run_root, "run.json")


def load_run(run_root):
    meta = jload(run_meta_path(run_root))
    if meta is None:
        die("运行目录无效（缺少 run.json）：%s" % run_root)
    meta["_root"] = run_root
    return meta


def save_run(run_root, meta):
    clean = {k: v for k, v in meta.items() if not k.startswith("_")}
    jdump(run_meta_path(run_root), clean)


def log_event(run_root, stage, message, level="info", extra=None):
    """阶段级日志：写入 events.jsonl，异常另记 exceptions.json。"""
    rec = {"ts": now_str(), "stage": stage, "level": level, "message": message}
    if extra:
        rec["extra"] = extra
    path = os.path.join(run_root, "events.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if level in ("warn", "error"):
        ex_path = os.path.join(run_root, "exceptions.json")
        ex = jload(ex_path, [])
        ex.append({"ts": rec["ts"], "stage": stage, "level": level,
                   "message": message, "extra": extra or {}})
        jdump(ex_path, ex)
    return rec


def die(msg, code=2):
    print("❌ " + msg, file=sys.stderr)
    sys.exit(code)


def ok(msg):
    print("✅ " + msg)


def info(msg):
    print("· " + msg)


def resolve(run_root, path):
    """清单中存放相对运行目录的路径；兼容历史绝对路径。"""
    return path if os.path.isabs(path) else os.path.join(run_root, path)


def sha8(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
