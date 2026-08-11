from setuptools import setup, find_packages

setup(
    name="superinstance-conductor",
    version="0.1.0",
    description="Agent routing layer for multi-agent systems",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Lucineer / Casey DiGenaro",
    author_email="casey@superinstance.com",
    url="https://github.com/superinstance/conductor",
    license="MIT",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[],  # pure Python, no hard deps
    extras_require={
        "config": ["pyyaml>=6.0"],
        "dev": ["pytest>=7.0", "pyyaml>=6.0"],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
