"""Report the desktop runtime without starting the app or writing user data."""
import argparse
import importlib.metadata as metadata
import importlib.util
import json
import platform
import sys
from pathlib import Path

DEPENDENCIES = {
    'pywebview': 'webview', 'pyinstaller': 'PyInstaller',
    'rapidocr-onnxruntime': 'rapidocr_onnxruntime', 'onnxruntime': 'onnxruntime',
    'opencv-python': 'cv2', 'numpy': 'numpy', 'Pillow': 'PIL',
    'mss': 'mss', 'websockets': 'websockets', 'pywin32': 'win32api',
    'pythonnet': 'pythonnet',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    packages = {}
    for distribution, module in DEPENDENCIES.items():
        try:
            dist = metadata.distribution(distribution)
            spec = importlib.util.find_spec(module)
            packages[distribution] = {'version': dist.version,
                'metadataRoot': str(dist.locate_file('')),
                'modulePath': spec.origin if spec else None}
        except (metadata.PackageNotFoundError, ImportError, ValueError) as exc:
            packages[distribution] = {'error': str(exc)}
    result = {'python': sys.version, 'executable': sys.executable,
              'platform': platform.platform(), 'packages': packages,
              'discoveryPassed': all(p.get('modulePath') for p in packages.values()),
              'scope': 'Metadata and module discovery only; not a native app or clean-install acceptance test.'}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding='utf-8')
    print(rendered)
    return 0 if result['discoveryPassed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
