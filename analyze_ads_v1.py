# -*- coding: utf-8 -*-
"""
analyze_ads.py — Google 广告报表数据分析工具（主脚本）
========================================================
业务场景：广告代理商日常处理 GA4 / Google Ads 导出的 CSV 报表，完成
    清洗 -> 指标计算 -> 问题广告筛选 -> 广告组汇总 -> 可视化

运行：python analyze_ads.py
输出（output/ 目录）：
  - ads_cleaned.csv           清洗并计算指标后的明细数据
  - adgroup_summary.csv       广告组维度汇总统计
  - high_spend_low_conv.csv   高消耗低转化广告（重点排查名单）
  - chart_*.png               可视化图表
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # 无界面环境渲染图片
import matplotlib.pyplot as plt
from pathlib import Path

# ====================== 0. 配置 ======================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUT_DIR = BASE_DIR / "output"
OUT_DIR.mkdir(exist_ok=True)

INPUT_FILE = DATA_DIR / "ads_report_2026Q3.csv"

# 业务规则：什么算“高消耗低转化”
SPEND_THRESHOLD = 1000.0    # 累计花费 >= 1000 美元
CVR_THRESHOLD = 0.01        # 转化率 < 1%
MIN_CLICKS = 100            # 至少有一定点击量，避免小样本误判


def main() -> None:
    # ====================== 1. 读取 ======================
    df = pd.read_csv(INPUT_FILE)
    print(f"[1] 读取 {INPUT_FILE.name}：{df.shape[0]:,} 行 × {df.shape[1]} 列")
    print(f"    原始重复行数：{df.duplicated().sum():,}")

    # ====================== 2. 数据清洗 ======================
    # 2.1 统一列名（去空格、转小写、下划线分隔）
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    # 2.2 删除完全重复的行（同广告同日重复导出）
    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    print(f"[2] 清洗：删除重复 {before - len(df):,} 行")

    # 2.3 日期类型转换
    df["date"] = pd.to_datetime(df["date"])

    # 2.4 负值处理：
    #     - 负花费：退款/数据修正，取绝对值并打标，方便后续审计
    #     - 负点击/转化：异常，按 0 处理
    df["cost_refunded"] = df["cost_usd"] < 0
    df["cost_usd"] = df["cost_usd"].abs()
    for col in ["clicks", "conversions"]:
        neg = df[col] < 0
        if neg.any():
            df.loc[neg, col] = 0

    # 2.5 缺失值处理（业务口径）：
    #     - 曝光/点击/转化缺失 -> 视为 0（当日无记录 / 无行为）
    #     - 花费缺失 -> 用「该广告组历史中位 CPC × 当日点击数」估算，并打标
    df["cost_imputed"] = False
    missing_cost = df["cost_usd"].isna()
    num_cols = ["impressions", "clicks", "conversions"]
    missing_before = df[num_cols].isna().sum().to_dict()
    df[num_cols] = df[num_cols].fillna(0).astype("int64")   # 计数列保持整数

    if missing_cost.any():
        unit_cpc = df["cost_usd"] / df["clicks"].replace(0, np.nan)   # 每行有效 CPC
        adgroup_median_cpc = unit_cpc.groupby(df["ad_group"]).median()
        df.loc[missing_cost, "cost_usd"] = (
            df.loc[missing_cost, "ad_group"].map(adgroup_median_cpc)
            * df.loc[missing_cost, "clicks"]
        )
        df.loc[missing_cost, "cost_imputed"] = True
        df["cost_usd"] = df["cost_usd"].fillna(0)                     # 兜底：仍无有效 CPC 的补 0
        print(f"    花费缺失 {int(missing_cost.sum()):,} 行，已按广告组中位 CPC 估算")
    print(f"    曝光/点击/转化缺失填充：{missing_before}")

    # 2.6 异常值标记（不删除，保留供人工复核；删除会丢失信息）
    p999 = df["cost_usd"].quantile(0.999)
    df["is_cost_outlier"] = df["cost_usd"] > p999
    print(f"    异常高花费行标记：{int(df['is_cost_outlier'].sum()):,} 行（> P99.9）")

    # ====================== 3. 指标计算 ======================
    # CTR = 点击 / 曝光；CPC = 花费 / 点击；CVR = 转化 / 点击
    # 分母为 0 时：CTR 记 0（无曝光无点击）；CPC / CVR 记 NaN（无点击时无意义）
    df["ctr"] = np.where(df["impressions"] > 0, df["clicks"] / df["impressions"], 0.0)
    df["cpc"] = np.where(df["clicks"] > 0, df["cost_usd"] / df["clicks"], np.nan)
    df["cvr"] = np.where(df["clicks"] > 0, df["conversions"] / df["clicks"], np.nan)
    print(f"[3] 指标计算完成：CTR / CPC / CVR 已添加到明细")

    # ====================== 4. 广告组汇总统计 ======================
    summary = df.groupby(["campaign", "ad_group"], as_index=False).agg(
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        conversions=("conversions", "sum"),
        cost_usd=("cost_usd", "sum"),
        days=("date", "nunique"),
    )
    # 汇总层指标（用合计值重算，避免“对平均再平均”）
    summary["ctr"] = summary["clicks"] / summary["impressions"].replace(0, np.nan)
    summary["cpc"] = summary["cost_usd"] / summary["clicks"].replace(0, np.nan)
    summary["cvr"] = summary["conversions"] / summary["clicks"].replace(0, np.nan)
    summary["spend_share"] = summary["cost_usd"] / summary["cost_usd"].sum()
    summary = summary.sort_values("cost_usd", ascending=False).reset_index(drop=True)
    print(f"[4] 广告组汇总：{len(summary)} 个广告组，按花费降序排列")

    # ====================== 5. 高消耗低转化筛选 ======================
    # 口径：累计花费 >= 阈值 且 转化率 < 阈值（0 转化也计入），并排除点击量过小的偶然样本
    flag = (
        (summary["cost_usd"] >= SPEND_THRESHOLD)
        & (summary["clicks"] >= MIN_CLICKS)
        & (summary["cvr"].fillna(0) < CVR_THRESHOLD)
    )
    bad = summary[flag].sort_values("cost_usd", ascending=False).reset_index(drop=True)
    bad_keys = set(zip(bad["campaign"], bad["ad_group"]))
    summary["is_high_spend_low_conv"] = [
        k in bad_keys for k in zip(summary["campaign"], summary["ad_group"])
    ]
    print(f"[5] 高消耗低转化广告组：{len(bad)} 个")
    for _, r in bad.iterrows():
        print(f"      - {r['ad_group']:<28} 花费 ${r['cost_usd']:>10,.0f}  "
              f"点击 {r['clicks']:>6,} 转化 {r['conversions']:>4} "
              f"CVR {r['cvr']:.2%}")

    # ====================== 6. 输出 CSV ======================
    detail_cols = ["date", "campaign", "ad_group", "impressions", "clicks",
                   "conversions", "cost_usd", "ctr", "cpc", "cvr",
                   "cost_imputed", "cost_refunded", "is_cost_outlier"]
    df[detail_cols].to_csv(OUT_DIR / "ads_cleaned.csv", index=False)
    summary.to_csv(OUT_DIR / "adgroup_summary.csv", index=False)
    bad.to_csv(OUT_DIR / "high_spend_low_conv.csv", index=False)
    print(f"[6] 输出 CSV 完成 -> {OUT_DIR}/")

    # ====================== 7. 可视化 ======================
    try:
        plt.style.use("seaborn-v0_8-whitegrid")
    except Exception:
        plt.style.use("ggplot")
    plt.rcParams.update({"figure.dpi": 150, "savefig.bbox": "tight", "font.size": 9})

    # 7.1 Top10 广告组：花费柱状 + 转化率折线（双轴）
    top = summary.head(10)
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.bar(top["ad_group"], top["cost_usd"], color="#4285F4", label="Spend (USD)")
    ax1.set_ylabel("Spend (USD)")
    ax1.set_title("Top 10 Ad Groups by Spend, with Conversion Rate")
    ax2 = ax1.twinx()
    ax2.plot(top["ad_group"], top["cvr"] * 100, color="#EA4335",
             marker="o", label="Conversion Rate (%)")
    ax2.set_ylabel("Conversion Rate (%)")
    ax1.set_xticks(range(len(top)))
    ax1.set_xticklabels(top["ad_group"], rotation=30, ha="right")
    fig.legend(loc="upper left", bbox_to_anchor=(0.12, 0.90), fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "chart_adgroup_spend_cvr.png")
    plt.close(fig)

    # 7.2 散点：广告组花费 vs 转化（红色高亮高消耗低转化）
    fig, ax = plt.subplots(figsize=(9, 6))
    norm = summary[~summary["is_high_spend_low_conv"]]
    flagged = summary[summary["is_high_spend_low_conv"]]
    ax.scatter(norm["cost_usd"], norm["conversions"], s=45, alpha=0.65,
               color="#4285F4", label="Normal ad groups")
    ax.scatter(flagged["cost_usd"], flagged["conversions"], s=90,
               color="#EA4335", edgecolor="black", linewidth=0.8,
               label="High-spend / Low-conversion")
    ax.set_xlabel("Total Spend (USD)")
    ax.set_ylabel("Total Conversions")
    ax.set_title("Ad Group Level: Spend vs Conversions")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "chart_spend_vs_conversions.png")
    plt.close(fig)

    # 7.3 各 Campaign 的每日花费趋势（模拟“日报”视角）
    daily = df.groupby(["date", "campaign"], as_index=False)["cost_usd"].sum()
    pivot = daily.pivot(index="date", columns="campaign", values="cost_usd").fillna(0)
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for col in pivot.columns:
        ax.plot(pivot.index, pivot[col], linewidth=1.4, label=col)
    ax.set_xlabel("Date")
    ax.set_ylabel("Daily Spend (USD)")
    ax.set_title("Daily Spend Trend by Campaign (Q3 2026)")
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "chart_daily_spend_trend.png")
    plt.close(fig)
    print(f"[7] 可视化完成：{len(list(OUT_DIR.glob('chart_*.png')))} 张图表")

    # ====================== 8. 控制台摘要 ======================
    print("\n========== 分析摘要 ==========")
    print(f"总花费    : ${summary['cost_usd'].sum():,.2f}")
    print(f"总曝光    : {summary['impressions'].sum():,}")
    print(f"总点击    : {summary['clicks'].sum():,}")
    print(f"总转化    : {summary['conversions'].sum():,}")
    print(f"整体 CTR  : {summary['clicks'].sum() / summary['impressions'].sum():.2%}")
    print(f"整体 CPC  : ${summary['cost_usd'].sum() / summary['clicks'].sum():.2f}")
    print(f"整体 CVR  : {summary['conversions'].sum() / summary['clicks'].sum():.2%}")
    print(f"高消耗低转化广告组: {len(bad)} 个")
    print(f"全部输出 -> {OUT_DIR}/")


if __name__ == "__main__":
    main()
