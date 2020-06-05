"""
Plugin for uploading output files to S3 "progressively," meaning to upload each task's output files
immediately upon task completion, instead of waiting for the whole workflow to finish. (The latter
technique, which doesn't need a plugin at all, is illustrated in ../upload_output_files.sh)

To enable, install this plugin (`pip3 install .` & confirm listed by `miniwdl --version`) and set
the environment variable MINIWDL__S3_PROGRESSIVE_UPLOAD__URI_PREFIX to a S3 URI prefix under which
to store the output files (e.g. "s3://my_bucket/workflow123_outputs"). The prefix should be set
uniquely for each run, to prevent different runs from overwriting each others' outputs.

Shells out to the AWS CLI, which must be pre-configured so that "aws s3 cp ..." into the specified
bucket works (without explicit auth-related arguments).

Deposits into each successful task/workflow run directory and S3 folder, an additional file
outputs.s3.json which copies outputs.json replacing local file paths with the uploaded S3 URIs.
(The JSON printed to miniwdl standard output keeps local paths.)

Limitations:
1) All task output files are uploaded, even ones that aren't top-level workflow outputs. (We can't,
   at the moment of task completion, necessarily predict which files the calling workflow will
   finally output.)
2) Doesn't upload (or rewrite outputs JSON for) workflow output files that weren't generated by a
   task, e.g. outputting an input file, or a file generated by write_lines() etc. in the workflow.
   (We could handle such stragglers by uploading them at workflow completion; it just hasn't been
   needed yet.)
"""

import os
import subprocess
import threading
import json
import WDL
from WDL._util import StructuredLogMessage as _

_uploaded_files = {}
_uploaded_files_lock = threading.Lock()


def task(cfg, logger, run_id, run_dir, task, **recv):
    """
    on completion of any task, upload its output files to S3, and record the S3 URI corresponding
    to each local file (keyed by inode) in _uploaded_files
    """
    logger = logger.getChild("s3_progressive_upload")

    # ignore inputs
    recv = yield recv
    # ignore command/runtime/container
    recv = yield recv

    if not cfg.has_option("s3_progressive_upload", "uri_prefix"):
        logger.debug("skipping because MINIWDL__S3_PROGRESSIVE_UPLOAD__URI_PREFIX is unset")
    elif not run_id[-1].startswith("download-"):
        s3prefix = cfg["s3_progressive_upload"]["uri_prefix"]
        assert s3prefix.startswith("s3://"), "MINIWDL__S3_PROGRESSIVE_UPLOAD__URI_PREFIX invalid"

        # for each file under output_links
        def _raise(ex):
            raise ex

        links_dir = os.path.join(run_dir, "output_links")
        for (dn, subdirs, files) in os.walk(links_dir, onerror=_raise):
            assert dn == links_dir or dn.startswith(links_dir + "/")
            for fn in files:
                # upload to S3
                abs_fn = os.path.join(dn, fn)
                # s3uri = os.path.join(s3prefix, *run_id[1:], dn[(len(links_dir) + 1) :], fn)
                s3uri = os.path.join(s3prefix, os.path.basename(fn))
                s3cp(logger, abs_fn, s3uri)
                # record in _uploaded_files (keyed by inode, so that it can be found from any
                # symlink or hardlink)
                with _uploaded_files_lock:
                    _uploaded_files[inode(abs_fn)] = s3uri
                logger.info(_("task output uploaded", file=abs_fn, uri=s3uri))

        # write outputs_s3.json using _uploaded_files
        write_outputs_s3_json(
            logger, recv["outputs"], run_dir, os.path.join(s3prefix, *run_id[1:]), task.name
        )

    yield recv


def workflow(cfg, logger, run_id, run_dir, workflow, **recv):
    """
    on workflow completion, add a file outputs.s3.json to the run directory, which is outputs.json
    with local filenames rewritten to the uploaded S3 URIs (as previously recorded on completion of
    each task).
    """
    logger = logger.getChild("s3_progressive_upload")

    # ignore inputs
    recv = yield recv

    if cfg.has_option("s3_progressive_upload", "uri_prefix"):
        # write outputs.s3.json using _uploaded_files
        write_outputs_s3_json(
            logger,
            recv["outputs"],
            run_dir,
            os.path.join(cfg["s3_progressive_upload"]["uri_prefix"], *run_id[1:]),
            workflow.name,
        )

    yield recv


def write_outputs_s3_json(logger, outputs, run_dir, s3prefix, namespace):
    # rewrite uploaded files to their S3 URIs
    def rewriter(fn):
        try:
            return _uploaded_files[inode(fn)]
        except Exception:
            logger.warning(
                _(
                    "output file wasn't uploaded to S3; keeping local path in outputs.s3.json",
                    file=fn,
                )
            )
            return fn

    with _uploaded_files_lock:
        outputs_s3 = WDL.Value.rewrite_env_files(outputs, rewriter)

    # get json dict of rewritten outputs
    outputs_s3_json = WDL.values_to_json(outputs_s3, namespace=namespace)

    # write to outputs.s3.json
    fn = os.path.join(run_dir, "outputs.s3.json")
    with open(fn, "w") as outfile:
        json.dump(outputs_s3_json, outfile, indent=2)
        outfile.write("\n")
    s3cp(logger, fn, os.environ.get("WDL_OUTPUT_URI", os.path.join(s3prefix, "outputs.s3.json")))


_s3parcp_lock = threading.Lock()


def s3cp(logger, fn, s3uri):
    with _s3parcp_lock:
        cmd = ["s3parcp", fn, s3uri]
        logger.debug(" ".join(cmd))
        rslt = subprocess.run(cmd, stderr=subprocess.PIPE)
        if rslt.returncode != 0:
            logger.error(
                _(
                    "failed uploading output file",
                    cmd=" ".join(cmd),
                    exit_status=rslt.returncode,
                    stderr=rslt.stderr.decode("utf-8"),
                )
            )
            raise WDL.Error.RuntimeError("failed: " + " ".join(cmd))


def inode(link):
    st = os.stat(os.path.realpath(link))
    return (st.st_dev, st.st_ino)
