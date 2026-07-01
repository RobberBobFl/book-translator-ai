import sys
import asyncio
import logging

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from gui.main_window import MainWindow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Book Translator")

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
