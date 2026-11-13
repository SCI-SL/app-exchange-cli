from pathlib import Path

from setuptools import find_namespace_packages, setup

setup(
    name="cli-anything-slcool",
    version="1.0.1",
    description="SL Cool public gateway and stock-game command-line client",
    long_description=Path(__file__).with_name("README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    python_requires=">=3.10",
    packages=find_namespace_packages(include=["cli_anything.*"], exclude=["*.tests", "*.tests.*"]),
    install_requires=["click>=8.1,<9", "jsonschema>=4.18,<5", "prompt-toolkit>=3.0,<4"],
    extras_require={"test": ["pytest>=8,<10", "build>=1,<2", "ruff>=0.9"]},
    package_data={"cli_anything.slcool": ["data/*.json", "skills/*.md", "README.md", "THIRD_PARTY.md"]},
    entry_points={"console_scripts": [
        "cli-anything-slcool=cli_anything.slcool.slcool_cli:main",
        "sl-cool=cli_anything.slcool.slcool_cli:main",
    ]},
)
