"""
音频设备诊断工具
用于检查可用的音频设备和配置
"""
import pyaudio

def diagnose_audio_devices():
    """诊断音频设备"""
    audio = pyaudio.PyAudio()
    
    print("=" * 80)
    print("音频设备诊断信息")
    print("=" * 80)
    
    print(f"\n总设备数: {audio.get_device_count()}")
    print(f"默认输入设备索引: {audio.get_default_input_device_info()['index']}")
    print(f"默认输出设备索引: {audio.get_default_output_device_info()['index']}")
    
    print("\n所有音频设备:")
    print("-" * 80)
    
    loopback_devices = []
    input_devices = []
    output_devices = []
    
    for i in range(audio.get_device_count()):
        try:
            info = audio.get_device_info_by_index(i)
            name = info.get('name', 'Unknown')
            max_input = info.get('maxInputChannels', 0)
            max_output = info.get('maxOutputChannels', 0)
            sample_rate = info.get('defaultSampleRate', 0)
            
            device_type = []
            if max_input > 0:
                device_type.append(f"输入({max_input}声道)")
            if max_output > 0:
                device_type.append(f"输出({max_output}声道)")
            
            device_str = f"设备 {i}: {name}"
            device_str += f" | {'/'.join(device_type)}"
            device_str += f" | 默认采样率: {sample_rate}Hz"
            
            # 检查是否是Loopback设备
            name_lower = name.lower()
            if 'loopback' in name_lower or 'stereo mix' in name_lower:
                device_str += " [LOOPBACK]"
                loopback_devices.append((i, info))
            
            print(device_str)
            
            if max_input > 0:
                input_devices.append((i, info))
            if max_output > 0:
                output_devices.append((i, info))
            
        except Exception as e:
            print(f"设备 {i}: 无法获取信息 - {e}")
    
    print("\n" + "=" * 80)
    print("分类设备列表:")
    print("=" * 80)
    
    print(f"\nLoopback设备 ({len(loopback_devices)}个):")
    if loopback_devices:
        for idx, info in loopback_devices:
            print(f"  [{idx}] {info['name']} - 输入:{info.get('maxInputChannels', 0)} 输出:{info.get('maxOutputChannels', 0)}")
    else:
        print("  未找到Loopback设备")
    
    print(f"\n输入设备 ({len(input_devices)}个):")
    for idx, info in input_devices[:10]:  # 只显示前10个
        print(f"  [{idx}] {info['name']} - {info.get('maxInputChannels', 0)}声道")
    
    print(f"\n输出设备 ({len(output_devices)}个):")
    for idx, info in output_devices[:10]:  # 只显示前10个
        print(f"  [{idx}] {info['name']} - {info.get('maxOutputChannels', 0)}声道")
    
    print("\n" + "=" * 80)
    print("测试设备配置:")
    print("=" * 80)
    
    # 测试默认输出设备作为输入
    try:
        default_output = audio.get_default_output_device_info()
        print(f"\n测试默认输出设备 [{default_output['index']}]: {default_output['name']}")
        print(f"  maxInputChannels: {default_output.get('maxInputChannels', 0)}")
        print(f"  maxOutputChannels: {default_output.get('maxOutputChannels', 0)}")
        print(f"  defaultSampleRate: {default_output.get('defaultSampleRate', 0)}")
        
        # 尝试打开流
        test_configs = [
            (2, 44100),
            (2, 48000),
            (2, 16000),
            (1, 44100),
            (1, 48000),
            (1, 16000),
        ]
        
        for channels, rate in test_configs:
            try:
                stream = audio.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=rate,
                    input=True,
                    input_device_index=default_output['index'],
                    frames_per_buffer=1024
                )
                stream.close()
                print(f"  ✓ {channels}声道, {rate}Hz - 成功")
            except Exception as e:
                print(f"  ✗ {channels}声道, {rate}Hz - 失败: {e}")
    except Exception as e:
        print(f"测试失败: {e}")
    
    audio.terminate()
    
    print("\n" + "=" * 80)
    print("建议:")
    print("=" * 80)
    if not loopback_devices:
        print("1. 未找到专用Loopback设备")
        print("2. 建议安装虚拟音频设备（如VB-Audio Cable）")
        print("3. 或者使用Windows的'立体声混音'功能（如果可用）")
        print("4. 或者考虑使用sounddevice库替代pyaudio")

if __name__ == "__main__":
    diagnose_audio_devices()

