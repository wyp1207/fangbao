export interface PlaceholderSpec {
  label: string
  purpose: string
  needs: string[]
  reference?: string
}

export const PLACEHOLDERS: Record<string, PlaceholderSpec> = {
  video: {
    label: '视频监控',
    purpose: '看可见光/热红外实时画面，云台可转动。',
    needs: [
      '机器人视频流地址（RTSP / WebRTC）与相机通道号 —— 采集表 05 表还没填',
      '云台控制接口（写操作，需现场授权签字）',
    ],
    reference: '参考系统：监控中心 → 设备监控（视频墙）',
  },
  'env-device': {
    label: '环境传感器',
    purpose: '管理气体、温湿度、噪声传感器的台账与在线状态。',
    needs: ['传感器型号与安装位置（还没定）', 'Modbus / MQTT 接入方式'],
    reference: '参考系统：设备管理 → 固定设备 / 气象站',
  },
  'record-plan': {
    label: '录像计划',
    purpose: '给摄像头排录像时段，决定什么时候录、录多久、存哪里。',
    needs: [
      '录像服务（NVR 或 MediaMTX 录制）先落地',
      '存储位置与保留天数（按天分区，和 W5 历史表一起规划）',
    ],
    reference: '参考系统：录像管理 → 录像计划',
  },
  'record-playback': {
    label: '录像回放',
    purpose: '按时间轴回放巡检录像，定位异常时段。',
    needs: [
      '录像文件索引（哪路摄像头、哪段时间、哪个文件）',
      '录像存储服务与播放转码（浏览器不能直接放 RTSP/裸 H264）',
    ],
    reference: '参考系统：录像管理 → 录像回放',
  },
  env: {
    label: '环境监测',
    purpose: '可燃气体、温湿度、噪声的实时值与超限报警。',
    needs: [
      '传感器型号与安装位置',
      '机器人 WebSocket 环境数据通道（采集表 D26 / D29）',
      '每项指标的报警阈值（现在全部「未标定」，不能凭空估值）',
    ],
    reference: '参考系统：首页右侧环境数据 + 设备管理 → 气象站',
  },
  'task-calendar': {
    label: '任务日历',
    purpose: '按天/周看巡检任务排在哪些时段、有没有漏跑。',
    needs: [
      '机器人侧历史任务记录接口（现在只有当前任务列表）',
      '任务执行结果落库（W5 历史表）',
    ],
    reference: '参考系统：巡检管理 → 任务日历',
  },
  'run-data': {
    label: '运行数据',
    purpose: '按时间范围查电压、速度、位姿、电量的连续曲线。',
    needs: [
      '状态采样表落库（1s 原始 7 天 / 1 分钟聚合 180 天，按天分区）',
      'W5 历史库建好之后才有数据可查',
    ],
    reference: '参考系统：数据查询 → 巡检设备数据',
  },
  oplog: {
    label: '系统日志',
    purpose: '谁在什么时候下发过什么、确认过哪条告警。',
    needs: [
      '写操作开放之后才有内容（现在所有写操作都锁着）',
      '审计表落库（W5，随历史表一起建）',
    ],
    reference: '参考系统：系统管理 → 日志',
  },
}
