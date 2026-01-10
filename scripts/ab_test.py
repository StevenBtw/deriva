#!/usr/bin/env python
"""
Fast A/B Testing for Deriva Configs

Usage:
    # Test a single config with N runs
    python scripts/ab_test.py DataObject --runs 5

    # Compare before/after a config change
    python scripts/ab_test.py DataObject --runs 5 --baseline bench_20260110_073524

    # Test with specific model
    python scripts/ab_test.py DataObject --runs 5 --model anthropic-haiku
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from deriva.services.benchmarking import BenchmarkConfig, BenchmarkOrchestrator
from deriva.services.session import PipelineSession


def get_element_consistency(summary_path: Path, prefix: str) -> dict:
    """Extract consistency metrics for a specific element type prefix."""
    with open(summary_path) as f:
        data = json.load(f)

    intra = data["intra_model"][0]

    stable = [e for e in intra["stable_elements"] if e.startswith(prefix)]
    unstable = {k: v for k, v in intra["unstable_elements"].items() if k.startswith(prefix)}

    total = len(stable) + len(unstable)
    consistency = (len(stable) / total * 100) if total > 0 else 0

    return {
        "stable": stable,
        "unstable": unstable,
        "total": total,
        "consistency": consistency,
    }


def run_quick_benchmark(
    config_name: str,
    runs: int = 5,
    model: str = "anthropic-haiku",
    repo: str = "flask_invoice_generator",
) -> str:
    """Run a quick benchmark focused on a single config."""

    print(f"\n{'=' * 60}")
    print(f"A/B TEST: {config_name}")
    print(f"{'=' * 60}")
    print(f"Model: {model}")
    print(f"Runs: {runs}")
    print(f"Config: {config_name}")
    print(f"{'=' * 60}\n")

    with PipelineSession() as session:
        config = BenchmarkConfig(
            repositories=[repo],
            models=[model],
            runs_per_combination=runs,
            bench_hash=True,
            use_cache=True,
            nocache_configs=[config_name],  # Only this config uncached
        )

        assert session._graph_manager is not None
        assert session._archimate_manager is not None

        orchestrator = BenchmarkOrchestrator(
            session._engine,
            session._graph_manager,
            session._archimate_manager,
            config,
        )

        result = orchestrator.run(verbose=False, progress=None)

        return result.session_id


def analyze_results(session_id: str, prefix: str) -> dict:
    """Analyze results for a specific element type."""
    summary_path = Path(f"workspace/benchmarks/{session_id}/analysis/summary.json")

    if not summary_path.exists():
        # Run analysis first
        from deriva.services.benchmarking import BenchmarkAnalyzer

        with PipelineSession() as session:
            analyzer = BenchmarkAnalyzer(session_id, session._engine)
            analyzer.compute_full_analysis()
            analyzer.export_summary()
            analyzer.save_metrics_to_db()

    return get_element_consistency(summary_path, prefix)


def compare_results(baseline_id: str, test_id: str, prefix: str):
    """Compare baseline vs test results."""
    baseline = analyze_results(baseline_id, prefix)
    test = analyze_results(test_id, prefix)

    print(f"\n{'=' * 60}")
    print("COMPARISON RESULTS")
    print(f"{'=' * 60}")
    print(f"{'Metric':<25} {'Baseline':>15} {'Test':>15} {'Change':>10}")
    print("-" * 65)

    print(f"{'Consistency':<25} {baseline['consistency']:>14.1f}% {test['consistency']:>14.1f}% {test['consistency'] - baseline['consistency']:>+9.1f}%")
    print(f"{'Stable elements':<25} {len(baseline['stable']):>15} {len(test['stable']):>15} {len(test['stable']) - len(baseline['stable']):>+10}")
    print(f"{'Unstable elements':<25} {len(baseline['unstable']):>15} {len(test['unstable']):>15} {len(test['unstable']) - len(baseline['unstable']):>+10}")
    print(f"{'Total elements':<25} {baseline['total']:>15} {test['total']:>15} {test['total'] - baseline['total']:>+10}")

    # Show which elements changed
    new_stable = set(test["stable"]) - set(baseline["stable"])
    became_unstable = set(test["unstable"].keys()) - set(baseline["unstable"].keys())

    if new_stable:
        print(f"\nNewly stable: {', '.join(sorted(new_stable))}")
    if became_unstable:
        print(f"Became unstable: {', '.join(sorted(became_unstable))}")

    # Verdict
    print(f"\n{'=' * 60}")
    if test["consistency"] >= 80:
        print("VERDICT: TARGET REACHED (>=80%)")
    elif test["consistency"] > baseline["consistency"]:
        print(f"VERDICT: IMPROVED (+{test['consistency'] - baseline['consistency']:.1f}%)")
    elif test["consistency"] < baseline["consistency"]:
        print(f"VERDICT: REGRESSED ({test['consistency'] - baseline['consistency']:.1f}%)")
    else:
        print("VERDICT: NO CHANGE")
    print(f"{'=' * 60}")


# Map config names to element prefixes
CONFIG_TO_PREFIX = {
    "ApplicationService": "as",
    "ApplicationComponent": "ac",
    "ApplicationInterface": "ai",
    "DataObject": "do",
    "BusinessProcess": "bp",
    "BusinessObject": "bo",
    "BusinessFunction": "bf",
    "BusinessEvent": "be",
    "BusinessActor": "ba",
    "TechnologyService": "techsvc",
    "Node": "node",
    "Device": "device",
    "SystemSoftware": "syssw",
}


def main():
    parser = argparse.ArgumentParser(description="Fast A/B testing for Deriva configs")
    parser.add_argument("config", help="Config name to test (e.g., DataObject)")
    parser.add_argument("--runs", "-n", type=int, default=5, help="Number of runs")
    parser.add_argument("--model", "-m", default="anthropic-haiku", help="Model to use")
    parser.add_argument("--repo", "-r", default="flask_invoice_generator", help="Repository")
    parser.add_argument("--baseline", "-b", help="Baseline session ID to compare against")
    parser.add_argument("--analyze-only", "-a", help="Only analyze existing session")

    args = parser.parse_args()

    prefix = CONFIG_TO_PREFIX.get(args.config, args.config.lower()[:2])

    if args.analyze_only:
        results = analyze_results(args.analyze_only, prefix)
        print(f"\nResults for {args.config} ({prefix}_*):")
        print(f"  Consistency: {results['consistency']:.1f}%")
        print(f"  Stable: {len(results['stable'])}")
        print(f"  Unstable: {len(results['unstable'])}")
        if results["unstable"]:
            print(f"  Unstable elements: {', '.join(sorted(results['unstable'].keys()))}")
        return

    # Run benchmark
    session_id = run_quick_benchmark(
        args.config,
        runs=args.runs,
        model=args.model,
        repo=args.repo,
    )

    print(f"\nSession: {session_id}")

    # Analyze
    results = analyze_results(session_id, prefix)

    print(f"\nResults for {args.config} ({prefix}_*):")
    print(f"  Consistency: {results['consistency']:.1f}%")
    print(f"  Stable: {len(results['stable'])}")
    print(f"  Unstable: {len(results['unstable'])}")
    if results["unstable"]:
        print(f"  Unstable elements: {', '.join(sorted(results['unstable'].keys()))}")

    # Compare if baseline provided
    if args.baseline:
        compare_results(args.baseline, session_id, prefix)


if __name__ == "__main__":
    main()
