#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查中文缓存正文的「翻译与修嵌规范」符合性（EPUB 正文层）。只读。

依据《翻译与修嵌规范.docx》中「落实到 EPUB 最终正文」的条款检查，
排除仅为交稿制作服务的机制（|基文[注文] 注音、内联（*译注：）、空行规则、
docx 交稿格式、漫画修嵌），那些在 EPUB 成品中已转换为 ruby / Note 脚注页 /
固定行模板，不再反向检查。

检查类别（对剥离标签后的正文文本与 ruby/加粗标签逐行判定）：
  P1  半角标点（中文语境下应为全角）
  P2  半角波浪号 ~（应为 ～）
  P3  问叹顺序 ！？ （问号应在感叹号左边，统一为 ？！）
  P4  省略号写成连续句号（。。/。。。 应改 …）
  P5  省略号后带句号/点号（……。 ……・ 不保留）
  P6  弯引号 “” ‘’（中文语境应使用直角引号 「」『』）
  P7  日文点号 ・（与全书主导 · 不一致，规范提醒勿混淆）
  P8  正文假名残留（可能为漏翻；形状描述/原文引用属合法，需人工确认）
  P9  单位（公斤/公里，规范建议 千克/千米）
  P10 注音（ruby <rt> 内日文假名应译为汉语；空 rt / 缺 rt 提示）
  P11 语气词/音译（切！、啊啦 等规范示例词）
  P12 单个省略号 …（非 …… 连用）
  P13 连续 ASCII 空格（交稿残留或断断续续，需人工确认）
  P14 小数应使用阿拉伯数字（0.7），不得写成汉字数字+小数点（〇.七、三·五）

报告写入 .cache/epub-work/translation-spec-check.tsv / .json / .md。
只读，不修改缓存。
"""
import os
import re
import sys
import json
import argparse
import html
from collections import OrderedDict, Counter

from epub_ids import content_sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(REPO_ROOT, ".cache", "epub-work", "chinese-text")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, ".cache", "epub-work")

TAG_RE = re.compile(r"<[^>]*>")
# 整段移除 ruby 的 <rt> 注音（含内容），避免注音泄漏进正文文本检查
RT_FULL_RE = re.compile(r"<rt\b[^>]*>.*?</rt>", re.S)
# 整段移除内嵌 <style>/<script> 块（含内容）：CSS/JS 里的半角逗号、分号
# 不属于正文，若不整段移除会被误判为半角标点。属性 style="..." 已由 TAG_RE 剥掉。
STYLE_FULL_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.S | re.I)
SCRIPT_FULL_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)

def strip_to_text(line):
    """把一行原始 XHTML 转成纯正文文本：先整段移除 <style>/<script>/<rt> 块，
    再剥标签、反转义。外部 CSS（.css 文件）不在 XHTML 文本层，天然不进入检查。"""
    t = STYLE_FULL_RE.sub("", line)
    t = SCRIPT_FULL_RE.sub("", t)
    t = RT_FULL_RE.sub("", t)
    return unescape(strip_tags(t))

# CJK 表意文字 + 全角标点（用于判断“中文语境”）
CJKX = r"\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef\u3000-\u303f"
KANA = r"\u3041-\u3096\u30a1-\u30fa\u30fc"

# 文件分类：Afterwords/Note/Information 允许引用日文原文，不做假名检查
AFTER_RE = re.compile(r"_Afterwords")
NOTE_RE = re.compile(r"-Note\.xhtml$")
INFO_RE = re.compile(r"-Information\.xhtml$")
def classify(fn):
    if AFTER_RE.search(fn):
        return "after"
    if NOTE_RE.search(fn):
        return "note"
    if INFO_RE.search(fn):
        return "info"
    if content_sequence(fn) is not None:
        return "content"
    return "other"


# 每条检查：pattern -> (category, severity, message, flags)
# 全部在剥离标签的文本上执行；CJK 语境用后视/前视限定。
CHECK_TEXT = [
    # 半角标点：前后都是中文语境
    (re.compile(r"(?<=[%s])[,;](?=[%s])" % (CJKX, CJKX)), "P1", "error",
     "半角逗号/分号，中文语境应为全角，"),
    (re.compile(r"(?<=[%s])\.(?=[%s])" % (CJKX, CJKX)), "P1", "error",
     "半角句号/点，中文语境应为全角，"),
    (re.compile(r"(?<=[%s])\?(?=[%s])" % (CJKX, CJKX)), "P1", "error",
     "半角问号，应为全角？，"),
    (re.compile(r"(?<=[%s])!(?=[%s!?])" % (CJKX, CJKX)), "P1", "error",
     "半角感叹号，应为全角！，"),
    (re.compile(r"(?<=[%s]):(?=[%s])" % (CJKX, CJKX)), "P1", "error",
     "半角冒号，应为全角：，"),
    # 半角波浪号
    (re.compile(r"(?<=[%s])~|~(?=[%s])" % (CJKX, CJKX)), "P2", "error",
     "半角波浪号~，应为全角～，"),
    # 问叹顺序：问号应在感叹号左边
    (re.compile(r"！？"), "P3", "error",
     "感叹号在问号前，统一为？！（问号始终在感叹号左边），"),
    # 省略号写成连续句号
    (re.compile(r"。{2,}"), "P4", "error",
     "连续句号疑似省略号，应使用……，"),
    # 省略号后带句号/点号
    (re.compile(r"…+[。・.]"), "P5", "error",
     "省略号后保留句号/点号，按规范不保留，"),
    # 弯引号夹中文：前后均为中文语境
    (re.compile(r"(?<=[%s])[“”‘’](?=[%s])" % (CJKX, CJKX)), "P6", "error",
     "弯引号“”/‘’用于中文语境，应使用直角引号「」『』，"),
    (re.compile(r"(?<=[%s])[“”](?=[、。，；：？！」』）])" % CJKX), "P6", "error",
     "弯引号“”用于中文语境，应使用直角引号「」『』，"),
    (re.compile(r"(?<=[「『（、。，；：？！])[“”](?=[%s])" % CJKX), "P6", "error",
     "弯引号“”用于中文语境，应使用直角引号「」『』，"),
    # 日文点号 ・
    (re.compile(r"・"), "P7", "warning",
     "日文点号・，与全书主导的间隔号·不一致，建议统一（规范：勿与日文点号混淆），"),
    # 单位
    (re.compile(r"公斤|公里"), "P9", "warning",
     "单位“公斤/公里”，规范建议对应キロ用 千克/千米，"),
    # 语气词/音译（规范示例）
    (re.compile(r"(?<![\u3400-\u9fff])切！"), "P11", "info",
     "「切！」：规范示例建议「チッ！」译为「啧！」而非「切！」（排除“一切！”），"),
    (re.compile(r"啊啦"), "P11", "info",
     "「啊啦」：规范提示「あら」不译为「啊啦」，"),
    (re.compile(r"呀嘞呀嘞"), "P11", "info",
     "「呀嘞呀嘞」：规范提示「やれやれ」不译为「呀嘞呀嘞」，"),
    # 单个省略号（非 …… 连用）
    (re.compile(r"(?<![…])…(?![…])"), "P12", "info",
     "单个省略号…（未与另一个…组成……），请确认是否有意为之，"),
    # 连续 ASCII 空格（仅正文文件触发，标题行另行排除）
    (re.compile(r" {3,}"), "P13", "info",
     "连续 ASCII 空格（3+），疑似交稿残留或断断续续表达，请确认，"),
    # 小数用阿拉伯数字：汉字数字+小数点+汉字数字 不符合中文数字写法
    (re.compile(r"[〇零一二三四五六七八九][.．・·][〇零一二三四五六七八九]+"), "P14", "error",
     "小数应使用阿拉伯数字（如 0.7），不得写成汉字数字+小数点（如 〇.七、三·五），"),
]

# 假名残留（仅 content 文件）
KANA_RE = re.compile(r"[%s]" % KANA)
# ruby 注音检查（逐行原始文本）
RT_RE = re.compile(r"<rt\b[^>]*>([^<]*)</rt>")
RUBY_OPEN_RE = re.compile(r"<ruby\b")
RT_OPEN_RE = re.compile(r"<rt\b")


def unescape(t):
    return html.unescape(t)


def strip_tags(t):
    return TAG_RE.sub("", t)


def short(text, n=60):
    text = text.replace("\n", "␤").replace("\t", " ")
    return text if len(text) <= n else text[:n] + "…"


def check_text(line, fkind):
    """对剥离标签的文本跑 TEXT 检查，返回 (category, severity, message, example) 列表。

    先整段移除 <style>/<script>/<rt> 块避免 CSS、JS、注音泄漏，再剥标签、反转义。
    类别级豁免：
    - P7 日文点号・：Note 页引用日文原文属合法，跳过；
    - P13 连续空格：仅对正文内容文件判定，且跳过 h1/h2 标题行。
    """
    text = strip_to_text(line)
    hits = []
    if not text.strip():
        return hits
    for rx, cat, sev, msg in CHECK_TEXT:
        if cat == "P7" and fkind == "note":
            continue
        if cat == "P13" and (fkind != "content" or "<h1" in line or "<h2" in line):
            continue
        for m in rx.finditer(text):
            s = max(0, m.start() - 12)
            example = text[s:m.end() + 12]
            hits.append((cat, sev, msg, short(example, 72)))
    return hits


def check_ruby(line, fkind):
    """ruby 注音检查（基于原始行）。"""
    hits = []
    rt_opens = len(RT_OPEN_RE.findall(line))
    ruby_opens = len(RUBY_OPEN_RE.findall(line))
    if ruby_opens and rt_opens == 0:
        hits.append(("P10", "info", "ruby 标签缺少 <rt> 注音，请确认是否漏注音。", short(strip_tags(line), 50)))
    for m in RT_RE.finditer(line):
        content = m.group(1)
        if not content.strip():
            hits.append(("P10", "info", "注音 <rt> 内容为空。", short(strip_tags(line), 50)))
        elif fkind == "content" and KANA_RE.search(content):
            hits.append(("P10", "warning",
                         "注音 <rt> 含日文假名（%s），按规范日文注音应译为汉语（若为原文引用可忽略）。" % short(content, 20),
                         short(strip_tags(line), 50)))
    return hits


def check_kana(text, line_no, fn):
    hits = []
    for m in KANA_RE.finditer(text):
        s = max(0, m.start() - 10)
        example = text[s:m.end() + 20]
        hits.append(("P8", "warning",
                     "正文出现日文假名，疑似漏翻；若为形状描述（コ字形/く字形）、原文引用或特殊效果可忽略。",
                     short(example, 60)))
        break  # 每行只报一条
    return hits


def main():
    ap = argparse.ArgumentParser(
        description="检查中文缓存正文的翻译与修嵌规范符合性（EPUB 正文层，只读）")
    ap.add_argument("--cache", default=DEFAULT_CACHE, help="中文缓存根目录")
    ap.add_argument("--output", default=DEFAULT_OUTPUT, help="报告输出目录")
    ap.add_argument("--pattern", default=None, help="按书名子串筛选，如 '*S3_10*'")
    ap.add_argument("--top", type=int, default=12, help="报告里每类最多列出的样例数")
    args = ap.parse_args()

    root = args.cache
    findings = []          # (book, file, line, category, severity, message, example)
    per_book = OrderedDict()
    category_counts = Counter()
    severity_counts = Counter()
    books_checked = set()
    dedup = set()          # 去重键：(book, fn, ln, category)

    def emit(book, fn, ln, cat, sev, msg, ex):
        key = (book, fn, ln, cat)
        if key in dedup:
            return
        dedup.add(key)
        findings.append((book, fn, ln, cat, sev, msg, ex))
        category_counts[cat] += 1
        severity_counts[sev] += 1
        per_book[book][fn].setdefault(cat, []).append((ln, sev, msg, ex))

    for book in sorted(os.listdir(root)):
        text_dir = os.path.join(root, book, "OEBPS", "Text")
        if not os.path.isdir(text_dir):
            continue
        if args.pattern:
            pat = args.pattern.replace("*", ".*")
            if not re.search(pat, book):
                continue
        books_checked.add(book)
        per_book[book] = OrderedDict()
        for fn in sorted(os.listdir(text_dir)):
            if not fn.endswith(".xhtml"):
                continue
            fkind = classify(fn)
            path = os.path.join(text_dir, fn)
            try:
                lines = open(path, encoding="utf-8-sig").read().splitlines()
            except Exception:
                continue
            per_book[book][fn] = OrderedDict()
            for ln, line in enumerate(lines, 1):
                # ruby 检查（原始行）
                for hit in check_ruby(line, fkind):
                    cat, sev, msg, ex = hit
                    emit(book, fn, ln, cat, sev, msg, ex)
                # 文本检查（先移除 <style>/<script>/<rt> 块再剥标签）
                text = strip_to_text(line)
                for hit in check_text(line, fkind):
                    cat, sev, msg, ex = hit
                    emit(book, fn, ln, cat, sev, msg, ex)
                # 假名残留（仅正文内容文件）
                if fkind == "content":
                    for hit in check_kana(text, ln, fn):
                        cat, sev, msg, ex = hit
                        emit(book, fn, ln, cat, sev, msg, ex)

    # ---- 终端摘要 ----
    print("共检查 %d 本书。命中 %d 条（按类别：%s）。" % (
        len(books_checked), len(findings),
        ", ".join("%s=%d" % (c, n) for c, n in sorted(category_counts.items()))))
    for cat in ["P1", "P3", "P4", "P5", "P6", "P7", "P8"]:
        if category_counts.get(cat):
            print("  类别 %s 命中 %d 条" % (cat, category_counts[cat]))

    # ---- TSV ----
    os.makedirs(args.output, exist_ok=True)
    tsv_path = os.path.join(args.output, "translation-spec-check.tsv")
    with open(tsv_path, "w", encoding="utf-8") as f:
        f.write("book\tfile\tline\tcategory\tseverity\tmessage\texample\n")
        for book, fn, ln, cat, sev, msg, ex in sorted(findings):
            f.write("\t".join([book, fn, str(ln), cat, sev, msg, ex]).replace("\n", " ") + "\n")
    print("TSV 已写入: %s" % tsv_path)

    # ---- JSON ----
    json_path = os.path.join(args.output, "translation-spec-check.json")
    payload = {
        "scope": "chinese-text/**/OEBPS/Text/*.xhtml（EPUB 正文层）",
        "books_checked": len(books_checked),
        "total_findings": len(findings),
        "category_counts": dict(category_counts),
        "severity_counts": dict(severity_counts),
        "per_book": {b: {f: v for f, v in p.items() if v} for b, p in per_book.items()},
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("JSON 已写入: %s" % json_path)

    # ---- MD ----
    md_path = os.path.join(args.output, "translation-spec-check.md")
    lines = []
    lines.append("# 翻译与修嵌规范检查报告（EPUB 正文层）\n")
    lines.append("依据《翻译与修嵌规范.docx》中**落实到 EPUB 最终正文**的条款检查。"
                 "交稿层面的机制（`|基文[注文]` 注音、内联 `（*译注：）`、空行规则、docx 交稿格式、漫画修嵌）"
                 "在 EPUB 成品中已转换为 `<ruby>` / Note 脚注页 / 固定行模板，**不反向检查**。\n")
    lines.append("检查范围：`%s/**/OEBPS/Text/*.xhtml`，共 **%d** 本、命中 **%d** 条。\n" % (
        os.path.relpath(root, REPO_ROOT), len(books_checked), len(findings)))
    lines.append("| 类别 | 含义 | 命中 |")
    lines.append("| --- | --- | --- |")
    cat_desc = {
        "P1": "半角标点（中文语境应为全角）",
        "P2": "半角波浪号~（应为～）",
        "P3": "问叹顺序 ！？（问号应在感叹号左边）",
        "P4": "省略号写成连续句号",
        "P5": "省略号后带句号/点号",
        "P6": "弯引号（应使用直角引号）",
        "P7": "日文点号・（与·不一致）",
        "P8": "正文假名残留（需人工确认）",
        "P9": "单位（公斤/公里）",
        "P10": "注音 ruby 问题",
        "P11": "语气词/音译（规范示例）",
        "P12": "单个省略号…",
        "P13": "连续 ASCII 空格",
        "P14": "小数应使用阿拉伯数字（非汉字数字+小数点）",
    }
    for cat in sorted(cat_desc):
        lines.append("| %s | %s | %d |" % (cat, cat_desc[cat], category_counts.get(cat, 0)))
    lines.append("")

    # ・ vs · 分册一致性表
    lines.append("## 日文点号 ・ 与间隔号 · 分册分布\n")
    lines.append("`・`(U+30FB) 是日文点号，`·`(U+00B7) 是中文间隔号。规范提醒勿混淆。"
                 "全书绝大多数书用 `·`，少数书出现 `・`，存在跨书不一致：\n")
    nakaguro = {}
    middot = {}
    for book, fn, ln, cat, sev, msg, ex in findings:
        if cat == "P7":
            nakaguro[book] = nakaguro.get(book, 0) + 1
    for book in books_checked:
        text_dir = os.path.join(root, book, "OEBPS", "Text")
        cnt = 0
        for fn in os.listdir(text_dir):
            if not fn.endswith(".xhtml"):
                continue
            try:
                t = open(os.path.join(text_dir, fn), encoding="utf-8-sig").read()
            except Exception:
                continue
            cnt += strip_tags(html.unescape(t)).count("·")
        middot[book] = cnt
    if nakaguro:
        lines.append("| 书 | ・ 出现 | · 出现 |")
        lines.append("| --- | --- | --- |")
        for b in sorted(set(nakaguro) | set(middot)):
            mark = " ← 与 · 混用/不一致" if (nakaguro.get(b, 0) and middot.get(b, 0)) else (
                " ← 全部用 ・" if nakaguro.get(b, 0) else "")
            lines.append("| %s | %d | %d%s |" % (b, nakaguro.get(b, 0), middot.get(b, 0), mark))
        lines.append("")
    else:
        lines.append("未发现 ・。\n")

    # 按书汇总
    lines.append("## 按书命中汇总\n")
    lines.append("| 书 | 命中 | 各类别计数 |")
    lines.append("| --- | --- | --- |")
    book_totals = Counter()
    book_cats = {}
    for book, fn, ln, cat, sev, msg, ex in findings:
        book_totals[book] += 1
        book_cats.setdefault(book, Counter())[cat] += 1
    for b in sorted(book_totals, key=lambda x: -book_totals[x]):
        cstr = ", ".join("%s:%d" % (c, n) for c, n in sorted(book_cats[b].items()))
        lines.append("| %s | %d | %s |" % (b, book_totals[b], cstr))
    lines.append("")

    # 每类样例
    lines.append("## 各类别样例（Top %d）\n" % args.top)
    by_cat = OrderedDict()
    for item in findings:
        by_cat.setdefault(item[3], []).append(item)
    for cat in sorted(by_cat):
        items = by_cat[cat]
        sev = items[0][4]
        sev_label = {"error": "错误", "warning": "警告", "info": "提示"}.get(sev, sev)
        lines.append("### %s %s（%d 条，%s）\n" % (cat, cat_desc.get(cat, cat), len(items), sev_label))
        for book, fn, ln, c, s, msg, ex in items[:args.top]:
            lines.append("- `%s` `%s:%s`：%s`%s`" % (book, fn, ln, msg, ex))
        lines.append("")

    lines.append("---\n")
    lines.append("生成命令：`python tools/check_translation_spec.py`。只读检查，未修改任何缓存文件。\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("MD 已写入: %s" % md_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
