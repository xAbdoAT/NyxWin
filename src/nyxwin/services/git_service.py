import os
import subprocess
from pathlib import Path
from typing import Dict, Any

def get_project_git_status(proj_dir: Path) -> Dict[str, Any]:
    """Returns comprehensive Git status info for a project directory safely without errors on unborn HEAD."""
    git_dir = proj_dir / ".git"
    if not git_dir.is_dir():
        return {
            "has_git": False,
            "branch": None,
            "has_commits": False,
            "commit_count": 0,
            "latest_commit": None,
            "clean": True,
            "modified_count": 0,
            "staged_count": 0,
            "untracked_count": 0,
            "raw_status": "",
        }

    try:
        # Detect current branch safely
        r_branch = subprocess.run(
            ["git", "-C", str(proj_dir), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2
        )
        branch = r_branch.stdout.strip() if r_branch.returncode == 0 else "main"

        # Check whether HEAD exists (unborn branch check)
        r_head = subprocess.run(
            ["git", "-C", str(proj_dir), "rev-parse", "--verify", "HEAD"],
            capture_output=True, text=True, timeout=2
        )
        has_commits = (r_head.returncode == 0)

        commit_count = 0
        latest_commit = None
        if has_commits:
            r_count = subprocess.run(
                ["git", "-C", str(proj_dir), "rev-list", "--count", "HEAD"],
                capture_output=True, text=True, timeout=2
            )
            if r_count.returncode == 0 and r_count.stdout.strip().isdigit():
                commit_count = int(r_count.stdout.strip())

            r_latest = subprocess.run(
                ["git", "-C", str(proj_dir), "log", "-1", "--format=%h %s"],
                capture_output=True, text=True, timeout=2
            )
            if r_latest.returncode == 0:
                latest_commit = r_latest.stdout.strip()

        # Parse status --porcelain
        r_stat = subprocess.run(
            ["git", "-C", str(proj_dir), "status", "--porcelain"],
            capture_output=True, text=True, timeout=2
        )
        raw_status = r_stat.stdout if r_stat.returncode == 0 else ""
        lines = [line for line in raw_status.splitlines() if line.strip()]
        clean = (len(lines) == 0)

        modified_count = 0
        staged_count = 0
        untracked_count = 0

        for line in lines:
            if line.startswith("??"):
                untracked_count += 1
            else:
                x = line[0] if len(line) > 0 else " "
                y = line[1] if len(line) > 1 else " "
                if x in ("M", "A", "D", "R", "C"):
                    staged_count += 1
                if y in ("M", "D"):
                    modified_count += 1

        return {
            "has_git": True,
            "branch": branch,
            "has_commits": has_commits,
            "commit_count": commit_count,
            "latest_commit": latest_commit,
            "clean": clean,
            "modified_count": modified_count,
            "staged_count": staged_count,
            "untracked_count": untracked_count,
            "raw_status": raw_status,
        }
    except Exception:
        return {
            "has_git": True,
            "branch": "git",
            "has_commits": False,
            "commit_count": 0,
            "latest_commit": None,
            "clean": True,
            "modified_count": 0,
            "staged_count": 0,
            "untracked_count": 0,
            "raw_status": "",
        }

def init_project_git(proj_dir: Path) -> bool:
    """Initializes a Git repository inside a project directory with appropriate .gitignore."""
    try:
        subprocess.run(["git", "-C", str(proj_dir), "init"], check=True, capture_output=True)

        gitignore_p = proj_dir / ".gitignore"
        if not gitignore_p.is_file():
            content = """# NyxWin Project Git Ignore
.DS_Store
Thumbs.db
ehthumbs.db
Desktop.ini
.cache/
*.ipa
*.zip
*.o
*.dylib
*.a
"""
            gitignore_p.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False
