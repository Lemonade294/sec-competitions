#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_all.py (多线程加速版 - 适配2026级121项细则)
============================
【本次修改说明】
1. 严格按照《网络空间安全学院奖励分细则最终版-2026级》的 121 个条目重新映射了 CONFIG。
2. 保留多线程并发（ThreadPoolExecutor）、日志实时刷新（flush=True）和防卡死超时。
3. 对于论文、专利、护网等非公开网页类项目，自动设为 manual 跳过抓取。
"""

import argparse
import html
import json
import os
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ---------------------------------------------------------------------------
# 0. 基础配置
# ---------------------------------------------------------------------------
DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.json")
BACKUP_PATH = os.path.join(os.path.dirname(DATA_PATH), "data.json.bak")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

DEFAULT_TIMEOUT = 10          # 单页超时缩短为10秒
DEFAULT_MAX_PAGES = 3         # 每个竞赛最多深入抓取的正文页数
REQUEST_INTERVAL = 0.2        # 请求间隔（秒）
MAX_WORKERS = 10              # 并发线程数

LINK_KEYWORDS = [
    "通知", "公告", "新闻", "动态", "报名", "竞赛", "大赛", "时间", "章程",
    "须知", "赛程", "日程", "安排", "简章", "about", "notice", "news",
    "announcement", "competition", "contest", "schedule", "registration",
]

LINK_NEGATIVE = ["培训", "研讨", "讲评", "交流会", "经验交流", "年会", "会议",
                 "论坛", "开幕式", "颁奖", "视频", "回顾", "简报", "花絮", "闭幕"]

LINK_BAD_WORDS = ["javascript", "mailto", "tel:", ".pdf", ".zip", ".rar", ".xlsx",
                  ".docx", ".doc", "login", "register?from", "download", "下载", "附件"]

UPDATE_MARKER = " (自动更新于 {})"

# ---------------------------------------------------------------------------
# 1. 官网发布特点配置 (严格按照 121 项最新ID映射)
# ---------------------------------------------------------------------------
CONFIG = {
    # === A 类 ===
    1: {"note": "互联网+"},
    2: {"title_include": r"课外学术|大挑", "note": "大挑"},
    3: {"title_include": r"创业计划|小挑", "note": "小挑"},

    # === B 类 ===
    4: {"lang": "en", "note": "ICPC"},
    5: {"note": "CISCN半决赛"},
    6: {"note": "CISCN决赛"},
    7: {"note": "长城杯决赛"},
    8: {"note": "CISCN作品赛"},
    9: {"urls": ["https://www.isclab.org.cn/category/iscc/", "https://www.isclab.org.cn/category/%e9%80%9a%e7%9f%a5%e5%85%ac%e5%91%8a/"], "mode": "list", "title_include": r"ISCC|信息安全与对抗", "note": "ISCC"},
    10: {"note": "物联网设计"},
    11: {"note": "AI算法大赛"},
    12: {"note": "中国软件杯"},
    13: {"note": "系统能力大赛"},
    14: {"note": "4C"},
    15: {"note": "C4"},
    16: {"mode": "spa", "note": "华为ICT (JS渲染)"},
    17: {"note": "百度之星"},
    18: {"lang": "en", "note": "Imagine Cup 国际"},
    19: {"lang": "en", "note": "Imagine Cup 中国区"},
    20: {"urls": ["https://www.mcm.edu.cn"], "note": "国赛数模"},
    21: {"mode": "spa", "note": "蓝桥杯 (JS渲染)"},
    22: {"note": "电赛"},
    23: {"note": "CMC"},
    24: {"note": "RoboCup"},
    25: {"note": "国创年会"},
    26: {"note": "智能车"},
    27: {"note": "嵌入式芯片"},
    28: {"note": "大唐杯"},
    29: {"note": "RoboMaster"},
    30: {"note": "RoboCon"},
    31: {"note": "睿抗"},
    32: {"note": "机器人及AI"},
    33: {"note": "机器人创意"},
    34: {"note": "工创赛"},
    35: {"note": "中美创客"},
    36: {"note": "光电设计"},
    37: {"note": "数媒竞赛"},
    38: {"note": "3D大赛"},
    39: {"note": "西门子杯"},
    40: {"note": "机械创新"},
    41: {"note": "iCAN"},
    42: {"note": "力学竞赛"},
    43: {"note": "外研社杯"},
    44: {"note": "统计建模"},
    45: {"note": "跨文化能力"},
    46: {"note": "中华经典"},
    47: {"note": "21世纪杯"},
    48: {"note": "物理实验"},
    49: {"note": "未来设计师"},
    50: {"note": "地质技能"},
    51: {"note": "米兰设计周"},
    52: {"note": "集成电路"},
    53: {"note": "商业精英"},
    54: {"note": "中国好创意"},
    55: {"note": "学创杯"},
    56: {"note": "BIM"},
    57: {"note": "化学邀请赛"},
    58: {"note": "生命科学"},
    59: {"note": "市场调查"},
    60: {"note": "华灿奖"},
    61: {"note": "服务外包"},
    62: {"note": "工业设计"},
    63: {"note": "大广赛"},
    64: {"note": "医学技能"},
    65: {"note": "企模"},
    66: {"note": "数字建筑"},
    67: {"note": "数智化沙盘"},
    68: {"note": "三创赛"},
    69: {"note": "财会"},
    70: {"note": "智能农业"},
    71: {"note": "企模竞赛"},
    72: {"note": "税收风险"},
    73: {"note": "基础医学"},
    74: {"note": "能源经济"},
    75: {"note": "测绘"},
    76: {"note": "花园设计"},
    77: {"note": "化学创新"},
    78: {"note": "化工实验"},
    79: {"note": "工行杯"},
    80: {"note": "机械创新"},
    81: {"note": "结构设计"},
    82: {"note": "成图大赛"},
    83: {"note": "化工设计"},
    84: {"note": "交通运输"},
    85: {"note": "水利创新"},
    86: {"note": "节能减排"},
    87: {"note": "物流设计"},
    88: {"note": "金相技能"},
    89: {"mode": "manual", "note": "B类论文 (需人工录入)"},
    90: {"mode": "manual", "note": "参军立功 (需人工录入)"},
    91: {"mode": "manual", "note": "国家级体育 (需人工录入)"},
    92: {"mode": "manual", "note": "国际实习 (需人工录入)"},

    # === C 类 ===
    93: {"note": "超算竞赛"},
    94: {"note": "软件创新"},
    95: {"lang": "en", "note": "美赛 MCM/ICM"},
    96: {"note": "密码技术"},
    97: {"title_include": r"密码数学|密码挑战", "note": "密码数学"},
    98: {"lang": "en", "note": "红点奖"},
    99: {"note": "NECCS"},
    100: {"mode": "manual", "note": "四六级口语 (需人工录入)"},
    101: {"note": "湖北信创"},
    102: {"mode": "manual", "note": "软考 (需人工录入)"},
    103: {"mode": "manual", "note": "国创项目 (需人工录入)"},
    104: {"mode": "manual", "note": "C类论文 (需人工录入)"},
    105: {"mode": "manual", "note": "专利 (需人工录入)"},
    106: {"mode": "manual", "note": "参军入伍 (需人工录入)"},
    107: {"mode": "manual", "note": "省大运会 (需人工录入)"},
    108: {"mode": "manual", "note": "省级文艺 (需人工录入)"},
    109: {"mode": "manual", "note": "思政类国家级 (需人工录入)"},
    110: {"mode": "manual", "note": "思政类省级 (需人工录入)"},
    111: {"mode": "manual", "note": "思政类校级 (需人工录入)"},

    # === 学院重点支持 ===
    112: {"urls": ["https://ccpc.io"], "note": "CCPC"},
    113: {"urls": ["http://ccsp.ccf.org.cn"], "note": "CCSP"},
    114: {"urls": ["https://www.cspro.org"], "note": "CSP"},
    115: {"mode": "manual", "note": "开源贡献 (需人工录入)"},
    116: {"urls": ["https://ccb.itsec.gov.cn"], "note": "长城杯铁人三项"},
    117: {"urls": ["https://www.wangdingcup.com"], "note": "网鼎杯"},
    118: {"urls": ["https://www.qiangwangbei.com"], "note": "强网杯"},
    119: {"mode": "manual", "note": "CNVD漏洞 (需人工录入)"},
    120: {"mode": "manual", "note": "开源PR (需人工录入)"},
    121: {"mode": "manual", "note": "护网行动 (需人工录入)"},
}

SKIP_REASONS = {}

# ---------------------------------------------------------------------------
# 2. 抓取层
# ---------------------------------------------------------------------------
def _ssl_context():
    return ssl.create_default_context()

def fetch(url, timeout=DEFAULT_TIMEOUT, allow_insecure=True):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    last_err = None
    for attempt in (1, 2):
        try:
            try:
                resp = urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())
            except urllib.error.URLError:
                if not allow_insecure:
                    raise
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
            data = resp.read()
            return data, resp.geturl()
        except Exception as e:
            last_err = e
            time.sleep(1.0)
    if last_err is not None:
        return None, None

def decode_html(raw):
    if raw is None: return ""
    if raw.startswith(b"\xef\xbb\xbf"): return raw.decode("utf-8", errors="replace")
    head = raw[:4096].decode("ascii", errors="ignore")
    m = re.search(r"charset\s*=\s*[\"']?\s*([\w-]+)", head, re.I)
    candidates = []
    if m: candidates.append(m.group(1).lower())
    candidates += ["utf-8", "gbk"]
    for enc in candidates:
        try: return raw.decode(enc)
        except Exception: pass
    best, best_bad = "", None
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            text = raw.decode(enc, errors="replace")
            bad = text.count("\ufffd")
            if best_bad is None or bad < best_bad:
                best, best_bad = text, bad
        except Exception: continue
    return best

def strip_html(html_text):
    s = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<!--[\s\S]*?-->", " ", s)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in s.split("\n")]
    return [ln for ln in lines if ln]

def abs_url(base, href):
    href = href.strip()
    if not href or href.startswith("#") or href.startswith(("javascript:", "mailto:", "tel:")): return None
    return urllib.parse.urljoin(base, href)

def extract_links(html_text, base):
    out = []
    for m in re.finditer(r"<a[^>]+href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html_text, re.I | re.S):
        url = abs_url(base, m.group(1))
        anchor = re.sub(r"<[^>]+>", "", m.group(2))
        anchor = re.sub(r"\s+", " ", html.unescape(anchor)).strip()
        if url: out.append((anchor, url))
    return out

def link_relevance(anchor, href, include_re=None):
    if include_re and not include_re.search(anchor): return -999
    if any(b in href.lower() for b in LINK_BAD_WORDS): return -999
    score = 0
    hay = (anchor + " " + href.lower())
    for kw in LINK_KEYWORDS:
        if kw in hay: score += 1
    for nw in LINK_NEGATIVE:
        if nw in hay: score -= 3
    m = re.search(r"(20\d{2})", hay)
    if m and int(m.group(1)) >= datetime.now().year - 1: score += 2
    return score

# ---------------------------------------------------------------------------
# 3. 抽取层
# ---------------------------------------------------------------------------
DATE_RE = re.compile(r"(?<!\d)(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?")
YEAR_RE = re.compile(r"(20\d{2})\s*年")
SIGNUP_STRONG = ["报名时间", "报名截止", "报名开始", "报名结束", "报名日期", "参赛报名", "作品提交截止", "提交截止", "注册截止"]
SIGNUP_WEAK = ["报名", "注册", "作品提交", "提交作品", "作品征集", "征集", "缴费"]
TIME_STRONG = ["比赛时间", "竞赛时间", "大赛时间", "比赛日期", "决赛时间", "总决赛时间", "初赛时间", "复赛时间", "赛程", "日程安排", "比赛日程", "竞赛日程", "赛事安排", "举办时间", "开赛时间"]
TIME_WEAK = ["初赛", "复赛", "省赛", "区域赛", "选拔赛", "总决赛", "全国总决赛", "决赛", "比赛", "竞赛", "大赛", "赛事", "线下赛", "线上赛"]
NOISE_WORDS = ["地址", "地点", "联系人", "联系电话", "电话", "邮箱", "E-mail", "附件", "下载", "咨询群", "登录", "账号", "密码", "微信", "公众号", "官网", "网址", "会务组", "报到地点", "食宿", "酒店", "发票", "赛题", "联系", "遴选", "须知"]
KEEP_STARTS = ("每年", "每两年", "即日", "即起", "报名", "截止", "初赛", "复赛", "决赛", "总决赛", "省赛", "校赛", "线上", "线下", "赛程", "日程", "比赛", "竞赛", "大赛", "作品", "提交", "注册", "开放", "开始", "结束", "举办", "赛事")
STRIP_CHARS = " 　/／、,，:：|｜-—–~～至到及与或(（【［"
STAGE_ORDER = ["校赛", "校内赛", "学校选拔", "初赛", "复赛", "半决赛", "省赛", "赛区赛", "区域赛", "选拔赛", "资格赛", "线上赛", "线下赛", "决赛", "总决赛", "全国总决赛"]
EN_SIGNUP_LABELS = ["registration deadline", "deadline for registration", "registration period", "registration", "register by", "submission deadline", "submit by"]
EN_TIME_LABELS = ["competition dates", "contest dates", "final", "finals", "competition will be held", "contest", "event dates", "results announced"]

def pick_labels(sent, strong_list, weak_list):
    low = sent.lower()
    for lab in strong_list:
        if lab.lower() in low: return lab, None
    for lab in weak_list:
        if lab.lower() in low: return None, lab
    return None, None

def _strip_prefix(content):
    content = content.strip()
    while content:
        ch = content[0]
        if ch.isdigit() or content.startswith(KEEP_STARTS): break
        if ch in STRIP_CHARS: content = content[1:]; continue
        if len(content) > 40: break
        content = content[1:]
    return re.sub(r"^(作品提交|提交作品|报名|时间|日期|截止)[（(]", r"\1：", content)

def _clean_content(sent, label):
    idx = sent.lower().find(label.lower())
    content = sent[idx + len(label):] if idx >= 0 else sent
    content = re.sub(r"^[\s:：,，、|｜\-—]+", "", content)
    cut = len(content)
    for nw in NOISE_WORDS:
        p = content.find(nw)
        if p != -1 and p < cut: cut = p
    content = content[:cut]
    punc = re.search(r"[。！？!?]", content)
    if punc: content = content[:punc.start()]
    tail = re.search(r"，(?=报名|截止|提交|作品|参赛|选手)", content)
    if tail: content = content[:tail.start()]
    content = _strip_prefix(content)
    content = content.replace("\u200c", "").replace("\u200b", "").replace("\ufeff", "")
    while content and content[-1] in " ，,。；;、）)】》」』":
        if content[-1] in "）)" and ("（" in content or "(" in content): break
        content = content[:-1]
    return content

def _ensure_year(text, hint_year):
    if "每年" in text and not YEAR_RE.search(text): return text
    def rep(m):
        y, mo, d = m.group(1), int(m.group(2)), m.group(3)
        prefix = f"{y if y else hint_year}年"
        return f"{prefix}{mo}月" + (f"{int(d)}日" if d else "")
    return DATE_RE.sub(rep, text)

CUR_YEAR = datetime.now().year

def build_records(lines, strong_list, weak_list):
    records = []
    for i, ln in enumerate(lines):
        strong, weak = pick_labels(ln, strong_list, weak_list)
        if not (strong or weak): continue
        label = strong or weak
        content = _clean_content(ln, label)
        has_time = bool(DATE_RE.search(content)) or ("截止" in content and re.search(r"\d", content)) or re.search(r"\d{1,2}月", content)
        if len(content) >= 2 and has_time:
            records.append((label, bool(strong), content))
        elif len(content) < 2:
            parts = []
            for j in range(i + 1, min(i + 6, len(lines))):
                nxt = lines[j]
                if pick_labels(nxt, strong_list, weak_list)[0] or pick_labels(nxt, strong_list, weak_list)[1]: break
                parts.append(nxt)
                if DATE_RE.search(nxt) or ("截止" in nxt and re.search(r"\d", nxt)): break
            val = "".join(parts).strip(" ，,。；;、")
            if len(val) >= 2 and (DATE_RE.search(val) or ("截止" in val and re.search(r"\d", val)) or re.search(r"\d{1,2}月", val)):
                records.append((label, bool(strong), val))
    return records

def _max_date(text):
    best = None
    for y, mo, d in DATE_RE.findall(text):
        if not y: continue
        try:
            dt = datetime(int(y), int(mo), int(d) if d else 28)
            if best is None or dt > best: best = dt
        except ValueError: continue
    return best

def _span_ok(v):
    m = re.search(r"([\d年月日]+)[—–\-－~～至到]+([\d年月日]+)", v)
    if not m: return True
    d1, d2 = _max_date(m.group(1)), _max_date(m.group(2))
    return not (d1 and d2 and (d2 - d1).days > 365)

def _has_strong_date(val):
    return any(y or d for y, mo, d in DATE_RE.findall(val))

def _score_record(label, strong, val, date_bonus):
    dates = DATE_RE.findall(val)
    if re.search(r"\d\s+\d", val): return 0
    score = (2 if strong else 1) + min(len(dates), date_bonus)
    if any(n in val for n in NOISE_WORDS): score -= 2
    if "截止" in val and re.search(r"\d", val): score += 1
    if not _has_strong_date(val) and len(val) > 30: score -= 2
    years = [int(y) for y, _, _ in dates if y]
    if years and (max(years) < CUR_YEAR or max(years) > CUR_YEAR + 3): return 0
    if not _span_ok(val): return 0
    return score

def _extract_signup(text_lines, title, year, rx=None):
    if rx:
        for ln in text_lines:
            for m in re.finditer(rx, ln):
                c = _clean_content(ln[m.start():], m.group(0).split("：")[0])
                if c and len(c) >= 2 and (_has_strong_date(c) or ("截止" in c and re.search(r"\d{1,2}月", c))):
                    return _ensure_year(c, year), 5
    records = build_records(text_lines, SIGNUP_STRONG, SIGNUP_WEAK)
    best, best_score = None, 0
    for label, strong, val in records:
        if not DATE_RE.search(val): continue
        score = _score_record(label, strong, val, 3)
        if score > best_score:
            v = _ensure_year(val, year)
            if _span_ok(v): best, best_score = v, score
    return (best, best_score) if best else (None, 0)

def _extract_time(text_lines, title, year, rx=None):
    if rx:
        for ln in text_lines:
            for m in re.finditer(rx, ln):
                c = _clean_content(ln[m.start():], m.group(0).split("：")[0])
                if c and len(c) >= 2 and (_has_strong_date(c) or ("截止" in c and re.search(r"\d{1,2}月", c))):
                    return _ensure_year(c, year), 5
    records = build_records(text_lines, TIME_STRONG, TIME_WEAK)
    best_single, best_score = None, 0
    stage_pick = {}
    now = datetime.now()
    has_future = any(_max_date(v) and _max_date(v) >= now for _, _, v in records)
    for label, strong, val in records:
        score = _score_record(label, strong, val, 4)
        if score <= 0: continue
        v = _ensure_year(val, year)
        if not _span_ok(v): continue
        if has_future and _max_date(v) and _max_date(v) < now: continue
        if score > best_score: best_single, best_score = v, score
        for st in STAGE_ORDER:
            if st in label or st in v:
                text_piece = v if st in v else f"{label}{v}"
                if st not in stage_pick or score > stage_pick[st][0]: stage_pick[st] = (score, text_piece)
                break
    if len(stage_pick) >= 2:
        parts = [stage_pick[st][1] for st in STAGE_ORDER if st in stage_pick][:4]
        if len(parts) >= 2 and sum(len(p) for p in parts) <= 150:
            return " → ".join(parts), 6
    return (best_single, best_score) if best_single else (None, 0)

def extract_en(text_lines, year):
    best_s, best_t = None, None
    for ln in text_lines:
        low = ln.lower()
        if any(lb in low for lb in EN_SIGNUP_LABELS) and DATE_RE.search(ln): best_s = _ensure_year(ln.strip()[:120], year)
        if any(lb in low for lb in EN_TIME_LABELS) and DATE_RE.search(ln): best_t = _ensure_year(ln.strip()[:150], year)
    return best_s, best_t

# ---------------------------------------------------------------------------
# 4. 页面发现与文本收集
# ---------------------------------------------------------------------------
def discover_article_urls(html_text, base, limit=DEFAULT_MAX_PAGES, include_re=None):
    scored = []
    seen = set()
    for anchor, href in extract_links(html_text, base):
        sc = link_relevance(anchor, href, include_re)
        if sc <= 0 or href in seen: continue
        seen.add(href)
        scored.append((sc, anchor, href))
    scored.sort(key=lambda x: -x[0])
    return [(a, h) for _, a, h in scored[:limit]]

def fetch_text_page(url, cfg, year):
    raw, final = fetch(url, timeout=cfg.get("timeout", DEFAULT_TIMEOUT))
    if raw is None: return None, None, None
    text = decode_html(raw)
    title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = re.sub(r"\s+", " ", html.unescape(title_m.group(1))).strip() if title_m else ""
    return strip_html(text), title, final

def collect_text(cfg, year):
    mode = cfg.get("mode", "auto")
    if mode in ("spa", "manual"):
        return None, [], f"跳过：官网为JS渲染/需人工（{cfg.get('note', '')}）"
    urls = cfg.get("urls") or [cfg.get("link")]
    urls = [u for u in urls if u]
    if not urls: return None, [], "无可用URL"

    all_lines, titles, pages = [], [], []
    include_re = re.compile(cfg["title_include"]) if cfg.get("title_include") else None
    
    for u in urls[:2]:
        raw, final = fetch(u, timeout=cfg.get("timeout", DEFAULT_TIMEOUT))
        if raw is None: continue
        text = decode_html(raw)
        lines = strip_html(text)
        title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        titles.append(re.sub(r"\s+", " ", html.unescape(title_m.group(1))).strip() if title_m else "")
        if mode == "article":
            pages.append((lines, u))
        else:
            all_lines.extend(lines)
            if mode in ("auto", "list"):
                for a, h in discover_article_urls(text, u, cfg.get("max_pages", DEFAULT_MAX_PAGES), include_re):
                    pages.append((a, h))
        time.sleep(REQUEST_INTERVAL)

    min_year = cfg.get("min_year")
    page_year_re = re.compile(r"20\d{2}")
    visited = set()
    for a, h in pages:
        if h in visited or len(visited) >= cfg.get("max_pages", DEFAULT_MAX_PAGES): continue
        ym = page_year_re.search(a or "")
        if min_year and ym and int(ym.group(0)) < min_year: continue
        visited.add(h)
        lines, title, _ = fetch_text_page(h, cfg, year)
        if lines:
            ym2 = page_year_re.search(title or "")
            if not (min_year and ym2 and int(ym2.group(0)) < min_year):
                all_lines.extend(lines)
                if title: titles.append(title)
        time.sleep(REQUEST_INTERVAL)

    return all_lines, titles, None

# ---------------------------------------------------------------------------
# 5. 单竞赛处理
# ---------------------------------------------------------------------------
def run_competition(comp, cfg, year, verbose):
    result = {"signUp": None, "time": None, "status": "skip", "detail": ""}
    link = comp.get("link")
    if not link or cfg.get("mode") == "manual":
        result["detail"] = "无官网链接或需人工维护，跳过"
        return result
    cfg = dict(cfg, link=link)

    min_year = None
    for fld in ("signUp", "time"):
        ys = [int(y) for y in YEAR_RE.findall(comp.get(fld, "") or "")]
        if ys: min_year = max(min_year or 0, max(ys))
    cfg = dict(cfg, min_year=min_year)

    lines, titles, err = collect_text(cfg, year)
    if err or not lines:
        result["detail"] = err or "抓取无内容"
        return result

    text_all = "\n".join(lines)
    title_all = " ".join(titles)
    yr_hint = year
    years_in_text = sorted({int(y) for y in YEAR_RE.findall(text_all + " " + title_all)})
    cand = [y for y in years_in_text if year <= y <= year + 3]
    if cand: yr_hint = min(cand)
    elif years_in_text: yr_hint = max(years_in_text)

    if cfg.get("lang") == "en":
        s, t = extract_en(lines, yr_hint)
        s_conf = t_conf = 1 if (s or t) else 0
    else:
        s, s_conf = _extract_signup(lines, title_all, yr_hint, cfg.get("signup_rx"))
        t, t_conf = _extract_time(lines, title_all, yr_hint, cfg.get("time_rx"))

    def _year_guard(new_text, old_text):
        new_years = [int(y) for y in YEAR_RE.findall(new_text)]
        old_years = [int(y) for y in YEAR_RE.findall(old_text or "")]
        if new_years and old_years and max(new_years) < max(old_years): return False
        if old_text and ("；" in old_text or "→" in old_text) and ("；" not in new_text and "→" not in new_text): return False
        if ("每年" in (old_text or "") and "每年" in new_text) or ("每两年" in (old_text or "") and "每两年" in new_text): return False
        n_dt, o_dt = _max_date(new_text), _max_date(old_text or "")
        return not (n_dt and n_dt < datetime.now() and (o_dt is None or o_dt >= datetime.now()))

    updated = []
    if s and s_conf >= 3 and _year_guard(s, comp.get("signUp")):
        result["signUp"] = s
        updated.append("signUp")
    if t and t_conf >= 3 and _year_guard(t, comp.get("time")):
        result["time"] = t
        updated.append("time")

    if updated:
        result["status"] = "updated"
        detail = [f"{k}={result[k]!r}" for k in updated]
        result["detail"] = "更新 " + "; ".join(detail)
    else:
        result["status"] = "low_conf"
        result["detail"] = f"低置信度（signUp={s or '无'!r}, time={t or '无'!r}），保留原值"
    return result

# ---------------------------------------------------------------------------
# 6. 主流程（多线程）
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--out")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--year", type=int, default=datetime.now().year)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = ap.parse_args()

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    only_ids = {int(x) for x in args.only.split(",") if x.strip()} if args.only else None
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    stats = {"updated": 0, "low_conf": 0, "failed": 0, "skipped": 0}
    stats_lock = threading.Lock()

    def process_comp(comp):
        cid = comp.get("id")
        if only_ids and cid not in only_ids: return None
        
        cfg = CONFIG.get(cid, {})
        if cid in SKIP_REASONS: cfg = dict(cfg, mode="manual", note=SKIP_REASONS[cid])
        name = comp.get("name", f"id={cid}")
        
        try:
            res = run_competition(comp, cfg, args.year, args.verbose)
        except Exception as e:
            res = {"status": "failed", "detail": f"异常: {e}"}
            
        if res["status"] == "updated":
            if res.get("signUp"): comp["signUp"] = res["signUp"] + UPDATE_MARKER.format(now_str)
            if res.get("time"): comp["time"] = res["time"] + UPDATE_MARKER.format(now_str)
            flag = "OK  "
        elif res["status"] == "low_conf": flag = "~    "
        elif res["status"] == "skip": flag = "SKIP "
        else: flag = "FAIL "
        return cid, name, res, flag

    print(f"🚀 开始并发抓取 (共 {MAX_WORKERS} 线程)...", flush=True)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_comp, comp): comp for comp in data}
        for future in as_completed(futures):
            try:
                res_data = future.result()
                if res_data is None: continue
                cid, name, res, flag = res_data
                
                with stats_lock:
                    stats[res["status"]] = stats.get(res["status"], 0) + 1
                    print(f"[{flag}] id={cid:<3} {name[:28]:<28} {res['detail']}", flush=True)
            except Exception as e:
                print(f"⚠️ 收集出错: {e}", flush=True)

    stats["skipped"] = stats.pop("skip", 0)
    
    if args.dry_run:
        print(f"\n[dry-run] 更新 {stats['updated']}，保留 {stats['low_conf']}，跳过 {stats['skipped']}，失败 {stats['failed']}。未写入。", flush=True)
        return

    out_path = args.out or DATA_PATH
    if os.path.abspath(out_path) == os.path.abspath(DATA_PATH):
        shutil.copy2(DATA_PATH, BACKUP_PATH)
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, out_path)
    print(f"🎉 已写入 {out_path}（更新 {stats['updated']}，保留 {stats['low_conf']}，跳过 {stats['skipped']}，失败 {stats['failed']}）", flush=True)

if __name__ == "__main__":
    main()
