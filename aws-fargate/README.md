# miniwdl AWS Fargate plugin
This miniwdl plugin implements a container backend for executing WDL tasks on
[AWS Fargate](https://aws.amazon.com/fargate/) containers.

The [ECS RunTask](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_RunTask.html) API is used to launch the
tasks. The [aegea](https://github.com/kislyuk/aegea) package is used to automatically provision, configure, and operate
an ECS cluster.

When used via ECS RunTask, AWS Fargate provides fast (approx. 10 second) container provisioning latencies, which allows
you to maintain zero-cost idle capacity in your AWS account while being able to quickly burst scale to high capacity
when load arrives.

## CPU and memory limits
AWS Fargate has relatively low
[task CPU and memory limits](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html). At most 4
vCPUs and at most 30 GB of memory can be provisioned per task container.

To configure the default Fargate CPU and memory size when WDL tasks don't specify one, set the `aws_fargate.default_cpu_shares`
and `aws_fargate.default_memory_mb` configuration parameters, for example by running:

```
export MINIWDL__AWS_FARGATE__DEFAULT_CPU_SHARES=4096
export MINIWDL__AWS_FARGATE__DEFAULT_MEMORY_MB=30720
```

## Configuring EFS
[AWS EFS](https://aws.amazon.com/efs/) is used for WDL task I/O. The machine running miniwdl launches one AWS Fargate
task and container for each WDL task. The machine running miniwdl and the task container must both have access to a
pre-created EFS filesystem. You can create a new EFS filesystem in the
[AWS Console](https://console.aws.amazon.com/efs). After creating, set the `aws_fargate.efs_id`,
`aws_fargate.efs_mountpoint`, and `aws_fargate.efs_security_group` miniwdl configuration parameters, for example by running:

```
export MINIWDL__AWS_FARGATE__EFS_ID=fs-12345678
export MINIWDL__AWS_FARGATE__EFS_MOUNTPOINT=/mnt/efs
export MINIWDL__AWS_FARGATE__EFS_SECURITY_GROUP=my-security-group
```

See https://docs.aws.amazon.com/efs/latest/ug/accessing-fs-create-security-groups.html for security group configuration details.

It is expected that the the miniwdl working directory will reside on the EFS filesystem (if not, miniwdl will attempt to mount
the EFS filesystem, and raise an error if that fails). The task container on Fargate is configured to mount the task-specific
working directory. For example, if you are running in the us-west-2 AWS region, call `miniwdl run my.wdl` in
`/var/run/miniwdl`, and set `aws_fargate.efs_id=fs-12345678`:

* miniwdl will expect `fs-12345678.efs.us-west-2.amazonaws.com:/` to be mounted on `/var/run/miniwdl` (or `/var/run` or `/var`)
* miniwdl will create a task working directory which looks like this: `/var/run/miniwdl/20200202_123456_my`
* miniwdl will configure the Fargate task to mount `fs-12345678.efs.us-west-2.amazonaws.com:/20200202_123456_my` on
  `/mnt/miniwdl_task_container`
* miniwdl will run the Fargate container with the default security group, `aegea.efs`
