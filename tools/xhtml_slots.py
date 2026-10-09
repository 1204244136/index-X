"""固定行模板 L1–L6 的槽位定义（唯一来源）。

规范正文（模板本身、L5 槽位规则、L6 包装页边界）在 `docs/epub-structure-spec.md`；
本模块只把**行号与槽位名**单一化，避免各校验入口各自散落 `6`、`lines[3]` 这类魔数。

判定逻辑**不在这里**：配对契约（`check_alignment.check_file`）、分页与合并契约
（`bw_preprocess.template_issues`）、模板重建（`xhtml_template.rebuild`）三者的宽严
要求不同（是否允许 L5 列表包装、L3 是否必须含 `main` 容器、L6 是否要求同行闭
`</p>`），属各自入口的策略，不做合并。
"""
from __future__ import annotations

# 1-based 物理行号；取值即 `docs/epub-structure-spec.md` 固定行模板里的「第 N 行」
LINE_XML = 1
LINE_DOCTYPE = 2
LINE_HEAD = 3
LINE_H1 = 4
LINE_H2 = 5
LINE_BODY_FIRST = 6
# 模板占用的行数：少于它的文件不适用模板检查
SLOT_COUNT = LINE_BODY_FIRST

SLOT_NAMES = {
    LINE_XML: "L1 XML 声明",
    LINE_DOCTYPE: "L2 DOCTYPE",
    LINE_HEAD: "L3 头部合并行",
    LINE_H1: "L4 h1 或空行",
    LINE_H2: "L5 h2／列表包装或空行",
    LINE_BODY_FIRST: "L6 正文首行",
}


def slot_name(line_number: int) -> str:
    """把 1-based 行号转成规范里的槽位名，用于报错信息。"""
    return SLOT_NAMES.get(line_number, f"L{line_number}")


# ---------------------------------------------------------------------------
# 译注页（Note）固定取值
#
# 规范正文见 `docs/epub-structure-spec.md`「译注页（Note）结构规约」。该 h1 在全库 73 个
# `S<作品号>-Note.xhtml` 上逐字一致，但原先只硬编码在 `docx2epub.py` 与
# `import_build_text.py` 两个生成器里、无任何成文；在此单一化，两处生成器
# 与检查器共用它。
# ---------------------------------------------------------------------------
NOTE_H1 = '<h1 class="center">译注</h1>'
