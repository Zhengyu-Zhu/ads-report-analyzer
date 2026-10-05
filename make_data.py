# -*- coding: utf-8 -*-
"""
make_data.py — 生成模拟 Google Ads 广告报表数据
===================================================
业务场景：模拟广告代理商日常从 GA4 / Google Ads 导出的日报表。

刻意注入真实数据中常见的“脏”情况，让清洗步骤有意义：
  - 重复行（同广告同日重复导出）
  - 缺失值（曝光 / 点击 / 花费漏传）
  - 负花费（退款 / 数据修正）
  - 极端值（个别广告单日异常高消耗）
  - 一个表现差的广告组（高消耗、低转化），供后续筛选演示

运行：python make_data.py
输出：data/ads_report_2026Q3.csv
"""

import numpy as np
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def main(seed: int = 42) -> None:
    rng = np.random.default_rng(seed)

    # 模拟一家代理商的账户结构：3 个 Campaign × 每个 2-3 个 Ad Group
    # 每个广告组配置：CTR 基准、单次点击成本、转化率基准
    campaigns = {
        "Brand_Search": {
            "Brand_Core":            {"ctr_base": 0.045, "cpc": 0.60, "cvr_base": 0.050},
            "Brand_Expanded":        {"ctr_base": 0.035, "cpc": 0.55, "cvr_base": 0.040},
        },
        "NonBrand_Prospecting": {
            "Prospecting_Generic":   {"ctr_base": 0.022, "cpc": 1.10, "cvr_base": 0.025},
            "Prospecting_Competitor":{"ctr_base": 0.015, "cpc": 1.60, "cvr_base": 0.015},
        },
        "Remarketing_Dynamic": {
            "Remarketing_All_Visitors":  {"ctr_base": 0.028, "cpc": 0.85, "cvr_base": 0.035},
            "Remarketing_Cart_Abandon":  {"ctr_base": 0.033, "cpc": 1.05, "cvr_base": 0.060},
            "Remarketing_Purchasers":    {"ctr_base": 0.030, "cpc": 0.95, "cvr_base": 0.045},
        },
    }
    # 表现差的广告组：高曝光、高消耗、转化率极低 -> 会被筛选逻辑抓出来
    bad_group_cfg = {"ctr_base": 0.008, "cpc": 2.30, "cvr_base": 0.002}

    dates = pd.date_range("2026-07-01", "2026-09-30", freq="D")

    rows = []
    for campaign, groups in campaigns.items():
        for ad_group, cfg in groups.items():
            for d in dates:
                impressions = int(rng.integers(3_000, 40_000))
                clicks = max(int(impressions * rng.normal(cfg["ctr_base"], 0.004)), 0)
                cost = clicks * rng.normal(cfg["cpc"], 0.10)
                conversions = rng.poisson(clicks * cfg["cvr_base"])
                rows.append([d.date(), campaign, ad_group, impressions, clicks,
                             conversions, round(cost, 2)])

    # 表现差的广告组（单独插入，制造“高消耗低转化”样本）
    for d in dates:
        impressions = int(rng.integers(20_000, 45_000))
        clicks = int(impressions * bad_group_cfg["ctr_base"])
        cost = clicks * bad_group_cfg["cpc"]
        conversions = rng.poisson(clicks * bad_group_cfg["cvr_base"])
        rows.append([d.date(), "Legacy_Display", "Display_Legacy_Placements",
                     impressions, clicks, conversions, round(cost, 2)])

    df = pd.DataFrame(rows, columns=[
        "date", "campaign", "ad_group", "impressions",
        "clicks", "conversions", "cost_usd"])
    
    unit_price = np.maximum(rng.normal(120,30,size=len(df)),0)
    df['conversion_value'] = (df['conversions'] * unit_price).round(2)

    # ---------------- 注入脏数据 ----------------
    # 1) 重复行：约 1.5% 的行重复（模拟重复导出）
    dup = df.sample(frac=0.015, random_state=rng)
    df = pd.concat([df, dup], ignore_index=True)

    # 2) 缺失值：曝光 / 点击 / 花费随机缺失
    m = rng.random(len(df))
    df.loc[m < 0.020, "impressions"] = np.nan
    df.loc[(m >= 0.020) & (m < 0.035), "clicks"] = np.nan
    df.loc[(m >= 0.035) & (m < 0.045), "cost_usd"] = np.nan

    # 3) 负花费：约 1%（模拟退款）
    refund = rng.random(len(df)) < 0.01
    df.loc[refund, "cost_usd"] = -df.loc[refund, "cost_usd"].abs()

    # 4) 极端值：约 0.5% 的行单日花费异常放大（模拟异常消耗）
    spike = rng.random(len(df)) < 0.005
    df.loc[spike, "cost_usd"] = df.loc[spike, "cost_usd"] * rng.uniform(6, 10, size=spike.sum())

    # 打乱顺序，模拟真实导出顺序
    df = df.sample(frac=1.0, random_state=rng).reset_index(drop=True)

    out = DATA_DIR / "ads_report_2026Q3.csv"
    df.to_csv(out, index=False)
    print(f"已生成 {out}，共 {len(df):,} 行 × {df.shape[1]} 列")
    print(f"时间范围：{df['date'].min()} ~ {df['date'].max()}")


if __name__ == "__main__":
    main()
