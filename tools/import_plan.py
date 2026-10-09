#!/usr/bin/env python3
"""新书导入计划文件的单一实现：结构校验、逐条改动装配（无 CLI）。

计划文件（plan.json）是**任务工作产物**：交稿与日文工作源不变时它决定成品形状，
由 `import_align_plan.py` 生成骨架、人工／agent 逐条填实，再由
`import_build_text.py`、`import_build_wrappers.py`、`import_images.py` 消费。
它不改写交稿，也不越权写入 EPUB——写盘由各入口按 `edit_safety` 约束执行。

结构：

```json
{
  "work_id": "S4_04",
  "book_dir": "[S4_04]某暗部的少女共栖 4X",
  "source_docx": "…/交稿.docx",
  "source_docx_sha256": "…",
  "jp_root": ".cache/epub-work/japanese-text",
  "jp_dir": "日本語ディレクトリ名",
  "images_source": "…/图片素材目录",
  "images": [{"dst": "S4_04-i-032.jpg", "src": "i-032.jpg", "role": "body"}],
  "chapters": [
    {"cn_title": "引子", "jp_file": "item/xhtml/S4_04-01.xhtml",
     "fname": "S4_04-01_Before_the_Prologue.xhtml",
     "h1_main": null, "h1_sub": null, "nav": null,
     "ops": [{"op": "split", "para": 295, "into": ["…", "…"]}]}
  ]
}
```

改动类型（`para` 一律是**交稿段落绝对序号**，与清单 TSV 的 `idx` 同源）：

| op | 作用 | 字段 |
| --- | --- | --- |
| `split` | 日文两段被译成一段：按语义边界还原为两段 | `into`（两个非空字符串） |
| `merge_prev` | 中文多拆一段：并入上一段 | — |
| `insert_br_after` | 该段之后补一个 `<br/>`（日文独有场景分隔行） | — |
| `drop` | 删除该段（插图前后排版空段、章末多余空段、制作指示） | — |
| `note_to_prev` | 独占成段的译注：改挂到上一段末尾 | — |

`images[].role`：`cover`／`illustration`／`body`；正文插图按 `body` 出现顺序落行。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

OP_TYPES = ("split", "merge_prev", "insert_br_after", "drop", "note_to_prev")
IMAGE_ROLES = ("cover", "illustration", "body")
CHAPTER_FIELDS = ("cn_title", "jp_file", "fname")
PLAN_FIELDS = ("work_id", "book_dir", "chapters")


class PlanError(ValueError):
    """计划文件缺失、结构非法或与交稿对不上。"""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 读写与校验
# ---------------------------------------------------------------------------

def load_plan(path: Path | str) -> dict:
    path = Path(path)
    if not path.is_file():
        raise PlanError(f"计划文件不存在：{path}")
    try:
        plan = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"计划文件不是合法 JSON：{exc}") from exc
    problems = validate_plan(plan)
    if problems:
        raise PlanError("计划文件不合法：" + "；".join(problems))
    return plan


def write_plan(path: Path | str, plan: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return path


def validate_plan(plan: dict) -> list[str]:
    problems: list[str] = []
    if not isinstance(plan, dict):
        return ["计划根节点必须是对象"]
    for field in PLAN_FIELDS:
        if not plan.get(field):
            problems.append(f"缺少字段 {field}")
    if plan.get("work_id") and not re.fullmatch(r"S\d+_\d+(?:_\d+)?", str(plan["work_id"])):
        problems.append(f"work_id 形状异常：{plan['work_id']}")
    chapters = plan.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        problems.append("chapters 必须是非空数组")
        return problems
    seen_names: set[str] = set()
    for index, chapter in enumerate(chapters):
        where = f"chapters[{index}]"
        if not isinstance(chapter, dict):
            problems.append(f"{where} 必须是对象")
            continue
        for field in CHAPTER_FIELDS:
            if not chapter.get(field):
                problems.append(f"{where} 缺少字段 {field}")
        name = chapter.get("fname")
        if name:
            if not name.endswith(".xhtml"):
                problems.append(f"{where}.fname 必须以 .xhtml 结尾：{name}")
            if name in seen_names:
                problems.append(f"{where}.fname 与前面的章节重复：{name}")
            seen_names.add(name)
        problems.extend(validate_ops(chapter.get("ops") or [], where))
    problems.extend(validate_images(plan.get("images") or []))
    return problems


def validate_ops(ops, where: str) -> list[str]:
    problems: list[str] = []
    if not isinstance(ops, list):
        return [f"{where}.ops 必须是数组"]
    used: set[int] = set()
    for order, op in enumerate(ops):
        at = f"{where}.ops[{order}]"
        if not isinstance(op, dict):
            problems.append(f"{at} 必须是对象")
            continue
        kind = op.get("op")
        if kind not in OP_TYPES:
            problems.append(f"{at}.op 非法：{kind!r}")
            continue
        para = op.get("para")
        if not isinstance(para, int) or para < 0:
            problems.append(f"{at}.para 必须是非负整数")
            continue
        if para in used:
            problems.append(f"{at}.para 与同章另一条改动重复：{para}")
        used.add(para)
        if kind == "split":
            into = op.get("into")
            if (not isinstance(into, list) or len(into) != 2
                    or not all(isinstance(part, str) and part.strip() for part in into)):
                problems.append(f"{at}.into 必须是两个非空字符串")
    return problems


def validate_images(images) -> list[str]:
    problems: list[str] = []
    if not isinstance(images, list):
        return ["images 必须是数组"]
    seen: set[str] = set()
    for index, entry in enumerate(images):
        at = f"images[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{at} 必须是对象")
            continue
        for field in ("dst", "src", "role"):
            if not entry.get(field):
                problems.append(f"{at} 缺少字段 {field}")
        if entry.get("role") and entry["role"] not in IMAGE_ROLES:
            problems.append(f"{at}.role 非法：{entry['role']!r}")
        if entry.get("dst") in seen:
            problems.append(f"{at}.dst 与前面的图片重复：{entry['dst']}")
        seen.add(entry.get("dst"))
    return problems


# ---------------------------------------------------------------------------
# 逐条改动装配
# ---------------------------------------------------------------------------

def ops_by_para(chapter: dict) -> dict[int, dict]:
    return {op["para"]: op for op in (chapter.get("ops") or [])}


def body_images(plan: dict) -> list[str]:
    return [entry["dst"] for entry in plan.get("images") or [] if entry.get("role") == "body"]


def illustrate_roles(plan: dict) -> list[str]:
    return [entry["dst"] for entry in plan.get("images") or []
            if entry.get("role") in ("cover", "illustration")]


def apply_ops(rows: list[dict], chapter: dict, where: str = "chapter") -> list[dict]:
    """把一章的交稿清单行按改动表装配成产物行。

    `rows` 是该章的清单行（`idx`/`kind`/`text`，见 `import_docx_outline.collect`）。
    产物行是 `{"kind": "p"|"br"|"h2"|"img", "text": str|None, "para": int|None}`，
    其中 `br` 不含文本、`img` 保留占位符原文以便与素材顺序对齐。
    """
    ops = ops_by_para(chapter)
    known = {row["idx"]: row for row in rows}
    unknown = sorted(set(ops) - set(known))
    if unknown:
        raise PlanError(f"{where}：改动指向不属于本章的段落 {unknown}")
    # 改动类型必须与该段的清单类型相容，避免静默忽略
    compatible = {
        "drop": {"p", "blank", "img", "note-only"},
        "note_to_prev": {"note-only"},
        "split": {"p"},
        "merge_prev": {"p"},
        "insert_br_after": {"p"},
    }
    for para, op in sorted(ops.items()):
        kind = known[para]["kind"]
        if kind not in compatible[op["op"]]:
            raise PlanError(
                f"{where}：段 {para} 的类型是 {kind}，不能使用 {op['op']}（允许："
                f"{'／'.join(sorted(compatible[op['op']]))}）")

    out: list[dict] = []

    def last_paragraph(op: dict) -> dict:
        for row in reversed(out):
            if row["kind"] == "p":
                return row
        raise PlanError(f"{where}：{op['op']} 之前没有可挂接的正文段（para={op['para']}）")

    for row in rows:
        para = row["idx"]
        op = ops.get(para)
        kind = row["kind"]
        if op and op["op"] == "drop":
            continue
        if op and op["op"] == "note_to_prev":
            match = re.search(r"【\*?译注[：:](.*?)】", row["text"], re.DOTALL)
            if not match:
                raise PlanError(f"{where}：段 {para} 标为 note_to_prev 但没有译注标记")
            last_paragraph(op)["text"] += match.group(0)
            continue
        if op and op["op"] == "split":
            for part in op["into"]:
                out.append({"kind": "p", "text": part, "para": para})
        elif kind == "img":
            out.append({"kind": "img", "text": row["text"].strip(), "para": para})
        elif kind == "h2":
            out.append({"kind": "h2", "text": row["text"].strip(), "para": para})
        elif kind == "blank":
            out.append({"kind": "br", "text": None, "para": para})
        elif kind == "note-only":
            raise PlanError(
                f"{where}：段 {para} 是独占成段的译注，须在计划里加 note_to_prev：{row['text'][:40]}")
        elif kind == "h1":
            raise PlanError(f"{where}：段 {para} 是章标题，不应出现在本章正文里")
        else:
            if op and op["op"] == "merge_prev":
                last_paragraph(op)["text"] += row["text"].strip()
            else:
                out.append({"kind": "p", "text": row["text"], "para": para})
        if op and op["op"] == "insert_br_after":
            out.append({"kind": "br", "text": None, "para": None})
    return out
