#!/usr/bin/env python3
from setuptools import setup
from os import path

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(path.dirname(__file__), "README.md")) as f:
    long_description = f.read()

setup(
    name="sfnwdl-miniwdl-plugin",
    version="0.0.1",
    description="miniwdl plugin for IDseq SFN-WDL customizations",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Mike Lin, Andrey Kislyuk",
    py_modules=["sfnwdl_miniwdl_plugin"],
    python_requires=">=3.6",
    setup_requires=["reentry"],
    install_requires=["boto3"],
    reentry_register=True,
    entry_points={
        "miniwdl.plugin.task": ["sfnwdl_miniwdl_plugin_task = sfnwdl_miniwdl_plugin:task"]
    },
)
