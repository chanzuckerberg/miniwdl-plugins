import os
import json
import time
import WDL
from WDL._util import StructuredLogMessage as _


# environment variables to be passed through from miniwdl runner environment to task containers
PASSTHROUGH_ENV_VARS = (
    "AWS_DEFAULT_REGION",
    "DEPLOYMENT_ENVIRONMENT",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
)


def task(cfg, logger, run_id, run_dir, task, **recv):
    t_0 = time.time()

    # First yield point -- through which we'll get the task inputs. Also, the 'task' object is a
    # WDL.Task through which we have access to the full AST of the task source code.
    #   https://miniwdl.readthedocs.io/en/latest/WDL.html#WDL.Tree.Task
    # pending proper documentation for this interface, see the detailed comments in this example:
    #   https://github.com/chanzuckerberg/miniwdl/blob/main/examples/plugin_task_omnibus/miniwdl_task_omnibus_example.py
    recv = yield recv

    # provide a callback for stderr log messages that attempts to parse them as JSON and pass them
    # on in structured form
    stderr_logger = logger.getChild("stderr")

    def stderr_callback(line):
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

    # do nothing with outputs
    yield recv
