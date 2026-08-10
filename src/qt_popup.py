"""扇区编辑浮层控制器 — 定位与信号接线

浮层窗口自身（SectorEditorPopup）在 qt_sector_editor.py；本模块的
PopupController 负责浮层打开/定位，place_under 提供可独立测试的
定位算法。扇区数据的读写仍由 qt_config_gui 完成。
"""

from PySide6.QtCore import QPoint

from src.qt_sector_editor import SectorEditorPopup


def place_under(anchor_center: QPoint, disc_r: float, popup_w: int,
                popup_h: int, screen_geo, gap: int = 12) -> QPoint:
    """把浮层放在锚点（圆盘中心）正下方；下方放不下改放上方，再兜底贴边。

    screen_geo 为屏幕可用区域 QRect。返回浮层窗口全局位置 (x, y)。
    """
    x = anchor_center.x() - popup_w // 2
    y = anchor_center.y() + int(disc_r) + gap
    if y + popup_h > screen_geo.bottom() - 8:
        y = anchor_center.y() - int(disc_r) - gap - popup_h
    x = max(screen_geo.left() + 8, min(x, screen_geo.right() - popup_w - 8))
    y = max(screen_geo.top() + 8, min(y, screen_geo.bottom() - popup_h - 8))
    if y + popup_h > screen_geo.bottom() - 8:
        y = screen_geo.bottom() - popup_h - 8
    return QPoint(x, y)


class PopupController:
    """浮层生命周期：信号接线 + 打开/定位。数据写回由主窗口完成。"""

    def __init__(self, popup: SectorEditorPopup, on_save, on_clear, on_closed,
                 on_blank_clicked, on_esc, on_reposition):
        self.popup = popup
        popup.save_requested.connect(on_save)
        popup.cleared.connect(on_clear)
        popup.closed.connect(on_closed)
        popup.blank_clicked.connect(on_blank_clicked)
        popup.esc_requested.connect(on_esc)
        popup.reposition_requested.connect(on_reposition)

    def fill(self, layer: str, idx: int, cfg: dict, n: int) -> None:
        """填充扇区数据（浮层尚未显示，由调用方决定定位）"""
        self.popup.show_sector(layer, idx, cfg, n)

    def show(self) -> None:
        self.popup.show()
        self.popup.raise_()

    def place(self, anchor_center: QPoint, disc_r: float) -> None:
        """定位到锚点（圆盘中心）下方；用户拖动过浮层则保持其位置"""
        if self.popup.user_moved:
            return
        self.popup.adjustSize()
        geo = self.popup.screen().availableGeometry()
        self.popup.move(place_under(anchor_center, disc_r,
                                    self.popup.width(), self.popup.height(), geo))
