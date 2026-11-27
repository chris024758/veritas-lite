"""Run only live Groq tests; this intentionally makes a real billable API call."""
import sys
import unittest
from pathlib import Path


def main() -> int:
    backend_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(backend_dir / "tests"),
        pattern="test_live_groq_api.py",
        top_level_dir=str(backend_dir / "tests"),
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
