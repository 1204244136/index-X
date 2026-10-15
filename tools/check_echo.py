#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呼应一致性检查（只读）：定位作品内"应当一致"的呼应点候选，供逐条回原文判定。

## 为什么需要它

同一句日文在作品内出现两次以上（台词被后文引述、同一说法复现、同一口癖），
中文两侧必须一致；只改一侧、或两侧各译各的，就会"呼应断裂"——
读者看到的是前后不一致，严重时后文引述的内容与前文原句矛盾。
这类断裂**不违反任何既有门禁**：行数对齐、XML、加粗、术语裁定都查不出来。

## 三类候选

| 类 | 信号 | 含义 |
| --- | --- | --- |
| 片段多译 | 同一日文片段（引号内或整行）在作品内出现多次，中文译法不一致 | 同一句话被译成多种说法 |
| 同源复现 | 日文两行高度相似（n-gram 倒排 + 序列相似度） | 原句与其引述/复现形态 |
| 引述回指 | 日语侧出现 `『…』` 嵌套引述，回全文找出处 | 引述处与被引处须对应 |

## 边界

只扫描、只报告，不判定、不写盘、不改书籍；判定与回改由人（或按流程复核）执行。
输出是**候选**而非结论：日文两侧本就不同内容的相近句式不构成呼应，需逐条排除。
命中数不设阈值——候选少不等于没有断裂，候选多也不等于都得改。

## 两类用法的关系（判定纪律）

`--book` 是**单本**扫描，输出候选；候选的**取形方向**不能只看本卷。同一句日文若在
卷内只有一个"局部多数"，而该说法在全库另有主流译法，按局部多数改就会改出全书孤例。
实测教训：S5_03_02 卷内 `そっと息を吐く` 以「吐气」居多（16:10），据此把一处「轻叹
一口气」改成「吐气」；但全库该说法其实是「叹气」占优（214 行中叹气 129、吐气 62），
改动方向与全书惯例相反，随后回退（commit cbee10ca）。

故判定涉及**高频叙述定型**（同一表达在全库出现数十次以上，如 `息を吐く`、`微笑む`、
`顔を上げる`）时，先用 `--convention` 取全库分布，再决定方向：

    python tools/check_echo.py --convention "そっと息を吐" --convention "呆れたように息を吐" \
        --convention-words "叹气,吐气,呼气"

多个 `--convention` 各成一组，按给出顺序取首个命中；`--convention-words` 是中文侧
词表，**词条按正则解释**（中文说法常被助词隔开，写 `叹[气了息]` 比写「叹气」可靠），
落在词表外的计入「未分类」。输出含匹配总数、各词占比与分卷分布（用于识别例外卷）。
只统计、不判定。

用法：
    python tools/check_echo.py --book S1_01 --book S1_02
    python tools/check_echo.py --book S1_01 --out .cache/epub-work/echo-check
    python tools/check_echo.py --convention "そっと息を吐" --convention-words "叹气,吐气"
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
from xhtml_text import text_of_without_ruby  # noqa: E402  注音剥除规则的唯一实现
from alignment_rules import (  # noqa: E402
    MANUAL_ALIGNMENT_HEADERS,
    NON_PAIR_WORK_IDS,
    PAIR_RULES,
    TEXTUAL_IMAGE_HEADERS,
)
from xhtml_structure import header_index, pair_structure_problems  # noqa: E402

KANA = r"\u3040-\u30ff"
HAN = r"\u4e00-\u9fff"
NORM_JP = re.compile(rf"[^{KANA}{HAN}A-Za-z0-9]")
NORM_CN = re.compile(rf"[^{HAN}A-Za-z0-9]")
QUOTE_PAIR = re.compile(r"[「『]([^「」『』]{2,120})[」』]")
CN_QUOTE_PAIR = re.compile(r"[「『“\"]([^「」『』“”\"]{2,80})[」』”\"]")
# 元数据行：head 区的 title／meta／link 与 XML 声明。各文件这些行往往同号，
# 不过滤会在「同源复现」里制造大量假对（实测 S6_24.06.07 报出 256 对，68 对是书名）。
META_LINE = re.compile(r"<\?xml|<!DOCTYPE|<title\b|<meta\b|<link\b", re.I)
# 长音／重复假名串（惨叫、拟声）。这类行彼此互配会造成大量假「同源复现」
# （实测 S6_24.06.07 的 190 对里 79 对属此类）。
LONG_VOWEL = re.compile(r"([\u3040-\u30ff\u30fc])\1{5,}")
# 平假名：引文含它才说明带语法成分（助词/活用），纯片假名或纯汉字的引文是专名。
HIRAGANA = re.compile(r"[\u3040-\u309f]")

DEFAULT_OUT = Path(".cache/epub-work/echo-check")
# 书目录名形如 `【作品号】标题`（兼容历史半角 `[]`）。惯例统计要按目录反查作品号。
WORK_DIR_RE = re.compile(r"^【([^】]+)】|^\[([^\]]+)\]")


def norm_jp(text: str) -> str:
    return NORM_JP.sub("", text)


def norm_cn(text: str) -> str:
    return NORM_CN.sub("", text)


def grams(text: str, n: int) -> set[str]:
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def find_book_dir(root: Path, work: str) -> Path | None:
    """按作品号定位目录，兼容全角【】与历史半角[]形态。"""
    if not root.is_dir():
        return None
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (f"【{work}】" in entry.name or f"[{work}]" in entry.name):
            return entry
    return None


def iter_works(cn_root: Path, jp_root: Path) -> list[str]:
    """枚举中日两侧都有书目录的作品号（取交集，避免无对照的作品刷告警）。"""
    def names(root: Path) -> set[str]:
        if not root.is_dir():
            return set()
        found: set[str] = set()
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            match = WORK_DIR_RE.match(entry.name)
            if match:
                found.add(match.group(1) or match.group(2))
        return found

    return sorted(names(cn_root) & names(jp_root))


def load_pairs(work: str, cn_root: Path, jp_root: Path) -> tuple[list[dict], list[str]]:
    """按共享表头与结构规则保守配对；返回 (可靠行记录, 跳过原因/告警)。"""
    work = work.upper()
    if work in NON_PAIR_WORK_IDS:
        return [], [f"{work}: 非同一形态，跳过按行配对"]
    notes: list[str] = []
    cn_dir_entry = find_book_dir(cn_root, work)
    jp_dir_entry = find_book_dir(jp_root, work)
    if cn_dir_entry is None:
        return [], [f"{work}: 中文成品目录未找到（{cn_root}）"]
    if jp_dir_entry is None:
        return [], [f"{work}: 日文参考目录未找到（{jp_root}）"]

    try:
        cn_by = header_index(cn_dir_entry)
        jp_by = header_index(jp_dir_entry)
    except ValueError as exc:
        return [], [f"{work}: {exc}；跳过该作品配对"]

    rows: list[dict] = []
    for seq in sorted(cn_by.keys() | jp_by.keys()):
        if seq in MANUAL_ALIGNMENT_HEADERS:
            notes.append(f"{work}: {seq} 人工对齐例外，跳过按行配对")
            continue
        if seq in TEXTUAL_IMAGE_HEADERS:
            notes.append(f"{work}: {seq} 文本化图片例外，跳过按行配对")
            continue
        if seq in PAIR_RULES:
            notes.append(f"{work}: {seq} 配对例外 {PAIR_RULES[seq]}，跳过按行配对")
            continue
        if seq not in cn_by:
            notes.append(f"{work}: 缺中文对照 {seq}（日文 {jp_by[seq].name}）")
            continue
        if seq not in jp_by:
            notes.append(f"{work}: 缺日文对照 {seq}（中文 {cn_by[seq].name}）")
            continue
        cn_file, jp_file = cn_by[seq], jp_by[seq]
        cn_lines = cn_file.read_text(encoding="utf-8").splitlines()
        jp_lines = jp_file.read_text(encoding="utf-8").splitlines()
        if len(cn_lines) != len(jp_lines):
            notes.append(f"{work}: {seq} 行数不等（cn={len(cn_lines)} jp={len(jp_lines)}），跳过配对")
            continue
        problems = pair_structure_problems(jp_lines, cn_lines)
        if problems:
            notes.extend(f"{work}: {seq} {problem}，跳过配对" for problem in problems)
            continue
        for i, (cn_raw, jp_raw) in enumerate(zip(cn_lines, jp_lines)):
            # 排除元数据行：各文件的 <title>／<meta>／<link> 与 XML 声明会在同一行号
            # 反复出现，制造大量假「同源复现」（实测 S6_24.06.07 因此报出 256 对，
            # 其中 68 对是各文件同一行的书名）。
            if META_LINE.search(jp_raw) or META_LINE.search(cn_raw):
                continue
            cn = text_of_without_ruby(cn_raw.encode("utf-8"))
            jp = text_of_without_ruby(jp_raw.encode("utf-8"))
            if not cn and not jp:
                continue
            rows.append({"seq": seq, "file": cn_file.name, "line": i + 1, "cn": cn, "jp": jp})
    return rows, notes


def fragment_key(text: str) -> str:
    """片段归一：只留假名/汉字/字母数字，且剥去行首行尾的引号与句读。

    同一句话的原句形态「…」与引述形态『…』必须归到同一键，
    行首省略号（`……、じゃあ`）也不得造成分叉。
    """
    return norm_jp(text.strip().strip("「」『』。、！？…‥—─ー～・")).lower()


# 中文侧的虚词/助词：仅这些字不同时，差异通常不承载语义（如「陪我」↔「跟我」）
CN_FUNCTION_CHARS = set("的了吗呢吧啊哦喔呀嘛么着过是在有和与跟同对从向往就都也才又还更最很挺太真")
# 同义替代组：不同字但可互换的常见译法（差异只发生在组内时判「虚词」级）
CN_SYNONYM_GROUPS = (
    frozenset("陪跟随"),
    frozenset("说讲道"),
    frozenset("看瞧望"),
    frozenset("拿取持"),
    frozenset("做作当"),
    frozenset("立站"),
)
# 译体词：同一日文名词的不同中文语体写法（差异可能抬高或降低语气）
CN_STYLE_WORDS = ("女孩", "少女", "女生", "女孩子")


def classify_cn_differences(rows: list[dict]) -> str:
    """给「同一日文片段、中文不一致」的组标注差异性质，用于降噪与优先级。

    - 虚词：差异只涉及虚词/助词或同义替代组（如「陪我」↔「跟我」）
    - 语体：差异涉及译体词（如「女孩」↔「少女」），可能抬高语气，须核原文语气层
    - 实词：差异涉及实词，最需要回原文（可能是真异译）

    三者都是**提示**而非判定：差异性质决定回原文时该看什么，不决定要不要统一。
    """
    def real_chars(text: str) -> set[str]:
        return {c for c in norm_cn(text) if c not in CN_FUNCTION_CHARS}

    def style_set(text: str) -> frozenset[str]:
        return frozenset(w for w in CN_STYLE_WORDS if w in text)

    styles = [style_set(r["cn"]) for r in rows]
    if len(set(styles)) > 1:
        return "语体"
    real = [real_chars(r["cn"]) for r in rows]
    all_diff: set[str] = set()
    for i in range(1, len(real)):
        all_diff |= real[0] ^ real[i]
    if all_diff:
        # 差异字是否全部落在同一个同义替代组内（「陪」↔「跟」这类）
        for group in CN_SYNONYM_GROUPS:
            if all_diff <= group:
                return "虚词"
        return "实词"
    if len({norm_cn(r["cn"]) for r in rows}) > 1:
        return "虚词"
    return "并列"


def frag_groups(rows: list[dict], min_len: int) -> list[tuple[str, list[dict]]]:
    """类 1：同一日文片段（引号内优先，兼取整行）在多行出现且中文不一致。"""
    index: dict[str, list[tuple[dict, str]]] = defaultdict(list)
    for row in rows:
        frags = [m.group(1) for m in QUOTE_PAIR.finditer(row["jp"])]
        stripped = row["jp"].strip("「」『』")
        if 12 <= len(norm_jp(stripped)) <= 200:
            frags.append(stripped)
        for frag in frags:
            key = fragment_key(frag)
            if len(key) >= min_len:
                index[key].append((row, frag))
    out: list[tuple[str, list[dict], str]] = []
    for key, items in index.items():
        if len(items) < 2:
            continue
        if len({norm_cn(row["cn"]) for row, _ in items}) < 2:
            continue
        seen: set[tuple[str, int]] = set()
        unique = []
        for row, _ in items:
            ident = (row["file"], row["line"])
            if ident in seen:
                continue
            seen.add(ident)
            unique.append(row)
        out.append((items[0][1], unique, classify_cn_differences(unique)))
    # 实词/语体级差异优先（那才是必须回原文判断的），虚词级差异排后
    order = {"实词": 0, "语体": 1, "虚词": 2, "并列": 3}
    out.sort(key=lambda x: (order.get(x[2], 9), -len(norm_jp(x[0]))))
    return out


def sim_pairs(rows: list[dict], n: int, threshold: float) -> list[tuple[dict, dict, float]]:
    """类 2：日文相似行对（同源复现/引述形态）。

    含长音／重复假名串的行（惨叫、拟声）不参与：它们彼此互配会产出大量假对。
    """
    docs = [r for r in rows
            if len(norm_jp(r["jp"])) >= 20 and not LONG_VOWEL.search(r["jp"])]
    inverted: dict[str, tuple[set[int], set[int]]] = defaultdict(lambda: (set(), set()))
    for idx, row in enumerate(docs):
        key = norm_jp(row["jp"])
        # 覆盖所有起点，避免单字插入/删除翻转奇偶性后丢失全部公共键。
        for k in range(len(key) - n + 1):
            inverted[key[k:k + n]][k % 2].add(idx)
    seen: set[tuple[int, int]] = set()
    out: list[tuple[dict, dict, float]] = []
    for even, odd in inverted.values():
        idxs = even | odd
        if len(idxs) > 40:
            # 全位置索引可能把旧稀疏桶推过高频上限，回退旧偶数桶以保留既有召回。
            idxs = even
        if not 2 <= len(idxs) <= 40:
            continue
        ordered = sorted(idxs)
        for a in range(len(ordered)):
            for b in range(a + 1, len(ordered)):
                pair = (ordered[a], ordered[b])
                if pair in seen:
                    continue
                seen.add(pair)
                left, right = docs[pair[0]], docs[pair[1]]
                ratio = difflib.SequenceMatcher(
                    None, norm_jp(left["jp"]), norm_jp(right["jp"])
                ).ratio()
                if ratio >= threshold:
                    out.append((left, right, ratio))
    out.sort(key=lambda x: -x[2])
    return out


def quote_relation(quote: str, source_jp: str) -> str:
    """引文与其出处之间的日语侧关系（归一后比较，标点与叙述框架不计）。

    - exact：逐字相同（出处侧的叙述框架在归一化时被剥掉，不影响判定）
    - within：引文包含于出处正文（引述被压缩、或出处本身更长）
    - wraps：出处正文包含于引文（**引述升级**：引述比被引处更完整更逐字，
      此时被引处措辞必须就是引述的版本，否则引述指向一个并不存在的说法）
    - fuzzy：n-gram 高度重合但互不包含（措辞有出入的引述）
    """
    q, s = norm_jp(quote), norm_jp(source_jp)
    if not q or not s:
        return "fuzzy"
    if q == s:
        return "exact"
    if q in s:
        return "within"
    if s in q:
        return "wraps"
    return "fuzzy"


def inner_cn(text: str) -> str:
    """取中文行最内层引号包裹的引文（无引号则返回原行）。

    引述处的整行含叙述与说话人框架，不能与出处行整行比较——那会把
    「神裂说道」这类框架差异误判成引文差异。
    """
    for pattern in (r"『([^『』]{2,120})』", r"[「“\"]([^「」『』“”\"]{2,120})[」”\"]"):
        inner = re.findall(pattern, text)
        if inner:
            return max(inner, key=len)
    return text


def marker_quotes(jp: str, min_len: int) -> list[str]:
    """从含引述助词的行里提取被引述的片段（`って` / `とか` 直接引述，或 `と`+引用动词）。

    日语引述不只用 `『…』`：「…って」「…とか」本身即可引述，且**改动引述措辞时
    更隐蔽**（历史案例：S1_01 第一章 L290 把 `つかないんだよって` 引述处改成
    「连一道伤痕都留不下」，而被引处 L288 并未使用同一措辞——当时工具抓不到这类）。
    该形态噪声高，调用方须再用「被引内容在作品内多处出现」等证据过滤。
    """
    out: list[str] = []
    # `って` / `とか` 直接引述（不要求后接引用动词）
    for m in re.finditer(r"([^。！？\n]{3,60}?)(?:って|とか)", jp):
        frag = m.group(1).strip("「」『』、。…—─ \u3000")
        if len(norm_jp(frag)) >= min_len:
            out.append(frag)
    # `と` + 引用动词（`と言った` 等），义项更确定
    for m in re.finditer(r"([^。！？\n]{4,60}?)と(言|告|思|繰り返|述|呼|聞)", jp):
        frag = m.group(1).strip("「」『』、。…—─ \u3000")
        if len(norm_jp(frag)) >= min_len:
            out.append(frag)
    return out


def cn_quotes_back(jp: str, cn: str) -> bool:
    """中文侧是否保留了「引述某处的说法」的标记。

    只要求「有引号」太宽（`「…」` 是台词常态，会淹没候选）；要求中文侧同时出现
    引号与**引述回指词**（说什么／说过／不记得／说什么来着…）才认。
    """
    if not CN_QUOTE_PAIR.search(cn):
        return False
    return any(w in cn for w in ("说什么", "说过", "不记得", "明明说", "什么来着", "什么话", "所谓"))


def quote_lookups(rows: list[dict], min_len: int, cover: float,
                  include_marker: bool = False) -> list[dict]:
    """类 3：日语侧 `『…』` 引文 -> 全文出处候选。

    每条候选带两项判定辅助：
    - `relation`：日语侧 exact／within／wraps／fuzzy（`wraps` 即「引述升级」，
      引述把简写补成了逐字句，被引处措辞必须与引述一致，否则引述指向一个
      并不存在的说法——最难自查的一类断裂）；
    - `cn_class`：中文侧引文与出处的差异性质（实词／语体／虚词／一致）。
    """
    bodies = [r for r in rows if len(norm_jp(r["jp"])) >= 6]
    inverted: dict[str, set[int]] = defaultdict(set)
    for idx, row in enumerate(bodies):
        for k in grams(norm_jp(row["jp"]), 4):
            inverted[k].add(idx)
    out: list[dict] = []
    seen: set[tuple[str, int, str, int, str]] = set()
    for row in bodies:
        # 两类引文来源：显式 `『…』`，以及引述助词标记（って／とか／と+引用动词）
        pending: list[tuple[str, str]] = [
            (m.group(1), "引用符") for m in re.finditer(r"『([^『』]{6,80})』", row["jp"])
        ]
        if include_marker:
            pending += [(frag, "引述助词") for frag in marker_quotes(row["jp"], max(4, min_len - 4))]
        for quote, kind in pending:
            key = norm_jp(quote)
            if len(key) < min_len:
                continue
            qgrams = grams(key, 4)
            score: dict[int, int] = defaultdict(int)
            for k in qgrams:
                for idx in inverted.get(k, ()):
                    score[idx] += 1
            matches = []
            row_pos = (row.get("seq", ""), row["line"])
            for idx, shared in score.items():
                candidate = bodies[idx]
                if candidate is row:
                    continue
                # 出处必须在引述处之前：引述是「回指前文」，出处在后的配对多为误配
                # （实测 S5_03_02 的 6/7 误配、S5_04_01 的 27/31 否决多属此类）。
                if (candidate.get("seq", ""), candidate["line"]) >= row_pos:
                    continue
                share = shared / max(1, len(qgrams))
                if share < cover:
                    continue
                # 出处行本身过短（如被省略号截断的术语 `（ニコラウスの……）`）不足以构成
                # 「被引述的说法」；实测 S3_03 的 11 条「升级」全属此类误判。
                if len(norm_jp(candidate["jp"])) < min_len:
                    continue
                relation = quote_relation(quote, candidate["jp"])
                # 仅 n-gram 相似而互不包含（fuzzy）的配对误配率高，要求更高覆盖率
                if relation == "fuzzy" and share < 0.8:
                    continue
                ident = (row["file"], row["line"], candidate["file"], candidate["line"], key)
                if ident in seen:
                    continue
                seen.add(ident)
                cn_class = classify_cn_differences([
                    {"cn": inner_cn(row["cn"])},
                    {"cn": inner_cn(candidate["cn"])},
                ])
                # 短引文 + 日语逐字同形 + 中文两侧一致 → 多为术语名复现，无断裂风险
                # （实测 S5_01_03 的 86 条里 79 条是『ブラフマーアストラ』这类专名引文）。
                if (relation == "exact" and len(key) < 12 and cn_class == "并列"):
                    continue
                # 引文不含平假名 = 纯专名或名词短语（如『ブラフマーアストラ』『破壊学園都市』），
                # 不承载「引述某处说法」的呼应；带语法成分的引文（如『簡単には殺さない』）才留。
                # `の` 是名词短语的连体助词，去掉它后仍无平假名的也归入此类
                # （如『ニコラウスの金貨』）。
                if not HIRAGANA.search(key.replace("の", "")):
                    continue
                matches.append({
                    "cover": share,
                    "row": candidate,
                    "relation": relation,
                    "cn_class": cn_class,
                    "upgrade": False,
                })
            if not matches:
                # 引述助词类：日文侧找不到出处，但中文译文用引号保留了「这是引述」
                # 的标记——正是「改写式引述」的高风险点（被引处措辞与引述不同）。
                # 历史案例：S1_01 L290「还说什么『伤不了一根汗毛』」对 L288
                # 「连一道伤痕都留不下」，日文两侧措辞本就不同。
                if include_marker and kind == "引述助词" and cn_quotes_back(row["jp"], row["cn"]):
                    out.append({"src": row, "quote": quote, "kind": kind, "hits": []})
                continue
            # 引述助词类噪声高：至少要有逐字命中，或中文侧保留了引号形态
            if include_marker and kind == "引述助词" and not (
                any(m["relation"] == "exact" for m in matches)
                or cn_quotes_back(row["jp"], row["cn"])
            ):
                continue
            rel_order = {"exact": 0, "wraps": 1, "within": 2, "fuzzy": 3}
            matches.sort(key=lambda m: (rel_order.get(m["relation"], 3), -m["cover"]))
            for m in matches:
                m["upgrade"] = m["relation"] == "wraps"
            out.append({"src": row, "quote": quote, "kind": kind, "hits": matches[:2]})
    # 「引述升级」置顶；无出处的改写式引述（待人工定位）次之；其余按日语关系强度
    def rank(c: dict) -> tuple[int, int]:
        if not c["hits"]:
            return (1, 9)
        if any(m["upgrade"] for m in c["hits"]):
            return (0, 0)
        rel = min({"exact": 0, "wraps": 1, "within": 2, "fuzzy": 3}.get(m["relation"], 3)
                  for m in c["hits"])
        return (2, rel)

    out.sort(key=rank)
    return out


def render(work: str, rows: list[dict], report: dict) -> tuple[str, str]:
    """返回 (候选明细 markdown, 统计摘要行)。"""
    lines = [f"# {work} 呼应候选清单（只读检测产物，判定须逐条回原文）", ""]
    lines.append(f"- 配对标：中文 `EPUB/【{work}】…/OEBPS/Text/` ↔ 日文 `.cache/…/japanese-text/【{work}】…/item/xhtml/`")
    lines.append(f"- 正文行数：{len(rows)}")
    lines.append("")

    frags = report["frag"]
    klass_count = {"实词": 0, "语体": 0, "虚词": 0, "并列": 0}
    for _, _, klass in frags:
        klass_count[klass] = klass_count.get(klass, 0) + 1
    lines.append(f"## 类 1 同一日文片段、中文不一致（{len(frags)} 组）")
    lines.append("")
    lines.append("同一句日文在作品内出现多次而中文译法不同：必须回原文确认是否应统一。")
    lines.append("")
    lines.append("**差异性质**（决定回原文时该看什么；本类按此优先级排序）：")
    lines.append("")
    lines.append(f"- **实词 {klass_count['实词']} 组**：差异涉及实词，优先核（可能是真异译）")
    lines.append(f"- **语体 {klass_count['语体']} 组**：差异是「女孩／少女」这类译体词——"
                 "**先核日语侧语气层**（`やっかなー` 式随口说法被译成郑重表态即是误改），"
                 "同义而语气相称的两种写法可以并存，不必强求字形一致")
    lines.append(f"- **虚词 {klass_count['虚词']} 组**：差异只在虚词/助词（如「陪我」↔「跟我」），"
                 "多数可并存；只在确认日语侧确需逐字一致时才统一")
    lines.append("")
    for i, (frag, items, klass) in enumerate(frags, 1):
        lines.append(f"### 1.{i}　〔{klass}〕 `{frag[:90]}`")
        for row in items:
            lines.append(f"- {row['file']}:{row['line']}　{row['cn'][:200]}")
        lines.append("")

    lines.append(f"## 类 2 日文相似行对（{len(report['pairs'])} 对）")
    lines.append("")
    lines.append("两侧日文高度相似：多为原句及其引述/复现形态，中文关键措辞应对应。")
    lines.append("")
    for i, (left, right, ratio) in enumerate(report["pairs"], 1):
        lines.append(f"### 2.{i} r={ratio:.2f}　{left['file']}:{left['line']} ↔ {right['file']}:{right['line']}")
        lines.append(f"- 日文A：{left['jp'][:180]}")
        lines.append(f"- 日文B：{right['jp'][:180]}")
        lines.append(f"- 中文A：{left['cn'][:180]}")
        lines.append(f"- 中文B：{right['cn'][:180]}")
        lines.append("")

    quotes = report["quotes"]
    n_upgrade = sum(1 for c in quotes if any(m["upgrade"] for m in c["hits"]))
    n_exact = sum(1 for c in quotes if any(m["relation"] == "exact" for m in c["hits"]))
    n_marker = sum(1 for c in quotes if c.get("kind") == "引述助词")
    lines.append(
        f"## 类 3 引述回指出处候选（{len(quotes)} 条：引用符 {len(quotes) - n_marker}／"
        f"引述助词 {n_marker}；其中引述升级 {n_upgrade} 条、逐字同形 {n_exact} 条）"
    )
    lines.append("")
    lines.append("核对被引处措辞是否与引文对应。「引述助词」类是 `って／とか／と+引用动词` 形态的"
                 "回指（不一定带引号），只在日语侧逐字命中时列出。")
    lines.append("")
    lines.append("**先看 `关系` 与 `中文差异` 两栏**：")
    lines.append("")
    lines.append("- `exact`（日语逐字同形）：被引处措辞应与引述一致——不一致即断裂，优先核；")
    lines.append("- `⤴升级`（`wraps`）：引述把简写补成了逐字句，被引处必须就是引述的那个版本，"
                 "否则引述指向一个并不存在的说法（**最难自查的一类**，本轮 S1_01 第一章的"
                 "「伤不了一根汗毛」即此型）；")
    lines.append("- `within`／`fuzzy`：引述对被引处做了压缩或改写，措辞可不逐字一致，但要核语义与语气。")
    lines.append("")
    for i, item in enumerate(quotes, 1):
        src = item["src"]
        kind = item.get("kind", "引用符")
        lines.append(f"### 3.{i}　〔{kind}〕 {src['file']}:{src['line']} 引述「{item['quote'][:70]}」")
        lines.append(f"- 引述处中文：{src['cn'][:200]}")
        if not item["hits"]:
            lines.append("- **出处未定位**：日文侧措辞与全文其他处不同（改写式引述），"
                         "中文却保留了引号形态——请人工核对被引处是否就是这句话、措辞是否一致")
        for m in item["hits"]:
            hit = m["row"]
            mark = "　**⤴升级**" if m["upgrade"] else ""
            lines.append(
                f"- 疑似出处 `{m['relation']}`{mark} / 中文差异 `{m['cn_class']}` / cov={m['cover']:.2f}"
                f"　{hit['file']}:{hit['line']}：{hit['cn'][:200]}"
            )
        lines.append("")

    summary = (
        f"{work}\t片段多译 {len(frags)} 组"
        f"（实词 {klass_count['实词']}／语体 {klass_count['语体']}／虚词 {klass_count['虚词']}）"
        f"\t同源复现 {len(report['pairs'])} 对"
        f"\t引述回指 {len(quotes)} 条"
        f"（升级 {n_upgrade}／同形 {n_exact}）"
    )
    return "\n".join(lines) + "\n", summary


def convention_stats(patterns: list[str], words: list[str], cn_root: Path, jp_root: Path,
                     books: list[str] | None = None) -> dict:
    """统计若干日文模式在全库的匹配行，以及中文侧落在给定词表上的分布。

    多个模式按给出顺序取首个命中（互斥分组）；不在任何模式内的行不参与统计。
    这是给「取形方向」提供全局依据的只读查询，不做任何判定。
    """
    group_res = [(p, re.compile(p)) for p in patterns]
    # 词条按正则解释：中文的说法在句中会被助词隔开（「叹气」多写作「叹了口气」），
    # 逐字串比对会大面积漏判（实测按字面比对时 92.5% 的行落进「未分类」）。
    word_res = [(w, re.compile(w)) for w in words]
    groups = [
        {"pattern": p, "hits": 0, "words": defaultdict(int), "other": 0,
         "other_samples": [], "by_work": defaultdict(lambda: defaultdict(int)), "rows": []}
        for p, _ in group_res
    ]
    works = list(dict.fromkeys(w.upper() for w in (books if books else iter_works(cn_root, jp_root))))
    notes: list[str] = []
    skipped_works: list[str] = []
    partial_works: list[str] = []
    matched_works: list[str] = []
    paired_works = paired_rows = 0
    if not works:
        if not cn_root.is_dir():
            notes.append(f"中文根目录不存在：{cn_root}")
        if not jp_root.is_dir():
            notes.append(f"日文根目录不存在：{jp_root}")
        if not notes:
            notes.append("中日作品目录无交集，未取到可靠配对行")
    for work in works:
        rows, work_notes = load_pairs(work, cn_root, jp_root)
        notes.extend(work_notes)
        if not rows:
            skipped_works.append(work)
            if not work_notes:
                notes.append(f"{work}: 未取到可靠配对行")
            continue
        paired_works += 1
        paired_rows += len(rows)
        if work_notes:
            partial_works.append(work)
        matched = False
        for row in rows:
            # 注音剥除会在 `<ruby>` 边界留下空白（日文行里写成 `呆 れ たように`），
            # 否则用户得自己写 `呆\s*れ`；匹配一律按连续文本，正则里不必带 \s。
            probe = re.sub(r"\s+", "", row["jp"])
            idx = next((i for i, (_, rx) in enumerate(group_res) if rx.search(probe)), None)
            if idx is None:
                continue
            matched = True
            group = groups[idx]
            group["hits"] += 1
            group["by_work"][work]["合计"] += 1
            hit = next((name for name, rx in word_res if rx.search(row["cn"])), None)
            if hit is None:
                group["other"] += 1
                group["by_work"][work]["（未分类）"] += 1
                if len(group["other_samples"]) < 5:
                    group["other_samples"].append(
                        f"{work}:{row['file']}:{row['line']}　{row['cn'][:40]}")
            else:
                group["words"][hit] += 1
                group["by_work"][work][hit] += 1
            group["rows"].append(
                f"- {work}:{row['file']}:{row['line']}　{hit or '（未分类）'}\n"
                f"    - JP {row['jp'][:80]}\n"
                f"    - CN {row['cn'][:80]}"
            )
        if matched:
            matched_works.append(work)
    return {
        "works": paired_works, "requested_works": len(works), "paired_rows": paired_rows,
        "matched_works": matched_works, "partial_works": partial_works, "skipped_works": skipped_works,
        "notes": notes, "words": words, "groups": groups,
    }


def render_convention(stats: dict, min_book: int = 5) -> tuple[str, str]:
    """渲染惯例统计：返回 (明细 Markdown, 终端摘要)。"""
    words = stats["words"]
    order = "/".join(words) + "/未分类"
    head = [f"# 全库惯例统计（作品 {stats['works']} 本）", "",
            f"词表：{'、'.join(words)}；下表的数字序为 {order}。", ""]
    summary = [f"=== 全库惯例统计（作品 {stats['works']} 本）===", f"词表：{'、'.join(words)}", ""]
    coverage = (
        f"覆盖：请求 {stats['requested_works']} 本；可靠配对 {stats['works']} 本；"
        f"模式命中 {len(stats['matched_works'])} 本；可靠配对行 {stats['paired_rows']}"
    )
    coverage_lines = [coverage]
    for label, key in (("部分覆盖", "partial_works"), ("零覆盖", "skipped_works")):
        if stats[key]:
            coverage_lines.append(f"{label}：{'、'.join(stats[key])}")
    if stats["notes"]:
        coverage_lines += ["", "配对告警与跳过原因："]
        coverage_lines += [f"- {note}" for note in stats["notes"]]
    head += coverage_lines + [""]
    summary += coverage_lines + [""]
    for group in stats["groups"]:
        total = group["hits"]
        head += [f"## {group['pattern']}　匹配 {total} 行", ""]
        summary += [f"[{group['pattern']}]  匹配 {total} 行"]
        if total == 0:
            head += ["（无匹配）", ""]
            summary += ["    （无匹配）", ""]
            continue
        for word in words:
            count = group["words"][word]
            head.append(f"- {word}：{count}（{count / total:.1%}）")
            summary.append(f"    {word}　{count:6d}　{count / total:6.1%}")
        head.append(f"- 未分类：{group['other']}（{group['other'] / total:.1%}）")
        summary.append(f"    未分类　{group['other']:6d}　{group['other'] / total:6.1%}")
        if group["other_samples"]:
            summary.append("      未分类样例（据此补词表）：")
            summary += [f"        {s}" for s in group["other_samples"]]
        head.append("")
        notable = []
        for work in sorted(group["by_work"]):
            counts = group["by_work"][work]
            if counts["合计"] < min_book:
                continue
            detail = "/".join([str(counts.get(w, 0)) for w in words] + [str(counts["（未分类）"])])
            notable.append(f"{work}（{counts['合计']} 行）：{detail}")
        if notable:
            head += [f"分卷分布（仅列 ≥{min_book} 行者；数字序为 {order}）", ""]
            head += [f"- {item}" for item in notable]
            head.append("")
            summary += [f"    分卷（≥{min_book} 行）："]
            summary += [f"      {item}" for item in notable]
            summary.append("")
        head += ["### 明细", ""]
        head += group["rows"]
        head.append("")
    return "\n".join(head), "\n".join(summary).rstrip()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="呼应一致性检查（只读，输出候选供回原文判定）")
    parser.add_argument("--book", action="append", default=[], help="作品号，如 S1_01；可重复")
    parser.add_argument("--root", type=Path, default=Path("EPUB"), help="中文成品根目录")
    parser.add_argument("--jp-root", type=Path, default=Path(".cache/epub-work/japanese-text"),
                        help="日文参考根目录")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出目录")
    parser.add_argument("--min-frag", type=int, default=12, help="片段多译的最短日文字数")
    parser.add_argument("--min-quote", type=int, default=8, help="引述回指的最短引文字数")
    parser.add_argument("--pair-threshold", type=float, default=0.5, help="同源复现的相似度阈值")
    parser.add_argument("--cover", type=float, default=0.5, help="引文在出处中的最低覆盖率")
    parser.add_argument("--include-marker-quotes", action="store_true",
                        help="额外扫描 `って／とか` 引述助词形态的回指（实验性：候选量大、"
                             "需人工筛，默认关闭）")
    parser.add_argument("--convention", action="append", default=[], metavar="REGEX",
                        help="惯例统计：给出日文正则（按连续文本写，行内空白会被忽略），"
                             "统计全库匹配行与中文侧词表分布；可重复，按给出顺序取首个命中。"
                             "此模式不需要 --book")
    parser.add_argument("--convention-words", default="",
                        help="惯例统计的中文词表，逗号分隔；词条按正则解释，如 "
                             "'叹[气了息]|叹息,吐[气了]|呼出'（中文说法常被助词隔开）")
    parser.add_argument("--convention-books", default="",
                        help="限定惯例统计的作品号，逗号分隔；缺省为全库")
    parser.add_argument("--convention-min-book", type=int, default=5,
                        help="分卷分布只列达到该行数的作品（默认 5）")
    args = parser.parse_args(argv)

    if args.convention:
        words = [w.strip() for w in args.convention_words.split(",") if w.strip()]
        books = [b.strip() for b in args.convention_books.split(",") if b.strip()]
        if not words:
            print("提示：未给 --convention-words，中文侧用词分布将全部计入「未分类」", file=sys.stderr)
        stats = convention_stats(args.convention, words, args.root, args.jp_root, books or None)
        text, summary = render_convention(stats, args.convention_min_book)
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / "convention.md"
        target.write_text(text, encoding="utf-8")
        print(summary)
        print(f"\n明细 -> {target}")
        return 0
    if not args.book:
        parser.error("需要 --book（呼应检查）或 --convention（惯例统计）")

    args.out.mkdir(parents=True, exist_ok=True)
    summaries = []
    all_notes: list[str] = []
    for work in args.book:
        rows, notes = load_pairs(work, args.root, args.jp_root)
        all_notes.extend(notes)
        if not rows:
            print(f"{work}: 未取到配对行，跳过", file=sys.stderr)
            continue
        report = {
            "frag": frag_groups(rows, args.min_frag),
            "pairs": sim_pairs(rows, 8, args.pair_threshold),
            "quotes": quote_lookups(rows, args.min_quote, args.cover, args.include_marker_quotes),
        }
        text, summary = render(work, rows, report)
        target = args.out / f"{work}-呼应候选.md"
        target.write_text(text, encoding="utf-8")
        summaries.append(summary)
        print(summary.replace("\t", "  ") + f"  -> {target}")

    if all_notes:
        print("\n告警：", file=sys.stderr)
        for note in all_notes:
            print("  " + note, file=sys.stderr)
    (args.out / "summary.md").write_text(
        "# 呼应候选统计\n\n" + "\n".join(f"- {s.replace(chr(9), '　')}" for s in summaries) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
