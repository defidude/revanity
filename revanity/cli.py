"""
Command-line interface for revanity.

Usage:
    python -m revanity --prefix dead
    python -m revanity --suffix cafe --workers 8
    python -m revanity --contains beef --dest nomadnetwork.node
    python -m revanity --regex "^(dead|beef)" --output my_identity
"""

import argparse
import sys

from revanity import __version__
from revanity.matcher import MatchMode
from revanity.generator import VanityGenerator, GeneratorStats
from revanity.export import prepare_export, save_identity_file, save_identity_text
from revanity.verify import verify_with_rns


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="revanity",
        description="Reticulum/LXMF Vanity Address Generator",
        epilog=(
            "Examples:\n"
            "  revanity --prefix dead\n"
            "  revanity --suffix cafe --workers 8\n"
            "  revanity --contains beef\n"
            '  revanity --regex "^(dead|beef)"\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version", action="version", version=f"revanity {__version__}"
    )

    pattern = parser.add_mutually_exclusive_group(required=True)
    pattern.add_argument(
        "--prefix", "-p", metavar="HEX",
        help="Find address starting with this hex string",
    )
    pattern.add_argument(
        "--suffix", "-s", metavar="HEX",
        help="Find address ending with this hex string",
    )
    pattern.add_argument(
        "--contains", "-c", metavar="HEX",
        help="Find address containing this hex string anywhere",
    )
    pattern.add_argument(
        "--regex", "-r", metavar="PATTERN",
        help="Find address matching this regex pattern",
    )

    parser.add_argument(
        "--dest", "-d", default="lxmf.delivery",
        help="Destination type (default: lxmf.delivery)",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=0,
        help="Number of worker processes (default: auto)",
    )
    parser.add_argument(
        "--output", "-o", metavar="PATH",
        help="Output file path prefix (default: ./<dest_hash>)",
    )
    parser.add_argument(
        "--no-verify", action="store_true",
        help="Skip RNS library verification",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show difficulty estimate without searching",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Minimal output (just the result address)",
    )

    return parser


def format_time(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    elif seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    else:
        return f"{seconds / 86400:.1f}d"


def format_rate(rate: float) -> str:
    if rate < 1000:
        return f"{rate:.0f}"
    elif rate < 1_000_000:
        return f"{rate / 1000:.1f}K"
    else:
        return f"{rate / 1_000_000:.2f}M"


def progress_callback(stats: GeneratorStats, quiet: bool = False) -> None:
    if quiet:
        return
    sys.stderr.write(
        f"\r  Checked: {stats.total_checked:,}  |  "
        f"Rate: {format_rate(stats.rate)}/sec  |  "
        f"Elapsed: {format_time(stats.elapsed)}  "
    )
    sys.stderr.flush()


def main(argv: list[str] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.prefix:
        mode, pattern = MatchMode.PREFIX, args.prefix
    elif args.suffix:
        mode, pattern = MatchMode.SUFFIX, args.suffix
    elif args.contains:
        mode, pattern = MatchMode.CONTAINS, args.contains
    else:
        mode, pattern = MatchMode.REGEX, args.regex

    try:
        gen = VanityGenerator(
            pattern=pattern,
            mode=mode,
            dest_type=args.dest,
            num_workers=args.workers,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    difficulty = gen.get_difficulty()

    if not args.quiet:
        print(f"revanity v{__version__}")
        print(f"  Pattern:    {mode.value}='{gen.pattern_str}'")
        print(f"  Destination: {args.dest}")
        print(f"  Workers:    {gen.num_workers}")
        if difficulty["expected_attempts"]:
            print(f"  Expected:   ~{difficulty['expected_attempts']:,} attempts")
        print(f"  Difficulty: {difficulty['difficulty_description']}")
        print()

    if args.dry_run:
        return 0

    gen.on_progress = lambda stats: progress_callback(stats, args.quiet)

    if not args.quiet:
        print("Searching...")

    results = gen.run_blocking(progress_interval=0.5)

    if not args.quiet:
        sys.stderr.write("\n")

    if not results:
        print("No results found (search was interrupted).", file=sys.stderr)
        return 1

    for i, result in enumerate(results):
        export = prepare_export(
            result.private_key,
            result.identity_hash,
            result.dest_type,
            result.dest_hash_hex,
        )

        if not args.quiet:
            print(f"\n{'=' * 60}")
            print(f"  MATCH FOUND")
            lxmf_addr = export.dest_hashes.get("lxmf.delivery", "N/A")
            print(f"  LXMF Address:   {lxmf_addr}")
            if "nomadnetwork.node" in export.dest_hashes:
                print(f"  NomadNet Node:  {export.dest_hashes['nomadnetwork.node']}")
            print(f"  Identity Hash:  {export.identity_hash_hex}")
            print(f"  Time:           {format_time(result.elapsed)}")
            print(f"  Keys Checked:   {result.total_checked:,}")
            print(f"  Rate:           {format_rate(result.rate)}/sec")
            print(f"{'=' * 60}")

        out_prefix = args.output if args.output else result.dest_hash_hex
        identity_path = save_identity_file(
            result.private_key, out_prefix + ".identity"
        )
        text_path = save_identity_text(export, out_prefix + ".txt")

        if not args.quiet:
            print(f"\n  Saved identity: {identity_path}")
            print(f"  Saved info:     {text_path}")

        if not args.no_verify:
            v = verify_with_rns(
                result.private_key,
                export.identity_hash_hex,
                result.dest_hash_hex,
                dest_name=args.dest,
            )
            if not args.quiet:
                if v["rns_available"]:
                    id_ok = "PASS" if v["identity_hash_match"] else "FAIL"
                    dest_ok = "PASS" if v["dest_hash_match"] else "FAIL"
                    print(f"\n  RNS Verification:")
                    print(f"    Identity hash: {id_ok}")
                    print(f"    Dest hash:     {dest_ok}")
                else:
                    print(f"\n  RNS verification skipped ({v['error']})")

        if args.quiet:
            print(result.dest_hash_hex)

    return 0
