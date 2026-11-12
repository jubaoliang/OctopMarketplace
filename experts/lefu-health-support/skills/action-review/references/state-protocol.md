# 当前状态协议 v1

这是单人私人专家的可见行动状态，不是临床档案。仅在用户明确请求保存或更新后使用；不要预先复制示例到 health/current.json。

## 内容

格式参考 `skills/action-review/references/current-state.example.json`。示例是虚构的，不能当作当前用户信息。字段固定为：

- `schema_version`：1。
- `revision`：首次保存 1，每次修改加 1。
- `subject`：self；仅为当前私人专家的使用者维护一份状态。不代表已完成实名核验。
- `updated_at`：含时区的 ISO 时间，通过 current_time 取得。
- `goal`：当前用户确认的目标，可为空字符串。
- `constraints`：最多 12 项，仅直接相关的已确认条件；每项含 text、source、as_of。source 为 user_report / user_file / device_connector；本版未接设备，不能用 device_connector。
- `actions`：最多三项，每项含 id、text、status、confirmed_at、observation、review_on、reason。无安排的 review_on 为 null。
- `unknowns`：最多八项待核实问题，不把“未提及疾病”记成“无疾病”。

## 状态与转换

- proposed：助手提出但用户还未选择；confirmed_at 为 null。
- confirmed：用户明确选定；记录确认时间。只确认已选项，沉默或收到提醒均不算确认。
- paused：用户要求暂停，或发生与该行动相关的不适，需要先暂停并核对。写明原因，不能自动恢复。
- completed：用户明确表示该行动已完成；不等于健康目标已经达成。
- superseded：用户确认由新行动替代；reason 写明新行动 id。旧记录按下方版本留存后，可从当前最多三项中移除。

proposed → confirmed 需要明确选择；confirmed → paused/completed/superseded 需要用户反馈或前述暂停条件；paused → confirmed 需要用户重新选择，相关安全问题未解决时不恢复。用户取消未确认建议可直接移除，保存时记录新 revision。

## 更新过程

1. 读取当前文件；不存在则从空状态开始，不复制虚构示例。不要求保存时只在对话中给卡片。
2. 核对目标、近期变化和本次用户授权的修改，形成新状态。更新前再读取 revision；版本变化则重新核对，不覆盖。
3. 已有文件时，先把旧文件原样写入 `health/history/revision-NNNN.json`（NNNN 为旧 revision，四位补零）。归档失败则停止本次写入，不破坏当前文件。
4. 写入新文件，重新读取并核对 revision 和实际变动；失败或不一致时说明保存结果不确定，不宣称完成。
5. 对话中只反馈本次变动、当前状态和观察安排。文件控制在约 6 KB 内；超出时请用户选择保留哪些当前内容，不擅自丢弃关键条件。

这些步骤不能保证并发原子性；MVP 只允许一个会话写入该专家状态，出现并发迹象时暂停保存。多人服务或自动写入需要专门的状态工具/数据库，不能仅靠此协议保证隔离。

用户请求删除时，说明本协议只管理可见状态文件；平台聊天、记忆、归档、备份等需分别按实际功能处理。不得只删当前卡片就承诺全部数据已删除。
