"""
run_final_report.py
精确构造 ATR%=6.73% 高波动场景，生成完整 v6 最终报告
"""

import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from patch_indicators_v3 import compute_extra_indicators
from market_filter_v3 import format_env_report

np.random.seed(42)

# ---------- 精确构造 ATR%≈6.73% ----------
n = 120
# 大振幅 + 上行趋势
amp_noise = np.random.normal(0, 3.0, n)
trend = np.linspace(0, 10, n)
base = 82 + trend + amp_noise.cumsum() * 0.25
base[-20:] += np.linspace(0, 6, 20)  # 末端加速

dates = pd.date_range("2026-03-01", periods=n, freq="B")
df = pd.DataFrame({
    "date":  dates.strftime("%Y-%m-%d"),
    "open":  np.clip(base + np.random.normal(0, 0.6, n), 80, 105),
    "high":  np.clip(base + np.abs(np.random.normal(2.0, 1.0, n)), 82, 110),
    "low":   np.clip(base - np.abs(np.random.normal(2.0, 1.0, n)), 78, 105),
    "close": np.clip(base + np.random.normal(0, 0.5, n), 80, 105),
    "volume": np.random.randint(1_000_000, 6_000_000, n),
})
# 末端精确匹配华曙高科真实收盘价 91.88 + 缩量小跌
n = len(df)
df.loc[n-1, "close"]  = 91.88
df.loc[n-1, "open"]   = 92.20
df.loc[n-1, "high"]   = 92.50
df.loc[n-1, "low"]    = 91.30
df.loc[n-1, "volume"] = 1_200_000

extra = compute_extra_indicators(df)

print("=" * 62)
print("  华曙高科(688433) v6 最终验证")
print("=" * 62)
print(f"  最新价: {extra['price']}  当日: {extra['chg_pct']}%")
print(f"  ATR14: {extra['atr14']}  ATR%: {extra['atr_pct']}%  → {extra['vol_level']}")
print(f"  量比: {extra['vol_ratio']}  量价: {extra['vol_price_state']}")
print(f"  BOLL: 上{extra['boll']['upper']}/中{extra['boll']['mid']}/下{extra['boll']['lower']}")
print(f"  BOLL宽度分位: {extra['boll']['width_pct_rank']} → {extra['boll']['width_label']}")
print(f"  KDJ: K={extra['kdj']['K']} D={extra['kdj']['D']} J={extra['kdj']['J']} {extra['kdj']['zone']}")
print(f"  MACD: DIF={extra['macd']['DIF']} DEA={extra['macd']['DEA']} {extra['macd']['zone']} {extra['macd']['cross']}")
print(f"  零轴纠缠: {extra['zero_tangled']}")

t = extra['targets']
print(f"\n  止损: {t['stop_loss']}  Stage1: {t['stage1_price']}  Stage2: {t['stage2_price']}")
print(f"  支撑1: {t['support1']}  支撑2: {t['support2']}")
print(f"  压力1: {t['resistance1']}  压力2: {t['resistance2']}")
print(f"  买入区间: {t['buy_zone']}")

# 高波动验证
assert extra['atr_pct'] > 4, f"ATR%={extra['atr_pct']}% 应>4%"
assert t['stop_loss'] < extra['price']
assert t['stage1_price'] > t['stage2_price'] > t['stop_loss']
print("\n  ✅ 高波动分支全部通过")

# ---------- 模拟 bull 环境 ----------
env_result = {
    "code": "688433", "market": "科创板", "industry": "半导体",
    "environment": "bull", "allow_trend_following": True, "allow_any_long": True,
    "details": {
        "layer1": {"a_indices": {"上证指数": True, "创业板指": True, "中证1000": True},
                    "a_above_count": 3, "a_adv_dec_ratio": 1.87,
                    "hk_hsi_above": True, "hk_adv_dec_ratio": 1.59},
        "layer2_style_above_ma20": True,
        "layer3_industry": {"above_ma20": True, "ma20_slope_up": True,
                            "relative_strength": True, "fund_inflow": True,
                            "industry": "半导体", "error": None},
    },
}
env_text = format_env_report(env_result)

# ---------- 组装最终报告 ----------
price = extra['price']
atr14 = extra['atr14']
atr_pct = extra['atr_pct']
boll = extra['boll']
kdj = extra['kdj']
macd = extra['macd']
rsi = extra['rsi']
vp = extra['vol_price_state']
dense = extra['dense_zone']

# 周期判定
if extra['zero_tangled']:
    period = "中线波段网格(1-4周)"
    reason = f"DIF零轴纠缠(dif_zero_dist_atr={macd['dif_zero_dist_atr']})+J={kdj['J']}中性+BOLL{boll['width_label']}→趋势启动初期，顺势做多"
elif kdj['J'] > 90:
    period = "超短线博弈(1-3天)"
    reason = f"J={kdj['J']}超买+{vp}，适合超短线博弈捕捉回调"
else:
    period = "中线波段网格(1-4周)"
    reason = f"三层环境全bull+DIF={macd['DIF']}金叉↑+BOLL{boll['width_label']}→顺势做多"

# 共振
bull_s, bear_s = [], []
if "金叉" in macd['cross']: bull_s.append("MACD金叉↑")
if "加速" in boll['shape'] or "加速" in boll['width_label']: bull_s.append("BOLL张口")
if kdj['J'] < 10: bull_s.append("KDJ超卖")
if kdj['J'] > 90: bear_s.append("KDJ超买")
if "死叉" in macd['cross']: bear_s.append("MACD死叉↓")
if boll['width_pct_rank'] and boll['width_pct_rank'] <= 0.20: bull_s.append("BOLL极致收口蓄势")
if bull_s and not bear_s: resonance = " + ".join(bull_s) + " = 多头共振✅"
elif bear_s and not bull_s: resonance = " + ".join(bear_s) + " = 空头共振⚠️"
else: resonance = "信号矛盾，待观察"

loss_pct = (t['stop_loss'] / price - 1) * 100
up_pct = (t['resistance2'] / price - 1) * 100
rr = up_pct / abs(loss_pct) if loss_pct != 0 else 0

lines = []
lines.append(f"# 📊 华曙高科(688433) 增强决策报告 v6")
lines.append(f"*生成时间：2026-08-17 | 最新价 **{price}** 当日 **{extra['chg_pct']:+.2f}%** | 数据：模拟(贴近真实统计特征)*")
lines.append("")
lines.append(env_text)
lines.append("")
lines.append(f"*仓位上限：**100%** | 止损倍数：**1.5×ATR** | ATR(14)={atr14}({atr_pct}%)*")
lines.append("")
lines.append("#### 1. 标的属性与推荐策略周期")
lines.append(f"* **标的属性**：{extra['vol_level']}科创板3D打印/机器人标的，ATR={atr_pct}%，受机器人/PEEK材料题材驱动")
lines.append(f"* **推荐交易周期**：**{period}**")
lines.append(f"* **决策理由**：{reason}")
lines.append("")
lines.append("#### 2. 技术面深度体检（多指标交叉）")
lines.append(f"* **量价状态**：{vp}，量比{extra['vol_ratio']}，振幅{extra['amp_pct']}%，收{'阴' if extra['chg_pct']<0 else '阳'}")
lines.append(f"* **BOLL布林线**：价格位于**{boll['position']}**，上/中/下轨={boll['upper']}/{boll['mid']}/{boll['lower']}，"
             f"形态{boll['shape']}，宽度历史分位**{boll['width_pct_rank']}→{boll['width_label']}**")
lines.append(f"* **KDJ状态**：K={kdj['K']} D={kdj['D']} J={kdj['J']}，{kdj['zone']}，{kdj['cross']}")
lines.append(f"* **MACD & RSI**：DIF={macd['DIF']} DEA={macd['DEA']}，{macd['bar_state']}，"
             f"{macd['zone']}{macd['cross']}；RSI6={rsi['RSI6']} RSI14={rsi['RSI14']}")
lines.append(f"* **多空共振**：{resonance}")
lines.append("* **综合关键点位**：")
lines.append(f"  - **压力位1**：{t['resistance1']}元（依据：现价+1.5×ATR={atr14}×1.5）")
lines.append(f"  - **压力位2**：{t['resistance2']}元（依据：BOLL上轨）")
lines.append(f"  - **支撑位1**：{t['support1']}元（依据：现价-1.5×ATR）")
lines.append(f"  - **支撑位2**：{t['support2']}元（依据：MA20/BOLL中轨）")
lines.append(f"  - **止损位**：{t['stop_loss']}元（依据：现价-1.5×ATR，亏损约**{loss_pct:.1f}%**）")
lines.append("")
lines.append("#### 3. 傻瓜式交易预案（Action Plan）")
lines.append("* **【已持仓三档减仓】**：")
lines.append(f"  - 跌破{t['stage1_price']}元(-0.5×ATR) → 减仓10%预警")
lines.append(f"  - 跌破{t['support1']}元(支撑位1) → 减仓30%")
lines.append(f"  - 跌破{t['stage2_price']}元(-1×ATR) → 再减仓30%")
lines.append(f"  - 跌破{t['stop_loss']}元(止损位-1.5×ATR) → **清仓**，单笔最大亏损约**{loss_pct:.1f}%**")
lines.append(f"  - 带量突破{t['resistance1']}元且量比>1.5 → 加仓20%")
lines.append(f"  - 触及{t['resistance2']}元(BOLL上轨) → 减仓50%锁利")
lines.append("* **【未持仓/买入预案】**：")
lines.append(f"  - 首次建仓：{t['buy_zone'][0]}元附近，单次≤总资金**20%**")
lines.append(f"  - 加仓点：回踩{t['support2']}元(BOLL中轨)不破 → 加仓20%")
lines.append(f"  - 止损位：{t['stop_loss']}元（亏损约**{loss_pct:.1f}%**），破位无条件离场")
lines.append(f"  - 目标位：{t['resistance2']}元（+{up_pct:.1f}%），盈亏比≈**1:{rr:.1f}**")
lines.append("")
lines.append("---")
lines.append("")
lines.append("#### 附：技术指标 JSON")
lines.append("```json")
lines.append(json.dumps(extra, ensure_ascii=False, indent=2))
lines.append("```")
lines.append("")
lines.append("#### 附：市场环境 JSON")
lines.append("```json")
lines.append(json.dumps(env_result, ensure_ascii=False, indent=2, default=str))
lines.append("```")

report = "\n".join(lines)
out_path = Path("/data/workspace/report_688433_v6_FINAL.md")
out_path.write_text(report, encoding="utf-8")
print(f"\n  ✅ 最终报告已保存: {out_path}")
print("\n" + "=" * 62)
print(report)
print("=" * 62)
