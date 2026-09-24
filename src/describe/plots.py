"""Figures for the PI-1 results section (main_EMSE.tex, D.1/D.2).

Reads data/prevalence_report.json -- already produced by prevalence.py -- and
writes two PDFs under figures/. No new statistics are computed here; this is
presentation only, so every number on these plots must already exist in that
report.

  D.1: monthly histogram of H1 first appearances, with the 2025-07-30 PR
       window cutoff marked. Two effects (saturation, selection) distort this
       curve and are discussed in prose (Sec. Cuando se adopto); the plot
       itself is descriptive.
  D.2: 5x5 co-occurrence heatmap among the five common mechanisms
       (H1/H2/H3/H7/H8). H5 pairs are excluded on purpose: H5 is conditioned
       on H1, not an independent mechanism (Sec. El caso H5), so a
       H5-inclusive matrix would misrepresent it as one.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPORT = ROOT / "data" / "prevalence_report.json"
FIGDIR = ROOT / "figures"

CUTOFF = dt.date(2025, 7, 30)
MECHS = ["H1", "H2", "H3", "H7", "H8"]

# matplotlib stamps /CreationDate into every PDF it writes, so two runs of an
# unchanged script produce files differing in exactly those seven bytes. That is
# enough to fail a checksum comparison in the replication package (spec 002,
# AC-2) while the plotted content is bit-identical. Suppressing the timestamp
# makes the figures byte-reproducible.
PDF_METADATA = {"CreationDate": None}


def plot_adoption_curve(report: dict) -> pathlib.Path:
    months = report["h1_first_appearance_by_month"]
    xs = [dt.datetime.strptime(k, "%Y-%m") for k in months]
    ys = [months[k] for k in months]
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    xs = [xs[i] for i in order]
    ys = [ys[i] for i in order]

    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.bar(xs, ys, width=20, color="#4C6EF5", edgecolor="none")
    ax.axvline(dt.datetime(CUTOFF.year, CUTOFF.month, CUTOFF.day),
               color="#B3261E", linestyle="--", linewidth=1.2)
    ax.text(dt.datetime(CUTOFF.year, CUTOFF.month, CUTOFF.day), max(ys) * 1.03,
            " cierre de la ventana\n (30 jul 2025)", color="#B3261E",
            fontsize=8, va="bottom", ha="left")
    ax.set_ylabel("Artefactos H1 (primera aparicion)")
    ax.set_xlabel("Mes")
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=7)
    fig.tight_layout()
    out = FIGDIR / "h1_adoption_curve.pdf"
    fig.savefig(out, metadata=PDF_METADATA)
    plt.close(fig)
    return out


def plot_cooccurrence_heatmap(report: dict) -> pathlib.Path:
    cooc = report["cooccurrence"]
    n = len(MECHS)
    diag = report["prevalence"]["by_stratum"]
    # Diagonal: total repos with the mechanism, pooled across strata, summing
    # the exact raw "k" counts (never back-derived from the rounded "pct"
    # field) -- matching the raw pair counts already used off-diagonal, NOT
    # reweighted, since this matrix describes the sampled corpus, not the
    # population.
    diag_counts = {}
    for m in MECHS:
        diag_counts[m] = sum(diag[st][m]["k"] for st in diag)

    mat = np.zeros((n, n), dtype=int)
    for i, a in enumerate(MECHS):
        for j, b in enumerate(MECHS):
            if i == j:
                mat[i, j] = diag_counts[a]
            elif i < j:
                key = f"{a}&{b}"
                mat[i, j] = mat[j, i] = cooc[key]

    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    im = ax.imshow(mat, cmap="Blues")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(MECHS)
    ax.set_yticklabels(MECHS)
    for i in range(n):
        for j in range(n):
            color = "white" if mat[i, j] > mat.max() * 0.6 else "black"
            weight = "bold" if i == j else "normal"
            ax.text(j, i, f"{mat[i, j]}", ha="center", va="center",
                    color=color, fontsize=9, fontweight=weight)
    ax.set_title("Coocurrencia entre mecanismos (n de repositorios)",
                  fontsize=9)
    fig.tight_layout()
    out = FIGDIR / "cooccurrence_heatmap.pdf"
    fig.savefig(out, metadata=PDF_METADATA)
    plt.close(fig)
    return out


def main() -> None:
    FIGDIR.mkdir(exist_ok=True)
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    p1 = plot_adoption_curve(report)
    p2 = plot_cooccurrence_heatmap(report)
    print(f"wrote {p1.relative_to(ROOT)} ({p1.stat().st_size} bytes)")
    print(f"wrote {p2.relative_to(ROOT)} ({p2.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
