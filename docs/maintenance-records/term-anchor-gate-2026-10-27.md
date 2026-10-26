# 术语锚点门禁（2026-10-27）

- 范围：新增 `tools/check_term_anchors.py` 与 `tools/tests/test_check_term_anchors.py`；把裁定表锚点检查接入 `publish_preflight.py`、`proofread-review` R7、`translation-term-unification` S6 与 CI 条件步骤；`audit_risk.py`／`proofread_review.py` 的受控术语标记改为加载裁定表「成品旧译」。
- 背景：`S5_01_02` 在 2026-10-05 的整卷复审重写中把 `魔術` 从 0 处「魔术」加到 98 处，四道既有门禁（text_norm／alignment／health／translation_spec）全绿；10-19 的统一只补了同一裁定行的 `魔術師`，裸 `魔術` 残留 33 处，读者 10-27 反馈后才修正。根因是裁定表锚点没有可执行的扫描器：`check_translation_table.py` 以译名表原始写法 `【魔術】` 当锚，正文 441 处裸写一处也匹配不到。

## 判定口径

- 规则只从 `docs/translation-name-rulings.md` 读：锚点取 `DEFAULT_ANCHORS`（`魔術`、`魔術師`），应作取「裁定」列，误形取「被否决或并存的候选」列；不复制第二份映射。
- 中日按作品号、表头、物理行配对；只在中日两侧都有且行数一致时判定。
- **命中条件 = 日文锚点出现 + 中文没有裁定写法 + 中文含裁定表登记的误形**。不采用「缺写法即报」：实测全库「日文含 `魔術`、中文无『魔法』」共 728 行，多为书名、省略与改写，会淹没真信号。
- 长锚点先匹配并掩码，`魔術師` 不会在 `魔術` 行重复计数；`手品`／`奇術`／`マジック` 不属本锚点。
- 语境例外：塔罗牌大阿尔卡那 I 的 `魔術師` 在日文行命中 `タロット`／`大アルカナ`／`カード` 时跳过（牌名译「魔术师」，裁定表牌名例外）。
- 「人读」条目、非配对作品、行数不等文件在报告中单列，不计通过。

## 接入点

- `publish_preflight.py`：带 `--jp-root` 的发布预检按选定书阻断，命中项并入阻断问题列表。
- `proofread-review` R7 门禁与 §二.5：整批 `rewrite` 写盘前必须 0 命中；R3.3 改为无条件先跑。
- `translation-term-unification` S6：术语统一写盘后的固定门禁。
- `audit_risk.py`／`proofread_review.py`：`audit_risk_flags` 支持 `extra_terms`，复核入口传入裁定表登记的「成品旧译」。
- CI：`.github/workflows/check-epub-health.yml` 增加条件步骤——有日文缓存才执行，否则明确跳过（CI checkout 只有中文侧）。

## 验证

- `python -m unittest discover -s tools/tests -p "test_*.py"`：**922 个测试通过，3 个跳过**（新增 11 个门禁测试与 1 个受控术语传递测试）。
- `python tools/check_term_anchors.py --strict`：784 个配对文件，**0 命中**。
- 对 2026-10-05 旧树（`6b34bc3f` 的 S5_01_02）运行同一命令：**19 行命中**，含读者反馈句 `S5_01_02-03_Chapter2.xhtml:220`。
- `python tools/publish_preflight.py --source EPUB --jp-root .cache/epub-work/japanese-text`：169 本，**问题 0 条**。
- `python tools/check_project_docs.py`：**问题 0 条**。

## 限制与维护

- 默认只覆盖 `魔術`／`魔術師` 两个已裁定锚点；新增锚点须同时确认「候选列可当误形」并补 `ANCHOR_CONTEXT_EXCEPTIONS`，再改 `DEFAULT_ANCHORS`（或用 `--anchor` 临时指定）。
- 只比对配对成功且行数一致的文件；无日文参考、未配对或行数不等的中文文件不视为通过。
- CI 无日文参考时不执行；工作站的 `publish_preflight.py` 与 review R7 是实际阻断点。
- 回退：`git revert <commit>`。
