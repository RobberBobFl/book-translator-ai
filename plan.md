# Plan.md — Desktop Book Translator (v3)

Пакетный перевод книг с помощью LLM. Python 3.12 + uv + PyQt6 + litellm.

---

## 1. Архитектура приложения

```
book_translator/
├── main.py
├── app.py
├── core/
│   ├── __init__.py
│   ├── models.py              # Pydantic: все модели
│   ├── book.py                # Book — агрегатор
│   ├── glossary.py            # GlossaryManager
│   └── config.py              # ConfigManager (providers.json)
├── parsers/
│   ├── __init__.py
│   ├── base.py
│   ├── epub_parser.py
│   ├── fb2_parser.py
│   ├── pdf_parser.py
│   ├── txt_parser.py
│   └── import_parser.py       # Импорт готового перевода для сравнения
├── translator/
│   ├── __init__.py
│   ├── engine.py              # TranslatorEngine (litellm)
│   ├── prompt_builder.py      # Многоуровневый промпт
│   ├── chunker.py             # Разбивка больших абзацев
│   └── context_builder.py     # Контекст из N предыдущих
├── state/
│   ├── __init__.py
│   ├── database.py            # SQLite CRUD
│   └── schema.py              # DDL + миграции
├── exporters/
│   ├── __init__.py
│   ├── markdown_exporter.py
│   ├── pandoc_exporter.py
│   └── comparison_exporter.py
├── gui/
│   ├── __init__.py
│   ├── main_window.py         # QMainWindow (QTabWidget)
│   ├── widgets/
│   │   ├── book_loader.py     # Загрузка книги + хеширование
│   │   ├── glossary_panel.py  # Таблица глоссария
│   │   ├── paragraph_editor.py # Оригинал + перевод + кнопки действий
│   │   ├── translation_panel.py # Переключатель режимов, прогресс, лог
│   │   ├── comparison_panel.py  # Split-view + difflib
│   │   ├── settings_panel.py    # Провайдеры, модели A/B, параметры
│   │   └── history_panel.py     # Выбор переводов из истории
│   └── worker.py              # QObject + корутины (auto/interactive/hybrid)
└── utils/
    ├── __init__.py
    ├── logger.py
    ├── hash_utils.py
    └── cost_calculator.py
```

**Поток данных:**
```
Файл → Parser → Book → GlossaryManager (авто-детект)
  → SQLite: books + translations + paragraphs (×1-2 model_id) + glossary
  → Worker (auto/interactive/hybrid) → prompt_builder → engine (litellm) → SQLite
  → Прогресс: по абзацам + по токенам
  → По завершению → Comparison panel или Exporter
```

---

## 2. Библиотеки (pyproject.toml)

```toml
[project]
name = "book-translator"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "PyQt6>=6.7",
    "qasync>=0.27",
    "litellm>=1.40",
    "ebooklib>=0.18",
    "PyMuPDF>=1.24",
    "lxml>=5.2",
    "pydantic>=2.7",
    "aiofiles>=24.1",
    "loguru>=0.7",
    "markdown>=3.6",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.4",
    "mypy>=1.10",
]
```

Pandoc устанавливается системно: `apt install pandoc` / `brew install pandoc`.

---

## 3. Детали GUI

### 3.1 Главное окно

`QTabWidget` с **четырьмя** вкладками:

| Вкладка | Содержимое |
|---------|-----------|
| **Книга** | `book_loader.py` + `glossary_panel.py`. Загрузка, хеширование, глоссарий. Кнопка «Скачать перевод». |
| **Перевод** | `translation_panel.py` + `paragraph_editor.py`. Переключатель режимов, 3 способа работы. |
| **Сравнение** | `comparison_panel.py`. 3 режима, split-view, difflib. |
| **Настройки** | `settings_panel.py`. Провайдеры, модели A/B, temperature, top-p, max_tokens, стиль. |

### 3.2 Три режима перевода

На вкладке «Перевод» — `QComboBox` выбора режима:

#### Режим A: Автоматический
- Start → полный автоперевод без остановок
- Показывает прогресс-бары (абзацы + токены)
- Пауза / Стоп — классически
- Пользователь уходит пить кофе

```
┌─────────────────────────────────────────────┐
│ Model A: ████████████░░░░░░ 60% (30/50)    │
│ Токены:  ████████░░░░░░░░░░ 42% (12K/27K)  │
│ Потрачено: $1.24  │  ≈$0.80 осталось       │
└─────────────────────────────────────────────┘
```

#### Режим B: Интерактивный
- Перевод 1 абзаца → показ в `paragraph_editor` → ожидание действия
- Кнопки: «Далее», «Пропустить», «Перефразировать», «Переключить на авто»
- Редактирование перевода напрямую в QTextEdit
- Автосохранение при смене абзаца

```
┌─────────────────────────────────────────────┐
│ Абзац 12/35  │  гл.2                        │
│─────────────────────────────────────────────│
│ Оригинал:                                    │
│ ┌─────────────────────────────────────────┐ │
│ │ The quick brown fox jumps over the dog │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ Перевод:                                    │
│ ┌─────────────────────────────────────────┐ │
│ │ Быстрая коричневая лиса прыгает...     │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ [< Назад] [Далее >] [Пропустить] [Перефразировать] │
│ [Переключить на авто]                        │
└─────────────────────────────────────────────┘
```

#### Режим C: Гибридный
- Автоматический перевод в фоне
- Справа — список всех переведённых абзацев (с цветовой индикацией)
- Пауза → клик на любой абзац → правка в `paragraph_editor` → Продолжить
- Самый гибкий режим

```
┌─────────────────────────────────────────────┬──────────────────────┐
│ ██████████████░░░░░░░ 65% (23/35)           │ [Список абзацев]     │
│ Потрачено: $1.98  │  ≈$0.55 осталось        │                     │
│                                             │ ✓ 1. Глава 1       │
│ Текущий: абзац 24/35 (гл.3)                 │ ✓ 2. Глава 1       │
│                                             │ ✓ 3. Глава 1  [✎]  │
│ [ Пауза ] [ Стоп ]                          │ ✓ 4. Глава 2       │
│                                             │ ...                 │
└─────────────────────────────────────────────┴──────────────────────┘
```

### 3.3 ParagraphEditor — `gui/widgets/paragraph_editor.py`

| Компонент | Описание |
|-----------|----------|
| `QTextBrowser` (оригинал) | Read-only, подсветка текущего абзаца |
| `QTextEdit` (перевод) | Редактируемый, автосохранение при потере фокуса |
| Кнопки | Далее / Пропустить / Перефразировать / Переключить на авто |
| Статус | Индикатор «изменено вручную» |

### 3.4 Управление провайдерами + цены

Гибридная система цен:
1. По умолчанию — из `litellm.model_cost` (встроенная база)
2. Переопределение в `providers.json` для кастомных провайдеров
3. Ollama → цена = 0

```json
{
  "providers": [
    {
      "id": "openai",
      "name": "OpenAI",
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-...",
      "models": {
        "gpt-4o": {
          "input_cost_per_1k": 0.005,
          "output_cost_per_1k": 0.015
        }
      }
    }
  ]
}
```

### 3.5 Сравнение — три режима (вкладка «Сравнение»)

| Подвкладка | Описание |
|-----------|----------|
| **Новое сравнение** | Выбор 2 моделей → параллельный перевод → split-view |
| **С готовым переводом** | Загрузка файла перевода → перевод оригинала → сравнение |
| **С предыдущим переводом** | Выбор 2 переводов из истории → сразу сравнение |

Split-view: `QSplitter` с двумя `QTextBrowser`, difflib HTML-подсветка.

**Ограничение:** режим сравнения работает только в автоматическом или гибридном режиме. Интерактивный — однопоточный (одна модель).

### 3.6 Resume и хеширование

При старте:
1. Проверить `session_state` — есть незавершённая книга?
2. Посчитать SHA256 текущего файла, сравнить с `file_hash` в БД
3. Если файл изменился — диалог: «Файл изменился. Начать заново? Продолжить (рискованно)?»
4. Если файл не менялся — предложить продолжить

### 3.7 Keyboard Shortcuts

| Клавиша | Действие |
|---------|----------|
| `Ctrl+O` | Открыть книгу |
| `Space` | Пауза / продолжить |
| `Esc` | Стоп |
| `Ctrl+Enter` | Далее (интерактивный режим) |
| `Ctrl+S` | Сохранить прогресс (force commit) |

### 3.8 Проблемные абзацы

```
┌─────────────────────────────────────────────┐
│ # │ Абзац         │ Модель │ Статус   │ Действие│
│───┼───────────────┼────────┼──────────┼─────────│
│ 12│ гл.2, абз. 4  │ gpt-4o │ 🔴 failed│ [Повторить]│
│ 45│ гл.5, абз. 12 │ gpt-4o │ 🟡 retry │ [Повторить]│
└─────────────────────────────────────────────┘
```

---

## 4. Архитектура Worker (три режима)

```python
class TranslationWorker(QObject):
    progress_updated = pyqtSignal(int, int)
    token_progress = pyqtSignal(int, int)
    cost_updated = pyqtSignal(Decimal, Decimal)
    paragraph_ready = pyqtSignal(int, Paragraph)
    translation_mode = pyqtSignal(str)
    log_message = pyqtSignal(str)
    finished = pyqtSignal()

    MODE_AUTO = "auto"
    MODE_INTERACTIVE = "interactive"
    MODE_HYBRID = "hybrid"

    def __init__(self):
        self.mode = self.MODE_AUTO
        self._paused = asyncio.Event()
        self._paused.set()
        self._user_action = asyncio.Future()
        self._cancelled = False
```

**Логика run():**

```
for каждый pending параграф:
  1. translate(paragraph) → litellm
  2. Если interactive → emit paragraph_ready → await wait_for_user_action()
  3. Если hybrid → emit paragraph_ready (UI обновляет список) → continue без ожидания
  4. save_paragraph(paragraph)
  5. emit progress_updated
  6. await self._paused.wait()  # проверка паузы
  7. Проверить self._cancelled
```

**Переключение режимов на лету:**
- Interactive → Auto: `worker.mode = "auto"`, `resolve_user_action("next")`
- Auto → Hybrid: `worker.mode = "hybrid"` (продолжает бежать, шлёт `paragraph_ready`)
- Hybrid → Interactive: `worker.mode = "interactive"` (следующий параграф будет ждать)

---

## 5. Структуры данных

### In-memory (Pydantic)

```python
class Paragraph(BaseModel):
    id: int
    translation_id: int
    chapter_title: str
    paragraph_index: int
    original_text: str
    model_id: str
    translated_text: str | None = None
    status: Literal["pending", "translating", "completed", "failed"] = "pending"
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    retry_count: int = 0
    error_message: str | None = None
    is_manually_edited: bool = False
    edit_history: list[EditRecord] = []

class EditRecord(BaseModel):
    timestamp: str
    old_text: str
    new_text: str

class Chapter(BaseModel):
    title: str
    paragraphs: list[Paragraph]

class Book(BaseModel):
    id: int | None = None
    title: str
    source_path: str
    source_format: str
    file_hash: str
    chapters: list[Chapter]
    translations: list[Translation] = []

class GlossaryEntry(BaseModel):
    id: int | None = None
    book_id: int
    original_term: str
    translated_term: str | None = None
    is_auto_detected: bool = False
    context: str | None = None

class Translation(BaseModel):
    id: int
    book_id: int
    name: str
    model_id: str | None
    source_type: Literal["parallel", "imported", "previous"]
    created_at: str
    total_cost: Decimal = Decimal("0")
    total_tokens: int = 0
    mode: Literal["auto", "interactive", "hybrid"] = "auto"

class Provider(BaseModel):
    id: str
    name: str
    base_url: str
    api_key: str | None = None
    models: dict[str, ModelPricing]
    default_model: str

class ModelPricing(BaseModel):
    input_cost_per_1k: Decimal
    output_cost_per_1k: Decimal

class TranslationJob(BaseModel):
    model_id: str
    temperature: Decimal = Decimal("0.3")
    top_p: Decimal = Decimal("0.9")
    max_tokens: int = 4096
    style: Literal["дословный", "литературный", "адаптированный"] = "литературный"
    mode: Literal["auto", "interactive", "hybrid"] = "auto"
```

### SQLite Schema

```sql
CREATE TABLE books (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    source_path     TEXT NOT NULL,
    source_format   TEXT NOT NULL,
    file_hash       TEXT NOT NULL,
    total_paragraphs INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE translations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    model_id        TEXT,
    source_type     TEXT NOT NULL
                    CHECK(source_type IN ('parallel','imported','previous')),
    mode            TEXT NOT NULL DEFAULT 'auto'
                    CHECK(mode IN ('auto','interactive','hybrid')),
    total_cost      DECIMAL(10,6) NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE paragraphs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    translation_id  INTEGER NOT NULL REFERENCES translations(id) ON DELETE CASCADE,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_title   TEXT NOT NULL,
    paragraph_index INTEGER NOT NULL,
    original_text   TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    translated_text TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','translating','completed','failed')),
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    cost_usd        DECIMAL(10,6) NOT NULL DEFAULT 0,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    is_manually_edited INTEGER NOT NULL DEFAULT 0,
    edit_history    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(translation_id, chapter_title, paragraph_index)
);

CREATE TABLE glossary (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    original_term   TEXT NOT NULL,
    translated_term TEXT,
    is_auto_detected INTEGER NOT NULL DEFAULT 0,
    context         TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(book_id, original_term)
);

CREATE TABLE session_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id),
    mode            TEXT NOT NULL DEFAULT 'auto',
    translation_a_id INTEGER REFERENCES translations(id),
    translation_b_id INTEGER REFERENCES translations(id),
    current_paragraph_index INTEGER DEFAULT 0,
    system_prompt   TEXT,
    is_paused       INTEGER NOT NULL DEFAULT 0
);
```

---

## 6. Пошаговый план реализации

| Шаг | Что делаем | Проверка |
|-----|-----------|----------|
| **1** | `uv init --python 3.12`, pyproject.toml, структура папок, `__init__.py` | `uv sync` |
| **2** | `core/models.py` — все Pydantic модели | mypy проходит |
| **3** | `state/schema.py` + `state/database.py` — SQLite: create_tables, CRUD | Юнит-тест |
| **4** | `parsers/` — 4 парсера + `import_parser.py`. SHA256 хеширование | Ручной тест |
| **4.5** | `core/glossary.py` — авто-детект имён, CRUD | Юнит-тест |
| **5** | `translator/prompt_builder.py` + `context_builder.py` | Тест вывода |
| **5.5** | `translator/chunker.py` — разбивка больших абзацев | Юнит-тест |
| **6** | `translator/engine.py` — litellm + retry + cost calc | Тест с моком |
| **7** | `gui/widgets/book_loader.py` + `gui/widgets/glossary_panel.py` | Загрузка + глоссарий |
| **8** | `gui/widgets/settings_panel.py` — провайдеры, Model A/B, параметры | Настройки сохраняются |
| **9** | `gui/worker.py` — базовая корутина (auto mode) | Перевод 1 абзаца |
| **9.5** | `gui/widgets/paragraph_editor.py` — виджет для правки абзацев | UI отображается |
| **9.6** | `gui/worker.py` — interactive + hybrid режимы | Все 3 режима работают |
| **9.7** | `gui/widgets/translation_panel.py` — переключатель, прогресс-бары, лог | Полный контроль |
| **10** | `gui/main_window.py` — QTabWidget, resume, хеширование, hotkeys | Полный цикл |
| **10.5** | `gui/widgets/comparison_panel.py` — 3 режима, split-view, difflib | Сравнение работает |
| **11** | `exporters/` — markdown + pandoc + comparison | Экспорт |
| **12** | Финальное тестирование + экспорт лога ошибок | Стабильная работа |

---

## 7. Риски и их решение

| Риск | Решение |
|------|---------|
| **UI зависает при переводе** | qasync + сигналы |
| **API error / timeout** | Retry 3× (2→4→8 сек). Если всё упало → `failed` |
| **Context window overflow** | Динамическое урезание контекста; chunker |
| **Битый файл книги** | try/except в парсерах, сообщение пользователю |
| **Краш / закрытие** | SQLite commit после каждого параграфа. Resume через session_state |
| **Файл книги изменился** | SHA256 при загрузке; диалог при расхождении |
| **Интерактивный режим замедляет** | Предупреждение при выборе: «Требуется ваше участие» |
| **Пользователь забыл сохранить правки** | Автосохранение при переключении абзаца |
| **Переключение режимов на лету** | Worker меняет `self.mode`, корректно завершает ожидание user_action |
| **Разные переводы одного имени** | Глоссарий + ручная правка |
| **Дорогой перевод / лимит токенов** | Cost_tracker + предупреждения через `litellm.model_cost` |
| **Параллельный перевод (сравнение)** | `asyncio.Semaphore(2)` — не более 2 одновременных запросов |
| **Pandoc не установлен** | `shutil.which("pandoc")` → инструкция |
| **Утечка API-ключа** | Password-echo, chmod 600 для конфига |
