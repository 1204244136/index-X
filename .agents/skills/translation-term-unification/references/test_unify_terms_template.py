"""`unify_terms_template.py` 的回归测试（无第三方依赖，不碰 EPUB/）。

    python .dsh/skills/translation-term-unification/references/test_unify_terms_template.py

覆盖模板的五条不变式：未命中／定位失败／空映射 → 整批拒绝且不写盘；命中 + 已统一 → 预检通过
且幂等；`--apply` 只替换目标行并保留行数、CRLF 与 BOM。
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TPL = Path(__file__).with_name("unify_terms_template.py")
ROOT = Path(tempfile.mkdtemp(prefix="unify-terms-test-"))

CN = (
    '<?xml version="1.0" encoding="utf-8"?>\r\n'
    "<!DOCTYPE html>\r\n"
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body>\r\n'
    "<h1>第一章</h1>\r\n"
    "\r\n"
    "<p>『别呀，别这样。』</p>\r\n"
    "<p>『可别啦。』</p>\r\n"
    "<p>『这里没有锚点。』</p>\r\n"
    "</body></html>\r\n"
)
NAME = "S3_05-01_Chapter1.xhtml"
FILE = ROOT / "[S3_05]测试书" / "OEBPS" / "Text" / NAME


def load_template():
    spec = importlib.util.spec_from_file_location("unify_terms", TPL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run(module, mappings, apply=False):
    module.MAPPINGS = mappings
    argv = ["unify_terms", "--epub", str(ROOT)] + (["--apply"] if apply else [])
    original = sys.argv
    sys.argv = argv
    buf = StringIO()
    try:
        with redirect_stdout(buf):
            code = module.main()
    finally:
        sys.argv = original
    return code, buf.getvalue()


def setup():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    FILE.parent.mkdir(parents=True)
    FILE.write_bytes(CN.encode("utf-8"))


def check(label, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    return ok


def main() -> int:
    results: list[bool] = []
    module = load_template()

    # 1. 原串未命中 → 整批拒绝、不写盘
    setup()
    code, out = run(module, [
        ("S3_05", NAME, 6, "别呀", "可别啦"),
        ("S3_05", NAME, 8, "不存在的串", "x"),
    ])
    results.append(check("未命中时整批拒绝（exit 1）", code == 1, f"exit={code}"))
    results.append(check("拒绝时未写盘", FILE.read_bytes() == CN.encode("utf-8")))
    results.append(check("报告点名未命中行", "原串未命中" in out))

    # 2. 命中 + 已统一 → 预检通过，预览不写盘
    code, out = run(module, [
        ("S3_05", NAME, 6, "别呀", "可别啦"),
        ("S3_05", NAME, 7, "不会吧", "可别啦"),
    ])
    results.append(check("命中+已统一预检通过（exit 0）", code == 0, f"exit={code}"))
    results.append(check("预览模式不写盘", FILE.read_bytes() == CN.encode("utf-8")))
    results.append(check("识别幂等（已统一）", "已统一" in out))

    # 3. --apply：只改目标行，行数 / CRLF / BOM 保持
    code, out = run(module, [
        ("S3_05", NAME, 6, "别呀", "可别啦"),
        ("S3_05", NAME, 7, "不会吧", "可别啦"),
    ], apply=True)
    after = FILE.read_bytes().decode("utf-8")
    results.append(check("apply 后 exit 0", code == 0, f"exit={code}"))
    results.append(check("仅替换目标行", "『可别啦，别这样。』" in after and "别呀" not in after))
    results.append(check(
        "行数与行尾风格不变",
        after.count("\n") == CN.count("\n") and after.count("\r\n") == CN.count("\r\n"),
    ))

    # 4. 幂等重跑
    code, out = run(module, [("S3_05", NAME, 6, "别呀", "可别啦")], apply=True)
    results.append(check("重跑幂等（0 待改 / 1 已统一）", code == 0 and "待改 0 处" in out))
    results.append(check("重跑不重复写坏文件", FILE.read_bytes().decode("utf-8") == after))

    # 5. 定位失败 / 空映射 → 拒绝
    code, out = run(module, [("S9_99", NAME, 6, "别呀", "可别啦")])
    results.append(check("作品号定位失败即拒绝", code == 1 and "文件定位不唯一" in out))
    code, out = run(module, [])
    results.append(check("空映射拒绝", code == 2 and "MAPPINGS 为空" in out))

    print(f"\n{sum(results)}/{len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
