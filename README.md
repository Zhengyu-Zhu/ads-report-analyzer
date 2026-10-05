# Google Ads Report Analyzer (Pandas)

A daily-report analysis toolkit that simulates an **ad-agency workflow**: ingest a raw Google Ads / GA4-style CSV, clean it, compute KPIs, classify ad groups into decision quadrants, and export summary CSVs + charts.

> **Business context**: Ad agencies pull Google Ads / GA4 reports every day and need quick answers to three questions — (1) Is the data clean? (2) Where is money spent and does it pay back? (3) Which ad groups are burning budget below the profitability line and need action? This project automates that loop with pandas.

---

## What's New in v2

| Change | Detail |
|---|---|
| **Data layer** | `make_data.py` now generates a `conversion_value` column (unit price drawn from `Normal(120, 30)`, so average order value varies realistically) |
| **New KPIs** | `cpa` (cost per acquisition) and `roas` (return on ad spend) at ad-group level; division-by-zero handled with `NaN` |
| **Decision layer** | Upgraded from a binary "high-spend / low-CVR" rule to a **four-quadrant ROAS classification** with a break-even line (`ROAS = 1 / gross margin`) |
| **New outputs** | `star_groups.csv`, `burn_groups.csv`, and a **quadrant bubble chart** (replaces the old spend-vs-conversions scatter) |
| **Actionability** | New `recommended_action` column translates metrics into concrete next steps for the client |

---

## Directory Structure

```
project/
├── make_data.py              # Generates simulated ad report data (with dirty data)
├── analyze_ads_v1.py         # v1 analysis script (kept for reference)
├── analyze_ads_v2.py         # v2 main script: cleaning / KPIs / quadrant / charts
├── requirements.txt
├── README.md
├── data/
│   └── ads_report_2026Q3.csv # Simulated raw report (auto-generated)
└── output/                   # Auto-generated after running
    ├── ads_cleaned.csv
    ├── adgroup_summary.csv
    ├── burn_groups.csv
    ├── star_groups.csv
    ├── chart_adgroup_spend_cvr.png
    ├── chart_adgroup_roas_vs_spend_2026Q3.png
    └── chart_daily_spend_trend.png
```

---

## Quick Start

```bash
# 1. Install dependencies (a virtual environment is recommended)
pip install -r requirements.txt

# 2. Generate simulated data (includes duplicates, missing values, negatives, outliers)
python make_data.py

# 3. Run the v2 analysis
python analyze_ads_v2.py
```

After the run, `output/` contains **4 CSVs and 3 charts**, and the console prints an analysis summary.

---

## Simulated Data

`make_data.py` simulates 3 campaigns / 8 ad groups / 92 days (2026 Q3) of daily reporting for an agency, and **deliberately injects the dirty-data patterns seen in real reports**:

| Dirty-data type | Ratio | Real-world cause |
|---|---|---|
| Duplicate rows | ~1.5% | Same ad exported twice on the same day |
| Missing impressions / clicks / cost | ~1-2% | Tracking / feed loss |
| Negative cost | ~1% | Refunds / billing corrections |
| Outlier high cost | ~0.5% | Budget runaway / tracking error |
| Budget-burning ad group | 1 | A legacy group that the screening logic must catch |

> A random seed (`seed=42`) keeps the data reproducible. Note: reproducibility also requires the **random-call sequence to stay unchanged** — any inserted/removed `rng.*` call shifts all downstream values (a good interview talking point).

---

## Cleaning & Metric Definitions

### Cleaning decisions
- **Duplicates**: dropped (`drop_duplicates`).
- **Missing values**:
  - impressions / clicks / conversions → fill with 0 ("no record = no activity").
  - **cost → estimate as `ad-group median CPC × clicks`**, flagged via `cost_imputed`. Rationale: filling with 0 understates spend; deleting rows loses information.
  - Remaining `NaN` (ad group has no valid CPC sample) → filled with 0 as a conservative fallback.
- **Negatives**: negative cost = refund → take absolute value + `cost_refunded` flag; negative clicks / conversions set to 0.
- **Outliers**: flagged only (`is_cost_outlier`), never silently deleted — real business requires human review.

### Metrics (note division-by-zero handling)

| Metric | Formula | When denominator = 0 |
|---|---|---|
| CTR | clicks / impressions | 0 |
| CPC | cost / clicks | NaN |
| CVR | conversions / clicks | NaN |
| **CPA** | cost / conversions | **NaN** (conversions=0 → undefined) |
| **ROAS** | conversion value / cost | **NaN** (cost=0 → undefined) |

---

## Decision Framework: Four Quadrants (ROAS-based)

| Quadrant | Condition | Action |
|---|---|---|
| ⭐ **star** | spend ≥ $1,000, clicks ≥ 100, ROAS ≥ break-even | Increase budget ~20% |
| 🔥 **burn** | spend ≥ $1,000, clicks ≥ 100, ROAS < break-even | Cut budget or pause; optimize creatives/bids |
| 🌱 **potential** | spend < $1,000, ROAS ≥ break-even | Test with small budget |
| ⚪ **watch** | everything else | Monitor |

**Break-even ROAS = 1 / gross margin** (0.4 in this project → **2.5**). Spending $1 on ads must return at least $2.5 in revenue to cover the 60% cost of goods.

**Why ROAS instead of CVR?** CVR ignores order value; ROAS captures it. Example from this dataset: `Prospecting_Competitor` has a CVR of 1.55% (looks "normal"), but ROAS of 1.13 — **below the 2.5 break-even, so it is actually losing money** at a 40% gross margin. The CVR-based rule would have missed it.

---

## Outputs

| File | Content | Business use |
|---|---|---|
| `ads_cleaned.csv` | Cleaned detail + CTR/CPC/CVR + flag columns | Auditable data source |
| `adgroup_summary.csv` | Ad-group summary + CPA/ROAS + quadrant + recommended action | Weekly report / budget decisions |
| `burn_groups.csv` | Groups below break-even | Immediate optimization list |
| `star_groups.csv` | Profitable groups above break-even | Growth / budget-increase list |
| `chart_adgroup_spend_cvr.png` | Top ad groups: spend bar + CVR line (dual axis) | One-page executive view |
| `chart_adgroup_roas_vs_spend_2026Q3.png` | Quadrant bubble chart (size = conversions, color = quadrant) | At-a-glance "who earns / who burns" |
| `chart_daily_spend_trend.png` | Daily spend trend by campaign | Daily monitoring |

---

## Why This Matters for the Target Role (gTech / Agency Cloud Architect)

1. **Pipeline thinking**: dirty data → structured decisions mirrors the ETL role of BigQuery / Dataflow / Cloud Storage (a mini version of a cloud data pipeline).
2. **Business-metric governance**: defining CTR/CPC/CVR/CPA/ROAS and the break-even threshold is exactly the kind of metric-consistency work gTech does when supporting advertisers.
3. **Auditability**: every cleaning decision leaves a flag (`cost_imputed` / `cost_refunded` / `is_cost_outlier`) — "traceable data" awareness.
4. **Decision-oriented output**: ships "problem list + action list + charts", not raw data — what an agency cloud analyst does daily: turn data into client decisions.

### 30-second interview pitch
> "I built a pandas pipeline that mimics a daily ad-agency reporting loop. v2 upgraded the screening logic from CVR to ROAS: CVR ignores order value, so a group with 1.55% CVR and ROAS 1.13 looked fine but was actually losing money below the 2.5 break-even at a 40% gross margin. The output is a quadrant chart plus star/burn lists with recommended actions."

---

## Roadmap

- [ ] Pull data via Google Ads API / GA4 API instead of manual CSV export
- [ ] Scheduled runs (cron / Cloud Scheduler + Cloud Functions) for daily reports
- [ ] Load results into BigQuery and build a Looker Studio dashboard
- [ ] Add anomaly detection (e.g., z-score alerts on spend spikes)
- [ ] Unit tests (pytest) to lock cleaning & metric logic

---

## Environment

- Python 3.9+
- pandas ≥ 2.0, numpy ≥ 1.24, matplotlib ≥ 3.7
