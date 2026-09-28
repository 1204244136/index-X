# 北欧灵装名注音语种统一记录（2026-09-26）

- 范围：`EPUB/` 中文归档（写入落点）与 `.cache/epub-work/` 中日配对文本（分析源）
- 涉及书籍：S1_19、S1_25、S2_03、S2_04、S2_05、S2_06、S2_08、S2_09、S2_10、S2_18、S5_01_01（11 本）
- 修改文件：27 个中文 XHTML
- 行内替换：198 处

## 判定口径

日文源侧这批北欧神话灵装／种族名是同一结构：**汉字意译基文 ＋ 片假名特殊读音**（当て字）。其中 `主神の槍（グングニル）`、`投擲の槌（ミョルニル）`、`地の底這う悪竜（ニーズヘツグ）` 成品原已用汉译注音；本轮把其余四个也统一为汉译注音，**基文的意译一律不动**（与 `docs/x-translation-differences.md`「二、中文注音」同一口径）。

| 日文锚点（源侧形态） | 中文规范 | 修订前（拉丁注音） | 源侧处数 |
| --- | --- | --- | ---: |
| `破滅の枝（レーヴァテイン）` | `<ruby>破灭之枝<rt>雷瓦汀</rt></ruby>` | `破灭之枝（Laevatain）` | 102 |
| `戦乱の剣（ダインスレーヴ）` | `<ruby>战乱之剑<rt>丹因斯莱夫</rt></ruby>` | `战乱之剑（Dáinsleif）` | 31 |
| `万象の金（ドラウプニル）` | `<ruby>万象之金<rt>德罗普尼尔</rt></ruby>` | `万象之金（Draupnir）` | 1 |
| `黒小人（ドヴェルグ／ドヴエルグ）` | `<ruby>黑侏儒<rt>矮人</rt></ruby>` | `黑侏儒（Dvergr）` | 62 |

依据：四者在日文源里与已用汉译注音的三例完全同构（汉字意译基文＋片假名当て字读音），故适用同一注音口径；`黒小人` 的基文在中文侧已作「黑侏儒」，本轮只换注音、不动基文。

### 顺带处理的两处独立问题（同属该锚点）

1. **同一锚点两种写法**：`S1_25-Stiyl_Magnus.xhtml` 内 `破灭之枝（Laevatain）`×101 与 `雷瓦汀（Lævateinn）`×1 并存，后者把汉译放进了基文槽位；统一为 `破灭之枝（雷瓦汀）`，该文件合计 102 处一致。
2. **非标准拼写**：拉丁注音原写作 `Laevatain`（103 处，标准拼写为 `Lævateinn`），随本轮注音改汉译一并清零，不再需要单独裁定拼写。

## 修订明细

| 作品 | 文件 | 处数 |
| --- | --- | ---: |
| S1_19 | `S1_19-06_Chapter4.xhtml` | 1 |
| S1_25 | `S1_25-Stiyl_Magnus.xhtml` | 138 |
| S2_03 | `S2_03-07_Epilogue.xhtml` | 2 |
| S2_04 | `S2_04-12_Main.11.xhtml` | 2 |
| S2_04 | `S2_04-15_Sub.14.xhtml` | 2 |
| S2_04 | `S2_04-17_Sub.16.xhtml` | 1 |
| S2_04 | `S2_04-19_Sub.18.xhtml` | 1 |
| S2_04 | `S2_04-25_Sub.24.xhtml` | 1 |
| S2_04 | `S2_04-33_Period.32.xhtml` | 1 |
| S2_04 | `S2_04-34_Sub.33.xhtml` | 3 |
| S2_04 | `S2_04-37_Chaptern.xhtml` | 14 |
| S2_04 | `S2_04-38_Severe_damage.xhtml` | 5 |
| S2_04 | `S2_04-39_Afterwords.xhtml` | 3 |
| S2_05 | `S2_05-02_Chapter1.xhtml` | 1 |
| S2_06 | `S2_06-05_Chapter6.xhtml` | 1 |
| S2_08 | `S2_08-01_Prologue.xhtml` | 1 |
| S2_08 | `S2_08-02_Chapter1.xhtml` | 1 |
| S2_08 | `S2_08-04_Chapter2.xhtml` | 1 |
| S2_08 | `S2_08-05_Between_the_Lines2.xhtml` | 1 |
| S2_08 | `S2_08-08_Chapter4.xhtml` | 1 |
| S2_08 | `S2_08-09_Epilogue.xhtml` | 2 |
| S2_09 | `S2_09-11_Chapter8.xhtml` | 1 |
| S2_09 | `S2_09-Illustrations.xhtml` | 1 |
| S2_10 | `S2_10-06_Chapter13.xhtml` | 8 |
| S2_10 | `S2_10-15_Afterwords.xhtml` | 2 |
| S2_18 | `S2_18-02_Chapter1.xhtml` | 1 |
| S5_01_01 | `S5_01_01-05_Chapter4.xhtml` | 2 |

## 保留项

- `S2_04-Note.xhtml` note9 的 `战乱之剑（古诺尔斯语：Dáinsleif）` 保留拉丁：该处标注的是古诺尔斯语原文，不是成品注音。
- `万象之金` 在 `S2_21`／`S2_23`／`S3_01`／`S3_07`／`S3_09` 的 `*-Information.xhtml` 中是译者署名，与灵装名无关，未改动。
- `黑侏儒` 在 `S1_25-Introduction.xhtml` 为无 ruby 的裸写（OPF 简介同文），本次只换注音内容，未改动。
- `S1_25-Stiyl_Magnus.xhtml` 中两处裸写 `Laevatain`（对应日文源同行的裸写 `レーヴァテイン`）按同一口径改写为 `雷瓦汀`，不新增 ruby。

## 统计与验证

- 修订前 / 修订后：`Laevatain` 103 → 0、`Dvergr` 62 → 0、`Dáinsleif` 32 → 1（Note 保留）、`Draupnir` 1 → 0；新写法计数 `破灭之枝（雷瓦汀）` 102、`黑侏儒（矮人）` 61、`战乱之剑（丹因斯莱夫）` 31、`万象之金（德罗普尼尔）` 1
- 全部为行内替换，不增删物理行：`git diff --stat` 为 182 insertions(+) / 182 deletions(-)，逐文件增删相等（27/27）
- 写入保持 BOM 与换行风格：仅 `S2_09-11_Chapter8.xhtml` 为既有 CRLF，未改动
- `python tools/check_alignment.py --strict`：1105 个正文文件，0 个问题
- `python tools/check_epub_health.py --strict`：78 本书、1197 个 XHTML，问题 0 条（ruby 项 0）
- `python tools/check_translation_spec.py`：P10 = 0（其余命中类别与本轮改动文件无交集）
- `python tools/publish_auto.py`：11 本已上传 OneDrive 并回流缓存
- 回退：`git revert` 本次提交（`fix(EPUB): 北欧灵装名注音统一为汉译`）
