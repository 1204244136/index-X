"""XHTML → 纯文本的统一口径；注音剥除规则只在这里实现，调用方不得再各写一套。

三种口径，按「要不要读音」选：

- `text_of(bytes)`：剥标签、解实体、并空白，**保留** `<rt>` 读音。复核 diff 用它，
  否则注音改动不会出现在差异里。
- `text_of_without_ruby(bytes)`：先移除 `<rt>`/`<rp>` 再按上面同一口径提取。
  原文检索与术语比对用它，否则 `魔術サイド` 会被读成 `魔術 まじゅつ サイド`。
- `visible_text_of(str)`：只移除 `<rt>`（保留 `<rp>` 包裹的可见括号）与全部标签，
  用于行级长度/字形比较。

分工：本模块只做提取，不扫描、不报告、不写盘。
"""
from __future__ import annotations

import html
import re

# 注音元素：`<rt>` 是读音，`<rp>` 是给不支持 ruby 的阅读器用的括号，二者都要移除
RUBY_ELEMENT = re.compile(r"<(?:rt|rp)\b[^>]*>.*?</(?:rt|rp)>", re.I | re.S)
# 只移除 `<rt>`：可见文本比较保留 `<rp>` 的括号
RT_ELEMENT = re.compile(r"<rt\b[^>]*>.*?</rt\s*>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")


def strip_ruby_annotations(html_text: str) -> str:
    """移除 `<rt>`/`<rp>` 及其内容；其余标记原样保留，供调用方继续剥标签。"""
    return RUBY_ELEMENT.sub("", html_text)


def visible_text_of(html_text: str) -> str:
    """移除 `<rt>` 与全部标签后的可见文本（保留基文，`<rp>` 括号保留）。"""
    return TAG.sub("", RT_ELEMENT.sub("", html_text)).strip()


def text_of(data: bytes) -> str:
    """Strip markup and collapse whitespace, preserving ruby readings.

    Source-term lookup must remove rt/rp first.（见 `text_of_without_ruby`）
    Review snippets retain them so that changes to readings remain visible to
    the diff classifier.
    """
    return _flatten(data.decode("utf-8", errors="ignore"))


def text_of_without_ruby(data: bytes) -> str:
    """与 `text_of` 同口径，但先移除注音；原文检索与术语比对用。"""
    return _flatten(strip_ruby_annotations(data.decode("utf-8", errors="ignore")))


def _flatten(text: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = TAG.sub(" ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()
