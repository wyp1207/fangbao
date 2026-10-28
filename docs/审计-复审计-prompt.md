# 复审计：核对上一轮审计的 8 处修复 + 现在还剩什么

你是外部审计方。仓库：当前工作目录。上一轮审计报告：`docs/reviews/independent-audit-20261028.md`。
刚提交了修复 `f0205f0`（以及未提交的小改动：notify 钉钉加签/短信校验/标签）。

## 任务
1. 逐条核对上一轮审计的 **E17 八条** 和 **A1/A2/B9/C13/D14** 主要缺陷，判断：
   已修复 / 部分修复 / 未修复，给文件:行号证据。
2. 特别验证这几个具体缺陷是否真的修好（读代码 + 跑测试，不要只看 commit message）：
   - 重启恢复：`mark_stale_runs` 是否被 main 调用、是否还会 NameError
   - 取消：是否回读 get_order，未停时是否写 failed
   - 接管：是否真的调 adapter.cancel
   - 巡航暂停：`_wait_if_paused` 是否在循环里生效
   - 点位锁：抢不到是否跳过
   - X30：是否还只执行第一个动作
   - 报警升级：是否排除搁置、无 tier=2 时是否还标记 escalated
   - CI：`server/requirements.txt` 是否存在、CI 是否能到测试步
3. 给出**当前仍缺的清单**，按"是否真机才能做"分两类：
   A. 代码/部署能做的（列最多 10 条，标影响）
   B. 必须真机/现场/HIL 才能做的
4. 直接回答：现在能不能说"只剩真机联调"？如果不能，一句话说清还差什么。

## 约束
- 只读 + 可跑测试（`cd server && python -m pytest -q`），不改任何文件。
- 输出到 `docs/reviews/independent-audit-round2-20261028.md`，中文，结论先行。
