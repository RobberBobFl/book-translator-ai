import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("book-translator v0.1.0 — структура проекта инициализирована")
    logger.info("Модули: core, parsers, translator, state, exporters, gui, utils")
    logger.info("Все библиотеки установлены, проект готов к разработке")


if __name__ == "__main__":
    main()
