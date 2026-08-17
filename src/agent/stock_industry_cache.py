"""
stock_industry_cache.py
股票→行业板块 映射缓存工具

首次运行时遍历东财行业板块成分股建立映射，存本地 JSON，
之后每天只增量更新，避免每次都全量遍历触发限流。
"""

import json
import os
import time
from pathlib import Path

import akshare as ak

CACHE_PATH = Path(__file__).parent / "industry_cache.json"


def build_cache(force: bool = False) -> dict:
    """
    构建/刷新 股票代码→行业板块 映射。
    force=True 时强制全量重建；否则读缓存。
    """
    if CACHE_PATH.exists() and not force:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    print("[IndustryCache] 首次构建，遍历东财行业板块...")
    cache: dict = {}
    boards = ak.stock_board_industry_name_em()
    total = len(boards)
    for i, row in enumerate(boards.itertuples(), 1):
        bname = row.板块名称
        try:
            cons = ak.stock_board_industry_cons_em(symbol=bname)
            for code in cons["代码"].values:
                cache[str(code).zfill(6)] = bname
        except Exception:
            continue
        if i % 10 == 0:
            print(f"  ... {i}/{total} 板块完成，已映射 {len(cache)} 只股票")
        time.sleep(0.2)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"[IndustryCache] 构建完成，共 {len(cache)} 只股票映射")
    return cache


def get_industry(code: str, cache: dict = None) -> str | None:
    """查询单只股票的行业板块"""
    code = str(code).replace("sh", "").replace("sz", "").replace("hk", "")
    code = code.zfill(6)
    if cache is None:
        cache = build_cache() if CACHE_PATH.exists() else {}
    return cache.get(code)


if __name__ == "__main__":
    c = build_cache(force=True)
    # 测试
    for t in ["688433", "600519", "000858", "300750"]:
        print(f"  {t} → {c.get(t, '未找到')}")
