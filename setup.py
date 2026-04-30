from __future__ import annotations

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [
            item
            for item in modules
            if not (item[0] == "sci_fi_dashboard" and item[1].startswith("test_"))
        ]


setup(cmdclass={"build_py": build_py})
