# 麦门省钱精算师 · mcd-saver-strategist

> 基于 **麦当劳中国 MCP** 开发的省钱点餐 Skill：
> 把「菜单 × 优惠券 × 叠加规则」的组合优化交给确定性算法，
> 让每一顿麦麦都点得明明白白、省得清清楚楚。

麦当劳程序员创意开发大赛参赛作品 · 非麦当劳官方产品。

---

## 一句话介绍

**用户说"我想吃巨无霸套餐，怎么最便宜"，它拉取门店菜单和所有可用优惠券，
用算法穷举出总价最低的合规组合，并帮你下单。**

示例：巨无霸 + 中薯条 + 可乐，直选 **¥47.00**；
用「1+1 随心配」组合后 **¥21.90**，省 **¥25.10（53%）**。

🎮 **在线试算（无需登录）**：[`docs/index.html`](docs/index.html) ——
优化算法的前端完整复刻，选好想吃的、拖动预算和热量上限，实时算出最优组合，打开即玩。
若已开启 GitHub Pages，可直接访问 `https://hujjun.github.io/mcd-saver-strategist/`。

🔎 静态示例：[`docs/demo.html`](docs/demo.html) ·
🖼️ 原理图：[`images/how-it-works.png`](images/how-it-works.png) ·
🎬 宣传动画：[`images/promo.mp4`](images/promo.mp4)

![在线试算页](docs/preview.png)

![原理图](images/how-it-works.png)

---

## 它解决什么问题

麦当劳的优惠是典型的**组合爆炸**问题：

- 菜单几十项、优惠券动辄十几张、叠加规则各不相同；
- 用券还要考虑「为凑满减而加购是否划算」；
- 用户懒得算，大模型**也容易算错**（价格、折扣、叠加口算不可靠）。

本 Skill 的核心洞察是：**取数交给 MCP，算术交给代码，表达交给 Agent。**

| 角色 | 职责 |
|---|---|
| 麦当劳 MCP | 实时菜单、价格、优惠券、营养、门店、下单 |
| `scripts/optimizer.py` | 确定性组合优化，输出总价最低的 Top-N 方案 |
| WorkBuddy Agent | 理解需求、归一化数据、讲解方案、确认后下单 |

---

## 架构

```mermaid
flowchart TD
    U[用户: 想吃X, 预算Y, 热量Z] --> A[WorkBuddy Agent]
    A -->|now-time-info| M[麦当劳 MCP<br/>mcp.mcd.cn]
    A -->|nearby/delivery stores| M
    A -->|query-meals / meal-detail| M
    A -->|auto-bind + 3路券池| M
    A -->|list-nutrition-foods| M
    M --> N[归一化<br/>menu/coupons/request.json]
    N --> O[optimizer.py<br/>确定性组合优化]
    O --> P[Top-N 最优方案]
    P --> A
    A -->|calculate-price 核价| M
    A --> Q{用户确认?}
    Q -->|是| C[create-order]
    Q -->|否| P
    C --> R[支付链接]
```

---

## 一句话安装

```bash
git clone https://github.com/hujjun/mcd-saver-strategist.git && cp -r mcd-saver-strategist/skills/mcd-saver-strategist ~/.workbuddy/skills/
```

（Windows 为 `%USERPROFILE%\.workbuddy\skills\`；MCP Token 配置见下文「安装」。）

---

## 安装

### 1. 申请麦当劳 MCP Token

前往麦当劳 MCP 开放平台 https://open.mcd.cn/mcp ，手机号登录后在「控制台」激活并复制 Token。

### 2. 配置 MCP 连接

在 WorkBuddy 左侧边栏【专家·技能·连接器】→【连接器】→ 右上角【自定义连接器】→【配置 MCP】中，
填入 [`mcp-config.example.json`](mcp-config.example.json) 的内容，
并把 `${MCD_MCP_TOKEN}` 替换为你的真实 Token（或用环境变量注入），保存后【启用】。

### 3. 安装本 Skill

把 `skills/mcd-saver-strategist/` 整个目录复制到 WorkBuddy 的用户技能目录：

```bash
cp -r skills/mcd-saver-strategist ~/.workbuddy/skills/
```

（Windows 为 `%USERPROFILE%\.workbuddy\skills\`）

装好后在对话框里直接说「我想吃巨无霸套餐，怎么点最便宜」即可触发。

---

## 使用示例

**示例 1 · 单人到店**
> 用户：我想吃巨无霸 + 薯条 + 可乐，怎么最便宜？

精算师：拉菜单 + 四路券池 → 优化 → 「1+1 随心配 ¥12.9 覆盖巨无霸和中薯条，另外单点可乐 ¥9，
合计 ¥21.90，比直选省 ¥25.10」。

**示例 2 · 预算硬约束**
> 用户：30 块钱在麦当劳能吃到什么？

精算师：以 `budget=30` 求解，返回在预算内的最优搭配，并列出各方案到手价与热量。

**示例 3 · 热量约束**
> 用户：减脂期，想吃麦当劳，800 大卡以内还要便宜。

精算师：引入 `list-nutrition-foods`，以 `max_calories=800` 求解，
给出低卡又省钱的组合（如板烧鸡腿堡 + 麦咖啡 + 圆筒）。

**示例 4 · 外送**
> 用户：帮我在麦乐送点一份午餐，别超过 40。

精算师：`delivery-query-addresses` → `delivery-query-stores` → 后续流程同上，
下单前用 `calculate-price` 核价（含配送费）。

---

## 命令行快速体验（无需 Token）

内置样例数据，可离线跑通完整优化流程：

```bash
cd skills/mcd-saver-strategist/scripts

# 看优化结果（默认到店自取场景）
python optimizer.py

# 同时输出结构化 JSON
python optimizer.py --json

# 外送场景：配送费计入总价，且仅外送可用的券参与优化
python optimizer.py --mode delivery --fee 9

# 预算 / 热量硬约束
python optimizer.py --budget 25
python optimizer.py --max-calories 800

# 跑 19 项自测（改逻辑后必跑）
python selftest.py
```

---

## 真实性对照表

| 项目 | 性质 | 说明 |
|---|---|---|
| 优化算法 | ✅ 真实 | `optimizer.py` 与在线试算页为同一套逻辑，结果可用上面命令复现 |
| 「省 53%」结论 | ✅ 真实 | 算法在示例数据上算出，非人工编排 |
| 券叠加规则 | ✅ 真实 | 保守策略：`stackable:false` 与任何券互斥，保证方案价 ≤ 实付价 |
| 菜单价格 / 热量 | 🟡 示例快照 | 结构对齐 MCP 返回，数值为演示用，以门店实时返回为准 |
| 优惠券内容 | 🟡 示例快照 | 结构对齐 MCP 四路券池归一化结果，可用性以账号实时状态为准 |
| 下单能力 | ✅ 真实 | 经 MCP 核价（`calculate-price`）→ 下单（`create-order`），本仓库页面不涉及下单 |

---

## 实测发现

开发过程中用真实 MCP 联调得到的观察（2026-10，个人账号实测）：

- **券要四路查全**：`query-my-coupons` 返回的是已入卡包的券；麦麦省的可领券需先 `auto-bind-coupons` 领取才会出现，门店券在 `query-store-coupons`。只查一个来源会漏掉最优组合。
- **券有场景属性**：实测部分门店券仅到店可用。优化器已支持 `channel` 字段（`pickup` / `delivery` / `any`），外送场景自动剔除不可用券，并把配送费计入总价参与预算判断。
- **历史订单可能为空**：`order-list` 在账号无历史订单时返回空列表，依赖它做推荐的功能必须有空态兜底。
- **营养数据可以直接用**：`list-nutrition-foods` 一次返回约 160 款餐品的多维营养数据，热量约束场景无需额外估算。

---

## 目录结构

```
.
├── README.md                      # 本文件
├── CONTEST_DECLARATION.md         # 参赛声明（官方原文，未改动）
├── MCP_INTEGRATION.md             # MCP 集成说明：Tool 清单 / 调用流程 / 业务价值
├── mcp-config.example.json        # 脱敏 MCP 配置（仅环境变量占位符）
├── workbuddy.md                   # WorkBuddy 开发对话上下文
├── LICENSE                        # MIT
├── docs/
│   ├── index.html                 # 可交互在线试算（算法的前端复刻，打开即玩）
│   ├── demo.html                  # 静态示例快照
│   └── preview.png                # 在线试算页整页截图
├── images/
│   ├── how-it-works.svg / .png    # 「省 53% 是怎么算出来的」原理图
│   └── promo.mp4                  # 宣传动画（AI 生成，仅作视觉物料）
└── skills/mcd-saver-strategist/   # ← Skill 本体
    ├── SKILL.md                   # 技能指令（Agent 加载）
    ├── scripts/
    │   ├── optimizer.py           # 确定性优惠组合优化器（纯标准库）
    │   ├── selftest.py            # 19 项自测
    │   └── sample_data/           # 离线示例：菜单/券/请求
    └── references/
        ├── mcp-tools.md           # MCP Tool 清单与字段映射
        └── coupon-strategy.md     # 5 类券建模与省钱策略
```

---

## 目标用户

- **价格敏感的学生 / 上班族**：想吃得划算，但懒得比价、算券。
- **减脂健身人群**：既要控制热量，又不想多花钱。
- **家庭 / 多人拼单**：需要在预算内配齐多人餐。
- **经常用券的"羊毛党"**：手里券多，需要最优组合方案。

---

## 技术亮点

- **确定性优化，不靠大模型口算**：所有金额由 `optimizer.py` 计算或 MCP 返回。
- **保守的叠加策略**：宁少报优惠，也不给"到店付不出"的假低价。
- **场景感知**：券的 `channel`（到店/外送）过滤 + 外送费计入总价，到店和外送给不同最优解。
- **零依赖**：纯 Python 标准库，WorkBuddy 沙箱可直接运行；在线试算页同样零依赖、单文件。
- **可核验闭环**：下单前用 `calculate-price` 复核，方案 = 实付。
- **19 项自测**：核心逻辑有断言保护，可安全迭代。

---

## 免责声明

本项目为麦当劳程序员创意开发大赛参赛作品，由参赛者独立开发，**非麦当劳官方产品**。
项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态
以麦当劳官方渠道的实时结果为准。使用麦当劳 MCP 服务须遵守其《使用条款》与《麦当劳 MCP 服务规则》。

## 许可

MIT License（见 [LICENSE](LICENSE)）。
