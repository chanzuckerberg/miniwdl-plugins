import os
import json
import time
import threading
import subprocess
import tempfile
import re
from WDL._util import StructuredLogMessage as _


# environment variables to be passed through from miniwdl runner environment to task containers
PASSTHROUGH_ENV_VARS = (
    "AWS_DEFAULT_REGION",
    "DEPLOYMENT_ENVIRONMENT",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
)


def task(cfg, logger, run_id, run_dir, task, **recv):
    t_0 = time.time()

    s3_wd_uri = recv["inputs"].get("s3_wd_uri", None)
    if s3_wd_uri and s3_wd_uri.value:
        s3_wd_uri = s3_wd_uri.value
        update_status_json(
            logger,
            task,
            run_id,
            s3_wd_uri,
            {"status": "running", "start_time": time.time()},
        )

    # First yield point -- through which we'll get the task inputs. Also, the 'task' object is a
    # WDL.Task through which we have access to the full AST of the task source code.
    #   https://miniwdl.readthedocs.io/en/latest/WDL.html#WDL.Tree.Task
    # pending proper documentation for this interface, see the detailed comments in this example:
    #   https://github.com/chanzuckerberg/miniwdl/blob/main/examples/plugin_task_omnibus/miniwdl_task_omnibus_example.py
    recv = yield recv

    # provide a callback for stderr log messages that attempts to parse them as JSON and pass them
    # on in structured form
    stderr_logger = logger.getChild("stderr")
    last_stderr_json = None

    def stderr_callback(line):
        nonlocal last_stderr_json
        line2 = line.strip()
        parsed = False
        if line2.startswith("{") and line2.endswith("}"):
            try:
                d = json.loads(line)
                assert isinstance(d, dict)
                msg = ""
                if "message" in d:
                    msg = d["message"]
                    del d["message"]
                elif "msg" in d:
                    msg = d["msg"]
                    del d["msg"]
                stderr_logger.verbose(_(msg.strip(), **d))
                last_stderr_json = d
                parsed = True
            except:
                pass
        if not parsed:
            stderr_logger.verbose(line.rstrip())

    recv["container"].stderr_callback = stderr_callback

    # pass through certain environment variables expected by idseq-dag
    recv["container"].create_service_kwargs = {
        "env": [f"{var}={os.environ[var]}" for var in PASSTHROUGH_ENV_VARS],
    }
    # inject command to log `aws sts get-caller-identity` to confirm AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
    # is passed through & effective
    if not run_id[-1].startswith("download-"):
        recv["command"] = (
            """aws sts get-caller-identity | jq -c '. + {message: "aws sts get-caller-identity"}' 1>&2\n\n"""
            + recv["command"]
        )

    try:
        recv = yield recv

        # After task completion -- logging elapsed time in structured form, to be picked up by
        # CloudWatch Logs. We also have access to the task outputs in recv.
        t_elapsed = time.time() - t_0
        logger.notice(
            _(
                "SFN-WDL task done",
                run_id=run_id[-1],
                task_name=task.name,
                elapsed_seconds=round(t_elapsed, 3),
            )
        )
    except Exception as exn:
        if s3_wd_uri:
            # read the error message to determine status user_errored or pipeline_errored
            status = "pipeline_errored"
            msg = str(exn)
            if last_stderr_json and "wdl_error_message" in last_stderr_json:
                msg = last_stderr_json.get("cause", last_stderr_json["wdl_error_message"])
                if last_stderr_json.get("error", None) == "InvalidInputFileError":
                    status = "user_errored"
            update_status_json(
                logger,
                task,
                run_id,
                s3_wd_uri,
                {"status": status, "error": msg, "end_time": time.time()},
            )
        raise

    if s3_wd_uri:
        update_status_json(
            logger,
            task,
            run_id,
            s3_wd_uri,
            {"status": "uploaded", "end_time": time.time()},
        )

    # do nothing with outputs
    yield recv


_status_json = {}
_status_json_lock = threading.Lock()


def update_status_json(logger, task, run_ids, s3_wd_uri, entries):
    """
    Post short-read-mngs workflow status JSON files to the output S3 bucket. These status files
    were originally created by idseq-dag, used to display pipeline progress in the IDseq webapp.
    We update it at the beginning and end of each task (carefully, because some tasks run
    concurrently).
    """
    global _status_json, _status_json_lock

    try:
        # Figure out workflow and step names:
        # e.g. run_ids = ["host_filter", "call-validate_input"]
        workflow_name = run_ids[0]
        if not s3_wd_uri or workflow_name not in (
            "idseq_host_filter",
            "idseq_non_host_alignment",
            "idseq_postprocess",
            "idseq_experimental",
        ):
            return
        workflow_name = workflow_name[6:]
        # parse --step-name from the task command template. For historical reasons, the status JSON
        # keys use this name and it's not the same as the WDL task name.
        step_name = None
        step_name_re = re.compile(r"--step-name\s+(\S+)\s")
        for part in task.command.parts:
            m = step_name_re.search(part) if isinstance(part, str) else None
            if m:
                step_name = m.group(1)
        assert step_name, "reading --step-name from task command"

        # Update _status_json which is accumulating over the course of workflow execution.
        with _status_json_lock:
            status = _status_json.setdefault(step_name, {})

            if "description" in task.meta:
                status["description"] = task["description"]
            status["resources"] = {
                "IDseq Docs": "https://github.com/chanzuckerberg/idseq-workflows"
            }
            for k, v in entries.items():
                status[k] = v

            # Upload it
            with tempfile.NamedTemporaryFile() as outfile:
                outfile.write(json.dumps(_status_json).encode())
                outfile.flush()
                cmd = [
                    "aws",
                    "s3",
                    "cp",
                    outfile.name,
                    os.path.join(s3_wd_uri, f"{workflow_name}_status_NEW.json"),
                ]
                logger.verbose(
                    _("update_status_json", step_name=step_name, status=status, cmd=" ".join(cmd))
                )
                try:
                    subprocess.run(cmd, capture_output=True, check=True)
                except subprocess.CalledProcessError as cpe:
                    logger.error(
                        _(
                            "update_status_json aws s3 cp failed",
                            exit_status=cpe.returncode,
                            cmd=" ".join(cmd),
                            stderr=cpe.stderr,
                        )
                    )
    except Exception as exn:
        logger.error(
            _("update_status_json failed", error=str(exn), s3_wd_uri=s3_wd_uri, run_ids=run_ids)
        )
        # Don't allow mere inability to update status to crash the whole workflow.
