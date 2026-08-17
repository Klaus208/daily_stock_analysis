"""
market_filter_v3.py
三层市场环境过滤器（方案Y）—— 最终生产版

第1层：市场级（A股三指数复合 / 港股恒指）
第2层：风格指数（按股票代码归属映射）
第3层：行业板块（通过 AkShare 反查个股所属行业）

汇总规则（保守，取较差）：
- 三层全 bull → 个股 environment = bull（允许顺势做多）
- 任一层 bear   → 个股 environment = bear（禁止做多）
- 其他          → 个股 environment = sideways（降级超短线）

降级逻辑：接口失败时逐级降级，永不阻断主流程。

依赖：akshare, pandas, numpy
"""

import time
import traceback
from typing import Optional

import numpy as np
import pandas as pd

# ============================================================
# 工具函数
# ============================================================

def _safe_get(func, *args, **kwargs):
    """安全调用 AkShare 接口，失败返回 None"""
    try:
        return func(*args, **kwargs)
    except Exception:
        return None


def _index_above_ma20(symbol: str, start: str = "20260301",
                       end: str = "20260817") -> Optional[bool]:
    """判断指数是否站上 MA20。返回 True/False/None(失败)"""
    df = _safe_get(
        __import__("akshare").stock_zh_index_hist_em,
        symbol=symbol, period="daily",
        start_date=start, end_date=end,
    )
    if df is None or df.empty or len(df) < 20:
        return None
    df["ma20"] = df["close"].rolling(20).mean()
    latest = df.iloc[-1]
    return bool(latest["close"] > latest["ma20"])


def _index_recent_return(symbol: str, days: int = 20,
                         start: str = "20260701",
                         end: str = "20260817") -> Optional[float]:
    """指数近 N 日收益率"""
    df = _safe_get(
        __import__("akshare").stock_zh_index_hist_em,
        symbol=symbol, period="daily",
        start_date=start, end_date=end,
    )
    if df is None or len(df) < days:
        return None
    return float(df["close"].iloc[-1] / df["close"].iloc[-days] - 1)


# ============================================================
# 第1层：市场级判定
# ============================================================

def layer1_market_level() -> dict:
    """
    A股：上证指数 + 创业板指 + 中证1000 三指数是否站上MA20
    港股：恒生指数是否站上MA20
    全市场涨跌比
    """
    ak = __import__("akshare")

    result = {
        "a_indices": {},
        "a_indices_above_count": 0,
        "hk_hsi_above": None,
        "a_adv_dec_ratio": None,
        "hk_adv_dec_ratio": None,
        "errors": [],
    }

    # --- A股三指数 ---
    a_index_map = {
        "上证指数": "上证指数",
        "创业板指": "创业板指",
        "中证1000": "中证1000",
    }
    for name, sym in a_index_map.items():
        ok = _index_above_ma20(sym)
        result["a_indices"][name] = ok
        if ok:
            result["a_indices_above_count"] += 1
        elif ok is None:
            result["errors"].append(f"{name}接口失败")

    # --- A股全市场涨跌比 ---
    spot = _safe_get(ak.stock_zh_a_spot_em)
    if spot is not None and not spot.empty:
        adv = int((spot["涨跌幅"] > 0).sum())
        dec = int((spot["涨跌幅"] < 0).sum())
        result["a_adv_dec_ratio"] = adv / max(dec, 1)

    # --- 港股恒指 ---
    # 恒生指数在 eastmoney 的 symbol 是 "HSI" 或 "恒生指数"
    for sym in ["恒生指数", "HSI"]:
        ok = _index_above_ma20(sym)
        if ok is not None:
            result["hk_hsi_above"] = ok
            break
    if result["hk_hsi_above"] is None:
        result["errors"].append("恒指接口失败")

    # --- 港股涨跌比（升跌比率）---
    # 尝试 AkShare 港股涨跌统计接口
    hk_stat = _safe_get(ak.stock_hk_quotation_em)  # 港股实时行情
    if hk_stat is not None and "涨跌幅" in hk_stat.columns:
        hk_adv = int((hk_stat["涨跌幅"] > 0).sum())
        hk_dec = int((hk_stat["涨跌幅"] < 0).sum())
        result["hk_adv_dec_ratio"] = hk_adv / max(hk_dec, 1)
    else:
        # 备选：用恒指涨跌代替
        hsi_spot = _safe_get(ak.stock_hk_index_em, symbol="恒生指数")
        if hsi_spot is not None:
            result["hk_adv_dec_ratio"] = 1.0  # 无法获取时保守设为1
            result["errors"].append("港股涨跌比接口不可用，使用保守估计")

    return result


def classify_market(code: str) -> str:
    """股票代码 → 市场分类"""
    c = str(code).replace("sh", "").replace("sz", "").replace("hk", "").strip()
    if c.startswith("688") or c.startswith("689"):
        return "科创板"
    elif c.startswith("300") or c.startswith("301"):
        return "创业板"
    elif c.startswith("60") or c.startswith("00"):
        return "沪深的"
    elif c.startswith("8") or c.startswith("4"):
        return "北交所"
    else:
        # 尝试港股判断（5位数字）
        if c.isdigit() and len(c) == 5:
            return "港股"
        return "其他"


def get_style_index(market: str) -> Optional[str]:
    """市场分类 → 对应风格指数名称（用于东财接口）"""
    return {
        "科创板": "科创50",
        "创业板": "创业板指",
        "沪深的": "上证50",
        "港股": "恒生指数",
        "北交所": "中证1000",
        "其他": None,
    }.get(market, None)


# ============================================================
# 第2层：风格指数判定
# ============================================================

def layer2_style_index(market: str) -> Optional[bool]:
    """风格指数是否站上 MA20"""
    style = get_style_index(market)
    if style is None:
        return None
    return _index_above_ma20(style)


# ============================================================
# 第3层：行业板块判定
# ============================================================

# 股票→行业板块 映射缓存
_industry_cache: dict = {}


def get_stock_industry(code: str) -> Optional[str]:
    """
    通过 AkShare 反查个股所属行业板块。
    优先用东财行业分类，缓存结果避免重复查询。
    """
    ak = __import__("akshare")
    code_clean = str(code).replace("sh", "").replace("sz", "").replace("hk", "")

    if code_clean in _industry_cache:
        return _industry_cache[code_clean]

    # 方法1：通过个股信息接口获取行业
    info = _safe_get(ak.stock_individual_info_em, symbol=code_clean)
    if info is not None:
        # info 通常是 DataFrame，找"行业"行
        try:
            row = info[info.iloc[:, 0] == "行业"]
            if not row.empty:
                industry = str(row.iloc[0, 1]).strip()
                if industry and industry != "nan":
                    _industry_cache[code_clean] = industry
                    return industry
        except Exception:
            pass

    # 方法2：遍历东财行业板块成分股反查
    boards = _safe_get(ak.stock_board_industry_name_em)
    if boards is not None and "板块名称" in boards.columns:
        for _, row in boards.iterrows():
            bname = row["板块名称"]
            cons = _safe_get(ak.stock_board_industry_cons_em, symbol=bname)
            if cons is not None and "代码" in cons.columns:
                if code_clean in cons["代码"].values.astype(str):
                    _industry_cache[code_clean] = bname
                    return bname
            time.sleep(0.2)  # 防限流

    _industry_cache[code_clean] = None
    return None


def layer3_industry_state(industry: Optional[str]) -> dict:
    """
    板块三因子判定：
    1. 趋势：板块指数站上 MA20
    2. 相对强弱：板块20日收益 vs 沪深300 20日收益
    3. 资金：板块主力净流入
    """
    ak = __import__("akshare")
    default = {
        "above_ma20": True,       # 失败时保守放行
        "ma20_slope_up": True,
        "relative_strength": True,
        "fund_inflow": True,
        "industry": industry,
        "error": None,
    }
    if not industry:
        default["error"] = "无行业信息"
        return default

    # 1. 板块指数趋势
    hist = _safe_get(
        ak.stock_board_industry_hist_em,
        symbol=industry, period="daily",
        start_date="20260301", end_date="20260817",
    )
    if hist is None or len(hist) < 20:
        default["error"] = "板块历史数据不足"
        return default

    hist["ma20"] = hist["close"].rolling(20).mean()
    above = bool(hist["close"].iloc[-1] > hist["ma20"].iloc[-1])
    slope_up = bool(hist["ma20"].iloc[-1] > hist["ma20"].iloc[-5])

    # 2. 相对强弱 vs 沪深300
    hs300_ret = _index_recent_return("沪深300", 20)
    ind_ret = float(hist["close"].iloc[-1] / hist["close"].iloc[-20] - 1)
    rel_strong = True
    if hs300_ret is not None:
        rel_strong = ind_ret > hs300_ret

    # 3. 板块资金流
    fund_in = True
    fund_df = _safe_get(ak.stock_fund_flow_industry, indicator="今日")
    if fund_df is not None and "行业" in fund_df.columns:
        row = fund_df[fund_df["行业"] == industry]
        if not row.empty and "主力净流入-净额" in row.columns:
            val = row["主力净流入-净额"].values[0]
            try:
                fund_in = float(val) > 0
            except (ValueError, TypeError):
                fund_in = True

    return {
        "above_ma20": above,
        "ma20_slope_up": slope_up,
        "relative_strength": rel_strong,
        "fund_inflow": fund_in,
        "industry": industry,
        "error": None,
    }


# ============================================================
# 汇总判定
# ============================================================

def evaluate_stock_environment(code: str) -> dict:
    """
    三层架构汇总，返回单只股票的环境判定结果。

    返回 dict:
    {
        "code": str,
        "market": str,           # 科创板/创业板/沪深的/港股
        "industry": str|None,
        "environment": str,      # "bull" / "sideways" / "bear"
        "allow_trend_following": bool,
        "allow_any_long": bool,
        "details": { ... }       # 各层详细数据
    }
    """
    ak = __import__("akshare")

    # 第1层
    mkt = layer1_market_level()

    # A股 bull 判定
    a_bull = (mkt["a_indices_above_count"] == 3 and
              mkt["a_adv_dec_ratio"] is not None and
              mkt["a_adv_dec_ratio"] >= 1.0)
    a_sideways = (mkt["a_indices_above_count"] >= 1 and
                  mkt["a_adv_dec_ratio"] is not None and
                  mkt["a_adv_dec_ratio"] >= 0.8)
    a_bear = not a_bull and not a_sideways

    # 港股 bull 判定
    hk_bull = (mkt["hk_hsi_above"] and
               mkt["hk_adv_dec_ratio"] is not None and
               mkt["hk_adv_dec_ratio"] >= 1.0)
    hk_sideways = (mkt["hk_hsi_above"] or
                   (mkt["hk_adv_dec_ratio"] is not None and
                    mkt["hk_adv_dec_ratio"] >= 1.0))
    hk_bear = not hk_bull and not hk_sideways

    # 根据股票市场选对应判定
    market_name = classify_market(code)
    if market_name == "港股":
        market_bull = hk_bull
        market_sideways = hk_sideways
        market_bear = hk_bear
    else:
        market_bull = a_bull
        market_sideways = a_sideways
        market_bear = a_bear

    # 第2层：风格指数
    style_ok = layer2_style_index(market_name)

    # 第3层：行业板块
    industry = get_stock_industry(code)
    ind_state = layer3_industry_state(industry)

    # ---------- 汇总（保守：取较差）----------
    # 行业三因子：至少满足"站上MA20"才算 bull
    industry_bull = (ind_state["above_ma20"] and
                     ind_state["relative_strength"] and
                     ind_state["fund_inflow"])

    # 综合判定
    if market_bear or (style_ok is not None and not style_ok and not industry_bull):
        env = "bear"
    elif market_bull and style_ok and industry_bull:
        env = "bull"
    else:
        env = "sideways"

    return {
        "code": code,
        "market": market_name,
        "industry": industry,
        "environment": env,
        "allow_trend_following": env == "bull",
        "allow_any_long": env != "bear",
        "details": {
            "layer1": {
                "a_indices": mkt["a_indices"],
                "a_above_count": mkt["a_indices_above_count"],
                "a_adv_dec_ratio": mkt["a_adv_dec_ratio"],
                "hk_hsi_above": mkt["hk_hsi_above"],
                "hk_adv_dec_ratio": mkt["hk_adv_dec_ratio"],
            },
            "layer2_style_above_ma20": style_ok,
            "layer3_industry": ind_state,
        },
    }


# ============================================================
# 批量评估（供项目主流程调用）
# ============================================================

def evaluate_all(stock_codes: list) -> dict:
    """
    批量评估一组股票的市场环境。
    返回 {code: env_dict, ...} 加上全局 summary。
    """
    results = {}
    for code in stock_codes:
        try:
            results[code] = evaluate_stock_environment(code)
        except Exception as e:
            results[code] = {
                "code": code,
                "market": classify_market(code),
                "industry": None,
                "environment": "sideways",  # 失败时保守降级
                "allow_trend_following": False,
                "allow_any_long": True,
                "details": {"error": str(e)},
            }
        time.sleep(0.5)  # 防限流

    # 全局汇总（取最差）
    env_rank = {"bull": 2, "sideways": 1, "bear": 0}
    global_env = min(
        (r["environment"] for r in results.values()),
        key=lambda x: env_rank.get(x, 1),
    )

    return {
        "stocks": results,
        "global_env": global_env,
        "summary": {
            code: r["environment"] for code, r in results.items()
        },
    }


# ============================================================
# 生成报告用的环境描述文本
# ============================================================

def format_env_report(env_result: dict) -> str:
    """把评估结果格式化为报告文本段落"""
    d = env_result
    lines = []
    lines.append("#### 0. 个股市场环境过滤（方案Y·三层架构）")

    det = d.get("details", {})
    l1 = det.get("layer1", {})

    # 市场层
    a_idx = l1.get("a_indices", {})
    a_desc = "、".join([f"{k}{'✅' if v else '❌'}" for k, v in a_idx.items()])
    a_ratio = l1.get("a_adv_dec_ratio")
    a_ratio_str = f"{a_ratio:.2f}" if a_ratio else "N/A"
    lines.append(f"* 市场层(A股)：{a_desc}，涨跌比{a_ratio_str}")

    # 港股
    hk_above = l1.get("hk_hsi_above")
    hk_ratio = l1.get("hk_adv_dec_ratio")
    if hk_above is not None:
        lines.append(
            f"* 市场层(港股)：恒指{'✅' if hk_above else '❌'}站上MA20，"
            f"升跌比{f'{hk_ratio:.2f}' if hk_ratio else 'N/A'}"
        )

    # 风格层
    l2 = det.get("layer2_style_above_ma20")
    lines.append(
        f"* 风格层：{d['market']}→"
        f"{'✅站上MA20' if l2 else '❌未站上MA20' if l2 is not None else '数据不足'}"
    )

    # 行业层
    l3 = det.get("layer3_industry", {})
    ind = d.get("industry") or "未知"
    lines.append(
        f"* 行业层：[{ind}] "
        f"MA20={'✅' if l3.get('above_ma20') else '❌'}"
        f" 相对强弱={'✅' if l3.get('relative_strength') else '❌'}"
        f" 资金={'✅流入' if l3.get('fund_inflow') else '❌流出'}"
    )

    # 汇总
    env_icon = {"bull": "✅", "sideways": "⚠️", "bear": "❌"}
    lines.append(
        f"* 综合判定：{env_icon.get(d['environment'], '?')} "
        f"**{d['environment'].upper()}**"
        f"{' → 允许顺势做多' if d['allow_trend_following'] else ''}"
        f"{' → 禁止任何做多' if not d['allow_any_long'] else ''}"
        f"{' → 降级超短线博弈' if d['environment']=='sideways' else ''}"
    )

    return "\n".join(lines)


# ============================================================
# 自检
# ============================================================

if __name__ == "__main__":
    print("=== 市场过滤器 v3 自检 ===")
    # 用华曙高科测试
    test_code = "688433"
    result = evaluate_stock_environment(test_code)
    print(format_env_report(result))
    print()
    print(f"环境: {result['environment']}")
    print(f"市场: {result['market']}")
    print(f"行业: {result['industry']}")
    print(f"允许顺势做多: {result['allow_trend_following']}")
    print(f"允许任何做多: {result['allow_any_long']}")
