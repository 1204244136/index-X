#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""译文改动风险与规范启发式诊断工具（原子模块）。

职责：
  输入 (old_text, new_text, jp_text)，通过启发式规则与规范条款检测潜在语义风险、
  事实层错误（否定颠倒、数字变动、反问反转）、未简化新字体、受控术语回退以及排版门禁违规。

用法：
    # 作为 CLI：
    python tools/audit_risk.py --old "..." --new "..." --jp "..."

    # 作为 Python 模块：
    from audit_risk import audit_risk_flags, audit_risk_details
    flags = audit_risk_flags(old, new, jp)
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# 常见日文新字体 / 异体字（简体中文成书应转化为规范简化字）
JP_SHINJITAI = {
    '浜': '滨', '沢': '泽', '黒': '黑', '広': '广', '単': '单', '気': '气',
    '竜': '龙', '滝': '泷', '覚': '觉', '証': '证', '転': '转', '撃': '击',
    '弾': '弹', '権': '权', '辺': '边', '桜': '樱', '渋': '涩', '変': '变',
    '剤': '剂', '済': '济', '歳': '岁', '覇': '霸', '絵': '绘', '続': '续',
    '練': '练', '総': '总', '窓': '窗', '観': '观', '辞': '辞', '読': '读',
    '説': '说', '語': '语', '誰': '谁', '調': '调', '談': '谈', '許': '许',
    '認': '认', '訳': '译', '論': '论', '計': '计', '記': '记', '訪': '访',
    '設': '设', '試': '试', '話': '话', '誠': '诚'
}

# 常见受控术语规则 (正则, 规范词, 风险描述)。
# 只保留能在《译名裁定总表》找到落点的条目并注明来源；查不到落点的纠错类规则
# （Saintium、站所、瓢虫铁处女机制、灵异照片机制、方向反转、12 人 VIP）已于
# 2026-10-05 按维护者决定删除——它们与裁定混在同一张表里、来源只存在于历史提交。
CONTROLLED_TERMS = [
    # 裁定表 §九「袴少女」系列：本卷既有写法自洽，不另拟
    (r"和服裤裙", "袴之少女", "应统一为「袴之少女」专称（裁定表 §九）"),
    # 裁定表 §五：オペレーションネーム・ハンドカフス／ハンドカフス（按语境）
    (r"行动代号[·・]手铐|代号[·・]手铐", "手铐行动", "应统一使用已裁定术语「手铐行动」（裁定表 §五）"),
]


def load_ruling_terms(path: str) -> list[tuple[str, str, str]]:
    """从《译名裁定总表》的候选列生成受控术语提示（只取标注「成品旧译」的条目）。

    只对**确证在成品里出现过**的旧译生成规则——把全表候选列都变成提示会让噪声淹没
    真信号。候选列的第一个词条（`／` 或 `（` 之前）是写法本体。
    """
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return []
    out: list[tuple[str, str, str]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        ruling = cells[1].replace("**", "").strip()
        alt = cells[2]
        if "成品旧译" not in alt or not ruling:
            continue
        form = re.split(r"／|（|\(", alt)[0].strip()
        if form:
            out.append((re.escape(form), ruling, f"裁定表登记的成品旧译「{form}」应作「{ruling}」"))
    return out

NEG_WORDS_CN = re.compile(r"(不|没|未|别|非|无|莫)")
NEG_MARKERS_JP = re.compile(r"(ない|なかった|ず|ぬ|ません|まい|なく|わけではない|とは限らない|否定)")
JP_QUESTION = re.compile(r"(か|のか|だろうか|のかっ|じゃないか|かしら)[。？！\?]*$")


def strip_html(text: str) -> str:
    """去除 HTML 标签。"""
    return re.sub(r"<[^>]+>", "", text).strip()


def audit_risk_flags(old: str, new: str, jp: str = "") -> list[str]:
    """返回改动命中风险标记的短标签列表（如 ['negation', 'number']）。"""
    details = audit_risk_details(old, new, jp)
    return [d["flag"] for d in details]


def audit_risk_details(old: str, new: str, jp: str = "",
                       extra_terms: list[tuple[str, str, str]] | None = None) -> list[dict]:
    """返回改动命中的所有风险详情列表。

    `extra_terms` 追加受控术语规则（格式同 `CONTROLLED_TERMS`），供调用方传入
    `load_ruling_terms()` 从裁定表生成的条目。
    """
    old_p = strip_html(old)
    new_p = strip_html(new)
    jp_p = strip_html(jp)

    risks = []

    # 1. 否定词翻转
    has_neg_old = bool(NEG_WORDS_CN.search(old_p))
    has_neg_new = bool(NEG_WORDS_CN.search(new_p))
    has_neg_jp = bool(NEG_MARKERS_JP.search(jp_p)) if jp_p else None
    if has_neg_old != has_neg_new:
        risks.append({
            "flag": "negation",
            "desc": f"否定状态改变 (旧:{has_neg_old} -> 新:{has_neg_new}, 日文否定:{has_neg_jp})"
        })

    # 2. 数字变动
    nums_old = set(re.findall(r"\d+", old_p))
    nums_new = set(re.findall(r"\d+", new_p))
    if nums_old != nums_new:
        risks.append({
            "flag": "number",
            "desc": f"阿拉伯数字变化 (旧:{sorted(nums_old)} -> 新:{sorted(nums_new)})"
        })

    # 3. 疑问/反问语气变更
    q_old = "？" in old_p or "?" in old_p
    q_new = "？" in new_p or "?" in new_p
    if q_old != q_new:
        q_jp = bool(JP_QUESTION.search(jp_p)) if jp_p else None
        risks.append({
            "flag": "question",
            "desc": f"疑问标点变化 (旧问号:{q_old} -> 新问号:{q_new}, 日文句尾疑问:{q_jp})"
        })

    # 4. 未简化日文新字体汉字残留
    found_kanji = [jk for jk in JP_SHINJITAI if jk in new_p]
    if found_kanji:
        risks.append({
            "flag": "kanji",
            "desc": f"检测到未简化日文汉字: {found_kanji}"
        })

    # 5. 加粗内含标点（违反健康门禁 [bold-punct]）
    # 匹配 <b> 标签内部紧邻或包含中英文逗号、句号、分号等
    if re.search(r"<b>[^<]*[，。！？；：、…][^<]*</b>", new):
        risks.append({
            "flag": "bold_punct",
            "desc": "<b> 加粗标签内包含标点符号，违反 [bold-punct] 规范"
        })

    # 6. 对话引号嵌套层级错误（外层「」内部使用「」而不是『』）
    # 启发式：匹配「...「...」...」型同级嵌套
    if re.search(r"「[^」]*「[^」]+」[^」]*」", new_p):
        risks.append({
            "flag": "quote_nest",
            "desc": "对话「」内部同级嵌套了「」，应使用二级引号『』"
        })

    # 7. 受控术语与已知误改模式
    for pat, standard, note in list(CONTROLLED_TERMS) + list(extra_terms or []):
        if re.search(pat, new):
            risks.append({
                "flag": "controlled_term",
                "desc": f"命中受控词规则 [{pat}]，规范应为 [{standard}] ({note})"
            })

    # 8. 明显实义删减与增补（排除规范标签）
    d_len = len(new_p) - len(old_p)
    if d_len <= -5:
        risks.append({
            "flag": "del_large",
            "desc": f"明显删减: 减少 {abs(d_len)} 字（漏译高发区）"
        })
    elif d_len >= 8:
        risks.append({
            "flag": "add_large",
            "desc": f"明显增补: 增加 {d_len} 字（脑补高发区）"
        })

    return risks


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="对单处译文改动进行语义与规范风险诊断")
    parser.add_argument("--old", required=True, help="旧译文（支持带 HTML）")
    parser.add_argument("--new", required=True, help="新译文（支持带 HTML）")
    parser.add_argument("--jp", default="", help="对应日文原文行（可选）")
    parser.add_argument("--rulings", default="docs/translation-name-rulings.md",
                        help="《译名裁定总表》路径，用于追加「成品旧译」受控术语（默认仓库内路径）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args(argv)

    risks = audit_risk_details(args.old, args.new, args.jp,
                               extra_terms=load_ruling_terms(args.rulings))
    if args.json:
        print(json.dumps(risks, ensure_ascii=False, indent=2))
    else:
        if not risks:
            print("未检出明显语义或排版风险。")
        else:
            print(f"检出 {len(risks)} 项潜在风险:")
            for r in risks:
                print(f"  [{r['flag']}] {r['desc']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
