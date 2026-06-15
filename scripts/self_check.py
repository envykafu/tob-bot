import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "bot.py", *sorted((ROOT / "src").glob("*.py")), *sorted((ROOT / "src" / "plugins").glob("*.py"))]


def main() -> None:
    for path in FILES:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print(f"AST OK: {len(FILES)} files")


if __name__ == "__main__":
    main()
