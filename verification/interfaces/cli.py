"""Command line of the Verification context: the demonstration fichas.

TEMPORARY PATCH for the demonstrations (see ``verification.infrastructure.demo``)::

    python -m verification demo-ca
    python -m verification demo-ficha --ruc 20601234567 --name "TEXTILES ANDINOS S.A.C." --out ficha.pdf

``demo-ca`` creates the CA once in ``demo-kyc/`` (kept out of git) and prints
the path ``KYC_DEMO_CA_PATH`` must point to. ``demo-ficha`` writes a ficha
signed by it, or unsigned with ``--unsigned``; ``--days-old`` dates it in the past.
"""
import argparse
import sys
from datetime import timedelta
from pathlib import Path

from shared.domain.calendar import lima_today
from verification.infrastructure.demo import DemoFicha, build_demo_ficha, create_demo_ca, sign_demo_ficha

DEFAULT_DIRECTORY = Path("demo-kyc")


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run it."""
    parser = argparse.ArgumentParser(
        prog="python -m verification", description="Demonstration fichas RUC, signed by Vankoo, never by SUNAT."
    )
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIRECTORY, help="where the demo CA lives (demo-kyc/)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo-ca", help="create the demonstration CA, unless it exists")
    ficha = commands.add_parser("demo-ficha", help="write a demonstration ficha RUC")
    ficha.add_argument("--ruc", required=True)
    ficha.add_argument("--name", required=True)
    ficha.add_argument("--status", default="ACTIVO")
    ficha.add_argument("--condition", default="HABIDO")
    ficha.add_argument("--days-old", type=int, default=0, help="how many days ago it was issued (default: 0)")
    ficha.add_argument("--unsigned", action="store_true", help="leave it without a signature")
    ficha.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args(argv)

    ca_path = create_demo_ca(arguments.dir)
    if arguments.command == "demo-ca":
        print(f"KYC_DEMO_CA_PATH={ca_path.resolve()}")
        return 0
    pdf = build_demo_ficha(
        DemoFicha(
            ruc=arguments.ruc,
            name=arguments.name,
            issued_on=lima_today() - timedelta(days=arguments.days_old),
            status=arguments.status,
            domicile_condition=arguments.condition,
        )
    )
    arguments.out.write_bytes(pdf if arguments.unsigned else sign_demo_ficha(pdf, arguments.dir))
    print(f"{'Unsigned' if arguments.unsigned else 'Signed'} demonstration ficha written to {arguments.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
