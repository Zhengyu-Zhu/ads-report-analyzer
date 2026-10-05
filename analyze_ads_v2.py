# -*- coding: utf-8 -*-
"""
Google Ads 报表数据分析工具 v2
================================
业务场景：模拟广告代理商日常 GA4 / Google Ads 报表分析。

v1 -> v2 升级：
  1. 数据层：make_data.py 新增 conversion_value 列（客单价 normal(120,30) 波动）
  2. 指标层：summary 新增 cpa（CPA=花费/转化，转化=0 时为 NaN）、
            roas（ROAS=转化价值/花费，花费=0 时为 NaN）
  3. 决策层：用四象限（ROAS 口径）取代原"高消耗低转化"（CVR 口径）二分类：
            star      高消耗 × ROAS>=盈亏线  -> 增长组，加预算
            burn      高消耗 × ROAS<盈亏线   -> 烧钱组，止损
            potential 低消耗 × ROAS>=盈亏线  -> 潜力组，小预算测试
            watch     其余                    -> 观察
            盈亏线 = 1/毛利率（本脚本 0.4 -> 2.5）
  4. 图表层：四象限气泡图取代原"花费 vs 转化"散点图

用法：python analyze_ads_v2.py
输出：output/ 下 4 个 CSV + 3 张图
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # 无界面环境渲染图片（本地跑可删这行）
import matplotlib.pyplot as plt
from pathlib import Path

# ========== 第 0 节：配置（业务规则集中在此，修改前先确认业务口径） ==========
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUT_DIR = BASE_DIR / "output"
OUT_DIR.mkdir(exist_ok=True)

INPUT_FILE = DATA_DIR / "ads_report_2026Q3.csv"

SPEND_THRESHOLD = 1000.0  # 高消耗判定：单组花费 >= $1,000
MIN_CLICKS = 100          # 最小样本量：排除小样本组，避免误判
GROSS_MARGIN = 0.4        # 毛利率（财务提供）：盈亏线 ROAS = 1/0.4 = 2.5

BREAKEVEN_ROAS = 1 / GROSS_MARGIN

# ========== 第 1-2 节：读取与清洗 ==========
df = pd.read_csv(INPUT_FILE)
print(f"[1] 读取 {INPUT_FILE.name}: {df.shape[0]:,} 行 x {df.shape[1]} 列")
print(f"    原始重复行数：{df.duplicated().sum():,}")

# 2.1 统一列名
df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

# 2.2 删除完全重复的行
before = len(df)
df = df.drop_duplicates().reset_index(drop=True)
print(f"[2] 清洗：删除重复 {before - len(df):,} 行")

# 2.3 日期类型转换
df["date"] = pd.to_datetime(df["date"])

# 2.4 负值处理
df["cost_refunded"] = df["cost_usd"] < 0
df["cost_usd"] = df["cost_usd"].abs()
for col in ["clicks", "conversions"]:
    neg = df[col] < 0
    if neg.any():
        df.loc[neg, col] = 0  # 负点击/负转化视为异常，按 0 处理

# 2.5 缺失值处理
df["cost_imputed"] = False
missing_cost = df["cost_usd"].isna()
num_cols = ["impressions", "clicks", "conversions"]
missing_before = df[num_cols].isna().sum().to_dict()
df[num_cols] = df[num_cols].fillna(0).astype("int64")  # 计数列保持整数

if missing_cost.any():
    unit_cpc = df["cost_usd"] / df["clicks"].replace(0, np.nan)  # 每行有效 CPC
    adgroup_median_cpc = unit_cpc.groupby(df["ad_group"]).median()
    df.loc[missing_cost, "cost_usd"] = (
        df.loc[missing_cost, "ad_group"].map(adgroup_median_cpc)
        * df.loc[missing_cost, "clicks"]
    )
    df.loc[missing_cost, "cost_imputed"] = True
    df["cost_usd"] = df["cost_usd"].fillna(0)
    print(f"    花费缺失 {int(missing_cost.sum()):,} 行，已按广告组中位 CPC 估算")
print(f"    曝光/点击/转化缺失填充：{missing_before}")

# 2.6 异常值：只标记，不删除
p999 = df["cost_usd"].quantile(0.999)
df["is_cost_outlier"] = df["cost_usd"] > p999
print(f"    异常高花费行标记：{int(df['is_cost_outlier'].sum()):,} 行（>P99.9）")

# ========== 第 3 节：明细指标计算 ==========
df["ctr"] = np.where(df["impressions"] > 0, df["clicks"] / df["impressions"], 0.0)
df["cpc"] = np.where(df["clicks"] > 0, df["cost_usd"] / df["clicks"], np.nan)
df["cvr"] = np.where(df["clicks"] > 0, df["conversions"] / df["clicks"], np.nan)
print("[3] 指标计算完成：CTR / CPC / CVR 已添加到明细")

# ========== 第 4 节：广告组汇总（组合键 campaign + ad_group 保证唯一） ==========
summary = df.groupby(["campaign", "ad_group"], as_index=False).agg(
    impressions=("impressions", "sum"),
    clicks=("clicks", "sum"),
    conversions=("conversions", "sum"),
    cost_usd=("cost_usd", "sum"),
    conversion_value=("conversion_value", "sum"),
    days=("date", "nunique"),
)
summary["ctr"] = summary["clicks"] / summary["impressions"].replace(0, np.nan)
summary["cpc"] = summary["cost_usd"] / summary["clicks"].replace(0, np.nan)
summary["cvr"] = summary["conversions"] / summary["clicks"].replace(0, np.nan)
# CPA：转化数为 0 -> NaN（无定义）；ROAS：花费为 0 -> NaN（无定义）
summary["cpa"] = summary["cost_usd"] / summary["conversions"].replace(0, np.nan)
summary["roas"] = summary["conversion_value"] / summary["cost_usd"].replace(0, np.nan)
summary["spend_share"] = summary["cost_usd"] / summary["cost_usd"].sum()
summary = summary.sort_values("cost_usd", ascending=False).reset_index(drop=True)
print(f"[4] 广告组汇总：{len(summary)} 个广告组，按花费降序排列")

# ========== 第 5 节：四象限分类（ROAS 口径） ==========
summary["quadrant"] = np.select(
    [
        (summary["cost_usd"] >= SPEND_THRESHOLD)
        & (summary["clicks"] >= MIN_CLICKS)
        & (summary["roas"] >= BREAKEVEN_ROAS),
        (summary["cost_usd"] >= SPEND_THRESHOLD)
        & (summary["clicks"] >= MIN_CLICKS)
        & (summary["roas"] < BREAKEVEN_ROAS),
        (summary["cost_usd"] < SPEND_THRESHOLD)
        & (summary["clicks"] >= MIN_CLICKS)
        & (summary["roas"] >= BREAKEVEN_ROAS),
    ],
    ["star", "burn", "potential"],
    default="watch",
)

print(f"[5] 四象限分类：star {int((summary['quadrant']=='star').sum())} / "
      f"burn {int((summary['quadrant']=='burn').sum())} / "
      f"potential {int((summary['quadrant']=='potential').sum())}")
for q in ["star", "burn", "potential"]:
    group = summary[summary["quadrant"] == q]
    print(f"=== {q}组（{len(group)}个）===")
    for _, r in group.iterrows():
        print(f"    - {r['campaign']:<28} {r['ad_group']:<28} "
              f"花费 ${r['cost_usd']:>10,.0f}  点击 {r['clicks']:>6,} "
              f"转化 {r['conversions']:>4}  ROAS {r['roas']:.2f}")

# ========== 第 6 节：输出 CSV（utf-8-sig：Excel 打开中文不乱码） ==========
detail_cols = ["date", "campaign", "ad_group", "impressions", "clicks",
               "conversions", "cost_usd", "ctr", "cpc", "cvr",
               "cost_imputed", "cost_refunded", "is_cost_outlier"]
df[detail_cols].to_csv(OUT_DIR / "ads_cleaned.csv", index=False, encoding="utf-8-sig")


def action(q):
    if q == "star":
        return "Increase budget 20% (scale up)"
    if q == "burn":
        return "Cut budget 50% or pause; optimize creatives/bids"
    if q == "potential":
        return "Test with small budget"
    return "Monitor"


summary["recommended_action"] = summary["quadrant"].map(action)
summary.to_csv(OUT_DIR / "adgroup_summary.csv", index=False, encoding="utf-8-sig")

burn = summary[summary["quadrant"] == "burn"].sort_values("cost_usd", ascending=False)
burn.to_csv(OUT_DIR / "burn_groups.csv", index=False, encoding="utf-8-sig")

star = summary[summary["quadrant"] == "star"].sort_values("cost_usd", ascending=False)
star.to_csv(OUT_DIR / "star_groups.csv", index=False, encoding="utf-8-sig")
print(f"[6] 输出 CSV 完成 -> {OUT_DIR}/")

# ========== 第 7 节：可视化 ==========
try:
    plt.style.use("seaborn-v0_8-whitegrid")
except Exception:
    plt.style.use("ggplot")
plt.rcParams.update({"figure.dpi": 150, "savefig.bbox": "tight", "font.size": 9})

# 图 1：Top 广告组 花费柱状 + 转化率折线（双轴）
top = summary.head(10)
fig, ax1 = plt.subplots(figsize=(12, 5))
ax1.bar(top["ad_group"], top["cost_usd"], color="#4285F4", label="Spend (USD)", width=0.6)
ax1.set_ylabel("Spend (USD)", fontsize=10)
ax1.set_title("Top 10 Ad Groups by Spend, with Conversion Rate", fontsize=15, pad=15)
ax1.tick_params(axis="y", labelsize=10)
ax2 = ax1.twinx()
ax2.plot(top["ad_group"], top["cvr"] * 100, color="#EA4335", marker="o",
         label="Conversion Rate(%)")
ax2.set_ylabel("Conversion Rate(%)", fontsize=10)
ax2.tick_params(axis="y", labelsize=10)
ax1.set_xticks(range(len(top)))
ax1.set_xticklabels(top["ad_group"], rotation=30, ha="right", fontsize=10)
fig.legend(loc="upper right", bbox_to_anchor=(0.95, 0.93), fontsize=8)
fig.tight_layout()
fig.savefig(OUT_DIR / "chart_adgroup_spend_cvr.png")
plt.close(fig)

# 图 2：四象限气泡图（取代原"花费 vs 转化"散点）
color_map = {"star": "#0072B2", "burn": "#E69F00",
             "potential": "#009E73", "watch": "#999999"}  # Okabe-Ito 色盲安全色板
fig, ax = plt.subplots(figsize=(10, 6))
for q in ["star", "burn", "potential", "watch"]:
    sub = summary[summary["quadrant"] == q]
    if sub.empty:
        continue
    ax.scatter(sub["cost_usd"], sub["roas"],
               s=(sub["conversions"] / summary["conversions"].max()) * 600 + 50,
               c=color_map[q], label=q, alpha=0.8,
               edgecolors="black", linewidths=0.5)

ax.axhline(BREAKEVEN_ROAS, color="#D55E00", linestyle="--")
ax.text(50000, 2.7, f"Breakeven ROAS={BREAKEVEN_ROAS:.1f}", color="#D55E00", fontsize=8)
ax.axvline(SPEND_THRESHOLD, color="#666666", linestyle="--")
ax.text(SPEND_THRESHOLD + 500, 9.5, f"SPEND THRESHOLD ${SPEND_THRESHOLD:,.0f}",
        color="#666666", fontsize=8)
ax.set_xlim(0, 70000)
ax.set_ylim(-0.25, 10)
ax.set_xlabel("Spend (USD)")
ax.set_ylabel("ROAS")
ax.legend(fontsize=8, markerscale=0.3)
ax.set_title("Ad Group ROAS vs. Spend - 2026 Q3", fontsize=12, pad=10)

for _, r in summary[summary["quadrant"] == "burn"].iterrows():
    ax.text(r["cost_usd"], r["roas"] + 0.3, f"{r['roas']:.2f}", fontsize=8, ha="center")
for _, r in summary[summary["quadrant"] == "star"].iterrows():
    ax.text(r["cost_usd"], r["roas"] + 0.4, f"{r['roas']:.2f}", fontsize=8, ha="center")
fig.tight_layout()
fig.savefig(OUT_DIR / "chart_adgroup_roas_vs_spend_2026Q3.png")
plt.close(fig)

# 图 3：各 Campaign 每日花费趋势
daily = df.groupby(["date", "campaign"], as_index=False)["cost_usd"].sum()
pivot = daily.pivot(index="date", columns="campaign", values="cost_usd").fillna(0)
fig, ax = plt.subplots(figsize=(11, 4.5))
for col in pivot.columns:
    ax.plot(pivot.index, pivot[col], linewidth=1.4, label=col)
ax.set_xlabel("Date", fontsize=10)
ax.set_ylabel("Cost_usd Sum", fontsize=10)
ax.set_title("Daily Spend Trend by Campaign (Q3 2026)", fontsize=15, pad=15)
ax.legend(ncol=2, fontsize=10)
fig.tight_layout()
fig.savefig(OUT_DIR / "chart_daily_spend_trend.png")
plt.close(fig)
print(f"[7] 可视化完成：{len(list(OUT_DIR.glob('chart_*.png')))} 张图表")

# ========== 第 8 节：控制台摘要 ==========
print("\n========== 分析摘要 ==========")
print(f"总花费  ：${summary['cost_usd'].sum():,.2f}")
print(f"总曝光  ：{summary['impressions'].sum():,}")
print(f"总点击  ：{summary['clicks'].sum():,}")
print(f"总转化  ：{summary['conversions'].sum():,}")
print(f"整体CTR：{summary['clicks'].sum() / summary['impressions'].sum():.2%}")
print(f"整体CPC：${summary['cost_usd'].sum() / summary['clicks'].sum():.2f}")
print(f"整体CVR：{summary['conversions'].sum() / summary['clicks'].sum():.2%}")
for q in ["star", "burn", "potential"]:
    group = summary[summary["quadrant"] == q]
    print(f"{q}组: {len(group)}个")
print(f"全部输出 -> {OUT_DIR}/")
