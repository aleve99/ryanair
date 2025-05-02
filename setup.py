from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="ryanair",
    version="0.2.2",
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
    ],
) 