import json
import shutil
from pathlib import Path
from typing import List
from nyxwin.core.models import log_info, log_warning

def flatten_xcassets(project_dir: Path, app_dir: Path) -> int:
    """
    Auto-flattens .xcassets catalogs so UIImage(named:) and SwiftUI Image() work
    seamlessly without requiring macOS actool. Extracts @1x, @2x, and @3x PNG/JPG variants.
    """
    xcasset_dirs = list(project_dir.glob("**/*.xcassets"))
    flattened_count = 0
    for xc in xcasset_dirs:
        for imageset in xc.glob("**/*.imageset"):
            img_name = imageset.stem
            contents_json = imageset / "Contents.json"
            if contents_json.is_file():
                try:
                    with open(contents_json, "r", encoding="utf-8") as jf:
                        cdata = json.load(jf)
                    for img in cdata.get("images", []):
                        fn = img.get("filename")
                        scale = img.get("scale", "1x")
                        if fn and (imageset / fn).is_file():
                            src_img = imageset / fn
                            ext = src_img.suffix
                            if scale == "1x":
                                target_name = f"{img_name}{ext}"
                            else:
                                target_name = f"{img_name}@{scale}{ext}"
                            shutil.copy2(src_img, app_dir / target_name)
                            flattened_count += 1
                except Exception:
                    pass
            else:
                for img_f in imageset.glob("*.*"):
                    if img_f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        shutil.copy2(img_f, app_dir / img_f.name)
                        flattened_count += 1

    if flattened_count > 0:
        log_info(f"Auto-extracted {flattened_count} image assets from .xcassets into app bundle.")
    return flattened_count
