"""
Git service alias module for nyxwin.services.git.
Re-exports all functionality from nyxwin.services.git_service.
"""
from nyxwin.services.git_service import get_project_git_status, init_project_git

__all__ = ["get_project_git_status", "init_project_git"]
