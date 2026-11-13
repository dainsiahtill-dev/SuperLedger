# 给任意Agent的持续执行提示词

将实际工程路径、owner与client替换后使用；不要照填OWNER或冒充协调者。

首次建账由实际协调者按FIRST-PROJECT.md执行：init→project show→package create→task create→doctor。worker发现空目录或缺少任务时应交付明确建账请求，不能冒用协调者修改既有责任。新增与拆分使用正式目录命令；所有旧报告和已领取合同保留。

```text
在 PROJECT 推进已配置的逆向主线。读AGENTS.md、super-ledger.json和台账；尊重暂停指令，不自行启动其他模型客户端。运行时验收按project.runtime使用真实接口/MCP，静态或编译不能冒充场景。
先执行 python -m super_ledger --project PROJECT candidates --owner 实际唯一执行者 --client 实际客户端 --phase core --limit 3。候选只读；优先复用waiting成果、已发布实现和现有证据，每轮只补一个明确剩余事实或消费者反例，不重写整条。
对选中任务 fresh show 包 任务 --identity，再用其revision正式take；waiting用take-handoff并带最新report SHA，必须不同实际执行者。保存返回grant在内存，仅在其scope写入，认证CLI通过stdin传grant。竞争失败换下一候选或下一页，不反复全库扫描。
发布前核准本任务publicTargets与公共前后像，按publish受控合入；保留真实命令、失败、退出码、输入/产物SHA、MCP操作和截图，分别登记module/scene。已有发布先复验，只有实际必要性才补原始取证。
有界交付完成就wait并写准确nextAction与blocker，释放长期占用；全部原验收句、依赖、当前证据和独立审核满足才end。不要直接改registry、冻结报告、原验收句或完成分母。每次修改前重新查询revision。
按工程授权提交/推送成果。汇报只写任务ID、实际变化、验收证据、提交SHA、剩余缺口，然后持续下一轮；需要共享运行时/协调者动作时交付可执行验收请求，不重复造算法。
```

开发环境如要求RTK，在每个shell命令前使用 `rtk proxy`。Super Ledger本身不强制某一种Agent、模型、CLI或运行时。
