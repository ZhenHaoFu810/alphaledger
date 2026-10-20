# alphaledger 剩余工作计划（Day 3 → 开源就绪）

> 起止：2026-10-21 → 2026-11-02（12 天 × 2–3 h）
> **终点线：本地仓库 + wheel 全部就绪，验证通过，但 `git push` / PyPI / 发帖一律不做。**
> 现状：统计内核 3 个模块完成，23 条测试绿，头条数字已用真实模块复现。

## 0. 已完成，不再返工

| 模块 | 状态 | 钉住它的测试 |
|---|---|---|
| `stats/rank.py` 整数平均秩 | ✅ | 手算秩 / 并列 / NaN / 单调不变 |
| `stats/ic.py` 截面 RankIC | ✅ | 与 `np.corrcoef` 逐位一致（1e-12）/ 样本不足跳过 / 常数因子 NaN |
| `stats/nw.py` NW t + 精确 t 尾 | ✅ | 正自相关下 NW < iid / df=1,10,1e6 的已知 p 值 |

**已实测的数字（写进 README 和面试稿）**：200 噪声因子、300×250，最好的 `IC=+0.0105, t_iid=3.03, t_nw=3.27`，`|t|>2` 有 10/200，`|t|>3` 有 1/200，单因子 25 ms。

## 1. 依赖关系（先定这个，避免返工）

```
identity/value_fp ──┐
                    ├──▶ store/ledger ──▶ evaluate ──▶ maxstat ──▶ gate ──▶ ledger_stats
panel/load ─────────┘                                  │
                                                       └──▶ 校准测试（FPR/功效）
                                                                  │
                                                     docs / demos ┴──▶ 打包就绪
```

**三条会卡住的边**：`value_fp` 定不下来，账本的表结构就得改；`panel` 的 Ref 格式定不下来，所有工具签名都得改；`maxstat` 的输入形状定不下来，`evaluate` 存什么就定不下来。

## 2. 动手前必须先锁死的六个决定

| # | 决定 | 为什么不能边写边改 |
|---|---|---|
| D1 | **PanelRef 格式**：`{path,key,format}` 或 `{values}`；相对路径基于 `ALPHALEDGER_CWD`；错误必须回显 `resolved_path` | 四个工具共享，改一次全改 |
| D2 | **指纹字符串规范**：`v1:<hex32>`，blob 前缀 `ALFP1`，含 `panel_fp` | 一旦有人存过账本，格式就不能变 |
| D3 | **trial 唯一键**：`(fp, panel_id, horizon)` | 决定幂等与并发行为 |
| D4 | **错误码表**：`PANEL_SHAPE_MISMATCH / PATH_NOT_FOUND / TOO_MANY_INLINE_VALUES / DEGENERATE / INSUFFICIENT_DATA / LABEL_CONTAMINATION` | agent 要靠错误码自纠，不能自由发挥 |
| D5 | **engine_version 写进每条记录** | 换实现后要能分辨旧账本的统计口径 |
| D6 | **`forward` 由调用方 shift**，工具内绝不 shift | 这一条写进 `instructions`，否则会被当成 bug 反复问 |

## 3. 阶段计划

### Phase A｜identity（Day 3–4）

| 步骤 | 内容 | 验收 |
|---|---|---|
| A1 | `value_fp.py`：逐日 `2*rank` → int32 → blob（`ALFP1`+panel_fp+T+每日 t_index/n_valid/rank 数组）→ sha256 | 两次算同一面板，字节完全一致 |
| A2 | 符号不变：`fp = min(h(blob), h(反序 blob))`，`orientation=±1` 落库 | `x` 与 `-x` 同 fp，orientation 相反 |
| A3 | `normalize.py`：8 条保守规则（小写、别名表、Fraction 折叠、单位元、结合律展平、交换律排序、最短浮点、统一括号） | 每条规则 3 组 golden 对 |
| A4 | `expr_fp`：`e1:<hex16>`，**只作诊断**，不参与合并 | 同表达式必同值指纹 |
| A5 | `similarity.py`：IC 序列最大 \|corr\|，>0.95 打 `NEAR_DUPLICATE` | **只报告不合并**——合并近邻等于允许"换参数再试"不算数 |

**Phase A 完成判据**：`x` / `rank(x)` / `log(x)`（x>0）/ `2x+3` / `-x` 五种写法在同一个面板上得到 **1 个 trial、5 次 eval、1 次 sign_flip**。

### Phase B｜store（Day 5）

| 步骤 | 内容 | 验收 |
|---|---|---|
| B1 | `schema.sql`：panel / trial / trial_eval / ic_series / gate_run / event / session | 建库可重入（`user_version` 迁移） |
| B2 | `config.py`：`ALPHALEDGER_DB` > `ALPHALEDGER_HOME` > 向上找 `.alphaledger/` > `.git` 根 > `~/.alphaledger/` | 三种启动位置各一条测试 |
| B3 | 幂等写入 `ON CONFLICT(fp,panel_id,horizon) DO UPDATE … RETURNING id,n_evals` | 同参调两次 → `n_trials=1, n_evals=2` |
| B4 | 并发：`WAL` + `busy_timeout=5000` + `BEGIN IMMEDIATE` | **8 进程同时写同一 fp → 1 行、n_evals=8、无 locked** |
| B5 | 云盘降级：路径含 OneDrive/Dropbox/iCloud → `DELETE` journal + 告警 | 命中时启动日志有告警 |

> **Windows 注意**：SQLite 在 Windows 上的锁行为更严格，B4 必须在 Windows 上跑一遍，不能只在 CI 的 ubuntu 上绿。

### Phase C｜evaluate 端到端 + 第一个 demo（Day 6–7）

| 步骤 | 内容 | 验收 |
|---|---|---|
| C1 | `panel/load.py`：npz / npy / csv / parquet（parquet 走 optional extra） | 四种格式各一条测试 |
| C2 | `panel/ref.py`：PanelRef 解析 + `resolved_path` 回显 + 内联上限 200×200 | 路径错时错误里能看到真实 cwd |
| C3 | `evaluate()` 服务层：算 IC → 查/写账本 → 返回 `trial_index` + `summary` | 返回 "Trial #1 of 1" |
| C4 | `demos/noise_200.py`：一次性跑 200 个噪声因子并打印排行 | 输出与 §0 的数字一致（±0.001） |
| C5 | **MCP 握手冒烟**：先写 20 行 stdio echo server 验证协议，再套真工具 | Claude Code / dsh 都能连上 |

> **C5 是 Day 6 的最大不确定性**：`mcp` SDK 的 API 面要现场确认。若 1 小时内握不上手，立刻降级为手写 NDJSON（`Content-Length` 帧），不要在这上面耗一天。

**Phase C 完成判据**：在 Claude Code 里说"测一下这 200 个随机因子哪个最好"，返回 `Trial #137 of 200 — REJECT`。**这一场就是面试前三分钟。**

### Phase D｜maxstat + gate（Day 8–9）

| 步骤 | 内容 | 验收 |
|---|---|---|
| D1 | `maxstat.py`：块 bootstrap（`C @ X` 矩阵乘，B=2000，L=⌈T^(1/3)⌉） | T=250,N=200 单次 < 1.5 s |
| D2 | 收敛：`SE(bar_q95)/bar_q95 < 0.5%` 或 B=4000 或 8 s | 慢机器上不会超时 |
| D3 | 稳定性：`L` 与 `2L` 的 `bar_q95` 差 < 0.1σ，否则取大者 + 告警 | 构造强自相关序列触发告警 |
| D4 | 降级链：T≥60 bootstrap / 60–120 降 B / T<60 `INSUFFICIENT_DATA` | 三档各一条测试 |
| D5 | `gate/engine.py`：三态判定 + 优先级（leak > 方向 > 显著性） | 前视因子必须 REJECT 而不是 PASS |
| D6 | `what_if.required_ic_mean`：反解"要多大 IC 才够" | 与 forward 计算自洽（误差 <2%） |
| D7 | `cross_family.effective_alpha = 1-(1-α)^K` | K=10 → 0.40 |

**Phase D 完成判据**：见 §4 的 14/15 两条校准测试。

### Phase E｜ledger_stats 与可移植（Day 10）

| 步骤 | 内容 | 验收 |
|---|---|---|
| E1 | `ledger_stats`：totals / families / churn（top_reevaluated、sign_flips、near_duplicate_clusters）/ anomalies | 构造 18 次评估 12 次重复的场景，能报出来 |
| E2 | `export` / `import`：跨账本合并时 N 正确累加，指纹去重 | 两个账本各 100 次 → 合并后不是 200 |
| E3 | `cli.py`：`init` / `doctor` / `serve` / `demo` | `alphaledger doctor` 能报出 python 版本、DB 路径、numpy 版本 |

### Phase F｜测试收口与校准（Day 11）

把计划里的 16 条测试补齐。当前 23 条覆盖了 #2 的一部分与底层，剩余：

| # | 测试 | 归属阶段 |
|---|---|---|
| 1 | 200 噪声 × 20 seed → `n_pass_fwer == 0`，`bar_q95∈[3.45,3.85]` | D |
| 3 | 等价写法 5 种 → 1 trial / 5 evals / 1 sign_flip | A |
| 4 | 代数不同也不等价（`x²`、winsorize）→ 不同 fp，`0.5<sim<0.99` | A |
| 5 | T=40 → `INSUFFICIENT_DATA`，仍落库 | D |
| 6 | 前视（factor=returns）→ `LABEL_CONTAMINATION` 优先于显著性 | D |
| 7 | 常数因子 → `DEGENERATE`，不崩 | A |
| 8–9 | float32 重算不变 / 改一天两个秩则变 | A |
| 10–11 | 幂等 / 8 进程并发 | B |
| 12–13 | family 10→200 时 `bar_q95` 单调不减（容 0.03σ）/ bootstrap vs 高斯（T=2000） | D |
| **14** | **FPR：100 seed × 200 噪声，PASS 率 ≤10%** | F |
| **15** | **功效：planted 0.03、T=500，PASS 率 ≥80%** | F |
| 16 | MCP 冒烟：真起子进程，`initialize` + `tools/list` + 一次 `evaluate` | C |

> **14 与 15 必须成对**。只测 14 会做出"永远 REJECT"的工具，面试一问就穿帮。
> 14 在 CI 用 20 seed（约 90 s），100 seed 版放 `tests/calibration/`，结果贴进 `docs/CALIBRATION.md`。

### Phase G｜文档（Day 12）

| 文件 | 内容 | 判据 |
|---|---|---|
| `docs/METHOD.md` | 全部公式：RankIC 定义、NW、bootstrap max、gate 判定；每个公式标注对应函数名 | 每个公式都能点到一条测试 |
| `docs/TOOLS.md` | 四个工具的 JSON schema、返回示例、错误码表 | 能照着写客户端 |
| `docs/AUDIT.md` | 竞品审计（把计划附录那 633 行整理成 100 行结论版） | 三条可引用的具体缺陷，带行号 |
| `docs/CALIBRATION.md` | FPR/功效的实测表（多 seed） | 数字与 `tests/calibration` 一致 |
| `README.md` / `README.zh-CN.md` | 头条数字 + 30 秒上手 + 四工具表 | 陌生人 10 分钟能跑通 |
| `CHANGELOG.md` | 0.1.0 | — |

### Phase H｜打包与"开源就绪"（Day 13–14）

| 步骤 | 内容 | 验收 |
|---|---|---|
| H1 | `uv build` 出 wheel + sdist | 产物 < 300 KB |
| H2 | 干净环境装 wheel：`uvx --from ./dist/*.whl alphaledger-mcp --help` | 冷启 < 30 s（含首次解析依赖） |
| H3 | `git init` + 分阶段提交（每个 Phase 一个 commit，信息用 conventional commits） | `git log` 能读出一条清晰的故事线 |
| H4 | `ruff check` / `mypy` 干净 | 零 warning |
| H5 | 就绪评审清单（下节）逐条打勾 | 全绿 |

## 4. 开源就绪清单（最后一道闸）

- [ ] 16 条测试全绿，CI 在 py3.10–3.13 × linux/windows 通过
- [ ] 100 seed 校准：FPR 3–8%，功效 ≥80%，数字写进 `docs/CALIBRATION.md`
- [ ] `uvx` 从 wheel 冷启 < 30 s；单次 `evaluate` < 2 s
- [ ] 四个 demo 可连播：噪声 → REJECT / 真因子 → PASS / 前视 → LABEL_CONTAMINATION / 等价写法 → 同一 trial
- [ ] `README` 里的头条数字能由 `python demos/noise_200.py` 一行复现
- [ ] `docs/METHOD.md` 每个公式对应一个函数名 + 一条测试名
- [ ] `git log` 干净，无密码、无本地绝对路径、无大文件
- [ ] `LICENSE`（MIT）、`.gitignore` 覆盖 `.alphaledger/` 与 `data/*.npz`

## 5. 明确不做（做到会拖垮进度）

表达式求值器（=RCE 风险）· akshare 取数（v0.2）· 回测/组合/容量 · UI 面板 · HTTP transport / 鉴权 / 云同步 · dsh TS bundle（H 阶段有富余才做）· 在线 FDR（LORD/SAFFRON）· 谱方法 N_eff · 用 LLM 推断假设族

## 6. 三个风险与回退

| 风险 | 触发信号 | 回退 |
|---|---|---|
| MCP SDK 握不上手 | Day 6 上午 1 小时没跑通 `initialize` | 手写 NDJSON（`Content-Length` 帧，约 120 行），协议本身很简单 |
| bootstrap 太慢 | T=250,N=200 单次 > 1.5 s | 降 B 到 1000 + 收敛提前退出；仍慢则改用 `float32` 与分块 matmul |
| 指纹误合并 | 测试 4 里 `x²` 与 `x` 被判同 fp | 说明秩编码有 bug（`x²` 对正数单调、对负数不单调，秩必然不同）——这是硬 bug，必须修到测试绿，不许放宽断言 |

## 7. 终点线定义

**到此为止，不越线**：

| 做完 | 不做（需用户逐条确认） |
|---|---|
| 本地 `git init` + 分阶段提交 | `git push` / 建远端仓库 |
| `uv build` 出 wheel 并在本地装通 | `twine upload` / PyPI 发布 |
| README / docs 全部写完 | 发帖（X / V2EX / 掘金） |
| 四个 demo 可跑 | 给 dsh 提 issue / 发插件到 catalog |

一句话：**到 11-02，东西已经是"可以开源的状态"，但开源这个动作留给用户决定。**
