"""Allow ``python -m verification demo-ca`` and ``demo-ficha``."""
import sys

from verification.interfaces.cli import main

sys.exit(main())
