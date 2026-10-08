# Analyze Markets and Portfolio

主动完成个股研究、基金穿透和具体机会发现的投研 skill。支持国内、香港和美国市场；根据实际证据给出分析周期、方向判断、首选动作、分批条件、失效条件与复核点。

## 能做什么

- **个股研究：**量价、MACD/BOLL/KDJ/RSI、可得盘口与供应商资金流，结合财务、估值、公告、行业及市场环境形成建仓、加仓、持有、减仓、退出或等待意见。
- **基金研究：**核对精确代码和份额，穿透已披露股票、债券、ETF和子基金，比较行业/地区/币种、费用、跟踪与申赎机制；覆盖ETF联接、主动QDII、FOF及债券案例。
- **自主机会发现：**从市场和板块扫描继续深挖到具体股票、ETF或场外基金，给出排序、理由与进入时机。
- **观点复核：**保留旧观点，遇到新事实后明确维持、调整或撤销；用户想买或已经持有不改变证据强度。

技术信号帮助判断走势与节奏。经营、估值及催化支持时可以提前分批布局；等待需要具体理由和机会成本，不要求所有指标同时通过。

## 安装

仓库保持根目录 `SKILL.md` 布局，沿用已有安装方式：

```bash
npx skills add stonebeast-river/analyze-markets-and-portfolio-skill
```

原有全局 Codex 安装方式：

```bash
npx skills add stonebeast-river/analyze-markets-and-portfolio-skill --agent codex --global --copy --yes
```

或将仓库内容放入个人技能目录下的 `analyze-markets-and-portfolio` 文件夹。工具运行环境见 [运行设置](references/local-runtime.md)。Python 3.12用于本版验证；可选数据连接和文档解析依赖列在 [依赖文件](scripts/requirements-optional.txt)。

## 使用

```text
用 $analyze-markets-and-portfolio 研究这只股票，判断未来数周至三个月的方向，给当前动作、入场条件、分批与失效点。

研究这只基金，穿透持仓，比较A/C等份额及替代，给配置和建仓／加仓意见。

主动找未来一至三个月的投资机会，自行筛选并研究到具体股票、ETF和场外基金，排序后给时机。
```

独立研究完成后再映射用户提供的权威持仓。没有个人金额时给清楚标注的预算情景，不推测私人资产。

## 数据与工具

公开行情来源包括腾讯、BaoStock、东方财富和Yahoo；宏观与估值使用FRED、统计局、中证、中债等路径，并主动补查公司、交易所及基金管理人的原文。注册接口使用环境变量提供凭据。

- `scripts/market_engine.py`：取数、指标、研究材料、冻结与复算入口。
- `references/`：个股、基金、自主发现、数据口径与决策流程。
- `assets/`：公开来源登记、产品费用/披露契约、交易日历和图标。
- `scripts/test_*.py`：可重复的回归检查。

KDJ采用9/3/3、K/D初值50、完整窗口和不截断J；RSI14采用Wilder平滑。国内筹码模块使用真实日价格与换手率建立明确命名的本地估算，输出分布图、成本区和初始未知库存残留。它不下载或冒充真实账户成本。详情见 [技术和来源扩展](references/technical-and-source-extensions.md)。

```bash
python scripts/market_engine.py --help
python -B -m unittest discover -s scripts -p 'test*.py'
```

## 版本与数据范围

2026-10-08扩展版已通过266项本地回归检查及代表性真实源复算。查看 [验证范围](references/validation-status.md) 和 [来源登记](references/provider-registry.md)。最新财报、事件日历与ETF净值/溢价根据具体判断补查；公共源当前可用性在每次研究时检查。

本仓库只包含可复用的 skill、代码、公开来源契约和说明。运行数据库、原始下载、个人持仓、密钥、本地路径与每日任务配置均由使用者在仓库外管理。研究意见和任何交易执行分开处理。

## License

MIT — see [LICENSE](LICENSE).
