import os
import sys
import plistlib
import subprocess
from pathlib import Path
from typing import Optional

from nyxwin.core.models import Color, log_info, log_success, log_error, log_warning
from nyxwin.core.toolchain import Toolchain
from nyxwin.core.project import load_project_config, save_project_config

ICON_SIZES = [
    ("AppIcon20x20.png", 20, 20),
    ("AppIcon20x20@2x.png", 40, 40),
    ("AppIcon20x20@3x.png", 60, 60),
    ("AppIcon29x29.png", 29, 29),
    ("AppIcon29x29@2x.png", 58, 58),
    ("AppIcon29x29@3x.png", 87, 87),
    ("AppIcon40x40.png", 40, 40),
    ("AppIcon40x40@2x.png", 80, 80),
    ("AppIcon40x40@3x.png", 120, 120),
    ("AppIcon60x60.png", 60, 60),
    ("AppIcon60x60@2x.png", 120, 120),
    ("AppIcon60x60@3x.png", 180, 180),
    ("AppIcon76x76@2x~ipad.png", 152, 152),
    ("AppIcon83.5x83.5@2x~ipad.png", 167, 167),
    ("AppIcon1024x1024.png", 1024, 1024),
]

def resize_image_pillow(src_path: Path, dest_path: Path, size: tuple) -> bool:
    """Helper to resize an image using Pillow with LANCZOS resampling."""
    try:
        from PIL import Image
        with Image.open(src_path) as img:
            img = img.convert("RGBA")
            resized = img.resize(size, Image.Resampling.LANCZOS)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            resized.save(dest_path, "PNG")
        return True
    except Exception:
        return False

def generate_app_icons(toolchain: Toolchain, project_name: str, icon_path: Path) -> bool:
    """
    Generates all standard iOS iPhone & iPad icon resolutions and updates Config/Project.plist.
    Uses Pillow (PIL.Image) if installed; otherwise uses a hardened parameterized PowerShell script.
    """
    if isinstance(icon_path, str):
        icon_path = Path(icon_path)

    if not icon_path.is_file():
        log_error(f"Source icon file not found: {icon_path}")
        return False

    proj_dir = toolchain.get_project_dir(project_name)
    if not proj_dir or not proj_dir.is_dir():
        log_error(f"Project not found: {project_name}")
        return False

    resources_dir = proj_dir / "Resources"
    os.makedirs(resources_dir, exist_ok=True)

    has_pil = False
    try:
        from PIL import Image
        has_pil = True
    except ImportError:
        has_pil = False

    log_info(f"Generating iOS icon variants for '{proj_dir.name}' using {'Pillow' if has_pil else 'PowerShell System.Drawing'}...")

    if has_pil:
        try:
            with Image.open(icon_path) as img:
                img = img.convert("RGBA")
                for fname, width, height in ICON_SIZES:
                    resized = img.resize((width, height), Image.Resampling.LANCZOS)
                    resized.save(resources_dir / fname, "PNG")
        except Exception as e:
            log_error(f"Pillow icon generation failed: {e}")
            return False
    else:
        # Hardened PowerShell fallback: pass paths via arguments to avoid string injection
        ps_script = """
        param([string]$srcPath, [string]$destPath, [int]$w, [int]$h)
        Add-Type -AssemblyName System.Drawing
        $src = [System.Drawing.Image]::FromFile($srcPath)
        $bmp = New-Object System.Drawing.Bitmap($w, $h)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.DrawImage($src, 0, 0, $w, $h)
        $bmp.Save($destPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $g.Dispose()
        $bmp.Dispose()
        $src.Dispose()
        """
        for fname, width, height in ICON_SIZES:
            out_f = resources_dir / fname
            cmd = [
                "powershell", "-NoProfile", "-Command", ps_script,
                "-srcPath", str(icon_path.resolve()),
                "-destPath", str(out_f.resolve()),
                "-w", str(width),
                "-h", str(height)
            ]
            subprocess.run(cmd, capture_output=True)

    # Update Config/Project.plist CFBundleIcons
    proj_data = load_project_config(proj_dir)
    if proj_data:
        bundle_info = proj_data.setdefault("BundleInfo", {})
        bundle_info["CFBundleIcons"] = {
            "CFBundlePrimaryIcon": {
                "CFBundleIconFiles": ["AppIcon60x60"],
                "CFBundleIconName": "AppIcon"
            }
        }
        bundle_info["CFBundleIcons~ipad"] = {
            "CFBundlePrimaryIcon": {
                "CFBundleIconFiles": [
                    "AppIcon60x60",
                    "AppIcon76x76",
                    "AppIcon83.5x83.5"
                ],
                "CFBundleIconName": "AppIcon"
            }
        }
        save_project_config(proj_dir, proj_data)

    log_success(f"Generated {len(ICON_SIZES)} icon variants in Resources/ and updated Project.plist!")
    return True
