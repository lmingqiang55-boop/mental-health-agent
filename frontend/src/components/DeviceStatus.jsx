// 摄像头/麦克风设备状态与后端视觉分析可用性。

export default function DeviceStatus({ visionEnabled, audioEnabled, cameraError }) {
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
      <p className="device-hint">
        {cameraError ? '摄像头分析暂不可用，仍可继续筛查。' : '视觉结果按发言区间绑定；未采集到的指标不会填成零。'}
      </p>
    </section>
  )
}
