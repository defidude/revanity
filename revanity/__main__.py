"""Entry point for python -m revanity."""

import sys


def main():
    if "--gui" in sys.argv or len(sys.argv) == 1:
        from revanity.gui import run_gui
        sys.exit(run_gui())
    else:
        from revanity.cli import main as cli_main
        sys.exit(cli_main())


if __name__ == "__main__":
    main()
