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
  P9  单位（公斤/公里，规范建议 千克/千米；赛事项目名如「十公里长跑」豁免）
  P10 注音（ruby <rt> 内日文假名应译为汉语；空 rt / 缺 rt 提示）
  P11 语气词/音译（切！、啊啦、呀吼、吥吥 等规范示例词）
  P12 单个省略号 …（非 …… 连用）
  P13 连续 ASCII 空格（交稿残留或断断续续，需人工确认）
  P14 小数应使用阿拉伯数字（0.7），不得写成汉字数字+小数点（〇.七、三·五）
  P15 淘汰异形词残留（规范推荐《第一批异形词整理表》及《现汉》推荐词形，如「想象」不作「想像」）
  P16 正文繁体字残留（汉化组的繁简混杂 X 版不保留，一律简体；日文引用与包装页豁免）

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
from xhtml_text import strip_ruby_annotations

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(REPO_ROOT, ".cache", "epub-work", "chinese-text")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, ".cache", "epub-work")

TAG_RE = re.compile(r"<[^>]*>")
# 整段移除内嵌 <style>/<script> 块（含内容）：CSS/JS 里的半角逗号、分号
# 不属于正文，若不整段移除会被误判为半角标点。属性 style="..." 已由 TAG_RE 剥掉。
STYLE_FULL_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.S | re.I)
SCRIPT_FULL_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)

def strip_to_text(line):
    """把一行原始 XHTML 转成纯正文文本：先整段移除 <style>/<script> 与 ruby 注音块，
    再剥标签、反转义。外部 CSS（.css 文件）不在 XHTML 文本层，天然不进入检查。

    注音剥除（`<rt>` 与 `<rp>`，含内容）的唯一实现在 `xhtml_text.strip_ruby_annotations`：
    此前只剥 `<rt>`，会把 `<rp>（</rp>` 这类全角括号留在正文文本里（如 `驱动铠（）`）；
    当前规则集对该残留没有命中，但剥离口径应与其它入口一致，不留第二份实现。
    """
    t = STYLE_FULL_RE.sub("", line)
    t = SCRIPT_FULL_RE.sub("", t)
    t = strip_ruby_annotations(t)
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


# P9 例外：赛事项目名里的「公里」（如「十公里长跑」「十公里赛跑」）按中文体育
# 定名惯例保留；P9 只约束一般距离、时速等单位用法（如「直径达十公里左右」）。
# 依据 docs/translation-spec.md §一.6「例外（项目名分轨）」与
# docs/translation-name-rulings.md 的 `一〇キロ走` 裁定。
# 词表是封闭集合：新增赛事类型词须同步上述两份文档。
P9_EVENT_SUFFIXES = ("长跑", "赛跑", "路跑", "马拉松", "竞走", "接力", "越野", "健走", "徒步")

# P11 示例词：翻译规范一.7 的**机械覆盖**部分（正则, re 标志, 报错说明）。
# 「噗噗」「哔哔」与中文合法拟声（电子音、笑声）同形，**不设机械检查**，转人工判断——
# 规范里保留该禁令，但这里不列规则，否则会命中大量正常文本。
P11_EXAMPLES = (
    (r"(?<![\u3400-\u9fff])切！", 0,
     "「切！」：规范示例建议「チッ！」译为「啧！」而非「切！」（排除“一切！”），"),
    (r"啊啦", 0, "「啊啦」：规范提示「あら」不译为「啊啦」，"),
    (r"呀嘞呀嘞", 0, "「呀嘞呀嘞」：规范提示「やれやれ」不译为「呀嘞呀嘞」，"),
    (r"[呀雅压][吼呵呼嗬嚯轰]", 0,
     "「呀吼/呀呵/呀呼」：规范要求やっほー类招呼语译为「嗨」「你好」等中文招呼语，不音译，"),
    (r"\bYAHOO\b|\bYahoo\b", 0,
     "「YAHOO/Yahoo」：规范要求やっほー类招呼语不得写成拉丁化音译（若确为网站名可忽略），"),
    (r"吥", 0, "「吥吥」：规范要求ぶっぶー类否定拟声译为「错了」「错啦」等，不音译，"),
    (r"\bbubu\b", re.I, "「bubu」：规范要求ぶっぶー类否定拟声不得写成拉丁化音译，"),
)

# P16：正文繁体字残留。字表由 OpenCC TSCharacters（繁->简，Apache-2.0）生成，
# 只保留中文正文中确属繁体形的字；简繁同形或中文规范本就用该字形的写法
# （著/祇/潟/捍/瞭/吋/乾）与已裁定保留的专名用字（姪/燐/鮟/鱇）不入表。
# 重新生成方法：取 TSCharacters 的 key，限定 U+4E00–U+9FFF，减去上述例外。
P16_TRADITIONAL = (
    "丟並亂亙亞佇佈佔併來侖侶侷俁係俔俠俥俬倀倆倈倉個們倖倫倲偉偑側偵偽傌傑傖傘備傢傭傯傳傴債傷傾僂僅僉僑僕僞僤僥僨僱價儀儁儂"
    "億儈儉儎儐儔儕儘償優儲儷儸儺儻儼兇兌兒兗內兩冊冑冪凈凍凜凱別刪剄則剋剎剗剛剝剮剴創剷劃劄劇劉劊劌劍劏劑劚勁動務勛勝勞勢勣"
    "勩勱勳勵勸勻匭匯匱區協卹卻卽厙厠厤厭厲厴參叄叢吒吳吶呂咼員唄唸問啓啞啟啢喎喚喪喫喬單喲嗆嗇嗊嗎嗚嗩嗰嗶嘆嘍嘓嘔嘖嘗嘜嘩嘮"
    "嘯嘰嘵嘸嘽噁噓噚噝噠噥噦噯噲噴噸噹嚀嚇嚌嚐嚕嚙嚥嚦嚧嚨嚮嚲嚳嚴嚶囀囁囂囅囈囉囌囑囪圇國圍園圓圖團垻埡埨埰執堅堊堖堝堯報場"
    "塊塋塏塒塗塚塢塤塵塸塹塿墊墜墠墮墰墳墶墻墾壇壋壎壓壗壘壙壚壜壞壟壠壢壩壪壯壺壼壽夠夢夥夾奐奧奩奪奬奮奼妝姍姦娙娛婁婦婭媧"
    "媯媰媼媽嫋嫗嫵嫺嫻嫿嬀嬃嬈嬋嬌嬙嬡嬤嬪嬰嬸孃孋孌孫學孻孿寀寢實寧審寫寬寵寶將專尋對導尷屆屍屓屜屢層屨屬岡峯峴島峽崍崑崗崙"
    "崢崬嵐嵗嵽嵾嶁嶄嶇嶔嶗嶠嶢嶧嶨嶮嶸嶺嶼嶽巋巒巔巖巘巰巹帥師帳帶幀幃幓幗幘幟幣幫幬幷幹幾庫廁廂廄廈廎廕廚廝廞廟廠廡廢廣廩廬"
    "廳弒弔弳張強彄彆彈彌彎彔彙彠彥彫彲彿後徑從徠復徵徹恆恥悅悞悵悶悽惡惱惲惻愛愜愨愴愷愾慄態慍慘慚慟慣慤慪慫慮慳慶慺慼慾憂憊"
    "憐憑憒憖憚憤憫憮憲憶懇應懌懍懞懟懣懤懨懲懶懷懸懺懼懾戀戇戔戧戩戰戱戲戶扞拋拚挩挱挾捨捫捱捲掃掄掆掗掙掛採揀揚換揮揯損搖搗"
    "搧搵搶摑摜摟摯摳摶摺摻撈撏撐撓撝撟撣撥撫撲撳撻撾撿擁擄擇擊擋擓擔據擠擡擣擬擯擰擱擲擴擷擺擻擼擽擾攄攆攏攔攖攙攛攜攝攢攣攤"
    "攪攬敎敓敗敘敵數斂斃斆斕斬斷於旂旣昇時晉晛晝暈暉暐暘暢暫曄曆曇曉曏曖曠曥曨曬書會朥朧朮東枴柵柺査桱桿梔梘梜條梟梲棄棊棖棗"
    "棟棡棧棲棶椏椲楊楓楨業極榘榦榪榮榲榿構槍槓槤槧槨槮槳槶槼樁樂樅樑樓標樞樢樣樧樫樳樸樹樺樿橈橋機橢橫橯檁檉檔檜檟檢檣檮檯檳"
    "檸檻櫃櫍櫓櫚櫛櫝櫞櫟櫥櫧櫨櫪櫫櫬櫱櫳櫸櫻欄欅權欏欒欓欖欞欽歎歐歟歡歲歷歸歿殘殞殤殨殫殭殮殯殰殲殺殻殼毀毆毿氂氈氌氣氫氬氳"
    "氾汎汙決沒沖況泝洩洶浹浿涇涗涼淒淚淥淨淩淪淵淶淺渙減渢渦測渾湊湋湞湧湯溈準溝溫溮溳溼滄滅滌滎滙滬滯滲滷滸滻滾滿漁漊漍漚漢"
    "漣漬漲漵漸漿潁潑潔潕潙潚潛潤潯潰潷潿澀澆澇澐澗澠澤澦澩澫澮澱澾濁濃濄濆濕濘濚濛濜濟濤濧濫濰濱濺濼濾瀂瀅瀆瀇瀉瀋瀏瀕瀘瀝瀟"
    "瀠瀦瀧瀨瀰瀲瀾灃灄灑灒灕灘灙灝灡灣灤灧灩災為烏烴無煉煒煙煢煥煩煬煱熅熒熗熰熱熲熾燀燁燈燉燒燖燙燜營燦燬燭燴燶燻燼燾爍爐爛"
    "爭爲爺爾牀牆牘牴牽犖犛犢犧狀狹狽猙猶猻獁獃獄獅獎獨獪獫獮獰獱獲獵獷獸獺獻獼玀現琱琺琿瑋瑒瑣瑤瑩瑪瑲璉璊璕璗璡璣璦璫璯環璵"
    "璸璽璿瓅瓊瓏瓔瓚瓛甌甕產産畝畢畫異畵當疇疊痙痠痾瘂瘋瘍瘓瘞瘡瘧瘮瘲瘺瘻療癆癇癉癒癘癟癡癢癤癥癧癩癬癭癮癰癱癲發皁皚皰皸皺"
    "盃盜盞盡監盤盧盪眞眥眾睍睏睜睞瞘瞜瞞瞶瞼矇矓矚矯硃硜硤硨硯碕碩碭碸確碼碽磑磚磠磣磧磯磽磾礄礎礐礙礦礪礫礬礱祕祿禍禎禕禡禦"
    "禪禮禰禱禿秈稅稈稏稜稟種稱穀穇穌積穎穠穡穢穩穫穭窩窪窮窯窵窶窺竄竅竇竈竊竪競筆筍筧筴箇箋箏箚節範築篋篔篠篢篤篩篳篸簀簍簑"
    "簞簡簣簫簹簽簾籃籅籌籔籙籛籜籟籠籤籩籪籬籮籲粵糉糝糞糧糰糲糴糶糹糾紀紂紃約紅紆紇紈紉紋納紐紓純紕紖紗紘紙級紛紜紝紞紡紬紮"
    "細紱紲紳紵紹紺紼紿絀終絃組絅絆絎結絕絛絝絞絡絢給絨絪絰統絲絳絶絹絺綁綃綄綆綈綉綌綎綏綐綑經綖綜綝綞綠綡綢綣綧綪綫綬維綯綰"
    "綱網綳綴綵綸綹綺綻綽綿緄緇緊緋緑緒緓緔緗緘緙線緝緞締緡緣緦編緩緬緯緱緲練緶緹緻緼縈縉縊縋縐縑縕縗縛縝縞縟縣縧縫縭縮縯縱縲"
    "縳縴縵縶縷縹總績繃繅繆繒織繕繚繞繡繢繩繪繫繭繮繯繰繳繶繸繹繻繼繽繾繿纁纆纇纈纊續纍纏纓纔纕纖纘纜缽罃罈罌罎罰罵罷羅羆羈羋"
    "羣羥羨義羶習翫翬翹翽耬耮聖聞聯聰聲聳聵聶職聹聽聾肅脅脈脛脣脩脫脹腎腖腡腦腫腳腸膃膕膚膞膠膢膩膽膾膿臉臍臏臘臚臟臠臢臥臨臺"
    "與興舉舊舖舘艙艤艦艫艱艷芻苧茲荊莊莖莢莧菴菸萇萊萬萴萵葒葤葦葯葷蒍蒐蒓蒔蒕蒞蓀蓆蓋蓮蓯蓴蓽蔄蔔蔘蔞蔣蔥蔦蔭蔯蔿蕁蕆蕎蕒蕓"
    "蕕蕘蕢蕩蕪蕭蕷薀薈薊薌薑薔薘薟薦薩薴薵薹薺藍藎藝藥藪藭藴藶藹藺蘀蘄蘆蘇蘊蘋蘚蘞蘟蘢蘭蘺蘿虆虉處虛虜號虧虯蛺蛻蜆蝀蝕蝟蝦蝨"
    "蝸螄螞螢螮螻螿蟄蟈蟎蟣蟬蟯蟲蟳蟶蟻蠁蠅蠆蠍蠐蠑蠔蠟蠣蠨蠱蠶蠻衆衊術衕衚衛衝袞袷裊裏補裝裡製複褌褘褲褳褸褻襀襇襉襏襖襝襠襤"
    "襪襬襯襲襴覈見覎規覓視覘覡覥覦親覬覯覲覷覺覽覿觀觴觶觸訁訂訃計訊訌討訏訐訒訓訕訖託記訛訝訟訢訣訥訩訪設許訴訶診註証詀詁詆"
    "詎詐詒詔評詖詗詘詛詝詞詠詡詢詣試詩詪詫詬詭詮詰話該詳詵詷詼詿誄誅誆誇誌認誑誒誕誘誚語誠誡誣誤誥誦誨說説誰課誶誹誼誾調諂諄"
    "談諉請諍諏諑諒諓論諗諛諜諝諞諟諡諢諤諦諧諫諭諮諱諲諳諴諶諷諸諺諼諾謀謁謂謄謅謊謎謏謐謔謖謗謙謚講謝謠謡謨謫謬謭謳謹謾譁證"
    "譎譏譓譖識譙譚譜譞譟譫譭譯議譴護譸譽譾讀讅變讋讌讎讒讓讕讖讚讜讞谿豈豎豐豔豬豶貍貓貙貝貞貟負財貢貧貨販貪貫責貯貰貲貳貴貶"
    "買貸貺費貼貽貿賀賁賂賃賄賅資賈賊賑賒賓賕賙賚賜賞賠賡賢賣賤賦賧質賫賬賭賰賴賵賺賻購賽賾贄贅贇贈贊贋贍贏贐贓贔贖贗贛贜赬趕"
    "趙趨趲跡踐踰踴蹌蹕蹟蹠蹣蹤蹺躂躉躊躋躍躎躑躒躓躕躚躡躥躦躪軀車軋軌軍軏軑軒軔軛軝軟軤軫軲軸軹軺軻軼軾較輄輅輇輈載輊輋輒輓"
    "輔輕輗輛輜輝輞輟輥輦輩輪輬輮輯輳輶輸輻輼輾輿轀轂轄轅轆轉轍轎轔轟轡轢轤辦辭辮辯農迴逕這連週進遊運過達違遙遜遞遠遡適遲遶遷"
    "選遺遼邁還邇邊邏邐郟郵鄆鄉鄒鄔鄖鄧鄩鄭鄰鄲鄳鄴鄶鄺酇酈醃醖醜醞醟醣醫醬醱醲釀釁釃釅釋釐釒釓釔釕釗釘釙針釣釤釦釧釩釴釵釷釹"
    "釺釾釿鈀鈁鈃鈄鈅鈇鈈鈉鈍鈎鈐鈑鈒鈔鈕鈞鈡鈣鈥鈦鈧鈮鈰鈳鈴鈷鈸鈹鈺鈽鈾鈿鉀鉅鉆鉈鉉鉊鉋鉍鉑鉕鉗鉚鉛鉝鉞鉢鉤鉥鉦鉧鉬鉭鉮鉳鉶"
    "鉷鉸鉺鉻鉿銀銃銅銈銍銑銓銖銘銚銛銜銠銣銥銦銨銩銪銫銬銱銳銶銷銹銻銼鋁鋃鋅鋇鋌鋏鋐鋒鋗鋙鋝鋟鋣鋤鋥鋦鋨鋩鋪鋭鋮鋯鋰鋱鋶鋸鋹"
    "鋼錀錁錄錆錇錈錏錐錒錕錘錙錚錛錞錟錠錡錢錤錦錨錩錫錮錯録錳錶錸錼鍀鍁鍃鍅鍆鍇鍈鍊鍋鍍鍔鍘鍚鍛鍠鍤鍥鍩鍬鍭鍰鍵鍶鍺鍼鍾鎂鎄"
    "鎇鎊鎌鎓鎔鎖鎘鎚鎛鎝鎡鎢鎣鎦鎧鎩鎪鎬鎭鎮鎰鎲鎳鎵鎶鎸鎿鏃鏇鏈鏌鏍鏏鏐鏑鏗鏘鏜鏝鏞鏟鏡鏢鏤鏨鏰鏵鏷鏹鏺鏻鏽鐃鐄鐇鐋鐍鐏鐐鐒"
    "鐓鐔鐘鐙鐝鐠鐥鐦鐧鐨鐩鐫鐮鐯鐲鐳鐵鐶鐸鐺鐽鐿鑄鑊鑌鑑鑒鑔鑕鑞鑠鑣鑥鑪鑭鑰鑱鑲鑷鑹鑼鑽鑾鑿钁钂長門閂閃閆閈閉開閌閎閏閑閒間"
    "閔閘閡閣閤閥閨閩閫閬閭閱閲閶閹閻閼閽閾閿闃闆闇闈闉闊闋闌闍闐闑闒闓闔闕闖關闞闠闡闢闤闥陘陝陞陣陰陳陸陽隉隊階隑隕際隤隨險"
    "隮隯隱隴隸隻雋雖雙雛雜雞離難雲電霑霢霧霽靂靄靆靈靉靚靜靝靦靨鞏鞝鞦鞽韁韃韆韉韋韌韍韓韙韜韝韞韻響頁頂頃項順頇須頊頌頍頎頏"
    "預頑頒頓頔頗領頜頠頡頤頦頫頭頮頰頲頴頵頷頸頹頻頽顆題額顎顏顒顓顔顗願顙顛類顢顥顧顫顬顯顰顱顳顴風颭颮颯颱颳颶颸颺颻颼飀飄"
    "飆飈飛飠飢飣飥飩飪飫飭飯飱飲飴飼飽飾飿餃餄餅餈餉養餌餎餏餑餒餓餕餖餗餘餚餛餜餞餡館餬餱餳餵餶餷餸餺餼餾餿饁饃饅饈饉饊饋饌"
    "饑饒饗饘饜饞饢馬馭馮馱馳馴馹馼駁駃駉駐駑駒駓駔駕駘駙駛駝駟駡駢駪駭駰駱駸駼駿騁騂騄騅騊騌騍騎騏騑騖騙騞騠騤騧騫騭騮騰騱騵"
    "騶騷騸騾驀驁驂驃驄驅驊驌驍驎驏驕驗驚驛驟驢驤驥驦驪驫骯髏髒體髕髖髮鬆鬍鬚鬢鬥鬧鬨鬩鬮鬱鬹魎魘魚魛魟魢魨魯魴魷魺鮀鮁鮃鮆鮈"
    "鮊鮋鮍鮎鮐鮑鮒鮓鮚鮜鮝鮞鮠鮡鮣鮦鮪鮫鮭鮮鮳鮶鮸鮺鯀鯁鯇鯉鯊鯒鯔鯕鯖鯗鯛鯝鯡鯢鯤鯧鯨鯪鯫鯰鯴鯷鯻鯽鯿鰁鰂鰃鰆鰈鰉鰊鰌鰍鰏鰐"
    "鰒鰓鰛鰜鰟鰠鰣鰤鰥鰧鰨鰩鰭鰮鰱鰲鰳鰵鰶鰷鰹鰺鰻鰼鰾鱀鱂鱅鱈鱉鱒鱔鱖鱗鱘鱚鱝鱟鱠鱣鱤鱧鱨鱭鱯鱲鱷鱸鱺鳥鳧鳩鳬鳲鳳鳴鳶鳾鴆鴇"
    "鴉鴒鴕鴛鴝鴞鴟鴣鴦鴨鴯鴰鴴鴷鴻鴿鵁鵂鵃鵏鵐鵑鵒鵓鵜鵝鵟鵠鵡鵪鵬鵮鵯鵰鵲鵷鵾鶄鶇鶉鶊鶓鶖鶘鶚鶠鶡鶥鶩鶪鶬鶯鶱鶲鶴鶹鶺鶻鶼鶿"
    "鷀鷁鷂鷄鷉鷊鷓鷖鷗鷙鷚鷟鷥鷦鷫鷭鷯鷲鷳鷴鷸鷹鷺鷽鸂鸇鸊鸌鸏鸑鸕鸘鸚鸛鸝鸞鹵鹹鹺鹼鹽麗麥麩麪麫麬麯麳麴麵麼麽黃黌點黨黲黴黶"
    "黷黽黿鼂鼉鼕鼴齊齋齎齏齒齔齕齗齘齙齜齟齠齡齣齦齧齪齬齮齯齲齶齷齼龍龎龐龑龔龕龜鿁鿓"
)
P16_RE = re.compile("[%s]" % P16_TRADITIONAL)

# ---------------------------------------------------------------------------
# 译注页（Note）检查：词表与判定口径的唯一来源
#
# 规范正文见 `docs/translation-spec.md` 三.2 与 `AGENTS.md`「译注页（Note）结构规约」。
# 本文件的常量是机器判定的唯一来源，规范与 `tools/README.md` 只留指针、不复制词表。
# 全库基线：73 个 `S<作品号>-Note.xhtml` / 856 条。
# ---------------------------------------------------------------------------

# 语言标签词表：同一语言只取规范译名，**不取库内多数派**——`纳瓦特语`(4:1)、
# `古诺斯语`(3:1) 的多数派写法恰好都不规范。`希腊语` 与 `古希腊语` **分列不合并**：
# 前者配现代希腊语单音调写法、后者配古希腊语多音调（带气号）写法，是语言的历史阶段差异。
NOTE_LANG_LABELS = {
    "拉丁语": "拉丁语", "拉丁文": "拉丁语", "拉丁语名": "拉丁语",
    "希伯来语": "希伯来语", "希伯来文": "希伯来语",
    "纳瓦特语": "纳瓦特尔语", "纳瓦特尔语": "纳瓦特尔语",
    "古诺斯语": "古诺尔斯语", "古诺尔斯语": "古诺尔斯语",
    "希腊语": "希腊语", "古希腊语": "古希腊语",
    "梵语": "梵语", "英语": "英语", "法语": "法语", "德语": "德语", "俄语": "俄语",
    "意大利语": "意大利语", "西班牙语": "西班牙语", "葡萄牙语": "葡萄牙语",
    "冰岛语": "冰岛语", "乌克兰语": "乌克兰语", "加泰罗尼亚语": "加泰罗尼亚语",
    "越南语": "越南语", "弗里吉亚语": "弗里吉亚语", "匈牙利语": "匈牙利语", "日语": "日语",
}
NOTE_LANG_CANONICAL = frozenset(NOTE_LANG_LABELS.values())
NOTE_LANG_LABEL_RE = re.compile(r"（([^（）：:]{1,10})[：:]([^（）]*)）")

# 起句三类（三.2「起句」）：甲 复现被注词 / 乙 无主语界说 / 丙 引证。
# 全库 372 条（43.5%）不满足本白名单，是「不同译者文风分裂」的主要形态。
NOTE_LEAD_PATTERNS = (
    re.compile(r"^[^，。；：]{1,26}（[^）]{1,40}）"),                          # 甲·带原文括注
    re.compile(r"^[^，。；：]{1,22}(是|为|原指|原是)"),                        # 甲·带谓语
    re.compile(r"^(指的是|指|即|意为|意思为|又称|也称|又名|亦称|俗称|原指|应该|应当|可能)"),  # 乙
    re.compile(r"^原文(为|中|是|注释)"),                                     # 丙·引证原文
    re.compile(r"^(据|根据|依据|出自|典出|引自|见于)"),                        # 丙·引证出处
)

# 同义谓语词收敛：库内写法 → 规范写法。**只在本表的键上判定**。
# 三族刻意不合并（各承独立语义，合并会丢信息）：
#   `即`（等号关系，如「Patriot Advanced Capability-3，即爱国者3型导弹。」）
#   `意为`／`意思为`（词义翻译，如「ambulance意为救护车。」）
#   `原指`（词源变迁，如「原指15～17世纪时…的武器。」）
NOTE_PREDICATE_CONVERGENCE = {
    "均为": "是", "则为": "是", "原为": "是",
    "指的是": "指", "是指": "指", "指的就是": "指", "此处指": "指",
    "也称": "又称", "又名": "又称", "亦称": "又称", "俗称": "又称",
    "原文中": "原文为", "原文是": "原文为", "原文注释": "原文为",
    "根据": "据",
    "典出": "出自", "引自": "出自", "见于": "出自",
}
NOTE_PREDICATE_KEEP = frozenset({"即", "意为", "意思为", "原指"})

# 不可见字符：LRM（希伯来文等 RTL 文本在 LTR 环境中的终止符）与 ZWJ（天城文
# 半体合写）是排版所需，**保留**；ZWNJ、ZWSP、BOM 与 NBSP 违规。
NOTE_INVIS_KEEP = frozenset({"\u200e", "\u200d"})
NOTE_INVIS_BAD = {
    "\u200c": "U+200C ZWNJ",
    "\u00a0": "U+00A0 NBSP",
    "\u200b": "U+200B ZWSP",
    "\ufeff": "U+FEFF BOM/ZWNBSP",
}

# 区间连接符：全库 25 处三种写法并存，**只报告不自动改**——`1897-1982` 是生卒年
# 通行写法、`1至1.8米` 改法不唯一，够不上 `text_norm.py`「替换值唯一确定」的门槛。
NOTE_RANGE_PATTERNS = (
    (re.compile(r"\d+\s*至\s*\d+"), "区间用「至」，建议统一为浪纹连接号 ～（生卒年除外）"),
    (re.compile(r"\d{2,4}\s*-\s*\d{2,4}"), "区间用半角连字符，请确认是否为生卒年（生卒年可保留）"),
)

# 互参：依赖编号或顺序的文字指代会被 `reorder_notes.py` 静默改错——该工具按书
# 重编号，且只重写正文 `href` 锚点与 Note 页 `id` 顺序，**注释正文里的中文文字引用一概不碰**。
NOTE_XREF_BAD = (
    (re.compile(r"(详见|参见|见)\s*注释\s*\d+"), "以数字注号互参：重排后会指错，应直接给出被注词"),
    (re.compile(r"^(与)?前者|^后者"), "以「前者／后者」顺序指代互参：重排后会指错"),
)

# P17 半角括号判据的两项辅助字符类：
#   LATIN_RE   —— `(N)Ever_Say_Good_bye.` 这类英文串里的半角括号是英文写法，合法；
#   KAOMOJI_RE —— `(╯‵□′)╯︵┻━┻` 这类颜文字由半角 ASCII 符号构成，括号是组成部分，合法。
LATIN_RE = re.compile(r"[A-Za-z]")
KAOMOJI_RE = re.compile(r"[╯╰︵︶‵′□▽≧≦°∀Дﾟ⌒╭╮╲╱]")

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
    # 单位（赛事项目名中的「公里」豁免，见 P9_EVENT_SUFFIXES）
    (re.compile(r"公斤|公里(?!%s)" % "|".join(P9_EVENT_SUFFIXES)), "P9", "warning",
     "单位“公斤/公里”，规范建议对应キロ用 千克/千米（赛事项目名如“十公里长跑”除外），"),
    # 语气词/音译（示例词表见 P11_EXAMPLES；「噗噗」「哔哔」与合法拟声同形，不设机械检查）
    *[(re.compile(pattern, flags), "P11", "info", message)
      for pattern, flags, message in P11_EXAMPLES],
    # 单个省略号（非 …… 连用）
    (re.compile(r"(?<![…])…(?![…])"), "P12", "info",
     "单个省略号…（未与另一个…组成……），请确认是否有意为之，"),
    # 连续 ASCII 空格（仅正文文件触发，标题行另行排除）
    (re.compile(r" {3,}"), "P13", "info",
     "连续 ASCII 空格（3+），疑似交稿残留或断断续续表达，请确认，"),
    # 小数用阿拉伯数字：汉字数字+小数点+汉字数字 不符合中文数字写法
    (re.compile(r"[〇零一二三四五六七八九][.．・·][〇零一二三四五六七八九]+"), "P14", "error",
     "小数应使用阿拉伯数字（如 0.7），不得写成汉字数字+小数点（如 〇.七、三·五），"),
    # 淘汰异形词残留（规范推荐使用《第一批异形词整理表》及《现代汉语词典》推荐词形）
    (re.compile(r"(?<!想)想像(?!(?:这|那)(?:样|般))"), "P15", "warning",
     "淘汰异形词「想像」，规范建议统一为「想象」（若为动词“想”＋“像……”等句法组合可忽略），"),
    # 繁体字残留（字表见 P16_TRADITIONAL；包装页与含假名的原文引用行在下文豁免）
    (P16_RE, "P16", "warning",
     "正文出现繁体字，X 版一律用简体（汉化组的繁简混杂不保留；日文原文引用可忽略），"),
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


CJKX_RE = re.compile("[%s]" % CJKX)


def check_note(text):
    """译注页（Note）条目检查；只在 fkind == 'note' 时由 check_text 调用。

    判定口径的唯一来源见本模块的 NOTE_* 常量与 `docs/translation-spec.md` 三.2。
    P17/P20 需要配对逻辑，因此不做成 CHECK_TEXT 的纯正则项。
    """
    hits = []
    body = text.strip()
    # 外壳行（`<h1 class="center">译注</h1>`、`<ul>`、`</ul>`）不参与条目检查
    if not body or body in ("译注", "</ul>"):
        return hits

    def add(cat, sev, msg, seg, n=72):
        hits.append((cat, sev, msg, short(seg, n)))

    # P17 半角括号：**两条并列的违规条件**，满足其一即违规，颜文字整体豁免。
    #   ① 配对片段内含 CJK（含全角标点）——`（endorphins)`、`(Sir … Frazer）`
    #   ② 片段是纯外文但**嵌在中文行文里**：前一个非空格字符是 CJK，且后一个
    #      非空格字符不是拉丁字母——`赫朗格尼尔 (Hrungnir)，`、`赫朗格尼尔 (Hrungnir)是` 违规；
    #      而 `(N)Ever_Say_Good_bye.` 后接 `E`、`Multiple Independently (Targetable) …`
    #      前接 `y`，两者都合法。
    # 未配对的孤立半角括号（`（endorphins)` 的 `)`、`(Sir … Frazer）` 的 `(`）用
    # ±12 字窗口取片段——孤立括号必与全角括号混用，窗口内必含 CJK。
    # 全库回测：Note 页 8 处半角括号 → 违规 6、合法 2，零误报零漏报。
    paired = [(m.start(), m.end() - 1) for m in re.finditer(r"\(([^()]*)\)", body)]
    covered = {k for a, b in paired for k in range(a, b + 1)}
    targets = [(a, b, body[a:b + 1]) for a, b in paired]
    for m in re.finditer(r"[()]", body):
        k = m.start()
        if k not in covered:
            targets.append((k, k, body[max(0, k - 12):k + 13]))
    for i, j, seg in targets:
        # 颜文字豁免：(╯‵□′)╯︵┻━┻ 一类由半角 ASCII 符号构成，括号是组成部分
        if KAOMOJI_RE.search(seg) or KAOMOJI_RE.search(body[max(0, i - 3):j + 4]):
            continue
        if CJKX_RE.search(seg):
            bad = True
        else:
            k = i - 1
            while k >= 0 and body[k] == " ":
                k -= 1
            n = j + 1
            while n < len(body) and body[n] == " ":
                n += 1
            prev_ch = body[k] if k >= 0 else ""
            next_ch = body[n] if n < len(body) else ""
            bad = bool(prev_ch and CJKX_RE.match(prev_ch) and not LATIN_RE.match(next_ch))
        if bad:
            add("P17", "error",
                "中文语境半角括号，应改为全角（）（纯外文串与颜文字内的半角括号合法），", seg)

    # P20 括号配对：全角、半角各自的开闭数量必须相等。**分域判据**——Note 页的
    # `<li>` 是自足单元，可用严格判据；正文存在跨段整段括注，不得套用本判据。
    for op, cl, name in (("（", "）", "全角"), ("(", ")", "半角")):
        if body.count(op) != body.count(cl):
            add("P20", "error",
                "%s括号不配对（开 %d / 闭 %d），" % (name, body.count(op), body.count(cl)), body)

    # P18 括号字符白名单：`【】``〈〉``［］` 各有合法用途（标题式标记／国标单书名号），
    # 只报告不自动改；`〔〕` 作补充说明时已由 text_norm.py 自动改为圆括号。
    for m in re.finditer(r"[【】〈〉［］]", body):
        add("P18", "warning",
            "非常用括号字符，请确认是否为标题式标记或单书名号（〔〕已由 text_norm 自动处理），",
            body[max(0, m.start() - 12):m.start() + 13])

    # P19 不可见字符（LRM/ZWJ 是 RTL 与天城文排版所需，见 NOTE_INVIS_KEEP，不报）
    for ch, nm in NOTE_INVIS_BAD.items():
        if ch in body:
            add("P19", "warning", "含不可见字符 %s，应删除或替换为全角空格，" % nm, body)

    # P21 区间连接符（只报告：改法不唯一，够不上自动规范化的门槛）
    for rx, msg in NOTE_RANGE_PATTERNS:
        for m in rx.finditer(body):
            add("P21", "info", msg + "，", body[max(0, m.start() - 10):m.end() + 10])

    # P22 语言标签：同一语言只取规范译名（词表见 NOTE_LANG_LABELS）
    for m in NOTE_LANG_LABEL_RE.finditer(body):
        raw = m.group(1)
        canon = NOTE_LANG_LABELS.get(raw)
        if canon and canon != raw:
            add("P22", "warning", "语言标签「%s」应统一为「%s」，" % (raw, canon), m.group(0))

    # P23 起句：必须以三.2 的三类之一起句
    if not any(rx.match(body) for rx in NOTE_LEAD_PATTERNS):
        add("P23", "warning",
            "起句不在三类白名单内（甲 复现被注词／乙 无主语界说／丙 引证），", body)

    # P24 同义谓语词收敛（只查起句区，且不打散 NOTE_PREDICATE_KEEP 三族）
    zone = body[:30]
    for word, canon in NOTE_PREDICATE_CONVERGENCE.items():
        if word in zone:
            add("P24", "info", "谓语词「%s」应收敛为「%s」，" % (word, canon), zone)
            break

    # P25 互参：数字注号与顺序指代会被 reorder_notes.py 静默改错
    for rx, msg in NOTE_XREF_BAD:
        for m in rx.finditer(body):
            add("P25", "warning", msg + "，", body[max(0, m.start() - 10):m.end() + 12])

    return hits


def check_text(line, fkind):
    """对剥离标签的文本跑 TEXT 检查，返回 (category, severity, message, example) 列表。

    先整段移除 <style>/<script>/<rt> 块避免 CSS、JS、注音泄漏，再剥标签、反转义。
    类别级豁免：
    - P7 日文点号・：Note 页引用日文原文属合法，跳过；
    - P13 连续空格：仅对正文内容文件判定，且跳过 h1/h2 标题行。
    Note 页另跑 check_note（P17–P25），因此不重复实现 Note 专属判据。
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
        if cat == "P16" and (fkind != "content" or KANA_RE.search(text)):
            continue
        for m in rx.finditer(text):
            s = max(0, m.start() - 12)
            example = text[s:m.end() + 12]
            hits.append((cat, sev, msg, short(example, 72)))
    if fkind == "note":
        hits.extend(check_note(text))
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


def audit_book(text_dir) -> list[tuple[str, int, str, str, str, str]]:
    """检查一本书的 `OEBPS/Text/` 目录，返回全部命中；只读，不写任何文件。

    返回 (file, line, category, severity, message, example) 列表，供本文件的
    `main()` 与 `tools/publish_preflight.py` 共用——发布预检只取 `severity ==
    "error"` 的项作阻断，warning／info 仍只报告（见 `tools/README.md` 的门禁列）。
    """
    findings: list[tuple[str, int, str, str, str, str]] = []
    for fn in sorted(os.listdir(text_dir)):
        if not fn.endswith(".xhtml"):
            continue
        fkind = classify(fn)
        path = os.path.join(text_dir, fn)
        try:
            with open(path, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except Exception:
            continue
        for ln, line in enumerate(lines, 1):
            # ruby 检查（原始行）
            for cat, sev, msg, ex in check_ruby(line, fkind):
                findings.append((fn, ln, cat, sev, msg, ex))
            # 文本检查（先移除 <style>/<script>/<rt> 块再剥标签）
            for cat, sev, msg, ex in check_text(line, fkind):
                findings.append((fn, ln, cat, sev, msg, ex))
            # 假名残留（仅正文内容文件）
            if fkind == "content":
                for cat, sev, msg, ex in check_kana(strip_to_text(line), ln, fn):
                    findings.append((fn, ln, cat, sev, msg, ex))
    return findings


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
        for fn, ln, cat, sev, msg, ex in audit_book(text_dir):
            per_book[book].setdefault(fn, OrderedDict())
            emit(book, fn, ln, cat, sev, msg, ex)

    # ---- 终端摘要 ----
    print("共检查 %d 本书。命中 %d 条（按类别：%s）。" % (
        len(books_checked), len(findings),
        ", ".join("%s=%d" % (c, n) for c, n in sorted(category_counts.items(), key=lambda x: int(x[0][1:])))))
    for cat in ["P1", "P3", "P4", "P5", "P6", "P7", "P8", "P15"]:
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
        "P9": "单位（公斤/公里；赛事项目名豁免）",
        "P10": "注音 ruby 问题",
        "P11": "语气词/音译（规范示例：切！、啊啦、呀吼、吥吥）",
        "P12": "单个省略号…",
        "P13": "连续 ASCII 空格",
        "P14": "小数应使用阿拉伯数字（非汉字数字+小数点）",
        "P15": "淘汰异形词残留（规范推荐词形，如「想象」不作「想像」）",
        "P16": "繁体字残留（Note／Information 与含假名的原文引用行豁免）",
        # P17–P25 只对 Note 页（`*-Note.xhtml`）判定，口径见 docs/translation-spec.md 三.2
        "P17": "译注·中文语境半角括号（纯外文串与颜文字内合法）",
        "P18": "译注·非常用括号字符（【】〈〉［］，需人工判断用途）",
        "P19": "译注·不可见字符（LRM/ZWJ 为排版所需，不报）",
        "P20": "译注·括号不配对",
        "P21": "译注·区间连接符（只报告：改法不唯一）",
        "P22": "译注·语言标签用词（应取规范译名，不取库内多数派）",
        "P23": "译注·起句（须属三类白名单：甲 复现被注词／乙 无主语界说／丙 引证）",
        "P24": "译注·谓语词未收敛（即／意为／原指 三族刻意保留，不报）",
        "P25": "译注·互参用数字注号或顺序指代（重排后会指错）",
    }
    for cat in sorted(cat_desc, key=lambda x: int(x[1:])):
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
                with open(os.path.join(text_dir, fn), encoding="utf-8-sig") as f:
                    t = f.read()
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
