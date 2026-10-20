# alphaledger

**因子研究的试验账本。** 每一次评估都是从彩票箱里抽一次；alphaledger 记账，并且在不知道你抽过多少次之前拒绝下判断。

## 20 秒看懂

一条命令，300 只股票 × 250 个交易日，**每一个因子都是纯噪声**：

```
$ python demos/noise_200.py

  best factor     fp=v1:32625af66…
  RankIC          +0.0105
  t (iid / NW)    3.03 / 3.27
  p_single        0.00273   <- 看起来可以发表
  family          200 trials
  bar_q95         3.73      <- 真因子需要的门槛
  p_family        0.351     <- 是运气
  verdict         REJECT
```

RankIC 1% 对真实因子来说是很正常的量级——**所以看数值大小根本分不出真假，唯一的判别信息是你抽了多少次**。

研究员一天试五个想法，还记得住。Agent 一小时试两百个，而且每次会话都从零开始。

## 为什么不是又一个工具箱

现有工具都擅长**算**：这边 59 个工具，那边 40 个，IC/ICIR/回测到处都是。它们缺的是**状态**——函数没法告诉你，这已经是你试的第 137 个动量变体。

alphaledger 是另一件事：一个账本，上面放四个工具。它在数完整个家族之前拒绝下结论，而这个数字来自账本，**永远不接受调用方传进来**。

（`docs/AUDIT.md` 有三份现有实现的逐行审计。）

## 装上

```bash
uvx alphaledger-mcp
```

Claude Code：

```bash
claude mcp add alphaledger -- uvx alphaledger-mcp
```

DeepSeek Harness，在 `$DSH_HOME/profiles/<name>/cordis.patch.yml` 加一段：

```yaml
- insert:
    - id: alphaledger
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: alphaledger
        transport: stdio
        command: uvx
        args: ['alphaledger-mcp']
        failOnStartupError: true
```

工具会以 `mcp__alphaledger__evaluate` 的形式出现。不需要 API key，不联网，数据不出本机。依赖只有 numpy 和标准库——scipy 会让安装体积翻倍、冷启动多几秒。

## 四个工具

| 工具 | 回答什么 |
|---|---|
| `fingerprint` | 这个因子我试过吗？（不消耗试验次数） |
| `evaluate` | IC 多少，这是第几次试验？ |
| `gate` | 过了家族校正吗？差多远？ |
| `ledger_stats` | 已经试了多少，哪里在打转？ |

`PASS` 必须满足 `p_family <= alpha`。`p_single` 会报出来，但永远不算证据。

## 账本拒绝做的三件事

**不把 `rank(x)` 算成新因子。** 身份是秩模式（整数哈希），所以 `x`、`rank(x)`、`log(x)`、`2x+3` 是**一次试验、四次评估**。翻符号也识别为同一试验，记为 `sign_flip`——这是家族悄悄膨胀最常见的方式。

**不合并近似因子。** 相关性 0.97 的两个因子会被标成 `NEAR_DUPLICATE`，但不会合并。合并等于允许"我只改了一个参数"逃脱计数，而那正是要防的。

**不让泄漏因子通过。** 与未来收益秩完全相同的因子会被判 `LABEL_CONTAMINATION`，**先于显著性检查**——因为那是唯一一种"数字看起来最好"的情形。

## 不做什么

不做数据层（喂它面板；akshare 适配器在计划里）、不做回测引擎、不做组合优化、不做 UI。它只判断一条 IC 序列，然后记账。

## 文档

- [`docs/METHOD.md`](docs/METHOD.md) — 每个公式，对应函数名与钉住它的测试
- [`docs/TOOLS.md`](docs/TOOLS.md) — 接口、错误码、宿主接线
- [`docs/AUDIT.md`](docs/AUDIT.md) — 三份现有实现的逐行审计
- [`docs/CALIBRATION.md`](docs/CALIBRATION.md) — 实测误报率与功效

## 状态

0.1.0。统计内核、身份判定、账本、MCP 接口已实现并通过测试（91 条）。akshare 适配器、OOS 测试锁、完整扰动协议在 v0.2。

## 许可

MIT
