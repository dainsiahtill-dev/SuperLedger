# Super Ledger

用于逆向工程与重建项目的独立任务台账。支持多 Agent 领取、冻结交付、不同执行者接手、受控发布、证据分层与逐句验收；网页只读，正式写入由 CLI 完成。

Python 3.11+，运行时只依赖标准库。项目名称、任务 ID、优先阶段、协调者、发布范围与运行时/MCP要求均来自配置。无需 Spore、Unity、RTK 或任何模型客户端即可运行；开发命令按当前工作区约定使用 RTK。

## 安装与启动

```powershell
rtk proxy python -m pip install --no-build-isolation -e .
rtk proxy super-ledger --project C:/Projects/MyReverseProject init --config examples/binary-format.json
rtk proxy super-ledger --project C:/Projects/MyReverseProject serve --port 5198
```

打开 http://127.0.0.1:5198/ 。`--project` 指向待管理工程；安装目录和被管理工程可以不同。init不会覆盖现有台账。也可以使用 `python -m super_ledger` 替代可执行入口。

## Agent 最短闭环

1. `candidates --owner 实际唯一执行者 --client 实际客户端 --phase core --limit 3` 查看少量候选。
2. `show 包ID 任务ID --identity` 读取最新 revision；正式 `take` 或 `take-handoff`，后者还需最新报告SHA，且必须不同执行者。
3. 只在返回的 scope 创建候选、报告和证据。使用 `publish` 按前后像及依赖SHA受控合入；`run-check` 执行真实命令并保留输出。
4. `verify` 登记 module/scene 的明确证据；`wait` 交付一个有界增量与精确下一步。只有全部原条件、独立审核和依赖满足，才允许 `end`。

认证操作通过 `--grant-stdin` 从标准输入读取 grant JSON；请在 Agent 内存中保管，不写入Git、报告、日志或网页。每次修改前重新查询 revision。wait保留grant，新的接手或协调撤销会使旧grant失效。

完整命令以 `rtk proxy super-ledger --help` 和各子命令 `--help` 为准。通用提示词见 [docs/AGENT-PROMPT.md](docs/AGENT-PROMPT.md)，配置及证据协议见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 完成量的含义

交付、公共合入、module验证、scene实测、原任务ended分别统计，可重叠。当前产物与历史证据变化时显示待复验；不删原结论、不伪增分母。候选与执行建议不授权写入。场景策略可要求Unity MCP或其他真实运行时接口；编译和静态检查不能替代场景证明。

## 验证与来源

```powershell
rtk proxy python -m unittest discover -s tests -v
```

初始抽离源于用户的 SporeUnity 台账，但不携带游戏资产、旧任务数据、原版二进制或原grant。来源与边界见 [PROVENANCE.md](PROVENANCE.md)。旧项目继续独立工作；本版本不自动迁移其运行中的授权。通用内核验证收据结构和哈希，真实执行和人工独立判断仍须由负责验收的执行者提供可复核证据。
