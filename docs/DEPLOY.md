# 增强决策系统 v6 — 部署说明

## 交付文件清单

| 文件 | 作用 | 部署位置 |
|---|---|---|
| `patch_indicators_v3.py` | 增强技术指标补丁（BOLL宽度分位/ATR止损/KDJ/BOLL/MACD/RSI/量价枚举） | `src/agent/patch_indicators_v3.py` |
| `market_filter_v3.py` | 三层市场环境过滤器（方案Y） | `src/agent/market_filter_v3.py` |
| `stock_industry_cache.py` | 股票→行业板块映射缓存 | `src/agent/stock_industry_cache.py` |
| `enhanced_decision_v6.yaml` | LLM 策略模板（含市场环境规则+输出模板） | `my_skills/enhanced_decision_v6.yaml` |

## GitHub Secrets 配置

在 `Settings → Secrets and variables → Actions → Secrets` 中添加：

| Secret 名 | 值 | 说明 |
|---|---|---|
| `STOCK_LIST` | `688433,600519,000858,hk00700` 等 | 你的持仓股票代码 |
| `GEMINI_API_KEY` | `AIza...` | Google Gemini API Key |
| `WECHAT_WEBHOOK_URL` | `https://qyapi.weixin.qq.com/...` | 企业微信群机器人 Webhook |
| `WECHAT_WEBHOOK_KEYWORD` | 如 `股票日报` | 关键词校验（如飞书/企微设了关键词） |
| `TUSHARE_TOKEN` | `你的Tushare Token` | 可选，用于修复资金流数据 |
| `AGENT_SKILL_DIR` | `./my_skills` | 告诉项目加载自定义策略目录 |

## 部署步骤

### 1. 上传策略文件
```bash
# 在 GitHub 仓库根目录创建 my_skills/ 文件夹
mkdir -p my_skills

# 上传 enhanced_decision_v6.yaml 到 my_skills/
# 上传 patch_indicators_v3.py 到 src/agent/
# 上传 market_filter_v3.py 到 src/agent/
# 上传 stock_industry_cache.py 到 src/agent/
```

### 2. 修改 runner.py 接入补丁
在 `src/agent/runner.py` 的 `analyze()` 函数返回前，加入：

```python
from patch_indicators_v3 import attach_to_analysis
from market_filter_v3 import evaluate_stock_environment, format_env_report

# 在 analysis 生成后、LLM 调用前
analysis = attach_to_analysis(analysis, df)

# 市场环境评估
env_result = evaluate_stock_environment(stock_code)
analysis["market_env"] = env_result
analysis["market_env_text"] = format_env_report(env_result)
```

### 3. 修改 LLM prompt 注入环境变量
在构建发给 Gemini 的 prompt 时，把 `analysis["market_env"]` 的 JSON 也注入进去，
YAML 模板里 `{{market_env}}` 占位符会自动替换。

### 4. 首次构建行业缓存
在 Actions runner 里加一步：
```yaml
- name: Build industry cache
  run: cd src/agent && python stock_industry_cache.py
```

## 降级策略（网络/接口失败时不阻断）

| 失败层级 | 降级行为 |
|---|---|
| 个股日线拉不到 | 跳过该股票，记录错误，继续下一只 |
| 风格指数接口失败 | 跳过第2层，用第1层+第3层判定 |
| 行业板块接口失败 | 行业因子视为通过（保守放行） |
| 三层全失败 | environment = sideways，禁止趋势做多 |
| LLM 调用失败 | 用 tech_summary 作为降级文本直接推送 |

## 验证清单

跑通后，每只股票的报告应包含：
- ✅ 第0节：三层市场环境过滤（市场层/风格层/行业层/综合判定）
- ✅ 第1节：标的属性 + 推荐周期 + 决策理由
- ✅ 第2节：量价/BOLL/KDJ/MACD&RSI/多空共振/关键点位
- ✅ BOLL 宽度历史分位 + 四档标签
- ✅ 三档减仓（stage1/stage2/止损）
- ✅ 已持仓 + 未持仓两套预案
- ✅ 附：技术指标 JSON + 市场环境 JSON

## 参数调优建议

| 参数 | 当前值 | 调整建议 |
|---|---|---|
| ATR 止损倍数 | 1.5× | 保守者改 1.2×；趋势跟踪者可改 2.0× |
| 三档减仓比例 | 10%/30%/30% | 重仓股可改 20%/30%/30% |
| 涨跌比阈值 | 1.0 | 保守改 1.2；宽松改 0.8 |
| BOLL 宽度分位阈值 | 0.20/0.80 | 震荡市可收紧到 0.30/0.70 |
| 零轴纠缠阈值 | 0.5×ATR | 敏感者可改 0.3×ATR |

## 注意事项

1. **AkShare 接口有频率限制**，10 只以内稳，超过 20 只有限流风险
2. **行业缓存首次构建需 5-10 分钟**（遍历 50+ 板块），之后增量更新很快
3. **企业微信 Webhook 地址等同于发消息权限**，不要泄露
4. **本系统为辅助决策工具**，所有止损/仓位建议需人工复核
