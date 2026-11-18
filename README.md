# 法治水平与数字金融发展：跨国横截面分析

第 1–6 步均已完成。**[点击这里查看完整 Python 代码](analysis.py)**。脚本从 `data/` 下的输入文件重新生成全部输出；`outputs/` 中保存了本次运行的结果。

## 课堂演讲

[下载 5 分钟英文 PPT](presentation/fin445_5min_english.pptx)。共 5 页，每页的英文讲述内容写在 PowerPoint 演讲者备注中；第 3 页散点图可在 PowerPoint 中编辑。

## 代码过程与入口

| 步骤 | 代码位置 | 生成的主要文件 |
| --- | --- | --- |
| 1. 读取、清洗、按 ISO3 合并 | [`merge_step1()`](analysis.py#L212) | `outputs/merged_all.csv`、`outputs/unmatched_countries.csv` |
| 2. 统计缺失并形成完整样本 | [`missingness_step2()`](analysis.py#L272) | `outputs/missingness.csv`、`outputs/merged.csv` |
| 3. 描述统计和绘图 | [`descriptives_step3()`](analysis.py#L304) | `outputs/descriptives.csv`、三张 PNG 图 |
| 4. M1、M2、八个 M3 回归 | [`regressions_step4()`](analysis.py#L390) | `outputs/regressions.csv`、`outputs/m3_factors.csv` |
| 5. 分组、VIF、Cook's distance | [`robustness_step5()`](analysis.py#L465) | `outputs/robustness_regressions.csv` 等 |
| 6. 自动生成结论 | [`results_summary_step6()`](analysis.py#L585) | `outputs/results_summary.md` |

[脚本末尾的主程序](analysis.py#L708)按上表顺序调用六个函数。所有回归用 `statsmodels.OLS(...).fit(cov_type="HC3")`，并在运行时把结果打印到终端。

## 从 GitHub 下载并运行

在终端执行以下命令（先安装 Python 3.12，使 `python3.12` 命令可用）：

```bash
git clone https://github.com/wendiye64-hub/Fin445.git
cd Fin445
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python analysis.py
```

运行结束后查看 `outputs/regressions.csv`、`outputs/m3_factors.csv` 和 `outputs/results_summary.md`。三份分析输入 CSV 已包含在仓库的 `data/` 中，因此正常运行无需联网；脚本不会插补缺失值。

如果是在已经配置好虚拟环境的本地项目目录中，只需运行 `.venv/bin/python analysis.py`。

## 数据来源和年份

| 文件 | 来源与代码 | 年份 | 单位 |
| --- | --- | --- | --- |
| `data/wjp.csv` | [WJP Rule of Law Index 2024 官方 CSV](https://worldjusticeproject.org/rule-of-law-index/data/2024.csv)；总分和 Factor 1–8 | 指数 2024 | 0–1 分 |
| `data/digital_finance.csv` | [World Bank Global Findex 2025 国家级 CSV](https://www.worldbank.org/en/publication/globalfindex/download-data)；官方原始文件保存在 `data/findex_raw_2025.csv`；`g20_any` = 过去一年做过或收到过数字支付的 15 岁以上成年人比例；`account_t_d` = 账户拥有率 | **调查 2024** | 已换算为百分比 0–100 |
| `data/controls.csv` | [World Bank WDI API](https://api.worldbank.org/v2/)；`NY.GDP.PCAP.CD` = 人均 GDP，`IT.NET.USER.ZS` = 互联网使用率，`SP.URB.TOTL.IN.ZS` = 城镇人口占比 | 2024 | 美元、%、% |

数字金融主指标选 `g20_any`，因为它直接衡量数字支付使用。“Global Findex 2025”是报告名称，**其最新调查数据为 2024 年**。本项目使用同年的 WJP、Findex 和 WDI，因而牺牲样本量：2024 年数字支付值与 142 个 WJP 国家中只有 85 个重合，最终完整样本为 84 国。账户拥有率保留为辅助描述变量，不作为数字支付的替代。

世界银行 API 的 `FX.OWN.TOTL.ZS` 代码已核实存在；本项目实际采用官方 Findex CSV 中的 `account_t_d`，与主指标 `g20_any` 同属 2024 年调查。所有 Findex 变量均在原始 CSV 表头核验后提取。

三个 WDI 控制变量统一取 2024 年。世界银行国家元数据中 `region.id = NA` 的地区和收入组汇总项均已剔除。WJP 官方文件自带 ISO3 国家代码，因而没有通过名称猜测国家代码。

## 回归代码

完整实现见 [`analysis.py` 第 390–463 行](analysis.py#L390-L463)。核心设定如下；M3 每次只放入一个法治分项：

```python
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm

OUTPUTS = Path("outputs")
data = pd.read_csv(OUTPUTS / "merged.csv")
data["log_gdp_per_capita"] = np.log(data["gdp_per_capita"])
outcome = data["digital_payment_pct"]
controls = ["log_gdp_per_capita", "internet_users_pct", "urban_population_pct"]

def fit(predictors):
    design = sm.add_constant(data[predictors], has_constant="add")
    return sm.OLS(outcome, design).fit(cov_type="HC3")

models = {
    "M1": fit(["wjp_overall"]),
    "M2": fit(["wjp_overall", *controls]),
}
for number in range(1, 9):
    factor = f"wjp_f{number}"
    models[f"M3_F{number}"] = fit([factor, *controls])

for name, result in models.items():
    print(name, "N =", int(result.nobs), "R² =", round(result.rsquared, 4))
    print(result.summary())
```

这段可在项目根目录单独运行；若要生成全部数据、图表和结果文件，请执行上面的 `analysis.py`，其中还包含满秩检查、CSV 保存和多重检验校正。

第 1–2 步只依赖 Python 标准库；图表和统计使用 pandas、NumPy、Matplotlib、Seaborn 与 statsmodels。脚本读取 `data/` 下三份 CSV；三份文件齐全时可离线运行。若后两份不存在，会尝试从世界银行官方数据源获取并生成。WJP 官方 CSV 是转置表，脚本会按其 ISO3 行转换为国家记录。`outputs/merged_all.csv` 是 142 个 WJP 国家的左连接底表，保留缺失；`outputs/merged.csv` 是后续描述统计和回归使用的完整样本，**最终 N = 84**。

完整样本要求数字支付、账户拥有率、WJP 总分及 8 个分项、三个 WDI 控制变量均有有效值，且人均 GDP 大于零（供后续取对数）。原始缺失和顺序筛选新增剔除数见 `outputs/missingness.csv`。57 个 WJP 国家缺少 2024 年数字支付值；在剩余国家中，Kosovo 因互联网使用率缺失而被排除，总计排除 58 个国家。原有 50 个高收入国家中仅 6 个进入完整样本。被排除国家及原因见 `outputs/excluded_countries.csv`。没有插补。

`outputs/descriptives.csv` 给出 14 个分析变量的 N、均值、样本标准差、最小值和最大值。图表为 `outputs/histograms.png`（所有变量；人均 GDP 使用对数横轴）、`outputs/wjp_vs_digital_payments.png`（含一元线性拟合、N 和 R²）、`outputs/correlation_heatmap.png`（Pearson 相关系数，含 8 个 WJP 分项），均以 300 dpi 保存。

## 回归设定

被解释变量是数字支付率（百分点），所有模型均用相同的 84 国样本，并以 statsmodels OLS 估计、使用 HC3 稳健标准误：

- M1：WJP 总分。
- M2：WJP 总分 + 人均 GDP 的自然对数 + 互联网使用率 + 城镇人口占比。
- M3_F1 至 M3_F8：每个模型用**一个** WJP 分项替换 M2 的总分，保留相同的三个控制变量；总分和分项不同时进入回归。

`outputs/regressions.csv` 按模型和系数逐行保存估计值、HC3 标准误、p 值、R² 和 N；`outputs/m3_factors.csv` 汇总八个分项的核心结果，并包含 Benjamini–Hochberg 校正后的 q 值。WJP 分数范围为 0–1，系数表示分数增加 1.0 时数字支付率的百分点差；增加 0.1 分对应系数的十分之一。回归关联本身不能解释为因果效应。

八个 M3 分项的原始 p 值和校正后 q 值同时保留，不能仅凭最小的 p 值断定该分项必然“最强”。

## 稳健性检验

- `outputs/subgroup_m2.csv`：按世界银行原始四档收入组分别重跑 M2，均使用 HC3。高收入组仅 6 国、低收入组仅 12 国，模型含 5 个参数，其标准误和 p 值尤其不稳定。
- `outputs/subgroup_m2_pooled.csv`：将低及下中等收入、上中等及高收入分别合并成两组（各 42 国）重跑 M2，以减少小样本问题。
- `outputs/vif.csv`：在完整样本的 M2 设计矩阵（含截距）上计算四个解释变量的 VIF；表中不报告截距项。
- `outputs/cooks_top5.csv`：列出基准 M2 中 Cook's distance 最高的五国，并同时报告杠杆值。Cook's distance 衡量观测对拟合的影响，杠杆值是另一项诊断。
- `outputs/robustness_regressions.csv`：保存基准 M2、四个原始收入组 M2、两个合并收入组 M2、剔除上述五国后的 M2 的全部系数、HC3 标准误、p 值、R² 和 N。剔除五国后的样本量为 79。该筛选仅用于敏感性检验，不改动主分析的 84 国样本。

## 结果解读

`outputs/results_summary.md` 用通俗语言总结显著性、效应大小、稳健性和局限性。三套数据均取 2024 年，但同年横截面关联仍不能证明因果，且高收入国家大量缺失。脚本设定 NumPy 随机种子为 2025；当前流程没有随机抽样或插补。
