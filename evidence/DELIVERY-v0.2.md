# v0.2 首次建账与持续规划交付

已补齐空项目初始化、generic/binary/unity模板、project show/update、package list/create/update、task list/create/update/split、catalog apply/dry-run/recover、doctor。准确可复制命令见docs/FIRST-PROJECT.md，指南同时随wheel提供并可从工作台使用说明打开。

目录更新核对原协调者、整项目revision和原因，复用同一Catalog事务。初始化与目录更新均先落冻结journal，再提交config/registry；中断阻止继续写并允许精确恢复，第三方状态受到保护。仅未领取草稿可变更合同；新增任务保留现有槽位与grant；拆分保留父原验收句并转成依赖子任务的gate，不能自动ended。

55项完整Python回归通过，Node协议与语法检查通过。隔离Python从wheel导入，真实执行从空项目到第一个工作包和任务的CLI，doctor健康，HTTP无重启显示新增任务。实际浏览器确认0包0任务的引导、1包1任务的显示和原合同详情；没有把创建计为交付或完成。证据见lifecycle-v0.2.json、browser-v0.2.png及release-0.2.0.json。

本轮不包含历史Spore台账导入、已领取合同重写、任务物理删除、运行时/协调者/sceneRequired政策迁移及网页写表单。已有CLI交付、发布、模块/场景和独立end门槛均继续执行。需要调整已经开始的工作时创建跟进任务；已验证成果仍应按原任务原责任收尾。
