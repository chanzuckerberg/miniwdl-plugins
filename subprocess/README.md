# miniwdl subprocess plugin
This miniwdl plugin implements a backend for executing WDL tasks on
the local system using subprocesses.

To configure miniwdl to use local processes:

1. Set the environment variable `MINIWDL__SCHEDULER__CONTAINER_BACKEND=subprocess` or the equivalent [configuration file](https://miniwdl.readthedocs.io/en/latest/runner_reference.html#configuration) option `[scheduler] container_backend=subprocess`
2. install aria2 using `apt-get install aria2` or `brew install aria2`
3. Test the configuration with `miniwdl run_self_test`
