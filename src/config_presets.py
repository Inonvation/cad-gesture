"""预设命令库和默认配置"""

import copy
from typing import Dict, Any

def get_preset_commands(target: str = "autocad") -> Dict[str, Dict[str, str]]:
    """获取预设命令库，根据 target 返回对应命令集
    
    Args:
        target: "autocad" 或 "zwcad"
    """
    # ========== 基础命令（两者共有） ==========
    base_commands = {
        "绘图": {
            "直线": {"key": "l", "description": "LINE", "label": "直线"},
            "圆": {"key": "c", "description": "CIRCLE", "label": "圆"},
            "圆弧": {"key": "a", "description": "ARC", "label": "圆弧"},
            "矩形": {"key": "rec", "description": "RECTANG", "label": "矩形"},
            "多段线": {"key": "pl", "description": "PLINE", "label": "多段线"},
            "样条曲线": {"key": "spl", "description": "SPLINE", "label": "样条"},
            "椭圆": {"key": "el", "description": "ELLIPSE", "label": "椭圆"},
            "填充": {"key": "h", "description": "BHATCH", "label": "填充"},
            "创建块": {"key": "b", "description": "BLOCK", "label": "块"},
            "插入块": {"key": "i", "description": "INSERT", "label": "插入块"},
            "点": {"key": "po", "description": "POINT", "label": "点"},
            "正多边形": {"key": "pol", "description": "POLYGON", "label": "多边形"},
            "圆环": {"key": "do", "description": "DONUT", "label": "圆环"},
            "构造线": {"key": "xl", "description": "XLINE", "label": "构造线"},
            "射线": {"key": "ray", "description": "RAY", "label": "射线"},
            "多线": {"key": "ml", "description": "MLINE", "label": "多线"},
            "边界": {"key": "bo", "description": "BOUNDARY", "label": "边界"},
            "面域": {"key": "reg", "description": "REGION", "label": "面域"},
            "渐变色填充": {"key": "gd", "description": "GRADIENT", "label": "渐变色"},
            "写块": {"key": "w", "description": "WBLOCK", "label": "写块"},
            "表格": {"key": "tb", "description": "TABLE", "label": "表格"},
        },
        "编辑修改": {
            "复制": {"key": "co", "description": "COPY", "label": "复制"},
            "移动": {"key": "m", "description": "MOVE", "label": "移动"},
            "删除": {"key": "e", "description": "ERASE", "label": "删除"},
            "偏移": {"key": "o", "description": "OFFSET", "label": "偏移"},
            "修剪": {"key": "tr", "description": "TRIM", "label": "修剪"},
            "延伸": {"key": "ex", "description": "EXTEND", "label": "延伸"},
            "镜像": {"key": "mi", "description": "MIRROR", "label": "镜像"},
            "旋转": {"key": "ro", "description": "ROTATE", "label": "旋转"},
            "缩放": {"key": "sc", "description": "SCALE", "label": "缩放"},
            "拉伸": {"key": "s", "description": "STRETCH", "label": "拉伸"},
            "打断": {"key": "br", "description": "BREAK", "label": "打断"},
            "圆角": {"key": "f", "description": "FILLET", "label": "圆角"},
            "倒角": {"key": "cha", "description": "CHAMFER", "label": "倒角"},
            "分解": {"key": "x", "description": "EXPLODE", "label": "分解"},
            "特性匹配": {"key": "ma", "description": "MATCHPROP", "label": "特性匹配"},
            "编辑多段线": {"key": "pe", "description": "PEDIT", "label": "编辑多段线"},
            "修改属性": {"key": "ch", "description": "CHANGE", "label": "修改属性"},
            "撤销删除": {"key": "oo", "description": "OOPS", "label": "撤销删除"},
            "定数等分": {"key": "div", "description": "DIVIDE", "label": "定数等分"},
            "定距等分": {"key": "me", "description": "MEASURE", "label": "定距等分"},
        },
        "标注": {
            "标注样式": {"key": "d", "description": "DDIM", "label": "标注样式"},
            "线性标注": {"key": "dli", "description": "DIMLINEAR", "label": "线性标注"},
            "对齐标注": {"key": "dal", "description": "DIMALIGNED", "label": "对齐标注"},
            "半径标注": {"key": "dra", "description": "DIMRADIUS", "label": "半径标注"},
            "直径标注": {"key": "ddi", "description": "DIMDIAMETER", "label": "直径标注"},
            "角度标注": {"key": "dan", "description": "DIMANGULAR", "label": "角度标注"},
            "基线标注": {"key": "dba", "description": "DIMBASELINE", "label": "基线标注"},
            "连续标注": {"key": "dco", "description": "DIMCONTINUE", "label": "连续标注"},
            "圆心标记": {"key": "dce", "description": "DIMCENTER", "label": "圆心标记"},
            "坐标标注": {"key": "dor", "description": "DIMORDINATE", "label": "坐标标注"},
            "快速引线": {"key": "le", "description": "QLEADER", "label": "引线"},
            "编辑标注": {"key": "ded", "description": "DIMEDIT", "label": "编辑标注"},
        },
        "文字与样式": {
            "单行文字": {"key": "dt", "description": "TEXT", "label": "单行文字"},
            "多行文字": {"key": "t", "description": "MTEXT", "label": "多行文字"},
            "文字编辑": {"key": "ed", "description": "TEXTEDIT", "label": "文字编辑"},
            "图层": {"key": "la", "description": "LAYER", "label": "图层"},
            "线型": {"key": "lt", "description": "LINETYPE", "label": "线型"},
            "线宽": {"key": "lw", "description": "LWEIGHT", "label": "线宽"},
            "颜色": {"key": "col", "description": "COLOR", "label": "颜色"},
            "文字样式": {"key": "st", "description": "STYLE", "label": "文字样式"},
            "表格样式": {"key": "ts", "description": "TABLESTYLE", "label": "表格样式"},
            "线型比例": {"key": "lts", "description": "LTSCALE", "label": "线型比例"},
        },
        "视图与系统": {
            "缩放": {"key": "z", "description": "ZOOM", "label": "缩放"},
            "平移": {"key": "p", "description": "PAN", "label": "平移"},
            "重生成": {"key": "re", "description": "REGEN", "label": "重生成"},
            "距离测量": {"key": "di", "description": "DIST", "label": "距离"},
            "列表显示": {"key": "li", "description": "LIST", "label": "列表"},
            "选项设置": {"key": "op", "description": "OPTIONS", "label": "选项"},
            "草图设置": {"key": "ds", "description": "DSETTINGS", "label": "草图设置"},
            "单位设置": {"key": "un", "description": "UNITS", "label": "单位"},
            "清理": {"key": "pu", "description": "PURGE", "label": "清理"},
            "重命名": {"key": "ren", "description": "RENAME", "label": "重命名"},
            "对象特性": {"key": "pr", "description": "PROPERTIES", "label": "特性"},
            "进入视口": {"key": "ms", "description": "MSPACE", "label": "进入视口"},
            "退出视口": {"key": "ps", "description": "PSPACE", "label": "退出视口"},
        },
        "快捷操作": {
            "撤销": {"key": "ctrl+z", "description": "U", "label": "撤销"},
            "重做": {"key": "ctrl+y", "description": "REDO", "label": "重做"},
            "保存": {"key": "ctrl+s", "description": "QSAVE", "label": "保存"},
            "另存为": {"key": "ctrl+shift+s", "description": "SAVEAS", "label": "另存为"},
            "打开": {"key": "ctrl+o", "description": "OPEN", "label": "打开"},
            "新建": {"key": "ctrl+n", "description": "NEW", "label": "新建"},
            "打印": {"key": "ctrl+p", "description": "PRINT", "label": "打印"},
            "复制到剪贴板": {"key": "ctrl+c", "description": "COPYCLIP", "label": "复制"},
            "粘贴": {"key": "ctrl+v", "description": "PASTECLIP", "label": "粘贴"},
            "剪切": {"key": "ctrl+x", "description": "CUTCLIP", "label": "剪切"},
            "全选": {"key": "ctrl+a", "description": "AI_SELALL", "label": "全选"},
            "带基点复制": {"key": "ctrl+shift+c", "description": "COPYBASE", "label": "基点复制"},
            "粘贴为块": {"key": "ctrl+shift+v", "description": "PASTEBLOCK", "label": "粘贴为块"},
        },
        "开关切换": {
            "正交": {"key": "f8", "description": "ORTHO", "label": "正交"},
            "对象捕捉": {"key": "f3", "description": "OSNAP", "label": "对象捕捉"},
            "栅格": {"key": "f7", "description": "GRID", "label": "栅格"},
            "捕捉": {"key": "f9", "description": "SNAP", "label": "捕捉"},
            "极轴": {"key": "f10", "description": "POLAR", "label": "极轴"},
            "对象追踪": {"key": "f11", "description": "OTRACK", "label": "追踪"},
        },
    }

    # AutoCAD 直接返回基础命令
    if target == "autocad":
        return base_commands

    # ========== 中望CAD 机械版专属命令（按《中望CAD快捷键指南》完整分类） ==========
    zw_mech_commands = {
        # 一、尺寸标注
        "尺寸标注": {
            "智能标注": {"key": "d", "description": "ZWMPOWERDIM", "label": "智能标注"},
            "长度标注": {"key": "", "description": "ZWMLINEARDIM", "label": "长度标注"},
            "水平标注": {"key": "", "description": "ZWMHORIZONTALDIM", "label": "水平标注"},
            "垂直标注": {"key": "", "description": "ZWMVERTICALDIM", "label": "垂直标注"},
            "对齐标注": {"key": "", "description": "ZWMALIGNEDDIM", "label": "对齐标注"},
            "半剖标注": {"key": "", "description": "ZWMHALFALIGNDIM", "label": "半剖标注"},
            "点线标注": {"key": "", "description": "ZWMPTLINEDIM", "label": "点线标注"},
            "直径标注": {"key": "", "description": "ZWMDIAMETERDIM", "label": "直径标注"},
            "半径标注": {"key": "", "description": "ZWMRADIUSDIM", "label": "半径标注"},
            "折弯标注": {"key": "", "description": "ZWMJOGGEDRADIUSDIM", "label": "折弯标注"},
            "坐标标注": {"key": "", "description": "ZWM_DIMORDINATE", "label": "坐标标注"},
            "弧长标注": {"key": "", "description": "ZWMARCLENGTHDIM", "label": "弧长标注"},
            "连续标注": {"key": "", "description": "ZWMCHAINDIM", "label": "连续标注"},
            "基线标注": {"key": "", "description": "ZWMBASELINEDIM", "label": "基线标注"},
            "中心记号": {"key": "", "description": "ZWMCENTERDIM", "label": "中心记号"},
            "角度标注": {"key": "", "description": "ZWMANGULARDIM", "label": "角度标注"},
            "引线标注": {"key": "", "description": "ZWMANGULARDIM YX", "label": "引线标注"},
            "板厚标注": {"key": "", "description": "ZWMTHICKNESSDIM", "label": "板厚标注"},
            "倒角标注": {"key": "", "description": "ZWMCHAMFERSYM DB", "label": "倒角标注"},
        },
        # 二、标注编辑
        "标注编辑": {
            "尺寸合并": {"key": "", "description": "ZWMDIMJOIN", "label": "尺寸合并"},
            "尺寸插入": {"key": "", "description": "ZWMDIMINSERT", "label": "尺寸插入"},
            "尺寸对齐": {"key": "", "description": "ZWMDIMALIGN", "label": "尺寸对齐"},
            "尺寸检查": {"key": "", "description": "ZWMDIMCHECK", "label": "尺寸检查"},
            "公差查询": {"key": "", "description": "ZWMDIMTOLQUERY", "label": "公差查询"},
        },
        # 三、构造工具
        "构造工具": {
            "构造线": {"key": "", "description": "ZWMCONSTLINES", "label": "构造线"},
            "自动构造线": {"key": "", "description": "ZWMAUTOCLINES", "label": "自动构造线"},
            "水平构造线": {"key": "", "description": "ZWMCONSTHOR", "label": "水平构造线"},
            "垂直构造线": {"key": "", "description": "ZWMCONSTVER", "label": "垂直构造线"},
            "交叉构造线": {"key": "", "description": "ZWMCONSTCRS", "label": "交叉构造线"},
            "两点构造线": {"key": "", "description": "ZWMCONSTHB", "label": "两点构造线"},
            "成角构造线": {"key": "", "description": "ZWMCONSTHW", "label": "成角构造线"},
            "全距平行线": {"key": "", "description": "ZWMCONSTPAR", "label": "全距平行线"},
            "半距平行线": {"key": "", "description": "ZWMCONSTPAR2", "label": "半距平行线"},
            "两点垂线": {"key": "", "description": "ZWMCONSTLOT2", "label": "两点垂线"},
            "直线垂线": {"key": "", "description": "ZWMCONSTLOT", "label": "直线垂线"},
            "角等分线": {"key": "", "description": "ZWMCONSTHM", "label": "角等分线"},
            "过点射线": {"key": "", "description": "ZWMCONSTXRAY", "label": "过点射线"},
            "过点直线": {"key": "", "description": "ZWMCONSTXLINE", "label": "过点直线"},
            "Z方向构造线": {"key": "", "description": "ZWMCONSTZ", "label": "Z方向构造线"},
            "圆切平行线": {"key": "", "description": "ZWMCONSTTAN", "label": "圆切平行线"},
            "两圆切线": {"key": "", "description": "ZWMCONSTTC", "label": "两圆切线"},
            "同心构造线": {"key": "", "description": "ZWMCONSTCC", "label": "同心构造线"},
            "轴断面构造线": {"key": "", "description": "ZWMCONSTCCREA", "label": "轴断面构造线"},
            "双线切圆": {"key": "", "description": "ZWMCONSTKR", "label": "双线切圆"},
            "外切矩形构造线": {"key": "", "description": "ZWMCONSTCIRCLI", "label": "外切矩形构造线"},
            "构造圆": {"key": "", "description": "ZWMCONSTCIRCLE", "label": "构造圆"},
            "已知圆心画圆": {"key": "hy", "description": "ZWMCIRCLEBYC", "label": "圆心画圆"},
            "已知端点画圆": {"key": "hyd", "description": "ZWMCIRCLEBY3P", "label": "端点画圆"},
            "已知圆心画弧": {"key": "hh", "description": "ZWMARCBYC", "label": "圆心画弧"},
            "已知端点画弧": {"key": "hhd", "description": "ZWMARCBY3P", "label": "端点画弧"},
            "直线切构造圆": {"key": "", "description": "ZWMCONSTC2", "label": "直线切构造圆"},
            "工艺槽构造": {"key": "gy", "description": "ZWMCONSTRECESS", "label": "工艺槽构造"},
        },
        # 四、绘图工具
        "绘图工具": {
            "智能画线": {"key": "ss", "description": "ZWMINTELLIGENTLINE", "label": "智能画线"},
            "对称画线": {"key": "dc", "description": "ZWMMIRRORLINE", "label": "对称画线"},
            "并行线": {"key": "px", "description": "ZWMPARALLELLINE", "label": "并行线"},
            "垂直线": {"key": "cz", "description": "ZWMVERTICALLINE", "label": "垂直线"},
            "切线": {"key": "qx", "description": "ZWMTANGENTLINE", "label": "切线"},
            "公切线": {"key": "gq", "description": "ZWMCOMMONTANGENT", "label": "公切线"},
            "管道线": {"key": "gd", "description": "ZWMPIPELINE", "label": "管道线"},
            "垂分线": {"key": "cf", "description": "ZWMPERPBISECTOR", "label": "垂分线"},
            "角度线": {"key": "jd", "description": "ZWMANGLELINER", "label": "角度线"},
            "平分线": {"key": "pf", "description": "ZWMANGLEBISECTOR", "label": "平分线"},
            "放射线": {"key": "", "description": "ZWMRADIATION", "label": "放射线"},
            "中心线": {"key": "zx", "description": "ZWMCENTERLINE", "label": "中心线"},
            "截断线": {"key": "jdx", "description": "ZWMSECTIONSYMBOL", "label": "截断线"},
            "插入折断符": {"key": "zdf", "description": "ZWMBREAKSYMBOL1", "label": "插入折断符"},
            "打断": {"key": "dad", "description": "ZWMBREAKENTITY", "label": "打断"},
            "动态延伸": {"key": "ys", "description": "ZWMDYNAMICEXTEND", "label": "动态延伸"},
            "矩形": {"key": "jx", "description": "ZWMRECTANGLE", "label": "矩形"},
            "锯齿线": {"key": "bl", "description": "ZWMZIGZAGLINE", "label": "锯齿线"},
            "波浪线": {"key": "", "description": "ZWMWAVILNESSLINE", "label": "波浪线"},
        },
        # 五、符号标注
        "符号标注": {
            "粗糙度": {"key": "cc", "description": "ZWMSURFSYM", "label": "粗糙度"},
            "形位公差": {"key": "xw", "description": "ZWMFCFRAME", "label": "形位公差"},
            "基准标注": {"key": "jz", "description": "ZWMDATUMID", "label": "基准标注"},
            "形状识别": {"key": "", "description": "ZWMFEATID", "label": "形状识别"},
            "基准目标": {"key": "", "description": "ZWMDATUMTGT", "label": "基准目标"},
            "锥斜度": {"key": "xd", "description": "ZWMTAPERSYM", "label": "锥斜度"},
            "中心孔标注": {"key": "zxk", "description": "ZWMCENTERHOLE", "label": "中心孔标注"},
            "圆孔标记": {"key": "bj", "description": "ZWMCIRCLEMARK", "label": "圆孔标记"},
            "折断符号": {"key": "zd", "description": "ZWMBREAKSYMBOL", "label": "折断符号"},
            "标高符号": {"key": "bgf", "description": "ZWMELEVSYM", "label": "标高符号"},
            "焊接符号": {"key": "hj", "description": "ZWMWELDING", "label": "焊接符号"},
        },
        # 六、序号与明细表
        "序号与明细表": {
            "标注序号": {"key": "xh", "description": "ZWMBALLOON", "label": "标注序号"},
            "序号类型修改": {"key": "", "description": "ZWMEDITBALLOONSTYLE", "label": "序号类型修改"},
            "序号数据修改": {"key": "", "description": "ZWMEDITBOMROW", "label": "序号数据修改"},
            "序号对齐": {"key": "", "description": "ZWMALIGNBALLOON", "label": "序号对齐"},
            "序号顺号": {"key": "", "description": "ZWMRENUMBERBALLOON", "label": "序号顺号"},
            "序号隐藏": {"key": "", "description": "ZWMHIDEBALLOON", "label": "序号隐藏"},
            "序号显示": {"key": "", "description": "ZWMSHOWBALLOON", "label": "序号显示"},
            "合并序号": {"key": "", "description": "ZWMCOMBINEBALLOON", "label": "合并序号"},
            "序号加引线": {"key": "", "description": "ZWMADDLEADER", "label": "序号加引线"},
            "序号去引线": {"key": "", "description": "ZWMREMOVELEADER", "label": "序号去引线"},
            "生成明细表": {"key": "mx", "description": "ZWMPARTLIST", "label": "生成明细表"},
            "处理明细表": {"key": "mxb", "description": "ZWMTOTALBOMEDIT", "label": "处理明细表"},
            "明细表表格": {"key": "", "description": "ZWMBOMCARDEXP", "label": "明细表表格"},
        },
        # 七、图纸与图框管理
        "图纸与图框": {
            "图纸设置": {"key": "tf", "description": "ZWMFRAMEINIT", "label": "图纸设置"},
            "标题栏填充": {"key": "", "description": "ZWMTITLEEDIT", "label": "标题栏填充"},
            "附加栏填充": {"key": "", "description": "ZWMFJLEDIT", "label": "附加栏填充"},
            "参数栏填充": {"key": "", "description": "ZWMCSLEDIT", "label": "参数栏填充"},
            "多图幅设置": {"key": "tf2", "description": "ZWMFRAMEINIT2", "label": "多图幅设置"},
            "更换图框": {"key": "", "description": "ZWMSWITCHFRAME", "label": "更换图框"},
            "更换比例": {"key": "", "description": "ZWMSWITCHSCALE", "label": "更换比例"},
            "更换标题栏": {"key": "", "description": "ZWMSWITCHTITLE", "label": "更换标题栏"},
            "更换明细栏": {"key": "", "description": "ZWMSWITCHBOM", "label": "更换明细栏"},
            "更换代号栏": {"key": "", "description": "ZWMSWITCHDHL", "label": "更换代号栏"},
            "更换附加栏": {"key": "", "description": "ZWMSWITCHFJL", "label": "更换附加栏"},
            "更换参数栏": {"key": "", "description": "ZWMSWITCHCSL2", "label": "更换参数栏"},
            "增加更改栏": {"key": "", "description": "ZWMREVISIONLIST", "label": "增加更改栏"},
            "更换标准": {"key": "gh", "description": "ZWMSTDANDARDC", "label": "更换标准"},
        },
        # 八、机械设计工具
        "机械设计": {
            "轴设计": {"key": "", "description": "ZWMSHAFT", "label": "轴设计"},
            "齿轮设计": {"key": "", "description": "ZWMGEAR", "label": "齿轮设计"},
            "文字标注": {"key": "wz", "description": "ZWMDIMTEXT", "label": "文字标注"},
            "技术要求": {"key": "tj", "description": "ZWMTECHREQUEST", "label": "技术要求"},
            "DWG资料浏览": {"key": "", "description": "ZWMDWGDATAVIEW", "label": "DWG资料浏览"},
        },
        # 九、表格与数据提取
        "表格与数据": {
            "提取表格数据": {"key": "tb", "description": "ZWMTABLEDATAPICKUP", "label": "提取表格数据"},
            "批量资料提取": {"key": "", "description": "ZWMDWGDATAPICKUP", "label": "批量资料提取"},
            "批量脚本操作": {"key": "", "description": "ZWMDWGBATCHSCRIPT", "label": "批量脚本操作"},
            "自动排图": {"key": "zdpt", "description": "ZWMJIGSAWPRINT", "label": "自动排图"},
        },
        # 十、增强编辑工具
        "增强编辑": {
            "超级编辑": {"key": "v", "description": "ZWMSUPEREDIT", "label": "超级编辑"},
            "计算面积": {"key": "aa", "description": "ZWMAREA", "label": "计算面积"},
            "增强调用": {"key": "zd", "description": "ZWMPOWERRECALL", "label": "增强调用"},
            "增强删除": {"key": "ze", "description": "ZWMPOWERERASE", "label": "增强删除"},
        },
        # 十一、孔加工工具
        "孔加工": {
            "单孔": {"key": "dk", "description": "ZWMSINGLEHOLE", "label": "单孔"},
            "孔阵": {"key": "kz", "description": "ZWMARRAYHOLE", "label": "孔阵"},
            "孔轴投影": {"key": "", "description": "ZWMHSPROJECTOR", "label": "孔轴投影"},
        },
        # 十二、卡片与样式管理
        "卡片与样式": {
            "超级卡片": {"key": "mcc", "description": "ZWMCREATECARD", "label": "超级卡片"},
            "卡片编辑": {"key": "mce", "description": "ZWMCARDEDIT", "label": "卡片编辑"},
            "定义表格": {"key": "mta", "description": "ZWMMAKETBL", "label": "定义表格"},
            "定义卡片": {"key": "mca", "description": "ZWMMAKECARD", "label": "定义卡片"},
            "样式配置": {"key": "", "description": "ZWMSTYLEMANAGER", "label": "样式配置"},
            "词句库维护": {"key": "", "description": "ZWMWORDLIBMNG", "label": "词句库维护"},
            "自定义标题栏": {"key": "", "description": "ZWMTITLEDEFINE", "label": "自定义标题栏"},
            "自定义附加栏": {"key": "", "description": "ZWMFJLDEFINE", "label": "自定义附加栏"},
            "自定义参数栏": {"key": "", "description": "ZWMCSLDEFINE", "label": "自定义参数栏"},
            "自定义代号栏": {"key": "", "description": "ZWMREVERSEDEFINE", "label": "自定义代号栏"},
            "自定义明细表表头": {"key": "", "description": "ZWMBOMHEADDEFINE", "label": "自定义表头"},
            "自定义明细表表体": {"key": "", "description": "ZWMBOMBODYDEFINE", "label": "自定义表体"},
            "超级属性块": {"key": "", "description": "ZWMATTBLOCKDEF", "label": "超级属性块"},
            "样式同步配置": {"key": "", "description": "ZWMUPDATESET", "label": "样式同步配置"},
        },
        # 十三、超级符号库
        "超级符号库": {
            "超级符号库调用": {"key": "fh", "description": "ZWM_SYMOUT", "label": "超级符号库"},
            "层变换工具": {"key": "ty", "description": "ZWMCHGLAYER", "label": "层变换工具"},
        },
        # 十四、其他实用命令
        "其他实用": {
            "快速标直径": {"key": "zwm", "description": "ZWM_%%D", "label": "快速标直径"},
            "缩放区域": {"key": "", "description": "ZwmScArea", "label": "缩放区域"},
            "导入PDF": {"key": "pdfim", "description": "PDFIMPORT", "label": "导入PDF"},
            "工程计算器": {"key": "jsq", "description": "ZWMBASCALC", "label": "工程计算器"},
            "样式库同步": {"key": "", "description": "ZWMUPDATE", "label": "样式库同步"},
            "系列化零件设计": {"key": "xl", "description": "ZWM_SPART_OUT", "label": "系列化零件"},
            "大小写转换": {"key": "", "description": "ZWM_CASECHG", "label": "大小写转换"},
            "标总长": {"key": "bzc", "description": "ZWM_BZC", "label": "标总长"},
        },
    }

    # 基础命令 + 机械版专属命令（使用 copy + update 合并，避免修改原字典）
    zwcad_commands = copy.deepcopy(base_commands)
    for category, cmds in zw_mech_commands.items():
        zwcad_commands[category] = cmds

    return zwcad_commands


def _default_config() -> Dict[str, Any]:
    """默认配置 — AutoCAD 和中望CAD 分开，含双层圆盘"""
    return {
        "settings": {
            "version": 1,
            "hold_threshold_ms": 80,
            "trigger_distance": 10,
            "dead_zone_radius": 24,
            "ring_radius": 70,
            "outer_ring_radius": 135,
            "ext_ring_radius": 185,
            "menu_scale": 100,
            "sector_count": 8,
            "menu_opacity": 0.95,
            "active_profile": "AutoCAD-常用",
            "autocad_profile": "AutoCAD-常用",
            "zwcad_profile": "ZWCAD-常用",
            "auto_start": False,
            "auto_switch_profile": True,
            "open_config_on_start": False,
            "menu_theme": "azure",
            "check_update_on_start": True,
            "update_source_url": "https://github.com/Inonvation/cad-gesture/releases/latest",
            "last_update_check": "",
            "language": "zh",
            "ui_mode": "dark",
            "trigger_button": "right",
            "gesture_trail": True,
            "menu_clamp_to_screen": True,
            "menu_font_scale": 100,
            "ui_font_scale": 100,
            "custom_text": "#e9edf2",
            "custom_highlight": "#6fa3d8",
            "custom_bg": "#1a202b",
            "custom_hover": "#2a3a4d",
            "command_feedback": True,
            "feedback_position": "bottom_center",
            "feedback_show_name": True,
            "feedback_show_key": True,
            "feedback_duration_ms": 1500,
            "feedback_offset_x": 0,
            "feedback_offset_y": 0
        },
        "profiles": {
            "AutoCAD-常用": {
                "name": "常用",
                "target": "autocad",
                "sectors": {
                    "0": {"label": "直线", "key": "l", "description": "LINE"},
                    "1": {"label": "偏移", "key": "o", "description": "OFFSET"},
                    "2": {"label": "复制", "key": "co", "description": "COPY"},
                    "3": {"label": "镜像", "key": "mi", "description": "MIRROR"},
                    "4": {"label": "删除", "key": "e", "description": "ERASE"},
                    "5": {"label": "修剪", "key": "tr", "description": "TRIM"},
                    "6": {"label": "移动", "key": "m", "description": "MOVE"},
                    "7": {"label": "圆", "key": "c", "description": "CIRCLE"}
                },
                "outer_sectors": {
                    "0": {"label": "圆弧", "key": "a", "description": "ARC"},
                    "1": {"label": "矩形", "key": "rec", "description": "RECTANG"},
                    "2": {"label": "延伸", "key": "ex", "description": "EXTEND"},
                    "3": {"label": "旋转", "key": "ro", "description": "ROTATE"},
                    "4": {"label": "缩放", "key": "sc", "description": "SCALE"},
                    "5": {"label": "圆角", "key": "f", "description": "FILLET"},
                    "6": {"label": "分解", "key": "x", "description": "EXPLODE"},
                    "7": {"label": "多段线", "key": "pl", "description": "PLINE"}
                },
                "extension_sectors": {
                    "0": {"label": "构造线", "key": "xl", "description": "XLINE"},
                    "1": {"label": "射线", "key": "ray", "description": "RAY"},
                    "2": {"label": "边界", "key": "bo", "description": "BOUNDARY"},
                    "3": {"label": "面域", "key": "reg", "description": "REGION"},
                    "4": {"label": "正交", "key": "f8", "description": "ORTHO"},
                    "5": {"label": "极轴", "key": "f10", "description": "POLAR"},
                    "6": {"label": "对象捕捉", "key": "f3", "description": "OSNAP"},
                    "7": {"label": "栅格", "key": "f7", "description": "GRID"}
                }
            },
            "AutoCAD-绘图": {
                "name": "绘图",
                "target": "autocad",
                "sectors": {
                    "0": {"label": "直线", "key": "l", "description": "LINE"},
                    "1": {"label": "圆", "key": "c", "description": "CIRCLE"},
                    "2": {"label": "矩形", "key": "rec", "description": "RECTANG"},
                    "3": {"label": "圆弧", "key": "a", "description": "ARC"},
                    "4": {"label": "多段线", "key": "pl", "description": "PLINE"},
                    "5": {"label": "样条", "key": "spl", "description": "SPLINE"},
                    "6": {"label": "椭圆", "key": "el", "description": "ELLIPSE"},
                    "7": {"label": "填充", "key": "h", "description": "BHATCH"}
                },
                "outer_sectors": {
                    "0": {"label": "构造线", "key": "xl", "description": "XLINE"},
                    "1": {"label": "块", "key": "b", "description": "BLOCK"},
                    "2": {"label": "插入块", "key": "i", "description": "INSERT"},
                    "3": {"label": "正多边形", "key": "pol", "description": "POLYGON"},
                    "4": {"label": "圆环", "key": "do", "description": "DONUT"},
                    "5": {"label": "多线", "key": "ml", "description": "MLINE"},
                    "6": {"label": "点", "key": "po", "description": "POINT"},
                    "7": {"label": "表格", "key": "tb", "description": "TABLE"}
                },
                "extension_sectors": {
                    "0": {"label": "点", "key": "po", "description": "POINT"},
                    "1": {"label": "圆环", "key": "do", "description": "DONUT"},
                    "2": {"label": "正多边形", "key": "pol", "description": "POLYGON"},
                    "3": {"label": "构造线", "key": "xl", "description": "XLINE"},
                    "4": {"label": "射线", "key": "ray", "description": "RAY"},
                    "5": {"label": "多线", "key": "ml", "description": "MLINE"},
                    "6": {"label": "边界", "key": "bo", "description": "BOUNDARY"},
                    "7": {"label": "面域", "key": "reg", "description": "REGION"}
                }
            },
            "AutoCAD-标注": {
                "name": "标注",
                "target": "autocad",
                "sectors": {
                    "0": {"label": "标注样式", "key": "d", "description": "DDIM"},
                    "1": {"label": "线性标注", "key": "dli", "description": "DIMLINEAR"},
                    "2": {"label": "对齐标注", "key": "dal", "description": "DIMALIGNED"},
                    "3": {"label": "半径标注", "key": "dra", "description": "DIMRADIUS"},
                    "4": {"label": "直径标注", "key": "ddi", "description": "DIMDIAMETER"},
                    "5": {"label": "角度标注", "key": "dan", "description": "DIMANGULAR"},
                    "6": {"label": "连续标注", "key": "dco", "description": "DIMCONTINUE"},
                    "7": {"label": "基线标注", "key": "dba", "description": "DIMBASELINE"}
                },
                "outer_sectors": {
                    "0": {"label": "快速引线", "key": "le", "description": "QLEADER"},
                    "1": {"label": "圆心标记", "key": "dce", "description": "DIMCENTER"},
                    "2": {"label": "坐标标注", "key": "dor", "description": "DIMORDINATE"},
                    "3": {"label": "编辑标注", "key": "ded", "description": "DIMEDIT"},
                    "4": {"label": "特性匹配", "key": "ma", "description": "MATCHPROP"},
                    "5": {"label": "特性", "key": "pr", "description": "PROPERTIES"},
                    "6": {"label": "文字编辑", "key": "ed", "description": "TEXTEDIT"},
                    "7": {"label": "图层", "key": "la", "description": "LAYER"}
                },
                "extension_sectors": {
                    "0": {"label": "快速引线", "key": "le", "description": "QLEADER"},
                    "1": {"label": "圆心标记", "key": "dce", "description": "DIMCENTER"},
                    "2": {"label": "坐标标注", "key": "dor", "description": "DIMORDINATE"},
                    "3": {"label": "编辑标注", "key": "ded", "description": "DIMEDIT"},
                    "4": {"label": "文字样式", "key": "st", "description": "STYLE"},
                    "5": {"label": "图层", "key": "la", "description": "LAYER"},
                    "6": {"label": "文字编辑", "key": "ed", "description": "TEXTEDIT"},
                    "7": {"label": "选项", "key": "op", "description": "OPTIONS"}
                }
            },
            "AutoCAD-视图": {
                "name": "视图",
                "target": "autocad",
                "sectors": {
                    "0": {"label": "缩放", "key": "z", "description": "ZOOM"},
                    "1": {"label": "平移", "key": "p", "description": "PAN"},
                    "2": {"label": "正交", "key": "f8", "description": "ORTHO"},
                    "3": {"label": "对象捕捉", "key": "f3", "description": "OSNAP"},
                    "4": {"label": "栅格", "key": "f7", "description": "GRID"},
                    "5": {"label": "极轴", "key": "f10", "description": "POLAR"},
                    "6": {"label": "距离测量", "key": "di", "description": "DIST"},
                    "7": {"label": "重生成", "key": "re", "description": "REGEN"}
                },
                "outer_sectors": {
                    "0": {"label": "列表", "key": "li", "description": "LIST"},
                    "1": {"label": "单位", "key": "un", "description": "UNITS"},
                    "2": {"label": "选项", "key": "op", "description": "OPTIONS"},
                    "3": {"label": "草图设置", "key": "ds", "description": "DSETTINGS"},
                    "4": {"label": "清理", "key": "pu", "description": "PURGE"},
                    "5": {"label": "重命名", "key": "ren", "description": "RENAME"},
                    "6": {"label": "进入视口", "key": "ms", "description": "MSPACE"},
                    "7": {"label": "退出视口", "key": "ps", "description": "PSPACE"}
                },
                "extension_sectors": {
                    "0": {"label": "视图", "key": "v", "description": "VIEW"},
                    "1": {"label": "视觉样式", "key": "vscurrent", "description": "VSCURRENT"},
                    "2": {"label": "UCS", "key": "ucs", "description": "UCS"},
                    "3": {"label": "计划视图", "key": "plan", "description": "PLAN"},
                    "4": {"label": "全屏显示", "key": "ctrl+0", "description": "CLEANSCREENON"},
                    "5": {"label": "前一个视图", "key": "", "description": ""},
                    "6": {"label": "实时平移", "key": "p", "description": "PAN"},
                    "7": {"label": "实时缩放", "key": "z", "description": "ZOOM"}
                }
            },
            "ZWCAD-成图大赛": {
                "name": "成图大赛推荐",
                "target": "zwcad",
                "sectors": {
                    "0": {"label": "基准", "key": "jz", "description": "ZWMDATUMID"},
                    "1": {"label": "形位公差", "key": "xw", "description": "ZWMFCFRAME"},
                    "2": {"label": "圆", "key": "c", "description": "CIRCLE"},
                    "3": {"label": "粗糙度", "key": "cc", "description": "ZWMSURFSYM"},
                    "4": {"label": "标注", "key": "dli", "description": "DIMLINEAR"},
                    "5": {"label": "中心线", "key": "zx", "description": "ZWMCENTERLINE"},
                    "6": {"label": "直线", "key": "l", "description": "LINE"},
                    "7": {"label": "裁剪", "key": "tr", "description": "TRIM"}
                },
                "outer_sectors": {
                    "0": {"label": "技术要求", "key": "tj", "description": "ZWMTECHREQUEST"},
                    "1": {"label": "局部详图", "key": "ZWMDETAIL", "description": "ZWMDETAIL"},
                    "2": {"label": "区域缩放", "key": "z", "description": "ZOOM"},
                    "3": {"label": "一键标注φ", "key": "ddi", "description": "DIMDIAMETER"},
                    "4": {"label": "方向符号", "key": "ZWMVIEWDIRECTION", "description": "ZWMVIEWDIRECTION"},
                    "5": {"label": "剖面线", "key": "h", "description": "BHATCH"},
                    "6": {"label": "图幅", "key": "tf", "description": "ZWMFRAMEINIT"},
                    "7": {"label": "剖切线", "key": "pq", "description": "ZWMSECTIONLINE"}
                },
                "extension_sectors": {}
            },
            "ZWCAD-常用": {
                "name": "常用",
                "target": "zwcad",
                "sectors": {
                    "0": {"label": "直线", "key": "l", "description": "LINE"},
                    "1": {"label": "偏移", "key": "o", "description": "OFFSET"},
                    "2": {"label": "复制", "key": "co", "description": "COPY"},
                    "3": {"label": "镜像", "key": "mi", "description": "MIRROR"},
                    "4": {"label": "删除", "key": "e", "description": "ERASE"},
                    "5": {"label": "修剪", "key": "tr", "description": "TRIM"},
                    "6": {"label": "移动", "key": "m", "description": "MOVE"},
                    "7": {"label": "圆", "key": "c", "description": "CIRCLE"}
                },
                "outer_sectors": {
                    "0": {"label": "圆弧", "key": "a", "description": "ARC"},
                    "1": {"label": "矩形", "key": "rec", "description": "RECTANG"},
                    "2": {"label": "延伸", "key": "ex", "description": "EXTEND"},
                    "3": {"label": "旋转", "key": "ro", "description": "ROTATE"},
                    "4": {"label": "缩放", "key": "sc", "description": "SCALE"},
                    "5": {"label": "圆角", "key": "f", "description": "FILLET"},
                    "6": {"label": "分解", "key": "x", "description": "EXPLODE"},
                    "7": {"label": "多段线", "key": "pl", "description": "PLINE"}
                },
                "extension_sectors": {
                    "0": {"label": "智能画线", "key": "ss", "description": "ZWMINTELLIGENTLINE"},
                    "1": {"label": "对称画线", "key": "dc", "description": "ZWMMIRRORLINE"},
                    "2": {"label": "中心线", "key": "zx", "description": "ZWMCENTERLINE"},
                    "3": {"label": "垂线", "key": "cz", "description": "ZWMVERTICALLINE"},
                    "4": {"label": "切线", "key": "qx", "description": "ZWMTANGENTLINE"},
                    "5": {"label": "管道线", "key": "gd", "description": "ZWMPIPELINE"},
                    "6": {"label": "构造线", "key": "xl", "description": "XLINE"},
                    "7": {"label": "表格", "key": "tb", "description": "TABLE"}
                }
            },
            "ZWCAD-绘图": {
                "name": "绘图",
                "target": "zwcad",
                "sectors": {
                    "0": {"label": "直线", "key": "l", "description": "LINE"},
                    "1": {"label": "圆", "key": "c", "description": "CIRCLE"},
                    "2": {"label": "矩形", "key": "rec", "description": "RECTANG"},
                    "3": {"label": "圆弧", "key": "a", "description": "ARC"},
                    "4": {"label": "多段线", "key": "pl", "description": "PLINE"},
                    "5": {"label": "样条", "key": "spl", "description": "SPLINE"},
                    "6": {"label": "椭圆", "key": "el", "description": "ELLIPSE"},
                    "7": {"label": "填充", "key": "h", "description": "BHATCH"}
                },
                "outer_sectors": {
                    "0": {"label": "智能画线", "key": "ss", "description": "ZWMINTELLIGENTLINE"},
                    "1": {"label": "对称画线", "key": "dc", "description": "ZWMMIRRORLINE"},
                    "2": {"label": "中心线", "key": "zx", "description": "ZWMCENTERLINE"},
                    "3": {"label": "构造线", "key": "xl", "description": "XLINE"},
                    "4": {"label": "块", "key": "b", "description": "BLOCK"},
                    "5": {"label": "插入块", "key": "i", "description": "INSERT"},
                    "6": {"label": "正多边形", "key": "pol", "description": "POLYGON"},
                    "7": {"label": "表格", "key": "tb", "description": "TABLE"}
                },
                "extension_sectors": {
                    "0": {"label": "智能画线", "key": "ss", "description": "ZWMINTELLIGENTLINE"},
                    "1": {"label": "对称画线", "key": "dc", "description": "ZWMMIRRORLINE"},
                    "2": {"label": "中心线", "key": "zx", "description": "ZWMCENTERLINE"},
                    "3": {"label": "并行线", "key": "px", "description": "ZWMPARALLELLINE"},
                    "4": {"label": "垂线", "key": "cz", "description": "ZWMVERTICALLINE"},
                    "5": {"label": "切线", "key": "qx", "description": "ZWMTANGENTLINE"},
                    "6": {"label": "管道线", "key": "gd", "description": "ZWMPIPELINE"},
                    "7": {"label": "构造线", "key": "xl", "description": "XLINE"}
                }
            },
            "ZWCAD-机械": {
                "name": "机械",
                "target": "zwcad",
                "sectors": {
                    "0": {"label": "智能标注", "key": "d", "description": "ZWMPOWERDIM"},
                    "1": {"label": "粗糙度", "key": "cc", "description": "ZWMSURFSYM"},
                    "2": {"label": "形位公差", "key": "xw", "description": "ZWMFCFRAME"},
                    "3": {"label": "基准标注", "key": "jz", "description": "ZWMDATUMID"},
                    "4": {"label": "序号", "key": "xh", "description": "ZWMBALLOON"},
                    "5": {"label": "明细表", "key": "mx", "description": "ZWMPARTLIST"},
                    "6": {"label": "图框设置", "key": "tf", "description": "ZWMFRAMEINIT"},
                    "7": {"label": "技术要求", "key": "tj", "description": "ZWMTECHREQUEST"}
                },
                "outer_sectors": {
                    "0": {"label": "焊接符号", "key": "hj", "description": "ZWMWELDING"},
                    "1": {"label": "锥斜度", "key": "xd", "description": "ZWMtapersym"},
                    "2": {"label": "文字标注", "key": "wz", "description": "ZWMDIMTEXT"},
                    "3": {"label": "超级符号", "key": "fh", "description": "ZWM_SYMOUT"},
                    "4": {"label": "计算面积", "key": "aa", "description": "ZWMAREA"},
                    "5": {"label": "超级编辑", "key": "v", "description": "ZWMSUPEREDIT"},
                    "6": {"label": "层变换", "key": "ty", "description": "ZWMCHGLAYER"},
                    "7": {"label": "标高符号", "key": "bgf", "description": "ZWMELEVSYM"}
                },
                "extension_sectors": {
                    "0": {"label": "焊接符号", "key": "hj", "description": "ZWMWELDING"},
                    "1": {"label": "锥斜度", "key": "xd", "description": "ZWMtapersym"},
                    "2": {"label": "标高符号", "key": "bgf", "description": "ZWMELEVSYM"},
                    "3": {"label": "圆孔标记", "key": "bj", "description": "ZWMCRCLMARK"},
                    "4": {"label": "中心孔标注", "key": "zxk", "description": "ZWMCENTERHOLE"},
                    "5": {"label": "折断符号", "key": "zd", "description": "ZWMBREAKSYMBOL"},
                    "6": {"label": "截断线", "key": "jdx", "description": "ZWMSECTIONSYMBOL"},
                    "7": {"label": "图框设置", "key": "tf", "description": "ZWMFRAMEINIT"}
                }
            }
        }
    }
