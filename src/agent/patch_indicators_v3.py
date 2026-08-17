"""
patch_indicators_v3.py
增强技术指标补丁 v3 —— 最终生产版
- BOLL 宽度历史分位 (boll_width_pct_rank) + 四档分类
- 1.5×ATR 止损（高波动标的）
- 三档减仓阶梯（30% → 30% → 清仓）
- 零轴纠缠态强制中线判定
- 量价状态枚举（含缩量阴跌/缩量观望）
- 密集成交区（近10日）
- tech_summary 字符串供 LLM 直接消费

依赖：numpy, pandas
"""

import numpy as np
import pandas as pd


# ============================================================
# BOLL 宽度历史分位
# ============================================================
def calc_boll_width_pct_rank(df: pd.DataFrame, close_col="close",
                              period: int = 20, std_mult: float = 2.0,
                              lookback: int = 100) -> pd.Series:
    """
    计算 BOLL 相对宽度在历史 lookback 窗口中的百分位 (0~1)。
    低分位 = 收口挤压（变盘在即），高分位 = 张口加速（趋势行情）。
    返回与 df 等长的 Series，最后一行即当前分位。
    """
    sma = df[close_col].rolling(period).mean()
    std = df[close_col].rolling(period).std()
    # 相对宽度 = 2σ / 中轨，消除价格量级影响
    width = (2 * std_mult * std) / sma
    # 在最近 lookback 个宽度值里排当前值的百分位
    pct_rank = width.rolling(lookback).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1]
        if len(x.dropna()) > 5 else np.nan,
        raw=False
    )
    return pct_rank


def classify_boll_width(width_pct_rank: float) -> str:
    """BOLL 宽度四档分类"""
    if pd.isna(width_pct_rank):
        return "数据不足"
    if width_pct_rank <= 0.20:
        return "🔒极致收口/蓄势"
    elif width_pct_rank <= 0.40:
        return "收口"
    elif width_pct_rank <= 0.80:
        return "常态"
    else:
        return "🚀张口加速"


# ============================================================
# ATR 计算
# ============================================================
def compute_atr(df: pd.DataFrame, period: int = 14,
                close_col: str = "close") -> float:
    """计算 ATR(period)，返回最新值"""
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df[close_col].astype(float)
    prev = c.shift(1)
    tr = pd.concat(
        [(h - l), (h - prev).abs(), (l - prev).abs()], axis=1
    ).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


# ============================================================
# 主入口：计算全部增强指标
# ============================================================
def compute_extra_indicators(df: pd.DataFrame,
                             close_col: str = "close") -> dict:
    """
    输入日线 DataFrame（需含 open/high/low/close/volume），
    返回增强指标 dict（含 BOLL 宽度分位、ATR 止损、三档减仓等）。
    """
    out: dict = {}
    req = {"open", "high", "low", "close", "volume"}
    if df is None or df.empty or not req.issubset(df.columns):
        out["error"] = "数据列缺失，无法计算增强指标"
        return out

    c = df[close_col].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    o = df["open"].astype(float)
    v = df["volume"].astype(float)
    n = len(c)

    # ---------- 均线 ----------
    ma5 = float(c.rolling(5).mean().iloc[-1]) if n >= 5 else np.nan
    ma10 = float(c.rolling(10).mean().iloc[-1]) if n >= 10 else np.nan
    ma20 = float(c.rolling(20).mean().iloc[-1]) if n >= 20 else np.nan
    ma60 = float(c.rolling(60).mean().iloc[-1]) if n >= 60 else np.nan

    # ---------- ATR(14) ----------
    atr14 = compute_atr(df, 14, close_col)
    atr_pct = atr14 / float(c.iloc[-1]) * 100

    # ---------- 量比（vs 近5日均量，不含今日）----------
    if n >= 6:
        avg5 = float(v.rolling(5).mean().iloc[-2])
        vol_ratio = float(v.iloc[-1] / avg5) if avg5 > 0 else 1.0
    else:
        vol_ratio = 1.0

    # ---------- 今日涨跌 / 振幅 ----------
    chg_pct = float((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100) if n >= 2 else 0.0
    is_up = bool(c.iloc[-1] >= o.iloc[-1])
    amp_pct = float((h.iloc[-1] - l.iloc[-1]) / c.iloc[-1] * 100)

    # ---------- 密集成交区（近10日收盘分位数）----------
    if n >= 10:
        win = c.iloc[-10:]
        upper_dense = float(np.percentile(win, 75))
        lower_dense = float(np.percentile(win, 25))
    else:
        upper_dense = float(c.iloc[-1])
        lower_dense = float(c.iloc[-1])

    # ---------- BOLL(20,2) + 通道形态 + 宽度分位 ----------
    if n >= 20:
        mid = float(c.rolling(20).mean().iloc[-1])
        std = float(c.rolling(20).std().iloc[-1])
        boll_u = mid + 2 * std
        boll_d = mid - 2 * std

        # 宽度历史分位
        width_series = calc_boll_width_pct_rank(df, close_col, 20, 2.0, 100)
        width_pct_rank = float(width_series.iloc[-1]) if pd.notna(width_series.iloc[-1]) else np.nan
        boll_width_label = classify_boll_width(width_pct_rank)

        # 通道形态（5日宽度变化率，作为补充）
        w5 = pd.Series(index=c.index, dtype=float)
        for i in range(len(c)):
            if i >= 19:
                m = c.iloc[i - 19:i + 1].mean()
                s = c.iloc[i - 19:i + 1].std()
                w5.iloc[i] = (m + 2 * s) - (m - 2 * s)
        w5_smooth = w5.rolling(5).mean()
        if n >= 10 and pd.notna(w5_smooth.iloc[-5]) and w5_smooth.iloc[-5] > 0:
            width_ratio = float(w5_smooth.iloc[-1] / w5_smooth.iloc[-5])
        else:
            width_ratio = 1.0

        if width_ratio > 1.08:
            boll_shape = "张口加速"
        elif width_ratio < 0.92:
            boll_shape = "收口变盘"
        else:
            boll_shape = "通道平稳"

        # 价格位置
        if c.iloc[-1] >= boll_u:
            boll_pos = "贴/破上轨"
        elif c.iloc[-1] >= mid:
            boll_pos = "中轨上方"
        elif c.iloc[-1] >= boll_d:
            boll_pos = "中轨下方"
        else:
            boll_pos = "贴/破下轨"
    else:
        mid = float(ma20) if not np.isnan(ma20) else float(c.iloc[-1])
        std = atr14
        boll_u = mid + 2 * std
        boll_d = mid - 2 * std
        boll_shape = "数据不足"
        boll_pos = "未知"
        width_pct_rank = np.nan
        boll_width_label = "数据不足"

    # ---------- KDJ(9,3,3) ----------
    if n >= 9:
        low9 = l.rolling(9).min()
        high9 = h.rolling(9).max()
        rsv = (c - low9) / (high9 - low9).replace(0, np.nan) * 100
        rsv = rsv.fillna(50)
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d
        k9 = float(k.iloc[-1])
        d9 = float(d.iloc[-1])
        j9 = float(j.iloc[-1])
        if n >= 10:
            if k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2]:
                kdj_cross = "低位金叉↑"
            elif k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2]:
                kdj_cross = "高位死叉↓"
            else:
                kdj_cross = "无交叉"
        else:
            kdj_cross = "无交叉"
        if j9 > 90:
            kdj_zone = "超买(J>90)"
        elif j9 < 10:
            kdj_zone = "超卖(J<10)"
        else:
            kdj_zone = "中性区间"
    else:
        k9 = d9 = j9 = 50.0
        kdj_cross = "数据不足"
        kdj_zone = "未知"

    # ---------- MACD(12,26,9) ----------
    if n >= 26:
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        bar = (dif - dea) * 2
        dif_v = float(dif.iloc[-1])
        dea_v = float(dea.iloc[-1])
        bar_v = float(bar.iloc[-1])
        if dif_v > 0 and dea_v > 0:
            macd_zone = "零轴上方多头"
        elif dif_v < 0 and dea_v < 0:
            macd_zone = "零轴下方空头"
        else:
            macd_zone = "零轴纠缠态"
        if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
            macd_cross = "金叉↑"
        elif dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
            macd_cross = "死叉↓"
        else:
            macd_cross = "无交叉"
        if bar_v > 0 and bar_v > bar.iloc[-2]:
            bar_state = "红柱放大"
        elif bar_v > 0:
            bar_state = "红柱缩短"
        elif bar_v < 0 and bar_v < bar.iloc[-2]:
            bar_state = "绿柱放大"
        else:
            bar_state = "绿柱缩短"
        dif_zero_dist_atr = abs(dif_v) / atr14 if atr14 > 0 else 0
    else:
        dif_v = dea_v = bar_v = 0.0
        macd_zone = "数据不足"
        macd_cross = "无"
        bar_state = "无"
        dif_zero_dist_atr = 0.0

    # ---------- 量价状态枚举 v3 ----------
    if vol_ratio > 1.5 and is_up and c.iloc[-1] >= c.iloc[-5:].max():
        vol_price = "放量突破"
    elif vol_ratio > 1.5 and not is_up and c.iloc[-1] < (ma20 if not np.isnan(ma20) else c.iloc[-1]):
        vol_price = "价跌量增出逃"
    elif vol_ratio > 1.5 and is_up:
        vol_price = "放量滞涨"
    elif vol_ratio < 0.7 and not is_up and (not np.isnan(ma20) and c.iloc[-1] < ma20):
        vol_price = "缩量阴跌"
    elif vol_ratio < 0.7 and amp_pct < 1.5:
        vol_price = "缩量观望（阴跌企稳）"
    elif vol_ratio < 0.7 and is_up:
        vol_price = "缩量洗盘"
    elif vol_ratio >= 0.7 and is_up:
        vol_price = "温和放量上涨"
    else:
        vol_price = "缩量洗盘"

    # ---------- 波动率分级 ----------
    if atr_pct > 4:
        vol_level = "高波动"
    elif atr_pct > 1.5:
        vol_level = "中波动"
    else:
        vol_level = "低波动"

    # ---------- 方案A v3：点位精算（1.5×ATR 止损）----------
    # 核心原则：所有下方点位以"现价"为锚点向下计算，
    # 保证止损/支撑/减仓线永远低于现价。
    price = float(c.iloc[-1])

    if atr_pct > 4:  # 高波动：ATR 止损
        stop_loss = price - 1.5 * atr14
        stage1_price = price - 0.5 * atr14
        stage2_price = price - 1.0 * atr14
        sup1 = price - 1.5 * atr14
        sup2 = price - 2.0 * atr14
        res1 = price + 1.5 * atr14
        res2 = boll_u
        buy_upper = price
        buy_lower = max(price - 0.5 * atr14, lower_dense)
    else:  # 中/低波动：仍用 ATR 锚定，但倍数更紧
        # 止损 = 现价 - 3%（中低波动标的正常回撤阈值）
        stop_loss = price * 0.97
        stage1_price = price * 0.99
        stage2_price = price * 0.98
        sup1 = price * 0.97  # 跌破3%确认破位
        sup2 = float(ma20) if not np.isnan(ma20) else (price * 0.95)
        # 压力取 BOLL 上轨 / 密集成交区上限 / 现价+3% 三者中最低者
        res1 = min(boll_u, upper_dense, price * 1.03)
        res2 = max(boll_u, upper_dense)
        buy_upper = price
        buy_lower = price * 0.97

    # 兜底校验：所有"下方点位"必须 < 现价
    for _name, _val in [("stop_loss", stop_loss),
                        ("stage1", stage1_price),
                        ("stage2", stage2_price),
                        ("sup1", sup1), ("sup2", sup2),
                        ("buy_lower", buy_lower)]:
        if _val >= price:
            # 极端情况（今日暴跌后 MA/密集区高于现价），强制以 ATR 重算
            _atr_offset = atr14 if atr14 > 0 else (price * 0.02)
            if _name == "stop_loss":  stop_loss = price - 1.5 * _atr_offset
            if _name == "stage1":    stage1_price = price - 0.5 * _atr_offset
            if _name == "stage2":    stage2_price = price - 1.0 * _atr_offset
            if _name == "sup1":      sup1 = price - 1.5 * _atr_offset
            if _name == "sup2":      sup2 = price - 2.0 * _atr_offset
            if _name == "buy_lower": buy_lower = price - 0.5 * _atr_offset

    # 上方点位必须 > 现价
    if res1 <= price:
        res1 = price * 1.03
    if res2 <= price:
        res2 = price * 1.05

    # ---------- 零轴纠缠 → 强制中线 ----------
    zero_tangled = (dif_zero_dist_atr < 0.5) and (
        "纠缠" in macd_zone or (dif_v * dea_v < 0)
    )

    # ---------- 打包输出 ----------
    out = {
        "price": round(price, 2),
        "chg_pct": round(chg_pct, 2),
        "vol_ratio": round(vol_ratio, 2),
        "amp_pct": round(amp_pct, 2),
        "is_up": bool(is_up),
        "atr14": round(atr14, 3),
        "atr_pct": round(atr_pct, 2),
        "vol_level": vol_level,
        "ma5": round(ma5, 2) if not np.isnan(ma5) else None,
        "ma10": round(ma10, 2) if not np.isnan(ma10) else None,
        "ma20": round(ma20, 2) if not np.isnan(ma20) else None,
        "ma60": round(ma60, 2) if not np.isnan(ma60) else None,
        "boll": {
            "upper": round(boll_u, 2),
            "mid": round(mid, 2),
            "lower": round(boll_d, 2),
            "shape": boll_shape,
            "position": boll_pos,
            "width_pct_rank": round(width_pct_rank, 2) if not np.isnan(width_pct_rank) else None,
            "width_label": boll_width_label,
        },
        "kdj": {
            "K": round(k9, 1),
            "D": round(d9, 1),
            "J": round(j9, 1),
            "zone": kdj_zone,
            "cross": kdj_cross,
        },
        "macd": {
            "DIF": round(dif_v, 3),
            "DEA": round(dea_v, 3),
            "BAR": round(bar_v, 3),
            "zone": macd_zone,
            "cross": macd_cross,
            "bar_state": bar_state,
            "dif_zero_dist_atr": round(dif_zero_dist_atr, 2),
        },
        "rsi": {
            "RSI6": round(_calc_rsi(c, 6), 1),
            "RSI14": round(_calc_rsi(c, 14), 1),
        },
        "vol_price_state": vol_price,
        "dense_zone": {
            "upper": round(upper_dense, 2),
            "lower": round(lower_dense, 2),
        },
        "zero_tangled": bool(zero_tangled),
        "targets": {
            "stop_loss": round(stop_loss, 2),
            "stop_loss_atr_mult": 1.5,
            "stage1_price": round(stage1_price, 2),
            "stage2_price": round(stage2_price, 2),
            "buy_zone": [round(buy_lower, 2), round(buy_upper, 2)],
            "support1": round(sup1, 2),
            "support2": round(sup2, 2) if not np.isnan(sup2) else None,
            "resistance1": round(res1, 2),
            "resistance2": round(res2, 2),
        },
    }

    # ---------- tech_summary 单行摘要 ----------
    width_info = (f"宽度分位{out['boll']['width_pct_rank']}"
                  if out['boll']['width_pct_rank'] is not None else "宽度数据不足")
    out["tech_summary"] = (
        f"价{price}({chg_pct:+.2f}%)量比{vol_ratio:.2f}→{vol_price} | "
        f"ATR={atr14:.2f}({atr_pct:.1f}%){vol_level} | "
        f"MA5={ma5:.2f} MA20={ma20:.2f} MA60={ma60:.2f} | "
        f"KDJ K={k9:.1f} D={d9:.1f} J={j9:.1f} {kdj_zone} {kdj_cross} | "
        f"BOLL上{boll_u:.2f}/中{mid:.2f}/下{boll_d:.2f} "
        f"{boll_shape}({boll_pos}) {width_info}→{boll_width_label} | "
        f"MACD DIF={dif_v:.3f} DEA={dea_v:.3f} {bar_state} {macd_zone} {macd_cross} | "
        f"RSI14={out['rsi']['RSI14']} | "
        f"密集区[{lower_dense:.2f}-{upper_dense:.2f}] | "
        f"零轴纠缠={zero_tangled}"
    )
    return out


# ============================================================
# RSI 辅助函数
# ============================================================
def _calc_rsi(close: pd.Series, period: int = 14) -> float:
    """计算 RSI(period) 最新值"""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0


# ============================================================
# 供项目调用的 hook
# ============================================================
def attach_to_analysis(analysis: dict, df: pd.DataFrame) -> dict:
    """把增强指标合并进现有 analysis dict。"""
    extra = compute_extra_indicators(df)
    analysis["extra_indicators"] = extra
    if "tech_summary" not in analysis and extra.get("tech_summary"):
        analysis["tech_summary"] = extra["tech_summary"]
    if extra.get("targets"):
        analysis.setdefault("targets", {}).update(extra["targets"])
    analysis["zero_tangled"] = extra.get("zero_tangled", False)
    analysis["atr_pct"] = extra.get("atr_pct")
    return analysis


# ============================================================
# 自检
# ============================================================
if __name__ == "__main__":
    rng = np.random.default_rng(42)
    base = 80 + rng.normal(0, 1, 100).cumsum() * 0.4
    df = pd.DataFrame(
        {
            "open": base + rng.normal(0, 0.3, 100),
            "high": base + np.abs(rng.normal(0.5, 0.5, 100)),
            "low": base - np.abs(rng.normal(0.5, 0.5, 100)),
            "close": base + rng.normal(0, 0.3, 100),
            "volume": rng.integers(1_000_000, 5_000_000, 100),
        }
    )
    res = compute_extra_indicators(df)
    print(res["tech_summary"])
    print("KEYS:", list(res.keys()))
    print("BOLL width_label:", res["boll"]["width_label"])
    print("Targets:", res["targets"])
