from setuptools import setup

setup(
    name="miniwdl-s3parcp",
    version="0.0.2",
    description="miniwdl download plugin for s3:// using s3parcp",
    author="Mike Lin, Andrey Kislyuk",
    py_modules=["miniwdl_s3parcp"],
    python_requires=">=3.6",
    setup_requires=["reentry"],
    install_requires=["boto3"],
    reentry_register=True,
    entry_points={
        "miniwdl.plugin.file_download": ["s3 = miniwdl_s3parcp:main"],
    }
)
