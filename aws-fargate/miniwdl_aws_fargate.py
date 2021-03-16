import os
import subprocess
import logging
import time
import contextlib
import pathlib
import shutil
import random
from typing import Callable, Set, Dict, Optional

import psutil
from aegea import ecs

from WDL._util import chmod_R_plus, PygtailLogger
from WDL.runtime import config, _statusbar
from WDL.runtime.task_container import TaskContainer
from WDL.runtime.error import Interrupted, Terminated


class AWSFargateContainer(TaskContainer):
    fargate_mem_values = [512] + list(range(1024, 30721, 1024))
    fargate_cpu_values = [256, 512, 1024, 2048, 4096]
    fargate_cpu_mem_constraints = {
        256: dict(min=512, max=2048),
        512: dict(min=1024, max=4096),
        1024: dict(min=2048, max=8192),
        2048: dict(min=4096, max=16384),
        4096: dict(min=8192, max=30720)
    }
    _limits = {
        "cpu": int(fargate_cpu_values[-1] / 1024),
        "mem_bytes": fargate_mem_values[-1] * 1024 * 1024
    }
    running_states = {"PROVISIONING", "PENDING", "ACTIVATING", "RUNNING"}
    stopping_states = {"DEACTIVATING", "STOPPING", "DEPROVISIONING", "STOPPED"}
    default_efs_security_group = "aegea.efs"
    _observed_states: Optional[Set[str]] = None

    @classmethod
    def global_init(cls, cfg: config.Loader, logger: logging.Logger) -> None:
        try:
            cls.efs_security_group = cfg["aws_fargate"]["efs_security_group"]
        except config.ConfigMissing:
            cls.efs_security_group = cls.default_efs_security_group
        try:
            cls.efs_id = cfg["aws_fargate"]["efs_id"]
        except config.ConfigMissing:
            cls.efs_id = None
        try:
            cls.efs_mountpoint = cfg["aws_fargate"]["efs_mountpoint"]
        except config.ConfigMissing:
            cls.efs_mountpoint = None

        for partition in psutil.disk_partitions(all=True):
            if partition.fstype == "nfs4":
                if f".efs.{ecs.clients.ecs.meta.region_name}.amazonaws.com:/" in partition.device:
                    # if os.stat(host_dir).st_dev == os.stat(partition.mountpoint).st_dev:
                    if cls.efs_id is None:
                        cls.efs_id = partition.device.split(":")[0].split(".")[-5]
                    elif cls.efs_id not in partition.device:
                        msg = "Expected filesystem mount {} to match configured EFS ID {}"
                        raise RuntimeError(msg.format(partition, cls.efs_id))
                    if cls.efs_mountpoint is None:
                        cls.efs_mountpoint = partition.mountpoint
                    elif cls.efs_mountpoint != partition.mountpoint:
                        msg = "Expected filesystem mount {} to match configured EFS mountpoint {}"
                        raise RuntimeError(msg.format(partition, cls.efs_mountpoint))
                    return
        else:
            if cls.efs_id is None:
                raise RuntimeError(
                    'EFS filesystem config is missing. Mount the filesystem and run miniwdl in a subdirectory of the '
                    'mountpoint or set the filesystem ID with "export MINIWDL__AWS_FARGATE__EFS_ID=fs-12345678 '
                    'MINIWDL__AWS_FARGATE__EFS_MOUNTPOINT=/mnt/efs" or any other miniwdl config facility. '
                    'Use "aws efs describe-file-systems" to list filesystems.'
                )
            logger.info("Mounting %s at %s", cls.efs_id, cls.efs_mountpoint)
            fs_url = f"{cls.efs_id}.efs.{ecs.clients.ecs.meta.region_name}.amazonaws.com:/"
            subprocess.run(["sudo", "mount", "-t", "nfs4", "-o",
                            "nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2",
                            fs_url, cls.efs_mountpoint])  # type: ignore

    @classmethod
    def detect_resource_limits(cls, cfg: config.Loader, logger: logging.Logger) -> Dict[str, int]:
        return cls._limits

    def poll_task(
        self, logger: logging.Logger, task_desc, verbose: bool = False
    ) -> Optional[int]:
        res = ecs.clients.ecs.describe_tasks(cluster=task_desc["clusterArn"], tasks=[task_desc["taskArn"]])
        task_desc = res["tasks"][0]
        if task_desc["lastStatus"] not in self._observed_states:  # type: ignore
            logger.info("Task %s %s", task_desc["taskArn"], task_desc["lastStatus"])
            self._observed_states.add(task_desc["lastStatus"])  # type: ignore
        if task_desc["lastStatus"] == "STOPPED" and task_desc.get("stopCode") == "TaskFailedToStart":
            raise Interrupted(task_desc.get("stoppedReason"))
        return task_desc.get("containers", [{}])[0].get("exitCode")

    def _run(self, logger: logging.Logger, terminating: Callable[[], bool], command: str) -> int:
        self._observed_states = set()
        with open(os.path.join(self.host_dir, "command"), "x") as outfile:
            outfile.write(command)

        image_tag = self.runtime_values.get("docker", "ubuntu:18.04")
        if ":" not in image_tag:
            image_tag += ":latest"
        logger.info("docker image tag %s", image_tag)

        if os.stat(self.host_dir).st_dev != os.stat(self.efs_mountpoint).st_dev:
            raise RuntimeError(f"miniwdl run directory is outside EFS mountpoint {self.efs_mountpoint}")

        for host_path, container_path in self.input_file_map.items():
            subd = os.path.basename(os.path.dirname(container_path))
            real_host_path = os.path.realpath(host_path)
            host_work_path = os.path.join(self.host_dir, "work/_miniwdl_inputs", subd, os.path.basename(real_host_path))
            os.makedirs(os.path.dirname(host_work_path), exist_ok=True)
            if os.stat(real_host_path).st_dev == os.stat(os.path.dirname(host_work_path)).st_dev:
                logger.debug("Linking input %s as %s", real_host_path, host_work_path)
                os.link(real_host_path, host_work_path)
            else:
                logger.debug("Copying input %s as %s", real_host_path, host_work_path)
                shutil.copyfile(real_host_path, host_work_path)

        chmod_R_plus(self.host_dir, file_bits=0o660, dir_bits=0o770)

        user = None
        if self.cfg["task_runtime"].get_bool("as_user"):
            user = f"{os.geteuid()}:{os.getegid()}"

        fargate_mem_value = self.fargate_mem_values[0]
        if self.cfg.has_option("aws_fargate", "default_memory_mb"):
            fargate_mem_value = self.cfg["aws_fargate"].get_int("default_memory_mb")
        if "memory_reservation" in self.runtime_values:
            for fargate_mem_value in self.fargate_mem_values:
                if fargate_mem_value * 1024 * 1024 >= self.runtime_values["memory_reservation"]:
                    break
            else:
                logger.warning("Memory reservation exceeds maximum Fargate memory")

        fargate_cpu_value = self.fargate_cpu_values[0]
        if self.cfg.has_option("aws_fargate", "default_cpu_shares"):
            fargate_cpu_value = self.cfg["aws_fargate"].get_int("default_cpu_shares")
        if "cpu" in self.runtime_values:
            for fargate_cpu_value in self.fargate_cpu_values:
                if fargate_mem_value > self.fargate_cpu_mem_constraints[fargate_cpu_value]["max"]:
                    continue
                if fargate_cpu_value >= self.runtime_values["cpu"] * 1024:
                    break
        fargate_mem_value = max(fargate_mem_value, self.fargate_cpu_mem_constraints[fargate_cpu_value]["min"])
        logger.info("Task mem %s, CPU %s", fargate_mem_value, fargate_cpu_value)

        wd = os.path.join(self.container_dir, "work")

        for pipe_file in ["stdout.txt", "stderr.txt"]:
            pathlib.Path(os.path.join(self.host_dir, pipe_file)).touch()

        efs_subdir = os.path.relpath(self.host_dir, self.efs_mountpoint)
        run_args = [
            "--command", f"cd {wd} && bash ../command 2> >(tee -a ../stderr.txt 1>&2) > >(tee -a ../stdout.txt)",
            "--security-group", self.efs_security_group,
            "--volumes", f"{self.efs_id}:{efs_subdir}={self.container_dir}",  # type: ignore
            "--image", image_tag,
            "--fargate-memory", str(fargate_mem_value),
            "--fargate-cpu", str(fargate_cpu_value)
        ]
        # Tags require "opt in to new ID format"
        # aws.amazon.com/blogs/compute/migrating-your-amazon-ecs-deployment-to-the-new-arn-and-resource-id-format-2/
        # "--tags", f"miniwdl_run_id={self.run_id}"

        if user:
            run_args += ["--user", user]
        task_desc = ecs.run(ecs.run_parser.parse_args(run_args))
        exit_code = None
        try:
            with contextlib.ExitStack() as cleanup:
                poll_stderr = cleanup.enter_context(
                    PygtailLogger(
                        logger,
                        os.path.join(self.host_dir, "stderr.txt"),
                        callback=self.stderr_callback,
                    )
                )

                # poll for task exit code
                was_running = False
                while exit_code is None:
                    time.sleep(random.uniform(1.0, 2.0))  # spread out work over the GIL
                    if terminating():
                        self.poll_task(logger, task_desc, verbose=True)
                        raise Terminated(quiet=False)
                    exit_code = self.poll_task(logger, task_desc)
                    if not was_running and self._observed_states.intersection(self.running_states):
                        cleanup.enter_context(
                            _statusbar.task_running(
                                self.runtime_values.get("cpu", 0),
                                self.runtime_values.get("memory_reservation", 0),
                            )
                        )
                        was_running = True
                    if "RUNNING" in self._observed_states:
                        poll_stderr()

            assert isinstance(exit_code, int)
            return exit_code
        finally:
            if not self._observed_states.intersection(self.stopping_states):
                try:
                    logger.info("Stopping task %s", task_desc["taskArn"])
                    ecs.stop(ecs.stop_parser.parse_args([task_desc["taskArn"]]))
                except Exception:
                    logger.exception("failed to stop ECS task")
