# 行动复盘方法与脚本

核对日期：2026-11-11。

依据 `niddk-habit-change`：[NIDDK Changing Your Habits for Better Health](https://www.niddk.nih.gov/health-information/diet-nutrition/changing-habits-better-health)，定位“Preparation”“Track your progress”“Overcome roadblocks”。支持从小改变开始、讨论障碍并回顾执行与感受；中断不等于失败。下列数据格式和统计规则由本项目设计，不是医学量表。

## 先复盘，再调整

用户不想行动时只帮助理解。已选行动时，关注实际做了什么、哪里不方便、体验如何。给一个调整选项，允许继续、缩小或暂停；不拿体重变化作为唯一成功标准，不把沉默视为同意。

## 可复现的计数

用户提供多天记录时，可通过 Python 运行 `skills/action-review/scripts/summarize_action_log.py`，JSON 从标准输入传入，不拼接到 shell。脚本不读取文件、不联网、不保存、不修改 `health/current.json`。

```json
{
  "start_date": "2026-11-01",
  "end_date": "2026-11-07",
  "scheduled_dates": ["2026-11-02", "2026-11-04", "2026-11-06"],
  "records": [
    {"date": "2026-11-02", "status": "done"},
    {"date": "2026-11-04", "status": "partial"}
  ]
}
```

这是虚构样例。只统计一个行动、每天至多一次机会，日期必须由用户明确安排；不要把整周自动当成七次任务。支持 `done`、`partial`、`not_done`、`paused`、`unknown`。未报告的计划日计入 unknown；未安排的日期不进入分母。重复日期、未安排日期和无效状态会报错，不默默合并。

该例应得到：三次计划，一次完成、一次部分完成、一次未知。输出计数而非“坚持率”或健康得分；只描述所选记录，不推断未记录时发生了什么。日期窗口最长 366 天；无执行环境时手动整理并明确未运行脚本。
