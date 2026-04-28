import sys
import os
import logging
import warnings

# 过滤警告和日志
warnings.filterwarnings("ignore")

logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

from core.config_manager import ConfigManager
from core.logging import emit_event, get_logger, init_logging, install_crash_handlers

def main():
    cfg = ConfigManager().config
    init_logging(config=cfg)
    logger = get_logger("app")
    install_crash_handlers(log_dir=str(cfg.get("log_dir", "data/logs")))
    emit_event(
        logger=logger,
        level="INFO",
        module="app",
        event="APP_START",
        msg_zh="正在启动 CosyVoice Desktop",
        fields={"version": "1.4"},
    )
    
    if hasattr(Qt, 'HighDpiScaleFactorRoundingPolicy'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    app = QApplication(sys.argv)
    app.setApplicationName("CosyVoice Desktop")
    app.setApplicationVersion("1.0")
    
    icon_path = "./icon.ico"
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    logger.info("[INFO] QApplication 已初始化，正在加载 UI 组件...")

    try:
        from qfluentwidgets import setTheme, Theme
        from ui.main_window import CosyVoiceProApp
        
        setTheme(Theme.AUTO)
        
        window = CosyVoiceProApp()
        window.show()
        emit_event(
            logger=logger,
            level="INFO",
            module="app",
            event="APP_READY",
            msg_zh="主窗口已显示，进入事件循环",
            fields={"window": "CosyVoiceProApp"},
        )
        code = app.exec_()
        emit_event(
            logger=logger,
            level="INFO",
            module="app",
            event="APP_SHUTDOWN",
            msg_zh="应用退出",
            fields={},
        )
        sys.exit(code)
        
    except Exception as e:
        emit_event(
            logger=logger,
            level="ERROR",
            module="app",
            event="CRH_UNCAUGHT",
            msg_zh="启动过程中发生错误",
            fields={"error_type": type(e).__name__, "message": str(e)},
        )
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
