#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_all.py
=============
按每个竞赛官网的“发布特点”，自动抓取每年的【报名时间】和【比赛时间】，
并更新到 sec-competitions/data.json（字段 signUp / time）。

设计要点
--------
1. 默认策略（auto）：以 data.json 中每条的 link 为官网首页，自动发现站内
   “通知/公告/新闻/报名/竞赛”类链接（标题或 URL 含关键词），取最新的若干页
   做正文抽取——适合大多数服务端渲染的竞赛官网。
2. 个别官网结构特殊，在 CONFIG 中按竞赛 id 给出覆盖配置：
   - urls : 指定直接抓取的页面（列表页 / 公告页）
   - mode : auto / list / article / spa / manual
       auto    首页自动发现链接（默认）
       list    urls 是列表页，从列表发现文章链接再抓正文
       article urls 直接是公告正文页
       spa     JS 渲染页，普通 HTTP 抓不到内容（跳过，保留原值并提示）
       manual  不抓取，保留原值并提示原因
   - lang  : zh（默认）/ en（英文官网，用英文关键词抽取）
   - signup_rx / time_rx : 针对已知公告格式的正则覆盖（优先尝试）
   - note  : 该官网的发布特点说明（维护用）
3. 抽取质量门控：只有找到“报名时间/报名截止/大赛时间/比赛时间/决赛时间”等
   明确标签且带具体日期，才覆盖原值；低置信度一律保留原值，并记入日志，
   避免用垃圾文本污染人工整理的数据。
4. 更新字段会追加标记“ (自动更新于 YYYY-MM-DD HH:MM:SS)”，与现有数据
   （如 id=1）保持一致；重复运行会先剥离旧标记再写新标记。
5. 写回前自动备份 data.json -> data.json.bak；采用临时文件 + os.replace
   原子替换，避免写坏原文件。

依赖：仅 Python 标准库（urllib / re / json / datetime），无需 pip 安装。

用法
----
    python update_all.py                     # 全量更新 data.json
    python update_all.py --dry-run           # 只抓取解析，不写文件
    python update_all.py --only 4,30,102     # 只更新指定 id（逗号分隔）
    python update_all.py --out test.json     # 结果写到 test.json（不碰原文件）
    python update_all.py --verbose           # 打印每个竞赛的抓取细节
    python update_all.py --year 2026         # 指定赛季年份（默认当前年）
    python update_all.py --timeout 15        # 单页超时秒数（默认 20）
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

# ---------------------------------------------------------------------------
# 0. 基础配置
# ---------------------------------------------------------------------------
DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.json")
BACKUP_PATH = os.path.join(os.path.dirname(DATA_PATH), "data.json.bak")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

DEFAULT_TIMEOUT = 20          # 单页抓取超时（秒）
DEFAULT_MAX_PAGES = 3         # 每个竞赛最多深入抓取的正文页数
REQUEST_INTERVAL = 0.5        # 请求间隔（秒），避免对官网造成压力

# 自动发现链接时用的关键词（标题或 href 命中即视为“可能含时间信息”的页面）
LINK_KEYWORDS = [
    "通知", "公告", "新闻", "动态", "报名", "竞赛", "大赛", "时间", "章程",
    "须知", "赛程", "日程", "安排", "简章", "about", "notice", "news",
    "announcement", "competition", "contest", "schedule", "registration",
]

# 命中即大幅降权：这些是“衍生事件页”（培训/研讨/讲评/会议/颁奖等），
# 通常不含竞赛本身的报名/比赛时间
LINK_NEGATIVE = ["培训", "研讨", "讲评", "交流会", "经验交流", "年会", "会议",
                 "论坛", "开幕式", "颁奖", "视频", "回顾", "简报", "花絮", "闭幕"]

# 过滤掉明显不是正文的链接
LINK_BAD_WORDS = ["javascript", "mailto", "tel:", ".pdf", ".zip", ".rar", ".xlsx",
                  ".docx", ".doc", "login", "register?from", "download", "下载", "附件"]

MARKER_RE = re.compile(r"\s*\(自动更新于\s*[\d\- :]+\)\s*$")
UPDATE_MARKER = " (自动更新于 {})"

# ---------------------------------------------------------------------------
# 1. 官网发布特点配置（按 data.json 中的竞赛 id 覆盖默认行为）
#    未列出的竞赛使用默认 auto 策略：从 link 首页自动发现公告并抽取。
# ---------------------------------------------------------------------------
CONFIG = {
    # ---- 已实测结构的关键官网 ----
    1: {"note": "互联网+：官网首页即发大赛通知（通知常以zip附件下发，但页面正文仍含报名/赛程时段），可自动发现"},
    2: {"title_include": r"课外学术|大挑",
        "note": "大挑：与“小挑”共用 tiaozhanbei.net，按标题过滤“课外学术/大挑”相关公告"},
    3: {"title_include": r"创业计划|小挑",
        "note": "小挑：与“大挑”共用 tiaozhanbei.net，按标题过滤“创业计划/小挑”相关公告"},
    4: {"urls": ["https://www.mcm.edu.cn"],
        "note": "数模国赛：静态站，首页直接列最新通知（/html_cn/node/...），标题含年份"},
    18: {"urls": ["https://www.isclab.org.cn/category/iscc/",
                 "https://www.isclab.org.cn/category/%e9%80%9a%e7%9f%a5%e5%85%ac%e5%91%8a/"],
         "mode": "list",
         "title_include": r"ISCC|信息安全与对抗",
         "note": "ISCC：WordPress 结构，多竞赛共站，需按标题过滤“ISCC/信息安全与对抗”相关公告"},
    22: {"mode": "spa",
         "note": "蓝桥杯：官网为 JS 渲染 SPA，普通 HTTP 抓不到正文，需人工或浏览器自动化（报名窗口约每年10月-12月）"},
    30: {"note": "信安赛 CISCN：首页直列最新公告（/announcement/view/<id>）；当年报名季过后首页多为获奖名单，章程页为“每年3-6月”周期表述"},
    102: {"note": "强网杯：首页为当届赛事门户，标题/正文含报名时间与线上线下赛时间，报名跳转 i春秋（endbm.ichunqiu.com）"},
    # ---- 语言为英文的官网 ----
    5: {"lang": "en", "note": "Imagine Cup 全球站：英文官网，按英文关键词抽取（registration/competition dates）"},
    6: {"lang": "en", "note": "Imagine Cup 中国区：同全球站，若抓不到以官网当年通知为准"},
    17: {"lang": "en", "note": "ICPC：英文官网，区域赛日程在 icpc.global 发布"},
    88: {"lang": "en", "note": "美赛 MCM/ICM：COMAP 官网英文发布，Advisor 注册截止与赛期可见"},
    91: {"lang": "en", "note": "红点奖：英文官网，注册截止与评审/颁奖时段以官网为准"},
    # ---- 已知 JS 渲染 / 需登录的官网（保留原值，提示人工） ----
    26: {"mode": "spa",
         "note": "华为ICT大赛：e.huawei.com 为 JS 渲染且需登录/地区跳转，普通HTTP抓不到，需人工或浏览器自动化"},
    15: {"mode": "auto", "note": "百度之星：官网高度动态，若首页抓不到正文则保留原值"},
    60: {"mode": "auto", "note": "数智化沙盘：官网平台化，若抓不到以官网当年通知为准"},
    45: {"mode": "auto", "note": "BIM毕业设计：报名入口平台化，公告正文可尝试抽取"},
    62: {"mode": "auto", "note": "财会职业能力：官网报名系统为主，公告页可尝试抽取"},
    90: {"title_include": r"密码数学|密码挑战",
         "note": "密码数学：官网(cmathc.org.cn)与数学竞赛类站点同域，多赛事公告混杂，仅跟进“密码数学/密码挑战”相关公告"},
}

# 已知大概率抓不到的站点（避免浪费时间），仍保留原值
SKIP_REASONS = {
    # 22/26 已在 CONFIG 用 mode=spa 处理；此处留给后续发现的站点
}


# ---------------------------------------------------------------------------
# 2. 抓取层（仅标准库）
# ---------------------------------------------------------------------------
def _ssl_context():
    ctx = ssl.create_default_context()
    return ctx


def fetch(url, timeout=DEFAULT_TIMEOUT, allow_insecure=True):
    """抓取一个 URL，返回 (bytes, final_url)。失败返回 (None, None)。"""
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
                # 部分官网证书链不完整，退化为不校验证书再试一次
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
            data = resp.read()
            return data, resp.geturl()
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.0)
    if last_err is not None:
        return None, None


def decode_html(raw):
    """根据 BOM / meta / Content-Type 推断编码，回退 utf-8 -> gbk，
    选择替换字符最少的一种解码结果。"""
    if raw is None:
        return ""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8", errors="replace")
    head = raw[:4096].decode("ascii", errors="ignore")
    m = re.search(r"charset\s*=\s*[\"']?\s*([\w-]+)", head, re.I)
    candidates = []
    if m:
        candidates.append(m.group(1).lower())
    candidates += ["utf-8", "gbk"]
    best, best_bad = "", None
    for enc in candidates:
        try:
            text = raw.decode(enc)
            return text
        except (UnicodeDecodeError, LookupError):
            continue
        except Exception:  # noqa: BLE001
            pass
    # 全部失败时选替换字符最少的
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            text = raw.decode(enc, errors="replace")
            bad = text.count("\ufffd")
            if best_bad is None or bad < best_bad:
                best, best_bad = text, bad
        except Exception:  # noqa: BLE001
            continue
    return best


def strip_html(html_text):
    """去掉 script/style/注释，把 HTML 转成干净的文本行。"""
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
    if not href or href.startswith("#"):
        return None
    if href.startswith(("javascript:", "mailto:", "tel:")):
        return None
    return urllib.parse.urljoin(base, href)


def extract_links(html_text, base):
    """返回 [(anchor_text, href), ...]"""
    out = []
    for m in re.finditer(r"<a[^>]+href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                         html_text, re.I | re.S):
        href = m.group(1)
        anchor = re.sub(r"<[^>]+>", "", m.group(2))
        anchor = re.sub(r"\s+", " ", html.unescape(anchor)).strip()
        url = abs_url(base, href)
        if url:
            out.append((anchor, url))
    return out


def link_relevance(anchor, href, include_re=None):
    """给链接打分：标题/URL 命中关键词越多越可能是“含时间信息的公告页”。
    include_re：若提供，锚文本必须匹配才考虑跟进（用于多竞赛共站的官网）。"""
    if include_re and not include_re.search(anchor):
        return -999
    if any(b in href.lower() for b in LINK_BAD_WORDS):
        return -999
    score = 0
    hay = (anchor + " " + href.lower())
    for kw in LINK_KEYWORDS:
        if kw in hay:
            score += 1
    for nw in LINK_NEGATIVE:
        if nw in hay:
            score -= 3
    # 最近年份优先（公告标题常带年份）
    m = re.search(r"(20\d{2})", hay)
    if m:
        yr = int(m.group(1))
        cur = datetime.now().year
        if yr >= cur - 1:
            score += 2
    return score


# ---------------------------------------------------------------------------
# 3. 抽取层
# ---------------------------------------------------------------------------
DATE_RE = re.compile(r"(?<!\d)(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?")
YEAR_RE = re.compile(r"(20\d{2})\s*年")

# 报名时间相关标签（强标签优先）
SIGNUP_STRONG = ["报名时间", "报名截止", "报名开始", "报名结束", "报名日期",
                 "参赛报名", "作品提交截止", "提交截止", "注册截止"]
SIGNUP_WEAK = ["报名", "注册", "作品提交", "提交作品", "作品征集", "征集", "缴费"]
TIME_STRONG = ["比赛时间", "竞赛时间", "大赛时间", "比赛日期", "决赛时间",
               "总决赛时间", "初赛时间", "复赛时间", "赛程", "日程安排",
               "比赛日程", "竞赛日程", "赛事安排", "举办时间", "开赛时间"]
TIME_WEAK = ["初赛", "复赛", "省赛", "区域赛", "选拔赛", "总决赛", "全国总决赛",
             "决赛", "比赛", "竞赛", "大赛", "赛事", "线下赛", "线上赛"]
NOISE_WORDS = ["地址", "地点", "联系人", "联系电话", "电话", "邮箱", "E-mail",
               "附件", "下载", "咨询群", "登录", "账号", "密码", "微信", "公众号",
               "官网", "网址", "会务组", "报到地点", "食宿", "酒店", "发票",
               "赛题", "联系", "遴选", "须知", "竞赛时间", "比赛时间",
               "初赛时间", "复赛时间", "决赛时间", "总决赛时间"]

# 取值允许保留的开头（避免把“报名截止/初赛/决赛”等关键语义当杂质剥掉）
KEEP_STARTS = ("每年", "每两年", "即日", "即起", "报名", "截止", "初赛", "复赛",
               "决赛", "总决赛", "省赛", "校赛", "线上", "线下", "赛程", "日程",
               "比赛", "竞赛", "大赛", "作品", "提交", "注册", "开放", "开始",
               "结束", "举办", "赛事")
STRIP_CHARS = " 　/／、,，:：|｜-—–~～至到及与或(（【［"
STAGE_ORDER = ["校赛", "校内赛", "学校选拔", "初赛", "复赛", "半决赛", "省赛",
               "赛区赛", "区域赛", "选拔赛", "资格赛", "线上赛", "线下赛",
               "决赛", "总决赛", "全国总决赛"]

if hasattr(sys, "setdefaultencoding"):  # py2 兼容占位，忽略
    pass

EN_SIGNUP_LABELS = ["registration deadline", "deadline for registration",
                    "registration period", "registration", "register by",
                    "submission deadline", "submit by"]
EN_TIME_LABELS = ["competition dates", "contest dates", "final", "finals",
                  "competition will be held", "contest", "event dates",
                  "results announced"]


def pick_labels(sent, strong_list, weak_list):
    """返回 (strong_label, weak_label)，命中任一即返回。"""
    low = sent.lower()
    for lab in strong_list:
        if lab.lower() in low:
            return lab, None
    for lab in weak_list:
        if lab.lower() in low:
            return None, lab
    return None, None


def _strip_prefix(content):
    """剥掉取值开头的杂质（“及”“为”“原则上定于”等），保留数字或关键语义开头。"""
    content = content.strip()
    while content:
        ch = content[0]
        if ch.isdigit() or content.startswith(KEEP_STARTS):
            break
        if ch in STRIP_CHARS:
            content = content[1:]
            continue
        if len(content) > 40:  # 长文本且开头不是关键语义 → 不剥，交给后续规则
            break
        content = content[1:]
    # 标签与括号连写时（如“作品提交（2026年…”）把括号规整为冒号
    content = re.sub(r"^(作品提交|提交作品|报名|时间|日期|截止)[（(]", r"\1：", content)
    return content


def _clean_content(sent, label):
    """取标签之后的内容并裁剪噪声/散文尾巴。"""
    idx = sent.lower().find(label.lower())
    if idx < 0:
        idx = 0
    content = sent[idx + len(label):]
    content = re.sub(r"^[\s:：,，、|｜\-—]+", "", content)
    # 在第一个噪声词处截断（保留含时间的部分）
    cut = len(content)
    for nw in NOISE_WORDS:
        p = content.find(nw)
        if p != -1 and p < cut:
            cut = p
    content = content[:cut]
    # 句号/感叹号后往往是散文尾巴（“…请大家抓紧时间！…”），截断
    punc = re.search(r"[。！？!?]", content)
    if punc:
        content = content[:punc.start()]
    # “，报名/，截止/，提交/，作品…” 后多为规则说明，截断
    tail = re.search(r"，(?=报名|截止|提交|作品|参赛|选手)", content)
    if tail:
        content = content[:tail.start()]
    content = _strip_prefix(content)
    content = content.replace("\u200c", "").replace("\u200b", "").replace("\ufeff", "")
    # 尾剥：无配对左括号的“））”视为残余剥掉；有配对的（如“11月7日（线下）”）保留
    while content and content[-1] in " ，,。；;、）)】》」』":
        if content[-1] in "）)" and ("（" in content or "(" in content):
            break
        content = content[:-1]
    return content


def _ensure_year(text, hint_year):
    """给缺年份的“M月D日”补年份；含“每年”的补“每年”。"""
    if "每年" in text and not YEAR_RE.search(text):
        return text

    def rep(m):
        y, mo, d = m.group(1), int(m.group(2)), m.group(3)
        if y:
            return f"{y}年{mo}月" + (f"{int(d)}日" if d else "")
        prefix = f"{hint_year}年" if hint_year else ""
        return f"{prefix}{mo}月" + (f"{int(d)}日" if d else "")

    return DATE_RE.sub(rep, text)


CUR_YEAR = datetime.now().year


def build_records(lines, strong_list, weak_list):
    """把文本行转成 (标签, 是否强标签, 取值) 记录，兼容两种官网排版：
      A. 标签与值同行：如 “报名时间：2026年4月1日—6月30日”
      B. 标签独占一行、值在下一行：如 “报名时间\\n即日起至10月下旬（暂定）”
    """
    records = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        strong, weak = pick_labels(ln, strong_list, weak_list)
        if not (strong or weak):
            i += 1
            continue
        label = strong or weak
        content = _clean_content(ln, label)
        has_time = bool(DATE_RE.search(content)) \
            or ("截止" in content and re.search(r"\d", content)) \
            or re.search(r"\d{1,2}月", content)
        if len(content) >= 2 and has_time:
            records.append((label, bool(strong), content))
        elif len(content) < 2:
            # 标签独占一行：向后合并若干行作为取值（遇到下一个标签即停）
            parts = []
            j = i + 1
            while j < n and j < i + 6:
                nxt = lines[j]
                s2, w2 = pick_labels(nxt, strong_list, weak_list)
                if s2 or w2:
                    break
                parts.append(nxt)
                if DATE_RE.search(nxt) or ("截止" in nxt and re.search(r"\d", nxt)):
                    break
                j += 1
            val = "".join(parts).strip(" ，,。；;、")
            if len(val) >= 2 and (DATE_RE.search(val) or ("截止" in val and re.search(r"\d", val))
                                  or re.search(r"\d{1,2}月", val)):
                records.append((label, bool(strong), val))
        i += 1
    return records


def _max_date(text):
    """取文本中日期（年月齐全即可）的最晚值；没有则 None。
    无“日”时按月末日(28)近似，用于新旧日期先后比较，不改动展示文本。"""
    best = None
    for y, mo, d in DATE_RE.findall(text):
        if not y:
            continue
        try:
            dt = datetime(int(y), int(mo), int(d) if d else 28)
        except ValueError:
            continue
        if best is None or dt > best:
            best = dt
    return best


def _span_ok(v):
    """补全年份后再校验区间跨度：起止间隔超过一年视为异常，拒收。"""
    m = re.search(r"([\d年月日]+)[—–\-－~～至到]+([\d年月日]+)", v)
    if not m:
        return True
    d1, d2 = _max_date(m.group(1)), _max_date(m.group(2))
    if d1 and d2 and (d2 - d1).days > 365:
        return False
    return True


def _has_strong_date(val):
    """日期里是否含明确年份或“日”（月份孤例不算强日期）。"""
    for y, mo, d in DATE_RE.findall(val):
        if y or d:
            return True
    return False


def _score_record(label, strong, val, date_bonus):
    dates = DATE_RE.findall(val)
    # 数字被网站样式拆碎（如 “202 6 年 9月10日”）→ 不可信，直接拒收
    if re.search(r"\d\s+\d", val):
        return 0
    noise = any(n in val for n in NOISE_WORDS)
    score = (2 if strong else 1) + min(len(dates), date_bonus)
    if noise:
        score -= 2
    if "截止" in val and re.search(r"\d", val):
        score += 1
    # 长文本且只有月份、无明确年份/日期 → 多为散文/章程式表述，降权；
    # 短值（≤30字）多为“标签:值”表格单元格或紧凑日期，可信
    if not _has_strong_date(val) and len(val) > 30:
        score -= 2
    # 年份合理性：取值年份应处于当前赛季附近（过早=旧公告/模板，过晚=乱码）
    years = [int(y) for y, _, _ in dates if y]
    if years:
        if max(years) < CUR_YEAR or max(years) > CUR_YEAR + 3:
            return 0
    # 日期区间跨度合理性（防 “2026年9月9日-2027年10月11日” 这类异常长区间）
    d1, d2 = _max_date(val), None
    rng = re.search(r"([\d年月日]+)[—–\-－~～至到]+([\d年月日]+)", val)
    if rng:
        head = val[:rng.start()] + rng.group(1)
        tail = rng.group(2)
        d1 = _max_date(head) or d1
        d2 = _max_date(tail)
        if d1 and d2 and (d2 - d1).days > 365:
            return 0
    return score


def _extract_signup(text_lines, title, year, rx=None):
    """抽取报名时间。返回 (文本, 置信度分数)。"""
    if rx:
        for ln in text_lines:
            for m in re.finditer(rx, ln):
                c = _clean_content(ln[m.start():], m.group(0).split("：")[0])
                if c and len(c) >= 2 and (_has_strong_date(c)
                                          or ("截止" in c and re.search(r"\d{1,2}月", c))):
                    return _ensure_year(c, year), 5
    records = build_records(text_lines, SIGNUP_STRONG, SIGNUP_WEAK)
    best, best_score = None, 0
    for label, strong, val in records:
        if not DATE_RE.search(val):
            continue  # 报名时间必须有日期痕迹
        score = _score_record(label, strong, val, 3)
        if score <= 0:
            continue
        v = _ensure_year(val, year)
        if not _span_ok(v):
            continue
        if score > best_score:
            best, best_score = v, score
    return (best, best_score) if best else (None, 0)


def _extract_time(text_lines, title, year, rx=None):
    """抽取比赛时间。优先按赛程阶段（初赛→决赛/线上→线下）合并；否则取单条。返回 (文本, 分数)。"""
    if rx:
        for ln in text_lines:
            for m in re.finditer(rx, ln):
                c = _clean_content(ln[m.start():], m.group(0).split("：")[0])
                if c and len(c) >= 2 and (_has_strong_date(c)
                                          or ("截止" in c and re.search(r"\d{1,2}月", c))):
                    return _ensure_year(c, year), 5
    records = build_records(text_lines, TIME_STRONG, TIME_WEAK)
    best_single, best_score = None, 0
    stage_pick = {}  # stage -> (score, text)
    # 若已有未来日期的阶段记录，则丢弃所有日期已过的阶段（旧公告残留）
    now = datetime.now()
    has_future = any(_max_date(v) and _max_date(v) >= now for _, _, v in records)
    for label, strong, val in records:
        score = _score_record(label, strong, val, 4)
        if score <= 0:
            continue
        v = _ensure_year(val, year)
        if not _span_ok(v):
            continue
        if has_future and _max_date(v) and _max_date(v) < now:
            continue
        if score > best_score:
            best_single, best_score = v, score
        for st in STAGE_ORDER:
            if st in label or st in v:
                text_piece = v if st in v else f"{label}{v}"
                if st not in stage_pick or score > stage_pick[st][0]:
                    stage_pick[st] = (score, text_piece)
                break
    if len(stage_pick) >= 2:
        order = [st for st in STAGE_ORDER if st in stage_pick]
        parts = []
        for st in order[:4]:
            piece = stage_pick[st][1]
            if len(piece) <= 30 and _time_like(piece):
                parts.append(piece)
        joined = " → ".join(parts)
        if len(parts) >= 2 and len(joined) <= 150:
            return joined, 6
    return (best_single, best_score) if best_single else (None, 0)


def _time_like(piece):
    """阶段片段是否“以时间为主”：去掉阶段前缀后，开头应是数字/“每年”等时间词，
    且日期相关字符占比不低（防止“省赛委员会确定，需在X月X日前”这类规则句混入）。"""
    core = piece
    for st in STAGE_ORDER:
        if core.startswith(st):
            core = core[len(st):]
            break
    core = core.lstrip("（(【[：: 　")
    if not core or not (core[0].isdigit() or core.startswith(("每年", "每两年", "即"))):
        return False
    n_date = sum(1 for ch in core
                 if ch.isdigit() or ch in "年月日时分至到前底上中旬～-—–")
    return n_date / len(core) >= 0.3


def extract_en(text_lines, year):
    """英文官网的简单抽取。"""
    best_s, best_t = None, None
    for ln in text_lines:
        low = ln.lower()
        if any(lb in low for lb in EN_SIGNUP_LABELS) and DATE_RE.search(ln):
            best_s = _ensure_year(ln.strip()[:120], year)
        if any(lb in low for lb in EN_TIME_LABELS) and DATE_RE.search(ln):
            best_t = _ensure_year(ln.strip()[:150], year)
    return best_s, best_t


# ---------------------------------------------------------------------------
# 4. 页面发现
# ---------------------------------------------------------------------------
def discover_article_urls(html_text, base, limit=DEFAULT_MAX_PAGES, include_re=None):
    links = extract_links(html_text, base)
    scored = []
    seen = set()
    for anchor, href in links:
        sc = link_relevance(anchor, href, include_re)
        if sc <= 0 or href in seen:
            continue
        seen.add(href)
        scored.append((sc, anchor, href))
    scored.sort(key=lambda x: -x[0])
    return [(a, h) for _, a, h in scored[:limit]]


def fetch_text_page(url, cfg, year):
    """抓取一页并返回 (text_lines, title, final_url)。"""
    raw, final = fetch(url, timeout=cfg.get("timeout", DEFAULT_TIMEOUT))
    if raw is None:
        return None, None, None
    text = decode_html(raw)
    title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = re.sub(r"\s+", " ", html.unescape(title_m.group(1))).strip() if title_m else ""
    lines = strip_html(text)
    return lines, title, final


def collect_text(cfg, year):
    """按配置抓取并汇总所有可用正文行。返回 (lines列表, 标题列表, 错误信息)。"""
    mode = cfg.get("mode", "auto")
    if mode in ("spa", "manual"):
        return None, [], "跳过：官网为JS渲染/需人工（%s）" % cfg.get("note", "")
    urls = cfg.get("urls") or [cfg.get("link")]
    urls = [u for u in urls if u]
    if not urls:
        return None, [], "无可用URL"

    all_lines, titles, pages = [], [], []
    include_re = None
    if cfg.get("title_include"):
        include_re = re.compile(cfg["title_include"])
    for u in urls[:2]:
        raw, final = fetch(u, timeout=cfg.get("timeout", DEFAULT_TIMEOUT))
        if raw is None:
            continue
        text = decode_html(raw)
        lines = strip_html(text)
        title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        titles.append(re.sub(r"\s+", " ", html.unescape(title_m.group(1))).strip()
                      if title_m else "")
        if mode in ("article",):
            pages.append((lines, u))
        else:
            all_lines.extend(lines)
            if mode in ("auto", "list"):
                for a, h in discover_article_urls(text, u, cfg.get("max_pages", DEFAULT_MAX_PAGES),
                                                  include_re):
                    pages.append((a, h))
        time.sleep(REQUEST_INTERVAL)

    # 抓正文页（含“年份防线”：页面锚文本/标题的年份若早于现有数据，跳过）
    min_year = cfg.get("min_year")
    page_year_re = re.compile(r"20\d{2}")
    visited = set()
    for a, h in pages:
        if h in visited or len(visited) >= cfg.get("max_pages", DEFAULT_MAX_PAGES):
            continue
        ym = page_year_re.search(a or "")
        if min_year and ym and int(ym.group(0)) < min_year:
            continue
        visited.add(h)
        lines, title, _ = fetch_text_page(h, cfg, year)
        if lines:
            ym2 = page_year_re.search(title or "")
            if min_year and ym2 and int(ym2.group(0)) < min_year:
                continue
            all_lines.extend(lines)
            if title:
                titles.append(title)
        time.sleep(REQUEST_INTERVAL)

    return all_lines, titles, None


# ---------------------------------------------------------------------------
# 5. 主流程
# ---------------------------------------------------------------------------
def run_competition(comp, cfg, year, verbose):
    """抓取并抽取单个竞赛，返回 dict(signUp=..., time=..., status=..., detail=...)。"""
    result = {"signUp": None, "time": None, "status": "skip", "detail": ""}
    link = comp.get("link")
    if not link:
        result["detail"] = "无官网链接，跳过"
        return result
    cfg = dict(cfg, link=link)

    # 年份防线：现有数据里出现过的最大年份，作为“不早于”的下限
    min_year = None
    for fld in ("signUp", "time"):
        ys = [int(y) for y in YEAR_RE.findall(comp.get(fld, "") or "")]
        if ys:
            my = max(ys)
            min_year = my if min_year is None else max(min_year, my)
    cfg = dict(cfg, min_year=min_year)

    lines, titles, err = collect_text(cfg, year)
    if err:
        result["detail"] = err
        return result
    if not lines:
        result["detail"] = "抓取无内容"
        return result

    text_all = "\n".join(lines)
    title_all = " ".join(titles)
    yr_hint = year
    # 年份提示：优先取“不早于当前年、且不超过当前年+3”的最小年份，
    # 避免被首页更早/更晚的新闻标题带偏（如 CCSP 首页“2027年度…”、
    # 章程模板中的“2035年”字样）
    years_in_text = sorted({int(y) for y in YEAR_RE.findall(text_all + " " + title_all)})
    cand = [y for y in years_in_text if year <= y <= year + 3]
    if cand:
        yr_hint = min(cand)
    elif years_in_text:
        yr_hint = max(years_in_text)

    if cfg.get("lang") == "en":
        s, t = extract_en(lines, yr_hint)
        s_conf = t_conf = 1 if (s or t) else 0
    else:
        s, s_conf = _extract_signup(lines, title_all, yr_hint, cfg.get("signup_rx"))
        t, t_conf = _extract_time(lines, title_all, yr_hint, cfg.get("time_rx"))

    def _year_guard(new_text, old_text):
        """综合防线：不降级、不退化、不用过期数据覆盖有效数据。"""
        # 1) 新值年份整体早于旧值年份 → 拒绝
        new_years = [int(y) for y in YEAR_RE.findall(new_text)]
        old_years = [int(y) for y in YEAR_RE.findall(old_text or "")]
        if new_years and old_years and max(new_years) < max(old_years):
            return False
        # 2) 旧值比新值更结构化（分号/箭头分隔多阶段）→ 拒绝用单句覆盖
        if old_text and ("；" in old_text or "→" in old_text) and \
                ("；" not in new_text and "→" not in new_text):
            return False
        # 3) 两者都是“每年/每两年”周期型表述 → 稳定政策，无需刷新
        if ("每年" in (old_text or "") and "每年" in new_text) or \
           ("每两年" in (old_text or "") and "每两年" in new_text):
            return False
        # 4) 新值日期已全部过去，而旧值无日期或含未来日期 → 拒绝（过期信息不覆盖有效信息）
        n_dt, o_dt = _max_date(new_text), _max_date(old_text or "")
        if n_dt and n_dt < datetime.now() and (o_dt is None or o_dt >= datetime.now()):
            return False
        return True

    updated = []
    if s and s_conf >= 3 and _year_guard(s, comp.get("signUp")):
        result["signUp"] = s
        updated.append("signUp")
    if t and t_conf >= 3 and _year_guard(t, comp.get("time")):
        result["time"] = t
        updated.append("time")

    if updated:
        result["status"] = "updated"
        detail = []
        if result["signUp"]:
            detail.append(f"signUp={result['signUp']!r}")
        if result["time"]:
            detail.append(f"time={result['time']!r}")
        result["detail"] = "更新 " + "; ".join(detail)
    else:
        result["status"] = "low_conf"
        result["detail"] = (f"低置信度（signUp候选={s or '无'!r}, time候选={t or '无'!r}），保留原值")
    if verbose:
        result["titles"] = titles[:3]
    return result


def main():
    ap = argparse.ArgumentParser(description="按竞赛官网发布特点抓取报名/比赛时间并更新 data.json")
    ap.add_argument("--dry-run", action="store_true", help="只抓取解析，不写文件")
    ap.add_argument("--only", help="只处理指定竞赛 id，逗号分隔，如 4,30,102")
    ap.add_argument("--out", help="结果写入指定路径（替代 data.json，不碰原文件）")
    ap.add_argument("--verbose", action="store_true", help="打印每个竞赛的抓取细节")
    ap.add_argument("--year", type=int, default=datetime.now().year, help="赛季年份（默认当前年）")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单页超时秒数")
    args = ap.parse_args()

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    only_ids = None
    if args.only:
        only_ids = {int(x) for x in args.only.split(",") if x.strip()}

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats = {"updated": 0, "low_conf": 0, "failed": 0, "skipped": 0}

    for comp in data:
        cid = comp.get("id")
        if only_ids and cid not in only_ids:
            continue
        cfg = CONFIG.get(cid, {})
        if cid in SKIP_REASONS:
            cfg = dict(cfg, mode="manual", note=SKIP_REASONS[cid])

        name = comp.get("name", f"id={cid}")
        res = run_competition(comp, cfg, args.year, args.verbose)

        if res["status"] == "updated":
            if res.get("signUp"):
                comp["signUp"] = res["signUp"] + UPDATE_MARKER.format(now_str)
            if res.get("time"):
                comp["time"] = res["time"] + UPDATE_MARKER.format(now_str)
            stats["updated"] += 1
            flag = "OK  "
        elif res["status"] == "low_conf":
            stats["low_conf"] += 1
            flag = "~    "
        elif res["status"] == "skip":
            stats["skipped"] += 1
            flag = "SKIP "
        else:
            stats["failed"] += 1
            flag = "FAIL "

        print(f"[{flag}] id={cid:<3} {name[:28]:<28} {res['detail']}")
        if args.verbose and res.get("titles"):
            for tt in res["titles"]:
                print(f"       标题: {tt[:60]}")

    # 写回
    if args.dry_run:
        print(f"\n[dry-run] 共 {len(data)} 条，更新 {stats['updated']}，低置信保留 {stats['low_conf']}，"
              f"跳过 {stats['skipped']}，失败 {stats['failed']}。未写入文件。")
        return

    out_path = args.out or DATA_PATH
    if os.path.abspath(out_path) == os.path.abspath(DATA_PATH):
        # 备份原文件
        shutil.copy2(DATA_PATH, BACKUP_PATH)
        print(f"已备份原文件 -> {BACKUP_PATH}")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, out_path)
    print(f"已写入 {out_path}（更新 {stats['updated']} 条，低置信保留 {stats['low_conf']} 条，"
          f"跳过 {stats['skipped']} 条，失败 {stats['failed']} 条）")


if __name__ == "__main__":
    main()
