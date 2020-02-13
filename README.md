# miniwdl-s3parcp

This Python package is a [MiniWDL](https://github.com/chanzuckerberg/miniwdl) plugin to handle S3 download (localization)
and upload (delocalization) tasks for S3 URIs in WDL workflow I/O.

## Installation
```
pip install miniwdl-s3parcp
```
To check that the installation was successful, run `miniwdl --version`, which will list available plugins, including this one.

## Usage
The plugin will automatically be used to handle `s3://bucket/key` URIs found in workflow inputs.
