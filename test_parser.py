from pathlib import Path
from parsers.txt_parser import TxtParser

# Замени на путь к своей книге
book_path = Path("/home/borrow/Загрузки/Litvak_Esli_hochesh_byit_schastlivyim_RuLit_Net.txt")

parser = TxtParser()
book = parser.parse(str(book_path))

print(f"Файл: {book_path}")
print(f"Размер: {book_path.stat().st_size} байт")
print(f"Название: {book.title}")
print(f"Глав: {len(book.chapters)}")
print(f"Страниц: {len(book.pages) if hasattr(book, 'pages') else 'N/A'}")

# Посчитаем общее количество символов
total_chars = sum(len(p.original_text) for p in book.pages) if hasattr(book, 'pages') else 0
print(f"Всего символов в страницах: {total_chars}")
print(f"Размер файла: {book_path.read_text(encoding='utf-8', errors='replace').__len__()}")

if total_chars < book_path.stat().st_size * 0.9:
    print("⚠️  ВНИМАНИЕ: Потеряно более 10% текста!")
else:
    print("✅ Текст загружен полностью")
EOF
