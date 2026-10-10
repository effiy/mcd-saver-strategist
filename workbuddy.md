# WorkBuddy 开发对话上下文 · workbuddy.md

> 本文件记录「麦门省钱精算师」使用腾讯 WorkBuddy 开发过程中的关键对话与决策，
> 用于核验本项目符合 WorkBuddy 专项奖励的联动条件。

## 一、开发环境

- 开发工具：腾讯 WorkBuddy（智能体）
- 工作目录：`F:/code/McDonald`
- 使用的 Skill 开发能力：`skill-creator`（Agent Skill 规范）
- 运行时：Python 3.13（纯标准库，无第三方依赖）

## 二、开发过程对话摘要

### 第 1 轮 · 了解活动

**用户：**
> https://github.com/M-China-Official/mcd-developer-innovation-challenge
> 了解这个 git 仓库的活动，按照开发 Skill 的要求，在当前仓库开发

**WorkBuddy：**
1. 读取活动仓库，梳理出活动规则：基于麦当劳 MCP 开发 Skill，发布到公开 GitHub 仓库并提交 Issue 报名，按 Star 排名。
2. 拉取 `activityGuidelines.md`、`CONTEST_DECLARATION.md` 与 `mcd-mcp-server` 工具清单。
3. 归纳出**必交文件清单**：`README.md`、`CONTEST_DECLARATION.md`、`MCP_INTEGRATION.md`、`mcp-config.example.json`、源代码、（可选）`workbuddy.md`。
4. 梳理麦当劳 MCP 的 30+ Tool 能力，向用户提出 4 个可选项目方向。

### 第 2 轮 · 确定方向

**用户：** 选择「麦门省钱精算师」方向。

**WorkBuddy 的决策：**
- 选题理由：优惠券组合优化是「用户懒得算、大模型算不准」的典型场景，
  且有明确的确定性解法（组合优化），技术内核扎实、实用价值高。
- 架构决策：**取数交给 MCP，算术交给代码，表达交给 Agent**，
  避免让大模型口算价格导致出错。

### 第 3 轮 · 开发实现

**WorkBuddy 的产出：**
1. 用 `skill-creator` 规范初始化 Skill 目录结构（`SKILL.md` + `scripts/` + `references/`）。
2. 实现 `scripts/optimizer.py`：把优惠券抽象为 5 类（单品改价/折扣/满减/组合价/赠品），
   在「菜单 × 券」组合空间里做带剪枝的穷举，输出总价最低的 Top-N 方案。
3. 编写 `scripts/selftest.py`：19 项断言覆盖各券型、叠加互斥、预算/热量过滤、券渠道过滤、外送费结算与确定性。
4. 编写 `scripts/sample_data/`：可离线跑通的脱敏示例数据。
5. 编写 `references/mcp-tools.md`（Tool 清单 + 字段映射）与
   `references/coupon-strategy.md`（券建模与省钱策略）。
6. 编写 `SKILL.md`：定义触发条件、四步工作流、硬性约束。

### 第 4 轮 · 验证与交付

**WorkBuddy 的验证：**
- 运行 `python optimizer.py`：示例请求下最优方案 ¥21.90（原价 ¥47.00，省 53%）。
- 运行 `python selftest.py`：**19 passed, 0 failed**。
- 补齐参赛文件：`README.md`、`MCP_INTEGRATION.md`、`mcp-config.example.json`，
  并以官方原文生成 `CONTEST_DECLARATION.md`。

## 三、关键技术决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| 优化方式 | 确定性代码穷举，而非大模型推理 | 价格计算必须可复现、可核验 |
| 券建模 | 抽象为 5 类 | 覆盖现有券型，且便于扩展新券 |
| 叠加策略 | 保守（宁少报不多报） | 保证方案价 ≤ 实付价，杜绝"假便宜" |
| 依赖 | 纯标准库 | WorkBuddy 沙箱可直接运行，零安装成本 |
| 数据 | 示例数据脱敏 | 符合参赛声明的信息安全要求 |

## 四、结论

本项目全程使用腾讯 WorkBuddy 完成**需求分析 → 方案设计 → 编码实现 → 测试验证 → 文档交付**，
Skill 本体（`skills/mcd-saver-strategist/`）可直接安装到 WorkBuddy 使用。
