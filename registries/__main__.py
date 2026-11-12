"""Allow ``python -m registries refresh``."""
import sys

from registries.interfaces.cli import main

sys.exit(main())
