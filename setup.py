from setuptools import setup, find_packages
import os
import re

# Read version from __init__.py
with open(os.path.join("ryanair", "__init__.py"), "r", encoding="utf-8") as f:
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", f.read(), re.M)
    version = version_match.group(1)

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="ryanair",
    version=version,
    author="Alessio",
    author_email="alessiovecchi00@gmail.com",
    description="Python Package to manage and retrieve information about Ryanair flights and fares",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/aleve99/ryanair",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.10",
    install_requires=[
        "aiohttp>=3.11.14",
        "tomli>=2.0.1;python_version<'3.11'",
        "xxhash>=3.6.0",
    ],
) 