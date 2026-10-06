#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""译名表 ↔ 成品落地核对（只读）。

以**项目译名表**（xlsx）为权威，核对 `EPUB/` 中文成品是否按表落地：
对译名表每条条目，先看它的日文锚点（`Base_Ori`）是否出现在该作品的日文侧，
再检查对应译名（`Base_Trans`）是否出现在中文侧。

依据 `AGENTS.md`：系列名、专有名词与术语以本项目译名表为准；台版、网翻或维基
旧译名不要回改。因此「日文侧出现该锚点、中文侧却找不到表定译名」是需要人工确认
的信号——既可能是术语未落地／拼写偏差（如 `Miliphone` vs 表定 `Milliphone`），
也可能是**同形不同义**（表内条目是某作品的能力/组织名，本书里是普通词）。

为什么只报「日文有、中文无」：反向（中文有、日文无）无法用锚点定位，且中文侧
大量普通词会命中表内短条目，噪音过大。

判定口径：
  · **门禁顺序（不可颠倒）**：先做**折叠归一化**，再用**折叠后的锚点**匹配 X 版固有
    裁定表，命中后才按裁定写法判定——即「码位折叠 → 裁定表 → 落地判定」。
    折叠依据《Data_Translation 九列取值口径裁定》§5.3「不妥协写法」：译名表与裁定表
    写不妥协形式（注音小字假名、半角 ASCII），BW 源是印刷妥协形式（小字写成大字、
    半角英数写成全角），故两侧同时折叠（全角 ASCII→半角、小字假名→大字）。拿未折叠的
    锚点直接查清单，源侧的妥协码位（`＆`／`６`／大字假名）就对不上；
  · 归一化还去 `【】「」『』` 与空白（`【】` 按该裁定 §5／§6 是振假名范围标记，非名称
    的一部分），因此表内 `アンナ=シュプレンゲル` 能匹配原文 `アンナ＝シュプレンゲル`；
  · 文本一律**先剥 `<rt>/<rp>` 注音再剥标签**，避免注音串入正文；
  · **裁定表门禁**（`docs/translation-name-rulings.md`）：该表登记已决口径（含与灰机 Wiki
    译名表的人为固有差异）。命中项按**裁定写法**判定——成品用裁定写法即算落地
    （`form_kind=ruling`），都没有才报未落地；判定列标 `人读` 的条目跳过判定、
    报告里单列（`status=human_only`）；
  · 命中处前后若是假名或汉字，标记为 `suspect`（疑似更长词的子串，如
    表内 `ニック` 命中 `パニック`）；默认不计入未落地，可用 `--include-suspect` 纳入。

用法：
    python tools/check_translation_table.py --table <译名表.xlsx>
    python tools/check_translation_table.py --table <译名表.xlsx> --book S3_06
    python tools/check_translation_table.py --table <译名表.xlsx> --strict
    python tools/check_translation_table.py --table <译名表.xlsx> --sheet data --limit 200
    python tools/check_translation_table.py --table <译名表.xlsx> --audit-rulings

`--audit-rulings` 是**清单自身的门禁**：只核对「译名裁定总表 ↔ 译名表」，不跑成品
核对，报出四类问题（表侧应回填／与表不一致、`<rt>` 与 `Ruby_Ori`／`Ruby_Trans`
不一致、写法含全角 ASCII），有问题则退出 1。改完清单锚点后应重跑一次——锚点归一化
之后若不重查译名表，就会出现「锚点改对了、表侧却还空着」的漏项。

产物（默认 `.cache/epub-work/`）：
    translation-table-check.tsv    全部「日文有」条目：作品/锚点/译名/类型/状态/是否疑似/是否命中裁定表/实际写法/日文上下文
    translation-table-check.json   结构化结果（含统计）
    translation-table-check.md     摘要 + 裁定表命中 + 未落地清单（可直接贴进复核报告）
    rulings-audit.tsv / .md         `--audit-rulings` 的清单一致性核对报告

退出码：0 正常；1 `--strict` 且存在未落地项、或 `--audit-rulings` 检出问题；2 参数或环境错误。
只读：不修改 `EPUB/`、`.cache/` 正文，只写报告文件。
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EPUB = REPO_ROOT / "EPUB"
DEFAULT_JP = REPO_ROOT / ".cache" / "epub-work" / "japanese-text"
DEFAULT_OUT = REPO_ROOT / ".cache" / "epub-work"
DEFAULT_RULINGS = REPO_ROOT / "docs" / "translation-name-rulings.md"

# 剥注音与标签：先整段移除 <rt>/<rp>（含内容），再剥其余标签
RT_RE = re.compile(r"<(rt|rp)\b[^>]*>.*?</\1>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[\s\u3000]+")
BOOK_RE = re.compile(r"^\[([^\]]+)\]")
KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fc]")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
BRACKET_CHARS = "【】「」『』"

# 折叠归一化表（`Data_Translation_九列口径裁定.md` §5.3「不妥协写法」）：
# 译名表的 base_ori／ruby_ori 写**不妥协写法**（注音小字假名、半角 ASCII、半角 `=`），
# 而 BW 源为印刷做了两类妥协——注音小字假名写成大字（99.8% 的 <rt>）、半角英数符号
# 写成全角（`Ａ５＝＆％` 等）。该节因此要求：**检索源时对查询串与源串同时做折叠
# 归一化（小字→大字、全角→半角）**。本工具照此折叠两侧，否则 `レベル6シフト`
# （表）对 `レベル６シフト`（源）、`シープ&シープ` 对 `シープ＆シープ`、
# `カリキュラム` 对 `カリキユラム` 都会匹配失败而误报未落地。
_ASCII_FOLD = {chr(0xFF01 + i): chr(0x21 + i) for i in range(0x5E)}
_KANA_FOLD = {
    # 小字假名（拗音・促音・合拗音）→ 大字假名
    "ァ": "ア", "ィ": "イ", "ゥ": "ウ", "ェ": "エ", "ォ": "オ", "ッ": "ツ",
    "ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ", "ヮ": "ワ",
    "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お", "っ": "つ",
    "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ",
}
# 匹配用：两类折叠都做（§5.3「对查询串与源串同时折叠」）
_FOLD_TABLE = str.maketrans({**_ASCII_FOLD, **_KANA_FOLD})
# 注音**写法**核对用：只折叠全角 ASCII，保留假名大小字差异——否则 `ミヨルニル`
# （源的大字）与 `ミョルニル`（不妥协小字）会被折叠成同一串，大小字问题就检不出来了。
_ASCII_FOLD_TABLE = str.maketrans(_ASCII_FOLD)

STATUS_LANDED = "landed"
STATUS_MISSING = "missing"
STATUS_SETTLED = "settled"   # 已判定为工具误报／暂缓（见 alignment_rules.SETTLED_ANCHORS）
STATUS_HUMAN_ONLY = "human_only"   # 裁定表「判定」列标 `人读`：工具不判定，报告里单列
STATUS_PENDING_RULING = "pending_ruling"   # 同形例外中 status=待裁定：两个译法都成立、尚未定


class ToolError(Exception):
    """参数或环境错误（退出码 2），区别于「检出未落地项」（退出码 1）。"""


def fold(text: str) -> str:
    """把文本折叠到「不妥协写法」的对照形式：全角 ASCII → 半角、小字假名 → 大字。

    依据 `Data_Translation_九列口径裁定.md` §5.3：译名表写不妥协写法，源是印刷妥协
    形式，检索时两侧同时折叠。只用于**匹配**，不改写任何落盘文本。
    """
    return text.translate(_FOLD_TABLE)


def fold_ascii(text: str) -> str:
    """只做全角 ASCII → 半角（**保留**假名大小字），用于注音写法核对。"""
    return text.translate(_ASCII_FOLD_TABLE)


def norm_anchor(value: str) -> str:
    """归一化锚点／译名：折叠（全角 ASCII→半角、小字假名→大字）、去装饰括号与全部空白。

    `【】` 按该裁定 §5／§6 是**振假名范围标记**而非名称的一部分（主键 = `base_ori` 去
    `【】`），故一并去掉；两侧文本走同一套归一化，保证可比。
    """
    text = fold(value or "")
    for ch in BRACKET_CHARS:
        text = text.replace(ch, "")
    return WS_RE.sub("", text)


def strip_markup(raw: str) -> str:
    """XHTML → 纯正文文本：先剥注音、再剥标签，最后**反转义实体**。

    顺序不可颠倒：先剥标签再反转义，否则 `&lt;p&gt;` 反转义出的尖括号会被当成标签吃掉。
    成品里含 `&` 的术语必须还原才能比对——`R&amp;C超自然公司` 对应译名表的
    `R&C超自然公司`，不反转义就会误报未落地（译名表核验口径同样要求「反转义实体」）。
    """
    return html.unescape(TAG_RE.sub("", RT_RE.sub("", raw)))


def load_plain(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return strip_markup(raw)


RUBY_PAIR_RE = re.compile(r"<ruby\b[^>]*>(.*?)</ruby>", re.S | re.I)
RT_INNER_RE = re.compile(r"<rt\b[^>]*>(.*?)</rt>", re.S | re.I)
# 裁定表锚点列：含注音的锚点直接写成 <ruby>…</ruby>（不加反引号，见 §12 格式约定）
RUBY_ANCHOR_RE = re.compile(r"<ruby\b[^>]*>.*?</ruby\s*>", re.S | re.I)


def to_ruby_text(raw: str) -> str:
    """XHTML → **带注音的复合串文本**：`<ruby>基文<rt>注文</rt></ruby>` → `基文（注文）`。

    剥注音文本只能比基文，判定不了成品把注音写成了什么（`<rt>Gungnir</rt>` 与
    `<rt>冈格尼尔</rt>` 剥完都是「主神之枪」）。复合串让「基文 + 注音」成为可匹配的
    整体。多段 ruby（当て字逐字分解）按段展开，这类锚点的注音判定交人工。
    """
    def repl(match):
        inner = match.group(1)
        rt = RT_INNER_RE.search(inner)
        base = re.sub(r"<[^>]+>", "", RT_INNER_RE.sub("", inner)).strip()
        note = re.sub(r"<[^>]+>", "", rt.group(1)).strip() if rt else ""
        return f"{base}（{note}）" if note else base

    text = RUBY_PAIR_RE.sub(repl, raw or "")
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def load_ruby_plain(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return to_ruby_text(raw)


def book_id(dir_name: str) -> str:
    """从 `[S3_06]创约 …` 取出作品号 `S3_06`。"""
    m = BOOK_RE.match(dir_name)
    return m.group(1) if m else ""


def collect_books(root: Path, text_subdir: str, only: set[str],
                  ruby: bool = False) -> dict[str, str]:
    """收集 {作品号: 全书纯文本}。目录名形如 `[S3_06]…`。

    `ruby=True` 时输出**带注音的复合串文本**（`基文（注文）`），供注音判定使用。
    """
    books: dict[str, str] = {}
    if not root.is_dir():
        return books
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        bid = book_id(child.name)
        if not bid or (only and bid not in only):
            continue
        text_dir = child / text_subdir
        if not text_dir.is_dir():
            continue
        chunks: list[str] = []
        for f in sorted(text_dir.iterdir()):
            if f.suffix.lower() == ".xhtml":
                chunks.append(load_ruby_plain(f) if ruby else load_plain(f))
        if chunks:
            books[bid] = "\n".join(chunks)
    return books


def context_of(text: str, idx: int, anchor: str, width: int = 30) -> str:
    head = text[max(0, idx - width):idx]
    tail = text[idx + len(anchor):idx + len(anchor) + width]
    return f"…{head}【{anchor}】{tail}…".replace("\n", " ")


def is_suspect(text: str, idx: int, anchor: str) -> bool:
    """命中处前后若是假名或汉字，可能是更长词的一部分。"""
    before = text[idx - 1] if idx > 0 else ""
    after = text[idx + len(anchor)] if idx + len(anchor) < len(text) else ""
    return bool(KANA_RE.match(before) or KANA_RE.match(after)
                or CJK_RE.match(before) or CJK_RE.match(after))


def load_table(path: Path, sheet: str | None, ori_col: str, trans_col: str,
               type_col: str, debuts_col: str,
               ruby_ori_col: str = "Ruby_Ori",
               ruby_trans_col: str = "Ruby_Trans",
               ) -> tuple[list[dict[str, str]], list[str]]:
    """读译名表；优先复用 read_xlsx.load_sheet_data，缺失 openpyxl 时给出明确提示。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from read_xlsx import load_sheet_data  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ToolError(f"[错误] 无法导入 tools/read_xlsx.py：{exc}")

    if not path.is_file():
        raise ToolError(f"[错误] 译名表不存在：{path}")
    try:
        actual, headers, rows, _total = load_sheet_data(path, sheet=sheet)
    except RuntimeError as exc:
        raise ToolError(f"[错误] {exc}")
    except (ValueError, FileNotFoundError) as exc:
        raise ToolError(f"[错误] 读取译名表失败：{exc}")

    for col in (ori_col, trans_col):
        if col not in headers:
            raise ToolError(
                f"[错误] 工作表「{actual}」缺少列 {col}；现有列：{', '.join(headers)}")

    i_ori = headers.index(ori_col)
    i_tr = headers.index(trans_col)
    i_ty = headers.index(type_col) if type_col in headers else -1
    i_db = headers.index(debuts_col) if debuts_col in headers else -1
    i_ro = headers.index(ruby_ori_col) if ruby_ori_col in headers else -1
    i_rt = headers.index(ruby_trans_col) if ruby_trans_col in headers else -1

    entries: list[dict[str, str]] = []
    for row in rows:
        ori = (row[i_ori] if i_ori < len(row) else "") or ""
        tr = (row[i_tr] if i_tr < len(row) else "") or ""
        if not norm_anchor(ori):
            continue
        entries.append({
            "ori": ori.strip(),
            "trans": tr.strip(),
            "type": (row[i_ty] if 0 <= i_ty < len(row) else "") or "",
            "debuts": (row[i_db] if 0 <= i_db < len(row) else "") or "",
            # 注音列供 `audit_rulings` 对照清单的 <rt>（`compare` 用不到）
            "ruby_ori": ((row[i_ro] if 0 <= i_ro < len(row) else "") or "").strip(),
            "ruby_trans": ((row[i_rt] if 0 <= i_rt < len(row) else "") or "").strip(),
        })
    return entries, headers


def load_rulings(path: Path) -> dict[str, dict[str, object]]:
    """解析「译名裁定总表」的锚点表格（Markdown），供落地判定与清单自检共用。

    返回 {归一化日文锚点: {"forms": [可接受写法…], "raw": [原始裁定单元格…],
                          "labels": [义项标识…], "human_only": bool}}。

    解析规则与裁定表 §12 的格式约定一致：
      · 锚点列用反引号包裹，**一行的多个反引号内容都算锚点**（如 `魔術`／`魔術師`）；
      · **含注音的锚点写成裸 `<ruby>基文<rt>注文</rt></ruby>`（不加反引号）**，同样计入锚点
        （反引号会把标记当代码原样显示，预览里注音不渲染）；
      · 「裁定」列用 `／` 分隔多个可接受写法，中文括号注释不参与匹配；
      · 同一锚点的多条登记**合并为候选集合**（分层与同词异译按不同义项标识并列）；
      · 「判定」列为 `人读` 时跳过判定（条件式、分层、描述性或聚合条目）。

    写法列可以带 `<ruby>` 注音（如 `<ruby>主神之枪<rt>冈格尼尔</rt></ruby>`）；本函数
    只取基文参与匹配（成品侧同样先剥注音），注音层的判定另行处理。
    """
    if not path.is_file():
        return {}
    out: dict[str, dict[str, object]] = {}
    header: list[str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if len(cells) != len(header) or set("".join(cells)) <= set("-: "):
            continue
        ai = 1 if "角色" in header[0] else 0
        ri = next((n for n, name in enumerate(header) if name in ("裁定", "裁定标准形")), None)
        ji = next((n for n, name in enumerate(header) if name == "判定"), None)
        if ri is None or max(ai, ri) >= len(cells):
            continue
        anchors = re.findall(r"`([^`]+)`", cells[ai])
        # 含注音的锚点直接写成 <ruby>…</ruby>（不加反引号，否则预览不渲染注音）：
        # 反引号内容与 ruby 块一并算锚点，同一串只计一次
        anchors += [match.group(0) for match in RUBY_ANCHOR_RE.finditer(cells[ai])]
        anchors = list(dict.fromkeys(anchors))
        if not anchors:
            continue
        label = RUBY_ANCHOR_RE.sub("", re.sub(r"`[^`]+`", "", cells[ai])).strip("（）() ").strip()
        human = bool(ji is not None and ji < len(cells) and "人读" in cells[ji])
        forms: list[str] = []
        ruby_forms: list[str] = []
        for part in re.split(r"／", cells[ri]):
            # 剥中文括号注释与 Markdown 装饰（粗体／反引号），再剥标签取基文
            clean = re.sub(r"（[^）]*）|\([^)]*\)", "", part)
            form = strip_markup(clean).replace("**", "").replace("`", "").strip()
            if form and form not in ("—", "-") and form not in forms:
                forms.append(form)
            # 带注音的写法另存复合串（`基文（注文）`），供注音判定
            if "<rt" in part:
                ruby_form = to_ruby_text(clean).replace("**", "").replace("`", "").strip()
                if ruby_form and ruby_form not in ruby_forms:
                    ruby_forms.append(ruby_form)
        for anchor in anchors:
            key = norm_anchor(strip_markup(anchor))
            if not key:
                continue
            slot = out.setdefault(key, {"forms": [], "ruby_forms": [], "raw": [], "labels": [],
                                        "ori_raw": [], "alt_raw": [], "human_only": False})
            for form in forms:
                if form not in slot["forms"]:
                    slot["forms"].append(form)
            for ruby_form in ruby_forms:
                if ruby_form not in slot["ruby_forms"]:
                    slot["ruby_forms"].append(ruby_form)
            slot["raw"].append(cells[ri])
            slot["alt_raw"].append(cells[ri + 1] if ri + 1 < len(cells) else "")
            slot["labels"].append(label)
            slot["ori_raw"].append(anchor)
            slot["human_only"] = bool(slot["human_only"]) or human
    return out


def _rt_of(raw: str) -> str:
    """取单元格里 `<rt>` 的注音内容（无则空串）。"""
    m = re.search(r"<rt\b[^>]*>(.*?)</rt>", raw or "", re.S | re.I)
    return m.group(1).strip() if m else ""


# 全角 ASCII（U+FF01–U+FF5E）；`，` 与 `／` 是本文档自用的中文标点与分隔符，不算违规
_FULLWIDTH_ASCII_RE = re.compile(r"[\uff01-\uff5e]")
# 锚点列只查全角英数字母：日文原文的全角标点（？（）等）是正常写法，不算不妥协写法违规
FULLWIDTH_ALNUM_RE = re.compile(r"[Ａ-Ｚａ-ｚ０-９]")


def _fullwidth_hits(raw: str) -> list[str]:
    return [ch for ch in _FULLWIDTH_ASCII_RE.findall(raw or "") if ch not in "，／"]


def audit_rulings(rulings: dict[str, dict[str, object]],
                  entries: list[dict[str, str]]) -> list[dict[str, str]]:
    """核对「译名裁定总表」与译名表的一致性（只读，供 `--audit-rulings`）。

    报三类问题：

    | kind | 含义 |
    | --- | --- |
    | `anchor-fullwidth` | 锚点列含全角 ASCII，按不妥协写法应写半角（中文标点与分隔符 `／` 除外） |
    | `forms-empty` | 裁定列解析不出任何可接受写法（散文格式或漏填）→ 应改标 `人读` 或补写法 |
    | `ruby-mismatch` | 锚点的 `<rt>` 与译名表 `Ruby_Ori` 不一致 → 应修正 |
    | `alt-unfounded` | 候选列的写法在译名表里找不到来源、也没标来源 → 疑似无据登记 |
    | `homonym-unregistered` | 译名表同一锚点有多种译法，但裁定表未登记 → 收敛时无从判断取哪个 |

    同名异物（同一锚点在表内多行）时，各候选都会列出，由人工判断该取哪一行。
    """
    index: dict[str, list[dict[str, str]]] = {}
    for e in entries:
        index.setdefault(norm_anchor(e["ori"]), []).append(e)

    problems: list[dict[str, str]] = []

    def add(kind: str, key: str, col: str, cur: str, expect: str, note: str = "") -> None:
        problems.append({"kind": kind, "anchor": key, "col": col,
                         "current": cur, "expected": expect, "note": note})

    for key, v in rulings.items():
        ori_raw = " ".join(v.get("ori_raw", []))
        hits = sorted(set(FULLWIDTH_ALNUM_RE.findall(ori_raw)))
        if hits:
            add("anchor-fullwidth", key, "锚点", ori_raw, "".join(hits),
                "不妥协写法：全角英数字母写半角 ASCII")

        if not v.get("forms") and not v.get("human_only"):
            add("forms-empty", key, "裁定", "（空）", "至少一个写法",
                "散文格式的裁定列应改标 `人读` 或补写法")

        if ori_raw.count("<ruby") > 1:
            continue      # 多段 ruby 结构（当て字逐字分解等）：注音比对交人工，避免拼接误报
        for e in index.get(key, []):
            rt_list = _rt_of(ori_raw)
            rt_table = (e.get("ruby_ori") or "").strip()
            # 注音写法比较只折叠全角 ASCII：假名大小字差异正是要检出的问题
            if rt_list and rt_table and fold_ascii(rt_list).strip() != fold_ascii(rt_table).strip():
                add("ruby-mismatch", key, "锚点", rt_list, rt_table, "锚点 <rt> 与表内 Ruby_Ori 不一致")

    # 候选列依据：只核对**声称了来源**的候选——候选列本来就包含从没落地过的候选（「势力」
    # 这类被否决的译法），它们不在译名表里是正常的，不能一律判无据。真正要拦的是
    # 「标成表内值、但表里并没有这个写法」那种误登记（2026-10-05 废弃的「表内原值」标注）。
    table_forms = {norm_anchor(e.get("trans", "")) for e in entries}
    table_forms.discard("")
    for key, v in rulings.items():
        for alt in v.get("alt_raw", []):
            if not alt or ("表内原值" not in alt and "译名表当前值" not in alt):
                continue
            first = re.split(r"／|（|\(", alt)[0].strip().strip("`*")
            if first and norm_anchor(first) not in table_forms:
                add("alt-unfounded", key, "候选", first, "译名表当前值",
                    "候选列标为表内值，但译名表里没有该写法")

    # 同词异译登记：译名表同一锚点有多种译法时，必须已在裁定表登记义项
    homonyms: dict[str, set[str]] = {}
    for e in entries:
        k = norm_anchor(e.get("ori", ""))
        if k:
            homonyms.setdefault(k, set()).add(norm_anchor(e.get("trans", "")))
    for k, forms in sorted(homonyms.items()):
        forms.discard("")
        if len(forms) > 1 and k not in rulings:
            add("homonym-unregistered", k, "锚点", "／".join(sorted(forms)), "在裁定表登记义项",
                f"译名表同锚点有 {len(forms)} 种译法，裁定表未登记")

    return problems


def run_audit_rulings(rulings_path: Path, entries: list[dict[str, str]],
                     table_path: Path, out_dir: Path) -> int:
    """`--audit-rulings` 的执行体：核对裁定表与译名表，写报告并返回退出码。"""
    rulings = load_rulings(rulings_path)
    if not rulings:
        print(f"[错误] 未加载到译名裁定总表：{rulings_path}", file=sys.stderr)
        return 2

    problems = audit_rulings(rulings, entries)
    out_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = out_dir / "rulings-audit.tsv"
    md_path = out_dir / "rulings-audit.md"

    fields = ["kind", "anchor", "col", "current", "expected", "note"]
    with tsv_path.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(problems)

    by_kind = Counter(p["kind"] for p in problems)
    lines = [
        "# 译名裁定总表 ↔ 译名表 一致性核对",
        "",
        f"- 裁定表：`{rulings_path.name}`（{len(rulings)} 条锚点）",
        f"- 译名表：`{table_path.name}`（{len(entries)} 条）",
        f"- **问题 {len(problems)} 条**",
        "",
    ]
    for kind, n in by_kind.most_common():
        lines.append(f"- `{kind}`：{n}")
    lines += ["", "| 类型 | 锚点 | 列 | 现值 | 期望 | 备注 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for p in problems:
        lines.append("| {kind} | {anchor} | {col} | {cur} | {exp} | {note} |".format(
            kind=p["kind"], anchor=p["anchor"], col=p["col"],
            cur=p["current"][:80].replace("|", "\\|"),
            exp=p["expected"][:80].replace("|", "\\|"), note=p["note"]))
    if not problems:
        lines.append("| — | — | — | — | — | 无 |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"译名裁定总表 ↔ 译名表：裁定 {len(rulings)} 条 / 表 {len(entries)} 条 "
          f"→ 问题 {len(problems)} 条")
    for kind, n in by_kind.most_common():
        print(f"    {kind}: {n}")
    for p in problems[:20]:
        print(f"  [{p['kind']}] {p['anchor']} · {p['col']}")
        print(f"      现：{p['current'][:70]}")
        print(f"      期望：{p['expected'][:70]}  {p['note']}")
    if len(problems) > 20:
        print(f"  …… 其余 {len(problems) - 20} 条见报告")
    print(f"  报告：{tsv_path.name} / {md_path.name}（{out_dir}）")
    return 1 if problems else 0


def compare(entries: list[dict[str, str]], jp_books: dict[str, str],
            cn_texts: dict[str, str],
            rulings: dict[str, dict[str, str]] | None = None,
            translation_host: dict[str, str] | None = None,
            settled_anchors: dict[str, str] | None = None,
            jp_ruby: dict[str, str] | None = None,
            cn_ruby: dict[str, str] | None = None,
            ) -> tuple[list[dict[str, str]], int, list[str]]:
    """核心比对：返回 (记录列表, 跳过的空译名数, 可比对作品号)。

    输入的 `jp_books` / `cn_texts` 应为**已剥标签的纯文本**（`collect_books` 的输出）。
    匹配在**归一化文本**上进行（与锚点同一套归一化：全角 `＝`→半角 `=`、去
    `【】「」『』` 与空白），否则表内 `アンナ=シュプレンゲル` 匹配不到原文
    `アンナ＝シュプレンゲル`；报告里的 `jp_context` 也取自归一化文本。

    `rulings` 是 **裁定表门禁**（`load_rulings` 的产物）：命中的锚点按**裁定写法**判定——
    成品用裁定写法即算落地（`form_kind=ruling`）；裁定列标 `人读` 的条目跳过判定
    （`status=human_only`，报告里单列）。这样「与灰机 Wiki 译名表的人为固有差异」
    不会被误报成术语未落地。

    `translation_host` 是**译文归属映射**（`alignment_rules.TRANSLATION_HOST`）：
    某作品的部分中文译文落在另一本书时（如 S5_02_03 的中文后记归入 S5_02_01），
    只在本作品的中文侧找会误报未落地。给了映射后，自己书未命中时**再到归属书找**，
    命中则在 `cn_host` 标出实际所在的书。

    记录字段：book / ori / trans / type / debuts / status / suspect /
    rulings / form_kind / cn_host / jp_context。
    `status` 为 landed（日文有、中文有可接受写法）或 missing（日文有、中文无）。
    """
    rulings = rulings or {}
    translation_host = translation_host or {}
    # 登记表按**自然写法**维护，这里统一折叠成与 `ori` 同一套归一化形式再查
    # （否则含小字假名的锚点对不上：`ヒュドラ` → `ヒユドラ`、`ロッド` → `ロツド`）
    settled_anchors = {norm_anchor(k): v for k, v in (settled_anchors or {}).items()}
    shared = sorted(set(jp_books) & set(cn_texts))
    jp_norm = {b: norm_anchor(jp_books[b]) for b in shared}
    jp_ruby_norm = {b: norm_anchor(v) for b, v in (jp_ruby or {}).items()}
    cn_ruby_norm = {b: norm_anchor(v) for b, v in (cn_ruby or {}).items()}
    # 中文侧归一化**覆盖全部中文书**（不只两侧都有的）：译文归属书可能只在中方存在，
    # 只按 shared 建表会让 TRANSLATION_HOST 永远查不到归属书。
    cn_norm = {b: norm_anchor(t) for b, t in cn_texts.items()}
    jp_charsets = {b: set(jp_norm[b]) for b in shared}
    records: list[dict[str, str]] = []
    skipped_empty_trans = 0

    for e in entries:
        ori = norm_anchor(e["ori"])
        tr = norm_anchor(e["trans"])
        if len(ori) < 2:
            continue
        if not tr:
            # 表内该条目的译名尚未定（Base_Trans 为空），无从核对
            skipped_empty_trans += 1
            continue
        rd = rulings.get(ori)
        forms = [norm_anchor(v) for v in (rd["forms"] if rd else [])]
        forms = [v for v in forms if v]
        ruby_forms = [norm_anchor(v) for v in (rd.get("ruby_forms", []) if rd else [])]
        ruby_forms = [v for v in ruby_forms if v]
        human_only = bool(rd["human_only"]) if rd else False

        def hit(text: str) -> tuple[bool, str]:
            """在给定中文文本里找可接受写法 → (是否命中, form_kind 标记)。"""
            if forms:
                # 长写法优先：否则「妹妹」会因是「妹妹们」的子串而误判
                for form_text in sorted(forms, key=len, reverse=True):
                    if form_text in text:
                        return True, "ruling"
                return False, ""
            return (tr in text), ""

        for bid in shared:
            # 字符集预筛：锚点全部字符都在该书字符集内，才做子串查找
            if not set(ori) <= jp_charsets[bid]:
                continue
            jp_text = jp_norm[bid]
            idx = jp_text.find(ori)
            if idx < 0:
                continue
            suspect = is_suspect(jp_text, idx, ori)

            settled = settled_anchors.get(ori)
            # 同形例外只在该锚点被判定过的那本书内抑制。`settled`（已判定为同形不同义）
            # 始终抑制——它讲的正是「表内义项 ≠ 正文义项」，裁定表登记的是表内那个义项，
            # 不该因此把正文义项也放行；只有 `待裁定`（两案都成立、尚未定）在裁定表
            # 登记该锚点后才失效、改按裁定判定。
            pending_settled = isinstance(settled, dict) and settled.get("status") == "待裁定"
            if settled is not None and not (pending_settled and ori in rulings) and (
                    not isinstance(settled, dict) or not settled.get("scope")
                    or settled.get("scope") == bid):
                settled_status = (STATUS_PENDING_RULING
                                  if isinstance(settled, dict) and settled.get("status") == "待裁定"
                                  else STATUS_SETTLED)
                records.append({
                    "book": bid,
                    "ori": e["ori"],
                    "trans": e["trans"],
                    "type": e["type"],
                    "debuts": e["debuts"],
                    "status": settled_status,
                    "suspect": "1" if suspect else "",
                    "rulings": "",
                    "form_kind": "",
                    "cn_host": "",
                    "jp_context": context_of(jp_text, idx, ori),
                })
                continue

            if human_only:
                # 条件式／分层／描述性／聚合条目：工具不判定，报告里单列
                records.append({
                    "book": bid,
                    "ori": e["ori"],
                    "trans": e["trans"],
                    "type": e["type"],
                    "debuts": e["debuts"],
                    "status": STATUS_HUMAN_ONLY,
                    "suspect": "1" if suspect else "",
                    "rulings": "1",
                    "form_kind": "",
                    "cn_host": "",
                    "jp_context": context_of(jp_text, idx, ori),
                })
                continue

            landed, form = hit(cn_norm[bid])
            # 注音判定：裁定条目带注音要求、且该书日文侧存在带注音的该锚点时，
            # 中文侧必须出现裁定的复合串（`基文（注文）`）——否则视为注音未落地
            if landed and ruby_forms and jp_ruby is not None and cn_ruby is not None:
                if f"{ori}(" in jp_ruby_norm.get(bid, ""):   # 归一化已把全角括号折叠为半角
                    if not any(rf in cn_ruby_norm.get(bid, "") for rf in ruby_forms):
                        landed, form = False, ""
            cn_host = ""
            host = translation_host.get(bid, "")
            if not landed and host and host in cn_norm:
                landed, form = hit(cn_norm[host])
                if landed:
                    cn_host = host
            records.append({
                "book": bid,
                "ori": e["ori"],
                "trans": e["trans"],
                "type": e["type"],
                "debuts": e["debuts"],
                "status": STATUS_LANDED if landed else STATUS_MISSING,
                "suspect": "1" if suspect else "",
                "rulings": ("1" if rd else ""),
                "form_kind": form,
                "cn_host": cn_host,
                "jp_context": context_of(jp_text, idx, ori),
            })
    return records, skipped_empty_trans, shared


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="译名表 ↔ 成品落地核对（只读）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", required=True, help="项目译名表 .xlsx（必需）")
    ap.add_argument("--sheet", default="data", help="工作表名（默认 data）")
    ap.add_argument("--ori-col", default="Base_Ori", help="日文锚点列名（默认 Base_Ori）")
    ap.add_argument("--trans-col", default="Base_Trans", help="译名列名（默认 Base_Trans）")
    ap.add_argument("--type-col", default="Type", help="类型列名（默认 Type）")
    ap.add_argument("--debuts-col", default="Debuts", help="出场列名（默认 Debuts）")
    ap.add_argument("--ruby-ori-col", default="Ruby_Ori", help="日文注音列名（默认 Ruby_Ori）")
    ap.add_argument("--ruby-trans-col", default="Ruby_Trans", help="中文注音列名（默认 Ruby_Trans）")
    ap.add_argument("--audit-rulings", action="store_true",
                    help="只核对「译名裁定总表 ↔ 译名表」的一致性（不跑成品核对）："
                         "表侧为空/不一致、<rt> 与 Ruby_Ori／Ruby_Trans 不一致、"
                         "写法含全角 ASCII；有问题则非 0 退出")
    ap.add_argument("--book", action="append", default=[],
                    help="只检查指定作品号（如 S3_06），可重复；默认全库")
    ap.add_argument("--epub", default=str(DEFAULT_EPUB), help="中文成品根目录（默认 EPUB/）")
    ap.add_argument("--jp-dir", default=str(DEFAULT_JP),
                    help="日文缓存根目录（默认 .cache/epub-work/japanese-text）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="报告输出目录")
    ap.add_argument("--rulings", default=str(DEFAULT_RULINGS),
                    help="译名裁定总表（默认 docs/translation-name-rulings.md）；"
                         "命中的锚点按裁定写法判定，不报未落地")
    ap.add_argument("--no-rulings", action="store_true",
                    help="跳过 裁定表门禁（仅用于诊断）")
    ap.add_argument("--include-suspect", action="store_true",
                    help="把疑似子串命中（suspect）也计入未落地")
    ap.add_argument("--limit", type=int, default=0, help="只检查前 N 条条目（调试用）")
    ap.add_argument("--strict", action="store_true", help="存在未落地项时非 0 退出")
    args = ap.parse_args(argv)

    table_path = Path(args.table).expanduser()
    try:
        entries, headers = load_table(table_path, args.sheet, args.ori_col,
                                      args.trans_col, args.type_col, args.debuts_col,
                                      args.ruby_ori_col, args.ruby_trans_col)
    except ToolError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.limit > 0:
        entries = entries[:args.limit]

    rulings_path = Path(args.rulings).expanduser()
    if args.audit_rulings:
        return run_audit_rulings(rulings_path, entries, table_path, Path(args.out))

    only = {b.strip() for b in args.book if b.strip()}
    jp_books = collect_books(Path(args.jp_dir), "item/xhtml", only)
    cn_books = collect_books(Path(args.epub), "OEBPS/Text", only)

    if not cn_books:
        print(f"[错误] 中文成品侧没有可用书籍：{args.epub}", file=sys.stderr)
        return 2
    if not jp_books:
        print(f"[提示] 日文缓存侧没有可用书籍（{args.jp_dir}）；"
              f"先运行 ./tools/pull.ps1 建立缓存。", file=sys.stderr)

    # 只核对中日两侧都存在的作品
    shared = sorted(set(jp_books) & set(cn_books))
    print(f"译名表条目 {len(entries)} 条；日文侧 {len(jp_books)} 本、中文侧 {len(cn_books)} 本；"
          f"可比对 {len(shared)} 本")
    if not shared:
        print("[错误] 中日两侧没有共同作品号，无法核对。", file=sys.stderr)
        return 2

    # 字符集预筛：锚点全部字符都在该书字符集内，才做子串查找（大幅减少全库扫描）。
    # 传**全部**中文书：译文归属书（TRANSLATION_HOST 的值）可能只存在于中文侧。
    cn_texts = dict(cn_books)
    rulings = {} if args.no_rulings else load_rulings(Path(args.rulings).expanduser())
    # 注音判定：只有裁定表里存在带注音写法时才收集复合串文本（内存约翻倍，按需启用）
    need_ruby = any(rd.get("ruby_forms") for rd in rulings.values())
    jp_ruby = collect_books(Path(args.jp_dir), "item/xhtml", only, ruby=True) if need_ruby else None
    cn_ruby = collect_books(Path(args.epub), "OEBPS/Text", only, ruby=True) if need_ruby else None
    if args.no_rulings:
        print("[提示] 已按 --no-rulings 跳过 裁定表门禁。", file=sys.stderr)
    elif not rulings:
        print(f"[提示] 未加载到 译名裁定总表（{args.rulings}）；"
              f"该门禁用于避免把人为差异报成未落地。", file=sys.stderr)
    else:
        print(f"裁定表门禁：{len(rulings)} 条锚点（{Path(args.rulings).name}）")
    try:
        from alignment_rules import SETTLED_ANCHORS, TRANSLATION_HOST  # noqa: PLC0415
    except ImportError as exc:
        print(f"[提示] 未加载译文归属映射与已判定锚点（{exc}）；"
              f"跨书归属与已判定项可能被误报为待判。", file=sys.stderr)
        TRANSLATION_HOST = {}
        SETTLED_ANCHORS = {}
    translation_host_pairs = [f"{k}→{v}" for k, v in sorted(TRANSLATION_HOST.items())]
    if translation_host_pairs:
        print(f"译文归属映射：{len(translation_host_pairs)} 项"
              f"（{'、'.join(translation_host_pairs)}）")
    if SETTLED_ANCHORS:
        print(f"已判定锚点（不计待判）：{len(SETTLED_ANCHORS)} 条")
    records, skipped_empty_trans, shared = compare(entries, jp_books, cn_texts,
                                                   rulings, TRANSLATION_HOST,
                                                   SETTLED_ANCHORS,
                                                   jp_ruby, cn_ruby)
    del jp_books

    missing = [r for r in records if r["status"] == STATUS_MISSING]
    missing_real = [r for r in missing if not r["suspect"]]
    missing_suspect = [r for r in missing if r["suspect"]]
    host_hits = [r for r in records if r.get("cn_host")]
    settled_hits = [r for r in records if r["status"] == STATUS_SETTLED]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = out_dir / "translation-table-check.tsv"
    json_path = out_dir / "translation-table-check.json"
    md_path = out_dir / "translation-table-check.md"

    fields = ["book", "ori", "trans", "type", "debuts", "status", "suspect",
              "rulings", "form_kind", "cn_host", "jp_context"]
    with tsv_path.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    x_hits = [r for r in records if r["rulings"]]
    form_kind_x = [r for r in x_hits if r["form_kind"] == "x"]
    form_kind_table = [r for r in x_hits if r["form_kind"] == "table"]

    summary = {
        "table": str(table_path),
        "rulings": "" if args.no_rulings else str(args.rulings),
        "ruling_anchors": len(rulings),
        "sheet_headers": headers,
        "entries": len(entries),
        "skipped_empty_trans": skipped_empty_trans,
        "books_compared": len(shared),
        "books": shared,
        "hits": len(records),
        "landed": len(records) - len(missing),
        "missing": len(missing),
        "missing_real": len(missing_real),
        "missing_suspect": len(missing_suspect),
        "ruling_hits": len(x_hits),
        "form_kind_x": len(form_kind_x),
        "form_kind_table": len(form_kind_table),
        "translation_host": translation_host_pairs,
        "cn_host_hits": len(host_hits),
        "settled_anchors": len(SETTLED_ANCHORS),
        "settled_hits": len(settled_hits),
    }
    json_path.write_text(
        json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    lines = [
        "# 译名表 ↔ 成品落地核对",
        "",
        f"- 译名表：`{table_path.name}`（工作表列：{', '.join(headers)}）",
        f"- 比对作品：{len(shared)} 本（{'、'.join(shared)}）",
        f"- 译名表条目：{len(entries)}"
        + (f"（其中表定译名为空、跳过核对 {skipped_empty_trans} 条）" if skipped_empty_trans else ""),
        f"- 日文侧命中：{len(records)}（译名已落地 {summary['landed']}）",
        f"- **未落地：{len(missing)}**（其中疑似子串 {len(missing_suspect)}、待判 {len(missing_real)}）",
        f"- 裁定表门禁：{len(rulings)} 条锚点，命中 {len(x_hits)}"
        + (f"（裁定写法 {len(form_kind_x)}）" if x_hits else ""),
        f"- 译文归属映射：{len(translation_host_pairs)} 项"
        + (f"（{'、'.join(translation_host_pairs)}），命中 {len(host_hits)} 条"
           if translation_host_pairs else ""),
        f"- 已判定锚点（同形不同义／暂缓，**不计待判**）：{len(SETTLED_ANCHORS)} 条，命中 {len(settled_hits)} 条",
        "",
    ]
    if settled_hits:
        lines += [
            "## 已判定锚点命中（工具误报或暂缓，非缺陷）",
            "",
            "`alignment_rules.SETTLED_ANCHORS` 登记的锚点：表内是专名、正文是普通词，"
            "或已判定暂缓。逐条回原文判定过，不再计入待判。",
            "",
            "| 作品 | 日文锚点 | 表定译名 | 判定 |",
            "| --- | --- | --- | --- |",
        ]
        seen = set()
        for r in settled_hits:
            key = (r["book"], r["ori"])
            if key in seen:
                continue
            seen.add(key)
            note = SETTLED_ANCHORS.get(norm_anchor(r["ori"]), "")
            lines.append(f"| {r['book']} | {r['ori']} | {r['trans']} | {note} |")
        lines.append("")
    if host_hits:
        lines += [
            "## 跨书归属命中（译文在归属书里，非缺陷）",
            "",
            "`alignment_rules.TRANSLATION_HOST` 登记的归属：日文锚点在本作品、"
            "中文译文在另一本书。",
            "",
            "| 作品 | 日文锚点 | 表定译名 | 译文所在 | 日文上下文 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in host_hits:
            lines.append(f"| {r['book']} | {r['ori']} | {r['trans']} | {r['cn_host']} | {r['jp_context']} |")
        lines.append("")
    lines += [
        "## 裁定表命中（门禁已过，非缺陷）",
        "",
        "`docs/translation-name-rulings.md` 登记的人为取舍：两侧各自维持自身写法，"
        "不计入待改、不得按表回改。",
        "",
        "| 作品 | 日文锚点 | 表定译名 | 采用写法 | 日文上下文 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in x_hits:
        used = "X 版" if r["form_kind"] == "x" else ("表侧" if r["form_kind"] == "table" else "**均未见**")
        lines.append(f"| {r['book']} | {r['ori']} | {r['trans']} | {used} | {r['jp_context']} |")
    if not x_hits:
        lines.append("| — | — | — | — | 无 |")
    lines += [
        "",
        "## 待判未落地项（日文侧出现该锚点，中文侧未见表定译名）",
        "",
        "| 作品 | 日文锚点 | 表定译名 | 类型 | 日文上下文 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in missing_real:
        lines.append(f"| {r['book']} | {r['ori']} | {r['trans']} | {r['type']} | {r['jp_context']} |")
    if not missing_real:
        lines.append("| — | — | — | — | 无 |")
    lines += [
        "",
        "## 疑似子串命中（前后为假名/汉字，多为误报）",
        "",
        "| 作品 | 日文锚点 | 表定译名 | 日文上下文 |",
        "| --- | --- | --- | --- |",
    ]
    for r in missing_suspect:
        lines.append(f"| {r['book']} | {r['ori']} | {r['trans']} | {r['jp_context']} |")
    if not missing_suspect:
        lines.append("| — | — | — | 无 |")
    lines += [
        "",
        "> 判定提示：`AGENTS.md` 定「专有名词与术语以本项目译名表为准」，"
        "但 `docs/translation-name-rulings.md` 登记的人为固有差异**不计入待改、不得按表回改**"
        "（本工具已把该清单作为门禁先加载）。待判项既可能是术语未落地/拼写偏差（应改成品），"
        "也可能是**同形不同义**（表内条目是某作品的能力或组织名，本书里是普通词，无需处理）。",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"  日文侧命中 {len(records)} 条；已落地 {summary['landed']}；"
          f"未落地 {len(missing)}（待判 {len(missing_real)}／疑似子串 {len(missing_suspect)}）")
    print(f"  裁定表命中 {len(x_hits)} 条"
          + (f"（裁定写法 {len(form_kind_x)}）" if x_hits else ""))
    if host_hits:
        print(f"  跨书归属命中 {len(host_hits)} 条（译文在 "
              + "、".join(sorted({r["cn_host"] for r in host_hits})) + "）")
    if settled_hits:
        print(f"  已判定锚点命中 {len(settled_hits)} 条（同形不同义／暂缓，不计待判）")
    print(f"  报告：{tsv_path.name} / {json_path.name} / {md_path.name}（{out_dir}）")
    if missing_real:
        print("\n待判未落地项（前 20）：")
        for r in missing_real[:20]:
            print(f"  [{r['book']}] {r['ori']} → 表定「{r['trans']}」")
            print(f"        {r['jp_context'][:120]}")

    if args.strict:
        effective = missing if args.include_suspect else missing_real
        if effective:
            print(f"\n[阻断] --strict：存在 {len(effective)} 条未落地项", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
