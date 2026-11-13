# 从零创建项目、工作包和任务

安装最新wheel后，从任意目录执行。下例使用 `C:/Projects/FormatLab`；`lead-session` 是创建时选定的实际协调者，后续管理命令必须一致。worker领取使用各自不同的实际owner/client。

## 1. 创建空项目

```powershell
rtk proxy python -m super_ledger --project C:/Projects/FormatLab init --id format-lab --name "格式逆向项目" --template binary --owner lead-session --client codex
rtk proxy python -m super_ledger --project C:/Projects/FormatLab project show
```

模板支持generic、binary、unity。unity模板启用sceneRequired及Unity MCP证据门槛，入口默认Assets/Scenes/Main.unity；实际场景不同，应初始化前使用自定义 `--config` 明确设置。`--config`与空项目字段不能混用。第一次无需预先准备整个任务树。

## 2. 创建第一个工作包

从刚才的project show结果取revision，替换下面的 `REVISION`。每次变更后旧revision失效；其他worker登记进展也会使整项目revision变化，重新查询后再提交。

```powershell
rtk proxy python -m super_ledger --project C:/Projects/FormatLab package create FORMAT --title "文件格式" --phase core --priority 10 --owner lead-session --client codex --expected-revision REVISION --reason "建立首个核心工作包"
rtk proxy python -m super_ledger --project C:/Projects/FormatLab package list
```

工作包可为空。phase来自配置，初始模板包含core/support/later；数值较小的priority更优先。

## 3. 创建第一个子任务

复制并按实际原始材料调整 `examples/first-task.json`。文件必须UTF-8，包含稳定ID、目标、原验收句、依赖和准确publicTargets；允许范围来自项目policy.publicPaths。

也可以在编辑器将下面内容另存为C:/Plans/first-task.json，并按实际目标修改：

```json
{"id":"read-header","title":"读取头部","objective":"从实际样本实现头部读取","acceptance":["字段来源可以复核","真实消费者覆盖正常和截断输入"],"dependencies":[],"publicTargets":["src/header.py"],"consumer":"src/header.py","counterexamples":["截断输入"]}
```

```powershell
rtk proxy python -m super_ledger --project C:/Projects/FormatLab project show
rtk proxy python -m super_ledger --project C:/Projects/FormatLab task create FORMAT --spec C:/Plans/first-task.json --owner lead-session --client codex --expected-revision REVISION --reason "拆出首个可验收任务"
rtk proxy python -m super_ledger --project C:/Projects/FormatLab task list --package FORMAT
rtk proxy python -m super_ledger --project C:/Projects/FormatLab doctor
rtk proxy python -m super_ledger --project C:/Projects/FormatLab serve --port 5199
```

现在worker可以candidates→show --identity→take；交付与审核流程见README。网页自动读取正式新增任务，空页面会提示下一条创建命令。

## 后续组织与拆分

- `package update FORMAT --title ... --phase core --priority 5`：调整显示名、阶段和调度优先级。
- `project update --name ... --description ...`：更新项目展示信息。
- `task update FORMAT read-header --spec revised-task.json`：仅调整从未领取的草稿。依赖也在spec内更新；缺失依赖和循环会拒绝。
- `task split FORMAT read-header --spec children.json`：children.json是任务对象数组。父任务保留原验收句，转为依赖全部子任务的gate，状态仍未完成；子任务记录parentTask。不得把已交付/已审核任务重新拆成未领取状态。
- `catalog apply --config proposed-project.json --dry-run`：整批预演新增工作包/任务和草稿变更；去掉dry-run才正式提交。

上述修改命令均需owner/client、最新expected-revision和reason。目录修改保留原ID和原历史，不支持直接删除任务；已经开始的责任发生变化时创建跟进任务，并写明依赖与原因。任务拆分会明确新增子任务，父合同不会因此自动ended。

## 事务恢复

config与registry不能靠两个独立文件写入假装原子提交。系统先冻结前后版本及journal，再写配置和权威状态；中断时阻止其他任务继续写。初始化中断也使用相同恢复流程。

```powershell
rtk proxy python -m super_ledger --project C:/Projects/FormatLab doctor
rtk proxy python -m super_ledger --project C:/Projects/FormatLab catalog recover --transaction TRANSACTION_ID --owner lead-session --client codex
```

doctor返回ready=false时退出码为1。恢复仅接受冻结的前/后状态，发现第三方修改会拒绝覆盖。直接编辑已初始化super-ledger.json仍会被身份校验拒绝；运行时、场景门槛和协调者变更需要单独的政策迁移能力。
