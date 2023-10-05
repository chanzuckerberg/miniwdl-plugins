# NOTE: this file is excluded from coverage analysis since alternate container backends may not be
#       available in the CI environment. To test locally: prove -v tests/singularity.t
import os
import logging
from typing import List
from contextlib import ExitStack
from WDL.runtime import config
from WDL.runtime.backend.cli_subprocess import SubprocessBase
from typing import ContextManager


class LocalSubprocess(SubprocessBase):
    """
    local task runtime based on cli_subprocess.SubprocessBase
    """

    @classmethod
    def global_init(cls, cfg: config.Loader, logger: logging.Logger) -> None:
        cfg.override({"file_io": {"copy_input_files": True}})
        logger.info("Local runtime initialized (BETA)")

    def __init__(self, cfg: config.Loader, run_id: str, host_dir: str) -> None:
        super().__init__(cfg, run_id, host_dir)
        self.container_dir = self.host_dir
        # self.host_dir = os.path.join(self.host_dir, "work")

    @property
    def cli_name(self) -> str:
        return "subprocess

    @property
    def cli_exe(self) -> List[str]:
        return self.cfg.get_list("singularity", "exe")

    def _pull(self, logger: logging.Logger, cleanup: ExitStack) -> str:
        return ''

    def _run_invocation(self, logger: logging.Logger, cleanup: ExitStack, image: str) -> List[str]:
        self.host_dir = os.path.join(self.host_dir, "work")
        return []

    def task_running_context(self) -> ContextManager[None]:
        self.host_dir = self.container_dir
        return super().task_running_context()
