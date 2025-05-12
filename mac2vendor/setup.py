from setuptools import setup, find_packages

# This enables shell completion for the mac2vendor command when installed with pipx
try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata

setup(
    name="mac2vendor",
    version="0.1.0",
    description="Look up vendor information from MAC addresses",
    author="Stephan",
    packages=find_packages(),
    py_modules=["mac2vendor"],
    install_requires=[
        "click>=8.1.8",
        "tqdm",
    ],
    entry_points={
        "console_scripts": [
            "mac2vendor=mac2vendor:mac2vendor",
        ],
    },
    # Add shell completion support
    options={
        'entry_points': {
            'pipx.run': [
                'mac2vendor=mac2vendor:mac2vendor',
            ],
        },
    },
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Utilities",
    ],
)
