"""Compatibility shim for older pip/setuptools installations."""
from setuptools import find_packages, setup

setup(
    name="blend-farm",
    version="0.1.0",
    description="A small, self-hosted Blender render farm",
    package_dir={"": "src"},
    packages=find_packages("src"),
    include_package_data=True,
    package_data={"renderfarm": ["templates/*.html", "static/*"]},
    python_requires=">=3.10",
    install_requires=[
        "fastapi>=0.110,<1", "uvicorn[standard]>=0.29,<1", "sqlalchemy>=2.0,<3",
        "jinja2>=3.1,<4", "python-multipart>=0.0.9,<1", "argon2-cffi>=23.1,<26",
        "itsdangerous>=2.1,<3", "boto3>=1.34,<2", "httpx>=0.27,<1", "platformdirs>=4.2,<5",
    ],
    entry_points={"console_scripts": [
        "blend-farm-server=renderfarm.app:run",
        "blend-farm-worker=renderfarm.worker:main",
    ]},
)
