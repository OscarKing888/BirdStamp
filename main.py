from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch BirdStamp GUI editor.")
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Open this image file on startup.",
    )
    args = parser.parse_args()

    startup_file = args.file.resolve(strict=False) if args.file else None

    try:
        from birdstamp.gui import launch_gui
    except Exception as exc:
        raise SystemExit(f"GUI is unavailable: {exc}") from exc

    launch_gui(startup_file=startup_file)


if __name__ == "__main__":
    main()

