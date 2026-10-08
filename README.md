# Analyze Markets and Portfolio

**中文 / English**

主动完成个股研究、基金穿透和具体机会发现的投研 skill。支持国内、香港和美国市场，给出分析周期、方向判断、首选动作、分批条件、失效条件与复核点。

A research skill for stocks, fund look-through and concrete opportunity discovery across mainland China, Hong Kong and the United States. It connects evidence to a time horizon, directional judgment, preferred action, staged entry conditions, invalidation and review points.

## 功能 / Capabilities

- **个股研究：**量价、MACD/BOLL/KDJ/RSI、可得盘口与供应商资金流，结合财务、估值、公告、行业及市场环境，形成建仓、加仓、持有、减仓、退出或等待意见。
  **Stock research:** combine price/volume, technical indicators, available quotes and vendor flows with financials, valuation, filings, industry and market conditions; recommend building, adding, holding, reducing, exiting or waiting.
- **基金研究：**核对精确代码和份额，穿透已披露股票、债券、ETF与子基金，比较行业、地区、币种、费用、跟踪和申赎机制；覆盖ETF联接、主动QDII、FOF及债券案例。
  **Fund research:** identify exact products and share classes, look through disclosed stocks, bonds, ETFs and child funds, and compare exposures, fees, tracking and dealing mechanics. Representative cases cover ETF feeders, active QDII, FOFs and bond funds.
- **自主发现：**从市场和板块扫描继续深挖到具体股票、ETF或场外基金，给出排序、理由和进入时机。
  **Autonomous discovery:** continue from market/sector scanning to named stocks, ETFs or off-exchange funds, with ranking, reasons and entry timing.
- **观点复核：**保留旧观点，遇到新事实后明确维持、调整或撤销。用户想买或已持有不改变证据强度。
  **Review:** preserve earlier theses and explicitly maintain, revise or revoke them when facts change. A user's wish to buy or existing position does not strengthen the evidence.

技术信号帮助判断走势与节奏。经营、估值与催化支持时可以提前分批布局；等待需要具体理由及机会成本，不要求所有指标同时通过。

Technical signals support trend and timing judgments. Business, valuation and catalysts can justify staged entry before full confirmation. Waiting needs a concrete reason and opportunity-cost comparison; every indicator need not agree.

## 安装与本地使用 / Installation and local use

已经安装当前版本的用户可以继续使用本地副本。GitHub用于保存、分享和后续安装；上传不会替换本地运行数据或配置。

Users who already have the current version installed can continue using their local copy. GitHub hosts the code for backup, sharing and future installation; publishing does not replace a local runtime or its configuration.

仓库保持根目录 `SKILL.md` 布局，沿用原有安装方式。
The repository retains its root `SKILL.md` layout and existing installation commands.

```bash
npx skills add stonebeast-river/analyze-markets-and-portfolio-skill
```

全局 Codex 安装 / Global Codex installation:

```bash
npx skills add stonebeast-river/analyze-markets-and-portfolio-skill --agent codex --global --copy --yes
```

也可将仓库内容放入个人技能目录下的 `analyze-markets-and-portfolio` 文件夹。Python 3.12用于本版验证。可选连接及解析依赖见[依赖文件](scripts/requirements-optional.txt)，环境配置见[运行设置](references/local-runtime.md)。

Alternatively, place the repository contents in an `analyze-markets-and-portfolio` folder in your personal skill directory. Python 3.12 was used for release validation. See [optional dependencies](scripts/requirements-optional.txt) and [runtime setup](references/local-runtime.md).

## 使用示例 / Usage examples

中文：

```text
用 $analyze-markets-and-portfolio 研究这只股票，判断未来数周至三个月的方向，给当前动作、入场条件、分批与失效点。

研究这只基金，穿透持仓，比较A/C等份额及替代，给配置和建仓／加仓意见。

主动找未来一至三个月的投资机会，自行筛选并研究到具体股票、ETF和场外基金，排序后给时机。
```

English:

```text
Use $analyze-markets-and-portfolio to research this stock over the next few weeks to three months. Give the preferred action, entry conditions, staged plan and invalidation.

Research this fund, look through its holdings, compare share classes and alternatives, and recommend allocation and entry/addition timing.

Independently discover investment opportunities over the next one to three months. Research named stocks, ETFs and off-exchange funds, then rank them and explain timing.
```

独立研究完成后，再映射用户提供的权威持仓。缺少个人金额时使用清楚标注的预算情景。
Complete independent research before mapping authoritative user-supplied holdings. Use explicitly labeled budget scenarios when personal amounts are absent.

## 数据与工具 / Data and tools

公开行情路径包括腾讯、BaoStock、东方财富和Yahoo。宏观与估值使用FRED、统计局、中证、中债等来源，并补查公司、交易所和基金管理人的原文。注册接口从环境变量读取凭据。

Public market-data routes include Tencent, BaoStock, Eastmoney and Yahoo. Macro and valuation research uses FRED, official statistics, CSI and ChinaBond sources, supplemented by company, exchange and fund-manager documents. Registered providers read credentials from environment variables.

| 内容 / Component | 用途 / Purpose |
| --- | --- |
| `scripts/market_engine.py` | 取数、指标、研究材料与复算 / Collection, indicators, research dossiers and replay |
| `references/` | 个股、基金、自主发现、数据口径与判断流程 / Research workflows, data conventions and decision guidance |
| `assets/` | 公开来源登记、费用与披露契约、交易日历 / Public-source registries, fee/disclosure contracts and calendars |
| `scripts/test_*.py` | 可重复的回归检查 / Reproducible regression tests |

KDJ使用9/3/3、K/D初值50、完整窗口和不截断J；RSI14使用Wilder平滑。国内筹码模块用真实日价格与换手率形成明确命名的本地估算，提供分布图、成本区及初始未知库存残留。详情见[技术与来源扩展](references/technical-and-source-extensions.md)。

KDJ uses 9/3/3, initial K/D values of 50, a full window and an unclipped J line; RSI14 uses Wilder smoothing. The domestic cost-distribution module uses actual daily prices and turnover in a named local model, with a distribution chart, cost regions and residual unknown initial inventory. See [technical and source extensions](references/technical-and-source-extensions.md).

```bash
python scripts/market_engine.py --help
python -B -m unittest discover -s scripts -p 'test*.py'
```

## 版本与范围 / Release and scope

2026-10-08扩展版通过266项本地回归检查及代表性真实源复算。最新财报、事件日历、ETF净值与溢价按具体判断补查；源的当前可用性在每次研究时核对。见[验证范围](references/validation-status.md)与[来源登记](references/provider-registry.md)。

The October 8, 2026 extension passed 266 local regression checks and representative live-source replay checks. Latest reports, event calendars, ETF NAV and premiums are researched when relevant to a decision. Source availability is checked at research time. See [validation scope](references/validation-status.md) and [provider registry](references/provider-registry.md).

仓库包含可复用的skill、代码、公开来源契约及说明。运行数据库、原始下载、私人持仓、密钥和机器配置在仓库外管理。研究与交易执行分开处理。

The repository contains the reusable skill, code, public-source contracts and documentation. Runtime databases, raw downloads, private holdings, keys and machine configuration are managed outside the repository. Research and trade execution are handled separately.

## License / 许可

MIT — see [LICENSE](LICENSE).
