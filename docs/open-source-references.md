# 开源项目参考（架构借鉴，不是直接套壳）

> 核实状态：2026-10-20 通过本机代理调用 GitHub REST API 复核，star 与最近提交时间为当日数值。许可证列取 GitHub 的 SPDX 检测；显示 `NOASSERTION` 的仓库必须人工核对 LICENSE 原文（GitHub 检测不出并不等于没有许可证）。

## 1. 先给结论：不要找“巡检机器人平台”整包套壳

原因很直接：

- JCROB 是厂商私有 HTTP/WS 协议，没有现成开源 adapter；
- 多数开源巡检/机器人平台绑定 ROS、MAVLink、MQTT 或 GB28181，直接套壳会把协议层做死；
- 真正能复用的是横向能力：设备模型、任务状态机、告警规则、地图渲染、视频接入、RBAC。

推荐组合：

| 用途 | 首选参考 | 用法 |
|---|---|---|
| 管理后台骨架 | RuoYi-Vue-Plus | 只取 RBAC、菜单、字典、操作日志、组织；不要整包生成器 |
| 前端布局与视觉 | Arco Design Pro Vue | 布局、暗色主题、权限路由、图表页；与 xlsx 的 Arco 选型一致 |
| IoT 领域模型 | ThingsBoard / JetLinks | 设备档案、遥测、告警、规则链的产品抽象；不引入其消息总线 |
| 机器人任务编排 | Open-RMF / openTCS / VDA5050 | 任务状态机、订单/状态/即时指令、车辆适配器的建模思路；JCROB 不实现 VDA5050 |
| 视频 | ZLMediaKit / MediaMTX | RTSP 转 WebRTC/FLV；需要 GB28181/录像选前者，单路轻量选后者 |
| 固定设备 | Apache PLC4X | Modbus/OPC UA 接入，P2 再上 |

## 2. 具体项目与“抄什么 / 不抄什么”

| 项目 | Star | 最近提交 | 许可证 | 可借鉴 / 不要照搬 |
|---|---|---|---|---|
| [ThingsBoard](https://github.com/thingsboard/thingsboard) | 22.6k | 2026-10-20 | NOASSERTION（官方声明 Apache-2.0，需核原文） | 设备 profile、遥测、告警、仪表盘模型；不要搬整套微服务与消息队列 |
| [JetLinks Community](https://github.com/jetlinks/jetlinks-community) | 6.7k | 2026-10-20 | Apache-2.0 | 物模型、告警配置、后台结构；不要搬响应式设备接入层 |
| [ThingsPanel](https://github.com/ThingsPanel/thingspanel-backend-community) | 593 | 2026-10-20 | Apache-2.0 | 轻量设备模板、遥测面板；Go 后端不适用 |
| [OpenRemote Core](https://github.com/openremote/core) | 1.9k | 2026-10-19 | NOASSERTION（AGPL，高风险） | 资产模型、仪表盘结构；**不要复制代码进闭源交付物** |
| [Open-RMF](https://github.com/open-rmf/rmf) | 454 | 2026-08-25 | Apache-2.0 | 多机任务派发、fleet adapter 概念；ROS 2 运行时不适用 |
| [openTCS](https://github.com/openTCS/opentcs) | 592 | 2026-09-17 | 无 SPDX 标注，需核原文 | 车辆/订单/路线模型；单机场景用不上 |
| [VDA5050](https://github.com/VDA5050/VDA5050) | — | 规范 | 规范/实现各异 | Order/State/InstantActions 的分层；不要声称 JCROB 支持它 |
| [RuoYi-Vue-Plus](https://github.com/dromara/RuoYi-Vue-Plus) | 2.8k | 2026-10-19 | MIT | RBAC、菜单、字典、操作日志；只在切 Spring Boot 时用，裁掉生成器 |
| [Arco Design Vue](https://github.com/arco-design/arco-design-vue) | 3.1k | 2026-10-20 | MIT | **活跃的组件库**；直接用它搭我们的控制台组件 |
| [Arco Design Pro Vue](https://github.com/arco-design/arco-design-pro-vue) | 1.8k | 2024-05-08 | MIT | 模板已两年未更新，只参考页面结构，不作为依赖 |
| ~~Foxglove Studio~~ | 93 | 2024-07（已归档） | 无 | **不要引用**；仓库已 archived，产品已闭源化 |
| [ZLMediaKit](https://github.com/ZLMediaKit/ZLMediaKit) | 17.6k | 2026-10-12 | NOASSERTION（需核原文） | 录像/GB28181/多协议；单路场景偏重 |
| [MediaMTX](https://github.com/bluenviron/mediamtx) | 20.5k | 2026-10-20 | MIT | **首选**：单二进制 RTSP→WebRTC，部署最简 |
| [WVP-PRO](https://github.com/648540858/wvp-GB28181-pro) | 7.4k | 2026-10-20 | MIT | 只在需要 GB28181 国标级联时用 |
| [Apache PLC4X](https://github.com/apache/plc4x) | 1.8k | 2026-10-19 | Apache-2.0 | Modbus/OPC UA 接入；P2 再上 |

## 3. 仿照哪个“框架架构”最合适

如果只看一张架构图，最接近本项目的是 **JetLinks / ThingsBoard 的“设备接入 → 物模型 → 遥测/告警 → 规则 → 可视化”分层**，而不是 Open-RMF 的机器人调度架构。原因是：

- 本项目只有 1–2 台 JCROB，机器人自己完成定位、路径规划和避障；
- 平台的核心工作是设备台账、任务编排、告警、视频、报表、权限；
- Open-RMF 解决的是“多机器人交通与任务协商”，本期用不上。

建议画成四层，不要画成微服务大杂烩：

```text
接入层   JCROB Adapter（HTTP/WS/UDP） + 视频网关（RTSP/ONVIF）
领域层   设备 / 地图 / 点位 / 任务 / 告警 / 媒体 / 报表
应用层   REST API + WebSocket 推送 + 定时调度
展示层   Vue 3 驾驶舱 / 任务 / 监控 / 设备 / 报表 / 系统管理
```

## 4. 明确不采用的做法

- 不 fork ThingsBoard 或 JetLinks 再改：它们的设备接入、消息总线和租户模型会拖慢 4 周 MVP；
- 不引入 ROS 2 / Open-RMF 作为运行时：JCROB 已经封装了导航，平台再接 ROS 只会增加一层故障点；
- 不把 VDA5050 当成 JCROB 的“标准协议”：两者不是一回事；
- 不复制 AGPL 项目代码到闭源交付物；只借鉴产品结构，必要时让法务确认；
- 不用“AI 巡检”作为首版卖点：JCROB 不返回点位 AI 结果，先把真机数据链路跑通。

## 5. 复核清单（研发落地前）

1. 每个仓库当日 LICENSE 是否允许闭源商用/二次分发；
2. 是否与 Spring Boot 3.2 / Vue 3 / JDK 17 版本兼容；
3. 是否仍在维护（最近 6 个月是否有 release/commit）；
4. 是否引入额外中间件（MQ、注册中心、时序库），能否裁掉；
5. 安全边界：默认口令、未鉴权接口、公网暴露面。
