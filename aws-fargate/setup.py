#!/usr/bin/env python3
from setuptools import setup
from os import path

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(path.dirname(__file__), "README.md")) as f:
    long_description = f.read()

setup(
    name="aws-fargate-miniwdl-plugin",
    version="0.0.1",
    description="miniwdl plugin for running task containers on AWS Fargate with EFS",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Andrey Kislyuk",
    py_modules=["miniwdl_aws_fargate"],
    python_requires=">=3.6",
    setup_requires=["reentry"],
    install_requires=["aegea >= 3.6.43"],
    reentry_register=True,
    entry_points={
        "miniwdl.plugin.container_backend": ["aws_fargate = miniwdl_aws_fargate:AWSFargateContainer"]
    },
)
