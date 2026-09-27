// 摄像头/麦克风设备状态。框架阶段只显示状态，不真正采集。

export default function DeviceStatus({ visionEnabled, audioEnabled }) {
  return (
    <section className="card device-status">
      <h3>设备状态</h3>
      <div className="device-row">
        <span className={`device-icon ${visionEnabled ? 'on' : 'off'}`}>●</span>
        <span>摄像头</span>
        <span className={`device-state ${visionEnabled ? 'on' : 'off'}`}>
          {visionEnabled ? '已开启' : '未开启'}
        </span>
      </div>
      <div className="device-row">
        <span className={`device-icon ${audioEnabled ? 'on' : 'off'}`}>●</span>
        <span>麦克风</span>
        <span className={`device-state ${audioEnabled ? 'on' : 'off'}`}>
          {audioEnabled ? '已开启' : '未开启'}
        </span>
      </div>
      <p className="device-hint">框架阶段使用 Mock 数据，不采集真实画面/录音。</p>
    </section>
  )
}
