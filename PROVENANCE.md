# 来源与抽离边界

本项目根据用户要求，从其 SporeUnity 工程的任务台账抽离并通用化。

- 源仓库：`https://github.com/dainsiahtill-dev/SporeUnity`
- 确定的源提交：`112a8d1635f9682c9a91c4f4818d390fb2e99e96`
- 抽离日期：2026-11-14。
- 来源机制：`workbench_maintenance.py` 的原子写入/跨进程锁；`workbench_registry_store.py` 的内容寻址历史与完整校验；`cell_agent_workbench.py` 的领取/交接/精确验收规则；`cell_workbench_integration.py` 的前后像和可恢复发布协议；`workbench_projection.py` 的只读快照/缓存协议；工作台四份HTML/CSS/JavaScript资源。

状态机和投影按独立配置接口重新拆分，未复制4000行的专用生成器。网页资源保留原布局、无障碍与刷新逻辑；包、任务、阶段、运行时、命令和缓存命名改成配置驱动。新的schema统一使用 `super-ledger/*@1`。

不包含原游戏资产、提取模型、反编译输入、Unity工程、第三方二进制或旧执行者授权；不导入、不调用、不依赖原仓库。原台账的234条任务和冻结历史继续保留在原项目。本版本不自动转换已有活跃grant或修改已初始化合同；此类迁移需要显式可审计的后续工具。

这是用户指定的内部项目交付。来源根目录未发现许可证声明；本次不擅自为继承代码授予MIT/Apache等开源许可。对外分发前应由代码权利人确定许可。
