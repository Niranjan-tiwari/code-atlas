"""
Code Atlas - Multi-repository task automation tool
"""

__version__ = "1.0.0"

from .core import ParallelRepoWorker, RepoConfig, Task
from .cli import InteractiveCLI, DaemonWorker

__all__ = [
    'ParallelRepoWorker',
    'RepoConfig', 
    'Task',
    'InteractiveCLI',
    'DaemonWorker',
    '__version__'
]
