# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "matplotlib"]
# ///
"""
Tail-at-scale: the source-of-truth model.

This is the receipts for the web toy (index.html). It runs a Monte-Carlo
simulation of N service calls aggregated either in parallel (wait for the
slowest -> max) or in series (sum), counts how often the aggregate latency
blows a budget, and *asserts* that the parallel result matches the analytic
headline   P(bad) = 1 - (1 - w)^N.

Run:  uv run model.py        # auto-installs numpy + matplotlib, regenerates docs/ plots

The intuition it proves:
  - Fan-out amplifies tails. A rare (1%) slow call becomes a common bad page
    load as you add parallel dependencies.
  - Parallel and serial fail by DIFFERENT mechanisms:
      parallel = max()  -> the tail mode takes over (variance amplification)
      serial   = sum()  -> the whole distribution marches right (the MEAN
                           accumulates; you blow the budget on the average
                           alone, you don't even need the tail).
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless; we only save files
import matplotlib.pyplot as plt
from pathlib import Path

# --- Model parameters (kept in lockstep with the defaults in index.html) -----
FAST_MEAN, FAST_SD = 80.0, 8.0      # ms   the common-case mode
SLOW_MEAN, SLOW_SD = 800.0, 80.0    # ms   the tail mode (heavy on purpose: a
                                    #      1.25x "tail" is too polite to see)
W = 0.01                            # weight of the slow mode == p99 -> 1% slow
BUDGET = 250.0                      # ms   "bad" == aggregate latency > BUDGET
TRIALS = 200_000                    # Monte-Carlo trials per data point
SEED = 7


def sample_calls(rng, shape, w=W):
    """Draw call latencies from the bimodal mixture, vectorised to `shape`."""
    is_slow = rng.random(shape) < w
    fast = rng.normal(FAST_MEAN, FAST_SD, shape)
    slow = rng.normal(SLOW_MEAN, SLOW_SD, shape)
    return np.where(is_slow, slow, fast)


def aggregate(calls, mode):
    """calls: (trials, N) -> (trials,) aggregate latency per trial."""
    if mode == "parallel":
        return calls.max(axis=1)   # wait for the slowest
    elif mode == "serial":
        return calls.sum(axis=1)   # chain of dependent calls
    raise ValueError(mode)


def p_bad_mc(rng, n, mode, w=W, budget=BUDGET, trials=TRIALS):
    calls = sample_calls(rng, (trials, n), w)
    agg = aggregate(calls, mode)
    return float(np.mean(agg > budget))


def p_bad_analytic_parallel(n, w=W):
    """The headline. Valid when BUDGET sits cleanly between the two modes:
    a call is 'clean' iff it's in the fast mode, so P(max clean) = (1-w)^N."""
    return 1.0 - (1.0 - w) ** n


def one_in(p):
    return float("inf") if p <= 0 else 1.0 / p


def print_table(rng):
    ns = [1, 5, 10, 15, 20, 30, 40, 50]
    print(f"\nModel: fast N({FAST_MEAN:.0f},{FAST_SD:.0f})  slow N({SLOW_MEAN:.0f},"
          f"{SLOW_SD:.0f})  w={W:.0%}  budget={BUDGET:.0f}ms  trials={TRIALS:,}\n")
    print(f"{'N':>4} | {'parallel MC':>11} {'analytic':>9} {'~1 in':>6} | "
          f"{'serial MC':>9} {'~1 in':>6}")
    print("-" * 60)
    worst = 0.0
    for n in ns:
        pp = p_bad_mc(rng, n, "parallel")
        pa = p_bad_analytic_parallel(n)
        ps = p_bad_mc(rng, n, "serial")
        worst = max(worst, abs(pp - pa))
        print(f"{n:>4} | {pp:>10.1%} {pa:>9.1%} {one_in(pp):>6.1f} | "
              f"{ps:>8.1%} {one_in(ps):>6.1f}")
    print()
    return worst


def assert_parallel_matches_analytic(rng):
    """The web toy can't lie if the Python proves the math first."""
    tol = 0.01  # 1 percentage point; MC noise at 200k trials is well under this
    for n in [1, 5, 10, 15, 20, 30, 40]:
        mc = p_bad_mc(rng, n, "parallel")
        an = p_bad_analytic_parallel(n)
        assert abs(mc - an) < tol, f"N={n}: MC {mc:.3%} vs analytic {an:.3%}"
    print(f"[ok] parallel MC matches 1-(1-w)^N within {tol:.0%} across N")


def plot_climb(rng, out):
    ns = np.arange(1, 51)
    mc = [p_bad_mc(rng, int(n), "parallel") for n in ns]
    an = [p_bad_analytic_parallel(int(n)) for n in ns]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(ns, np.array(an) * 100, "-", lw=2, label="analytic  1-(1-w)^N")
    ax.plot(ns, np.array(mc) * 100, "o", ms=3, label="Monte-Carlo (max)")
    for n, lbl in [(18, "N=18\n~17% (1 in 6)"), (40, "N=40\n~1 in 3")]:
        y = p_bad_analytic_parallel(n) * 100
        ax.annotate(lbl, (n, y), textcoords="offset points", xytext=(6, -28),
                    fontsize=9, arrowprops=dict(arrowstyle="->", lw=0.8))
    ax.set_xlabel("N parallel dependencies")
    ax.set_ylabel("% of page loads that are BAD")
    ax.set_title("Fan-out amplifies tails: P(bad) = 1 - (1-w)^N   (p99 call, w=1%)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"[plot] {out}")


def plot_morph(rng, out):
    """Parallel: tail takes over.  Serial: distribution marches right."""
    ns = [1, 5, 15, 40]
    fig, axes = plt.subplots(2, len(ns), figsize=(13, 6), sharey="row")
    for col, n in enumerate(ns):
        for row, mode in enumerate(["parallel", "serial"]):
            ax = axes[row][col]
            calls = sample_calls(rng, (40_000, n))
            agg = aggregate(calls, mode)
            hi = np.percentile(agg, 99.5)
            ax.hist(agg, bins=80, range=(0, max(hi, BUDGET * 1.2)),
                    color="#4c72b0" if mode == "parallel" else "#dd8452",
                    alpha=0.85)
            ax.axvline(BUDGET, color="crimson", lw=1.5, ls="--")
            pbad = float(np.mean(agg > BUDGET))
            ax.set_title(f"{mode}  N={n}\n{pbad:.0%} bad", fontsize=9)
            ax.set_yticks([])
            if row == 1:
                ax.set_xlabel("latency (ms)")
    fig.suptitle("Same model, two mechanisms — parallel (max) fattens the tail; "
                 "serial (sum) marches the whole distribution past the budget",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"[plot] {out}")


def main():
    rng = np.random.default_rng(SEED)
    worst = print_table(rng)
    print(f"max |MC - analytic| over the table (parallel) = {worst:.3%}")
    assert_parallel_matches_analytic(rng)
    docs = Path(__file__).parent / "docs"
    docs.mkdir(exist_ok=True)
    plot_climb(rng, docs / "climb.png")
    plot_morph(rng, docs / "morph.png")
    print("\nDone. The web toy (index.html) uses this exact model.\n")


if __name__ == "__main__":
    main()
