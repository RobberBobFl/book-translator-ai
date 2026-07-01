# PROJECT CONTEXT & AGENT RULES

## 1. PROJECT OVERVIEW
We are building a desktop book translation app using Python 3.12, `uv`, PyQt6, and `litellm`. 
Core features: Paragraph-by-paragraph translation with context preservation, crash-resilient state saving (SQLite/JSONL), and multi-format export.

## 2. CRITICAL SAFETY & FILE MANAGEMENT (STRICT)
- NEVER delete any files, directories, or git branches without explicit, prior confirmation.
- If you need to delete a file, STOP and ask: "I need to delete [file_path] because [reason]. Approve? (yes/no)". Wait for "yes".
- NEVER execute destructive shell commands (`rm -rf`, `git clean -fd`, `git reset --hard`) automatically. Always ask first.
- If unsure if an action is safe, ASK ME FIRST.

## 3. CODING STANDARDS & PYTHON RULES
- **Python Version:** Strictly Python 3.12. Use modern features (type hinting with `|`, `match/case`, etc.).
- **Type Hinting:** MANDATORY. All functions, methods, and class attributes must have strict type hints. Use `typing` or built-in types.
- **Asynchronous GUI:** PyQt6 UI must NEVER freeze. All LLM API calls and file I/O must be asynchronous. Use `asyncio` and `qasync`.
- **Error Handling:** NEVER use bare `except:`. Catch specific exceptions. Log errors using `loguru`.
- **Modularity:** Keep files small. Separate concerns (e.g., `ui/`, `core/`, `parsers/`, `exporters/`).
- **State Management:** When implementing the translation loop, ALWAYS write the translated paragraph to the state database/file IMMEDIATELY after receiving it from the LLM. Do not batch save in memory.

## 4. WORKFLOW RULES
- **Step-by-Step:** Do not write the whole app at once. Follow the approved `Plan.md`. Implement one module, test it, then move to the next.
- **No Rewrites:** If a piece of code is working, do not rewrite it just to "make it prettier" without asking.
- **Explanations:** Before writing a complex block of code (like the context-sliding-window for translation), briefly explain your logic.
- **Dependencies:** If you need a new library, tell me and add it to `pyproject.toml` using `uv add <package>`. Do not just `pip install`.

## 5. TRANSLATION LOGIC SPECIFICS
- When prompting the LLM, always include a system prompt defining the persona (e.g., "You are a professional literary translator...").
- Pass previous translated paragraphs as context to maintain pronoun consistency and tone.
- Handle LLM rate limits and token limits gracefully (implement retries with exponential backoff).
