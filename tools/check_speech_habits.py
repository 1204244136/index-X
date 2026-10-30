"""说话习惯表门禁（只读）：`docs/character-speech-habits.csv` 与裁定表 §六 是否一致。

本表是角色说话习惯的**盘点层**，裁定表 §六 是**裁定层**；`X版` 与 §六「裁定」逐字镜像。
口径正文见 `docs/translation-spec.md`「说话习惯表」，本文件只实现可机器判定的部分：

1. 表头与列序固定（9 列）；不再允许 `-` 占位。
2. `(角色, 口癖)` 唯一；`类型` 取自 `TYPES` 词表（唯一来源是本常量）。
3. `裁定状态` 三值合法，且与 §六 对齐：`已裁定` 必须找得到、`未裁定` 不得找得到、
   `规则型` 的 `口癖` 必须是 `【不适用】`；规则型的版本列按实际处理记具体写法、`【已处理】`
   或 `【不处理】`，角色不在小说语料中时记 `【无文本】`。
4. **镜像**：`已裁定` 行的 `X版` 必须等于 §六「裁定」（去 `**` 与反引号）；§六 裁定是
   散文指令（含「译出」「不拟」）时，`X版` 必须记 `【不处理】`。
5. **反向覆盖**：§六 每个锚点都要在本表有一行；跨角色规则三条登记为例外。
6. 记号只许出现在规定列：`【未查到】` 可出现在 `小说首次出现`／`网翻`／`台版（转简中）`／`X版`，
   `【不适用】` 只许在 `口癖`，`【不处理】` 与 `【已处理】` 只许在三个版本列，`【无此卷】` 与
   `【无文本】` 只许在两个外部版本列；`类型` 不用记号，必须落在词表内。

`【未查到】` 表示该版本有这一卷、但角色没有出场；该版本没有这一卷记 `【无此卷】`，
角色只出现在小说语料之外（漫画等）记 `【无文本】`。二者都不等于「没有查」。

对齐时允许三种写法差异：合体角色（`土御门元春／黑夜海鸟／芙蕾梅亚·塞维伦`）、
锚点变体（`どす・まへん・はる` 对应 §六 的 `どす`）、以及 §六 标 `人读` 的散文裁定。

退出码：0 通过；1 有问题；2 输入缺失。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO_ROOT / "docs" / "character-speech-habits.csv"
DEFAULT_RULINGS = REPO_ROOT / "docs" / "translation-name-rulings.md"

COLUMNS = ("角色", "口癖", "类型", "小说首次出现", "网翻", "台版（转简中）", "X版", "备注", "裁定状态")
STATUSES = {"已裁定", "未裁定", "规则型"}
MARKERS = {"【未查到】", "【不适用】", "【不处理】", "【已处理】", "【无此卷】", "【无文本】"}
ALLOWED = {
    "【未查到】": {"小说首次出现", "网翻", "台版（转简中）", "X版"},
    "【不适用】": {"口癖"},
    "【不处理】": {"网翻", "台版（转简中）", "X版"},
    "【已处理】": {"网翻", "台版（转简中）", "X版"},
    "【无此卷】": {"网翻", "台版（转简中）"},
    "【无文本】": {"网翻", "台版（转简中）"},
}
# 类型词表：唯一来源是本常量，规范与工具合同只留指针。
TYPES = {
    "第一人称",
    "称谓",
    "句首语气词",
    "句末语气词",
    "接续词",
    "谓语形式",
    "句式",
    "方言腔调",
    "名词",
    "名词前缀",
    "名词后缀",
    "短句",
}
# §六 里属于跨角色规则、盘点表不设对应行的锚点（理由见规范正文）
EXEMPT_ANCHORS = {
    "上条ちゃん": "月咏小萌等沿用的敬称，属跨角色规则",
    "エセ関西弁": "蓝发耳环的方言标记，本行无字面口癖",
    "たん": "通用称呼后缀，非角色条目",
    "、": "手盐惠未的断顿句式，本行按句式类登记、无字面口癖",
}
RULING_SECTION = "## 六、角色口癖与自称"
PROSE_HINTS = ("译出", "不拟")
ROLE_SPLIT = re.compile(r"[／/]")
ANCHOR_SPLIT = re.compile(r"[・/]")
PAREN = re.compile(r"（[^）]*）|\([^)]*\)")


def role_set(cell: str) -> set[str]:
    """合体角色拆开：去掉括注，再按全角／半角斜线拆分。"""
    return {part.strip() for part in ROLE_SPLIT.split(PAREN.sub("", cell or "")) if part.strip()}


def anchor_match(csv_anchor: str, ruling_anchor: str) -> bool:
    """精确相等，或本表把多个形态用 `・` 连写而裁定表只登记其中一个。"""
    if csv_anchor == ruling_anchor:
        return True
    return ruling_anchor in {part.strip() for part in ANCHOR_SPLIT.split(csv_anchor) if part.strip()}


def norm_decision(cell: str) -> str:
    return (cell or "").replace("**", "").replace("`", "").strip()


def is_prose(decision: str) -> bool:
    return any(hint in decision for hint in PROSE_HINTS)


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    return header, rows


def read_rulings(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(RULING_SECTION))
    except StopIteration:
        raise ValueError(f"{path}: 找不到小节「{RULING_SECTION}」") from None
    rows: list[dict[str, str]] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] == "角色" or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(
            {
                "role": cells[0],
                "anchor": cells[1].strip("`").strip(),
                "decision": cells[2],
                "judge": cells[5] if len(cells) > 5 else "",
            }
        )
    return rows


def check(csv_path: Path, rulings_path: Path) -> tuple[list[str], int, int]:
    header, rows = read_table(csv_path)
    rulings = read_rulings(rulings_path)
    problems: list[str] = []

    if tuple(header) != COLUMNS:
        problems.append(
            f"表头不符：期望 {'、'.join(COLUMNS)}；实际 {'、'.join(header) or '（空）'}"
        )
        return problems, len(rows), len(rulings)

    # ② 键唯一与类型词表
    seen: dict[tuple[str, str], int] = {}
    for number, row in enumerate(rows, start=2):
        key = (row["角色"], row["口癖"])
        if key in seen:
            problems.append(f"第 {number} 行：`(角色, 口癖)` 重复（首见第 {seen[key]} 行）")
        else:
            seen[key] = number
        if not row["角色"]:
            problems.append(f"第 {number} 行：`角色` 为空")
        if row.get("类型", "") not in TYPES:
            problems.append(
                f"第 {number} 行 `类型`：`{row.get('类型', '')}` 不在词表（{'、'.join(sorted(TYPES))}）"
            )

    # ⑥ 记号位置与 `-` 回归
    for number, row in enumerate(rows, start=2):
        for column in COLUMNS:
            value = row.get(column, "")
            if value == "-":
                problems.append(f"第 {number} 行 `{column}`：不再允许 `-`，改用 `【未查到】`／`【不适用】`／`【不处理】`")
            if value in MARKERS and column not in ALLOWED[value]:
                problems.append(
                    f"第 {number} 行 `{column}`：记号 `{value}` 只允许出现在 {'、'.join(sorted(ALLOWED[value]))}"
                )

    # ③ 状态合法性与对齐、④ 镜像
    for number, row in enumerate(rows, start=2):
        status = row.get("裁定状态", "")
        habit = row.get("口癖", "")
        hit = next(
            (
                r
                for r in rulings
                if row["角色"] in role_set(r["role"]) and anchor_match(habit, r["anchor"])
            ),
            None,
        )
        if status not in STATUSES:
            problems.append(f"第 {number} 行 `裁定状态`：`{status}` 不在 {'、'.join(sorted(STATUSES))}")
            continue
        if status == "规则型":
            if habit != "【不适用】":
                problems.append(f"第 {number} 行：`规则型` 的 `口癖` 必须是 `【不适用】`（实际 `{habit}`）")
            continue
        if status == "已裁定":
            if hit is None:
                problems.append(f"第 {number} 行：标 `已裁定`，但 §六 找不到 `{row['角色']}` 的 `{habit}`")
                continue
            decision = norm_decision(hit["decision"])
            want = "【不处理】" if is_prose(decision) else decision
            if row["X版"] != want:
                problems.append(
                    f"第 {number} 行：`X版` 应镜像 §六 裁定 `{want}`，实际 `{row['X版']}`"
                )
        else:  # 未裁定
            if hit is not None:
                problems.append(
                    f"第 {number} 行：标 `未裁定`，但 §六 已登记 `{hit['role']}` 的 `{hit['anchor']}`"
                )

    # ⑤ 反向覆盖
    for ruling in rulings:
        if ruling["anchor"] in EXEMPT_ANCHORS:
            continue
        if any(
            row["角色"] in role_set(ruling["role"]) and anchor_match(row["口癖"], ruling["anchor"])
            for row in rows
        ):
            continue
        problems.append(
            f"§六 `{ruling['role']}` 的 `{ruling['anchor']}` 在本表没有对应行"
            f"（跨角色规则请登记为例外：{'、'.join(sorted(EXEMPT_ANCHORS))}）"
        )

    return problems, len(rows), len(rulings)


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="说话习惯表与裁定表 §六 的一致性门禁（只读）")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="说话习惯表 CSV 路径")
    parser.add_argument("--rulings", type=Path, default=DEFAULT_RULINGS, help="译名裁定总表路径")
    parser.add_argument("--limit", type=int, default=0, help="只显示前 N 条问题（0 = 全部）")
    args = parser.parse_args(argv)

    if not args.csv.is_file():
        print(f"缺少说话习惯表：{args.csv}", file=sys.stderr)
        return 2
    if not args.rulings.is_file():
        print(f"缺少译名裁定总表：{args.rulings}", file=sys.stderr)
        return 2

    try:
        problems, rows, rulings = check(args.csv, args.rulings)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    print(f"说话习惯表核对：{rows} 行／§六 {rulings} 条；问题 {len(problems)} 条")
    for item in problems[: args.limit] if args.limit else problems:
        print(f"  {item}")
    if args.limit and len(problems) > args.limit:
        print(f"  …另有 {len(problems) - args.limit} 条；用 --limit 0 显示全部")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
