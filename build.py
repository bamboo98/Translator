import PyInstaller.__main__
import os
from pathlib import Path

# 尝试找到 vosk 的安装位置并手动收集 DLL 文件
# 因为 vosk 的 DLL 加载机制特殊，需要确保 DLL 被正确打包
binaries = []
try:
    import vosk
    vosk_path = Path(vosk.__file__).parent
    print(f"找到 vosk 路径: {vosk_path}")
    
    # 查找 vosk 目录下的所有 DLL 文件
    for dll_file in vosk_path.glob('*.dll'):
        binaries.append(f'--add-binary={dll_file};.')
        print(f"添加 DLL: {dll_file}")
    
    # 也查找子目录中的 DLL（vosk 可能将 DLL 放在子目录中）
    for dll_file in vosk_path.rglob('*.dll'):
        if dll_file.parent != vosk_path:  # 只处理子目录中的 DLL
            rel_path = dll_file.relative_to(vosk_path)
            target_dir = str(rel_path.parent) if rel_path.parent != Path('.') else '.'
            binaries.append(f'--add-binary={dll_file};{target_dir}')
            print(f"添加 DLL: {dll_file} -> {target_dir}")
except ImportError as e:
    print(f"警告: 无法导入 vosk: {e}")

# 构建 PyInstaller 命令
build_args = [
    'main.py',
    # '--onefile',
    '--name=Translator',
    '--clean',
    '--hidden-import=vosk',  # 确保 vosk 被包含
    '--collect-all', 'vosk',  # 收集 vosk 的所有文件（包括 DLL 和数据文件）
]

# 添加手动收集的二进制文件（如果找到）
build_args.extend(binaries)

print(f"构建参数: {build_args}")

# 运行 PyInstaller
PyInstaller.__main__.run(build_args)