# 配置、授权与证据协议

Super Ledger将工程定义、权威状态、不可变证据和只读页面分开。`super-ledger.json`定义原合同，`.super-ledger/registry.json`记录当前执行权，SHA对象记录历史，`ledger-work/包/任务/attempts/随机ID`保存执行者成果。网页快照可删除重建；它们从不授权修改。

## 项目配置

完整示例见 `examples/binary-format.json` 与 `examples/unity-runtime.json`。项目可放在任意独立目录。ID采用字母数字、下划线和连字符，最大64字符；不要求CRE或L编号。任务依赖用 `包/任务`，拒绝未定义依赖和真实任务环。

`project.runtime`提供运行时名称、入口和 `verificationMethod`。`policy.coordinator`指定行政恢复执行者；`publicPaths`是可发布路径前缀；每条任务的 `publicTargets`进一步限定它可发布的准确文件。`sceneRequired`决定结束是否必须含真实场景证据。`snapshotKeep`/`snapshotBytes`控制派生缓存。

初始化持久绑定完整规范化配置SHA。修改协调者、运行时、验收句或场景策略后，即使重开CLI也会拒绝现有台账；v0.1不提供静默修改合同或历史转换。需要新增任务时请先准备完整项目配置再初始化；对已有台账做合同迁移属于需单独实现的显式管理能力。

## 执行权

grant包含packageId、taskId、owner、client、attempt、generation、scope、token与revision。registry仅存tokenHash；网页、候选、报告和Git均不保存grant。CLI需要认证时从stdin读取grant。owner指实际执行者，client指执行程序；改显示名不能构成独立审核。

所有正式修改在OS文件锁内完成完整历史校验→鉴权→fresh revision CAS→变更→原子提交。sequence覆盖同秒ABA。轻量候选不展开历史，明确 `admissionEvaluated:false`；正式动作仍会拒绝缺失/坏历史。

`wait`冻结非空UTF-8 Markdown报告并记录SHA，保留当前grant供必要时resume。`take-handoff`要求waiting、不同owner、当前revision和报告SHA，生成新的attempt/token/scope并继承前任记录；旧grant随之失效。协调requeue保留历史并撤销授权，不声称停止任何外部进程。

## 正式发布

`publish 包 任务 --manifest 路径 --grant-stdin --expected-revision SHA` 消费当前scope中的 `super-ledger/publication@1`：

```json
{
  "schema": "super-ledger/publication@1",
  "files": {"src/parser.py": {"candidate": "ledger-work/P/T/attempts/ID/parser.py", "preimage": null, "postimage": "64位SHA"}},
  "dependencies": {"samples/input.bin": "64位SHA"},
  "verification": {"path": "ledger-work/P/T/attempts/ID/check.json", "sha256": "64位SHA"}
}
```

preimage为null表示准确的新建状态。发布检查全局范围、任务范围、路径/链接/大小写边界、原文件SHA、候选SHA、依赖SHA及真实通过收据，冻结全部输入后先落journal，再写公共文件，最后提交正式收据。中断后pending阻止普通修改；`recover`只恢复冻结事务，任何第三种公共内容都会阻止覆盖。v0.1明确拒绝删除与移动发布。

## 实测与结束

`run-check --receipt 当前scope/check.json --grant-stdin --expected-revision SHA -- <真实argv>`执行命令并保留stdout/stderr哈希。输出重名时先拒绝再执行，失败和超时保留实际退出码（超时124）。`checks:1`只表示执行一条命令；测试内断言数量应由具体验证器明确报告。

`super-ledger/verification@1`字段包括contractSha256、tier(module/scene)、command数组、整数exitCode=0、正整数checks、inputs与artifacts的路径→SHA映射，以及当前scope内receipts引用。所有收据的command/exitCode/checks必须一致。scene还必须提供配置的method、toolCalls与有有效图片字节的screenshots。字段与哈希验证不能替代可信的实际运行和独立判断，维护者须检查原始命令输出与MCP日志。

`super-ledger/completion@1`包括contractSha256、前任submissionSha256、acceptance数组（原text逐字原序、passed=true）、当前审核attempt已正式登记的verification引用。结束还要求不同执行者的implementation交接、原报告未变、依赖仍有效ended、所有任务publicTargets已受控合入并被当前证据覆盖、消费者绑定，以及配置要求的scene。模块通过和有限交付不会自动结束原任务。

结束后的证据漂移保留原ended记录，当前匹配量减少，依赖不能借旧结论通过。不提供重写冻结证据、直接改registry或伪造计数的快捷方式。

## 网页与缓存

`serve`仅绑定loopback，网页只读。只提供随包静态资源和允许类型的attempt证据，不把整个工程作为HTTP根。身份接口白名单脱敏，始终writeAuthorized=false；复制接手命令时重新取身份。配置缓存按projectId隔离。

不可变快照分片带SHA和字节数。建造与清理共用锁，隐藏staging不参与清理；当前代始终保留，单个当前代超预算会明确报告。非当前被淘汰的代返回410并刷新manifest；当前损坏维持错误，不能假装正常过期。历史量、当前匹配量和原任务数独立展示，阶段可重叠。
