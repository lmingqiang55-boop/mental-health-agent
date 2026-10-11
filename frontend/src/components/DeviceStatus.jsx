// 摄像头/麦克风设备状态与后端视觉分析可用性。

export default function DeviceStatus({ visionEnabled, audioEnabled, cameraError, visionStatus, visionResult }) {
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
        {cameraError ? '摄像头分析暂不可用，仍可继续筛查。' :
          visionStatus?.provider === 'mock' ? '表情识别处于模拟模式，摄像头预览不会触发表情回应。' :
          visionStatus?.state === 'unavailable' ? '暂时无法确认表情识别是否可用。' :
          !visionEnabled ? '开启摄像头后，可在画面可靠时结合表情交流。' :
          visionResult?.face_detected === false ? '当前画面未识别到人脸，请调整光线和位置。' :
          visionResult?.face_detected ? '已识别人脸；表情稳定时会偶尔结合画面交流。' :
          '摄像头已开启，正在等待有效识别结果。'}
      </p>
    </section>
  )
}
