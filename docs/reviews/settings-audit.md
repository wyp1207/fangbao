# 设置项审计：界面上有，代码里有没有人读

共 24 项，有代码读取 24 项，**没人读 0 项**。

> 判定方法：在 server/app、web/src、scripts、deploy 里搜设置键的字面量；
> 只看 settings_schema.py 不算（那是定义本身）。

| 设置项 | 有代码读 | 生效位置（前 2 处） |
|---|---|---|
| `alarm.sla_minutes` | ✅ | `server/app/services/sla.py` |
| `alarm.battery_warn` | ✅ | `server/app/services/alarms.py`<br>`web/src/pages/AlarmRules.vue` |
| `alarm.battery_critical` | ✅ | `server/app/services/alarms.py`<br>`web/src/pages/AlarmRules.vue` |
| `alarm.offline_after_s` | ✅ | `server/app/services/alarms.py`<br>`web/src/pages/AlarmRules.vue` |
| `alarm.dedupe_s` | ✅ | `server/app/services/alarms.py` |
| `alarm.sustain_s` | ✅ | `server/app/services/alarms.py`<br>`web/src/pages/AlarmRules.vue` |
| `notify.escalate_enabled` | ✅ | `server/app/services/notify.py` |
| `notify.escalate_after_min` | ✅ | `server/app/services/notify.py` |
| `robot.write_enabled` | ✅ | `server/app/adapters/deeprobotics/adapter.py`<br>`server/app/services/task_dispatch.py` |
| `security.idle_minutes` | ✅ | `web/src/composables/useIdleSession.ts` |
| `sensor.keep_days` | ✅ | `server/app/main.py` |
| `telemetry.keep_days` | ✅ | `server/app/main.py` |
| `clock.max_skew_s` | ✅ | `server/app/services/robot_runtime.py` |
| `disk.warn_free_gb` | ✅ | `server/app/services/disk_monitor.py`<br>`web/src/pages/AlarmRules.vue` |
| `disk.crit_free_gb` | ✅ | `server/app/services/disk_monitor.py`<br>`web/src/pages/AlarmRules.vue` |
| `record.enabled` | ✅ | `server/app/api/v1/recordings.py`<br>`server/app/api/v1/settings.py` |
| `record.keep_days` | ✅ | `server/app/api/v1/recordings.py`<br>`server/app/api/v1/settings.py` |
| `record.max_gb` | ✅ | `server/app/api/v1/recordings.py`<br>`server/app/api/v1/settings.py` |
| `record.min_free_gb` | ✅ | `server/app/api/v1/recordings.py`<br>`server/app/api/v1/settings.py` |
| `video.transcode_width` | ✅ | `server/app/api/v1/settings.py`<br>`server/app/services/video_stream.py` |
| `video.mjpeg_fps` | ✅ | `server/app/services/video_stream.py` |
| `platform.name` | ✅ | `web/src/layouts/ConsoleLayout.vue`<br>`web/src/pages/Dashboard.vue` |
| `platform.site` | ✅ | `web/src/pages/RobotProfile.vue`<br>`web/src/stores/platform.ts` |
| `platform.banner_on_fault` | ✅ | `web/src/stores/platform.ts` |

## 处理建议

没有发现假开关。
