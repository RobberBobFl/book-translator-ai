"""UI internationalisation (RU / EN) with system-locale auto-detection.

Usage::

    from gui import i18n
    i18n.set_language("auto")          # resolve via system locale
    label.setText(i18n.tr("tab.book"))  # static string
    log(i18n.tr("tp.started", pages=10, mode="auto"))  # templated string

The active language is stored in the app config under ``ui_language`` and can
take one of three values: ``"auto"``, ``"ru"`` or ``"en"``.
"""

from __future__ import annotations

from PyQt6.QtCore import QLocale

# ---------------------------------------------------------------------------
# Constants & labels
# ---------------------------------------------------------------------------

LANG_AUTO = "auto"
LANG_RU = "ru"
LANG_EN = "en"

THEME_AUTO = "auto"
THEME_LIGHT = "light"
THEME_DARK = "dark"

_LANG_LABELS: dict[str, str] = {
    LANG_AUTO: "🌐 Авто",
    LANG_RU: "Русский",
    LANG_EN: "English",
}

LANGUAGE_LABELS: list[str] = [
    _LANG_LABELS[LANG_AUTO],
    _LANG_LABELS[LANG_RU],
    _LANG_LABELS[LANG_EN],
]

_CURRENT = LANG_RU


# ---------------------------------------------------------------------------
# String table
# ---------------------------------------------------------------------------

STRINGS: dict[str, dict[str, str]] = {
    # --- App / About ---
    "app.about_title": {
        "ru": "Book Translator AI",
        "en": "Book Translator AI",
    },
    "app.about_text": {
        "ru": "Пакетный переводчик TXT-книг через LLM API.\n\n"
              "Версия 0.1.0\n"
              "https://github.com/RobberBobFl/book-translator-ai",
        "en": "Batch translator for TXT books via LLM APIs.\n\n"
              "Version 0.1.0\n"
              "https://github.com/RobberBobFl/book-translator-ai",
    },

    # --- Menu ---
    "menu.file": {"ru": "&Файл", "en": "&File"},
    "menu.open": {"ru": "&Открыть книгу...", "en": "&Open Book..."},
    "menu.quit": {"ru": "&Выход", "en": "&Quit"},
    "menu.help": {"ru": "&Справка", "en": "&Help"},
    "menu.about": {"ru": "&О программе", "en": "&About"},

    # --- Status bar ---
    "status.ready": {"ru": "Готов", "en": "Ready"},
    "status.loaded": {
        "ru": "Загружено: {title}  |  {chapters} глав, {pages} страниц",
        "en": "Loaded: {title}  |  {chapters} chapters, {pages} pages",
    },
    "status.translation_finished": {
        "ru": "Перевод завершён",
        "en": "Translation finished",
    },
    "status.session_reset": {
        "ru": "Сессия сброшена, загрузите книгу заново",
        "en": "Session reset, load the book again",
    },

    # --- Dialogs ---
    "dlg.file_not_found.title": {"ru": "Файл не найден", "en": "File not found"},
    "dlg.file_not_found.text": {
        "ru": "Файл книги не найден:\n{path}\n\n"
              "Невозможно продолжить перевод. Сессия будет очищена.",
        "en": "Book file not found:\n{path}\n\n"
              "Cannot continue translation. The session will be cleared.",
    },
    "dlg.file_changed.title": {"ru": "Файл изменился", "en": "File changed"},
    "dlg.file_changed.text": {
        "ru": "Файл книги изменился с момента последнего перевода.",
        "en": "The book file has changed since the last translation.",
    },
    "dlg.file_changed.info": {
        "ru": "Книга: {title}\nПрогресс: {idx}/{total}\n\n"
              "Начать перевод заново или продолжить текущий "
              "(рискованно — нумерация страниц могла измениться)?",
        "en": "Book: {title}\nProgress: {idx}/{total}\n\n"
              "Restart the translation or continue the current one "
              "(risky — page numbering may have changed)?",
    },
    "dlg.resume.title": {"ru": "Восстановить сессию?", "en": "Resume session?"},
    "dlg.resume.text": {
        "ru": "Обнаружен незавершённый перевод книги «{title}».",
        "en": "An unfinished translation of “{title}” was found.",
    },
    "dlg.resume.info": {
        "ru": "Переведено {idx} из {total} страниц.\n\nПродолжить?",
        "en": "Translated {idx} of {total} pages.\n\nContinue?",
    },
    "btn.restart": {"ru": "Начать заново", "en": "Restart"},
    "btn.continue": {"ru": "Продолжить", "en": "Continue"},
    "btn.cancel": {"ru": "Отмена", "en": "Cancel"},

    # --- Tabs ---
    "tab.book": {"ru": "📖 Книга", "en": "📖 Book"},
    "tab.translate": {"ru": "🌐 Перевод", "en": "🌐 Translate"},
    "tab.settings": {"ru": "⚙ Настройки", "en": "⚙ Settings"},

    # --- Top bar ---
    "topbar.language_tooltip": {
        "ru": "Язык интерфейса",
        "en": "Interface language",
    },
    "topbar.theme_tooltip": {
        "ru": "Тема оформления",
        "en": "Color theme",
    },

    # --- Book loader ---
    "bl.drop_hint": {
        "ru": "📂  Перетащите файл книги сюда\n"
              "или воспользуйтесь кнопкой «Открыть файл»",
        "en": "📂  Drop a book file here\nor use the “Open file” button",
    },
    "bl.open_file": {"ru": "📂  Открыть файл...", "en": "📂  Open file..."},
    "bl.title": {"ru": "Название:", "en": "Title:"},
    "bl.chapters": {"ru": "Глав:", "en": "Chapters:"},
    "bl.pages": {"ru": "Страниц:", "en": "Pages:"},
    "bl.chars": {"ru": "Всего символов:", "en": "Total characters:"},
    "bl.format": {"ru": "Формат:", "en": "Format:"},
    "bl.legacy_warning": {
        "ru": "⚠️  Книга загружена в старой версии — страницы отсутствуют.\n"
              "Перезагрузите файл для работы с новой версией.",
        "en": "⚠️  The book was loaded in an older version — pages are missing.\n"
              "Reload the file to use the new version.",
    },
    "bl.loaded": {
        "ru": "✅  Загружено: {title}\n{chapters} глав, {pages} страниц",
        "en": "✅  Loaded: {title}\n{chapters} chapters, {pages} pages",
    },
    "bl.filter": {
        "ru": "Текст (*.txt);;Все файлы (*)",
        "en": "Text (*.txt);;All files (*)",
    },
    "bl.unsupported.title": {
        "ru": "Неподдерживаемый формат",
        "en": "Unsupported format",
    },
    "bl.unsupported.text": {
        "ru": "Файлы .{ext} не поддерживаются.\nДоступные форматы: {formats}",
        "en": "Files .{ext} are not supported.\nSupported formats: {formats}",
    },
    "bl.file_changed.title": {"ru": "Файл изменился", "en": "File changed"},
    "bl.file_changed.text": {
        "ru": "Этот файл уже загружался, но его содержимое изменилось.\n"
              "Начать заново?",
        "en": "This file was loaded before but its contents have changed.\n"
              "Start over?",
    },
    "bl.parse_error.title": {"ru": "Ошибка парсинга", "en": "Parsing error"},
    "bl.parse_error.text": {
        "ru": "Не удалось прочитать файл:\n{exc}",
        "en": "Could not read the file:\n{exc}",
    },
    "bl.empty_book.title": {"ru": "Пустая книга", "en": "Empty book"},
    "bl.empty_book.text": {
        "ru": "Файл не содержит текста для перевода.\n"
              "Проверьте содержимое файла.",
        "en": "The file contains no text to translate.\n"
              "Check the file contents.",
    },
    "bl.db_error.title": {"ru": "Ошибка БД", "en": "Database error"},
    "bl.db_error.text": {
        "ru": "Не удалось сохранить книгу в базу:\n{exc}",
        "en": "Could not save the book to the database:\n{exc}",
    },

    # --- Translation panel ---
    "tp.mode": {"ru": "Режим:", "en": "Mode:"},
    "tp.model": {"ru": "Модель: {model}", "en": "Model: {model}"},
    "tp.language": {"ru": "Язык:", "en": "Language:"},
    "tp.language_tooltip": {
        "ru": "Язык, на который выполняется перевод",
        "en": "Target language of the translation",
    },
    "tp.start": {"ru": "▶ Начать", "en": "▶ Start"},
    "tp.pause": {"ru": "⏸ Пауза", "en": "⏸ Pause"},
    "tp.resume": {"ru": "▶ Продолжить", "en": "▶ Resume"},
    "tp.stop": {"ru": "⏹ Стоп", "en": "⏹ Stop"},
    "tp.export": {"ru": "💾 Сохранить как MD", "en": "💾 Save as MD"},
    "tp.progress": {"ru": "Страниц: %v / %m", "en": "Pages: %v / %m"},
    "tp.log_label": {"ru": "Лог перевода:", "en": "Translation log:"},
    "tp.problem_pages": {
        "ru": "Проблемные страницы:",
        "en": "Problem pages:",
    },
    "tp.export_title": {
        "ru": "Сохранить перевод как Markdown",
        "en": "Save translation as Markdown",
    },
    "tp.export_filter": {
        "ru": "Markdown files (*.md);;All files (*)",
        "en": "Markdown files (*.md);;All files (*)",
    },
    "tp.export_no_active": {
        "ru": "Нет активного перевода для экспорта.",
        "en": "No active translation to export.",
    },
    "tp.not_complete.title": {
        "ru": "Перевод не завершён",
        "en": "Translation not complete",
    },
    "tp.not_complete.text": {
        "ru": "Перевод ещё не завершён. Экспортировать как есть?",
        "en": "The translation is not finished yet. Export anyway?",
    },
    "tp.export_done": {
        "ru": "Перевод сохранён:\n{result}",
        "en": "Translation saved:\n{result}",
    },
    "tp.export_error.title": {"ru": "Ошибка экспорта", "en": "Export error"},
    "tp.export_error.text": {
        "ru": "Не удалось сохранить файл:\n{exc}",
        "en": "Could not save the file:\n{exc}",
    },
    "tp.no_pages.title": {"ru": "Нет страниц", "en": "No pages"},
    "tp.no_pages.text": {
        "ru": "В книге нет страниц для перевода.\n"
              "Возможно, файл пуст или повреждён.",
        "en": "The book has no pages to translate.\n"
              "The file may be empty or corrupted.",
    },
    "tp.err_book_not_selected": {
        "ru": "Ошибка: книга не выбрана",
        "en": "Error: no book selected",
    },
    "tp.err_book_not_found": {
        "ru": "Ошибка: книга не найдена",
        "en": "Error: book not found",
    },
    "tp.err_model_not_selected": {
        "ru": "Ошибка: модель не выбрана",
        "en": "Error: no model selected",
    },
    "tp.err_no_pages": {
        "ru": "Ошибка: книга не содержит страниц для перевода",
        "en": "Error: the book contains no pages to translate",
    },
    "tp.started": {
        "ru": "Запущен перевод: {pages} страниц, режим: {mode}",
        "en": "Translation started: {pages} pages, mode: {mode}",
    },
    "tp.model_log": {"ru": " Модель: {model}", "en": " Model: {model}"},
    "tp.paused": {"ru": "Перевод приостановлен", "en": "Translation paused"},
    "tp.resumed": {"ru": "Перевод продолжен", "en": "Translation resumed"},
    "tp.stopped": {
        "ru": "Перевод остановлен пользователем",
        "en": "Translation stopped by user",
    },
    "tp.finished": {"ru": "Перевод завершён", "en": "Translation finished"},
    "tp.progress_saved": {"ru": "Прогресс сохранён", "en": "Progress saved"},
    "tp.save_error": {
        "ru": "Ошибка сохранения: {exc}",
        "en": "Save error: {exc}",
    },
    "tp.critical": {
        "ru": "Перевод остановлен:\n{message}",
        "en": "Translation stopped:\n{message}",
    },
    "tp.critical_title": {"ru": "Критическая ошибка", "en": "Critical error"},
    "tp.page_failed": {
        "ru": "Ошибка страницы #{idx}: {error}",
        "en": "Page #{idx} error: {error}",
    },
    "tp.resume_session": {
        "ru": "Сессия восстановлена (книга #{book_id}, шаг {current_index})",
        "en": "Session restored (book #{book_id}, step {current_index})",
    },

    # --- Settings panel ---
    "sp.providers": {"ru": "Поставщики API", "en": "API providers"},
    "sp.add": {"ru": "➕ Добавить", "en": "➕ Add"},
    "sp.edit": {"ru": "✏️ Редактировать", "en": "✏️ Edit"},
    "sp.delete": {"ru": "🗑️ Удалить", "en": "🗑️ Delete"},
    "sp.model": {"ru": "Модель для перевода", "en": "Translation model"},
    "sp.model_label": {"ru": "Model:", "en": "Model:"},
    "sp.params": {"ru": "Параметры перевода", "en": "Translation parameters"},
    "sp.temperature": {"ru": "Temperature:", "en": "Temperature:"},
    "sp.top_p": {"ru": "Top-p:", "en": "Top-p:"},
    "sp.max_tokens": {"ru": "Max tokens:", "en": "Max tokens:"},
    "sp.style": {"ru": "Стиль:", "en": "Style:"},
    "sp.provider_title": {"ru": "Провайдер", "en": "Provider"},
    "sp.provider_edit_title": {
        "ru": "Редактировать провайдера",
        "en": "Edit provider",
    },
    "sp.name": {"ru": "Название:", "en": "Name:"},
    "sp.base_url": {"ru": "API Base URL:", "en": "API Base URL:"},
    "sp.api_key": {"ru": "API Key:", "en": "API Key:"},
    "sp.load_ollama": {
        "ru": "📥 Загрузить модели Ollama",
        "en": "📥 Load Ollama models",
    },
    "sp.load_ollama_tooltip": {
        "ru": "Получить список моделей из локального Ollama (localhost:11434)",
        "en": "Fetch the model list from local Ollama (localhost:11434)",
    },
    "sp.no_url": {
        "ru": "Сначала укажите API Base URL",
        "en": "Specify the API Base URL first",
    },
    "sp.no_models": {
        "ru": "Ollama не вернул список моделей.\n"
              "Убедитесь: 1) ollama serve запущен, 2) есть модели (ollama list)",
        "en": "Ollama returned no models.\n"
              "Make sure: 1) ollama serve is running, 2) models exist (ollama list)",
    },
    "sp.model_dialog_title": {
        "ru": "Выберите модель Ollama",
        "en": "Select Ollama model",
    },
    "sp.model_dialog_text": {
        "ru": "Доступные модели:",
        "en": "Available models:",
    },
    "sp.model_selected": {
        "ru": "Модель выбрана: ollama/{model}\nНажмите OK для сохранения.",
        "en": "Model selected: ollama/{model}\nPress OK to save.",
    },
    "sp.ollama_error_title": {"ru": "Ошибка", "en": "Error"},
    "sp.ollama_error_text": {
        "ru": "Не удалось загрузить модели Ollama:\n{exc}\n\n"
              "Проверьте: 1) ollama serve, 2) URL: {base_url}, 3) ollama list",
        "en": "Could not load Ollama models:\n{exc}\n\n"
              "Check: 1) ollama serve, 2) URL: {base_url}, 3) ollama list",
    },
    "sp.name_required": {"ru": "Название обязательно", "en": "Name is required"},
    "sp.url_required": {"ru": "URL обязателен", "en": "URL is required"},
    "sp.delete_title": {"ru": "Удалить провайдера", "en": "Delete provider"},
    "sp.delete_text": {"ru": "Удалить «{name}»?", "en": "Delete “{name}”?"},
    "sp.ok": {"ru": "OK", "en": "OK"},
    "sp.cancel": {"ru": "Отмена", "en": "Cancel"},

    # --- Page editor ---
    "pe.original": {"ru": "Оригинал:", "en": "Original:"},
    "pe.translation": {"ru": "Перевод:", "en": "Translation:"},
    "pe.back": {"ru": "◀ Назад", "en": "◀ Back"},
    "pe.skip": {"ru": "⏭ Пропустить", "en": "⏭ Skip"},
    "pe.rephrase": {"ru": "🔄 Перефразировать", "en": "🔄 Rephrase"},
    "pe.translate": {"ru": "🌐 Перевести", "en": "🌐 Translate"},
    "pe.next": {"ru": "Далее ▶", "en": "Next ▶"},
    "pe.accept": {"ru": "✅ Принять", "en": "✅ Accept"},
    "pe.reject": {"ru": "↩️ Оставить как есть", "en": "↩️ Keep as is"},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def tr(key: str, /, **kwargs) -> str:
    """Return the translated string for *key* in the active language.

    If *kwargs* are given, the string is formatted with them (``str.format``).
    """
    entry = STRINGS.get(key)
    if entry is None:
        return key.format(**kwargs) if kwargs else key
    text = entry.get(_CURRENT) or entry.get(LANG_RU) or key
    return text.format(**kwargs) if kwargs else text


def detect_language() -> str:
    """Detect the system UI language via ``QLocale``.

    Returns ``"en"`` for an English system locale, ``"ru"`` otherwise.
    """
    if QLocale.system().language() == QLocale.Language.English:
        return LANG_EN
    return LANG_RU


def _resolve(lang: str) -> str:
    return detect_language() if lang == LANG_AUTO else lang


def set_language(lang: str) -> None:
    """Set the active UI language (``auto``/``ru``/``en``)."""
    global _CURRENT
    _CURRENT = _resolve(lang)


def get_language() -> str:
    """Return the concrete active language (``ru``/``en``)."""
    return _CURRENT


def language_label(lang: str) -> str:
    """Return the human-readable label for *lang* (falls back to Auto)."""
    return _LANG_LABELS.get(lang, _LANG_LABELS[LANG_AUTO])


def label_to_language(label: str) -> str:
    """Return the language key for a combo-box *label* (falls back to Auto)."""
    return {v: k for k, v in _LANG_LABELS.items()}.get(label, LANG_AUTO)
