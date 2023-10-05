#!/usr/bin/env python3
from setuptools import setup
from os import path

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(path.dirname(__file__), "README.md")) as f:
    long_description = f.read()

setup(
    name="local-miniwdl-plugin",
    version="0.0.1",
    description="miniwdl plugin for running tasks locally without using containers",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Bernd Höhl",
    py_modules=["miniwdl_subprocess"],
    python_requires=">=3.6",
    setup_requires=["reentry"],
    install_requires=[],
    reentry_register=True,
    entry_points={
        "miniwdl.plugin.container_backend": ["subprocess = miniwdl_subprocess:LocalSubprocess"]
    },
)
